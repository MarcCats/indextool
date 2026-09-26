"""Command line: argument parsing, exit codes, and nothing else."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import gitio
from .config import load_config
from .errors import ConfigError
from .pipeline import sync_files


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
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    args = _parser().parse_args(argv)
    return {"generate": _generate}[args.command](args)
