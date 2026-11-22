import subprocess

import pytest

from scripts.trusted_runs import trusted_run_ids

REPO = "owner/NivoSense"
PATH = ".github/workflows/snow-model.yml"


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, encoding="utf-8").stdout.strip()


@pytest.fixture
def shas(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")
    git("config", "commit.gpgsign", "false")
    git("commit", "--allow-empty", "-q", "-m", "on main")
    on_main = git("rev-parse", "HEAD")
    git("checkout", "-q", "-b", "side")
    git("commit", "--allow-empty", "-q", "-m", "not merged")
    off_main = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    return on_main, off_main


def run(run_id, sha, created_at, **overrides):
    base = {
        "id": run_id,
        "status": "completed",
        "conclusion": "success",
        "event": "schedule",
        "path": PATH,
        "head_branch": "main",
        "head_sha": sha,
        "head_repository": {"full_name": REPO},
        "repository": {"full_name": REPO},
        "created_at": created_at,
    }
    base.update(overrides)
    return base


def test_only_trusted_runs_newest_first(shas):
    on_main, off_main = shas
    runs = [
        run(1, on_main, "2026-11-20T07:40:00Z"),
        run(2, on_main, "2026-11-21T07:40:00Z", event="workflow_dispatch"),
        run(3, on_main, "2026-11-22T01:00:00Z", event="pull_request", head_repository={"full_name": "fork/NivoSense"}),
        run(4, on_main, "2026-11-22T02:00:00Z", event="pull_request"),
        run(5, on_main, "2026-11-22T03:00:00Z", head_repository={"full_name": "fork/NivoSense"}),
        run(6, off_main, "2026-11-22T04:00:00Z", event="workflow_dispatch"),
        run(7, on_main, "2026-11-22T05:00:00Z", path=".github/workflows/ci.yml"),
        run(8, on_main, "2026-11-22T06:00:00Z", conclusion="failure"),
        run(9, on_main, "2026-11-22T07:00:00Z", head_branch="feature"),
        run(10, on_main, "2026-11-22T08:00:00Z", event="push"),
        run(11, on_main, "2026-11-22T09:00:00Z", head_repository=None),
    ]
    assert trusted_run_ids(runs, REPO, PATH, "main") == [2, 1]


def test_fork_pull_request_from_a_branch_named_main_is_ignored(shas):
    on_main, _ = shas
    fork_repo = {"full_name": "fork/NivoSense"}
    fork = run(3, on_main, "2026-11-22T01:00:00Z", event="pull_request", head_repository=fork_repo)
    assert trusted_run_ids([fork], REPO, PATH, "main") == []


def test_run_on_a_tag_named_main_off_main_is_ignored(shas):
    _, off_main = shas
    assert trusted_run_ids([run(6, off_main, "2026-11-22T04:00:00Z")], REPO, PATH, "main") == []
