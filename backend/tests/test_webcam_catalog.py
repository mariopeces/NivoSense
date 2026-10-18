import json
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).parents[2]


class WebcamCatalogTest(unittest.TestCase):
    def test_committed_catalog_is_valid_and_inside_configured_region(self) -> None:
        config = json.loads(
            (ROOT / "backend" / "webcam_sources.json").read_text(encoding="utf-8")
        )
        cameras = json.loads(
            (ROOT / "frontend" / "public" / "data" / "webcams.json").read_text(
                encoding="utf-8"
            )
        )
        west, south, east, north = config["region"]["bbox"]
        ids = set()

        for camera in cameras:
            self.assertNotIn(camera["id"], ids)
            ids.add(camera["id"])
            self.assertTrue(camera["name"])
            self.assertLessEqual(west, camera["longitude"])
            self.assertLessEqual(camera["longitude"], east)
            self.assertLessEqual(south, camera["latitude"])
            self.assertLessEqual(camera["latitude"], north)
            if camera["image_url"] is not None:
                self.assertEqual(urlparse(camera["image_url"]).scheme, "https")
            self.assertEqual(urlparse(camera["source_url"]).scheme, "https")
            self.assertTrue(camera["attribution"])


if __name__ == "__main__":
    unittest.main()
