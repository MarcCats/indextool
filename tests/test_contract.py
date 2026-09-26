import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "indextool"
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_package_imports_only_the_standard_library():
    stdlib = set(sys.stdlib_module_names)
    for path in sorted(SRC.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] in stdlib, (path.name, alias.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert node.module.split(".")[0] in stdlib, (path.name, node.module)


def test_no_runtime_dependencies_are_declared_and_the_floor_is_python_3_11():
    assert PYPROJECT["project"]["dependencies"] == []
    assert PYPROJECT["project"]["requires-python"] == ">=3.11"


def test_splitlines_is_not_used_in_the_package():
    for path in sorted(SRC.glob("*.py")):
        assert ".splitlines(" not in path.read_text(encoding="utf-8"), path.name


def test_the_entry_point_is_the_cli_main():
    assert PYPROJECT["project"]["scripts"] == {"indextool": "indextool.cli:main"}


def test_the_pre_commit_hook_verifies_the_index():
    text = (ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    assert "entry: indextool verify --source index" in text and "id: indextool-verify" in text
