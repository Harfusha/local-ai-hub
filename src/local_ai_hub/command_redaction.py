"""Secret redaction for captured command output."""

from __future__ import annotations

import re


_SECRET_PATTERNS = (
    re.compile(r"(?i)(--?(?:password|token|secret|api[-_]?key)\s*[= ]\s*)([^\s]+)"),
    re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+"),
    re.compile(r"(?i)(basic\s+)[A-Za-z0-9+/=]{16,}"),
    re.compile(r"sk-[a-zA-Z0-9_\-]{16,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(aws_secret_access_key\s*=\s*)([^\s]+)"),
)


def redact_secrets(text: str) -> str:
    if not text:
        return ""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups in (1, 2):
            redacted = pattern.sub(r"\1***", redacted)
        else:
            redacted = pattern.sub("***REDACTED_SECRET***", redacted)
    return redacted
