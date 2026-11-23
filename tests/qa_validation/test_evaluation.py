from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from pipelines.snow_model_v2.forcing import HourlyForcing
from qa.validation import evaluation as ev
from qa.validation import metrics
from scripts import snow_v2_evaluation as run


def test_block_folds_deal_blocks_in_turn():
    start = date(2024, 10, 1)
    days = [start + timedelta(days=d) for d in (0, 11, 12, 23, 24, 36, 40)]
    assert ev.block_folds(days, start).tolist() == [0, 0, 1, 1, 2, 0, 0]


def test_block_folds_never_split_a_block():
    start = date(2024, 10, 1)
    days = [start + timedelta(days=d) for d in range(0, 120)]
    folds = ev.block_folds(days, start, block_days=12, folds=3)
    for first in range(0, 120, 12):
        assert len(set(folds[first : first + 12])) == 1


def test_snow_line_finds_the_step():
    z = np.arange(1000.0, 3000.0, 5.0)
    snow = z >= 2210.0
    assert ev.snow_line(z, snow) == pytest.approx(2207.5)


def test_snow_line_tolerates_noise_and_needs_both_classes():
    rng = np.random.default_rng(3)
    z = rng.uniform(1000, 3000, 5000)
    snow = (z >= 2000) ^ (rng.random(5000) < 0.03)
    assert abs(ev.snow_line(z, snow) - 2000) < 60
    assert np.isnan(ev.snow_line(z, np.ones(5000, dtype=bool)))
    assert np.isnan(ev.snow_line(z[:50], snow[:50]))


def test_snow_line_all_snow_above_lowest_cell_is_the_lowest_elevation():
    z = np.linspace(1000, 2000, 400)
    snow = np.ones(400, dtype=bool)
    snow[0] = False
    assert ev.snow_line(z, snow) == pytest.approx((z[0] + z[1]) / 2)


def test_area_bias_sign():
    truth = np.array([1, 1, 1, 1, 0, 0], dtype=bool)
    assert ev.area_bias(np.array([1, 1, 1, 1, 1, 1], dtype=bool), truth) == pytest.approx(0.5)
    assert ev.area_bias(np.array([1, 1, 0, 0, 0, 0], dtype=bool), truth) == pytest.approx(-0.5)
    assert np.isnan(ev.area_bias(truth, np.zeros(6, dtype=bool)))


def test_band_table_scores_each_band_and_drops_small_ones():
    z = np.concatenate([np.full(40, 1950.0), np.full(40, 2050.0), np.full(5, 2150.0)])
    truth = np.concatenate([np.zeros(40), np.ones(40), np.ones(5)]).astype(bool)
    pred = truth.copy()
    pred[:10] = True  # false alarms in the lowest band
    table = ev.band_table({"m": pred}, truth, z)
    assert table["band_m"].tolist() == [1900.0, 2000.0]
    assert table.loc[table.band_m == 2000.0, "m_f1"].item() == pytest.approx(1.0)
    assert (
        table.loc[table.band_m == 1900.0, "m_bias"].item() != table.loc[table.band_m == 1900.0, "m_bias"].item()
    )  # NaN: no snow


def test_weighted_crps_matches_brute_force():
    rng = np.random.default_rng(1)
    members = rng.gamma(2.0, 0.3, size=(40, 6))
    weights = rng.random(40)
    weights /= weights.sum()
    observed = rng.gamma(2.0, 0.3, size=6)
    brute = np.mean(
        [
            (weights * np.abs(members[:, t] - observed[t])).sum()
            - 0.5 * (weights[:, None] * weights[None] * np.abs(members[:, t, None] - members[None, :, t])).sum()
            for t in range(6)
        ]
    )
    assert ev.weighted_crps(members, weights, observed) == pytest.approx(brute)
    equal = np.full(40, 1 / 40)
    assert ev.weighted_crps(members, equal, observed) == pytest.approx(metrics.crps_members(members, observed))


def test_weighted_crps_skips_missing_observations():
    members = np.array([[0.0, 1.0], [2.0, 1.0]])
    assert ev.weighted_crps(members, np.array([0.5, 0.5]), np.array([np.nan, 1.0])) == pytest.approx(0.0)


def test_depth_scores_perfect_ensemble_and_snow_day_coverage():
    t = 100
    truth = np.concatenate([np.zeros(60), np.linspace(0, 1, 40)])
    members = np.stack([truth * f for f in np.linspace(0.95, 1.05, 21)])
    out = ev.depth_scores(members, np.full(21, 1 / 21), truth)
    assert out["n"] == t and out["rmse"] < 0.01
    assert out["coverage80"] == pytest.approx(1.0)
    assert out["snow_days"] < t  # the bare days are left out of the snow-day coverage
    assert out["coverage80_snow_days"] == pytest.approx(1.0)


def test_climatology_leaves_the_season_out():
    days = pd.Series(pd.to_datetime(["2010-12-01", "2011-12-01", "2012-12-01", "2012-12-05", "2012-03-01"]))
    depth = pd.Series([0.2, 0.4, 0.9, 0.9, 5.0])
    seasons = days.dt.year + (days.dt.month >= 10)
    out = ev.climatology(days, depth, seasons)
    # 2010-12-01 (season 2011): the other seasons near that day are 2011-12-01 (2012) and 2012-12-01 (2013)
    assert out[0] == pytest.approx((0.4 + 0.9 + 0.9) / 3)
    # the March value of 2012 has no other season near its day of year
    assert np.isnan(out[4])


def test_annual_ratio_uses_common_days_and_min_days():
    days = pd.date_range("2017-10-01", "2018-09-30")
    model = pd.DataFrame({"date": days, "value": 1.0})
    station = pd.DataFrame({"date": days, "value": 2.0})
    station.loc[:9, "value"] = np.nan
    out = ev.annual_ratio(model, station, min_days=300)
    assert out["water_year"].tolist() == [2018]
    assert out["ratio"].item() == pytest.approx(0.5)
    assert out["days"].item() == 355
    assert ev.annual_ratio(model, station, min_days=400).empty


def test_default_member_is_the_middle_of_the_priors():
    member = run.default_member(2011, storms=3)
    assert member.count == 1 and member.xi.shape == (1, 3)
    assert member.b0[0] == 1.0 and member.dT[0] == 0.0 and member.xi.sum() == 0.0
    assert member.L[0] == pytest.approx(6.25) and member.Ts[0] == pytest.approx(1.25)


def test_modis_observations_keep_clear_days_in_the_window():
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2010-01-01", "2010-01-01", "2010-01-02", "2010-01-03", "2011-01-01"]),
            "platform": ["terra", "aqua", "terra", "terra", "terra"],
            "ndsi": [50.0, 70.0, np.nan, 20.0, 10.0],
            "fsca": [0.5, 0.7, np.nan, 0.2, 0.1],
            "qc": ["ok", "ok", "cloud", "ok", "ok"],
            "lat": 37.0,
            "lon": -3.3,
        }
    )
    days = [date(2010, 1, 1) + timedelta(days=d) for d in range(10)]
    obs = run.modis_observations(frame, days)
    assert obs.days == [date(2010, 1, 1), date(2010, 1, 3)]
    assert obs.fraction[0].tolist() == pytest.approx([0.6, 0.2])
    assert obs.sigma[0, 0] == pytest.approx(np.sqrt(0.1**2 + (0.5 / 5) ** 2))
    assert obs.usable.all()


def test_melt_out_errors_signs():
    dates = pd.Series(pd.date_range("2012-03-01", periods=40))
    observed = np.where(np.arange(40) < 20, 0.5, 0.0)  # last snow day index 19, melt-out on index 20
    early = np.where(np.arange(40) < 15, 0.5, 0.0)
    late = np.where(np.arange(40) < 25, 0.5, 0.0)
    out = run.melt_out_errors(dates, np.stack([early, late]), observed)
    assert out["camera"] == "2012-03-21"
    assert out["members_with_melt_out"] == 2
    assert out["p10"] < 0 < out["p90"]


def _hourly(temperature: float, precipitation: float, days: int = 4) -> HourlyForcing:
    hours = days * 24
    shape = (1, hours)
    return HourlyForcing(
        model="era5",
        water_year=2010,
        start=date(2010, 1, 1),
        lon=np.array([-3.3]),
        lat=np.array([37.0]),
        elevation=np.array([2500.0], dtype="float32"),
        cell_lon=np.array([-3.25]),
        cell_lat=np.array([37.0]),
        cell_elevation=np.array([2500.0], dtype="float32"),
        temperature=np.full(shape, temperature, dtype="float32"),
        precipitation=np.full(shape, precipitation, dtype="float32"),
        shortwave=np.zeros(shape, dtype="float32"),
        from_forecast=np.zeros(hours, dtype=bool),
    )


def test_station_correction_shifts_temperature_and_scales_precipitation():
    hourly = _hourly(temperature=-2.0, precipitation=0.1)  # 2.4 mm per day
    days = pd.date_range("2010-01-01", periods=4)
    station = pd.concat(
        [
            pd.DataFrame({"date": days, "variable": "precipitation", "value": 4.8}),
            pd.DataFrame({"date": days[:3], "variable": "air_temperature", "value": -0.5}),
        ]
    )
    corrected, info = run.station_correction(hourly, station)
    assert info["precipitation_scale"] == pytest.approx(2.0)
    assert info["temperature_shift_c"] == pytest.approx(1.5)
    assert info["temperature_days"] == 3
    assert corrected.temperature.mean() == pytest.approx(-0.5)
    assert corrected.precipitation.sum() == pytest.approx(hourly.precipitation.sum() * 2.0)
    assert hourly.temperature.mean() == pytest.approx(-2.0)  # the input is not changed


def test_modis_vs_camera_reports_bias_and_melt_out():
    days = pd.date_range("2012-03-01", periods=60)
    camera = pd.DataFrame(
        {
            "date": days,
            "variable": "snow_cover_fraction",
            "qc": "ok",
            "value": np.where(np.arange(60) < 20, 0.8, 0.0),
        }
    )
    modis = pd.DataFrame(
        {
            "date": days,
            "platform": "terra",
            "ndsi": 0.0,
            "fsca": np.where(np.arange(60) < 40, 0.8, 0.0),
            "qc": "ok",
            "lat": 37.0,
            "lon": -3.3,
        }
    )
    out = run.modis_vs_camera(camera, modis)
    season = out["seasons"][2012]
    assert season["camera_melt_out"] == "2012-03-21"
    assert season["modis_melt_out"] == "2012-04-10"
    assert season["bias_modis_minus_camera"] == pytest.approx(0.8 * 20 / 60)
    assert out["days"] == 60
