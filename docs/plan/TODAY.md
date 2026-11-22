# Ship today: reduced scope (Mario, 2026-11-22)

This file overrides `README.md`, `tasks.md`, `gauntlets.md` and `orchestration.md` wherever they differ. Goal: the most consistent version that can be live in production **today, 2026-11-22**, at lower token cost. Consistency beats completeness: a layer that is not solid is hidden, not shipped half-working.

## What ships today

1. **Dates on the timeline**
   - Current season: 2026-10-01 to today, growing daily.
   - Demo window with deep snow: **March 2025** (2025-03-01 to 2025-03-31): every clear Sentinel-2 date. If March 2025 has fewer than 3 clear dates over the massif, add the clearest snowy dates of February and April 2025. The UI offers a "Ver un mes con nieve (marzo 2025)" jump, since the massif is bare today.
   - No other history. No past-season masks.
2. **Layers**
   - Observed snow cover (T1.2), true colour RGB L1C (T1.3), gap-filled snow cover v1 (T1.4), for the dates above.
   - SWE and depth: **only if the lite fix below lands and passes today**; otherwise the two layers are hidden in the UI (row shown as "Proximamente"), never shown with false snow.
3. **Model lite (replaces T2.2, T2.3, T2.4)**: keep the current forcing and calibration. Add only:
   - direct insertion: SWE set to zero where a clear S2 observation sees bare ground;
   - the published map is the ensemble median, values under 5 mm transparent;
   - domain from T2.1;
   - the layer is labelled "Modelo experimental" with a one-line caveat.
   - Runs: current season, and season 2024-25 up to 2025-03-31 for the demo window.
   - Accept: on 2026-11-20 the crest shows no snow outside the ski resort; in March 2025 modelled snow overlaps observed snow sensibly (visual check plus one accuracy number per date).
4. **Webcams**: Cetursa cams (T3.1) and live DGT cams (T3.2) on the map with icon and view cone (T3.4). Bearings (T3.3): estimated from the image and the map, marked "orientacion aproximada"; no skyline-matching script.
5. **Interface**: shell (T4.1), timeline (T4.2), layers and legends (T4.3), basin panel with what data exists (T4.4, minimal), per `docs/design/`. A short "Metodo" section with sources, limits and the Q1 score (replaces T2.6). Must work on mobile; no separate T4.5 pass, Lighthouse is a warning only.
6. **Operations**: catalogue and publish (T0.3), QA harness as it stands once its two majors are fixed (T0.4), one backfill run for the dates above (T1.5), the daily job (T1.6), a failure opens an issue (T5.1 minimal). Go-live (T5.4) today. `docs/runbook.md` covers only: rerun a date, roll back the site.

## Dropped or deferred (keep the Orca Tasks, mark them deferred in STATUS.md)

T1.7, T2.2, T2.4, T2.6 (as a page), T4.5, T5.5, both 7-day soaks, T5.3 beyond the two procedures, history before 2026-10-01 other than the demo window, sublimation and wind terms, Landsat, GFSC, wet snow. Stop any worker on these now.

## Validation rules for today

- One combined gauntlet per task, one fresh worker. One round. The builder fixes blockers and majors; the coordinator checks the fix from the diff and CI and merges. A second gauntlet round only if a blocker touched method or data correctness.
- No mutation testing, no throwaway probe PRs, no re-review of minors.
- G-Code is: CI green plus a diff read. Full attention goes to: G-Method on T1.2, T1.4 and model lite; G-UI once on the integrated staging site; one G-Product pass on staging before go-live.
- Tasks already in a later round finish that round under these rules (minors are waived to a follow-up list).

## Cost rules

- At most 4 builders and 2 gauntlets alive.
- Use `--model sonnet` for combined gauntlets on code, data and infra, if `worker-start` accepts it; keep the default model for builders, G-Method and G-UI.
- STATUS.md: update on merges and blockers only.
- Merge order: T0.3, T0.4, T1.1, T2.1, T3.1, T4.1 first (they are approved or nearly), then T1.2, T1.3, T4.2, T4.3, T3.2, then T1.4, T3.3/T3.4, model lite, T4.4, then T1.5, T1.6, T5.1, then acceptance and T5.4.

## Definition of done for today

On the live URL: the site loads with the new interface; the timeline has the current season and March 2025; observed snow, gap-filled snow and RGB open for every listed date; webcams show with cones and real image age; no layer shows snow where the same-date clear image shows bare ground; the daily job is scheduled and a failure opens an issue.

If the day ends before go-live, leave the best consistent state on staging, write in STATUS.md exactly what is missing, and do not go live half-done.
