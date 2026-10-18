import argparse
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.fetch_snow_observation import (
    PipelineError,
    build_manifest,
    fixture_inputs,
    geometry_bbox,
    run,
    select_latest_products,
    validate_manifest,
)


class CatalogSelectionTests(unittest.TestCase):
    def test_selects_every_tile_from_latest_observation_day(self) -> None:
        catalog = {
            "features": [
                {"id": "older", "properties": {"datetime": "2026-01-09T20:00:00Z"}},
                {"id": "latest-b", "properties": {"datetime": "2026-01-10T21:00:00Z"}},
                {"id": "latest-a", "properties": {"datetime": "2026-01-10T20:00:00Z"}},
            ]
        }

        observed_at, selected = select_latest_products(catalog)

        self.assertEqual(observed_at, datetime(2026, 1, 10, 21, tzinfo=timezone.utc))
        self.assertEqual([item["id"] for item in selected], ["latest-a", "latest-b"])

    def test_rejects_empty_catalog(self) -> None:
        with self.assertRaisesRegex(PipelineError, "no products"):
            select_latest_products({"features": []})


class ManifestTests(unittest.TestCase):
    def test_builds_and_validates_manifest(self) -> None:
        manifest = build_manifest(
            bbox=[-3.5, 36.9, -2.6, 37.2],
            collection="gfsc-collection",
            observed_at=datetime(2026, 1, 10, 20, tzinfo=timezone.utc),
            products=[{"id": "tile-a"}, {"id": "tile-b"}],
            generated_at=datetime(2026, 1, 12, 8, tzinfo=timezone.utc),
            layer_path="gfsc_latest.tif",
            public_base_url="https://example.test/snow",
        )

        validate_manifest(manifest)
        self.assertEqual(manifest["observation"]["freshness"], "current")
        self.assertEqual(manifest["source"]["native_resolution_m"], 60)
        self.assertEqual(manifest["quality"]["band"], 2)
        self.assertEqual(manifest["layer"]["url"], "https://example.test/snow/gfsc_latest.tif")

    def test_rejects_invalid_bbox(self) -> None:
        manifest = build_manifest(
            bbox=[-2.0, 37.0, -3.0, 36.0],
            collection="gfsc-collection",
            observed_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
            products=[{"id": "tile"}],
            generated_at=datetime(2026, 1, 11, tzinfo=timezone.utc),
            layer_path="gfsc_latest.tif",
            public_base_url=None,
        )
        with self.assertRaisesRegex(PipelineError, "bbox"):
            validate_manifest(manifest)


class InputTests(unittest.TestCase):
    def test_reads_bbox_from_geojson(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "area.geojson"
            path.write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {},
                                "geometry": {
                                    "type": "Polygon",
                                    "coordinates": [[[1, 4], [3, 4], [3, 8], [1, 4]]],
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(geometry_bbox(path), [1.0, 4.0, 3.0, 8.0])

    def test_fixture_mode_is_test_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            (fixture / "catalog.json").write_text('{"features": []}', encoding="utf-8")
            (fixture / "observation.tif").write_bytes(b"fixture")
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(PipelineError, "restricted to tests"):
                    fixture_inputs(fixture)

    def test_fixture_pipeline_writes_raster_and_valid_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "fixture"
            output = root / "output"
            fixture.mkdir()
            (fixture / "catalog.json").write_text(
                json.dumps(
                    {
                        "features": [
                            {"id": "tile", "properties": {"datetime": "2026-01-10T20:00:00Z"}}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (fixture / "observation.tif").write_bytes(b"test-raster")
            args = argparse.Namespace(
                area=Path("data/basins.geojson"), output=output, fixture=fixture
            )

            with patch.dict(os.environ, {"NIVOSENSE_TEST_MODE": "1"}, clear=True):
                manifest_path = run(args)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            validate_manifest(manifest)
            self.assertEqual((output / "gfsc_latest.tif").read_bytes(), b"test-raster")
            self.assertEqual(manifest["source"]["item_ids"], ["tile"])


if __name__ == "__main__":
    unittest.main()
