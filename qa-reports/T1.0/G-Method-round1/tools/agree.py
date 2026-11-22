import csv, json, sys, math
from collections import Counter, defaultdict
pts = {f["properties"]["id"]: f["properties"] for f in json.load(open(sys.argv[1], encoding="utf-8"))["features"]}
rel = {r["id"]: r["label"] for r in csv.DictReader(open(sys.argv[2]))}
L = ("snow", "no_snow", "cloud", "unsure")
cross = Counter((pts[i]["label"], l) for i, l in rel.items())
def agg(keyf):
    g = defaultdict(lambda: Counter())
    for i, l in rel.items():
        p = pts[i]; k = keyf(p)
        g[k]["n"] += 1
        if "unsure" in (p["label"], l): g[k]["unsure_either"] += 1; continue
        g[k]["compared"] += 1; g[k]["agree"] += int(p["label"] == l)
        if p["label"] == "snow" or l == "snow":
            g[k]["snow_either"] += 1; g[k]["snow_both"] += int(p["label"] == l == "snow")
    return g
def wilson(k, n, z=1.96):
    if n == 0: return (None, None)
    ph = k / n; d = 1 + z * z / n; c = (ph + z * z / (2 * n)) / d; h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))
def table(title, g):
    print(f"\n### {title}\n\n| group | relabelled | unsure (either) | compared | agree | agreement | 95% CI (Wilson) |\n|---|---|---|---|---|---|---|")
    for k in sorted(g):
        c = g[k]; a = c["agree"] / c["compared"] if c["compared"] else None
        lo, hi = wilson(c["agree"], c["compared"])
        print(f"| {k} | {c['n']} | {c['unsure_either']} | {c['compared']} | {c['agree']} | {'' if a is None else f'{a:.3f}'} | {'' if lo is None else f'{lo}-{hi}'} |")
table("Overall", agg(lambda p: "all"))
table("Per stratum (drawn from)", agg(lambda p: p["stratum"]))
table("Per date", agg(lambda p: p["date"]))
table("Per draw", agg(lambda p: f"draw {p['draw']}"))
print("\n### Cross table (rows frozen label, columns G-Method relabel)\n\n| frozen \ G-Method | " + " | ".join(L) + " | total |\n|---|" + "---|" * (len(L) + 1))
for a in L:
    print(f"| {a} | " + " | ".join(str(cross[(a, b)]) for b in L) + f" | {sum(cross[(a, b)] for b in L)} |")
print("| total | " + " | ".join(str(sum(cross[(a, b)] for a in L)) for b in L) + f" | {sum(cross.values())} |")
# kappa on compared
comp = [(pts[i]["label"], l) for i, l in rel.items() if "unsure" not in (pts[i]["label"], l)]
n = len(comp); po = sum(a == b for a, b in comp) / n
ca = Counter(a for a, _ in comp); cb = Counter(b for _, b in comp)
pe = sum(ca[x] * cb[x] for x in L) / n / n
print(f"\nCohen's kappa (compared points): {(po - pe) / (1 - pe):.3f}; snow-class agreement: {sum(a==b=='snow' for a,b in comp)} both snow of {sum('snow' in (a,b) for a,b in comp)} with snow on either side")
print("\n### Disagreements (compared, excluding unsure)\n\n| id | date | draw | stratum | frozen | G-Method |\n|---|---|---|---|---|---|")
for i, l in sorted(rel.items()):
    p = pts[i]
    if "unsure" not in (p["label"], l) and p["label"] != l:
        print(f"| {i} | {p['date']} | {p['draw']} | {p['stratum']} | {p['label']} | {l} |")
