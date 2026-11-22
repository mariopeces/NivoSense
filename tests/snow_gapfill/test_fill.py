import math
import unittest
from datetime import date

import numpy as np

from pipelines.snow_gapfill import fill as f
from pipelines.snow_obs.classify import CLOUD, NO_SNOW, NODATA, SNOW

ROWS, COLS = 100, 200


def terrain(group: int = 0) -> f.Terrain:
    """Elevation rising 10 m per column from 1000 m (1000 pixels per 50 m band), one group."""
    elevation = np.tile(1000.0 + 10.0 * np.arange(COLS, dtype="float32"), (ROWS, 1))
    inside = np.ones((ROWS, COLS), bool)
    return f.Terrain(elevation, np.full((ROWS, COLS), group, "uint8"), inside, inside.copy())


def snow_above(z: float, t: f.Terrain) -> np.ndarray:
    return np.where(t.elevation >= z, SNOW, NO_SNOW).astype("uint8")


class TerrainGroupsTest(unittest.TestCase):
    def test_sectors_and_flat(self) -> None:
        slope = np.radians(np.array([20.0, 20.0, 20.0, 20.0, 2.0]))
        aspect = np.radians(np.array([0.0, 90.0, 350.0, 200.0, 90.0]))
        self.assertEqual(f.terrain_groups(slope, aspect).tolist(), [0, 2, 0, 4, f.FLAT])


class IsotonicTest(unittest.TestCase):
    def test_pools_violators_by_weight(self) -> None:
        fitted = f.isotonic_increasing(np.array([0.2, 0.1, 0.5]), np.array([1.0, 3.0, 1.0]))
        np.testing.assert_allclose(fitted, [0.125, 0.125, 0.5])

    def test_increasing_input_is_unchanged(self) -> None:
        np.testing.assert_allclose(f.isotonic_increasing(np.array([0.0, 0.3, 1.0]), np.ones(3)), [0.0, 0.3, 1.0])


class FitSnowlineTest(unittest.TestCase):
    def test_sharp_snowline_is_found_between_band_centres(self) -> None:
        t = terrain()
        line = f.fit_snowline(snow_above(2000.0, t), t)
        self.assertAlmostEqual(line.elevation[0], 2000.0)
        self.assertAlmostEqual(line.width[0], max(25.0 / (2 * math.log(3)), f.MIN_WIDTH_M))
        self.assertTrue(np.isnan(line.elevation[1:]).all())

    def test_gradual_transition_gives_a_wider_curve(self) -> None:
        t = terrain()
        rng = np.random.default_rng(0)
        p = 1 / (1 + np.exp(-(t.elevation - 2000.0) / 150.0))
        classes = np.where(rng.random(p.shape) < p, SNOW, NO_SNOW).astype("uint8")
        line = f.fit_snowline(classes, t)
        self.assertAlmostEqual(line.elevation[0], 2000.0, delta=40)
        self.assertAlmostEqual(line.width[0], 150.0, delta=40)

    def test_all_snow_down_to_the_bottom_puts_the_line_below(self) -> None:
        t = terrain()
        line = f.fit_snowline(np.full((ROWS, COLS), SNOW, "uint8"), t)
        self.assertAlmostEqual(line.elevation[0], 1025.0 - f.BEYOND_RANGE_M)

    def test_no_snow_up_to_the_top_puts_the_line_above(self) -> None:
        t = terrain()
        line = f.fit_snowline(np.full((ROWS, COLS), NO_SNOW, "uint8"), t)
        self.assertAlmostEqual(line.elevation[0], 2975.0 + f.BEYOND_RANGE_M)

    def test_cloud_over_the_summits_leaves_the_line_unknown(self) -> None:
        t = terrain()
        classes = np.full((ROWS, COLS), NO_SNOW, "uint8")
        classes[:, 120:] = CLOUD  # nothing seen above 2200 m
        self.assertTrue(np.isnan(f.fit_snowline(classes, t).elevation[0]))

    def test_ski_resort_is_left_out_of_the_fit(self) -> None:
        t = terrain()
        classes = np.full((ROWS, COLS), NO_SNOW, "uint8")
        classes[:, :50] = SNOW  # artificial snow low down
        fit = t.fit.copy()
        fit[:, :50] = False
        line = f.fit_snowline(classes, f.Terrain(t.elevation, t.group, t.inside, fit))
        self.assertGreater(line.elevation[0], 2975.0)


class SnowlineTableTest(unittest.TestCase):
    def test_gaps_take_the_nearest_date(self) -> None:
        days = [date(2026, 1, d) for d in (1, 5, 8, 20)]
        observations = [f.Observation(d, np.zeros((1, 1), "uint8"), str(d)) for d in days]
        lines = [f.Snowline(np.full(f.GROUPS, v), np.full(f.GROUPS, 50.0)) for v in (1500.0, np.nan, np.nan, 2000.0)]
        table = f.snowline_table(observations, lines)
        self.assertEqual(table.elevation[:, 0].tolist(), [1500.0, 1500.0, 1500.0, 2000.0])
        self.assertEqual(table.source[:, 0].tolist(), [0, 0, 0, 3])


class FillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.t = terrain()
        # Snowline at 1500 m on 1 Jan, 2500 m on 11 Jan; the pixel at column 100 (2000 m)
        # goes from snow to no snow, and column 199 (2990 m) stays snow.
        jan1 = snow_above(1500.0, self.t)
        jan11 = snow_above(2500.0, self.t)
        jan11[0, 199] = CLOUD
        self.obs = [
            f.Observation(date(2026, 1, 1), jan1, "a"),
            f.Observation(date(2026, 1, 11), jan11, "b"),
        ]
        self.table = f.snowline_table(self.obs, [f.fit_snowline(o.classes, self.t) for o in self.obs])

    def fill(self, day: date) -> f.Filled:
        return f.fill(day, self.obs, self.table, self.t)

    def test_observed_day_keeps_the_observation(self) -> None:
        result = self.fill(date(2026, 1, 1))
        self.assertTrue((result.method[:, :] == f.OBSERVED).all())
        self.assertEqual(float(result.probability[5, 100]), 1.0)
        self.assertEqual(float(result.probability[5, 10]), 0.0)
        self.assertTrue((result.days_since == 0).all())

    def test_agreeing_brackets_are_carried(self) -> None:
        result = self.fill(date(2026, 1, 4))
        self.assertEqual(int(result.method[5, 199]), f.BRACKETED)
        self.assertEqual(float(result.probability[5, 199]), 1.0)
        self.assertEqual(float(result.days_since[5, 199]), 3.0)
        self.assertEqual(result.sources, {"a", "b"})

    def test_disagreeing_brackets_follow_the_interpolated_snowline(self) -> None:
        # On 6 Jan the snowline is halfway, at 2000 m: just above it snow, just below bare.
        result = self.fill(date(2026, 1, 6))
        self.assertEqual(int(result.method[5, 100]), f.SNOWLINE_BETWEEN)
        self.assertGreater(float(result.probability[5, 110]), 0.99)  # 2100 m
        self.assertLess(float(result.probability[5, 90]), 0.01)  # 1900 m
        self.assertTrue(result.snow[5, 105])
        self.assertFalse(result.snow[5, 95])

    def test_a_cloudy_pixel_on_an_observation_day_is_filled(self) -> None:
        result = self.fill(date(2026, 1, 11))
        self.assertEqual(int(result.method[0, 199]), f.SNOWLINE_NO_NEXT)
        self.assertGreater(float(result.probability[0, 199]), 0.99)
        self.assertEqual(float(result.days_since[0, 199]), 10.0)

    def test_after_the_last_observation_the_last_snowline_persists(self) -> None:
        result = self.fill(date(2026, 1, 20))
        self.assertTrue((result.method == f.SNOWLINE_NO_NEXT).all())
        self.assertTrue(result.snow[5, 160])  # 2600 m
        self.assertFalse(result.snow[5, 140])  # 2400 m
        self.assertEqual(float(result.days_since[5, 140]), 9.0)

    def test_before_the_first_observation_the_first_snowline_is_used(self) -> None:
        result = self.fill(date(2025, 12, 28))
        self.assertTrue((result.method == f.SNOWLINE_NO_LAST).all())
        self.assertTrue((result.days_since == f.NODATA).all())
        self.assertTrue(result.snow[5, 60])  # 1600 m
        self.assertFalse(result.snow[5, 40])  # 1400 m

    def test_outside_the_domain_is_nodata(self) -> None:
        inside = self.t.inside.copy()
        inside[:, :10] = False
        t = f.Terrain(self.t.elevation, self.t.group, inside, inside)
        obs = [f.Observation(o.day, np.where(inside, o.classes, NODATA).astype("uint8"), o.source) for o in self.obs]
        result = f.fill(date(2026, 1, 6), obs, self.table, t)
        self.assertTrue((result.probability[:, :10] == f.NODATA).all())
        self.assertTrue((result.method[:, :10] == 255).all())


if __name__ == "__main__":
    unittest.main()
