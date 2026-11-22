"""openpas viewer through 'Log in as Guest', same run, 1440 and 375."""
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    for w, h in [(1440, 900), (375, 812)]:
        ctx = b.new_context(viewport=dict(width=w, height=h)); p = ctx.new_page()
        p.goto('https://openpas-habitat.web.app', wait_until='networkidle', timeout=60000)
        p.get_by_text('Log in as Guest').click(); p.wait_for_timeout(9000)
        p.screenshot(path=f'shots/ref-openpas-viewer-{w}.png'); ctx.close()
    b.close()
