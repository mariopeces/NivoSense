"""
Batch extraction of 5-band feature TIFs for all S2 acquisitions.

Discovers acquisitions by listing b03 files in GCS, then runs
prepare_acquisition for each one. Already-processed files are skipped.
Failed acquisitions are logged and skipped without stopping the batch.
"""
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed, TimeoutError
from pathlib import Path

from google.cloud import storage

from .pipeline import prepare_acquisition

_GCS_BUCKET = "darwin-general-hdh-sandbox-tiles"
_GCS_PREFIX = "tiles/guest/raster/temporal/s2_raw_images"
_FNAME_RE = re.compile(
    r"s2_raw_images_b03_(\d{4})_(\w{3})_sierra_nevada_(\w+)\.tif$"
)

# Snow season only — June, July, August have no meaningful snow signal
SNOW_MONTHS = {"jan", "feb", "mar", "apr", "may", "oct", "nov", "dec"}


def list_acquisitions() -> list[dict]:
    """Return list of {year, month, timestamp} dicts from GCS."""
    client = storage.Client()
    bucket = client.bucket(_GCS_BUCKET)
    acquisitions = []
    for blob in bucket.list_blobs(prefix=_GCS_PREFIX, match_glob="**/s2_raw_images_b03_*.tif"):
        m = _FNAME_RE.search(blob.name)
        if m and m.group(2) in SNOW_MONTHS:
            acquisitions.append({
                "year": int(m.group(1)),
                "month": m.group(2),
                "timestamp": m.group(3),
            })
    return acquisitions


def _process_one(acq: dict, dem_path: str, output_dir: str, retries: int = 3) -> tuple[str, str | None]:
    """Process one acquisition with retries. Returns (label, error_message | None)."""
    label = f"{acq['year']}_{acq['month']}_{acq['timestamp']}"
    out_path = Path(output_dir) / f"ndsi_{label}.tif"

    if out_path.exists():
        return label, "skipped"

    last_error = None
    for attempt in range(retries):
        try:
            prepare_acquisition(
                year=acq["year"],
                month=acq["month"],
                timestamp=acq["timestamp"],
                dem_path=dem_path,
                output_dir=output_dir,
            )
            return label, None
        except Exception as e:
            last_error = str(e)
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))  # back off: 5s, 10s

    return label, last_error


def run_batch(
    dem_path: str,
    output_dir: str,
    max_workers: int = 6,
) -> None:
    """
    Extract all S2 acquisitions to output_dir.

    Parameters
    ----------
    dem_path    : path or gs:// URI to the CNIG MDT05 GeoTIFF
    output_dir  : directory where feature TIFs are written
    max_workers : parallel threads (GCS I/O bound, 4-8 is optimal)
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print("Discovering acquisitions from GCS...")
    acquisitions = list_acquisitions()
    total = len(acquisitions)
    print(f"Found {total} acquisitions\n")

    done, skipped, failed = 0, 0, 0

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_one, acq, dem_path, output_dir): acq
            for acq in acquisitions
        }
        for future in as_completed(futures):
            done += 1
            try:
                label, error = future.result(timeout=300)  # 5 min per acquisition
            except TimeoutError:
                acq = futures[future]
                label = f"{acq['year']}_{acq['month']}_{acq['timestamp']}"
                error = "timeout"

            if error == "skipped":
                skipped += 1
                status = "SKIP"
            elif error:
                failed += 1
                status = f"FAIL — {error}"
            else:
                status = "OK"

            print(f"[{done:>3}/{total}] {label}  {status}")

    print(f"\nDone. OK: {done - skipped - failed}  Skipped: {skipped}  Failed: {failed}")
