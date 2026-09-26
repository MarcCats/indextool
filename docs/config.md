# Configuration

indextool looks for its configuration in each directory from the working directory upward to the git top level (outside
git, up to the filesystem root). In each directory it tries `indextool.toml` first, then the `[tool.indextool]` table of
`pyproject.toml`; the first directory that has either is the base directory. With no config at all, the defaults apply
and the base directory is the git top level, or the working directory outside git. `--config PATH` overrides the search;
inside a git repository the path must be inside it. Relative paths in the config resolve against the base directory,
never the working directory. Unknown keys, invalid regexes, nested roots and other mistakes are errors that name the key:
`generate`, `verify` and `init` exit 2, while `refresh`, which always fails open, reports the error on stderr and exits 0.

In git mode the config file must be tracked, or `verify` exits 2 naming it (`generate` and `refresh` only warn). Under
`--source index` the config is read from the index as well, so a config that was never staged is simply not found: the
defaults apply and nothing is reported. With `--config PATH` and `--source index` there is no such fallback: a config
file that was never staged is an error, `not present in the index` (exit 2).

In `pyproject.toml` the same keys are nested under `[tool.indextool]`.

## Top-level keys

| Key | Default | Meaning |
|---|---|---|
| `title` | `[project].name` of the base directory's `pyproject.toml`, else none | Shown as `# Architecture map: <title>`. Without a `title` the tool never uses the folder name. `init` writes a `title` into the config it creates (the project name, else the folder name), so the folder name is recorded once, in the committed file. |
| `roots` | `["."]` | Source roots. Module keys are paths under a root. Files outside every configured root are not part of the map, and are not counted as excluded: with `roots = ["src"]`, `scripts/` and `setup.py` are left out. Roots must not nest or repeat, so `"."` cannot be combined with another root. `init` writes `["src"]` when `src/` holds Python files. |
| `exclude` | `[]` | Glob patterns for files to leave out. When the effective list is not empty, the map prints how many files it removed; `exclude = []` prints nothing. |
| `tests` | `["test_*.py", "*_test.py", "tests/", "test/"]` | Glob patterns for test modules. |
| `architecture` | `"docs/architecture.md"` | Where the map is written. A relative path inside the repository. It must not name a source or config file (a path ending in `.py`, or `indextool.toml` or `pyproject.toml` in any directory and any case): every `generate` and `refresh` rewrites it. |
| `index` | `"docs/architecture.index.txt"` | Where the index is written. A relative path inside the repository, not the same file as `architecture`, and subject to the same rule about source and config files. |
| `discovery` | `"auto"` | `auto`: git when inside a work tree, else a directory walk. `git` and `walk` force one; `git` needs a work tree, and `walk` cannot be combined with `--source index`. |

## Glob patterns

`exclude` and `tests` use gitignore rules without negation: a trailing `/` means a directory; a leading `/` anchors to
the base directory; `**` spans directories; otherwise `*` and `?` do not cross `/`; a pattern with no other `/` matches
at any depth; `[...]` is a character class; matching is case-sensitive; backslashes are treated as `/`. `!`, comments
and empty patterns are errors.

## Detectors

Detectors are data. Nothing executes your code: decorators and imports come from the syntax tree, and regexes run only
over string literals, never over docstrings or comments. The one exception is a file that cannot be decoded or parsed:
its raw text, comments and docstrings included, is its only literal, so SQL-looking text in it can count as evidence for
tables, their users and writers. Such a file gets no routes and no IO rating, and the map counts it as "could not be
parsed".

```toml
[routes]
decorators = ["route", "get", "post", "put", "patch", "delete", "head", "options", "websocket", "api_route"]

[io]      # dotted import prefixes; the three keys are the whole vocabulary
db      = ["sqlite3", "sqlalchemy", "psycopg", "psycopg2", "asyncpg", "pymysql", "duckdb"]
network = ["requests", "urllib.request", "urllib3", "aiohttp", "httpx"]
http    = ["flask", "fastapi", "starlette"]

[sql]     # all patterns use re.IGNORECASE and nothing else
create    = ['CREATE\s+(?:VIRTUAL\s+)?TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|AS\b|USING\b)']
use       = ['\b(?:FROM|JOIN|INTO|UPDATE|TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+(@TABLES@)\b']
write     = ['\b(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|ALTER\s+TABLE|DROP\s+TABLE|CREATE\s+(?:VIRTUAL\s+)?TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+(@TABLES@)\b']
write_any = ['\b(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|REPLACE\s+INTO|UPDATE\s+[\w.\"`\[\]]+\s+SET|DELETE\s+FROM|CREATE\s+(?:TEMP(?:ORARY)?\s+)?(?:TABLE|INDEX|VIEW)|DROP\s+(?:TABLE|INDEX|VIEW)|ALTER\s+TABLE)\b']
```

Giving a key replaces that key's default entirely; keys you leave out keep their defaults.

- **Routes.** A function decorator counts when it is a call `x.<name>(...)` with `<name>` in `decorators` and a first
  positional argument that is a string literal starting with `/`. A literal alone would count `@cache.delete("user")`;
  the leading slash prevents that. `add_url_rule`, keyword-only paths and empty-path router routes are not seen.
- **IO.** An import statement yields the module name and, for `from m import n`, also `m.n`. An entry matches when a
  yielded name equals it or starts with it plus `.`, so `from urllib import request` is `urllib.request` and
  `import urllib.parse` does not match it. A module's rating is `db-r` or `db-rw` (write evidence is `.to_sql` or a
  `write_any` match), then `network`, then `http`, joined with `+`. No evidence gives an empty rating.
- **SQL.** `create` has exactly one capture group, the table name. `use` and `write` contain `@TABLES@` exactly once and
  have exactly one capture group, the table name; `@TABLES@` is replaced by the created names, each escaped, longest
  first. `write_any` has no placeholder. `CREATE TEMP TABLE` is deliberately not counted by `create`: a temporary table
  is session-scoped, not schema. In a file that cannot be parsed, `create`, `use` and `write` run over its whole raw
  text (see above).
