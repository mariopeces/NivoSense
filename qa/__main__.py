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
import sys
import time
from pathlib import Path
from typing import Any

from pipelines.catalog import Storage
from pipelines.catalog.storage import NO_CACHE
from pipelines.region import load_region

from .check_catalog import check_catalog
from .freshness import freshness
from .objects import catalogue, index_entries
from .regression import load_fixtures, run_fixtures
from .render_thumbs import fixture_thumbs, render_thumbs


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
    lines.append(
        f"| check_catalog | {'pass' if check['ok'] else 'fail'} | {check['entries_checked']} entries, "
        f"{len(check['errors'])} errors, {check['duration_s']} s |"
    )
    for fixture in report["regression_fixtures"]["fixtures"]:
        detail = "; ".join(fixture.get("pending") or fixture.get("failures") or []) or "-"
        lines.append(f"| fixture {fixture['id']} | {fixture['status']} | {detail} |")
    if "freshness" in report:
        for slo in ("f1", "f2"):
            result = report["freshness"][slo]
            lines.append(
                f"| {slo.upper()} | {'pass' if result['ok'] else 'fail'} | {len(result['breaches'])} breaches |"
            )
    if "thumbs" in report:
        lines.append(f"| render_thumbs | done | {len(report['thumbs'])} PNGs |")
    lines += [
        "",
        "<details><summary>Report JSON</summary>",
        "",
        "```json",
        json.dumps(report, indent=1),
        "```",
        "</details>",
        "",
    ]
    return "\n".join(lines)


def upload(storage: Storage, report: dict[str, Any], out_dir: Path) -> list[str]:
    """Write the report and thumbnails under qa/ of the catalogue; return the keys written."""
    stamp = report["generated_at"].replace(":", "").replace("-", "")
    run = os.environ.get("GITHUB_RUN_ID", "local")
    keys = []
    for thumb in report.get("thumbs", []):
        path = Path(thumb["png"])
        key = "qa/thumbs/" + path.relative_to(out_dir / "thumbs").as_posix()
        storage.write(key, path, "image/png", NO_CACHE)
        thumb["key"] = key
        keys.append(key)
    key = f"qa/reports/{report['generated_at'][:10]}/{stamp}-{run}.json"
    report["report_key"] = key
    storage.write(key, json.dumps(report, indent=1).encode(), "application/json", NO_CACHE)
    keys.append(key)
    return keys


def run(args: argparse.Namespace) -> dict[str, Any]:
    storage = catalogue(args.target, args.root)
    started = time.monotonic()
    report: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "catalogue": repr(storage),
        "code_version": os.environ.get("GITHUB_SHA"),
        "check_catalog": check_catalog(storage, args.start, args.end),
    }
    entries = index_entries(storage)
    fixtures = load_fixtures()
    report["regression_fixtures"] = run_fixtures(storage, entries, fixtures)
    if args.thumbs:
        thumbs_dir = args.out_dir / "thumbs"
        report["thumbs"] = render_thumbs(storage, _in_range(entries, args.start, args.end), thumbs_dir)
        report["thumbs"] += fixture_thumbs(storage, fixtures, entries, thumbs_dir)
    if args.freshness:
        report["freshness"] = freshness(storage, load_region(args.region).bbox)
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
    parser.add_argument("--start", help="first date checked, YYYY-MM-DD")
    parser.add_argument("--end", help="last date checked, YYYY-MM-DD")
    parser.add_argument("--out-dir", type=Path, default=Path("qa-out"))
    parser.add_argument("--region", type=Path, default=Path("regions/sierra-nevada.json"))
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
        part = check_catalog(storage, args.start, args.end)
    elif args.command == "render-thumbs":
        part = render_thumbs(storage, _in_range(index_entries(storage), args.start, args.end), args.out_dir / "thumbs")
    elif args.command == "freshness":
        part = freshness(storage, load_region(args.region).bbox)
    else:
        part = run_fixtures(storage, index_entries(storage))
    print(json.dumps(part, indent=1))
    return 0 if not isinstance(part, dict) or part.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
