"""Facts a regex or a decorator can read out of the source with no model in the loop."""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field

from .config import TABLES_TOKEN, Config
from .errors import ConfigError
from .scan import SENTINEL, ImportSpec, Module


@dataclass
class Facts:
    created: set[str] = field(default_factory=set)
    tables: dict[str, set[str]] = field(default_factory=dict)
    writers: dict[str, set[str]] = field(default_factory=dict)
    routes: dict[str, list[str]] = field(default_factory=dict)
    io: dict[str, str] = field(default_factory=dict)


def import_names(imports: tuple[ImportSpec, ...]) -> set[str]:
    """Dotted names an import statement can be matched by. Relative imports are repository modules, never libraries."""
    names: set[str] = set()
    for spec in imports:
        if spec.level != 0 or not spec.module:
            continue
        names.add(spec.module)
        names.update(f"{spec.module}.{n}" for n in spec.names if n != "*")
    return names


def _matches(names: set[str], entries: tuple[str, ...]) -> bool:
    return any(n == e or n.startswith(e + ".") for n in names for e in entries)


def _writes_sql(mod: Module, cfg: Config) -> bool:
    if mod.calls_to_sql:
        return True
    return any(
        rx.search(literal.replace(SENTINEL, "x")) for literal in mod.literals for rx in cfg.sql.write_any
    )


def _io_rating(mod: Module, cfg: Config) -> str:
    if mod.parse_error:
        return ""
    names = import_names(mod.imports)
    kinds = {kind for kind, entries in cfg.io if _matches(names, entries)}
    parts: list[str] = []
    if "db" in kinds:
        parts.append("db-rw" if _writes_sql(mod, cfg) else "db-r")
    if "network" in kinds:
        parts.append("network")
    if "http" in kinds:
        parts.append("http")
    return "+".join(parts)


def _compile_template(template: str, alternation: str, where: str) -> re.Pattern[str]:
    """A `use` or `write` template with the created names put in. Config only saw it with a dummy word, so real names
    (a look-behind wants one fixed width) can still break it; that is a misconfiguration, not a crash."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            return re.compile(template.replace(TABLES_TOKEN, alternation), re.IGNORECASE)
    except (re.error, FutureWarning, OverflowError, RecursionError) as exc:
        raise ConfigError(f"{where}: {template!r} does not compile with the table names found: {exc}") from exc


def derive_facts(mods: dict[str, Module], cfg: Config) -> Facts:
    facts = Facts()
    texts: dict[str, str] = {}
    for key in sorted(mods):
        mod = mods[key]
        if mod.is_test:
            continue
        texts[key] = "\n".join(mod.literals).replace(SENTINEL, "?")
        if mod.routes:
            facts.routes[key] = list(mod.routes)
        facts.io[key] = _io_rating(mod, cfg)
    for text in texts.values():
        for rx in cfg.sql.create:
            facts.created.update(rx.findall(text))
    if facts.created:
        canon: dict[str, str] = {}
        for name in sorted(facts.created):
            canon.setdefault(name.lower(), name)
        alternation = "|".join(re.escape(n) for n in sorted(facts.created, key=lambda n: (-len(n), n)))
        detectors = [(_compile_template(t, alternation, "[sql] use"), facts.tables) for t in cfg.sql.use]
        detectors += [(_compile_template(t, alternation, "[sql] write"), facts.writers) for t in cfg.sql.write]
        for key, text in texts.items():
            for rx, into in detectors:
                for found in set(rx.findall(text)):
                    if found.lower() in canon:  # a template's group may capture more than a created name; that is no fact
                        into.setdefault(canon[found.lower()], set()).add(key)
    return facts
