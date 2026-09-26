# indextool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `indextool`, a stdlib-only Python tool that derives an architecture map and a module index from a Python repository, commits them, and fails CI when they are stale.

**Architecture:** `scan -> graph + facts -> render -> write | compare`. Everything up to `render` is a pure function of the discovered file contents and the config. Four CLI commands (`generate`, `verify`, `refresh`, `init`) sit on top. Detectors (route decorators, SQL patterns, IO import lists) are data in config, never plugins.

**Tech Stack:** Python 3.11+ standard library only at runtime (`ast`, `tokenize`, `tomllib`, `re`, `subprocess`, `argparse`); `pytest` for development; `hatchling` as build backend; GitHub Actions for CI and PyPI trusted publishing.

**Spec:** `docs/superpowers/specs/2026-09-26-indextool-design.md` (approved 2026-09-26). Executors read the spec alongside this plan; where the plan adds a detail the spec is silent on, the plan says so.

## Global Constraints

Every task's requirements implicitly include these, copied from the spec.

- Python floor: `requires-python >= 3.11`; `dependencies = []`; the package imports only the standard library.
- Contract: the output is a pure function of (contents of the discovered files, the config, the tool's `major.minor`, the Python `major.minor`). Working directory, folder name, clone location, time, git history, hash seed, OS and file mtimes must not change a byte.
- Output is UTF-8 with LF. Sources are decoded with `tokenize.detect_encoding` and `errors="replace"`, never the locale; `\r\n` and lone `\r` are normalized to `\n`; text is split with `split("\n")` and `str.splitlines()` is not used anywhere in the package.
- Every list has a total order (name as last tie-break, code-point comparison), `/` paths, a cap, and a "(+N more)" line. No dates, hashes or run counts in output.
- Both outputs carry `indextool <major.minor>` (`indextool.FORMAT_VERSION`): within the map's first three lines and on the index's first line.
- Exit codes: 0 current or success, 1 drift, 2 misconfiguration.
- Git is used only to decide which files exist and, in index mode, to supply their content. Untracked files are never part of the map in git mode.
- Public-content rule (spec 1.6): nothing specific to the private reference project may appear in any file, fixture, golden, example or commit message. All fixtures use invented names (for example `shop`, `orders`, `ledger`, `billing`). The local guard hook installed in Task 1 enforces this.
- Package and command name `indextool`; license MIT with the copyright line `Copyright (c) 2026 Marc Cats`.
- Commit messages end with a `Co-Authored-By: <model> <noreply@anthropic.com>` trailer (pass it as a second `-m`) that names the model that actually authored the commit. The commands in this plan show `Claude Sonnet 5`; an implementer running on a different model substitutes its own name, and the controller states the exact line in each dispatch.
- Parity is private. `tests/test_parity.py` runs against the synthetic strings in that file only. The comparison against the private reference repository is a manual, local step of the release gate (Task 17, Step 2). Never add the reference's outputs, its parity config or any diff of them to this repository: not as goldens, fixtures, examples or documentation, however helpful that might look.
- Commands assume Git Bash on Windows and the virtualenv interpreter `.venv/Scripts/python`; on macOS or Linux use `.venv/bin/python`.

## Review Focus

Inputs the spec implies but that are easy to miss, most likely to bite first. Each has a test in the task named on the right.

1. A repository with no tracked `.py` files: `generate` writes a valid empty map, and `refresh` never overwrites a good map with an empty one (Tasks 10, 11).
2. Files that cannot be parsed: a syntax error, a nesting depth that exhausts the parser, a bad coding cookie, a BOM/cookie mismatch. Each is counted and never crashes a run (Tasks 4, 6).
3. A committed map that is missing, or that has CRLF line endings after a Windows checkout: `verify` says "does not exist" for the first and passes for the second (Task 11).
4. Non-ASCII paths, docstrings and identifiers (`café/naïve.py`): not quoted by git, written as UTF-8, and printable on a console that is not UTF-8 (Tasks 3, 6, 10).
5. Running from a subdirectory of the repository, and in a repository with no commits yet: config is found by searching upward, and staged files count (Tasks 4, 5, 11).

## File Structure

```
pyproject.toml  LICENSE  README.md  .gitignore  .pre-commit-hooks.yaml
indextool.toml  AGENTS.md                      (self-hosting, Task 15)
src/indextool/
  __init__.py     version constants
  __main__.py     python -m indextool
  errors.py       ConfigError (exit code 2)
  globs.py        gitignore-style matcher for `exclude` and `tests`
  gitio.py        git plumbing wrappers
  decode.py       bytes -> text (PEP 263, LF-normalized)
  sources.py      file discovery and content reading (worktree | index)
  config.py       locate, load, validate and normalize configuration
  scan.py         parse once with ast -> Module records; import edge resolution
  graph.py        importers, library/standalone, depth, cycles, look-alike names
  facts.py        tables, writers, routes, IO rating
  render.py       Repo + facts -> map text and index text (no I/O)
  output.py       atomic write, newline-normalized compare, diff lines
  pipeline.py     build_from_files, build, generate_files
  pointer.py      managed pointer block: render, upsert, placement, verify
  init.py         idempotent setup plan and apply
  cli.py          argument parsing, exit codes
tests/            helpers.py conftest.py fixture_repos.py test_*.py golden/
scripts/          update_goldens.py check_golden_bump.py check_patch_release.py
                  check_doc_tests.py parity.py
docs/             rules.md config.md trial.md architecture.md architecture.index.txt
CHANGELOG.md
.github/workflows/ci.yml release.yml
```

The spec's `scan` module (discover, decode, parse) is decomposed here into `sources`, `decode` and `scan`, and `gitio`,
`globs`, `errors`, `pointer` and `pipeline` are extracted, so that each file has one responsibility and can be tested
alone. The spec's module table still describes the responsibilities; only the file boundaries are finer.

---

### Task 1: Scaffold, license and the private-term guard

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `README.md`, `.gitignore`, `src/indextool/__init__.py`, `tests/__init__.py`, `tests/test_scaffold.py`
- Create outside the repository: `~/.indextool-private-terms`
- Create, unversioned: `.git/hooks/pre-commit`, `.git/hooks/commit-msg`

**Interfaces:**
- Produces: `indextool.__version__: str` (`"0.1.0"`), `indextool.FORMAT_VERSION: str` (`"0.1"`, the `major.minor` of `__version__`).

- [ ] **Step 1: Confirm the private-term list exists**

Run: `test -s ~/.indextool-private-terms && echo present`
Expected: `present`. The file is generated from the private reference repository by its own generator (every module key, table, route and class name it emits, plus hand-chosen terms), never written from memory: one extended regular expression per line; blank lines and lines starting with `#` are ignored; matching is case-insensitive. If it is missing, stop and tell the human partner; do not write it yourself. This file lives outside the repository and its contents must never be written into any tracked file, including this plan. A companion `~/.indextool-private-terms.full` holds the unfiltered extraction and is not read by the hooks.

- [ ] **Step 2: Install the local guard hooks**

```bash
cd /c/python/indextool
cat > .git/hooks/pre-commit <<'HOOK'
#!/bin/sh
# indextool private-term guard: local only, unversioned.
terms="${INDEXTOOL_PRIVATE_TERMS:-$HOME/.indextool-private-terms}"
if [ ! -s "$terms" ]; then
  echo "indextool guard: term list missing or empty: $terms" >&2
  exit 1
fi
clean=$(mktemp)
trap 'rm -f "$clean"' EXIT
grep -v -E '^[[:space:]]*(#|$)' "$terms" > "$clean"
if [ ! -s "$clean" ]; then
  echo "indextool guard: no terms in $terms" >&2
  exit 1
fi
if git diff --cached -U0 --no-color | grep -n -i -E -f "$clean" >&2; then
  echo "indextool guard: the staged changes contain a private term; commit refused" >&2
  exit 1
fi
exit 0
HOOK
cat > .git/hooks/commit-msg <<'HOOK'
#!/bin/sh
# indextool private-term guard for commit messages: local only, unversioned.
terms="${INDEXTOOL_PRIVATE_TERMS:-$HOME/.indextool-private-terms}"
if [ ! -s "$terms" ]; then
  echo "indextool guard: term list missing or empty: $terms" >&2
  exit 1
fi
clean=$(mktemp)
trap 'rm -f "$clean"' EXIT
grep -v -E '^[[:space:]]*(#|$)' "$terms" > "$clean"
if [ -s "$clean" ] && grep -n -i -E -f "$clean" "$1" >&2; then
  echo "indextool guard: the commit message contains a private term; commit refused" >&2
  exit 1
fi
exit 0
HOOK
chmod +x .git/hooks/pre-commit .git/hooks/commit-msg
```

- [ ] **Step 3: Prove the guard blocks a staged term and a commit message term**

This uses a throwaway term list, so no private term is written anywhere.

```bash
cd /c/python/indextool
T=$(mktemp)
printf 'zz-sample-private-term\n' > "$T"
printf 'zz-sample-private-term\n' > guard_probe.txt
git add guard_probe.txt
INDEXTOOL_PRIVATE_TERMS="$T" git commit -q -m "probe"; echo "staged-diff exit=$?"
git reset -q guard_probe.txt && rm guard_probe.txt
INDEXTOOL_PRIVATE_TERMS="$T" git commit -q --allow-empty -m "zz-sample-private-term"; echo "message exit=$?"
rm "$T"; git status --short
```
Expected: `staged-diff exit=1`, `message exit=1`, and an empty `git status --short`. If either exit is 0, the hooks are not executable or not being run; fix before continuing.

- [ ] **Step 4: Write the failing scaffold test**

`tests/__init__.py` (empty file), and `tests/test_scaffold.py`:

```python
import indextool


def test_version_and_format_version():
    assert indextool.__version__ == "0.1.0"
    assert indextool.FORMAT_VERSION == "0.1"
```

- [ ] **Step 5: Create the virtualenv and run the test to see it fail**

```bash
cd /c/python/indextool
python -m venv .venv
.venv/Scripts/python -m pip install -q pytest
.venv/Scripts/python -m pytest tests/test_scaffold.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'indextool'`.

- [ ] **Step 6: Create the package and project files**

`src/indextool/__init__.py`:

```python
"""indextool: a derived, verified architecture map for Python repositories."""

__version__ = "0.1.0"
FORMAT_VERSION = ".".join(__version__.split(".")[:2])
```

`pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.24"]
build-backend = "hatchling.build"

[project]
name = "indextool"
dynamic = ["version"]
description = "Derive a deterministic architecture map from a Python repository, commit it, and fail CI when it is stale."
readme = "README.md"
requires-python = ">=3.11"
license = { file = "LICENSE" }
authors = [{ name = "Marc Cats" }]
dependencies = []
classifiers = [
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3 :: Only",
    "License :: OSI Approved :: MIT License",
    "Topic :: Software Development :: Documentation",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
indextool = "indextool.cli:main"

[tool.hatch.version]
path = "src/indextool/__init__.py"

[tool.hatch.build.targets.wheel]
packages = ["src/indextool"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

`LICENSE`:

```
MIT License

Copyright (c) 2026 Marc Cats

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

`README.md` (replaced in Task 16):

```markdown
# indextool

Work in progress. See `docs/superpowers/specs/` for the design.
```

`.gitignore`:

```
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
.mypy_cache/
*.egg-info/
dist/
build/
.claude/settings.local.json
```

- [ ] **Step 7: Install the package editable and run the test to see it pass**

```bash
cd /c/python/indextool
.venv/Scripts/python -m pip install -q -e ".[dev]"
.venv/Scripts/python -m pytest tests/test_scaffold.py -v
```
Expected: `1 passed`.

- [ ] **Step 8: Commit**

```bash
cd /c/python/indextool
git add pyproject.toml LICENSE README.md .gitignore src tests
git commit -q -m "chore: scaffold indextool package" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git log --oneline | head -3
```
Expected: the guard hooks run silently and the commit succeeds.

---

### Task 2: Gitignore-style glob matcher

**Files:**
- Create: `src/indextool/errors.py`, `src/indextool/globs.py`
- Test: `tests/test_globs.py`

**Interfaces:**
- Produces: `errors.ConfigError(Exception)`; `globs.GlobSet(patterns: Iterable[str])` with `.patterns: tuple[str, ...]` and `.matches(path: str) -> bool`, where `path` is a `/`-separated path relative to the base directory. Invalid patterns raise `ConfigError`.

The rules (spec 5.4): a trailing `/` means a directory; a leading `/` anchors to the base directory; `**` spans directories; otherwise `*` and `?` do not cross `/`; a pattern with no `/` other than a trailing one matches at any depth; `[...]` is a character class; matching is case-sensitive; a `!` negation is an error; backslashes in patterns are separators.

- [ ] **Step 1: Write the failing tests**

`tests/test_globs.py`:

```python
import pytest

from indextool.errors import ConfigError
from indextool.globs import GlobSet


@pytest.mark.parametrize(
    "pattern,path,expected",
    [
        ("legacy/", "legacy/a.py", True),
        ("legacy/", "pkg/legacy/a.py", True),
        ("legacy/", "legacyx/a.py", False),
        ("legacy/", "pkg/legacy.py", False),  # a directory-only pattern never matches a file
        ("/build/", "build/a.py", True),
        ("/build/", "pkg/build/a.py", False),
        ("test_*.py", "pkg/test_a.py", True),
        ("test_*.py", "pkg/a_test_.py", False),
        ("*_test.py", "x/y/a_test.py", True),
        ("tests/", "tests/a.py", True),
        ("tests/", "a/b/tests/c/d.py", True),
        ("**/generated/*", "generated/a.py", True),
        ("**/generated/*", "x/y/generated/a.py", True),
        ("**/generated/*", "x/generated/sub/a.py", True),  # the directory "sub" matches "*"
        ("src/*.py", "src/a.py", True),
        ("src/*.py", "src/sub/a.py", False),  # "*" does not cross "/"
        ("src/**/gen.py", "src/gen.py", True),
        ("src/**/gen.py", "src/a/b/gen.py", True),
        ("docs/**", "docs/a/b.py", True),
        ("a?c.py", "abc.py", True),
        ("a?c.py", "a/c.py", False),
        ("[ab]*.py", "b1.py", True),
        ("[!ab]*.py", "b1.py", False),
        ("*.PY", "a.py", False),  # case-sensitive
    ],
)
def test_glob_matching(pattern, path, expected):
    assert GlobSet([pattern]).matches(path) is expected


@pytest.mark.parametrize("bad", ["!keep.py", "", "   ", "#comment", "/"])
def test_bad_patterns_are_config_errors(bad):
    with pytest.raises(ConfigError):
        GlobSet([bad])


def test_backslashes_are_separators():
    assert GlobSet(["legacy\\old\\"]).matches("legacy/old/a.py")


def test_any_pattern_in_the_set_matches():
    globs = GlobSet(["legacy/", "*.gen.py"])
    assert globs.matches("x/a.gen.py")
    assert globs.matches("legacy/b.py")
    assert not globs.matches("x/a.py")
    assert globs.patterns == ("legacy/", "*.gen.py")
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_globs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indextool.errors'`.

- [ ] **Step 3: Implement**

`src/indextool/errors.py`:

```python
class ConfigError(Exception):
    """A misconfiguration. The command line reports it and exits with code 2."""
```

`src/indextool/globs.py`:

```python
"""A small gitignore-style matcher, because fnmatch has no `**` and PurePath.match is not recursive before 3.13."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .errors import ConfigError


@dataclass(frozen=True)
class _Rule:
    regex: re.Pattern[str]
    dir_only: bool
    basename_only: bool


def _translate(body: str) -> str:
    out: list[str] = []
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c == "*":
            if body.startswith("**", i):
                j = i + 2
                if body.startswith("/", j):
                    out.append("(?:.*/)?")
                    i = j + 1
                else:
                    out.append(".*")
                    i = j
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and body[j] in "!^":
                j += 1
            if j < n and body[j] == "]":
                j += 1
            while j < n and body[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(c))
                i += 1
            else:
                cls = body[i + 1 : j]
                if cls[:1] in ("!", "^"):
                    cls = "^" + cls[1:]
                out.append("[" + cls.replace("\\", "\\\\") + "]")
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def _compile(pattern: str) -> _Rule:
    p = pattern.strip().replace("\\", "/")
    if not p or p.startswith("#"):
        raise ConfigError(f"glob {pattern!r}: empty patterns and comments are not allowed")
    if p.startswith("!"):
        raise ConfigError(f"glob {pattern!r}: negation is not supported")
    dir_only = p.endswith("/")
    p = p.rstrip("/")
    anchored = p.startswith("/")
    p = p.lstrip("/")
    if not p:
        raise ConfigError(f"glob {pattern!r}: the pattern names nothing")
    basename_only = "/" not in p and not anchored
    return _Rule(re.compile(_translate(p)), dir_only, basename_only)


class GlobSet:
    def __init__(self, patterns: Iterable[str]):
        self.patterns: tuple[str, ...] = tuple(patterns)
        self._rules = [_compile(p) for p in self.patterns]

    def matches(self, path: str) -> bool:
        parts = path.split("/")
        candidates = [("/".join(parts[:k]), True) for k in range(1, len(parts))] + [(path, False)]
        for rule in self._rules:
            for candidate, is_dir in candidates:
                if rule.dir_only and not is_dir:
                    continue
                target = candidate.rsplit("/", 1)[-1] if rule.basename_only else candidate
                if rule.regex.fullmatch(target):
                    return True
        return False
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_globs.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/indextool/errors.py src/indextool/globs.py tests/test_globs.py
git commit -q -m "feat: gitignore-style glob matcher" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Git plumbing wrappers and test helpers

**Files:**
- Create: `src/indextool/gitio.py`, `tests/helpers.py`, `tests/conftest.py`
- Test: `tests/test_gitio.py`

**Interfaces:**
- Produces (`gitio`): `GitError(Exception)`; `in_work_tree(base: Path) -> bool`; `top_level(base: Path) -> Path | None`; `IndexEntry(mode: str, sha: str, stage: int, path: str)` (frozen dataclass); `index_entries(base: Path) -> list[IndexEntry]` (paths relative to `base`, sorted as git sorts them); `cat_blobs(base: Path, specs: list[str]) -> list[bytes]` (each spec is a sha or `:./relative/path`; a missing object raises `GitError`); `unstaged(base: Path) -> set[str]` (tracked files modified in the working tree relative to the index, paths relative to `base`); `is_tracked(base: Path, rel: str) -> bool`.
- Produces (`tests/helpers.py`): `git(repo, *args, input=None) -> str`; `write_files(root, files)`; `init_repo(repo)`; `commit_all(repo, message="commit")`; `make_repo(parent, files, name="repo", commit=True) -> Path`. `files` maps a relative path to `str` or `bytes`.
- Produces (`tests/conftest.py`): fixture `repo_factory(files, name="repo", commit=True) -> Path` creating a repository under the test's `tmp_path`.

- [ ] **Step 1: Write the helpers and fixtures**

`tests/helpers.py`:

```python
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
```

`tests/conftest.py`:

```python
import pytest

from tests.helpers import make_repo


@pytest.fixture
def repo_factory(tmp_path):
    def factory(files, name="repo", commit=True):
        return make_repo(tmp_path, files, name=name, commit=commit)

    return factory
```

- [ ] **Step 2: Write the failing tests**

`tests/test_gitio.py`:

```python
import pytest

from indextool import gitio
from tests.helpers import git


def test_index_entries_report_mode_sha_stage_and_path(repo_factory):
    repo = repo_factory({"pkg/a.py": "x = 1\n", "b.txt": "hi\n"})
    entries = gitio.index_entries(repo)
    assert [(e.path, e.mode, e.stage) for e in entries] == [("b.txt", "100644", 0), ("pkg/a.py", "100644", 0)]
    assert all(len(e.sha) == 40 for e in entries)


def test_index_entries_are_relative_to_the_base_directory(repo_factory):
    repo = repo_factory({"top.py": "", "sub/pkg/a.py": "x = 1\n"})
    assert [e.path for e in gitio.index_entries(repo / "sub")] == ["pkg/a.py"]


def test_non_ascii_paths_are_not_quoted(repo_factory):
    repo = repo_factory({"café/naïve.py": "x = 1\n"})
    assert [e.path for e in gitio.index_entries(repo)] == ["café/naïve.py"]


def test_symlink_and_gitlink_modes_are_reported(repo_factory):
    repo = repo_factory({"a.py": "x = 1\n"})
    blob = git(repo, "hash-object", "-w", "--stdin", input=b"target").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},link.py")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},mod")
    assert {e.path: e.mode for e in gitio.index_entries(repo)} == {
        "a.py": "100644",
        "link.py": "120000",
        "mod": "160000",
    }


def test_files_staged_in_a_repository_with_no_commits_are_listed(repo_factory):
    repo = repo_factory({"a.py": "x = 1\n"}, commit=False)
    git(repo, "add", "-A")
    assert [e.path for e in gitio.index_entries(repo)] == ["a.py"]


def test_cat_blobs_by_sha_and_by_relative_path_and_missing_raises(repo_factory):
    repo = repo_factory({"sub/a.py": "x = 1\n"})
    sub = repo / "sub"
    sha = gitio.index_entries(sub)[0].sha
    assert gitio.cat_blobs(sub, [sha, ":./a.py"]) == [b"x = 1\n", b"x = 1\n"]
    assert gitio.cat_blobs(sub, []) == []
    with pytest.raises(gitio.GitError):
        gitio.cat_blobs(sub, [":./nope.py"])


def test_unstaged_lists_modified_tracked_files_relative_to_base(repo_factory):
    repo = repo_factory({"sub/a.py": "x = 1\n", "sub/b.py": "y = 1\n"})
    (repo / "sub" / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert gitio.unstaged(repo / "sub") == {"a.py"}
    git(repo, "add", "-A")
    assert gitio.unstaged(repo / "sub") == set()


def test_in_work_tree_top_level_and_is_tracked(repo_factory, tmp_path):
    repo = repo_factory({"sub/a.py": ""})
    (repo / "sub" / "loose.py").write_text("", encoding="utf-8")
    assert gitio.in_work_tree(repo / "sub") is True
    assert gitio.top_level(repo / "sub") == repo.resolve()
    assert gitio.is_tracked(repo / "sub", "a.py") is True
    assert gitio.is_tracked(repo / "sub", "loose.py") is False
    plain = tmp_path / "plain"
    plain.mkdir()
    assert gitio.in_work_tree(plain) is False
    assert gitio.top_level(plain) is None
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_gitio.py -v`
Expected: FAIL with `ImportError` (cannot import name `gitio`).

- [ ] **Step 4: Implement**

`src/indextool/gitio.py`:

```python
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
        if len(header) != 3:
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
    return bool(_run(["ls-files", "-z", "--", rel], base).strip(b"\0"))
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_gitio.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/indextool/gitio.py tests/helpers.py tests/conftest.py tests/test_gitio.py
git commit -q -m "feat: git plumbing wrappers and test helpers" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Source decoding and file discovery

**Files:**
- Create: `src/indextool/decode.py`, `src/indextool/sources.py`
- Test: `tests/test_decode.py`, `tests/test_sources.py`

**Interfaces:**
- Consumes: `gitio.*` (Task 3), `globs.GlobSet` and `errors.ConfigError` (Task 2).
- Produces (`decode`): `decode_source(data: bytes) -> tuple[str, bool]` returning the text with `\r\n` and `\r` normalized to `\n`, and `True` when the encoding was determinable (`False` for a bad cookie, a BOM/cookie mismatch, or invalid UTF-8 in the first two lines; the text is then a UTF-8 decode with replacement characters).
- Produces (`sources`): `DEFAULT_WALK_EXCLUDES: frozenset[str]`; `Discovered(files: dict[str, bytes], excluded: int, mode: str)` (frozen dataclass; `files` is keyed by base-relative `/` path, in sorted order; `mode` is `"git"` or `"walk"`); `discover(base: Path, discovery: str, exclude: GlobSet, source: str) -> Discovered` where `discovery` is `"auto"`, `"git"` or `"walk"` and `source` is `"worktree"` or `"index"`; `read_file(base: Path, rel: str, source: str) -> bytes | None` (`None` when the file does not exist in that source).

- [ ] **Step 1: Write the failing decode tests**

`tests/test_decode.py`:

```python
from indextool.decode import decode_source


def test_bom_is_stripped_and_newlines_are_normalized():
    text, ok = decode_source(b"\xef\xbb\xbfx = 1\r\ny = 2\rz = 3\n")
    assert (text, ok) == ("x = 1\ny = 2\nz = 3\n", True)


def test_latin1_cookie_is_honoured():
    text, ok = decode_source(b"# -*- coding: latin-1 -*-\nx = '\xe9'\n")
    assert ok is True
    assert "é" in text


def test_unknown_cookie_and_bom_mismatch_are_not_ok_and_never_raise():
    text, ok = decode_source(b"# coding: nosuchcodec\nx = 1\n")
    assert (text, ok) == ("# coding: nosuchcodec\nx = 1\n", False)
    _, ok = decode_source(b"\xef\xbb\xbf# coding: latin-1\nx = 1\n")
    assert ok is False


def test_invalid_utf8_in_the_first_two_lines_is_not_ok():
    _, ok = decode_source(b"x = '\xe9'\n")
    assert ok is False


def test_invalid_utf8_after_the_first_two_lines_is_replaced_not_fatal():
    text, ok = decode_source(b"a = 1\nb = 2\nc = '\xe9'\n")
    assert ok is True
    assert "\ufffd" in text
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_decode.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indextool.decode'`.

- [ ] **Step 3: Implement decode**

`src/indextool/decode.py`:

```python
"""Turn source bytes into text without ever consulting the locale."""
from __future__ import annotations

import io
import tokenize


def decode_source(data: bytes) -> tuple[str, bool]:
    """(text, encoding_ok). Newlines are normalized to LF. A file whose encoding cannot be determined (a bad
    coding cookie, a BOM that contradicts the cookie, invalid UTF-8 in the first two lines) is decoded as UTF-8 with
    replacement characters and reported as not ok, so the caller can count it as unparsable."""
    ok = True
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    except SyntaxError:
        encoding, ok = "utf-8", False
    text = data.decode(encoding, errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, ok
```

- [ ] **Step 4: Run to see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_decode.py -v`
Expected: all pass.

- [ ] **Step 5: Write the failing discovery tests**

`tests/test_sources.py`:

```python
import pytest

from indextool import sources
from indextool.errors import ConfigError
from indextool.globs import GlobSet
from tests.helpers import git, write_files

NOTHING = GlobSet([])


def test_git_mode_lists_tracked_python_files_only_and_sorted(repo_factory):
    repo = repo_factory({"b.py": "y = 1\n", "a.py": "x = 1\n", "notes.txt": "hi\n"})
    (repo / "scratch.py").write_text("z = 1\n", encoding="utf-8")  # untracked: never part of the map
    found = sources.discover(repo, "auto", NOTHING, "worktree")
    assert found.mode == "git"
    assert list(found.files) == ["a.py", "b.py"]
    assert found.files["a.py"] == b"x = 1\n"


def test_symlink_and_gitlink_entries_are_skipped_by_mode(repo_factory):
    repo = repo_factory({"a.py": "x = 1\n"})
    blob = git(repo, "hash-object", "-w", "--stdin", input=b"target").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},link.py")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},mod.py")
    assert list(sources.discover(repo, "auto", NOTHING, "worktree").files) == ["a.py"]


def test_tracked_but_deleted_files_are_skipped_in_worktree_mode(repo_factory):
    repo = repo_factory({"a.py": "x = 1\n", "b.py": "y = 1\n"})
    (repo / "b.py").unlink()
    assert list(sources.discover(repo, "auto", NOTHING, "worktree").files) == ["a.py"]
    assert list(sources.discover(repo, "auto", NOTHING, "index").files) == ["a.py", "b.py"]


def test_index_source_reads_staged_content_not_the_working_tree(repo_factory):
    repo = repo_factory({"a.py": "x = 1\n"})
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert sources.discover(repo, "auto", NOTHING, "worktree").files["a.py"] == b"x = 2\n"
    assert sources.discover(repo, "auto", NOTHING, "index").files["a.py"] == b"x = 1\n"
    git(repo, "add", "a.py")
    assert sources.discover(repo, "auto", NOTHING, "index").files["a.py"] == b"x = 2\n"


def test_exclude_patterns_drop_files_and_are_counted(repo_factory):
    repo = repo_factory({"keep.py": "", "legacy/old.py": "", "legacy/older.py": ""})
    found = sources.discover(repo, "auto", GlobSet(["legacy/"]), "worktree")
    assert list(found.files) == ["keep.py"]
    assert found.excluded == 2


def test_paths_that_differ_only_by_case_are_an_error(repo_factory):
    repo = repo_factory({"Foo.py": "", "x.txt": ""})
    git(repo, "config", "core.ignorecase", "false")  # git on Windows defaults to true, which would merge the two names
    blob = git(repo, "hash-object", "-w", "--stdin", input=b"").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},foo.py")
    with pytest.raises(ConfigError, match="differ only by case"):
        sources.discover(repo, "auto", NOTHING, "worktree")


def test_unmerged_paths_are_an_error(repo_factory):
    repo = repo_factory({"a.py": ""})
    blob = git(repo, "hash-object", "-w", "--stdin", input=b"x = 1\n").strip()
    entries = f"100644 {blob} 2\tconflict.py\n100644 {blob} 3\tconflict.py\n"
    git(repo, "update-index", "--index-info", input=entries.encode())
    with pytest.raises(ConfigError, match="unmerged"):
        sources.discover(repo, "auto", NOTHING, "worktree")


def test_staged_files_count_in_a_repository_with_no_commits(repo_factory):
    repo = repo_factory({"a.py": "x = 1\n"}, commit=False)
    git(repo, "add", "-A")
    assert list(sources.discover(repo, "auto", NOTHING, "index").files) == ["a.py"]


def test_walk_mode_skips_default_excludes_and_symlinks_and_is_sorted(tmp_path):
    write_files(tmp_path, {"b.py": "", "a.py": "", "venv/x.py": "", "node_modules/y.py": "", "pkg/__pycache__/z.py": ""})
    found = sources.discover(tmp_path, "auto", NOTHING, "worktree")
    assert found.mode == "walk"
    assert list(found.files) == ["a.py", "b.py"]
    assert found.excluded == 0


def test_walk_mode_rejects_index_source_and_forced_git_needs_a_repository(tmp_path):
    write_files(tmp_path, {"a.py": ""})
    with pytest.raises(ConfigError):
        sources.discover(tmp_path, "auto", NOTHING, "index")
    with pytest.raises(ConfigError):
        sources.discover(tmp_path, "git", NOTHING, "worktree")
    assert sources.discover(tmp_path, "walk", NOTHING, "worktree").mode == "walk"


def test_read_file_from_worktree_and_index(repo_factory):
    repo = repo_factory({"sub/cfg.toml": "a = 1\n"})
    (repo / "sub" / "cfg.toml").write_text("a = 2\n", encoding="utf-8")
    assert sources.read_file(repo / "sub", "cfg.toml", "worktree") == b"a = 2\n"
    assert sources.read_file(repo / "sub", "cfg.toml", "index") == b"a = 1\n"
    assert sources.read_file(repo / "sub", "missing.toml", "worktree") is None
    assert sources.read_file(repo / "sub", "missing.toml", "index") is None
```

- [ ] **Step 6: Run to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_sources.py -v`
Expected: FAIL with `ImportError` (cannot import name `sources`).

- [ ] **Step 7: Implement discovery**

`src/indextool/sources.py`:

```python
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
```

- [ ] **Step 8: Run to see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_decode.py tests/test_sources.py -v`
Expected: all pass. If `test_paths_that_differ_only_by_case_are_an_error` fails on Windows because the working tree cannot hold both names, that is expected to still pass, since the error is raised from the index path list before any file is read.

- [ ] **Step 9: Commit**

```bash
git add src/indextool/decode.py src/indextool/sources.py tests/test_decode.py tests/test_sources.py
git commit -q -m "feat: source decoding and git-aware file discovery" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Configuration

**Files:**
- Create: `src/indextool/config.py`
- Modify: `tests/helpers.py` (append `make_config`)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `sources.read_file` (Task 4), `gitio.*` (Task 3), `globs.GlobSet`, `errors.ConfigError` (Task 2).
- Produces (`config`):
  - `CONFIG_NAME = "indextool.toml"`, `DEFAULT_TESTS`, `DEFAULT_ARCHITECTURE = "docs/architecture.md"`, `DEFAULT_INDEX = "docs/architecture.index.txt"`, `DEFAULT_DECORATORS`, `DEFAULT_IO`, `DEFAULT_SQL`.
  - `SqlDetectors(create: tuple[re.Pattern, ...], use: tuple[str, ...], write: tuple[str, ...], write_any: tuple[re.Pattern, ...], is_default: bool)`. `use` and `write` are templates that contain `@TABLES@` exactly once; `create` and `write_any` are compiled with `re.IGNORECASE`.
  - `Config` (frozen dataclass): `base: Path` (absolute), `config_file: Path | None`, `config_untracked: bool`, `title: str` (empty when none), `roots: tuple[str, ...]`, `exclude: GlobSet`, `tests: GlobSet`, `architecture: str`, `index: str` (both base-relative `/` paths), `discovery: str`, `route_decorators: tuple[str, ...]`, `io: tuple[tuple[str, tuple[str, ...]], ...]` (ordered `db`, `network`, `http`), `sql: SqlDetectors`, plus a property `io_map -> dict[str, tuple[str, ...]]`.
  - `load_config(start: Path, explicit: Path | None = None, source: str = "worktree") -> Config`.
- Produces (`tests/helpers.py`): `make_config(directory: Path, toml_text: str = "") -> Config` writing `indextool.toml` (when `toml_text` is non-empty) and loading it.

Rules implemented here (spec 5.1 to 5.3): `indextool.toml` wins, else `[tool.indextool]` in `pyproject.toml`, else defaults; the config is searched upward from `start` and the search stops at the git top level; with no config the base is the git top level, or `start` outside git; `--config PATH` overrides; all relative paths resolve against the base; validation is strict and names the key; per-key replacement of defaults inside `[io]` and `[sql]`; title falls back to `[project].name` of the base directory's `pyproject.toml`; `--source` governs the content read for the config and for `pyproject.toml`; an explicit config outside the repository is an error; an untracked config sets `config_untracked` (the command decides what to do).

- [ ] **Step 1: Append the helper**

Append to `tests/helpers.py`:

```python
def make_config(directory: Path, toml_text: str = ""):
    from indextool.config import load_config

    directory.mkdir(parents=True, exist_ok=True)
    if toml_text:
        (directory / "indextool.toml").write_text(toml_text, encoding="utf-8")
    return load_config(directory)
```

- [ ] **Step 2: Write the failing tests**

`tests/test_config.py`:

```python
import pytest

from indextool.config import DEFAULT_ARCHITECTURE, DEFAULT_INDEX, DEFAULT_TESTS, load_config
from indextool.errors import ConfigError
from tests.helpers import git, make_config, write_files


def test_defaults_when_there_is_no_config(tmp_path):
    cfg = make_config(tmp_path)
    assert cfg.config_file is None and cfg.config_untracked is False
    assert cfg.base == tmp_path.resolve()
    assert cfg.title == "" and cfg.roots == (".",)
    assert cfg.architecture == DEFAULT_ARCHITECTURE and cfg.index == DEFAULT_INDEX
    assert cfg.discovery == "auto"
    assert cfg.tests.patterns == DEFAULT_TESTS
    assert cfg.exclude.patterns == ()
    assert "route" in cfg.route_decorators and "api_route" in cfg.route_decorators
    assert cfg.io_map["network"] == ("requests", "urllib.request", "urllib3", "aiohttp", "httpx")
    assert cfg.sql.is_default is True


def test_indextool_toml_overrides_and_normalizes(tmp_path):
    cfg = make_config(
        tmp_path,
        'title = "Shop"\nroots = ["src\\\\", "./lib"]\nexclude = ["legacy/"]\narchitecture = "docs\\\\map.md"\n'
        'index = "docs/idx.txt"\ndiscovery = "walk"\n[routes]\ndecorators = ["route", "get"]\n'
        '[io]\nnetwork = ["httpx"]\n',
    )
    assert cfg.title == "Shop"
    assert cfg.roots == ("src", "lib")
    assert cfg.exclude.matches("legacy/a.py")
    assert cfg.architecture == "docs/map.md" and cfg.index == "docs/idx.txt"
    assert cfg.discovery == "walk"
    assert cfg.route_decorators == ("route", "get")
    assert cfg.io_map["network"] == ("httpx",)
    assert cfg.io_map["db"][0] == "sqlite3"  # unspecified kinds keep their defaults


def test_pyproject_table_and_project_name_fallback(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "acme-shop"\n\n[tool.indextool]\nroots = ["src"]\n', encoding="utf-8"
    )
    cfg = make_config(tmp_path)
    assert cfg.config_file == (tmp_path / "pyproject.toml").resolve()
    assert cfg.roots == ("src",) and cfg.title == "acme-shop"


def test_project_name_is_the_title_fallback_even_without_a_config(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "acme-shop"\n', encoding="utf-8")
    assert make_config(tmp_path).title == "acme-shop"


def test_indextool_toml_wins_over_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.indextool]\ntitle = "from pyproject"\n', encoding="utf-8")
    assert make_config(tmp_path, 'title = "from toml"\n').title == "from toml"


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("titel = 'x'\n", "unknown key 'titel'"),
        ("[io]\ncache = ['redis']\n", "unknown key 'cache'"),
        ("[routes]\nfoo = []\n", "unknown key 'foo'"),
        ("[sql]\nmerge = []\n", "unknown key 'merge'"),
        ("discovery = 'sometimes'\n", "discovery"),
        ("roots = ['src', 'src/pkg']\n", "overlap"),
        ("roots = ['.', 'src']\n", "overlap"),
        ("roots = ['../outside']\n", "relative path"),
        ("exclude = ['!keep.py']\n", "negation"),
        ("architecture = 'a.md'\nindex = 'a.md'\n", "different"),
        ("[routes]\ndecorators = ['not valid']\n", "decorators"),
        ("[io]\ndb = ['a b']\n", "dotted"),
        ("[sql]\ncreate = ['CREATE TABLE (x']\n", "invalid regex"),
        ("[sql]\ncreate = ['CREATE TABLE \\w+']\n", "capture group"),
        ("[sql]\nuse = ['FROM (t)']\n", "@TABLES@"),
        ("[sql]\nwrite = ['@TABLES@ @TABLES@']\n", "@TABLES@"),
        ("this is not toml", "indextool.toml"),
    ],
)
def test_invalid_config_is_an_error_that_names_the_problem(tmp_path, text, fragment):
    with pytest.raises(ConfigError, match=fragment):
        make_config(tmp_path, text)


def test_config_is_found_by_searching_upward_and_base_is_its_directory(repo_factory):
    repo = repo_factory({"indextool.toml": 'title = "Root"\n', "pkg/deep/a.py": "x = 1\n"})
    cfg = load_config(repo / "pkg" / "deep")
    assert cfg.title == "Root"
    assert cfg.base == repo.resolve()
    assert cfg.config_untracked is False


def test_without_a_config_the_base_is_the_git_top_level(repo_factory):
    repo = repo_factory({"pkg/a.py": "x = 1\n"})
    assert load_config(repo / "pkg").base == repo.resolve()


def test_search_stops_at_the_git_top_level(repo_factory, tmp_path):
    (tmp_path / "indextool.toml").write_text('title = "outer"\n', encoding="utf-8")
    repo = repo_factory({"a.py": "x = 1\n"})
    assert load_config(repo).title == ""


def test_untracked_config_is_flagged(repo_factory):
    repo = repo_factory({"a.py": "x = 1\n"})
    (repo / "indextool.toml").write_text('title = "New"\n', encoding="utf-8")
    cfg = load_config(repo)
    assert cfg.title == "New" and cfg.config_untracked is True


def test_explicit_config_outside_the_repository_is_an_error(repo_factory, tmp_path):
    repo = repo_factory({"a.py": "x = 1\n"})
    outside = tmp_path / "elsewhere.toml"
    outside.write_text('title = "x"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="outside the repository"):
        load_config(repo, explicit=outside)


def test_explicit_config_inside_the_repository_is_used(repo_factory):
    repo = repo_factory({"a.py": "x = 1\n", "conf/custom.toml": 'title = "Custom"\n'})
    cfg = load_config(repo, explicit=repo / "conf" / "custom.toml")
    assert cfg.title == "Custom"
    assert cfg.base == (repo / "conf").resolve()


def test_source_index_reads_the_committed_config_not_the_edited_one(repo_factory):
    repo = repo_factory({"indextool.toml": 'title = "Committed"\n', "a.py": ""})
    (repo / "indextool.toml").write_text('title = "Edited"\n', encoding="utf-8")
    assert load_config(repo, source="worktree").title == "Edited"
    assert load_config(repo, source="index").title == "Committed"
    git(repo, "add", "indextool.toml")
    assert load_config(repo, source="index").title == "Edited"
```

- [ ] **Step 3: Run to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indextool.config'`.

- [ ] **Step 4: Implement**

`src/indextool/config.py`:

```python
"""Locate, load, validate and normalize configuration. Detectors are data, never code."""
from __future__ import annotations

import re
import tomllib
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


def _has_tool_table(path: Path) -> bool:
    try:
        return "indextool" in tomllib.loads(path.read_text(encoding="utf-8")).get("tool", {})
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return False


def _locate(start: Path) -> tuple[Path | None, Path]:
    top = gitio.top_level(start) if gitio.in_work_tree(start) else None
    directory = start
    while True:
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate, directory
        pyproject = directory / "pyproject.toml"
        if pyproject.is_file() and _has_tool_table(pyproject):
            return pyproject, directory
        if directory == top or directory.parent == directory:
            break
        directory = directory.parent
    return None, (top or start)


def _project_name(base: Path, source: str) -> str | None:
    raw = read_file(base, "pyproject.toml", source)
    if raw is None:
        return None
    try:
        name = tomllib.loads(raw.decode("utf-8")).get("project", {}).get("name")
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None
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
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
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


def _known_keys(table: object, allowed: tuple[str, ...] | frozenset[str], where: str) -> dict:
    if not isinstance(table, dict):
        raise ConfigError(f"{where}: expected a table")
    for key in sorted(table):
        if key not in allowed:
            raise ConfigError(f"{where}: unknown key {key!r}")
    return table


def _build_sql(table: dict | None) -> SqlDetectors:
    given = _known_keys(table or {}, SQL_KEYS, "[sql]")
    raw = {key: (_string_list(given[key], f"[sql] {key}") if key in given else dict(DEFAULT_SQL)[key]) for key in SQL_KEYS}
    return SqlDetectors(
        create=tuple(_compile(p, "[sql] create", groups=1) for p in raw["create"]),
        use=_templates(raw["use"], "[sql] use"),
        write=_templates(raw["write"], "[sql] write"),
        write_any=tuple(_compile(p, "[sql] write_any") for p in raw["write_any"]),
        is_default=not given,
    )


def _build_io(table: dict | None) -> tuple[tuple[str, tuple[str, ...]], ...]:
    given = _known_keys(table or {}, IO_KINDS, "[io]")
    out = []
    for kind, default in DEFAULT_IO:
        entries = _string_list(given[kind], f"[io] {kind}") if kind in given else default
        for entry in entries:
            if not _DOTTED.match(entry):
                raise ConfigError(f"[io] {kind}: {entry!r} is not a dotted import name")
        out.append((kind, entries))
    return tuple(out)


def _build_decorators(table: dict | None) -> tuple[str, ...]:
    given = _known_keys(table or {}, ("decorators",), "[routes]")
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
        config_file, base = _locate(start)

    table: dict = {}
    project_name: str | None = None
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
            table = data.get("tool", {}).get("indextool", {})
            name = data.get("project", {}).get("name")
            project_name = name if isinstance(name, str) else None
        else:
            table = data
        if gitio.in_work_tree(base):
            untracked = not gitio.is_tracked(base, rel)
    if project_name is None:
        project_name = _project_name(base, source)

    table = _known_keys(table, _TOP_KEYS, config_file.name if config_file else "config")
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
        exclude=GlobSet(_string_list(table.get("exclude", []), "exclude")),
        tests=GlobSet(_string_list(table.get("tests", list(DEFAULT_TESTS)), "tests")),
        architecture=architecture,
        index=index,
        discovery=discovery,
        route_decorators=_build_decorators(table.get("routes")),
        io=_build_io(table.get("io")),
        sql=_build_sql(table.get("sql")),
    )
```

- [ ] **Step 5: Run to see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: all pass. The `this is not toml` case must raise a `ConfigError` whose message contains `indextool.toml`.

- [ ] **Step 6: Commit**

```bash
git add src/indextool/config.py tests/helpers.py tests/test_config.py
git commit -q -m "feat: configuration loading and validation" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 6: Scan: parse once, collect module facts, resolve import edges

**Files:**
- Create: `src/indextool/scan.py`
- Test: `tests/test_scan.py`

**Interfaces:**
- Consumes: `config.Config` (fields `roots`, `tests`, `route_decorators`; Task 5), `decode.decode_source` (Task 4), `errors.ConfigError` (Task 2).
- Produces (`scan`): `SENTINEL = ""` (stands where an f-string holds a value); `ImportSpec(level: int, module: str, names: tuple[str, ...])` (frozen); `Module` (mutable dataclass) with fields `key: str`, `path: str`, `is_package: bool`, `is_test: bool`, `parse_error: bool = False`, `doc: str = ""`, `has_main: bool = False`, `imports: tuple[ImportSpec, ...] = ()`, `classes: tuple[str, ...] = ()`, `constants: tuple[str, ...] = ()`, `literals: tuple[str, ...] = ()`, `routes: tuple[str, ...] = ()`, `calls_to_sql: bool = False`, `edges: frozenset[str] = frozenset()`; `module_key(inner: str) -> tuple[str, bool]` (`inner` is the path relative to its root; returns the dotted key and whether the file is a package `__init__`); `scan(files: dict[str, bytes], cfg: Config) -> dict[str, Module]` (keyed by module key, in key-insertion order of the sorted paths); `resolve_edges(mods: dict[str, Module]) -> None` (fills `edges` in place: keys of repository modules a module imports, without itself).

Rules (reference rule document sections 3 to 4, plus spec 4 and 5.3): a file outside every root is ignored; a root-level `__init__.py` has an empty key and is skipped; two files with the same key are an error; function-level and conditional imports are edges; `import a.b` targets the longest known prefix; `from a import b` targets the longest known prefix of `a` plus `a.b` when that is a module; relative imports resolve against the importing module's package; anything that resolves to no repository module is dropped; docstrings are not string evidence; an f-string is one string with `SENTINEL` where each value goes; a file that cannot be decoded or parsed is a module with no imports, title or routes whose raw text is its only literal.

- [ ] **Step 1: Write the failing tests**

`tests/test_scan.py`:

```python
import pytest

from indextool.errors import ConfigError
from indextool.scan import SENTINEL, module_key, resolve_edges, scan
from tests.helpers import make_config


def run_scan(directory, files, toml=""):
    cfg = make_config(directory, toml)
    data = {path: (c.encode("utf-8") if isinstance(c, str) else c) for path, c in files.items()}
    mods = scan(data, cfg)
    resolve_edges(mods)
    return mods


def test_module_keys():
    assert module_key("pkg/mod.py") == ("pkg.mod", False)
    assert module_key("pkg/__init__.py") == ("pkg", True)
    assert module_key("top.py") == ("top", False)
    assert module_key("__init__.py") == ("", True)


def test_roots_relativize_keys_and_files_outside_are_ignored(tmp_path):
    mods = run_scan(
        tmp_path,
        {"src/shop/orders.py": "", "src/shop/__init__.py": "", "tools/x.py": "", "__init__.py": ""},
        'roots = ["src"]\n',
    )
    assert list(mods) == ["shop", "shop.orders"]
    assert mods["shop"].is_package and not mods["shop.orders"].is_package


def test_two_files_with_the_same_key_are_an_error(tmp_path):
    with pytest.raises(ConfigError, match="both map to the key 'util'"):
        run_scan(tmp_path, {"src/util.py": "", "lib/util.py": ""}, 'roots = ["src", "lib"]\n')


def test_test_modules_follow_the_tests_patterns(tmp_path):
    mods = run_scan(
        tmp_path,
        {"shop/orders.py": "", "shop/test_orders.py": "", "tests/conftest.py": "", "shop/orders_test.py": ""},
    )
    assert {k for k, m in mods.items() if m.is_test} == {"shop.test_orders", "tests.conftest", "shop.orders_test"}


def test_first_docstring_line_and_main_guard(tmp_path):
    mods = run_scan(
        tmp_path,
        {
            "a.py": '"""\n\n  Order ledger.\n\nMore text.\n"""\nif __name__ == "__main__":\n    pass\n',
            "b.py": "x = 1\n",
        },
    )
    assert mods["a"].doc == "Order ledger." and mods["a"].has_main is True
    assert mods["b"].doc == "" and mods["b"].has_main is False


def test_a_docstring_with_a_form_feed_and_u2028_stays_one_line(tmp_path):
    mods = run_scan(tmp_path, {"a.py": '"""Alpha\\x0cbeta\\u2028gamma"""\n'})
    assert mods["a"].doc == "Alpha\x0cbeta gamma"


def test_public_classes_and_upper_case_constant_tables(tmp_path):
    src = "class Money: pass\nclass _Hidden: pass\nRATES = {'a': 1}\nNAMES = ['x']\nLIMIT = 5\n_PRIVATE = (1,)\n"
    mod = run_scan(tmp_path, {"a.py": src})["a"]
    assert mod.classes == ("Money",) and mod.constants == ("RATES", "NAMES")


def test_edges_absolute_relative_and_submodule_imports(tmp_path):
    files = {
        "shop/__init__.py": "",
        "shop/orders.py": "from . import ledger\nfrom .ledger import Money\nimport shop.web\nimport os.path\n",
        "shop/ledger.py": "class Money: pass\n",
        "shop/web.py": "from shop import orders as o\nfrom shop.missing import x\nfrom .. import nothing\n",
        "shop/sub/__init__.py": "from ..ledger import Money\n",
    }
    mods = run_scan(tmp_path, files)
    assert mods["shop.orders"].edges == {"shop", "shop.ledger", "shop.web"}
    assert mods["shop.web"].edges == {"shop", "shop.orders"}
    assert mods["shop.sub"].edges == {"shop.ledger"}


def test_function_level_and_conditional_imports_are_edges(tmp_path):
    src = "import a\n\ndef f():\n    import b\n\ntry:\n    import c\nexcept ImportError:\n    pass\n"
    mods = run_scan(tmp_path, {"m.py": src, "a.py": "", "b.py": "", "c.py": ""})
    assert mods["m"].edges == {"a", "b", "c"}


def test_routes_require_a_listed_decorator_and_a_literal_path_starting_with_a_slash(tmp_path):
    src = (
        "@app.route('/orders')\ndef a(): pass\n"
        "@bp.get('/orders/<int:id>')\nasync def b(): pass\n"
        "@cache.delete('user')\ndef c(): pass\n"
        "@app.route(path)\ndef d(): pass\n"
        "@retry.get\ndef e(): pass\n"
        "@app.custom('/x')\ndef f(): pass\n"
    )
    assert run_scan(tmp_path, {"web.py": src})["web"].routes == ("/orders", "/orders/<int:id>")


def test_literals_skip_docstrings_and_mark_fstring_values(tmp_path):
    src = '"""Docs mention INSERT INTO ghost."""\nq = "SELECT 1"\nr = f"INSERT INTO t VALUES ({1})"\n'
    literals = run_scan(tmp_path, {"m.py": src})["m"].literals
    assert "SELECT 1" in literals
    assert f"INSERT INTO t VALUES ({SENTINEL})" in literals
    assert not any("ghost" in s for s in literals)


def test_to_sql_calls_are_noticed(tmp_path):
    mods = run_scan(tmp_path, {"a.py": "df.to_sql('t', con)\n", "b.py": "x = 1\n"})
    assert mods["a"].calls_to_sql is True and mods["b"].calls_to_sql is False


@pytest.mark.parametrize(
    "data",
    [
        b"def broken(:\n",
        ("x = " + "(" * 300 + "1" + ")" * 300 + "\n").encode(),
        b"# coding: nosuchcodec\nx = 1\n",
        b"\xef\xbb\xbf# coding: latin-1\nx = 1\n",
    ],
)
def test_unparsable_files_are_counted_modules_with_only_their_raw_text(tmp_path, data):
    mod = run_scan(tmp_path, {"bad.py": data})["bad"]
    assert mod.parse_error is True
    assert mod.imports == () and mod.edges == frozenset() and mod.doc == "" and mod.routes == ()
    assert len(mod.literals) == 1


def test_non_ascii_paths_and_docstrings(tmp_path):
    mods = run_scan(tmp_path, {"café/naïve.py": '"""Crème brûlée."""\n'})
    assert list(mods) == ["café.naïve"]
    assert mods["café.naïve"].doc == "Crème brûlée."


def test_scan_is_independent_of_input_order(tmp_path):
    files = {"a.py": "import b\n", "b.py": "", "c.py": "import a\n"}
    first = run_scan(tmp_path, files)
    second = run_scan(tmp_path, dict(reversed(list(files.items()))))
    assert list(first) == list(second) == ["a", "b", "c"]
    assert first == second
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_scan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indextool.scan'`.

- [ ] **Step 3: Implement**

`src/indextool/scan.py`:

```python
"""Parse each discovered file once and keep what the map needs."""
from __future__ import annotations

import ast
from dataclasses import dataclass

from .config import Config
from .decode import decode_source
from .errors import ConfigError

SENTINEL = ""  # stands where an f-string holds a value


@dataclass(frozen=True)
class ImportSpec:
    level: int
    module: str
    names: tuple[str, ...]


@dataclass
class Module:
    key: str
    path: str
    is_package: bool
    is_test: bool
    parse_error: bool = False
    doc: str = ""
    has_main: bool = False
    imports: tuple[ImportSpec, ...] = ()
    classes: tuple[str, ...] = ()
    constants: tuple[str, ...] = ()
    literals: tuple[str, ...] = ()
    routes: tuple[str, ...] = ()
    calls_to_sql: bool = False
    edges: frozenset[str] = frozenset()


def module_key(inner: str) -> tuple[str, bool]:
    parts = inner[:-3].split("/")
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _within_root(path: str, roots: tuple[str, ...]) -> str | None:
    for root in roots:
        if root == ".":
            return path
        if path.startswith(root + "/"):
            return path[len(root) + 1 :]
    return None


def _first_doc_line(tree: ast.Module) -> str:
    doc = ast.get_docstring(tree) or ""
    for line in doc.split("\n"):
        if line.strip():
            return line.strip()
    return ""


def _has_main_guard(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.If):
            text = ast.unparse(node.test)
            if "__name__" in text and "__main__" in text:
                return True
    return False


def _top_level_names(tree: ast.Module) -> tuple[tuple[str, ...], tuple[str, ...]]:
    classes: list[str] = []
    constants: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            classes.append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(
            node.value, (ast.Dict, ast.List, ast.Tuple, ast.Set)
        ):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Name) and target.id.isupper() and not target.id.startswith("_"):
                    constants.append(target.id)
    return tuple(classes), tuple(constants)


def _collect_imports(tree: ast.Module) -> tuple[ImportSpec, ...]:
    specs: list[ImportSpec] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            specs.extend(ImportSpec(0, alias.name, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            specs.append(ImportSpec(node.level, node.module or "", tuple(a.name for a in node.names)))
    return tuple(specs)


def _string_literals(tree: ast.Module) -> tuple[str, ...]:
    """Every string literal except docstrings; an f-string is one string with SENTINEL where a value goes."""
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                skip.add(id(first.value))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            skip.update(id(v) for v in node.values)
            out.append(
                "".join(
                    v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else SENTINEL
                    for v in node.values
                )
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            out.append(node.value)
    return tuple(out)


def _routes_in(tree: ast.Module, decorators: frozenset[str]) -> tuple[str, ...]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                if (
                    isinstance(deco, ast.Call)
                    and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr in decorators
                    and deco.args
                    and isinstance(deco.args[0], ast.Constant)
                    and isinstance(deco.args[0].value, str)
                    and deco.args[0].value.startswith("/")
                ):
                    found.append((deco.lineno, deco.args[0].value))
    return tuple(path for _line, path in sorted(found))


def _parse(key: str, path: str, is_package: bool, data: bytes, is_test: bool, decorators: frozenset[str]) -> Module:
    text, encoding_ok = decode_source(data)
    mod = Module(key=key, path=path, is_package=is_package, is_test=is_test)
    tree = None
    if encoding_ok:
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError, RecursionError):
            tree = None
    if tree is None:
        mod.parse_error = True
        mod.literals = (text,)
        return mod
    mod.doc = _first_doc_line(tree)
    mod.has_main = _has_main_guard(tree)
    mod.imports = _collect_imports(tree)
    mod.classes, mod.constants = _top_level_names(tree)
    mod.literals = _string_literals(tree)
    mod.routes = _routes_in(tree, decorators)
    mod.calls_to_sql = any(isinstance(n, ast.Attribute) and n.attr == "to_sql" for n in ast.walk(tree))
    return mod


def scan(files: dict[str, bytes], cfg: Config) -> dict[str, Module]:
    mods: dict[str, Module] = {}
    decorators = frozenset(cfg.route_decorators)
    for path in sorted(files):
        inner = _within_root(path, cfg.roots)
        if inner is None:
            continue
        key, is_package = module_key(inner)
        if not key:
            continue
        if key in mods:
            raise ConfigError(f"modules {mods[key].path} and {path} both map to the key {key!r}")
        mods[key] = _parse(key, path, is_package, files[path], cfg.tests.matches(path), decorators)
    return mods


def _longest_known(dotted: str, known: set[str]) -> str | None:
    parts = dotted.split(".") if dotted else []
    while parts:
        candidate = ".".join(parts)
        if candidate in known:
            return candidate
        parts.pop()
    return None


def _resolve(spec: ImportSpec, importer: Module, known: set[str]) -> set[str]:
    if spec.level == 0 and not spec.names:  # `import a.b`
        hit = _longest_known(spec.module, known)
        return {hit} if hit else set()
    out: set[str] = set()
    if spec.level == 0:
        base = spec.module
    else:
        pkg = importer.key.split(".") if importer.key else []
        if not importer.is_package:
            pkg = pkg[:-1]
        up = spec.level - 1
        if up > len(pkg):
            return out
        pkg = pkg[: len(pkg) - up]
        base = ".".join(pkg + ([spec.module] if spec.module else []))
    hit = _longest_known(base, known)
    if hit:
        out.add(hit)
    for name in spec.names:
        sub = f"{base}.{name}" if base else name
        if sub in known:
            out.add(sub)
    return out


def resolve_edges(mods: dict[str, Module]) -> None:
    known = set(mods)
    for mod in mods.values():
        edges: set[str] = set()
        for spec in mod.imports:
            edges |= _resolve(spec, mod, known)
        edges.discard(mod.key)
        mod.edges = frozenset(edges)
```

- [ ] **Step 4: Run to see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_scan.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/indextool/scan.py tests/test_scan.py
git commit -q -m "feat: scan modules and resolve import edges" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Graph: importers, library modules, depth, cycles, look-alike names

**Files:**
- Create: `src/indextool/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: `scan.Module` (its `key`, `is_test`, `edges`, `classes`, `constants`).
- Produces (`graph`), all pure functions over `mods: dict[str, Module]`:
  - `dependents(mods) -> dict[str, set[str]]` (for each key, the keys that import it, tests included).
  - `importers(mods) -> dict[str, list[str]]` (for each key, the sorted non-test modules that import it).
  - `library_modules(mods) -> set[str]` (non-test modules with at least one non-test importer).
  - `find_cycles(mods) -> list[list[str]]` (strongly connected components of two or more modules, each sorted, ordered largest first then by members).
  - `compute_depths(mods) -> dict[str, int]` (every non-test module; cycles collapse into one node).
  - `find_duplicate_names(mods) -> list[tuple[str, str, list[str]]]` (`(kind, name, keys)` with kind `"class"` or `"constant"`, most definitions first then by name then kind; a name qualifies when two or more library modules define it; standalone copies are listed with the others).

- [ ] **Step 1: Write the failing tests**

`tests/test_graph.py`:

```python
from indextool.graph import (
    compute_depths,
    dependents,
    find_cycles,
    find_duplicate_names,
    importers,
    library_modules,
)
from indextool.scan import Module


def mk(key, edges=(), is_test=False, classes=(), constants=()):
    return Module(
        key=key,
        path=key.replace(".", "/") + ".py",
        is_package=False,
        is_test=is_test,
        edges=frozenset(edges),
        classes=tuple(classes),
        constants=tuple(constants),
    )


def graph_of(*modules):
    return {m.key: m for m in modules}


def test_dependents_and_importers_ignore_test_importers_only_in_importers():
    mods = graph_of(mk("a", ["b"]), mk("b"), mk("test_b", ["b"], is_test=True))
    assert dependents(mods)["b"] == {"a", "test_b"}
    assert importers(mods)["b"] == ["a"]


def test_library_and_standalone_ignore_test_importers():
    mods = graph_of(mk("a", ["b"]), mk("b"), mk("test_c", ["c"], is_test=True), mk("c"))
    assert library_modules(mods) == {"b"}  # c is imported only by a test module


def test_depth_is_one_more_than_the_deepest_import():
    mods = graph_of(mk("top", ["mid", "leaf"]), mk("mid", ["leaf"]), mk("leaf"), mk("alone"))
    assert compute_depths(mods) == {"top": 2, "mid": 1, "leaf": 0, "alone": 0}


def test_depth_ignores_test_modules():
    mods = graph_of(mk("a"), mk("test_a", ["a"], is_test=True))
    assert compute_depths(mods) == {"a": 0}


def test_cycle_members_share_a_depth_and_are_reported():
    mods = graph_of(mk("x", ["y"]), mk("y", ["z"]), mk("z", ["x", "base"]), mk("base"), mk("app", ["x"]))
    assert find_cycles(mods) == [["x", "y", "z"]]
    depths = compute_depths(mods)
    assert depths["x"] == depths["y"] == depths["z"] == 1
    assert depths["app"] == 2 and depths["base"] == 0


def test_cycles_are_ordered_largest_first_then_by_name():
    mods = graph_of(mk("a", ["b"]), mk("b", ["a"]), mk("c", ["d"]), mk("d", ["e"]), mk("e", ["c"]))
    assert find_cycles(mods) == [["c", "d", "e"], ["a", "b"]]


def test_no_cycles_in_a_dag():
    assert find_cycles(graph_of(mk("a", ["b"]), mk("b"))) == []


def test_duplicate_names_need_two_library_definitions():
    mods = graph_of(
        mk("app", ["one", "two"]),
        mk("one", classes=["Money"], constants=["RATES"]),
        mk("two", classes=["Money"]),
        mk("script", classes=["Money", "Solo"]),
        mk("test_x", classes=["Money"], is_test=True),
    )
    assert find_duplicate_names(mods) == [("class", "Money", ["one", "script", "two"])]
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_graph.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indextool.graph'`.

- [ ] **Step 3: Implement**

`src/indextool/graph.py`:

```python
"""Graph rules over module records: who imports whom, depth, cycles, look-alike names."""
from __future__ import annotations

from .scan import Module


def dependents(mods: dict[str, Module]) -> dict[str, set[str]]:
    rev: dict[str, set[str]] = {key: set() for key in mods}
    for mod in mods.values():
        for dep in mod.edges:
            if dep in rev:
                rev[dep].add(mod.key)
    return rev


def importers(mods: dict[str, Module]) -> dict[str, list[str]]:
    rev = dependents(mods)
    return {key: sorted(i for i in rev[key] if not mods[i].is_test) for key in mods}


def library_modules(mods: dict[str, Module]) -> set[str]:
    imp = importers(mods)
    return {key for key, mod in mods.items() if not mod.is_test and imp[key]}


def find_cycles(mods: dict[str, Module]) -> list[list[str]]:
    """Strongly connected components with more than one module (iterative Tarjan)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    sccs: list[list[str]] = []
    counter = 0
    for start in sorted(mods):
        if start in index:
            continue
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        work = [(start, iter(sorted(mods[start].edges)))]
        while work:
            node, it = work[-1]
            descended = False
            for nxt in it:
                if nxt not in mods:
                    continue
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(mods[nxt].edges))))
                    descended = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if descended:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    comp.append(member)
                    if member == node:
                        break
                if len(comp) > 1:
                    sccs.append(sorted(comp))
    return sorted(sccs, key=lambda c: (-len(c), c))


def compute_depths(mods: dict[str, Module]) -> dict[str, int]:
    """Depth of every non-test module: 0 when it imports no other module here, otherwise one more than the deepest
    module it imports. Modules in an import cycle share one depth. Tests are not part of the graph."""
    keys = {k for k, m in mods.items() if not m.is_test}
    cycles = [[k for k in comp if k in keys] for comp in find_cycles(mods)]
    node_of = {k: ("cycle", i) for i, comp in enumerate(c for c in cycles if len(c) > 1) for k in comp}
    deps: dict = {}
    for k in sorted(keys):
        node = node_of.get(k, k)
        deps.setdefault(node, set()).update(node_of.get(d, d) for d in mods[k].edges if d in keys)
        deps[node].discard(node)
    depth: dict = {}
    for start in sorted(deps, key=repr):
        if start in depth:
            continue
        active = {start}
        stack = [(start, iter(sorted(deps[start], key=repr)))]
        while stack:
            node, pending = stack[-1]
            for nxt in pending:
                if nxt not in depth and nxt not in active:
                    active.add(nxt)
                    stack.append((nxt, iter(sorted(deps[nxt], key=repr))))
                    break
            else:
                depth[node] = 1 + max((depth[d] for d in deps[node] if d in depth), default=-1)
                active.discard(node)
                stack.pop()
    return {k: depth[node_of.get(k, k)] for k in keys}


def find_duplicate_names(mods: dict[str, Module]) -> list[tuple[str, str, list[str]]]:
    """A class or constant table that two or more library modules define, most definitions first. Copies in standalone
    scripts are listed with the others but do not make a name a duplicate."""
    library = library_modules(mods)
    where: dict[tuple[str, str], list[str]] = {}
    for mod in mods.values():
        if mod.is_test:
            continue
        for name in mod.classes:
            where.setdefault(("class", name), []).append(mod.key)
        for name in mod.constants:
            where.setdefault(("constant", name), []).append(mod.key)
    rows = [
        (kind, name, sorted(keys))
        for (kind, name), keys in where.items()
        if sum(1 for k in keys if k in library) >= 2
    ]
    return sorted(rows, key=lambda r: (-len(r[2]), r[1], r[0]))
```

- [ ] **Step 4: Run to see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_graph.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/indextool/graph.py tests/test_graph.py
git commit -q -m "feat: graph rules (importers, depth, cycles, look-alike names)" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Facts: tables, writers, routes and IO rating

**Files:**
- Create: `src/indextool/facts.py`
- Test: `tests/test_facts.py`

**Interfaces:**
- Consumes: `scan.Module`, `scan.SENTINEL`, `scan.ImportSpec` (Task 6); `config.Config` (`cfg.sql`, `cfg.io_map`; Task 5).
- Produces (`facts`): `Facts` dataclass with `created: set[str]`, `tables: dict[str, set[str]]` (table to keys of the non-test modules that create or query it), `writers: dict[str, set[str]]`, `routes: dict[str, list[str]]` (module key to its route paths in source order), `io: dict[str, str]` (module key to rating; every non-test module has an entry, `""` when there is no evidence); `derive_facts(mods: dict[str, Module], cfg: Config) -> Facts`; `import_names(imports: tuple[ImportSpec, ...]) -> set[str]`.

Rules (spec 5.3): tests contribute nothing; SQL is read from string literals only, joined per module with `\n` and with `SENTINEL` replaced by `?` for table facts; `@TABLES@` is replaced textually by the created names, each `re.escape`d, sorted longest first with ties by name; all patterns are `re.IGNORECASE`; a module's IO rating comes from its own imports: an import statement yields the module name and, for `from m import n`, also `m.n`; a `[io]` entry matches a yielded name that equals it or starts with it plus `.`; the rating is `db-r` or `db-rw` (write evidence is `.to_sql` or a `write_any` match in a single literal with `SENTINEL` replaced by `x`), then `network`, then `http`, joined with `+`; a module that failed to parse has no rating; relative imports are repository modules and never count.

- [ ] **Step 1: Write the failing tests**

`tests/test_facts.py`:

```python
import pytest

from indextool.facts import derive_facts
from indextool.scan import resolve_edges, scan
from tests.helpers import make_config


def facts_of(directory, files, toml=""):
    cfg = make_config(directory, toml)
    mods = scan({p: c.encode("utf-8") for p, c in files.items()}, cfg)
    resolve_edges(mods)
    return derive_facts(mods, cfg)


SQL_APP = {
    "shop/ledger.py": 'import sqlite3\nSCHEMA = "CREATE TABLE IF NOT EXISTS ledger (id INTEGER)"\nq = "SELECT * FROM ledger"\n',
    "shop/orders.py": (
        'import sqlite3\nA = "CREATE TABLE orders (id INTEGER)"\nB = "INSERT INTO orders VALUES (1)"\n'
        'C = "SELECT o.id FROM orders o JOIN ledger l ON 1"\n'
    ),
    "shop/report.py": 'import sqlite3\nD = "SELECT * FROM orders"\n',
}


def test_created_tables_users_and_writers(tmp_path):
    facts = facts_of(tmp_path, SQL_APP)
    assert facts.created == {"ledger", "orders"}
    assert facts.tables == {
        "ledger": {"shop.ledger", "shop.orders"},
        "orders": {"shop.orders", "shop.report"},
    }
    assert facts.writers == {"ledger": {"shop.ledger"}, "orders": {"shop.orders"}}


def test_docstrings_and_comments_are_not_evidence_and_fstrings_count(tmp_path):
    files = {
        "a.py": 'X = "CREATE TABLE real_one (id INTEGER)"\n',
        "b.py": '"""Reads FROM real_one in prose."""\n# INSERT INTO real_one is a comment\n',
        "c.py": 'def f(t):\n    return f"INSERT INTO real_one VALUES ({t})"\n',
    }
    facts = facts_of(tmp_path, files)
    assert facts.tables == {"real_one": {"a", "c"}}
    assert facts.writers == {"real_one": {"a", "c"}}


def test_similar_table_names_are_not_confused(tmp_path):
    files = {
        "a.py": 'A = "CREATE TABLE orders (id INT)"\nB = "CREATE TABLE orders_archive (id INT)"\nC = "INSERT INTO orders_archive VALUES (1)"\n',
        "b.py": 'D = "SELECT * FROM orders"\n',
    }
    facts = facts_of(tmp_path, files)
    assert facts.tables["orders"] == {"a", "b"} and facts.tables["orders_archive"] == {"a"}
    assert facts.writers["orders_archive"] == {"a"}


def test_test_modules_contribute_nothing(tmp_path):
    files = {
        "a.py": 'X = "CREATE TABLE t1 (id INTEGER)"\n',
        "test_a.py": 'X = "CREATE TABLE t2 (id INTEGER)"\n@app.route("/x")\ndef f(): pass\n',
    }
    facts = facts_of(tmp_path, files)
    assert facts.created == {"t1"} and facts.routes == {}
    assert "test_a" not in facts.io


def test_custom_create_pattern_and_table_names_are_escaped(tmp_path):
    toml = r"""
[sql]
create = ['DEFINE\s+"([\w$-]+)"']
"""
    files = {"a.py": "X = 'DEFINE \"my-table$1\"'\nY = 'INSERT INTO my-table$1 VALUES (1)'\n"}
    facts = facts_of(tmp_path, files, toml)
    assert facts.created == {"my-table$1"}
    assert facts.writers == {"my-table$1": {"a"}}


def test_routes_are_collected_per_module(tmp_path):
    files = {"web.py": "@app.route('/a')\ndef a(): pass\n@app.route('/b')\ndef b(): pass\n", "x.py": ""}
    assert facts_of(tmp_path, files).routes == {"web": ["/a", "/b"]}


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import sqlite3\nq = 'SELECT 1'\n", "db-r"),
        ("import sqlite3\nq = 'INSERT INTO t VALUES (1)'\n", "db-rw"),
        ("import sqlite3\nq = f'UPDATE {t} SET a = 1'\n", "db-rw"),
        ("import sqlalchemy\ndf.to_sql('t', con)\n", "db-rw"),
        ("import requests\n", "network"),
        ("import urllib.parse\n", ""),
        ("from urllib import parse\n", ""),
        ("from urllib import request\n", "network"),
        ("import urllib.request\n", "network"),
        ("from urllib.request import urlopen\n", "network"),
        ("import flask\n", "http"),
        ("import sqlite3, requests\nfrom flask import Flask\n", "db-r+network+http"),
        ("q = 'INSERT INTO t VALUES (1)'\n", ""),
        ("from . import sqlite3\n", ""),
        ("import sqlite3\ndef broken(:\n", ""),
    ],
)
def test_io_rating(tmp_path, source, expected):
    assert facts_of(tmp_path, {"m.py": source}).io["m"] == expected


def test_io_lists_are_replaced_per_kind_by_config(tmp_path):
    toml = '[io]\nnetwork = ["mylib"]\n'
    facts = facts_of(tmp_path, {"a.py": "import mylib\n", "b.py": "import requests\n", "c.py": "import sqlite3\n"}, toml)
    assert (facts.io["a"], facts.io["b"], facts.io["c"]) == ("network", "", "db-r")
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_facts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indextool.facts'`.

- [ ] **Step 3: Implement**

`src/indextool/facts.py`:

```python
"""Facts a regex or a decorator can read out of the source with no model in the loop."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import TABLES_TOKEN, Config
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
        use = [re.compile(t.replace(TABLES_TOKEN, alternation), re.IGNORECASE) for t in cfg.sql.use]
        write = [re.compile(t.replace(TABLES_TOKEN, alternation), re.IGNORECASE) for t in cfg.sql.write]
        for key, text in texts.items():
            for rx in use:
                for found in set(rx.findall(text)):
                    facts.tables.setdefault(canon[found.lower()], set()).add(key)
            for rx in write:
                for found in set(rx.findall(text)):
                    facts.writers.setdefault(canon[found.lower()], set()).add(key)
    return facts
```

- [ ] **Step 4: Run to see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_facts.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/indextool/facts.py tests/test_facts.py
git commit -q -m "feat: derive tables, writers, routes and IO ratings" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Render the architecture map and the module index

**Files:**
- Create: `src/indextool/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `scan.Module` (Task 6), `graph.*` (Task 7), `facts.Facts` (Task 8), `config.Config` (`title`, `exclude`, `route_decorators`, `sql.is_default`; Task 5), `indextool.FORMAT_VERSION` (Task 1).
- Produces (`render`): `render_architecture(mods: dict[str, Module], facts: Facts, cfg: Config, excluded: int) -> str` and `render_index(mods: dict[str, Module], facts: Facts, cfg: Config) -> str`. Both return text without a trailing newline (the output layer adds exactly one). Cap constants `CAP_PACKAGES = CAP_HUBS = CAP_TABLES = CAP_ROUTE_GROUPS = CAP_ROUTE_FILES = 25`, `CAP_CYCLES = 10`, `CAP_DUPLICATES = 20`, `NAMES_PER_DEPTH = 6`, `NAMES_PER_CYCLE = 8`, `WRITERS_NAMED = 4`, `READERS_NAMED = 4`.

Layout (spec 6.2): the map's sections in order are numbers, packages, dependency layers, import cycles, most depended-on modules, HTTP surface, database, same name in different modules (only when there are any), what this map cannot say. Spec 4 rule 6 says every list has a cap and a "(+N more)" line, but the spec's cap list (6.1) omitted three lists. The reference did not cap the package list or the route-file list, and did not add a "(+N more)" line to the hubs list. This plan caps packages and route files at 25 and adds the line to the hubs list; the spec was updated to record these (6.1 and delta 10 in 6.2). Reference outputs with fewer than 25 entries are unaffected.

- [ ] **Step 1: Write the failing tests**

`tests/test_render.py`:

```python
from indextool import FORMAT_VERSION
from indextool.facts import derive_facts
from indextool.render import render_architecture, render_index
from indextool.scan import resolve_edges, scan
from tests.helpers import make_config

SHOP = {
    "shop/__init__.py": '"""Shop package."""\n',
    "shop/ledger.py": (
        '"""Ledger of money movements."""\nimport sqlite3\n\nSCHEMA = "CREATE TABLE ledger (id INTEGER)"\n\n\n'
        "class Money:\n    pass\n"
    ),
    "shop/orders.py": (
        '"""Order handling."""\nimport sqlite3\nfrom shop import ledger\n\nSQL = "CREATE TABLE orders (id INTEGER)"\n'
        'INSERT = "INSERT INTO orders VALUES (1)"\n\n\nclass Money:\n    pass\n'
    ),
    "shop/web.py": (
        '"""HTTP routes."""\nfrom flask import Flask\nfrom shop import orders\n\napp = Flask(__name__)\n\n\n'
        '@app.route("/orders")\ndef list_orders():\n    return orders\n\n\n'
        '@app.route("/orders/<int:id>")\ndef show(id):\n    return id\n'
    ),
    "shop/cycle_a.py": "from shop import cycle_b\n",
    "shop/cycle_b.py": "from shop import cycle_a\n",
    "scripts/report.py": '"""Print a report."""\nfrom shop import orders\n\nif __name__ == "__main__":\n    print(orders)\n',
    "tests/test_orders.py": "from shop import orders\n",
}


def render_pair(directory, files, toml="", excluded=0):
    cfg = make_config(directory, toml)
    mods = scan({p: c.encode("utf-8") for p, c in files.items()}, cfg)
    resolve_edges(mods)
    facts = derive_facts(mods, cfg)
    return render_architecture(mods, facts, cfg, excluded), render_index(mods, facts, cfg)


def test_header_and_numbers(tmp_path):
    arch, _ = render_pair(tmp_path, SHOP)
    lines = arch.split("\n")
    assert lines[0] == "# Architecture map"
    assert f"indextool {FORMAT_VERSION}" in "\n".join(lines[:3])
    assert "- 7 modules (plus 1 test module) in 2 packages; 1 with a `__main__` guard" in lines
    assert "- 5 are imported by another module; 2 standalone (imported by nothing: scripts, servers, entry points)" in lines
    assert "- 2 routes in 1 file; 2 tables created in code" in lines


def test_title_from_config(tmp_path):
    arch, _ = render_pair(tmp_path, SHOP, 'title = "Acme shop"\n')
    assert arch.split("\n")[0] == "# Architecture map: Acme shop"


def test_packages_layers_cycles_hubs_and_lookalikes(tmp_path):
    arch, _ = render_pair(tmp_path, SHOP)
    lines = arch.split("\n")
    assert "- `scripts` - 1 module" in lines and "- `shop` - 5 modules" in lines and "- top level - 1 module" in lines
    assert "- depth 0 (2 modules): `shop`, `shop.ledger`" in lines
    assert "- depth 1 (3 modules): `shop.orders`, `shop.cycle_a`, `shop.cycle_b`" in lines
    assert "- `shop.cycle_a`, `shop.cycle_b` (2 modules)" in lines
    assert "- `shop` (5 importers) - Shop package." in lines
    assert "- class `Money`: `shop.ledger`, `shop.orders`" in lines


def test_http_surface_and_database(tmp_path):
    arch, _ = render_pair(tmp_path, SHOP)
    lines = arch.split("\n")
    assert "2 routes in 1 file: `shop.web` (2)." in lines
    assert "- `/orders` - 1 route" in lines and "- `/orders/<int:id>` - 1 route" in lines
    assert "- `ledger` - 1 module (1 library, 0 standalone); written by `shop.ledger`" in lines
    assert "- `orders` - 1 module (1 library, 0 standalone); written by `shop.orders`" in lines


def test_index_lines(tmp_path):
    _, index = render_pair(tmp_path, SHOP)
    lines = index.split("\n")
    assert lines[0].startswith(f"# indextool {FORMAT_VERSION} index, one line per module")
    assert lines[1:] == [
        "scripts.report | Print a report. | standalone",
        "shop | Shop package. | lib",
        "shop.cycle_a | - | lib",
        "shop.cycle_b | - | lib",
        "shop.ledger | Ledger of money movements. | lib db-rw | tables: ledger*",
        "shop.orders | Order handling. | lib db-rw | tables: orders*",
        "shop.web | HTTP routes. | standalone http | routes 2",
    ]


def test_lists_are_capped_with_a_more_line(tmp_path):
    files = {f"t/hub{i:02d}.py": "" for i in range(30)}
    files["t/user.py"] = "".join(f"import t.hub{i:02d}\n" for i in range(30))
    arch, _ = render_pair(tmp_path, files)
    hubs = arch.split("## Most depended-on modules\n")[1].split("\n\n")[0].split("\n")
    assert len(hubs) == 26 and hubs[-1] == "- (+5 more)"


def test_an_empty_repository_renders_a_valid_map(tmp_path):
    arch, index = render_pair(tmp_path, {})
    assert "- 0 modules (plus 0 test modules) in 0 packages; 0 with a `__main__` guard" in arch
    assert arch.count("None found by this detector.") == 2
    assert index.split("\n") == [index.split("\n")[0]]


def test_detector_lines_and_cannot_say_reflect_the_config(tmp_path):
    custom, _ = render_pair(tmp_path / "a", SHOP, '[routes]\ndecorators = ["route"]\n')
    assert "Detector: functions decorated with `.route(...)`" in custom
    assert "Routes not registered by a decorator named `route`" in custom
    default, _ = render_pair(tmp_path / "b", SHOP)
    assert "`.route(...)`, `.get(...)`" in default
    assert "Detector: `CREATE TABLE` statements" in default
    custom_sql, _ = render_pair(tmp_path / "c", SHOP, "[sql]\ncreate = ['CREATE TABLE (\\w+)']\n")
    assert "Detector: custom SQL patterns from the configuration" in custom_sql


def test_counts_of_excluded_and_unparsable_files_are_printed(tmp_path):
    arch, _ = render_pair(tmp_path, {"a.py": "x = 1\n", "b.py": "def broken(:\n"}, 'exclude = ["legacy/"]\n', excluded=3)
    assert "- 3 files excluded by the configured `exclude` patterns" in arch
    assert "- 1 file could not be parsed (counted as a module with no imports)" in arch
    plain, _ = render_pair(tmp_path / "plain", {"a.py": "x = 1\n"})
    assert "excluded by the configured" not in plain and "could not be parsed" not in plain


def test_output_does_not_depend_on_input_order(tmp_path):
    first = render_pair(tmp_path / "a", SHOP)
    second = render_pair(tmp_path / "b", dict(reversed(list(SHOP.items()))))
    assert first == second
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indextool.render'`.

- [ ] **Step 3: Implement**

`src/indextool/render.py`:

```python
"""Render the architecture map and the module index. Pure functions: no I/O."""
from __future__ import annotations

from . import FORMAT_VERSION
from .config import Config
from .facts import Facts
from .graph import compute_depths, find_cycles, find_duplicate_names, importers, library_modules
from .scan import Module

CAP_PACKAGES = 25
CAP_HUBS = 25
CAP_TABLES = 25
CAP_ROUTE_GROUPS = 25
CAP_ROUTE_FILES = 25
CAP_CYCLES = 10
CAP_DUPLICATES = 20
NAMES_PER_DEPTH = 6
NAMES_PER_CYCLE = 8
WRITERS_NAMED = 4
READERS_NAMED = 4
TITLE_WIDTH = 70
INDEX_TITLE_WIDTH = 90
NONE_FOUND = "None found by this detector."


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {many or word + 's'}"


def _names(keys, limit: int) -> str:
    keys = list(keys)
    shown = ", ".join(f"`{k}`" for k in keys[:limit])
    return shown + (f", +{len(keys) - limit}" if len(keys) > limit else "")


def _title(mod: Module) -> str:
    return mod.doc.strip()[:TITLE_WIDTH]


def _route_detector(cfg: Config) -> str:
    listed = ", ".join(f"`.{d}(...)`" for d in cfg.route_decorators) or "nothing (no decorators are configured)"
    return f"Detector: functions decorated with {listed} whose first argument is a string literal starting with `/`."


def _sql_detector(cfg: Config) -> str:
    if cfg.sql.is_default:
        return (
            "Detector: `CREATE TABLE` statements (including `CREATE VIRTUAL TABLE`) found in string literals; temporary "
            "tables and schema-qualified names are not counted. Uses and writes are matched against those names."
        )
    return (
        "Detector: custom SQL patterns from the configuration; uses and writes are matched against the names they find."
    )


def render_architecture(mods: dict[str, Module], facts: Facts, cfg: Config, excluded: int) -> str:
    real = sorted((m for m in mods.values() if not m.is_test), key=lambda m: m.key)
    n_tests = sum(1 for m in mods.values() if m.is_test)
    n_unparsed = sum(1 for m in mods.values() if m.parse_error)
    imp = importers(mods)
    library = library_modules(mods)
    packages: dict[str | None, list[str]] = {}
    for m in real:
        packages.setdefault(m.key.split(".")[0] if "." in m.key else None, []).append(m.key)
    named = {k: v for k, v in packages.items() if k is not None}
    n_routes = sum(len(v) for v in facts.routes.values())

    out = [
        f"# Architecture map: {cfg.title}" if cfg.title else "# Architecture map",
        "",
        f"Generated by indextool {FORMAT_VERSION} from the source code. Everything below is read from the source and "
        "regenerated, never edited by hand, so it cannot go stale and needs no upkeep.",
        "",
        "## In numbers",
        f"- {_plural(len(real), 'module')} (plus {_plural(n_tests, 'test module')}) in {_plural(len(named), 'package')}; "
        f"{sum(1 for m in real if m.has_main)} with a `__main__` guard",
        f"- {len(library)} {'is' if len(library) == 1 else 'are'} imported by another module; "
        f"{len(real) - len(library)} standalone (imported by nothing: scripts, servers, entry points)",
        f"- {_plural(n_routes, 'route')} in {_plural(len(facts.routes), 'file')}; "
        f"{_plural(len(facts.created), 'table')} created in code",
    ]
    if cfg.exclude.patterns:
        out.append(f"- {_plural(excluded, 'file')} excluded by the configured `exclude` patterns")
    if n_unparsed:
        out.append(
            f"- {_plural(n_unparsed, 'file')} could not be parsed "
            f"(counted as {'a module' if n_unparsed == 1 else 'modules'} with no imports)"
        )
    out.append("")

    out.append("## Packages")
    ranked_packages = sorted(named.items())
    out += [f"- `{name}` - {_plural(len(keys), 'module')}" for name, keys in ranked_packages[:CAP_PACKAGES]]
    if len(ranked_packages) > CAP_PACKAGES:
        out.append(f"- (+{len(ranked_packages) - CAP_PACKAGES} more packages)")
    out.append(f"- top level - {_plural(len(packages.get(None, [])), 'module')}")
    out.append("")

    depths = compute_depths(mods)
    levels: dict[int, list[str]] = {}
    for key in library:
        levels.setdefault(depths[key], []).append(key)
    out += [
        "## Dependency layers (computed from imports)",
        "Library modules only. Depth 0 imports no other module here; depth N is one more than the deepest module it "
        "imports; modules in an import cycle share a depth. The most imported modules at each depth:",
    ]
    for depth in sorted(levels):
        members = sorted(levels[depth], key=lambda k: (-len(imp[k]), k))
        out.append(f"- depth {depth} ({_plural(len(members), 'module')}): " + _names(members, NAMES_PER_DEPTH))
    out.append("")

    cycles = [[k for k in comp if not mods[k].is_test] for comp in find_cycles(mods)]
    cycles = [c for c in cycles if len(c) > 1]
    out.append("## Import cycles")
    if cycles:
        out.append("Modules that import each other, directly or through others; change them together.")
        out += [f"- {_names(c, NAMES_PER_CYCLE)} ({_plural(len(c), 'module')})" for c in cycles[:CAP_CYCLES]]
        if len(cycles) > CAP_CYCLES:
            out.append(f"- (+{len(cycles) - CAP_CYCLES} more cycles)")
    else:
        out.append("None.")
    out.append("")

    hubs = sorted((m for m in real if imp[m.key]), key=lambda m: (-len(imp[m.key]), m.key))
    out.append("## Most depended-on modules")
    for m in hubs[:CAP_HUBS]:
        out.append(f"- `{m.key}` ({_plural(len(imp[m.key]), 'importer')})" + (f" - {_title(m)}" if m.doc.strip() else ""))
    if len(hubs) > CAP_HUBS:
        out.append(f"- (+{len(hubs) - CAP_HUBS} more)")
    out.append("")

    out += ["## HTTP surface", _route_detector(cfg)]
    if n_routes:
        route_files = sorted(facts.routes.items())
        shown = ", ".join(f"`{k}` ({len(v)})" for k, v in route_files[:CAP_ROUTE_FILES])
        if len(route_files) > CAP_ROUTE_FILES:
            shown += f", +{len(route_files) - CAP_ROUTE_FILES}"
        out.append(f"{_plural(n_routes, 'route')} in {_plural(len(route_files), 'file')}: {shown}.")
        groups: dict[str, int] = {}
        for paths in facts.routes.values():
            for path in paths:
                prefix = "/" + "/".join(path.strip("/").split("/")[:3])
                groups[prefix] = groups.get(prefix, 0) + 1
        ranked = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))
        out += [f"- `{prefix}` - {_plural(n, 'route')}" for prefix, n in ranked[:CAP_ROUTE_GROUPS]]
        if len(ranked) > CAP_ROUTE_GROUPS:
            out.append(f"- (+{len(ranked) - CAP_ROUTE_GROUPS} more route groups)")
    else:
        out.append(NONE_FOUND)
    out.append("")

    out += ["## Database", _sql_detector(cfg)]
    if facts.created:
        out.append(
            f"{_plural(len(facts.created), 'table')} created in code (tables that exist only in the database file are not "
            "counted). Ranked by how many library modules use them; standalone scripts are counted but named last:"
        )

        def by_role(keys):
            return sorted(keys, key=lambda k: (k not in library, -len(imp.get(k, ())), k))

        ranked_tables = sorted(
            facts.tables.items(),
            key=lambda kv: (-len([k for k in kv[1] if k in library]), -len(kv[1]), kv[0]),
        )
        for name, keys in ranked_tables[:CAP_TABLES]:
            writers = facts.writers.get(name, set())
            line = (
                f"- `{name}` - {_plural(len(keys), 'module')} ({len([k for k in keys if k in library])} library, "
                f"{len([k for k in keys if k not in library])} standalone)"
            )
            if writers:
                line += "; written by " + _names(by_role(writers), WRITERS_NAMED)
            readers = [k for k in by_role(keys - writers) if k in library]
            if readers:
                line += "; also used by " + _names(readers, READERS_NAMED)
            out.append(line)
        if len(ranked_tables) > CAP_TABLES:
            out.append(f"- (+{len(ranked_tables) - CAP_TABLES} more tables)")
    else:
        out.append(NONE_FOUND)
    out.append("")

    same = find_duplicate_names(mods)
    if same:
        out += [
            "## Same name, different modules",
            "Defined in two or more library modules. Check which one a piece of code really imports before you edit or "
            "cite it.",
        ]
        out += [f"- {kind} `{name}`: {_names(keys, NAMES_PER_CYCLE)}" for kind, name, keys in same[:CAP_DUPLICATES]]
        if len(same) > CAP_DUPLICATES:
            out.append(f"- (+{len(same) - CAP_DUPLICATES} more)")
        out.append("")

    decorators = ", ".join(f"`{d}`" for d in cfg.route_decorators) or "(none configured)"
    out += [
        "## What this map cannot say",
        "- Why a module exists or how modules cooperate beyond importing each other: titles are the first line of each "
        "docstring.",
        "- Formulas, thresholds, ordering of the data flow, and the reasons behind design rules.",
        "- Imports made through `importlib`, `exec` or `sys.path` changes, and anything outside Python source files.",
        "- Tables that no `CREATE TABLE` statement in a string literal creates (created outside the code, by an ORM, or "
        "under a name built at run time).",
        f"- Routes not registered by a decorator named {decorators} with a literal path starting with `/`.",
    ]
    return "\n".join(out)


def render_index(mods: dict[str, Module], facts: Facts, cfg: Config) -> str:
    library = library_modules(mods)
    per_module: dict[str, list[str]] = {}
    for table, keys in facts.tables.items():
        for key in keys:
            per_module.setdefault(key, []).append(table)
    lines = [
        f"# indextool {FORMAT_VERSION} index, one line per module, fields split by a pipe: key, first docstring line, "
        "role, tables, routes. Role: `lib` (another module imports it) or `standalone` (nothing does), then the io the "
        "code shows. Tables ending in * are ones the module writes."
    ]
    for m in sorted((m for m in mods.values() if not m.is_test), key=lambda m: m.key):
        role = " ".join(p for p in ("lib" if m.key in library else "standalone", facts.io.get(m.key, "")) if p)
        cells = [m.key, m.doc.strip()[:INDEX_TITLE_WIDTH] or "-", role]
        tables = sorted(per_module.get(m.key, []))
        if tables:
            cells.append(
                "tables: " + ", ".join(t + ("*" if m.key in facts.writers.get(t, ()) else "") for t in tables)
            )
        if facts.routes.get(m.key):
            cells.append(f"routes {len(facts.routes[m.key])}")
        lines.append(" | ".join(cells))
    return "\n".join(lines)
```

- [ ] **Step 4: Run to see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_render.py -v`
Expected: all pass. If `test_packages_layers_cycles_hubs_and_lookalikes` fails on the depth lines, print the map (`print(arch)` in the test) and check the members' importer counts before changing the expected strings: `shop.orders` has two non-test importers (`shop.web`, `scripts.report`) and the cycle modules one each.

- [ ] **Step 5: Run the whole suite and commit**

Run: `.venv/Scripts/python -m pytest -q`
Expected: everything so far passes.

```bash
git add src/indextool/render.py tests/test_render.py
git commit -q -m "feat: render the architecture map and module index" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 10: Output layer, pipeline and the `generate` command

**Files:**
- Create: `src/indextool/output.py`, `src/indextool/pipeline.py`, `src/indextool/cli.py`, `src/indextool/__main__.py`, `tests/fixture_repos.py`
- Modify: `tests/helpers.py` (append `Result`, `run_cli`)
- Test: `tests/test_output.py`, `tests/test_cli_generate.py`

**Interfaces:**
- Consumes: `sources.read_file`, `sources.discover` (Task 4); `config.load_config`, `Config` (Task 5); `scan.scan`, `scan.resolve_edges` (Task 6); `facts.derive_facts` (Task 8); `render.render_architecture`, `render.render_index` (Task 9).
- Produces (`output`): `expected_text(text: str) -> str` (exactly one trailing `\n`); `normalize_newlines(text: str) -> str` (`\r\n` and `\r` become `\n`); `write_atomic(path: Path, text: str) -> None` (creates parents, writes UTF-8 bytes to a temporary sibling, then `os.replace`); `read_committed(base: Path, rel: str, source: str) -> str | None` (decoded UTF-8, newline-normalized; `None` when missing); `compare(actual: str | None, wanted: str) -> str` returning `"missing"`, `"current"` or `"stale"`; `changed_lines(actual: str, wanted: str) -> list[str]` (the added and removed lines of a zero-context unified diff, without headers).
- Produces (`pipeline`): `Built(architecture: str, index: str, py_files: tuple[str, ...], module_count: int, unparsable: int, excluded: int)` (frozen dataclass; `py_files` are the discovered base-relative paths, sorted; `module_count` counts every module including tests); `build_from_files(files: dict[str, bytes], cfg: Config, excluded: int = 0) -> Built`; `build(cfg: Config, source: str) -> Built`; `sync_files(cfg: Config, source: str, built: Built | None = None) -> list[tuple[str, str, int]]` which writes each output only when its content differs from what is on disk and returns `(rel, action, chars)` with `action` in `"created"`, `"updated"`, `"unchanged"`.
- Produces (`cli`): `main(argv: list[str] | None = None) -> int`, with only the `generate` command so far (`--config PATH`, `--source worktree|index`). Exit 0 success, 2 misconfiguration.
- Produces (`tests/helpers.py`): `Result(code: int, out: str, err: str)` and `run_cli(cwd: Path, *args: str, env: dict | None = None) -> Result` running `python -m indextool` in `cwd`.
- Produces (`tests/fixture_repos.py`): `TINY: dict[str, str]`, a four-file synthetic repository.

- [ ] **Step 1: Append the CLI test helper and create the small fixture**

Append to `tests/helpers.py` (add `import os` and `import sys` to the imports at the top of the file, and `from dataclasses import dataclass`):

```python
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
```

`tests/fixture_repos.py`:

```python
"""Synthetic repositories used by the command-line tests. Invented names only."""

TINY = {
    "shop/__init__.py": '"""Shop package."""\n',
    "shop/ledger.py": '"""Ledger of money movements."""\nimport sqlite3\n\nSCHEMA = "CREATE TABLE ledger (id INTEGER)"\n',
    "shop/orders.py": '"""Order handling."""\nfrom shop import ledger\n',
    "scripts/report.py": '"""Print a report."""\nfrom shop import orders\n\nif __name__ == "__main__":\n    print(orders)\n',
}
```

- [ ] **Step 2: Write the failing output tests**

`tests/test_output.py`:

```python
from indextool import output


def test_expected_text_ends_with_exactly_one_newline():
    assert output.expected_text("a\nb") == "a\nb\n"
    assert output.expected_text("a\nb\n\n\n") == "a\nb\n"


def test_normalize_newlines():
    assert output.normalize_newlines("a\r\nb\rc\n") == "a\nb\nc\n"


def test_write_atomic_creates_parents_writes_utf8_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "docs" / "deep" / "map.md"
    output.write_atomic(target, "café\n")
    assert target.read_bytes() == "café\n".encode("utf-8")
    assert [p.name for p in target.parent.iterdir()] == ["map.md"]


def test_compare_states():
    assert output.compare(None, "x\n") == "missing"
    assert output.compare("x\n", "x\n") == "current"
    assert output.compare("x\n", "y\n") == "stale"


def test_changed_lines_are_only_the_added_and_removed_lines():
    lines = output.changed_lines("a\nold\nc\n", "a\nnew\nc\n")
    assert lines == ["-old", "+new"]
    assert output.changed_lines("same\n", "same\n") == []


def test_a_removed_rule_line_is_not_mistaken_for_a_diff_header():
    assert output.changed_lines("--- rule\nx\n", "x\n") == ["---- rule"]


def test_read_committed_normalizes_crlf_and_reports_missing(tmp_path):
    (tmp_path / "map.md").write_bytes(b"a\r\nb\r\n")
    assert output.read_committed(tmp_path, "map.md", "worktree") == "a\nb\n"
    assert output.read_committed(tmp_path, "nope.md", "worktree") is None
```

- [ ] **Step 3: Run to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_output.py -v`
Expected: FAIL with `ImportError` (cannot import name `output`).

- [ ] **Step 4: Implement `output.py`**

`src/indextool/output.py`:

```python
"""Write and compare the generated files."""
from __future__ import annotations

import difflib
import os
from pathlib import Path

from .sources import read_file


def expected_text(text: str) -> str:
    return text.rstrip("\n") + "\n"


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(text.encode("utf-8"))
    os.replace(temporary, path)


def read_committed(base: Path, rel: str, source: str) -> str | None:
    data = read_file(base, rel, source)
    if data is None:
        return None
    return normalize_newlines(data.decode("utf-8", errors="replace"))


def compare(actual: str | None, wanted: str) -> str:
    if actual is None:
        return "missing"
    return "current" if actual == wanted else "stale"


def changed_lines(actual: str, wanted: str) -> list[str]:
    lines = list(difflib.unified_diff(actual.split("\n"), wanted.split("\n"), lineterm="", n=0))
    return [line for line in lines[2:] if not line.startswith("@@")]
```

- [ ] **Step 5: Run to see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_output.py -v`
Expected: all pass.

- [ ] **Step 6: Write the failing `generate` tests**

`tests/test_cli_generate.py`:

```python
from tests.fixture_repos import TINY
from tests.helpers import git, run_cli


def test_generate_writes_both_files_and_reports(repo_factory):
    repo = repo_factory(TINY)
    result = run_cli(repo, "generate")
    assert result.code == 0, result.err
    assert "wrote docs/architecture.md" in result.out and "wrote docs/architecture.index.txt" in result.out
    arch = (repo / "docs" / "architecture.md").read_bytes()
    assert arch.startswith(b"# Architecture map") and arch.endswith(b"\n") and not arch.endswith(b"\n\n")
    assert b"\r" not in arch
    assert (repo / "docs" / "architecture.index.txt").read_text(encoding="utf-8").startswith("# indextool ")


def test_generate_twice_is_byte_identical_and_reports_unchanged(repo_factory):
    repo = repo_factory(TINY)
    run_cli(repo, "generate")
    first = {p: (repo / p).read_bytes() for p in ("docs/architecture.md", "docs/architecture.index.txt")}
    again = run_cli(repo, "generate")
    assert again.code == 0 and "unchanged" in again.out and "wrote" not in again.out
    assert first == {p: (repo / p).read_bytes() for p in first}


def test_generate_from_a_subdirectory_writes_at_the_repository_base(repo_factory):
    repo = repo_factory(TINY)
    assert run_cli(repo / "shop", "generate").code == 0
    assert (repo / "docs" / "architecture.md").is_file()


def test_an_empty_repository_gets_a_valid_empty_map(repo_factory):
    repo = repo_factory({"README.md": "hello\n"})
    result = run_cli(repo, "generate")
    assert result.code == 0, result.err
    assert "- 0 modules (plus 0 test modules)" in (repo / "docs" / "architecture.md").read_text(encoding="utf-8")


def test_a_repository_with_no_commits_uses_staged_files(repo_factory):
    repo = repo_factory(TINY, commit=False)
    git(repo, "add", "-A")
    assert run_cli(repo, "generate", "--source", "index").code == 0
    assert "`shop.ledger`" in (repo / "docs" / "architecture.md").read_text(encoding="utf-8")


def test_non_ascii_names_are_written_as_utf8_and_survive_a_narrow_console(repo_factory):
    repo = repo_factory({"café/naïve.py": '"""Crème brûlée."""\n'})
    result = run_cli(repo, "generate", env={"PYTHONIOENCODING": "ascii"})
    assert result.code == 0, result.err
    index = (repo / "docs" / "architecture.index.txt").read_text(encoding="utf-8")
    assert "café.naïve | Crème brûlée. | standalone" in index


def test_generate_warns_about_an_untracked_config(repo_factory):
    repo = repo_factory(TINY)
    (repo / "indextool.toml").write_text('title = "Shop"\n', encoding="utf-8")
    result = run_cli(repo, "generate")
    assert result.code == 0 and "indextool.toml is not tracked by git" in result.err
    assert "# Architecture map: Shop" in (repo / "docs" / "architecture.md").read_text(encoding="utf-8")


def test_generate_reports_config_errors_with_exit_code_2(repo_factory):
    repo = repo_factory({**TINY, "indextool.toml": "titel = 'x'\n"})
    result = run_cli(repo, "generate")
    assert result.code == 2 and "unknown key 'titel'" in result.err
    assert not (repo / "docs").exists()


def test_generate_honours_config_paths_and_roots(repo_factory):
    files = {"src/shop/__init__.py": "", "src/shop/a.py": "", "other/x.py": ""}
    toml = 'roots = ["src"]\narchitecture = "maps/arch.md"\nindex = "maps/idx.txt"\n'
    repo = repo_factory({**files, "indextool.toml": toml})
    result = run_cli(repo, "generate")
    assert result.code == 0, result.err
    arch = (repo / "maps" / "arch.md").read_text(encoding="utf-8")
    assert "- 2 modules" in arch and "other.x" not in arch
```

- [ ] **Step 7: Run to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_cli_generate.py -v`
Expected: FAIL (`No module named indextool.__main__`, so every test reports a non-zero exit).

- [ ] **Step 8: Implement the pipeline, the CLI and `__main__`**

`src/indextool/pipeline.py`:

```python
"""Wire scan, graph, facts and render together, and write the results."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Config
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
            write_atomic(cfg.base / rel, wanted)
        results.append((rel, {"missing": "created", "stale": "updated", "current": "unchanged"}[state], len(wanted)))
    return results
```

`src/indextool/cli.py`:

```python
"""Command line: argument parsing, exit codes, and nothing else."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import gitio
from .config import load_config
from .errors import ConfigError
from .pipeline import sync_files


def _warn(message: str) -> None:
    print(f"indextool: {message}", file=sys.stderr)


def _generate(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(Path.cwd(), args.config, args.source)
        if cfg.config_untracked:
            _warn(f"{cfg.config_file.name} is not tracked by git; CI will not see it (git add it)")
        for rel, action, size in sync_files(cfg, args.source):
            if action == "unchanged":
                print(f"indextool: {rel} is unchanged")
            else:
                print(f"indextool: wrote {rel} ({size:,} chars)")
    except (ConfigError, gitio.GitError) as exc:
        _warn(str(exc))
        return 2
    return 0


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config", type=Path, default=None, help="path to indextool.toml, or a pyproject.toml with [tool.indextool]"
    )
    common.add_argument(
        "--source",
        choices=("worktree", "index"),
        default="worktree",
        help="read files from the working tree (default) or from the git index",
    )
    parser = argparse.ArgumentParser(
        prog="indextool", description="Derive an architecture map from a Python repository and verify it in CI."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", parents=[common], help="write the architecture map and the module index")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    args = _parser().parse_args(argv)
    return {"generate": _generate}[args.command](args)
```

`src/indextool/__main__.py`:

```python
from .cli import main

raise SystemExit(main())
```

- [ ] **Step 9: Run to see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_output.py tests/test_cli_generate.py -v`
Expected: all pass. If `test_non_ascii_names_are_written_as_utf8_and_survive_a_narrow_console` fails with a `UnicodeEncodeError` in stderr, the stream reconfiguration in `main` did not run before the first `print`; confirm `main` reconfigures both streams before parsing arguments.

- [ ] **Step 10: Commit**

```bash
git add src/indextool/output.py src/indextool/pipeline.py src/indextool/cli.py src/indextool/__main__.py tests/helpers.py tests/fixture_repos.py tests/test_output.py tests/test_cli_generate.py
git commit -q -m "feat: output layer, pipeline and the generate command" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 11: The `verify` and `refresh` commands

**Files:**
- Modify: `src/indextool/cli.py`
- Test: `tests/test_cli_verify_refresh.py`

**Interfaces:**
- Consumes: everything from Tasks 1 to 10 (`pipeline.build`, `pipeline.sync_files`, `output.*`, `config.load_config`, `gitio.unstaged`, `indextool.__version__`).
- Produces (`cli`): two more commands sharing `--config` and `--source`. `verify`: exit 0 when both files are current, 1 on drift, 2 on misconfiguration (invalid or untracked config, key collision, unmerged paths); prints `indextool: <rel> is current`, or `... is out of date; regenerate it with: indextool generate`, or `... does not exist; write it with: indextool generate`; on drift prints at most 12 changed lines, then `... (N more changed lines)`, then `indextool <version>, Python <major>.<minor>`, and, when files failed to parse, a hint that CI and local Python versions must match; in worktree mode it warns on stderr when tracked `.py` files or the config have unstaged changes. `refresh`: prints nothing to stdout, always exits 0, reports problems as one line on stderr, writes only when content changed, and writes nothing when no Python module is found.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli_verify_refresh.py`:

```python
import os

from tests.fixture_repos import TINY
from tests.helpers import commit_all, git, run_cli

MAPS = ("docs/architecture.md", "docs/architecture.index.txt")


def committed_repo(repo_factory, files=None):
    repo = repo_factory(files or TINY)
    assert run_cli(repo, "generate").code == 0
    commit_all(repo, "add maps")
    return repo


def test_verify_passes_after_generate(repo_factory):
    repo = committed_repo(repo_factory)
    result = run_cli(repo, "verify")
    assert result.code == 0, result.out + result.err
    assert result.out.count("is current") == 2


def test_verify_fails_when_an_import_changes_and_says_how_to_fix_it(repo_factory):
    repo = committed_repo(repo_factory)
    report = repo / "scripts" / "report.py"
    report.write_text(report.read_text(encoding="utf-8") + "import shop.ledger\n", encoding="utf-8")
    result = run_cli(repo, "verify")
    assert result.code == 1
    assert "docs/architecture.md is out of date; regenerate it with: indextool generate" in result.out
    assert "indextool 0.1.0, Python " in result.out
    assert any(line.startswith(("-", "+")) for line in result.out.split("\n"))


def test_verify_says_a_missing_map_does_not_exist(repo_factory):
    repo = committed_repo(repo_factory)
    (repo / "docs" / "architecture.md").unlink()
    result = run_cli(repo, "verify")
    assert result.code == 1
    assert "docs/architecture.md does not exist; write it with: indextool generate" in result.out


def test_verify_accepts_crlf_line_endings_in_the_committed_map(repo_factory):
    repo = committed_repo(repo_factory)
    for rel in MAPS:
        path = repo / rel
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert run_cli(repo, "verify").code == 0


def test_verify_names_an_untracked_config_and_exits_2(repo_factory):
    repo = committed_repo(repo_factory)
    (repo / "indextool.toml").write_text('title = "Shop"\n', encoding="utf-8")
    result = run_cli(repo, "verify")
    assert result.code == 2 and "indextool.toml is not tracked by git" in result.err


def test_verify_rejects_a_config_outside_the_repository(repo_factory, tmp_path):
    repo = committed_repo(repo_factory)
    outside = tmp_path / "elsewhere.toml"
    outside.write_text('title = "x"\n', encoding="utf-8")
    result = run_cli(repo, "verify", "--config", str(outside))
    assert result.code == 2 and "outside the repository" in result.err


def test_index_source_checks_what_would_be_committed(repo_factory):
    repo = committed_repo(repo_factory)
    ledger = repo / "shop" / "ledger.py"
    ledger.write_text(ledger.read_text(encoding="utf-8") + "import shop.orders\n", encoding="utf-8")
    assert run_cli(repo, "generate").code == 0  # the working-tree map now matches the edited code
    git(repo, "add", "shop/ledger.py")  # the code change is staged, the map is not
    assert run_cli(repo, "verify").code == 0
    result = run_cli(repo, "verify", "--source", "index")
    assert result.code == 1 and "indextool generate --source index" in result.out
    git(repo, "add", "docs")
    assert run_cli(repo, "verify", "--source", "index").code == 0


def test_an_unstaged_edit_warns_in_worktree_mode(repo_factory):
    repo = committed_repo(repo_factory)
    ledger = repo / "shop" / "ledger.py"
    ledger.write_text(ledger.read_text(encoding="utf-8") + "import shop.orders\n", encoding="utf-8")
    run_cli(repo, "generate")
    result = run_cli(repo, "verify")
    assert result.code == 0
    assert "unstaged changes" in result.err and "shop/ledger.py" in result.err


def test_verify_works_from_a_subdirectory(repo_factory):
    repo = committed_repo(repo_factory)
    assert run_cli(repo / "shop", "verify").code == 0


def test_refresh_is_silent_and_writes_only_when_stale(repo_factory):
    repo = repo_factory(TINY)
    first = run_cli(repo, "refresh")
    assert first.code == 0 and first.out == ""
    assert all((repo / rel).is_file() for rel in MAPS)
    stamps = {rel: os.stat(repo / rel).st_mtime_ns for rel in MAPS}
    second = run_cli(repo, "refresh")
    assert second.code == 0 and second.out == ""
    assert stamps == {rel: os.stat(repo / rel).st_mtime_ns for rel in MAPS}
    report = repo / "scripts" / "report.py"
    report.write_text(report.read_text(encoding="utf-8") + "import shop.ledger\n", encoding="utf-8")
    run_cli(repo, "refresh")
    assert run_cli(repo, "verify").code == 0


def test_refresh_fails_open_on_a_broken_config(repo_factory):
    repo = repo_factory({**TINY, "indextool.toml": "this is not toml"})
    result = run_cli(repo, "refresh")
    assert result.code == 0 and result.out == ""
    assert "refresh" in result.err and "indextool.toml" in result.err


def test_refresh_never_replaces_a_good_map_with_an_empty_one(repo_factory):
    repo = committed_repo(repo_factory)
    before = (repo / "docs" / "architecture.md").read_bytes()
    git(repo, "rm", "-q", "-r", "shop", "scripts")
    result = run_cli(repo, "refresh")
    assert result.code == 0 and result.out == "" and "no Python modules" in result.err
    assert (repo / "docs" / "architecture.md").read_bytes() == before


def test_refresh_with_bad_arguments_still_exits_zero(repo_factory):
    repo = repo_factory(TINY)
    result = run_cli(repo, "refresh", "--bogus")
    assert result.code == 0 and result.out == ""
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_cli_verify_refresh.py -v`
Expected: FAIL (the `verify` and `refresh` commands do not exist yet: argparse exits with code 2 for an invalid choice).

- [ ] **Step 3: Implement**

In `src/indextool/cli.py`, replace the import block and everything after `_warn` with the following (keeping `_warn` and `_generate` as they are, and adding the new functions between `_generate` and `_parser`):

The imports become:

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, gitio
from .config import load_config
from .errors import ConfigError
from .output import changed_lines, compare, expected_text, read_committed
from .pipeline import build, sync_files
```

Add these functions after `_generate`:

```python
def _regenerate_command(source: str) -> str:
    return "indextool generate" + (" --source index" if source == "index" else "")


def _warn_unstaged(cfg, built, source: str) -> None:
    if source != "worktree" or not gitio.in_work_tree(cfg.base):
        return
    watched = set(built.py_files)
    if cfg.config_file is not None:
        watched.add(cfg.config_file.name)
    touched = sorted(gitio.unstaged(cfg.base) & watched)
    if touched:
        _warn(
            f"warning: {len(touched)} tracked file(s) have unstaged changes (for example {touched[0]}); CI will see "
            "the committed version; use --source index to check what you would commit"
        )


def _verify(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(Path.cwd(), args.config, args.source)
        if cfg.config_untracked:
            _warn(f"{cfg.config_file.name} is not tracked by git, so CI would not see it; git add it first")
            return 2
        built = build(cfg, args.source)
    except (ConfigError, gitio.GitError) as exc:
        _warn(str(exc))
        return 2
    _warn_unstaged(cfg, built, args.source)
    regenerate = _regenerate_command(args.source)
    drift = False
    for rel, produced in ((cfg.architecture, built.architecture), (cfg.index, built.index)):
        wanted = expected_text(produced)
        actual = read_committed(cfg.base, rel, args.source)
        state = compare(actual, wanted)
        if state == "current":
            print(f"indextool: {rel} is current")
            continue
        drift = True
        if state == "missing":
            print(f"indextool: {rel} does not exist; write it with: {regenerate}")
            continue
        print(f"indextool: {rel} is out of date; regenerate it with: {regenerate}")
        lines = changed_lines(actual, wanted)
        print("\n".join(lines[:12]) + (f"\n... ({len(lines) - 12} more changed lines)" if len(lines) > 12 else ""))
    if drift:
        python = f"{sys.version_info.major}.{sys.version_info.minor}"
        print(f"indextool {__version__}, Python {python}")
        if built.unparsable:
            print(
                f"{built.unparsable} file(s) failed to parse under Python {python}; "
                "check that CI and local Python versions match."
            )
    return 1 if drift else 0


def _refresh(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(Path.cwd(), args.config, args.source)
        if cfg.config_untracked:
            _warn(f"{cfg.config_file.name} is not tracked by git; CI will not see it")
        built = build(cfg, args.source)
        if built.module_count == 0:
            _warn("refresh: no Python modules found; nothing written")
            return 0
        sync_files(cfg, args.source, built)
    except Exception as exc:  # a SessionStart hook must fail open, whatever went wrong
        _warn(f"refresh: {type(exc).__name__}: {exc}")
    return 0
```

Replace `_parser` and `main` with:

```python
def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config", type=Path, default=None, help="path to indextool.toml, or a pyproject.toml with [tool.indextool]"
    )
    common.add_argument(
        "--source",
        choices=("worktree", "index"),
        default="worktree",
        help="read files from the working tree (default) or from the git index",
    )
    parser = argparse.ArgumentParser(
        prog="indextool", description="Derive an architecture map from a Python repository and verify it in CI."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate", parents=[common], help="write the architecture map and the module index")
    sub.add_parser("verify", parents=[common], help="fail when the committed files are stale (exit 1) or misconfigured (exit 2)")
    sub.add_parser("refresh", parents=[common], help="silent, fail-open regeneration for a session-start hook")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    try:
        args = _parser().parse_args(argv)
    except SystemExit:
        given = sys.argv[1:] if argv is None else argv
        if given[:1] == ["refresh"]:
            return 0  # even a bad argument must not fail a session
        raise
    return {"generate": _generate, "verify": _verify, "refresh": _refresh}[args.command](args)
```

- [ ] **Step 4: Run to see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_cli_verify_refresh.py -v`
Expected: all pass. `test_index_source_checks_what_would_be_committed` is the important one: it shows worktree mode and index mode disagreeing exactly when a code change is staged and its map is not.

- [ ] **Step 5: Run the whole suite and commit**

Run: `.venv/Scripts/python -m pytest -q`
Expected: everything passes.

```bash
git add src/indextool/cli.py tests/test_cli_verify_refresh.py
git commit -q -m "feat: verify and refresh commands" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 12: The managed pointer block, and `verify` checks it

**Files:**
- Create: `src/indextool/pointer.py`
- Modify: `src/indextool/cli.py` (`_verify`, `_warn_unstaged`)
- Test: `tests/test_pointer.py`

**Interfaces:**
- Consumes: `config.Config` (`architecture`, `index`; Task 5), `sources.read_file` (Task 4), `output.normalize_newlines` (Task 10).
- Produces (`pointer`): `BEGIN`, `END` (the marker lines), `CANDIDATES = ("CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md")`; `render_block(cfg: Config) -> str` (marker lines included, no trailing newline); `upsert(text: str, block: str) -> tuple[str, bool]` (replace an existing managed block or append one; the bool says whether the text changed); `imports_agents(text: str) -> bool` (a line that is exactly `@AGENTS.md`); `targets(base: Path) -> list[str]` (placement, spec 7.2); `check_pointers(cfg: Config, source: str) -> tuple[list[str], bool]` returning `(problems, found_any_block)` where a problem names a file whose managed block differs from `render_block(cfg)`.
- Produces (`cli`): `verify` also runs `check_pointers`; a problem is printed and makes the exit code 2 (which wins over 1); when no candidate file has a block, one stderr note says to run `indextool init`; the unstaged-changes warning also watches the candidate files.

- [ ] **Step 1: Write the failing tests**

`tests/test_pointer.py`:

```python
import pytest

from indextool.pointer import BEGIN, CANDIDATES, END, check_pointers, imports_agents, render_block, targets, upsert
from tests.fixture_repos import TINY
from tests.helpers import commit_all, make_config, run_cli, write_files


def test_render_block_names_the_configured_paths_and_carries_no_numbers(tmp_path):
    cfg = make_config(tmp_path, 'architecture = "maps/arch.md"\nindex = "maps/idx.txt"\n')
    block = render_block(cfg)
    lines = block.split("\n")
    assert lines[0] == BEGIN and lines[-1] == END and len(lines) == 5
    assert "`maps/arch.md`" in lines[1] and "Read it whole for whole-repo questions." in lines[1]
    assert "`maps/idx.txt`" in lines[2] and "It is large: do not read it whole." in lines[2]
    assert "indextool generate" in lines[3] and "indextool verify" in lines[3]
    assert not any(ch.isdigit() for ch in "".join(lines[1:4]).replace("`maps/arch.md`", "").replace("`maps/idx.txt`", ""))


def test_upsert_appends_replaces_and_is_idempotent(tmp_path):
    block = render_block(make_config(tmp_path))
    appended, changed = upsert("# Notes\n\nSome text.\n", block)
    assert changed and appended.startswith("# Notes\n\nSome text.\n\n") and appended.endswith(END + "\n")
    again, changed = upsert(appended, block)
    assert not changed and again == appended
    stale = appended.replace("Read it whole", "Read it")
    fixed, changed = upsert(stale, block)
    assert changed and fixed == appended
    fresh, changed = upsert("", block)
    assert changed and fresh == block + "\n"


def test_upsert_keeps_text_around_the_block(tmp_path):
    block = render_block(make_config(tmp_path))
    text = "before\n\n" + block.replace("Read it whole", "Read it") + "\n\nafter\n"
    fixed, _ = upsert(text, block)
    assert fixed == "before\n\n" + block + "\n\nafter\n"


def test_imports_agents():
    assert imports_agents("@AGENTS.md\n\n## Claude Code\n")
    assert imports_agents("intro\n  @AGENTS.md  \n")
    assert not imports_agents("see @AGENTS.md for more\n")


@pytest.mark.parametrize(
    "files,expected",
    [
        ({}, ["AGENTS.md"]),
        ({"CLAUDE.md": "x\n"}, ["CLAUDE.md"]),
        ({"AGENTS.md": "x\n"}, ["AGENTS.md"]),
        ({".claude/CLAUDE.md": "x\n"}, [".claude/CLAUDE.md"]),
        ({"CLAUDE.md": "x\n", "AGENTS.md": "y\n"}, ["CLAUDE.md", "AGENTS.md"]),
        ({"CLAUDE.md": "@AGENTS.md\n", "AGENTS.md": "y\n"}, ["AGENTS.md"]),
        ({"CLAUDE.md": "@AGENTS.md\n"}, ["CLAUDE.md"]),
    ],
)
def test_placement(tmp_path, files, expected):
    write_files(tmp_path, files)
    assert targets(tmp_path) == expected


def test_check_pointers_reports_stale_blocks_and_whether_any_block_exists(repo_factory):
    repo = repo_factory(TINY)
    cfg = make_config(repo)
    assert check_pointers(cfg, "worktree") == ([], False)
    block = render_block(cfg)
    write_files(repo, {"AGENTS.md": block + "\n", "CLAUDE.md": block.replace("Read it whole", "Read it") + "\n"})
    problems, found = check_pointers(cfg, "worktree")
    assert found is True
    assert problems == ["CLAUDE.md: the managed pointer block is out of date; run: indextool init"]


def test_check_pointers_reads_the_index_in_index_mode(repo_factory):
    repo = repo_factory(TINY)
    cfg = make_config(repo)
    write_files(repo, {"AGENTS.md": render_block(cfg) + "\n"})
    assert check_pointers(cfg, "index") == ([], False)  # not staged yet
    commit_all(repo)
    assert check_pointers(cfg, "index") == ([], True)


def committed_with_pointer(repo_factory, block_edit=None):
    repo = repo_factory(TINY)
    assert run_cli(repo, "generate").code == 0
    block = render_block(make_config(repo))
    write_files(repo, {"AGENTS.md": (block_edit(block) if block_edit else block) + "\n"})
    commit_all(repo)
    return repo


def test_verify_passes_with_a_current_block_and_notes_a_missing_one(repo_factory):
    repo = committed_with_pointer(repo_factory)
    result = run_cli(repo, "verify")
    assert result.code == 0 and "no managed pointer block" not in result.err
    bare = repo_factory(TINY, name="bare")
    run_cli(bare, "generate")
    commit_all(bare)
    result = run_cli(bare, "verify")
    assert result.code == 0 and "no managed pointer block found" in result.err


def test_verify_exits_2_when_a_block_was_edited_by_hand(repo_factory):
    repo = committed_with_pointer(repo_factory, lambda b: b.replace("Read it whole", "Read it"))
    result = run_cli(repo, "verify")
    assert result.code == 2
    assert "AGENTS.md: the managed pointer block is out of date; run: indextool init" in result.out


def test_a_pointer_problem_wins_over_drift(repo_factory):
    repo = committed_with_pointer(repo_factory, lambda b: b.replace("Read it whole", "Read it"))
    (repo / "docs" / "architecture.md").unlink()
    assert run_cli(repo, "verify").code == 2


def test_candidates_are_the_files_agents_read():
    assert CANDIDATES == ("CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md")
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_pointer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indextool.pointer'`.

- [ ] **Step 3: Implement `pointer.py`**

`src/indextool/pointer.py`:

```python
"""The managed pointer block that tells a coding agent where the generated files are and how to use them."""
from __future__ import annotations

import re
from pathlib import Path

from .config import Config
from .output import normalize_newlines
from .sources import read_file

BEGIN = "<!-- indextool:begin (managed: change indextool.toml, not this block) -->"
END = "<!-- indextool:end -->"
CANDIDATES = ("CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md")
_BLOCK = re.compile(r"<!-- indextool:begin[^\n]*?-->.*?<!-- indextool:end -->", re.DOTALL)


def render_block(cfg: Config) -> str:
    return "\n".join(
        [
            BEGIN,
            f"- `{cfg.architecture}` - generated map of layout, dependency layers, import cycles, routes, tables and "
            "what writes them, and the most-used modules. Read it whole for whole-repo questions. Regenerated from "
            "code, never edited by hand.",
            f"- `{cfg.index}` - generated one-line-per-module index (title, library or standalone, io, tables, "
            "routes). Search it with grep for where something lives or which modules read or write a table. It is "
            "large: do not read it whole.",
            "- Regenerate with `indextool generate`. CI runs `indextool verify` and fails when either file is stale.",
            END,
        ]
    )


def upsert(text: str, block: str) -> tuple[str, bool]:
    match = _BLOCK.search(text)
    if match:
        if match.group(0) == block:
            return text, False
        return text[: match.start()] + block + text[match.end() :], True
    if not text.strip():
        return block + "\n", True
    return text.rstrip("\n") + "\n\n" + block + "\n", True


def imports_agents(text: str) -> bool:
    return any(line.strip() == "@AGENTS.md" for line in text.split("\n"))


def targets(base: Path) -> list[str]:
    """Which instruction files receive the block (spec 7.2)."""
    existing = [rel for rel in CANDIDATES if (base / rel).is_file()]
    if not existing:
        return ["AGENTS.md"]
    claude = [rel for rel in existing if rel != "AGENTS.md"]
    if "AGENTS.md" in existing:
        for rel in claude:
            try:
                text = (base / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if imports_agents(text):
                return ["AGENTS.md"]
    return existing


def check_pointers(cfg: Config, source: str) -> tuple[list[str], bool]:
    """(problems, found_any_block): every managed block that differs from what the config renders is a problem."""
    block = render_block(cfg)
    problems: list[str] = []
    found = False
    for rel in CANDIDATES:
        raw = read_file(cfg.base, rel, source)
        if raw is None:
            continue
        match = _BLOCK.search(normalize_newlines(raw.decode("utf-8", errors="replace")))
        if not match:
            continue
        found = True
        if match.group(0) != block:
            problems.append(f"{rel}: the managed pointer block is out of date; run: indextool init")
    return problems, found
```

- [ ] **Step 4: Wire it into `verify`**

In `src/indextool/cli.py` add the import `from .pointer import CANDIDATES, check_pointers`.

In `_warn_unstaged`, after `watched = set(built.py_files)` add the line:

```python
    watched.update(CANDIDATES)
```

In `_verify`, replace the last line of the function, `    return 1 if drift else 0`, with:

```python
    problems, found = check_pointers(cfg, args.source)
    for problem in problems:
        print(f"indextool: {problem}")
    if not found:
        _warn("no managed pointer block found in CLAUDE.md, .claude/CLAUDE.md or AGENTS.md; run indextool init to add one")
    if problems:
        return 2
    return 1 if drift else 0
```

The drift-versions lines printed inside `if drift:` stay as they are.

- [ ] **Step 5: Run to see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_pointer.py tests/test_cli_verify_refresh.py -v`
Expected: all pass. The earlier verify tests still pass because a missing block only writes a stderr note.

- [ ] **Step 6: Commit**

```bash
git add src/indextool/pointer.py src/indextool/cli.py tests/test_pointer.py
git commit -q -m "feat: managed pointer block, verified by verify" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 13: The `init` command

**Files:**
- Create: `src/indextool/init.py`
- Modify: `src/indextool/cli.py` (add the `init` subcommand and handler)
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `config.load_config`, `CONFIG_NAME` (Task 5); `pointer.render_block`, `upsert`, `targets` (Task 12); `pipeline.sync_files`, `output.write_atomic` (Task 10); `gitio.top_level` (Task 3); `indextool.FORMAT_VERSION` (Task 1).
- Produces (`init`): `Item(rel: str, action: str, note: str = "")` and `InitResult(items: tuple[Item, ...], precommit: str)` (frozen dataclasses; `action` is `created`, `updated`, `unchanged`, `skipped` or `planned`); `detect_roots(base: Path) -> list[str]`; `render_config(roots: list[str]) -> str`; `merge_hook(text: str | None) -> tuple[str | None, str]` returning `(new_text_or_None, outcome)` with outcome `"changed"`, `"unchanged"` or `"skipped"` (unparsable settings); `workflow_text(workdir: str) -> str`; `run(start: Path, *, dry_run: bool = False, hook: str = "shared") -> InitResult`.
- Produces (`cli`): `indextool init [--dry-run] [--hook shared|local|none]`, printing one `<action> <path>` line per item, then (when files were written) a `git add ...` line, then the pre-commit snippet. Exit 0, or 2 on misconfiguration.

Behaviour (spec 7.1): it edits only what the standard library can edit safely (new files, a JSON merge, marker blocks, single-line appends) and prints YAML as a snippet; it plans every new file's content in memory before writing anything; an existing config (`indextool.toml` or a `[tool.indextool]` table) is never touched; `--hook local` writes `.claude/settings.local.json` and adds it to `.gitignore`; settings that are not valid JSON are left alone with a note; the workflow pins the Python version that ran `init` and `indextool~=<major.minor>.0`, and adds `working-directory` for a sub-project; it ends by generating the two files so the pointer targets exist.

- [ ] **Step 1: Write the failing tests**

`tests/test_init.py`:

```python
import json
import sys

from indextool import FORMAT_VERSION
from indextool.init import merge_hook, render_config, workflow_text
from tests.fixture_repos import TINY
from tests.helpers import commit_all, git, run_cli, write_files

PY = f"{sys.version_info.major}.{sys.version_info.minor}"


def snapshot(repo):
    return {
        p.relative_to(repo).as_posix(): p.read_bytes()
        for p in sorted(repo.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(repo).parts
    }


SRC_LAYOUT = {
    "src/shop/__init__.py": '"""Shop package."""\n',
    "src/shop/ledger.py": '"""Ledger."""\n',
}


def test_init_creates_everything_in_a_fresh_project(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    result = run_cli(repo, "init")
    assert result.code == 0, result.err
    assert 'roots = ["src"]' in (repo / "indextool.toml").read_text(encoding="utf-8")
    agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- indextool:begin" in agents and "`docs/architecture.md`" in agents
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hook = settings["hooks"]["SessionStart"][0]["hooks"][0]
    assert hook == {"type": "command", "command": "indextool refresh", "timeout": 30}
    workflow = (repo / ".github" / "workflows" / "indextool.yml").read_text(encoding="utf-8")
    assert f'python-version: "{PY}"' in workflow and f'pip install "indextool~={FORMAT_VERSION}.0"' in workflow
    assert "run: indextool verify" in workflow and "working-directory" not in workflow
    attributes = (repo / ".gitattributes").read_text(encoding="utf-8")
    assert "docs/architecture.md text eol=lf" in attributes and "docs/architecture.index.txt text eol=lf" in attributes
    assert (repo / "docs" / "architecture.md").is_file() and (repo / "docs" / "architecture.index.txt").is_file()
    assert "git add " in result.out and "indextool-verify" in result.out


def test_init_is_idempotent(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    run_cli(repo, "init")
    before = snapshot(repo)
    result = run_cli(repo, "init")
    assert result.code == 0, result.err
    assert snapshot(repo) == before
    action_lines = [ln for ln in result.out.split("\n") if ln.startswith("  ")]
    assert action_lines and not any(ln.split()[0] in ("created", "updated") for ln in action_lines)


def test_dry_run_writes_nothing(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    result = run_cli(repo, "init", "--dry-run")
    assert result.code == 0 and "dry run" in result.out
    assert git(repo, "status", "--porcelain").strip() == ""
    assert not (repo / "indextool.toml").exists()


def test_existing_config_is_never_overwritten(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "indextool.toml": 'title = "Mine"\nroots = ["src"]\n'})
    result = run_cli(repo, "init")
    assert result.code == 0, result.err
    assert (repo / "indextool.toml").read_text(encoding="utf-8") == 'title = "Mine"\nroots = ["src"]\n'
    assert "skipped" in result.out and "configuration already present" in result.out


def test_a_pyproject_table_counts_as_an_existing_config(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "pyproject.toml": '[tool.indextool]\nroots = ["src"]\n'})
    assert run_cli(repo, "init").code == 0
    assert not (repo / "indextool.toml").exists()


def test_hook_merge_keeps_foreign_keys_and_never_duplicates(repo_factory):
    existing = {
        "permissions": {"allow": ["Bash(git log *)"]},
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]},
    }
    repo = repo_factory({**SRC_LAYOUT, ".claude/settings.json": json.dumps(existing)})
    run_cli(repo, "init")
    run_cli(repo, "init")
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"] == existing["permissions"]
    commands = [h["command"] for g in settings["hooks"]["SessionStart"] for h in g["hooks"]]
    assert commands == ["echo hi", "indextool refresh"]


def test_local_hook_goes_to_settings_local_and_is_gitignored(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    assert run_cli(repo, "init", "--hook", "local").code == 0
    assert (repo / ".claude" / "settings.local.json").is_file()
    assert not (repo / ".claude" / "settings.json").exists()
    assert ".claude/settings.local.json" in (repo / ".gitignore").read_text(encoding="utf-8").split("\n")


def test_hook_none_writes_no_settings(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    assert run_cli(repo, "init", "--hook", "none").code == 0
    assert not (repo / ".claude").exists()


def test_settings_that_are_not_json_are_left_alone(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, ".claude/settings.json": "{not json"})
    result = run_cli(repo, "init")
    assert result.code == 0
    assert (repo / ".claude" / "settings.json").read_text(encoding="utf-8") == "{not json"
    assert "skipped" in result.out and "not valid JSON" in result.out


def test_pointer_goes_into_every_existing_instruction_file_and_keeps_their_text(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "CLAUDE.md": "# Claude notes\n", "AGENTS.md": "# Agent notes\n"})
    run_cli(repo, "init")
    for name, head in (("CLAUDE.md", "# Claude notes\n"), ("AGENTS.md", "# Agent notes\n")):
        text = (repo / name).read_text(encoding="utf-8")
        assert text.startswith(head) and text.count("<!-- indextool:begin") == 1


def test_pointer_goes_only_into_agents_md_when_claude_md_imports_it(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "CLAUDE.md": "@AGENTS.md\n", "AGENTS.md": "# Agent notes\n"})
    run_cli(repo, "init")
    assert "indextool:begin" not in (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert "indextool:begin" in (repo / "AGENTS.md").read_text(encoding="utf-8")


def test_the_workflow_is_not_overwritten(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, ".github/workflows/indextool.yml": "name: mine\n"})
    result = run_cli(repo, "init")
    assert (repo / ".github" / "workflows" / "indextool.yml").read_text(encoding="utf-8") == "name: mine\n"
    assert "exists; not overwritten" in result.out


def test_a_sub_project_workflow_runs_verify_in_its_directory(repo_factory):
    repo = repo_factory({"svc/indextool.toml": 'roots = ["."]\n', "svc/a.py": "x = 1\n"})
    result = run_cli(repo / "svc", "init")
    assert result.code == 0, result.err
    workflow = (repo / ".github" / "workflows" / "indextool.yml").read_text(encoding="utf-8")
    assert "run: indextool verify\n        working-directory: svc" in workflow


def test_after_init_and_a_commit_verify_passes_in_both_modes(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    assert run_cli(repo, "init").code == 0
    commit_all(repo, "adopt indextool")
    verified = run_cli(repo, "verify")
    assert verified.code == 0, verified.out + verified.err
    assert "no managed pointer block" not in verified.err
    assert run_cli(repo, "verify", "--source", "index").code == 0


def test_init_reports_config_errors_and_writes_nothing(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "indextool.toml": "titel = 'x'\n"})
    result = run_cli(repo, "init")
    assert result.code == 2 and "unknown key 'titel'" in result.err
    assert not (repo / "AGENTS.md").exists()


def test_helpers_render_config_merge_hook_and_workflow():
    assert render_config(["."]).count('roots = ["."]') == 1
    text, outcome = merge_hook(None)
    assert outcome == "changed" and json.loads(text)["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] == 30
    assert merge_hook(text) == (None, "unchanged")
    assert merge_hook("[1, 2]") == (None, "skipped")
    assert "working-directory: svc" in workflow_text("svc") and "working-directory" not in workflow_text("")
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_init.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indextool.init'`.

- [ ] **Step 3: Implement `init.py`**

`src/indextool/init.py`:

```python
"""Idempotent project setup: config, pointer, hook, CI workflow, .gitattributes. It edits only what the standard
library can edit safely; anything else is printed as a snippet."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import FORMAT_VERSION, gitio
from .config import CONFIG_NAME, load_config
from .output import write_atomic
from .pipeline import sync_files
from .pointer import render_block, targets, upsert

HOOK_COMMAND = "indextool refresh"
LOCAL_SETTINGS = ".claude/settings.local.json"

PRECOMMIT_SNIPPET = """\
To run the check in pre-commit, add this to .pre-commit-config.yaml:

repos:
  - repo: local
    hooks:
      - id: indextool-verify
        name: indextool verify
        entry: indextool verify --source index
        language: system
        pass_filenames: false
        always_run: true
"""

_WORKFLOW = """\
name: architecture-map
on:
  push:
  pull_request:
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "@PY@"
      - run: pip install "indextool~=@FMT@.0"
@VERIFY@"""


@dataclass(frozen=True)
class Item:
    rel: str
    action: str
    note: str = ""


@dataclass(frozen=True)
class InitResult:
    items: tuple[Item, ...]
    precommit: str


def detect_roots(base: Path) -> list[str]:
    src = base / "src"
    if src.is_dir() and next(src.rglob("*.py"), None) is not None:
        return ["src"]
    return ["."]


def render_config(roots: list[str]) -> str:
    listed = ", ".join(f'"{r}"' for r in roots)
    return (
        "# indextool configuration. Every key is optional; see the indextool documentation for the full list.\n"
        f"roots = [{listed}]\n"
        'architecture = "docs/architecture.md"\n'
        'index = "docs/architecture.index.txt"\n'
    )


def merge_hook(text: str | None) -> tuple[str | None, str]:
    """Add the SessionStart hook to a Claude Code settings file's text. Returns (new_text_or_None, outcome)."""
    try:
        data = json.loads(text) if text and text.strip() else {}
    except json.JSONDecodeError:
        return None, "skipped"
    if not isinstance(data, dict):
        return None, "skipped"
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return None, "skipped"
    session = hooks.setdefault("SessionStart", [])
    if not isinstance(session, list):
        return None, "skipped"
    for group in session:
        for hook in group.get("hooks", []) if isinstance(group, dict) else []:
            if isinstance(hook, dict) and HOOK_COMMAND in str(hook.get("command", "")):
                return None, "unchanged"
    session.append({"hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": 30}]})
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n", "changed"


def workflow_text(workdir: str) -> str:
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    verify = "      - run: indextool verify\n" + (f"        working-directory: {workdir}\n" if workdir else "")
    return _WORKFLOW.replace("@PY@", python).replace("@FMT@", FORMAT_VERSION).replace("@VERIFY@", verify)


def _with_line(text: str | None, line: str) -> str | None:
    existing = text or ""
    if line in [ln.strip() for ln in existing.split("\n")]:
        return None
    prefix = existing if (not existing or existing.endswith("\n")) else existing + "\n"
    return prefix + line + "\n"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _rel(path: Path, base: Path) -> str:
    return Path(os.path.relpath(path, base)).as_posix()


def run(start: Path, *, dry_run: bool = False, hook: str = "shared") -> InitResult:
    cfg = load_config(start)
    base = cfg.base
    top = gitio.top_level(base) or base
    items: list[Item] = []
    writes: list[tuple[Path, str]] = []

    def stage(path: Path, text: str | None, note: str = "") -> None:
        if text is None:
            items.append(Item(_rel(path, base), "unchanged", note))
            return
        items.append(Item(_rel(path, base), "updated" if path.exists() else "created", note))
        writes.append((path, text))

    if cfg.config_file is not None:
        items.append(Item(_rel(cfg.config_file, base), "skipped", "configuration already present"))
    else:
        stage(base / CONFIG_NAME, render_config(detect_roots(base)))

    block = render_block(cfg)
    for rel in targets(base):
        path = base / rel
        try:
            text = _read(path) or ""
        except UnicodeDecodeError:
            items.append(Item(rel, "skipped", "not valid UTF-8; left alone"))
            continue
        new_text, changed = upsert(text, block)
        stage(path, new_text if changed else None)

    if hook == "none":
        items.append(Item(".claude/settings.json", "skipped", "hook disabled (--hook none)"))
    else:
        hook_rel = ".claude/settings.json" if hook == "shared" else LOCAL_SETTINGS
        try:
            new_text, outcome = merge_hook(_read(base / hook_rel))
        except UnicodeDecodeError:
            new_text, outcome = None, "skipped"
        if outcome == "skipped":
            items.append(Item(hook_rel, "skipped", "not valid JSON; left alone (add the hook by hand)"))
        else:
            stage(base / hook_rel, new_text)
        if hook == "local":
            ignore = base / ".gitignore"
            stage(ignore, _with_line(_read(ignore), LOCAL_SETTINGS))

    workflow = top / ".github" / "workflows" / "indextool.yml"
    if workflow.exists():
        items.append(Item(_rel(workflow, base), "skipped", "exists; not overwritten"))
    else:
        workdir = "" if base == top else base.relative_to(top).as_posix()
        stage(workflow, workflow_text(workdir))

    attributes = base / ".gitattributes"
    original = _read(attributes)
    updated = original
    for out in (cfg.architecture, cfg.index):
        updated = _with_line(updated, f"{out} text eol=lf") or updated
    stage(attributes, None if updated == original else updated)

    if not dry_run:
        for path, text in writes:
            write_atomic(path, text)
        for rel, action, _size in sync_files(load_config(base), "worktree"):
            items.append(Item(rel, action, "generated"))
    else:
        items.append(Item(cfg.architecture, "planned", "generated after setup"))
        items.append(Item(cfg.index, "planned", "generated after setup"))
    return InitResult(items=tuple(items), precommit=PRECOMMIT_SNIPPET)
```

- [ ] **Step 4: Add the CLI subcommand**

In `src/indextool/cli.py` add `from . import init as init_command` to the imports (next to `from . import __version__, gitio`), then add this handler after `_refresh`:

```python
def _init(args: argparse.Namespace) -> int:
    try:
        result = init_command.run(Path.cwd(), dry_run=args.dry_run, hook=args.hook)
    except (ConfigError, gitio.GitError) as exc:
        _warn(str(exc))
        return 2
    for item in result.items:
        print(f"  {item.action:<10} {item.rel}" + (f"  ({item.note})" if item.note else ""))
    if args.dry_run:
        print("(dry run: nothing was written)")
    else:
        written = [i.rel for i in result.items if i.action in ("created", "updated")]
        if written:
            print("git add " + " ".join(written))
    print()
    print(result.precommit)
    return 0
```

In `_parser`, before `return parser`, add:

```python
    init_parser = sub.add_parser("init", help="add config, pointer, hook, CI workflow and .gitattributes; then generate")
    init_parser.add_argument("--dry-run", action="store_true", help="show what would change and write nothing")
    init_parser.add_argument(
        "--hook",
        choices=("shared", "local", "none"),
        default="shared",
        help="where to put the SessionStart hook: .claude/settings.json (shared, default), settings.local.json, or nowhere",
    )
```

In `main`, extend the handler table to `{"generate": _generate, "verify": _verify, "refresh": _refresh, "init": _init}`.

- [ ] **Step 5: Run to see them pass**

Run: `.venv/Scripts/python -m pytest tests/test_init.py -v`
Expected: all pass. If `test_init_is_idempotent` fails because the second run reports `updated` for `.gitattributes` or the settings file, print the first differing item; the usual cause is `_with_line` or `merge_hook` producing text that differs by a trailing newline.

- [ ] **Step 6: Run the whole suite and commit**

Run: `.venv/Scripts/python -m pytest -q`
Expected: everything passes.

```bash
git add src/indextool/init.py src/indextool/cli.py tests/test_init.py
git commit -q -m "feat: init command (config, pointer, hook, workflow, gitattributes)" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 14: Determinism suite, portable golden output and the golden bump gate

**Files:**
- Modify: `tests/fixture_repos.py` (add `PORTABLE`, `LATIN1`, `PEP701`)
- Create: `.gitattributes`, `scripts/update_goldens.py`, `scripts/check_golden_bump.py`, `tests/golden/portable.architecture.md`, `tests/golden/portable.index.txt`
- Test: `tests/test_determinism.py`, `tests/test_golden.py`, `tests/test_check_golden_bump.py`

**Interfaces:**
- Consumes: the whole tool through the CLI (`run_cli`), plus `pipeline.build_from_files`, `config.load_config` via `make_config`.
- Produces (`tests/fixture_repos.py`): `PORTABLE: dict[str, str]` (a synthetic repository, including its committed `indextool.toml`, that parses on every supported Python), `LATIN1: dict[str, bytes]` (one module with a `latin-1` coding cookie), `PEP701: dict[str, str]` (one module using PEP 701 f-string syntax, valid only on Python 3.12 and later).
- Produces (`scripts/check_golden_bump.py`): `header_version(text: str) -> str | None`; `bump_required(old: str, new: str) -> bool` (true when the text changed but the `indextool <major.minor>` in it did not); `main(argv: list[str]) -> int` where `argv[1]` is the base ref; exit 1 when a golden under `tests/golden` changed relative to the base ref without a minor bump.
- Produces (`scripts/update_goldens.py`): rewrites the two golden files from the portable fixture.

Contract being pinned (spec section 4 and 8.1): the output is a pure function of file contents, config, the tool's `major.minor` and the Python `major.minor`. The portable fixture is compared against one golden on every OS and Python in the CI matrix; the PEP 701 fixture is asserted per Python version.

- [ ] **Step 1: Add the fixtures**

Append to `tests/fixture_repos.py`:

```python
PORTABLE = {
    "indextool.toml": 'title = "Portable shop"\nexclude = ["legacy/"]\n',
    "shop/__init__.py": '"""Shop package."""\n',
    "shop/ledger.py": (
        '"""Ledger of money movements."""\nimport sqlite3\n\nSCHEMA = "CREATE TABLE ledger (id INTEGER)"\n'
        'RATES = {"usd": 1}\n\n\nclass Money:\n    pass\n'
    ),
    "shop/orders.py": (
        '"""Order handling."""\nimport sqlite3\nfrom shop import ledger\n\nSQL = "CREATE TABLE orders (id INTEGER)"\n'
        'INSERT = "INSERT INTO orders VALUES (1)"\nRATES = {"eur": 2}\n\n\nclass Money:\n    pass\n'
    ),
    "shop/web.py": (
        '"""HTTP routes."""\nfrom flask import Flask\nfrom shop import orders\n\napp = Flask(__name__)\n\n\n'
        '@app.route("/orders")\ndef list_orders():\n    return orders\n\n\n'
        '@app.route("/orders/<int:id>")\ndef show(id):\n    return id\n'
    ),
    "shop/cycle_a.py": "from shop import cycle_b\n",
    "shop/cycle_b.py": "from shop import cycle_a\n",
    "shop/cafe.py": '"""Crème brûlée café."""\nimport requests\n',
    "shop/broken.py": "def broken(:\n",
    "scripts/report.py": '"""Print a report."""\nfrom shop import orders\n\nif __name__ == "__main__":\n    print(orders)\n',
    "tests/test_orders.py": "from shop import orders\n",
    "legacy/old.py": "from shop import orders\n",
}

LATIN1 = {"shop/legacy_names.py": b'# -*- coding: latin-1 -*-\n"""Caf\xe9 module."""\n'}

PEP701 = {"a.py": 'names = ["x"]\nmsg = f"{"\\n".join(names)}"\n'}
```

`shop/broken.py` is unparsable on every Python version on purpose, so the "could not be parsed" line is part of the golden.

- [ ] **Step 2: Write the failing determinism tests**

`tests/test_determinism.py`:

```python
import random
import shutil
import sys

import pytest

from indextool.pipeline import build_from_files
from tests.fixture_repos import LATIN1, PEP701, PORTABLE
from tests.helpers import commit_all, git, make_config, run_cli, write_files

MAPS = ("docs/architecture.md", "docs/architecture.index.txt")


def read_maps(repo):
    return {rel: (repo / rel).read_bytes() for rel in MAPS}


def regenerate(repo, env=None, cwd=None, *args):
    shutil.rmtree(repo / "docs", ignore_errors=True)
    result = run_cli(cwd or repo, "generate", *args, env=env)
    assert result.code == 0, result.err
    return read_maps(repo)


def test_the_same_repository_generated_twice_is_identical(repo_factory):
    repo = repo_factory(PORTABLE)
    assert regenerate(repo) == regenerate(repo)


@pytest.mark.parametrize("seed", ["0", "1", "4242"])
def test_hash_seed_does_not_matter(repo_factory, seed):
    repo = repo_factory(PORTABLE)
    baseline = regenerate(repo, env={"PYTHONHASHSEED": "random"})
    assert regenerate(repo, env={"PYTHONHASHSEED": seed}) == baseline


def test_renamed_copies_produce_identical_output(repo_factory):
    assert regenerate(repo_factory(PORTABLE, name="alpha")) == regenerate(repo_factory(PORTABLE, name="beta-2"))


def test_working_directory_does_not_matter(repo_factory):
    repo = repo_factory(PORTABLE)
    assert regenerate(repo) == regenerate(repo, cwd=repo / "shop")


def test_crlf_sources_produce_identical_output(repo_factory):
    crlf = {k: (v.replace("\n", "\r\n") if k.endswith(".py") else v) for k, v in PORTABLE.items()}
    assert regenerate(repo_factory(PORTABLE, name="lf")) == regenerate(repo_factory(crlf, name="crlf"))


@pytest.mark.parametrize(
    "env",
    [{"LC_ALL": "C"}, {"LC_ALL": "C", "PYTHONUTF8": "0"}, {"PYTHONUTF8": "1"}, {"PYTHONUTF8": "0", "PYTHONIOENCODING": "ascii"}],
)
def test_locale_and_utf8_mode_do_not_matter_and_the_latin1_cookie_is_honoured(repo_factory, env):
    repo = repo_factory({**PORTABLE, **LATIN1})
    baseline = regenerate(repo)
    assert regenerate(repo, env=env) == baseline
    assert "Café module." in baseline[MAPS[1]].decode("utf-8")


def test_untracked_files_and_default_excluded_directories_change_nothing(repo_factory, tmp_path):
    repo = repo_factory(PORTABLE)
    before = regenerate(repo)
    write_files(repo, {"scratch.py": "import shop.orders\n", "venv/x.py": "x = 1\n"})  # untracked: never in the map
    assert regenerate(repo) == before
    walk = tmp_path / "walk"
    write_files(walk, {"a.py": "x = 1\n", "b.py": "import a\n"})
    baseline = regenerate(walk)
    write_files(walk, {"venv/extra.py": "x = 1\n", "node_modules/y.py": "y = 1\n", "pkg/__pycache__/z.py": ""})
    assert regenerate(walk) == baseline


def test_a_file_under_a_configured_exclude_changes_only_the_count_line(repo_factory):
    repo = repo_factory(PORTABLE)
    before = regenerate(repo)
    write_files(repo, {"legacy/extra.py": "import shop.orders\n"})
    commit_all(repo, "add an excluded file")
    after = regenerate(repo)
    assert after[MAPS[1]] == before[MAPS[1]]
    changed = set(before[MAPS[0]].decode("utf-8").split("\n")) ^ set(after[MAPS[0]].decode("utf-8").split("\n"))
    assert changed == {
        "- 1 file excluded by the configured `exclude` patterns",
        "- 2 files excluded by the configured `exclude` patterns",
    }


def test_a_rename_changes_the_output(repo_factory):
    repo = repo_factory(PORTABLE)
    before = regenerate(repo)
    git(repo, "mv", "shop/ledger.py", "shop/books.py")
    commit_all(repo, "rename")
    assert regenerate(repo) != before


def test_a_one_import_mutation_changes_the_output(repo_factory):
    repo = repo_factory(PORTABLE)
    before = regenerate(repo)
    report = repo / "scripts" / "report.py"
    report.write_text(report.read_text(encoding="utf-8") + "import shop.ledger\n", encoding="utf-8")
    commit_all(repo, "one more import")
    assert regenerate(repo) != before


def test_shuffled_discovery_order_gives_identical_output(tmp_path):
    cfg = make_config(tmp_path)
    files = {p: (c.encode("utf-8") if isinstance(c, str) else c) for p, c in PORTABLE.items() if p.endswith(".py")}
    expected = build_from_files(dict(sorted(files.items())), cfg)
    for seed in range(5):
        items = list(files.items())
        random.Random(seed).shuffle(items)
        built = build_from_files(dict(items), cfg)
        assert (built.architecture, built.index) == (expected.architecture, expected.index)


def test_worktree_and_index_outputs_match_on_a_clean_tree_and_differ_on_a_dirty_one(repo_factory):
    repo = repo_factory(PORTABLE)
    clean_worktree = regenerate(repo)
    assert regenerate(repo, None, None, "--source", "index") == clean_worktree
    ledger = repo / "shop" / "ledger.py"
    ledger.write_text(ledger.read_text(encoding="utf-8") + "import shop.web\n", encoding="utf-8")  # unstaged edit
    dirty_worktree = regenerate(repo)
    dirty_index = regenerate(repo, None, None, "--source", "index")
    assert dirty_worktree != dirty_index and dirty_index == clean_worktree
    regenerate(repo)
    assert "unstaged changes" in run_cli(repo, "verify").err


def test_pep701_fixture_is_parsed_only_on_python_3_12_and_later(tmp_path):
    cfg = make_config(tmp_path)
    built = build_from_files({p: c.encode("utf-8") for p, c in PEP701.items()}, cfg)
    if sys.version_info >= (3, 12):
        assert built.unparsable == 0
    else:
        assert built.unparsable == 1
        assert "- 1 file could not be parsed (counted as a module with no imports)" in built.architecture
```

Note `regenerate(repo, None, None, "--source", "index")` passes `env=None`, `cwd=None` positionally before the extra arguments.

- [ ] **Step 3: Run the suite**

Run: `.venv/Scripts/python -m pytest tests/test_determinism.py -v`
Expected: all pass without any production change, because the behaviour was built in Tasks 2 to 13. If a test fails, that is a real determinism bug: find the source (dict or set iteration, a path separator, a locale-dependent call, a folder name in the output) and fix it in the production module; do not weaken the test.

- [ ] **Step 4: Create the golden tooling**

`.gitattributes`:

```
tests/golden/* text eol=lf
```

`scripts/update_goldens.py`:

```python
"""Regenerate tests/golden/* from the portable fixture. Usage: python scripts/update_goldens.py"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.fixture_repos import PORTABLE  # noqa: E402
from tests.helpers import make_repo, run_cli  # noqa: E402

GOLDEN = ROOT / "tests" / "golden"


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:  # git object files are read-only on Windows
        repo = make_repo(Path(tmp), PORTABLE, name="portable")
        result = run_cli(repo, "generate")
        if result.code != 0:
            print(result.err, file=sys.stderr)
            return 1
        GOLDEN.mkdir(parents=True, exist_ok=True)
        (GOLDEN / "portable.architecture.md").write_bytes((repo / "docs" / "architecture.md").read_bytes())
        (GOLDEN / "portable.index.txt").write_bytes((repo / "docs" / "architecture.index.txt").read_bytes())
    print(f"updated {GOLDEN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/check_golden_bump.py`:

```python
"""Fail when golden output changed without a minor version bump.

Usage: python scripts/check_golden_bump.py <base-ref>

Golden files carry `indextool <major.minor>` in their header. A change to a golden that leaves that version
unchanged means a patch release could change users' output, which the versioning policy forbids."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

GOLDEN_DIR = "tests/golden"
_VERSION = re.compile(r"indextool (\d+\.\d+)")


def header_version(text: str) -> str | None:
    match = _VERSION.search(text)
    return match.group(1) if match else None


def bump_required(old: str, new: str) -> bool:
    if old == new:
        return False
    return header_version(old) == header_version(new)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout.decode("utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_golden_bump.py <base-ref>", file=sys.stderr)
        return 2
    base = argv[1]
    changed = [n for n in _git("diff", "--name-only", f"{base}...HEAD", "--", GOLDEN_DIR).split("\n") if n]
    failures: list[str] = []
    for name in changed:
        path = Path(name)
        if not path.exists():
            continue  # a deleted golden needs no bump
        try:
            old = _git("show", f"{base}:{name}")
        except subprocess.CalledProcessError:
            continue  # a new golden needs no bump
        new = path.read_text(encoding="utf-8")
        if bump_required(old.replace("\r\n", "\n"), new.replace("\r\n", "\n")):
            failures.append(name)
    if failures:
        print("golden output changed without a minor version bump (edit __version__ and regenerate the goldens):")
        for name in failures:
            print(f"  {name}")
        return 1
    print("golden output is unchanged, or the minor version was bumped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 5: Write the failing golden and bump-gate tests**

`tests/test_golden.py`:

```python
from pathlib import Path

import pytest

from tests.fixture_repos import PORTABLE
from tests.helpers import run_cli

GOLDEN = Path(__file__).resolve().parent / "golden"


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


@pytest.mark.parametrize(
    "golden,rel",
    [("portable.architecture.md", "docs/architecture.md"), ("portable.index.txt", "docs/architecture.index.txt")],
)
def test_portable_fixture_matches_the_golden_output(repo_factory, golden, rel):
    repo = repo_factory(PORTABLE)  # the folder is named "repo"; the golden was made in one named "portable"
    assert run_cli(repo, "generate").code == 0
    assert _lf((repo / rel).read_bytes()) == _lf((GOLDEN / golden).read_bytes())
```

`tests/test_check_golden_bump.py`:

```python
import importlib.util
from pathlib import Path

from tests.helpers import commit_all, git


def load():
    path = Path(__file__).resolve().parent.parent / "scripts" / "check_golden_bump.py"
    spec = importlib.util.spec_from_file_location("check_golden_bump", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD = "# Map\n\nGenerated by indextool 0.1 from the source.\nbody\n"


def test_bump_required_only_when_the_body_changed_under_the_same_version():
    m = load()
    assert m.bump_required(OLD, OLD) is False
    assert m.bump_required(OLD, OLD.replace("body", "other")) is True
    assert m.bump_required(OLD, OLD.replace("0.1", "0.2").replace("body", "other")) is False
    assert m.header_version("no version here") is None


def test_main_flags_an_unbumped_golden_change_and_accepts_a_bumped_one(repo_factory, monkeypatch, capsys):
    m = load()
    repo = repo_factory({"tests/golden/g.md": OLD})
    git(repo, "checkout", "-q", "-b", "feature")
    golden = repo / "tests" / "golden" / "g.md"
    golden.write_text(OLD.replace("body", "changed"), encoding="utf-8")
    commit_all(repo, "change without a bump")
    monkeypatch.chdir(repo)
    assert m.main(["check", "main"]) == 1
    assert "tests/golden/g.md" in capsys.readouterr().out
    golden.write_text(OLD.replace("0.1", "0.2").replace("body", "changed"), encoding="utf-8")
    commit_all(repo, "bump")
    assert m.main(["check", "main"]) == 0


def test_main_needs_a_base_ref():
    assert load().main(["check"]) == 2
```

- [ ] **Step 6: Generate the golden files and review them**

```bash
cd /c/python/indextool
.venv/Scripts/python scripts/update_goldens.py
cat tests/golden/portable.architecture.md
cat tests/golden/portable.index.txt
```

Expected: both files exist. Read them and confirm, by eye, that: the first line is `# Architecture map: Portable shop`; the third line contains `indextool 0.1`; the numbers section shows 1 excluded file and 1 file that could not be parsed; the cycle `shop.cycle_a`, `shop.cycle_b` is listed; `class Money` and `constant RATES` appear under "Same name, different modules"; the two routes appear; the tables `ledger` and `orders` appear; the index has one line per non-test module, including `shop.cafe | Crème brûlée café. | standalone network` (nothing imports it, and it imports `requests`) and `shop.broken | - | standalone`; and that no temporary directory path, `portable` folder name, date or hash appears anywhere. If anything environment-specific appears, fix the production code, not the golden.

- [ ] **Step 7: Run the golden and bump-gate tests, then the whole suite**

Run: `.venv/Scripts/python -m pytest tests/test_golden.py tests/test_check_golden_bump.py tests/test_determinism.py -v`
Expected: all pass.
Run: `.venv/Scripts/python -m pytest -q`
Expected: everything passes.

- [ ] **Step 8: Commit**

```bash
git add .gitattributes scripts tests/fixture_repos.py tests/golden tests/test_determinism.py tests/test_golden.py tests/test_check_golden_bump.py
git commit -q -m "test: determinism suite, portable golden output and the golden bump gate" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 15: Contract tests, CI matrix, release workflow, self-hosting

**Files:**
- Create: `tests/test_contract.py`, `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.pre-commit-hooks.yaml`, `scripts/check_patch_release.py`, `tests/test_check_patch_release.py`
- Create by running the tool on itself: `indextool.toml`, `AGENTS.md`, `docs/architecture.md`, `docs/architecture.index.txt`
- Modify: `.gitattributes` (appended by `init`)

**Interfaces:**
- Produces (`scripts/check_patch_release.py`): `parse_tag(tag: str) -> tuple[int, int, int]` (raises `ValueError` for anything but `vX.Y.Z`); `declared_version(root: Path) -> str` (the `__version__` in `src/indextool/__init__.py`); `main(argv: list[str]) -> int` where `argv[1]` is the tag: exit 2 for a bad tag or a tag that does not match `__version__`, exit 0 for `vX.Y.0`, and for `vX.Y.Z` with `Z > 0` exit 1 when any file under `tests/golden` differs from its content at `vX.Y.0`.

- [ ] **Step 1: Write the contract tests**

`tests/test_contract.py`:

```python
import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "indextool"
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_package_imports_only_the_standard_library():
    stdlib = set(sys.stdlib_module_names)
    for path in sorted(SRC.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] in stdlib, (path.name, alias.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert node.module.split(".")[0] in stdlib, (path.name, node.module)


def test_no_runtime_dependencies_are_declared_and_the_floor_is_python_3_11():
    assert PYPROJECT["project"]["dependencies"] == []
    assert PYPROJECT["project"]["requires-python"] == ">=3.11"


def test_splitlines_is_not_used_in_the_package():
    for path in sorted(SRC.glob("*.py")):
        assert ".splitlines(" not in path.read_text(encoding="utf-8"), path.name


def test_the_entry_point_is_the_cli_main():
    assert PYPROJECT["project"]["scripts"] == {"indextool": "indextool.cli:main"}


def test_the_pre_commit_hook_verifies_the_index():
    text = (ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    assert "entry: indextool verify --source index" in text and "id: indextool-verify" in text
```

- [ ] **Step 2: Create the pre-commit hook definition, then run the contract tests**

`.pre-commit-hooks.yaml`:

```yaml
- id: indextool-verify
  name: indextool verify
  description: Fail the commit when the committed architecture map is stale.
  entry: indextool verify --source index
  language: python
  pass_filenames: false
  always_run: true
```

Run: `.venv/Scripts/python -m pytest tests/test_contract.py -v`
Expected: all pass. A failure of the first test names the file and the import that is not standard library; remove the import.

- [ ] **Step 3: Write the failing patch-release tests**

`tests/test_check_patch_release.py`:

```python
import importlib.util
from pathlib import Path

import pytest

from tests.helpers import commit_all, git, make_repo


def load():
    path = Path(__file__).resolve().parent.parent / "scripts" / "check_patch_release.py"
    spec = importlib.util.spec_from_file_location("check_patch_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_tag():
    m = load()
    assert m.parse_tag("v1.22.3") == (1, 22, 3)
    for bad in ("1.2.3", "v1.2", "v1.2.3rc1", "release-1"):
        with pytest.raises(ValueError):
            m.parse_tag(bad)


def make_project(tmp_path, version, golden):
    return make_repo(
        tmp_path,
        {
            "src/indextool/__init__.py": f'__version__ = "{version}"\n',
            "tests/golden/g.md": golden,
        },
    )


def test_declared_version_and_tag_mismatch_is_an_error(tmp_path, monkeypatch):
    m = load()
    repo = make_project(tmp_path, "0.1.0", "Generated by indextool 0.1\nbody\n")
    monkeypatch.chdir(repo)
    assert m.declared_version(repo) == "0.1.0"
    assert m.main(["check", "v0.2.0"]) == 2
    assert m.main(["check", "nonsense"]) == 2
    assert m.main(["check", "v0.1.0"]) == 0


def test_a_patch_release_must_not_change_the_goldens(tmp_path, monkeypatch):
    m = load()
    repo = make_project(tmp_path, "0.1.0", "Generated by indextool 0.1\nbody\n")
    git(repo, "tag", "v0.1.0")
    (repo / "src" / "indextool" / "__init__.py").write_text('__version__ = "0.1.1"\n', encoding="utf-8")
    commit_all(repo, "patch")
    monkeypatch.chdir(repo)
    assert m.main(["check", "v0.1.1"]) == 0
    (repo / "tests" / "golden" / "g.md").write_text("Generated by indextool 0.1\nchanged\n", encoding="utf-8")
    commit_all(repo, "output changed in a patch")
    assert m.main(["check", "v0.1.1"]) == 1
```

- [ ] **Step 4: Run to see them fail, then implement**

Run: `.venv/Scripts/python -m pytest tests/test_check_patch_release.py -v`
Expected: FAIL (the script does not exist: `FileNotFoundError`).

`scripts/check_patch_release.py`:

```python
"""Before publishing vX.Y.Z with Z > 0, assert the golden output equals that of vX.Y.0.

Usage: python scripts/check_patch_release.py <tag>

Patch releases are output-neutral by policy, so users who pin `indextool~=X.Y.0` never have to regenerate."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

GOLDEN_DIR = "tests/golden"
_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)\Z")
_DECLARED = re.compile(r'^__version__ = "([^"]+)"', re.MULTILINE)


def parse_tag(tag: str) -> tuple[int, int, int]:
    match = _TAG.match(tag)
    if not match:
        raise ValueError(f"not a release tag: {tag!r}")
    major, minor, patch = (int(g) for g in match.groups())
    return major, minor, patch


def declared_version(root: Path) -> str:
    text = (root / "src" / "indextool" / "__init__.py").read_text(encoding="utf-8")
    match = _DECLARED.search(text)
    if not match:
        raise ValueError("no __version__ in src/indextool/__init__.py")
    return match.group(1)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout.decode("utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_patch_release.py <tag>", file=sys.stderr)
        return 2
    tag = argv[1]
    try:
        major, minor, patch = parse_tag(tag)
        declared = declared_version(Path.cwd())
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if declared != f"{major}.{minor}.{patch}":
        print(f"tag {tag} does not match __version__ {declared}", file=sys.stderr)
        return 2
    if patch == 0:
        return 0
    base_tag = f"v{major}.{minor}.0"
    names = [n for n in _git("ls-tree", "-r", "--name-only", base_tag, "--", GOLDEN_DIR).split("\n") if n]
    problems = []
    for name in names:
        old = _git("show", f"{base_tag}:{name}").replace("\r\n", "\n")
        path = Path(name)
        new = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else None
        if old != new:
            problems.append(name)
    if problems:
        print(f"{tag} changes golden output relative to {base_tag}; a patch release must be output-neutral:")
        for name in problems:
            print(f"  {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

Run: `.venv/Scripts/python -m pytest tests/test_check_patch_release.py -v`
Expected: all pass.

- [ ] **Step 5: Add the CI and release workflows**

`.github/workflows/ci.yml`:

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python: ["3.11", "3.12", "3.13", "3.14"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
          allow-prereleases: true
      - run: python -m pip install -e ".[dev]"
      - run: python -m pytest
      - name: The committed architecture map of this repository is current
        run: python -m indextool verify
      - name: Docs cite existing tests
        run: python scripts/check_doc_tests.py
      - name: Golden output changed without a minor bump
        if: github.event_name == 'pull_request' && matrix.os == 'ubuntu-latest' && matrix.python == '3.12'
        run: python scripts/check_golden_bump.py origin/${{ github.base_ref }}
```

`.github/workflows/release.yml`:

```yaml
name: release
on:
  push:
    tags: ["v*"]
jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install build -e ".[dev]"
      - name: Tag matches __version__, and a patch release is output-neutral
        run: python scripts/check_patch_release.py "$GITHUB_REF_NAME"
      - run: python -m pytest
      - run: python -m build
      - uses: pypa/gh-action-pypi-publish@release/v1
```

`scripts/check_doc_tests.py` is created in Task 16; the CI step that runs it fails until then, so do not push before Task 16 is committed.

- [ ] **Step 6: Self-host: run the tool on its own repository**

```bash
cd /c/python/indextool
git status --short            # expect a clean tree except the files from this task
.venv/Scripts/python -m indextool init --hook none
rm -f .github/workflows/indextool.yml
git add indextool.toml AGENTS.md docs/architecture.md docs/architecture.index.txt .gitattributes
.venv/Scripts/python -m indextool verify
```

Expected: `init` reports created items for `indextool.toml` (with `roots = ["src"]`), `AGENTS.md`, `.gitattributes` (updated), the workflow, and the two generated files; the workflow is then removed because this repository verifies itself in `ci.yml` with the local install. `verify` prints `is current` twice and exits 0, with no "no managed pointer block" note.

Open `docs/architecture.md` and confirm the first line is `# Architecture map: indextool` and that the modules listed are the ones under `src/indextool`.

- [ ] **Step 7: Run everything and commit**

Run: `.venv/Scripts/python -m pytest -q`
Expected: everything passes.

```bash
git add tests/test_contract.py tests/test_check_patch_release.py scripts/check_patch_release.py .pre-commit-hooks.yaml .github indextool.toml AGENTS.md docs/architecture.md docs/architecture.index.txt .gitattributes
git commit -q -m "ci: matrix, release workflow, contract tests, self-hosted architecture map" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
.venv/Scripts/python -m indextool verify --source index
```
Expected: the last command prints `is current` twice: the committed map describes the committed code.

From this point, any change under `src/` must be followed by `python -m indextool generate` and a commit of `docs/`, or `verify` (locally and in CI) fails. That is the tool doing its job on itself.

---

### Task 16: Documentation, parity script and the doc-test checker

**Files:**
- Create: `README.md` (replacing the stub), `CHANGELOG.md`, `docs/rules.md`, `docs/config.md`, `docs/trial.md`, `scripts/parity.py`, `scripts/check_doc_tests.py`
- Test: `tests/test_parity.py`, `tests/test_check_doc_tests.py`, `tests/test_readme.py`

**Interfaces:**
- Produces (`scripts/check_doc_tests.py`): `missing_citations(doc_text: str, root: Path) -> list[str]` (citations of the form `` `tests/<file>.py::<test_name>` `` whose file or `def <test_name>(` does not exist under `root`); `main() -> int` checking `docs/rules.md`, exit 1 when any citation is dangling.
- Produces (`scripts/parity.py`): `reduce(kind: str, text: str) -> list[str]` (the lines that remain after the allowed categories are removed; `kind` is `"map"` or `"index"`); `main(argv: list[str]) -> int` for `python scripts/parity.py {map|index} EXPECTED ACTUAL`, exit 0 when the reduced texts are identical, 1 otherwise, printing the differing lines. The script and its public test are generic and synthetic; the parity run against the private reference repository is a manual, local step (Task 17, Step 2) and its outputs never enter this repository.

Allowed categories (spec 8.2, gate 2): for a map, its first three lines (title, blank line, intro), every line from the `## What this` heading to the end, every `Detector:` line, every `None found by this detector.` line, and the excluded-file and unparsable-file count lines; for an index, its first line. The script is generic: it names no project.

- [ ] **Step 1: Write the failing tests**

`tests/test_check_doc_tests.py`:

```python
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    path = ROOT / "scripts" / "check_doc_tests.py"
    spec = importlib.util.spec_from_file_location("check_doc_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dangling_citations_are_reported(tmp_path):
    m = load()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_present():\n    pass\n", encoding="utf-8")
    text = "`tests/test_a.py::test_present` and `tests/test_a.py::test_gone` and `tests/test_b.py::test_x`"
    assert m.missing_citations(text, tmp_path) == ["`tests/test_a.py::test_gone`", "`tests/test_b.py::test_x`"]


def test_every_citation_in_the_real_rules_document_exists():
    m = load()
    text = (ROOT / "docs" / "rules.md").read_text(encoding="utf-8")
    assert m.missing_citations(text, ROOT) == []
    assert text.count("`tests/") >= 20  # the rules document really does cite its pinning tests
```

`tests/test_parity.py`:

```python
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("parity", ROOT / "scripts" / "parity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REFERENCE_MAP = "\n".join(
    [
        "# Architecture skeleton: some_folder",
        "",
        "Derived from the code by a generator.",
        "",
        "## In numbers",
        "- 3 modules",
        "",
        "## HTTP surface",
        "2 routes in 1 file: `web` (2).",
        "",
        "## What this skeleton does not say",
        "- reasons",
    ]
)
OUR_MAP = "\n".join(
    [
        "# Architecture map",
        "",
        "Generated by indextool 0.1 from the source code.",
        "",
        "## In numbers",
        "- 3 modules",
        "- 4 files excluded by the configured `exclude` patterns",
        "- 1 file could not be parsed (counted as a module with no imports)",
        "",
        "## HTTP surface",
        "Detector: functions decorated with `.route(...)`.",
        "2 routes in 1 file: `web` (2).",
        "",
        "## What this map cannot say",
        "- other reasons",
    ]
)


def test_allowed_categories_are_ignored():
    m = load()
    assert m.reduce("map", REFERENCE_MAP) == m.reduce("map", OUR_MAP)


def test_a_real_difference_is_flagged(tmp_path, capsys):
    m = load()
    expected = tmp_path / "expected.md"
    actual = tmp_path / "actual.md"
    expected.write_text(REFERENCE_MAP, encoding="utf-8")
    actual.write_text(OUR_MAP.replace("- 3 modules", "- 4 modules"), encoding="utf-8")
    assert m.main(["parity", "map", str(expected), str(actual)]) == 1
    assert "4 modules" in capsys.readouterr().out
    actual.write_text(OUR_MAP, encoding="utf-8")
    assert m.main(["parity", "map", str(expected), str(actual)]) == 0


def test_index_kind_ignores_only_the_first_line():
    m = load()
    assert m.reduce("index", "# header one\na | x | lib\nb | y | standalone") == m.reduce(
        "index", "# other header\na | x | lib\nb | y | standalone"
    )
    assert m.reduce("index", "# h\na | x | lib") != m.reduce("index", "# h\na | x | standalone")


def test_bad_usage_is_exit_code_2():
    assert load().main(["parity", "map", "only-one-file"]) == 2
```

`tests/test_readme.py`:

```python
import re
from pathlib import Path

README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")


def test_the_headline_claim_is_only_what_ci_enforces():
    first_paragraph = README.split("\n\n")[1]
    assert "cannot silently diverge" in first_paragraph


def test_limits_are_stated_up_front():
    top = README[:2500]
    assert "Python only" in top
    assert "structure, not intent" in top
    assert "importlib" in README


def test_no_token_saving_figure_is_advertised():
    assert not re.search(r"\d+\s*%", README)
    assert "fewer tokens" not in README.lower()


def test_related_work_credits_prior_art_without_claiming_a_new_category():
    assert "Related work" in README
    assert "not a new category" in README
```

- [ ] **Step 2: Run to see them fail**

Run: `.venv/Scripts/python -m pytest tests/test_check_doc_tests.py tests/test_parity.py tests/test_readme.py -v`
Expected: FAIL (the scripts and documents do not exist yet).

- [ ] **Step 3: Implement the two scripts**

`scripts/check_doc_tests.py`:

```python
"""Fail when docs/rules.md cites a test that does not exist. Usage: python scripts/check_doc_tests.py

The documentation of what is computed must not silently diverge from the tests that pin it: the same idea the tool
applies to the architecture map."""
from __future__ import annotations

import re
import sys
from pathlib import Path

CITATION = re.compile(r"`(tests/[\w/]+\.py)::(\w+)`")


def missing_citations(doc_text: str, root: Path) -> list[str]:
    missing: list[str] = []
    for match in CITATION.finditer(doc_text):
        path = root / match.group(1)
        found = path.is_file() and re.search(
            rf"^def {re.escape(match.group(2))}\(", path.read_text(encoding="utf-8"), re.MULTILINE
        )
        if not found:
            missing.append(match.group(0))
    return missing


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    missing = missing_citations((root / "docs" / "rules.md").read_text(encoding="utf-8"), root)
    if missing:
        print("docs/rules.md cites tests that do not exist:")
        for citation in missing:
            print(f"  {citation}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/parity.py`:

```python
"""Compare indextool output with another generator's output and classify every differing line.

Usage: python scripts/parity.py {map|index} EXPECTED ACTUAL

Exit 0 when the two texts are identical once the allowed categories are removed, 1 otherwise. The script names no
project; the parity config and the reference outputs are kept outside this repository."""
from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

MAP_HEAD_LINES = 3
CANNOT_SAY_HEADING = "## What this"
_ALLOWED_ANYWHERE = [
    re.compile(r"^Detector: "),
    re.compile(r"^None found by this detector\.$"),
    re.compile(r"^- \d+ files? excluded by the configured"),
    re.compile(r"^- \d+ files? could not be parsed"),
]


def reduce(kind: str, text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").rstrip("\n").split("\n")
    if kind == "index":
        return lines[1:]
    lines = lines[MAP_HEAD_LINES:]
    for i, line in enumerate(lines):
        if line.startswith(CANNOT_SAY_HEADING):
            lines = lines[:i]
            break
    return [line for line in lines if not any(rx.match(line) for rx in _ALLOWED_ANYWHERE)]


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] not in ("map", "index"):
        print("usage: parity.py {map|index} EXPECTED ACTUAL", file=sys.stderr)
        return 2
    kind = argv[1]
    expected = reduce(kind, Path(argv[2]).read_text(encoding="utf-8"))
    actual = reduce(kind, Path(argv[3]).read_text(encoding="utf-8"))
    if expected == actual:
        print("parity: identical apart from the allowed categories")
        return 0
    print("parity: the outputs differ outside the allowed categories:")
    for line in list(difflib.unified_diff(expected, actual, "expected", "actual", lineterm="", n=0))[:80]:
        print(line)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: Write `docs/rules.md`**

Each rule cites the test that pins it. Test names must match the tests written in Tasks 2 to 14.

```markdown
# What indextool computes

Every rule below is pinned by a test, named in the right-hand column. `scripts/check_doc_tests.py` fails CI when a
cited test does not exist, so this page cannot silently drift from the code.

## Which files are read

| Rule | Pinned by |
|---|---|
| In a git work tree only tracked regular `.py` files count, sorted by path; untracked files never do. | `tests/test_sources.py::test_git_mode_lists_tracked_python_files_only_and_sorted` |
| Symlinks and gitlinks are skipped by their index mode, identically on every OS. | `tests/test_sources.py::test_symlink_and_gitlink_entries_are_skipped_by_mode` |
| A tracked file deleted from the working tree is skipped in worktree mode. | `tests/test_sources.py::test_tracked_but_deleted_files_are_skipped_in_worktree_mode` |
| `--source index` reads the staged content, not the working tree. | `tests/test_sources.py::test_index_source_reads_staged_content_not_the_working_tree` |
| `exclude` patterns remove files and the count is reported. | `tests/test_sources.py::test_exclude_patterns_drop_files_and_are_counted` |
| Two paths that differ only by case are an error. | `tests/test_sources.py::test_paths_that_differ_only_by_case_are_an_error` |
| Unmerged index entries are an error. | `tests/test_sources.py::test_unmerged_paths_are_an_error` |
| Outside git a sorted walk skips `venv`, `node_modules`, `__pycache__` and similar directories. | `tests/test_sources.py::test_walk_mode_skips_default_excludes_and_symlinks_and_is_sorted` |
| Sources are decoded by their PEP 263 cookie or BOM, never the locale; newlines become LF. | `tests/test_decode.py::test_bom_is_stripped_and_newlines_are_normalized` |
| A bad cookie or a BOM/cookie mismatch makes the file an unparsable module, never a crash. | `tests/test_decode.py::test_unknown_cookie_and_bom_mismatch_are_not_ok_and_never_raise` |
| Globs follow gitignore rules without negation. | `tests/test_globs.py::test_glob_matching` |

## Modules and import edges

| Rule | Pinned by |
|---|---|
| A module key is its path under a root, dotted; `pkg/__init__.py` is `pkg`. | `tests/test_scan.py::test_module_keys` |
| Roots relativize keys; files outside every root are ignored. | `tests/test_scan.py::test_roots_relativize_keys_and_files_outside_are_ignored` |
| Two files with the same key are an error. | `tests/test_scan.py::test_two_files_with_the_same_key_are_an_error` |
| A test module matches a `tests` pattern and appears only in the module count. | `tests/test_scan.py::test_test_modules_follow_the_tests_patterns` |
| Absolute, relative and submodule imports resolve to the longest known repository module; the rest are dropped. | `tests/test_scan.py::test_edges_absolute_relative_and_submodule_imports` |
| Function-level and conditional imports are edges. | `tests/test_scan.py::test_function_level_and_conditional_imports_are_edges` |
| A file that cannot be parsed is a module with no imports, and is counted. | `tests/test_scan.py::test_unparsable_files_are_counted_modules_with_only_their_raw_text` |
| The title is the first non-empty docstring line; lines are split on `\n` only. | `tests/test_scan.py::test_a_docstring_with_a_form_feed_and_u2028_stays_one_line` |

## Graph

| Rule | Pinned by |
|---|---|
| A library module has at least one non-test importer; the rest are standalone. | `tests/test_graph.py::test_library_and_standalone_ignore_test_importers` |
| Depth is one more than the deepest import; tests are ignored. | `tests/test_graph.py::test_depth_is_one_more_than_the_deepest_import` |
| Modules in a cycle share a depth. | `tests/test_graph.py::test_cycle_members_share_a_depth_and_are_reported` |
| Cycles are ordered largest first, then by name. | `tests/test_graph.py::test_cycles_are_ordered_largest_first_then_by_name` |
| A name is a look-alike when two or more library modules define it. | `tests/test_graph.py::test_duplicate_names_need_two_library_definitions` |

## Tables, routes and IO

| Rule | Pinned by |
|---|---|
| Tables, users and writers come from `CREATE TABLE` in string literals. | `tests/test_facts.py::test_created_tables_users_and_writers` |
| Docstrings and comments are not evidence; f-string values stand in as `?`. | `tests/test_facts.py::test_docstrings_and_comments_are_not_evidence_and_fstrings_count` |
| Table names are escaped and matched longest first. | `tests/test_facts.py::test_custom_create_pattern_and_table_names_are_escaped` |
| Test modules contribute no facts. | `tests/test_facts.py::test_test_modules_contribute_nothing` |
| A route is a listed decorator call with a literal first argument starting with `/`. | `tests/test_scan.py::test_routes_require_a_listed_decorator_and_a_literal_path_starting_with_a_slash` |
| The IO rating comes from imports matched by dotted prefix; SQL text alone is not evidence. | `tests/test_facts.py::test_io_rating` |

## Output

| Rule | Pinned by |
|---|---|
| The header carries the title and `indextool <major.minor>`; the numbers section counts what it says. | `tests/test_render.py::test_header_and_numbers` |
| Every list is capped and ends with a "(+N more)" line. | `tests/test_render.py::test_lists_are_capped_with_a_more_line` |
| Detector lines and the "cannot say" list come from the active config. | `tests/test_render.py::test_detector_lines_and_cannot_say_reflect_the_config` |
| The index has one line per non-test module. | `tests/test_render.py::test_index_lines` |
| The output does not depend on input order. | `tests/test_render.py::test_output_does_not_depend_on_input_order` |

## Determinism and verification

| Rule | Pinned by |
|---|---|
| Hash seed, folder name, working directory, CRLF and locale do not change a byte. | `tests/test_determinism.py::test_hash_seed_does_not_matter` |
| A renamed copy produces identical output. | `tests/test_determinism.py::test_renamed_copies_produce_identical_output` |
| Untracked files and default-excluded directories change nothing. | `tests/test_determinism.py::test_untracked_files_and_default_excluded_directories_change_nothing` |
| Worktree and index outputs match on a clean tree and differ on a dirty one. | `tests/test_determinism.py::test_worktree_and_index_outputs_match_on_a_clean_tree_and_differ_on_a_dirty_one` |
| The portable fixture matches its golden output on every OS and Python. | `tests/test_golden.py::test_portable_fixture_matches_the_golden_output` |
| `verify` fails on drift and says how to fix it. | `tests/test_cli_verify_refresh.py::test_verify_fails_when_an_import_changes_and_says_how_to_fix_it` |
| `verify` accepts CRLF in the committed map. | `tests/test_cli_verify_refresh.py::test_verify_accepts_crlf_line_endings_in_the_committed_map` |
| `verify --source index` checks what would be committed. | `tests/test_cli_verify_refresh.py::test_index_source_checks_what_would_be_committed` |
| An untracked config makes `verify` exit 2, naming it. | `tests/test_cli_verify_refresh.py::test_verify_names_an_untracked_config_and_exits_2` |
| `refresh` is silent, fails open and never replaces a good map with an empty one. | `tests/test_cli_verify_refresh.py::test_refresh_never_replaces_a_good_map_with_an_empty_one` |
| A hand-edited pointer block makes `verify` exit 2. | `tests/test_pointer.py::test_verify_exits_2_when_a_block_was_edited_by_hand` |

## What the map cannot see

Why a module exists, how modules cooperate beyond importing each other, formulas and thresholds, imports made through
`importlib`, `exec` or `sys.path` changes, tables not created by a matching `CREATE TABLE` in a string literal, routes
not registered by a listed decorator with a literal `/` path, and anything that is not Python source. Every generated
map states this in its closing section, built from the active configuration.

## Reading traps

- `top level` includes package `__init__` files: a package's own key has no dot.
- Depth is height in the import graph, not architectural layering, and function-level imports inflate it.
- A standalone module is not unused; it means no module imports it. A shell script may still run it.
- A standalone module with routes may not be mounted; check how the server registers it.
- Table rank is breadth (how many modules mention the table), not importance.
- `written by` includes the module that creates a table, so migration and backfill scripts appear in it.
- Counts are exact; a module's role is inferred from its name and title only.
```

- [ ] **Step 5: Write `docs/config.md`, `docs/trial.md`, `README.md` and `CHANGELOG.md`**

`docs/config.md`:

```markdown
# Configuration

indextool reads `indextool.toml` in the base directory; failing that, the `[tool.indextool]` table of `pyproject.toml`;
failing that, defaults. The base directory is the directory holding the config, found by searching upward from the
working directory to the git top level; with no config it is the git top level, or the working directory outside git.
`--config PATH` overrides. Relative paths in the config resolve against the base directory, never the working
directory. Unknown keys, invalid regexes, nested roots and other mistakes are errors that name the key (exit code 2).
In git mode the config file must be tracked, or `verify` exits 2.

In `pyproject.toml` the same keys are nested under `[tool.indextool]`.

## Top-level keys

| Key | Default | Meaning |
|---|---|---|
| `title` | `[project].name` of the base directory's `pyproject.toml`, else none | Shown as `# Architecture map: <title>`. The folder name is never used. |
| `roots` | `["."]` | Source roots. Module keys are paths under a root. Roots must not nest or repeat. `init` writes `["src"]` when `src/` holds Python files. |
| `exclude` | `[]` | Glob patterns for files to leave out. The number removed is printed in the map. |
| `tests` | `["test_*.py", "*_test.py", "tests/", "test/"]` | Glob patterns for test modules. |
| `architecture` | `"docs/architecture.md"` | Where the map is written. |
| `index` | `"docs/architecture.index.txt"` | Where the index is written. |
| `discovery` | `"auto"` | `auto`: git when inside a work tree, else a directory walk. `git` and `walk` force one. |

## Glob patterns

`exclude` and `tests` use gitignore rules without negation: a trailing `/` means a directory; a leading `/` anchors to
the base directory; `**` spans directories; otherwise `*` and `?` do not cross `/`; a pattern with no other `/` matches
at any depth; `[...]` is a character class; matching is case-sensitive; backslashes are treated as `/`. `!` is an error.

## Detectors

Detectors are data. Nothing executes your code: decorators and imports come from the syntax tree, and regexes run only
over string literals (never docstrings).

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
- **SQL.** `create` has exactly one capture group, the table name. `use` and `write` contain `@TABLES@` exactly once,
  inside one capture group; it is replaced by the created names, each escaped, longest first. `write_any` has no
  placeholder. `CREATE TEMP TABLE` is deliberately not counted by `create`: a temporary table is session-scoped, not
  schema.
```

`docs/trial.md`:

```markdown
# Measure it on your own repository

Two afternoons. Decide the bar before you run anything, and report both directions.

**Setup.** Same commit, a fresh session per run, same model and settings. Arm A: your current architecture notes and
no map. Arm B: the map, the pointer and the hook installed by `indextool init`. Four runs per task per arm.

**Tasks.** One architecture overview ("describe how this system is laid out and what writes its main tables"); one
lookup a grep answers ("where is X computed"); one trivial named edit. Optionally one impact task ("change table T's
schema and update its dependents").

**Measure.** Tokens after the first turn and the tool-call count, from the transcript; wrong claims per overview,
counted by a blind grader with a fixed rubric; pass or fail on the edits.

**Bar.** Overview: at least 15% fewer tokens at no loss of accuracy. Trivial edit: no more than 5% extra cost.
Lookup: expect no change.

**Report both directions.** A result that misses the bar is still a result. If the overview bar is missed but the
notes you had were found to be wrong, the freshness guarantee is the reason to keep the map, not the token count.

The pointer text `init` writes carries no numbers, because a figure in hand-written text goes stale. If you change the
wording, measure it the same way: how the pointer is worded changes how often the assistant opens the map.
```

`README.md`:

````markdown
# indextool

The committed architecture map of a Python repository cannot silently diverge from the code: `indextool verify` fails
the build the moment it does.

indextool reads your source with the standard library, writes an architecture map and a one-line-per-module index,
and gives your coding agent a short pointer to them. There is no service, no model call and nothing to install beyond
Python. Python only, and it describes structure, not intent: imports, dependency layers, cycles, routes, tables and
their writers, look-alike names. It cannot see why a module exists, and it cannot see imports made through
`importlib`.

```
your repository -> indextool generate -> docs/architecture.md, docs/architecture.index.txt
                -> committed -> pointer in AGENTS.md or CLAUDE.md -> your coding agent
CI: indextool verify -> regenerate in memory, compare bytes -> stale? fail : pass
```

## Quickstart

```
pip install indextool
indextool init
git add -A && git commit -m "Adopt indextool"
```

`init` writes `indextool.toml`, a managed pointer block in your agent instruction files, a Claude Code SessionStart
hook, a GitHub Actions workflow and `.gitattributes` lines, then generates the two files. It never overwrites an
existing config or workflow, and `--dry-run` shows what it would do.

## Commands

| Command | What it does |
|---|---|
| `indextool generate` | Write the map and the index. |
| `indextool verify` | Exit 0 when both committed files are current, 1 on drift, 2 on misconfiguration. |
| `indextool refresh` | Silent, fail-open regeneration for a session-start hook. |
| `indextool init` | One-time setup, safe to re-run. |

`--source index` reads staged content instead of the working tree; use it in pre-commit so the check matches what you
are about to commit.

## Determinism

The output is a pure function of the tracked files, the config, the tool's `major.minor` and the Python
`major.minor`. Folder name, working directory, time, hash seed, locale and line endings do not change a byte. Files
that are not tracked by git are never part of the map. A file that cannot be parsed is counted, not skipped.

## Configuration

See [docs/config.md](docs/config.md). Detectors (route decorators, SQL patterns, IO import lists) are data in the
config; nothing executes your code.

## What is computed

See [docs/rules.md](docs/rules.md); every rule names the test that pins it.

## Measure it yourself

See [docs/trial.md](docs/trial.md).

## Related work

indextool is a specific lightweight pattern, not a new category: derive a small description from source with
standard-library code, commit it, fail CI when it is stale, and point the agent to it instead of injecting it. Related
tools cover parts of that ground: the Repository Intelligence Graph work on deterministic repository maps for coding
agents, Aider's repository map, architecture-diagram tools such as Tecture, ArchDoc and CodeSee, import-boundary
linters such as import-linter, Tach and dependency-cruiser, and code-graph servers that agents query.

## License

MIT.
````

`CHANGELOG.md` (spec 9.2: a change that can alter generated output bumps the minor version and carries an "Output changes" line):

```markdown
# Changelog

A change that can alter the generated files bumps the minor version, and its entry has an "Output changes" line that
tells users to run `indextool generate` and commit the result. Patch releases never change output, so
`pip install "indextool~=X.Y.0"` is safe to pin.

## 0.1.0

First release.

Output changes: none (first release).
```

- [ ] **Step 6: Verify each related-work description before it ships**

For each tool named in the README's "Related work" paragraph, open its own project page and confirm the description in the README is accurate. Edit the sentence to say only what the source supports, or drop the name. Do not describe a project from memory. Record what was checked in the commit message body.

- [ ] **Step 7: Run everything**

Run: `.venv/Scripts/python -m pytest -q && .venv/Scripts/python scripts/check_doc_tests.py`
Expected: everything passes and `check_doc_tests.py` prints nothing and exits 0. If it lists a dangling citation, correct the test name in `docs/rules.md` to the one that exists in the test file.

- [ ] **Step 8: Commit**

```bash
git add README.md CHANGELOG.md docs/rules.md docs/config.md docs/trial.md scripts/parity.py scripts/check_doc_tests.py tests/test_parity.py tests/test_check_doc_tests.py tests/test_readme.py
git commit -q -m "docs: README, rules, config and trial documents; parity and doc-test scripts" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
.venv/Scripts/python -m indextool verify --source index
```
Expected: the last command prints `is current` twice. (Adding documentation and scripts does not touch `src/`, so the self-hosted map is unaffected.)

---

### Task 17: Release gates (manual; nothing here is code)

These are the spec's acceptance gates 2 to 5 (spec 8.2) plus publication hygiene. Gate 1 (the determinism suite and the CI matrix) is the CI run itself. Nothing in this task may put a project-specific name, path, value or number into the repository.

- [ ] **Step 1: Push and get the matrix green.** Create the GitHub repository, push `main`, and open a pull request from a trivial branch so every job runs, including the golden bump gate. Expected: all three operating systems and all four Python versions pass, including the portable golden and the PEP 701 fixture, and the self-hosted `verify` job. If the portable golden differs between Python minors, the tool's output depends on the interpreter for code that parses everywhere: add the Python `major.minor` to the header in `render.py`, regenerate the goldens, bump the minor version, and record the finding in the changelog. This is the empirical answer to spec open item 1.

- [ ] **Step 2: Gate 2, parity on the private reference repository (run privately).** In the private reference repository, regenerate the reference generator's map and index fresh (never read the committed generated files, which can predate the generator's last edit). Write a parity config outside this repository that sets `roots` to the reference's source folder, `decorators = ["route"]`, and the reference's IO libraries with a top-level `urllib` entry; run `indextool generate` against the same commit with that config. Then run `python scripts/parity.py map <reference-map> <indextool-map>` and `python scripts/parity.py index <reference-index> <indextool-index>`. Expected: exit 0 for both. Any line that differs outside the allowed categories is a real difference: decide whether it is a bug in indextool or an intended change, and if it is intended add it to spec 6.2 as a delta. This step is manual and local, and no executor of this plan performs it: the public repository's own `tests/test_parity.py` covers `scripts/parity.py` with synthetic strings only. Keep the config, the outputs and the diff out of this repository, and never turn them into goldens or fixtures; the release notes say only that parity was verified on a private repository of several hundred modules.

- [ ] **Step 3: Gate 3, cold start on three public repositories** with different layouts: a `src/` layout, a flat layout, and a monorepo with two configs. On each, start a stopwatch and run `pip install indextool` (from the built wheel or the index), `indextool init`, commit, push and see the workflow's `verify` job go green; then change one import, push, and see it fail. Expected: under 15 minutes each. Note any friction in `init` output or documentation and fix it.

- [ ] **Step 4: Gate 4, speed.** On the private reference repository run `time indextool refresh` twice. Expected: the second run, which finds nothing to write, is far below the 30 second hook timeout; report the time only. Confirm one scan feeds both files by profiling `sync_files` once (`python -X importtime` is not needed; a single `cProfile` run showing one call to `scan` is enough).

- [ ] **Step 5: Gate 5, pointer wording.** On the private reference repository, using the private trial harness, compare the reference pointer wording (with its token figure) against the number-free wording that `init` writes, following `docs/trial.md`. The winner ships. If the reference wording wins, change `pointer.render_block` to the winning text with the figure computed and rounded by `init` only, update the tests in `tests/test_pointer.py`, bump the minor version, regenerate the goldens, and regenerate the self-hosted docs. Keep the trial's data out of this repository.

- [ ] **Step 6: Publication hygiene.** Run the private-term scan across every commit and the working tree, using the list that lives outside the repository:

```bash
cd /c/python/indextool
clean=$(mktemp)
grep -v -E '^[[:space:]]*(#|$)' ~/.indextool-private-terms > "$clean"
git grep -n -i -E -f "$clean" $(git rev-list --all); echo "exit=$? (1 means no matches)"
git grep -n -i -E -f "$clean"; echo "working tree exit=$?"
git log --all --format=%B | grep -n -i -E -f "$clean"; echo "exit=$?"
rm -f "$clean"
```
Expected: all three print `exit=1`. Then confirm the `LICENSE` copyright line reads as the owner wants it, that the owner has confirmed that code derived from the private repository may be open-sourced, that `indextool` is still free on PyPI and the GitHub name is available, and configure PyPI trusted publishing for the `pypi` environment used by `release.yml`. Publish by pushing a `v0.1.0` tag.

---
