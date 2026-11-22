"""Tests of the QA harness on small catalogues built with publish() in a temporary folder.

The rasters come from tests/catalog/helpers.py: they exercise the plumbing only and are never published anywhere.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import transform_bounds

from pipelines.catalog import LocalStorage, publish, rebuild_index
from qa.__main__ import main
from qa.check_catalog import check_catalog, cog_problems
from qa.freshness import check_f2, freshness
from qa.objects import index_entries
from qa.regression import evaluate, load_fixtures
from qa.render_thumbs import render_thumbs
from tests.catalog.helpers import LEFT, TOP, meta, product, write_raster

DAILY = ("2026-11-01", "2026-11-02", "2026-11-03")


def build(folder: Path, dates: tuple[str, ...] = DAILY, layer: str = "snow_gapfill") -> LocalStorage:
    storage = LocalStorage(folder / "catalog")
    for seed, date in enumerate(dates):
        publish(layer, date, product(folder, f"{layer}-{date}", resolution=20, seed=seed), meta(), storage)
    rebuild_index(storage)
    return storage


def errors_of(report: dict[str, Any], check: str) -> list[dict[str, Any]]:
    return [error for error in report["errors"] if error["check"] == check]


class CatalogueTestCase(unittest.TestCase):
    """One published catalogue per class, copied for every test so each test can break its own copy."""

    template: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.template = Path(cls._tmp.name) / "template"
        build(cls.template)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def setUp(self) -> None:
        self._case = tempfile.TemporaryDirectory()
        self.addCleanup(self._case.cleanup)
        shutil.copytree(self.template / "catalog", Path(self._case.name) / "catalog")
        self.storage = LocalStorage(Path(self._case.name) / "catalog")
        self.entries = index_entries(self.storage)["snow_gapfill"]

    def cog_path(self, index: int = 0) -> Path:
        return self.storage.root / self.entries[index]["cog"]


class CheckCatalogTests(CatalogueTestCase):
    def test_a_published_catalogue_passes(self) -> None:
        report = check_catalog(self.storage)
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["ok"])
        self.assertEqual(report["entries_checked"], 3)
        self.assertEqual(report["layers"]["snow_gapfill"]["missing_days"], [])

    def test_a_missing_day_is_caught(self) -> None:
        (self.storage.root / "catalog/entries/snow_gapfill/2026-11-02.json").unlink()
        rebuild_index(self.storage)
        report = check_catalog(self.storage)
        self.assertFalse(report["ok"])
        self.assertEqual([e["date"] for e in errors_of(report, "missing_day")], ["2026-11-02"])

    def test_missing_days_at_the_edges_of_a_requested_range_are_caught(self) -> None:
        report = check_catalog(self.storage, start="2026-10-31", end="2026-11-04")
        self.assertEqual([e["date"] for e in errors_of(report, "missing_day")], ["2026-10-31", "2026-11-04"])

    def test_a_daily_layer_with_no_entry_in_the_range_misses_every_day(self) -> None:
        report = check_catalog(self.storage, start="2026-11-10", end="2026-11-11")
        self.assertEqual([e["date"] for e in errors_of(report, "missing_day")], ["2026-11-10", "2026-11-11"])

    def test_a_truncated_cog_is_caught(self) -> None:
        path = self.cog_path()
        path.write_bytes(path.read_bytes()[: path.stat().st_size // 2])
        report = check_catalog(self.storage)
        self.assertEqual([e["date"] for e in errors_of(report, "cog")], ["2026-11-01"])

    def test_corrupted_tile_data_is_caught(self) -> None:
        path = self.cog_path()
        data = bytearray(path.read_bytes())
        with rasterio.open(path) as src:
            offset = int(src.get_tag_item("BLOCK_OFFSET_0_0", "TIFF", bidx=1))
        data[offset : offset + 64] = b"\xff" * 64
        path.write_bytes(bytes(data))
        problems = cog_problems(path)
        self.assertTrue(any(p.startswith("unreadable") for p in problems), problems)
        self.assertTrue(errors_of(check_catalog(self.storage), "cog"))

    def test_a_plain_geotiff_in_place_of_the_cog_is_caught(self) -> None:
        path = self.cog_path()
        with rasterio.open(path) as src:
            array, profile = src.read(), src.profile
        profile.update(driver="GTiff", tiled=False)
        path.unlink()
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(array)
        messages = [e["message"] for e in errors_of(check_catalog(self.storage), "cog")]
        self.assertIn("no GDAL structural metadata: not written by the COG driver", messages)

    def test_a_cog_edited_after_writing_is_caught(self) -> None:
        # GDAL flags the edit only when it breaks the layout, which needs overviews: a 1200 px image has two.
        from rasterio.shutil import copy

        folder = Path(self._case.name)
        array = np.random.default_rng(0).integers(0, 2, (1200, 1200), dtype=np.uint8)
        plain = write_raster(folder / "plain.tif", array, 20, 255)
        copy(plain, folder / "cog.tif", driver="COG", COMPRESS="DEFLATE", BLOCKSIZE=512)
        self.assertEqual(cog_problems(folder / "cog.tif"), [])
        with rasterio.open(folder / "cog.tif", "r+", IGNORE_COG_LAYOUT_BREAK="YES") as dst:
            dst.write(np.zeros((1, 8, 8), dtype=np.uint8), window=((10, 18), (10, 18)))
        self.assertIn("edited after it was written; the COG layout no longer holds", cog_problems(folder / "cog.tif"))

    def test_a_missing_cog_and_a_truncated_pmtiles_are_caught(self) -> None:
        self.cog_path(0).unlink()
        pmtiles = self.storage.root / self.entries[1]["pmtiles"]
        pmtiles.write_bytes(pmtiles.read_bytes()[:200])
        report = check_catalog(self.storage)
        self.assertEqual([(e["date"], e["message"]) for e in errors_of(report, "cog")], [("2026-11-01", "missing")])
        self.assertTrue(any(e["date"] == "2026-11-02" for e in errors_of(report, "pmtiles")))

    def test_wrong_crs_unset_nodata_and_changed_pixels_are_caught(self) -> None:
        from rasterio.shutil import copy

        path = self.cog_path()
        with rasterio.open(path) as src:
            array, profile = src.read(), src.profile
        array[0, 10, 10] = 7
        profile.update(driver="GTiff", crs="EPSG:25830", nodata=None)
        plain = path.with_suffix(".plain.tif")
        with rasterio.open(plain, "w", **profile) as dst:
            dst.write(array)
        path.unlink()
        copy(plain, path, driver="COG")
        plain.unlink()
        report = check_catalog(self.storage)
        checks = {e["check"] for e in report["errors"] if e["date"] == "2026-11-01"}
        self.assertTrue({"crs", "nodata", "values", "pixel_hash"} <= checks, report["errors"])

    def test_an_entry_published_without_rebuilding_the_index_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            publish("snow_gapfill", "2026-11-04", product(Path(tmp), "late", seed=9), meta(), self.storage)
        report = check_catalog(self.storage)
        self.assertEqual([(e["date"], e["check"]) for e in report["errors"]], [("2026-11-04", "index")])

    def test_an_empty_catalogue_passes_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = check_catalog(LocalStorage(Path(tmp)))
        self.assertTrue(report["ok"])
        self.assertEqual(report["index"], "absent")


class ThumbsTests(CatalogueTestCase):
    def test_one_png_per_entry_with_the_display_tiles_drawn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            written = render_thumbs(self.storage, self.entries, Path(tmp))
            self.assertEqual([w["date"] for w in written], list(DAILY))
            image = Image.open(written[0]["png"]).convert("RGB")
            # The helper's display is white for snow and grey (120) for no snow; both must show in the sheet.
            colours = {colour for _, colour in image.getcolors(maxcolors=1 << 16) or []}
            self.assertIn((255, 255, 255), colours)
            self.assertIn((120, 120, 120), colours)


class CommandLineTests(CatalogueTestCase):
    def test_run_writes_the_report_and_uploads_it_under_qa(self) -> None:
        catalogue_root = Path(self._case.name)
        shutil.copytree(self.storage.root, catalogue_root / "staging")
        with (
            tempfile.TemporaryDirectory() as out,
            mock.patch.dict("os.environ", {"CATALOG_LOCAL_ROOT": str(catalogue_root)}),
        ):
            summary = Path(out) / "summary.md"
            with mock.patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary)}):
                status = main(["run", "--no-freshness", "--upload", "--out-dir", out])
            report = json.loads((Path(out) / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(status, 0)
            self.assertTrue(report["ok"])
            self.assertIn("QA report: pass", summary.read_text(encoding="utf-8"))
            staging = LocalStorage(catalogue_root / "staging")
            self.assertIsNotNone(staging.read(report["report_key"]))
            self.assertEqual(len(staging.list("qa/thumbs/snow_gapfill")), 3)

            (staging.root / self.entries[1]["cog"]).unlink()
            self.assertEqual(main(["run", "--no-freshness", "--no-thumbs", "--out-dir", out]), 1)


def _item(scene: str, created: str, product_uri: str = "") -> dict[str, Any]:
    date = scene.split("_")[2][:8]
    return {
        "id": scene,
        "properties": {
            "datetime": f"{date[:4]}-{date[4:6]}-{date[6:]}T11:00:00Z",
            "created": created,
            "s2:product_uri": product_uri or f"S2A_MSIL2A_{date}T110301_N0513_R094_T30SVG_{date}T173709.SAFE",
        },
    }


class FreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage = build(Path(self._tmp.name), dates=("2026-11-10",), layer="snow_obs")
        self.items = [
            _item("S2A_T30SVG_20261110T110234_L2A", "2026-11-10T17:30:00Z"),
            _item("S2A_T30SVG_20261113T110234_L2A", "2026-11-13T15:00:00Z"),
            _item("S2A_T30SVG_20261120T110610_L2A", "2026-11-20T18:55:00Z"),
        ]
        entry = index_entries(self.storage)["snow_obs"][0]
        self.created_at = entry["created_at"]
        self.source_ids = entry["source_ids"]

    def search(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        if "ids" in body:
            # The test entry's sources, listed 2 h before it was published.
            listed = (dt.datetime.fromisoformat(self.created_at) - dt.timedelta(hours=2)).isoformat()
            return [{"id": source, "properties": {"created": listed}} for source in body["ids"]]
        return self.items

    def run_f1(self, now: str) -> dict[str, Any]:
        return freshness(self.storage, (-3.5, 36.9, -2.5, 37.3), dt.datetime.fromisoformat(now), 30, self.search)["f1"]

    def test_unexplained_pass_is_missing_and_a_recent_one_is_not_due(self) -> None:
        f1 = self.run_f1("2026-11-21T08:00:00+00:00")
        states = {row["date"]: row["state"] for row in f1["passes"]}
        self.assertEqual(states, {"2026-11-10": "published", "2026-11-13": "missing", "2026-11-20": "not_due"})
        self.assertFalse(f1["ok"])
        self.assertEqual([b["date"] for b in f1["breaches"]], ["2026-11-13"])
        self.assertEqual(f1["latencies"][0]["latency_h"], 2.0)

    def test_a_decision_not_listed_explains_a_pass(self) -> None:
        decision = {
            "date": "2026-11-13",
            "orbit": "R094",
            "scene_ids": ["S2A_T30SVG_20261113T110234_L2A"],
            "domain_coverage": 1.0,
            "domain_valid_fraction": 0.12,
            "complete": True,
            "listed": False,
            "decided_at": "2026-11-13T16:00:00+00:00",
            "code_version": "test",
        }
        self.storage.write(
            "s2/decisions/2026-11-13_R094.json", json.dumps(decision).encode(), "application/json", "no-cache"
        )
        f1 = self.run_f1("2026-11-21T08:00:00+00:00")
        self.assertTrue(f1["ok"], f1["breaches"])
        decision["listed"] = True
        self.storage.write(
            "s2/decisions/2026-11-13_R094.json", json.dumps(decision).encode(), "application/json", "no-cache"
        )
        self.assertFalse(self.run_f1("2026-11-21T08:00:00+00:00")["ok"])

    def test_late_publication_is_a_breach(self) -> None:
        self.search_listed = None
        original = self.search

        def late(body: dict[str, Any]) -> list[dict[str, Any]]:
            if "ids" in body:
                listed = (dt.datetime.fromisoformat(self.created_at) - dt.timedelta(hours=30)).isoformat()
                return [{"id": source, "properties": {"created": listed}} for source in body["ids"]]
            return original(body)[:1]

        self.search = late  # type: ignore[method-assign]
        f1 = self.run_f1("2026-11-21T08:00:00+00:00")
        self.assertEqual([b["why"] for b in f1["breaches"]], ["published 30.0 h after listing"])


class F2Tests(unittest.TestCase):
    @staticmethod
    def entries(created_at: str, date: str = "2026-11-20") -> dict[str, list[dict[str, Any]]]:
        return {layer: [{"date": date, "created_at": created_at}] for layer in ("snow_gapfill", "swe", "snow_depth")}

    def test_on_time_late_missing_and_not_due(self) -> None:
        now = dt.datetime(2026, 11, 21, 12, 0, tzinfo=dt.timezone.utc)
        # 10:00 Europe/Madrid is 09:00 UTC in November (CET).
        self.assertTrue(check_f2(self.entries("2026-11-21T08:59:00+00:00"), now)["ok"])
        late = check_f2(self.entries("2026-11-21T09:01:00+00:00"), now)
        self.assertEqual({b["why"] for b in late["breaches"]}, {"late"})
        self.assertEqual(len(check_f2({}, now)["breaches"]), 3)
        early = check_f2({}, dt.datetime(2026, 11, 21, 8, 30, tzinfo=dt.timezone.utc))
        self.assertTrue(early["ok"])
        self.assertEqual(early["layers"]["swe"]["state"], "not_due")

    def test_the_deadline_follows_summer_time(self) -> None:
        # 2026-03-29 is the first day of CEST: 10:00 Madrid is 08:00 UTC.
        now = dt.datetime(2026, 3, 29, 12, 0, tzinfo=dt.timezone.utc)
        self.assertFalse(check_f2(self.entries("2026-03-29T08:30:00+00:00", "2026-03-28"), now)["ok"])
        self.assertTrue(check_f2(self.entries("2026-03-29T07:30:00+00:00", "2026-03-28"), now)["ok"])


class RegressionTests(unittest.TestCase):
    """The fixture rule on test rasters: 20 m classes (0 bare, 1 snow, 255 nodata) and 100 m SWE in mm."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.storage = LocalStorage(self.folder / "catalog")
        classes = np.zeros((50, 50), dtype=np.uint8)
        classes[:, 25:] = 1  # east half snow, west half bare
        self._publish("snow_obs", "2026-11-20", classes, 20, 255, [[0, 1]], "snow_class", "1")
        left, bottom, right, top = LEFT, TOP - 1000, LEFT + 1000, TOP
        self.bbox = list(transform_bounds("EPSG:32630", "EPSG:4326", left + 1, bottom + 1, right - 1, top - 1))
        self.fixture = load_fixtures()[0] | {"bbox": self.bbox, "model_dates": ["2026-11-21"]}
        self.fixture["rule"] = self.fixture["rule"] | {"observed_band": "snow_class", "bare_values": [0]}
        # A stand-in resort inside the 100 m cell at row 7, column 1, written as the fixture's GeoJSON.
        resort = transform_bounds("EPSG:32630", "EPSG:4326", LEFT + 120, TOP - 780, LEFT + 180, TOP - 720)
        west, south, east, north = resort
        ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
        polygon = {"type": "Polygon", "coordinates": [ring]}
        resort_path = self.folder / "resort.geojson"
        resort_path.write_text(
            json.dumps(
                {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": polygon}]}
            )
        )
        self.fixture["exclude"] = {"name": "ski resort", "geometry": str(resort_path)}
        self.fixture["s2_scenes"] = {"sentinel-2-c1-l2a": ["test-scene-a"], "sentinel-2-l1c": []}

    def _publish(
        self,
        layer: str,
        date: str,
        array: np.ndarray,
        resolution: int,
        nodata: float,
        value_range: list[list[float]],
        band: str,
        unit: str,
    ) -> None:
        data = write_raster(self.folder / f"{layer}-{date}.tif", array, resolution, nodata)
        rgba = np.full((4, *array.shape), 255, dtype=np.uint8)
        display = write_raster(self.folder / f"{layer}-{date}-display.tif", rgba, resolution, None)
        publish(
            layer,
            date,
            {"data": data, "display": display},
            meta(bands=[band], units=[unit], value_range=value_range),
            self.storage,
        )
        rebuild_index(self.storage)

    def evaluate(self) -> dict[str, Any]:
        return evaluate(self.storage, self.fixture, index_entries(self.storage), self.folder)

    def test_pending_until_the_model_is_published(self) -> None:
        result = self.evaluate()
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["pending"], ["no swe entry for 2026-11-21"])

    def test_snow_on_bare_ground_fails_and_snow_on_snow_passes(self) -> None:
        swe = np.zeros((10, 10), dtype=np.float32)
        swe[:, 5:] = 80.0  # snow over the observed snow: allowed
        swe[2, 1] = 12.0  # snow over observed bare ground: a violation
        swe[3, 1] = 4.0  # under the 5 mm presence threshold: not snow
        swe[7, 1] = 300.0  # artificial snow in the resort: excluded
        self._publish("swe", "2026-11-21", swe, 100, -1, [[0, 2000]], "swe", "mm")
        result = self.evaluate()
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["dates"], [{"date": "2026-11-21", "bare_cells": 49, "snow_on_bare_cells": 1}])

    def test_the_real_q4_fixture_is_pending_while_its_inputs_are_undefined(self) -> None:
        fixture = load_fixtures()[0]
        self.assertEqual(fixture["id"], "q4_crest_2026-11-20")
        self.assertEqual(fixture["bbox"], [-3.42, 37.01, -3.30, 37.07])
        result = evaluate(self.storage, fixture, {}, self.folder)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(len(result["pending"]), 4)


if __name__ == "__main__":
    unittest.main()
