"""Deliberate breaks of PR #14 @ dafc7f3 (pipelines/s2), each run against tests/s2.
Usage: python mutations.py <pr checkout> <scratch dir>. Each mutation is one exact string
replacement in a fresh copy; the copy's tests/s2 is run with pytest."""
import shutil, subprocess, sys
from pathlib import Path

PR, SCRATCH = Path(sys.argv[1]), Path(sys.argv[2])
I, S, M = "pipelines/s2/ingest.py", "pipelines/s2/stac.py", "pipelines/s2/mosaic.py"
MUTATIONS = [
    ("BASELINE unmutated (must pass)", I, "MIN_LISTED_VALID_FRACTION = 0.30", "MIN_LISTED_VALID_FRACTION = 0.30"),
    # round-1 survivors
    ("R1a listing threshold 0.30 -> 0.05", I, "MIN_LISTED_VALID_FRACTION = 0.30", "MIN_LISTED_VALID_FRACTION = 0.05"),
    ("R1b scale/offset of items[0] for every granule", M, "*scale_offset(item, asset)", "*scale_offset(acquisition.items[0], asset)"),
    ("R1c footprint filter removed from run()", I, 'if domain.touches(item["geometry"])', ""),
    # round-1 major, reintroduced
    ("G1 datatake ignored in grouping (blend platforms)", S, "granules[(day, orbit_of(item), datatake_of(item), tile_of(item))]", "granules[(day, orbit_of(item), '', tile_of(item))]"),
    ("G2 datatake = raw id (baseline suffix kept)", S, 'return _BASELINE_SUFFIX.sub("", item["properties"]["s2:datatake_id"])', 'return item["properties"]["s2:datatake_id"]'),
    ("G3 murkiest datatake kept", I, "if best is None or rank > best[0]:", "if best is None or rank < best[0]:"),
    ("G4 rank by coverage before valid", I, "rank = (valid, coverage, acquisition.datatake)", "rank = (coverage, valid, acquisition.datatake)"),
    ("G5 first datatake kept, no ranking", I, "if best is None or rank > best[0]:", "if best is None:"),
    ("G6 missing tiles from union of datatakes", I, "missing = sorted(expected - set(chosen.tiles))", "missing = sorted(expected - set().union(*(a.tiles for a in candidates)))"),
    ("G7 chosen datatake listed in alternatives", I, "            if other is not chosen\n", ""),
    ("G8 alternatives get chosen valid fraction", I, '"domain_valid_fraction": round(other_valid, 4),', '"domain_valid_fraction": round(valid, 4),'),
    # reprocessing / input key
    ("K1 input key from chosen datatake only", I, "input_key=input_key(candidates),", "input_key=input_key([chosen]),"),
    ("K2 is_current ignores input key", I, 'return stored.get("input_key") == input_key(candidates) and stored["expected_tiles"] == sorted(expected)', 'return stored["expected_tiles"] == sorted(expected)'),
    ("K3 is_current ignores expected tiles", I, 'return stored.get("input_key") == input_key(candidates) and stored["expected_tiles"] == sorted(expected)', 'return stored.get("input_key") == input_key(candidates)'),
    ("K4 input key ignores granule ids", I, '(item["id"], item["properties"]["s2:processing_baseline"])', '(item["properties"]["s2:processing_baseline"],)'),
    ("K5 reprocess window 0 days", I, "REPROCESS_DAYS = 10", "REPROCESS_DAYS = 0"),
    ("K6 reprocess window 3 days", I, "REPROCESS_DAYS = 10", "REPROCESS_DAYS = 3"),
    # listing / decisions
    ("L1 listed ignores complete", I, "return complete and bool(valid_fraction >= MIN_LISTED_VALID_FRACTION)", "return bool(valid_fraction >= MIN_LISTED_VALID_FRACTION)"),
    ("L2 decision not rewritten on rebuild", I, "(rebuilt or not decision_path(catalogue_root, day, orbit).exists())", "(not decision_path(catalogue_root, day, orbit).exists())"),
    ("L3 decision code_version ignored", I, '"code_version": version,', '"code_version": "unknown",'),
    ("L4 decision listed always False", I, '"listed": record["listed"],', '"listed": False,'),
    # carried over
    ("C1 SCL 2 counted not valid", M, "SCL_NOT_VALID = (0, 1, 3, 8, 9, 10)", "SCL_NOT_VALID = (0, 1, 2, 3, 8, 9, 10)"),
    ("C2 keep every baseline", S, "return [item for item in granules if _baseline(item) == newest]", "return granules"),
]
caught = 0
for name, rel, old, new in MUTATIONS:
    work = SCRATCH / "m"
    shutil.rmtree(work, ignore_errors=True)
    for part in ("pipelines", "tests"):
        shutil.copytree(PR / part, work / part, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(PR / "pyproject.toml", work / "pyproject.toml")
    (work / "data").mkdir()
    shutil.copy(PR / "data" / "basins.geojson", work / "data" / "basins.geojson")
    path = work / rel
    text = path.read_text(encoding="utf-8")
    assert text.count(old) >= 1, (name, old)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "pytest", "tests/s2", "-q", "-p", "no:cacheprovider", "-W", "ignore",
                             f"--basetemp={SCRATCH / 'mt'}"], cwd=work, capture_output=True, text=True)
    last = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr[-200:]
    failed = [l.split(" ")[1] for l in result.stdout.splitlines() if l.startswith("FAILED")]
    ok = result.returncode != 0
    caught += ok
    print(f"{'caught  ' if ok else 'SURVIVED'} {name}: {last}{' ' + ', '.join(f.split('::')[-1] for f in failed) if failed else ''}", flush=True)
print(f"{caught}/{len(MUTATIONS) - 1} mutations caught (baseline row excluded; it must read 22 passed)")
