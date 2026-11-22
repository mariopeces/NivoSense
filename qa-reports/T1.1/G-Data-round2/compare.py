"""Compare the PR's records (full run, monthly chunks under argv[1]) with own_fractions.json, and validate
every decision object against T0.4's s2_decision schema (path argv[2]) and its consistency with the record."""
import collections, glob, json, os, sys
import jsonschema
full = sys.argv[1]
schema = json.load(open(sys.argv[2]))
own = json.load(open("own_fractions.json"))["rows"]
own_pass = collections.defaultdict(list)
for r in own:
    own_pass[(r["date"], r["orbit"])].append(r)
recs = {}
for f in sorted(glob.glob(f"{full}/*/records.json")):
    for r in json.load(open(f)):
        recs[(r["date"], r["orbit"])] = r
problems, rows = [], []
for key in sorted(set(own_pass) | set(recs)):
    o, r = own_pass.get(key), recs.get(key)
    if o is None or r is None:
        problems.append(f"{key}: only in {'PR' if o is None else 'own query'}"); continue
    # independent choice of datatake: highest valid fraction, then coverage
    best = max(o, key=lambda x: (x["valid"], x["coverage"]))
    own_listed = best["valid"] >= 0.30
    row = dict(date=key[0], orbit=key[1], pr_tiles=",".join(r["tiles"]), own_tiles=",".join(best["tiles"]),
               pr_ids=sorted(r["scene_ids"]) == best["ids"], pr_cov=r["domain_coverage"], own_cov=best["coverage"],
               pr_valid=r["domain_valid_fraction"], own_valid=best["valid"], pr_listed=r["listed"], own_listed=own_listed,
               complete=r["complete"], n_datatakes=len(o), alternatives=len(r["alternatives"]))
    rows.append(row)
    if not row["pr_ids"]: problems.append(f"{key}: scene ids differ {r['scene_ids']} vs {best['ids']}")
    if abs(r["domain_coverage"] - best["coverage"]) > 1e-4: problems.append(f"{key}: coverage {r['domain_coverage']} vs {best['coverage']}")
    if abs(r["domain_valid_fraction"] - best["valid"]) > 1e-4: problems.append(f"{key}: valid {r['domain_valid_fraction']} vs {best['valid']}")
    if r["listed"] != own_listed: problems.append(f"{key}: listed {r['listed']} vs {own_listed}")
    if len(r["alternatives"]) != len(o) - 1: problems.append(f"{key}: {len(r['alternatives'])} alternatives vs {len(o)-1}")
    for alt in r["alternatives"]:
        m = next((x for x in o if sorted(alt["scene_ids"]) == x["ids"]), None)
        if m is None or abs(m["valid"] - alt["domain_valid_fraction"]) > 1e-4 or abs(m["coverage"] - alt["domain_coverage"]) > 1e-4:
            problems.append(f"{key}: alternative {alt['datatake']} differs from own {m}")
# decisions
decisions = {}
for f in glob.glob(f"{full}/*/catalogue/s2/decisions/*.json"):
    d = json.load(open(f)); decisions[os.path.basename(f)[:-5]] = d
    try: jsonschema.validate(d, schema)
    except jsonschema.ValidationError as e: problems.append(f"decision {f}: {e.message}")
for (d, o), r in recs.items():
    dec = decisions.get(f"{d}_{o}")
    if dec is None: problems.append(f"{d} {o}: no decision object"); continue
    for k in ("scene_ids", "domain_coverage", "domain_valid_fraction", "complete", "listed"):
        if dec[k] != r[k]: problems.append(f"{d} {o}: decision {k} {dec[k]} != record {r[k]}")
    if not r["listed"] and not (dec["complete"] and dec["domain_valid_fraction"] < 0.30 and dec["domain_valid_fraction"] <= dec["domain_coverage"]):
        problems.append(f"{d} {o}: unlisted but the decision would not explain it to qa/freshness")
extra = set(decisions) - {f"{d}_{o}" for d, o in recs}
if extra: problems.append(f"decisions without a record: {sorted(extra)}")
listed_dates = sorted({r["date"] for r in recs.values() if r["listed"]})
own_dates = sorted({k[0] for k, v in own_pass.items() if max(x["valid"] for x in v) >= 0.30})
summary = dict(pr_passes=len(recs), own_passes=len(own_pass), own_datatakes=len(own), decisions=len(decisions),
               incomplete=[k for k, r in recs.items() if not r["complete"]],
               pr_listed_dates=listed_dates, own_listed_dates=own_dates,
               d_2026_11_10=[(k[1], r["listed"], r["domain_valid_fraction"]) for k, r in recs.items() if k[0] == "2026-11-10"],
               d_2026_11_05=[(k[1], r["listed"], r["domain_coverage"], r["domain_valid_fraction"]) for k, r in recs.items() if k[0] == "2026-11-05"],
               problems=problems)
json.dump({"summary": summary, "rows": rows}, open("compare.json", "w"), indent=1)
with open("compare.md", "w") as f:
    f.write("| date | orbit | tiles PR / own | ids equal | coverage PR / own | valid PR / own | listed PR / own | complete | datatakes |\n|---|---|---|---|---|---|---|---|---|\n")
    for r in rows:
        f.write(f"| {r['date']} | {r['orbit']} | {r['pr_tiles']} / {r['own_tiles']} | {r['pr_ids']} | {r['pr_cov']:.4f} / {r['own_cov']:.4f} | "
                f"{r['pr_valid']:.4f} / {r['own_valid']:.4f} | {r['pr_listed']} / {r['own_listed']} | {r['complete']} | {r['n_datatakes']} |\n")
print(json.dumps(summary, indent=1))
