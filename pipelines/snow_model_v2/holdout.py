"""Block hold-out of Sentinel-2 dates inside one season (docs/snow-methodology.md section 5.2, level 2)."""

from __future__ import annotations

from datetime import date

import numpy as np

from .observations import Observations

BLOCK_DAYS = 12
HELD_EVERY = 3


def block_mask(
    days: list[date], season_start: date, block_days: int = BLOCK_DAYS, every: int = HELD_EVERY
) -> np.ndarray:
    """True for the dates in every `every`-th block of `block_days` days counted from the season start.

    Blocks of at least ten days stop the neighbouring dates of a held-out block from leaking its information
    through the temporal correlation of the snow cover.
    """
    block = np.array([(day - season_start).days // block_days for day in days])
    return block % every == 1


def split(observations: Observations, season_start: date) -> tuple[Observations, Observations]:
    held = block_mask(observations.days, season_start)
    return observations.select(~held), observations.select(held)
