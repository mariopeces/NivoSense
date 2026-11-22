# T4.1 Tokens and app shell: G-Code round 2 and narrow G-UI round 2

I judged PR #25 at head `1bd78e2`, the head named in the dispatch. I checked out that head in two detached worktrees of my own: one for the breaks and one clean one for the build and the renders. Every number below comes from my own runs. The builder's table is not used as evidence.

- **G-Code: FAIL.** One major: the rewritten copy-key test lost coverage that round 1's test had.
- **G-UI (narrow): PASS.** The round-1 minors are fixed, nothing regressed, axe reports 0 violations, and there are no console errors.

Files in this folder:
- `breaks.json`: every break, with the command it ran and the result.
- `breaks.py`: the break harness.
- `shoot.py` and `click375.py`: the render scripts.
- `shots/`: 24 renders plus `report.json` and `click375.json`.
- `side-r1-r2-*.webp`: round-1 renders next to round-2 renders.

## G-Code

### Checks I ran

| Check | Result |
|---|---|
| `tsc -b` | exit 0 |
| `eslint .` | 0 errors, 1 warning (the existing `Map.tsx:245` exhaustive-deps warning) |
| `vitest run` | 65 tests in 12 files. All passed when CI ran them. In my local full run, 64 passed and 1 timed out at 5 s: the first case of `eslint/no-hard-coded-colour.test.js`, a T0.6 file, slowed by load on this machine. That file passes 29/29 on its own. |
| `vite build` | passes |
| PR CI (`frontend`, `python`, `staging-writer`, `prod-writer-from-branch`) | all pass on `1bd78e2` |
| Colour baseline against `main` (`node eslint/check-colour-baseline.js <main baseline>`) | passes. The baseline holds only `src/components/Legend.tsx`: 19 values, 21 occurrences. |
| My own grep for hex, `rgb()` and `hsl()` across `src/` and `index.html`, leaving out tests and `styles/tokens.css` | 21 hits, all in `Legend.tsx`. That is exactly the declared exception. |
| Dependencies | `jsdom 26.1.0`, `@testing-library/react 16.3.0` and `@testing-library/dom 10.4.0` are dev-only, pinned exactly and justified in the PR. |

### Deliberate breaks

I applied each break alone, ran the named test file (or the whole suite, or eslint), then restored the file. The full list is in `breaks.json`.

| # | Break | Check run | Result |
|---|---|---|---|
| R1-1 | `handleBasinSelect` without `setSection("agua")` | App.test | caught |
| R1-2 | rail arrow map reduced to `{ ArrowDown: 0 }` | Rail.test | caught |
| R1-3 | `NEXT_SHEET.full = "full"` | Panel.test | caught |
| R1-4 | `rail.tooltip_meteo` renamed in the deck | copy.test | caught |
| N-1 | `estado.tooltip_observado` renamed in the deck (reached only through a template) | copy.test | caught |
| N-2 | the first layer's `capa.*.cadencia` renamed in the deck (reached only through a template) | copy.test | caught |
| N-3 | a new template `` t(`rail.tip_${…}`) `` that the test's table does not list | copy.test | caught |
| N-4b | lowercase typo in a ternary key: `fila_capa.ocultr` | copy.test | caught |
| N-5 | `handleBasinSelect` without `setPanelOpen(true)` | App.test | caught |
| N-6 | calendar enables days that have no scene | DateBar.test | caught |
| N-7 | the next button is never disabled | DateBar.test | caught |
| N-8 | Home jumps to the second section | Rail.test | caught |
| N-9 | the panel never gets `is-collapsed` | Panel.test | caught |
| N-10 | the desktop map inset ignores the collapsed panel | App.test | caught |
| N-11 | hand edit of one hex in `tokens.css` | token sync test | caught |
| N-12 | edit of `tokens.json` without regenerating | token sync test | caught |
| N-13 | `bg-[#ffffff]` added in Panel | eslint | caught (1 error) |
| N-14 | inline `style={{ color: "#ff0000" }}` added in Rail | eslint | caught (1 error) |
| N-15 | webcam PK keeps the decimal point | WebcamsSection.test | caught |
| N-16 | Agua list sorted ascending by area | App.test | caught |
| **N-4f** | **section typo in a direct literal: `t("leyenda.experimental")` → `t("leyendas.experimental")`** | **whole suite** | **missed: 65/65 pass** |
| N-4f (control) | the same break against round 1's `copy.test.ts` (4d41315) | that file | caught |
| N-4d | section typo in a ternary key: `"leyenda.swe"` → `"leyendas.swe"` | whole suite | missed |
| N-4e | `t("rail.tooltip_mapa_base")` → `t("rails.…")` | copy.test / whole suite | missed by copy.test; caught by the Rail render tests |
| N-4 / N-4c | a typo containing a capital letter (`fila_capa.ocultarX`, `leyenda.sweTotal`) | copy.test | missed. N-4's first run reported "caught" only because PostCSS failed to load; the rerun is the real result. |
| N-17 | `map.on("style.load", setupLayers)` removed | whole suite | missed. Expected: the map is stubbed under jsdom. I checked this behaviour by rendering instead (below). |
| N-18 | the mobile half-sheet inset uses the peek height | whole suite | missed (minor 2) |

### CLAUDE.md behaviours (code read plus my own renders)

- **`style.load` re-adds the layers: PASS.** `Map.tsx:211-212` registers `setupLayers` on both `load` and `style.load`. In my run I switched the basemap Claro → PNOA → 3D → Claro. The basins and the selected Guadalfeo outline survived, and a map click afterwards still selected Guadalfeo and opened Agua (`shots/app-tras-setstyle-clic-1440.webp`).
- **`handleBasinSelect` is the single path: PASS.** `App.tsx:355` is the only place a basin is selected. The map (`onBasinSelect`) and the list (`AguaSection onSelect`) both call it.
- **The date comes from the scene lists: PASS, unchanged.** `DateBar` steps only through `scenes`, and the calendar disables every day without a scene (N-6 and N-7 prove the tests guard this). There is no free date state.

### Round-1 findings

1. **Major, no shell tests: fixed.** All four round-1 breaks and 14 new breaks of the shell behaviour fail the suite.
2. **Major, copy keys: partly fixed, and one case regressed (finding 1 below).** Composed keys are now fully checked (N-1, N-2, N-3).
3. **Minor, `mapInset` magic numbers: fixed.** The inset is built with `tokenPx()`, and `useViewportHeight` recomputes it on resize.
4. **Minor, the calendar stole focus: fixed.** The focus effect runs on mount only and reads `onClose` through a ref.
5. **Minor, dead bits: fixed.** The `BasinRow` alias and `logo.png` are gone. `SECTIONS` is now used by the tests.

### Findings

**1. Major. The new copy-key test only sees keys whose section already exists, so a misspelt section passes CI and blanks the app.**
- **Where:** `frontend/src/lib/copy.test.ts:54`.
- **What:** The literal check builds its regex from the deck's own top-level sections (`(?:leyenda|rail|…)\.[a-z0-9_.]+`). A key whose section is misspelt, such as `leyendas.…` or `rails.…`, is never extracted, so it is never checked. The same goes for any key containing a capital letter.
- **Why it is a regression:** round 1's test matched every `t("…")` literal whatever its prefix, and it catches the same break (N-4f control).
- **Why it matters:** `t()` throws and there is no error boundary. The legend renders whenever a model or observation layer is on, so the typo gives a blank page in production while all 65 tests pass.
- **How I observed it:** N-4f, `t("leyenda.experimental")` → `t("leyendas.experimental")`: the whole suite passes 65/65. Round 1's `copy.test.ts` fails on it with "Missing copy key leyendas.experimental". N-4d (the same kind of typo in a ternary) and N-4c (a capital letter) also pass the whole suite.
- **To pass:** Check every string literal in the key positions, whatever its section or case:
  - the first argument of `t(…)`;
  - both branches of a ternary inside `t(…)`;
  - the values of key lookup tables such as `WEATHER_TITLE`.

  For example, keep round 1's `t\(\s*["']([^"']+)["']` matcher alongside the section-based one, and extract the ternary branches the same way. N-4f, N-4d and N-4c must then fail the suite.

**2. Minor. The mobile shell logic has no test, and the `setMobile` helper is never used.**
- **Where:** `frontend/src/test/dom.ts:15`; `frontend/src/App.tsx:362`, `:369` and `:428`.
- **What:** `setMobile` is exported but no test calls it. Three mobile behaviours are therefore never exercised:
  - the sheet inset;
  - tapping the active tab toggling the sheet between peek and half;
  - selecting a basin raising the sheet from peek to half.
- **How I observed it:** N-18 (the half-sheet inset uses the peek height) passes the whole suite.
- **To pass:** Add one App test under `setMobile(true)`, or drop the helper.

**3. Minor. A type re-export and an import sit below code.**
- **Where:** `frontend/src/components/Map.tsx:19-20`.
- **What:** The `export type { Basemap } from "../lib/basemaps"` and `import type` lines sit after the `SIERRA_NEVADA_BOUNDS` constant. `App.tsx` could import `Basemap` from `lib/basemaps` directly.
- **To pass:** Move the import to the top, or drop the re-export.

**Follow-ups (not blocking):**
- The `style.load` re-add cannot be tested under jsdom. Cover it in the T4.5 browser smoke test, so a future refactor of `Map.tsx` is guarded.
- `eslint/no-hard-coded-colour.test.js` (T0.6) keeps vitest's 5 s default for its first RuleTester case, and timed out once on a loaded machine. Raise its timeout.

## G-UI (narrow)

**How I checked.** I built the PR myself (`vite build`) and served it with `vite preview`. I rendered it with Playwright Chromium (swiftshader) at 1440×900 and 375×812:
- all 5 sections;
- the collapsed panel at 1440;
- the three sheet heights at 375 (peek 132 px, half 406 px, full 704 px);
- the basin selected from the list and from the map;
- the basemap switch, 3D, and back to Claro;
- a Tab walk.

I compared the renders with round 1's from `g-t41-gui-r1` (`side-r1-r2-*.webp`).

| Check | Result |
|---|---|
| axe-core 4.10.2 (wcag2a, 2aa, 21aa, best-practice) | 0 violations in all 5 sections at both widths. Also 0 on the collapsed panel, the sheet state and the basin view. |
| Console | No errors at either width. At 1440 the only warnings are swiftshader "GPU stall due to ReadPixels" driver messages. |
| Requests | No 4xx or 5xx. The only failures are PNOA and terrain tiles cancelled (`ERR_ABORTED`) during the basemap and 3D switch, which is expected. |
| Section A audits | Smallest text is 12 px everywhere. 0 tracked capitals, 0 `backdrop-filter`, 0 text-shadow. Fonts loaded: Inter 400/500/600 and Source Serif 4 600. |
| Rail keyboard | ↓↓ goes to Agua then Webcams, End to Método, Home to Nieve, and ↑ wraps to Método. The rail is one tab stop. |
| Map click | 1440: from Nieve, a click opens Agua with Río Guadalfeo o Río Cádiar. 375 (fresh load at peek): a click opens Agua with Río Guadalquivir (`shots/click375.json`). |

**Round-1 minors:**
- **MapLibre names: fixed.** Every MapLibre name is now Spanish: "Mapa", "Acercar", "Alejar", "Orientar al norte", "Mostrar u ocultar la atribución". No English name is left (`report.json` `maplibre_names` and the Tab walk).
- **Cádiar: fixed.** The list, the basin title and the map-click title all read "Río Guadalfeo o Río Cádiar".
- **Webcam rows: fixed.** Rows read "A-395 · PK 12,6" and "Granada", sorted by PK 7,8 → 30,92 at both widths (`side-r1-r2-webcams-*.webp`). The row's right side still says "Sin imagen", where the mockup shows the provider (DGT). Round 1 left that part to T3.4/T4.4 if it was out of T4.1's scope, so I am not raising it again.
- **The date bar against dated layers:** still with T4.2, as agreed.

**Regressions:** none. The 1440 Agua, collapsed and basin views and the 375 Nieve sheet match round 1 apart from the fixed text.

```json
{
  "gauntlet": "G-Code",
  "task": "T4.1",
  "round": 2,
  "verdict": "fail",
  "findings": [
    {
      "severity": "major",
      "where": "frontend/src/lib/copy.test.ts:54",
      "what": "Literal key check only extracts keys whose section already exists in the deck, all lowercase; a misspelt section (t(\"leyendas.experimental\")) or a key with a capital letter is never checked, though round 1's t(\"literal\") matcher caught it; t() throws with no error boundary, so the app blanks when the legend renders",
      "observed": "break N-4f t(\"leyenda.experimental\") -> t(\"leyendas.experimental\"): whole vitest suite 65/65 green on 1bd78e2; round 1's copy.test.ts (4d41315) fails it with 'Missing copy key leyendas.experimental'; N-4d (ternary 'leyendas.swe') and N-4c ('leyenda.sweTotal') also pass the whole suite",
      "to_pass": "check every string literal in key position whatever its section or case: t() first argument, both ternary branches inside t(), lookup-table values (e.g. keep round 1's t\\(\\s*[\"']([^\"']+)[\"'] matcher alongside); breaks N-4f, N-4d and N-4c must fail"
    },
    {
      "severity": "minor",
      "where": "frontend/src/test/dom.ts:15; frontend/src/App.tsx:362,369,428",
      "what": "setMobile is exported but unused, so the mobile shell logic (sheet inset, active-tab sheet toggle, basin select raising peek to half) has no test",
      "observed": "break N-18 (half-sheet inset uses the peek height) passes the whole suite",
      "to_pass": "one App test under setMobile(true), or drop the helper"
    },
    {
      "severity": "minor",
      "where": "frontend/src/components/Map.tsx:19-20",
      "what": "type re-export and import placed below the SIERRA_NEVADA_BOUNDS constant; App could import Basemap from lib/basemaps",
      "observed": "code read",
      "to_pass": "move the import to the top or drop the re-export"
    }
  ],
  "followups": [
    "style.load re-add cannot be tested under jsdom (break N-17 passes the suite); verified by render; cover it in the T4.5 browser smoke test.",
    "eslint/no-hard-coded-colour.test.js (T0.6) timed out once at vitest's 5 s default on a loaded machine; raise its timeout."
  ]
}
```

```json
{
  "gauntlet": "G-UI",
  "task": "T4.1",
  "round": 2,
  "verdict": "pass",
  "findings": [],
  "followups": [
    "Webcam rows still show 'Sin imagen' at the right where the T4.0 mockup shows the provider (DGT); left to T3.4/T4.4 in round 1.",
    "Date bar empty message against dated layer rows stays with T4.2's catalogue timeline."
  ]
}
```
