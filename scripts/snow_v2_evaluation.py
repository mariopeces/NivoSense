"""Evaluation of the snow model v2 against v1 and against in-situ references (results in docs/snow-evaluation.md).

    python -m scripts.snow_v2_evaluation sentinel --water-years 2024 2025 2026
    python -m scripts.snow_v2_evaluation camera
    python -m scripts.snow_v2_evaluation forcing

sentinel: v1 (prod catalogue), the v2 prior ensemble median and the v2 particle batch smoother (PBS) against
    Sentinel-2 snow presence, SWE >= 5 mm, with the rules of qa/validation/presence.py. The PBS is scored held out
    (leave-date-blocks-out, 12 day blocks in 3 folds) and, for reference only, in sample.
camera: v2 ensemble driven by ERA5 against the Poqueira camera snow depth and cover, 2009 to 2013, prior and
    MODIS-fSCA PBS, with simple baselines.
forcing: ERA5 and IFS precipitation and temperature against the Guadalfeo stations.

Forcing comes from Open-Meteo (cached in --cache); Sentinel-2 class fractions from the mirrored catalogue under
--cache/catalog; v1 from the public prod bucket; references from PANGAEA and the Planetary Computer (qa-cache/).
Outputs go to docs/snow-evaluation/ (CSV and JSON). Seeds are fixed: ensembles use `season_seed`, resampling
uses seed 0.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from pipelines.catalog.storage import LocalStorage
from pipelines.snow_model import insertion
from pipelines.snow_model.outputs import MIN_VISIBLE_SWE_MM
from pipelines.snow_model_v2 import assimilation as a
from pipelines.snow_model_v2.assimilation import systematic_resample
from pipelines.snow_model_v2.contract import MemberParameters, Priors, sample_parameters
from pipelines.snow_model_v2.domain import aspect_classes, cellwise_domain
from pipelines.snow_model_v2.engine import run_ensemble
from pipelines.snow_model_v2.experiments import Season, load_season
from pipelines.snow_model_v2.forcing import HourlyForcing, fetch_season_forcing, to_season_forcing
from pipelines.snow_model_v2.observations import Observations, observation_error
from pipelines.snow_model_v2.region_domain import RegionDomain
from qa.validation import evaluation as ev
from qa.validation import metrics, modis, pangaea
from qa.validation.baselines import HttpStorage, catalogue_dates, read_layer

WORKERS = max(1, (os.cpu_count() or 2) - 2)
OUT = Path("docs/snow-evaluation")
MODELS = ("v1", "prior", "pbs_heldout", "pbs_insample", "prior_fsca", "pbs_heldout_fsca")
FSCA_SNOW = 0.5  # a Sentinel-2 cell holds snow when at least half of its pixels are snow (insertion.cell_state)


@dataclass
class DateScore:
    day: date
    fold: int
    v1_inserted: bool | None
    cells: np.ndarray  # flat indices into the model cell list of the decided cells
    truth: np.ndarray
    pred: dict[str, np.ndarray]
    prob: dict[str, np.ndarray]


def _pooled(entries: list[DateScore], model: str, elevation: np.ndarray) -> dict[str, float]:
    selected = [e for e in entries if model in e.pred]
    if not selected:
        return {}
    pred = np.concatenate([e.pred[model] for e in selected])
    truth = np.concatenate([e.truth for e in selected])
    out = ev.summarise(pred, truth)
    lines = [
        (ev.snow_line(elevation[e.cells], e.pred[model]) - ev.snow_line(elevation[e.cells], e.truth)) for e in selected
    ]
    out["dates"] = float(len(selected))
    out["snow_line_error_mean"] = float(np.nanmean(lines)) if np.isfinite(lines).any() else float("nan")
    out["snow_line_error_mae"] = float(np.nanmean(np.abs(lines))) if np.isfinite(lines).any() else float("nan")
    return out


def run_sentinel_season(water_year: int, args: argparse.Namespace, v1_storage: HttpStorage) -> dict:
    season: Season = load_season(water_year, None, args.cache)
    region, domain, forcing = season.region, season.region.domain, season.forcing
    observations = season.observations
    obs_days = [int(i) for i in observations.day_index(forcing.days)]
    parameters = sample_parameters(args.members, water_year, storm_count=forcing.storm_count)
    run = run_ensemble(domain, forcing, parameters, obs_days, WORKERS)
    stored = {int(d): i for i, d in enumerate(run.day_index)}
    start = date(water_year - 1, 10, 1)
    fold_of = ev.block_folds(observations.days, start, args.block_days, args.folds)

    equal = np.full(args.members, 1.0 / args.members)
    predicted = a.predicted_fractions(run, observations, forcing.days)
    insample = a.pbs_weights(a.cost(predicted, observations, a.N_CORR))
    fold_weights = []
    for fold in range(args.folds):
        train = observations.select(fold_of != fold)
        fold_weights.append(a.pbs_weights(a.cost(a.predicted_fractions(run, train, forcing.days), train, a.N_CORR)))

    local = LocalStorage(args.cache / "catalog")
    published = set(catalogue_dates(v1_storage, "swe"))
    cell_index = region.cell_index
    in_class = domain.class_of_cell >= 0
    elevation = region.elevation
    entries: list[DateScore] = []
    harness_v1: dict[date, tuple[np.ndarray, np.ndarray]] = {}
    ski_grid = insertion_ski(region)
    for k, day in enumerate(observations.days):
        observation = insertion.load_observation(local, day.isoformat())
        if observation is None:
            continue
        state = insertion.cell_state(observation, region.grid)
        valid = state.valid.ravel()[cell_index]
        decided = valid & ~region.ski_cells & in_class
        if not decided.any():
            continue
        truth_all = state.snow.ravel()[cell_index]
        position = stored[obs_days[k]]
        pred: dict[str, np.ndarray] = {}
        prob: dict[str, np.ndarray] = {}
        swe = run.swe[:, :, position]
        for name, w in (
            ("prior", equal),
            ("pbs_insample", insample.weights),
            ("pbs_heldout", fold_weights[fold_of[k]].weights),
        ):
            median = ev.weighted_interval(swe, w, (0.5,))[0]
            pred[name] = domain.upsample(median)[decided] >= MIN_VISIBLE_SWE_MM
            if name in ("prior", "pbs_heldout"):
                median_fsca = ev.weighted_interval(run.f_sca[:, :, position], w, (0.5,))[0]
                pred[f"{name}_fsca"] = domain.upsample(median_fsca)[decided] >= FSCA_SNOW
            share = (w[:, None] * (swe >= MIN_VISIBLE_SWE_MM)).sum(axis=0)
            prob[name] = domain.upsample(share.astype("float32"))[decided]
        inserted: bool | None = None
        if day in published:
            raster = read_layer(v1_storage, "swe", day)
            if raster is not None:
                if raster[0].shape != (region.grid.height, region.grid.width):
                    raise RuntimeError("v1 swe grid differs from the model grid")
                pred["v1"] = (raster[0].ravel()[cell_index] >= MIN_VISIBLE_SWE_MM)[decided]
                inserted = "observation_inserted" in raster[3]["qa"]["flags"]
                # Harness rule: every valid cell of the grid, ski resort out, including cells outside the domain.
                whole = state.valid & ~ski_grid
                harness_v1[day] = ((raster[0] >= MIN_VISIBLE_SWE_MM)[whole], state.snow[whole])
        entries.append(
            DateScore(day, int(fold_of[k]), inserted, np.flatnonzero(decided), truth_all[decided], pred, prob)
        )

    result: dict = {
        "water_year": water_year,
        "members": args.members,
        "dates": len(entries),
        "v1_dates": sum("v1" in e.pred for e in entries),
        "v1_dates_inserted": sum(e.v1_inserted is True for e in entries),
        "ess_insample": insample.ess,
        "ess_folds": [w.ess for w in fold_weights],
        "folds": args.folds,
        "block_days": args.block_days,
    }
    subsets = {
        "all_dates": entries,
        "v1_dates": [e for e in entries if "v1" in e.pred],
        "v1_dates_not_inserted": [e for e in entries if "v1" in e.pred and e.v1_inserted is False],
    }
    summary: dict[str, dict] = {}
    for label, subset in subsets.items():
        summary[label] = {m: _pooled(subset, m, elevation) for m in MODELS if any(m in e.pred for e in subset)}
    result["pooled"] = summary
    if harness_v1:
        whole_pred = np.concatenate([p for p, _ in harness_v1.values()])
        whole_truth = np.concatenate([t for _, t in harness_v1.values()])
        result["v1_harness_whole_grid"] = ev.summarise(whole_pred, whole_truth)

    # Probability of snow (P(SWE >= 5 mm) of the ensemble): Brier score, held-out and prior.
    result["brier"] = {
        m: float(np.mean(np.concatenate([(e.prob[m] - e.truth) ** 2 for e in entries])))
        for m in ("prior", "pbs_heldout")
    }

    for label, subset in subsets.items():
        if not subset:
            continue
        truth = np.concatenate([e.truth for e in subset])
        z = np.concatenate([elevation[e.cells] for e in subset])
        names = [m for m in MODELS if all(m in e.pred for e in subset)]
        table = ev.band_table({m: np.concatenate([e.pred[m] for e in subset]) for m in names}, truth, z)
        table.to_csv(args.out / f"sentinel-wy{water_year}-bands-{label}.csv", index=False, float_format="%.4f")
    rows = []
    for e in entries:
        row: dict[str, object] = {"date": e.day, "fold": e.fold, "v1_inserted": e.v1_inserted, "cells": len(e.truth)}
        row["obs_snow_share"] = float(e.truth.mean())
        for m in MODELS:
            if m in e.pred:
                row[f"{m}_f1"] = ev.summarise(e.pred[m], e.truth)["f1"]
                row[f"{m}_snow_line_error"] = ev.snow_line(elevation[e.cells], e.pred[m]) - ev.snow_line(
                    elevation[e.cells], e.truth
                )
        rows.append(row)
    pd.DataFrame(rows).to_csv(args.out / f"sentinel-wy{water_year}-dates.csv", index=False, float_format="%.4f")
    (args.out / f"sentinel-wy{water_year}.json").write_text(
        json.dumps(result, indent=2, default=float) + "\n", encoding="utf-8"
    )
    return result


def insertion_ski(region: RegionDomain) -> np.ndarray:
    """Ski resort mask on the whole grid (the harness rule), rasterised from the same file."""
    from pipelines.snow_model.run import rasterize_geometries
    from qa.validation.presence import SKI_RESORT

    return rasterize_geometries(SKI_RESORT, region.grid, all_touched=True)


def sentinel(args: argparse.Namespace) -> None:
    storage = HttpStorage()
    for year in args.water_years:
        result = run_sentinel_season(year, args, storage)
        print(json.dumps(result, indent=2, default=float), flush=True)


CAMERA_YEARS = (2010, 2011, 2012, 2013)
CAMERA_MEMBERS = 5000
MODIS_PIXEL_CELLS = 25  # one 500 m MODIS pixel is 25 model cells of 100 m
MODIS_N_CORR = (3.0, 10.0)
ERA5_CELL_DEG = 0.25


def camera_cell(cache: Path) -> dict:
    """The 100 m model cell holding the camera: elevation, slope, aspect and radiation index from the cached DEM,
    and the mean DEM elevation of the ERA5 0.25 degree cell the camera falls in."""
    from rasterio.warp import transform

    from pipelines.region import load_region
    from pipelines.snow_model.dem import slope_aspect
    from pipelines.snow_model.grid import build_grid
    from pipelines.snow_model.radiation import radiation_index

    region = load_region(Path("regions/sierra-nevada.json"))
    grid = build_grid(region.bbox, 100)
    dem = np.load(cache / f"dem-{region.id}-{grid.signature()}.npy")
    lat, lon = cast(float, pangaea.POQUEIRA_SITE["lat"]), cast(float, pangaea.POQUEIRA_SITE["lon"])
    x, y = transform("EPSG:4326", grid.crs, [lon], [lat])
    col, row = int((x[0] - grid.left) // grid.resolution), int((grid.top - y[0]) // grid.resolution)
    slope, aspect = slope_aspect(dem, grid.resolution)
    one = (slice(row, row + 1), slice(col, col + 1))
    centre_lat, centre_lon = round(lat / ERA5_CELL_DEG) * ERA5_CELL_DEG, round(lon / ERA5_CELL_DEG) * ERA5_CELL_DEG
    xs, ys = transform(
        "EPSG:4326",
        grid.crs,
        [centre_lon - ERA5_CELL_DEG / 2, centre_lon + ERA5_CELL_DEG / 2],
        [centre_lat + ERA5_CELL_DEG / 2, centre_lat - ERA5_CELL_DEG / 2],
    )
    c0, c1 = sorted(int((v - grid.left) // grid.resolution) for v in xs)
    r0, r1 = sorted(int((grid.top - v) // grid.resolution) for v in ys)
    window = dem[max(r0, 0) : r1 + 1, max(c0, 0) : c1 + 1]
    return {
        "lat": lat,
        "lon": lon,
        "row": row,
        "col": col,
        "elevation": float(dem[row, col]),
        "camera_elevation": cast(float, pangaea.POQUEIRA_SITE["elevation_m"]),
        "slope_deg": float(np.degrees(slope[row, col])),
        "aspect_deg": float(np.degrees(aspect[row, col])),
        "radiation": radiation_index(lat, slope[one].ravel(), aspect[one].ravel()),
        "aspect_class": int(aspect_classes(slope[one].ravel(), aspect[one].ravel())[0]),
        "era5_cell_centre": (centre_lat, centre_lon),
        "era5_cell_mean_dem": float(np.nanmean(window)),
        "era5_cell_dem_share": float(np.isfinite(window).mean()),
    }


def default_member(water_year: int, storms: int) -> MemberParameters:
    """One member at the middle of every prior range (b0 = 1, no temperature bias, no storm noise): the
    deterministic default-parameter degree-day run used as a baseline."""
    priors = Priors()

    def mid(bounds: tuple[float, float]) -> np.ndarray:
        return np.array([(bounds[0] + bounds[1]) / 2])

    return MemberParameters(
        water_year,
        np.array([priors.b0_median]),
        mid(priors.g),
        np.zeros(1),
        mid(priors.L),
        mid(priors.Ts),
        mid(priors.DDF),
        mid(priors.rad),
        mid(priors.beta),
        np.ones(1),
        np.zeros((1, storms)),
    )


def modis_observations(frame: pd.DataFrame, days: list[date]) -> Observations:
    """Clear-day MODIS fSCA of the camera pixel as the observations of a one-class domain; the error is the
    one of `observation_error` for a pool of 25 cells (one 500 m pixel)."""
    daily = modis.combine_daily(frame)
    daily = daily[(daily["qc"] == "ok") & daily["date"].dt.date.isin(set(days))]
    n = np.full((1, len(daily)), float(MODIS_PIXEL_CELLS))
    return Observations(
        [d.date() for d in daily["date"]],
        daily["fsca"].to_numpy(dtype="float64")[None],
        n,
        observation_error(n),
        np.zeros(n.shape),
    )


def melt_out_errors(dates: pd.Series, members: np.ndarray, observed: np.ndarray) -> dict:
    """Melt-out (first bare day after the last snow day above 1 cm) of the camera and of every member over the
    camera days of one season; errors are member minus camera in days."""
    reference = metrics.melt_out_date(dates, observed, metrics.DEPTH_SNOW_M)
    errors = np.array(
        [
            metrics.melt_out_error_days(metrics.melt_out_date(dates, member, metrics.DEPTH_SNOW_M), reference)
            for member in members
        ]
    )
    finite = errors[np.isfinite(errors)]
    return {
        "camera": reference.date.isoformat() if reference else None,
        "camera_last_snow": reference.last_snow.isoformat() if reference else None,
        "members": int(errors.size),
        "members_with_melt_out": int(finite.size),
        "p10": float(np.percentile(finite, 10)) if finite.size else None,
        "p50": float(np.percentile(finite, 50)) if finite.size else None,
        "p90": float(np.percentile(finite, 90)) if finite.size else None,
    }


def station_correction(hourly: HourlyForcing, station: pd.DataFrame) -> tuple[HourlyForcing, dict[str, float]]:
    """ERA5 forcing of one season corrected toward the PG2 gauge, which stands at the camera (37.029 N, -3.324 E):
    temperature shifted by the mean station minus model daily bias, precipitation scaled by the ratio of the
    station to the model total, both over the days the station has a value. Returns the forcing and the two
    numbers. A diagnostic of how much of the depth error is forcing: the gauge undercatches snow, so the scaled
    precipitation is, if anything, low."""
    from dataclasses import replace

    modelled = daily_model(hourly, 0)
    precipitation = station[station["variable"] == "precipitation"][["date", "value"]]
    temperature = station[station["variable"] == "air_temperature"][["date", "value"]]
    rain = modelled.merge(precipitation, on="date").dropna()
    heat = modelled.merge(temperature, on="date").dropna()
    scale = float(rain["value"].sum() / rain["precip"].sum())
    shift = float((heat["value"] - heat["temp"]).mean())
    corrected = replace(
        hourly,
        temperature=(hourly.temperature + shift).astype("float32"),
        precipitation=(hourly.precipitation * scale).astype("float32"),
    )
    return corrected, {
        "temperature_shift_c": shift,
        "precipitation_scale": scale,
        "rain_days": int(len(rain)),
        "temperature_days": int(len(heat)),
    }


def camera_season(
    wy: int,
    forcing_elevation: float,
    site: dict,
    table: pd.DataFrame,
    modis_frame: pd.DataFrame,
    args: argparse.Namespace,
    station: pd.DataFrame | None = None,
) -> tuple[dict, pd.DataFrame]:
    # The forcing adapter names a water year by its start year; this script, like the catalogue, by its end year.
    hourly = fetch_season_forcing(
        wy - 1, [(site["lat"], site["lon"])], [forcing_elevation], args.cache, "era5", pause=1.0
    )
    correction = None
    if station is not None:
        hourly, correction = station_correction(hourly, station)
    forcing = to_season_forcing(hourly)
    domain = cellwise_domain(
        np.array([site["elevation"]]),
        np.zeros((1, 1)),
        np.ones((1, 1)),
        site["radiation"],
        100.0**2,
        np.array([site["aspect_class"]]),
    )
    days = forcing.days
    every_day = list(range(len(days)))
    parameters = sample_parameters(CAMERA_MEMBERS, wy, storm_count=forcing.storm_count)
    run = run_ensemble(domain, forcing, parameters, every_day, 1)
    default = run_ensemble(domain, forcing, default_member(wy, forcing.storm_count), every_day, 1)
    depth, fsca = run.depth[:, 0, :], run.f_sca[:, 0, :]
    index = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    observed = {
        v: table[(table["variable"] == v) & (table["qc"] == "ok")].set_index("date")["value"].reindex(index).to_numpy()
        for v in ("snow_depth", "snow_cover_fraction")
    }
    obs_depth, obs_cover = observed["snow_depth"], observed["snow_cover_fraction"]
    valid = np.isfinite(obs_depth)

    observations = modis_observations(modis_frame, days)
    predicted = a.predicted_fractions(run, observations, days)
    weights: dict[str, np.ndarray] = {"prior": np.full(CAMERA_MEMBERS, 1.0 / CAMERA_MEMBERS)}
    ess = {}
    for n_corr in MODIS_N_CORR:
        posterior = a.pbs_weights(a.cost(predicted, observations, n_corr))
        weights[f"pbs_ncorr{n_corr:g}"] = posterior.weights
        ess[f"pbs_ncorr{n_corr:g}"] = posterior.ess
    weights["pbs"] = weights["pbs_ncorr3"]

    season: dict = {"modis_dates": len(observations.days), "ess": ess, "camera_days": int(valid.sum())}
    for name, w in weights.items():
        season[name] = ev.depth_scores(depth[:, valid], w, obs_depth[valid])
        median_cover = ev.weighted_interval(fsca[:, valid], w, (0.5,))[0]
        season[name]["cover"] = metrics.depth_metrics(median_cover, obs_cover[valid])
    season["default_run"] = {
        **metrics.depth_metrics(default.depth[0, 0, valid], obs_depth[valid]),
        "cover": metrics.depth_metrics(default.f_sca[0, 0, valid], obs_cover[valid]),
    }
    season["station_correction"] = correction
    season["zero_depth_rmse"] = float(np.sqrt(np.mean(obs_depth[valid] ** 2)))
    dates_valid = pd.Series(index[valid])
    posterior_members = depth[systematic_resample(weights["pbs"], 1000, 0)][:, valid]
    season["melt_out"] = {
        "prior": melt_out_errors(dates_valid, depth[:1000, valid], obs_depth[valid]),
        "pbs": melt_out_errors(dates_valid, posterior_members, obs_depth[valid]),
        "default_run": melt_out_errors(dates_valid, default.depth[:, 0, valid], obs_depth[valid]),
    }
    peak = depth.max(axis=1)
    season["peak_depth_m"] = {
        "camera": float(np.nanmax(obs_depth)),
        "prior_p10_p50_p90": [float(v) for v in np.percentile(peak, [10, 50, 90])],
        "pbs_p10_p50_p90": [float(v) for v in ev.weighted_interval(peak[:, None], weights["pbs"])[:, 0]],
        "default_run": float(default.depth[0, 0].max()),
    }
    season["parameters"] = {
        "era5_precipitation_mm": float(hourly.precipitation.sum()),
        "prior_b0_mean": float(parameters.b0.mean()),
        "pbs_b0_mean": float(np.sum(weights["pbs"] * parameters.b0)),
        "pbs_dT_mean": float(np.sum(weights["pbs"] * parameters.dT)),
        "era5_cell_lat_lon_elevation": [
            float(hourly.cell_lat[0]),
            float(hourly.cell_lon[0]),
            float(hourly.cell_elevation[0]),
        ],
    }
    frame = pd.DataFrame({"date": index, "camera_depth_m": obs_depth, "camera_cover": obs_cover})
    for name in ("prior", "pbs"):
        q = ev.weighted_interval(depth, weights[name])
        frame[f"{name}_depth_p10"], frame[f"{name}_depth_p50"], frame[f"{name}_depth_p90"] = q
        frame[f"{name}_cover_p50"] = ev.weighted_interval(fsca, weights[name], (0.5,))[0]
    frame["default_depth"] = default.depth[0, 0, :]
    frame["default_cover"] = default.f_sca[0, 0, :]
    return season, frame


def pooled_camera(frame: pd.DataFrame) -> dict:
    keep = frame["camera_depth_m"].notna()
    seasons = frame["date"].dt.year + (frame["date"].dt.month >= 10)
    frame = frame.assign(climatology_depth=ev.climatology(frame["date"], frame["camera_depth_m"], seasons).to_numpy())
    obs = frame.loc[keep, "camera_depth_m"]
    out: dict = {}
    for name, column in (
        ("prior", "prior_depth_p50"),
        ("pbs", "pbs_depth_p50"),
        ("default_run", "default_depth"),
        ("climatology_loso", "climatology_depth"),
    ):
        out[name] = metrics.depth_metrics(frame.loc[keep, column], obs)
    out["zero_depth_rmse"] = float(np.sqrt(np.mean(obs**2)))
    for name in ("prior", "pbs"):
        lo, hi = frame[f"{name}_depth_p10"], frame[f"{name}_depth_p90"]
        snowy = keep & ((frame["camera_depth_m"] > metrics.DEPTH_SNOW_M) | (hi > metrics.DEPTH_SNOW_M))
        out[name]["coverage80"] = metrics.interval_coverage(lo[keep], hi[keep], obs)
        out[name]["coverage80_snow_days"] = metrics.interval_coverage(
            lo[snowy], hi[snowy], frame.loc[snowy, "camera_depth_m"]
        )
        out[name]["snow_days"] = float(snowy.sum())
        out[name]["cover"] = metrics.depth_metrics(
            frame.loc[keep, f"{name}_cover_p50"], frame.loc[keep, "camera_cover"]
        )
    out["default_run"]["cover"] = metrics.depth_metrics(
        frame.loc[keep, "default_cover"], frame.loc[keep, "camera_cover"]
    )
    return out


def modis_vs_camera(table: pd.DataFrame, modis_frame: pd.DataFrame) -> dict:
    """How well the 500 m MODIS pixel stands for the camera plot: cover on the days both have a clear value, and
    the melt-out of both series (first bare day after the last day above 10 % cover) per water year."""
    cover = table[(table["variable"] == "snow_cover_fraction") & (table["qc"] == "ok")].set_index("date")["value"]
    daily = modis.combine_daily(modis_frame)
    satellite = daily[daily["qc"] == "ok"].set_index("date")["fsca"]
    both = pd.concat([cover.rename("camera"), satellite.rename("modis")], axis=1, sort=True).dropna()
    seasons = both.index.year + (both.index.month >= 10)
    out: dict = {
        "days": int(len(both)),
        "mean_camera": float(both["camera"].mean()),
        "mean_modis": float(both["modis"].mean()),
        "r": float(np.corrcoef(both["camera"], both["modis"])[0, 1]),
        "seasons": {},
    }
    for wy in sorted(set(seasons)):
        part = both[seasons == wy]
        camera_out = metrics.melt_out_date(part.index, part["camera"].to_numpy(), metrics.FSCA_SNOW)
        modis_out = metrics.melt_out_date(part.index, part["modis"].to_numpy(), metrics.FSCA_SNOW)
        out["seasons"][int(wy)] = {
            "days": int(len(part)),
            "bias_modis_minus_camera": float((part["modis"] - part["camera"]).mean()),
            "camera_melt_out": camera_out.date.isoformat() if camera_out else None,
            "modis_melt_out": modis_out.date.isoformat() if modis_out else None,
        }
    return out


def camera(args: argparse.Namespace) -> None:
    site = camera_cell(args.cache)
    print({k: v for k, v in site.items() if k != "radiation"}, flush=True)
    table = pangaea.load_poqueira(Path("qa-cache/pangaea/871706.tab"))
    modis_frame = pd.read_csv(Path("qa-cache/modis_fsca.csv"), parse_dates=["date"])
    pg2 = pangaea.load_guadalfeo(("PG2",), Path("qa-cache/pangaea/895236.zip"))
    pg2 = pg2[pg2["qc"] == "ok"]
    variants = {
        "cell_dem": (site["elevation"], None),
        "era5_cell_mean": (site["era5_cell_mean_dem"], None),
        "pg2_corrected": (site["elevation"], pg2),
    }
    summary: dict = {
        "site": {k: v for k, v in site.items() if k != "radiation"},
        "modis_vs_camera": modis_vs_camera(table, modis_frame),
        "variants": {},
    }
    for variant, (forcing_elevation, station) in variants.items():
        seasons, frames = {}, []
        for wy in CAMERA_YEARS:
            seasons[wy], frame = camera_season(wy, forcing_elevation, site, table, modis_frame, args, station)
            frames.append(frame)
            print(variant, wy, json.dumps(seasons[wy], default=float), flush=True)
        pooled = pd.concat(frames, ignore_index=True)
        summary["variants"][variant] = {
            "forcing_elevation": forcing_elevation,
            "seasons": seasons,
            "pooled": pooled_camera(pooled),
        }
        for name in ("prior", "pbs"):
            counts = np.array([seasons[wy][name]["n"] for wy in CAMERA_YEARS])
            crps = np.array([seasons[wy][name]["crps"] for wy in CAMERA_YEARS])
            summary["variants"][variant]["pooled"][name]["crps"] = float((counts * crps).sum() / counts.sum())
        pooled.to_csv(args.out / f"camera-daily-{variant}.csv", index=False, float_format="%.4f")
    (args.out / "camera.json").write_text(json.dumps(summary, indent=2, default=float) + "\n", encoding="utf-8")


ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
IFS_WATER_YEARS = (2016, 2017)  # adapter naming (start year): IFS archive starts 2017-01-01


def station_elevations(lat: list[float], lon: list[float]) -> list[float]:
    """90 m DEM elevation of each coordinate from the Open-Meteo elevation API; the Guadalfeo files carry none."""
    import urllib.parse
    import urllib.request

    query = urllib.parse.urlencode({"latitude": ",".join(map(str, lat)), "longitude": ",".join(map(str, lon))})
    with urllib.request.urlopen(f"{ELEVATION_URL}?{query}", timeout=60) as response:
        return [float(v) for v in json.load(response)["elevation"]]


def daily_model(hourly: HourlyForcing, station: int) -> pd.DataFrame:
    """Daily (UTC) precipitation sum and temperature mean of one forcing point."""
    from pipelines.snow_model_v2.forcing import daily_means, daily_totals

    days = pd.DatetimeIndex([pd.Timestamp(d) for d in hourly.days])
    return pd.DataFrame(
        {
            "date": days,
            "precip": daily_totals(hourly.precipitation)[station],
            "temp": daily_means(hourly.temperature)[station],
        }
    )


def forcing_check(args: argparse.Namespace) -> None:
    table = pangaea.load_guadalfeo(path=Path("qa-cache/pangaea/895236.zip"))
    names = list(pangaea.GUADALFEO_STATIONS)
    place = table.groupby("station")[["lat", "lon"]].first().loc[names]
    elevation = station_elevations(place["lat"].tolist(), place["lon"].tolist())
    points = list(zip(place["lat"], place["lon"]))
    print(dict(zip(names, elevation)), flush=True)
    coverage = pangaea.coverage(table)
    first_year = int(coverage["first"].min().year) - 1
    models: dict[str, dict[int, HourlyForcing]] = {"era5": {}, "ecmwf_ifs": {}}
    for start_year in range(first_year, 2018):
        models["era5"][start_year] = fetch_season_forcing(start_year, points, elevation, args.cache, "era5", pause=1.0)
    for start_year in IFS_WATER_YEARS:
        try:
            models["ecmwf_ifs"][start_year] = fetch_season_forcing(
                start_year, points, elevation, args.cache, "ecmwf_ifs", pause=1.0
            )
        except (RuntimeError, ValueError) as error:
            print("IFS", start_year, "not available:", error, flush=True)
    rows: list[dict] = []
    for model, seasons in models.items():
        for start_year, hourly in seasons.items():
            cell_elevation = hourly.cell_elevation
            for index, station in enumerate(names):
                modelled = daily_model(hourly, index)
                for variable, column in (("precipitation", "precip"), ("air_temperature", "temp")):
                    ref = table[(table["station"] == station) & (table["variable"] == variable) & (table["qc"] == "ok")]
                    ref = ref[["date", "value"]]
                    simulated = modelled[["date", column]].rename(columns={column: "value"})
                    if variable == "precipitation":
                        part = ev.annual_ratio(simulated, ref, min_days=30)
                        if part.empty:
                            continue
                        part = part[part["water_year"] == start_year + 1]
                        for row in part.to_dict("records"):
                            best = {}
                            for lag in (-1, 0, 1):
                                shifted = simulated.assign(date=simulated["date"] + pd.Timedelta(days=lag))
                                merged = shifted.merge(ref, on="date", suffixes=("_m", "_s")).dropna()
                                merged = merged[
                                    (merged["date"] >= pd.Timestamp(start_year, 10, 1))
                                    & (merged["date"] <= pd.Timestamp(start_year + 1, 9, 30))
                                ]
                                best[lag] = (
                                    float(np.corrcoef(merged["value_m"], merged["value_s"])[0, 1])
                                    if len(merged) > 30
                                    else float("nan")
                                )
                            rows.append(
                                {
                                    "model": model,
                                    "station": station,
                                    "variable": variable,
                                    **row,
                                    "daily_r_lag-1": best[-1],
                                    "daily_r_lag+1": best[1],
                                    "cell_elevation_m": float(cell_elevation[index]),
                                    "station_elevation_m": elevation[index],
                                }
                            )
                    else:
                        merged = simulated.merge(ref, on="date", suffixes=("_model", "_station")).dropna()
                        merged = merged[
                            (merged["date"] >= pd.Timestamp(start_year, 10, 1))
                            & (merged["date"] <= pd.Timestamp(start_year + 1, 9, 30))
                        ]
                        if len(merged) >= 30:
                            diff = merged["value_model"] - merged["value_station"]
                            rows.append(
                                {
                                    "model": model,
                                    "station": station,
                                    "variable": variable,
                                    "water_year": start_year + 1,
                                    "days": len(merged),
                                    "bias_c": float(diff.mean()),
                                    "rmse_c": float(np.sqrt((diff**2).mean())),
                                    "daily_r": float(np.corrcoef(merged["value_model"], merged["value_station"])[0, 1]),
                                    "cell_elevation_m": float(cell_elevation[index]),
                                    "station_elevation_m": elevation[index],
                                }
                            )
    frame = pd.DataFrame(rows)
    frame.to_csv(args.out / "forcing-check-by-year.csv", index=False, float_format="%.4f")
    print(frame.to_string(), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["sentinel", "camera", "forcing"])
    parser.add_argument("--water-years", type=int, nargs="+", default=[2024, 2025, 2026])
    parser.add_argument("--members", type=int, default=1000)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--block-days", type=int, default=ev.BLOCK_DAYS)
    parser.add_argument("--cache", type=Path, default=Path(".cache/snow-v2"))
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command == "sentinel":
        sentinel(args)
    elif args.command == "camera":
        camera(args)
    elif args.command == "forcing":
        forcing_check(args)


if __name__ == "__main__":
    main()
