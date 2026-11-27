from __future__ import annotations

# Keep route dependencies exported here for dynamic monkeypatch lookup in http_routes_api.

from .repository_scope import (
    RepositoryScopeError, authorized_repository_root, reject_retired_tenancy_fields,  # noqa: F401
)

import hashlib
import hmac
import ipaddress
import inspect as inspect
import io  # noqa: F401
import json
import math
import os
import sys
import queue  # noqa: F401
import re
import select  # noqa: F401
import socket
import sqlite3  # noqa: F401
import uuid  # noqa: F401
import time
import traceback
import threading
from datetime import datetime as datetime, timezone as timezone
from collections import deque
from contextlib import nullcontext as nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
import urllib.request
from urllib.parse import parse_qs, urlparse  # noqa: F401

from . import __version__
if __name__ == "__main__":
    sys.modules[f"{__package__}.http_server"] = sys.modules[__name__]
from .app import LocalAIApp
from .features import FeatureSet  # noqa: F401
from .http_transport import RequestHeadReader  # noqa: F401
from .http_headers import apply_cors_headers  # noqa: F401
from .operation_contracts import capability_feature_gate, capability_minimum_profile, capability_profile_available
from .http_event_cursor import (
    MAX_EVENT_SEQUENCE,  # noqa: F401
    encode_agent_event_cursor as _encode_agent_event_cursor,  # noqa: F401
    parse_agent_event_cursor as _parse_agent_event_cursor,  # noqa: F401
)
from .http_transcription import (
    _ActiveTranscriptionRegistry,
    _invoke_cancellable_request,  # noqa: F401
    _is_client_disconnect,  # noqa: F401
    _start_disconnect_monitor,  # noqa: F401
)

_STATUS_DEPENDENCY_TIMEOUT_SECONDS = 0.25
_STATUS_TOTAL_BUDGET_SECONDS = 1.0


def _api_result_http_response(result: Any) -> tuple[int, Any]:
    if not isinstance(result, dict) or result.get("success") is not False:
        return 200, result
    body = dict(result)
    retryable = body.get("retryable") is True
    result_status = body.get("status_code")
    if isinstance(result_status, int) and not isinstance(result_status, bool) and 400 <= result_status <= 599:
        status = result_status
    elif body.get("error_code") == "model_output_truncated":
        status = 422
    elif body.get("error_code") == "local_model_error":
        status = 502
    elif body.get("error_code") == "gpu_reserved":
        status = 503
    elif body.get("error_code") == "gpu_outcome_unknown":
        status = 409
    elif body.get("error_code") in {
        "index_stale",
        "gpu_lease_conflict",
    }:
        status = 409
    elif body.get("error_code") == "invalid_project_configuration":
        status = 400
    elif body.get("error_code") == "migration_database_missing":
        status = 404
    elif body.get("error_code") == "migration_database_path_invalid":
        status = 400
    elif body.get("error_code") == "package_manifest_unavailable":
        status = 422
    elif body.get("error_code") in {
        "review_diff_fragment_exceeds_budget",
        "review_prompt_budget_too_small",
        "review_diff_segment_limit_exceeded",
    }:
        status = 422
    else:
        status = 503 if retryable else (409 if body.get("operation_not_started") is True else 500)
    body.setdefault("status_code", status)
    body.setdefault("retryable", retryable)
    body.setdefault("terminal", not retryable)
    return status, body


def _recovery_claim_failure_response(
    recovery: Any,
    error: Exception | None = None,
    *,
    invalid_claim: bool = False,
) -> dict[str, Any]:
    base = {
        "success": False,
        "status_code": 503,
        "outcome_unknown": False,
    }
    if invalid_claim:
        return {
            **base,
            "error_code": "request_journal_invalid",
            "error": "request was not dispatched because recovery journal returned an invalid claim",
            "terminal": True,
            "retryable": False,
        }
    if (
        getattr(recovery, "_journal_unavailable", False) is not True
        and error is not None
        and is_busy_error(error)
    ):
        return {
            **base,
            "error_code": "request_journal_busy",
            "error": "request was not dispatched because recovery journal is temporarily busy",
            "terminal": False,
            "retryable": True,
            "retry_after_seconds": 1,
        }
    if getattr(recovery, "_journal_unavailable", False) is True:
        error_code = "request_journal_unavailable"
        detail = "request was not dispatched because recovery journal is unavailable"
    else:
        error_code = "request_journal_error"
        detail = "request was not dispatched because recovery journal failed"
    return {
        **base,
        "error_code": error_code,
        "error": detail,
        "terminal": True,
        "retryable": False,
    }


def _status_dependency(callback, fallback, *, key, lock, inflight, slots, timeout_seconds=None):
    timeout = _STATUS_DEPENDENCY_TIMEOUT_SECONDS if timeout_seconds is None else max(0.0, float(timeout_seconds))
    if timeout <= 0:
        return fallback, False
    executor = getattr(APP, "_status_dependency_executor", None)
    if executor is not None:
        try:
            from .app import _status_dependency as app_status_dep
            return app_status_dep(
                callback, fallback, key=key, lock=lock, inflight=inflight,
                slots=slots, executor=executor, deadline=time.monotonic() + timeout,
            )
        except Exception:
            pass
    if not hasattr(slots, "acquire") or not slots.acquire(blocking=False):
        return fallback, False
    outcome = {}
    completed = threading.Event()

    def run() -> None:
        try:
            outcome["value"] = callback()
        except Exception as exc:
            outcome["error"] = exc
        finally:
            with lock:
                if inflight.get(key) is outcome:
                    del inflight[key]
            try:
                slots.release()
            finally:
                completed.set()

    with lock:
        inflight[key] = outcome
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    if not completed.wait(timeout=timeout):
        return fallback, False
    if "error" in outcome:
        return fallback, False
    return outcome.get("value", fallback), True
from .scheduler import ModelUnavailableError, QueueFullError  # noqa: F401
from .debug_traces import DebugTraceObserver, _normalize_trace_content, redact_trace_export  # noqa: F401
from .agent_diagnostics import detailed_diagnostics_enabled, agent_diagnostics_enabled, project_agent_response, project_pubsub_poll_response, project_wait_event_response, project_status_response, project_aggregate_response  # noqa: F401
from .agent_surface import diagnostic_http_operation, diagnostics_disabled_response  # noqa: F401
from .response_budget import _reconcile_existing_budget  # noqa: F401
from .trace_context import reset_context, reset_observer, set_context, set_observer  # noqa: F401
from .http_route_registry import select_get_handler, select_http_routes, select_post_handler  # noqa: F401
from .http_post_repository_analysis import handle_post_repository_analysis, handle_post_plan  # noqa: F401
from .config import ConfigError as ConfigError, deep_merge as deep_merge, load_config, save_runtime_overrides as save_runtime_overrides, validate_config as validate_config
from .delivery import decide_delivery  # noqa: F401
from .resilience import RecoveryJournal  # noqa: F401
from .sqlite_support import connect_sqlite, is_busy_error  # noqa: F401
from .search_modes import default_agent_search_mode, repository_search_timeout, search_execution_stopped  # noqa: F401
from .agent_identity import AgentScope, ScopeContext  # noqa: F401
from .project_config import resolve_project_context
from .state_paths import configured_state_dir
from .agent_tasks import (
    CheckpointResponseBudgetError,  # noqa: F401
    CompletionGateError,  # noqa: F401
    GoalContract,
    TaskIdempotencyConflictError,  # noqa: F401
    TaskPage,  # noqa: F401
    TaskWorktreeError,  # noqa: F401
    TaskCheckpoint,  # noqa: F401
    TaskStatus,  # noqa: F401
)
from .agent_memory import ApprovalRequiredError, MAX_MEMORY_QUERY_LIMIT, MemoryKind, MemoryRecord, MemoryStatus  # noqa: F401
from .agent_incidents import IncidentFingerprint, ToolOutcome, _incident_scope_key as _incident_scope_key  # noqa: F401
from .agent_verification import VerificationReceipt  # noqa: F401
from .task_context import build_context_request, compose_task_context  # noqa: F401
from .agent_learning import ImprovementCandidate, SLOObservation  # noqa: F401
from .operation_contracts import normalize_transport_error  # noqa: F401
from .search_pagination import (
    MAX_HTTP_PAGE_RESPONSE_BYTES,  # noqa: F401
    MAX_PAGE_SIZE,  # noqa: F401
    MAX_PAGE_WINDOW,  # noqa: F401
    pagination_bounds_error,  # noqa: F401
)
from .json_utils import dumps as json_dumps, dumps_bytes as json_dumps_bytes, loads as json_loads  # noqa: F401
from .agent_event_pages import (
    AGENT_EVENT_PAGE_MAX_BYTES,
    AGENT_EVENT_PAGE_MAX_LIMIT,  # noqa: F401
    _bound_agent_event_page as _bound_agent_event_page_impl,
    _minimum_json_bytes,
)
from .process_utils import process_identity, process_owner_state, process_parent_pid

from .browser_bridge import (
    abandon_staged_capture,  # noqa: F401
    capture_failure,  # noqa: F401
    capture_to_artifacts,  # noqa: F401
    commit_staged_capture,  # noqa: F401
    issue_capture_capability,  # noqa: F401
    origin_allowed,  # noqa: F401
    stage_capture,  # noqa: F401
    validate_capture_request,  # noqa: F401
)
from .operational_mode import (
    load_operational_mode as load_operational_mode,
    set_operational_mode as set_operational_mode,
)


os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

APP: LocalAIApp | None = None
_MODE_UNLOAD_STATUS_LOCK = threading.Lock()
_DB_QUERY_TIMEOUT_SECONDS = 0.5
_DB_QUERY_MAX_ROWS = 100
_DB_QUERY_MAX_RESPONSE_BYTES = 256 * 1024
_DB_QUERY_MAX_SQL_BYTES = 8192
_MODEL_PULL_TIMEOUT_SECONDS = 120.0


_MODEL_PULL_MAX_RESPONSE_BYTES = 1024 * 1024
_HTTP_MAX_JSON_BODY_BYTES = 64 * 1024 * 1024
_HTTP_MAX_BODY_SECONDS = 60.0


def _trusted_project_context(root: str) -> Any | None:
    """Resolve coordination identity from server project config, never request data."""
    root = str(root or "").strip()
    if not root or APP is None:
        return None
    state_store = getattr(APP, "agent_state", None)
    if state_store is None:
        return None
    try:
        from .project_config import resolve_project_context

        return resolve_project_context(root, Path(state_store.db_path).parent)
    except Exception:
        # Project identity is optional: resolution failure keeps the physical
        # worktree local and cannot grant cross-worktree access.
        return None


def _bind_repository_memory_provenance(
    provenance: Mapping[str, Any], *, root: str, project_context: Any | None,
) -> dict[str, Any]:
    """Use the server-resolved project identity; missing identity never falls back."""
    if "tenant" in provenance or "tenant_key" in provenance:
        raise ValueError("retired memory provenance field")
    physical_root = getattr(project_context, "root", None)
    if isinstance(physical_root, Path):
        physical_root = str(physical_root)
    coordination_id = getattr(project_context, "coordination_id", None)
    if not isinstance(coordination_id, str) or not coordination_id or coordination_id != coordination_id.strip() or "\x00" in coordination_id:
        raise ValueError("repository memory requires resolved project coordination identity")
    if _strict_root_path(physical_root) != _strict_root_path(root):
        raise ValueError("resolved project root does not match memory root")
    result = dict(provenance)
    result.update(root=str(_strict_root_path(physical_root)), repository_id=coordination_id)
    return result

def _lease_coordination_id(root: str) -> str | None:
    """Resolve lease namespace from server-side project identity only."""
    if APP is None:
        return None
    try:
        state_dir = configured_state_dir(APP.config)
        return resolve_project_context(root, state_dir).coordination_id
    except Exception:
        return None


def _parse_include_body(value: Any, *, query: bool = False) -> bool | None:
    if query:
        if value is None:
            return False
        if value == "true":
            return True
        if value == "false":
            return False
    elif type(value) is bool:
        return value
    return None




_ACTIVE_TRANSCRIPTIONS = _ActiveTranscriptionRegistry()
_ACTIVE_CONVERSATIONS = _ActiveTranscriptionRegistry()
_ACTIVE_DELEGATES = _ActiveTranscriptionRegistry()
_GAMING_DRAIN_TIMEOUT_SECONDS = 4.5




# Monitoring/control reads must never appear as workload. Keep this hard safety set
# independent of user config so a dashboard refresh cannot create immortal active jobs.
MONITOR_PATHS = {
    "/health", "/ready", "/api/live", "/api/live/status",
    "/api/status", "/api/mode", "/api/capabilities", "/api/metrics", "/api/adoption",
    "/api/telemetry/report", "/api/telemetry/tool-accounting", "/api/telemetry/timeline", "/api/repair-priorities",
    "/api/telemetry/endpoint-stats",
    "/api/audit/tail",
    "/api/config", "/api/logs/tail", "/api/hardware/system", "/api/hardware/gpu",
    "/api/mode", "/api/admin/mode",
    "/api/debug-traces",
}
READINESS_COMPONENTS = (
    "artifacts",
    "telemetry",
    "agent_state",
    "agent_tasks",
    "agent_memory",
    "agent_incidents",
    "agent_verification",
    "agent_blackboard",
    "agent_context",
    "agent_learning",
    "async_jobs",
)











def _is_loopback_peer(handler: Any) -> bool:
    """Trust the socket peer address, never a client-controlled Host header."""
    peer = getattr(handler, "client_address", None)
    if not isinstance(peer, tuple) or not peer:
        return False
    try:
        address = ipaddress.ip_address(str(peer[0]))
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        return address.is_loopback
    except ValueError:
        return False






def _query_int(query: Mapping[str, list[str]], name: str, default: int) -> int:
    try:
        return int((query.get(name) or [default])[0])
    except (TypeError, ValueError, OverflowError):
        return default






def _in_process_cuda_unload_blockers(app: Any) -> list[str]:
    blockers: list[str] = []
    for name in ("embeddings", "reranker"):
        component = getattr(app, name, None)
        model = getattr(component, "_model", None)
        backend = str(getattr(component, "active_backend", "") or getattr(component, "backend", "")).strip().lower()
        device = str(getattr(component, "active_device", "") or "").strip().lower()
        if model is not None and backend != "ollama" and device.startswith("cuda"):
            blockers.append(name)
    return blockers


def _public_gaming_unload_status(value: dict[str, Any]) -> dict[str, Any]:
    allowed_states = {"pending", "complete", "partial", "deferred", "failed", "unknown", "not_applicable"}

    def names(key: str) -> list[str] | None:
        rows = value.get(key)
        if not isinstance(rows, list):
            return None
        return [str(row)[:160] for row in rows[:64]]

    state = str(value.get("state", "unknown"))
    status = {
        "success": value.get("success") is True,
        "state": state if state in allowed_states else "unknown",
        "reason": str(value.get("reason", ""))[:80],
        "unloaded": names("unloaded") or [],
        "remaining": names("remaining"),
    }
    blockers = names("unsupported_in_process_cuda")
    if blockers:
        status["unsupported_in_process_cuda"] = blockers
    detached = names("in_process_cuda_detached")
    if detached:
        status["in_process_cuda_detached"] = detached
    failed_value = value.get("in_process_cuda_release_failed")
    if isinstance(failed_value, dict):
        failed = {
            name: str(failed_value[name])[:80]
            for name in ("embeddings", "reranker")
            if name in failed_value
        }
        if failed:
            status["in_process_cuda_release_failed"] = failed
    return status



HTTP_MODE_OPERATOR_GET_PATHS = frozenset({
    "/api/adoption", "/api/audit/tail", "/api/capabilities", "/api/config",
    "/api/debug-traces", "/api/hardware/gpu", "/api/hardware/system",
    "/api/live/status", "/api/logs/tail", "/api/metrics", "/api/mode",
    "/api/models/manage", "/api/preprocess/status", "/api/status",
    "/api/telemetry/report", "/api/telemetry/timeline", "/api/repair-priorities",
    "/api/telemetry/endpoint-stats",
})
HTTP_MODE_GAMING_READ_GET_PATHS = frozenset({
    "/api/agent-state/blackboard", "/api/agent-state/events",
    "/api/agent-state/memory", "/api/agent-state/swarm",
    "/api/agent-state/tasks", "/api/db/query", "/api/rag/workspaces",
    "/api/repo/files", "/api/repo/topology",
})
HTTP_MODE_OPERATOR_POST_PATHS = frozenset({"/api/admin/mode"})
HTTP_MODE_ACTION_POST_PATHS = frozenset({
    "/api/async-jobs",
    "/api/work-orders",
    "/api/speculative-lint",
})


def _http_admin_action(method: str, path: str) -> str | None:
    method = str(method).upper()
    path = urlparse(str(path)).path
    if method == "GET":
        if path == "/api/debug-traces" or path.startswith("/api/debug-traces/"):
            return "trace.read"
        return {
            "/api/adoption": "telemetry.read",
            "/api/audit/tail": "audit.read",
            "/api/capabilities": "status.read",
            "/api/config": "config.read",
            "/api/db/query": "db.query",
            "/api/hardware/gpu": "hardware.read",
            "/api/hardware/system": "hardware.read",
            "/api/live": "telemetry.read",
            "/api/live/status": "status.read",
            "/api/logs/tail": "logs.read",
            "/api/metrics": "telemetry.read",
            "/api/models/manage": "model.manage",
            "/api/mode": "status.read",
            "/api/status": "status.read",
            "/api/updates": "status.read",
            "/api/repair-priorities": "telemetry.read",
            "/api/telemetry/report": "telemetry.read",
            "/api/telemetry/timeline": "telemetry.read",
        }.get(path)
    if method == "POST":
        if path == "/api/debug-traces/purge":
            return "trace.manage"
        if path.startswith("/api/maintenance/"):
            return "maintenance"
        return {
            "/api/admin/mode": "mode.control",
            "/api/updates": "maintenance",
            "/api/bundle/import": "bundle.import",
            "/api/config": "config.write",
            "/api/config/update": "config.write",
            "/api/db/query": "db.query",
            "/api/models/manage": "model.manage",
        }.get(path)
    return None


def _ollama_runner_present(config: dict[str, Any]) -> bool:
    ollama = config.get("ollama", {})
    ollama_url = ollama.get("url", "http://localhost:11434") if isinstance(ollama, dict) else None
    if not isinstance(ollama_url, str) or not ollama_url.strip():
        raise ValueError("Ollama URL unavailable")
    req = urllib.request.Request(f"{ollama_url.rstrip('/')}/api/ps")
    with urllib.request.urlopen(req, timeout=2) as response:
        body = response.read(262145)
    if len(body) > 262144:
        raise ValueError("Ollama runner response too large")
    value = json.loads(body.decode("utf-8"))
    models = value.get("models") if isinstance(value, dict) else None
    if not isinstance(models, list):
        raise ValueError("Ollama runner state unavailable")
    return bool(models)


def _apply_live_debug_trace_toggle(app: Any, settings: dict[str, Any]) -> bool:
    if "telemetry.mode" in settings:
        enabled = (str(settings["telemetry.mode"]).strip().lower() == "full")
    else:
        return False
    store = getattr(app, "debug_traces", None)
    if store is None:
        return False
    store.enabled = enabled

    # Dashboard status is cached for a short interval. Keep its copy of the
    # live switch coherent so the post-update poll cannot immediately redraw
    # the old value over the server-confirmed setting.
    status_cache = getattr(app, "_live_status_cache", None)
    status_lock = getattr(app, "_live_status_lock", None)
    acquire = getattr(status_lock, "acquire", None)
    release = getattr(status_lock, "release", None)
    if isinstance(status_cache, dict):
        locked = callable(acquire) and callable(release)
        if locked:
            acquire()
        try:
            for entry in status_cache.values():
                if not isinstance(entry, tuple) or len(entry) != 2:
                    continue
                snapshot = entry[1]
                if not isinstance(snapshot, dict):
                    continue
                trace_status = snapshot.get("debug_traces")
                if isinstance(trace_status, dict):
                    snapshot["debug_traces"] = {**trace_status, "enabled": enabled}
                telemetry_status = snapshot.get("telemetry")
                if isinstance(telemetry_status, dict):
                    snapshot["telemetry"] = {**telemetry_status, "mode": "full" if enabled else "minimal"}
        finally:
            if locked:
                release()
    return True


def _config_update_failure_payload(exc: Exception) -> dict[str, Any]:
    return {
        "success": False,
        "error": "configuration update rejected",
        "error_code": "config_update_rejected",
        "error_type": type(exc).__name__,
        "terminal": True,
        "retryable": False,
    }


def _token_matches(supplied: str, expected: str) -> bool:
    if not expected:
        return False
    try:
        return hmac.compare_digest(str(supplied), expected)
    except (TypeError, ValueError):
        return False


def _redact_config_secrets(config: dict[str, Any]) -> dict[str, Any]:
    security_settings = config.get("security")
    if isinstance(security_settings, dict) and "users" in security_settings:
        raise ValueError("security.users was removed; configuration projection requires canonical settings")
    serialized_config = json_dumps(config, default=str)
    config_stamp = hashlib.sha256(serialized_config.encode("utf-8")).hexdigest()
    cached = getattr(_redact_config_secrets, "_cached", None)
    if cached is not None and cached[0] == config_stamp:
        return json.loads(cached[1])
    view = json.loads(serialized_config)
    if "_config_path" in view:
        view["_config_path"] = _safe_config_file_label(view["_config_path"])
    if "_runtime_override_path" in view:
        view["_runtime_override_path"] = _safe_config_file_label(view["_runtime_override_path"])
    _redact_config_secrets._cached = (config_stamp, json_dumps(view, default=str))
    return view


def _safe_config_file_label(value: Any) -> str:
    """Expose only a config filename, never the host filesystem path."""
    try:
        name = Path(str(value or "").replace("\\", "/")).name
    except (OSError, TypeError, ValueError):
        return ""
    return name[:128]
HTTP_MODE_GAMING_READ_POST_PATHS = frozenset({
    "/api/artifact/get", "/api/artifact/list", "/api/db/query",
    "/api/evidence/get", "/api/memory/get", "/api/memory/search",
    "/api/repo/profile",
})
HTTP_MODE_SAFE_METHOD_REJECTIONS = frozenset({
    "/api/maintenance/optimize_db", "/api/maintenance/purge_cache",
    "/api/maintenance/resolve_errors",
})


def _http_mode_action(path: str, payload: Mapping[str, Any] | None = None) -> str:
    if path == "/api/speculative-lint":
        action = str((payload or {}).get("action", "submit")).strip().lower().replace("-", "_")
        return "speculative_lint" if action == "submit" else f"speculative_lint_{action}"
    if path in {"/api/async-jobs", "/api/work-orders"}:
        action_key = "action" if path == "/api/work-orders" else ("job_action" if "job_action" in (payload or {}) else "action")
        return str((payload or {}).get(action_key, "submit")).strip().lower().replace("-", "_")
    if path == "/api/delegate":
        return "delegate"
    return path.removeprefix("/api/").replace("/", "_").replace("-", "_") or "http_request"


def _http_mode_policy(method: str, path: str, payload: Mapping[str, Any] | None = None) -> str:
    if not path.startswith("/api/"):
        return "operator"
    if method == "GET":
        if path in HTTP_MODE_OPERATOR_GET_PATHS or path in HTTP_MODE_SAFE_METHOD_REJECTIONS:
            return "operator"
        return "gaming_read" if path in HTTP_MODE_GAMING_READ_GET_PATHS else "blocked"
    if method != "POST":
        return "blocked"
    if path in HTTP_MODE_OPERATOR_POST_PATHS:
        return "operator"
    if path in {"/api/async-jobs", "/api/work-orders"}:
        action = _http_mode_action(path, payload)
    else:
        action = str((payload or {}).get("action", "")).strip().lower().replace("-", "_")
    if path == "/api/evaluation" and action == "report":
        return "gaming_read"
    if path == "/api/async-jobs" and action in {"status", "wait", "result", "cancel", "evaluation_report"}:
        return "existing_job"
    if path == "/api/work-orders" and action in {"status", "wait", "get", "cancel"}:
        return "existing_job"
    if path == "/api/speculative-lint" and action in {"status", "cancel"}:
        return "existing_job"
    if path == "/api/agent-state/events/delta" and action == "export":
        return "gaming_read"
    if path == "/api/agent-state/tasks" and action in {"get", "list"}:
        return "gaming_read"
    if path == "/api/agent-state/memory" and action in {"get", "list", "search"}:
        return "gaming_read"
    if path == "/api/agent-state/incidents" and action in {"get", "list"}:
        return "gaming_read"
    if path == "/api/agent-state/verification" and action in {"get", "list", "status"}:
        return "gaming_read"
    if path == "/api/agent-state/blackboard" and action in {"get", "list", "read"}:
        return "gaming_read"
    return "gaming_read" if path in HTTP_MODE_GAMING_READ_POST_PATHS else "blocked"


def _http_hardware_capability_error(
    path: str, payload: Mapping[str, Any] | None, config: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Apply the shared hardware ceiling to direct HTTP semantic/write routes."""
    action_by_path = {
        "/api/solve/repo": ("local_ai_repo", "solve"),
        "/api/review/diff": ("local_ai_repo", "review_diff"),
        "/api/delegate/repo": ("local_ai_repo", "delegate"),
        "/api/delegate": ("local_ai_task", "delegate"),
        "/api/reason": ("local_ai_task", "reason"),
        "/api/review": ("local_ai_task", "review"),
        "/api/second-opinion": ("local_ai_task", "second_opinion"),
        "/api/conversations/continue": ("local_ai_task", "continue"),
        "/api/delegate/batch": ("local_ai_task", "batch"),
        "/api/task/vision": ("local_ai_task", "vision"),
        "/api/complete": ("local_ai_task", "complete_code"),
        "/api/task/scaffold": ("local_ai_task", "scaffold"),
        "/api/task/speculative_draft": ("local_ai_task", "speculative_draft"),
        "/api/task/automation": ("local_ai_task", "automation"),
    }
    capability = action_by_path.get(path)
    if path == "/api/async-jobs" and isinstance(payload, Mapping):
        action = payload.get("action", "submit")
        if action == "submit":
            job_action = payload.get("job_action", "")
            if job_action == "review_diff":
                capability = ("local_ai_repo", "review_diff")
            else:
                capability = ("local_ai_task", job_action if isinstance(job_action, str) and job_action else "submit")
    if path == "/api/work-orders" and isinstance(payload, Mapping):
        if payload.get("action", "submit") == "submit":
            if payload.get("mode") != "bounded":
                return {
                    "success": False, "unsupported": True,
                    "error_code": "bounded_mode_required",
                    "error": "work-order submit requires mode='bounded'",
                    "terminal": True, "retryable": False, "status_code": 400,
                }
            capability = ("local_ai_work", "submit")
    if capability is None:
        return None
    effective = (config or {}).get("_hardware", {})
    hardware = effective if isinstance(effective, Mapping) and "profile" in effective else (config or {}).get("hardware", {})
    profile = hardware.get("profile", "low") if isinstance(hardware, Mapping) else "low"
    minimum = capability_minimum_profile(*capability)
    requirement = f"the {minimum} profile or higher"
    if minimum == "high":
        requirement = "the high or max hardware profile"
    if not capability_profile_available(profile, minimum):
        return {
            "success": False,
            "unsupported": True,
            "status_code": 403,
            "error_code": "hardware_profile_too_low",
            "error": f"{capability[0]} action '{capability[1]}' requires {requirement}",
            "hardware_profile": profile if isinstance(profile, str) else "low",
            "minimum_profile": minimum,
            "terminal": True,
            "retryable": False,
        }
    required_feature = capability_feature_gate(*capability)
    features = (config or {}).get("features", {})
    if required_feature and (not isinstance(features, Mapping) or features.get(required_feature) is not True):
        return {
            "success": False,
            "unsupported": True,
            "status_code": 403,
            "error_code": "capability_feature_disabled",
            "error": f"{capability[0]} action '{capability[1]}' requires features.{required_feature}=true",
            "required_feature": required_feature,
            "terminal": True,
            "retryable": False,
        }
    return None


def _operational_mode_api() -> Any:
    from . import operational_mode
    return operational_mode


def _http_mode_gate_error(
    method: str, path: str, payload: Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    policy = _http_mode_policy(method, path, payload)
    if policy == "operator":
        return None
    action = _http_mode_action(path, payload)
    try:
        api = _operational_mode_api()
        app_cfg = getattr(APP, "config", None)
        async_jobs = getattr(APP, "async_jobs", None)
        jobs_path = getattr(async_jobs, "path", None)
        if jobs_path is not None:
            state_dir = Path(jobs_path).parent
        else:
            state_dir = app_cfg.get("server", {}).get("state_dir", "state") if isinstance(app_cfg, dict) else "state"
        from . import operational_mode as _op_mod
        if globals().get("load_operational_mode") is not _op_mod.load_operational_mode:
            load_fn = globals()["load_operational_mode"]
        else:
            load_fn = getattr(api, "load_operational_mode", _op_mod.load_operational_mode)
        try:
            snapshot = load_fn(state_dir=state_dir)
        except TypeError:
            snapshot = load_fn(state_dir)
        if not snapshot.degraded and snapshot.mode == "active":
            return None
        if method == "POST" and payload is None and path in HTTP_MODE_ACTION_POST_PATHS:
            # Gaming may defer safe job controls until parsing the bounded body;
            # maintenance and unavailable mode state must fail closed pre-trace.
            if not snapshot.degraded and snapshot.mode == "gaming":
                return None
        if (
            not snapshot.degraded
            and snapshot.mode == "gaming"
            and policy == "existing_job"
        ):
            return None
        if not snapshot.degraded and snapshot.mode == "gaming" and policy == "gaming_read":
            return None
        gate_override = globals().get("operational_mode_gate_error")
        if gate_override is not None and gate_override is not _op_mod.operational_mode_gate_error:
            gate_fn = gate_override
        else:
            gate_fn = getattr(api, "operational_mode_gate_error", _op_mod.operational_mode_gate_error)
        rejection = gate_fn(
            snapshot, action, requires_heavy_work=True
        )
        if rejection is None:
            return None
    except Exception:
        rejection = {
            "success": False, "mode": "maintenance",
            "error": "operation blocked because operational mode is unavailable",
            "error_code": "operational_mode_unavailable",
            "retryable": True, "terminal": False, "retry_after_seconds": 5,
        }
    result = dict(rejection) if isinstance(rejection, dict) else {}
    result.setdefault("success", False)
    result.setdefault("error", "operation blocked by operational mode")
    result.setdefault("error_code", "operational_mode_blocked")
    result.setdefault("action", action)
    result["retryable"] = True
    result["terminal"] = False
    result.setdefault("retry_after_seconds", 5)
    return result


_MODE_UNLOAD_STATUS: dict[tuple[str, int], dict[str, Any]] = {}
_MODE_UNLOAD_DEADLINE_SECONDS: float = 5.0


def _mode_unload_status_key(app: Any, revision: int) -> tuple[str, int]:
    config = getattr(app, "config", None)
    server = config.get("server", {}) if isinstance(config, dict) else {}
    state_dir = server.get("state_dir", "state") if isinstance(server, dict) else "state"
    try:
        scope = str(Path(state_dir).expanduser().absolute())
    except (OSError, TypeError, ValueError):
        scope = str(state_dir)
    return scope, int(revision)


def _store_mode_unload_status(app: Any, revision: int, status: dict[str, Any]) -> None:
    key = _mode_unload_status_key(app, revision)
    with _MODE_UNLOAD_STATUS_LOCK:
        latest_revision = max(
            (item_revision for scope, item_revision in _MODE_UNLOAD_STATUS if scope == key[0]),
            default=-1,
        )
        if key[1] < latest_revision:
            return
        for old_key in tuple(_MODE_UNLOAD_STATUS):
            if old_key[0] == key[0] and old_key != key:
                _MODE_UNLOAD_STATUS.pop(old_key, None)
        _MODE_UNLOAD_STATUS[key] = dict(status)


def _get_mode_unload_status(app: Any, revision: int) -> dict[str, Any] | None:
    key = _mode_unload_status_key(app, revision)
    with _MODE_UNLOAD_STATUS_LOCK:
        status = _MODE_UNLOAD_STATUS.get(key)
        return dict(status) if isinstance(status, dict) else None


def _start_gaming_model_unload(
    revision: int, runtime: Any, unload_fn: Any, app: Any
) -> dict[str, Any]:
    initial: dict[str, Any] = {
        "success": False,
        "state": "pending",
        "reason": "unload_in_progress",
        "unloaded": [],
        "remaining": None,
    }
    _store_mode_unload_status(app, revision, initial)
    try:
        deadline_seconds = max(0.001, float(globals().get("_MODE_UNLOAD_DEADLINE_SECONDS", 5.0)))
    except (TypeError, ValueError, OverflowError):
        deadline_seconds = 5.0
    unload_deadline = time.monotonic() + deadline_seconds

    def worker() -> None:
        worker_done = threading.Event()
        worker_result: list[dict[str, Any]] = []

        def run_unload() -> None:
            try:
                res = unload_fn(runtime, inference_active=False)
                if not isinstance(res, dict):
                    res = {
                        "success": False,
                        "state": "failed",
                        "reason": "invalid_unload_result",
                        "unloaded": [],
                        "remaining": None,
                    }
            except Exception as exc:
                res = {
                    "success": False,
                    "state": "failed",
                    "reason": type(exc).__name__,
                    "unloaded": [],
                    "remaining": None,
                }
            worker_result.append(res)
            worker_done.set()

        t = threading.Thread(target=run_unload, daemon=True)
        t.start()

        if not worker_done.wait(timeout=deadline_seconds):
            _store_mode_unload_status(app, revision, {
                "success": False,
                "state": "failed",
                "reason": "unload_deadline_exceeded",
                "unloaded": [],
                "remaining": None,
            })
            return

        final_res = dict(worker_result[0])
        detached_cuda: list[str] = []
        failed_cuda: dict[str, str] = {}
        for name in ("embeddings", "reranker"):
            comp = getattr(app, name, None)
            if comp is not None:
                has_model = getattr(comp, "_model", None) is not None
                is_cuda = str(getattr(comp, "active_device", "") or "").strip().lower().startswith("cuda")
                if has_model and is_cuda:
                    release = getattr(comp, "release", None)
                    if not callable(release):
                        failed_cuda[name] = "release_unavailable"
                        continue
                    remaining_seconds = max(0.001, unload_deadline - time.monotonic())
                    try:
                        release(timeout_seconds=remaining_seconds)
                    except Exception as exc:
                        failed_cuda[name] = type(exc).__name__
                    if getattr(comp, "_model", None) is None:
                        detached_cuda.append(name)
                    else:
                        failed_cuda.setdefault(name, "release_failed")
        if detached_cuda:
            final_res["in_process_cuda_detached"] = detached_cuda
        if failed_cuda:
            final_res["success"] = False
            final_res["state"] = "partial"
            final_res["reason"] = "in_process_cuda_release_incomplete"
            final_res["in_process_cuda_release_failed"] = failed_cuda
            rem = list(final_res.get("remaining") or [])
            for name in failed_cuda:
                rem.append(f"in_process_cuda:{name}")
            final_res["remaining"] = rem

        cur = _get_mode_unload_status(app, revision)
        if isinstance(cur, dict) and cur.get("reason") == "unload_deadline_exceeded":
            return
        _store_mode_unload_status(app, revision, final_res)

    watcher = threading.Thread(target=worker, daemon=True)
    watcher.start()
    return initial


def _perform_deferred_gaming_release(
    app: Any, revision: int, manager_token: Any | None, async_jobs: Any | None
) -> None:
    try:
        runtime = getattr(app, "runtime", None)
        unload = getattr(runtime, "unload_configured_models", None)
        unload_res = unload(timeout_seconds=5.0) if callable(unload) else {}
        preprocessor = getattr(app, "preprocessor", None)
        prep_running = False
        if preprocessor is not None:
            try:
                prep_status = preprocessor.status()
                is_paused = bool(prep_status.get("paused")) or bool(getattr(preprocessor, "_paused", None) and preprocessor._paused.is_set())
                prep_running = (not is_paused) and (
                    not isinstance(prep_status, dict) or prep_status.get("success") is not True or any(
                        isinstance(project, dict) and project.get("status") == "running"
                        for project in prep_status.get("projects", [])
                    )
                )
            except Exception:
                prep_running = True
        if not prep_running:
            components = {
                "embeddings": getattr(app, "embeddings", None),
                "reranker": getattr(app, "reranker", None),
            }
            for name, component in components.items():
                if component is not None:
                    rel = getattr(component, "release", None)
                    if callable(rel):
                        try:
                            rel(timeout_seconds=3.0)
                        except Exception:
                            pass
            api = _operational_mode_api()
            if hasattr(api, "_empty_torch_cuda_cache"):
                try:
                    api._empty_torch_cuda_cache(3.0)
                except Exception:
                    pass
        final_status = unload_res if isinstance(unload_res, dict) and unload_res.get("success") else {
            "success": True,
            "state": "complete",
            "unloaded": unload_res.get("unloaded", []) if isinstance(unload_res, dict) else [],
            "remaining": unload_res.get("remaining") if isinstance(unload_res, dict) else [],
        }
        _store_mode_unload_status(app, revision, final_status)
    except Exception as exc:
        _store_mode_unload_status(app, revision, {"success": False, "state": "failed", "reason": type(exc).__name__})
    finally:
        if manager_token is not None and async_jobs is not None:
            end_release = getattr(async_jobs, "end_resource_release", None)
            if callable(end_release):
                end_release(manager_token)


def _is_loopback_client_address(client_address: Any) -> bool:
    try:
        host = str(client_address[0]).split("%", 1)[0]
        return ipaddress.ip_address(host).is_loopback
    except (IndexError, TypeError, ValueError):
        return False


DEBUG_TRACE_HTTP_MAX_BYTES = 8 * 1024 * 1024
SSE_REPLAY_MAX_EVENTS = 10_000


def _json_bytes(data: Any) -> bytes:
    return json_dumps_bytes(data)


def _bound_agent_event_page(status: int, page: dict[str, Any], after_seq: Any) -> tuple[int, dict[str, Any]]:
    return _bound_agent_event_page_impl(
        status,
        page,
        after_seq,
        json_bytes=_json_bytes,
        minimum_json_bytes=_minimum_json_bytes,
        max_bytes=AGENT_EVENT_PAGE_MAX_BYTES,
    )


def _resolve_memory_scope(
    scope: AgentScope | None, *, scope_id: Any = None, root: Any = None,
    repository_id: Any = None, task_id: Any = None, session_id: Any = None,
    clone_id: Any = None, worktree_id: Any = None, branch: Any = None,
) -> tuple[AgentScope | None, str | None, bool]:
    """Resolve declared namespaces without deriving an owner/session identity."""
    supplied = (scope_id, root, repository_id, task_id, session_id, clone_id, worktree_id, branch)
    if any(value is not None and (
        not isinstance(value, str) or value != value.strip() or "\x00" in value
    ) for value in supplied):
        return None, None, True
    values = {
        AgentScope.TASK: task_id or "", AgentScope.SESSION: session_id or "",
        AgentScope.CLONE: clone_id or "", AgentScope.WORKTREE: worktree_id or "",
        AgentScope.BRANCH: branch or "",
    }
    identity_scopes = [(name, value) for name, value in values.items() if value]
    resolved_id = scope_id or ""
    if scope is None:
        if len(identity_scopes) > 1:
            return None, None, True
        if identity_scopes:
            scope, expected = identity_scopes[0]
            if resolved_id and resolved_id != expected:
                return None, None, True
            resolved_id = expected
        elif root or repository_id:
            scope = AgentScope.REPOSITORY
        elif resolved_id:
            return None, None, True
    if scope is AgentScope.GLOBAL:
        if identity_scopes or resolved_id:
            return None, None, True
    elif scope is AgentScope.REPOSITORY:
        if not (root or repository_id):
            return None, None, True
    elif scope is not None:
        expected = values.get(scope, "")
        if expected:
            if resolved_id and resolved_id != expected:
                return None, None, True
            resolved_id = expected
        elif identity_scopes:
            return None, None, True
        if not resolved_id:
            return None, None, True
    return scope, resolved_id or None, False



def _parse_memory_scope(value: Any) -> AgentScope | None:
    if value is None or value == "":
        return None
    return AgentScope.parse(value)


def _memory_query_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("memory limit must be an integer") from exc
    return max(1, min(parsed, MAX_MEMORY_QUERY_LIMIT))


def _completion_revision_or_stop(root: Any, repo_tools: Any, repo_state: Any = None) -> tuple[str, dict[str, Any] | None]:
    root_value = str(root or "").strip()
    tracker = repo_state
    fingerprint = getattr(tracker, "fingerprint", None)
    if root_value and callable(fingerprint):
        try:
            state = fingerprint(root_value, force=True)
            revision = str(state.get("fingerprint", "") if isinstance(state, dict) else "").strip()
            if (
                isinstance(state, dict)
                and state.get("success") is not False
                and not state.get("degraded")
                and not state.get("stale")
                and revision
            ):
                return revision, None
        except Exception:
            pass
    snapshotter = getattr(repo_tools, "git_snapshot", None)
    if not root_value or not callable(snapshotter):
        return "", {
            "success": False,
            "terminal": True,
            "retryable": False,
            "stop_code": "completion_repository_revision_unavailable",
            "error": "completion requires a repository snapshot with a non-empty revision",
        }
    try:
        snapshot = snapshotter(root_value)
        revision = str(getattr(snapshot, "revision", "") or "").strip()
        if getattr(snapshot, "degraded", False) or getattr(snapshot, "error", None) or not revision:
            raise ValueError("repository snapshot revision unavailable")
    except Exception:
        return "", {
            "success": False,
            "terminal": True,
            "retryable": False,
            "stop_code": "completion_repository_revision_unavailable",
            "error": "completion requires a repository snapshot with a non-empty revision",
        }
    return revision, None


def _memory_lookup_has_identity(*values: Any) -> bool:
    return any(str(value or "").strip() for value in values)


def _agent_question_scope(
    *, payload: Mapping[str, Any], authorized_root: str,
) -> str:
    """Bind question storage to the authorized repository root."""
    reject_retired_tenancy_fields(payload)
    canonical_root = _strict_root_path(authorized_root)
    requested_root = payload.get("root")
    if requested_root not in (None, ""):
        if _strict_root_path(requested_root) != canonical_root:
            raise ValueError("root does not match authenticated scope")

    return str(canonical_root)


def _strict_root_path(raw: Any) -> Path:
    if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > 4096:
        raise ValueError("root is required")
    candidate = Path(raw.strip()).expanduser()
    if not candidate.is_absolute():
        raise ValueError("root must be an absolute directory")
    try:
        checked_paths = (candidate, *candidate.parents)
        before = {}
        from .repository_scope import _is_redirecting_link
        for path in checked_paths:
            info = path.lstat()
            if _is_redirecting_link(path):
                raise ValueError("symlink or junction roots are not allowed")
            before[path] = (info.st_dev, info.st_ino)
        resolved = candidate.resolve(strict=True)
        for path in checked_paths:
            info = path.lstat()
            if _is_redirecting_link(path) or (info.st_dev, info.st_ino) != before[path]:
                raise ValueError("root path changed during validation")
        resolved_info = resolved.stat()
        candidate_info = candidate.stat()
        if (resolved_info.st_dev, resolved_info.st_ino) != (candidate_info.st_dev, candidate_info.st_ino):
            raise ValueError("root target changed during validation")
    except (OSError, RuntimeError) as exc:
        raise ValueError("root must resolve to an existing allowed directory") from exc
    if not resolved.is_dir():
        raise ValueError("root must resolve to an existing directory")
    return resolved


def _root_is_allowed(root: Path, allowed_roots: Any) -> bool:
    if not isinstance(allowed_roots, list) or not allowed_roots:
        return False
    for raw_allowed in allowed_roots:
        try:
            allowed = _strict_root_path(raw_allowed)
            root.relative_to(allowed)
            return True
        except (ValueError, OSError):
            continue
    return False


def _telemetry_http_outcome(status: int, data: Any, path: str = "") -> tuple[bool, str, bool]:
    """Return reliability success, safe outcome category, and error-record flag."""
    payload = data if isinstance(data, dict) else {}
    if payload.get("outcome_unknown") is True:
        return False, "outcome_unknown", True
    success = status < 400 and payload.get("success") is not False
    if payload.get("policy_blocked"):
        return True, "policy_block", False
    if status == 404 and str(path).startswith("/" + "v" + "1/"):
        return True, "compatibility_404", False
    if payload.get("in_progress"):
        return True, "in_progress", False
    if payload.get("terminal") and status < 500:
        return True, "terminal_client_result", False
    if path == "/api/artifact/get" and payload.get("error") == "artifact not found or expired":
        return True, "terminal_client_result", False
    if success:
        return True, "", False
    if status < 400:
        return False, "application_error", True
    return False, "http_error", True


def _journal_outcome_success(status: int, data: Any) -> bool:
    payload = data if isinstance(data, dict) else {}
    if payload.get("outcome_unknown") is True:
        return False
    return bool(payload.get("terminal") or payload.get("in_progress") or (status < 400 and payload.get("success") is not False))


def _response_phase_latency(data: Any) -> dict[str, float]:
    """Extract only upstream phase timings that were actually measured."""
    latency = data.get("latency", {}) if isinstance(data, dict) else {}
    latency = latency if isinstance(latency, dict) else {}
    def value(name: str) -> float | None:
        if name not in latency:
            return None
        raw = latency[name]
        if isinstance(raw, bool):
            return None
        try:
            measured = float(raw)
            return measured if math.isfinite(measured) and measured >= 0 else None
        except (TypeError, ValueError):
            return None
    result = {
        name: value(name) or 0.0
        for name in ("queue_wait_ms", "service_ms")
    }
    result.update({
        name: measured
        for name in ("db_wait_ms", "exec_ms", "serialization_ms")
        if (measured := value(name)) is not None
    })
    return result


def _log_http_failure(
    logger: Any,
    method: str,
    path: str,
    exc: BaseException,
    *,
    request_id: str = "",
) -> None:
    # Stack locations only: messages, source lines and locals can contain secrets.
    frames = traceback.extract_tb(exc.__traceback__, limit=-32)
    stack = "\n".join(
        f"  File {frame.filename!r}, line {frame.lineno}, in {frame.name}"
        for frame in frames
    )
    safe_request_id = "".join(
        char for char in str(request_id)[:96]
        if (char.isascii() and char.isalnum()) or char in "_.:-"
    )
    logger.error(
        "%s request failed path=%s request_id=%s pid=%s error_type=%s traceback=\n%s",
        method, urlparse(path).path, safe_request_id, os.getpid(), type(exc).__name__, stack or "(unavailable)",
    )





class RequestBodyError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


_CANONICAL_AGENT_ACTION = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")
_AGENT_TASK_ACTIONS = frozenset({
    "create", "list", "get", "transition", "complete", "fail",
    "checkpoint", "rollback", "resume", "heartbeat", "ask", "answer",
    "cleanup_worktree", "reap_expired", "curate_dataset", "budget_increase",
    "claim", "adopt", "repair_session", "projection_restore_preview", "projection_restore",
    "projection_restore_batch_preview", "projection_restore_batch",
})
_AGENT_VERIFICATION_ACTIONS = frozenset({"receipt", "completion", "export", "native_receipt", "project_command"})
_AGENT_BLACKBOARD_RETIRED_FIELDS = frozenset({"key", "value", "approver", "sections", "record"})


def _agent_action_selector(payload: Mapping[str, Any], default: str | None = None) -> str | None:
    if "action" not in payload:
        return default
    action = payload["action"]
    if not isinstance(action, str) or _CANONICAL_AGENT_ACTION.fullmatch(action) is None:
        raise RequestBodyError("action must use canonical lowercase underscore syntax")
    return action


class LocalAIHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server with a hard cap on live handler threads and installation-wide rate limiting.

    ``ThreadingHTTPServer`` is otherwise unbounded: a burst of local agents or a
    misbehaving local client can create hundreds of handler threads before the model
    scheduler's own queue limits are reached. Overload is rejected immediately with a
    small 503 so the hub remains responsive to health checks and existing work.
    """

    daemon_threads = True
    # POSIX can rebind after TIME_WAIT while still excluding a second listener.
    allow_reuse_address = os.name == "posix"
    allow_reuse_port = False
    request_queue_size = 128

    def __init__(self, server_address: tuple[str, int], handler: type[BaseHTTPRequestHandler], *, max_handlers: int = 64, overload_wait_seconds: float = 0.05):
        self.max_handlers = max(4, int(max_handlers))
        self.overload_wait_seconds = max(0.0, float(overload_wait_seconds))
        self._overload_retry_after_seconds = 1
        self._overload_body = json_dumps(
            {
                "success": False, "error": "hub overloaded; retry later", "status_code": 503,
                "retryable": True, "retry_after_seconds": self._overload_retry_after_seconds,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        self._handler_slots = threading.BoundedSemaphore(self.max_handlers)
        self._active_handlers = 0
        self._rejected_handlers = 0
        self._handler_stats_lock = threading.Lock()
        # One bounded request window for the local installation.
        self._rate_limit_requests: int = 600   # overridden after config load
        self._rate_limit_window: float = 60.0  # seconds
        self._rate_window: deque[float] = deque()
        self._rate_lock = threading.Lock()
        super().__init__(server_address, handler)

    def get_request(self) -> tuple[Any, Any]:
        sock, addr = super().get_request()
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (OSError, AttributeError):
            pass
        return sock, addr

    def server_bind(self) -> None:
        host = str(self.server_address[0]) if isinstance(self.server_address, tuple) else ""
        if host != "127.0.0.1":
            raise RuntimeError("Refusing Local AI Hub network exposure: server.bind must be 127.0.0.1")
        if os.name == "nt":
            exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if exclusive is None:
                raise OSError("exclusive Hub listener binding is unavailable")
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()

    def verify_request(self, request: Any, client_address: Any) -> bool:
        """Reject non-loopback peers before any HTTP route, including health."""
        return _is_loopback_client_address(client_address)

    def configure_rate_limit(self, requests: int, window_seconds: float) -> None:
        """Apply config-driven rate limit values after server creation."""
        with self._rate_lock:
            self._rate_limit_requests = max(1, int(requests))
            self._rate_limit_window = max(1.0, float(window_seconds))

    def check_rate_limit(self) -> bool:
        """Apply the installation's request limit without identity partitions."""
        if self._rate_limit_requests <= 0:
            return True  # rate limiting disabled
        with self._rate_lock:
            now = time.monotonic()
            window = self._rate_window
            cutoff = now - self._rate_limit_window
            # Prune old entries; keep list bounded to avoid unbounded growth
            while window and window[0] < cutoff:
                window.popleft()
            if len(window) >= self._rate_limit_requests:
                return False
            window.append(now)
            return True

    def process_request(self, request: Any, client_address: Any) -> None:
        acquired = self._handler_slots.acquire(timeout=self.overload_wait_seconds)
        if not acquired:
            with self._handler_stats_lock:
                self._rejected_handlers += 1
            body = self._overload_body
            try:
                if APP is not None:
                    APP.telemetry.record_http(
                        action="admission", duration_ms=0.0, success=False, status_code=503,
                        error_type="overload", retry_count=0,
                    )
            except Exception:
                pass
            try:
                # Rejection runs on the acceptor, before Handler.setup can set
                # socket deadlines. A stalled peer must not freeze all clients.
                request.settimeout(1.0)
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Type: application/json; charset=utf-8\r\n"
                    b"Connection: close\r\n"
                    b"Retry-After: 1\r\n"
                    + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
                    + body
                )
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        with self._handler_stats_lock:
            self._active_handlers += 1
        try:
            super().process_request(request, client_address)
        except Exception:
            with self._handler_stats_lock:
                self._active_handlers = max(0, self._active_handlers - 1)
            self._handler_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._handler_stats_lock:
                self._active_handlers = max(0, self._active_handlers - 1)
            self._handler_slots.release()

    def concurrency_stats(self) -> dict[str, int]:
        with self._handler_stats_lock:
            return {
                "active": self._active_handlers,
                "limit": self.max_handlers,
                "rejected": self._rejected_handlers,
            }


def _task_create_contract(payload: Mapping[str, Any]) -> GoalContract:
    """Parse the canonical task contract object."""
    contract_data = payload.get("contract")
    if not isinstance(contract_data, Mapping):
        raise ValueError("contract must be an object")
    return GoalContract.from_dict(contract_data)


def _safe_agent(handler: Any) -> str:
    headers = getattr(handler, "headers", None)
    if headers is not None and hasattr(headers, "get"):
        value = headers.get("X-LocalAI-Agent")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "generic"


def _async_job_http_status(response: Any) -> int:
    """Map async-job result metadata to the matching transport status."""
    if not isinstance(response, dict):
        return 200
    explicit = response.get("status_code")
    if type(explicit) is int and 400 <= explicit <= 599:
        return explicit
    state = response.get("state")
    if response.get("conflict") is True or state == "conflict":
        return 409
    if state == "expired" or response.get("error") == "async job result expired":
        return 410
    if response.get("error") == "async job not found":
        return 404
    if state == "rejected" and response.get("retryable") is True:
        return 429
    return 200


from .http_routes_api import Handler as Handler



def validate_network_security(config: dict[str, Any]) -> None:
    server = config.get("server", {})
    security = config.get("security", {})
    if "client_host" in server:
        raise RuntimeError("Refusing remote Hub client: server.client_host was removed")
    if "allow_remote" in security:
        raise RuntimeError("Refusing remote Hub access: security.allow_remote was removed")
    if security.get("allowed_hosts") or security.get("allowed_origins"):
        raise RuntimeError("Refusing remote Hub origins: configured host/origin overrides were removed")
    bind = str(server.get("bind", "127.0.0.1"))
    if bind != "127.0.0.1":
        raise RuntimeError("Refusing Local AI Hub network exposure: server.bind must be 127.0.0.1")


def _require_owned_supervisor_parent(state_dir: Path) -> None:
    owner_path = state_dir / "supervisor.owner.json"
    deadline = time.monotonic() + 1.0
    while True:
        try:
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
            break
        except FileNotFoundError as exc:
            # Popen returns before the supervisor can publish the verified
            # child/parent identity record. Wait briefly for that atomic write;
            # never accept a missing, malformed, or unverified owner.
            if time.monotonic() >= deadline:
                raise RuntimeError("Hub must be started by an identity-verified supervisor") from exc
            time.sleep(0.01)
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("Hub must be started by an identity-verified supervisor") from exc
    if not isinstance(owner, dict) or isinstance(owner.get("pid"), bool):
        raise RuntimeError("Hub must be started by an identity-verified supervisor")
    try:
        owner_pid = int(owner.get("pid", 0) or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError("Hub must be started by an identity-verified supervisor") from exc
    parent_pid = process_parent_pid()
    parent_matches = owner_pid == parent_pid
    if not parent_matches and parent_pid is not None:
        # Windows may insert the python.exe/pythonw.exe launcher as the
        # process's direct parent. Accept only that known interpreter shim
        # when its own parent is the identity-verified supervisor.
        parent_identity = process_identity(parent_pid)
        parent_executable = (
            Path(str(parent_identity.get("executable", ""))).name.casefold()
            if isinstance(parent_identity, dict)
            else ""
        )
        parent_matches = (
            parent_executable in {"python.exe", "pythonw.exe"}
            and process_parent_pid(parent_pid) == owner_pid
        )
    owner_state = process_owner_state(owner, state_dir, "supervisor")
    if not parent_matches or owner_state != "owned":
        raise RuntimeError(
            "Hub must be started by an identity-verified supervisor "
            f"(parent_match={parent_matches}, owner_state={owner_state}, "
            f"owner_pid={owner_pid}, parent_pid={parent_pid})"
        )


def serve(config_path: str | None = None) -> None:
    global APP
    # Bind the public port before constructing LocalAIApp. A duplicate/stale service
    # process therefore fails before it starts preprocessing threads or opens the
    # shared SQLite stores, eliminating a major source of lock storms during restart.
    startup_config = load_config(config_path)
    validate_network_security(startup_config)
    startup_state_dir = Path(startup_config["server"]["state_dir"]).expanduser().resolve()
    # The supervisor owns the PID record, which can identify a Windows venv launcher.
    _require_owned_supervisor_parent(startup_state_dir)
    cfg = startup_config["server"]
    server = LocalAIHTTPServer(
        (cfg.get("bind", "127.0.0.1"), int(cfg.get("port", 11435))),
        Handler,
        max_handlers=int(cfg.get("max_concurrent_requests", 64)),
        overload_wait_seconds=float(cfg.get("overload_wait_seconds", 0.05)),
    )
    app: LocalAIApp | None = None
    telemetry_start_attempted = False
    try:
        app = LocalAIApp(config_path)
        APP = app
        validate_network_security(APP.config)
        cfg = APP.config["server"]
        state_dir = Path(cfg["state_dir"]).expanduser().resolve()
        if state_dir != startup_state_dir:
            raise RuntimeError("Hub config state directory changed during startup")
        state_dir.mkdir(parents=True, exist_ok=True)
        # Configure rate limiting from security config
        sec_cfg = APP.config.get("security", {})
        server.configure_rate_limit(
            requests=int(sec_cfg.get("rate_limit_requests", 600)),
            window_seconds=float(sec_cfg.get("rate_limit_window_seconds", 60.0)),
        )
        APP.logger.info(
            "hub started version=%s bind=%s port=%s pid=%s parent_pid=%s",
            __version__, cfg.get("bind", "127.0.0.1"), int(cfg.get("port", 11435)),
            os.getpid(), os.getppid(),
        )
        telemetry_start_attempted = True
        APP.telemetry.session_start(os.getpid(), __version__)
        APP.telemetry.record_system("hub_start", success=True)
        server.serve_forever()
    finally:
        try:
            server.server_close()
        finally:
            if app is not None:
                if telemetry_start_attempted:
                    try:
                        app.telemetry.session_stop()
                        app.telemetry.record_system("hub_stop", success=True)
                        app.telemetry.flush(1.0)
                        app.logger.info("hub stopping version=%s pid=%s", __version__, os.getpid())
                    except Exception:
                        pass
                try:
                    app.close()
                except Exception:
                    pass
                finally:
                    if APP is app:
                        APP = None


if __name__ == "__main__":
    serve(os.environ.get("LOCAL_AI_CONFIG"))


__all__ = [
    'AGENT_EVENT_PAGE_MAX_BYTES',
    'AGENT_EVENT_PAGE_MAX_LIMIT',
    'AgentScope',
    'Any',
    'ApprovalRequiredError',
    'BaseHTTPRequestHandler',
    'CheckpointResponseBudgetError',
    'CompletionGateError',
    'ConfigError',
    'DEBUG_TRACE_HTTP_MAX_BYTES',
    'DebugTraceObserver',
    'FeatureSet',
    'GoalContract',
    'HTTP_MODE_ACTION_POST_PATHS',
    'HTTP_MODE_GAMING_READ_GET_PATHS',
    'HTTP_MODE_GAMING_READ_POST_PATHS',
    'HTTP_MODE_OPERATOR_GET_PATHS',
    'HTTP_MODE_OPERATOR_POST_PATHS',
    'HTTP_MODE_SAFE_METHOD_REJECTIONS',
    'Handler',
    'ImprovementCandidate',
    'IncidentFingerprint',
    'LocalAIApp',
    'LocalAIHTTPServer',
    'MAX_EVENT_SEQUENCE',
    'MAX_HTTP_PAGE_RESPONSE_BYTES',
    'MAX_MEMORY_QUERY_LIMIT',
    'MAX_PAGE_SIZE',
    'MAX_PAGE_WINDOW',
    'MONITOR_PATHS',
    'Mapping',
    'MemoryKind',
    'MemoryRecord',
    'MemoryStatus',
    'ModelUnavailableError',
    'Path',
    'QueueFullError',
    'READINESS_COMPONENTS',
    'RecoveryJournal',
    'RepositoryScopeError',
    'RequestBodyError',
    'RequestHeadReader',
    'SLOObservation',
    'SSE_REPLAY_MAX_EVENTS',
    'ScopeContext',
    'TaskCheckpoint',
    'TaskIdempotencyConflictError',
    'TaskPage',
    'TaskStatus',
    'TaskWorktreeError',
    'ThreadingHTTPServer',
    'ToolOutcome',
    'VerificationReceipt',
    '_ACTIVE_CONVERSATIONS',
    '_ACTIVE_DELEGATES',
    '_ACTIVE_TRANSCRIPTIONS',
    '_AGENT_BLACKBOARD_RETIRED_FIELDS',
    '_AGENT_TASK_ACTIONS',
    '_AGENT_VERIFICATION_ACTIONS',
    '_ActiveTranscriptionRegistry',
    '_CANONICAL_AGENT_ACTION',
    '_DB_QUERY_MAX_RESPONSE_BYTES',
    '_DB_QUERY_MAX_ROWS',
    '_DB_QUERY_MAX_SQL_BYTES',
    '_DB_QUERY_TIMEOUT_SECONDS',
    '_GAMING_DRAIN_TIMEOUT_SECONDS',
    '_HTTP_MAX_BODY_SECONDS',
    '_HTTP_MAX_JSON_BODY_BYTES',
    '_MODEL_PULL_MAX_RESPONSE_BYTES',
    '_MODEL_PULL_TIMEOUT_SECONDS',
    '_MODE_UNLOAD_STATUS_LOCK',
    '_STATUS_DEPENDENCY_TIMEOUT_SECONDS',
    '_STATUS_TOTAL_BUDGET_SECONDS',
    '__version__',
    '_agent_action_selector',
    '_agent_question_scope',
    '_api_result_http_response',
    '_apply_live_debug_trace_toggle',
    '_async_job_http_status',
    '_bind_repository_memory_provenance',
    '_bound_agent_event_page',
    '_bound_agent_event_page_impl',
    '_completion_revision_or_stop',
    '_config_update_failure_payload',
    '_encode_agent_event_cursor',
    '_get_mode_unload_status',
    '_http_admin_action',
    '_http_hardware_capability_error',
    '_http_mode_action',
    '_http_mode_gate_error',
    '_http_mode_policy',
    '_in_process_cuda_unload_blockers',
    '_incident_scope_key',
    '_invoke_cancellable_request',
    '_is_client_disconnect',
    '_is_loopback_client_address',
    '_is_loopback_peer',
    '_journal_outcome_success',
    '_json_bytes',
    '_lease_coordination_id',
    '_log_http_failure',
    '_memory_lookup_has_identity',
    '_memory_query_limit',
    '_minimum_json_bytes',
    '_mode_unload_status_key',
    '_normalize_trace_content',
    '_ollama_runner_present',
    '_operational_mode_api',
    '_parse_agent_event_cursor',
    '_parse_include_body',
    '_parse_memory_scope',
    '_perform_deferred_gaming_release',
    '_public_gaming_unload_status',
    '_query_int',
    '_reconcile_existing_budget',
    '_recovery_claim_failure_response',
    '_redact_config_secrets',
    '_require_owned_supervisor_parent',
    '_resolve_memory_scope',
    '_response_phase_latency',
    '_root_is_allowed',
    '_safe_agent',
    '_safe_config_file_label',
    '_start_disconnect_monitor',
    '_start_gaming_model_unload',
    '_status_dependency',
    '_store_mode_unload_status',
    '_strict_root_path',
    '_task_create_contract',
    '_telemetry_http_outcome',
    '_token_matches',
    '_trusted_project_context',
    'abandon_staged_capture',
    'annotations',
    'apply_cors_headers',
    'authorized_repository_root',
    'build_context_request',
    'capability_feature_gate',
    'capability_minimum_profile',
    'capability_profile_available',
    'capture_failure',
    'capture_to_artifacts',
    'commit_staged_capture',
    'compose_task_context',
    'configured_state_dir',
    'connect_sqlite',
    'datetime',
    'decide_delivery',
    'deep_merge',
    'default_agent_search_mode',
    'deque',
    'agent_diagnostics_enabled',
    'detailed_diagnostics_enabled',
    'diagnostic_http_operation',
    'diagnostics_disabled_response',
    'handle_post_plan',
    'handle_post_repository_analysis',
    'hashlib',
    'hmac',
    'inspect',
    'io',
    'ipaddress',
    'is_busy_error',
    'issue_capture_capability',
    'json',
    'json_dumps',
    'json_dumps_bytes',
    'json_loads',
    'load_config',
    'load_operational_mode',
    'math',
    'normalize_transport_error',
    'nullcontext',
    'origin_allowed',
    'os',
    'pagination_bounds_error',
    'parse_qs',
    'process_identity',
    'process_owner_state',
    'process_parent_pid',
    'project_agent_response',
    'project_aggregate_response',
    'project_pubsub_poll_response',
    'project_status_response',
    'project_wait_event_response',
    'queue',
    're',
    'redact_trace_export',
    'reject_retired_tenancy_fields',
    'repository_search_timeout',
    'reset_context',
    'reset_observer',
    'resolve_project_context',
    'save_runtime_overrides',
    'search_execution_stopped',
    'select',
    'select_get_handler',
    'select_http_routes',
    'select_post_handler',
    'serve',
    'set_context',
    'set_observer',
    'set_operational_mode',
    'socket',
    'sqlite3',
    'stage_capture',
    'sys',
    'threading',
    'time',
    'timezone',
    'traceback',
    'urllib',
    'urlparse',
    'uuid',
    'validate_capture_request',
    'validate_config',
    'validate_network_security',
]
