from __future__ import annotations

from collections import Counter
from typing import Any


def compress_diagnostic_text(text: str, target_tokens: int = 650) -> dict[str, Any]:
    """Compress repetitive diagnostics without an inference call.

    The confidence score stays low for narrative text so callers can use a
    model-backed compressor for general prose.
    """
    lines = text.splitlines()
    if not lines:
        return {"success": True, "text": "", "confidence": 1.0, "deterministic": True}
    budget_lines = max(12, int(target_tokens * 4 / 90))
    needles = ("error", "fatal", "exception", "traceback", "failed", "failure", "warning", "assert", "panic", "timeout", "segfault", "passed", "success")
    diagnostic = sum(1 for line in lines[:2000] if any(n in line.lower() for n in needles))
    repetitive = 1.0 - (len(set(lines[:5000])) / max(1, min(len(lines), 5000)))
    if diagnostic == 0 and repetitive < 0.18:
        return {"success": False, "confidence": 0.2, "reason": "narrative/non-diagnostic input"}
    selected: list[str] = []
    seen: Counter[str] = Counter()
    important_idx = [i for i, line in enumerate(lines) if any(n in line.lower() for n in needles)]
    indices: set[int] = set()
    for i in important_idx:
        indices.update(range(max(0, i - 1), min(len(lines), i + 2)))
    indices.update(range(min(6, len(lines))))
    indices.update(range(max(0, len(lines) - 6), len(lines)))
    for i in sorted(indices):
        line = lines[i]
        seen[line] += 1
        if seen[line] > 2:
            continue
        selected.append(f"{i+1}: {line}")
        if len(selected) >= budget_lines:
            break
    repeats = [(line, count) for line, count in Counter(lines).most_common(8) if count > 2]
    if repeats:
        selected.append("REPEATED: " + "; ".join(f"{count}x {line[:120]}" for line, count in repeats))
    confidence = min(0.98, 0.82 + min(0.12, diagnostic * 0.01) + min(0.04, repetitive * 0.08))
    return {
        "success": True,
        "text": "\n".join(selected),
        "confidence": round(confidence, 4),
        "deterministic": True,
        "original_lines": len(lines),
        "selected_lines": len(selected),
    }
