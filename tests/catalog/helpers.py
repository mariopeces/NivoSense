"""Small rasters for the catalogue tests. They exercise the plumbing only and are never published anywhere."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

# A corner on the 100 m grid inside UTM 30N over Sierra Nevada; any multiple of the resolution would do.
LEFT, TOP = 460000.0, 4105000.0


def write_raster(
    path: Path,
    array: np.ndarray,
    resolution: float,
    nodata: float | None,
    crs: str = "EPSG:32630",
    left: float = LEFT,
    top: float = TOP,
) -> Path:
    if array.ndim == 2:
        array = array[np.newaxis]
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=array.shape[2],
        height=array.shape[1],
        count=array.shape[0],
        dtype=array.dtype,
        crs=crs,
        transform=from_origin(left, top, resolution, resolution),
        nodata=nodata,
    ) as dst:
        dst.write(array)
    return path


def product(
    folder: Path, name: str, resolution: int = 20, seed: int = 0, size: int = 64, **kwargs: object
) -> dict[str, Path]:
    """A single-band class raster (0 no snow, 1 snow, 255 nodata) and its RGBA display on the same grid."""
    rng = np.random.default_rng(seed)
    classes = rng.integers(0, 2, (size, size), dtype=np.uint8)
    classes[:4, :] = 255
    data = write_raster(folder / f"{name}-data.tif", classes, resolution, 255, **kwargs)  # type: ignore[arg-type]
    rgba = np.zeros((4, size, size), dtype=np.uint8)
    rgba[:3] = np.where(classes == 1, 255, 120)
    rgba[3] = np.where(classes == 255, 0, 255)
    display = write_raster(folder / f"{name}-display.tif", rgba, resolution, None, **kwargs)  # type: ignore[arg-type]
    return {"data": data, "display": display}


def meta(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "source_ids": ["test-scene-a", "test-scene-b"],
        "bands": ["snow_class"],
        "units": ["1"],
        "value_range": [[0, 1]],
        "code_version": "test",
        "processing_baseline": "test-baseline",
    }
    base.update(overrides)
    return base
