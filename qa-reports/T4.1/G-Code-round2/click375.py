"""375: fresh load (sheet at peek), click inside the Guadalfeo basin on the map, record section, title and sheet."""
import json, sys
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    p = b.new_page(viewport=dict(width=375, height=812), locale='es-ES')
    errs = []; p.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None); p.on('pageerror', lambda e: errs.append(str(e)))
    p.goto(sys.argv[1], wait_until='networkidle'); p.wait_for_timeout(5000)
    p.screenshot(path='out/app-fresh-peek-375.png')
    h0 = p.evaluate("() => Math.round(document.getElementById('panel').getBoundingClientRect().height)")
    out = []
    for x, y in [(150, 250), (200, 240), (260, 240), (310, 230)]:
        p.mouse.click(x, y); p.wait_for_timeout(2500)
        out.append([x, y, p.evaluate("() => document.querySelector('[role=tab][aria-selected=true]').textContent"),
                    p.locator('#panel h3').first.inner_text() if p.locator('#panel h3').count() else None])
        if out[-1][3] and 'Río' in out[-1][3]: break
    p.screenshot(path='out/app-cuenca-desde-mapa-fresh-375.png')
    print(json.dumps({'peek_height': h0, 'clicks': out, 'errors': errs}, ensure_ascii=False))
    b.close()
