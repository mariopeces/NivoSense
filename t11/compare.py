"""Join pipelines/s2 records with the independent query; print a markdown table and verdicts."""
import json
import sys
from pathlib import Path

run_dir, indep_path = Path(sys.argv[1]), Path(sys.argv[2])
ours = {(r["date"], r["orbit"]): r for r in (json.loads(p.read_text()) for p in run_dir.glob("*/*/record.json"))}
theirs = {(r["date"], r["orbit"]): r for r in json.loads(indep_path.read_text())}

print("| date | orbit | tiles (ingest) | tiles (indep.) | complete | coverage ingest / indep. pixels / indep. footprint | valid fraction ingest / indep. | listed (>= 0.30) ingest / indep. |")
print("|---|---|---|---|---|---|---|---|")
problems = []
for key in sorted(set(ours) | set(theirs)):
    o, t = ours.get(key), theirs.get(key)
    if o is None or t is None:
        problems.append(f"{key} only in {'independent' if o is None else 'ingest'}")
        print(f"| {key[0]} | {key[1]} | {o and ','.join(o['tiles'])} | {t and ','.join(sorted(set(t['tiles'])))} | | | | |")
        continue
    t_tiles = sorted(set(t["tiles"]))
    t_listed = t["pixel_valid_fraction"] >= 0.30
    if o["tiles"] != t_tiles:
        problems.append(f"{key} tiles differ")
    if abs(o["domain_coverage"] - t["pixel_coverage"]) > 0.005:
        problems.append(f"{key} coverage differs")
    if abs(o["domain_valid_fraction"] - t["pixel_valid_fraction"]) > 0.005:
        problems.append(f"{key} valid fraction differs")
    if o["listed"] != t_listed:
        problems.append(f"{key} listed differs")
    if not o["complete"]:
        problems.append(f"{key} incomplete: missing {o['missing_tiles']}")
    print(
        f"| {key[0]} | {key[1]} | {','.join(o['tiles'])} | {','.join(t_tiles)} | {o['complete']} | "
        f"{o['domain_coverage']:.4f} / {t['pixel_coverage']:.4f} / {t['footprint_coverage']:.4f} | "
        f"{o['domain_valid_fraction']:.4f} / {t['pixel_valid_fraction']:.4f} | "
        f"{'yes' if o['listed'] else 'no'} / {'yes' if t_listed else 'no'} |"
    )
listed_ours = sorted({k[0] for k, r in ours.items() if r["listed"]})
listed_theirs = sorted({k[0] for k, r in theirs.items() if r["pixel_valid_fraction"] >= 0.30})
print()
print(f"acquisitions: ingest {len(ours)}, independent {len(theirs)}")
print(f"listed dates ingest ({len(listed_ours)}): {', '.join(listed_ours)}")
print(f"listed dates independent ({len(listed_theirs)}): {', '.join(listed_theirs)}")
print(f"2026-11-10 listed: {'2026-11-10' in listed_ours}; 2026-11-05 listed: {'2026-11-05' in listed_ours}")
print("problems:", problems or "none")
sys.exit(1 if problems or listed_ours != listed_theirs else 0)
