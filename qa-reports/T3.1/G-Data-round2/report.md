# G-Data gauntlet: T3.1 Cetursa webcams, round 2

PR #8, branch `plan/t31-cetursa` at `2f28bf1`, evidence branch `evidence/t31-cetursa`.
I ran everything on 2026-11-22 between 00:14 and 00:30 UTC (01:14 to 01:30 CET), at night. Writing through `pipelines/catalog/` waits on T0.3 and is not part of this round.

**Verdict: fail. There is 1 major finding.** Both round 1 majors are fixed: I checked each one with live frames and could not get a placeholder or an unchecked frame shown as live in a normal run. The remaining major is the failure path. When the ingest fails, the published site falls back to the committed `webcams.json`. That file points at stills that never exist in CI, so every Cetursa card shows as live, with no image, a stale age and no "Sin conexión" label.

## What I ran

| Check | Result | Evidence |
|---|---|---|
| Live ingest (`ingest_webcams.py --output … --stills-dir …`) | Exit 0. 26 cams, 13 live. Cetursa: Pradollano and 12 feratel views live. 15110/2, 15110/4 and 15114/0-2 are offline ("provider placeholder"). All 8 DGT cams are offline. | `ingest.log`, `webcams.json` |
| Status matches what the provider serves | I fetched the frames myself. 15114/0 serves feratel's "Derzeit ist kein aktuelles Bild verfügbar." frame (md5 `db70616d…`, `last-modified` = `date` = 00:26:37). DGT 312 serves "IMAGEN NO DISPONIBLE" (md5 `c92fb644…`). The 13 live cams serve real scenes. | `frames/placeholders.png`, `frames/*.headers` |
| Age matches the time burned into the frame, for every stored still (both sizes) | Pradollano: overlay 01:14:20 CET, `captured_at` 00:14:24Z. Borreguiles 15111/0, 2, 3, 4: overlay 18:08, and 15111/1 (v3 design) shows "06:08 PM", against 17:08:05Z. Veleta 15112/0-1: overlay 18:09, 17:09:37Z. Montebajo 15113/0-3 and 5: overlay 18:11, 17:11:48Z. Thumbnail and 3840x2160 large are the same frame in every case. The feratel stills are the last frames before dark, so "hace 7 h" is the real age. | `overlays.png` |
| Card shows exactly the checked bytes | The stored names are content-addressed (`<cam>/<captured_at>-<size>-<sha256[:16]>`). In the local build every live card loads `data/webcam-stills/…` (13 of 13 loaded, naturalWidth > 0). Nothing loads from a provider host. | `rail-1440.png`, `cards-all.png` |
| Credit line on every Cetursa card (local `vite build` of the PR with my live catalogue, 1440x900) | 18 of 18 cards read "Imagen: Cetursa Sierra Nevada / feratel", linked to `https://sierranevada.es/es/webcams/`. Ages: "hace 9 min · 22/11/26, 1:14" (Pradollano), "hace 7 h · 21/11/26, 18:08/18:09/18:11" (feratel), and "Sin conexión" on the 5 offline views. | `cards-all.png` |
| Positions come from feratel metadata | I fetched the webtv player for 15110 to 15114 (browser UA plus sierranevada.es Referer, as `position_source_note` says). `infolat`/`infolong` match the config exactly for all 5 stations. Pradollano is null and is not placed on the map; nothing is guessed. | `positions.out` |
| Tests | 35 OK | |
| Deliberate breaks (one at a time, restored after each) | Removing the Last-Modified = Date guard: 1 test fails. Disabling dHash: 1 fails. Disabling the shared-bytes guard: 1 fails. Dropping the size capture-time equality: 1 fails. Not storing stills (card keeps the provider URL): 2 fail. Dropping the size-38 MD5: 1 fails. Unpinning Accept-Language: 1 fails. | |

## Round 1 findings, rechecked with live frames

| Round 1 finding | Status | How I checked |
|---|---|---|
| Major 1: the age shown is not the age of the image shown | **Fixed** | The card loads the stored still whose `captured_at` it shows (see above). The age grows on the client between runs, so it stays honest. |
| Major 2: an unknown placeholder rendition shows as live | **Fixed** | `probe_renditions.py` fetched 15110/2 at hotspot sizes 30 to 45 with 20 `Accept-Language` values (none, de, es, en, fr, it, nl, pt, ca, eu, pl, cs, ru, ja, zh, sv, hu, sl, hr, da). Sizes 30-34 return 404. Sizes 35-45 give 118 distinct renditions, including 6 sizes the builder never saw (40-45, from 76x43 to 586x330). All 220 responses are rejected with their real headers. With `Last-Modified` moved 3 h back (so only MD5 and dHash decide), all are still rejected. dHash distances are 0-7, against a threshold of 10 (`renditions.out`). Real frames are at least 22 bits away. Synthetic whiteout, fog and black-night frames are 14 to 27 bits away, so fog does not turn a live cam offline (`dhash_margin.out`). |
| | | Shared-bytes guard alone, on a live run with MD5, dHash and the Date guard disabled: the same 5 dead feratel views go offline and every real cam stays live (`adversarial_probe.out` H). |
| Minor 3: `captured_at` comes from one size only | **Fixed** | Probe G: different `Last-Modified` per size → offline. Probe F: real thumbnail plus placeholder large → offline. |
| Minor 4: `position_source` returns 404 | **Fixed** | `position_source_note` states the headers needed, and they work. |

## F3 adversarial probes (`adversarial_probe.py`, real bytes)

| Case | Result |
|---|---|
| A. 118 placeholder renditions × 2 header variants | 0 pass as a frame |
| B. Frozen camera: the real 18:08 frame re-served with a fresh `Last-Modified` | live, `captured_at` = now−5 min. There is no guard against this. Not observed at any provider; a follow-up as agreed in round 1. |
| C. Stale camera: the real frame with its true `Last-Modified`, served 3 days later | live, `captured_at` 21 Nov 17:08. The card says "hace 3 d", which is honest. |
| D. Clock skew: `Last-Modified` 50 min ahead of `Date` | live. `formatCapturedAt` clamps negative ages to 0, so the card shows **"hace 0 min"** for a frame of unknown age. Not observed today (Pradollano runs 30 s behind `Date`). Minor. |
| E. Real frame with no `Last-Modified` | live, "Hora desconocida". The card allows it ("when available"). |

## Shipping stills in the Pages artifact

- **Size.** One run stores 26 files, 26 MB. The site build grows from 5.1 MB to 31 MB. About 24 MB of that is the 3840x2160 large stills (1.6 to 3.3 MB each), which no UI loads yet. Pradollano's single file is stored twice, as thumbnail and large.
- **Retention.** None is needed. Every Pages run starts from a fresh checkout, so each deploy holds only that run's stills and nothing accumulates.
- **Between runs.** The last deploy stays up, and each card ages honestly against its stored frame. That is sound.
- **When the ingest fails, the site breaks (major 1 below).** `pages.yml` runs the ingest with `continue-on-error: true` and then builds anyway. The other products restore their last good artifact, but webcams restore nothing. The build then ships the committed `frontend/public/data/webcams.json`, whose 13 live entries point at `data/webcam-stills/…` files that are gitignored and so never exist on the runner.

## Findings

1. **Major: a failed ingest publishes 13 "live" Cetursa cards with no image, a stale age and no "Sin conexión" label.**
   - Where: `.github/workflows/pages.yml` ("Refresh webcam catalog", `continue-on-error: true`); `frontend/public/data/webcams.json` (committed, references gitignored stills); `backend/ingest_webcams.py:423-432` (`fetch_bytes` of the DGT XML is not guarded).
   - Trigger 1, an outage at an unrelated provider: with the DGT URL unreachable, `ingest_webcams.py` exits 1 with no catalogue and no stills (`dgt_down.out`), so one DGT outage stops the Cetursa refresh.
   - Trigger 2, any other uncaught error has the same effect.
   - Observed: I built the PR from a clean checkout, which is what CI ships after a failed ingest, and served it. All 13 `<img>` return 404 and are hidden by `onError`. The cards read "Pradollano … hace 50 min · 0:33" and "hace 7 h · 18:08", with no image and not "Sin conexión" (`failed-ingest-rail-1440.png`, `fallback-committed-webcams.json`). Pradollano was live and updating at the time, yet the card showed an old age for a frame the site does not have.
   - Why it is silent: the step is `continue-on-error`, so the run succeeds and no issue is opened. The state lasts until a later run succeeds, with the age growing to days.
   - To pass: a failed or partial ingest must never publish live cards without their stills. For example:
     - make each source's failure local (DGT down marks only DGT cams offline);
     - commit a `webcams.json` that references nothing unshipped (all offline, or empty);
     - in "Validate static artifact", fail the build when a live camera's `thumbnail_url` or `large_url` is missing from `dist/`, so the last good deploy stays up.
   - Add a test for the source-failure path.

### Minor

2. **A `Last-Modified` ahead of `Date` shows as "hace 0 min".** Where: `backend/ingest_webcams.py:352-354` and `LeftRail.tsx` `formatCapturedAt` (`Math.max(0, …)`). Probe D: a frame with `Last-Modified` 50 min in the future is live, and the card says "hace 0 min". Not observed at either provider today. To pass: treat `Last-Modified` more than a few minutes after `Date` as no capture time (or offline), with a test.

## Follow-ups (not blocking)

- Frozen camera re-serving an old frame with a fresh `Last-Modified` (probe B): OCR the overlay against `Last-Modified` in monitoring. This is already in "Found, not done".
- The 3840x2160 large stills are 24 of the 26 MB per deploy and are unused until the large image appears in the UI. Consider storing a downscaled large image once T0.3 moves stills to the bucket.
- Pradollano's thumbnail and large are the same URL and are stored twice.

```json
{
  "gauntlet": "G-Data",
  "task": "T3.1",
  "round": 2,
  "verdict": "fail",
  "findings": [
    {
      "severity": "major",
      "where": ".github/workflows/pages.yml 'Refresh webcam catalog' (continue-on-error: true); frontend/public/data/webcams.json (committed, references gitignored stills); backend/ingest_webcams.py:423-432 (DGT fetch_bytes unguarded)",
      "what": "A failed ingest ships the committed webcams.json: 13 Cetursa cams marked live whose stills do not exist in the artifact, so the cards show no image, an old age and no 'Sin conexión'; a DGT outage alone triggers it, silently",
      "observed": "DGT URL unreachable -> ingest exit 1, nothing written (dgt_down.out); clean-checkout build served locally 2026-11-22 00:2x UTC: 13/13 stills 404 and hidden, cards 'Pradollano hace 50 min · 0:33', 'hace 7 h · 18:08' (failed-ingest-rail-1440.png)",
      "to_pass": "A failed or partial ingest never publishes live cards without their stills: per-source failure isolation, a committed webcams.json that references nothing unshipped, and/or artifact validation that fails the build when a live cam's stills are missing from dist (keeping the last good deploy); test for the source-failure path"
    },
    {
      "severity": "minor",
      "where": "backend/ingest_webcams.py:352-354; frontend/src/components/LeftRail.tsx formatCapturedAt (Math.max(0, ...))",
      "what": "A Last-Modified ahead of the response Date is accepted and the card shows 'hace 0 min'",
      "observed": "adversarial_probe.out D: real frame with Last-Modified now+50 min -> live, captured_at in the future; card clamps to 0 min. Not observed at the providers today",
      "to_pass": "Last-Modified more than a few minutes after Date is treated as no capture time or offline, with a test"
    }
  ],
  "followups": [
    "Frozen camera re-serving an old frame with a fresh Last-Modified (probe B): overlay OCR vs Last-Modified in monitoring",
    "3840x2160 large stills are 24 of 26 MB per deploy and unused by the UI; store a downscaled large once stills move to the bucket (T0.3)",
    "Pradollano thumbnail and large are the same URL and stored twice"
  ]
}
```
