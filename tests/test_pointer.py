import pytest

from indextool.errors import ConfigError
from indextool.pointer import (
    BEGIN,
    CANDIDATES,
    END,
    check_pointers,
    has_block,
    imports_agents,
    render_block,
    targets,
    upsert,
)
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
        ({".claude/CLAUDE.md": "@AGENTS.md\n", "AGENTS.md": "y\n"}, ["AGENTS.md"]),
        ({".claude/CLAUDE.md": "@AGENTS.md\n"}, [".claude/CLAUDE.md"]),
        ({"CLAUDE.md": "x\n", ".claude/CLAUDE.md": "@AGENTS.md\n", "AGENTS.md": "y\n"}, ["AGENTS.md"]),
        ({"CLAUDE.md": "x\n", ".claude/CLAUDE.md": "@AGENTS.md\n"}, ["CLAUDE.md", ".claude/CLAUDE.md"]),
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


@pytest.mark.parametrize(
    "text,line",
    [
        (f"intro\n\n{BEGIN}\nUSER CONTENT ONE\nUSER CONTENT TWO\n", 3),
        (f"intro\n\nUSER CONTENT ONE\n{END}\nUSER CONTENT TWO\n", 4),
        (f"{BEGIN}\nUSER CONTENT ONE\n{BEGIN}\nUSER CONTENT TWO\n{END}\n", 1),
    ],
)
def test_upsert_refuses_an_unpaired_marker_and_returns_nothing_to_write(tmp_path, text, line):
    block = render_block(make_config(tmp_path))
    for _ in range(2):
        with pytest.raises(ConfigError, match=f"unpaired indextool marker at line {line}"):
            upsert(text, block)
    assert "USER CONTENT ONE" in text and "USER CONTENT TWO" in text


def test_upsert_refuses_a_second_block(tmp_path):
    block = render_block(make_config(tmp_path))
    with pytest.raises(ConfigError, match="more than one managed pointer block at line 7"):
        upsert(block + "\n\n" + block + "\n", block)


def test_a_prose_mention_of_the_markers_is_not_a_block(tmp_path):
    block = render_block(make_config(tmp_path))
    sentence = "The block runs from `<!-- indextool:begin -->` to `<!-- indextool:end -->` in this file.\n"
    fixed, changed = upsert(sentence, block)
    assert changed and fixed == sentence + "\n" + block + "\n"
    again, changed = upsert(fixed, block)
    assert not changed and again == fixed


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_a_fenced_example_is_skipped_in_favour_of_the_real_block(tmp_path, fence):
    block = render_block(make_config(tmp_path))
    stale = block.replace("Read it whole", "Read it")
    example = f"Example:\n\n{fence}markdown\n{block}\n{fence}\n\n"
    fixed, changed = upsert(example + stale + "\n\nafter\n", block)
    assert changed and fixed == example + block + "\n\nafter\n"
    again, changed = upsert(fixed, block)
    assert not changed and again == fixed
    current = example.replace("Read it whole", "Read it") + block + "\n"
    kept, changed = upsert(current, block)
    assert not changed and kept == current


def test_markers_only_inside_a_fence_mean_no_block(tmp_path):
    block = render_block(make_config(tmp_path))
    text = f"```\n{block}\n```\n"
    fixed, changed = upsert(text, block)
    assert changed and fixed == text + "\n" + block + "\n"


def test_an_unclosed_fence_is_refused_rather_than_appended_to_again_and_again(tmp_path):
    block = render_block(make_config(tmp_path))
    with pytest.raises(ConfigError, match="unclosed code fence at line 3"):
        upsert("notes\n\n```python\nprint(1)\n", block)


def test_check_pointers_reports_unpaired_markers_and_a_second_block(repo_factory):
    repo = repo_factory(TINY)
    cfg = make_config(repo)
    block = render_block(cfg)
    write_files(repo, {"CLAUDE.md": block + "\n\n" + block + "\n", "AGENTS.md": f"# Notes\n\n{BEGIN}\nUSER CONTENT\n"})
    problems, found = check_pointers(cfg, "worktree")
    assert found is True
    assert problems == [
        "CLAUDE.md: more than one managed pointer block at line 7; fix the markers by hand, then run: indextool init",
        "AGENTS.md: unpaired indextool marker at line 3; fix the markers by hand, then run: indextool init",
    ]


def test_check_pointers_skips_fenced_examples(repo_factory):
    repo = repo_factory(TINY)
    cfg = make_config(repo)
    block = render_block(cfg)
    stale = block.replace("Read it whole", "Read it")
    write_files(repo, {"CLAUDE.md": f"```\n{block}\n```\n", "AGENTS.md": f"```\n{stale}\n```\n\n{block}\n"})
    assert check_pointers(cfg, "worktree") == ([], True)
    write_files(repo, {"AGENTS.md": f"```\n{block}\n```\n\n{stale}\n"})
    assert check_pointers(cfg, "worktree") == (
        ["AGENTS.md: the managed pointer block is out of date; run: indextool init"],
        True,
    )
    write_files(repo, {"CLAUDE.md": "text\n\n```\nunclosed\n", "AGENTS.md": "plain\n"})
    assert check_pointers(cfg, "worktree") == ([], False)


def test_verify_exits_2_on_an_unpaired_marker_and_leaves_the_file_alone(repo_factory):
    repo = repo_factory(TINY)
    assert run_cli(repo, "generate").code == 0
    original = f"# Notes\n\n{BEGIN}\nUSER CONTENT ONE\nUSER CONTENT TWO\n"
    write_files(repo, {"AGENTS.md": original})
    commit_all(repo)
    result = run_cli(repo, "verify")
    assert result.code == 2
    assert "AGENTS.md: unpaired indextool marker at line 3" in result.out
    assert "no managed pointer block" not in result.err
    assert (repo / "AGENTS.md").read_bytes() == original.encode("utf-8")


def test_has_block_uses_the_same_scanner_and_never_raises(tmp_path):
    block = render_block(make_config(tmp_path))
    assert has_block(f"# Notes\n\n{block}\n")
    assert not has_block("# Notes\n\nplain text\n")
    assert not has_block("")
    assert not has_block(f"```\n{block}\n```\n")  # a fenced example is not a block
    assert not has_block("The block runs from `<!-- indextool:begin -->` to `<!-- indextool:end -->`.\n")
    assert not has_block("text\n\n```\nunclosed fence\n")
    assert has_block(f"```\n{block}\n```\n\n{block}\n")  # a real block after a fenced example
    # An unpaired marker counts as a block, so that upsert then raises instead of appending a second block.
    assert has_block(f"# Notes\n\n{BEGIN}\nUSER CONTENT\n")
    assert has_block(f"# Notes\n\n{END}\n")
    assert has_block(block + "\n\n" + block + "\n")
