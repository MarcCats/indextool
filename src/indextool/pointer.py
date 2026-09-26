"""The managed pointer block that tells a coding agent where the generated files are and how to use them."""
from __future__ import annotations

import re
from pathlib import Path

from .config import Config
from .output import normalize_newlines
from .sources import read_file

BEGIN = "<!-- indextool:begin (managed: change indextool.toml, not this block) -->"
END = "<!-- indextool:end -->"
CANDIDATES = ("CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md")
_BLOCK = re.compile(r"<!-- indextool:begin[^\n]*?-->.*?<!-- indextool:end -->", re.DOTALL)


def render_block(cfg: Config) -> str:
    return "\n".join(
        [
            BEGIN,
            f"- `{cfg.architecture}` - generated map of layout, dependency layers, import cycles, routes, tables and "
            "what writes them, and the most-used modules. Read it whole for whole-repo questions. Regenerated from "
            "code, never edited by hand.",
            f"- `{cfg.index}` - generated one-line-per-module index (title, library or standalone, io, tables, "
            "routes). Search it with grep for where something lives or which modules read or write a table. It is "
            "large: do not read it whole.",
            "- Regenerate with `indextool generate`. CI runs `indextool verify` and fails when either file is stale.",
            END,
        ]
    )


def upsert(text: str, block: str) -> tuple[str, bool]:
    match = _BLOCK.search(text)
    if match:
        if match.group(0) == block:
            return text, False
        return text[: match.start()] + block + text[match.end() :], True
    if not text.strip():
        return block + "\n", True
    return text.rstrip("\n") + "\n\n" + block + "\n", True


def imports_agents(text: str) -> bool:
    return any(line.strip() == "@AGENTS.md" for line in text.split("\n"))


def targets(base: Path) -> list[str]:
    """Which instruction files receive the block (spec 7.2)."""
    existing = [rel for rel in CANDIDATES if (base / rel).is_file()]
    if not existing:
        return ["AGENTS.md"]
    claude = [rel for rel in existing if rel != "AGENTS.md"]
    if "AGENTS.md" in existing:
        for rel in claude:
            try:
                text = (base / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if imports_agents(text):
                return ["AGENTS.md"]
    return existing


def check_pointers(cfg: Config, source: str) -> tuple[list[str], bool]:
    """(problems, found_any_block): every managed block that differs from what the config renders is a problem."""
    block = render_block(cfg)
    problems: list[str] = []
    found = False
    for rel in CANDIDATES:
        raw = read_file(cfg.base, rel, source)
        if raw is None:
            continue
        match = _BLOCK.search(normalize_newlines(raw.decode("utf-8", errors="replace")))
        if not match:
            continue
        found = True
        if match.group(0) != block:
            problems.append(f"{rel}: the managed pointer block is out of date; run: indextool init")
    return problems, found
