"""Which day boundary do RIA daily totals use? Daily r against two forcings for several UTC day starts.

Run from the repo root: python <path>/ria_day_boundary.py
"""
from datetime import date
from pathlib import Path

from pipelines.forcing_study import openmeteo, stations, study
from pipelines.region import load_region

cache = Path(".cache/forcing")
start, end = date(2023, 10, 1), date(2026, 9, 30)
bbox = load_region(Path("regions/sierra-nevada.json")).bbox
print("| station | forcing | " + " | ".join(f"start {h:+d} h UTC" for h in (-2, -1, 0, 1, 6, 7)) + " |")
print("|---|---|" + "---|" * 6)
for station in [s for s in stations.ria_stations(cache) if stations.near(s, bbox, study.STATION_MARGIN_DEG)]:
    observed = stations.ria_daily(station, start, end, cache)
    for model in ("ecmwf_ifs", "icon_eu"):
        times, values = openmeteo.hourly_precipitation(model, station.lat, station.lon, start, end, cache)
        rs = [study.precipitation_metrics(study.daily_totals(times, values, h), observed)["daily_r"] for h in (-2, -1, 0, 1, 6, 7)]
        print(f"| {station.name} | {model} | " + " | ".join(f"{r:.3f}" for r in rs) + " |")
