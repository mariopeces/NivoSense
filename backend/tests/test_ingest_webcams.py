import hashlib
import json
import unittest
import urllib.error
from pathlib import Path

from backend.ingest_webcams import (
    DEFAULT_CONFIG,
    PLACEHOLDER_MD5,
    ImageResponse,
    build_catalog,
    image_problem,
    parse_datex_cameras,
    probe_camera_image,
    static_cameras,
)


FIXTURES = Path(__file__).parent / "fixtures"
DGT_PLACEHOLDER = (FIXTURES / "dgt_placeholder.jpg").read_bytes()
FERATEL_PLACEHOLDER = (FIXTURES / "feratel_placeholder.jpg").read_bytes()
# Zona Borreguiles view 0 (hotspot size 37) as served on 2026-11-21, with the
# Last-Modified feratel sent; the frame shows 18:08 local time.
FERATEL_FRAME = (FIXTURES / "feratel_15111_0.jpg").read_bytes()
FERATEL_LAST_MODIFIED = "Sat, 21 Nov 2026 17:08:05 GMT"
BBOX = (-3.55, 36.92, -2.95, 37.18)


def jpeg(body: bytes, last_modified: str | None = None) -> ImageResponse:
    return ImageResponse(200, "image/jpeg", len(body), body, last_modified)


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
        cameras = parse_datex_cameras(FEED, BBOX, "https://example.test/feed.xml", "DGT")

        self.assertEqual(len(cameras), 1)
        self.assertEqual(cameras[0]["id"], "dgt-312")
        self.assertEqual(cameras[0]["name"], "A-395 · PK 28.9")
        self.assertEqual(cameras[0]["location"], "GRANADA · SIERRA NEVADA")
        self.assertEqual(cameras[0]["provider"], "DGT")
        self.assertEqual(cameras[0]["latitude"], 37.105434)
        self.assertEqual(cameras[0]["thumbnail_url"], "https://example.test/312.jpg")
        self.assertEqual(cameras[0]["large_url"], "https://example.test/312.jpg")
        self.assertIsNone(cameras[0]["captured_at"])

    def test_discards_unsafe_image_url(self) -> None:
        feed = FEED.replace("https://example.test/312.jpg", "javascript:alert(1)")

        cameras = parse_datex_cameras(feed, BBOX, "https://example.test/feed.xml", "DGT")

        self.assertIsNone(cameras[0]["thumbnail_url"])

    def test_rejects_malformed_xml(self) -> None:
        with self.assertRaises(Exception):
            parse_datex_cameras("<payload>", BBOX, "https://example.test/feed.xml", "DGT")


class ImageCheckTest(unittest.TestCase):
    def test_fixtures_are_the_known_placeholders(self) -> None:
        self.assertIn(hashlib.md5(DGT_PLACEHOLDER).hexdigest(), PLACEHOLDER_MD5)
        self.assertIn(hashlib.md5(FERATEL_PLACEHOLDER).hexdigest(), PLACEHOLDER_MD5)

    def test_real_frame_passes(self) -> None:
        self.assertIsNone(image_problem(jpeg(FERATEL_FRAME)))

    def test_placeholders_fail(self) -> None:
        self.assertEqual(image_problem(jpeg(DGT_PLACEHOLDER)), "provider placeholder")
        self.assertEqual(image_problem(jpeg(FERATEL_PLACEHOLDER)), "provider placeholder")

    def test_non_200_fails(self) -> None:
        response = ImageResponse(203, "image/jpeg", None, FERATEL_FRAME, None)
        self.assertEqual(image_problem(response), "HTTP 203")

    def test_wrong_content_type_fails(self) -> None:
        response = ImageResponse(200, "text/html; charset=utf-8", None, b"<html>", None)
        self.assertEqual(image_problem(response), "content type text/html")

    def test_short_body_fails(self) -> None:
        cut = FERATEL_FRAME[:1000]
        self.assertEqual(
            image_problem(ImageResponse(200, "image/jpeg", len(FERATEL_FRAME), cut, None)),
            f"truncated: 1000 of {len(FERATEL_FRAME)} bytes",
        )
        self.assertEqual(image_problem(jpeg(cut)), "not a complete JPEG")

    def test_empty_body_fails(self) -> None:
        self.assertEqual(image_problem(jpeg(b"")), "empty body")


class ProbeCameraImageTest(unittest.TestCase):
    def test_placeholder_marks_camera_offline_and_ignores_last_modified(self) -> None:
        camera = self._feratel_camera()

        record = probe_camera_image(
            camera, lambda url: jpeg(FERATEL_PLACEHOLDER, "Sat, 21 Nov 2026 23:12:53 GMT")
        )

        self.assertEqual(camera["status"], "offline")
        self.assertIsNone(camera["thumbnail_url"])
        self.assertIsNone(camera["large_url"])
        self.assertIsNone(camera["captured_at"])
        self.assertEqual(record["problem"], "provider placeholder")

    def test_real_frame_is_live_with_last_modified_as_capture_time(self) -> None:
        camera = self._feratel_camera()
        fetched = []

        def fetch(url: str) -> ImageResponse:
            fetched.append(url)
            return jpeg(FERATEL_FRAME, FERATEL_LAST_MODIFIED)

        record = probe_camera_image(camera, fetch)

        self.assertEqual(camera["status"], "live")
        self.assertEqual(camera["captured_at"], "2026-11-21T17:08:05+00:00")
        self.assertEqual(fetched, [camera["thumbnail_url"], camera["large_url"]])
        self.assertEqual(record["images"][0]["md5"], hashlib.md5(FERATEL_FRAME).hexdigest())

    def test_placeholder_on_large_image_only_is_offline(self) -> None:
        camera = self._feratel_camera()
        large = camera["large_url"]

        probe_camera_image(
            camera,
            lambda url: jpeg(FERATEL_PLACEHOLDER if url == large else FERATEL_FRAME),
        )

        self.assertEqual(camera["status"], "offline")

    def test_same_url_for_both_sizes_is_fetched_once(self) -> None:
        camera = parse_datex_cameras(FEED, BBOX, "https://example.test/feed.xml", "DGT")[0]
        fetched = []

        def fetch(url: str) -> ImageResponse:
            fetched.append(url)
            return jpeg(FERATEL_FRAME, FERATEL_LAST_MODIFIED)

        probe_camera_image(camera, fetch)

        self.assertEqual(fetched, ["https://example.test/312.jpg"])

    def test_http_error_is_offline(self) -> None:
        camera = self._feratel_camera()

        def fail(url: str) -> ImageResponse:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]

        record = probe_camera_image(camera, fail)

        self.assertEqual(camera["status"], "offline")
        self.assertEqual(record["problem"], "HTTP 404")

    def test_unreachable_image_is_offline(self) -> None:
        camera = self._feratel_camera()

        def fail(url: str) -> ImageResponse:
            raise OSError("timed out")

        probe_camera_image(camera, fail)

        self.assertEqual(camera["status"], "offline")
        self.assertIsNone(camera["captured_at"])

    def test_camera_without_image_is_offline(self) -> None:
        camera = parse_datex_cameras(
            FEED.replace("https://example.test/312.jpg", ""), BBOX, "https://example.test/feed.xml", "DGT"
        )[0]

        probe_camera_image(camera, lambda url: self.fail("must not fetch"))

        self.assertEqual(camera["status"], "offline")

    def _feratel_camera(self) -> dict:
        config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        source = next(source for source in config["sources"] if source["id"] == "cetursa")
        cameras = static_cameras(source, BBOX)
        return next(camera for camera in cameras if camera["id"] == "cetursa-15111-0")


class CetursaSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        self.source = next(source for source in config["sources"] if source["id"] == "cetursa")

    def test_every_cetursa_camera_carries_the_agreed_credit(self) -> None:
        for camera in static_cameras(self.source, BBOX):
            self.assertEqual(camera["attribution"], "Imagen: Cetursa Sierra Nevada / feratel")
            self.assertEqual(camera["source_url"], "https://sierranevada.es/es/webcams/")

    def test_covers_feratel_cams_15110_to_15114_and_pradollano(self) -> None:
        ids = {camera["id"] for camera in static_cameras(self.source, BBOX)}
        for cam in range(15110, 15115):
            self.assertTrue(any(i.startswith(f"cetursa-{cam}-") for i in ids), cam)
        self.assertIn("cetursa-pradollano-c1", ids)

    def test_feratel_urls_are_stills_never_video(self) -> None:
        for camera in static_cameras(self.source, BBOX):
            for key in ("thumbnail_url", "large_url"):
                self.assertRegex(camera[key].split("?")[0], r"\.jpe?g$")

    def test_position_outside_region_is_rejected(self) -> None:
        source = dict(self.source)
        source["cameras"] = [dict(self.source["cameras"][1], latitude=40.0)]
        with self.assertRaises(ValueError):
            static_cameras(source, BBOX)

    def test_position_without_its_source_is_rejected(self) -> None:
        source = dict(self.source)
        source["cameras"] = [dict(self.source["cameras"][1], position_source=None)]
        with self.assertRaises(ValueError):
            static_cameras(source, BBOX)

    def test_unknown_position_stays_null(self) -> None:
        pradollano = next(
            camera for camera in static_cameras(self.source, BBOX) if camera["id"] == "cetursa-pradollano-c1"
        )
        self.assertIsNone(pradollano["latitude"])
        self.assertIsNone(pradollano["longitude"])

    def test_build_catalog_probes_every_static_camera(self) -> None:
        config = {"region": {"bbox": list(BBOX)}, "sources": [self.source]}

        cameras, log = build_catalog(config, lambda url: jpeg(FERATEL_FRAME, FERATEL_LAST_MODIFIED))

        self.assertEqual(len(cameras), len(self.source["cameras"]))
        self.assertEqual(len(log), len(cameras))
        self.assertTrue(all(camera["status"] == "live" for camera in cameras))


if __name__ == "__main__":
    unittest.main()
