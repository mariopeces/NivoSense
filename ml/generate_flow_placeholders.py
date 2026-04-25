"""Generate placeholder flow JSONs for the 4 supported rivers, so the
RiverFlowChart renders in the demo while real CSVs from SAIH/Hidrosur are
being acquired manually.

The values are SYNTHETIC: they reflect documented mean annual discharge and
nivo-pluvial seasonality (snowmelt peak in March-May, dry summer) but should
never be cited as real measurements. The `source` field of every output is
set to `PLACEHOLDER — replace with SAIH/Hidrosur export` so consumers know.

Run:
    python ml/generate_flow_placeholders.py

Outputs to `data/flow/<river>.json`. Upload to the bucket separately.
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

# Profile per river: (mean m³/s, amplitude m³/s, peak DOY relative to hydro year start, noise_factor)
# Hydro year DOY 0 = Oct 1; DOY ~180 = late March (peak snowmelt); DOY ~210 = late April.
RIVERS = [
    {
        "river_id": "dilar",
        "station_id": "5086",
        "station_name": "Dilar (A05)",
        "river_name": "Río Dilar",
        "source_label": "SAIH Guadalquivir",
        "license": "© Confederación Hidrográfica del Guadalquivir",
        "baseline": 0.20,
        "amplitude": 0.45,
        "peak_doy": 200,
        "noise": 0.08,
        "min_floor": 0.05,
    },
    {
        "river_id": "alhori",
        "station_id": "5051",
        "station_name": "Jerez del Marquesado (A53)",
        "river_name": "Río Alhorí",
        "source_label": "SAIH Guadalquivir",
        "license": "© Confederación Hidrográfica del Guadalquivir",
        "baseline": 0.10,
        "amplitude": 0.25,
        "peak_doy": 195,
        "noise": 0.05,
        "min_floor": 0.02,
    },
    {
        "river_id": "guadalfeo",
        "station_id": "73",
        "station_name": "Órgiva",
        "river_name": "Río Guadalfeo",
        "source_label": "Hidrosur",
        "license": "© Junta de Andalucía",
        "baseline": 4.50,
        "amplitude": 7.50,
        "peak_doy": 205,
        "noise": 1.20,
        "min_floor": 1.50,
    },
    {
        "river_id": "andarax",
        "station_id": "90",
        "station_name": "Terque (Río Nacimiento)",
        "river_name": "Río Andarax",
        "source_label": "Hidrosur",
        "license": "© Junta de Andalucía",
        "baseline": 0.30,
        "amplitude": 1.30,
        "peak_doy": 210,
        "noise": 0.18,
        "min_floor": 0.05,
    },
]

PLACEHOLDER_PREFIX = "PLACEHOLDER — replace with"


def synthesize(profile: dict) -> list[dict]:
    rng = random.Random(int(profile["station_id"]))
    points: list[dict] = []
    total_days = (END - START).days + 1
    for i in range(total_days):
        d = START + timedelta(days=i)
        phase = 2 * math.pi * (i - profile["peak_doy"]) / 365.0
        base = profile["baseline"] + profile["amplitude"] * (
            0.5 * (1.0 + math.cos(phase))
        )
        wiggle = rng.gauss(0, profile["noise"])
        value = max(profile["min_floor"], base + wiggle)
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
    for profile in RIVERS:
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
        print(f"Wrote {len(points)} placeholder points to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
