"""G-Method chips: read L1C windows straight from the recorded Earth Search scene ids."""
import json, os, random, sys, urllib.request
from collections import defaultdict
from multiprocessing import Pool
import numpy as np

ENV = dict(AWS_NO_SIGN_REQUEST="YES", AWS_REGION="eu-central-1", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
           CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".jp2", GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="3")
ITEM = "https://earth-search.aws.element84.com/v1/collections/sentinel-2-l1c/items/{}"
Z = 72      # zoom window, 10 m px (720 m)
CTX = 240   # context window, 10 m px (2.4 km), read decimated x2
BANDS = ["red", "green", "blue", "nir", "swir16"]

def item(scene, cache):
    p = os.path.join(cache, scene + ".json")
    if not os.path.exists(p):
        with urllib.request.urlopen(ITEM.format(scene), timeout=60) as r:
            open(p, "wb").write(r.read())
    return json.load(open(p))

def read_scene(args):
    import rasterio
    from rasterio.windows import Window
    scene, pts, cache = args
    it = item(scene, cache)
    out = {}
    with rasterio.Env(**ENV):
        ds = {b: rasterio.open("/vsis3/" + it["assets"][b]["href"][5:]) for b in BANDS}
        so = {b: (it["assets"][b]["raster:bands"][0]["scale"], it["assets"][b]["raster:bands"][0]["offset"]) for b in BANDS}
        for pid, x, y in pts:
            arr = {}
            for b in BANDS:
                d = ds[b]; res = d.res[0]
                c = (x - d.transform.c) / res; r = (d.transform.f - y) / res
                for name, size, dec in (("z", Z, 1), ("c", CTX, 2)):
                    if b in ("nir",) and name == "c":
                        continue
                    n = int(size * 10 / res)
                    w = Window(c - n / 2, r - n / 2, n, n)
                    a = d.read(1, window=w, boundless=True, fill_value=0, out_shape=(n // dec, n // dec) if dec > 1 else None).astype("float32")
                    refl = np.where(a == 0, np.nan, a * so[b][0] + so[b][1])
                    if res == 20:
                        refl = refl.repeat(2, 0).repeat(2, 1)
                    arr[(b, name)] = refl
            out[pid] = arr
    return out

def stretch(a, top=1.0, gamma=0.5):
    v = np.clip(np.nan_to_num(a, nan=0) / top, 0, 1) ** gamma
    return (v * 255).astype("uint8")

def rgb(arr, bands, name):
    return np.dstack([stretch(arr[(b, name)]) for b in bands])

def marks(img, scale, centre_px, half_px):
    big = img.repeat(scale, 0).repeat(scale, 1).copy()
    lo, hi = int((centre_px - half_px) * scale) - 3, int((centre_px + half_px) * scale) + 2
    t = 8
    for r, c, dr, dc in ((lo, lo, 1, 1), (lo, hi, 1, -1), (hi, lo, -1, 1), (hi, hi, -1, -1)):
        for s in range(t):
            for rr, cc in ((r + dr * s, c), (r, c + dc * s)):
                if 0 <= rr < big.shape[0] and 0 <= cc < big.shape[1]:
                    big[rr, cc] = (255, 0, 0)
    return big

def main():
    pts_path, cache, outdir, seed = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    os.makedirs(cache, exist_ok=True); os.makedirs(outdir, exist_ok=True)
    feats = json.load(open(pts_path, encoding="utf-8"))["features"]
    by_scene = defaultdict(list)
    for f in feats:
        p = f["properties"]; by_scene[p["chip_scene_id"]].append((p["id"], p["x"], p["y"]))
    with Pool(8) as pool:
        res = {}
        for part in pool.imap_unordered(read_scene, [(s, v, cache) for s, v in by_scene.items()]):
            res.update(part)
    np.save(os.path.join(cache, "chips.npy"), res, allow_pickle=True)
    from PIL import Image, ImageDraw, ImageFont
    order = sorted(feats, key=lambda f: f["properties"]["id"])
    random.Random(seed).shuffle(order)
    key = {}
    font = ImageFont.load_default(size=20)
    SC = 4; P = Z * SC; G = 8; CAP = 26
    per_page, cols = 6, 2
    cell_w = 3 * P + 2 * G
    for page in range(0, len(order), per_page):
        chunk = order[page:page + per_page]
        rows = -(-len(chunk) // cols)
        im = Image.new("RGB", (cols * (cell_w + 24), rows * (P + CAP + G)), (30, 30, 30))
        dr = ImageDraw.Draw(im)
        for i, f in enumerate(chunk):
            p = f["properties"]; n = page + i + 1; key[f"B{n:03d}"] = p["id"]
            a = res[p["id"]]
            left = (i % cols) * (cell_w + 24); top = (i // cols) * (P + CAP + G)
            tc = marks(rgb(a, ["red", "green", "blue"], "z"), SC, Z / 2, 1)
            sw = marks(rgb(a, ["swir16", "nir", "red"], "z"), SC, Z / 2, 1)
            cx = rgb(a, ["red", "green", "blue"], "c")  # 120 px of 20 m
            cxs = P / cx.shape[0]
            cxi = np.array(Image.fromarray(cx).resize((P, P), Image.NEAREST))
            c0 = P / 2; hz = (Z / 2) * 10 / 20 * cxs  # zoom box in context
            cxi = cxi.copy()
            lo, hi = int(c0 - hz), int(c0 + hz)
            cxi[lo, lo:hi] = cxi[hi, lo:hi] = (255, 255, 0); cxi[lo:hi, lo] = cxi[lo:hi, hi] = (255, 255, 0)
            for k, panel in enumerate((tc, sw, cxi)):
                im.paste(Image.fromarray(panel), (left + k * (P + G), top + CAP))
            dr.text((left, top + 2), f"B{n:03d}  {p['date']}", fill=(255, 255, 255), font=font)
        im.save(os.path.join(outdir, f"blind_{page // per_page:02d}.png"))
    json.dump(key, open(os.path.join(outdir, "key.json"), "w"), indent=0)
    print(len(res), "points,", -(-len(order) // per_page), "pages")

if __name__ == "__main__":
    main()
