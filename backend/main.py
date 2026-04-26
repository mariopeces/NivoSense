from datetime import date, datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import urlopen
import json
import re
import time

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.errors import RasterioIOError
from rasterio.features import geometry_mask
from rasterio.mask import mask
from rasterio.transform import from_bounds
from rasterio.warp import reproject, transform_bounds, transform_geom
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="NivoSense API", version="0.1.0")

# Demo pública durante el hackathon: CORS abierto.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LAYERS_FILE = Path(__file__).parent / "layers.yaml"
with LAYERS_FILE.open("r", encoding="utf-8") as f:
    LAYERS: dict = yaml.safe_load(f).get("layers", {})

BUCKET = "nivosense-cogs"
REGION = "sierra-nevada"
PUBLIC_BASE_URL = f"https://storage.googleapis.com/{BUCKET}"
STORAGE_API_URL = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o"
OBSERVATION_RE = re.compile(
    r"^observations/sierra-nevada/(?P<year>\d{4})/[a-z]{3}/"
    r"ndsi_\d{4}_[a-z]{3}_(?P<stamp>\d{8}t\d{6}z)\.tif$"
)
PREDICTION_RE = re.compile(
    r"^predictions/sierra-nevada/\d{4}/[a-z]{3}/"
    r"ndsi_pred_(?P<date>\d{8})\.tif$"
)
SNOW_NDSI_THRESHOLD = 0.4
TILE_SIZE = 256
WEB_MERCATOR_LIMIT = 20037508.342789244
TILE_VERSION = "20260425-reprojected"

RIVERS: list[dict] = [
    {
        "id": "dilar",
        "name": "Río Dilar",
        "basin_cod_uni": 508678,
        "station_id": "5086",
        "station_name": "Dilar (A05)",
        "source": "SAIH Guadalquivir",
        "variable": "caudal",
        "unit": "m3/s",
    },
    {
        "id": "alhori",
        "name": "Río Alhorí",
        "basin_cod_uni": 508678,
        "station_id": "5051",
        "station_name": "Jerez del Marquesado (A53)",
        "source": "SAIH Guadalquivir",
        "variable": "caudal",
        "unit": "m3/s",
    },
    {
        "id": "guadalfeo",
        "name": "Río Guadalfeo",
        "basin_cod_uni": 604456,
        "station_id": "73",
        "station_name": "Órgiva",
        "source": "Hidrosur",
        "variable": "caudal",
        "unit": "m3/s",
    },
    {
        "id": "andarax",
        "name": "Río Andarax",
        "basin_cod_uni": 604370,
        "station_id": "90",
        "station_name": "Terque",
        "source": "Hidrosur",
        "variable": "caudal",
        "unit": "m3/s",
    },
]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/layers")
def list_layers():
    return [
        {"id": key, "label": meta.get("label", key), "path": meta.get("path")}
        for key, meta in LAYERS.items()
    ]


@app.get("/observations")
def list_observations(
    start: date | None = None,
    end: date | None = None,
    region: str = REGION,
):
    if region != REGION:
        raise HTTPException(status_code=404, detail="Region not found")

    observations = get_observations()
    if start:
        observations = [item for item in observations if item["date"] >= start]
    if end:
        observations = [item for item in observations if item["date"] <= end]

    return [
        {
            "date": item["date"].isoformat(),
            "path": item["path"],
            "url": item["url"],
            "tile_url": (
                f"/observations/{item['date'].isoformat()}"
                f"/tiles/{{z}}/{{x}}/{{y}}.png?v={TILE_VERSION}"
            ),
            "size": item["size"],
        }
        for item in observations
    ]


@app.get("/observations/{observed_on}/tiles/{z}/{x}/{y}.png")
def observation_tile(observed_on: date, z: int, x: int, y: int):
    if z < 0 or z > 18:
        raise HTTPException(status_code=400, detail="Invalid zoom")
    max_tile = (2**z) - 1
    if x < 0 or y < 0 or x > max_tile or y > max_tile:
        raise HTTPException(status_code=400, detail="Invalid tile")

    observation = get_observation_by_date(observed_on)
    try:
        png = render_ndsi_tile(observation["url"], z, x, y)
    except RasterioIOError as exc:
        raise HTTPException(status_code=502, detail="Could not read COG") from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/predictions")
def list_predictions():
    return [
        {
            "date": p["date"].isoformat(),
            "path": p["path"],
            "url": p["url"],
            "tile_url": f"/predictions/{p['date'].isoformat()}/tiles/{{z}}/{{x}}/{{y}}.png",
        }
        for p in get_predictions()
    ]


@app.get("/predictions/{predicted_on}/tiles/{z}/{x}/{y}.png")
def prediction_tile(predicted_on: date, z: int, x: int, y: int):
    if z < 0 or z > 18:
        raise HTTPException(status_code=400, detail="Invalid zoom")
    max_tile = (2**z) - 1
    if x < 0 or y < 0 or x > max_tile or y > max_tile:
        raise HTTPException(status_code=400, detail="Invalid tile")

    prediction = next(
        (p for p in get_predictions() if p["date"] == predicted_on), None
    )
    if prediction is None:
        raise HTTPException(status_code=404, detail="Prediction not found")

    try:
        png = render_ndsi_tile(prediction["url"], z, x, y)
    except RasterioIOError as exc:
        raise HTTPException(status_code=502, detail="Could not read COG") from exc

    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/rivers")
def list_rivers():
    return RIVERS


@app.get("/rivers/{river_id}/flow")
def river_flow(river_id: str):
    river = next((r for r in RIVERS if r["id"] == river_id), None)
    if river is None:
        raise HTTPException(status_code=404, detail="River not found")

    url = f"{PUBLIC_BASE_URL}/static/{REGION}/flow/{river_id}.json"
    try:
        with urlopen(url, timeout=20) as response:
            payload = json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Flow data not yet uploaded for {river_id}. "
                    "Run ml/normalize_flow.py and upload to "
                    f"gs://{BUCKET}/static/{REGION}/flow/{river_id}.json."
                ),
            ) from exc
        raise

    payload.setdefault("river_id", river_id)
    payload.setdefault("river_name", river["name"])
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.get("/basins/{basin_id}/snow-series")
def basin_snow_series(
    basin_id: str,
    hydrological_year: int = Query(2024, ge=1900, le=2100),
):
    url = (
        f"{PUBLIC_BASE_URL}/static/{REGION}/basins/"
        f"{basin_id}/series_{hydrological_year}.json"
    )
    try:
        with urlopen(url, timeout=20) as response:
            payload = json.load(response)
            return JSONResponse(
                payload,
                headers={"Cache-Control": "no-store"},
            )
    except HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Basin series has not been precomputed. "
                    "Run backend/build_basin_series.py for this year."
                ),
            ) from exc
        raise


_obs_cache: list = []
_obs_cache_ts: float = 0.0
_pred_cache: list = []
_pred_cache_ts: float = 0.0
_OBS_CACHE_TTL = 300  # refresh every 5 minutes


def get_observations():
    global _obs_cache, _obs_cache_ts
    if time.time() - _obs_cache_ts < _OBS_CACHE_TTL and _obs_cache:
        return _obs_cache
    _obs_cache = _fetch_observations()
    _obs_cache_ts = time.time()
    return _obs_cache


def get_predictions():
    global _pred_cache, _pred_cache_ts
    if time.time() - _pred_cache_ts < _OBS_CACHE_TTL and _pred_cache:
        return _pred_cache
    _pred_cache = _fetch_predictions()
    _pred_cache_ts = time.time()
    return _pred_cache


def _fetch_predictions():
    prefix = f"predictions/{REGION}/"
    objects = list_bucket_objects(prefix)
    predictions = []
    for obj in objects:
        name = obj.get("name", "")
        match = PREDICTION_RE.match(name)
        if not match:
            continue
        pred_date = datetime.strptime(match.group("date"), "%Y%m%d").date()
        predictions.append(
            {
                "date": pred_date,
                "path": f"gs://{BUCKET}/{name}",
                "url": f"{PUBLIC_BASE_URL}/{name}",
            }
        )
    return sorted(predictions, key=lambda p: p["date"])


def _fetch_observations():
    prefix = f"observations/{REGION}/"
    objects = list_bucket_objects(prefix)
    observations = []

    for obj in objects:
        name = obj.get("name", "")
        match = OBSERVATION_RE.match(name)
        if not match:
            continue
        observed_at = datetime.strptime(match.group("stamp"), "%Y%m%dt%H%M%Sz")
        observations.append(
            {
                "date": observed_at.date(),
                "path": f"gs://{BUCKET}/{name}",
                "url": f"{PUBLIC_BASE_URL}/{name}",
                "size": int(obj.get("size", 0)),
            }
        )

    return sorted(observations, key=lambda item: item["date"])


def get_observation_by_date(observed_on: date):
    for observation in get_observations():
        if observation["date"] == observed_on:
            return observation
    raise HTTPException(status_code=404, detail="Observation not found")


def render_ndsi_tile(url: str, z: int, x: int, y: int) -> bytes:
    mercator_bounds = xyz_bounds(z, x, y)
    destination = np.full((TILE_SIZE, TILE_SIZE), np.nan, dtype="float32")
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(url) as dataset:
            if dataset.crs is None:
                return transparent_tile()

            left, bottom, right, top = transform_bounds(
                "EPSG:3857",
                dataset.crs,
                *mercator_bounds,
                densify_pts=21,
            )
            if (
                right < dataset.bounds.left
                or left > dataset.bounds.right
                or top < dataset.bounds.bottom
                or bottom > dataset.bounds.top
            ):
                return transparent_tile()

            reproject(
                source=rasterio.band(dataset, 1),
                destination=destination,
                src_transform=dataset.transform,
                src_crs=dataset.crs,
                src_nodata=dataset.nodata,
                dst_transform=from_bounds(*mercator_bounds, TILE_SIZE, TILE_SIZE),
                dst_crs="EPSG:3857",
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )

    values = np.asarray(destination, dtype="float32")
    valid = np.isfinite(values)
    clipped = np.clip(values, 0, 1)
    rgba = colorize_ndsi(clipped, valid)
    buffer = BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def xyz_bounds(z: int, x: int, y: int):
    tiles = 2**z
    span = (WEB_MERCATOR_LIMIT * 2) / tiles
    left = -WEB_MERCATOR_LIMIT + x * span
    right = left + span
    top = WEB_MERCATOR_LIMIT - y * span
    bottom = top - span
    return left, bottom, right, top


def colorize_ndsi(values: np.ndarray, valid: np.ndarray):
    values = np.nan_to_num(values, nan=0, posinf=1, neginf=0)
    low = np.array([15, 23, 42], dtype="float32")
    mid = np.array([34, 211, 238], dtype="float32")
    high = np.array([236, 254, 255], dtype="float32")

    t = values[..., None]
    first = low + (mid - low) * np.minimum(t * 2, 1)
    second = mid + (high - mid) * np.maximum((t - 0.5) * 2, 0)
    rgb = np.where(t <= 0.5, first, second).astype("uint8")
    alpha = np.where(valid, np.clip(45 + values * 175, 35, 220), 0)

    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype="uint8")
    rgba[..., :3] = rgb
    rgba[..., 3] = alpha.astype("uint8")
    return rgba


def transparent_tile():
    buffer = BytesIO()
    Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0)).save(
        buffer,
        format="PNG",
    )
    return buffer.getvalue()


def list_bucket_objects(prefix: str):
    items = []
    page_token = None
    while True:
        url = f"{STORAGE_API_URL}?prefix={quote(prefix, safe='')}&maxResults=1000"
        if page_token:
            url += f"&pageToken={quote(page_token, safe='')}"
        with urlopen(url, timeout=20) as response:
            payload = json.load(response)
        items.extend(payload.get("items", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            return items


def group_monthly_observations(observations: list[dict]):
    by_month: dict[tuple[int, int], list[dict]] = {}
    for observation in observations:
        key = (observation["date"].year, observation["date"].month)
        by_month.setdefault(key, []).append(observation)
    return [
        sorted(items, key=lambda item: abs(item["date"].day - 15))
        for _, items in sorted(by_month.items())
    ]


def best_monthly_point(observations: list[dict], geometry: dict, threshold: float):
    fallback = None
    for observation in observations:
        point = observation_point(observation, geometry, threshold)
        if fallback is None:
            fallback = point
        if point["valid_pixels"] > 0:
            return point
    return fallback


def observation_point(observation: dict, geometry: dict, threshold: float):
    stats = snow_coverage_for_observation(
        observation["url"],
        geometry,
        threshold,
    )
    return {
        "date": observation["date"].isoformat(),
        "label": observation["date"].strftime("%d %b"),
        "observed": stats["snow_pct"],
        "total_pixels": stats["total_pixels"],
        "valid_pixels": stats["valid_pixels"],
        "masked_pixels": stats["masked_pixels"],
        "data_coverage_pct": stats["data_coverage_pct"],
        "snow_pixels": stats["snow_pixels"],
        "source": observation["path"],
    }


@lru_cache(maxsize=1)
def get_basins():
    url = f"{PUBLIC_BASE_URL}/static/{REGION}/basins.geojson"
    with urlopen(url, timeout=20) as response:
        return json.load(response)


def get_basin_feature(basin_id: str):
    for feature in get_basins().get("features", []):
        if str(feature.get("properties", {}).get("cod_uni")) == basin_id:
            return feature
    raise HTTPException(status_code=404, detail="Basin not found")


def snow_coverage_for_observation(url: str, geometry: dict, threshold: float):
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(url) as dataset:
            raster_geometry = geometry
            if dataset.crs and dataset.crs.to_string() != "EPSG:4326":
                raster_geometry = transform_geom(
                    "EPSG:4326",
                    dataset.crs,
                    geometry,
                    precision=6,
                )

            data, transform = mask(
                dataset,
                [raster_geometry],
                crop=True,
                indexes=1,
                filled=False,
            )
            band = data.astype("float32", copy=False)
            inside_geometry = geometry_mask(
                [raster_geometry],
                out_shape=band.shape,
                transform=transform,
                invert=True,
            )
            valid = inside_geometry & ~np.ma.getmaskarray(band)
            values = np.asarray(band.filled(np.nan), dtype="float32")
            valid &= np.isfinite(values)
            if dataset.nodata is not None:
                valid &= values != dataset.nodata

            total_pixels = int(inside_geometry.sum())
            valid_pixels = int(valid.sum())
            masked_pixels = total_pixels - valid_pixels
            if valid_pixels == 0:
                return {
                    "snow_pct": None,
                    "total_pixels": total_pixels,
                    "valid_pixels": 0,
                    "masked_pixels": masked_pixels,
                    "data_coverage_pct": 0,
                    "snow_pixels": 0,
                }

            snow_pixels = int((valid & (values >= threshold)).sum())
            return {
                "snow_pct": round((snow_pixels / total_pixels) * 100, 2)
                if total_pixels
                else None,
                "total_pixels": total_pixels,
                "valid_pixels": valid_pixels,
                "masked_pixels": masked_pixels,
                "data_coverage_pct": round((valid_pixels / total_pixels) * 100, 2)
                if total_pixels
                else None,
                "snow_pixels": snow_pixels,
            }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
