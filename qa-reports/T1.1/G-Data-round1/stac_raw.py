"""G-Data own query: raw Earth Search search (GET via pystac-client, bbox of the domain, no cloud filter),
plus the same query on the sentinel-2-l2a (non-c1) collection to see if any datatake is missing from c1."""
import json, sys
from pystac_client import Client
from shapely.geometry import shape
from shapely.ops import unary_union

dom = unary_union([shape(f["geometry"]) for f in json.load(open(sys.argv[1]))["features"]])
cat = Client.open("https://earth-search.aws.element84.com/v1")
out = {}
for coll in ["sentinel-2-c1-l2a", "sentinel-2-l2a"]:
    s = cat.search(collections=[coll], bbox=list(dom.bounds), datetime="2026-09-20/2026-11-22T23:59:59Z", max_items=2000)
    items = [i.to_dict() for i in s.items()]
    out[coll] = items
    print(coll, len(items))
json.dump(out, open("raw_items.json", "w"))
