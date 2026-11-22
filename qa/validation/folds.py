"""Leave-one-season-out folds by water year (docs/snow-methodology.md 5.2)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class Fold:
    held_out: int
    train: tuple[int, ...]

    @property
    def start(self) -> date:
        return water_year_bounds(self.held_out)[0]

    @property
    def end(self) -> date:
        return water_year_bounds(self.held_out)[1]


def water_year(day: date) -> int:
    """The water year runs 1 October to 30 September and is named by the year it ends in."""
    return day.year + (1 if day.month >= 10 else 0)


def water_year_bounds(wy: int) -> tuple[date, date]:
    return date(wy - 1, 10, 1), date(wy, 9, 30)


def seasons_of(dates: Iterable[date | pd.Timestamp]) -> list[int]:
    return sorted({water_year(pd.Timestamp(d).date()) for d in dates})


def leave_one_season_out(seasons: Iterable[int]) -> Iterator[Fold]:
    """One fold per season: that season is held out and every other one is for tuning."""
    ordered = sorted(set(seasons))
    for wy in ordered:
        yield Fold(wy, tuple(s for s in ordered if s != wy))


def in_season(frame: pd.DataFrame, wy: int, column: str = "date") -> pd.DataFrame:
    start, end = water_year_bounds(wy)
    days = pd.to_datetime(frame[column])
    return frame[(days >= pd.Timestamp(start)) & (days <= pd.Timestamp(end))]
