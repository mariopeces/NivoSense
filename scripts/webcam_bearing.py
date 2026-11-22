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
# Feratel stations also publish a stitched panorama about every 20 minutes;
# the player page gives its horizontal span ("degrees") and the day's archive.
FERATEL_PLAYER_URL = "https://webtvfc.feratel.com/webtv/?cam={station}&t=9&lg=en"
FERATEL_TZ = "Europe/Madrid"
# Daylight panoramas (local hours, one per hour) are fitted one by one; the sun
# and clouds move between them, so a false fit in one frame is not repeated.
PANORAMA_HOURS = range(9, 17)
PANORAMA_MIN_FRAMES = 4
PANORAMA_AGREEMENT_DEG = 1.0
PANORAMA_MIN_AGREEING = 3
# The published span is rounded and the stitch is not exactly cylindrical, so
# the fit may stretch it by this fraction and scale it vertically within this range.
PANORAMA_SPAN_TOLERANCE = 0.02
PANORAMA_VSCALE_RANGE = (0.9, 1.1)
PANORAMA_TILT_MAX_DEG = 10.0
# A view is located in the panorama taken in the same capture cycle.
SAME_CYCLE_MINUTES = 30
MATCH_PX_PER_DEG = 3.0
MATCH_FINE_PX_PER_DEG = 8.0
# Normalised cross-correlation of edge maps: the best position more than
# UNIQUE_SEPARATION_DEG away must score at least this much lower.
MATCH_MARGIN = 0.1
# The view's own skyline fit, started from the panorama bearing, may move it this far.
VIEW_AGREEMENT_DEG = 2.0
# The two estimates of the field of view (panorama match, skyline refit) may differ by this fraction.
VIEW_FOV_AGREEMENT = 0.15
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


@dataclass
class PanoPose:
    """Cylindrical panorama: columns are linear in azimuth, rows in tan(elevation).

    ``tilt`` is a small tilt of the stitch axis, highest at azimuth ``tilt_phase``.
    """

    centre_az: float
    span: float
    y0: float
    vscale: float
    tilt: float
    tilt_phase: float

    def azimuth(self, column: np.ndarray, width: int) -> np.ndarray:
        return np.asarray((self.centre_az + (np.asarray(column) - (width - 1) / 2) * self.span / width) % 360.0)

    def column(self, azimuth: np.ndarray, width: int) -> np.ndarray:
        offset = (np.asarray(azimuth) - self.centre_az + 180.0) % 360.0 - 180.0
        return np.asarray(offset * width / self.span + (width - 1) / 2)

    def row(self, azimuth: np.ndarray, elevation: np.ndarray, width: int) -> np.ndarray:
        focal = width / math.radians(self.span)
        tilt = math.tan(math.radians(self.tilt)) * np.sin(np.radians(np.asarray(azimuth) - self.tilt_phase))
        return np.asarray(self.y0 - self.vscale * focal * (np.tan(np.radians(elevation)) + tilt))


@dataclass
class PanoFit:
    pose: PanoPose
    height_m: float
    cost_px: float
    alternative_cost_px: float
    horizon: Horizon


def panorama_cost(
    horizon: Horizon, columns: np.ndarray, rows: np.ndarray, width: int, pose: PanoPose, nominal_span: float
) -> float:
    if not (
        abs(pose.span / nominal_span - 1) <= PANORAMA_SPAN_TOLERANCE + 1e-9
        and PANORAMA_VSCALE_RANGE[0] <= pose.vscale <= PANORAMA_VSCALE_RANGE[1]
        and abs(pose.tilt) <= PANORAMA_TILT_MAX_DEG
    ):
        return math.inf
    azimuth = pose.azimuth(columns, width)
    elevation, _ = horizon.at(azimuth)
    return trimmed_cost(rows - pose.row(azimuth, elevation, width))


def refine_panorama(
    horizon: Horizon, columns: np.ndarray, rows: np.ndarray, width: int, start: PanoPose, nominal_span: float
) -> tuple[PanoPose, float]:
    pose = start
    best = panorama_cost(horizon, columns, rows, width, pose, nominal_span)
    steps = {"centre_az": 0.2, "y0": 4.0, "vscale": 0.02, "tilt": 0.5, "tilt_phase": 20.0, "span": 1.0}
    while max(step for name, step in steps.items() if name != "y0") > 0.005:
        improved = False
        for name, step in steps.items():
            for sign in (1.0, -1.0):
                trial = PanoPose(**{**pose.__dict__, name: getattr(pose, name) + sign * step})
                cost = panorama_cost(horizon, columns, rows, width, trial, nominal_span)
                if cost < best - 1e-9:
                    pose, best, improved = trial, cost, True
        if not improved:
            steps = {name: step / 2 for name, step in steps.items()}
    return pose, best


def fit_panorama_at(
    horizon: Horizon, columns: np.ndarray, rows: np.ndarray, width: int, span: float
) -> tuple[PanoPose, float, float]:
    """Best panorama pose for one horizon, its cost and the best cost more than
    UNIQUE_SEPARATION_DEG away. Exhaustive over the centre azimuth (0.1 degree)
    with the nominal span, then a pattern search from the 3 best distinct centres."""
    focal = width / math.radians(span)
    centres = np.arange(0.0, 360.0, 0.1)
    offsets = (columns - (width - 1) / 2) * span / width
    costs = np.empty(centres.size)
    for start in range(0, centres.size, 400):
        block = centres[start : start + 400]
        elevation, _ = horizon.at(block[:, None] + offsets[None, :])
        residual = rows[None, :] + focal * np.tan(np.radians(elevation))
        residual -= np.median(residual, axis=1)[:, None]
        magnitude = np.sort(np.abs(residual), axis=1)
        keep = max(1, int(magnitude.shape[1] * TRIM_KEEP))
        costs[start : start + 400] = magnitude[:, :keep].mean(axis=1)
    seeds: list[int] = []
    for candidate in np.argsort(costs):
        if all(angular_gap(centres[candidate], centres[s]) > UNIQUE_SEPARATION_DEG for s in seeds):
            seeds.append(int(candidate))
        if len(seeds) == 3:
            break
    refined: list[tuple[PanoPose, float]] = []
    for index in seeds:
        elevation, _ = horizon.at(centres[index] + offsets)
        y0 = float(np.median(rows + focal * np.tan(np.radians(elevation))))
        refined.append(
            refine_panorama(
                horizon, columns, rows, width, PanoPose(float(centres[index]), span, y0, 1.0, 0.0, 0.0), span
            )
        )
    refined.sort(key=lambda item: item[1])
    pose, cost = refined[0]
    far = costs[angular_gap(centres, pose.centre_az) > UNIQUE_SEPARATION_DEG]
    alternatives = [c for p, c in refined[1:] if angular_gap(p.centre_az, pose.centre_az) > UNIQUE_SEPARATION_DEG]
    return pose, cost, min([float(np.min(far)), *alternatives])


def fit_panorama(
    dem: Dem, x: float, y: float, ground_z: float, columns: np.ndarray, rows: np.ndarray, width: int, span: float
) -> PanoFit:
    best: PanoFit | None = None
    for camera_height in CAMERA_HEIGHTS_M:
        horizon = render_horizon(dem, x, y, ground_z + camera_height)
        pose, cost, alternative = fit_panorama_at(horizon, columns, rows, width, span)
        if best is None or cost < best.cost_px:
            best = PanoFit(pose, camera_height, cost, alternative, horizon)
    assert best is not None
    return best


def panorama_position_spread(
    dem: Dem, x: float, y: float, fit: PanoFit, columns: np.ndarray, rows: np.ndarray, width: int, span: float
) -> tuple[float, int]:
    """As position_spread, for the panorama centre azimuth."""
    shifts = [0.0]
    consistent = 0
    for angle in range(0, 360, 45):
        dx = POSITION_TOLERANCE_M * math.sin(math.radians(angle))
        dy = POSITION_TOLERANCE_M * math.cos(math.radians(angle))
        ground = float(dem.sample(np.array([x + dx]), np.array([y + dy]))[0])
        horizon = render_horizon(dem, x + dx, y + dy, ground + fit.height_m)
        pose, cost = refine_panorama(horizon, columns, rows, width, fit.pose, span)
        if cost <= CONSISTENT_RATIO * fit.cost_px:
            consistent += 1
            shifts.append(float(angular_gap(pose.centre_az, fit.pose.centre_az)))
    return max(shifts), consistent


def edge_map(luminance: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(luminance)
    return np.asarray(np.hypot(gx, gy))


def masked_ncc(image: np.ndarray, template: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Normalised cross-correlation with a masked template at every position where
    it fits inside the image (Padfield 2012, "Masked object registration in the
    Fourier domain")."""
    image_h, image_w = image.shape
    tpl_h, tpl_w = template.shape
    shape = (image_h + tpl_h, image_w + tpl_w)
    weight = mask.astype(float)
    tpl = template * weight
    f_image = np.fft.rfft2(image, shape)
    f_image2 = np.fft.rfft2(image**2, shape)
    f_mask = np.fft.rfft2(weight[::-1, ::-1], shape)
    f_tpl = np.fft.rfft2(tpl[::-1, ::-1], shape)
    count = weight.sum()
    sum_t = tpl.sum()
    sum_t2 = (tpl**2).sum()
    corr_it = np.fft.irfft2(f_image * f_tpl, shape)
    corr_im = np.fft.irfft2(f_image * f_mask, shape)
    corr_i2m = np.fft.irfft2(f_image2 * f_mask, shape)
    numerator = corr_it - corr_im * sum_t / count
    denominator = (corr_i2m - corr_im**2 / count) * (sum_t2 - sum_t**2 / count)
    ncc = numerator / np.sqrt(np.maximum(denominator, 1e-9))
    return np.asarray(ncc[tpl_h - 1 : image_h, tpl_w - 1 : image_w])


def view_template(
    edges: np.ndarray, mask: np.ndarray, fov: float, pitch: float, px_per_deg: float
) -> tuple[np.ndarray, np.ndarray, float]:
    """A view's edge map resampled onto a cylindrical grid (columns: azimuth from
    the optical axis, rows: -tan(elevation)), and the grid row of elevation 0."""
    height, width = edges.shape
    pose = Pose(0.0, fov, pitch, 0.0)
    corner_u = np.array([0, width - 1, 0, width - 1, (width - 1) / 2, (width - 1) / 2], dtype=float)
    corner_v = np.array([0, 0, height - 1, height - 1, 0, height - 1], dtype=float)
    _, elevation = pixel_rays(corner_u, corner_v, width, height, pose)
    focal = px_per_deg * 180 / math.pi
    top = math.tan(math.radians(float(elevation.max())))
    bottom = math.tan(math.radians(float(elevation.min())))
    half = fov / 2 + 1.0
    n_cols = int(2 * half * px_per_deg)
    n_rows = int((top - bottom) * focal)
    az = (np.arange(n_cols) - (n_cols - 1) / 2) / px_per_deg
    tangent = top - np.arange(n_rows) / focal
    grid_az, grid_t = np.meshgrid(az, tangent)
    u, v = project(grid_az.ravel(), np.degrees(np.arctan(grid_t.ravel())), width, height, pose)
    u = u.reshape(grid_az.shape)
    v = v.reshape(grid_az.shape)
    inside = np.isfinite(u) & (u >= 0) & (u <= width - 1) & (v >= 0) & (v <= height - 1)
    ui = np.clip(np.round(np.nan_to_num(u)).astype(int), 0, width - 1)
    vi = np.clip(np.round(np.nan_to_num(v)).astype(int), 0, height - 1)
    return edges[vi, ui], inside & mask[vi, ui], top * focal


@dataclass
class ViewMatch:
    bearing: float
    fov: float
    pitch: float
    score: float
    alternative_score: float
    pano_column: float


def locate_view(
    view: Image.Image,
    masks: tuple[tuple[float, float, float, float], ...],
    panorama: Image.Image,
    pano_pose: PanoPose,
    fov_range: tuple[float, float] = FOV_RANGE_DEG,
) -> ViewMatch:
    """Bearing, fov and pitch of a view from where its edge map best correlates
    with the station panorama of the same capture cycle (coarse grid over fov
    and pitch, then a finer grid around the best)."""
    pano_px_per_deg = panorama.width / pano_pose.span
    pano_lum = np.asarray(panorama.convert("L"), dtype=float)

    def pano_edges(px_per_deg: float) -> np.ndarray:
        scale = px_per_deg / pano_px_per_deg
        size = (round(panorama.width * scale), round(panorama.height * scale / pano_pose.vscale))
        small = Image.fromarray(pano_lum.astype(np.uint8)).resize(size, Image.Resampling.BILINEAR)
        return edge_map(np.asarray(small, dtype=float))

    def view_edges(px_per_deg: float, fov: float) -> tuple[np.ndarray, np.ndarray]:
        view_px_per_deg = focal_length(view.width, fov) * math.pi / 180
        scale = min(1.0, px_per_deg / view_px_per_deg)
        size = (round(view.width * scale), round(view.height * scale))
        lum = np.asarray(view.convert("L").resize(size, Image.Resampling.BILINEAR), dtype=float)
        mask = np.ones(lum.shape, dtype=bool)
        for x0, y0, x1, y1 in masks:
            mask[round(y0 * size[1]) : round(y1 * size[1]), round(x0 * size[0]) : round(x1 * size[0])] = False
        return edge_map(lum), mask

    def scan(
        px_per_deg: float, fovs: np.ndarray, pitches: np.ndarray, column_window: tuple[float, float] | None
    ) -> list[tuple[float, float, float, float, np.ndarray]]:
        image = pano_edges(px_per_deg)
        offset = 0
        if column_window is not None:
            lo = max(0, int(column_window[0] * px_per_deg / pano_px_per_deg))
            hi = min(image.shape[1], int(column_window[1] * px_per_deg / pano_px_per_deg))
            image, offset = image[:, lo:hi], lo
        found = []
        for fov in fovs:
            edges, mask = view_edges(px_per_deg, float(fov))
            for pitch in pitches:
                tpl, tpl_mask, _ = view_template(edges, mask, float(fov), float(pitch), px_per_deg)
                if tpl.shape[0] >= image.shape[0] or tpl.shape[1] >= image.shape[1] or tpl_mask.sum() < 100:
                    continue
                ncc = masked_ncc(image, tpl, tpl_mask)
                peak = int(np.argmax(ncc))
                row, col = divmod(peak, ncc.shape[1])
                centre = (offset + col + (tpl.shape[1] - 1) / 2) * pano_px_per_deg / px_per_deg
                # Best score per panorama column, for the uniqueness check.
                profile = np.full(image.shape[1] + offset, -1.0)
                cols = offset + np.arange(ncc.shape[1]) + (tpl.shape[1] - 1) // 2
                profile[cols] = ncc.max(axis=0)
                found.append((float(ncc[row, col]), float(fov), float(pitch), centre, profile))
        found.sort(key=lambda item: -item[0])
        return found

    coarse = scan(MATCH_PX_PER_DEG, np.arange(fov_range[0], fov_range[1] + 0.1, 4.0), np.arange(-16, 17, 4), None)
    score, fov, pitch, centre, _ = coarse[0]
    profiles = np.max([item[4] for item in coarse], axis=0)
    columns_deg = np.arange(profiles.size) / MATCH_PX_PER_DEG
    far = profiles[np.abs(columns_deg - centre / pano_px_per_deg) > UNIQUE_SEPARATION_DEG]
    alternative = float(far.max()) if far.size else -1.0
    window = (centre - (fov / 2 + 8) * pano_px_per_deg, centre + (fov / 2 + 8) * pano_px_per_deg)
    fine = scan(
        MATCH_FINE_PX_PER_DEG, np.arange(fov - 4, fov + 4.1, 1.0), np.arange(pitch - 4, pitch + 4.1, 1.0), window
    )
    if fine and fine[0][0] >= score - 0.05:
        _, fov, pitch, centre, _ = fine[0]
    return ViewMatch(
        float(pano_pose.azimuth(np.array([centre]), panorama.width)[0]), fov, pitch, score, alternative, centre
    )


def feratel_station(camera: dict[str, Any]) -> str | None:
    query = urllib.parse.urlparse(camera.get("position_source") or "").query
    values = urllib.parse.parse_qs(query).get("cam")
    return values[0] if values else None


def station_panoramas(station: str, saved_dir: Path) -> tuple[float, list[tuple[datetime, str]]]:
    """Panorama span in degrees and the archived panoramas (UTC capture time, URL)
    listed on the station's player page; the page is saved so a rerun sees the same list."""
    import re
    from zoneinfo import ZoneInfo

    page_path = saved_dir / f"player_{station}.html"
    if page_path.exists():
        page = page_path.read_text(encoding="utf-8")
    else:
        page = fetch(FERATEL_PLAYER_URL.format(station=station))[0].decode("utf-8", "replace")
        saved_dir.mkdir(parents=True, exist_ok=True)
        page_path.write_text(page, encoding="utf-8")
    span = re.search(r"let degrees = (\d+(?:\.\d+)?);", page)
    if not span:
        raise ValueError(f"no panorama span on the player page of station {station}")
    local = ZoneInfo(FERATEL_TZ)
    panoramas = []
    for url in re.findall(r'url: "(https://arch\.feratel\.com/[^"]+/pano/PA-[^"]+)"', page):
        stamp = re.search(r"PA-(\d{4})-(\d\d)-(\d\d)-(\d\d)-(\d\d)-(\d\d)\.jpeg", url)
        if stamp:
            year, month, day, hour, minute, second = (int(g) for g in stamp.groups())
            when = datetime(year, month, day, hour, minute, second, tzinfo=local).astimezone(timezone.utc)
            panoramas.append((when, url))
    return float(span.group(1)), sorted(set(panoramas))


def load_panorama(url: str, saved: Path) -> Image.Image | None:
    if not saved.exists():
        try:
            body, _ = fetch(url)
        except (urllib.error.URLError, TimeoutError) as error:
            print(f"  panorama fetch failed: {url}: {error}", file=sys.stderr)
            return None
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(body)
    try:
        return Image.open(saved).convert("RGB")
    except OSError:
        return None


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


def judge_view(
    skyline_fraction: float, match: ViewMatch, cost_px: float, tolerance_px: float, pose: Pose
) -> str | None:
    """Why a view located in its station panorama is not settled, or None if it is.

    ``pose`` is the view's own skyline refit started from the match.
    """
    agreement = float(angular_gap(pose.bearing, match.bearing))
    if skyline_fraction < MIN_SKYLINE_FRACTION:
        return f"view skyline found in only {skyline_fraction:.0%} of the columns, nothing to confirm the match"
    if match.score - match.alternative_score < MATCH_MARGIN:
        return (
            f"panorama match not unique: a position more than {UNIQUE_SEPARATION_DEG:.0f} deg away scores"
            f" {match.alternative_score:.2f} against {match.score:.2f} (needs {MATCH_MARGIN} lower)"
        )
    if cost_px > tolerance_px:
        return f"view skyline residual {cost_px:.1f} px exceeds {tolerance_px:.1f} px at the matched pose"
    if agreement > VIEW_AGREEMENT_DEG:
        return f"view skyline moves the matched bearing by {agreement:.1f} deg (allowed {VIEW_AGREEMENT_DEG})"
    if not (FOV_RANGE_DEG[0] + 1.0 < pose.fov < FOV_RANGE_DEG[1] - 1.0):
        return f"field of view {pose.fov:.1f} deg at the edge of the searched range"
    if abs(pose.fov / match.fov - 1) > VIEW_FOV_AGREEMENT:
        return (
            f"field of view disagrees: {match.fov:.1f} deg from the panorama match,"
            f" {pose.fov:.1f} deg from the view skyline (allowed {VIEW_FOV_AGREEMENT:.0%})"
        )
    return None


def list_cameras(sources: dict[str, Any]) -> list[dict[str, Any]]:
    """Every camera the ingest lists, read fresh from the providers (positions and image URLs)."""
    west, south, east, north = (float(value) for value in sources["region"]["bbox"])
    bbox = (west, south, east, north)
    cameras: list[dict[str, Any]] = []
    for source in sources["sources"]:
        if not source.get("enabled", True):
            continue
        if source["type"] == "datex2":
            xml = fetch_bytes(source["url"])
            cameras += parse_datex_cameras(
                xml,
                bbox,
                source["url"],
                source["attribution"],
                source.get("provider", source["id"]),
            )
        elif source["type"] == "static":
            cameras += static_cameras(source, bbox)
    return cameras


def load_frame(url: str, saved: Path, provider: str) -> tuple[bytes, str | None, str | None]:
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
    problem = image_problem(response, provider)
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_bytes(response.body)
    meta = {"url": url, "last_modified": response.last_modified, "problem": problem}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return response.body, response.last_modified, problem


def panorama_image(
    panorama: Image.Image,
    skyline: tuple[np.ndarray, np.ndarray],
    fit: PanoFit,
    peaks: list[dict[str, Any]],
    views: list[tuple[str, ViewMatch]],
    title: list[str],
    path: Path,
) -> None:
    """Panorama with the voted photo skyline (cyan), the rendered DEM skyline at the
    fitted pose (magenta), azimuth ticks, named peaks and where each view was found."""
    width, height = panorama.size
    scale = 2400 / width
    photo = panorama.convert("RGB").resize((2400, round(height * scale)), Image.Resampling.BILINEAR)
    header = 30 * len(title) + 16
    canvas = Image.new("RGB", (2400, photo.height + header), (20, 20, 20))
    canvas.paste(photo, (0, header))
    draw = ImageDraw.Draw(canvas)
    for i, line in enumerate(title):
        draw.text((12, 8 + 30 * i), line, fill=(240, 240, 240), font=font(22))
    columns, rows = skyline
    for c, r in zip(columns, rows):
        draw.ellipse(
            (c * scale - 1.5, header + r * scale - 1.5, c * scale + 1.5, header + r * scale + 1.5), fill=(0, 230, 255)
        )
    line_columns = np.arange(0.0, width, 2.0)
    azimuth = fit.pose.azimuth(line_columns, width)
    rendered, _ = fit.horizon.at(azimuth)
    line_rows = fit.pose.row(azimuth, rendered, width)
    draw.line([(c * scale, header + r * scale) for c, r in zip(line_columns, line_rows)], fill=(255, 0, 200), width=3)
    for tick in range(0, 360, 10):
        column = float(fit.pose.column(np.array([tick]), width)[0])
        if 0 <= column < width:
            draw.line([(column * scale, header), (column * scale, header + 18)], fill=(255, 255, 255), width=2)
            draw.text(
                (column * scale + 3, header + 18),
                f"{tick}",
                fill=(255, 255, 255),
                font=font(18),
                stroke_width=2,
                stroke_fill=(0, 0, 0),
            )
    for peak in peaks:
        column = float(fit.pose.column(np.array([peak["azimuth"]]), width)[0])
        if not 0 <= column < width:
            continue
        row = float(fit.pose.row(np.array([peak["azimuth"]]), np.array([peak["elevation_deg"]]), width)[0])
        cx, cy = column * scale, header + row * scale
        draw.line([(cx, cy), (cx, cy - 40)], fill=(255, 230, 0), width=2)
        draw.text(
            (cx + 4, cy - 62),
            f"{peak['name']} ({peak['distance_m'] / 1000:.1f} km)",
            fill=(255, 230, 0),
            font=font(18),
            stroke_width=2,
            stroke_fill=(0, 0, 0),
        )
    bottom = header + photo.height - 40
    for label, match in views:
        half = match.fov / 2 * width / fit.pose.span * scale
        cx = match.pano_column * scale
        draw.rectangle((cx - half, bottom - 60, cx + half, bottom), outline=(120, 255, 120), width=3)
        draw.text(
            (cx - half + 6, bottom - 56),
            label,
            fill=(120, 255, 120),
            font=font(20),
            stroke_width=2,
            stroke_fill=(0, 0, 0),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, quality=88)


def settle_station(
    dem: Dem,
    station: str,
    views: list[tuple[dict[str, Any], dict[str, Any], Image.Image, str | None]],
    masks_of: dict[str, tuple[tuple[float, float, float, float], ...]],
    peaks: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Bearings of a feratel station's views through its panorama.

    1. The day's daylight panoramas (one per hour) are each fitted to the DEM
       skyline with a cylindrical pose. They are pixel-aligned (the stitch does
       not move between captures), so one pose maps every panorama column to an
       azimuth. The most distinct fit is checked like a single view (residual,
       uniqueness, position test) with 200 degrees of skyline instead of 30, and
       at least PANORAMA_MIN_AGREEING other frames must land on the same centre.
    2. Each view is located in the panorama of its own capture cycle by masked
       cross-correlation of edge maps; the column gives the bearing.
    3. The view's own skyline, refined against the DEM from that pose, must stay
       within VIEW_AGREEMENT_DEG of it and inside the residual tolerance.
    """
    from zoneinfo import ZoneInfo

    record: dict[str, Any] = {"station": station}
    first = views[0][0]
    x, y = to_utm(first["longitude"], first["latitude"])
    ground = float(dem.sample(np.array([x]), np.array([y]))[0])

    def unsettle_all(reason: str) -> dict[str, Any]:
        record["reason"] = reason
        for _, entry, _, _ in views:
            entry["panorama"] = {"station": station, "reason": reason}
            entry["reason"] = f"station panorama: {reason}"
        print(f"station {station}: unsettled, {reason}", file=sys.stderr)
        return record

    saved_dir = args.frames_dir / "panoramas" / station
    try:
        span, listed = station_panoramas(station, saved_dir)
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        return unsettle_all(f"player page unavailable: {error}")
    local = ZoneInfo(FERATEL_TZ)
    hourly: dict[tuple[Any, int], tuple[datetime, str]] = {}
    for when, url in listed:
        stamp = when.astimezone(local)
        if stamp.hour in PANORAMA_HOURS:
            hourly.setdefault((stamp.date(), stamp.hour), (when, url))
    voters: list[tuple[datetime, Image.Image]] = []
    for when, url in hourly.values():
        image = load_panorama(url, saved_dir / url.split("?")[0].rsplit("/", 1)[-1])
        if image is not None:
            voters.append((when, image))
    if voters:
        sizes = [image.size for _, image in voters]
        common = max(set(sizes), key=sizes.count)
        voters = [(when, image) for when, image in voters if image.size == common]
    if len(voters) < PANORAMA_MIN_FRAMES:
        return unsettle_all(f"only {len(voters)} daylight panoramas archived (needs {PANORAMA_MIN_FRAMES})")
    width = voters[0][1].width
    fitted: list[tuple[datetime, Image.Image, np.ndarray, np.ndarray, PanoFit, float, float]] = []
    # Per-frame fits are slow (three camera heights), so they are kept next to
    # the saved panoramas and reused on a rerun of the same frames.
    fits_path = saved_dir / "fits.json"
    saved_fits: dict[str, Any] = json.loads(fits_path.read_text(encoding="utf-8")) if fits_path.exists() else {}
    for when, image in voters:
        frame_columns, frame_rows = extract_skyline(image, ())
        keep = np.isfinite(frame_rows)
        if keep.mean() < MIN_SKYLINE_FRACTION:
            continue
        key = f"{when.isoformat()} {x:.1f} {y:.1f}"
        if key in saved_fits:
            known = saved_fits[key]
            frame_fit = PanoFit(
                PanoPose(**known["pose"]),
                known["height_m"],
                known["cost_px"],
                known["alternative_cost_px"],
                render_horizon(dem, x, y, ground + known["height_m"]),
            )
        else:
            frame_fit = fit_panorama(dem, x, y, ground, frame_columns[keep], frame_rows[keep], width, span)
            saved_fits[key] = {
                "pose": frame_fit.pose.__dict__,
                "height_m": frame_fit.height_m,
                "cost_px": frame_fit.cost_px,
                "alternative_cost_px": frame_fit.alternative_cost_px,
            }
            fits_path.write_text(json.dumps(saved_fits, indent=1), encoding="utf-8")
        _, frame_distances = frame_fit.horizon.at(frame_fit.pose.azimuth(frame_columns[keep], width))
        frame_distance = float(np.median(frame_distances))
        frame_tolerance = (
            math.atan2(DEM_RESOLUTION_M, frame_distance) * width / math.radians(frame_fit.pose.span)
            + 2 * width / WORK_WIDTH
        )
        fitted.append((when, image, frame_columns[keep], frame_rows[keep], frame_fit, frame_tolerance, frame_distance))
        print(
            f"  panorama {when.isoformat()}: centre {frame_fit.pose.centre_az:.2f} residual {frame_fit.cost_px:.1f}"
            f"/{frame_tolerance:.1f} px unique x{frame_fit.alternative_cost_px / max(frame_fit.cost_px, 1e-6):.2f}",
            file=sys.stderr,
        )
    if not fitted:
        return unsettle_all("no daylight panorama shows enough skyline")

    def uniqueness(item: tuple[datetime, Image.Image, np.ndarray, np.ndarray, PanoFit, float, float]) -> float:
        return item[4].alternative_cost_px / max(item[4].cost_px, 1e-6)

    # The reference is the frame whose fit is most distinct; the other frames,
    # lit and clouded differently, must land on the same centre for it to count.
    within = [item for item in fitted if item[4].cost_px <= item[5]]
    reference = max(within or fitted, key=uniqueness)
    _, best_image, columns, rows, fit, tolerance, median_distance = reference
    agreeing = [
        item
        for item in fitted
        if item is not reference and angular_gap(item[4].pose.centre_az, fit.pose.centre_az) <= PANORAMA_AGREEMENT_DEG
    ]
    ratio = uniqueness(reference)
    spread: float | None = None
    consistent: int | None = None
    if fit.cost_px > tolerance:
        reason: str | None = f"skyline residual {fit.cost_px:.1f} px exceeds {tolerance:.1f} px"
    elif ratio < UNIQUE_RATIO:
        reason = (
            f"not unique: a centre azimuth more than {UNIQUE_SEPARATION_DEG:.0f} deg away fits {ratio:.1f}x as well"
            f" (needs {UNIQUE_RATIO:.0f}x)"
        )
    elif len(agreeing) < PANORAMA_MIN_AGREEING:
        reason = (
            f"only {len(agreeing)} other panoramas land within {PANORAMA_AGREEMENT_DEG} deg of the best one"
            f" (needs {PANORAMA_MIN_AGREEING})"
        )
    else:
        spread, consistent = panorama_position_spread(dem, x, y, fit, columns, rows, width, span)
        reason = (
            f"centre azimuth moves {spread:.1f} deg when the camera moves {POSITION_TOLERANCE_M:.0f} m"
            if spread > SPREAD_MEDIUM_DEG
            else None
        )
    station_confidence = "unsettled" if reason else ("high" if (spread or 0.0) <= SPREAD_HIGH_DEG else "medium")
    record.update(
        {
            "published_span_deg": span,
            "reference_panorama": reference[0].isoformat(),
            "panorama_centres_deg": {item[0].isoformat(): round(item[4].pose.centre_az, 2) for item in fitted},
            "agreeing_panoramas": len(agreeing),
            "centre_azimuth_deg": round(fit.pose.centre_az, 2),
            "span_deg": round(fit.pose.span, 2),
            "vertical_scale": round(fit.pose.vscale, 3),
            "tilt_deg": round(fit.pose.tilt, 2),
            "camera_height_m": fit.height_m,
            "residual_px": round(fit.cost_px, 1),
            "tolerance_px": round(tolerance, 1),
            "uniqueness_ratio": round(ratio, 2),
            "position_spread_deg": None if spread is None else round(spread, 2),
            "consistent_shifted_positions": consistent,
            "median_skyline_distance_km": round(median_distance / 1000, 2),
            "confidence": station_confidence,
        }
    )
    if reason:
        record["reason"] = reason
    print(
        f"station {station}: {station_confidence}{': ' + reason if reason else ''} centre {fit.pose.centre_az:.2f}"
        f" span {fit.pose.span:.2f} residual {fit.cost_px:.1f}/{tolerance:.1f} px unique x{ratio:.2f} spread {spread}",
        file=sys.stderr,
    )

    camera_z = ground + fit.height_m
    on_skyline = visible_peaks(dem, x, y, camera_z, fit.horizon, peaks)
    found: list[tuple[str, ViewMatch]] = []
    for camera, entry, photo, captured in views:
        camera_id = camera["id"]
        view_record: dict[str, Any] = {"station": station, "station_confidence": station_confidence}
        entry["panorama"] = view_record
        if reason:
            view_record["reason"] = reason
            entry["reason"] = f"station panorama: {reason}"
            continue
        captured_at = datetime.fromisoformat(captured) if captured else None
        cycle = (
            min(listed, key=lambda item: abs((item[0] - captured_at).total_seconds()))
            if captured_at and listed
            else None
        )
        if (
            cycle is None
            or captured_at is None
            or abs((cycle[0] - captured_at).total_seconds()) > SAME_CYCLE_MINUTES * 60
        ):
            view_record["reason"] = f"no panorama within {SAME_CYCLE_MINUTES} min of the frame"
            entry["reason"] = f"station panorama: {view_record['reason']}"
            continue
        same_cycle = load_panorama(cycle[1], saved_dir / cycle[1].split("?")[0].rsplit("/", 1)[-1])
        if same_cycle is None or same_cycle.width != width:
            view_record["reason"] = "the same-cycle panorama could not be read"
            entry["reason"] = f"station panorama: {view_record['reason']}"
            continue
        match = locate_view(photo, masks_of[camera_id], same_cycle, fit.pose)
        found.append((camera_id.split("-", 1)[1], match))
        skyline = extract_skyline(photo, masks_of[camera_id])
        valid = np.isfinite(skyline[1])
        fraction = float(valid.mean())
        view_w, view_h = photo.size
        start = Pose(
            match.bearing,
            float(np.clip(match.fov, *FOV_RANGE_DEG)),
            float(np.clip(match.pitch, *PITCH_RANGE_DEG)),
            0.0,
        )
        pose, cost = (
            refine(fit.horizon, skyline[0][valid], skyline[1][valid], view_w, view_h, start)
            if fraction >= MIN_SKYLINE_FRACTION
            else (start, math.inf)
        )
        view_az, _ = pixel_rays(skyline[0][valid], skyline[1][valid], view_w, view_h, pose)
        _, view_distances = fit.horizon.at(view_az) if view_az.size else (None, np.array([median_distance]))
        view_distance = float(np.median(view_distances))
        view_tolerance = (
            math.atan2(DEM_RESOLUTION_M, view_distance) * focal_length(view_w, pose.fov) + 2 * view_w / WORK_WIDTH
        )
        agreement = float(angular_gap(pose.bearing, match.bearing))
        view_reason = judge_view(fraction, match, cost, view_tolerance, pose)
        confidence = "unsettled" if view_reason else station_confidence
        in_view = [p for p in on_skyline if angular_gap(p["azimuth"], pose.bearing) <= pose.fov / 2]
        view_record.update(
            {
                "same_cycle_panorama": cycle[0].isoformat(),
                "matched_bearing_deg": round(match.bearing, 1),
                "matched_fov_deg": round(match.fov, 1),
                "match_score": round(match.score, 3),
                "match_alternative_score": round(match.alternative_score, 3),
                "bearing_deg": round(pose.bearing, 1),
                "fov_deg": round(pose.fov, 1),
                "pitch_deg": round(pose.pitch, 2),
                "roll_deg": round(pose.roll, 2),
                "view_residual_px": None if math.isinf(cost) else round(cost, 1),
                "view_tolerance_px": round(view_tolerance, 1),
                "skyline_agreement_deg": round(agreement, 2),
                "skyline_columns": round(fraction, 3),
                "median_skyline_distance_km": round(view_distance / 1000, 2),
                "peaks_in_view": [
                    f"{p['name']} ({p['distance_m'] / 1000:.1f} km, OSM node {p['osm_id']})" for p in in_view
                ],
            }
        )
        image_name = f"{camera_id}.jpg"
        entry.setdefault("comparison_images", []).append(image_name)
        if view_reason:
            view_record["reason"] = view_reason
            entry["reason"] = f"station panorama: {view_reason}"
        else:
            entry.pop("reason", None)
            entry["method"] = "station panorama"
            entry["confidence"] = confidence
            entry["bearing_deg"] = view_record["bearing_deg"]
            entry["fov_deg"] = view_record["fov_deg"]
            entry["range_km"] = view_record["median_skyline_distance_km"]
        verdict = confidence + (f": {view_reason}" if view_reason else "")
        comparison_image(
            photo,
            skyline,
            Fit(pose, fit.height_m, cost, math.inf, fit.horizon),
            in_view,
            [
                f"{camera_id}  {camera.get('name', '')}  frame {captured}",
                f"panorama {station}: matched bearing {match.bearing:.1f} fov {match.fov:.0f} (ncc {match.score:.2f},"
                f" next {match.alternative_score:.2f})  ->  skyline refit bearing {pose.bearing:.1f} fov {pose.fov:.1f}"
                f" residual {cost:.1f}/{view_tolerance:.1f} px",
                f"cyan: photo skyline   magenta: DEM skyline (GLO-30)   yellow: OSM peaks   -> {verdict}"[:150],
            ],
            args.evidence_dir / image_name,
        )
        print(
            f"{camera_id}: panorama {verdict} bearing {pose.bearing:.1f}"
            f" (matched {match.bearing:.1f}) fov {pose.fov:.1f}",
            file=sys.stderr,
        )

    record["image"] = f"station-{station}.jpg"
    panorama_image(
        best_image,
        (columns, rows),
        fit,
        on_skyline,
        found,
        [
            f"station {station}  {first.get('location', '')}  {len(fitted)} daylight panoramas fitted,"
            f" {len(agreeing)} agree with this one,"
            f" published span {span:.0f} deg",
            f"centre {fit.pose.centre_az:.2f}  span {fit.pose.span:.2f}  height {fit.height_m:.0f} m  residual"
            f" {fit.cost_px:.1f}/{tolerance:.1f} px  unique x{ratio:.2f}  spread {record['position_spread_deg']} deg"
            f"  -> {station_confidence}{': ' + reason if reason else ''}"[:160],
            "cyan: photo skyline (this frame)   magenta: DEM skyline (GLO-30)   white: azimuth   yellow: OSM peaks"
            "   green: views found",
        ],
        args.evidence_dir / record["image"],
    )
    return record


def single_view(
    dem: Dem,
    camera: dict[str, Any],
    entry: dict[str, Any],
    photo: Image.Image,
    captured: str | None,
    masks: tuple[tuple[float, float, float, float], ...],
    peaks: list[dict[str, Any]],
    evidence_dir: Path,
) -> None:
    """The view's own skyline against the DEM over all bearings (used when the station panorama does not settle it)."""
    camera_id = camera["id"]
    x, y = to_utm(camera["longitude"], camera["latitude"])
    ground = float(dem.sample(np.array([x]), np.array([y]))[0])
    skyline = extract_skyline(photo, masks)
    width, height = photo.size
    valid = np.isfinite(skyline[1])
    fraction = float(valid.mean())
    columns = skyline[0][valid]
    rows = skyline[1][valid]
    if fraction < MIN_SKYLINE_FRACTION:
        entry["reason"] = f"photo skyline found in only {fraction:.0%} of the columns"
        print(f"{camera_id}: unsettled, {entry['reason']}", file=sys.stderr)
        return
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
        "peaks_in_view": [f"{p['name']} ({p['distance_m'] / 1000:.1f} km, OSM node {p['osm_id']})" for p in in_view],
    }
    entry["fit"] = fit_record
    entry["confidence"] = confidence
    image_name = f"{camera_id}-own-skyline.jpg"
    entry.setdefault("comparison_images", []).append(image_name)
    if reason:
        entry["reason"] = "; ".join(filter(None, [entry.get("reason"), f"own skyline: {reason}"]))
    else:
        entry.pop("reason", None)
        entry["method"] = "own skyline"
        entry["bearing_deg"] = fit_record["bearing_deg"]
        entry["fov_deg"] = fit_record["fov_deg"]
        entry["range_km"] = fit_record["median_skyline_distance_km"]
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
        evidence_dir / image_name,
    )
    print(
        f"{camera_id}: own skyline {verdict} bearing {fit.pose.bearing:.1f} fov {fit.pose.fov:.1f}"
        f" residual {fit.cost_px:.1f}/{tolerance:.1f} px",
        file=sys.stderr,
    )


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
        body, last_modified, problem = load_frame(
            url, args.frames_dir / f"{camera_id}.jpg", str(camera.get("provider", ""))
        )
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

    masks_of: dict[str, tuple[tuple[float, float, float, float], ...]] = {
        camera["id"]: (
            FERATEL_MASKS
            if camera.get("provider") == "feratel"
            else PRADOLLANO_MASKS
            if camera["id"] in static_ids
            else ()
        )
        for camera, _, _, _ in usable
    }
    by_station: dict[str, list[tuple[dict[str, Any], dict[str, Any], Image.Image, str | None]]] = {}
    for item in usable:
        station = feratel_station(item[0]) if item[0].get("provider") == "feratel" else None
        if station:
            by_station.setdefault(station, []).append(item)
    stations: dict[str, Any] = {}
    for station, views in by_station.items():
        stations[station] = settle_station(dem, station, views, masks_of, peaks, args)
    for camera, entry, photo, captured in usable:
        if entry["bearing_deg"] is None:
            single_view(dem, camera, entry, photo, captured, masks_of[camera["id"]], peaks, args.evidence_dir)

    output = {
        "generated_by": "scripts/webcam_bearing.py",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "method": (
            "Skylines are matched to the skyline rendered from the Copernicus GLO-30 DEM at the provider position "
            "(curvature and refraction k=0.13). Feratel views: the station's daylight panoramas are fitted jointly "
            "(cylindrical pose, published span), each view is located in the panorama of its capture cycle by "
            "edge cross-correlation, and the view's own skyline must confirm the pose (method 'station panorama'). "
            "Otherwise the view's own skyline is fitted over all bearings (pinhole camera, method 'own skyline'). "
            "range_km is the median distance to the rendered skyline inside the field of view. Unsettled cameras "
            "have no bearing and wait for a person to confirm one; their fit blocks are the best candidates, "
            "not bearings."
        ),
        "dem": "Copernicus DEM GLO-30 (copernicus-dem-30m on AWS Open Data), resampled to 30 m EPSG:32630",
        "peaks": "OpenStreetMap natural=peak via the Overpass API, labels only",
        "stations": stations,
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
