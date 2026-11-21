"""Sentinel-2 L2A ingest over the domain into a local folder.

    python -m pipelines.s2.ingest --domain data/basins.geojson --start 2026-10-01 --end 2026-11-21 --out work/s2

For each UTC date and relative orbit it writes <out>/<date>/<orbit>/ with reflectance.tif
(green, red, swir16), classes.tif (scl, cloud probability) and record.json (tiles, scene ids,
completeness, domain coverage, valid fraction and whether the date is listed). Incomplete
dates are searched again on later runs and rebuilt when their set of scenes changes.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .domain import Domain, Grid, convex_hull, load_domain
from .mosaic import REFLECTANCE_ASSETS, Mosaic, build_mosaic, domain_fractions
from .stac import Acquisition, Fetch, expected_tiles, fetch_json, group_acquisitions, reference_window, search_items

# Twice the 10-day repeat of one satellite, so every orbit has passed at least twice
# even with a single satellite operating.
REFERENCE_DAYS = 20
# Earth Search lists late granules within hours; past this an incomplete date is final.
RETRY_DAYS = 10
# README D1: an S2 date is listed when the domain is at least 30% covered and valid.
MIN_LISTED_VALID_FRACTION = 0.30


@dataclass(frozen=True)
class Record:
    date: str
    orbit: str
    tiles: list[str]
    expected_tiles: list[str]
    missing_tiles: list[str]
    complete: bool
    scene_ids: list[str]
    processing_baselines: list[str]
    domain_coverage: float
    domain_valid_fraction: float
    domain_pixels: int
    listed: bool


def record_path(out: Path, day: date, orbit: str) -> Path:
    return out / day.isoformat() / orbit / "record.json"


def read_records(out: Path) -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(out.glob("*/*/record.json"))]


def pending_start(out: Path, today: date) -> date | None:
    """Earliest incomplete date still inside the retry window, if any."""
    days = [
        date.fromisoformat(record["date"])
        for record in read_records(out)
        if not record["complete"] and (today - date.fromisoformat(record["date"])).days <= RETRY_DAYS
    ]
    return min(days) if days else None


def write_rasters(folder: Path, mosaic: Mosaic, grid: Grid) -> None:
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
    with rasterio.open(
        folder / "reflectance.tif", "w", count=3, dtype="float32", nodata=float("nan"), predictor=3, **profile
    ) as target:
        for band, asset in enumerate(REFLECTANCE_ASSETS, start=1):
            target.write(mosaic.reflectance[asset], band)
            target.set_band_description(band, asset)
    with rasterio.open(folder / "classes.tif", "w", count=2, dtype="uint8", **profile) as target:
        target.write(mosaic.scl, 1)
        target.set_band_description(1, "scl")
        target.write(mosaic.cloud, 2)
        target.set_band_description(2, "cloud")


def process(acquisition: Acquisition, expected: set[str], domain: Domain, out: Path) -> Record:
    mosaic = build_mosaic(acquisition, domain.grid)
    coverage, valid = domain_fractions(mosaic.scl, domain.mask)
    missing = sorted(expected - set(acquisition.tiles))
    record = Record(
        date=acquisition.day.isoformat(),
        orbit=acquisition.orbit,
        tiles=list(acquisition.tiles),
        expected_tiles=sorted(expected),
        missing_tiles=missing,
        complete=not missing,
        scene_ids=list(acquisition.scene_ids),
        processing_baselines=[item["properties"]["s2:processing_baseline"] for item in acquisition.items],
        domain_coverage=round(coverage, 4),
        domain_valid_fraction=round(valid, 4),
        domain_pixels=domain.pixel_count,
        listed=bool(valid >= MIN_LISTED_VALID_FRACTION),
    )
    folder = record_path(out, acquisition.day, acquisition.orbit).parent
    folder.mkdir(parents=True, exist_ok=True)
    write_rasters(folder, mosaic, domain.grid)
    record_path(out, acquisition.day, acquisition.orbit).write_text(
        json.dumps(record.__dict__, indent=2) + "\n", encoding="utf-8"
    )
    return record


def is_current(out: Path, acquisition: Acquisition, expected: set[str]) -> bool:
    """A record built from exactly these scenes against the same expected tiles needs no rerun."""
    path = record_path(out, acquisition.day, acquisition.orbit)
    if not path.exists():
        return False
    stored = json.loads(path.read_text(encoding="utf-8"))
    return stored["scene_ids"] == list(acquisition.scene_ids) and stored["expected_tiles"] == sorted(expected)


def run(
    domain_path: Path, start: date, end: date, out: Path, today: date | None = None, fetch: Fetch = fetch_json
) -> list[dict]:
    """Ingest every acquisition in [start, end] plus earlier incomplete ones; returns the
    records of the acquisitions searched, in date and orbit order."""
    today = today or datetime.now(timezone.utc).date()
    pending = pending_start(out, today)
    if pending is not None and pending < start:
        start = pending
    domain = load_domain(domain_path)
    hull = convex_hull(domain.geometries)
    reference_start, reference_end = reference_window(start, end, REFERENCE_DAYS)
    items = [
        item for item in search_items(hull, reference_start, reference_end, fetch) if domain.touches(item["geometry"])
    ]
    acquisitions = group_acquisitions(items)
    expected = expected_tiles(acquisitions)
    records = []
    for acquisition in acquisitions:
        if not start <= acquisition.day <= end:
            continue
        if not is_current(out, acquisition, expected[acquisition.orbit]):
            process(acquisition, expected[acquisition.orbit], domain, out)
        records.append(json.loads(record_path(out, acquisition.day, acquisition.orbit).read_text(encoding="utf-8")))
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--domain", type=Path, required=True, help="GeoJSON of the domain polygons (EPSG:4326)")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error("--end is before --start")
    records = run(args.domain, args.start, args.end, args.out)
    for record in records:
        print(
            f"{record['date']} {record['orbit']} tiles={','.join(record['tiles'])} "
            f"complete={record['complete']} coverage={record['domain_coverage']:.4f} "
            f"valid={record['domain_valid_fraction']:.4f} listed={record['listed']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
