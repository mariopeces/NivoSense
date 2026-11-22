"""L1C bands to an 8-bit true colour image on the 10 m domain grid."""

from concurrent.futures import ThreadPoolExecutor

import numpy as np

from pipelines.s2.domain import Grid
from pipelines.s2.mosaic import read_window, scale_offset
from pipelines.s2.stac import Acquisition

from .source import RGB_ASSETS, asset_href, gdal_options

RESOLUTION_M = 10.0
READ_THREADS = 4

# Fixed stretch, the same on every date so dates compare, in top-of-atmosphere reflectance
# (red, green, blue). Measured with pipelines.rgb_l1c.calibrate inside the domain on
# 2025-12-18, 2026-02-21 and 2026-03-25 (R094, all four tiles):
# - BLACK: dark-object subtraction (Chavez 1988), the lowest 0.1th percentile of each band
#   over those dates (0.0233, 0.0397, 0.0646); removes most of the blue path radiance haze.
# - WHITE: the highest 99.9th percentile of each band under the L2A snow stand-in mask over
#   those dates (1.6089, 1.4313, 1.4515). Sunlit winter slopes reach a TOA reflectance of 1.6,
#   so the Sentinel-2 TCI (white at 0.4) saturates on snow; a white per band also balances
#   snow to neutral, since TOA red exceeds blue over snow.
# - GAMMA: the usual display gamma, so dark terrain stays readable next to snow.
BLACK = (0.023, 0.040, 0.065)
WHITE = (1.61, 1.43, 1.45)
GAMMA = 2.2
NODATA = 0


def grid_10m(grid: Grid) -> Grid:
    """The 10 m grid with the same extent as a 20 m domain grid: every 20 m pixel holds exactly
    2x2 of these, so the RGB and the 20 m snow masks share pixel edges by construction."""
    factor = int(round(grid.resolution / RESOLUTION_M))
    return Grid(grid.crs, grid.left, grid.top, RESOLUTION_M, grid.width * factor, grid.height * factor)


def domain_mask(geometries: tuple[dict, ...], grid: Grid) -> np.ndarray:
    """Pixels whose centre falls inside the domain polygons (EPSG:4326 GeoJSON)."""
    from rasterio.features import rasterize
    from rasterio.warp import transform_geom

    return rasterize(
        [(transform_geom("EPSG:4326", grid.crs, geometry), 1) for geometry in geometries],
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        fill=0,
        dtype="uint8",
    ).astype(bool)


def read_reflectance(acquisition: Acquisition, grid: Grid, source: str) -> dict[str, np.ndarray]:
    """Top-of-atmosphere reflectance of B04, B03 and B02 mosaicked on the grid, float32, NaN
    where no tile has data. Each pixel takes the first tile, in name order, with data in all
    three bands (tiles of one datatake hold the same values where they overlap)."""
    import rasterio

    jobs = [(item, asset) for item in acquisition.items for asset in RGB_ASSETS]
    with rasterio.Env(**gdal_options(source)):
        with ThreadPoolExecutor(READ_THREADS) as pool:
            arrays = list(pool.map(lambda job: read_window(asset_href(job[0], job[1], source), grid), jobs))
    raw = {(item["id"], asset): array for (item, asset), array in zip(jobs, arrays)}

    shape = (grid.height, grid.width)
    reflectance = {asset: np.full(shape, np.nan, dtype="float32") for asset in RGB_ASSETS}
    filled = np.zeros(shape, dtype=bool)
    for item in acquisition.items:
        bands = [raw.pop((item["id"], asset)) for asset in RGB_ASSETS]
        take = ~filled & np.stack([band != 0 for band in bands]).all(axis=0)
        for asset, band in zip(RGB_ASSETS, bands):
            scale, offset = scale_offset(item, asset)
            reflectance[asset][take] = band[take].astype("float32") * np.float32(scale) + np.float32(offset)
        filled |= take
    return reflectance


def stretch(reflectance: np.ndarray, black: float, white: float, gamma: float = GAMMA) -> np.ndarray:
    """uint8 in 1..255 from reflectance: linear between black and white, clipped, then gamma.
    0 is kept for nodata (NaN), as in the Sentinel-2 TCI product."""
    scaled = np.clip((reflectance - np.float32(black)) / np.float32(white - black), 0, 1) ** np.float32(1 / gamma)
    missing = np.isnan(reflectance)
    out = (1 + np.rint(np.where(missing, 0, scaled) * 254)).astype("uint8")
    out[missing] = NODATA
    return out


def render(reflectance: dict[str, np.ndarray], inside: np.ndarray) -> np.ndarray:
    """(3, rows, cols) uint8 true colour, nodata 0 outside the domain and where any band is missing."""
    valid = inside & np.stack([~np.isnan(reflectance[asset]) for asset in RGB_ASSETS]).all(axis=0)
    rgb = np.stack([stretch(reflectance[asset], BLACK[i], WHITE[i]) for i, asset in enumerate(RGB_ASSETS)])
    rgb[:, ~valid] = NODATA
    return rgb
