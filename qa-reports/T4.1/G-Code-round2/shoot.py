"""G-UI T4.1 round 2 (narrow): renders of the PR #25 build at 1440x900 and 375x812, audits, axe, console.

Adapted from round 1's shoot.py (qa-reports/T4.1/G-UI-round1 on mariopeces/g-t41-gui-r1); mockup and reference
renders dropped, round 1's are reused for comparison. Adds a Tab walk and a scan for English MapLibre names.

Usage: python shoot.py <out_dir> <app_url> <axe.min.js>
"""
import json, sys, pathlib
from playwright.sync_api import sync_playwright

OUT = pathlib.Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
APP, AXE = sys.argv[2], pathlib.Path(sys.argv[3]).read_text(encoding='utf-8')
VIEWS = {'1440': dict(width=1440, height=900), '375': dict(width=375, height=812)}
SECTIONS = ['Nieve', 'Agua', 'Webcams', 'Meteo', 'Método']

AUDIT = r"""() => {
  const out = {minFont: 99, minFontEl: '', capsTracked: [], backdrop: [], gradients: [], textShadow: [], fontsLoaded: []};
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0 || r.right < 0 || r.bottom < 0 || r.left > innerWidth || r.top > innerHeight) continue;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (own) {
      const fs = parseFloat(cs.fontSize);
      if (fs < out.minFont) { out.minFont = fs; out.minFontEl = el.textContent.trim().slice(0, 40); }
      if (cs.textTransform === 'uppercase' && (parseFloat(cs.letterSpacing) || 0) > 0.5) out.capsTracked.push(el.textContent.trim().slice(0, 30));
      if (cs.textShadow && cs.textShadow !== 'none') out.textShadow.push(el.textContent.trim().slice(0, 30));
    }
    if (cs.backdropFilter && cs.backdropFilter !== 'none') out.backdrop.push(String(el.className).slice(0, 60));
    if (/gradient/.test(cs.backgroundImage) && !el.closest('[class*=legend], [aria-label*=eyenda]')) out.gradients.push(String(el.className).slice(0, 60));
  }
  out.fontsLoaded = [...new Set([...document.fonts].filter(f => f.status === 'loaded').map(f => f.family + ' ' + f.weight))];
  return out;
}"""

MAPLIBRE_NAMES = r"""() => [...document.querySelectorAll('.maplibregl-map, .maplibregl-map *')]
  .flatMap(e => ['aria-label', 'title', 'aria-roledescription'].map(a => e.getAttribute(a)).filter(Boolean))"""


def axe(p):
    p.add_script_tag(content=AXE)
    return p.evaluate("""async () => { const r = await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa','best-practice']}});
      return {violations: r.violations.map(v => ({id: v.id, impact: v.impact, n: v.nodes.length, t: v.nodes.slice(0,3).map(n => n.target.join(' '))})), passes: r.passes.length}; }""")


def watch(p):
    log = {'console': [], 'failed': []}
    p.on('console', lambda m: log['console'].append(f'{m.type}: {m.text}') if m.type in ('error', 'warning') else None)
    p.on('pageerror', lambda e: log['console'].append(f'pageerror: {e}'))
    p.on('requestfailed', lambda r: log['failed'].append(f'FAILED {r.url} {r.failure}'))
    p.on('response', lambda r: log['failed'].append(f'{r.status} {r.url}') if r.status >= 400 else None)
    return log


def shot(p, name):
    p.screenshot(path=str(OUT / f'{name}.png'))


rep = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    for vk, vp in VIEWS.items():
        ctx = b.new_context(viewport=vp, device_scale_factor=1, locale='es-ES', timezone_id='Europe/Madrid')
        p = ctx.new_page(); log = watch(p)
        p.goto(APP, wait_until='networkidle'); p.wait_for_timeout(5000)
        r = rep[vk] = {'sections': {}}
        r['maplibre_names'] = sorted(set(p.evaluate(MAPLIBRE_NAMES)))
        for s in SECTIONS:
            p.get_by_role('tab', name=s).click(); p.wait_for_timeout(1500)
            key = s.lower().replace('é', 'e')
            shot(p, f'app-{key}-{vk}')
            r['sections'][key] = {'audit': p.evaluate(AUDIT), 'axe': axe(p), 'panel_text': p.locator('#panel').inner_text()[:2000]}
        # Tab walk from the top of the page: accessible names of every focus stop
        p.get_by_role('tab', name='Nieve').click(); p.evaluate("() => document.activeElement.blur()")
        walk = []
        for _ in range(40):
            p.keyboard.press('Tab')
            walk.append(p.evaluate("""() => { const e = document.activeElement; return e ? (e.tagName + ' ' + (e.getAttribute('aria-label') || e.getAttribute('title') || e.textContent.trim().slice(0, 40))) : null }"""))
        r['tab_walk'] = walk
        # rail keyboard
        p.get_by_role('tab', name='Nieve').focus()
        seq = []
        for k in ['ArrowDown', 'ArrowDown', 'End', 'Home', 'ArrowUp']:
            p.keyboard.press(k)
            seq.append(p.evaluate("() => document.querySelector('[role=tab][aria-selected=true]').textContent"))
        r['rail_keys'] = seq
        p.get_by_role('tab', name='Nieve').click(); p.wait_for_timeout(500)
        if vk == '1440':
            p.get_by_role('button', name='Ocultar').click(); p.wait_for_timeout(800)
            shot(p, f'app-colapsado-{vk}')
            r['collapsed'] = {'audit': p.evaluate(AUDIT), 'axe': axe(p)}
            p.get_by_role('button', name='Mostrar').click(); p.wait_for_timeout(800)
        else:
            heights = []
            for i, h in enumerate(['half', 'full', 'peek']):
                p.locator('#panel > button').first.click(); p.wait_for_timeout(800)
                heights.append(p.evaluate("() => Math.round(document.getElementById('panel').getBoundingClientRect().height)"))
                shot(p, f'app-sheet-{i}-{h}-{vk}')
            r['sheet_heights'] = heights
            r['sheet_axe'] = axe(p)
        # Agua list, basin from the panel, then from the map
        p.get_by_role('tab', name='Agua').click(); p.wait_for_timeout(800)
        rows = p.locator('#panel ul button')
        r['basin_rows'] = [rows.nth(i).inner_text().replace('\n', ' | ') for i in range(rows.count())]
        if rows.count():
            rows.nth(1).click(); p.wait_for_timeout(3500)
            shot(p, f'app-cuenca-{vk}')
            r['cuenca_text'] = p.locator('#panel').inner_text()[:1500]
            r['cuenca_axe'] = axe(p)
            p.get_by_role('button', name='Todas las cuencas').click(); p.wait_for_timeout(800)
            p.get_by_role('tab', name='Nieve').click(); p.wait_for_timeout(800)
            x, y = ((64 + 320 + (1440 - 384) / 2, 450) if vk == '1440' else (187, 230))
            p.mouse.click(x, y); p.wait_for_timeout(2500)
            r['map_click_section'] = p.evaluate("() => document.querySelector('[role=tab][aria-selected=true]').textContent")
            r['map_click_title'] = p.locator('#panel h3').first.inner_text() if p.locator('#panel h3').count() else None
            shot(p, f'app-cuenca-desde-mapa-{vk}')
        if vk == '1440':
            p.get_by_role('button', name='Todas las cuencas').click(); p.wait_for_timeout(500)
            p.get_by_role('button', name='Mapa', exact=True).click(); p.wait_for_timeout(400)
            p.get_by_label('Ortofoto PNOA (IGN)').check(); p.keyboard.press('Escape'); p.wait_for_timeout(5000)
            p.get_by_role('button', name='3D', exact=True).click(); p.wait_for_timeout(5000)
            p.get_by_role('button', name='Mapa', exact=True).click(); p.get_by_label('Claro (IGN)').check(); p.keyboard.press('Escape'); p.wait_for_timeout(4000)
            shot(p, f'app-vuelta-claro-3d-{vk}')
            p.get_by_role('tab', name='Nieve').click(); p.wait_for_timeout(500)
            p.mouse.click(64 + 320 + (1440 - 384) / 2, 450); p.wait_for_timeout(2500)
            r['after_setstyle_click'] = [p.evaluate("() => document.querySelector('[role=tab][aria-selected=true]').textContent"),
                                         p.locator('#panel h3').first.inner_text() if p.locator('#panel h3').count() else None]
            shot(p, f'app-tras-setstyle-clic-{vk}')
            r['basin_layers'] = p.evaluate("() => null")
        r['console'] = log['console']; r['failed'] = log['failed']
        ctx.close()
    b.close()
(OUT / 'report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding='utf-8')
print('ok')
