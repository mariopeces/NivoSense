from __future__ import annotations

import argparse
import email.utils
import json
import math
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_CONFIG = Path(__file__).with_name("webcam_sources.json")
DEFAULT_OUTPUT = Path(__file__).parents[1] / "frontend" / "public" / "data" / "webcams.json"


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

        cameras.append(
            {
                "id": f"dgt-{raw_id}",
                "name": " · ".join(name_parts) or f"Cámara DGT {raw_id}",
                "location": " · ".join(location_parts) or None,
                "latitude": latitude,
                "longitude": longitude,
                "image_url": safe_http_url(first_text(device, "deviceUrl")),
                "captured_at": None,
                "source_url": source_url,
                "attribution": attribution,
            }
        )

    return sorted(cameras, key=lambda item: (item["name"], item["id"]))


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "NivoSense webcam catalog"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def fetch_last_modified(url: str) -> str | None:
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "NivoSense webcam catalog"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            value = response.headers.get("Last-Modified")
    except OSError:
        return None
    if not value:
        return None
    try:
        return email.utils.parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return None


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_catalog(config: dict[str, Any]) -> list[dict[str, Any]]:
    region = config["region"]
    bbox = tuple(float(value) for value in region["bbox"])
    if len(bbox) != 4:
        raise ValueError("region.bbox must contain west, south, east and north")

    cameras: list[dict[str, Any]] = []
    for source in config["sources"]:
        if not source.get("enabled", True):
            continue
        if source["type"] != "datex2":
            raise ValueError(f"Unsupported webcam source type: {source['type']}")
        source_url = source["url"]
        source_cameras = parse_datex_cameras(
            fetch_bytes(source_url),
            bbox,  # type: ignore[arg-type]
            source_url,
            source["attribution"],
        )
        for camera in source_cameras:
            if camera["image_url"]:
                camera["captured_at"] = fetch_last_modified(camera["image_url"])
        cameras.extend(source_cameras)
    return cameras


def write_catalog(cameras: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(cameras, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    cameras = build_catalog(load_config(args.config))
    write_catalog(cameras, args.output)
    print(f"Wrote {len(cameras)} webcams to {args.output}")


if __name__ == "__main__":
    main()
