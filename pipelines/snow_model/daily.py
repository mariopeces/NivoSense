"""Daily SWE and snow depth for the catalogue, from the model state of the day before.

    python -m pipelines.snow_model.daily --start 2026-10-01 --end 2026-11-21 --target staging

Per date it steps the ensemble one day, applies direct insertion of the date's Sentinel-2 observation
(pipelines.snow_model.insertion), takes the ensemble median and publishes layers `swe` (mm) and
`snow_depth` (m) through pipelines.catalog.publish(). The state of every member is stored under
`state/<date>.npz` of the target, so a rerun of a date starts from the day before. A season starts on
1 October with no snow, as the calibration assumes.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from pipelines.catalog import code_version, publish, storage_from_env
from pipelines.catalog.storage import NO_CACHE, Storage
from pipelines.ramps import colour_values
from pipelines.region import load_region

from . import insertion
from .forcing import Forcing, fetch_forcing, neighbour_weights
from .outputs import MIN_VISIBLE_SWE_MM, to_grid, write_geotiff
from .run import Static, log, merged_settings
from .snowpack import Domain, Member, build_tables

SEASON_START_MONTH = 10
SWE_RANGE = [0.0, 5000.0]
DEPTH_RANGE = [0.0, 20.0]


@dataclass(frozen=True)
class Season:
    start: date
    first: date
    last: date


def seasons(first: date, last: date) -> list[Season]:
    """The hydrological seasons (1 October to 30 September) a date range touches, in order."""
    result = []
    day = first
    while day <= last:
        year = day.year if day.month >= SEASON_START_MONTH else day.year - 1
        season_start = date(year, SEASON_START_MONTH, 1)
        season_end = date(year + 1, SEASON_START_MONTH, 1) - timedelta(days=1)
        result.append(Season(season_start, day, min(last, season_end)))
        day = season_end + timedelta(days=1)
    return result


def state_key(day: date) -> str:
    return f"state/{day.isoformat()}.npz"


def state_signature(static: Static, members: list[dict]) -> str:
    text = json.dumps([static.grid.signature(), int(static.cell_index.size), members], sort_keys=True)
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def state_digest(swe: np.ndarray, depth: np.ndarray) -> str:
    digest = hashlib.sha256()
    for array in (swe, depth):
        digest.update(np.ascontiguousarray(array, dtype="<f4").tobytes())
    return digest.hexdigest()


def save_state(storage: Storage, day: date, swe: np.ndarray, depth: np.ndarray, signature: str) -> None:
    buffer = io.BytesIO()
    np.savez_compressed(buffer, swe=swe, depth=depth, signature=np.array(signature))
    storage.write(state_key(day), buffer.getvalue(), "application/octet-stream", NO_CACHE)


def load_state(storage: Storage, day: date, signature: str) -> tuple[np.ndarray, np.ndarray] | None:
    blob = storage.read(state_key(day))
    if blob is None:
        return None
    with np.load(io.BytesIO(blob.data)) as stored:
        if str(stored["signature"]) != signature:
            raise RuntimeError(
                f"{state_key(day)} was written for another grid or ensemble; rerun from the season start"
            )
        return stored["swe"], stored["depth"]


def operational_members(calibration_file: Path, count: int) -> list[dict]:
    calibration = json.loads(calibration_file.read_text(encoding="utf-8"))
    ranked = sorted(calibration["members"], key=lambda member: member["weight"], reverse=True)
    return [member["parameters"] for member in ranked[:count]]


def build_domain(static: Static, forcing: Forcing) -> Domain:
    neighbours, weights = neighbour_weights(forcing, static.cell_x, static.cell_y, static.grid.crs)
    return Domain(
        static.elevation,
        neighbours,
        weights,
        static.basin,
        len(static.basin_ids),
        static.grid.cell_area_m2,
        static.radiation,
    )


def forcing_digest(forcing: Forcing) -> str:
    digest = hashlib.sha256()
    for array in (forcing.temperature, forcing.precipitation, forcing.shortwave):
        digest.update(np.ascontiguousarray(array, dtype="<f4").tobytes())
    return digest.hexdigest()[:16]


def write_products(folder: Path, static: Static, swe: np.ndarray, depth: np.ndarray) -> dict[str, dict[str, Path]]:
    """Data GeoTIFFs (nodata under 5 mm of SWE) and RGBA display rasters of the two layers."""
    import rasterio

    grid = static.grid
    visible = swe >= MIN_VISIBLE_SWE_MM
    swe_grid = to_grid(np.where(visible, swe, np.nan), static.cell_index, grid)
    depth_grid = to_grid(np.where(visible, depth, np.nan), static.cell_index, grid)
    files: dict[str, dict[str, Path]] = {}
    # The depth ramp is in cm; the published data stays in metres.
    for layer, array, scale in (("swe", swe_grid, 1.0), ("snow_depth", depth_grid, 100.0)):
        data = folder / f"{layer}.tif"
        write_geotiff(data, [(array, layer)], grid)
        display = folder / f"{layer}-display.tif"
        rgba = colour_values(array * scale, layer)
        with rasterio.open(
            display,
            "w",
            driver="GTiff",
            width=grid.width,
            height=grid.height,
            count=4,
            dtype="uint8",
            crs=grid.crs,
            transform=grid.transform,
            photometric="RGB",
            alpha="YES",
            compress="deflate",
        ) as target:
            target.write(np.moveaxis(rgba, 2, 0))
        files[layer] = {"data": data, "display": display}
    return files


def run_season(
    static: Static,
    settings: dict,
    parameters: list[dict],
    season: Season,
    storage: Storage,
    cache: Path,
    version: str,
) -> list[dict]:
    signature = state_signature(static, parameters)
    day_before = season.first - timedelta(days=1)
    if season.first == season.start:
        swe = np.zeros((len(parameters), static.cell_index.size), dtype="float32")
        depth = np.zeros_like(swe)
        prior = None
    else:
        stored = load_state(storage, day_before, signature)
        if stored is None:
            raise RuntimeError(
                f"No model state for {day_before}; run the season from {season.start} "
                "or from a date with a stored state"
            )
        swe, depth = stored
        prior = state_digest(swe, depth)

    last = min(season.last, date.today() - timedelta(days=1))
    log(f"Season {season.start.year}-{season.start.year + 1}: {season.first} to {last}")
    forcing = fetch_forcing(
        static.region.bbox,
        season.first,
        last,
        settings["forcing"]["spacing_deg"],
        settings["forcing"]["model"],
        cache,
    )
    tables = build_tables(forcing)
    domain = build_domain(static, forcing)
    forcing_id = f"forcing:{forcing_digest(forcing)}"
    members = [Member(domain, tables, p, swe[i], depth[i]) for i, p in enumerate(parameters)]
    ski = static.ski_cells
    elevation_grid = to_grid(static.elevation, static.cell_index, static.grid)
    cell_km2 = static.grid.cell_area_m2 / 1e6
    ski_km2 = float(ski.sum()) * cell_km2

    results = []
    for index, day in enumerate(tables.days):
        for member in members:
            member.step(index)
        before = np.median(np.stack([m.swe for m in members]), axis=0)

        scores: dict[str, float] = {}
        flags = ["experimental_model", "median_of_ensemble", "ski_resort_excluded_from_score"]
        source_ids = [f"open-meteo:{settings['forcing']['model']}", forcing_id]
        observation = insertion.load_observation(storage, day.isoformat())
        if observation is not None:
            state = insertion.cell_state(observation, static.grid)
            inferred = insertion.shadow_bare(state, elevation_grid, static.ski_resort).ravel()[static.cell_index]
            bare = state.bare.ravel()[static.cell_index] | inferred
            snowy_before = (before >= MIN_VISIBLE_SWE_MM) & ~ski
            for member in members:
                member.insert_bare(bare)
            flags.append("observation_inserted")
            source_ids.append(f"snow_obs:{day.isoformat()}:{observation.pixel_hash[:16]}")
            scores["cells_cleared_by_observation"] = float((bare & (before > 0)).sum())
            scores["cells_cleared_in_terrain_shadow"] = float((inferred & (before > 0)).sum())
            scores["false_snow_before_insertion_pct"] = round(
                100.0 * float((snowy_before & bare).sum()) / max(1, int(snowy_before.sum())), 2
            )
        else:
            flags.append("no_observation")

        swe = np.stack([m.swe for m in members])
        depth = np.stack([m.depth for m in members])
        median_swe = np.median(swe, axis=0)
        median_depth = np.median(depth, axis=0)
        outside_ski = (median_swe >= MIN_VISIBLE_SWE_MM) & ~ski
        scores.update(
            {
                "snow_area_km2": round(float(outside_ski.sum()) * cell_km2, 2),
                "members": float(len(members)),
                "ski_resort_area_km2": round(ski_km2, 2),
                "swe_mm_max": round(float(median_swe.max()), 1),
            }
        )
        save_state(storage, day, swe, depth, signature)
        result: dict[str, Any] = {"date": day.isoformat(), "flags": flags, "scores": scores, "published": False}
        if (median_swe >= MIN_VISIBLE_SWE_MM).any():
            with tempfile.TemporaryDirectory(prefix="snow-model-") as tmp:
                files = write_products(Path(tmp), static, median_swe, median_depth)
                for layer, units, value_range in (("swe", "mm", SWE_RANGE), ("snow_depth", "m", DEPTH_RANGE)):
                    meta: dict[str, Any] = {
                        "source_ids": source_ids,
                        "bands": [layer],
                        "units": [units],
                        "value_range": [value_range],
                        "code_version": version,
                        "prior_state": prior,
                        "qa": {"flags": flags, "scores": scores},
                    }
                    publish(layer, day.isoformat(), files[layer], meta, storage)
            result["published"] = True
        else:
            log(f"{day}: no modelled snow above {MIN_VISIBLE_SWE_MM:g} mm, nothing published")
        prior = state_digest(swe, depth)
        results.append(result)
        false_before = scores.get("false_snow_before_insertion_pct")
        note = "" if false_before is None else f", false snow before insertion {false_before} %"
        log(f"{day} snow {scores['snow_area_km2']} km2, max {scores['swe_mm_max']} mm{note}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--target", choices=("staging", "prod"), required=True)
    parser.add_argument("--region", type=Path, default=Path("regions/sierra-nevada.json"))
    parser.add_argument("--calibration", type=Path, default=Path("regions/sierra-nevada.snow-calibration.json"))
    parser.add_argument("--cache", type=Path, default=Path("snow-cache"))
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error("--end is before --start")
    region = load_region(args.region)
    settings = merged_settings(region)
    parameters = operational_members(args.calibration, settings["ensemble"]["operational_members"])
    static = Static(region, settings)
    storage = storage_from_env(args.target)
    version = code_version()
    for season in seasons(args.start, args.end):
        run_season(static, settings, parameters, season, storage, args.cache, version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
