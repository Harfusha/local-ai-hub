from __future__ import annotations

"""Bounded agent-facing response projection.

The Hub may need large payloads internally, but an agent only needs the smallest
decision-grade envelope.  This module applies an aggregate estimate after the
existing semantic projection and keeps exact detail behind artifact/evidence IDs.
"""

from hashlib import sha256
from typing import Any

from .compact import compact_result, syntax_aware_truncate
from .token_accounting import json_tokens


_POINTER_KEYS = (
    "success", "supported", "unsupported", "status", "error", "warning", "message",
    "action", "task_id", "work_id", "cache_hit", "coalesced", "in_progress",
    "terminal", "retryable", "artifact_id", "artifact_ids", "evidence_id",
    "evidence_ids", "changed_paths", "affected_tests", "summary", "text",
)


def _safe_limit(value: Any, default: int) -> int:
    try:
        return max(64, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _pointer_envelope(value: Any, *, max_tokens: int, reuse_key: str = "", reused: bool = False) -> dict[str, Any]:
    """Keep status, IDs and a bounded summary while omitting bulk detail."""
    budget_chars = max(96, max_tokens * 3)
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key in _POINTER_KEYS:
            if key not in value:
                continue
            item = value[key]
            if isinstance(item, str):
                out[key] = syntax_aware_truncate(item, budget_chars)
            elif isinstance(item, list):
                out[key] = item[:8]
            elif isinstance(item, dict):
                out[key] = {k: item[k] for k in list(item)[:8]}
            else:
                out[key] = item
    elif isinstance(value, str):
        out["text"] = syntax_aware_truncate(value, budget_chars)
    else:
        out["value"] = value
    if reuse_key:
        out["reuse_key"] = reuse_key[:160]
    if reused:
        out["reused"] = True
    return out


def _fit_to_tokens(value: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    """Drop optional envelope fields until the aggregate estimate fits."""
    optional = (
        "text", "message", "warning", "changed_paths", "affected_tests",
        "evidence_ids", "evidence_id", "artifact_ids", "summary",
    )
    for key in optional:
        if json_tokens(value) <= max_tokens:
            break
        value.pop(key, None)
    if json_tokens(value) > max_tokens:
        for key, item in list(value.items()):
            if key == "response_budget" or not isinstance(item, str):
                continue
            value[key] = syntax_aware_truncate(item, max(32, max_tokens * 2))
            if json_tokens(value) <= max_tokens:
                break
    if json_tokens(value) > max_tokens:
        keep = {key: value[key] for key in ("success", "status", "error", "artifact_id", "reuse_key", "reused", "response_budget") if key in value}
        value.clear()
        value.update(keep)
    return value


def _with_budget_meta(value: dict[str, Any], *, requested: int, original: int, reused: bool = False) -> dict[str, Any]:
    value["response_budget"] = {
        "requested_tokens": requested,
        "original_tokens": original,
        "returned_tokens": 0,
        "truncated": True,
        "reused": reused,
    }
    _fit_to_tokens(value, requested)
    value["response_budget"]["returned_tokens"] = min(requested, json_tokens(value))
    return value


def result_id(value: Any) -> str:
    """Return a short opaque id; never expose the payload in the id."""
    return sha256(repr(value).encode("utf-8", errors="replace")).hexdigest()[:16]


def delta_response(previous: Any, current: Any, *, result_id: str = "") -> dict[str, Any]:
    """Return only changed top-level mapping fields plus stable status fields."""
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return {"result_id": result_id, "delta": {"changed": {"value": current}, "added": {}, "removed": []}}
    changed: dict[str, Any] = {}
    added: dict[str, Any] = {}
    removed: list[str] = []
    for key, value in current.items():
        if key not in previous:
            added[key] = value
        elif previous[key] != value:
            changed[key] = value
    for key in previous:
        if key not in current:
            removed.append(key)
    out: dict[str, Any] = {"result_id": result_id, "delta": {"changed": changed, "added": added, "removed": removed}}
    for key in ("success", "status", "error", "warning", "terminal", "retryable"):
        if key in current:
            out[key] = current[key]
    return out


def budget_response(
    value: Any,
    *,
    max_tokens: int,
    profile: str = "compact",
    artifact_backed: bool = True,
    reuse_key: str = "",
    reuse_only: bool = False,
) -> Any:
    """Apply a hard aggregate estimate to an already projected MCP value."""
    requested = _safe_limit(max_tokens, 1200)
    original = json_tokens(value)
    if reuse_only:
        envelope = _pointer_envelope(value, max_tokens=requested, reuse_key=reuse_key, reused=True)
        return _with_budget_meta(envelope, requested=requested, original=original, reused=True)
    if original <= requested:
        return value

    profile_name = str(profile or "compact").strip().lower()
    if profile_name == "minimal":
        text_chars, evidence, items = 420, 2, 3
    elif profile_name == "standard":
        text_chars, evidence, items = 1000, 6, 8
    elif profile_name == "debug":
        text_chars, evidence, items = 1800, 12, 20
    else:
        text_chars, evidence, items = 700, 4, 5

    candidates = [
        compact_result(value, max_text_chars=text_chars, max_evidence=evidence, max_items=items),
        compact_result(value, max_text_chars=max(180, text_chars // 2), max_evidence=max(1, evidence // 2), max_items=max(1, items // 2)),
        _pointer_envelope(value, max_tokens=requested, reuse_key=reuse_key),
    ]
    for candidate in candidates:
        if json_tokens(candidate) <= requested:
            if isinstance(candidate, dict):
                return _with_budget_meta(candidate, requested=requested, original=original)
            return candidate

    envelope = _pointer_envelope(value, max_tokens=max(64, requested // 2), reuse_key=reuse_key)
    return _with_budget_meta(envelope, requested=requested, original=original)
