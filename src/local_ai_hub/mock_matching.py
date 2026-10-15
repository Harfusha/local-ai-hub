"""Bounded mock-route matchers; explicit regexes use a restricted safe subset."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit


def _safe_regex(pattern: str) -> re.Pattern[str]:
    if not isinstance(pattern, str) or not pattern or len(pattern) > 256:
        raise ValueError("path_regex must contain 1..256 characters")
    in_class = False
    escaped = False
    repeats = 0
    for index, char in enumerate(pattern):
        if escaped:
            if char.isdigit() or char in {"A", "Z", "b", "B", "g", "k"}:
                raise ValueError("path_regex backreferences and boundary escapes are unsupported")
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == "[" and not in_class:
            in_class = True
        elif char == "]" and in_class:
            in_class = False
        elif not in_class:
            if char in "()|{}":
                raise ValueError("path_regex groups, alternatives and counted repeats are unsupported")
            if char in "*+?":
                repeats += 1
                if repeats > 1:
                    raise ValueError("path_regex supports at most one repetition operator")
            if (char == "^" and index != 0) or (char == "$" and index != len(pattern) - 1):
                raise ValueError("path_regex anchors must be at the ends")
    if escaped or in_class:
        raise ValueError("path_regex has an incomplete escape or character class")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError("invalid path_regex") from exc


def _wildcard(value: str, pattern: str) -> bool:
    """Glob '*' and '?' only, with bounded caller inputs and no regex expansion."""
    i = j = 0
    star = -1
    resume = 0
    while i < len(value):
        if j < len(pattern) and (pattern[j] == "?" or pattern[j] == value[i]):
            i += 1
            j += 1
        elif j < len(pattern) and pattern[j] == "*":
            star, resume = j, i
            j += 1
        elif star >= 0:
            resume += 1
            i, j = resume, star + 1
        else:
            return False
    return all(char == "*" for char in pattern[j:])


@dataclass(frozen=True)
class MockRouteMatcher:
    method: str
    path: re.Pattern[str]
    query: tuple[tuple[str, str], ...]

    def matches(self, method: str, target: str) -> bool:
        if len(target) > 4096 or self.method != method:
            return False
        try:
            parts = urlsplit(target)
            if len(parts.path) > 2048 or not self.path.fullmatch(parts.path):
                return False
            values = parse_qs(parts.query, keep_blank_values=True, max_num_fields=64)
        except ValueError:
            return False
        return all(any(len(value) <= 512 and _wildcard(value, pattern)
                       for value in values.get(key, [])) for key, pattern in self.query)


def compile_mock_matcher(endpoint: dict[str, Any]) -> MockRouteMatcher:
    method = endpoint.get("method", "GET")
    if not isinstance(method, str) or method.upper() not in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}:
        raise ValueError("unsupported mock method")
    explicit = endpoint.get("path_regex")
    if explicit is not None:
        path = _safe_regex(explicit)
    else:
        template = endpoint.get("path", "")
        if not isinstance(template, str) or not template.startswith("/") or len(template) > 2048:
            raise ValueError("mock path must begin with '/' and be at most 2048 characters")
        chunks: list[str] = []
        cursor = 0
        for parameter in re.finditer(r"\{[A-Za-z0-9_]+\}", template):
            if (parameter.start() and template[parameter.start() - 1] != "/") or (
                parameter.end() < len(template) and template[parameter.end()] != "/"
            ):
                raise ValueError("mock template parameters must occupy a whole path segment")
            chunks.extend((re.escape(template[cursor:parameter.start()]), "[^/]+"))
            cursor = parameter.end()
        chunks.append(re.escape(template[cursor:]))
        path = re.compile("".join(chunks))
    query = endpoint.get("query_matchers", {})
    if not isinstance(query, dict) or len(query) > 16 or any(
        not isinstance(key, str) or not key or len(key) > 128
        or not isinstance(value, str) or len(value) > 128 for key, value in query.items()
    ):
        raise ValueError("query_matchers must contain at most 16 bounded string wildcard rules")
    return MockRouteMatcher(method.upper(), path, tuple(query.items()))
