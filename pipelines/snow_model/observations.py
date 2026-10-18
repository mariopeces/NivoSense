import json
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from .grid import OBSERVATION_RESOLUTION_M, Grid

STAC_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-l2a"
NDSI_THRESHOLD = 0.4
MIN_GREEN_REFLECTANCE = 0.1
INVALID_SCL = (0, 1, 3, 8, 9, 10)
READ_THREADS = 8
GDAL_OPTIONS = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_MAX_RETRY": "4",
    "GDAL_HTTP_RETRY_DELAY": "3",
}


@dataclass(frozen=True)
class Scene:
    day: date
    items: tuple[dict, ...]

    @property
    def cloud_cover(self) -> float:
        values = [item["properties"].get("eo:cloud_cover", 100.0) for item in self.items]
        return sum(values) / len(values)


def search_scenes(
    bbox: tuple[float, float, float, float], start: date, end: date, max_cloud: float
) -> list[Scene]:
    body = {
        "collections": [COLLECTION],
        "bbox": list(bbox),
        "datetime": f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z",
        "limit": 200,
        "query": {"eo:cloud_cover": {"lt": max_cloud}},
    }
    by_day = defaultdict(list)
    request = urllib.request.Request(
        STAC_SEARCH_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    while request is not None:
        with urllib.request.urlopen(request, timeout=60) as response:
            page = json.load(response)
        for item in page["features"]:
            by_day[date.fromisoformat(item["properties"]["datetime"][:10])].append(item)
        next_link = next((link for link in page.get("links", []) if link["rel"] == "next"), None)
        request = (
            urllib.request.Request(
                next_link["href"],
                data=json.dumps(next_link["body"]).encode(),
                headers={"Content-Type": "application/json"},
            )
            if next_link and next_link.get("method") == "POST"
            else None
        )
    return [Scene(day, tuple(items)) for day, items in sorted(by_day.items())]


def choose_scenes(scenes: list[Scene], limit: int, min_gap_days: int) -> list[Scene]:
    """Greedy pick of the clearest scenes, keeping a minimum spacing between dates."""
    chosen: list[Scene] = []
    for scene in sorted(scenes, key=lambda item: item.cloud_cover):
        if len(chosen) >= limit:
            break
        if all(abs((scene.day - other.day).days) >= min_gap_days for other in chosen):
            chosen.append(scene)
    return sorted(chosen, key=lambda item: item.day)


def reflectance_offset(item: dict) -> float:
    properties = item["properties"]
    if properties.get("earthsearch:boa_offset_applied"):
        return 0.0
    baseline = float(properties.get("s2:processing_baseline", "0") or 0)
    return 1000.0 if baseline >= 4.0 else 0.0


def _read_band(href: str, fine: Grid, resampling: str, band: int = 1):
    """Reads one band onto the fine grid, returning the array and a boolean coverage mask."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT
    from rasterio.windows import Window

    method = Resampling[resampling]
    with rasterio.open(href) as source:
        if str(source.crs) != fine.crs:
            with WarpedVRT(
                source,
                crs=fine.crs,
                transform=fine.transform,
                width=fine.width,
                height=fine.height,
                resampling=method,
            ) as vrt:
                array = vrt.read(band)
            return array, np.ones(array.shape, dtype=bool)

        scale = source.res[0]
        col0 = (fine.left - source.transform.c) / scale
        row0 = (source.transform.f - fine.top) / scale
        if col0 % 1 or row0 % 1:
            raise ValueError("Observation grid is not aligned with the source pixels")
        columns = fine.width * OBSERVATION_RESOLUTION_M / scale
        rows = fine.height * OBSERVATION_RESOLUTION_M / scale
        col_start = max(0, int(col0))
        row_start = max(0, int(row0))
        col_stop = min(source.width, int(col0 + columns))
        row_stop = min(source.height, int(row0 + rows))
        array = np.zeros((fine.height, fine.width), dtype=source.dtypes[0])
        covered = np.zeros((fine.height, fine.width), dtype=bool)
        if col_stop <= col_start or row_stop <= row_start:
            return array, covered
        factor = int(round(scale / OBSERVATION_RESOLUTION_M))
        out_rows = (row_stop - row_start) * factor
        out_cols = (col_stop - col_start) * factor
        block = source.read(
            band,
            window=Window(col_start, row_start, col_stop - col_start, row_stop - row_start),
            out_shape=(out_rows, out_cols),
            resampling=method,
        )
        top = int(round((row_start - row0) * factor))
        left = int(round((col_start - col0) * factor))
        array[top : top + out_rows, left : left + out_cols] = block
        covered[top : top + out_rows, left : left + out_cols] = True
        return array, covered


def snow_mask(scene: Scene, fine: Grid) -> tuple[np.ndarray, np.ndarray]:
    """Snow and valid-observation masks at 10 m, merged over the tiles of one acquisition day."""
    import rasterio

    jobs = []
    for index, item in enumerate(scene.items):
        jobs.append((index, "green", item["assets"]["green"]["href"], "nearest"))
        jobs.append((index, "swir16", item["assets"]["swir16"]["href"], "bilinear"))
        jobs.append((index, "scl", item["assets"]["scl"]["href"], "nearest"))

    with rasterio.Env(**GDAL_OPTIONS):
        with ThreadPoolExecutor(READ_THREADS) as pool:
            results = list(pool.map(lambda job: _read_band(job[2], fine, job[3]), jobs))

    bands = {(job[0], job[1]): result for job, result in zip(jobs, results)}
    snow = np.zeros((fine.height, fine.width), dtype=bool)
    valid = np.zeros((fine.height, fine.width), dtype=bool)
    for index, item in enumerate(scene.items):
        green, covered = bands[(index, "green")]
        swir, _ = bands[(index, "swir16")]
        classification, _ = bands[(index, "scl")]
        offset = reflectance_offset(item)
        green_reflectance = (green.astype("float32") - offset) / 10000.0
        swir_reflectance = (swir.astype("float32") - offset) / 10000.0
        total = green_reflectance + swir_reflectance
        ndsi = np.divide(
            green_reflectance - swir_reflectance,
            total,
            out=np.zeros_like(total),
            where=total > 0,
        )
        usable = covered & ~np.isin(classification, INVALID_SCL) & (green > 0)
        tile_snow = usable & (ndsi >= NDSI_THRESHOLD) & (green_reflectance >= MIN_GREEN_REFLECTANCE)
        snow |= tile_snow
        valid |= usable
    return snow, valid


def true_colour(scene: Scene, fine: Grid, cache: Path) -> Path:
    """Sentinel-2 true colour at 10 m for one acquisition day, as a cached JPEG."""
    from PIL import Image
    import rasterio

    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"s2-rgb-{fine.signature()}-{scene.day.isoformat()}.jpg"
    if path.exists():
        return path
    jobs = [
        (index, band, item["assets"]["visual"]["href"])
        for index, item in enumerate(scene.items)
        for band in (1, 2, 3)
    ]
    with rasterio.Env(**GDAL_OPTIONS):
        with ThreadPoolExecutor(READ_THREADS) as pool:
            results = list(pool.map(lambda job: _read_band(job[2], fine, "nearest", job[1]), jobs))
    image = np.zeros((fine.height, fine.width, 3), dtype="uint8")
    filled = np.zeros((fine.height, fine.width), dtype=bool)
    for index in range(len(scene.items)):
        channels = [
            result[0] for job, result in zip(jobs, results) if job[0] == index
        ]
        tile = np.stack(channels, axis=-1)
        usable = (tile.max(axis=-1) > 0) & ~filled
        image[usable] = tile[usable]
        filled |= usable
    Image.fromarray(image, mode="RGB").save(path, quality=82, optimize=True)
    return path


def aggregate(snow: np.ndarray, valid: np.ndarray, factor: int) -> tuple[np.ndarray, np.ndarray]:
    """Snow fraction and valid fraction of each model cell from the 10 m masks."""
    height, width = snow.shape
    shape = (height // factor, factor, width // factor, factor)
    valid_count = valid.reshape(shape).sum(axis=(1, 3), dtype="float32")
    snow_count = snow.reshape(shape).sum(axis=(1, 3), dtype="float32")
    snow_fraction = np.divide(
        snow_count, valid_count, out=np.zeros_like(snow_count), where=valid_count > 0
    )
    return snow_fraction, valid_count / (factor * factor)


def cached_snow_mask(scene: Scene, fine: Grid, cache: Path) -> tuple[np.ndarray, np.ndarray]:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"s2-{fine.signature()}-{scene.day.isoformat()}.npz"
    if path.exists():
        with np.load(path) as stored:
            count = fine.height * fine.width
            snow = np.unpackbits(stored["snow"], count=count).astype(bool)
            valid = np.unpackbits(stored["valid"], count=count).astype(bool)
        return snow.reshape(fine.height, fine.width), valid.reshape(fine.height, fine.width)
    snow, valid = snow_mask(scene, fine)
    np.savez_compressed(
        path,
        snow=np.packbits(snow.ravel()),
        valid=np.packbits(valid.ravel()),
    )
    return snow, valid
