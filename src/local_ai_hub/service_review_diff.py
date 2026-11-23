from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Any

from .budget import estimate_tokens

_REVIEW_DIFF_MIN_CHUNK_TOKENS: int = 256
_REVIEW_DIFF_CONTEXT_FRACTION: float = 0.5
_MAX_REVIEW_DIFF_CHUNKS: int = 8
_REVIEW_SYNTHESIS_CONTEXT_TOKENS: int = 6000
_UNIFIED_HUNK_RE: re.Pattern[str] = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")

# Public aliases for constants
REVIEW_DIFF_MIN_CHUNK_TOKENS = _REVIEW_DIFF_MIN_CHUNK_TOKENS
REVIEW_DIFF_CONTEXT_FRACTION = _REVIEW_DIFF_CONTEXT_FRACTION
MAX_REVIEW_DIFF_CHUNKS = _MAX_REVIEW_DIFF_CHUNKS
REVIEW_SYNTHESIS_CONTEXT_TOKENS = _REVIEW_SYNTHESIS_CONTEXT_TOKENS
UNIFIED_HUNK_RE = _UNIFIED_HUNK_RE


def _safe_int(val: Any, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    if isinstance(val, bool) or val is None:
        return default
    try:
        if isinstance(val, float) and not math.isfinite(val):
            return default
        res = int(val)
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res


def _review_text_error(value: Any) -> str | None:
    """Validate model review output, returning an error message if missing or malformed."""
    if not isinstance(value, str) or not value.strip():
        return "Model returned empty review output."
    text = value.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    # Match SUMMARY: with tolerance for markdown headers (#, ##), bullet points (- , * ),
    # bolding (**SUMMARY:** or **SUMMARY**), backticks (`SUMMARY:`), or 1 introductory line.
    match = re.search(
        r"(?:^|\n)(?:#{1,6}\s*)?(?:\*{1,2}|`{1,3})?(?:(?:\d+[\.\)]|[-*+])\s+)?(?:\*{1,2}|`{1,3})?(?:SUMMARY|SYNTHESIS|OVERALL SUMMARY)(?:\*{1,2}|`{1,3})?:?[ \t]*(.*)$",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match is None or match.start() > 1000:
        return "Model output did not start with the required SUMMARY: header."
    words = re.findall(r"[^\W\d_]+", match.group(1), flags=re.UNICODE)
    if len(words) < 1:
        return "Model returned an incomplete or malformed review summary."
    return None


def _review_failure_details(response: Any) -> dict[str, Any]:
    """Preserve bounded execution state when a chunked review fails."""
    if not isinstance(response, dict):
        return {}
    details: dict[str, Any] = {}
    error_code = response.get("error_code")
    if isinstance(error_code, str):
        error_code = error_code.strip()
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", error_code):
            details["error_code"] = error_code
    for key in (
        "retryable",
        "operation_not_started",
        "timed_out",
        "outcome_unknown",
        "cancelled",
        "cleanup_unconfirmed",
        "output_truncated",
        "terminal",
    ):
        value = response.get(key)
        if isinstance(value, bool):
            details[key] = value
    model = response.get("model")
    if isinstance(model, str) and model.strip():
        details["model"] = model.strip()[:120]
    return details


def _review_model_identity(value: Any) -> str:
    """Normalize Ollama quantization/instruct tags for tier comparisons."""
    model = str(value or "").strip().casefold()
    return re.sub(r"-(?:instruct|q\d+).*?$", "", model)


def _merge_review_segment_results(
    segment_results: list[dict[str, Any]],
    *,
    label: str,
    task_type: str,
    chunked: bool,
    synthesis_context_budget: int,
    synthesis_task: str,
    max_output_tokens: int,
    complexity: str,
    delegate: Callable[[dict[str, Any]], Any] | Any,
    priority: int = 5,
) -> tuple[str, dict[str, Any]]:
    """Return raw review output or a bounded synthesis of chunked results."""
    raw_text = "\n\n".join(
        f"### {label} {index}/{len(segment_results)}\n{str(item.get('text', '')).strip()}"
        for index, item in enumerate(segment_results, start=1)
    )
    if not chunked:
        return str(segment_results[0].get("text", "")), {"enabled": False}

    if estimate_tokens(raw_text) > synthesis_context_budget:
        return raw_text, {"enabled": True, "degraded": True, "error": "Segment findings exceed synthesis budget."}
    try:
        merged = delegate(
            {
                "task_type": task_type,
                "task": synthesis_task,
                "context": raw_text,
                "complexity": complexity,
                "max_tokens": min(max_output_tokens, 1800),
                "priority": int(priority),
            },
        )
        if isinstance(merged, dict) and merged.get("success") is not False:
            output_error = _review_text_error(merged.get("text"))
            if output_error is None:
                return str(merged["text"]), {
                    "enabled": True,
                    "degraded": False,
                    "model": merged.get("model"),
                }
            error = f"Synthesis returned unusable output: {output_error}"
        else:
            error = (
                merged.get("error", "Synthesis returned no text.")
                if isinstance(merged, dict)
                else "Synthesis returned no result."
            )
        return raw_text, {"enabled": True, "degraded": True, "error": str(error)}
    except Exception as exc:
        return raw_text, {"enabled": True, "degraded": True, "error": str(exc)}


def _split_review_diff(diff_text: str, max_tokens: int) -> list[str]:
    """Split a unified diff into bounded, file/hunk-aligned review inputs."""
    if not isinstance(diff_text, str) or not diff_text.strip():
        return []
    budget = _safe_int(max_tokens, default=_REVIEW_DIFF_MIN_CHUNK_TOKENS, min_val=_REVIEW_DIFF_MIN_CHUNK_TOKENS)
    sections = [part for part in re.split(r"(?=^diff --git )", diff_text, flags=re.MULTILINE) if part]
    if not sections:
        return [diff_text] if diff_text else []

    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for section in sections:
        if estimate_tokens(section) <= budget:
            if current and estimate_tokens(current + section) > budget:
                flush()
            current += section
            continue

        flush()
        chunks.extend(_split_large_review_file(section, budget))
    flush()
    return chunks or [diff_text]


def _split_large_review_file(section: str, budget: int) -> list[str]:
    """Split a single large file diff into chunks aligned on hunk boundaries."""
    lines = section.splitlines(keepends=True)
    hunk_starts = [index for index, line in enumerate(lines) if line.startswith("@@ ")]
    if not hunk_starts:
        return [section]

    prefix = "".join(lines[:hunk_starts[0]])
    hunks = [
        "".join(lines[start:end])
        for start, end in zip(hunk_starts, hunk_starts[1:] + [len(lines)], strict=False)
    ]
    chunks: list[str] = []
    pending_hunks: list[str] = []

    def flush_pending() -> None:
        if pending_hunks:
            chunks.append(prefix + "".join(pending_hunks))
            pending_hunks.clear()

    for hunk in hunks:
        candidate = prefix + "".join(pending_hunks) + hunk
        if estimate_tokens(candidate) <= budget:
            pending_hunks.append(hunk)
            continue

        flush_pending()
        if estimate_tokens(prefix + hunk) <= budget:
            pending_hunks.append(hunk)
        else:
            chunks.extend(_split_large_review_hunk(prefix, hunk, budget))

    flush_pending()
    return chunks or [section]


def _split_large_review_hunk(prefix: str, hunk: str, budget: int) -> list[str]:
    """Split a single oversized hunk into smaller valid unified diff hunks."""
    lines = hunk.splitlines(keepends=True)
    if not lines:
        return [prefix + hunk]
    match = _UNIFIED_HUNK_RE.match(lines[0].rstrip("\r\n"))
    if match is None:
        return [prefix + hunk]

    old_start = int(match.group(1))
    old_consumed = 0
    new_start = int(match.group(3))
    new_consumed = 0
    old_count = new_count = 0
    suffix = match.group(5)
    body: list[str] = []
    chunks: list[str] = []

    def render(part: list[str], old_offset: int, new_offset: int, old_lines: int, new_lines: int) -> str:
        header = f"@@ -{old_start + old_offset},{old_lines} +{new_start + new_offset},{new_lines} @@{suffix}\n"
        return prefix + header + "".join(part)

    def flush_body() -> None:
        nonlocal old_consumed, new_consumed, old_count, new_count, body
        if not body:
            return
        chunks.append(render(body, old_consumed, new_consumed, old_count, new_count))
        old_consumed += old_count
        new_consumed += new_count
        old_count = new_count = 0
        body = []

    for line in lines[1:]:
        adds_old = int(line.startswith((" ", "-")))
        adds_new = int(line.startswith((" ", "+")))
        proposed = body + [line]
        candidate = render(proposed, old_consumed, new_consumed, old_count + adds_old, new_count + adds_new)
        if body and estimate_tokens(candidate) > budget:
            flush_body()
        body.append(line)
        old_count += adds_old
        new_count += adds_new
    flush_body()
    return chunks or [prefix + hunk]


# Public aliases
review_text_error = _review_text_error
review_failure_details = _review_failure_details
review_model_identity = _review_model_identity
merge_review_segment_results = _merge_review_segment_results
split_review_diff = _split_review_diff
split_large_review_file = _split_large_review_file
split_large_review_hunk = _split_large_review_hunk

__all__ = [
    "_MAX_REVIEW_DIFF_CHUNKS",
    "_REVIEW_DIFF_CONTEXT_FRACTION",
    "_REVIEW_DIFF_MIN_CHUNK_TOKENS",
    "_REVIEW_SYNTHESIS_CONTEXT_TOKENS",
    "_UNIFIED_HUNK_RE",
    "MAX_REVIEW_DIFF_CHUNKS",
    "REVIEW_DIFF_CONTEXT_FRACTION",
    "REVIEW_DIFF_MIN_CHUNK_TOKENS",
    "REVIEW_SYNTHESIS_CONTEXT_TOKENS",
    "UNIFIED_HUNK_RE",
    "_merge_review_segment_results",
    "_review_failure_details",
    "_review_model_identity",
    "_review_text_error",
    "_split_large_review_file",
    "_split_large_review_hunk",
    "_split_review_diff",
    "merge_review_segment_results",
    "review_failure_details",
    "review_model_identity",
    "review_text_error",
    "split_large_review_file",
    "split_large_review_hunk",
    "split_review_diff",
]
