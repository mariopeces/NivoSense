import json, sys
mine = {(r["date"], r["orbit"]): r for r in json.load(open(sys.argv[1]))}
theirs = {(r["date"], r["orbit"]): r for r in json.load(open(sys.argv[2]))}
print("keys only mine", sorted(set(mine) - set(theirs)), "only builder", sorted(set(theirs) - set(mine)))
bad = 0
for k in sorted(mine):
    m, t = mine[k], theirs.get(k)
    if not t: continue
    diffs = []
    if m["tiles"] != t["tiles"]: diffs.append(("tiles", m["tiles"], t["tiles"]))
    if abs(m["coverage"] - t["domain_coverage"]) > 1e-4: diffs.append(("cov", m["coverage"], t["domain_coverage"]))
    if abs(m["valid"] - t["domain_valid_fraction"]) > 1e-4: diffs.append(("valid", m["valid"], t["domain_valid_fraction"]))
    if m["listed"] != t["listed"]: diffs.append(("listed", m["listed"], t["listed"]))
    if sorted(m["ids"]) != sorted(t["scene_ids"]): diffs.append(("ids", m["ids"], t["scene_ids"]))
    bad += bool(diffs)
    print(k[0], k[1], ",".join(m["tiles"]), t["complete"], m["n_granules"], m["coverage"], t["domain_coverage"], m["valid"], t["domain_valid_fraction"], m["listed"], t["listed"], max(m["eo_cloud_cover"]), "DIFF" if diffs else "ok", diffs or "")
print("mismatching rows", bad, "of", len(mine))
print("listed mine", [k for k in sorted(mine) if mine[k]["listed"]])
