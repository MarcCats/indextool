"""Write and compare the generated files."""
from __future__ import annotations

import difflib
import os
from pathlib import Path

from .sources import read_file


def expected_text(text: str) -> str:
    return text.rstrip("\n") + "\n"


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(text.encode("utf-8"))
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def read_committed(base: Path, rel: str, source: str) -> str | None:
    data = read_file(base, rel, source)
    if data is None:
        return None
    return normalize_newlines(data.decode("utf-8", errors="replace"))


def compare(actual: str | None, wanted: str) -> str:
    if actual is None:
        return "missing"
    return "current" if actual == wanted else "stale"


def changed_lines(actual: str, wanted: str) -> list[str]:
    lines = list(difflib.unified_diff(actual.split("\n"), wanted.split("\n"), lineterm="", n=0))
    return [line for line in lines[2:] if not line.startswith("@@")]
