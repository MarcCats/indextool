"""Fail when golden output changed without a minor version bump.

Usage: python scripts/check_golden_bump.py <base-ref>

Golden files carry `indextool <major.minor>` in their header. A change to a golden that leaves that version
unchanged means a patch release could change users' output, which the versioning policy forbids.

The comparison is between the merge base of <base-ref> and HEAD, and HEAD itself, both read from git objects (the
working tree is never read), so a base that has moved on since the branch point cannot hide or invent a change. Every
git command runs from the repository root, so the current directory does not matter. A golden that exists only at
HEAD (new) or only at the merge base (deleted) needs no bump; a rename is therefore a delete plus an add and needs
none either.

Exit codes: 0 fine, 1 a golden changed without a minor bump, 2 usage or git problem (not a repository, unknown base
ref, no merge base as in a shallow clone)."""
from __future__ import annotations

import re
import subprocess
import sys

GOLDEN_DIR = "tests/golden"
_VERSION = re.compile(r"indextool (\d+\.\d+)")


def header_version(text: str) -> str | None:
    match = _VERSION.search(text)
    return match.group(1) if match else None


def bump_required(old: str, new: str) -> bool:
    if old == new:
        return False
    return header_version(old) == header_version(new)


class _GitFailure(Exception):
    """A git problem that is reported as one line on stderr and exit code 2."""


def _git(cwd: str | None, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    except OSError as exc:
        raise _GitFailure(f"cannot run git: {exc}") from exc


def _git_ok(root: str, *args: str) -> str:
    proc = _git(root, *args)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().split("\n")[-1]
        raise _GitFailure(f"git {args[0]} failed: {detail}")
    return proc.stdout.decode("utf-8", "replace")


def _merge_base(root: str, base: str) -> str:
    if _git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode != 0:
        raise _GitFailure(f"cannot resolve the base ref {base!r}")
    proc = _git(root, "merge-base", base, "HEAD")
    merge_base = proc.stdout.decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not merge_base:
        raise _GitFailure(
            f"no merge base between {base!r} and HEAD; in a shallow clone fetch the full history (fetch-depth: 0)"
        )
    return merge_base


def _changed_goldens(root: str, merge_base: str) -> list[tuple[str, str]]:
    """(status, name) for each golden that differs between the merge base and HEAD; renames are not detected."""
    raw = _git_ok(root, "diff", "--name-status", "--no-renames", "-z", merge_base, "HEAD", "--", GOLDEN_DIR)
    fields = [f for f in raw.split("\0") if f]
    return list(zip(fields[0::2], fields[1::2]))


def _check(root: str, base: str) -> list[str]:
    merge_base = _merge_base(root, base)
    failures: list[str] = []
    for status, name in _changed_goldens(root, merge_base):
        if status in ("A", "D"):
            continue  # a new golden or a deleted golden needs no bump
        old = _git_ok(root, "show", f"{merge_base}:{name}")
        new = _git_ok(root, "show", f"HEAD:{name}")
        if bump_required(old.replace("\r\n", "\n"), new.replace("\r\n", "\n")):
            failures.append(name)
    return failures


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_golden_bump.py <base-ref>", file=sys.stderr)
        return 2
    try:
        top = _git(None, "rev-parse", "--show-toplevel")
        if top.returncode != 0:
            raise _GitFailure("not inside a git repository")
        failures = _check(top.stdout.decode("utf-8", "replace").rstrip("\n"), argv[1])
    except _GitFailure as exc:
        print(f"check_golden_bump.py: {exc}", file=sys.stderr)
        return 2
    if failures:
        print("golden output changed without a minor version bump (edit __version__ and regenerate the goldens):")
        for name in failures:
            print(f"  {name}")
        return 1
    print("golden output is unchanged, or the minor version was bumped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
