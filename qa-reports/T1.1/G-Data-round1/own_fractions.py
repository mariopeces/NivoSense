"""G-Data independent coverage/valid computation.
Grouping: by datatake (platform + sensing start in s2:product_uri), not date/orbit.
Domain test: shapely intersection of footprint with the domain union (not rasterised).
Pixels: each SCL COG read through a WarpedVRT onto my own 20 m grid (nearest), mask via geometry_mask.
"""
import json, sys, collections
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
left, top = np.floor(minx/20)*20, np.ceil(maxy/20)*20
W, H = int(np.ceil((maxx-left)/20)), int(np.ceil((top-miny)/20))
T = from_origin(left, top, 20, 20)
inside = ~geometry_mask([mapping(dom_utm)], (H, W), T)
N = inside.sum(); print("domain pixels", N, file=sys.stderr)

items = json.load(open("raw_items.json"))["sentinel-2-c1-l2a"]
dts = collections.defaultdict(list)
for it in items:
    p = it["properties"]
    if not ("2026-10-01" <= p["datetime"][:10] <= "2026-11-21"): continue
    if not shape(it["geometry"]).intersects(dom): continue
    pu = p["s2:product_uri"].split("_")
    dts[(pu[0], pu[2], pu[4])].append(it)
rows = []
env = rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4")
with env:
    for (plat, start, orb), its in sorted(dts.items(), key=lambda k: k[0][1]):
        acc = np.zeros((H, W), np.uint8)
        for it in its:
            with rasterio.open(it["assets"]["scl"]["href"]) as src, WarpedVRT(src, crs="EPSG:32630", transform=T, width=W, height=H, resampling=Resampling.nearest, nodata=0) as v:
                a = v.read(1)
            fill = (acc == 0) & (a != 0); acc[fill] = a[fill]
        s = acc[inside]
        cov = (s != 0).mean(); val = (~np.isin(s, [0,1,3,8,9,10])).mean()
        tiles = sorted({it["properties"]["grid:code"][5:] for it in its})
        rows.append(dict(date=f"{start[:4]}-{start[4:6]}-{start[6:8]}", platform=plat, orbit=orb, tiles=tiles, n_items=len(its),
                         ids=sorted(it["id"] for it in its), coverage=round(float(cov),4), valid=round(float(val),4)))
        print(rows[-1]["date"], orb, tiles, len(its), rows[-1]["coverage"], rows[-1]["valid"], file=sys.stderr)
json.dump(rows, open("own_fractions.json", "w"), indent=1)
