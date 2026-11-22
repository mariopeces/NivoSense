"""Runs of the snow model v2 smoothers on real data: twin experiments, hold-out blocks, the smoke run and the tuning.

    python -m scripts.snow_v2_assimilation twin-pbs --water-year 2025
    python -m scripts.snow_v2_assimilation twin-es-mda --water-year 2025 --members 300 --n-corr 3
    python -m scripts.snow_v2_assimilation holdout --water-year 2025
    python -m scripts.snow_v2_assimilation smoke --water-year 2027 --last-day 2026-11-20
    python -m scripts.snow_v2_assimilation tune --first-year 2020 --last-year 2026

Forcing is fetched from Open-Meteo (cached in --cache). The Sentinel-2 class fractions come from the `snow_obs`
entries of the prod catalogue (DATA_BUCKET and DATA_PREFIX set, read only) or, without them, from the copy
already mirrored under --cache/catalog.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from pipelines.snow_model.ensemble import weighted_quantiles
from pipelines.snow_model_v2 import assimilation as a
from pipelines.snow_model_v2 import tuning
from pipelines.snow_model_v2.contract import EnsembleRun, MemberParameters, sample_parameters
from pipelines.snow_model_v2.engine import run_ensemble
from pipelines.snow_model_v2.experiments import Season, load_season
from pipelines.snow_model_v2.holdout import split
from pipelines.snow_model_v2.observations import Observations
from pipelines.snow_model_v2.twin import run_twin, score_twin, truth_observations

CREST_BOX = (-3.42, -3.30, 37.01, 37.07)  # lon min, lon max, lat min, lat max
TRUTH_SEED = 7001
WORKERS = max(1, (os.cpu_count() or 2) - 2)


def observation_days(season: Season) -> list[int]:
    return [int(i) for i in season.observations.day_index(season.forcing.days)]


def twin_pbs(args: argparse.Namespace) -> None:
    season = load_season(args.water_year, None, args.cache)
    storms = season.forcing.storm_count
    days = observation_days(season)
    prior = run_ensemble(
        season.region.domain,
        season.forcing,
        sample_parameters(args.members, args.water_year, storm_count=storms),
        days,
        WORKERS,
    )
    truth = run_ensemble(
        season.region.domain,
        season.forcing,
        sample_parameters(args.truths, TRUTH_SEED, storm_count=storms),
        days,
        WORKERS,
    )
    for n_corr in args.n_corr:
        results = [
            run_twin(prior, truth, i, season.observations, season.forcing.days, season.region.domain, n_corr, 100 + i)
            for i in range(args.truths)
        ]
        for i, r in enumerate(results):
            print(
                f"n_corr {n_corr} truth {i}: b0 {r.truth_b0:.2f} -> {r.post_b0_mean:.2f} "
                f"[{r.post_b0_p10:.2f}, {r.post_b0_p90:.2f}] dT {r.truth_dT:+.2f} -> {r.post_dT_mean:+.2f} "
                f"ess {r.ess:.0f} swe coverage {r.swe_coverage:.2f} rmse {r.swe_rmse_mm:.0f}/{r.prior_swe_rmse_mm:.0f}"
            )
        print(
            f"n_corr {n_corr}: b0 within 10% on {sum(r.b0_error < 0.10 for r in results)}/{args.truths}, "
            f"mean swe coverage {np.mean([r.swe_coverage for r in results]):.2f}"
        )


def forward_runner(
    season: Season, days: list[int], observations: Observations, runs: list[EnsembleRun]
) -> Callable[[MemberParameters], np.ndarray]:
    def forward(parameters: MemberParameters) -> np.ndarray:
        runs.append(run_ensemble(season.region.domain, season.forcing, parameters, days, WORKERS))
        return a.predicted_fractions(runs[-1], observations, season.forcing.days)

    return forward


def twin_es_mda(args: argparse.Namespace) -> None:
    season = load_season(args.water_year, None, args.cache)
    storms = season.forcing.storm_count
    days = observation_days(season)
    domain, forcing = season.region.domain, season.forcing
    prior_parameters = sample_parameters(args.members, args.water_year, storm_count=storms)
    prior = run_ensemble(domain, forcing, prior_parameters, days, WORKERS)
    truth = run_ensemble(domain, forcing, sample_parameters(args.truths, TRUTH_SEED, storm_count=storms), days, WORKERS)
    equal = np.full(args.members, 1.0 / args.members)
    for i in args.only or range(args.truths):
        observations = truth_observations(truth, i, season.observations, forcing.days, 100 + i)
        runs: list[EnsembleRun] = []
        forward = forward_runner(season, days, observations, runs)
        posterior, predicted = a.es_mda(prior_parameters, forward, observations, n_corr=args.n_corr[0], seed=i)
        r = score_twin(runs[-1], equal, predicted, prior, truth, i, observations, domain, 100 + i, args.members, 1.0)
        print(
            f"es-mda n_corr {args.n_corr[0]} truth {i}: b0 {r.truth_b0:.2f} -> {r.post_b0_mean:.2f} "
            f"[{r.post_b0_p10:.2f}, {r.post_b0_p90:.2f}] dT {r.truth_dT:+.2f} -> {r.post_dT_mean:+.2f} "
            f"swe coverage {r.swe_coverage:.2f} rmse {r.swe_rmse_mm:.0f}/{r.prior_swe_rmse_mm:.0f}",
            flush=True,
        )


def holdout(args: argparse.Namespace) -> None:
    season = load_season(args.water_year, None, args.cache)
    start = date(args.water_year - 1, 10, 1)
    train, test = split(season.observations, start)
    days = observation_days(season)
    params = sample_parameters(args.members, args.water_year, storm_count=season.forcing.storm_count)
    run = run_ensemble(season.region.domain, season.forcing, params, days, WORKERS)
    train_predicted = a.predicted_fractions(run, train, season.forcing.days)
    test_predicted = a.predicted_fractions(run, test, season.forcing.days)
    equal = np.full(args.members, 1.0 / args.members)
    print(f"train {len(train.days)} dates, held out {len(test.days)} dates")
    print("prior", a.reliability(test_predicted, test, equal), "crps", a.crps(test_predicted, test, equal))
    for n_corr in args.n_corr:
        weights = a.pbs_weights(a.cost(train_predicted, train, n_corr))
        print(
            f"PBS n_corr {n_corr} ess {weights.ess:.1f}",
            a.reliability(test_predicted, test, weights.weights),
            "crps",
            a.crps(test_predicted, test, weights.weights),
        )


def smoke(args: argparse.Namespace) -> None:
    last_day = date.fromisoformat(args.last_day)
    season = load_season(args.water_year, last_day, args.cache)
    observations = season.observations
    print("observation dates", [d.isoformat() for d in observations.days])
    params = sample_parameters(args.members, args.water_year, storm_count=season.forcing.storm_count)
    run = run_ensemble(season.region.domain, season.forcing, params, observation_days(season), WORKERS)
    predicted = a.predicted_fractions(run, observations, season.forcing.days)
    weights = a.pbs_weights(a.cost(predicted, observations, args.n_corr[0]))
    print(f"PBS ess {weights.ess:.1f} lambda {weights.strength:.4f} usable data {int(observations.usable.sum())}")
    print(a.format_table(a.posterior_table(params, weights.weights)))
    print("reliability", a.reliability(predicted, observations, weights.weights))
    region = season.region
    rows, columns = np.divmod(region.cell_index, region.grid.width)
    from rasterio.warp import transform

    lon, lat = transform(
        region.grid.crs,
        "EPSG:4326",
        (region.grid.left + (columns + 0.5) * region.grid.resolution).tolist(),
        (region.grid.top - (rows + 0.5) * region.grid.resolution).tolist(),
    )
    lon, lat = np.array(lon), np.array(lat)
    box = (
        (lon >= CREST_BOX[0])
        & (lon <= CREST_BOX[1])
        & (lat >= CREST_BOX[2])
        & (lat <= CREST_BOX[3])
        & ~region.ski_cells
    )
    index = region.domain.class_of_cell[box]
    for label, w in (("prior", np.full(args.members, 1.0 / args.members)), ("posterior", weights.weights)):
        q = weighted_quantiles(run.swe[:, :, -1], w, [0.5, 0.9])
        median = np.where(index >= 0, q[0][np.maximum(index, 0)], 0.0)
        p90 = np.where(index >= 0, q[1][np.maximum(index, 0)], 0.0)
        print(
            f"{label} crest box on {last_day}: {int(box.sum())} cells outside the resort, "
            f"{int((median > 0.5).sum())} with median SWE above 0.5 mm, {int((p90 > 0.5).sum())} with p90 above 0.5 mm"
        )


def tune(args: argparse.Namespace) -> None:
    seasons = []
    for year in range(args.first_year, args.last_year + 1):
        season = load_season(year, None, args.cache)
        if len(season.observations.days) < args.min_dates:
            print(f"water year {year}: {len(season.observations.days)} dates, skipped")
            continue
        params = sample_parameters(args.members, year, tuning.BASE_PRIORS, storm_count=season.forcing.storm_count)
        run = run_ensemble(season.region.domain, season.forcing, params, observation_days(season), WORKERS)
        predicted = a.predicted_fractions(run, season.observations, season.forcing.days)
        seasons.append(tuning.SeasonEnsemble(year, run, predicted, season.observations))
        print(f"water year {year}: {len(season.observations.days)} dates", flush=True)
    years = [s.water_year for s in seasons]
    table = tuning.score_table(seasons)
    folds = tuning.leave_one_season_out(table, years)
    for fold in folds:
        print(fold)
    best, score = tuning.best_candidate(table, years)
    payload = {
        "schema_version": 1,
        "region": "sierra-nevada",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "leave-one-season-out CRPS of the prior predictive fSCA, importance reweighting of a wide base "
        "ensemble (pipelines/snow_model_v2/tuning.py)",
        "water_years": years,
        "priors": {"b0_median": best.b0_median, "b0_cv": best.b0_cv, "dT_sd": best.dT_sd},
        "all_season_crps": score,
        "folds": folds,
        "fold_spread": tuning.fold_spread(folds),
    }
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["fold_spread"], indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["twin-pbs", "twin-es-mda", "holdout", "smoke", "tune"])
    parser.add_argument("--water-year", type=int, default=2025)
    parser.add_argument("--last-day", default="2026-11-20")
    parser.add_argument("--members", type=int, default=1000)
    parser.add_argument("--truths", type=int, default=10)
    parser.add_argument("--only", type=int, nargs="*")
    parser.add_argument("--n-corr", type=float, nargs="+", default=[a.N_CORR])
    parser.add_argument("--first-year", type=int, default=2020)
    parser.add_argument("--last-year", type=int, default=2026)
    parser.add_argument("--min-dates", type=int, default=8)
    parser.add_argument("--cache", type=Path, default=Path(".cache/snow-v2"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    {"twin-pbs": twin_pbs, "twin-es-mda": twin_es_mda, "holdout": holdout, "smoke": smoke, "tune": tune}[args.command](
        args
    )


if __name__ == "__main__":
    main()
