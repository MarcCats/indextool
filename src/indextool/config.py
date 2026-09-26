"""Locate, load, validate and normalize configuration. Detectors are data, never code."""
from __future__ import annotations

import re
import tomllib
import warnings
from dataclasses import dataclass
from pathlib import Path

from . import gitio
from .errors import ConfigError
from .globs import GlobSet
from .sources import read_file

CONFIG_NAME = "indextool.toml"
TABLES_TOKEN = "@TABLES@"
IO_KINDS = ("db", "network", "http")
SQL_KEYS = ("create", "use", "write", "write_any")
_TOP_KEYS = frozenset({"title", "roots", "exclude", "tests", "architecture", "index", "discovery", "routes", "io", "sql"})
_DOTTED = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\Z")

DEFAULT_TESTS = ("test_*.py", "*_test.py", "tests/", "test/")
DEFAULT_ARCHITECTURE = "docs/architecture.md"
DEFAULT_INDEX = "docs/architecture.index.txt"
DEFAULT_DECORATORS = ("route", "get", "post", "put", "patch", "delete", "head", "options", "websocket", "api_route")
DEFAULT_IO = (
    ("db", ("sqlite3", "sqlalchemy", "psycopg", "psycopg2", "asyncpg", "pymysql", "duckdb")),
    ("network", ("requests", "urllib.request", "urllib3", "aiohttp", "httpx")),
    ("http", ("flask", "fastapi", "starlette")),
)
DEFAULT_SQL = (
    ("create", (r'CREATE\s+(?:VIRTUAL\s+)?TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|AS\b|USING\b)',)),
    ("use", (r'\b(?:FROM|JOIN|INTO|UPDATE|TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+(@TABLES@)\b',)),
    ("write", (r'\b(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|ALTER\s+TABLE|DROP\s+TABLE'
               r'|CREATE\s+(?:VIRTUAL\s+)?TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+(@TABLES@)\b',)),
    ("write_any", (r'\b(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|REPLACE\s+INTO|UPDATE\s+[\w.\"`\[\]]+\s+SET|DELETE\s+FROM'
                   r'|CREATE\s+(?:TEMP(?:ORARY)?\s+)?(?:TABLE|INDEX|VIEW)|DROP\s+(?:TABLE|INDEX|VIEW)|ALTER\s+TABLE)\b',)),
)


@dataclass(frozen=True)
class SqlDetectors:
    create: tuple[re.Pattern[str], ...]
    use: tuple[str, ...]
    write: tuple[str, ...]
    write_any: tuple[re.Pattern[str], ...]
    is_default: bool


@dataclass(frozen=True)
class Config:
    base: Path
    config_file: Path | None
    config_untracked: bool
    title: str
    roots: tuple[str, ...]
    exclude: GlobSet
    tests: GlobSet
    architecture: str
    index: str
    discovery: str
    route_decorators: tuple[str, ...]
    io: tuple[tuple[str, tuple[str, ...]], ...]
    sql: SqlDetectors

    @property
    def io_map(self) -> dict[str, tuple[str, ...]]:
        return dict(self.io)


def _parse_toml(raw: bytes | None) -> dict | None:
    """The parsed table, or None when there is no content or it is not valid UTF-8 TOML."""
    if raw is None:
        return None
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None


def _indextool_table(data: dict | None) -> dict | None:
    """`[tool.indextool]` of parsed pyproject content, or None when it is absent or not shaped like a table."""
    tool = data.get("tool") if data else None
    table = tool.get("indextool") if isinstance(tool, dict) else None
    return table if isinstance(table, dict) else None


def _config_file_in(directory: Path, source: str) -> Path | None:
    """The config file `directory` holds in `source` (the working tree or the index), or None."""
    if source == "index":
        has_toml = read_file(directory, CONFIG_NAME, source) is not None
    else:
        has_toml = (directory / CONFIG_NAME).is_file()
    if has_toml:
        return directory / CONFIG_NAME
    if _indextool_table(_parse_toml(read_file(directory, "pyproject.toml", source))) is not None:
        return directory / "pyproject.toml"
    return None


def _locate(start: Path, source: str) -> tuple[Path | None, Path]:
    top = gitio.top_level(start) if gitio.in_work_tree(start) else None
    directory = start
    while True:
        found = _config_file_in(directory, source)
        if found is not None:
            return found, directory
        if directory == top or directory.parent == directory:
            break
        directory = directory.parent
    return None, (top or start)


def _project_name(base: Path, source: str) -> str | None:
    data = _parse_toml(read_file(base, "pyproject.toml", source))
    project = data.get("project") if data else None
    name = project.get("name") if isinstance(project, dict) else None
    return name if isinstance(name, str) else None


def _string_list(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where}: expected a list of strings")
    return tuple(value)


def _rel_path(value: object, where: str, allow_dot: bool) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{where}: expected a string")
    p = value.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    p = p.rstrip("/")
    if p in ("", "."):
        if allow_dot:
            return "."
        raise ConfigError(f"{where}: {value!r} must name a file")
    parts = p.split("/")
    if p.startswith("/") or (len(p) > 1 and p[1] == ":") or ".." in parts:
        raise ConfigError(f"{where}: {value!r} must be a relative path inside the repository")
    return "/".join(parts)


def _check_roots(roots: tuple[str, ...]) -> None:
    for i, a in enumerate(roots):
        for b in roots[i + 1 :]:
            if a == b or a == "." or b == "." or b.startswith(a + "/") or a.startswith(b + "/"):
                raise ConfigError(f"roots {a!r} and {b!r} overlap")


def _compile(pattern: str, where: str, groups: int | None = None) -> re.Pattern[str]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)  # e.g. "Possible nested set": a change coming in a later Python
            rx = re.compile(pattern, re.IGNORECASE)
    except (re.error, FutureWarning, OverflowError, RecursionError) as exc:
        raise ConfigError(f"{where}: invalid regex {pattern!r}: {exc}") from exc
    if groups is not None and rx.groups != groups:
        raise ConfigError(f"{where}: {pattern!r} must contain exactly {groups} capture group")
    return rx


def _templates(patterns: tuple[str, ...], where: str) -> tuple[str, ...]:
    for pattern in patterns:
        if pattern.count(TABLES_TOKEN) != 1:
            raise ConfigError(f"{where}: {pattern!r} must contain {TABLES_TOKEN} exactly once")
        _compile(pattern.replace(TABLES_TOKEN, "zz"), where, groups=1)
    return patterns


def _globs(patterns: tuple[str, ...], key: str) -> GlobSet:
    try:
        return GlobSet(patterns)
    except ConfigError as exc:
        raise ConfigError(f"{key}: {exc}") from exc


def _known_keys(table: object, allowed: tuple[str, ...] | frozenset[str], where: str) -> dict:
    if table is None:  # the section is absent; a present but falsy value (`sql = false`) is not
        return {}
    if not isinstance(table, dict):
        raise ConfigError(f"{where}: expected a table")
    for key in sorted(table):
        if key not in allowed:
            raise ConfigError(f"{where}: unknown key {key!r}")
    return table


def _build_sql(table: dict | None) -> SqlDetectors:
    given = _known_keys(table, SQL_KEYS, "[sql]")
    raw = {key: (_string_list(given[key], f"[sql] {key}") if key in given else dict(DEFAULT_SQL)[key]) for key in SQL_KEYS}
    return SqlDetectors(
        create=tuple(_compile(p, "[sql] create", groups=1) for p in raw["create"]),
        use=_templates(raw["use"], "[sql] use"),
        write=_templates(raw["write"], "[sql] write"),
        write_any=tuple(_compile(p, "[sql] write_any") for p in raw["write_any"]),
        is_default=not given,
    )


def _build_io(table: dict | None) -> tuple[tuple[str, tuple[str, ...]], ...]:
    given = _known_keys(table, IO_KINDS, "[io]")
    out = []
    for kind, default in DEFAULT_IO:
        entries = _string_list(given[kind], f"[io] {kind}") if kind in given else default
        for entry in entries:
            if not _DOTTED.match(entry):
                raise ConfigError(f"[io] {kind}: {entry!r} is not a dotted import name")
        out.append((kind, entries))
    return tuple(out)


def _build_decorators(table: dict | None) -> tuple[str, ...]:
    given = _known_keys(table, ("decorators",), "[routes]")
    names = _string_list(given["decorators"], "[routes] decorators") if "decorators" in given else DEFAULT_DECORATORS
    for name in names:
        if not name.isidentifier():
            raise ConfigError(f"[routes] decorators: {name!r} is not a valid decorator name")
    return names


def load_config(start: Path, explicit: Path | None = None, source: str = "worktree") -> Config:
    start = start.resolve()
    if explicit is not None:
        config_file: Path | None = explicit.resolve()
        if not config_file.is_file():
            raise ConfigError(f"config file not found: {explicit}")
        top = gitio.top_level(start) if gitio.in_work_tree(start) else None
        if top is not None and top not in config_file.parents:
            raise ConfigError(f"config file {explicit} is outside the repository")
        base = config_file.parent
    else:
        config_file, base = _locate(start, source)

    table: dict = {}
    project_name: str | None = None
    where = "config"
    untracked = False
    if config_file is not None:
        rel = config_file.name
        raw = read_file(base, rel, source)
        if raw is None:
            raise ConfigError(f"{rel} is not present in the {source}")
        try:
            data = tomllib.loads(raw.decode("utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            raise ConfigError(f"{rel}: {exc}") from exc
        if rel == "pyproject.toml":
            tool, project = data.get("tool", {}), data.get("project", {})
            if not isinstance(tool, dict):
                raise ConfigError(f"{rel}: [tool] must be a table")
            if not isinstance(project, dict):
                raise ConfigError(f"{rel}: [project] must be a table")
            table = tool.get("indextool", {})
            where = "[tool.indextool]"
            name = project.get("name")
            project_name = name if isinstance(name, str) else None
        else:
            table, where = data, rel
        if gitio.in_work_tree(base):
            untracked = not gitio.is_tracked(base, rel)
    if project_name is None:
        project_name = _project_name(base, source)

    table = _known_keys(table, _TOP_KEYS, where)
    title = table.get("title", "")
    if not isinstance(title, str):
        raise ConfigError("title: expected a string")
    roots = tuple(_rel_path(r, "roots", allow_dot=True) for r in _string_list(table.get("roots", ["."]), "roots"))
    if not roots:
        raise ConfigError("roots: at least one root is required")
    _check_roots(roots)
    architecture = _rel_path(table.get("architecture", DEFAULT_ARCHITECTURE), "architecture", allow_dot=False)
    index = _rel_path(table.get("index", DEFAULT_INDEX), "index", allow_dot=False)
    if architecture == index:
        raise ConfigError("architecture and index must be different files")
    discovery = table.get("discovery", "auto")
    if discovery not in ("auto", "git", "walk"):
        raise ConfigError("discovery: expected one of 'auto', 'git', 'walk'")

    return Config(
        base=base,
        config_file=config_file,
        config_untracked=untracked,
        title=title or (project_name or ""),
        roots=roots,
        exclude=_globs(_string_list(table.get("exclude", []), "exclude"), "exclude"),
        tests=_globs(_string_list(table.get("tests", list(DEFAULT_TESTS)), "tests"), "tests"),
        architecture=architecture,
        index=index,
        discovery=discovery,
        route_decorators=_build_decorators(table.get("routes")),
        io=_build_io(table.get("io")),
        sql=_build_sql(table.get("sql")),
    )
