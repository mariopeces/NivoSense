"""Storm segmentation of hourly precipitation, the fixed event partition for the storm-level
precipitation multipliers of the v2 snow model.

A storm is a spell of precipitation hours (at least DRY_THRESHOLD_MM per hour) in which every dry gap is
shorter than MIN_DRY_HOURS; two spells separated by MIN_DRY_HOURS or more dry hours are different storms. A
storm owns the hours from its first to its last wet hour, interior dry hours included. Storms whose total is
below MIN_STORM_TOTAL_MM are dropped (their hours get NO_STORM) and the rest are numbered from 0 in time order.
The thresholds are the design values of docs/snow-methodology.md and are arguments, not tuned numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DRY_THRESHOLD_MM = 0.1
MIN_DRY_HOURS = 12
MIN_STORM_TOTAL_MM = 0.5
NO_STORM = -1


@dataclass(frozen=True)
class Storms:
    """storm_id is (points, hours) int32 with NO_STORM outside storms; n_storms is (points,)."""

    storm_id: np.ndarray
    n_storms: np.ndarray
    totals: list[np.ndarray]


def segment_storms(
    precipitation: np.ndarray,
    dry_threshold: float = DRY_THRESHOLD_MM,
    min_dry_hours: int = MIN_DRY_HOURS,
    min_total: float = MIN_STORM_TOTAL_MM,
) -> Storms:
    """Segment (points, hours) hourly precipitation in mm; a 1-D series is treated as one point."""
    series = np.atleast_2d(np.asarray(precipitation, dtype="float64"))
    storm_id = np.full(series.shape, NO_STORM, dtype="int32")
    counts = np.zeros(series.shape[0], dtype="int32")
    totals: list[np.ndarray] = []
    for point, row in enumerate(series):
        wet = np.flatnonzero(row >= dry_threshold)
        kept: list[float] = []
        if wet.size:
            dry_between = np.diff(wet) - 1
            starts = np.concatenate([[0], np.flatnonzero(dry_between >= min_dry_hours) + 1])
            stops = np.concatenate([starts[1:], [wet.size]]) - 1
            for first, last in zip(wet[starts], wet[stops]):
                total = float(row[first : last + 1].sum())
                if total >= min_total:
                    storm_id[point, first : last + 1] = len(kept)
                    kept.append(total)
        counts[point] = len(kept)
        totals.append(np.array(kept))
    return Storms(storm_id, counts, totals)
