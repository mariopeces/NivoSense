from __future__ import annotations

import ast
import re
import tarfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import HTTPError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    import numpy as np
    from affine import Affine

DOWNLOAD_URL = "https://www.aemet.es/es/api-eltiempo/modelos/download/harmonie/PB"
USER_AGENT = "NivoSense forecast pipeline"
WINDOW_HOURS = 6
MAX_HORIZON_HOURS = 48
RUN_HOURS = (0, 6, 12, 18)
VISIBLE_ALPHA = 128
PRECIPITATION_MEMBER = re.compile(r"down_(?P<valid>[^_]+)_61_6HH\.tif$")
# Hourly instantaneous maps in the same archive: product 11 is temperature (deg C), 32 wind speed (km/h).
INSTANT_PRODUCTS = {"temperature_2m": "11", "wind_speed_10m": "32"}
ANY_MEMBER = re.compile(r"down_(?P<valid>[^_]+)_")


def download_archive(destination: Path, timeout: int = 300, attempts: int = 4) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(DOWNLOAD_URL, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read()
            break
        except HTTPError as error:
            if error.code < 500 or attempt == attempts:
                raise
            time.sleep(10 * attempt)
    if payload[:2] != b"\x1f\x8b":
        raise RuntimeError("AEMET download is not a gzip archive")
    destination.write_bytes(payload)
    return destination


def _valid_time(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def run_cycle(archive: tarfile.TarFile) -> datetime:
    """The archive is a rolling 48 h window whose first hourly field is run time + 1 h."""
    first = min(
        _valid_time(match["valid"])
        for name in archive.getnames()
        if (match := ANY_MEMBER.match(name))
    )
    cycle = first - timedelta(hours=1)
    if cycle.hour not in RUN_HOURS or cycle.minute:
        raise RuntimeError(f"Archive window starts at {first.isoformat()}, not at a model run")
    return cycle


def precipitation_windows(archive: tarfile.TarFile, cycle: datetime) -> dict[int, str]:
    """Maps the end hour of each disjoint 6 h accumulation window to its archive member."""
    windows = {}
    for name in archive.getnames():
        match = PRECIPITATION_MEMBER.match(name)
        if not match:
            continue
        end = (_valid_time(match["valid"]) - cycle) / timedelta(hours=1)
        if end == int(end) and 0 < end <= MAX_HORIZON_HOURS and end % WINDOW_HOURS == 0:
            windows[int(end)] = name
    expected = set(range(WINDOW_HOURS, MAX_HORIZON_HOURS + 1, WINDOW_HOURS))
    if set(windows) != expected:
        raise RuntimeError("AEMET archive lacks the complete set of 6 h precipitation windows")
    return windows


def _read_window(data: bytes, bbox: tuple[float, float, float, float]):
    import math

    import rasterio
    from rasterio.windows import Window, from_bounds

    with rasterio.MemoryFile(data) as memory, memory.open() as dataset:
        domain = tuple(dataset.bounds)
        west, south, east, north = bbox
        if not (domain[0] <= west and domain[1] <= south and east <= domain[2] and north <= domain[3]):
            raise RuntimeError("Region is outside the AEMET model domain")
        exact = from_bounds(*bbox, transform=dataset.transform)
        col, row = math.floor(exact.col_off), math.floor(exact.row_off)
        window = Window(
            col,
            row,
            math.ceil(exact.col_off + exact.width) - col,
            math.ceil(exact.row_off + exact.height) - row,
        )
        rgba = dataset.read(window=window)
        transform = dataset.window_transform(window)
        legend = ast.literal_eval(dataset.tags()["ESCALA"])["Lista RGBA"]
    return rgba, transform, domain, legend


def decode_instant(
    data: bytes, bbox: tuple[float, float, float, float]
) -> tuple[np.ndarray, Affine]:
    """Reads one rendered temperature or wind map as class midpoints.

    Every pixel is assigned to the legend class with the nearest colour, so the field is
    quantised to the class width (2 deg C for temperature, 10 km/h for wind). The open
    top class takes its lower bound.
    """
    import numpy as np

    rgba, transform, _, legend = _read_window(data, bbox)
    classes = [
        (float(item["Valores"][0]), None if item["Valores"][1] == "" else float(item["Valores"][1]), item["RGBA"][:3])
        for item in legend
    ]
    colours = np.array([[int(c) for c in item[2]] for item in classes], dtype="int32")
    estimates = np.array([item[0] if item[1] is None else (item[0] + item[1]) / 2 for item in classes], dtype="float32")
    pixels = rgba[:3].transpose(1, 2, 0).astype("int32")
    nearest = ((pixels[..., None, :] - colours) ** 2).sum(axis=-1).argmin(axis=-1)
    estimate = np.where(rgba[3] >= VISIBLE_ALPHA, estimates[nearest], np.nan).astype("float32")
    return estimate, transform


def instant_members(archive: tarfile.TarFile, cycle: datetime, product: str) -> dict[int, str]:
    """Maps each hour after the run to the archive member of an instantaneous product."""
    pattern = re.compile(rf"down_(?P<valid>[^_]+)_{product}\.tif$")
    members = {}
    for name in archive.getnames():
        match = pattern.match(name)
        if not match:
            continue
        hour = (_valid_time(match["valid"]) - cycle) / timedelta(hours=1)
        if hour == int(hour) and 0 < hour <= MAX_HORIZON_HOURS:
            members[int(hour)] = name
    return members


def decode_window(
    data: bytes, bbox: tuple[float, float, float, float]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, Affine, tuple[float, ...]]:
    """Reads one rendered precipitation map and recovers per-class bounds in millimetres.

    The product is a colour-classified image rather than a physical field, so each
    pixel is assigned to the legend class with the nearest colour. Returns the lower
    bound, upper bound and estimate rasters, the window transform and the domain bounds.
    """
    import numpy as np

    rgba, transform, domain, legend = _read_window(data, bbox)
    classes = sorted(
        (
            float(item["Valores"][0]),
            None if item["Valores"][1] == "" else float(item["Valores"][1]),
            [int(channel) for channel in item["RGBA"][:3]],
        )
        for item in legend
    )
    lowest = classes[0]
    if lowest[1] is None:
        raise ValueError("The AEMET legend's lowest class has no upper bound")
    lowest_upper = lowest[1]
    visible_classes = classes[1:]
    colours = np.array([item[2] for item in visible_classes], dtype="int32")
    lows = np.array([item[0] for item in visible_classes], dtype="float32")
    highs = np.array(
        [item[0] if item[1] is None else item[1] for item in visible_classes], dtype="float32"
    )
    estimates = np.where(
        [item[1] is None for item in visible_classes], lows, (lows + highs) / 2
    ).astype("float32")

    pixels = rgba[:3].transpose(1, 2, 0).astype("int32")
    distance = ((pixels[..., None, :] - colours) ** 2).sum(axis=-1)
    nearest = distance.argmin(axis=-1)
    visible = rgba[3] >= VISIBLE_ALPHA
    lower = np.where(visible, lows[nearest], 0.0).astype("float32")
    upper = np.where(visible, highs[nearest], lowest_upper).astype("float32")
    estimate = np.where(visible, estimates[nearest], 0.0).astype("float32")
    return lower, upper, estimate, transform, domain
