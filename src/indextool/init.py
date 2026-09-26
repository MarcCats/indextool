"""Idempotent project setup: config, pointer, hook, CI workflow, .gitattributes. It edits only what the standard
library can edit safely; anything else is printed as a snippet."""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import FORMAT_VERSION, gitio
from .config import CONFIG_NAME, load_config, project_name
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
permissions:
  contents: read
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "@PY@"
      - run: @INSTALL@
@VERIFY@"""


@dataclass(frozen=True)
class Item:
    rel: str
    action: str
    note: str = ""


@dataclass(frozen=True)
class CiGap:
    """An existing workflow that does not run `indextool verify` in this sub-project."""

    workflow: str  # relative to the base directory
    workdir: str  # the sub-project's directory relative to the git top level
    step: str  # the step to add to the workflow's job


@dataclass(frozen=True)
class InitResult:
    items: tuple[Item, ...]
    precommit: str
    base: Path | None = None
    ci_commands: str = ""
    ci_gap: CiGap | None = None
    outputs: tuple[str, ...] = ()  # the generated files, relative to the base directory


def detect_roots(base: Path) -> list[str]:
    src = base / "src"
    if src.is_dir() and next(src.rglob("*.py"), None) is not None:
        return ["src"]
    return ["."]


def _toml_string(value: str) -> str:
    """A TOML basic string: backslash, quote and control characters are escaped."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + "".join(f"\\u{ord(c):04x}" if ord(c) < 0x20 or ord(c) == 0x7F else c for c in escaped) + '"'


def default_title(base: Path) -> str:
    """The title written into a new config: `[project].name` of the base directory's pyproject.toml, else the name of
    the folder. It is recorded once, in the committed config, so the output never depends on the folder afterwards."""
    return project_name(base, "worktree") or base.name


def render_config(roots: list[str], title: str = "") -> str:
    listed = ", ".join(f'"{r}"' for r in roots)
    return (
        "# indextool configuration. Every key is optional; see the indextool documentation for the full list.\n"
        + (f"title = {_toml_string(title)}\n" if title else "")
        + f"roots = [{listed}]\n"
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


def install_command() -> str:
    """The compatible-release pin: a patch release of indextool cannot change the output."""
    return f'pip install "indextool~={FORMAT_VERSION}.0"'


def verify_step(workdir: str) -> str:
    return "      - run: indextool verify\n" + (f"        working-directory: {workdir}\n" if workdir else "")


def ci_commands() -> str:
    return "\n".join(["For other CI systems, run these two commands:", f"  {install_command()}", "  indextool verify"])


def workflow_text(workdir: str) -> str:
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    return (
        _WORKFLOW.replace("@PY@", python).replace("@INSTALL@", install_command()).replace("@VERIFY@", verify_step(workdir))
    )


def _checks(workflow: Path, workdir: str) -> bool:
    """Whether the workflow has a `working-directory: <workdir>` line. A file that cannot be read gets the benefit of
    the doubt: the message is only worth printing when it is certain."""
    try:
        text = normalize_newlines(workflow.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return True
    line = re.compile(r"(?:-\s+)?working-directory:\s*[\"']?" + re.escape(workdir) + r"[\"']?\s*(?:#.*)?")
    return any(line.fullmatch(ln.strip()) for ln in text.split("\n"))


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


def run(start: Path, *, dry_run: bool = False, hook: str = "shared", config: Path | None = None) -> InitResult:
    cfg = load_config(start, config)
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
        stage(base / CONFIG_NAME, render_config(detect_roots(base), default_title(base)))

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
    workdir = "" if base == top else base.relative_to(top).as_posix()
    ci_gap = None
    if workflow.exists():
        items.append(Item(_rel(workflow, base), "skipped", "exists; not overwritten"))
        if workdir and not _checks(workflow, workdir):
            ci_gap = CiGap(_rel(workflow, base), workdir, verify_step(workdir))
    else:
        stage(workflow, workflow_text(workdir))

    attributes = base / ".gitattributes"
    existing = load(attributes)
    if existing is not None:
        original, crlf = existing
        updated = original
        for out in (cfg.architecture, cfg.index):
            updated = _with_line(updated, f"{out} text eol=lf") or updated
        stage(attributes, None if updated == original else updated, crlf)

    outputs = (cfg.architecture, cfg.index)
    if not dry_run:
        for real, (rel, text) in writes.items():
            try:
                write_atomic(real, text)
            except OSError as exc:
                raise ConfigError(f"cannot write {rel}: {exc}") from exc
        final = load_config(base, cfg.config_file)  # the config as written, when there was none before
        for rel, action, _size in sync_files(final, "worktree"):
            items.append(Item(rel, action, "generated"))
        outputs = (final.architecture, final.index)
    else:
        items.append(Item(cfg.architecture, "planned", "generated after setup"))
        items.append(Item(cfg.index, "planned", "generated after setup"))
    return InitResult(
        items=tuple(items),
        precommit=PRECOMMIT_SNIPPET,
        base=base,
        ci_commands=ci_commands(),
        ci_gap=ci_gap,
        outputs=outputs,
    )
