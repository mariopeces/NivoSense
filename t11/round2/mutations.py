"""Deliberate breaks of pipelines/s2: each must make tests/s2 fail. Run from the repo root."""
import subprocess
import sys
from pathlib import Path

MUTATIONS = [
    ("listing threshold 0.30 -> 0.05 (G-Code)", "pipelines/s2/ingest.py",
     "MIN_LISTED_VALID_FRACTION = 0.30", "MIN_LISTED_VALID_FRACTION = 0.05"),
    ("listed ignores complete (G-Data/G-Code)", "pipelines/s2/ingest.py",
     "return complete and bool(", "return bool("),
    ("scale/offset of items[0] for every tile (G-Code)", "pipelines/s2/mosaic.py",
     "values = to_grid_reflectance(band, *scale_offset(item, asset), factor)",
     "values = to_grid_reflectance(band, *scale_offset(acquisition.items[0], asset), factor)"),
    ("hard-coded offset -0.1 (G-Method)", "pipelines/s2/mosaic.py",
     'return float(bands[0]["scale"]), float(bands[0]["offset"])', "return 0.0001, -0.1"),
    ("offset ignored", "pipelines/s2/mosaic.py",
     ' + np.float32(offset)', ''),
    ("footprint filter removed from run() (G-Data/G-Code/G-Method)", "pipelines/s2/ingest.py",
     'if domain.touches(item["geometry"])', "if True"),
    ("datatakes of one orbit and day merged (G-Code)", "pipelines/s2/stac.py",
     'return _BASELINE_SUFFIX.sub("", item["properties"]["s2:datatake_id"])', 'return ""'),
    ("no reprocessing window (G-Data)", "pipelines/s2/ingest.py",
     "    recent = (today - timedelta(days=REPROCESS_DAYS), today)\n",
     "    return [(start, end)]\n    recent = (today - timedelta(days=REPROCESS_DAYS), today)\n"),
    ("input key ignores baseline", "pipelines/s2/ingest.py",
     '(item["id"], item["properties"]["s2:processing_baseline"])', '(item["id"], "")'),
    ("newest granule only (split datatake dropped)", "pipelines/s2/stac.py",
     "return [item for item in granules if _baseline(item) == newest]",
     'return [max(granules, key=lambda item: item["properties"]["s2:generation_time"])]'),
    ("complete always True", "pipelines/s2/ingest.py", "complete=not missing,", "complete=True,"),
    ("SCL 3 cloud shadow counted valid", "pipelines/s2/mosaic.py",
     "SCL_NOT_VALID = (0, 1, 3, 8, 9, 10)", "SCL_NOT_VALID = (0, 1, 8, 9, 10)"),
    ("SCL 10 cirrus counted valid (G-Method)", "pipelines/s2/mosaic.py",
     "SCL_NOT_VALID = (0, 1, 3, 8, 9, 10)", "SCL_NOT_VALID = (0, 1, 3, 8, 9)"),
    ("cloud filter added to the search", "pipelines/s2/stac.py",
     '"limit": PAGE_LIMIT,', '"limit": PAGE_LIMIT, "query": {"eo:cloud_cover": {"lt": 40}},'),
    ("10 m nodata blocks kept", "pipelines/s2/mosaic.py", "    values[raw == 0] = np.nan\n", ""),
]

survivors = 0
for name, path, old, new in MUTATIONS:
    file = Path(path)
    original = file.read_text(encoding="utf-8")
    if old not in original:
        print(f"SKIP (pattern missing): {name}")
        survivors += 1
        continue
    file.write_text(original.replace(old, new, 1), encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/s2", "-q", "-p", "no:warnings", "-x"],
            capture_output=True, text=True,
        )
    finally:
        file.write_text(original, encoding="utf-8")
    failed = [line.split("::")[1].split(" ")[0] for line in result.stdout.splitlines() if line.startswith("FAILED")]
    caught = result.returncode != 0
    survivors += not caught
    print(f"{'caught  ' if caught else 'SURVIVED'} {name}: {', '.join(failed)}")
print(f"{len(MUTATIONS) - survivors}/{len(MUTATIONS)} caught")
sys.exit(1 if survivors else 0)
