"""Direct insertion of Sentinel-2 snow observations (catalogue layer `snow_obs`) into the model state.

The model is a temperature-index model forced by a coarse analysis; it can keep snow on cells where
Sentinel-2 sees bare ground. On a date with a clear observation, the state is set to zero on the cells
the observation calls bare with high confidence. Cloud, unknown and low-confidence pixels carry no
evidence of bare ground and are ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from pipelines.catalog.storage import Storage
from pipelines.snow_obs import classify as c

from .grid import Grid

# A 100 m cell holds 5 x 5 pixels of 20 m. It is called bare when at least half of them are decisive
# (high-confidence bare ground or snow) and at least 85 % of the decisive ones are bare. The numbers are
# our own choice: strict enough that a cell with a visible snow patch keeps its snow, loose enough that
# one cloud-shadow or forest pixel does not stop a clear crest from being cleaned.
MIN_DECISIVE_SHARE = 0.5
MIN_BARE_SHARE = 0.85


# Terrain shadow hides the ground from Sentinel-2 (the classifier calls those pixels unknown), and the
# north faces of the crest sit in shadow in November. A shaded cell is called bare when the lit, decided
# cells from 200 m below its elevation up show (almost) no snow: snow cover does not
# decrease with height, so a snow-free summit area leaves no reason for snow in the shade below it. The
# thresholds are our own choice: enough decided cells to say anything, and 2 % for a stray misclassified pixel.
SHADOW_BAND_M = 100.0
SHADOW_REACH_BANDS = 2
MIN_BAND_CELLS = 20
MAX_BAND_SNOW_SHARE = 0.02


@dataclass(frozen=True)
class Observation:
    date: str
    classes: np.ndarray
    confidence: np.ndarray
    flags: np.ndarray
    left: float
    top: float
    resolution: float
    pixel_hash: str


def load_observation(storage: Storage, date: str) -> Observation | None:
    """The published snow_obs entry of a date with its class and confidence bands, or None."""
    from rasterio.io import MemoryFile

    blob = storage.read(f"catalog/entries/snow_obs/{date}.json")
    if blob is None:
        return None
    entry = json.loads(blob.data)
    cog = storage.read(entry["cog"])
    if cog is None:
        return None
    with MemoryFile(cog.data) as memory, memory.open() as source:
        transform = source.transform
        return Observation(
            date,
            source.read(1),
            source.read(2),
            source.read(3),
            float(transform.c),
            float(transform.f),
            float(transform.a),
            entry["pixel_hash"],
        )


def _on_model_blocks(values: np.ndarray, observation: Observation, grid: Grid) -> np.ndarray:
    """Paste an observation raster on a canvas of the model grid at observation resolution; 255 elsewhere."""
    factor = grid.resolution / observation.resolution
    if factor != int(factor) or (observation.left - grid.left) % observation.resolution:
        raise ValueError("The observation grid does not nest in the model grid")
    factor = int(factor)
    canvas = np.full((grid.height * factor, grid.width * factor), c.NODATA, dtype="uint8")
    column = int(round((observation.left - grid.left) / observation.resolution))
    row = int(round((grid.top - observation.top) / observation.resolution))
    source_rows = slice(max(0, -row), min(values.shape[0], canvas.shape[0] - row))
    source_columns = slice(max(0, -column), min(values.shape[1], canvas.shape[1] - column))
    canvas[
        row + source_rows.start : row + source_rows.stop, column + source_columns.start : column + source_columns.stop
    ] = values[source_rows, source_columns]
    return canvas


@dataclass(frozen=True)
class CellState:
    """Observation summarised on the model grid. `bare` is what drives insertion; `snow` and `valid` score it."""

    bare: np.ndarray
    snow: np.ndarray
    valid: np.ndarray
    shadow: np.ndarray


def cell_state(observation: Observation, grid: Grid) -> CellState:
    classes = _on_model_blocks(observation.classes, observation, grid)
    confidence = _on_model_blocks(observation.confidence, observation, grid)
    flags = _on_model_blocks(observation.flags, observation, grid)
    factor = classes.shape[0] // grid.height

    def per_cell(mask: np.ndarray) -> np.ndarray:
        blocks = mask.reshape(grid.height, factor, grid.width, factor)
        return np.asarray(blocks.sum(axis=(1, 3)), dtype="float64")

    bare = per_cell((classes == c.NO_SNOW) & (confidence == c.CONFIDENCE_HIGH))
    snow = per_cell(classes == c.SNOW)
    decisive = bare + snow
    pixels = factor * factor
    valid = decisive >= MIN_DECISIVE_SHARE * pixels
    share = np.divide(bare, decisive, out=np.zeros_like(bare), where=decisive > 0)
    shaded = per_cell((classes == c.UNKNOWN) & (flags != c.NODATA) & ((flags & c.FLAG_TERRAIN_SHADOW) > 0))
    return CellState(
        bare=valid & (share >= MIN_BARE_SHARE),
        snow=snow >= MIN_DECISIVE_SHARE * pixels,
        valid=valid,
        shadow=~valid & (shaded >= MIN_DECISIVE_SHARE * pixels),
    )


def shadow_bare(state: CellState, elevation: np.ndarray, exclude: np.ndarray) -> np.ndarray:
    """Shaded cells with decided, snow-free cells from 200 m below their elevation up; `exclude` (the ski resort)
    is left out of the statistics because its artificial snow says nothing about natural snow."""
    band = np.floor(np.nan_to_num(elevation, nan=-1.0) / SHADOW_BAND_M).astype("int64")
    decided = state.valid & ~exclude & (band >= 0)
    size = int(band.max()) + 1
    count = np.bincount(band[decided], minlength=size)[::-1].cumsum()[::-1]
    snowy = np.bincount(band[decided & state.snow], minlength=size)[::-1].cumsum()[::-1]
    clear_band = (count >= MIN_BAND_CELLS) & (snowy <= MAX_BAND_SNOW_SHARE * count)
    return np.asarray(state.shadow & (band >= 0) & clear_band[np.maximum(band - SHADOW_REACH_BANDS, 0)])
