from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np

from .domain import Grid
from .stac import LEGACY_COLLECTION, Acquisition

REFLECTANCE_ASSETS = ("green", "red", "swir16")
CLASS_ASSETS = ("scl", "cloud")
# Legacy collection items point `cloud` at a JP2 in a requester-pays bucket (or lack it); nothing downstream
# of the ingest reads it, so such items give zeros.
OPTIONAL_ASSETS = ("cloud",)
READ_THREADS = 8
GDAL_OPTIONS = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_MAX_RETRY": "4",
    "GDAL_HTTP_RETRY_DELAY": "3",
}

# Sen2Cor scene classification (ESA S2 L2A Product Specification, SCL classes):
# 0 no data, 1 saturated or defective, 3 cloud shadow, 8 cloud medium probability,
# 9 cloud high probability, 10 thin cirrus. Every other class is a clear-sky observation,
# including 11 snow and 2 dark area / topographic shadow (shadow is handled downstream).
SCL_NODATA = 0
SCL_NOT_VALID = (0, 1, 3, 8, 9, 10)


@dataclass(frozen=True)
class Mosaic:
    """Bands of one acquisition on the domain grid. Reflectance is float32 with NaN where no
    tile has data; scl is 0 there and cloud (probability, percent) is 0 there."""

    reflectance: dict[str, np.ndarray]
    scl: np.ndarray
    cloud: np.ndarray


def scale_offset(item: dict, asset: str) -> tuple[float, float]:
    """Scale and offset of the digital numbers of one asset, from its raster:bands.

    Exception: the legacy collection declares offset -0.1 for baseline 04.00 and later (including the 05.xx
    reprocessing of older dates) but stores digital numbers with the +1000 already removed and clipped at 1
    (green over 30SVG, 2024-03-13, baseline 05.10: legacy p1/p50/p99 500/1218/2574, c1 1500/2218/3574, the
    same pixels one thousand apart; legacy 02.11 and 05.00 of 2019-04-29 agree within a few percent). Applying
    the declared offset there makes reflectance 0.1 too low, so its offset is 0."""
    if item.get("collection") == LEGACY_COLLECTION:
        return 0.0001, 0.0
    bands = item["assets"][asset].get("raster:bands")
    if not bands or "scale" not in bands[0] or "offset" not in bands[0]:
        raise ValueError(f"{item['id']} asset {asset} has no raster:bands scale and offset")
    return float(bands[0]["scale"]), float(bands[0]["offset"])


def read_window(href: str, grid: Grid) -> np.ndarray:
    """The part of one tile asset that falls on the grid, at the asset's native resolution
    (grid.resolution / pixel size times the grid shape), zero where the tile has no pixels."""
    import rasterio
    from rasterio.windows import Window

    with rasterio.open(href) as source:
        if str(source.crs) != grid.crs:
            raise ValueError(f"{href} is in {source.crs}, expected {grid.crs}")
        pixel = source.res[0]
        factor = int(round(grid.resolution / pixel))
        if factor * pixel != grid.resolution:
            raise ValueError(f"{href} pixel size {pixel} does not nest in {grid.resolution} m")
        col0 = (grid.left - source.transform.c) / pixel
        row0 = (source.transform.f - grid.top) / pixel
        if col0 % 1 or row0 % 1:
            raise ValueError(f"{href} pixels are not aligned with the domain grid")
        col0, row0 = int(col0), int(row0)
        width, height = grid.width * factor, grid.height * factor
        out = np.zeros((height, width), dtype=source.dtypes[0])
        col_start, row_start = max(0, col0), max(0, row0)
        col_stop = min(source.width, col0 + width)
        row_stop = min(source.height, row0 + height)
        if col_stop <= col_start or row_stop <= row_start:
            return out
        block = source.read(1, window=Window(col_start, row_start, col_stop - col_start, row_stop - row_start))
        out[row_start - row0 : row_stop - row0, col_start - col0 : col_stop - col0] = block
        return out


def to_grid_reflectance(raw: np.ndarray, scale: float, offset: float, factor: int) -> np.ndarray:
    """Digital numbers to reflectance on the 20 m grid. 10 m bands are averaged over the
    2x2 block that makes each 20 m pixel; a block with any nodata (0) pixel is nodata."""
    values = raw.astype("float32") * np.float32(scale) + np.float32(offset)
    values[raw == 0] = np.nan
    if factor == 1:
        return values
    height, width = values.shape[0] // factor, values.shape[1] // factor
    return values.reshape(height, factor, width, factor).mean(axis=(1, 3))


def build_mosaic(acquisition: Acquisition, grid: Grid) -> Mosaic:
    """Mosaic of every granule of one acquisition. Sen2Cor corrects each tile on its own, so
    overlapping granules differ slightly (clear land, 2026-10/11: median |d| 0.0006 to 0.006
    reflectance, p95 <= 0.016); each pixel takes the first granule with data in a fixed
    order (tile name, then latest generation) so reruns give the same mosaic."""
    import rasterio

    jobs = [
        (index, asset, item["assets"][asset]["href"])
        for index, item in enumerate(acquisition.items)
        for asset in REFLECTANCE_ASSETS + CLASS_ASSETS
        if asset not in OPTIONAL_ASSETS or item["assets"].get(asset, {}).get("href", "").endswith(".tif")
    ]
    with rasterio.Env(**GDAL_OPTIONS):
        with ThreadPoolExecutor(READ_THREADS) as pool:
            arrays = list(pool.map(lambda job: read_window(job[2], grid), jobs))
    raw = {(index, asset): array for (index, asset, _), array in zip(jobs, arrays)}

    shape = (grid.height, grid.width)
    reflectance = {asset: np.full(shape, np.nan, dtype="float32") for asset in REFLECTANCE_ASSETS}
    scl = np.zeros(shape, dtype="uint8")
    cloud = np.zeros(shape, dtype="uint8")
    for index, item in enumerate(acquisition.items):
        tile_scl = raw[(index, "scl")]
        take = (scl == SCL_NODATA) & (tile_scl != SCL_NODATA)
        scl[take] = tile_scl[take]
        if (index, "cloud") in raw:
            cloud[take] = raw[(index, "cloud")][take]
        for asset in REFLECTANCE_ASSETS:
            band = raw[(index, asset)]
            factor = band.shape[0] // grid.height
            values = to_grid_reflectance(band, *scale_offset(item, asset), factor)
            reflectance[asset][take] = values[take]
    return Mosaic(reflectance, scl, cloud)


def domain_fractions(scl: np.ndarray, domain_mask: np.ndarray) -> tuple[float, float]:
    """Share of domain pixels with data (coverage) and with a clear-sky SCL class (valid)."""
    inside = scl[domain_mask]
    total = inside.size
    covered = np.count_nonzero(inside != SCL_NODATA)
    valid = np.count_nonzero(~np.isin(inside, SCL_NOT_VALID))
    return covered / total, valid / total
