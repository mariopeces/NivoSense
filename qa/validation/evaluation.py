"""Scores used to compare the v2 ensemble with v1 and with the in-situ references (docs/snow-evaluation.md).

Pure numpy and pandas. Sign convention as in metrics.py: model minus reference.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from . import metrics

BLOCK_DAYS = 12
BAND_M = 100.0
MIN_BAND_CELLS = 30
# Fewer decided cells than this and a snow line is not defined for the date.
MIN_SNOW_LINE_CELLS = 200


def block_folds(days: list[date], season_start: date, block_days: int = BLOCK_DAYS, folds: int = 3) -> np.ndarray:
    """Fold id (0 .. folds-1) of each date: blocks of `block_days` days counted from the season start are dealt
    to the folds in turn, so a held-out date never has an assimilated date within a block width of it unless
    it sits at a block edge (neighbouring blocks belong to different folds, the nearest assimilated date is
    then at most one block away; for the 5 day Sentinel-2 revisit that is the leakage the scheme tolerates)."""
    block = np.array([(day - season_start).days // block_days for day in days], dtype="int64")
    return block % folds


def snow_line(elevation: object, snow: object) -> float:
    """Snow line altitude (m): the elevation z for which the rule `snow where elevation >= z` misclassifies the
    fewest of the given cells. Ties go to the lowest z. NaN with too few cells or when one class is missing."""
    z, s = np.asarray(elevation, dtype="float64"), np.asarray(snow, dtype=bool)
    keep = np.isfinite(z)
    z, s = z[keep], s[keep]
    if z.size < MIN_SNOW_LINE_CELLS or s.all() or not s.any():
        return float("nan")
    order = np.argsort(z, kind="stable")
    z, s = z[order], s[order]
    # With the cut before sorted index i: cells below it are called bare, the others snow.
    snow_below = np.concatenate([[0], np.cumsum(s)])
    bare_above = (~s).sum() - np.concatenate([[0], np.cumsum(~s)])
    errors = snow_below + bare_above
    best = int(np.argmin(errors))
    if best == 0:
        return float(z[0])
    if best == z.size:
        return float(z[-1] + 1.0)
    return float((z[best - 1] + z[best]) / 2)


def area_bias(pred: object, truth: object) -> float:
    """Predicted over observed snow area minus one; positive means too much snow."""
    p, t = np.asarray(pred, dtype=bool), np.asarray(truth, dtype=bool)
    return float(float(p.sum()) / float(t.sum()) - 1.0) if t.any() else float("nan")


def summarise(pred: object, truth: object) -> dict[str, float]:
    out = metrics.confusion(pred, truth)
    out["area_bias"] = area_bias(pred, truth)
    return out


def band_table(preds: dict[str, np.ndarray], truth: np.ndarray, elevation: np.ndarray) -> pd.DataFrame:
    """Per 100 m band, one column set per model: F1, MCC and area bias, plus the observed snow share."""
    z = np.asarray(elevation, dtype="float64")
    base = np.floor(z / BAND_M) * BAND_M
    rows = []
    for band in np.unique(base[np.isfinite(base)]):
        pick = base == band
        if pick.sum() < MIN_BAND_CELLS:
            continue
        row: dict[str, float] = {
            "band_m": float(band),
            "cells": float(pick.sum()),
            "snow_share_ref": float(truth[pick].mean()),
        }
        for name, pred in preds.items():
            s = summarise(pred[pick], truth[pick])
            row[f"{name}_f1"], row[f"{name}_mcc"], row[f"{name}_bias"] = s["f1"], s["mcc"], s["area_bias"]
        rows.append(row)
    return pd.DataFrame(rows)


def weighted_interval(
    members: np.ndarray, weights: np.ndarray, levels: tuple[float, ...] = (0.1, 0.5, 0.9)
) -> np.ndarray:
    """Weighted quantiles of members (N, T) per time: (len(levels), T)."""
    from pipelines.snow_model.ensemble import weighted_quantiles

    return np.asarray(weighted_quantiles(members, weights, list(levels)))


def weighted_crps(members: np.ndarray, weights: np.ndarray, observed: np.ndarray) -> float:
    """Mean CRPS of a weighted ensemble (members (N, T), weights (N,) summing to one) against observed (T,):
    sum w|x - y| - 0.5 sum w w' |x - x'|, the pair term from the sorted members so the cost is N log N."""
    x, y = np.asarray(members, dtype="float64"), np.asarray(observed, dtype="float64")
    keep = np.isfinite(y)
    x, y = x[:, keep], y[keep]
    if y.size == 0:
        return float("nan")
    order = np.argsort(x, axis=0)
    sorted_x = np.take_along_axis(x, order, axis=0)
    w = np.asarray(weights, dtype="float64")[order]
    upper = np.cumsum(w, axis=0)
    pair = 2.0 * (w * sorted_x * (upper + (upper - w) - 1.0)).sum(axis=0)
    skill = (np.asarray(weights)[:, None] * np.abs(x - y[None])).sum(axis=0)
    return float(np.mean(skill - 0.5 * pair))


def depth_scores(
    members: np.ndarray, weights: np.ndarray, observed: np.ndarray, snow_m: float = metrics.DEPTH_SNOW_M
) -> dict[str, float]:
    """Scores of an ensemble of snow depth series (N, T) against an observed series (T,), metres.

    Median accuracy (RMSE, bias, KGE, r), CRPS of the weighted ensemble, 80 % interval coverage over all
    days and over snow days only (the camera or the ensemble p90 above `snow_m`), because the long bare
    summers trivially fall inside a zero-width interval.
    """
    q = weighted_interval(members, weights)
    low, med, high = q
    out = {f"{k}": v for k, v in metrics.depth_metrics(med, observed).items()}
    keep = np.isfinite(observed)
    snowy = keep & ((observed > snow_m) | (high > snow_m))
    out["coverage80"] = metrics.interval_coverage(low, high, observed)
    out["coverage80_snow_days"] = metrics.interval_coverage(low[snowy], high[snowy], observed[snowy])
    out["snow_days"] = float(snowy.sum())
    out["crps"] = weighted_crps(members, weights, observed)
    return out


def climatology(days: pd.Series, depth: pd.Series, season_of: pd.Series) -> pd.Series:
    """Leave-one-season-out day-of-season climatology of an observed series: for each row, the mean over the
    other seasons of the values within +-7 days of the same day of the water year. NaN where no other season
    has a value."""
    day_of_year = pd.to_datetime(days).dt.dayofyear.to_numpy()
    shifted = (day_of_year - 274) % 366  # 1 October is day 274 of a non-leap year
    values = depth.to_numpy(dtype="float64")
    seasons = season_of.to_numpy()
    out = np.full(values.shape, np.nan)
    for index in range(values.size):
        other = (seasons != seasons[index]) & np.isfinite(values)
        near = other & (np.abs(shifted - shifted[index]) <= 7)
        if near.any():
            out[index] = values[near].mean()
    return pd.Series(out, index=depth.index)


def annual_ratio(model: pd.DataFrame, station: pd.DataFrame, min_days: int = 1) -> pd.DataFrame:
    """Water-year model over station precipitation on the days both have a value.

    Both frames have columns date and value (mm per day). Years with fewer than `min_days` common days are
    dropped because a total over a gappy year is a lower bound.
    """
    merged = model.merge(station, on="date", suffixes=("_model", "_station")).dropna()
    merged["water_year"] = merged["date"].dt.year + (merged["date"].dt.month >= 10)
    rows = []
    for wy, part in merged.groupby("water_year"):
        if len(part) < min_days:
            continue
        rows.append(
            {
                "water_year": int(wy),
                "days": len(part),
                "station_mm": float(part["value_station"].sum()),
                "model_mm": float(part["value_model"].sum()),
                "ratio": float(part["value_model"].sum() / part["value_station"].sum())
                if part["value_station"].sum() > 0
                else float("nan"),
                "daily_r": float(np.corrcoef(part["value_model"], part["value_station"])[0, 1])
                if len(part) > 2 and part["value_station"].std() > 0 and part["value_model"].std() > 0
                else float("nan"),
            }
        )
    return pd.DataFrame(rows, columns=["water_year", "days", "station_mm", "model_mm", "ratio", "daily_r"])
