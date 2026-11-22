"""Passes (UTC date, relative orbit) that the T0.4 freshness monitor sees (bbox of data/basins.geojson) vs
passes with at least one granule touching the domain (where the PR writes a decision object)."""
import collections, gzip, json, re, sys
from shapely.geometry import shape
from shapely.ops import unary_union
dom = unary_union([shape(f["geometry"]) for f in json.load(open(sys.argv[1]))["features"]])
items = json.load(gzip.open("raw_items.json.gz", "rt"))
passes = collections.defaultdict(list)
for it in items:
    d = it["properties"]["datetime"][:10]
    if "2025-10-01" <= d <= "2026-11-21":
        orb = "R" + re.search(r"_R(\d{3})_", it["properties"]["s2:product_uri"]).group(1)
        passes[(d, orb)].append(it)
bbox_only = [{"date": d, "orbit": o, "ids": sorted(i["id"] for i in its)} for (d, o), its in sorted(passes.items())
             if not any(shape(i["geometry"]).intersects(dom) for i in its)]
print(len(passes), "bbox passes;", len(bbox_only), "touch the bbox but not the domain")
for b in bbox_only: print(b)
json.dump({"bbox_passes": len(passes), "bbox_only": bbox_only}, open("bbox_vs_domain.json", "w"), indent=1)
