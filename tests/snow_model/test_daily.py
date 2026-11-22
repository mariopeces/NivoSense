import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np

from pipelines.catalog import LocalStorage
from pipelines.snow_model import insertion
from pipelines.snow_model.daily import load_state, save_state, seasons, state_digest
from pipelines.snow_model.grid import Grid
from pipelines.snow_model.snowpack import Member, build_tables, simulate
from pipelines.snow_obs import classify as c
from tests.snow_model.test_snow_model import PARAMETERS, synthetic_domain, synthetic_forcing


def observation(
    classes: np.ndarray, confidence: np.ndarray, left: float, top: float, flags: np.ndarray | None = None
) -> insertion.Observation:
    if flags is None:
        flags = np.zeros_like(classes)
    return insertion.Observation("2026-11-20", classes, confidence, flags, left, top, 20.0, "a" * 64)


class SeasonTests(unittest.TestCase):
    def test_range_inside_one_season(self):
        found = seasons(date(2026, 10, 1), date(2026, 11, 21))
        self.assertEqual(
            [(s.start, s.first, s.last) for s in found], [(date(2026, 10, 1), date(2026, 10, 1), date(2026, 11, 21))]
        )

    def test_range_across_seasons_is_split_in_order(self):
        found = seasons(date(2025, 9, 28), date(2025, 10, 2))
        self.assertEqual([(s.start, s.first, s.last) for s in found], [
            (date(2024, 10, 1), date(2025, 9, 28), date(2025, 9, 30)),
            (date(2025, 10, 1), date(2025, 10, 1), date(2025, 10, 2)),
        ])


class MemberTests(unittest.TestCase):
    def test_stepping_gives_the_same_state_as_simulate(self):
        tables = build_tables(synthetic_forcing(5, 5))
        domain = synthetic_domain()
        expected = simulate(domain, tables, PARAMETERS, set(), True)
        member = Member(domain, tables, PARAMETERS)
        for day in range(len(tables.days)):
            member.step(day)
        np.testing.assert_array_equal(member.swe, expected.final_swe)
        np.testing.assert_array_equal(member.depth, expected.final_depth)

    def test_resuming_from_a_state_continues_the_run(self):
        tables = build_tables(synthetic_forcing(5, 5))
        domain = synthetic_domain()
        whole = Member(domain, tables, PARAMETERS)
        for day in range(10):
            whole.step(day)
        first = Member(domain, tables, PARAMETERS)
        for day in range(5):
            first.step(day)
        resumed = Member(domain, tables, PARAMETERS, first.swe, first.depth)
        for day in range(5, 10):
            resumed.step(day)
        np.testing.assert_array_equal(resumed.swe, whole.swe)

    def test_insertion_clears_only_the_bare_cells(self):
        tables = build_tables(synthetic_forcing(5, 0))
        member = Member(synthetic_domain(), tables, PARAMETERS)
        for day in range(5):
            member.step(day)
        self.assertTrue((member.swe > 0).all())
        member.insert_bare(np.array([True, False, True]))
        self.assertEqual(member.swe[0], 0)
        self.assertEqual(member.depth[2], 0)
        self.assertGreater(member.swe[1], 0)


class InsertionTests(unittest.TestCase):
    grid = Grid("EPSG:32630", 300000.0, 4100200.0, 100.0, 2, 2)

    def pasted(self, classes_value: int, confidence_value: int) -> insertion.Observation:
        classes = np.full((10, 10), classes_value, dtype="uint8")
        confidence = np.full((10, 10), confidence_value, dtype="uint8")
        return observation(classes, confidence, self.grid.left, self.grid.top)

    def test_clear_bare_ground_is_bare(self):
        state = insertion.cell_state(self.pasted(c.NO_SNOW, c.CONFIDENCE_HIGH), self.grid)
        self.assertTrue(state.bare.all() and state.valid.all())
        self.assertFalse(state.snow.any())

    def test_cloud_unknown_and_forest_carry_no_evidence(self):
        for classes, confidence in (
            (c.CLOUD, c.CONFIDENCE_NONE),
            (c.UNKNOWN, c.CONFIDENCE_NONE),
            (c.NO_SNOW, c.CONFIDENCE_LOW),
        ):
            state = insertion.cell_state(self.pasted(classes, confidence), self.grid)
            self.assertFalse(state.bare.any(), classes)

    def test_snow_keeps_its_cell(self):
        state = insertion.cell_state(self.pasted(c.SNOW, c.CONFIDENCE_HIGH), self.grid)
        self.assertFalse(state.bare.any())
        self.assertTrue(state.snow.all())

    def test_a_snow_patch_in_a_cell_stops_the_clearing(self):
        classes = np.full((10, 10), c.NO_SNOW, dtype="uint8")
        classes[:5, :5] = c.SNOW
        classes[1, 1] = c.SNOW
        confidence = np.full((10, 10), c.CONFIDENCE_HIGH, dtype="uint8")
        state = insertion.cell_state(observation(classes, confidence, self.grid.left, self.grid.top), self.grid)
        self.assertFalse(state.bare[0, 0])
        self.assertTrue(state.bare[1, 1])

    def test_three_snow_pixels_of_twenty_five_still_leave_a_bare_cell_and_four_do_not(self):
        confidence = np.full((10, 10), c.CONFIDENCE_HIGH, dtype="uint8")
        for snow_pixels, expected in ((3, True), (4, False)):
            classes = np.full((10, 10), c.NO_SNOW, dtype="uint8")
            classes[0, :snow_pixels] = c.SNOW
            state = insertion.cell_state(observation(classes, confidence, self.grid.left, self.grid.top), self.grid)
            self.assertEqual(bool(state.bare[0, 0]), expected, snow_pixels)

    def test_observation_smaller_and_offset_is_placed_by_coordinates(self):
        classes = np.full((5, 5), c.NO_SNOW, dtype="uint8")
        confidence = np.full((5, 5), c.CONFIDENCE_HIGH, dtype="uint8")
        # One model cell (5 x 5 pixels of 20 m) at column 1, row 0.
        state = insertion.cell_state(observation(classes, confidence, self.grid.left + 100.0, self.grid.top), self.grid)
        self.assertEqual(state.bare.tolist(), [[False, True], [False, False]])

    def test_observation_off_the_grid_is_refused(self):
        classes = np.zeros((5, 5), dtype="uint8")
        with self.assertRaises(ValueError):
            insertion.cell_state(observation(classes, classes, self.grid.left + 10.0, self.grid.top), self.grid)


class ShadowTests(unittest.TestCase):
    grid = Grid("EPSG:32630", 300000.0, 4100000.0, 100.0, 40, 1)

    def state(self, snow_columns: int) -> insertion.CellState:
        # 40 cells in a row: 30 lit and decided (snow_columns of them snowy), 10 in terrain shadow.
        classes = np.full((5, 200), c.NO_SNOW, dtype="uint8")
        classes[:, : snow_columns * 5] = c.SNOW
        classes[:, 150:] = c.UNKNOWN
        flags = np.zeros_like(classes)
        flags[:, 150:] = c.FLAG_TERRAIN_SHADOW
        confidence = np.full_like(classes, c.CONFIDENCE_HIGH)
        confidence[:, 150:] = c.CONFIDENCE_NONE
        return insertion.cell_state(observation(classes, confidence, self.grid.left, self.grid.top, flags), self.grid)

    def test_shaded_cells_of_a_snow_free_band_are_bare(self):
        state = self.state(0)
        self.assertTrue(state.shadow[0, 30:].all())
        bare = insertion.shadow_bare(state, np.full((1, 40), 3050.0), np.zeros((1, 40), dtype=bool))
        self.assertTrue(bare[0, 30:].all() and not bare[0, :30].any())

    def test_shaded_cells_of_a_snowy_band_stay_unknown(self):
        state = self.state(5)
        bare = insertion.shadow_bare(state, np.full((1, 40), 3050.0), np.zeros((1, 40), dtype=bool))
        self.assertFalse(bare.any())

    def test_a_band_with_too_few_decided_cells_says_nothing(self):
        state = self.state(0)
        # Only cells 20 to 29 are decided in the 3000 m band, under the minimum.
        elevation = np.concatenate([np.full(20, 2050.0), np.full(20, 3050.0)])[None]
        bare = insertion.shadow_bare(state, elevation, np.zeros((1, 40), dtype=bool))
        self.assertFalse(bare[0, 30:].any())

    def test_the_ski_resort_does_not_count_as_snow_in_the_band(self):
        state = self.state(3)
        ski = np.zeros((1, 40), dtype=bool)
        ski[0, :3] = True
        bare = insertion.shadow_bare(state, np.full((1, 40), 3050.0), ski)
        self.assertTrue(bare[0, 30:].all())


class StateTests(unittest.TestCase):
    def test_state_round_trips_and_checks_its_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalStorage(Path(tmp))
            swe = np.arange(6, dtype="float32").reshape(2, 3)
            depth = swe / 3
            save_state(storage, date(2026, 11, 20), swe, depth, "sig")
            loaded = load_state(storage, date(2026, 11, 20), "sig")
            assert loaded is not None
            np.testing.assert_array_equal(loaded[0], swe)
            self.assertEqual(state_digest(*loaded), state_digest(swe, depth))
            self.assertIsNone(load_state(storage, date(2026, 11, 19), "sig"))
            with self.assertRaises(RuntimeError):
                load_state(storage, date(2026, 11, 20), "other")
