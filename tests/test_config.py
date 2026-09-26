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


@pytest.mark.parametrize(
    "text",
    [
        "[sql]\nwrite_any = ['a{1,99999999999999999999}']\n",  # the regex engine raises OverflowError
        "[sql]\ncreate = ['(x){99999999999}']\n",
        "[sql]\nuse = ['FROM (@TABLES@){99999999999}']\n",
        "[sql]\nwrite_any = ['" + "(" * 2000 + "a" + ")" * 2000 + "']\n",  # the regex engine raises RecursionError
    ],
    ids=["repeat-overflow", "group-repeat-overflow", "template-repeat-overflow", "deep-nesting"],
)
def test_a_regex_the_engine_cannot_compile_is_a_config_error_not_a_raw_exception(tmp_path, text):
    with pytest.raises(ConfigError, match="invalid regex"):
        make_config(tmp_path, text)


@pytest.mark.filterwarnings("error")
@pytest.mark.parametrize(
    "text",
    [
        "[sql]\nwrite_any = ['[[a]']\n",
        "[sql]\ncreate = ['CREATE TABLE ([[a]+)']\n",
        "[sql]\nuse = ['FROM ([[a]|@TABLES@)']\n",
    ],
    ids=["write_any", "create", "use"],
)
def test_a_regex_the_engine_warns_about_is_a_config_error_whatever_the_warning_filters(tmp_path, text):
    with pytest.raises(ConfigError, match="invalid regex"):
        make_config(tmp_path, text)


@pytest.mark.parametrize("text", ["sql = false\n", "io = []\n", "routes = 0\n", "sql = ''\n"])
def test_a_falsy_value_where_a_table_belongs_is_an_error(tmp_path, text):
    with pytest.raises(ConfigError, match="expected a table"):
        make_config(tmp_path, text)
