"""Bayesian batch smoothers for the snow model v2 ensemble (docs/snow-methodology.md sections 3.6 and 3.7).

The observations never enter the forward run. The default is a particle batch smoother (PBS, Margulis et al.
2015; as used with fSCA in Aalstad et al. 2018, Sect. 3.3.2, Eq. 27): each prior member keeps its whole
trajectory and is weighted by the Gaussian likelihood of the observed class fractions. The fallback is the
ensemble smoother with multiple data assimilation (ES-MDA) of Aalstad et al. 2018 (Sect. 3.3.2, Eqs. 17 to 24,
open access: https://doi.org/10.5194/tc-12-247-2018), with Na = 4, alpha = Na at every iteration so that the
inverse inflation factors sum to one, and parameters updated in Gaussian space.

Two departures from Aalstad et al. 2018, both deliberate. Their priors are logit-normal and lognormal and they
anamorphose with logit and log; our priors are uniform (the probit of the normalised value is exactly standard
normal) and truncated lognormal (log of the ratio to the median). And the observation error is inflated by the
correlation correction n_corr (R = n_corr sigma_o^2), the same factor that divides the PBS cost, because pooled
classes and nearby dates are not independent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from statistics import NormalDist
from typing import Callable

import numpy as np

from pipelines.snow_model.ensemble import effective_size, tempered_weights, weighted_quantiles

from .contract import EnsembleRun, MemberParameters, Priors
from .observations import Observations

N_CORR = 3.0
MIN_ESS = 10.0
ES_MDA_ITERATIONS = 4
SCALAR_PARAMETERS = ("b0", "g", "dT", "L", "Ts", "DDF", "rad", "beta")
_NORMAL = NormalDist()
_PHI = np.vectorize(_NORMAL.cdf, otypes=[float])
_PROBIT = np.vectorize(_NORMAL.inv_cdf, otypes=[float])


def target_ess(members: int) -> float:
    """30 for 1000 members, never below the ES-MDA switch level."""
    return float(min(members, max(MIN_ESS, 0.03 * members)))


def predicted_fractions(run: EnsembleRun, observations: Observations, forcing_days: list[date]) -> np.ndarray:
    """Model snow covered fraction of every class on the observation dates: (N, C, K)."""
    stored = {int(day): position for position, day in enumerate(run.day_index)}
    columns = [stored[int(index)] for index in observations.day_index(forcing_days)]
    return run.f_sca[:, :, columns]


def cost(predicted: np.ndarray, observations: Observations, n_corr: float = N_CORR) -> np.ndarray:
    """J_m = 0.5 sum_{c,k} ((y - x_m) / sigma_o)^2 / n_corr over the usable classes and dates, (N,)."""
    z = (observations.fraction[None] - predicted) / observations.sigma[None]
    return 0.5 * (np.where(observations.usable[None], z, 0.0) ** 2).sum(axis=(1, 2)) / n_corr


@dataclass(frozen=True)
class Weights:
    weights: np.ndarray  # (N,) sum to one
    cost: np.ndarray  # (N,)
    strength: float  # lambda of exp(-lambda J); 1 is the untempered posterior
    ess: float

    @property
    def degenerate(self) -> bool:
        return self.ess < MIN_ESS


def pbs_weights(cost_values: np.ndarray, target: float | None = None) -> Weights:
    """Weights proportional to exp(-lambda J). Untempered (lambda = 1) when that already keeps the target
    effective size, else `tempered_weights` lowers lambda until it does."""
    target = target_ess(cost_values.size) if target is None else target
    shifted = cost_values - cost_values.min()
    natural = np.exp(-shifted)
    natural /= natural.sum()
    if effective_size(natural) >= target:
        return Weights(natural, cost_values, 1.0, effective_size(natural))
    weights = tempered_weights(cost_values, target)
    probe = int(np.argmax(shifted))
    strength = float(np.log(weights.max() / weights[probe]) / shifted[probe]) if shifted[probe] > 0 else 0.0
    return Weights(weights, cost_values, strength, effective_size(weights))


def systematic_resample(weights: np.ndarray, count: int, seed: int = 0) -> np.ndarray:
    """Indices of `count` members drawn with probability `weights` (low-variance systematic resampling)."""
    start = np.random.default_rng(seed).random() / count
    positions = start + np.arange(count) / count
    return np.minimum(np.searchsorted(np.cumsum(weights), positions), weights.size - 1)


def top_members(weights: np.ndarray, count: int) -> tuple[np.ndarray, np.ndarray]:
    """The `count` heaviest members and their renormalised weights, for the 100 m grid run."""
    chosen = np.sort(np.argsort(-weights)[:count])
    kept = weights[chosen]
    return chosen, kept / kept.sum()


def posterior_table(
    parameters: MemberParameters, weights: np.ndarray, prior: MemberParameters | None = None
) -> dict[str, dict[str, float]]:
    """Prior and posterior mean and 5 / 95 percent of every scalar parameter.

    `prior` is the ensemble before the update (ES-MDA changes the parameters); by default it is `parameters`
    with equal weights, which is the PBS case.
    """
    prior = prior or parameters
    uniform = np.full(prior.count, 1.0 / prior.count)
    table: dict[str, dict[str, float]] = {}
    for name in (*SCALAR_PARAMETERS, "rho_s"):
        row = {}
        for label, source, w in (("prior", prior, uniform), ("post", parameters, weights)):
            values = getattr(source, name)
            p5, p95 = weighted_quantiles(values, w, [0.05, 0.95])
            row[f"{label}_mean"] = float(np.sum(w * values))
            row[f"{label}_p5"] = float(p5)
            row[f"{label}_p95"] = float(p95)
        table[name] = row
    return table


def format_table(table: dict[str, dict[str, float]]) -> str:
    lines = ["param   prior mean (p5, p95)        posterior mean (p5, p95)"]
    for name, r in table.items():
        lines.append(
            f"{name:<7} {r['prior_mean']:7.3f} ({r['prior_p5']:6.3f}, {r['prior_p95']:6.3f})    "
            f"{r['post_mean']:7.3f} ({r['post_p5']:6.3f}, {r['post_p95']:6.3f})"
        )
    return "\n".join(lines)


def reliability(
    predicted: np.ndarray, observations: Observations, weights: np.ndarray, seed: int = 0
) -> dict[str, float]:
    """Rank and coverage of the observed fractions in the weighted predicted ensemble.

    The predicted fractions get the observation error added (one Gaussian draw per member and datum), so the
    ranks are those of an observation, not of the model state. A reliable ensemble has uniform ranks and an
    80 % interval holding 80 % of the data.
    """
    usable = observations.usable
    rng = np.random.default_rng(seed)
    x = predicted[:, usable]
    y, sigma = observations.fraction[usable], observations.sigma[usable]
    noisy = x + sigma[None] * rng.standard_normal(x.shape)
    rank = (weights[:, None] * (noisy < y[None])).sum(axis=0)
    state_rank = (weights[:, None] * (x < y[None])).sum(axis=0)
    mean = (weights[:, None] * x).sum(axis=0)
    return {
        "data": float(y.size),
        "coverage80": float(np.mean((rank >= 0.1) & (rank <= 0.9))),
        "coverage80_state": float(np.mean((state_rank >= 0.1) & (state_rank <= 0.9))),
        "rmse": float(np.sqrt(np.mean((mean - y) ** 2))),
        "bias": float(np.mean(mean - y)),
        "mean_rank": float(rank.mean()),
    }


def crps(predicted: np.ndarray, observations: Observations, weights: np.ndarray) -> float:
    """Mean continuous ranked probability score of the weighted ensemble against the usable observed fractions.

    Uses CRPS = E|X - y| - 0.5 E|X - X'| with the pair term from the sorted ensemble, so the cost is N log N
    per datum, not N^2.
    """
    usable = observations.usable
    x = predicted[:, usable].astype("float64")
    y = observations.fraction[usable]
    order = np.argsort(x, axis=0)
    sorted_x = np.take_along_axis(x, order, axis=0)
    w = weights[order]
    upper = np.cumsum(w, axis=0)
    pair = 2.0 * (w * sorted_x * (upper + (upper - w) - 1.0)).sum(axis=0)
    return float(np.mean((weights[:, None] * np.abs(x - y[None])).sum(axis=0) - 0.5 * pair))


def _clip_unit(u: np.ndarray) -> np.ndarray:
    return np.clip(u, 1e-6, 1 - 1e-6)


def _b0_sigma(priors: Priors) -> float:
    return math.sqrt(math.log(1 + priors.b0_cv**2))


def to_gaussian(parameters: MemberParameters, priors: Priors) -> np.ndarray:
    """Standard-normal coordinates of the updatable parameters, (N, 8 + storms)."""

    def probit(values: np.ndarray, bounds: tuple[float, float]) -> np.ndarray:
        return _PROBIT(_clip_unit((values - bounds[0]) / (bounds[1] - bounds[0])))

    return np.column_stack(
        [
            np.log(parameters.b0 / priors.b0_median) / _b0_sigma(priors),
            probit(parameters.g, priors.g),
            parameters.dT / priors.dT_sd,
            probit(parameters.L, priors.L),
            probit(parameters.Ts, priors.Ts),
            probit(parameters.DDF, priors.DDF),
            probit(parameters.rad, priors.rad),
            probit(parameters.beta, priors.beta),
            parameters.xi / priors.xi_sd,
        ]
    )


def from_gaussian(z: np.ndarray, template: MemberParameters, priors: Priors) -> MemberParameters:
    sigma = _b0_sigma(priors)
    low, high = (math.log(b / priors.b0_median) / sigma for b in priors.b0_bounds)

    def uniform(column: int, bounds: tuple[float, float]) -> np.ndarray:
        return bounds[0] + _PHI(z[:, column]) * (bounds[1] - bounds[0])

    return MemberParameters(
        water_year=template.water_year,
        b0=priors.b0_median * np.exp(sigma * np.clip(z[:, 0], low, high)),
        g=uniform(1, priors.g),
        dT=z[:, 2] * priors.dT_sd,
        L=uniform(3, priors.L),
        Ts=uniform(4, priors.Ts),
        DDF=uniform(5, priors.DDF),
        rad=uniform(6, priors.rad),
        beta=uniform(7, priors.beta),
        rho_s=template.rho_s,
        xi=z[:, 8:] * priors.xi_sd,
    )


def es_mda_update(
    z: np.ndarray,
    predicted: np.ndarray,
    observations: Observations,
    alpha: float,
    n_corr: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """One ES-MDA step (Aalstad et al. 2018, Eqs. 19 and 21) in ensemble space.

    The gain is applied through the Woodbury identity, so only an (N, N) matrix is inverted whatever the
    number of data.
    """
    usable = observations.usable
    y = observations.fraction[usable]
    variance = n_corr * observations.sigma[usable] ** 2
    members = z.shape[0]
    data = predicted[:, usable].astype("float64")
    perturbed = y[None] + math.sqrt(alpha) * np.sqrt(variance)[None] * rng.standard_normal(data.shape)
    inverse_r = 1.0 / (alpha * variance)
    data_anomaly = data - data.mean(axis=0)
    z_anomaly = z - z.mean(axis=0)
    inner = (members - 1) * np.eye(members) + (data_anomaly * inverse_r) @ data_anomaly.T
    residual = (perturbed - data) * inverse_r
    solved = residual - (residual @ data_anomaly.T) @ np.linalg.solve(inner, data_anomaly * inverse_r)
    return z + ((solved @ data_anomaly.T) @ z_anomaly) / (members - 1)


def es_mda(
    prior: MemberParameters,
    forward: Callable[[MemberParameters], np.ndarray],
    observations: Observations,
    priors: Priors | None = None,
    n_corr: float = N_CORR,
    iterations: int = ES_MDA_ITERATIONS,
    seed: int = 0,
) -> tuple[MemberParameters, np.ndarray]:
    """ES-MDA with alpha = `iterations` at every step. `forward` maps parameters to predicted fractions (N, C, K);
    returns the updated parameters and the predicted fractions of the final ensemble."""
    priors = priors or Priors()
    rng = np.random.default_rng(seed)
    z = to_gaussian(prior, priors)
    predicted = forward(prior)
    parameters = prior
    for _ in range(iterations):
        z = es_mda_update(z, predicted, observations, float(iterations), n_corr, rng)
        parameters = from_gaussian(z, prior, priors)
        predicted = forward(parameters)
    return parameters, predicted
