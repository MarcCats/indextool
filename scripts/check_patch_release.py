"""Before publishing vX.Y.Z with Z > 0, assert the golden output equals that of vX.Y.0.

Usage: python scripts/check_patch_release.py <tag>

Patch releases are output-neutral by policy, so users who pin `indextool~=X.Y.0` never have to regenerate.

The commit being judged is the one <tag> points to when the tag exists (the release job runs on exactly that tag),
otherwise HEAD, which lets a dry run before tagging work. The declared `__version__` and every golden are read from
git objects at that commit and at vX.Y.0 (the working tree is never read), so uncommitted edits or a different
checkout cannot change the answer. Every git command runs from the repository root, so the current directory does not
matter. Line endings are normalized on both sides. A golden that exists only at the judged commit (new) is ignored; a
golden that exists only at vX.Y.0 (deleted) counts as changed. A vX.Y.0 with no golden at all fails closed: there is
nothing to compare.

Exit codes: 0 fine, 1 a patch release changes golden output, 2 usage or git problem (bad tag, tag not matching
`__version__`, not a repository, missing vX.Y.0 tag as in a shallow clone, no golden files at vX.Y.0)."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

GOLDEN_DIR = "tests/golden"
VERSION_FILE = "src/indextool/__init__.py"
_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)\Z")
_DECLARED = re.compile(r'^__version__ = "([^"]+)"', re.MULTILINE)


class _GitFailure(Exception):
    """A git problem that is reported as one line on stderr and exit code 2."""


def parse_tag(tag: str) -> tuple[int, int, int]:
    match = _TAG.match(tag)
    if not match:
        raise ValueError(f"not a release tag: {tag!r}")
    major, minor, patch = (int(g) for g in match.groups())
    return major, minor, patch


def _git(cwd: str | Path | None, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    except OSError as exc:
        raise _GitFailure(f"cannot run git: {exc}") from exc


def _git_ok(root: str | Path, *args: str) -> bytes:
    proc = _git(root, *args)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().split("\n")[-1]
        raise _GitFailure(f"git {args[0]} failed: {detail}")
    return proc.stdout


def _resolve(root: str | Path, rev: str) -> str | None:
    """The commit a revision names, or None when it does not resolve."""
    proc = _git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    commit = proc.stdout.decode("utf-8", "replace").strip()
    return commit if proc.returncode == 0 and commit else None


def declared_version(root: str | Path, rev: str) -> str:
    """The `__version__` declared in src/indextool/__init__.py at <rev>, read from git."""
    text = _git_ok(root, "show", f"{rev}:{VERSION_FILE}").decode("utf-8", "replace")
    match = _DECLARED.search(text)
    if not match:
        raise ValueError(f"no __version__ in {VERSION_FILE}")
    return match.group(1)


def _goldens(root: str | Path, rev: str) -> list[str]:
    raw = _git_ok(root, "ls-tree", "-r", "--name-only", "-z", rev, "--", GOLDEN_DIR).decode("utf-8", "replace")
    return [name for name in raw.split("\0") if name]


def _changed_goldens(root: str | Path, base_tag: str, base: str, current: str) -> list[str]:
    """Goldens whose bytes at <current> differ from those at <base>, or that no longer exist at <current>."""
    at_base = _goldens(root, base)
    if not at_base:
        raise _GitFailure(f"no golden files at {base_tag}: nothing to compare")
    at_current = set(_goldens(root, current))
    changed = []
    for name in at_base:
        if name not in at_current:
            changed.append(name)
            continue
        old = _git_ok(root, "show", f"{base}:{name}").replace(b"\r\n", b"\n")
        new = _git_ok(root, "show", f"{current}:{name}").replace(b"\r\n", b"\n")
        if old != new:
            changed.append(name)
    return changed


def _check(tag: str) -> tuple[str, list[str]]:
    """(base tag, changed goldens); raises _GitFailure or ValueError for a problem that is exit code 2."""
    major, minor, patch = parse_tag(tag)
    top = _git(None, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        raise _GitFailure("not inside a git repository")
    root = top.stdout.decode("utf-8", "replace").rstrip("\n")
    current = _resolve(root, tag) or _resolve(root, "HEAD")
    if current is None:
        raise _GitFailure("the repository has no commits")
    declared = declared_version(root, current)
    if declared != f"{major}.{minor}.{patch}":
        raise ValueError(f"tag {tag} does not match __version__ {declared}")
    base_tag = f"v{major}.{minor}.0"
    if patch == 0:
        return base_tag, []
    base = _resolve(root, base_tag)
    if base is None:
        raise _GitFailure(f"cannot resolve the base tag {base_tag!r}; the release job needs fetch-depth: 0")
    return base_tag, _changed_goldens(root, base_tag, base, current)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_patch_release.py <tag>", file=sys.stderr)
        return 2
    tag = argv[1]
    try:
        base_tag, changed = _check(tag)
    except (_GitFailure, ValueError) as exc:
        print(f"check_patch_release.py: {exc}", file=sys.stderr)
        return 2
    if changed:
        print(f"{tag} changes golden output relative to {base_tag}; a patch release must be output-neutral:")
        for name in changed:
            print(f"  {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
