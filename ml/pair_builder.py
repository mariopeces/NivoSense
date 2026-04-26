"""
Build pixel-level training pairs for the 1-week NDSI forecast model.

For each consecutive pair of S2 acquisitions 4–12 days apart:
  - Reads both observation COGs from gs://nivosense-cogs/observations/
  - Samples N pixels randomly from valid (non-NaN) pixels
  - Extracts features from time T and target from time T+~7d

Output: ml/data/pairs_1week.parquet

Features per row (one pixel):
  ndsi_t        float32   NDSI at time T
  ndsi_t_prev   float32   NDSI at previous acquisition (captures trend)
  elevation     float32   metres
  slope         float32   degrees
  aspect        float32   degrees from North
  month         int8      1–12
  doy           int16     day of year (1–365)

Target:
  ndsi_target   float32   NDSI ~7 days later
"""
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from google.cloud import storage
import rasterio

GCS_OBS_BUCKET = "nivosense-cogs"
GCS_OBS_PREFIX = "observations/sierra-nevada"
OUTPUT_PATH      = Path(__file__).parent / "data" / "pairs_1week.parquet"
CHECKPOINT_DIR   = Path(__file__).parent / "data" / "checkpoints"

PAIR_GAP_MIN = 4   # days
PAIR_GAP_MAX = 12  # days
PIXELS_PER_PAIR = 10_000
RANDOM_SEED = 42

_OBS_RE = re.compile(r"ndsi_(\d{4})_(\w{3})_(\w+)\.tif$")
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_date(timestamp: str) -> datetime:
    return datetime.strptime(timestamp[:8], "%Y%m%d")


def _list_acquisitions(years: list[int] | None = None) -> list[dict]:
    """List all observation COGs sorted by date. Filter by years if provided."""
    client = storage.Client()
    acqs = []
    for blob in client.bucket(GCS_OBS_BUCKET).list_blobs(prefix=GCS_OBS_PREFIX):
        m = _OBS_RE.search(blob.name)
        if m:
            year = int(m.group(1))
            if years and year not in years:
                continue
            month_str = m.group(2)
            timestamp = m.group(3)
            date = _parse_date(timestamp)
            acqs.append({
                "uri": f"gs://{GCS_OBS_BUCKET}/{blob.name}",
                "date": date,
                "year": year,
                "month": _MONTH_MAP.get(month_str, 0),
                "doy": date.timetuple().tm_yday,
            })
    return sorted(acqs, key=lambda x: x["date"])


def _find_pairs(acqs: list[dict]) -> list[tuple[dict, dict, dict | None]]:
    """
    For each acquisition T, find the closest T+next within PAIR_GAP_MIN–MAX days.
    Also find T-prev (the acquisition just before T) for the trend feature.
    Returns list of (prev, current, next) tuples.
    """
    pairs = []
    for i, curr in enumerate(acqs):
        # find next acquisition within gap window
        nxt = None
        for j in range(i + 1, len(acqs)):
            gap = (acqs[j]["date"] - curr["date"]).days
            if gap > PAIR_GAP_MAX:
                break
            if gap >= PAIR_GAP_MIN:
                nxt = acqs[j]
                break
        if nxt is None:
            continue

        prev = acqs[i - 1] if i > 0 else None
        pairs.append((prev, curr, nxt))

    return pairs


def _download(uri: str, dest: Path) -> None:
    """Download a GCS URI to a local path using the GCS client."""
    bucket_name, blob_path = uri.replace("gs://", "").split("/", 1)
    storage.Client().bucket(bucket_name).blob(blob_path).download_to_filename(str(dest))


def _download_all(uris: list[str], cache_dir: Path, max_workers: int = 8) -> dict[str, Path]:
    """
    Download all unique URIs in parallel to cache_dir.
    Returns {uri: local_path} mapping.
    """
    uri_to_path = {uri: cache_dir / f"{abs(hash(uri))}.tif" for uri in uris}
    to_fetch = {uri: path for uri, path in uri_to_path.items() if not path.exists()}

    if not to_fetch:
        return uri_to_path

    print(f"  Downloading {len(to_fetch)} files in parallel (workers={max_workers})...")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_download, uri, path): uri for uri, path in to_fetch.items()}
        done = 0
        for future in as_completed(futures):
            future.result()
            done += 1
            print(f"  {done}/{len(to_fetch)} downloaded", end="\r")
    print()
    return uri_to_path


def _read_band(path: Path, band: int) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(band).astype(np.float32)


def _sample_pixels(
    path_curr: Path,
    path_next: Path,
    path_prev: Path | None,
    month: int,
    doy: int,
    n: int,
    rng: np.random.Generator,
) -> pd.DataFrame | None:
    """
    Read local COG files, find valid pixels in both, sample n of them.
    Returns DataFrame with feature columns or None if not enough valid pixels.
    """
    with rasterio.open(path_curr) as src:
        ndsi_t    = src.read(1).astype(np.float32)
        elevation = src.read(2).astype(np.float32)
        slope     = src.read(3).astype(np.float32)
        aspect    = src.read(4).astype(np.float32)

    ndsi_target = _read_band(path_next, 1)

    ndsi_t_prev = np.full_like(ndsi_t, np.nan)
    if path_prev:
        ndsi_t_prev = _read_band(path_prev, 1)

    valid = (
        ~np.isnan(ndsi_t) &
        ~np.isnan(ndsi_target) &
        ~np.isnan(elevation)
    )
    idx = np.argwhere(valid)
    if len(idx) < 100:
        return None

    chosen = rng.choice(len(idx), size=min(n, len(idx)), replace=False)
    rows, cols = idx[chosen, 0], idx[chosen, 1]

    return pd.DataFrame({
        "ndsi_t":      ndsi_t[rows, cols],
        "ndsi_t_prev": ndsi_t_prev[rows, cols],
        "elevation":   elevation[rows, cols],
        "slope":       slope[rows, cols],
        "aspect":      aspect[rows, cols],
        "month":       np.int8(month),
        "doy":         np.int16(doy),
        "ndsi_target": ndsi_target[rows, cols],
    })


def build_pairs(years: list[int] | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_SEED)

    print("Listing acquisitions from GCS...")
    acqs = _list_acquisitions(years=years)
    print(f"  Found {len(acqs)} acquisitions")

    pairs = _find_pairs(acqs)
    print(f"  Found {len(pairs)} valid pairs (gap {PAIR_GAP_MIN}–{PAIR_GAP_MAX} days)\n")

    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    done_keys = {p.stem for p in CHECKPOINT_DIR.glob("*.parquet")}
    pending_pairs = [
        (prev, curr, nxt) for prev, curr, nxt in pairs
        if f"{curr['date'].strftime('%Y%m%d')}_{nxt['date'].strftime('%Y%m%d')}" not in done_keys
    ]
    print(f"  {len(done_keys)} pairs already checkpointed, {len(pending_pairs)} remaining\n")

    # Download all unique files in parallel — each file downloaded once
    cache_dir = CHECKPOINT_DIR / "_file_cache"
    cache_dir.mkdir(exist_ok=True)
    all_uris = {acq["uri"] for trio in pending_pairs for acq in trio if acq is not None}
    uri_to_path = _download_all(list(all_uris), cache_dir)

    new_pairs = 0
    for i, (prev, curr, nxt) in enumerate(pending_pairs):
        gap = (nxt["date"] - curr["date"]).days
        key = f"{curr['date'].strftime('%Y%m%d')}_{nxt['date'].strftime('%Y%m%d')}"
        label = f"{curr['date'].date()} → {nxt['date'].date()} (+{gap}d)"
        print(f"  [{i+1:>4}/{len(pending_pairs)}] {label}", end="\r")

        df = _sample_pixels(
            path_curr=uri_to_path[curr["uri"]],
            path_next=uri_to_path[nxt["uri"]],
            path_prev=uri_to_path[prev["uri"]] if prev else None,
            month=curr["month"],
            doy=curr["doy"],
            n=PIXELS_PER_PAIR,
            rng=rng,
        )
        if df is not None:
            df["year"] = curr["year"]
            df["gap_days"] = gap
            df.to_parquet(CHECKPOINT_DIR / f"{key}.parquet", index=False)
            new_pairs += 1

    # Merge all checkpoints into final parquet
    all_chunks = list(CHECKPOINT_DIR.glob("*.parquet"))
    print(f"\n\nMerging {len(all_chunks)} checkpoints ({new_pairs} new)...")
    dataset = pd.concat([pd.read_parquet(p) for p in all_chunks], ignore_index=True)
    print(f"Total rows: {len(dataset):,}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_parquet(OUTPUT_PATH, index=False)
    print(f"Saved to {OUTPUT_PATH}")

    return dataset


if __name__ == "__main__":
    build_pairs()
