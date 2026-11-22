"""Footprint-only scan: per datatake touching the domain, which tiles and how many granules."""
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
g = defaultdict(list)
for it in items:
    if st(tu, shape(it.geometry)).intersects(dom):
        g[(it.datetime.date().isoformat(), it.properties["s2:product_uri"].split("_")[4])].append(it)
for k in sorted(g):
    its = g[k]
    tiles = sorted(i.properties["grid:code"][-5:] for i in its)
    bls = sorted({i.properties["s2:processing_baseline"] for i in its})
    flag = ""
    if k[1] == "R094" and len(set(tiles)) < 4: flag += " MISSING"
    if len(tiles) != len(set(tiles)): flag += " DUP"
    print(k[0], k[1], ",".join(tiles), bls, flag)
