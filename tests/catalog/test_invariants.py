"""Invariants behind the catalogue's Accept lines that a single wrong line of code could break silently."""

import io
import json
import os
import subprocess
import unittest
from unittest import mock

import numpy as np
import rasterio

from pipelines.catalog import LocalStorage, code_version, pixel_hash, promote, publish, rebuild_index
from pipelines.catalog.index import INDEX_KEY
from pipelines.catalog.publish import entry_key
from pipelines.catalog.storage import NO_CACHE
from tests.catalog.helpers import LEFT, TOP, meta, product, write_raster
from tests.catalog.test_catalog import CatalogTestCase


class Boom(Exception):
    pass


def failing_on(prefix: str) -> type[LocalStorage]:
    """A storage whose writes under `prefix` fail with a non-412 error, like a 403 or a dropped connection."""

    class FailOn(LocalStorage):
        def write(self, key, source, content_type, cache_control, if_generation_match=None):
            if key.startswith(prefix):
                raise Boom(key)
            return super().write(key, source, content_type, cache_control, if_generation_match)

    return FailOn


class PublishOrderTests(CatalogTestCase):
    def test_a_failed_cog_or_pmtiles_upload_stops_before_the_entry(self) -> None:
        self.publish("2026-11-19", seed=1)
        rebuild_index(self.storage)
        before = self.storage.read(INDEX_KEY)
        for prefix in ("layers/", "tiles/"):
            with self.subTest(prefix):
                with self.assertRaises(Boom):
                    self.publish("2026-11-20", seed=2, storage=failing_on(prefix)(self.storage.root))
                self.assertFalse(self.storage.exists(entry_key("snow_obs", "2026-11-20")))
        rebuild_index(self.storage)
        after = self.storage.read(INDEX_KEY)
        self.assertEqual((after.data, after.generation), (before.data, before.generation))

    def test_republish_restores_a_missing_file(self) -> None:
        entry = self.publish(seed=1)
        for key in (entry["pmtiles"], entry["cog"]):
            with self.subTest(key):
                (self.storage.root / key).unlink()
                self.assertEqual(self.publish(seed=1), entry)
                self.assertTrue(self.storage.exists(key))


class IndexInvariantTests(CatalogTestCase):
    def test_a_rival_rebuild_after_our_listing_is_not_lost(self) -> None:
        self.publish("2026-11-19", seed=1)
        rebuild_index(self.storage)
        real_list = LocalStorage.list
        raced: list[bool] = []

        def list_then_rival(storage, prefix):
            keys = real_list(storage, prefix)
            if prefix.startswith("catalog/entries") and not raced:
                raced.append(True)
                # A rival publishes and rebuilds after we listed, before we write the index.
                self.publish("2026-11-20", seed=2)
                rebuild_index(self.storage)
            return keys

        with mock.patch.object(LocalStorage, "list", list_then_rival):
            rebuild_index(self.storage)
        self.assertTrue(raced)
        stored = json.loads(self.storage.read(INDEX_KEY).data)
        self.assertEqual(stored["layers"]["snow_obs"]["dates"], ["2026-11-19", "2026-11-20"])

    def test_a_changed_entry_reaches_the_index(self) -> None:
        first = self.publish(seed=1)
        rebuild_index(self.storage)
        second = self.publish(seed=2, code_version="next")
        self.assertNotEqual(second["cog"], first["cog"])
        index = json.loads(self.storage.read(INDEX_KEY).data)
        self.assertEqual(index["layers"]["snow_obs"]["entries"][0]["cog"], first["cog"])
        rebuild_index(self.storage)
        index = json.loads(self.storage.read(INDEX_KEY).data)
        self.assertEqual(index["layers"]["snow_obs"]["entries"], [second])

    def test_an_entry_under_another_dates_key_is_refused(self) -> None:
        entry = self.publish("2026-11-20")
        self.storage.write(
            entry_key("snow_obs", "2026-11-21"), json.dumps(entry).encode(), "application/json", NO_CACHE
        )
        with self.assertRaisesRegex(ValueError, "holds the entry of"):
            rebuild_index(self.storage)


class OverlappingPromoteTests(CatalogTestCase):
    def test_a_slow_promote_does_not_overwrite_a_newer_version_in_prod(self) -> None:
        prod = LocalStorage(self.tmp / "prod")
        self.publish(seed=1)
        newer: dict = {}
        real_write = LocalStorage.write

        def rival_first(storage, key, source, content_type, cache_control, if_generation_match=None):
            if storage is prod and key.startswith("catalog/entries/") and not newer:
                # Staging republishes the date and a second promote copies it before ours writes the entry.
                newer.update(self.publish(seed=2, code_version="next"))
                promote(self.storage, prod, "2026-11-20", "2026-11-20")
            return real_write(storage, key, source, content_type, cache_control, if_generation_match)

        with mock.patch.object(LocalStorage, "write", rival_first):
            promote(self.storage, prod, "2026-11-20", "2026-11-20")
        self.assertTrue(newer)
        self.assertEqual(json.loads(prod.read(entry_key("snow_obs", "2026-11-20")).data), newer)
        self.assertEqual(json.loads(prod.read(INDEX_KEY).data)["layers"]["snow_obs"]["entries"], [newer])

    def test_promote_replaces_an_older_prod_version(self) -> None:
        prod = LocalStorage(self.tmp / "prod")
        self.publish(seed=1)
        promote(self.storage, prod, "2026-11-20", "2026-11-20")
        newer = self.publish(seed=2, code_version="next")
        promote(self.storage, prod, "2026-11-20", "2026-11-20")
        self.assertEqual(json.loads(prod.read(entry_key("snow_obs", "2026-11-20")).data), newer)


class RasterCheckTests(CatalogTestCase):
    def test_pixel_hash_covers_the_georeferencing_and_nodata(self) -> None:
        array = np.arange(64, dtype=np.uint8).reshape(8, 8)
        base = pixel_hash(write_raster(self.inputs / "a.tif", array, 20, 255))
        self.assertEqual(pixel_hash(write_raster(self.inputs / "b.tif", array, 20, 255)), base)
        self.assertNotEqual(pixel_hash(write_raster(self.inputs / "c.tif", array, 20, 255, left=LEFT + 20)), base)
        self.assertNotEqual(pixel_hash(write_raster(self.inputs / "d.tif", array, 20, 254)), base)

    def test_display_raster_on_another_grid_is_refused(self) -> None:
        files = product(self.inputs, "a")
        shifted = write_raster(self.inputs / "s.tif", np.zeros((4, 64, 64), np.uint8), 20, None, left=LEFT + 20)
        with self.assertRaisesRegex(ValueError, "same grid"):
            publish("snow_obs", "2026-11-20", {**files, "display": shifted}, meta(), self.storage)
        self.assertEqual(self.storage.list(""), [])

    def test_values_below_the_declared_minimum_are_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the declared"):
            publish("snow_obs", "2026-11-20", product(self.inputs, "a"), meta(value_range=[[1, 1]]), self.storage)

    def test_a_cog_without_the_cog_layout_is_refused(self) -> None:
        from rasterio.shutil import copy as real_copy

        def plain_tiff(source, target, **options):
            real_copy(source, target, driver="GTiff")

        with mock.patch("rasterio.shutil.copy", plain_tiff):
            with self.assertRaisesRegex(RuntimeError, "COG layout"):
                self.publish()
        self.assertEqual(self.storage.list(""), [])

    def test_the_display_pixels_are_part_of_the_file_names(self) -> None:
        files = product(self.inputs, "a")
        first = publish("snow_obs", "2026-11-20", files, meta(), LocalStorage(self.tmp / "one"))
        with rasterio.open(files["display"], "r+") as dst:
            dst.write(np.full((64, 64), 7, np.uint8), 1)
        second = publish("snow_obs", "2026-11-20", files, meta(), LocalStorage(self.tmp / "two"))
        self.assertEqual(second["pixel_hash"], first["pixel_hash"])
        self.assertNotEqual(second["pmtiles"], first["pmtiles"])

    def test_categorical_tiles_hold_only_the_display_colours(self) -> None:
        import mercantile
        from PIL import Image
        from pmtiles.reader import MmapSource, Reader
        from rasterio.warp import transform

        size = 64
        checker = (np.indices((size, size)).sum(axis=0) % 2).astype(np.uint8)
        rgba = np.zeros((4, size, size), np.uint8)
        rgba[:3] = checker * 255
        rgba[3] = 255
        files = {
            "data": write_raster(self.inputs / "c.tif", checker, 20, 255),
            "display": write_raster(self.inputs / "c-rgba.tif", rgba, 20, None),
        }
        entry = publish("snow_obs", "2026-11-20", files, meta(), self.storage)
        lons, lats = transform("EPSG:32630", "EPSG:4326", [LEFT + 640], [TOP - 640])
        tile = mercantile.tile(lons[0], lats[0], 14)
        with open(self.storage.root / entry["pmtiles"], "rb") as handle:
            image = np.asarray(
                Image.open(io.BytesIO(Reader(MmapSource(handle)).get(14, tile.x, tile.y))).convert("RGBA")
            )
        visible = image[..., 3] > 0
        self.assertGreater(int(visible.sum()), 0)
        self.assertLessEqual(set(np.unique(image[..., :3][visible]).tolist()), {0, 255})


class CodeVersionTests(unittest.TestCase):
    def test_uses_github_sha_in_actions_and_head_locally(self) -> None:
        with mock.patch.dict(os.environ, {"GITHUB_SHA": "abc123"}):
            self.assertEqual(code_version(), "abc123")
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        with mock.patch.dict(os.environ, {"GITHUB_SHA": ""}):
            self.assertEqual(code_version(), head)


if __name__ == "__main__":
    unittest.main()
