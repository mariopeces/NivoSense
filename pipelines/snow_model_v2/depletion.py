"""Sub-grid snow depletion curve for a cell with lognormal local peak SWE and homogeneous melt.

Formulation (closed forms of Donald et al. 1995 as written in Essery and Pomeroy 2004, Annals of Glaciology 38,
261-265, https://doi.org/10.3189/172756404781815275, equations 5 to 11): local SWE X at the start of a melt
episode is lognormal with mean S0 (`s_peak`) and coefficient of variation beta, and every point loses the same
melt M (`m_cum`). Then

    covered fraction   f(M)  = P(X > M)           = 1/2 erfc((ln M - mu) / (sigma sqrt 2))
    cell-mean SWE      S(M)  = E[(X - M)+]        = S0 * 1/2 erfc((ln M - mu - sigma^2) / (sigma sqrt 2)) - M f(M)

with sigma^2 = ln(1 + beta^2) and mu = ln S0 - sigma^2 / 2.

The cell mean loses S(M_old) - S(M_new) when the point melt grows from M_old to M_new, so a partly bare cell
melts less than the potential melt. Snowfall of at least `NEW_SNOW_MM` (or any snowfall onto bare ground) starts
a new episode; smaller snowfall is added to the mean and to S0 and melts first with the left-over potential melt.
"""

from __future__ import annotations

import numpy as np

NEW_SNOW_MM = 5.0
MIN_BETA = 1e-3
EPSILON_MM = 1e-4


def erfc(x: np.ndarray) -> np.ndarray:
    """Complementary error function, fractional error below 1.2e-7 (Numerical Recipes erfcc)."""
    z = np.abs(x)
    t = 1.0 / (1.0 + 0.5 * z)
    poly = -1.26551223 + t * (
        1.00002368
        + t
        * (
            0.37409196
            + t
            * (
                0.09678418
                + t
                * (
                    -0.18628806
                    + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277))))
                )
            )
        )
    )
    answer = t * np.exp(-z * z + poly)
    return np.where(x >= 0, answer, 2.0 - answer)


def _sigma(beta: np.ndarray) -> np.ndarray:
    return np.sqrt(np.log1p(np.maximum(beta, MIN_BETA) ** 2))


def covered_fraction(s_peak: np.ndarray, m_cum: np.ndarray, beta: np.ndarray) -> np.ndarray:
    """Snow covered fraction f(M); 1 before any melt and 0 where there was no snow to melt."""
    sigma = _sigma(beta)
    peak = np.maximum(s_peak, EPSILON_MM)
    melt = np.maximum(m_cum, EPSILON_MM * 1e-3)
    mu = np.log(peak) - sigma**2 / 2
    f = 0.5 * erfc((np.log(melt) - mu) / (sigma * np.sqrt(2.0)))
    f = np.where(m_cum <= 0, 1.0, f)
    return np.where(s_peak <= EPSILON_MM, 0.0, np.clip(f, 0.0, 1.0)).astype(np.float32)


def mean_swe(s_peak: np.ndarray, m_cum: np.ndarray, beta: np.ndarray) -> np.ndarray:
    """Cell-mean SWE S(M) left from `s_peak` after the point melt `m_cum`."""
    sigma = _sigma(beta)
    peak = np.maximum(s_peak, EPSILON_MM)
    melt = np.maximum(m_cum, EPSILON_MM * 1e-3)
    mu = np.log(peak) - sigma**2 / 2
    root = sigma * np.sqrt(2.0)
    lm = np.log(melt) - mu
    f = 0.5 * erfc(lm / root)
    s = peak * 0.5 * erfc((lm - sigma**2) / root) - melt * f
    s = np.where(m_cum <= 0, s_peak, s)
    return np.clip(s, 0.0, s_peak).astype(np.float32)


def step(
    swe: np.ndarray,
    s_peak: np.ndarray,
    m_cum: np.ndarray,
    curve: np.ndarray,
    snowfall: np.ndarray,
    potential_melt: np.ndarray,
    beta: np.ndarray,
    new_snow_mm: float = NEW_SNOW_MM,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """One day: add snowfall, melt, update the depletion state.

    `curve` is the cell-mean SWE the depletion curve accounts for, `mean_swe(s_peak, m_cum, beta)`, carried as
    state so the erfc evaluations only run on melting cells. All arrays share one shape (beta may broadcast).
    Returns swe, s_peak, m_cum, curve and the melt (mm) removed from the cell mean, with
    swe_new = swe + snowfall - melt exactly and 0 <= melt <= swe + snowfall.
    """
    beta = np.broadcast_to(beta, swe.shape)
    bare = swe <= EPSILON_MM
    total = swe + snowfall
    reset = (snowfall >= new_snow_mm) | (bare & (snowfall > 0))
    small = (snowfall > 0) & ~reset
    s_peak = np.where(reset, total, np.where(small, s_peak + snowfall, s_peak))
    m_cum = np.where(reset, 0.0, m_cum)
    curve = np.where(reset, total, curve)
    if small.any():
        curve[small] = mean_swe(s_peak[small], m_cum[small], beta[small])

    new_m = m_cum + potential_melt
    active = (potential_melt > 0) & (total > EPSILON_MM)
    melt = np.zeros_like(total)
    if active.any():
        curve_new = mean_swe(s_peak[active], new_m[active], beta[active])
        curve_melt = np.maximum(curve[active] - curve_new, 0.0)
        # Mass above what the curve accounts for came from small snowfalls and melts first, with the potential
        # melt the curve part left over.
        excess = np.maximum(total[active] - curve[active], 0.0)
        left_over = np.maximum(potential_melt[active] - curve_melt, 0.0)
        melt[active] = np.minimum(total[active], curve_melt + np.minimum(excess, left_over))
        curve[active] = curve_new
    m_cum = np.where(active, new_m, m_cum)
    swe_new = np.maximum(total - melt, 0.0)
    swe_new = np.where(swe_new <= EPSILON_MM, 0.0, swe_new)
    melt = total - swe_new
    return (
        swe_new.astype(np.float32),
        s_peak.astype(np.float32),
        m_cum.astype(np.float32),
        curve.astype(np.float32),
        melt.astype(np.float32),
    )
