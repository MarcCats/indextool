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


@pytest.mark.parametrize("bad", ["[z-a]*.py", "[a&&b]", "[[]x", "[a--b]"])
def test_invalid_character_classes_are_config_errors(bad):
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
