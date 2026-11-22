## G-Data gauntlet, T1.1 Sentinel-2 ingest, round 1: **fail** (1 major, 3 minor)

Reviewed PR #14 at `cc705a2` (branch `plan/t11-s2-ingest`) and evidence at `f5b5d29`. Domain: `data/basins.geojson` (2,147,071 px at 20 m), the same one the builder used. The catalogue checks (`qa/check_catalog`, `qa/render_thumbs`) wait on T0.3, CI waits on T0.6, and the final domain comes from T2.1. I judged everything else.

### Accept lines

| Accept line | Verdict | My evidence |
|---|---|---|
| 2026-10-01..2026-11-21: listed dates match an independent STAC query; 2026-11-10 in, 2026-11-05 out | **pass** | I wrote my own query and computation and did not use `independent_query.py` or `compare.py`. The query is pystac-client GET with a bbox and no cloud filter (`stac_raw.py`). Domain touch is a shapely intersection. Grouping is by datatake (platform plus sensing start from `s2:product_uri`). Each SCL COG is read through a `WarpedVRT` onto my own 20 m grid, and the mask comes from `geometry_mask` (`own_fractions.py`). Result: **30/30 acquisitions match on scene ids, tiles, coverage and valid fraction (identical to 4 decimals)**, and the same 11 dates are listed. 2026-11-10 R094 is listed (valid 0.837). Its 30SVG tile has `eo:cloud_cover` 41.4, so the old tile-level `< 40` filter would have dropped it. 2026-11-05 is out. |
| Each date's domain coverage and valid fraction recorded | **pass** | `record.json` holds `domain_coverage`, `domain_valid_fraction`, `domain_pixels`, `tiles`, `expected_tiles`, `missing_tiles`, `complete` and `scene_ids`. My reruns of 2026-10-21, 2026-11-10 and 2026-11-17 reproduced the builder's records. |

**"2026-11-05 out for no coverage" read as the 30% rule: I agree.** 2026-11-05 has only an R051 pass (S2C). Its tiles are clear (`eo:cloud_cover` 2.6 to 12.9), but the swath reaches the domain only through 30SWG and covers 9.43% of it (7.06% valid). The date is out because coverage is below D1's 30% threshold, not because cloud kept the valid fraction down. Every R051 pass covers 9.4 to 10.5% of the current domain, so no R051 date can be listed with this domain. The R051 numbers may change once T2.1 delivers the larger domain.

**Cross-source check (CDSE STAC, November):** I found the same datatakes and tile sets as on Earth Search. R094 has no pass on 2026-11-03 or 2026-11-18 in Earth Search `c1`, Earth Search `sentinel-2-l2a` or CDSE. Those datatakes were never acquired, so nothing is missing from the ingest.

### Rubric

- **Scale and offset from `raster:bands`:** pass. Every `c1` item I sampled has `scale 0.0001, offset -0.1`: 2019 (sensed before baseline 04.00, reprocessed as N0500), 2021-12 (N0500), 2022 (05.09 to 05.11), 2023 (05.09) and 2026 (05.13). The DN values confirm the offset is real. Over sea, 30SVF swir16 has p0.1 DN of 1075 (2019, N0500) and 1002 (2026, N0513), which gives about 0 reflectance after the offset. The old `sentinel-2-l2a` collection mixes offset 0 (03.01) and -0.1 for one month, which shows why a baseline rule would be fragile. The code rejects an asset that has no `raster:bands` scale and offset.
- **Mosaics (rendered myself: SWIR16/red/green false colour, green, SCL; 2026-10-21 R051/R094, 2026-11-10 R051/R094, 2026-11-17 R051):**
  - no stripes, no empty tiles and no misregistration;
  - each mosaic matches its first-precedence granule exactly (max abs 0.0);
  - zoomed crops at the 30SVF/30SVG precedence edge show no visible seam in reflectance;
  - snow on the crest on 2026-11-10 and on the western summits on 2026-10-21 shows as expected;
  - the 2026-11-17 split granules leave no gap.
- **Units and ranges:**
  - reflectance is float32 with NaN nodata;
  - minimum about -0.046 over dark targets and water, which is expected with the `c1` offset and is not clipped;
  - maximum about 1.6 on bright cloud and snow, which is normal for L2A;
  - `classes.tif` is uint8 with SCL 0 as nodata.
- **Idempotency:** pass. I reran 2026-11-10 into a fresh folder. The SHA-256 of the pixel arrays of `reflectance.tif` and `classes.tif`, and `record.json`, are identical for R094 and R051.
- **Tests:** 16/16 pass. Deliberate breaks:

  | Break | Result |
  |---|---|
  | offset forced to 0 | caught, 2 tests fail |
  | listing by coverage instead of valid fraction | caught |
  | `complete=True` always | caught |
  | SCL 3 (cloud shadow) counted as valid | caught |
  | latest-generation granule only (split dropped) | caught |
  | domain-touch filter removed from `run()` | **not caught**, see minor 3 |

- **Completeness logic** (I drove the builder's `ingest.run` with the real Earth Search items and stubbed the rasters, `completeness_sim.py`):
  - full window: 30 records, all complete. Expected tiles are R051 {30SWG} and R094 {30SVF, 30SVG, 30SWF, 30SWG}. There is no real date with a missing tile in the range.
  - simulated missing tile (2026-11-20 R094 without 30SWF): the record is marked `complete: false` with `missing_tiles: ["30SWF"]`. A later run on another date picks it up and rebuilds it as complete. Pass.
  - 2026-11-17 split datatake: both 30SWG granules (two datastrips of one datatake) are kept and mosaicked. Pass.
  - **late split granule:** fails, see major 1.

### Findings

**Major 1: a late split-datatake granule never refreshes a date already marked complete on a normal daily run.**
- Where: `pipelines/s2/ingest.py`, `pending_start` and `run`; `pipelines/s2/stac.py`, `expected_tiles`. Date 2026-11-17 R051.
- What is wrong:
  - completeness is checked per tile, and only incomplete records are searched again;
  - on 2026-11-17 the two 30SWG granules were generated 67 minutes apart (15:48 and 16:55 UTC);
  - a run between the two generations sees the tile as present, so it marks the date complete with one granule;
  - the next daily run (start = end = the next day) never searches 2026-11-17 again, so the record stays at one granule for good.
- The PR says the opposite: "a granule that arrives late also refreshes a record that was already complete". That only holds when the later run's own date range happens to include the date.
- Observed: `completeness_sim.py` case 4. Run on 11-17 without `S2A_T30SWG_20261117T110058_L2A`, then run 11-18..11-18 with every item. The stored 11-17 record still lists one scene and `complete: true`.
- In this real case the later granule adds no domain pixels (see minor 2), so nothing was lost this time. If the granules arrive in the other order, the stored record covers about half of 30SWG.
- To pass:
  - every run searches again at least the last `RETRY_DAYS`, complete or not (`is_current` already avoids rebuilding unchanged records), or completeness also covers the granule set of the datatake;
  - add a test built on the real 2026-11-17 items where a daily run picks up the late granule.

**Minor 2: the claim that overlapping tiles hold the same values is false for L2A, and the 11-17 granules are not complementary.**
- Where: `pipelines/s2/mosaic.py`, docstring of `build_mosaic`; PR body ("Tiles of one datatake have the same values where they overlap", "complementary coverage").
- Observed (`overlap_check.py`, `seam_stats.py`):
  - Sen2Cor corrects each tile separately, so swir16 DN values are identical in only 1 to 4% of overlap pixels;
  - on clear land, the median |Δ| is 0.0006 to 0.006 reflectance and the p95 is at most 0.016; SCL agrees on 94.6 to 99.8% of overlap pixels;
  - on 2026-11-17, the newer 30SWG granule (730,300 px in the grid window) lies entirely inside the older one (1,468,707 px), and they hold equal DN on only 0.01% of those pixels;
  - the mosaic gives precedence to the newer, smaller granule.
- Impact: no visible seam. The tile-order choice is acceptable, but the stated reason is wrong.
- To pass: fix the docstring and PR text. State that overlaps differ slightly and that the precedence is deterministic: tile name order, then latest generation.

**Minor 3: no test checks that `run()` applies the domain-touch filter.**
- Where: `tests/s2/test_s2.py`; `ingest.py` line with `if domain.touches(item["geometry"])`.
- Observed: replacing the condition with `if True` leaves 16/16 tests passing. Without the filter, R051's expected tiles would include 30SVF and 30SWF, which do not touch the domain. R051 dates would then be marked incomplete whenever those granules are missing.
- To pass: add an offline `run()` test in which a granule that touches the hull but not the domain does not appear in `expected_tiles`.

**Minor 4: `listed` ignores `complete`.**
- Where: `ingest.py`, the `Record` field `listed`.
- Observed: in the simulated 2026-11-20 R094 case with 30SWF missing, the record is `complete: false` and `listed: true`.
- This is defensible under D1, which only sets the 30% rule, and the record is rebuilt when the missing tile arrives.
- To pass: document that consumers (T0.3, T1.2) must check `complete` before publishing, or make `listed` require `complete`.

### Follow-ups (not blocking)
- Rerun the full window once T2.1 delivers `data/domain.geojson`. R051 coverage and expected tiles may change; R051 may reach 30SWF.
- Run `qa/check_catalog` and `qa/render_thumbs` once T0.3 is merged.
- The intermediate `reflectance.tif` and `classes.tif` are tiled GTiff without overviews, and `classes.tif` declares no nodata. Publication through T0.3 has to produce valid COGs that declare nodata (D2).

Artefacts (my worktree, `qa-reports/T1.1/G-Data-round1/`):
- scripts: `stac_raw.py`, `own_fractions.py`, `overlap_check.py`, `seam_stats.py`, `render_thumbs_gdata.py`, `completeness_sim.py`
- outputs: `own_fractions.json`, `seam_stats.json`, `mosaic_*.png`, `seam_zoom_*.png`
- raw query data: `raw_items.json.gz`, `cdse.json.gz`

```json
{
  "gauntlet": "G-Data",
  "task": "T1.1",
  "round": 1,
  "verdict": "fail",
  "findings": [
    {
      "severity": "major",
      "where": "pipelines/s2/ingest.py pending_start/run; date 2026-11-17 R051 (split datatake, 30SWG granules generated 15:48 and 16:55 UTC)",
      "what": "Completeness is per tile and only incomplete records are searched again, so a split-datatake granule that arrives after a run never refreshes a date already marked complete. The PR claims late granules refresh complete records.",
      "observed": "completeness_sim.py case 4 with the real Earth Search items: ingest 11-17 without S2A_T30SWG_20261117T110058_L2A, then a daily run 11-18..11-18 with all items; the stored 11-17 record keeps 1 scene and complete=true",
      "to_pass": "each run searches again at least the last RETRY_DAYS whether complete or not (is_current prevents needless rebuilds), or completeness covers the datatake's granule set; plus a test with the real 2026-11-17 items"
    },
    {
      "severity": "minor",
      "where": "pipelines/s2/mosaic.py build_mosaic docstring; PR body",
      "what": "States that tiles of one datatake hold the same values where they overlap, and that the 11-17 granules are complementary. Both are false for L2A.",
      "observed": "overlap_check.py / seam_stats.py: swir16 DN equal in 1-4% of overlap pixels; clear-land median |d| 0.0006-0.006, p95 <= 0.016; SCL agreement 94.6-99.8%; the newer 11-17 30SWG granule (730,300 px) lies entirely inside the older one (1,468,707 px), equal DN on 0.01%; no visible seam in rendered crops",
      "to_pass": "correct the docstring and PR text: overlaps differ slightly; precedence is deterministic (tile name, then latest generation)"
    },
    {
      "severity": "minor",
      "where": "tests/s2/test_s2.py; pipelines/s2/ingest.py run() domain.touches filter",
      "what": "No test checks that run() drops granules that do not touch the domain",
      "observed": "replacing the filter with `if True` leaves 16/16 tests passing",
      "to_pass": "an offline run() test where a hull-touching, domain-missing granule is absent from expected_tiles"
    },
    {
      "severity": "minor",
      "where": "pipelines/s2/ingest.py Record.listed",
      "what": "An incomplete date with valid >= 0.30 is marked listed",
      "observed": "completeness_sim.py case 2: 2026-11-20 R094 without 30SWF gives complete=false, listed=true",
      "to_pass": "document that consumers must check complete before publishing, or make listed require complete"
    }
  ],
  "followups": [
    "Rerun the full window on the T2.1 domain; R051 coverage and expected tiles may change",
    "Run qa/check_catalog and qa/render_thumbs once T0.3 is merged",
    "Publication via T0.3 must produce valid COGs that declare nodata; the intermediates are tiled GTiff without overviews and classes.tif declares no nodata",
    "R094 had no pass on 2026-11-03 or 2026-11-18 (absent on Earth Search and CDSE): not acquired, nothing to ingest"
  ]
}
```
