import math

import numpy as np

from .grid import Grid

COPERNICUS_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/"
    "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif"
)


def _tile_url(lon: int, lat: int) -> str:
    return COPERNICUS_URL.format(
        ns="N" if lat >= 0 else "S",
        lat=abs(lat),
        ew="E" if lon >= 0 else "W",
        lon=abs(lon),
    )


def load_elevation(grid: Grid, bbox: tuple[float, float, float, float]) -> np.ndarray:
    """Elevation in metres on the model grid from the global 30 m Copernicus DEM."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.errors import RasterioIOError
    from rasterio.warp import reproject

    west, south, east, north = bbox
    pad = 0.01
    elevation = np.full((grid.height, grid.width), np.nan, dtype="float32")
    for lon in range(math.floor(west - pad), math.floor(east + pad) + 1):
        for lat in range(math.floor(south - pad), math.floor(north + pad) + 1):
            try:
                source = rasterio.open(f"/vsicurl/{_tile_url(lon, lat)}")
            except RasterioIOError:
                continue
            with source:
                tile = np.full(elevation.shape, np.nan, dtype="float32")
                reproject(
                    source=rasterio.band(source, 1),
                    destination=tile,
                    dst_transform=grid.transform,
                    dst_crs=grid.crs,
                    dst_nodata=np.nan,
                    resampling=Resampling.average,
                )
            elevation = np.where(np.isnan(elevation), tile, elevation)
    if np.isnan(elevation).all():
        raise RuntimeError("No elevation data found for the region")
    return elevation


def slope_aspect(elevation: np.ndarray, resolution: float) -> tuple[np.ndarray, np.ndarray]:
    """Slope and aspect in radians; aspect is the downslope direction clockwise from north."""
    filled = np.where(np.isnan(elevation), np.nanmean(elevation), elevation)
    d_row, d_col = np.gradient(filled, resolution)
    slope = np.arctan(np.hypot(d_row, d_col))
    aspect = np.arctan2(-d_col, d_row) % (2 * np.pi)
    return slope.astype("float32"), aspect.astype("float32")
