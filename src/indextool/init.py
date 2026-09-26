"""Idempotent project setup: config, pointer, hook, CI workflow, .gitattributes. It edits only what the standard
library can edit safely; anything else is printed as a snippet."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import FORMAT_VERSION, gitio
from .config import CONFIG_NAME, load_config
from .errors import ConfigError
from .output import normalize_newlines, write_atomic
from .pipeline import sync_files
from .pointer import CANDIDATES, has_block, render_block, targets, upsert

HOOK_COMMAND = "indextool refresh"
LOCAL_SETTINGS = ".claude/settings.local.json"

PRECOMMIT_SNIPPET = """\
To run the check in pre-commit, add this to .pre-commit-config.yaml:

repos:
  - repo: local
    hooks:
      - id: indextool-verify
        name: indextool verify
        entry: indextool verify --source index
        language: system
        pass_filenames: false
        always_run: true
"""

_WORKFLOW = """\
name: architecture-map
on:
  push:
  pull_request:
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "@PY@"
      - run: pip install "indextool~=@FMT@.0"
@VERIFY@"""


@dataclass(frozen=True)
class Item:
    rel: str
    action: str
    note: str = ""


@dataclass(frozen=True)
class InitResult:
    items: tuple[Item, ...]
    precommit: str
    base: Path | None = None


def detect_roots(base: Path) -> list[str]:
    src = base / "src"
    if src.is_dir() and next(src.rglob("*.py"), None) is not None:
        return ["src"]
    return ["."]


def render_config(roots: list[str]) -> str:
    listed = ", ".join(f'"{r}"' for r in roots)
    return (
        "# indextool configuration. Every key is optional; see the indextool documentation for the full list.\n"
        f"roots = [{listed}]\n"
        'architecture = "docs/architecture.md"\n'
        'index = "docs/architecture.index.txt"\n'
    )


def merge_hook(text: str | None) -> tuple[str | None, str]:
    """Add the SessionStart hook to a Claude Code settings file's text. Returns (new_text_or_None, outcome)."""
    try:
        data = json.loads(text) if text and text.strip() else {}
    except json.JSONDecodeError:
        return None, "skipped"
    if not isinstance(data, dict):
        return None, "skipped"
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return None, "skipped"
    session = hooks.setdefault("SessionStart", [])
    if not isinstance(session, list):
        return None, "skipped"
    for group in session:
        entries = group.get("hooks") if isinstance(group, dict) else None
        for hook in entries if isinstance(entries, list) else []:  # any other shape is not ours: kept as it is
            if isinstance(hook, dict) and HOOK_COMMAND in str(hook.get("command", "")):
                return None, "unchanged"
    session.append({"hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": 30}]})
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n", "changed"


def workflow_text(workdir: str) -> str:
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    verify = "      - run: indextool verify\n" + (f"        working-directory: {workdir}\n" if workdir else "")
    return _WORKFLOW.replace("@PY@", python).replace("@FMT@", FORMAT_VERSION).replace("@VERIFY@", verify)


def _with_line(text: str | None, line: str) -> str | None:
    existing = text or ""
    if line in [ln.strip() for ln in existing.split("\n")]:
        return None
    prefix = existing if (not existing or existing.endswith("\n")) else existing + "\n"
    return prefix + line + "\n"


def _read(path: Path, rel: str) -> tuple[str | None, bool]:
    """(the file's text with LF newlines, or None when it does not exist; whether the file used CRLF). Raises
    UnicodeDecodeError for a file that is not UTF-8 and ConfigError for one that cannot be read."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, False
    except OSError as exc:
        raise ConfigError(f"cannot read {rel}: {exc}") from exc
    return normalize_newlines(raw.decode("utf-8")), b"\r\n" in raw


def _rel(path: Path, base: Path) -> str:
    return Path(os.path.relpath(path, base)).as_posix()


def _real(path: Path) -> Path:
    """The file a write to this path lands on: a symlink is written through, never replaced."""
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return path


def run(start: Path, *, dry_run: bool = False, hook: str = "shared") -> InitResult:
    cfg = load_config(start)
    base = cfg.base
    top = gitio.top_level(base) or base
    items: list[Item] = []
    writes: dict[Path, tuple[str, str]] = {}  # the file each write lands on -> (its name as the user knows it, text)

    def load(path: Path) -> tuple[str | None, bool] | None:
        """_read, or None (and a skipped item) for a file that is not UTF-8: it is left alone."""
        try:
            return _read(path, _rel(path, base))
        except UnicodeDecodeError:
            items.append(Item(_rel(path, base), "skipped", "not valid UTF-8; left alone"))
            return None

    def stage(path: Path, text: str | None, crlf: bool = False, note: str = "") -> None:
        """Plan a write. Text is LF here; a file that used CRLF keeps it, and an unchanged file (text None) is not
        rewritten. The write goes to the file a symlink points at, and a file reachable under two names is planned
        once."""
        rel = _rel(path, base)
        real = _real(path)
        if real in writes:
            items.append(Item(rel, "unchanged", f"same file as {writes[real][0]}"))
            return
        if text is None:
            items.append(Item(rel, "unchanged", note))
            return
        items.append(Item(rel, "updated" if real.exists() else "created", note))
        writes[real] = (rel, text.replace("\n", "\r\n") if crlf else text)

    if cfg.config_file is not None:
        items.append(Item(_rel(cfg.config_file, base), "skipped", "configuration already present"))
    else:
        stage(base / CONFIG_NAME, render_config(detect_roots(base)))

    block = render_block(cfg)
    placement = targets(base)
    # Every candidate that already holds a block is refreshed, because verify checks them all; a candidate that is
    # not a placement target and holds none gets none.
    for rel in placement + [c for c in CANDIDATES if c not in placement and (base / c).is_file()]:
        path = base / rel
        loaded = load(path)
        if loaded is None:
            continue
        text, crlf = loaded[0] or "", loaded[1]
        if rel not in placement and not has_block(text):
            continue
        try:
            new_text, changed = upsert(text, block)
        except ConfigError as exc:
            raise ConfigError(f"{rel}: {exc}") from exc
        stage(path, new_text if changed else None, crlf)

    if hook == "none":
        items.append(Item(".claude/settings.json", "skipped", "hook disabled (--hook none)"))
    else:
        hook_rel = ".claude/settings.json" if hook == "shared" else LOCAL_SETTINGS
        settings = load(base / hook_rel)
        if settings is not None:
            new_text, outcome = merge_hook(settings[0])
            if outcome == "skipped":
                items.append(Item(hook_rel, "skipped", "not valid JSON; left alone (add the hook by hand)"))
            else:
                stage(base / hook_rel, new_text, settings[1])
        if hook == "local":
            ignore = base / ".gitignore"
            listed = load(ignore)
            if listed is not None:
                stage(ignore, _with_line(listed[0], LOCAL_SETTINGS), listed[1])

    workflow = top / ".github" / "workflows" / "indextool.yml"
    if workflow.exists():
        items.append(Item(_rel(workflow, base), "skipped", "exists; not overwritten"))
    else:
        workdir = "" if base == top else base.relative_to(top).as_posix()
        stage(workflow, workflow_text(workdir))

    attributes = base / ".gitattributes"
    existing = load(attributes)
    if existing is not None:
        original, crlf = existing
        updated = original
        for out in (cfg.architecture, cfg.index):
            updated = _with_line(updated, f"{out} text eol=lf") or updated
        stage(attributes, None if updated == original else updated, crlf)

    if not dry_run:
        for real, (rel, text) in writes.items():
            try:
                write_atomic(real, text)
            except OSError as exc:
                raise ConfigError(f"cannot write {rel}: {exc}") from exc
        for rel, action, _size in sync_files(load_config(base), "worktree"):
            items.append(Item(rel, action, "generated"))
    else:
        items.append(Item(cfg.architecture, "planned", "generated after setup"))
        items.append(Item(cfg.index, "planned", "generated after setup"))
    return InitResult(items=tuple(items), precommit=PRECOMMIT_SNIPPET, base=base)
