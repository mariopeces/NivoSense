# T4.2 Timeline: G-UI and G-Code, round 1

PR #31. I was dispatched at head 345f466 (T4.2 commit 4bbf31e). The head moved to **9f7499a** during the review, and the verdicts below are on 9f7499a.

What changed for T4.2 between the two heads:
- The calendar focus fix in `Timeline.tsx`.
- `Timeline.test.tsx`, which arrived with merge 2a3dd03.
- The `mapInset` sizes in `App.tsx`, now from tokens.

The rest is the stacked branches. I re-checked 9f7499a with a new build and render (`head-9f7499a/`), plus `npm ci`, typecheck, lint, 3 full test runs and the play and App mutants again.

**G-UI: fail** (M1 and M2 still reproduce on 9f7499a). **G-Code: pass** on 9f7499a. On 345f466 G-Code was a fail: the play timer had no test (G1). The new `Timeline.test.tsx` catches all three play breaks.

| On 9f7499a | Result |
|---|---|
| typecheck / lint | exit 0; 0 errors (1 warning from before this branch, Map.tsx:227) |
| vitest | 92/92 in each of 3 runs |
| Play mutants (step every day, never stop, 0 ms frame) | all 3 caught |
| App mutant (shared `d` ignored) | missed (minor) |
| Render: keyboard scrub, play, calendar, links, console, axe | same results as below. Calendar focus now stays on 10 Nov when the mouse moves over the track (m1 fixed). axe 0 violations in 8 states. 0 console errors with the real catalogue |
| M1 (no Hoy label or forecast slot), M2 (21x44 px mobile step buttons) | still present (`head-9f7499a/detail.txt`, `head-9f7499a/10-1440-track-end-3x.png`, `head-9f7499a/11-375-timeline-2x.png`) |

The empty (404) and error (403) states in `head-9f7499a/results.json` reuse the 345f466 bundles. The only T4.2 code change in between is the calendar effect, which those states do not render.

The sections below are the original round on 345f466.

## How it was checked

- Production build of 345f466 with `VITE_CATALOG_URL` set to the T0.4 evidence catalogue `gs://nivosense-cogs/staging/_scratch/t04-evidence-98f90df/staging/catalog/index.json`: 7 real observed RGB entries, 24 Oct to 20 Nov 2026. The live site's `data/snow-model/manifest.json` was copied into the build so `l=` has real layers to restore. Its overlay PNGs were not copied, so the `*_latest.png` 404s in `results.json` come from this harness, not from the PR.
- Two copies of the same bundle with only the catalogue URL changed: `staging/catalog/index.json` (404 today) and `gs://nivosense-cogs/` (403). Everything was served from `localhost:4173`, the only localhost origin in the bucket's CORS.
- Headless Chromium through Playwright 1.65 (SwiftShader WebGL), at 1440x900 and 375x812, `es-ES`, Europe/Madrid, on 2026-11-22. axe-core 4.10.2 with the wcag2a/aa, wcag21a/aa and best-practice tags. The scripts are in `harness/`; every number below is in `results.json`.
- Lighthouse was not run: the brief asks for axe, and Lighthouse is a T4.5 bar.
- G-Code: `npm ci`, `typecheck`, `lint` and `vitest` were run on a detached checkout of 345f466, plus 25 deliberate breaks (`mutations-batch*.txt`, run with TZ=Europe/Madrid).

## G-UI results

| Check | Result |
|---|---|
| Keyboard only | 12 Tabs from the page start reach the slider. Home goes to 1 Oct 2025. 417 ArrowRight presses visit 418 distinct days, each +1, and `?d=` follows every step. The cursor stops at 22 Nov 2026. DST (25 to 26 Oct 2025, 28 to 29 Mar 2026), month ends and the year end are all crossed one day at a time. Shift+→ from Home goes to 24 Oct 2026, then 29 Oct. End then Shift+← gives 20 Nov. **Pass** |
| Pointer drag edge to edge | 101 distinct days, index 4 to 417. **Pass** |
| Play | Space from 24 Oct steps through the 6 later real dates about 800 ms apart (5 intervals, mean 818 ms headless), then stops with Reproducir disabled. Pause holds the date. **Pass** |
| Última, previous, next | From a pending day (14 Feb 2026), previous is disabled and next goes to 24 Oct. Última goes to 20 Nov and is then disabled. **Pass** |
| Calendar | Opens with focus on the selected day. Only the 6 days in the month that have a product are enabled. Escape and picking a day both return focus to the calendar button. **Pass**, with a minor focus bug (m1) |
| Shared URL | `?d=2026-10-29&l=swe` opens on 29 Oct with SWE on. Bad or off-track `d` values (2026-02-30, garbage, 2024-01-01, 2026-12-25, 2026-1-5) fall back to the latest product. `l=SWE` and `l=nope` are dropped. `s=agua` is kept. **Pass** |
| Empty (404) | Honest copy at both widths. **Pass**, minor m2 |
| Error (403) | Error copy and Reintentar, which refetches (a new 403 request). **Pass** |
| axe | 0 violations at 1440, 375, both with the calendar open, and in the empty and error states at both widths. **Pass** |
| Console | Real catalogue: 0 errors at 1440 and 375. The 404 state logs only the declared catalogue 404. The 403 state logs the 403 and the handled `Failed to load the catalogue`. **Pass** |
| Copy | Spanish throughout, no text under 12 px. **Pass** |
| Against the T4.0 mockups (`timeline`, `vacio`) | **Fail**: M1, M2 |

## G-Code results

- `typecheck` passes. `lint` gives 0 errors (1 warning in Map.tsx:223, from before this branch). With the T0.6 colour rule there are no hex, rgb or hsl colours in the diff.
- Tests: 67 pass. One run out of four failed `eslint/no-hard-coded-colour.test.js > valid > "bg-navy text-slate-100 #section"`. That is the T0.6 rule's own test, flaky under load, and outside T4.2 (follow-up).
- Deliberate breaks caught (19): span length off by one; day stepping across DST (local-time `addDays`), month ends (30-day months) and the year end; month labels; status map and rank swaps; latest-up-to-today; forecast split at today; Shift jumps; Madrid today; the `.8s` play-frame parse; `d=2026-02-30`; malformed layer; other query parameters kept; 404 versus error; unknown status.
- **Missed (4)**: play steps every day instead of days with data; play never stops at the end; play frame 0 ms; App ignoring the shared `d`. Two other breaks behave exactly like the original code, so they don't count as misses (listed in the batch files).
- CLAUDE.md behaviours are intact. `style.load` re-adds layers (Map.tsx:190). `handleBasinSelect` is unchanged, and `applySelected` still runs on `selectedBasinId` (Map.tsx:237). The removed Map effect only re-applied the NDSI layer.
- No secrets or personal data in the diff. No new dependency.

## Findings

**M1 (G-UI, major): no "Hoy" label and no forecast slot.** Seen at both widths with the real catalogue (`01b-1440-timeline-zoom.png`, `10-1440-track-end-3x.png`, `11-375-timeline-2x.png`).
- Design spec 4.2 and both `timeline` mockups ask for a forecast slot at least 64 px wide after today, labelled "Previsión" at the "Hoy" line, with a visible "Hoy" label to the left of the line. Month labels within about a month of Hoy are dropped.
- The build draws the slot only when the catalogue has forecast entries. It uses a per-day scale, so 5 forecast days would be about 1.2 % of the track (roughly 8 px). "Hoy" exists only as a `title` on an `aria-hidden` line, and that line sits exactly on the track's right edge.
- The result: the reader cannot tell where today is, and `linea_tiempo.prevision_slot_pendiente` ("Previsión: aún no se publica") is never used.
- To pass: always render the slot (minimum `space-16`, pending on `panel-soft` when the catalogue has no forecast), with the visible "Hoy" label and the month-label rule.

**M2 (G-UI, major): mobile step and play buttons are 21x44 px.**
- At 375 the previous, play and next buttons measure 21x44 px (`11-375-timeline-2x.png`, detail.py output). `max-md:w-touch` is crushed by the flex column.
- That is under the 44 px touch size the class asks for and under the 24 px minimum of WCAG 2.2 SC 2.5.8.
- To pass: prevent shrinking (`shrink-0`) or give the left column room, then re-measure 44x44 at 375.

**G1 (G-Code, major on 345f466; fixed on 9f7499a, where Timeline.test.tsx catches all three breaks): play has no test.** The timer effect in Timeline.tsx:64-77 (step to the next day with data, stop at the end, frame duration) is new behaviour, and three deliberate breaks of it pass the suite.
- To pass: extract the next-frame choice into a pure function with tests, and/or add a component test with fake timers that checks the 800 ms step, skipping empty days, and stopping at the last date.

**Minor (follow-ups, not blocking):**
- **m1. Calendar focus jumps (fixed on 9f7499a).** With focus on 10 Nov in the calendar, moving the mouse over the track sends focus back to 20 Nov. Cause: the effect in Timeline.tsx:376-383 depends on the inline `onClose`, so every Timeline re-render (hover state) runs it again and refocuses the pressed day. Focus once on mount, or keep `onClose` stable.
- **m2. Empty state controls.** Spec 4.2 says "Última" and the calendar stay visible but disabled in the empty state. The build drops them (`09-1440-e404.png` against the `vacio` mockup).
- **m3. Disabled button style.** Spec 4.2 says disabled buttons have a dashed `line` border on `panel-soft`. The timeline's disabled buttons keep the solid border with grey text.
- **m4. Strip at the end of the track.** One-day status segments with a 1.5 px border are about 3 px wide at 1440, so the clear-pass cluster renders as "( (" glyphs (`10-1440-track-end-3x.png`). Consider no border radius or border under about 4 px per day.
- **m5. Tooltip has no source.** The mockup tooltip names the source ("Observado (S2 L1C)"); the build shows the status only.
- **m6. Panel in the empty state.** With the catalogue at 404, the panel still shows snow-model dates and badges from the legacy manifest. The `vacio` mockup has a panel notice and every layer Pendiente. This belongs to T4.3.
- **m7. Flaky T0.6 rule test.** `eslint/no-hard-coded-colour.test.js` fails intermittently (1 run in 4).
- **m8. Two background classes on one segment.** A pending forecast-slot segment gets both `bg-panel` and `bg-panel-soft` (Timeline.tsx:44 and :238), so CSS order picks the winner. This becomes visible once M1 is fixed.

```json
{
  "gauntlet": "G-UI",
  "task": "T4.2",
  "round": 1,
  "head": "9f7499a",
  "verdict": "fail",
  "findings": [
    {"severity": "major", "where": "frontend/src/components/Timeline.tsx:263-277 (head 9f7499a, same code); 1440 and 375; real T0.4 catalogue", "what": "No visible 'Hoy' label and no forecast slot: the slot exists only when the catalogue has forecast entries and is per-day scaled (about 8 px for 5 days); 'Hoy' is only a title on an aria-hidden line at the track's right edge. Spec 4.2 and the timeline mockups require a 64 px minimum slot labelled 'Previsión' and a visible 'Hoy' label.", "observed": "own render: innerText of the track has neither 'Hoy' nor 'Previsión'; today line x = track right; screenshots 01b, 10, 11", "to_pass": "always render the forecast slot (min space-16, pending on panel-soft when no forecast, prevision_slot_pendiente copy), visible 'Hoy' label, month labels near Hoy dropped"},
    {"severity": "major", "where": "frontend/src/components/Timeline.tsx:29-31,168-198; 375x812", "what": "Previous, play and next buttons render 21x44 px on mobile: max-md:w-touch is shrunk by the flex column, below the 44 px touch size and the WCAG 2.2 2.5.8 24 px minimum", "observed": "getBoundingClientRect at 375: 21x44 for all three; screenshot 11-375-timeline-2x.png", "to_pass": "buttons keep 44x44 at 375 (shrink-0 or room in the column), re-measured"},
    {"severity": "minor", "where": "Timeline.tsx:99-108; empty state 1440 and 375", "what": "Empty state omits the disabled 'Última' and calendar buttons the spec (4.2) and the vacio mockup show", "observed": "09-1440-e404.png vs docs/design/screenshots/mockups/vacio-1440.webp", "to_pass": "render both disabled"},
    {"severity": "minor", "where": "Timeline.tsx:29-34", "what": "Disabled buttons keep a solid border; spec 4.2 asks for a dashed line border on panel-soft", "observed": "screenshots 01b, 11", "to_pass": "disabled style per spec"},
    {"severity": "minor", "where": "Timeline.tsx:38-45,234-242; 1440", "what": "About 3 px one-day segments with a 1.5 px border and radius render as '( (' glyph clusters near the clear passes", "observed": "10-1440-track-end-3x.png", "to_pass": "no border or radius on very narrow segments"},
    {"severity": "minor", "where": "Timeline.tsx:285-296", "what": "Tick tooltip has no source; the mockup shows 'Observado (S2 L1C)'", "observed": "05-1440-tooltip-end.png", "to_pass": "add the layer or source to the tooltip"}
  ],
  "followups": ["Empty state panel still shows legacy snow-model dates and badges while the catalogue is 404 (T4.3)", "Lighthouse per U2 not run here (T4.5)"]
}
```

```json
{
  "gauntlet": "G-Code",
  "task": "T4.2",
  "round": 1,
  "head": "9f7499a",
  "verdict": "pass",
  "findings": [
    {"severity": "minor", "where": "frontend/src/App.tsx (shared-link date selection effect)", "what": "The shared-link date wiring (keep d when it is on the track) is not covered; replacing current ?? initialUrl.date with current passes all 92 tests", "observed": "mutation on 9f7499a, full suite, missed", "to_pass": "extract the choice into a tested helper or add an App test with ?d="},
    {"severity": "minor", "where": "Timeline.tsx:44,238", "what": "A pending forecast segment gets bg-panel and bg-panel-soft together; CSS order decides which wins", "observed": "code read", "to_pass": "one background class per state (relevant once G-UI M1 adds the slot)"},
    {"severity": "minor", "where": "frontend/eslint/no-hard-coded-colour.test.js (T0.6, outside T4.2)", "what": "Flaky on 345f466: 1 of 4 full runs failed the 'bg-navy text-slate-100 #section' valid case; 0 of 3 on 9f7499a", "observed": "vitest runs", "to_pass": "follow-up on the T0.6 rule test"}
  ],
  "followups": ["On 345f466 the play timer was untested (3 breaks passed); fixed on 9f7499a by Timeline.test.tsx", "Calendar refocus on parent re-render fixed on 9f7499a"]
}
```
