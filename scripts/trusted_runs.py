"""List the producer runs whose artifacts the live site may publish.

Reads a GitHub API response of /actions/workflows/<file>/runs on stdin and
prints the run ids, newest first, of successful scheduled or dispatched runs of
that workflow, in this repository, on a commit of main. A fork pull request
from a branch named main, a run on a tag named main, or a run of another
workflow is never trusted: its artifacts could carry unreviewed HTML or JSON
straight into Pages.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

TRUSTED_EVENTS = {"schedule", "workflow_dispatch"}


def is_on_main(sha: str, main_ref: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, main_ref], capture_output=True, encoding="utf-8", check=False
    )
    return result.returncode == 0


def trusted_run_ids(runs: list[dict[str, Any]], repo: str, workflow_path: str, main_ref: str) -> list[int]:
    trusted = []
    for run in runs:
        head_repository = run.get("head_repository") or {}
        if (
            run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and run.get("event") in TRUSTED_EVENTS
            and run.get("path") == workflow_path
            and run.get("head_branch") == "main"
            and head_repository.get("full_name") == repo
            and (run.get("repository") or {}).get("full_name") == repo
            and is_on_main(str(run.get("head_sha", "")), main_ref)
        ):
            trusted.append((run["created_at"], int(run["id"])))
    return [run_id for _, run_id in sorted(trusted, reverse=True)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/name of this repository")
    parser.add_argument("--workflow-path", required=True, help="for example .github/workflows/snow-model.yml")
    parser.add_argument("--main-ref", default="refs/remotes/origin/main")
    args = parser.parse_args()
    runs = json.load(sys.stdin).get("workflow_runs", [])
    for run_id in trusted_run_ids(runs, args.repo, args.workflow_path, args.main_ref):
        print(run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
