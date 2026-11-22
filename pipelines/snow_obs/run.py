"""Observed snow cover for every Sentinel-2 date ingested by pipelines.s2.ingest.

    python -m pipelines.snow_obs.run --domain data/domain.geojson --s2 work/s2 --start 2026-11-01 \
        --end 2026-11-21 --out work/snow_obs [--static-cache work/static] [--publish staging]

For each date it takes the complete pass with the highest domain valid fraction, classifies it
(pipelines.snow_obs.classify) and writes <out>/<date>/ with snow_obs.tif (bands class, confidence,
flags; 255 outside the domain), display.tif (RGBA) and summary.json. A date is published when
its pass is complete and at least 30% of the domain is observed (snow or no snow), counted after
the bright-snow correction, so a clear snowy date Sen2Cor calls cloudy is not dropped.
"""

import argparse
import json
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from pipelines.s2.domain import Domain, Grid, load_domain
from pipelines.s2.stac import COLLECTION, Fetch, fetch_json

from . import classify as c
from .terrain import load_static, terrain_shadow

ITEM_URL = "https://earth-search.aws.element84.com/v1/collections/{collection}/items/{id}"
LAYER = "snow_obs"
BANDS = ["class", "confidence", "flags"]
UNITS = ["class", "class", "bitmask"]
VALUE_RANGE = [[0, 3], [0, 2], [0, 15]]
# README D1: an S2 date is listed when the domain is at least 30% covered and valid.
MIN_PUBLISHED_OBSERVED_FRACTION = 0.30

# Colours of the observed snow ramp in docs/design/ramps.json (cmocean "ice", Thyng et al. 2016,
# doi:10.5670/oceanog.2016.66) as RGBA. Cloud dots and the unknown hatch are drawn one map pixel
# wide every PATTERN_PERIOD pixels.
SNOW_RGBA = (0x3E, 0x48, 0x91, 230)
SNOW_LOW_CONFIDENCE_RGBA = (0x52, 0x96, 0xC1, 204)
CLOUD_RGBA = (0xF4, 0xF2, 0xEE, 204)
CLOUD_DOT_RGBA = (0x6E, 0x6A, 0x63, 204)
UNKNOWN_HATCH_RGBA = (0x2E, 0x33, 0x3B, 179)
PATTERN_PERIOD = 3


def pick_record(records: list[dict]) -> dict | None:
    """The complete pass of a date with the highest domain valid fraction (passes are never blended)."""
    complete = [record for record in records if record["complete"]]
    if not complete:
        return None
    return max(complete, key=lambda r: (r["domain_valid_fraction"], r["domain_coverage"], r["orbit"]))


def sun_angles(scene_ids: list[str], fetch: Fetch = fetch_json) -> tuple[float, float]:
    """Mean sun azimuth and elevation (degrees) of the granules. Across the four tiles of one pass
    they differ by about a degree, below the 20 m DEM's ability to place a shadow edge."""
    azimuths, elevations = [], []
    for scene_id in scene_ids:
        request = urllib.request.Request(ITEM_URL.format(collection=COLLECTION, id=scene_id))
        properties = fetch(request)["properties"]
        azimuths.append(float(properties["view:sun_azimuth"]))
        elevations.append(float(properties["view:sun_elevation"]))
    return float(np.mean(azimuths)), float(np.mean(elevations))


def read_pass(folder: Path) -> tuple[dict[str, np.ndarray], np.ndarray]:
    import rasterio

    with rasterio.open(folder / "reflectance.tif") as source:
        reflectance = {name: source.read(band) for band, name in enumerate(source.descriptions, start=1)}
    with rasterio.open(folder / "classes.tif") as source:
        scl = source.read(1)
    return reflectance, scl


def display_rgba(result: c.Classification) -> np.ndarray:
    rows, cols = np.indices(result.classes.shape)
    rgba = np.zeros((4, *result.classes.shape), dtype="uint8")

    def paint(where: np.ndarray, colour: tuple[int, int, int, int]) -> None:
        for band, value in enumerate(colour):
            rgba[band][where] = value

    snow = result.classes == c.SNOW
    paint(snow & (result.confidence == c.CONFIDENCE_HIGH), SNOW_RGBA)
    paint(snow & (result.confidence == c.CONFIDENCE_LOW), SNOW_LOW_CONFIDENCE_RGBA)
    cloud = result.classes == c.CLOUD
    paint(cloud, CLOUD_RGBA)
    paint(cloud & (rows % PATTERN_PERIOD == 0) & (cols % PATTERN_PERIOD == 0), CLOUD_DOT_RGBA)
    paint((result.classes == c.UNKNOWN) & ((rows + cols) % PATTERN_PERIOD == 0), UNKNOWN_HATCH_RGBA)
    return rgba


def write_rasters(folder: Path, grid: Grid, result: c.Classification) -> tuple[Path, Path]:
    import rasterio

    profile = {
        "driver": "GTiff",
        "width": grid.width,
        "height": grid.height,
        "crs": grid.crs,
        "transform": grid.transform,
        "dtype": "uint8",
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "compress": "deflate",
    }
    data_path, display_path = folder / "snow_obs.tif", folder / "display.tif"
    with rasterio.open(data_path, "w", count=3, nodata=c.NODATA, **profile) as target:
        for band, (name, array) in enumerate(
            zip(BANDS, (result.classes, result.confidence, result.flags)), start=1
        ):
            target.write(array, band)
            target.set_band_description(band, name)
    with rasterio.open(display_path, "w", count=4, photometric="RGB", alpha="YES", **profile) as target:
        target.write(display_rgba(result))
    return data_path, display_path


def summarise(record: dict, result: c.Classification, inside: np.ndarray, sun: tuple[float, float]) -> dict:
    total = int(inside.sum())
    counts = {
        name: int(np.count_nonzero(result.classes[inside] == code))
        for name, code in (("no_snow", c.NO_SNOW), ("snow", c.SNOW), ("cloud", c.CLOUD), ("unknown", c.UNKNOWN))
    }
    flags = result.flags[inside]
    observed = (counts["snow"] + counts["no_snow"]) / total
    return {
        "date": record["date"],
        "orbit": record["orbit"],
        "datatake": record["datatake"],
        "scene_ids": record["scene_ids"],
        "processing_baselines": record["processing_baselines"],
        "s2_input_key": record["input_key"],
        "ingest_listed": record["listed"],
        "ingest_valid_fraction": record["domain_valid_fraction"],
        "sun_azimuth_deg": round(sun[0], 3),
        "sun_elevation_deg": round(sun[1], 3),
        "snowline_m": result.snowline_m,
        "domain_pixels": total,
        "counts": counts,
        "observed_fraction": round(observed, 4),
        "snow_fraction_of_observed": round(counts["snow"] / max(1, counts["snow"] + counts["no_snow"]), 4),
        "bright_snow_pixels": int(np.count_nonzero(flags & c.FLAG_BRIGHT_SNOW)),
        "pass2_snow_pixels": int(np.count_nonzero(flags & c.FLAG_PASS2)),
        "published": bool(observed >= MIN_PUBLISHED_OBSERVED_FRACTION),
    }


def process(
    record: dict, pass_folder: Path, domain: Domain, elevation: np.ndarray, forest: np.ndarray, out: Path,
    fetch: Fetch = fetch_json,
) -> dict:
    reflectance, scl = read_pass(pass_folder)
    sun = sun_angles(record["scene_ids"], fetch)
    scene = c.Scene(
        green=reflectance["green"],
        red=reflectance["red"],
        swir16=reflectance["swir16"],
        scl=scl,
        elevation=elevation,
        terrain_shadow=terrain_shadow(elevation, domain.grid.resolution, *sun),
        forest=forest,
        inside=domain.mask,
    )
    result = c.classify(scene)
    folder = out / record["date"]
    folder.mkdir(parents=True, exist_ok=True)
    write_rasters(folder, domain.grid, result)
    summary = summarise(record, result, domain.mask, sun)
    (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def publish_date(folder: Path, summary: dict, target: str, version: str) -> dict[str, Any]:
    from pipelines.catalog import publish, storage_from_env

    scores = {
        "observed_fraction": summary["observed_fraction"],
        "snow_fraction_of_observed": summary["snow_fraction_of_observed"],
        "cloud_fraction": round(summary["counts"]["cloud"] / summary["domain_pixels"], 4),
        "unknown_fraction": round(summary["counts"]["unknown"] / summary["domain_pixels"], 4),
        "sun_elevation_deg": summary["sun_elevation_deg"],
    }
    if summary["snowline_m"] is not None:
        scores["snowline_m"] = summary["snowline_m"]
    flags = [] if summary["ingest_listed"] else ["listed_after_bright_snow_correction"]
    meta = {
        "source_ids": summary["scene_ids"],
        "processing_baseline": ",".join(sorted(set(summary["processing_baselines"]))),
        "bands": BANDS,
        "units": UNITS,
        "value_range": VALUE_RANGE,
        "code_version": version,
        "qa": {"flags": flags, "scores": scores},
    }
    files = {"data": folder / "snow_obs.tif", "display": folder / "display.tif"}
    return publish(LAYER, summary["date"], files, meta, storage_from_env(target))


def run(
    domain_path: Path, s2: Path, start: date, end: date, out: Path, static_cache: Path | None = None,
    target: str | None = None, version: str | None = None, fetch: Fetch = fetch_json,
) -> list[dict]:
    domain = load_domain(domain_path)
    elevation, forest = load_static(domain.grid, static_cache)
    if target is not None and version is None:
        from pipelines.catalog import code_version

        version = code_version()
    summaries = []
    day = start
    while day <= end:
        paths = sorted((s2 / day.isoformat()).glob("*/record.json"))
        records = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
        record = pick_record(records)
        day += timedelta(days=1)
        if record is None:
            continue
        summary = process(record, s2 / record["date"] / record["orbit"], domain, elevation, forest, out, fetch)
        if target is not None and version is not None and summary["published"]:
            entry = publish_date(out / record["date"], summary, target, version)
            summary["entry"] = {"cog": entry["cog"], "pixel_hash": entry["pixel_hash"]}
        summaries.append(summary)
    return summaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--domain", type=Path, required=True, help="GeoJSON of the domain polygons (EPSG:4326)")
    parser.add_argument("--s2", type=Path, required=True, help="output folder of pipelines.s2.ingest")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--static-cache", type=Path, help="folder to keep the DEM and forest grids between runs")
    parser.add_argument("--publish", choices=("staging", "prod"), help="publish dates that pass the listing rule")
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error("--end is before --start")
    for summary in run(args.domain, args.s2, args.start, args.end, args.out, args.static_cache, args.publish):
        counts = summary["counts"]
        print(
            f"{summary['date']} {summary['orbit']} observed={summary['observed_fraction']:.4f} "
            f"snow={counts['snow']} no_snow={counts['no_snow']} cloud={counts['cloud']} "
            f"unknown={counts['unknown']} snowline={summary['snowline_m']} published={summary['published']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
