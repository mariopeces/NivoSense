# Tasks

Every task is one unit a build agent takes from start to a merged PR. Format of a card:

- **Lane**: which worktree it runs in (see `orchestration.md`).
- **Needs**: tasks that must be merged first. **Gate**: human gate that must be answered first.
- **Do**: the change. **Out**: files and products it must produce.
- **Accept**: the criteria the gauntlets check. **Evidence**: what the builder attaches to the PR so the gauntlets can check without guessing.
- **Gauntlets**: which validators must pass (codes in `gauntlets.md`). Every task also passes G-Code.

Rules for every task:
- Read `AGENTS.md`, `docs/plan/README.md` and the card. Do only the card; anything else found goes into the PR's "Found, not done" list.
- Real data only. Never invent values, dates, scenes or camera positions. Empty states are fine.
- Every product goes through `pipelines/publish` and the catalogue; nothing writes to the bucket directly.
- Tests run in CI. A task that adds a pipeline step adds its tests and a QA check.
- No secrets in code, logs or PRs.

## Lanes

| Lane | Worktree | Tasks |
|---|---|---|
| A. Platform | `plan-platform` | T0.1 to T0.4, T0.6, T0.7, T1.5, T1.6, T5.x |
| B. Observation | `plan-observation` | T1.0 to T1.4, T1.7 |
| C. Model | `plan-model` | T2.x |
| D. Webcams | `plan-webcams` | T3.x |
| E. Interface | `plan-ui` | T4.x |

## Dependency graph

```
T0.1 rules ─> T0.6 CI+tooling ─┬─> T0.3 catalogue+publish ─┬─> T0.4 QA harness
T0.2 buckets (H2) ─────────────┘   T0.7 staging site+freeze ┘
T0.5 hotfix on live site (no deps, only exception to the freeze)

T0.4 ─> T1.1 S2 ingest ─┬─> T1.0 reference sample (frozen) ─> T1.2 snow obs ─┬─> T1.4 gapfill
                        ├─> T1.3 RGB L1C                                       ├─> T1.7 past seasons masks (cache only)
                        │                                                      └─> T1.5 backfill obs ─> T1.6 daily ops (+ 7-day soak check)
T0.3 ─> T2.1 domain ─> T2.2 forcing study (needs T1.7) ─> T2.3 physics+assimilation ─> T2.4 calibration
        T2.4 + T1.5 ─> T2.5 model backfill (serial, from state) + daily ─> T2.6 validation page
T0.3 ─> T3.1 Cetursa ─> T3.2 DGT ; T3.1 ─> T3.3 bearings ─> T3.4 cones (needs T4.1)
T0.6 ─> T4.1 tokens+shell ─> T4.2 timeline (needs T0.3) ─> T4.3 layers ─> T4.4 panels ─> T4.5 mobile/a11y/perf
T1.6 + T2.5 ─> T5.1 monitoring ─> T5.3 runbook ─> T5.2 acceptance on staging ─> H5 ─> T5.4 go-live ─> T5.5 7-day live soak
```

Soak periods (7 days of daily runs) are never a builder waiting: the builder finishes the setup and reports; the coordinator schedules a check (an Orca automation, see `orchestration.md`) that wakes it 7 days later to run the soak verdict.

---

## P0 Foundations

### T0.1 Rules for a maintained product
- Lane A. Gate H1.
- Do: rewrite the "Critical rules" of `AGENTS.md` and `CLAUDE.md` for a maintained product:
  - real data only;
  - comments only for the non-obvious why;
  - libraries may be named;
  - Spanish UI copy;
  - every product through the catalogue;
  - the plan folder is the spec;
  - Darwin rule: agents commit only within the scope Mario granted in H0.
- Also update the stale parts: repo layout, state model, stack versions (MapLibre 6), and the hackathon roadmap marked as history.
- Accept: no rule left that contradicts this plan; layout section matches the tree.
- Evidence: diff; `tree -L 2` output.
- Gauntlets: G-Code.

### T0.2 Storage and access
- Lane A. Gate H2.
- Do: first check the org policy of `darwin-general-sandbox` for public access prevention and domain-restricted sharing, and report. Then prepare (and, once approved, run) the commands for:
  - buckets `nivosense-data` (prod) and `nivosense-staging`, europe-west1, uniform access, `allUsers` object read (they hold only public products);
  - CORS for the Pages origin, the staging site origin and localhost: methods GET and HEAD, request header `Range`, response headers exposed `ETag`, `Content-Range`, `Content-Length`, `Accept-Ranges`;
  - no lifecycle rule except 14 days on `nivosense-staging/_scratch/` (probes and per-branch trial runs);
  - two service accounts: a staging writer (object admin on staging only) and a prod writer (object admin on both);
  - a Workload Identity Federation pool and provider bound to `mariopeces/NivoSense`: any ref may impersonate the staging writer, only `assertion.ref == 'refs/heads/main'` the prod writer.
- Write it all in `docs/runbook.md`.
- Out: the buckets; GitHub variables `GCP_WIF_PROVIDER`, `GCP_SA_STAGING`, `GCP_SA_PROD`, `DATA_BUCKET`, `STAGING_BUCKET` (variables: not secret).
- Accept:
  - a job on a branch writes `nivosense-staging/_scratch/probe` and fails to write `nivosense-data`;
  - a job on `main` can write both;
  - from the Pages origin, an `OPTIONS` preflight with `Range` succeeds and a ranged GET returns 206 with `Content-Range` readable;
  - uploads are not gzip-encoded.
- Evidence: the probe job logs; the preflight and ranged GET output.
- Gauntlets: G-Infra.

### T0.3 Catalogue and publish
- Lane A. Needs T0.6 (T0.2 for the bucket write; build against a local folder first).
- Do: `pipelines/catalog/` with:
  - `schema.json` (JSON Schema);
  - `publish(layer, date, files, meta)`: writes the COG and the PMTiles (zoom 8 to 14 for 20 m and 10 m layers, 8 to 12 for 100 m) under content-addressed names `<date>-<hash>`, uploads them with long cache headers and no gzip encoding, then writes the entry object `catalog/entries/<layer>/<date>.json` (`Cache-Control: no-cache`);
  - `rebuild_index()`: the only writer of `catalog/index.json`, run in a workflow concurrency group `catalog`, with `ifGenerationMatch` and retry;
  - `promote(range)`: staging to prod (copies files and entries, then rebuilds the prod index);
  - one aligned grid per resolution in EPSG:32630.
- Catalogue fields per entry: `layer`, `date`, `status` (observed, gapfilled, modelled, forecast), `cog`, `pmtiles`, `bounds`, `crs`, `units`, `value_range`, `source_ids`, `input_key`, `pixel_hash`, `code_version`, `qa` (flags and scores), `created_at`.
- Accept:
  - schema validates;
  - publishing the same date twice with the same input key gives the same `pixel_hash` and reuses the same file names;
  - two concurrent publishes of different dates both end up in the index;
  - a crash between files and entry leaves the index unchanged.
- Evidence: unit tests including a simulated crash and a concurrency test; a sample `index.json`.
- Gauntlets: G-Infra, G-Data.

### T0.4 QA harness and regression fixtures
- Lane A. Needs T0.3.
- Do: `qa/` with:
  - `check_catalog` (every entry's files exist, COG valid, CRS EPSG:25830, nodata set, values in range, no missing daily dates for daily layers);
  - `render_thumbs` (a PNG per entry for visual review, used by G-Data);
  - `freshness` (SLOs F1 and F2);
  - regression fixtures, first one the 2026-11-19/20 crest case (Q4) with the S2 scene ids.
- Results are written as JSON to the run's summary and to `qa/` in the staging or prod bucket.
- Accept: harness runs in CI in under 10 minutes on a month of data; a broken COG and a missing day are both caught by tests.
- Evidence: CI log; a QA report JSON.
- Gauntlets: G-Data, G-Infra.

### T0.6 CI and tooling
- Lane A. Needs T0.1. Every later task needs it.
- Do:
  - `ci.yml` on `pull_request`: pytest, ruff, mypy on public functions, tsc, eslint (with a rule that bans hard-coded colours outside the tokens file), vitest, a frontend production build;
  - `pyproject.toml` for ruff and mypy settings;
  - a lockfile for the Python pipelines with GDAL, rasterio and the PMTiles builder pinned;
  - fix the snow-model cache key (today keyed on `run_id`, so it never hits exactly and grows).
- Accept: CI runs on a PR and fails on a lint error, a type error and a failing test (three trial commits); the full CI takes under 15 minutes.
- Evidence: the three failing runs and one green run.
- Gauntlets: G-Infra.

### T0.7 Staging site and production freeze
- Lane A. Needs T0.2, T0.6.
- Do:
  - a workflow that builds the frontend with the staging catalogue URL and publishes it to `nivosense-staging/site/` on every push to `main` and on demand for a PR (under `site/pr-<n>/`);
  - change `pages.yml` so the live site deploys only from a release tag (`v*`), not on every push or hourly; data refresh for the live site keeps working as today until go-live.
- Accept: a merge to `main` updates the staging site and not the live site; the live site keeps its daily data.
- Evidence: URLs and run links.
- Gauntlets: G-Infra.

### T0.5 Quick fixes on the current site
- Lane E. No deps. The only task that deploys to the live site before go-live (as a tagged hotfix release).
- Do:
  - the date bar shows "Sin escenas disponibles" when no scenes load (not an endless "Loading scenes");
  - the webcam ingest drops any image whose md5 matches a known provider placeholder and marks those cams offline;
  - `captured_at` stops trusting `Last-Modified` on placeholders.
- Accept: the live site no longer hangs on "Loading scenes"; no "IMAGEN NO DISPONIBLE" card shows as live.
- Evidence: Playwright screenshot of the live site after deploy.
- Gauntlets: G-UI (light).

## P1 Observation data

### T1.1 Sentinel-2 ingest
- Lane B. Needs T0.3.
- Do: `pipelines/s2/`:
  - search Earth Search `sentinel-2-c1-l2a` by the domain geometry (not the tile);
  - group by date and orbit;
  - compute the **domain** valid fraction from SCL inside the domain polygon, not `eo:cloud_cover`;
  - read B03, B11, B04, SCL, cloud probability by window, taking scale and offset from each asset's `raster:bands` (not from a processing baseline rule);
  - mosaic the 4 tiles;
  - record the scene ids;
  - mark a date "complete" only when every tile that covers the domain on that orbit is present;
  - reprocess incomplete dates on later runs.
- Accept:
  - for 2026-10-01 to 2026-11-21, the listed dates match an independent STAC query (no clear date missing: 2026-11-10 must be in, 2026-11-05 out for no coverage);
  - each date's domain coverage and valid fraction are recorded.
- Evidence: table date / tiles / coverage / valid fraction vs the independent query.
- Gauntlets: G-Data, G-Method.

### T1.0 Frozen reference sample
- Lane B, done by a labeller worker that never sees classifier code or output. Needs T1.1.
- Do:
  - pick at least 12 dates across 2025-26 (early season, storm, mid-winter, melt, late spring, and 2026-11-20);
  - draw at least 1,500 points stratified by snowline band (DEM), terrain shadow (sun angle), forest, cloud edge, open terrain;
  - label each point snow / no snow / cloud / unsure from the L1C true colour and a SWIR false colour (B11/B8/B4) chip;
  - write `qa/reference/snow_points.geojson` with the chips' scene ids, and freeze it (the file hash goes into the card's PR).
- Accept: G-Method relabels a random 10% blind and agrees on >= 90% (excluding "unsure").
- Evidence: the sample file, chip montage per stratum, the agreement table.
- Gauntlets: G-Method.

### T1.2 Observed snow cover
- Lane B. Needs T1.1, T1.0, T0.4. Optional gate H6.
- Do: `pipelines/snow_obs/` per the method in README section 6; classes snow / no snow / cloud / unknown + confidence; GLO-30 DEM snowline for LIS pass 2; terrain shadow from DEM and sun angles; forest flag.
- Accept:
  - Q1 against the frozen sample (per-stratum confusion matrices);
  - if H6 granted: agreement with Copernicus FSC 20 m reported on the same dates as a secondary check;
  - the 2026-11-20 crest shows bare ground except the ski resort.
- Evidence: confusion matrices per stratum and date, thumbnails.
- Gauntlets: G-Method, G-Data.

### T1.3 True colour RGB from L1C
- Lane B. Needs T1.1 (dates), T0.3.
- Do: `pipelines/rgb_l1c/`:
  - find the matching `sentinel-2-l1c` items per date;
  - read B04/B03/B02 JP2 by window through GDAL `/vsis3/` with unsigned requests (allow `.jp2` in `CPL_VSIL_CURL_ALLOWED_EXTENSIONS`; budget: under 10 minutes per date on a GitHub runner, measured);
  - mosaic and crop;
  - fixed snow-aware stretch (documented constants, same for all dates), 8-bit 10 m COG + PMTiles;
  - a requester-pays / CDSE fallback behind a flag, off by default.
- Accept:
  - every observation date has an RGB unless L1C is missing (logged);
  - snow not saturated (fewer than 1% of snow pixels at 255 in all bands);
  - RGB and snow masks align within one 20 m pixel.
- Evidence: thumbnails of 5 dates incl. one full-snow date; alignment check output.
- Gauntlets: G-Data, G-Method.

### T1.4 Gap-filled snow cover v1
- Lane B. Needs T1.2 (T2.x model probability is optional input; v1 must work without it).
- Do: daily filler per README section 6; outputs probability, class, days since observation.
- Accept: Q2 by cloud-mask transplant and hidden runs of 2 to 3 clear dates over the 2025-26 season, scored on pixels that change state within 10 days; no day missing; the latest days are labelled as extrapolated in the catalogue.
- Evidence: score table per test case; a timeline of daily snow area vs observed dates.
- Gauntlets: G-Method, G-Data.

### T1.5 Backfill observation layers
- Lane A. Needs T1.2, T1.3, T1.4, T0.2.
- Do:
  - workflow `backfill.yml`, `workflow_dispatch` with a date range, matrix by month, resumable;
  - run 2025-10-01 to today to the staging bucket;
  - after G-Data passes, the range is ready for promotion at go-live (T5.4).
- Accept: D1 and D2 for observation layers; rerunning one month changes nothing (D3).
- Evidence: QA report over the full range; run links.
- Gauntlets: G-Data, G-Infra.

### T1.6 Daily operations for observation layers
- Lane A. Needs T1.5.
- Do: replace `snow-observation.yml` with a daily job that processes the last 5 days, publishes, rebuilds the index, runs QA, and opens an issue on failure or SLO breach. The staging site no longer depends on Actions artifacts for these layers.
- Accept (merge): two consecutive daily runs green; a forced failure opens an issue.
- Accept (soak, checked 7 days after merge by the coordinator's scheduled check): F1 met every day.
- Evidence: run links and freshness JSON.
- Gauntlets: G-Infra.

### T1.7 Past seasons snow masks (cache only)
- Lane B. Needs T1.2.
- Do: run T1.1 and T1.2 for 2023-09-01 to 2025-09-30 into `nivosense-staging/_cache/snow_obs/` (not published in the catalogue), for the forcing study and calibration.
- Accept: every clear date of those seasons present, with the same QA as T1.2 (sampled).
- Evidence: date table vs independent STAC query.
- Gauntlets: G-Data.

## P2 Model

### T2.1 Domain: Natural Park, peripheral perimeter, National Park
- Lane C. Needs T0.3.
- Do: `pipelines/domain/build.py`:
  - download the official boundaries (REDIAM / Junta de Andalucia protected areas for the Parque Natural Sierra Nevada and its perimeter; MITECO or the national network for the National Park);
  - record source URLs, dates and licences;
  - build the union domain;
  - intersect the river sub-basins (keep their codes);
  - write `data/domain.geojson` and `data/basins.geojson` (and the frontend copy) from the script;
  - update `regions/sierra-nevada.json` bbox.
- Accept: polygons match the official layers (area within 0.5%); every sub-basin carries `source_area_km2` and `domain_area_km2`; nothing hand-edited.
- Evidence: map thumbnail with the three boundaries; areas table; source citations.
- Gauntlets: G-Data, G-Method.

### T2.2 Forcing study
- Lane C. Needs T2.1, T1.7.
- Do:
  - first deliverable, reported to the coordinator before any run: which forcing archives exist for 2023-09 to today (Open-Meteo archive per model, AEMET HARMONIE, ERA5-Land), at what resolution; ERA5-Land is the fallback;
  - run the current model with each available forcing over 2023-24 to 2025-26;
  - score snow presence against clear S2 dates by elevation band;
  - also compare precipitation against any open station data (AEMET OpenData stations in and around the massif);
  - recommend one forcing or a blend.
- Accept: the recommendation follows from the scores; the scores are reproducible from a script.
- Evidence: notebook-free script + results table + short write-up in `docs/method/forcing.md`.
- Gauntlets: G-Method.

### T2.3 Physics fixes and assimilation
- Lane C. Needs T2.2, T1.2.
- Do: per README section 6:
  - sublimation and wind scouring terms;
  - narrower rain-snow threshold prior;
  - assimilation on clear S2 dates (reweighting by band and sub-basin, zero-SWE direct insertion on confident bare ground, flagged insertion where S2 sees snow and the model does not);
  - median + probability outputs;
  - display threshold and colour scale;
  - ski resort polygon excluded from scores and marked.
- Hold out every fourth clear date from assimilation (the Q3 test set) and keep the forecast state before each update for scoring.
- Accept: Q3 and Q4 on 2025-26 (held-out dates and pre-update states only); unit tests for each new term; mass balance closes per cell and day: accumulation - melt - sublimation - scouring + assimilation increment = change in SWE, to 1e-6.
- Evidence: scores, mass balance test, before/after thumbnails for 2026-11-19.
- Gauntlets: G-Method, G-Data.

### T2.4 Calibration over three seasons
- Lane C. Needs T2.3.
- Do: recalibrate on 2023-24, 2024-25, 2025-26 with snow dates weighted; split by season (fit two, test one, rotate); publish parameter posteriors.
- Accept: test-season scores within 0.05 of fit-season scores (no overfit); Q3 holds on each test season.
- Evidence: calibration report `docs/method/calibration.md` + `regions/sierra-nevada.snow-calibration.json`.
- Gauntlets: G-Method.

### T2.5 Model backfill and daily run
- Lane A + C. Needs T2.4, T1.5.
- Do: SWE, depth and snow probability daily from 2025-10-01 through publish to staging, writing `state/<date>.npz` every day; the backfill runs as chained serial jobs (each resumes from the last stored state, well under the 6 h limit); the daily job runs after the observation job and starts from yesterday's state; promote after G-Data.
- Accept (merge): D1 to D3 for model layers (D3 by rerunning one date from the stored state of the day before); two consecutive daily runs green.
- Accept (soak, scheduled check 7 days later): F2 met every day.
- Evidence: QA report; run links.
- Gauntlets: G-Data, G-Infra.

### T2.6 Validation page
- Lane C + E. Needs T2.5.
- Do: a page in the site ("Metodo y validacion") with the method, scores per season, limits, and the ground references used; data from `qa/` in the bucket.
- Accept: every number on the page comes from a file; limits stated plainly.
- Evidence: screenshot, links to the source files.
- Gauntlets: G-Method, G-UI.

## P3 Webcams

### T3.1 Cetursa webcams
- Lane D. Needs T0.3, gate H4.
- Do:
  - add the feratel cams 15110 to 15114 from the resort's live page and `recursos.sierranevada.es/_extras/fotos_camaras/pradollano/snap_c1.jpg` to `backend/webcam_sources.json`;
  - store position, provider, credit, thumbnail and large URLs;
  - check every image at ingest (status, content type, size, placeholder md5);
  - set `status` live or offline with the real capture time from the image (EXIF or provider metadata) when available.
- Accept: every Cetursa cam that is live today shows as live with a correct age; credit line on each.
- Evidence: ingest log, catalogue JSON.
- Gauntlets: G-Data.

### T3.2 Live DGT cams only
- Lane D. Needs T3.1.
- Do: widen the DGT bbox to the new domain, keep only cams that pass the placeholder check, re-check every run; link the credit to the DGT page, not the raw XML.
- Accept: no placeholder card in the catalogue.
- Evidence: log listing kept and dropped cams.
- Gauntlets: G-Data.

### T3.3 Bearings and field of view
- Lane D. Needs T3.1.
- Do:
  - `backend/webcam_overrides.json` with `bearing_deg`, `fov_deg`, `range_km`, `elevation_m` per cam;
  - each bearing derived by matching named peaks and ridgelines visible in the image against a DEM viewshed rendered from the camera position (script `scripts/webcam_bearing.py` renders the expected skyline for candidate bearings and scores the match);
  - record the method and confidence per cam;
  - cams the method cannot settle are listed for Mario to confirm.
- Accept: each bearing has a rendered-skyline vs photo comparison image; confidence recorded; nothing guessed.
- Evidence: the comparison images.
- Gauntlets: G-Method (geometry), G-Data.

### T3.4 Map cones and cards
- Lane E. Needs T3.3, T4.1.
- Do:
  - camera icon rotated to the bearing;
  - view cone polygon built client-side from bearing, field of view and range;
  - hover highlights;
  - click opens the card with the large image, age, provider credit and an offline state.
- Accept: U4; matches the foto-webcam.eu behaviour in the G-UI rubric.
- Evidence: screenshots desktop and mobile.
- Gauntlets: G-UI.

## P4 Interface

### T4.1 Tokens and app shell
- Lane E. Needs T0.1.
- Do:
  - CSS variables for colour, type, spacing, radius and shadow, mapped into Tailwind `theme.extend`;
  - Inter loaded for body and one display face for headings;
  - remove inline hex classes and glow shadows;
  - shell after cedar-vista: dark 64 px icon rail (Nieve, Agua, Webcams, Meteo, Metodo) plus a 320 px light panel with eyebrow, title, subtitle and a collapse;
  - map controls restyled and moved to the rail foot (basemap, 3D terrain);
  - one icon set (consistent stroke).
- Accept: G-UI rubric sections A and B; no hard-coded colours left (lint rule).
- Evidence: screenshots; the lint rule output.
- Gauntlets: G-UI.

### T4.2 Timeline
- Lane E. Needs T4.1, T0.3.
- Do:
  - bottom-centred timeline built from `catalog/index.json`;
  - ticks styled per status (observed, gap-filled, modelled, forecast);
  - step and play;
  - keyboard arrows;
  - jump to latest;
  - calendar popover as secondary;
  - the URL keeps date and layer (shareable).
- Accept: scrubbing the whole year works; empty states honest; keyboard accessible.
- Evidence: screen recording or screenshots; axe report.
- Gauntlets: G-UI.

### T4.3 Layers panel and legends
- Lane E. Needs T4.2.
- Do:
  - layers panel with one row per layer;
  - inline legend with units and classes, opacity slider, info popover (source, resolution, date of the source scene, status);
  - PMTiles sources by date;
  - RGB under the snow layers.
- Accept: every layer in the catalogue reachable; legend values match the colour scales in the pipelines (shared constants file).
- Evidence: screenshots per layer.
- Gauntlets: G-UI, G-Data (legend vs data).

### T4.4 Basin and river panels
- Lane E. Needs T4.3, T2.5 (shows "pending" before).
- Do: move the chart cards into the panel; per sub-basin snow area, SWE and depth with this season vs last season; river flow as today; values from static JSON in the bucket.
- Accept: no overlay covering the map at 1440 px; charts readable at 375 px.
- Evidence: screenshots.
- Gauntlets: G-UI.

### T4.5 Mobile, accessibility, performance
- Lane E. Needs T4.1 to T4.4.
- Do: bottom-sheet panel under 768 px; focus order; contrast; lazy-load charts; image sizes.
- Accept: U2 and U3 on staging.
- Evidence: Lighthouse JSON, axe report, screenshots at 375 and 1440.
- Gauntlets: G-UI.

## P5 Production

### T5.1 Monitoring and cost
- Lane A. Needs T1.6, T2.5. Gate H3.
- Do: daily freshness and QA job that writes `qa/status.json` in the bucket (shown in the UI as a small status line) and opens or updates one issue per failing check; GCP budget alert at the H3 cap.
- Accept: P1, P3; a forced stale layer opens an issue within a day.
- Evidence: issue link from the forced test.
- Gauntlets: G-Infra.

### T5.2 Acceptance on staging
- Lane A. Needs everything above, including T5.3 and the T1.6 and T2.5 soak checks passed.
- Do: use the staging site (T0.7) against the staging bucket, run the full G-Product gauntlet.
- Accept: G-Product pass.
- Evidence: the G-Product report.
- Gauntlets: G-Product.

### T5.3 Runbook
- Lane A. Needs T5.1.
- Do: `docs/runbook.md` (rerun a date, backfill, promote, roll back a deploy, rotate access, add a webcam, recalibrate).
- Accept: G-Infra follows two procedures literally on staging and they work.
- Evidence: the two runs.
- Gauntlets: G-Infra.

### T5.4 Go-live
- Lane A. Needs T5.2, T5.3. Gate H5.
- Do: promote data to prod, switch the daily workflows to the prod writer, tag a release so Pages deploys the new site, run G-Product against the live URL.
- Accept: every D, Q and U line of README section 2 true on the live URL; rollback tested (previous tag redeploys).
- Evidence: G-Product live report.
- Gauntlets: G-Product.

### T5.5 Live soak
- Lane A. Needs T5.4. Scheduled check 7 days after go-live.
- Accept: F1, F2, F3 and P1 met on the live site for 7 days; any breach opened an issue.
- Evidence: freshness JSON for the 7 days; issue list.
- Gauntlets: G-Infra.
