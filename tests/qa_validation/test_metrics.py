import math
from datetime import date

import numpy as np
import pytest

from qa.validation import metrics


def test_depth_metrics_constant_offset():
    obs = np.array([0.0, 0.2, 0.5, 1.0])
    out = metrics.depth_metrics(obs + 0.1, obs)
    assert out["bias"] == pytest.approx(0.1)
    assert out["rmse"] == pytest.approx(0.1)
    assert out["mae"] == pytest.approx(0.1)
    assert out["r"] == pytest.approx(1.0)
    # r = 1 and alpha = 1, so only beta = (0.425 + 0.1) / 0.425 costs anything
    assert out["kge"] == pytest.approx(1 - 0.1 / 0.425)


def test_depth_metrics_perfect_and_nan_handling():
    obs = np.array([0.0, 0.3, np.nan, 0.9])
    sim = np.array([0.0, 0.3, 5.0, 0.9])
    out = metrics.depth_metrics(sim, obs)
    assert out["n"] == 3 and out["rmse"] == 0 and out["kge"] == pytest.approx(1.0)


def test_kge_known_value():
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    sim = 2 * obs  # r = 1, alpha = 2, beta = 2
    assert metrics.depth_metrics(sim, obs)["kge"] == pytest.approx(1 - np.sqrt(2))


def test_depth_metrics_empty_and_shape_error():
    assert np.isnan(metrics.depth_metrics([np.nan], [1.0])["rmse"])
    with pytest.raises(ValueError):
        metrics.depth_metrics([1.0, 2.0], [1.0])


def test_confusion_known_counts():
    pred = np.array([1, 1, 1, 0, 0, 0, 0, 1], dtype=bool)
    truth = np.array([1, 1, 0, 0, 0, 1, 0, 0], dtype=bool)
    out = metrics.confusion(pred, truth)
    assert (out["tp"], out["fp"], out["fn"], out["tn"]) == (2, 2, 1, 3)
    assert out["f1"] == pytest.approx(4 / 7)
    assert out["accuracy"] == pytest.approx(5 / 8)
    assert out["mcc"] == pytest.approx((2 * 3 - 2 * 1) / np.sqrt(4 * 3 * 5 * 4))


def test_confusion_undefined_cases_are_nan():
    out = metrics.confusion(np.zeros(5, bool), np.zeros(5, bool))
    assert np.isnan(out["f1"]) and np.isnan(out["mcc"]) and out["accuracy"] == 1.0


def test_presence_by_band_splits_and_drops_small_bands():
    elevation = np.concatenate([np.full(40, 1900.0), np.full(40, 2100.0), np.full(5, 2500.0)])
    truth = np.concatenate([np.zeros(40, bool), np.ones(40, bool), np.ones(5, bool)])
    pred = truth.copy()
    pred[:10] = True  # 10 false positives in the low band
    table = metrics.presence_by_band(pred, truth, elevation)
    assert list(table["band_m"]) == [1800.0, 2000.0]
    assert table.loc[0, "fp"] == 10 and table.loc[1, "f1"] == 1.0


def dated(values, start="2020-01-01"):
    days = [date.fromordinal(date.fromisoformat(start).toordinal() + i) for i in range(len(values))]
    return days, np.array(values, dtype=float)


def test_melt_out_date_rule():
    days, depth = dated([0, 0.1, 0.5, 0.4, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    found = metrics.melt_out_date(days, depth, 0.01)
    assert found.date == date(2020, 1, 6) and found.last_snow == date(2020, 1, 5)


def test_melt_out_ignores_nan_and_uses_next_valid_sample():
    days, depth = dated([0.3, 0.2, np.nan, np.nan, 0, 0, 0, 0, 0, 0, 0, 0])
    found = metrics.melt_out_date(days, depth, 0.01)
    assert found.date == date(2020, 1, 5) and found.last_snow == date(2020, 1, 2)


def test_melt_out_none_when_still_snowy_never_snowy_or_tail_short():
    assert metrics.melt_out_date(*dated([0.2, 0.3]), 0.01) is None
    assert metrics.melt_out_date(*dated([0.0] * 10), 0.01) is None
    assert metrics.melt_out_date(*dated([0.2, 0.2, 0.0, 0.0, 0.0]), 0.01) is None


def test_melt_out_error_sign_and_nan():
    a = metrics.MeltOut(date(2020, 5, 10), date(2020, 5, 8))
    b = metrics.MeltOut(date(2020, 5, 3), date(2020, 5, 1))
    assert metrics.melt_out_error_days(a, b) == 7.0
    assert np.isnan(metrics.melt_out_error_days(None, b))


def test_crps_members_known_values():
    assert metrics.crps_members([[0.0], [1.0]], [0.0]) == pytest.approx(0.25)
    assert metrics.crps_members([[2.0], [2.0]], [5.0]) == pytest.approx(3.0)  # a point forecast gives |x - y|


def test_crps_members_matches_gaussian_formula():
    rng = np.random.default_rng(1)
    members = rng.normal(size=(2000, 1))
    # closed form for N(0, 1) at y = 0.5: y(2 Phi(y) - 1) + 2 phi(y) - 1/sqrt(pi)
    phi, big_phi = np.exp(-0.125) / np.sqrt(2 * np.pi), 0.5 * (1 + math.erf(0.5 / np.sqrt(2)))
    expected = 0.5 * (2 * big_phi - 1) + 2 * phi - 1 / np.sqrt(np.pi)
    assert metrics.crps_members(members, [0.5]) == pytest.approx(expected, abs=0.02)


def test_crps_quantiles_point_forecast_and_agreement_with_members():
    levels = np.linspace(0.01, 0.99, 99)
    assert metrics.crps_quantiles(levels, np.full((1, 99), 2.0), [5.0]) == pytest.approx(3.0, rel=0.02)
    rng = np.random.default_rng(2)
    members = rng.normal(size=(4000, 1))
    q = np.quantile(members, levels, axis=0).T
    assert metrics.crps_quantiles(levels, q, [0.5]) == pytest.approx(
        metrics.crps_members(members[:500], [0.5]), abs=0.03
    )


def test_calibrated_ensemble_has_unit_spread_skill_and_80_coverage():
    rng = np.random.default_rng(3)
    centre = rng.normal(size=4000)
    obs = centre + rng.normal(size=4000)
    members = centre + rng.normal(size=(300, 4000))
    out = metrics.ensemble_summary(members, obs)
    assert out["coverage80"] == pytest.approx(0.8, abs=0.03)
    assert out["spread_skill"] == pytest.approx(1.0, abs=0.06)


def test_overconfident_ensemble_is_detected():
    rng = np.random.default_rng(4)
    obs = rng.normal(size=3000)
    members = 0.2 * rng.normal(size=(30, 3000))
    out = metrics.ensemble_summary(members, obs)
    assert out["spread_skill"] < 0.3 and out["coverage80"] < 0.3


def test_quantile_summary_uses_p10_p50_p90():
    rng = np.random.default_rng(5)
    obs = rng.normal(size=4000)
    levels = [0.1, 0.5, 0.9]
    q = np.tile(np.quantile(obs, levels), (4000, 1))
    out = metrics.quantile_summary(levels, q, obs)
    assert out["coverage80"] == pytest.approx(0.8, abs=0.01)
    assert out["spread_skill"] == pytest.approx(1.0, abs=0.05)
    assert np.isfinite(out["crps"])
