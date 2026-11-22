import numpy as np

from pipelines.snow_model.dem import slope_aspect
from pipelines.snow_model.forcing import neighbour_weights
from pipelines.snow_model.radiation import radiation_index
from pipelines.snow_model_v2.contract import sample_parameters
from pipelines.snow_model_v2.domain import aspect_classes, build_class_domain, cellwise_domain
from pipelines.snow_model_v2.engine import run_ensemble

from .helpers import UTM, real_forcing


def synthetic_dem(size=80, resolution=100.0):
    """Smooth ridge-and-valley surface between 1200 and 3200 m, cells of 100 m."""
    y, x = np.mgrid[0:size, 0:size]
    return (
        2200 + 700 * np.sin(x / 13.0) * np.cos(y / 17.0) + 15 * (x - size / 2) + 6 * y + 120 * np.sin((x + 2 * y) / 5.0)
    ).astype("float32"), resolution


def build_domains(min_cells=12):
    v1, v2 = real_forcing()
    dem, resolution = synthetic_dem()
    size = dem.shape[0]
    slope, aspect = slope_aspect(dem, resolution)
    cls = aspect_classes(slope, aspect).ravel()
    radiation = radiation_index(37.1, slope.ravel(), aspect.ravel())
    from rasterio.warp import transform

    x0, y0 = transform("EPSG:4326", UTM, [-3.2], [37.0])
    yy, xx = np.mgrid[0:size, 0:size]
    cx, cy = x0[0] + xx.ravel() * resolution, y0[0] + yy.ravel() * resolution
    neighbours, _ = neighbour_weights(v1, cx, cy, UTM)
    nearest = neighbours[:, :1]
    elevation = dem.ravel()
    cells = cellwise_domain(elevation, nearest, np.ones((elevation.size, 1), dtype="float32"), radiation, 1e4, cls)
    classes = build_class_domain(elevation, cls, nearest, radiation, 1e4, min_cells=min_cells)
    return v2, cells, classes


def test_aspect_classes():
    slope = np.radians(np.array([2.0, 20, 20, 20, 20, 20]))
    aspect = np.radians(np.array([0.0, 0, 90, 180, 270, 350]))
    assert aspect_classes(slope, aspect).tolist() == [4, 0, 1, 2, 3, 0]


def test_class_domain_structure():
    _, cells, classes = build_domains()
    covered = classes.class_of_cell >= 0
    assert 0.5 < covered.mean() <= 1.0
    assert classes.class_count < cells.class_count / 4
    assert classes.cell_count.min() >= 12
    assert np.bincount(classes.class_of_cell[covered]).tolist() == classes.cell_count.tolist()
    members = classes.class_of_cell == 3
    assert abs(classes.elevation[3] - cells.elevation[members].mean()) < 1e-3
    assert classes.neighbours.shape == (classes.class_count, 1) and classes.radiation.shape[1] == classes.class_count


def test_class_means_reproduce_the_cellwise_run():
    v2, cells, classes = build_domains()
    params = sample_parameters(12, 2025, storm_count=v2.storm_count)
    last = len(v2.days) - 1
    full = run_ensemble(cells, v2, params, [last])
    reduced = run_ensemble(classes, v2, params, [last])
    covered = classes.class_of_cell >= 0
    ids = classes.class_of_cell[covered]
    for name, tolerance in (("swe", 0.005), ("depth", 0.005)):
        cell_values = getattr(full, name)[:, :, -1][:, covered]
        truth = np.stack([np.bincount(ids, row, classes.class_count) / classes.cell_count for row in cell_values])
        modelled = getattr(reduced, name)[:, :, -1]
        scale = truth.sum()
        assert truth.sum() > 0
        # Total over cells, weighted by class size, and class-wise error relative to the mean
        total_error = (
            abs((modelled * classes.cell_count).sum() - (truth * classes.cell_count).sum())
            / (truth * classes.cell_count).sum()
        )
        class_error = np.abs(modelled - truth).mean() / (scale / truth.size)
        assert total_error < tolerance, (name, total_error)
        assert class_error < 0.02, (name, class_error)
    upsampled = classes.upsample(reduced.swe[0, :, -1])
    assert np.isnan(upsampled[~covered]).all() and np.isfinite(upsampled[covered]).all()


def test_ensemble_shapes_determinism_and_mass_balance():
    v2, _, classes = build_domains()
    params = sample_parameters(10, 2025, storm_count=v2.storm_count)
    a = run_ensemble(classes, v2, params, [5, 12])
    b = run_ensemble(classes, v2, params, [5, 12], workers=2)
    assert a.day_index.tolist() == [5, 12, len(v2.days) - 1]
    for name in ("swe", "depth", "f_sca", "s_peak", "m_cum"):
        array = getattr(a, name)
        assert array.shape == (10, classes.class_count, 3) and array.dtype == np.float32
        assert np.array_equal(array, getattr(b, name))
    assert a.seed == 2025 * 1000 + 17
    assert (a.f_sca >= 0).all() and (a.f_sca <= 1).all() and (a.swe >= 0).all()
    assert ((a.f_sca > 0) <= (a.swe > 0)).all()
    other = sample_parameters(10, 2026, storm_count=v2.storm_count)
    assert not np.array_equal(a.swe, run_ensemble(classes, v2, other, [5, 12]).swe)


def test_storm_noise_changes_snowfall_and_zero_noise_is_neutral():
    v2, _, classes = build_domains()
    params = sample_parameters(6, 2025, storm_count=v2.storm_count)
    quiet = params.__class__(**{**params.__dict__, "xi": np.zeros_like(params.xi)})
    noisy = run_ensemble(classes, v2, params, [])
    flat = run_ensemble(classes, v2, quiet, [])
    assert not np.allclose(noisy.swe, flat.swe)
    wetter = params.__class__(**{**params.__dict__, "xi": np.full_like(params.xi, 0.5)})
    assert run_ensemble(classes, v2, wetter, []).swe.sum() > flat.swe.sum() * 1.2
