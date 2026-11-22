"""Rebuild passes into a fresh folder with the PR's run() and compare pixel hashes (SHA-256 of the decoded
arrays, so GTiff metadata/timestamps are excluded) and record.json with the full run under argv[2].
today is set past the end of the data so the reprocessing window is empty and only the asked date is built."""
import hashlib, json, shutil, sys
from datetime import date
from pathlib import Path
import rasterio
sys.path.insert(0, sys.argv[1])
from pipelines.s2 import ingest
full, fresh = Path(sys.argv[2]), Path(sys.argv[3])
shutil.rmtree(fresh, ignore_errors=True)
def phash(p):
    with rasterio.open(p) as s: return hashlib.sha256(s.read().tobytes()).hexdigest()
res = []
for d, orb, chunk in [x.split(",") for x in sys.argv[4:]]:
    day = date.fromisoformat(d)
    ingest.run(Path(sys.argv[1]) / "data/basins.geojson", day, day, fresh / d, today=date(2027, 6, 1))
    a, b = full / chunk / "s2" / d / orb, fresh / d / d / orb
    r = {"date": d, "orbit": orb}
    for n in ("reflectance.tif", "classes.tif"):
        r[n] = phash(a / n) == phash(b / n); r[n + "_sha"] = phash(b / n)
    r["record.json"] = json.loads((a / "record.json").read_text()) == json.loads((b / "record.json").read_text())
    print(r, flush=True); res.append(r)
json.dump(res, open("idempotency.json", "w"), indent=1)
