import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import ClassVar
from unittest import mock
from urllib.parse import urlparse

from PIL import Image, ImageEnhance

from backend.ingest_webcams import (
    DEFAULT_CONFIG,
    PLACEHOLDER_DHASH,
    PLACEHOLDER_MD5,
    ImageResponse,
    LocalStillStore,
    build_catalog,
    dhash,
    fetch_image,
    image_problem,
    load_area,
    parse_datex_cameras,
    parse_http_date,
    picture_problem,
    probe_camera_image,
    static_cameras,
)

FIXTURES = Path(__file__).parent / "fixtures"
DGT_PLACEHOLDER = (FIXTURES / "dgt_placeholder.jpg").read_bytes()
# DGT's black "No video" frame, served on 2026-11-22 with the current time burned in
# (new bytes on every fetch): the reference copy from cam 168121, cam 168113, and cam
# 168099 (all black, no logo).
DGT_NO_VIDEO = (Path(__file__).parents[1] / "webcam_placeholders" / "dgt_no_video.jpg").read_bytes()
DGT_NO_VIDEO_168113 = (FIXTURES / "dgt_no_video_168113.jpg").read_bytes()
DGT_NO_VIDEO_168099 = (FIXTURES / "dgt_no_video_168099.jpg").read_bytes()
# Real DGT night frames served on 2026-11-22: A-382 PK 6+7 (cam 1310, burned-in
# 05:32:06 UTC, re-served with Last-Modified 05:47:01, 05:57:01 and 06:02:01) and
# A-44 PK 158+300 (cam 169624, burned-in 05:53:40 UTC served with Last-Modified
# 05:54:01 and re-stamped 05:58:01; the next frame, burned-in 05:58:40, came at 06:00:02).
DGT_NIGHT_1310 = (FIXTURES / "dgt_night_1310.jpg").read_bytes()
# Dead DGT frames of other colours, 2026-11-22: cam 168074's blue "no signal" (as
# served) and cam 164375's solid green (cropped from the G-Data round 2 evidence
# sheet; the cam serves a real view again).
DGT_BLUE = (FIXTURES / "dgt_blue_no_signal_168074.jpg").read_bytes()
DGT_GREEN = (FIXTURES / "dgt_solid_green_164375.jpg").read_bytes()
# Cam 162889 (N-351): a frame burned in on 2026-10-02, still served on 2026-11-22
# with Last-Modified 07:52:01 GMT that day.
DGT_FROZEN_162889 = (FIXTURES / "dgt_frozen_162889.jpg").read_bytes()
# Real bluish fog, cam 163996 (Puerto de Navacerrada), 2026-11-22 09:05 CET.
DGT_FOG = (FIXTURES / "dgt_fog_163996.jpg").read_bytes()
DGT_NIGHT_169624 = (FIXTURES / "dgt_night_169624_0553.jpg").read_bytes()
DGT_NIGHT_169624_NEXT = (FIXTURES / "dgt_night_169624_0558.jpg").read_bytes()
# feratel's dead-camera frame as served for cam 15110 on 2026-11-21: German at
# hotspot size 37 (the default), Spanish and English at 37, German at 38, Dutch at 39.
FERATEL_PLACEHOLDER = (FIXTURES / "feratel_placeholder.jpg").read_bytes()
FERATEL_PLACEHOLDER_ES = (FIXTURES / "feratel_placeholder_es.jpg").read_bytes()
FERATEL_PLACEHOLDER_EN = (FIXTURES / "feratel_placeholder_en.jpg").read_bytes()
FERATEL_PLACEHOLDER_38 = (FIXTURES / "feratel_placeholder_38.jpg").read_bytes()
FERATEL_PLACEHOLDER_NL_39 = (FIXTURES / "feratel_placeholder_nl_39.jpg").read_bytes()
# Real frames (hotspot size 37) served on 2026-11-21: Zona Borreguiles view 0 with
# the Last-Modified feratel sent (the frame shows 18:08 local time), and Universiada.
FERATEL_FRAME = (FIXTURES / "feratel_15111_0.jpg").read_bytes()
FERATEL_FRAME_OTHER = (FIXTURES / "feratel_15113_2.jpg").read_bytes()
# Real Cetursa frames before dawn on 2026-11-22 (burned-in 07:08 and 07:11 CET):
# Borreguiles view 2 all but black, Montebajo view 2 with a faint sky.
FERATEL_NIGHT = (FIXTURES / "feratel_15111_2_night.jpg").read_bytes()
FERATEL_DAWN = (FIXTURES / "feratel_15113_2_dawn.jpg").read_bytes()
FERATEL_LAST_MODIFIED = "Sat, 21 Nov 2026 17:08:05 GMT"
FERATEL_DATE = "Sat, 21 Nov 2026 23:22:54 GMT"
BBOX = (-3.55, 36.92, -2.95, 37.18)


def jpeg(
    body: bytes,
    last_modified: str | None = FERATEL_LAST_MODIFIED,
    date: str | None = FERATEL_DATE,
) -> ImageResponse:
    return ImageResponse(200, "image/jpeg", len(body), body, last_modified, date)


def without_md5(body: bytes) -> mock._patch:
    """Drop one fingerprint so a test exercises the guards behind the exact match."""
    return mock.patch(
        "backend.ingest_webcams.PLACEHOLDER_MD5",
        PLACEHOLDER_MD5 - {hashlib.md5(body).hexdigest()},
    )


def cetursa_source() -> dict:
    config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    return next(source for source in config["sources"] if source["id"] == "cetursa")


DGT_PAGE = "https://www.dgt.es/conoce-el-estado-del-trafico/camaras-de-trafico/"


def dgt_source() -> dict:
    return {"id": "dgt", "type": "datex2", "url": "https://example.test/feed.xml", "page": DGT_PAGE,
            "attribution": "DGT", "provider": "DGT", "live_only": True}


def feratel_camera(camera_id: str = "cetursa-15111-0") -> dict:
    return next(c for c in static_cameras(cetursa_source(), BBOX) if c["id"] == camera_id)


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
        with self.assertRaises(ET.ParseError):
            parse_datex_cameras("<payload>", BBOX, "https://example.test/feed.xml", "DGT")


class FetchImageTest(unittest.TestCase):
    def test_pins_the_request_language(self) -> None:
        sent = []

        class Response:
            status = 200
            headers: ClassVar[dict[str, str]] = {"Content-Type": "image/jpeg"}

            def read(self) -> bytes:
                return FERATEL_FRAME

            def __enter__(self):
                return self

            def __exit__(self, *args) -> None:
                return None

        def urlopen(request, timeout):
            sent.append(request)
            return Response()

        with mock.patch("urllib.request.urlopen", urlopen):
            fetch_image("https://wtvhspt.feratel.com/hotspot/37/15111/0.jpeg")

        self.assertEqual(sent[0].get_header("Accept-language"), "de")


class ImageCheckTest(unittest.TestCase):
    def test_fixtures_are_the_known_placeholders(self) -> None:
        for body in (
            DGT_PLACEHOLDER,
            FERATEL_PLACEHOLDER,
            FERATEL_PLACEHOLDER_ES,
            FERATEL_PLACEHOLDER_EN,
            FERATEL_PLACEHOLDER_38,
            FERATEL_PLACEHOLDER_NL_39,
        ):
            self.assertIn(hashlib.md5(body).hexdigest(), PLACEHOLDER_MD5)

    def test_reference_dhashes_match_the_fixtures(self) -> None:
        self.assertEqual(dhash(FERATEL_PLACEHOLDER), PLACEHOLDER_DHASH[0])
        self.assertEqual(dhash(DGT_PLACEHOLDER), PLACEHOLDER_DHASH[1])

    def test_real_frames_pass(self) -> None:
        self.assertIsNone(image_problem(jpeg(FERATEL_FRAME), "feratel"))
        self.assertIsNone(image_problem(jpeg(FERATEL_FRAME_OTHER), "feratel"))

    def test_fingerprinted_placeholders_fail(self) -> None:
        for body in (DGT_PLACEHOLDER, FERATEL_PLACEHOLDER, FERATEL_PLACEHOLDER_ES, FERATEL_PLACEHOLDER_EN):
            self.assertEqual(image_problem(jpeg(body), "feratel"), "provider placeholder")

    def test_feratel_frame_stamped_at_request_time_fails(self) -> None:
        # The real size-38 placeholder with the headers feratel sent for it.
        stamp = "Sat, 21 Nov 2026 23:25:58 GMT"
        with without_md5(FERATEL_PLACEHOLDER_38):
            problem = image_problem(jpeg(FERATEL_PLACEHOLDER_38, stamp, stamp), "feratel")
        self.assertEqual(problem, "generated on request (Last-Modified equals Date)")

    def test_request_time_guard_applies_to_feratel_only(self) -> None:
        stamp = "Sat, 21 Nov 2026 23:11:24 GMT"
        self.assertIsNone(image_problem(jpeg(FERATEL_FRAME, stamp, stamp), "Cetursa Sierra Nevada"))

    def test_unknown_placeholder_rendition_fails_on_perceptual_match(self) -> None:
        # Unfingerprinted and with a real-looking Last-Modified: only the dHash catches it.
        for body in (FERATEL_PLACEHOLDER_38, FERATEL_PLACEHOLDER_NL_39, FERATEL_PLACEHOLDER_ES):
            with without_md5(body):
                problem = image_problem(jpeg(body), "feratel")
            self.assertIsNotNone(problem)
            self.assertTrue(problem.startswith("looks like a provider placeholder"), problem)

    def test_non_200_fails(self) -> None:
        response = ImageResponse(203, "image/jpeg", None, FERATEL_FRAME, None, None)
        self.assertEqual(image_problem(response, "feratel"), "HTTP 203")

    def test_wrong_content_type_fails(self) -> None:
        response = ImageResponse(200, "text/html; charset=utf-8", None, b"<html>", None, None)
        self.assertEqual(image_problem(response, "feratel"), "content type text/html")

    def test_short_body_fails(self) -> None:
        cut = FERATEL_FRAME[:1000]
        self.assertEqual(
            image_problem(ImageResponse(200, "image/jpeg", len(FERATEL_FRAME), cut, None, None), "feratel"),
            f"truncated: 1000 of {len(FERATEL_FRAME)} bytes",
        )
        self.assertEqual(image_problem(jpeg(cut), "feratel"), "not a complete JPEG")

    def test_empty_body_fails(self) -> None:
        self.assertEqual(image_problem(jpeg(b""), "feratel"), "empty body")


class ProbeCameraImageTest(unittest.TestCase):
    def test_placeholder_marks_camera_offline_and_ignores_last_modified(self) -> None:
        camera = feratel_camera()

        record, bodies = probe_camera_image(
            camera, lambda url: jpeg(FERATEL_PLACEHOLDER, "Sat, 21 Nov 2026 23:12:53 GMT")
        )

        self.assertEqual(camera["status"], "offline")
        self.assertIsNone(camera["thumbnail_url"])
        self.assertIsNone(camera["large_url"])
        self.assertIsNone(camera["captured_at"])
        self.assertEqual(record["problem"], "provider placeholder")
        self.assertEqual(bodies, {})

    def test_spanish_placeholder_with_feratel_headers_is_offline(self) -> None:
        camera = feratel_camera()
        stamp = "Sat, 21 Nov 2026 23:25:31 GMT"

        with without_md5(FERATEL_PLACEHOLDER_ES):
            probe_camera_image(camera, lambda url: jpeg(FERATEL_PLACEHOLDER_ES, stamp, stamp))

        self.assertEqual(camera["status"], "offline")

    def test_real_frame_is_live_with_last_modified_as_capture_time(self) -> None:
        camera = feratel_camera()
        fetched = []

        def fetch(url: str) -> ImageResponse:
            fetched.append(url)
            return jpeg(FERATEL_FRAME)

        record, bodies = probe_camera_image(camera, fetch)

        self.assertEqual(camera["status"], "live")
        self.assertEqual(camera["captured_at"], "2026-11-21T17:08:05+00:00")
        self.assertEqual(fetched, [camera["thumbnail_url"], camera["large_url"]])
        self.assertEqual(bodies, {"thumbnail": FERATEL_FRAME, "large": FERATEL_FRAME})
        self.assertEqual(record["images"][0]["md5"], hashlib.md5(FERATEL_FRAME).hexdigest())

    def test_placeholder_on_large_image_only_is_offline(self) -> None:
        camera = feratel_camera()
        large = camera["large_url"]

        probe_camera_image(
            camera,
            lambda url: jpeg(FERATEL_PLACEHOLDER_38 if url == large else FERATEL_FRAME),
        )

        self.assertEqual(camera["status"], "offline")

    def test_sizes_with_different_capture_times_are_offline(self) -> None:
        camera = feratel_camera()
        large = camera["large_url"]

        record, _ = probe_camera_image(
            camera,
            lambda url: jpeg(FERATEL_FRAME, "Sat, 21 Nov 2026 16:58:05 GMT" if url == large else FERATEL_LAST_MODIFIED),
        )

        self.assertEqual(camera["status"], "offline")
        self.assertEqual(record["problem"], "thumbnail and large image carry different capture times")

    def test_same_url_for_both_sizes_is_fetched_once(self) -> None:
        camera = parse_datex_cameras(FEED, BBOX, "https://example.test/feed.xml", "DGT")[0]
        fetched = []

        def fetch(url: str) -> ImageResponse:
            fetched.append(url)
            return jpeg(FERATEL_FRAME)

        probe_camera_image(camera, fetch)

        self.assertEqual(fetched, ["https://example.test/312.jpg"])
        self.assertEqual(camera["status"], "live")

    def test_http_error_is_offline(self) -> None:
        camera = feratel_camera()

        def fail(url: str) -> ImageResponse:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]

        record, _ = probe_camera_image(camera, fail)

        self.assertEqual(camera["status"], "offline")
        self.assertEqual(record["problem"], "HTTP 404")

    def test_unreachable_image_is_offline(self) -> None:
        camera = feratel_camera()

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


class BuildCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = LocalStillStore(Path(self.tmp.name), "data/webcam-stills/")

    def config(self, camera_ids: list[str]) -> dict:
        source = cetursa_source()
        source["cameras"] = [c for c in source["cameras"] if c["id"] in camera_ids]
        return {"region": {"bbox": list(BBOX)}, "sources": [source]}

    def test_card_points_at_the_stored_checked_bytes(self) -> None:
        cameras, log = build_catalog(self.config(["cetursa-15111-0"]), self.store, lambda url: jpeg(FERATEL_FRAME))

        camera = cameras[0]
        digest = hashlib.sha256(FERATEL_FRAME).hexdigest()[:16]
        self.assertEqual(
            camera["thumbnail_url"],
            f"data/webcam-stills/cetursa-15111-0/20261121T170805Z-thumbnail-{digest}.jpg",
        )
        stored = Path(self.tmp.name) / camera["thumbnail_url"].removeprefix("data/webcam-stills/")
        self.assertEqual(stored.read_bytes(), FERATEL_FRAME)
        self.assertEqual(log[0]["stored"], [camera["thumbnail_url"], camera["large_url"]])

    def test_identical_bytes_from_two_cameras_are_offline_and_not_stored(self) -> None:
        # The unfingerprinted size-38 placeholder, with a real-looking Last-Modified, from
        # two cams; without the MD5 or the dHash only the shared-bytes guard catches it.
        with without_md5(FERATEL_PLACEHOLDER_38), mock.patch(
            "backend.ingest_webcams.PLACEHOLDER_DHASH_MAX_BITS", -1
        ):
            cameras, log = build_catalog(
                self.config(["cetursa-15110-2", "cetursa-15114-0", "cetursa-15111-0"]),
                self.store,
                lambda url: jpeg(FERATEL_FRAME if "/15111/" in url else FERATEL_PLACEHOLDER_38),
            )

        status = {camera["id"]: camera["status"] for camera in cameras}
        self.assertEqual(
            status,
            {"cetursa-15110-2": "offline", "cetursa-15114-0": "offline", "cetursa-15111-0": "live"},
        )
        problems = {record["id"]: record["problem"] for record in log if "id" in record}
        self.assertEqual(problems["cetursa-15110-2"], "identical bytes served by another camera")
        stored = sorted(p.parent.name for p in Path(self.tmp.name).rglob("*.jpg"))
        self.assertEqual(stored, ["cetursa-15111-0"])

    def test_offline_camera_points_to_no_image(self) -> None:
        cameras, _ = build_catalog(self.config(["cetursa-15110-2"]), self.store, lambda url: jpeg(FERATEL_PLACEHOLDER))

        self.assertIsNone(cameras[0]["thumbnail_url"])
        self.assertIsNone(cameras[0]["large_url"])
        self.assertEqual(list(Path(self.tmp.name).rglob("*.jpg")), [])


    def test_feed_outage_leaves_other_sources_ingesting(self) -> None:
        config = self.config(["cetursa-15111-0"])
        config["sources"].insert(0, dgt_source())

        def feed_down(url: str) -> bytes:
            raise urllib.error.URLError("Name or service not known")

        cameras, log = build_catalog(config, self.store, lambda url: jpeg(FERATEL_FRAME), feed_down)

        self.assertEqual([(c["id"], c["status"]) for c in cameras], [("cetursa-15111-0", "live")])
        self.assertEqual(log[0]["source"], "dgt")
        self.assertEqual(log[0]["status"], "failed")

    def test_malformed_feed_leaves_other_sources_ingesting(self) -> None:
        config = self.config(["cetursa-15111-0"])
        config["sources"].insert(0, dgt_source())

        cameras, _ = build_catalog(config, self.store, lambda url: jpeg(FERATEL_FRAME), lambda url: b"<payload>")

        self.assertEqual([c["status"] for c in cameras], ["live"])

    def test_unexpected_error_on_one_camera_marks_only_it_offline(self) -> None:
        def fetch(url: str) -> ImageResponse:
            if "/15110/" in url:
                raise RuntimeError("bug")
            return jpeg(FERATEL_FRAME)

        cameras, log = build_catalog(self.config(["cetursa-15110-2", "cetursa-15111-0"]), self.store, fetch)

        self.assertEqual({c["id"]: c["status"] for c in cameras},
                         {"cetursa-15110-2": "offline", "cetursa-15111-0": "live"})
        self.assertIsNone(cameras[0]["thumbnail_url"])
        self.assertIn("RuntimeError", log[0]["problem"])

    def test_one_url_for_both_sizes_is_stored_once(self) -> None:
        cameras, _ = build_catalog(self.config(["cetursa-pradollano-c1"]), self.store, lambda url: jpeg(FERATEL_FRAME))

        self.assertEqual(cameras[0]["large_url"], cameras[0]["thumbnail_url"])
        self.assertEqual(len(list(Path(self.tmp.name).rglob("*.jpg"))), 1)


class LiveOnlyFixture:
    """A DGT feed with cams 312 and 313 next to one Cetursa view, on a real still store."""

    FEED_TWO = FEED.replace(
        '<device:device id="outside">',
        """<device:device id="313">
    <device:typeOfDevice>camera</device:typeOfDevice>
    <loc:latitude>37.15</loc:latitude>
    <loc:longitude>-3.5</loc:longitude>
    <ext:deviceUrl>https://example.test/313.jpg</ext:deviceUrl>
  </device:device>
  <device:device id="outside">""",
    )

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = LocalStillStore(self.root, "data/webcam-stills/")
        source = cetursa_source()
        source["cameras"] = [c for c in source["cameras"] if c["id"] == "cetursa-15110-2"]
        self.config = {"region": {"bbox": list(BBOX)}, "sources": [dgt_source(), source]}

    def run_ingest(
        self,
        dgt_312: bytes,
        last_modified: str = FERATEL_LAST_MODIFIED,
        now: str = "Sat, 21 Nov 2026 17:10:00 GMT",
        restore: str | None = None,
    ) -> tuple[list[dict], list[dict]]:
        def fetch(url: str) -> ImageResponse:
            if url.endswith("/312.jpg"):
                return jpeg(dgt_312, last_modified, now)
            if url.endswith("/313.jpg"):
                return jpeg(FERATEL_FRAME_OTHER, now, now)
            return jpeg(FERATEL_PLACEHOLDER)

        return build_catalog(
            self.config,
            self.store,
            fetch,
            lambda url: self.FEED_TWO.encode(),
            now=parse_http_date(now),
            history_restore=restore,
        )

    def seen_other_frames(self) -> None:
        """A history in which the previous run saw other frames on both DGT cams."""
        frames = {cid: {"sha256": "0" * 64, "captured_at": None, "confirmed": True} for cid in ("dgt-312", "dgt-313")}
        self.store.save_state({"frames": frames})



class LiveOnlySourceTest(LiveOnlyFixture, unittest.TestCase):
    """DGT cams are listed only while their image passes the check (task T3.2)."""

    def setUp(self) -> None:
        super().setUp()
        self.seen_other_frames()

    def run_ingest(self, *args, **kwargs) -> tuple[list[dict], list[dict]]:  # noqa: ANN002, ANN003
        # Each run here stands for one after a frame change, as cams update every few minutes.
        result = super().run_ingest(*args, **kwargs)
        self.seen_other_frames()
        return result

    def test_placeholder_dgt_cam_is_dropped_and_logged(self) -> None:
        cameras, log = self.run_ingest(DGT_PLACEHOLDER)

        self.assertEqual(
            [(c["id"], c["status"]) for c in cameras],
            [("dgt-313", "live"), ("cetursa-15110-2", "offline")],
        )
        record = next(r for r in log if r["id"] == "dgt-312")
        self.assertEqual((record["catalogue"], record["problem"]), ("dropped", "provider placeholder"))
        self.assertEqual({r["id"]: r["catalogue"] for r in log if r["catalogue"] == "kept"},
                         {"dgt-313": "kept", "cetursa-15110-2": "kept"})
        self.assertEqual([p.parent.name for p in self.root.rglob("*.jpg")], ["dgt-313"])

    def test_unfingerprinted_dgt_placeholder_is_dropped(self) -> None:
        with without_md5(DGT_PLACEHOLDER):
            cameras, log = self.run_ingest(DGT_PLACEHOLDER)

        self.assertNotIn("dgt-312", [c["id"] for c in cameras])
        self.assertIn("dHash", next(r for r in log if r["id"] == "dgt-312")["problem"])

    def test_no_video_frame_is_dropped(self) -> None:
        for body in (DGT_NO_VIDEO, DGT_NO_VIDEO_168113, DGT_NO_VIDEO_168099):
            cameras, log = self.run_ingest(body)

            self.assertNotIn("dgt-312", [c["id"] for c in cameras])
            self.assertEqual(next(r for r in log if r["id"] == "dgt-312")["catalogue"], "dropped")

    def test_every_run_checks_again(self) -> None:
        first, _ = self.run_ingest(DGT_PLACEHOLDER)
        second, _ = self.run_ingest(FERATEL_FRAME)

        self.assertNotIn("dgt-312", [c["id"] for c in first])
        self.assertEqual(next(c for c in second if c["id"] == "dgt-312")["status"], "live")

    def test_credit_links_to_the_dgt_page_and_position_to_the_feed(self) -> None:
        cameras, _ = self.run_ingest(FERATEL_FRAME)

        dgt = next(c for c in cameras if c["id"] == "dgt-312")
        self.assertEqual(dgt["source_url"], DGT_PAGE)
        self.assertEqual(dgt["position_source"], "https://example.test/feed.xml")

    def test_shipped_config(self) -> None:
        config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        dgt = next(source for source in config["sources"] if source["id"] == "dgt")

        self.assertTrue(dgt["live_only"])
        self.assertEqual(urlparse(dgt["page"]).netloc, "www.dgt.es")
        self.assertFalse(dgt["page"].endswith(".xml"))
        self.assertEqual(config["region"]["domain"], "data/domain.geojson")
        self.assertEqual(config["region"]["domain_buffer_m"], 2000)


class FrameHistoryTest(LiveOnlyFixture, unittest.TestCase):
    """A DGT card's age is bounded: listed only after a run has seen its content appear.

    DGT re-stamps Last-Modified on unchanged frames for weeks (cam 162889 served a frame
    burned in on 2026-10-02 with Last-Modified 2026-11-22 07:47 UTC).
    """

    T0 = ("Sun, 22 Nov 2026 05:47:01 GMT", "Sun, 22 Nov 2026 05:50:00 GMT")

    def card(self, cameras: list[dict]) -> dict | None:
        return next((c for c in cameras if c["id"] == "dgt-312"), None)

    def record(self, log: list[dict]) -> dict:
        return next(r for r in log if r.get("id") == "dgt-312")

    def test_weeks_old_restamped_frame_gets_no_card_without_history(self) -> None:
        cameras, log = self.run_ingest(
            DGT_FROZEN_162889, "Sun, 22 Nov 2026 07:52:01 GMT", "Sun, 22 Nov 2026 07:56:00 GMT"
        )
        again, _ = self.run_ingest(
            DGT_FROZEN_162889, "Sun, 22 Nov 2026 08:52:01 GMT", "Sun, 22 Nov 2026 08:56:00 GMT"
        )

        self.assertIsNone(self.card(cameras))
        self.assertIsNone(self.card(again))

    def test_no_history_holds_a_restamped_old_frame(self) -> None:
        cameras, log = self.run_ingest(DGT_NIGHT_1310, *self.T0)

        self.assertIsNone(self.card(cameras))
        self.assertEqual(self.record(log)["problem"], "first sight, waiting for a new frame (age unknown)")
        self.assertIn({"source": "history", "status": "absent", "problem": "DGT cams wait for a new frame"}, log)

    def test_frozen_frame_is_never_listed(self) -> None:
        for minute in range(0, 600, 60):
            hour, rest = divmod(6 * 60 + minute, 60)
            stamp = f"Sun, 22 Nov 2026 {hour:02d}:{rest:02d}:01 GMT"
            cameras, _ = self.run_ingest(DGT_NIGHT_1310, stamp, stamp.replace(":01 GMT", ":30 GMT"))
            self.assertIsNone(self.card(cameras), stamp)

    def test_new_content_after_first_sight_is_listed_with_its_last_modified(self) -> None:
        self.run_ingest(DGT_NIGHT_169624, "Sun, 22 Nov 2026 05:54:01 GMT", "Sun, 22 Nov 2026 05:56:00 GMT")
        cameras, log = self.run_ingest(
            DGT_NIGHT_169624_NEXT, "Sun, 22 Nov 2026 06:00:02 GMT", "Sun, 22 Nov 2026 06:02:00 GMT"
        )

        self.assertEqual(self.card(cameras)["captured_at"], "2026-11-22T06:00:02+00:00")
        self.assertTrue(self.record(log)["content_change_seen"])

    def test_restamped_frame_keeps_its_first_capture_time(self) -> None:
        self.run_ingest(DGT_NIGHT_1310, *self.T0)
        self.run_ingest(DGT_NIGHT_169624, "Sun, 22 Nov 2026 05:54:01 GMT", "Sun, 22 Nov 2026 05:56:00 GMT")
        cameras, log = self.run_ingest(
            DGT_NIGHT_169624, "Sun, 22 Nov 2026 05:58:01 GMT", "Sun, 22 Nov 2026 06:02:00 GMT"
        )

        self.assertEqual(self.card(cameras)["captured_at"], "2026-11-22T05:54:01+00:00")
        self.assertEqual(self.record(log)["captured_at_header"], "2026-11-22T05:58:01+00:00")
        self.assertTrue(self.record(log)["unchanged_since_last_run"])

    def test_frame_unchanged_past_the_stale_threshold_is_dropped(self) -> None:
        self.run_ingest(DGT_NIGHT_169624, *self.T0)
        self.run_ingest(DGT_NIGHT_1310, "Sun, 22 Nov 2026 05:52:01 GMT", "Sun, 22 Nov 2026 05:53:00 GMT")
        later, log = self.run_ingest(DGT_NIGHT_1310, "Sun, 22 Nov 2026 07:55:01 GMT", "Sun, 22 Nov 2026 07:56:00 GMT")

        self.assertIsNone(self.card(later))
        self.assertEqual(self.record(log)["problem"], "stale: frame captured at 2026-11-22T05:52:01+00:00")

    def test_history_survives_an_offline_run(self) -> None:
        self.run_ingest(DGT_NIGHT_169624, *self.T0)
        self.run_ingest(DGT_NIGHT_1310, "Sun, 22 Nov 2026 05:52:01 GMT", "Sun, 22 Nov 2026 05:53:00 GMT")
        self.run_ingest(DGT_PLACEHOLDER, "Sun, 22 Nov 2026 05:57:01 GMT", "Sun, 22 Nov 2026 05:58:00 GMT")
        back, _ = self.run_ingest(DGT_NIGHT_1310, "Sun, 22 Nov 2026 06:02:01 GMT", "Sun, 22 Nov 2026 06:03:00 GMT")

        self.assertEqual(self.card(back)["captured_at"], "2026-11-22T05:52:01+00:00")

    def test_frame_without_capture_time_is_dropped(self) -> None:
        self.run_ingest(DGT_NIGHT_169624, *self.T0)
        # Last-Modified ten minutes ahead of Date: a wrong clock, so the age is unknown.
        cameras, log = self.run_ingest(DGT_NIGHT_1310, "Sun, 22 Nov 2026 06:10:01 GMT", "Sun, 22 Nov 2026 06:00:00 GMT")

        self.assertIsNone(self.card(cameras))
        self.assertEqual(self.record(log)["problem"], "no capture time")

    def test_corrupt_history_is_discarded_and_holds(self) -> None:
        self.run_ingest(DGT_NIGHT_169624, *self.T0)
        (self.root / "state.json").write_text("{not json", encoding="utf-8")

        cameras, log = self.run_ingest(
            DGT_NIGHT_1310, "Sun, 22 Nov 2026 05:52:01 GMT", "Sun, 22 Nov 2026 05:53:00 GMT"
        )

        self.assertIsNone(self.card(cameras))
        self.assertEqual(next(r for r in log if r.get("source") == "history")["status"], "corrupt, discarded")
        state = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        self.assertFalse(state["frames"]["dgt-312"]["confirmed"])

    def test_failed_restore_holds_even_with_a_history_on_disk(self) -> None:
        self.run_ingest(DGT_NIGHT_169624, *self.T0)

        cameras, log = self.run_ingest(
            DGT_NIGHT_1310, "Sun, 22 Nov 2026 05:52:01 GMT", "Sun, 22 Nov 2026 05:53:00 GMT", restore="failed"
        )

        self.assertIsNone(self.card(cameras))
        self.assertEqual(next(r for r in log if r.get("source") == "history")["status"], "restore failed")

    def test_history_cannot_make_a_frame_look_fresher(self) -> None:
        self.run_ingest(DGT_NIGHT_169624, *self.T0)
        self.run_ingest(DGT_NIGHT_1310, "Sun, 22 Nov 2026 05:52:01 GMT", "Sun, 22 Nov 2026 05:53:00 GMT")
        state = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        state["frames"]["dgt-312"]["captured_at"] = "2026-11-22T06:30:00+00:00"
        (self.root / "state.json").write_text(json.dumps(state), encoding="utf-8")

        cameras, _ = self.run_ingest(DGT_NIGHT_1310, "Sun, 22 Nov 2026 05:57:01 GMT", "Sun, 22 Nov 2026 06:00:00 GMT")

        self.assertEqual(self.card(cameras)["captured_at"], "2026-11-22T05:57:01+00:00")

    def test_feratel_cams_are_listed_on_first_sight(self) -> None:
        source = cetursa_source()
        source["cameras"] = [c for c in source["cameras"] if c["id"] == "cetursa-15111-0"]
        self.config["sources"] = [source]

        cameras, _ = build_catalog(
            self.config, self.store, lambda url: jpeg(FERATEL_FRAME), now=parse_http_date(FERATEL_DATE)
        )

        self.assertEqual([(c["id"], c["status"]) for c in cameras], [("cetursa-15111-0", "live")])


class PictureGuardTest(unittest.TestCase):
    """Dead-camera frames caught by picture, whatever their bytes (DGT "No video")."""

    @staticmethod
    def variants(body: bytes) -> list[bytes]:
        with Image.open(io.BytesIO(body)) as image:
            image = image.convert("RGB")
            out = []
            for quality in (30, 95):
                out.append(encode(image, quality))
            out.append(encode(image.resize((853, 480))))
            out.append(encode(image.resize((320, 240))))
            out.append(encode(ImageEnhance.Brightness(image).enhance(1.15)))
            # 4:3 letterbox, black bands above and below.
            letterbox = Image.new("RGB", (image.width, image.width * 3 // 4))
            letterbox.paste(image, (0, (letterbox.height - image.height) // 2))
            out.append(encode(letterbox))
        return out

    def problem(self, body: bytes) -> str | None:
        return image_problem(jpeg(body), "DGT")

    def test_no_video_frames_and_reencodings_are_caught(self) -> None:
        for body in (DGT_NO_VIDEO, DGT_NO_VIDEO_168113, DGT_NO_VIDEO_168099, *self.variants(DGT_NO_VIDEO_168113)):
            self.assertIsNotNone(self.problem(body))

    def test_each_no_video_guard_holds_alone(self) -> None:
        bodies = (DGT_NO_VIDEO_168113, DGT_NO_VIDEO_168099, *self.variants(DGT_NO_VIDEO_168113))
        with mock.patch("backend.ingest_webcams.reference_thumbnails", dict):
            for body in bodies:
                self.assertIn("blank dark frame", self.problem(body) or "")
        with mock.patch("backend.ingest_webcams.BLANK_MAX_MEAN", -1), mock.patch(
            "backend.ingest_webcams.UNIFORM_MAX_STDDEV", -1
        ):
            for body in bodies:
                self.assertIn("dgt_no_video", self.problem(body) or "")

    def test_imagen_no_disponible_reencodings_are_caught(self) -> None:
        for body in self.variants(DGT_PLACEHOLDER):
            self.assertIsNotNone(self.problem(body))

    def test_uniform_and_solid_colour_frames_are_caught(self) -> None:
        with Image.open(io.BytesIO(DGT_FROZEN_162889)) as image:
            half = image.convert("RGB")
        # Decoder failure as cam 1086 served it: lower half one flat green.
        half.paste((0, 128, 0), (0, half.height // 2, half.width, half.height))
        with Image.open(io.BytesIO(DGT_NO_VIDEO)) as image:
            grey_no_video = ImageEnhance.Brightness(image.convert("RGB")).enhance(6)
        cases = {
            "blue no signal": (DGT_BLUE, "solid colour block"),
            "solid green": (DGT_GREEN, "uniform frame"),
            "half green": (encode(half), "solid colour block"),
            "No video brightened to grey": (encode(grey_no_video), "uniform frame"),
        }
        for name, (body, expected) in cases.items():
            for variant in (body, *self.variants(body)[:3]):
                self.assertIn(expected, self.problem(variant) or "", name)

    def test_real_night_frames_pass(self) -> None:
        for body in (DGT_NIGHT_1310, DGT_NIGHT_169624, DGT_NIGHT_169624_NEXT, FERATEL_FRAME, FERATEL_FRAME_OTHER,
                     DGT_FROZEN_162889, DGT_FOG):
            self.assertIsNone(image_problem(jpeg(body), "DGT"))
        # Darkened down to x0.6, as the gauntlet checked, night frames stay live.
        for body in (DGT_NIGHT_1310, DGT_NIGHT_169624):
            with Image.open(io.BytesIO(body)) as image:
                for factor in (0.8, 0.6):
                    darker = encode(ImageEnhance.Brightness(image.convert("RGB")).enhance(factor))
                    self.assertIsNone(image_problem(jpeg(darker), "DGT"), factor)

    def test_dark_feratel_frames_before_dawn_stay_live(self) -> None:
        # Real Cetursa captures as flat and dark as "No video"; the picture guards are DGT only.
        for body in (FERATEL_NIGHT, FERATEL_DAWN):
            self.assertIsNotNone(picture_problem(Image.open(io.BytesIO(body)), "DGT"))
            served = jpeg(body, "Sun, 22 Nov 2026 06:08:03 GMT", "Sun, 22 Nov 2026 06:26:01 GMT")
            self.assertIsNone(image_problem(served, "feratel"))


def encode(image: Image.Image, quality: int = 75) -> bytes:
    out = io.BytesIO()
    image.save(out, "JPEG", quality=quality)
    return out.getvalue()


class DomainAreaTest(unittest.TestCase):
    """The shipped area: the T2.1 domain polygon with a 2 km buffer."""

    @classmethod
    def setUpClass(cls) -> None:
        config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        cls.area = load_area(config["region"])

    def test_cams_by_distance_to_the_domain(self) -> None:
        # DGT positions from the feed on 2026-11-22; distances to the domain measured
        # with shapely in EPSG:25830.
        cases = {
            "312 A-395 PK 28.9, inside": (-3.426944, 37.105434, True),
            "169624 A-44 PK 158.3, just outside": (-3.554722, 36.96417, True),
            "1550 A-92 PK 249.1, Granada": (-3.56975, 37.232918, False),
            "298 GR-30 PK 7.96, Granada": (-3.62331, 37.2095, False),
        }
        for name, (lon, lat, expected) in cases.items():
            self.assertEqual(self.area.contains(lon, lat), expected, name)

    def test_buffer_edge(self) -> None:
        # A point 1.9 km and one 2.1 km due south of the domain's southernmost vertex.
        ring = [point for ring in self.area.rings for point in ring]
        x, y = min(ring, key=lambda point: point[1])
        lon, lat = x / self.area.kx, y / self.area.METRES_PER_DEGREE
        self.assertTrue(self.area.contains(lon, lat - 1900 / self.area.METRES_PER_DEGREE))
        self.assertFalse(self.area.contains(lon, lat - 2100 / self.area.METRES_PER_DEGREE))


class ClockTest(unittest.TestCase):
    def test_last_modified_ahead_of_date_gives_unknown_age(self) -> None:
        camera = feratel_camera()

        record, _ = probe_camera_image(
            camera, lambda url: jpeg(FERATEL_FRAME, "Sun, 22 Nov 2026 00:15:00 GMT", "Sat, 21 Nov 2026 23:25:00 GMT")
        )

        self.assertEqual(camera["status"], "live")
        self.assertIsNone(camera["captured_at"])
        self.assertEqual(record["flag"], "Last-Modified ahead of Date: capture time unknown")

    def test_small_clock_skew_keeps_the_capture_time(self) -> None:
        camera = feratel_camera()

        probe_camera_image(
            camera, lambda url: jpeg(FERATEL_FRAME, "Sat, 21 Nov 2026 23:26:00 GMT", "Sat, 21 Nov 2026 23:25:00 GMT")
        )

        self.assertEqual(camera["captured_at"], "2026-11-21T23:26:00+00:00")


class CetursaSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = cetursa_source()

    def test_every_cetursa_camera_carries_the_agreed_credit(self) -> None:
        for camera in static_cameras(self.source, BBOX):
            self.assertEqual(camera["attribution"], "Imagen: Cetursa Sierra Nevada / feratel")
            self.assertEqual(camera["source_url"], "https://sierranevada.es/es/webcams/")

    def test_covers_feratel_cams_15110_to_15114_and_pradollano(self) -> None:
        ids = {camera["id"] for camera in static_cameras(self.source, BBOX)}
        for cam in range(15110, 15115):
            self.assertTrue(any(i.startswith(f"cetursa-{cam}-") for i in ids), cam)
        self.assertIn("cetursa-pradollano-c1", ids)

    def test_station_positions_match_feratel_metadata(self) -> None:
        # infolat/infolong from the feratel player page of each station, read 2026-11-21.
        expected = {
            "15110": (37.058909, -3.39374),
            "15111": (37.071122, -3.389411),
            "15112": (37.062669, -3.373692),
            "15113": (37.083357, -3.405949),
            "15114": (37.090944, -3.399593),
        }
        for camera in static_cameras(self.source, BBOX):
            if camera["provider"] != "feratel":
                continue
            station = camera["id"].split("-")[1]
            self.assertEqual((camera["latitude"], camera["longitude"]), expected[station], camera["id"])
            self.assertIn(f"cam={station}&", camera["position_source"])

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


if __name__ == "__main__":
    unittest.main()
