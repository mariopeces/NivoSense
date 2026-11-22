"""Regression fixtures: real cases the products got wrong once, checked on every QA run.

A fixture (qa/fixtures/*.json) names an area, the observation date and its Sentinel-2 scenes, the model dates
and a rule: no modelled snow (model band above `snow_threshold`) in a cell where the observation sees bare
ground, outside the excluded area. A model cell counts as bare only when every observation pixel inside it is
one of `bare_values`, so mixed cells at the snowline are not scored. A fixture whose inputs do not exist yet
(layer not published, class codes or exclusion polygon not defined) is `pending`, never passed.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from pipelines.catalog import Storage
from pipelines.catalog.layers import aligned_bounds

from .objects import local_file

FIXTURES_DIR = Path(__file__).with_name("fixtures")
REPO_ROOT = Path(__file__).resolve().parent.parent


def load_fixtures(folder: Path = FIXTURES_DIR) -> list[dict[str, Any]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))]


def _read_band(path: Path, band_name: str, entry: dict[str, Any], bounds: tuple[float, ...]) -> np.ma.MaskedArray:
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(path) as src:
        window = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
        band = entry["bands"].index(band_name) + 1
        data: np.ma.MaskedArray = src.read(band, window=window, boundless=True, masked=True)
    return data


def _excluded(
    geometry_path: str | None, bounds: tuple[float, ...], resolution: int, shape: tuple[int, int]
) -> np.ndarray:
    if geometry_path is None:
        return np.zeros(shape, dtype=bool)
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    from rasterio.warp import transform_geom

    collection = json.loads((REPO_ROOT / geometry_path).read_text(encoding="utf-8"))
    shapes = [transform_geom("EPSG:4326", "EPSG:32630", feature["geometry"]) for feature in collection["features"]]
    transform = from_origin(bounds[0], bounds[3], resolution, resolution)
    mask: np.ndarray = rasterize(
        shapes, out_shape=shape, transform=transform, all_touched=True, default_value=1
    ).astype(bool)
    return mask


def evaluate(
    storage: Storage, fixture: dict[str, Any], entries: dict[str, list[dict[str, Any]]], folder: Path
) -> dict[str, Any]:
    """Score one fixture against the catalogue entries (by layer, as in the index)."""
    from rasterio.warp import transform_bounds

    rule = fixture["rule"]
    result: dict[str, Any] = {"id": fixture["id"], "title": fixture["title"], "s2_scenes": fixture["s2_scenes"]}
    pending = []
    if rule["observed_band"] is None or rule["bare_values"] is None:
        pending.append(f"the bare-ground class of {rule['observed_layer']} is not set in the fixture")
    if fixture["exclude"]["geometry"] is None:
        pending.append(f"no {fixture['exclude']['name']} polygon set in the fixture")
    observed = next(
        (e for e in entries.get(rule["observed_layer"], []) if e["date"] == fixture["observation_date"]), None
    )
    if observed is None:
        pending.append(f"no {rule['observed_layer']} entry for {fixture['observation_date']}")
    models = {e["date"]: e for e in entries.get(rule["model_layer"], []) if e["date"] in fixture["model_dates"]}
    absent = [date for date in fixture["model_dates"] if date not in models]
    if absent:
        pending.append(f"no {rule['model_layer']} entry for {', '.join(absent)}")
    if pending or observed is None:
        return dict(result, status="pending", pending=pending)

    failures = []
    expected_scenes = set(fixture["s2_scenes"]["sentinel-2-c1-l2a"])
    if not expected_scenes <= set(observed["source_ids"]):
        failures.append(f"{rule['observed_layer']} {observed['date']} is not built from {sorted(expected_scenes)}")

    resolution = next(iter(models.values()))["resolution_m"]
    ratio = resolution // observed["resolution_m"]
    left, bottom, right, top = transform_bounds("EPSG:4326", "EPSG:32630", *fixture["bbox"], densify_pts=21)
    bounds = aligned_bounds(left, bottom, right, top, resolution)
    obs_path = local_file(storage, observed["cog"], folder)
    if obs_path is None:
        return dict(result, status="fail", failures=[f"{observed['cog']} is missing"])
    obs = _read_band(obs_path, rule["observed_band"], observed, bounds)
    height, width = obs.shape[0] // ratio, obs.shape[1] // ratio
    is_bare = np.isin(obs.data, rule["bare_values"]) & ~np.ma.getmaskarray(obs)
    bare = is_bare[: height * ratio, : width * ratio].reshape(height, ratio, width, ratio).all(axis=(1, 3))
    scored = bare & ~_excluded(fixture["exclude"]["geometry"], bounds, resolution, (height, width))

    dates = []
    for date, entry in sorted(models.items()):
        path = local_file(storage, entry["cog"], folder)
        if path is None:
            failures.append(f"{entry['cog']} is missing")
            continue
        model = _read_band(path, rule["model_band"], entry, bounds)[:height, :width]
        snow = np.ma.filled(model > rule["snow_threshold"], False)
        violations = int((snow & scored).sum())
        dates.append({"date": date, "bare_cells": int(scored.sum()), "snow_on_bare_cells": violations})
        if violations > rule["max_violations"]:
            failures.append(f"{date}: {violations} cells of modelled snow where S2 saw bare ground")
    status = "fail" if failures else "pass"
    return dict(result, status=status, dates=dates, failures=failures)


def run_fixtures(
    storage: Storage, entries: dict[str, list[dict[str, Any]]], fixtures: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Evaluate every fixture; ok unless one fails (pending fixtures are listed, not failed)."""
    results = []
    with tempfile.TemporaryDirectory(prefix="fixtures-") as tmp:
        for fixture in fixtures if fixtures is not None else load_fixtures():
            results.append(evaluate(storage, fixture, entries, Path(tmp)))
    return {"check": "regression_fixtures", "fixtures": results, "ok": all(r["status"] != "fail" for r in results)}
