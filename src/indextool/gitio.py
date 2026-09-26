"""Thin wrappers over the git plumbing commands the tool needs."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    """git is unavailable, or a git command failed."""


def _run(args: list[str], cwd: Path, data: bytes | None = None) -> bytes:
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), input=data, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"git is unavailable: {exc}") from exc
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(message or f"git {args[0]} failed with exit code {proc.returncode}")
    return proc.stdout


def in_work_tree(base: Path) -> bool:
    try:
        return _run(["rev-parse", "--is-inside-work-tree"], base).strip() == b"true"
    except GitError:
        return False


def top_level(base: Path) -> Path | None:
    try:
        text = _run(["rev-parse", "--show-toplevel"], base).decode("utf-8", "replace").strip()
    except GitError:
        return None
    return Path(text).resolve() if text else None


@dataclass(frozen=True)
class IndexEntry:
    mode: str
    sha: str
    stage: int
    path: str


def index_entries(base: Path) -> list[IndexEntry]:
    """Every index entry under `base`, with paths relative to `base`."""
    out = _run(["ls-files", "-z", "-s", "--", "."], base)
    entries = []
    for record in out.split(b"\0"):
        if not record:
            continue
        meta, _, path = record.partition(b"\t")
        mode, sha, stage = meta.decode("ascii").split(" ")
        entries.append(IndexEntry(mode, sha, int(stage), path.decode("utf-8", "replace")))
    return entries


def cat_blobs(base: Path, specs: list[str]) -> list[bytes]:
    """Content of each object spec (a sha, or `:./path` relative to `base`), in order."""
    if not specs:
        return []
    out = _run(["cat-file", "--batch"], base, ("\n".join(specs) + "\n").encode("utf-8"))
    blobs: list[bytes] = []
    pos = 0
    for spec in specs:
        eol = out.index(b"\n", pos)
        header = out[pos:eol].split(b" ")
        if len(header) != 3 or not header[2].isdigit():
            raise GitError(f"object not found: {spec}")
        size = int(header[2])
        blobs.append(out[eol + 1 : eol + 1 + size])
        pos = eol + 1 + size + 1
    return blobs


def unstaged(base: Path) -> set[str]:
    """Tracked files whose working-tree content differs from the index, relative to `base`."""
    out = _run(["diff", "--relative", "--name-only", "-z", "--", "."], base)
    return {p.decode("utf-8", "replace") for p in out.split(b"\0") if p}


def is_tracked(base: Path, rel: str) -> bool:
    return bool(_run(["ls-files", "-z", "--", f":(literal){rel}"], base).strip(b"\0"))
