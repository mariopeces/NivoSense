import json, sys, pathlib
from playwright.sync_api import sync_playwright
OUT = pathlib.Path(sys.argv[1])
ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
with sync_playwright() as p:
    b = p.chromium.launch(args=ARGS)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=3, locale="es-ES", timezone_id="Europe/Madrid")
    pg = ctx.new_page(); pg.goto("http://localhost:4173/real/?d=2026-11-13", wait_until="domcontentloaded"); pg.wait_for_timeout(3000)
    box = pg.locator("[role=slider]").bounding_box()
    pg.screenshot(path=OUT / "10-1440-track-end-3x.png", clip={"x": box["x"] + box["width"] - 220, "y": box["y"] - 6, "width": 240, "height": box["height"] + 12})
    info = pg.evaluate("""() => { const t=document.querySelector('[role=slider]'); const hoy=[...t.querySelectorAll('span[title]')].map(s=>({title:s.title, text:s.innerText, left:s.style.left}));
      const today=[...t.querySelectorAll('span')].filter(s=>s.className.includes('border-dashed')&&s.className.includes('border-l')).map(s=>s.getBoundingClientRect().x);
      const cursor=[...t.querySelectorAll('span')].filter(s=>s.className.includes('bg-accent')&&s.className.includes('w-[2px]')).map(s=>s.getBoundingClientRect().x);
      return {titled: hoy, todayLineX: today, cursorX: cursor, trackRight: t.getBoundingClientRect().right, visibleHoyText: t.innerText.includes('Hoy'), visiblePrevision: t.innerText.includes('Previsión')}; }""")
    print(json.dumps(info, ensure_ascii=False))
    ctx.close()
    ctx = b.new_context(viewport={"width": 375, "height": 812}, device_scale_factor=2, locale="es-ES", timezone_id="Europe/Madrid")
    pg = ctx.new_page(); pg.goto("http://localhost:4173/real/", wait_until="domcontentloaded"); pg.wait_for_timeout(3000)
    sizes = pg.locator(".shell-timeline button").evaluate_all("els => els.map(e => { const r = e.getBoundingClientRect(); return [e.getAttribute('aria-label') || e.innerText, Math.round(r.width), Math.round(r.height)]; })")
    print(json.dumps(sizes, ensure_ascii=False))
    small = pg.evaluate("""() => [...document.querySelectorAll('.shell-timeline *')].filter(e => e.childNodes.length && [...e.childNodes].some(n => n.nodeType===3 && n.textContent.trim())).map(e => [e.textContent.trim().slice(0,20), getComputedStyle(e).fontSize]).filter(([,s]) => parseFloat(s) < 12)""")
    print("text under 12px:", small)
    pg.locator(".shell-timeline").screenshot(path=OUT / "11-375-timeline-2x.png")
    b.close()
