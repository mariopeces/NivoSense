"""Google DeepMind WeatherNext 3: ensemble-mean surface fields from the precomputed statistics Zarr store.

Access needs an allowlisted Google identity (WeatherNext Data Request Form); see docs/weathernext.md. The
statistics bucket is not requester-pays and needs no billing header. Credentials come from Application Default
Credentials (Workload Identity Federation in the workflow), never from keys in the repository.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    import xarray as xr
    from affine import Affine

BUCKET = "weathernext3_statistics_spatial"
ROOT = "weathernext_3_0_0_statistics/zarr/2026_to_present"
GRID_DEGREES = 0.1
# Variable name in the store, factor, offset and unit shown on the site (value * factor + offset).
# The store holds SI units: kelvin, metres of water per hour, metres per second.
SOURCES = {
    "temperature_2m": ("temperature_2m_mean", 1.0, -273.15, "°C"),
    "wind_speed_10m": ("wind_speed_10m_mean", 3.6, 0.0, "km/h"),
    "precipitation_total": ("total_precipitation_1hr_mean", 1000.0, 0.0, "mm"),
}
ATTRIBUTION = (
    "Google DeepMind, WeatherNext 3 (media de 64 miembros). "
    "Datos con los términos GDM Real-Time Weather Forecasting Experimental Data Terms of Use; "
    "pasadas de más de una hora, CC BY 4.0"
)
SOURCE_URL = "https://developers.google.com/weathernext"


def init_prefix(cycle: datetime) -> str:
    """Only the 00, 06, 12 and 18 UTC runs reach 360 h; the hourly interim runs stop at 48 h."""
    return f"{ROOT}/{cycle:%Y%m%d_%H}hr_01_preds/predictions.zarr"


def _credentials():
    """Application Default Credentials as an obstore credential provider.

    obstore does not read the external-account file that Workload Identity Federation writes, so the
    token comes from google-auth, which does.
    """
    import google.auth
    from google.auth.transport.requests import Request

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/devstorage.read_only"])

    def provider() -> dict:
        credentials.refresh(Request())
        return {"token": credentials.token, "expires_at": credentials.expiry.replace(tzinfo=timezone.utc)}

    return provider


def _store(cycle: datetime):
    import obstore

    return obstore.store.GCSStore(
        bucket=BUCKET, prefix=init_prefix(cycle), credential_provider=_credentials()
    )


def is_complete(cycle: datetime, final_hour: int) -> bool:
    """True when the last hourly chunk of the last needed field is already published."""
    import obstore

    try:
        obstore.head(_store(cycle), f"{SOURCES['precipitation_total'][0]}/c/{final_hour - 1}/0/0")
    except OSError:
        return False
    return True


def open_run(cycle: datetime) -> xr.Dataset:
    import xarray as xr
    import zarr

    return xr.open_zarr(zarr.storage.ObjectStore(_store(cycle)), chunks=None, consolidated=False)


def regional_fields(
    dataset: xr.Dataset, bbox: tuple[float, float, float, float], horizons: tuple[int, ...]
) -> tuple[dict[str, dict[int, np.ndarray]], Affine]:
    """Slices the region and returns, per variable and horizon, a north-up array in site units.

    Temperature and wind are the ensemble mean at the valid hour; precipitation is the sum of the
    hourly ensemble means from the run time to the horizon. All cells within one cell of the bbox are
    kept so the image covers it.
    """
    import numpy as np
    from rasterio.transform import from_origin

    west, south, east, north = bbox
    step = GRID_DEGREES
    lat = dataset["lat_0p1"].values
    lon = dataset["lon_0p1"].values
    lat_index = np.flatnonzero((lat >= south - step) & (lat <= north + step))
    lon_index = np.flatnonzero((lon >= west % 360 - step) & (lon <= east % 360 + step))
    if not lat_index.size or not lon_index.size:
        raise ValueError("Region is outside the WeatherNext grid")
    rows = slice(int(lat_index[0]), int(lat_index[-1]) + 1)
    columns = slice(int(lon_index[0]), int(lon_index[-1]) + 1)

    lead_hours = (dataset["lead_time"].values / np.timedelta64(1, "h")).astype(int)
    wanted = np.flatnonzero((lead_hours >= 1) & (lead_hours <= max(horizons)))
    result: dict[str, dict[int, np.ndarray]] = {}
    for variable, (name, factor, offset, _) in SOURCES.items():
        field = dataset[name].isel(lat_0p1=rows, lon_0p1=columns)
        if variable == "precipitation_total":
            cumulative = field.isel(lead_time=wanted).load().cumsum(dim="lead_time").values
            picks = {h: cumulative[int(np.flatnonzero(lead_hours[wanted] == h)[0])] for h in horizons}
        else:
            picks = {h: field.isel(lead_time=int(np.flatnonzero(lead_hours == h)[0])).values for h in horizons}
        result[variable] = {h: np.flipud(v.astype("float32") * factor + offset) for h, v in picks.items()}

    first_lon = (float(lon[columns][0]) + 180) % 360 - 180
    transform = from_origin(first_lon - step / 2, float(lat[rows][-1]) + step / 2, step, step)
    return result, transform
