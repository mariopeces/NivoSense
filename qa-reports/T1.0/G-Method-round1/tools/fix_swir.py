"""Re-read B11 on whole 20 m pixels and crop to the 10 m-aligned window (fixes a 10 m shift)."""
import json, math, os, sys
from collections import defaultdict
from multiprocessing import Pool
import numpy as np
from make_chips import ENV, item, Z

def read(args):
    import rasterio
    from rasterio.windows import Window
    scene, pts, cache = args
    it = item(scene, cache)
    b = it["assets"]["swir16"]; sc, of = b["raster:bands"][0]["scale"], b["raster:bands"][0]["offset"]
    out = {}
    with rasterio.Env(**ENV), rasterio.open("/vsis3/" + b["href"][5:]) as d:
        for pid, x, y in pts:
            # left/top edge of the 10 m window in 20 m pixel units (k - 17.5 for a 20 m pixel centre)
            c0 = (x - Z * 5 - d.transform.c) / 20.0; r0 = (d.transform.f - (y + Z * 5)) / 20.0
            ci, ri = math.floor(c0), math.floor(r0)
            a = d.read(1, window=Window(ci, ri, Z // 2 + 1, Z // 2 + 1), boundless=True, fill_value=0).astype("float32")
            a = np.where(a == 0, np.nan, a * sc + of).repeat(2, 0).repeat(2, 1)
            dc, dr = int(round((c0 - ci) * 2)), int(round((r0 - ri) * 2))
            out[pid] = a[dr:dr + Z, dc:dc + Z]
    return out

if __name__ == "__main__":
    feats = json.load(open("blind_points.geojson", encoding="utf-8"))["features"]
    by = defaultdict(list)
    for f in feats:
        p = f["properties"]; by[p["chip_scene_id"]].append((p["id"], p["x"], p["y"]))
    res = np.load("cache/chips.npy", allow_pickle=True).item()
    with Pool(8) as pool:
        for part in pool.imap_unordered(read, [(s, v, "cache") for s, v in by.items()]):
            for pid, a in part.items():
                old = res[pid][("swir16", "z")]
                res[pid][("swir16", "z")] = a
    np.save("cache/chips_fixed.npy", res, allow_pickle=True)
    # sanity: old shifted array should equal new shifted by one 10 m px
    pid = feats[0]["properties"]["id"]
    print("done", len(res))
