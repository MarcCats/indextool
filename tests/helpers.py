"""Shared test helpers. Fixtures use invented names only (spec 1.6)."""
from __future__ import annotations

import subprocess
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
