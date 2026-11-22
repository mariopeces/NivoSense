"""One test per check of the harness, so removing any check fails a test (G-Code round 1 mutation run)."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np
from rasterio.shutil import copy as rio_copy

from pipelines.catalog import LocalStorage, publish, rebuild_index
from pipelines.catalog.layers import get_layer
from qa.check_catalog import _data_problems, check_catalog, check_entry, cog_problems, expected_last_day
from qa.check_catalog import pmtiles_problems as pm_problems
from qa.freshness import check_f1, check_f2
from qa.regression import run_fixtures
from tests.catalog.helpers import meta, write_raster
from tests.qa_harness.test_qa import NOW, CatalogueTestCase, RegressionCase, errors_of

BBOX = (-3.5, 36.9, -2.5, 37.3)


def _rewrite_header(path: Path, **fields: Any) -> None:
    """Change fields of a PMTiles v3 header in place."""
    from pmtiles.tile import deserialize_header, serialize_header

    data = bytearray(path.read_bytes())
    header = deserialize_header(bytes(data[:127]))
    header.update(fields)  # type: ignore[typeddict-item]
    data[:127] = serialize_header(header)
    path.write_bytes(bytes(data))


class CogTests(CatalogueTestCase):
    def patched(self, old: bytes, new: bytes) -> Path:
        """A copy of the first COG with one string of its GDAL structural metadata replaced (same length)."""
        assert len(old) == len(new)
        data = self.cog_path().read_bytes()
        self.assertIn(old, data[:1024])
        path = Path(self._case.name) / "patched.tif"
        path.write_bytes(data.replace(old, new, 1))
        return path

    def test_the_published_cog_is_valid(self) -> None:
        self.assertEqual(cog_problems(self.cog_path()), [])

    def test_a_file_that_is_not_a_tiff_is_named_as_such(self) -> None:
        path = Path(self._case.name) / "not.tif"
        path.write_bytes(b"\x89PNG" + bytes(2000))
        self.assertEqual(cog_problems(path), ["not a TIFF file"])

    def test_ifds_after_the_data_are_caught(self) -> None:
        path = self.patched(b"LAYOUT=IFDS_BEFORE_DATA", b"LAYOUT=IFDS_AFTERS_DATA")
        self.assertIn("IFDs are not before the image data", cog_problems(path))

    def test_a_layout_gdal_does_not_call_cog_is_caught(self) -> None:
        # GDAL reports LAYOUT=COG only for row-major block order; the rest of the metadata stays valid.
        path = self.patched(b"BLOCK_ORDER=ROW_MAJOR", b"BLOCK_ORDER=COL_MAJOR")
        self.assertEqual(cog_problems(path), ["GDAL does not report LAYOUT=COG"])

    def test_a_large_striped_image_without_overviews_is_caught(self) -> None:
        array = np.random.default_rng(0).integers(0, 2, (600, 600), dtype=np.uint8)
        path = write_raster(Path(self._case.name) / "strips.tif", array, 20, 255)
        problems = cog_problems(path)
        self.assertTrue(any(p.startswith("not tiled (blocks 600x") for p in problems), problems)
        self.assertIn("no overviews on a 600x600 image", problems)

    def test_a_large_tiled_cog_with_overviews_passes(self) -> None:
        array = np.random.default_rng(0).integers(0, 2, (600, 600), dtype=np.uint8)
        plain = write_raster(Path(self._case.name) / "plain.tif", array, 20, 255)
        rio_copy(plain, Path(self._case.name) / "cog.tif", driver="COG", BLOCKSIZE=256)
        self.assertEqual(cog_problems(Path(self._case.name) / "cog.tif"), [])


class DataTests(CatalogueTestCase):
    def problems(self, entry: dict[str, Any] | None = None, path: Path | None = None) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for check, message in _data_problems(path or self.cog_path(), entry or self.entries[0]):
            found.setdefault(check, []).append(message)
        return found

    def test_the_published_cog_has_no_data_problem(self) -> None:
        self.assertEqual(self.problems(), {})

    def test_a_cog_off_the_layer_grid_is_caught(self) -> None:
        # The entry says 100 m: the 20 m pixels are not on the 100 m grid.
        self.assertIn("grid", self.problems(self.entries[0] | {"resolution_m": 100}))

    def test_a_nodata_value_other_than_the_entry_is_caught(self) -> None:
        self.assertEqual(self.problems(self.entries[0] | {"nodata": 0})["nodata"], ["file nodata 255.0, entry 0"])

    def test_a_band_count_other_than_the_entry_is_caught(self) -> None:
        entry = self.entries[0] | {"bands": ["a", "b"], "value_range": [[0, 1], [0, 1]]}
        self.assertEqual(self.problems(entry)["bands"], ["1 bands, entry lists 2"])

    def test_values_below_the_declared_range_are_caught(self) -> None:
        found = self.problems(self.entries[0] | {"value_range": [[1, 1]]})
        self.assertEqual(found["values"], ["band 1 spans 0..1, declared 1..1"])

    def test_values_above_the_declared_range_are_caught(self) -> None:
        found = self.problems(self.entries[0] | {"value_range": [[0, 0]]})
        self.assertEqual(found["values"], ["band 1 spans 0..1, declared 0..0"])

    def test_a_band_with_no_valid_pixel_is_caught(self) -> None:
        plain = write_raster(Path(self._case.name) / "empty.tif", np.full((64, 64), 255, np.uint8), 20, 255)
        path = Path(self._case.name) / "empty-cog.tif"
        rio_copy(plain, path, driver="COG")
        self.assertEqual(self.problems(path=path)["values"], ["band 1 has no valid pixels"])

    def test_bounds_other_than_the_entry_are_caught(self) -> None:
        west, south, east, north = self.entries[0]["bounds"]
        found = self.problems(self.entries[0] | {"bounds": [west + 0.001, south, east, north]})
        self.assertEqual(len(found["bounds"]), 1)


class PmtilesTests(CatalogueTestCase):
    def pmtiles(self) -> Path:
        return self.storage.root / self.entries[0]["pmtiles"]

    def test_the_published_pmtiles_pass(self) -> None:
        self.assertEqual(pm_problems(self.storage, self.entries[0]), [])

    def test_a_missing_pmtiles_is_caught(self) -> None:
        self.pmtiles().unlink()
        self.assertEqual(pm_problems(self.storage, self.entries[0]), ["missing"])
        report = check_catalog(self.storage, now=NOW)
        self.assertEqual([(e["date"], e["message"]) for e in errors_of(report, "pmtiles")], [("2026-11-01", "missing")])

    def test_a_file_that_is_not_pmtiles_is_caught(self) -> None:
        self.pmtiles().write_bytes(b"NOTPMTILES" + bytes(500))
        problems = pm_problems(self.storage, self.entries[0])
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("bad header: MagicNumberNotFound"), problems)

    def test_zooms_other_than_the_resolution_needs_are_caught(self) -> None:
        _rewrite_header(self.pmtiles(), max_zoom=11)
        self.assertEqual(pm_problems(self.storage, self.entries[0]), ["zooms 8..11, expected 8..14"])

    def test_no_tiles_is_caught(self) -> None:
        _rewrite_header(self.pmtiles(), addressed_tiles_count=0)
        self.assertEqual(pm_problems(self.storage, self.entries[0]), ["no tiles"])

    def test_tiles_away_from_the_entry_bounds_are_caught(self) -> None:
        _rewrite_header(self.pmtiles(), min_lon_e7=100_000_000, max_lon_e7=110_000_000)
        problems = pm_problems(self.storage, self.entries[0])
        self.assertEqual(len(problems), 1)
        self.assertIn("do not overlap the entry bounds", problems[0])

    def test_check_entry_expects_the_layer_tile_format(self) -> None:
        # A layer that declares WebP tiles (as rgb does) but whose PMTiles hold PNG.
        webp = dataclasses.replace(get_layer("snow_gapfill"), tile_format="WEBP")
        with tempfile.TemporaryDirectory() as tmp, mock.patch("qa.check_catalog.get_layer", return_value=webp):
            problems = check_entry(self.storage, self.entries[0], Path(tmp))
        self.assertEqual([(p["check"], p["message"]) for p in problems], [("pmtiles", "tile type PNG, expected WEBP")])


class CatalogueObjectTests(CatalogueTestCase):
    def entry_path(self, date: str = "2026-11-02") -> Path:
        return self.storage.root / f"catalog/entries/snow_gapfill/{date}.json"

    def test_an_entry_object_under_another_key_is_caught(self) -> None:
        key = "catalog/entries/snow_gapfill/2026-11-09.json"
        self.storage.write(key, self.entry_path().read_bytes(), "application/json", "no-cache")
        report = check_catalog(self.storage, now=NOW)
        self.assertEqual(
            [(e["key"], e["message"]) for e in errors_of(report, "entry_key")],
            [("catalog/entries/snow_gapfill/2026-11-09.json", "holds snow_gapfill 2026-11-02")],
        )

    def test_an_entry_object_against_the_schema_is_caught(self) -> None:
        entry = json.loads(self.entry_path().read_bytes())
        del entry["cog"]
        self.entry_path().write_text(json.dumps(entry), encoding="utf-8")
        report = check_catalog(self.storage, now=NOW)
        self.assertEqual(
            [e["key"] for e in errors_of(report, "entry_schema")],
            [str(self.entry_path().relative_to(self.storage.root).as_posix())],
        )

    def test_index_dates_out_of_order_are_caught(self) -> None:
        path = self.storage.root / "catalog/index.json"
        index = json.loads(path.read_bytes())
        item = index["layers"]["snow_gapfill"]
        item["dates"] = list(reversed(item["dates"]))
        path.write_text(json.dumps(index), encoding="utf-8")
        messages = [e["message"] for e in errors_of(check_catalog(self.storage, now=NOW), "index")]
        self.assertIn("snow_gapfill: dates are not the ascending dates of its entries", messages)

    def test_entries_without_an_index_are_caught(self) -> None:
        (self.storage.root / "catalog/index.json").unlink()
        report = check_catalog(self.storage, now=NOW, allow_absent=True)
        self.assertEqual(
            [e["message"] for e in errors_of(report, "index")], ["catalog/index.json is missing but entries exist"]
        )

    def test_a_check_that_raises_is_reported_against_its_entry(self) -> None:
        with mock.patch("qa.check_catalog.check_entry", side_effect=KeyError("bands")):
            report = check_catalog(self.storage, now=NOW)
        self.assertEqual(
            [(e["date"], e["message"]) for e in errors_of(report, "unexpected")],
            [(date, "KeyError: 'bands'") for date in ("2026-11-01", "2026-11-02", "2026-11-03")],
        )

    def test_the_last_expected_day_is_judged_in_madrid_time(self) -> None:
        # 09:30 UTC on 2026-11-04 is 10:30 in Madrid: past the deadline there, so 2026-11-03 is due.
        self.assertEqual(expected_last_day(dt.datetime(2026, 11, 4, 9, 30, tzinfo=dt.timezone.utc)), "2026-11-03")
        self.assertEqual(expected_last_day(dt.datetime(2026, 11, 4, 8, 30, tzinfo=dt.timezone.utc)), "2026-11-02")


def _l2a(scene: str, created: str, orbit: str = "R094") -> dict[str, Any]:
    date = scene.split("_")[2][:8]
    return {
        "id": scene,
        "properties": {
            "datetime": f"{date[:4]}-{date[4:6]}-{date[6:]}T11:00:00Z",
            "created": created,
            "s2:product_uri": f"S2A_MSIL2A_{date}T110301_N0513_{orbit}_T30SVG_{date}T173709.SAFE",
        },
    }


class F1Case(unittest.TestCase):
    """check_f1 on entry dicts and a stub Earth Search; decisions in a local catalogue."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage = LocalStorage(Path(self._tmp.name))
        self.listed: dict[str, str] = {}
        self.items: list[dict[str, Any]] = []

    def search(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        if "ids" in body:
            return [{"id": i, "properties": {"created": self.listed[i]}} for i in body["ids"] if i in self.listed]
        return self.items

    def f1(self, entries: dict[str, list[dict[str, Any]]], now: str) -> dict[str, Any]:
        return check_f1(self.storage, entries, BBOX, dt.datetime.fromisoformat(now), 30, self.search)

    @staticmethod
    def obs(created_at: str, sources: list[str], date: str = "2026-11-13") -> dict[str, list[dict[str, Any]]]:
        entry = {"layer": "snow_obs", "date": date, "created_at": created_at, "source_ids": sources}
        return {"snow_obs": [entry], "rgb": [entry | {"layer": "rgb"}]}

    def write_decision(self, key: str, **fields: Any) -> None:
        decision = {
            "date": "2026-11-13",
            "orbit": "R094",
            "scene_ids": ["S2B_T30SVG_20261113T110242_L2A"],
            "domain_coverage": 1.0,
            "domain_valid_fraction": 0.1,
            "complete": True,
            "listed": False,
            "decided_at": "2026-11-13T16:00:00+00:00",
            "code_version": "test",
        } | fields
        self.storage.write(key, json.dumps(decision).encode(), "application/json", "no-cache")


class F1Tests(F1Case):
    def test_latency_runs_from_the_latest_source(self) -> None:
        self.listed = {"a": "2026-11-12T08:00:00+00:00", "b": "2026-11-13T12:00:00+00:00"}
        f1 = self.f1(self.obs("2026-11-13T14:00:00+00:00", ["a", "b"]), "2026-11-21T00:00:00+00:00")
        self.assertEqual({row["latency_h"] for row in f1["latencies"]}, {2.0})
        self.assertTrue(f1["ok"], f1["breaches"])

    def test_a_source_unknown_to_earth_search_is_a_breach(self) -> None:
        self.listed = {"a": "2026-11-13T12:00:00+00:00"}
        f1 = self.f1(self.obs("2026-11-13T14:00:00+00:00", ["a", "gone"]), "2026-11-21T00:00:00+00:00")
        self.assertEqual({b["why"] for b in f1["breaches"]}, {"source not on Earth Search: ['gone']"})

    def test_exactly_24_h_is_on_time(self) -> None:
        self.listed = {"a": "2026-11-12T14:00:00+00:00"}
        f1 = self.f1(self.obs("2026-11-13T14:00:00+00:00", ["a"]), "2026-11-21T00:00:00+00:00")
        self.assertEqual({row["latency_h"] for row in f1["latencies"]}, {24.0})
        self.assertTrue(f1["ok"], f1["breaches"])

    def test_a_pass_is_due_24_h_after_its_last_tile_was_listed(self) -> None:
        self.items = [
            _l2a("S2B_T30SVG_20261113T110242_L2A", "2026-11-13T15:00:00+00:00"),
            _l2a("S2B_T30SVF_20261113T110242_L2A", "2026-11-14T20:00:00+00:00"),
        ]
        # 30 h after the first tile, 19 h after the last: not due yet.
        early = self.f1({}, "2026-11-14T21:00:00+00:00")["passes"][0]
        self.assertEqual((early["state"], early["listed_at"]), ("not_due", "2026-11-14T20:00:00+00:00"))
        # 30 h after the last: missing.
        late = self.f1({}, "2026-11-16T02:00:00+00:00")
        self.assertEqual(late["passes"][0]["state"], "missing")
        self.assertEqual(late["breaches"][0]["why"], "missing: no decision recorded")

    def test_a_decision_whose_date_does_not_match_its_key_is_refused(self) -> None:
        self.items = [_l2a("S2B_T30SVG_20261113T110242_L2A", "2026-11-13T15:00:00+00:00")]
        self.write_decision("s2/decisions/2026-11-13_R094.json", date="2026-11-12")
        f1 = self.f1({}, "2026-11-21T00:00:00+00:00")
        self.assertEqual(
            f1["breaches"][0]["why"], "missing: decision s2/decisions/2026-11-13_R094.json is for 2026-11-12 R094"
        )


class StaleDecisionTests(F1Case):
    """The real late tiles of 2026-11-17, relative orbit R051, as Earth Search lists them on 2026-11-22: tiles
    of processing 105237 were listed at about 17:00 UTC, and the reprocessing 110058 at 18:07 to 18:18 UTC."""

    FIRST = {
        "S2A_T30SWF_20261117T105237_L2A": "2026-11-17T17:00:12.323Z",
        "S2A_T30SWG_20261117T105237_L2A": "2026-11-17T17:03:01.080Z",
    }
    LATE = {
        "S2A_T30SVF_20261117T110058_L2A": "2026-11-17T18:10:29.300Z",
        "S2A_T30SWF_20261117T110058_L2A": "2026-11-17T18:18:14.673Z",
        "S2A_T30SWG_20261117T110058_L2A": "2026-11-17T18:07:58.371Z",
    }
    KEY = "s2/decisions/2026-11-17_R051.json"
    NOW = "2026-11-22T06:00:00+00:00"

    def decide(self, scenes: dict[str, str], decided_at: str) -> None:
        self.write_decision(self.KEY, date="2026-11-17", orbit="R051", scene_ids=sorted(scenes), decided_at=decided_at)

    def pass_state(self) -> tuple[str, list[str]]:
        self.items = [_l2a(scene, created, "R051") for scene, created in (self.FIRST | self.LATE).items()]
        f1 = self.f1({}, self.NOW)
        return f1["passes"][0]["state"], [b["why"] for b in f1["breaches"]]

    def test_a_decision_on_the_first_tiles_does_not_cover_the_late_ones(self) -> None:
        self.decide(self.FIRST, "2026-11-17T17:30:00+00:00")
        state, whys = self.pass_state()
        self.assertEqual(state, "missing")
        self.assertEqual(len(whys), 1)
        self.assertTrue(whys[0].startswith("missing: stale decision: Earth Search now lists ['S2A_T30SVF_"), whys)

    def test_a_decision_made_before_the_last_tile_was_listed_is_stale(self) -> None:
        # It names every tile, but was decided before the last one (18:18) was listed.
        self.decide(self.FIRST | self.LATE, "2026-11-17T18:15:00+00:00")
        self.assertEqual(
            self.pass_state(),
            (
                "missing",
                ["missing: stale decision: decided at 2026-11-17T18:15:00+00:00, before the last scene was listed"],
            ),
        )

    def test_a_new_decision_on_every_tile_explains_the_pass(self) -> None:
        self.decide(self.FIRST | self.LATE, "2026-11-17T18:30:00+00:00")
        self.assertEqual(self.pass_state(), ("not_clear", []))


class F2Tests(unittest.TestCase):
    @staticmethod
    def entries(created_at: str) -> dict[str, list[dict[str, Any]]]:
        return {
            layer: [{"date": "2026-11-20", "created_at": created_at}] for layer in ("snow_gapfill", "swe", "snow_depth")
        }

    def test_the_deadline_is_10_00_in_madrid_not_in_utc(self) -> None:
        # 09:30 UTC on 2026-11-21 is 10:30 in Madrid: yesterday is due, and an entry from 09:15 UTC is late.
        now = dt.datetime(2026, 11, 21, 9, 30, tzinfo=dt.timezone.utc)
        with mock.patch.dict("qa.freshness.DAILY_SINCE", {"swe": "2025-10-01"}):
            self.assertEqual(check_f2({}, now)["layers"]["swe"]["state"], "missing")
        late = check_f2(self.entries("2026-11-21T09:15:00+00:00"), now)
        self.assertEqual({layer["state"] for layer in late["layers"].values()}, {"late"})

    def test_publishing_at_the_deadline_is_on_time(self) -> None:
        now = dt.datetime(2026, 11, 21, 12, 0, tzinfo=dt.timezone.utc)
        self.assertTrue(check_f2(self.entries("2026-11-21T09:00:00+00:00"), now)["ok"])

    def test_a_layer_that_is_not_live_yet_is_no_breach(self) -> None:
        now = dt.datetime(2026, 11, 21, 12, 0, tzinfo=dt.timezone.utc)
        result = check_f2({}, now)
        self.assertTrue(result["ok"])
        self.assertEqual({layer["state"] for layer in result["layers"].values()}, {"not_live"})
        # Once a layer declares its start, or has any entry, a missing yesterday is a breach.
        with mock.patch.dict("qa.freshness.DAILY_SINCE", {"swe": "2025-10-01"}):
            self.assertEqual([b["layer"] for b in check_f2({}, now)["breaches"]], ["swe"])
        old = {"snow_depth": [{"date": "2026-11-01", "created_at": "2026-11-02T08:00:00+00:00"}]}
        self.assertEqual([b["layer"] for b in check_f2(old, now)["breaches"]], ["snow_depth"])


class FixtureRuleTests(RegressionCase):
    """More of the fixture rule on RegressionTests' rasters: 20 m classes and a 100 m SWE grid."""

    def publish_swe(self, swe: np.ndarray) -> None:
        self._publish("swe", "2026-11-21", swe.astype(np.float32), 100, -1, [[0, 2000]], "swe", "mm")

    def republish_obs(self, classes: np.ndarray, **overrides: Any) -> None:
        data = write_raster(self.folder / "obs2.tif", classes, 20, 255)
        display = write_raster(self.folder / "obs2-display.tif", np.full((4, 50, 50), 255, np.uint8), 20, None)
        publish(
            "snow_obs",
            "2026-11-20",
            {"data": data, "display": display},
            # A new code_version: publish refuses other pixels for the same inputs and code.
            meta(bands=["snow_class"], value_range=[[0, 1]], code_version="test-republish", **overrides),
            self.storage,
        )
        rebuild_index(self.storage)

    def test_a_mixed_cell_is_not_scored(self) -> None:
        classes = np.zeros((50, 50), dtype=np.uint8)
        classes[:, 25:] = 1
        classes[10, 10] = 1  # one snow pixel makes the 100 m cell at row 2, column 2 mixed
        self.republish_obs(classes)
        swe = np.zeros((10, 10))
        swe[2, 2] = 50.0
        self.publish_swe(swe)
        result = self.evaluate()
        self.assertEqual((result["status"], result["dates"][0]["bare_cells"]), ("pass", 48))

    def test_a_nodata_pixel_does_not_count_as_bare(self) -> None:
        # Bare class 255 as well as 0: the cell of nodata pixels is still not bare ground.
        self.fixture["rule"] = self.fixture["rule"] | {"bare_values": [0, 255]}
        classes = np.zeros((50, 50), dtype=np.uint8)
        classes[:, 25:] = 1
        classes[10:15, 10:15] = 255
        self.republish_obs(classes)
        swe = np.zeros((10, 10))
        swe[2, 2] = 50.0
        self.publish_swe(swe)
        self.assertEqual(self.evaluate()["dates"][0]["snow_on_bare_cells"], 0)

    def test_swe_at_the_threshold_is_not_snow(self) -> None:
        swe = np.zeros((10, 10))
        swe[2, 1] = 5.0
        self.publish_swe(swe)
        self.assertEqual(self.evaluate()["status"], "pass")

    def test_an_observation_from_other_scenes_fails(self) -> None:
        self.republish_obs(
            np.where(np.arange(50) >= 25, 1, 0).astype(np.uint8)[np.newaxis].repeat(50, 0), source_ids=["other-scene"]
        )
        self.publish_swe(np.zeros((10, 10)))
        result = self.evaluate()
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["failures"], ["snow_obs 2026-11-20 is not built from ['test-scene-a']"])

    def test_a_failing_fixture_fails_the_run_and_a_pending_one_does_not(self) -> None:
        swe = np.zeros((10, 10))
        swe[2, 1] = 12.0
        self.publish_swe(swe)
        from qa.objects import index_entries

        entries = index_entries(self.storage)
        self.assertFalse(run_fixtures(self.storage, entries, [self.fixture])["ok"])
        pending = self.fixture | {"model_dates": ["2026-11-22"]}
        self.assertTrue(run_fixtures(self.storage, entries, [pending])["ok"])


if __name__ == "__main__":
    unittest.main()
