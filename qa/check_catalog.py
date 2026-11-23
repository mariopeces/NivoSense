"""check_catalog: every entry's files exist, the COG is valid, on the EPSG:32630 grid, with nodata and values in
range, and no daily layer misses a day (README D1, D2)."""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from jsonschema import ValidationError

from pipelines.catalog import LocalStorage, Storage, pixel_hash
from pipelines.catalog.layers import CRS, ZOOMS, check_on_grid, get_layer
from pipelines.catalog.validate import validate_entry, validate_index

from .freshness import DAILY_SINCE, F2_DEADLINE, MADRID
from .objects import byte_reader, local_file

INDEX_KEY = "catalog/index.json"
ENTRIES_PREFIX = "catalog/entries/"
# DAILY_SINCE (in freshness, shared with F2) lists the daily layers and the first day each must exist from.
# Without --start, files and thumbnails are checked for the last 35 days: a month plus the 5 days the daily
# observation job reprocesses. A full-range check is an explicit --start/--end run (one job per month in qa.yml).
DEFAULT_WINDOW_DAYS = 35
# Entry bounds are rounded to 6 decimals (about 0.1 m) by publish().
BOUNDS_TOLERANCE_DEG = 2e-6


def _problem(check: str, message: str, entry: dict[str, Any] | None = None, key: str | None = None) -> dict[str, Any]:
    return {
        "check": check,
        "layer": entry.get("layer") if entry else None,
        "date": entry.get("date") if entry else None,
        "key": key,
        "message": message,
    }


def cog_problems(path: Path) -> list[str]:
    """Why a file is not a valid Cloud Optimized GeoTIFF, as GDAL's COG driver lays it out; empty if it is.

    Follows the checks of GDAL's validate_cloud_optimized_geotiff.py: the structural metadata header that the
    COG driver writes (IFDs before data, not edited since), internal tiling, overviews for images larger than a
    tile, and every block of every band decoding without error.
    """
    import rasterio
    from rasterio.errors import RasterioError

    with open(path, "rb") as handle:
        head = handle.read(1024)
    if head[:4] not in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
        return ["not a TIFF file"]
    problems = []
    marker = b"GDAL_STRUCTURAL_METADATA_SIZE="
    if marker not in head:
        problems.append("no GDAL structural metadata: not written by the COG driver")
    else:
        if b"LAYOUT=IFDS_BEFORE_DATA" not in head:
            problems.append("IFDs are not before the image data")
        if b"KNOWN_INCOMPATIBLE_EDITION=YES" in head:
            problems.append("edited after it was written; the COG layout no longer holds")
    try:
        with rasterio.open(path) as src:
            if src.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") != "COG":
                problems.append("GDAL does not report LAYOUT=COG")
            block_height, block_width = src.block_shapes[0]
            if (src.width > 512 or src.height > 512) and (block_width == src.width or block_height == 1):
                problems.append(f"not tiled (blocks {block_width}x{block_height})")
            if (src.width > 512 or src.height > 512) and not src.overviews(1):
                problems.append(f"no overviews on a {src.width}x{src.height} image")
            for band in range(1, src.count + 1):
                for _, window in src.block_windows(band):
                    src.read(band, window=window)
                for level in src.overviews(band):
                    src.read(band, out_shape=(max(1, src.height // level), max(1, src.width // level)))
    except RasterioError as error:
        # rasterio wraps the GDAL error that says which block failed; report that one.
        problems.append(f"unreadable: {error.__cause__ or error}")
    return problems


def _data_problems(path: Path, entry: dict[str, Any]) -> list[tuple[str, str]]:
    import rasterio
    from rasterio.warp import transform_bounds

    problems: list[tuple[str, str]] = []
    with rasterio.open(path) as src:
        crs = src.crs.to_string() if src.crs else ""
        if crs != CRS or entry["crs"] != CRS:
            problems.append(("crs", f"file CRS {crs or 'none'}, entry {entry['crs']}, expected {CRS}"))
        try:
            check_on_grid(crs, tuple(src.transform), entry["resolution_m"])
        except ValueError as error:
            problems.append(("grid", str(error)))
        if src.nodata is None:
            problems.append(("nodata", "nodata is not set"))
        elif float(src.nodata) != float(entry["nodata"]):
            problems.append(("nodata", f"file nodata {src.nodata}, entry {entry['nodata']}"))
        if src.count != len(entry["bands"]) or src.count != len(entry["value_range"]):
            problems.append(("bands", f"{src.count} bands, entry lists {len(entry['bands'])}"))
            return problems
        for band, (low, high) in enumerate(entry["value_range"], start=1):
            values = src.read(band, masked=True).compressed()
            if values.dtype.kind == "f":
                values = values[~np.isnan(values)]
            if values.size == 0:
                problems.append(("values", f"band {band} has no valid pixels"))
            elif values.min() < low or values.max() > high:
                problems.append(("values", f"band {band} spans {values.min()}..{values.max()}, declared {low}..{high}"))
        if src.crs:
            bounds = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
            if max(abs(a - b) for a, b in zip(bounds, entry["bounds"])) > BOUNDS_TOLERANCE_DEG:
                problems.append(("bounds", f"file bounds {[round(b, 6) for b in bounds]}, entry {entry['bounds']}"))
    if pixel_hash(path) != entry["pixel_hash"]:
        problems.append(("pixel_hash", "the COG's pixels do not match the entry's pixel_hash"))
    return problems


def pmtiles_problems(storage: Storage, entry: dict[str, Any], tile_format: str = "PNG") -> list[str]:
    """Header and layout checks of the display PMTiles, read by byte range; tile_format is the layer's."""
    from pmtiles.reader import deserialize_header
    from pmtiles.tile import MagicNumberNotFound, SpecVersionUnsupported, TileType

    reader = byte_reader(storage, entry["pmtiles"])
    if reader is None:
        return ["missing"]
    read, size = reader
    try:
        header = deserialize_header(read(0, 127))
    except (MagicNumberNotFound, SpecVersionUnsupported, ValueError) as error:
        return [f"bad header: {type(error).__name__} {error}".strip()]
    problems = []
    for name in ("root", "metadata", "leaf_directory", "tile_data"):
        if header[f"{name}_offset"] + header[f"{name}_length"] > size:  # type: ignore[literal-required]
            problems.append(f"{name} section ends past the end of the file ({size} bytes)")
    if header["tile_type"] != TileType[tile_format]:
        problems.append(f"tile type {header['tile_type'].name}, expected {tile_format}")
    zooms = get_layer(entry["layer"]).zooms or ZOOMS[entry["resolution_m"]]
    if (header["min_zoom"], header["max_zoom"]) != zooms:
        problems.append(f"zooms {header['min_zoom']}..{header['max_zoom']}, expected {zooms[0]}..{zooms[1]}")
    if header["addressed_tiles_count"] == 0:
        problems.append("no tiles")
    west, south, east, north = entry["bounds"]
    tile_box = [header[k] / 1e7 for k in ("min_lon_e7", "min_lat_e7", "max_lon_e7", "max_lat_e7")]  # type: ignore[literal-required]
    if tile_box[0] > east or tile_box[2] < west or tile_box[1] > north or tile_box[3] < south:
        problems.append(f"tile bounds {tile_box} do not overlap the entry bounds {entry['bounds']}")
    return problems


def check_entry(storage: Storage, entry: dict[str, Any], folder: Path) -> list[dict[str, Any]]:
    """Every problem of one entry and its files."""
    problems: list[dict[str, Any]] = []
    try:
        spec = get_layer(entry["layer"])
    except ValueError as error:
        return [_problem("layer", str(error), entry)]
    if (spec.status, spec.resolution_m) != (entry["status"], entry["resolution_m"]):
        declared = f"{entry['status']} at {entry['resolution_m']} m"
        problems.append(_problem("layer", f"{declared}, layer is {spec.status} at {spec.resolution_m} m", entry))
    for message in pmtiles_problems(storage, entry, spec.tile_format):
        problems.append(_problem("pmtiles", message, entry, entry["pmtiles"]))
    path = local_file(storage, entry["cog"], folder)
    if path is None:
        problems.append(_problem("cog", "missing", entry, entry["cog"]))
        return problems
    try:
        cog = cog_problems(path)
        problems.extend(_problem("cog", message, entry, entry["cog"]) for message in cog)
        if not cog:
            problems.extend(
                _problem(check, message, entry, entry["cog"]) for check, message in _data_problems(path, entry)
            )
    finally:
        if not isinstance(storage, LocalStorage):
            path.unlink(missing_ok=True)
    return problems


def _checked(storage: Storage, entry: dict[str, Any], folder: Path) -> list[dict[str, Any]]:
    # One malformed object must not stop the run before the report is written: whatever it raises is
    # reported against its entry.
    try:
        return check_entry(storage, entry, folder)
    except Exception as error:
        return [_problem("unexpected", f"{type(error).__name__}: {error}", entry)]


def missing_days(dates: list[str], start: str, end: str) -> list[str]:
    """Every day from start to end (inclusive) that is not in dates."""
    present = set(dates)
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    return [
        day.isoformat()
        for day in (first + dt.timedelta(days=n) for n in range((last - first).days + 1))
        if day.isoformat() not in present
    ]


def _entry_objects(storage: Storage) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    problems: list[dict[str, Any]] = []
    for key in storage.list(ENTRIES_PREFIX):
        if not key.endswith(".json"):
            continue
        blob = storage.read(key)
        if blob is None:
            continue
        try:
            entry = json.loads(blob.data)
            validate_entry(entry)
        except (ValueError, ValidationError) as error:  # unparsable JSON or a schema violation
            problems.append(_problem("entry_schema", str(error).splitlines()[0], key=key))
            continue
        if key != f"{ENTRIES_PREFIX}{entry['layer']}/{entry['date']}.json":
            problems.append(_problem("entry_key", f"holds {entry['layer']} {entry['date']}", entry, key))
            continue
        entries[(entry["layer"], entry["date"])] = entry
    return entries, problems


def expected_last_day(now: dt.datetime) -> str:
    """The latest day the daily layers must have: yesterday (Europe/Madrid) once its F2 deadline has passed."""
    local = now.astimezone(MADRID)
    lag = 1 if local.time() >= F2_DEADLINE else 2
    return (local.date() - dt.timedelta(days=lag)).isoformat()


def check_catalog(
    storage: Storage,
    start: str | None = None,
    end: str | None = None,
    workers: int = 4,
    now: dt.datetime | None = None,
    allow_absent: bool = False,
) -> dict[str, Any]:
    """Check the catalogue and return the report.

    A catalogue with no index and no entry fails, so a wrong root or a wiped catalogue never reads as a pass,
    unless allow_absent says an empty catalogue is expected (pull requests before the first publish).

    Files are checked for entries dated start..end; without start, for the last DEFAULT_WINDOW_DAYS days.
    Every daily layer of DAILY_SINCE is checked for missing days from its first expected day (clipped to start)
    to `end`, or to the last expected day when no end is given, also when it has no entry in the index.
    """
    started = time.monotonic()
    now = now or dt.datetime.now(dt.timezone.utc)
    window_start = start or (now.astimezone(MADRID).date() - dt.timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat()
    report: dict[str, Any] = {
        "check": "check_catalog",
        "catalogue": repr(storage),
        "generated_at": now.isoformat(timespec="seconds"),
        "range": {"start": window_start, "end": end, "default_window": start is None},
        "entries_checked": 0,
        "layers": {},
        "errors": [],
    }
    errors: list[dict[str, Any]] = report["errors"]
    objects, entry_errors = _entry_objects(storage)
    errors.extend(entry_errors)

    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    blob = storage.read(INDEX_KEY)
    if blob is None:
        if objects or entry_errors:
            errors.append(_problem("index", "catalog/index.json is missing but entries exist", key=INDEX_KEY))
        elif not allow_absent:
            errors.append(_problem("index", "catalogue absent: no catalog/index.json and no entry", key=INDEX_KEY))
        report["index"] = "absent"
    else:
        try:
            index = json.loads(blob.data)
            validate_index(index)
        except (ValueError, ValidationError) as error:  # unparsable JSON or a schema violation
            errors.append(_problem("index", f"invalid: {str(error).splitlines()[0]}", key=INDEX_KEY))
            index = {"layers": {}}
        report["index"] = {"generated_at": index.get("generated_at"), "entries_digest": index.get("entries_digest")}
        for layer, item in index["layers"].items():
            if item["dates"] != [entry["date"] for entry in item["entries"]] or item["dates"] != sorted(item["dates"]):
                errors.append(_problem("index", f"{layer}: dates are not the ascending dates of its entries"))
            for entry in item["entries"]:
                indexed[(entry["layer"], entry["date"])] = entry
        for key in sorted(set(objects) | set(indexed)):
            if objects.get(key) != indexed.get(key):
                where = (
                    "only in the index"
                    if key not in objects
                    else "not in the index"
                    if key not in indexed
                    else "differs from its entry object"
                )
                entry = objects.get(key) or indexed.get(key)
                errors.append(_problem("index", f"index entry {where}; rebuild the index", entry))

    # The index is what the site reads, so its entries are what is checked; entry objects not yet indexed
    # are already reported above.
    selected = [
        entry
        for _, entry in sorted(indexed.items())
        if entry["date"] >= window_start and (end is None or entry["date"] <= end)
    ]
    with tempfile.TemporaryDirectory(prefix="qa-") as tmp, ThreadPoolExecutor(max_workers=workers) as pool:
        for problems in pool.map(lambda entry: _checked(storage, entry, Path(tmp)), selected):
            errors.extend(problems)
    report["entries_checked"] = len(selected)

    all_dates: dict[str, list[str]] = {layer: [] for layer in DAILY_SINCE}
    for layer, date in sorted(indexed):
        all_dates.setdefault(layer, []).append(date)
    last_expected = end or expected_last_day(now)
    for layer, dates in sorted(all_dates.items()):
        in_window = [date for date in dates if date >= window_start and (end is None or date <= end)]
        summary: dict[str, Any] = {
            "entries": len(dates),
            "first": min(dates, default=None),
            "last": max(dates, default=None),
        }
        summary["checked_files"] = len(in_window)
        if layer in DAILY_SINCE:
            since = DAILY_SINCE[layer] or summary["first"]
            if since is None:
                summary["daily"] = "not live: no entry and no declared start"
            else:
                first = max(since, start) if start else since
                gaps = missing_days(dates, first, last_expected) if first <= last_expected else []
                summary["daily"] = {"expected": [first, last_expected], "missing_days": gaps}
                errors.extend(
                    _problem("missing_day", "no entry for this day", {"layer": layer, "date": day}) for day in gaps
                )
        report["layers"][layer] = summary
    report["ok"] = not errors
    report["duration_s"] = round(time.monotonic() - started, 1)
    return report
