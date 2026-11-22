"""Open-Meteo forcing candidates, fetched politely and cached response by response.

Open-Meteo data are CC BY 4.0; the free API is for non-commercial use and limits clients to
600 calls a minute, 5,000 an hour and 10,000 a day, where one call is one location with up
to 10 variables and 2 weeks of data (https://open-meteo.com/en/terms, /en/pricing). A study
over three seasons costs tens of thousands of such calls, so every response is cached on
disk and a ledger of spent calls keeps the client under the limits across restarts.
"""

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np

from ..snow_model.forcing import VARIABLES, Forcing, forcing_from_records, request_points

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

# Candidates approved for the study, with the endpoint that holds each archive.
CANDIDATES = {
    "ecmwf_ifs": ARCHIVE_URL,
    "icon_eu": HISTORICAL_FORECAST_URL,
    "gfs_global": HISTORICAL_FORECAST_URL,
    "meteofrance_arpege_europe": HISTORICAL_FORECAST_URL,
    "era5_seamless": ARCHIVE_URL,
}

# Kept below the published limits so another client on the same address does not tip us over.
LIMITS = ((60, 500), (3600, 4500), (86400, 9000))
POINTS_PER_REQUEST = 10


def call_weight(locations: int, days: int, variables: int) -> float:
    """Calls Open-Meteo counts for one request (its fractional call rule)."""
    return locations * max(1.0, days / 14) * max(1.0, variables / 10)


@dataclass
class Ledger:
    """Calls spent, persisted so restarts and parallel runs respect the same limits."""

    path: Path

    def _entries(self) -> list[tuple[float, float]]:
        if not self.path.exists():
            return []
        now = time.time()
        rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]
        return [(stamp, weight) for stamp, weight in rows if now - stamp < 86400]

    def wait_for(self, weight: float) -> None:
        while True:
            entries = self._entries()
            now = time.time()
            delays = []
            for window, limit in LIMITS:
                inside = [(stamp, spent) for stamp, spent in entries if now - stamp < window]
                total = sum(spent for _, spent in inside)
                if total + weight > limit:
                    # Wait until enough of the oldest calls leave this window.
                    excess = total + weight - limit
                    for stamp, spent in sorted(inside):
                        excess -= spent
                        if excess <= 0:
                            delays.append(stamp + window - now + 1)
                            break
            if not delays:
                return
            time.sleep(min(max(delays), 900))

    def spend(self, weight: float) -> None:
        # Append-only, so concurrent study processes on one cache do not drop each other's calls.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps([time.time(), weight]) + "\n")


def cached_get(url: str, weight: float, cache: Path, ledger: Ledger, attempts: int = 6) -> list[dict]:
    """GET a JSON response once; later calls read it from the cache."""
    path = cache / "openmeteo" / f"{hashlib.sha256(url.encode()).hexdigest()[:24]}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    for attempt in range(1, attempts + 1):
        ledger.wait_for(weight)
        ledger.spend(weight)
        try:
            with urllib.request.urlopen(url, timeout=300) as response:
                payload = json.load(response)
            break
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == attempts:
                raise
            # A 429 after our own pacing means another client spent the shared budget: back off long.
            time.sleep(900 if error.code == 429 else 60 * attempt)
    records = payload if isinstance(payload, list) else [payload]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records), encoding="utf-8")
    return records


def fetch_records(
    model: str,
    points: list[tuple[float, float]],
    start: date,
    end: date,
    cache: Path,
    variables: tuple[str, ...] = VARIABLES,
) -> list[dict]:
    url = CANDIDATES[model]
    ledger = Ledger(cache / "openmeteo-ledger.jsonl")
    days = (end - start).days + 1
    records: list[dict] = []
    for offset in range(0, len(points), POINTS_PER_REQUEST):
        chunk = points[offset : offset + POINTS_PER_REQUEST]
        query = urllib.parse.urlencode(
            {
                "latitude": ",".join(str(lat) for lat, _ in chunk),
                "longitude": ",".join(str(lon) for _, lon in chunk),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "hourly": ",".join(variables),
                "models": model,
                "timezone": "UTC",
            }
        )
        weight = call_weight(len(chunk), days, len(variables))
        records.extend(cached_get(f"{url}?{query}", weight, cache, ledger))
    return records


def missing_fraction(records: list[dict], start: date, end: date) -> dict[str, float]:
    """Share of hours with no value, per variable, before any gap filling."""
    hours = ((end - start).days + 1) * 24
    result = {}
    for name in VARIABLES:
        present = sum(sum(value is not None for value in record["hourly"][name]) for record in records)
        result[name] = round(1 - present / (hours * len(records)), 6)
    return result


def fetch_forcing(
    model: str, bbox: tuple[float, float, float, float], spacing: float, start: date, end: date, cache: Path
) -> tuple[Forcing, dict[str, float]]:
    """Forcing for the model grid points plus the raw missing fraction per variable.

    Gaps are filled by the snow model's own rule, which refuses more than 2% missing.
    """
    records = fetch_records(model, request_points(bbox, spacing), start, end, cache)
    return forcing_from_records(records, start, end), missing_fraction(records, start, end)


def hourly_precipitation(
    model: str, lat: float, lon: float, start: date, end: date, cache: Path
) -> tuple[list[datetime], np.ndarray]:
    """Hourly precipitation (mm, UTC hours) at one point; missing hours are NaN."""
    records = fetch_records(model, [(lat, lon)], start, end, cache, ("precipitation",))
    hourly = records[0]["hourly"]
    times = [datetime.fromisoformat(stamp) for stamp in hourly["time"]]
    values = np.array([np.nan if value is None else value for value in hourly["precipitation"]], dtype="float64")
    return times, values
