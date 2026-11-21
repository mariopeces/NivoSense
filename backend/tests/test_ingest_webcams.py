import hashlib
import unittest
from pathlib import Path

from backend.ingest_webcams import (
    PLACEHOLDER_MD5,
    parse_datex_cameras,
    probe_camera_image,
)


PLACEHOLDER_BODY = (Path(__file__).parent / "fixtures" / "dgt_placeholder.jpg").read_bytes()


FEED = """<?xml version="1.0" encoding="UTF-8"?>
<d2:payload xmlns:d2="urn:payload" xmlns:device="urn:device" xmlns:loc="urn:location" xmlns:ext="urn:extension">
  <device:device id="312">
    <device:typeOfDevice>camera</device:typeOfDevice>
    <device:lastUpdateOfDeviceInformation>2026-10-18T12:00:00+02:00</device:lastUpdateOfDeviceInformation>
    <device:pointLocation>
      <loc:roadName>A-395</loc:roadName>
      <loc:roadDestination>SIERRA NEVADA</loc:roadDestination>
      <loc:latitude>37.105434</loc:latitude>
      <loc:longitude>-3.426944</loc:longitude>
      <ext:kilometerPoint>28.9</ext:kilometerPoint>
      <ext:province>GRANADA</ext:province>
    </device:pointLocation>
    <ext:deviceUrl>https://example.test/312.jpg</ext:deviceUrl>
  </device:device>
  <device:device id="outside">
    <device:typeOfDevice>camera</device:typeOfDevice>
    <loc:latitude>40.0</loc:latitude>
    <loc:longitude>-3.4</loc:longitude>
  </device:device>
  <device:device id="not-camera">
    <device:typeOfDevice>weatherStation</device:typeOfDevice>
    <loc:latitude>37.1</loc:latitude>
    <loc:longitude>-3.4</loc:longitude>
  </device:device>
</d2:payload>
"""


class ParseDatexCamerasTest(unittest.TestCase):
    def test_parses_namespaced_feed_and_filters_bbox_and_type(self) -> None:
        cameras = parse_datex_cameras(
            FEED,
            (-3.55, 36.92, -2.95, 37.18),
            "https://example.test/feed.xml",
            "DGT",
        )

        self.assertEqual(len(cameras), 1)
        self.assertEqual(cameras[0]["id"], "dgt-312")
        self.assertEqual(cameras[0]["name"], "A-395 · PK 28.9")
        self.assertEqual(cameras[0]["location"], "GRANADA · SIERRA NEVADA")
        self.assertEqual(cameras[0]["latitude"], 37.105434)
        self.assertEqual(cameras[0]["image_url"], "https://example.test/312.jpg")
        self.assertIsNone(cameras[0]["captured_at"])

    def test_discards_unsafe_image_url(self) -> None:
        feed = FEED.replace("https://example.test/312.jpg", "javascript:alert(1)")

        cameras = parse_datex_cameras(
            feed,
            (-3.55, 36.92, -2.95, 37.18),
            "https://example.test/feed.xml",
            "DGT",
        )

        self.assertIsNone(cameras[0]["image_url"])

    def test_fixture_is_the_known_dgt_placeholder(self) -> None:
        self.assertIn(hashlib.md5(PLACEHOLDER_BODY).hexdigest(), PLACEHOLDER_MD5)

    def test_placeholder_image_marks_camera_offline_and_ignores_last_modified(self) -> None:
        camera = self._camera()

        probe_camera_image(
            camera,
            lambda url: (PLACEHOLDER_BODY, "Sat, 21 Nov 2026 00:23:03 GMT"),
        )

        self.assertTrue(camera["offline"])
        self.assertIsNone(camera["image_url"])
        self.assertIsNone(camera["captured_at"])

    def test_real_image_stays_live_with_last_modified_as_capture_time(self) -> None:
        camera = self._camera()

        probe_camera_image(
            camera,
            lambda url: (b"\xff\xd8 a real frame", "Sat, 21 Nov 2026 09:10:00 GMT"),
        )

        self.assertFalse(camera["offline"])
        self.assertEqual(camera["image_url"], "https://example.test/312.jpg")
        self.assertEqual(camera["captured_at"], "2026-11-21T09:10:00+00:00")

    def test_unreachable_image_keeps_url_without_capture_time(self) -> None:
        camera = self._camera()

        def fail(url: str) -> tuple[bytes, str | None]:
            raise OSError("timed out")

        probe_camera_image(camera, fail)

        self.assertFalse(camera["offline"])
        self.assertEqual(camera["image_url"], "https://example.test/312.jpg")
        self.assertIsNone(camera["captured_at"])

    def test_camera_without_image_is_offline(self) -> None:
        camera = self._camera()
        camera["image_url"] = None

        probe_camera_image(camera, lambda url: self.fail("must not fetch"))

        self.assertTrue(camera["offline"])

    def _camera(self) -> dict:
        return parse_datex_cameras(
            FEED,
            (-3.55, 36.92, -2.95, 37.18),
            "https://example.test/feed.xml",
            "DGT",
        )[0]

    def test_rejects_malformed_xml(self) -> None:
        with self.assertRaises(Exception):
            parse_datex_cameras(
                "<payload>",
                (-3.55, 36.92, -2.95, 37.18),
                "https://example.test/feed.xml",
                "DGT",
            )


if __name__ == "__main__":
    unittest.main()
