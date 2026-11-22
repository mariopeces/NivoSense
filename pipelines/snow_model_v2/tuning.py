"""Leave-one-season-out tuning of the prior hyperparameters (docs/snow-methodology.md section 5.2, level 1).

Every season is run once from a wide base prior. A candidate prior is scored on a season by importance
reweighting of that base ensemble (candidate density over base density on b0 and dT) and taking the CRPS of
the resulting prior predictive snow covered fraction against the Sentinel-2 class fractions; no observation is
assimilated, so the score measures how well the prior alone predicts the season. A fold tunes on all seasons
but one and reports the held-out score of the tuned prior next to the default one.

Only the hyperparameters whose density can be reweighted are tuned: the b0 median and CV and the dT spread.
The storm noise has 100 or more dimensions per season and cannot be reweighted without degeneracy, so its
spread stays at the design value.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import asdict, dataclass, replace
from statistics import NormalDist

import numpy as np

from .assimilation import crps
from .contract import EnsembleRun, Priors
from .observations import Observations

B0_MEDIANS = (0.6, 0.8, 1.0, 1.25, 1.6)
B0_CVS = (0.25, 0.4, 0.6)
DT_SDS = (1.0, 1.5, 2.5)
MIN_ESS_FRACTION = 0.05
BASE_PRIORS = Priors(b0_median=1.0, b0_cv=0.8, b0_bounds=(0.2, 4.0), dT_sd=3.0)
_NORMAL = NormalDist()


@dataclass(frozen=True)
class Candidate:
    b0_median: float
    b0_cv: float
    dT_sd: float


def candidates() -> list[Candidate]:
    return [Candidate(*c) for c in itertools.product(B0_MEDIANS, B0_CVS, DT_SDS)]


def _log_density_b0(b0: np.ndarray, median: float, cv: float, bounds: tuple[float, float]) -> np.ndarray:
    """Log density of the truncated lognormal of `contract.sample_parameters`."""
    sigma = math.sqrt(math.log(1 + cv**2))
    low, high = (_NORMAL.cdf(math.log(b / median) / sigma) for b in bounds)
    z = np.log(b0 / median) / sigma
    return -0.5 * z**2 - np.log(b0 * sigma) - math.log(high - low)


def importance_weights(base: Priors, candidate: Candidate, b0: np.ndarray, dT: np.ndarray) -> np.ndarray:
    bounds = Priors().b0_bounds
    log_ratio = _log_density_b0(b0, candidate.b0_median, candidate.b0_cv, bounds) - _log_density_b0(
        b0, base.b0_median, base.b0_cv, base.b0_bounds
    )
    log_ratio = np.where((b0 >= bounds[0]) & (b0 <= bounds[1]), log_ratio, -np.inf)
    log_ratio += (
        -0.5 * (dT / candidate.dT_sd) ** 2 + 0.5 * (dT / base.dT_sd) ** 2 - math.log(candidate.dT_sd / base.dT_sd)
    )
    weights = np.exp(log_ratio - log_ratio.max())
    return weights / weights.sum()


@dataclass(frozen=True)
class SeasonEnsemble:
    water_year: int
    run: EnsembleRun
    predicted: np.ndarray  # (N, C, K)
    observations: Observations


def season_score(season: SeasonEnsemble, candidate: Candidate, base: Priors = BASE_PRIORS) -> float | None:
    """Prior predictive CRPS of the fSCA of one season, or None when the reweighted ensemble is too thin."""
    parameters = season.run.parameters
    weights = importance_weights(base, candidate, parameters.b0, parameters.dT)
    if 1.0 / np.sum(weights**2) < MIN_ESS_FRACTION * weights.size:
        return None
    return crps(season.predicted, season.observations, weights)


def score_table(seasons: list[SeasonEnsemble]) -> dict[Candidate, dict[int, float | None]]:
    return {c: {s.water_year: season_score(s, c) for s in seasons} for c in candidates()}


def best_candidate(table: dict[Candidate, dict[int, float | None]], years: list[int]) -> tuple[Candidate, float]:
    """The candidate with the lowest mean CRPS over `years`; candidates too thin on any year are skipped."""
    best: tuple[Candidate, float] | None = None
    for candidate, scores in table.items():
        values = [scores[y] for y in years]
        if any(v is None for v in values):
            continue
        mean = float(np.mean([v for v in values if v is not None]))
        if best is None or mean < best[1]:
            best = (candidate, mean)
    if best is None:
        raise ValueError("every candidate is too thin on some season")
    return best


def leave_one_season_out(table: dict[Candidate, dict[int, float | None]], years: list[int]) -> list[dict]:
    default = Candidate(Priors().b0_median, Priors().b0_cv, Priors().dT_sd)
    folds = []
    for held_out in years:
        training = [y for y in years if y != held_out]
        chosen, train_score = best_candidate(table, training)
        folds.append(
            {
                "held_out": held_out,
                "tuned": asdict(chosen),
                "train_crps": train_score,
                "held_out_crps_tuned": table[chosen][held_out],
                "held_out_crps_default": table.get(default, {}).get(held_out),
            }
        )
    return folds


def fold_spread(folds: list[dict]) -> dict[str, dict[str, float]]:
    spread = {}
    for name in ("b0_median", "b0_cv", "dT_sd"):
        values = np.array([f["tuned"][name] for f in folds])
        spread[name] = {
            "min": float(values.min()),
            "max": float(values.max()),
            "mean": float(values.mean()),
            "sd": float(values.std()),
        }
    return spread


def priors_from(candidate: Candidate) -> Priors:
    return replace(Priors(), b0_median=candidate.b0_median, b0_cv=candidate.b0_cv, dT_sd=candidate.dT_sd)


def load_priors(path: str) -> Priors:
    """Priors from a `regions/<id>.snow-priors.json` file; absent fields keep the design values."""
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)["priors"]
    return replace(Priors(), **{k: payload[k] for k in ("b0_median", "b0_cv", "dT_sd") if k in payload})
