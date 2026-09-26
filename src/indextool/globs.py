"""A small gitignore-style matcher, because fnmatch has no `**` and PurePath.match is not recursive before 3.13."""
from __future__ import annotations

import re
import warnings
from collections.abc import Iterable
from dataclasses import dataclass

from .errors import ConfigError


@dataclass(frozen=True)
class _Rule:
    regex: re.Pattern[str]
    dir_only: bool
    basename_only: bool


def _translate(body: str) -> str:
    out: list[str] = []
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c == "*":
            if body.startswith("**", i):
                j = i + 2
                if body.startswith("/", j):
                    out.append("(?:.*/)?")
                    i = j + 1
                else:
                    out.append(".*")
                    i = j
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and body[j] in "!^":
                j += 1
            if j < n and body[j] == "]":
                j += 1
            while j < n and body[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(c))
                i += 1
            else:
                cls = body[i + 1 : j]
                if cls[:1] in ("!", "^"):
                    cls = "^" + cls[1:]
                out.append("[" + cls.replace("\\", "\\\\") + "]")
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def _compile(pattern: str) -> _Rule:
    p = pattern.strip().replace("\\", "/")
    if not p or p.startswith("#"):
        raise ConfigError(f"glob {pattern!r}: empty patterns and comments are not allowed")
    if p.startswith("!"):
        raise ConfigError(f"glob {pattern!r}: negation is not supported")
    dir_only = p.endswith("/")
    p = p.rstrip("/")
    anchored = p.startswith("/")
    p = p.lstrip("/")
    if not p:
        raise ConfigError(f"glob {pattern!r}: the pattern names nothing")
    basename_only = "/" not in p and not anchored
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            regex = re.compile(_translate(p))
    except (re.error, FutureWarning) as exc:
        raise ConfigError(f"glob {pattern!r}: {exc}") from exc
    return _Rule(regex, dir_only, basename_only)


class GlobSet:
    def __init__(self, patterns: Iterable[str]):
        self.patterns: tuple[str, ...] = tuple(patterns)
        self._rules = [_compile(p) for p in self.patterns]

    def matches(self, path: str) -> bool:
        parts = path.split("/")
        candidates = [("/".join(parts[:k]), True) for k in range(1, len(parts))] + [(path, False)]
        for rule in self._rules:
            for candidate, is_dir in candidates:
                if rule.dir_only and not is_dir:
                    continue
                target = candidate.rsplit("/", 1)[-1] if rule.basename_only else candidate
                if rule.regex.fullmatch(target):
                    return True
        return False
