import pytest

from tests.helpers import make_repo


@pytest.fixture
def repo_factory(tmp_path):
    def factory(files, name="repo", commit=True):
        return make_repo(tmp_path, files, name=name, commit=commit)

    return factory
