"""G-Code T4.1 round 2: apply each deliberate break alone, run the named check, record pass/fail, restore.

Usage: python breaks.py <frontend_dir> <out_json>
"""
import json, os, subprocess, sys, pathlib, time
ENV = {**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0"}

FE = pathlib.Path(sys.argv[1]); OUT = pathlib.Path(sys.argv[2])
DECK = '../docs/design/copy.es.json'
TOK = '../docs/design/tokens.json'

def vt(*files):
    return ['npx', 'vitest', 'run', '--testTimeout=60000', *files]

LINT = ['npx', 'eslint', '.']
BASE = ['node', 'eslint/check-colour-baseline.js']

# (id, origin, description, file, old, new, command)
BREAKS = [
    ('R1-1', 'round1', 'handleBasinSelect: drop setSection("agua")', 'src/App.tsx',
     '      setSection("agua");\n      setPanelOpen(true);\n      if (sheet', '      setPanelOpen(true);\n      if (sheet', vt('src/App.test.tsx')),
    ('R1-2', 'round1', 'rail arrow map reduced to { ArrowDown: 0 }', 'src/components/Rail.tsx',
     '{ ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }', '{ ArrowDown: 0 }', vt('src/components/Rail.test.tsx')),
    ('R1-3', 'round1', 'NEXT_SHEET.full = "full"', 'src/components/Panel.tsx',
     'full: "peek" }', 'full: "full" }', vt('src/components/Panel.test.tsx')),
    ('R1-4', 'round1', 'deck: rename rail.tooltip_meteo -> tooltip_meteoX', DECK,
     '"tooltip_meteo":', '"tooltip_meteoX":', vt('src/lib/copy.test.ts')),
    ('N-1', 'new', 'deck: drop estado.tooltip_observado (only reached via t(`estado.tooltip_${status}`))', DECK,
     '"tooltip_observado":', '"tooltip_observadoX":', vt('src/lib/copy.test.ts')),
    ('N-2', 'new', 'deck: rename capa.*.cadencia of the first layer (only reached via t(`capa.${layer}.cadencia`))', DECK,
     '"cadencia": "Cada pasada despejada"', '"cadenciaX": "Cada pasada despejada"', vt('src/lib/copy.test.ts')),
    ('N-3', 'new', 'code: new template key t(`rail.tip_${item.id}`) not in the deck', 'src/components/Rail.tsx',
     't(`rail.tooltip_${item.id}`)', 't(`rail.tip_${item.id}`)', vt('src/lib/copy.test.ts')),
    ('N-4', 'new', 'code: ternary key typo fila_capa.ocultar -> ocultarX (first occurrence)', 'src/components/NieveSection.tsx',
     'aria-label={t(on ? "fila_capa.ocultar"', 'aria-label={t(on ? "fila_capa.ocultarX"', vt('src/lib/copy.test.ts')),
    ('N-4b', 'new', 'code: lowercase ternary key typo fila_capa.ocultar -> ocultr', 'src/components/NieveSection.tsx',
     'aria-label={t(on ? "fila_capa.ocultar"', 'aria-label={t(on ? "fila_capa.ocultr"', vt('src/lib/copy.test.ts')),
    ('N-4c', 'new', 'code: camel-case typo in a literal t() key, t("leyenda.swe") -> t("leyenda.sweTotal")', 'src/components/Legend.tsx',
     '"leyenda.swe"', '"leyenda.sweTotal"', vt('src/lib/copy.test.ts')),
    ('N-4d', 'new', 'code: typo in the top-level section of a literal t() key, t("leyenda.swe") -> t("leyendas.swe")', 'src/components/Legend.tsx',
     '"leyenda.swe"', '"leyendas.swe"', vt('src/lib/copy.test.ts')),
    ('N-4e', 'new', 'code: typo in the section of a plain t() key, t("rail.tooltip_mapa_base") -> t("rails.tooltip_mapa_base")', 'src/components/Rail.tsx',
     't("rail.tooltip_mapa_base")', 't("rails.tooltip_mapa_base")', vt('src/lib/copy.test.ts')),
    ('N-4d-full', 'new', 'as N-4d, whole vitest suite', 'src/components/Legend.tsx',
     '"leyenda.swe"', '"leyendas.swe"', vt()),
    ('N-4e-full', 'new', 'as N-4e, whole vitest suite', 'src/components/Rail.tsx',
     't("rail.tooltip_mapa_base")', 't("rails.tooltip_mapa_base")', vt()),
    ('N-4f-full', 'new', 'code: section typo in a direct t() literal on the legend path, t("leyenda.experimental") -> t("leyendas.experimental"); whole suite', 'src/components/Legend.tsx',
     't("leyenda.experimental")', 't("leyendas.experimental")', vt()),
    ('N-5', 'new', 'handleBasinSelect: drop setPanelOpen(true)', 'src/App.tsx',
     '      setSection("agua");\n      setPanelOpen(true);\n      if (sheet', '      setSection("agua");\n      if (sheet', vt('src/App.test.tsx')),
    ('N-6', 'new', 'calendar enables days without a scene', 'src/components/DateBar.tsx',
     'disabled={!scene}', 'disabled={false}', vt('src/components/DateBar.test.tsx')),
    ('N-7', 'new', 'next button never disabled (steps past the last scene)', 'src/components/DateBar.tsx',
     'disabled={index >= scenes.length - 1}', 'disabled={false}', vt('src/components/DateBar.test.tsx')),
    ('N-8', 'new', 'Home jumps to the second section', 'src/components/Rail.tsx',
     'if (key === "Home") return SECTIONS[0].id;', 'if (key === "Home") return SECTIONS[1].id;', vt('src/components/Rail.test.tsx')),
    ('N-9', 'new', 'panel never gets is-collapsed', 'src/components/Panel.tsx',
     '${open ? "" : "is-collapsed"}', '${open ? "" : ""}', vt('src/components/Panel.test.tsx')),
    ('N-10', 'new', 'desktop map inset ignores the collapsed panel', 'src/App.tsx',
     'rail + (panelOpen ? tokenPx("layout-panel-width") : 0)', 'rail + tokenPx("layout-panel-width")', vt('src/App.test.tsx')),
    ('N-11', 'new', 'tokens.css hand edit (one hex)', 'src/styles/tokens.css',
     '--color-accent: #E0703F;', '--color-accent: #E0703E;', vt('scripts/build-tokens.test.mjs')),
    ('N-12', 'new', 'tokens.json edit without regenerating tokens.css', TOK,
     '"#E0703F"', '"#E0703E"', vt('scripts/build-tokens.test.mjs')),
    ('N-13', 'new', 'hard-coded hex class in a shell component', 'src/components/Panel.tsx',
     'bg-panel shadow-panel', 'bg-[#ffffff] shadow-panel', LINT),
    ('N-14', 'new', 'inline style hex in Rail', 'src/components/Rail.tsx',
     'aria-label={t("app.nombre")}', 'aria-label={t("app.nombre")} style={{ color: "#ff0000" }}', LINT),
    ('N-15', 'new', 'webcam PK keeps the decimal point', 'src/components/WebcamsSection.tsx',
     'km.replace(".", ",")', 'km', vt('src/components/WebcamsSection.test.ts')),
    ('N-16', 'new', 'Agua list sorted ascending by area', 'src/components/AguaSection.tsx',
     '(b.areaKm2 ?? 0) - (a.areaKm2 ?? 0)', '(a.areaKm2 ?? 0) - (b.areaKm2 ?? 0)', vt('src/App.test.tsx')),
    ('N-17', 'new', 'Map: drop the style.load handler (layers lost on setStyle)', 'src/components/Map.tsx',
     '    map.on("style.load", setupLayers);\n', '', vt()),
    ('N-18', 'new', 'mobile half sheet inset uses the peek height', 'src/App.tsx',
     'sheet === "peek" ? tokenPx("layout-sheet-peek") : viewportHeight / 2', 'tokenPx("layout-sheet-peek")', vt()),
]

ONLY = set(sys.argv[3].split(',')) if len(sys.argv) > 3 else None
results = []
for bid, origin, desc, rel, old, new, cmd in BREAKS:
    if ONLY and bid not in ONLY: continue
    f = FE / rel
    src = f.read_bytes().decode('utf-8')
    n = src.count(old)
    if n < 1:
        results.append(dict(id=bid, origin=origin, what=desc, applied=False, note=f'pattern not found in {rel}'))
        print(bid, 'NOT APPLIED', flush=True); continue
    f.write_bytes(src.replace(old, new, 1).encode('utf-8'))
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=FE, capture_output=True, text=True, encoding='utf-8', errors="replace", shell=True, env=ENV)
        tail = (p.stdout + p.stderr).strip().splitlines()
        summary = [l for l in tail if ('Tests' in l and ('passed' in l or 'failed' in l)) or 'problem' in l or 'error' in l.lower()][-4:]
        fails = [l.strip() for l in tail if l.strip().startswith(('×', 'FAIL', '✗')) or ' FAIL ' in l][:6]
        results.append(dict(id=bid, origin=origin, what=desc, file=rel, command=' '.join(cmd), exit=p.returncode,
                            caught=p.returncode != 0, seconds=round(time.time() - t0), summary=summary, failing=fails))
    finally:
        f.write_bytes(src.encode('utf-8'))
    print(bid, 'CAUGHT' if results[-1]['caught'] else 'MISSED', results[-1]['seconds'], 's', flush=True)
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')

OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
