"""Input layers of the reference sample on the domain grid: GLO-30 elevation, WorldCover
tree cover, Sentinel-2 L2A scene classes (cloud only) and Sentinel-2 L1C reflectance."""

import json
import math
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import numpy as np

from pipelines.s2.domain import Grid
from pipelines.s2.mosaic import scale_offset
from pipelines.s2.stac import STAC_SEARCH_URL, orbit_of, tile_of

GDAL_OPTIONS = {
    "AWS_NO_SIGN_REQUEST": "YES",
    "AWS_REGION": "eu-central-1",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.jp2",
    "GDAL_HTTP_MULTIRANGE": "YES",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MAX_RETRY": "4",
    "GDAL_HTTP_RETRY_DELAY": "3",
}
READ_THREADS = 8

# Copernicus DEM GLO-30 (ESA / Airbus, Copernicus licence), 1-degree COG tiles on AWS Open Data.
GLO30_URL = (
    "https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/"
    "Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM.tif"
)
# ESA WorldCover 10 m 2021 v200 (Zanaga et al. 2022, CC BY 4.0), 3-degree COG tiles on AWS Open Data.
WORLDCOVER_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
)
WORLDCOVER_TREE_COVER = 10

L1C_COLLECTION = "sentinel-2-l1c"
L1C_BANDS = ("blue", "green", "red", "nir", "swir16")
# Sen2Cor scene classes 8, 9, 10: cloud medium and high probability, thin cirrus
# (ESA S2 L2A Product Specification). Used only to place the cloud-edge sampling stratum.
SCL_CLOUD = (8, 9, 10)
SCL_NODATA = 0


def padded(grid: Grid, metres: float) -> Grid:
    """The grid grown by `metres` (rounded up to whole pixels) on every side."""
    pixels = int(math.ceil(metres / grid.resolution))
    step = pixels * grid.resolution
    return replace(
        grid,
        left=grid.left - step,
        top=grid.top + step,
        width=grid.width + 2 * pixels,
        height=grid.height + 2 * pixels,
    )


def resampled(grid: Grid, resolution: float) -> Grid:
    """Same extent at another resolution that divides or is a multiple of the grid's."""
    width = grid.width * grid.resolution / resolution
    height = grid.height * grid.resolution / resolution
    if width % 1 or height % 1:
        raise ValueError(f"{resolution} m does not tile a {grid.width}x{grid.height} grid of {grid.resolution} m")
    return replace(grid, resolution=resolution, width=int(width), height=int(height))


def bounds_lonlat(grid: Grid) -> tuple[float, float, float, float]:
    from rasterio.warp import transform_bounds

    right = grid.left + grid.width * grid.resolution
    bottom = grid.top - grid.height * grid.resolution
    return transform_bounds(grid.crs, "EPSG:4326", grid.left, bottom, right, grid.top)


def _reproject_tiles(urls: list[str], grid: Grid, resampling: str, dtype: str, fill: float) -> np.ndarray:
    import rasterio
    from rasterio.warp import Resampling, reproject

    out = np.full((grid.height, grid.width), fill, dtype=dtype)
    with rasterio.Env(**GDAL_OPTIONS):
        for url in urls:
            with rasterio.open(url) as source:
                part = np.full_like(out, fill)
                reproject(
                    rasterio.band(source, 1),
                    part,
                    dst_transform=grid.transform,
                    dst_crs=grid.crs,
                    dst_nodata=fill,
                    resampling=getattr(Resampling, resampling),
                )
                take = part != fill if not np.isnan(fill) else ~np.isnan(part)
                out[take] = part[take]
    return out


def glo30_urls(grid: Grid) -> list[str]:
    west, south, east, north = bounds_lonlat(grid)
    urls = []
    for lat in range(math.floor(south), math.floor(north) + 1):
        for lon in range(math.floor(west), math.floor(east) + 1):
            lat_name = f"N{lat:02d}" if lat >= 0 else f"S{-lat:02d}"
            lon_name = f"E{lon:03d}" if lon >= 0 else f"W{-lon:03d}"
            urls.append(GLO30_URL.format(lat=lat_name, lon=lon_name))
    return urls


def read_elevation(grid: Grid) -> np.ndarray:
    """GLO-30 heights (m, EGM2008) bilinearly resampled to the grid; NaN where no tile."""
    return _reproject_tiles(glo30_urls(grid), grid, "bilinear", "float32", float("nan"))


def worldcover_urls(grid: Grid) -> list[str]:
    west, south, east, north = bounds_lonlat(grid)
    urls = []
    for lat in range(math.floor(south / 3) * 3, math.floor(north / 3) * 3 + 1, 3):
        for lon in range(math.floor(west / 3) * 3, math.floor(east / 3) * 3 + 1, 3):
            lat_name = f"N{lat:02d}" if lat >= 0 else f"S{-lat:02d}"
            lon_name = f"E{lon:03d}" if lon >= 0 else f"W{-lon:03d}"
            urls.append(WORLDCOVER_URL.format(tile=f"{lat_name}{lon_name}"))
    return urls


def read_tree_fraction(grid: Grid) -> np.ndarray:
    """Share of the 10 m WorldCover cells inside each grid pixel that are tree cover."""
    fine = resampled(grid, 10.0)
    classes = _reproject_tiles(worldcover_urls(fine), fine, "nearest", "uint8", 0)
    factor = int(grid.resolution / 10.0)
    trees = (classes == WORLDCOVER_TREE_COVER).astype("float32")
    return trees.reshape(grid.height, factor, grid.width, factor).mean(axis=(1, 3))


def read_aligned(href: str, grid: Grid) -> np.ndarray:
    """The part of one Sentinel-2 tile band that falls on the grid, zero where the tile has no
    pixels. The grid resolution must be a whole multiple of the band's pixel size (coarser
    grids are read from the JPEG 2000 / COG overviews and decimated) or half of it (each
    pixel repeated 2x2)."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.windows import Window

    # rasterio.Env is per thread, and the SCL readers run in a thread pool.
    with rasterio.Env(**GDAL_OPTIONS), rasterio.open(href) as source:
        pixel = source.res[0]
    if grid.resolution < pixel:
        if pixel != 2 * grid.resolution or grid.width % 2 or grid.height % 2:
            raise ValueError(f"{href}: only 2x upsampling onto an even-sized grid is supported")
        return read_aligned(href, resampled(grid, pixel)).repeat(2, axis=0).repeat(2, axis=1)
    with rasterio.Env(**GDAL_OPTIONS), rasterio.open(href) as source:
        if str(source.crs) != grid.crs:
            raise ValueError(f"{href} is in {source.crs}, expected {grid.crs}")
        factor = int(round(grid.resolution / pixel))
        if factor * pixel != grid.resolution:
            raise ValueError(f"{href} pixel size {pixel} does not nest in {grid.resolution} m")
        col0 = (grid.left - source.transform.c) / pixel
        row0 = (source.transform.f - grid.top) / pixel
        if col0 % 1 or row0 % 1:
            raise ValueError(f"{href} pixels are not aligned with the grid")
        col0, row0 = int(col0), int(row0)
        out = np.zeros((grid.height, grid.width), dtype=source.dtypes[0])
        # First and last grid cells that lie fully inside the tile.
        first_col = max(0, math.ceil(-col0 / factor))
        first_row = max(0, math.ceil(-row0 / factor))
        last_col = min(grid.width, (source.width - col0) // factor)
        last_row = min(grid.height, (source.height - row0) // factor)
        if last_col <= first_col or last_row <= first_row:
            return out
        window = Window(
            col0 + first_col * factor,
            row0 + first_row * factor,
            (last_col - first_col) * factor,
            (last_row - first_row) * factor,
        )
        out[first_row:last_row, first_col:last_col] = source.read(
            1,
            window=window,
            out_shape=(last_row - first_row, last_col - first_col),
            resampling=Resampling.nearest,
        )
        return out


def s3_to_vsi(href: str) -> str:
    return "/vsis3/" + href[len("s3://") :] if href.startswith("s3://") else href


def search_l1c(day: date, orbit: str, geometry: dict) -> list[dict]:
    """L1C items of one date and relative orbit over the geometry, latest processing first."""
    body = {
        "collections": [L1C_COLLECTION],
        "intersects": geometry,
        "datetime": f"{day.isoformat()}T00:00:00Z/{day.isoformat()}T23:59:59Z",
        "limit": 100,
    }
    request = urllib.request.Request(
        STAC_SEARCH_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        items = json.load(response)["features"]
    items = [item for item in items if orbit_of(item) == orbit]
    items.sort(key=lambda item: item["properties"]["s2:generation_time"], reverse=True)
    return sorted(items, key=tile_of)


@dataclass(frozen=True)
class L1CMosaic:
    """Top-of-atmosphere reflectance per band (NaN where no tile) and, per pixel, the index
    in `item_ids` of the tile it was taken from (-1 where none)."""

    reflectance: dict[str, np.ndarray]
    source: np.ndarray
    item_ids: tuple[str, ...]


def build_l1c(items: list[dict], grid: Grid, bands: tuple[str, ...] = L1C_BANDS) -> L1CMosaic:
    """Mosaic of the L1C tiles of one acquisition. Each pixel takes the first tile, in the
    items' order, with data in every band, so all bands of a pixel come from one tile."""
    # Sequential on purpose: concurrent JPEG 2000 reads through GDAL's OpenJPEG driver
    # (GDAL 3.10.3, rasterio 1.4.4) returned corrupted blocks; callers parallelise by process.
    shape = (grid.height, grid.width)
    reflectance = {band: np.full(shape, np.nan, dtype="float32") for band in bands}
    source = np.full(shape, -1, dtype="int8")
    for index, item in enumerate(items):
        raw = {band: read_aligned(s3_to_vsi(item["assets"][band]["href"]), grid) for band in bands}
        has_data = np.logical_and.reduce([raw[band] != 0 for band in bands])
        take = (source < 0) & has_data
        source[take] = index
        for band in bands:
            scale, offset = scale_offset(item, band)
            reflectance[band][take] = raw[band][take].astype("float32") * scale + offset
    return L1CMosaic(reflectance, source, tuple(item["id"] for item in items))


def save_l1c(mosaic: L1CMosaic, grid: Grid, path: Path) -> None:
    import rasterio

    bands = list(mosaic.reflectance)
    path.parent.mkdir(parents=True, exist_ok=True)
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
    options = {"count": len(bands), "dtype": "float32", "nodata": float("nan"), "predictor": 3}
    with rasterio.open(path, "w", **options, **profile) as out:
        for number, band in enumerate(bands, start=1):
            out.write(mosaic.reflectance[band], number)
            out.set_band_description(number, band)
    with rasterio.open(path.with_suffix(".source.tif"), "w", count=1, dtype="int8", nodata=-1, **profile) as out:
        out.write(mosaic.source, 1)
    path.with_suffix(".json").write_text(json.dumps({"item_ids": list(mosaic.item_ids)}) + "\n", encoding="utf-8")


def load_l1c(path: Path) -> L1CMosaic:
    import rasterio

    with rasterio.open(path) as source:
        reflectance = {source.descriptions[i]: source.read(i + 1) for i in range(source.count)}
    with rasterio.open(path.with_suffix(".source.tif")) as source:
        tile = source.read(1)
    item_ids = tuple(json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))["item_ids"])
    return L1CMosaic(reflectance, tile, item_ids)


def cached_l1c(cache: Path, day: date, orbit: str, geometry: dict, grid: Grid) -> L1CMosaic:
    path = cache / f"l1c_{day.isoformat()}_{orbit}_{int(grid.resolution)}m.tif"
    if not path.exists():
        save_l1c(build_l1c(search_l1c(day, orbit, geometry), grid), grid, path)
    return load_l1c(path)


def read_scl(items: list[dict], grid: Grid) -> np.ndarray:
    """Sen2Cor scene classes of one L2A acquisition on a 20 m grid (first tile with data wins)."""
    with ThreadPoolExecutor(READ_THREADS) as pool:
        tiles = list(pool.map(lambda item: read_aligned(item["assets"]["scl"]["href"], grid), items))
    scl = np.zeros((grid.height, grid.width), dtype="uint8")
    for tile in tiles:
        take = (scl == SCL_NODATA) & (tile != SCL_NODATA)
        scl[take] = tile[take]
    return scl
