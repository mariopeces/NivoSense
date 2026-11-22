"""Magnitude of tile-to-tile L2A differences in overlaps (clear land pixels, both SCL 4/5/11), swir16 and red (20 m)."""
import sys, json, itertools, numpy as np, rasterio
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling
out = sys.argv[1]
items = {i["id"]: i for i in json.load(open("raw_items.json"))["sentinel-2-c1-l2a"]}
res = {}
for day, orb in [("2026-11-10","R094"),("2026-10-21","R094"),("2026-11-17","R051")]:
    rec = json.load(open(f"{out}/{day}/{orb}/record.json"))
    with rasterio.open(f"{out}/{day}/{orb}/classes.tif") as m: T, H, W = m.transform, m.height, m.width
    arr = {}
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        for sid in rec["scene_ids"]:
            d = {}
            for a, href in (("swir16", items[sid]["assets"]["swir16"]["href"]), ("scl", items[sid]["assets"]["scl"]["href"]), ("red20", items[sid]["assets"]["red"]["href"].replace("/B04.tif","/B04.tif"))):
                with rasterio.open(href) as s, WarpedVRT(s, crs="EPSG:32630", transform=T, width=W, height=H, resampling=Resampling.average if a=="red20" else Resampling.nearest, nodata=0) as v:
                    d[a] = v.read(1).astype("float32")
            arr[sid] = d
    for a, b in itertools.combinations(arr, 2):
        A, B = arr[a], arr[b]
        clear = np.isin(A["scl"], [4,5,11]) & np.isin(B["scl"], [4,5,11])
        if clear.sum() < 1000: continue
        for band in ("swir16","red20"):
            dd = (A[band][clear] - B[band][clear]) * 1e-4
            rel = np.abs(dd) / np.maximum((B[band][clear]*1e-4 - 0.1), 0.01)
            key = f"{day} {orb} {a[4:9]}/{a[-19:-4]} x {b[4:9]}/{b[-19:-4]} {band}"
            res[key] = dict(n=int(clear.sum()), bias=round(float(dd.mean()),4), median_abs=round(float(np.median(np.abs(dd))),4), p95_abs=round(float(np.percentile(np.abs(dd),95)),4), median_rel=round(float(np.median(rel)),3))
            print(key, res[key])
json.dump(res, open("seam_stats.json","w"), indent=1)
