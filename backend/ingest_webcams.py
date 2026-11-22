from __future__ import annotations

import argparse
import email.utils
import hashlib
import http.client
import io
import json
import math
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple, Protocol
from urllib.parse import urlparse

from PIL import Image, ImageStat

ROOT = Path(__file__).parents[1]
DEFAULT_CONFIG = Path(__file__).with_name("webcam_sources.json")
DEFAULT_OUTPUT = ROOT / "frontend" / "public" / "data" / "webcams.json"
# Stills are served next to webcams.json by the static site; the folder is not committed.
DEFAULT_STILLS_DIR = ROOT / "frontend" / "public" / "data" / "webcam-stills"
DEFAULT_STILLS_PREFIX = "data/webcam-stills/"
# Per camera, the last checked frame and the capture time of its content; the next
# run reads it back from the published site (pages.yml).
STATE_KEY = "state.json"

# feratel localises its dead-camera frame by Accept-Language (de, es, en, fr, it, nl
# seen on 2026-11-21; pt falls back to de). Pinning the language keeps the exact
# fingerprints below meaningful; the perceptual check covers renditions not listed.
REQUEST_HEADERS = {"User-Agent": "NivoSense webcam catalog", "Accept-Language": "de"}

# Frames providers serve in place of a dead camera, by MD5 of the file.
PLACEHOLDER_MD5 = frozenset(
    {
        "c92fb6440dc51109074769bcad5c7de9",  # DGT "IMAGEN NO DISPONIBLE", 639x359, seen 2026-11-21
        # feratel "no current image" frame, per language, at hotspot sizes 39, 38, 37
        # and 35 (36 serves the 35 file), fetched from cam 15110 on 2026-11-21.
        # de (also served for pt and without Accept-Language)
        "5e072355aec31a0025afa7295c4d3728", "ca2e6386379e28d5fa22afda02d8f9bf",
        "db70616dcde9cec7ae8f6d45c28cf8d9", "01aa3856a58d9b74272c0f551317be3d",
        # es
        "b5c40f5cc7475028266cadc7f7341283", "93504884cdad86c385eaad82a2f240e0",
        "b53d99a18289f5880238e2dad7e82e3e", "96a207de0a26be4e108723f4a304a137",
        # en
        "27480c2be97fa23eea682e98afddda9f", "4ef29c947afa238f97707ac3995df391",
        "471730f7d0fe38aa9a49cd4e58cb3fa2", "32e72c31e48abb2d593ca5a678e30824",
        # fr
        "8e56f6a6766097715ba95d5364fccf17", "5025bd8c2007d00a354620898bf3a813",
        "31d6be3d73d6d7391d537473bdf3b67d", "0586db3915962af59157057453a0939f",
        # it
        "b2e554095eb86009f4d4a9b7e55b85b7", "3d580ada77f5fc3d6f95f678c9fc76d7",
        "fc86bac66b093f94939dfa04357a5183", "81d8518d1cf37cde2637d01c70bd3406",
        # nl
        "5a6a4461daddb5fe1a09ffed290e28b2", "f571e893c81fe9b43b33c2ea8793bb4a",
        "d6e2dbaaaed3a3a49d168631c8172081", "acab8ce0b6d9e9e9c4b7dcbdcf5854f3",
    }
)
# 64-bit difference hashes (dHash, 9x8 grayscale, Lanczos) of the placeholders:
# feratel de at hotspot size 37, and the DGT frame.
PLACEHOLDER_DHASH = (0x04C2844160F39900, 0x0020C8A0C8CA1000)
# Measured on 2026-11-21: the 40 feratel placeholder renditions (6 languages x
# sizes 35 to 39) lie within 7 bits of the de/37 hash; the 26 real frames from the
# live Cetursa cams lie 25 bits or more from every placeholder.
PLACEHOLDER_DHASH_MAX_BITS = 10
# feratel stamps its placeholder with Last-Modified equal to the response Date (to
# the second, every rendition on 2026-11-21); real frames carry the capture time.
GENERATED_ON_REQUEST_SECONDS = 2
# Every frame on 2026-11-21 had Last-Modified at or before the response Date. A later
# Last-Modified means a wrong clock, so its age is unknown; two minutes absorbs skew
# between the provider's file and HTTP clocks.
CLOCK_SKEW_SECONDS = 120

# Dead-camera frames whose bytes change on every fetch (DGT burns the current time into
# its black "No video" frame), matched by picture instead of by bytes. Only for DGT: real
# feratel frames before dawn are as flat and dark (Cetursa at 06:24 UTC on 2026-11-22:
# 12 views at mean 1 to 2, sd 0 to 2.8, within 8 of "No video"), and an offline card
# for them would be false. A DGT cam whose real frame is that dark shows nothing
# either and is dropped too.
PICTURE_GUARD_PROVIDERS = frozenset({"DGT"})
REFERENCE_FRAMES_DIR = Path(__file__).with_name("webcam_placeholders")
REFERENCE_THUMB_SIZE = (64, 48)
# Mean absolute grey-level difference between 64x48 thumbnails. Measured on
# 2026-11-22: "No video" from 7 DGT cams lies within 4 of the reference, real DGT night
# frames 18 or more from it; real frames lie 70 or more from "IMAGEN NO DISPONIBLE".
REFERENCE_MAX_DIFFERENCE = 8
# A frame whose picture (overlay bands excluded) is near-uniform and dark carries no
# view: "No video" measures mean 0 to 3 and standard deviation 0.0, real DGT night
# frames mean 17 or more and standard deviation 6 or more (2026-11-22).
BLANK_MAX_MEAN = 16
BLANK_MAX_STDDEV = 3
# DGT and feratel burn text in the top and bottom bands.
OVERLAY_BAND = 0.15

# A frame whose content has not changed for longer than this is stale; the card's
# stale state uses the same two hours (task T4.0 design spec).
STALE_AFTER = timedelta(hours=2)


class ImageResponse(NamedTuple):
    status: int
    content_type: str | None
    content_length: int | None
    body: bytes
    last_modified: str | None
    date: str | None


class StillStore(Protocol):
    def put(self, key: str, body: bytes, content_type: str) -> str:
        """Store body under key and return the URL the site loads it from."""
        ...

    def load_state(self) -> dict[str, Any]:
        """The frame history the previous run saved, or {} when there is none."""
        ...

    def save_state(self, state: dict[str, Any]) -> None: ...


class Area(Protocol):
    def contains(self, longitude: float, latitude: float) -> bool: ...


class BoxArea(NamedTuple):
    west: float
    south: float
    east: float
    north: float

    def contains(self, longitude: float, latitude: float) -> bool:
        return self.west <= longitude <= self.east and self.south <= latitude <= self.north


class PolygonArea:
    """Inside a polygon or within buffer_m metres of its boundary.

    Distances use an equirectangular projection about the polygon's mean latitude,
    under 0.1 % off over the 60 km of the Sierra Nevada domain.
    """

    METRES_PER_DEGREE = 111_320.0

    def __init__(self, rings: list[list[tuple[float, float]]], buffer_m: float) -> None:
        latitudes = [lat for ring in rings for _, lat in ring]
        self.kx = self.METRES_PER_DEGREE * math.cos(math.radians(sum(latitudes) / len(latitudes)))
        self.rings = [[(lon * self.kx, lat * self.METRES_PER_DEGREE) for lon, lat in ring] for ring in rings]
        self.buffer_m = buffer_m
        xs = [x for ring in self.rings for x, _ in ring]
        ys = [y for ring in self.rings for _, y in ring]
        self.bounds = (min(xs) - buffer_m, min(ys) - buffer_m, max(xs) + buffer_m, max(ys) + buffer_m)

    def contains(self, longitude: float, latitude: float) -> bool:
        x, y = longitude * self.kx, latitude * self.METRES_PER_DEGREE
        left, bottom, right, top = self.bounds
        if not (left <= x <= right and bottom <= y <= top):
            return False
        inside = False
        nearest = math.inf
        for ring in self.rings:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
                if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    inside = not inside
                dx, dy = x2 - x1, y2 - y1
                length2 = dx * dx + dy * dy
                t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length2))
                nearest = min(nearest, math.hypot(x - x1 - t * dx, y - y1 - t * dy))
        return inside or nearest <= self.buffer_m


def load_area(region: dict[str, Any], root: Path = ROOT) -> Area:
    """The region's domain polygon with its buffer, or its bbox when it names no domain."""
    if "domain" not in region:
        bbox = tuple(float(value) for value in region["bbox"])
        if len(bbox) != 4:
            raise ValueError("region.bbox must contain west, south, east and north")
        return BoxArea(*bbox)
    collection = json.loads((root / region["domain"]).read_text(encoding="utf-8"))
    part = region.get("domain_part", "domain")
    geometry = next(f["geometry"] for f in collection["features"] if f["properties"].get("part") == part)
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    rings = [[(float(point[0]), float(point[1])) for point in ring] for polygon in polygons for ring in polygon]
    return PolygonArea(rings, float(region.get("domain_buffer_m", 0)))


def as_area(area: Area | tuple[float, float, float, float]) -> Area:
    if isinstance(area, tuple) and not isinstance(area, BoxArea):
        return BoxArea(*area)
    return area  # type: ignore[return-value]


class LocalStillStore:
    """Still store on a local folder, served by the static site under url_prefix."""

    def __init__(self, root: Path, url_prefix: str) -> None:
        self.root = root
        self.url_prefix = url_prefix

    def put(self, key: str, body: bytes, content_type: str) -> str:
        path = self.root / key
        # Keys are content-addressed, so an existing file already holds these bytes.
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        return self.url_prefix + key

    def load_state(self) -> dict[str, Any]:
        try:
            state = json.loads((self.root / STATE_KEY).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A missing or broken history only costs the earlier capture times.
            return {}
        return state if isinstance(state, dict) else {}

    def save_state(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / STATE_KEY).write_text(
            json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )


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
    area: Area | tuple[float, float, float, float],
    source_url: str,
    attribution: str,
    provider: str = "DGT",
    credit_url: str | None = None,
) -> list[dict[str, Any]]:
    """Cameras of a DATEX II device feed inside area.

    source_url is the feed, kept as each camera's position source; credit_url is the
    provider's page the card's credit links to (the feed itself when not given).
    """
    root = ET.fromstring(xml_data)
    area = as_area(area)
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
        if not area.contains(longitude, latitude):
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
                "source_url": credit_url or source_url,
                "attribution": attribution,
            }
        )

    return sorted(cameras, key=lambda item: (item["name"], item["id"]))


def static_cameras(
    source: dict[str, Any],
    area: Area | tuple[float, float, float, float],
) -> list[dict[str, Any]]:
    """Cameras listed by hand in the config, each with the page its position came from.

    A camera whose position no provider publishes keeps latitude and longitude
    null; it is listed but not placed on the map.
    """
    area = as_area(area)
    cameras: list[dict[str, Any]] = []
    for entry in source["cameras"]:
        latitude, longitude = entry.get("latitude"), entry.get("longitude")
        if (latitude is None) != (longitude is None):
            raise ValueError(f"{entry['id']}: latitude and longitude must both be set or both null")
        if latitude is not None:
            if not area.contains(longitude, latitude):
                raise ValueError(f"{entry['id']}: position is outside the region")
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
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def fetch_image(url: str) -> ImageResponse:
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        length = response.headers.get("Content-Length")
        return ImageResponse(
            status=response.status,
            content_type=response.headers.get("Content-Type"),
            content_length=int(length) if length and length.isdigit() else None,
            body=response.read(),
            last_modified=response.headers.get("Last-Modified"),
            date=response.headers.get("Date"),
        )


def parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def dhash(body: bytes) -> int:
    with Image.open(io.BytesIO(body)) as image:
        return dhash_of(image.convert("L"))


def dhash_of(grey: Image.Image) -> int:
    pixels = list(grey.resize((9, 8), Image.Resampling.LANCZOS).getdata())
    value = 0
    for row in range(8):
        for col in range(8):
            left, right = pixels[row * 9 + col], pixels[row * 9 + col + 1]
            value = value << 1 | (left > right)
    return value


def thumbnail(grey: Image.Image) -> bytes:
    return grey.resize(REFERENCE_THUMB_SIZE, Image.Resampling.BOX).tobytes()


_reference_thumbnails: dict[str, bytes] = {}


def reference_thumbnails() -> dict[str, bytes]:
    if not _reference_thumbnails:
        for path in sorted(REFERENCE_FRAMES_DIR.glob("*.jpg")):
            with Image.open(path) as image:
                _reference_thumbnails[path.stem] = thumbnail(image.convert("L"))
    return _reference_thumbnails


def picture_problem(grey: Image.Image, provider: str) -> str | None:
    """Why the decoded picture is not a camera view, whatever its bytes."""
    distance = min((dhash_of(grey) ^ known).bit_count() for known in PLACEHOLDER_DHASH)
    if distance <= PLACEHOLDER_DHASH_MAX_BITS:
        return f"looks like a provider placeholder (dHash distance {distance})"
    if provider not in PICTURE_GUARD_PROVIDERS:
        return None
    width, height = grey.size
    band = round(height * OVERLAY_BAND)
    stat = ImageStat.Stat(grey.crop((0, band, width, height - band)))
    mean, stddev = stat.mean[0], stat.stddev[0]
    if mean <= BLANK_MAX_MEAN and stddev <= BLANK_MAX_STDDEV:
        return f"blank dark frame (mean {mean:.1f}, sd {stddev:.1f})"
    small = thumbnail(grey)
    for name, reference in reference_thumbnails().items():
        difference = sum(abs(a - b) for a, b in zip(small, reference, strict=True)) / len(small)
        if difference <= REFERENCE_MAX_DIFFERENCE:
            return f"looks like the {name} placeholder (difference {difference:.1f})"
    return None


def image_problem(response: ImageResponse, provider: str) -> str | None:
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
    if provider == "feratel":
        modified, served = parse_http_date(response.last_modified), parse_http_date(response.date)
        if modified and served and abs((served - modified).total_seconds()) <= GENERATED_ON_REQUEST_SECONDS:
            return "generated on request (Last-Modified equals Date)"
    try:
        with Image.open(io.BytesIO(response.body)) as image:
            grey = image.convert("L")
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return "undecodable JPEG"
    return picture_problem(grey, provider)


def probe_camera_image(
    camera: dict[str, Any],
    fetch: Callable[[str], ImageResponse] = fetch_image,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Check the images the provider serves right now and set status and captured_at.

    Dead DGT and feratel cameras still answer 200 with a stock frame and a fresh
    Last-Modified, so the header alone would show them as live. For a real frame,
    Last-Modified is the capture time: on 2026-11-21 it matched the time burned
    into the feratel and Cetursa frames to the second (feratel 18:08 CET vs
    17:08:05 GMT; Pradollano 00:11:20 CET vs 23:11:24 GMT). The images carry no EXIF.

    Returns the log record and the checked bytes by size ("thumbnail", "large"),
    which the caller stores so the site shows exactly what was checked.
    """
    record: dict[str, Any] = {"id": camera["id"], "images": []}
    bodies: dict[str, bytes] = {}
    fetched: dict[str, ImageResponse] = {}
    problem = None if camera["thumbnail_url"] and camera["large_url"] else "no image URL"
    capture_times: set[str | None] = set()
    served_at: list[datetime] = []
    for size in ("thumbnail", "large") if problem is None else ():
        url = camera[f"{size}_url"]
        response = fetched.get(url)
        if response is None:
            try:
                response = fetched[url] = fetch(url)
            except urllib.error.HTTPError as exc:
                problem = f"HTTP {exc.code}"
            except (OSError, http.client.HTTPException) as exc:
                problem = f"unreachable: {exc}"
            if response is not None:
                record["images"].append(
                    {
                        "url": url,
                        "http": response.status,
                        "content_type": response.content_type,
                        "bytes": len(response.body),
                        "md5": hashlib.md5(response.body).hexdigest(),
                        "last_modified": response.last_modified,
                        "date": response.date,
                    }
                )
                problem = image_problem(response, camera["provider"])
        if problem:
            break
        assert response is not None
        bodies[size] = response.body
        capture_times.add(response.last_modified)
        if (served := parse_http_date(response.date)) is not None:
            served_at.append(served)
    if not problem and len(capture_times) > 1:
        problem = "thumbnail and large image carry different capture times"

    if problem:
        set_offline(camera)
        bodies = {}
    else:
        captured = parse_http_date(capture_times.pop())
        if captured and served_at and (captured - min(served_at)).total_seconds() > CLOCK_SKEW_SECONDS:
            record["flag"] = "Last-Modified ahead of Date: capture time unknown"
            captured = None
        camera["status"] = "live"
        camera["captured_at"] = captured.isoformat() if captured else None
    record.update(status=camera["status"], problem=problem, captured_at=camera["captured_at"])
    return record, bodies


def set_offline(camera: dict[str, Any]) -> None:
    camera["status"] = "offline"
    camera["thumbnail_url"] = None
    camera["large_url"] = None
    camera["captured_at"] = None


def drop_shared_frames(
    cameras: list[dict[str, Any]],
    log: list[dict[str, Any]],
    bodies: dict[str, dict[str, bytes]],
) -> None:
    """Set offline every camera whose frame bytes another camera also served this run.

    Two cameras never capture identical bytes; a shared file is a stock frame,
    whatever its fingerprint (on 2026-11-21, five dead feratel views served one file).
    """
    owners: dict[str, set[str]] = defaultdict(set)
    for camera_id, sizes in bodies.items():
        for body in sizes.values():
            owners[hashlib.md5(body).hexdigest()].add(camera_id)
    shared = {camera_id for ids in owners.values() if len(ids) > 1 for camera_id in ids}
    for camera, record in zip(cameras, log):
        if camera["id"] in shared:
            set_offline(camera)
            bodies.pop(camera["id"], None)
            record.update(
                status="offline",
                problem="identical bytes served by another camera",
                captured_at=None,
            )


def store_stills(camera: dict[str, Any], sizes: dict[str, bytes], store: StillStore) -> None:
    """Point the camera at stored copies of the checked bytes, named by content."""
    stamp = (
        datetime.fromisoformat(camera["captured_at"]).strftime("%Y%m%dT%H%M%SZ")
        if camera["captured_at"]
        else "undated"
    )
    for size, body in sizes.items():
        if size == "large" and body == sizes.get("thumbnail"):
            # One URL serves both sizes (Pradollano, DGT): store the frame once.
            camera["large_url"] = camera["thumbnail_url"]
            continue
        digest = hashlib.sha256(body).hexdigest()[:16]
        key = f"{camera['id']}/{stamp}-{size}-{digest}.jpg"
        camera[f"{size}_url"] = store.put(key, body, "image/jpeg")


def frame_digest(sizes: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for size in sorted(sizes):
        digest.update(size.encode() + b"\0" + hashlib.sha256(sizes[size]).digest())
    return digest.hexdigest()


def apply_history(
    camera: dict[str, Any],
    record: dict[str, Any],
    sizes: dict[str, bytes],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep the capture time of unchanged content and return the camera's new history.

    DGT rewrites an unchanged file with a fresh Last-Modified (on 2026-11-22, cam 1310
    served a 05:32 UTC frame as 05:57, then 06:02), so Last-Modified is only an upper
    bound. The same bytes as the last run keep the earlier capture time. Identity is
    by bytes, not by a perceptual hash: every DGT capture burns in a new clock, while a
    perceptual hash would equate two real captures of a still scene and age a live cam.
    """
    digest = frame_digest(sizes)
    if previous and previous.get("sha256") == digest:
        earlier = parse_iso(previous.get("captured_at"))
        current = parse_iso(camera["captured_at"])
        if earlier and (current is None or earlier < current):
            record["captured_at_header"] = camera["captured_at"]
            camera["captured_at"] = earlier.isoformat()
            record["captured_at"] = camera["captured_at"]
        record["unchanged_since_last_run"] = True
    return {"sha256": digest, "captured_at": camera["captured_at"]}


def parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_catalog(
    config: dict[str, Any],
    store: StillStore,
    fetch: Callable[[str], ImageResponse] = fetch_image,
    fetch_xml: Callable[[str], bytes] = fetch_bytes,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now = now or datetime.now(UTC)
    area = load_area(config["region"])

    cameras: list[dict[str, Any]] = []
    log: list[dict[str, Any]] = []
    live_only: set[str] = set()
    for source in config["sources"]:
        if not source.get("enabled", True):
            continue
        first = len(cameras)
        if source["type"] == "datex2":
            # A feed outage must not stop the other providers: its cameras are left
            # out of this run (the feed is the only list of them) and the log says why.
            try:
                feed = fetch_xml(source["url"])
                cameras.extend(
                    parse_datex_cameras(
                        feed,
                        area,
                        source["url"],
                        source["attribution"],
                        source.get("provider", source["id"]),
                        credit_url=source["page"],
                    )
                )
            except (OSError, http.client.HTTPException, ET.ParseError) as exc:
                log.append({"source": source["id"], "status": "failed", "problem": f"feed unavailable: {exc}"})
        elif source["type"] == "static":
            cameras.extend(static_cameras(source, area))
        else:
            raise ValueError(f"Unsupported webcam source type: {source['type']}")
        if source.get("live_only"):
            live_only.update(camera["id"] for camera in cameras[first:])

    bodies: dict[str, dict[str, bytes]] = {}
    probe_log: list[dict[str, Any]] = []
    for camera in cameras:
        try:
            record, sizes = probe_camera_image(camera, fetch)
        except Exception as exc:  # noqa: BLE001 - one camera's unexpected failure must not stop the rest
            set_offline(camera)
            record, sizes = {"id": camera["id"], "status": "offline", "problem": f"ingest error: {exc!r}"}, {}
        probe_log.append(record)
        if sizes:
            bodies[camera["id"]] = sizes
    drop_shared_frames(cameras, probe_log, bodies)

    history = store.load_state().get("frames")
    history = history if isinstance(history, dict) else {}
    new_history: dict[str, Any] = {}
    for camera, record in zip(cameras, probe_log, strict=True):
        previous = history.get(camera["id"])
        previous = previous if isinstance(previous, dict) else None
        if camera["id"] not in bodies:
            # An offline run keeps the history, so a frozen frame that returns keeps its age.
            if previous:
                new_history[camera["id"]] = previous
            continue
        new_history[camera["id"]] = apply_history(camera, record, bodies[camera["id"]], previous)
        captured = parse_iso(camera["captured_at"])
        if camera["id"] in live_only and captured and now - captured > STALE_AFTER:
            set_offline(camera)
            bodies.pop(camera["id"])
            record.update(status="offline", problem=f"stale: frame captured at {captured.isoformat()}")
    store.save_state({"frames": new_history})

    kept: list[dict[str, Any]] = []
    for camera, record in zip(cameras, probe_log, strict=True):
        if camera["id"] in bodies:
            store_stills(camera, bodies[camera["id"]], store)
            record["stored"] = [camera["thumbnail_url"], camera["large_url"]]
        # A live_only source (DGT) lists hundreds of road cams, many dead for months:
        # a failed check leaves the card out of this run instead of an offline card.
        # Every run probes again, so a cam that comes back reappears.
        if camera["id"] in live_only and camera["status"] != "live":
            record["catalogue"] = "dropped"
        else:
            record["catalogue"] = "kept"
            kept.append(camera)
    return kept, log + probe_log


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
    parser.add_argument("--stills-dir", type=Path, default=DEFAULT_STILLS_DIR)
    parser.add_argument("--stills-prefix", default=DEFAULT_STILLS_PREFIX)
    args = parser.parse_args()
    store = LocalStillStore(args.stills_dir, args.stills_prefix)
    cameras, log = build_catalog(load_config(args.config), store)
    for record in log:
        print(json.dumps(record, ensure_ascii=False))
    write_catalog(cameras, args.output)
    live = sum(camera["status"] == "live" for camera in cameras)
    dropped = sum(record.get("catalogue") == "dropped" for record in log)
    print(f"Wrote {len(cameras)} webcams ({live} live) to {args.output}; dropped {dropped} that failed the check")


if __name__ == "__main__":
    main()
