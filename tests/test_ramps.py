import json
import re
import unittest
from pathlib import Path

import numpy as np

from pipelines.catalog.layers import LAYERS
from pipelines.ramps import RAMP_OF_LAYER, RAMPS_JSON, colour_classes, colour_values, ramps

ROOT = Path(__file__).resolve().parents[1]


def hex_rgb(value: str) -> list[int]:
    number = int(value[1:], 16)
    return [number >> 16, (number >> 8) & 255, number & 255]


class ColourValuesTest(unittest.TestCase):
    def test_every_class_gets_its_colour_and_alpha_at_both_bounds(self) -> None:
        for ramp_id in ("swe", "snow_depth", "snow_cover_probability"):
            for cls in ramps()[ramp_id]["classes"]:
                probes = [cls["min"]]
                if cls["max"] is not None:
                    # Just under the exclusive upper bound still belongs to the class.
                    probes.append(np.nextafter(cls["max"], -np.inf))
                rgba = colour_values(np.array(probes), ramp_id)
                for pixel in rgba:
                    if cls["color"] is None:
                        self.assertEqual(pixel[3], 0, (ramp_id, cls))
                    else:
                        self.assertEqual(pixel[:3].tolist(), hex_rgb(cls["color"]), (ramp_id, cls))
                        self.assertEqual(pixel[3], round(cls["alpha"] * 255), (ramp_id, cls))

    def test_swe_under_5_mm_nan_and_negative_are_transparent(self) -> None:
        rgba = colour_values(np.array([np.nan, -1.0, 0.0, 4.99, 5.0]), "swe")
        self.assertEqual(rgba[:, 3].tolist()[:4], [0, 0, 0, 0])
        self.assertGreater(rgba[4, 3], 0)

    def test_open_last_class_covers_any_larger_value(self) -> None:
        top = ramps()["swe"]["classes"][-1]
        rgba = colour_values(np.array([1e6]), "swe")
        self.assertEqual(rgba[0, :3].tolist(), hex_rgb(top["color"]))

    def test_refuses_the_wrong_kind_of_ramp(self) -> None:
        with self.assertRaises(ValueError):
            colour_values(np.zeros(2), "snow_cover_observed")
        with self.assertRaises(ValueError):
            colour_classes(np.array(["snow"]), "swe")


class ColourClassesTest(unittest.TestCase):
    def test_classes_fill_with_their_colour_and_transparent_ones_stay_clear(self) -> None:
        classes = {cls["key"]: cls for cls in ramps()["snow_cover_observed"]["classes"]}
        rgba = colour_classes(np.array([["snow", "snow_low_confidence", "no_snow", ""]]), "snow_cover_observed")
        self.assertEqual(rgba[0, 0, :3].tolist(), hex_rgb(classes["snow"]["color"]))
        self.assertEqual(rgba[0, 0, 3], round(classes["snow"]["alpha"] * 255))
        self.assertEqual(rgba[0, 1, :3].tolist(), hex_rgb(classes["snow_low_confidence"]["color"]))
        self.assertEqual(rgba[0, 2, 3], 0)
        self.assertEqual(rgba[0, 3, 3], 0)

    def test_cloud_gets_its_fill_and_dots_unknown_only_its_hatch(self) -> None:
        classes = {cls["key"]: cls for cls in ramps()["snow_cover_observed"]["classes"]}
        cloud = colour_classes(np.full((12, 12), "cloud"), "snow_cover_observed")
        colours = {tuple(p) for p in cloud.reshape(-1, 4)[:, :3].tolist()}
        expected = {tuple(hex_rgb(classes["cloud"]["color"])), tuple(hex_rgb(classes["cloud"]["pattern"]["color"]))}
        self.assertEqual(colours, expected)
        unknown = colour_classes(np.full((12, 12), "unknown"), "snow_cover_observed")
        hatch = unknown[..., 3] > 0
        self.assertTrue(0 < hatch.mean() < 0.5)
        self.assertEqual(unknown[hatch][0, :3].tolist(), hex_rgb(classes["unknown"]["pattern"]["color"]))
        # 45 degree hatch: a pixel and its down-left neighbour are on the same line.
        rows, cols = np.nonzero(hatch)
        self.assertTrue(all(hatch[r + 1, c - 1] for r, c in zip(rows, cols) if r + 1 < 12 and c >= 1))

    def test_a_key_the_ramp_does_not_define_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            colour_classes(np.array(["snow", "water"]), "snow_cover_observed")


class SharedMappingTest(unittest.TestCase):
    def test_every_catalogue_layer_but_true_colour_has_a_ramp(self) -> None:
        self.assertEqual(set(RAMP_OF_LAYER), set(LAYERS) - {"rgb"})
        for ramp_id in RAMP_OF_LAYER.values():
            self.assertIn(ramp_id, ramps())

    def test_ramp_coloured_layers_are_tiled_without_blending_classes(self) -> None:
        # Bilinear tiling would mix two class colours into one the legend does not show.
        for layer_id in RAMP_OF_LAYER:
            self.assertEqual(LAYERS[layer_id].display_resampling, "nearest", layer_id)
        self.assertEqual(LAYERS["rgb"].display_resampling, "bilinear")

    def test_the_frontend_draws_each_layer_with_the_same_ramp(self) -> None:
        source = (ROOT / "frontend" / "src" / "lib" / "layers.ts").read_text(encoding="utf-8")
        pairs = dict(re.findall(r'id: "([a-z_]+)", copy: "[a-z_]+", ramp: "([a-z_]+)"', source))
        self.assertEqual(pairs, RAMP_OF_LAYER)

    def test_the_file_is_the_one_the_frontend_imports(self) -> None:
        source = (ROOT / "frontend" / "src" / "lib" / "layers.ts").read_text(encoding="utf-8")
        self.assertIn("docs/design/ramps.json", source)
        self.assertEqual(RAMPS_JSON, ROOT / "docs" / "design" / "ramps.json")
        self.assertIn("layers", json.loads(RAMPS_JSON.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
