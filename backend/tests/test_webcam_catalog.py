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
            self.assertTrue(camera["provider"])
            if camera["latitude"] is None:
                self.assertIsNone(camera["longitude"])
            else:
                self.assertLessEqual(west, camera["longitude"])
                self.assertLessEqual(camera["longitude"], east)
                self.assertLessEqual(south, camera["latitude"])
                self.assertLessEqual(camera["latitude"], north)
                self.assertEqual(urlparse(camera["position_source"]).scheme, "https")
            self.assertIn(camera["status"], {"live", "offline"})
            if camera["status"] == "offline":
                self.assertIsNone(camera["thumbnail_url"])
                self.assertIsNone(camera["large_url"])
                self.assertIsNone(camera["captured_at"])
            else:
                # The site shows the stored copy of the checked still, never the provider URL.
                for key in ("thumbnail_url", "large_url"):
                    self.assertRegex(
                        camera[key], r"^data/webcam-stills/[a-z0-9-]+/([0-9]{8}T[0-9]{6}Z|undated)-(thumbnail|large)-[0-9a-f]{16}\.jpg$"
                    )
            self.assertEqual(urlparse(camera["source_url"]).scheme, "https")
            self.assertTrue(camera["attribution"])
            if camera["id"].startswith("cetursa-"):
                self.assertEqual(
                    camera["attribution"], "Imagen: Cetursa Sierra Nevada / feratel"
                )


if __name__ == "__main__":
    unittest.main()
