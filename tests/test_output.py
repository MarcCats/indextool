import pytest

from indextool import output


def test_expected_text_ends_with_exactly_one_newline():
    assert output.expected_text("a\nb") == "a\nb\n"
    assert output.expected_text("a\nb\n\n\n") == "a\nb\n"


def test_normalize_newlines():
    assert output.normalize_newlines("a\r\nb\rc\n") == "a\nb\nc\n"


def test_write_atomic_creates_parents_writes_utf8_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "docs" / "deep" / "map.md"
    output.write_atomic(target, "café\n")
    assert target.read_bytes() == "café\n".encode("utf-8")
    assert [p.name for p in target.parent.iterdir()] == ["map.md"]


def test_compare_states():
    assert output.compare(None, "x\n") == "missing"
    assert output.compare("x\n", "x\n") == "current"
    assert output.compare("x\n", "y\n") == "stale"


def test_changed_lines_are_only_the_added_and_removed_lines():
    lines = output.changed_lines("a\nold\nc\n", "a\nnew\nc\n")
    assert lines == ["-old", "+new"]
    assert output.changed_lines("same\n", "same\n") == []


def test_a_removed_rule_line_is_not_mistaken_for_a_diff_header():
    assert output.changed_lines("--- rule\nx\n", "x\n") == ["---- rule"]


def test_read_committed_normalizes_crlf_and_reports_missing(tmp_path):
    (tmp_path / "map.md").write_bytes(b"a\r\nb\r\n")
    assert output.read_committed(tmp_path, "map.md", "worktree") == "a\nb\n"
    assert output.read_committed(tmp_path, "nope.md", "worktree") is None


def test_a_failed_write_leaves_no_temp_file(tmp_path):
    target = tmp_path / "map"
    target.mkdir()
    with pytest.raises(OSError):
        output.write_atomic(target, "x\n")
    assert [p.name for p in tmp_path.iterdir()] == ["map"]
