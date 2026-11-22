"""Render the builder's mosaics: SWIR/red/green false colour, green-only grey and SCL, with tile edges."""
import sys, json, glob, os
import numpy as np, rasterio, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
out, dest = sys.argv[1], sys.argv[2]
SCLC = ["#000000","#ff0000","#2f2f2f","#643200","#00a000","#ffe65a","#0000ff","#808080","#c0c0c0","#ffffff","#64c8ff","#ff96ff"]
for rec in sorted(glob.glob(f"{out}/*/*/record.json")):
    r = json.load(open(rec)); f = os.path.dirname(rec)
    with rasterio.open(f+"/reflectance.tif") as s: g, rd, sw = s.read(1), s.read(2), s.read(3)
    with rasterio.open(f+"/classes.tif") as s: scl, cld = s.read(1), s.read(2)
    def st(a, lo=0.0, hi=0.6): return np.clip((np.nan_to_num(a, nan=0)-lo)/(hi-lo), 0, 1)
    fc = np.dstack([st(sw), st(rd), st(g)])
    fig, ax = plt.subplots(1, 3, figsize=(24, 7))
    ax[0].imshow(fc); ax[0].set_title(f"{r['date']} {r['orbit']} SWIR16/red/green  tiles {r['tiles']}")
    ax[1].imshow(st(g, 0, 1.0), cmap="gray"); ax[1].set_title(f"green refl 0..1, NaN black; nan={np.isnan(g).mean():.3f}")
    ax[2].imshow(scl, cmap=ListedColormap(SCLC), vmin=0, vmax=11, interpolation="nearest"); ax[2].set_title(f"SCL; cov {r['domain_coverage']} valid {r['domain_valid_fraction']}")
    for a in ax: a.axis("off")
    plt.tight_layout(); plt.savefig(f"{dest}/mosaic_{r['date']}_{r['orbit']}.png", dpi=55); plt.close()
    print(r["date"], r["orbit"], "green range", np.nanmin(g), np.nanmax(g), "neg frac", np.nanmean(g<0), "swir range", np.nanmin(sw), np.nanmax(sw))
