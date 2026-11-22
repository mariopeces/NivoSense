"""MODIS fractional snow cover at a point from the Planetary Computer (collection `modis-10A1-061`).

MOD10A1 (Terra) and MYD10A1 (Aqua) v061, daily, 500 m, sinusoidal tiles. The STAC API and the SAS token of the
public `modiseuwest` account need no key. This is how the 2009 to 2013 camera series gets a satellite snow
signal when Sentinel-2 L2A does not exist yet: it can test the method (fSCA assimilation, melt-out timing) in
those four seasons, never today's product.

Limits to state wherever the numbers are used: a 500 m pixel against a 30 x 30 m camera plot; clouds hide many
days (`qc` marks them); fSCA is a linear conversion of NDSI, not a measurement.

fSCA = -0.01 + 1.45 * NDSI clipped to 0..1 (Salomonson and Appel 2004, Remote Sensing of Environment 89:351,
fitted on Terra over a wide range of conditions). NDSI_Snow_Cover codes above 100 are not snow cover values:
200 missing, 201 no decision, 211 night, 237 inland water, 239 ocean, 250 cloud, 253 not selected, 254 saturated
detector, 255 fill (MOD10A1 v061 user guide). Water, ocean and night cannot happen over the Poqueira cell by day
and are treated as `no_data` together with the other non-cloud codes.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/modiseuwest/modis-061-cogs"
COLLECTION = "modis-10A1-061"
CLOUD_CODE = 250
MAX_NDSI = 100
COLUMNS = ["date", "platform", "ndsi", "fsca", "qc", "lat", "lon"]
# Items are cut into windows of this many days so a search page never exceeds the API limit.
WINDOW_DAYS = 90


def ndsi_to_fsca(ndsi: np.ndarray) -> np.ndarray:
    return np.clip(-0.01 + 1.45 * np.asarray(ndsi, dtype="float64") / 100.0, 0.0, 1.0)


def classify(code: int) -> str:
    if code <= MAX_NDSI:
        return "ok"
    return "cloud" if code == CLOUD_CODE else "no_data"


def _post(url: str, body: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "nivosense-validation"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def search_items(lat: float, lon: float, start: date, end: date) -> list[dict]:
    """STAC items covering the point, Terra and Aqua, from `start` to `end` inclusive."""
    items: list[dict] = []
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=WINDOW_DAYS - 1), end)
        body = {
            "collections": [COLLECTION],
            "intersects": {"type": "Point", "coordinates": [lon, lat]},
            "datetime": f"{cursor.isoformat()}T00:00:00Z/{stop.isoformat()}T23:59:59Z",
            "limit": 500,
        }
        page = _post(STAC_URL, body)
        items += page["features"]
        cursor = stop + timedelta(days=1)
    return items


class SasToken:
    """The keyless token of the MODIS COG container, refreshed shortly before it expires."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token = ""
        self._expiry = 0.0

    def get(self) -> str:
        with self._lock:
            if time.time() > self._expiry - 300:
                request = urllib.request.Request(TOKEN_URL, headers={"User-Agent": "nivosense-validation"})
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.load(response)
                self._token = payload["token"]
                self._expiry = datetime.fromisoformat(payload["msft:expiry"].replace("Z", "+00:00")).timestamp()
            return self._token


def _read_pixel(href: str, token: str, lat: float, lon: float) -> int:
    import rasterio
    from rasterio.warp import transform

    url = f"{href}?{token}"
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="1"):
        with rasterio.open(url) as source:
            x, y = transform("EPSG:4326", source.crs, [lon], [lat])
            row, col = source.index(x[0], y[0])
            return int(source.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])


def load_fsca(lat: float, lon: float, start: date, end: date, workers: int = 8) -> pd.DataFrame:
    """Tidy daily fSCA of the 500 m pixel containing a point, one row per overpass product (Terra, Aqua).

    Columns: date, platform, ndsi (0 to 100, NaN unless `qc` is ok), fsca (0 to 1, same), qc (`ok`, `cloud`,
    `no_data`), lat, lon. A day without an item at all (the product has gaps) has no row.
    """
    items = search_items(lat, lon, start, end)
    token = SasToken()

    def one(item: dict) -> dict[str, object]:
        code = _read_pixel(item["assets"]["NDSI_Snow_Cover"]["href"], token.get(), lat, lon)
        qc = classify(code)
        day = pd.Timestamp(item["properties"]["start_datetime"]).tz_localize(None).normalize()
        ndsi = float(code) if qc == "ok" else np.nan
        return {
            "date": day,
            "platform": item["properties"]["platform"],
            "ndsi": ndsi,
            "fsca": float(ndsi_to_fsca(np.array(ndsi))) if qc == "ok" else np.nan,
            "qc": qc,
            "lat": lat,
            "lon": lon,
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, items))
    return pd.DataFrame(rows, columns=COLUMNS).sort_values(["date", "platform"], ignore_index=True)


def combine_daily(frame: pd.DataFrame) -> pd.DataFrame:
    """One value per day: the mean of the clear Terra and Aqua values, else cloud if any pass saw cloud,
    else no_data. Output columns: date, fsca, qc, n_clear."""
    rows = []
    for day, part in frame.groupby("date"):
        clear = part[part["qc"] == "ok"]
        if len(clear):
            rows.append({"date": day, "fsca": float(clear["fsca"].mean()), "qc": "ok", "n_clear": len(clear)})
        else:
            qc = "cloud" if (part["qc"] == "cloud").any() else "no_data"
            rows.append({"date": day, "fsca": np.nan, "qc": qc, "n_clear": 0})
    return pd.DataFrame(rows, columns=["date", "fsca", "qc", "n_clear"])


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Daily MODIS fSCA at a point; the default is the Poqueira camera.")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2009, 11, 15))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2013, 5, 31))
    parser.add_argument("--lat", type=float, default=37.02825)
    parser.add_argument("--lon", type=float, default=-3.32337)
    parser.add_argument("--out", type=Path, default=Path("qa-cache/modis_fsca.csv"))
    args = parser.parse_args(argv)
    frame = load_fsca(args.lat, args.lon, args.start, args.end)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out, index=False)
    daily = combine_daily(frame)
    print(f"{len(frame)} rows, {len(daily)} days, clear days {int((daily['qc'] == 'ok').sum())}; written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
