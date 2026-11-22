import json
import unittest
from pathlib import Path

from scripts import build_ski_resort

ROOT = Path(__file__).resolve().parent.parent


class SkiResortTest(unittest.TestCase):
    def test_closed_way_becomes_a_polygon(self) -> None:
        nodes = [{"lon": -3.40, "lat": 37.09}, {"lon": -3.39, "lat": 37.09}, {"lon": -3.39, "lat": 37.10}]
        element = {"id": 1, "tags": {"name": "x"}, "geometry": nodes + nodes[:1]}
        feature = build_ski_resort.to_feature(element)
        self.assertEqual(feature["geometry"]["type"], "Polygon")
        self.assertEqual(feature["properties"], {"name": "x", "osm_id": "way/1"})

    def test_open_way_is_rejected(self) -> None:
        nodes = [{"lon": -3.40, "lat": 37.09}, {"lon": -3.39, "lat": 37.09}, {"lon": -3.39, "lat": 37.10}]
        with self.assertRaises(ValueError):
            build_ski_resort.to_feature({"id": 1, "tags": {}, "geometry": nodes})

    def test_committed_outline_overlaps_the_q4_crest_box(self) -> None:
        collection = json.loads((ROOT / "data" / "ski_resort.geojson").read_text(encoding="utf-8"))
        self.assertIn("OpenStreetMap way 654498540", collection["metadata"]["source"])
        ring = collection["features"][0]["geometry"]["coordinates"][0]
        fixture = json.loads((ROOT / "qa" / "fixtures" / "q4_crest_2026-11-20.json").read_text(encoding="utf-8"))
        self.assertEqual(fixture["exclude"]["geometry"], "data/ski_resort.geojson")
        west, south, east, north = fixture["bbox"]
        self.assertTrue(any(west <= lon <= east and south <= lat <= north for lon, lat in ring))


if __name__ == "__main__":
    unittest.main()
