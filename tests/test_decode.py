from indextool.decode import decode_source


def test_bom_is_stripped_and_newlines_are_normalized():
    text, ok = decode_source(b"\xef\xbb\xbfx = 1\r\ny = 2\rz = 3\n")
    assert (text, ok) == ("x = 1\ny = 2\nz = 3\n", True)


def test_latin1_cookie_is_honoured():
    text, ok = decode_source(b"# -*- coding: latin-1 -*-\nx = '\xe9'\n")
    assert ok is True
    assert "é" in text


def test_unknown_cookie_and_bom_mismatch_are_not_ok_and_never_raise():
    text, ok = decode_source(b"# coding: nosuchcodec\nx = 1\n")
    assert (text, ok) == ("# coding: nosuchcodec\nx = 1\n", False)
    _, ok = decode_source(b"\xef\xbb\xbf# coding: latin-1\nx = 1\n")
    assert ok is False


def test_invalid_utf8_in_the_first_two_lines_is_not_ok():
    _, ok = decode_source(b"x = '\xe9'\n")
    assert ok is False


def test_invalid_utf8_after_the_first_two_lines_is_replaced_not_fatal():
    text, ok = decode_source(b"a = 1\nb = 2\nc = '\xe9'\n")
    assert ok is True
    assert "�" in text
