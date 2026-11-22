from pathlib import Path

import numpy as np

from pipelines.snow_model_v2.storms import NO_STORM, segment_storms

FIXTURE = Path(__file__).parent / "fixtures" / "ifs_water_year_2024_precipitation.npz"


def series(*spells: tuple[int, float, int]) -> np.ndarray:
    """(start hour, mm per hour, duration) spells on 200 dry hours."""
    values = np.zeros(200)
    for start, rate, hours in spells:
        values[start : start + hours] = rate
    return values


def test_two_spells_split_at_twelve_dry_hours():
    # wet 10-14, 12 dry hours (15..26), wet 27-30
    result = segment_storms(series((10, 1.0, 5), (27, 1.0, 4)))
    assert result.n_storms.tolist() == [2]
    assert result.storm_id[0, 10:15].tolist() == [0] * 5
    assert result.storm_id[0, 27:31].tolist() == [1] * 4


def test_eleven_dry_hours_stay_one_storm_and_own_the_gap():
    # wet 10-14, 11 dry hours (15..25), wet 26-29
    result = segment_storms(series((10, 1.0, 5), (26, 1.0, 4)))
    assert result.n_storms.tolist() == [1]
    assert (result.storm_id[0, 10:30] == 0).all()
    assert (result.storm_id[0, :10] == NO_STORM).all() and (result.storm_id[0, 30:] == NO_STORM).all()


def test_drizzle_below_threshold_is_dry():
    result = segment_storms(series((10, 0.09, 50)))
    assert result.n_storms.tolist() == [0]
    assert (result.storm_id == NO_STORM).all()


def test_drizzle_does_not_bridge_two_storms():
    values = series((10, 1.0, 3), (40, 1.0, 3))
    values[13:40] = 0.09
    assert segment_storms(values).n_storms.tolist() == [2]


def test_small_storms_are_dropped_and_ids_stay_dense():
    # totals 0.4 (dropped), 0.5 (kept, the threshold is inclusive), 2.0 (kept)
    result = segment_storms(series((10, 0.4, 1), (40, 0.5, 1), (80, 1.0, 2)))
    assert result.n_storms.tolist() == [2]
    assert result.storm_id[0, 10] == NO_STORM
    assert result.storm_id[0, 40] == 0
    assert result.storm_id[0, 80] == 1
    assert [round(t, 2) for t in result.totals[0]] == [0.5, 2.0]


def test_storm_total_includes_sub_threshold_hours_inside():
    values = series((10, 1.0, 2), (14, 1.0, 2))
    values[12:14] = 0.05
    assert round(segment_storms(values).totals[0][0], 2) == 4.1


def test_points_are_independent_and_a_dry_point_has_none():
    wet = series((10, 1.0, 5), (60, 1.0, 5), (120, 1.0, 5))
    result = segment_storms(np.stack([wet, np.zeros(200)]))
    assert result.n_storms.tolist() == [3, 0]
    assert result.storm_id.shape == (2, 200)


def test_a_storm_running_to_the_last_hour_is_closed():
    result = segment_storms(series((195, 1.0, 5)))
    assert result.n_storms.tolist() == [1]
    assert result.storm_id[0, -1] == 0


def test_real_season_counts_are_plausible():
    # IFS HRES via Open-Meteo, water year 2024-25, three points of the Sierra Nevada lattice (low, middle, high).
    with np.load(FIXTURE) as stored:
        precipitation = stored["precipitation"]
        elevation = stored["elevation"]
    assert precipitation.shape == (3, 8760)
    result = segment_storms(precipitation)
    # A mid-latitude Mediterranean mountain range sees a few dozen to about a hundred frontal events a year.
    assert ((result.n_storms >= 30) & (result.n_storms <= 150)).all(), (elevation, result.n_storms)
    assert all((totals >= 0.5).all() for totals in result.totals)
