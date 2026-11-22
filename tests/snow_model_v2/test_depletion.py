import math

import numpy as np

from pipelines.snow_model_v2 import depletion as dep


def test_erfc_matches_math():
    x = np.linspace(-4, 4, 161)
    expected = np.array([math.erfc(v) for v in x])
    assert np.allclose(dep.erfc(x), expected, rtol=2e-7, atol=1e-12)


def test_closed_form_matches_monte_carlo_of_the_lognormal():
    rng = np.random.default_rng(1)
    s0, beta = 300.0, 0.4
    sigma = math.sqrt(math.log(1 + beta**2))
    local = np.exp(math.log(s0) - sigma**2 / 2 + sigma * rng.standard_normal(2_000_000))
    assert abs(local.mean() - s0) / s0 < 0.01
    for melt in (50.0, 150.0, 300.0, 500.0):
        f = dep.covered_fraction(np.float64(s0), np.float64(melt), np.float64(beta))
        mean = dep.mean_swe(np.float64(s0), np.float64(melt), np.float64(beta))
        assert abs(float(f) - (local > melt).mean()) < 0.005
        assert abs(float(mean) - np.maximum(local - melt, 0).mean()) < 1.0


def test_fraction_is_one_before_melt_zero_without_snow_and_monotone_in_melt():
    beta = np.full(50, 0.3)
    peak = np.full(50, 200.0)
    melt = np.linspace(0, 600, 50)
    f = dep.covered_fraction(peak, melt, beta)
    assert f[0] == 1.0
    assert np.all(np.diff(f) <= 1e-6) and f.min() >= 0 and f.max() <= 1
    assert dep.covered_fraction(np.array([0.0]), np.array([10.0]), np.array([0.3]))[0] == 0.0
    mean = dep.mean_swe(peak, melt, beta)
    assert np.all(np.diff(mean) <= 1e-4) and mean[0] == 200.0


def test_larger_beta_gives_flatter_curve():
    peak, melt = np.array([200.0]), np.array([250.0])
    low = dep.covered_fraction(peak, melt, np.array([0.1]))
    high = dep.covered_fraction(peak, melt, np.array([0.7]))
    assert high > low


def run(snowfall, potential, beta, new_snow_mm=dep.NEW_SNOW_MM):
    swe = peak = cum = curve = np.zeros(snowfall.shape[1], dtype="float32")
    series = []
    for day in range(snowfall.shape[0]):
        swe, peak, cum, curve, melt = dep.step(swe, peak, cum, curve, snowfall[day], potential[day], beta, new_snow_mm)
        series.append((swe, peak, cum, melt, dep.covered_fraction(peak, cum, beta) * (swe > 0)))
    return series


def test_mass_is_conserved_and_bounded_on_random_weather():
    rng = np.random.default_rng(2)
    days, cells = 300, 40
    snowfall = rng.gamma(0.3, 12, (days, cells)) * (rng.random((days, cells)) < 0.25)
    potential = rng.gamma(2, 3, (days, cells)) * (rng.random((days, cells)) < 0.5)
    beta = rng.uniform(0.05, 0.8, cells)
    series = run(snowfall.astype("float32"), potential.astype("float32"), beta)
    previous = np.zeros(cells)
    total_in = total_out = 0.0
    for day, (swe, _, _, melt, fsca) in enumerate(series):
        assert np.all(swe >= 0) and np.all(melt >= -1e-4)
        assert np.all(melt <= previous + snowfall[day] + 1e-3)
        assert np.all(melt <= potential[day] + 1e-3)
        assert np.allclose(swe, previous + snowfall[day] - melt, atol=2e-3)
        assert np.all((fsca >= 0) & (fsca <= 1))
        previous = swe
        total_in += snowfall[day].sum()
        total_out += melt.sum()
    assert abs(total_in - total_out - previous.sum()) < 0.5


def test_snowfall_resets_the_episode_and_small_snowfall_does_not():
    beta = np.array([0.4], dtype="float32")
    zero = np.zeros((1, 1), dtype="float32")
    snow = np.array([[100.0]], dtype="float32")
    state = dep.step(zero[0], zero[0], zero[0], zero[0], snow[0], np.array([0.0], dtype="float32"), beta)
    melt_day = np.array([60.0], dtype="float32")
    state = dep.step(state[0], state[1], state[2], state[3], np.array([0.0], dtype="float32"), melt_day, beta)
    assert dep.covered_fraction(state[1], state[2], beta)[0] < 1
    small = dep.step(
        state[0], state[1], state[2], state[3], np.array([2.0], dtype="float32"), np.array([0.0], dtype="float32"), beta
    )
    assert small[2][0] == state[2][0] and dep.covered_fraction(small[1], small[2], beta)[0] < 1
    big = dep.step(
        state[0], state[1], state[2], state[3], np.array([8.0], dtype="float32"), np.array([0.0], dtype="float32"), beta
    )
    assert big[2][0] == 0 and big[1][0] == big[0][0]
    assert dep.covered_fraction(big[1], big[2], beta)[0] == 1.0


def test_tiny_beta_is_a_plain_bucket_like_v1():
    rng = np.random.default_rng(3)
    days, cells = 200, 30
    snowfall = (rng.gamma(0.3, 15, (days, cells)) * (rng.random((days, cells)) < 0.3)).astype("float32")
    potential = (rng.gamma(2, 3, (days, cells)) * (rng.random((days, cells)) < 0.5)).astype("float32")
    series = run(snowfall, potential, np.full(cells, 1e-3, dtype="float32"))
    bucket = np.zeros(cells)
    for day, (swe, *_rest) in enumerate(series):
        bucket = bucket + snowfall[day]
        bucket = bucket - np.minimum(bucket, potential[day])
        assert np.allclose(swe, bucket, atol=0.05), day
