import os
import sys

import pytest

from indextool import cli, gitio
from indextool.pointer import render_block
from tests.fixture_repos import TINY
from tests.helpers import commit_all, git, make_config, run_cli, write_files

PY = f"{sys.version_info.major}.{sys.version_info.minor}"

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
    assert result.code == 1
    # the map in the working tree is right; only the staging is missing (the index file does not list imports)
    assert (
        "indextool: docs/architecture.md is current in the working tree but not staged; "
        "stage it with: git add docs/architecture.md"
    ) in result.out
    assert "indextool: docs/architecture.index.txt is current\n" in result.out.replace("\r\n", "\n")
    assert "regenerate it with" not in result.out  # regenerating changes nothing here
    assert "is unchanged" in run_cli(repo, "generate", "--source", "index").out
    git(repo, "add", "docs")
    assert run_cli(repo, "verify", "--source", "index").code == 0


def test_index_source_says_to_regenerate_and_stage_when_the_working_tree_copy_is_not_right_either(repo_factory):
    repo = committed_repo(repo_factory)
    ledger = repo / "shop" / "ledger.py"
    ledger.write_text(ledger.read_text(encoding="utf-8") + "import shop.orders\n", encoding="utf-8")
    git(repo, "add", "shop/ledger.py")  # staged code, and the map was never regenerated
    result = run_cli(repo, "verify", "--source", "index")
    assert result.code == 1
    assert (
        "indextool: docs/architecture.md is out of date; regenerate it with: indextool generate --source index, "
        "then git add docs/architecture.md"
    ) in result.out
    assert "not staged" not in result.out
    assert run_cli(repo, "generate", "--source", "index").code == 0
    git(repo, "add", "docs")
    assert run_cli(repo, "verify", "--source", "index").code == 0


@pytest.mark.parametrize("ignored", [False, True])
def test_index_source_says_to_stage_an_output_file_that_exists_on_disk_but_is_not_tracked(repo_factory, ignored):
    repo = repo_factory({**TINY, ".gitignore": "docs/\n"} if ignored else TINY)
    assert run_cli(repo, "generate").code == 0
    result = run_cli(repo, "verify", "--source", "index")
    assert result.code == 1
    for rel in MAPS:
        assert f"indextool: {rel} is current in the working tree but not staged; stage it with: git add {rel}" in result.out
    assert "does not exist" not in result.out


def test_index_source_says_to_generate_and_stage_an_output_file_that_exists_nowhere(repo_factory):
    repo = repo_factory(TINY)
    result = run_cli(repo, "verify", "--source", "index")
    assert result.code == 1
    assert (
        "indextool: docs/architecture.md is not in the index; write it with: indextool generate --source index, "
        "then git add docs/architecture.md"
    ) in result.out


def test_worktree_mode_keeps_its_messages(repo_factory):
    repo = committed_repo(repo_factory)
    (repo / "docs" / "architecture.md").unlink()
    (repo / "docs" / "architecture.index.txt").write_bytes(b"# stale\n")
    result = run_cli(repo, "verify")
    out = result.out.replace("\r\n", "\n")
    assert result.code == 1
    assert "indextool: docs/architecture.md does not exist; write it with: indextool generate\n" in out
    assert "indextool: docs/architecture.index.txt is out of date; regenerate it with: indextool generate\n" in out
    assert "not staged" not in out and "git add" not in out


def test_index_source_says_when_a_pointer_file_is_current_in_the_working_tree_but_not_staged(repo_factory):
    repo = committed_repo(repo_factory)
    write_files(repo, {"AGENTS.md": render_block(make_config(repo)) + "\n"})  # written, never staged
    result = run_cli(repo, "verify", "--source", "index")
    assert result.code == 0, result.out + result.err  # the maps are staged and current
    assert "run indextool init to add one" not in result.err
    assert (
        "indextool: the managed pointer block in AGENTS.md is current in the working tree but not staged; "
        "stage it with: git add AGENTS.md"
    ) in result.err.replace("\r\n", "\n")
    git(repo, "add", "AGENTS.md")
    staged = run_cli(repo, "verify", "--source", "index")
    assert staged.code == 0 and "pointer" not in staged.err


def test_index_source_says_to_run_init_and_stage_when_the_unstaged_pointer_block_is_out_of_date(repo_factory):
    repo = committed_repo(repo_factory)
    stale = render_block(make_config(repo)).replace("Read it whole", "Read it")
    write_files(repo, {"AGENTS.md": stale + "\n"})
    result = run_cli(repo, "verify", "--source", "index")
    assert result.code == 0, result.out + result.err
    assert (
        "the managed pointer block in AGENTS.md is out of date in the working tree; run indextool init, "
        "then git add AGENTS.md"
    ) in result.err


def test_index_source_with_no_pointer_block_anywhere_says_to_run_init_and_stage_what_it_writes(repo_factory):
    repo = committed_repo(repo_factory)
    result = run_cli(repo, "verify", "--source", "index")
    assert result.code == 0
    assert (
        "no managed pointer block found in CLAUDE.md, .claude/CLAUDE.md or AGENTS.md; run indextool init to add one, "
        "then git add the file it writes"
    ) in result.err


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


def test_a_git_failure_while_looking_for_unstaged_files_is_one_warning_line_and_changes_nothing(
    repo_factory, monkeypatch, capsys
):
    repo = committed_with_config_and_pointer(repo_factory, "AGENTS.md")
    monkeypatch.chdir(repo)

    def refuse(base):
        raise gitio.GitError("fatal: Unable to create index.lock: File exists.\n\nAnother git process seems to be running")

    monkeypatch.setattr(gitio, "unstaged", refuse)
    assert cli.main(["verify"]) == 0  # current: the advisory warning cannot turn it into a failure
    captured = capsys.readouterr()
    assert captured.out.count("is current") == 2
    assert captured.err.strip().split("\n") == [
        "indextool: warning: could not check for unstaged changes: fatal: Unable to create index.lock: File exists. "
        "Another git process seems to be running"
    ]
    (repo / "docs" / "architecture.md").unlink()
    assert cli.main(["verify"]) == 1  # drift keeps its own exit code
    assert capsys.readouterr().err.strip().count("\n") == 0


def test_a_warning_is_always_one_line_even_when_git_says_several(capsys):
    cli._warn("first line\nsecond line\r\n\n   third\tline  ")
    assert capsys.readouterr().err == "indextool: first line second line third line\n"


@pytest.mark.parametrize("extra,more", [(12, None), (13, 1), (20, 8)])
def test_verify_prints_at_most_twelve_changed_lines_and_counts_the_rest(repo_factory, extra, more):
    repo = committed_repo(repo_factory)
    write_files(repo, {f"extra/m{i:02d}.py": "" for i in range(extra)})
    git(repo, "add", "-A")  # tracked, so that the files are part of the map
    result = run_cli(repo, "verify")
    assert result.code == 1
    lines = result.out.replace("\r\n", "\n").split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith("indextool: docs/architecture.index.txt is out of date"))
    block = []
    for line in lines[start + 1 :]:
        if not line.startswith(("+", "-", "... (")):
            break
        block.append(line)
    assert len(block[:12]) == 12 and all(ln.startswith("+") for ln in block[:12])  # one new index line per new module
    assert block[12:] == ([f"... (+{more} more changed lines)"] if more else [])


def test_a_drift_with_an_unparsable_file_says_to_check_the_python_versions(repo_factory):
    repo = committed_repo(repo_factory, {**TINY, "shop/broken.py": "def broken(:\n"})
    clean = run_cli(repo, "verify")
    assert clean.code == 0 and "failed to parse" not in clean.out
    report = repo / "scripts" / "report.py"
    report.write_text(report.read_text(encoding="utf-8") + "import shop.ledger\n", encoding="utf-8")
    result = run_cli(repo, "verify")
    assert result.code == 1
    assert f"1 file(s) failed to parse under Python {PY}; check that CI and local Python versions match." in result.out


def test_refresh_with_source_index_writes_what_would_be_committed(repo_factory):
    repo = committed_repo(repo_factory)
    ledger = repo / "shop" / "ledger.py"
    ledger.write_text(ledger.read_text(encoding="utf-8") + "import shop.orders\n", encoding="utf-8")  # closes a cycle
    first = run_cli(repo, "refresh", "--source", "index")
    assert first.code == 0 and first.out == ""
    assert "## Import cycles\nNone.\n" in (repo / "docs" / "architecture.md").read_bytes().decode("utf-8")  # unstaged: unseen
    git(repo, "add", "shop/ledger.py")
    second = run_cli(repo, "refresh", "--source", "index")
    assert second.code == 0 and second.out == ""
    assert "- `shop.ledger`, `shop.orders` (2 modules)" in (repo / "docs" / "architecture.md").read_text(encoding="utf-8")


def test_refresh_warns_about_an_untracked_config_and_still_writes(repo_factory):
    repo = repo_factory(TINY)
    (repo / "indextool.toml").write_text('title = "Shop"\n', encoding="utf-8")
    result = run_cli(repo, "refresh")
    assert result.code == 0 and result.out == ""
    assert "indextool: indextool.toml is not tracked by git; CI will not see it" in result.err
    assert "# Architecture map: Shop" in (repo / "docs" / "architecture.md").read_text(encoding="utf-8")
