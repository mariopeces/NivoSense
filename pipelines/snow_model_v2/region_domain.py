"""Class domain of a region built from the real DEM, the model domain polygon and the forcing lattice."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pipelines.region import load_region
from pipelines.snow_model.dem import load_elevation, slope_aspect
from pipelines.snow_model.forcing import Forcing, neighbour_weights
from pipelines.snow_model.grid import Grid, build_grid
from pipelines.snow_model.radiation import radiation_index
from pipelines.snow_model.run import rasterize_geometries

from .contract import ClassDomain
from .domain import aspect_classes, build_class_domain

RESOLUTION_M = 100


@dataclass(frozen=True)
class RegionDomain:
    grid: Grid
    cell_index: np.ndarray  # (cells,) flat indices of the model cells in the grid
    elevation: np.ndarray  # (cells,) m
    ski_cells: np.ndarray  # (cells,) bool: artificial snow, never evidence for the natural snow model
    domain: ClassDomain
    elevation_grid: np.ndarray  # (height, width) m, NaN outside the DEM
    # Per-cell inputs of the cell-wise run (`domain.cellwise_domain`), in the order of `cell_index`.
    neighbours: np.ndarray | None = None  # (cells, K) forcing point indices
    weights: np.ndarray | None = None  # (cells, K)
    radiation: np.ndarray | None = None  # (samples, cells)
    aspect: np.ndarray | None = None  # (cells,) int8 aspect classes


def build_region_domain(region_path: Path, forcing: Forcing, cache: Path) -> RegionDomain:
    region = load_region(region_path)
    grid = build_grid(region.bbox, RESOLUTION_M)
    dem_path = cache / f"dem-{region.id}-{grid.signature()}.npy"
    if dem_path.exists():
        elevation = np.load(dem_path)
    else:
        elevation = load_elevation(grid, region.bbox)
        np.save(dem_path, elevation)

    inside = ~np.isnan(elevation)
    if region.domain is not None:
        inside &= rasterize_geometries(region.domain, grid, parts={"domain"})
    ski = rasterize_geometries(
        Path(region.settings.get("snow_model", {}).get("ski_resort", "data/ski_resort.geojson")), grid, all_touched=True
    )
    cell_index = np.flatnonzero(inside.ravel())
    slope, aspect = slope_aspect(elevation, grid.resolution)
    latitude = (region.bbox[1] + region.bbox[3]) / 2
    radiation = radiation_index(latitude, slope.ravel()[cell_index], aspect.ravel()[cell_index])
    rows, columns = np.divmod(cell_index, grid.width)
    cell_x = grid.left + (columns + 0.5) * grid.resolution
    cell_y = grid.top - (rows + 0.5) * grid.resolution
    neighbours, weights = neighbour_weights(forcing, cell_x, cell_y, grid.crs)
    classes = aspect_classes(slope.ravel()[cell_index], aspect.ravel()[cell_index])
    domain = build_class_domain(
        elevation.ravel()[cell_index], classes, neighbours, radiation, grid.cell_area_m2, weights=weights
    )
    return RegionDomain(
        grid,
        cell_index,
        elevation.ravel()[cell_index],
        ski.ravel()[cell_index],
        domain,
        elevation,
        neighbours,
        weights,
        radiation,
        classes,
    )
