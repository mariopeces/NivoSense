# G-Code gauntlet: T3.1 Cetursa webcams, round 2

PR #8, branch `plan/t31-cetursa`. I started on `2f28bf1`. The builder pushed `083c3b5` ("Isolate webcam source failures and gate the deploy on shipped stills") while I was testing, so every check below was rerun on **`083c3b5`**. Checked 2026-11-22 from 00:25 to 00:45 UTC (01:25 to 01:45 CET). Writing through `pipelines/catalog/` is pending on T0.3 and is out of scope for this round.

**Verdict: pass.** Four minor findings and some follow-ups, none blocking.

## Round 1 findings, rechecked with live frames

| Round 1 finding | Status | How I checked |
|---|---|---|
| G-Code major: localised feratel placeholder | **Fixed** | Fetched dead cam 15110/2 in 16 languages and 13 sizes, none of them in the builder's set (below) |
| G-Data major: the age does not belong to the image shown | **Fixed** | The card loads `data/webcam-stills/<cam>/<captured_at>-<size>-<sha>.jpg`, the bytes that were checked. The overlay on every stored still matches its `captured_at` |
| G-Data major: the size-38 placeholder gets past MD5 | **Fixed** | dHash and the request-time guard each catch every new rendition independently |
| captured_at taken from one size only | **Fixed** | Thumbnail and large carry the same `Last-Modified` for all 12 feratel cams; a test fails if the check is removed |
| No test pins station coordinates | **Fixed** | Latitude typo 37.058909 → 37.0589 now fails a test |
| ruff UP035 | **Fixed** | `ruff check` is clean on the changed files. The 5 remaining errors are in `build_basin_series.py` and `main.py`, which this PR does not touch |
| Hotlinking / `continue-on-error` | **Fixed in `083c3b5`** | See "Provider outage" below |

## Live ingest (my run, `083c3b5`, 00:40 UTC)

`python backend/ingest_webcams.py`: exit 0, 26 cams, **13 live and 5 offline among the 18 Cetursa cams**, all 8 DGT cams offline (T3.2). Log: [`ingest-083c3b5.log`](ingest-083c3b5.log); output: [`webcams.json`](webcams.json).

I compared each status and age with what the provider serves:
- **Pradollano**: `Last-Modified` 00:39:08Z; burned-in overlay `22.Nov 2026 01:39:05` CET ([crop](pradollano-overlay-crop.png)). The two agree within 3 s. Thumbnail and large are the same URL, and the frame is now stored once.
- **feratel 15111 (×5), 15112 (×2), 15113 (×5)**: `Last-Modified` 17:08:05Z, 17:09:37Z and 17:11:48Z. The overlays on the stored 3840×2160 larges read 18:08, 18:09, 18:11 and 06:08 PM CET ([crops](feratel-overlay-crops.png)), so they match. feratel serves no new frame overnight and keeps the old `Last-Modified` (still 17:08 at 00:40). The cards honestly show "hace 8 h · 21/11/26, 18:08".
- **Offline (15110/2, 15110/4, 15114/0-2)**: each serves the feratel placeholder (MD5 `db70616d`, `Last-Modified` = `Date`). Status offline, no image, "Sin conexión" on the card.

Positions: each feratel station has its own `latitude`/`longitude` with `position_source` = the feratel player. The five values are the ones round 1 verified against `infolat`/`infolong`, and a test now pins them. Pradollano has no published position, so it is `null`: listed in the rail, not on the map. No coordinates are guessed.

## F3 adversarial tests

**Placeholder in a new language or size.** I fetched dead cam 15110/2 and fed each frame to the PR's `image_problem`. I also replayed each one with an old `Last-Modified`, as a cache or CDN would send it, so that only the dHash guard is left:

| Variant | In MD5 list | dHash distance | Result | Result with old Last-Modified |
|---|---|---|---|---|
| pl, cs, ru, ca, hu, sv, da, sk (size 37) | no | 1 to 3 | offline (generated on request) | offline (dHash) |
| ja, zh, sl, hr, eu, gl, ro | yes (fall back to de) | 0 | offline | offline |
| sizes 40, 41, 42, 43, 44, 45 (de) | no | 0 to 2 | offline (generated on request) | offline (dHash) |
| sizes 30 to 34, 50 | n/a (HTTP 404) | n/a | n/a | n/a |
| `design=v3/v4`, `ap=1`, `lg=es` | yes | 0 to 2 | offline | offline |

Two independent guards catch every placeholder I could make feratel serve. Sample frames are in [`frames/`](frames/).

**dHash false positives.** Of the 26 real stills from my run, the closest is 22 bits from a placeholder (15111-0 large). The rest are 24 to 37 bits away, including the fog frames. Uniform grey and black frames are 14 bits away. The threshold is 10, so live cams are not dropped.

**Frozen camera: a stale frame with a fresh Last-Modified.** I replayed yesterday's real 15111-0 frame with `Last-Modified` = Date − 60 s, and `probe_camera_image` returned `live` with `captured_at` 1 minute old. So the hole exists in code. No provider has been seen doing this: overnight, feratel keeps the old `Last-Modified` for a frame it is not updating, and Pradollano's header is the time its file was written. The builder lists it under "Found, not done". Minor 2.

**Provider outage between runs, or a failed ingest.**
- On `2f28bf1` I reproduced the gap: with an unreachable DGT URL, `build_catalog` raised `URLError`, the whole ingest died, and `continue-on-error` shipped the committed `webcams.json`. Its stills were not in the build. The site then showed 13 Cetursa cards with an age and no image instead of "Sin conexión" ([`cards-failed-ingest.png`](cards-failed-ingest.png)).
- **`083c3b5` closes it**, and I checked each part:
  - A DGT outage is now logged (`"feed unavailable"`) and leaves the 18 Cetursa cams ingesting: exit 0, 13 live.
  - An unexpected error on one camera marks only that camera offline. The `except Exception` is logged with `noqa`, not silent.
  - `continue-on-error` is gone, and `webcams.json` is no longer committed (it is gitignored).
  - `validate_webcam_artifact.py` fails the deploy when a live card's still is not in `dist`. I deleted one cam's stills from a real build and it exited 1 with two `::error::` lines; on the intact build it prints "webcam catalogue OK".
  - A broken run now leaves the last good deploy up.
- Between runs, the site shows the last checked stills, and the age is computed in the browser, so it keeps growing honestly. A cam that dies after a run shows its last real frame with a growing age until the next run marks it offline. That meets F3.

**Last-Modified missing or ahead of Date.** If `Last-Modified` is ahead of `Date` by more than 120 s, the age becomes unknown, and a test covers it. If the header is missing, the cam is still `live` with `captured_at: null`, and the card reads "Hora desconocida" next to a picture. The card text allows this ("when available"). Minor 1.

## Stills in the Pages artifact

- Size: my build is 31 MB against 5 MB without stills. Large stills are 25.9 MB of that and thumbnails 1.0 MB. That is far below the 1 GB Pages site limit.
- Nothing accumulates between deploys. Each run checks out fresh, the stills folder is gitignored, and the artifact is rebuilt. Retention is one deploy, which suits a "latest still" product.
- The large stills (about 96 % of the bytes) are never displayed: the card uses `thumbnail_url` only. They are in scope because the card says "store thumbnail and large URLs", and U4's large image in the card comes later. Follow-up.
- Verdict: sound as a stand-in until the bucket `StillStore` (T0.3) exists.

## Accept lines

- **"Every Cetursa cam that is live today shows as live with a correct age": met.** In a local build of `083c3b5` with my live ingest, there are 13 live cards. Each loads its stored still, whose overlay time matches the card ("hace 4 min · 1:39" on the 01:39:05 Pradollano frame; "hace 8 h · 18:08/18:09/18:11" on the feratel frames). The 5 offline cams really serve the placeholder.
- **"Credit line on each": met.** All 18 of 18 Cetursa cards read exactly "Imagen: Cetursa Sierra Nevada / feratel" (DOM check plus [`cards-083c3b5.png`](cards-083c3b5.png)). Both the test and the deploy validator enforce it.
- H4, stills only: met. Only JPEG stills are fetched and stored, never video.

## Rubric

- **Tests**: `python -m unittest discover -s backend/tests` gives 46 OK on `083c3b5`. PR #8 has no CI checks; the tests run in `pages.yml` on `main`.
- **Deliberate breaks**: each of these fails the suite:
  - remove the request-time guard, the dHash check, the language pin, the capture-time agreement, the offline URL clearing, the shared-bytes guard, the EOI check or the content-type check;
  - empty the feratel MD5 list;
  - put a typo in a latitude or in the credit;
  - make the validator skip `is_file`;
  - leave the DGT outage uncaught;
  - turn off the clock-skew guard;
  - remove the per-camera except.
- **Scope**: the changes stay inside the card, plus the workflow wiring the coordinator asked for. There is no dead code, and the `StillStore` Protocol has one implementation now and a second pending on T0.3 (justified).
- **Names and comments**: readable; the comments explain why (dated provider observations).
- **Types and lint**: `tsc -b` and `vite build` OK; `ruff check` is clean on the changed files.
- **Secrets**: none. The User-Agent is generic.
- **Dependencies**: `pillow==11.*` in `pages.yml`, matching `requirements.txt`; justified in the PR (dHash).

```json
{
  "gauntlet": "G-Code",
  "task": "T3.1",
  "round": 2,
  "verdict": "pass",
  "findings": [
    {
      "severity": "minor",
      "where": "backend/ingest_webcams.py probe_camera_image (status live with captured_at None); frontend/src/components/LeftRail.tsx formatCapturedAt",
      "what": "A frame served without Last-Modified passes every check and is shown live with 'Hora desconocida' next to the picture; the request-time guard is also skipped for such a response",
      "observed": "probe_camera_image on the real 15111-0 fixture with last_modified=None returned status=live, captured_at=None; no provider omits the header today",
      "to_pass": "treat a missing Last-Modified as offline, or flag it in the log and the card, in a later round or T3.4"
    },
    {
      "severity": "minor",
      "where": "backend/ingest_webcams.py image_problem / probe_camera_image",
      "what": "A frozen camera that re-serves an old real frame with a fresh Last-Modified shows as live with a fresh age",
      "observed": "replayed the 2026-11-21 17:08 frame of 15111-0 with Last-Modified = Date - 60 s: status=live, captured_at 1 min old. Not seen at any provider: feratel kept Last-Modified 17:08:05 overnight",
      "to_pass": "follow-up with the T0.3 bucket store: offline when the sha256 equals a stored still with an older captured_at (no OCR needed); overlay OCR in T5.1"
    },
    {
      "severity": "minor",
      "where": ".github/workflows/pages.yml artifact; frontend/src/components/LeftRail.tsx (uses thumbnail_url only)",
      "what": "Large stills (25.9 of 26.9 MB of stills per deploy) ship in every Pages artifact but are never displayed",
      "observed": "du on a live ingest: large 25,947,582 B, thumbnails 1,032,216 B; grep finds no large_url use in frontend/src",
      "to_pass": "follow-up for T3.4/U4 (show the large still) or ship only what the card shows until then"
    },
    {
      "severity": "minor",
      "where": "PR body and backend/ingest_webcams.py:63-65 comment",
      "what": "The stated margin 'all real frames >= 25 bits' is not what I measured",
      "observed": "15111-0 large at 22 bits from the nearest placeholder (my run, 00:40 UTC); still 12 bits clear of the threshold",
      "to_pass": "correct the comment to the measured minimum"
    }
  ],
  "followups": [
    "frontend/public/data/webcams.json is no longer committed, so plain `npm run dev` without an ingest shows the English error 'Could not load webcams' (pre-existing copy); Spanish copy for T4.x",
    "DGT cameras vanish from the catalogue, rather than showing offline, during a DGT feed outage; logged, and acceptable for T3.2 to revisit",
    "position_source URLs still need a browser User-Agent and a sierranevada.es Referer to re-verify (recorded as position_source_note)"
  ]
}
```
