import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from tests import helpers
from tests.helpers import commit_all, git, make_repo, run_cli


def test_git_helpers_ignore_the_git_configuration_of_the_person_and_machine(tmp_path, monkeypatch):
    hostile = tmp_path / "hostile-gitconfig"
    hostile.write_bytes(
        b"[commit]\n\tgpgsign = true\n[tag]\n\tgpgSign = true\n[core]\n\tautocrlf = true\n\thooksPath = /no/such/hooks\n"
        b"[user]\n\tname = Someone Else\n"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(hostile))
    monkeypatch.delenv("GIT_CONFIG_NOSYSTEM", raising=False)
    repo = make_repo(tmp_path, {"a.py": "x = 1\n"})  # a commit needs no signature, whatever the person configured
    git(repo, "tag", "-a", "v1", "-m", "release")  # and neither does an annotated tag
    commit_all(repo, "second")
    assert git(repo, "config", "--get", "core.autocrlf").strip() == "false"
    listing = git(repo, "config", "--list", "--show-origin")
    assert "hostile-gitconfig" not in listing and "Someone Else" not in listing


def test_cli_subprocesses_get_the_same_isolated_environment(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen.update(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(helpers, "subprocess", SimpleNamespace(run=fake_run))
    monkeypatch.setenv("PYTHONUTF8", "1")
    assert run_cli(Path("."), "verify", env={"PYTHONHASHSEED": "3", "PYTHONUTF8": None}).code == 0
    assert seen["GIT_CONFIG_NOSYSTEM"] == "1" and Path(seen["GIT_CONFIG_GLOBAL"]).read_bytes() == b""
    assert seen["PYTHONHASHSEED"] == "3"  # a variable the test asks for is passed on
    assert "PYTHONUTF8" not in seen  # and None means the variable is not set at all


def test_the_isolated_environment_does_not_touch_the_process_environment(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "elsewhere")
    assert helpers.isolated_env()["GIT_CONFIG_GLOBAL"] != "elsewhere"
    assert os.environ["GIT_CONFIG_GLOBAL"] == "elsewhere"
