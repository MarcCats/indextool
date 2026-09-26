"""Shared test helpers. Fixtures use invented names only (spec 1.6)."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def git(repo: Path, *args: str, input: bytes | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, input=input)
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
    full_env = {**os.environ, **(env or {})}
    proc = subprocess.run(
        [sys.executable, "-m", "indextool", *args], cwd=cwd, env=full_env, capture_output=True
    )
    return Result(proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace"))
