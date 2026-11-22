"""Apply one mutation at a time to the PR worktree, run vitest, restore. Prints caught/missed."""
import subprocess, sys, pathlib, os

ROOT = pathlib.Path(sys.argv[1])  # frontend dir
MUTATIONS = [
    ("timeline: addDays with 30-day months (month end)", "src/lib/timeline.ts",
     "return new Date(toTime(iso) + days * DAY_MS).toISOString().slice(0, 10);",
     "let [y, m, d] = iso.split('-').map(Number); d += days; while (d > 30) { d -= 30; m += 1; if (m > 12) { m = 1; y += 1; } } return `${y}-${String(m).padStart(2,'0')}-${String(d).padStart(2,'0')}`;"),
    ("timeline: addDays never rolls the year", "src/lib/timeline.ts",
     "return new Date(toTime(iso) + days * DAY_MS).toISOString().slice(0, 10);",
     "const s = new Date(toTime(iso) + days * DAY_MS).toISOString().slice(0, 10); return iso.slice(0, 4) + s.slice(4);"),
    ("timeline: span by calendar months instead of days (length)", "src/lib/timeline.ts",
     "Math.round((toTime(end) - toTime(start)) / DAY_MS) + 1", "Math.floor((toTime(end) - toTime(start)) / DAY_MS / 30) * 30 + 1"),
    ("timeline: monthStarts on day 2", "src/lib/timeline.ts",
     'day.date.endsWith("-01")', 'day.date.endsWith("-02")'),
    ("app: shared date ignored, always latest", "src/App.tsx",
     "const wanted = current ?? initialUrl.date;", "const wanted = current;"),
]

def run():
    env = dict(os.environ, TZ="Europe/Madrid")
    r = subprocess.run("npx vitest run", cwd=ROOT, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return r.returncode

for name, rel, old, new in MUTATIONS:
    p = ROOT / rel
    src = p.read_bytes().decode("utf-8")
    if old not in src:
        print(f"NOT APPLIED  {name}"); continue
    p.write_bytes(src.replace(old, new, 1).encode("utf-8"))
    try:
        code = run()
    finally:
        p.write_bytes(src.encode("utf-8"))
    print(f"{'CAUGHT ' if code else 'MISSED '}  {name}", flush=True)
