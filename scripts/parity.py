"""Compare indextool output with another generator's output and classify every differing line.

Usage: python scripts/parity.py {map|index} EXPECTED ACTUAL

Exit 0 when the two texts are identical once the allowed categories are removed, 1 otherwise. The script names no
project; the parity config and the reference outputs are kept outside this repository."""
from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

MAP_HEAD_LINES = 3
CANNOT_SAY_HEADING = "## What this"
_ALLOWED_ANYWHERE = [
    re.compile(r"^Detector: "),
    re.compile(r"^None found by this detector\.$"),
    re.compile(r"^- \d+ files? excluded by the configured"),
    re.compile(r"^- \d+ files? could not be parsed"),
]


def reduce(kind: str, text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").rstrip("\n").split("\n")
    if kind == "index":
        return lines[1:]
    lines = lines[MAP_HEAD_LINES:]
    for i, line in enumerate(lines):
        if line.startswith(CANNOT_SAY_HEADING):
            lines = lines[:i]
            break
    return [line for line in lines if not any(rx.match(line) for rx in _ALLOWED_ANYWHERE)]


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] not in ("map", "index"):
        print("usage: parity.py {map|index} EXPECTED ACTUAL", file=sys.stderr)
        return 2
    kind = argv[1]
    expected = reduce(kind, Path(argv[2]).read_text(encoding="utf-8"))
    actual = reduce(kind, Path(argv[3]).read_text(encoding="utf-8"))
    if expected == actual:
        print("parity: identical apart from the allowed categories")
        return 0
    print("parity: the outputs differ outside the allowed categories:")
    for line in list(difflib.unified_diff(expected, actual, "expected", "actual", lineterm="", n=0))[:80]:
        print(line)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
