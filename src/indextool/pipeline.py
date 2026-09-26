"""Wire scan, graph, facts and render together, and write the results."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .errors import ConfigError
from .facts import derive_facts
from .output import compare, expected_text, read_committed, write_atomic
from .render import render_architecture, render_index
from .scan import resolve_edges, scan
from .sources import discover


@dataclass(frozen=True)
class Built:
    architecture: str
    index: str
    py_files: tuple[str, ...]
    module_count: int
    unparsable: int
    excluded: int


def build_from_files(files: dict[str, bytes], cfg: Config, excluded: int = 0) -> Built:
    mods = scan(files, cfg)
    resolve_edges(mods)
    facts = derive_facts(mods, cfg)
    return Built(
        architecture=render_architecture(mods, facts, cfg, excluded),
        index=render_index(mods, facts, cfg),
        py_files=tuple(sorted(files)),
        module_count=len(mods),
        unparsable=sum(1 for m in mods.values() if m.parse_error),
        excluded=excluded,
    )


def build(cfg: Config, source: str) -> Built:
    found = discover(cfg.base, cfg.discovery, cfg.exclude, source)
    return build_from_files(found.files, cfg, found.excluded)


def sync_files(cfg: Config, source: str, built: Built | None = None) -> list[tuple[str, str, int]]:
    """Write each output only when it differs from what is on disk. Returns (rel, action, chars) per output."""
    built = built or build(cfg, source)
    results: list[tuple[str, str, int]] = []
    for rel, produced in ((cfg.architecture, built.architecture), (cfg.index, built.index)):
        wanted = expected_text(produced)
        state = compare(read_committed(cfg.base, rel, "worktree"), wanted)
        if state != "current":
            try:
                write_atomic(cfg.base / rel, wanted)
            except OSError as exc:
                raise ConfigError(f"cannot write {rel}: {exc.strerror or exc}") from exc
        results.append((rel, {"missing": "created", "stale": "updated", "current": "unchanged"}[state], len(wanted)))
    return results
