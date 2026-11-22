## G-UI gauntlet: T4.1 Tokens and app shell, round 1. Verdict: **pass**

Judged: PR #25 head `4d41315` (`plan/t41-shell`), T4.1's own work only, against T4.0 (`plan/t40-design`: `tokens.json`, `copy.es.json`, mockups). This round was restarted after the first worker stopped. Every render and number below is from this worker's own run. Nothing from the earlier partial output is reused except its Playwright script, which I re-read and re-ran.

**How I checked.** I built the PR myself (`npm ci`, `npm run build`, `vite preview`). I took Playwright screenshots of all five rail sections at 1440×900 and 375×812, plus collapsed and open panel, the three sheet heights, empty states, basin selection both ways, the basemap switch, 3D, and rail hover and focus. In the same run I rendered the T4.0 mockups (`?s=nieve|agua|cuenca|webcams|metodo|colapsado|vacio`) and openpas-habitat (guest viewer). The local cedar-vista build only shows its sign-in landing (the viewer needs auth and isn't in public guest mode), so for the cedar viewer I compared against T4.0's reference screenshot `docs/design/screenshots/reference/cedar-vista-1440.webp`.

Evidence on branch `mariopeces/g-t41-gui-r1` under `qa-reports/T4.1/G-UI-round1/`: `shots/` (57 renders), `shots/report.json` and `shots/extra.json` (audits), side-by-side sheets `side-*.webp`, and the scripts (`shoot.py`, `extra.py`, `fresh375.py`, `refs_viewer.py`, `sheet.py`). The renders were saved as PNG and converted to WebP afterwards.

### Rubric

| Section | Result | My evidence |
|---|---|---|
| A. Tokens only, generated from tokens.json | Pass | Re-running `node scripts/build-tokens.mjs` leaves `src/styles/tokens.css` unchanged. A grep for hex, `rgb()` and `hsl()` across `src` finds only the 5 declared `Legend.tsx` palette lines (the coordinator's exception until T4.3). `eslint .` gives 0 errors and 1 existing warning (Map.tsx exhaustive-deps). `vitest` 41/41. |
| A. One display face plus Inter, loaded | Pass | `document.fonts` loaded: Inter 400/500/600 and Source Serif 4 600, in every section at both widths. Serif only on the wordmark and panel titles. |
| A. No text under 12 px | Pass | Smallest computed size on visible text: 12 px, every section, both viewports, collapsed state too. |
| A. No all-caps tracking, glow or glass | Pass | Computed styles: 0 uppercase with letter-spacing above 0.5 px, 0 `backdrop-filter`, 0 text-shadow, 0 coloured box-shadows, 0 CSS gradients outside the legend. |
| B. Dark rail + light panel, collapses, map is the hero | Pass | Matches the mockups at 1440 (`side-nieve`, `side-cuenca`, `side-colapsado`). Ocultar/Mostrar work by mouse and keyboard. The collapsed panel is `visibility:hidden`, so it doesn't take focus. At 375: tab bar plus sheet, opens at peek, and peek, half and full all work. Only the date bar, legend card (builder's `datos-swe`), zoom and compass float over the map. |
| C. Honest empty states, units | Pass (1 minor) | Pendiente rows, "Aún no hay previsión publicada", "Ninguna cámara con imagen en este momento", 8/8 cams "Sin imagen". Units shown (km², hm³, m). |
| D. Keyboard, hover vs selected | Pass | Rail is a tablist with a roving tabindex: ↓↓ goes Agua then Webcams, End goes to Método, Home to Nieve, and ↑ from Nieve wraps to Método. Visible 2 px focus ring. Rail hover (lighter fill) differs from selected (fill plus accent bar). The selected basin is drawn in accent orange. URL state is T4.2 scope: none today. |
| F. Console, requests, axe, copy | Pass (2 minor) | axe-core 4.10.2 (wcag2a/2aa/21aa/best-practice): 0 violations in all 5 sections at both widths and on the basin detail. No console errors, and no warnings beyond swiftshader GL driver messages. No 4xx/5xx. The only failed requests are PNOA and terrain tiles cancelled (`ERR_ABORTED`) during the basemap switch, which is expected. `lang="es"`. |
| CLAUDE.md behaviours | Pass | **Date only from the scene lists:** the bar shows "Aún no hay escenas publicadas" because the scene lists are empty; there is no free date state. **setStyle:** after Claro → PNOA → 3D → Claro, the basins, the selection and the click handler survive (`app-ortofoto-1440`, `app-ortofoto-3d-1440`, `app-vuelta-claro-3d-1440`); a map click after the switch still selects Guadalfeo. **Bidirectional:** picking from the list highlights the basin on the map. A map click from Nieve switches to Agua and shows the same basin (`app-cuenca-desde-mapa-1440`, `x-cuenca-lista-375`). |

### G. Would a geospatial professional trust it?
Yes as a shell. It reads like the T4.0 spec made real: a quiet dark rail, a light panel with a serif title, real source and resolution lines and honest Pendiente states. Nothing invented is shown, and the map stays in front. Next to the openpas viewer (same run) and the cedar-vista viewer reference it holds up: same rail-and-panel grammar, tighter type, no decorative chrome, gradients or filler icons. The weak spots are in the data-facing details, not the shell: the webcam list prints raw DGT strings (`PK 12.6`, `GRANADA`, unsorted), and the date bar can contradict dated layers. Both are below.

No "looks generated" element found. The dotted "Pendiente del modelo" chart box is the spec's dotted shape for the pending status, not filler.

### Findings (all minor, none block)
1. **Minor, C.** The date bar says "Aún no hay escenas publicadas" while the layer rows show "Escena del 21 nov 2026" (builder's evidence `t41/screens/datos-swe-1440.webp`). It is declared in Found, not done, and T4.2's catalogue timeline fixes it.
2. **Minor, F.** MapLibre's default English accessible names are still there: the map region is "Map" and the attribution button is "Toggle attribution" (Tab walk in `extra.json`). Only zoom and compass were localised.
3. **Minor, F/C.** The Webcams list shows raw provider strings, not the mockup row: `A-395 · PK 12.6` with a decimal point (mockup: `PK 12,6`), the province in capitals (`GRANADA`), and an order that is not by PK (PK 7.8 comes last). The per-row "Sin imagen" also repeats the group heading where the mockup shows the provider (DGT). See `side-webcams-1440.webp`.
4. **Minor, copy.** "Río Guadalfeo o Río Cadiar" without the accent (mockup: "Cádiar"). Declared.
5. **Info.** Basins on the map have no hover state, only the pointer cursor; the list row hover is a faint fill. Selected is clearly distinct, so D holds. A map hover outline would match the mockup's intent (T4.4).

```json
{
  "gauntlet": "G-UI",
  "task": "T4.1",
  "round": 1,
  "verdict": "pass",
  "findings": [
    {
      "severity": "minor",
      "where": "date bar, all screens, 1440 and 375 (builder evidence t41/screens/datos-swe-1440.webp)",
      "what": "Date bar says 'Aún no hay escenas publicadas' while layer rows show dated scenes",
      "observed": "builder's datos-swe render: SWE row 'Escena del 21 nov 2026' with the bar's empty message",
      "to_pass": "T4.2 timeline from catalog/index.json (declared in Found, not done)"
    },
    {
      "severity": "minor",
      "where": "frontend/src/components/Map.tsx:183 (locale); map canvas and attribution button",
      "what": "English accessible names left from MapLibre defaults: 'Map', 'Toggle attribution'",
      "observed": "Tab walk at 1440: focus reaches 'Map' and 'Toggle attribution' (shots/extra.json tab_order)",
      "to_pass": "add the remaining MapLibre locale keys (Map.Title, AttributionControl.ToggleAttribution, etc.) with copy.es.json strings"
    },
    {
      "severity": "minor",
      "where": "frontend/src/components/WebcamsSection.tsx:76-82; Webcams panel 1440 and 375",
      "what": "Webcam rows print raw DGT strings: 'PK 12.6' with a decimal point, province in capitals 'GRANADA', not sorted by PK; differs from the T4.0 mockup row ('PK 12,6', provider DGT, sorted)",
      "observed": "shots/app-webcams-1440.webp vs shots/mock-webcams-1440.webp (side-webcams-1440.webp)",
      "to_pass": "format PK with Spanish decimals, sort by PK, show provider as in the mockup (T3.4/T4.4 if out of T4.1 scope)"
    },
    {
      "severity": "minor",
      "where": "Agua list and basin title",
      "what": "'Río Cadiar' without the accent; mockup has 'Cádiar'",
      "observed": "shots/app-agua-hover-1440.webp",
      "to_pass": "accented display names (declared in Found, not done)"
    }
  ],
  "followups": [
    "Map hover state on basins (only cursor today) to match the mockup intent, T4.4",
    "URL state (date and layer) is T4.2 scope; none today",
    "cedar-vista local build shows only the sign-in landing; future G-UI runs need a guest-mode build or credentials to screenshot its viewer in the same run"
  ]
}
```
