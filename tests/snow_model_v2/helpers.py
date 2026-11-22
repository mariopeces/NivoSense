from datetime import date, timedelta
from pathlib import Path

import numpy as np

from pipelines.snow_model.forcing import Forcing, neighbour_weights
from pipelines.snow_model_v2.contract import SeasonForcing

FIXTURE = Path(__file__).parent / "data" / "forcing-ecmwf_ifs-2025-02-01_2025-03-02.npz"
UTM = "EPSG:32630"


def segment_storms(precipitation: np.ndarray, dry_hours: int = 12, wet_mm: float = 0.1) -> np.ndarray:
    """Regional storm ids (D, 24): spells of domain-mean precipitation separated by at least `dry_hours` dry hours."""
    wet = precipitation.mean(axis=0).reshape(-1) > wet_mm
    ids = np.full(wet.size, -1, dtype="int32")
    storm, last = -1, None
    for hour in np.flatnonzero(wet):
        if last is None or hour - last - 1 >= dry_hours:
            storm += 1
        else:
            ids[last + 1 : hour] = storm
        ids[hour] = storm
        last = hour
    return ids.reshape(-1, 24)


def real_forcing() -> tuple[Forcing, SeasonForcing]:
    z = np.load(FIXTURE)
    days = [date(2025, 2, 1) + timedelta(days=i) for i in range(z["temperature"].shape[1])]
    v1 = Forcing(days, z["lon"], z["lat"], z["elevation"], z["temperature"], z["precipitation"], z["shortwave"])
    v2 = SeasonForcing(
        days, v1.elevation, v1.temperature, v1.precipitation, v1.shortwave, segment_storms(v1.precipitation)
    )
    return v1, v2


def random_cells(v1: Forcing, count: int, seed: int = 0):
    """Cell positions inside the forcing extent with elevations spread over the range of the region.

    Only the forcing is real data here; both models under comparison get the same cell geometry.
    """
    from rasterio.warp import transform

    rng = np.random.default_rng(seed)
    x0, y0 = transform("EPSG:4326", UTM, [-3.6433], [36.9129])
    x1, y1 = transform("EPSG:4326", UTM, [-2.5885], [37.2532])
    x = rng.uniform(x0[0], x1[0], count)
    y = rng.uniform(y0[0], y1[0], count)
    elevation = rng.uniform(900, 3300, count).astype("float32")
    neighbours, weights = neighbour_weights(v1, x, y, UTM)
    return x, y, elevation, neighbours, weights
