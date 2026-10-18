import argparse
import copy
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ..region import Region, load_region
from . import observations as obs
from .dem import load_elevation, slope_aspect
from .ensemble import sample_members, tempered_weights, weighted_quantiles
from .forcing import fetch_forcing, neighbour_weights
from .grid import Grid, build_grid
from .outputs import (
    MIN_VISIBLE_DEPTH_M,
    MIN_VISIBLE_SWE_MM,
    to_grid,
    write_field_png,
    write_geotiff,
    write_json,
    write_observation_png,
)
from .radiation import radiation_index
from .snowpack import Domain, build_tables, simulate
from .validation import confusion_metrics, gate, misclassification, observed_snow, split_fit_test

DEFAULTS = {
    "resolution_m": 100,
    "hydrological_year_start_month": 10,
    "basin_id_field": "cod_uni",
    "basin_name_field": "nom_rio_1",
    "calibration_years": [],
    "forcing": {"model": "ecmwf_ifs", "spacing_deg": 0.1},
    "ensemble": {
        "members": 48,
        "seed": 1,
        "target_effective_members": 12,
        "operational_members": 16,
    },
    "observation": {
        "max_cloud": 40,
        "scenes_per_year": 28,
        "min_gap_days": 7,
        "min_usable_fraction": 0.3,
        "monitor_days": 45,
    },
    "gate": {"min_f1": 0.8, "min_test_dates_with_snow": 3},
}
LIMITATIONS = [
    "Temperature-index melt with a radiation term; no wind redistribution, sublimation or avalanching",
    "The season starts snow-free, so glaciers and perennial snow are not represented",
    "Forcing is a 9 km to 25 km analysis downscaled with an elevation lapse rate and a precipitation gradient",
    "Skill is verified against Sentinel-2 snow cover only; snow water equivalent and depth magnitudes are not verified against in-situ measurements",
]
PERCENTILES = [0.1, 0.5, 0.9]


def merged_settings(region: Region) -> dict:
    settings = copy.deepcopy(DEFAULTS)
    for key, value in region.settings.get("snow_model", {}).items():
        if isinstance(value, dict) and isinstance(settings.get(key), dict):
            settings[key].update(value)
        else:
            settings[key] = value
    return settings


def log(message: str) -> None:
    print(message, flush=True)


class Static:
    """Everything that depends only on the region, not on the year or the ensemble member."""

    def __init__(self, region: Region, settings: dict):
        import rasterio.features
        from rasterio.warp import transform_geom

        self.region = region
        self.settings = settings
        self.grid = build_grid(region.bbox, settings["resolution_m"])
        grid = self.grid
        payload = json.loads(region.basins.read_text(encoding="utf-8"))
        shapes, self.basin_ids, self.basin_names = [], [], []
        for index, feature in enumerate(payload["features"]):
            shapes.append((transform_geom("EPSG:4326", grid.crs, feature["geometry"]), index))
            self.basin_ids.append(str(feature["properties"][settings["basin_id_field"]]))
            self.basin_names.append(str(feature["properties"][settings["basin_name_field"]]))
        basin_raster = rasterio.features.rasterize(
            shapes,
            out_shape=(grid.height, grid.width),
            transform=grid.transform,
            fill=-1,
            dtype="int16",
        )
        log("Loading the elevation model")
        elevation = load_elevation(grid, region.bbox)
        inside = (basin_raster >= 0) & ~np.isnan(elevation)
        self.cell_index = np.flatnonzero(inside.ravel())
        self.elevation = elevation.ravel()[self.cell_index]
        self.basin = basin_raster.ravel()[self.cell_index].astype("int64")
        slope, aspect = slope_aspect(elevation, grid.resolution)
        latitude = (region.bbox[1] + region.bbox[3]) / 2
        self.radiation = radiation_index(
            latitude, slope.ravel()[self.cell_index], aspect.ravel()[self.cell_index]
        )
        rows, columns = np.divmod(self.cell_index, grid.width)
        self.cell_x = grid.left + (columns + 0.5) * grid.resolution
        self.cell_y = grid.top - (rows + 0.5) * grid.resolution
        self.basin_area_km2 = (
            np.bincount(self.basin, minlength=len(shapes)) * grid.cell_area_m2 / 1e6
        )
        log(f"Model grid {grid.width}x{grid.height} at {grid.resolution:.0f} m, {self.cell_index.size} cells")


def year_bounds(year: int, start_month: int) -> tuple[date, date]:
    start = date(year, start_month, 1)
    end = min(date(year + 1, start_month, 1) - timedelta(days=1), date.today() - timedelta(days=1))
    return start, end


def current_year(start_month: int) -> int:
    today = date.today()
    return today.year if today.month >= start_month else today.year - 1


def prepare_year(static: Static, year: int, cache: Path):
    settings = static.settings
    start, end = year_bounds(year, settings["hydrological_year_start_month"])
    if (end - start).days < 1:
        return None
    log(f"Fetching forcing for {start} to {end}")
    forcing = fetch_forcing(
        static.region.bbox,
        start,
        end,
        settings["forcing"]["spacing_deg"],
        settings["forcing"]["model"],
        cache,
    )
    tables = build_tables(forcing)
    neighbours, weights = neighbour_weights(
        forcing, static.cell_x, static.cell_y, static.grid.crs
    )
    domain = Domain(
        static.elevation,
        neighbours,
        weights,
        static.basin,
        len(static.basin_ids),
        static.grid.cell_area_m2,
        static.radiation,
    )
    return start, end, tables, domain


def observation_arrays(static: Static, scene: obs.Scene, cache: Path):
    """Observed snow state and usability on the model cells, plus the 10 m masks."""
    fine = static.grid.refined()
    snow, valid = obs.cached_snow_mask(scene, fine, cache)
    fraction, valid_fraction = obs.aggregate(snow, valid, static.grid.factor)
    observed, usable = observed_snow(
        fraction.ravel()[static.cell_index], valid_fraction.ravel()[static.cell_index]
    )
    return observed, usable, snow, valid


def usable_scenes(static: Static, scenes: list[obs.Scene], cache: Path):
    minimum = static.settings["observation"]["min_usable_fraction"]
    for scene in scenes:
        observed, usable, snow, valid = observation_arrays(static, scene, cache)
        if usable.mean() >= minimum:
            yield scene, observed, usable, snow, valid


def calibrate(region_file: Path, cache: Path, output: Path) -> Path:
    region = load_region(region_file)
    settings = merged_settings(region)
    years = settings["calibration_years"]
    if not years:
        raise RuntimeError("The region defines no calibration years")
    static = Static(region, settings)
    members = sample_members(settings["ensemble"]["members"], settings["ensemble"]["seed"])

    dates, observed_list, usable_list, simulated = [], [], [], []
    for year in years:
        prepared = prepare_year(static, year, cache)
        if prepared is None:
            continue
        start, end, tables, domain = prepared
        config = settings["observation"]
        scenes = obs.search_scenes(region.bbox, start, end, config["max_cloud"])
        chosen = obs.choose_scenes(scenes, config["scenes_per_year"], config["min_gap_days"])
        log(f"{year}: {len(chosen)} Sentinel-2 days selected from {len(scenes)}")
        kept = list(usable_scenes(static, chosen, cache))
        indexes = {(scene.day - start).days: position for position, (scene, *_rest) in enumerate(kept)}
        results = []
        for number, parameters in enumerate(members, start=1):
            results.append(simulate(domain, tables, parameters, set(indexes), False))
            if number % 8 == 0:
                log(f"{year}: simulated {number}/{len(members)} members")
        for day_index, position in sorted(indexes.items()):
            scene, observed, usable, *_ = kept[position]
            dates.append(scene.day)
            observed_list.append(observed)
            usable_list.append(usable)
            simulated.append([result.snow_masks[day_index] for result in results])

    if not dates:
        raise RuntimeError("No usable Sentinel-2 observations for the calibration years")

    cells = static.cell_index.size

    def simulated_masks(position: int) -> np.ndarray:
        return np.stack(
            [np.unpackbits(packed, count=cells).astype(bool) for packed in simulated[position]]
        )

    order = sorted(range(len(dates)), key=lambda position: dates[position])
    fit, test = split_fit_test(len(order))
    fit_positions = [order[index] for index in fit]
    test_positions = [order[index] for index in test]

    errors = np.zeros((len(members), len(fit_positions)))
    for column, position in enumerate(fit_positions):
        stack = simulated_masks(position)
        for member in range(len(members)):
            errors[member, column] = misclassification(
                stack[member], observed_list[position], usable_list[position]
            )
    cost = errors.mean(axis=1)
    weights = tempered_weights(cost, settings["ensemble"]["target_effective_members"])
    uniform = np.full(len(members), 1.0 / len(members))

    def pooled(weight_vector: np.ndarray) -> tuple[dict, int]:
        probabilities, truths, usables, snow_dates = [], [], [], 0
        for position in test_positions:
            probabilities.append(weight_vector @ simulated_masks(position))
            truths.append(observed_list[position])
            usables.append(usable_list[position])
            if observed_list[position][usable_list[position]].mean() >= 0.01:
                snow_dates += 1
        return (
            confusion_metrics(
                np.concatenate(probabilities), np.concatenate(truths), np.concatenate(usables)
            ),
            snow_dates,
        )

    posterior, snow_dates = pooled(weights)
    prior, _ = pooled(uniform)
    verdict = gate(posterior, prior, snow_dates, settings["gate"])
    log(f"Held-out F1 {posterior['f1']} (unweighted {prior['f1']}); gate passed: {verdict['passed']}")

    payload = {
        "schema_version": 1,
        "region": region.id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "resolution_m": settings["resolution_m"],
        "forcing": settings["forcing"],
        "calibration_years": years,
        "observation": {
            "source": "Sentinel-2 L2A snow cover at 10 m (NDSI >= 0.4, green reflectance >= 0.1)",
            "fit_dates": [dates[position].isoformat() for position in fit_positions],
            "test_dates": [dates[position].isoformat() for position in test_positions],
        },
        "members": [
            {"parameters": parameters, "weight": float(weight), "cost": float(member_cost)}
            for parameters, weight, member_cost in zip(members, weights, cost)
        ],
        "metrics": {"posterior": posterior, "prior": prior, "test_dates_with_snow": snow_dates},
        "gate": verdict,
        "limitations": LIMITATIONS,
    }
    destination = output / "calibration.json"
    write_json(destination, payload)
    return destination


def quantile_series(values: np.ndarray, weights: np.ndarray) -> dict:
    """Weighted p10, p50 and p90 over members for an array of shape members x days x basins."""
    low, middle, high = weighted_quantiles(values, weights, PERCENTILES)
    return {"p10": low, "p50": middle, "p90": high}


def operate(region_file: Path, calibration_file: Path, cache: Path, output: Path) -> Path:
    region = load_region(region_file)
    settings = merged_settings(region)
    if calibration_file.exists():
        calibration = json.loads(calibration_file.read_text(encoding="utf-8"))
    else:
        calibration = {
            "created_at": None,
            "calibration_years": [],
            "metrics": None,
            "limitations": LIMITATIONS,
            "gate": {"passed": False, "reasons": ["No calibration is available yet"]},
        }
    static = Static(region, settings)
    grid = static.grid
    config = settings["observation"]
    today = date.today()
    start_month = settings["hydrological_year_start_month"]
    year = current_year(start_month)
    start, end = year_bounds(year, start_month)

    scenes = obs.search_scenes(
        region.bbox, today - timedelta(days=config["monitor_days"]), today, config["max_cloud"]
    )
    recent = obs.choose_scenes(scenes, 8, 3)
    log(f"{len(recent)} recent Sentinel-2 days")
    kept = list(usable_scenes(static, recent, cache))

    layers = {}
    if kept:
        scene, observed, usable, snow, valid = max(kept, key=lambda row: row[0].day)
        write_observation_png(output / "observed_snow_10m.png", snow, valid)
        layers["observed_snow_10m"] = {
            "image": "observed_snow_10m.png",
            "corners": grid.lonlat_corners(),
            "date": scene.day.isoformat(),
            "resolution_m": 10,
            "valid_fraction": round(float(valid.mean()), 3),
            "snow_fraction_of_valid": round(float(snow.sum() / max(valid.sum(), 1)), 4),
            "source": "Sentinel-2 L2A, NDSI >= 0.4 at 10 m (contains modified Copernicus Sentinel data)",
        }

    verdict = calibration["gate"]
    status = {"available": False, "reasons": list(verdict["reasons"])}
    manifest = {
        "schema_version": 1,
        "region": {"id": region.id, "name": region.name},
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "hydrological_year": year,
        "forcing": {
            "model": settings["forcing"]["model"],
            "provider": "Open-Meteo",
            "start": start.isoformat(),
            "last_day": end.isoformat(),
        },
        "model": {
            "status": "unavailable",
            "reasons": status["reasons"],
            "resolution_m": settings["resolution_m"],
            "limitations": calibration["limitations"],
        },
        "basins": [
            {
                "id": basin_id,
                "name": name,
                "area_km2": round(float(area), 1),
            }
            for basin_id, name, area in zip(
                static.basin_ids, static.basin_names, static.basin_area_km2
            )
        ],
        "layers": layers,
        "monitoring": [],
    }

    if calibration["metrics"]:
        manifest["model"]["calibration"] = {
            "created_at": calibration["created_at"],
            "gate": verdict,
            "metrics": calibration["metrics"],
            "years": calibration["calibration_years"],
        }

    prepared = prepare_year(static, year, cache) if verdict["passed"] else None
    if prepared is not None:
        _, _, tables, domain = prepared
        chosen = sorted(
            calibration["members"], key=lambda member: member["weight"], reverse=True
        )[: settings["ensemble"]["operational_members"]]
        weights = np.array([member["weight"] for member in chosen])
        weights /= weights.sum()
        observation_days = {
            (scene.day - start).days: row
            for row, (scene, *_rest) in enumerate(kept)
            if 0 <= (scene.day - start).days < len(tables.days)
        }
        results = []
        for number, member in enumerate(chosen, start=1):
            results.append(
                simulate(domain, tables, member["parameters"], set(observation_days), True)
            )
        log(f"Simulated {len(results)} members for {len(tables.days)} days")

        dates = [day.isoformat() for day in tables.days]
        swe = quantile_series(np.stack([r.basin_swe_hm3 for r in results]), weights)
        area = quantile_series(np.stack([r.basin_snow_area_km2 for r in results]), weights)
        snowfall = quantile_series(np.stack([r.basin_snowfall_hm3 for r in results]), weights)
        melt = quantile_series(np.stack([r.basin_melt_hm3 for r in results]), weights)
        for index, basin in enumerate(manifest["basins"]):
            def series(source):
                return {key: np.round(value[:, index], 4).tolist() for key, value in source.items()}

            write_json(
                output / "series" / f"{basin['id']}.json",
                {
                    "basin": basin["id"],
                    "dates": dates,
                    "swe_hm3": series(swe),
                    "snow_area_km2": series(area),
                    "snowfall_hm3": series(snowfall),
                    "melt_hm3": series(melt),
                },
            )
            basin["series"] = f"series/{basin['id']}.json"
            basin["latest"] = {
                "date": dates[-1],
                "swe_hm3": {key: round(float(value[-1, index]), 4) for key, value in swe.items()},
                "snow_area_km2": {
                    key: round(float(value[-1, index]), 2) for key, value in area.items()
                },
            }

        final_swe = np.stack([r.final_swe for r in results])
        final_depth = np.stack([r.final_depth for r in results])
        mean_swe = to_grid(weights @ final_swe, static.cell_index, grid)
        mean_depth = to_grid(weights @ final_depth, static.cell_index, grid)
        low_swe, high_swe = weighted_quantiles(final_swe, weights, [0.1, 0.9])
        spread = to_grid(high_swe - low_swe, static.cell_index, grid)
        swe_max = float(max(np.nanpercentile(mean_swe, 99), 50.0))
        depth_max = float(max(np.nanpercentile(mean_depth, 99), 0.5))
        write_field_png(output / "swe_latest.png", mean_swe, swe_max, "swe", MIN_VISIBLE_SWE_MM)
        write_field_png(output / "depth_latest.png", mean_depth, depth_max, "depth", MIN_VISIBLE_DEPTH_M)
        write_geotiff(
            output / "snow_state_latest.tif",
            [
                (mean_swe, "swe_mm_weighted_mean"),
                (mean_depth, "snow_depth_m_weighted_mean"),
                (spread, "swe_mm_p90_minus_p10"),
            ],
            grid,
        )
        corners = grid.lonlat_corners()
        layers["swe"] = {
            "image": "swe_latest.png",
            "corners": corners,
            "date": dates[-1],
            "units": "mm water equivalent",
            "scale_max": round(swe_max, 1),
            "minimum_visible": MIN_VISIBLE_SWE_MM,
        }
        layers["depth"] = {
            "image": "depth_latest.png",
            "corners": corners,
            "date": dates[-1],
            "units": "m",
            "scale_max": round(depth_max, 2),
            "minimum_visible": MIN_VISIBLE_DEPTH_M,
        }
        manifest["model"]["status"] = "available"
        manifest["model"]["reasons"] = []
        manifest["model"]["members"] = len(results)

        for scene, observed, usable, *_ in kept:
            index = (scene.day - start).days
            if index not in observation_days:
                continue
            packed = [r.snow_masks[index] for r in results]
            probability = weights @ np.stack(
                [np.unpackbits(item, count=static.cell_index.size).astype(bool) for item in packed]
            )
            manifest["monitoring"].append(
                {"date": scene.day.isoformat(), **confusion_metrics(probability, observed, usable)}
            )

    write_json(output / "manifest.json", manifest)
    return output / "manifest.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("calibrate", "operate"):
        command = commands.add_parser(name)
        command.add_argument("--region", type=Path, default=Path("regions/sierra-nevada.json"))
        command.add_argument("--cache", type=Path, default=Path("snow-cache"))
        command.add_argument("--output", type=Path, default=Path("snow-output"))
        if name == "operate":
            command.add_argument("--calibration", type=Path)
    args = parser.parse_args()
    started = time.time()
    if args.command == "calibrate":
        path = calibrate(args.region, args.cache, args.output)
    else:
        calibration = args.calibration or args.region.with_suffix(".snow-calibration.json")
        path = operate(args.region, calibration, args.cache, args.output)
    log(f"{path} written in {time.time() - started:.0f} s")


if __name__ == "__main__":
    sys.exit(main())
