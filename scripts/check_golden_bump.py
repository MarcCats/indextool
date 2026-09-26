"""Fail when golden output changed without a minor version bump.

Usage: python scripts/check_golden_bump.py <base-ref>

Golden files carry `indextool <major.minor>` in their header. A change to a golden that leaves that version
unchanged means a patch release could change users' output, which the versioning policy forbids."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

GOLDEN_DIR = "tests/golden"
_VERSION = re.compile(r"indextool (\d+\.\d+)")


def header_version(text: str) -> str | None:
    match = _VERSION.search(text)
    return match.group(1) if match else None


def bump_required(old: str, new: str) -> bool:
    if old == new:
        return False
    return header_version(old) == header_version(new)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout.decode("utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_golden_bump.py <base-ref>", file=sys.stderr)
        return 2
    base = argv[1]
    changed = [n for n in _git("diff", "--name-only", f"{base}...HEAD", "--", GOLDEN_DIR).split("\n") if n]
    failures: list[str] = []
    for name in changed:
        path = Path(name)
        if not path.exists():
            continue  # a deleted golden needs no bump
        try:
            old = _git("show", f"{base}:{name}")
        except subprocess.CalledProcessError:
            continue  # a new golden needs no bump
        new = path.read_text(encoding="utf-8")
        if bump_required(old.replace("\r\n", "\n"), new.replace("\r\n", "\n")):
            failures.append(name)
    if failures:
        print("golden output changed without a minor version bump (edit __version__ and regenerate the goldens):")
        for name in failures:
            print(f"  {name}")
        return 1
    print("golden output is unchanged, or the minor version was bumped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
