import numpy as np
import pytest

from pipelines.snow_model_v2 import assimilation as a
from pipelines.snow_model_v2.contract import sample_parameters
from pipelines.snow_model_v2.engine import run_ensemble
from pipelines.snow_model_v2.observations import Observations, observation_error
from pipelines.snow_model_v2.twin import run_twin, score_twin, synthetic_observations, truth_observations

from .test_domain_engine import build_domains

OBS_DAYS = list(range(5, 30, 3))


def setup(members=300):
    forcing, _, domain = build_domains()
    storms = forcing.storm_count
    prior = run_ensemble(domain, forcing, sample_parameters(members, 2025, storm_count=storms), OBS_DAYS, workers=4)
    truth = run_ensemble(domain, forcing, sample_parameters(4, 777, storm_count=storms), OBS_DAYS, workers=1)
    shape = (domain.class_count, len(OBS_DAYS))
    n = np.broadcast_to(domain.cell_count[:, None].astype("float64"), shape).copy()
    real = Observations([forcing.days[i] for i in OBS_DAYS], np.zeros(shape), n, observation_error(n), np.zeros(shape))
    return forcing, domain, prior, truth, real


def test_synthetic_observations_keep_the_real_gaps_and_noise_level():
    n = np.full((200, 3), 25.0)
    sigma = observation_error(n)
    fraction = np.full((200, 3), 0.5)
    fraction[:50, 2] = np.nan
    real = Observations([], fraction, n, np.where(np.isfinite(fraction), sigma, np.nan), np.zeros((200, 3)))
    synthetic = synthetic_observations(real, np.full((200, 3), 0.5), seed=1)
    assert np.array_equal(np.isnan(synthetic.fraction), np.isnan(fraction))
    assert np.nanstd(synthetic.fraction) == pytest.approx(observation_error(np.array([25.0]))[0], rel=0.15)
    assert np.nanmin(synthetic.fraction) >= 0.0 and np.nanmax(synthetic.fraction) <= 1.0


def test_pbs_twin_is_deterministic_and_beats_the_prior_on_swe():
    forcing, domain, prior, truth, real = setup()
    assert truth.f_sca[0].max() > 0.3  # the test season has snow to observe
    results = [run_twin(prior, truth, i, real, forcing.days, domain, 3.0, seed=5 + i) for i in range(4)]
    again = run_twin(prior, truth, 0, real, forcing.days, domain, 3.0, seed=5)
    assert again == results[0]
    assert all(r.ess == pytest.approx(a.target_ess(300), rel=0.05) or r.strength == 1.0 for r in results)
    assert sum(r.swe_rmse_mm < r.prior_swe_rmse_mm for r in results) >= 3
    assert sum(r.post_b0_sd < r.prior_b0_sd for r in results) >= 3


def test_es_mda_twin_runs_end_to_end_and_tightens_the_ensemble():
    forcing, domain, prior, truth, real = setup(members=120)
    observations = truth_observations(truth, 1, real, forcing.days, seed=11)

    def forward(parameters):
        return a.predicted_fractions(
            run_ensemble(domain, forcing, parameters, OBS_DAYS, workers=4), observations, forcing.days
        )

    posterior, predicted = a.es_mda(prior.parameters, forward, observations, seed=2)
    final = run_ensemble(domain, forcing, posterior, OBS_DAYS, workers=4)
    equal = np.full(120, 1 / 120)
    result = score_twin(final, equal, predicted, prior, truth, 1, observations, domain, 3, 120.0, 1.0)
    before = a.cost(a.predicted_fractions(prior, observations, forcing.days), observations, 3.0)
    after = a.cost(predicted, observations, 3.0)
    assert np.median(after) < np.median(before)
    assert result.post_b0_sd < result.prior_b0_sd
