"""Pick the release tag the live site deploys.

A release is a tag named vMAJOR.MINOR.PATCH whose commit is on main. Any other
tag (vtest, v1.0.0-rc1, a tag on an unmerged branch, a tag on a tree or blob) is
ignored, so a stray tag can never reach the live site and cannot stop the
hourly data refresh either.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# [0-9], not \d: \d also matches non-ASCII digits such as U+0661.
RELEASE_TAG = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class ReleaseError(RuntimeError):
    pass


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, encoding="utf-8", check=False)


def is_on_main(tag: str, main_ref: str) -> bool:
    commit = git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
    if commit.returncode != 0:
        print(f"::warning::tag {tag} does not point to a commit; ignored", file=sys.stderr)
        return False
    return git("merge-base", "--is-ancestor", commit.stdout.strip(), main_ref).returncode == 0


def pick_release(main_ref: str) -> str:
    if git("rev-parse", "--verify", "--quiet", f"{main_ref}^{{commit}}").returncode != 0:
        raise ReleaseError(f"{main_ref} is not a commit; fetch main with full history first")
    listed = git("tag", "--list", "v*")
    if listed.returncode != 0:
        raise ReleaseError(f"git tag failed: {listed.stderr.strip()}")
    versions = []
    for tag in listed.stdout.split():
        match = RELEASE_TAG.match(tag)
        if match and is_on_main(tag, main_ref):
            versions.append((tuple(int(part) for part in match.groups()), tag))
    if not versions:
        raise ReleaseError(f"no tag vMAJOR.MINOR.PATCH on {main_ref}; the live site deploys only from a release")
    return max(versions)[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-ref", default="refs/remotes/origin/main")
    args = parser.parse_args()
    try:
        print(pick_release(args.main_ref))
    except ReleaseError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
