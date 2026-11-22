"""GcsStorage against an in-memory stand-in for the google-cloud-storage client, so CI stays offline."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from google.api_core.exceptions import NotFound
from google.api_core.exceptions import PreconditionFailed as GcsPreconditionFailed
from google.cloud.storage.retry import DEFAULT_RETRY, DEFAULT_RETRY_IF_GENERATION_SPECIFIED

from pipelines.catalog import GcsStorage, promote, publish, rebuild_index
from pipelines.catalog.index import INDEX_KEY
from pipelines.catalog.storage import PreconditionFailed
from tests.catalog.helpers import meta, product

# What an authenticated download answers, whatever the object's own metadata says.
DOWNLOAD_CACHE_CONTROL = "no-cache, no-store, max-age=0, must-revalidate"


class FakeBlob:
    def __init__(self, bucket: "FakeBucket", name: str) -> None:
        self.bucket = bucket
        self.name = name
        self.cache_control: str | None = None
        self.content_type: str | None = None
        self.content_encoding: str | None = None
        self.generation: int | None = None
        stored = bucket.objects.get(name)
        if stored:
            self._load(stored)

    def _load(self, stored: dict) -> None:
        self.cache_control = stored["cache_control"]
        self.content_type = stored["content_type"]
        self.content_encoding = stored["content_encoding"]
        self.generation = stored["generation"]

    def _check(self, if_generation_match: int | None) -> None:
        current = self.bucket.objects.get(self.name, {}).get("generation", 0)
        if if_generation_match is not None and if_generation_match != current:
            raise GcsPreconditionFailed(f"412 {self.name}: generation {current}")

    def upload_from_string(self, data: bytes, content_type: str, if_generation_match=None, retry=None) -> None:
        self.bucket.client.calls.append(("upload", self.name, if_generation_match, retry))
        self._check(if_generation_match)
        self.bucket.client.generation += 1
        stored = {
            "data": bytes(data),
            "generation": self.bucket.client.generation,
            "content_type": content_type,
            "cache_control": self.cache_control,
            "content_encoding": self.content_encoding,
        }
        self.bucket.objects[self.name] = stored
        self._load(stored)

    def upload_from_filename(self, filename: str, content_type: str, if_generation_match=None, retry=None) -> None:
        self.upload_from_string(Path(filename).read_bytes(), content_type, if_generation_match, retry)

    def download_as_bytes(self, if_generation_match=None) -> bytes:
        self.bucket.client.calls.append(("download", self.name, if_generation_match))
        if self.name not in self.bucket.objects:
            raise NotFound(self.name)
        self._check(if_generation_match)
        # The real client copies the response headers onto the blob.
        self.cache_control = DOWNLOAD_CACHE_CONTROL
        return self.bucket.objects[self.name]["data"]

    def exists(self) -> bool:
        return self.name in self.bucket.objects


class FakeBucket:
    def __init__(self, client: "FakeClient", name: str) -> None:
        self.client = client
        self.name = name
        self.objects = client.buckets.setdefault(name, {})

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)

    def get_blob(self, name: str) -> FakeBlob | None:
        return FakeBlob(self, name) if name in self.objects else None

    def copy_blob(self, blob: FakeBlob, destination: "FakeBucket", new_name: str, if_generation_match=None) -> None:
        self.client.calls.append(("copy", blob.name, new_name, if_generation_match))
        target = FakeBlob(destination, new_name)
        target._check(if_generation_match)
        self.client.generation += 1
        destination.objects[new_name] = {**self.objects[blob.name], "generation": self.client.generation}


class FakeClient:
    buckets: dict[str, dict[str, dict]] = {}
    calls: list[tuple] = []
    generation = 1_000

    def bucket(self, name: str) -> FakeBucket:
        return FakeBucket(self, name)

    def list_blobs(self, bucket: str, prefix: str = "") -> list[FakeBlob]:
        store = FakeBucket(self, bucket)
        return [FakeBlob(store, name) for name in sorted(self.buckets.get(bucket, {})) if name.startswith(prefix)]


class GcsStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeClient.buckets = {}
        FakeClient.calls = []
        patcher = mock.patch("google.cloud.storage.Client", FakeClient)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.staging = GcsStorage("bucket", "staging/")
        self.objects = FakeClient.buckets["bucket"]

    def test_write_sets_type_and_cache_control_and_never_a_content_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.tif"
            path.write_bytes(b"tiff")
            self.staging.write("layers/a.tif", path, "image/tiff", "public, max-age=31536000, immutable", 0)
        self.staging.write("catalog/index.json", b"{}", "application/json", "no-cache")
        stored = self.objects["staging/layers/a.tif"]
        self.assertEqual(
            (stored["content_type"], stored["cache_control"]), ("image/tiff", "public, max-age=31536000, immutable")
        )
        self.assertEqual(self.objects["staging/catalog/index.json"]["cache_control"], "no-cache")
        for name, stored in self.objects.items():
            self.assertIsNone(stored["content_encoding"], name)

    def test_a_412_becomes_precondition_failed(self) -> None:
        self.staging.write("layers/a.tif", b"1", "image/tiff", "x", if_generation_match=0)
        with self.assertRaises(PreconditionFailed):
            self.staging.write("layers/a.tif", b"2", "image/tiff", "x", if_generation_match=0)
        self.assertEqual(self.objects["staging/layers/a.tif"]["data"], b"1")

    def test_unconditional_writes_are_retried_and_conditional_ones_only_with_their_precondition(self) -> None:
        self.staging.write("catalog/entries/x/2026-11-20.json", b"{}", "application/json", "no-cache")
        self.staging.write("layers/a.tif", b"1", "image/tiff", "x", if_generation_match=0)
        retries = [call[3] for call in FakeClient.calls if call[0] == "upload"]
        self.assertEqual(retries, [DEFAULT_RETRY, DEFAULT_RETRY_IF_GENERATION_SPECIFIED])

    def test_read_returns_the_object_metadata_not_the_download_headers(self) -> None:
        generation = self.staging.write("catalog/index.json", b"{}", "application/json", "no-cache")
        blob = self.staging.read("catalog/index.json")
        self.assertEqual((blob.data, blob.generation, blob.cache_control), (b"{}", generation, "no-cache"))
        self.assertIsNone(self.staging.read("catalog/missing.json"))
        self.assertIn(("download", "staging/catalog/index.json", generation), FakeClient.calls, "read not pinned")

    def test_list_stays_inside_the_prefix_and_strips_it(self) -> None:
        self.staging.write("catalog/entries/a/2026-11-20.json", b"{}", "application/json", "no-cache")
        GcsStorage("bucket", "prod").write("catalog/entries/a/2026-11-19.json", b"{}", "application/json", "no-cache")
        self.assertEqual(self.staging.list("catalog/entries/"), ["catalog/entries/a/2026-11-20.json"])

    def test_copy_between_prefixes_is_server_side_and_keeps_metadata(self) -> None:
        prod = GcsStorage("bucket", "prod/")
        self.staging.write("layers/a.tif", b"1", "image/tiff", "public, max-age=31536000, immutable", 0)
        prod.copy_from(self.staging, "layers/a.tif", if_generation_match=0)
        self.assertIn(("copy", "staging/layers/a.tif", "prod/layers/a.tif", 0), FakeClient.calls)
        self.assertEqual(self.objects["prod/layers/a.tif"]["cache_control"], "public, max-age=31536000, immutable")
        with self.assertRaises(PreconditionFailed):
            prod.copy_from(self.staging, "layers/a.tif", if_generation_match=0)

    def test_publish_rebuild_and_promote_through_gcs(self) -> None:
        prod = GcsStorage("bucket", "prod/")
        with tempfile.TemporaryDirectory() as tmp:
            for date, seed in (("2026-11-19", 1), ("2026-11-20", 2)):
                publish("snow_obs", date, product(Path(tmp), date, seed=seed), meta(), self.staging)
            rebuild_index(self.staging)
            promote(self.staging, prod, "2026-11-20", "2026-11-20")
        staging_index = json.loads(self.objects["staging/" + INDEX_KEY]["data"])
        prod_index = json.loads(self.objects["prod/" + INDEX_KEY]["data"])
        self.assertEqual(staging_index["layers"]["snow_obs"]["dates"], ["2026-11-19", "2026-11-20"])
        self.assertEqual(prod_index["layers"]["snow_obs"]["dates"], ["2026-11-20"])
        index_writes = [call for call in FakeClient.calls if call[0] == "upload" and call[1].endswith(INDEX_KEY)]
        self.assertTrue(all(call[2] is not None for call in index_writes), "index written without a precondition")


if __name__ == "__main__":
    unittest.main()
