import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from qa import score_snow_reference as score

LEFT, TOP = 460000.0, 4100000.0


def point(label: str, stratum: str, row: int, col: int, day: str = "2026-01-12", **extra: object) -> dict:
    return {
        "date": day,
        "x": LEFT + col * 20 + 10,
        "y": TOP - row * 20 - 10,
        "stratum": stratum,
        "in_strata": extra.get("in_strata", [stratum]),
        "label": label,
        "scored": True,
    }


def write_classes(folder: Path, day: str, classes: np.ndarray) -> None:
    import rasterio
    from rasterio.transform import from_origin

    (folder / day).mkdir(parents=True)
    with rasterio.open(
        folder / day / "snow_obs.tif", "w", driver="GTiff", width=classes.shape[1], height=classes.shape[0],
        count=1, dtype="uint8", crs="EPSG:32630", transform=from_origin(LEFT, TOP, 20, 20), nodata=255,
    ) as dst:
        dst.write(classes, 1)


class ScoresTest(unittest.TestCase):
    def test_cloud_and_unknown_on_snow_count_as_misses(self) -> None:
        pairs = [("snow", "snow"), ("snow", "cloud"), ("snow", "unknown"), ("no_snow", "snow"), ("cloud", "snow"),
                 ("no_snow", "no_snow"), ("no_snow", "cloud")]
        result = score.scores(pairs)
        self.assertEqual((result["tp"], result["fp"], result["fn"]), (1, 2, 2))
        self.assertEqual(result["f1"], round(2 / 6, 4))
        # Where both see the ground: (snow, snow), (no_snow, snow), (no_snow, no_snow).
        self.assertEqual(result["f1_where_observed"], round(2 / 3, 4))
        self.assertEqual(result["clear_points_observed"], round(3 / 6, 4))
        self.assertEqual(result["matrix"]["snow"]["cloud"], 1)

    def test_no_snow_anywhere_gives_no_f1(self) -> None:
        self.assertIsNone(score.scores([("no_snow", "no_snow")])["f1"])


class ReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        classes = np.zeros((10, 10), dtype="uint8")
        classes[:, 5:] = 1  # snow in the east half
        classes[0] = 2  # cloud on the top row
        write_classes(self.folder, "2026-01-12", classes)

    def test_reads_each_point_from_its_pixel(self) -> None:
        points = [
            point("snow", "forest", 5, 7),
            point("no_snow", "forest", 5, 2),
            point("snow", "open_terrain", 0, 7),
            point("snow", "open_terrain", 5, 6, in_strata=["open_terrain", "forest"]),
        ]
        predicted = score.sample(self.folder, points)
        self.assertEqual(predicted, ["snow", "no_snow", "cloud", "snow"])
        result = score.report(points, predicted)
        self.assertEqual(result["by_stratum"]["forest"]["f1"], 1.0)
        self.assertEqual(result["by_stratum"]["open_terrain"]["f1"], round(2 / 3, 4))
        self.assertEqual(result["by_in_strata"]["forest"]["points"], 3)
        self.assertFalse(result["ok"])
        self.assertIn("open_terrain snow F1 0.6667 < 0.7", result["failures"])

    def test_point_outside_the_raster_is_nodata(self) -> None:
        self.assertEqual(score.sample(self.folder, [point("snow", "forest", 50, 50)]), ["nodata"])

    def test_missing_date_is_an_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            score.sample(self.folder, [point("snow", "forest", 1, 1, day="2026-02-21")])

    def test_cli_writes_the_report_and_exits_by_the_thresholds(self) -> None:
        reference = self.folder / "ref.geojson"
        features = [{"type": "Feature", "geometry": None, "properties": p} for p in (
            point("snow", "forest", 5, 7), point("no_snow", "forest", 5, 2),
            dict(point("snow", "forest", 5, 2), scored=False, label="unsure"),
        )]
        reference.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
        out = self.folder / "report.json"
        args = ["--snow-obs", str(self.folder), "--reference", str(reference), "--out", str(out)]
        self.assertEqual(score.main(args), 0)
        self.assertEqual(json.loads(out.read_text())["overall"]["points"], 2)


if __name__ == "__main__":
    unittest.main()
