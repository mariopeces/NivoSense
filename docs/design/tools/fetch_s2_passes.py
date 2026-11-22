"""List real Sentinel-2 L1C passes over the domain tiles since 2025-10-01 (Earth Search STAC).

Used only to give the timeline mockup real pass dates; production ticks come from catalog/index.json.
Usage: python -I docs/design/tools/fetch_s2_passes.py <end-date> <out.json>
"""

from __future__ import annotations

import json
import sys
import urllib.request

STAC = "https://earth-search.aws.element84.com/v1/search"
TILES = {"30SVF", "30SVG", "30SWF", "30SWG"}


def main(end: str, out: str) -> None:
    body = {
        "collections": ["sentinel-2-l1c"],
        "bbox": [-3.62, 36.88, -2.55, 37.25],
        "datetime": f"2025-10-01T00:00:00Z/{end}T23:59:59Z",
        "limit": 200,
    }
    items, url = [], STAC
    while url:
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            page = json.load(r)
        items += page["features"]
        nxt = [link for link in page.get("links", []) if link.get("rel") == "next"]
        url, body = (nxt[0]["href"], nxt[0].get("body", body)) if nxt else (None, None)
    by_date: dict[str, dict] = {}
    for it in items:
        tile = it["id"].split("_")[1]
        if tile not in TILES:
            continue
        d = it["properties"]["datetime"][:10]
        e = by_date.setdefault(d, {"date": d, "items": [], "tile_cloud_cover": {}})
        e["items"].append(it["id"])
        e["tile_cloud_cover"][tile] = round(it["properties"].get("eo:cloud_cover", -1), 1)
    doc = {
        "source": "Earth Search v1, collection sentinel-2-l1c, tiles 30SVF 30SVG 30SWF 30SWG",
        "queried_range": ["2025-10-01", end],
        "note": "Every listed pass, without the domain cloud filter that the catalogue (D1) will apply.",
        "passes": sorted(by_date.values(), key=lambda e: e["date"]),
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    print(len(doc["passes"]), "dates")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
