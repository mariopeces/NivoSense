import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pipelines.catalog import LocalStorage
from pipelines.s2.stac import Acquisition
from pipelines.snow_obs import cache


def item(scene: str, baseline: str = "05.11") -> dict:
    return {"id": scene, "properties": {"s2:processing_baseline": baseline}}


def acquisition(day: str, orbit: str, scenes: list[str], baseline: str = "05.11") -> Acquisition:
    return Acquisition(date.fromisoformat(day), orbit, f"GS2A_{day}_{orbit}", tuple(item(s, baseline) for s in scenes))


def record(day: str, orbit: str, complete: bool = True, valid: float = 0.8) -> dict:
    return {
        "date": day,
        "orbit": orbit,
        "datatake": "d",
        "tiles": ["30SVF"],
        "missing_tiles": [] if complete else ["x"],
        "complete": complete,
        "scene_ids": ["s"],
        "processing_baselines": ["05.11"],
        "input_key": "k",
        "domain_coverage": 1.0,
        "domain_valid_fraction": valid,
        "listed": complete and valid >= 0.3,
    }


class KeyTests(unittest.TestCase):
    def test_month_ranges_split_at_month_ends(self) -> None:
        self.assertEqual(
            cache.month_ranges(date(2024, 1, 20), date(2024, 3, 5)),
            [
                (date(2024, 1, 20), date(2024, 1, 31)),
                (date(2024, 2, 1), date(2024, 2, 29)),
                (date(2024, 3, 1), date(2024, 3, 5)),
            ],
        )

    def test_date_key_follows_every_input(self) -> None:
        base = cache.date_key({"R094": "a"}, {"R094": ["30SVF"]}, "code", "domain")
        self.assertEqual(base, cache.date_key({"R094": "a"}, {"R094": ["30SVF"]}, "code", "domain"))
        changed = [
            cache.date_key({"R094": "b"}, {"R094": ["30SVF"]}, "code", "domain"),
            cache.date_key({"R094": "a", "R051": "c"}, {"R094": ["30SVF"]}, "code", "domain"),
            cache.date_key({"R094": "a"}, {"R094": ["30SVF", "30SVG"]}, "code", "domain"),
            cache.date_key({"R094": "a"}, {"R094": ["30SVF"]}, "code2", "domain"),
            cache.date_key({"R094": "a"}, {"R094": ["30SVF"]}, "code", "domain2"),
        ]
        self.assertNotIn(base, changed)
        self.assertEqual(len(base), cache.KEY_LENGTH)

    def test_code_key_covers_the_classifier_and_ignores_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in cache.CODE_FILES:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_bytes(b"a = 1\nb = 2\n")
            key = cache.code_key(root)
            (root / "pipelines/snow_obs/classify.py").write_bytes(b"a = 1\r\nb = 2\r\n")
            self.assertEqual(key, cache.code_key(root))
            (root / "pipelines/snow_obs/classify.py").write_bytes(b"a = 1\nb = 3\n")
            self.assertNotEqual(key, cache.code_key(root))
        self.assertIn("pipelines/snow_obs/classify.py", cache.CODE_FILES)
        self.assertIn("pipelines/s2/mosaic.py", cache.CODE_FILES)
        self.assertIn("pipelines/requirements.lock", cache.CODE_FILES)


class BuildDateTests(unittest.TestCase):
    def build(self, records: dict[str, dict]) -> tuple[dict, Path | None, mock.MagicMock]:
        orbits = {orbit: [acquisition(r["date"], orbit, [orbit])] for orbit, r in records.items()}
        summary = {"published": True, "observed_fraction": 0.7}
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(cache, "load_domain"),
            mock.patch.object(
                cache.ingest, "process", side_effect=lambda c, e, d, out: SimpleNamespace(**records[c[0].orbit])
            ),
            mock.patch.object(cache.snow, "process", return_value=summary) as process,
            mock.patch.object(cache, "pixel_hash", return_value="h"),
        ):
            entry, mask = cache.build_date(
                date(2024, 1, 3),
                orbits,
                {o: set() for o in orbits},
                "key",
                Path("d"),
                (None, None),
                Path(tmp),
                lambda r: {},
            )
        return entry, mask, process

    def test_takes_the_complete_pass_with_most_valid_pixels(self) -> None:
        entry, mask, process = self.build(
            {
                "R051": record("2024-01-03", "R051", valid=0.09),
                "R094": record("2024-01-03", "R094", valid=0.6),
            }
        )
        self.assertEqual(process.call_args.args[0]["orbit"], "R094")
        self.assertEqual(entry["chosen_orbit"], "R094")
        self.assertEqual(entry["mask"], "snow_obs/2024-01-03/key/snow_obs.tif")
        self.assertTrue(entry["clear"])
        self.assertEqual([p["orbit"] for p in entry["passes"]], ["R051", "R094"])
        self.assertIsNotNone(mask)

    def test_no_mask_without_a_complete_pass(self) -> None:
        entry, mask, process = self.build({"R094": record("2024-01-03", "R094", complete=False)})
        process.assert_not_called()
        self.assertIsNone(mask)
        self.assertIsNone(entry["mask"])
        self.assertFalse(entry["clear"])


class RunMonthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.storage = LocalStorage(self.root / "cache")
        self.domain = self.root / "domain.geojson"
        self.domain.write_text("{}")
        self.mask = self.root / "mask.tif"
        self.mask.write_bytes(b"tif")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_month(self, days: dict, built: list[str]) -> list[dict]:
        def build(day, orbits, expected, key, domain, static, work, fetch):  # type: ignore[no-untyped-def]
            built.append(day.isoformat())
            clear = day.day % 2 == 1
            entry = {
                "date": day.isoformat(),
                "key": key,
                "clear": clear,
                "mask": f"snow_obs/{day}/{key}/snow_obs.tif",
                "summary": {"published": clear},
            }
            return entry, self.mask

        with (
            mock.patch.object(cache, "plan", return_value=(days, {"R094": {"30SVF"}})),
            mock.patch.object(cache, "build_date", side_effect=build),
            mock.patch.object(cache, "load_domain"),
            mock.patch.object(cache, "load_static", return_value=(None, None)),
        ):
            return cache.run_month(
                self.domain, date(2024, 1, 1), date(2024, 1, 31), self.storage, self.root / "work", version="abc"
            )

    def test_second_run_reads_the_cache_and_a_changed_input_rebuilds_only_its_date(self) -> None:
        days = {
            date(2024, 1, 3): {"R094": [acquisition("2024-01-03", "R094", ["a"])]},
            date(2024, 1, 8): {"R094": [acquisition("2024-01-08", "R094", ["b"])]},
        }
        built: list[str] = []
        first = self.run_month(days, built)
        self.assertEqual(built, ["2024-01-03", "2024-01-08"])
        for entry in first:
            folder = f"snow_obs/{entry['date']}/{entry['key']}"
            self.assertTrue(self.storage.exists(f"{folder}/entry.json"))
            self.assertTrue(self.storage.exists(f"{folder}/snow_obs.tif"))
            self.assertEqual(entry["code_version"], "abc")
        self.assertEqual(self.run_month(days, built), first)
        self.assertEqual(built, ["2024-01-03", "2024-01-08"])

        days[date(2024, 1, 8)] = {"R094": [acquisition("2024-01-08", "R094", ["b"], baseline="05.99")]}
        third = self.run_month(days, built)
        self.assertEqual(built, ["2024-01-03", "2024-01-08", "2024-01-08"])
        self.assertEqual(third[0], first[0])
        self.assertNotEqual(third[1]["key"], first[1]["key"])

    def test_manifest_lists_clear_dates_and_refuses_missing_months(self) -> None:
        days = {
            date(2024, 1, 3): {"R094": [acquisition("2024-01-03", "R094", ["a"])]},
            date(2024, 1, 8): {"R094": [acquisition("2024-01-08", "R094", ["b"])]},
        }
        self.run_month(days, [])
        manifest = cache.build_manifest(self.storage, date(2024, 1, 1), date(2024, 1, 31))
        self.assertEqual(manifest["clear_dates"], ["2024-01-03"])
        self.assertEqual(manifest["acquisition_dates"], 2)
        stored = json.loads(self.storage.read("snow_obs/manifest.json").data)  # type: ignore[union-attr]
        self.assertEqual(stored["clear_dates"], ["2024-01-03"])
        with self.assertRaisesRegex(RuntimeError, "2024-02-01_2024-02-29"):
            cache.build_manifest(self.storage, date(2024, 1, 1), date(2024, 2, 29))


if __name__ == "__main__":
    unittest.main()
