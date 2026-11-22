"""Draw G-Method's blind 10% subset; writes points WITHOUT label/scored fields."""
import json, random, sys
from collections import defaultdict
SEED = 7340211
src, out = sys.argv[1], sys.argv[2]
c = json.load(open(src, encoding="utf-8"))
print("metadata keys:", list(c["metadata"].keys()))
feats = c["features"]
cells = defaultdict(list)
for f in feats:
    p = f["properties"]
    cells[(p["draw"], p["date"], p["stratum"])].append(f)
rng = random.Random(SEED)
import math; target = math.ceil(len(feats) * 0.10)
picked, rema = [], []
for k in sorted(cells):
    members = sorted(cells[k], key=lambda f: f["properties"]["id"])
    n = len(members) * 0.10
    base = int(n)
    rng.shuffle(members)
    picked += members[:base]
    rema.append((n - base, k, members[base:]))
need = target - len(picked)
# remainders: probability proportional to fractional part (weighted sampling without replacement)
pool = [(r, k, m) for r, k, m in rema if r > 0 and m]
while need > 0 and pool:
    tot = sum(r for r, _, _ in pool)
    x = rng.random() * tot
    acc = 0
    for i, (r, k, m) in enumerate(pool):
        acc += r
        if acc >= x:
            picked.append(m[0]); pool.pop(i); need -= 1; break
strip = {"label", "scored"}
blind = []
for f in picked:
    p = {k: v for k, v in f["properties"].items() if k not in strip}
    blind.append({"type": "Feature", "geometry": f["geometry"], "properties": p})
blind.sort(key=lambda f: f["properties"]["id"])
json.dump({"type": "FeatureCollection", "metadata": {"seed": SEED, "source_sha256": sys.argv[3]}, "features": blind}, open(out, "w", encoding="utf-8"), indent=1)
from collections import Counter
print(len(blind), "of", len(feats))
print(Counter(f["properties"]["draw"] for f in blind))
print(sorted(Counter(f["properties"]["date"] for f in blind).items()))
print(Counter(f["properties"]["stratum"] for f in blind))
print("all props:", sorted(blind[0]["properties"].keys()))
