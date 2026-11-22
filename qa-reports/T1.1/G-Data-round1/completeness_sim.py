"""Drive the builder's ingest.run with the real Earth Search items (raw_items.json), with rasters stubbed,
to exercise grouping, expected tiles, completeness and reprocessing. Run from the builder checkout."""
import sys, json, copy, shutil
from datetime import date
from pathlib import Path
import numpy as np
from pipelines.s2 import ingest
from pipelines.s2.mosaic import Mosaic

Q = Path(sys.argv[1]); out = Path(sys.argv[2]); shutil.rmtree(out, ignore_errors=True)
raw = json.load(open(Q / "raw_items.json"))["sentinel-2-c1-l2a"]
def stub(acq, grid):  # every pixel valid; only the record flags matter here
    shp = (grid.height, grid.width)
    return Mosaic({a: np.zeros(shp, "float32") for a in ("green","red","swir16")}, np.full(shp, 4, "uint8"), np.zeros(shp, "uint8"))
ingest.build_mosaic = stub
ingest.write_rasters = lambda *a: None
def fetcher(items): return lambda req: {"type":"FeatureCollection","features":copy.deepcopy(items),"links":[]}
dom = Path("data/basins.geojson")

# 1. full real window: all records and expected tiles
recs = ingest.run(dom, date(2026,10,1), date(2026,11,21), out/"full", date(2026,11,22), fetcher(raw))
print("full run:", len(recs), "records; incomplete:", [(r["date"], r["orbit"], r["missing_tiles"]) for r in recs if not r["complete"]])
r17 = [r for r in recs if r["date"]=="2026-11-17"]; print("11-17:", [(r["orbit"], r["tiles"], r["scene_ids"], r["complete"]) for r in r17])
print("expected per orbit:", sorted({(r["orbit"], tuple(r["expected_tiles"])) for r in recs}))

# 2. missing tile: 2026-11-20 R094 without 30SWF (as if late), run on 11-21, then the tile arrives, run on 11-22
late = "S2A_T30SWF_20261120T110"
early = [i for i in raw if not i["id"].startswith(late)]
print("dropped:", [i["id"] for i in raw if i["id"].startswith(late)])
o = out/"late"
r1 = [r for r in ingest.run(dom, date(2026,11,20), date(2026,11,21), o, date(2026,11,21), fetcher(early)) if r["date"]=="2026-11-20" and r["orbit"]=="R094"][0]
print("run 11-21:", r1["complete"], r1["missing_tiles"], r1["listed"])
r2 = [r for r in ingest.run(dom, date(2026,11,22), date(2026,11,22), o, date(2026,11,22), fetcher(raw))]
print("run 11-22 (start=end=11-22) returned:", [(r["date"], r["orbit"], r["complete"], r["missing_tiles"]) for r in r2])

# 3. split datatake: drop the 16:55 granule of 30SWG on 11-17 -> still complete (tile present) though coverage halves
o = out/"split"
part = [i for i in raw if i["id"] != "S2A_T30SWG_20261117T110058_L2A"]
r3 = [r for r in ingest.run(dom, date(2026,11,17), date(2026,11,17), o, date(2026,11,17), fetcher(part)) if r["date"]=="2026-11-17"]
print("11-17 with one 30SWG granule only:", [(r["tiles"], r["scene_ids"], r["complete"]) for r in r3])
r4 = [r for r in ingest.run(dom, date(2026,11,17), date(2026,11,17), o, date(2026,11,18), fetcher(raw)) if r["date"]=="2026-11-17"]
print("  after the second granule arrives:", [(r["scene_ids"], r["complete"]) for r in r4])

# 4. same split case, but the next run is a normal daily run (start=end=next day): is 11-17 refreshed?
o = out/"split_daily"
ingest.run(dom, date(2026,11,17), date(2026,11,17), o, date(2026,11,17), fetcher(part))
ingest.run(dom, date(2026,11,18), date(2026,11,18), o, date(2026,11,18), fetcher(raw))
stored = json.loads((o/"2026-11-17"/"R051"/"record.json").read_text())
print("daily run on 11-18 after the late split granule arrived; stored 11-17 scenes:", stored["scene_ids"], "complete", stored["complete"])
