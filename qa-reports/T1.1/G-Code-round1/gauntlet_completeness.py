"""Real Earth Search pages with one granule withheld, then the real pages: completeness and reprocessing."""
import sys, json, shutil
from datetime import date
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from pipelines.s2 import ingest, stac
work = Path(sys.argv[2]); domain = Path(sys.argv[1]) / "data" / "basins.geojson"
def dropping(ids):
    def fetch(req):
        page = stac.fetch_json(req)
        page["features"] = [f for f in page["features"] if f["id"] not in ids]
        return page
    return fetch
def show(tag, recs, d, o):
    r = next((r for r in recs if r["date"] == d and r["orbit"] == o), None)
    if r is None:
        print(tag, d, o, "NOT REVISITED (record complete, date outside the run range)"); return
    print(tag, d, o, "tiles", r["tiles"], "missing", r["missing_tiles"], "complete", r["complete"], "cov", r["domain_coverage"], "valid", r["domain_valid_fraction"], "n_scenes", len(r["scene_ids"]))
for case, d, o, drop in [("missing-tile", date(2026, 11, 10), "R094", {"S2A_T30SVG_20261110T110234_L2A"}),
                         ("split-late", date(2026, 11, 17), "R051", {"S2A_T30SWG_20261117T110058_L2A"}),
                         ("split-late-other", date(2026, 11, 17), "R051", {"S2A_T30SWG_20261117T105237_L2A"})]:
    out = work / case
    shutil.rmtree(out, ignore_errors=True)
    recs = ingest.run(domain, d, d, out, today=d, fetch=dropping(drop))
    show(case + " first run ", recs, d.isoformat(), o)
    later = date.fromordinal(d.toordinal() + 2)
    recs = ingest.run(domain, later, later, out, today=later)
    show(case + " later run ", recs, d.isoformat(), o)
