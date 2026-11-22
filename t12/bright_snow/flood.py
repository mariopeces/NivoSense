import sys, time, numpy as np, rasterio
from PIL import Image

def dilate(mask):
    out = mask.copy()
    out[1:] |= mask[:-1]; out[:-1] |= mask[1:]
    out[:, 1:] |= out[:, :-1].copy(); out[:, :-1] |= out[:, 1:].copy()
    return out

def flood(candidate, seed):
    reached = dilate(seed) & candidate
    frontier = reached
    n = 0
    while frontier.any():
        rows = np.flatnonzero(frontier.any(axis=1)); cols = np.flatnonzero(frontier.any(axis=0))
        r0, r1 = max(rows[0] - 1, 0), rows[-1] + 2; c0, c1 = max(cols[0] - 1, 0), cols[-1] + 2
        grown = dilate(frontier[r0:r1, c0:c1]) & candidate[r0:r1, c0:c1] & ~reached[r0:r1, c0:c1]
        frontier = np.zeros_like(frontier); frontier[r0:r1, c0:c1] = grown
        reached[r0:r1, c0:c1] |= grown
        n += 1
    return reached, n

folder, out = sys.argv[1], sys.argv[2]
with rasterio.open(folder + "/reflectance.tif") as s: g, r, w = s.read()
with rasterio.open(folder + "/classes.tif") as s: scl, cp = s.read()
with np.errstate(invalid="ignore", divide="ignore"): n = (g - w) / (g + w)
p1 = (n > 0.4) & (r > 0.2)
cand = (scl == 8) & p1
seed = np.isin(scl, tuple(int(x) for x in sys.argv[3].split(",")))
t = time.time(); reached, it = flood(scl == 8, seed); dt = time.time() - t
rescued = cand & ~reached
print(folder.split("s2/")[-1], "candidates", int(cand.sum()), "rescued", int(rescued.sum()), "iterations", it, f"{dt:.1f}s")
st = lambda a: (np.clip(np.nan_to_num(a) / 0.8, 0, 1) ** (1 / 1.6) * 255).astype("uint8")
fc = np.dstack([st(w), st(r), st(g)]); ov = fc.copy()
ov[(scl == 8) & ~rescued] = (255, 120, 120); ov[np.isin(scl, (9, 10))] = (255, 0, 0); ov[rescued] = (255, 0, 255)
step = 3
Image.fromarray(np.vstack([fc[::step, ::step], ov[::step, ::step]])).save(out)
