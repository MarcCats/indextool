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
