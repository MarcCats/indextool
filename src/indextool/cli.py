"""Command line: argument parsing, exit codes, and nothing else."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, gitio
from . import init as init_command
from .config import load_config
from .errors import ConfigError
from .output import changed_lines, compare, expected_text, read_committed
from .pipeline import build, sync_files
from .pointer import CANDIDATES, check_pointers, pointer_states


def _warn(message: str) -> None:
    print(f"indextool: {' '.join(message.split())}", file=sys.stderr)  # one line, whatever git or an exception said


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
    try:
        touched = sorted(gitio.unstaged(cfg.base) & watched)
    except gitio.GitError as exc:  # advisory only: the verdict and the exit code do not depend on it
        _warn(f"warning: could not check for unstaged changes: {exc}")
        return
    if touched:
        _warn(
            f"warning: {len(touched)} tracked file(s) have unstaged changes (for example {touched[0]}); CI will see "
            "the committed version; use --source index to check what you would commit"
        )


def _no_pointer_note(cfg, source: str) -> str:
    """Why no managed pointer block was found. Under --source index a block can exist in the working tree without
    being staged, and then `run indextool init` is not the remedy."""
    where = "CLAUDE.md, .claude/CLAUDE.md or AGENTS.md"
    if source != "index":
        return f"no managed pointer block found in {where}; run indextool init to add one"
    local = pointer_states(cfg, "worktree")
    if not local:
        return f"no managed pointer block found in {where}; run indextool init to add one, then git add the file it writes"
    files = [rel for rel, _state, _detail in local]
    names = " and ".join(files) if len(files) < 3 else ", ".join(files[:-1]) + " and " + files[-1]
    subject = f"the managed pointer block in {names} is" if len(files) == 1 else f"the managed pointer blocks in {names} are"
    if all(state == "current" for _rel, state, _detail in local):
        return f"{subject} current in the working tree but not staged; stage it with: git add {' '.join(files)}"
    return f"{subject} out of date in the working tree; run indextool init, then git add {' '.join(files)}"


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
        if args.source == "index":
            # What would be committed is what is staged. A file that is right in the working tree only needs
            # staging; regenerating it would change nothing and the check would keep failing.
            stage = compare(read_committed(cfg.base, rel, "worktree"), wanted) == "current"
            then = f", then git add {rel}"
            if stage:
                print(f"indextool: {rel} is current in the working tree but not staged; stage it with: git add {rel}")
            elif state == "missing":
                print(f"indextool: {rel} is not in the index; write it with: {regenerate}{then}")
            else:
                print(f"indextool: {rel} is out of date; regenerate it with: {regenerate}{then}")
        elif state == "missing":
            print(f"indextool: {rel} does not exist; write it with: {regenerate}")
        else:
            print(f"indextool: {rel} is out of date; regenerate it with: {regenerate}")
        if state == "missing":
            continue
        lines = changed_lines(actual, wanted)
        print("\n".join(lines[:12]) + (f"\n... (+{len(lines) - 12} more changed lines)" if len(lines) > 12 else ""))
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
        _warn(_no_pointer_note(cfg, args.source))
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


def _from(path: Path, cwd: Path) -> str:
    """A path as the shell in `cwd` can use it."""
    try:
        return Path(os.path.relpath(path, cwd)).as_posix()
    except ValueError:  # another drive
        return path.as_posix()


def _git_add_line(base: Path, items, cwd: Path) -> str | None:
    """The command that stages what init wrote, or None when there is nothing to stage. A symlink is staged through
    the file it points at, and a path git ignores is left out (git add refuses the whole command over one)."""
    top = gitio.top_level(base)
    if top is None:
        return None
    files: list[Path] = []
    for item in items:
        if item.action in ("created", "updated"):
            real = (base / item.rel).resolve()
            if top in real.parents and real not in files:
                files.append(real)
    skip = gitio.ignored(base, [_from(f, base) for f in files])
    staged = [f for f in files if _from(f, base) not in skip]
    return "git add " + " ".join(_from(f, cwd) for f in staged) if staged else None


def _init(args: argparse.Namespace) -> int:
    try:
        result = init_command.run(Path.cwd(), dry_run=args.dry_run, hook=args.hook, config=args.config)
    except (ConfigError, gitio.GitError) as exc:
        _warn(str(exc))
        return 2
    cwd = Path.cwd().resolve()
    base = result.base or cwd
    print(f"initialised {_from(base, cwd)}")
    for item in result.items:
        print(f"  {item.action:<10} {_from(base / item.rel, cwd)}" + (f"  ({item.note})" if item.note else ""))
    if args.dry_run:
        print("(dry run: nothing was written)")
    else:
        line = _git_add_line(base, result.items, cwd)
        if line:
            print(line)
    ignored = gitio.ignored(base, list(result.outputs))  # an ignored output is not in the commit CI checks out
    for rel in result.outputs:
        if rel in ignored:
            print(f"note: {_from(base / rel, cwd)} is ignored by git; CI cannot verify it")
    print()
    gap = result.ci_gap
    if gap:
        print("CI does not check this sub-project yet:")
        print(
            f"The existing workflow {_from(base / gap.workflow, cwd)} does not run indextool verify in {gap.workdir}; "
            "add this step to its job:"
        )
        print()
        print(gap.step)
    print(result.ci_commands)
    print()
    print(result.precommit)
    return 0


def _parser() -> argparse.ArgumentParser:
    config_option = argparse.ArgumentParser(add_help=False)
    config_option.add_argument(
        "--config", type=Path, default=None, help="path to indextool.toml, or a pyproject.toml with [tool.indextool]"
    )
    common = argparse.ArgumentParser(add_help=False, parents=[config_option])
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
    init_parser = sub.add_parser(
        "init", parents=[config_option], help="add config, pointer, hook, CI workflow and .gitattributes; then generate"
    )
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
