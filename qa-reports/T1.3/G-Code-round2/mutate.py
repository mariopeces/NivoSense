"""Mutation check for T1.3 round 2 (PR #22 head 25102f2): the round-1 reviewer's mutations
(qa-reports/T1.3/G-Code-round1/mutate.py, strings updated where the code moved) plus round-2
ones on the datatake match and the new flag. One break at a time on a detached checkout of the
PR, run tests/rgb_l1c, restore with git, record caught/survived.

    python mutate.py <checkout> <python> > mutations.jsonl
"""

import json
import subprocess
import sys
from pathlib import Path

R = "pipelines/rgb_l1c/render.py"
S = "pipelines/rgb_l1c/source.py"
RUN = "pipelines/rgb_l1c/run.py"
Q = "pipelines/rgb_l1c/qa.py"

ROUND1 = [
    ("stretch white to 1.0", R, "WHITE = (1.61, 1.43, 1.45)", "WHITE = (1.0, 1.0, 1.0)"),
    ("stretch white to TCI 0.4", R, "WHITE = (1.61, 1.43, 1.45)", "WHITE = (0.4, 0.4, 0.4)"),
    ("stretch black to 0", R, "BLACK = (0.023, 0.040, 0.065)", "BLACK = (0.0, 0.0, 0.0)"),
    ("stretch gamma constant to 1", R, "GAMMA = 2.2", "GAMMA = 1.0"),
    ("stretch bands swapped in render", R, "BLACK[i], WHITE[i]", "BLACK[2 - i], WHITE[2 - i]"),
    ("stretch scale 254 -> 255", R, "scaled) * 254", "scaled) * 255"),
    ("grid_10m: width not multiplied", R, "grid.width * factor, grid.height * factor", "grid.width, grid.height * factor"),
    ("grid_10m: origin shifted half pixel", R, "Grid(grid.crs, grid.left, grid.top,", "Grid(grid.crs, grid.left + 5, grid.top,"),
    ("blocks: no swapaxes", Q, ".swapaxes(1, 2).reshape(rows, cols, factor * factor)", ".reshape(rows, cols, factor * factor)"),
    ("mosaic: last tile wins", R, "take = ~filled & np.stack", "take = np.stack"),
    ("mosaic: any band instead of all", R, "for band in bands]).all(axis=0)", "for band in bands]).any(axis=0)"),
    ("missing L1C: no warning logged", RUN, "log.warning(\n            \"%s %s: no L1C granule", "log.info(\n            \"%s %s: no L1C granule"),
    ("missing tiles: no warning logged", RUN, 'log.warning("%s %s: L1C lacks tiles', 'log.debug("%s %s: L1C lacks tiles'),
    ("missing L1C: status renamed", RUN, '"status": "l1c_missing"}', '"status": "skipped"}'),
    ("CLI default source cdse", RUN, "choices=SOURCES,\n        default=AWS,", "choices=SOURCES,\n        default=CDSE,"),
    ("run() default source cdse", RUN, "storage: Storage, source: str = AWS)", 'storage: Storage, source: str = "cdse")'),
    ("aws: signed requests", S, '{**_COMMON, "AWS_NO_SIGN_REQUEST": "YES", "AWS_REGION": _AWS_REGION}', '{**_COMMON, "AWS_NO_SIGN_REQUEST": "NO", "AWS_REGION": _AWS_REGION}'),
    ("aws: requester pays on by default", S, '{**_COMMON, "AWS_NO_SIGN_REQUEST": "YES", "AWS_REGION": _AWS_REGION}', '{**_COMMON, "AWS_NO_SIGN_REQUEST": "YES", "AWS_REGION": _AWS_REGION, "AWS_REQUEST_PAYER": "requester"}'),
    ("allowed extensions .tif only", S, '"CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".jp2"', '"CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif"'),
    ("allowed extensions any", S, '"CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".jp2"', '"CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ""'),
    ("cdse: credentials not required", S, "if not key or not secret:", "if False:"),
    ("saturation flag threshold >= -> >", RUN, ") >= MAX_SNOW_SATURATED:", ") > MAX_SNOW_SATURATED:"),
    ("saturation flag threshold 10%", RUN, "MAX_SNOW_SATURATED = 0.01", "MAX_SNOW_SATURATED = 0.1"),
    ("misaligned flag threshold 40 m", Q, "ALIGNED_M = 20.0", "ALIGNED_M = 40.0"),
    ("saturation counts 254", Q, "SATURATED = 255", "SATURATED = 254"),
    ("LIS NDSI 0.0", Q, "NDSI_SNOW = 0.4", "NDSI_SNOW = 0.0"),
    ("best orbit: smallest valid fraction", RUN, '> current["domain_valid_fraction"]', '< current["domain_valid_fraction"]'),
    ("unlisted records included", RUN, 'if not record["listed"] or not start', "if not start"),
]

ROUND2 = [
    ("datatake: back to first group of the day", S, "if a.day == day and a.datatake == datatake)", "if a.day == day)"),
    ("datatake: first group of the record's orbit", S,
     "if a.day == day and a.datatake == datatake)",
     "if a.day == day and a.orbit == next(b.orbit for b in group_acquisitions(items) if b.datatake == datatake))"),
    ("datatake: same satellite prefix only", S, "a.datatake == datatake)", "a.datatake[:4] == datatake[:4])"),
    ("datatake: same timestamp day only", S, "a.datatake == datatake)", "a.datatake.split('_')[1][:8] == datatake.split('_')[1][:8])"),
    ("datatake: last matching group", S,
     "return next((a for a in group_acquisitions(items) if a.day == day and a.datatake == datatake), None)",
     "return next((a for a in reversed(group_acquisitions(items)) if a.day == day), None)"),
    ("process passes orbit not datatake", RUN, 'find_acquisition(hull, day, record["datatake"], domain.touches)', 'find_acquisition(hull, day, record["orbit"], domain.touches)'),
    ("alignment_unchecked never raised", RUN, 'if not scores.get("shift_l2a_green_chips"):', "if False:"),
    ("alignment_unchecked: chips<1 reads as aligned (old rule)", RUN,
     'if not scores.get("shift_l2a_green_chips"):\n        # No chip was clear and textured enough to correlate (a cloudy date): not checked,\n        # which must not read as aligned.\n        flags.append("alignment_unchecked")\n    elif scores["shift_l2a_green_median_m"] >= qa.ALIGNED_M:',
     'if scores.get("shift_l2a_green_median_m", 0.0) >= qa.ALIGNED_M:'),
    ("missing-L1C warning drops the datatake", RUN, '"%s %s: no L1C granule of datatake %s on Earth Search; no RGB for this date",\n            record["date"],\n            orbit,\n            record["datatake"],',
     '"%s %s: no L1C granule on Earth Search; no RGB for this date",\n            record["date"],\n            orbit,'),
    ("missing tiles: computed backwards", RUN, 'sorted(set(record["tiles"]) - set(acquisition.tiles))', 'sorted(set(acquisition.tiles) - set(record["tiles"]))'),
    ("L1C collection is L2A", S, 'COLLECTION = "sentinel-2-l1c"', 'COLLECTION = "sentinel-2-l2a"'),
    ("published value_range 0..255", RUN, '"value_range": [[1, 255]] * 3', '"value_range": [[0, 255]] * 3'),
    ("display alpha ignores one band", RUN, "np.where((rgb != NODATA).all(axis=0), 255, 0)", "np.where((rgb != NODATA).any(axis=0), 255, 0)"),
    ("stretch: missing reflectance not marked nodata", R, "out = (1 + np.rint(np.where(missing, 0, scaled) * 254)).astype(\"uint8\")", "out = (1 + np.rint(np.where(missing, 0, scaled) * 254)).astype(\"uint8\")\n    missing = missing & False"),
]


def main() -> None:
    root, python = Path(sys.argv[1]), sys.argv[2]
    for group, mutations in (("round1", ROUND1), ("round2", ROUND2)):
        for name, path, old, new in mutations:
            target = root / path
            text = target.read_text(encoding="utf-8")
            if text.count(old) != 1:
                print(json.dumps({"set": group, "mutation": name, "result": "not applied", "matches": text.count(old)}), flush=True)
                continue
            target.write_text(text.replace(old, new), encoding="utf-8")
            try:
                run = subprocess.run(
                    [python, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "tests/rgb_l1c"],
                    cwd=root, capture_output=True, text=True, timeout=600,
                )
                last = run.stdout.strip().splitlines()[-1] if run.stdout.strip() else run.stderr[-200:]
                result = "caught" if run.returncode != 0 else "SURVIVED"
                print(json.dumps({"set": group, "mutation": name, "file": path, "result": result, "pytest": last}), flush=True)
            finally:
                subprocess.run(["git", "checkout", "--", path], cwd=root, check=True)


if __name__ == "__main__":
    main()
