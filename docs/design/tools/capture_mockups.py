"""Render every mockup screen, check it, and save the screenshots compose_evidence.py reads.

Usage (from the repo root):
  python -I docs/design/tools/capture_mockups.py            # check + write screenshots/mockups/*.png
  python -I docs/design/tools/capture_mockups.py --check    # check only, write nothing

Serves the repo root on a free local port and renders each ?s=<screen> in headless Chromium
(Playwright) at 1440x900 and 375x812, locale es-ES, Europe/Madrid. The clock is pinned with
?now= so the webcam age reads the same on every run.

A screen fails when its DOM (text, title, aria-label, alt, placeholder) holds a copy fallback
'[some.key]' or an unfilled '{placeholder}', when the page reports an error, or when the console
logs one. Any failure exits 1.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "docs" / "design" / "screenshots" / "mockups"
PAGE = "docs/design/mockups/index.html"
SYMBOL = "docs/design/mockups/webcam-symbol.svg"
# The clock is pinned 41 min after the stored webcam still's capture time (fetch_webcam_still.py).
_STILL = json.loads((REPO / "docs/design/mockups/data/cetursa_pradollano.json").read_text(encoding="utf-8"))
NOW = f"{datetime.fromisoformat(_STILL['http_last_modified']) + timedelta(minutes=41):%Y-%m-%dT%H:%M:%SZ}"
VIEWPORTS = {1440: (1440, 900), 375: (375, 812)}

# t() in app.js returns '[path]' for a missing key; placeholders are '{name}'.
FALLBACK = re.compile(r"\[[a-z_][a-z0-9_]*(?:\.[a-z0-9_]+)+\]|\{[a-z_]+\}|\bundefined\b|\bNaN\b")

COLLECT = """() => {
  const out = [document.body.innerText];
  for (const el of document.querySelectorAll('[title],[aria-label],[alt],[placeholder],[aria-valuetext]'))
    for (const a of ['title', 'aria-label', 'alt', 'placeholder', 'aria-valuetext'])
      if (el.hasAttribute(a)) out.push(el.getAttribute(a));
  return out;
}"""


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass


def serve() -> tuple[http.server.ThreadingHTTPServer, int]:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(REPO)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def problems_in(texts: list[str]) -> list[str]:
    found = []
    for s in texts:
        for m in FALLBACK.finditer(s or ""):
            found.append(m.group(0))
    return sorted(set(found))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--check",
        action="store_true",
        help="render and check only, write no screenshots",
    )
    ap.add_argument(
        "--screens",
        nargs="*",
        help="subset of screen ids (default: all in app.js SCREENS)",
    )
    args = ap.parse_args(argv)

    srv, port = serve()
    base = f"http://127.0.0.1:{port}/"
    failures: list[str] = []
    if not args.check:
        OUT.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            screens = args.screens
            for w, (vw, vh) in VIEWPORTS.items():
                ctx = browser.new_context(
                    viewport={"width": vw, "height": vh},
                    locale="es-ES",
                    timezone_id="Europe/Madrid",
                )
                page = ctx.new_page()
                errors: list[str] = []
                page.on(
                    "console",
                    lambda m, e=errors: m.type == "error" and e.append(m.text),
                )
                page.on("pageerror", lambda ex, e=errors: e.append(str(ex)))
                if screens is None:
                    page.goto(f"{base}{PAGE}?now={NOW}")
                    page.wait_for_selector("body[data-ready]", timeout=60000)
                    screens = page.evaluate("Object.keys(SCREENS)")
                for s in screens:
                    errors.clear()
                    page.goto(f"{base}{PAGE}?s={s}&now={NOW}")
                    page.wait_for_selector("body[data-ready]", timeout=60000)
                    page.wait_for_timeout(300)
                    if page.get_attribute("body", "data-ready") == "error":
                        errors.append(page.inner_text("pre"))
                    bad = problems_in(page.evaluate(COLLECT))
                    tag = f"{s}@{w}"
                    if bad:
                        failures.append(f"{tag}: copy fallback {bad}")
                    for e in errors:
                        failures.append(f"{tag}: {e}")
                    if not args.check:
                        page.screenshot(path=str(OUT / f"{s}-{w}.png"))
                    print(f"{'FAIL' if bad or errors else 'ok  '} {tag}")
                ctx.close()
            if not args.check:
                ctx = browser.new_context(viewport={"width": 1200, "height": 560})
                page = ctx.new_page()
                page.goto(f"{base}{SYMBOL}")
                page.screenshot(path=str(OUT / "webcam-symbol.png"))
                ctx.close()
            browser.close()
    finally:
        srv.shutdown()

    for f in failures:
        print("MOCKUP ERROR:", f, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
