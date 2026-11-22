"""Pairwise agreement of overlapping granules (swir16 DN and SCL, native 20 m) on the builder's grid,
and agreement of the builder's mosaic with each granule over that granule's data area."""
import sys, json, itertools, numpy as np, rasterio
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling
out = sys.argv[1]
items = {i["id"]: i for i in json.load(open("raw_items.json"))["sentinel-2-c1-l2a"]}
for day, orb in [("2026-11-10","R094"),("2026-11-17","R051"),("2026-10-21","R094")]:
    rec = json.load(open(f"{out}/{day}/{orb}/record.json"))
    with rasterio.open(f"{out}/{day}/{orb}/reflectance.tif") as m:
        T, H, W = m.transform, m.height, m.width; msw = m.read(3)
    with rasterio.open(f"{out}/{day}/{orb}/classes.tif") as m: mscl = m.read(1)
    arr = {}
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        for sid in rec["scene_ids"]:
            it = items[sid]; d = {}
            for a in ("swir16","scl"):
                with rasterio.open(it["assets"][a]["href"]) as s, WarpedVRT(s, crs="EPSG:32630", transform=T, width=W, height=H, resampling=Resampling.nearest, nodata=0) as v:
                    d[a] = v.read(1)
            arr[sid] = d
    print(f"== {day} {orb}")
    for sid, d in arr.items():
        has = d["scl"] > 0
        refl = d["swir16"].astype("float32")*1e-4 - 0.1
        okm = has & np.isfinite(msw)
        print(f"  {sid}: data px {has.sum()}, mosaic-vs-granule swir maxabs {np.nanmax(np.abs(msw[okm]-refl[okm])) if okm.any() else 'n/a':.6f}, scl agree {np.mean(mscl[has]==d['scl'][has]):.6f}")
    for a, b in itertools.combinations(arr, 2):
        ov = (arr[a]["scl"] > 0) & (arr[b]["scl"] > 0)
        if ov.sum() == 0: print(f"  {a[:10]}..{a[-20:]} x {b[-20:]}: no overlap"); continue
        dsw = np.abs(arr[a]["swir16"][ov].astype(int) - arr[b]["swir16"][ov].astype(int))
        print(f"  overlap {a[4:9]}{a[-19:-4]} x {b[4:9]}{b[-19:-4]}: {ov.sum()} px, swir DN equal {np.mean(dsw==0):.4f}, max diff {dsw.max()}, scl equal {np.mean(arr[a]['scl'][ov]==arr[b]['scl'][ov]):.4f}")
