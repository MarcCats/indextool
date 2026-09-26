"""Decide which files exist and read their content from the working tree or the git index."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import gitio
from .errors import ConfigError
from .globs import GlobSet

DEFAULT_WALK_EXCLUDES = frozenset(
    {".git", "__pycache__", "venv", ".venv", "node_modules", ".idea", "site-packages",
     ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)
_REGULAR_MODES = frozenset({"100644", "100755"})


@dataclass(frozen=True)
class Discovered:
    files: dict[str, bytes]
    excluded: int
    mode: str


def read_file(base: Path, rel: str, source: str) -> bytes | None:
    """Bytes of `base/rel` from the working tree or the index; None when it does not exist there."""
    if source == "index":
        try:
            return gitio.cat_blobs(base, [f":./{rel}"])[0]
        except gitio.GitError:
            return None
    try:
        return (base / rel).read_bytes()
    except OSError:
        return None


def _use_git(base: Path, discovery: str, source: str) -> bool:
    if discovery == "walk":
        if source == "index":
            raise ConfigError('--source index needs git discovery, but discovery = "walk"')
        return False
    inside = gitio.in_work_tree(base)
    if discovery == "git" and not inside:
        raise ConfigError('discovery = "git" but the directory is not inside a git work tree')
    if source == "index" and not inside:
        raise ConfigError("--source index needs a git work tree")
    return inside


def _walk(base: Path) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(
            d for d in dirnames if d not in DEFAULT_WALK_EXCLUDES and not os.path.islink(os.path.join(dirpath, d))
        )
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if name.endswith(".py") and not os.path.islink(full):
                found.append(Path(full).relative_to(base).as_posix())
    return sorted(found)


def _check_case_collisions(paths: list[str]) -> None:
    seen: dict[str, str] = {}
    for path in paths:
        folded = path.casefold()
        if folded in seen and seen[folded] != path:
            raise ConfigError(f"paths differ only by case and cannot coexist on every OS: {seen[folded]} and {path}")
        seen[folded] = path


def discover(base: Path, discovery: str, exclude: GlobSet, source: str) -> Discovered:
    use_git = _use_git(base, discovery, source)
    shas: dict[str, str] = {}
    if use_git:
        entries = gitio.index_entries(base)
        unmerged = sorted({e.path for e in entries if e.stage != 0})
        if unmerged:
            raise ConfigError("unmerged paths in the index: " + ", ".join(unmerged[:5]))
        kept = [e for e in entries if e.mode in _REGULAR_MODES and e.path.endswith(".py")]
        shas = {e.path: e.sha for e in kept}
        paths = sorted(shas)
    else:
        paths = _walk(base)
    _check_case_collisions(paths)
    selected = [p for p in paths if not exclude.matches(p)]
    excluded = len(paths) - len(selected)
    files: dict[str, bytes] = {}
    if use_git and source == "index":
        for path, data in zip(selected, gitio.cat_blobs(base, [shas[p] for p in selected])):
            files[path] = data
    else:
        for path in selected:
            try:
                files[path] = (base / path).read_bytes()
            except OSError:
                continue  # tracked but deleted (or replaced by a directory) in the working tree
    return Discovered(files=files, excluded=excluded, mode="git" if use_git else "walk")
