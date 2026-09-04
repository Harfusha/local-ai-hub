from __future__ import annotations

import math
from dataclasses import dataclass


TRUNCATION_MARKER = "\n\n[... context omitted to fit local budget ...]\n"


def estimate_tokens(text: str) -> int:
    """Conservative tokenizer-free estimate suitable for prompt budgeting/telemetry."""
    if not text:
        return 0
    return max(1, math.ceil(len(text.encode("utf-8")) / 3.4))


def chars_for_tokens(tokens: int) -> int:
    return max(0, int(tokens * 3.4))


@dataclass(frozen=True)
class PackedText:
    text: str
    estimated_tokens: int
    truncated: bool
    original_tokens: int


def fit_text(text: str, max_tokens: int, *, preserve_tail: bool = True) -> PackedText:
    max_tokens = max(64, int(max_tokens))
    original = estimate_tokens(text)
    if original <= max_tokens:
        return PackedText(text=text, estimated_tokens=original, truncated=False, original_tokens=original)

    # Token estimates use UTF-8 bytes, so character slicing can overshoot badly
    # for non-ASCII text. Keep the output within the same byte budget.
    budget = max(1, int(max_tokens * 3.4))
    marker = TRUNCATION_MARKER
    marker_bytes = len(marker.encode("utf-8"))
    usable = max(0, budget - marker_bytes)

    def prefix(value: str, limit: int) -> str:
        return value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")

    def suffix(value: str, limit: int) -> str:
        return value.encode("utf-8")[-limit:].decode("utf-8", errors="ignore")

    if preserve_tail and usable >= 800:
        head = int(usable * 0.72)
        fitted = prefix(text, head) + marker + suffix(text, usable - head)
    else:
        fitted = prefix(text, usable) + marker
    return PackedText(
        text=fitted,
        estimated_tokens=estimate_tokens(fitted),
        truncated=True,
        original_tokens=original,
    )
