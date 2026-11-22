"""G-UI T4.1 round 1: renders of the PR #25 build, the T4.0 mockups, cedar-vista and openpas in one run.

Usage: python shoot.py <out_dir> <app_url> <mockups_url> <cedar_url> <axe.min.js>
"""
import json, sys, pathlib
from playwright.sync_api import sync_playwright

OUT = pathlib.Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
APP, MOCK, CEDAR, AXE = sys.argv[2], sys.argv[3], sys.argv[4], pathlib.Path(sys.argv[5]).read_text(encoding='utf-8')
VIEWS = {'1440': dict(width=1440, height=900), '375': dict(width=375, height=812)}
SECTIONS = ['Nieve', 'Agua', 'Webcams', 'Meteo', 'Método']

AUDIT = r"""() => {
  const out = {minFont: 99, minFontEl: '', capsTracked: [], backdrop: [], gradients: [], textShadow: [],
               colouredShadows: [], fontsLoaded: [], families: {}};
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0 || r.right < 0 || r.bottom < 0 || r.left > innerWidth || r.top > innerHeight) continue;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (own) {
      const fs = parseFloat(cs.fontSize);
      if (fs < out.minFont) { out.minFont = fs; out.minFontEl = String(el.className).slice(0, 60) + ' :: ' + el.textContent.trim().slice(0, 40); }
      const ls = parseFloat(cs.letterSpacing) || 0;
      if (cs.textTransform === 'uppercase' && ls > 0.5) out.capsTracked.push(el.textContent.trim().slice(0, 30));
      if (cs.textShadow && cs.textShadow !== 'none') out.textShadow.push(String(el.className).slice(0, 60));
      const fam = cs.fontFamily.split(',')[0].replace(/"/g, '').trim();
      out.families[fam] = (out.families[fam] || 0) + 1;
    }
    if (cs.backdropFilter && cs.backdropFilter !== 'none') out.backdrop.push(String(el.className).slice(0, 60));
    if (/gradient/.test(cs.backgroundImage)) out.gradients.push(String(el.className).slice(0, 60) + ' ' + cs.backgroundImage.slice(0, 80));
    if (cs.boxShadow && cs.boxShadow !== 'none' && !/rgba\(0, 0, 0|rgba\(23, 32, 43|rgba\(15, 23/.test(cs.boxShadow)) out.colouredShadows.push(String(el.className).slice(0, 50) + ' ' + cs.boxShadow.slice(0, 80));
  }
  out.fontsLoaded = [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family + ' ' + f.weight);
  return out;
}"""

def axe(p):
    p.add_script_tag(content=AXE)
    r = p.evaluate("""async () => { const r = await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21aa','best-practice']}});
      return {violations: r.violations.map(v => ({id: v.id, impact: v.impact, n: v.nodes.length, t: v.nodes.slice(0,3).map(n => n.target.join(' '))})), passes: r.passes.length}; }""")
    return r


def watch(p):
    log = {'console': [], 'failed': []}
    p.on('console', lambda m: log['console'].append(f'{m.type}: {m.text}') if m.type in ('error', 'warning') else None)
    p.on('pageerror', lambda e: log['console'].append(f'pageerror: {e}'))
    p.on('requestfailed', lambda r: log['failed'].append(f'FAILED {r.url} {r.failure}'))
    p.on('response', lambda r: log['failed'].append(f'{r.status} {r.url}') if r.status >= 400 else None)
    return log


def app(b):
    rep = {}
    for vk, vp in VIEWS.items():
        ctx = b.new_context(viewport=vp, device_scale_factor=1, locale='es-ES', timezone_id='Europe/Madrid')
        p = ctx.new_page(); log = watch(p)
        p.goto(APP, wait_until='networkidle'); p.wait_for_timeout(4000)
        r = rep[vk] = {'sections': {}}
        r['datebar'] = p.evaluate("() => [...document.querySelectorAll('body *')].filter(e => /escena|fecha/i.test(e.textContent) && e.children.length===0).map(e=>e.textContent.trim()).slice(0,6)")
        for s in SECTIONS:
            p.get_by_role('tab', name=s).click(); p.wait_for_timeout(1200)
            key = s.lower().replace('é', 'e')
            p.screenshot(path=str(OUT / f'app-{key}-{vk}.png'))
            r['sections'][key] = {'audit': p.evaluate(AUDIT), 'axe': axe(p),
                                  'panel_text': p.locator('#panel').inner_text()[:1500]}
        # keyboard on the rail
        p.get_by_role('tab', name='Nieve').click(); p.get_by_role('tab', name='Nieve').focus()
        seq = []
        for k in ['ArrowDown', 'ArrowDown', 'End', 'Home', 'ArrowUp']:
            p.keyboard.press(k)
            seq.append(p.evaluate("() => [document.activeElement.textContent, document.querySelector('[role=tab][aria-selected=true]').textContent]"))
        r['rail_keys'] = seq
        p.get_by_role('tab', name='Nieve').click()
        p.keyboard.press('Tab'); r['tab_after_rail'] = p.evaluate("() => document.activeElement.outerHTML.slice(0,160)")
        p.screenshot(path=str(OUT / f'app-focus-after-rail-{vk}.png'))
        # hover vs selected on rail
        p.get_by_role('tab', name='Meteo').hover(); p.wait_for_timeout(300)
        p.screenshot(path=str(OUT / f'app-hover-rail-{vk}.png'))
        if vk == '1440':
            # collapse
            p.get_by_role('button', name='Ocultar').click(); p.wait_for_timeout(600)
            p.screenshot(path=str(OUT / f'app-colapsado-{vk}.png'))
            r['collapsed_audit'] = p.evaluate(AUDIT)
            p.get_by_role('button', name='Mostrar').click(); p.wait_for_timeout(600)
        else:
            for i, h in enumerate(['half', 'full', 'peek']):
                p.get_by_role('button', name=p.evaluate("() => document.querySelector('#panel > button').getAttribute('aria-label')")).click()
                p.wait_for_timeout(600); p.screenshot(path=str(OUT / f'app-sheet-{i}-{h}-{vk}.png'))
        # basin: panel -> map
        p.get_by_role('tab', name='Agua').click(); p.wait_for_timeout(600)
        rows = p.locator('#panel ul button')
        r['basin_rows'] = rows.count()
        if rows.count():
            first = rows.nth(0).locator('span').first.inner_text(); r['basin_first'] = first
            rows.nth(0).hover(); p.wait_for_timeout(200); p.screenshot(path=str(OUT / f'app-agua-hover-{vk}.png'))
            rows.nth(0).click(); p.wait_for_timeout(3500)
            p.screenshot(path=str(OUT / f'app-cuenca-{vk}.png'))
            r['cuenca_text'] = p.locator('#panel').inner_text()[:1500]
            r['cuenca_axe'] = axe(p); r['cuenca_audit'] = p.evaluate(AUDIT)
            # back, then click map at the selected basin's location (the map fitted to it): map -> panel
            p.get_by_role('button', name='Todas las cuencas').click(); p.wait_for_timeout(800)
            canvas = p.locator('canvas.maplibregl-canvas').bounding_box()
            if vk == '1440':
                x = 64 + 320 + (1440 - 384) / 2; y = 450
            else:
                x = 187; y = 230
            p.mouse.click(x, y); p.wait_for_timeout(2500)
            r['map_click_title'] = p.locator('#panel h3').first.inner_text() if p.locator('#panel h3').count() else None
            r['map_click_section'] = p.evaluate("() => document.querySelector('[role=tab][aria-selected=true]').textContent")
            p.screenshot(path=str(OUT / f'app-cuenca-desde-mapa-{vk}.png'))
        if vk == '1440':
            # basemap switch: setStyle must keep the custom layers
            p.get_by_role('button', name='Mapa', exact=True).click(); p.wait_for_timeout(400)
            p.screenshot(path=str(OUT / f'app-mapa-base-{vk}.png'))
            p.get_by_label('Ortofoto PNOA (IGN)').check(); p.keyboard.press('Escape'); p.wait_for_timeout(5000)
            p.screenshot(path=str(OUT / f'app-ortofoto-{vk}.png'))
            p.mouse.click(64 + 320 + (1440 - 384) / 2, 450); p.wait_for_timeout(2000)
            r['after_setstyle_click_title'] = p.locator('#panel h3').first.inner_text() if p.locator('#panel h3').count() else None
            p.get_by_role('button', name='3D', exact=True).click(); p.wait_for_timeout(5000)
            p.screenshot(path=str(OUT / f'app-ortofoto-3d-{vk}.png'))
            p.get_by_role('button', name='Mapa', exact=True).click(); p.get_by_label('Claro (IGN)').check(); p.keyboard.press('Escape'); p.wait_for_timeout(4000)
            p.screenshot(path=str(OUT / f'app-vuelta-claro-3d-{vk}.png'))
            # map controls
            r['map_controls'] = p.evaluate("() => [...document.querySelectorAll('.maplibregl-ctrl button')].map(b => b.getAttribute('aria-label') || b.title)")
            r['attribution'] = p.evaluate("() => document.querySelector('.maplibregl-ctrl-attrib')?.innerText")
        r['console'] = log['console']; r['failed'] = log['failed']
        ctx.close()
    return rep


def mockups(b):
    for vk, vp in VIEWS.items():
        for s in ['nieve', 'colapsado', 'agua', 'cuenca', 'webcams', 'metodo', 'vacio']:
            ctx = b.new_context(viewport=vp, device_scale_factor=1, locale='es-ES')
            p = ctx.new_page(); p.goto(MOCK + '?s=' + s, wait_until='load'); p.wait_for_timeout(2500)
            p.screenshot(path=str(OUT / f'mock-{s}-{vk}.png')); ctx.close()


def refs(b):
    for vk, vp in VIEWS.items():
        for name, url in [('cedar', CEDAR), ('openpas', 'https://openpas-habitat.web.app')]:
            ctx = b.new_context(viewport=vp, device_scale_factor=1)
            p = ctx.new_page()
            try:
                p.goto(url, wait_until='networkidle', timeout=45000)
            except Exception:
                pass
            p.wait_for_timeout(4000); p.screenshot(path=str(OUT / f'ref-{name}-{vk}.png')); ctx.close()


with sync_playwright() as pw:
    b = pw.chromium.launch(args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    rep = app(b)
    (OUT / 'report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding='utf-8')
    mockups(b); refs(b)
    b.close()
print('ok')
