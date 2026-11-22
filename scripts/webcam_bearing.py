"""Webcam bearing and field of view from a DEM skyline match.

For each camera with a position and a live frame:

1. Render the expected skyline from the camera position: for every azimuth
   (0.05 degree step) march a ray over the Copernicus GLO-30 DEM out to
   ``MAX_RANGE_M`` and keep the highest elevation angle, corrected for Earth
   curvature and standard refraction.
2. Extract the photo skyline: the lower edge of the sky region connected to
   the top of the frame, column by column.
3. Fit a pinhole camera (bearing, horizontal field of view, pitch, roll) so
   that the photo skyline, projected to azimuth and elevation angle, lies on
   the rendered skyline. Coarse exhaustive search over bearing and field of
   view, then a local pattern search over all four parameters.
4. Judge the fit (residual against the angle a DEM cell subtends at the
   skyline distance, uniqueness against the best fit at another bearing,
   bearing shift when the camera position moves by ``POSITION_TOLERANCE_M``)
   and draw a comparison image: rendered skyline and named peaks (OpenStreetMap
   ``natural=peak``) over the photo.

A camera whose fit fails any check is written as unsettled with the reason, so
a person can confirm it; no bearing is written for it. The approach follows
the photo-to-DEM horizon alignment of Baboud et al. (2011, CVPR, "Automatic
photo-to-terrain alignment for the annotation of mountain pictures") and the
webcam georectification of Portenier et al. (2020, Hydrological Processes,
"Towards a webcam-based snow cover monitoring network").
"""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import io
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.ingest_webcams import (  # noqa: E402
    fetch_bytes,
    fetch_image,
    image_problem,
    parse_datex_cameras,
    static_cameras,
)
from pipelines.snow_model.dem import COPERNICUS_URL  # noqa: E402

UTM_CRS = "EPSG:32630"
DEM_RESOLUTION_M = 30.0
# From 3,000 m on the crest the skyline to the north lies 70 to 90 km away
# (Sierra Magina, Sierra de Cazorla); 100 km keeps it inside the render.
MAX_RANGE_M = 100_000.0
AZIMUTH_STEP_DEG = 0.05
EARTH_RADIUS_M = 6_371_000.0
# Coefficient of terrestrial refraction for daytime lines of sight; the usual
# geodetic value (Hirt et al. 2010, "Monitoring of the refraction coefficient
# in the lower atmosphere").
REFRACTION_K = 0.13
# Camera height above the DEM surface. GLO-30 is a surface model, so roofs and
# masts are partly in it; the fit is repeated at each height and the best kept.
CAMERA_HEIGHTS_M = (3.0, 10.0, 25.0)
# Feratel gives one position per camera site and several views share it, so a
# view can sit a few hundred metres away; this is the shift the bearing must
# survive to count as settled.
POSITION_TOLERANCE_M = 150.0
FOV_RANGE_DEG = (20.0, 110.0)
PITCH_RANGE_DEG = (-30.0, 20.0)
# Fixed webcams are mounted close to level; a wider roll lets a wrong bearing
# twist a ridge into place.
ROLL_RANGE_DEG = (-10.0, 10.0)
# Fraction of skyline columns kept by the trimmed cost; the rest are masts,
# lift cables, buildings and other objects that are not in the DEM.
TRIM_KEEP = 0.75
WORK_WIDTH = 960
# The feratel frames carry a caption band at the bottom and the resort logo at
# the top right; both are masked before the skyline is read.
FERATEL_MASKS = ((0.0, 0.925, 1.0, 1.0), (0.86, 0.0, 1.0, 0.085))
PRADOLLANO_MASKS = ((0.0, 0.0, 1.0, 0.07),)
# Uniqueness: the best fit at a bearing more than UNIQUE_SEPARATION_DEG away
# must cost at least UNIQUE_RATIO times the best.
UNIQUE_SEPARATION_DEG = 10.0
UNIQUE_RATIO = 2.0
# Bearing shift under the position test, in degrees, for each confidence.
SPREAD_HIGH_DEG = 2.0
SPREAD_MEDIUM_DEG = 5.0
CONSISTENT_RATIO = 2.0
MIN_SKYLINE_FRACTION = 0.3
USER_AGENT = "NivoSense-webcam-bearing (+https://github.com/mariopeces/NivoSense)"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


@dataclass
class Dem:
    elevation: np.ndarray
    west: float
    north: float
    resolution: float
    # Views of one feratel station share a position, so their horizons are reused.
    horizons: dict[tuple[float, float, float], "Horizon"] = field(default_factory=dict)

    def sample(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Bilinear elevation at UTM coordinates; NaN outside the grid."""
        col = (x - self.west) / self.resolution - 0.5
        row = (self.north - y) / self.resolution - 0.5
        rows, cols = self.elevation.shape
        c0 = np.floor(col).astype(np.int64)
        r0 = np.floor(row).astype(np.int64)
        inside = (c0 >= 0) & (r0 >= 0) & (c0 < cols - 1) & (r0 < rows - 1)
        c0 = np.clip(c0, 0, cols - 2)
        r0 = np.clip(r0, 0, rows - 2)
        fc = col - c0
        fr = row - r0
        z = self.elevation
        top = z[r0, c0] * (1 - fc) + z[r0, c0 + 1] * fc
        bottom = z[r0 + 1, c0] * (1 - fc) + z[r0 + 1, c0 + 1] * fc
        value = top * (1 - fr) + bottom * fr
        return np.where(inside, value, np.nan)


@dataclass
class Horizon:
    azimuth: np.ndarray
    elevation_deg: np.ndarray
    distance_m: np.ndarray

    def at(self, azimuth_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        index = np.round((np.mod(azimuth_deg, 360.0)) / AZIMUTH_STEP_DEG).astype(np.int64)
        index %= self.azimuth.size
        return self.elevation_deg[index], self.distance_m[index]


@dataclass
class Pose:
    bearing: float
    fov: float
    pitch: float
    roll: float


@dataclass
class Fit:
    pose: Pose
    height_m: float
    cost_px: float
    alternative_cost_px: float
    horizon: Horizon


def to_utm(lon: float, lat: float) -> tuple[float, float]:
    from rasterio.warp import transform

    xs, ys = transform("EPSG:4326", UTM_CRS, [lon], [lat])
    return float(xs[0]), float(ys[0])


def to_lonlat(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from rasterio.warp import transform

    lons, lats = transform(UTM_CRS, "EPSG:4326", list(x), list(y))
    return np.asarray(lons), np.asarray(lats)


def load_dem(centres: list[tuple[float, float]], cache_dir: Path) -> Dem:
    """GLO-30 resampled to a 30 m UTM grid covering MAX_RANGE_M around every camera."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.warp import reproject, transform_bounds

    xs, ys = zip(*(to_utm(lon, lat) for lon, lat in centres))
    pad = MAX_RANGE_M + 2 * DEM_RESOLUTION_M
    west = math.floor((min(xs) - pad) / DEM_RESOLUTION_M) * DEM_RESOLUTION_M
    north = math.ceil((max(ys) + pad) / DEM_RESOLUTION_M) * DEM_RESOLUTION_M
    east = math.ceil((max(xs) + pad) / DEM_RESOLUTION_M) * DEM_RESOLUTION_M
    south = math.floor((min(ys) - pad) / DEM_RESOLUTION_M) * DEM_RESOLUTION_M
    width = int(round((east - west) / DEM_RESOLUTION_M))
    height = int(round((north - south) / DEM_RESOLUTION_M))
    key = hashlib.sha256(f"{west},{north},{width},{height}".encode()).hexdigest()[:12]
    cached = cache_dir / f"glo30_utm30n_{key}.npy"
    if cached.exists():
        return Dem(np.load(cached), west, north, DEM_RESOLUTION_M)

    dst_transform = from_origin(west, north, DEM_RESOLUTION_M, DEM_RESOLUTION_M)
    elevation = np.full((height, width), np.nan, dtype="float32")
    lon_min, lat_min, lon_max, lat_max = transform_bounds(UTM_CRS, "EPSG:4326", west, south, east, north)
    for lon in range(math.floor(lon_min), math.floor(lon_max) + 1):
        for lat in range(math.floor(lat_min), math.floor(lat_max) + 1):
            url = COPERNICUS_URL.format(
                ns="N" if lat >= 0 else "S",
                lat=abs(lat),
                ew="E" if lon >= 0 else "W",
                lon=abs(lon),
            )
            try:
                source = rasterio.open(f"/vsicurl/{url}")
            except rasterio.errors.RasterioIOError:
                # Open sea tiles do not exist in GLO-30.
                print(f"  DEM tile absent: {url}", file=sys.stderr)
                continue
            with source:
                tile = np.full(elevation.shape, np.nan, dtype="float32")
                reproject(
                    source=rasterio.band(source, 1),
                    destination=tile,
                    dst_transform=dst_transform,
                    dst_crs=UTM_CRS,
                    dst_nodata=np.nan,
                    resampling=Resampling.bilinear,
                )
            elevation = np.where(np.isnan(elevation), tile, elevation)
            print(f"  DEM tile read: {url}", file=sys.stderr)
    # Sea and missing tiles are at sea level for the purpose of a skyline.
    elevation = np.where(np.isnan(elevation), 0.0, elevation).astype("float32")
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(cached, elevation)
    return Dem(elevation, west, north, DEM_RESOLUTION_M)


def ray_distances() -> np.ndarray:
    """Sample distances along a ray: half a DEM cell near the camera, coarser far away."""
    near = np.arange(15.0, 3_000.0, 15.0)
    middle = np.arange(3_000.0, 15_000.0, 30.0)
    far = np.arange(15_000.0, MAX_RANGE_M, 60.0)
    return np.concatenate([near, middle, far])


def render_horizon(dem: Dem, x: float, y: float, camera_z: float) -> Horizon:
    key = (round(x, 1), round(y, 1), round(camera_z, 1))
    if key not in dem.horizons:
        dem.horizons[key] = _render_horizon(dem, x, y, camera_z)
    return dem.horizons[key]


def _render_horizon(dem: Dem, x: float, y: float, camera_z: float) -> Horizon:
    azimuth = np.arange(0.0, 360.0, AZIMUTH_STEP_DEG)
    distances = ray_distances()
    drop = distances**2 * (1.0 - REFRACTION_K) / (2.0 * EARTH_RADIUS_M)
    elevation = np.empty(azimuth.size)
    distance = np.empty(azimuth.size)
    for start in range(0, azimuth.size, 600):
        az = np.radians(azimuth[start : start + 600])[:, None]
        px = x + np.sin(az) * distances[None, :]
        py = y + np.cos(az) * distances[None, :]
        z = dem.sample(px, py)
        angle = np.degrees(np.arctan2(z - drop[None, :] - camera_z, distances[None, :]))
        angle = np.where(np.isnan(angle), -90.0, angle)
        best = np.argmax(angle, axis=1)
        elevation[start : start + 600] = angle[np.arange(best.size), best]
        distance[start : start + 600] = distances[best]
    return Horizon(azimuth, elevation, distance)


def otsu_threshold(values: np.ndarray) -> float:
    hist, edges = np.histogram(values, bins=256, range=(0.0, 255.0))
    hist = hist.astype(float)
    centres = (edges[:-1] + edges[1:]) / 2
    weight = np.cumsum(hist)
    mean = np.cumsum(hist * centres)
    total = weight[-1]
    between = (mean[-1] * weight / total - mean) ** 2 / np.maximum(weight * (total - weight), 1e-9)
    return float(centres[int(np.argmax(between))])


def extract_skyline(
    image: Image.Image, masks: tuple[tuple[float, float, float, float], ...]
) -> tuple[np.ndarray, np.ndarray]:
    """Column and row (full-size pixels) of the sky-to-ground edge, sampled on
    WORK_WIDTH columns; the row is NaN where no edge is found.

    The sky is the bright region (Otsu threshold on luminance) connected to the
    top of the frame. Masked overlay boxes count as sky at the top of the frame
    and end the column below it.
    """
    scale = WORK_WIDTH / image.width
    small = image.convert("RGB").resize((WORK_WIDTH, round(image.height * scale)), Image.Resampling.BILINEAR)
    rgb = np.asarray(small, dtype=float)
    luminance = rgb.mean(axis=2)
    height, width = luminance.shape
    masked = np.zeros_like(luminance, dtype=bool)
    for x0, y0, x1, y1 in masks:
        masked[round(y0 * height) : round(y1 * height), round(x0 * width) : round(x1 * width)] = True
    threshold = otsu_threshold(luminance[~masked])
    sky = (luminance > threshold) | masked
    bottom = height
    for x0, y0, x1, y1 in masks:
        if y1 >= 0.999 and x0 <= 0.001 and x1 >= 0.999:
            bottom = min(bottom, round(y0 * height))
    skyline = np.full(width, np.nan)
    for column in range(width):
        if not sky[0, column]:
            continue
        ground = np.flatnonzero(~sky[:bottom, column])
        if ground.size == 0:
            continue
        row = int(ground[0])
        if masked[row - 1, column] or row < 2:
            continue
        skyline[column] = row
    # A short median filter removes single-column spikes (cables, pylons).
    filtered = skyline.copy()
    for column in range(2, width - 2):
        window = skyline[column - 2 : column + 3]
        if np.isfinite(window).sum() >= 3:
            filtered[column] = np.nanmedian(window)
    columns = (np.arange(width) + 0.5) / scale - 0.5
    return columns, filtered / scale


def pixel_rays(
    columns: np.ndarray, rows: np.ndarray, width: int, height: int, pose: Pose
) -> tuple[np.ndarray, np.ndarray]:
    """Azimuth and elevation angle (degrees) of image pixels for a pinhole camera."""
    focal = (width / 2) / math.tan(math.radians(pose.fov) / 2)
    u = columns - (width - 1) / 2
    v = rows - (height - 1) / 2
    theta, tau, rho = (math.radians(a) for a in (pose.bearing, pose.pitch, pose.roll))
    forward = np.array([math.sin(theta) * math.cos(tau), math.cos(theta) * math.cos(tau), math.sin(tau)])
    right = np.array([math.cos(theta), -math.sin(theta), 0.0])
    up = np.array([-math.sin(theta) * math.sin(tau), -math.cos(theta) * math.sin(tau), math.cos(tau)])
    right, up = right * math.cos(rho) + up * math.sin(rho), up * math.cos(rho) - right * math.sin(rho)
    direction = focal * forward[None, :] + u[:, None] * right[None, :] - v[:, None] * up[None, :]
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    azimuth = np.degrees(np.arctan2(direction[:, 0], direction[:, 1])) % 360.0
    elevation = np.degrees(np.arcsin(direction[:, 2]))
    return azimuth, elevation


def project(
    azimuth: np.ndarray, elevation: np.ndarray, width: int, height: int, pose: Pose
) -> tuple[np.ndarray, np.ndarray]:
    """Image column and row of world directions; NaN behind the camera."""
    focal = (width / 2) / math.tan(math.radians(pose.fov) / 2)
    theta, tau, rho = (math.radians(a) for a in (pose.bearing, pose.pitch, pose.roll))
    forward = np.array([math.sin(theta) * math.cos(tau), math.cos(theta) * math.cos(tau), math.sin(tau)])
    right = np.array([math.cos(theta), -math.sin(theta), 0.0])
    up = np.array([-math.sin(theta) * math.sin(tau), -math.cos(theta) * math.sin(tau), math.cos(tau)])
    right, up = right * math.cos(rho) + up * math.sin(rho), up * math.cos(rho) - right * math.sin(rho)
    az = np.radians(azimuth)
    el = np.radians(elevation)
    world = np.stack([np.sin(az) * np.cos(el), np.cos(az) * np.cos(el), np.sin(el)], axis=1)
    depth = world @ forward
    with np.errstate(divide="ignore", invalid="ignore"):
        u = focal * (world @ right) / depth
        v = -focal * (world @ up) / depth
    u = np.where(depth > 0, u, np.nan)
    v = np.where(depth > 0, v, np.nan)
    return u + (width - 1) / 2, v + (height - 1) / 2


def focal_length(width: int, fov: float) -> float:
    return (width / 2) / math.tan(math.radians(fov) / 2)


def trimmed_cost(residual: np.ndarray) -> float:
    magnitude = np.sort(np.abs(residual))
    keep = max(1, int(magnitude.size * TRIM_KEEP))
    return float(magnitude[:keep].mean())


def coarse_search(horizon: Horizon, columns: np.ndarray, rows: np.ndarray, width: int, height: int) -> np.ndarray:
    """Cost (pixels) for every (bearing, fov) on a 0.5 x 2 degree grid, pitch solved per cell, roll 0.

    Costs are reprojection errors in image pixels: measured in degrees, a
    narrower field of view would always look better.

    With zero roll, pitch shifts the elevation of every column by nearly the
    same angle, so the best pitch is the median residual.
    """
    bearings = np.arange(0.0, 360.0, 0.5)
    fovs = np.arange(FOV_RANGE_DEG[0], FOV_RANGE_DEG[1] + 0.1, 2.0)
    costs = np.full((bearings.size, fovs.size), np.inf)
    u = columns - (width - 1) / 2
    v = rows - (height - 1) / 2
    for j, fov in enumerate(fovs):
        focal = (width / 2) / math.tan(math.radians(fov) / 2)
        offset = np.degrees(np.arctan2(u, focal))
        photo = np.degrees(np.arctan2(-v, np.hypot(focal, u)))
        rendered, _ = horizon.at(bearings[:, None] + offset[None, :])
        residual = photo[None, :] - rendered
        residual -= np.median(residual, axis=1)[:, None]
        magnitude = np.sort(np.abs(residual), axis=1)
        keep = max(1, int(magnitude.shape[1] * TRIM_KEEP))
        costs[:, j] = magnitude[:, :keep].mean(axis=1) * focal * math.pi / 180
    return costs


def pose_cost(horizon: Horizon, columns: np.ndarray, rows: np.ndarray, width: int, height: int, pose: Pose) -> float:
    if not (
        FOV_RANGE_DEG[0] <= pose.fov <= FOV_RANGE_DEG[1]
        and PITCH_RANGE_DEG[0] <= pose.pitch <= PITCH_RANGE_DEG[1]
        and ROLL_RANGE_DEG[0] <= pose.roll <= ROLL_RANGE_DEG[1]
    ):
        return math.inf
    azimuth, elevation = pixel_rays(columns, rows, width, height, pose)
    rendered, _ = horizon.at(azimuth)
    return trimmed_cost(elevation - rendered) * focal_length(width, pose.fov) * math.pi / 180


def refine(
    horizon: Horizon, columns: np.ndarray, rows: np.ndarray, width: int, height: int, start: Pose
) -> tuple[Pose, float]:
    """Pattern search over bearing, fov, pitch and roll from a starting pose."""
    pose = start
    best = pose_cost(horizon, columns, rows, width, height, pose)
    steps = {"bearing": 0.5, "fov": 1.0, "pitch": 0.5, "roll": 1.0}
    while max(steps.values()) > 0.02:
        improved = False
        for name, step in steps.items():
            for sign in (1.0, -1.0):
                trial = Pose(**{**pose.__dict__, name: getattr(pose, name) + sign * step})
                trial.bearing %= 360.0
                cost = pose_cost(horizon, columns, rows, width, height, trial)
                if cost < best - 1e-9:
                    pose, best, improved = trial, cost, True
        if not improved:
            steps = {name: step / 2 for name, step in steps.items()}
    return pose, best


def angular_gap(a: np.ndarray | float, b: float) -> np.ndarray | float:
    return np.abs((np.asarray(a) - b + 180.0) % 360.0 - 180.0)


def fit_camera(
    dem: Dem,
    x: float,
    y: float,
    ground_z: float,
    columns: np.ndarray,
    rows: np.ndarray,
    width: int,
    height: int,
    heights: tuple[float, ...] = CAMERA_HEIGHTS_M,
) -> Fit:
    best: Fit | None = None
    for camera_height in heights:
        horizon = render_horizon(dem, x, y, ground_z + camera_height)
        costs = coarse_search(horizon, columns, rows, width, height)
        bearings = np.arange(0.0, 360.0, 0.5)
        fovs = np.arange(FOV_RANGE_DEG[0], FOV_RANGE_DEG[1] + 0.1, 2.0)
        per_bearing = costs.min(axis=1)
        order = np.argsort(per_bearing)
        # Refine the best few distinct bearings: the coarse grid ignores roll
        # and approximates pitch, so the ranking can change after refinement.
        seeds: list[int] = []
        for index in order:
            if all(angular_gap(bearings[index], bearings[s]) > UNIQUE_SEPARATION_DEG for s in seeds):
                seeds.append(int(index))
            if len(seeds) == 4:
                break
        refined: list[tuple[float, Pose]] = []
        for index in seeds:
            fov = float(fovs[int(np.argmin(costs[index]))])
            focal = (width / 2) / math.tan(math.radians(fov) / 2)
            u = columns - (width - 1) / 2
            v = rows - (height - 1) / 2
            photo = np.degrees(np.arctan2(-v, np.hypot(focal, u)))
            rendered, _ = horizon.at(bearings[index] + np.degrees(np.arctan2(u, focal)))
            pitch = float(np.median(rendered - photo))
            pose, cost = refine(horizon, columns, rows, width, height, Pose(float(bearings[index]), fov, pitch, 0.0))
            refined.append((cost, pose))
        refined.sort(key=lambda item: item[0])
        cost, pose = refined[0]
        far = per_bearing[angular_gap(bearings, pose.bearing) > UNIQUE_SEPARATION_DEG]
        alternatives = [c for c, p in refined[1:] if angular_gap(p.bearing, pose.bearing) > UNIQUE_SEPARATION_DEG]
        alternative = min([float(far.min()), *alternatives])
        if best is None or cost < best.cost_px:
            best = Fit(pose, camera_height, cost, alternative, horizon)
    assert best is not None
    return best


def position_spread(
    dem: Dem, x: float, y: float, fit: Fit, columns: np.ndarray, rows: np.ndarray, width: int, height: int
) -> tuple[float, int]:
    """Largest bearing change over the positions POSITION_TOLERANCE_M away (eight
    directions) from which the photo still fits, and how many such positions there are.

    A shifted position whose best fit costs more than CONSISTENT_RATIO times the
    fit at the provider position is one the photo rules out, so it does not
    widen the bearing range.
    """
    shifts = [0.0]
    consistent = 0
    for angle in range(0, 360, 45):
        dx = POSITION_TOLERANCE_M * math.sin(math.radians(angle))
        dy = POSITION_TOLERANCE_M * math.cos(math.radians(angle))
        ground = float(dem.sample(np.array([x + dx]), np.array([y + dy]))[0])
        horizon = render_horizon(dem, x + dx, y + dy, ground + fit.height_m)
        pose, cost = refine(horizon, columns, rows, width, height, fit.pose)
        if cost <= CONSISTENT_RATIO * fit.cost_px:
            consistent += 1
            shifts.append(float(angular_gap(pose.bearing, fit.pose.bearing)))
    return max(shifts), consistent


def fetch(url: str, timeout: float = 60.0) -> tuple[bytes, str | None]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("Last-Modified")


def load_peaks(bbox: tuple[float, float, float, float], cache_dir: Path) -> list[dict[str, Any]]:
    """Named peaks (OpenStreetMap natural=peak) inside a lon/lat bbox, cached."""
    west, south, east, north = bbox
    cached = cache_dir / f"osm_peaks_{west:.2f}_{south:.2f}_{east:.2f}_{north:.2f}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    query = f'[out:json][timeout:60];node["natural"="peak"]["name"]({south},{west},{north},{east});out;'
    url = OVERPASS_URL + "?data=" + urllib.parse.quote(query)
    for attempt in range(3):
        try:
            body, _ = fetch(url, timeout=90.0)
            break
        except urllib.error.HTTPError as error:
            # The public Overpass instance answers 429/502/504 under load; the query is read-only.
            if error.code not in (429, 502, 504) or attempt == 2:
                raise
            time.sleep(30 * (attempt + 1))
    peaks = [
        {
            "name": element["tags"]["name"],
            "lon": element["lon"],
            "lat": element["lat"],
            "ele": element["tags"].get("ele"),
            "osm_id": element["id"],
        }
        for element in json.loads(body)["elements"]
    ]
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(peaks, ensure_ascii=False, indent=1), encoding="utf-8")
    return peaks


def visible_peaks(
    dem: Dem, x: float, y: float, camera_z: float, horizon: Horizon, peaks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Peaks that lie on the rendered skyline (within a DEM cell of it)."""
    if not peaks:
        return []
    from rasterio.warp import transform

    px, py = transform("EPSG:4326", UTM_CRS, [p["lon"] for p in peaks], [p["lat"] for p in peaks])
    px = np.asarray(px)
    py = np.asarray(py)
    distance = np.hypot(px - x, py - y)
    azimuth = np.degrees(np.arctan2(px - x, py - y)) % 360.0
    # Summit nodes are often a cell off the DEM top, so take the highest of
    # the surrounding cells.
    offsets = (-DEM_RESOLUTION_M, 0.0, DEM_RESOLUTION_M)
    z = np.max([dem.sample(px + dx, py + dy) for dx in offsets for dy in offsets], axis=0)
    drop = distance**2 * (1.0 - REFRACTION_K) / (2.0 * EARTH_RADIUS_M)
    elevation = np.degrees(np.arctan2(z - drop - camera_z, distance))
    sky_elevation, sky_distance = horizon.at(azimuth)
    tolerance = np.degrees(np.arctan2(DEM_RESOLUTION_M, np.maximum(distance, 1.0)))
    found = []
    for i, peak in enumerate(peaks):
        if 100.0 < distance[i] <= MAX_RANGE_M and elevation[i] >= sky_elevation[i] - tolerance[i]:
            found.append(
                {
                    **peak,
                    "azimuth": float(azimuth[i]),
                    "elevation_deg": float(elevation[i]),
                    "distance_m": float(distance[i]),
                }
            )
    return found


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def comparison_image(
    photo: Image.Image,
    skyline: tuple[np.ndarray, np.ndarray],
    fit: Fit,
    peaks: list[dict[str, Any]],
    title: list[str],
    path: Path,
) -> None:
    """Photo with its extracted skyline (cyan), the rendered DEM skyline (magenta) and named peaks."""
    width, height = photo.size
    scale = 1600 / width
    canvas_photo = photo.convert("RGB").resize((1600, round(height * scale)), Image.Resampling.BILINEAR)
    header = 30 * len(title) + 16
    canvas = Image.new("RGB", (1600, canvas_photo.height + header), (20, 20, 20))
    canvas.paste(canvas_photo, (0, header))
    draw = ImageDraw.Draw(canvas)
    for i, line in enumerate(title):
        draw.text((12, 8 + 30 * i), line, fill=(240, 240, 240), font=font(22))

    columns, rows = skyline
    finite = np.isfinite(rows)
    points = [(c * scale, header + r * scale) for c, r in zip(columns[finite], rows[finite])]
    for px, py in points:
        draw.ellipse((px - 1.5, py - 1.5, px + 1.5, py + 1.5), fill=(0, 230, 255))

    margin = fit.pose.fov
    azimuth = (fit.pose.bearing + np.arange(-margin, margin, AZIMUTH_STEP_DEG)) % 360.0
    rendered, _ = fit.horizon.at(azimuth)
    u, v = project(azimuth, rendered, width, height, fit.pose)
    inside = np.isfinite(u) & (u >= 0) & (u < width) & (v > -height) & (v < 2 * height)
    rendered_line = [(float(a) * scale, header + float(b) * scale) for a, b in zip(u[inside], v[inside])]
    if len(rendered_line) > 1:
        draw.line(rendered_line, fill=(255, 0, 200), width=3)

    for peak in peaks:
        pu, pv = project(np.array([peak["azimuth"]]), np.array([peak["elevation_deg"]]), width, height, fit.pose)
        if not np.isfinite(pu[0]) or not (0 <= pu[0] < width) or not (-0.1 * height < pv[0] < height):
            continue
        cx, cy = float(pu[0]) * scale, header + float(pv[0]) * scale
        draw.line([(cx, cy), (cx, cy - 40)], fill=(255, 230, 0), width=2)
        label = f"{peak['name']} ({peak['distance_m'] / 1000:.1f} km)"
        draw.text((cx + 4, cy - 62), label, fill=(255, 230, 0), font=font(20), stroke_width=2, stroke_fill=(0, 0, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, quality=88)


def judge(fit: Fit, skyline_fraction: float, tolerance_px: float, spread_deg: float | None) -> tuple[str, str | None]:
    """Confidence label and, when unsettled, the reason."""
    if skyline_fraction < MIN_SKYLINE_FRACTION:
        return (
            "unsettled",
            f"photo skyline found in only {skyline_fraction:.0%} of the columns"
            " (sky hidden by cloud, fog or foreground)",
        )
    if fit.cost_px > tolerance_px:
        return (
            "unsettled",
            f"skyline residual {fit.cost_px:.1f} px exceeds the {tolerance_px:.1f} px"
            " a DEM cell plus the skyline extraction step subtend",
        )
    ratio = fit.alternative_cost_px / max(fit.cost_px, 1e-6)
    if ratio < UNIQUE_RATIO:
        return (
            "unsettled",
            f"not unique: a bearing more than {UNIQUE_SEPARATION_DEG:.0f} deg away"
            f" fits {ratio:.1f}x as well (needs {UNIQUE_RATIO:.0f}x)",
        )
    if not (FOV_RANGE_DEG[0] + 1.0 < fit.pose.fov < FOV_RANGE_DEG[1] - 1.0):
        return "unsettled", f"field of view {fit.pose.fov:.1f} deg at the edge of the searched range"
    if spread_deg is None:
        return "unsettled", "position test not run"
    if spread_deg > SPREAD_MEDIUM_DEG:
        return "unsettled", f"bearing moves {spread_deg:.1f} deg when the camera moves {POSITION_TOLERANCE_M:.0f} m"
    return ("high" if spread_deg <= SPREAD_HIGH_DEG else "medium"), None


def list_cameras(sources: dict[str, Any]) -> list[dict[str, Any]]:
    """Every camera the ingest lists, read fresh from the providers (positions and image URLs)."""
    bbox = tuple(float(value) for value in sources["region"]["bbox"])
    cameras: list[dict[str, Any]] = []
    for source in sources["sources"]:
        if not source.get("enabled", True):
            continue
        if source["type"] == "datex2":
            xml = fetch_bytes(source["url"])
            cameras += parse_datex_cameras(
                xml, bbox, source["url"], source["attribution"], source.get("provider", source["id"])  # type: ignore[arg-type]
            )
        elif source["type"] == "static":
            cameras += static_cameras(source, bbox)  # type: ignore[arg-type]
    return cameras


def load_frame(url: str, saved: Path) -> tuple[bytes, str | None, str | None]:
    """Frame bytes, Last-Modified and why it is unusable (None if usable).

    The frame is saved next to its response metadata so a rerun scores the same
    frame; delete the folder to score the current one.
    """
    meta_path = saved.with_suffix(".json")
    if saved.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return saved.read_bytes(), meta["last_modified"], meta["problem"]
    try:
        response = fetch_image(url)
    except (urllib.error.URLError, TimeoutError) as error:
        return b"", None, f"fetch failed: {error}"
    problem = image_problem(response)
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_bytes(response.body)
    meta = {"url": url, "last_modified": response.last_modified, "problem": problem}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return response.body, response.last_modified, problem


def run(args: argparse.Namespace) -> int:
    sources = json.loads(args.sources.read_text(encoding="utf-8"))
    static_ids = {camera["id"] for source in sources["sources"] for camera in source.get("cameras", [])}
    cameras = [c for c in list_cameras(sources) if not args.only or c["id"] in args.only]
    results: dict[str, Any] = {}
    usable: list[tuple[dict[str, Any], dict[str, Any], Image.Image, str | None]] = []
    for camera in cameras:
        camera_id = camera["id"]
        entry: dict[str, Any] = {
            "bearing_deg": None,
            "fov_deg": None,
            "range_km": None,
            "elevation_m": None,
            "confidence": "unsettled",
        }
        results[camera_id] = entry
        if camera.get("latitude") is None or camera.get("longitude") is None:
            entry["reason"] = "no sourced camera position"
            print(f"{camera_id}: unsettled, no position", file=sys.stderr)
            continue
        url = camera.get("large_url") or camera.get("thumbnail_url")
        if not url:
            entry["reason"] = "the provider lists no image URL"
            print(f"{camera_id}: unsettled, no image URL", file=sys.stderr)
            continue
        body, last_modified, problem = load_frame(url, args.frames_dir / f"{camera_id}.jpg")
        captured = (
            email.utils.parsedate_to_datetime(last_modified).astimezone(timezone.utc).isoformat()
            if last_modified
            else None
        )
        entry["frame"] = {"url": url, "captured_at": captured, "md5": hashlib.md5(body).hexdigest()}
        if problem:
            entry["reason"] = f"no usable frame ({problem})"
            print(f"{camera_id}: unsettled, {problem}", file=sys.stderr)
            continue
        usable.append((camera, entry, Image.open(io.BytesIO(body)), captured))

    positioned = [(c["longitude"], c["latitude"]) for c in cameras if c.get("latitude") is not None]
    centres = [(c["longitude"], c["latitude"]) for c, _, _, _ in usable] or positioned
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"Loading DEM around {len(centres)} cameras", file=sys.stderr)
    dem = load_dem(centres, args.cache_dir)
    for camera in cameras:
        if camera.get("latitude") is None:
            continue
        x, y = to_utm(camera["longitude"], camera["latitude"])
        ground = float(dem.sample(np.array([x]), np.array([y]))[0])
        results[camera["id"]]["elevation_m"] = None if math.isnan(ground) else round(ground)
        results[camera["id"]]["elevation_source"] = "Copernicus GLO-30 at the provider position"
    lons = [p[0] for p in centres]
    lats = [p[1] for p in centres]
    pad = 0.9
    peaks = load_peaks((min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad), args.cache_dir)

    for camera, entry, photo, captured in usable:
        camera_id = camera["id"]
        x, y = to_utm(camera["longitude"], camera["latitude"])
        ground = float(dem.sample(np.array([x]), np.array([y]))[0])
        masks = (
            FERATEL_MASKS
            if camera.get("provider") == "feratel"
            else PRADOLLANO_MASKS
            if camera_id in static_ids
            else ()
        )
        skyline = extract_skyline(photo, masks)
        width, height = photo.size
        valid = np.isfinite(skyline[1])
        fraction = float(valid.mean())
        columns = skyline[0][valid]
        rows = skyline[1][valid]
        if fraction < MIN_SKYLINE_FRACTION:
            entry["reason"] = f"photo skyline found in only {fraction:.0%} of the columns"
            print(f"{camera_id}: unsettled, {entry['reason']}", file=sys.stderr)
            continue
        fit = fit_camera(dem, x, y, ground, columns, rows, width, height)
        azimuth, _ = pixel_rays(columns, rows, width, height, fit.pose)
        _, distances = fit.horizon.at(azimuth)
        median_distance = float(np.median(distances))
        cell_deg = float(np.degrees(np.arctan2(DEM_RESOLUTION_M, median_distance)))
        tolerance = cell_deg * focal_length(width, fit.pose.fov) * math.pi / 180 + 2 * width / WORK_WIDTH
        # The position test is slow; it only matters for a fit that passes the other checks.
        passes = judge(fit, fraction, tolerance, 0.0)[0] != "unsettled"
        spread, consistent_positions = (
            position_spread(dem, x, y, fit, columns, rows, width, height) if passes else (None, None)
        )
        confidence, reason = judge(fit, fraction, tolerance, spread)
        camera_z = ground + fit.height_m
        on_skyline = visible_peaks(dem, x, y, camera_z, fit.horizon, peaks)
        in_view = [p for p in on_skyline if angular_gap(p["azimuth"], fit.pose.bearing) <= fit.pose.fov / 2]
        fit_record = {
            "bearing_deg": round(fit.pose.bearing, 1),
            "fov_deg": round(fit.pose.fov, 1),
            "pitch_deg": round(fit.pose.pitch, 2),
            "roll_deg": round(fit.pose.roll, 2),
            "camera_height_m": fit.height_m,
            "residual_px": round(fit.cost_px, 1),
            "tolerance_px": round(tolerance, 1),
            "uniqueness_ratio": round(fit.alternative_cost_px / max(fit.cost_px, 1e-6), 2),
            "position_spread_deg": None if spread is None else round(spread, 2),
            "consistent_shifted_positions": consistent_positions,
            "skyline_columns": round(fraction, 3),
            "median_skyline_distance_km": round(median_distance / 1000, 2),
            "peaks_in_view": [
                f"{p['name']} ({p['distance_m'] / 1000:.1f} km, OSM node {p['osm_id']})" for p in in_view
            ],
        }
        entry["fit"] = fit_record
        entry["confidence"] = confidence
        if reason:
            entry["reason"] = reason
        else:
            entry["bearing_deg"] = fit_record["bearing_deg"]
            entry["fov_deg"] = fit_record["fov_deg"]
            entry["range_km"] = fit_record["median_skyline_distance_km"]
        image_name = f"{camera_id}.jpg"
        entry["comparison_image"] = image_name
        verdict = f"{confidence}" + (f": {reason}" if reason else "")
        comparison_image(
            photo,
            skyline,
            fit,
            in_view,
            [
                f"{camera_id}  {camera.get('name', '')}  frame {captured}",
                f"bearing {fit.pose.bearing:.1f}  fov {fit.pose.fov:.1f}  pitch {fit.pose.pitch:.1f}"
                f"  roll {fit.pose.roll:.1f}  height {fit.height_m:.0f} m"
                f"  residual {fit.cost_px:.1f}/{tolerance:.1f} px  unique x{fit_record['uniqueness_ratio']}"
                f"  spread {fit_record['position_spread_deg']} deg",
                f"cyan: photo skyline   magenta: DEM skyline (GLO-30)   yellow: OSM peaks   -> {verdict}"[:150],
            ],
            args.evidence_dir / image_name,
        )
        print(
            f"{camera_id}: {verdict} bearing {fit.pose.bearing:.1f} fov {fit.pose.fov:.1f}"
            f" residual {fit.cost_px:.1f}/{tolerance:.1f} px",
            file=sys.stderr,
        )

    output = {
        "generated_by": "scripts/webcam_bearing.py",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "method": (
            "Bearing, field of view and range from matching the photo skyline to the skyline rendered from the "
            "Copernicus GLO-30 DEM at the provider position (pinhole camera, curvature and refraction k=0.13). "
            "range_km is the median distance to the rendered skyline inside the field of view. Unsettled cameras "
            "have no bearing and wait for a person to confirm one; their fit block is the best candidate, "
            "not a bearing."
        ),
        "dem": "Copernicus DEM GLO-30 (copernicus-dem-30m on AWS Open Data), resampled to 30 m EPSG:32630",
        "peaks": "OpenStreetMap natural=peak via the Overpass API, labels only",
        "cameras": results,
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sources", type=Path, default=REPO / "backend" / "webcam_sources.json")
    parser.add_argument("--output", type=Path, default=REPO / "backend" / "webcam_overrides.json")
    parser.add_argument("--evidence-dir", type=Path, required=True, help="where the comparison images go")
    parser.add_argument("--cache-dir", type=Path, required=True, help="DEM and peak cache")
    parser.add_argument("--frames-dir", type=Path, required=True, help="frames are saved here and reused on reruns")
    parser.add_argument("--only", nargs="*", help="camera ids to process")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
