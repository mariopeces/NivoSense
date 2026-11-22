import sys, numpy as np, rasterio
from PIL import Image
folder, out = sys.argv[1], sys.argv[2]
step = 3
with rasterio.open(folder + "/reflectance.tif") as s: g, r, w = s.read()
with rasterio.open(folder + "/classes.tif") as s: scl, cp = s.read()
with np.errstate(invalid="ignore", divide="ignore"): n = (g - w) / (g + w)
p1 = (n > 0.4) & (r > 0.2)
fix = p1 & np.isin(scl, (8, 9)) & (cp <= 35)
st = lambda a: (np.clip(np.nan_to_num(a) / 0.8, 0, 1) ** (1 / 1.6) * 255).astype("uint8")
fc = np.dstack([st(w), st(r), st(g)])
ov = fc.copy()
ov[(scl == 8) & ~fix] = (255, 120, 120)
ov[fix] = (255, 0, 255)
h, wd = fix.shape
blocks = fix[: h // step * step, : wd // step * step].reshape(h // step, step, wd // step, step).any(axis=(1, 3))
small = ov[::step, ::step][: h // step, : wd // step].copy()
small[blocks] = (255, 0, 255)
Image.fromarray(np.vstack([fc[::step, ::step][: h // step, : wd // step], small])).save(out)
print("fix pixels", int(fix.sum()), "of which prob==0:", int((fix & (cp == 0)).sum()))
