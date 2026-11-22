from dataclasses import dataclass, field

import numpy as np

from .forcing import Forcing
from .radiation import index_for_day

DELTA_MIN = -30.0
DELTA_STEP = 0.5
DELTA_COUNT = 101
SNOW_TRANSITION_K = 1.0
MIN_PRECIPITATION_FACTOR = 0.3
MAX_PRECIPITATION_FACTOR = 3.0
MAX_DENSITY = 450.0
COMPACTION_PER_DAY = 0.02
WET_COMPACTION_PER_DAY = 0.05
SNOW_DEPTH_THRESHOLD_M = 0.03


@dataclass
class Domain:
    elevation: np.ndarray
    neighbours: np.ndarray
    weights: np.ndarray
    basin: np.ndarray
    basin_count: int
    cell_area_m2: float
    radiation: np.ndarray


@dataclass
class Tables:
    days: list
    forcing_elevation: np.ndarray
    precipitation_hourly: np.ndarray
    temperature_hourly: np.ndarray
    mean_temperature: np.ndarray
    shortwave: np.ndarray
    positive_degrees: np.ndarray


@dataclass
class Result:
    basin_swe_hm3: np.ndarray
    basin_snowfall_hm3: np.ndarray
    basin_melt_hm3: np.ndarray
    basin_snow_area_km2: np.ndarray
    snow_masks: dict = field(default_factory=dict)
    final_swe: np.ndarray | None = None
    final_depth: np.ndarray | None = None


def build_tables(forcing: Forcing) -> Tables:
    """Day-major tables: arrays are indexed by day first so each day is one contiguous block."""
    deltas = DELTA_MIN + DELTA_STEP * np.arange(DELTA_COUNT, dtype="float32")
    temperature = np.ascontiguousarray(forcing.temperature.transpose(1, 0, 2))
    positive = np.empty(temperature.shape[:2] + (DELTA_COUNT,), dtype="float32")
    for index, delta in enumerate(deltas):
        positive[..., index] = np.maximum(temperature + delta, 0).mean(axis=2)
    return Tables(
        days=forcing.days,
        forcing_elevation=forcing.elevation,
        precipitation_hourly=np.ascontiguousarray(forcing.precipitation.transpose(1, 0, 2)),
        temperature_hourly=temperature,
        mean_temperature=np.ascontiguousarray(temperature.mean(axis=2)),
        shortwave=np.ascontiguousarray(forcing.shortwave.T),
        positive_degrees=positive,
    )


def snowfall_table(tables: Tables, rain_snow_threshold: float) -> np.ndarray:
    """Daily snowfall at each forcing point for every temperature offset."""
    table = np.empty(tables.positive_degrees.shape, dtype="float32")
    for index in range(DELTA_COUNT):
        temperature = tables.temperature_hourly + (DELTA_MIN + DELTA_STEP * index)
        fraction = np.clip(
            (rain_snow_threshold + SNOW_TRANSITION_K - temperature) / (2 * SNOW_TRANSITION_K), 0, 1
        )
        table[..., index] = (tables.precipitation_hourly * fraction).sum(axis=2)
    return table


def _interpolation(point: np.ndarray, delta: np.ndarray):
    position = np.clip((delta - DELTA_MIN) / DELTA_STEP, 0, DELTA_COUNT - 1.001)
    lower = position.astype("int32")
    return point * DELTA_COUNT + lower, (position - lower).astype("float32")


def _lookup(table: np.ndarray, day: int, base: np.ndarray, fraction: np.ndarray) -> np.ndarray:
    row = table[day].reshape(-1)
    return row[base] * (1 - fraction) + row[base + 1] * fraction


def new_snow_density(temperature: np.ndarray) -> np.ndarray:
    return np.clip(67.92 + 51.25 * np.exp(temperature / 2.59), 50.0, 200.0)


class Member:
    """One ensemble member stepped a day at a time, so a run can start from a stored state and be corrected
    by observations between days."""

    def __init__(
        self,
        domain: Domain,
        tables: Tables,
        parameters: dict,
        swe: np.ndarray | None = None,
        depth: np.ndarray | None = None,
    ):
        self.domain = domain
        self.tables = tables
        self.parameters = parameters
        cells = domain.elevation.size
        self.swe = np.zeros(cells, dtype="float32") if swe is None else swe.astype("float32", copy=True)
        self.depth = np.zeros(cells, dtype="float32") if depth is None else depth.astype("float32", copy=True)
        self.snow_table = snowfall_table(tables, parameters["rain_snow_threshold"])
        lapse = parameters["lapse_k_per_km"]
        gradient = parameters["precipitation_gradient_per_100m"]
        self.offsets = [
            -lapse * (domain.elevation - tables.forcing_elevation[domain.neighbours[:, k]]) / 1000.0
            for k in range(domain.neighbours.shape[1])
        ]
        self.interpolation = [
            _interpolation(domain.neighbours[:, k], self.offsets[k]) for k in range(len(self.offsets))
        ]
        self.factors = [
            np.clip(
                1
                + gradient
                * (domain.elevation - tables.forcing_elevation[domain.neighbours[:, k]])
                / 100.0,
                MIN_PRECIPITATION_FACTOR,
                MAX_PRECIPITATION_FACTOR,
            )
            for k in range(domain.neighbours.shape[1])
        ]

    def step(self, day_index: int) -> tuple[np.ndarray, np.ndarray]:
        """Advance one day; returns the snowfall and melt (mm) of the day."""
        domain, tables, parameters = self.domain, self.tables, self.parameters
        day = tables.days[day_index]
        cells = domain.elevation.size
        snowfall = np.zeros(cells, dtype="float32")
        degrees = np.zeros(cells, dtype="float32")
        mean_temperature = np.zeros(cells, dtype="float32")
        shortwave = np.zeros(cells, dtype="float32")
        for k, delta in enumerate(self.offsets):
            point = domain.neighbours[:, k]
            weight = domain.weights[:, k]
            base, fraction = self.interpolation[k]
            snowfall += weight * self.factors[k] * _lookup(self.snow_table, day_index, base, fraction)
            degrees += weight * _lookup(tables.positive_degrees, day_index, base, fraction)
            mean_temperature += weight * (tables.mean_temperature[day_index][point] + delta)
            shortwave += weight * tables.shortwave[day_index][point]
        snowfall *= parameters["precipitation_scale"]
        shortwave *= index_for_day(domain.radiation, day.timetuple().tm_yday)

        potential_melt = (parameters["melt_factor"] + parameters["radiation_factor"] * shortwave) * degrees
        density_new = new_snow_density(mean_temperature)

        swe, depth = self.swe, self.depth
        swe += snowfall
        depth += snowfall / density_new
        melt = np.minimum(swe, potential_melt)
        remaining = np.divide(swe - melt, swe, out=np.zeros_like(swe), where=swe > 0)
        depth *= remaining
        swe -= melt

        density = np.divide(swe, depth, out=np.full_like(swe, MAX_DENSITY), where=depth > 1e-6)
        rate = np.where(melt > 0, WET_COMPACTION_PER_DAY, COMPACTION_PER_DAY)
        density = density + (MAX_DENSITY - density) * (1 - np.exp(-rate))
        self.depth = np.divide(swe, density, out=np.zeros_like(swe), where=swe > 0)
        return snowfall, melt

    def insert_bare(self, bare: np.ndarray) -> None:
        """Direct insertion of an observation: no snow where the cells are observed bare."""
        self.swe[bare] = 0.0
        self.depth[bare] = 0.0


def simulate(
    domain: Domain,
    tables: Tables,
    parameters: dict,
    observation_days: set,
    keep_final: bool,
) -> Result:
    member = Member(domain, tables, parameters)
    day_count = len(tables.days)
    area_km2 = domain.cell_area_m2 / 1e6
    to_hm3 = domain.cell_area_m2 / 1e9
    series = {
        name: np.zeros((day_count, domain.basin_count), dtype="float32")
        for name in ("swe", "snowfall", "melt", "area")
    }
    masks = {}

    for day_index in range(day_count):
        snowfall, melt = member.step(day_index)
        swe = member.swe
        covered = member.depth >= SNOW_DEPTH_THRESHOLD_M
        series["swe"][day_index] = np.bincount(domain.basin, swe, domain.basin_count) * to_hm3
        series["snowfall"][day_index] = np.bincount(domain.basin, snowfall, domain.basin_count) * to_hm3
        series["melt"][day_index] = np.bincount(domain.basin, melt, domain.basin_count) * to_hm3
        series["area"][day_index] = np.bincount(domain.basin, covered, domain.basin_count) * area_km2
        if day_index in observation_days:
            masks[day_index] = np.packbits(covered)

    return Result(
        series["swe"],
        series["snowfall"],
        series["melt"],
        series["area"],
        masks,
        member.swe.copy() if keep_final else None,
        member.depth.copy() if keep_final else None,
    )
