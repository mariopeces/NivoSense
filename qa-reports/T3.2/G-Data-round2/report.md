# G-Data round 2: T3.2 Live DGT cams only (PR #29)

Head judged: **aacc5ca** (still the PR head when I checked, on `plan/t31-cetursa` b30435d). I judged only T3.2's diff (`git diff b30435d aacc5ca`). Live runs: 2026-11-22, 07:46 to 08:00 UTC.

**Verdict: fail.** Today's catalogue is clean: both kept DGT cams show real, current frames, and the 8 dropped cams are all the "IMAGEN NO DISPONIBLE" frame. The polygon filter matches my own computation exactly. The fix that keeps the first capture time works once a history exists. It fails open whenever there is no history: on the first deploy of this code, after any failed restore, and with a corrupt `state.json`. Then DGT shows frames burned in days or weeks earlier as minutes old. The documented 2 to 15 min limit is wrong by orders of magnitude. Separately, solid-colour dead frames (green, blue) pass the picture guards.

## What I ran

| Check | How | Result |
|---|---|---|
| Unit tests | `pytest -q backend/tests` on aacc5ca | 67 passed |
| Live ingest | `ingest_webcams.py` 07:46 UTC, then 3 more runs at 07:58 to 07:59 on the same stills folder | `Wrote 20 webcams (15 live); dropped 8`. Kept: dgt-169623, dgt-169624. Dropped: 312, 313, 316 to 320 and 168446, all md5 `c92fb644` (IMAGEN NO DISPONIBLE) |
| Kept frames, looked at | `evidence/live_run_0746_log.jsonl` | 169623 burned in 08:38:17 CET, 169624 08:38:40 CET; Last-Modified 07:42:01 UTC, so 3.5 min later. Both real daylight road scenes. Credit `https://www.dgt.es/conoce-el-estado-del-trafico/camaras-de-trafico/` |
| History with state present, live | runs 2 to 4 | Run 4 saw the same bytes as run 3: `unchanged_since_last_run: true`, captured_at kept at 07:54:01 |
| Validator | `validate_webcam_artifact.py` on a dist built from run 1 (with `state.json` in the stills folder) | `webcam catalogue OK` |
| Polygon + 2 km | shapely `distance` in EPSG:25830 against the `domain` part of `data/domain.geojson`, for all 1,980 cams in the DGT feed (`evidence/poly.py`, `polygon_check.txt`) | **0 mismatches** with `load_area().contains`. Nearest in: 168446 at 1,916 m. Nearest out: 1565 at 2,015 m, 169625 at 2,492 m. `domain.geojson` is the same blob as `plan/t21-domain` bad749e (47a4974) |
| National scan of DGT frames | all 1,980 feed URLs, three scans (07:48, 07:52, 07:56 UTC); `picture_problem(…, "DGT")` run on all 1,609 decodable non-stock frames (`evidence/national_classification.json`) | 1,576 pass, 19 caught as blank dark, 4 caught by "No video" match, 8 IMAGEN NO DISPONIBLE at a new md5 caught by dHash, 2 undecodable. Of the passes, **3 are dead frames** (finding 2) |
| Own "No video" variants | `evidence/variants.py` | Caught: 1280×720 q50, 352×288 q20, ±6 sensor noise, and DGT's own 704×480 and 853×480 renditions found live. Passed: a brightened "No video" (uniform grey) |
| Real dark night frames | builder's DGT night fixtures, darkened | ×0.8 and ×0.6 stay live. ×0.4 dropped (the documented DGT-only limit; correct) |
| Missing or corrupt `state.json`, frozen frame | `evidence/repro.py` on the shipped region config, real DGT bytes, in-domain cam 312 | Fails open (finding 1) |

## Findings

### 1. Blocker: without a history, a weeks-old re-stamped DGT frame is listed as minutes old; the "2 to ~15 min" known limit is wrong

DGT re-stamps unchanged frames for weeks, not minutes. In the national scan, these frames kept the same bytes between 07:48 and 07:56 UTC while Last-Modified moved forward to about 07:47 UTC (`evidence/restamped_frozen_frames.jpg`):

| cam | burned-in clock | Last-Modified at 07:56 UTC | real age |
|---|---|---|---|
| 162889 (N-351) | 02/10/2026 09:?7 | 07:47:01 | about 7 weeks |
| 160004 (A-7) | 13-11-2026 01:05:44 | 07:47:01 | 9 days |
| 330 (A-483) | 21-11-2026 13:01:22 | 07:47:01 | 19 h |
| 169538 (N-352) | 21-11-2026 18:07:59 | 07:47:01 | 13 h |

`apply_history` only pulls `captured_at` back when the previous run saw the same bytes. With no usable history, `captured_at` is the latest re-stamp. My reproduction (`evidence/repro.py`, output in `repro_output.txt`) put the 162889 bytes on in-domain cam 312, with Last-Modified 3 min before the run, as DGT serves it:

- no `state.json` (this code's first deploy: the live site has no `state.json` today): `kept, live, captured_at 07:57` for a frame from 2 October;
- state kept for 60 min, then lost because the restore failed: the run at t0+90 min resets to `kept, live, captured_at 09:27`. The new `state.json` written by that run overwrites the old history for good, so the drop slips another 2 h (dropped only at t0+211 min);
- corrupt `state.json` after the frame had already been dropped as stale: `kept, live, captured_at 12:57`. The frame comes back as fresh.

The restore step treats any curl failure as "no history" and carries on (`pages.yml`, "Restore the webcam frame history"). Pages answered 503 three times out of three for `…/data/webcam-stills/state.json` during my check (that file does not exist yet on the site), so a failure is not hypothetical. The builder's own test `test_broken_history_only_loses_earlier_times` asserts this fail-open behaviour.

This breaks F3 ("never a fresh-looking placeholder") exactly as round 1's re-stamp major did, and the PR's Known limits ("2 min … about 15 min … from the next run on its age grows") understates it. The STATUS.md decision accepted a 2 to ~15 min residual, not weeks.

**To pass:** never list a DGT frame whose age cannot be bounded. For example: a DGT cam with no history entry, or after a failed or corrupt restore, is held out (logged `first sight, waiting for a new frame`). It is listed only once a run sees bytes that differ from the previous run's, which bounds the error by the run interval. Make a failed restore distinguishable from "no history yet", so it is not silently written over. Add a test: no history plus a re-stamped old frame gives no card. Correct the Known limits.

### 2. Major: solid-colour and half-corrupt dead frames pass the picture guards

The dark-frame rule needs mean ≤ 16, and the thumbnail match only knows the black "No video" and the grey "IMAGEN NO DISPONIBLE". Three dead frames from the live national feed pass, and my reproduction lists each one as `kept, live` with a fresh `captured_at` on in-domain cam 312 (`evidence/uniform_and_dead_frames.jpg`, `repro_output.txt` section A):

- 164375 (A-138): a solid green frame, grey mean 79.0, sd 0.2;
- 168074 (AP-66): a solid blue "no signal" frame, mean 46.0, sd 5.3, with 96 % of pixels in one colour bin;
- 1086 (LO-20): the bottom half is solid green (decoder failure) and there is no burned-in clock.

A "No video" frame brightened to uniform grey also passes (`variants_output.txt`). None of these cams is in the domain today. But 168074 belongs to the same 168xxx series as the "No video" and "login return time is up" frames, and in-domain dgt-168446 belongs to that series too. This is the same class as round 1's blocker: a dead frame with unique bytes. No real frame in the national scan came close to these: the next most uniform pass had 51 % of pixels in one colour bin.

**To pass:** treat a frame as blank when most of its picture (overlay bands excluded) is one colour, at any brightness. Examples: sd ≤ 3 at any mean, or ≥ 90 % of pixels in one coarse RGB bin, or a large single-colour block. Keep the real night fixtures live. Add 164375, 168074 and 1086 as fixtures.

### 3. Minor: a DGT frame with no usable Last-Modified is listed live with no age

When Last-Modified is missing, or more than 2 min ahead of Date, `captured_at` is null. The stale check needs `captured`, so it is skipped, and the cam is listed live with an unknown age. This did not happen in today's runs. **To pass:** for `live_only` sources, drop a frame without a capture time, or test that the card shows an unknown age.

## Known limits, as documented

- "First-sight capture time … 2 min … about 15 min": **inaccurate** (finding 1). Re-stamped frames up to about 7 weeks old were seen live today.
- "Picture guards are DGT only; a real DGT frame that dark is dropped too": **accurate.** My darkened night fixtures stay live down to ×0.6 and drop at ×0.4.

## Accept: "no placeholder card in the catalogue"

Holds for today's live catalogue (2 DGT cams, both real and current). It does not hold in general: findings 1 and 2 each produce a live DGT card that is not a current view, on real DGT bytes, through `build_catalog` with the shipped config.

## Finding JSON

```json
{
  "gauntlet": "G-Data",
  "task": "T3.2",
  "round": 2,
  "verdict": "fail",
  "findings": [
    {
      "severity": "blocker",
      "where": "backend/ingest_webcams.py apply_history / build_catalog history load; .github/workflows/pages.yml 'Restore the webcam frame history'; PR #29 Known limits",
      "what": "With no usable frame history (first deploy, failed restore, corrupt state.json) a DGT frame re-stamped for days or weeks is listed live with captured_at = its latest Last-Modified; a failed restore also overwrites the history for good. The documented 2 to ~15 min residual is wrong.",
      "observed": "National scan 07:48-07:56 UTC: cams 162889 (burned in 2026-10-02), 160004 (2026-11-13), 330 and 169538 (2026-11-21) had unchanged bytes and Last-Modified 07:47 UTC. repro.py with the 162889 bytes on in-domain cam 312: no state gives kept/live at 07:57; state lost at t0+90 gives captured_at reset to 09:27 and drop delayed to t0+211; corrupt state after a stale drop brings it back live at 12:57. Pages answered 503 for state.json during the check.",
      "to_pass": "Hold out any DGT cam whose frame age cannot be bounded (no history entry, failed or corrupt restore) until a run sees bytes that differ from the previous run's; do not silently overwrite history after a failed restore; add a test (no history + re-stamped old frame gives no card); correct Known limits."
    },
    {
      "severity": "major",
      "where": "backend/ingest_webcams.py picture_problem (BLANK_MAX_MEAN / reference match)",
      "what": "Solid-colour and half-corrupt dead DGT frames pass the picture guards and would be listed live.",
      "observed": "Live national feed: 164375 solid green (mean 79, sd 0.2), 168074 solid blue no-signal (mean 46, sd 5.3, 96% in one colour bin), 1086 lower half solid green; each is kept/live on in-domain cam 312 in repro.py. A brightened No video frame also passes. The next most uniform real frame: 51% in one bin.",
      "to_pass": "Blank test on uniformity at any brightness (e.g. sd <= 3 at any mean, or >= 90% of picture pixels in one coarse RGB bin, or a large single-colour block), keeping real night fixtures live; add 164375, 168074 and 1086 as fixtures."
    },
    {
      "severity": "minor",
      "where": "backend/ingest_webcams.py build_catalog stale check",
      "what": "A live_only (DGT) frame with no usable Last-Modified is listed live with captured_at null and skips the stale check.",
      "observed": "Code path: captured is None, so the STALE_AFTER branch is skipped; not seen live today.",
      "to_pass": "Drop live_only frames without a capture time, or test that the card shows an unknown age."
    }
  ],
  "followups": []
}
```
