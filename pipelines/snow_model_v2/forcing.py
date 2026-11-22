"""Hourly forcing of one water year for the v2 snow model, from Open-Meteo.

Models (verified on 2026-11-22, see docs/snow-methodology.md 4.2):
- `ecmwf_ifs`: IFS HRES 9 km, archive from 2017. Default.
- `era5`: ERA5 0.25 degrees, archive from 1940. Not `era5_land`: it returns temperature and snow depth only,
  with no precipitation or radiation.

Elevation. The archive API returns, for each coordinate, the values of the nearest grid cell and reports the
90 m DEM elevation of the requested coordinate (a summit pixel at 37.05, -3.31 gives 3389 m although the cell
mean is far lower). Its temperature is already lapse-corrected from the cell elevation to that DEM elevation
(about 6.4 K per km on IFS and ERA5). The v1 loader passes no elevation, so its temperature carries the lapse
to a single DEM pixel while that pixel elevation is stored as the forcing elevation. Here every point is
requested with an explicit `elevation` (the caller passes the mean DEM elevation of the cells the point
represents), so the temperature Open-Meteo returns is for that elevation and the model applies its own lapse
only relative to it. Precipitation and radiation of ERA5 do not depend on `elevation`; IFS precipitation and
shortwave did change with it in the test, which is why the requested elevation is part of the cache key.

Splice. The archive lags real time (ERA5 about 5 days). The days after the archive end, up to today, come from
the forecast API with `past_days`; ERA5 has no forecast product, so those days come from `ecmwf_ifs` and are
flagged in `HourlyForcing.from_forecast`. Only the archive part is cached, and an unfinished season is
extended incrementally.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from pipelines.snow_model.forcing import neighbour_weights, request_points

from .contract import SeasonForcing
from .storms import segment_storms

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
VARIABLES = ("temperature_2m", "precipitation", "shortwave_radiation")
MODELS = ("ecmwf_ifs", "era5")
DEFAULT_MODEL = "ecmwf_ifs"
# First water year with an archive per model (IFS HRES from 2017-01-01).
FIRST_WATER_YEAR = {"ecmwf_ifs": 2016, "era5": 1940}
# Days the archive trails real time: ERA5 5 days (Open-Meteo docs); IFS is nearer real time, 3 is a margin.
ARCHIVE_LAG_DAYS = {"ecmwf_ifs": 3, "era5": 7}
FORECAST_MODEL = "ecmwf_ifs"
MAX_PAST_DAYS = 92
# Free tier: 600 calls per minute, and a request over more than 2 weeks for one location counts as several.
POINTS_PER_REQUEST = 10
PAUSE_SECONDS = 2.0
MAX_MISSING_FRACTION = 0.02

GetJson = Callable[[str], list[dict]]


@dataclass
class HourlyForcing:
    """Hourly forcing at the lattice points from `start` 00:00 UTC. Arrays are (points, hours).

    lon, lat, elevation are the requested coordinates and elevations; cell_lon, cell_lat and cell_elevation
    are what Open-Meteo reports (grid cell centre and the elevation of the values returned).
    """

    model: str
    water_year: int
    start: date
    lon: np.ndarray
    lat: np.ndarray
    elevation: np.ndarray
    cell_lon: np.ndarray
    cell_lat: np.ndarray
    cell_elevation: np.ndarray
    temperature: np.ndarray
    precipitation: np.ndarray
    shortwave: np.ndarray
    from_forecast: np.ndarray

    @property
    def hours(self) -> int:
        return int(self.precipitation.shape[1])

    @property
    def days(self) -> list[date]:
        return [self.start + timedelta(days=d) for d in range(self.hours // 24)]


def water_year_bounds(water_year: int) -> tuple[date, date]:
    """1 October of `water_year` to 30 September of the next year (water year 2024 is 2024-25)."""
    return date(water_year, 10, 1), date(water_year + 1, 9, 30)


def lattice(bbox: tuple[float, float, float, float], spacing: float = 0.1) -> list[tuple[float, float]]:
    """(lat, lon) points of the 0.1 degree lattice over the bbox, the one v1 uses."""
    return request_points(bbox, spacing)


def _get_json(url: str, attempts: int = 6) -> list[dict]:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                payload = json.load(response)
            return payload if isinstance(payload, list) else [payload]
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == attempts:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts:
                raise
        # 429 on the free tier means the minute or hour budget is spent; waiting longer is the only fix.
        time.sleep(min(30 * 2 ** (attempt - 1), 600))
    raise RuntimeError("unreachable")


def _location_params(points: list[tuple[float, float]], elevations: list[float]) -> dict[str, str]:
    return {
        "latitude": ",".join(f"{lat:.4f}" for lat, _ in points),
        "longitude": ",".join(f"{lon:.4f}" for _, lon in points),
        "elevation": ",".join(f"{e:.0f}" for e in elevations),
    }


def _place(records: list[dict], origin: datetime, hours: int) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Records in request order to (points, hours) arrays; hours the API did not return stay NaN."""
    arrays = {name: np.full((len(records), hours), np.nan, dtype="float32") for name in VARIABLES}
    for index, record in enumerate(records):
        slots = np.array(
            [int((datetime.fromisoformat(stamp) - origin) / timedelta(hours=1)) for stamp in record["hourly"]["time"]]
        )
        keep = (slots >= 0) & (slots < hours)
        for name in VARIABLES:
            values = np.array([np.nan if v is None else v for v in record["hourly"][name]], dtype="float32")
            arrays[name][index, slots[keep]] = values[keep]
    cell = np.array([[r["longitude"], r["latitude"], r["elevation"]] for r in records], dtype="float64")
    return arrays, cell


def _fetch_archive(
    points: list[tuple[float, float]],
    elevations: list[float],
    start: date,
    end: date,
    model: str,
    get_json: GetJson,
    pause: float,
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    records: list[dict] = []
    for offset in range(0, len(points), POINTS_PER_REQUEST):
        chunk = slice(offset, offset + POINTS_PER_REQUEST)
        query = urllib.parse.urlencode(
            {
                **_location_params(points[chunk], elevations[chunk]),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "hourly": ",".join(VARIABLES),
                "models": model,
                "timezone": "UTC",
            }
        )
        records.extend(get_json(f"{ARCHIVE_URL}?{query}"))
        time.sleep(pause)
    if len(records) != len(points):
        raise RuntimeError(f"Open-Meteo returned {len(records)} locations for {len(points)} requested")
    hours = ((end - start).days + 1) * 24
    return _place(records, datetime.combine(start, datetime.min.time()), hours)


def _fetch_forecast(
    points: list[tuple[float, float]],
    elevations: list[float],
    first: date,
    end: date,
    today: date,
    get_json: GetJson,
    pause: float,
) -> dict[str, np.ndarray]:
    past_days = max(0, (today - first).days)
    if past_days > MAX_PAST_DAYS:
        raise ValueError(f"The forecast API reaches back {MAX_PAST_DAYS} days; {first} is {past_days} days ago")
    forecast_days = max(1, (end - today).days + 1)
    records: list[dict] = []
    for offset in range(0, len(points), POINTS_PER_REQUEST):
        chunk = slice(offset, offset + POINTS_PER_REQUEST)
        query = urllib.parse.urlencode(
            {
                **_location_params(points[chunk], elevations[chunk]),
                "hourly": ",".join(VARIABLES),
                "models": FORECAST_MODEL,
                "past_days": past_days,
                "forecast_days": forecast_days,
                "timezone": "UTC",
            }
        )
        records.extend(get_json(f"{FORECAST_URL}?{query}"))
        time.sleep(pause)
    hours = ((end - first).days + 1) * 24
    arrays, _ = _place(records, datetime.combine(first, datetime.min.time()), hours)
    return arrays


def _fill(values: np.ndarray, label: str, interpolate: bool) -> np.ndarray:
    """Short gaps: interpolated for temperature, zero for precipitation and radiation (no invented rain)."""
    missing = np.isnan(values)
    if missing.mean() > MAX_MISSING_FRACTION:
        raise RuntimeError(f"Too many missing {label} values in the forcing data")
    if not missing.any():
        return values
    filled = values.copy()
    for row in filled:
        gaps = np.isnan(row)
        if gaps.any():
            row[gaps] = np.interp(np.flatnonzero(gaps), np.flatnonzero(~gaps), row[~gaps]) if interpolate else 0.0
    return filled


def _clean(arrays: dict[str, np.ndarray], label: str) -> dict[str, np.ndarray]:
    return {
        "temperature": _fill(arrays["temperature_2m"], f"{label} temperature", True),
        "precipitation": np.maximum(_fill(arrays["precipitation"], f"{label} precipitation", False), 0),
        "shortwave": np.maximum(_fill(arrays["shortwave_radiation"], f"{label} shortwave radiation", False), 0),
    }


def cache_path(
    cache: Path, model: str, water_year: int, points: list[tuple[float, float]], elevations: list[float]
) -> Path:
    payload = json.dumps([[round(lat, 4), round(lon, 4), round(e)] for (lat, lon), e in zip(points, elevations)])
    digest = hashlib.sha256(payload.encode()).hexdigest()[:12]
    return cache / f"forcing-{model}-wy{water_year}-{len(points)}p-{digest}.npz"


def fetch_season_forcing(
    water_year: int,
    points: list[tuple[float, float]],
    elevations: list[float],
    cache: Path,
    model: str = DEFAULT_MODEL,
    end: date | None = None,
    today: date | None = None,
    get_json: GetJson = _get_json,
    pause: float = PAUSE_SECONDS,
) -> HourlyForcing:
    """Hourly forcing from 1 October of the water year to `end` (default: the season end, capped at today).

    points are (lat, lon); elevations the elevation in metres each point's values are adjusted to.
    """
    if model not in MODELS:
        raise ValueError(f"model must be one of {MODELS}, got {model}")
    if water_year < FIRST_WATER_YEAR[model]:
        raise ValueError(f"{model} has no archive before water year {FIRST_WATER_YEAR[model]}")
    if len(points) != len(elevations):
        raise ValueError("one elevation per point")
    today = today or date.today()
    start, season_end = water_year_bounds(water_year)
    end = min(end or season_end, season_end, today)
    archive_end = min(end, today - timedelta(days=ARCHIVE_LAG_DAYS[model]))
    if archive_end < start:
        raise ValueError("the water year has not started far enough for the archive")
    hours = ((end - start).days + 1) * 24
    archive_hours = ((archive_end - start).days + 1) * 24

    path = cache_path(cache, model, water_year, points, elevations)
    stored: dict[str, np.ndarray] | None = None
    if path.exists():
        with np.load(path) as handle:
            stored = {name: handle[name] for name in handle.files}
    if stored is None or stored["temperature"].shape[1] < archive_hours:
        have = 0 if stored is None else stored["temperature"].shape[1]
        first = start + timedelta(hours=have)
        arrays, cell = _fetch_archive(points, elevations, first, archive_end, model, get_json, pause)
        new = _clean(arrays, "archive")
        if stored is not None:
            new = {name: np.concatenate([stored[name], new[name]], axis=1) for name in new}
            cell = stored["cell"]
        stored = {**new, "cell": cell}
        cache.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = stored
        np.savez_compressed(path, **payload)

    series = {name: stored[name][:, :archive_hours] for name in ("temperature", "precipitation", "shortwave")}
    from_forecast = np.zeros(hours, dtype=bool)
    if end > archive_end:
        first = archive_end + timedelta(days=1)
        tail = _clean(_fetch_forecast(points, elevations, first, end, today, get_json, pause), "forecast")
        series = {name: np.concatenate([series[name], tail[name]], axis=1) for name in series}
        from_forecast[archive_hours:] = True
    cell = stored["cell"]
    return HourlyForcing(
        model=model,
        water_year=water_year,
        start=start,
        lon=np.array([lon for _, lon in points], dtype="float64"),
        lat=np.array([lat for lat, _ in points], dtype="float64"),
        elevation=np.asarray(elevations, dtype="float32"),
        cell_lon=cell[:, 0],
        cell_lat=cell[:, 1],
        cell_elevation=cell[:, 2].astype("float32"),
        temperature=series["temperature"],
        precipitation=series["precipitation"],
        shortwave=series["shortwave"],
        from_forecast=from_forecast,
    )


def daily_totals(hourly: np.ndarray) -> np.ndarray:
    """(points, hours) to (points, days) sums, for precipitation in mm."""
    return np.asarray(hourly.reshape(hourly.shape[0], -1, 24).sum(axis=2))


def daily_means(hourly: np.ndarray) -> np.ndarray:
    """(points, hours) to (points, days) means, for temperature and shortwave radiation."""
    return np.asarray(hourly.reshape(hourly.shape[0], -1, 24).mean(axis=2))


def class_weights(forcing: HourlyForcing, class_x: np.ndarray, class_y: np.ndarray, crs: str) -> np.ndarray:
    """(classes, points) inverse-distance weights of the nearest points to each class centre, rows sum to 1."""
    adapter: Any = forcing
    nearest, weights = neighbour_weights(adapter, class_x, class_y, crs)
    dense = np.zeros((len(class_x), len(forcing.lon)), dtype="float32")
    np.put_along_axis(dense, nearest, weights, axis=1)
    return dense


def to_classes(hourly: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """(points, hours) to (classes, hours) class means with a (classes, points) weight matrix."""
    if weights.shape[1] != hourly.shape[0]:
        raise ValueError("weights need one column per forcing point")
    normalised = weights / weights.sum(axis=1, keepdims=True)
    return np.asarray((normalised @ hourly).astype("float32"))


def to_season_forcing(hourly: HourlyForcing) -> SeasonForcing:
    """The engine's forcing: (points, days, 24) arrays, daily mean shortwave, and one regional storm
    segmentation from the mean precipitation of the points, so every point shares the storm timing.

    `elevation` is the elevation the temperature was requested for (the caller passes the mean DEM elevation
    the point represents), which the engine takes as the elevation the weather model sees."""
    days = hourly.hours // 24
    points = hourly.precipitation.shape[0]
    regional = hourly.precipitation.mean(axis=0)
    storm_id = segment_storms(regional).storm_id.reshape(days, 24)
    return SeasonForcing(
        days=hourly.days,
        elevation=hourly.elevation.astype("float32"),
        temperature=hourly.temperature.reshape(points, days, 24),
        precipitation=hourly.precipitation.reshape(points, days, 24),
        shortwave=daily_means(hourly.shortwave).astype("float32"),
        storm_id=storm_id,
    )
