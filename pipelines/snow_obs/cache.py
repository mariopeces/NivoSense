"""Observed snow masks of past seasons into a cache outside the catalogue (task T1.7).

    python -m pipelines.snow_obs.cache month --domain work/domain.geojson --start 2023-09-01 --end 2023-09-30 \
        --work work/t17 [--static-cache work/static] [--local-cache work/cache]
    python -m pipelines.snow_obs.cache manifest --start 2023-09-01 --end 2025-09-30 [--local-cache work/cache]

`month` runs the S2 ingest (pipelines.s2.ingest) and the classifier (pipelines.snow_obs.run) on every
acquisition date of the range, exactly as the daily layer does, and writes to the cache:

    snow_obs/<date>/<key>/snow_obs.tif     the classified pass (same COG as the published layer)
    snow_obs/<date>/<key>/summary.json     the classifier's summary of it
    snow_obs/<date>/<key>/entry.json       every pass of the date and the decision; written last
    snow_obs/months/<YYYY-MM-DD>_<YYYY-MM-DD>.json   the entries of the range

The key hashes what the mask is made from: the input key of every pass that day (scene ids and
processing baselines, from the ingest), the tiles expected on each orbit, the domain file and the
source of the ingest and classifier with the locked dependencies. A date whose key already has an
entry is not recomputed, so a rerun after a method fix or a reprocessed granule redoes only the dates
it changes. Nothing here is published in the catalogue.

`manifest` merges the month files into snow_obs/manifest.json. The cache is the staging bucket's
`_cache/` prefix (STAGING_BUCKET, STAGING_PREFIX), or a local folder with --local-cache.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pipelines.catalog.publish import code_version, pixel_hash
from pipelines.catalog.storage import IMMUTABLE, NO_CACHE, GcsStorage, LocalStorage, Storage
from pipelines.s2 import ingest
from pipelines.s2.domain import convex_hull, load_domain
from pipelines.s2.stac import Acquisition, Fetch, expected_tiles, fetch_json, group_acquisitions, search_items

from . import run as snow
from .terrain import load_static

REPO = Path(__file__).resolve().parents[2]
# Everything a mask's pixels depend on besides the scenes and the domain. The cache module itself and
# the display colours of run.py change no pixel of snow_obs.tif, but run.py is kept whole for simplicity.
CODE_FILES = [
    "pipelines/s2/domain.py",
    "pipelines/s2/ingest.py",
    "pipelines/s2/mosaic.py",
    "pipelines/s2/stac.py",
    "pipelines/snow_obs/classify.py",
    "pipelines/snow_obs/run.py",
    "pipelines/snow_obs/terrain.py",
    "pipelines/requirements.lock",
]
KEY_LENGTH = 16
PREFIX = "snow_obs"


def file_sha256(path: Path) -> str:
    # Line endings are normalised so a Windows checkout keys like the Linux runner.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def code_key(root: Path = REPO) -> str:
    digest = hashlib.sha256()
    for name in CODE_FILES:
        digest.update(f"{name}\0{file_sha256(root / name)}\n".encode())
    return digest.hexdigest()


def date_key(passes: dict[str, str], expected: dict[str, list[str]], code: str, domain_sha256: str) -> str:
    payload = {"passes": passes, "expected_tiles": expected, "code": code, "domain": domain_sha256}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:KEY_LENGTH]


def month_ranges(start: date, end: date) -> list[tuple[date, date]]:
    ranges = []
    first = start
    while first <= end:
        next_month = (first.replace(day=1) + timedelta(days=32)).replace(day=1)
        last = min(end, next_month - timedelta(days=1))
        ranges.append((first, last))
        first = next_month
    return ranges


def plan(
    domain_path: Path, start: date, end: date, fetch: Fetch = fetch_json
) -> tuple[dict[date, dict[str, list[Acquisition]]], dict[str, set[str]]]:
    """The passes of every acquisition date in [start, end] and the tiles expected per orbit, from the
    same search, domain filter and reference window as pipelines.s2.ingest.run."""
    domain = load_domain(domain_path)
    reference_start, reference_end = ingest.reference_window(start, end, ingest.REFERENCE_DAYS)
    items = [
        item
        for item in search_items(convex_hull(domain.geometries), reference_start, reference_end, fetch)
        if domain.touches(item["geometry"])
    ]
    acquisitions = group_acquisitions(items)
    days: dict[date, dict[str, list[Acquisition]]] = defaultdict(lambda: defaultdict(list))
    for acquisition in acquisitions:
        if start <= acquisition.day <= end:
            days[acquisition.day][acquisition.orbit].append(acquisition)
    return {day: dict(orbits) for day, orbits in sorted(days.items())}, expected_tiles(acquisitions)


def pass_summary(record: dict) -> dict:
    fields = (
        "orbit",
        "datatake",
        "tiles",
        "missing_tiles",
        "complete",
        "scene_ids",
        "processing_baselines",
        "input_key",
        "domain_coverage",
        "domain_valid_fraction",
        "listed",
    )
    return {field: record[field] for field in fields}


def build_date(
    day: date,
    orbits: dict[str, list[Acquisition]],
    expected: dict[str, set[str]],
    key: str,
    domain_path: Path,
    static: tuple[Any, Any],
    work: Path,
    fetch: Fetch,
) -> tuple[dict, Path | None]:
    """Ingests and classifies one date in `work`; returns the entry and the mask path (None when no
    pass of the date is complete)."""
    domain = load_domain(domain_path)
    s2, out = work / "s2", work / "snow_obs"
    records = [
        json.loads(json.dumps(ingest.process(candidates, expected[orbit], domain, s2).__dict__))
        for orbit, candidates in sorted(orbits.items())
    ]
    entry: dict[str, Any] = {
        "date": day.isoformat(),
        "key": key,
        "passes": [pass_summary(record) for record in records],
        "chosen_orbit": None,
        "mask": None,
        "summary": None,
        "clear": False,
    }
    record = snow.pick_record(records)
    if record is None:
        return entry, None
    summary = snow.process(record, s2 / record["date"] / record["orbit"], domain, *static, out, fetch)
    mask = out / record["date"] / "snow_obs.tif"
    entry.update(
        chosen_orbit=record["orbit"],
        mask=f"{PREFIX}/{day.isoformat()}/{key}/snow_obs.tif",
        summary=summary,
        pixel_hash=pixel_hash(mask),
        # The T1.2 listing rule: a complete pass with at least 30% of the domain observed.
        clear=bool(summary["published"]),
    )
    return entry, mask


def run_month(
    domain_path: Path,
    start: date,
    end: date,
    cache: Storage,
    work: Path,
    static_cache: Path | None = None,
    fetch: Fetch = fetch_json,
    version: str | None = None,
) -> list[dict]:
    code, domain_sha256 = code_key(), file_sha256(domain_path)
    version = version or code_version()
    days, expected = plan(domain_path, start, end, fetch)
    static = None
    entries = []
    for day, orbits in days.items():
        passes = {orbit: ingest.input_key(candidates) for orbit, candidates in sorted(orbits.items())}
        tiles = {orbit: sorted(expected[orbit]) for orbit in passes}
        key = date_key(passes, tiles, code, domain_sha256)
        folder = f"{PREFIX}/{day.isoformat()}/{key}"
        stored = cache.read(f"{folder}/entry.json")
        if stored is not None:
            entry = json.loads(stored.data)
            print(f"{day} {key} cached clear={entry['clear']}", flush=True)
            entries.append(entry)
            continue
        if static is None:
            domain = load_domain(domain_path)
            static = load_static(domain.grid, static_cache)
        day_work = work / day.isoformat()
        started = datetime.now(timezone.utc)
        entry, mask = build_date(day, orbits, expected, key, domain_path, static, day_work, fetch)
        entry.update(
            code_key=code,
            domain_sha256=domain_sha256,
            code_version=version,
            seconds=round((datetime.now(timezone.utc) - started).total_seconds(), 1),
        )
        if mask is not None:
            cache.write(f"{folder}/snow_obs.tif", mask, "image/tiff", IMMUTABLE)
            cache.write(f"{folder}/summary.json", json_bytes(entry["summary"]), "application/json", IMMUTABLE)
        cache.write(f"{folder}/entry.json", json_bytes(entry), "application/json", IMMUTABLE)
        shutil.rmtree(day_work, ignore_errors=True)
        print(f"{day} {key} built clear={entry['clear']} seconds={entry['seconds']}", flush=True)
        entries.append(entry)
    month = {"start": start.isoformat(), "end": end.isoformat(), "entries": entries}
    cache.write(month_key(start, end), json_bytes(month), "application/json", NO_CACHE)
    return entries


def month_key(start: date, end: date) -> str:
    return f"{PREFIX}/months/{start.isoformat()}_{end.isoformat()}.json"


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def build_manifest(cache: Storage, start: date, end: date) -> dict:
    """Merges the month files of [start, end]; fails when a month has not run."""
    entries: list[dict] = []
    missing = []
    for first, last in month_ranges(start, end):
        blob = cache.read(month_key(first, last))
        if blob is None:
            missing.append(month_key(first, last))
            continue
        entries.extend(json.loads(blob.data)["entries"])
    if missing:
        raise RuntimeError(f"months not run: {', '.join(missing)}")
    entries.sort(key=lambda entry: entry["date"])
    manifest = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "acquisition_dates": len(entries),
        "clear_dates": [entry["date"] for entry in entries if entry["clear"]],
        "entries": entries,
    }
    cache.write(f"{PREFIX}/manifest.json", json_bytes(manifest), "application/json", NO_CACHE)
    return manifest


def cache_from_env(local: Path | None) -> Storage:
    if local is not None:
        return LocalStorage(local)
    bucket = os.environ.get("STAGING_BUCKET")
    if not bucket:
        raise RuntimeError("STAGING_BUCKET is not set (or pass --local-cache)")
    return GcsStorage(bucket, os.environ.get("STAGING_PREFIX", "") + "_cache")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    month = commands.add_parser("month", help="ingest, classify and cache every acquisition date of a range")
    month.add_argument("--domain", type=Path, required=True, help="GeoJSON of the domain polygons (EPSG:4326)")
    month.add_argument("--work", type=Path, required=True, help="scratch folder, emptied date by date")
    month.add_argument("--static-cache", type=Path, help="folder to keep the DEM and forest grids between runs")
    manifest = commands.add_parser("manifest", help="merge the month files into snow_obs/manifest.json")
    for command in (month, manifest):
        command.add_argument("--start", type=date.fromisoformat, required=True)
        command.add_argument("--end", type=date.fromisoformat, required=True)
        command.add_argument("--local-cache", type=Path, help="a folder instead of the staging bucket")
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error("--end is before --start")
    cache = cache_from_env(args.local_cache)
    if args.command == "month":
        entries = run_month(args.domain, args.start, args.end, cache, args.work, args.static_cache)
        print(f"{len(entries)} acquisition dates, {sum(entry['clear'] for entry in entries)} clear")
    else:
        result = build_manifest(cache, args.start, args.end)
        print(f"{result['acquisition_dates']} acquisition dates, {len(result['clear_dates'])} clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
