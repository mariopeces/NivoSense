"""Gap-filled snow cover for every day of a range, from the snow_obs entries of a catalogue.

    python -m pipelines.snow_gapfill.run --target staging --start 2025-10-01 --end 2026-11-21 \
        --out work/gapfill [--static-cache work/static] [--publish]

Reads the snow_obs entries within LOOKAROUND_DAYS of the range from `catalog/index.json` of the
target, fills each day (pipelines.snow_gapfill.fill) and writes <out>/<date>/ with
snow_gapfill.tif (bands probability, snow, days_since, method; -1 is nodata) and display.tif.
With --publish each day goes through the catalogue. A day after the last observation is
flagged `extrapolated` in its entry. A day before the first observation has no age to report and
is refused: ingest and classify earlier dates first.
"""

import argparse
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from pipelines.catalog.storage import Storage
from pipelines.s2.domain import Grid
from pipelines.snow_obs import classify as observed_classes
from pipelines.snow_obs.terrain import load_static, slope_aspect

from . import fill as f

LAYER = "snow_gapfill"
OBSERVED_LAYER = "snow_obs"
BANDS = ["probability", "snow", "days_since", "method"]
UNITS = ["probability", "class", "days", "class"]
INDEX_KEY = "catalog/index.json"
# Observations further than this from the range are not read. A pixel unobserved for longer
# falls back to the snowline of the nearest dates, which this window always holds.
LOOKAROUND_DAYS = 120
SKI_RESORT = Path(__file__).resolve().parents[2] / "data" / "ski_resort.geojson"
PIXEL_KM2 = 0.0004

# docs/design/ramps.json "snow_cover_probability" (cmocean "ice", Thyng et al. 2016,
# doi:10.5670/oceanog.2016.66): lower bound of each class and its RGBA; under 0.1 is transparent.
PROBABILITY_RAMP = (
    (0.1, (0xA8, 0xDA, 0xDE, 115)),
    (0.3, (0x76, 0xBB, 0xCF, 153)),
    (0.5, (0x52, 0x96, 0xC1, 204)),
    (0.7, (0x3F, 0x6F, 0xB3, 217)),
    (0.9, (0x3E, 0x48, 0x91, 230)),
)


def read_index(storage: Storage) -> dict[str, Any]:
    blob = storage.read(INDEX_KEY)
    if blob is None:
        raise FileNotFoundError(f"{INDEX_KEY} not found in {storage}")
    index: dict[str, Any] = json.loads(blob.data)
    return index


def load_observations(
    storage: Storage, start: date, end: date, lookaround: int = LOOKAROUND_DAYS
) -> tuple[list[f.Observation], Grid]:
    """The snow_obs class band of every entry within `lookaround` days of [start, end], sorted by date."""
    import rasterio

    entries = read_index(storage).get("layers", {}).get(OBSERVED_LAYER, {}).get("entries", [])
    low, high = start - timedelta(days=lookaround), end + timedelta(days=lookaround)
    wanted = [e for e in entries if low <= date.fromisoformat(e["date"]) <= high]
    if not wanted:
        raise ValueError(f"no {OBSERVED_LAYER} entry between {low} and {high}")
    observations, grid = [], None
    with tempfile.TemporaryDirectory(prefix="gapfill-") as tmp:
        for entry in sorted(wanted, key=lambda e: e["date"]):
            blob = storage.read(entry["cog"])
            if blob is None:
                raise FileNotFoundError(f"{entry['cog']} is listed but missing")
            path = Path(tmp) / "obs.tif"
            path.write_bytes(blob.data)
            with rasterio.open(path) as src:
                classes = src.read(entry["bands"].index("class") + 1)
                this = Grid(src.crs.to_string(), src.transform.c, src.transform.f, src.res[0], src.width, src.height)
            if grid is None:
                grid = this
            elif this != grid:
                raise ValueError(f"{entry['cog']} is on {this}, not on {grid}")
            observations.append(f.Observation(date.fromisoformat(entry["date"]), classes, entry["cog"]))
    assert grid is not None
    return observations, grid


def ski_resort_mask(grid: Grid, path: Path = SKI_RESORT) -> np.ndarray:
    from rasterio.features import rasterize
    from rasterio.warp import transform_geom

    collection = json.loads(path.read_text(encoding="utf-8"))
    shapes = [transform_geom("EPSG:4326", grid.crs, feature["geometry"]) for feature in collection["features"]]
    mask: np.ndarray = rasterize(
        shapes, out_shape=(grid.height, grid.width), transform=grid.transform, all_touched=True, default_value=1
    ).astype(bool)
    return mask


def build_terrain(grid: Grid, inside: np.ndarray, static_cache: Path | None) -> f.Terrain:
    elevation, _ = load_static(grid, static_cache)
    slope, aspect = slope_aspect(elevation, grid.resolution)
    return f.Terrain(elevation, f.terrain_groups(slope, aspect), inside, inside & ~ski_resort_mask(grid))


def display_rgba(probability: np.ndarray) -> np.ndarray:
    rgba = np.zeros((4, *probability.shape), dtype="uint8")
    for low, colour in PROBABILITY_RAMP:
        where = probability >= low
        for band, value in enumerate(colour):
            rgba[band][where] = value
    return rgba


def write_rasters(folder: Path, grid: Grid, filled: f.Filled) -> tuple[Path, Path]:
    import rasterio

    profile = {
        "driver": "GTiff",
        "width": grid.width,
        "height": grid.height,
        "crs": grid.crs,
        "transform": grid.transform,
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "compress": "deflate",
    }
    nodata = filled.probability < 0
    snow = np.where(nodata, f.NODATA, filled.snow.astype("float32"))
    method = np.where(nodata, f.NODATA, filled.method.astype("float32"))
    data_path, display_path = folder / "snow_gapfill.tif", folder / "display.tif"
    with rasterio.open(data_path, "w", count=4, dtype="float32", nodata=f.NODATA, **profile) as target:
        for band, (name, array) in enumerate(
            zip(BANDS, (filled.probability, snow, filled.days_since, method)), start=1
        ):
            target.write(array.astype("float32"), band)
            target.set_band_description(band, name)
    with rasterio.open(display_path, "w", count=4, dtype="uint8", photometric="RGB", alpha="YES", **profile) as target:
        target.write(display_rgba(filled.probability))
    return data_path, display_path


def summarise(day: date, filled: f.Filled, observations: list[f.Observation], inside: np.ndarray) -> dict[str, Any]:
    valid = inside & (filled.probability >= 0)
    total = int(inside.sum())
    latest = observations[-1].day
    methods = {
        name: round(int(np.count_nonzero(valid & (filled.method == code))) / total, 4)
        for name, code in (
            ("observed", f.OBSERVED),
            ("bracketed", f.BRACKETED),
            ("snowline_between", f.SNOWLINE_BETWEEN),
            ("snowline_no_next", f.SNOWLINE_NO_NEXT),
            ("snowline_no_last", f.SNOWLINE_NO_LAST),
        )
    }
    flags = []
    if day > latest:
        flags.append("extrapolated")
    days_since = filled.days_since[valid & (filled.days_since >= 0)]
    return {
        "date": day.isoformat(),
        "snow_area_km2": round(int(np.count_nonzero(filled.snow & valid)) * PIXEL_KM2, 2),
        "valid_fraction": round(int(valid.sum()) / total, 4),
        "method_fractions": methods,
        "median_days_since": float(np.median(days_since)) if days_since.size else None,
        "latest_observation": latest.isoformat(),
        "days_after_latest_observation": max(0, (day - latest).days),
        "flags": flags,
        "sources": sorted(filled.sources),
    }


def publish_day(folder: Path, summary: dict[str, Any], storage: Storage, version: str) -> dict[str, Any]:
    from pipelines.catalog import publish

    scores: dict[str, float] = {
        "snow_area_km2": summary["snow_area_km2"],
        "valid_fraction": summary["valid_fraction"],
        "days_after_latest_observation": summary["days_after_latest_observation"],
        **{f"fraction_{name}": value for name, value in summary["method_fractions"].items()},
    }
    meta = {
        "source_ids": summary["sources"],
        "bands": BANDS,
        "units": UNITS,
        "value_range": [[0, 1], [0, 1], [0, 3660], [0, 4]],
        "code_version": version,
        "qa": {"flags": summary["flags"], "scores": scores},
    }
    files = {"data": folder / "snow_gapfill.tif", "display": folder / "display.tif"}
    return publish(LAYER, summary["date"], files, meta, storage)


def run(
    storage: Storage, start: date, end: date, out: Path, static_cache: Path | None = None,
    publish: bool = False, version: str | None = None,
) -> list[dict[str, Any]]:
    observations, grid = load_observations(storage, start, end)
    if start < observations[0].day:
        raise ValueError(f"no {OBSERVED_LAYER} entry on or before {start}; the first is {observations[0].day}")
    inside = observations[0].classes != observed_classes.NODATA
    terrain = build_terrain(grid, inside, static_cache)
    table = f.snowline_table(observations, [f.fit_snowline(o.classes, terrain) for o in observations])
    if publish and version is None:
        from pipelines.catalog import code_version

        version = code_version()
    summaries = []
    day = start
    while day <= end:
        filled = f.fill(day, observations, table, terrain)
        folder = out / day.isoformat()
        folder.mkdir(parents=True, exist_ok=True)
        write_rasters(folder, grid, filled)
        summary = summarise(day, filled, observations, inside)
        if publish and version is not None:
            entry = publish_day(folder, summary, storage, version)
            summary["entry"] = {"cog": entry["cog"], "pixel_hash": entry["pixel_hash"]}
        (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        summaries.append(summary)
        day += timedelta(days=1)
    return summaries


def main(argv: list[str] | None = None) -> int:
    from pipelines.catalog import storage_from_env

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", choices=("staging", "prod"), required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--static-cache", type=Path, help="folder to keep the DEM grid between runs")
    parser.add_argument("--publish", action="store_true", help="publish every day to the target catalogue")
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error("--end is before --start")
    storage = storage_from_env(args.target)
    for summary in run(storage, args.start, args.end, args.out, args.static_cache, args.publish):
        print(
            f"{summary['date']} snow={summary['snow_area_km2']} km2 valid={summary['valid_fraction']} "
            f"observed={summary['method_fractions']['observed']} flags={','.join(summary['flags']) or '-'}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
