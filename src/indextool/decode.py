"""Turn source bytes into text without ever consulting the locale."""
from __future__ import annotations

import io
import tokenize


def decode_source(data: bytes) -> tuple[str, bool]:
    """(text, encoding_ok). Newlines are normalized to LF. A file whose encoding cannot be determined (a bad
    coding cookie, a BOM that contradicts the cookie, invalid UTF-8 in the first two lines, a cookie naming a codec
    that is not a text encoding) is decoded as UTF-8 with replacement characters and reported as not ok, so the
    caller can count it as unparsable. Never raises."""
    ok = True
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        # detect_encoding only checks that the codec exists: rot13, hex, zlib, undefined and idna exist but cannot
        # decode text with errors="replace", so the decode itself can still fail.
        text = data.decode(encoding, errors="replace")
    except (SyntaxError, LookupError, UnicodeError):
        text, ok = data.decode("utf-8", errors="replace"), False
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, ok
