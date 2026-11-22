## G-Data gauntlet, T1.1 Sentinel-2 ingest, round 2: **pass** (0 blocker, 0 major, 1 minor)

Reviewed PR #14 at `dafc7f3` (branch `plan/t11-s2-ingest`; the head has not moved). I judged T1.1's own diff, `a76529b..dafc7f3`. Builder evidence is at `8a978f8`. Domain: `data/basins.geojson` (2,147,071 px at 20 m). Earth Search was queried live on 2026-11-22. `qa/check_catalog` and `qa/render_thumbs` are on T0.3/T0.4 branches that are not merged, so I used my own renderer.

### Round-1 major: a late split-datatake granule now reopens a complete date

I replayed arrival orders with the PR's `ingest.run`. It ran against **live Earth Search and real rasters**, through a fetch wrapper that hides or adds items (`late_granule.py`, `late_granule.json`). The two 30SWG granules of 2026-11-17 R051 share datatake `GS2A_20261117T105241_059565`. They were generated at 15:48 (`…105237`) and 16:55 (`…110058`) and listed at 17:03 and 18:07.

| Case | First run | Second run | Result |
|---|---|---|---|
| A: later granule hidden | 11-17 only, sees `105237`: complete, cov 0.1014, valid 0.0009 | normal daily run, start = end = today = 11-18 | record and decision rebuilt with both granules. **Pass.** |
| B: earlier granule hidden | sees `110058` only: complete, **cov 0.0354**, valid 0.0 | daily run 11-18 | reopened: cov 0.1014, valid 0.0009, both ids in the record and the decision. **Pass.** This is the order that would have lost data under round 1. |
| C: late granule first seen 11 days later | as A | daily run 11-28 | not reopened. This is by design: `REPROCESS_DAYS` = 10, and README section 5 asks for 5. |
| D: newer baseline | 2026-11-10 R094 built at N0513 | a copy of the 30SVF item at baseline 05.14 (new id, `N0514` product name, `N05.14` datatake suffix, later generation) appears; daily run 11-15 | the date was reopened. The 05.14 granule replaces the 05.13 one (the other three tiles stay at 05.13), the input key changed, the rasters were rewritten and the decision lists the new id. **Pass.** |
| E: unchanged rerun | case A's state | daily run 11-19, same inputs | `record.json`, `reflectance.tif`, `classes.tif` and the decision are untouched (same mtime and bytes). **Pass.** |

### Accept lines and rubric on the new head

| Check | Verdict | Evidence |
|---|---|---|
| Listed dates match an independent query (card window 2026-10-01..11-21, extended to **2025-10-01..2026-11-21**) | **pass** | My own query and computation (`stac_raw.py`, `own_fractions.py`): pystac-client GET with a bbox and no cloud filter, 911 items. The domain test is a shapely intersection. Datatakes are parsed from `s2:product_uri` (not the PR's `s2:datatake_id`). SCL is read through a WarpedVRT onto my own 20 m grid. I ran the PR's `run()` over the same 14 months in monthly chunks. **237/237 passes match on scene ids, tiles, coverage and valid fraction (to 4 decimals), and 242 datatakes. The 5 two-satellite passes (2026-02-03, 02-06, 02-13, 02-16, 02-23) keep the same datatake I would choose, and their alternatives match my numbers. The 85 listed dates are identical.** No incomplete pass, and no tile with two baselines, exists in the range. Table: `compare.md`. |
| 30% domain rule: 2026-11-10 in, 2026-11-05 out | **pass** | 2026-11-10 R094 is listed (valid 0.837). 2026-11-05 has R051 only (cov 0.0943, valid 0.0706) and is out. R051 never reaches 30% of this domain (121/121 R051 passes have cov ≤ 0.105). |
| Coverage and valid fraction recorded per date | **pass** | In every record and decision object. |
| Decision objects explain every unlisted date | **pass** | 237 decisions, one per pass. All validate against T0.4's `s2_decision.schema.json`, and all equal their record on ids, fractions, `complete` and `listed`. All 152 unlisted passes are complete, with valid < 0.30 and valid ≤ coverage, so `qa/freshness._decision` would accept each as an explanation. The freshness monitor searches the region **bbox**. Of the 237 bbox passes in the range, none touches the bbox without touching the domain, so the bbox finds no pass that lacks a decision (`bbox_vs_domain.py`). |
| Listed implies complete | **pass** | `is_listed` requires `complete`, and no incomplete record exists in the 14 months. |
| Two platforms on one orbit and day are never blended | **pass** | The thumbnail of 2026-02-13 R051 shows only the S2B swath (77% NaN, no S2A fill). The thumbnail of 2026-02-16 R094 shows S2B only, with no seam. `pr_ids` matches the single chosen datatake. |
| Idempotency by input key | **pass** | Rebuilding 2026-02-13 R051 and 2026-02-16 R094 into a fresh folder gives identical pixel SHA-256 for `reflectance.tif` and `classes.tif` and an identical `record.json` (`idempotency.json`). Case E shows an unchanged rerun rewrites nothing. |
| Thumbnails: 10 random passes (seed 20261122) plus 2026-11-10, 11-17, 02-13 and 02-16 | **pass** | No stripes, empty tiles or misregistration; NaN is shown as NaN; there are no seams in reflectance. 2026-04-02 R094 has an SCL class step at x = 509,740 m (the 30SVF/30SWF edge; Sen2Cor runs per tile). It lies outside the domain (0 domain pixels there). |
| Units and ranges | **pass** | Reflectance is float32 NaN, about -0.07 to 1.78. The negatives are dark targets under the c1 offset, and values up to about 1.78 occur on snow and cloud. SCL is uint8 0..11. |
| Tests | **pass** | 22/22 in `tests/s2`. Breaks I made: no recheck window → 3 fail; input key without baseline → 1 fail; `is_current` = "record exists" → 3 fail; decision not rewritten on rebuild → 1 fail. One break survives, see minor 1. |

### Findings

**Minor 1: no test covers a granule arriving late for the second datatake of a two-satellite pass.**
- Where: `tests/s2/test_s2.py`. The break is in `pipelines/s2/ingest.py`, `input_key`.
- Observed: hashing only `candidates[:1]` leaves 22/22 tests passing. The code at head hashes every datatake, so the behaviour is right today.
- To pass: a `run()` test on the 2026-02-13 fixture where the second datatake's granule appears on a later run and changes `input_key` and `alternatives`.

### Follow-ups (not blocking)
- Bright snow called cloud by SCL. On 2026-11-10 the crest snowfield is mostly SCL 9, and the date still lists at 0.837. On a snow-covered mid-winter date this could push valid below 0.30 and leave a clear date unlisted. This is the open G-Method follow-up for T1.2's cloud mask.
- A granule first listed more than `REPROCESS_DAYS` = 10 after sensing is never picked up by a daily run (case C). That is acceptable under README section 5. A backfill run over the date still picks it up.
- Run `qa/check_catalog` and `qa/render_thumbs` once T0.3/T0.4 are merged. Publication must produce COGs that declare nodata (open since round 1).
- Rerun the window on the T2.1 domain, because R051 coverage and expected tiles may change.

Artefacts are in this folder (branch `mariopeces/g-t11-gdata-r2`):
- scripts: `stac_raw.py`, `own_fractions.py`, `run_builder_full.py`, `compare.py`, `late_granule.py`, `idempotency.py`, `bbox_vs_domain.py`, `render_thumbs_gdata.py`
- outputs: `compare.md`/`compare.json`, `pr_records_full.json`, `own_fractions.json`, `late_granule.json`/`.log`, `idempotency.json`, `mutations.txt`, `decisions_sample/`, `thumbs/`
- raw query: `raw_items.json.gz`

No live bucket writes were needed; everything ran locally.

```json
{
  "gauntlet": "G-Data",
  "task": "T1.1",
  "round": 2,
  "verdict": "pass",
  "findings": [
    {
      "severity": "minor",
      "where": "tests/s2/test_s2.py; pipelines/s2/ingest.py input_key",
      "what": "No test covers a granule that arrives late for the second datatake of a two-satellite pass",
      "observed": "mutation hashing only candidates[:1] in input_key leaves 22/22 tests passing; head code hashes every datatake, so behaviour is correct today",
      "to_pass": "a run() test on the 2026-02-13 fixture where the second datatake's granule appears on a later run and changes input_key and alternatives"
    }
  ],
  "followups": [
    "SCL calls bright crest snow cloud (2026-11-10 crest mostly SCL 9); a snowy mid-winter clear date could fall under 0.30 valid. Open G-Method follow-up for T1.2's cloud mask",
    "A granule first listed more than REPROCESS_DAYS=10 after sensing is not picked up by a daily run (by design; README section 5 asks for 5)",
    "Run qa/check_catalog and qa/render_thumbs once T0.3/T0.4 merge; publication must produce COGs that declare nodata",
    "Rerun on the T2.1 domain; R051 coverage and expected tiles may change"
  ]
}
```
