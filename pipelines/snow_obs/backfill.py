"""Backfill of the observed snow cover layer for past dates, resumable and idempotent.

    python -m pipelines.snow_obs.backfill --domain data/domain.geojson --start 2024-10-01 --end 2025-06-30 \
        --work work --target prod [--static-cache work/static] [--republish]

The range is cut into windows of WINDOW_DAYS days that do not straddle a change of Earth Search collection
(pipelines.s2.stac.collection_for). For each window the dates that already have a catalogue entry are left
out, the rest are ingested (pipelines.s2.ingest) and classified and published (pipelines.snow_obs.run), and
the scratch files are deleted, so a crashed or cancelled run loses at most one window and a rerun picks up
where it stopped. A window that fails is retried, then reported at the end with a non-zero exit code.
Only the observed snow cover layer is written here; the catalogue index is rebuilt by the workflow.
It writes <work>/backfill-summary.json: per date whether a pass was found, whether it was complete, its
observed fraction and whether the date is in the catalogue.
"""

import argparse
import json
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from pipelines.s2 import ingest
from pipelines.s2.stac import collection_for

from . import run as snow_obs
from .run import LAYER

WINDOW_DAYS = 7
ATTEMPTS = 3
RETRY_PAUSE_SECONDS = 60


@dataclass(frozen=True)
class Window:
    start: date
    end: date
    collection: str


def windows(start: date, end: date, days: int = WINDOW_DAYS) -> list[Window]:
    result = []
    day = start
    while day <= end:
        collection = collection_for(day)
        last = day
        while (
            last < end
            and last - day < timedelta(days=days - 1)
            and collection_for(last + timedelta(days=1)) == collection
        ):
            last += timedelta(days=1)
        result.append(Window(day, last, collection))
        day = last + timedelta(days=1)
    return result


def published_dates(storage: object) -> set[date]:
    prefix = f"catalog/entries/{LAYER}/"
    keys = storage.list(prefix)  # type: ignore[attr-defined]
    return {date.fromisoformat(key[len(prefix) : -len(".json")]) for key in keys if key.endswith(".json")}


def pending_range(window: Window, done: set[date]) -> tuple[date, date] | None:
    days = [window.start + timedelta(days=i) for i in range((window.end - window.start).days + 1)]
    todo = [day for day in days if day not in done]
    return (todo[0], todo[-1]) if todo else None


def run_window(
    domain: Path, window: Window, first: date, last: date, work: Path, static_cache: Path | None, target: str
) -> dict[str, dict]:
    s2_out, obs_out = work / "s2", work / "snow_obs"
    for folder in (s2_out, obs_out):
        shutil.rmtree(folder, ignore_errors=True)
    records = ingest.run(domain, first, last, s2_out, collection=window.collection, reprocess=False)
    rows: dict[str, dict] = {}
    for record in records:
        row = rows.setdefault(
            record["date"], {"found": True, "complete": False, "observed_fraction": None, "in_catalogue": False}
        )
        row["complete"] = row["complete"] or record["complete"]
    for summary in snow_obs.run(domain, s2_out, first, last, obs_out, static_cache, target):
        rows[summary["date"]].update(observed_fraction=summary["observed_fraction"], in_catalogue=summary["published"])
    shutil.rmtree(s2_out, ignore_errors=True)
    shutil.rmtree(obs_out, ignore_errors=True)
    return rows


def run(
    domain: Path,
    start: date,
    end: date,
    work: Path,
    target: str,
    static_cache: Path | None = None,
    republish: bool = False,
) -> tuple[dict[str, dict], list[str]]:
    from pipelines.catalog import storage_from_env

    storage = storage_from_env(target)
    done = set() if republish else published_dates(storage)
    rows: dict[str, dict] = {
        day.isoformat(): {"found": True, "complete": True, "observed_fraction": None, "in_catalogue": True}
        for day in sorted(done)
        if start <= day <= end
    }
    failed: list[str] = []
    for window in windows(start, end):
        span = pending_range(window, done)
        if span is None:
            print(f"{window.start} to {window.end}: all published", flush=True)
            continue
        for attempt in range(1, ATTEMPTS + 1):
            try:
                rows.update(run_window(domain, window, span[0], span[1], work, static_cache, target))
                break
            except Exception as error:  # a flaky tile read or STAC page must not end the month
                print(
                    f"{span[0]} to {span[1]} attempt {attempt}/{ATTEMPTS}: {type(error).__name__}: {error}", flush=True
                )
                if attempt == ATTEMPTS:
                    failed.append(f"{span[0]}..{span[1]}")
                else:
                    time.sleep(RETRY_PAUSE_SECONDS * attempt)
        published = sum(1 for row in rows.values() if row["in_catalogue"])
        print(
            f"{window.start} to {window.end} ({window.collection}): {published} dates in the catalogue so far",
            flush=True,
        )
    return rows, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--domain", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--target", choices=("staging", "prod"), required=True)
    parser.add_argument("--static-cache", type=Path)
    parser.add_argument("--republish", action="store_true", help="redo dates that already have an entry")
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error("--end is before --start")
    rows, failed = run(args.domain, args.start, args.end, args.work, args.target, args.static_cache, args.republish)
    args.work.mkdir(parents=True, exist_ok=True)
    (args.work / "backfill-summary.json").write_text(
        json.dumps({"dates": rows, "failed": failed}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    in_catalogue = sum(row["in_catalogue"] for row in rows.values())
    print(
        f"BACKFILL {args.start}..{args.end}: {len(rows)} dates seen, {in_catalogue} in the catalogue, failed: {failed}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
