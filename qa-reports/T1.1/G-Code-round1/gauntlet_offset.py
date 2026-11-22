"""Spot-check: builder reflectance vs DN*scale+offset from the source COG, 200 random domain pixels."""
import sys, json, numpy as np, rasterio
from rasterio.windows import Window
from pystac_client import Client
folder = sys.argv[1]
rec = json.load(open(folder + "/record.json"))
items = {i.id: i for i in Client.open("https://earth-search.aws.element84.com/v1").search(ids=rec["scene_ids"], collections=["sentinel-2-c1-l2a"]).items()}
with rasterio.open(folder + "/reflectance.tif") as r:
    refl = r.read(); tr = r.transform
rng = np.random.default_rng(7)
ok = bad = 0; err_no_offset = []
rows, cols = np.where(np.isfinite(refl[2]))
pick = rng.choice(len(rows), 200, replace=False)
for k in pick:
    row, col = rows[k], cols[k]
    x, y = tr * (col + 0.5, row + 0.5)
    for it in items.values():
        a = it.assets["swir16"]; rb = a.extra_fields["raster:bands"][0]
        with rasterio.open(a.href) as s:
            rr, cc = s.index(x, y)
            if not (0 <= rr < s.height and 0 <= cc < s.width): continue
            dn = int(s.read(1, window=Window(cc, rr, 1, 1))[0, 0])
        if dn == 0: continue
        expect = dn * rb["scale"] + rb["offset"]
        if abs(refl[2, row, col] - expect) < 1e-5: ok += 1
        else: bad += 1
        err_no_offset.append(abs(refl[2, row, col] - dn * rb["scale"]))
        break
print(folder.split("out/")[-1], "baselines", sorted(set(rec["processing_baselines"])), "swir16 match DN*scale+offset:", ok, "mismatch:", bad, "| mean |diff| if offset ignored:", round(float(np.mean(err_no_offset)), 4))
