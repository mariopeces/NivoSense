import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from pipelines.s2.domain import Grid
from qa.reference import chips, layers, sample, score, strata

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

    def test_second_draw_keeps_its_distance_from_the_first(self):
        masks = {name: np.zeros((60, 60), dtype=bool) for name in strata.STRATA}
        masks["forest"][:, :] = True
        bands = np.zeros((60, 60), dtype="int8")
        earlier = [(30, 30)]
        draws = strata.draw_points(masks, bands, {"forest": 5}, np.random.default_rng(3), 20.0, taken=earlier)
        self.assertEqual(len(draws), 5)
        self.assertTrue(all(math.hypot(d.row - 30, d.col - 30) * 20.0 >= strata.MIN_SPACING_M for d in draws))
        self.assertEqual(earlier, [(30, 30)])

    def test_elevation_bands(self):
        bands = strata.elevation_band(np.array([1000.0, 1500.0, 2499.0, 3400.0]))
        self.assertEqual([strata.band_name(int(b)) for b in bands], ["<1500", "1500-2000", "2000-2500", ">=2500"])


class SampleHelpersTest(unittest.TestCase):
    def test_grid_cell_of_a_pixel_centre(self):
        grid = Grid("EPSG:32630", 1000.0, 5000.0, 20.0, 3, 2)
        self.assertEqual(sample.grid_cell(1050.0, 4970.0, grid), (1, 2))

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


def synthetic_sample() -> dict:
    """One date with a snowline at 2,400 m; draw 2 samples forest above it."""

    def point(point_id, draw, in_strata, elevation, label):
        properties = {
            "id": point_id,
            "draw": draw,
            "date": "2026-01-01",
            "stratum": in_strata[0],
            "in_strata": in_strata,
            "elevation_band": ">=2500" if elevation >= 2500 else "2000-2500",
            "elevation_m": elevation,
            "label": label,
            "scored": label != "unsure",
        }
        return {"type": "Feature", "geometry": None, "properties": properties}

    def cell(draw, stratum, band, pixels, points):
        return {
            "draw": draw,
            "date": "2026-01-01",
            "stratum": stratum,
            "elevation_band": band,
            "pixels": pixels,
            "points": points,
        }

    return {
        "type": "FeatureCollection",
        "metadata": {
            "dates": [{"date": "2026-01-01", "snowline_m": 2400.0}],
            "supplements": {"2": {"above_snowline_m": 0.0}},
            "cells": [
                {
                    "draw": 1,
                    "date": "2026-01-01",
                    "stratum": "forest",
                    "elevation_band": "2000-2500",
                    "pixels": 800,
                    "points": 1,
                },
                {
                    "draw": 1,
                    "date": "2026-01-01",
                    "stratum": "forest",
                    "elevation_band": ">=2500",
                    "pixels": 200,
                    "points": 1,
                },
                {
                    "draw": 2,
                    "date": "2026-01-01",
                    "stratum": "forest",
                    "elevation_band": ">=2500",
                    "pixels": 200,
                    "points": 3,
                },
                {
                    "draw": 1,
                    "date": "2026-01-01",
                    "stratum": "open_terrain",
                    "elevation_band": ">=2500",
                    "pixels": 400,
                    "points": 1,
                },
            ],
        },
        "features": [
            point("a", 1, ["forest"], 2100.0, "no_snow"),
            point("b", 1, ["forest"], 2600.0, "snow"),
            point("c", 2, ["forest"], 2700.0, "snow"),
            point("d", 2, ["forest"], 2650.0, "unsure"),
            point("e", 2, ["forest", "open_terrain"], 2800.0, "cloud"),
        ],
    }


class ScoreTest(unittest.TestCase):
    def test_inclusion_probability_sums_every_draw_and_stratum_the_pixel_is_in(self):
        probabilities = score.inclusion_probabilities(synthetic_sample())
        self.assertAlmostEqual(probabilities["a"], 1 / 800)
        self.assertAlmostEqual(probabilities["b"], 1 / 200 + 3 / 200)
        self.assertAlmostEqual(probabilities["c"], 1 / 200 + 3 / 200)
        self.assertAlmostEqual(probabilities["e"], 1 / 200 + 3 / 200 + 1 / 400)

    def test_point_below_the_snowline_gets_no_share_of_the_later_draw(self):
        sample = synthetic_sample()
        sample["metadata"]["supplements"]["2"]["above_snowline_m"] = 250.0
        probabilities = score.inclusion_probabilities(sample)
        self.assertAlmostEqual(probabilities["b"], 1 / 200)
        self.assertAlmostEqual(probabilities["c"], 1 / 200 + 3 / 200)

    def test_point_outside_every_cell_is_refused(self):
        sample = synthetic_sample()
        sample["metadata"]["cells"] = [c for c in sample["metadata"]["cells"] if c["elevation_band"] != "2000-2500"]
        with self.assertRaises(ValueError):
            score.inclusion_probabilities(sample)

    def test_weighted_confusion_and_snow_f1(self):
        sample = synthetic_sample()
        weight = score.weights(sample)
        points = score.scored_points(sample)
        self.assertEqual([p["id"] for p in points], ["a", "b", "c", "e"])
        predicted = {"a": "snow", "b": "snow", "c": "unknown", "e": "no_snow"}
        matrix = score.confusion(points, predicted, weight)
        self.assertAlmostEqual(matrix["no_snow"]["snow"], 800.0)
        self.assertAlmostEqual(matrix["snow"]["snow"], 50.0)
        self.assertAlmostEqual(matrix["snow"]["unknown"], 50.0)
        result = score.snow_f1(matrix)
        self.assertAlmostEqual(result["precision"], 50 / 850)
        self.assertAlmostEqual(result["recall"], 0.5)
        self.assertAlmostEqual(result["f1"], 100 / 950)
        self.assertAlmostEqual(score.snow_f1(score.confusion(points, predicted))["f1"], 2 / 4)

    def test_missing_prediction_is_refused(self):
        sample = synthetic_sample()
        with self.assertRaises(ValueError):
            score.confusion(score.scored_points(sample), {"a": "snow"})

    def test_report_scores_strata_by_membership(self):
        sample = synthetic_sample()
        predicted = {"a": "no_snow", "b": "snow", "c": "snow", "e": "cloud"}
        result = score.report(sample, predicted)
        self.assertEqual(result["open_terrain"]["weighted"]["points"], 1)
        self.assertEqual(result["forest"]["weighted"]["f1"], 1.0)
        self.assertEqual(result["forest"]["unsure_share"], 0.2)
        self.assertEqual(result["overall"]["per_draw_unweighted"]["2"]["points"], 2)

    def test_weighting_lowers_the_oversampled_snow_share(self):
        rows = {row["stratum"]: row for row in score.prevalence(synthetic_sample())}
        self.assertEqual(rows["forest"]["pooled unweighted"], 0.5)
        self.assertAlmostEqual(
            rows["forest"]["pooled weighted"], 100 / (800 + 50 + 50 + 1 / (1 / 200 + 3 / 200 + 1 / 400)), places=4
        )


FROZEN_SHA256 = "a6f2586b23df03de6b1effffaec9c55ea49a4e15d859f6323c7c2407c0d9372e"


class FrozenSampleTest(unittest.TestCase):
    def setUp(self):
        self.path = REFERENCE / "snow_points.geojson"
        self.collection = json.loads(self.path.read_text(encoding="utf-8"))
        self.points = [feature["properties"] for feature in self.collection["features"]]

    def test_sample_matches_its_frozen_hash(self):
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), FROZEN_SHA256)

    def test_sample_meets_the_card(self):
        points = self.points
        scored = [p for p in points if p["scored"]]
        self.assertTrue(all(p["scored"] == (p["label"] != "unsure") for p in points))
        self.assertGreaterEqual(len(scored), 1500)
        self.assertGreaterEqual(len({p["date"] for p in scored}), 12)
        self.assertIn("2026-11-20", {p["date"] for p in scored})
        self.assertEqual({p["stratum"] for p in scored}, set(strata.STRATA))
        self.assertTrue({p["label"] for p in points} <= set(chips.LABELS))
        self.assertTrue({p["draw"] for p in points} <= {1, *sample.SUPPLEMENTS})
        self.assertTrue(all(p["chip_scene_id"].endswith("_L1C") for p in points))
        self.assertEqual(len({p["id"] for p in points}), len(points))

    def test_forest_and_cloud_edge_hold_100_scored_snow_points(self):
        for name in ("forest", "cloud_edge"):
            snow = [p for p in self.points if p["stratum"] == name and p["label"] == "snow"]
            self.assertGreaterEqual(len(snow), 100, name)

    def test_stored_weights_are_the_inverse_inclusion_probabilities(self):
        probabilities = score.inclusion_probabilities(self.collection)
        for point in self.points:
            self.assertAlmostEqual(point["inclusion_probability"], probabilities[point["id"]], places=7)
            self.assertAlmostEqual(point["weight"], 1 / probabilities[point["id"]], delta=0.001)


if __name__ == "__main__":
    unittest.main()
