import subprocess

import pytest

from scripts.pick_release import ReleaseError, pick_release


def run(*args):
    subprocess.run(["git", *args], check=True, capture_output=True, text=True)


def commit(message):
    run("commit", "--allow-empty", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "test@example.invalid")
    run("config", "user.name", "test")
    run("config", "commit.gpgsign", "false")
    run("config", "tag.gpgsign", "false")
    commit("first")
    return tmp_path


def test_newest_semver_tag_on_main_wins_by_number(repo):
    run("tag", "v0.9.0")
    commit("second")
    run("tag", "v0.10.0")
    assert pick_release("main") == "v0.10.0"


def test_stray_names_are_ignored(repo):
    run("tag", "v0.1.0")
    commit("second")
    for name in ("vtest", "v1.0.0-rc1", "v2", "v2.0", "v01.0.0", "version-3.0.0"):
        run("tag", name)
    assert pick_release("main") == "v0.1.0"


def test_tag_on_unmerged_branch_is_ignored(repo):
    run("tag", "v0.1.0")
    run("checkout", "-q", "-b", "side")
    commit("not merged")
    run("tag", "v9.0.0")
    run("checkout", "-q", "main")
    assert pick_release("main") == "v0.1.0"


def test_annotated_tag_is_accepted(repo):
    run("tag", "-a", "v1.2.3", "-m", "release")
    assert pick_release("main") == "v1.2.3"


def test_no_release_fails(repo):
    run("tag", "vtest")
    run("checkout", "-q", "-b", "side")
    commit("not merged")
    run("tag", "v1.0.0")
    run("checkout", "-q", "main")
    with pytest.raises(ReleaseError, match="no tag"):
        pick_release("main")


def test_pushed_tag_must_be_the_newest_release(repo):
    run("tag", "v0.1.0")
    commit("second")
    run("tag", "v0.2.0")
    assert pick_release("main", pushed_tag="v0.2.0") == "v0.2.0"
    with pytest.raises(ReleaseError, match="not the newest"):
        pick_release("main", pushed_tag="v0.1.0")
    with pytest.raises(ReleaseError, match="not the newest"):
        pick_release("main", pushed_tag="vtest")
