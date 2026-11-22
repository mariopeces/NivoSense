# G-Code, T1.1 Sentinel-2 ingest, round 1

**Verdict: fail** (2 major, 4 minor). PR #14, `plan/t11-s2-ingest` @ cc705a2. Not judged here: catalogue output (pending T0.3), CI (pending T0.6), final domain (T2.1). Every run below used `data/basins.geojson`.

## Accept lines

| Accept line | Result | My evidence |
|---|---|---|
| 2026-10-01..2026-11-21 listed dates match an independent STAC query; 2026-11-10 in, 2026-11-05 out | **pass** | `gauntlet_stac.py` is my own code. It searches by bbox with pystac-client, groups by `s2:datatake_id`, tests footprints with shapely in UTM, reads SCL through boundless windows onto a 60 m-anchored 20 m grid, and uses no `eo:cloud_cover`. It finds 30 acquisitions, and all 30 match the builder's records on keys, tiles, scene ids, coverage and valid fraction (to 1e-4) and on `listed` (`gauntlet_diff.txt`). The same 11 dates are listed. 2026-11-10 R094 is in (valid 0.837). That pass's max tile `eo:cloud_cover` is 41.4, so a tile filter at < 40 would have dropped it. 2026-11-05 R051 is out (coverage 0.0943, valid 0.0706). |
| Each date's coverage and valid fraction recorded | **pass** | Present in every `record.json`; my values are identical. |

**Builder's reading of "2026-11-05 out for no coverage":** I accept it. 2026-11-05 has only an R051 pass, which reaches the domain through 30SWG alone, at 9.4% coverage. D1 lists a date when "the massif is at least 30% covered and valid". Valid-pixels / all-domain-pixels ≥ 0.30 is that rule exactly, because a valid pixel is also a covered one. The card's "no coverage" means no coverage of the massif, and the 30% rule is the right way to make that precise.

## Rubric checks

- Tests: 16/16 pass locally (`pytest tests/s2`). Ruff check and format are clean with T0.6's `pyproject.toml`, and `mypy pipelines/s2` is clean (project config). No new dependencies: numpy and rasterio are in T0.6's lock. No `except`, no secrets, no personal data.
- Scale/offset from `raster:bands`: checked on real pixels. For 2021-12-09 R094 (sensed before baseline 04.00, now N05.00 in c1) and 2026-11-10 R094 (N05.13), 200 random domain pixels match `DN*scale+offset` from each item's `raster:bands` 200/200. Ignoring the offset would be off by 0.1 (`gauntlet_offset.txt`). Every c1 item I sampled (2020, 2021, 2024, 2026) carries offset -0.1, so a date-based "no offset before 2022-01-25" rule would have been wrong here.
- Mosaics, from my own renders (`ql_*.png`; left: red/green/green, middle: swir16/red/green, right: SCL): I see no tile seams, no misregistration and no empty tiles on 2026-11-10 R094, 2026-02-16 R094 or 2021-12-09 R094. 2026-11-17 R051 merges its two split granules cleanly. 2026-02-13 R051 has a seam (finding 1).
- Completeness, simulated on real Earth Search pages (`gauntlet_completeness.py`; no date in 2025-09..2026-09 is missing a tile for this domain, `gauntlet_scan_2025_26.txt`). I withheld 30SVG from 2026-11-10 R094 and got `complete=False, missing=['30SVG']`. A run two days later, on a later date range, rebuilt the date to 4 tiles, `complete=True`, valid 0.837. On the 2026-11-17 split datatake, withholding either 30SWG granule leaves the record `complete=True`: coverage is 0.0354 instead of 0.1014 when the large granule is missing. The next daily run never revisits that record (finding 5).
- Deliberate breaks (`gauntlet_mutations.txt`, 10 of my own). 7 are caught: listing from coverage instead of valid, grouping that ignores orbit, keeping every baseline, keeping only the newest granule, `complete` always True, counting SCL 2 as invalid, and keeping nodata 10 m blocks. **3 survive** (finding 2).

## Findings

1. **Major: two satellites on one orbit and day are mixed into one mosaic.** Where: `pipelines/s2/stac.py:82-105` (`_latest_baseline`, `group_acquisitions`) and `mosaic.py:86-88`. Dates: 2026-02-03, 02-06, 02-13, 02-16, 02-23 and 08-29. On those days S2A and S2B both pass the same relative orbit, minutes apart, as two datatakes (for example GS2A_20260213T105211 and GS2B_20260213T105139). `_latest_baseline` treats them as the split granules of one datatake and keeps both. The mosaic then fills pixels first-with-data across the two acquisitions, on the docstring's assumption that "tiles of one datatake hold the same values", which does not hold across datatakes.
   - How I saw it (2026-02-13 R051, 30SWG; `gauntlet_mix_20260213.txt`): the two datatakes disagree on SCL in 469,083 of the 1,360,375 pixels they share (34%). The builder's mosaic is S2B plus a 22,447-pixel strip from S2A along the swath edge. `zoom_20260213_R051_swathedge.png` shows the seam line and a different cloud field in the strip.
   - The record's numbers belong to neither acquisition. The mosaic covers 0.0958 with valid 0.0193; S2A alone is 0.0947 / 0.0193 and S2B alone is 0.0958 / 0.0191.
   - These dates fall in the D1 backfill range (from 2025-10-01).
   - To pass: within (date, orbit), keep split granules together only when they share `s2:datatake_id`. Then either record each datatake separately or pick one by a stated rule (for example the highest domain valid fraction). Add a test with two datatakes on the same day.
2. **Major: tests do not pin the Accept rule or two other card behaviours.** Where: `tests/s2/test_s2.py`. Three deliberate breaks pass all 16 tests:
   - `MIN_LISTED_VALID_FRACTION` changed from 0.30 to 0.05. That change would list 2026-11-05 (valid 0.0706) and break the Accept line. The tests only use valid fractions of 0.0 and 1.0.
   - Scale/offset taken from `acquisition.items[0]` for every tile. The card says "from each asset's raster:bands"; the mosaic test gives both tiles the same offset.
   - The footprint filter removed from `ingest.run`. On real data, R051 would then expect 30SVF and 30SWF as well. The test checks `Domain.touches`, not that `run` applies it.
   - To pass: add tests that fail on each of these. For the threshold, a record just above and one just below 0.30, or 11-05-like and 11-10-like fixtures. For scale/offset, two tiles with different offsets. For the filter, a `run` whose search returns a non-touching granule, and an assertion on tiles and expected tiles.
3. **Minor: the docstring says tiles of one datatake hold the same values where they overlap; they do not.** Where: `mosaic.py:87-88` and the PR text. On 2026-11-10 R094, in 200x200 px samples of each tile overlap (`gauntlet_overlap_20261110.txt`), 0-2% of swir16 DNs are identical, with a median difference of 12-41 DN (0.001-0.004 reflectance). SCL agrees on 54-100% of pixels; 30SVG/30SWG agrees on only 53.8%. Sen2Cor runs per tile. No seam is visible at 80 m and the effect on NDSI is small, but the stated reason for first-in-name-order is wrong. To pass: correct the comment and state the deterministic tie rule as the reason.
4. **Minor: an incomplete record can be `listed: true`.** 2026-11-10 R094 with 30SVG withheld gives `complete=False, listed=True` (valid 0.3561). Downstream code (T1.2, the catalogue) could publish a partial mosaic. To pass: document that `listed` implies nothing about completeness, or make `listed` require `complete` (T1.2/T0.3 decision).
5. **Minor (disclosed in the PR's Found, not done): a late split granule for a tile already present is never picked up by the daily run.** 2026-11-17 R051 without its large granule is recorded `complete=True` at coverage 0.0354, and a run two days later does not revisit it. This relies on T1.6's 5-day re-run. To pass: none for this card; track it in T1.6.
6. **Minor: c1 on Earth Search returns no items for this bbox on 2022-01-20..30 or 2022-06-01..10, and none in 2017-07.** This is a source gap, not a code fault. Note it for T1.7's calibration seasons.

Scripts and outputs are in this folder. Builder outputs were regenerated by me with `python -m pipelines.s2.ingest` from the PR code.

```json
{
  "gauntlet": "G-Code",
  "task": "T1.1",
  "round": 1,
  "verdict": "fail",
  "findings": [
    {
      "severity": "major",
      "where": "pipelines/s2/stac.py:82-105, pipelines/s2/mosaic.py:86-88; dates 2026-02-03, 02-06, 02-13, 02-16, 02-23, 08-29",
      "what": "S2A and S2B datatakes on the same relative orbit and day are treated as split granules of one datatake and mixed pixel by pixel in one mosaic",
      "observed": "2026-02-13 R051 30SWG: the two datatakes disagree on SCL in 469,083 of 1,360,375 shared pixels; the mosaic is S2B plus a 22,447 px S2A strip at the swath edge, with a visible seam (zoom_20260213_R051_swathedge.png); the record (0.0958/0.0193) matches neither acquisition",
      "to_pass": "group split granules by s2:datatake_id; record each datatake separately or pick one by a stated rule; test with two datatakes on one day"
    },
    {
      "severity": "major",
      "where": "tests/s2/test_s2.py",
      "what": "Tests do not pin the 30% listing rule (Accept: 2026-11-05 out), per-item scale/offset, or that run() applies the footprint filter",
      "observed": "deliberate breaks MIN_LISTED_VALID_FRACTION=0.05, scale_offset(acquisition.items[0]) for all tiles, and footprint filter removed from ingest.run all pass 16/16 tests (gauntlet_mutations.txt)",
      "to_pass": "tests that fail on each break: threshold straddled near 0.30, two tiles with different offsets, run() with a non-touching granule checking tiles and expected tiles"
    },
    {
      "severity": "minor",
      "where": "pipelines/s2/mosaic.py:87-88; 2026-11-10 R094",
      "what": "Docstring claims tiles of one datatake hold the same values in overlaps; they do not (Sen2Cor runs per tile)",
      "observed": "overlap samples: 0-2% swir16 DN identical, median |dDN| 12-41, SCL agreement 53.8-100% (gauntlet_overlap_20261110.txt); no seam visible at 80 m",
      "to_pass": "correct the comment; state the deterministic tie rule"
    },
    {
      "severity": "minor",
      "where": "pipelines/s2/ingest.py:102-108",
      "what": "An incomplete record can be listed=true",
      "observed": "2026-11-10 R094 with 30SVG withheld: complete=False, listed=True, valid 0.3561",
      "to_pass": "document that listed implies nothing about completeness, or require complete for listed"
    },
    {
      "severity": "minor",
      "where": "pipelines/s2/ingest.py:55-62, 119-125; 2026-11-17 R051",
      "what": "A late split granule for a tile already present is never revisited by the daily run (disclosed in Found, not done)",
      "observed": "large 30SWG granule withheld: complete=True, coverage 0.0354 instead of 0.1014; a run 2 days later does not revisit the date",
      "to_pass": "none for this card; covered by T1.6's 5-day re-run"
    }
  ],
  "followups": [
    "c1 on Earth Search returns no items over the domain bbox for 2022-01-20..30, 2022-06-01..10 and 2017-07; check coverage before T1.7 calibration seasons",
    "rasterio 1.4.4 + numpy 2.5 DeprecationWarning from source.read (as noted by the builder)"
  ]
}
```
