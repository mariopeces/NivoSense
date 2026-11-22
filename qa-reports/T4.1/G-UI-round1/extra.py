"""G-UI T4.1 r1 extra checks: fresh 375 load, map->panel from Nieve, map hover vs selected, panel keyboard, URL state."""
import json, sys, pathlib
from playwright.sync_api import sync_playwright
OUT = pathlib.Path(sys.argv[1]); APP = sys.argv[2]
rep = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    # fresh mobile load
    ctx = b.new_context(viewport=dict(width=375, height=812), locale='es-ES'); p = ctx.new_page()
    errs = []; p.on('console', lambda m: errs.append(m.type + ': ' + m.text) if m.type == 'error' else None)
    p.goto(APP, wait_until='networkidle'); p.wait_for_timeout(4000)
    p.screenshot(path=str(OUT / 'x-fresh-375.png'))
    # tap a basin on the map (centre of the visible map area above sheet)
    p.get_by_role('tab', name='Agua').click(); p.wait_for_timeout(800)
    rows = p.locator('#panel ul button'); rows.nth(1).click(); p.wait_for_timeout(3000)
    p.screenshot(path=str(OUT / 'x-cuenca-lista-375.png'))
    rep['m_list_title'] = p.locator('#panel h3').first.inner_text() if p.locator('#panel h3').count() else None
    p.get_by_role('tab', name='Nieve').click(); p.wait_for_timeout(800)
    rep['m_url_after'] = p.url
    rep['m_errors'] = errs
    ctx.close()
    # desktop: map click from Nieve, hover, keyboard, URL
    ctx = b.new_context(viewport=dict(width=1440, height=900), locale='es-ES'); p = ctx.new_page()
    p.goto(APP, wait_until='networkidle'); p.wait_for_timeout(4000)
    p.mouse.move(64 + 320 + 528, 450); p.wait_for_timeout(600)
    p.screenshot(path=str(OUT / 'x-map-hover-1440.png'))
    rep['cursor_on_basin'] = p.evaluate("() => getComputedStyle(document.querySelector('canvas.maplibregl-canvas')).cursor")
    p.mouse.click(64 + 320 + 528, 450); p.wait_for_timeout(3000)
    rep['from_nieve_section'] = p.evaluate("() => document.querySelector('[role=tab][aria-selected=true]').textContent")
    rep['from_nieve_title'] = p.locator('#panel h3').first.inner_text() if p.locator('#panel h3').count() else None
    rep['url_after_select'] = p.url
    p.mouse.move(700, 300); p.wait_for_timeout(600)
    p.screenshot(path=str(OUT / 'x-selected-plus-hover-1440.png'))
    # reload keeps state?
    p.reload(wait_until='networkidle'); p.wait_for_timeout(3000)
    rep['after_reload_section'] = p.evaluate("() => document.querySelector('[role=tab][aria-selected=true]').textContent")
    # keyboard walk: Tab through the page, record focus order and visible focus ring
    p.keyboard.press('Escape'); p.evaluate("() => document.activeElement.blur()")
    order = []
    for i in range(22):
        p.keyboard.press('Tab')
        order.append(p.evaluate("""() => { const e = document.activeElement; const cs = getComputedStyle(e);
          return (e.getAttribute('aria-label') || e.textContent.trim().slice(0,30) || e.tagName) + ' | outline=' + cs.outlineStyle + ' ' + cs.outlineWidth + ' shadow=' + (cs.boxShadow !== 'none'); }"""))
    rep['tab_order'] = order
    p.screenshot(path=str(OUT / 'x-keyboard-focus-1440.png'))
    # collapse via keyboard
    p.get_by_role('button', name='Ocultar').focus(); p.keyboard.press('Enter'); p.wait_for_timeout(500)
    rep['collapsed_kbd'] = p.get_by_role('button', name='Mostrar').count()
    rep['panel_hidden_focusable'] = p.evaluate("() => { const pn = document.querySelector('#panel'); return pn ? [pn.getAttribute('aria-hidden'), pn.inert, getComputedStyle(pn).visibility] : null; }")
    p.keyboard.press('Enter'); p.wait_for_timeout(500)
    # font of attribution, uppercase text in DOM
    rep['helvetica'] = p.evaluate("() => [...document.querySelectorAll('body *')].filter(e => getComputedStyle(e).fontFamily.startsWith('\"Helvetica')).map(e => e.className).slice(0,3)")
    rep['title'] = p.title(); rep['lang'] = p.evaluate("() => document.documentElement.lang")
    ctx.close(); b.close()
(OUT / 'extra.json').write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding='utf-8')
print('ok')
