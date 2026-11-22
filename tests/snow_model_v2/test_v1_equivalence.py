import numpy as np

from pipelines.snow_model.snowpack import Domain, Member, build_tables
from pipelines.snow_model_v2.contract import MemberParameters
from pipelines.snow_model_v2.domain import cellwise_domain
from pipelines.snow_model_v2.engine import run_ensemble

from .helpers import random_cells, real_forcing

V1 = {
    "lapse_k_per_km": 6.0,
    "precipitation_gradient_per_100m": 0.04,
    "precipitation_scale": 1.0,
    "rain_snow_threshold": 1.2,
    "melt_factor": 2.2,
    "radiation_factor": 0.006,
}


def v1_params(storms, **override):
    values = {
        "b0": 1.0,
        "g": V1["precipitation_gradient_per_100m"],
        "dT": 0.0,
        "L": V1["lapse_k_per_km"],
        "Ts": V1["rain_snow_threshold"],
        "DDF": V1["melt_factor"],
        "rad": V1["radiation_factor"],
        "beta": 1e-3,
        "rho_s": 1.0,
        **override,
    }
    arrays = {k: np.array([v], dtype="float64") for k, v in values.items()}
    return MemberParameters(2025, xi=np.zeros((1, storms)), **arrays)


def setup(count=400):
    v1, v2 = real_forcing()
    x, y, elevation, neighbours, weights = random_cells(v1, count)
    radiation = np.ones((92, count), dtype="float32")
    domain = Domain(elevation, neighbours, weights, np.zeros(count, dtype=int), 1, 1e4, radiation)
    return v1, v2, domain, cellwise_domain(elevation, neighbours, weights, radiation, 1e4)


def test_reproduces_v1_on_real_forcing():
    v1, v2, domain, class_domain = setup()
    member = Member(domain, build_tables(v1), V1)
    for day in range(len(v1.days)):
        member.step(day)
    last = len(v1.days) - 1
    run = run_ensemble(class_domain, v2, v1_params(v2.storm_count), [last])
    swe, depth = run.swe[0, :, -1], run.depth[0, :, -1]
    assert member.swe.max() > 50
    # Offset tables on a 0.5 K grid in both models; the snowfall table is indexed by (offset - Ts) here.
    assert np.abs(swe - member.swe).max() < 1.0
    assert abs(swe.sum() - member.swe.sum()) / member.swe.sum() < 0.01
    assert np.abs(depth - member.depth).max() < 0.03
    assert ((swe > 0) == (member.swe > 0)).mean() > 0.995


def test_depth_is_divided_by_rho_s_and_precipitation_scales_with_b0():
    v1, v2, _, class_domain = setup(60)
    last = len(v1.days) - 1
    base = run_ensemble(class_domain, v2, v1_params(v2.storm_count), [last])
    dense = run_ensemble(class_domain, v2, v1_params(v2.storm_count, rho_s=1.25), [last])
    assert np.allclose(dense.depth[0, :, -1], base.depth[0, :, -1] / 1.25, rtol=1e-5, atol=1e-6)
    wet = run_ensemble(class_domain, v2, v1_params(v2.storm_count, b0=1.5), [last])
    assert wet.swe[0, :, -1].sum() > 1.3 * base.swe[0, :, -1].sum()
