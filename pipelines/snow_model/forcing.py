import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
VARIABLES = ("temperature_2m", "precipitation", "shortwave_radiation")
CHUNK = 20
MAX_MISSING_FRACTION = 0.02
NEIGHBOURS = 4


@dataclass
class Forcing:
    days: list[date]
    lon: np.ndarray
    lat: np.ndarray
    elevation: np.ndarray
    temperature: np.ndarray
    precipitation: np.ndarray
    shortwave: np.ndarray


def request_points(
    bbox: tuple[float, float, float, float], spacing: float
) -> list[tuple[float, float]]:
    west, south, east, north = bbox
    lons = np.arange(np.floor(west / spacing) * spacing, east + spacing, spacing)
    lats = np.arange(np.floor(south / spacing) * spacing, north + spacing, spacing)
    return [(round(float(lat), 4), round(float(lon), 4)) for lat in lats for lon in lons]


def _fetch(url: str, attempts: int = 5) -> list[dict]:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                payload = json.load(response)
            return payload if isinstance(payload, list) else [payload]
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503) or attempt == attempts:
                raise
            time.sleep(20 * attempt)
    raise RuntimeError("unreachable")


def _fill_missing(values: np.ndarray, label: str) -> np.ndarray:
    missing = np.isnan(values)
    if missing.mean() > MAX_MISSING_FRACTION:
        raise RuntimeError(f"Too many missing {label} values in the forcing data")
    if not missing.any():
        return values
    filled = values.copy()
    for series in range(values.shape[0]):
        row = filled[series]
        gaps = np.isnan(row)
        if gaps.any():
            row[gaps] = np.interp(np.flatnonzero(gaps), np.flatnonzero(~gaps), row[~gaps])
    return filled


def fetch_forcing(
    bbox: tuple[float, float, float, float],
    start: date,
    end: date,
    spacing: float,
    model: str,
    cache: Path,
) -> Forcing:
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    points = request_points(bbox, spacing)
    key = f"forcing-{model}-{spacing}-{start}-{end}-{len(points)}-{points[0]}-{points[-1]}.npz"
    path = cache / key
    complete_year = end < date.today() - timedelta(days=10)
    if complete_year and path.exists():
        with np.load(path) as stored:
            return Forcing(days, *(stored[name] for name in (
                "lon", "lat", "elevation", "temperature", "precipitation", "shortwave")))

    records: list[dict] = []
    for offset in range(0, len(points), CHUNK):
        chunk = points[offset : offset + CHUNK]
        query = urllib.parse.urlencode(
            {
                "latitude": ",".join(str(lat) for lat, _ in chunk),
                "longitude": ",".join(str(lon) for _, lon in chunk),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "hourly": ",".join(VARIABLES),
                "models": model,
                "timezone": "UTC",
            }
        )
        records.extend(_fetch(f"{ARCHIVE_URL}?{query}"))
        time.sleep(1)

    unique = {}
    for record in records:
        unique[(record["latitude"], record["longitude"], record["elevation"])] = record
    selected = list(unique.values())

    hours = len(days) * 24
    origin = datetime.combine(start, datetime.min.time())
    shape = (len(selected), hours)
    arrays = {name: np.full(shape, np.nan, dtype="float32") for name in VARIABLES}
    for index, record in enumerate(selected):
        slots = np.array(
            [
                int((datetime.fromisoformat(stamp) - origin) / timedelta(hours=1))
                for stamp in record["hourly"]["time"]
            ]
        )
        for name in VARIABLES:
            values = np.array(
                [np.nan if value is None else value for value in record["hourly"][name]],
                dtype="float32",
            )
            arrays[name][index, slots] = values

    temperature = _fill_missing(arrays["temperature_2m"], "temperature")
    precipitation = np.nan_to_num(_fill_missing(arrays["precipitation"], "precipitation"))
    shortwave = np.nan_to_num(_fill_missing(arrays["shortwave_radiation"], "shortwave radiation"))
    forcing = Forcing(
        days,
        np.array([record["longitude"] for record in selected], dtype="float64"),
        np.array([record["latitude"] for record in selected], dtype="float64"),
        np.array([record["elevation"] for record in selected], dtype="float32"),
        temperature.reshape(len(selected), len(days), 24),
        np.maximum(precipitation, 0).reshape(len(selected), len(days), 24),
        shortwave.reshape(len(selected), len(days), 24).mean(axis=2),
    )
    if complete_year:
        cache.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            lon=forcing.lon,
            lat=forcing.lat,
            elevation=forcing.elevation,
            temperature=forcing.temperature,
            precipitation=forcing.precipitation,
            shortwave=forcing.shortwave,
        )
    return forcing


def neighbour_weights(
    forcing: Forcing, cell_x: np.ndarray, cell_y: np.ndarray, crs: str
) -> tuple[np.ndarray, np.ndarray]:
    """Indices and inverse-distance weights of the nearest forcing points for each cell."""
    from rasterio.warp import transform

    xs, ys = transform("EPSG:4326", crs, forcing.lon.tolist(), forcing.lat.tolist())
    point_x, point_y = np.asarray(xs), np.asarray(ys)
    count = min(NEIGHBOURS, len(point_x))
    distance = np.hypot(cell_x[:, None] - point_x[None, :], cell_y[:, None] - point_y[None, :])
    nearest = np.argsort(distance, axis=1)[:, :count]
    nearest_distance = np.take_along_axis(distance, nearest, axis=1)
    weights = 1.0 / np.maximum(nearest_distance, 100.0) ** 2
    weights /= weights.sum(axis=1, keepdims=True)
    return nearest.astype("int32"), weights.astype("float32")
