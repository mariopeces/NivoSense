import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform as warp

from pipelines.catalog.storage import LocalStorage
from qa.validation import baselines, report

LAT, LON = 37.02825, -3.32337


def write_layer(storage, layer, day, centre_value):
    """A 5 x 5 raster of 100 m cells whose centre cell holds the point; other cells are nodata."""
    x, y = warp("EPSG:4326", "EPSG:32630", [LON], [LAT])
    data = np.full((5, 5), -9999.0, dtype="float32")
    data[2, 2] = centre_value
    path = storage.root / f"{layer}-{day}.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=5,
        height=5,
        count=1,
        dtype="float32",
        crs="EPSG:32630",
        transform=from_origin(x[0] - 250, y[0] + 250, 100, 100),
        nodata=-9999.0,
    ) as target:
        target.write(data, 1)
    cog_key = f"layers/{layer}/{day}.tif"
    storage.write(cog_key, path.read_bytes(), "image/tiff", "no-cache")
    entry = {"layer": layer, "date": day, "cog": cog_key, "qa": {"flags": []}}
    storage.write(f"catalog/entries/{layer}/{day}.json", json.dumps(entry).encode(), "application/json", "no-cache")


@pytest.fixture
def catalogue(tmp_path):
    storage = LocalStorage(tmp_path / "cat")
    write_layer(storage, "snow_depth", "2025-01-01", 0.4)
    write_layer(storage, "snow_depth", "2025-01-03", -9999.0)
    index = {"layers": {"snow_depth": {"dates": ["2025-01-01", "2025-01-03"]}}}
    storage.write("catalog/index.json", json.dumps(index).encode(), "application/json", "no-cache")
    return storage


def test_sample_catalogue_reads_cell_and_skips_dates_without_entry(catalogue):
    points = pd.DataFrame({"lat": [LAT], "lon": [LON]})
    days = [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)]
    table, stats = baselines.sample_catalogue(catalogue, "snow_depth", points, days)
    assert list(table["value"]) == pytest.approx([0.4, 0.0])  # nodata inside the grid is "no snow"
    assert stats["no_entry_days"] == 1
    assert table["unit"].iloc[0] == "m"


def test_sample_catalogue_point_outside_raster_is_nan(catalogue):
    table, stats = baselines.sample_catalogue(
        catalogue, "snow_depth", pd.DataFrame({"lat": [38.0], "lon": [-3.0]}), [date(2025, 1, 1)]
    )
    assert np.isnan(table["value"].iloc[0]) and stats["outside_raster_points"] == 1


def season_csv(path, offset=0.0, with_quantiles=False):
    days = pd.date_range("2012-10-01", "2013-06-30")
    depth = np.clip(np.sin(np.linspace(0, np.pi, len(days))) * 1.0 - 0.1, 0, None)
    frame = pd.DataFrame({"date": days, "value": np.round(depth, 4), "lat": LAT, "lon": LON})
    if with_quantiles:
        frame = frame.assign(
            value=frame["value"] + offset, q10=frame["value"] - 0.2, q50=frame["value"], q90=frame["value"] + 0.2
        )
    else:
        frame["value"] = frame["value"] + offset
    frame.to_csv(path, index=False)


def test_report_main_on_csvs(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    season_csv(tmp_path / "ref.csv")
    season_csv(tmp_path / "prod.csv", offset=0.05, with_quantiles=True)
    code = report.main(["--product", "prod.csv", "--reference-csv", "ref.csv", "--fold", "2013"])
    assert code == 0
    text = (tmp_path / "qa-reports" / "prod-snow_depth-2013.md").read_text(encoding="utf-8")
    assert "What this reference can and cannot validate" in text
    assert "Melt-out date per season" in text and "Ensemble quality" in text
    headline = capsys.readouterr().out
    assert "bias: 0.0500" in headline and "rmse: 0.0500" in headline


def test_report_with_no_overlap_scores_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    season_csv(tmp_path / "ref.csv")
    other = pd.DataFrame({"date": ["2030-01-01"], "value": [1.0], "lat": LAT, "lon": LON})
    other.to_csv(tmp_path / "prod.csv", index=False)
    report.main(["--product", "prod.csv", "--reference-csv", "ref.csv", "--fold", "2013"])
    text = (tmp_path / "qa-reports" / "prod-snow_depth-2013.md").read_text(encoding="utf-8")
    assert "share no dates" in text and "Time series scores" not in text


def test_md_table_formats_numbers_and_nan():
    text = report.md_table(pd.DataFrame({"a": [1.23456, np.nan], "b": ["x", "y"]}))
    assert "| 1.235 | x |" in text and "| n/a | y |" in text
