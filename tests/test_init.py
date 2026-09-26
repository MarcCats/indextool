import json
import re
import sys

import pytest

from indextool import FORMAT_VERSION
from indextool.init import merge_hook, render_config, workflow_text
from indextool.pointer import BEGIN, render_block
from tests.helpers import commit_all, git, make_config, run_cli, write_files

PY = f"{sys.version_info.major}.{sys.version_info.minor}"


def snapshot(repo):
    return {
        p.relative_to(repo).as_posix(): p.read_bytes()
        for p in sorted(repo.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(repo).parts
    }


SRC_LAYOUT = {
    "src/shop/__init__.py": '"""Shop package."""\n',
    "src/shop/ledger.py": '"""Ledger."""\n',
}


def test_init_creates_everything_in_a_fresh_project(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    result = run_cli(repo, "init")
    assert result.code == 0, result.err
    assert 'roots = ["src"]' in (repo / "indextool.toml").read_text(encoding="utf-8")
    agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- indextool:begin" in agents and "`docs/architecture.md`" in agents
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hook = settings["hooks"]["SessionStart"][0]["hooks"][0]
    assert hook == {"type": "command", "command": "indextool refresh", "timeout": 30}
    workflow = (repo / ".github" / "workflows" / "indextool.yml").read_text(encoding="utf-8")
    assert f'python-version: "{PY}"' in workflow and f'pip install "indextool~={FORMAT_VERSION}.0"' in workflow
    assert "run: indextool verify" in workflow and "working-directory" not in workflow
    attributes = (repo / ".gitattributes").read_text(encoding="utf-8")
    assert "docs/architecture.md text eol=lf" in attributes and "docs/architecture.index.txt text eol=lf" in attributes
    assert (repo / "docs" / "architecture.md").is_file() and (repo / "docs" / "architecture.index.txt").is_file()
    assert "git add " in result.out and "indextool-verify" in result.out


def test_init_is_idempotent(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    run_cli(repo, "init")
    before = snapshot(repo)
    result = run_cli(repo, "init")
    assert result.code == 0, result.err
    assert snapshot(repo) == before
    action_lines = [ln for ln in result.out.split("\n") if ln.startswith("  ")]
    assert action_lines and not any(ln.split()[0] in ("created", "updated") for ln in action_lines)


def test_dry_run_writes_nothing(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    result = run_cli(repo, "init", "--dry-run")
    assert result.code == 0 and "dry run" in result.out
    assert git(repo, "status", "--porcelain").strip() == ""
    assert not (repo / "indextool.toml").exists()


def test_existing_config_is_never_overwritten(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "indextool.toml": 'title = "Mine"\nroots = ["src"]\n'})
    result = run_cli(repo, "init")
    assert result.code == 0, result.err
    assert (repo / "indextool.toml").read_text(encoding="utf-8") == 'title = "Mine"\nroots = ["src"]\n'
    assert "skipped" in result.out and "configuration already present" in result.out


def test_a_pyproject_table_counts_as_an_existing_config(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "pyproject.toml": '[tool.indextool]\nroots = ["src"]\n'})
    assert run_cli(repo, "init").code == 0
    assert not (repo / "indextool.toml").exists()


def test_hook_merge_keeps_foreign_keys_and_never_duplicates(repo_factory):
    existing = {
        "permissions": {"allow": ["Bash(git log *)"]},
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]},
    }
    repo = repo_factory({**SRC_LAYOUT, ".claude/settings.json": json.dumps(existing)})
    run_cli(repo, "init")
    run_cli(repo, "init")
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"] == existing["permissions"]
    commands = [h["command"] for g in settings["hooks"]["SessionStart"] for h in g["hooks"]]
    assert commands == ["echo hi", "indextool refresh"]


def test_local_hook_goes_to_settings_local_and_is_gitignored(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    assert run_cli(repo, "init", "--hook", "local").code == 0
    assert (repo / ".claude" / "settings.local.json").is_file()
    assert not (repo / ".claude" / "settings.json").exists()
    assert ".claude/settings.local.json" in (repo / ".gitignore").read_text(encoding="utf-8").split("\n")


def test_hook_none_writes_no_settings(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    assert run_cli(repo, "init", "--hook", "none").code == 0
    assert not (repo / ".claude").exists()


def test_settings_that_are_not_json_are_left_alone(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, ".claude/settings.json": "{not json"})
    result = run_cli(repo, "init")
    assert result.code == 0
    assert (repo / ".claude" / "settings.json").read_text(encoding="utf-8") == "{not json"
    assert "skipped" in result.out and "not valid JSON" in result.out


def test_pointer_goes_into_every_existing_instruction_file_and_keeps_their_text(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "CLAUDE.md": "# Claude notes\n", "AGENTS.md": "# Agent notes\n"})
    run_cli(repo, "init")
    for name, head in (("CLAUDE.md", "# Claude notes\n"), ("AGENTS.md", "# Agent notes\n")):
        text = (repo / name).read_text(encoding="utf-8")
        assert text.startswith(head) and text.count("<!-- indextool:begin") == 1


def test_pointer_goes_only_into_agents_md_when_claude_md_imports_it(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "CLAUDE.md": "@AGENTS.md\n", "AGENTS.md": "# Agent notes\n"})
    run_cli(repo, "init")
    assert "indextool:begin" not in (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert "indextool:begin" in (repo / "AGENTS.md").read_text(encoding="utf-8")


def test_the_workflow_is_not_overwritten(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, ".github/workflows/indextool.yml": "name: mine\n"})
    result = run_cli(repo, "init")
    assert (repo / ".github" / "workflows" / "indextool.yml").read_text(encoding="utf-8") == "name: mine\n"
    assert "exists; not overwritten" in result.out


def test_a_sub_project_workflow_runs_verify_in_its_directory(repo_factory):
    repo = repo_factory({"svc/indextool.toml": 'roots = ["."]\n', "svc/a.py": "x = 1\n"})
    result = run_cli(repo / "svc", "init")
    assert result.code == 0, result.err
    workflow = (repo / ".github" / "workflows" / "indextool.yml").read_text(encoding="utf-8")
    assert "run: indextool verify\n        working-directory: svc" in workflow


def test_after_init_and_a_commit_verify_passes_in_both_modes(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    assert run_cli(repo, "init").code == 0
    commit_all(repo, "adopt indextool")
    verified = run_cli(repo, "verify")
    assert verified.code == 0, verified.out + verified.err
    assert "no managed pointer block" not in verified.err
    assert run_cli(repo, "verify", "--source", "index").code == 0


def test_init_reports_config_errors_and_writes_nothing(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "indextool.toml": "titel = 'x'\n"})
    result = run_cli(repo, "init")
    assert result.code == 2 and "unknown key 'titel'" in result.err
    assert not (repo / "AGENTS.md").exists()


def test_helpers_render_config_merge_hook_and_workflow():
    assert render_config(["."]).count('roots = ["."]') == 1
    text, outcome = merge_hook(None)
    assert outcome == "changed" and json.loads(text)["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] == 30
    assert merge_hook(text) == (None, "unchanged")
    assert merge_hook("[1, 2]") == (None, "skipped")
    assert "working-directory: svc" in workflow_text("svc") and "working-directory" not in workflow_text("")


LONE_LF = re.compile(rb"(?<!\r)\n")


@pytest.mark.parametrize(
    "files,culprit",
    [
        ({"AGENTS.md": f"# Notes\n\n{BEGIN}\nUSER CONTENT\n"}, "AGENTS.md: unpaired indextool marker at line 3"),
        (
            {"CLAUDE.md": "# Claude notes\n", "AGENTS.md": f"# Notes\n\n{BEGIN}\nUSER CONTENT\n"},
            "AGENTS.md: unpaired indextool marker at line 3",
        ),
        ({"AGENTS.md": "# Notes\n\n```python\nprint(1)\n"}, "AGENTS.md: unclosed code fence at line 3"),
        (
            {"CLAUDE.md": f"@AGENTS.md\n\n{BEGIN}\nUSER CONTENT\n", "AGENTS.md": "# Agent notes\n"},
            "CLAUDE.md: unpaired indextool marker at line 3",
        ),
    ],
)
def test_a_pointer_file_that_cannot_be_edited_safely_fails_the_run_before_anything_is_written(
    repo_factory, files, culprit
):
    repo = repo_factory({**SRC_LAYOUT, **files})
    before = snapshot(repo)
    result = run_cli(repo, "init")
    assert result.code == 2, result.out + result.err
    assert result.err.strip().count("\n") == 0 and culprit in result.err and "Traceback" not in result.err
    assert snapshot(repo) == before  # no indextool.toml, no workflow, no settings, no generated files, no edited file
    assert git(repo, "status", "--porcelain").strip() == ""


def test_a_write_that_fails_is_a_one_line_error_not_a_traceback(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, ".github": "a file where the workflows directory should go\n"})
    result = run_cli(repo, "init")
    assert result.code == 2
    assert result.err.startswith("indextool: cannot write .github/workflows/indextool.yml: ")
    assert result.err.strip().count("\n") == 0 and "Traceback" not in result.err


def test_a_settings_path_that_cannot_be_read_is_a_one_line_error_and_writes_nothing(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, ".claude/settings.json/keep": "a directory where the settings file should be\n"})
    before = snapshot(repo)
    result = run_cli(repo, "init")
    assert result.code == 2
    assert result.err.startswith("indextool: cannot read .claude/settings.json: ")
    assert result.err.strip().count("\n") == 0 and "Traceback" not in result.err
    assert snapshot(repo) == before


def test_files_that_use_crlf_keep_it_and_an_up_to_date_file_is_not_rewritten(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    write_files(
        repo,
        {
            "AGENTS.md": b"# Agent notes\r\nsecond line\r\n",
            "CLAUDE.md": b"# Claude notes\nsecond line\n",
            ".gitattributes": b"*.png binary\r\n",
            ".claude/settings.json": b'{\r\n  "permissions": {"allow": []}\r\n}\r\n',
        },
    )
    assert run_cli(repo, "init").code == 0
    for rel, head in (
        ("AGENTS.md", b"# Agent notes\r\nsecond line\r\n"),
        (".gitattributes", b"*.png binary\r\n"),
        (".claude/settings.json", b"{\r\n"),
    ):
        data = (repo / rel).read_bytes()
        assert data.startswith(head) and b"\r\n" in data and not LONE_LF.search(data), rel
    agents = (repo / "AGENTS.md").read_bytes()
    assert BEGIN.encode() in agents and b"indextool:end" in agents
    assert b"docs/architecture.md text eol=lf\r\n" in (repo / ".gitattributes").read_bytes()
    assert b"indextool refresh" in (repo / ".claude" / "settings.json").read_bytes()
    claude = (repo / "CLAUDE.md").read_bytes()
    assert BEGIN.encode() in claude and b"\r" not in claude  # an LF file stays LF
    before = snapshot(repo)
    result = run_cli(repo, "init")
    assert result.code == 0, result.err
    assert snapshot(repo) == before
    assert not any(ln.split()[0] in ("created", "updated") for ln in result.out.split("\n") if ln.startswith("  "))


def test_a_local_hook_and_gitignore_that_use_crlf_keep_it(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    write_files(repo, {".gitignore": b"*.log\r\n", ".claude/settings.local.json": b'{\r\n  "env": {}\r\n}\r\n'})
    assert run_cli(repo, "init", "--hook", "local").code == 0
    ignore = (repo / ".gitignore").read_bytes()
    assert ignore == b"*.log\r\n.claude/settings.local.json\r\n"
    settings = (repo / ".claude" / "settings.local.json").read_bytes()
    assert b"indextool refresh" in settings and not LONE_LF.search(settings)
    before = snapshot(repo)
    assert run_cli(repo, "init", "--hook", "local").code == 0
    assert snapshot(repo) == before


def test_a_stale_block_in_a_file_that_is_not_a_target_is_refreshed_but_no_block_is_added_elsewhere(repo_factory):
    block = render_block(make_config(repo_factory({}, name="probe")))
    stale = block.replace("Read it whole", "Read it")
    repo = repo_factory(
        {
            **SRC_LAYOUT,
            "CLAUDE.md": f"@AGENTS.md\n\n{stale}\n\nafter\n",
            ".claude/CLAUDE.md": "@AGENTS.md\n\n```\nan open fence, no block\n",
            "AGENTS.md": "# Agent notes\n",
        }
    )
    unrelated = (repo / ".claude" / "CLAUDE.md").read_bytes()
    result = run_cli(repo, "init")
    assert result.code == 0, result.err
    assert (repo / "CLAUDE.md").read_text(encoding="utf-8") == f"@AGENTS.md\n\n{block}\n\nafter\n"
    assert (repo / "AGENTS.md").read_text(encoding="utf-8").count("<!-- indextool:begin") == 1
    assert (repo / ".claude" / "CLAUDE.md").read_bytes() == unrelated  # no block, so nothing is added
    assert "updated    CLAUDE.md" in result.out
    commit_all(repo, "adopt indextool")
    verified = run_cli(repo, "verify")
    assert verified.code == 0, verified.out + verified.err


@pytest.mark.parametrize(
    "rel,args",
    [
        ("CLAUDE.md", ()),
        (".claude/settings.json", ()),
        (".claude/settings.local.json", ("--hook", "local")),
        (".gitignore", ("--hook", "local")),
        (".gitattributes", ()),
    ],
)
def test_a_file_that_is_not_utf8_is_left_alone_with_a_note(repo_factory, rel, args):
    odd = "*.log\n".encode("utf-16")  # what a PowerShell redirect writes
    repo = repo_factory({**SRC_LAYOUT, rel: odd})
    result = run_cli(repo, "init", *args)
    assert result.code == 0, result.err
    assert (repo / rel).read_bytes() == odd
    assert f"skipped    {rel}  (not valid UTF-8; left alone)" in result.out
