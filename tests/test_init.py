import json
import os
import re
import sys
import tomllib

import pytest

from indextool import FORMAT_VERSION
from indextool import init as init_module
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
    assert (repo / "indextool.toml").read_bytes().decode("utf-8") == (
        "# indextool configuration. Every key is optional; see the indextool documentation for the full list.\n"
        'title = "repo"\n'
        'roots = ["src"]\n'
        'architecture = "docs/architecture.md"\n'
        'index = "docs/architecture.index.txt"\n'
    )
    agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- indextool:begin" in agents and "`docs/architecture.md`" in agents
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hook = settings["hooks"]["SessionStart"][0]["hooks"][0]
    assert hook == {"type": "command", "command": "indextool refresh", "timeout": 30}
    workflow = (repo / ".github" / "workflows" / "indextool.yml").read_text(encoding="utf-8")
    assert f'python-version: "{PY}"' in workflow and f'pip install "indextool~={FORMAT_VERSION}.0"' in workflow
    assert "run: indextool verify" in workflow and "working-directory" not in workflow
    assert "\npermissions:\n  contents: read\njobs:\n" in workflow  # the token can read the repository, nothing more
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


OUR_GROUP = {"hooks": [{"type": "command", "command": "indextool refresh", "timeout": 30}]}


@pytest.mark.parametrize(
    "session", [[{"hooks": None}], [{"hooks": 5}], [5], [None], [{"hooks": {"a": 1}}], [[{"hooks": []}]]]
)
def test_merge_hook_keeps_an_entry_of_an_unexpected_shape_and_appends_its_own_group(session):
    text, outcome = merge_hook(json.dumps({"hooks": {"SessionStart": session}}))
    assert outcome == "changed"
    assert json.loads(text)["hooks"]["SessionStart"] == [*session, OUR_GROUP]
    assert merge_hook(text) == (None, "unchanged")


@pytest.mark.parametrize(
    "settings",
    ['{"hooks": null}', '{"hooks": []}', '{"hooks": {"SessionStart": {}}}', '{"hooks": {"SessionStart": "x"}}', "[1]", "null"],
)
def test_merge_hook_leaves_settings_with_the_wrong_overall_shape_alone(settings):
    assert merge_hook(settings) == (None, "skipped")


def test_settings_with_a_null_hooks_entry_are_merged_not_a_crash(repo_factory):
    existing = {"permissions": {"allow": ["Bash(git log *)"]}, "hooks": {"SessionStart": [{"hooks": None}]}}
    repo = repo_factory({**SRC_LAYOUT, ".claude/settings.json": json.dumps(existing)})
    result = run_cli(repo, "init")
    assert result.code == 0, result.err
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"] == existing["permissions"]
    assert settings["hooks"]["SessionStart"] == [{"hooks": None}, OUR_GROUP]
    before = snapshot(repo)
    assert run_cli(repo, "init").code == 0
    assert snapshot(repo) == before


def test_a_symlinked_pointer_file_stays_a_link_and_both_names_show_one_block(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "AGENTS.md": "# Agent notes\n"})
    try:
        os.symlink("AGENTS.md", repo / "CLAUDE.md")
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create symlinks")
    result = run_cli(repo, "init")
    assert result.code == 0, result.err
    assert (repo / "CLAUDE.md").is_symlink() and not (repo / "AGENTS.md").is_symlink()
    for name in ("CLAUDE.md", "AGENTS.md"):
        text = (repo / name).read_text(encoding="utf-8")
        assert text.startswith("# Agent notes\n") and text.count("<!-- indextool:begin") == 1
    assert not list(repo.glob("*.tmp"))
    line = next(ln for ln in result.out.replace("\r\n", "\n").split("\n") if ln.startswith("git add "))
    git(repo, "add", *line.split()[2:])
    assert "AGENTS.md" in git(repo, "diff", "--cached", "--name-only")


def test_a_symlinked_settings_file_stays_a_link_and_its_target_gets_the_hook(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "dotfiles/claude.json": '{"permissions": {}}\n'})
    (repo / ".claude").mkdir()
    try:
        os.symlink(os.path.join("..", "dotfiles", "claude.json"), repo / ".claude" / "settings.json")
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create symlinks")
    assert run_cli(repo, "init").code == 0
    assert (repo / ".claude" / "settings.json").is_symlink()
    target = json.loads((repo / "dotfiles" / "claude.json").read_text(encoding="utf-8"))
    assert target["hooks"]["SessionStart"] == [OUR_GROUP]
    assert not list((repo / "dotfiles").glob("*.tmp"))


def test_two_names_for_one_file_are_planned_and_written_once(repo_factory, monkeypatch):
    repo = repo_factory({**SRC_LAYOUT, "CLAUDE.md": "# Notes\n", "AGENTS.md": "# Notes\n"})
    shared = (repo / "AGENTS.md").resolve()
    monkeypatch.setattr(
        init_module, "_real", lambda path: shared if path.name in ("CLAUDE.md", "AGENTS.md") else path.resolve()
    )
    written = []
    real_write = init_module.write_atomic
    monkeypatch.setattr(init_module, "write_atomic", lambda path, text: (written.append(path), real_write(path, text))[1])
    result = init_module.run(repo)
    assert written.count(shared) == 1
    agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Notes\n") and agents.count("<!-- indextool:begin") == 1
    assert (repo / "CLAUDE.md").read_bytes() == b"# Notes\n"  # the second name is only another way to reach AGENTS.md
    by_name = {item.rel: item for item in result.items}
    assert by_name["CLAUDE.md"].action == "updated"
    assert (by_name["AGENTS.md"].action, by_name["AGENTS.md"].note) == ("unchanged", "same file as CLAUDE.md")


def printed_lines(result):
    return result.out.replace("\r\n", "\n").split("\n")


def git_add_tokens(result):
    line = next(ln for ln in printed_lines(result) if ln.startswith("git add "))
    return line.split()[2:]


def test_every_printed_path_is_relative_to_the_shell_directory(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "svc/keep.txt": "x\n"})
    svc = repo / "svc"
    result = run_cli(svc, "init")  # no configuration anywhere, so the project is the whole repository
    assert result.code == 0, result.err
    assert (repo / "indextool.toml").is_file() and not (svc / "indextool.toml").exists()
    lines = printed_lines(result)
    assert lines[0] == "initialised .."
    item_paths = [ln.split()[1] for ln in lines if ln.startswith("  ") and ln.split()[0] in ("created", "updated")]
    assert "../indextool.toml" in item_paths and "../AGENTS.md" in item_paths
    tokens = git_add_tokens(result)
    assert set(tokens) == set(item_paths)
    assert all((svc / token).exists() for token in tokens)
    git(svc, "add", *tokens)  # pasting the printed line works
    assert "indextool.toml" in git(svc, "diff", "--cached", "--name-only")


def test_the_initialised_line_says_dot_when_the_project_is_the_shell_directory(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    assert printed_lines(run_cli(repo, "init", "--dry-run"))[0] == "initialised ."


@pytest.mark.parametrize(
    "extra,args,ignored",
    [
        ({}, ("--hook", "local"), ".claude/settings.local.json"),
        ({".gitignore": "docs/\n"}, (), "docs/architecture.md"),
    ],
)
def test_the_git_add_line_never_lists_an_ignored_path(repo_factory, extra, args, ignored):
    repo = repo_factory({**SRC_LAYOUT, **extra})
    result = run_cli(repo, "init", *args)
    assert result.code == 0, result.err
    tokens = git_add_tokens(result)
    assert tokens and ignored not in tokens
    assert any(ignored in ln for ln in printed_lines(result) if ln.startswith("  "))  # still reported as written
    git(repo, "add", *tokens)  # git refuses the whole command when it is given an ignored path


def test_the_written_title_is_the_project_name_of_the_pyproject_when_there_is_one(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "pyproject.toml": '[project]\nname = "ledger-service"\nversion = "1"\n'}, name="checkout")
    assert run_cli(repo, "init").code == 0
    written = (repo / "indextool.toml").read_text(encoding="utf-8").split("\n")
    assert 'title = "ledger-service"' in written and not any("checkout" in ln for ln in written)
    assert "# Architecture map: ledger-service" in (repo / "docs" / "architecture.md").read_text(encoding="utf-8")


def test_the_written_title_is_the_folder_name_of_the_base_directory_without_a_pyproject_name(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "pyproject.toml": "[tool.other]\nx = 1\n"}, name="orders-api")
    result = run_cli(repo, "init")
    assert result.code == 0, result.err
    assert 'title = "orders-api"' in (repo / "indextool.toml").read_text(encoding="utf-8").split("\n")
    assert "orders-api" not in result.out.replace("\r\n", "\n").split("\n")[0]  # the folder name is not printed by itself
    assert "# Architecture map: orders-api" in (repo / "docs" / "architecture.md").read_text(encoding="utf-8")


def test_the_written_title_is_a_toml_string_whatever_the_name_holds():
    for name in ('say "hi"', "back\\slash", "café", "tab\there"):
        assert tomllib.loads(render_config(["."], name))["title"] == name
    assert "title" not in tomllib.loads(render_config(["."], ""))


def test_init_prints_the_two_commands_for_other_ci_systems(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    for args in ((), ("--dry-run",)):
        lines = printed_lines(run_cli(repo, "init", *args))
        at = lines.index("For other CI systems, run these two commands:")
        assert lines[at + 1 : at + 3] == [f'  pip install "indextool~={FORMAT_VERSION}.0"', "  indextool verify"]


def test_an_output_git_ignores_is_named_in_a_note_because_ci_cannot_verify_it(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, ".gitignore": "docs/\n"})
    lines = printed_lines(run_cli(repo, "init"))
    assert "note: docs/architecture.md is ignored by git; CI cannot verify it" in lines
    assert "note: docs/architecture.index.txt is ignored by git; CI cannot verify it" in lines
    plain = printed_lines(run_cli(repo_factory(SRC_LAYOUT, name="plain"), "init"))
    assert not any("ignored by git" in ln for ln in plain)


def test_the_note_about_ignored_files_is_for_the_outputs_only(repo_factory):
    repo = repo_factory(SRC_LAYOUT)
    lines = printed_lines(run_cli(repo, "init", "--hook", "local"))  # settings.local.json is ignored on purpose
    assert not any("ignored by git" in ln for ln in lines)


def two_sub_projects(repo_factory):
    return repo_factory(
        {
            "a/indextool.toml": 'roots = ["."]\n',
            "a/m.py": "x = 1\n",
            "b/indextool.toml": 'roots = ["."]\n',
            "b/m.py": "y = 2\n",
        }
    )


def test_a_second_sub_project_is_told_that_the_shared_workflow_does_not_check_it(repo_factory):
    repo = two_sub_projects(repo_factory)
    workflow = repo / ".github" / "workflows" / "indextool.yml"
    first = run_cli(repo / "a", "init")
    assert first.code == 0, first.err
    assert "working-directory: a" in workflow.read_text(encoding="utf-8")
    assert "does not check" not in first.out  # it created the workflow, so it is covered
    before = workflow.read_bytes()
    second = run_cli(repo / "b", "init")
    assert second.code == 0, second.err
    assert workflow.read_bytes() == before  # never overwritten
    lines = printed_lines(second)
    assert any("exists; not overwritten" in ln for ln in lines)
    at = lines.index("CI does not check this sub-project yet:")
    assert "../.github/workflows/indextool.yml" in lines[at + 1] and "does not run indextool verify in b" in lines[at + 1]
    assert lines[at + 3 : at + 5] == ["      - run: indextool verify", "        working-directory: b"]
    again = printed_lines(run_cli(repo / "a", "init"))
    assert not any("does not check" in ln or "working-directory" in ln for ln in again)


def test_no_snippet_is_printed_once_the_shared_workflow_names_the_sub_project(repo_factory):
    repo = two_sub_projects(repo_factory)
    assert run_cli(repo / "a", "init").code == 0
    workflow = repo / ".github" / "workflows" / "indextool.yml"
    workflow.write_bytes(workflow.read_bytes() + b"      - run: indextool verify\n        working-directory: b   \n")
    assert "does not check" not in run_cli(repo / "b", "init").out


def test_a_project_at_the_top_of_the_repository_is_not_told_about_its_workflow(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, ".github/workflows/indextool.yml": "name: mine\n"})
    result = run_cli(repo, "init")
    assert "exists; not overwritten" in result.out and "does not check" not in result.out


def test_init_takes_the_config_option_the_other_commands_take(repo_factory):
    conf = 'roots = ["."]\narchitecture = "maps/arch.md"\nindex = "maps/idx.txt"\n'
    repo = repo_factory({"conf/indextool.toml": conf, "conf/pkg/a.py": '"""A."""\n'})
    result = run_cli(repo, "init", "--config", "conf/indextool.toml")
    assert result.code == 0, result.err
    assert not (repo / "indextool.toml").exists()  # no second config, and the one that exists is untouched
    assert (repo / "conf" / "indextool.toml").read_bytes() == conf.encode("utf-8")
    pointer = (repo / "conf" / "AGENTS.md").read_text(encoding="utf-8")
    assert "`maps/arch.md`" in pointer and "`maps/idx.txt`" in pointer and "docs/architecture" not in pointer
    assert (repo / "conf" / "maps" / "arch.md").is_file() and not (repo / "conf" / "docs").exists()
    assert "working-directory: conf" in (repo / ".github" / "workflows" / "indextool.yml").read_text(encoding="utf-8")
    commit_all(repo, "adopt indextool")
    verified = run_cli(repo, "verify", "--config", "conf/indextool.toml")
    assert verified.code == 0, verified.out + verified.err
    assert "no managed pointer block" not in verified.err
    assert run_cli(repo, "verify", "--config", "conf/indextool.toml", "--source", "index").code == 0


def test_init_dry_run_accepts_config_and_reports_a_missing_config_file_as_exit_2(repo_factory):
    repo = repo_factory({**SRC_LAYOUT, "indextool.toml": 'title = "Mine"\nroots = ["src"]\n'})
    dry = run_cli(repo, "init", "--config", "indextool.toml", "--dry-run")
    assert dry.code == 0 and "dry run" in dry.out, dry.err
    assert git(repo, "status", "--porcelain").strip() == ""
    missing = run_cli(repo, "init", "--config", "nope.toml")
    assert missing.code == 2 and "config file not found" in missing.err and "Traceback" not in missing.err
