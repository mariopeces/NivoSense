from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen
import json
import re
import time

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.mask import mask
from rasterio.warp import transform_geom
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

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
SNOW_NDSI_THRESHOLD = 0.4


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
            "size": item["size"],
        }
        for item in observations
    ]


@app.get("/basins/{basin_id}/snow-series")
def basin_snow_series(
    basin_id: str,
    hydrological_year: int = Query(2018, ge=1900, le=2100),
    threshold: float = Query(SNOW_NDSI_THRESHOLD, ge=0, le=1),
    cadence: str = Query("monthly", pattern="^(monthly|all)$"),
):
    basin = get_basin_feature(basin_id)
    start = date(hydrological_year, 10, 1)
    end = date(hydrological_year + 1, 9, 30)
    observations = [
        item for item in get_observations() if start <= item["date"] <= end
    ]

    points = []
    if cadence == "monthly":
        for candidates in group_monthly_observations(observations):
            points.append(
                best_monthly_point(candidates, basin["geometry"], threshold)
            )
    else:
        for observation in observations:
            points.append(
                observation_point(observation, basin["geometry"], threshold)
            )

    return {
        "basin_id": basin_id,
        "basin_name": basin["properties"].get("nom_rio_1"),
        "hydrological_year": f"{hydrological_year}-{hydrological_year + 1}",
        "threshold": threshold,
        "cadence": cadence,
        "points": points,
    }


_obs_cache: list = []
_obs_cache_ts: float = 0.0
_OBS_CACHE_TTL = 300  # refresh every 5 minutes


def get_observations():
    global _obs_cache, _obs_cache_ts
    if time.time() - _obs_cache_ts < _OBS_CACHE_TTL and _obs_cache:
        return _obs_cache
    _obs_cache = _fetch_observations()
    _obs_cache_ts = time.time()
    return _obs_cache


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
                "snow_pct": round((snow_pixels / valid_pixels) * 100, 2),
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
