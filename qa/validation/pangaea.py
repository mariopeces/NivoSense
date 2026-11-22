"""Loaders for the open reference data used to validate snow products, both from PANGAEA.

Poqueira camera, https://doi.org/10.1594/PANGAEA.871706 (Pimentel, Herrero and Polo 2017), CC-BY-3.0.
    Daily snow cover fraction and snow depth of a 30 x 30 m plot at 37.02825 N, -3.32337 E, 2,510 m, by
    terrestrial photography, 2009-11-15 to 2013-05-31 (1,218 dated rows, 2 depth and 64 cover values empty,
    and a 62-day gap in the dates).
    CAN validate: snow depth physics and snow presence at one point, in four seasons that are long past.
    CANNOT validate: SWE (no density is given), current seasons, spatial patterns, or a 100 m cell without a
    representativeness error: the camera sees 900 m2.

Guadalfeo Monitoring Network, https://doi.org/10.1594/PANGAEA.895236 (Polo, Herrero, Pimentel and
Perez-Palazon 2018, supplement to ESSD 11:393, 2019), CC-BY-4.0.
    Daily air temperature, precipitation, humidity, wind, pressure (radiation at PG2 to PG5) at PG1, PG2, PG4 and
    PG5 (PG3 is on the Contraviesa crest, outside the Sierra Nevada domain, and is not loaded), up to 2018-08-31.
    CAN validate: forcing temperature and precipitation of the seasons up to 2017-18.
    CANNOT validate: snow. No snow variable is in the files, snowfall is probably undercaught by the gauges
    (gauge type not checked) and nothing after August 2018 exists. The files carry no elevation either, so none
    is reported here.

The files carry no QC flags. The `qc` column here is ours: `missing` for an empty value, `out_of_range` for a
value outside the physical limits in `LIMITS`, `ok` otherwise. Downloads are cached in a gitignored folder.
"""

from __future__ import annotations

import io
import re
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

CACHE_DIR = Path("qa-cache/pangaea")
POQUEIRA_DOI = "10.1594/PANGAEA.871706"
GUADALFEO_DOI = "10.1594/PANGAEA.895236"
POQUEIRA_LICENCE = "CC-BY-3.0"
GUADALFEO_LICENCE = "CC-BY-4.0"
POQUEIRA_SITE = {"station": "poqueira_camera", "lat": 37.02825, "lon": -3.32337, "elevation_m": 2510.0}
GUADALFEO_STATIONS = ("PG1", "PG2", "PG4", "PG5")
TIDY_COLUMNS = ["date", "station", "variable", "value", "unit", "qc", "lat", "lon", "elevation_m"]

# Physical limits for the QC flag, wide enough that only impossible values trip it. Relative humidity gets
# half a percent: the PG3 file reaches 100.08, which is sensor noise and not a gap.
LIMITS = {
    "snow_depth": (0.0, 5.0),
    "snow_cover_fraction": (0.0, 1.0),
    "air_temperature": (-40.0, 50.0),
    "precipitation": (0.0, 500.0),
    "relative_humidity": (0.0, 100.5),
    "wind_speed": (0.0, 80.0),
    "pressure": (500.0, 1100.0),
    "longwave_down": (0.0, 60.0),
    "shortwave_down": (0.0, 40.0),
}

# Column header prefix of the Guadalfeo daily files -> (variable, unit). Matching on the prefix keeps the
# loader independent of how the degree sign in the other headers is encoded.
_GUADALFEO_COLUMNS = {
    "RH": ("relative_humidity", "%"),
    "TTT day m": ("air_temperature", "degC"),
    "ff day m": ("wind_speed", "m/s"),
    "Precip": ("precipitation", "mm/day"),
    "PPPP day m": ("pressure", "hPa"),
    "LWD daily sum": ("longwave_down", "MJ/m2/day"),
    "SWD daily sum": ("shortwave_down", "MJ/m2/day"),
}


@dataclass(frozen=True)
class Dataset:
    """A parsed PANGAEA tab file: its metadata and the raw table with the source's column names."""

    citation: str
    licence: str
    lat: float
    lon: float
    table: pd.DataFrame


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def parse_tab(text: str) -> Dataset:
    """Parse a PANGAEA `.tab` text: a `/* ... */` header, then a tab separated table."""
    lines = text.splitlines()
    end = next((n for n, line in enumerate(lines) if line.startswith("*/")), None)
    if end is None:
        raise ValueError("Not a PANGAEA tab file: no '*/' header end")
    header = lines[:end]
    citation = next((ln.split("\t", 1)[1] for ln in header if ln.startswith("Citation:")), "")
    licence = next((ln.split("\t", 1)[1] for ln in header if ln.startswith("License:")), "")
    match = re.search(r"LATITUDE: (-?[\d.]+) \* LONGITUDE: (-?[\d.]+)", "\n".join(header))
    lat, lon = (float(match.group(1)), float(match.group(2))) if match else (float("nan"), float("nan"))
    table = pd.read_csv(io.StringIO("\n".join(lines[end + 1 :])), sep="\t")
    return Dataset(citation, licence, lat, lon, table)


def _download(url: str, target: Path) -> Path:
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "nivosense-validation"})
        with urllib.request.urlopen(request, timeout=120) as response:
            target.write_bytes(response.read())
    return target


def _flag(variable: str, values: pd.Series) -> pd.Series:
    low, high = LIMITS[variable]
    qc = pd.Series("ok", index=values.index, dtype="object")
    qc[(values < low) | (values > high)] = "out_of_range"
    qc[values.isna()] = "missing"
    return qc


def _tidy(dates: pd.Series, values: pd.Series, variable: str, unit: str, site: dict[str, object]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(dates).dt.normalize(),
            "station": site["station"],
            "variable": variable,
            "value": values.astype("float64"),
            "unit": unit,
            "qc": _flag(variable, values),
            "lat": site["lat"],
            "lon": site["lon"],
            "elevation_m": site["elevation_m"],
        }
    )
    return frame[TIDY_COLUMNS]


def tidy_poqueira(dataset: Dataset) -> pd.DataFrame:
    table = dataset.table
    scf = next(c for c in table.columns if c.startswith("SCF"))
    depth = next(c for c in table.columns if c.startswith("Snow thick"))
    parts = [
        _tidy(table["Date/Time"], table[depth], "snow_depth", "m", POQUEIRA_SITE),
        _tidy(table["Date/Time"], table[scf], "snow_cover_fraction", "1", POQUEIRA_SITE),
    ]
    return pd.concat(parts, ignore_index=True).sort_values(["variable", "date"], ignore_index=True)


def load_poqueira(path: Path | None = None, cache_dir: Path = CACHE_DIR) -> pd.DataFrame:
    """Daily snow depth (m) and snow cover fraction at the Refugio Poqueira camera, as a tidy long table."""
    if path is None:
        path = _download(f"https://doi.pangaea.de/{POQUEIRA_DOI}?format=textfile", cache_dir / "871706.tab")
    return tidy_poqueira(parse_tab(decode(path.read_bytes())))


def tidy_guadalfeo(dataset: Dataset, station: str) -> pd.DataFrame:
    site = {"station": station, "lat": dataset.lat, "lon": dataset.lon, "elevation_m": float("nan")}
    parts = []
    for column in dataset.table.columns:
        for prefix, (variable, unit) in _GUADALFEO_COLUMNS.items():
            if column == prefix or column.startswith((f"{prefix} ", f"{prefix}[")):
                parts.append(_tidy(dataset.table["Date/Time"], dataset.table[column], variable, unit, site))
                break
    return pd.concat(parts, ignore_index=True)


def load_guadalfeo(
    stations: tuple[str, ...] = GUADALFEO_STATIONS, path: Path | None = None, cache_dir: Path = CACHE_DIR
) -> pd.DataFrame:
    """Daily meteorology of the Guadalfeo stations as a tidy long table. `path` is the collection zip."""
    if path is None:
        path = _download(f"https://doi.pangaea.de/{GUADALFEO_DOI}?format=zip", cache_dir / "895236.zip")
    frames = []
    with zipfile.ZipFile(path) as archive:
        for station in stations:
            text = decode(archive.read(f"datasets/Guadalfeo_{station}_meteo.tab"))
            frames.append(tidy_guadalfeo(parse_tab(text), station))
    return pd.concat(frames, ignore_index=True).sort_values(["station", "variable", "date"], ignore_index=True)


def coverage(frame: pd.DataFrame) -> pd.DataFrame:
    """First date, last date and count of usable (qc ok) values per station and variable."""
    ok = frame[frame["qc"] == "ok"]
    return (
        ok.groupby(["station", "variable"])
        .agg(first=("date", "min"), last=("date", "max"), n=("value", "size"))
        .reset_index()
    )


def annual_precipitation(frame: pd.DataFrame, min_valid_share: float = 0.9) -> pd.DataFrame:
    """Water-year precipitation totals (mm) per station, only for years with enough valid days.

    A total over a year with gaps is a lower bound, so such years are dropped instead of reported low.
    """
    rain = frame[(frame["variable"] == "precipitation") & (frame["qc"] == "ok")].copy()
    rain["water_year"] = rain["date"].dt.year + (rain["date"].dt.month >= 10)
    out = rain.groupby(["station", "water_year"]).agg(total_mm=("value", "sum"), valid_days=("value", "size"))
    days = [(date(wy, 9, 30) - date(wy - 1, 10, 1)).days + 1 for wy in out.index.get_level_values("water_year")]
    out["share_valid"] = out["valid_days"] / pd.Series(days, index=out.index)
    return out[out["share_valid"] >= min_valid_share].reset_index()
