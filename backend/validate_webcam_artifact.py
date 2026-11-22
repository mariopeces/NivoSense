"""Check the webcam catalogue inside a built site before it is deployed.

Every image the catalogue points at must be in the build, so a failed or partial
ingest can never publish a live card without its still. Exits 1 on any error,
which fails the deploy and leaves the last good one in place.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CONFIG = Path(__file__).with_name("webcam_sources.json")
CETURSA_CREDIT = "Imagen: Cetursa Sierra Nevada / feratel"
STILL_PATH = re.compile(
    r"^data/webcam-stills/[a-z0-9-]+/([0-9]{8}T[0-9]{6}Z|undated)-(thumbnail|large)-[0-9a-f]{16}\.jpg$"
)


def validate(dist: Path, config: dict[str, Any]) -> list[str]:
    catalog_path = dist / "data" / "webcams.json"
    if not catalog_path.is_file():
        return [f"{catalog_path} is missing"]
    try:
        cameras = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{catalog_path} is not JSON: {exc}"]
    if not isinstance(cameras, list):
        return [f"{catalog_path} is not a list"]

    west, south, east, north = config["region"]["bbox"]
    # Providers whose cams are listed only while they pass the check, with the page
    # their credit must link to.
    live_only = {
        source.get("provider", source["id"]): source.get("page", source["url"])
        for source in config["sources"]
        if source.get("live_only") and source.get("enabled", True)
    }
    errors: list[str] = []
    seen: set[str] = set()
    for camera in cameras:
        cid = camera.get("id")
        provider = camera.get("provider")
        if provider in live_only:
            if camera.get("status") != "live":
                errors.append(f"{cid}: {provider} cam listed without passing the check")
            if camera.get("source_url") != live_only[provider]:
                errors.append(f"{cid}: credit links to {camera.get('source_url')!r}, not {live_only[provider]!r}")
        if not cid or cid in seen:
            errors.append(f"missing or duplicate id: {cid!r}")
        seen.add(cid)
        for key in ("name", "provider", "attribution"):
            if not camera.get(key):
                errors.append(f"{cid}: {key} is empty")
        if urlparse(camera.get("source_url") or "").scheme != "https":
            errors.append(f"{cid}: source_url is not https")
        if str(cid).startswith("cetursa-") and camera.get("attribution") != CETURSA_CREDIT:
            errors.append(f"{cid}: credit is not {CETURSA_CREDIT!r}")

        latitude, longitude = camera.get("latitude"), camera.get("longitude")
        if (latitude is None) != (longitude is None):
            errors.append(f"{cid}: only one of latitude and longitude is set")
        elif latitude is not None:
            if not (west <= longitude <= east and south <= latitude <= north):
                errors.append(f"{cid}: position outside region.bbox")
            if urlparse(camera.get("position_source") or "").scheme != "https":
                errors.append(f"{cid}: position without an https position_source")

        status = camera.get("status")
        if status == "offline":
            for key in ("thumbnail_url", "large_url", "captured_at"):
                if camera.get(key) is not None:
                    errors.append(f"{cid}: offline but {key} is set")
        elif status == "live":
            for key in ("thumbnail_url", "large_url"):
                path = camera.get(key)
                if not isinstance(path, str) or not STILL_PATH.match(path):
                    errors.append(f"{cid}: {key} {path!r} is not a stored still")
                elif not (dist / path).is_file():
                    errors.append(f"{cid}: {key} {path} is not in the build")
        else:
            errors.append(f"{cid}: status {status!r}")
    return errors


def main() -> None:
    dist = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("frontend/dist")
    errors = validate(dist, json.loads(CONFIG.read_text(encoding="utf-8")))
    for error in errors:
        print(f"::error::webcams: {error}")
    if errors:
        sys.exit(1)
    print("webcam catalogue OK")


if __name__ == "__main__":
    main()
