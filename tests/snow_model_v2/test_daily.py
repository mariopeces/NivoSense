import json
from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.warp import transform

from pipelines.catalog.layers import get_layer
from pipelines.catalog.storage import LocalStorage
from pipelines.snow_model.grid import Grid
from pipelines.snow_model.insertion import cell_state, load_observation
from pipelines.snow_model.radiation import radiation_index
from pipelines.snow_model_v2 import daily
from pipelines.snow_model_v2.contract import SeasonForcing
from pipelines.snow_model_v2.domain import build_class_domain
from pipelines.snow_model_v2.region_domain import RegionDomain
from pipelines.snow_obs import classify as c

from .helpers import real_forcing

WIDTH, HEIGHT = 8, 6
FACTOR = daily.OBS_FACTOR


def make_grid() -> Grid:
    x, y = transform("EPSG:4326", "EPSG:32630", [-3.1], [37.05])
    return Grid("EPSG:32630", float(round(x[0], -2)), float(round(y[0], -2)), 100.0, WIDTH, HEIGHT)


def make_context(forcing_lattice) -> daily.Context:
    """A 8 x 6 cell region on the real forcing lattice: elevations 1800 to 3100 m rising to the east."""
    from pipelines.snow_model.forcing import neighbour_weights

    grid = make_grid()
    cell_index = np.arange(WIDTH * HEIGHT)
    rows, columns = np.divmod(cell_index, WIDTH)
    elevation = (1800.0 + 190.0 * columns + 10.0 * rows).astype("float32")
    cell_x = grid.left + (columns + 0.5) * grid.resolution
    cell_y = grid.top - (rows + 0.5) * grid.resolution
    neighbours, weights = neighbour_weights(forcing_lattice, cell_x, cell_y, grid.crs)
    aspect = np.full(cell_index.size, 4, dtype="int8")
    radiation = radiation_index(37.05, np.zeros(cell_index.size), np.zeros(cell_index.size))
    domain = build_class_domain(
        elevation, aspect, neighbours, radiation, grid.cell_area_m2, min_cells=2, weights=weights
    )
    region = RegionDomain(
        grid,
        cell_index,
        elevation,
        np.zeros(cell_index.size, dtype=bool),
        domain,
        elevation.reshape(HEIGHT, WIDTH),
        neighbours,
        weights,
        radiation,
        aspect,
    )
    basin = np.where(columns < 4, 0, -1).astype("int64")
    grid20 = Grid(grid.crs, grid.left, grid.top, 20.0, WIDTH * FACTOR, HEIGHT * FACTOR)
    inside = np.ones((HEIGHT * FACTOR, WIDTH * FACTOR), dtype=bool)
    return daily.Context(region, [], np.zeros(0), basin, ["604456"], ["RIO TEST"], inside, grid20, workers=2)


def obs_raster(grid: Grid) -> bytes:
    """Left half snow, right half bare with high confidence, the top two cell rows cloud."""
    rows, columns = HEIGHT * FACTOR, WIDTH * FACTOR
    classes = np.full((rows, columns), c.NO_SNOW, dtype="uint8")
    classes[:, : columns // 2] = c.SNOW
    classes[: 2 * FACTOR, :] = c.CLOUD
    confidence = np.full(classes.shape, c.CONFIDENCE_HIGH, dtype="uint8")
    flags = np.zeros(classes.shape, dtype="uint8")
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=rows,
            width=columns,
            count=3,
            dtype="uint8",
            crs=grid.crs,
            transform=from_origin(grid.left, grid.top, 20.0, 20.0),
        ) as target:
            for band, values in enumerate((classes, confidence, flags), start=1):
                target.write(values, band)
        return memory.read()


class FakeCatalogue(LocalStorage):
    """A local catalogue with the `dates` method of the public one."""

    def dates(self, layer: str) -> list[date]:
        return [date.fromisoformat(k.rsplit("/", 1)[-1][:-5]) for k in self.list(f"catalog/entries/{layer}/")]


@pytest.fixture
def scene(tmp_path, monkeypatch):
    v1, v2 = real_forcing()
    context = make_context(v1)
    storage = LocalStorage(tmp_path / "out")
    catalogue = FakeCatalogue(tmp_path / "obs")
    catalogue.write("layers/snow_obs/2025-02-11.tif", obs_raster(context.region.grid), "image/tiff", "no-cache")
    entry = {"cog": "layers/snow_obs/2025-02-11.tif", "pixel_hash": "ab" * 32}
    catalogue.write("catalog/entries/snow_obs/2025-02-11.json", json.dumps(entry).encode(), "application/json", "")
    hourly = SimpleNamespace(model="ecmwf_ifs", from_forecast=np.zeros(len(v2.days) * 24, dtype=bool))
    monkeypatch.setattr(daily, "season_forcing", lambda *args, **kwargs: (v2, hourly))
    return context, catalogue, storage, tmp_path


def run(scene, first=date(2025, 2, 10), last=date(2025, 2, 11)):
    context, catalogue, storage, tmp_path = scene
    return daily.run_water_year(
        context, catalogue, storage, 2025, first, last, tmp_path / "cache", "test", members=20, cellwise_members=5
    )


def read_entry(storage, layer, day):
    return json.loads(storage.read(f"catalog/entries/{layer}/{day}.json").data)


def read_bands(storage, entry):
    with MemoryFile(storage.read(entry["cog"]).data) as memory, memory.open() as source:
        return source.read(masked=True), source.nodata


def test_layer_bands_are_the_contract_of_the_producer():
    assert get_layer("snow_gapfill").bands == ("snow_probability", "obs_age_days")
    assert get_layer("snow_depth").bands == ("depth_p50", "depth_p10", "depth_p90")
    assert get_layer("snow_gapfill").status == "gapfilled"
    assert get_layer("snow_depth").status == "modelled"


def test_publishes_the_observation_where_it_decides_and_the_prior_elsewhere(scene):
    summaries = run(scene)
    _, _, storage, _ = scene
    assert [s["date"] for s in summaries] == ["2025-02-10", "2025-02-11"]

    observed = read_entry(storage, "snow_gapfill", "2025-02-11")
    prior = read_entry(storage, "snow_gapfill", "2025-02-10")
    assert observed["status"] == "gapfilled" and observed["resolution_m"] == 20
    assert observed["bands"] == ["snow_probability", "obs_age_days"]
    assert {"prior_ensemble", "observation_used", "obs_age_days", "not_validated_against_measurements"} <= set(
        observed["qa"]["flags"]
    )
    assert "ski_resort_excluded_from_score" in observed["qa"]["flags"]
    assert "observation_used" not in prior["qa"]["flags"]
    assert "prior_agreement_pct" in observed["qa"]["scores"] and "prior_agreement_pct" not in prior["qa"]["scores"]

    data, _ = read_bands(storage, observed)
    probability, age = data[0], data[1]
    # Rows 0 and 1 of cells are cloud: they keep the model value (not forced to 0 or 1) and were never decided.
    assert (age[: 2 * FACTOR] == daily.OBS_AGE_NEVER).all()
    assert not ((probability[: 2 * FACTOR] == 1) | (probability[: 2 * FACTOR] == 0)).all()
    # Decided pixels: snow on the left, bare on the right, observed today (age 0).
    assert (probability[2 * FACTOR :, : 4 * FACTOR] == 1).all()
    assert (probability[2 * FACTOR :, 4 * FACTOR :] == 0).all()
    assert (age[2 * FACTOR :] == 0).all()
    # The day before the observation has no age to give.
    before, _ = read_bands(storage, prior)
    assert (before[1] == daily.OBS_AGE_NEVER).all()


def test_the_depth_range_is_ordered_and_summarised_per_basin(scene):
    run(scene)
    _, _, storage, _ = scene
    entry = read_entry(storage, "snow_depth", "2025-02-11")
    assert entry["status"] == "modelled" and entry["bands"] == ["depth_p50", "depth_p10", "depth_p90"]
    assert {"prior_ensemble", "median_of_ensemble", "not_validated_against_measurements"} <= set(entry["qa"]["flags"])
    assert "observation_used" not in entry["qa"]["flags"]
    data, _ = read_bands(storage, entry)
    p50, p10, p90 = data
    assert (p10 <= p50 + 1e-6).all() and (p50 <= p90 + 1e-6).all()
    assert p90.max() > 0  # the east of the region is above 2,500 m, in February
    scores = entry["qa"]["scores"]
    for group in ("basin_604456", "domain"):
        for label in ("snow_area_km2", "depth_mean_m", "depth_peak_m"):
            low, mid, high = (scores[f"{group}_{label}_p{q}"] for q in (10, 50, 90))
            assert low <= mid <= high
    assert scores["domain_snow_area_km2_p50"] >= scores["basin_604456_snow_area_km2_p50"]


def test_a_snow_free_day_is_still_a_product(scene):
    # The first days of the forcing are before any snowfall in the cells below 2,300 m, but the product must exist.
    run(scene, date(2025, 2, 1), date(2025, 2, 1))
    _, _, storage, _ = scene
    entry = read_entry(storage, "snow_gapfill", "2025-02-01")
    data, _ = read_bands(storage, entry)
    assert data[0].min() == 0.0 and data[0].max() == 0.0
    assert storage.exists(entry["pmtiles"])


def test_rerunning_a_date_is_idempotent(scene):
    run(scene)
    _, _, storage, _ = scene
    first = read_entry(storage, "snow_gapfill", "2025-02-11")
    depth = read_entry(storage, "snow_depth", "2025-02-11")
    run(scene)
    assert read_entry(storage, "snow_gapfill", "2025-02-11")["created_at"] == first["created_at"]
    assert read_entry(storage, "snow_depth", "2025-02-11")["pixel_hash"] == depth["pixel_hash"]


def gate_state(valid, snow, bare):
    return SimpleNamespace(valid=valid, snow=snow, bare=bare)


def test_quality_gate_scores_agreement_and_flags_a_failing_date_without_dropping_it(scene):
    context, catalogue, _, _ = scene
    region = context.region
    state = cell_state(load_observation(catalogue, "2025-02-11"), region.grid)
    truth = state.snow.ravel()[region.cell_index]
    ski = np.zeros(region.cell_index.size, dtype=bool)
    good, flags = daily.quality_gate(context, state, truth.astype("float32"), ski)
    assert good["prior_agreement_pct"] == 100.0 and good["prior_snow_on_bare_pct"] == 0.0 and flags == []

    cells = 10_000  # enough decided cells for a failure to count
    wide = SimpleNamespace(region=SimpleNamespace(cell_index=np.arange(cells)))
    none_ski = np.zeros(cells, dtype=bool)
    all_bare = gate_state(np.ones((100, 100), bool), np.zeros((100, 100), bool), np.ones((100, 100), bool))
    scores, flags = daily.quality_gate(wide, all_bare, np.ones(cells, dtype="float32"), none_ski)
    assert scores["prior_agreement_pct"] == 0.0 and scores["prior_snow_on_bare_pct"] == 100.0
    assert flags == ["quality_check_failed"]
    # A date the observation decides nowhere is flagged too, with a count of zero clear cells.
    nothing = gate_state(np.zeros((100, 100), bool), all_bare.snow, all_bare.bare)
    assert daily.quality_gate(wide, nothing, np.ones(cells, dtype="float32"), none_ski) == (
        {"clear_cells": 0.0},
        ["quality_check_failed"],
    )


def test_the_ski_resort_is_left_out_of_the_gate(scene):
    context, catalogue, _, _ = scene
    region = context.region
    state = cell_state(load_observation(catalogue, "2025-02-11"), region.grid)
    ski = np.ones(region.cell_index.size, dtype=bool)
    scores, flags = daily.quality_gate(context, state, np.zeros(region.cell_index.size, dtype="float32"), ski)
    assert scores == {"clear_cells": 0.0} and flags == ["quality_check_failed"]


def test_water_years_are_named_by_the_year_they_end_in():
    assert daily.water_years(date(2024, 9, 28), date(2024, 10, 2)) == [
        (2024, date(2024, 9, 28), date(2024, 9, 30)),
        (2025, date(2024, 10, 1), date(2024, 10, 2)),
    ]
    assert daily.water_years(date(2025, 2, 1), date(2025, 2, 3)) == [(2025, date(2025, 2, 1), date(2025, 2, 3))]


def test_candidate_cells_cover_the_snowy_classes_and_the_cells_above_the_lowest(scene):
    context, _, _, _ = scene
    domain = context.region.domain
    elevation = context.region.elevation
    none = daily.candidate_cells(domain, elevation, np.zeros(domain.class_count, dtype=bool))
    assert not none.any()
    snowy = domain.elevation > 2800
    cells = daily.candidate_cells(domain, elevation, snowy)
    in_snowy = (domain.class_of_cell >= 0) & snowy[np.maximum(domain.class_of_cell, 0)]
    assert cells[in_snowy].all()
    unclassed = domain.class_of_cell < 0
    floor = domain.elevation[snowy].min() - daily.CANDIDATE_MARGIN_M
    assert (cells[unclassed] == (elevation[unclassed] >= floor)).all()


def test_point_elevations_are_the_weighted_mean_of_the_cells_a_point_serves(scene):
    context, _, _, _ = scene
    region = context.region
    count = int(region.neighbours.max()) + 3
    result = daily.point_elevations(region, count)
    assert result.shape == (count,)
    used = np.unique(region.neighbours)
    low, high = region.elevation.min(), region.elevation.max()
    assert ((result[used] >= low) & (result[used] <= high)).all()
    unused = np.setdiff1d(np.arange(count), used)
    assert np.allclose(result[unused], region.elevation.mean())


def test_apply_observation_leaves_cloud_and_low_confidence_bare_to_the_model():
    classes = np.array([[c.SNOW, c.NO_SNOW, c.NO_SNOW, c.CLOUD, c.UNKNOWN]], dtype="uint8")
    confidence = np.array([[c.CONFIDENCE_LOW, c.CONFIDENCE_HIGH, c.CONFIDENCE_LOW, 0, 0]], dtype="uint8")
    inside = np.array([[True, True, True, True, False]])
    model = np.full((1, 5), 0.4, dtype="float32")
    result = daily.apply_observation(model, classes, confidence, inside)
    assert result.tolist() == [[1.0, 0.0, pytest.approx(0.4), pytest.approx(0.4), pytest.approx(0.4)]]
    assert daily.decisive_pixels(classes, confidence, inside).tolist() == [[True, True, False, False, False]]


def test_forcing_digest_changes_with_the_forcing():
    _, v2 = real_forcing()
    changed = SeasonForcing(v2.days, v2.elevation, v2.temperature + 1, v2.precipitation, v2.shortwave, v2.storm_id)
    assert daily.forcing_digest(v2) == daily.forcing_digest(v2) != daily.forcing_digest(changed)


def test_public_catalogue_caches_content_addressed_files_only(tmp_path, monkeypatch):
    calls = []

    def fetch(self, key):
        calls.append(key)
        return b"data"

    monkeypatch.setattr(daily.PublicCatalogue, "_fetch", fetch)
    catalogue = daily.PublicCatalogue("https://example.invalid/prod", tmp_path)
    for _ in range(2):
        assert catalogue.read("layers/snow_obs/2025/x.tif").data == b"data"
        assert catalogue.read("catalog/entries/snow_obs/2025-01-01.json").data == b"data"
    # The COG is fetched once; the entry, which can be republished, every time.
    assert calls == [
        "layers/snow_obs/2025/x.tif",
        "catalog/entries/snow_obs/2025-01-01.json",
        "catalog/entries/snow_obs/2025-01-01.json",
    ]
