# G-Data · T3.2 Live DGT cams only · round 1

PR #29, branch `plan/t32-dgt`, head **f12ab57** (unchanged since dispatch). Judged only T3.2's commit `f12ab57` (5 files). Live checks were run against the DGT feed on 2026-11-22, 05:56 to 06:10 UTC.

**Verdict: fail.** Today's catalogue is clean: 1 DGT cam is kept, it is a real frame, and the 24 dropped cams really are serving the placeholder. But the check lets through a second DGT dead-camera frame that DGT serves right now, and that would put a placeholder card in the catalogue on any run where an in-domain cam falls back to it. Separately, the card's age comes from `Last-Modified`, and DGT re-stamps that header on unchanged frames, so the age can be wrong.

## What I checked

| Check | Result |
|---|---|
| Unit tests at f12ab57 | `python -m unittest discover -s backend/tests`: 53 OK |
| bbox vs T2.1 domain | `data/domain.geojson` on `origin/plan/t21-domain` (7 rings), bounds computed independently: `[-3.6433, 36.9129, -2.5885, 37.2532]`. Matches `region.bbox` exactly. |
| Missed cams | Independent regex parse of the live DATEX II feed (`publicationTime 06:00:01+01:00`, 1980 cameras): 25 in the bbox, the same 25 IDs as the builder's log and as my ingest run. None missed. |
| Builder's ingest, live, 06:02 UTC | exit 0, `Wrote 19 webcams (14 live) ...; dropped 24`. Log: `ingest-live-0602utc.log`. Validator on that output: `webcam catalogue OK`. |
| Dropped cams | All 24 serve md5 `c92fb644…` (32634 B, 639x359), visually "IMAGEN NO DISPONIBLE" (`evidence/dgt-312-placeholder.jpg`). Correctly dropped. |
| Kept cam dgt-169624 | Real night frame of A-44 PK 158+300 Nigüelas, 853x480. Stored still burned-in 06:53:40 CET = 05:53:40 UTC, `captured_at` 05:58:01 (see finding 2). |
| Credit link | `https://www.dgt.es/conoce-el-estado-del-trafico/camaras-de-trafico/` → HTTP 200, title "DGT - Cámaras de tráfico". The page itself says "no disponemos de la visualización de estas cámaras" until you search; the builder already notes this. |
| Placeholder variants (builder's `image_problem`, provider DGT) | re-encoded q50/q95, resized 320x180/853x480/1280x720, 10 px crop, brightness 0.8/1.15, letterboxed 4:3, and a real re-encoded copy DGT serves (cam 1687, 9422 B, md5 `7292eb9b…`): **all caught** (dHash distance 0 to 7). |
| Other DGT dead-camera frames | Random sample of 500 cams nationwide (seed 7): 81 serve `c92fb644`, 3 return a 0-byte 200 (caught as "empty body"), 11 return 404, and **7 serve a black "No video" frame that the check does not catch** (finding 1). |
| Frozen frame | Same bytes re-served with a newer `Last-Modified` were seen on 5 cams in about 5 minutes (finding 2). |

## Findings

### 1. Blocker: DGT's "No video" frame passes the check and is listed as a live card
- Where: `backend/ingest_webcams.py` `image_problem` / `PLACEHOLDER_DHASH`; it applies through `build_catalog` `live_only`.
- Observed: DGT cams 168076, 168095, 168099, 168113, 168114, 168119 and 168121 (7 of 489 that answered in the sample) serve a 587x480 all-black frame with only the DGT logo, a burned-in timestamp and "No video" (`evidence/dgt-168121-no-video.jpg`). Because the timestamp is burned in, every copy has different bytes, so neither the MD5 list nor the shared-bytes check matches it. `image_problem` returns `None`, with dHash distance 20 to 21. That is past the 10-bit threshold and close to real night frames (23 to 28), so dHash cannot separate them.
- End to end (`scripts/e2e.py`): the real feed was used, with in-domain cam **dgt-168445** (GR-3211, the same 168xxx encoder series) serving this frame. `build_catalog` kept it with `status: live` and a stored still, and `validate_webcam_artifact.py` returned no errors. Today 168445 and 168446 serve "IMAGEN NO DISPONIBLE". Once either comes back as "No video", the catalogue holds a placeholder card.
- To pass: detect this frame, for example as a frame whose picture area (overlay bands excluded) is uniformly black (mean and standard deviation near 0; the samples measure mean 0 to 3, std 0.0). Add a test that uses the real frame as a fixture and drops it, and keep a real night frame (for example dgt-169624's) passing.

### 2. Major: a DGT card's age comes from `Last-Modified`, which DGT re-stamps on unchanged frames (F3)
- Where: `probe_camera_image` sets `captured_at` from `Last-Modified`, and the card shows it via `formatCapturedAt`.
- Observed:
  - DGT 1310: the same bytes (md5 `91e268b1…`) moved from `Last-Modified 05:47:01` to `05:57:01`. The burned-in time is 06:32:06 CET (05:32:06 UTC), so the card would read about 25 min fresher than the frame (`evidence/dgt-1310-…`).
  - The kept dgt-169624: md5 `76b8c750…` was served with `Last-Modified 05:54:01` at 05:56 and with `05:58:01` at 06:02. The burned-in time is 05:53:40 UTC. My live catalogue therefore says `captured_at 05:58:01`, 4.3 min too fresh. The next frame (05:58:40 burned-in) arrived with `Last-Modified 06:00:02`.
  - In a re-fetch of 405 live sample cams about 5 minutes later, 4 had the same bytes with a newer `Last-Modified`.
- So for DGT, `Last-Modified` is when DGT last rewrote the file, not when the frame was captured. The T3.1 proof (LM equals burned-in time) was for feratel and Cetursa. A frozen DGT cam keeps a fresh-looking age, which is what F3 forbids.
- To pass: DGT `captured_at` is never later than the frame's real capture. Options: take the earliest `Last-Modified` seen for the same bytes (state from the previous published `webcams.json`), or read the burned-in time. Show it on a re-stamped cam like 1310, or treat a DGT frame whose time cannot be established as "Hora desconocida".

### 3. Minor (follow-up): the domain bbox holds cams far outside the domain polygon
- Only 4 of the 25 in-bbox cams lie inside `domain.geojson` (312, 313, 319, 320 on the A-395). The kept dgt-169624 is about 2 km outside it, and the A-92 and GR-30 cams are Granada metro cams.
- The card says "bbox", so this does not block. A polygon (or buffered polygon) filter would keep the map on the domain.

### 4. Minor (follow-up): PR #29 is stacked on pre-rebase T3.1 commits
- The PR's T3.1 commits are `34a7648`, `2f28bf1` and `083c3b5`. The current `plan/t31-cetursa` is `4c92ab0`, `2874cd4`, `47dd0bb` and `b30435d`, so the PR does not contain `b30435d`.
- It needs a rebase onto the current base before merge, otherwise the diff GitHub shows includes T3.1.

## Scripts and evidence
- `scripts/probe.py`: independent feed parse, polygon test (shapely), fetch of every in-bbox cam.
- `scripts/national.py`, `scripts/novideo.py`, `scripts/restamp.py`: national sample, black-frame detection, re-stamp detection.
- `scripts/variants.py`: placeholder variants and frozen frame through the builder's `image_problem` and `probe_camera_image`.
- `scripts/e2e.py`: `build_catalog` plus the validator, with dgt-168445 serving "No video".
- `evidence/*.jpg`: the frames named above.

```json
{
  "gauntlet": "G-Data",
  "task": "T3.2",
  "round": 1,
  "verdict": "fail",
  "findings": [
    {
      "severity": "blocker",
      "where": "backend/ingest_webcams.py image_problem / PLACEHOLDER_DHASH (via build_catalog live_only); live DGT feed 2026-11-22 05:59 UTC",
      "what": "DGT's black 'No video' dead-camera frame (587x480, burned-in timestamp, unique bytes per fetch) passes every check and is listed as a live card",
      "observed": "7 of 489 sampled DGT cams (168076, 168095, 168099, 168113, 168114, 168119, 168121) serve it; image_problem returns None (dHash distance 20-21, threshold 10, real night frames 23-28); build_catalog on the real feed with in-domain dgt-168445 (same 168xxx series) serving it -> kept, status live, validator OK",
      "to_pass": "detect the uniformly black picture area (overlay bands excluded) and drop it; test with the real frame fixture, and a real night frame still passes"
    },
    {
      "severity": "major",
      "where": "backend/ingest_webcams.py probe_camera_image captured_at from Last-Modified; card age via LeftRail formatCapturedAt; dgt-169624 and DGT 1310, 2026-11-22 05:47-06:05 UTC",
      "what": "DGT re-stamps Last-Modified on unchanged frames, so captured_at and the card's age are fresher than the real capture (F3); a frozen DGT cam keeps a fresh age",
      "observed": "1310: same md5 91e268b1, LM 05:47:01 -> 05:57:01, burned-in 05:32:06 UTC (25 min too fresh); dgt-169624 (kept): md5 76b8c750 with LM 05:54:01 then 05:58:01, burned-in 05:53:40 UTC, live catalogue captured_at 05:58:01; 4 of 405 sampled live cams re-stamped within ~5 min",
      "to_pass": "a DGT captured_at never later than the real capture: earliest LM seen for the same bytes (previous published catalogue), burned-in time, or 'Hora desconocida'; shown on a re-stamped cam"
    },
    {
      "severity": "minor",
      "where": "backend/webcam_sources.json region.bbox",
      "what": "the domain bbox holds 21 cams outside the domain polygon, including the kept dgt-169624 (~2 km out) and Granada metro A-92/GR-30 cams",
      "observed": "shapely point-in-polygon against origin/plan/t21-domain data/domain.geojson: 4 of 25 in-bbox cams inside",
      "to_pass": "follow-up: filter by the (buffered) domain polygon once T2.1 merges"
    },
    {
      "severity": "minor",
      "where": "PR #29 branch history",
      "what": "the PR is stacked on pre-rebase T3.1 commits and lacks b30435d from the current plan/t31-cetursa",
      "observed": "git log origin/plan/t31-cetursa..f12ab57 shows 34a7648, 2f28bf1, 083c3b5 besides f12ab57",
      "to_pass": "rebase onto the current plan/t31-cetursa before merge"
    }
  ],
  "followups": [
    "Filter DGT cams by the domain polygon rather than its bbox (finding 3).",
    "The DGT credit page shows no cameras until a search; consider the NAP dataset page with the licence."
  ]
}
```
