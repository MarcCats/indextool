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


def test_an_output_directory_that_cannot_be_created_is_a_one_line_error(repo_factory):
    repo = repo_factory(TINY)
    (repo / "docs").write_bytes(b"not a directory\n")
    result = run_cli(repo, "generate")
    assert result.code == 2 and "Traceback" not in result.err
    assert result.err.startswith("indextool: cannot write docs/architecture.md") and result.err.count("\n") == 1


def test_an_output_path_that_is_a_directory_is_a_one_line_error_and_leaves_no_temp_file(repo_factory):
    repo = repo_factory({**TINY, "indextool.toml": 'architecture = "map"\n'})
    (repo / "map").mkdir()
    result = run_cli(repo, "generate")
    assert result.code == 2 and "Traceback" not in result.err
    assert result.err.startswith("indextool: cannot write map") and result.err.count("\n") == 1
    assert [p.name for p in repo.iterdir() if p.name.endswith(".tmp")] == []
