"""Pick the release tag the live site deploys.

A release is a tag named vMAJOR.MINOR.PATCH whose commit is on main. Any other
tag (vtest, v1.0.0-rc1, a tag on an unmerged branch) is ignored, so a stray tag
can never reach the live site.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

RELEASE_TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class ReleaseError(RuntimeError):
    pass


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def is_on_main(tag: str, main_ref: str) -> bool:
    result = git("merge-base", "--is-ancestor", f"refs/tags/{tag}^{{commit}}", main_ref)
    if result.returncode not in (0, 1):
        raise ReleaseError(f"git merge-base failed for {tag}: {result.stderr.strip()}")
    return result.returncode == 0


def newest_release(main_ref: str) -> str:
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


def pick_release(main_ref: str, pushed_tag: str | None = None) -> str:
    newest = newest_release(main_ref)
    if pushed_tag is not None and pushed_tag != newest:
        raise ReleaseError(
            f"pushed tag {pushed_tag} is not the newest release on {main_ref} ({newest}); not deploying it"
        )
    return newest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-ref", default="refs/remotes/origin/main")
    parser.add_argument("--pushed-tag", help="tag that triggered the run; it must be the newest release")
    args = parser.parse_args()
    try:
        print(pick_release(args.main_ref, args.pushed_tag))
    except ReleaseError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
