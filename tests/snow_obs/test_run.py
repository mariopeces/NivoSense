import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from pipelines.catalog import LocalStorage
from pipelines.snow_obs import classify as c
from pipelines.snow_obs import run

# A 0.01 x 0.006 degree box near Pradollano, about 45 x 34 pixels at 20 m.
DOMAIN = {
    "type": "Polygon",
    "coordinates": [[[-3.40, 37.09], [-3.39, 37.09], [-3.39, 37.096], [-3.40, 37.096], [-3.40, 37.09]]],
}
SCENES = ["S2A_T30SVF_20261120T110610_L2A", "S2A_T30SVG_20261120T110610_L2A"]


def record(day: str = "2026-11-20", orbit: str = "R094", **overrides: object) -> dict:
    base = {
        "date": day,
        "orbit": orbit,
        "datatake": "GS2A_20261120T110301_059608",
        "scene_ids": SCENES,
        "processing_baselines": ["05.13", "05.13"],
        "input_key": "k",
        "complete": True,
        "listed": True,
        "domain_valid_fraction": 0.9,
        "domain_coverage": 1.0,
    }
    base.update(overrides)
    return base


def fake_fetch(request: object) -> dict:
    return {"properties": {"view:sun_azimuth": 166.0, "view:sun_elevation": 32.0}}


def write_pass(
    folder: Path, grid: object, green: np.ndarray, red: np.ndarray, swir: np.ndarray, scl: np.ndarray
) -> None:
    import rasterio

    folder.mkdir(parents=True)
    profile = {"driver": "GTiff", "width": grid.width, "height": grid.height, "crs": grid.crs,
               "transform": grid.transform}
    with rasterio.open(folder / "reflectance.tif", "w", count=3, dtype="float32", nodata=float("nan"),
                       **profile) as target:
        for band, (name, array) in enumerate(zip(("green", "red", "swir16"), (green, red, swir)), start=1):
            target.write(array.astype("float32"), band)
            target.set_band_description(band, name)
    with rasterio.open(folder / "classes.tif", "w", count=2, dtype="uint8", **profile) as target:
        target.write(scl.astype("uint8"), 1)
        target.write(np.zeros_like(scl, dtype="uint8"), 2)
    (folder / "record.json").write_text(json.dumps(record()))


class PickRecordTest(unittest.TestCase):
    def test_picks_the_complete_pass_with_most_valid_domain(self) -> None:
        chosen = run.pick_record([
            record(orbit="R051", domain_valid_fraction=0.95, complete=False),
            record(orbit="R094", domain_valid_fraction=0.5),
            record(orbit="R008", domain_valid_fraction=0.4),
        ])
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["orbit"], "R094")

    def test_no_complete_pass_gives_none(self) -> None:
        self.assertIsNone(run.pick_record([record(complete=False)]))
        self.assertIsNone(run.pick_record([]))


class SunAnglesTest(unittest.TestCase):
    def test_mean_of_the_granules_from_their_stac_items(self) -> None:
        urls = []
        answers = iter([(160.0, 30.0), (170.0, 34.0)])

        def fetch(request: object) -> dict:
            urls.append(request.full_url)  # type: ignore[attr-defined]
            azimuth, elevation = next(answers)
            return {"properties": {"view:sun_azimuth": azimuth, "view:sun_elevation": elevation}}

        self.assertEqual(run.sun_angles(SCENES, fetch), (165.0, 32.0))
        self.assertTrue(urls[0].endswith("/collections/sentinel-2-c1-l2a/items/S2A_T30SVF_20261120T110610_L2A"))


class DisplayTest(unittest.TestCase):
    def test_colours_follow_the_design_ramp(self) -> None:
        classes = np.array([[c.SNOW, c.SNOW, c.NO_SNOW, c.CLOUD, c.UNKNOWN, c.NODATA]], "uint8")
        confidence = np.array([[2, 1, 2, 0, 0, 255]], "uint8")
        rgba = run.display_rgba(c.Classification(classes, confidence, np.zeros_like(classes), None))
        self.assertEqual(tuple(rgba[:, 0, 0]), run.SNOW_RGBA)
        self.assertEqual(tuple(rgba[:, 0, 1]), run.SNOW_LOW_CONFIDENCE_RGBA)
        self.assertEqual(int(rgba[3, 0, 2]), 0)
        self.assertEqual(tuple(rgba[:, 0, 3]), run.CLOUD_DOT_RGBA)  # (0, 3) is on the dot lattice
        self.assertEqual(int(rgba[3, 0, 5]), 0)

    def test_unknown_is_a_hatch_and_cloud_is_filled(self) -> None:
        classes = np.full((6, 6), c.UNKNOWN, "uint8")
        rgba = run.display_rgba(c.Classification(classes, np.zeros_like(classes), np.zeros_like(classes), None))
        drawn = rgba[3] > 0
        self.assertEqual(int(drawn.sum()), 12)
        self.assertTrue(drawn[0, 0] and drawn[1, 2] and not drawn[0, 1])
        classes[:] = c.CLOUD
        rgba = run.display_rgba(c.Classification(classes, np.zeros_like(classes), np.zeros_like(classes), None))
        self.assertTrue((rgba[3] > 0).all())


class RunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.domain_path = self.tmp / "domain.geojson"
        self.domain_path.write_text(json.dumps(DOMAIN))
        from pipelines.s2.domain import load_domain

        self.domain = load_domain(self.domain_path)
        shape = self.domain.mask.shape
        self.elevation = np.full(shape, 2500.0, "float32")
        self.forest = np.zeros(shape, bool)
        self.forest[:, :5] = True
        green = np.full(shape, 0.10)
        red = np.full(shape, 0.10)
        swir = np.full(shape, 0.20)
        green[:, 20:], red[:, 20:], swir[:, 20:] = 0.8, 0.7, 0.1  # snow in the east half
        scl = np.full(shape, 5)
        scl[:3] = 9  # cloud on the top rows
        write_pass(self.tmp / "s2" / "2026-11-20" / "R094", self.domain.grid, green, red, swir, scl)
        static = mock.patch.object(run, "load_static", return_value=(self.elevation, self.forest))
        static.start()
        self.addCleanup(static.stop)

    def test_writes_classes_display_and_summary(self) -> None:
        import rasterio

        out = self.tmp / "out"
        day = run.date(2026, 11, 20)
        summaries = run.run(self.domain_path, self.tmp / "s2", day, day, out, fetch=fake_fetch)
        self.assertEqual(len(summaries), 1)
        summary = summaries[0]
        with rasterio.open(out / "2026-11-20" / "snow_obs.tif") as src:
            self.assertEqual(src.count, 3)
            self.assertEqual(src.nodata, c.NODATA)
            self.assertEqual(src.crs.to_string(), "EPSG:32630")
            classes, confidence, flags = src.read()
        inside = self.domain.mask
        self.assertTrue((classes[~inside] == c.NODATA).all())
        self.assertTrue((classes[:3][inside[:3]] == c.CLOUD).all())
        self.assertTrue((classes[3:, 20:][inside[3:, 20:]] == c.SNOW).all())
        self.assertTrue((classes[3:, 5:20][inside[3:, 5:20]] == c.NO_SNOW).all())
        self.assertTrue((confidence[3:, :5][inside[3:, :5]] == c.CONFIDENCE_LOW).all())
        self.assertEqual(summary["counts"]["snow"], int((classes == c.SNOW).sum()))
        self.assertEqual(summary["sun_azimuth_deg"], 166.0)
        self.assertTrue(summary["published"])
        with rasterio.open(out / "2026-11-20" / "display.tif") as src:
            self.assertEqual((src.count, src.dtypes[0]), (4, "uint8"))

    def test_mostly_cloudy_date_is_not_published(self) -> None:
        import rasterio

        with rasterio.open(self.tmp / "s2" / "2026-11-20" / "R094" / "classes.tif", "r+") as dst:
            dst.write(np.full(self.domain.mask.shape, 9, "uint8"), 1)
        day = run.date(2026, 11, 20)
        summary = run.run(self.domain_path, self.tmp / "s2", day, day, self.tmp / "out", fetch=fake_fetch)[0]
        self.assertFalse(summary["published"])
        self.assertEqual(summary["observed_fraction"], 0.0)

    def test_publishes_through_the_catalogue_and_is_idempotent(self) -> None:
        day = run.date(2026, 11, 20)
        with mock.patch.dict(os.environ, {"CATALOG_LOCAL_ROOT": str(self.tmp / "catalogue")}):
            first = run.run(self.domain_path, self.tmp / "s2", day, day, self.tmp / "a", target="staging",
                            version="test", fetch=fake_fetch)[0]
            second = run.run(self.domain_path, self.tmp / "s2", day, day, self.tmp / "b", target="staging",
                             version="test", fetch=fake_fetch)[0]
        self.assertEqual(first["entry"], second["entry"])
        written = json.loads((self.tmp / "b" / "2026-11-20" / "summary.json").read_text())
        self.assertEqual(written["entry"], second["entry"])
        storage = LocalStorage(self.tmp / "catalogue" / "staging")
        blob = storage.read("catalog/entries/snow_obs/2026-11-20.json")
        self.assertIsNotNone(blob)
        entry = json.loads(blob.data)  # type: ignore[union-attr]
        self.assertEqual(entry["bands"], ["class", "confidence", "flags"])
        self.assertEqual(entry["status"], "observed")
        self.assertEqual(entry["source_ids"], SCENES)
        self.assertEqual(entry["nodata"], 255.0)
        self.assertIn("observed_fraction", entry["qa"]["scores"])
        self.assertTrue(storage.exists(entry["cog"]) and storage.exists(entry["pmtiles"]))


if __name__ == "__main__":
    unittest.main()
