"""Daily snow probability and snow depth range for the catalogue (snow model v2, prior ensemble).

    python -m pipelines.snow_model_v2.daily --start 2026-11-16 --end 2026-11-22 --target staging

What it publishes, and why (docs/snow-evaluation.md, section 0): the v2 prior ensemble, with no assimilation,
beats v1 for snow presence against Sentinel-2 (F1 0.744 against 0.692 on 18 independent dates), the particle
smoother adds nothing on held-out dates, and nothing in the repository measures SWE. So the site gets
- `snow_gapfill` (status gapfilled): the share of prior members with SWE of at least 5 mm, replaced by 1 or 0 on
  the 20 m pixels a clear Sentinel-2 date decides; the other pixels keep the model value and carry the days since
  their last decisive observation in band `obs_age_days`.
- `snow_depth` (status modelled): the ensemble p50 depth in metres with p10 and p90 as bands 2 and 3.
- SWE is not published. Direct insertion and the particle smoother stay in the code base (tested) but are not on
  this path.

Every run recomputes the water year from 1 October to the last published date (no state files): forcing from
ECMWF IFS (archive plus forecast splice, cached), the class domain, `MEMBERS` prior members on the classes, then
`CELLWISE_MEMBERS` of them on the 100 m cells. `--start` and `--end` only choose the dates that are published.

Sizes. Class pass: 200 members x about 1,700 classes x 365 days, under a minute. Cell-wise pass: the
engine benchmark (docs of the engine PR) is 1.7 M member-cell-days per second per thread, so 50 members on the
whole 358,000-cell grid for a season would take about 2 hours single-threaded. The pass is limited to cells whose
class has SWE of at least 1 mm in some member on some published day (plus the cells outside every class above
the lowest such class, less 100 m), and runs in cell chunks on all cores. Cells outside it have probability 0.

The member count is justified by `--convergence` (see `convergence`): p_snow and the median depth of a 200
member draw differ from a 1000 member draw by a few hundredths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from pipelines.catalog import code_version, publish, storage_from_env
from pipelines.catalog.layers import get_layer
from pipelines.catalog.storage import Blob, Storage
from pipelines.ramps import colour_values
from pipelines.region import load_region
from pipelines.snow_model.grid import Grid
from pipelines.snow_model.insertion import _on_model_blocks, cell_state, load_observation
from pipelines.snow_model.outputs import write_geotiff
from pipelines.snow_obs import classify as c

from . import forcing as forcing_adapter
from .contract import ClassDomain, MemberParameters, SeasonForcing, sample_parameters, season_seed
from .domain import cellwise_domain
from .engine import run_ensemble
from .region_domain import RegionDomain, build_region_domain

GAPFILL = get_layer("snow_gapfill")
DEPTH = get_layer("snow_depth")
MEMBERS = 200
CELLWISE_MEMBERS = 50
SNOW_MM = 5.0  # SWE that counts as snow, as in the evaluation
CANDIDATE_MM = 1.0  # a class with less than this in every member on every day has no snow to map
CANDIDATE_MARGIN_M = 100.0
OBS_FACTOR = 5  # 20 m pixels per 100 m cell side
DEPTH_RANGE = [0.0, 20.0]
OBS_AGE_NEVER = 400.0  # obs_age_days of a pixel no clear date decided since 1 October; a real age is at most 365
OBS_AGE_RANGE = [0.0, OBS_AGE_NEVER]
NODATA = -9999.0
SEASON_START_MONTH = 10
DEFAULT_OBS_URL = "https://storage.googleapis.com/nivosense-cogs/prod"
# The quality gate flags a date, it never drops one. The thresholds are our own: the evaluation scored the
# prior at 0.74 to 0.86 F1 and a 100 m snow-area bias of -23 % to +22 % by season.
GATE_MIN_AGREEMENT = 0.80
GATE_MAX_SNOW_ON_BARE = 0.30
GATE_MIN_CLEAR_CELLS = 200
QUANTILES = (0.1, 0.5, 0.9)
PUBLISH_WORKERS = 3
CELL_CHUNK_BUDGET_BYTES = 500_000_000  # engine output arrays of one chunk: members x cells x days x 5 x 4 B


def log(message: str) -> None:
    print(message, flush=True)


@dataclass(frozen=True)
class Lattice:
    """The forcing lattice as `neighbour_weights` reads it (lon and lat only)."""

    lon: np.ndarray
    lat: np.ndarray


class PublicCatalogue:
    """Read-only view of a published catalogue over HTTPS (the observation reference of the prod site).

    The bucket is world readable, so the runner reads the observations without credentials for either target.
    COGs are named after their content, so they are cached for good; entries are fetched fresh.
    """

    def __init__(self, base_url: str, cache: Path) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = cache / "catalogue-http"
        self._dates: dict[str, list[str]] | None = None

    def _fetch(self, key: str) -> bytes | None:
        for attempt in range(1, 6):
            try:
                with urllib.request.urlopen(f"{self.base_url}/{key}", timeout=120) as response:
                    data: bytes = response.read()
                return data
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                if error.code not in (429, 500, 502, 503, 504) or attempt == 5:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == 5:
                    raise
            time.sleep(5 * attempt)
        raise RuntimeError("unreachable")

    def read(self, key: str) -> Blob | None:
        immutable = key.startswith("layers/")
        path = self.cache / key
        if immutable and path.exists():
            data: bytes | None = path.read_bytes()
        else:
            data = self._fetch(key)
            if data is not None and immutable:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        if data is None:
            return None
        return Blob(data, 0, "application/octet-stream", "", None)

    def dates(self, layer: str) -> list[date]:
        if self._dates is None:
            blob = self._fetch("catalog/index.json")
            if blob is None:
                raise RuntimeError(f"No catalogue index under {self.base_url}")
            self._dates = {name: body["dates"] for name, body in json.loads(blob)["layers"].items()}
        return [date.fromisoformat(d) for d in self._dates.get(layer, [])]


@dataclass
class Context:
    """Everything that does not change from one water year to the next."""

    region: RegionDomain
    points: list[tuple[float, float]]
    point_elevation: np.ndarray
    basin: np.ndarray  # (cells,) index into basin_ids, -1 outside every basin
    basin_ids: list[str]
    basin_names: list[str]
    inside20: np.ndarray  # (height * 5, width * 5) bool: pixels of cells in the model domain
    grid20: Grid
    workers: int = field(default_factory=lambda: max(1, os.cpu_count() or 1))


def point_elevations(region: RegionDomain, point_count: int) -> np.ndarray:
    """Mean elevation of the cells each forcing point represents (inverse distance weighted), the elevation the
    adapter asks Open-Meteo to adjust its temperature to. Points no cell uses get the domain mean."""
    assert region.neighbours is not None and region.weights is not None
    numerator, denominator = np.zeros(point_count), np.zeros(point_count)
    for k in range(region.neighbours.shape[1]):
        np.add.at(numerator, region.neighbours[:, k], region.weights[:, k] * region.elevation)
        np.add.at(denominator, region.neighbours[:, k], region.weights[:, k])
    mean = float(region.elevation.mean())
    return np.where(denominator > 0, numerator / np.maximum(denominator, 1e-12), mean)


def basin_raster(region_path: Path, region: RegionDomain) -> tuple[np.ndarray, list[str], list[str]]:
    import rasterio.features
    from rasterio.warp import transform_geom

    settings = load_region(region_path)
    payload = json.loads(settings.basins.read_text(encoding="utf-8"))
    grid = region.grid
    shapes, ids, names = [], [], []
    for index, feature in enumerate(payload["features"]):
        shapes.append((transform_geom("EPSG:4326", grid.crs, feature["geometry"]), index))
        ids.append(str(feature["properties"]["cod_uni"]))
        names.append(str(feature["properties"]["nom_rio_1"]))
    raster = rasterio.features.rasterize(
        shapes, out_shape=(grid.height, grid.width), transform=grid.transform, fill=-1, dtype="int16"
    )
    return raster.ravel()[region.cell_index].astype("int64"), ids, names


def build_context(region_path: Path, cache: Path) -> Context:
    settings = load_region(region_path)
    points = forcing_adapter.lattice(settings.bbox)
    lattice = Lattice(np.array([lon for _, lon in points]), np.array([lat for lat, _ in points]))
    cache.mkdir(parents=True, exist_ok=True)
    region = build_region_domain(region_path, lattice, cache)  # type: ignore[arg-type]
    basin, ids, names = basin_raster(region_path, region)
    grid = region.grid
    inside = np.zeros(grid.height * grid.width, dtype=bool)
    inside[region.cell_index] = True
    inside20 = np.repeat(np.repeat(inside.reshape(grid.height, grid.width), OBS_FACTOR, 0), OBS_FACTOR, 1)
    grid20 = Grid(
        grid.crs, grid.left, grid.top, grid.resolution / OBS_FACTOR, grid.width * OBS_FACTOR, grid.height * OBS_FACTOR
    )
    return Context(region, points, point_elevations(region, len(points)), basin, ids, names, inside20, grid20)


def water_years(first: date, last: date) -> list[tuple[int, date, date]]:
    """(water year named by the year it ends in, first, last) for every water year a range touches."""
    result = []
    day = first
    while day <= last:
        end_year = day.year + 1 if day.month >= SEASON_START_MONTH else day.year
        season_end = date(end_year, 9, 30)
        result.append((end_year, day, min(last, season_end)))
        day = season_end + timedelta(days=1)
    return result


def season_forcing(
    context: Context, water_year: int, last: date, cache: Path
) -> tuple[SeasonForcing, forcing_adapter.HourlyForcing]:
    hourly = forcing_adapter.fetch_season_forcing(
        water_year - 1, context.points, context.point_elevation.tolist(), cache, end=last
    )
    return forcing_adapter.to_season_forcing(hourly), hourly


def forcing_digest(forcing: SeasonForcing) -> str:
    digest = hashlib.sha256()
    for array in (forcing.temperature, forcing.precipitation, forcing.shortwave):
        digest.update(np.ascontiguousarray(array, dtype="<f4").tobytes())
    return digest.hexdigest()[:16]


def candidate_cells(domain: ClassDomain, elevation: np.ndarray, snowy_class: np.ndarray) -> np.ndarray:
    """Cells the cell-wise pass must run: cells of a class that has snow in some member, and the cells outside
    every class that lie above the lowest such class (less one 100 m band)."""
    member = domain.class_of_cell >= 0
    selected = np.zeros(domain.class_of_cell.size, dtype=bool)
    selected[member] = snowy_class[domain.class_of_cell[member]]
    if snowy_class.any():
        floor = float(domain.elevation[snowy_class].min()) - CANDIDATE_MARGIN_M
        selected |= ~member & (elevation >= floor)
    return selected


@dataclass
class CellwiseResult:
    cells: np.ndarray  # (n,) indices into the region cells
    p_snow: np.ndarray  # (n, T)
    depth: np.ndarray  # (3, n, T) p10, p50, p90 over members
    basin_area: np.ndarray  # (members, basins + 1, T) km2 with SWE >= SNOW_MM, last row the whole domain
    basin_depth_sum: np.ndarray  # (members, basins + 1, T) m summed over snow-covered cells
    basin_covered: np.ndarray  # (members, basins + 1, T) snow-covered cell count
    basin_peak: np.ndarray  # (members, basins + 1, T) m, highest cell


def run_cellwise(
    context: Context,
    forcing: SeasonForcing,
    parameters: MemberParameters,
    cells: np.ndarray,
    store: np.ndarray,
) -> CellwiseResult:
    region = context.region
    assert region.neighbours is not None and region.weights is not None
    assert region.radiation is not None and region.aspect is not None
    members, days, groups = parameters.count, store.size, len(context.basin_ids) + 1
    per_cell = members * days * 5 * 4
    chunk = int(np.clip(CELL_CHUNK_BUDGET_BYTES // per_cell, 250, 8000))
    pieces = [cells[start : start + chunk] for start in range(0, cells.size, chunk)]
    area_km2 = region.grid.cell_area_m2 / 1e6
    basin_of = np.where(context.basin >= 0, context.basin, groups - 1)  # cells in no basin only count in the domain

    def work(selected: np.ndarray) -> tuple[np.ndarray, np.ndarray, tuple[np.ndarray, ...]]:
        domain = cellwise_domain(
            region.elevation[selected],
            region.neighbours[selected],  # type: ignore[index]
            region.weights[selected],  # type: ignore[index]
            region.radiation[:, selected],  # type: ignore[index]
            region.grid.cell_area_m2,
            region.aspect[selected],  # type: ignore[index]
        )
        run = run_ensemble(domain, forcing, parameters, store.tolist(), workers=1)
        covered = run.swe >= SNOW_MM
        depth = run.depth
        quantiles = np.quantile(depth, QUANTILES, axis=0).astype("float32")
        area = np.zeros((members, groups, days), dtype="float32")
        total = np.zeros_like(area)
        covered_count = np.zeros_like(area)
        peak = np.zeros_like(area)
        masked = np.where(covered, depth, 0.0)
        for group in range(groups):
            in_group = basin_of[selected] == group if group < groups - 1 else np.ones(selected.size, dtype=bool)
            if group < groups - 1 and not in_group.any():
                continue
            covered_count[:, group] = covered[:, in_group].sum(axis=1)
            area[:, group] = covered_count[:, group] * area_km2
            total[:, group] = masked[:, in_group].sum(axis=1)
            peak[:, group] = depth[:, in_group].max(axis=1)
        return covered.mean(axis=0).astype("float32"), quantiles, (area, total, covered_count, peak)

    with ThreadPoolExecutor(context.workers) as pool:
        results = list(pool.map(work, pieces))
    p_snow = np.concatenate([r[0] for r in results], axis=0) if results else np.zeros((0, days), dtype="float32")
    depth_q = np.concatenate([r[1] for r in results], axis=1) if results else np.zeros((3, 0, days), dtype="float32")
    shape = (members, groups, days)
    area, total, covered_count, peak = (np.zeros(shape, dtype="float32") for _ in range(4))
    for r in results:
        a, t, n, p = r[2]
        area += a
        total += t
        covered_count += n
        peak = np.maximum(peak, p)
    return CellwiseResult(cells, p_snow, depth_q, area, total, covered_count, peak)


def basin_scores(result: CellwiseResult, context: Context, day: int) -> dict[str, float]:
    """p10, p50 and p90 over members of the snow-covered area, the mean depth over the snow-covered cells and the
    peak depth, for every basin and the whole domain."""
    scores: dict[str, float] = {}
    names = [f"basin_{basin}" for basin in context.basin_ids] + ["domain"]
    for group, name in enumerate(names):
        area = result.basin_area[:, group, day]
        covered = result.basin_covered[:, group, day]
        mean = np.divide(result.basin_depth_sum[:, group, day], covered, out=np.zeros_like(area), where=covered > 0)
        peak = result.basin_peak[:, group, day]
        for label, values in (("snow_area_km2", area), ("depth_mean_m", mean), ("depth_peak_m", peak)):
            for quantile, value in zip(QUANTILES, np.quantile(values, QUANTILES)):
                scores[f"{name}_{label}_p{int(quantile * 100)}"] = round(float(value), 3)
    return scores


def full_cells(context: Context, values: np.ndarray, fill: float = np.nan) -> np.ndarray:
    """(cells,) values to the (height, width) model grid."""
    grid = context.region.grid
    full = np.full(grid.height * grid.width, fill, dtype="float32")
    full[context.region.cell_index] = values
    return full.reshape(grid.height, grid.width)


@dataclass
class ObservationTrack:
    """Days since the last decisive Sentinel-2 pixel, kept pixel by pixel through a season."""

    last_clear: np.ndarray  # (height * 5, width * 5) int32 date ordinal, 0 for never

    @classmethod
    def empty(cls, grid20: Grid) -> ObservationTrack:
        return cls(np.zeros((grid20.height, grid20.width), dtype="int32"))


def decisive_pixels(classes: np.ndarray, confidence: np.ndarray, inside: np.ndarray) -> np.ndarray:
    """Snow, or bare ground with high confidence, as `pixel_counts` of the observation operator reads them.
    Cloud, unknown and low-confidence bare pixels are not evidence."""
    snow = classes == c.SNOW
    bare = (classes == c.NO_SNOW) & (confidence == c.CONFIDENCE_HIGH)
    return np.asarray((snow | bare) & inside)


def apply_observation(
    probability: np.ndarray, classes: np.ndarray, confidence: np.ndarray, inside: np.ndarray
) -> np.ndarray:
    """The probability with the pixels the observation decides set to 1 (snow) or 0 (bare)."""
    result = probability.copy()
    result[(classes == c.SNOW) & inside] = 1.0
    result[(classes == c.NO_SNOW) & (confidence == c.CONFIDENCE_HIGH) & inside] = 0.0
    return result


def quality_gate(
    context: Context, state: Any, prior_p: np.ndarray, ski: np.ndarray
) -> tuple[dict[str, float], list[str]]:
    """Agreement of the prior with the observation of the date on the 100 m cells it decides, outside the ski
    resort (artificial snow), and the share of modelled snow area on cells observed bare with high confidence."""
    region = context.region
    valid = state.valid.ravel()[region.cell_index] & ~ski
    snow = state.snow.ravel()[region.cell_index]
    bare = state.bare.ravel()[region.cell_index] & ~ski
    modelled = prior_p >= 0.5
    clear = int(valid.sum())
    if clear == 0:
        return {"clear_cells": 0.0}, ["quality_check_failed"]
    tp = int((modelled & snow & valid).sum())
    fp = int((modelled & ~snow & valid).sum())
    fn = int((~modelled & snow & valid).sum())
    agreement = float(((modelled == snow) & valid).sum()) / clear
    f1 = 2 * tp / max(1, 2 * tp + fp + fn)
    on_bare = float((modelled & bare).sum()) / max(1, int((modelled & ~ski).sum()))
    scores = {
        "clear_cells": float(clear),
        "prior_agreement_pct": round(100 * agreement, 2),
        "prior_f1": round(f1, 3),
        "prior_snow_on_bare_pct": round(100 * on_bare, 2),
    }
    failed = clear >= GATE_MIN_CLEAR_CELLS and (agreement < GATE_MIN_AGREEMENT or on_bare > GATE_MAX_SNOW_ON_BARE)
    return scores, ["quality_check_failed"] if failed else []


def write_rgba(path: Path, rgba: np.ndarray, grid: Grid) -> None:
    import rasterio

    with rasterio.open(
        path,
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


def write_gapfill(folder: Path, context: Context, probability: np.ndarray, age: np.ndarray) -> dict[str, Path]:
    grid = context.grid20
    data, display = folder / "snow_gapfill.tif", folder / "snow_gapfill-display.tif"
    write_geotiff(data, [(probability, "snow_probability"), (age, "obs_age_days")], grid)
    write_rgba(display, colour_values(probability, "snow_cover_probability"), grid)
    return {"data": data, "display": display}


def write_depth(folder: Path, context: Context, bands: list[np.ndarray], shown: np.ndarray) -> dict[str, Path]:
    grid = context.region.grid
    data, display = folder / "snow_depth.tif", folder / "snow_depth-display.tif"
    write_geotiff(data, [(bands[0], "depth_p50"), (bands[1], "depth_p10"), (bands[2], "depth_p90")], grid)
    # The depth ramp is in cm; the published data stays in metres.
    write_rgba(display, colour_values(np.where(shown, bands[0], np.nan) * 100.0, "snow_depth"), grid)
    return {"data": data, "display": display}


def common_flags(forecast_day: bool) -> list[str]:
    flags = ["prior_ensemble", "not_validated_against_measurements", "ski_resort_excluded_from_score"]
    return flags + (["forcing_from_forecast"] if forecast_day else [])


@dataclass
class Product:
    """Everything one date publishes, prepared on the main thread so the publishing threads only write."""

    date: str
    probability: np.ndarray  # (height * 5, width * 5), NaN outside the domain
    age: np.ndarray
    depth_bands: list[np.ndarray]  # p50, p10, p90 on the 100 m grid
    shown: np.ndarray  # cells drawn on the depth map
    source_ids: list[str]
    baseline: str
    flags: list[str]
    scores: dict[str, float]
    depth_flags: list[str]
    depth_scores: dict[str, float]


def publish_product(
    context: Context, product: Product, storage: Storage, version: str, slots: threading.BoundedSemaphore
) -> None:
    try:
        with tempfile.TemporaryDirectory(prefix="snow-v2-") as tmp:
            folder = Path(tmp)
            publish(
                "snow_gapfill",
                product.date,
                write_gapfill(folder, context, product.probability, product.age),
                {
                    "source_ids": product.source_ids,
                    "processing_baseline": product.baseline,
                    "bands": list(GAPFILL.bands or ()),
                    "units": ["1", "d"],
                    "value_range": [[0.0, 1.0], OBS_AGE_RANGE],
                    "code_version": version,
                    "qa": {"flags": product.flags, "scores": product.scores},
                },
                storage,
            )
            publish(
                "snow_depth",
                product.date,
                write_depth(folder, context, product.depth_bands, product.shown),
                {
                    "source_ids": product.source_ids[:3],
                    "bands": list(DEPTH.bands or ()),
                    "units": ["m", "m", "m"],
                    "value_range": [DEPTH_RANGE] * 3,
                    "code_version": version,
                    "qa": {"flags": product.depth_flags, "scores": product.depth_scores},
                },
                storage,
            )
    finally:
        slots.release()


def run_water_year(
    context: Context,
    catalogue: PublicCatalogue,
    storage: Storage,
    water_year: int,
    first: date,
    last: date,
    cache: Path,
    version: str,
    members: int = MEMBERS,
    cellwise_members: int = CELLWISE_MEMBERS,
) -> list[dict[str, Any]]:
    region = context.region
    started = time.time()
    forcing, hourly = season_forcing(context, water_year, last, cache)
    days = forcing.days
    index_of = {day: i for i, day in enumerate(days)}
    publish_days = [d for d in days if first <= d <= last]
    # The engine always keeps the last day, so it is part of the stored days here too.
    store = np.array(sorted({index_of[d] for d in publish_days} | {len(days) - 1}), dtype="int64")
    log(f"WY{water_year}: forcing {days[0]} to {days[-1]} ({len(days)} days), publishing {len(publish_days)} dates")

    parameters = sample_parameters(members, water_year, storm_count=forcing.storm_count)
    run = run_ensemble(region.domain, forcing, parameters, store.tolist(), workers=context.workers)
    snowy_class = np.asarray((run.swe >= CANDIDATE_MM).any(axis=(0, 2)), dtype=bool)
    selected = candidate_cells(region.domain, region.elevation, snowy_class)
    cells = np.flatnonzero(selected)
    log(
        f"class pass {time.time() - started:.0f} s, {int(snowy_class.sum())} of {snowy_class.size} classes with snow, "
        f"{cells.size} of {selected.size} cells in the cell-wise pass"
    )
    del run

    rng = np.random.default_rng(season_seed(water_year) + 1)
    subset = np.sort(rng.choice(members, size=min(cellwise_members, members), replace=False))
    cellwise = run_cellwise(context, forcing, parameters.take(subset), cells, store)
    log(f"cell-wise pass done {time.time() - started:.0f} s")

    digest = forcing_digest(forcing)
    # The decisive pixels of an observation set the probability on its date; the track keeps their age for the
    # days after it, so every observation of the water year is read, also those before the first published date.
    observed = {d for d in catalogue.dates("snow_obs") if days[0] <= d <= last}
    track = ObservationTrack.empty(context.grid20)
    summaries: list[dict[str, Any]] = []
    position = {int(day): j for j, day in enumerate(store)}
    ski = region.ski_cells
    # Writing a COG and tiles takes longer than preparing a day, so a few days publish at once; the semaphore keeps
    # the rasters of waiting days (about 150 MB each) from piling up.
    slots = threading.BoundedSemaphore(PUBLISH_WORKERS + 1)
    futures: list[Future[None]] = []
    pool = ThreadPoolExecutor(PUBLISH_WORKERS)
    for day in days:
        if day > last:
            break
        observation = load_observation(catalogue, day.isoformat()) if day in observed else None  # type: ignore[arg-type]
        classes = confidence = None
        if observation is not None:
            classes = _on_model_blocks(observation.classes, observation, region.grid)
            confidence = _on_model_blocks(observation.confidence, observation, region.grid)
            track.last_clear[decisive_pixels(classes, confidence, context.inside20)] = day.toordinal()
        j = position.get(index_of[day])
        if j is None:
            continue

        p_cells = np.zeros(region.cell_index.size, dtype="float32")
        p_cells[cellwise.cells] = cellwise.p_snow[:, j]
        model_grid = full_cells(context, p_cells)
        probability = np.repeat(np.repeat(model_grid, OBS_FACTOR, 0), OBS_FACTOR, 1)
        flags = common_flags(bool(hourly.from_forecast[index_of[day] * 24 : index_of[day] * 24 + 24].any()))
        scores: dict[str, float] = {"members": float(cellwise.basin_area.shape[0])}
        source_ids = [
            f"open-meteo:{hourly.model}",
            f"forcing:{digest}",
            f"prior:n{members}:r{cellwise_members}:seed{season_seed(water_year)}",
        ]
        baseline = "prior-only"
        if observation is not None:
            decisive = decisive_pixels(classes, confidence, context.inside20)  # type: ignore[arg-type]
            probability = apply_observation(probability, classes, confidence, context.inside20)  # type: ignore[arg-type]
            gate_scores, gate_flags = quality_gate(context, cell_state(observation, region.grid), p_cells, ski)
            scores.update(gate_scores)
            flags += ["observation_used"] + gate_flags
            source_ids.append(f"snow_obs:{day.isoformat()}:{observation.pixel_hash[:16]}")
            baseline = f"snow_obs:{observation.pixel_hash[:16]}"
            scores["observed_fraction"] = round(float(decisive.sum()) / max(1, int(context.inside20.sum())), 4)
        decided_ever = track.last_clear > 0
        age = np.where(decided_ever, day.toordinal() - track.last_clear, OBS_AGE_NEVER).astype("float32")
        age = np.where(context.inside20, age, np.nan)
        flags.append("obs_age_days")
        if (decided_ever & context.inside20).any():
            scores["obs_age_days_median"] = float(np.median(age[decided_ever & context.inside20]))
        published_area = float(((probability >= 0.5) & context.inside20).sum()) * (context.grid20.cell_area_m2 / 1e6)
        scores["snow_area_km2"] = round(published_area, 2)
        scores["model_snow_area_km2"] = round(float((p_cells >= 0.5).sum()) * region.grid.cell_area_m2 / 1e6, 2)
        scores["ski_resort_area_km2"] = round(float(ski.sum()) * region.grid.cell_area_m2 / 1e6, 2)

        summary: dict[str, Any] = {"date": day.isoformat(), "flags": list(flags), "scores": dict(scores)}
        depth_scores = {
            "members": scores["members"],
            "ski_resort_area_km2": scores["ski_resort_area_km2"],
            **basin_scores(cellwise, context, j),
        }
        depth_flags = [f for f in flags if f not in ("observation_used", "obs_age_days", "quality_check_failed")]
        depth_flags += ["median_of_ensemble", "magnitude_uncertain_factor_two"]
        depth_bands = []
        for q in (1, 0, 2):  # p50, p10, p90
            band = np.zeros(region.cell_index.size, dtype="float32")
            band[cellwise.cells] = cellwise.depth[q, :, j]
            depth_bands.append(full_cells(context, band))
        product = Product(
            day.isoformat(),
            probability,
            age,
            depth_bands,
            full_cells(context, p_cells, 0.0) >= 0.5,
            source_ids,
            baseline,
            flags,
            scores,
            depth_flags,
            depth_scores,
        )
        for future in futures:
            if future.done():
                future.result()  # a failed publication stops the run now, not after the whole season
        slots.acquire()
        futures.append(pool.submit(publish_product, context, product, storage, version, slots))
        summaries.append(summary)
        gate = " ".join(f"{k}={scores[k]}" for k in ("prior_agreement_pct", "prior_snow_on_bare_pct") if k in scores)
        log(
            f"{day} snow {scores['snow_area_km2']} km2 {'obs ' if observation else ''}{gate}"
            f"{' FLAGGED' if 'quality_check_failed' in flags else ''}"
        )
    pool.shutdown(wait=True)
    for future in futures:
        future.result()
    log(f"WY{water_year} done in {time.time() - started:.0f} s")
    return summaries


def convergence(context: Context, water_year: int, last: date, cache: Path, days: int = 12) -> dict[str, float]:
    """Max and mean absolute difference of p_snow and of the median depth between a 200 member draw and a 1000
    member draw (class pass, `days` evenly spread days of the season), and of the 50 member subset of the 200."""
    forcing, _ = season_forcing(context, water_year, last, cache)
    store = np.unique(np.linspace(30, len(forcing.days) - 1, days).astype(int))
    outputs = {}
    for count in (50, MEMBERS, 1000):
        parameters = sample_parameters(count, water_year, storm_count=forcing.storm_count)
        run = run_ensemble(context.region.domain, forcing, parameters, store.tolist(), workers=context.workers)
        outputs[count] = ((run.swe >= SNOW_MM).mean(axis=0), np.median(run.depth, axis=0))
    weights = context.region.domain.cell_count / context.region.domain.cell_count.sum()
    result: dict[str, float] = {}
    for count in (50, MEMBERS):
        p_diff = np.abs(outputs[count][0] - outputs[1000][0])
        d_diff = np.abs(outputs[count][1] - outputs[1000][1])
        result[f"n{count}_p_snow_max"] = round(float(p_diff.max()), 3)
        result[f"n{count}_p_snow_cell_weighted_mean"] = round(float((p_diff.mean(axis=1) * weights).sum()), 4)
        result[f"n{count}_depth_p50_max_m"] = round(float(d_diff.max()), 3)
        result[f"n{count}_depth_p50_cell_weighted_mean_m"] = round(float((d_diff.mean(axis=1) * weights).sum()), 4)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=date.fromisoformat, required=True, help="first date to publish")
    parser.add_argument("--end", type=date.fromisoformat, required=True, help="last date to publish")
    parser.add_argument("--target", choices=("staging", "prod"), required=True)
    parser.add_argument("--region", type=Path, default=Path("regions/sierra-nevada.json"))
    parser.add_argument("--cache", type=Path, default=Path("snow-cache"))
    parser.add_argument("--members", type=int, default=MEMBERS)
    parser.add_argument("--cellwise-members", type=int, default=CELLWISE_MEMBERS)
    parser.add_argument("--convergence", action="store_true", help="print the member count check and stop")
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error("--end is before --start")
    end = min(args.end, date.today() - timedelta(days=1))
    if end < args.end:
        log(f"--end {args.end} is not past yet; publishing to {end}")
    context = build_context(args.region, args.cache)
    log(
        f"Model grid {context.region.grid.width}x{context.region.grid.height}, {context.region.cell_index.size} cells, "
        f"{context.region.domain.class_count} classes, {len(context.points)} forcing points"
    )
    catalogue = PublicCatalogue(os.environ.get("SNOW_OBS_URL", DEFAULT_OBS_URL), args.cache)
    if args.convergence:
        for water_year, _, last in water_years(args.start, end):
            print(json.dumps({"water_year": water_year, **convergence(context, water_year, last, args.cache)}))
        return 0
    storage = storage_from_env(args.target)
    version = code_version()
    for water_year, first, last in water_years(args.start, end):
        run_water_year(
            context,
            catalogue,
            storage,
            water_year,
            first,
            last,
            args.cache,
            version,
            args.members,
            args.cellwise_members,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
