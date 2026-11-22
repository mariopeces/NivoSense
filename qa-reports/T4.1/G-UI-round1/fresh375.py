"""Fresh 375 loads: are the park and basin outlines drawn before any interaction?"""
import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    for i in range(2):
        ctx = b.new_context(viewport=dict(width=375, height=812)); p = ctx.new_page()
        logs = []; p.on('console', lambda m: logs.append(m.type + ' ' + m.text))
        p.on('requestfinished', lambda r: logs.append('req ' + r.url) if 'geojson' in r.url else None)
        p.goto(sys.argv[1], wait_until='networkidle'); p.wait_for_timeout(12000)
        p.screenshot(path=f'shots/x-fresh-375-run{i}-12s.png'); print(i, logs[:8]); ctx.close()
    b.close()
