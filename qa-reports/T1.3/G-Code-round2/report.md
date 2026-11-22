## T1.3 G-Code round 2 + narrow G-Method round 2: **G-Code pass, G-Method pass**

**Head judged: `25102f2`, not `9f3f51d`.** The builder pushed `25102f2` during this review. It adds only a test and a recorded Earth Search fixture for the real 2026-02-06 R094 pair. The coordinator told me to judge it as the final head. The diff `9f3f51d..25102f2` (`tests/rgb_l1c/test_rgb_l1c.py` +20 lines, `fixtures/earth_search_l1c_2026-02-06.json`) is included below. Scope: T1.3's own commits only (`c7bc7a4`, `9d3cbb2`, `830e830`, `9f3f51d`, `25102f2`), i.e. `pipelines/rgb_l1c/*`, the `collection` parameter in `pipelines/s2/stac.py`, and `tests/rgb_l1c/*`. I ran everything myself from detached checkouts of the PR. I did not edit the branch and wrote nothing live: this review needed no write to `gs://nivosense-cogs/staging/_scratch/g-t13-r2/`.

Process note: the coordinator reported that python processes were killed at 05:39 and 06:05 UTC. My first Python run started at 06:55 UTC. Every result below has complete output, and every mutation counted as "caught" shows a real pytest failure line (`1 failed, …`), not a killed process.

---

### G-Code (full)

**Tests, lint, types (T0.6 config, `pipelines/requirements-dev.lock` versions: ruff 0.17.6, mypy 1.20.2, pytest 9.2.0, rasterio 1.4.4)**

| Check | Result |
|---|---|
| `ruff check .` at `25102f2` | All checks passed |
| `ruff format --check pipelines/rgb_l1c tests/rgb_l1c` | 8 files already formatted |
| `mypy` (files = pipelines, scripts) | no issues in 44 source files |
| `pytest tests/rgb_l1c` at `25102f2` | 23 passed |
| full `pytest -q` at `9f3f51d` (local, Windows) | 167 passed, 30 subtests passed |
| CI on `25102f2` (run 44995641338) | python and frontend jobs green |

**Mutations** (`mutate.py`, `mutations.jsonl`). I applied each break on its own to a clean checkout of `25102f2`, ran `tests/rgb_l1c`, then restored the file with git.

- **Round-1 reviewer's 28 mutations, re-applied** (strings updated where the code moved): **28/28 caught**. The 8 that survived round 1 all fail now:
  - WHITE=(1,1,1), BLACK=0, GAMMA=1, and BLACK/WHITE applied to the wrong band: caught by `test_render_applies_the_shipped_stretch_per_band`.
  - mosaic `.all` → `.any`: caught by `test_mosaic_takes_a_tile_only_where_all_three_bands_have_data`.
  - missing-L1C warning → info, and missing-tiles warning → debug: caught by the caplog assertions.
  - CLI default `--source cdse`, and `run(source="cdse")`: caught by `test_source_defaults_to_unsigned_aws`.
- **My 14 round-2 mutations: 12 caught, 2 survived.** Both survivors behave the same as the original code on real data:

| Mutation | Result |
|---|---|
| datatake filter dropped (first group of the day) | caught |
| first group of the record's orbit (the round-1 G-Method bug) | caught (the real 02-06 pair test) |
| match on acquisition day only | caught |
| last matching group | caught |
| `process()` passes `record["orbit"]` instead of `record["datatake"]` | caught (`searched == [DATATAKE]`) |
| `alignment_unchecked` never raised / old rule (0 chips reads as aligned) | caught / caught |
| missing-L1C warning no longer names the datatake | caught |
| missing tiles computed backwards (`L1C − L2A`) | caught |
| collection `sentinel-2-l2a` instead of `sentinel-2-l1c` | caught |
| published `value_range` 0..255 | caught |
| stretch no longer marks NaN as nodata | caught |
| match on the satellite prefix only (`GS2B` = `GS2B`) | **survived: equivalent.** One satellite cannot make two datatakes over this domain on one UTC day (adjacent tracks pass on different days), so the prefix match and the full-id match pick the same group on real data. |
| display alpha from `.any` instead of `.all` over bands | **survived: equivalent.** `render()` already sets all three bands to 0 wherever any band is missing, and valid pixels are 1..255, so `.any` and `.all` agree on every array `render()` can return. |

**Round-1 findings, checked against the code**

| Round-1 finding | Status |
|---|---|
| major: missing-L1C logging untested | fixed: caplog asserts one WARNING naming date, orbit, datatake and "no L1C"; the missing-tiles warning is asserted too |
| major: `--source` default untested | fixed: `main()` without `--source` → `"aws"`, `run()` default `"aws"`, unsigned GDAL options |
| major: shipped stretch constants unpinned | fixed: values pinned and checked per band (black → 1, white → 255, mid value → the expected gamma-2.2 level, a different level per band) |
| minor: `.all`/`.any` mosaic rule untested | fixed (test above) |
| minor: unused `fetch` parameter on `process()` | removed |
| minor: 0 chips reads as aligned | fixed: `alignment_unchecked` flag, tested |
| minor: hard-coded ×2 in `calibrate.py` | fixed: factor derived from the grid shapes |
| minor: timing not measured on head | builder re-timed `9f3f51d` on a runner (run 44993030654): 41–114 s per date. Not re-run by me on a runner; my local Windows renders (below) read the JP2 in 23–82 s. |

**Diff `9f3f51d..25102f2`**: one test, `test_two_datatakes_on_one_orbit_take_the_one_the_record_kept`, plus a recorded Earth Search L1C fixture for 2026-02-06. Checked against a live query: Earth Search lists exactly the two datatakes `GS2A_20260206T110621_055504_N05.12` and `GS2B_20260206T110129_046595_N05.12`, and the PR's live pipeline returns the same four `S2B_30SV?/30SW?_20260206_1_L1C` ids the test asserts (`data/2026-02-06_R094.json`). The fixture is real, and the test fails on its own with the orbit-only matcher (run alone with that mutation: `AssertionError: GS2A_20260206T110621_055504 != GS2B_…`).

**Other G-Code rubric lines**
- No secrets: a grep of `pipelines/rgb_l1c`, `tests/rgb_l1c` and the PR body for key, token and private-key patterns finds nothing. Only environment variable names appear.
- No new dependencies: T1.3's commits do not touch `requirements*.in` or `*.lock`.
- No silent `except` and no dead code. Comments state the why (datatake vs orbit; unchecked must not read as aligned). Public functions are typed (mypy and ruff ANN rules pass).

**G-Code verdict: pass.** No blocker or major findings.

---

### G-Method (narrow)

I ran the T1.1 ingest from the PR stack (`dafc7f3` code inside `25102f2`) for 2026-01-12, 2026-02-06, 2026-02-16 and 2026-07-16. Domain: `data/domain.geojson` from `plan/t21-domain` `bad749e`. Each date then went through the PR's own `run.process()` into a local catalogue (`gmethod_render.py`). The only bypass is the `listed` filter, because 02-06 is unlisted. The script captures the rendered array and checks which overpass the RGB came from against T1.1's stored record and SCL.

**1. The RGB comes from the datatake T1.1 keeps** (`data/2026-02-06_R094.json`, `data/2026-02-16_R094.json`, `data/t11_record_*.json`)

| | 2026-02-06 R094 | 2026-02-16 R094 |
|---|---|---|
| T1.1 kept datatake (valid fraction) | `GS2B_20260206T110129_046595` (0.0197) | `GS2B_20260216T110029_046738` (0.8959, **listed**) |
| alternative | GS2A …055504 (0.0162) | GS2A …055647 (0.8944) |
| L1C datatakes on Earth Search that day | GS2A + GS2B (N05.12) | GS2A + GS2B (N05.12) |
| L1C published by `process()` | `S2B_30S{VF,VG,WF,WG}_20260206_1_L1C` → GS2B | `S2B_30S{VF,VG,WF,WG}_20260216_0_L1C` → GS2B |
| datatake of RGB = record's datatake | **yes** | **yes** |
| green r, RGB (10 m→20 m) vs T1.1 L2A green: kept / other L1C | **0.9954** / 0.9498 | **0.9269** / 0.9087 |
| T1.1 SCL cloud pixels bright (>0.25 TOA green) in RGB: kept / other | 0.968 / 0.969 (98% cloud both) | **0.754** / 0.715 |
| QA flags | none (45 chips, median shift 0.06 m) | none (median shift 0.04 m, snow 255 share ≤ 0.03%) |

In both cases GS2B sorts second, so round 1's orbit-only matcher would have taken GS2A. **2026-02-16 R094 is listed** (valid 0.896 with this domain and T1.1 `dafc7f3`). Round 1 found none of the five dual dates listed, but this one would have been published from the wrong overpass, so the fix matters on a real catalogue date. Both radiometric checks put the RGB on the kept pass: the higher green correlation and the better cloud agreement with T1.1's SCL. The source ids prove it directly.

**2. No regression in the stretch** (`data/2026-01-12_R094.json`, `data/2026-07-16_R094.json`, compared with round 1's `G-Method-round1/data/*.json` on `eeac1c6`)

| | 2026-01-12 (full snow, S2C) | 2026-07-16 (summer, S2B) |
|---|---|---|
| L1C datatake = record's | yes (GS2C …007071) | yes (GS2B …048883) |
| snow pixels (10 m) | 5,113,892, same as round 1 | 16,328, same as round 1 |
| snow 8-bit p1/p5/p50/p95/p99, R/G/B | identical to round 1 in every band (e.g. red 60/73/162/231/246) | identical to round 1 in every band |
| all-pixel 8-bit percentiles | identical to round 1 | identical to round 1 |
| snow at 255 (red/green/blue) | 0.20% / 0.34% / 0.30% (< 1%) | 0 / 0 / 0 |
| QA scores vs the builder's head entry (`t13/round2/entries/2026-01-12.json`) | identical to the last digit | — |
| L2A alignment | median 0.05 m, 45/45 chips within 20 m | median 0.02 m, 45/45 chips within 20 m |

The thumbnails (`img/`) show snow texture on the crest on 01-12 and 02-16, nothing blown out, and summer bare ground not crushed.

**G-Method verdict: pass.**

---

### Follow-ups (not blocking)
- My local `pixel_hash` for 2026-01-12 (`5a95ac04…`, Windows, rasterio 1.4.4 / GDAL 3.10.3 wheel) differs from the builder's runner hash (`9fc1636e…`). Bounds, snow-pixel count and every QA score match to the last digit, so the difference is a few pixels from platform decoding or float rounding. That does not matter for prod, which runs only on ubuntu runners. But `publish()` raises `NonDeterministicOutput` if a rerun with the same `input_key` gives a different hash, so idempotency reruns must stay on the same platform. A note for G-Data and T1.5.
- `--source aws-requester-pays|cdse` remain unit-tested only until the H6 credentials exist (already stated in `--help` and the PR body).

```json
{
  "gauntlet": "G-Code",
  "task": "T1.3",
  "round": 2,
  "head": "25102f2",
  "verdict": "pass",
  "findings": [],
  "followups": [
    "Two equivalent mutants survive (satellite-prefix datatake match; display alpha .any vs .all); no test needed while one satellite cannot make two datatakes over the domain on one UTC day and render() zeroes all bands together",
    "Runner timing on the merged head is the builder's (run 44993030654, 41-114 s per date); re-check at T1.5 backfill"
  ]
}
```

```json
{
  "gauntlet": "G-Method",
  "task": "T1.3",
  "round": 2,
  "head": "25102f2",
  "verdict": "pass",
  "findings": [],
  "followups": [
    "2026-02-16 R094 (S2A+S2B, listed, T1.1 keeps GS2B) is a real catalogue date the round-1 matcher would have got wrong; worth a G-Data spot check after the backfill",
    "pixel_hash differs between a Windows local render and the ubuntu runner for 2026-01-12 (QA scores identical); keep idempotency reruns on the same platform (G-Data, T1.5)",
    "Requester-pays and CDSE fallbacks untested until H6 credentials exist"
  ]
}
```
