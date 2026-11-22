"""Apply one mutation at a time to the PR worktree, run vitest, restore. Prints caught/missed."""
import subprocess, sys, pathlib, os

ROOT = pathlib.Path(sys.argv[1])  # frontend dir
MUTATIONS = [
    ("timeline: length off by one (drops today)", "src/lib/timeline.ts",
     "Math.round((toTime(end) - toTime(start)) / DAY_MS) + 1", "Math.round((toTime(end) - toTime(start)) / DAY_MS)"),
    ("timeline: addDays in local time (DST)", "src/lib/timeline.ts",
     "return new Date(toTime(iso) + days * DAY_MS).toISOString().slice(0, 10);",
     "const d = new Date(`${iso}T00:00:00`); d.setTime(d.getTime() + days * DAY_MS); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;"),
    ("timeline: addDays naive string increment (month end)", "src/lib/timeline.ts",
     "return new Date(toTime(iso) + days * DAY_MS).toISOString().slice(0, 10);",
     "const [y,m,dd] = iso.split('-').map(Number); return new Date(Date.UTC(y, m-1, Math.min(dd + days, 31 + days))).toISOString().slice(0, 10);"),
    ("timeline: status map gapfilled<->modelled", "src/lib/timeline.ts",
     'gapfilled: "rellenado",\n  modelled: "modelado",', 'gapfilled: "modelado",\n  modelled: "rellenado",'),
    ("timeline: rank order modelled before gapfilled", "src/lib/timeline.ts",
     '["observado", "rellenado", "modelado", "prevision"]', '["observado", "modelado", "rellenado", "prevision"]'),
    ("timeline: latest ignores today cutoff", "src/lib/timeline.ts",
     "dataIndices.filter((i) => i <= todayIndex)", "dataIndices.filter((i) => i >= 0)"),
    ("timeline: forecast slot not split at today", "src/lib/timeline.ts",
     "const forecastSlot = i > model.todayIndex;", "const forecastSlot = false;"),
    ("timeline: shift jumps to any data day", "src/lib/timeline.ts",
     "previousIn(model.observedIndices, current)", "previousIn(model.dataIndices, current)"),
    ("timeline: today in UTC", "src/lib/timeline.ts",
     'timeZone: "Europe/Madrid"', 'timeZone: "UTC"'),
    ("timeline: durationMs ignores s unit", "src/lib/timeline.ts",
     '(match[2] === "s" ? 1000 : 1)', "1"),
    ("url: accept 2026-02-30", "src/lib/urlState.ts",
     "new Date(time).toISOString().slice(0, 10) === value", "true"),
    ("url: accept any layer", "src/lib/urlState.ts",
     "layer && LAYER_ID.test(layer)", "layer"),
    ("url: drop other params", "src/lib/urlState.ts",
     "const params = new URLSearchParams(search);\n  for", "const params = new URLSearchParams();\n  for"),
    ("url: accept d=2026-1-5 (no ISO check)", "src/lib/urlState.ts",
     "if (!ISO_DATE.test(value)) return false;", ""),
    ("catalog: 404 treated as error", "src/lib/catalog.ts",
     "if (response.status === 404) return { kind: \"missing\" };", ""),
    ("catalog: unknown status accepted", "src/lib/catalog.ts",
     "|| !STATUSES.has(entry.status)", ""),
    ("play: steps every day instead of data days", "src/components/Timeline.tsx",
     "const next = nextIn(model.dataIndices, index);\n    if (next === null) {", "const next = index + 1 < model.days.length ? index + 1 : null;\n    if (next === null) {"),
    ("play: never stops at the end", "src/components/Timeline.tsx",
     "    if (next === null) {\n      setPlaying(false);\n      return;\n    }", "    if (next === null) return;"),
    ("play: frame 0 ms", "src/components/Timeline.tsx",
     'durationMs(token("motion-duration-play-frame"))', "0"),
    ("app: shared date ignored, always latest", "src/App.tsx",
     "const wanted = current ?? initialUrl.date;", "const wanted = current;"),
]

def run():
    env = dict(os.environ, TZ="Europe/Madrid")
    r = subprocess.run("npx vitest run src/lib src/components", cwd=ROOT, shell=True, capture_output=True, text=True, env=env)
    return r.returncode

for name, rel, old, new in MUTATIONS:
    p = ROOT / rel
    src = p.read_text(encoding="utf-8")
    if old not in src:
        print(f"NOT APPLIED  {name}"); continue
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    try:
        code = run()
    finally:
        p.write_text(src, encoding="utf-8")
    print(f"{'CAUGHT ' if code else 'MISSED '}  {name}", flush=True)
