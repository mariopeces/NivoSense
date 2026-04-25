"""
Batch extraction of 5-band COGs for all snow-season S2 acquisitions.

Uses one process per acquisition with a hard timeout — if a worker hangs
it is killed and the acquisition is marked FAIL (safe to retry on next run).
"""
import multiprocessing
import re
import time
from pathlib import Path

from google.cloud import storage

from .pipeline import prepare_acquisition

_SRC_BUCKET  = "darwin-general-hdh-sandbox-tiles"
_SRC_PREFIX  = "tiles/guest/raster/temporal/s2_raw_images"
_OUT_BUCKET  = "nivosense-cogs"
_OUT_PREFIX  = "observations/sierra-nevada"

_FNAME_RE = re.compile(
    r"s2_raw_images_b03_(\d{4})_(\w{3})_sierra_nevada_(\w+)\.tif$"
)

# Snow season only — Jun/Jul/Aug have no meaningful snow signal
SNOW_MONTHS = {"jan", "feb", "mar", "apr", "may", "oct", "nov", "dec"}

# Kill worker if it takes longer than this
_TIMEOUT_SEC = 300


def list_acquisitions() -> list[dict]:
    """Return list of {year, month, timestamp} dicts for snow-season months."""
    client = storage.Client()
    acquisitions = []
    for blob in client.bucket(_SRC_BUCKET).list_blobs(prefix=_SRC_PREFIX):
        m = _FNAME_RE.search(blob.name)
        if m and m.group(2) in SNOW_MONTHS:
            acquisitions.append({
                "year": int(m.group(1)),
                "month": m.group(2),
                "timestamp": m.group(3),
            })
    return acquisitions


def _already_done(year: int, month: str, timestamp: str) -> bool:
    blob_path = f"{_OUT_PREFIX}/{year}/{month}/ndsi_{year}_{month}_{timestamp}.tif"
    return storage.Client().bucket(_OUT_BUCKET).blob(blob_path).exists()


def _worker(acq: dict, dem_path: str, result_queue: multiprocessing.Queue) -> None:
    """Runs in a child process. Puts (label, error|None) into the queue."""
    label = f"{acq['year']}_{acq['month']}_{acq['timestamp']}"
    try:
        prepare_acquisition(
            year=acq["year"],
            month=acq["month"],
            timestamp=acq["timestamp"],
            dem_path=dem_path,
        )
        result_queue.put((label, None))
    except Exception as e:
        result_queue.put((label, str(e)))


def run_batch(dem_path: str, max_workers: int = 4) -> None:
    """
    Extract all snow-season S2 acquisitions and upload COGs to GCS.

    Parameters
    ----------
    dem_path    : local path to the CNIG MDT05 GeoTIFF
    max_workers : number of parallel acquisition processes (default 4)
    """
    print("Discovering acquisitions...")
    acquisitions = list_acquisitions()
    total = len(acquisitions)
    print(f"Found {total} acquisitions\n")

    done = skipped = failed = 0
    pending = list(acquisitions)
    active: list[tuple[multiprocessing.Process, multiprocessing.Queue, dict, float]] = []

    def _reap(proc, queue, acq, start):
        nonlocal done, skipped, failed
        label = f"{acq['year']}_{acq['month']}_{acq['timestamp']}"
        elapsed = time.time() - start

        if not queue.empty():
            _, error = queue.get_nowait()
            status = f"FAIL — {error}" if error else "OK"
            if error:
                failed += 1
        elif elapsed >= _TIMEOUT_SEC:
            proc.kill()
            proc.join()
            status = f"FAIL — timeout ({_TIMEOUT_SEC}s)"
            failed += 1
        else:
            return False  # still running

        done += 1
        print(f"[{done:>3}/{total}] {label}  {status}")
        return True

    while pending or active:
        # Fill up to max_workers
        while pending and len(active) < max_workers:
            acq = pending.pop(0)
            label = f"{acq['year']}_{acq['month']}_{acq['timestamp']}"

            if _already_done(acq["year"], acq["month"], acq["timestamp"]):
                done += 1
                skipped += 1
                print(f"[{done:>3}/{total}] {label}  SKIP")
                continue

            q: multiprocessing.Queue = multiprocessing.Queue()
            p = multiprocessing.Process(target=_worker, args=(acq, dem_path, q))
            p.start()
            active.append((p, q, acq, time.time()))

        # Check active workers
        still_active = []
        for proc, queue, acq, start in active:
            proc.join(timeout=0.1)
            if not _reap(proc, queue, acq, start):
                still_active.append((proc, queue, acq, start))
        active = still_active

        time.sleep(0.5)

    print(f"\nDone.  OK: {done - skipped - failed}  Skipped: {skipped}  Failed: {failed}")
