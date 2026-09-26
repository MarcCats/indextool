"""Turn source bytes into text without ever consulting the locale."""
from __future__ import annotations

import io
import tokenize


def decode_source(data: bytes) -> tuple[str, bool]:
    """(text, encoding_ok). Newlines are normalized to LF. A file whose encoding cannot be determined (a bad
    coding cookie, a BOM that contradicts the cookie, invalid UTF-8 in the first two lines) is decoded as UTF-8 with
    replacement characters and reported as not ok, so the caller can count it as unparsable."""
    ok = True
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    except SyntaxError:
        encoding, ok = "utf-8", False
    text = data.decode(encoding, errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, ok
