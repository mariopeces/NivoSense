import sys, glob, numpy as np, rasterio
from pathlib import Path
from pipelines.s2.domain import load_domain
dom = load_domain(Path(sys.argv[1]))
for folder in sys.argv[2:]:
    with rasterio.open(folder + "/reflectance.tif") as s: g, r, w = s.read()
    with rasterio.open(folder + "/classes.tif") as s: scl, cp = s.read()
    m = dom.mask & np.isfinite(g)
    with np.errstate(invalid="ignore", divide="ignore"): ndsi = (g - w) / (g + w)
    p1 = m & (ndsi > 0.4) & (r > 0.2)
    print(folder.split("s2/")[-1], "pass1", int(p1.sum()), "scl11", int((m & (scl == 11)).sum()))
    for k in (8, 9, 10, 3):
        sel = m & (scl == k)
        if sel.sum() == 0: continue
        q = np.percentile(cp[sel], [1, 5, 25, 50, 75, 95])
        sp = p1 & (scl == k)
        hist = [int((sp & (cp <= t)).sum()) for t in (10, 20, 35, 50, 65)]
        print(f"  scl{k} n={int(sel.sum())} prob pct(1,5,25,50,75,95)={q.tolist()} pass1={int(sp.sum())} pass1&prob<=10,20,35,50,65: {hist}")
