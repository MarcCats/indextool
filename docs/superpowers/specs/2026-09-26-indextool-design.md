# indextool: design

Date: 2026-09-26. Status: draft for review. Path: architectural (new project), so this spec is followed by an implementation plan.

## 1. Purpose and scope

### 1.1 What is being built

An open-source, stdlib-only Python tool that turns a Python repository into a committed, machine-verified architecture description for coding agents and people:

```
repository -> deterministic parser -> architecture map + module index
           -> committed to git -> pointer in CLAUDE.md / AGENTS.md -> coding agent
CI: regenerate in memory -> byte comparison -> stale? fail : pass
```

The core property: **the architecture artifact cannot silently diverge from the repository.** Everything else is in service of it. The tool does not claim a new category. The claim is a specific lightweight pattern: derive from source with stdlib code, commit the result, fail CI when it is stale, and point the agent to it instead of injecting it.

### 1.2 Sources

- The business case PDF ("Generated Architecture Maps: Business Case for Any Team", 2026-09-26) and the note pasted with the request ("architecture-as-code for agents, with CI-enforced freshness").
- The reference implementation: a private, stdlib-only Python script of about 1,500 lines with a hook-safe refresh helper, its tests, and a hand-written rule document. Its location is deliberately not recorded in this repository (section 1.6). The rule document's sections on vocabulary and computation are the normative description of what is computed, except where section 6.2 lists a delta.

### 1.3 Success criteria

1. A stranger can install the tool, run `init` on a Python repository, commit, and have a working CI freshness check in under 15 minutes.
2. A committed map that differs from what `generate` would write now makes `verify` exit non-zero, in CI and in pre-commit, for every kind of drift the contract in section 4 covers.
3. Output is byte-identical for the same inputs under the conditions listed in section 4.
4. Zero runtime dependencies; nothing to install beyond Python and the tool.
5. Generalizing the reference loses nothing: with a parity config, the tool reproduces the reference's output on a private reference repository, apart from a fixed list of intended differences (section 8.2).

### 1.4 Assumptions made without being told

- v1 parses Python only. The pattern is language-neutral; other languages are later work.
- No model calls, no service, no vector store.
- The README will not advertise the business case's headline token-saving figure (section 9.3).

### 1.5 Explicitly not in v1

Nameplates, the tag file, `--check`, baselines and locks (declared-layer enforcement); the `impact`, `symbols` and `package` query modes and the token-budgeted schematic; a JSON artifact; non-Python languages; an MCP server; a composite GitHub Action; CI templates other than GitHub Actions; a measurement harness. The next candidates, in order: a JSON artifact (cheap, because facts and rendering are separate) and declared-layer enforcement (the PDF's follow-on).

### 1.6 Public-content rule

This repository is intended to be published, and it must contain nothing specific to the private reference project: no project, company or product names, no paths, no module, table or route names, no configuration values, no fixtures, and no generated output derived from it. Consequences:

- Every fixture, example config and golden is synthetic or produced from this tool's own source. Ported tests are re-derived with invented names, never copied.
- The parity run (section 8.2, gate 2) happens outside the repository. Its config, reference outputs and diffs are never committed, and release notes name no project.
- Notes that must name the reference (its location, its rule document, its trial harness) live outside the repository.
- Defaults are generic: the IO lists hold widely used libraries only, and no default names a folder or file of the reference project.
- Guard: a local-only pre-commit hook, installed in the unversioned `.git/hooks` before any source is written, refuses a commit whose staged diff contains a term from a list kept outside the repository. Public CI cannot run it, because publishing the list would publish the names.

## 2. Reference implementation: what carries over, what changes

Carried over: the scan (one `ast` parse per file), the import graph, library/standalone classification, depth, import cycles (iterative Tarjan), look-alike names, table/writer/route facts from string literals and decorators, the two rendered files, the atomic silent `refresh`, and the byte-comparing `verify`. Tests that pin those rules are re-derived, not copied: each fixture is rewritten with invented module, table and route names (section 1.6). Nameplate and check tests stay behind.

Project-specific in the reference and therefore generalized: a hardcoded list of third-party libraries chosen for one project; a hardcoded excluded-directory name; a hardcoded default root folder; route detection limited to one decorator name; project-named output files; the folder name printed in the map title; and import resolution that strips a leading root-folder-name prefix.

Two hazards in the reference that the "cannot silently diverge" property forbids, because the reference never verified against a clean checkout:

1. `scan()` walks the disk with `os.walk`, so an untracked scratch file changes the local map but not CI's.
2. The map's first line prints the root folder's name, so the same commit in a differently named folder produces different bytes.

Both are fixed by the contract in section 4.

## 3. Architecture

### 3.1 Commands

| Command | Behavior |
|---|---|
| `indextool generate` | Scan, then write the architecture map and the index to the configured paths (atomic, UTF-8, LF). |
| `indextool verify` | Scan in memory and compare with the committed files. Exit 0 current, 1 drift, 2 misconfiguration. Also checks the managed pointer blocks (section 7.4). |
| `indextool refresh` | Hook-safe `generate`: prints nothing to stdout, always exits 0, reports problems as one line on stderr, writes only when a file's content changed, writes atomically, never replaces a good file with a worse one. |
| `indextool init` | Idempotent setup (section 7.1). Re-running it also updates managed pointer blocks after a config change. |

Global options: `--config PATH` and, on `generate`, `verify` and `refresh`, `--source worktree|index` (section 4, rule 2). `init` takes `--dry-run` and `--hook shared|local|none`.

### 3.2 Package layout (`src/indextool/`, stdlib only, Python 3.11+)

| Module | Responsibility |
|---|---|
| `scan` | Discover files, decode, parse each once with `ast`, return module records (imports, first docstring line, public class names, `UPPER_CASE` constants bound to literals, string literals, route decorators). |
| `graph` | Edges, library or standalone, depth, cycles, look-alike names. Pure functions of the module records. |
| `facts` | Tables, writers, routes and IO rating from string literals, decorators and imports, using the configured detectors. |
| `render` | Repo and facts in, two strings out. No I/O. |
| `output` | Atomic write, normalized compare, diff summary. |
| `config` | Locate and load `indextool.toml` or `[tool.indextool]`, validate, normalize. |
| `init` | Plan and apply the setup steps and hold the templates (pointer, workflow, hook entry). |
| `cli` | Argument parsing and exit codes only. |

### 3.3 Data flow

`scan -> graph + facts -> render -> write | compare`. Everything up to `render` is a pure function of the discovered file contents and the config. One scan feeds both output files.

## 4. Determinism contract

**Contract:** the output is a pure function of (the contents of the discovered files, the config, the tool's `major.minor`, the Python `major.minor`). Working directory, folder name, clone location, time, git history, hash seed, OS and file mtimes must not change a byte. Git is used only to decide which files exist and, in index mode, to supply their content. It is never used for history, dates, hashes or churn.

1. **Discovery.**
   - In a git work tree (`discovery = "auto"` or `"git"`): run `git ls-files -z -s` scoped to the base directory (the directory containing the active config, else the git top level). Keep entries of stage 0 with mode 100644 or 100755 whose path ends in `.py`. Skip gitlinks (160000) and symlinks (120000) by mode, which is identical on every OS. Any entry with stage other than 0 is a misconfiguration error (exit 2). In worktree mode, tracked paths missing on disk are skipped.
   - Outside git, or with `discovery = "walk"`: a walk with each directory listing sorted, skipping symlinks, and silently skipping `.git`, `__pycache__`, `venv`, `.venv`, `node_modules`, `.idea`, `site-packages`, `.tox`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`. `--source index` is an error in walk mode.
   - Configured `exclude` patterns apply in both modes. The number of files they removed is printed in the map.
   - Two paths that are equal after case-folding are an error (exit 2). It is computed from the path list, so Linux, macOS and Windows agree.
   - Untracked files are never part of the map in git mode.
2. **Source.** `--source worktree` (default) reads content from disk. `--source index` reads blobs through one `git cat-file --batch`. `--source` governs the config file and the managed pointer blocks as well as the `.py` files. In worktree mode `verify` warns on stderr when any tracked `.py` file, the config, or a pointer file has unstaged changes ("CI will see the committed version; use `--source index` to check what you would commit"). CI is unaffected, because working tree and commit are identical there. The pre-commit hook written for users uses `--source index`.
3. **Decoding.** Read bytes; `tokenize.detect_encoding` (PEP 263 cookie and BOM, default UTF-8); decode with `errors="replace"`, never the locale. A bad cookie or a BOM/cookie mismatch (a `SyntaxError` from the detector) makes the file an unparsable module, counted, never a crash. `\r\n` and lone `\r` are normalized to `\n` before anything else; text is split with `split("\n")` only, and `str.splitlines()` is not used anywhere in the package. `surrogateescape` is not used, because lone surrogates cannot be encoded when a docstring title is written to the map.
4. **Names.** The map title comes from config `title`, else `[project].name` in the base directory's `pyproject.toml`, else the fixed string "Architecture map". The folder name is never printed. Module keys are paths relative to the configured `roots`, without `.py`, `/` replaced by `.`, `pkg/__init__.py` becoming `pkg`. Absolute imports resolve against modules under the roots. Two files producing the same key is an error (exit 2). Roots that are equal, or where one contains the other, are an error.
5. **Python.** Minimum 3.11. `ast` rejects syntax newer than the running interpreter, so a file can parse locally and fail in CI. An unparsable file stays in the map as a module with no edges, title or routes, and its raw text feeds the table rules, as in the reference. The map states the count of unparsable files. The contract is **byte-identical for the same Python major.minor.** Whether output is also identical across minors for code that parses on all of them is tested (section 8.1) but not promised until the evidence exists; if the portable cross-version golden diverges, the Python minor goes into the header.
6. **Order and size.** Every list has a total order with the name as the last tie-break, using code-point comparison and never the locale. Paths use `/`. Every list of lines has a cap and ends with a "(+N more)" line; every enumeration inside one line (names per depth, cycle members, writers and readers per table, route files) has a cap and ends with ", +N", which is the reference's form. Output holds no dates, hashes or run counts.
7. **Header.** The first lines of both outputs carry `indextool major.minor`. Patch releases are output-neutral by policy, enforced by CI (section 8.1). A minor bump may change output, and the changelog says so.
8. **Bytes.** Output is UTF-8 with LF. `verify` normalizes CRLF in the committed file before comparing, because Windows `autocrlf` rewrites it. `init` adds `<path> text eol=lf` lines to `.gitattributes` for both generated files.
9. **Failure output.** `verify` failure messages print the running Python and tool versions. When any file failed to parse, the message adds "N files failed to parse under Python X.Y; check that CI and local Python versions match."

## 5. Configuration

### 5.1 Location and validation

1. `indextool.toml` in the base directory, with top-level keys (its tables are `[routes]`, `[io]`, `[sql]`).
2. Otherwise `[tool.indextool]` in `pyproject.toml` (same keys, nested under that table).
3. Otherwise defaults.

The base directory is found by searching upward from the working directory for a config; the search stops at the git top level. With no config, the base directory is the git top level, or the working directory when there is no git repository (walk mode). `--config PATH` overrides. All relative paths in config (roots, outputs, glob anchors) resolve against the base directory, never the working directory, so `cd` then `verify` gives the same bytes. Discovery is scoped to the base directory's subtree, so a monorepo can hold one config per sub-project.

Validation is strict: unknown keys, invalid regexes, a missing `@TABLES@` placeholder, unknown keys under `[io]`, a `!` negation in a glob, and nested or duplicate roots are all errors (exit 2) that name the key. In git mode the active config file must be tracked (present in `git ls-files`) and inside the repository; otherwise `verify` exits 2 naming it, and `generate` warns. `refresh` only warns, on stderr.

### 5.2 Schema and defaults

```toml
title        = "Acme platform"              # else project.name, else "Architecture map"
roots        = ["src"]                      # else ["."]; init writes the detected value
exclude      = ["legacy/", "**/generated/*"]   # counted in the map
tests        = ["test_*.py", "*_test.py", "tests/", "test/"]
architecture = "docs/architecture.md"
index        = "docs/architecture.index.txt"
discovery    = "auto"                       # auto | git | walk

[routes]
decorators = ["route", "get", "post", "put", "patch", "delete", "head", "options", "websocket", "api_route"]

[io]                                        # dotted import prefix -> rating part; the three keys are the whole vocabulary
db      = ["sqlite3", "sqlalchemy", "psycopg", "psycopg2", "asyncpg", "pymysql", "duckdb"]
network = ["requests", "urllib.request", "urllib3", "aiohttp", "httpx"]
http    = ["flask", "fastapi", "starlette"]

[sql]                                       # matched against string literals only, re.IGNORECASE
create    = ['CREATE\s+(?:VIRTUAL\s+)?TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|AS\b|USING\b)']
use       = ['\b(?:FROM|JOIN|INTO|UPDATE|TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+(@TABLES@)\b']
write     = ['\b(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|ALTER\s+TABLE|DROP\s+TABLE|CREATE\s+(?:VIRTUAL\s+)?TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+(@TABLES@)\b']
write_any = ['\b(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|REPLACE\s+INTO|UPDATE\s+[\w.\"`\[\]]+\s+SET|DELETE\s+FROM|CREATE\s+(?:TEMP(?:ORARY)?\s+)?(?:TABLE|INDEX|VIEW)|DROP\s+(?:TABLE|INDEX|VIEW)|ALTER\s+TABLE)\b']
```

These four defaults are the reference implementation's patterns, with two changes, both to accept `CREATE VIRTUAL TABLE ... USING`: in `create`, and in the `CREATE TABLE` verb of `write`. `create` has one capture group, the table name. `use` and `write` contain `@TABLES@` inside one capture group. `write_any` has no placeholder and drives the `db-rw` rating. `CREATE TEMP TABLE` is deliberately not counted by `create`, because a temporary table is session-scoped and not schema, and the provenance line says so. The `write` default keeps `CREATE TABLE`, which makes a script that only creates a table its "writer", as in the reference.

### 5.3 Detector semantics

Detectors are data, never plugins. Nothing executes user code. Decorators and imports come from the AST; regexes run only over string literals, never over docstrings.

- **Routes.** A function decorator counts when it is a call whose function is an attribute (`x.<name>`), `<name>` is in `decorators`, and its first positional argument is a string literal that starts with `/`. A literal alone does not exclude `@cache.delete("user")`; the leading slash does. Routes registered by `add_url_rule`, keyword-only paths, or empty-path router routes are not seen, and the provenance line says so.
- **IO.** An import statement yields the module name and, for `from m import n`, also `m.n`. An entry matches when a yielded name equals it or starts with it plus `.`. So `from urllib import request` is `urllib.request`, and `import urllib.parse` does not match `urllib.request`. A module's rating is built from `db` (`db-r`, or `db-rw` when its string literals match `write_any` or the code calls `.to_sql`), `network` and `http`, joined with `+`. No evidence gives an empty rating, never `none`, because IO reached through another module's helper cannot be seen.
- **SQL.** All patterns use exactly the flag set `re.IGNORECASE`. `@TABLES@` is replaced textually (not with `str.format`, so `{2}` quantifiers stay legal) by the created table names, each `re.escape`d, sorted longest first with ties by name, joined with `|`.
- **Tests.** A module is a test module when a `tests` pattern matches its path. Test modules are counted in the module total and appear nowhere else.

### 5.4 Glob semantics

`exclude` and `tests` are the only users of globs, matched by a matcher written for this tool, because `fnmatch` has no `**` and `PurePath.match` is not recursive before Python 3.13. The rules are gitignore's, without negation: a trailing `/` means a directory; a leading `/` anchors to the base directory; `**` spans directories; otherwise `*` and `?` do not cross `/`; a pattern with no `/` other than a trailing one matches at any depth; `[...]` is a character class; matching is case-sensitive; patterns are normalized to `/` before use.

## 6. The derived map

### 6.1 Computation (condensed from the reference rule document, sections 3 to 5)

| Term | Rule |
|---|---|
| Module | A discovered `.py` file. |
| Test module | Matched by a `tests` pattern. |
| Edge | Module A imports repo module B anywhere in A: top level, inside a function, inside `try`/`except`. Function-level imports are edges. `from m import n` targets `m.n` when that is a module, else `m`; relative imports resolve against the importing module's package. Anything that resolves to no repo module, and self-imports, are dropped. |
| Importer | A non-test module with an edge to this one; counts modules, not statements. |
| Library / standalone | Library: at least one non-test importer. Standalone: none. Tests are ignored on both sides. |
| Depth | 0 when the module imports no other repo module, else 1 plus the deepest module it imports; each import cycle collapses into one node. |
| Cycle | A strongly connected component of two or more non-test modules. |
| Table | A name matched by `create`. |
| Writer | A non-test module whose string literals match `write` for that table. |
| Route | Per section 5.3. |
| Look-alike | A public top-level class name or top-level `UPPER_CASE` name bound to a dict, list, tuple or set literal, defined in two or more library modules. |

Caps: packages 25; most depended-on modules 25; tables 25; route groups 25 (first three path segments); route files 25; cycles 10 (largest first, 8 names each); look-alike names 20; modules named per depth 6; writers named per table 4; readers named per table 4. Every capped list of lines ends with a "(+N more)" line, and every capped enumeration inside a line (modules named per depth, cycle members, writers, readers, route files) ends with ", +N". The index never truncates.

### 6.2 Output layout and deltas from the reference

Architecture map sections, in order: numbers, packages, dependency layers, import cycles, most depended-on modules, HTTP surface, database, same name in different modules, what this map cannot say. The index is one header line and then one line per non-test module, sorted by key: `key | first docstring line (90 chars, "-" if none) | lib or standalone + io | tables: a, b* | routes N`, where `*` marks a table the module writes. A title is cut to its width and then stripped of trailing whitespace, in the map and in the index; in the index a `|` in a title is written as `/`, so that the field separator is unambiguous.

Deltas from the reference, each intentional:

1. Title and header per section 4, rules 4 and 7; no folder name. The map's first line is `# Architecture map` (or `# Architecture map: <title>` when a title is set). The text `indextool <major.minor>` appears within the map's first three lines and on the index's first line; the rest of the header wording is pinned by the goldens.
2. Keys and import resolution relative to `roots`; the reference's stripping of a leading root-folder-name prefix is gone.
3. Detectors from config (section 5.3), with generic defaults.
4. Route rule requires a literal starting with `/`.
5. IO matching by dotted prefix; default `network` uses `urllib.request`.
6. `create` and the `CREATE TABLE` verb in `write` accept `VIRTUAL ... USING`.
7. Each detector-based section states its detector in one line, prints "none found by this detector" instead of vanishing, and "what this map cannot say" is generated from the active config.
8. The excluded-file count and the unparsable-file count are printed.
9. The unused `lazy` field is not carried over.
10. The package list and the route-file enumeration are capped at 25 (the packages list ends with a "(+N more packages)" line, the route files with ", +N"), and the most-depended-on list gets a "(+N more)" line, so that every list obeys section 4, rule 6. The reference left the first two uncapped and gave the third no such line; outputs with fewer than 25 entries are unaffected.

## 7. Delivery

### 7.1 `init`

`init` edits only what the standard library can edit safely: new files, JSON merges, marker-delimited text blocks and single-line appends. Anything else (YAML) is printed as a snippet. It builds the whole plan before writing, is idempotent, supports `--dry-run`, and reports created, updated, unchanged or skipped per item. It ends by running `generate`, so the pointer targets exist and CI passes on the first push, and by listing what to `git add`.

| Target | How |
|---|---|
| `indextool.toml` | New file, never overwritten. Records the detected `roots`, a title and the output paths. |
| Pointer | Managed block in each instruction file (7.2). |
| SessionStart hook | JSON merge into `.claude/settings.json`; adds an entry only when none already runs `indextool refresh`. `--hook local` writes `.claude/settings.local.json` and adds it to `.gitignore` (Claude Code only auto-ignores the file when it creates it). `--hook none` skips. An unparsable settings file is left alone with a message. Default is `shared`. |
| CI | New `.github/workflows/indextool.yml` (7.3). |
| `.gitattributes` | One-line appends (section 4, rule 8). |
| pre-commit | A printed snippet using the tool repository's `.pre-commit-hooks.yaml`, whose entry is `indextool verify --source index`. |

### 7.2 Pointer

Placement (verified against the Claude Code memory docs: with both `AGENTS.md` and `CLAUDE.md` present, Claude reads only `CLAUDE.md` unless it imports `AGENTS.md`):

- If `CLAUDE.md` contains an `@AGENTS.md` import, write the block once, into `AGENTS.md`.
- Otherwise write it into every existing file among `CLAUDE.md`, `.claude/CLAUDE.md` and `AGENTS.md`.
- If none exists, create `AGENTS.md`.

Text (paths come from config; no derived numbers, because a figure in hand-written text goes stale):

```
<!-- indextool:begin (managed: change indextool.toml, not this block) -->
- `docs/architecture.md` - generated map of layout, dependency layers, import cycles, routes, tables and what writes them, and the most-used modules. Read it whole for whole-repo questions. Regenerated from code, never edited by hand.
- `docs/architecture.index.txt` - generated one-line-per-module index (title, library or standalone, io, tables, routes). Search it with grep for where something lives or which modules read or write a table. It is large: do not read it whole.
- Regenerate with `indextool generate`. CI runs `indextool verify` and fails when either file is stale.
<!-- indextool:end -->
```

This keeps the structure of the reference pointer, whose wording the business case's trial found to matter (rewording alone changed the measured saving), and replaces the reference pointer's token figure with "It is large". That wording is untested; acceptance gate 5 (section 8.2) decides it.

### 7.3 Hook and CI

Hook entry: `{"type": "command", "command": "indextool refresh", "timeout": 30}`, the shape of a working reference `settings.json`. No path is needed because config discovery searches upward.

CI workflow: checkout, `setup-python` pinned to the version that ran `init`, `pip install "indextool~=<major.minor>.0"`, `indextool verify`. The compatible-release pin means a patch release cannot change output. For other CI systems `init` prints the same two commands.

### 7.4 `verify` details

Exit 0: current. Exit 1: drift; prints at most 12 changed lines, "(+N more changed lines)", and the regenerate command; a missing output file says how to write it. Exit 2: misconfiguration (invalid or untracked config, key or case-fold collision, unmerged paths, a pointer block that differs from what the config renders). Each managed pointer block must equal what the current config renders, which catches a moved output path or a hand edit; files without markers are not checked, and `verify` notes that once on stderr without changing the exit code. After a config change, `indextool init` updates the blocks.

## 8. Testing and acceptance

### 8.1 Test layers

| Layer | What it pins |
|---|---|
| Unit | Per module, on synthetic fixtures built in `tmp_path` with a real `git init`; tests that pin a rule are re-derived from the reference's, with synthetic fixtures. |
| Determinism | Conditions below. |
| Golden and bump gate | Goldens carry the header; PR CI fails when golden bytes change while the header's `major.minor` is unchanged against the base branch; the release job asserts goldens of `vX.Y.Z` (Z above 0) are byte-identical to `vX.Y.0`. |
| CLI integration | Subprocess runs: exit codes 0, 1, 2; `refresh` silent and exit 0 with a broken config; `init` twice leaves everything unchanged; `--dry-run` writes nothing; JSON merge keeps foreign keys; marker replacement keeps surrounding text; pointer placement for `CLAUDE.md` only, `AGENTS.md` only, both, the import case, and neither; `generate` then `verify` passes; any single-file mutation makes `verify` fail. |
| Contract | The package imports only stdlib (AST scan against `sys.stdlib_module_names`); `dependencies = []`; no `splitlines(` in the package source. |
| Matrix | ubuntu, windows, macos, each with Python 3.11 to 3.14: per-version self-consistency (generate twice, compare); a portable-fixture golden compared across all versions; a PEP 701 f-string fixture asserted per version (unparsable and counted on 3.11, parsed on 3.12 and later). |
| Self-hosting | The tool's own repository commits its own map; its CI runs `verify` on it. |

Determinism conditions: the same fixture generated twice; different `PYTHONHASHSEED`; two differently named copies; different working directories; CRLF versus LF sources; shuffled discovery order; `LC_ALL` and `PYTHONUTF8` variants; a latin-1-cookie fixture; an extra untracked file changes nothing; a file under a default exclude changes nothing; a file under a configured exclude changes only the count line; a rename changes the output; a one-import mutation changes the output; a case-fold collision on a plain path list; a clean tree gives identical worktree and index output while a dirty tree differs and the warning fires; an untracked config makes `verify` fail naming it; a `--config` path outside the repository is an error; a docstring with a form feed and U+2028 keeps one line convention.

### 8.2 Acceptance gates for 1.0

1. The determinism suite and the matrix are green.
2. **Parity on a private reference repository** (run privately, since that code cannot be in public CI). `scripts/parity.py` is generic: it takes two output files and classifies each differing line against the allowed categories. It compares fresh reference-generator output with `indextool` run under a parity config that reproduces the reference's settings (its source folder as `roots`, its single route decorator, its IO libraries including a top-level `urllib`). The baseline is regenerated with the reference generator, never read from committed generated files, which can predate the generator's last edit. Every differing line must fall in a fixed list of allowed categories: title, intro, header, provenance lines, counts of excluded and unparsable files, and the configured top-level `urllib` entry. The parity config, the reference outputs and the diff stay outside this repository; the release notes say only that parity was verified on a private repository of several hundred modules.
3. **Cold start on three public repositories** with different layouts (a `src/` layout, a flat layout, a monorepo with two configs): install, `init`, commit, CI `verify` green; then mutate an import and see it fail. Stopwatch target: under 15 minutes.
4. **Speed:** one scan feeds both files. `refresh` time on the private reference repository is reported (as a time only) and leaves comfortable margin under the 30 second hook timeout.
5. **Pointer wording:** one trial on the private reference repository, comparing the reference wording (with its figure) against the number-free wording, using the existing private trial harness. The winner ships; the trial's data stays outside this repository.

## 9. Repository, release, documentation

### 9.1 Repository

A fresh repository. Layout: `src/indextool/`, `tests/`, `docs/`, `.pre-commit-hooks.yaml`, and a PEP 621 `pyproject.toml` with `requires-python >= 3.11` and no runtime dependencies. Test fixtures, example configs, goldens and the self-hosted map are synthetic or generated from this tool's own source (section 1.6).

### 9.2 Versioning and release

Semver with a stricter meaning for minor: an output-affecting change bumps minor and adds an "Output changes" line to the changelog; a patch release is output-neutral; a major release breaks the CLI or config schema. Tagging triggers PyPI trusted publishing over OIDC (no stored token). License: MIT.

### 9.3 Documentation and README rules

- `docs/rules.md` is adapted from the reference rule document; each rule names the test that pins it, and a small CI script fails on a dangling test name.
- `docs/config.md` documents section 5.
- `docs/trial.md` is the PDF's two-afternoon method: decide the bar before running, and report both directions.
- README headline claim: only what CI enforces, that the committed map cannot silently diverge. It states up front that the tool is Python only, describes structure and not intent, and cannot see dynamic imports or routes and tables outside the detectors.
- The business case's token-saving figure is not in the headline. It appears at most once, under "Evidence", with its scope (one task type, one repository, a small number of sessions per arm; no claim about general savings, accuracy or compliance), and only if the trial write-up is published with it and has been checked to contain nothing project-specific. Otherwise it is omitted.
- "Related work" credits RIG, Aider's repo map, Tecture and similar tools, import-linter and Tach, and code-graph MCP servers, and states the claim as a specific lightweight pattern, not a new category.

## 10. Risks and open items

Risks, with mitigations already in the design:

- Detector defaults produce wrong facts on repositories unlike the reference. Mitigation: provenance lines, "none found by this detector", config-driven "cannot say" list.
- Hand-written documentation drifts. Mitigation: `docs/rules.md` cites pinning tests; pointer blocks are verified.
- Cross-minor AST differences (f-strings, new syntax). Mitigation: same-minor contract, matrix, PEP 701 fixture, version hint in failures.
- The shared SessionStart hook needs the tool on every teammate's machine; a missing executable gives one non-blocking error line at session start. `--hook local` is the opt-in alternative.
- The index grows with the repository and is never truncated. Mitigation: the pointer says to grep it, and it is not offered as a whole-file read.

Open items, each with the point at which it is resolved:

1. Whether the portable-fixture golden diverges across Python minors (matrix result); if so, add the Python minor to the header.
2. The pointer wording trial (gate 5).
3. Each prior-art description in the README is checked against its source before publishing; the PDF's descriptions are not yet verified.
4. `indextool` was free on PyPI on 2026-09-26 (not a reservation); the GitHub repository name has not been checked.
5. Confirmation that code derived from the private repository may be open-sourced. (The MIT `LICENSE` copyright holder is Marc Cats, decided 2026-09-26.)
6. Whether `write_any` reproduces the reference's `db-rw` ratings exactly is settled by the parity gate.

## 11. Decision log

| Decision | Choice | Reason |
|---|---|---|
| v1 scope | Core loop only | Matches the pitch; enforcement is a separate later step in the PDF. |
| Artifacts | `architecture.md` plus `index.txt` | The user's call: the index was unused in overview tasks but is a valuable grep lookup. JSON later. |
| Packaging | Installable stdlib-only package, Python 3.11+ | Testable, upgradeable, config in TOML. |
| Committed vs untracked | Committed and CI-verified | Required for the core property; the hook is a convenience. |
| File discovery | Tracked files only in git mode | Describes what CI will see. |
| Detectors | Data in config, no plugins | Keeps output a pure function of files plus config. |
| Config as input | Must be tracked; governed by `--source` | Otherwise local and CI silently differ. |
| Header version | `major.minor` only | Patch releases must not force regeneration. |
| Pointer numbers | None | Hand-written numbers go stale. |
| Hook default | `shared` | Mirrors the reference; `local` is opt-in. |
| Name, license | `indextool`, MIT | User's choice. |
| Public content | Nothing specific to the private reference project; synthetic fixtures and configs; parity run and its config kept outside the repository | User's instruction (section 1.6). |
