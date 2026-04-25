"""
Build the LightGBM training dataset at basin level.

For each basin × year, computes:
  - Mean NDSI per month (from observation COGs)
  - NDSI anomaly vs 2018-2024 historical mean per basin × month
  - Zonal climate stats (prcp, tavg, tmin, tmax) per season
  - Terrain stats (elevation, slope, aspect) — static per basin

Target variable:
  Spring NDSI anomaly (apr + may average) — negative = scarcity risk.

Output: parquet at ml/data/dataset.parquet
  Columns: basin_id, year, [monthly ndsi anomalies], [climate features],
           [terrain features], target_spring_anomaly
"""
import json
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from google.cloud import storage
from rasterstats import zonal_stats

# ── paths ──────────────────────────────────────────────────────────────────
GCS_OBS_BUCKET   = "nivosense-cogs"
GCS_OBS_PREFIX   = "observations/sierra-nevada"
GCS_SRC_BUCKET   = "darwin-general-hdh-sandbox-tiles"
GCS_CLIMATE_PREFIX = "tiles/guest/raster/temporal"
GCS_BASINS_URI   = "gs://nivosense-cogs/static/sierra-nevada/basins.geojson"

CLIMATE_VARS   = ["prcp", "tavg", "tmin", "tmax"]
WINTER_MONTHS  = ["jan", "feb", "mar"]
SPRING_MONTHS  = ["apr", "may"]
SNOW_MONTHS    = ["jan", "feb", "mar", "apr", "may", "oct"]

OUTPUT_PATH = Path(__file__).parent / "data" / "dataset.parquet"

_OBS_RE = re.compile(r"ndsi_(\d{4})_(\w{3})_\w+\.tif$")


# ── helpers ────────────────────────────────────────────────────────────────

def _load_basins() -> gpd.GeoDataFrame:
    client = storage.Client()
    bucket = client.bucket("nivosense-cogs")
    blob = bucket.blob("static/sierra-nevada/basins.geojson")
    data = json.loads(blob.download_as_text())
    return gpd.GeoDataFrame.from_features(data["features"], crs="EPSG:4326")


def _list_obs_blobs() -> list[dict]:
    """List all observation COGs grouped by year/month."""
    client = storage.Client()
    blobs = []
    for blob in client.bucket(GCS_OBS_BUCKET).list_blobs(prefix=GCS_OBS_PREFIX):
        m = _OBS_RE.search(blob.name)
        if m:
            blobs.append({"year": int(m.group(1)), "month": m.group(2), "uri": f"gs://{GCS_OBS_BUCKET}/{blob.name}"})
    return blobs


def _zonal_mean(raster_uri: str, basins: gpd.GeoDataFrame, band: int = 1) -> np.ndarray:
    """Return mean value of band per basin. NaN where no valid pixels."""
    with rasterio.open(raster_uri) as src:
        basins_reproj = basins.to_crs(src.crs)
        stats = zonal_stats(
            basins_reproj,
            raster_uri,
            band=band,
            stats=["mean"],
            nodata=src.nodata,
            all_touched=False,
        )
    return np.array([s["mean"] if s["mean"] is not None else np.nan for s in stats])


def _climate_uri(var: str, year: int, season: str) -> str:
    fname = f"easyclimate_{var}_{year}_{season}_sierra_nevada.tif"
    return f"gs://{GCS_SRC_BUCKET}/{GCS_CLIMATE_PREFIX}/{var}/{year}/{season}/{fname}"


def _month_to_season(month: str) -> str:
    return {
        "jan": "winter", "feb": "winter", "mar": "spring",
        "apr": "spring", "may": "spring", "oct": "autumn",
    }.get(month, "annual")


# ── main ───────────────────────────────────────────────────────────────────

def build_dataset() -> pd.DataFrame:
    print("Loading basins...")
    basins = _load_basins()
    n_basins = len(basins)
    basin_ids = basins["cod_uni"].tolist()
    print(f"  {n_basins} basins found")

    # Step 1: collect mean NDSI per basin × year × month
    print("\nComputing NDSI zonal stats per basin...")
    obs_blobs = _list_obs_blobs()
    ndsi_records = []  # {year, month, basin_id, ndsi_mean}

    for i, obs in enumerate(obs_blobs):
        print(f"  [{i+1}/{len(obs_blobs)}] {obs['year']}/{obs['month']}", end="\r")
        means = _zonal_mean(obs["uri"], basins, band=1)
        for basin_id, mean_val in zip(basin_ids, means):
            ndsi_records.append({
                "year": obs["year"],
                "month": obs["month"],
                "basin_id": str(basin_id),
                "ndsi_mean": mean_val,
            })

    ndsi_df = pd.DataFrame(ndsi_records)

    # Step 2: historical mean per basin × month (across all years)
    hist_mean = (
        ndsi_df.groupby(["basin_id", "month"])["ndsi_mean"]
        .mean()
        .rename("ndsi_hist_mean")
        .reset_index()
    )
    ndsi_df = ndsi_df.merge(hist_mean, on=["basin_id", "month"])
    ndsi_df["ndsi_anomaly"] = (
        (ndsi_df["ndsi_mean"] - ndsi_df["ndsi_hist_mean"])
        / ndsi_df["ndsi_hist_mean"].replace(0, np.nan)
    )

    # Step 3: terrain stats per basin (static — use any single acquisition)
    print("\nComputing terrain zonal stats (static)...")
    sample_uri = obs_blobs[0]["uri"]
    terrain_data = []
    for band, name in [(2, "elev_mean"), (3, "slope_mean"), (4, "aspect_mean")]:
        vals = _zonal_mean(sample_uri, basins, band=band)
        terrain_data.append(pd.Series(vals, index=[str(b) for b in basin_ids], name=name))
    terrain_df = pd.concat(terrain_data, axis=1).reset_index().rename(columns={"index": "basin_id"})
    basin_names = basins[["cod_uni", "nom_rio_1"]].copy()
    basin_names["basin_id"] = basin_names["cod_uni"].astype(str)
    terrain_df = terrain_df.merge(basin_names[["basin_id", "nom_rio_1"]], on="basin_id", how="left")

    # Step 4: climate zonal stats per basin × year × season
    print("\nComputing climate zonal stats per basin...")
    years = ndsi_df["year"].unique()
    climate_records = []

    for year in years:
        for var in CLIMATE_VARS:
            for season in ["winter", "spring", "autumn", "annual"]:
                try:
                    uri = _climate_uri(var, year, season)
                    means = _zonal_mean(uri, basins, band=1)
                    for basin_id, val in zip(basin_ids, means):
                        climate_records.append({
                            "year": year,
                            "basin_id": basin_id,
                            f"{var}_{season}": val,
                        })
                except Exception:
                    pass  # missing climate file for this year/season

    # Pivot climate records into one row per basin × year
    climate_df = pd.DataFrame(climate_records)
    climate_df = (
        climate_df.groupby(["year", "basin_id"])
        .first()
        .reset_index()
    )

    # Step 5: build feature matrix — one row per basin × year
    # Winter features: mean NDSI anomaly across jan/feb/mar
    winter_df = (
        ndsi_df[ndsi_df["month"].isin(WINTER_MONTHS)]
        .groupby(["year", "basin_id"])["ndsi_anomaly"]
        .mean()
        .rename("ndsi_anomaly_winter")
        .reset_index()
    )

    # Target: mean NDSI anomaly across apr/may
    spring_df = (
        ndsi_df[ndsi_df["month"].isin(SPRING_MONTHS)]
        .groupby(["year", "basin_id"])["ndsi_anomaly"]
        .mean()
        .rename("target_spring_anomaly")
        .reset_index()
    )

    dataset = (
        winter_df
        .merge(spring_df, on=["year", "basin_id"])
        .merge(terrain_df, on="basin_id")
        .merge(climate_df, on=["year", "basin_id"], how="left")
    )

    # Drop rows where target is NaN (no spring data for that year)
    dataset = dataset.dropna(subset=["target_spring_anomaly"])

    print(f"\nDataset shape: {dataset.shape}")
    print(f"Years: {sorted(dataset['year'].unique())}")
    print(f"Basins: {dataset['basin_id'].nunique()}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_parquet(OUTPUT_PATH, index=False)
    print(f"\nSaved to {OUTPUT_PATH}")

    return dataset


if __name__ == "__main__":
    build_dataset()
