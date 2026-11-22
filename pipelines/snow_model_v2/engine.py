"""Vectorised ensemble forward model: N members x classes, one numpy pass per day.

Same daily physics as pipelines/snow_model/snowpack.py (temperature-index melt with a radiation term, snowfall
fraction ramp, density curve and compaction) with these changes (docs/snow-methodology.md section 3.4):
member parameters b0, dT and rho_s, a storm-level lognormal precipitation multiplier, and the sub-grid
depletion curve of `depletion.py`.

Cost layout: the member-independent hourly work is done once per season into tables over a temperature offset
(like v1). A member only enters through the offset `-L dz/1000 + dT` of each class, which is constant in time,
so each day is a table lookup, not an hourly computation. The rain/snow threshold Ts shifts the offset of the
snowfall table, so one snowfall table serves all members.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from pipelines.snow_model.radiation import index_for_day
from pipelines.snow_model.snowpack import (
    COMPACTION_PER_DAY,
    MAX_DENSITY,
    MAX_PRECIPITATION_FACTOR,
    MIN_PRECIPITATION_FACTOR,
    SNOW_TRANSITION_K,
    WET_COMPACTION_PER_DAY,
    new_snow_density,
)

from . import depletion
from .contract import ClassDomain, EnsembleRun, MemberParameters, SeasonForcing, season_seed

OFFSET_MIN = -40.0
OFFSET_STEP = 0.5
OFFSET_COUNT = 141  # to +30 K
SNOW_OFFSET_MIN = -45.0  # offset minus Ts, Ts up to 2.5 C
SNOW_OFFSET_COUNT = 151
CHUNK_ELEMENTS = 400_000


@dataclass
class _Tables:
    degrees: np.ndarray  # (D, P * OFFSET_COUNT) mean positive temperature of the day (degree days)
    snow: np.ndarray  # (D, S, P * SNOW_OFFSET_COUNT) snowfall per storm slot (mm)
    mean_temperature: np.ndarray  # (D, P)
    slot_storm: np.ndarray  # (D, S) storm id of each slot, -1 for dry hours or padding


def _build_tables(forcing: SeasonForcing) -> _Tables:
    temperature, precipitation = forcing.temperature, forcing.precipitation
    points, days = temperature.shape[:2]

    offsets = OFFSET_MIN + OFFSET_STEP * np.arange(OFFSET_COUNT, dtype="float32")
    degrees = np.empty((days, points, OFFSET_COUNT), dtype="float32")
    for index, offset in enumerate(offsets):
        degrees[..., index] = np.maximum(temperature + offset, 0).mean(axis=2).T

    slot_of_hour = np.zeros((days, 24), dtype="int64")
    slot_lists = []
    for day in range(days):
        ids = np.unique(forcing.storm_id[day])
        slot_lists.append(ids)
        slot_of_hour[day] = np.searchsorted(ids, forcing.storm_id[day])
    slots = max(len(ids) for ids in slot_lists)
    slot_storm = np.full((days, slots), -1, dtype="int64")
    for day, ids in enumerate(slot_lists):
        slot_storm[day, : len(ids)] = ids
    masks = np.stack([slot_of_hour == s for s in range(slots)]).astype("float32")  # (S, D, 24)

    snow = np.zeros((days, slots, points, SNOW_OFFSET_COUNT), dtype="float32")
    for index in range(SNOW_OFFSET_COUNT):
        offset = SNOW_OFFSET_MIN + OFFSET_STEP * index
        fraction = np.clip((SNOW_TRANSITION_K - (temperature + offset)) / (2 * SNOW_TRANSITION_K), 0, 1)
        snowy = precipitation * fraction  # (P, D, 24)
        for s in range(slots):
            snow[:, s, :, index] = (snowy * masks[s][None]).sum(axis=2).T
    return _Tables(
        degrees.reshape(days, -1),
        snow.reshape(days, slots, -1),
        np.ascontiguousarray(temperature.mean(axis=2).T),
        slot_storm,
    )


def _interpolation(point: np.ndarray, offset: np.ndarray, first: float, count: int) -> tuple[np.ndarray, np.ndarray]:
    position = np.clip((offset - first) / OFFSET_STEP, 0, count - 1.001)
    lower = position.astype("int64")
    return point * count + lower, (position - lower).astype("float32")


def _lookup(row: np.ndarray, base: np.ndarray, fraction: np.ndarray) -> np.ndarray:
    return row[base] * (1 - fraction) + row[base + 1] * fraction


def _run_chunk(
    domain: ClassDomain,
    forcing: SeasonForcing,
    tables: _Tables,
    parameters: MemberParameters,
    store: np.ndarray,
    outputs: dict[str, np.ndarray],
    members: slice,
) -> None:
    p = parameters.take(members)
    count, classes = p.count, domain.class_count
    neighbours, weights = domain.neighbours.astype("int64"), domain.weights
    dz = domain.elevation[:, None] - forcing.elevation[neighbours]  # (C, K)

    offset = (-p.L[:, None, None] * dz[None] / 1000.0 + p.dT[:, None, None]).astype("float32")  # (M, C, K)
    base_d, frac_d = _interpolation(neighbours[None], offset, OFFSET_MIN, OFFSET_COUNT)
    snow_offset = offset - p.Ts[:, None, None].astype("float32")
    base_s, frac_s = _interpolation(neighbours[None], snow_offset, SNOW_OFFSET_MIN, SNOW_OFFSET_COUNT)
    gradient = np.clip(
        1 + p.g[:, None, None] * dz[None] / 100.0, MIN_PRECIPITATION_FACTOR, MAX_PRECIPITATION_FACTOR
    ).astype("float32")
    snow_weight = (weights[None] * gradient * p.b0[:, None, None].astype("float32")).astype("float32")
    offset_mean = (weights[None] * offset).sum(axis=2)  # (M, C)

    ddf = p.DDF[:, None].astype("float32")
    rad = p.rad[:, None].astype("float32")
    beta = p.beta[:, None].astype("float32")
    storm_noise = np.exp(p.xi).astype("float32")
    noise_with_dry = np.concatenate([storm_noise, np.ones((count, 1), dtype="float32")], axis=1)
    dry_column = noise_with_dry.shape[1] - 1

    shape = (count, classes)
    swe = np.zeros(shape, dtype="float32")
    depth = np.zeros(shape, dtype="float32")
    s_peak = np.zeros(shape, dtype="float32")
    m_cum = np.zeros(shape, dtype="float32")
    curve = np.zeros(shape, dtype="float32")
    position = {int(day): index for index, day in enumerate(store)}

    for day_index, day in enumerate(forcing.days):
        row_degrees = tables.degrees[day_index]
        degrees = (weights[None] * _lookup(row_degrees, base_d, frac_d)).sum(axis=2)

        snowfall = np.zeros(shape, dtype="float32")
        for slot, storm in enumerate(tables.slot_storm[day_index]):
            column = dry_column if storm < 0 else storm
            row = tables.snow[day_index, slot]
            flat = (snow_weight * _lookup(row, base_s, frac_s)).sum(axis=2)
            snowfall += noise_with_dry[:, column][:, None] * flat

        mean_temperature = (weights * tables.mean_temperature[day_index][neighbours]).sum(axis=1)[None] + offset_mean
        shortwave = (weights * forcing.shortwave[:, day_index][neighbours]).sum(axis=1)
        shortwave = shortwave * index_for_day(domain.radiation, day.timetuple().tm_yday)
        potential_melt = (ddf + rad * shortwave[None]) * degrees

        total = swe + snowfall
        swe, s_peak, m_cum, curve, melt = depletion.step(swe, s_peak, m_cum, curve, snowfall, potential_melt, beta)
        depth = depth + snowfall / new_snow_density(mean_temperature)
        remaining = np.divide(swe, total, out=np.zeros_like(swe), where=total > 0)
        depth = depth * remaining

        density = np.divide(swe, depth, out=np.full_like(swe, MAX_DENSITY), where=depth > 1e-6)
        rate = np.where(melt > 0, WET_COMPACTION_PER_DAY, COMPACTION_PER_DAY)
        density = density + (MAX_DENSITY - density) * (1 - np.exp(-rate))
        depth = np.divide(swe, density, out=np.zeros_like(swe), where=swe > 0)

        slot_out = position.get(day_index)
        if slot_out is not None:
            outputs["swe"][members, :, slot_out] = swe
            outputs["depth"][members, :, slot_out] = depth / p.rho_s[:, None].astype("float32")
            outputs["f_sca"][members, :, slot_out] = depletion.covered_fraction(s_peak, m_cum, beta) * (swe > 0)
            outputs["s_peak"][members, :, slot_out] = s_peak
            outputs["m_cum"][members, :, slot_out] = m_cum


def run_ensemble(
    domain: ClassDomain,
    forcing: SeasonForcing,
    parameters: MemberParameters,
    observation_days: Sequence[int],
    workers: int = 1,
) -> EnsembleRun:
    if parameters.xi.shape[1] < forcing.storm_count:
        raise ValueError("parameters.xi needs one column per storm of the forcing")
    day_count = len(forcing.days)
    store = np.array(sorted({int(d) for d in observation_days} | {day_count - 1}), dtype="int64")
    if store.min() < 0 or store.max() >= day_count:
        raise ValueError("observation_days outside the forcing period")

    tables = _build_tables(forcing)
    shape = (parameters.count, domain.class_count, len(store))
    outputs = {name: np.zeros(shape, dtype="float32") for name in ("swe", "depth", "f_sca", "s_peak", "m_cum")}
    size = max(1, CHUNK_ELEMENTS // max(domain.class_count, 1))
    chunks = [slice(start, min(start + size, parameters.count)) for start in range(0, parameters.count, size)]

    def work(members: slice) -> None:
        _run_chunk(domain, forcing, tables, parameters, store, outputs, members)

    if workers > 1 and len(chunks) > 1:
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(work, chunks))
    else:
        for members in chunks:
            work(members)
    return EnsembleRun(
        day_index=store,
        swe=outputs["swe"],
        depth=outputs["depth"],
        f_sca=outputs["f_sca"],
        s_peak=outputs["s_peak"],
        m_cum=outputs["m_cum"],
        parameters=parameters,
        seed=season_seed(parameters.water_year),
    )
