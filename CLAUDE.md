# Claude Code Guide

Project-specific guidance for Claude Code working in this repository. The full agent guide is in [AGENTS.md](AGENTS.md) — read that first; this file holds only the Claude-Code-specific extras.

## Critical reminder

**Hackathon "fresh code only" rule is non-negotiable.** Never reference external repositories, prior implementations, or named projects in code, comments, or commit messages. Patterns may be borrowed; the implementation is always written from scratch in this repo.

If you ever recognize a pattern from elsewhere while working, transcribe the *idea* in your own words and write fresh code. Don't copy file structures, naming conventions, or boilerplate verbatim.

## How to operate effectively here

### Before making changes

- Skim [AGENTS.md](AGENTS.md) for project conventions.
- Check [ROADMAP.md](ROADMAP.md) to see which day / phase we're in — scope expectations differ between Saturday morning (scaffolding) and Sunday afternoon (polish).
- Default to **plan mode** for non-trivial work. The user prefers to validate the approach before code is written.

### State of the repo

- A long-running Vite dev server may already be active in the background (`npm run dev` from `frontend/`). HMR picks up changes automatically. Don't restart it unless something is genuinely broken.
- The backend is **not yet deployed**. Local-only via `uvicorn`. Deploy is blocked on GCP IAM for a runtime service account.
- Buckets `nivosense-cogs` (data) and `nivosense-web` (frontend hosting) exist with public read + CORS configured.

### Tools to prefer

- **Edit / Write** for code changes; never use `sed` / `awk` / shell heredocs.
- **Grep / Glob** for search; never `grep` / `rg` / `find` via Bash.
- **Read** for inspecting files; never `cat` / `head` / `tail`.
- **Agent / Explore** when the question genuinely spans multiple files. Prefer direct tools when the target is known.
- **TodoWrite** when a task has 3+ distinct steps. Don't use it for trivial single-step work.

### Tone

- Spanish or English depending on what the user is using in the current turn. The user code-switches; follow their lead per turn.
- Terse end-of-turn summaries: 1–2 sentences. Don't restate the diff.
- When you find a problem, name it directly and propose a fix. Don't hedge.

## Things specific to this repo that catch agents off-guard

### TopBanner date and horizon are linked

The forecast horizon is the **single source of truth** for time. The displayed date is computed from it. If you find yourself adding a separate `date` state, you're recreating a bug we already fixed. See `frontend/src/lib/horizons.ts` and `TopBanner.tsx`.

### MapLibre layers vanish on basemap switch

`map.setStyle()` wipes everything custom. Re-add sources, layers, and click handlers in the `style.load` event handler — it fires once on initial load and again after every basemap switch. See `Map.tsx` `addBasinsLayers()` and `attachBasinInteractions()`.

### Basin selection is bidirectional

Selecting a basin from the map (click on polygon) and from the LeftRail accordion both flow through the same `handleBasinSelect` handler in `App.tsx`. Don't introduce a separate "click on map" path that bypasses the rail's awareness — the highlighting in the accordion would desync.

### `frontend/public/data/` mirrors `data/`

GeoJSONs live canonically in `data/` (committed, used by the backend / pipeline). For Vite to serve them at `/data/*` during dev, copies live in `frontend/public/data/`. If you change one, change the other. (Better: a build step that copies on `npm run dev` start — TODO if it becomes painful.)

### Empty states are intentional

If you see `const basins: Basin[] = []` or skeleton rows in the UI, that's deliberate while real data is wired. Do not populate with sample values to "make the UI look alive" — the user has explicitly rejected this.

## Don't

- Don't run `gcloud` commands that mutate shared GCP resources without explicit approval. Buckets, service accounts, IAM grants on `darwin-general-sandbox` affect other Darwin workloads.
- Don't commit without an explicit ask.
- Don't push to remote without an explicit ask.
- Don't introduce a new dependency without justifying it in the conversation.
- Don't create new top-level documentation files (`*.md`) unless the user asks.

## When you're stuck

- The user has deep context on this project. Ask a focused question rather than guessing.
- For permission / infra walls (which we hit often), pause and present the trade-offs — don't power through with a workaround that has security implications.
