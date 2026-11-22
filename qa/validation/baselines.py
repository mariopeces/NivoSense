"""Baseline predictors to score a new model against: the v1 product in the catalogue, and the prior.

v1 is read from the public prod bucket (catalogue layers `swe` in mm and `snow_depth` in m, 100 m, EPSG:32630,
one COG per date under `catalog/entries/<layer>/<date>.json`). A date without an entry is ambiguous: the
model had no snow above 5 mm, or it was not run (v1 ran 2024-10 to 2025-03 and from 2026-10 only, and nothing
in the catalogue tells the two apart). Such dates are skipped and counted, never read as zero: reading them as
zero scored April to June 2025 as "no snow" while Sentinel-2 showed snow.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterable
from datetime import date

import numpy as np
import pandas as pd

from pipelines.catalog.storage import Blob

PROD_URL = "https://storage.googleapis.com/nivosense-cogs/prod"
LAYER_VARIABLE = {"swe": ("swe", "mm"), "snow_depth": ("snow_depth", "m")}


class HttpStorage:
    """Read-only access to a public catalogue over HTTPS; enough for `insertion.load_observation`."""

    def __init__(self, base_url: str = PROD_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def __repr__(self) -> str:
        return f"HttpStorage({self.base_url})"

    def read(self, key: str) -> Blob | None:
        request = urllib.request.Request(f"{self.base_url}/{key}", headers={"User-Agent": "nivosense-validation"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return Blob(response.read(), 0, response.headers.get("Content-Type", ""), "", None)
        except urllib.error.HTTPError as error:
            if error.code in (403, 404):
                return None
            raise

    def exists(self, key: str) -> bool:
        return self.read(key) is not None


def catalogue_dates(storage: HttpStorage, layer: str) -> list[date]:
    blob = storage.read("catalog/index.json")
    if blob is None:
        raise FileNotFoundError(f"No catalog/index.json in {storage!r}")
    index = json.loads(blob.data)
    return [date.fromisoformat(d) for d in index["layers"].get(layer, {}).get("dates", [])]


def read_layer(storage: HttpStorage, layer: str, day: date) -> tuple[np.ndarray, object, str, dict] | None:
    """The raster of a catalogue entry as float with nodata read as zero, its rasterio transform and CRS, and the
    entry; None when the date has no entry."""
    from rasterio.io import MemoryFile

    blob = storage.read(f"catalog/entries/{layer}/{day.isoformat()}.json")
    if blob is None:
        return None
    entry = json.loads(blob.data)
    cog = storage.read(entry["cog"])
    if cog is None:
        return None
    with MemoryFile(cog.data) as memory, memory.open() as source:
        values = source.read(1).astype("float64")
        # The model layers store cells below the visible threshold as nodata (the entry says -9999), so nodata
        # means "no snow here"; the cells outside the domain are told apart by the snow_obs mask instead.
        if source.nodata is not None:
            values[values == source.nodata] = 0.0
        return values, source.transform, source.crs.to_string(), entry


def sample_catalogue(
    storage: HttpStorage, layer: str, points: pd.DataFrame, days: Iterable[date]
) -> tuple[pd.DataFrame, dict[str, int]]:
    """The catalogue layer at each (lat, lon) of `points` on each of `days`, as a table of date, value, lat, lon,
    variable, unit. Dates with no catalogue entry are skipped and counted in `stats["no_entry_days"]`."""
    from rasterio.warp import transform as warp

    variable, unit = LAYER_VARIABLE[layer]
    published = set(catalogue_dates(storage, layer))
    if not published:
        return pd.DataFrame(columns=["date", "value", "lat", "lon", "variable", "unit"]), {"no_entry_days": 0}
    rows: list[dict[str, object]] = []
    stats = {"no_entry_days": 0, "outside_raster_points": 0}
    for day in sorted(set(days)):
        raster = read_layer(storage, layer, day) if day in published else None
        if raster is None:
            stats["no_entry_days"] += 1
            continue
        values, transform, crs, _ = raster
        for point in points.itertuples():
            xs, ys = warp("EPSG:4326", crs, [point.lon], [point.lat])
            row, col = _index(transform, xs[0], ys[0])
            if 0 <= row < values.shape[0] and 0 <= col < values.shape[1]:
                value = float(values[row, col])
            else:
                value = float("nan")
                stats["outside_raster_points"] += 1
            rows.append(
                {
                    "date": pd.Timestamp(day),
                    "value": value,
                    "lat": point.lat,
                    "lon": point.lon,
                    "variable": variable,
                    "unit": unit,
                }
            )
    return pd.DataFrame(rows, columns=["date", "value", "lat", "lon", "variable", "unit"]), stats


def _index(transform: object, x: float, y: float) -> tuple[int, int]:
    inverse = ~transform  # type: ignore[operator]
    col, row = inverse @ (x, y)
    return int(np.floor(row)), int(np.floor(col))


def prior_median(ensemble: pd.DataFrame) -> pd.DataFrame:
    """Prior baseline: the ensemble median without assimilation, from a long table of date, lat, lon, member,
    value (the run of the v2 engine with the observations switched off)."""
    keys = [c for c in ("date", "lat", "lon", "variable") if c in ensemble.columns]
    return ensemble.groupby(keys, as_index=False)["value"].median()
