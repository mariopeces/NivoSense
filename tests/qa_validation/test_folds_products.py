from datetime import date

import pandas as pd
import pytest

from qa.validation import baselines, folds, products


def test_water_year_boundaries():
    assert folds.water_year(date(2012, 9, 30)) == 2012
    assert folds.water_year(date(2012, 10, 1)) == 2013
    assert folds.water_year_bounds(2013) == (date(2012, 10, 1), date(2013, 9, 30))


def test_leave_one_season_out():
    result = list(folds.leave_one_season_out([2012, 2010, 2011, 2011]))
    assert [f.held_out for f in result] == [2010, 2011, 2012]
    assert result[1].train == (2010, 2012)
    assert result[0].start == date(2009, 10, 1) and result[0].end == date(2010, 9, 30)


def test_in_season_and_seasons_of():
    frame = pd.DataFrame({"date": pd.to_datetime(["2012-09-30", "2012-10-01", "2013-09-30", "2013-10-01"])})
    assert len(folds.in_season(frame, 2013)) == 2
    assert folds.seasons_of(frame["date"]) == [2012, 2013, 2014]


def test_quantile_columns_and_member_reduction():
    frame = pd.DataFrame(
        {"date": ["2020-01-01"] * 3, "lat": 37.0, "lon": -3.3, "member": [0, 1, 2], "value": [1.0, 5.0, 3.0]}
    )
    wide = products.reduce_members(frame)
    assert wide["value"].iloc[0] == 3.0 and products.member_columns(wide) == ["m0", "m1", "m2"]
    assert products.quantile_columns(pd.DataFrame(columns=["q90", "q10", "x", "q5"])) == {
        0.05: "q5",
        0.1: "q10",
        0.9: "q90",
    }


def test_read_table_requires_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("date,value\n2020-01-01,1\n")
    with pytest.raises(ValueError, match="lat"):
        products.read_table(path)


def test_read_table_uses_q50_as_value(tmp_path):
    path = tmp_path / "q.csv"
    path.write_text("date,lat,lon,q10,q50,q90\n2020-01-01,37,-3.3,0,1,2\n")
    assert products.read_table(path)["value"].iloc[0] == 1.0


def test_match_pairs_nearest_location_within_distance():
    reference = pd.DataFrame(
        {"date": pd.to_datetime(["2020-01-01", "2020-01-02"]), "value": [0.5, 0.6], "lat": 37.02825, "lon": -3.32337}
    )
    product = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-02"]),
            "value": [0.4, 0.9, 7.0],
            "lat": [37.0289, 37.0289, 37.20],  # 70 m away, 70 m away, 19 km away
            "lon": -3.32337,
        }
    )
    pairs = products.match(product, reference)
    assert list(pairs["sim"]) == [0.4, 0.9] and list(pairs["ref"]) == [0.5, 0.6]


def test_prior_median_over_members():
    ensemble = pd.DataFrame(
        {"date": ["2020-01-01"] * 3, "lat": 37.0, "lon": -3.3, "member": [0, 1, 2], "value": [1.0, 9.0, 2.0]}
    )
    assert baselines.prior_median(ensemble)["value"].iloc[0] == 2.0
