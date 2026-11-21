# Claude Code Guide

Project-specific guidance for Claude Code working in this repository. The full agent guide is in [AGENTS.md](AGENTS.md): read it first, including its **Critical rules**. This file holds only the Claude-Code-specific extras.

## Critical reminder

NivoSense is a maintained product, built from the plan in [docs/plan/](docs/plan/). The rules that matter most, in short (AGENTS.md has the full list):

- The plan folder is the spec: work from a task card in `docs/plan/tasks.md` and do only that card; anything else goes into the PR's "Found, not done" list.
- Real data only; empty states are fine.
- Every product goes through the catalogue (`pipelines/catalog/`, task T0.3).
- Comments only for the non-obvious why. Libraries, data sources and papers may be named.
- Spanish UI copy.
- Commits only within the scope Mario granted in gate H0: on `mariopeces/NivoSense`, for this plan, commit to your branch, push it and open a PR. Never push to `main`, never merge; the coordinator squash-merges after every required gauntlet passes.
- No secrets anywhere; never email or message a person on Mario's behalf (Gmail drafts only).

## How to operate effectively here

### Before making changes

- Read [AGENTS.md](AGENTS.md), [docs/plan/README.md](docs/plan/README.md) and your task card.
- For plan work, the card is the approved plan: its Do, Accept and Evidence lines set the scope. When a card is ambiguous or blocked by a human gate, ask (the coordinator, when you are a dispatched worker) rather than guess.
- Outside the plan, default to **plan mode** for non-trivial work; Mario prefers to validate the approach before code is written.
- [ROADMAP.md](ROADMAP.md) is the hackathon timeline, kept as history; it does not set current scope.

### State of the repo

- A long-running Vite dev server may already be active (`npm run dev` from `frontend/`). HMR picks up changes; don't restart it unless something is broken.
- The live site is the static build on GitHub Pages, deployed by `pages.yml`. The FastAPI backend is not deployed and is not on the v1 critical path.
- The hackathon buckets (`nivosense-cogs`, `nivosense-web`) are not the plan's storage; the plan uses `nivosense-data` and `nivosense-staging` (task T0.2).

### Tools to prefer

- **Edit / Write** for code changes.
- **Grep / Glob** for search, **Read** for inspecting files.
- **Agent / Explore** when the question genuinely spans multiple files. Prefer direct tools when the target is known.
- **TodoWrite** when a task has 3+ distinct steps.

### Tone

- Spanish or English depending on what Mario is using in the current turn; switch language per turn to match. UI copy is always Spanish.
- Terse end-of-turn summaries: 1 to 2 sentences. Don't restate the diff.
- When you find a problem, name it directly and propose a fix. Don't hedge.

## Things specific to this repo that catch agents off-guard

### The map date comes from the scene lists

`TopBanner` lets the user pick only dates that have an observation or prediction scene; `App.tsx` keeps the choice in `selectedObservationDate`. Don't add a free date state that can land on a day with no product. Task T4.2 replaces this with a timeline built from `catalog/index.json`.

### MapLibre layers vanish on `setStyle`

`map.setStyle()` wipes everything custom. Re-add sources, layers and click handlers in the `style.load` handler. See `addBasinsLayers()`, `addWebcamLayers()` and `attachBasinInteractions()` in `Map.tsx`.

### Basin selection is bidirectional

Selecting a basin from the map and from the LeftRail accordion both flow through `handleBasinSelect` in `App.tsx`. Don't add a separate map-click path; the accordion highlight would desync.

### `frontend/public/data/` mirrors `data/`

GeoJSONs live canonically in `data/`; Vite serves copies from `frontend/public/data/`. If you change one, change the other (they are byte-identical today).

### Empty states are intentional

Skeleton rows and "no data" messages are deliberate while real data is wired. Do not populate them with sample values to make the UI look alive; Mario has explicitly rejected this.

## Don't

- Don't run `gcloud` (or other outside) actions your card doesn't need. What a card needs is allowed under gate H2 and the advance OK in `docs/plan/README.md` section 4, with every command recorded in `docs/runbook.md`; never change org policies, never touch resources other workloads use, never message a person for Mario, never commit secrets.
- Don't commit, push or open PRs outside the H0 scope above. Never merge and never push to `main`.
- Don't introduce a new dependency without justifying it in the PR.
- Don't create Markdown files unless a card names them or Mario asks.

## When you're stuck

- Ask a focused question rather than guessing: the coordinator when you are a dispatched worker, Mario otherwise.
- For permission and infra walls, pause and present the trade-offs; don't power through with a workaround that has security implications.
