"""Products and references as tidy tables, and the matching of one to the other.

A table has the columns date, value, lat, lon. Optional: variable, unit, and either quantile columns named
q<percent> (q10, q50, q90) or several rows per date and point with a `member` column (an ensemble).
This is the format to drop in-situ data from ERHIN or Cetursa into, once it exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED = ("date", "value", "lat", "lon")
CATALOGUE_PREFIX = "catalogue:"


def read_table(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = [c for c in REQUIRED if c not in frame.columns and not (c == "value" and quantile_columns(frame))]
    if missing:
        raise ValueError(f"{path} lacks the columns {missing}; expected date, value, lat, lon")
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    if "value" not in frame.columns:
        frame["value"] = frame["q50"] if "q50" in frame.columns else np.nan
    return frame


def quantile_columns(frame: pd.DataFrame) -> dict[float, str]:
    """Quantile level (0 to 1) -> column, for columns named q<percent>."""
    found = {}
    for column in frame.columns:
        match = re.fullmatch(r"q(\d+(?:\.\d+)?)", str(column))
        if match:
            found[float(match.group(1)) / 100.0] = str(column)
    return dict(sorted(found.items()))


def reduce_members(frame: pd.DataFrame) -> pd.DataFrame:
    """Collapse an ensemble table (a `member` column) to one row per date and point: the median as `value`
    and the members kept as columns `m0, m1, ...` for the ensemble scores."""
    if "member" not in frame.columns:
        return frame
    keys = [c for c in ("date", "lat", "lon", "variable") if c in frame.columns]
    wide = frame.pivot_table(index=keys, columns="member", values="value").reset_index()
    members = [c for c in wide.columns if c not in keys]
    wide = wide.rename(columns={m: f"m{m}" for m in members})
    wide["value"] = wide[[f"m{m}" for m in members]].median(axis=1)
    return wide


def member_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if re.fullmatch(r"m\d+", str(c))]


def locations(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[["lat", "lon"]].drop_duplicates().reset_index(drop=True)


def match(product: pd.DataFrame, reference: pd.DataFrame, max_distance_m: float = 150.0) -> pd.DataFrame:
    """Pair product and reference rows on the same date and the same place.

    Each product row is assigned to the nearest reference location, kept when it is within `max_distance_m`
    (1.5 cells of a 100 m grid, so a product sampled at the cell of a point still matches). Result columns:
    date, lat, lon (reference), ref, sim, plus the product's quantile and member columns.
    """
    ref_loc = locations(reference)
    lat0 = np.deg2rad(ref_loc["lat"].mean())
    scale = np.array([111_320.0, 111_320.0 * np.cos(lat0)])  # metres per degree, lat then lon

    def metres(frame: pd.DataFrame) -> np.ndarray:
        return frame[["lat", "lon"]].to_numpy() * scale

    distance = np.linalg.norm(metres(product)[:, None, :] - metres(ref_loc)[None, :, :], axis=2)
    nearest = distance.argmin(axis=1)
    kept = distance[np.arange(len(product)), nearest] <= max_distance_m
    sim = product.loc[kept].copy()
    sim["lat"] = ref_loc["lat"].to_numpy()[nearest[kept]]
    sim["lon"] = ref_loc["lon"].to_numpy()[nearest[kept]]
    sim = sim.rename(columns={"value": "sim"}).drop(columns=[c for c in ("variable", "unit") if c in sim.columns])
    ref = reference[["date", "lat", "lon", "value"]].rename(columns={"value": "ref"})
    return ref.merge(sim, on=["date", "lat", "lon"], how="inner").sort_values("date", ignore_index=True)
