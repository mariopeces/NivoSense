"""True colour RGB from Sentinel-2 L1C for every listed observation date, published through the
catalogue as layer `rgb`.

    python -m pipelines.rgb_l1c.run --s2 work/s2 --domain data/domain.geojson \\
        --start 2026-10-01 --end 2026-11-21 --target staging [--source aws]

The observation dates come from the records of pipelines.s2 in --s2 (records with `listed`
true; when two orbits of one date are listed, the one with the larger valid fraction). For each,
the L1C granules of the record's datatake are read, mosaicked, cropped to the domain, stretched
and published. A date without L1C on Earth Search is logged and skipped.
--source picks how the JP2 files are reached: `aws` (default, unsigned), or the fallbacks
`aws-requester-pays` and `cdse`, which need credentials in the environment and have not been
run against those services yet.
"""

import argparse
import json
import logging
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import numpy as np

from pipelines.catalog import code_version, publish, storage_from_env
from pipelines.catalog.storage import Storage
from pipelines.s2.domain import Domain, Grid, convex_hull, load_domain

from . import qa
from .render import NODATA, domain_mask, grid_10m, read_reflectance, render
from .source import AWS, SOURCES, find_acquisition

LAYER = "rgb"
# Accept line of the layer: fewer than 1% of snow pixels at 255.
MAX_SNOW_SATURATED = 0.01

log = logging.getLogger("rgb_l1c")


def observation_dates(s2_out: Path, start: date, end: date) -> list[dict]:
    """One record per listed date in [start, end]: the orbit with the largest valid fraction."""
    best: dict[str, dict] = {}
    for path in sorted(s2_out.glob("*/*/record.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if not record["listed"] or not start <= date.fromisoformat(record["date"]) <= end:
            continue
        current = best.get(record["date"])
        if current is None or record["domain_valid_fraction"] > current["domain_valid_fraction"]:
            best[record["date"]] = record
    return [best[day] for day in sorted(best)]


def write_rasters(rgb: np.ndarray, grid: Grid, folder: Path) -> dict[str, Path]:
    """The data GeoTIFF (3-band RGB, nodata 0) and the display GeoTIFF (RGBA, alpha 0 on nodata)."""
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
    paths = {"data": folder / "rgb.tif", "display": folder / "rgba.tif"}
    with rasterio.open(paths["data"], "w", count=3, nodata=NODATA, photometric="RGB", **profile) as target:
        target.write(rgb)
        for band, name in enumerate(("red", "green", "blue"), start=1):
            target.set_band_description(band, name)
    alpha = np.where((rgb != NODATA).all(axis=0), 255, 0).astype("uint8")
    with rasterio.open(paths["display"], "w", count=4, **profile) as target:
        target.write(rgb, (1, 2, 3))
        target.write(alpha, 4)
    return paths


def qa_flags(scores: dict[str, float], missing_tiles: list[str]) -> list[str]:
    flags = []
    if missing_tiles:
        flags.append("l1c_tiles_missing")
    if max(scores.get(f"snow_saturated_{band}", 0.0) for band in ("red", "green", "blue")) >= MAX_SNOW_SATURATED:
        flags.append("snow_saturated")
    if not scores.get("shift_l2a_green_chips"):
        # No chip was clear and textured enough to correlate (a cloudy date): not checked,
        # which must not read as aligned.
        flags.append("alignment_unchecked")
    elif scores["shift_l2a_green_median_m"] >= qa.ALIGNED_M:
        flags.append("misaligned")
    return flags


def process(
    record: dict,
    domain: Domain,
    hull: dict,
    inside: np.ndarray,
    s2_out: Path,
    storage: Storage,
    source: str,
) -> dict:
    """Build and publish the RGB of one observation record; returns a summary line."""
    day, orbit = date.fromisoformat(record["date"]), record["orbit"]
    summary: dict = {"date": record["date"], "orbit": orbit}
    started = time.monotonic()
    acquisition = find_acquisition(hull, day, record["datatake"], domain.touches)
    summary["search_s"] = round(time.monotonic() - started, 1)
    if acquisition is None:
        log.warning(
            "%s %s: no L1C granule of datatake %s on Earth Search; no RGB for this date",
            record["date"],
            orbit,
            record["datatake"],
        )
        return {**summary, "status": "l1c_missing"}
    missing = sorted(set(record["tiles"]) - set(acquisition.tiles))
    if missing:
        log.warning("%s %s: L1C lacks tiles %s that L2A has", record["date"], orbit, ",".join(missing))

    grid = grid_10m(domain.grid)
    mark = time.monotonic()
    reflectance = read_reflectance(acquisition, grid, source)
    summary["read_s"] = round(time.monotonic() - mark, 1)
    rgb = render(reflectance, inside)
    del reflectance

    l2a, scl = qa.read_l2a(s2_out / record["date"] / orbit)
    snow = qa.snow_mask(l2a, scl) & domain.mask
    scores = {**qa.snow_saturation(rgb, snow), **qa.alignment(rgb, l2a, snow, domain.grid.resolution)}
    flags = qa_flags(scores, missing)
    if flags:
        log.warning("%s: QA flags %s; scores %s", record["date"], flags, json.dumps(scores))

    mark = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="rgb-l1c-") as tmp:
        files = write_rasters(rgb, grid, Path(tmp))
        entry = publish(
            LAYER,
            record["date"],
            files,
            {
                "source_ids": list(acquisition.scene_ids),
                "bands": ["red", "green", "blue"],
                "units": ["1", "1", "1"],
                "value_range": [[1, 255]] * 3,
                "code_version": code_version(),
                "processing_baseline": ",".join(
                    sorted({item["properties"]["s2:processing_baseline"] for item in acquisition.items})
                ),
                "qa": {"flags": flags, "scores": scores},
            },
            storage,
        )
    summary["publish_s"] = round(time.monotonic() - mark, 1)
    summary["total_s"] = round(time.monotonic() - started, 1)
    return {
        **summary,
        "status": "published",
        "tiles": list(acquisition.tiles),
        "l1c_missing_tiles": missing,
        "source_ids": list(acquisition.scene_ids),
        "cog": entry["cog"],
        "qa": entry["qa"],
    }


def run(s2_out: Path, domain_path: Path, start: date, end: date, storage: Storage, source: str = AWS) -> list[dict]:
    domain = load_domain(domain_path)
    hull = convex_hull(domain.geometries)
    inside = domain_mask(domain.geometries, grid_10m(domain.grid))
    results = []
    for record in observation_dates(s2_out, start, end):
        result = process(record, domain, hull, inside, s2_out, storage, source)
        log.info(json.dumps(result))
        results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--s2", type=Path, required=True, help="output folder of pipelines.s2.ingest")
    parser.add_argument("--domain", type=Path, required=True, help="GeoJSON of the domain polygons (EPSG:4326)")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--target", choices=["staging", "prod"], default="staging")
    parser.add_argument(
        "--source",
        choices=SOURCES,
        default=AWS,
        help="where the L1C JP2 files are read from; the two fallbacks are untested until their credentials exist",
    )
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error("--end is before --start")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    results = run(args.s2, args.domain, args.start, args.end, storage_from_env(args.target), args.source)
    missing = [result["date"] for result in results if result["status"] == "l1c_missing"]
    log.info("%d dates, %d published, L1C missing on: %s", len(results), len(results) - len(missing), missing or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
