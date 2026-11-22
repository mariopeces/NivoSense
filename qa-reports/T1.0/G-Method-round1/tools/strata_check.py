"""Independent recomputation of stratum inputs for the G-Method blind subset."""
import json, math, sys, urllib.request
from collections import Counter
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin
from rasterio.windows import Window
from make_chips import ENV as _E, item
ENV = dict(_E, CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.jp2")

full = json.load(open(sys.argv[1], encoding="utf-8"))
meta = {d["date"]: d for d in full["metadata"]["dates"]}
blind = [f["properties"] for f in json.load(open("blind_points.geojson"))["features"]]
xs = [p["x"] for p in blind]; ys = [p["y"] for p in blind]
PAD = 9000; RES = 20.0
left = math.floor((min(xs) - PAD) / 60) * 60; top = math.ceil((max(ys) + PAD) / 60) * 60
right = math.ceil((max(xs) + PAD) / 60) * 60; bottom = math.floor((min(ys) - PAD) / 60) * 60
W_, H_ = int((right - left) / RES), int((top - bottom) / RES)
T = from_origin(left, top, RES, RES)
dem = np.full((H_, W_), np.nan, dtype="float32")
GLO = "https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/Copernicus_DSM_COG_10_{a}_00_{b}_00_DEM/Copernicus_DSM_COG_10_{a}_00_{b}_00_DEM.tif"
with rasterio.Env(**ENV):
    for a in ("N36", "N37"):
        for b in ("W003", "W004"):
            with rasterio.open(GLO.format(a=a, b=b)) as s:
                part = np.full_like(dem, np.nan)
                reproject(rasterio.band(s, 1), part, dst_transform=T, dst_crs="EPSG:32630", dst_nodata=np.nan, resampling=Resampling.bilinear)
                m = np.isfinite(part); dem[m] = part[m]
print("dem", dem.shape, np.nanmin(dem), np.nanmax(dem))

def rc(x, y): return int((top - y) // RES), int((x - left) // RES)
def cos_i(r, c, az, el):
    dzdn = (dem[r - 1, c] - dem[r + 1, c]) / (2 * RES); dzde = (dem[r, c + 1] - dem[r, c - 1]) / (2 * RES)
    a, e = math.radians(az), math.radians(el)
    s = (math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e))
    return (-dzde * s[0] - dzdn * s[1] + s[2]) / math.sqrt(dzde ** 2 + dzdn ** 2 + 1)
def shadow(r, c, az, el, maxd=8000.0):
    a = math.radians(az); t = math.tan(math.radians(el)); z0 = dem[r, c]
    for step in range(1, int(maxd / RES) + 1):
        rr = r + int(round(-math.cos(a) * step)); cc = c + int(round(math.sin(a) * step))
        if not (0 <= rr < H_ and 0 <= cc < W_): return False
        if dem[rr, cc] > z0 + step * RES * t: return True
    return False

# WorldCover 10 m class 10 fraction in the 20 m pixel
WC = {t: f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{t}_Map.tif" for t in ("N36W006", "N36W003")}
def tree_fraction(lon, lat, x, y, src):
    from pyproj import Transformer
    tr = Transformer.from_crs(32630, 4326, always_xy=True)
    cells = [(x - 5, y + 5), (x + 5, y + 5), (x - 5, y - 5), (x + 5, y - 5)]
    ll = [tr.transform(*q) for q in cells]
    tot = 0
    for q in ll:
        ds = src["N36W006"] if q[0] < -3.0 else src["N36W003"]
        v = next(ds.sample([q]))[0]
        assert v != 0, ("worldcover nodata", q)
        tot += int(v == 10)
    return tot / 4

# SCL cloud edge: cloud (8,9,10) and clear (not cloud, not 0) both within 5 px (100 m) square, pixel itself in one of them
def scl_items(day):
    out = {}
    for sid in meta[day]["l2a_scene_ids"]:
        it = json.load(urllib.request.urlopen(f"https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a/items/{sid}", timeout=60))
        out.setdefault(sid.split("_")[1].lstrip("T"), []).append(it)
    return out
scl_cache = {}
rows = []
with rasterio.Env(**ENV), rasterio.open(WC["N36W006"]) as wa, rasterio.open(WC["N36W003"]) as wb:
    wc = {"N36W006": wa, "N36W003": wb}
    for p in blind:
        day = p["date"]; it = item(p["chip_scene_id"], "cache")
        # sun angles: mean over the L2A items of the date, as the builder documents
        if day not in scl_cache: scl_cache[day] = scl_items(day)
        l2a = [i for v in scl_cache[day].values() for i in v]
        az = float(np.mean([i["properties"]["view:sun_azimuth"] for i in l2a])); el = float(np.mean([i["properties"]["view:sun_elevation"] for i in l2a]))
        r, c = rc(p["x"], p["y"])
        z = float(dem[r, c]); ci = cos_i(r, c, az, el); sh = shadow(r, c, az, el)
        tf = tree_fraction(None, None, p["x"], p["y"], wc)
        tile = p["chip_scene_id"].split("_")[1]
        cloud_edge = None; centre = None
        for l2 in scl_cache[day].get(tile, []):
            with rasterio.open(l2["assets"]["scl"]["href"]) as s:
                col = int((p["x"] - s.transform.c) // 20); row = int((s.transform.f - p["y"]) // 20)
                win = s.read(1, window=Window(col - 5, row - 5, 11, 11), boundless=True, fill_value=0)
            if win[5, 5] == 0: continue
            cl = np.isin(win, (8, 9, 10)); clear = (~cl) & (win != 0)
            cloud_edge = bool((cl[5, 5] and clear.any()) or (clear[5, 5] and cl.any())); centre = int(win[5, 5]); break
        sl = meta[day]["snowline_m"]
        mine = {
            "snowline_band": sl is not None and abs(z - sl) <= 200,
            "terrain_shadow": sh or ci < math.cos(math.radians(80)),
            "forest": tf >= 0.5,
            "cloud_edge": cloud_edge,
        }
        rows.append(dict(id=p["id"], stratum=p["stratum"], in_strata=p["in_strata"], z=z, z_b=p["elevation_m"], ci=ci, ci_b=p["cos_incidence"], sh=sh, sh_b=p["cast_shadow"], tf=tf, tf_b=p["tree_fraction"], scl=centre, mine=mine))
json.dump(rows, open("strata_check.json", "w"), indent=0, default=str)
dz = np.array([r["z"] - r["z_b"] for r in rows]); dci = np.array([r["ci"] - r["ci_b"] for r in rows]); dtf = np.array([r["tf"] - r["tf_b"] for r in rows])
print(f"elevation diff m: median {np.median(dz):.1f}, p95 abs {np.percentile(abs(dz),95):.1f}, max abs {abs(dz).max():.1f}")
print(f"cos_incidence diff: median {np.median(dci):.3f}, p95 abs {np.percentile(abs(dci),95):.3f}, max abs {abs(dci).max():.3f}")
print(f"tree fraction diff: exact {np.mean(dtf==0):.2%}, max abs {abs(dtf).max():.2f}")
print(f"cast shadow agree {np.mean([r['sh']==r['sh_b'] for r in rows]):.2%}")
# drawn stratum supported by my layers?
print("\n| drawn stratum | n | my layers put the point in that stratum | in_strata membership agreement (per stratum flag) |\n|---|---|---|---|")
for s in ("snowline_band", "terrain_shadow", "forest", "cloud_edge", "open_terrain"):
    rs = [r for r in rows if r["stratum"] == s]
    if s == "open_terrain":
        ok = [not any(v for v in r["mine"].values()) and r["tf"] == 0 for r in rs]
    else:
        ok = [bool(r["mine"][s]) for r in rs]
    flags = [bool(r["mine"].get(s)) == (s in r["in_strata"]) for r in rows] if s != "open_terrain" else [((not any(v for v in r["mine"].values()) and r["tf"] == 0) == (s in r["in_strata"])) for r in rows]
    print(f"| {s} | {len(rs)} | {sum(ok)}/{len(rs)} | {sum(flags)}/{len(flags)} |")
miss = [(r["id"], r["stratum"], r["mine"], r["z"], r["z_b"], round(r["ci"],3), r["ci_b"], r["sh"], r["sh_b"], r["tf"], r["tf_b"], r["scl"]) for r in rows
        if (r["stratum"] != "open_terrain" and not r["mine"][r["stratum"]]) or (r["stratum"] == "open_terrain" and (any(v for v in r["mine"].values()) or r["tf"] > 0))]
print("\nmismatches:"); [print(m) for m in miss]
