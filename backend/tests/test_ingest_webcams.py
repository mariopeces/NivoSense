import unittest

from backend.ingest_webcams import parse_datex_cameras


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
