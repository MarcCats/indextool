import ast
import re
import sys
import tomllib
from pathlib import Path

from indextool.init import workflow_text

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "indextool"
WORKFLOWS = ROOT / ".github" / "workflows"
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_package_imports_only_the_standard_library():
    stdlib = set(sys.stdlib_module_names)
    for path in sorted(SRC.rglob("*.py")):
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
    for path in sorted(SRC.rglob("*.py")):
        assert ".splitlines(" not in path.read_text(encoding="utf-8"), path.name


def test_the_entry_point_is_the_cli_main():
    assert PYPROJECT["project"]["scripts"] == {"indextool": "indextool.cli:main"}


def test_the_pre_commit_hook_verifies_the_index():
    text = (ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    assert "entry: indextool verify --source index" in text and "id: indextool-verify" in text


def workflow(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def jobs_of(text):
    """{job name: the lines of its body}. The workflows here are plain two-space YAML and the standard library has no
    YAML parser, so this reads only what they use: `jobs:` at the top and one key per job below it."""
    lines = text.split("\n")
    found, name = {}, None
    for line in lines[lines.index("jobs:") + 1 :]:
        header = re.fullmatch(r"  ([\w-]+):", line)
        if header:
            name = header.group(1)
            found[name] = []
        elif name and (line.startswith("    ") or not line.strip()):
            found[name].append(line)
        elif line.strip():
            break
    return found


def block_under(body, key):
    """The lines indented under a job-level `key:` (four spaces), stripped."""
    at = body.index(f"    {key}:")
    out = []
    for line in body[at + 1 :]:
        if not line.startswith("      "):
            break
        out.append(line.strip())
    return out


def all_workflows():
    files = {path.name: path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS.glob("*.yml"))}
    files["(the workflow init writes)"] = workflow_text("")
    return files


def test_the_ci_workflow_and_the_workflow_init_writes_grant_only_read_access_at_the_top_level():
    for name, text in (("ci.yml", workflow("ci.yml")), ("the workflow init writes", workflow_text(""))):
        assert "\npermissions:\n  contents: read\njobs:\n" in text, name


def test_no_job_that_can_mint_an_id_token_installs_dev_dependencies_or_runs_project_code():
    checked = 0
    for name, text in all_workflows().items():
        for job, body in jobs_of(text).items():
            joined = "\n".join(body)
            if "id-token: write" not in joined:
                continue
            checked += 1
            assert "run:" not in joined, (name, job)  # not one shell step: publishing needs actions only
            assert "pytest" not in joined and "[dev]" not in joined and "pip install" not in joined, (name, job)
    assert checked >= 1  # the release workflow has a publishing job, so the check is looking at something


def test_the_release_workflow_builds_and_tests_in_one_job_and_publishes_from_another():
    text = workflow("release.yml")
    head = text.split("\nname:")[0]
    assert "CI matrix is green" in head and head.startswith("#")  # the comment sits above the first key
    assert 'tags: ["v*"]' in text  # still triggered by a version tag
    jobs = jobs_of(text)
    assert sorted(jobs) == ["build", "publish"]
    build, publish = jobs["build"], jobs["publish"]
    assert block_under(build, "permissions") == ["contents: read"]
    build_text = "\n".join(build)
    assert "id-token" not in build_text and "environment:" not in build_text
    assert "python -m pytest" in build_text and "python -m build" in build_text and "actions/upload-artifact" in build_text
    assert "    needs: build" in publish
    assert block_under(publish, "permissions") == ["id-token: write"]  # and nothing else
    assert "    environment: pypi" in publish
    publish_text = "\n".join(publish)
    assert "actions/download-artifact" in publish_text and "pypa/gh-action-pypi-publish@release/v1" in publish_text
    assert "actions/checkout" not in publish_text and "setup-python" not in publish_text
