"""Daily snow probability per 20 m pixel from the observed snow cover (README section 6).

For each day and pixel:
1. observed that day (snow or no snow): that value;
2. else, if the pixel's last and next observations agree: that value, carried;
3. else (they disagree, or one of them does not exist yet): the probability from the snowline of
   the nearest observation dates. The snowline is fitted per date and per terrain group (eight
   aspect sectors and flat ground) as a logistic curve of snow against elevation, and
   interpolated linearly in time between the last observation date on or before the day and
   the first one after it.

Snow probability is 1 or 0 in cases 1 and 2. v1 has no model input (README section 6 lists the
model's snow probability as an optional input once the model assimilates; T2.x).
"""

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from pipelines.snow_obs import classify as observed_classes

NODATA = -1.0

# Method band: how each pixel's value was decided.
OBSERVED = 0
BRACKETED = 1
SNOWLINE_BETWEEN = 2
SNOWLINE_NO_NEXT = 3
SNOWLINE_NO_LAST = 4

# Terrain groups: aspect sectors of 45 degrees clockwise from north (0 = N, 1 = NE, ... 7 = NW)
# and flat ground. Slope under 5 degrees has no meaningful aspect at 20 m on a 30 m DEM.
SECTORS = 8
FLAT = SECTORS
GROUPS = SECTORS + 1
FLAT_SLOPE_DEG = 5.0
# Elevation bands of the snowline fit. 50 m keeps over a hundred observed pixels in nearly every
# band of every group on a clear date, so the snow fraction of a band is not noise.
ELEVATION_BAND_M = 50.0
MIN_BAND_PIXELS = 100
# A fit whose observed bands stop short of the group's lowest or highest terrain by more than
# this cannot tell where the snowline is when it lies beyond them (cloud over the summits, say).
CENSORED_MARGIN_M = 100.0
# When the whole observed range is snow (or bare), the snowline is put this far below (above)
# it, with the narrowest width, so every observed band keeps its class.
BEYOND_RANGE_M = 200.0
MIN_WIDTH_M = 10.0


@dataclass(frozen=True)
class Terrain:
    """Static inputs on the 20 m grid. `fit` is where snowline fits look (inside the domain,
    outside the ski resort, whose artificial snow is not a snowline)."""

    elevation: np.ndarray
    group: np.ndarray
    inside: np.ndarray
    fit: np.ndarray


@dataclass(frozen=True)
class Observation:
    day: date
    classes: np.ndarray
    source: str


@dataclass(frozen=True)
class Snowline:
    """Per terrain group: the elevation of 50% snow and the logistic width (m); NaN where the
    date says nothing about it."""

    elevation: np.ndarray
    width: np.ndarray


@dataclass
class Filled:
    probability: np.ndarray
    snow: np.ndarray
    days_since: np.ndarray
    method: np.ndarray
    sources: set[str] = field(default_factory=set)


def terrain_groups(slope: np.ndarray, aspect: np.ndarray) -> np.ndarray:
    """Aspect sector (0..7) per pixel, FLAT where the slope is under FLAT_SLOPE_DEG. Radians in."""
    sector = (np.floor((np.degrees(aspect) + 22.5) / 45.0) % SECTORS).astype("uint8")
    sector[np.degrees(slope) < FLAT_SLOPE_DEG] = FLAT
    return sector


def isotonic_increasing(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Weighted least-squares non-decreasing fit (pool adjacent violators)."""
    blocks: list[list[float]] = []  # [mean, weight, length]
    for value, weight in zip(values.tolist(), weights.tolist()):
        blocks.append([value, weight, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            mean2, weight2, length2 = blocks.pop()
            mean1, weight1, length1 = blocks.pop()
            total = weight1 + weight2
            blocks.append([(mean1 * weight1 + mean2 * weight2) / total, total, length1 + length2])
    return np.array([mean for mean, _, length in blocks for _ in range(int(length))])


def _crossing(centres: np.ndarray, fraction: np.ndarray, level: float) -> float | None:
    """Lowest elevation where the non-decreasing curve reaches `level`, linearly interpolated."""
    above = np.flatnonzero(fraction >= level)
    if above.size == 0:
        return None
    i = int(above[0])
    if i == 0:
        return None
    f0, f1 = fraction[i - 1], fraction[i]
    return float(centres[i - 1] + (level - f0) / (f1 - f0) * (centres[i] - centres[i - 1]))


def fit_snowline(classes: np.ndarray, terrain: Terrain) -> Snowline:
    elevation = np.full(GROUPS, np.nan)
    width = np.full(GROUPS, np.nan)
    seen = terrain.fit & np.isin(classes, (observed_classes.SNOW, observed_classes.NO_SNOW))
    for group in range(GROUPS):
        in_group = terrain.fit & (terrain.group == group)
        if not in_group.any():
            continue
        group_bands = np.floor(terrain.elevation[in_group] / ELEVATION_BAND_M).astype("int64")
        low, high = int(group_bands.min()), int(group_bands.max())
        selected = seen & (terrain.group == group)
        bands = np.floor(terrain.elevation[selected] / ELEVATION_BAND_M).astype("int64") - low
        snow = classes[selected] == observed_classes.SNOW
        counts = np.bincount(bands, minlength=high - low + 1)
        snow_counts = np.bincount(bands, weights=snow, minlength=high - low + 1)
        keep = np.flatnonzero(counts >= MIN_BAND_PIXELS)
        if keep.size == 0:
            continue
        centres = (keep + low + 0.5) * ELEVATION_BAND_M
        fraction = isotonic_increasing(snow_counts[keep] / counts[keep], counts[keep].astype(float))
        reaches_bottom = centres[0] - (low + 0.5) * ELEVATION_BAND_M <= CENSORED_MARGIN_M
        reaches_top = (high + 0.5) * ELEVATION_BAND_M - centres[-1] <= CENSORED_MARGIN_M
        mid = _crossing(centres, fraction, 0.5)
        if mid is not None:
            elevation[group] = mid
            # A logistic curve rises from 25% to 50% and from 50% to 75% over width * ln 3 each.
            lower, upper = _crossing(centres, fraction, 0.25), _crossing(centres, fraction, 0.75)
            if lower is not None and upper is not None:
                spread = (upper - lower) / (2 * math.log(3))
            elif lower is not None or upper is not None:
                spread = abs(mid - (lower if lower is not None else upper)) / math.log(3)  # type: ignore[operator]
            else:
                spread = 0.0
            width[group] = max(spread, MIN_WIDTH_M)
        elif fraction[0] >= 0.5 and reaches_bottom:
            elevation[group], width[group] = centres[0] - BEYOND_RANGE_M, MIN_WIDTH_M
        elif fraction[-1] < 0.5 and reaches_top:
            elevation[group], width[group] = centres[-1] + BEYOND_RANGE_M, MIN_WIDTH_M
    return Snowline(elevation, width)


@dataclass(frozen=True)
class SnowlineTable:
    """Snowlines of every observation date, gaps filled per group from the nearest date in
    time (the earlier one on a tie); `source[i, g]` is the date index each value comes from."""

    elevation: np.ndarray
    width: np.ndarray
    source: np.ndarray


def snowline_table(observations: list[Observation], fits: list[Snowline]) -> SnowlineTable:
    n = len(observations)
    elevation = np.stack([fit.elevation for fit in fits]) if n else np.zeros((0, GROUPS))
    width = np.stack([fit.width for fit in fits]) if n else np.zeros((0, GROUPS))
    source = np.tile(np.arange(n)[:, None], (1, GROUPS))
    ordinals = np.array([o.day.toordinal() for o in observations])
    for group in range(GROUPS):
        valid = np.flatnonzero(~np.isnan(elevation[:, group]))
        if valid.size == 0:
            continue
        for i in np.flatnonzero(np.isnan(elevation[:, group])):
            j = int(valid[np.argmin(np.abs(ordinals[valid] - ordinals[i]) * 2 + (valid > i))])
            elevation[i, group], width[i, group], source[i, group] = elevation[j, group], width[j, group], j
    return SnowlineTable(elevation, width, source)


def _scan(
    observations: list[Observation], order: range, inside: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Value and observation index of the first observed (snow / no snow) pixel along `order`."""
    value = np.full(inside.shape, 255, dtype="uint8")
    index = np.full(inside.shape, -1, dtype="int32")
    pending = inside.copy()
    for i in order:
        classes = observations[i].classes
        take = pending & ((classes == observed_classes.SNOW) | (classes == observed_classes.NO_SNOW))
        value[take] = classes[take]
        index[take] = i
        pending &= ~take
        if not pending.any():
            break
    return value, index


def fill(day: date, observations: list[Observation], table: SnowlineTable, terrain: Terrain) -> Filled:
    """The gap-filled snow cover of one day. `observations` are sorted by date."""
    days = np.array([o.day.toordinal() for o in observations])
    before = int(np.searchsorted(days, day.toordinal(), side="right"))  # observations on or before
    last_value, last_index = _scan(observations, range(before - 1, -1, -1), terrain.inside)
    next_value, next_index = _scan(observations, range(before, len(observations)), terrain.inside)
    has_last, has_next = last_index >= 0, next_index >= 0
    last_day = np.where(has_last, days[np.maximum(last_index, 0)], 0) if days.size else np.zeros_like(last_index)

    observed = has_last & (last_day == day.toordinal())
    bracketed = has_last & has_next & ~observed & (last_value == next_value)
    by_snowline = terrain.inside & (has_last | has_next) & ~observed & ~bracketed

    probability = np.full(terrain.inside.shape, NODATA, dtype="float32")
    carried = observed | bracketed
    probability[carried] = (last_value[carried] == observed_classes.SNOW).astype("float32")

    sources: set[str] = {observations[i].source for i in np.unique(last_index[carried & has_last])}
    if by_snowline.any():
        a, b = before - 1, before  # nearest observation dates on or before, and after, the day
        groups = terrain.group[by_snowline]
        if a >= 0 and b < len(observations):
            weight = (day.toordinal() - days[a]) / (days[b] - days[a])
            line = (1 - weight) * table.elevation[a, groups] + weight * table.elevation[b, groups]
            spread = (1 - weight) * table.width[a, groups] + weight * table.width[b, groups]
            rows = [a, b]
        else:
            row = a if a >= 0 else b
            line, spread, rows = table.elevation[row, groups], table.width[row, groups], [row]
        z = (terrain.elevation[by_snowline] - line) / spread
        probability[by_snowline] = np.where(np.isnan(z), NODATA, 1.0 / (1.0 + np.exp(-np.clip(z, -50, 50))))
        for row in rows:
            sources |= {observations[i].source for i in np.unique(table.source[row, np.unique(groups)])}
        sources |= {observations[i].source for i in np.unique(last_index[by_snowline & has_last])}
        sources |= {observations[i].source for i in np.unique(next_index[by_snowline & has_next])}
    sources |= {observations[i].source for i in np.unique(next_index[bracketed])}

    method = np.full(terrain.inside.shape, 255, dtype="uint8")
    method[observed] = OBSERVED
    method[bracketed] = BRACKETED
    method[by_snowline & has_last & has_next] = SNOWLINE_BETWEEN
    method[by_snowline & has_last & ~has_next] = SNOWLINE_NO_NEXT
    method[by_snowline & ~has_last] = SNOWLINE_NO_LAST
    valid = probability >= 0
    method[~valid] = 255

    days_since = np.full(terrain.inside.shape, NODATA, dtype="float32")
    with_last = valid & has_last
    days_since[with_last] = (day.toordinal() - last_day[with_last]).astype("float32")
    snow = valid & (probability >= 0.5)
    return Filled(probability, snow, days_since, method, sources)
