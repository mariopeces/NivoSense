import unittest

import numpy as np

from pipelines.snow_obs import classify as c


def scene(**overrides: np.ndarray) -> c.Scene:
    """A one-row scene of clear, bare, unshadowed, unforested pixels at 1000 m, inside the domain,
    with fields overridden per test."""
    n = len(next(iter(overrides.values()))) if overrides else 1
    base = {
        "green": np.full(n, 0.10, dtype="float32"),
        "red": np.full(n, 0.10, dtype="float32"),
        "swir16": np.full(n, 0.20, dtype="float32"),
        "scl": np.full(n, 5, dtype="uint8"),
        "elevation": np.full(n, 1000.0, dtype="float32"),
        "terrain_shadow": np.zeros(n, dtype=bool),
        "forest": np.zeros(n, dtype=bool),
        "inside": np.ones(n, dtype=bool),
    }
    for key, value in overrides.items():
        base[key] = np.asarray(value, dtype=base[key].dtype)
    return c.Scene(**{k: v.reshape(1, -1) for k, v in base.items()})


def reflectance_for(ndsi: float, red: float, green: float = 0.5) -> tuple[float, float, float]:
    swir = green * (1 - ndsi) / (1 + ndsi)
    return green, red, swir


class NdsiTest(unittest.TestCase):
    def test_values_and_undefined(self) -> None:
        index = c.ndsi(np.array([0.6, 0.0, np.nan], "float32"), np.array([0.2, 0.0, 0.1], "float32"))
        self.assertAlmostEqual(float(index[0]), 0.5, places=6)
        self.assertTrue(np.isnan(index[1]))
        self.assertTrue(np.isnan(index[2]))


class PassOneTest(unittest.TestCase):
    def classes_for(self, ndsi: float, red: float) -> int:
        green, red_, swir = reflectance_for(ndsi, red)
        result = c.classify(scene(green=[green], red=[red_], swir16=[swir]))
        return int(result.classes[0, 0])

    def test_thresholds_are_the_lis_defaults(self) -> None:
        self.assertEqual((c.NDSI_PASS1, c.RED_PASS1, c.NDSI_PASS2, c.RED_PASS2), (0.4, 0.2, 0.15, 0.04))
        self.assertEqual(c.SNOWLINE_BAND_M, 100.0)
        self.assertEqual((c.SNOWLINE_MIN_CLEAR_FRACTION, c.SNOWLINE_MIN_SNOW_FRACTION), (0.1, 0.1))
        self.assertEqual((c.SNOWLINE_LOWER_BANDS, c.SNOW_TOTAL_MIN_FRACTION), (2, 0.001))

    def test_snow_needs_both_ndsi_and_red(self) -> None:
        self.assertEqual(self.classes_for(0.41, 0.21), c.SNOW)
        self.assertEqual(self.classes_for(0.39, 0.5), c.NO_SNOW)
        self.assertEqual(self.classes_for(0.8, 0.19), c.NO_SNOW)

    def test_bare_pixel_is_no_snow_with_high_confidence(self) -> None:
        result = c.classify(scene())
        self.assertEqual(int(result.classes[0, 0]), c.NO_SNOW)
        self.assertEqual(int(result.confidence[0, 0]), c.CONFIDENCE_HIGH)
        self.assertEqual(int(result.flags[0, 0]), 0)


def field(scl: np.ndarray, snow: np.ndarray) -> c.Scene:
    """A 2-D scene with the given SCL classes; pixels where `snow` is True look like bright snow."""
    shape = scl.shape
    g, r, s = reflectance_for(0.7, 0.6)
    green = np.where(snow, g, 0.1).astype("float32")
    red = np.where(snow, r, 0.1).astype("float32")
    swir = np.where(snow, s, 0.2).astype("float32")
    return c.Scene(
        green=green,
        red=red,
        swir16=swir,
        scl=scl.astype("uint8"),
        elevation=np.full(shape, 2500.0, "float32"),
        terrain_shadow=np.zeros(shape, bool),
        forest=np.zeros(shape, bool),
        inside=np.ones(shape, bool),
    )


class CloudTest(unittest.TestCase):
    def test_every_cloud_class_is_cloud(self) -> None:
        result = c.classify(scene(scl=[3, 8, 9, 10]))
        self.assertTrue((result.classes == c.CLOUD).all())
        self.assertTrue((result.confidence == c.CONFIDENCE_NONE).all())

    def test_medium_cloud_patch_inside_clear_snow_is_snow(self) -> None:
        scl = np.full((9, 9), 11)
        scl[3:6, 3:6] = 8
        result = c.classify(field(scl, np.ones((9, 9), bool)))
        self.assertTrue((result.classes == c.SNOW).all())
        self.assertTrue((result.flags[3:6, 3:6] & c.FLAG_BRIGHT_SNOW > 0).all())
        self.assertFalse((result.flags[0] & c.FLAG_BRIGHT_SNOW).any())

    def test_medium_cloud_patch_joined_to_sure_cloud_stays_cloud(self) -> None:
        for sure in (9, 10, 0, 1):
            scl = np.full((9, 9), 11)
            scl[3:6, 3:6] = 8
            scl[6, 6] = sure  # touches the patch on a diagonal
            result = c.classify(field(scl, np.ones((9, 9), bool)))
            self.assertTrue((result.classes[3:6, 3:6] == c.CLOUD).all(), sure)

    def test_the_join_may_run_through_medium_cloud_that_is_not_snow(self) -> None:
        scl = np.full((9, 12), 11)
        scl[3:6, 2:9] = 8
        scl[4, 9] = 9
        snow = np.ones((9, 12), bool)
        snow[3:6, 6:9] = False  # the part of the patch next to the core fails the snow test
        result = c.classify(field(scl, snow))
        self.assertTrue((result.classes[3:6, 2:6] == c.CLOUD).all())

    def test_medium_cloud_patch_on_the_grid_edge_stays_cloud(self) -> None:
        scl = np.full((9, 9), 11)
        scl[0:3, 3:6] = 8
        result = c.classify(field(scl, np.ones((9, 9), bool)))
        self.assertTrue((result.classes[0:3, 3:6] == c.CLOUD).all())

    def test_kept_patch_must_pass_the_snow_test(self) -> None:
        scl = np.full((9, 9), 11)
        scl[3:6, 3:6] = 8
        snow = np.ones((9, 9), bool)
        snow[4, 4] = False
        result = c.classify(field(scl, snow))
        self.assertEqual(int(result.classes[4, 4]), c.CLOUD)
        self.assertEqual(int(result.classes[3, 3]), c.SNOW)

    def test_cloud_shadow_and_sure_cloud_are_never_turned_into_snow(self) -> None:
        scl = np.full((9, 9), 11)
        scl[2, 2], scl[4, 4], scl[6, 6] = 3, 9, 10
        result = c.classify(field(scl, np.ones((9, 9), bool)))
        self.assertEqual([int(result.classes[i, i]) for i in (2, 4, 6)], [c.CLOUD] * 3)


class UnknownAndFlagsTest(unittest.TestCase):
    def test_no_data_inside_the_domain_is_unknown(self) -> None:
        result = c.classify(scene(green=[np.nan, 0.1, 0.1], scl=[5, 0, 1]))
        self.assertTrue((result.classes == c.UNKNOWN).all())

    def test_outside_the_domain_is_nodata_in_every_band(self) -> None:
        result = c.classify(scene(inside=[False]))
        for band in (result.classes, result.confidence, result.flags):
            self.assertEqual(int(band[0, 0]), c.NODATA)

    def test_terrain_shadow_is_unknown_unless_snow_is_seen(self) -> None:
        g, r, s = reflectance_for(0.7, 0.3)
        result = c.classify(
            scene(green=[0.1, g], red=[0.1, r], swir16=[0.2, s], terrain_shadow=[True, True])
        )
        self.assertEqual(result.classes[0].tolist(), [c.UNKNOWN, c.SNOW])
        self.assertTrue((result.flags[0] & c.FLAG_TERRAIN_SHADOW > 0).all())

    def test_cloud_wins_over_terrain_shadow(self) -> None:
        result = c.classify(scene(scl=[9], terrain_shadow=[True]))
        self.assertEqual(int(result.classes[0, 0]), c.CLOUD)

    def test_forest_lowers_confidence_of_snow_and_no_snow(self) -> None:
        g, r, s = reflectance_for(0.7, 0.3)
        result = c.classify(scene(green=[0.1, g], red=[0.1, r], swir16=[0.2, s], forest=[True, True]))
        self.assertEqual(result.classes[0].tolist(), [c.NO_SNOW, c.SNOW])
        self.assertTrue((result.confidence == c.CONFIDENCE_LOW).all())
        self.assertTrue((result.flags[0] & c.FLAG_FOREST > 0).all())


class SnowlineTest(unittest.TestCase):
    def test_pass_two_runs_only_above_the_snowline(self) -> None:
        # 100 pixels per 100 m band from 1000 to 2900 m; pass-1 snow on every pixel from 2000 m up,
        # so the snowline is 2000 - 2 * 100 = 1800 m.
        elevation = np.repeat(np.arange(1000.0, 3000.0, 100.0) + 50, 100)
        n = elevation.size
        green, red, swir = (np.full(n, v, "float32") for v in (0.1, 0.1, 0.2))
        snow = elevation >= 2000
        g1, r1, s1 = reflectance_for(0.7, 0.5)
        green[snow], red[snow], swir[snow] = g1, r1, s1
        # A pass-2 pixel (NDSI 0.2, red 0.05) in the 1800 m band and one in the 1700 m band.
        g2, r2, s2 = reflectance_for(0.2, 0.05)
        at_1850, at_1750 = int(np.argmax(elevation == 1850)), int(np.argmax(elevation == 1750))
        for i in (at_1850, at_1750):
            green[i], red[i], swir[i] = g2, r2, s2
        result = c.classify(scene(green=green, red=red, swir16=swir, elevation=elevation))
        self.assertEqual(result.snowline_m, 1800.0)
        self.assertEqual(int(result.classes[0, at_1850]), c.SNOW)
        self.assertTrue(result.flags[0, at_1850] & c.FLAG_PASS2)
        self.assertEqual(int(result.classes[0, at_1750]), c.NO_SNOW)

    def test_no_snowline_when_pass_one_finds_almost_no_snow(self) -> None:
        # 25 clear pixels at 1500 m and 1975 cloudy ones at 2500 m: 2000 pixels in the domain.
        elevation = np.where(np.arange(2000) < 25, 1550.0, 2550.0)
        clear = elevation < 2000
        snow = np.zeros(2000, bool)
        snow[:2] = True  # 0.1% of the domain, not more
        self.assertIsNone(c.snowline(elevation, snow, clear, np.ones(2000, bool)))
        snow[:3] = True  # 12% of the clear 1500 m band
        self.assertEqual(c.snowline(elevation, snow, clear, np.ones(2000, bool)), 1300.0)

    def test_bands_with_too_few_clear_pixels_are_skipped(self) -> None:
        elevation = np.repeat([1050.0, 1150.0, 1250.0], 100)
        snow = np.zeros(300, bool)
        clear = np.ones(300, bool)
        clear[:95] = False  # the 1000 m band is 5% clear
        snow[95:100] = True  # and all of its clear pixels are snow
        snow[250:] = True  # half of the 1200 m band is snow
        self.assertEqual(c.snowline(elevation, snow, clear, np.ones(300, bool)), 1000.0)
        snow[250:] = False
        snow[150:160] = True  # 10% of the 1100 m band: not more than 10%
        self.assertIsNone(c.snowline(elevation, snow & (elevation < 1200), clear, np.ones(300, bool)))


if __name__ == "__main__":
    unittest.main()
