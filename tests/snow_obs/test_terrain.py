import unittest

import numpy as np

from pipelines.s2.domain import Grid
from pipelines.snow_obs import terrain


class TerrainShadowTest(unittest.TestCase):
    def wall(self) -> np.ndarray:
        """Flat ground at 0 m with a 100 m high east-west wall on rows 20 and 21."""
        elevation = np.zeros((40, 30), dtype="float32")
        elevation[20:22] = 100.0
        return elevation

    def test_flat_ground_has_no_shadow(self) -> None:
        shadow = terrain.terrain_shadow(np.full((20, 20), 1500.0, "float32"), 20.0, 160.0, 25.0)
        self.assertFalse(shadow.any())

    def test_wall_casts_its_height_over_tan_of_the_sun_elevation(self) -> None:
        # Sun in the south at 45 degrees: the shadow reaches 100 m (5 pixels) north of the wall.
        shadow = terrain.terrain_shadow(self.wall(), 20.0, 180.0, 45.0)
        column = shadow[:, 15]
        self.assertTrue(column[16:20].all())
        self.assertFalse(column[:15].any())
        # Row 20, the north edge of the wall top, faces north in the central-difference gradient.
        self.assertFalse(column[21:].any())

    def test_lower_sun_casts_a_longer_shadow(self) -> None:
        # At 20 degrees the shadow reaches 100 / tan(20) = 275 m, 13 pixels.
        column = terrain.terrain_shadow(self.wall(), 20.0, 180.0, 20.0)[:, 15]
        self.assertTrue(column[7:20].all())
        self.assertFalse(column[:6].any())

    def test_sun_from_the_north_shades_the_south_side(self) -> None:
        column = terrain.terrain_shadow(self.wall(), 20.0, 0.0, 45.0)[:, 15]
        self.assertTrue(column[22:26].all())
        self.assertFalse(column[:20].any())

    def test_slope_facing_away_from_a_low_sun_is_self_shadowed(self) -> None:
        # A plane dropping 1 m per metre towards the north, sun in the south at 30 degrees.
        rows = np.arange(30, dtype="float32")[:, None] * np.ones((1, 30), "float32")
        elevation = rows * 20.0
        shadow = terrain.terrain_shadow(elevation, 20.0, 180.0, 30.0)
        self.assertTrue(shadow.all())
        self.assertFalse(terrain.terrain_shadow(elevation, 20.0, 0.0, 30.0).any())


class SlopeAspectTest(unittest.TestCase):
    def test_aspect_is_the_downslope_direction(self) -> None:
        cols = np.arange(10, dtype="float32")[None, :] * np.ones((10, 1), "float32")
        _, aspect = terrain.slope_aspect(-cols * 20.0, 20.0)  # falling to the east
        self.assertAlmostEqual(float(np.degrees(aspect[5, 5])), 90.0, places=3)
        rows = cols.T
        _, aspect = terrain.slope_aspect(rows * 20.0, 20.0)  # rising to the south, falling north
        self.assertAlmostEqual(float(np.degrees(aspect[5, 5])) % 360, 0.0, places=3)


class SourceTilesTest(unittest.TestCase):
    def test_tiles_cover_the_sierra_nevada_grid(self) -> None:
        grid = Grid("EPSG:32630", 442780.0, 4123000.0, 20.0, 4692, 1887)
        self.assertEqual(sorted(terrain._tiles(grid, 1)), [(36, 3), (36, 4), (37, 3), (37, 4)])
        self.assertEqual(sorted(terrain._tiles(grid, 3)), [(36, 3), (36, 6)])
        self.assertIn("N36W006", terrain.WORLDCOVER_URL.format(lat=36, lon=6))
        self.assertIn("N37_00_W004", terrain.COPERNICUS_DEM_URL.format(lat=37, lon=4))


if __name__ == "__main__":
    unittest.main()
