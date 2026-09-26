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
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8", newline="\n")
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
    (repo / "sub" / "cfg.toml").write_text("a = 2\n", encoding="utf-8", newline="\n")
    assert sources.read_file(repo / "sub", "cfg.toml", "worktree") == b"a = 2\n"
    assert sources.read_file(repo / "sub", "cfg.toml", "index") == b"a = 1\n"
    assert sources.read_file(repo / "sub", "missing.toml", "worktree") is None
    assert sources.read_file(repo / "sub", "missing.toml", "index") is None
