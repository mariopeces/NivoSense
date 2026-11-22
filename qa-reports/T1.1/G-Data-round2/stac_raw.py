"""G-Data own query (round 2): pystac-client GET, bbox of the domain, no cloud filter, c1 collection,
2025-09-01..2026-11-22. Kept raw so every later step reads the same snapshot."""
import gzip, json, sys
from pystac_client import Client
from shapely.geometry import shape
from shapely.ops import unary_union
dom = unary_union([shape(f["geometry"]) for f in json.load(open(sys.argv[1]))["features"]])
cat = Client.open("https://earth-search.aws.element84.com/v1")
s = cat.search(collections=["sentinel-2-c1-l2a"], bbox=list(dom.bounds),
               datetime="2025-09-01T00:00:00Z/2026-11-22T23:59:59Z", max_items=5000)
items = [i.to_dict() for i in s.items()]
print(len(items))
json.dump(items, gzip.open("raw_items.json.gz", "wt"))
