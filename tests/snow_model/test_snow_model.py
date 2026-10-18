import unittest
from datetime import date, timedelta

import numpy as np

from pipelines.snow_model import observations as obs
from pipelines.snow_model.ensemble import (
    PARAMETER_RANGES,
    effective_size,
    sample_members,
    tempered_weights,
    weighted_quantiles,
)
from pipelines.snow_model.forcing import Forcing, neighbour_weights
from pipelines.snow_model.grid import build_grid
from pipelines.snow_model.radiation import index_for_day, radiation_index
from pipelines.snow_model.snowpack import Domain, build_tables, simulate
from pipelines.snow_model.validation import confusion_metrics, gate, split_fit_test

PARAMETERS = {
    "lapse_k_per_km": 6.5,
    "precipitation_gradient_per_100m": 0.05,
    "precipitation_scale": 1.0,
    "rain_snow_threshold": 1.0,
    "melt_factor": 2.5,
    "radiation_factor": 0.005,
}


def synthetic_forcing(cold_days: int, warm_days: int) -> Forcing:
    days = [date(2025, 11, 1) + timedelta(days=offset) for offset in range(cold_days + warm_days)]
    hours = np.arange(24)
    cold = -5 + 3 * np.sin((hours - 9) / 24 * 2 * np.pi)
    warm = 8 + 4 * np.sin((hours - 9) / 24 * 2 * np.pi)
    temperature = np.stack([cold] * cold_days + [warm] * warm_days)[None].astype("float32")
    precipitation = np.zeros_like(temperature)
    precipitation[:, :cold_days, 12] = 2.0
    return Forcing(
        days,
        np.array([0.0]),
        np.array([37.0]),
        np.array([1000.0], dtype="float32"),
        temperature,
        precipitation,
        np.full((1, len(days)), 120.0, dtype="float32"),
    )


def synthetic_domain() -> Domain:
    return Domain(
        elevation=np.array([1000.0, 1500.0, 2000.0], dtype="float32"),
        neighbours=np.zeros((3, 1), dtype="int32"),
        weights=np.ones((3, 1), dtype="float32"),
        basin=np.array([0, 0, 1]),
        basin_count=2,
        cell_area_m2=1e6,
        radiation=np.ones((92, 3), dtype="float32"),
    )


class EnsembleTests(unittest.TestCase):
    def test_latin_hypercube_covers_each_range_evenly(self):
        members = sample_members(20, 3)
        for name, (low, high) in PARAMETER_RANGES.items():
            values = np.array([member[name] for member in members])
            self.assertTrue(((values >= low) & (values <= high)).all())
            strata = np.floor((values - low) / (high - low) * 20).astype(int)
            self.assertEqual(sorted(strata.tolist()), list(range(20)))

    def test_tempered_weights_reach_target_size(self):
        cost = np.linspace(0, 1, 40)
        weights = tempered_weights(cost, 8)
        self.assertAlmostEqual(weights.sum(), 1.0)
        self.assertAlmostEqual(effective_size(weights), 8, delta=0.2)
        self.assertEqual(int(np.argmax(weights)), 0)

    def test_weighted_quantiles_follow_the_weights(self):
        values = np.arange(1, 11, dtype="float32")[:, None]
        heavy_low = np.array([0.3] * 5 + [0.1 / 5] * 5)
        heavy_low /= heavy_low.sum()
        median = weighted_quantiles(values, heavy_low, [0.5])[0, 0]
        self.assertLess(median, 4)
        uniform = np.full(10, 0.1)
        self.assertAlmostEqual(float(weighted_quantiles(values, uniform, [0.5])[0, 0]), 5.5, places=4)


class GridAndObservationTests(unittest.TestCase):
    def test_grid_is_snapped_and_nests_sentinel_pixels(self):
        grid = build_grid((-3.55, 36.94, -2.66, 37.21), 100)
        self.assertEqual(grid.crs, "EPSG:32630")
        self.assertEqual(grid.left % 100, 0)
        self.assertEqual(grid.top % 100, 0)
        fine = grid.refined()
        self.assertEqual((fine.width, fine.height), (grid.width * 10, grid.height * 10))
        self.assertEqual(fine.resolution, 10.0)
        with self.assertRaises(ValueError):
            build_grid((-3.55, 36.94, -2.66, 37.21), 90)

    def test_aggregation_returns_snow_and_valid_fractions(self):
        snow = np.zeros((20, 20), dtype=bool)
        valid = np.ones((20, 20), dtype=bool)
        snow[:10, :10] = True
        snow[:5, 10:] = True
        valid[10:, 10:] = False
        fraction, coverage = obs.aggregate(snow, valid, 10)
        self.assertEqual(fraction.tolist(), [[1.0, 0.5], [0.0, 0.0]])
        self.assertEqual(coverage.tolist(), [[1.0, 1.0], [1.0, 0.0]])

    def test_scene_choice_keeps_spacing_and_prefers_clear_days(self):
        def scene(day, cloud):
            return obs.Scene(day, ({"properties": {"eo:cloud_cover": cloud}},))

        scenes = [
            scene(date(2026, 1, 1), 30),
            scene(date(2026, 1, 3), 5),
            scene(date(2026, 1, 12), 20),
            scene(date(2026, 1, 15), 10),
        ]
        chosen = obs.choose_scenes(scenes, 3, 7)
        self.assertEqual([item.day for item in chosen], [date(2026, 1, 3), date(2026, 1, 15)])

    def test_reflectance_offset_depends_on_baseline(self):
        applied = {"properties": {"earthsearch:boa_offset_applied": True}}
        raw = {"properties": {"s2:processing_baseline": "05.11"}}
        old = {"properties": {"s2:processing_baseline": "03.00"}}
        self.assertEqual(obs.reflectance_offset(applied), 0.0)
        self.assertEqual(obs.reflectance_offset(raw), 1000.0)
        self.assertEqual(obs.reflectance_offset(old), 0.0)


class RadiationTests(unittest.TestCase):
    def test_flat_ground_is_neutral_and_winter_slopes_follow_aspect(self):
        slope = np.radians(np.array([0.0, 30.0, 30.0], dtype="float32"))
        aspect = np.radians(np.array([0.0, 180.0, 0.0], dtype="float32"))
        samples = radiation_index(37.0, slope, aspect)
        january = index_for_day(samples, 15)
        self.assertAlmostEqual(float(january[0]), 1.0, places=3)
        self.assertGreater(january[1], 1.2)
        self.assertLess(january[2], 0.5)


class SnowpackTests(unittest.TestCase):
    def run_model(self, parameters=PARAMETERS, cold_days=30, warm_days=30):
        tables = build_tables(synthetic_forcing(cold_days, warm_days))
        return simulate(synthetic_domain(), tables, parameters, {5}, True)

    def test_mass_is_conserved(self):
        result = self.run_model()
        for basin in range(2):
            balance = (
                result.basin_snowfall_hm3[:, basin].sum() - result.basin_melt_hm3[:, basin].sum()
            )
            self.assertAlmostEqual(float(balance), float(result.basin_swe_hm3[-1, basin]), places=5)
        self.assertTrue((result.basin_swe_hm3 >= 0).all())

    def test_cold_period_accumulates_more_snow_higher_up_and_warm_period_melts_it(self):
        cold = self.run_model(warm_days=0)
        self.assertGreater(cold.final_swe[2], cold.final_swe[0])
        self.assertTrue((cold.basin_melt_hm3 == 0).all())
        warm = self.run_model()
        self.assertLess(warm.final_swe.sum(), cold.final_swe.sum())
        self.assertEqual(float(warm.final_swe[0]), 0.0)

    def test_depth_follows_density_and_snow_mask_is_recorded(self):
        result = self.run_model(warm_days=0)
        density = result.final_swe / result.final_depth
        self.assertTrue(((density > 50) & (density <= 450)).all())
        self.assertIn(5, result.snow_masks)

    def test_neighbour_weights_favour_close_points(self):
        forcing = synthetic_forcing(1, 0)
        forcing.lon = np.array([3.0, 3.01])
        forcing.lat = np.array([0.0, 0.0])
        forcing.elevation = np.array([0.0, 0.0], dtype="float32")
        nearest, weights = neighbour_weights(
            forcing, np.array([500050.0]), np.array([0.0]), "EPSG:32631"
        )
        self.assertEqual(int(nearest[0, 0]), 0)
        self.assertGreater(weights[0, 0], weights[0, 1])
        self.assertAlmostEqual(float(weights.sum()), 1.0, places=5)


class ValidationTests(unittest.TestCase):
    def test_metrics_and_gate(self):
        observed = np.array([True, True, False, False, True, False])
        usable = np.array([True, True, True, True, True, False])
        perfect = confusion_metrics(observed.astype(float), observed, usable)
        self.assertEqual(perfect["f1"], 1.0)
        self.assertEqual(perfect["cells"], 5)
        wrong = confusion_metrics(1.0 - observed.astype(float), observed, usable)
        self.assertEqual(wrong["f1"], 0.0)
        settings = {"min_f1": 0.8, "min_test_dates_with_snow": 3}
        self.assertTrue(gate(perfect, wrong, 3, settings)["passed"])
        self.assertFalse(gate(perfect, wrong, 2, settings)["passed"])
        self.assertFalse(gate(wrong, perfect, 5, settings)["passed"])

    def test_every_third_date_is_held_out(self):
        fit, test = split_fit_test(7)
        self.assertEqual(test, [2, 5])
        self.assertEqual(sorted(fit + test), list(range(7)))


if __name__ == "__main__":
    unittest.main()
