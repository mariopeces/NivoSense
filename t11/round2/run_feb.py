import json
import sys
from datetime import date
from pathlib import Path

from pipelines.s2 import ingest

out, catalogue = Path(sys.argv[1]), Path(sys.argv[2])
# today = end, so the reprocessing window stays inside February and the run touches only these dates.
records = ingest.run(
    Path("data/basins.geojson"), date(2026, 2, 1), date(2026, 2, 24), out, today=date(2026, 2, 24),
    catalogue_root=catalogue,
)
for r in records:
    alts = "; ".join(f"{a['datatake']} cov={a['domain_coverage']:.4f} valid={a['domain_valid_fraction']:.4f}" for a in r["alternatives"])
    print(f"{r['date']} {r['orbit']} {r['datatake']} tiles={','.join(r['tiles'])} complete={r['complete']} "
          f"cov={r['domain_coverage']:.4f} valid={r['domain_valid_fraction']:.4f} listed={r['listed']}"
          + (f" | alternatives: {alts}" if alts else ""))
json.dump(records, open(out / "records.json", "w"), indent=1)
