"""Rerun PR #14's ingest on dates already built, now with catalogue_root: records must not be
rebuilt (same input key), decisions must be written and valid against T0.4's schema."""
import sys, os
from datetime import date
from pathlib import Path
pr, domain, out, cat = map(Path, sys.argv[1:5])
sys.path.insert(0, str(pr))
from pipelines.s2 import ingest  # noqa: E402
calls = []
real = ingest.process
ingest.process = lambda *a, **k: (calls.append(a[0][0].day), real(*a, **k))[1]
before = {p: p.stat().st_mtime for p in out.rglob("record.json")}
for d in sys.argv[5:]:
    day = date.fromisoformat(d)
    ingest.run(domain, day, day, out, today=day, catalogue_root=cat, version="g-code-r2")
after = {p: p.stat().st_mtime for p in out.rglob("record.json")}
print("records rebuilt:", sorted({str(c) for c in calls}) or "none", "| record.json mtimes changed:", sum(before.get(p) != m for p, m in after.items()))
print("decisions:", len(list((cat / "s2" / "decisions").glob("*.json"))))
