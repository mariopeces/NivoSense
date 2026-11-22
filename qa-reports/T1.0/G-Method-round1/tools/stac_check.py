import json, sys, urllib.request
from collections import defaultdict
from shapely.geometry import shape, Point
pts = json.load(open(sys.argv[1], encoding="utf-8"))
meta = {d["date"]: d for d in pts["metadata"]["dates"]}
dom = [shape(f["geometry"]) for f in json.load(open("domain_bad749e.geojson", encoding="utf-8"))["features"] if f["properties"]["part"] == "domain"][0]
URL = "https://earth-search.aws.element84.com/v1/search"
used = defaultdict(set)
for f in pts["features"]:
    used[f["properties"]["date"]].add(f["properties"]["chip_scene_id"])
items_by_id = {}
rows = []
for day in sorted(meta):
    body = {"collections": ["sentinel-2-l1c"], "intersects": json.loads(json.dumps(dom.__geo_interface__)), "datetime": f"{day}T00:00:00Z/{day}T23:59:59Z", "limit": 100}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    feats = json.load(urllib.request.urlopen(req, timeout=120))["features"]
    found = {}
    for it in feats:
        uri = it["properties"].get("s2:product_uri", "")
        orb = uri.split("_")[4] if uri else None
        found[it["id"]] = (orb, it["properties"].get("s2:processing_baseline"), it["properties"].get("eo:cloud_cover"))
        items_by_id[it["id"]] = it
    r094 = sorted(i for i, v in found.items() if v[0] == "R094")
    other = sorted(f"{i}({v[0]})" for i, v in found.items() if v[0] != "R094")
    rec = sorted(meta[day]["l1c_scene_ids"])
    rows.append((day, len(found), r094 == rec, sorted(set(rec) - set(r094)), sorted(set(r094) - set(rec)), sorted(used[day] - set(r094)), other))
print("| date | L1C items over domain | R094 set == recorded | recorded not in STAC | STAC R094 not recorded | chip ids not in STAC R094 | other orbits |")
print("|---|---|---|---|---|---|---|")
for r in rows:
    print("| " + " | ".join(str(x) if not isinstance(x, list) else (", ".join(x) or "-") for x in r) + " |")
# footprint check: every point inside its chip scene footprint
bad = [f["properties"]["id"] for f in pts["features"] if not shape(items_by_id[f["properties"]["chip_scene_id"]]["geometry"]).contains(Point(f["geometry"]["coordinates"]))]
print(f"\npoints outside their chip scene's footprint: {len(bad)} {bad[:10]}")
