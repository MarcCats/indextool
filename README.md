# indextool

The committed architecture map of a Python repository cannot silently diverge from the code: CI runs `indextool verify`,
which fails the build the moment it does.

indextool reads your source with the standard library, writes an architecture map and a one-line-per-module index,
and gives your coding agent a short pointer to them. There is no service, no model call and no dependency beyond
Python's standard library. Python only, and it describes structure, not intent: imports, dependency layers, cycles,
routes, tables and their writers, look-alike names. Routes and tables are found only where a configured detector
matches; nothing outside the detectors is seen. It cannot see why a module exists, and it cannot see imports made
through `importlib`.

```
your repository -> indextool generate -> docs/architecture.md, docs/architecture.index.txt
                -> committed -> pointer in AGENTS.md or CLAUDE.md -> your coding agent
CI: indextool verify -> regenerate in memory, compare with the committed files -> stale? fail : pass
```

## Quickstart

```
pip install indextool
indextool init
git add -A && git commit -m "Adopt indextool"
```

`init` writes `indextool.toml`, a managed pointer block in your agent instruction files, a Claude Code SessionStart
hook, a GitHub Actions workflow and `.gitattributes` lines, then generates the two files and prints the `git add` line
for what it wrote. It never overwrites an existing config or workflow, and `--dry-run` shows what it would do without
writing anything.

The pointer block goes into `AGENTS.md`, which `init` creates when no instruction file exists. When `AGENTS.md` exists
and `CLAUDE.md` or `.claude/CLAUDE.md` imports it (a line reading `@AGENTS.md`), the block goes only into `AGENTS.md`.
In every other case it goes into every existing file among `CLAUDE.md`, `.claude/CLAUDE.md` and `AGENTS.md`, so an
import of an `AGENTS.md` that does not exist redirects nothing: the block goes into the importing file. Running `init`
again refreshes the managed blocks it finds, keeps CRLF files CRLF, writes through symlinks and prints paths relative
to your current directory. Markers inside fenced code and prose mentions of them are ignored; unpaired or duplicate
markers are refused, and `verify` exits 2 on them.

## Commands

| Command | What it does |
|---|---|
| `indextool generate` | Write the map and the index. |
| `indextool verify` | Exit 0 when both committed files are current, 1 on drift, 2 on misconfiguration. |
| `indextool refresh` | Silent, fail-open regeneration for a session-start hook. |
| `indextool init` | One-time setup, safe to re-run. |

`--config PATH` names the config file. `--source index` reads staged content instead of the working tree; use it in
pre-commit so the check matches what you are about to commit (`init` prints a snippet). In the default worktree mode,
`verify` warns when a tracked Python file, the config or a pointer file has unstaged changes, because CI will see the
committed version.

## Determinism

The output is a pure function of the files it reads (in a git work tree, the tracked ones), the config, the tool's
`major.minor` and the Python `major.minor`. Folder name, working directory, time, hash seed, locale and line endings do
not change a byte. In a git work tree, files that git does not track are never part of the map. A file that cannot be
decoded or parsed is counted, not skipped, and its raw text, comments included, still feeds the table detectors. Because
syntax trees differ between Python versions, run `verify` in CI on the same Python `major.minor` that generated the
files.

## Configuration

See [docs/config.md](docs/config.md). Detectors (route decorators, SQL patterns, IO import lists) are data in the
config; nothing executes your code.

## What is computed

See [docs/rules.md](docs/rules.md); every rule names the test that pins it.

## Measure it yourself

See [docs/trial.md](docs/trial.md).

## Related work

indextool is a specific lightweight pattern, not a new category: derive a small description from source with
standard-library code, commit it, fail CI when it is stale, and point the agent to it instead of injecting it. Other
projects cover parts of that ground; each description below follows the project's own page.

- The [Repository Intelligence Graph](https://arxiv.org/abs/2601.10112) paper describes a deterministic architectural
  map for LLM code assistants, extracted from build and test artifacts.
- [Aider's repository map](https://aider.chat/docs/repomap.html) is a concise map of a git repository, ranked with a
  graph algorithm, that Aider gives its model as context.
- [Tecture](https://github.com/tecture-io/tecture) is an architecture documentation format, structured JSON and
  Markdown, that a coding agent writes and maintains; a bundled evidence script checks its node paths and declared edges
  against the code.
- [import-linter](https://github.com/seddonym/import-linter) imposes constraints on the imports between Python
  modules, [Tach](https://github.com/gauge-sh/tach) enforces dependencies and interfaces in Python code, and
  [dependency-cruiser](https://github.com/sverweij/dependency-cruiser) validates and visualises dependencies against
  your rules for JavaScript and TypeScript.
- [RepoMap](https://github.com/Knowledge-Forge-AI/repo-map) builds a deterministic knowledge graph of a repository, and
  [code-review-graph](https://github.com/tirth8205/code-review-graph) builds a structural map of the code; both serve
  it to AI assistants over MCP.

## License

MIT.
