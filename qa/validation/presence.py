"""Snow presence of a catalogue SWE layer against Sentinel-2 snow masks (catalogue layer `snow_obs`).

Reference cell rule: the one of `pipelines.snow_model.insertion.cell_state` (a 100 m cell is decided when at
least half of its 20 m pixels are decisive; it holds snow when at least half of its pixels are snow), with the
ski resort left out because its artificial snow says nothing about natural snow.

A date with no swe entry is skipped, not read as bare: the catalogue cannot tell "no visible snow" from "model not
run" (see baselines.py), and reading it as bare scored April to June 2025 as F1 zero while the model had not run.

Independence: v1 inserts the Sentinel-2 mask into its state on every date it has one (the entry flag
`observation_inserted`), so on those dates this is a consistency check, not a validation. Only dates without
the flag, or a model that does not use the masks, are an independent test. The per-date table carries the flag.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from pipelines.snow_model import insertion
from pipelines.snow_model.dem import load_elevation
from pipelines.snow_model.grid import Grid
from pipelines.snow_model.outputs import MIN_VISIBLE_SWE_MM
from pipelines.snow_model.run import rasterize_geometries

from . import metrics
from .baselines import HttpStorage, catalogue_dates, read_layer

SKI_RESORT = Path(__file__).resolve().parents[2] / "data" / "ski_resort.geojson"
REGION_FILE = Path(__file__).resolve().parents[2] / "regions" / "sierra-nevada.json"


def _grid(values: np.ndarray, transform: object, crs: str) -> Grid:
    return Grid(crs, float(transform.c), float(transform.f), float(transform.a), values.shape[1], values.shape[0])  # type: ignore[attr-defined]


def obs_dates(storage: HttpStorage) -> list[date]:
    blob = storage.read("catalog/index.json")
    if blob is None:
        return []
    return [date.fromisoformat(d) for d in json.loads(blob.data)["layers"].get("snow_obs", {}).get("dates", [])]


@dataclass
class PresenceResult:
    per_date: pd.DataFrame
    by_band: pd.DataFrame
    pooled: dict[str, float]
    pooled_not_inserted: dict[str, float]
    skipped: list[date]


def score_swe_presence(storage: HttpStorage, days: list[date], elevation: np.ndarray | None = None) -> PresenceResult:
    """Per-date and pooled presence scores of `swe` >= the visible threshold against Sentinel-2 snow.

    Returns the per-date table, the pooled by-band table (empty when the elevation could not be loaded) and the
    pooled confusion. Dates without a swe entry are left out and listed in `skipped`.
    """
    published = set(catalogue_dates(storage, "swe"))
    swe_days = {d: read_layer(storage, "swe", d) for d in days if d in published}
    skipped = [d for d in days if swe_days.get(d) is None]
    days = [d for d in days if swe_days.get(d) is not None]
    if not days:
        return PresenceResult(pd.DataFrame(), pd.DataFrame(), {}, {}, skipped)
    first = swe_days[days[0]]
    assert first is not None
    grid = _grid(first[0], first[1], first[2])
    if elevation is None:
        region = json.loads(REGION_FILE.read_text(encoding="utf-8"))
        try:
            elevation = load_elevation(grid, tuple(region["bbox"]))
        except Exception:  # offline or tile missing: scores without bands are still useful
            elevation = None
    ski = rasterize_geometries(SKI_RESORT, grid, all_touched=True)
    rows, preds, truths, elevs, inserted = [], [], [], [], []
    for day in days:
        observation = insertion.load_observation(storage, day.isoformat())  # type: ignore[arg-type]
        if observation is None:
            continue
        state = insertion.cell_state(observation, grid)
        raster = swe_days[day]
        assert raster is not None
        swe = raster[0]
        decided = state.valid & ~ski
        pred = swe >= MIN_VISIBLE_SWE_MM
        row: dict[str, object] = {
            "date": day,
            "observation_inserted": "observation_inserted" in raster[3]["qa"]["flags"],
            "cells": int(decided.sum()),
            "obs_snow_cells": int((state.snow & decided).sum()),
        }
        row.update(
            {
                k: v
                for k, v in metrics.confusion(pred[decided], state.snow[decided]).items()
                if k in ("f1", "mcc", "accuracy")
            }
        )
        rows.append(row)
        inserted.append(bool(row["observation_inserted"]))
        preds.append(pred[decided])
        truths.append(state.snow[decided])
        if elevation is not None:
            elevs.append(elevation[decided])
    result = PresenceResult(pd.DataFrame(rows), pd.DataFrame(), {}, {}, skipped)
    if preds:
        pred_all, truth_all = np.concatenate(preds), np.concatenate(truths)
        result.pooled = metrics.confusion(pred_all, truth_all)
        free = [i for i, flag in enumerate(inserted) if not flag]
        if free:
            result.pooled_not_inserted = metrics.confusion(
                np.concatenate([preds[i] for i in free]), np.concatenate([truths[i] for i in free])
            )
        if elevs:
            result.by_band = metrics.presence_by_band(pred_all, truth_all, np.concatenate(elevs))
    return result
