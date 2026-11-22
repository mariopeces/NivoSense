import urllib.parse
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from pipelines.snow_model_v2.forcing import (
    cache_path,
    daily_means,
    daily_totals,
    fetch_season_forcing,
    to_classes,
    to_season_forcing,
    water_year_bounds,
)

POINTS = [(37.0, -3.3), (37.1, -3.2), (37.2, -3.1)]
ELEVATIONS = [1500.0, 2200.0, 2800.0]
TODAY = date(2026, 11, 22)


class FakeOpenMeteo:
    """Answers archive and forecast URLs with a deterministic series: precipitation 1 mm in hour 5 of each day."""

    def __init__(self, today: date = TODAY) -> None:
        self.urls: list[str] = []
        self.today = today

    def __call__(self, url: str) -> list[dict]:
        self.urls.append(url)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        lats, lons = query["latitude"].split(","), query["longitude"].split(",")
        elevations = [float(e) for e in query["elevation"].split(",")]
        if "past_days" in query:
            last = self.today + timedelta(days=int(query["forecast_days"]) - 1)
            first = self.today - timedelta(days=int(query["past_days"]))
        else:
            first, last = date.fromisoformat(query["start_date"]), date.fromisoformat(query["end_date"])
        stamps = []
        moment = datetime.combine(first, datetime.min.time())
        while moment.date() <= last:
            stamps.append(moment)
            moment += timedelta(hours=1)
        marker = 100.0 if "past_days" in query else 0.0
        return [
            {
                "latitude": float(lat),
                "longitude": float(lon),
                "elevation": elevation,
                "hourly": {
                    "time": [s.strftime("%Y-%m-%dT%H:%M") for s in stamps],
                    "temperature_2m": [marker + 5.0 - elevation / 1000 for _ in stamps],
                    "precipitation": [1.0 if s.hour == 5 else 0.0 for s in stamps],
                    "shortwave_radiation": [200.0 if 8 <= s.hour <= 16 else 0.0 for s in stamps],
                },
            }
            for lat, lon, elevation in zip(lats, lons, elevations)
        ]


def fetch(tmp_path, fake, **kwargs):
    return fetch_season_forcing(
        kwargs.pop("water_year", 2024), POINTS, ELEVATIONS, tmp_path, get_json=fake, pause=0, today=TODAY, **kwargs
    )


def test_a_finished_season_is_fetched_once_and_cached(tmp_path):
    fake = FakeOpenMeteo()
    first = fetch(tmp_path, fake)
    requests = len(fake.urls)
    assert first.precipitation.shape == (3, 365 * 24)
    assert not first.from_forecast.any()
    again = fetch(tmp_path, fake)
    assert len(fake.urls) == requests
    np.testing.assert_array_equal(first.precipitation, again.precipitation)
    assert cache_path(tmp_path, "ecmwf_ifs", 2024, POINTS, ELEVATIONS).exists()


def test_requests_carry_the_requested_elevations_and_batch_the_points(tmp_path):
    fake = FakeOpenMeteo()
    fetch(tmp_path, fake)
    assert len(fake.urls) == 1
    query = urllib.parse.parse_qs(urllib.parse.urlparse(fake.urls[0]).query)
    assert query["elevation"] == ["1500,2200,2800"]
    assert query["models"] == ["ecmwf_ifs"]
    assert query["start_date"] == ["2024-10-01"] and query["end_date"] == ["2025-09-30"]


def test_a_different_elevation_is_a_different_cache_entry(tmp_path):
    assert cache_path(tmp_path, "era5", 2024, POINTS, ELEVATIONS) != cache_path(
        tmp_path, "era5", 2024, POINTS, [1500.0, 2200.0, 2900.0]
    )


def test_the_current_season_splices_the_forecast_after_the_archive_lag(tmp_path):
    fake = FakeOpenMeteo()
    forcing = fetch(tmp_path, fake, water_year=2026)
    archive_end = TODAY - timedelta(days=3)
    expected_hours = ((TODAY - date(2026, 10, 1)).days + 1) * 24
    assert forcing.hours == expected_hours
    split = ((archive_end - date(2026, 10, 1)).days + 1) * 24
    assert not forcing.from_forecast[:split].any() and forcing.from_forecast[split:].all()
    assert forcing.temperature[0, split - 1] < 50 < forcing.temperature[0, split]
    assert "past_days=2" in fake.urls[-1] and "models=ecmwf_ifs" in fake.urls[-1]


def test_an_unfinished_season_extends_the_cache_instead_of_refetching(tmp_path):
    earlier = date(2026, 11, 12)
    fetch_season_forcing(2026, POINTS, ELEVATIONS, tmp_path, get_json=FakeOpenMeteo(earlier), pause=0, today=earlier)
    fake = FakeOpenMeteo()
    forcing = fetch(tmp_path, fake, water_year=2026)
    archive_urls = [u for u in fake.urls if "archive-api" in u]
    assert len(archive_urls) == 1
    assert "start_date=2026-11-10" in archive_urls[0] and "end_date=2026-11-19" in archive_urls[0]
    assert forcing.precipitation.shape[1] == ((TODAY - date(2026, 10, 1)).days + 1) * 24
    assert forcing.precipitation.sum(axis=1).tolist() == [(TODAY - date(2026, 10, 1)).days + 1] * 3


def test_model_and_water_year_are_checked(tmp_path):
    with pytest.raises(ValueError, match="era5_land"):
        fetch(tmp_path, FakeOpenMeteo(), model="era5_land")
    with pytest.raises(ValueError, match="no archive"):
        fetch(tmp_path, FakeOpenMeteo(), water_year=2015)


def test_too_many_missing_values_fail_loudly(tmp_path):
    class Broken(FakeOpenMeteo):
        def __call__(self, url: str) -> list[dict]:
            records = super().__call__(url)
            for record in records:
                record["hourly"]["precipitation"][: len(record["hourly"]["time"]) // 2] = [None] * (
                    len(record["hourly"]["time"]) // 2
                )
            return records

    with pytest.raises(RuntimeError, match="missing archive precipitation"):
        fetch(tmp_path, Broken())


def test_water_year_bounds():
    assert water_year_bounds(2024) == (date(2024, 10, 1), date(2025, 9, 30))


def test_daily_aggregates():
    hourly = np.tile(np.arange(24, dtype="float32"), (2, 3))
    assert daily_totals(hourly).tolist() == [[276.0] * 3] * 2
    assert daily_means(hourly).tolist() == [[11.5] * 3] * 2


def test_class_means_are_weighted_and_validated():
    hourly = np.array([[1.0, 1.0], [3.0, 5.0], [100.0, 100.0]], dtype="float32")
    weights = np.array([[1, 1, 0], [0, 1, 0]], dtype="float32")
    assert to_classes(hourly, weights).tolist() == [[2.0, 3.0], [3.0, 5.0]]
    with pytest.raises(ValueError):
        to_classes(hourly, weights[:, :2])


def test_the_engine_forcing_has_the_contract_shapes_and_one_regional_storm_partition(tmp_path):
    hourly = fetch(tmp_path, FakeOpenMeteo())
    forcing = to_season_forcing(hourly)
    assert forcing.temperature.shape == (3, 365, 24) and forcing.shortwave.shape == (3, 365)
    assert forcing.storm_id.shape == (365, 24)
    # 1 mm in hour 5 of every day, 18 dry hours between: each day is its own storm, ids in time order.
    assert forcing.storm_count == 365
    assert forcing.storm_id[0, 5] == 0 and forcing.storm_id[364, 5] == 364
    assert forcing.elevation.tolist() == ELEVATIONS
    assert forcing.days[0] == date(2024, 10, 1) and len(forcing.days) == 365
