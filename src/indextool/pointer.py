"""The managed pointer block that tells a coding agent where the generated files are and how to use them."""
from __future__ import annotations

from pathlib import Path

from .config import Config
from .errors import ConfigError
from .output import normalize_newlines
from .sources import read_file

BEGIN = "<!-- indextool:begin (managed: change indextool.toml, not this block) -->"
END = "<!-- indextool:end -->"
CANDIDATES = ("CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md")
_BEGIN_PREFIX = "<!-- indextool:begin"


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


def _fence(line: str) -> tuple[str, int] | None:
    """(character, length) when the line can open or close a fenced code block: up to three spaces of indent, then
    three or more backticks or tildes (a backtick fence has no backtick in its info string)."""
    rest = line.lstrip(" ")
    if len(line) - len(rest) > 3 or rest[:1] not in ("`", "~"):
        return None
    length = len(rest) - len(rest.lstrip(rest[0]))
    if length < 3 or (rest[0] == "`" and "`" in rest[length:]):
        return None
    return rest[0], length


def _scan(text: str) -> tuple[tuple[int, int] | None, int | None]:
    """((start, end) offsets of the one managed block or None, line of a code fence left open at the end or None).

    A marker counts only as a whole line and never inside a fenced code block, so a prose mention or a quoted example
    is not a block. Raises ConfigError for anything but zero blocks or exactly one properly paired block."""
    span: tuple[int, int] | None = None
    opened: tuple[int, int] | None = None  # (offset, line number) of a begin marker still waiting for its end
    fence: tuple[str, int, int] | None = None  # (character, length, line number) of the open fence
    offset = 0
    for number, line in enumerate(text.split("\n"), 1):
        marker = _fence(line)
        if fence is not None:
            if marker and marker[0] == fence[0] and marker[1] >= fence[1] and not line.strip().lstrip(fence[0]):
                fence = None
        elif marker:
            fence = (marker[0], marker[1], number)
        else:
            stripped = line.strip()
            if stripped.startswith(_BEGIN_PREFIX) and stripped.endswith("-->"):
                if opened:
                    raise ConfigError(f"unpaired indextool marker at line {opened[1]}")
                if span:
                    raise ConfigError(f"more than one managed pointer block at line {number}")
                opened = (offset, number)
            elif stripped == END:
                if not opened:
                    raise ConfigError(f"unpaired indextool marker at line {number}")
                span = (opened[0], offset + len(line))
                opened = None
        offset += len(line) + 1
    if opened:
        raise ConfigError(f"unpaired indextool marker at line {opened[1]}")
    return span, fence[2] if fence else None


def upsert(text: str, block: str) -> tuple[str, bool]:
    """Replace the managed block or append one; (new text, whether it changed).

    Raises ConfigError, and so returns nothing to write, when the markers are unpaired or repeated, or when an unclosed
    code fence would swallow an appended block: the user's text is never rewritten on a guess."""
    span, unclosed = _scan(text)
    if span:
        start, end = span
        if text[start:end] == block:
            return text, False
        return text[:start] + block + text[end:], True
    if unclosed:
        raise ConfigError(f"unclosed code fence at line {unclosed}")
    if not text.strip():
        return block + "\n", True
    return text.rstrip("\n") + "\n\n" + block + "\n", True


def has_block(text: str) -> bool:
    """Whether the text holds a managed block. Unpaired or repeated markers count as one, so that a caller goes on to
    upsert, which raises, instead of adding a second block next to them."""
    try:
        span, _unclosed = _scan(text)
    except ConfigError:
        return True
    return span is not None


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
        text = normalize_newlines(raw.decode("utf-8", errors="replace"))
        try:
            span, _unclosed = _scan(text)
        except ConfigError as exc:
            found = True
            problems.append(f"{rel}: {exc}; fix the markers by hand, then run: indextool init")
            continue
        if not span:
            continue
        found = True
        if text[span[0] : span[1]] != block:
            problems.append(f"{rel}: the managed pointer block is out of date; run: indextool init")
    return problems, found
