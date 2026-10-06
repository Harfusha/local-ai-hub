from __future__ import annotations

"""Bounded agent-facing response projection.

The Hub may need large payloads internally, but an agent only needs the smallest
decision-grade envelope.  This module applies an aggregate estimate after the
existing semantic projection and keeps exact detail behind artifact/evidence IDs.
"""

from hashlib import sha256
from typing import Any, Mapping

from .compact import compact_result, syntax_aware_truncate
from .token_accounting import json_tokens, token_efficiency_metadata


_POINTER_KEYS = (
    "success", "supported", "unsupported", "status", "error", "warning", "message",
    "action", "task_id", "work_id", "cache_hit", "coalesced", "in_progress",
    "terminal", "retryable", "artifact_id", "artifact_ids", "evidence_id",
    "evidence_ids", "changed_paths", "affected_tests", "summary", "text",
    "context", "context_pack", "adaptive_context_pack", "contract", "reuse_candidates", "mappings", "relevance", "model_warnings",
    "context_id", "repo_revision", "stale", "warnings", "delta_from", "since_hash",
    # A compiled task context is the authoritative handoff contract.  Keep its
    # bounded projection in pointer responses; dropping it silently turns a
    # successful context call into an unauditable text-only result.
    "task_context", "complete", "partial", "source_layers", "provenance",
    "omitted_sections", "next_action", "estimated_tokens", "truncated",
    "repository_required", "etag",
)

_CONTEXT_PROTECTED_KEYS = (
    "success", "complete", "partial", "task_context", "context_id", "etag",
    "evidence_ids", "repo_revision", "stale", "warnings", "omitted_sections",
    "context_pack",
    "next_action", "adaptive_context_pack",
)


def _safe_limit(value: Any, default: int) -> int:
    try:
        return max(64, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _bounded_string(value: str, max_chars: int) -> str:
    """Truncate metadata strings to an explicit character bound."""
    limit = max(1, int(max_chars))
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _bounded_pointer_item(value: Any, *, budget_chars: int, depth: int = 0) -> Any:
    if depth > 3:
        return "[…depth…]"
    if isinstance(value, str):
        return syntax_aware_truncate(value, budget_chars)
    if isinstance(value, list):
        return [_bounded_pointer_item(item, budget_chars=budget_chars, depth=depth + 1) for item in value[:8]]
    if isinstance(value, dict):
        return {
            str(key)[:160]: _bounded_pointer_item(item, budget_chars=budget_chars, depth=depth + 1)
            for key, item in list(value.items())[:8]
        }
    return value


def _pointer_envelope(
    value: Any,
    *,
    max_tokens: int,
    reuse_key: str = "",
    reused: bool = False,
    protected_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Keep status, IDs and a bounded summary while omitting bulk detail."""
    budget_chars = max(96, max_tokens * 3)
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key in dict.fromkeys((*_POINTER_KEYS, *protected_keys)):
            if key not in value:
                continue
            out[key] = _bounded_pointer_item(value[key], budget_chars=budget_chars)
    elif isinstance(value, str):
        out["text"] = syntax_aware_truncate(value, budget_chars)
    else:
        out["value"] = value
    if reuse_key:
        out["reuse_key"] = reuse_key[:160]
    if reused:
        out["reused"] = True
    return out


def _fit_to_tokens(
    value: dict[str, Any], max_tokens: int, *, protected_keys: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Drop optional envelope fields until the aggregate estimate fits."""
    protected = set(protected_keys)
    optional = (
        "text", "message", "warning", "changed_paths", "affected_tests",
        "evidence_ids", "evidence_id", "artifact_ids", "summary",
    )
    for key in optional:
        if key in protected:
            continue
        if json_tokens(value) <= max_tokens:
            break
        value.pop(key, None)
    if json_tokens(value) > max_tokens:
        for key, item in list(value.items()):
            if key == "response_budget" or key in protected or not isinstance(item, str):
                continue
            value[key] = syntax_aware_truncate(item, max(32, max_tokens * 2))
            if json_tokens(value) <= max_tokens:
                break
    if json_tokens(value) > max_tokens:
        keep_keys = (
            "success", "status", "error", "artifact_id", "reuse_key", "reused",
            "response_budget", *protected_keys,
        )
        keep = {key: value[key] for key in dict.fromkeys(keep_keys) if key in value}
        value.clear()
        value.update(keep)
    return value


def _with_budget_meta(
    value: dict[str, Any],
    *,
    requested: int,
    original: int,
    reused: bool = False,
    protected_keys: tuple[str, ...] = (),
    token_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    value["response_budget"] = {
        "requested_tokens": requested,
        "original_tokens": original,
        "returned_tokens": 0,
        "truncated": True,
        "reused": reused,
    }
    effective_protected = protected_keys
    if token_metadata is not None:
        value["token_efficiency"] = token_efficiency_metadata(token_metadata)
    _fit_to_tokens(value, requested, protected_keys=effective_protected)
    for _ in range(16):
        returned = min(requested, json_tokens(value))
        if value["response_budget"]["returned_tokens"] == returned:
            break
        value["response_budget"]["returned_tokens"] = returned
    return value


def _bounded_context_pack(value: Any, *, budget_chars: int) -> Any:
    """Keep context identity and one exact citation in a bounded response."""
    if not isinstance(value, dict):
        return _bounded_pointer_item(value, budget_chars=budget_chars)
    result: dict[str, Any] = {}
    for key in ("context_id", "repo_revision"):
        item = value.get(key)
        if isinstance(item, str) and item:
            result[key] = _bounded_string(item, min(160, budget_chars))
    evidence = value.get("evidence")
    if isinstance(evidence, list):
        citations: list[dict[str, Any]] = []
        for item in evidence[:24]:
            if not isinstance(item, dict):
                continue
            citation: dict[str, Any] = {}
            for key in ("evidence_id", "path", "start_line", "end_line", "source"):
                field = item.get(key)
                if isinstance(field, str):
                    citation[key] = _bounded_string(field, min(160, budget_chars))
                elif isinstance(field, int) and not isinstance(field, bool):
                    citation[key] = field
            if citation.get("evidence_id") and citation.get("path"):
                citations.append(citation)
                break
        if citations:
            result["evidence"] = citations
    evidence_ids = value.get("evidence_ids")
    if isinstance(evidence_ids, (list, tuple)) and evidence_ids:
        result["evidence_ids"] = [_bounded_string(str(evidence_ids[0]), min(160, budget_chars))]
    return result


def _retain_bounded_context_citation(
    candidate: Any,
    source: Any,
    *,
    protected_keys: tuple[str, ...],
    budget_chars: int,
) -> Any:
    """Apply the context citation contract to every reduced budget candidate."""
    if not isinstance(candidate, dict) or not isinstance(source, dict):
        return candidate
    for key in ("adaptive_context_pack", "context_pack"):
        pack = source.get(key)
        if key in protected_keys and isinstance(pack, dict):
            candidate[key] = _bounded_context_pack(pack, budget_chars=budget_chars)
    return candidate


def _budget_rejection(
    *,
    requested: int,
    original: int,
    source: Any = None,
    protected_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return bounded deterministic error when required metadata cannot fit."""
    preserved = source if isinstance(source, dict) else {}
    error = str(preserved.get("error") or "max_response_tokens too small for authoritative context envelope")
    metadata_variants = (
        {
            "requested_tokens": requested,
            "original_tokens": original,
            "returned_tokens": 0,
            "truncated": True,
            "rejected": True,
            "unit": "estimated_tokens",
        },
        {
            "requested_tokens": requested,
            "returned_tokens": 0,
            "rejected": True,
            "unit": "estimated_tokens",
        },
        {"requested_tokens": requested, "rejected": True},
        {},
    )
    for metadata in metadata_variants:
        for error_chars in (256, 128, 64, 32, 16, 8, 1):
            value: dict[str, Any] = {
                "success": False,
                "error": _bounded_string(error, error_chars),
            }
            status_code = preserved.get("status_code")
            value["status_code"] = (
                status_code
                if isinstance(status_code, int) and not isinstance(status_code, bool)
                else 400
            )
            for key, fallback in (("terminal", True), ("retryable", False)):
                item = preserved.get(key)
                value[key] = item if isinstance(item, bool) else fallback
            if metadata:
                value["response_budget"] = dict(metadata)
            for key in protected_keys:
                if key not in preserved or key in {"success", "error", "status_code", "terminal", "retryable", "response_budget"}:
                    continue
                item = preserved[key]
                if key in {"adaptive_context_pack", "context_pack"}:
                    value[key] = _bounded_context_pack(item, budget_chars=error_chars)
                elif key in {"evidence_ids", "artifact_ids"} and isinstance(item, (list, tuple)):
                    value[key] = [_bounded_string(str(part), min(160, error_chars)) for part in item[:1]]
                elif key == "warnings" and isinstance(item, (list, tuple)):
                    value[key] = [
                        _bounded_pointer_item(item[0], budget_chars=error_chars)
                    ] if item else []
                elif key == "changed_paths" and isinstance(item, (list, tuple)):
                    value[key] = [
                        _bounded_string(str(item[0]), min(160, error_chars))
                    ] if item else []
                elif isinstance(item, str):
                    value[key] = _bounded_string(item, min(160, error_chars))
                else:
                    value[key] = _bounded_pointer_item(item, budget_chars=error_chars)
            if json_tokens(value) > requested:
                continue
            if "returned_tokens" in value.get("response_budget", {}):
                for _ in range(8):
                    returned = json_tokens(value)
                    value["response_budget"]["returned_tokens"] = returned
                    if json_tokens(value) == returned:
                        break
                if json_tokens(value) != value["response_budget"]["returned_tokens"]:
                    # Tokenizer boundaries can make the self-referential count
                    # oscillate by one. Try a shorter error/metadata variant.
                    continue
            if json_tokens(value) <= requested:
                return value
    return {"success": False, "error": "max_response_tokens too small"}


def _bounded_result(
    result: Any,
    *,
    requested: int,
    original: int,
    source: Any = None,
    protected_keys: tuple[str, ...] = (),
) -> Any:
    """Never let envelope metadata invalidate the advertised hard budget."""
    if json_tokens(result) <= requested:
        return result
    return _budget_rejection(
        requested=requested,
        original=original,
        source=source if source is not None else result,
        protected_keys=protected_keys,
    )


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
    protected_keys: tuple[str, ...] = (),
    token_metadata: Mapping[str, Any] | None = None,
) -> Any:
    """Apply a hard aggregate estimate to an already projected MCP value."""
    requested = _safe_limit(max_tokens, 1200)
    original = json_tokens(value)
    if reuse_only:
        envelope = _pointer_envelope(
            value,
            max_tokens=requested,
            reuse_key=reuse_key,
            reused=True,
            protected_keys=protected_keys,
        )
        result = _with_budget_meta(
            envelope,
            requested=requested,
            original=original,
            reused=True,
            protected_keys=protected_keys,
            token_metadata=token_metadata,
        )
        return _bounded_result(
            result,
            requested=requested,
            original=original,
            source=value,
            protected_keys=protected_keys,
        ) if protected_keys or json_tokens(result) > requested else result
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
        _retain_bounded_context_citation(
            compact_result(value, max_text_chars=text_chars, max_evidence=evidence, max_items=items),
            value,
            protected_keys=protected_keys,
            budget_chars=text_chars,
        ),
        _retain_bounded_context_citation(
            compact_result(
                value,
                max_text_chars=max(180, text_chars // 2),
                max_evidence=max(1, evidence // 2),
                max_items=max(1, items // 2),
            ),
            value,
            protected_keys=protected_keys,
            budget_chars=max(180, text_chars // 2),
        ),
        _retain_bounded_context_citation(
            _pointer_envelope(
                value,
                max_tokens=requested,
                reuse_key=reuse_key,
                protected_keys=protected_keys,
            ),
            value,
            protected_keys=protected_keys,
            budget_chars=max(180, text_chars // 2),
        ),
    ]
    for candidate in candidates:
        if json_tokens(candidate) <= requested:
            if isinstance(candidate, dict):
                result = _with_budget_meta(
                    candidate,
                    requested=requested,
                    original=original,
                    protected_keys=protected_keys,
                    token_metadata=token_metadata,
                )
                if json_tokens(result) <= requested:
                    return result
                if not protected_keys:
                    return _bounded_result(
                        result,
                        requested=requested,
                        original=original,
                        source=value,
                        protected_keys=protected_keys,
                    )
                continue
            return candidate

    envelope = _pointer_envelope(
        value,
        max_tokens=max(64, requested // 2),
        reuse_key=reuse_key,
        protected_keys=protected_keys,
    )
    result = _with_budget_meta(
        envelope,
        requested=requested,
        original=original,
        protected_keys=protected_keys,
        token_metadata=token_metadata,
    )
    return _bounded_result(
        result,
        requested=requested,
        original=original,
        source=value,
        protected_keys=protected_keys,
    )
