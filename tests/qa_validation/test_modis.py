from datetime import date

import numpy as np
import pandas as pd
import pytest

from qa.validation import modis


def test_fsca_conversion_clips_and_scales():
    assert list(modis.ndsi_to_fsca(np.array([0, 100]))) == [0.0, 1.0]
    assert modis.ndsi_to_fsca(np.array([50.0]))[0] == pytest.approx(-0.01 + 1.45 * 0.5)


@pytest.mark.parametrize(
    ("code", "expected"),
    [(0, "ok"), (100, "ok"), (250, "cloud"), (200, "no_data"), (201, "no_data"), (211, "no_data"), (255, "no_data")],
)
def test_classify_codes(code, expected):
    assert modis.classify(code) == expected


def item(platform, day, name):
    return {
        "assets": {"NDSI_Snow_Cover": {"href": f"https://example.invalid/{name}.tif"}},
        "properties": {"platform": platform, "start_datetime": f"{day}T10:30:00Z"},
    }


def test_load_fsca_and_combine(monkeypatch):
    codes = {"a": 40, "b": 250, "c": 250, "d": 201}
    monkeypatch.setattr(
        modis,
        "search_items",
        lambda *args: [
            item("terra", "2012-03-01", "a"),
            item("aqua", "2012-03-01", "b"),
            item("terra", "2012-03-02", "c"),
            item("aqua", "2012-03-02", "d"),
        ],
    )
    monkeypatch.setattr(modis.SasToken, "get", lambda self: "tok")
    monkeypatch.setattr(modis, "_read_pixel", lambda href, token, lat, lon: codes[href.rsplit("/", 1)[1][:-4]])
    table = modis.load_fsca(37.0, -3.3, date(2012, 3, 1), date(2012, 3, 2))
    assert list(table.columns) == modis.COLUMNS
    assert list(table["qc"]) == ["cloud", "ok", "no_data", "cloud"]
    daily = modis.combine_daily(table)
    first, second = daily.iloc[0], daily.iloc[1]
    assert first["qc"] == "ok" and first["fsca"] == pytest.approx(-0.01 + 1.45 * 0.4) and first["n_clear"] == 1
    assert second["qc"] == "cloud" and np.isnan(second["fsca"])
    assert table["date"].iloc[0] == pd.Timestamp("2012-03-01")


def test_combine_daily_averages_two_clear_passes():
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2012-03-01"] * 2),
            "platform": ["terra", "aqua"],
            "ndsi": [40.0, 60.0],
            "fsca": [0.4, 0.6],
            "qc": ["ok", "ok"],
        }
    )
    assert modis.combine_daily(frame)["fsca"].iloc[0] == pytest.approx(0.5)


def test_search_items_cuts_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(modis, "_post", lambda url, body: calls.append(body["datetime"]) or {"features": []})
    modis.search_items(37.0, -3.3, date(2012, 1, 1), date(2012, 7, 1))
    assert len(calls) == 3 and calls[0].startswith("2012-01-01") and calls[-1].endswith("2012-07-01T23:59:59Z")
