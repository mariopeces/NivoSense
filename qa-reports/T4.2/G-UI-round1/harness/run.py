"""G-UI round 1 for T4.2: real catalogue (T0.4 evidence), staging 404, bucket 403. Writes screenshots and JSON."""
import json, sys, time, pathlib
from playwright.sync_api import sync_playwright

OUT = pathlib.Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
AXE = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
BASE = "http://localhost:4173"
R = {}
ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]


def new(browser, w, h, path):
    ctx = browser.new_context(viewport={"width": w, "height": h}, locale="es-ES", timezone_id="Europe/Madrid")
    pg = ctx.new_page()
    log = {"console_errors": [], "page_errors": [], "failed_requests": []}
    pg.on("console", lambda m: m.type == "error" and log["console_errors"].append(m.text[:300]))
    pg.on("pageerror", lambda e: log["page_errors"].append(str(e)[:300]))
    pg.on("requestfailed", lambda r: log["failed_requests"].append(f"{r.url} {r.failure}"))
    pg.on("response", lambda r: r.status >= 400 and log["failed_requests"].append(f"{r.status} {r.url}"))
    pg.goto(BASE + path, wait_until="domcontentloaded")
    pg.wait_for_timeout(2500)
    return ctx, pg, log


def slider(pg):
    s = pg.locator("[role=slider]")
    return {"now": int(s.get_attribute("aria-valuenow")), "text": s.get_attribute("aria-valuetext"),
            "max": int(s.get_attribute("aria-valuemax"))}


def axe(pg, name):
    pg.evaluate(AXE)
    res = pg.evaluate("""async () => { const r = await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','best-practice']}});
      return r.violations.map(v => ({id: v.id, impact: v.impact, nodes: v.nodes.map(n => n.target.join(' ')).slice(0,5)})); }""")
    R.setdefault("axe", {})[name] = res


def query(pg):
    return pg.evaluate("location.search")


with sync_playwright() as p:
    b = p.chromium.launch(args=ARGS)

    # ---------- 1440, real catalogue ----------
    ctx, pg, log = new(b, 1440, 900, "/real/")
    R["1440_initial"] = {**slider(pg), "query": query(pg)}
    pg.screenshot(path=OUT / "01-1440-initial-latest.png")
    pg.locator(".shell-timeline").screenshot(path=OUT / "01b-1440-timeline-zoom.png")
    axe(pg, "1440")

    # Keyboard only: Tab from the start of the page until the slider has focus.
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    tabs = 0
    while tabs < 80:
        pg.keyboard.press("Tab"); tabs += 1
        if pg.evaluate("document.activeElement?.getAttribute('role')") == "slider":
            break
    R["tabs_to_slider"] = tabs
    pg.keyboard.press("Home")
    start = slider(pg)
    seen = [start["now"]]; texts = [start["text"]]; queries = [query(pg)]
    for _ in range(start["max"] + 3):
        pg.keyboard.press("ArrowRight")
        s = slider(pg); seen.append(s["now"]); texts.append(s["text"]); queries.append(query(pg))
    steps_ok = all(b2 - a == 1 for a, b2 in zip(seen, seen[1:start["max"] + 1]))
    R["keyboard_scrub"] = {"home": texts[0], "first_query": queries[0], "presses": len(seen) - 1,
                           "distinct": len(set(seen)), "every_step_plus_one": steps_ok,
                           "end": texts[-1], "end_query": queries[-1], "stays_at_end": seen[-1] == seen[-3],
                           "samples": {str(i): [seen[i], texts[i], queries[i]] for i in (1, 31, 92, 152, 182, 365, 390, 416, 417)
                                       if i < len(seen)}}
    # crossing checks from the texts: 2025-10-25/26 (DST end), 2026-02-28/03-01, 2025-12-31/2026-01-01, 2026-03-28/29 (DST start)
    R["keyboard_scrub"]["crossings"] = [t for t in texts if any(k in t for k in ("26 oct 2025", "25 oct 2025", "28 feb 2026", "1 mar 2026", "31 dic 2025", "1 ene 2026", "29 mar 2026", "28 mar 2026"))]
    pg.keyboard.press("Home")
    pg.keyboard.press("Shift+ArrowRight"); a = slider(pg)["text"]
    pg.keyboard.press("Shift+ArrowRight"); b1 = slider(pg)["text"]
    pg.keyboard.press("End"); e = slider(pg)["text"]
    pg.keyboard.press("Shift+ArrowLeft"); c = slider(pg)["text"]
    R["shift_keys"] = {"home_shift_right": a, "again": b1, "end": e, "end_shift_left": c}
    pg.screenshot(path=OUT / "02-1440-end-today-keyboard.png")

    # Play from 24 oct 2026 with Space on the slider.
    pg.goto(BASE + "/real/?d=2026-10-24", wait_until="domcontentloaded"); pg.wait_for_timeout(2500)
    pg.locator("[role=slider]").focus()
    t0 = time.time(); pg.keyboard.press("Space")
    frames = []; last = slider(pg)["text"]
    while time.time() - t0 < 8:
        s = slider(pg)["text"]
        if s != last:
            frames.append([round((time.time() - t0) * 1000), s]); last = s
            if len(frames) == 2:
                pg.screenshot(path=OUT / "03-1440-playing.png")
        pg.wait_for_timeout(20)
    play_btn = pg.locator("button[aria-label='Reproducir'], button[aria-label='Pausar']").first
    R["play_space"] = {"frames": frames, "button_after": play_btn.get_attribute("aria-label"),
                       "button_disabled": play_btn.is_disabled(), "query_after": query(pg)}
    # Play button then pause mid-way.
    pg.goto(BASE + "/real/?d=2026-10-24", wait_until="domcontentloaded"); pg.wait_for_timeout(2500)
    pg.get_by_role("button", name="Reproducir").click(); pg.wait_for_timeout(1900)
    pg.get_by_role("button", name="Pausar").click(); paused = slider(pg)["text"]; pg.wait_for_timeout(1700)
    R["play_pause_button"] = {"paused_on": paused, "after_1.7s": slider(pg)["text"]}

    # Última, previous, next.
    pg.goto(BASE + "/real/?d=2026-02-14", wait_until="domcontentloaded"); pg.wait_for_timeout(2500)
    before = slider(pg)["text"]
    nxt = pg.get_by_role("button", name="Fecha siguiente con datos"); prv = pg.get_by_role("button", name="Fecha anterior con datos")
    R["buttons_from_pending_day"] = {"start": before, "prev_disabled": prv.is_disabled(), "next_disabled": nxt.is_disabled()}
    nxt.click(); R["buttons_from_pending_day"]["after_next"] = slider(pg)["text"]
    pg.goto(BASE + "/real/?d=2026-10-29", wait_until="domcontentloaded"); pg.wait_for_timeout(2500)
    pg.get_by_role("button", name="Última").click()
    R["ultima"] = {"after": slider(pg)["text"], "disabled_now": pg.get_by_role("button", name="Última").is_disabled(), "query": query(pg)}

    # Calendar.
    cal = pg.get_by_role("button", name="Elegir en el calendario")
    cal.click(); pg.wait_for_timeout(300)
    focus = pg.evaluate("document.activeElement?.getAttribute('aria-label')")
    pg.screenshot(path=OUT / "04-1440-calendar-open.png")
    axe(pg, "1440_calendar_open")
    enabled_days = pg.locator("[role=dialog] button[aria-pressed]:not([disabled])").evaluate_all("els => els.map(e => e.getAttribute('aria-label'))")
    # Hover over the track while a different day has focus: does focus jump back?
    pg.keyboard.press("Shift+Tab"); pg.keyboard.press("Shift+Tab")
    f_before = pg.evaluate("document.activeElement?.getAttribute('aria-label')")
    box = pg.locator("[role=slider]").bounding_box()
    pg.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + 20); pg.wait_for_timeout(200)
    pg.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + 20); pg.wait_for_timeout(200)
    f_after = pg.evaluate("document.activeElement?.getAttribute('aria-label')")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    esc_focus = pg.evaluate("document.activeElement?.getAttribute('aria-label')")
    cal.click(); pg.wait_for_timeout(300)
    pg.get_by_role("button", name="Mes anterior").click()
    pick = pg.locator("[role=dialog] button[aria-label^='sábado, 24 de octubre de 2026'], [role=dialog] button[aria-label*='24 de octubre de 2026']").first
    pick_label = pick.get_attribute("aria-label"); pick.click(); pg.wait_for_timeout(200)
    R["calendar"] = {"focus_on_open": focus, "enabled_days_in_month": enabled_days, "focus_before_hover": f_before,
                     "focus_after_hover_track": f_after, "escape_focus": esc_focus, "picked": pick_label,
                     "slider_after_pick": slider(pg)["text"], "focus_after_pick": pg.evaluate("document.activeElement?.getAttribute('aria-label')"),
                     "query": query(pg)}

    # Tooltips.
    for name, frac in (("start", 0.01), ("feb", 0.35), ("end", 0.995)):
        pg.mouse.move(box["x"] + box["width"] * frac, box["y"] + 20); pg.wait_for_timeout(250)
        pg.screenshot(path=OUT / f"05-1440-tooltip-{name}.png", clip={"x": 380, "y": 700, "width": 1060, "height": 200})
    # Pointer drag across the track.
    pg.mouse.move(box["x"] + 1, box["y"] + 20); pg.mouse.down()
    drag = []
    for i in range(0, 101):
        pg.mouse.move(box["x"] + box["width"] * i / 100, box["y"] + 20); drag.append(slider(pg)["now"])
    pg.mouse.up()
    R["pointer_drag"] = {"distinct": len(set(drag)), "first": drag[0], "last": drag[-1], "query": query(pg)}
    R["log_1440_real"] = log
    ctx.close()

    # ---------- shared links and bad params ----------
    links = {}
    for q in ["?d=2026-10-29&l=swe", "?d=2026-02-30&l=swe", "?d=garbage&l=SWE", "?d=2024-01-01", "?d=2026-12-25",
              "?d=2026-11-10&l=depth&s=agua", "?l=nope", "?d=2026-1-5", "?d=2026-03-29"]:
        ctx, pg, log = new(b, 1440, 900, "/real/" + q)
        pg.wait_for_timeout(1500)
        links[q] = {"slider": slider(pg)["text"], "query_after_load": query(pg),
                    "legend": pg.evaluate("[...document.querySelectorAll('[class*=legend], [aria-label*=Leyenda]')].map(e=>e.innerText.slice(0,80)).join(' | ')"),
                    "console_errors": log["console_errors"]}
        if q == "?d=2026-10-29&l=swe":
            pg.screenshot(path=OUT / "06-1440-shared-link-swe.png")
        ctx.close()
    R["links"] = links

    # ---------- 375, real ----------
    ctx, pg, log = new(b, 375, 812, "/real/")
    R["375_initial"] = {**slider(pg), "query": query(pg)}
    pg.screenshot(path=OUT / "07-375-peek.png")
    axe(pg, "375")
    pg.locator("[role=slider]").focus(); pg.keyboard.press("Home")
    pg.screenshot(path=OUT / "07b-375-home.png")
    cal = pg.get_by_role("button", name="Elegir en el calendario"); cal.click(); pg.wait_for_timeout(300)
    pg.screenshot(path=OUT / "08-375-calendar.png")
    axe(pg, "375_calendar_open")
    R["375_calendar_rect"] = pg.locator("[role=dialog]").bounding_box()
    R["375_timeline_rect"] = pg.locator(".shell-timeline").bounding_box()
    pg.keyboard.press("Escape")
    R["log_375_real"] = log
    ctx.close()

    # ---------- empty (404) and error (403) ----------
    for variant in ("e404", "e403"):
        for w, h in ((1440, 900), (375, 812)):
            ctx, pg, log = new(b, w, h, f"/{variant}/?d=2026-10-29&l=swe")
            pg.wait_for_timeout(1500)
            pg.screenshot(path=OUT / f"09-{w}-{variant}.png")
            el = pg.locator(".shell-timeline")
            entry = {"text": el.inner_text() if el.count() else None, "query": query(pg), "log": log,
                     "buttons": pg.locator(".shell-timeline button").evaluate_all("els => els.map(e => e.innerText || e.getAttribute('aria-label'))") if el.count() else []}
            if variant == "e403" and w == 1440:
                # Reintentar refetches.
                n0 = len(log["failed_requests"])
                pg.get_by_role("button", name="Reintentar").click(); pg.wait_for_timeout(1500)
                entry["retry_new_failed_requests"] = log["failed_requests"][n0:]
            axe(pg, f"{variant}_{w}")
            R[f"{variant}_{w}"] = entry
            ctx.close()
    b.close()

(OUT / "results.json").write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(R, ensure_ascii=False, indent=1)[:12000])
