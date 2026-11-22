"""Merge the labels into the drawn points and freeze the reference sample.

    python -m qa.reference.freeze --points work/reference/points.geojson --labels labels.csv

Writes qa/reference/snow_points.geojson and its SHA-256 next to it. The tests check the file
against that hash, so any later edit of the sample fails CI.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import strata
from .chips import read_labels

REFERENCE = Path(__file__).parent
SAMPLE_PATH = REFERENCE / "snow_points.geojson"

PROTOCOL = {
    "unit": "one 20 m pixel of the EPSG:32630 grid snapped to the Sentinel-2 20 m pixel edges",
    "imagery": (
        "Sentinel-2 L1C top-of-atmosphere reflectance (Earth Search sentinel-2-l1c, scale and offset "
        "from raster:bands), 10 m; B11 shown with each 20 m pixel repeated 2x2"
    ),
    "panels": (
        "true colour B04/B03/B02 and SWIR false colour B11/B8/B4 over 340 m around the point (x3), "
        "true colour over 1 km around it (x1); the pixel sits inside red corner marks"
    ),
    "stretch": "reflectance 0 to 1, square root, the same for every date",
    "classes": {
        "snow": "the marked pixel is covered by snow on most of its area (white in true colour, cyan in SWIR)",
        "no_snow": "the marked pixel is clear-sky ground, vegetation, rock or water without snow on most of it",
        "cloud": "a cloud, thick haze or cloud veil over the pixel hides the ground (white or grey in both panels)",
        "unsure": "a mixed pixel at a snow edge, deep shadow too dark to read, thin haze, or any doubt",
    },
    "rules": [
        "labels are the labeller's visual judgement on the chips; no index, threshold or classifier output is "
        "computed or looked at",
        "snow in SWIR false colour is cyan or blue (low B11), cloud is white or pink (high B11)",
        "cloud shadow on clear ground is not cloud: label what the ground shows, or unsure if too dark",
        "points were labelled in a shuffled order per date, without their stratum shown",
        "unsure points stay in the file with scored = false and are left out of every score",
    ],
    "labeller": "LLM labelling agent (Claude), blind to every snow classifier in the repository",
}

SOURCES = {
    "sentinel-2-l1c": "Copernicus Sentinel-2 L1C via Earth Search (Element 84), AWS Open Data",
    "sentinel-2-c1-l2a": (
        "Copernicus Sentinel-2 L2A collection 1 via Earth Search; scene classes 8, 9, 10 used only to place "
        "the cloud-edge stratum, sun angles from item metadata"
    ),
    "glo-30": "Copernicus DEM GLO-30 (ESA, Airbus), AWS Open Data, bilinear to 20 m",
    "worldcover": "ESA WorldCover 10 m 2021 v200 (Zanaga et al. 2022), CC BY 4.0, class 10 tree cover",
}


def design() -> dict:
    return {
        "strata": {
            "snowline_band": f"elevation within {strata.SNOWLINE_HALF_WIDTH_M:.0f} m of the date's snowline_m",
            "terrain_shadow": (
                f"cast shadow (rays traced {strata.SHADOW_MAX_DISTANCE_M:.0f} m towards the sun) or local "
                f"incidence cosine under {strata.SHADOW_COS_INCIDENCE:.3f} (80 degrees)"
            ),
            "forest": f"WorldCover tree cover on at least {strata.FOREST_FRACTION:.0%} of the pixel",
            "cloud_edge": f"within {strata.CLOUD_EDGE_PIXELS * 20} m of the SCL cloud / clear-sky boundary",
            "open_terrain": "SCL clear sky, no tree cell, not in any other stratum",
        },
        "elevation_bands_m": list(strata.ELEVATION_BREAKS_M),
        "min_spacing_m": strata.MIN_SPACING_M,
        "draw": (
            "simple random sample per date, stratum and elevation band; quotas split evenly over the dates "
            "where the stratum has pixels, then over its elevation bands; strata other than cloud_edge drawn "
            "only on SCL clear-sky pixels. Points also carry every stratum they fall in (in_strata) and the "
            "pixel count of their draw cell (cell_pixels) for design-weighted estimates."
        ),
        "supplement": (
            "points with draw = 2 come from a second draw (seed and quotas in metadata.supplement) on the dates "
            "with a snowline, from the same strata and elevation bands restricted to ground at or above the "
            "date's snowline_m, keeping the minimum spacing to the first draw; their cell_pixels count the "
            "restricted cell. They oversample snow-prone ground: weight each draw by its own cells."
        ),
    }


def freeze(points_path: Path, labels_path: Path, out: Path = SAMPLE_PATH) -> str:
    collection = json.loads(points_path.read_text(encoding="utf-8"))
    labels = read_labels(labels_path)
    ids = [feature["properties"]["id"] for feature in collection["features"]]
    missing = [point_id for point_id in ids if point_id not in labels]
    extra = sorted(set(labels) - set(ids))
    if missing or extra:
        raise ValueError(f"labels do not match the points: {len(missing)} missing, {len(extra)} unknown")
    for feature in collection["features"]:
        label = labels[feature["properties"]["id"]]
        feature["properties"]["label"] = label
        feature["properties"]["scored"] = label != "unsure"
    collection["metadata"] = {
        "name": "NivoSense frozen snow reference sample",
        "crs_of_x_y": "EPSG:32630",
        "protocol": PROTOCOL,
        "design": design(),
        "sources": SOURCES,
        **collection["metadata"],
    }
    text = json.dumps(collection, indent=1, ensure_ascii=False) + "\n"
    out.write_text(text, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    out.with_name(out.name + ".sha256").write_text(f"{digest}  {out.name}\n", encoding="utf-8", newline="\n")
    return digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    args = parser.parse_args(argv)
    print(freeze(args.points, args.labels))
    return 0


if __name__ == "__main__":
    sys.exit(main())
