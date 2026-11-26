"""Small, deterministic privacy checks for canonical project knowledge."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_PRIVATE_FIELD = re.compile(
    r"(?:session|lease|token|password|passwd|secret|credential|receipt|evidenceid)",
    re.IGNORECASE,
)
_PRIVATE_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(?:password|passwd|token|secret|api[_-]?key|access[_-]?key|client[_-]?secret)\b\s*[:=]\s*[^\s,;]{4,}"),
    re.compile(r"(?i)\b(?:session|lease)[_-]?(?:id|key|token)\b\s*[:=]\s*[^\s,;]{4,}"),
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|xox[baprs]-[A-Za-z0-9-]{12,}|AKIA[0-9A-Z]{16})\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
)


def contains_private_project_data(value: Any) -> bool:
    """Return true for private field names or recognizable credential values."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str) and _PRIVATE_FIELD.search(re.sub(r"[^A-Za-z0-9]", "", key)):
                return True
            if contains_private_project_data(child):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(contains_private_project_data(child) for child in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _PRIVATE_VALUE_PATTERNS)
    return False
