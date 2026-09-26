from pathlib import Path

import pytest

from tests.fixture_repos import PORTABLE
from tests.helpers import run_cli

GOLDEN = Path(__file__).resolve().parent / "golden"


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


@pytest.mark.parametrize(
    "golden,rel",
    [("portable.architecture.md", "docs/architecture.md"), ("portable.index.txt", "docs/architecture.index.txt")],
)
def test_portable_fixture_matches_the_golden_output(repo_factory, golden, rel):
    repo = repo_factory(PORTABLE)  # the folder is named "repo"; the golden was made in one named "portable"
    assert run_cli(repo, "generate").code == 0
    assert _lf((repo / rel).read_bytes()) == _lf((GOLDEN / golden).read_bytes())
