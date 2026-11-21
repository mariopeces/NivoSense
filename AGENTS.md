# Agent Guide

Working notes for AI coding agents (Claude Code, Codex, Cursor, etc.) developing NivoSense. Read this before making changes.

## What is NivoSense

A public snow viewer for the Sierra Nevada (Spain): Natural Park, its peripheral protection perimeter and the National Park. It started at the Cassini Hackathon (April 2026) and is now maintained as a product. The production target is in [docs/plan/README.md](docs/plan/README.md); in short, past and present scenes from 2025-10-01 onwards for:

- **Observed snow cover** from Sentinel-2 L2A (20 m, every clear pass).
- **Gap-filled snow cover** (20 m, daily).
- **SWE and snow depth** from our own assimilating snow model (100 m, daily).
- **True colour** from Sentinel-2 L1C (10 m).
- **Webcams** (Cetursa / feratel and live DGT cams) and **weather forecasts** (GFS, ECMWF IFS, AEMET HARMONIE-AROME).
- **Per-basin panels**: snow area, SWE, depth and river flow.

## Critical rules

These are non-negotiable:

1. **The plan folder is the spec.** [docs/plan/](docs/plan/) holds the goal and definition of done (`README.md`), the task cards (`tasks.md`), the validation rubrics (`gauntlets.md`) and how the work is run (`orchestration.md`). Work from a card; do only what the card says. Anything else you find goes into the PR's "Found, not done" list. If this file and the plan disagree, the plan wins and this file gets fixed.

2. **Real data only.** Never invent basin names, values, dates, scene ids, camera positions or sample series. Empty states, skeletons and honest "Sin datos" messages are fine; fake data is not. Real data comes from real sources with their origin recorded, for example the pipelines, the catalogue in the bucket, `data/*.geojson` built by a script, region configs, provider metadata for webcams, or reference files a card names (such as `qa/reference/snow_points.geojson`).

3. **Every product goes through the catalogue.** Published products (their data files, COG and PMTiles, and their catalogue entries) are written only by `publish()` in `pipelines/catalog/` (task T0.3); `catalog/index.json` only by `rebuild_index()`, and staging to prod only by `promote()`. No other code writes product files or catalogue objects, and the frontend finds products only through `catalog/index.json`. Operational prefixes are not products and are written by their own workflow steps as their cards define: `_scratch/` (T0.2), `qa/` (T0.4), `site/` (T0.7), `_cache/` (T1.7) and `state/` (T2.5). Until T0.3 lands, the existing workflows keep running as they are, and no new product is added outside that path.

4. **Comments only for the non-obvious why.** Add a comment when there is a hidden constraint, a workaround or behaviour that would surprise a reader. Don't restate what the code says, and don't reference task numbers or commit ids in code.

5. **Libraries and sources may be named.** Name the libraries, data sources, papers and methods you use, in code, comments, docs and commits. Cite the source of every threshold or constant (paper, calibration run or measured value). Dependencies are pinned; a new one is justified in the PR.

6. **Spanish UI copy.** Everything the user reads on the site is in Spanish, in one language per screen (English may come later as an option). Code, identifiers, comments, commit messages and docs for developers stay in English.

7. **Commit only within the scope Mario granted (Darwin rule, gate H0).** In `mariopeces/NivoSense`, for this plan only, agents may commit to their own branch, push it and open a PR. Builders and gauntlets never push to `main` and never merge: the coordinator squash-merges after every required gauntlet passes. Release tags (`v*`) are pushed only by the coordinator, on a merged `main` commit, and only for the T0.5 hotfix and at go-live (T5.4). Today `pages.yml` still deploys the live site hourly and on every push; from T0.7 on the live site's code deploys only from a release tag (the T0.5 hotfix is the one exception before go-live), while its data refresh keeps working as today until go-live. Outside this repo and this plan, agents do not commit on Mario's behalf.

8. **No secrets, no messages on Mario's behalf.** No keys, tokens or personal data in code, logs, PRs or published files; GitHub Actions reach GCP only through Workload Identity Federation. Never send an email or message to a person for Mario; outreach is prepared as a Gmail draft only.

9. **No backwards-compat shims, no premature abstractions.** Three similar lines beat a generic helper. Refactor only when the next change becomes clearly easier. Bug fixes don't need surrounding cleanup.

10. **No emojis in code or commits** unless Mario asks.

## Stack

- **Frontend:** React 18, Vite 5, TypeScript 5, Tailwind CSS 3, MapLibre GL JS 6, Recharts 2. Static site on GitHub Pages; a staging build will be served from the staging bucket (T0.7).
- **Pipelines:** Python 3.11 package `pipelines/` (numpy, rasterio/GDAL, Pillow, jsonschema, eccodes), run by scheduled GitHub Actions workflows.
- **Data:** COGs for the archive and PMTiles for display, plus a JSON catalogue, in Google Cloud Storage (`nivosense-data` for prod, `nivosense-staging`; task T0.2). EPSG:32630, one aligned grid per resolution.
- **Backend:** FastAPI (`backend/main.py`) is not on the critical path of v1: everything the site needs is a static file. It is kept for local development and may return for v2 features (point queries, downloads).

## Repo layout

```
NivoSense/
├── AGENTS.md, CLAUDE.md          agent guidance (this file + Claude-specific extras)
├── README.md, ARCHITECTURE.md    project description and original technical design
├── ROADMAP.md, development_strategy.md, inventory_sierra_nevada.md
│                                 hackathon-era documents, kept as history
├── HANDOFF_CLAUDE.md             2026-10-18 agent handoff, superseded by this file, CLAUDE.md and docs/plan
├── docs/plan/                    the production plan: the spec agents work from
├── .github/workflows/            pages.yml, weather-forecasts.yml, snow-model.yml, snow-observation.yml
├── pipelines/                    Python package run by the workflows
│   ├── region.py, geo.py         region config loading and shared geometry helpers
│   ├── snow_model/               DEM, forcing, snowpack, ensemble, validation, outputs
│   └── weather_forecasts/        GFS, ECMWF, AEMET ingest and the forecast manifest
├── regions/                      sierra-nevada.json and its committed snow calibration
├── scripts/                      one-off and workflow helper scripts (snow observation fetch)
├── tests/                        unittest suites for the pipelines and scripts
├── backend/
│   ├── main.py                   FastAPI: /health, /layers, /observations, /predictions, /rivers, /basins
│   ├── ingest_webcams.py         webcam catalogue refresh (run by pages.yml)
│   ├── webcam_sources.json       webcam providers and cams
│   ├── build_basin_series.py     per-basin snow series
│   ├── layers.yaml, data/, tests/, Dockerfile, requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx               owns shared state, passes it down by props
│   │   ├── components/           Map, TopBanner, LeftRail, Legend, SnowLayerPicker,
│   │   │                         BasinChart, SnowVolumeChart, RiverFlowChart
│   │   └── lib/                  types, geo, icons, horizons, snowModel, snowObservation, weather
│   └── public/                   data/ (basins.geojson, webcams.json, snow-model/) and weather/
├── data/                         canonical GeoJSONs (basins, routes) and river flow series
├── ml/                           hackathon ML experiments; not in any workflow
├── deploy/                       hackathon-era Cloud Run / bucket setup (SETUP.md, cloudbuild)
├── assets/                       logo, brand board, mockup
└── spikes.png                    hackathon image, not referenced anywhere
```

## State model (frontend)

State lives in `App.tsx` and is passed down by props. No Zustand, no Context; add them only when prop drilling becomes painful. The main pieces:

| State | Notes |
|---|---|
| `selectedObservationDate` | The date shown on the map, picked in `TopBanner` from the observation and prediction scene lists. There is no free date picker: only dates that have a scene can be selected. Task T4.2 replaces this with a timeline built from `catalog/index.json`. |
| `layer`, `snowLayerId` | Which raster layer is on the map; drives `Legend`. Snow model layers come from `data/snow-model/manifest.json`. |
| `weatherManifest`, `weatherHorizon`, `weatherModelId`, `weatherVariable` | Weather forecast overlay; horizons are the fixed list in `lib/weather.ts`. |
| `hydrologicalYear` | Season shown in the basin charts (`lib/horizons.ts`). |
| `selectedBasinId`, `selectedRiverId` | **Bidirectional sync** between the map and the rail, see below. |
| `selectedWebcamId`, `webcams` | Webcam markers and card. |
| `railExpanded`, `statsOpen`, `routesOpen`, `webcamsOpen`, `waterTab` | Rail and accordion state. |
| `basinsFC`, `rivers`, `basinSeries`, `volumeSeries`, `flowSeries` | Fetched data, each with its own loading and error state. |

Basin selection from a map click and from the rail both go through `handleBasinSelect` in `App.tsx`, which also selects the matching river and opens the rail. Don't add a separate map-click path; the rail highlight would desync.

## MapLibre patterns

- **Re-add custom layers on `style.load`.** `setStyle` wipes custom sources and layers; `Map.tsx` adds them in its `style.load` handler (`addBasinsLayers`, `addWebcamLayers`).
- **Refs for stable handlers.** Layer event listeners that depend on props read them through a ref (`onBasinSelectRef` in `Map.tsx`).
- **Idempotent attachment.** A marker (`__basinClickAttached`) keeps click handlers from being registered twice.
- **Selection via filter.** Two layer pairs (base + selected) with `setFilter` instead of `feature-state`.

## Data pipelines and schedules

Today the site is static (GitHub Pages). Every product is produced by a scheduled GitHub Actions workflow, uploaded as an artifact, and restored by the publishing workflow. The plan moves products to the catalogue in the bucket (T0.3, T1.6, T2.5) and freezes the live site on release tags (T0.7).

| Workflow | Schedule (UTC) | Produces | Artifact |
|---|---|---|---|
| `pages.yml` | hourly, on push, and after the three below | webcam catalogue refresh, frontend build, deploy | the site |
| `weather-forecasts.yml` | 05:30, 11:30, 17:30, 23:30 | GFS, ECMWF IFS and AEMET HARMONIE-AROME precipitation and snowfall at 24/48/72/120 h | `weather-forecasts` |
| `snow-model.yml` | daily 07:40 | Sentinel-2 10 m snow and true colour, SWE and depth maps, basin snow volume | `snow-model` |
| `snow-observation.yml` | daily 05:35 | GFSC from CDSE, skipped without credentials | `snow-observation-<run id>` |

A scheduled run that fails opens or comments on a GitHub issue titled "Scheduled workflow failed: <name>".

Regions are described by `regions/<id>.json` (id, name, basins GeoJSON, optional `snow_model` settings). The weather and snow pipelines take `--region` and contain nothing specific to Sierra Nevada. To add a mountain range: add the file, run `Snow model` with mode `calibrate`, review the artifact, and commit it as `regions/<id>.snow-calibration.json`. The daily `operate` mode refuses to publish volumes and maps until a calibration passes its held-out gate.

Snow model today, in one paragraph: Copernicus GLO-30 elevation on a UTM grid snapped to Sentinel-2 pixels, Open-Meteo hourly IFS forcing downscaled with a lapse rate and precipitation gradient, a temperature-index snowpack with a radiation term, a Latin hypercube ensemble weighted against held-out Sentinel-2 snow cover at 10 m. Magnitudes of SWE and depth are not validated against in-situ data; the UI and manifest say so. The plan's P2 tasks (forcing study, physics fixes, assimilation, three-season calibration) change this.

## Dev workflow

### Frontend

```bash
cd frontend
npm install        # first time only
npm run dev        # http://localhost:5173
npm run build      # tsc + production build
npm run lint       # eslint; hard-coded colours outside the tokens file fail
npm test           # vitest
```

The lint rule `frontend/eslint/no-hard-coded-colour.js` bans colours (hex, `rgb()`/`hsl()` and the other CSS colour functions, and named colours in CSS) in `src/` and `tailwind.config.js`, except in `src/styles/tokens.css`. Colours that predate the tokens file are listed value by value and file by file in `frontend/colour-baseline.json`: a new, moved or swapped colour fails, and so does a baseline entry whose colour is gone (delete the entries the rule reports).

### Pipelines and tests

```bash
python -m venv .venv
source .venv/Scripts/activate    # Git Bash on Windows
pip install --require-hashes -r pipelines/requirements-dev.lock   # Linux x86_64; elsewhere: pip install -r pipelines/requirements-dev.in
ruff check .
mypy
pytest
```

Dependencies are pinned with hashes in `pipelines/requirements.lock` (workflows) and `pipelines/requirements-dev.lock` (CI tools); edit the `.in` files and regenerate both with the `uv pip compile` commands at the top of `pipelines/requirements.in`.

`ci.yml` runs on every pull request: ruff, mypy and pytest, then tsc, eslint, vitest and the production build of the frontend.

### Backend (local, optional)

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8080
```

## Common tasks

### Wiring a new GeoJSON layer

1. Produce the file with a script (never by hand) at `data/{name}.geojson` and copy it to `frontend/public/data/{name}.geojson`; the two must stay identical.
2. In `App.tsx`, fetch it in a `useEffect` and keep it in state, like `basinsFC`.
3. In `Map.tsx`, add a source and layers in an `add...Layers` helper called from the `style.load` handler.
4. Pass the selected id and the select callback through props to `LeftRail`.

### Adding a sidebar nav item

1. Add the item in `LeftRail.tsx` with an icon from `lib/icons.tsx`.
2. Lift its state to `App.tsx`.
3. If it opens a panel, follow the accordion pattern (`expandable` plus conditional children).

### Visual changes

The visual system is being replaced by design tokens (task T4.1) and is checked by the G-UI rubric in `docs/plan/gauntlets.md`: colours, type, radius and shadow from tokens only, no text under 12 px, no all-caps blocks with wide tracking, no glow and no glassmorphism over the map. Don't add new inline hex colours or glow shadows.

## Things to avoid

- **Adding state to a component that only the parent reads or writes.** Lift it to `App`.
- **Hard-coding sample basins, routes, scenes or stats.** Empty states are correct.
- **Fetching from external APIs at runtime in the site.** Pipelines fetch and publish; the site reads static files.
- **GCP and other outside actions beyond the plan.** Cloud resources and tooling outside the repo are allowed when a card needs them, under gate H2 and Mario's advance OK in [docs/plan/README.md](docs/plan/README.md) section 4: NivoSense resources go in `darwin-general-sandbox` first; if its org policy blocks the plan, never change the policy: pick the cleanest alternative (another Darwin project that allows it, or a dedicated project) and record why; record every command in `docs/runbook.md`; never message a person on Mario's behalf; never commit secrets. Resources other workloads use are not modified.
- **Markdown files nobody asked for.** Write docs only when a card names them (for example `docs/runbook.md`, `docs/method/*.md`) or Mario asks.

## Pointers

- [docs/plan/README.md](docs/plan/README.md): goal, definition of done, decisions, human gates.
- [docs/plan/tasks.md](docs/plan/tasks.md): task cards.
- [docs/plan/gauntlets.md](docs/plan/gauntlets.md): validation rubrics.
- [docs/plan/orchestration.md](docs/plan/orchestration.md): how the work is run.
- [README.md](README.md): public project description.
- [ARCHITECTURE.md](ARCHITECTURE.md): original hackathon technical design (superseded by `docs/plan/README.md` section 5 where they differ).
- [ROADMAP.md](ROADMAP.md): the hackathon weekend timeline, kept as history.
- [data/README.md](data/README.md): GeoJSON schema for basins and routes.
- [ml/README.md](ml/README.md): hackathon ML contract.
