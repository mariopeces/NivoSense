"""Daily precipitation from open station networks in and around the massif.

RIA, Red de Informacion Agroclimatica de Andalucia (IFAPA, Junta de Andalucia): open REST
service, no key; data licensed CC BY-NC 4.0 (Junta de Andalucia open data portal, dataset
"estaciones-de-la-red-de-informacion-agroclimatica-de-andalucia"). Used here only to score
forcings, never republished. The stations are agricultural and sit far below the snow zone.

AEMET OpenData: free, but every request needs an API key (env AEMET_API_KEY); data are
reusable citing AEMET as the source (AEMET legal notice). Without a key the reader is skipped.
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

RIA_URL = "https://www.juntadeandalucia.es/agriculturaypesca/ifapa/riaws"
# Granada and Almeria hold the RIA stations around Sierra Nevada.
RIA_PROVINCES = (18, 4)
AEMET_URL = "https://opendata.aemet.es/opendata/api"
AEMET_CHUNK_DAYS = 180


@dataclass(frozen=True)
class Station:
    network: str
    id: str
    name: str
    lat: float
    lon: float
    elevation_m: float


def _get_json(url: str, cache: Path | None, headers: dict | None = None, attempts: int = 4) -> Any:
    path = None
    if cache is not None:
        safe = re.sub(r"[^A-Za-z0-9]+", "_", url.split("://", 1)[1])[-180:]
        path = cache / "stations" / f"{safe}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == attempts:
                raise
            time.sleep(15 * attempt)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def dms_to_degrees(text: str) -> float:
    """RIA ('365523000N', '031102000W') and AEMET ('370600N', '032412W') coordinates.

    Both networks write two degree digits for longitude too, which holds for all of Spain.
    """
    digits, hemisphere = text[:-1], text[-1].upper()
    width = 2
    degrees = int(digits[:width])
    minutes = int(digits[width : width + 2])
    seconds = int(digits[width + 2 : width + 4])
    fraction = digits[width + 4 :]
    if fraction:
        seconds += int(fraction) / 10 ** len(fraction)
    value = degrees + minutes / 60 + seconds / 3600
    return -value if hemisphere in "SW" else value


def near(station: Station, bbox: tuple[float, float, float, float], margin_deg: float) -> bool:
    west, south, east, north = bbox
    return (
        west - margin_deg <= station.lon <= east + margin_deg
        and south - margin_deg <= station.lat <= north + margin_deg
    )


def ria_stations(cache: Path) -> list[Station]:
    stations = []
    for province in RIA_PROVINCES:
        for entry in _get_json(f"{RIA_URL}/estaciones/{province}", cache):
            stations.append(
                Station(
                    "RIA",
                    f"{province}-{entry['codigoEstacion']}",
                    entry["nombre"],
                    dms_to_degrees(entry["latitud"]),
                    dms_to_degrees(entry["longitud"]),
                    float(entry["altitud"]),
                )
            )
    return stations


def ria_daily(station: Station, start: date, end: date, cache: Path) -> dict[date, float]:
    """Daily precipitation in mm; days the station did not report are absent."""
    province, code = station.id.split("-")
    totals: dict[date, float] = {}
    year_start = start
    while year_start <= end:
        year_end = min(end, date(year_start.year, 12, 31))
        url = f"{RIA_URL}/datosdiarios/{province}/{code}/{year_start}/{year_end}/false"
        for row in _get_json(url, cache):
            if row.get("precipitacion") is not None:
                totals[date.fromisoformat(row["fecha"])] = float(row["precipitacion"])
        year_start = year_end + timedelta(days=1)
    return totals


def aemet_key() -> str | None:
    return os.environ.get("AEMET_API_KEY") or None


def _aemet(path: str, key: str, cache: Path) -> Any:
    """AEMET answers with a pointer to the data; the key never enters the cache file names."""
    try:
        meta = _get_json(f"{AEMET_URL}/{path}", None, {"api_key": key})
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        meta = json.loads(error.read().decode("utf-8", errors="replace"))
    if not isinstance(meta, dict) or meta.get("estado") != 200:
        message = meta.get("descripcion") if isinstance(meta, dict) else meta
        raise RuntimeError(f"AEMET request failed: {message}")
    return _get_json(meta["datos"], cache)


def aemet_stations(key: str, cache: Path) -> list[Station]:
    rows = _aemet("valores/climatologicos/inventarioestaciones/todasestaciones", key, cache)
    return [
        Station(
            "AEMET",
            row["indicativo"],
            row["nombre"],
            dms_to_degrees(row["latitud"]),
            dms_to_degrees(row["longitud"]),
            float(row["altitud"]),
        )
        for row in rows
    ]


def aemet_value(text: str | None) -> float | None:
    """AEMET precipitation strings: decimal comma, 'Ip' below 0.1 mm, 'Acum' a multi-day total."""
    if text is None or text == "Acum":
        return None
    if text == "Ip":
        return 0.0
    return float(text.replace(",", "."))


def aemet_daily(station: Station, start: date, end: date, key: str, cache: Path) -> dict[date, float]:
    totals: dict[date, float] = {}
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + timedelta(days=AEMET_CHUNK_DAYS - 1))
        path = (
            "valores/climatologicos/diarios/datos/"
            f"fechaini/{chunk_start}T00:00:00UTC/fechafin/{chunk_end}T23:59:59UTC/"
            f"estacion/{urllib.parse.quote(station.id)}"
        )
        try:
            rows = _aemet(path, key, cache)
        except RuntimeError as error:
            if "No hay datos" not in str(error):
                raise
            rows = []
        for row in rows:
            value = aemet_value(row.get("prec"))
            if value is not None:
                totals[date.fromisoformat(row["fecha"])] = value
        chunk_start = chunk_end + timedelta(days=1)
    return totals
