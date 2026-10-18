import ast
import re
import tarfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

DOWNLOAD_URL = "https://www.aemet.es/es/api-eltiempo/modelos/download/harmonie/PB"
USER_AGENT = "NivoSense forecast pipeline"
WINDOW_HOURS = 6
MAX_HORIZON_HOURS = 48
RUN_HOURS = (0, 6, 12, 18)
VISIBLE_ALPHA = 128
PRECIPITATION_MEMBER = re.compile(r"down_(?P<valid>[^_]+)_61_6HH\.tif$")
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


def decode_window(data: bytes, bbox: tuple[float, float, float, float]):
    """Reads one rendered precipitation map and recovers per-class bounds in millimetres.

    The product is a colour-classified image rather than a physical field, so each
    pixel is assigned to the legend class with the nearest colour. Returns the lower
    bound, upper bound and estimate rasters, the window transform and the domain bounds.
    """
    import math

    import numpy as np
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

    classes = sorted(
        (
            float(item["Valores"][0]),
            None if item["Valores"][1] == "" else float(item["Valores"][1]),
            [int(channel) for channel in item["RGBA"][:3]],
        )
        for item in legend
    )
    lowest = classes[0]
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
    upper = np.where(visible, highs[nearest], lowest[1]).astype("float32")
    estimate = np.where(visible, estimates[nearest], 0.0).astype("float32")
    return lower, upper, estimate, transform, domain
