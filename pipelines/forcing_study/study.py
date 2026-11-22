"""Forcing study: which meteorological archive drives the snow model best over the massif.

    python -m pipelines.forcing_study.study inventory --end 2026-11-21 --cache ... --output ...
    python -m pipelines.forcing_study.study fetch --years 2023 2024 2025 --cache ... --output ...
    python -m pipelines.forcing_study.study snow --years 2026 --reference interim --dates ... --cache ... --output ...
    python -m pipelines.forcing_study.study precip --years 2023 2024 2025 --cache ... --output ...

`snow` runs the current snow model (pipelines/snow_model) with each forcing, the same Latin
hypercube ensemble for every forcing, weights the members on two of every three clear
Sentinel-2 dates exactly as the model's calibration does, and scores snow presence on the
held-out third by elevation band. `precip` compares each forcing's daily precipitation with
open station records. Every number in docs/method/forcing.md comes from these commands.
"""

import argparse
import json
import sys
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ..region import load_region
from ..snow_model import observations as obs
from ..snow_model.ensemble import sample_members, tempered_weights
from ..snow_model.forcing import Forcing, neighbour_weights
from ..snow_model.run import Static, merged_settings, observation_arrays
from ..snow_model.snowpack import Domain, build_tables, simulate
from ..snow_model.validation import misclassification, split_fit_test
from . import era5_land, openmeteo, stations

ERA5_LAND = "era5_land"
FORCINGS = (*openmeteo.CANDIDATES, ERA5_LAND)
# Band edges in metres: the snowline in this massif moves between about 1,500 and 3,000 m.
ELEVATION_BANDS = (0, 1500, 2000, 2500, 3000, 4000)
# A date belongs to the snow season when S2 sees snow on at least 1% of the usable cells,
# the same rule the model's calibration gate uses to count "dates with snow".
SNOW_DATE_FRACTION = 0.01
WET_DAY_MM = 1.0
# About 10 km around the domain box: the foothill stations, not the coast or the Granada plain.
STATION_MARGIN_DEG = 0.1
INVENTORY_POINT = (37.06, -3.38)
INVENTORY_MODELS = {
    openmeteo.ARCHIVE_URL: (
        "ecmwf_ifs",
        "era5",
        "era5_land",
        "era5_seamless",
        "cerra",
        "ecmwf_ifs_analysis_long_window",
    ),
    openmeteo.HISTORICAL_FORECAST_URL: (
        "ecmwf_ifs025",
        "icon_eu",
        "icon_global",
        "gfs_global",
        "meteofrance_arpege_europe",
        "meteofrance_arome_france",
        "meteofrance_arome_france_hd",
        "knmi_harmonie_arome_europe",
        "dmi_harmonie_arome_europe",
        "ukmo_global_deterministic_10km",
        "gem_global",
    ),
}


def log(message: str) -> None:
    print(message, flush=True)


def season_bounds(year: int, today: date) -> tuple[date, date]:
    """Hydrological year starting 1 October of `year`, cut at yesterday."""
    return date(year, 10, 1), min(date(year + 1, 9, 30), today - timedelta(days=1))


def load_forcing(
    name: str, bbox: tuple[float, float, float, float], spacing: float, start: date, end: date, cache: Path
) -> tuple[Forcing, dict[str, float] | None]:
    if name == ERA5_LAND:
        return era5_land.fetch_forcing(bbox, start, end, cache), None
    return openmeteo.fetch_forcing(name, bbox, spacing, start, end, cache)


@dataclass
class Reference:
    """Observed snow and usable cells on the model grid for one clear date."""

    day: date
    observed: np.ndarray
    usable: np.ndarray


def interim_reference(static: Static, days: list[date], cache: Path) -> list[Reference]:
    """Snow masks from the snow model's own Sentinel-2 reader, for testing the pipeline only.

    The study's reference is the past-season observed snow cover cache; these masks are the
    hackathon NDSI rule and must not be reported as the study result.
    """
    minimum = static.settings["observation"]["min_usable_fraction"]
    references = []
    for day in days:
        scenes = obs.search_scenes(static.region.bbox, day, day, 100)
        if not scenes:
            log(f"{day}: no Sentinel-2 scene found")
            continue
        observed, usable, _, _ = observation_arrays(static, scenes[0], cache)
        if usable.mean() < minimum:
            log(f"{day}: only {usable.mean():.0%} of the cells usable, skipped")
            continue
        references.append(Reference(day, observed, usable))
    return references


def exclusion_mask(static: Static, geojson: Path | None) -> np.ndarray:
    """Model cells inside the polygons to leave out of every score (the ski resort)."""
    if geojson is None:
        return np.zeros(static.cell_index.size, dtype=bool)
    import rasterio.features
    from rasterio.warp import transform_geom

    payload = json.loads(geojson.read_text(encoding="utf-8"))
    shapes = [(transform_geom("EPSG:4326", static.grid.crs, feature["geometry"]), 1) for feature in payload["features"]]
    raster = rasterio.features.rasterize(
        shapes,
        out_shape=(static.grid.height, static.grid.width),
        transform=static.grid.transform,
        fill=0,
        dtype="uint8",
    )
    return raster.ravel()[static.cell_index].astype(bool)


def simulate_forcing(static: Static, forcing: Forcing, members: list[dict], days: list[date]) -> list[list[np.ndarray]]:
    """Snow masks per reference day and member (packed bits), from one season's forcing."""
    tables = build_tables(forcing)
    neighbours, weights = neighbour_weights(forcing, static.cell_x, static.cell_y, static.grid.crs)
    domain = Domain(
        static.elevation,
        neighbours,
        weights,
        static.basin,
        len(static.basin_ids),
        static.grid.cell_area_m2,
        static.radiation,
    )
    indexes = [(day - forcing.days[0]).days for day in days]
    results = [simulate(domain, tables, parameters, set(indexes), False) for parameters in members]
    return [[result.snow_masks[index] for result in results] for index in indexes]


def confusion(predicted: np.ndarray, observed: np.ndarray) -> dict:
    tp = int(np.sum(predicted & observed))
    fp = int(np.sum(predicted & ~observed))
    fn = int(np.sum(~predicted & observed))
    tn = int(np.sum(~predicted & ~observed))
    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "accuracy": round((tp + tn) / total, 4) if total else None,
        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        # README Q3: modelled snow where S2 sees bare ground, as a share of the modelled snow area.
        "false_snow_share": round(fp / (tp + fp), 4) if tp + fp else 0.0,
    }


def band_scores(predicted: list[np.ndarray], references: list[Reference], elevation: np.ndarray) -> dict:
    """Pooled confusion overall and per elevation band over the given dates."""
    if not references:
        return {}
    guess = np.concatenate([p[r.usable] for p, r in zip(predicted, references)])
    truth = np.concatenate([r.observed[r.usable] for r in references])
    height = np.concatenate([elevation[r.usable] for r in references])
    scores = {"all": confusion(guess, truth)}
    for low, high in zip(ELEVATION_BANDS[:-1], ELEVATION_BANDS[1:]):
        inside = (height >= low) & (height < high)
        scores[f"{low}-{high}"] = confusion(guess[inside], truth[inside])
    return scores


def score(masks: list[list[np.ndarray]], references: list[Reference], elevation: np.ndarray, settings: dict) -> dict:
    """Weights on fit dates, scores on held-out dates (every third clear date, model rule)."""
    cells = elevation.size
    order = sorted(range(len(references)), key=lambda position: references[position].day)
    fit, test = split_fit_test(len(order))
    fit_positions = [order[index] for index in fit]
    test_positions = [order[index] for index in test]
    members = len(masks[0])

    def unpacked(position: int) -> np.ndarray:
        return np.stack([np.unpackbits(packed, count=cells).astype(bool) for packed in masks[position]])

    errors = np.zeros((members, len(fit_positions)))
    for column, position in enumerate(fit_positions):
        stack = unpacked(position)
        reference = references[position]
        for member in range(members):
            errors[member, column] = misclassification(stack[member], reference.observed, reference.usable)
    weights = tempered_weights(errors.mean(axis=1), settings["ensemble"]["target_effective_members"])
    uniform = np.full(members, 1.0 / members)

    held_out = [references[position] for position in test_positions]
    snowy = [
        index
        for index, reference in enumerate(held_out)
        if reference.observed[reference.usable].mean() >= SNOW_DATE_FRACTION
    ]
    result: dict = {
        "fit_dates": [references[position].day.isoformat() for position in fit_positions],
        "test_dates": [reference.day.isoformat() for reference in held_out],
        "snow_season_test_dates": [held_out[index].day.isoformat() for index in snowy],
        "effective_members": round(float(1 / np.sum(weights**2)), 2),
    }
    for label, vector in (("weighted", weights), ("prior", uniform)):
        predicted = [vector @ unpacked(position) >= 0.5 for position in test_positions]
        result[label] = {
            "all_dates": band_scores(predicted, held_out, elevation),
            "snow_season": band_scores([predicted[i] for i in snowy], [held_out[i] for i in snowy], elevation),
        }
    return result


def run_snow(args: argparse.Namespace) -> dict:
    region = load_region(args.region)
    settings = merged_settings(region)
    static = Static(region, settings)
    members = sample_members(args.members, settings["ensemble"]["seed"])
    excluded = exclusion_mask(static, args.exclude)
    today = datetime.now(timezone.utc).date()
    spacing = settings["forcing"]["spacing_deg"]

    references_by_year: dict[int, list[Reference]] = {}
    for year in args.years:
        start, end = season_bounds(year, today)
        if args.reference == "interim":
            days = [day for day in args.dates if start <= day <= end]
            references = interim_reference(static, days, args.cache)
        else:
            raise RuntimeError(f"Unknown reference {args.reference}")
        for reference in references:
            reference.usable &= ~excluded
        references_by_year[year] = references
        log(f"{year}: {len(references)} usable reference dates")

    output: dict = {
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reference": args.reference,
        "members": args.members,
        "seed": settings["ensemble"]["seed"],
        "years": args.years,
        "excluded_cells": int(excluded.sum()),
        "elevation_bands_m": list(ELEVATION_BANDS),
        "forcings": {},
    }
    for name in args.forcings:
        masks: list[list[np.ndarray]] = []
        scored: list[Reference] = []
        missing: dict[str, dict] = {}
        try:
            for year in args.years:
                start, end = season_bounds(year, today)
                forcing, gaps = load_forcing(name, region.bbox, spacing, start, end, args.cache)
                missing[str(year)] = gaps or {}
                days = [reference.day for reference in references_by_year[year]]
                log(f"{name} {year}: simulating {len(members)} members")
                masks.extend(simulate_forcing(static, forcing, members, days))
                scored.extend(references_by_year[year])
        except RuntimeError as error:
            log(f"{name}: not scored ({error})")
            output["forcings"][name] = {"status": "not scored", "reason": str(error), "missing_fraction": missing}
            continue
        output["forcings"][name] = {
            "status": "scored",
            "missing_fraction": missing,
            **score(masks, scored, static.elevation, settings),
        }
    return output


def daily_totals(times: list[datetime], values: np.ndarray, day_start_hour: int) -> dict[date, float]:
    """Sums hourly amounts into days that start at `day_start_hour` UTC, complete days only."""
    sums: dict[date, list[float]] = {}
    for stamp, value in zip(times, values):
        sums.setdefault((stamp - timedelta(hours=day_start_hour)).date(), []).append(value)
    return {day: float(np.sum(items)) for day, items in sums.items() if len(items) == 24 and not np.isnan(items).any()}


def precipitation_metrics(model: dict[date, float], station: dict[date, float]) -> dict | None:
    days = sorted(set(model) & set(station))
    if len(days) < 30:
        return None
    m = np.array([model[day] for day in days])
    s = np.array([station[day] for day in days])
    pentads = len(days) // 5
    m5 = m[: pentads * 5].reshape(pentads, 5).sum(axis=1)
    s5 = s[: pentads * 5].reshape(pentads, 5).sum(axis=1)
    wet_model, wet_station = m >= WET_DAY_MM, s >= WET_DAY_MM
    hits = int(np.sum(wet_model & wet_station))
    return {
        "days": len(days),
        "station_total_mm": round(float(s.sum()), 1),
        "model_total_mm": round(float(m.sum()), 1),
        "ratio": round(float(m.sum()) / float(s.sum()), 3) if s.sum() > 0 else None,
        "daily_r": round(float(np.corrcoef(m, s)[0, 1]), 3) if m.std() > 0 and s.std() > 0 else None,
        "pentad_r": round(float(np.corrcoef(m5, s5)[0, 1]), 3) if m5.std() > 0 and s5.std() > 0 else None,
        "wet_day_pod": round(hits / int(wet_station.sum()), 3) if wet_station.any() else None,
        "wet_day_far": round(1 - hits / int(wet_model.sum()), 3) if wet_model.any() else None,
    }


def run_precip(args: argparse.Namespace) -> dict:
    region = load_region(args.region)
    today = datetime.now(timezone.utc).date()
    start = season_bounds(min(args.years), today)[0]
    end = season_bounds(max(args.years), today)[1]
    readers: list[tuple[list[stations.Station], Callable[[stations.Station], dict[date, float]], int]] = [
        (stations.ria_stations(args.cache), lambda station: stations.ria_daily(station, start, end, args.cache), 0)
    ]
    key = stations.aemet_key()
    if key:
        # AEMET's climatological day runs from 07 to 07 UTC.
        readers.append(
            (
                stations.aemet_stations(key, args.cache),
                lambda station: stations.aemet_daily(station, start, end, key, args.cache),
                7,
            )
        )
    era5_land_forcing = None
    if ERA5_LAND in args.forcings and era5_land.api_key():
        era5_land_forcing = era5_land.fetch_forcing(region.bbox, start, end, args.cache)
    output: dict = {
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "period": [start.isoformat(), end.isoformat()],
        "aemet": "used" if key else "skipped: no AEMET_API_KEY",
        "stations": [],
    }
    hours = [
        datetime.combine(start, datetime.min.time()) + timedelta(hours=h) for h in range(((end - start).days + 1) * 24)
    ]
    for candidates, reader, day_start in readers:
        for station in [s for s in candidates if stations.near(s, region.bbox, STATION_MARGIN_DEG)]:
            observed = reader(station)
            entry: dict = {**station.__dict__, "observed_days": len(observed), "forcings": {}}
            if len(observed) >= 30:
                for name in args.forcings:
                    if name == ERA5_LAND:
                        if era5_land_forcing is None:
                            entry["forcings"][name] = "pending: no CDSAPI_KEY"
                            continue
                        nearest = int(
                            np.argmin(
                                np.hypot(era5_land_forcing.lon - station.lon, era5_land_forcing.lat - station.lat)
                            )
                        )
                        times, values = hours, era5_land_forcing.precipitation[nearest].ravel().astype("float64")
                    else:
                        times, values = openmeteo.hourly_precipitation(
                            name, station.lat, station.lon, start, end, args.cache
                        )
                    entry["forcings"][name] = precipitation_metrics(daily_totals(times, values, day_start), observed)
            output["stations"].append(entry)
            log(f"{station.network} {station.name} ({station.elevation_m:.0f} m): {len(observed)} days")
    output["summary"] = precipitation_summary(output["stations"], args.forcings)
    return output


def precipitation_summary(entries: list[dict], forcings: list[str]) -> dict:
    """Across stations: median total ratio and mean of the other metrics, per forcing."""
    summary = {}
    for name in forcings:
        metrics = [entry["forcings"][name] for entry in entries if isinstance(entry["forcings"].get(name), dict)]
        if not metrics:
            continue
        row: dict = {
            "stations": len(metrics),
            "median_ratio": round(float(np.median([m["ratio"] for m in metrics])), 3),
        }
        for key in ("daily_r", "pentad_r", "wet_day_pod", "wet_day_far"):
            values = [m[key] for m in metrics if m[key] is not None]
            row[f"mean_{key}"] = round(float(np.mean(values)), 3) if values else None
        summary[name] = row
    return summary


def run_inventory(args: argparse.Namespace) -> dict:
    """Coverage of every Open-Meteo archive checked for the study, at one point in the domain."""
    lat, lon = INVENTORY_POINT
    start, end = date(2023, 9, 1), args.end
    ledger = openmeteo.Ledger(args.cache / "openmeteo-ledger.jsonl")
    rows = []
    for url, models in INVENTORY_MODELS.items():
        for model in models:
            query = (
                f"{url}?latitude={lat}&longitude={lon}&start_date={start}&end_date={end}"
                f"&hourly={','.join(openmeteo.VARIABLES)}&models={model}&timezone=UTC"
            )
            weight = openmeteo.call_weight(1, (end - start).days + 1, len(openmeteo.VARIABLES))
            try:
                record = openmeteo.cached_get(query, weight, args.cache, ledger)[0]
            except urllib.error.HTTPError as error:
                if error.code != 400:
                    raise
                # Open-Meteo answers 400 with a reason, e.g. a model domain that misses the point.
                reason = json.loads(error.read().decode()).get("reason", "")
                rows.append({"endpoint": url, "model": model, "available": False, "reason": reason})
                continue
            row: dict = {
                "endpoint": url,
                "model": model,
                "available": True,
                "grid_point": [record["latitude"], record["longitude"]],
            }
            times = record["hourly"]["time"]
            for name in openmeteo.VARIABLES:
                values = record["hourly"][name]
                present = [index for index, value in enumerate(values) if value is not None]
                if not present:
                    row[name] = None
                    continue
                first, last = present[0], present[-1]
                row[name] = {
                    "first": times[first],
                    "last": times[last],
                    "gap_hours": sum(values[index] is None for index in range(first, last + 1)),
                }
            rows.append(row)
    return {"point": [lat, lon], "period": [start.isoformat(), end.isoformat()], "archives": rows}


def run_fetch(args: argparse.Namespace) -> dict:
    """Fills the forcing cache ahead of `snow`, which can take days under the free API limits."""
    region = load_region(args.region)
    spacing = merged_settings(region)["forcing"]["spacing_deg"]
    today = datetime.now(timezone.utc).date()
    result: dict = {}
    for year in args.years:
        start, end = season_bounds(year, today)
        for name in args.forcings:
            try:
                _, gaps = load_forcing(name, region.bbox, spacing, start, end, args.cache)
            except RuntimeError as error:
                result[f"{name} {year}"] = str(error)
            else:
                result[f"{name} {year}"] = gaps
            log(f"{name} {year}: {result[f'{name} {year}']}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inventory", "fetch", "snow", "precip"):
        command = commands.add_parser(name)
        command.add_argument("--region", type=Path, default=Path("regions/sierra-nevada.json"))
        command.add_argument("--cache", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name == "inventory":
            command.add_argument("--end", type=date.fromisoformat, required=True)
            continue
        command.add_argument("--years", type=int, nargs="+", required=True, help="hydrological years, by start")
        command.add_argument("--forcings", nargs="+", default=list(FORCINGS), choices=FORCINGS)
        if name == "snow":
            command.add_argument("--reference", choices=["interim"], required=True)
            command.add_argument("--dates", type=date.fromisoformat, nargs="*", default=[])
            command.add_argument("--members", type=int, default=48)
            command.add_argument("--exclude", type=Path, help="GeoJSON of areas left out of the scores")
    args = parser.parse_args(argv)
    runners = {"inventory": run_inventory, "fetch": run_fetch, "snow": run_snow, "precip": run_precip}
    runner = runners[args.command]
    result = runner(args)
    args.output.mkdir(parents=True, exist_ok=True)
    destination = args.output / f"{args.command}.json"
    destination.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    log(f"Wrote {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
