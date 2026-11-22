"""Class-reduced and cell-wise model domains (docs/snow-methodology.md section 3.5)."""

from __future__ import annotations

import numpy as np

from .contract import ClassDomain

BAND_M = 100.0
MIN_CELLS = 20
FLAT_SLOPE_DEG = 5.0
ASPECT_NAMES = ("N", "E", "S", "W", "flat")


def aspect_classes(slope: np.ndarray, aspect: np.ndarray, flat_slope_deg: float = FLAT_SLOPE_DEG) -> np.ndarray:
    """0 N, 1 E, 2 S, 3 W, 4 flat. `aspect` is the downslope azimuth clockwise from north in radians
    (pipelines.snow_model.dem.slope_aspect), so a north-facing slope has aspect near 0."""
    sector = np.floor(((np.degrees(aspect) + 45.0) % 360.0) / 90.0).astype("int8")
    return np.where(np.degrees(slope) < flat_slope_deg, 4, sector).astype("int8")


def cellwise_domain(
    elevation: np.ndarray,
    neighbours: np.ndarray,
    weights: np.ndarray,
    radiation: np.ndarray,
    cell_area_m2: float,
    aspect: np.ndarray | None = None,
) -> ClassDomain:
    """One class per cell, keeping the full neighbour interpolation of v1. Used for the final maps."""
    cells = elevation.size
    return ClassDomain(
        class_of_cell=np.arange(cells, dtype="int32"),
        elevation=elevation.astype("float32"),
        aspect=np.full(cells, 4, dtype="int8") if aspect is None else aspect.astype("int8"),
        neighbours=neighbours.astype("int32"),
        weights=weights.astype("float32"),
        radiation=radiation.astype("float32"),
        cell_count=np.ones(cells, dtype="int32"),
        cell_area_m2=cell_area_m2,
    )


def build_class_domain(
    elevation: np.ndarray,
    aspect: np.ndarray,
    neighbours: np.ndarray,
    radiation: np.ndarray,
    cell_area_m2: float,
    band_m: float = BAND_M,
    min_cells: int = MIN_CELLS,
    weights: np.ndarray | None = None,
) -> ClassDomain:
    """Classes of cells sharing an elevation band, an aspect class and the nearest forcing point.

    `aspect` holds the classes of `aspect_classes`; `neighbours` is (cells, K) with the nearest forcing point
    first, as `pipelines.snow_model.forcing.neighbour_weights` returns it; `radiation` is (samples, cells).
    A class runs on its mean elevation and mean radiation index. Without `weights` it uses its nearest forcing
    point only; with the (cells, K) weights of the cells it uses the K points carrying most of the mean cell
    weight, renormalised, which follows the cell-wise interpolation of v1 more closely. Cells
    in classes below `min_cells` (and cells without elevation) get class -1: they are not represented in the
    smoother and are covered only by the final cell-wise run.
    """
    valid = np.isfinite(elevation)
    band = np.floor(np.where(valid, elevation, 0) / band_m).astype("int64")
    point = neighbours[:, 0].astype("int64")
    key = (band * 5 + aspect.astype("int64")) * (int(point.max()) + 1) + point
    key = np.where(valid, key, -1)
    unique, inverse, counts = np.unique(key, return_inverse=True, return_counts=True)
    keep = (counts >= min_cells) & (unique >= 0)
    new_id = np.cumsum(keep) - 1
    class_of_cell = np.where(keep[inverse], new_id[inverse], -1).astype("int32")

    member = class_of_cell >= 0
    ids = class_of_cell[member]
    count = int(keep.sum())
    cell_count = np.bincount(ids, minlength=count).astype("int32")
    class_elevation = np.bincount(ids, elevation[member], count) / cell_count
    class_radiation = np.stack(
        [np.bincount(ids, radiation[sample][member], count) / cell_count for sample in range(radiation.shape[0])]
    )
    first = np.zeros(count, dtype="int64")
    first[ids[::-1]] = np.flatnonzero(member)[::-1]
    if weights is None:
        class_neighbours, class_weights = neighbours[first, :1], np.ones((count, 1))
    else:
        columns = neighbours.shape[1]
        accumulated = np.zeros((count, int(neighbours.max()) + 1))
        for k in range(columns):
            np.add.at(accumulated, (ids, neighbours[member, k]), weights[member, k])
        class_neighbours = np.argsort(-accumulated, axis=1)[:, :columns]
        class_weights = np.take_along_axis(accumulated, class_neighbours, axis=1)
        class_weights = class_weights / class_weights.sum(axis=1, keepdims=True)
    return ClassDomain(
        class_of_cell=class_of_cell,
        elevation=class_elevation.astype("float32"),
        aspect=aspect[first].astype("int8"),
        neighbours=class_neighbours.astype("int32"),
        weights=class_weights.astype("float32"),
        radiation=class_radiation.astype("float32"),
        cell_count=cell_count,
        cell_area_m2=cell_area_m2,
    )
