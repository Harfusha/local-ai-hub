from __future__ import annotations

from .json_utils import dumps as json_dumps

import errno
import hashlib
import json
import logging
import base64
import math
import numbers
import os
import queue
import re
import sqlite3
import threading
import time
from contextlib import closing
from collections import deque
from pathlib import Path
from typing import Any

from .operation_contracts import operation_actions
from .laya_decisions import _CATEGORY_OPTIONS
from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error, quick_sanity_check
from .http_route_registry import (
    GET_ROUTE_HANDLER_BOUNDARIES,
    POST_ROUTE_REGISTRY,
    TELEMETRY_SAFE_GET_ROUTE_LABELS,
)
from .telemetry_contracts import (
    _LAYA_DECISION_FIELDS,
    _LAYA_ELIGIBILITY_FIELDS,
    load_telemetry_json,
    normalize_laya_decision_metadata,
)

logger = logging.getLogger(__name__)


_PATH_RE = re.compile(r"(?:(?:[A-Za-z]:\\\\|/)(?:[^\s:'\"<>|]+[/\\\\])+[^\s:'\"<>|]*)")
_LONG_TOKEN_RE = re.compile(r"\b(?:[A-Fa-f0-9]{24,}|[A-Za-z0-9_\-]{48,})\b")
_SAFE_REQUEST_ID_RE = re.compile(
    r"(?:[A-Fa-f0-9]{32}|[A-Fa-f0-9]{8}-(?:[A-Fa-f0-9]{4}-){3}[A-Fa-f0-9]{12}|req_[A-Fa-f0-9]{12})"
)
_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:[\\/][^\s<>|\"']+")
_UNC_PATH_RE = re.compile(r"\\\\[^\\/\s]+\\[^\\/\s]+(?:\\[^\s<>|\"']*)?")
_POSIX_PATH_RE = re.compile(r"(?<![\w:])/(?:[^/\s]+/)+[^/\s]*")
_POSIX_FILE_PATH_RE = re.compile(r"(?<![\w:])/[^\s/,;\"']+\.[A-Za-z0-9]{1,12}(?![\w-])")
_POSIX_ROOT_PATH_RE = re.compile(r"(?<![\w:/])/(?!/)[^\s/\\,;\"']+(?![\w/])")
_SAFE_HTTP_ROUTE_LABELS = frozenset(
    {
        "/slow", "/median", "/api/context/pack", "/api/debug-traces/{trace_id}",
        "/api/cross_repo_contract", "/api/ast_rename", "/api/repo/batch_replace", "/api/code_invariants",
        "/api/command",
    }
    | set(TELEMETRY_SAFE_GET_ROUTE_LABELS)
    | set(GET_ROUTE_HANDLER_BOUNDARIES)
    | {path for rule in POST_ROUTE_REGISTRY for path in rule.paths}
)
_SAFE_TOOL_ACTIONS = frozenset({
    "local_ai_status", "local_ai_task", "local_ai_repo", "local_ai_rag",
    "local_ai_coord", "local_ai_work", "local_ai_artifact",
    # repo actions
    "context", "outline", "symbols", "references", "skeletonize", "ast_grep",
    "code_index", "review_diff", "security_audit", "solve", "preprocess",
    # task actions
    "delegate", "explore", "reason", "review", "second_opinion", "compress",
    "vision", "transcribe", "batch", "submit", "status", "wait", "result", "cancel",
    # coord actions
    "task_create", "task_get", "task_checkpoint", "task_complete", "task_fail",
    "task_list", "ask", "answer", "memory_record", "memory_get", "memory_find", "context_compile",
    "verify_receipt", "verify_completion", "negative_knowledge_record",
    "negative_knowledge_find", "lease_acquire", "lease_renew", "lease_release",
    "memo_record", "memo_search",
    # rag actions
    "search", "ingest", "docset",
    # artifact actions
    "slice", "get", "read", "list",
    # system actions
    "hub_start", "hub_stop", "heartbeat", "cleanup",
})


def _validate_token_cost_rate(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{name} must be a finite non-negative number")
    try:
        rate = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite non-negative number") from exc
    if not math.isfinite(rate) or rate < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return rate
_MAX_QUERY_WINDOW_DAYS = 3650
_SENSITIVE_METADATA_VALUE_RE = re.compile(
    r"(?i)[\"']?(prompt|source(?:_text)?|input(?:_text)?|completion|output(?:_text)?|"
    r"response(?:_body)?|request(?:_body)?|body|payload|content|api[_-]?key|token|"
    r"password|secret|authorization)[\"']?\s*([=:])\s*.*$"
)
CLOUD_PRICING_PROFILES: dict[str, dict[str, Any]] = {
    "claude-5-sonnet": {
        "id": "claude-5-sonnet",
        "name": "Claude 5 Sonnet",
        "input": 2.50,
        "output": 12.50,
        "cache_read": 0.25,
        "cache_write": 3.125,
    },
    "claude-5-haiku": {
        "id": "claude-5-haiku",
        "name": "Claude 5 Haiku",
        "input": 0.50,
        "output": 2.50,
        "cache_read": 0.05,
        "cache_write": 0.625,
    },
    "claude-5-opus": {
        "id": "claude-5-opus",
        "name": "Claude 5 Opus",
        "input": 10.0,
        "output": 50.0,
        "cache_read": 1.00,
        "cache_write": 12.50,
    },
    "gpt-6": {
        "id": "gpt-6",
        "name": "GPT-6",
        "input": 2.00,
        "output": 8.00,
        "cache_read": 0.80,
        "cache_write": 2.00,
    },
    "gpt-6-mini": {
        "id": "gpt-6-mini",
        "name": "GPT-6 mini",
        "input": 0.10,
        "output": 0.40,
        "cache_read": 0.04,
        "cache_write": 0.10,
    },
    "gemini-3-flash": {
        "id": "gemini-3-flash",
        "name": "Gemini 3 Flash",
        "input": 0.05,
        "output": 0.20,
        "cache_read": 0.0125,
        "cache_write": 0.05,
    },
    "gemini-3-pro": {
        "id": "gemini-3-pro",
        "name": "Gemini 3 Pro",
        "input": 1.00,
        "output": 4.00,
        "cache_read": 0.20,
        "cache_write": 1.00,
    },
    "claude-3-5-sonnet": {
        "id": "claude-3-5-sonnet",
        "name": "Claude 3.5 / 3.7 Sonnet",
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-3-5-haiku": {
        "id": "claude-3-5-haiku",
        "name": "Claude 3.5 Haiku",
        "input": 0.80,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_write": 1.0,
    },
    "claude-3-opus": {
        "id": "claude-3-opus",
        "name": "Claude 3 Opus",
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    "gpt-4o": {
        "id": "gpt-4o",
        "name": "GPT-4o",
        "input": 2.50,
        "output": 10.0,
        "cache_read": 1.25,
        "cache_write": 2.50,
    },
    "gpt-4o-mini": {
        "id": "gpt-4o-mini",
        "name": "GPT-4o mini",
        "input": 0.15,
        "output": 0.60,
        "cache_read": 0.075,
        "cache_write": 0.15,
    },
    "gemini-2-flash": {
        "id": "gemini-2-flash",
        "name": "Gemini 2.0 / 1.5 Flash",
        "input": 0.10,
        "output": 0.40,
        "cache_read": 0.025,
        "cache_write": 0.10,
    },
    "gemini-2-pro": {
        "id": "gemini-2-pro",
        "name": "Gemini 2.0 / 1.5 Pro",
        "input": 1.25,
        "output": 5.0,
        "cache_read": 0.3125,
        "cache_write": 1.25,
    },
}

_SAVINGS_SOURCE_ALLOWLIST = frozenset({
    "cache_hit", "cache_or_local_reuse", "context_compaction", "delegated_context",
    "deterministic_outline", "local_compute", "measured_context", "reused",
    "response_compaction", "workspace_cache",
})
_DECISION_DETAIL_LIMIT = 24
_REPORT_GROUP_LIMIT = 100
_REPORT_CACHE_LIMIT = 16
_SUMMARY_CACHE_LIMIT = 16
_MAX_METADATA_LENGTH = 160
_MAX_TELEMETRY_REPORT_BYTES = 256 * 1024 - 64  # reserve space for HTTP envelope
_REPORT_TRIMMABLE_LISTS = (
    "runtime_snapshots", "daily", "by_agent", "by_model", "provider_token_usage",
    "by_operation", "execution_routes", "cache_layers", "hotspots", "routes", "cache", "bypass",
    "error_fingerprints",
)


def _encode_error_page_cursor(snapshot_id: int, snapshot_cutoff: float, row: tuple[Any, ...] | list[Any]) -> str:
    values = [int(snapshot_id), float(snapshot_cutoff), *(str(value or "") for value in row[:4])]
    raw = json_dumps(values, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_error_page_cursor(cursor: str | None) -> tuple[int, float, str, str, str, str] | None:
    if cursor in (None, ""):
        return None
    if len(cursor) > 1024:
        raise ValueError("error_cursor is too long")
    try:
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        values = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("error_cursor is invalid") from exc
    if (
        not isinstance(values, list) or len(values) != 6
        or isinstance(values[0], bool) or not isinstance(values[0], int) or values[0] < 0
        or isinstance(values[1], bool) or not isinstance(values[1], (int, float))
        or not math.isfinite(float(values[1]))
        or any(not isinstance(value, str) or len(value) > 160 for value in values[2:])
    ):
        raise ValueError("error_cursor is invalid")
    return (values[0], float(values[1]), *values[2:])



def _bound_telemetry_report(report: dict[str, Any]) -> dict[str, Any]:
    """Keep telemetry report JSON below the public response budget."""
    truncated: list[str] = []
    encoded = json_dumps(report).encode("utf-8")
    for field in _REPORT_TRIMMABLE_LISTS:
        values = report.get(field)
        if not isinstance(values, list):
            continue
        while len(encoded) > _MAX_TELEMETRY_REPORT_BYTES and values:
            del values[max(0, len(values) // 2):]
            if field not in truncated:
                truncated.append(field)
            report["response_truncated_fields"] = truncated
            if field == "error_fingerprints":
                page = report.get("error_fingerprints_page")
                if isinstance(page, dict):
                    if "cursor" not in page:
                        next_offset = int(page.get("offset", 0)) + len(values)
                        page["next_offset"] = next_offset if next_offset < int(page.get("total", 0)) else None
                    if "next_cursor" in page:
                        if values:
                            last = values[-1]
                            page["next_cursor"] = _encode_error_page_cursor(
                                int(page.get("snapshot_id", 0)), float(page.get("snapshot_cutoff", 0)), (
                                last.get("fingerprint", ""), last.get("error_type", ""),
                                last.get("component", ""), last.get("operation", ""),
                            ))
                            page["has_more"] = True
                        else:
                            page["next_cursor"] = page.get("cursor") or None
                            page["has_more"] = page["next_cursor"] is not None
            encoded = json_dumps(report).encode("utf-8")
    if len(encoded) > _MAX_TELEMETRY_REPORT_BYTES:
        return {
            "generated_at": report.get("generated_at"),
            "window_days": report.get("window_days"),
            "scope": report.get("scope"),
            "response_truncated": True,
        }
    if truncated:
        report["response_truncated"] = True
    return report
_MAX_DURATION_MS = 86_400_000.0


def _clean_savings_source(value: Any) -> str:
    label = re.sub(r"[^a-z0-9_.-]+", "_", str(value or "").strip().casefold())[:80]
    return label if label in _SAVINGS_SOURCE_ALLOWLIST else ""


def _clean_savings_breakdown(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return ""
    if not isinstance(value, dict):
        return ""
    cleaned: dict[str, int] = {}
    for source, tokens in list(value.items())[:16]:
        label = _clean_savings_source(source)
        if not label:
            continue
        try:
            bounded = max(0, int(tokens or 0))
        except (TypeError, ValueError, OverflowError):
            continue
        if bounded:
            cleaned[label] = bounded
    return json_dumps(cleaned, separators=(",", ":"), sort_keys=True) if cleaned else ""


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(x) for x in values)
    if pct == 0.50 and len(ordered) % 2 == 0:
        middle = len(ordered) // 2
        return round((ordered[middle - 1] + ordered[middle]) / 2, 1)
    idx = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * pct))))
    return round(ordered[idx], 1)


def _tail_latency(rows: list[tuple[Any, ...]], key_name: str) -> list[dict[str, Any]]:
    """Aggregate metadata-only HTTP tail latency without schema changes."""
    groups: dict[str, list[tuple[float, float, float, int]]] = {}
    for key, duration_ms, queue_wait_ms, service_ms, success in rows:
        group = str(key or "uncategorized")[:160]
        groups.setdefault(group, []).append((
            float(duration_ms or 0), float(queue_wait_ms or 0),
            float(service_ms or 0), int(success or 0),
        ))
    result: list[dict[str, Any]] = []
    for key, items in groups.items():
        durations = [item[0] for item in items]
        queue_waits = [item[1] for item in items]
        services = [item[2] for item in items]
        # Legacy rows encode both an unmeasured phase and a measured zero as 0.
        # A percentile across such rows cannot distinguish those two cases.
        queue_complete = all(value > 0 for value in queue_waits)
        service_complete = all(value > 0 for value in services)
        result.append({
            key_name: key, "events": len(items), "failures": sum(1 for item in items if not item[3]),
            "failure_rate": round(sum(1 for item in items if not item[3]) / len(items), 4) if items else 0.0,
            "p50_duration_ms": _percentile(durations, 0.50),
            "p95_duration_ms": _percentile(durations, 0.95),
            "p99_duration_ms": _percentile(durations, 0.99),
            "p95_queue_wait_ms": _percentile(queue_waits, 0.95) if queue_complete else None,
            "p95_service_ms": _percentile(services, 0.95) if service_complete else None,
            "queue_wait_measurement_complete": queue_complete,
            "service_measurement_complete": service_complete,
        })
    return sorted(result, key=lambda item: (-float(item["p99_duration_ms"]), -int(item["events"]), str(item[key_name])))


def _safe_error_message(value: Any, *, error_type_override: str = "") -> str:
    """Return a bounded reason from an allowlist; never persist exception text."""
    typed_reasons = {
        "SchedulerTimeoutError": "model request timed out",
        "MCPSoftTimeoutError": "operation timed out",
        "TimeoutError": "operation timed out",
        "OperationalError": "database operation failed",
        "IntegrityError": "database integrity constraint failed",
        "DatabaseError": "database operation failed",
        "ConnectionError": "connection failed",
        "ConnectionResetError": "connection failed",
        "ConnectionRefusedError": "connection failed",
        "JSONDecodeError": "invalid JSON",
        "FileNotFoundError": "file not found",
        "PermissionError": "permission denied",
        "ValueError": "invalid value or argument",
        "TypeError": "invalid type",
    }
    error_type = error_type_override or (type(value).__name__ if isinstance(value, BaseException) else "Error")
    if isinstance(value, sqlite3.Error) and is_busy_error(value):
        reason = "database busy or locked"
    elif error_type in typed_reasons:
        reason = typed_reasons[error_type]
    elif isinstance(value, TimeoutError):
        reason = "operation timed out"
    elif isinstance(value, ConnectionError):
        reason = "connection failed"
    elif isinstance(value, json.JSONDecodeError):
        reason = "invalid JSON"
    elif isinstance(value, FileNotFoundError):
        reason = "file not found"
    elif isinstance(value, PermissionError):
        reason = "permission denied"
    elif isinstance(value, ValueError):
        reason = "invalid value or argument"
    elif isinstance(value, TypeError):
        reason = "invalid type"
    elif isinstance(value, OSError):
        if value.errno == errno.ENOENT:
            reason = "file not found"
        elif value.errno in {errno.EACCES, errno.EPERM}:
            reason = "permission denied"
        elif value.errno == errno.EEXIST:
            reason = "file already exists"
        elif value.errno == errno.ENOTDIR:
            reason = "path component is not a directory"
        else:
            reason = "operating system failure"
    elif isinstance(value, RuntimeError):
        reason = "operation failed"
    else:
        reason = "unexpected failure"
    safe_type = _safe_error_metadata(error_type, 48) or "Error"
    return f"{safe_type}: {reason}"[:96]


_SAFE_ERROR_CODE_MESSAGES = {
    "gpu_reserved": "GPU admission unavailable",
    "gpu_outcome_unknown": "GPU inference outcome unknown",
    "local_backend_transport": "local backend transport failure",
    "local_model_error": "local model inference failed",
    "model_output_truncated": "model output was truncated",
    "model_request_timeout": "model request timed out",
    "circuit_open": "model circuit open",
    "http_request_failed": "HTTP request failed",
    "http_stream_failed": "HTTP stream failed",
    "embedding_space_rebuild_required": "embedding space rebuild required",
    "embedding_space_recovery_failed": "embedding space recovery failed",
    "embedding_count_mismatch": "embedding count mismatch",
    "embedding_identity_changed": "embedding identity changed",
    "invalid_embedding_vector": "invalid embedding vector",
}


def _error_fingerprint(error_type: str, component: str, operation: str, error_code: str = "") -> str:
    # Fingerprint only sanitized classification labels, never free-form error text.
    labels = (
        _safe_error_metadata(error_type), _safe_error_metadata(component),
        _safe_operation_metadata(operation), _safe_error_metadata(error_code),
    )
    stable = [value.casefold() for value in labels]
    raw = "|".join(stable).encode("utf-8", "replace")
    return hashlib.sha256(raw).hexdigest()[:16]


def _safe_metadata(value: Any, limit: int = _MAX_METADATA_LENGTH, *, preserve_route: bool = False) -> str:
    """Keep labels useful while excluding secrets, absolute paths, and long tokens."""
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"(?i)\bbearer\s+[^\s,;]+", "Bearer [redacted]", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|password|secret|authorization)\s*([=:])\s*[^&\s,;]+",
        r"\1\2[redacted]",
        text,
    )
    if preserve_route:
        canonical_route = text.split("?", 1)[0].split("#", 1)[0]
        if canonical_route in _SAFE_HTTP_ROUTE_LABELS:
            text = canonical_route
        elif canonical_route in _SAFE_TOOL_ACTIONS:
            return canonical_route[:limit]
        elif ":" in canonical_route:
            tool, action = canonical_route.split(":", 1)
            if action in operation_actions(tool):
                return canonical_route[:limit]
            text = "<path>"
        elif "/" in canonical_route:
            tool, action = canonical_route.split("/", 1)
            if action in operation_actions(tool):
                return canonical_route[:limit]
            trace_prefix = "/api/debug-traces/"
            trace_id = canonical_route[len(trace_prefix):] if canonical_route.startswith(trace_prefix) else ""
            if trace_id and "/" not in trace_id:
                text = "/api/debug-traces/{trace_id}"
            else:
                text = "<path>"
    text = _WINDOWS_PATH_RE.sub("<path>", text)
    text = _UNC_PATH_RE.sub("<path>", text)

    def redact_posix(match: re.Match[str]) -> str:
        candidate = match.group(0)
        return candidate if preserve_route and candidate in _SAFE_HTTP_ROUTE_LABELS else "<path>"

    text = _POSIX_PATH_RE.sub(redact_posix, text)

    def redact_posix_file(match: re.Match[str]) -> str:
        candidate = match.group(0)
        if preserve_route and candidate in _SAFE_HTTP_ROUTE_LABELS:
            return candidate
        return "<path>"

    text = _POSIX_FILE_PATH_RE.sub(redact_posix_file, text)
    text = _POSIX_ROOT_PATH_RE.sub(redact_posix_file, text)
    text = _LONG_TOKEN_RE.sub("<token>", text)
    return " ".join(text.split())[:limit]


def _safe_request_id(value: Any, limit: int = 96) -> str:
    """Preserve canonical correlation IDs while redacting other long metadata."""
    raw = str(value or "")
    if _SAFE_REQUEST_ID_RE.fullmatch(raw):
        return raw[:limit]
    return _safe_metadata(raw, limit)


_RETIRED_TENANT_FIELDS = frozenset({"tenant", "tenant_id", "tenant_key", "tenant_scope"})
_TELEMETRY_METADATA_CONTAINERS = frozenset({"context", "metadata", "metrics", "provenance", "scope"})


def _retired_tenant_field(value: Any) -> str:
    seen: set[int] = set()
    inspected = 0

    def inspect_mapping(mapping: dict[str, Any]) -> str:
        nonlocal inspected
        fields = _RETIRED_TENANT_FIELDS.intersection(mapping)
        if fields:
            return f"Retired telemetry field: {sorted(fields)[0]}"
        identity = id(mapping)
        if identity in seen:
            return ""
        seen.add(identity)
        inspected += len(mapping)
        if inspected > 4096:
            return "Telemetry event exceeds the supported field limit."
        # Inspect exactly one direct metadata/control layer. Nested domain values,
        # captured content and arbitrary structured output remain opaque.
        for key, item in mapping.items():
            if isinstance(key, str) and key in _TELEMETRY_METADATA_CONTAINERS and isinstance(item, dict):
                error = inspect_direct_mapping(item)
                if error:
                    return error
        return ""

    def inspect_direct_mapping(mapping: dict[str, Any]) -> str:
        nonlocal inspected
        fields = _RETIRED_TENANT_FIELDS.intersection(mapping)
        if fields:
            return f"Retired telemetry field: {sorted(fields)[0]}"
        identity = id(mapping)
        if identity in seen:
            return ""
        seen.add(identity)
        inspected += len(mapping)
        if inspected > 4096:
            return "Telemetry event exceeds the supported field limit."
        return ""

    if isinstance(value, dict):
        return inspect_mapping(value)
    if isinstance(value, (list, tuple, set)):
        identity = id(value)
        if identity in seen:
            return ""
        seen.add(identity)
        inspected += len(value)
        if inspected > 4096:
            return "Telemetry event exceeds the supported field limit."
        for item in value:
            if isinstance(item, dict):
                error = inspect_mapping(item)
                if error:
                    return error
    return ""


def _safe_error_metadata(value: Any, limit: int = _MAX_METADATA_LENGTH) -> str:
    """Redact sensitive labeled payloads as well as paths in error classifications."""
    text = _safe_metadata(value, limit)
    text = re.sub(r"(?i)/api/[^\s,;\"']+", "<path>", text)
    text = _SENSITIVE_METADATA_VALUE_RE.sub(r"\1\2[redacted]", text)
    return " ".join(text.split())[:limit]


def _safe_operation_metadata(value: Any) -> str:
    """Preserve registered endpoint identities, never arbitrary path-like labels."""
    route = _safe_metadata(value, preserve_route=True)
    if route in _SAFE_HTTP_ROUTE_LABELS or route in _SAFE_TOOL_ACTIONS or (":" in route and all(p in _SAFE_TOOL_ACTIONS or bool(re.fullmatch(r"[a-zA-Z0-9_\-\.]+", p)) for p in route.split(":", 1))):
        return route
    return _safe_error_metadata(value)


def _safe_error_code(error: Any) -> str:
    """Retain only bounded numeric codes; never hash free-form exception attributes."""
    for attribute in ("status_code", "errno", "code"):
        value = getattr(error, attribute, None)
        if type(value) is int and -65_535 <= value <= 65_535:
            return f"{attribute}:{value}"
    return ""


def _bounded_number(value: Any, *, integer: bool = False, maximum: float = _MAX_DURATION_MS) -> int | float:
    try:
        number = max(0.0, min(float(value or 0), maximum))
    except (TypeError, ValueError, OverflowError):
        number = 0.0
    return int(number) if integer else number


def _phase_timing(event: dict[str, Any], name: str) -> tuple[float, int]:
    value = event.get(name)
    measured = (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )
    measured_key = name.removesuffix("_ms") + "_measured"
    if measured_key in event:
        flag = event[measured_key]
        measured = measured and (flag is True or type(flag) is int and flag == 1)
    return _bounded_number(value), int(measured)


def _outcome_flag(event: dict[str, Any], name: str) -> int:
    if name in event and event[name] is not None:
        return 1 if bool(event[name]) else 0
    try:
        status = int(event.get("status_code", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        status = 0
    if name == "retryable":
        if status in {408, 425, 429, 500, 502, 503, 504}:
            return 1
        if status >= 400 or event.get("success", True):
            return 0
        return -1
    if status:
        return 0 if status >= 500 or status == 429 else 1
    return 1 if event.get("success", True) else -1


def _receipt_count(event: dict[str, Any]) -> int:
    for key in ("receipt_count", "validation_receipt_count"):
        if key in event:
            return int(_bounded_number(event.get(key), integer=True, maximum=1000))
    receipts = event.get("receipts")
    if isinstance(receipts, (list, tuple, set)):
        return min(len(receipts), 1000)
    return 1 if event.get("receipt_id") else 0


_LIVE_OMIT_EMPTY = frozenset({
    "bypass_reason", "terminal", "retryable", "receipt_count", "queue_age_ms",
    "wait_count", "wait_duration_ms", "service_ms", "tool_calls", "evidence_count",
    "response_bytes", "component", "operation", "fingerprint", "recovered",
    "preprocessed_hit", "root", "error_type", "error_fingerprint", "model",
    "stage", "task_type", "complexity", "route", "cache_layer", "coalesced",
    "retry_count", "fallback_used", "degraded", "load_duration_ms", "trace_id",
})

_LAYA_DECISION_OPTIONS = {
    category.value: set(options) for category, options in _CATEGORY_OPTIONS.items()
}
_LAYA_DECISION_STATUSES = {"success", "abstain", "skipped", "error"}
_LAYA_REASON_CODES = {
    "EVIDENCE_SUFFICIENT", "INSUFFICIENT_EVIDENCE", "OPTION_UNSUPPORTED", "LOW_SIGNAL",
    "MODEL_UNAVAILABLE", "INVALID_OUTPUT", "TIMEOUT", "OVERLOADED", "DISABLED",
    "DUPLICATE", "CACHE_HIT", "STALE_EVIDENCE",
}
_LAYA_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
def _laya_decision_report(
    rows: list[tuple[Any, ...]],
    eligible_rows: list[tuple[Any, ...]] | None = None,
    *,
    scope: str,
) -> dict[str, Any]:
    mode_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    by_mode = {
        mode: {
            "records": 0,
            "uncalibrated_estimates": 0,
            "counts_by_category": {},
            "counts_by_category_status": {},
            "counts_by_category_scope": {},
            "eligible_by_category": {},
            "baseline_comparison": {"matched": 0, "diverged": 0, "not_comparable": 0},
            "baseline_by_category": {},
            "counts_by_status": {},
            "counts_by_reason_code": {},
            "abstentions": 0,
            "errors": 0,
            "skips": 0,
            "eligible_decisions": 0,
            "latencies": [],
            "inference_latencies": [],
            "queue_waits": [],
            "backends": {},
            "fallback_used": 0,
            "fallback_not_used": 0,
            "fallback_unknown": 0,
            "fallback_reasons": {},
            "coverage": {"available": False, "reason": "eligible_decision_count_not_recorded"},
            "latency_ms": {"available": False, "reason": "runtime_latency_not_recorded"},
            "backend": {"available": False, "reason": "runtime_backend_not_recorded"},
            "fallbacks": {"available": False, "reason": "fallback_outcome_not_recorded"},
        }
        for mode in ("advisory",)
    }
    invalid_records = 0
    truncated = len(rows) > 1000 or len(eligible_rows or []) > 1000
    eligible_counts: dict[str, int] = {}
    eligible_ids: dict[str, tuple[str, str]] = {}
    for (metrics_json,) in (eligible_rows or [])[:1000]:
        try:
            eligible = load_telemetry_json(metrics_json)
            if not isinstance(eligible, dict) or set(eligible) != _LAYA_ELIGIBILITY_FIELDS:
                raise ValueError("invalid stored Laya eligibility")
            mode = eligible["mode"]
            category = eligible["category"]
            if mode != "advisory" or category not in _LAYA_DECISION_OPTIONS:
                raise ValueError("invalid stored Laya eligibility")
            decision_id = eligible["decision_id"]
            if not isinstance(decision_id, str) or not _LAYA_IDENTIFIER.fullmatch(decision_id):
                raise ValueError("invalid stored Laya eligibility")
            identity = (mode, category)
            previous = eligible_ids.get(decision_id)
            if previous is not None:
                if previous != identity:
                    raise ValueError("conflicting stored Laya eligibility")
                continue
            eligible_ids[decision_id] = identity
            eligible_counts[mode] = eligible_counts.get(mode, 0) + 1
            eligible_by_category = by_mode[mode]["eligible_by_category"]
            eligible_by_category[category] = eligible_by_category.get(category, 0) + 1
        except (TypeError, ValueError, json.JSONDecodeError):
            invalid_records += 1
    decision_ids: dict[str, tuple[str, str]] = {}
    for (metrics_json,) in rows[:1000]:
        try:
            metadata = normalize_laya_decision_metadata(load_telemetry_json(metrics_json))
            if not isinstance(metadata, dict) or frozenset(metadata) != _LAYA_DECISION_FIELDS:
                raise ValueError("invalid stored Laya metadata")
            mode = metadata["mode"]
            category = metadata["category"]
            decision_id = metadata["decision_id"]
            status = metadata["status"]
            task_id = metadata["task_id"]
            session_id = metadata["session_id"]
            reason_codes = metadata["reason_codes"]
            if isinstance(reason_codes, str):
                reason_codes = json.loads(reason_codes)
            if mode != "advisory":
                raise ValueError("invalid stored Laya mode")
            if not isinstance(decision_id, str) or not _LAYA_IDENTIFIER.fullmatch(decision_id):
                raise ValueError("invalid stored Laya decision id")
            if task_id is not None and (not isinstance(task_id, str) or not _LAYA_IDENTIFIER.fullmatch(task_id)):
                raise ValueError("invalid stored Laya task id")
            if session_id is not None and (not isinstance(session_id, str) or not _LAYA_IDENTIFIER.fullmatch(session_id)):
                raise ValueError("invalid stored Laya session id")
            if category not in _LAYA_DECISION_OPTIONS or status not in _LAYA_DECISION_STATUSES:
                raise ValueError("invalid stored Laya category or status")
            if (
                not isinstance(reason_codes, list)
                or len(reason_codes) > 8
                or any(not isinstance(code, str) or code not in _LAYA_REASON_CODES for code in reason_codes)
                or len(set(reason_codes)) != len(reason_codes)
            ):
                raise ValueError("invalid stored Laya reason codes")
            for field in ("runtime_latency_ms", "inference_latency_ms", "queue_wait_ms"):
                value = metadata[field]
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(float(value)) or not 0 <= float(value) <= 86_400_000
                ):
                    raise ValueError("invalid stored Laya latency")
            backend = metadata["backend"]
            if backend is not None and (
                not isinstance(backend, str) or not _LAYA_IDENTIFIER.fullmatch(backend)
            ):
                raise ValueError("invalid stored Laya backend")
            fallback_used = metadata["fallback_used"]
            if fallback_used is not None and type(fallback_used) is not bool:
                raise ValueError("invalid stored Laya fallback flag")
            fallback_reason = metadata["fallback_reason"]
            if fallback_reason is not None and (
                not isinstance(fallback_reason, str)
                or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", fallback_reason)
            ):
                raise ValueError("invalid stored Laya fallback reason")
            if (fallback_used is True) != (fallback_reason is not None):
                raise ValueError("inconsistent stored Laya fallback metadata")
            if type(metadata["baseline_available"]) is not bool:
                raise ValueError("invalid stored Laya baseline availability")
            if metadata["baseline_match"] is not None and type(metadata["baseline_match"]) is not bool:
                raise ValueError("invalid stored Laya baseline comparison")
            if metadata["baseline_match"] is not None and not metadata["baseline_available"]:
                raise ValueError("stored Laya baseline comparison has no baseline")
            if metadata["baseline_match"] is not None and (
                status != "success" or not isinstance(metadata["suggestion"], str)
            ):
                raise ValueError("stored Laya baseline comparison has no successful suggestion")
        except (TypeError, ValueError, json.JSONDecodeError):
            invalid_records += 1
            continue
        identity = (mode, category)
        previous = decision_ids.get(decision_id)
        if previous is not None:
            if previous != identity:
                invalid_records += 1
            continue
        decision_ids[decision_id] = identity
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
        mode_summary = by_mode[mode]
        mode_summary["records"] += 1
        mode_summary["uncalibrated_estimates"] += metadata["uncertainty"] == "UNCALIBRATED"
        comparison = mode_summary["baseline_comparison"]
        category_comparison = mode_summary["baseline_by_category"].setdefault(
            category, {"matched": 0, "diverged": 0, "not_comparable": 0}
        )
        comparison_key = (
            "matched" if metadata["baseline_match"] is True else
            "diverged" if metadata["baseline_match"] is False else
            "not_comparable"
        )
        comparison[comparison_key] += 1
        category_comparison[comparison_key] += 1
        mode_categories = mode_summary["counts_by_category"]
        mode_categories[category] = mode_categories.get(category, 0) + 1
        category_statuses = mode_summary["counts_by_category_status"].setdefault(category, {})
        category_statuses[status] = category_statuses.get(status, 0) + 1
        category_scopes = mode_summary["counts_by_category_scope"].setdefault(category, {"request": 0, "task": 0})
        decision_scope = "task" if task_id is not None else "request"
        category_scopes[decision_scope] += 1
        mode_statuses = mode_summary["counts_by_status"]
        mode_statuses[status] = mode_statuses.get(status, 0) + 1
        mode_summary["abstentions"] += status == "abstain"
        mode_summary["errors"] += status == "error"
        mode_summary["skips"] += status == "skipped"
        mode_summary["eligible_decisions"] = eligible_counts.get(mode, 0)
        for field, target in (
            ("runtime_latency_ms", "latencies"),
            ("inference_latency_ms", "inference_latencies"),
            ("queue_wait_ms", "queue_waits"),
        ):
            if metadata[field] is not None:
                mode_summary[target].append(float(metadata[field]))
        if metadata["backend"] is not None:
            backends = mode_summary["backends"]
            backends[metadata["backend"]] = backends.get(metadata["backend"], 0) + 1
        if metadata["fallback_used"] is True:
            mode_summary["fallback_used"] += 1
            reasons = mode_summary["fallback_reasons"]
            reason = metadata["fallback_reason"]
            reasons[reason] = reasons.get(reason, 0) + 1
        elif metadata["fallback_used"] is False:
            mode_summary["fallback_not_used"] += 1
        else:
            mode_summary["fallback_unknown"] += 1
        mode_reasons = mode_summary["counts_by_reason_code"]
        for reason_code in reason_codes:
            mode_reasons[reason_code] = mode_reasons.get(reason_code, 0) + 1
    for mode, mode_summary in by_mode.items():
        eligible = eligible_counts.get(mode, 0)
        mode_summary["eligible_decisions"] = eligible
        recorded_eligible = sum(
            1 for decision_id, identity in decision_ids.items()
            if identity[0] == mode and eligible_ids.get(decision_id) == identity
        )
        if not truncated and eligible > 0:
            mode_summary["coverage"] = {
                "available": True,
                "eligible_decisions": eligible,
                "recorded_decisions": recorded_eligible,
                "rate": round(recorded_eligible / eligible, 4),
            }
        elif truncated:
            mode_summary["coverage"] = {
                "available": False, "reason": "laya_window_truncated",
            }
        elif eligible < mode_summary["records"]:
            mode_summary["coverage"] = {
                "available": False, "reason": "eligible_count_incomplete",
            }
        runtime_values = mode_summary.pop("latencies")
        inference_values = mode_summary.pop("inference_latencies")
        queue_values = mode_summary.pop("queue_waits")
        if runtime_values or inference_values or queue_values:
            mode_summary["latency_ms"] = {
                "available": True,
                "samples": len(runtime_values),
                "mean": round(sum(runtime_values) / len(runtime_values), 2) if runtime_values else None,
                "max": round(max(runtime_values), 2) if runtime_values else None,
                "inference_samples": len(inference_values),
                "inference_mean": round(sum(inference_values) / len(inference_values), 2) if inference_values else None,
                "queue_wait_samples": len(queue_values),
                "queue_wait_mean": round(sum(queue_values) / len(queue_values), 2) if queue_values else None,
            }
        if mode_summary["backends"]:
            mode_summary["backend"] = {"available": True, "counts": dict(sorted(mode_summary["backends"].items()))}
        mode_summary.pop("backends")
        if mode_summary["fallback_used"] + mode_summary["fallback_not_used"]:
            mode_summary["fallbacks"] = {
                "available": True,
                "used": mode_summary["fallback_used"],
                "not_used": mode_summary["fallback_not_used"],
                "unknown": mode_summary["fallback_unknown"],
                "reasons": dict(sorted(mode_summary["fallback_reasons"].items())),
            }
        mode_summary.pop("fallback_used")
        mode_summary.pop("fallback_not_used")
        mode_summary.pop("fallback_unknown")
        mode_summary.pop("fallback_reasons")
        for field in ("counts_by_category", "counts_by_status", "counts_by_reason_code", "eligible_by_category"):
            mode_summary[field] = dict(sorted(mode_summary[field].items()))
        comparison = mode_summary["baseline_comparison"]
        comparable = comparison["matched"] + comparison["diverged"]
        comparison["comparable"] = comparable
        comparison["agreement_rate"] = round(comparison["matched"] / comparable, 4) if comparable else None
        mode_summary["baseline_by_category"] = dict(sorted(mode_summary["baseline_by_category"].items()))
        mode_summary["counts_by_category_status"] = {
            category: dict(sorted(statuses.items()))
            for category, statuses in sorted(mode_summary["counts_by_category_status"].items())
        }
        mode_summary["counts_by_category_scope"] = {
            category: dict(sorted(scopes.items()))
            for category, scopes in sorted(mode_summary["counts_by_category_scope"].items())
        }
    return {
        "available": True,
        "scope": scope,
        "records": sum(status_counts.values()),
        "counts_by_mode": dict(sorted(mode_counts.items())),
        "counts_by_category": dict(sorted(category_counts.items())),
        "counts_by_status": dict(sorted(status_counts.items())),
        "by_mode": by_mode,
        "invalid_records": invalid_records,
        "truncated": truncated,
    }


from .telemetry_aggregates import TelemetryAggregateMixin
from .telemetry_queries import TelemetryQueryMixin
from .telemetry_events import TelemetryEventMixin
from .telemetry_writer import TelemetryWriterMixin


class TelemetryStore(TelemetryAggregateMixin, TelemetryQueryMixin, TelemetryEventMixin, TelemetryWriterMixin):
    """Low-overhead, metadata-only observability store.

    Foreground callers never write SQLite directly. Events are queued and flushed in
    small batches by a daemon writer. Prompts, source text and model output are never
    accepted by the schema. Raw events have bounded retention; compact daily rollups
    are retained longer so real-world tuning data survives pruning.
    """

    _EVENT_COLUMNS = (
        "created_at", "event_type", "agent", "request_id", "trace_id",
        "action", "stage", "task_type", "complexity", "route", "model",
        "cache_hit", "coalesced", "cache_layer", "input_tokens", "cache_read_tokens", "output_tokens",
        "avoided_cloud_tokens", "duration_ms", "queue_wait_ms", "wait_count", "wait_duration_ms", "service_ms",
        "load_duration_ms", "success", "status_code", "degraded", "retry_count",
        "fallback_used", "bypass_reason", "queue_age_ms", "terminal", "retryable", "receipt_count",
        "error_type", "error_fingerprint", "tool_calls",
        "evidence_count", "response_bytes",
        "gross_avoided_cloud_tokens", "gross_input_tokens_avoided", "gross_output_tokens_avoided",
        "agent_protocol_tokens", "tool_request_tokens", "tool_response_tokens", "tool_schema_tokens",
        "local_compute_tokens_avoided",
        "net_cloud_token_delta", "cloud_token_overhead",
        "net_after_schema_token_delta", "schema_adjusted_overhead",
        "savings_source", "input_savings_source", "output_savings_source", "savings_breakdown_json",
        "preprocessed_hit", "root", "db_wait_ms", "exec_ms", "serialization_ms",
        "db_wait_measured", "exec_measured", "serialization_measured",
    )

    def __init__(
        self,
        state_dir: Path,
        enabled: bool = True,
        max_events: int = 100000,
        *,
        retention_days: int = 30,
        rollup_retention_days: int = 365,
        cloud_input_token_cost_usd_per_million: float = 3.0,
        cloud_output_token_cost_usd_per_million: float = 3.0,
        pricing_profile: str = "claude-5-sonnet",
        cloud_cache_read_token_cost_usd_per_million: float = 0.30,
        cloud_cache_write_token_cost_usd_per_million: float = 3.75,
        config: dict[str, Any] | None = None,
        batch_size: int = 64,
        flush_interval_seconds: float = 0.5,
        queue_size: int = 10000,
        live_buffer_size: int = 2500,
        mode: str = "full",
    ):
        self.enabled = bool(enabled)
        self.mode = str(mode or "full").strip().lower()
        if not self.enabled or self.mode == "off":
            self.enabled = False
            self.mode = "off"
        self._minimal_stats = {
            "requests_total": 0,
            "errors_total": 0,
            "tokens_total": 0,
            "input_tokens_total": 0,
            "output_tokens_total": 0,
            "start_time": time.time(),
        }
        self.max_events = max(100, int(max_events))
        self.retention_days = max(1, int(retention_days))
        self.rollup_retention_days = max(self.retention_days, int(rollup_retention_days))
        self.cloud_input_token_cost_usd_per_million = _validate_token_cost_rate(
            "cloud_input_token_cost_usd_per_million", cloud_input_token_cost_usd_per_million
        )
        self.cloud_output_token_cost_usd_per_million = _validate_token_cost_rate(
            "cloud_output_token_cost_usd_per_million", cloud_output_token_cost_usd_per_million
        )
        self.cloud_cache_read_token_cost_usd_per_million = _validate_token_cost_rate(
            "cloud_cache_read_token_cost_usd_per_million", cloud_cache_read_token_cost_usd_per_million
        )
        self.cloud_cache_write_token_cost_usd_per_million = _validate_token_cost_rate(
            "cloud_cache_write_token_cost_usd_per_million", cloud_cache_write_token_cost_usd_per_million
        )
        self.pricing_profile = str(pricing_profile or "claude-5-sonnet")
        self.config = dict(config or {})
        self.batch_size = max(1, min(int(batch_size), 1000))
        self.flush_interval_seconds = max(0.05, float(flush_interval_seconds))
        self.path = state_dir / "telemetry.sqlite3"
        # Persisted telemetry spans restarts. Keep an explicit in-memory boundary
        # so operators can separate current deploy/process behavior from history.
        self.process_started_at = time.time()
        self._process_started_monotonic = time.monotonic()
        self._current_session_id: int | None = None
        self._current_pid: int = os.getpid()
        self._current_version: str = ""
        self._queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=max(100, int(queue_size)))
        self._stop = threading.Event()
        self._stats_lock = threading.Lock()
        self._stats = {
            "queued": 0, "processed": 0, "written": 0, "dropped": 0,
            "writer_errors": 0, "batches": 0,
            "attempted": 0, "accepted": 0,
            "rejected_overflow": 0, "lost_after_acceptance": 0,
        }
        self._live_lock = threading.Lock()
        self._live_seq = 0
        self._live_events: deque[dict[str, Any]] = deque(maxlen=max(100, int(live_buffer_size)))
        self._report_lock = threading.Lock()
        self._report_cache: dict[tuple[int, str], dict[str, Any]] = {}
        self._report_cache_at: dict[tuple[int, str], float] = {}
        self._summary_cache_lock = threading.Lock()
        self._summary_cache: dict[Any, dict[str, Any]] = {}
        self._thread: threading.Thread | None = None
        state_dir.mkdir(parents=True, exist_ok=True)
        if self.enabled:
            if self.mode != "minimal":
                self._init_db_with_recovery()
                self._thread = threading.Thread(target=self._writer_loop, name="local-ai-telemetry", daemon=True)
                self._thread.start()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=5.0)

    def _init_db_with_recovery(self) -> None:
        self._reject_retired_schema()
        if self.path.exists() and not self._schema_is_current():
            raise RuntimeError(
                "telemetry schema is unsupported; explicit offline conversion required; database preserved"
            )
        try:
            self._init_db()
            with closing(self._connect()) as con:
                if not quick_sanity_check(con):
                    raise sqlite3.DatabaseError("telemetry sanity check failed")
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(
                "telemetry database could not be opened safely; database preserved"
            ) from exc

    def _reject_retired_schema(self) -> None:
        """Refuse tenant-shaped durable data before any WAL, DDL, or recovery writes."""
        if not self.path.exists():
            return
        uri = f"{self.path.as_uri()}?mode=ro"
        deadline = time.monotonic() + 10.0
        interrupted = False

        def stop_long_scan() -> int:
            nonlocal interrupted
            if time.monotonic() >= deadline:
                interrupted = True
                return 1
            return 0

        try:
            with closing(connect_sqlite(uri, uri=True, timeout_seconds=1.0, read_only=True)) as con:
                con.set_progress_handler(stop_long_scan, 5000)
                tables = {
                    str(row[0]) for row in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
                for table in tables:
                    quoted_table = '"' + table.replace('"', '""') + '"'
                    columns = {str(row[1]) for row in con.execute(f"PRAGMA table_info({quoted_table})")}
                    if _RETIRED_TENANT_FIELDS.intersection(columns):
                        raise RuntimeError(
                            "telemetry contains retired tenant schema; explicit offline conversion required; database preserved"
                        )
                    # Snapshot metrics are the supported structured telemetry envelope.
                    # Opaque event/model/debug payloads are not interpreted as scope.
                    structured = columns.intersection({"metrics_json"})
                    for column in structured:
                        quoted_column = '"' + column.replace('"', '""') + '"'
                        rows = con.execute(f"SELECT substr({quoted_column},1,1048577) FROM {quoted_table} LIMIT 500001")
                        for row_number, (raw,) in enumerate(rows, 1):
                            if row_number > 500000:
                                raise RuntimeError(
                                    "telemetry structured-record preflight exceeded its bound; explicit offline conversion required; database preserved"
                                )
                            if not isinstance(raw, str):
                                continue
                            if len(raw) > 1048576:
                                raise RuntimeError(
                                    "telemetry structured-record preflight exceeded its bound; explicit offline conversion required; database preserved"
                                )
                            try:
                                value = json.loads(raw)
                            except (TypeError, ValueError):
                                continue
                            if _retired_tenant_field(value):
                                raise RuntimeError(
                                    "telemetry contains retired tenant records; explicit offline conversion required; database preserved"
                                )
        except RuntimeError:
            raise
        except sqlite3.DatabaseError as exc:
            if interrupted:
                raise RuntimeError(
                    "telemetry schema preflight exceeded its time bound; database preserved"
                ) from exc
            # Preserve existing recovery behavior for unrelated corrupt databases.
            return

    def _schema_is_current(self) -> bool:
        if not self.path.exists():
            return True
        expected_tables = {"events", "errors", "snapshots", "daily_rollups", "process_sessions"}
        expected_columns = {
            "events": {"id", *self._EVENT_COLUMNS},
            "errors": {
                "id", "created_at", "request_id", "agent", "component",
                "operation", "error_type", "fingerprint", "safe_message", "retryable", "recovered",
            },
            "snapshots": {"id", "created_at", "name", "metrics_json"},
            "daily_rollups": {
                "day", "event_type", "action", "agent", "model", "cache_layer", "success",
                "events", "duration_ms", "queue_wait_ms", "input_tokens", "cache_read_tokens", "output_tokens",
                "avoided_cloud_tokens", "cache_hits", "fallback_count", "degraded_count",
                "gross_avoided_cloud_tokens", "gross_input_tokens_avoided", "gross_output_tokens_avoided",
                "agent_protocol_tokens", "tool_schema_tokens", "local_compute_tokens_avoided",
                "tool_request_tokens", "tool_response_tokens", "net_cloud_token_delta",
                "cloud_token_overhead", "net_after_schema_token_delta", "schema_adjusted_overhead",
            },
            "process_sessions": {
                "id", "pid", "version", "started_at", "stopped_at", "last_heartbeat", "exit_clean",
            },
        }
        try:
            with closing(connect_sqlite(self.path, timeout_seconds=1.0, read_only=True)) as con:
                tables = {
                    str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    if not str(row[0]).startswith("sqlite_")
                }
                if not expected_tables.issubset(tables):
                    return False
                for table, expected in expected_columns.items():
                    actual = {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}
                    if not expected.issubset(actual):
                        return False
                return True
        except sqlite3.DatabaseError:
            return False

    def _init_db(self) -> None:
        with closing(self._connect()) as con:
            initialize_wal(con)
            con.execute(
                """CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    action TEXT NOT NULL DEFAULT 'unknown',
                    model TEXT,
                    cache_hit INTEGER NOT NULL DEFAULT 0,
                    coalesced INTEGER NOT NULL DEFAULT 0,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    avoided_cloud_tokens INTEGER NOT NULL DEFAULT 0,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    success INTEGER NOT NULL DEFAULT 1,
                    cache_layer TEXT NOT NULL DEFAULT '',
                    load_duration_ms REAL NOT NULL DEFAULT 0,
                    event_type TEXT NOT NULL DEFAULT 'inference',
                    agent TEXT NOT NULL DEFAULT '',
                    request_id TEXT NOT NULL DEFAULT '',
                    trace_id TEXT NOT NULL DEFAULT '',
                    stage TEXT NOT NULL DEFAULT '',
                    task_type TEXT NOT NULL DEFAULT '',
                    complexity TEXT NOT NULL DEFAULT '',
                    route TEXT NOT NULL DEFAULT '',
                    queue_wait_ms REAL NOT NULL DEFAULT 0,
                    queue_age_ms REAL NOT NULL DEFAULT 0,
                    wait_count INTEGER NOT NULL DEFAULT 0,
                    wait_duration_ms REAL NOT NULL DEFAULT 0,
                    service_ms REAL NOT NULL DEFAULT 0,
                    status_code INTEGER NOT NULL DEFAULT 0,
                    degraded INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    fallback_used INTEGER NOT NULL DEFAULT 0,
                    bypass_reason TEXT NOT NULL DEFAULT '',
                    terminal INTEGER NOT NULL DEFAULT -1,
                    retryable INTEGER NOT NULL DEFAULT -1,
                    receipt_count INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT NOT NULL DEFAULT '',
                    error_fingerprint TEXT NOT NULL DEFAULT '',
                    tool_calls INTEGER NOT NULL DEFAULT 0,
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    response_bytes INTEGER NOT NULL DEFAULT 0,
                    gross_avoided_cloud_tokens INTEGER NOT NULL DEFAULT 0,
                    gross_input_tokens_avoided INTEGER NOT NULL DEFAULT 0,
                    gross_output_tokens_avoided INTEGER NOT NULL DEFAULT 0,
                    agent_protocol_tokens INTEGER NOT NULL DEFAULT 0,
                    tool_request_tokens INTEGER NOT NULL DEFAULT 0,
                    tool_response_tokens INTEGER NOT NULL DEFAULT 0,
                    tool_schema_tokens INTEGER NOT NULL DEFAULT 0,
                    local_compute_tokens_avoided INTEGER NOT NULL DEFAULT 0,
                    net_cloud_token_delta INTEGER NOT NULL DEFAULT 0,
                    cloud_token_overhead INTEGER NOT NULL DEFAULT 0,
                    net_after_schema_token_delta INTEGER NOT NULL DEFAULT 0,
                    schema_adjusted_overhead INTEGER NOT NULL DEFAULT 0,
                    savings_source TEXT NOT NULL DEFAULT '',
                    input_savings_source TEXT NOT NULL DEFAULT '',
                    output_savings_source TEXT NOT NULL DEFAULT '',
                    savings_breakdown_json TEXT NOT NULL DEFAULT '',
                    preprocessed_hit INTEGER NOT NULL DEFAULT 0,
                    root TEXT NOT NULL DEFAULT '',
                    db_wait_ms REAL NOT NULL DEFAULT 0,
                    exec_ms REAL NOT NULL DEFAULT 0,
                    serialization_ms REAL NOT NULL DEFAULT 0,
                    db_wait_measured INTEGER NOT NULL DEFAULT 0,
                    exec_measured INTEGER NOT NULL DEFAULT 0,
                    serialization_measured INTEGER NOT NULL DEFAULT 0
                )"""
            )
            con.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
                CREATE INDEX IF NOT EXISTS idx_events_type_created ON events(event_type, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_action_created ON events(action, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_error ON events(error_fingerprint, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_model ON events(model, created_at);
                CREATE TABLE IF NOT EXISTS process_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pid INTEGER NOT NULL,
                    version TEXT NOT NULL DEFAULT '',
                    started_at REAL NOT NULL,
                    stopped_at REAL,
                    last_heartbeat REAL NOT NULL,
                    exit_clean INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_process_sessions_started ON process_sessions(started_at);
                CREATE TABLE IF NOT EXISTS errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    agent TEXT NOT NULL DEFAULT '',
                    component TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    safe_message TEXT NOT NULL,
                    retryable INTEGER NOT NULL DEFAULT 0,
                    recovered INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_errors_fp_created ON errors(fingerprint, created_at);
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    name TEXT NOT NULL,
                    metrics_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_name_created ON snapshots(name, created_at);
                CREATE TABLE IF NOT EXISTS daily_rollups (
                    day TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    model TEXT NOT NULL,
                    cache_layer TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    events INTEGER NOT NULL DEFAULT 0,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    queue_wait_ms REAL NOT NULL DEFAULT 0,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    avoided_cloud_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_hits INTEGER NOT NULL DEFAULT 0,
                    fallback_count INTEGER NOT NULL DEFAULT 0,
                    degraded_count INTEGER NOT NULL DEFAULT 0,
                    gross_avoided_cloud_tokens INTEGER NOT NULL DEFAULT 0,
                    gross_input_tokens_avoided INTEGER NOT NULL DEFAULT 0,
                    gross_output_tokens_avoided INTEGER NOT NULL DEFAULT 0,
                    agent_protocol_tokens INTEGER NOT NULL DEFAULT 0,
                    tool_schema_tokens INTEGER NOT NULL DEFAULT 0,
                    local_compute_tokens_avoided INTEGER NOT NULL DEFAULT 0,
                    tool_request_tokens INTEGER NOT NULL DEFAULT 0,
                    tool_response_tokens INTEGER NOT NULL DEFAULT 0,
                    net_cloud_token_delta INTEGER NOT NULL DEFAULT 0,
                    cloud_token_overhead INTEGER NOT NULL DEFAULT 0,
                    net_after_schema_token_delta INTEGER NOT NULL DEFAULT 0,
                    schema_adjusted_overhead INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(day,event_type,action,agent,model,cache_layer,success)
                );
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_savings_created ON events(event_type, savings_source, created_at)")
            con.commit()

















































    def reset(self) -> bool:
        """Purge all recorded events, rollups, snapshots, errors, and reset in-memory caches."""
        if not self.enabled:
            return False
        try:
            self.flush(0.5)
            with self._stats_lock:
                self._stats = {
                    "queued": 0, "processed": 0, "written": 0, "dropped": 0,
                    "writer_errors": 0, "batches": 0,
                    "attempted": 0, "accepted": 0,
                    "rejected_overflow": 0, "lost_after_acceptance": 0,
                }
            with self._live_lock:
                self._live_events.clear()
                self._live_seq = 0
            with self._report_lock:
                self._report_cache.clear()
                self._report_cache_at.clear()
            with self._summary_cache_lock:
                self._summary_cache.clear()
            self.process_started_at = time.time()
            self._process_started_monotonic = time.monotonic()
            with closing(self._connect()) as con, con:
                con.execute("DELETE FROM events")
                con.execute("DELETE FROM daily_rollups")
                con.execute("DELETE FROM errors")
                con.execute("DELETE FROM snapshots")
                con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            return True
        except Exception as exc:
            logger.warning("telemetry store reset failed: %s", exc)
            return False

    def close(self) -> None:
        if not self.enabled:
            return
        self.session_stop()
        self._stop.set()
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=max(1.0, self.flush_interval_seconds * 4))
