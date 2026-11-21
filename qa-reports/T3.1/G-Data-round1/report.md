# G-Data gauntlet: T3.1 Cetursa webcams, round 1

PR #8, branch `plan/t31-cetursa` at `34a7648`, evidence `evidence/t31-cetursa` at `b425b1c`.
Run on 2026-11-21 between 23:22 and 23:30 UTC (00:22 to 00:30 CET), at night. The catalogue write through `pipelines/catalog/` is out of scope this round, because it waits on T0.3.

**Verdict: fail.** There are 2 major findings, both about F3 and the "correct age" Accept line. Everything else checked holds.

## What I ran

| Check | Result | Evidence |
|---|---|---|
| Ingest against the live providers (`python backend/ingest_webcams.py --output …`) | exit 0, 26 cams, 13 live. Same split as the builder: 5 Cetursa offline (15110/2, 15110/4, 15114/0-2), all 8 DGT offline | `ingest.log`, `webcams.json` |
| Status vs what the provider serves | I fetched every thumbnail and the large frame myself. All 5 offline Cetursa views serve the feratel "Derzeit ist kein aktuelles Bild verfügbar." frame at both sizes (md5 `db70616d…` / `01aa3856…`). The 13 live ones serve real frames | `frames/`, `headers/` |
| Age vs the time burned into the frame | Every live cam matches. 15111/0: overlay 18:08 CET, `Last-Modified` 17:08:05 GMT. 15111/1 (v3 design): "06:08 PM". 15112/0: 18:09 vs 17:09:37. 15113/5: 18:11 vs 17:11:48. Pradollano: overlay 00:22:35 CET, `Last-Modified` 23:22:38 GMT. The feratel frames are the last stills before dark, so "hace 6 h" is the real age | `frames/*.jpg`, `headers/` |
| DGT placeholder with real frames | All 8 DGT cams serve md5 `c92fb644…` ("IMAGEN NO DISPONIBLE") and are offline | `ingest.log` |
| Positions come from feratel metadata | I fetched the feratel player for 15110 to 15114. `infolat`/`infolong` are 37.058909/-3.39374, 37.071122/-3.389411, 37.062669/-3.373692, 37.083357/-3.405949 and 37.090944/-3.399593. They match the config exactly. Pradollano is left null rather than guessed | player HTML (scratch) |
| Coverage | The resort page references 17 feratel views from stations 15110 to 15114, all in the config, plus `snap_c1.jpg`. Every URL is a `.jpeg`/`.jpg` still | `webcam_sources.json` |
| Credit line on every card (local `vite preview` build at 1440x900 with my `webcams.json`) | All 18 Cetursa cards show "Imagen: Cetursa Sierra Nevada / feratel", linked to `https://sierranevada.es/es/webcams/`. All 13 live images load | `cards-all.png`, `rail-1440.png` |
| Tests | 25 OK | |
| Deliberate breaks | Dropping the feratel 720x405 md5: 4 tests fail. Dropping the EOI check: 1 fails. Dropping the Content-Length check: 1 fails. Keeping `Last-Modified` on an offline cam: 1 fails | |

## F3 adversarial probes

`adversarial_probe.py` feeds real fetched bytes through `probe_camera_image`. The output is in `adversarial_probe.out`.

| Case | Result |
|---|---|
| A. feratel placeholder at hotspot size 38 (a real feratel response, 496x279, md5 `ca2e6386…`, not fingerprinted), served with `Last-Modified` = now | **live, captured_at = now** |
| B. real 15111/0 frame (overlay 18:08) served with a fresh `Last-Modified`, as a frozen cam would be | **live, captured_at = now** |
| C. the fingerprinted placeholder at sizes 37 and 35 (control) | offline |
| D. thumbnail is a real frame, large is the unfingerprinted placeholder | **live, captured_at = now** |

Two facts from feratel's own headers (`headers/`) matter here. On the placeholder, `Last-Modified` equals the response `Date` to the second: 15110/2 returns `date 23:22:52 / last-modified 23:22:52`, and size 38 returns `23:25:58 / 23:25:58`. On real frames, `Last-Modified` is the capture time (15111/0 returns `date 23:22:54 / last-modified 17:08:05`). So the only defence is the exact MD5, and any placeholder rendition it does not know turns into the worst F3 case: "live, hace 0 min" over a placeholder.

## Findings

1. **Major: the displayed age is not the age of the displayed image.** `LeftRail.tsx` hotlinks `thumbnail_url` from the provider, but the age is computed from the `captured_at` of the frame checked at ingest, and ingest runs hourly (`pages.yml` cron `17 * * * *`). I observed this at 23:29:02 UTC in the local build. The Pradollano card read "hace 10 min · 22/11/26, 0:18" (catalogue `captured_at` 23:18:08), while the image it was showing was the 23:27:09 frame (`Last-Modified` read in the browser, where CORS `*` allows it). With the hourly cadence the gap reaches about an hour. The worse direction: if a feratel cam dies after a run, the card keeps "live, hace N min" while it shows feratel's placeholder, which is exactly what F3 forbids. To pass, the card must show the frame that was checked. For example, ingest stores the checked still (H4 allows stills) and the card points at that copy, which fits the T0.3 catalogue. Another option is any equivalent that ties the shown bytes to `captured_at`. If hotlinking is meant to stay, that is a coordinator decision and F3 needs a stated exception.
2. **Major: an unknown placeholder rendition shows as live with age 0** (`backend/ingest_webcams.py:200-206`, `probe_camera_image`). See probes A and D above, run on real feratel bytes. Two cheap structural guards, both backed by today's data, would close it without a sourced threshold. First, for feratel, `Last-Modified` equal to the response `Date` (to within a few seconds) means not a camera frame, because real frames carry the capture time. Second, identical bytes served by two or more different cams in the same run mean placeholder: today 5 cams served the same bytes. Add a test for each guard using `frames/feratel-placeholder-38-unfingerprinted.jpg`. Probe B (a frozen frame with a fresh `Last-Modified`) has no cheap guard and was not observed at any provider. I list it as a follow-up.

### Minor

3. `probe_camera_image` takes `captured_at` from the `Last-Modified` of the last URL (the large image) and never compares it with the thumbnail's. If the two come from different frames, the rail's age describes a different image. Fix: require the two to be equal (or within one refresh), or keep both.
4. The `position_source` URLs (`webtv.feratel.com/webtv/?design=v5&cam=…`) return 404 to a plain client and 200 only with a browser User-Agent and a `sierranevada.es` Referer. Record that in the config or the runbook so the position can be re-checked.

## Follow-ups (not blocking, no new scope)
- A frozen camera that keeps re-serving an old frame with a fresh `Last-Modified` (probe B). Comparing the burned-in overlay (OCR) with `Last-Modified` would catch it; that belongs to a later monitoring task.
- The resort page lists 15111/1 in two renditions (`ap=1&design=v3`, 12-hour overlay, and `design=v5`). The config uses v3, which is fine.

```json
{
  "gauntlet": "G-Data",
  "task": "T3.1",
  "round": 1,
  "verdict": "fail",
  "findings": [
    {
      "severity": "major",
      "where": "frontend/src/components/LeftRail.tsx (img src = thumbnail_url, age from captured_at); .github/workflows/pages.yml cron 17 * * * *",
      "what": "The card hotlinks the provider's current image but shows the age of the frame checked at the last hourly ingest; the age does not belong to the image shown, and a cam that dies between runs shows feratel's placeholder labelled live with a recent age (F3).",
      "observed": "Local preview 2026-11-21 23:29:02 UTC: Pradollano card 'hace 10 min · 0:18' (captured_at 23:18:08) while the served and displayed frame had Last-Modified 23:27:09; cadence is hourly so the gap reaches about 60 min",
      "to_pass": "The card displays the checked still (e.g. ingest stores it, H4 allows stills, and the card uses that copy) or an equivalent that ties the displayed bytes to captured_at; otherwise a coordinator decision that F3 accepts hotlinking"
    },
    {
      "severity": "major",
      "where": "backend/ingest_webcams.py:200-206 image_problem / probe_camera_image",
      "what": "Placeholder detection is exact MD5 only; any feratel placeholder rendition not in the set passes as live with captured_at = now, because feratel sets Last-Modified = Date on its placeholder",
      "observed": "adversarial_probe.out: real feratel size-38 placeholder (md5 ca2e6386, Last-Modified == Date 23:25:58) -> live, captured_at now; thumbnail real + large unknown placeholder -> live, now",
      "to_pass": "Add guards with tests on the real size-38 frame: feratel Last-Modified within a few seconds of response Date means offline; identical bytes from 2 or more different cams in one run means placeholder"
    },
    {
      "severity": "minor",
      "where": "backend/ingest_webcams.py probe_camera_image (last_modified from the last URL only)",
      "what": "captured_at comes from the large image only; the thumbnail's Last-Modified is never compared",
      "observed": "code read; today both carry equal Last-Modified (ingest.log)",
      "to_pass": "Require equal Last-Modified across sizes, or keep both"
    },
    {
      "severity": "minor",
      "where": "backend/webcam_sources.json position_source",
      "what": "position_source URLs 404 without a browser User-Agent and a sierranevada.es Referer",
      "observed": "curl plain: 404; with UA + Referer: 200 with infolat/infolong matching the config",
      "to_pass": "Note the needed headers next to position_source or in the runbook"
    }
  ],
  "followups": [
    "Frozen camera re-serving an old frame with a fresh Last-Modified (probe B): overlay OCR vs Last-Modified in monitoring",
    "15111/1 is listed by the resort in v3 and v5 renditions; config uses v3"
  ]
}
```
