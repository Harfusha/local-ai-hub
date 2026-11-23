from __future__ import annotations

import re

_SECURITY_AUDIT_SECRETS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS Access Key", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
    ("GitHub Token", re.compile(r"\b(ghp_[0-9a-zA-Z]{36}|github_pat_[0-9a-zA-Z_]{82})\b")),
    ("Slack Token", re.compile(r"\b(xox[baprs]-[0-9a-zA-Z]{10,48})\b")),
    ("Private Key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Hardcoded Password", re.compile(r"""(?:password|passwd|pwd|secret|api_key)\s*[:=]\s*["']([^"'\s]{6,})["']""", re.I)),
]

_SECURITY_AUDIT_SMELLS: list[tuple[str, re.Pattern[str]]] = [
    ("Unsafe eval/exec", re.compile(r"(?<![.\w])(eval|exec)\s*\(")),
    ("Unsafe Pickle", re.compile(r"\bpickle\.loads?\s*\(")),
    ("Unsafe PyYAML", re.compile(r"\byaml\.load\s*\([^,]+(?:\)|,\s*Loader\s*=\s*(?:yaml\.)?(?:Unsafe|Full)?Loader\b)")),
    ("Shell Injection Risk", re.compile(r"\bsubprocess\.(?:Popen|run|call)\s*\(.*shell\s*=\s*True", re.S)),
]


def _pattern_match_lines(text: str, pattern: re.Pattern[str]) -> list[int]:
    """Map regex matches to lines with one cumulative scan, not repeated prefixes."""
    line_number = 1
    previous_start = 0
    matched_lines: set[int] = set()
    for match in pattern.finditer(text):
        line_number += text.count("\n", previous_start, match.start())
        matched_lines.add(line_number)
        previous_start = match.start()
    return sorted(matched_lines)


_YAML_LOAD_START = re.compile(r"\byaml\.load\s*\(")
_YAML_LOADER_SUFFIX = re.compile(r",\s*Loader\s*=\s*(?:yaml\.)?(?:Unsafe|Full)?Loader\b")


def _yaml_load_match_lines(text: str) -> list[int]:
    """Match the PyYAML audit rule without rescanning an unterminated suffix."""
    cursor = 0
    segment_end = -1
    last_close = -1
    loader_end = None
    line_number = 1
    previous_start = 0
    matched_lines: set[int] = set()
    for match in _YAML_LOAD_START.finditer(text):
        start, content_start = match.start(), match.end()
        if start < cursor:
            continue
        if start >= segment_end:
            comma = text.find(",", content_start)
            segment_end = comma if comma >= 0 else len(text) + 1
            last_close = text.rfind(")", content_start, comma if comma >= 0 else len(text))
            suffix = _YAML_LOADER_SUFFIX.match(text, comma) if comma >= 0 else None
            loader_end = suffix.end() if suffix else None
        if loader_end is not None and segment_end > content_start:
            cursor = loader_end
        elif last_close > content_start:
            cursor = last_close + 1
        else:
            continue
        line_number += text.count("\n", previous_start, start)
        matched_lines.add(line_number)
        previous_start = start
    return sorted(matched_lines)
