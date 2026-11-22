"""Which datatake each pixel of the builder's mosaic came from (SCL), for a same-day two-satellite date."""
import sys, numpy as np, rasterio
from rasterio.windows import from_bounds
from pystac_client import Client
out, day, tile = sys.argv[1], sys.argv[2], sys.argv[3]
with rasterio.open(out) as m:
    scl = m.read(1); b = m.bounds; shp = scl.shape
items = list(Client.open("https://earth-search.aws.element84.com/v1").search(collections=["sentinel-2-c1-l2a"], datetime=day, query={"grid:code": {"eq": "MGRS-" + tile}}).items())
arrs = {}
for it in items:
    with rasterio.open(it.assets["scl"].href) as s:
        arrs[it.id] = s.read(1, window=from_bounds(*b, s.transform), boundless=True, fill_value=0, out_shape=shp)
ids = list(arrs)
a, c = arrs[ids[0]], arrs[ids[1]]
has = scl > 0
both = (a > 0) & (c > 0)
print("mosaic px with data", int(has.sum()))
for i in ids:
    print(i, "px with data", int((arrs[i] > 0).sum()), "mosaic==this", int((has & (scl == arrs[i])).sum()))
print("both have data", int(both.sum()), "and disagree", int((both & (a != c)).sum()))
only_a = (a > 0) & (c == 0) & has; only_c = (c > 0) & (a == 0) & has
print("from", ids[0], "only", int(only_a.sum()), "| from", ids[1], "only", int(only_c.sum()))
