"""ERA5-Land hourly forcing from the Copernicus Climate Data Store (CDS).

ERA5-Land (Munoz-Sabater et al. 2021, doi:10.5194/essd-13-4349-2021) is 0.1 deg hourly from
1950 with about five days of latency, licensed CC BY 4.0. Open-Meteo serves only its
temperature, so precipitation and radiation come from the CDS, which needs a free account,
the dataset licence accepted once on the website, and an API key (env CDSAPI_KEY). The CDS
retrieve API is driven with plain HTTP to avoid a new dependency; GRIB is decoded with ecCodes.

Accumulated fields (total precipitation, surface solar radiation downwards) hold the sum
since 00 UTC of the forecast day: the 00 UTC value closes the previous day
(ECMWF, ERA5-Land documentation, "Accumulations").
"""

import json
import os
import time
import urllib.request
from datetime import date, datetime, timedelta
from functools import partial
from pathlib import Path

import numpy as np

from ..snow_model.forcing import Forcing, _fill_missing

CDS_URL = "https://cds.climate.copernicus.eu/api"
DATASET = "reanalysis-era5-land"
VARIABLES = ("2m_temperature", "total_precipitation", "surface_solar_radiation_downwards")
GRAVITY = 9.80665
# A pad of two grid cells so every model cell has its four nearest forcing points.
PAD_DEG = 0.2


def api_key() -> str | None:
    return os.environ.get("CDSAPI_KEY") or None


def _request(method: str, url: str, key: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method, headers={"PRIVATE-TOKEN": key, "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def retrieve(inputs: dict, key: str, target: Path, poll_seconds: int = 30) -> Path:
    """Submits one CDS request, waits for it and downloads the result."""
    if target.exists():
        return target
    job = _request("POST", f"{CDS_URL}/retrieve/v1/processes/{DATASET}/execution", key, {"inputs": inputs})
    job_url = f"{CDS_URL}/retrieve/v1/jobs/{job['jobID']}"
    while job["status"] in ("accepted", "running"):
        time.sleep(poll_seconds)
        job = _request("GET", job_url, key)
    if job["status"] != "successful":
        raise RuntimeError(f"CDS job {job['jobID']} ended as {job['status']}")
    href = _request("GET", f"{job_url}/results", key)["asset"]["value"]["href"]
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    urllib.request.urlretrieve(href, partial)
    partial.replace(target)
    return target


def month_request(year: int, month: int, bbox: tuple[float, float, float, float], variables: tuple[str, ...]) -> dict:
    west, south, east, north = bbox
    return {
        "variable": list(variables),
        "year": str(year),
        "month": f"{month:02d}",
        "day": [f"{day:02d}" for day in range(1, 32)],
        "time": [f"{hour:02d}:00" for hour in range(24)],
        "area": [north + PAD_DEG, west - PAD_DEG, south - PAD_DEG, east + PAD_DEG],
        "data_format": "grib",
        "download_format": "unarchived",
    }


def deaccumulate(values: np.ndarray, hours: np.ndarray) -> np.ndarray:
    """Hourly amounts from ERA5-Land accumulations along the last axis.

    `hours` is the UTC hour of each valid time. At 01 UTC the accumulation is already the
    first hour; at every other hour (00 UTC included, which closes the day) the amount is the
    difference with the previous hour.
    """
    previous = np.concatenate([np.full(values.shape[:-1] + (1,), np.nan), values[..., :-1]], axis=-1)
    amounts = np.where(hours == 1, values, values - previous)
    return np.maximum(amounts, 0.0)


def read_grib(path: Path) -> tuple[dict[str, dict[datetime, np.ndarray]], np.ndarray, np.ndarray]:
    """Fields by ecCodes short name and valid time (NaN over sea), with cell centre lon and lat."""
    import eccodes

    fields: dict[str, dict[datetime, np.ndarray]] = {}
    lon = lat = np.empty(0)
    with path.open("rb") as handle:
        while (message := eccodes.codes_grib_new_from_file(handle)) is not None:
            try:
                get = partial(eccodes.codes_get, message)
                columns, rows = get("Ni"), get("Nj")
                values = eccodes.codes_get_values(message).astype("float64")
                if get("bitmapPresent"):
                    values[values == get("missingValue")] = np.nan
                first_lon = (get("longitudeOfFirstGridPointInDegrees") + 180) % 360 - 180
                step_x = get("iDirectionIncrementInDegrees")
                step_y = get("jDirectionIncrementInDegrees") * (1 if get("jScansPositively") else -1)
                lon = first_lon + step_x * np.arange(columns)
                lat = get("latitudeOfFirstGridPointInDegrees") + step_y * np.arange(rows)
                valid = datetime.strptime(f"{get('validityDate')}{get('validityTime'):04d}", "%Y%m%d%H%M")
                fields.setdefault(get("shortName"), {})[valid] = values.reshape(rows, columns)
            finally:
                eccodes.codes_release(message)
    return fields, lon, lat


def forcing_from_grib(paths: list[Path], orography_path: Path, start: date, end: date) -> Forcing:
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    origin = datetime.combine(start, datetime.min.time())
    # One extra hour at the end: 00 UTC of the day after closes the last day's accumulation.
    times = [origin + timedelta(hours=hour) for hour in range(len(days) * 24 + 1)]
    merged: dict[str, dict[datetime, np.ndarray]] = {}
    lon_axis = lat_axis = np.empty(0)
    for path in paths:
        fields, lon_axis, lat_axis = read_grib(path)
        for name, by_time in fields.items():
            merged.setdefault(name, {}).update(by_time)
    if "2t" not in merged:
        raise RuntimeError("No ERA5-Land temperature in the files read")
    orography_fields, _, _ = read_grib(orography_path)
    geopotential = next(iter(orography_fields["z"].values()))
    land = ~np.isnan(next(iter(merged["2t"].values())))
    rows, columns = np.nonzero(land)
    empty = np.full(land.shape, np.nan)

    def stack(name: str) -> np.ndarray:
        return np.stack([merged[name].get(stamp, empty)[rows, columns] for stamp in times], axis=1)

    hours = np.array([stamp.hour for stamp in times])
    temperature = stack("2t")[:, :-1] - 273.15
    # Amounts are labelled by the end of their hour; dropping the first gives start-labelled hours.
    precipitation = deaccumulate(stack("tp"), hours)[:, 1:] * 1000.0
    shortwave = deaccumulate(stack("ssrd"), hours)[:, 1:] / 3600.0
    count, points = len(days), rows.size
    temperature = _fill_missing(temperature.astype("float32"), "temperature")
    precipitation = np.nan_to_num(_fill_missing(precipitation.astype("float32"), "precipitation"))
    shortwave = np.nan_to_num(_fill_missing(shortwave.astype("float32"), "shortwave radiation"))
    return Forcing(
        days,
        lon_axis[columns].astype("float64"),
        lat_axis[rows].astype("float64"),
        (geopotential[rows, columns] / GRAVITY).astype("float32"),
        temperature.reshape(points, count, 24),
        precipitation.reshape(points, count, 24),
        shortwave.reshape(points, count, 24).mean(axis=2),
    )


def fetch_forcing(bbox: tuple[float, float, float, float], start: date, end: date, cache: Path) -> Forcing:
    key = api_key()
    if key is None:
        raise RuntimeError("ERA5-Land needs a CDS API key in CDSAPI_KEY")
    folder = cache / "era5-land"
    paths = []
    month = date(start.year, start.month, 1)
    last = end + timedelta(days=1)
    while month <= last:
        target = folder / f"{month:%Y-%m}-{bbox}.grib"
        paths.append(retrieve(month_request(month.year, month.month, bbox, VARIABLES), key, target))
        month = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    orography = month_request(start.year, start.month, bbox, ("geopotential",))
    orography.update(day=["01"], time=["00:00"])
    orography_path = retrieve(orography, key, folder / f"orography-{bbox}.grib")
    return forcing_from_grib(paths, orography_path, start, end)
