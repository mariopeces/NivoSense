"""G-Data independent coverage / valid fraction per datatake, 2025-10-01..2026-11-21 (round 2).
- Datatake = platform + sensing start parsed from s2:product_uri (not s2:datatake_id, which the PR uses).
- Domain touch: shapely intersection of the footprint with the domain union (not rasterised).
- Within one datatake and tile only the highest baseline (N#### in the product name) is kept; all its
  granules are kept. Precedence where granules overlap: tile name, then latest generation first
  (the PR's stated tie rule; SCL differs slightly in overlaps so a different rule moves the 4th decimal).
- SCL read through a WarpedVRT onto my own 20 m grid (nearest); domain mask via geometry_mask.
- Valid = SCL not in {0 nodata, 1 saturated, 3 cloud shadow, 8, 9 cloud, 10 cirrus}.
"""
import collections, gzip, json, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np, rasterio
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from shapely.geometry import shape, mapping
from shapely.ops import unary_union, transform as stransform
from pyproj import Transformer

dom = unary_union([shape(f["geometry"]) for f in json.load(open(sys.argv[1]))["features"]])
tr = Transformer.from_crs(4326, 32630, always_xy=True).transform
dom_utm = stransform(tr, dom)
minx, miny, maxx, maxy = dom_utm.bounds
left, top = np.floor(minx / 20) * 20, np.ceil(maxy / 20) * 20
W, H = int(np.ceil((maxx - left) / 20)), int(np.ceil((top - miny) / 20))
T = from_origin(left, top, 20, 20)
inside = ~geometry_mask([mapping(dom_utm)], (H, W), T)
print("domain pixels", int(inside.sum()), file=sys.stderr)

items = json.load(gzip.open("raw_items.json.gz", "rt"))
by_tile = collections.defaultdict(list)
for it in items:
    p = it["properties"]
    if not ("2025-10-01" <= p["datetime"][:10] <= "2026-11-21"):
        continue
    if not shape(it["geometry"]).intersects(dom):
        continue
    pu = p["s2:product_uri"].split("_")  # S2A MSIL2A 20261110T110211 N0513 R094 T30SVF 20261110T160053
    by_tile[(pu[2], pu[0], pu[4], pu[5][1:])].append((pu[3], pu[6], it))
multi_baseline = []
dts = collections.defaultdict(list)
for (start, plat, orb, tile), vs in by_tile.items():
    top_b = max(v[0] for v in vs)
    if len({v[0] for v in vs}) > 1:
        multi_baseline.append({"datatake": f"{plat}_{start}", "tile": tile, "baselines": sorted({v[0] for v in vs}),
                               "ids": sorted(v[2]["id"] for v in vs)})
    dts[(start, plat, orb)].extend((tile, gen, it) for b, gen, it in vs if b == top_b)

def read_scl(href):
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="5", GDAL_HTTP_RETRY_DELAY="2"):
        with rasterio.open(href) as src, WarpedVRT(src, crs="EPSG:32630", transform=T, width=W, height=H,
                                                   resampling=Resampling.nearest, nodata=0) as v:
            return v.read(1)

def one(key):
    start, plat, orb = key
    gran = sorted(sorted(dts[key], key=lambda g: g[1], reverse=True), key=lambda g: g[0])
    acc = np.zeros((H, W), np.uint8)
    for tile, gen, it in gran:
        a = read_scl(it["assets"]["scl"]["href"])
        fill = (acc == 0) & (a != 0)
        acc[fill] = a[fill]
    s = acc[inside]
    row = dict(date=f"{start[:4]}-{start[4:6]}-{start[6:8]}", platform=plat, orbit=orb, sensing=start,
               tiles=sorted({g[0] for g in gran}), ids=sorted(g[2]["id"] for g in gran),
               coverage=round(float((s != 0).mean()), 4),
               valid=round(float((~np.isin(s, [0, 1, 3, 8, 9, 10])).mean()), 4))
    print(row["date"], orb, plat, row["tiles"], row["coverage"], row["valid"], file=sys.stderr, flush=True)
    return row

with ThreadPoolExecutor(8) as ex:
    rows = list(ex.map(one, sorted(dts)))
json.dump({"rows": rows, "multi_baseline": multi_baseline}, open("own_fractions.json", "w"), indent=1)
print(len(rows), "datatakes;", len(multi_baseline), "multi-baseline tiles", file=sys.stderr)
