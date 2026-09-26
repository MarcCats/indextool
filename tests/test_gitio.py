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


def test_cat_blobs_missing_spec_containing_spaces_raises_git_error(repo_factory):
    repo = repo_factory({"my file.py": "x = 1\n"})
    assert gitio.cat_blobs(repo, [":./my file.py"]) == [b"x = 1\n"]
    with pytest.raises(gitio.GitError):
        gitio.cat_blobs(repo, [":./no such.py"])


def test_is_tracked_treats_the_path_literally_not_as_a_glob(repo_factory):
    repo = repo_factory({"a1.py": "x = 1\n"})
    (repo / "a[1].py").write_text("", encoding="utf-8")
    assert gitio.is_tracked(repo, "a1.py") is True
    assert gitio.is_tracked(repo, "a[1].py") is False
    assert gitio.is_tracked(repo, "*.py") is False


def test_ignored_returns_the_paths_git_ignores_and_nothing_when_it_cannot_say(repo_factory, tmp_path):
    repo = repo_factory({".gitignore": "*.log\nbuild/\n", "a.py": "x = 1\n"})
    assert gitio.ignored(repo, ["a.py", "run.log", "build/out.txt", "docs/notes.md"]) == {"run.log", "build/out.txt"}
    assert gitio.ignored(repo, ["a.py"]) == set()
    assert gitio.ignored(repo, []) == set()
    assert gitio.ignored(tmp_path / "nowhere", ["a.log"]) == set()
