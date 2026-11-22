"""Same-datatake tile overlap: compare swir16 DN and SCL between adjacent tiles where both have data."""
import sys, itertools, numpy as np, rasterio
from rasterio.windows import from_bounds
from pystac_client import Client
day, orbit = sys.argv[1], sys.argv[2]
its = [i for i in Client.open("https://earth-search.aws.element84.com/v1").search(collections=["sentinel-2-c1-l2a"], datetime=day, bbox=[-3.6, 36.95, -2.9, 37.25]).items() if f"_{orbit}_" in i.properties["s2:product_uri"]]
bounds = {}
for i in its:
    with rasterio.open(i.assets["scl"].href) as s: bounds[i.id] = s.bounds
for a, b in itertools.combinations(sorted(its, key=lambda i: i.id), 2):
    A, B = bounds[a.id], bounds[b.id]
    l, bo, r, t = max(A.left, B.left), max(A.bottom, B.bottom), min(A.right, B.right), min(A.top, B.top)
    if r <= l or t <= bo: continue
    # sample a 4 km strip in the middle of the overlap
    cx, cy = (l + r) / 2, (bo + t) / 2
    box = (max(l, cx - 2000), max(bo, cy - 2000), min(r, cx + 2000), min(t, cy + 2000))
    out = {}
    for it in (a, b):
        for asset in ("swir16", "scl"):
            with rasterio.open(it.assets[asset].href) as s:
                out[(it.id, asset)] = s.read(1, window=from_bounds(*box, s.transform))
    da, db = out[(a.id, "swir16")].astype(int), out[(b.id, "swir16")].astype(int)
    m = (da > 0) & (db > 0)
    if m.sum() == 0: continue
    sa, sb = out[(a.id, "scl")], out[(b.id, "scl")]
    ms = (sa > 0) & (sb > 0)
    print(a.id.split("_")[1], b.id.split("_")[1], "px", int(m.sum()), "swir16 DN identical %.1f%%" % (100 * np.mean(da[m] == db[m])), "median|dDN| %d" % np.median(np.abs(da[m] - db[m])), "SCL identical %.1f%%" % (100 * np.mean(sa[ms] == sb[ms])))
