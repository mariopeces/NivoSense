"""Independent footprint scan: (UTC date, relative orbit) passes over the domain where more
than one datatake / platform is present. pystac-client + shapely; no PR code."""
import json, sys
from collections import defaultdict
from pathlib import Path
from pyproj import Transformer
from pystac_client import Client
from shapely.geometry import shape
from shapely.ops import transform as st, unary_union
gj = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
dom_ll = unary_union([shape(f["geometry"]) for f in gj["features"]])
tu = Transformer.from_crs(4326, 32630, always_xy=True).transform
dom = st(tu, dom_ll)
items = list(Client.open("https://earth-search.aws.element84.com/v1").search(
    collections=["sentinel-2-c1-l2a"], bbox=list(dom_ll.bounds), datetime=f"{sys.argv[2]}/{sys.argv[3]}").items())
g = defaultdict(lambda: defaultdict(list))
for it in items:
    if st(tu, shape(it.geometry)).intersects(dom):
        k = (it.datetime.date().isoformat(), it.properties["s2:product_uri"].split("_")[4])
        dt = it.properties["s2:datatake_id"].rsplit("_N", 1)[0]
        g[k][dt].append(it.properties["grid:code"][-5:])
print(f"items {len(items)} passes {len(g)}")
for k in sorted(g):
    if len(g[k]) > 1:
        print(k[0], k[1], "; ".join(f"{dt}:{','.join(sorted(t))}" for dt, t in sorted(g[k].items())))
