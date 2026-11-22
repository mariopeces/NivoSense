import json, sys
from collections import Counter, defaultdict
import numpy as np
P = [f["properties"] for f in json.load(open(sys.argv[1], encoding="utf-8"))["features"]]
S = ("snowline_band", "terrain_shadow", "forest", "cloud_edge", "open_terrain")
print("| stratum | scored (draw 1 / 2) | snow (draw 1 / 2) | no_snow | cloud | snow by in_strata membership (scored) |\n|---|---|---|---|---|---|")
for s in S:
    sc = [p for p in P if p["stratum"] == s and p["scored"]]
    c = Counter((p["draw"], p["label"]) for p in sc)
    mem = sum(1 for p in P if p["scored"] and s in p["in_strata"] and p["label"] == "snow")
    print(f"| {s} | {len(sc)} ({sum(1 for p in sc if p['draw']==1)} / {sum(1 for p in sc if p['draw']==2)}) | {c[(1,'snow')]+c[(2,'snow')]} ({c[(1,'snow')]} / {c[(2,'snow')]}) | {c[(1,'no_snow')]+c[(2,'no_snow')]} | {c[(1,'cloud')]+c[(2,'cloud')]} | {mem} |")
tot = Counter(p["label"] for p in P); print("\nall labels:", dict(tot))
# Sampling distribution of F1 for a stratum with n_snow reference snow points and n_neg reference non-snow points,
# for a classifier with true recall r and true false-positive rate chosen so true F1 = target.
rng = np.random.default_rng(7340211)
def sim(n_snow, n_neg, target, recall_eq_precision=True, reps=20000):
    # precision = recall = target in the stratum population mix of the sample
    r = target
    tp_mean = r * n_snow
    fp_mean = tp_mean * (1 - target) / target   # precision = target
    fpr = fp_mean / n_neg
    tp = rng.binomial(n_snow, r, reps); fp = rng.binomial(n_neg, fpr, reps)
    fn = n_snow - tp
    f1 = 2 * tp / (2 * tp + fp + fn)
    return np.percentile(f1, [2.5, 97.5]), np.mean(f1 < 0.70)
print("\n| stratum | n snow | n not snow | true F1 | 95% range of measured F1 | P(measured < 0.70) |\n|---|---|---|---|---|---|")
for s, ns, nn in (("forest", 43, None), ("cloud_edge", 44, None)):
    nn = sum(1 for p in P if p["stratum"] == s and p["scored"] and p["label"] != "snow")
    for t in (0.70, 0.75, 0.80, 0.85):
        (lo, hi), pf = sim(ns, nn, t)
        print(f"| {s} | {ns} | {nn} | {t:.2f} | {lo:.3f} to {hi:.3f} | {pf:.2f} |")
print("\n| n snow points | true F1 0.80: 95% range | half-width |\n|---|---|---|")
for ns in (43, 80, 100, 150, 200, 300):
    (lo, hi), _ = sim(ns, 300, 0.80)
    print(f"| {ns} | {lo:.3f} to {hi:.3f} | {(hi-lo)/2:.3f} |")
