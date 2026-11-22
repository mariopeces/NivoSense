"""Sentinel-2 L2A ingest over the domain into a local folder.

    python -m pipelines.s2.ingest --domain data/basins.geojson --start 2026-10-01 --end 2026-11-21 --out work/s2 \
        [--catalogue-root work/catalogue]

For each UTC date and relative orbit it writes <out>/<date>/<orbit>/ with reflectance.tif
(green, red, swir16), classes.tif (scl, cloud probability) and record.json (tiles, scene ids,
input key, completeness, domain coverage, valid fraction and whether the date is listed).
Every run also searches the last REPROCESS_DAYS days again, complete or not, and rebuilds a
date whose input key (scene ids and processing baselines) or expected tiles changed. With
--catalogue-root it writes the pass decision read by the freshness monitor to
<root>/s2/decisions/<date>_<orbit>.json.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .domain import Domain, Grid, convex_hull, load_domain
from .mosaic import REFLECTANCE_ASSETS, Mosaic, build_mosaic, domain_fractions
from .stac import Acquisition, Fetch, expected_tiles, fetch_json, group_acquisitions, reference_window, search_items

# Twice the 10-day repeat of one satellite, so every orbit has passed at least twice
# even with a single satellite operating.
REFERENCE_DAYS = 20
# README section 5 has the daily job reprocess the last 5 days so late granules complete a
# mosaic; the split 30SWG granules of 2026-11-17 were generated 67 min apart. 10 days is a
# margin over that, and a recheck costs one STAC search when nothing changed.
REPROCESS_DAYS = 10
# README D1: an S2 date is listed when the domain is at least 30% covered and valid. A date
# with a missing tile is not listed until the tile arrives.
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
    input_key: str
    domain_coverage: float
    domain_valid_fraction: float
    domain_pixels: int
    listed: bool


def record_path(out: Path, day: date, orbit: str) -> Path:
    return out / day.isoformat() / orbit / "record.json"


def decision_path(catalogue_root: Path, day: date, orbit: str) -> Path:
    return catalogue_root / "s2" / "decisions" / f"{day.isoformat()}_{orbit}.json"


def input_key(acquisition: Acquisition) -> str:
    """Hash of the granules a mosaic is built from: a new granule or a newer baseline changes it."""
    granules = sorted((item["id"], item["properties"]["s2:processing_baseline"]) for item in acquisition.items)
    return hashlib.sha256(json.dumps(granules).encode()).hexdigest()


def code_version() -> str:
    """The commit being run: GITHUB_SHA in Actions, else the local HEAD."""
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    return subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def search_windows(start: date, end: date, today: date) -> list[tuple[date, date]]:
    """The requested range and the reprocessing window ending today, merged when they meet."""
    recent = (today - timedelta(days=REPROCESS_DAYS), today)
    if recent[0] > end + timedelta(days=1) or recent[1] < start - timedelta(days=1):
        return sorted([(start, end), recent])
    return [(min(start, recent[0]), max(end, recent[1]))]


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
        input_key=input_key(acquisition),
        domain_coverage=round(coverage, 4),
        domain_valid_fraction=round(valid, 4),
        domain_pixels=domain.pixel_count,
        listed=not missing and bool(valid >= MIN_LISTED_VALID_FRACTION),
    )
    folder = record_path(out, acquisition.day, acquisition.orbit).parent
    folder.mkdir(parents=True, exist_ok=True)
    write_rasters(folder, mosaic, domain.grid)
    record_path(out, acquisition.day, acquisition.orbit).write_text(
        json.dumps(record.__dict__, indent=2) + "\n", encoding="utf-8"
    )
    return record


def is_current(out: Path, acquisition: Acquisition, expected: set[str]) -> bool:
    """A record built from the same input key against the same expected tiles needs no rerun."""
    path = record_path(out, acquisition.day, acquisition.orbit)
    if not path.exists():
        return False
    stored = json.loads(path.read_text(encoding="utf-8"))
    return stored.get("input_key") == input_key(acquisition) and stored["expected_tiles"] == sorted(expected)


def write_decision(catalogue_root: Path, record: dict, version: str) -> None:
    """The pass decision (pipelines/catalog/s2_decision.schema.json) for the freshness monitor."""
    decision = {
        "date": record["date"],
        "orbit": record["orbit"],
        "scene_ids": record["scene_ids"],
        "domain_coverage": record["domain_coverage"],
        "domain_valid_fraction": record["domain_valid_fraction"],
        "complete": record["complete"],
        "listed": record["listed"],
        "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "code_version": version,
    }
    path = decision_path(catalogue_root, date.fromisoformat(record["date"]), record["orbit"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")


def run(
    domain_path: Path,
    start: date,
    end: date,
    out: Path,
    today: date | None = None,
    fetch: Fetch = fetch_json,
    catalogue_root: Path | None = None,
    version: str | None = None,
) -> list[dict]:
    """Ingest every acquisition in [start, end] and in the last REPROCESS_DAYS days; returns
    their records in date and orbit order."""
    today = today or datetime.now(timezone.utc).date()
    domain = load_domain(domain_path)
    hull = convex_hull(domain.geometries)
    records: dict[tuple[str, str], dict] = {}
    for window_start, window_end in search_windows(start, end, today):
        reference_start, reference_end = reference_window(window_start, window_end, REFERENCE_DAYS)
        items = [
            item
            for item in search_items(hull, reference_start, reference_end, fetch)
            if domain.touches(item["geometry"])
        ]
        acquisitions = group_acquisitions(items)
        expected = expected_tiles(acquisitions)
        for acquisition in acquisitions:
            if not window_start <= acquisition.day <= window_end:
                continue
            orbit_tiles = expected[acquisition.orbit]
            rebuilt = not is_current(out, acquisition, orbit_tiles)
            if rebuilt:
                process(acquisition, orbit_tiles, domain, out)
            record = json.loads(record_path(out, acquisition.day, acquisition.orbit).read_text(encoding="utf-8"))
            if catalogue_root is not None and (
                rebuilt or not decision_path(catalogue_root, acquisition.day, acquisition.orbit).exists()
            ):
                write_decision(catalogue_root, record, version or code_version())
            records[(record["date"], record["orbit"])] = record
    return [records[key] for key in sorted(records)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--domain", type=Path, required=True, help="GeoJSON of the domain polygons (EPSG:4326)")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--catalogue-root", type=Path, help="write pass decisions under <root>/s2/decisions/")
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error("--end is before --start")
    records = run(args.domain, args.start, args.end, args.out, catalogue_root=args.catalogue_root)
    for record in records:
        print(
            f"{record['date']} {record['orbit']} tiles={','.join(record['tiles'])} "
            f"complete={record['complete']} coverage={record['domain_coverage']:.4f} "
            f"valid={record['domain_valid_fraction']:.4f} listed={record['listed']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
