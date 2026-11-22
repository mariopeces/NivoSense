"""Writes data/ski_resort.geojson, the Sierra Nevada ski resort outline from OpenStreetMap.

    python -m scripts.build_ski_resort

The outline is the OSM way tagged landuse=winter_sports for the Estación de Esquí y Montaña de
Sierra Nevada (way 654498540). Artificial snow is beyond the reach of the snow model and of the
regression checks, so they exclude this area (README section 6, Q4).
OpenStreetMap data (c) OpenStreetMap contributors, ODbL 1.0.
"""

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
WAY_ID = 654498540
OUT = Path(__file__).resolve().parent.parent / "data" / "ski_resort.geojson"


def to_feature(element: dict) -> dict:
    ring = [[round(node["lon"], 7), round(node["lat"], 7)] for node in element["geometry"]]
    if ring[0] != ring[-1]:
        raise ValueError(f"OSM way {element['id']} is not closed")
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {"name": element["tags"].get("name"), "osm_id": f"way/{element['id']}"},
    }


def main() -> int:
    query = f"[out:json][timeout:60];way({WAY_ID});out tags geom;"
    request = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": "nivosense-pipeline"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        elements = json.load(response)["elements"]
    if len(elements) != 1 or elements[0]["tags"].get("landuse") != "winter_sports":
        raise ValueError(f"Expected one landuse=winter_sports way {WAY_ID}, got {elements}")
    feature = to_feature(elements[0])
    collection = {
        "type": "FeatureCollection",
        "metadata": {
            "source": f"OpenStreetMap way {WAY_ID} via the Overpass API ({OVERPASS_URL})",
            "licence": "ODbL 1.0, (c) OpenStreetMap contributors",
            "retrieved": datetime.now(timezone.utc).date().isoformat(),
            "built_by": "python -m scripts.build_ski_resort",
        },
        "features": [feature],
    }
    OUT.write_text(json.dumps(collection, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(feature['geometry']['coordinates'][0])} vertices)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
