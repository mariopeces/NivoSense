"""Command line of the QA harness.

    python -m qa run --target staging [--root PREFIX] [--start DATE --end DATE] [--no-freshness] [--upload]

`run` checks the catalogue, scores the regression fixtures, renders the thumbnails and, unless told not to,
checks freshness. The report goes to <out-dir>/report.json, to the step summary of a GitHub Actions run
(GITHUB_STEP_SUMMARY) and, with --upload, to qa/ in the catalogue's bucket. The exit status is 1 when any check
fails. `check-catalog`, `render-thumbs`, `freshness` and `fixtures` run one part and print its JSON.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from pipelines.catalog import Storage
from pipelines.catalog.storage import NO_CACHE, PreconditionFailed
from pipelines.region import load_region

from .check_catalog import check_catalog
from .freshness import freshness
from .objects import catalogue, index_entries
from .regression import load_fixtures, run_fixtures
from .render_thumbs import fixture_thumbs, render_thumbs

UPLOAD_ATTEMPTS = 20
SUMMARY_JSON_LIMIT = 500_000


def _in_range(entries: dict[str, list[dict[str, Any]]], start: str | None, end: str | None) -> list[dict[str, Any]]:
    return [
        entry
        for layer_entries in entries.values()
        for entry in layer_entries
        if (start is None or entry["date"] >= start) and (end is None or entry["date"] <= end)
    ]


def summary_markdown(report: dict[str, Any]) -> str:
    """A short table for the Actions step summary, followed by the full report JSON."""
    lines = [f"## QA report: {'pass' if report['ok'] else 'FAIL'}", "", f"Catalogue: `{report['catalogue']}`", ""]
    lines += ["| Check | Result | Detail |", "|---|---|---|"]
    check = report["check_catalog"]
    absent = " (catalogue absent)" if check.get("index") == "absent" else ""
    lines.append(
        f"| check_catalog | {'pass' if check['ok'] else 'fail'} | {check['entries_checked']} entries{absent}, "
        f"{len(check['errors'])} errors, {check['duration_s']} s |"
    )
    for fixture in report["regression_fixtures"]["fixtures"]:
        detail = "; ".join(fixture.get("pending") or fixture.get("failures") or []) or "-"
        lines.append(f"| fixture {fixture['id']} | {fixture['status']} | {detail} |")
    if "freshness" in report:
        for slo in ("f1", "f2"):
            result = report["freshness"][slo]
            detail = result.get("error") or f"{len(result['breaches'])} breaches"
            lines.append(f"| {slo.upper()} | {'pass' if result['ok'] else 'fail'} | {detail} |")
    if "thumbs" in report:
        failed = sum(1 for thumb in report["thumbs"] if "error" in thumb)
        lines.append(f"| render_thumbs | done | {len(report['thumbs']) - failed} PNGs, {failed} failed |")
    full = json.dumps(report, indent=1)
    if len(full) > SUMMARY_JSON_LIMIT:
        # The step summary is capped at 1 MiB; the full report is in the artifact and in the bucket.
        full = f"(report JSON is {len(full)} bytes; see the run artifact or {report.get('report_key', 'qa-out/')})"
    lines += ["", "<details><summary>Report JSON</summary>", "", "```json", full, "```", "</details>", ""]
    return "\n".join(lines)


def report_id(generated_at: str) -> str:
    """Time, run, attempt and job of this run: every matrix job and workflow call of one run gets its own."""
    stamp = generated_at.replace(":", "").replace("-", "")
    run = os.environ.get("GITHUB_RUN_ID", "local")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    job = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.environ.get("QA_JOB", "") or "local")
    return f"{stamp}-{run}-{attempt}-{job}"


def upload(storage: Storage, report: dict[str, Any], out_dir: Path) -> list[str]:
    """Write the report and its thumbnails under qa/ of the catalogue; return the keys written.

    Every object is created with if_generation_match=0, so a run never overwrites another run's report or
    thumbnails; if the id is taken anyway (two calls with the same job name), the next free suffix is used.
    """
    day, base = report["generated_at"][:10], report_id(report["generated_at"])
    for attempt in range(UPLOAD_ATTEMPTS):
        name = base if attempt == 0 else f"{base}-{attempt + 1}"
        keys = []
        try:
            for thumb in report.get("thumbs", []):
                if "png" not in thumb:
                    continue
                path = Path(thumb["png"])
                key = f"qa/thumbs/{day}/{name}/" + path.relative_to(out_dir / "thumbs").as_posix()
                storage.write(key, path, "image/png", NO_CACHE, if_generation_match=0)
                thumb["key"] = key
                keys.append(key)
            key = f"qa/reports/{day}/{name}.json"
            report["report_key"] = key
            storage.write(key, json.dumps(report, indent=1).encode(), "application/json", NO_CACHE, 0)
        except PreconditionFailed:
            continue
        keys.append(key)
        return keys
    raise RuntimeError(f"No free report key for {base} after {UPLOAD_ATTEMPTS} attempts")


def run(args: argparse.Namespace) -> dict[str, Any]:
    storage = catalogue(args.target, args.root)
    started = time.monotonic()
    report: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "catalogue": repr(storage),
        "code_version": os.environ.get("GITHUB_SHA"),
        "check_catalog": check_catalog(storage, args.start, args.end, now=args.now, allow_absent=args.allow_absent),
    }
    entries = index_entries(storage)
    fixtures = load_fixtures()
    report["regression_fixtures"] = run_fixtures(storage, entries, fixtures)
    if args.thumbs:
        thumbs_dir = args.out_dir / "thumbs"
        window = report["check_catalog"]["range"]["start"]
        report["thumbs"] = render_thumbs(storage, _in_range(entries, window, args.end), thumbs_dir)
        report["thumbs"] += fixture_thumbs(storage, fixtures, entries, thumbs_dir)
    if args.freshness:
        report["freshness"] = freshness(storage, load_region(args.region).bbox, args.now)
    report["ok"] = all(
        report[part]["ok"] for part in ("check_catalog", "regression_fixtures", "freshness") if part in report
    )
    report["duration_s"] = round(time.monotonic() - started, 1)
    if args.upload:
        upload(storage, report, args.out_dir)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m qa")
    parser.add_argument("command", choices=["run", "check-catalog", "render-thumbs", "freshness", "fixtures"])
    parser.add_argument("--target", choices=["staging", "prod"], default="staging")
    parser.add_argument("--root", default="", help="a catalogue under this prefix of the target (trial runs)")
    parser.add_argument("--start", help="first date checked, YYYY-MM-DD; default: files of the last 35 days")
    parser.add_argument("--end", help="last date checked, YYYY-MM-DD")
    parser.add_argument("--out-dir", type=Path, default=Path("qa-out"))
    parser.add_argument("--region", type=Path, default=Path("regions/sierra-nevada.json"))
    parser.add_argument(
        "--now",
        type=dt.datetime.fromisoformat,
        help="judge as of this time (ISO 8601 with offset), to rerun a past day",
    )
    parser.add_argument(
        "--allow-absent",
        action="store_true",
        help="pass an empty catalogue (no index, no entry); without it, an absent catalogue fails",
    )
    parser.add_argument("--no-thumbs", dest="thumbs", action="store_false")
    parser.add_argument("--no-freshness", dest="freshness", action="store_false")
    parser.add_argument("--upload", action="store_true", help="write the report and thumbnails to qa/ in the bucket")
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.command == "run":
        report = run(args)
        (args.out_dir / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write(summary_markdown(report))
        print(
            json.dumps(
                {k: report[k] for k in ("catalogue", "ok", "duration_s")}
                | {"report": str(args.out_dir / "report.json")}
            )
        )
        return 0 if report["ok"] else 1

    storage = catalogue(args.target, args.root)
    part: Any
    if args.command == "check-catalog":
        part = check_catalog(storage, args.start, args.end, now=args.now, allow_absent=args.allow_absent)
    elif args.command == "render-thumbs":
        part = render_thumbs(storage, _in_range(index_entries(storage), args.start, args.end), args.out_dir / "thumbs")
    elif args.command == "freshness":
        part = freshness(storage, load_region(args.region).bbox, args.now)
    else:
        part = run_fixtures(storage, index_entries(storage))
    print(json.dumps(part, indent=1))
    return 0 if not isinstance(part, dict) or part.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
