from __future__ import annotations

import argparse
import email.utils
import hashlib
import http.client
import json
import math
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, NamedTuple
from urllib.parse import urlparse

DEFAULT_CONFIG = Path(__file__).with_name("webcam_sources.json")
DEFAULT_OUTPUT = Path(__file__).parents[1] / "frontend" / "public" / "data" / "webcams.json"
# Frames providers serve in place of a dead camera, by MD5 of the file.
PLACEHOLDER_MD5 = frozenset(
    {
        "c92fb6440dc51109074769bcad5c7de9",  # DGT "IMAGEN NO DISPONIBLE", 639x359, seen 2026-11-21
        # feratel "Derzeit ist kein aktuelles Bild verfügbar.", served with a fresh
        # Last-Modified by every view of cams 15110 and 15114 on 2026-11-21.
        "db70616dcde9cec7ae8f6d45c28cf8d9",  # 720x405 (hotspot size 37)
        "01aa3856a58d9b74272c0f551317be3d",  # large (hotspot size 35)
    }
)


class ImageResponse(NamedTuple):
    status: int
    content_type: str | None
    content_length: int | None
    body: bytes
    last_modified: str | None


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def first_text(element: ET.Element, name: str) -> str | None:
    for child in element.iter():
        if local_name(child.tag) == name and child.text and child.text.strip():
            return child.text.strip()
    return None


def safe_http_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def parse_datex_cameras(
    xml_data: bytes | str,
    bbox: tuple[float, float, float, float],
    source_url: str,
    attribution: str,
    provider: str = "DGT",
) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_data)
    west, south, east, north = bbox
    cameras: list[dict[str, Any]] = []

    for device in root.iter():
        if local_name(device.tag) != "device":
            continue
        if first_text(device, "typeOfDevice") != "camera":
            continue

        raw_id = device.attrib.get("id")
        latitude_text = first_text(device, "latitude")
        longitude_text = first_text(device, "longitude")
        if not raw_id or not latitude_text or not longitude_text:
            continue

        try:
            latitude = float(latitude_text)
            longitude = float(longitude_text)
        except ValueError:
            continue
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            continue
        if not (west <= longitude <= east and south <= latitude <= north):
            continue

        road = first_text(device, "roadName")
        kilometer = first_text(device, "kilometerPoint")
        province = first_text(device, "province")
        destination = first_text(device, "roadDestination")
        name_parts = [part for part in (road, f"PK {kilometer}" if kilometer else None) if part]
        location_parts = [part for part in (province, destination) if part]
        image_url = safe_http_url(first_text(device, "deviceUrl"))

        cameras.append(
            {
                "id": f"dgt-{raw_id}",
                "name": " · ".join(name_parts) or f"Cámara DGT {raw_id}",
                "location": " · ".join(location_parts) or None,
                "provider": provider,
                "latitude": latitude,
                "longitude": longitude,
                "position_source": source_url,
                "thumbnail_url": image_url,
                "large_url": image_url,
                "captured_at": None,
                "source_url": source_url,
                "attribution": attribution,
            }
        )

    return sorted(cameras, key=lambda item: (item["name"], item["id"]))


def static_cameras(
    source: dict[str, Any],
    bbox: tuple[float, float, float, float],
) -> list[dict[str, Any]]:
    """Cameras listed by hand in the config, each with the page its position came from.

    A camera whose position no provider publishes keeps latitude and longitude
    null; it is listed but not placed on the map.
    """
    west, south, east, north = bbox
    cameras: list[dict[str, Any]] = []
    for entry in source["cameras"]:
        latitude, longitude = entry.get("latitude"), entry.get("longitude")
        if (latitude is None) != (longitude is None):
            raise ValueError(f"{entry['id']}: latitude and longitude must both be set or both null")
        if latitude is not None:
            if not (west <= longitude <= east and south <= latitude <= north):
                raise ValueError(f"{entry['id']}: position is outside region.bbox")
            if not entry.get("position_source"):
                raise ValueError(f"{entry['id']}: a position needs its position_source")
        for key in ("thumbnail_url", "large_url"):
            if urlparse(entry[key]).scheme != "https":
                raise ValueError(f"{entry['id']}: {key} must be https")
        cameras.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "location": entry.get("location"),
                "provider": entry["provider"],
                "latitude": latitude,
                "longitude": longitude,
                "position_source": entry.get("position_source"),
                "thumbnail_url": entry["thumbnail_url"],
                "large_url": entry["large_url"],
                "captured_at": None,
                "source_url": source["url"],
                "attribution": source["attribution"],
            }
        )
    return cameras


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "NivoSense webcam catalog"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def fetch_image(url: str) -> ImageResponse:
    request = urllib.request.Request(url, headers={"User-Agent": "NivoSense webcam catalog"})
    with urllib.request.urlopen(request, timeout=30) as response:
        length = response.headers.get("Content-Length")
        return ImageResponse(
            status=response.status,
            content_type=response.headers.get("Content-Type"),
            content_length=int(length) if length and length.isdigit() else None,
            body=response.read(),
            last_modified=response.headers.get("Last-Modified"),
        )


def parse_http_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return email.utils.parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return None


def image_problem(response: ImageResponse) -> str | None:
    """Why a provider response is not a usable frame, or None if it is one."""
    if response.status != 200:
        return f"HTTP {response.status}"
    content_type = (response.content_type or "").split(";")[0].strip().lower()
    if content_type != "image/jpeg":
        return f"content type {content_type or 'missing'}"
    if not response.body:
        return "empty body"
    if response.content_length is not None and response.content_length != len(response.body):
        return f"truncated: {len(response.body)} of {response.content_length} bytes"
    # A JPEG starts with SOI (FFD8) and ends with EOI (FFD9); a cut transfer loses the EOI.
    if not response.body.startswith(b"\xff\xd8") or not response.body.endswith(b"\xff\xd9"):
        return "not a complete JPEG"
    if hashlib.md5(response.body).hexdigest() in PLACEHOLDER_MD5:
        return "provider placeholder"
    return None


def probe_camera_image(
    camera: dict[str, Any],
    fetch: Callable[[str], ImageResponse] = fetch_image,
) -> dict[str, Any]:
    """Set status and captured_at from the images the provider serves right now.

    Dead DGT and feratel cameras still answer 200 with a stock frame and a fresh
    Last-Modified, so the header alone would show them as live. For a real frame,
    Last-Modified is the capture time: on 2026-11-21 it matched the time burned
    into the feratel and Cetursa frames to the second (feratel 18:08 CET vs
    17:08:05 GMT; Pradollano 00:11:20 CET vs 23:11:24 GMT). The images carry no EXIF.
    """
    urls = [url for url in dict.fromkeys((camera["thumbnail_url"], camera["large_url"])) if url]
    record: dict[str, Any] = {"id": camera["id"], "images": []}
    problem = None if urls else "no image URL"
    last_modified = None
    for url in urls:
        try:
            response = fetch(url)
        except urllib.error.HTTPError as exc:
            problem = f"HTTP {exc.code}"
        except (OSError, http.client.HTTPException) as exc:
            problem = f"unreachable: {exc}"
        else:
            problem = image_problem(response)
            last_modified = response.last_modified
            record["images"].append(
                {
                    "url": url,
                    "http": response.status,
                    "content_type": response.content_type,
                    "bytes": len(response.body),
                    "md5": hashlib.md5(response.body).hexdigest(),
                    "last_modified": response.last_modified,
                }
            )
        if problem:
            break

    if problem:
        camera["status"] = "offline"
        camera["thumbnail_url"] = None
        camera["large_url"] = None
        camera["captured_at"] = None
    else:
        camera["status"] = "live"
        camera["captured_at"] = parse_http_date(last_modified)
    record.update(status=camera["status"], problem=problem, captured_at=camera["captured_at"])
    return record


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_catalog(
    config: dict[str, Any],
    fetch: Callable[[str], ImageResponse] = fetch_image,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    region = config["region"]
    bbox = tuple(float(value) for value in region["bbox"])
    if len(bbox) != 4:
        raise ValueError("region.bbox must contain west, south, east and north")

    cameras: list[dict[str, Any]] = []
    log: list[dict[str, Any]] = []
    for source in config["sources"]:
        if not source.get("enabled", True):
            continue
        if source["type"] == "datex2":
            source_cameras = parse_datex_cameras(
                fetch_bytes(source["url"]),
                bbox,  # type: ignore[arg-type]
                source["url"],
                source["attribution"],
                source.get("provider", source["id"]),
            )
        elif source["type"] == "static":
            source_cameras = static_cameras(source, bbox)  # type: ignore[arg-type]
        else:
            raise ValueError(f"Unsupported webcam source type: {source['type']}")
        for camera in source_cameras:
            log.append(probe_camera_image(camera, fetch))
        cameras.extend(source_cameras)
    return cameras, log


def write_catalog(cameras: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(cameras, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    cameras, log = build_catalog(load_config(args.config))
    for record in log:
        print(json.dumps(record, ensure_ascii=False))
    write_catalog(cameras, args.output)
    live = sum(camera["status"] == "live" for camera in cameras)
    print(f"Wrote {len(cameras)} webcams ({live} live) to {args.output}")


if __name__ == "__main__":
    main()
