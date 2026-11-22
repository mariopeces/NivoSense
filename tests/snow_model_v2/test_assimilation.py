from datetime import date, timedelta

import numpy as np
import pytest

from pipelines.snow_model.ensemble import effective_size
from pipelines.snow_model_v2 import assimilation as a
from pipelines.snow_model_v2.contract import Priors, sample_parameters
from pipelines.snow_model_v2.observations import Observations, observation_error

DAYS = [date(2025, 1, 1) + timedelta(days=i) for i in range(10)]


def observations(fraction: np.ndarray, n_cells: float = 25.0) -> Observations:
    n = np.full(fraction.shape, n_cells)
    sigma = np.where(np.isfinite(fraction), observation_error(n), np.nan)
    return Observations(DAYS[: fraction.shape[1]], fraction, n, sigma, np.zeros(fraction.shape))


def test_cost_counts_only_usable_data_and_divides_by_n_corr():
    y = np.array([[0.5, np.nan], [0.2, 0.9]])
    obs = observations(y)
    predicted = np.zeros((2, 2, 2))
    predicted[1] = [[0.5, 0.1], [0.2, 0.9]]  # member 1 is exact on every usable datum
    j = a.cost(predicted, obs, n_corr=1.0)
    assert j[1] == pytest.approx(0.0)
    sigma = obs.sigma
    expected = 0.5 * ((0.5 / sigma[0, 0]) ** 2 + (0.2 / sigma[1, 0]) ** 2 + (0.9 / sigma[1, 1]) ** 2)
    assert j[0] == pytest.approx(expected)
    assert a.cost(predicted, obs, n_corr=3.0)[0] == pytest.approx(expected / 3)


def test_weights_reach_target_ess_and_keep_the_natural_posterior_when_flat():
    rng = np.random.default_rng(1)
    sharp = a.pbs_weights(rng.uniform(0, 4000, 1000))
    assert sharp.ess == pytest.approx(30.0, rel=0.02) and sharp.strength < 1.0 and not sharp.degenerate
    assert sharp.weights.sum() == pytest.approx(1.0)
    flat = a.pbs_weights(rng.uniform(0, 3, 1000))
    assert flat.strength == 1.0 and flat.ess > 30
    reconstructed = np.exp(-sharp.strength * (sharp.cost - sharp.cost.min()))
    assert np.allclose(reconstructed / reconstructed.sum(), sharp.weights, rtol=1e-3, atol=1e-9)


def test_target_ess_scale():
    assert a.target_ess(1000) == 30.0 and a.target_ess(48) == 10.0 and a.target_ess(5) == 5.0


def test_resampling_and_top_members():
    weights = np.array([0.0, 0.5, 0.0, 0.25, 0.25])
    indices = a.systematic_resample(weights, 100, seed=3)
    assert set(indices) == {1, 3, 4} and (indices == 1).sum() == 50
    chosen, kept = a.top_members(weights, 2)
    assert chosen.tolist() == [1, 3] or chosen.tolist() == [1, 4]
    assert kept.sum() == pytest.approx(1.0)


def test_posterior_table_moves_with_weights():
    params = sample_parameters(500, 2025, storm_count=3)
    weights = np.exp(-50 * (params.b0 - 1.5) ** 2)
    weights /= weights.sum()
    table = a.posterior_table(params, weights)
    assert table["b0"]["post_mean"] == pytest.approx(1.5, abs=0.05)
    assert table["b0"]["post_p95"] - table["b0"]["post_p5"] < table["b0"]["prior_p95"] - table["b0"]["prior_p5"]
    assert table["DDF"]["prior_mean"] == pytest.approx(2.25, abs=0.05)
    assert "b0" in a.format_table(table)


def test_reliability_of_a_calibrated_ensemble():
    rng = np.random.default_rng(0)
    members, data = 400, 3000
    truth = rng.uniform(0.2, 0.8, data)
    sigma = np.full(data, 0.1)
    observed = (truth + sigma * rng.standard_normal(data))[None, :]
    predicted = (truth[None] + np.zeros((members, data)))[:, None, :]
    obs = Observations(
        DAYS[:1] * 1, observed.reshape(1, -1), np.full((1, data), 25.0), sigma[None], np.zeros((1, data))
    )
    out = a.reliability(predicted.reshape(members, 1, data), obs, np.full(members, 1 / members))
    assert out["coverage80"] == pytest.approx(0.8, abs=0.03)


def test_gaussian_transform_round_trip_and_bounds():
    priors = Priors()
    params = sample_parameters(200, 2025, priors, storm_count=4)
    z = a.to_gaussian(params, priors)
    assert z.shape == (200, 12)
    assert np.allclose(z[:, 2:3].std(), 1.0, atol=0.15)
    back = a.from_gaussian(z, params, priors)
    for name in a.SCALAR_PARAMETERS:
        assert np.allclose(getattr(back, name), getattr(params, name), rtol=1e-5, atol=1e-5), name
    assert np.allclose(back.xi, params.xi)
    wild = a.from_gaussian(np.full((2, 12), 9.0), params.take(slice(0, 2)), priors)
    assert wild.b0.max() <= priors.b0_bounds[1] + 1e-9 and wild.DDF.max() <= priors.DDF[1] + 1e-9


def toy_problem(members=300, data=40, seed=5):
    """A linear forward model of two parameters in Gaussian space, observed with noise."""
    rng = np.random.default_rng(seed)
    priors = Priors()
    prior = sample_parameters(members, 2025, priors, storm_count=0)
    loading = rng.normal(size=(data, 8))
    loading[:, 3:] = 0.0  # only b0, g and dT are observable

    def forward(params):
        z = a.to_gaussian(params, priors)
        return (0.5 + 0.1 * z @ loading.T)[:, None, :]

    truth = a.to_gaussian(sample_parameters(1, 99, priors, storm_count=0), priors)
    clean = 0.5 + 0.1 * truth @ loading.T
    noise = 0.02
    y = (clean + noise * rng.standard_normal(data))[None]
    obs = Observations(
        DAYS[:1], y.reshape(1, -1), np.full((1, data), 25.0), np.full((1, data), noise), np.zeros((1, data))
    )
    return priors, prior, forward, obs, truth


def test_es_mda_pulls_observable_parameters_to_the_truth_and_is_deterministic():
    priors, prior, forward, obs, truth = toy_problem()
    post, predicted = a.es_mda(prior, forward, obs, priors, n_corr=1.0, seed=7)
    z_prior, z_post = a.to_gaussian(prior, priors), a.to_gaussian(post, priors)
    error_prior = np.abs(z_prior.mean(axis=0)[:3] - truth[0, :3])
    error_post = np.abs(z_post.mean(axis=0)[:3] - truth[0, :3])
    assert (error_post < error_prior + 1e-9).all() and error_post.max() < 0.4
    assert z_post[:, :3].std(axis=0).max() < 0.5 * z_prior[:, :3].std(axis=0).min()
    assert np.allclose(z_post[:, 5:].std(axis=0), z_prior[:, 5:].std(axis=0), rtol=0.5)  # unobservable stay broad
    again, _ = a.es_mda(prior, forward, obs, priors, n_corr=1.0, seed=7)
    assert np.array_equal(again.b0, post.b0) and predicted.shape == (300, 1, 40)


def test_inverse_inflation_factors_sum_to_one():
    assert sum(1.0 / a.ES_MDA_ITERATIONS for _ in range(a.ES_MDA_ITERATIONS)) == pytest.approx(1.0)
    assert effective_size(np.full(10, 0.1)) == pytest.approx(10.0)


def test_crps_matches_the_pairwise_definition():
    rng = np.random.default_rng(2)
    members, data = 40, 7
    x = rng.uniform(0, 1, (members, 1, data))
    w = rng.uniform(0.1, 1, members)
    w /= w.sum()
    y = rng.uniform(0, 1, (1, data))
    obs = Observations(DAYS[:1], y, np.full((1, data), 25.0), np.full((1, data), 0.1), np.zeros((1, data)))
    direct = np.mean(
        [
            (w * np.abs(x[:, 0, d] - y[0, d])).sum()
            - 0.5 * (w[:, None] * w[None, :] * np.abs(x[:, 0, d][:, None] - x[:, 0, d][None, :])).sum()
            for d in range(data)
        ]
    )
    assert a.crps(x, obs, w) == pytest.approx(direct)
    assert a.crps(np.broadcast_to(y[None], (members, 1, data)).copy(), obs, w) == pytest.approx(0.0, abs=1e-12)


def test_block_holdout_holds_whole_blocks_and_about_a_third():
    from pipelines.snow_model_v2.holdout import block_mask, split

    start = DAYS[0]
    days = [start + timedelta(days=d) for d in range(0, 120, 5)]
    held = block_mask(days, start)
    assert 0.25 < held.mean() < 0.45
    runs = np.flatnonzero(np.diff(held.astype(int)))
    assert len(runs) >= 4  # separate blocks, not scattered dates
    fraction = np.zeros((2, len(days)))
    obs = Observations(days, fraction, fraction + 25, fraction + 0.1, fraction)
    train, test = split(obs, start)
    assert len(train.days) + len(test.days) == len(days) and not set(train.days) & set(test.days)
