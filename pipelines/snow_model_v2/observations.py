"""Observation operator of the smoother (docs/snow-methodology.md section 3.6).

For every class of the domain and every clear Sentinel-2 date: the snow share among the decisive 20 m pixels
(snow, or high-confidence bare ground, as in `pipelines.snow_model.insertion.cell_state`), pooled over the
100 m cells of the class that have at least half of their pixels decisive. Cloud, unknown and terrain-shadow
pixels are not evidence and are left out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from pipelines.catalog.storage import Storage
from pipelines.snow_model.grid import Grid
from pipelines.snow_model.insertion import (
    MIN_DECISIVE_SHARE,
    CellState,
    Observation,
    _on_model_blocks,
    load_observation,
    shadow_bare,
)
from pipelines.snow_obs import classify as c

from .contract import ClassDomain

ERROR_FLOOR = 0.10  # Landsat fSCA sd at about 480 m, Margulis et al. 2019, as a floor for a pooled class
ERROR_PER_CELL = 0.5  # sd of the share of one cell; the pooled mean shrinks it by sqrt(n)
SHADOW_CELL_WEIGHT = 0.5  # a shadow-inherited bare cell counts as half a decisive cell


@dataclass(frozen=True)
class Observations:
    """Observed class fractions aligned with the classes of the domain. Axis order: classes C, dates K."""

    days: list[date]
    fraction: np.ndarray  # (C, K) observed snow share, NaN where the class has no usable cell
    n_cells: np.ndarray  # (C, K) decisive cells pooled (shadow-inherited cells count SHADOW_CELL_WEIGHT)
    sigma: np.ndarray  # (C, K) observation error, NaN where fraction is NaN
    shadow_cells: np.ndarray  # (C, K) number of shadow-inherited bare cells in the pool

    @property
    def usable(self) -> np.ndarray:
        return np.isfinite(self.fraction)

    def day_index(self, forcing_days: list[date]) -> np.ndarray:
        position = {day: index for index, day in enumerate(forcing_days)}
        return np.array([position[day] for day in self.days], dtype="int64")

    def select(self, keep: np.ndarray) -> Observations:
        """The dates where `keep` (K,) is true."""
        return Observations(
            [day for day, k in zip(self.days, keep) if k],
            self.fraction[:, keep],
            self.n_cells[:, keep],
            self.sigma[:, keep],
            self.shadow_cells[:, keep],
        )


def observation_error(n_cells: np.ndarray) -> np.ndarray:
    return np.sqrt(ERROR_FLOOR**2 + (ERROR_PER_CELL / np.sqrt(np.maximum(n_cells, 1e-9))) ** 2)


def pixel_counts(observation: Observation, grid: Grid) -> tuple[np.ndarray, np.ndarray, CellState, int]:
    """Per 100 m cell: snow pixels, decisive pixels, the cell state (for shadow inheritance) and pixels per cell."""
    classes = _on_model_blocks(observation.classes, observation, grid)
    confidence = _on_model_blocks(observation.confidence, observation, grid)
    flags = _on_model_blocks(observation.flags, observation, grid)
    factor = classes.shape[0] // grid.height

    def per_cell(mask: np.ndarray) -> np.ndarray:
        return np.asarray(mask.reshape(grid.height, factor, grid.width, factor).sum(axis=(1, 3)), dtype="float64")

    snow = per_cell(classes == c.SNOW)
    bare = per_cell((classes == c.NO_SNOW) & (confidence == c.CONFIDENCE_HIGH))
    shaded = per_cell((classes == c.UNKNOWN) & (flags != c.NODATA) & ((flags & c.FLAG_TERRAIN_SHADOW) > 0))
    pixels = factor * factor
    decisive = snow + bare
    valid = decisive >= MIN_DECISIVE_SHARE * pixels
    state = CellState(
        bare=valid & (bare >= 0.85 * decisive),
        snow=snow >= MIN_DECISIVE_SHARE * pixels,
        valid=valid,
        shadow=~valid & (shaded >= MIN_DECISIVE_SHARE * pixels),
    )
    return snow, decisive, state, pixels


def class_fractions(
    observation: Observation,
    grid: Grid,
    cell_index: np.ndarray,
    domain: ClassDomain,
    exclude: np.ndarray | None = None,
    elevation_grid: np.ndarray | None = None,
    use_shadow: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Observed snow share, decisive cell count, error and shadow-inherited cell count of every class on one date.

    `exclude` flags domain cells that carry no evidence (the ski resort: artificial snow). With `use_shadow`
    shaded cells that `insertion.shadow_bare` calls bare join the pool as snow-free evidence at reduced weight;
    that needs `elevation_grid`.
    """
    snow, decisive, state, pixels = pixel_counts(observation, grid)
    snow_c, decisive_c = snow.ravel()[cell_index], decisive.ravel()[cell_index]
    usable = state.valid.ravel()[cell_index]
    if exclude is not None:
        usable = usable & ~exclude
    count = domain.class_count
    member = (domain.class_of_cell >= 0) & usable
    ids = domain.class_of_cell[member]
    snow_sum = np.bincount(ids, snow_c[member], count)
    decisive_sum = np.bincount(ids, decisive_c[member], count)
    n_cells = np.bincount(ids, minlength=count).astype("float64")

    shadow_cells = np.zeros(count)
    if use_shadow:
        if elevation_grid is None:
            raise ValueError("use_shadow needs elevation_grid")
        grid_exclude = np.zeros(grid.height * grid.width, dtype=bool)
        if exclude is not None:
            grid_exclude[cell_index] = exclude
        inherited = shadow_bare(state, elevation_grid, grid_exclude.reshape(grid.height, grid.width)).ravel()[
            cell_index
        ]
        inherited = inherited & (domain.class_of_cell >= 0)
        shadow_cells = np.bincount(domain.class_of_cell[inherited], minlength=count).astype("float64")
        decisive_sum = decisive_sum + shadow_cells * pixels
        n_cells = n_cells + SHADOW_CELL_WEIGHT * shadow_cells
    with np.errstate(invalid="ignore", divide="ignore"):
        fraction = np.where(decisive_sum > 0, snow_sum / decisive_sum, np.nan)
    sigma = np.where(np.isfinite(fraction), observation_error(n_cells), np.nan)
    return fraction, n_cells, sigma, shadow_cells


def load_observations(
    storage: Storage,
    dates: list[date],
    domain: ClassDomain,
    grid: Grid,
    cell_index: np.ndarray,
    exclude: np.ndarray | None = None,
    elevation_grid: np.ndarray | None = None,
    use_shadow: bool = False,
) -> Observations:
    """Observations of the dates the catalogue holds a `snow_obs` entry for; other dates are skipped.

    `cell_index` gives the flat grid index of every domain cell (the order of `domain.class_of_cell`).
    """
    kept: list[date] = []
    columns: list[tuple[np.ndarray, ...]] = []
    for day in sorted(dates):
        observation = load_observation(storage, day.isoformat())
        if observation is None:
            continue
        fraction, n_cells, sigma, shadow = class_fractions(
            observation, grid, cell_index, domain, exclude, elevation_grid, use_shadow
        )
        if np.isfinite(fraction).any():
            kept.append(day)
            columns.append((fraction, n_cells, sigma, shadow))
    count = domain.class_count
    stack = [np.stack([col[i] for col in columns], axis=1) if columns else np.zeros((count, 0)) for i in range(4)]
    return Observations(kept, stack[0], stack[1], stack[2], stack[3])
