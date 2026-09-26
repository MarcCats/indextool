"""Before publishing vX.Y.Z with Z > 0, assert the golden output equals that of vX.Y.0.

Usage: python scripts/check_patch_release.py <tag>

Patch releases are output-neutral by policy, so users who pin `indextool~=X.Y.0` never have to regenerate."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

GOLDEN_DIR = "tests/golden"
_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)\Z")
_DECLARED = re.compile(r'^__version__ = "([^"]+)"', re.MULTILINE)


def parse_tag(tag: str) -> tuple[int, int, int]:
    match = _TAG.match(tag)
    if not match:
        raise ValueError(f"not a release tag: {tag!r}")
    major, minor, patch = (int(g) for g in match.groups())
    return major, minor, patch


def declared_version(root: Path) -> str:
    text = (root / "src" / "indextool" / "__init__.py").read_text(encoding="utf-8")
    match = _DECLARED.search(text)
    if not match:
        raise ValueError("no __version__ in src/indextool/__init__.py")
    return match.group(1)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout.decode("utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_patch_release.py <tag>", file=sys.stderr)
        return 2
    tag = argv[1]
    try:
        major, minor, patch = parse_tag(tag)
        declared = declared_version(Path.cwd())
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if declared != f"{major}.{minor}.{patch}":
        print(f"tag {tag} does not match __version__ {declared}", file=sys.stderr)
        return 2
    if patch == 0:
        return 0
    base_tag = f"v{major}.{minor}.0"
    names = [n for n in _git("ls-tree", "-r", "--name-only", base_tag, "--", GOLDEN_DIR).split("\n") if n]
    problems = []
    for name in names:
        old = _git("show", f"{base_tag}:{name}").replace("\r\n", "\n")
        path = Path(name)
        new = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else None
        if old != new:
            problems.append(name)
    if problems:
        print(f"{tag} changes golden output relative to {base_tag}; a patch release must be output-neutral:")
        for name in problems:
            print(f"  {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
