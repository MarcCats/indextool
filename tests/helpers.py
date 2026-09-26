"""Shared test helpers. Fixtures use invented names only (spec 1.6)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# git reads no configuration of the person or the machine that runs the tests (autocrlf, signing, hooks, identity), so
# a result cannot depend on it. The empty file lives as long as the interpreter does.
_GIT_HOME = tempfile.TemporaryDirectory(prefix="indextool-git-")
_EMPTY_GIT_CONFIG = Path(_GIT_HOME.name) / "gitconfig"
_EMPTY_GIT_CONFIG.write_bytes(b"")


def isolated_env(extra: dict | None = None) -> dict:
    """The environment of every git call and every CLI subprocess. A value of None in `extra` removes the variable."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(_EMPTY_GIT_CONFIG), "GIT_CONFIG_NOSYSTEM": "1"}
    for key, value in (extra or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def git(repo: Path, *args: str, input: bytes | None = None) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, input=input, env=isolated_env()
    )
    return proc.stdout.decode("utf-8", "replace")


def write_files(root: Path, files: dict) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "tag.gpgsign", "false")


def commit_all(repo: Path, message: str = "commit") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)


def make_repo(parent: Path, files: dict, name: str = "repo", commit: bool = True) -> Path:
    repo = parent / name
    init_repo(repo)
    write_files(repo, files)
    if commit:
        commit_all(repo)
    return repo


def make_config(directory: Path, toml_text: str = ""):
    from indextool.config import load_config

    directory.mkdir(parents=True, exist_ok=True)
    if toml_text:
        (directory / "indextool.toml").write_text(toml_text, encoding="utf-8")
    return load_config(directory)


@dataclass
class Result:
    code: int
    out: str
    err: str


def run_cli(cwd: Path, *args: str, env: dict | None = None) -> Result:
    proc = subprocess.run(
        [sys.executable, "-m", "indextool", *args], cwd=cwd, env=isolated_env(env), capture_output=True
    )
    return Result(proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace"))
