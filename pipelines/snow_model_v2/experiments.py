"""Shared setup of the twin experiments and the real-data runs: forcing, domain and observations of a season."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from pipelines.catalog.storage import LocalStorage, Storage, storage_from_env
from pipelines.region import load_region
from pipelines.snow_model.forcing import Forcing, fetch_forcing

from .contract import SeasonForcing
from .observations import Observations, load_observations
from .region_domain import RegionDomain, build_region_domain

DRY_HOURS = 12
WET_MM = 0.1


def regional_storms(precipitation: np.ndarray) -> np.ndarray:
    """Storm ids (D, 24): spells of the domain mean precipitation separated by at least DRY_HOURS dry hours."""
    wet = precipitation.mean(axis=0).reshape(-1) > WET_MM
    ids = np.full(wet.size, -1, dtype="int32")
    storm, last = -1, None
    for hour in np.flatnonzero(wet):
        if last is None or hour - last - 1 >= DRY_HOURS:
            storm += 1
        else:
            ids[last + 1 : hour] = storm
        ids[hour] = storm
        last = hour
    return ids.reshape(-1, 24)


def season_forcing(forcing: Forcing) -> SeasonForcing:
    return SeasonForcing(
        forcing.days,
        forcing.elevation,
        forcing.temperature,
        forcing.precipitation,
        forcing.shortwave,
        regional_storms(forcing.precipitation),
    )


def mirror_catalogue(cache: Path, prefix: str = "catalog/entries/snow_obs/") -> LocalStorage:
    """A local copy of the prod `snow_obs` entries and their COGs (read only use of the bucket)."""
    local = LocalStorage(cache / "catalog")
    remote: Storage = storage_from_env("prod")
    for key in remote.list(prefix):
        if local.exists(key):
            continue
        local.copy_from(remote, key)
        blob = local.read(key)
        assert blob is not None
        import json

        cog = json.loads(blob.data)["cog"]
        if not local.exists(cog):
            local.copy_from(remote, cog)
    return local


@dataclass
class Season:
    water_year: int
    v1: Forcing
    forcing: SeasonForcing
    region: RegionDomain
    observations: Observations


def load_season(
    water_year: int,
    last_day: date | None,
    cache: Path,
    region_file: Path = Path("regions/sierra-nevada.json"),
    use_shadow: bool = False,
) -> Season:
    """Forcing, class domain and Sentinel-2 class fractions of the water year ending in `water_year`."""
    start, end = date(water_year - 1, 10, 1), last_day or date(water_year, 9, 30)
    settings = load_region(region_file)
    v1 = fetch_forcing(settings.bbox, start, end, 0.1, "ecmwf_ifs", cache)
    region = build_region_domain(region_file, v1, cache)
    catalogue = LocalStorage(cache / "catalog") if not os.environ.get("DATA_BUCKET") else mirror_catalogue(cache)
    keys = catalogue.list("catalog/entries/snow_obs/")
    days = [date.fromisoformat(k.rsplit("/", 1)[-1][:-5]) for k in keys]
    observations = load_observations(
        catalogue,
        [d for d in days if start <= d <= end],
        region.domain,
        region.grid,
        region.cell_index,
        region.ski_cells,
        region.elevation_grid,
        use_shadow,
    )
    return Season(water_year, v1, season_forcing(v1), region, observations)
