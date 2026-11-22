"""Check the published SWE layer against the published Sentinel-2 snow cover, date by date.

    python -m qa.validate_swe_depth --target prod

For every date of the snow_obs catalogue in the windows below it prints:
  false_pct   share of the modelled snow area (SWE > 5 mm, ski resort excluded) that the observation calls
              bare ground with high confidence (the cell rule of pipelines.snow_model.insertion).
  before_pct  the same share measured before direct insertion, from the entry's qa; this is the model's own
              error, whereas false_pct is after the observation has been inserted.
  crest       cells with SWE > 5 mm in the Veleta-Mulhacen crest box on 2026-11-20.
  iou         intersection over union of modelled snow and observed snow on the cells the observation
              decides (at least half of their 20 m pixels clear), ski resort excluded.
Exit status is 1 when a date has false_pct of 10 or more, or the crest box has modelled snow.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

from pipelines.catalog import storage_from_env
from pipelines.catalog.storage import Storage
from pipelines.snow_model import insertion
from pipelines.snow_model.grid import Grid
from pipelines.snow_model.outputs import MIN_VISIBLE_SWE_MM
from pipelines.snow_model.run import rasterize_geometries

WINDOWS = [(date(2026, 10, 1), date(2026, 11, 20)), (date(2025, 3, 20), date(2025, 3, 30))]
MAX_FALSE_PCT = 10.0
CREST_DATE = "2026-11-20"
CREST_BOX = (-3.42, 37.01, -3.30, 37.07)
IOU_DATES = ("2025-03-28", "2025-03-30")
SKI_RESORT = Path("data/ski_resort.geojson")


def read_swe(storage: Storage, day: str) -> tuple[np.ndarray, Grid, dict] | None:
    from rasterio.io import MemoryFile

    blob = storage.read(f"catalog/entries/swe/{day}.json")
    if blob is None:
        return None
    entry = json.loads(blob.data)
    cog = storage.read(entry["cog"])
    if cog is None:
        return None
    with MemoryFile(cog.data) as memory, memory.open() as source:
        swe = source.read(1).astype("float64")
        nodata = source.nodata
        grid = Grid(
            source.crs.to_string(),
            float(source.transform.c),
            float(source.transform.f),
            float(source.transform.a),
            source.width,
            source.height,
        )
    return np.where(swe == nodata, 0.0, swe), grid, entry


def crest_mask(grid: Grid) -> np.ndarray:
    lons, lats = grid.cell_centres_lonlat()
    west, south, east, north = CREST_BOX
    return (lons >= west) & (lons <= east) & (lats >= south) & (lats <= north)


def validate(storage: Storage) -> list[dict]:
    swe_days = [key.rsplit("/", 1)[1].removesuffix(".json") for key in storage.list("catalog/entries/swe/")]
    reference = next((read_swe(storage, day) for day in swe_days), None)
    days = sorted(
        key.rsplit("/", 1)[1].removesuffix(".json") for key in storage.list("catalog/entries/snow_obs/")
    )
    wanted = [d for d in days if any(a <= date.fromisoformat(d) <= b for a, b in WINDOWS)]
    rows = []
    for day in wanted:
        observation = insertion.load_observation(storage, day)
        published = read_swe(storage, day)
        if observation is None:
            continue
        row: dict = {"date": day}
        if published is None and reference is None:
            row["note"] = "no SWE published for any date"
            rows.append(row)
            continue
        if published is None:
            # A date without an entry is a date where the model has no snow above 5 mm.
            assert reference is not None
            grid = reference[1]
            swe = np.zeros((grid.height, grid.width))
            entry: dict = {"qa": {"scores": {}}}
            row["note"] = "no SWE published: no modelled snow above 5 mm, or the date was not run"
        else:
            swe, grid, entry = published
        state = insertion.cell_state(observation, grid)
        ski = rasterize_geometries(SKI_RESORT, grid, all_touched=True)
        modelled = (swe >= MIN_VISIBLE_SWE_MM) & ~ski
        row["modelled_km2"] = round(float(modelled.sum()) * grid.cell_area_m2 / 1e6, 2)
        row["false_pct"] = round(100.0 * float((modelled & state.bare).sum()) / max(1, int(modelled.sum())), 2)
        row["before_pct"] = entry["qa"]["scores"].get("false_snow_before_insertion_pct")
        if day == CREST_DATE:
            row["crest_cells"] = int((modelled & crest_mask(grid)).sum())
        if day in IOU_DATES:
            decided = state.valid & ~ski
            model, seen = modelled & decided, state.snow & decided
            union = int((model | seen).sum())
            row["iou"] = round(float((model & seen).sum()) / union, 3) if union else None
            row["observed_snow_km2"] = round(float(seen.sum()) * grid.cell_area_m2 / 1e6, 2)
            row["modelled_snow_km2_on_decided_cells"] = round(float(model.sum()) * grid.cell_area_m2 / 1e6, 2)
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", choices=("staging", "prod"), required=True)
    args = parser.parse_args(argv)
    rows = validate(storage_from_env(args.target))
    for row in rows:
        print(json.dumps(row))
    failed = [r for r in rows if r.get("false_pct", 0) >= MAX_FALSE_PCT or r.get("crest_cells", 0) > 0]
    print(f"dates checked: {len(rows)}; failing: {[r['date'] for r in failed]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
