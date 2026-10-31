from __future__ import annotations

"""Bounded agent-facing response projection.

The Hub may need large payloads internally, but an agent only needs the smallest
decision-grade envelope.  This module applies an aggregate estimate after the
existing semantic projection and keeps exact detail behind artifact/evidence IDs.
"""

from hashlib import sha256
import math
import re
import time
from typing import Any, Mapping

from .compact import compact_result, syntax_aware_truncate
from .token_accounting import json_tokens, token_efficiency_metadata


LIFECYCLE_PROTECTED_KEYS = (
    "operation", "operation_id", "action", "status", "state", "accepted", "completed",
    "job_id", "task_id", "work_id", "request_id", "execution_id", "in_progress",
    "request_not_sent", "outcome_unknown", "mutation_applied", "operation_not_started",
    "complete", "partial", "cancel_requested",
    "expires_at", "artifact_id", "output_artifact_id", "task_context_artifact_id",
)

_POINTER_KEYS = (
    *LIFECYCLE_PROTECTED_KEYS,
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
    "repository_required", "etag", "context_truncated", "context_chars",
    "tasks", "task", "records", "matches", "items", "negative_knowledge",
    "receipts", "total_count", "active_count", "has_more", "offset", "limit", "next_offset",
    "symbols", "files", "board", "columns", "missing_criteria", "unverified_criteria",
    "plan", "plans", "file_revision", "plan_id", "rel_path", "git_branch", "git_head",
)


def _is_current_evidence_id(value: Any, evidence_store: Any) -> bool:
    """Require fresh, content-addressed provenance using either store API."""
    evidence_id = str(value or "").strip()
    if not re.fullmatch(r"E[0-9a-fA-F]{20}", evidence_id) or evidence_store is None:
        return False

    validator = getattr(evidence_store, "validate_current", None)
    if callable(validator):
        try:
            return validator(evidence_id) is True
        except Exception:
            return False

    getter = getattr(evidence_store, "get", None)
    identity = getattr(evidence_store, "_id", None)
    if not callable(getter) or not callable(identity):
        return False
    try:
        item = getter(evidence_id, verify=True)
        if (
            not item.get("success")
            or item.get("stale") is not False
            or item.get("evidence_id") != evidence_id
        ):
            return False
        return identity(
            str(item["root"]),
            str(item["path"]),
            str(item["file_sha256"]),
            int(item["start_line"]),
            int(item["end_line"]),
            str(item["text"]),
        ) == evidence_id
    except Exception:
        return False

_CONTEXT_PROTECTED_KEYS = (
    "success", "complete", "partial", "task_context", "context_id", "etag", "task_context_artifact_id",
    "evidence_ids", "repo_revision", "stale", "warnings", "omitted_sections",
    "next_action", "evidence_id", "error", "status_code", "terminal", "retryable",
    "context_truncated", "context_chars", "context_pack", "adaptive_context_pack",
)
_RESPONSE_PROTECTED_KEYS = (
    *LIFECYCLE_PROTECTED_KEYS,
    "success", "status", "error", "status_code", "terminal", "retryable", "evidence_id", "evidence_ids",
    "semantic_quality", "review_consistency", "advisory_only", "quality_warning", "bypass_reason",
)
_IDENTIFIER_KEYS = {
    "operation_id", "job_id", "output_artifact_id",
    "artifact_id", "task_context_artifact_id", "context_id", "etag", "repo_revision", "revision", "task_id", "work_id",
    "request_id", "execution_id",
    "delta_from", "since_hash", "reuse_key",
}


def _bounded_string(value: str, max_chars: int) -> str:
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    # syntax_aware_truncate may add a marker longer than a tiny character cap;
    # the response-budget boundary must still honor the requested bound.
    return syntax_aware_truncate(value, max(1, max_chars))[:max(1, max_chars)]


def _safe_limit(value: Any, default: int) -> int:
    try:
        def_val = max(64, int(default)) if not isinstance(default, bool) else 1200
    except (TypeError, ValueError, OverflowError):
        def_val = 1200
    try:
        if value is None or isinstance(value, bool):
            return def_val
        val_float = float(value)
        if not math.isfinite(val_float) or val_float <= 0:
            return def_val
        return max(64, int(val_float))
    except (TypeError, ValueError, OverflowError):
        return def_val


def is_valid_evidence_id(value: Any) -> bool:
    """Return True if value is a canonical E[0-9a-fA-F]{20} evidence identifier."""
    if value is None or isinstance(value, bool) or not isinstance(value, str):
        return False
    clean = value.strip()
    return bool(re.fullmatch(r"E[0-9a-fA-F]{20}", clean))


def _bounded_pointer_item(value: Any, *, budget_chars: int, depth: int = 0) -> Any:
    if depth > 3:
        return "[…depth…]"
    if isinstance(value, str):
        return _bounded_string(value, budget_chars)
    if isinstance(value, list):
        return [_bounded_pointer_item(item, budget_chars=budget_chars, depth=depth + 1) for item in value[:8]]
    if isinstance(value, dict):
        return {
            str(key)[:160]: _bounded_pointer_item(item, budget_chars=budget_chars, depth=depth + 1)
            for key, item in list(value.items())[:8]
        }
    return value



def _bounded_task_summary(task: Any, budget_chars: int) -> Any:
    if not isinstance(task, dict):
        return _bounded_pointer_item(task, budget_chars=budget_chars)
    out: dict[str, Any] = {}
    for key in ("task_id", "status", "owner", "created_at", "updated_at", "heartbeat_expires_at", "stale"):
        if key in task:
            out[key] = task[key]
    checkpoint = task.get("checkpoint")
    if isinstance(checkpoint, dict):
        if "phase" in checkpoint and checkpoint["phase"]:
            out["phase"] = checkpoint["phase"]
        if "next_action" in checkpoint and checkpoint["next_action"]:
            out["next_action"] = checkpoint["next_action"]
    contract = task.get("contract")
    if isinstance(contract, dict):
        goal = contract.get("goal")
        if isinstance(goal, str) and goal:
            out["goal"] = syntax_aware_truncate(goal, min(120, budget_chars), marker="…")
    return out


def _bounded_record_summary(record: Any, budget_chars: int) -> Any:
    if not isinstance(record, dict):
        return _bounded_pointer_item(record, budget_chars=budget_chars)
    out: dict[str, Any] = {}
    for key in ("record_id", "id", "scope", "scope_id", "key", "operation_class", "timestamp", "score"):
        if key in record:
            out[key] = record[key]
    for key in ("value", "summary", "message", "root_cause", "verified_fix"):
        if key in record:
            val = record[key]
            out[key] = syntax_aware_truncate(str(val), min(120, budget_chars), marker="…") if isinstance(val, (str, dict, list)) else val
    return out


def _is_meaningfully_empty_success(candidate: Any, source: Any) -> bool:
    """Return True if candidate claimed success but stripped all primary results without a recovery pointer."""
    if not isinstance(candidate, dict) or not isinstance(source, dict):
        return False
    if candidate.get("success") is not True or source.get("success") is not True:
        return False
    # If candidate has an authentic artifact pointer or materialization, it is recoverable.
    if candidate.get("artifact_id") or candidate.get("output_artifact_id") or candidate.get("materialization"):
        return False

    collection_keys = (
        "tasks", "records", "matches", "items", "negative_knowledge",
        "results", "symbols", "files", "receipts",
    )
    for key in collection_keys:
        source_val = source.get(key)
        if isinstance(source_val, list) and len(source_val) > 0:
            cand_val = candidate.get(key)
            if cand_val is None or (isinstance(cand_val, list) and len(cand_val) == 0):
                return True

    if isinstance(source.get("task"), dict) and "task" not in candidate:
        return True
    if any(k in source and isinstance(source[k], dict) for k in ("context_pack", "adaptive_context_pack", "task_context")):
        if not any(k in candidate and isinstance(candidate[k], dict) for k in ("context_pack", "adaptive_context_pack", "task_context")):
            return True

    return False

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
        has_artifact = bool(
            value.get("artifact_id")
            or value.get("output_artifact_id")
            or (isinstance(value.get("artifact"), dict) and value["artifact"].get("id"))
        )
        for key in dict.fromkeys((*_POINTER_KEYS, *protected_keys)):
            if key not in value:
                continue
            if key == "tasks" and isinstance(value["tasks"], list):
                if has_artifact:
                    continue
                tasks = value["tasks"]
                if not tasks:
                    out["tasks"] = []
                else:
                    max_count = max(1, min(len(tasks), max_tokens // 45))
                    if max_tokens <= 128:
                        max_count = 1
                    bounded = [
                        _bounded_task_summary(t, min(40 if max_tokens <= 128 else 120, budget_chars))
                        for t in tasks[:max_count]
                    ]
                    out["tasks"] = bounded
                    if len(tasks) > len(bounded):
                        out["tasks_omitted"] = len(tasks) - len(bounded)
            elif key in {"records", "matches", "negative_knowledge"} and isinstance(value[key], list):
                if has_artifact:
                    continue
                items = value[key]
                if not items:
                    out[key] = []
                else:
                    max_count = max(1, min(len(items), max_tokens // 45))
                    if max_tokens <= 128:
                        max_count = 1
                    bounded = [
                        _bounded_record_summary(r, min(40 if max_tokens <= 128 else 120, budget_chars))
                        for r in items[:max_count]
                    ]
                    out[key] = bounded
                    if len(items) > len(bounded):
                        out[f"{key}_omitted"] = len(items) - len(bounded)
            elif key in {"items", "board"} and isinstance(value[key], list):
                if has_artifact:
                    continue
                items = value[key]
                if not items:
                    out[key] = []
                else:
                    max_count = max(1, min(len(items), max_tokens // 40))
                    if max_tokens <= 128:
                        max_count = 1
                    bounded = [_bounded_pointer_item(it, budget_chars=budget_chars) for it in items[:max_count]]
                    out[key] = bounded
                    if len(items) > len(bounded):
                        out[f"{key}_omitted"] = len(items) - len(bounded)
            elif key in {"results", "symbols", "files"} and has_artifact:
                continue
            else:
                out[key] = _bounded_pointer_item(value[key], budget_chars=budget_chars)
        artifact = value.get("artifact")
        artifact = artifact if isinstance(artifact, dict) else {}
        artifact_id = str(value.get("artifact_id") or artifact.get("id") or "").strip()
        expiry = value.get("fresh_until", value.get("artifact_expires_at", artifact.get("expires_at")))
        if artifact_id:
            out["artifact_id"] = artifact_id[:160]
            out["materialization"] = {
                "tool": "local_ai_artifact",
                "action": "get",
                "artifact_id": artifact_id[:160],
                "offset": 0,
            }
        if expiry is not None:
            try:
                expiry_value = float(expiry)
            except (TypeError, ValueError, OverflowError):
                expiry_value = 0.0
            out["fresh_until"] = expiry_value
            out["freshness"] = "fresh" if expiry_value > time.time() else "stale"
        elif artifact_id:
            out["freshness"] = "unknown"
    elif isinstance(value, str):
        out["text"] = _bounded_string(value, budget_chars)
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
        "evidence_ids", "evidence_id", "artifact_ids", "summary", "token_efficiency",
    )
    for key in optional:
        if key in protected or key not in value:
            continue
        if json_tokens(value) <= max_tokens:
            break
        value.pop(key, None)
    if json_tokens(value) > max_tokens:
        for key, item in list(value.items()):
            if (
                key == "response_budget"
                or (key in protected and key not in ("context", "text", "summary"))
                or not isinstance(item, str)
            ):
                continue
            value[key] = _bounded_string(item, max(32, max_tokens * 2))
            if json_tokens(value) <= max_tokens:
                break
    if json_tokens(value) > max_tokens:
        # Keep protected text fields present, but never let their full body
        # override the requested aggregate response cap.
        for key in ("context", "text", "summary"):
            current = value.get(key)
            while isinstance(current, str) and len(current) > 1 and json_tokens(value) > max_tokens:
                current = _bounded_string(current, max(1, len(current) // 2))
                value[key] = current
    if json_tokens(value) > max_tokens:
        while isinstance(value.get("tasks"), list) and len(value["tasks"]) > 1:
            cur = json_tokens(value)
            if cur <= max_tokens:
                break
            excess = cur - max_tokens
            avg_task_tokens = max(1, cur // len(value["tasks"]))
            pop_count = min(len(value["tasks"]) - 1, max(1, excess // avg_task_tokens))
            del value["tasks"][-pop_count:]
            value["tasks_omitted"] = value.get("tasks_omitted", 0) + pop_count
        if isinstance(value.get("tasks"), list) and len(value["tasks"]) == 1 and json_tokens(value) > max_tokens:
            t = value["tasks"][0]
            if isinstance(t, dict):
                for k in ("goal", "next_action", "phase", "contract"):
                    if json_tokens(value) <= max_tokens:
                        break
                    t.pop(k, None)

        while isinstance(value.get("records"), list) and len(value["records"]) > 1:
            cur = json_tokens(value)
            if cur <= max_tokens:
                break
            excess = cur - max_tokens
            avg_rec_tokens = max(1, cur // len(value["records"]))
            pop_count = min(len(value["records"]) - 1, max(1, excess // avg_rec_tokens))
            del value["records"][-pop_count:]
            value["records_omitted"] = value.get("records_omitted", 0) + pop_count
        if isinstance(value.get("records"), list) and len(value["records"]) == 1 and json_tokens(value) > max_tokens:
            r = value["records"][0]
            if isinstance(r, dict):
                for k in ("value", "summary", "message", "root_cause", "verified_fix"):
                    if json_tokens(value) <= max_tokens:
                        break
                    r.pop(k, None)

        while isinstance(value.get("items"), list) and len(value["items"]) > 1:
            cur = json_tokens(value)
            if cur <= max_tokens:
                break
            excess = cur - max_tokens
            avg_item_tokens = max(1, cur // len(value["items"]))
            pop_count = min(len(value["items"]) - 1, max(1, excess // avg_item_tokens))
            del value["items"][-pop_count:]
            value["items_omitted"] = value.get("items_omitted", 0) + pop_count

    if json_tokens(value) > max_tokens:
        collection_keep = ()
        if not (value.get("artifact_id") or value.get("materialization")):
            collection_keep = (
                "tasks", "records", "matches", "items", "negative_knowledge",
                "total_count", "active_count", "tasks_omitted", "records_omitted", "items_omitted",
                "plan", "plans", "file_revision", "plan_id", "rel_path", "git_branch", "git_head",
            )
        keep_keys = (
            "success", "status", "error", "artifact_id", "reuse_key", "reused",
            "freshness", "fresh_until", "materialization", "response_budget",
            *collection_keep,
            *protected_keys,
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
    evidence_store: Any = None,
    profile: str = "compact",
) -> dict[str, Any]:
    if profile == "dense":
        value.pop("token_efficiency", None)
        value.pop("path_hint_usage", None)
        value["response_budget"] = {
            "requested_tokens": requested,
            "returned_tokens": 0,
        }
        _fit_to_tokens(value, requested, protected_keys=protected_keys)
        value["response_budget"]["returned_tokens"] = json_tokens(value)
        return value
    value["response_budget"] = {
        "requested_tokens": requested,
        "original_tokens": original,
        "returned_tokens": 0,
        "truncated": True,
        "reused": reused,
        "unit": "estimated_tokens",
    }
    effective_protected = protected_keys
    has_valid_baseline = False
    if token_metadata is not None:
        source = dict(token_metadata)
        accounting = {
            key: item
            for key, item in token_efficiency_metadata(source).items()
            if item is not None
            and item != ""
            and not (isinstance(item, (int, float)) and not isinstance(item, bool) and item == 0)
        }
        accounting["protocol_tokens_est"] = _nonnegative_int(source.get("protocol_tokens_est"))
        accounting["schema_tokens_est"] = _nonnegative_int(source.get("schema_tokens_est"))
        accounting["local_compute_reused_tokens_est"] = _nonnegative_int(source.get("local_compute_reused_tokens_est"))
        baseline_evidence = str(source.get("baseline_evidence_id") or "").strip()
        baseline_tokens = _optional_nonnegative_int(source.get("baseline_tokens_est"))
        has_valid_baseline = (
            baseline_tokens is not None
            and _is_current_evidence_id(baseline_evidence, evidence_store)
        )
        if has_valid_baseline:
            accounting["baseline_tokens_est"] = baseline_tokens
            accounting["baseline_evidence_id"] = baseline_evidence[:64]
            accounting["token_savings_delta_est"] = baseline_tokens
            accounting["avoided_payload_tokens_est"] = 0
        else:
            accounting.pop("baseline_tokens_est", None)
            accounting.pop("baseline_evidence_id", None)
            accounting.pop("token_savings_delta_est", None)
            accounting["avoided_payload_tokens_est"] = 0
        value["token_efficiency"] = accounting
        # Accounting is useful but must not crowd out protected error/evidence or
        # context identity fields when an unusually small ceiling is requested.
    _fit_to_tokens(value, requested, protected_keys=effective_protected)
    for _ in range(8):
        returned = json_tokens(value)
        value["response_budget"]["returned_tokens"] = returned
        accounting = value.get("token_efficiency")
        if isinstance(accounting, dict) and has_valid_baseline:
            accounting["token_savings_delta_est"] = accounting["baseline_tokens_est"] - returned
            accounting["avoided_payload_tokens_est"] = max(0, accounting["token_savings_delta_est"])
        finalized = json_tokens(value)
        if finalized == returned and finalized <= requested:
            return value
        if finalized > requested:
            _fit_to_tokens(value, requested, protected_keys=effective_protected)

    # If accounting cannot settle, omit savings claims rather than return a
    # stale estimate. Keep other diagnostics for the deterministic rejection.
    accounting = value.get("token_efficiency")
    if isinstance(accounting, dict):
        accounting.pop("baseline_tokens_est", None)
        accounting.pop("baseline_evidence_id", None)
        accounting.pop("token_savings_delta_est", None)
        accounting["avoided_payload_tokens_est"] = 0
    return _budget_rejection(
        requested=requested,
        original=original,
        source=value,
        protected_keys=effective_protected,
    )


def _bounded_context_pack(
    value: Any, *, budget_chars: int, include_decisions: bool = True,
    include_revision: bool = True, include_context_id: bool = True,
) -> Any:
    """Keep context identity and one exact citation in a bounded response."""
    if not isinstance(value, dict):
        return _bounded_pointer_item(value, budget_chars=budget_chars)
    result: dict[str, Any] = {}
    identity_keys = (
        (("context_id",) if include_context_id else ())
        + (("repo_revision",) if include_revision else ())
    )
    for key in identity_keys:
        item = value.get(key)
        if isinstance(item, str) and item:
            result[key] = _bounded_string(item, min(160, budget_chars))
    # Master decision fields remain authoritative when a T14 citation is reduced.
    # They are duplicated by the outer response in rejection envelopes, so omit
    # them only as a later compaction step when the diagnostic needs the space.
    if include_decisions:
        for key in (
            "success", "status", "status_code", "terminal", "retryable", "error",
            "degraded", "stale", "fallback_used", "requires_override", "requires_approval",
            "decision_recorded", "decision_persisted", "task_status", "waiting", "stop_code",
        ):
            if key in value:
                result[key] = _bounded_pointer_item(value[key], budget_chars=budget_chars)
    evidence = value.get("evidence")
    has_citation = False
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
                has_citation = True
                break
        if citations:
            result["evidence"] = citations
    evidence_ids = value.get("evidence_ids")
    if not has_citation and isinstance(evidence_ids, (list, tuple)) and evidence_ids:
        result["evidence_ids"] = [_bounded_string(str(evidence_ids[0]), min(160, budget_chars))]
    return result


def _retain_bounded_context_citation(
    candidate: Any, source: Any, *, protected_keys: tuple[str, ...], budget_chars: int,
) -> Any:
    """Keep one complete citation when compacting an oversized context pack."""
    if not isinstance(candidate, dict) or not isinstance(source, dict):
        return candidate
    for key in ("adaptive_context_pack", "context_pack"):
        if key in protected_keys and isinstance(source.get(key), dict):
            candidate[key] = _bounded_context_pack(source[key], budget_chars=budget_chars)
    return candidate


def _budget_rejection(
    *, requested: int, original: int, source: Any = None, protected_keys: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Return bounded deterministic error when required metadata cannot fit."""
    preserved = source if isinstance(source, dict) else {}
    original_error = preserved.get("error")
    error = str(original_error) if original_error else "max_response_tokens too small"
    base_keys = {"success", "error", "status", "status_code", "terminal", "retryable", "response_budget"}

    # Shrink values and optional metadata in stages. Protected means the field
    # remains present; pathological values still must fit the hard cap.
    metadata_variants = (
        {"requested_tokens": requested, "original_tokens": original, "returned_tokens": 0, "truncated": True, "rejected": True, "unit": "estimated_tokens"},
        {"requested_tokens": requested, "returned_tokens": 0, "rejected": True, "unit": "estimated_tokens"},
        {"requested_tokens": requested, "returned_tokens": 0, "truncated": True, "rejected": True},
        {"requested_tokens": requested, "returned_tokens": 0, "truncated": True},
    )
    # Prefer a compact command-failure protocol envelope over shortening IDs
    # or retaining artifact payloads that are optional for recovery.
    protocol_keys = (
        "status", "status_code", "terminal", "retryable", "request_id", "execution_id",
        "exit_code", "outcome_unknown", "request_not_sent", "in_progress", "timed_out",
        "mutation_applied", "operation_not_started", "reused", "reuse_key",
    )
    fast_path_keys = {*protocol_keys, "summary", "error"}
    has_unhandled_protected = any(
        key in preserved and key not in fast_path_keys for key in protected_keys
    )
    error_limits: tuple[int | None, ...] = (None, 256, 128, 64, 32, 16)
    summary_limits: tuple[int | None, ...] = (None, 512, 256, 128, 96, 64, 48, 32, 24, 16, 8, 1)
    command_failure = preserved.get("success") is False and (
        "execution_id" in preserved or preserved.get("exit_code") not in (None, 0)
    )
    for error_limit in error_limits if command_failure and not has_unhandled_protected else ():
        if error_limit is not None and error_limit < min(64, len(error)):
            continue
        for summary_limit in summary_limits:
            core: dict[str, Any] = {"success": False}
            if original_error is not None:
                core["error"] = error if error_limit is None else _bounded_string(error, error_limit)
            for key in protocol_keys:
                if key not in preserved:
                    continue
                item = preserved[key]
                core[key] = _bounded_string(str(item), 160) if key in {"request_id", "execution_id"} else item
            summary = preserved.get("summary")
            if isinstance(summary, str):
                core["summary"] = summary if summary_limit is None else _bounded_string(summary, summary_limit)
            for metadata in metadata_variants:
                candidate = dict(core)
                candidate["response_budget"] = dict(metadata)
                for _ in range(16):
                    returned = json_tokens(candidate)
                    candidate["response_budget"]["returned_tokens"] = returned
                    if json_tokens(candidate) == returned:
                        break
                if json_tokens(candidate) <= requested:
                    return candidate

    # Try compacting duplicated context diagnostics before shortening the
    # top-level error. Keep complete context decision fields whenever possible.
    context_variants = ((True, True), (False, True), (False, False))
    # Preserve the complete diagnostic and citation before compacting the
    # duplicated context pointer or its optional accounting metadata.
    for error_chars in (512, 256, 128, 64, 32, 16):
        if error_chars < min(64, len(error)):
            continue
        # Keep complete accounting whenever any compact projection fits.
        for budget_metadata in metadata_variants:
            # Keep at least one exact evidence ID before retaining decisions or
            # revision duplicated inside the context pack. Top-level decision
            # fields remain in the envelope and are authoritative.
            for evidence_count in (8, 4, 2, 1, 0):
                for include_context_decisions, include_context_revision in context_variants:
                    value: dict[str, Any] = {
                        "success": False,
                        "error": _bounded_string(error, error_chars),
                    }
                    if budget_metadata:
                        value["response_budget"] = dict(budget_metadata)
                    accounting = preserved.get("token_efficiency")
                    if requested >= 128 and isinstance(accounting, dict):
                        value["token_efficiency"] = {"avoided_payload_tokens_est": 0}
                    for key in protected_keys:
                        if key not in preserved or key in base_keys:
                            continue
                        item = preserved[key]
                        if key in {"adaptive_context_pack", "context_pack"}:
                            value[key] = _bounded_context_pack(
                                item,
                                budget_chars=error_chars,
                                include_decisions=include_context_decisions,
                                include_revision=include_context_revision and "repo_revision" not in preserved,
                                include_context_id="context_id" not in preserved,
                            )
                        elif key == "evidence_ids" and isinstance(item, (list, tuple)):
                            # Preserve whole IDs and bound only the number emitted.
                            value[key] = [str(item[index])[:160] for index in range(min(evidence_count, len(item)))]
                        elif key == "evidence_id":
                            value[key] = str(item)[:160]
                        elif key == "summary" and command_failure and isinstance(item, str):
                            # Keep the failure class even when the protected
                            # artifact inventory leaves only a tiny envelope.
                            # Bulk summary detail is expendable; classification
                            # is useful to callers deciding whether to retry.
                            value[key] = _bounded_string(item, 24)
                        elif key in _IDENTIFIER_KEYS:
                            value[key] = _bounded_string(str(item), 160)
                        else:
                            value[key] = _bounded_pointer_item(item, budget_chars=error_chars)

                    # Retain protocol outcome fields when supplied, but give evidence
                    # and the diagnostic precedence when the requested cap is tiny.
                    for key in (
                        "status", "status_code", "terminal", "retryable",
                        "mutation_applied", "operation_not_started",
                        "request_id", "execution_id", "reused", "reuse_key",
                    ):
                        if key in preserved and key not in value:
                            value[key] = _bounded_pointer_item(preserved[key], budget_chars=error_chars)

                    if json_tokens(value) <= requested:
                        stable = "response_budget" not in value or "returned_tokens" not in value["response_budget"]
                        if "response_budget" in value and "returned_tokens" in value["response_budget"]:
                            for _ in range(16):
                                returned = json_tokens(value)
                                value["response_budget"]["returned_tokens"] = returned
                                if json_tokens(value) == returned:
                                    stable = True
                                    break
                        if stable and json_tokens(value) <= requested:
                            return value

    # At the minimum public budget, even protocol metadata may not fit beside
    # unusually large protected fields. Keep the diagnostic keys and evidence
    # first, with the same deterministic size bounds.
    minimal: dict[str, Any] = {"success": False, "error": _bounded_string(error, 512)}
    for key in (
        "status", "status_code", "terminal", "retryable",
        "mutation_applied", "operation_not_started",
        "request_id", "execution_id", "reused", "reuse_key",
    ):
        if key in preserved:
            minimal[key] = _bounded_pointer_item(preserved[key], budget_chars=160)
    for key in protected_keys:
        if key in base_keys or key not in preserved:
            continue
        item = preserved[key]
        if key in {"adaptive_context_pack", "context_pack"}:
            minimal[key] = _bounded_context_pack(item, budget_chars=160)
        elif key == "evidence_ids" and isinstance(item, (list, tuple)):
            minimal[key] = [str(part)[:160] for part in item[:1]]
        elif key == "evidence_id":
            minimal[key] = str(item)[:160]
        elif key == "summary" and command_failure and isinstance(item, str):
            minimal[key] = _bounded_string(item, 24)
        elif key in _IDENTIFIER_KEYS:
            minimal[key] = _bounded_string(str(item), 160)
        else:
            minimal[key] = _bounded_pointer_item(item, budget_chars=1)
    if json_tokens(minimal) <= requested:
        for metadata in (
            {"requested_tokens": requested, "rejected": True, "unit": "estimated_tokens"},
            {"requested_tokens": requested, "rejected": True},
        ):
            candidate = dict(minimal)
            if metadata:
                candidate["response_budget"] = dict(metadata)
                for _ in range(16):
                    returned = json_tokens(candidate)
                    candidate["response_budget"]["returned_tokens"] = returned
                    if json_tokens(candidate) == returned:
                        break
            if json_tokens(candidate) <= requested:
                return candidate
    # If the full protected envelope is mathematically too large, keep diagnostic
    # and evidence fields first; never return a success-shaped partial result.
    protocol: dict[str, Any] = {}
    for key in (
        "status", "status_code", "terminal", "retryable", "outcome_unknown",
        "request_not_sent", "in_progress", "timed_out", "exit_code",
        "mutation_applied", "operation_not_started",
        "request_id", "execution_id", "reused", "reuse_key",
    ):
        if key not in preserved:
            continue
        item = preserved[key]
        if key in {"request_id", "execution_id"}:
            identifier = str(item)
            if len(identifier) <= 160:
                protocol[key] = _bounded_string(identifier, 160)
        else:
            protocol[key] = _bounded_pointer_item(item, budget_chars=160)
    for key in ("evidence_ids", "evidence_id"):
        if key not in protected_keys or key not in preserved:
            continue
        item = preserved[key]
        protocol[key] = (
            [str(part)[:160] for part in item[:1]]
            if key == "evidence_ids" and isinstance(item, (list, tuple))
            else str(item)[:160]
        )
    # Protected payloads can be too large even after compaction. Retain the
    # diagnostic and protocol outcome, then spend the remaining cap on error.
    metadata_variants = (
        {"requested_tokens": requested, "rejected": True, "unit": "estimated_tokens"},
        {"requested_tokens": requested, "rejected": True},
    )

    decision_keys = (
        "terminal", "retryable", "outcome_unknown", "request_not_sent",
        "in_progress", "timed_out", "mutation_applied", "operation_not_started",
    )
    protocol_variants = [protocol]
    without_evidence = {key: item for key, item in protocol.items() if key not in {"evidence_ids", "evidence_id"}}
    if without_evidence != protocol:
        protocol_variants.append(without_evidence)
    without_ids = {
        key: item for key, item in without_evidence.items()
        if key not in {"request_id", "execution_id"}
    }
    if without_ids != protocol_variants[-1]:
        protocol_variants.append(without_ids)
    decisions_only = {key: protocol[key] for key in decision_keys if key in protocol}
    if decisions_only != protocol_variants[-1]:
        protocol_variants.append(decisions_only)

    def candidate_for(error_chars: int, fields: dict[str, Any]) -> dict[str, Any] | None:
        critical = {"success": False, "error": _bounded_string(error, error_chars), **fields}
        for metadata in metadata_variants:
            candidate = dict(critical)
            candidate["response_budget"] = dict(metadata)
            for _ in range(4):
                returned = json_tokens(candidate)
                candidate["response_budget"]["returned_tokens"] = returned
                if json_tokens(candidate) == returned:
                    break
            if json_tokens(candidate) <= requested:
                return candidate
        return None

    # Serialized token count is monotonic with this bounded string length.
    # Binary search keeps the rejection path bounded for pathological payloads.
    fallback_best: dict[str, Any] | None = None
    for fields in protocol_variants:
        low, high = 1, min(512, len(error))
        best: dict[str, Any] | None = None
        while low <= high:
            middle = (low + high) // 2
            candidate = candidate_for(middle, fields)
            if candidate is None:
                high = middle - 1
            else:
                best = candidate
                low = middle + 1
        # Keep optional protocol detail when it still leaves a readable error.
        if best is not None and len(str(best.get("error", ""))) >= 12:
            return best
        if best is not None and (
            fallback_best is None
            or len(str(best.get("error", ""))) > len(str(fallback_best.get("error", "")))
        ):
            fallback_best = best
    if fallback_best is not None:
        return fallback_best
    return {"success": False, "error": "budget"} if requested >= json_tokens({"success": False, "error": "budget"}) else {"success": False}


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
        requested=requested, original=original, source=source, protected_keys=protected_keys
    )


def _reconcile_existing_budget(value: Any) -> dict[str, Any] | None:
    """Refresh returned_tokens on an existing response envelope without mutating input."""
    if not isinstance(value, dict) or not isinstance(value.get("response_budget"), dict):
        return None
    metadata = value["response_budget"]
    actual = json_tokens(value)
    if metadata.get("returned_tokens") == actual:
        return value
    result = dict(value)
    result_metadata = dict(metadata)
    result["response_budget"] = result_metadata
    for _ in range(4):
        returned = json_tokens(result)
        result_metadata["returned_tokens"] = returned
        if json_tokens(result) == returned:
            return result
    return result


def _restore_protected_fields(candidate: Any, source: Any, protected_keys: tuple[str, ...]) -> Any:
    """Keep source values authoritative until the bounded rejection path fits them."""
    if isinstance(candidate, dict) and isinstance(source, dict):
        for key in protected_keys:
            if key in source:
                candidate[key] = source[key]
    return candidate


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
        if parsed < 0 or float(value) != parsed:
            return None
        return parsed
    except (TypeError, ValueError, OverflowError):
        return None


def result_id(value: Any) -> str:
    """Return a short opaque id; never expose the payload in the id."""
    return sha256(repr(value).encode("utf-8", errors="replace")).hexdigest()[:16]


def delta_response(previous: Any, current: Any, *, result_id: str = "") -> dict[str, Any]:
    """Return only changed top-level mapping fields plus stable status fields."""
    res_id = str(result_id or "").replace("\x00", "")[:160]
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return {"result_id": res_id, "delta": {"changed": {"value": current}, "added": {}, "removed": []}}
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
    out: dict[str, Any] = {"result_id": res_id, "delta": {"changed": changed, "added": added, "removed": removed}}
    for key in ("success", "status", "error", "warning", "terminal", "retryable"):
        if key in current:
            out[key] = current[key]
    return out


_INLINE_EVIDENCE_TEXT_KEYS = frozenset({"content", "text", "raw", "snippet", "excerpt", "source_text"})


def _redact_inline_evidence_text(value: Any, *, inside_evidence: bool = False) -> Any:
    """Keep evidence provenance while leaving source bodies behind evidence IDs."""
    if isinstance(value, list):
        return [_redact_inline_evidence_text(item, inside_evidence=inside_evidence) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).casefold()
        if inside_evidence and normalized in _INLINE_EVIDENCE_TEXT_KEYS:
            continue
        result[key] = _redact_inline_evidence_text(
            item,
            inside_evidence=inside_evidence or normalized in {"evidence", "evidence_items"},
        )
    return result


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
    evidence_store: Any = None,
) -> Any:
    """Apply a hard aggregate estimate to an already projected MCP value."""
    requested = _safe_limit(max_tokens, 1200)
    original = json_tokens(value)
    protected = tuple(dict.fromkeys((*_RESPONSE_PROTECTED_KEYS, *protected_keys)))
    if isinstance(value, dict) and any(
        key in protected for key in ("context_id", "evidence_ids", "adaptive_context_pack", "context_pack")
    ):
        value = _redact_inline_evidence_text(value)
    reconciled = _reconcile_existing_budget(value)
    if (
        isinstance(value, dict)
        and value.get("success") is False
        and "status_code" in value
        and original <= requested
    ):
        if reconciled is None:
            return value
        if json_tokens(reconciled) <= requested:
            return reconciled
        return _bounded_result(
            reconciled, requested=requested, original=original,
            source=value, protected_keys=protected,
        )
    if reuse_only:
        envelope = _pointer_envelope(
            value,
            max_tokens=requested,
            reuse_key=reuse_key,
            reused=True,
            protected_keys=protected,
        )
        _restore_protected_fields(envelope, value, protected)
        result = _with_budget_meta(
            envelope,
            requested=requested,
            original=original,
            reused=True,
            protected_keys=protected,
            token_metadata=token_metadata,
            evidence_store=evidence_store,
            profile=profile,
        )
        return (
            result
            if json_tokens(result) <= requested
            else _bounded_result(
                result, requested=requested, original=original, source=value, protected_keys=protected
            )
        )
    if original <= requested:
        if not isinstance(value, dict):
            return value
        if profile == "dense":
            candidate = dict(reconciled or value)
            return _with_budget_meta(
                candidate,
                requested=requested,
                original=original,
                protected_keys=protected,
                token_metadata=token_metadata,
                evidence_store=evidence_store,
                profile=profile,
            )
        if token_metadata is None:
            if reconciled is None:
                return value
            if json_tokens(reconciled) <= requested:
                return reconciled
            return _bounded_result(
                reconciled, requested=requested, original=original,
                source=value, protected_keys=protected,
            )
        candidate = dict(reconciled or value)
        result = _with_budget_meta(
            candidate,
            requested=requested,
            original=original,
            protected_keys=protected,
            token_metadata=token_metadata,
            evidence_store=evidence_store,
            profile=profile,
        )
        return result if json_tokens(result) <= requested else _bounded_result(
            result, requested=requested, original=original, source=value, protected_keys=protected
        )

    profile_name = str(profile or "compact").strip().lower()
    if profile_name == "minimal":
        text_chars, evidence, items = 420, 2, 3
    elif profile_name == "dense":
        text_chars, evidence, items = 1200, 10, 20
    elif profile_name == "standard":
        text_chars, evidence, items = 1000, 6, 8
    elif profile_name == "debug":
        text_chars, evidence, items = 1800, 12, 20
    else:
        text_chars, evidence, items = 700, 4, 5

    candidates = [
        compact_result(value, max_text_chars=text_chars, max_evidence=evidence, max_items=items),
        compact_result(value, max_text_chars=max(180, text_chars // 2), max_evidence=max(1, evidence // 2), max_items=max(1, items // 2)),
        _pointer_envelope(
            value,
            max_tokens=requested,
            reuse_key=reuse_key,
            protected_keys=protected,
        ),
    ]
    for candidate in candidates:
        _restore_protected_fields(candidate, value, protected)
        _retain_bounded_context_citation(
            candidate, value, protected_keys=protected, budget_chars=text_chars,
        )
        if json_tokens(candidate) <= requested:
            if isinstance(candidate, dict):
                result = _with_budget_meta(
                    candidate,
                    requested=requested,
                    original=original,
                    protected_keys=protected,
                    token_metadata=token_metadata,
                    evidence_store=evidence_store,
                    profile=profile,
                )
                if json_tokens(result) <= requested:
                    if _is_meaningfully_empty_success(result, value):
                        continue
                    return result
                if not protected:
                    bounded = _bounded_result(
                        result, requested=requested, original=original, source=value, protected_keys=protected
                    )
                    if _is_meaningfully_empty_success(bounded, value):
                        continue
                    return bounded
                continue
            return candidate

    envelope = _pointer_envelope(
        value,
        max_tokens=max(64, requested // 2),
        reuse_key=reuse_key,
        protected_keys=protected,
    )
    _restore_protected_fields(envelope, value, protected)
    _retain_bounded_context_citation(
        envelope, value, protected_keys=protected, budget_chars=text_chars,
    )
    result = _with_budget_meta(
        envelope,
        requested=requested,
        original=original,
        protected_keys=protected,
        token_metadata=token_metadata,
        evidence_store=evidence_store,
        profile=profile,
    )
    bounded = _bounded_result(
        result, requested=requested, original=original, source=value, protected_keys=protected
    )
    if _is_meaningfully_empty_success(bounded, value):
        return _budget_rejection(
            requested=requested, original=original, source=value, protected_keys=protected
        )
    return bounded


def is_response_budgeted(value: Mapping[str, Any] | None) -> bool:
    """Return True if value has a valid response_budget dictionary."""
    if not isinstance(value, Mapping):
        return False
    budget = value.get("response_budget")
    return isinstance(budget, Mapping) and "returned_tokens" in budget


def get_response_budget_info(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return a dictionary copy of the response_budget metadata if present."""
    if not isinstance(value, Mapping):
        return None
    budget = value.get("response_budget")
    return dict(budget) if isinstance(budget, Mapping) else None


def get_returned_tokens(value: Mapping[str, Any] | None) -> int:
    """Return returned_tokens from response_budget if present, else 0."""
    if not isinstance(value, Mapping):
        return 0
    budget = value.get("response_budget")
    if isinstance(budget, Mapping) and "returned_tokens" in budget:
        try:
            return max(0, int(budget["returned_tokens"]))
        except (TypeError, ValueError, OverflowError):
            pass
    return 0


def is_budget_rejected(value: Mapping[str, Any] | None) -> bool:
    """Return True if response_budget signals that the requested limit was rejected."""
    if not isinstance(value, Mapping):
        return False
    budget = value.get("response_budget")
    if isinstance(budget, Mapping):
        return bool(budget.get("rejected", False))
    return False

