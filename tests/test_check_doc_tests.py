import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    path = ROOT / "scripts" / "check_doc_tests.py"
    spec = importlib.util.spec_from_file_location("check_doc_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dangling_citations_are_reported(tmp_path):
    m = load()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_present():\n    pass\n", encoding="utf-8")
    text = "`tests/test_a.py::test_present` and `tests/test_a.py::test_gone` and `tests/test_b.py::test_x`"
    assert m.missing_citations(text, tmp_path) == ["`tests/test_a.py::test_gone`", "`tests/test_b.py::test_x`"]


def test_every_citation_in_the_real_rules_document_exists():
    m = load()
    text = (ROOT / "docs" / "rules.md").read_text(encoding="utf-8")
    assert m.missing_citations(text, ROOT) == []
    assert text.count("`tests/") >= 20  # the rules document really does cite its pinning tests
