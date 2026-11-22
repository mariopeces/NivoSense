import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from pipelines.s2.domain import Grid
from qa.reference import chips, layers, sample, strata

REFERENCE = Path(__file__).resolve().parents[2] / "qa" / "reference"


class IlluminationTest(unittest.TestCase):
    def test_flat_ground_gets_sine_of_sun_elevation(self):
        flat = np.full((5, 5), 1000.0)
        cos_i = strata.cos_incidence(flat, 20.0, 160.0, 30.0)
        self.assertAlmostEqual(float(cos_i[2, 2]), math.sin(math.radians(30.0)), places=6)

    def test_slope_facing_the_sun_is_brighter_than_one_facing_away(self):
        rows = np.arange(7, dtype="float64")[:, None] * np.ones((1, 7))
        south_facing = rows * 20.0 * -0.5  # falls towards the south (row index grows southwards)
        north_facing = -south_facing
        sun_south = strata.cos_incidence(south_facing, 20.0, 180.0, 30.0)[3, 3]
        sun_away = strata.cos_incidence(north_facing, 20.0, 180.0, 30.0)[3, 3]
        self.assertGreater(sun_south, math.sin(math.radians(30.0)))
        self.assertLess(sun_away, math.sin(math.radians(30.0)))


class CastShadowTest(unittest.TestCase):
    def test_wall_shades_the_ground_on_the_far_side_up_to_its_shadow_length(self):
        ground = np.zeros((3, 40))
        ground[:, 30] = 100.0  # 100 m wall; sun due east at 45 degrees casts 100 m = 5 pixels west
        shadow = strata.cast_shadow(ground, 20.0, 90.0, 45.0, max_distance=1000.0)
        self.assertTrue(shadow[1, 26:30].all())
        self.assertFalse(shadow[1, 20:25].any())
        self.assertFalse(shadow[1, 31:].any())

    def test_no_shadow_on_flat_ground(self):
        self.assertFalse(strata.cast_shadow(np.zeros((10, 10)), 20.0, 135.0, 20.0).any())


class StrataTest(unittest.TestCase):
    def test_boundary_zone_covers_both_sides_within_the_distance(self):
        cloud = np.zeros((1, 20), dtype=bool)
        cloud[0, 10:] = True
        zone = strata.boundary_zone(cloud, ~cloud, 3)
        self.assertEqual(np.flatnonzero(zone[0]).tolist(), list(range(7, 13)))

    def test_open_terrain_excludes_every_other_stratum(self):
        shape = (4, 4)
        layer = strata.Layers(
            elevation=np.full(shape, 2000.0),
            cos_incidence=np.full(shape, 0.8),
            cast_shadow=np.zeros(shape, dtype=bool),
            tree_fraction=np.zeros(shape),
            cloud=np.zeros(shape, dtype=bool),
            clear=np.ones(shape, dtype=bool),
            eligible=np.ones(shape, dtype=bool),
        )
        self.assertTrue(strata.stratum_masks(layer, None)["open_terrain"].all())
        masks = strata.stratum_masks(layer, 2100.0)
        self.assertTrue(masks["snowline_band"].all())
        self.assertFalse(masks["open_terrain"].any())

    def test_split_quota_is_even_and_capped_by_cell_size(self):
        self.assertEqual(strata.split_quota(10, [100, 100, 0, 100]), [4, 3, 0, 3])
        self.assertEqual(strata.split_quota(10, [1, 100]), [1, 9])
        self.assertEqual(strata.split_quota(10, [2, 3]), [2, 3])

    def test_draw_respects_masks_quotas_spacing_and_seed(self):
        mask = np.zeros((100, 100), dtype=bool)
        mask[:50, :] = True
        masks = {name: np.zeros_like(mask) for name in strata.STRATA}
        masks["forest"] = mask
        bands = np.zeros(mask.shape, dtype="int8")
        draws = strata.draw_points(masks, bands, {"forest": 20}, np.random.default_rng(1), 20.0)
        again = strata.draw_points(masks, bands, {"forest": 20}, np.random.default_rng(1), 20.0)
        self.assertEqual(draws, again)
        self.assertEqual(len(draws), 20)
        self.assertTrue(all(mask[d.row, d.col] and d.stratum == "forest" for d in draws))
        for i, a in enumerate(draws):
            for b in draws[i + 1 :]:
                self.assertGreaterEqual(math.hypot(a.row - b.row, a.col - b.col) * 20.0, strata.MIN_SPACING_M)

    def test_elevation_bands(self):
        bands = strata.elevation_band(np.array([1000.0, 1500.0, 2499.0, 3400.0]))
        self.assertEqual([strata.band_name(int(b)) for b in bands], ["<1500", "1500-2000", "2000-2500", ">=2500"])


class SampleHelpersTest(unittest.TestCase):
    def test_single_tile_needs_all_four_cells_from_one_tile(self):
        source = np.array([[0, 0, 1, 1], [0, 0, 1, 0], [-1, -1, 2, 2], [-1, -1, 2, 2]], dtype="int8")
        self.assertEqual(sample.single_tile(source).tolist(), [[True, False], [False, True]])

    def test_crop_takes_the_domain_out_of_the_padded_grid(self):
        grid = Grid("EPSG:32630", 1000.0, 5000.0, 20.0, 3, 2)
        padded = layers.padded(grid, 40.0)
        values = np.arange(padded.height * padded.width).reshape(padded.height, padded.width)
        self.assertEqual(sample.crop(values, grid, padded).tolist(), values[2:4, 2:5].tolist())


class ReadAlignedTest(unittest.TestCase):
    def setUp(self):
        import rasterio
        from rasterio.transform import from_origin

        self.folder = tempfile.TemporaryDirectory()
        self.path = str(Path(self.folder.name) / "band.tif")
        self.values = np.arange(1, 8 * 8 + 1, dtype="uint16").reshape(8, 8)
        with rasterio.open(
            self.path,
            "w",
            driver="GTiff",
            width=8,
            height=8,
            count=1,
            dtype="uint16",
            crs="EPSG:32630",
            transform=from_origin(1000.0, 2000.0, 10.0, 10.0),
        ) as out:
            out.write(self.values, 1)

    def tearDown(self):
        self.folder.cleanup()

    def test_partial_overlap_is_zero_outside_the_tile(self):
        grid = Grid("EPSG:32630", 980.0, 2020.0, 10.0, 4, 4)
        out = layers.read_aligned(self.path, grid)
        self.assertEqual(out[:2].sum() + out[:, :2].sum(), 0)
        self.assertEqual(out[2:, 2:].tolist(), self.values[:2, :2].tolist())

    def test_two_times_upsampling_repeats_pixels(self):
        grid = Grid("EPSG:32630", 1000.0, 2000.0, 5.0, 4, 4)
        out = layers.read_aligned(self.path, grid)
        self.assertEqual(out.tolist(), self.values[:2, :2].repeat(2, 0).repeat(2, 1).tolist())

    def test_misaligned_grid_is_refused(self):
        with self.assertRaises(ValueError):
            layers.read_aligned(self.path, Grid("EPSG:32630", 1005.0, 2000.0, 10.0, 2, 2))


class ChipsTest(unittest.TestCase):
    def mosaic(self, size: int = 40) -> layers.L1CMosaic:
        band = np.zeros((size, size), dtype="float32")
        band[20:22, 20:22] = 1.0
        bands = {name: band.copy() for name in layers.L1C_BANDS}
        return layers.L1CMosaic(bands, np.zeros((size, size), dtype="int8"), ("tile",))

    def test_stretch_is_fixed_square_root(self):
        self.assertEqual(chips.stretch(np.array([0.0, 0.25, 1.0, 2.0, np.nan])).tolist(), [0, 128, 255, 255, 0])

    def test_point_sits_inside_the_marks_at_the_panel_centre(self):
        grid = Grid("EPSG:32630", 0.0, 400.0, 10.0, 40, 40)
        row, col = chips.mosaic_cell(210.0, 190.0, grid)  # centre of the 20 m pixel over cells 20-21
        self.assertEqual((row, col), (20, 20))
        zoom = chips.point_panels(self.mosaic(), row, col)[0]
        half = chips.ZOOM_PX // 2 - 1
        centre = zoom[half * chips.SCALE : (half + 2) * chips.SCALE, half * chips.SCALE : (half + 2) * chips.SCALE]
        self.assertTrue((centre == 255).all())
        self.assertEqual(tuple(zoom[half * chips.SCALE - 2, half * chips.SCALE - 2]), chips.MARK)

    def test_agreement_excludes_unsure_on_either_side(self):
        points = [
            {"properties": {"id": "a", "label": "snow", "stratum": "forest"}},
            {"properties": {"id": "b", "label": "unsure", "stratum": "forest"}},
            {"properties": {"id": "c", "label": "cloud", "stratum": "cloud_edge"}},
            {"properties": {"id": "d", "label": "no_snow", "stratum": "cloud_edge"}},
        ]
        result = chips.agreement(points, {"a": "snow", "b": "snow", "c": "snow", "d": "unsure"})
        self.assertEqual((result["compared"], result["agreed"]), (2, 1))
        self.assertEqual(result["per_stratum"]["cloud_edge"]["agreement"], 0.0)
        with self.assertRaises(ValueError):
            chips.agreement(points, {"zz": "snow"})

    def test_blind_subset_is_ten_percent_and_reproducible(self):
        points = [{"properties": {"id": str(i)}} for i in range(1000)]
        subset = chips.blind_subset(points)
        self.assertEqual(len(subset), 100)
        self.assertEqual(subset, chips.blind_subset(points))


class FrozenSampleTest(unittest.TestCase):
    def test_sample_matches_its_frozen_hash(self):
        sample_path = REFERENCE / "snow_points.geojson"
        expected = (REFERENCE / "snow_points.geojson.sha256").read_text(encoding="utf-8").split()[0]
        self.assertEqual(hashlib.sha256(sample_path.read_bytes()).hexdigest(), expected)

    def test_sample_meets_the_card(self):
        collection = json.loads((REFERENCE / "snow_points.geojson").read_text(encoding="utf-8"))
        points = [feature["properties"] for feature in collection["features"]]
        self.assertGreaterEqual(len(points), 1500)
        self.assertGreaterEqual(len({p["date"] for p in points}), 12)
        self.assertIn("2026-11-20", {p["date"] for p in points})
        self.assertEqual({p["stratum"] for p in points}, set(strata.STRATA))
        self.assertTrue({p["label"] for p in points} <= set(chips.LABELS))
        self.assertTrue(all(p["chip_scene_id"].endswith("_L1C") for p in points))
        self.assertEqual(len({p["id"] for p in points}), len(points))


if __name__ == "__main__":
    unittest.main()
