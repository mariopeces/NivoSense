# NivoSense design spec (T4.0)

Every interface task follows this folder: T4.1 to T4.5, T3.4 and the validation page in T2.6. If a screen needs something not written here, ask the coordinator or extend this spec in the same PR. Don't improvise in code.

| File | What it is |
|---|---|
| [`tokens.json`](tokens.json) | UI tokens: colour, type, spacing, radius, shadow, motion, layout, z-order, icons, basemaps. **Source of truth for T4.1**: every token becomes a CSS variable `--<group>-<name>` and a Tailwind `theme.extend` entry. |
| [`ramps.json`](ramps.json) | Map colour ramps for observed snow, snow probability, SWE and depth, with their colour checks. Shared with the pipelines (tile colouring and legend constants) and read by the legends (T4.3). Generated, not hand-edited. |
| [`copy.es.json`](copy.es.json) | Spanish copy deck: every label, tooltip, empty, loading and error string, keyed for the frontend. |
| [`mockups/`](mockups/) | Static mockups (`index.html?s=<screen>`, plus `webcam-symbol.svg`). They read `tokens.json`, `ramps.json`, `copy.es.json` and real repo data, so they can only show what the spec defines. |
| [`screenshots/`](screenshots/) | Mockups at 1440x900 and 375x812, the reference screenshots, and the side-by-side sheets. |
| [`simulations/`](simulations/) | Colour-blind and greyscale simulations of the ramps, over the real S2 L1C image and over the light basemap. |
| [`tools/`](tools/) | Scripts that rebuild `ramps.json`, the simulations, the S2 pass list and the evidence sheets. |

## 1. Identity

NivoSense is a scientific viewer of one massif. The design has to look like an instrument a hydrologist or a park ranger trusts, not a marketing page, and the map is the product.

- **Pattern from cedar-vista**: a dark 64 px icon rail, a light collapsible panel with eyebrow, title and subtitle, layer rows with inline legend and opacity, and map tools docked at the foot of the rail. **From OpenPAS**: white cards with hairline borders, 8 to 12 px radii and soft shadows; status badges next to values.
- **What is NivoSense's own:**
  - **Pizarra** `#17202B` for the rail and text, from the dark mica schist (launa) of the Sierra Nevada crest. Cedar's rail is navy with a lime accent; ours is near-black slate.
  - **Arrebol** `#E0703F` as the only accent: the alpenglow on the crest at dusk. It marks one thing at a time: the active section, the selected basin, the timeline cursor and the selected camera. It never appears in a data ramp, so it can't be mistaken for data.
  - **Nevero** `#F3F5F8` for grouped surfaces.
  - **Source Serif 4** as the display face (panel titles, method page), with Inter for everything else. A serif title on a data panel reads as a reference work. Cedar uses Quicksand and OpenPAS uses Inter only, so the serif sets NivoSense apart.
  - **Status as shape, not only colour.** Observado is a solid glyph, Rellenado an outline, Modelado half-filled, Previsión dashed and Pendiente dotted. This holds for timeline ticks, badges and info popovers, and it survives colour blindness and greyscale.
  - **No top header.** The brand mark sits at the top of the rail, so the map gets the full height.
- **Rules that keep it from looking generated** (G-UI A and G):
  - no gradients except data ramps;
  - no glow, no blur, no glass;
  - icons only where they name an action or a state;
  - no text under 12 px (checked: the smallest computed text size on every mockup screen is 12 px);
  - eyebrows and group labels in sentence case with no extra tracking;
  - copy states facts and limits, never sells.

## 2. Tokens (summary; `tokens.json` is authoritative)

**Colour.** WCAG contrast is measured against white unless stated.

| Token | Value | Use | Contrast |
|---|---|---|---|
| `ink` / `text` | `#17202B` | rail, text, primary button, focus ring | 16.4:1 |
| `on-ink` | `#C3CCD6` | rail labels at rest | 10.1:1 on ink |
| `accent` | `#E0703F` | active rail bar, selected basin, timeline cursor | 5.1:1 on ink; 3.2:1 on white, so never used as text there |
| `accent-text` | `#B5502A` | accent as text on white | 5.1:1 |
| `text-muted` | `#5A6573` | secondary text, units, captions | 5.9:1; 5.4:1 on nevero |
| `status-gapfilled` / `-modelled` / `-forecast` | `#3F6283` / `#6C4F8F` / `#7A5B1E` | badges and ticks | 6.4 / 6.7 / 6.3:1 |
| `live` / `warning` / `danger` | `#2E7048` / `#8A5A00` / `#B0362C` | live camera, stale data, load errors | 6.0 / 5.9 / 6.2:1 |

An offline camera is a state, not an error: it uses `text-muted`, not `danger`.

**Type.** Inter 400/500/600 and Source Serif 4 600, both OFL and both on Google Fonts. Scale in px (size/line):

| Style | Size/line | Font | Used for |
|---|---|---|---|
| caption | 12/16 | Inter | rail, legend and axis labels |
| small | 13/18 | Inter | row metadata |
| body | 14/20 | Inter | default text |
| lead | 16/24 | Inter | method page body |
| value | 20/24 | Inter | headline numbers |
| title | 22/28 | Source Serif 4 | panel titles |
| display-l | 28/34 | Source Serif 4 | method page section headings |
| display-xl | 36/42 | Source Serif 4 | method page title |

Every number and date uses tabular figures (`tnum`).

**Spacing** follows a 4 px grid. **Radii**:

- 4 px for swatches, legend bars and badges;
- 8 px for buttons, rows and inputs;
- 12 px for cards, popovers, the timeline bar and the sheet;
- full for dots and toggles.

**Shadows** are three plain drop shadows (`panel`, `float`, `popover`).

**Motion**:

- 120 ms for hover and press;
- 200 ms for popovers;
- 240 ms for the panel and the sheet;
- 800 ms per frame when the timeline plays, waiting for the tiles before it steps;
- every duration drops to 0 under `prefers-reduced-motion`.

**Icons.** One set: [Lucide](https://lucide.dev) 0.460.0 (ISC licence), `lucide-react` in the app.

- **Stroke rule:** 1.75 px at every size (`absoluteStrokeWidth`), round caps and joins, no fills, `currentColor`.
- **Sizes:** 20 px in the rail, 16 px inline.

| Use | Lucide name |
|---|---|
| Nieve | `snowflake` |
| Agua | `droplets` |
| Webcams | `cctv` |
| Meteo | `cloud-sun-rain` |
| Método | `book-open-text` |
| Mapa base | `map` |
| 3D | `mountain` |
| Ocultar / mostrar | `panel-left-close` / `panel-left-open` |
| Show / hide layer | `eye` / `eye-off` |
| Layer info | `info` |
| Timeline | `chevron-left`, `play` / `pause`, `chevron-right`, `arrow-right-to-line`, `calendar` |
| Camera with no image | `camera-off` |
| Camera image older than 2 h | `clock` |
| Camera on the map (with image) | `cctv` inside the map symbol |
| Retry | `rotate-cw` |
| Back | `arrow-left` |
| Close | `x` |
| Zoom and north | `plus`, `minus`, `compass` |

No other icons.

**Basemaps.**

- **Claro (default):** IGN Base gris (`https://www.ign.es/wmts/ign-base`, layer `IGNBase-gris`, CORS open, CC BY 4.0 scne.es). It's a grey map with hillshade, so it never competes with the data colours.
- **Ortofoto PNOA (IGN):** for detail.
- The Sentinel-2 L1C image is a dated data layer in Nieve, not a basemap.

## 3. Map ramps (`ramps.json`)

Each ramp samples a published, perceptually uniform colour map at fixed positions, with stepped classes so tile colours, legend and data match exactly.

| Layer | Source map | Why this one | Classes |
|---|---|---|---|
| Observed snow (`snow_cover_observed`) | cmocean **ice** ([Thyng et al. 2016](https://doi.org/10.5670/oceanog.2016.66), built in CAM02-UCS for sea ice) | blue reads as snow on a map and stays visible over the white snow in the RGB, unlike white ramps | Nieve `#3E4891` 0.9; Nieve, confianza baja (bosque) `#5296C1` 0.8; Sin nieve transparent (the image shows through); Nube `#F4F2EE` 0.8 + dot pattern; Sin dato transparent + 45° hatch |
| Snow probability, gap-filled (`snow_cover_probability`) | cmocean **ice**, light to dark | same family as observed snow: "Nieve" is the same colour as ≥ 90 % | < 10 % transparent; 10–30, 30–50, 50–70, 70–90, ≥ 90 %. Alpha rises 0.45 to 0.9, so doubtful pixels stay faint |
| SWE (`swe`) | cmocean **deep** ([Thyng et al. 2016](https://doi.org/10.5670/oceanog.2016.66), built for water depth) | a different hue path from the snow layers (yellow-green, teal, navy), so SWE is never mistaken for cover | < 5 mm transparent (README section 6); 5–25 mm light green at alpha 0.4, so **trace snow never reads as solid cover**; 25–50, 50–100, 100–200, 200–400, 400–800, ≥ 800 mm |
| Snow depth (`snow_depth`) | Crameri **acton** ([Crameri 2018](https://doi.org/10.5281/zenodo.1243862); [Crameri et al. 2020](https://doi.org/10.1038/s41467-020-19160-7)), light to dark | a third hue family (lilac to violet) and different units: depth and SWE can't be confused when you switch between them | drawn only where SWE ≥ 5 mm (same mask); < 25 cm at alpha 0.5; 25–50, 50–100, 100–150, 150–200, 200–300, ≥ 300 cm |

Source files are fetched from pinned commits (cmocean `59c3500`, cmcrameri `7670e3c`). The class breaks are display choices, not data. T4.3 and G-Data check them against the real value range once T2.5 publishes, and change them here (rerun the builder) if the data asks for it.

**Checks** (`tools/build_ramps.py`; results are stored in `ramps.json` under `colour_checks`):

| Ramp | Lightness order kept in normal, deuteranopia, protanopia, tritanopia and greyscale | Minimum OKLab distance between adjacent classes (normal / deutan / protan / tritan / grey) |
|---|---|---|
| Snow probability | yes, all five | 0.105 / 0.108 / 0.098 / 0.103 / 0.101 |
| Observed snow (snow vs low confidence) | yes, all five | 0.225 / 0.222 / 0.236 / 0.222 / 0.224 |
| SWE | yes, all five | 0.107 / 0.099 / 0.107 / 0.097 / 0.100 |
| Depth | yes, all five | 0.062 / 0.050 / 0.049 / 0.066 / 0.056 |

How these numbers were produced:

- Colour-blind simulation: Machado, Oliveira & Fernandes 2009 at severity 1.0, applied in linear sRGB.
- Distances: OKLab (Ottosson 2020). One just-noticeable difference is about 0.02.
- Greyscale: Rec. 709 luminance.
- Cloud and Sin dato are told apart by pattern (dots versus hatch) as well as by colour, so they survive every simulation.

**Readability over the backgrounds.** Tested on real pixels:

- The **L1C** background is S2C_30SVG_20260221_1_L1C, ESA TCI, over the Veleta–Mulhacén crest, read unsigned from `sentinel-s2-l1c`. 37 % of its pixels are bright snow.
- The **light basemap** background is IGN Base gris over the same extent.

`colour_checks.visibility_mean_deltaE_ok` gives each class's mean OKLab shift over bright and dark pixels. Every class after the first shifts the background by at least 0.11 over dark terrain in the L1C, at least 0.15 over bright snow in the L1C, and at least 0.11 over the IGN basemap. The first class of each ramp is faint on purpose: 0.04 to 0.08 over bright pixels, still above a just-noticeable difference. Cloud over bright snow shifts the colour only 0.03; its dot pattern carries it.

**Evidence images:**

- [ramps-cvd-greyscale.png](simulations/ramps-cvd-greyscale.png)
- over L1C: [normal](simulations/over-l1c.webp), [deuteranopia](simulations/over-l1c-deuteranopia.webp), [protanopia](simulations/over-l1c-protanopia.webp), [greyscale](simulations/over-l1c-greyscale.webp)
- over IGN: [normal](simulations/over-ign.webp), [deuteranopia](simulations/over-ign-deuteranopia.webp), [protanopia](simulations/over-ign-protanopia.webp), [greyscale](simulations/over-ign-greyscale.webp)

**Pipeline contract.**

- Raster tiles are coloured with exactly these classes; patterns are baked into the tile at the spacing given.
- Class keys of observed snow (`snow`, `snow_low_confidence`, `no_snow`, `cloud`, `unknown`) are what T1.2's codes map to.
- The frontend never hard-codes a ramp colour; it reads `ramps.json`.

## 4. Screens

Open a screen with `python -m http.server` from the repo root, then go to `/docs/design/mockups/index.html?s=<id>`. Below 768 px the same page switches to the mobile layout. Screenshots are in [`screenshots/mockups/`](screenshots/mockups/) as `<id>-1440.webp` and `<id>-375.webp`; contact sheets: [all screens 1440](screenshots/all-screens-1440.webp), [all screens 375](screenshots/all-screens-375.webp).

| id | Screen | What it specifies |
|---|---|---|
| `nieve` | Shell, Nieve section | Rail with brand mark, five sections and map tools at the foot; 320 px panel with eyebrow, serif title and subtitle; grouped layer rows; legend chip on the map naming the visible layer and its date; map controls top right; attribution bottom right; bottom-centred timeline. |
| `capas` | Layer rows expanded | Every snow layer with its inline stepped legend, units, transparent-class note, opacity slider and status badge. Pending layers keep their legend so the reader learns it, but the toggle and slider are disabled. |
| `nieve-info` | Layer info popover | Source, resolution, frequency, date of the real observation, status, source scene ids, one-line description, link to the method. |
| `colapsado` | Panel collapsed | Panel slides out (240 ms), the timeline re-centres, and the rail button changes to "Mostrar". |
| `timeline` | Timeline | Date with weekday, previous / play / next, a track over the whole season (Oct 2025 to today) plus the forecast slot after "Hoy", observation ticks, the daily status strip (all Pendiente today: no gap-filled or model product exists), month labels, the arrebol cursor, a dashed "Hoy" line, a tick tooltip with the long date and statuses (kept inside the viewport), "Última" and a calendar button, and the status legend. |
| `timeline-estados` | Timeline states (spec sheet) | Each state drawn with the component's own CSS: Observado tick (solid), Rellenado day (outline), Modelado day (half-filled), Previsión day (dashed), Pendiente (dotted), and a schematic strip in abstract day units (no dates, no data) showing their order: past days, the "Hoy" line, forecast days, then the empty rest of the forecast slot. |
| `agua` | Basin list | The 4 basins in `data/basins.geojson`, sorted by area, with their real area. |
| `cuenca` | Basin panel | Selected basin outlined in arrebol on the map; key figures (area real, the rest Pendiente); season charts (this season solid, last season dashed) with empty axes and a stated reason; river flow block with the real station and source, Pendiente. |
| `webcams` | Webcam list + offline card | Cameras grouped Con imagen / Sin imagen with counts; offline card anchored to its symbol; symbol legend (cone, no image, no bearing); Cetursa block pending. |
| `webcam-live` | Live card | Large image, En directo, capture time and age (`formats.edad`: min, h, días, then the date), bearing state, credit line from gate H4, provider link. The age is computed against the viewer's clock, so opening the mockup later shows the real, older age; past 2 h the status becomes "Imagen antigua" (`warning`, `clock` icon) with the line "Imagen antigua: tiene más de 2 h". `?now=<ISO>` pins the clock for reproducible screenshots. On mobile it is the full-width sheet above the tab bar, the same as the offline card. |
| `metodo` | Method page | Full-width reading view next to the rail; table of contents; facts strip (source, resolution, frequency) per layer; "how it is computed", "how it is validated", "result pending" box, known limits. Text follows README section 6. |
| `vacio` | Empty | No catalogue yet: basemap, basins and cameras still work; panel notice; every layer Pendiente; timeline says why it is empty and from when it will fill. |
| `cargando` | Loading | Skeleton rows, `aria-live` label, no timeline until the catalogue answers. |
| `error` | Error | Catalogue failed: error notice with Reintentar; basemap stays usable; no timeline (dates are unknown). |

Also: [`webcam-symbol.svg`](mockups/webcam-symbol.svg) ([png](screenshots/mockups/webcam-symbol.webp)), the map symbol spec for T3.4: cone geometry from θ (bearing), φ (field of view) and r (range); five states (rest, hover/focus, selected, image without verified bearing, no image). The SVG and the mockups use the same glyphs: an ink disc with Lucide `cctv` for a camera with an image, a white disc with a `text-muted` border and Lucide `camera-off` for no image. **What rotates to the bearing is the notch on the disc rim**; the `cctv` glyph stays upright so it stays legible. A camera without a verified bearing has no notch and no cone.

### 4.1 Layout rules

**Desktop (≥ 768 px):**

- The rail is 64 px, fixed. The panel is 320 px, over the map, with the `panel` shadow.
- Nothing else floats over the map except:
  - the timeline (bottom centre, at most 1000 px wide, 24 px from the edges);
  - the legend chip (top left of the map area);
  - the map controls (top right);
  - the attribution (bottom right);
  - a popover or card the user opened.
- Basin charts live in the panel, never over the map (T4.4).

**Mobile (< 768 px):**

- The rail becomes a 60 px bottom tab bar with the same five sections; the accent bar moves to the top edge of the active tab.
- The panel becomes a bottom sheet with three heights:
  - peek 132 px: handle, eyebrow, title, subtitle;
  - half 50 vh;
  - full, leaving 48 px of map.
- The timeline sits above the sheet in peek and half, and hides when the sheet is full or a card is open.
- Map controls are 44 px; the attribution collapses to an `info` button.
- The webcam card (live or offline) becomes a full-width sheet above the tab bar and replaces the panel sheet while it is open.
- Map tools (basemap, 3D) move into the Nieve panel header on mobile (T4.5).

### 4.2 Interaction

**Keyboard.** Tab order: rail, panel, timeline, map controls.

- In the rail, arrow keys move between sections.
- The timeline track is a `slider`:
  - ← / → step one day;
  - Shift + ← / → jump to the previous or next date with an observation;
  - Home and End go to the first and latest date;
  - Space plays and pauses.
- Esc closes a popover or card and returns focus to the button that opened it.
- Focus ring: 2 px `focus` with a 2 px offset; on the rail the ring is white.

**States:**

- Hover: background `panel-soft` (rail: `ink-raised`).
- Selected: arrebol (rail bar, basin outline, camera ring) plus a stronger border.
- Hover and selected never share a look.

**URL** keeps section, date, visible layers with opacity, selected basin and selected camera, for example `?s=nieve&d=2026-02-21&l=rgb:100,obs:80&b=604456`. Basins are keyed by `cod_uni`.

**Timeline content:**

- Ticks come only from `catalog/index.json`.
- **Forecast days** sit after the "Hoy" line, in a forecast slot that runs to the last forecast date in the catalogue (the mockup draws 5 days, the horizon of the live site's forecast buttons today). Forecast days with a product are drawn dashed (Previsión); the rest of the slot is Pendiente on a `panel-soft` ground. The slot is labelled "Previsión". Nothing in the slot is drawn as observed.
- The daily strip shows, per day, the best status available (Observado > Rellenado > Modelado > Previsión); days with nothing are dotted (Pendiente).
- Picking a date with no product for a layer keeps the layer visible at its nearest date and says so in the row ("Sin escena este día. La más cercana: …").

## 5. Copy

[`copy.es.json`](copy.es.json) has every string.

- **Tone:** plain and precise; actions as short "tú" imperatives ("Elige", "Activa"), never "usted"; no exclamation marks, no marketing words.
- **Formats:** dates like "21 feb 2026"; the long form "sábado 21 de febrero de 2026" in tooltips; Europe/Madrid time "00:22"; "hace 4 min"; a space before units ("20 m", "25 mm", "50 %"); decimal comma; a thin space for thousands only from 10 000.
- **Status words:** Observado, Rellenado, Modelado, Previsión, Pendiente. Each has a one-sentence tooltip.
- **Credit lines:** Cetursa uses the exact gate H4 line, "Imagen: Cetursa Sierra Nevada / feratel". DGT: "Imagen: Dirección General de Tráfico (DGT)", linked to the DGT page (T3.2).
- **Basin attribution** stays empty until T2.1 records the source of the sub-basins; it is not guessed.

## 6. What the mockups show, and where it comes from

Nothing in the mockups is invented. Every value traces to a file or a live source:

| Shown | Source |
|---|---|
| Basins, names, areas (319,2 / 303,6 / 113,6 / 123,1 km²) | `data/basins.geojson` (`nom_rio_1`, `area_km2`); names re-cased with accents only |
| 8 DGT cameras "A-395 · PK …", all offline, no image | `frontend/public/data/webcams.json` (the live catalogue today) |
| River station "Órgiva · Río Guadalfeo", source Hidrosur | `data/flow/guadalfeo.json`. Its series is marked `PLACEHOLDER` in the file, so the mockup shows the flow as Pendiente, not the numbers. |
| Timeline ticks | Every S2 L1C pass over tiles 30SVF/30SVG/30SWF/30SWG from 2025-10-01 to 2026-11-20 listed on Earth Search ([`mockups/data/s2_passes.json`](mockups/data/s2_passes.json), `tools/fetch_s2_passes.py`). They are shown without the domain cloud filter that the catalogue (D1) will apply, so production will have fewer ticks. None of these products is published yet. |
| "Color real" image and its four scene ids | Real S2 L1C TCI of 2026-02-21 (ESA's TCI stretch, not the snow stretch T1.3 will make), cropped to the crest ([`mockups/data/l1c_tci_20260221.jpg`](mockups/data/l1c_tci_20260221.jpg), `tools/fetch_backgrounds.py`). It stands in for the RGB layer to show the filled state; T1.3 has not published it. Contains modified Copernicus Sentinel data 2026. |
| Pradollano image and its capture time | One still of `recursos.sierranevada.es/.../pradollano/snap_c1.jpg` (the URL named in T3.1), saved with its HTTP `Last-Modified` (2026-11-22 00:25:38 UTC) in [`mockups/data/cetursa_pradollano.json`](mockups/data/cetursa_pradollano.json), shown with the H4 credit line. Its map position is not in the catalogue yet (T3.1), so the card is shown unanchored and the camera is not drawn on the map. |
| Snow layers, SWE, depth, basin series, snow area | Not produced yet: every one is Pendiente with its legend. |
| Bearings and cones | Not measured yet (T3.3): no camera shows a cone or a rotated icon on the map; the cone is specified with symbolic θ, φ, r in `webcam-symbol.svg`. |

## 7. G-UI self-check on the mockups (sections A to E)

| Section | Check | Result and evidence |
|---|---|---|
| A. Visual system | Colours, type, radius, shadow from tokens only | Pass. `app.css` and `app.js` contain no colour literals (only `var(--…)` set from `tokens.json`, plus ramp colours read from `ramps.json`). |
| A | One display face + Inter, loaded | Pass: Source Serif 4 + Inter from Google Fonts. |
| A | No text under 12 px | Pass: the smallest computed font size measured on all 14 screens at 1440 is 12 px. |
| A | No all-caps blocks with wide tracking; no glow or glassmorphism | Pass: sentence case everywhere, letter-spacing 0; plain shadows, no `backdrop-filter`. |
| B. Layout | Dark rail + light collapsible panel; only timeline, legend chip and controls float; map is the hero | Pass: `nieve`, `colapsado`, mobile tab bar + sheet. |
| C. Information | Source, resolution, real observation date, status on every layer; units; honest empty and offline states | Pass: layer rows and `nieve-info`; legends carry units; `vacio`, `cargando`, `error`, offline card, Pendiente everywhere data is missing. |
| D. Interaction | Timeline over the whole history; keyboard; URL state; distinct hover and selected | Specified in 4.2; the mockup timeline spans 2025-10-01 to today. Behaviour is verified on the real build in T4.2. |
| E. Webcams | Icon to bearing, cone from bearing/FOV/range, card with large image, age and credit, offline state | Pass at spec level: `webcam-symbol.svg` and the mockups share one symbol system; `webcam-live` always shows capture time and age; both cards are sheets on mobile. Pending on T3.3 for real bearings: no cone is drawn until then. |

The side-by-side sheets show the references and the current site next to the mockup: [1440](screenshots/side-by-side-1440.webp), [375](screenshots/side-by-side-375.webp).

- **cedar-vista**: a local build of `frontend/dist` with `publicGuestMode` forced on and its own `backend/app/services/data/layers.json` served as the catalogue. The live API answers 401 from localhost, and nothing in the cedar-vista repo was changed.
- **openpas-habitat.web.app**: "Log in as Guest".
- **The live NivoSense site** as it is today.

## 8. Rebuilding the evidence

From the repo root (Python with numpy, Pillow and rasterio; Playwright for the screenshots):

```
python -I docs/design/tools/fetch_backgrounds.py <tmp>/bg
python -I docs/design/tools/build_ramps.py --cache <tmp>/ramps --l1c <tmp>/bg/l1c_tci_20260221.png --basemap <tmp>/bg/ign_base_gris.png
python -I docs/design/tools/fetch_s2_passes.py 2026-11-21 docs/design/mockups/data/s2_passes.json
# serve the repo root, screenshot every ?s=<id> at 1440x900 and 375x812 into screenshots/mockups/*.png
python -I docs/design/tools/compose_evidence.py   # sheets, then PNG to WebP
```

## 9. Out of scope here, for the tasks that follow

- **Meteo panel layout:** forecast layers stay as today until a card covers them. A precipitation ramp is not defined here.
- **The data-status line from T5.1** (`estado_servicio.*` strings exist in the copy deck).
- **Map tools on mobile** (basemap, 3D) live in the Nieve panel header: specified in 4.1, drawn in T4.5.
- **Ski resort polygon:** a copy string exists, but the geometry is not in the repo yet. It needs a source before it is drawn.
