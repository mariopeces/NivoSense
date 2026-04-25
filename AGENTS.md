# Agent Guide

Working notes for AI coding agents (Claude Code, Codex, Cursor, etc.) helping develop NivoSense. Read this before making changes.

## What is NivoSense

Real-time snow cover viewer for mountain ranges (starting with Sierra Nevada, Spain), built for the **Cassini Hackathon**. The product visualizes:

- **Now** — current observed snow cover (NDSI from Sentinel-2).
- **Forecasts** — predicted snow cover at +24h, +48h, +72h, +7d, +1mo from an ML model.
- **Stats per basin** — % coverage and trend (this year vs. multi-year average) per hydrographic sub-basin.
- **Snow routes** — classic ski touring / snowshoe routes intersected with the active layer to show which segments are skiable.

Read [README.md](README.md), [ARCHITECTURE.md](ARCHITECTURE.md) and [ROADMAP.md](ROADMAP.md) for full context.

## Critical rules

These are non-negotiable:

1. **Hackathon "fresh code only" constraint.** Every line in this repo must look like it was written this weekend during the hackathon. **Never** reference external repositories, libraries-by-name, or prior implementations in code, comments, commit messages, or docs. Patterns may be borrowed, but the implementation is always written from scratch in this repo.

2. **No hardcoded data.** Do not invent basin names, route names, snow coverage values, or sample series. Empty states and skeletons are fine; fake data is not. Real data flows from `data/*.geojson`, the backend API, or pre-computed JSONs in the bucket.

3. **No backwards-compat shims, no premature abstractions.** Three similar lines beats a generic helper. Refactor only when the next change becomes clearly easier. Bug fixes don't need surrounding cleanup.

4. **Default to no comments.** Only add a comment when the *why* is non-obvious (a hidden constraint, a workaround, behavior that would surprise a reader). Don't restate what code already says. Don't reference task numbers or commit IDs.

5. **No emojis in code or commits** unless the user explicitly asks.

## Stack

- **Frontend:** React 18 + Vite 5 + TypeScript + Tailwind 3 + MapLibre GL JS 4 + Recharts.
- **Backend:** Python 3.11 + FastAPI + rio-tiler (when integrated). Single `main.py` until it grows organically.
- **Data:** COGs (NDSI), GeoJSONs (basins, routes), JSON time series — all in **Google Cloud Storage**.
- **Infra:** Cloud Run (backend) + GCS (data + frontend hosting) + Artifact Registry, region `europe-west1`.

## Repo layout

```
NivoSense/
├── README.md, ARCHITECTURE.md, ROADMAP.md, development_strategy.md
├── AGENTS.md, CLAUDE.md            ← agent guidance (this file + Claude-specific)
├── backend/
│   ├── main.py                     FastAPI: /health, /layers
│   ├── layers.yaml                 forecast horizon manifest
│   ├── requirements.txt            rio-tiler etc. commented until wired
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx                 owns shared state (horizon, selectedBasinId, etc.)
│   │   ├── components/             Map, TopBanner, LeftRail, BasinChart, Legend, BasemapSwitcher
│   │   └── lib/
│   │       ├── horizons.ts         single source of truth for forecast horizons
│   │       ├── icons.tsx           inline SVG icons
│   │       ├── geo.ts              bbox + name helpers
│   │       └── types.ts            Basin, Route, CoverageSeriesPoint
│   └── public/data/                GeoJSONs served at /data/*.geojson during dev
├── data/                           canonical GeoJSON sources (basins, routes)
├── deploy/                         cloudbuild.yaml, deploy-web.sh, SETUP.md
└── ml/                             Joan's domain — training & inference, NOT in deploy pipeline
```

## State model (frontend)

State lives in `App.tsx` and is passed down by props. No Zustand, no Context. Add them only when prop drilling becomes painful (current size doesn't justify it).

| State | Type | Owner | Notes |
|---|---|---|---|
| `horizon` | `HorizonId \| null` | App | Single source of truth for time. `null` = today. Date display is computed. |
| `railExpanded` | `boolean` | App | Auto-expands on nav item click via `onExpand`. |
| `layer` | `'cover' \| 'change'` | App | Drives map raster layer + Legend gradient. |
| `statsOpen` / `routesOpen` | `boolean` | App | Accordion in LeftRail. |
| `selectedBasinId` | `string \| null` | App | **Bidirectional sync**: clicked from map polygon OR from accordion list. |
| `basinsFC` | `FeatureCollection \| null` | App | Fetched once at mount from `/data/basins.geojson`. |

Bidirectional sync notes:
- Click on a basin polygon in `Map` → `onBasinSelect` callback → App → propagates to LeftRail (highlights that item) AND auto-opens the accordion / expands the rail if needed.
- Click in LeftRail accordion → same handler → App → propagates to Map (highlights polygon, fits bounds).

## MapLibre patterns

- **Basemap switching wipes custom layers.** `setStyle` resets everything. Re-add custom sources/layers in the `style.load` event handler. See `Map.tsx` `addBasinsLayers()`.
- **Refs for stable handlers.** When attaching layer event listeners that depend on props (e.g., `onBasinSelect`), use a ref so the captured value is always fresh. See `onBasinSelectRef` in `Map.tsx`.
- **Idempotent attachment.** Use a marker (`__basinClickAttached`) reset on `style.load` to avoid double-registering click handlers across basemap changes.
- **Selection via filter, not feature-state.** Two layer pairs (base + selected) with `setFilter` is more reliable than `feature-state` for simple highlighting.

## Data architecture (forward-looking)

Three data tiers, all in `gs://nivosense-cogs/`:

```
observations/sierra-nevada/{YYYY-MM-DD}.tif    past observations from Sentinel-2/HRWSI
forecasts/sierra-nevada/
  latest/                                       always points to current run
    manifest.json                               run metadata, horizon → COG mapping
    ndsi_{horizon}.tif                          5 horizons (plus24h, plus48h, plus72h, plus7d, plus1m)
  archive/{YYYY-MM-DD}/                         optional, for evaluating model over time
static/sierra-nevada/
  basins.geojson, routes.geojson
  basins/{id}/series.json                       pre-computed coverage time series per basin
```

Pipeline ingests from CDSE / HRWSI **at build time**, never at runtime. Backend serves tiles via `rio-tiler` (or, as a fallback, frontend uses TiTiler's public endpoint or pre-rendered tiles from the bucket). See [ARCHITECTURE.md](ARCHITECTURE.md) and [ml/README.md](ml/README.md).

## Time / horizon model

The `horizon` state has 6 values: `null` (today/nowcast) + 5 forecast IDs. **No arbitrary dates.** The date arrows in `TopBanner` step through this list — there is no way to land on, say, "today + 5 days" because that doesn't correspond to any model output. See `lib/horizons.ts`.

If a future horizon is added (e.g., `plus2m`), update `lib/horizons.ts` AND `backend/layers.yaml` together.

## Dev workflow

### Frontend

```bash
cd frontend
npm install        # first time only
npm run dev        # http://localhost:5173
```

Vite has HMR. State + style changes propagate live. On structural changes (adding new components, dependency changes), check the dev server log for errors.

### Backend (local)

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate    # Git Bash on Windows
pip install -r requirements.txt
uvicorn main:app --reload --port 8080
```

Test:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/layers
```

### Backend (Docker)

```bash
cd backend
docker build -t nivosense-api:local .
docker run -p 8080:8080 nivosense-api:local
```

### Deploy

See [deploy/SETUP.md](deploy/SETUP.md). The repo is set up for Cloud Run "deploy from source" (`gcloud run deploy --source backend/`) once IAM is in place.

## Common tasks

### Adding a new forecast horizon

1. Add an entry to `frontend/src/lib/horizons.ts` (`HORIZONS` array, `HorizonId` type, `ORDER` array, and `horizonToDate` switch).
2. Add the same key to `backend/layers.yaml` with the GCS path.
3. ML pipeline starts producing the COG at the canonical path.
4. No frontend changes needed beyond step 1 — `TopBanner` and `BasemapSwitcher` re-render automatically.

### Wiring a new GeoJSON layer (e.g., routes)

1. Drop the file at `data/{name}.geojson` and copy to `frontend/public/data/{name}.geojson`.
2. In `App.tsx`, add a `useEffect` that fetches it and stores `Feature[]` in state, similar to `basinsFC`.
3. In `Map.tsx`, add a source + layers in `addBasinsLayers`-style helper, re-added on `style.load`.
4. Pass selected ID + select callback through props to LeftRail (for the accordion).

### Adding a sidebar nav item

1. Add an item in `LeftRail.tsx` with appropriate icon from `lib/icons.tsx` (or add a new icon there).
2. Lift the corresponding state to `App.tsx`.
3. If the item opens a panel, follow the accordion pattern (`expandable={true}` + conditional render of children).

### Adjusting visual hierarchy

- Glassmorphism panels: `border-white/5 bg-slate-950/80 backdrop-blur-xl`.
- Cyan accent: `cyan-300`, `cyan-400` for highlights, with `shadow-[0_0_*_rgba(34,211,238,0.X)]` for glow.
- Section labels: `text-[11px] uppercase tracking-[0.22em] text-slate-400`.

## Things to avoid

- **Adding state to a component that only the parent reads/writes.** Lift it to App.
- **Calling `setStyle` redundantly** during basemap initialization — `Map.tsx` uses `isFirstBasemapRun` to skip this on mount.
- **Hardcoding sample basins, routes, or stats values.** Empty states are correct.
- **Fetching from CDSE / external APIs at runtime in the backend.** That's a build-time job; runtime serves from our bucket.
- **Touching `darwingeospatial.com` org IAM or shared GCP resources** without explicit approval. The backend lives in a project where Mario is Owner OR uses a least-privilege runtime SA dedicated to NivoSense.
- **Documentation files (`*.md`) created without explicit user request.** Only the planning docs already in the repo, plus this file and `CLAUDE.md` when asked.

## Pointers

- [README.md](README.md) — public-facing project description.
- [ARCHITECTURE.md](ARCHITECTURE.md) — full technical design + API contract + ML contract.
- [ROADMAP.md](ROADMAP.md) — weekend timeline and per-person tasks.
- [development_strategy.md](development_strategy.md) — original Spanish-language brief from project kickoff.
- [deploy/SETUP.md](deploy/SETUP.md) — GCP setup commands.
- [ml/README.md](ml/README.md) — COG format and bucket contract for the ML team.
- [data/README.md](data/README.md) — GeoJSON schema for basins and routes.
