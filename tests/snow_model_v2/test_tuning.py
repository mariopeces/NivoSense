import json

import numpy as np
import pytest

from pipelines.snow_model_v2 import tuning as t
from pipelines.snow_model_v2.contract import Priors, sample_parameters


def test_identical_candidate_gives_equal_weights_and_matches_the_target_density():
    base = Priors(b0_median=1.0, b0_cv=0.4, dT_sd=1.5)
    params = sample_parameters(2000, 2025, base, storm_count=0)
    same = t.importance_weights(base, t.Candidate(1.0, 0.4, 1.5), params.b0, params.dT)
    assert np.allclose(same, 1 / 2000)
    shifted = t.importance_weights(base, t.Candidate(1.6, 0.4, 1.5), params.b0, params.dT)
    assert np.sum(shifted * params.b0) > 1.3 and 1 / np.sum(shifted**2) > 100


def test_weights_follow_the_default_prior_bounds():
    params = sample_parameters(2000, 2025, t.BASE_PRIORS, storm_count=0)
    weights = t.importance_weights(t.BASE_PRIORS, t.Candidate(1.0, 0.4, 1.5), params.b0, params.dT)
    outside = (params.b0 < 0.3) | (params.b0 > 3.0)
    assert outside.any() and weights[outside].sum() == 0.0


def test_best_candidate_and_leave_one_out_folds():
    cands = t.candidates()
    good, other = cands[0], cands[1]
    table = {c: {2023: 0.2, 2024: 0.2, 2025: 0.2} for c in cands}
    table[good] = {2023: 0.05, 2024: 0.06, 2025: 0.9}
    table[other] = {2023: 0.3, 2024: 0.3, 2025: 0.01}
    assert t.best_candidate(table, [2023, 2024])[0] == good
    folds = t.leave_one_season_out(table, [2023, 2024, 2025])
    assert [f["held_out"] for f in folds] == [2023, 2024, 2025]
    assert folds[2]["tuned"]["b0_median"] == good.b0_median
    spread = t.fold_spread(folds)
    assert set(spread) == {"b0_median", "b0_cv", "dT_sd"} and spread["b0_median"]["min"] <= spread["b0_median"]["max"]


def test_thin_candidates_are_skipped_and_priors_load(tmp_path):
    cands = t.candidates()
    table = {c: {2024: None} for c in cands}
    table[cands[5]] = {2024: 0.4}
    assert t.best_candidate(table, [2024])[0] == cands[5]
    with pytest.raises(ValueError):
        t.best_candidate({cands[0]: {2024: None}}, [2024])
    path = tmp_path / "priors.json"
    path.write_text(json.dumps({"priors": {"b0_median": 1.25, "dT_sd": 2.0}}), encoding="utf-8")
    loaded = t.load_priors(str(path))
    assert loaded.b0_median == 1.25 and loaded.dT_sd == 2.0 and loaded.b0_cv == Priors().b0_cv


def test_committed_priors_file_loads_and_lists_every_fold():
    payload = json.loads(open("regions/sierra-nevada.snow-priors.json", encoding="utf-8").read())
    assert len(payload["folds"]) == len(payload["water_years"]) >= 5
    assert set(payload["fold_spread"]) == {"b0_median", "b0_cv", "dT_sd"}
    priors = t.load_priors("regions/sierra-nevada.snow-priors.json")
    assert priors.b0_median == payload["priors"]["b0_median"]
