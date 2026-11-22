"""Drive the PR's ingest (dafc7f3, extracted to argv[1]) over one month chunk; today = chunk end so the
reprocessing window stays near the chunk. Output folder and catalogue root per chunk."""
import json, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from pipelines.s2 import ingest
start, end, out = date.fromisoformat(sys.argv[2]), date.fromisoformat(sys.argv[3]), Path(sys.argv[4])
records = ingest.run(Path(sys.argv[1]) / "data/basins.geojson", start, end, out / "s2", today=end,
                     catalogue_root=out / "catalogue", version="dafc7f3e785b1c7422ae4ecf329cb2fdd9e0e1ff")
records = [r for r in records if start.isoformat() <= r["date"] <= end.isoformat()]
json.dump(records, open(out / "records.json", "w"), indent=1)
print(start, end, len(records), "records")
