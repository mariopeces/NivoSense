"""Drive the PR's ingest.run (dafc7f3, path in argv[1]) against LIVE Earth Search, real rasters, with a fetch
wrapper that hides or alters items to replay arrival orders. Writes local folders under argv[2].
Cases:
 A  2026-11-17 R051 split datatake, the later-generated 30SWG granule hidden on the first run, then a
    normal daily run (start = end = next day) sees both.
 B  same, reversed: the earlier-generated granule hidden first.
 C  late granule seen first 11 days later (outside REPROCESS_DAYS): is the date reopened?
 D  newer processing baseline: 2026-11-10 R094 built normally, then a copy of the 30SVF item with baseline
    05.14 (new id, product name N0514, datatake suffix N05.14, later generation) appears; daily run 11-15.
 E  rerun with unchanged inputs: record, rasters and decision untouched (mtime and bytes).
"""
import copy, hashlib, json, os, shutil, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from pipelines.s2 import ingest
from pipelines.s2.stac import fetch_json

ROOT = Path(sys.argv[2]); shutil.rmtree(ROOT, ignore_errors=True)
DOM = Path(sys.argv[1]) / "data/basins.geojson"
V = "dafc7f3e785b1c7422ae4ecf329cb2fdd9e0e1ff"
out = {}

def wrapper(hide=(), extra=()):
    def fetch(req):
        page = fetch_json(req)
        page["features"] = [f for f in page["features"] if f["id"] not in hide]
        body = json.loads(req.data)
        lo, hi = body["datetime"].split("/") if "datetime" in body else ("", "z")
        if not any(l["rel"] == "next" for l in page.get("links", [])):  # add synthetic items once, on the last page
            page["features"] += [e for e in extra if lo <= e["properties"]["datetime"] <= hi]
        return page
    return fetch

def rec(o, d, orb):
    return json.loads((o / "s2" / d / orb / "record.json").read_text())

def dec(o, d, orb):
    p = o / "cat" / "s2" / "decisions" / f"{d}_{orb}.json"
    return json.loads(p.read_text()) if p.exists() else None

def run(o, s, e, today, fetch):
    return ingest.run(DOM, s, e, o / "s2", today=today, fetch=fetch, catalogue_root=o / "cat", version=V)

# the two 30SWG granules of 2026-11-17, by generation time
items = [f for f in fetch_json(__import__("urllib.request").request.Request(
    "https://earth-search.aws.element84.com/v1/search",
    data=json.dumps({"collections": ["sentinel-2-c1-l2a"], "ids": [
        "S2A_T30SWG_20261117T110058_L2A", "S2A_T30SWG_20261117T105237_L2A"]}).encode(),
    headers={"Content-Type": "application/json"}))["features"]]
gen = sorted(items, key=lambda f: f["properties"]["s2:generation_time"])
early_id, late_id = gen[0]["id"], gen[1]["id"]
out["split_granules"] = [{k: f["properties"][k] for k in ("s2:generation_time", "s2:datatake_id", "s2:processing_baseline", "created")} | {"id": f["id"]} for f in gen]

for case, hidden, second_today in (("A", late_id, date(2026, 11, 18)), ("B", early_id, date(2026, 11, 18)),
                                   ("C", late_id, date(2026, 11, 28))):
    o = ROOT / case
    run(o, date(2026, 11, 17), date(2026, 11, 17), date(2026, 11, 17), wrapper(hide={hidden}))
    first, d1 = rec(o, "2026-11-17", "R051"), dec(o, "2026-11-17", "R051")
    run(o, second_today, second_today, second_today, wrapper())
    second, d2 = rec(o, "2026-11-17", "R051"), dec(o, "2026-11-17", "R051")
    out[case] = {"hidden_first": hidden, "second_run_today": second_today.isoformat(),
                 "first": {k: first[k] for k in ("scene_ids", "complete", "domain_coverage", "domain_valid_fraction", "input_key")},
                 "second": {k: second[k] for k in ("scene_ids", "complete", "domain_coverage", "domain_valid_fraction", "input_key")},
                 "decision_first": d1 and d1["scene_ids"], "decision_second": d2 and d2["scene_ids"],
                 "decision_matches_record": d2 is not None and d2["scene_ids"] == second["scene_ids"]
                     and d2["domain_valid_fraction"] == second["domain_valid_fraction"]}
    print(case, json.dumps(out[case], indent=1), flush=True)

# D newer baseline
o = ROOT / "D"
run(o, date(2026, 11, 10), date(2026, 11, 10), date(2026, 11, 10), wrapper())
base = rec(o, "2026-11-10", "R094")
svf = next(i for i in fetch_json(__import__("urllib.request").request.Request(
    "https://earth-search.aws.element84.com/v1/search",
    data=json.dumps({"collections": ["sentinel-2-c1-l2a"], "ids": [s for s in base["scene_ids"] if "T30SVF" in s]}).encode(),
    headers={"Content-Type": "application/json"}))["features"])
new = copy.deepcopy(svf)
p = new["properties"]
new["id"] = svf["id"].replace("_L2A", "_N0514_L2A")
p["s2:processing_baseline"] = "05.14"
p["s2:product_uri"] = p["s2:product_uri"].replace("_N0513_", "_N0514_")
p["s2:datatake_id"] = p["s2:datatake_id"].rsplit("_N", 1)[0] + "_N05.14"
p["s2:generation_time"] = "2026-11-14T09:00:00.000000Z"
mt0 = os.path.getmtime(o / "s2/2026-11-10/R094/reflectance.tif")
run(o, date(2026, 11, 15), date(2026, 11, 15), date(2026, 11, 15), wrapper(extra=[new]))
after = rec(o, "2026-11-10", "R094")
out["D"] = {"svf_original": svf["id"], "svf_synthetic": new["id"],
            "before": {k: base[k] for k in ("scene_ids", "processing_baselines", "input_key", "complete", "domain_valid_fraction")},
            "after": {k: after[k] for k in ("scene_ids", "processing_baselines", "input_key", "complete", "domain_valid_fraction")},
            "rasters_rewritten": os.path.getmtime(o / "s2/2026-11-10/R094/reflectance.tif") != mt0,
            "decision_scene_ids": dec(o, "2026-11-10", "R094")["scene_ids"]}
print("D", json.dumps(out["D"], indent=1), flush=True)

# E unchanged rerun of A's state (both granules live): nothing rewritten
o = ROOT / "A"
files = [o / "s2/2026-11-17/R051/" / n for n in ("record.json", "reflectance.tif", "classes.tif")] + [o / "cat/s2/decisions/2026-11-17_R051.json"]
before = {str(f.name): (os.path.getmtime(f), hashlib.sha256(f.read_bytes()).hexdigest()) for f in files}
run(o, date(2026, 11, 19), date(2026, 11, 19), date(2026, 11, 19), wrapper())
after = {str(f.name): (os.path.getmtime(f), hashlib.sha256(f.read_bytes()).hexdigest()) for f in files}
out["E"] = {"unchanged": before == after, "files": list(before)}
print("E", out["E"], flush=True)
json.dump(out, open("late_granule.json", "w"), indent=1)
