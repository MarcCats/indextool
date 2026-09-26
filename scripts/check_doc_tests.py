"""Fail when docs/rules.md cites a test that does not exist. Usage: python scripts/check_doc_tests.py

The documentation of what is computed must not silently diverge from the tests that pin it: the same idea the tool
applies to the architecture map."""
from __future__ import annotations

import re
import sys
from pathlib import Path

CITATION = re.compile(r"`(tests/[\w/]+\.py)::(\w+)`")


def missing_citations(doc_text: str, root: Path) -> list[str]:
    missing: list[str] = []
    for match in CITATION.finditer(doc_text):
        path = root / match.group(1)
        found = path.is_file() and re.search(
            rf"^def {re.escape(match.group(2))}\(", path.read_text(encoding="utf-8"), re.MULTILINE
        )
        if not found:
            missing.append(match.group(0))
    return missing


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    missing = missing_citations((root / "docs" / "rules.md").read_text(encoding="utf-8"), root)
    if missing:
        print("docs/rules.md cites tests that do not exist:")
        for citation in missing:
            print(f"  {citation}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
