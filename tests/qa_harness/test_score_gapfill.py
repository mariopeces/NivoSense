import unittest
from datetime import date, timedelta

import numpy as np

from pipelines.snow_gapfill import fill as f
from pipelines.snow_obs.classify import CLOUD, NO_SNOW, SNOW
from qa import score_gapfill as score

ROWS, COLS = 60, 200


def terrain() -> f.Terrain:
    elevation = np.tile(1000.0 + 10.0 * np.arange(COLS, dtype="float32"), (ROWS, 1))
    inside = np.ones((ROWS, COLS), bool)
    return f.Terrain(elevation, np.zeros((ROWS, COLS), "uint8"), inside, inside.copy())


def melt_season(t: f.Terrain, cloudy_day: int | None = None) -> list[f.Observation]:
    """Observations every 5 days from 1 Mar; the snowline rises 50 m a day from 1500 m."""
    observations = []
    for k in range(8):
        day = date(2026, 3, 1) + timedelta(days=5 * k)
        classes = np.where(t.elevation >= 1500.0 + 250.0 * k, SNOW, NO_SNOW).astype("uint8")
        if k == cloudy_day:
            classes[: ROWS // 2] = CLOUD
        observations.append(f.Observation(day, classes, day.isoformat()))
    return observations


class CountsTest(unittest.TestCase):
    def test_confusion_counts_on_the_population_only(self) -> None:
        predicted = np.array([True, True, False, False, True])
        truth = np.array([SNOW, NO_SNOW, SNOW, NO_SNOW, SNOW], "uint8")
        population = np.array([True, True, True, True, False])
        c = score.counts(predicted, truth, population)
        self.assertEqual((c["tp"], c["fp"], c["fn"], c["tn"], c["pixels"]), (1, 1, 1, 1, 4))
        self.assertEqual(score.f1(c), 0.5)


class ChangingTest(unittest.TestCase):
    def test_only_pixels_seen_both_ways_within_ten_days(self) -> None:
        t = terrain()
        obs = melt_season(t)
        mask = score.changing(date(2026, 3, 11), obs)  # sees 1 Mar to 21 Mar: snowlines 1500..2500 m
        self.assertTrue(mask[0, 60])  # 1600 m: snow on 1 Mar, bare from 6 Mar
        self.assertFalse(mask[0, 20])  # 1200 m: always bare
        self.assertFalse(mask[0, 170])  # 2700 m: always snow in the window


class SeasonTest(unittest.TestCase):
    def test_span_of_dates_with_snow(self) -> None:
        t = terrain()
        obs = melt_season(t)
        bare = date(2026, 2, 20)
        obs.insert(0, f.Observation(bare, np.full((ROWS, COLS), NO_SNOW, "uint8"), "bare"))
        # The snowline passes the top (2990 m) before 31 Mar.
        self.assertEqual(score.season(obs, t.inside), (date(2026, 3, 1), date(2026, 3, 26)))


class ReportTest(unittest.TestCase):
    def test_a_steady_melt_is_filled_well_in_both_families(self) -> None:
        t = terrain()
        obs = melt_season(t, cloudy_day=3)
        result = score.report(obs, t, date(2026, 3, 1), date(2026, 4, 30))
        self.assertTrue(result["ok"], result["failures"])
        self.assertGreaterEqual(result["families"]["transplant"]["f1"], 0.9)
        self.assertGreaterEqual(result["families"]["hidden_run"]["f1"], 0.8)
        # 6 dates in the season: 5 runs of 2 and 4 runs of 3, so 10 + 12 hidden days.
        self.assertEqual(result["families"]["hidden_run"]["cases"], 22)
        transplants = [c for c in result["cases"] if c["family"] == "transplant"]
        self.assertTrue(all(c["donor"] == "2026-03-16" for c in transplants))
        self.assertNotIn("2026-03-16", [c["date"] for c in transplants])

    def test_a_filler_that_ignores_the_snowline_fails(self) -> None:
        t = terrain()
        obs = melt_season(t, cloudy_day=3)
        real_fill = f.fill

        def stale(day: date, observations: list, table: f.SnowlineTable, terrain_: f.Terrain) -> f.Filled:
            filled = real_fill(day, observations, table, terrain_)
            filled.snow[filled.method >= f.SNOWLINE_BETWEEN] = True
            return filled

        score.f.fill = stale  # type: ignore[assignment]
        try:
            result = score.report(obs, t, date(2026, 3, 1), date(2026, 4, 30))
        finally:
            score.f.fill = real_fill  # type: ignore[assignment]
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
