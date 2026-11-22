import json
import multiprocessing
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import rasterio
from jsonschema import Draft202012Validator, ValidationError

from pipelines.catalog import LocalStorage, NonDeterministicOutput, promote, publish, rebuild_index, storage_from_env
from pipelines.catalog.index import INDEX_KEY
from pipelines.catalog.layers import aligned_bounds
from pipelines.catalog.publish import entry_key
from pipelines.catalog.storage import IMMUTABLE, NO_CACHE, PreconditionFailed
from pipelines.catalog.validate import SCHEMA_PATH, validate_entry, validate_index
from tests.catalog.helpers import meta, product, write_raster


class Crash(Exception):
    pass


class CrashOnEntryWrite(LocalStorage):
    """Fails like a killed job right after the data files are uploaded and before the entry is written."""

    def write(self, key, source, content_type, cache_control, if_generation_match=None):
        if key.startswith("catalog/entries/"):
            raise Crash(key)
        return super().write(key, source, content_type, cache_control, if_generation_match)


def _publish_and_rebuild(root: str, folder: str, date: str, seed: int) -> None:
    storage = LocalStorage(Path(root))
    publish("snow_obs", date, product(Path(folder), date, seed=seed), meta(), storage)
    rebuild_index(storage)


class CatalogTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.storage = LocalStorage(self.tmp / "staging")
        self.inputs = self.tmp / "inputs"
        self.inputs.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def publish(self, date: str = "2026-11-20", seed: int = 0, storage: LocalStorage | None = None, **kw: object):
        return publish(
            "snow_obs", date, product(self.inputs, f"{date}-{seed}", seed=seed), meta(**kw), storage or self.storage
        )


class SchemaTests(CatalogTestCase):
    def test_schema_is_valid_json_schema(self) -> None:
        Draft202012Validator.check_schema(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_published_entry_and_index_validate(self) -> None:
        entry = self.publish()
        validate_entry(entry)
        validate_index(rebuild_index(self.storage))

    def test_schema_rejects_other_crs_status_and_missing_fields(self) -> None:
        entry = self.publish()
        for change in ({"crs": "EPSG:25830"}, {"status": "guessed"}, {"pixel_hash": "abc"}, {"extra": 1}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                validate_entry({**entry, **change})
        incomplete = dict(entry)
        del incomplete["source_ids"]
        with self.assertRaises(ValidationError):
            validate_entry(incomplete)


class PublishTests(CatalogTestCase):
    def test_writes_cog_pmtiles_and_entry_with_their_cache_headers(self) -> None:
        entry = self.publish()
        name = Path(entry["cog"]).stem
        self.assertRegex(name, r"^2026-11-20-[0-9a-f]{16}$")
        self.assertEqual(entry["cog"], f"layers/snow_obs/2026/{name}.tif")
        self.assertEqual(entry["pmtiles"], f"tiles/snow_obs/{name}.pmtiles")
        self.assertEqual((entry["status"], entry["crs"], entry["resolution_m"]), ("observed", "EPSG:32630", 20))
        for key in (entry["cog"], entry["pmtiles"]):
            blob = self.storage.read(key)
            self.assertEqual(blob.cache_control, IMMUTABLE)
            self.assertIsNone(blob.content_encoding)
        stored = self.storage.read(entry_key("snow_obs", "2026-11-20"))
        self.assertEqual(stored.cache_control, NO_CACHE)
        self.assertEqual(json.loads(stored.data), entry)

    def test_cog_is_cloud_optimised_with_nodata_and_overviews(self) -> None:
        entry = self.publish()
        with rasterio.open(self.storage.root / entry["cog"]) as cog:
            self.assertEqual(cog.tags(ns="IMAGE_STRUCTURE")["LAYOUT"], "COG")
            self.assertEqual(cog.crs.to_string(), "EPSG:32630")
            self.assertEqual(cog.nodata, 255)
            self.assertEqual(cog.compression.name, "deflate")

    def test_pmtiles_zoom_range_follows_the_resolution(self) -> None:
        from pmtiles.reader import MmapSource, Reader

        swe = np.full((32, 32), 120.0, dtype=np.float32)
        files = {
            "data": write_raster(self.inputs / "swe.tif", swe, 100, -9999.0),
            "display": write_raster(self.inputs / "swe-rgba.tif", np.full((4, 32, 32), 200, np.uint8), 100, None),
        }
        swe_entry = publish(
            "swe", "2026-11-20", files, meta(bands=["swe"], units=["mm"], value_range=[[0, 5000]]), self.storage
        )
        for entry, zooms in ((self.publish(), (8, 14)), (swe_entry, (8, 12))):
            with open(self.storage.root / entry["pmtiles"], "rb") as handle:
                header = Reader(MmapSource(handle)).header()
            self.assertEqual((header["min_zoom"], header["max_zoom"]), zooms)

    def test_rejects_rasters_off_the_shared_grid(self) -> None:
        classes = np.zeros((16, 16), dtype=np.uint8)
        rgba = np.zeros((4, 16, 16), dtype=np.uint8)
        cases = {
            "shifted origin": {"left": 460010.0},
            "other CRS": {"crs": "EPSG:25830"},
            "other resolution": {"resolution": 10},
        }
        for label, change in cases.items():
            with self.subTest(label):
                resolution = change.pop("resolution", 20)
                files = {
                    "data": write_raster(self.inputs / f"{label}.tif", classes, resolution, 255, **change),
                    "display": write_raster(self.inputs / f"{label}-d.tif", rgba, resolution, None, **change),
                }
                with self.assertRaises(ValueError):
                    publish("snow_obs", "2026-11-20", files, meta(), self.storage)
        self.assertEqual(self.storage.list(""), [])

    def test_rejects_missing_nodata_values_out_of_range_and_unknown_layer(self) -> None:
        files = product(self.inputs, "a")
        no_nodata = dict(files, data=write_raster(self.inputs / "nn.tif", np.zeros((64, 64), np.uint8), 20, None))
        with self.assertRaisesRegex(ValueError, "nodata"):
            publish("snow_obs", "2026-11-20", no_nodata, meta(), self.storage)
        with self.assertRaisesRegex(ValueError, "outside the declared"):
            publish("snow_obs", "2026-11-20", files, meta(value_range=[[0, 0]]), self.storage)
        with self.assertRaisesRegex(ValueError, "Unknown layer"):
            publish("snow_cover", "2026-11-20", files, meta(), self.storage)
        self.assertEqual(self.storage.list(""), [])


class IdempotencyTests(CatalogTestCase):
    def test_same_input_key_gives_same_pixel_hash_and_names_and_writes_nothing(self) -> None:
        first = self.publish(seed=1)
        files_before = {key: self.storage.read(key).generation for key in self.storage.list("")}
        second = publish("snow_obs", "2026-11-20", product(self.tmp, "again", seed=1), meta(), self.storage)
        self.assertEqual(second, first)
        self.assertEqual({key: self.storage.read(key).generation for key in self.storage.list("")}, files_before)

    def test_new_code_version_with_same_pixels_reuses_the_files(self) -> None:
        first = self.publish(seed=1)
        second = self.publish(seed=1, code_version="next")
        self.assertNotEqual(second["input_key"], first["input_key"])
        self.assertEqual(
            (second["pixel_hash"], second["cog"], second["pmtiles"]),
            (first["pixel_hash"], first["cog"], first["pmtiles"]),
        )

    def test_same_input_key_with_different_pixels_is_refused(self) -> None:
        self.publish(seed=1)
        with self.assertRaises(NonDeterministicOutput):
            self.publish(seed=2)

    def test_pixel_hash_ignores_file_timestamps(self) -> None:
        from pipelines.catalog import pixel_hash

        files = product(self.inputs, "a", seed=3)
        before = pixel_hash(files["data"])
        with rasterio.open(files["data"], "r+") as dst:
            dst.update_tags(TIFFTAG_DATETIME="2026:11:22 10:00:00")
        self.assertEqual(pixel_hash(files["data"]), before)


class CrashTests(CatalogTestCase):
    def test_crash_between_files_and_entry_leaves_index_unchanged(self) -> None:
        self.publish("2026-11-19")
        rebuild_index(self.storage)
        index_before = self.storage.read(INDEX_KEY)

        crashing = CrashOnEntryWrite(self.storage.root)
        with self.assertRaises(Crash):
            self.publish("2026-11-20", seed=5, storage=crashing)

        self.assertEqual(len(self.storage.list("layers/snow_obs/2026/")), 2, "files were uploaded before the crash")
        self.assertFalse(self.storage.exists(entry_key("snow_obs", "2026-11-20")))
        index = rebuild_index(self.storage)
        self.assertEqual(index["layers"]["snow_obs"]["dates"], ["2026-11-19"])
        after = self.storage.read(INDEX_KEY)
        self.assertEqual((after.data, after.generation), (index_before.data, index_before.generation))

    def test_rerun_after_a_crash_completes_the_date(self) -> None:
        with self.assertRaises(Crash):
            self.publish(seed=5, storage=CrashOnEntryWrite(self.storage.root))
        self.publish(seed=5)
        self.assertEqual(rebuild_index(self.storage)["layers"]["snow_obs"]["dates"], ["2026-11-20"])


class ConcurrencyTests(CatalogTestCase):
    def test_two_concurrent_publishes_of_different_dates_both_end_in_the_index(self) -> None:
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def job(date: str, seed: int) -> None:
            try:
                files = product(self.inputs, date, seed=seed)
                barrier.wait()
                publish("snow_obs", date, files, meta(), self.storage)
                rebuild_index(self.storage)
            except BaseException as error:  # noqa: BLE001 - re-raised in the main thread below
                errors.append(error)

        threads = [threading.Thread(target=job, args=args) for args in (("2026-11-19", 1), ("2026-11-20", 2))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        index = json.loads(self.storage.read(INDEX_KEY).data)
        self.assertEqual(index["layers"]["snow_obs"]["dates"], ["2026-11-19", "2026-11-20"])

    def test_two_processes_publishing_different_dates_both_end_in_the_index(self) -> None:
        context = multiprocessing.get_context("spawn")
        processes = [
            context.Process(target=_publish_and_rebuild, args=(str(self.storage.root), str(self.inputs), date, seed))
            for date, seed in (("2026-11-19", 1), ("2026-11-20", 2))
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(120)
            self.assertEqual(process.exitcode, 0)
        index = json.loads(self.storage.read(INDEX_KEY).data)
        self.assertEqual(index["layers"]["snow_obs"]["dates"], ["2026-11-19", "2026-11-20"])

    def test_rebuild_that_loses_the_race_retries_with_the_new_entry(self) -> None:
        self.publish("2026-11-19", seed=1)
        real_write = LocalStorage.write
        raced = threading.Event()

        def write_after_a_rival(storage, key, source, content_type, cache_control, if_generation_match=None):
            if key == INDEX_KEY and not raced.is_set():
                raced.set()
                # A rival job publishes another date and rebuilds first, between our read and our write.
                self.publish("2026-11-20", seed=2)
                rebuild_index(self.storage)
            return real_write(storage, key, source, content_type, cache_control, if_generation_match)

        with mock.patch.object(LocalStorage, "write", write_after_a_rival):
            index = rebuild_index(self.storage)
        self.assertTrue(raced.is_set())
        self.assertEqual(index["layers"]["snow_obs"]["dates"], ["2026-11-19", "2026-11-20"])
        self.assertEqual(json.loads(self.storage.read(INDEX_KEY).data)["layers"], index["layers"])

    def test_stale_generation_write_is_refused(self) -> None:
        self.storage.write(INDEX_KEY, b"{}", "application/json", NO_CACHE, if_generation_match=0)
        with self.assertRaises(PreconditionFailed):
            self.storage.write(INDEX_KEY, b"{}", "application/json", NO_CACHE, if_generation_match=0)


class IndexTests(CatalogTestCase):
    def test_unchanged_entries_do_not_rewrite_the_index(self) -> None:
        self.publish()
        rebuild_index(self.storage)
        generation = self.storage.read(INDEX_KEY).generation
        rebuild_index(self.storage)
        self.assertEqual(self.storage.read(INDEX_KEY).generation, generation)

    def test_index_refuses_an_invalid_entry(self) -> None:
        entry = self.publish()
        broken = json.dumps({**entry, "crs": "EPSG:4326"}).encode()
        self.storage.write(entry_key("snow_obs", "2026-11-20"), broken, "application/json", NO_CACHE)
        with self.assertRaises(ValidationError):
            rebuild_index(self.storage)
        self.assertFalse(self.storage.exists(INDEX_KEY))


class PromoteTests(CatalogTestCase):
    def test_promote_copies_the_range_files_first_and_rebuilds_prod(self) -> None:
        prod = LocalStorage(self.tmp / "prod")
        for day, seed in (("2026-11-18", 1), ("2026-11-19", 2), ("2026-11-20", 3)):
            self.publish(day, seed=seed)
        rebuild_index(self.storage)

        promoted = promote(self.storage, prod, "2026-11-19", "2026-11-20")
        self.assertEqual([entry["date"] for entry in promoted], ["2026-11-19", "2026-11-20"])
        index = json.loads(prod.read(INDEX_KEY).data)
        self.assertEqual(index["layers"]["snow_obs"]["dates"], ["2026-11-19", "2026-11-20"])
        for entry in promoted:
            for key in (entry["cog"], entry["pmtiles"]):
                self.assertEqual(prod.read(key).data, self.storage.read(key).data)
                self.assertEqual(prod.read(key).cache_control, IMMUTABLE)
            self.assertEqual(prod.read(entry_key("snow_obs", entry["date"])).cache_control, NO_CACHE)

        generations = {key: prod.read(key).generation for key in prod.list("") if not key.startswith("catalog/entries")}
        promote(self.storage, prod, "2026-11-19", "2026-11-20")
        self.assertEqual(
            {key: prod.read(key).generation for key in prod.list("") if not key.startswith("catalog/entries")},
            generations,
        )

    def test_promote_of_an_empty_range_fails(self) -> None:
        self.publish()
        with self.assertRaises(ValueError):
            promote(self.storage, LocalStorage(self.tmp / "prod"), "2025-10-01", "2025-10-31")


class GridAndConfigTests(unittest.TestCase):
    def test_aligned_bounds_snap_outwards_to_the_resolution(self) -> None:
        self.assertEqual(aligned_bounds(399965, 4090001, 509799, 4200000, 20), (399960, 4090000, 509800, 4200000))
        self.assertEqual(aligned_bounds(399960, 4090010, 509800, 4199990, 100), (399900, 4090000, 509800, 4200000))

    def test_storage_comes_from_the_repository_variables(self) -> None:
        with mock.patch.dict(os.environ, {"CATALOG_LOCAL_ROOT": "", "STAGING_BUCKET": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "STAGING_BUCKET"):
                storage_from_env("staging")
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ, {"CATALOG_LOCAL_ROOT": root}):
            self.assertEqual(storage_from_env("prod").root, Path(root) / "prod")
        with self.assertRaises(ValueError):
            storage_from_env("production")


if __name__ == "__main__":
    unittest.main()
