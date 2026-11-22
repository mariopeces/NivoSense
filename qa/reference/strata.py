"""Sampling strata of the reference sample and the stratified draw of points.

The strata only decide where points are drawn; no stratum layer is ever a label.
"""

import math
from dataclasses import dataclass

import numpy as np

STRATA = ("snowline_band", "terrain_shadow", "forest", "cloud_edge", "open_terrain")
# Elevation bands inside each stratum, so every stratum holds both low (mostly bare) and high
# (mostly snowy) ground instead of being dominated by the large low-lying part of the park.
ELEVATION_BREAKS_M = (1500.0, 2000.0, 2500.0)

# Local solar incidence angle above 80 degrees: self-shadowed or grazing-lit slopes, which get
# under 17% of the direct irradiance of a slope facing the sun (cosine law), so snow there is
# dark and easily missed. A stratum boundary, not a classification threshold.
SHADOW_COS_INCIDENCE = math.cos(math.radians(80.0))
# WorldCover tree cover over at least half of the 20 m pixel.
FOREST_FRACTION = 0.5
# Open terrain has no tree cell at all in its 20 m pixel.
OPEN_MAX_FOREST_FRACTION = 0.0
# Within 100 m (5 pixels of 20 m) of the boundary between SCL cloud and clear sky, on either side.
CLOUD_EDGE_PIXELS = 5
# Half-width of the snowline band around the snowline elevation read by eye on each date.
SNOWLINE_HALF_WIDTH_M = 200.0
# Cast shadows are traced up to this distance; the relief of the massif (under 2,500 m above
# the surrounding valleys) at the lowest winter sun elevation sampled (about 29 degrees)
# casts shadows under 5 km long.
SHADOW_MAX_DISTANCE_M = 8000.0
# Points of one date at least this far apart, so neighbouring pixels of the same slope do not
# count twice.
MIN_SPACING_M = 200.0


def elevation_band(elevation: np.ndarray) -> np.ndarray:
    """Index of the elevation band (0 lowest) of every pixel."""
    return np.digitize(elevation, ELEVATION_BREAKS_M).astype("int8")


def band_name(index: int) -> str:
    edges = (None, *ELEVATION_BREAKS_M, None)
    low, high = edges[index], edges[index + 1]
    if low is None:
        return f"<{high:.0f}"
    if high is None:
        return f">={low:.0f}"
    return f"{low:.0f}-{high:.0f}"


def cos_incidence(elevation: np.ndarray, resolution: float, sun_azimuth: float, sun_elevation: float) -> np.ndarray:
    """Cosine of the local solar incidence angle on a north-up grid: the dot product of the
    terrain normal (central differences) and the unit vector to the sun. Azimuth is
    clockwise from north, in degrees."""
    north = np.full_like(elevation, np.nan)
    east = np.full_like(elevation, np.nan)
    north[1:-1, :] = (elevation[:-2, :] - elevation[2:, :]) / (2 * resolution)
    east[:, 1:-1] = (elevation[:, 2:] - elevation[:, :-2]) / (2 * resolution)
    azimuth, altitude = math.radians(sun_azimuth), math.radians(sun_elevation)
    sun = (math.sin(azimuth) * math.cos(altitude), math.cos(azimuth) * math.cos(altitude), math.sin(altitude))
    norm = np.sqrt(east**2 + north**2 + 1.0)
    return ((-east * sun[0]) + (-north * sun[1]) + sun[2]) / norm


def cast_shadow(
    elevation: np.ndarray,
    resolution: float,
    sun_azimuth: float,
    sun_elevation: float,
    max_distance: float = SHADOW_MAX_DISTANCE_M,
) -> np.ndarray:
    """Pixels whose line of sight to the sun is blocked by terrain: walk from every pixel
    towards the sun one pixel at a time and compare the terrain with the sun ray
    (nearest-neighbour ray tracing, as in Dozier and Frew 1990 without the horizon
    shortcut). Pixels whose ray leaves the grid are taken as lit."""
    height, width = elevation.shape
    azimuth = math.radians(sun_azimuth)
    rise = math.tan(math.radians(sun_elevation))
    d_col, d_row = math.sin(azimuth), -math.cos(azimuth)
    shadow = np.zeros(elevation.shape, dtype=bool)
    for step in range(1, int(max_distance / resolution) + 1):
        # The same whole-pixel offset applies to every pixel, so the terrain along the ray is
        # the elevation array shifted by it.
        dr, dc = int(round(d_row * step)), int(round(d_col * step))
        if abs(dr) >= height or abs(dc) >= width:
            break
        target = (slice(max(0, -dr), height - max(0, dr)), slice(max(0, -dc), width - max(0, dc)))
        ahead = (slice(max(0, dr), height + min(0, dr)), slice(max(0, dc), width + min(0, dc)))
        shadow[target] |= elevation[ahead] > elevation[target] + step * resolution * rise
    return shadow


def _dilate(mask: np.ndarray, pixels: int) -> np.ndarray:
    """Binary dilation with a square of side 2 * pixels + 1."""
    out = mask.copy()
    for _ in range(pixels):
        grown = out.copy()
        grown[1:, :] |= out[:-1, :]
        grown[:-1, :] |= out[1:, :]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def boundary_zone(inside: np.ndarray, outside: np.ndarray, pixels: int) -> np.ndarray:
    """Pixels of either set that lie within `pixels` of the other set."""
    return (inside & _dilate(outside, pixels)) | (outside & _dilate(inside, pixels))


@dataclass(frozen=True)
class Layers:
    """Per-pixel inputs on one 20 m grid; every array has the grid's shape."""

    elevation: np.ndarray
    cos_incidence: np.ndarray
    cast_shadow: np.ndarray
    tree_fraction: np.ndarray
    cloud: np.ndarray
    clear: np.ndarray
    eligible: np.ndarray


def stratum_masks(layers: Layers, snowline_m: float | None) -> dict[str, np.ndarray]:
    """Where each stratum may draw points. Open terrain is what no other stratum covers."""
    shadow = layers.cast_shadow | (layers.cos_incidence < SHADOW_COS_INCIDENCE)
    forest = layers.tree_fraction >= FOREST_FRACTION
    cloud_edge = boundary_zone(layers.cloud, layers.clear, CLOUD_EDGE_PIXELS)
    if snowline_m is None:
        snowline = np.zeros_like(layers.eligible)
    else:
        snowline = np.abs(layers.elevation - snowline_m) <= SNOWLINE_HALF_WIDTH_M
    open_terrain = ~shadow & ~cloud_edge & ~snowline & (layers.tree_fraction <= OPEN_MAX_FOREST_FRACTION) & layers.clear
    masks = {
        "snowline_band": snowline,
        "terrain_shadow": shadow,
        "forest": forest,
        "cloud_edge": cloud_edge,
        "open_terrain": open_terrain,
    }
    return {name: mask & layers.eligible for name, mask in masks.items()}


@dataclass(frozen=True)
class Draw:
    row: int
    col: int
    stratum: str
    band: int
    cell_pixels: int


def split_quota(total: int, cells: list[int]) -> list[int]:
    """`total` points shared as evenly as possible over cells with room, never giving a cell
    more points than it has pixels."""
    quota = [0] * len(cells)
    remaining = total
    open_cells = [index for index, size in enumerate(cells) if size > 0]
    while remaining > 0 and open_cells:
        share, extra = divmod(remaining, len(open_cells))
        next_open = []
        for rank, index in enumerate(open_cells):
            give = min(share + (1 if rank < extra else 0), cells[index] - quota[index])
            quota[index] += give
            remaining -= give
            if quota[index] < cells[index]:
                next_open.append(index)
        if share == 0 and extra == 0:
            break
        open_cells = next_open
    return quota


def draw_points(
    masks: dict[str, np.ndarray],
    bands: np.ndarray,
    quotas: dict[str, int],
    rng: np.random.Generator,
    resolution: float,
    min_spacing: float = MIN_SPACING_M,
) -> list[Draw]:
    """Simple random sample of each (stratum, elevation band) cell, quotas split evenly over
    the bands of a stratum; candidates closer than `min_spacing` to a point already drawn on
    the date are skipped. Strata are drawn in `STRATA` order."""
    taken: list[tuple[int, int]] = []
    spacing_px = min_spacing / resolution
    draws: list[Draw] = []
    band_count = len(ELEVATION_BREAKS_M) + 1
    for stratum in STRATA:
        mask = masks[stratum]
        cells = [np.flatnonzero(mask & (bands == band)) for band in range(band_count)]
        band_quotas = split_quota(quotas.get(stratum, 0), [len(c) for c in cells])
        for band, (candidates, quota) in enumerate(zip(cells, band_quotas)):
            if quota == 0:
                continue
            got = 0
            for flat in rng.permutation(candidates):
                row, col = divmod(int(flat), mask.shape[1])
                if any((row - r) ** 2 + (col - c) ** 2 < spacing_px**2 for r, c in taken):
                    continue
                taken.append((row, col))
                draws.append(Draw(row, col, stratum, band, len(candidates)))
                got += 1
                if got == quota:
                    break
    return draws
