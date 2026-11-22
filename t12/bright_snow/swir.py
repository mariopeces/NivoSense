import sys, numpy as np, rasterio
from pathlib import Path
from pipelines.s2.domain import load_domain
dom = load_domain(Path(sys.argv[1]))
def load(f):
    with rasterio.open(f + "/reflectance.tif") as s: g, r, w = s.read()
    with rasterio.open(f + "/classes.tif") as s: scl, cp = s.read()
    m = dom.mask & np.isfinite(g)
    with np.errstate(invalid="ignore", divide="ignore"): n = (g - w) / (g + w)
    p1 = m & (n > 0.4) & (r > 0.2)
    return g, r, w, n, scl, cp, p1
P = [1, 5, 25, 50, 75, 95, 99]
for f in sys.argv[2:]:
    g, r, w, n, scl, cp, p1 = load(f)
    print(f.split("s2/")[-1])
    for name, sel in (("scl11", p1 & (scl == 11)), ("scl8", p1 & (scl == 8)), ("scl9", p1 & (scl == 9)), ("scl10", p1 & (scl == 10))):
        if sel.sum() < 100: continue
        print(f"  {name:6s} n={int(sel.sum()):8d} swir16 {np.round(np.percentile(w[sel], P), 3).tolist()} ndsi {np.round(np.percentile(n[sel], P), 2).tolist()} red {np.round(np.percentile(r[sel],[5,50,95]),2).tolist()}")
