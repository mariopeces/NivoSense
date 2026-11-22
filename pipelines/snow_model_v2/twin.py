"""Twin experiments: recover a known truth from synthetic Sentinel-2 fractions (docs/snow-methodology.md T6).

The truth is a draw of the prior outside the ensemble. Its snow covered fraction is observed on the dates and
classes where the real Sentinel-2 season has data, with Gaussian noise of the real class error sigma_o, so the
gaps (cloud, shadow, small classes) are realistic. The experiment asks how well the smoother recovers the
precipitation multiplier and the snow water equivalent from those data alone.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pipelines.snow_model.ensemble import weighted_quantiles

from .assimilation import Weights, cost, pbs_weights, predicted_fractions, reliability
from .contract import ClassDomain, EnsembleRun
from .observations import Observations

B0_TOLERANCE = 0.10
SWE_COVERAGE_TARGET = 0.70
MIN_SWE_MM = 0.1


def synthetic_observations(real: Observations, truth: np.ndarray, seed: int) -> Observations:
    """The real observation pattern filled with the truth fractions (C, K) plus noise at sigma_o, kept in [0, 1]."""
    rng = np.random.default_rng(seed)
    noisy = np.clip(truth + np.nan_to_num(real.sigma) * rng.standard_normal(truth.shape), 0.0, 1.0)
    return Observations(real.days, np.where(real.usable, noisy, np.nan), real.n_cells, real.sigma, real.shadow_cells)


@dataclass(frozen=True)
class TwinResult:
    truth_b0: float
    truth_dT: float
    post_b0_mean: float
    post_b0_median: float
    post_b0_p10: float
    post_b0_p90: float
    post_dT_mean: float
    post_dT_sd: float
    prior_b0_sd: float
    post_b0_sd: float
    ess: float
    strength: float
    swe_coverage: float  # 80 % interval holds the truth, cells x days where any snow, share
    swe_coverage_all: float  # same over every class and day, dry ones included
    swe_rmse_mm: float
    prior_swe_rmse_mm: float
    fsca_coverage80: float

    @property
    def b0_error(self) -> float:
        return abs(self.post_b0_mean - self.truth_b0) / self.truth_b0


def swe_coverage(
    prior: EnsembleRun, weights: np.ndarray, truth_swe: np.ndarray, domain: ClassDomain
) -> tuple[float, float, float, float]:
    """Coverage of the truth SWE (C, T) by the weighted p10 to p90, weighted by cells, and SWE errors in mm."""
    swe = prior.swe.reshape(prior.swe.shape[0], -1)
    p10, p50, p90 = weighted_quantiles(swe, weights, [0.1, 0.5, 0.9]).reshape(3, *truth_swe.shape)
    inside = (truth_swe >= p10 - 1e-3) & (truth_swe <= p90 + 1e-3)
    area = np.broadcast_to(domain.cell_count[:, None].astype("float64"), truth_swe.shape)
    snowy = (truth_swe > MIN_SWE_MM) | (p90 > MIN_SWE_MM)
    equal = np.full(weights.size, 1.0 / weights.size)
    prior_median = weighted_quantiles(swe, equal, [0.5])[0].reshape(truth_swe.shape)
    rmse = float(np.sqrt(np.average((p50 - truth_swe) ** 2, weights=area)))
    prior_rmse = float(np.sqrt(np.average((prior_median - truth_swe) ** 2, weights=area)))
    return (
        float(np.average(inside[snowy], weights=area[snowy])),
        float(np.average(inside, weights=area)),
        rmse,
        prior_rmse,
    )


def run_twin(
    prior: EnsembleRun,
    truth: EnsembleRun,
    truth_member: int,
    real: Observations,
    forcing_days: list,
    domain: ClassDomain,
    n_corr: float,
    seed: int,
    target: float | None = None,
) -> TwinResult:
    columns = {int(day): position for position, day in enumerate(truth.day_index)}
    obs_columns = [columns[int(i)] for i in real.day_index(forcing_days)]
    truth_fsca = truth.f_sca[truth_member][:, obs_columns]
    observations = synthetic_observations(real, truth_fsca, seed)
    predicted = predicted_fractions(prior, observations, forcing_days)
    weights: Weights = pbs_weights(cost(predicted, observations, n_corr), target)
    w = weights.weights
    b0 = prior.parameters.b0
    p10, p50, p90 = weighted_quantiles(b0, w, [0.1, 0.5, 0.9])
    mean_b0 = float(np.sum(w * b0))
    dT = prior.parameters.dT
    mean_dT = float(np.sum(w * dT))
    covered, covered_all, rmse, prior_rmse = swe_coverage(prior, w, truth.swe[truth_member], domain)
    return TwinResult(
        truth_b0=float(truth.parameters.b0[truth_member]),
        truth_dT=float(truth.parameters.dT[truth_member]),
        post_b0_mean=mean_b0,
        post_b0_median=float(p50),
        post_b0_p10=float(p10),
        post_b0_p90=float(p90),
        post_dT_mean=mean_dT,
        post_dT_sd=float(np.sqrt(np.sum(w * (dT - mean_dT) ** 2))),
        prior_b0_sd=float(b0.std()),
        post_b0_sd=float(np.sqrt(np.sum(w * (b0 - mean_b0) ** 2))),
        ess=weights.ess,
        strength=weights.strength,
        swe_coverage=covered,
        swe_coverage_all=covered_all,
        swe_rmse_mm=rmse,
        prior_swe_rmse_mm=prior_rmse,
        fsca_coverage80=reliability(predicted, observations, w, seed)["coverage80"],
    )
