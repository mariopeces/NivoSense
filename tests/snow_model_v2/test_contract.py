from datetime import date, timedelta

import numpy as np
import pytest

from pipelines.snow_model_v2.contract import (
    ClassDomain,
    Priors,
    SeasonForcing,
    sample_parameters,
)


def test_sample_parameters_shapes_and_bounds():
    p = sample_parameters(200, 2025, storm_count=7)
    priors = Priors()
    for name in ("b0", "g", "dT", "L", "Ts", "DDF", "rad", "beta", "rho_s"):
        assert getattr(p, name).shape == (200,)
    assert p.xi.shape == (200, 7)
    assert p.b0.min() >= priors.b0_bounds[0] and p.b0.max() <= priors.b0_bounds[1]
    assert 0.0 <= p.g.min() and p.g.max() <= 0.10
    assert 4.5 <= p.L.min() and p.L.max() <= 8.0
    assert 0.05 <= p.beta.min() and p.beta.max() <= 0.8
    assert abs(np.median(p.b0) - 1.0) < 0.05
    assert abs(p.dT.mean()) < 0.05 and abs(p.dT.std() - 1.5) < 0.1
    assert abs(p.xi.std() - 0.25) < 0.03


def test_sample_parameters_deterministic_and_season_specific():
    a, b = sample_parameters(50, 2025, storm_count=3), sample_parameters(50, 2025, storm_count=3)
    c = sample_parameters(50, 2026, storm_count=3)
    for name in ("b0", "g", "dT", "L", "Ts", "DDF", "rad", "beta", "rho_s", "xi"):
        assert np.array_equal(getattr(a, name), getattr(b, name))
    assert not np.array_equal(a.b0, c.b0)


def test_take_subset():
    p = sample_parameters(10, 2025, storm_count=4)
    q = p.take(np.array([1, 3]))
    assert q.count == 2 and q.xi.shape == (2, 4) and q.b0[1] == p.b0[3] and q.water_year == 2025


def test_season_forcing_validates_shapes():
    days = [date(2025, 10, 1) + timedelta(days=i) for i in range(2)]
    good = dict(
        days=days,
        elevation=np.zeros(3),
        temperature=np.zeros((3, 2, 24)),
        precipitation=np.zeros((3, 2, 24)),
        shortwave=np.zeros((3, 2)),
        storm_id=np.full((2, 24), -1, dtype="int32"),
    )
    assert SeasonForcing(**good).storm_count == 0
    with pytest.raises(ValueError):
        SeasonForcing(**{**good, "shortwave": np.zeros((3, 3))})


def test_class_domain_upsample():
    domain = ClassDomain(
        class_of_cell=np.array([0, 1, -1, 1], dtype="int32"),
        elevation=np.array([2000.0, 2100.0]),
        aspect=np.array([0, 4], dtype="int8"),
        neighbours=np.zeros((2, 1), dtype="int32"),
        weights=np.ones((2, 1), dtype="float32"),
        radiation=np.ones((92, 2), dtype="float32"),
        cell_count=np.array([1, 2], dtype="int32"),
        cell_area_m2=1e4,
    )
    out = domain.upsample(np.array([[5.0, 7.0], [1.0, 2.0]], dtype="float32"))
    assert out.shape == (2, 4)
    assert out[0, 0] == 5.0 and out[0, 3] == 7.0 and np.isnan(out[0, 2])
