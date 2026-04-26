"""
Run 1-week NDSI forecast for a given S2 acquisition.

Usage
-----
    python ml/predict_1week.py --year 2026 --month apr
    python ml/predict_1week.py --year 2026 --month apr --timestamp 20260420t104501z

Output filename uses the predicted date (~7 days after input acquisition).
"""
import argparse
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import rasterio
from google.cloud import storage

GCS_OBS_BUCKET  = "nivosense-cogs"
GCS_OBS_PREFIX  = "observations/sierra-nevada"
GCS_PRED_PREFIX = "predictions/sierra-nevada"
MODEL_PATH      = Path(__file__).parent / "models" / "lgbm_1week.txt"
OUTPUT_DIR      = Path(__file__).parent / "predictions"

_OBS_RE = re.compile(r"ndsi_(\d{4})_(\w{3})_(\w+)\.tif$")
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _list_acquisitions() -> list[dict]:
    client = storage.Client()
    acqs = []
    for blob in client.bucket(GCS_OBS_BUCKET).list_blobs(prefix=GCS_OBS_PREFIX):
        m = _OBS_RE.search(blob.name)
        if m:
            month_str = m.group(2)
            timestamp = m.group(3)
            date = datetime.strptime(timestamp[:8], "%Y%m%d")
            acqs.append({
                "uri":       f"gs://{GCS_OBS_BUCKET}/{blob.name}",
                "year":      int(m.group(1)),
                "month_str": month_str,
                "month":     _MONTH_MAP.get(month_str, 0),
                "timestamp": timestamp,
                "date":      date,
                "doy":       date.timetuple().tm_yday,
            })
    return sorted(acqs, key=lambda x: x["date"])


def _download(uri: str, dest: Path) -> None:
    bucket_name, blob_path = uri.replace("gs://", "").split("/", 1)
    storage.Client().bucket(bucket_name).blob(blob_path).download_to_filename(str(dest), timeout=120)


def _upload(local_path: Path, blob_path: str) -> None:
    storage.Client().bucket(GCS_OBS_BUCKET).blob(blob_path).upload_from_filename(str(local_path))
    print(f"Uploaded to gs://{GCS_OBS_BUCKET}/{blob_path}")


def predict(year: int, month: str, timestamp: str | None = None) -> Path:
    print("Loading model...")
    model = lgb.Booster(model_file=str(MODEL_PATH))
    features = model.feature_name()

    print("Listing acquisitions from GCS...")
    acqs = _list_acquisitions()

    candidates = [a for a in acqs if a["year"] == year and a["month_str"] == month]
    if not candidates:
        raise ValueError(f"No acquisitions found for {year}/{month}")

    if timestamp:
        acq = next((a for a in candidates if a["timestamp"] == timestamp), None)
        if acq is None:
            raise ValueError(f"Timestamp {timestamp} not found for {year}/{month}")
    else:
        acq = candidates[-1]
        print(f"  Using latest: {acq['timestamp']}")

    idx = acqs.index(acq)
    prev = acqs[idx - 1] if idx > 0 else None

    # Predicted date = input date + 7 days
    pred_date = acq["date"] + timedelta(days=7)
    pred_date_str = pred_date.strftime("%Y%m%d")
    pred_month_str = pred_date.strftime("%b").lower()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        print(f"Downloading COG: {acq['uri']}")
        curr_path = tmp / "curr.tif"
        _download(acq["uri"], curr_path)

        prev_path = None
        if prev:
            prev_path = tmp / "prev.tif"
            _download(prev["uri"], prev_path)

        with rasterio.open(curr_path) as src:
            profile   = src.profile.copy()
            ndsi_t    = src.read(1).astype(np.float32)
            elevation = src.read(2).astype(np.float32)
            slope     = src.read(3).astype(np.float32)
            aspect    = src.read(4).astype(np.float32)

        ndsi_t_prev = np.full_like(ndsi_t, np.nan)
        if prev_path:
            with rasterio.open(prev_path) as src:
                ndsi_t_prev = src.read(1).astype(np.float32)

        rows_shape, cols_shape = ndsi_t.shape
        valid = ~np.isnan(ndsi_t) & ~np.isnan(elevation)
        flat_idx = np.argwhere(valid)
        r, c = flat_idx[:, 0], flat_idx[:, 1]

        feature_arrays = {
            "ndsi_t":      ndsi_t[r, c],
            "ndsi_t_prev": ndsi_t_prev[r, c],
            "elevation":   elevation[r, c],
            "slope":       slope[r, c],
            "aspect":      aspect[r, c],
            "month":       np.full(len(r), acq["month"],  dtype=np.float32),
            "doy":         np.full(len(r), acq["doy"],    dtype=np.float32),
        }

        # Fill any extra features (e.g. weather) with NaN if not available
        for f in features:
            if f not in feature_arrays:
                feature_arrays[f] = np.full(len(r), np.nan, dtype=np.float32)

        X = pd.DataFrame({f: feature_arrays[f] for f in features})

        print(f"Predicting {len(r):,} valid pixels → target date {pred_date.date()}...")
        preds = model.predict(X).astype(np.float32)
        preds = np.clip(preds, -1.0, 1.0)

        pred_raster = np.full((rows_shape, cols_shape), np.nan, dtype=np.float32)
        pred_raster[r, c] = preds

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_name = f"ndsi_pred_{pred_date_str}.tif"
        out_path = OUTPUT_DIR / out_name

        profile.update(count=1, dtype="float32", nodata=np.nan)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(pred_raster, 1)

        print(f"Saved to {out_path}")

        blob_path = f"{GCS_PRED_PREFIX}/{year}/{pred_month_str}/{out_name}"
        _upload(out_path, blob_path)

    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year",      type=int, required=True)
    parser.add_argument("--month",     type=str, required=True)
    parser.add_argument("--timestamp", type=str, default=None)
    args = parser.parse_args()

    predict(year=args.year, month=args.month, timestamp=args.timestamp)
