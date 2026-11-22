"""Interfaces of the snow model v2 engine (docs/snow-methodology.md sections 3.3 to 3.6).

Other lanes (forcing, assimilation, daily runner) code against these types only.
Axis order everywhere: members N, then classes C, then days D.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from datetime import date
from statistics import NormalDist
from typing import Sequence

import numpy as np

DRY_STORM = -1


@dataclass(frozen=True)
class SeasonForcing:
    """Hourly forcing of one season at the forcing points, before any elevation adjustment.

    `storm_id` is one regional segmentation (a storm is a precipitation spell separated from the next by at
    least 12 dry hours): hour h of day d belongs to storm `storm_id[d, h]`, or `DRY_STORM`. Storm ids are
    0..storm_count-1 and index the columns of `MemberParameters.xi`, so all points share the storm timing and
    the noise of a storm is one multiplier for the whole region.
    """

    days: list[date]
    elevation: np.ndarray  # (P,) m, elevation of the forcing point as the weather model sees it
    temperature: np.ndarray  # (P, D, 24) C
    precipitation: np.ndarray  # (P, D, 24) mm per hour
    shortwave: np.ndarray  # (P, D) W/m2, daily mean
    storm_id: np.ndarray  # (D, 24) int32

    def __post_init__(self) -> None:
        points, day_count = self.temperature.shape[:2]
        if self.temperature.shape != (points, day_count, 24) or self.precipitation.shape != self.temperature.shape:
            raise ValueError("temperature and precipitation must be (points, days, 24)")
        if self.elevation.shape != (points,) or self.shortwave.shape != (points, day_count):
            raise ValueError("elevation must be (points,) and shortwave (points, days)")
        if len(self.days) != day_count or self.storm_id.shape != (day_count, 24):
            raise ValueError("days and storm_id must match the number of days")

    @property
    def storm_count(self) -> int:
        return int(self.storm_id.max()) + 1 if self.storm_id.size else 0


@dataclass(frozen=True)
class ClassDomain:
    """Model points: classes of 100 m cells (or the cells themselves, one class per cell).

    A class is a set of cells that share an elevation band, an aspect class and a forcing cell; the model runs
    once on its mean elevation and mean radiation index. `neighbours` and `weights` give the forcing points
    and inverse-distance weights of each class (one column for a class, four for a cell-wise domain as in v1).
    """

    class_of_cell: np.ndarray  # (cells,) int32, class id per 100 m cell, -1 for cells outside every class
    elevation: np.ndarray  # (C,) m, mean over the class cells
    aspect: np.ndarray  # (C,) int8: 0 N, 1 E, 2 S, 3 W, 4 flat
    neighbours: np.ndarray  # (C, K) int32 forcing point indices
    weights: np.ndarray  # (C, K) float32, rows sum to one
    radiation: np.ndarray  # (samples, C) radiation index (pipelines.snow_model.radiation), class mean
    cell_count: np.ndarray  # (C,) int32 number of 100 m cells in the class
    cell_area_m2: float

    @property
    def class_count(self) -> int:
        return int(self.elevation.size)

    def upsample(self, values: np.ndarray) -> np.ndarray:
        """Class values (..., C) to cell values (..., cells); cells outside every class get NaN."""
        index = self.class_of_cell
        floats = values.astype("float32") if values.dtype.kind != "f" else values
        return np.where(index >= 0, floats[..., np.maximum(index, 0)], np.nan).astype(floats.dtype)


@dataclass(frozen=True)
class Priors:
    """Prior distributions of docs/snow-methodology.md section 3.3 (uniform: low, high; normal: mean, sd)."""

    b0_median: float = 1.0
    b0_cv: float = 0.4
    b0_bounds: tuple[float, float] = (0.3, 3.0)
    g: tuple[float, float] = (0.0, 0.10)
    dT_sd: float = 1.5
    L: tuple[float, float] = (4.5, 8.0)
    Ts: tuple[float, float] = (0.0, 2.5)
    DDF: tuple[float, float] = (1.0, 3.5)
    rad: tuple[float, float] = (0.0, 0.012)
    beta: tuple[float, float] = (0.05, 0.8)
    rho_s_sd: float = 0.15
    xi_sd: float = 0.25


@dataclass(frozen=True)
class MemberParameters:
    """Parameters of N members, drawn once per water year. Every array has N rows."""

    water_year: int
    b0: np.ndarray  # (N,) season precipitation multiplier
    g: np.ndarray  # (N,) precipitation gradient per 100 m
    dT: np.ndarray  # (N,) K, additive temperature bias
    L: np.ndarray  # (N,) K/km lapse rate
    Ts: np.ndarray  # (N,) C rain/snow threshold
    DDF: np.ndarray  # (N,) mm per degree day
    rad: np.ndarray  # (N,) radiation melt factor
    beta: np.ndarray  # (N,) sub-grid CV of SWE
    rho_s: np.ndarray  # (N,) compaction scale; published depth is the compaction-curve depth divided by it
    xi: np.ndarray  # (N, S) log precipitation error per storm, independent per member and storm

    @property
    def count(self) -> int:
        return int(self.b0.size)

    def take(self, members: np.ndarray | slice) -> MemberParameters:
        """The parameters of a subset of members (indices, mask or slice)."""
        values = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "water_year"}
        return MemberParameters(self.water_year, **{name: array[members] for name, array in values.items()})


@dataclass
class EnsembleRun:
    """Model output on the stored days. `day_index` are indices into `SeasonForcing.days`.

    Always contains every observation day and the last day. swe in mm and depth in m are cell means;
    f_sca is the sub-grid snow covered fraction; s_peak and m_cum (mm) are the depletion state.
    """

    day_index: np.ndarray  # (T,) int
    swe: np.ndarray  # (N, C, T) float32
    depth: np.ndarray  # (N, C, T) float32
    f_sca: np.ndarray  # (N, C, T) float32
    s_peak: np.ndarray  # (N, C, T) float32
    m_cum: np.ndarray  # (N, C, T) float32
    parameters: MemberParameters
    seed: int
    meta: dict = field(default_factory=dict)


def season_seed(water_year: int) -> int:
    return water_year * 1000 + 17


def sample_parameters(n: int, water_year: int, priors: Priors | None = None, storm_count: int = 0) -> MemberParameters:
    """Latin hypercube draw of the priors, deterministic given (n, water_year, priors, storm_count)."""
    priors = priors or Priors()
    generator = np.random.default_rng(season_seed(water_year))
    normal = NormalDist()

    def strata() -> np.ndarray:
        return (generator.permutation(n) + generator.random(n)) / n

    def uniform(low_high: tuple[float, float]) -> np.ndarray:
        return low_high[0] + strata() * (low_high[1] - low_high[0])

    def truncated_lognormal(median: float, cv: float, bounds: tuple[float, float]) -> np.ndarray:
        sigma = math.sqrt(math.log(1 + cv**2))
        low, high = (normal.cdf(math.log(b / median) / sigma) for b in bounds)
        z = [normal.inv_cdf(low + u * (high - low)) for u in strata()]
        return median * np.exp(sigma * np.array(z))

    def gaussian(sd: float) -> np.ndarray:
        return sd * np.array([normal.inv_cdf(min(max(u, 1e-12), 1 - 1e-12)) for u in strata()])

    rho_s = np.clip(1.0 + gaussian(priors.rho_s_sd), 0.5, 1.5)
    return MemberParameters(
        water_year=water_year,
        b0=truncated_lognormal(priors.b0_median, priors.b0_cv, priors.b0_bounds),
        g=uniform(priors.g),
        dT=gaussian(priors.dT_sd),
        L=uniform(priors.L),
        Ts=uniform(priors.Ts),
        DDF=uniform(priors.DDF),
        rad=uniform(priors.rad),
        beta=uniform(priors.beta),
        rho_s=rho_s,
        xi=priors.xi_sd * generator.standard_normal((n, storm_count)),
    )


def run_ensemble(
    domain: ClassDomain,
    forcing: SeasonForcing,
    parameters: MemberParameters,
    observation_days: Sequence[int],
) -> EnsembleRun:
    """Run every member on every class from the first day of `forcing` with zero snow.

    No observation enters the run. Deterministic: the only randomness is in `parameters`.
    """
    raise NotImplementedError("implemented in pipelines/snow_model_v2/engine.py")
