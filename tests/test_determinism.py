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
