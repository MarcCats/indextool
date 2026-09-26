import os

import pytest

from indextool.pointer import render_block
from tests.fixture_repos import TINY
from tests.helpers import commit_all, git, make_config, run_cli, write_files

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


def committed_with_config_and_pointer(repo_factory, pointer_file):
    """A committed, current repository whose committed config and pointer file are both up to date."""
    repo = repo_factory({**TINY, "indextool.toml": 'title = "Shop"\n'})
    assert run_cli(repo, "generate").code == 0
    write_files(repo, {pointer_file: render_block(make_config(repo)) + "\n"})
    commit_all(repo, "add maps and pointer")
    clean = run_cli(repo, "verify")
    assert clean.code == 0 and "unstaged" not in clean.err, clean.out + clean.err
    return repo


def test_an_unstaged_edit_of_the_config_warns_in_worktree_mode(repo_factory):
    repo = committed_repo(repo_factory, {**TINY, "indextool.toml": 'title = "Shop"\n'})
    config = repo / "indextool.toml"
    config.write_bytes(config.read_bytes() + b"# a note that changes no output\n")
    result = run_cli(repo, "verify")
    assert result.code == 0, result.out + result.err
    assert "unstaged changes" in result.err and "indextool.toml" in result.err


@pytest.mark.parametrize("pointer_file", ["AGENTS.md", "CLAUDE.md", ".claude/CLAUDE.md"])
def test_an_unstaged_edit_of_a_pointer_file_warns_in_worktree_mode(repo_factory, pointer_file):
    repo = committed_with_config_and_pointer(repo_factory, pointer_file)
    path = repo / pointer_file
    path.write_bytes(path.read_bytes() + b"\nA note added after the managed block.\n")
    result = run_cli(repo, "verify")
    assert result.code == 0, result.out + result.err  # the block itself is unchanged, so only the warning appears
    assert "unstaged changes" in result.err and pointer_file in result.err


def test_source_index_never_warns_about_unstaged_config_or_pointer_edits(repo_factory):
    repo = committed_with_config_and_pointer(repo_factory, "AGENTS.md")
    for rel in ("indextool.toml", "AGENTS.md"):
        path = repo / rel
        path.write_bytes(path.read_bytes() + b"\n# an unstaged note\n")
    worktree = run_cli(repo, "verify")
    assert worktree.code == 0 and "2 tracked file(s) have unstaged changes" in worktree.err  # both files are watched
    result = run_cli(repo, "verify", "--source", "index")
    assert result.code == 0, result.out + result.err
    assert "unstaged" not in result.err


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
