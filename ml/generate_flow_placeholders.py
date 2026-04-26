"""Generate realistic placeholder flow JSONs for the 4 supported rivers, so the
RiverFlowChart renders during the demo while real CSVs from SAIH/Hidrosur are
acquired manually.

Hydrological model (synthetic, calibrated against SAIH chart for Río Dilar
2025-26):

  * Per-river monthly baseline (Oct → Sep) reflecting nivo-pluvial regime:
    flat low summer (Jul-Sep), gradual autumn rise, snowmelt peak end of
    March / early April, decline through May-Jun.
  * Storm spikes (4-6 per winter, Oct 15 → Apr 30) — duration 2-4 days,
    peak 4-10x local baseline, exponential decay.
  * Small daily Gaussian noise around the baseline.

Run:
    python ml/generate_flow_placeholders.py

Outputs to `data/flow/<river>.json`. The generator is seeded per station_id
so values are deterministic across runs.
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "flow"
START = date(2024, 10, 1)
END = date(2025, 9, 30)

PLACEHOLDER_PREFIX = "PLACEHOLDER — replace with"

# Monthly baseline mean discharge (Oct, Nov, Dec, Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep) in m³/s.
PROFILES = [
    {
        "river_id": "dilar",
        "station_id": "5086",
        "station_name": "Dilar (A05)",
        "river_name": "Río Dilar",
        "source_label": "SAIH Guadalquivir",
        "license": "© Confederación Hidrográfica del Guadalquivir",
        "monthly": [0.55, 0.75, 0.95, 1.20, 1.45, 1.85, 1.95, 1.40, 0.85, 0.45, 0.30, 0.32],
        "noise": 0.05,
        "storms_per_year": 6,
        "storm_peak_min": 3.5,
        "storm_peak_max": 9.5,
        "min_floor": 0.10,
    },
    {
        "river_id": "alhori",
        "station_id": "5051",
        "station_name": "Jerez del Marquesado (A53)",
        "river_name": "Río Alhorí",
        "source_label": "SAIH Guadalquivir",
        "license": "© Confederación Hidrográfica del Guadalquivir",
        "monthly": [0.18, 0.25, 0.35, 0.48, 0.62, 0.85, 0.95, 0.65, 0.38, 0.18, 0.10, 0.11],
        "noise": 0.025,
        "storms_per_year": 5,
        "storm_peak_min": 1.2,
        "storm_peak_max": 4.5,
        "min_floor": 0.04,
    },
    {
        "river_id": "guadalfeo",
        "station_id": "73",
        "station_name": "Órgiva",
        "river_name": "Río Guadalfeo",
        "source_label": "Hidrosur",
        "license": "© Junta de Andalucía",
        "monthly": [3.20, 4.50, 6.20, 7.80, 9.20, 11.50, 12.40, 9.00, 5.40, 2.80, 1.90, 2.10],
        "noise": 0.45,
        "storms_per_year": 6,
        "storm_peak_min": 18.0,
        "storm_peak_max": 55.0,
        "min_floor": 1.20,
    },
    {
        "river_id": "andarax",
        "station_id": "90",
        "station_name": "Terque (Río Nacimiento)",
        "river_name": "Río Andarax",
        "source_label": "Hidrosur",
        "license": "© Junta de Andalucía",
        "monthly": [0.25, 0.45, 0.70, 0.95, 1.25, 1.65, 1.75, 1.10, 0.55, 0.18, 0.08, 0.10],
        "noise": 0.05,
        "storms_per_year": 5,
        "storm_peak_min": 2.5,
        "storm_peak_max": 8.0,
        "min_floor": 0.04,
    },
]

# Hydrological-year ordering (DOY 0 = Oct 1).
HYDRO_MONTH_ORDER = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]


def hydro_doy(d: date) -> int:
    delta = d - START
    return delta.days


def baseline_at(d: date, monthly: list[float]) -> float:
    """Linear interpolation between mid-month means (Oct→Sep)."""
    # Mid-day of each month within the hydro year.
    mid_points: list[tuple[int, float]] = []
    for idx, month in enumerate(HYDRO_MONTH_ORDER):
        year = START.year if month >= 10 else START.year + 1
        mid = date(year, month, 15)
        mid_points.append((hydro_doy(mid), monthly[idx]))

    doy = hydro_doy(d)
    if doy <= mid_points[0][0]:
        return monthly[0]
    if doy >= mid_points[-1][0]:
        return monthly[-1]
    for (a_doy, a_val), (b_doy, b_val) in zip(mid_points, mid_points[1:]):
        if a_doy <= doy <= b_doy:
            t = (doy - a_doy) / (b_doy - a_doy)
            return a_val + t * (b_val - a_val)
    return monthly[-1]


def synthesize(profile: dict) -> list[dict]:
    rng = random.Random(int(profile["station_id"]))
    total_days = (END - START).days + 1

    # 1. Baseline + small Gaussian noise.
    series: list[float] = []
    for i in range(total_days):
        d = START + timedelta(days=i)
        base = baseline_at(d, profile["monthly"])
        wiggle = rng.gauss(0, profile["noise"])
        series.append(max(profile["min_floor"], base + wiggle))

    # 2. Storm events between Oct 15 and Apr 30 (DOYs 14 to 211).
    storm_window_start, storm_window_end = 14, 211
    for _ in range(profile["storms_per_year"]):
        peak_day = rng.randint(storm_window_start, storm_window_end)
        peak_value = rng.uniform(profile["storm_peak_min"], profile["storm_peak_max"])
        rise_days = rng.randint(1, 2)
        decay_days = rng.randint(2, 4)
        # Apply rise then exponential-ish decay; keep the max with baseline.
        for offset in range(-rise_days, decay_days + 1):
            i = peak_day + offset
            if 0 <= i < total_days:
                if offset <= 0:
                    factor = 0.55 + 0.45 * (offset + rise_days) / max(rise_days, 1)
                else:
                    factor = math.exp(-offset / max(decay_days * 0.7, 1.0))
                bump = peak_value * factor
                if bump > series[i]:
                    series[i] = round(bump, 3)

    # 3. Build points.
    points = []
    for i, value in enumerate(series):
        d = START + timedelta(days=i)
        points.append(
            {
                "date": d.isoformat(),
                "label": d.strftime("%d %b"),
                "value": round(value, 3),
            }
        )
    return points


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for profile in PROFILES:
        points = synthesize(profile)
        payload = {
            "station_id": profile["station_id"],
            "station_name": profile["station_name"],
            "river_id": profile["river_id"],
            "river_name": profile["river_name"],
            "variable": "caudal",
            "unit": "m3/s",
            "source": f"{PLACEHOLDER_PREFIX} {profile['source_label']} export",
            "license": profile["license"],
            "first_date": points[0]["date"],
            "last_date": points[-1]["date"],
            "points": points,
        }
        out_path = OUT_DIR / f"{profile['river_id']}.json"
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        peak = max(p["value"] for p in points if p["value"] is not None)
        mean = sum(p["value"] for p in points if p["value"] is not None) / len(points)
        print(
            f"Wrote {len(points)} placeholder points to {out_path} "
            f"(peak={peak:.2f} m³/s, mean={mean:.2f})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
