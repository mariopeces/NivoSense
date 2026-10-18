from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_CATALOG_ENDPOINT = "https://sh.dataspace.copernicus.eu/catalog/v1/search"
DEFAULT_PROCESS_ENDPOINT = "https://sh.dataspace.copernicus.eu/process/v1"
DEFAULT_TOKEN_ENDPOINT = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)
DEFAULT_COLLECTION = "byoc-0b5265f5-3664-44c2-96ab-e91aba67b0c3"
SOURCE_RESOLUTION_METRES = 60


class PipelineError(RuntimeError):
    pass


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def item_datetime(item: dict[str, Any]) -> datetime:
    properties = item.get("properties", {})
    value = properties.get("datetime") or properties.get("start_datetime")
    if not isinstance(value, str):
        raise PipelineError(f"Catalog item {item.get('id', '<unknown>')} has no observation datetime")
    return parse_datetime(value)


def select_latest_products(catalog: dict[str, Any]) -> tuple[datetime, list[dict[str, Any]]]:
    features = catalog.get("features")
    if not isinstance(features, list) or not features:
        raise PipelineError("The GFSC catalog returned no products for the configured area and time window")

    dated = [(item_datetime(item), item) for item in features]
    latest_day = max(observed.date() for observed, _ in dated)
    selected = [item for observed, item in dated if observed.date() == latest_day]
    selected.sort(key=lambda item: str(item.get("id", "")))
    observed_at = max(item_datetime(item) for item in selected)
    return observed_at, selected


def geometry_bbox(path: Path) -> list[float]:
    with path.open(encoding="utf-8") as source:
        geojson = json.load(source)

    coordinates: list[tuple[float, float]] = []

    def visit(value: Any) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            coordinates.append((float(value[0]), float(value[1])))
            return
        if isinstance(value, list):
            for child in value:
                visit(child)

    for feature in geojson.get("features", []):
        visit(feature.get("geometry", {}).get("coordinates", []))
    if not coordinates:
        raise PipelineError(f"No coordinates found in {path}")

    xs, ys = zip(*coordinates)
    return [min(xs), min(ys), max(xs), max(ys)]


def request_json(url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise PipelineError(f"Request to {url} failed with HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise PipelineError(f"Request to {url} failed: {error.reason}") from error


def access_token() -> str:
    supplied = os.environ.get("GFSC_ACCESS_TOKEN")
    if supplied:
        return supplied

    client_id = os.environ.get("CDSE_CLIENT_ID")
    client_secret = os.environ.get("CDSE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise PipelineError(
            "Authentication is missing. Set GFSC_ACCESS_TOKEN or both CDSE_CLIENT_ID and CDSE_CLIENT_SECRET"
        )

    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode("utf-8")
    endpoint = os.environ.get("GFSC_TOKEN_ENDPOINT", DEFAULT_TOKEN_ENDPOINT)
    request = urllib.request.Request(endpoint, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise PipelineError(f"Token request failed with HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise PipelineError(f"Token request failed: {error.reason}") from error
    token = result.get("access_token")
    if not isinstance(token, str) or not token:
        raise PipelineError("Token endpoint did not return access_token")
    return token


def search_catalog(
    endpoint: str, collection: str, bbox: list[float], token: str, now: datetime
) -> dict[str, Any]:
    start = now - timedelta(days=14)
    return request_json(
        endpoint,
        {
            "collections": [collection],
            "bbox": bbox,
            "datetime": f"{start:%Y-%m-%dT%H:%M:%SZ}/{now:%Y-%m-%dT%H:%M:%SZ}",
            "limit": 100,
        },
        token,
    )


def output_dimensions(bbox: list[float]) -> tuple[int, int]:
    west, south, east, north = bbox
    middle_latitude = math.radians((south + north) / 2)
    width_metres = (east - west) * 111_320 * math.cos(middle_latitude)
    height_metres = (north - south) * 110_574
    return (
        max(1, math.ceil(width_metres / SOURCE_RESOLUTION_METRES)),
        max(1, math.ceil(height_metres / SOURCE_RESOLUTION_METRES)),
    )


def process_payload(
    collection: str, bbox: list[float], observed_at: datetime
) -> dict[str, Any]:
    width, height = output_dimensions(bbox)
    day_start = observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    evalscript = """//VERSION=3
function setup() {
  return {
    input: [{bands: [\"GF\", \"GF_QA\", \"dataMask\"]}],
    output: {bands: 2, sampleType: \"UINT8\", nodataValue: 255}
  };
}
function evaluatePixel(sample) {
  return sample.dataMask ? [sample.GF, sample.GF_QA] : [255, 255];
}"""
    return {
        "input": {
            "bounds": {"bbox": bbox, "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"}},
            "data": [
                {
                    "type": collection,
                    "dataFilter": {
                        "timeRange": {
                            "from": day_start.isoformat().replace("+00:00", "Z"),
                            "to": day_end.isoformat().replace("+00:00", "Z"),
                        },
                        "mosaickingOrder": "mostRecent",
                    },
                }
            ],
        },
        "output": {
            "width": width,
            "height": height,
            "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
        },
        "evalscript": evalscript,
    }


def download_observation(
    endpoint: str, payload: dict[str, Any], token: str, destination: Path
) -> None:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "image/tiff",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response, destination.open("wb") as target:
            shutil.copyfileobj(response, target)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise PipelineError(f"GFSC download failed with HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise PipelineError(f"GFSC download failed: {error.reason}") from error

    if destination.stat().st_size == 0:
        raise PipelineError("GFSC download returned an empty raster")


def build_manifest(
    *,
    bbox: list[float],
    collection: str,
    observed_at: datetime,
    products: list[dict[str, Any]],
    generated_at: datetime,
    layer_path: str,
    public_base_url: str | None,
) -> dict[str, Any]:
    age_days = max(0, (generated_at.date() - observed_at.date()).days)
    freshness = "current" if age_days <= 2 else "delayed" if age_days <= 7 else "stale"
    layer: dict[str, Any] = {
        "path": layer_path,
        "media_type": "image/tiff; application=geotiff",
        "bands": ["snow_fraction", "quality"],
    }
    if public_base_url:
        layer["url"] = f"{public_base_url.rstrip('/')}/{layer_path}"
    return {
        "schema_version": 1,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "observation": {
            "date": observed_at.date().isoformat(),
            "datetime": observed_at.isoformat().replace("+00:00", "Z"),
            "age_days": age_days,
            "freshness": freshness,
        },
        "source": {
            "provider": "Copernicus Land Monitoring Service",
            "product": "GFSC Europe 60m Daily V1",
            "collection": collection,
            "item_ids": [str(product.get("id", "")) for product in products],
            "native_resolution_m": SOURCE_RESOLUTION_METRES,
        },
        "coverage": {"bbox": bbox, "crs": "EPSG:4326"},
        "quality": {
            "band": 2,
            "values": {"0": "high", "1": "medium", "2": "low", "3": "minimal"},
            "special_values": {"205": "cloud_or_shadow", "210": "inland_water"},
            "nodata": 255,
        },
        "layer": layer,
    }


def validate_manifest(manifest: dict[str, Any]) -> None:
    required = {"schema_version", "generated_at", "observation", "source", "coverage", "quality", "layer"}
    missing = required - manifest.keys()
    if missing:
        raise PipelineError(f"Manifest is missing fields: {', '.join(sorted(missing))}")
    parse_datetime(manifest["generated_at"])
    parse_datetime(manifest["observation"]["datetime"])
    if manifest["observation"]["date"] != manifest["observation"]["datetime"][:10]:
        raise PipelineError("Manifest observation date and datetime disagree")
    bbox = manifest["coverage"]["bbox"]
    if not isinstance(bbox, list) or len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise PipelineError("Manifest coverage bbox is invalid")
    if manifest["source"]["native_resolution_m"] != SOURCE_RESOLUTION_METRES:
        raise PipelineError("Manifest source resolution is invalid")
    if not manifest["layer"].get("path"):
        raise PipelineError("Manifest layer path is missing")


def fixture_inputs(path: Path) -> tuple[dict[str, Any], Path]:
    if os.environ.get("NIVOSENSE_TEST_MODE") != "1":
        raise PipelineError("Fixture mode is restricted to tests; set NIVOSENSE_TEST_MODE=1")
    catalog_path = path / "catalog.json"
    raster_path = path / "observation.tif"
    if not catalog_path.is_file() or not raster_path.is_file():
        raise PipelineError("Fixture directory must contain catalog.json and observation.tif")
    with catalog_path.open(encoding="utf-8") as source:
        return json.load(source), raster_path


def run(args: argparse.Namespace) -> Path:
    now = datetime.now(timezone.utc)
    bbox = geometry_bbox(args.area)
    collection = os.environ.get("GFSC_COLLECTION", DEFAULT_COLLECTION)

    if args.fixture:
        catalog, fixture_raster = fixture_inputs(args.fixture)
        token = None
    else:
        token = access_token()
        catalog = search_catalog(
            os.environ.get("GFSC_CATALOG_ENDPOINT", DEFAULT_CATALOG_ENDPOINT),
            collection,
            bbox,
            token,
            now,
        )

    observed_at, products = select_latest_products(catalog)
    args.output.mkdir(parents=True, exist_ok=True)
    raster_path = args.output / "gfsc_latest.tif"
    if args.fixture:
        shutil.copyfile(fixture_raster, raster_path)
    else:
        download_observation(
            os.environ.get("GFSC_PROCESS_ENDPOINT", DEFAULT_PROCESS_ENDPOINT),
            process_payload(collection, bbox, observed_at),
            token,
            raster_path,
        )

    manifest = build_manifest(
        bbox=bbox,
        collection=collection,
        observed_at=observed_at,
        products=products,
        generated_at=now,
        layer_path=raster_path.name,
        public_base_url=os.environ.get("GFSC_PUBLIC_BASE_URL"),
    )
    validate_manifest(manifest)
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch the latest daily GFSC observation")
    parser.add_argument("--area", type=Path, default=Path("data/basins.geojson"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/generated/observations/sierra-nevada/latest")
    )
    parser.add_argument("--fixture", type=Path)
    return parser.parse_args()


def main() -> int:
    try:
        manifest_path = run(parse_args())
    except (PipelineError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"GFSC pipeline failed: {error}", file=sys.stderr)
        return 1
    print(f"GFSC observation written to {manifest_path.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
