import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from backend.ingest_webcams import LocalStillStore, build_catalog, write_catalog
from backend.tests.test_ingest_webcams import (
    BBOX,
    DGT_PAGE,
    FEED,
    FERATEL_FRAME,
    FERATEL_FRAME_OTHER,
    FERATEL_PLACEHOLDER,
    cetursa_source,
    dgt_source,
    jpeg,
)
from backend.validate_webcam_artifact import validate


def config() -> dict:
    return {"region": {"bbox": list(BBOX)}, "sources": [cetursa_source()]}


def dgt_config() -> dict:
    return {"region": {"bbox": list(BBOX)}, "sources": [dgt_source(), cetursa_source()]}


class ValidateWebcamArtifactTest(unittest.TestCase):
    """The deploy gate: a built site may only reference stills it contains."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dist = Path(tmp.name)

    def ingest_into_dist(self, fetch) -> list[dict]:
        store = LocalStillStore(self.dist / "data" / "webcam-stills", "data/webcam-stills/")
        cameras, _ = build_catalog(config(), store, fetch)
        write_catalog(cameras, self.dist / "data" / "webcams.json")
        return cameras

    def test_fresh_ingest_passes(self) -> None:
        def fetch(url: str):
            if "/15111/0." in url:
                return jpeg(FERATEL_FRAME)
            if "/15113/2." in url:
                return jpeg(FERATEL_FRAME_OTHER)
            return jpeg(FERATEL_PLACEHOLDER)

        cameras = self.ingest_into_dist(fetch)

        live = sorted(camera["id"] for camera in cameras if camera["status"] == "live")
        self.assertEqual(live, ["cetursa-15111-0", "cetursa-15113-2"])
        self.assertEqual(validate(self.dist, config()), [])

    def test_live_camera_whose_still_is_not_shipped_fails(self) -> None:
        self.ingest_into_dist(lambda url: jpeg(FERATEL_FRAME if "/15111/0" in url else FERATEL_PLACEHOLDER))
        for still in (self.dist / "data" / "webcam-stills").rglob("*.jpg"):
            still.unlink()

        errors = validate(self.dist, config())

        self.assertTrue(errors)
        self.assertTrue(all("is not in the build" in error for error in errors), errors)

    def test_missing_catalogue_fails(self) -> None:
        self.assertEqual(validate(self.dist, config()), [f"{self.dist / 'data' / 'webcams.json'} is missing"])

    def test_live_camera_pointing_at_the_provider_fails(self) -> None:
        cameras = self.ingest_into_dist(lambda url: jpeg(FERATEL_FRAME if "/15111/0" in url else FERATEL_PLACEHOLDER))
        live = next(camera for camera in cameras if camera["status"] == "live")
        live["thumbnail_url"] = "https://wtvhspt.feratel.com/hotspot/37/15111/0.jpeg"
        write_catalog(cameras, self.dist / "data" / "webcams.json")

        errors = validate(self.dist, config())

        self.assertEqual(len(errors), 1)
        self.assertIn("is not a stored still", errors[0])

    def test_wrong_credit_and_offline_with_image_fail(self) -> None:
        cameras = self.ingest_into_dist(lambda url: jpeg(FERATEL_PLACEHOLDER))
        cameras[0]["attribution"] = "Cetursa"
        cameras[1]["captured_at"] = "2026-11-21T17:08:05+00:00"
        write_catalog(cameras, self.dist / "data" / "webcams.json")

        errors = validate(self.dist, config())

        self.assertEqual(len(errors), 2, errors)

    def test_dgt_cam_that_failed_the_check_fails(self) -> None:
        cameras = self.ingest_into_dist(lambda url: jpeg(FERATEL_PLACEHOLDER))
        cameras.append({**cameras[0], "id": "dgt-312", "provider": "DGT", "attribution": "DGT",
                        "source_url": DGT_PAGE, "latitude": None, "longitude": None})
        write_catalog(cameras, self.dist / "data" / "webcams.json")

        errors = validate(self.dist, dgt_config())

        self.assertEqual(errors, ["dgt-312: DGT cam listed without passing the check"])

    def test_dgt_credit_to_the_feed_fails(self) -> None:
        store = LocalStillStore(self.dist / "data" / "webcam-stills", "data/webcam-stills/")
        cameras, _ = build_catalog(
            dgt_config(),
            store,
            lambda url: jpeg(FERATEL_FRAME if url.startswith("https://example.test/") else FERATEL_PLACEHOLDER),
            lambda url: FEED.encode(),
            now=datetime(2026, 11, 21, 17, 10, tzinfo=UTC),
        )
        write_catalog(cameras, self.dist / "data" / "webcams.json")
        self.assertEqual(validate(self.dist, dgt_config()), [])

        dgt = next(camera for camera in cameras if camera["id"] == "dgt-312")
        dgt["source_url"] = "https://example.test/feed.xml"
        write_catalog(cameras, self.dist / "data" / "webcams.json")

        errors = validate(self.dist, dgt_config())

        self.assertEqual(len(errors), 1, errors)
        self.assertIn("dgt-312: credit links to", errors[0])

    def test_catalogue_is_not_committed(self) -> None:
        # A committed webcams.json would ship stale "live" cards whose stills are not in the repo.
        root = Path(__file__).parents[2]
        self.assertFalse(_tracked(root, "frontend/public/data/webcams.json"))
        self.assertIn("frontend/public/data/webcams.json", (root / ".gitignore").read_text(encoding="utf-8"))


def _tracked(root: Path, path: str) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", path], cwd=root, capture_output=True, check=False
    )
    return result.returncode == 0


if __name__ == "__main__":
    unittest.main()
