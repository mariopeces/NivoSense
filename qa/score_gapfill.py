"""Scores the gap-filled snow cover by hiding real observations (README section 2, Q2).

    python -m qa.score_gapfill --target staging --start 2025-10-01 --end 2026-09-30 --out q2.json

Two families of test cases over the snow season of the range:
- cloud-mask transplant: the cloud mask of a cloudy date is laid on a clear date (observed on at
  least CLEAR_MIN_OBSERVED of the domain), and the day is filled without the hidden pixels;
- hidden runs: every run of 2 and of 3 consecutive observation dates is removed, and each of
  its days is filled from the rest.
A case is scored only on hidden pixels the observation saw (snow or no snow) that change state
within CHANGE_WINDOW_DAYS of the day in the full observation record, inside the domain and
outside the ski resort. The snow season is the span from the first to the last observation date
on which snow covers at least SEASON_MIN_SNOW_FRACTION of the observed domain. Q2 passes when
the snow F1 pooled over each family's pixels is at least MIN_F1. v1 takes no model input, so no
model run has to withhold these dates.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from pipelines.snow_gapfill import fill as f
from pipelines.snow_gapfill.run import build_terrain, load_observations
from pipelines.snow_obs.classify import CLOUD, NO_SNOW, NODATA, SNOW

MIN_F1 = 0.75  # README section 2, Q2
CHANGE_WINDOW_DAYS = 10  # README section 2, Q2
CLEAR_MIN_OBSERVED = 0.9
DONOR_MIN_CLOUD = 0.2
SEASON_MIN_SNOW_FRACTION = 0.01
RUN_LENGTHS = (2, 3)


def counts(predicted: np.ndarray, truth: np.ndarray, population: np.ndarray) -> dict[str, int]:
    p, t = predicted[population], truth[population] == SNOW
    return {
        "pixels": int(population.sum()),
        "tp": int(np.count_nonzero(p & t)),
        "fp": int(np.count_nonzero(p & ~t)),
        "fn": int(np.count_nonzero(~p & t)),
        "tn": int(np.count_nonzero(~p & ~t)),
    }


def f1(c: dict[str, int]) -> float | None:
    denominator = 2 * c["tp"] + c["fp"] + c["fn"]
    return round(2 * c["tp"] / denominator, 4) if denominator else None


def pooled(cases: list[dict[str, Any]]) -> dict[str, Any]:
    total = {key: sum(case[key] for case in cases) for key in ("pixels", "tp", "fp", "fn", "tn")}
    return dict(total, cases=len(cases), f1=f1(total))


def changing(day: date, observations: list[f.Observation]) -> np.ndarray:
    """Pixels seen both as snow and as no snow within CHANGE_WINDOW_DAYS of the day."""
    window = [o for o in observations if abs((o.day - day).days) <= CHANGE_WINDOW_DAYS]
    shape = observations[0].classes.shape
    snow, bare = np.zeros(shape, bool), np.zeros(shape, bool)
    for o in window:
        snow |= o.classes == SNOW
        bare |= o.classes == NO_SNOW
    return snow & bare


def season(observations: list[f.Observation], inside: np.ndarray) -> tuple[date, date] | None:
    snowy = []
    for o in observations:
        seen = int(np.count_nonzero(inside & ((o.classes == SNOW) | (o.classes == NO_SNOW))))
        if seen and np.count_nonzero(inside & (o.classes == SNOW)) / seen >= SEASON_MIN_SNOW_FRACTION:
            snowy.append(o.day)
    return (snowy[0], snowy[-1]) if snowy else None


def _case(
    family: str, day: date, filled: f.Filled, truth: np.ndarray, hidden: np.ndarray,
    observations: list[f.Observation], terrain: f.Terrain, **extra: Any,
) -> dict[str, Any]:
    population = hidden & terrain.fit & ((truth == SNOW) | (truth == NO_SNOW)) & changing(day, observations)
    result = counts(filled.snow, truth, population)
    return dict(family=family, date=day.isoformat(), **extra, **result, f1=f1(result))


def transplant_cases(
    observations: list[f.Observation], fits: list[f.Snowline], terrain: f.Terrain, first: date, last: date
) -> list[dict[str, Any]]:
    inside = terrain.inside
    total = int(inside.sum())
    clear = [
        i for i, o in enumerate(observations)
        if first <= o.day <= last
        and np.count_nonzero(inside & ((o.classes == SNOW) | (o.classes == NO_SNOW))) / total >= CLEAR_MIN_OBSERVED
    ]
    donors = [
        i
        for i, o in enumerate(observations)
        if np.count_nonzero(inside & (o.classes == CLOUD)) / total >= DONOR_MIN_CLOUD
    ]
    cases = []
    for k, target in enumerate(clear):
        candidates = [d for d in donors if d != target]
        if not candidates:
            break
        donor = candidates[k % len(candidates)]
        truth = observations[target].classes
        hidden = inside & (observations[donor].classes == CLOUD) & ((truth == SNOW) | (truth == NO_SNOW))
        masked = np.where(hidden, CLOUD, truth).astype("uint8")
        trial = list(observations)
        trial[target] = f.Observation(observations[target].day, masked, observations[target].source)
        trial_fits = list(fits)
        trial_fits[target] = f.fit_snowline(masked, terrain)
        table = f.snowline_table(trial, trial_fits)
        filled = f.fill(observations[target].day, trial, table, terrain)
        cases.append(
            _case("transplant", observations[target].day, filled, truth, hidden, observations, terrain,
                  donor=observations[donor].day.isoformat())
        )
    return cases


def hidden_run_cases(
    observations: list[f.Observation], fits: list[f.Snowline], terrain: f.Terrain, first: date, last: date
) -> list[dict[str, Any]]:
    in_season = [i for i, o in enumerate(observations) if first <= o.day <= last]
    cases = []
    for length in RUN_LENGTHS:
        for start in range(len(in_season) - length + 1):
            run = in_season[start : start + length]
            keep = [i for i in range(len(observations)) if i not in run]
            trial = [observations[i] for i in keep]
            table = f.snowline_table(trial, [fits[i] for i in keep])
            label = f"{observations[run[0]].day.isoformat()}..{observations[run[-1]].day.isoformat()}"
            for i in run:
                filled = f.fill(observations[i].day, trial, table, terrain)
                cases.append(
                    _case(f"hidden_run_{length}", observations[i].day, filled, observations[i].classes,
                          terrain.inside, observations, terrain, run=label)
                )
    return cases


def report(observations: list[f.Observation], terrain: f.Terrain, start: date, end: date) -> dict[str, Any]:
    in_range = [o for o in observations if start <= o.day <= end]
    span = season(in_range, terrain.inside)
    if span is None:
        return {"check": "q2_gapfill", "ok": False, "failures": ["no snow season in the range"]}
    fits = [f.fit_snowline(o.classes, terrain) for o in observations]
    cases = transplant_cases(observations, fits, terrain, *span) + hidden_run_cases(observations, fits, terrain, *span)
    families = {
        name: pooled([c for c in cases if c["family"].startswith(name)]) for name in ("transplant", "hidden_run")
    }
    overall = pooled(cases)
    failures = [
        f"{name} snow F1 {result['f1']} < {MIN_F1}"
        for name, result in families.items()
        if result["f1"] is None or result["f1"] < MIN_F1
    ]
    return {
        "check": "q2_gapfill",
        "season": [span[0].isoformat(), span[1].isoformat()],
        "observation_dates": [o.day.isoformat() for o in observations],
        "thresholds": {"min_f1": MIN_F1, "change_window_days": CHANGE_WINDOW_DAYS},
        "overall": overall,
        "families": families,
        "by_run_length": {
            str(n): pooled([c for c in cases if c["family"] == f"hidden_run_{n}"]) for n in RUN_LENGTHS
        },
        "cases": cases,
        "failures": failures,
        "ok": not failures,
    }


def main(argv: list[str] | None = None) -> int:
    from pipelines.catalog import storage_from_env

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", choices=("staging", "prod"), required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--static-cache", type=Path)
    args = parser.parse_args(argv)
    observations, grid = load_observations(storage_from_env(args.target), args.start, args.end, lookaround=0)
    terrain = build_terrain(grid, observations[0].classes != NODATA, args.static_cache)
    result = report(observations, terrain, args.start, args.end)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for name, family in result.get("families", {}).items():
        print(f"{name}: F1 {family['f1']} over {family['pixels']} pixels in {family['cases']} cases")
    for failure in result["failures"]:
        print(f"FAIL {failure}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
