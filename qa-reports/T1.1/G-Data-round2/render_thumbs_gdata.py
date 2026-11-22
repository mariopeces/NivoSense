"""Render PR mosaics for visual review: SWIR16/red/green false colour, green grey (NaN black), SCL.
argv[1] = destination folder, argv[2:] = record folders (<date>/<orbit>)."""
import json, os, sys
import numpy as np, rasterio, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
SCLC = ["#000000","#ff0000","#2f2f2f","#643200","#00a000","#ffe65a","#0000ff","#808080","#c0c0c0","#ffffff","#64c8ff","#ff96ff"]
dest = sys.argv[1]; os.makedirs(dest, exist_ok=True)
for f in sys.argv[2:]:
    r = json.load(open(f + "/record.json"))
    with rasterio.open(f + "/reflectance.tif") as s: g, rd, sw = s.read(1), s.read(2), s.read(3)
    with rasterio.open(f + "/classes.tif") as s: scl = s.read(1)
    st = lambda a, lo=0.0, hi=0.6: np.clip((np.nan_to_num(a, nan=0) - lo) / (hi - lo), 0, 1)
    fig, ax = plt.subplots(1, 3, figsize=(24, 7))
    ax[0].imshow(np.dstack([st(sw), st(rd), st(g)])); ax[0].set_title(f"{r['date']} {r['orbit']} {r['datatake']} SWIR16/red/green {r['tiles']}")
    ax[1].imshow(st(g, 0, 1.0), cmap="gray"); ax[1].set_title(f"green 0..1, NaN black; nan={np.isnan(g).mean():.3f}")
    ax[2].imshow(scl, cmap=ListedColormap(SCLC), vmin=0, vmax=11, interpolation="nearest")
    ax[2].set_title(f"SCL; cov {r['domain_coverage']} valid {r['domain_valid_fraction']} listed {r['listed']}")
    for a in ax: a.axis("off")
    plt.tight_layout(); plt.savefig(f"{dest}/mosaic_{r['date']}_{r['orbit']}.png", dpi=50); plt.close()
    print(r["date"], r["orbit"], "green", float(np.nanmin(g)), float(np.nanmax(g)), "swir", float(np.nanmin(sw)), float(np.nanmax(sw)),
          "scl values", sorted(np.unique(scl).tolist()), "dtype", g.dtype, scl.dtype)
