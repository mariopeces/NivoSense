"""Scores of snow products against references (docs/snow-methodology.md 5.3). Pure numpy and pandas.

Sign convention: errors are model minus reference, so a positive bias is an overestimate and a positive
melt-out error is a model that melts out late.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Our own choices for turning a series into "snow" and "melted out"; not from a paper. 1 cm of depth is
# about the resolution of a camera reading, and 10 % cover leaves out a lone patch in shade.
DEPTH_SNOW_M = 0.01
FSCA_SNOW = 0.1
MIN_BARE_TAIL_DAYS = 7
BAND_M = 200.0
MIN_BAND_CELLS = 30
Z80 = 1.2815515655446004  # standard normal quantile at 0.9; turns a p10 to p90 width into a spread


def _pair(sim: object, obs: object) -> tuple[np.ndarray, np.ndarray]:
    s, o = np.asarray(sim, dtype="float64"), np.asarray(obs, dtype="float64")
    if s.shape != o.shape:
        raise ValueError(f"Shapes differ: {s.shape} and {o.shape}")
    keep = np.isfinite(s) & np.isfinite(o)
    return s[keep], o[keep]


def depth_metrics(sim: object, obs: object) -> dict[str, float]:
    """RMSE, bias, MAE, correlation and KGE (Gupta et al. 2009) over the pairs where both are finite."""
    s, o = _pair(sim, obs)
    n = int(s.size)
    out = {"n": float(n), "rmse": np.nan, "bias": np.nan, "mae": np.nan, "r": np.nan, "kge": np.nan}
    if n == 0:
        return out
    err = s - o
    out.update(rmse=float(np.sqrt(np.mean(err**2))), bias=float(err.mean()), mae=float(np.abs(err).mean()))
    if n > 1 and s.std() > 0 and o.std() > 0:
        r = float(np.corrcoef(s, o)[0, 1])
        out["r"] = r
        if o.mean() != 0:
            alpha, beta = s.std() / o.std(), s.mean() / o.mean()
            out["kge"] = float(1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))
    return out


def confusion(pred: object, truth: object) -> dict[str, float]:
    p, t = np.asarray(pred, dtype=bool), np.asarray(truth, dtype=bool)
    tp, fp = float((p & t).sum()), float((p & ~t).sum())
    fn, tn = float((~p & t).sum()), float((~p & ~t).sum())
    n = tp + fp + fn + tn
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else np.nan
    denom = np.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = (tp * tn - fp * fn) / denom if denom else np.nan
    accuracy = (tp + tn) / n if n else np.nan
    return {
        "n": n,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "f1": float(f1),
        "mcc": float(mcc),
        "accuracy": float(accuracy),
    }


def brier(prob: object, truth: object) -> float:
    p, t = np.asarray(prob, dtype="float64"), np.asarray(truth, dtype="float64")
    return float(np.mean((p - t) ** 2)) if p.size else float("nan")


def presence_by_band(
    pred: object, truth: object, elevation: object, band_m: float = BAND_M, min_cells: int = MIN_BAND_CELLS
) -> pd.DataFrame:
    """Snow presence scores per elevation band. A good all-range score can hide the thin-snow bands, so the
    bands are reported one by one; bands with fewer than `min_cells` cells are left out as too small to score."""
    p, t = np.asarray(pred, dtype=bool), np.asarray(truth, dtype=bool)
    z = np.asarray(elevation, dtype="float64")
    keep = np.isfinite(z)
    base = np.floor(z[keep] / band_m) * band_m
    rows = []
    for band in np.unique(base):
        pick = base == band
        if pick.sum() < min_cells:
            continue
        rows.append(
            {
                "band_m": float(band),
                "snow_share_ref": float(t[keep][pick].mean()),
                **confusion(p[keep][pick], t[keep][pick]),
            }
        )
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class MeltOut:
    """Melt-out of one season. The true date lies between `last_snow` and `date`: the interval is the
    uncertainty of the reference when samples are days apart (clear Sentinel-2 passes)."""

    date: dt.date
    last_snow: dt.date


def melt_out_date(
    dates: object, values: object, threshold: float, min_bare_tail_days: int = MIN_BARE_TAIL_DAYS
) -> MeltOut | None:
    """Melt-out date of one season of a depth or fSCA series.

    Rule: the melt-out date is the first valid sample after the last sample above `threshold`. The season has
    no melt-out (None) when it never exceeds the threshold, when the last sample still exceeds it, or when the
    series ends less than `min_bare_tail_days` after that first bare sample, because then a late snowfall could
    still follow. NaN samples are skipped. Pass one season (a water year) at a time.
    """
    d = pd.to_datetime(pd.Series(dates)).dt.date.to_numpy()
    v = np.asarray(values, dtype="float64")
    valid = np.isfinite(v)
    d, v = d[valid], v[valid]
    order = np.argsort(d)
    d, v = d[order], v[order]
    snow = np.flatnonzero(v > threshold)
    if snow.size == 0 or snow[-1] == len(v) - 1:
        return None
    first_bare = d[snow[-1] + 1]
    if (d[-1] - first_bare) < dt.timedelta(days=min_bare_tail_days - 1):
        return None
    return MeltOut(first_bare, d[snow[-1]])


def melt_out_error_days(model: MeltOut | None, reference: MeltOut | None) -> float:
    """Model minus reference melt-out in days, NaN when either season has none."""
    if model is None or reference is None:
        return float("nan")
    return float((model.date - reference.date).days)


def crps_members(members: object, obs: object) -> float:
    """Mean CRPS of an ensemble, members on axis 0 and times on axis 1: E|X - y| - 0.5 E|X - X'|."""
    x, y = np.asarray(members, dtype="float64"), np.asarray(obs, dtype="float64")
    if x.ndim != 2 or x.shape[1] != y.shape[0]:
        raise ValueError("members must be (n_members, n_times) and obs (n_times,)")
    keep = np.isfinite(y) & np.isfinite(x).all(axis=0)
    x, y = x[:, keep], y[keep]
    if y.size == 0:
        return float("nan")
    skill = np.abs(x - y).mean(axis=0)
    spread = np.abs(x[:, None, :] - x[None, :, :]).mean(axis=(0, 1))
    return float((skill - 0.5 * spread).mean())


def crps_quantiles(levels: object, quantiles: object, obs: object) -> float:
    """Mean CRPS approximated from quantile forecasts, as 2 times the integral of the pinball loss over the
    levels (Gneiting and Ranjan 2011). Levels outside the given range count as the outermost one, so the
    approximation is good for a dense grid of levels and rough for a few (for example only p10, p50, p90).
    quantiles is (n_times, n_levels)."""
    tau = np.asarray(levels, dtype="float64")
    q, y = np.asarray(quantiles, dtype="float64"), np.asarray(obs, dtype="float64")
    if q.shape != (y.shape[0], tau.shape[0]):
        raise ValueError("quantiles must be (n_times, n_levels)")
    keep = np.isfinite(y) & np.isfinite(q).all(axis=1)
    q, y = q[keep], y[keep]
    if y.size == 0:
        return float("nan")
    diff = y[:, None] - q
    pinball = np.where(diff >= 0, tau * diff, (tau - 1.0) * diff)
    edges = np.concatenate([[0.0], (tau[1:] + tau[:-1]) / 2, [1.0]])
    return float((2.0 * (pinball * np.diff(edges)).sum(axis=1)).mean())


def interval_coverage(low: object, high: object, obs: object) -> float:
    lo, hi, y = (np.asarray(a, dtype="float64") for a in (low, high, obs))
    keep = np.isfinite(lo) & np.isfinite(hi) & np.isfinite(y)
    return float(((y[keep] >= lo[keep]) & (y[keep] <= hi[keep])).mean()) if keep.any() else float("nan")


def spread_skill_ratio(spread: object, median: object, obs: object) -> float:
    """Root mean ensemble variance over the RMSE of the median: 1 is reliable, below 1 overconfident.
    `spread` is the ensemble standard deviation per time."""
    sd, med, y = (np.asarray(a, dtype="float64") for a in (spread, median, obs))
    keep = np.isfinite(sd) & np.isfinite(med) & np.isfinite(y)
    if not keep.any():
        return float("nan")
    rmse = np.sqrt(np.mean((med[keep] - y[keep]) ** 2))
    return float(np.sqrt(np.mean(sd[keep] ** 2)) / rmse) if rmse > 0 else float("nan")


def ensemble_summary(members: object, obs: object) -> dict[str, float]:
    """CRPS, spread-skill ratio and 80 % interval coverage from members (axis 0) and observations."""
    x, y = np.asarray(members, dtype="float64"), np.asarray(obs, dtype="float64")
    low, med, high = np.quantile(x, [0.1, 0.5, 0.9], axis=0)
    return {
        "crps": crps_members(x, y),
        "spread_skill": spread_skill_ratio(x.std(axis=0, ddof=1), med, y),
        "coverage80": interval_coverage(low, high, y),
    }


def quantile_summary(levels: object, quantiles: object, obs: object) -> dict[str, float]:
    """The same from quantile columns; the spread is the p10 to p90 width over 2 x 1.2816 (a normal assumption)."""
    tau = np.asarray(levels, dtype="float64")
    q = np.asarray(quantiles, dtype="float64")
    col = {round(float(t), 4): i for i, t in enumerate(tau)}
    out = {"crps": crps_quantiles(tau, q, obs), "spread_skill": float("nan"), "coverage80": float("nan")}
    if {0.1, 0.5, 0.9} <= col.keys():
        low, med, high = q[:, col[0.1]], q[:, col[0.5]], q[:, col[0.9]]
        out["spread_skill"] = spread_skill_ratio((high - low) / (2 * Z80), med, obs)
        out["coverage80"] = interval_coverage(low, high, obs)
    return out
