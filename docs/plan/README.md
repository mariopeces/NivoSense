# NivoSense production plan

Status: draft for approval, 2026-11-21. Owner: Mario Peces. Repo: `mariopeces/NivoSense` (personal repo for now; the org repo `darwin-geospatial/project-nivosense` is not touched by this plan).

This folder is the working spec that the build agents and the validation agents (gauntlets) follow. Four files:

| File | What it holds |
|---|---|
| `README.md` (this file) | Goal, definition of done, decisions, target architecture, phases, human gates |
| [`tasks.md`](tasks.md) | Every task as a card: inputs, outputs, acceptance criteria, evidence, dependencies |
| [`gauntlets.md`](gauntlets.md) | The validation agents, their rubrics and the loop that sends work back until it passes |
| [`orchestration.md`](orchestration.md) | How the coordinator runs this in Orca: runs, workers, worktrees, merges, escalation |

## 1. Goal

A public, 100% working NivoSense in production for the Sierra Nevada Natural and National Park, that shows **past and present scenes** (rolling history from 2025-10-01, the start of hydrological year 2025-26, to today, kept forever from then on) for these layers:

| Layer | Source | Resolution | Cadence |
|---|---|---|---|
| Observed snow cover | Sentinel-2 L2A (Earth Search `sentinel-2-c1-l2a`, AWS, no credentials), NDSI with the Theia/LIS two-pass method, SCL + cloud probability mask, DEM snowline | 20 m | every clear S2 pass (about every 2.5 days, visible about 8 h after the pass) |
| Gap-filled snow cover | Observed snow cover filled in time (v1: bracketing observations + persistence with age + snowline + model probability; v2: adds Landsat 8/9 and Copernicus GFSC as cross-check) | 20 m | daily |
| SWE | Own snow model on a 100 m grid, ensemble, with assimilation of the observed snow cover | 100 m | daily |
| Snow depth | Same model, SWE divided by modelled density | 100 m | daily |
| True colour RGB | Sentinel-2 **L1C** (Earth Search `sentinel-2-l1c`, B04/B03/B02 JP2 on AWS), own snow-aware stretch | 10 m | every S2 pass with the massif covered |
| Wet snow (v2, optional) | Sentinel-1 RTC (Microsoft Planetary Computer, free anonymous token), change detection at -3 dB | 20 m | about 6 days |
| Webcams | Cetursa ski resort cams (feratel, permission granted, non-profit) + live DGT cams | live | provider refresh |
| Weather forecasts | Existing pipeline (GFS, ECMWF, AEMET) | as today | 4 runs/day |

## 2. Definition of done (production)

The platform is "done" when the final acceptance gauntlet (G-Product, see `gauntlets.md`) passes on the **live URL** and every line below is true with evidence:

Data and history
- D1. The catalogue (`catalog/index.json`) lists every date from 2025-10-01 to yesterday for gap-filled snow cover, SWE and depth (no missing day), and every S2 date where the massif is at least 30% covered and valid for observed snow cover and RGB.
- D2. Every listed product opens on the site and its file exists, is a valid COG with the right CRS (EPSG:32630, the native Sentinel-2 UTM zone the pipelines already use; one aligned grid per resolution), nodata and value range.
- D3. Backfill and daily runs are idempotent: rerunning a date with the same input key (source scene ids, processing baseline, code version, and for the model the stored state of the day before) gives the same pixel hash; timestamps and `created_at` are excluded. GDAL, rasterio and the PMTiles builder are pinned in a lockfile.

Freshness (SLOs, checked daily by the freshness monitor)
- F1. A clear S2 pass appears on the site within 24 h of being listed on Earth Search.
- F2. Daily model and gap-filled layers for yesterday are live by 10:00 Europe/Madrid.
- F3. Every webcam card shows the real image age; a dead feed shows "offline", never a fresh-looking placeholder.

Quality (checked by G-Method and G-Data)
- Q1. Observed snow cover vs a frozen reference sample (task T1.0): at least 1,500 points over at least 12 dates, stratified by snowline band, terrain shadow, forest, cloud edge and open terrain, labelled on true colour plus SWIR false colour (B11/B8/B4) so snow and cloud can be told apart. Snow F1 >= 0.85 overall and >= 0.70 in every stratum; the per-stratum confusion matrices are published. Copernicus FSC 20 m is a secondary comparison only (same sensor and a similar method, so not independent).
- Q2. Gap-filled snow cover, scored by cloud-mask transplant: real cloud masks from cloudy dates are laid on clear dates, and runs of 2 to 3 consecutive clear dates are hidden. Scored only on pixels that change state within 10 days of the date (the hard ones), snow season only: snow F1 >= 0.75. When the model probability is an input, the model run used has those dates withheld from assimilation.
- Q3. Model snow presence (SWE > 5 mm) scored on clear S2 dates **withheld from assimilation** (every fourth clear date held out) and on the model's forecast state before each assimilation update: overall accuracy >= 0.85; area where the model shows snow and S2 sees bare ground < 10% of the modelled snow area. Thresholds are reviewed by G-Method after T2.2 with the first real scores; they can only go up without Mario.
- Q4. Regression case: 2026-11-19/20, crest Veleta to Mulhacen (lon -3.42 to -3.30, lat 37.01 to 37.07), scored on the model state **before** the 20 Nov update and on 21 to 25 Nov: no snow outside the ski resort where S2 sees bare ground.
- Q5. SWE and depth are checked against every reachable ground reference (ERHIN reports, Poqueira / UCO-UGR data if shared, Cetursa snow reports for the resort) and the results are published on a validation page with the method and its limits. No claim of accuracy beyond what the validation shows.

Platform
- P1. All daily workflows green for 7 consecutive days; any failure or SLO breach opens a GitHub issue automatically.
- P2. No secrets in the repo; GitHub Actions reach GCP only through Workload Identity Federation.
- P3. Monthly cloud cost estimated and under the budget Mario sets (proposed: < 20 EUR/month).
- P4. Runbook in `docs/runbook.md`: how to rerun a date, backfill a range, roll back a deploy, rotate access.

Interface (checked by G-UI)
- U1. The redesign follows the cedar-vista pattern (dark icon rail + light collapsible panel, tokens, inline legends with opacity, bottom timeline) and passes the G-UI rubric.
- U2. Lighthouse, median of 3 runs: desktop preset performance >= 80, mobile preset >= 55 (WebGL map, headless); accessibility >= 95 and best practices >= 95 on both. Map initialised after the shell renders.

Where each line is checked: D, Q and U lines on staging first (T5.2) and again on the live URL (T5.4); F and P1 lines on staging during the soak and on the live URL during the 7 days after go-live (T5.5).
- U3. Works at 375 px wide and at 1440 px; no console errors; one language (Spanish, with English as a later option).
- U4. Webcams appear on the map as an icon plus a view cone pointing where the camera looks (like foto-webcam.eu), and the card shows the large image, its age and the provider credit.

## 3. Decisions taken

| # | Decision | Date | By |
|---|---|---|---|
| 1 | Work in the personal repo `mariopeces/NivoSense` for now | 2026-11-21 | Mario |
| 2 | RGB from Sentinel-2 L1C (not the L2A `visual`) | 2026-11-21 | Mario |
| 3 | Cetursa webcams may be used (non-profit collaboration); credit Cetursa / feratel on every card | 2026-11-21 | Mario |
| 4 | Observed snow cover from S2 L2A on AWS, not GFSC behind credentials | 2026-11-21 | Mario |
| 5 | Domain: Sierra Nevada Natural Park including the peripheral protection perimeter, plus the National Park | 2026-11-21 | Mario |
| 6 | SWE and depth come from our own assimilating model; no S1 snow-depth product (none valid for a thin, wet Mediterranean snowpack) | 2026-11-21 | proposed, see README section 6 |
| 7 | UI reference: cedar-vista (same stack); OpenPAS for the light card style | 2026-11-21 | proposed |

## 4. Human gates

Answers given by Mario on 2026-11-21 ("agree with everything suggested, be fully autonomous"):

| Gate | Answer |
|---|---|
| H0 | Yes: agents commit to branches, push, open PRs and squash-merge to `main` of `mariopeces/NivoSense` once every required gauntlet passed. Scope: this repo and this plan only. |
| H1 | Yes: replace the hackathon rules (T0.1). |
| H2 | Yes: the agent checks the org policy, then creates the buckets, service accounts and Workload Identity Federation in `darwin-general-sandbox` itself, recording every command in `docs/runbook.md`. If the org policy blocks public buckets, stop and ask. |
| H3 | 20 EUR/month. |
| H4 | Credit line "Imagen: Cetursa Sierra Nevada / feratel"; stills only. |
| H5 | Still Mario's: go-live waits for his explicit OK after G-Product passes on staging. |
| H6 | Recommended, but only Mario can create the account; until the secrets exist, run without it. |

Original gate definitions:

These are human gates (H-gates). The coordinator stops and asks Mario; agents never decide them.

| Gate | Question | Default if Mario agrees | Blocks |
|---|---|---|---|
| H0 | Agents may commit to branches, push, open PRs and merge to `main` of `mariopeces/NivoSense` after the gauntlets pass? (Darwin rule: agents never commit for the person, so this needs an explicit, durable yes for this repo and this run only.) | Yes for branches + PRs; merges to `main` only after all gauntlets pass; deploy to production stays H5 | everything |
| H1 | Retire the hackathon rules in `AGENTS.md` ("fresh code only", never name libraries, no comments)? They conflict with a maintained product. | Replace with the rules in `tasks.md` T0.1 | T0.1 |
| H2 | GCP home for data: two public-read buckets `nivosense-data` (prod) and `nivosense-staging` in `darwin-general-sandbox` (europe-west1), two service accounts and a Workload Identity Federation pool for GitHub Actions. First check: does the org policy of that project allow `allUsers` read (public access prevention, domain-restricted sharing)? If not, pick another project. Mario creates it or approves the agent running the exact commands. | Agent prepares the commands in `docs/runbook.md`, Mario runs or approves them | T0.2 and all publishing |
| H6 | A free Copernicus Data Space account for the FSC cross-check (T1.2) and the L1C fallback (T1.3): Mario creates it and adds `CDSE_CLIENT_ID` / `CDSE_CLIENT_SECRET` as repo secrets | Optional: without it Q1 uses only the reference sample and the L1C fallback stays off | T1.2 secondary check |
| H3 | Monthly budget cap | 20 EUR | T5.1 |
| H4 | Cetursa: written OK on the image URLs and redistribution (stills only, no video), and the exact credit line | Use the feratel stills with "Imagen: Cetursa Sierra Nevada / feratel" | T3.1 |
| H5 | Go live: switch the production site to the new build and data | After G-Product passes on staging | T5.4 |

## 5. Target architecture

```
Earth Search (AWS)          Open-Meteo / AEMET        Cetursa (feratel) + DGT
S2 L2A COGs, S2 L1C JP2,    forcing + forecasts       webcam stills
Copernicus DEM, Landsat
          |                         |                          |
          v                         v                          v
  GitHub Actions (public repo, free minutes): one Python package `pipelines/`
    s2_ingest -> snow_obs -> gapfill        rgb_l1c          webcams
                     \         |                |               |
                      +--> snow_model (ensemble + assimilation) |
                               |                                |
                         publish (COG + PMTiles + catalog entry, idempotent per date)
                               |
                               v
     GCS nivosense-data (prod) and nivosense-staging, public read, CORS with Range
       catalog/entries/<layer>/<date>.json   one object per product (no shared writes)
       catalog/index.json                    rebuilt from entries in one serialised step
       layers/<layer>/<yyyy>/<date>-<hash>.tif       COG archive (content-addressed)
       tiles/<layer>/<date>-<hash>.pmtiles           display (content-addressed, never overwritten)
       state/<date>.npz                      model and ensemble state, for restart and reruns
       site/                                 staging build of the frontend (staging bucket only)
                               |
                               v
   Frontend (React + MapLibre + pmtiles protocol), static
   prod on GitHub Pages; staging served from nivosense-staging/site/
   reads catalog/index.json, builds the timeline, streams PMTiles by range
```

Key choices and why:
- **COG for the archive, PMTiles for display.** COGs keep full-precision values for analysis and downloads; one PMTiles per layer and date gives fast tiles from a plain bucket with no tile server (cedar-vista already uses the pmtiles protocol). A year of 20 m and 100 m layers over the massif is a few GB: cheap in GCS, too big for GitHub Pages (1 GB) or Actions artifacts (14-day retention, the cause of today's lost history).
- **No server in v1.** The FastAPI backend and Cloud Run stay out of the critical path; everything the site needs is a static file. The backend can come back for v2 features (point queries, downloads).
- **Catalogue as the contract.** `catalog/index.json` (JSON Schema in `pipelines/catalog/schema.json`) is the only thing the frontend trusts: per layer, the list of dates, the file paths, the product status (observed, gap-filled, modelled, forecast), the source scene ids and the quality flags.
  - Every pipeline writes through one `publish()` function: data files first (content-addressed, never overwritten, so caches and range reads never mix versions), then its own entry object. Parallel jobs never touch the same object.
  - A single serialised step (workflow concurrency group `catalog`) rebuilds `index.json` from the entries, with `ifGenerationMatch` and retry.
  - Catalogue objects carry `Cache-Control: no-cache`; data files are immutable and cache for a year.
- **Staging before production.** Branches and `main` publish to the staging bucket until go-live; a staging build of the site is served from `nivosense-staging/site/`. G-Data, G-UI and G-Product run against staging. Promotion copies a validated date range to prod. The live Pages site is frozen on the current version (deploys only from a release tag) until go-live, except the T0.5 hotfix.
- **Idempotent by date.** Every observation step is `run(date) -> outputs`, safe to rerun, keyed on inputs (scene ids, processing baseline, code version). The daily workflow reprocesses the last 5 days so late-arriving S2 tiles complete a mosaic (today's bug: masks cached by date before all tiles existed). The model carries state from day to day, so it stores `state/<date>.npz` and reruns from the day before, never month-parallel.
- **Access.** Two service accounts through Workload Identity Federation: a staging writer (any ref of the repo) and a prod writer (only `refs/heads/main`). No keys.

## 6. Method (summary; details and references in `tasks.md`)

Observed snow cover (T1.2)
- All four tiles that touch the domain (30SVF, 30SVG, 30SWF, 30SWG), mosaicked per date and orbit.
- Cloud filtering on the **domain**, never on the tile: the tile-level `eo:cloud_cover < 40` filter is what dropped the clear 10 Nov scene.
- NDSI = (B03 - B11)/(B03 + B11) at 20 m, reflectance with the c1 offset applied. Theia/LIS two-pass: pass 1 NDSI > 0.4 and red > 0.2; pass 2 NDSI > 0.15 and red > 0.04 above the snowline found from the DEM.
- Cloud: SCL 8, 9, 10 plus cloud shadow 3, with the bright-snow fix (pixels SCL calls cloud with NDSI > 0.4 and low cloud probability are kept as snow).
- Terrain shadow from the DEM and the sun angle is "unknown", not "no snow". Forest flagged as low confidence.
- Output classes: snow, no snow, cloud, unknown (shadow, nodata), plus a confidence band.

Gap-filled snow cover (T1.4)
- Daily per pixel. If observed today: use it.
- Else if the last and next clear observations agree: carry that value.
- Else (they disagree, or there is no next one yet, as on the latest days): decide from the elevation and aspect snowline of the nearest clear dates and the model's snow probability.
- Output: snow probability 0 to 1, class, and "days since a real observation".
- Validated by hiding each clear date in turn (Q2).

SWE and depth (T2.x)
- Domain: Natural Park + peripheral protection perimeter + National Park, sub-basins re-intersected by a script (none exists today; `data/basins.geojson` was clipped by hand to ES610002).
- Forcing: compare ECMWF IFS (today), AEMET HARMONIE and ERA5-Land against S2 snow cover over past seasons, and keep the best (or a blend). Temperature lapse rate and precipitation gradient stay calibrated parameters.
- Physics fixes: sublimation and wind scouring terms on exposed crests (both missing today), and the rain-snow threshold range narrowed with evidence.
- Assimilation:
  - on every clear S2 date, ensemble members are reweighted per elevation band and sub-basin by their agreement with the observation;
  - where S2 sees bare ground with high confidence, SWE is set to zero (direct insertion);
  - where S2 sees snow and the model has none, a minimum SWE is inserted and flagged.
- This is what makes the 19 Nov crest error impossible.
- Display: ensemble median and the probability of snow, not the weighted mean. Values under 5 mm drawn as transparent, colour scale that does not make trace snow look like solid cover.
- Calibration over at least three seasons (2023-24, 2024-25, 2025-26), with snow dates weighted so the summer bare dates do not dominate (today half the fit dates were snow-free).
- Ski resort: artificial snow is out of the model's reach. The resort polygon is marked on the map and excluded from the scores.

RGB L1C (T1.3)
- B04/B03/B02 JP2 read with GDAL from `s3://sentinel-s2-l1c` (unsigned access worked on 2026-11-21; if the bucket turns requester-pays again, the fallback is the CDSE S3 endpoint, gate H6).
- JP2 is not cloud-optimised: windowed reads are slow, so the card sets a time budget per date and the backfill parallelises by month. The existing GDAL settings allow only `.tif` (`CPL_VSIL_CURL_ALLOWED_EXTENSIONS`); the L1C reader needs `.jp2` too.
- Cropped to the domain, 10 m COG, with a stretch fitted for snow (TCI saturates on snow) and gamma, applied the same way on every date so dates compare.

## 7. Phases

| Phase | Content | Exit criterion | Rough effort (agent time) |
|---|---|---|---|
| P0 Foundations | rules, storage, catalogue, publish, QA harness, quick fixes | the site shows "no scenes" honestly; staging bucket + catalogue + QA harness work end to end with one real date | 2 to 3 days |
| P1 Observation data | S2 ingest, snow cover, L1C RGB, gap-fill v1, backfill since 2025-10-01, daily ops | D1 to D3 and F1 for observation layers; Q1 and Q2 pass | 1 to 1.5 weeks |
| P2 Model | domain, forcing study, physics, assimilation, calibration, backfill, validation page | Q3 to Q5 pass; F2 | 2 to 3 weeks |
| P3 Webcams | Cetursa ingest, live DGT filter, bearings, cones, offline state | U4, F3 | 3 to 5 days, parallel with P1 |
| P4 Interface | tokens, shell, timeline, layers, webcams, charts, mobile, a11y | U1 to U3 on staging | 1.5 to 2 weeks, parallel with P1 and P2 |
| P5 Production | monitoring, alerts, runbook, acceptance, go-live | all of section 2 on the live URL | 3 to 5 days |

Dependencies and the parallel lanes are in `tasks.md`. Total: about 4 to 6 weeks of agent time with three lanes in parallel, gated by human answers to H0 to H5.

## 8. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| L1C bucket becomes requester-pays | RGB stops | CDSE S3 fallback behind a flag; RGB is the only layer that depends on L1C |
| Snow/cloud confusion, winter terrain shadow | false snow or holes | LIS two-pass, shadow as unknown, Q1 check against Copernicus FSC |
| No open ground truth for SWE | SWE accuracy unknown | publish validation honestly (Q5); ask UCO/UGR (Polo, Pimentel, Herrero) and ERHIN for data; Cetursa snow reports |
| Forcing bias (9 to 11 km grids on a 3,400 m range) | wrong accumulation | forcing study T2.2; assimilation bounds the error on every clear date |
| Agents drift or rubber-stamp their own work | silent low quality | gauntlets run in fresh context with rubrics and real evidence, different roles, max 3 loops then human |
| GitHub Actions 6 h job limit for backfill | backfill fails | observation layers: matrix by month, resumable by date; model: chained serial jobs that resume from `state/<date>.npz` |
| Forcing archives (AEMET HARMONIE, IFS before 2024) may not exist for past seasons | forcing study incomplete | archive availability is the first output of T2.2; ERA5-Land is the fallback |
| Cost creep | budget | budget alert T5.1, PMTiles only for the zoom range used |
