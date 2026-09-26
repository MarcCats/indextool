"""Command line: argument parsing, exit codes, and nothing else."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, gitio
from . import init as init_command
from .config import load_config
from .errors import ConfigError
from .output import changed_lines, compare, expected_text, read_committed
from .pipeline import build, sync_files
from .pointer import CANDIDATES, check_pointers


def _warn(message: str) -> None:
    print(f"indextool: {message}", file=sys.stderr)


def _generate(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(Path.cwd(), args.config, args.source)
        if cfg.config_untracked:
            _warn(f"{cfg.config_file.name} is not tracked by git; CI will not see it (git add it)")
        for rel, action, size in sync_files(cfg, args.source):
            if action == "unchanged":
                print(f"indextool: {rel} is unchanged")
            else:
                print(f"indextool: wrote {rel} ({size:,} chars)")
    except (ConfigError, gitio.GitError) as exc:
        _warn(str(exc))
        return 2
    return 0


def _regenerate_command(source: str) -> str:
    return "indextool generate" + (" --source index" if source == "index" else "")


def _warn_unstaged(cfg, built, source: str) -> None:
    if source != "worktree" or not gitio.in_work_tree(cfg.base):
        return
    watched = set(built.py_files)
    watched.update(CANDIDATES)
    if cfg.config_file is not None:
        watched.add(cfg.config_file.name)
    touched = sorted(gitio.unstaged(cfg.base) & watched)
    if touched:
        _warn(
            f"warning: {len(touched)} tracked file(s) have unstaged changes (for example {touched[0]}); CI will see "
            "the committed version; use --source index to check what you would commit"
        )


def _verify(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(Path.cwd(), args.config, args.source)
        if cfg.config_untracked:
            _warn(f"{cfg.config_file.name} is not tracked by git, so CI would not see it; git add it first")
            return 2
        built = build(cfg, args.source)
    except (ConfigError, gitio.GitError) as exc:
        _warn(str(exc))
        return 2
    _warn_unstaged(cfg, built, args.source)
    regenerate = _regenerate_command(args.source)
    drift = False
    for rel, produced in ((cfg.architecture, built.architecture), (cfg.index, built.index)):
        wanted = expected_text(produced)
        actual = read_committed(cfg.base, rel, args.source)
        state = compare(actual, wanted)
        if state == "current":
            print(f"indextool: {rel} is current")
            continue
        drift = True
        if state == "missing":
            print(f"indextool: {rel} does not exist; write it with: {regenerate}")
            continue
        print(f"indextool: {rel} is out of date; regenerate it with: {regenerate}")
        lines = changed_lines(actual, wanted)
        print("\n".join(lines[:12]) + (f"\n... ({len(lines) - 12} more changed lines)" if len(lines) > 12 else ""))
    if drift:
        python = f"{sys.version_info.major}.{sys.version_info.minor}"
        print(f"indextool {__version__}, Python {python}")
        if built.unparsable:
            print(
                f"{built.unparsable} file(s) failed to parse under Python {python}; "
                "check that CI and local Python versions match."
            )
    problems, found = check_pointers(cfg, args.source)
    for problem in problems:
        print(f"indextool: {problem}")
    if not found:
        _warn("no managed pointer block found in CLAUDE.md, .claude/CLAUDE.md or AGENTS.md; run indextool init to add one")
    if problems:
        return 2
    return 1 if drift else 0


def _refresh(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(Path.cwd(), args.config, args.source)
        if cfg.config_untracked:
            _warn(f"{cfg.config_file.name} is not tracked by git; CI will not see it")
        built = build(cfg, args.source)
        if built.module_count == 0:
            _warn("refresh: no Python modules found; nothing written")
            return 0
        sync_files(cfg, args.source, built)
    except Exception as exc:  # a SessionStart hook must fail open, whatever went wrong
        _warn(f"refresh: {type(exc).__name__}: {exc}")
    return 0


def _init(args: argparse.Namespace) -> int:
    try:
        result = init_command.run(Path.cwd(), dry_run=args.dry_run, hook=args.hook)
    except (ConfigError, gitio.GitError) as exc:
        _warn(str(exc))
        return 2
    for item in result.items:
        print(f"  {item.action:<10} {item.rel}" + (f"  ({item.note})" if item.note else ""))
    if args.dry_run:
        print("(dry run: nothing was written)")
    else:
        written = [i.rel for i in result.items if i.action in ("created", "updated")]
        if written:
            print("git add " + " ".join(written))
    print()
    print(result.precommit)
    return 0


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config", type=Path, default=None, help="path to indextool.toml, or a pyproject.toml with [tool.indextool]"
    )
    common.add_argument(
        "--source",
        choices=("worktree", "index"),
        default="worktree",
        help="read files from the working tree (default) or from the git index",
    )
    parser = argparse.ArgumentParser(
        prog="indextool", description="Derive an architecture map from a Python repository and verify it in CI."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", parents=[common], help="write the architecture map and the module index")
    sub.add_parser("verify", parents=[common], help="fail when the committed files are stale (exit 1) or misconfigured (exit 2)")
    sub.add_parser("refresh", parents=[common], help="silent, fail-open regeneration for a session-start hook")
    init_parser = sub.add_parser("init", help="add config, pointer, hook, CI workflow and .gitattributes; then generate")
    init_parser.add_argument("--dry-run", action="store_true", help="show what would change and write nothing")
    init_parser.add_argument(
        "--hook",
        choices=("shared", "local", "none"),
        default="shared",
        help="where to put the SessionStart hook: .claude/settings.json (shared, default), settings.local.json, or nowhere",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    try:
        args = _parser().parse_args(argv)
    except SystemExit:
        given = sys.argv[1:] if argv is None else argv
        if given[:1] == ["refresh"]:
            return 0  # even a bad argument must not fail a session
        raise
    return {"generate": _generate, "verify": _verify, "refresh": _refresh, "init": _init}[args.command](args)
