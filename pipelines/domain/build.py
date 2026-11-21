"""Build the model domain and its river sub-basins from the official boundary layers.

Domain: Sierra Nevada National Park (MITECO, Banco de Datos de la Naturaleza) united with the
Sierra Nevada Natural Park (REDIAM, Junta de Andalucia). Decreto 238/2011 (BOJA 155, 9/8/2011)
defines the protection system of the massif as a core zone (the National Park) and a peripheral
buffer zone that is the Natural Park, so the Natural Park is the peripheral protection perimeter
and no separate polygon exists for it (REDIAM marks ZON_PRO = NO for both parks).

Sub-basins: MITECO "Subcuencas de rios completos clasificadas segun Pfafstetter modificado". That
layer is nested (every river carries its whole drainage area, tributaries included), so the
domain is partitioned with the outermost rivers: those whose Pfafstetter code has no prefix
among the other rivers that touch the domain. These are the rivers that leave the massif to the
sea or to the Guadalquivir, and their codes are the ones the site and the river gauges use.

Areas are planar areas in ETRS89 / UTM zone 30N (EPSG:25830), the CRS of the three sources and
of their published surfaces, so the comparison with the official figures is like for like.
GeoJSON is written in EPSG:4326 (RFC 7946); ETRS89 and WGS84 differ by well under a metre here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import geopandas as gpd
import shapely
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

AREA_CRS = "EPSG:25830"
OUTPUT_CRS = "EPSG:4326"
COORDINATE_DECIMALS = 6
# 1 km around the domain: enough to keep every sub-basin that touches it in the clipped source.
SOURCE_CLIP_BUFFER_M = 1000.0
MAX_AREA_ERROR = 0.005
SUBBASIN_FIELDS = ("COD_MAR", "cod_uni", "pfafrio", "nom_rio_1", "Cuen_Tipo")

REDIAM_WFS = "https://www.juntadeandalucia.es/medioambiente/mapwms/REDIAM_RENPA"
REDIAM_PARKS_URL = f"{REDIAM_WFS}?service=WFS&version=2.0.0&request=GetFeature&typeNames=ms:eennpp"
REDIAM_LICENCE = (
    "REDIAM WFS access constraints: free use provided the authors and owners of the "
    "information are cited (Junta de Andalucia, Consejeria de Sostenibilidad y Medio "
    "Ambiente, REDIAM)."
)
MITECO_ENP_URL = (
    "https://www.miteco.gob.es/content/dam/miteco/es/biodiversidad/servicios/"
    "banco-datos-naturaleza/enp/Enp2025_shp.zip"
)
MITECO_ENP_PAGE = (
    "https://www.miteco.gob.es/es/biodiversidad/servicios/banco-datos-naturaleza/"
    "informacion-disponible/enp_descargas.html"
)
MITECO_LICENCE = (
    "Free use provided the Ministerio para la Transicion Ecologica y el Reto Demografico "
    "is cited as author and owner: 'Fuente: Ministerio para la Transicion Ecologica y el "
    "Reto Demografico'."
)
MITECO_SUBBASINS_PAGE = (
    "https://www.miteco.gob.es/es/cartografia-y-sig/ide/descargas/agua/cuencas-y-subcuencas.html"
)
MITECO_SUBBASIN_FILES = {
    "A_cuencas_rios_Atl_Sur.zip": (
        "bdc091bf3c8c3d5eb86e9bef9310667323c7edb8f367a21ca972894dab9d8b00"
    ),
    "M_cuencas_rios_Med_Sur.zip": (
        "ec4e490d4cb498adebb959a4d00eb001dd9e086ca342b0205210224baa57e113"
    ),
}
MITECO_SUBBASINS_DOWNLOADED = "2026-11-22"

REPO = Path(__file__).resolve().parents[2]
SOURCE_CLIP = REPO / "data" / "sources" / "miteco_subcuencas_rios_completos_sierra_nevada.geojson"
OUTPUT_DIRS = (REPO / "data", REPO / "frontend" / "public" / "data")
REGION_FILE = REPO / "regions" / "sierra-nevada.json"


@dataclass(frozen=True)
class Parks:
    national: BaseGeometry
    natural: BaseGeometry
    national_rediam: BaseGeometry
    national_official_ha: float
    natural_official_ha: float
    national_attrs: dict
    natural_attrs: dict


def fetch(url: str, destination: Path) -> Path:
    if destination.exists():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "NivoSense domain build"})
    with urllib.request.urlopen(request, timeout=600) as response:
        payload = response.read()
    destination.write_bytes(payload)
    return destination


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def only_row(frame: gpd.GeoDataFrame, description: str) -> gpd.GeoSeries:
    if len(frame) != 1:
        raise ValueError(f"Expected exactly one {description}, found {len(frame)}")
    return frame.iloc[0]


def load_parks(rediam_gml: Path, miteco_zip: Path) -> Parks:
    rediam = gpd.read_file(rediam_gml).to_crs(AREA_CRS)
    sierra = rediam[rediam["NOMBRE"].str.upper() == "SIERRA NEVADA"]
    natural = only_row(sierra[sierra["FIGURA"] == "Parque Natural"], "REDIAM Parque Natural")
    national_rediam = only_row(
        sierra[sierra["FIGURA"] == "Parque Nacional"], "REDIAM Parque Nacional"
    )

    enp = gpd.read_file(f"zip://{miteco_zip}!Enp2025_shp/Enp2025_p.shp").to_crs(AREA_CRS)
    national = only_row(
        enp[(enp["SITE_NAME"] == "Sierra Nevada") & (enp["ODESIGNATE"] == "Parque Nacional")],
        "MITECO Parque Nacional",
    )
    return Parks(
        national=shapely.make_valid(national.geometry),
        natural=shapely.make_valid(natural.geometry),
        national_rediam=shapely.make_valid(national_rediam.geometry),
        # REDIAM SUPERFICIE holds the surfaces stated in Decreto 238/2011, not the polygon
        # areas, so they are an independent check of the geometry.
        national_official_ha=float(national_rediam["SUPERFICIE"]),
        natural_official_ha=float(natural["SUPERFICIE"]),
        national_attrs={
            key: national[key] for key in ("SITE_NAME", "ODESIGNATE", "SITE_CODE_", "SITE_CDDA")
        },
        natural_attrs={
            key: natural[key]
            for key in ("CODIGOESPA", "FIGURA", "NOMBRE", "NOR_DECLA", "NOR_LIM_LI")
        },
    )


def build_domain(national: BaseGeometry, natural: BaseGeometry) -> BaseGeometry:
    return shapely.make_valid(shapely.union(national, natural))


def load_subbasins(sources: list[Path]) -> gpd.GeoDataFrame:
    frames = []
    for source in sources:
        if source.suffix == ".zip":
            frame = gpd.read_file(f"zip://{source}!{source.stem}.shp")
        else:
            frame = gpd.read_file(source)
        frames.append(frame.to_crs(AREA_CRS))
    merged = gpd.GeoDataFrame(
        gpd.pd.concat(frames, ignore_index=True), crs=AREA_CRS, geometry="geometry"
    )
    return merged


def outermost_rivers(candidates: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Keep the rivers whose Pfafstetter code has no proper prefix among the candidates."""
    codes = set(candidates["pfafrio"])
    keep = [
        not any(code[:length] in codes for length in range(1, len(code)))
        for code in candidates["pfafrio"]
    ]
    return candidates[keep]


def outermost_touching(subbasins: gpd.GeoDataFrame, domain: BaseGeometry) -> gpd.GeoDataFrame:
    touching = subbasins[subbasins.intersects(domain)].copy()
    touching["pfafrio"] = touching["pfafrio"].astype(str)
    return outermost_rivers(touching)


def intersect_subbasins(subbasins: gpd.GeoDataFrame, domain: BaseGeometry) -> gpd.GeoDataFrame:
    rows = []
    for _, row in outermost_touching(subbasins, domain).iterrows():
        clipped = shapely.make_valid(shapely.intersection(row.geometry, domain))
        clipped = shapely.union_all(
            [
                part
                for part in shapely.get_parts(clipped)
                if part.geom_type in ("Polygon", "MultiPolygon")
            ]
        )
        if clipped.is_empty:
            continue
        properties = {field: row[field] for field in SUBBASIN_FIELDS if field in row.index}
        properties["cod_uni"] = int(properties["cod_uni"])
        # The source's own published area: the full sub-basin, most of it outside the domain,
        # is not in the clipped source copy, so its geometry cannot be measured there.
        properties["source_area_km2"] = round(float(row["Shape_Area"]) / 1e6, 3)
        properties["domain_area_km2"] = round(clipped.area / 1e6, 3)
        rows.append({**properties, "geometry": clipped})
    result = gpd.GeoDataFrame(rows, crs=AREA_CRS, geometry="geometry")
    return result.sort_values("cod_uni").reset_index(drop=True)


def clip_source(subbasins: gpd.GeoDataFrame, domain: BaseGeometry) -> gpd.GeoDataFrame:
    window = box(*domain.buffer(SOURCE_CLIP_BUFFER_M).bounds)
    chosen = outermost_touching(subbasins, domain)
    chosen["geometry"] = chosen.geometry.intersection(window)
    columns = [*SUBBASIN_FIELDS, "Shape_Area", "geometry"]
    return chosen[[column for column in columns if column in chosen.columns]].sort_values("cod_uni")


def rounded(geometry: BaseGeometry) -> BaseGeometry:
    return shapely.make_valid(shapely.set_precision(geometry, 10**-COORDINATE_DECIMALS))


def feature_collection(frame: gpd.GeoDataFrame, name: str, metadata: dict) -> dict:
    projected = frame.to_crs(OUTPUT_CRS)
    projected["geometry"] = projected.geometry.apply(rounded)
    collection = json.loads(projected.to_json(drop_id=True, na="null"))
    return {
        "type": "FeatureCollection",
        "name": name,
        "metadata": metadata,
        "features": collection["features"],
    }


def write_json(payload: dict, paths: list[Path]) -> None:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def outward_bbox(geometry: BaseGeometry) -> list[float]:
    west, south, east, north = (
        gpd.GeoSeries([geometry], crs=AREA_CRS).to_crs(OUTPUT_CRS).total_bounds
    )
    step = 10**4
    return [
        math.floor(west * step) / step,
        math.floor(south * step) / step,
        math.ceil(east * step) / step,
        math.ceil(north * step) / step,
    ]


def update_region(path: Path, bbox: list[float]) -> None:
    region = json.loads(path.read_text(encoding="utf-8"))
    region["domain"] = "data/domain.geojson"
    region["bbox"] = bbox
    ordered = {key: region[key] for key in ("id", "name", "basins", "domain", "bbox")}
    ordered.update({key: value for key, value in region.items() if key not in ordered})
    path.write_text(
        json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )


def area_error(measured_km2: float, official_km2: float) -> float:
    return abs(measured_km2 - official_km2) / official_km2


def check(parks: Parks, domain: BaseGeometry, basins: gpd.GeoDataFrame) -> dict:
    report = {
        "national_park_km2": round(parks.national.area / 1e6, 3),
        "national_park_official_km2": round(parks.national_official_ha / 100, 3),
        "national_park_vs_rediam_symmetric_difference_km2": round(
            parks.national.symmetric_difference(parks.national_rediam).area / 1e6, 4
        ),
        "natural_park_km2": round(parks.natural.area / 1e6, 3),
        "natural_park_official_km2": round(parks.natural_official_ha / 100, 3),
        "parks_overlap_km2": round(parks.national.intersection(parks.natural).area / 1e6, 4),
        "domain_km2": round(domain.area / 1e6, 3),
        "subbasins_domain_area_sum_km2": round(float(basins["domain_area_km2"].sum()), 3),
    }
    errors = {
        "national park": area_error(
            report["national_park_km2"], report["national_park_official_km2"]
        ),
        "natural park": area_error(report["natural_park_km2"], report["natural_park_official_km2"]),
        "sub-basin cover": area_error(
            report["subbasins_domain_area_sum_km2"], report["domain_km2"]
        ),
    }
    for name, error in errors.items():
        if error > MAX_AREA_ERROR:
            raise ValueError(f"{name} area off by {error:.2%}, more than {MAX_AREA_ERROR:.1%}")
    return report


def sources_metadata(parks: Parks, retrieved: str, miteco_enp_sha: str) -> list[dict]:
    return [
        {
            "layer": "Parque Natural Sierra Nevada (peripheral protection zone)",
            "publisher": "Junta de Andalucia, REDIAM, Espacios Naturales Protegidos de Andalucia (RENPA)",
            "url": REDIAM_PARKS_URL,
            "feature": parks.natural_attrs,
            "retrieved": retrieved,
            "licence": REDIAM_LICENCE,
        },
        {
            "layer": "Parque Nacional Sierra Nevada",
            "publisher": "MITECO, Banco de Datos de la Naturaleza, Espacios Naturales Protegidos 2025",
            "url": MITECO_ENP_URL,
            "page": MITECO_ENP_PAGE,
            "sha256": miteco_enp_sha,
            "feature": parks.national_attrs,
            "retrieved": retrieved,
            "licence": MITECO_LICENCE,
        },
        {
            "layer": "Subcuencas de rios completos clasificadas segun Pfafstetter modificado",
            "publisher": "MITECO, IDE, cuencas y subcuencas hidrograficas (1:25.000, 14/03/2018)",
            "page": MITECO_SUBBASINS_PAGE,
            "files": MITECO_SUBBASIN_FILES,
            "retrieved": MITECO_SUBBASINS_DOWNLOADED,
            "retrieval_note": (
                "Downloaded through the MITECO download page in a browser (the page has a "
                "visitor check); the build reads the clipped copy in data/sources/."
            ),
            "licence": MITECO_LICENCE,
        },
    ]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=REPO / ".cache" / "domain")
    parser.add_argument(
        "--subbasin-zips",
        type=Path,
        nargs="*",
        help="The MITECO zips; when given, the clipped source copy is rewritten from them.",
    )
    parser.add_argument("--retrieved", default=date.today().isoformat())
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    rediam_gml = fetch(REDIAM_PARKS_URL, args.cache / "rediam_eennpp.gml")
    miteco_zip = fetch(MITECO_ENP_URL, args.cache / "Enp2025_shp.zip")
    parks = load_parks(rediam_gml, miteco_zip)
    domain = build_domain(parks.national, parks.natural)

    if args.subbasin_zips:
        for path in args.subbasin_zips:
            expected = MITECO_SUBBASIN_FILES.get(path.name)
            if expected is None or sha256(path) != expected:
                raise ValueError(f"{path} is not one of the recorded MITECO files")
        full = load_subbasins(args.subbasin_zips)
        write_json(
            feature_collection(
                clip_source(full, domain),
                "miteco_subcuencas_rios_completos_sierra_nevada",
                {
                    "note": (
                        "The outermost rivers of MITECO 'Subcuencas de rios completos clasificadas "
                        "segun Pfafstetter modificado' that touch the domain, clipped to its "
                        "bounding box plus 1 km. Attributes unchanged. Fuente: Ministerio para la "
                        "Transicion Ecologica y el Reto Demografico."
                    ),
                    "page": MITECO_SUBBASINS_PAGE,
                    "files": MITECO_SUBBASIN_FILES,
                    "licence": MITECO_LICENCE,
                },
            ),
            [SOURCE_CLIP],
        )

    basins = intersect_subbasins(load_subbasins([SOURCE_CLIP]), domain)
    report = check(parks, domain, basins)
    metadata = {
        "sources": sources_metadata(parks, args.retrieved, sha256(miteco_zip)),
        "area_crs": AREA_CRS,
        "areas": report,
    }
    domain_frame = gpd.GeoDataFrame(
        [
            {
                "id": "sierra-nevada",
                "name": "Espacio Natural Sierra Nevada",
                "part": "domain",
                "area_km2": report["domain_km2"],
                "geometry": domain,
            },
            {
                "id": "parque-nacional",
                "name": "Parque Nacional de Sierra Nevada",
                "part": "national_park",
                "area_km2": report["national_park_km2"],
                "geometry": parks.national,
            },
            {
                "id": "parque-natural",
                "name": "Parque Natural de Sierra Nevada",
                "part": "natural_park",
                "area_km2": report["natural_park_km2"],
                "geometry": parks.natural,
            },
        ],
        crs=AREA_CRS,
        geometry="geometry",
    )
    write_json(
        feature_collection(domain_frame, "domain", metadata),
        [directory / "domain.geojson" for directory in OUTPUT_DIRS],
    )
    write_json(
        feature_collection(basins, "basins", metadata),
        [directory / "basins.geojson" for directory in OUTPUT_DIRS],
    )
    update_region(REGION_FILE, outward_bbox(domain))
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
