"""Static inputs on the 20 m domain grid: elevation, terrain shadow and forest."""

import math
from pathlib import Path

import numpy as np

from pipelines.s2.domain import Grid

# Copernicus DEM GLO-30 (ESA / Airbus, 2021 release) on AWS Open Data, 1x1 degree COGs.
COPERNICUS_DEM_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_N{lat:02d}_00_W{lon:03d}_00_DEM/"
    "Copernicus_DSM_COG_10_N{lat:02d}_00_W{lon:03d}_00_DEM.tif"
)
# ESA WorldCover 10 m 2021 v200 (Zanaga et al. 2022, doi:10.5281/zenodo.7254221), 3x3 degree COGs
# on AWS Open Data. Class 10 is tree cover.
WORLDCOVER_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_N{lat:02d}W{lon:03d}_Map.tif"
)
WORLDCOVER_TREE = 10
# A 20 m pixel is forest when tree cover is the majority of its 10 m WorldCover pixels.
FOREST_MIN_PERCENT = 50


def _bounds_4326(grid: Grid) -> tuple[float, float, float, float]:
    from rasterio.warp import transform_bounds

    right = grid.left + grid.width * grid.resolution
    bottom = grid.top - grid.height * grid.resolution
    return transform_bounds(grid.crs, "EPSG:4326", grid.left, bottom, right, grid.top, densify_pts=21)


def _warp_window(url: str, grid: Grid, resampling: str, value: int | None = None) -> np.ndarray:
    """Reads the part of a EPSG:4326 raster over the grid and warps it onto the grid; NaN where
    the source has no data. With `value`, warps the share (0 to 100) of source pixels equal to it."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject
    from rasterio.windows import from_bounds

    west, south, east, north = _bounds_4326(grid)
    pad = 0.01
    with rasterio.open(url) as source:
        window = from_bounds(west - pad, south - pad, east + pad, north + pad, source.transform)
        window = window.round_offsets().round_lengths().intersection(
            rasterio.windows.Window(0, 0, source.width, source.height)
        )
        data = source.read(1, window=window)
        transform = source.window_transform(window)
        nodata = source.nodata
    missing = data == nodata if nodata is not None else np.zeros(data.shape, dtype=bool)
    data = np.where(data == value, 100, 0).astype("float32") if value is not None else data.astype("float32")
    data[missing] = np.nan
    target = np.full((grid.height, grid.width), np.nan, dtype="float32")
    reproject(
        source=data,
        destination=target,
        src_transform=transform,
        src_crs="EPSG:4326",
        src_nodata=np.nan,
        dst_transform=grid.transform,
        dst_crs=grid.crs,
        dst_nodata=np.nan,
        resampling=getattr(Resampling, resampling),
    )
    return target


def _tiles(grid: Grid, size: int) -> list[tuple[int, int]]:
    """(lat, west longitude as a positive number) of the source tiles of `size` degrees over the grid."""
    west, south, east, north = _bounds_4326(grid)
    lats = range(math.floor(south / size) * size, math.floor(north / size) * size + 1, size)
    lons = range(math.floor(west / size) * size, math.floor(east / size) * size + 1, size)
    return [(lat, -lon) for lat in lats for lon in lons]


def _merge(layers: list[np.ndarray]) -> np.ndarray:
    merged = layers[0]
    for layer in layers[1:]:
        merged = np.where(np.isnan(merged), layer, merged)
    return merged


def load_elevation(grid: Grid) -> np.ndarray:
    """Elevation (m) from GLO-30, bilinear onto the 20 m grid (the DEM is coarser than the grid)."""
    elevation = _merge([_warp_window(COPERNICUS_DEM_URL.format(lat=lat, lon=lon), grid, "bilinear")
                        for lat, lon in _tiles(grid, 1)])
    if np.isnan(elevation).all():
        raise RuntimeError("No GLO-30 elevation over the grid")
    return elevation


def load_forest(grid: Grid) -> np.ndarray:
    """True where tree cover is the majority of the WorldCover 10 m pixels in a 20 m pixel."""
    share = _merge([
        _warp_window(WORLDCOVER_URL.format(lat=lat, lon=lon), grid, "average", value=WORLDCOVER_TREE)
        for lat, lon in _tiles(grid, 3)
    ])
    with np.errstate(invalid="ignore"):
        return np.nan_to_num(share, nan=0.0) >= FOREST_MIN_PERCENT


def slope_aspect(elevation: np.ndarray, resolution: float) -> tuple[np.ndarray, np.ndarray]:
    """Slope and aspect in radians; aspect is the downslope azimuth clockwise from north."""
    filled = np.where(np.isnan(elevation), np.nanmean(elevation), elevation)
    d_row, d_col = np.gradient(filled, resolution)
    slope = np.arctan(np.hypot(d_row, d_col))
    aspect = np.arctan2(-d_col, d_row) % (2 * np.pi)
    return slope.astype("float32"), aspect.astype("float32")


def terrain_shadow(elevation: np.ndarray, resolution: float, sun_azimuth: float, sun_elevation: float) -> np.ndarray:
    """Pixels the sun does not reach: facing away from it (self shadow) or behind a ridge (cast
    shadow). Angles in degrees, azimuth clockwise from north.

    Cast shadow marches from each pixel towards the sun one pixel at a time and compares the
    terrain on the way with the sun ray, up to the distance where the ray clears the highest
    point of the grid. Terrain outside the grid casts no shadow.
    """
    azimuth, altitude = math.radians(sun_azimuth), math.radians(sun_elevation)
    slope, aspect = slope_aspect(elevation, resolution)
    incidence = math.sin(altitude) * np.cos(slope) + math.cos(altitude) * np.sin(slope) * np.cos(azimuth - aspect)
    shadow = incidence <= 0

    filled = np.where(np.isnan(elevation), -np.inf, elevation).astype("float32")
    tan_altitude = math.tan(altitude)
    relief = float(np.nanmax(elevation) - np.nanmin(elevation))
    steps = int(math.ceil(relief / tan_altitude / resolution))
    d_col, d_row = math.sin(azimuth), -math.cos(azimuth)
    height, width = filled.shape
    cast = np.zeros(filled.shape, dtype=bool)
    for step in range(1, steps + 1):
        row_shift, col_shift = int(round(step * d_row)), int(round(step * d_col))
        if abs(row_shift) >= height or abs(col_shift) >= width:
            break
        ahead = np.full(filled.shape, -np.inf, dtype="float32")
        ahead[
            max(0, -row_shift) : height - max(0, row_shift), max(0, -col_shift) : width - max(0, col_shift)
        ] = filled[max(0, row_shift) : height + min(0, row_shift), max(0, col_shift) : width + min(0, col_shift)]
        distance = resolution * math.hypot(row_shift, col_shift)
        cast |= ahead - filled > distance * tan_altitude
    return shadow | (cast & np.isfinite(elevation))


def load_static(grid: Grid, cache: Path | None) -> tuple[np.ndarray, np.ndarray]:
    """Elevation and forest on the grid, cached as .npy files keyed by the grid when `cache` is set."""
    key = f"{grid.crs.replace(':', '')}_{grid.left:.0f}_{grid.top:.0f}_{grid.resolution:.0f}_{grid.width}x{grid.height}"
    if cache is not None:
        paths = cache / f"elevation_{key}.npy", cache / f"forest_{key}.npy"
        if all(path.exists() for path in paths):
            return np.load(paths[0]), np.load(paths[1])
    elevation, forest = load_elevation(grid), load_forest(grid)
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
        np.save(paths[0], elevation)
        np.save(paths[1], forest)
    return elevation, forest
