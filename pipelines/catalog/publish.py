"""publish(): the only writer of product files and catalogue entries."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from .layers import CRS, ZOOMS, Layer, check_on_grid, get_layer
from .storage import IMMUTABLE, NO_CACHE, PreconditionFailed, Storage
from .validate import dump_json, validate_entry

COG_CONTENT_TYPE = "image/tiff; application=geotiff; profile=cloud-optimized"
PMTILES_CONTENT_TYPE = "application/vnd.pmtiles"


class NonDeterministicOutput(Exception):
    """The same input key produced different pixels than the published entry (README D3)."""


def entry_key(layer: str, date: str) -> str:
    return f"catalog/entries/{layer}/{date}.json"


def input_key(
    layer: str,
    date: str,
    source_ids: list[str],
    code_version: str,
    processing_baseline: str | None = None,
    prior_state: str | None = None,
) -> str:
    """sha256 of everything that determines a product's pixels (README D3).

    `prior_state` is the hash of the model state of the day before, for products that carry state.
    """
    payload = {
        "layer": layer,
        "date": date,
        "source_ids": sorted(source_ids),
        "code_version": code_version,
        "processing_baseline": processing_baseline,
        "prior_state": prior_state,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def pixel_hash(path: Path) -> str:
    """sha256 of the pixels and their georeferencing; file metadata such as timestamps is not part of it."""
    import rasterio

    digest = hashlib.sha256()
    with rasterio.open(path) as src:
        header = {
            "count": src.count,
            "width": src.width,
            "height": src.height,
            "dtypes": list(src.dtypes),
            "crs": src.crs.to_string() if src.crs else None,
            "transform": list(src.transform)[:6],
            "nodata": src.nodata,
        }
        digest.update(json.dumps(header, sort_keys=True).encode())
        for band in range(1, src.count + 1):
            array = src.read(band)
            digest.update(np.ascontiguousarray(array, dtype=array.dtype.newbyteorder("<")).tobytes())
    return digest.hexdigest()


def code_version() -> str:
    """The commit being run: GITHUB_SHA in Actions, else the local HEAD."""
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    return subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def _check_data(
    path: Path, resolution_m: int, bands: list[str], units: list[str], value_range: list[list[float]]
) -> dict[str, Any]:
    import rasterio
    from rasterio.warp import transform_bounds

    with rasterio.open(path) as src:
        check_on_grid(src.crs.to_string() if src.crs else "", tuple(src.transform), resolution_m)
        if src.nodata is None:
            raise ValueError(f"{path}: nodata is not set")
        # NaN is not valid JSON, so it cannot travel in the entry, and inf would not survive either.
        if not math.isfinite(src.nodata):
            raise ValueError(f"{path}: nodata is {src.nodata}; use a finite sentinel such as -9999")
        if not (len(bands) == len(units) == len(value_range) == src.count):
            raise ValueError(
                f"{path}: {src.count} bands, but {len(bands)} names, {len(units)} units and {len(value_range)} ranges"
            )
        if not all(math.isfinite(bound) for pair in value_range for bound in pair):
            raise ValueError(f"{path}: value_range must be finite, got {value_range}")
        for band, (low, high) in enumerate(value_range, start=1):
            data = src.read(band, masked=True)
            # Checked on the raw values: a NaN hidden by a GDAL mask band would still be copied into the COG.
            if data.dtype.kind == "f" and not np.isfinite(data.data).all():
                raise ValueError(f"{path}: band {band} has NaN or infinite pixels; set them to nodata")
            values = data.compressed()
            if values.size == 0:
                raise ValueError(f"{path}: band {band} has no valid pixels")
            if values.min() < low or values.max() > high:
                raise ValueError(
                    f"{path}: band {band} spans {values.min()}..{values.max()}, outside the declared {low}..{high}"
                )
        west, south, east, north = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
        return {
            "bounds": [round(west, 6), round(south, 6), round(east, 6), round(north, 6)],
            "nodata": float(src.nodata),
            "transform": tuple(src.transform)[:6],
            "shape": (src.height, src.width),
        }


def _check_display(path: Path, data: dict[str, Any]) -> None:
    import rasterio

    with rasterio.open(path) as src:
        if src.count != 4 or any(dtype != "uint8" for dtype in src.dtypes):
            raise ValueError(f"{path}: the display raster must be 4-band RGBA uint8")
        grid = (src.crs.to_string() if src.crs else "", tuple(src.transform)[:6], (src.height, src.width))
        if grid != (CRS, data["transform"], data["shape"]):
            raise ValueError(f"{path}: the display raster is not on the same grid as the data")


def _write_cog(source: Path, target: Path, categorical: bool) -> None:
    import rasterio
    from rasterio.shutil import copy

    copy(
        source,
        target,
        driver="COG",
        COMPRESS="DEFLATE",
        PREDICTOR="YES",
        BLOCKSIZE=512,
        OVERVIEW_RESAMPLING="NEAREST" if categorical else "AVERAGE",
    )
    with rasterio.open(target) as cog:
        if cog.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") != "COG":
            raise RuntimeError(f"GDAL did not write a COG layout to {target}")


def _write_pmtiles(display: Path, target: Path, zooms: tuple[int, int], spec: Layer) -> None:
    # rio-pmtiles is a rasterio CLI plugin; running it as a subprocess keeps its process pool out of ours.
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from rasterio.rio.main import main_group; main_group()",
            "pmtiles",
            str(display),
            str(target),
            "--format",
            spec.tile_format,
            *(["--co", f"QUALITY={spec.tile_quality}"] if spec.tile_quality is not None else []),
            "--rgba",
            "--zoom-levels",
            f"{zooms[0]}..{zooms[1]}",
            "--resampling",
            spec.display_resampling,
            "--exclude-empty-tiles",
            "--silent",
        ],
        check=True,
    )


def _upload_once(storage: Storage, key: str, source: Path, content_type: str) -> None:
    try:
        storage.write(key, source, content_type, IMMUTABLE, if_generation_match=0)
    except PreconditionFailed:
        # The name is derived from the content, so an object already under it holds the same pixels.
        pass


def publish(
    layer: str,
    date: str,
    files: dict[str, Path],
    meta: dict[str, Any],
    storage: Storage,
) -> dict[str, Any]:
    """Publish one product: data COG and display PMTiles first, then its catalogue entry.

    files: `data`, a GeoTIFF on the layer's grid with nodata set; `display`, a 4-band RGBA uint8 GeoTIFF on
    the same grid, coloured by the producing pipeline, from which the PMTiles are built.
    meta: `source_ids`, `bands`, `units`, `value_range`, `code_version`, `processing_baseline` (required for
    the Sentinel-2 derived observed and gap-filled layers), optional `prior_state` and `qa`
    ({"flags": [...], "scores": {...}}).

    Files are named `<date>-<hash>` after their content and never overwritten. The entry is written last,
    so a crash before it leaves the catalogue as it was. Republishing the same input key is a no-op.
    """
    spec = get_layer(layer)
    dt.date.fromisoformat(date)
    # Sentinel-2 reprocessing changes the pixels under the same scene ids, so README D3 keys on the baseline.
    if spec.status in ("observed", "gapfilled") and not meta.get("processing_baseline"):
        raise ValueError(f"{layer} is derived from Sentinel-2; meta needs its processing_baseline")
    source_ids = list(meta["source_ids"])
    version_ = meta["code_version"]
    key = input_key(layer, date, source_ids, version_, meta.get("processing_baseline"), meta.get("prior_state"))
    data_info = _check_data(
        Path(files["data"]), spec.resolution_m, list(meta["bands"]), list(meta["units"]), meta["value_range"]
    )
    _check_display(Path(files["display"]), data_info)
    zooms = ZOOMS[spec.resolution_m]

    with tempfile.TemporaryDirectory(prefix="publish-") as tmp:
        cog = Path(tmp) / "data.tif"
        _write_cog(Path(files["data"]), cog, spec.categorical)
        pixels = pixel_hash(cog)
        tiling = {
            "display": pixel_hash(Path(files["display"])),
            "zooms": zooms,
            "format": spec.tile_format,
            "quality": spec.tile_quality,
            "resampling": spec.display_resampling,
            "rio-pmtiles": version("rio-pmtiles"),
        }
        name = f"{date}-{hashlib.sha256((pixels + json.dumps(tiling, sort_keys=True)).encode()).hexdigest()[:16]}"
        cog_key = f"layers/{layer}/{date[:4]}/{name}.tif"
        pmtiles_key = f"tiles/{layer}/{name}.pmtiles"

        entry = {
            "layer": layer,
            "date": date,
            "status": spec.status,
            "cog": cog_key,
            "pmtiles": pmtiles_key,
            "bounds": data_info["bounds"],
            "crs": CRS,
            "resolution_m": spec.resolution_m,
            "bands": list(meta["bands"]),
            "units": list(meta["units"]),
            "value_range": [list(pair) for pair in meta["value_range"]],
            "nodata": data_info["nodata"],
            "source_ids": source_ids,
            "input_key": key,
            "pixel_hash": pixels,
            "code_version": version_,
            "qa": meta.get("qa", {"flags": [], "scores": {}}),
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
        }
        validate_entry(entry)

        published: dict[str, Any] | None = None
        existing_blob = storage.read(entry_key(layer, date))
        if existing_blob is not None:
            existing = json.loads(existing_blob.data)
            if existing["input_key"] == key:
                if (existing["pixel_hash"], existing["cog"], existing["pmtiles"]) != (pixels, cog_key, pmtiles_key):
                    raise NonDeterministicOutput(
                        f"{layer} {date}: input key {key[:12]} gave pixel hash {pixels[:12]}, "
                        f"published {existing['pixel_hash'][:12]}; a code change must change code_version"
                    )
                published = existing
                if storage.exists(cog_key) and storage.exists(pmtiles_key):
                    return dict(published)

        _upload_once(storage, cog_key, cog, COG_CONTENT_TYPE)
        if not storage.exists(pmtiles_key):
            pmtiles = Path(tmp) / "tiles.pmtiles"
            _write_pmtiles(Path(files["display"]), pmtiles, zooms, spec)
            _upload_once(storage, pmtiles_key, pmtiles, PMTILES_CONTENT_TYPE)

    # Files lost from under a published entry are restored; the entry itself stays as it was.
    if published is not None:
        return dict(published)
    storage.write(entry_key(layer, date), dump_json(entry, indent=2), "application/json", NO_CACHE)
    return entry
