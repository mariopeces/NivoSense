import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from qa.validation import pangaea

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_tab_reads_metadata_and_table():
    dataset = pangaea.parse_tab((FIXTURES / "poqueira_excerpt.tab").read_text(encoding="utf-8"))
    assert "10.1594/PANGAEA.871706" in dataset.citation
    assert "CC-BY-3.0" in dataset.licence
    assert (dataset.lat, dataset.lon) == (37.02825, -3.32337)
    assert list(dataset.table["Date/Time"])[:2] == ["2009-11-27", "2009-11-28"]


def test_poqueira_tidy_units_and_qc():
    tidy = pangaea.tidy_poqueira(pangaea.parse_tab((FIXTURES / "poqueira_excerpt.tab").read_text(encoding="utf-8")))
    assert list(tidy.columns) == pangaea.TIDY_COLUMNS
    depth = tidy[tidy["variable"] == "snow_depth"].set_index("date")
    assert (depth["unit"] == "m").all() and (depth["elevation_m"] == 2510.0).all()
    assert depth.loc["2009-11-29", "value"] == 0.0339
    scf = tidy[tidy["variable"] == "snow_cover_fraction"].set_index("date")
    assert scf.loc["2009-11-29", "qc"] == "missing" and np.isnan(scf.loc["2009-11-29", "value"])
    assert scf.loc["2009-11-30", "value"] == 0.86 and scf.loc["2009-11-30", "qc"] == "ok"


def test_qc_flags_impossible_values():
    values = pd.Series([0.2, -0.1, 7.0, np.nan])
    assert list(pangaea._flag("snow_depth", values)) == ["ok", "out_of_range", "out_of_range", "missing"]


def test_guadalfeo_tidy_and_zip_loader(tmp_path):
    text = (FIXTURES / "guadalfeo_pg1_excerpt.tab").read_text(encoding="utf-8")
    archive = tmp_path / "g.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("datasets/Guadalfeo_PG1_meteo.tab", text)
    tidy = pangaea.load_guadalfeo(("PG1",), path=archive)
    precipitation = tidy[tidy["variable"] == "precipitation"].set_index("date")
    assert precipitation["unit"].iloc[0] == "mm/day"
    assert precipitation.loc["2009-11-22", "qc"] == "missing"
    assert precipitation.loc["2009-11-26", "value"] == 4.7
    temperature = tidy[tidy["variable"] == "air_temperature"].set_index("date")
    assert temperature.loc["2009-11-23", "value"] == 7.28 and temperature["unit"].iloc[0] == "degC"
    assert set(tidy["station"]) == {"PG1"} and tidy["lat"].iloc[0] == 37.049
    assert tidy["elevation_m"].isna().all()
    assert set(tidy["variable"]) == {"relative_humidity", "air_temperature", "wind_speed", "precipitation", "pressure"}


def test_annual_precipitation_drops_incomplete_years():
    days = pd.date_range("2016-10-01", "2018-03-31")
    full = pd.DataFrame({"date": days, "station": "PG1", "variable": "precipitation", "value": 1.0, "qc": "ok"})
    totals = pangaea.annual_precipitation(full)
    assert list(totals["water_year"]) == [2017]
    assert totals["total_mm"].iloc[0] == 365.0


def test_coverage_counts_only_ok_values():
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2010-01-01", "2010-01-02", "2010-01-03"]),
            "station": "A",
            "variable": "air_temperature",
            "value": [1.0, np.nan, 2.0],
            "qc": ["ok", "missing", "ok"],
        }
    )
    row = pangaea.coverage(frame).iloc[0]
    assert row["n"] == 2 and row["last"] == pd.Timestamp("2010-01-03")


def test_decode_falls_back_to_latin1():
    assert pangaea.decode("Pérez".encode("latin-1")) == "Pérez"
    assert pangaea.decode("Pérez".encode("utf-8")) == "Pérez"


def test_parse_tab_rejects_other_text():
    try:
        pangaea.parse_tab("a\tb\n1\t2\n")
    except ValueError:
        return
    raise AssertionError("expected ValueError")
