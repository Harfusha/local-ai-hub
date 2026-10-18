from __future__ import annotations

from .http_identity import request_principal_tenant

import hashlib
import hmac
import ipaddress
import inspect
import json
import math
import os
import queue
import re
import select
import socket
import sqlite3
import uuid
import time
import threading
from contextlib import contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
import urllib.request
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import __version__
from .app import LocalAIApp

_STATUS_DEPENDENCY_TIMEOUT_SECONDS = 0.25
_STATUS_TOTAL_BUDGET_SECONDS = 1.0


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
from .scheduler import ModelUnavailableError, QueueFullError
from .debug_traces import _normalize_trace_content
from .trace_context import reset_context, reset_observer, set_context
from .http_route_registry import select_get_handler, select_http_routes, select_post_handler
from .http_post_repository_analysis import handle_post_repository_analysis
from .dashboard import DASHBOARD_HTML
from .config import ConfigError, deep_merge, load_config, save_runtime_overrides, validate_config
from .delivery import decide_delivery
from .resilience import RecoveryJournal
from .sqlite_support import is_busy_error
from .agent_identity import AgentScope, ScopeContext
from .project_config import resolve_project_context
from .state_paths import configured_state_dir
from .agent_tasks import (
    CheckpointResponseBudgetError,
    CompletionGateError,
    GoalContract,
    TaskWorktreeError,
    TaskCheckpoint,
    TaskStatus,
)
from .agent_memory import ApprovalRequiredError, MAX_MEMORY_QUERY_LIMIT, MemoryKind, MemoryRecord, MemoryStatus
from .agent_incidents import IncidentFingerprint, ToolOutcome, _incident_scope_key
from .agent_verification import VerificationReceipt
from .task_context import build_context_request, compose_task_context
from .agent_learning import ImprovementCandidate, SLOObservation
from .operation_contracts import normalize_transport_error
from .search_pagination import MAX_HTTP_PAGE_RESPONSE_BYTES, pagination_bounds_error
from .json_utils import dumps as json_dumps, dumps_bytes as json_dumps_bytes, loads as json_loads
from .process_utils import process_identity, process_owner_state, process_parent_pid

from .browser_bridge import (
    abandon_staged_capture,
    capture_failure,
    capture_to_artifacts,
    commit_staged_capture,
    issue_capture_capability,
    origin_allowed,
    stage_capture,
    validate_capture_request,
)
from .operational_mode import (
    load_operational_mode,
    operational_mode_gate_error,
    set_operational_mode,
)


os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

APP: LocalAIApp | None = None
_MODE_UNLOAD_STATUS_LOCK = threading.Lock()
MAX_EVENT_SEQUENCE = (1 << 63) - 1
_DB_QUERY_TIMEOUT_SECONDS = 0.5
_DB_QUERY_MAX_ROWS = 100
_DB_QUERY_MAX_RESPONSE_BYTES = 256 * 1024
_DB_QUERY_MAX_SQL_BYTES = 8192
_MODEL_PULL_TIMEOUT_SECONDS = 120.0


def _encode_agent_event_cursor(stream_id: str, seq: int) -> str:
    return f"{quote(str(stream_id), safe='')}:{max(0, min(int(seq), MAX_EVENT_SEQUENCE))}"


def _parse_agent_event_cursor(value: Any) -> tuple[str, int] | None:
    raw = str(value or "")
    if not raw or len(raw) > 2048 or "\r" in raw or "\n" in raw:
        return None
    encoded_stream, separator, encoded_seq = raw.rpartition(":")
    if not separator or not encoded_stream or not encoded_seq.isascii() or not encoded_seq.isdecimal():
        return None
    try:
        stream_id = unquote(encoded_stream)
        seq = int(encoded_seq)
    except (TypeError, ValueError, OverflowError):
        return None
    if not stream_id or seq < 0 or seq > MAX_EVENT_SEQUENCE:
        return None
    return stream_id, seq
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
    provenance: Mapping[str, Any],
    *,
    root: str,
    tenant: str,
    project_context: Any | None,
) -> dict[str, Any]:
    """Bind repository source and shared identity from trusted server context."""
    result = dict(provenance)
    result.pop("repository_id", None)
    physical_root = str(getattr(project_context, "root", root) or root).strip()
    if physical_root:
        result["root"] = physical_root
    if tenant:
        result["tenant"] = tenant
    coordination_id = str(
        getattr(project_context, "coordination_id", None) or ""
    ).strip()
    if coordination_id:
        # Reuse existing provenance field, populated only from ProjectContext.
        result["repository_id"] = coordination_id
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

class _ActiveTranscriptionRegistry:
    """Track synchronous Whisper calls and cancel them before gaming release."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._active: dict[str, threading.Event] = {}
        self._results: dict[str, dict[str, Any]] = {}
        self._waiting: set[str] = set()
        self._gaming = False
        self._drained_callbacks: list[Any] = []

    def enter_gaming(self) -> None:
        with self._condition:
            self._gaming = True
            # Track before signaling: a cooperative worker may finish before
            # cancel_and_wait takes its own active snapshot.
            self._waiting.update(self._active)
            for event in self._active.values():
                event.set()
            self._condition.notify_all()

    def enter_active(self) -> None:
        with self._condition:
            self._gaming = False

    def begin(self) -> tuple[str, threading.Event]:
        token = uuid.uuid4().hex
        event = threading.Event()
        with self._condition:
            if self._gaming:
                self._waiting.add(token)
                event.set()
            self._active[token] = event
            self._condition.notify_all()
        return token, event

    def finish(self, token: str, result: Any) -> None:
        callbacks: list[Any] = []
        with self._condition:
            normalized = result if isinstance(result, dict) else {}
            if token in self._waiting:
                self._results[token] = {
                    "cancelled": normalized.get("reason") == "cancelled" or normalized.get("cancelled") is True,
                    "success": normalized.get("success") is True,
                }
            self._active.pop(token, None)
            if not self._active:
                callbacks, self._drained_callbacks = self._drained_callbacks, []
                self._condition.notify_all()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass

    def cancel_and_wait(self, timeout_seconds: float) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        with self._condition:
            active_at_start = tuple(self._active)
            self._waiting.update(active_at_start)
            for event in self._active.values():
                event.set()
            while self._active and time.monotonic() < deadline:
                self._condition.wait(max(0.0, deadline - time.monotonic()))
            pending = len(self._active)
            tracked = set(active_at_start) | set(self._waiting) | set(self._results)
            results = [self._results.pop(token, {}) for token in tracked]
            self._waiting.difference_update(tracked)
        if pending:
            return {"state": "timed_out", "inference_active": True, "active": pending}
        if not tracked:
            return {"state": "not_applicable", "inference_active": False, "active": 0}
        cancelled = all(item.get("cancelled") is True for item in results)
        return {
            "state": "cancelled" if cancelled else "completed",
            "inference_active": False,
            "active": 0,
            "cancelled": cancelled,
        }

    def when_drained(self, callback: Any) -> None:
        with self._condition:
            if self._active:
                self._drained_callbacks.append(callback)
                return
        try:
            callback()
        except Exception:
            pass

    def active_count(self) -> int:
        with self._condition:
            return len(self._active)

    def defer_process_cleanup(self, token: str, process: Any, *, tree_termination_confirmed: bool) -> None:
        if not tree_termination_confirmed:
            return

        def observe_exit() -> None:
            try:
                process.wait()
            except Exception:
                return
            self.finish(token, {"success": False, "reason": "cancelled", "cancelled": True})

        try:
            threading.Thread(target=observe_exit, name="whisper-cleanup-observer", daemon=True).start()
        except Exception:
            return


_ACTIVE_TRANSCRIPTIONS = _ActiveTranscriptionRegistry()
_ACTIVE_CONVERSATIONS = _ActiveTranscriptionRegistry()
_GAMING_DRAIN_TIMEOUT_SECONDS = 4.5


def _invoke_cancellable_request(registry: _ActiveTranscriptionRegistry, callback: Any, payload: dict[str, Any], tenant: str) -> Any:
    token, cancel_event = registry.begin()
    result: Any = {}
    try:
        try:
            parameters = inspect.signature(callback).parameters.values()
            supports_cancel = any(
                parameter.name == "cancel_event"
                or parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
        except (TypeError, ValueError):
            supports_cancel = False
        if cancel_event.is_set() and not supports_cancel:
            result = {
                "success": False,
                "cancelled": True,
                "preempted": True,
                "reason": "cancelled",
                "error": "request cancelled before an uncancellable handler could start",
                "terminal": True,
                "retryable": False,
            }
            return result
        result = (
            callback(payload, tenant, cancel_event=cancel_event)
            if supports_cancel
            else callback(payload, tenant)
        )
        return result
    finally:
        registry.finish(token, result)

# Monitoring/control reads must never appear as workload. Keep this hard safety set
# independent of user config so a dashboard refresh cannot create immortal active jobs.
MONITOR_PATHS = {
    "/health", "/ready", "/dashboard", "/favicon.ico", "/api/live", "/api/live/status",
    "/api/status", "/api/mode", "/api/capabilities", "/api/metrics", "/api/adoption",
    "/api/telemetry/report", "/api/telemetry/tool-accounting", "/api/telemetry/timeline",
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










def _dashboard_html_with_trace_notice() -> str:
    return DASHBOARD_HTML.replace(
        "Agent debug traces · off by default; payloads available when enabled",
        "Agent debug traces · full input/output only when enabled · complete stored details shown as recorded · local access only · separate local retention policy",
        1,
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
    "/api/telemetry/report", "/api/telemetry/timeline",
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
    "/api/command/speculative-lint",
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
            "/api/telemetry/report": "telemetry.read",
            "/api/telemetry/timeline": "telemetry.read",
        }.get(path)
    if method == "POST":
        if path.startswith("/api/maintenance/"):
            return "maintenance"
        return {
            "/api/admin/mode": "mode.control",
            "/api/bundle/import": "bundle.import",
            "/api/config": "config.write",
            "/api/config/update": "config.write",
            "/api/db/query": "db.query",
            "/api/models/manage": "model.manage",
        }.get(path)
    return None


def _apply_live_debug_trace_toggle(app: Any, settings: dict[str, Any]) -> bool:
    if set(settings) != {"debug_traces.enabled"}:
        return False
    store = getattr(app, "debug_traces", None)
    if store is None:
        return False
    store.enabled = bool(settings["debug_traces.enabled"])
    return True


def _token_matches(supplied: str, expected: str) -> bool:
    if not expected:
        return False
    try:
        return hmac.compare_digest(str(supplied), expected)
    except (TypeError, ValueError):
        return False


def _redact_config_secrets(config: dict[str, Any]) -> dict[str, Any]:
    view = json.loads(json_dumps(config, default=str))
    security = view.get("security")
    if not isinstance(security, dict):
        return view
    if security.get("api_token"):
        security["api_token"] = "***configured***"
    if security.get("supervisor_token"):
        security["supervisor_token"] = "***configured***"
    action_tokens = security.get("action_tokens")
    if isinstance(action_tokens, dict):
        security["action_tokens"] = {
            str(action): "***configured***"
            for action, token in action_tokens.items() if token
        }
    elif action_tokens:
        security["action_tokens"] = "***configured***"
    users = security.get("users")
    if isinstance(users, dict):
        for user in users.values():
            if isinstance(user, dict) and user.get("token"):
                user["token"] = "***configured***"
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
    if path in {"/api/speculative-lint", "/api/command/speculative-lint"}:
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
    action_key = "job_action" if path == "/api/async-jobs" else "action"
    action = str((payload or {}).get(action_key, "")).strip().lower().replace("-", "_")
    if path == "/api/evaluation" and action == "report":
        return "gaming_read"
    if path == "/api/async-jobs" and action in {"status", "wait", "result", "cancel", "evaluation_report"}:
        return "existing_job"
    if path == "/api/work-orders" and action in {"status", "get", "cancel"}:
        return "existing_job"
    if path in {"/api/speculative-lint", "/api/command/speculative-lint"} and action in {"status", "cancel"}:
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
        if globals().get("operational_mode_gate_error") is not _op_mod.operational_mode_gate_error:
            gate_fn = globals()["operational_mode_gate_error"]
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


def _is_loopback_client_address(client_address: Any) -> bool:
    try:
        host = str(client_address[0]).split("%", 1)[0]
        return ipaddress.ip_address(host).is_loopback
    except (IndexError, TypeError, ValueError):
        return False


def _json_bytes(data: Any) -> bytes:
    return json_dumps_bytes(data)


AGENT_EVENT_PAGE_MAX_BYTES = 1024 * 1024
AGENT_EVENT_PAGE_MAX_LIMIT = 100
DEBUG_TRACE_HTTP_MAX_BYTES = 8 * 1024 * 1024
SSE_REPLAY_MAX_EVENTS = 10_000


def _minimum_json_bytes(value: Any, ceiling: int) -> int:
    """Lower bound UTF-8 JSON size without encoding potentially huge event values."""
    if isinstance(value, str):
        return min(len(value) + 2, ceiling + 1)
    if value is None:
        return 4
    if value is True:
        return 4
    if value is False:
        return 5
    if isinstance(value, (int, float)):
        try:
            return min(len(json_dumps(value).encode("ascii")), ceiling + 1)
        except (OverflowError, ValueError):
            return ceiling + 1
    total = 0
    if isinstance(value, dict):
        total = 2 + max(0, len(value) - 1)
        if total > ceiling:
            return ceiling + 1
        for key, item in value.items():
            total += _minimum_json_bytes(key, ceiling - total)
            if total > ceiling:
                return ceiling + 1
            total += 1 + _minimum_json_bytes(item, ceiling - total)
            if total > ceiling:
                return ceiling + 1
    elif isinstance(value, (list, tuple)):
        total = 2 + max(0, len(value) - 1)
        if total > ceiling:
            return ceiling + 1
        for item in value:
            total += _minimum_json_bytes(item, ceiling - total)
            if total > ceiling:
                return ceiling + 1
    return total


def _bound_agent_event_page(status: int, page: dict[str, Any], after_seq: Any) -> tuple[int, dict[str, Any]]:
    """Bound serialized event pages while keeping the cursor on the last returned row."""
    try:
        cursor = max(0, int(after_seq))
    except (TypeError, ValueError, OverflowError):
        cursor = 0

    original_events = list(page.get("events") or [])
    if not original_events:
        return (status, page) if len(_json_bytes(page)) <= AGENT_EVENT_PAGE_MAX_BYTES else (
            413,
            {
                "success": False, "events": [], "next_seq": cursor,
                "first_retained_seq": max(0, int(page.get("first_retained_seq") or 0)),
                "last_seq": max(0, int(page.get("last_seq") or 0)), "has_more": False,
                "gap_ranges": [], "cursor_reset": bool(page.get("cursor_reset")),
                "error": {"code": "agent_event_page_too_large", "message": "event page metadata exceeds serialized response byte limit", "max_bytes": AGENT_EVENT_PAGE_MAX_BYTES},
            },
        )

    event_bytes = 0
    best_page: dict[str, Any] | None = None
    for index, event in enumerate(original_events):
        candidate = dict(page)
        try:
            candidate["next_seq"] = max(0, int(event.get("seq") or 0))
        except (AttributeError, TypeError, ValueError, OverflowError):
            break
        trimmed = index + 1 < len(original_events)
        candidate["has_more"] = bool(page.get("has_more")) or trimmed
        candidate["gap_ranges"] = [
            gap for gap in (page.get("gap_ranges") or [])
            if isinstance(gap, dict) and int(gap.get("to_seq") or 0) <= candidate["next_seq"]
        ]
        candidate["events"] = []
        envelope_bytes = len(_json_bytes(candidate)) - 2  # Replace serialized empty event list.
        separator_bytes = 1 if index else 0
        if envelope_bytes + event_bytes + separator_bytes + _minimum_json_bytes(
            event, AGENT_EVENT_PAGE_MAX_BYTES
        ) > AGENT_EVENT_PAGE_MAX_BYTES:
            break
        item_bytes = len(_json_bytes(event))
        if envelope_bytes + event_bytes + separator_bytes + item_bytes > AGENT_EVENT_PAGE_MAX_BYTES:
            break
        event_bytes += item_bytes
        candidate["events"] = original_events[:index + 1]
        best_page = candidate
    if best_page is not None:
        return status, best_page

    # A single event can exceed the budget through uncapped metadata fields.
    # Keep the caller cursor unchanged so retry cannot silently skip that row.
    return 413, {
        "success": False,
        "events": [],
        "next_seq": cursor,
        "first_retained_seq": max(0, int(page.get("first_retained_seq") or 0)),
        "last_seq": max(0, int(page.get("last_seq") or 0)),
        "has_more": bool(page.get("has_more")) or bool(original_events),
        "gap_ranges": [],
        "cursor_reset": bool(page.get("cursor_reset")),
        "error": {
            "code": "agent_event_page_too_large",
            "message": "first event exceeds serialized response byte limit",
            "max_bytes": AGENT_EVENT_PAGE_MAX_BYTES,
        },
    }


def _resolve_memory_scope(
    scope: AgentScope | None,
    *,
    scope_id: Any = None,
    root: Any = None,
    repository_id: Any = None,
    tenant: Any = None,
    task_id: Any = None,
    session_id: Any = None,
    clone_id: Any = None,
    worktree_id: Any = None,
    branch: Any = None,
) -> tuple[AgentScope | None, str | None, bool]:
    """Resolve one unambiguous memory scope; reject mixed identity contexts."""
    clean = lambda value: str(value or "").strip()
    values = {
        "task": clean(task_id),
        "session": clean(session_id),
        "clone": clean(clone_id),
        "worktree": clean(worktree_id),
        "branch": clean(branch),
    }
    identity_scopes = [(name, value) for name, value in values.items() if value]
    scope_id_value = clean(scope_id)
    root_value = clean(root)
    repository_value = clean(repository_id)
    tenant_value = clean(tenant)

    if scope is AgentScope.TASK and not values["task"] and any(
        values[name] for name in ("session", "clone", "worktree", "branch")
    ):
        return None, None, True
    if scope is AgentScope.SESSION and not values["session"] and any(
        values[name] for name in ("task", "clone", "worktree", "branch")
    ):
        return None, None, True

    if scope is None:
        if len(identity_scopes) > 1:
            return None, None, True
        if identity_scopes:
            scope = AgentScope.parse(identity_scopes[0][0], default=None)
            if scope is None:
                return None, None, True
            if not scope_id_value:
                scope_id_value = identity_scopes[0][1]
        elif root_value or repository_value:
            scope = AgentScope.REPOSITORY
        elif tenant_value:
            scope = AgentScope.SESSION
            if not scope_id_value:
                scope_id_value = tenant_value
        elif scope_id_value:
            return None, None, True

    if scope is AgentScope.SESSION and tenant_value and not scope_id_value and not values["session"]:
        return None, None, True

    expected = {
        AgentScope.TASK: values["task"],
        AgentScope.SESSION: values["session"],
        AgentScope.CLONE: values["clone"],
        AgentScope.WORKTREE: values["worktree"],
        AgentScope.BRANCH: values["branch"],
    }.get(scope, "")
    if identity_scopes:
        if scope is None:
            return None, None, True
        if expected == "":
            if scope is AgentScope.GLOBAL:
                return None, None, True
        elif scope_id_value and scope_id_value != expected:
            return None, None, True
        elif expected:
            scope_id_value = expected
        if scope is None:
            return None, None, True

    return scope, (scope_id_value or None), False


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
    *, payload: Mapping[str, Any], authorized_root: str, authorized_tenant: str
) -> tuple[str, str]:
    """Bind question storage to the root and tenant authorized for this request."""
    canonical_root = _strict_root_path(authorized_root)
    requested_root = payload.get("root")
    if requested_root not in (None, ""):
        if _strict_root_path(requested_root) != canonical_root:
            raise ValueError("root does not match authenticated scope")

    requested_tenant = payload.get("tenant")
    if requested_tenant not in (None, ""):
        if not isinstance(requested_tenant, str) or requested_tenant != authorized_tenant:
            raise ValueError("tenant does not match authenticated scope")
    return str(canonical_root), authorized_tenant


def _strict_root_path(raw: Any) -> Path:
    if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > 4096:
        raise ValueError("root is required")
    candidate = Path(raw.strip()).expanduser()
    if not candidate.is_absolute():
        raise ValueError("root must be an absolute directory")
    try:
        if any(path.is_symlink() for path in (candidate, *candidate.parents)):
            raise ValueError("symlink roots are not allowed")
        resolved = candidate.resolve(strict=True)
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


def _derive_root_tenant(principal: str, canonical_root: str, key: str) -> str:
    message = f"local-ai-root-tenant\0{principal}\0{canonical_root}".encode("utf-8")
    digest = hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"root-{digest}"


def _task_memory_scope_id(tenant: str, task_id: str) -> str:
    message = f"{tenant}\0{task_id.strip()}".encode("utf-8")
    return "task-" + hashlib.sha256(message).hexdigest()


def _telemetry_http_outcome(status: int, data: Any, path: str = "") -> tuple[bool, str, bool]:
    """Return reliability success, safe outcome category, and error-record flag."""
    payload = data if isinstance(data, dict) else {}
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
    if path == "/api/command":
        if payload.get("timed_out"):
            return False, "command_timeout", True
        return False, "command_failure", True
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


@contextmanager
def _command_peer_cancellation(
    connection: socket.socket | None, request_cancel_event: threading.Event | None = None,
):
    """Observe EOF without consuming bytes or changing the request socket."""
    cancelled = request_cancel_event if request_cancel_event is not None else threading.Event()
    if not isinstance(connection, socket.socket):
        # Embedded requests have their own lifetime event, not a TCP peer.
        yield cancelled
        return
    stopped = threading.Event()

    def watch() -> None:
        while not stopped.wait(0.05):
            try:
                readable, _, _ = select.select([connection], [], [], 0)
                if readable and connection.recv(1, socket.MSG_PEEK) == b"":
                    cancelled.set()
                    return
            except OSError as exc:
                if _is_client_disconnect(exc):
                    cancelled.set()
                return
            except ValueError:
                return

    watcher = threading.Thread(target=watch, name="command-peer-cancellation", daemon=True)
    watcher.start()
    try:
        yield cancelled
    finally:
        stopped.set()
        watcher.join(timeout=0.25)


def _is_client_disconnect(exc: BaseException) -> bool:
    """Identify a peer closing an HTTP connection before the response is written."""
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True
    # Socket error codes indicating peer disconnect across Windows & POSIX:
    #   32     – ERROR_BROKEN_PIPE  (mapped from POSIX EPIPE)
    #   103    – ECONNABORTED       – software caused connection abort (POSIX)
    #   104    – ECONNRESET         – connection reset by peer (POSIX)
    #   107    – ENOTCONN           – transport is not connected (POSIX)
    #   108    – ESHUTDOWN          – cannot send after transport endpoint shutdown (POSIX)
    #   10038  – WSAENOTSOCK        – socket closed/invalidated before send
    #   10040  – WSAEMSGSIZE        – used by some intermediaries on broken pipes in older stacks
    #   10052  – WSAENETRESET       – connection timed out / reset
    #   10053  – WSAECONNABORTED    – software caused connection abort
    #   10054  – WSAECONNRESET      – connection reset by peer
    #   10057  – WSAENOTCONN        – transport is already connected, but not connected anymore
    #   10058  – WSAESHUTDOWN       – cannot send after socket shutdown
    if not isinstance(exc, OSError):
        return False
    win_error = getattr(exc, "winerror", None)
    errno = getattr(exc, "errno", None)
    known = {32, 103, 104, 107, 108, 10038, 10040, 10052, 10053, 10054, 10057, 10058}
    if win_error in known or errno in known:
        return True
    msg = str(exc).lower()
    return any(marker in msg for marker in (
        "broken pipe",
        "connection reset",
        "connection aborted",
        "not a socket",
        "cannot send after socket shutdown",
        "winerror 10038",
        "winerror 10053",
        "winerror 10054",
        "winerror 10057",
        "winerror 10058",
    ))


class RequestBodyError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


_CANONICAL_AGENT_ACTION = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")
_AGENT_TASK_ACTIONS = frozenset({
    "create", "list", "get", "transition", "complete", "fail",
    "checkpoint", "rollback", "resume", "heartbeat", "ask", "answer",
    "cleanup_worktree", "reap_expired", "curate_dataset",
})
_AGENT_VERIFICATION_ACTIONS = frozenset({"receipt", "completion", "export"})
_AGENT_BLACKBOARD_RETIRED_FIELDS = frozenset({"key", "value", "approver", "sections", "record"})


def _agent_action_selector(payload: Mapping[str, Any], default: str | None = None) -> str | None:
    if "action" not in payload:
        return default
    action = payload["action"]
    if not isinstance(action, str) or _CANONICAL_AGENT_ACTION.fullmatch(action) is None:
        raise RequestBodyError("action must use canonical lowercase underscore syntax")
    return action


class LocalAIHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server with a hard cap on live handler threads and per-tenant rate limiting.

    ``ThreadingHTTPServer`` is otherwise unbounded: a burst of local agents or a
    misbehaving local client can create hundreds of handler threads before the model
    scheduler's own queue limits are reached. Overload is rejected immediately with a
    small 503 so the hub remains responsive to health checks and existing work.
    """

    daemon_threads = True
    # The OS bind is the cross-config singleton gate; supervisors also own
    # independent state-directory locks.
    allow_reuse_address = False
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
        # Per-tenant sliding window rate limiter
        self._rate_limit_requests: int = 600   # overridden after config load
        self._rate_limit_window: float = 60.0  # seconds
        self._rate_windows: dict[str, list[float]] = {}
        self._rate_lock = threading.Lock()
        super().__init__(server_address, handler)

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

    def configure_rate_limit(self, requests: int, window_seconds: float) -> None:
        """Apply config-driven rate limit values after server creation."""
        with self._rate_lock:
            self._rate_limit_requests = max(1, int(requests))
            self._rate_limit_window = max(1.0, float(window_seconds))

    def check_rate_limit(self, tenant: str) -> bool:
        """Return True if tenant is within the rate limit, False if exceeded."""
        if self._rate_limit_requests <= 0:
            return True  # rate limiting disabled
        now = time.monotonic()
        with self._rate_lock:
            window = self._rate_windows.setdefault(tenant, [])
            cutoff = now - self._rate_limit_window
            # Prune old entries; keep list bounded to avoid unbounded growth
            while window and window[0] < cutoff:
                window.pop(0)
            if len(window) >= self._rate_limit_requests:
                return False
            window.append(now)
            # Evict stale tenants in batches to prevent per-request churn (keep at most 4096 entries)
            if len(self._rate_windows) > 4096:
                stale = [t for t, w in self._rate_windows.items() if not w or w[-1] < cutoff]
                if len(stale) < 512:
                    stale = list(self._rate_windows.keys())[:512]
                for t in stale:
                    self._rate_windows.pop(t, None)
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
    """Parse the canonical task contract or its declared task-string shorthand."""
    contract_data = payload.get("contract")
    if contract_data is not None:
        if not isinstance(contract_data, Mapping):
            raise ValueError("contract must be an object")
        return GoalContract.from_dict(contract_data)
    return GoalContract.from_dict({
        "goal": payload.get("goal", payload.get("task", "")),
        "acceptance_criteria": payload.get("acceptance_criteria") or [],
        "scope": payload.get("scope", "task"),
        "non_goals": payload.get("non_goals") or [],
        "constraints": payload.get("constraints") or [],
        "risk_profile": payload.get("risk_profile", "normal"),
    })


class Handler(BaseHTTPRequestHandler):
    _ADMIN_ACTIONS = {
        "db.query": ({"GET", "POST"}, "/api/db/query", None),
        "debug_traces.list": ({"GET"}, "/api/debug-traces", None),
        "debug_traces.detail": ({"GET"}, "/api/debug-traces/", None),
        "config.read": ({"GET"}, "/api/config", None),
        "config.update": ({"POST"}, "/api/config/update", "update"),
        "config.reset": ({"POST"}, "/api/config/update", "reset"),
        "maintenance.optimize_db": ({"POST"}, "/api/maintenance/optimize_db", None),
        "maintenance.purge_cache": ({"POST"}, "/api/maintenance/purge_cache", None),
        "maintenance.resolve_errors": ({"POST"}, "/api/maintenance/resolve_errors", None),
        "models.list": ({"GET", "POST"}, "/api/models/manage", "list"),
        "models.pull": ({"POST"}, "/api/models/manage", "pull"),
        "models.delete": ({"POST"}, "/api/models/manage", "delete"),
        "bundle.import": ({"POST"}, "/api/bundle/import", None),
    }
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        try:
            keepalive = float(APP.config.get("server", {}).get("keepalive_timeout_seconds", 5.0)) if APP is not None else 5.0
            self.connection.settimeout(max(1.0, keepalive))
        except Exception:
            pass

    def handle(self) -> None:
        """Handle exactly one request per thread and release socket immediately."""
        self.close_connection = True
        self.handle_one_request()

    def handle_one_request(self) -> None:
        """Handle a single HTTP request, releasing idle keep-alive sockets fast."""
        try:
            keepalive = float(APP.config.get("server", {}).get("keepalive_timeout_seconds", 5.0)) if APP is not None else 5.0
            request_timeout = float(APP.config.get("server", {}).get("request_timeout_seconds", 210.0)) if APP is not None else 210.0
            try:
                self.connection.settimeout(max(1.0, keepalive))
            except OSError:
                pass
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline = ''
                self.request_version = ''
                self.command = ''
                self.send_error(414)
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            try:
                self.connection.settimeout(max(1.0, request_timeout))
            except OSError:
                pass
            if not self.parse_request():
                self.close_connection = True
                return
            mname = 'do_' + self.command
            if not hasattr(self, mname):
                self.send_error(501, f"Unsupported method ({self.command!r})")
                self.close_connection = True
                return
            method = getattr(self, mname)
            method()
            self.wfile.flush()
            # The hub does not pool request handlers. Closing every response
            # releases the handler socket immediately and prevents stale
            # keep-alive sockets from surviving shutdown or app replacement.
            self.close_connection = True
        except (socket.timeout, TimeoutError):
            self.close_connection = True
            return
        except OSError as exc:
            if _is_client_disconnect(exc):
                self.close_connection = True
                return
            raise

    def _common_headers(self, *, html: bool = False, nonce: str | None = None) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        request_headers = getattr(self, "headers", None)
        if not hasattr(request_headers, "get"):
            request_headers = {}
        header = lambda name, default="": request_headers.get(name, default)
        request_origin = str(header("Origin", "") or "").strip()
        bridge_path = str(getattr(self, "path", "")).startswith("/api/browser/") or str(getattr(self, "path", "")) == "/api/vision/review"
        requested_headers = str(header("Access-Control-Request-Headers", "") or "").lower()
        token_preflight = str(getattr(self, "command", "")) == "OPTIONS" and ("x-localai-token" in requested_headers or "authorization" in requested_headers)
        if request_origin and bridge_path and APP is not None and origin_allowed(APP.config, request_origin):
            self.send_header("Access-Control-Allow-Origin", request_origin)
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-LocalAI-Tenant, X-LocalAI-Token, Authorization")
            self.send_header("Vary", "Origin")
        elif request_origin and bridge_path and APP is not None:
            expected_token = str(APP.config.get("security", {}).get("api_token", ""))
            supplied_token = str(header("X-LocalAI-Token", "") or "")
            auth_header = str(header("Authorization", "") or "")
            if auth_header.lower().startswith("bearer "):
                supplied_token = auth_header[7:].strip()
            if expected_token and (hmac.compare_digest(supplied_token, expected_token) or token_preflight):
                self.send_header("Access-Control-Allow-Origin", request_origin)
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-LocalAI-Tenant, X-LocalAI-Token, Authorization")
                self.send_header("Vary", "Origin")
        if html:
            script_source = f"'nonce-{nonce}'" if nonce else "'none'"
            self.send_header("Content-Security-Policy", f"default-src 'none'; connect-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; script-src {script_source}; script-src-attr 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")

    def _send_html(self, status: int, html: str) -> None:
        nonce = uuid.uuid4().hex
        body = html.replace("<script>", f'<script nonce="{nonce}">', 1).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Connection", "close")
            self._common_headers(html=True, nonce=nonce)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError as exc:
            if not _is_client_disconnect(exc):
                raise
        finally:
            self.close_connection = True

    server_version = f"LocalAIHub/{__version__}"

    def _handle_db_query(self, db_name: str, sql_q: str) -> dict[str, Any]:
        sql_clean = sql_q.strip()
        if not sql_clean.upper().startswith("SELECT"):
            return {"success": False, "error": "Only read-only SELECT queries are permitted."}
        forbidden = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "REPLACE", "VACUUM", "ATTACH")
        tokens = [t.strip().upper() for t in re.split(r"[\s,()]+", sql_clean)]
        for f in forbidden:
            if f in tokens:
                return {"success": False, "error": f"Forbidden keyword in query: {f}"}
        if ";" in sql_clean.rstrip(";"):
            return {"success": False, "error": "Multi-statement queries are forbidden"}

        if APP is None:
            return {"success": False, "error": "Hub app not initialized"}
        state_dir = Path(APP.config.get("server", {}).get("state_dir", "state")).resolve()
        db_map = {
            "agent_state": state_dir / "agent_state.sqlite",
            "cache": state_dir / "cache.sqlite",
            "telemetry": state_dir / "telemetry.sqlite3",
        }
        target_db = db_map.get(db_name.lower())
        if not target_db or not target_db.is_file():
            return {"success": False, "error": f"Database not found: {db_name}"}

        def _readonly_authorizer(action: int, *_args: str | None) -> int:
            """SQLite authorizer that permits only read operations."""
            _ALLOWED = {
                sqlite3.SQLITE_SELECT,  # SELECT statements
                sqlite3.SQLITE_READ,    # Reading a column
                sqlite3.SQLITE_FUNCTION,  # Calling a function
            }
            return sqlite3.SQLITE_OK if action in _ALLOWED else sqlite3.SQLITE_DENY

        work_limit_reached = False
        try:
            uri = f"file:{target_db.as_posix()}?mode=ro"
            con = sqlite3.connect(uri, uri=True, timeout=3.0)
            try:
                con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _DB_QUERY_MAX_RESPONSE_BYTES)
                con.set_authorizer(_readonly_authorizer)
                progress_checks = 0

                def _limit_sqlite_work() -> int:
                    nonlocal progress_checks, work_limit_reached
                    progress_checks += 1
                    if progress_checks > 5000:
                        work_limit_reached = True
                        return 1
                    return 0

                con.set_progress_handler(_limit_sqlite_work, 1000)
                cur = con.cursor()
                cur.execute(sql_clean)
                col_names = [d[0] for d in cur.description] if cur.description else []
                clean_rows = []
                while len(clean_rows) < 100:
                    batch = cur.fetchmany(1)
                    if not batch:
                        break
                    clean_row = [str(item) if isinstance(item, (bytes, bytearray)) else item for item in batch[0]]
                    clean_rows.append(clean_row)
                    result = {
                        "success": True,
                        "db": db_name,
                        "columns": col_names,
                        "rows": clean_rows,
                        "count": len(clean_rows),
                    }
                    if len(json_dumps(result, separators=(",", ":")).encode("utf-8")) > _DB_QUERY_MAX_RESPONSE_BYTES:
                        return {"success": False, "error": "query result exceeded byte limit"}
                return {
                    "success": True,
                    "db": db_name,
                    "columns": col_names,
                    "rows": clean_rows,
                    "count": len(clean_rows),
                }
            finally:
                con.close()
        except sqlite3.DatabaseError as exc:
            if getattr(exc, "sqlite_errorcode", None) == getattr(sqlite3, "SQLITE_TOOBIG", -1):
                return {"success": False, "error": "query result exceeded byte limit"}
            if work_limit_reached:
                return {"success": False, "error": "query execution exceeded work limit"}
            # Sanitize error to avoid leaking internal paths
            msg = str(exc)
            if state_dir.as_posix() in msg or str(state_dir) in msg:
                msg = "query execution failed"
            return {"success": False, "error": msg}
        except Exception:
            return {"success": False, "error": "query execution failed"}
    def _handle_models_list(self) -> dict[str, Any]:
        if APP is None:
            return {"success": False, "error": "Hub app not initialized", "models": []}
        ollama_url = APP.config.get("ollama", {}).get("url", "http://localhost:11434")
        try:
            req = urllib.request.Request(f"{ollama_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                tags_data = json.loads(resp.read().decode("utf-8"))
            models = tags_data.get("models", [])
            running: dict[str, Any] = {}
            try:
                req_ps = urllib.request.Request(f"{ollama_url}/api/ps")
                with urllib.request.urlopen(req_ps, timeout=2) as resp_ps:
                    ps_data = json.loads(resp_ps.read().decode("utf-8"))
                    running = {m.get("model"): m for m in ps_data.get("models", [])}
            except Exception:
                pass

            enriched = []
            for m in models:
                name = str(m.get("name", ""))
                is_running = name in running or any(name.startswith(k) for k in running)
                run_info = running.get(name, {})
                enriched.append({
                    "name": name,
                    "size_gb": round(m.get("size", 0) / (1024**3), 2),
                    "modified_at": m.get("modified_at", ""),
                    "running": is_running,
                    "vram_mb": round(run_info.get("size_vram", 0) / (1024**2), 1) if is_running else 0,
                })
            return {"success": True, "models": enriched, "count": len(enriched)}
        except Exception as exc:
            return {"success": False, "error": f"Ollama query failed: {exc}", "models": []}

    def _handle_models_action(self, action: str, model_name: str) -> dict[str, Any]:
        if not model_name:
            return {"success": False, "error": "model parameter required"}
        if APP is None:
            return {"success": False, "error": "Hub app not initialized"}
        ollama_url = APP.config.get("ollama", {}).get("url", "http://localhost:11434")
        try:
            if action == "delete":
                req = urllib.request.Request(f"{ollama_url}/api/delete", data=json_dumps({"name": model_name}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="DELETE")
                with urllib.request.urlopen(req, timeout=5):
                    return {"success": True, "deleted": model_name}
            elif action == "pull":
                req = urllib.request.Request(f"{ollama_url}/api/pull", data=json_dumps({"name": model_name, "stream": False}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
                timeout = max(0.001, min(float(_MODEL_PULL_TIMEOUT_SECONDS), 600.0))
                deadline = time.monotonic() + timeout
                timed_out = threading.Event()
                response_holder: dict[str, Any] = {}

                def _expire_pull() -> None:
                    timed_out.set()
                    response = response_holder.get("response")
                    if response is not None:
                        try:
                            response.close()
                        except Exception:
                            pass

                timer = threading.Timer(timeout, _expire_pull)
                timer.daemon = True
                timer.start()
                try:
                    response = urllib.request.urlopen(req, timeout=max(0.001, deadline - time.monotonic()))
                    response_holder["response"] = response
                    remaining = deadline - time.monotonic()
                    if timed_out.is_set() or remaining <= 0:
                        return {"success": False, "degraded": True, "retryable": True, "error": "model pull time budget exceeded"}
                    sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                    if sock is not None:
                        sock.settimeout(remaining)
                    body = response.read(max(1, min(int(_MODEL_PULL_MAX_RESPONSE_BYTES), 4 * 1024 * 1024)) + 1)
                    if timed_out.is_set() or time.monotonic() >= deadline:
                        return {"success": False, "degraded": True, "retryable": True, "error": "model pull time budget exceeded"}
                    if len(body) > _MODEL_PULL_MAX_RESPONSE_BYTES:
                        return {"success": False, "error": "model pull response exceeded byte limit"}
                    if body:
                        payload = json_loads(body)
                        if isinstance(payload, dict) and payload.get("error"):
                            return {"success": False, "error": str(payload["error"])}
                    return {"success": True, "pulled": model_name}
                finally:
                    timer.cancel()
                    response = response_holder.get("response")
                    if response is not None:
                        try:
                            response.close()
                        except Exception:
                            pass
            return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as exc:
            timed_out_event = locals().get("timed_out")
            deadline = locals().get("deadline")
            pull_timed_out = action == "pull" and (
                bool(timed_out_event and timed_out_event.is_set())
                or (deadline is not None and time.monotonic() >= deadline)
            )
            if pull_timed_out:
                return {"success": False, "degraded": True, "retryable": True, "error": "model pull time budget exceeded"}
            return {"success": False, "error": str(exc)}

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("LOCAL_AI_HTTP_LOG") == "1":
            super().log_message(fmt, *args)

    def _begin_trace(self, path: str) -> None:
        request_id = self.headers.get("X-LocalAI-Request-ID") or uuid.uuid4().hex
        trace_id = self.headers.get("X-LocalAI-Trace-ID") or request_id
        self._trace_request_id = request_id
        self._trace_id = trace_id
        self._request_path = path
        self._request_started = time.perf_counter()
        self._telemetry_finished = False
        self._admin_operation = ""
        self._admin_audited = False
        self._admin_payload = {}
        self._trace_context_token = set_context(request_id=request_id, trace_id=trace_id, agent=self._agent(), tenant=self._tenant())
        self._debug_trace_id = ""
        self._debug_observer_token = None
        try:
            if APP is not None:
                excluded = set(APP.config.get("observability", {}).get("exclude_http_paths", []))
                if path not in MONITOR_PATHS and not path.startswith("/api/debug-traces/") and path not in excluded:
                    APP.telemetry.record_live(kind="request", event_type="request_start", tenant=self._tenant(), agent=self._agent(), request_id=request_id, trace_id=trace_id, action=path, success=True)
                    trace_store = getattr(APP, "debug_traces", None)
                    if trace_store is not None and bool(getattr(trace_store, "enabled", True)):
                        self._debug_trace_id = trace_store.start(
                            kind="api_request", tenant=self._tenant(), agent=self._agent(),
                            action=path, source="http", request_id=request_id,
                            initial_event=("request_received", {
                                "method": self.command, "path": path, "request_id": request_id,
                            }),
                        )
        except Exception:
            pass

    def _ensure_trace_request_id(self) -> str:
        request_id = getattr(self, "_trace_request_id", None)
        if not request_id:
            request_id = self.headers.get("X-LocalAI-Request-ID") or uuid.uuid4().hex
            self._trace_request_id = request_id
        return request_id

    @classmethod
    def _safe_debug_trace_request(cls, payload: Any) -> Any:
        """Normalize content for explicitly enabled local debug traces."""
        return _normalize_trace_content(payload)
    def _finish_debug_trace(self, status: int, data: Any, *, error: str = "") -> None:
        trace_id = str(getattr(self, "_debug_trace_id", "") or "")
        store = getattr(APP, "debug_traces", None) if APP is not None else None
        if not trace_id or store is None or getattr(self, "_debug_trace_finished", False):
            return
        try:
            failed = status >= 400 or (isinstance(data, dict) and data.get("success") is False)
            detail = "request failed" if failed else ""
            if isinstance(data, dict):
                data = self._safe_debug_trace_request(data)
            else:
                data = {"output": self._safe_debug_trace_request({"output": data}).get("output", "")}
            state = "failed" if failed else "done"
            update = getattr(store, "update", None)
            if callable(update):
                if getattr(self, "_debug_stream_capture", False):
                    update(trace_id, response=data)
                else:
                    update(trace_id, output=data)
                finished = store.finish(trace_id, state=state, error=detail)
            else:
                finished = store.finish(trace_id, state=state, response=data, error=detail)
            if not finished:
                # A concurrent event writer can briefly hold SQLite's write lock.
                # Do not mark the trace finished until the terminal write is real;
                # one bounded second attempt prevents successful requests from
                # being left visibly running without creating retry loops.
                time.sleep(0.02)
                if callable(update):
                    update(trace_id, output=data)
                    finished = store.finish(trace_id, state=state, error=detail)
                else:
                    finished = store.finish(trace_id, state=state, response=data, error=detail)
            if finished:
                self._debug_trace_finished = True
        except Exception:
            pass

    def _reconcile_debug_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        """Make a stale trace follow the request journal when it is terminal."""
        if not isinstance(trace, dict) or trace.get("state") not in {"queued", "running"}:
            return trace
        store = getattr(APP, "debug_traces", None) if APP is not None else None
        recovery = getattr(APP, "recovery", None) if APP is not None else None
        if store is None or recovery is None or not trace.get("request_id"):
            return trace
        try:
            journal = recovery.lookup_metadata(
                str(trace.get("request_id")),
                str(trace.get("tenant", "")),
                str(trace.get("action", "")),
                identity=str(trace.get("agent", "")),
            )
            journal_state = str((journal or {}).get("state", ""))
            if journal_state not in {"done", "failed"}:
                return trace
            error = "" if journal_state == "done" else str(trace.get("error") or "request journal finished with failure")
            store.reconcile_terminal(
                str(trace.get("trace_id", "")),
                state=journal_state,
                response=(journal or {}).get("response"),
                error=error,
            )
            trace["state"] = journal_state
            trace["error"] = error
            trace["finished_at"] = float((journal or {}).get("updated_at") or time.time())
            trace["updated_at"] = trace["finished_at"]
        except Exception:
            pass
        return trace

    def _close_trace_context(self) -> None:
        token = getattr(self, "_debug_observer_token", None)
        if token is not None:
            try:
                reset_observer(token)
            except Exception:
                pass
            self._debug_observer_token = None
        token = getattr(self, "_trace_context_token", None)
        if token is not None:
            try:
                reset_context(token)
            except Exception:
                pass
            self._trace_context_token = None

    def _tenant(self) -> str:
        bound_tenant = getattr(self, "_authorization_tenant", None)
        if bound_tenant:
            return str(bound_tenant)
        return self._principal_identity_tenant()

    def _principal_tenant(self) -> str:
        path = str(getattr(self, "path", ""))
        config = getattr(APP, "config", {}) if APP is not None else {}
        return request_principal_tenant(config if isinstance(config, dict) else {}, path)

    def _root_sandbox_enabled(self) -> bool:
        config = getattr(APP, "config", {}) if APP is not None else {}
        security = config.get("security", {}) if isinstance(config, dict) else {}
        if not isinstance(security, dict):
            security = {}
        return bool(
            security.get("allowed_roots")
            or security.get("tenant_derivation_key")
            or security.get("api_token")
        )

    def _configured_principal_tenant(self) -> str:
        config = getattr(APP, "config", {}) if APP is not None else {}
        security = config.get("security", {}) if isinstance(config, dict) else {}
        return str(
            security.get("api_token_tenant", "")
            or security.get("api_token_principal", "")
            or ""
        ).strip()

    def _principal_identity_tenant(self) -> str:
        authenticated_tenant = getattr(self, "_authorization_tenant", None)
        if authenticated_tenant and not getattr(self, "_authorization_root", None):
            self._authenticated_principal_tenant = str(authenticated_tenant).strip()
        authenticated_tenant = getattr(self, "_authenticated_principal_tenant", None)
        if authenticated_tenant:
            return str(authenticated_tenant).strip()
        return self._configured_principal_tenant() or self._principal_tenant()

    def _bind_root_tenant(
        self,
        root: Any,
        tenant_values: list[Any] | tuple[Any, ...] = (),
        *,
        allow_principal_header: bool = False,
        require_configured_principal: bool = False,
        ignore_transport_tenant: bool = False,
    ) -> tuple[str, str] | None:
        supplied_tenants = {
            str(value).strip()
            for value in tenant_values
            if value is not None and str(value).strip()
        }
        if len(supplied_tenants) > 1:
            self._send(403, {
                "success": False,
                "error": "tenant binding is ambiguous",
                "error_code": "tenant_binding_mismatch",
                "terminal": True,
                "retryable": False,
            })
            return None
        if isinstance(root, str) and root.strip():
            try:
                candidate = Path(root.strip()).expanduser()
                if candidate.is_absolute() and not candidate.exists():
                    self._send(403, {"success": False, "error": "root is missing, invalid, or not allowed", "error_code": "root_not_allowed", "terminal": True, "retryable": False})
                    return None
            except (OSError, RuntimeError, ValueError):
                pass
        if not self._root_sandbox_enabled():
            try:
                canonical = _strict_root_path(root)
                header_tenant = self.headers.get("X-LocalAI-Tenant")
                principal = self._tenant()
                effective = principal
                if not ignore_transport_tenant and any(
                    value is not None and str(value).strip() != principal
                    for value in (*tenant_values, header_tenant)
                ):
                    self._send(403, {"success": False, "error": "tenant does not match authenticated principal", "error_code": "tenant_binding_mismatch", "terminal": True, "retryable": False})
                    return None
            except (OSError, TypeError, ValueError):
                self._send(403, {"success": False, "error": "root is missing, invalid, or not allowed", "error_code": "root_not_allowed", "terminal": True, "retryable": False})
                return None
            self._authorization_root = str(canonical)
            self._authorization_tenant = effective
            return str(canonical), effective
        config = getattr(APP, "config", {}) if APP is not None else {}
        security = config.get("security", {}) if isinstance(config, dict) else {}
        try:
            canonical = _strict_root_path(root)
            if not _root_is_allowed(canonical, security.get("allowed_roots", [])):
                raise ValueError("root is not allowed")
            if require_configured_principal and not self._configured_principal_tenant():
                raise ValueError("configured principal tenant is unavailable")
            principal = self._tenant()
            key = str(security.get("tenant_derivation_key") or security.get("api_token") or "")
            if not key:
                raise ValueError("tenant derivation secret is unavailable")
            effective = _derive_root_tenant(principal, str(canonical), key)
        except (OSError, TypeError, ValueError):
            self._send(403, {"success": False, "error": "root is missing, invalid, or not allowed", "error_code": "root_not_allowed", "terminal": True, "retryable": False})
            return None
        headers = [self.headers.get("X-LocalAI-Tenant")]
        header_mismatch = any(
            value is not None
            and str(value).strip() != effective
            and not (allow_principal_header and str(value).strip() == principal)
            for value in headers
        )
        value_mismatch = any(value is not None and str(value).strip() != effective for value in tenant_values)
        if not ignore_transport_tenant and (header_mismatch or value_mismatch):
            self._send(403, {"success": False, "error": "tenant does not match authenticated root scope", "error_code": "tenant_binding_mismatch", "terminal": True, "retryable": False})
            return None
        self._authorization_root = str(canonical)
        self._authorization_tenant = effective
        return str(canonical), effective

    def _bind_principal_tenant(self, tenant_values: list[Any] | tuple[Any, ...] = ()) -> bool:
        principal = self._principal_identity_tenant()
        header_tenants = [self.headers.get("X-LocalAI-Tenant")]
        requested = [*header_tenants, *tenant_values]
        if any(value is not None and str(value).strip() != principal for value in requested):
            self._send(403, {"success": False, "error": "tenant does not match authenticated principal", "error_code": "tenant_binding_mismatch", "terminal": True, "retryable": False})
            return False
        self._authorization_tenant = principal
        return True

    def _reject_legacy_tenant_header(self) -> bool:
        headers = getattr(self, "headers", None)
        if headers is None or headers.get("X-Tenant-ID") is None:
            return True
        self._send(400, {
            "success": False,
            "error": "X-Tenant-ID is unsupported; use X-LocalAI-Tenant",
            "error_code": "unsupported_tenant_header",
            "terminal": True,
            "retryable": False,
        })
        return False

    def _agent_action_or_error(self, payload: dict[str, Any], default: str) -> str | None:
        try:
            return _agent_action_selector(payload, default)
        except RequestBodyError as exc:
            self._send(exc.status, {
                "success": False,
                "error": str(exc),
                "terminal": True,
                "retryable": False,
            })
            return None

    def _bind_memory_payload(self, payload: dict[str, Any]) -> bool:
        record = payload.get("record") if isinstance(payload.get("record"), dict) else {}
        payload_provenance = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
        record_provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
        containers = (payload, record, payload_provenance, record_provenance)
        action = self._agent_action_or_error(payload, "")
        if action is None:
            return False
        if action == "record":
            # The outer request root is the trust anchor for creation. Nested
            # provenance is evidence to sanitize, not a second authority.
            record_root = record.get("root")
            trusted_root = payload.get("root") or record_root
            roots = [trusted_root] if trusted_root not in (None, "") else []
        else:
            roots = [item.get("root") for item in containers if item.get("root") not in (None, "")]
        tenant_values = [item.get("tenant") for item in containers if item.get("tenant") not in (None, "")]
        try:
            scope = _parse_memory_scope(payload.get("scope") or record.get("scope"))
        except ValueError as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False})
            return False
        if action == "delete" and scope is AgentScope.WORKTREE:
            self._send(403, {"success": False, "error": "worktree-scoped memory delete requires verified worktree scope", "terminal": True, "retryable": False})
            return False
        has_task_identity = any(
            item.get(key)
            for item in (payload, record)
            for key in ("task_id", "repository_id", "clone_id", "worktree_id", "branch")
        )

        if roots:
            bound = self._bind_root_tenant(
                roots[0],
                [] if action == "record" else tenant_values,
                allow_principal_header=True,
                require_configured_principal=True,
            )
            if bound is None:
                return False
            canonical_root, effective_tenant = bound
            try:
                if any(str(_strict_root_path(value)) != canonical_root for value in roots[1:]):
                    raise ValueError("conflicting roots")
            except (OSError, TypeError, ValueError):
                self._send(403, {"success": False, "error": "root identity mismatch", "error_code": "root_not_allowed", "terminal": True, "retryable": False})
                return False
            payload["root"] = canonical_root
            payload["tenant"] = effective_tenant
            self._authorization_root = str(canonical_root)
            if record:
                record["root"] = canonical_root
                record["tenant"] = effective_tenant
            for provenance in (payload_provenance, record_provenance):
                if provenance:
                    provenance["root"] = canonical_root
                    provenance["tenant"] = effective_tenant
            task_ids = [
                item.get("task_id")
                for item in (payload, record, payload_provenance, record_provenance)
                if item.get("task_id") not in (None, "")
            ]
            if scope is AgentScope.TASK and not task_ids:
                task_ids = [payload.get("scope_id") or record.get("scope_id")]
            if not self._validate_memory_task_identity(canonical_root, effective_tenant, task_ids):
                return False
            if scope is AgentScope.SESSION:
                for item in (payload, record):
                    if item:
                        session_identity = str(item.get("session_id") or item.get("scope_id") or effective_tenant).strip()
                        if item.get("session_id") and item.get("scope_id") and str(item["session_id"]).strip() != str(item["scope_id"]).strip():
                            self._send(400, {"success": False, "error": "conflicting session identity", "terminal": True, "retryable": False})
                            return False
                        item.update(scope_id=session_identity, session_id=session_identity)
            return True

        if scope in {AgentScope.TASK, AgentScope.REPOSITORY, AgentScope.CLONE, AgentScope.WORKTREE, AgentScope.BRANCH} or has_task_identity:
            self._send(400, {"success": False, "error": "root is required for repository or task memory", "error_code": "root_required", "terminal": True, "retryable": False})
            return False
        if not self._bind_principal_tenant([] if action == "record" else tenant_values):
            return False
        principal = self._authorization_tenant or self._principal_tenant()
        security = (getattr(APP, "config", {}) or {}).get("security", {}) if APP is not None else {}
        shared_token_configured = bool(security.get("api_token")) if isinstance(security, dict) else False
        for key in ("task_id", "clone_id", "worktree_id", "branch"):
            if any(item.get(key) not in (None, "", principal) for item in (payload, record)):
                self._send(403, {"success": False, "error": "memory identity does not match authenticated principal", "error_code": "tenant_binding_mismatch", "terminal": True, "retryable": False})
                return False
        for item in (payload, record, payload_provenance, record_provenance):
            if item:
                item["tenant"] = principal
        for item in (payload, record):
            if not item:
                continue
            if action != "delete" and (
                scope is None or (scope is AgentScope.GLOBAL and shared_token_configured)
            ):
                item["scope"] = AgentScope.SESSION.value
            if scope is AgentScope.SESSION or item.get("scope") == AgentScope.SESSION.value:
                session_identity = str(item.get("session_id") or item.get("scope_id") or principal).strip()
                if item.get("session_id") and item.get("scope_id") and str(item["session_id"]).strip() != str(item["scope_id"]).strip():
                    self._send(400, {"success": False, "error": "conflicting session identity", "terminal": True, "retryable": False})
                    return False
                item.update(scope=AgentScope.SESSION.value, scope_id=session_identity, session_id=session_identity)
        return True

    def _bind_memory_query(self, query: dict[str, list[str]]) -> bool:
        root_values = query.get("root", [])
        tenant_values = query.get("tenant", [])
        try:
            scope = _parse_memory_scope((query.get("scope") or [None])[0])
        except ValueError as exc:
            self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False})
            return False
        scoped_values = [query.get(name, [""])[0] for name in ("task_id", "repository_id", "clone_id", "worktree_id", "branch")]
        if root_values and root_values[0]:
            # In sandboxed mode tenant is derived from authenticated principal + root;
            # a query parameter is only an untrusted filter and must not become identity.
            tenant_bindings = (
                ()
                if self._root_sandbox_enabled() or self._configured_principal_tenant()
                else tenant_values
            )
            bound = self._bind_root_tenant(
                root_values[0],
                tenant_bindings,
                allow_principal_header=True,
                require_configured_principal=True,
            )
            if bound is None:
                return False
            canonical_root, effective_tenant = bound
            try:
                if any(str(_strict_root_path(value)) != canonical_root for value in root_values[1:] if value):
                    raise ValueError("conflicting roots")
            except (OSError, TypeError, ValueError):
                self._send(403, {"success": False, "error": "root identity mismatch", "error_code": "root_not_allowed", "terminal": True, "retryable": False})
                return False
            query["root"] = [canonical_root]
            query["tenant"] = [effective_tenant]
            self._authorization_root = canonical_root
            task_ids = [value for value in query.get("task_id", []) if value]
            if scope is AgentScope.TASK and not task_ids:
                task_ids = [((query.get("scope_id") or [""])[0])]
            if not self._validate_memory_task_identity(canonical_root, effective_tenant, task_ids):
                return False
            if scope is AgentScope.SESSION:
                session_id = (query.get("session_id") or [None])[0]
                scope_id = (query.get("scope_id") or [None])[0]
                if session_id and scope_id and session_id != scope_id:
                    self._send(400, {"success": False, "error": "conflicting session identity", "terminal": True, "retryable": False})
                    return False
                session_identity = session_id or scope_id or effective_tenant
                query.update(scope_id=[session_identity], session_id=[session_identity])
            return True
        if scope in {AgentScope.TASK, AgentScope.REPOSITORY, AgentScope.CLONE, AgentScope.WORKTREE, AgentScope.BRANCH} or any(str(value or "").strip() for value in scoped_values):
            self._send(400, {"success": False, "error": "root is required for repository or task memory", "error_code": "root_required", "terminal": True, "retryable": False})
            return False
        if not self._bind_principal_tenant(tenant_values):
            return False
        principal = self._authorization_tenant or self._principal_tenant()
        security = (getattr(APP, "config", {}) or {}).get("security", {}) if APP is not None else {}
        shared_token_configured = bool(security.get("api_token")) if isinstance(security, dict) else False
        if scope is None:
            session_id = (query.get("session_id") or [None])[0]
            scope_id = (query.get("scope_id") or [None])[0]
            if session_id and scope_id and session_id != scope_id:
                self._send(400, {"success": False, "error": "conflicting session identity", "terminal": True, "retryable": False})
                return False
            session_identity = session_id or scope_id or principal
            query.update(scope=[AgentScope.SESSION.value], scope_id=[session_identity], session_id=[session_identity], tenant=[principal])
        elif scope is AgentScope.GLOBAL and shared_token_configured:
            query.update(scope=[AgentScope.SESSION.value], scope_id=[principal], session_id=[principal], tenant=[principal])
        else:
            query["tenant"] = [principal]
        return True

    def _bind_task_payload(self, payload: dict[str, Any]) -> bool:
        bound = self._bind_root_tenant(
            payload.get("root"),
            allow_principal_header=True,
            require_configured_principal=True,
        )
        if bound is None:
            return False
        canonical_root, effective_tenant = bound
        self._authorization_root = str(canonical_root)
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        supplied_root = context.get("repository_id")
        if supplied_root:
            try:
                if str(_strict_root_path(supplied_root)) != canonical_root:
                    raise ValueError("root identity mismatch")
            except (OSError, TypeError, ValueError):
                self._send(403, {"success": False, "error": "task root identity mismatch", "error_code": "root_not_allowed", "terminal": True, "retryable": False})
                return False
        if context.get("session_id") not in (None, "", effective_tenant):
            self._send(403, {"success": False, "error": "task tenant identity mismatch", "error_code": "tenant_binding_mismatch", "terminal": True, "retryable": False})
            return False
        context.update(repository_id=canonical_root, session_id=effective_tenant)
        payload["context"] = context
        payload["root"] = canonical_root
        payload["tenant"] = effective_tenant
        if payload.get("repo_root"):
            try:
                if str(_strict_root_path(payload["repo_root"])) != canonical_root:
                    raise ValueError("root identity mismatch")
            except (OSError, TypeError, ValueError):
                self._send(403, {"success": False, "error": "task root identity mismatch", "error_code": "root_not_allowed", "terminal": True, "retryable": False})
                return False
        payload["repo_root"] = canonical_root
        return True

    def _bind_incident_payload(self, payload: dict[str, Any]) -> bool:
        """Bind incident requests to an authenticated repository/tenant scope."""
        bound = self._bind_root_tenant(
            payload.get("root"),
            [payload.get("tenant")],
            allow_principal_header=True,
            require_configured_principal=True,
        )
        if bound is None:
            return False
        canonical_root, effective_tenant = bound
        payload["root"] = canonical_root
        payload["tenant"] = effective_tenant
        self._authorization_root = str(canonical_root)
        self._authorization_tenant = str(effective_tenant)
        return True

    def _bind_swarm_payload(self, payload: dict[str, Any]) -> bool:
        bound = self._bind_root_tenant(
            payload.get("root"),
            [payload.get("tenant")],
            allow_principal_header=True,
            require_configured_principal=True,
        )
        if bound is None:
            return False
        canonical_root, effective_tenant = bound
        payload["root"] = canonical_root
        payload["tenant"] = effective_tenant
        self._authorization_root = str(canonical_root)
        self._authorization_tenant = str(effective_tenant)
        return True

    def _bind_swarm_query(self, query: dict[str, list[str]]) -> bool:
        bound = self._bind_root_tenant(
            (query.get("root") or [None])[0],
            query.get("tenant", []),
            allow_principal_header=True,
            require_configured_principal=True,
        )
        if bound is None:
            return False
        query["root"], query["tenant"] = [[bound[0]], [bound[1]]]
        self._authorization_root = str(bound[0])
        self._authorization_tenant = str(bound[1])
        return True

    def _bind_repository_root_payload(self, payload: dict[str, Any]) -> bool:
        """Require authenticated repository scope for direct file mutations."""
        bound = self._bind_root_tenant(
            payload.get("root"),
            [payload.get("tenant")],
            allow_principal_header=True,
            require_configured_principal=True,
        )
        if bound is None:
            return False
        canonical_root, effective_tenant = bound
        payload["root"] = canonical_root
        payload["tenant"] = effective_tenant
        self._authorization_root = str(canonical_root)
        self._authorization_tenant = str(effective_tenant)
        return True

    def _bind_repository_root_query(self, query: dict[str, list[str]]) -> bool:
        """Require authenticated repository scope for read-only repo queries."""
        raw_root = (query.get("root") or [""])[0]
        if not isinstance(raw_root, str) or not raw_root.strip() or raw_root.strip() == ".":
            self._send(400, {
                "success": False,
                "error": "root is required for repository queries",
                "error_code": "root_required",
                "terminal": True,
                "retryable": False,
            })
            return False
        bound = self._bind_root_tenant(
            raw_root,
            query.get("tenant", []),
            allow_principal_header=True,
            require_configured_principal=True,
        )
        if bound is None:
            return False
        canonical_root, effective_tenant = bound
        try:
            if any(
                value and str(_strict_root_path(value)) != canonical_root
                for value in query.get("root", [])[1:]
            ):
                raise ValueError("conflicting roots")
        except (OSError, TypeError, ValueError):
            self._send(403, {
                "success": False,
                "error": "root identity mismatch",
                "error_code": "root_not_allowed",
                "terminal": True,
                "retryable": False,
            })
            return False
        query["root"] = [canonical_root]
        query["tenant"] = [effective_tenant]
        self._authorization_root = canonical_root
        self._authorization_tenant = effective_tenant
        return True

    def _bind_multi_repository_query(self, query: dict[str, list[str]]) -> bool:
        """Require explicit canonical roots and one tenant for cross-repo GETs."""
        roots = [str(value).strip() for value in query.get("roots", []) if str(value).strip()]
        if not roots:
            self._send(400, {
                "success": False,
                "error": "explicit roots list is required",
                "error_code": "roots_required",
                "terminal": True,
                "retryable": False,
            })
            return False
        payload: dict[str, Any] = {
            "roots": roots,
            "tenant": (query.get("tenant") or [None])[0],
        }
        if not self._bind_multi_repository_payload(payload):
            return False
        query["roots"] = [str(root) for root in payload["roots"]]
        query["tenant"] = [str(payload["tenant"])]
        return True

    def _bind_multi_repository_payload(self, payload: dict[str, Any], *, cross_repo_contract: bool = False) -> bool:
        """Validate every explicit root in a cross-repository request."""
        if cross_repo_contract:
            names = ("backend_root", "frontend_root")
            raw_roots = [payload.get(name) for name in names]
        else:
            names = ("roots",)
            raw_roots = [payload.get("roots")]
        if cross_repo_contract:
            if any(not isinstance(root, str) or not root.strip() for root in raw_roots):
                self._send(400, {"success": False, "error": "explicit backend_root and frontend_root are required", "terminal": True, "retryable": False})
                return False
            roots = list(raw_roots)
        else:
            if not isinstance(raw_roots[0], list) or not raw_roots[0]:
                self._send(400, {"success": False, "error": "explicit roots list is required", "terminal": True, "retryable": False})
                return False
            roots = raw_roots[0]
        canonical: list[str] = []
        first_tenant: str | None = None
        for root in roots:
            bound = self._bind_root_tenant(
                root,
                [payload.get("tenant")],
                allow_principal_header=True,
                require_configured_principal=True,
            )
            if bound is None:
                return False
            canonical.append(bound[0])
            if first_tenant is None:
                first_tenant = bound[1]
        if cross_repo_contract:
            payload["backend_root"], payload["frontend_root"] = canonical
        else:
            payload["roots"] = canonical
            origin_root = payload.get("origin_root")
            if origin_root not in (None, ""):
                bound_origin = self._bind_root_tenant(
                    origin_root,
                    [payload.get("tenant")],
                    allow_principal_header=True,
                    require_configured_principal=True,
                )
                if bound_origin is None:
                    return False
                if bound_origin[0] not in canonical:
                    self._send(400, {"success": False, "error": "origin_root must be one of the explicit roots", "terminal": True, "retryable": False})
                    return False
                payload["origin_root"] = bound_origin[0]
        self._authorization_root = canonical[0]
        self._authorization_tenant = first_tenant
        return True

    @staticmethod
    def _task_matches_request(task: Any, root: str, tenant: str) -> bool:
        context = getattr(task, "context", None)
        try:
            if context is None or not root or not tenant:
                return False
            task_root = str(getattr(context, "repository_id", "") or "").strip()
            task_tenant = str(getattr(context, "session_id", "") or "").strip()
            return bool(task_root and task_tenant) and (
                str(_strict_root_path(task_root)) == str(_strict_root_path(root))
                and task_tenant == tenant
            )
        except (OSError, TypeError, ValueError):
            return False

    def _request_task(self, task_id: str, root: str, tenant: str) -> Any | None:
        task = APP.agent_tasks.get(task_id) if APP is not None and getattr(APP, "agent_tasks", None) else None
        if task is None:
            self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False})
            return None
        if self._root_sandbox_enabled() and not self._task_matches_request(task, root, tenant):
            self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False})
            return None
        return task

    def _require_scoped_task(self, task_id: str) -> Any | None:
        root = str(getattr(self, "_authorization_root", "") or "")
        tenant = str(getattr(self, "_authorization_tenant", "") or "")
        if not root or not tenant:
            return True
        return self._request_task(str(task_id or "").strip(), root, tenant)

    def _bind_context_payload(self, payload: dict[str, Any]) -> bool:
        if not self._root_sandbox_enabled():
            return True
        task_id = str(payload.get("task_id", "") or "").strip()
        if not task_id:
            self._send(400, {"success": False, "error": "task_id is required for context compilation", "terminal": True, "retryable": False})
            return False
        task = APP.agent_tasks.get(task_id) if APP is not None and getattr(APP, "agent_tasks", None) else None
        context = getattr(task, "context", None) if task is not None else None
        task_root = str(getattr(context, "repository_id", "") or "")
        if not task_root:
            self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False})
            return False
        for name in ("root", "repository_id"):
            supplied = payload.get(name)
            if supplied:
                try:
                    if str(_strict_root_path(supplied)) != str(_strict_root_path(task_root)):
                        raise ValueError("task root mismatch")
                except (OSError, TypeError, ValueError):
                    self._send(403, {"success": False, "error": "context root does not match task", "terminal": True, "retryable": False})
                    return False
        tenant_values = [payload.get("tenant"), payload.get("session_id")]
        bound = self._bind_root_tenant(
            task_root,
            tenant_values,
            allow_principal_header=True,
            require_configured_principal=True,
        )
        if bound is None:
            return False
        canonical_root, effective_tenant = bound
        if not self._task_matches_request(task, canonical_root, effective_tenant):
            self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False})
            return False
        payload.update(
            root=canonical_root,
            tenant=effective_tenant,
            repository_id=canonical_root,
            session_id=effective_tenant,
            _scoped_task_only=True,
        )
        return True

    def _bind_task_event_query(self, query: dict[str, list[str]]) -> bool:
        stream_id = str((query.get("stream_id") or [""])[0]).strip()
        if not stream_id.startswith("task:") or not stream_id[5:]:
            self._send(403, {"success": False, "error": "only task-scoped event streams are available", "terminal": True, "retryable": False})
            return False
        task_id = stream_id[5:]
        supplied_task_id = str((query.get("task_id") or [""])[0]).strip()
        if supplied_task_id and supplied_task_id != task_id:
            self._send(403, {"success": False, "error": "event stream task identity mismatch", "terminal": True, "retryable": False})
            return False
        bound = self._bind_root_tenant(
            (query.get("root") or [None])[0],
            query.get("tenant", []),
            allow_principal_header=True,
            require_configured_principal=True,
        )
        if bound is None:
            return False
        canonical_root, effective_tenant = bound
        query["root"] = [canonical_root]
        query["tenant"] = [effective_tenant]
        return self._validate_memory_task_identity(canonical_root, effective_tenant, [task_id])

    def _bind_task_event_payload(self, payload: dict[str, Any]) -> bool:
        action = self._agent_action_or_error(payload, "export")
        if action is None:
            return False
        if action != "export":
            self._send(403, {"success": False, "error": "global event import is unavailable through root-scoped access", "terminal": True, "retryable": False})
            return False
        payload["action"] = "export"
        stream_id = str(payload.get("stream_id", "") or "").strip()
        if not stream_id.startswith("task:") or not stream_id[5:]:
            self._send(403, {"success": False, "error": "only task-scoped event export is available", "terminal": True, "retryable": False})
            return False
        task_id = stream_id[5:]
        if payload.get("task_id") not in (None, "", task_id):
            self._send(403, {"success": False, "error": "event stream task identity mismatch", "terminal": True, "retryable": False})
            return False
        bound = self._bind_root_tenant(
            payload.get("root"),
            [payload.get("tenant")],
            allow_principal_header=True,
            require_configured_principal=True,
        )
        if bound is None:
            return False
        canonical_root, effective_tenant = bound
        if not self._validate_memory_task_identity(canonical_root, effective_tenant, [task_id]):
            return False
        payload.update(root=canonical_root, tenant=effective_tenant, task_id=task_id)
        return True

    @staticmethod
    def _task_board_id_allowed(board_id: str, task_id: str) -> bool:
        return board_id in {task_id, f"task:{task_id}"}

    def _bind_task_board_query(self, query: dict[str, list[str]]) -> bool:
        task_id = str((query.get("task_id") or [""])[0]).strip()
        if not task_id:
            self._send(400, {"success": False, "error": "task_id is required for blackboard access", "terminal": True, "retryable": False})
            return False
        bound = self._bind_root_tenant(
            (query.get("root") or [None])[0],
            query.get("tenant", []),
            allow_principal_header=True,
            require_configured_principal=True,
        )
        if bound is None:
            return False
        canonical_root, effective_tenant = bound
        if not self._validate_memory_task_identity(canonical_root, effective_tenant, [task_id]):
            return False
        board_id = str((query.get("board_id") or [task_id])[0]).strip()
        if not self._task_board_id_allowed(board_id, task_id):
            self._send(403, {"success": False, "error": "blackboard access requires task-owned board id", "terminal": True, "retryable": False})
            return False
        query.update(root=[canonical_root], tenant=[effective_tenant], board_id=[board_id], task_id=[task_id])
        return True

    def _bind_task_board_payload(self, payload: dict[str, Any]) -> bool:
        retired_fields = sorted(_AGENT_BLACKBOARD_RETIRED_FIELDS.intersection(payload))
        if retired_fields:
            fields = ", ".join(retired_fields)
            self._send(400, {
                "success": False,
                "error": f"unsupported blackboard field(s): {fields}",
                "terminal": True,
                "retryable": False,
            })
            return False
        action = self._agent_action_or_error(payload, "get")
        if action is None:
            return False
        if action == "list":
            self._send(403, {"success": False, "error": "global blackboard listing is unavailable through root-scoped access", "terminal": True, "retryable": False})
            return False
        if action not in {"update", "get", "merge", "delete"}:
            self._send(400, {"success": False, "error": "unknown blackboard action", "terminal": True, "retryable": False})
            return False
        if not self._bind_task_payload(payload):
            return False
        task_id = str(payload.get("task_id", "") or "").strip()
        if self._require_scoped_task(task_id) is None:
            return False
        board_id = str(payload.get("board_id", task_id)).strip()
        if not self._task_board_id_allowed(board_id, task_id):
            self._send(403, {"success": False, "error": "blackboard access requires task-owned board id", "terminal": True, "retryable": False})
            return False
        payload["board_id"] = board_id
        payload["action"] = action
        return True

    def _bind_workspace_memory_payload(self, path: str, payload: dict[str, Any]) -> bool:
        is_global_delete = (
            path == "/api/memory/delete"
            and payload.get("scope") == "global"
        )
        bound = self._bind_root_tenant(
            payload.get("root"),
            [payload.get("tenant")],
            allow_principal_header=True,
            require_configured_principal=True,
            ignore_transport_tenant=is_global_delete,
        )
        if bound is None:
            return False
        canonical_root, effective_tenant = bound
        payload["root"] = canonical_root
        payload["tenant"] = effective_tenant
        if path in {"/api/memory/put", "/api/memory/get", "/api/memory/search"}:
            self._send(403, {"success": False, "error": "workspace-shared memory access is unavailable through this tenant-scoped endpoint", "terminal": True, "retryable": False})
            return False
        return True

    def _validate_memory_task_identity(self, root: str, tenant: str, task_ids: list[Any]) -> bool:
        supplied = {str(value).strip() for value in task_ids if value not in (None, "")}
        if len(supplied) > 1:
            self._send(400, {"success": False, "error": "conflicting memory task identities", "terminal": True, "retryable": False})
            return False
        if supplied and self._request_task(next(iter(supplied)), root, tenant) is None:
            return False
        return True

    def _bound_memory_scope_id(self, scope: AgentScope | None, scope_id: Any, task_id: Any = None) -> str | None:
        tenant = getattr(self, "_authorization_tenant", None)
        if not tenant:
            return str(scope_id or task_id or "").strip() or None
        if scope is AgentScope.TASK:
            raw_task_id = str(task_id or scope_id or "").strip()
            return _task_memory_scope_id(tenant, raw_task_id) if raw_task_id else None
        if scope is AgentScope.SESSION:
            return str(scope_id).strip() if scope_id not in (None, "") else tenant
        return str(scope_id).strip() if scope_id not in (None, "") else None

    def _get_bound_memory_record(self, payload: dict[str, Any], record_id: str) -> Any | None:
        scope_val = _parse_memory_scope(payload.get("scope"))
        scope_id_val = payload.get("scope_id")
        requested_root = payload.get("root")
        project_identity = self._memory_project_identity(requested_root)
        if requested_root and project_identity is None:
            return None
        root_val, repository_id_val = project_identity or (None, None)
        explicit_tenant = self.headers.get("X-LocalAI-Tenant")
        raw_tenant = (
            self._tenant()
            if scope_val is AgentScope.GLOBAL
            else payload.get("tenant") or (str(explicit_tenant).strip() if explicit_tenant else None) or self._tenant()
        )
        tenant_val = str(raw_tenant).strip() if raw_tenant else None
        task_id_val = payload.get("task_id")
        session_id_val = payload.get("session_id")
        clone_id_val = payload.get("clone_id")
        worktree_id_val = payload.get("worktree_id")
        branch_val = payload.get("branch")
        scope_val, scope_id_val, ambiguous_scope = _resolve_memory_scope(
            scope_val,
            scope_id=scope_id_val,
            root=root_val,
            repository_id=repository_id_val,
            tenant=tenant_val,
            task_id=task_id_val,
            session_id=session_id_val,
            clone_id=clone_id_val,
            worktree_id=worktree_id_val,
            branch=branch_val,
        )
        if ambiguous_scope:
            return None
        original_scope_none = scope_val is None
        if scope_val is None:
            scope_val = AgentScope.SESSION
        scope_id_val = self._bound_memory_scope_id(scope_val, scope_id_val, task_id_val)
        if scope_val is AgentScope.TASK:
            task_id_val = scope_id_val
        elif scope_val is AgentScope.SESSION:
            session_id_val = scope_id_val
        rec = APP.agent_memory.get(
            record_id,
            scope=scope_val,
            scope_id=str(scope_id_val) if scope_id_val is not None else None,
            root=str(root_val) if root_val else None,
            repository_id=str(repository_id_val) if repository_id_val else None,
            tenant=str(tenant_val) if tenant_val else None,
            task_id=str(task_id_val) if task_id_val else None,
            session_id=str(session_id_val) if session_id_val else None,
            clone_id=str(clone_id_val) if clone_id_val else None,
            worktree_id=str(worktree_id_val) if worktree_id_val else None,
            branch=str(branch_val) if branch_val else None,
        )
        if rec is None and original_scope_none:
            rec = APP.agent_memory.get(record_id, scope=AgentScope.GLOBAL)
        return rec

    def _memory_project_identity(self, requested_root: Any) -> tuple[str, str] | None:
        """Resolve memory project identity from server project configuration."""
        if not requested_root:
            return ("", "")
        try:
            if APP is None:
                return None
            import sys
            project_config_module = sys.modules.get("local_ai_hub.project_config")
            if project_config_module is None:
                from . import project_config as project_config_module
            resolve_project_context = getattr(project_config_module, "resolve_project_context")
            from .state_paths import configured_state_dir

            context = resolve_project_context(requested_root, configured_state_dir(APP.config))
            root = str(Path(context.root).resolve(strict=True))
            repository_id = str(getattr(context, "coordination_id", "") or "").strip()
            return root, repository_id
        except Exception:
            return None

    def _tenant_binding_allowed(self) -> bool:
        if APP is None:
            return True
        path = urlparse(str(getattr(self, "path", ""))).path
        security = APP.config.get("security", {})
        bound_tenant = getattr(self, "_authorization_tenant", None)
        requested_tenant = self.headers.get("X-LocalAI-Tenant")
        if path in {"/api/agent-state/memory", "/api/agent-state/tasks"} or path.startswith("/api/memory/"):
            # Root-scoped routes validate any client tenant after resolving request root.
            return True
        if bound_tenant and requested_tenant and str(requested_tenant).strip() != str(bound_tenant):
            self._send(403, {"success": False, "error": "user credential is bound to its configured tenant", "error_code": "tenant_binding_mismatch", "terminal": True, "retryable": False})
            return False
        if not (path.startswith("/api/browser/") or path == "/api/vision/review") or not security.get("api_token"):
            return True
        configured = str(APP.config.get("browser_bridge", {}).get("tenant", "http-default") or "http-default")
        requested = self.headers.get("X-LocalAI-Tenant")
        if requested and str(requested).strip() != configured:
            self._send(403, {"success": False, "error": "browser bridge tenant is bound to its configured token tenant", "error_code": "tenant_binding_mismatch", "terminal": True, "retryable": False})
            return False
        return True

    def _agent(self) -> str:
        return self.headers.get("X-LocalAI-Agent") or "generic"

    def _authorization_permission(self) -> str:
        path = urlparse(str(getattr(self, "path", ""))).path
        method = str(getattr(self, "command", "GET")).upper()
        if (
            path.startswith("/api/admin/")
            or path.startswith("/api/maintenance/")
            or (path == "/api/mode" and method not in {"GET", "HEAD"})
        ):
            return "admin"
        if method in {"GET", "HEAD"}:
            return "monitor" if path in MONITOR_PATHS else "read"
        return "write"

    def _required_permission(self) -> str:
        path = urlparse(str(getattr(self, "path", ""))).path.rstrip("/") or "/"
        method = str(getattr(self, "command", "GET")).upper()
        read_only = method in {"GET", "HEAD"}
        if path.startswith("/api/agent-state/"):
            return "agent_tasks:read" if read_only else "agent_tasks:write"
        if (
            path.startswith("/api/admin/")
            or path.startswith("/api/maintenance/")
            or (path == "/api/mode" and not read_only)
        ):
            return "admin:read" if read_only else "admin:write"
        if path in {"/", "/dashboard", "/api/metrics", "/api/status"}:
            return "dashboard:read"
        return "api:read" if read_only else "api:write"

    def _loopback_client(self) -> bool:
        try:
            address = str(self.client_address[0]).split("%", 1)[0]
            return ipaddress.ip_address(address).is_loopback
        except (AttributeError, IndexError, TypeError, ValueError):
            return False

    def _authorized(self, action: str | None = None, *, permission: str | None = None) -> bool:
        self._authorization_actor = "unrecognized"
        self._authorization_root = None
        self._authorization_tenant = None
        self._authenticated_principal_tenant = None
        self._authorization_permissions = frozenset()
        self._authorization_status = 401
        if APP is None:
            return _is_loopback_client_address(getattr(self, "client_address", None))
        security = APP.config.get("security", {})
        if not isinstance(security, dict):
            return False
        expected = security.get("api_token", "") or ""
        supervisor_token = security.get("supervisor_token", "") or ""
        action_tokens = security.get("action_tokens", {}) or {}
        users = security.get("users", {}) or {}
        if (
            not isinstance(expected, str)
            or not isinstance(supervisor_token, str)
            or not isinstance(action_tokens, dict)
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in action_tokens.items())
            or not isinstance(users, dict)
        ):
            return False
        user_records: list[tuple[str, dict[str, Any], str]] = []
        for principal, record in users.items():
            if not isinstance(principal, str) or not principal.strip() or not isinstance(record, dict):
                return False
            user_token = record.get("token", "") or ""
            user_permissions = record.get("permissions")
            user_tenant = record.get("tenant")
            if (
                not isinstance(user_token, str)
                or not isinstance(user_permissions, list)
                or not user_permissions
                or any(not isinstance(item, str) or not item.strip() for item in user_permissions)
                or (user_tenant is not None and (not isinstance(user_tenant, str) or not user_tenant.strip()))
            ):
                return False
            user_records.append((principal, record, user_token))
        configured_tokens = [token for token in (expected, supervisor_token, *action_tokens.values()) if token]
        configured_tokens.extend(token for _, _, token in user_records if token)
        if len(configured_tokens) != len(set(configured_tokens)):
            return False
        if action is None:
            action = _http_admin_action(
                str(getattr(self, "command", "")),
                urlparse(str(getattr(self, "path", ""))).path,
            )
        supplied = self.headers.get("X-LocalAI-Token", "")
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        global_valid = _token_matches(supplied, expected)
        supervisor_valid = _token_matches(supplied, supervisor_token)
        scoped = str(action_tokens.get(action, "")) if action else ""
        scoped_valid = len(scoped) >= 16 and _token_matches(supplied, scoped)
        matching_users = [
            (principal, record)
            for principal, record, token in user_records
            if _token_matches(supplied, token)
        ]
        matching_credentials = int(global_valid) + int(supervisor_valid) + int(scoped_valid) + len(matching_users)
        if matching_credentials > 1:
            return False
        local_client = _is_loopback_client_address(getattr(self, "client_address", None))
        configured_principal = self._configured_principal_tenant()
        if matching_users:
            principal, record = matching_users[0]
            grants = frozenset(item.strip().lower() for item in record["permissions"])
            required = (
                permission.strip().lower()
                if isinstance(permission, str) and ":" in permission
                else action.strip().lower()
                if isinstance(action, str) and ":" in action
                else self._required_permission()
            )
            self._authorization_actor = principal
            self._authorization_tenant = str(record.get("tenant") or "").strip() or None
            self._authorization_permissions = grants
            if required not in grants:
                self._authorization_status = 403
                return False
            self._authorization_status = 200
            return True
        if supervisor_valid:
            self._authorization_actor = "supervisor"
            self._authorization_tenant = self._principal_tenant()
            self._authorization_permissions = frozenset({"admin:read", "admin:write"})
            required = (
                permission.strip().lower()
                if isinstance(permission, str) and ":" in permission
                else action.strip().lower()
                if isinstance(action, str) and ":" in action
                else self._required_permission()
            )
            if required not in self._authorization_permissions:
                self._authorization_status = 403
                return False
            self._authorization_status = 200
            return True
        if scoped_valid:
            self._authorization_actor = "action_token"
            self._authorization_tenant = configured_principal or None
            self._authorization_permissions = frozenset({str(action)})
            self._authorization_status = 200
            return True
        if global_valid:
            grants = security.get("api_token_permissions", ["monitor", "read", "write", "admin"])
            allowed = {
                "monitor": {"monitor", "read", "write", "admin"},
                "read": {"read", "write", "admin"},
                "write": {"write", "admin"},
                "admin": {"admin"},
            }
            requested = permission
            if requested is None and isinstance(action, str) and ":" in action:
                requested = action
            if isinstance(requested, str) and ":" in requested:
                resource, _, verb = requested.partition(":")
                needed = "admin" if resource == "admin" else "monitor" if resource == "dashboard" and verb == "read" else verb
            else:
                needed = self._authorization_permission()
            self._authorization_actor = configured_principal or "service"
            self._authorization_permissions = frozenset(
                item.strip().lower() for item in grants if isinstance(item, str)
            ) if isinstance(grants, list) else frozenset()
            if (
                not isinstance(grants, list)
                or any(not isinstance(item, str) for item in grants)
                or needed not in allowed
                or not ({item.strip().lower() for item in grants} & allowed[needed])
            ):
                self._authorization_status = 403
                return False
            self._authorization_tenant = self._principal_tenant()
            self._authorization_status = 200
            return True
        if expected or supervisor_token or action_tokens or users:
            return False
        self._authorization_actor = "local" if local_client else "unrecognized"
        if local_client:
            self._authorization_status = 200
        return local_client

    def _audit_admin_authorization(self, action: str, *, allowed: bool) -> bool:
        if APP is None:
            return False
        telemetry = getattr(APP, "telemetry", None)
        recorder = getattr(telemetry, "record_system", None)
        if not callable(recorder):
            return False
        try:
            accepted = recorder(
                "admin.authorization",
                success=allowed,
                component="http_admin",
                operation=action,
                path=urlparse(str(getattr(self, "path", ""))).path,
                actor=str(getattr(self, "_authorization_actor", "unknown")),
            )
            return accepted is not False
        except Exception:
            return False

    def _audit_admin_result(self, status: int) -> bool:
        action = str(getattr(self, "_admin_action", "") or "")
        if not action:
            return True
        if getattr(self, "_admin_result_audited", False):
            return bool(getattr(self, "_admin_result_audit_accepted", False))
        self._admin_result_audited = True
        self._admin_result_audit_accepted = False
        telemetry = getattr(APP, "telemetry", None) if APP is not None else None
        recorder = getattr(telemetry, "record_system", None)
        if not callable(recorder):
            return False
        try:
            accepted = recorder(
                "admin.action.result",
                success=200 <= int(status) < 400,
                component="http_admin",
                operation=action,
                path=urlparse(str(getattr(self, "path", ""))).path,
                status_code=int(status),
                actor=str(getattr(self, "_authorization_actor", "unknown")),
            )
            self._admin_result_audit_accepted = accepted is not False
        except Exception:
            # Audit transport failure is reported, never silently accepted.
            self._admin_result_audit_accepted = False
        return self._admin_result_audit_accepted

    def _authorize_admin_action(self, operation: str) -> bool:
        """Require a globally authenticated request and an exact action/method route."""
        rule = self._ADMIN_ACTIONS.get(str(operation))
        if rule is None or not getattr(self, "_authorization_succeeded", False):
            self._send(403 if rule is not None else 400, {"success": False, "error": "admin action not authorized"})
            return False
        methods, expected_path, expected_action = rule
        actual_path = urlparse(str(getattr(self, "path", ""))).path
        path_matches = actual_path == expected_path
        if expected_path.endswith("/"):
            path_matches = actual_path.startswith(expected_path) and actual_path.count("/") == expected_path.count("/")
        if str(getattr(self, "command", "")) not in methods:
            self._send(
                405,
                {"success": False, "status_code": 405, "error": "method not allowed for admin action"},
                headers={"Allow": ", ".join(sorted(methods))},
            )
            return False
        if not path_matches:
            self._send(403, {"success": False, "error": "admin action does not match route"})
            return False
        if expected_action is not None and str(getattr(self, "command", "")) == "POST":
            payload = getattr(self, "_admin_payload", {})
            default_action = "update" if operation == "config.update" else "list" if operation == "models.list" else ""
            action = str(payload.get("action", default_action)).strip().lower().replace("-", "_") if isinstance(payload, dict) else ""
            if action != expected_action:
                self._send(403, {"success": False, "error": "admin action does not match request"})
                return False
        self._admin_operation = str(operation)
        self._admin_audited = False
        return True

    def _audit_admin_action(self, status: int, data: Any = None) -> bool:
        """Record only fixed operation and outcome metadata; never request content."""
        if getattr(self, "_admin_audited", False):
            return True
        operation = str(getattr(self, "_admin_operation", ""))
        if not operation:
            return True
        if APP is None:
            return False
        try:
            elapsed_ms = max(0.0, (time.perf_counter() - float(getattr(self, "_request_started", time.perf_counter()))) * 1000)
            accepted = APP.telemetry.record_system(
                f"admin.{operation}",
                success=200 <= int(status) < 300,
                duration_ms=elapsed_ms,
                status_code=int(status),
            )
        except Exception:
            accepted = False
        if accepted is True:
            self._admin_audited = True
            return True
        logger = getattr(APP, "logger", None)
        if logger is not None:
            logger.error("admin audit event not accepted operation=%s", operation)
        return False

    def _validate_host_and_origin(self) -> bool:
        """Validate Host and Origin headers to protect against DNS rebinding and cross-origin attacks."""
        if APP is None:
            return True
        request_headers = getattr(self, "headers", None)
        if not hasattr(request_headers, "get"):
            request_headers = {}
        header = lambda name, default="": request_headers.get(name, default)
        host_header = str(header("Host", "") or "").strip()
        if host_header:
            host_name = host_header.split(":", 1)[0].strip("[]").lower()
            allowed_hosts = {"127.0.0.1", "localhost", "::1", "testserver"}
            server_cfg = APP.config.get("server", {})
            bind = str(server_cfg.get("bind", "")).strip("[]").lower()
            if bind and bind not in {"0.0.0.0", "::"}:
                allowed_hosts.add(bind)

            if host_name not in allowed_hosts:
                self._send(403, {"success": False, "error": "forbidden: invalid Host header"})
                return False

        origin_header = str(header("Origin", "") or "").strip()
        if origin_header:
            parsed_origin = urlparse(origin_header)
            origin_host = str(parsed_origin.hostname or "").lower()
            allowed_origins = {"127.0.0.1", "localhost", "::1", "testserver"}
            server_cfg = APP.config.get("server", {})
            bind = str(server_cfg.get("bind", "")).strip("[]").lower()
            if bind and bind not in {"0.0.0.0", "::"}:
                allowed_origins.add(bind)

            bridge_origin = False
            bridge_token = False
            if str(getattr(self, "path", "")).startswith("/api/browser/") or str(getattr(self, "path", "")) == "/api/vision/review":
                bridge_origin = origin_allowed(APP.config, origin_header)
                expected_token = str(APP.config.get("security", {}).get("api_token", ""))
                supplied_token = str(header("X-LocalAI-Token", "") or "")
                auth_header = str(header("Authorization", "") or "")
                if auth_header.lower().startswith("bearer "):
                    supplied_token = auth_header[7:].strip()
                requested_headers = str(header("Access-Control-Request-Headers", "") or "").lower()
                token_preflight = str(getattr(self, "command", "")) == "OPTIONS" and ("x-localai-token" in requested_headers or "authorization" in requested_headers)
                bridge_token = bool(expected_token and (hmac.compare_digest(supplied_token, expected_token) or token_preflight))
            if origin_host not in allowed_origins and not bridge_origin and not bridge_token:
                self._send(403, {"success": False, "error": "forbidden: cross-origin requests are not allowed"})
                return False
        return True

    def _require_authorized(self, permission: str | None = None) -> bool:
        if not self._validate_host_and_origin():
            return False
        if not self._reject_legacy_tenant_header():
            return False
        local_mode_read = (
            str(getattr(self, "command", "")).upper() == "GET"
            and urlparse(str(getattr(self, "path", ""))).path == "/api/mode"
            and _is_loopback_client_address(getattr(self, "client_address", None))
        )
        action = _http_admin_action(
            str(getattr(self, "command", "")),
            urlparse(str(getattr(self, "path", ""))).path,
        )
        self._admin_action = action or ""
        self._admin_result_audited = False
        authorized = self._authorized(action, permission=permission)
        if not authorized and local_mode_read:
            self._authorization_actor = "local"
            authorized = True
        if not authorized:
            if action:
                self._audit_admin_authorization(action, allowed=False)
            status = int(getattr(self, "_authorization_status", 401))
            self._send(status, {"success": False, "error": "forbidden" if status == 403 else "unauthorized"})
            return False
        audit_accepted = self._audit_admin_authorization(action, allowed=True) if action else True
        mutation = str(getattr(self, "command", "GET")).upper() not in {"GET", "HEAD", "OPTIONS"}
        if mutation and not audit_accepted:
            self._send(503, {"success": False, "error": "admin audit unavailable", "retryable": True})
            return False
        if not self._tenant_binding_allowed():
            return False
        # Rate limit is checked after auth to avoid leaking tenant existence to unauthenticated callers.
        srv = self.server
        if hasattr(srv, "check_rate_limit"):
            tenant = self._tenant()
            if not srv.check_rate_limit(tenant):
                self._send(429, {"success": False, "error": "rate limit exceeded; slow down", "retryable": True, "retry_after_seconds": 10})
                return False
        return True

    def _content_length(self, *, limit: int) -> int:
        raw = self.headers.get("Content-Length")
        if raw is None:
            raise RequestBodyError("Content-Length is required", 411)
        try:
            length = int(raw)
        except (ValueError, TypeError) as exc:
            raise RequestBodyError("invalid Content-Length") from exc
        if length < 0:
            raise RequestBodyError("invalid Content-Length")
        if length > limit:
            raise RequestBodyError(f"request body exceeds configured limit ({limit} bytes)", 413)
        return length

    def _read_body(self, *, limit: int) -> bytes:
        length = self._content_length(limit=limit)
        if length == 0:
            return b""
        old_timeout = None
        chunks: list[bytes] = []
        received = 0
        try:
            old_timeout = self.connection.gettimeout()
            body_timeout = float(APP.config.get("server", {}).get("request_body_timeout_seconds", 15.0)) if APP is not None else 15.0
            deadline = time.monotonic() + max(0.1, body_timeout)
            read_once = getattr(self.rfile, "read1", None) or self.rfile.read
            # A socket timeout alone is only an *idle* timeout: a slow peer can keep
            # a handler forever by trickling one byte just before each expiry. Read in
            # chunks and shrink the socket timeout against one monotonic wall-clock
            # deadline so the complete body has a hard upper bound.
            while received < length:
                remaining_time = deadline - time.monotonic()
                if remaining_time <= 0:
                    raise RequestBodyError("request body timed out", 408)
                self.connection.settimeout(max(0.05, remaining_time))
                chunk = read_once(min(64 * 1024, length - received))
                if not chunk:
                    break
                chunks.append(chunk)
                received += len(chunk)
        except RequestBodyError:
            raise
        except (socket.timeout, TimeoutError) as exc:
            raise RequestBodyError("request body timed out", 408) from exc
        finally:
            try:
                self.connection.settimeout(old_timeout)
            except OSError:
                pass
        if received != length:
            raise RequestBodyError("request body ended before Content-Length bytes were received")
        return b"".join(chunks)

    def _read_json(self) -> dict[str, Any]:
        limit = max(1024, int(APP.config.get("server", {}).get("max_request_body_bytes", 16 * 1024 * 1024))) if APP is not None else (16 * 1024 * 1024)
        raw = self._read_body(limit=limit)
        if not raw:
            return {}
        content_type = self.headers.get("Content-Type", "application/json").split(";", 1)[0].strip().lower()
        if content_type not in {"application/json", "application/merge-patch+json"}:
            raise RequestBodyError("Content-Type must be application/json", 415)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestBodyError(f"invalid JSON body: {exc}") from exc
        if not isinstance(value, dict):
            raise RequestBodyError("JSON request body must be an object")
        trace_store = getattr(APP, "debug_traces", None) if APP is not None else None
        trace_id = str(getattr(self, "_debug_trace_id", "") or "")
        if trace_store is not None and trace_id:
            try:
                captured = self._safe_debug_trace_request(value)
                trace_store.update(trace_id, request=captured)
                trace_store.event(trace_id, "request_body_captured", {
                    "content_type": content_type,
                    "capture_status": captured.get("capture_status", "captured") if isinstance(captured, dict) else "captured",
                })
            except Exception:
                pass
        return value

    @staticmethod
    def _validate_payload(path: str, payload: dict[str, Any]) -> None:
        """Cheap endpoint schemas before scheduling or model policy work."""
        def text(value: Any, name: str, maximum: int) -> str:
            if not isinstance(value, str) or len(value) > maximum:
                raise RequestBodyError(f"{name} must be a string of at most {maximum} characters")
            return value

        def required_text(name: str, *aliases: str, maximum: int = 4096) -> str:
            for key in (name, *aliases):
                if key in payload:
                    value = text(payload[key], name, maximum).strip()
                    if value:
                        return value
            raise RequestBodyError(f"{name} is required")

        def bounded_integer(value: Any, name: str, minimum: int, maximum: int) -> None:
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise RequestBodyError(f"{name} must be an integer from {minimum} to {maximum}")

        def bounded_number(value: Any, name: str, minimum: float, maximum: float) -> None:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or (isinstance(value, float) and not math.isfinite(value))
                or not minimum <= value <= maximum
            ):
                raise RequestBodyError(f"{name} must be a finite number from {minimum:g} to {maximum:g}")

        if path.startswith("/api/agent-state/") and "action" in payload:
            action = _agent_action_selector(payload)
            if path == "/api/agent-state/tasks" and action not in _AGENT_TASK_ACTIONS:
                raise RequestBodyError("unknown task action")
            if path == "/api/agent-state/verification" and action not in _AGENT_VERIFICATION_ACTIONS:
                raise RequestBodyError("unknown verification action")
            if path == "/api/agent-state/verification" and action == "completion" and "repository_revision" in payload:
                revision = payload["repository_revision"]
                if (
                    not isinstance(revision, str)
                    or len(revision) > 256
                    or revision != revision.strip()
                ):
                    raise RequestBodyError(
                        "repository_revision must be empty or an opaque revision of at most 256 characters"
                    )

        if path == "/api/agent-state/blackboard":
            retired_fields = sorted(_AGENT_BLACKBOARD_RETIRED_FIELDS.intersection(payload))
            if retired_fields:
                fields = ", ".join(retired_fields)
                raise RequestBodyError(f"unsupported blackboard field(s): {fields}")

        if path == "/api/agent-state/incidents":
            action = payload.get("action")
            retired_by_action = {
                "decision": {"revision"},
                "record": {
                    "reason", "fix", "status", "redacted_message", "value",
                    "tool_name", "key", "paths", "revision", "error_class",
                },
                "find": {"key"},
            }
            retired = sorted(retired_by_action.get(action, set()).intersection(payload))
            if retired:
                raise RequestBodyError(f"unsupported incident field(s): {', '.join(retired)}")
            if action in retired_by_action:
                allowed_fields = {
                    "decision": {"action", "root", "tenant", "fingerprint", "state_revision"},
                    "record": {
                        "action", "root", "tenant", "root_cause", "verified_fix", "message",
                        "operation_class", "exit_code", "state_revision", "evidence_ids", "affected_paths",
                    },
                    "find": {"action", "root", "tenant", "query", "limit"},
                }[action]
                unexpected = sorted(set(payload) - allowed_fields)
                if unexpected:
                    raise RequestBodyError(f"unsupported incident field(s): {', '.join(unexpected)}")
                if "root" in payload:
                    text(payload["root"], "root", 4096)
                if "tenant" in payload:
                    text(payload["tenant"], "tenant", 160)
            if action == "decision":
                fingerprint = payload.get("fingerprint")
                if not isinstance(fingerprint, dict):
                    raise RequestBodyError("fingerprint must be an object")
                expected = {"error_class", "operation_class", "signature_hash"}
                if set(fingerprint) != expected:
                    raise RequestBodyError("fingerprint must contain error_class, operation_class, and signature_hash")
                for field, maximum in (("error_class", 160), ("operation_class", 160), ("signature_hash", 128)):
                    value = text(fingerprint[field], f"fingerprint.{field}", maximum)
                    if not value.strip():
                        raise RequestBodyError(f"fingerprint.{field} is required")
                if "state_revision" in payload:
                    text(payload["state_revision"], "state_revision", 256)
            elif action == "record":
                for field, maximum in (
                    ("root_cause", 4096), ("verified_fix", 4096), ("message", 4096),
                    ("operation_class", 160), ("state_revision", 256),
                ):
                    if field in payload:
                        text(payload[field], field, maximum)
                if "exit_code" in payload:
                    bounded_integer(payload["exit_code"], "exit_code", -(1 << 31), (1 << 32) - 1)
                for field, maximum_items, maximum_chars in (("evidence_ids", 64, 256), ("affected_paths", 128, 4096)):
                    if field not in payload:
                        continue
                    values = payload[field]
                    if not isinstance(values, list) or len(values) > maximum_items:
                        raise RequestBodyError(f"{field} must be a list of at most {maximum_items} entries")
                    for item in values:
                        text(item, f"{field} item", maximum_chars)
            elif action == "find":
                if "query" not in payload:
                    raise RequestBodyError("query is required")
                query = text(payload["query"], "query", 4096)
                if not query.strip() or "\x00" in query:
                    raise RequestBodyError("query is required")
                bounded_integer(payload.get("limit", 100), "limit", 1, 100)
                for field, maximum in (("root", 4096), ("tenant", 160)):
                    if field not in payload:
                        raise RequestBodyError(f"{field} is required")
                    scope_value = text(payload[field], field, maximum)
                    if not scope_value or scope_value != scope_value.strip() or "\x00" in scope_value:
                        raise RequestBodyError(f"{field} must be a canonical non-empty string")

        if path == "/api/embed":
            values = payload.get("texts", payload.get("input", []))
            values = [values] if isinstance(values, str) else values
            if not isinstance(values, list) or len(values) > 256:
                raise RequestBodyError("texts must be a list of at most 256 entries")
            for value in values:
                text(value, "embedding text", 200000)
        elif path == "/api/command":
            text(payload.get("command", ""), "command", 8000)
        elif path == "/api/telemetry/tool-accounting":
            events = payload.get("events", [])
            if not isinstance(events, list) or len(events) > 64:
                raise RequestBodyError("events must be a list of at most 64 entries")
            for event in events:
                if not isinstance(event, dict) or len(event) > 40:
                    raise RequestBodyError("each accounting event must be a small object")
                if "tool" in event:
                    text(event["tool"], "tool", 80)
                if "tenant" in event:
                    text(event["tenant"], "tenant", 160)
                if "agent" in event:
                    text(event["agent"], "agent", 80)
                breakdown = event.get("savings_breakdown", {})
                if not isinstance(breakdown, dict) or len(breakdown) > 16:
                    raise RequestBodyError("savings_breakdown must be an object with at most 16 entries")
        elif path == "/api/work-orders":
            action = text(payload.get("action", "submit"), "action", 32).strip().lower().replace("-", "_")
            if action not in {"submit", "status", "wait", "get", "cancel", "continue"}:
                raise RequestBodyError("unsupported work-order action")
            if action == "submit":
                required_text("root", maximum=4096)
                required_text("task", maximum=24000)
            if action in {"status", "wait", "get", "cancel", "continue"}:
                required_text("work_id", maximum=128)
            if action == "continue":
                required_text("answer", maximum=8000)
            for name, max_items, max_chars in (("acceptance_criteria", 24, 2000), ("constraints", 24, 2000), ("return_fields", 32, 80)):
                if name not in payload:
                    continue
                values = payload[name]
                if not isinstance(values, list) or len(values) > max_items:
                    raise RequestBodyError(f"{name} must be a list of at most {max_items} entries")
                for item in values:
                    text(item, f"{name} item", max_chars)
            for name in ("permissions", "budget"):
                if name in payload and not isinstance(payload[name], dict):
                    raise RequestBodyError(f"{name} must be an object")
            if "response_profile" in payload:
                text(payload["response_profile"], "response_profile", 16)
            if action == "wait" or "timeout_seconds" in payload:
                bounded_number(payload.get("timeout_seconds", 90), "timeout_seconds", 0, 90)
            if action in {"submit", "get"} or "max_output_tokens" in payload:
                bounded_integer(payload.get("max_output_tokens", 0), "max_output_tokens", 0, 4096)
        elif path in {"/api/preprocess", "/api/repo/profile", "/api/repo/map", "/api/repo/code-index", "/api/repo/investigate", "/api/repo/diagnose", "/api/repo/briefing", "/api/command/preflight", "/api/repo/deterministic", "/api/search"}:
            if "root" in payload:
                text(payload["root"], "root", 4096)
        elif path == "/api/memory/put":
            required_text("key", maximum=160)
            required_text("value", maximum=1000000)
            if "expected_version" in payload and (
                type(payload["expected_version"]) is not int or payload["expected_version"] < 0
            ):
                raise RequestBodyError("expected_version must be a non-negative integer")
            if "root" in payload:
                text(payload["root"], "root", 4096)
        elif path in {"/api/memory/get", "/api/memory/delete"}:
            required_text("key", maximum=160)
            if "root" in payload:
                text(payload["root"], "root", 4096)
            if path == "/api/memory/delete" and "scope" in payload:
                scope = text(payload["scope"], "scope", 16)
                if scope not in {"global", "tenant"}:
                    raise RequestBodyError("scope must be 'global' or 'tenant'")
        elif path == "/api/memory/search":
            if "root" in payload:
                text(payload["root"], "root", 4096)
            if "query" in payload:
                text(payload["query"], "query", 4096)
        elif path == "/api/code/symbol":
            required_text("symbol", maximum=1024)
        elif path == "/api/code/find_symbol":
            required_text("pattern", "name_path_pattern", maximum=1024)
        elif path in {"/api/code/find_declaration", "/api/code/find_implementations", "/api/code/find_referencing_symbols"}:
            required_text("symbol", "name", maximum=1024)
        elif path in {"/api/code/ast_outline", "/api/code/symbols_overview", "/api/code/diagnostics"}:
            required_text("path", "file", maximum=4096)
        elif path in {"/api/code/batch_replace", "/api/repo/batch_replace"}:
            edits = payload.get("edits") or payload.get("replacements")
            if not isinstance(edits, list) or not edits:
                raise RequestBodyError("edits must be a non-empty list of replacement operations")
        elif path in {"/api/speculative-lint", "/api/command/speculative-lint"}:
            action = text(payload.get("action", "submit"), "action", 32).strip().lower().replace("-", "_")
            if action not in {"submit", "status", "cancel"}:
                raise RequestBodyError("unsupported speculative lint action")
            if action == "submit":
                required_text("root", maximum=4096)
                paths = payload.get("paths")
                if not isinstance(paths, list) or not paths or len(paths) > 256:
                    raise RequestBodyError("paths must be a non-empty list of at most 256 entries")
                for item in paths:
                    text(item, "changed path", 4096)
                if "command" in payload:
                    text(payload["command"], "command", 4000)
            else:
                required_text("job_id", maximum=128)
        elif path == "/api/code-intelligence/query":
            action = text(payload.get("action", "search"), "action", 80).strip().lower().replace("-", "_")
            if action not in {"dead_code", "dead", "stats", "repository_stats"}:
                required_text("query", maximum=4096)
            if action in {"overview", "symbols_overview", "references", "find_references", "referencing"}:
                required_text("path", maximum=4096)
        elif path == "/api/browser/capability":
            required_text("origin", maximum=512)
            if "tab_id" not in payload or payload["tab_id"] in (None, ""):
                raise RequestBodyError("tab_id is required")
            if not isinstance(payload["tab_id"], (int, str)):
                raise RequestBodyError("tab_id must be an integer or string")
            if "window_id" not in payload or payload["window_id"] in (None, ""):
                raise RequestBodyError("window_id is required")
            if not isinstance(payload["window_id"], (int, str)):
                raise RequestBodyError("window_id must be an integer or string")
        elif path == "/api/browser/capture":
            required_text("capability", maximum=256)
            if "tab_id" not in payload:
                raise RequestBodyError("tab_id is required")
            if "window_id" not in payload or payload["window_id"] in (None, ""):
                raise RequestBodyError("window_id is required")
        elif path == "/api/vision/review":
            if "prompt" in payload:
                text(payload["prompt"], "prompt", 20000)
        elif path == "/api/coord/pubsub_poll":
            unsupported = set(payload) - {"root", "topic", "after_seq", "limit", "after_ts"}
            if unsupported:
                raise RequestBodyError(
                    "pubsub_poll accepts only root, topic, after_seq, limit, and after_ts"
                )
            if "after_seq" in payload:
                bounded_integer(payload["after_seq"], "after_seq", 0, (1 << 63) - 1)
            if "limit" in payload:
                bounded_integer(payload["limit"], "limit", 1, 1000)
            if "after_ts" in payload:
                bounded_number(payload["after_ts"], "after_ts", 0.0, 1e12)
        evaluation = payload.get("evaluation")
        if evaluation is not None:
            if not isinstance(evaluation, dict):
                raise RequestBodyError("evaluation must be an object")
            if "task_id" not in evaluation or "cohort" not in evaluation:
                raise RequestBodyError("evaluation task_id and cohort are required")

    def _handle_get_live(self, query: Mapping[str, list[str]]) -> None:
        after = int((query.get("after") or [0])[0])
        limit = int((query.get("limit") or [200])[0])
        max_batch = int(APP.config.get("monitoring", {}).get("live_max_batch", 200))
        self._send(200, APP.telemetry.live(after, min(limit, max_batch)))

    def _handle_get_live_status(self, query: Mapping[str, list[str]]) -> None:
        light = str((query.get("light") or ["0"])[0]).lower() in {"1", "true", "yes"}
        scope = str((query.get("scope") or ["process"])[0])
        status = APP.realtime_status(light=light, scope=scope)
        if isinstance(self.server, LocalAIHTTPServer):
            status["http_concurrency"] = self.server.concurrency_stats()
        self._send(200, status)

    def _handle_post_work_orders(self, payload: Any, *, tenant: str) -> None:
        if not getattr(APP, "work_orchestrator", None) or not APP.work_orchestrator.enabled:
            self._send(403, {"success": False, "unsupported": True, "error": "work orchestrator is disabled", "terminal": True}); return
        action = str(payload.get("action", "submit")).strip().lower().replace("-", "_")
        work_id = str(payload.get("work_id", "")).strip()
        if action == "submit":
            self._send(200, APP.work_orchestrator.submit(tenant, payload)); return
        if action == "status":
            self._send(200, APP.work_orchestrator.status(tenant, work_id)); return
        if action == "wait":
            self._send(200, APP.work_orchestrator.wait(tenant, work_id, float(payload.get("timeout_seconds", 90)))); return
        if action == "get":
            self._send(200, APP.work_orchestrator.get(tenant, work_id, profile=str(payload.get("response_profile", "")), return_fields=payload.get("return_fields") if isinstance(payload.get("return_fields"), list) else None, max_output_tokens=int(payload.get("max_output_tokens", 0) or 0))); return
        if action == "cancel":
            self._send(200, APP.work_orchestrator.cancel(tenant, work_id)); return
        if action == "continue":
            self._send(200, APP.work_orchestrator.continue_work(tenant, work_id, str(payload.get("answer", "")))); return
        self._send(400, {"success": False, "error": "unknown work-order action", "terminal": True}); return

    def _handle_post_async_jobs(self, payload: Any, *, tenant: str) -> None:
        action = str(payload.get("action", "")).strip().lower().replace("-", "_")
        if action == "submit":
            if bool(payload.get("conversation", False)):
                self._send(400, {"success": False, "error": "conversations require delivery=sync", "terminal": True, "retryable": False}); return
            job_payload = dict(payload)
            supplied_request_id = self.headers.get("X-LocalAI-Request-ID")
            if supplied_request_id and not job_payload.get("request_id"):
                job_payload["request_id"] = supplied_request_id
            self._send(200, APP.async_jobs.submit(tenant, str(payload.get("job_action", "reason")), job_payload)); return
        if action == "status":
            self._send(200, APP.async_jobs.status(tenant, str(payload.get("job_id", "")))); return
        if action == "wait":
            self._send(200, APP.async_jobs.wait(tenant, str(payload.get("job_id", "")), float(payload.get("timeout_seconds", 90)))); return
        if action == "result":
            self._send(200, APP.async_jobs.result(tenant, str(payload.get("job_id", "")))); return
        if action == "cancel":
            self._send(200, APP.async_jobs.cancel(tenant, str(payload.get("job_id", "")))); return
        self._send(400, {"success": False, "error": "unknown async job action", "terminal": True, "retryable": False}); return

    def _handle_post_db_query(self, payload: Any, *, tenant: str = "") -> None:
        db_name = str(payload.get("db", "agent_state"))
        sql_q = str(payload.get("query", "SELECT name FROM sqlite_master WHERE type='table'"))
        self._send(200, self._handle_db_query(db_name, sql_q))

    def _handle_post_telemetry_timeline(self, payload: Any, *, tenant: str = "") -> None:
        limit = payload.get("limit", 100) if isinstance(payload, dict) else 100
        before_id = payload.get("before_id") if isinstance(payload, dict) else None
        try:
            page = APP.telemetry.get_timeline_page(limit, before_id=before_id)
        except (TypeError, ValueError):
            raise
        except Exception as exc:
            logger = getattr(APP, "logger", None)
            if logger is not None:
                logger.warning("telemetry timeline page failed error_type=%s", type(exc).__name__)
            self._send(503, {
                "success": False,
                "error": {"code": "telemetry_page_unavailable", "message": "telemetry timeline is temporarily unavailable"},
                "status_code": 503,
                "retryable": True,
                "terminal": False,
            })
            return
        self._send(200, {"success": True, **page})

    def _handle_post_repository_analysis(
        self, payload: Any, *, tenant: str = "", route_ids: tuple[str, ...] = ()
    ) -> None:
        handle_post_repository_analysis(self, payload, route_ids, APP)

    def _async_delivery(self, path: str, payload: dict[str, Any], tenant: str) -> tuple[int, dict[str, Any]] | None:
        """Convert eligible long foreground work into an existing durable job when requested."""
        if APP is None:
            return None
        action_by_path = {
            "/api/delegate": "delegate", "/api/reason": "reason", "/api/review": "review",
            "/api/review/diff": "review_diff",
            "/api/second-opinion": "second_opinion", "/api/compress": "compress",
            "/api/route": "route", "/api/delegate/batch": "batch",
        }
        job_action = action_by_path.get(path)
        if not job_action:
            return None
        if bool(payload.get("conversation", False)):
            if str(payload.get("delivery", "sync")).strip().lower() != "sync":
                return 400, {"success": False, "error": "conversations require delivery=sync", "terminal": True, "retryable": False}
            return None
        try:
            estimate = APP.telemetry.http_latency_estimate(path)
            delivery = str(payload.get("delivery", "sync"))
            budget_ms = float(payload.get("latency_budget_ms", 0) or 0)
            samples = int(estimate.get("samples", 0) or 0)
            queue_age_ms = float(payload.get("queue_age_ms", estimate.get("queue_age_ms", 0)) or 0)
            max_queue_age_ms = float(
                payload.get(
                    "max_queue_age_ms",
                    getattr(APP, "config", {}).get("review", {}).get("max_queue_age_ms", 30_000),
                ) or 0
            )
            if (
                job_action == "review_diff"
                and delivery.strip().lower() == "auto"
                and max_queue_age_ms > 0
                and queue_age_ms > max_queue_age_ms
            ):
                decision = decide_delivery(
                    delivery,
                    latency_budget_ms=budget_ms,
                    observed_p95_ms=estimate.get("p95_duration_ms", 0),
                    samples=samples,
                    queue_age_ms=queue_age_ms,
                    max_queue_age_ms=max_queue_age_ms,
                )
            elif job_action == "review_diff" and delivery.strip().lower() == "auto" and budget_ms > 0 and samples < 5:
                # A cold-start review has no trustworthy p95 yet. Do not let a
                # large diff run synchronously while telemetry learns the cost.
                decision = {"mode": "async", "reason": "cold_start_review_diff"}
            else:
                decision = decide_delivery(
                    delivery, latency_budget_ms=payload.get("latency_budget_ms", 0),
                    observed_p95_ms=estimate.get("p95_duration_ms", 0), samples=estimate.get("samples", 0),
                    queue_age_ms=queue_age_ms,
                    max_queue_age_ms=max_queue_age_ms,
                )
        except (TypeError, ValueError) as exc:
            return 400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}
        if decision["mode"] == "bypass":
            return 503, {
                "success": False,
                "terminal": True,
                "retryable": False,
                "error": "review queue age exceeded delivery budget",
                "delivery": decision,
                "next_action": "retry_with_bounded_sync_or_inspect_existing_job",
            }
        if decision["mode"] != "async":
            return None
        job_payload = dict(payload)
        headers = getattr(self, "headers", None)
        supplied_request_id = headers.get("X-LocalAI-Request-ID") if hasattr(headers, "get") else None
        if supplied_request_id:
            job_payload["request_id"] = supplied_request_id
        job_payload.pop("delivery", None); job_payload.pop("latency_budget_ms", None)
        if job_action == "reason":
            job_payload["task"] = str(job_payload.get("problem", job_payload.get("task", "")))
        elif job_action == "review":
            job_payload["task"] = str(job_payload.get("instructions", job_payload.get("task", "Report actionable defects only.")))
            job_payload["context"] = str(job_payload.get("code", job_payload.get("context", "")))
        elif job_action == "second_opinion":
            job_payload["task"] = str(job_payload.get("question", job_payload.get("task", "")))
        elif job_action == "compress":
            job_payload["task"] = str(job_payload.get("instruction", job_payload.get("task", "Compress while preserving facts.")))
            job_payload["context"] = str(job_payload.get("text", job_payload.get("context", "")))
        elif job_action == "route":
            job_payload["task"] = str(job_payload.get("query", job_payload.get("task", "")))
            job_payload["context"] = str(job_payload.get("text", job_payload.get("context", "")))
        elif job_action == "review_diff":
            job_payload["_async_job"] = True
        result = APP.async_jobs.submit(tenant, job_action, job_payload)
        result["delivery"] = decision
        trace_store = getattr(APP, "debug_traces", None)
        api_trace_id = str(getattr(self, "_debug_trace_id", "") or "")
        if trace_store is not None and api_trace_id and isinstance(result, dict):
            if result.get("job_id"):
                trace_store.link(api_trace_id, async_job_id=str(result["job_id"]))
            trace_store.event(api_trace_id, "async_job_submitted", {"job_id": result.get("job_id", ""), "trace_id": result.get("trace_id", ""), "delivery": decision})
        return 200, result

    def _send_database_locked(self) -> None:
        mutation = str(getattr(self, "command", "GET")).upper() not in {"GET", "HEAD", "OPTIONS"}
        response = {
            "success": False,
            "degraded": True,
            "error": "database_locked",
            "error_code": "database_locked",
            "status_code": 503,
            "terminal": mutation,
            "retryable": not mutation,
            "outcome_unknown": mutation,
        }
        self._send(503, response)

    def _send(self, status: int, data: Any, *, headers: Mapping[str, str] | None = None) -> None:
        execution_started = getattr(self, "_handler_execution_started", None)
        operation = str(getattr(self, "_admin_operation", ""))
        if operation:
            audit_recorded = self._audit_admin_action(status, data)
            if not audit_recorded and isinstance(data, dict):
                data = dict(data)
                data["audit_accepted"] = False
                if 200 <= int(status) < 300:
                    data.setdefault("warning", "operation may have completed but audit event was not accepted for queuing")
        if getattr(self, "_admin_action", ""):
            audit_accepted = self._audit_admin_result(status)
            mutation = str(getattr(self, "command", "GET")).upper() not in {"GET", "HEAD", "OPTIONS"}
            if mutation and not audit_accepted and 200 <= status < 400 and isinstance(data, dict):
                status = 503
                data = {**data, "success": False, "error": "admin result audit unavailable; operation may have completed",
                        "outcome_unknown": True, "terminal": True, "retryable": False}
        if status >= 400:
            data = normalize_transport_error(status, data)
        request_headers = getattr(self, "headers", None)
        response_request_id = request_headers.get("X-LocalAI-Request-ID", "") if hasattr(request_headers, "get") else ""
        if (
            isinstance(data, dict)
            and "request_id" not in data
            and isinstance(response_request_id, str)
            and 1 <= len(response_request_id) <= 128
            and response_request_id.isascii()
            and all(0x21 <= ord(char) <= 0x7E for char in response_request_id)
        ):
            data = {**data, "request_id": response_request_id}
        request_id = getattr(self, "_journal_request_id", None)
        if request_id and isinstance(data, dict):
            data = dict(data)
            data.setdefault("request_id", request_id)
        if request_id and APP is not None and not getattr(self, "_journal_finished", False):
            try:
                success = _journal_outcome_success(status, data)
                detail = "" if success else str(data.get("error", "request failed")) if isinstance(data, dict) else "request failed"
                APP.recovery.finish(request_id, success, detail, status_code=status, response=data)
                self._journal_finished = True
            except Exception:
                pass
        serialization_started = time.perf_counter()
        exec_ms = (
            max(0.0, (serialization_started - execution_started) * 1000.0)
            if isinstance(execution_started, (int, float))
            else None
        )
        body = _json_bytes(data)
        response_path = urlparse(str(getattr(self, "path", ""))).path
        if (
            response_path in {"/api/search", "/api/repo/code-index"}
            and int(status) < 400
            and len(body) > MAX_HTTP_PAGE_RESPONSE_BYTES
            and isinstance(data, dict)
        ):
            page_key = "results" if response_path == "/api/search" else "symbols"
            data = {
                "success": False,
                "status_code": 413,
                "terminal": True,
                "retryable": False,
                "error": "requested search page exceeds the 4 MiB HTTP response limit; reduce limit or snippet size",
                "root": data.get("root"),
                "offset": data.get("offset", 0),
                "limit": data.get("limit", 24),
                "total_matches": data.get("total_matches", 0),
                "has_more": data.get("has_more", False),
                page_key: [],
            }
            status = 413
            body = _json_bytes(data)
        serialization_ms = max(0.0, (time.perf_counter() - serialization_started) * 1000.0)
        self._finish_debug_trace(status, data)
        if APP is not None and not getattr(self, "_telemetry_finished", False):
            try:
                path = str(getattr(self, "_request_path", urlparse(self.path).path))
                excluded = set(APP.config.get("observability", {}).get("exclude_http_paths", []))
                if path not in MONITOR_PATHS and not path.startswith("/api/debug-traces/") and path not in excluded:
                    elapsed_ms = max(0.0, (time.perf_counter() - float(getattr(self, "_request_started", time.perf_counter()))) * 1000)
                    policy_blocked = bool(path == "/api/command" and isinstance(data, dict) and data.get("policy_blocked"))
                    telemetry_data = dict(data) if isinstance(data, dict) else data
                    if policy_blocked and isinstance(telemetry_data, dict):
                        telemetry_data["policy_blocked"] = True
                    reliability_success, outcome_error_type, record_operational_error = _telemetry_http_outcome(status, telemetry_data, path)
                    err = str(data.get("error", "")) if isinstance(data, dict) else ""
                    evidence = data.get("evidence", []) if isinstance(data, dict) else []
                    canonical = data.get("canonical", {}) if isinstance(data, dict) and isinstance(data.get("canonical"), dict) else {}
                    canonical_route = canonical.get("route", {}) if isinstance(canonical.get("route"), dict) else {}
                    pipeline = data.get("pipeline", {}) if isinstance(data, dict) and isinstance(data.get("pipeline"), dict) else {}
                    repo_context = data.get("repo_context", {}) if isinstance(data, dict) and isinstance(data.get("repo_context"), dict) else {}
                    repo_evidence = repo_context.get("evidence", []) if isinstance(repo_context.get("evidence"), list) else []
                    stages = pipeline.get("stages", []) if isinstance(pipeline.get("stages"), list) else []
                    phase_latency = _response_phase_latency(data)
                    APP.telemetry.record_http(
                        tenant=self._tenant(), agent=self._agent(), request_id=str(getattr(self, "_trace_request_id", "")),
                        trace_id=str(getattr(self, "_trace_id", "")), action=path, duration_ms=elapsed_ms, success=reliability_success,
                        status_code=status, response_bytes=len(body), model=str(data.get("model", "")) if isinstance(data, dict) else "",
                        cache_hit=bool(data.get("cache_hit", False)) if isinstance(data, dict) else False,
                        preprocessed_hit=bool(data.get("preprocessed_hit", False)) if isinstance(data, dict) else False,
                        cache_layer=str(data.get("cache_layer", "")) if isinstance(data, dict) else "",
                        fallback_used=bool(data.get("fallback_used", False)) if isinstance(data, dict) else False,
                        degraded=bool(data.get("stale_fallback", False) or data.get("degraded", False)) if isinstance(data, dict) else False,
                        route=(">".join(str(x) for x in stages) if stages else str(data.get("strategy", data.get("route", ""))))[:120] if isinstance(data, dict) else "",
                        task_type=str(canonical_route.get("task_type", ""))[:80], complexity=str(canonical_route.get("complexity", ""))[:40],
                        evidence_count=(len(repo_evidence) if repo_evidence else (len(evidence) if isinstance(evidence, list) else 0)),
                        error_type=outcome_error_type,
                        queue_wait_ms=phase_latency.get("queue_wait_ms"), service_ms=phase_latency.get("service_ms"),
                        db_wait_ms=phase_latency.get("db_wait_ms"), exec_ms=exec_ms,
                        serialization_ms=serialization_ms,
                    )
                    request_evaluation = getattr(self, "_request_evaluation", None)
                    if reliability_success and request_evaluation is not None:
                        APP.telemetry.record_request_evaluation(request_evaluation, duration_ms=elapsed_ms)
                    if record_operational_error and err:
                        APP.telemetry.record_error(
                            "http", path, err, request_id=str(getattr(self, "_trace_request_id", "")),
                            tenant=self._tenant(), agent=self._agent(), error_type_override=outcome_error_type,
                            error_code_override="http_request_failed", retryable=status in {429, 500, 502, 503, 504},
                        )
                self._telemetry_finished = True
            except Exception:
                pass
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Connection", "close")
            self._common_headers()
            for name, value in (headers or {}).items():
                self.send_header(str(name), str(value))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError as exc:
            if not _is_client_disconnect(exc):
                raise
        finally:
            self.close_connection = True
            if not getattr(self, "_debug_trace_finished", False):
                self._finish_debug_trace(status, data)
            self._close_trace_context()

    def _finish_stream_request(self, success: bool, error: str = "") -> None:
        """Finish journal/telemetry for responses whose headers/body were streamed manually."""
        if APP is None:
            return
        response = {"success": success, "streamed": True, "error": error} if error else {"success": success, "streamed": True}
        if getattr(self, "_debug_stream_capture_failed", False):
            response["trace_capture_status"] = "storage_error"
        self._finish_debug_trace(200 if success else 500, response, error=error)
        request_id = str(getattr(self, "_journal_request_id", "") or "")
        if request_id and not getattr(self, "_journal_finished", False):
            try:
                APP.recovery.finish(
                    request_id, success, error, status_code=200,
                    response={"success": success, "streamed": True, "error": error} if error else {"success": success, "streamed": True},
                )
                self._journal_finished = True
            except Exception:
                pass
        if not getattr(self, "_telemetry_finished", False):
            try:
                path = str(getattr(self, "_request_path", urlparse(self.path).path))
                elapsed_ms = max(0.0, (time.perf_counter() - float(getattr(self, "_request_started", time.perf_counter()))) * 1000)
                APP.telemetry.record_http(
                    tenant=self._tenant(), agent=self._agent(), request_id=str(getattr(self, "_trace_request_id", "")),
                    trace_id=str(getattr(self, "_trace_id", "")), action=path, duration_ms=elapsed_ms, success=success,
                    status_code=200, response_bytes=0, model="", cache_hit=False, fallback_used=False,
                    degraded=False, route="stream", evidence_count=0, error_type="stream_error" if error else "",
                )
                if error:
                    APP.telemetry.record_error(
                        "http", path, error, request_id=str(getattr(self, "_trace_request_id", "")),
                        tenant=self._tenant(), agent=self._agent(), error_type_override="HttpStreamError",
                        error_code_override="http_stream_failed", retryable=True,
                    )
                self._telemetry_finished = True
            except Exception:
                pass
        self._close_trace_context()

    def _stream_agent_events(
        self,
        stream_id: str = "",
        kind: str = "",
        after_seq: int = 0,
        timeout: float = 0.0,
        last_event_id: str = "",
    ) -> None:
        if APP is None or not getattr(APP, "agent_state", None) or not APP.agent_state.enabled:
            self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False})
            return

        # EventSource reconnects carry the last numeric event ID automatically.
        # It is safe to apply only with an explicit stream filter; an unscoped
        # cursor could otherwise resume one stream inside another.
        headers = getattr(self, "headers", {})
        last_event_id_header = str(headers.get("Last-Event-ID", "") if hasattr(headers, "get") else "" or "").strip()
        effective_last_event_id = last_event_id_header or last_event_id
        prefixed_cursor = bool(stream_id and ":" in effective_last_event_id)

        if stream_id and effective_last_event_id:
            parsed = _parse_agent_event_cursor(effective_last_event_id)
            if parsed is not None:
                parsed_stream, parsed_seq = parsed
                if parsed_stream == stream_id:
                    after_seq = parsed_seq
            elif effective_last_event_id.isascii() and effective_last_event_id.isdecimal():
                try:
                    resume_seq = int(effective_last_event_id)
                    if 0 <= resume_seq <= (1 << 63) - 1:
                        after_seq = resume_seq
                except (TypeError, ValueError, OverflowError):
                    pass

        q = None

        def send_initial_error(_status: int, _payload: Mapping[str, Any]) -> None:
            try:
                if q is not None:
                    try:
                        APP.agent_state.unsubscribe(q)
                    except Exception as exc:
                        logger = getattr(APP, "logger", None)
                        if logger is not None:
                            logger.warning("event stream unsubscribe failed error_type=%s", type(exc).__name__)
                payload = dict(_payload)
                self.send_response(_status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self._common_headers()
                self.end_headers()
                self.wfile.write(_json_bytes(payload))
                self.wfile.flush()
            except OSError:
                pass
            self._finish_stream_request(False, error="event replay unavailable")

        try:
            q = APP.agent_state.subscribe(maxsize=200)
        except Exception as exc:
            logger = getattr(APP, "logger", None)
            if logger is not None:
                logger.warning("event stream subscribe failed error_type=%s", type(exc).__name__)
            send_initial_error(503, {
                "success": False,
                "error": {"code": "event_replay_unavailable", "message": "Event replay is temporarily unavailable."},
            })
            return

        initial_page: dict[str, Any] | None = None
        if stream_id and after_seq >= 0:
            if not hasattr(APP.agent_state, "event_page"):
                send_initial_error(503, {
                    "success": False,
                    "error": {"code": "event_page_unavailable", "message": "Event page could not be read."},
                    "next_seq": after_seq,
                    "terminal": False,
                    "retryable": True,
                })
                return
            first_limit = min(AGENT_EVENT_PAGE_MAX_LIMIT, SSE_REPLAY_MAX_EVENTS)
            try:
                initial_page = APP.agent_state.event_page(
                    stream_id=stream_id,
                    after_seq=after_seq,
                    limit=first_limit,
                )
            except Exception:
                send_initial_error(503, {
                    "success": False,
                    "error": {"code": "event_page_unavailable", "message": "Event page could not be read."},
                    "next_seq": after_seq,
                    "terminal": False,
                    "retryable": True,
                })
                return
            if not isinstance(initial_page, dict) or initial_page.get("success") is not True:
                send_initial_error(503, initial_page if isinstance(initial_page, dict) else {
                    "success": False,
                    "error": {"code": "event_page_unavailable", "message": "Event page could not be read."},
                    "next_seq": after_seq,
                    "terminal": False,
                    "retryable": True,
                })
                return

        # Bound maximum stream duration to prevent holding worker threads indefinitely
        app_cfg = getattr(APP, "config", {}) or {}
        max_duration = float(app_cfg.get("server", {}).get("max_stream_duration_seconds", 300.0) if isinstance(app_cfg, dict) else 300.0)
        if timeout <= 0.0 or timeout > max_duration:
            timeout = max_duration

        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self._common_headers()
            self.end_headers()
        except OSError:
            self._finish_stream_request(False, error="client disconnected before headers")
            return

        stream_success = True
        stream_error = ""
        trace_stream_output = bool(getattr(self, "_debug_trace_id", ""))
        if trace_stream_output:
            self._debug_stream_capture = True
        try:
            # Subscribe before fetching history. An event appended in the replay
            # window is then either replayed or queued; duplicate queued events
            # are discarded by the per-stream sequence check below.
            last_seq_by_stream: dict[str, int] = {}
            last_seq = after_seq
            last_delivered_seq = after_seq
            stream_success = True

            def note_seq(event_stream: str, seq: int) -> None:
                last_seq_by_stream[event_stream] = max(
                    last_seq_by_stream.get(event_stream, after_seq), seq
                )

            def current_last_seq() -> int:
                if stream_id:
                    return last_seq_by_stream.get(stream_id, last_seq)
                return max([after_seq, *last_seq_by_stream.values()])

            def format_seq(seq: int | None) -> str:
                if seq is None:
                    return ""
                if prefixed_cursor and stream_id:
                    return _encode_agent_event_cursor(stream_id, seq)
                return str(seq)

            def capture_sse_chunk(chunk: bytes) -> None:
                if not trace_stream_output:
                    return
                store = getattr(APP, "debug_traces", None) if APP is not None else None
                append_output = getattr(store, "append_output", None)
                if not callable(append_output) or not append_output(
                    str(getattr(self, "_debug_trace_id", "")), chunk.decode("utf-8")
                ):
                    self._debug_stream_capture_failed = True

            def write_sse(event_name: str, payload: Mapping[str, Any], seq: int | None = None) -> bool:
                nonlocal stream_success, stream_error, last_delivered_seq
                if seq is not None:
                    event_id = f"id: {seq}\n" if event_name == "replay_page" else f"id: {format_seq(seq)}\n"
                else:
                    event_id = ""
                msg = (
                    f"{event_id}event: {event_name}\n"
                    f"data: {json_dumps(payload, separators=(',', ':'))}\n\n"
                ).encode("utf-8")
                try:
                    self.wfile.write(msg)
                    self.wfile.flush()
                    if trace_stream_output:
                        capture_sse_chunk(msg)
                    if seq is not None:
                        last_delivered_seq = seq
                    return True
                except OSError:
                    stream_success = False
                    stream_error = "client disconnected"
                    return False

            if stream_id and after_seq >= 0:
                replay_cursor = after_seq
                replay_through_seq = None
                replayed_events = 0
                reported_gap_ranges: set[tuple[int, int]] = set()
                first_page = True
                while replayed_events < SSE_REPLAY_MAX_EVENTS:
                    if first_page and initial_page is not None:
                        page = initial_page
                        first_page = False
                    else:
                        page_limit = min(AGENT_EVENT_PAGE_MAX_LIMIT, SSE_REPLAY_MAX_EVENTS - replayed_events)
                        try:
                            page = APP.agent_state.event_page(
                                stream_id=stream_id,
                                after_seq=replay_cursor,
                                limit=page_limit,
                                through_seq=replay_through_seq,
                            )
                        except Exception as exc:
                            stream_success = False
                            stream_error = "event replay unavailable"
                            logger = getattr(APP, "logger", None)
                            if logger is not None:
                                logger.warning("event replay page failed error_type=%s", type(exc).__name__)
                            write_sse("replay_error", {
                                "success": False,
                                "next_seq": max(0, int(replay_cursor)),
                                "error": {
                                    "code": "event_replay_unavailable",
                                    "message": "event replay is temporarily unavailable",
                                },
                                "retryable": True,
                                "terminal": False,
                            })
                            return
                        if not isinstance(page, dict) or page.get("success") is not True:
                            stream_success = False
                            stream_error = "event replay unavailable"
                            err_payload = page if isinstance(page, dict) else {
                                "success": False,
                                "next_seq": max(0, int(replay_cursor)),
                                "error": {
                                    "code": "event_replay_unavailable",
                                    "message": "event replay is temporarily unavailable",
                                },
                                "retryable": True,
                                "terminal": False,
                            }
                            write_sse("replay_error", err_payload)
                            return

                    if replay_through_seq is None:
                        raw_high_water = page.get("last_seq", replay_cursor)
                        replay_through_seq = max(0, int(replay_cursor if raw_high_water is None else raw_high_water))
                        if replay_cursor > replay_through_seq or (page.get("cursor_reset") is True and prefixed_cursor):
                            first_retained = max(0, int(page.get("first_retained_seq", 0) or 0))
                            checkpoint = min(max(0, first_retained - 1), replay_through_seq)
                            if prefixed_cursor and page.get("next_seq") is not None:
                                checkpoint = int(page["next_seq"])
                            cursor_reset = {
                                "requested_after_seq": replay_cursor,
                                "last_seq": replay_through_seq,
                                "resume_after_seq": checkpoint,
                                "cursor_ahead": True,
                            }
                            if first_retained > 1:
                                cursor_reset.update({
                                    "retention_gap": True,
                                    "missing_from_seq": 1,
                                    "missing_through_seq": min(first_retained - 1, replay_through_seq),
                                    "first_available_seq": first_retained,
                                })
                            reset_event_name = "cursor_reset" if prefixed_cursor else "replay_cursor_reset"
                            if not write_sse(reset_event_name, cursor_reset, seq=checkpoint):
                                return
                            replay_cursor = checkpoint
                            last_seq = checkpoint
                            last_seq_by_stream[stream_id] = checkpoint
                            if prefixed_cursor:
                                if not page.get("has_more") and not page.get("events"):
                                    break
                            else:
                                continue

                    page_cursor = int(page.get("next_seq", replay_cursor) or 0)
                    gap_ranges = page.get("gap_ranges", [])
                    replay_events = page.get("events", [])
                    if not isinstance(replay_events, (list, tuple)):
                        replay_events = []

                    if prefixed_cursor and gap_ranges and not replay_events:
                        gap_payload = {
                            "stream_id": stream_id,
                            "next_seq": page_cursor,
                            "gap_ranges": gap_ranges,
                            "first_retained_seq": page.get("first_retained_seq", page_cursor),
                            "last_seq": page.get("last_seq", page_cursor),
                            "cursor_reset": False,
                            "retention_gap": True,
                        }
                        if not write_sse("retention_gap", gap_payload, seq=page_cursor):
                            return
                        last_seq = page_cursor
                        note_seq(stream_id, page_cursor)
                        last_delivered_seq = page_cursor
                        break

                    replay_entries = []
                    if isinstance(gap_ranges, (list, tuple)):
                        for gap in gap_ranges:
                            if not isinstance(gap, dict):
                                continue
                            try:
                                gap_start = int(gap.get("from_seq"))
                                gap_end = int(gap.get("to_seq"))
                            except (TypeError, ValueError, OverflowError):
                                continue
                            gap_start = max(gap_start, last_seq + 1)
                            gap_end = min(gap_end, page_cursor)
                            if gap_start < 0 or gap_end < gap_start or (gap_start, gap_end) in reported_gap_ranges:
                                continue
                            gap_event_kind = "retention_gap" if prefixed_cursor else "stream.gap"
                            replay_entries.append((gap_end, gap_event_kind, {
                                **gap, "from_seq": gap_start, "to_seq": gap_end,
                            }, True))
                    if page.get("cursor_reset") is True and not prefixed_cursor:
                        first_retained = int(page.get("first_retained_seq", 0) or 0)
                        last_seq = max(0, first_retained - 1)

                    for raw_event in replay_events:
                        if hasattr(raw_event, "to_dict") and callable(raw_event.to_dict):
                            raw_event = raw_event.to_dict()
                        if not isinstance(raw_event, dict):
                            continue
                        event_seq = int(raw_event.get("seq", 0) or 0)
                        event_kind = str(raw_event.get("kind", ""))
                        if event_seq <= last_seq:
                            continue
                        replay_entries.append((event_seq, event_kind, raw_event, False))

                    for event_seq, event_kind, raw_event, is_gap in sorted(replay_entries, key=lambda item: item[0]):
                        if event_seq <= last_seq:
                            continue
                        if is_gap:
                            if not write_sse(event_kind, raw_event, seq=event_seq):
                                return
                            reported_gap_ranges.add((raw_event["from_seq"], raw_event["to_seq"]))
                        elif not kind or event_kind == kind:
                            if not write_sse(event_kind, raw_event, seq=event_seq):
                                return
                        last_seq = event_seq
                        note_seq(stream_id, event_seq)

                    page_id = page_cursor if page_cursor > last_delivered_seq else None
                    if not write_sse("replay_page", page, seq=page_id):
                        return
                    replayed_events += len(replay_events)
                    next_cursor = int(page.get("next_seq", replay_cursor) or 0)
                    has_more = page.get("has_more") is True
                    if replayed_events >= SSE_REPLAY_MAX_EVENTS:
                        if has_more:
                            limit_reached = {
                                "replay_limit": SSE_REPLAY_MAX_EVENTS,
                                "last_seq": last_seq,
                                "has_more": True,
                            }
                            limit_msg = (
                                f"id: {format_seq(last_seq)}\nevent: replay_limit\ndata: "
                                f"{json_dumps(limit_reached, separators=(',', ':'))}\n\n"
                            ).encode("utf-8")
                            try:
                                self.wfile.write(limit_msg)
                                self.wfile.flush()
                            except OSError:
                                stream_success = False
                                stream_error = "client disconnected"
                                return
                        break
                    if not has_more or next_cursor <= replay_cursor:
                        break
                    replay_cursor = next_cursor

            start_time = time.monotonic()
            while True:
                remaining = timeout - (time.monotonic() - start_time)
                if remaining <= 0:
                    write_sse(
                        "stream_timeout",
                        {
                            "reconnect": True,
                            "last_seq": current_last_seq(),
                            "next_seq": current_last_seq(),
                            "last_seq_by_stream": dict(last_seq_by_stream),
                        },
                    )
                    break
                try:
                    ev = q.get(timeout=min(1.0, remaining))
                    if ev.kind == "stream.gap":
                        ranges = ev.payload.get("gap_ranges", [])
                        matching_ranges = [
                            gap for gap in ranges
                            if isinstance(gap, Mapping)
                            and (not stream_id or str(gap.get("stream_id", ev.stream_id)) == stream_id)
                        ]
                        relevant = not stream_id or ev.stream_id == stream_id or matching_ranges
                        if not relevant:
                            continue
                        for gap in matching_ranges:
                            gap_stream = str(gap.get("stream_id", ev.stream_id))
                            try:
                                note_seq(gap_stream, int(gap.get("to_seq", 0)))
                            except (TypeError, ValueError):
                                continue
                        gap_kind = "retention_gap" if prefixed_cursor else ev.kind
                        if not write_sse(gap_kind, ev.to_dict()):
                            break
                        continue

                    if stream_id and ev.stream_id != stream_id:
                        continue
                    if ev.seq is not None:
                        if ev.seq <= last_seq_by_stream.get(ev.stream_id, after_seq):
                            continue
                        note_seq(ev.stream_id, ev.seq)
                    if kind and ev.kind != kind:
                        if prefixed_cursor and stream_id and ev.seq is not None:
                            try:
                                cursor_event = f"id: {format_seq(ev.seq)}\n\n".encode("utf-8")
                                self.wfile.write(cursor_event)
                                self.wfile.flush()
                                if trace_stream_output:
                                    capture_sse_chunk(cursor_event)
                                last_delivered_seq = ev.seq
                            except OSError:
                                stream_success = False
                                stream_error = "client disconnected"
                                break
                        continue
                    if not write_sse(ev.kind, ev.to_dict(), ev.seq):
                        break
                except queue.Empty:
                    try:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        if trace_stream_output:
                            capture_sse_chunk(b": keep-alive\n\n")
                    except OSError:
                        stream_success = False
                        stream_error = "client disconnected"
                        break
        except OSError:
            stream_success = False
            stream_error = "client disconnected"
        except Exception:
            stream_success = False
            stream_error = "stream failed"
        finally:
            self.close_connection = True
            APP.agent_state.unsubscribe(q)
            self._finish_stream_request(stream_success, error=stream_error)

    def do_OPTIONS(self) -> None:
        if APP is None:
            self._send(503, {"success": False, "error": "hub starting up; please retry", "retryable": True})
            return
        path = urlparse(self.path).path
        bridge_route = path.startswith("/api/browser/") or path == "/api/vision/review"
        if not bridge_route or not self._validate_host_and_origin():
            self._send(404, {"success": False, "error": "unsupported browser bridge route", "terminal": True, "retryable": False})
            return
        try:
            self.send_response(204)
            self._common_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()
        except OSError as exc:
            if not _is_client_disconnect(exc):
                raise

    def do_GET(self) -> None:
        self._handler_execution_started = time.perf_counter()
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/health":
            self._send(200, {"success": True, "hub_online": True, "version": __version__})
            return
        if path == "/ready":
            if APP is None and not self._loopback_client():
                self._send(403, {"success": False, "ready": False, "error": "readiness is loopback-only"})
                return
            if APP is not None and not self._require_authorized("monitor"):
                return
            app = APP
            stores_ready = app is not None and all(
                getattr(app, name, None) is not None
                for name in READINESS_COMPONENTS
            )
            ready = app is not None and not bool(getattr(app, "_closed", False)) and stores_ready
            reason = "ready" if ready else "app_initializing_or_closed"
            if app is not None and not bool(getattr(app, "_closed", False)) and not stores_ready:
                reason = "required_store_unavailable"
            self._send(
                200 if ready else 503,
                {
                    "success": ready,
                    "ready": ready,
                    "reason": reason,
                    "retryable": not ready,
                    "version": __version__,
                },
            )
            return
        if APP is None:
            self._send(503, {"success": False, "error": "hub starting up; please retry", "status_code": 503, "retryable": True})
            return
        # The dashboard shell is public; loopback mode reads expose only local
        # runtime state, while mode mutations remain authenticated.
        if path == "/api/mode" and not _is_loopback_peer(self):
            self._send(403, {"success": False, "error": "local_control_requires_loopback"})
            return
        elif path == "/api/mode":
            if not self._validate_host_and_origin():
                return
        elif path not in {"/", "/dashboard", "/favicon.ico"} and not self._require_authorized():
            return
        mode_error = _http_mode_gate_error("GET", path)
        if mode_error is not None:
            self._send(503, mode_error)
            return
        self._begin_trace(path)
        query = parse_qs(parsed.query)
        trace_store = getattr(APP, "debug_traces", None) if APP is not None else None
        trace_id = str(getattr(self, "_debug_trace_id", "") or "")
        if trace_store is not None and trace_id and query:
            try:
                trace_store.update(trace_id, request={"query": query})
            except Exception:
                pass
        allowed_agent_state_get = {
            "/api/agent-state/memory",
            "/api/agent-state/tasks",
            "/api/agent-state/events",
            "/api/agent-state/events/stream",
            "/api/agent-state/blackboard",
            "/api/agent-state/swarm",
        }
        if path.startswith("/api/agent-state/") and path not in allowed_agent_state_get and not path.startswith("/api/agent-state/swarm/"):
            self._send(403, {"success": False, "error": "agent_state route has no root-scoped access contract", "terminal": True, "retryable": False}); return
        if path == "/api/agent-state/memory" and not self._bind_memory_query(query):
            return
        if path in {"/api/agent-state/events", "/api/agent-state/events/stream"} and not self._bind_task_event_query(query):
            return
        if path == "/api/agent-state/blackboard" and not self._bind_task_board_query(query):
            return
        if path == "/api/agent-state/swarm" or path.startswith("/api/agent-state/swarm/"):
            if not self._bind_swarm_query(query):
                return
        root_scoped_repo_get_paths = {
            "/api/git/status", "/api/git/diff", "/api/git/history_search", "/api/git/synthesize_commit",
            "/api/repo_state", "/api/hotspots", "/api/topology", "/api/dead_code",
            "/api/symbol_callgraph", "/api/audit_dependencies", "/api/refactor_impact", "/api/test_matrix",
            "/api/resolve_imports", "/api/security_audit", "/api/search",
            "/api/preprocess", "/api/preprocess/status", "/api/coord/worktrees", "/api/worktrees",
        }
        if (
            path.startswith("/api/repo/")
            or path.startswith("/api/code/")
            or path in root_scoped_repo_get_paths
        ) and not self._bind_repository_root_query(query):
            return
        if path == "/api/cross_project_graph" and not self._bind_multi_repository_query(query):
            return
        if path == "/api/agent-state/tasks":
            task_identity = self._bind_root_tenant(
                (query.get("root") or [None])[0],
                query.get("tenant", []),
                allow_principal_header=True,
                require_configured_principal=True,
            )
            if task_identity is None:
                return
            query["root"], query["tenant"] = [[task_identity[0]], [task_identity[1]]]
        try:
            get_handler_name = select_get_handler(path)
            if get_handler_name is not None:
                getattr(self, get_handler_name)(query)
                return
            if path in {"/", "/dashboard"}:
                if not bool(APP.config.get("monitoring", {}).get("dashboard_enabled", True)) or not bool(APP.config.get("features", {}).get("dashboard", True)):
                    self._send(404, {"error": "dashboard disabled"}); return
                self._telemetry_finished = True
                self._send_html(200, _dashboard_html_with_trace_notice()); return
            if path == "/favicon.ico":
                self._telemetry_finished = True
                self.send_response(204); self.end_headers(); return
            if path == "/api/mode":
                try:
                    mode_api = _operational_mode_api()
                    jobs_path = getattr(getattr(APP, "async_jobs", None), "path", None)
                    config = getattr(APP, "config", {})
                    state_dir = Path(jobs_path).parent if jobs_path is not None else config.get("server", {}).get("state_dir", "state")
                    snapshot = mode_api.load_operational_mode(state_dir=state_dir)
                except Exception:
                    self._send(503, {"success": False, "error": "operational mode state unavailable", "retryable": True})
                    return
                response = {
                    "success": True,
                    "mode": str(getattr(snapshot, "mode", "maintenance")),
                    "revision": int(getattr(snapshot, "revision", -1)),
                    "degraded": bool(getattr(snapshot, "degraded", True)),
                }
                if response["mode"] == "gaming":
                    unload_status = _get_mode_unload_status(APP, response["revision"])
                    if unload_status is not None:
                        response["runtime_unload"] = _public_gaming_unload_status(unload_status)
                if response["degraded"]:
                    response["error"] = "operational mode state is invalid"
                self._send(200, response); return
            if path == "/api/status":
                detail = str((query.get("detail") or [""])[0]).strip().lower()
                if detail == "agent_state":
                    # The dependency-backed branch reads durable projections.
                    # Without an already-bound root it must stay capability-only;
                    # global task IDs/counts are never a valid monitor projection.
                    if not getattr(self, "_authorization_root", None):
                        requested_root = (query.get("root") or [""])[0]
                        if requested_root:
                            bound = self._bind_root_tenant(
                                requested_root,
                                query.get("tenant", []),
                                allow_principal_header=True,
                                require_configured_principal=True,
                            )
                            if bound is None:
                                return
                            query["root"], query["tenant"] = [[bound[0]], [bound[1]]]
                    if getattr(self, "_authorization_root", None) and hasattr(APP, "_status_dependency_lock"):
                        dependency_status: dict[str, dict[str, Any]] = {}
                        deadline = time.monotonic() + _STATUS_TOTAL_BUDGET_SECONDS

                        def read_agent_detail(key: str, callback, fallback):
                            timeout = min(_STATUS_DEPENDENCY_TIMEOUT_SECONDS, max(0.0, deadline - time.monotonic()))
                            value, healthy = _status_dependency(
                                callback, fallback, key=f"detail.agent_state.{key}",
                                lock=APP._status_dependency_lock, inflight=APP._status_dependency_inflight,
                                slots=APP._status_dependency_slots, timeout_seconds=timeout,
                            )
                            dependency_status[key] = {"deadline_ms": max(0, int(timeout * 1000)), "degraded": not healthy, "status": "ok" if healthy else "degraded"}
                            return value

                        scoped_root = str(getattr(self, "_authorization_root", "") or "")
                        scoped_tenant = str(getattr(self, "_authorization_tenant", "") or "")
                        tasks = read_agent_detail("tasks", APP.agent_tasks.list_tasks, []) if getattr(APP, "agent_tasks", None) else []
                        scoped_tasks = [
                            task for task in tasks
                            if self._task_matches_request(task, scoped_root, scoped_tenant)
                        ]
                        active_tasks = [getattr(t, "task_id", "") for t in scoped_tasks if getattr(t, "status", None) == TaskStatus.ACTIVE]
                        incidents = read_agent_detail("incidents", APP.agent_incidents.list_incidents, []) if getattr(APP, "agent_incidents", None) else []
                        repository_key = _incident_scope_key("repository", scoped_root)
                        tenant_key = _incident_scope_key("tenant", scoped_tenant)
                        scoped_incidents = [
                            incident for incident in incidents
                            if getattr(incident, "repository_key", "") == repository_key
                            and getattr(incident, "tenant_key", "") == tenant_key
                        ]
                        # Improvement candidates currently have no authenticated
                        # root/tenant provenance; never expose global candidates.
                        # Candidate records currently lack authenticated
                        # root/tenant provenance, so do not scan the global
                        # candidate store for this scoped projection.
                        scoped_candidates: list[Any] = []
                        degraded = any(item["degraded"] for item in dependency_status.values())
                        self._send(200, {
                            "success": not degraded,
                            "degraded": degraded,
                            "status": "degraded" if degraded else "ok",
                            "dependency_status": dependency_status,
                            "snapshot_cached": False,
                            "enabled": bool(getattr(APP, "agent_state", None) and APP.agent_state.enabled),
                            "active_tasks": active_tasks,
                            "tasks_count": len(scoped_tasks),
                            "incidents_count": len(scoped_incidents),
                            "candidates_count": len(scoped_candidates),
                        }); return
                    # Capability readiness only: global projection counts would
                    # disclose other roots/tenants and require an unbounded scan.
                    state = getattr(APP, "agent_state", None)
                    enabled = bool(state is not None and state.enabled)
                    initialized = bool(enabled and getattr(state, "_initialized", False))
                    self._send(200, {
                        "success": True,
                        "enabled": enabled,
                        "initialized": initialized,
                        "status": "ok" if enabled else "disabled",
                        "active_tasks": [],
                        "tasks_count": 0,
                        "incidents_count": 0,
                        "candidates_count": 0,
                    }); return
                scope = str((query.get("scope") or ["process"])[0])
                if detail in {"summary", "light"}:
                    status = APP.realtime_status(light=True, scope=scope)
                    status["detail_level"] = "summary"
                else:
                    status = APP.status(scope=scope)
                    status["detail_level"] = "full"
                if isinstance(self.server, LocalAIHTTPServer):
                    status["http_concurrency"] = self.server.concurrency_stats()
                self._send(200, status); return
            if path == "/api/agent-state/tasks":
                if not getattr(APP, "agent_tasks", None) or not APP.agent_tasks.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                request_root = (query.get("root") or [""])[0]
                request_tenant = (query.get("tenant") or [""])[0]
                task_id = (query.get("task_id") or [""])[0]
                if task_id:
                    task = self._request_task(task_id, request_root, request_tenant)
                    if task is None:
                        return
                    self._send(200, {"success": True, "task": task.to_dict()}); return
                status_filter = None
                if query.get("status"):
                    try:
                        status_filter = TaskStatus(str(query.get("status")[0]).strip().lower())
                    except ValueError:
                        pass
                limit = int((query.get("limit") or [100])[0])
                include_stale = str((query.get("include_stale") or ["false"])[0]).lower() in ("true", "1", "yes")
                task_query = (query.get("query") or [""])[0]
                tasks = APP.agent_tasks.list_tasks(
                    status=status_filter,
                    limit=limit,
                    include_stale=include_stale,
                    query=task_query,
                )
                response = {"success": True, "tasks": [t.to_dict() for t in tasks if self._task_matches_request(t, request_root, request_tenant)]}
                if getattr(tasks, "query_truncated", False):
                    response["query_truncated"] = True
                self._send(200, response); return
            if path == "/api/agent-state/memory":
                if not getattr(APP, "agent_memory", None) or not APP.agent_memory.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                rec_id = (query.get("record_id") or [""])[0]
                if rec_id:
                    scope_raw = (query.get("scope") or [None])[0]
                    scope_val = _parse_memory_scope(scope_raw)
                    scope_id_val = (query.get("scope_id") or [None])[0]
                    requested_root = (query.get("root") or [None])[0]
                    project_identity = self._memory_project_identity(requested_root)
                    if requested_root and project_identity is None:
                        self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
                    root_val, repository_id_val = project_identity or (None, None)
                    query_tenant = (query.get("tenant") or [None])[0]
                    explicit_tenant = self.headers.get("X-LocalAI-Tenant")
                    tenant_val = str(query_tenant).strip() if query_tenant else (str(explicit_tenant).strip() if explicit_tenant else None)
                    task_id_val = (query.get("task_id") or [None])[0]
                    session_id_val = (query.get("session_id") or [None])[0]
                    clone_id_val = (query.get("clone_id") or [None])[0]
                    worktree_id_val = (query.get("worktree_id") or [None])[0]
                    branch_val = (query.get("branch") or [None])[0]
                    scope_val, scope_id_val, ambiguous_scope = _resolve_memory_scope(
                        scope_val,
                        scope_id=scope_id_val,
                        root=root_val,
                        repository_id=repository_id_val,
                        tenant=tenant_val,
                        task_id=task_id_val,
                        session_id=session_id_val,
                        clone_id=clone_id_val,
                        worktree_id=worktree_id_val,
                        branch=branch_val,
                    )
                    if ambiguous_scope:
                        self._send(400, {"success": False, "error": "ambiguous memory scope identity", "terminal": True, "retryable": False}); return
                    if scope_val is None:
                        scope_val = AgentScope.GLOBAL
                    scope_id_val = self._bound_memory_scope_id(scope_val, scope_id_val, task_id_val)
                    if scope_val is AgentScope.TASK:
                        task_id_val = scope_id_val
                    elif scope_val is AgentScope.SESSION:
                        session_id_val = scope_id_val
                    matches = APP.agent_memory.find(
                            record_id=rec_id,
                            scope=scope_val,
                            scope_id=str(scope_id_val) if scope_id_val is not None else None,
                            root=str(root_val) if root_val else None,
                            repository_id=str(repository_id_val) if repository_id_val else None,
                            tenant=str(tenant_val) if tenant_val else None,
                            task_id=str(task_id_val) if task_id_val else None,
                            session_id=str(session_id_val) if session_id_val else None,
                            clone_id=str(clone_id_val) if clone_id_val else None,
                            worktree_id=str(worktree_id_val) if worktree_id_val else None,
                            branch=str(branch_val) if branch_val else None,
                            limit=1,
                    )
                    rec = matches[0] if matches else None
                    if not rec:
                        self._send(404, {"success": False, "error": "memory record not found", "terminal": True, "retryable": False}); return
                    self._send(200, {"success": True, "record": rec.to_dict()}); return
                scope_raw = (query.get("scope") or [None])[0]
                scope_val = _parse_memory_scope(scope_raw)
                key_val = (query.get("key") or [None])[0]
                query_val = (query.get("query") or [None])[0]
                status_raw = (query.get("status") or [None])[0]
                status_val = None
                if status_raw:
                    try:
                        status_val = MemoryStatus(str(status_raw).lower())
                    except ValueError:
                        pass
                limit_val = _memory_query_limit((query.get("limit") or [100])[0])
                scope_id_val = (query.get("scope_id") or [None])[0]
                requested_root = (query.get("root") or [None])[0]
                project_identity = self._memory_project_identity(requested_root)
                if requested_root and project_identity is None:
                    self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
                root_val, repository_id_val = project_identity or (None, None)
                query_tenant = (query.get("tenant") or [None])[0]
                explicit_tenant = self.headers.get("X-LocalAI-Tenant")
                tenant_val = str(query_tenant).strip() if query_tenant else (str(explicit_tenant).strip() if explicit_tenant else None)
                task_id_val = (query.get("task_id") or [None])[0]
                session_id_val = (query.get("session_id") or [None])[0]
                clone_id_val = (query.get("clone_id") or [None])[0]
                worktree_id_val = (query.get("worktree_id") or [None])[0]
                branch_val = (query.get("branch") or [None])[0]
                if not _memory_lookup_has_identity(
                    scope_id_val, root_val, repository_id_val, tenant_val, task_id_val,
                    session_id_val, clone_id_val, worktree_id_val, branch_val,
                ):
                    self._send(400, {"success": False, "error": "memory lookup requires explicit root or identity", "terminal": True, "retryable": False}); return
                scope_val, scope_id_val, ambiguous_scope = _resolve_memory_scope(
                    scope_val,
                    scope_id=scope_id_val,
                    root=root_val,
                    repository_id=repository_id_val,
                    tenant=tenant_val,
                    task_id=task_id_val,
                    session_id=session_id_val,
                    clone_id=clone_id_val,
                    worktree_id=worktree_id_val,
                    branch=branch_val,
                )
                if ambiguous_scope:
                    self._send(400, {"success": False, "error": "ambiguous memory scope identity", "terminal": True, "retryable": False}); return
                scope_id_val = self._bound_memory_scope_id(scope_val, scope_id_val, task_id_val)
                if scope_val is AgentScope.TASK:
                    task_id_val = scope_id_val
                elif scope_val is AgentScope.SESSION:
                    session_id_val = scope_id_val
                records = APP.agent_memory.find(
                    scope=scope_val if scope_raw is not None else None,
                    scope_id=str(scope_id_val) if scope_id_val is not None else None,
                    root=str(root_val) if root_val else None,
                    repository_id=str(repository_id_val) if repository_id_val else None,
                    tenant=str(tenant_val) if tenant_val else None,
                    task_id=str(task_id_val) if task_id_val else None,
                    session_id=str(session_id_val) if session_id_val else (str(scope_id_val) if (scope_raw is None and scope_val == AgentScope.SESSION) else None),
                    clone_id=str(clone_id_val) if clone_id_val else None,
                    worktree_id=str(worktree_id_val) if worktree_id_val else None,
                    branch=str(branch_val) if branch_val else None,
                    key=key_val,
                    query=query_val,
                    status=status_val,
                    limit=limit_val,
                )
                self._send(200, {"success": True, "records": [r.to_dict() for r in records]}); return
            if path == "/api/agent-state/events":
                agent_state = getattr(APP, "agent_state", None)
                stream_id = (query.get("stream_id") or [""])[0]
                after_seq = (query.get("after_seq") or [0])[0]
                through_seq = (query.get("through_seq") or [None])[0]
                limit = (query.get("limit") or [100])[0]
                try:
                    after_seq = max(0, min(int(after_seq), MAX_EVENT_SEQUENCE))
                except (TypeError, ValueError, OverflowError):
                    after_seq = 0
                if agent_state is None:
                    self._send(403, {
                        "success": False, "events": [], "next_seq": 0,
                        "first_retained_seq": 0, "last_seq": 0, "has_more": False,
                        "gap_ranges": [], "cursor_reset": False,
                        "error": {"code": "agent_state_disabled", "message": "agent state is disabled"},
                    }); return
                try:
                    requested_limit = int(limit)
                except (TypeError, ValueError, OverflowError):
                    requested_limit = 100
                snapshot_bound = None
                if through_seq is not None:
                    try:
                        snapshot_bound = int(through_seq)
                        if snapshot_bound < 0:
                            raise ValueError("through_seq cannot be negative")
                    except (TypeError, ValueError, OverflowError):
                        try:
                            error_cursor = max(0, int(after_seq))
                        except (TypeError, ValueError, OverflowError):
                            error_cursor = 0
                        self._send(400, {
                            "success": False, "events": [], "next_seq": error_cursor,
                            "first_retained_seq": 0, "last_seq": 0, "has_more": False,
                            "gap_ranges": [], "cursor_reset": False,
                            "error": {"code": "invalid_through_seq", "message": "through_seq must be a non-negative integer"},
                        }); return
                page_kwargs = {
                    "stream_id": stream_id,
                    "after_seq": after_seq,
                    "limit": max(1, min(requested_limit, AGENT_EVENT_PAGE_MAX_LIMIT)),
                }
                if snapshot_bound is not None:
                    page_kwargs["through_seq"] = through_seq
                try:
                    page = agent_state.event_page(**page_kwargs)
                except Exception as exc:
                    logger = getattr(APP, "logger", None)
                    if logger is not None:
                        logger.warning("agent event page failed error_type=%s", type(exc).__name__)
                    try:
                        error_cursor = max(0, int(after_seq))
                    except (TypeError, ValueError, OverflowError):
                        error_cursor = 0
                    self._send(503, {
                        "success": False,
                        "events": [],
                        "next_seq": error_cursor,
                        "first_retained_seq": 0,
                        "last_seq": 0,
                        "has_more": False,
                        "gap_ranges": [],
                        "cursor_reset": False,
                        "error": {"code": "event_page_unavailable", "message": "agent event page is temporarily unavailable"},
                        "retryable": True,
                        "terminal": False,
                    }); return
                status = 200 if page.get("success") is True else (
                    403 if (page.get("error") or {}).get("code") == "agent_state_disabled" else 503
                )
                status, page = _bound_agent_event_page(status, page, after_seq)
                self._send(status, page); return
            if path == "/api/agent-state/blackboard":
                if not getattr(APP, "agent_blackboard", None):
                    self._send(503, {"success": False, "error": "blackboard unavailable"}); return
                board_id = (query.get("board_id") or query.get("task_id") or [""])[0]
                section = (query.get("section") or [None])[0]
                self._send(200, APP.agent_blackboard.get(board_id, section=section)); return
            if path == "/api/agent-state/swarm":
                if not getattr(APP, "swarm", None):
                    self._send(503, {"success": False, "error": "swarm coordinator unavailable"}); return
                st = (query.get("state") or [None])[0]
                lim = int((query.get("limit") or [50])[0])
                root = (query.get("root") or [None])[0]
                self._send(200, APP.swarm.list_swarms(state=st, limit=lim, root=root)); return
            if path.startswith("/api/agent-state/swarm/"):
                swarm_id = path.split("/api/agent-state/swarm/", 1)[1].strip()
                if not getattr(APP, "swarm", None):
                    self._send(503, {"success": False, "error": "swarm coordinator unavailable"}); return
                root = (query.get("root") or [None])[0]
                self._send(200, APP.swarm.get_status(swarm_id, root=root)); return
            if path == "/api/agent-state/events/stream":
                if not getattr(APP, "agent_state", None) or not APP.agent_state.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                stream_filter = (query.get("stream_id") or [""])[0]
                kind_filter = (query.get("kind") or [""])[0]
                after_seq = max(0, min(int((query.get("after_seq") or [0])[0]), MAX_EVENT_SEQUENCE))
                timeout = float((query.get("timeout") or [0.0])[0])
                last_event_id = str(self.headers.get("Last-Event-ID", "") or (query.get("last_event_id") or [""])[0])
                self._stream_agent_events(
                    stream_id=stream_filter,
                    kind=kind_filter,
                    after_seq=after_seq,
                    timeout=timeout,
                    last_event_id=last_event_id,
                )
                return
            if path == "/api/capabilities":
                self._send(200, APP.capabilities()); return
            if path == "/api/benchmark/summary":
                if not getattr(APP, "benchmark_runner", None):
                    self._send(200, {"available": False}); return
                self._send(200, APP.benchmark_runner.get_latest_summary()); return
            if path == "/api/adoption":
                store = getattr(getattr(APP, "services", None), "adoption_metrics", None)
                if store is None:
                    self._send(200, {"success": True, "available": False}); return
                self._send(200, {"success": True, "available": True, "adoption": store.report(days=7)}); return
            if path == "/api/metrics":
                try:
                    days = int((query.get("days") or [30])[0])
                except (TypeError, ValueError, OverflowError):
                    self._send(400, {
                        "success": False,
                        "error": "days must be an integer",
                        "terminal": True,
                        "retryable": False,
                    }); return
                scope = str((query.get("scope") or ["window"])[0])
                try:
                    metrics = APP.telemetry.summary(days, scope=scope)
                except ValueError as exc:
                    self._send(400, {
                        "success": False, "error": str(exc), "terminal": True, "retryable": False,
                    }); return
                self._send(200, {"success": True, "metrics": metrics}); return
            if path == "/api/telemetry/report":
                try:
                    days = int((query.get("days") or [30])[0])
                except (TypeError, ValueError, OverflowError):
                    self._send(400, {
                        "success": False,
                        "error": "days must be an integer",
                        "terminal": True,
                        "retryable": False,
                    }); return
                scope = str((query.get("scope") or ["window"])[0])
                try:
                    recent_errors = int((query.get("recent_errors") or query.get("error_limit") or [25])[0])
                    error_offset = int((query.get("error_offset") or [0])[0])
                    error_cursor_values = parse_qs(parsed.query, keep_blank_values=True).get("error_cursor")
                    error_cursor = error_cursor_values[0] if error_cursor_values else None
                    if error_cursor_values is not None and "error_offset" in parse_qs(parsed.query, keep_blank_values=True):
                        raise ValueError("error_offset cannot be combined with error_cursor")
                except (TypeError, ValueError):
                    self._send(400, {
                        "success": False,
                        "error": "recent_errors and error_offset must be integers",
                        "terminal": True,
                        "retryable": False,
                    }); return
                try:
                    report = APP.telemetry.report(
                        days, recent_errors=recent_errors, error_offset=error_offset,
                        error_cursor=error_cursor, scope=scope,
                    )
                except ValueError as exc:
                    self._send(400, {
                        "success": False, "error": str(exc), "terminal": True, "retryable": False,
                    }); return
                self._send(200, {"success": True, "report": report}); return
            if path == "/api/telemetry/timeline":
                limit = (query.get("limit") or [100])[0]
                before_id = (query.get("before_id") or [None])[0]
                try:
                    page = APP.telemetry.get_timeline_page(limit, before_id=before_id)
                except (TypeError, ValueError):
                    raise
                except Exception as exc:
                    logger = getattr(APP, "logger", None)
                    if logger is not None:
                        logger.warning("telemetry timeline page failed error_type=%s", type(exc).__name__)
                    self._send(503, {
                        "success": False,
                        "error": {"code": "telemetry_page_unavailable", "message": "telemetry timeline is temporarily unavailable"},
                        "status_code": 503,
                        "retryable": True,
                        "terminal": False,
                    }); return
                self._send(200, {"success": True, **page}); return
            if path == "/api/audit/tail":
                try:
                    limit = int((query.get("limit") or [20])[0])
                except (TypeError, ValueError, OverflowError):
                    self._send(400, {
                        "success": False,
                        "error": "limit must be an integer",
                        "terminal": True,
                        "retryable": False,
                    }); return
                self._send(200, {"success": True, "events": APP.telemetry.tail(limit)}); return
            if path == "/api/debug-traces":
                try:
                    trace_min_duration = int((query.get("min_duration_ms") or [0])[0])
                    trace_action = str((query.get("action") or [""])[0])
                    if not 0 <= trace_min_duration <= 86_400_000 or len(trace_action) > 64:
                        raise ValueError("trace filter outside allowed bounds")
                except (TypeError, ValueError, OverflowError):
                    self._send(400, {"success": False, "error": "trace filters require min_duration_ms=0..86400000 and action of at most 64 characters", "terminal": True, "retryable": False}); return
                result = APP.debug_traces.list(
                    kind=str((query.get("kind") or [""])[0]),
                    state=str((query.get("state") or [""])[0]),
                    agent=str((query.get("agent") or [""])[0]),
                    model=str((query.get("model") or [""])[0]),
                    action=trace_action.strip(),
                    min_duration_ms=trace_min_duration,
                    limit=_query_int(query, "limit", 50),
                    offset=_query_int(query, "offset", 0),
                )
                for item in result.get("items", []):
                    self._reconcile_debug_trace(item)
                self._send(200 if result.get("success") else 503 if result.get("retryable") else 400, result); return
            trace_prefix = "/api/debug-traces/"
            metrics_suffix = "/metrics"
            if path.startswith(trace_prefix) and path.endswith(metrics_suffix):
                trace_id = path[len(trace_prefix):-len(metrics_suffix)]
                if not trace_id or "/" in trace_id:
                    self._send(404, {"success": False, "error": "trace not found"}); return
                try:
                    request_id = APP.debug_traces.request_id_for_trace(trace_id)
                    if request_id is None:
                        self._send(404, {"success": False, "error": "trace not found"}); return
                    metrics_provider = getattr(getattr(APP, "telemetry", None), "request_metrics", None)
                    if not callable(metrics_provider):
                        raise RuntimeError("trace telemetry unavailable")
                    metrics = metrics_provider(request_id)
                except Exception as exc:
                    logger = getattr(APP, "logger", None)
                    warning = getattr(logger, "warning", None)
                    if callable(warning):
                        warning("debug trace metrics unavailable error_type=%s", type(exc).__name__)
                    self._send(503, {
                        "success": False,
                        "error": "trace metrics are temporarily unavailable",
                        "retryable": True,
                        "terminal": False,
                    }); return
                self._send(200, {"success": True, "trace_id": trace_id, "metrics": metrics}); return
            if path.startswith("/api/debug-traces/"):
                trace_id = path.rsplit("/", 1)[-1]
                detail_args = {
                    "since_seq": _query_int(query, "since_seq", 0),
                    "limit": _query_int(query, "limit", 100),
                    "max_bytes": max(
                        1024,
                        min(
                            _query_int(query, "max_bytes", DEBUG_TRACE_HTTP_MAX_BYTES),
                            DEBUG_TRACE_HTTP_MAX_BYTES,
                        ),
                    ),
                    "before_seq": _query_int(query, "before_seq", 0),
                    "full_payload": str((query.get("full") or [""])[0]).strip().lower()
                    in {"1", "true", "yes", "on"},
                    "content_field": str((query.get("content_field") or [""])[0])[:64],
                    "content_offset": _query_int(query, "content_offset", 0),
                }
                result = APP.debug_traces.detail(trace_id, **detail_args)
                if result.get("error") == "trace not found":
                    self._send(404, result); return
                if result.get("error_code") == "trace_detail_oversize":
                    self._send(413, result); return
                if result.get("success") and isinstance(result.get("session"), dict):
                    session = result["session"]
                    session_before = _json_bytes(session)
                    session = self._reconcile_debug_trace(session)
                    if _json_bytes(session) != session_before:
                        # Rebuild page after reconciliation so response_bytes still
                        # describes exact response, including refreshed session data.
                        result = APP.debug_traces.detail(trace_id, **detail_args)
                        if result.get("error_code") == "trace_detail_oversize":
                            self._send(413, result); return
                        if result.get("error") == "trace not found":
                            self._send(404, result); return
                        session = result.get("session", {})
                    result["terminal"] = session.get("state") in APP.debug_traces.TERMINAL_STATES
                self._send(200, result); return
            if path == "/api/rag/workspaces":
                self._send(200, {"success": True, "workspaces": APP.rag.list_workspaces(self._tenant())}); return
            if path == "/api/leases":
                root = (query.get("root") or [""])[0]
                coordination_id = _lease_coordination_id(root)
                self._send(200, {"success": True, "leases": APP.leases.list(root, coordination_id=coordination_id), "waits": APP.leases.waits(root, coordination_id=coordination_id)}); return
            if path == "/api/cross_project_graph":
                roots = [str(root) for root in query.get("roots", []) if root]
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.cross_project_graph(roots))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/repo/dead_code", "/api/dead_code"}:
                root = (query.get("root") or ["."])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.services.dead_code(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/symbol_callgraph":
                root = (query.get("root") or ["."])[0]
                sym = (query.get("symbol") or [None])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.symbol_callgraph(root, sym))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/hardware/gpu":
                from .gpu_monitor import get_gpu_telemetry
                self._send(200, get_gpu_telemetry())
                return
            if path == "/api/hardware/system":
                from .gpu_monitor import get_system_telemetry
                self._send(200, get_system_telemetry())
                return
            if path == "/api/audit_dependencies":
                root = (query.get("root") or ["."])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.audit_dependencies(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/refactor_impact":
                root = (query.get("root") or ["."])[0]
                file_param = (query.get("file") or [""])[0]
                symbol_param = (query.get("symbol") or [None])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.services.refactor_impact(root, file_param, symbol_param))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/test_matrix":
                root = (query.get("root") or ["."])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.services.test_matrix(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/repo/affected_tests", "/api/affected_tests"}:
                root = (query.get("root") or ["."])[0]
                paths = query.get("path") or query.get("paths") or None
                if APP.deterministic is not None:
                    self._send(200, APP.services.affected_tests(root, changed_paths=paths))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/repo/topology", "/api/topology"}:
                root = (query.get("root") or ["."])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.services.repo_topology(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/db/query":
                db_name = (query.get("db") or ["agent_state"])[0]
                sql_q = (query.get("query") or ["SELECT name FROM sqlite_master WHERE type='table'"])[0]
                self._send(200, self._handle_db_query(db_name, sql_q))
                return
            if path == "/api/models/manage":
                self._send(200, self._handle_models_list())
                return
            if path == "/api/security_audit":
                root = (query.get("root") or ["."])[0]
                limit = int((query.get("limit") or [50])[0])
                if APP.deterministic is not None:
                    self._send(200, APP.services.security_audit(root, limit))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/code/ast_outline":
                root = (query.get("root") or ["."])[0]
                path_param = (query.get("path") or [""])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.services.ast_outline(root, path_param))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/maintenance/optimize_db":
                self._send(405, {"success": False, "error": "method not allowed"}, headers={"Allow": "POST"})
                return
            if path == "/api/maintenance/purge_cache":
                self._send(405, {"success": False, "error": "method not allowed"}, headers={"Allow": "POST"})
                return
            if path == "/api/maintenance/resolve_errors":
                self._send(405, {"success": False, "error": "method not allowed"}, headers={"Allow": "POST"})
                return
            if path == "/api/config":
                view = _redact_config_secrets(APP.config)
                self._send(200, {
                    "success": True,
                    "config": view,
                    "config_path": _safe_config_file_label(APP.config.get("_config_path", "")),
                    "runtime_override_path": _safe_config_file_label(APP.config.get("_runtime_override_path", "")),
                })
                return
            if path == "/api/logs/tail":
                try:
                    lines = max(1, min(int((query.get("lines") or [200])[0]), 1000))
                    log_path = Path(APP.config["server"]["state_dir"]) / "logs" / "hub.log"
                    if not log_path.is_file():
                        self._send(200, {"success": True, "lines": []}); return
                    with log_path.open("rb") as fh:
                        fh.seek(0, 2); size = fh.tell(); fh.seek(max(0, size - 512 * 1024))
                        text = fh.read(512 * 1024).decode("utf-8", errors="replace")
                    self._send(200, {"success": True, "lines": text.splitlines()[-lines:]})
                except (OSError, ValueError):
                    self._send(400, {
                        "success": False,
                        "error": "log tail unavailable",
                        "error_code": "log_tail_unavailable",
                        "terminal": True,
                        "retryable": False,
                    })
                return
            if path == "/api/doctor":
                self._send(200, APP.services.run_doctor())
                return
            if path in {"/api/preprocess", "/api/preprocess/status"}:
                root = (query.get("root") or [None])[0]
                self._send(200, APP.preprocessor.status(root))
                return
            if path == "/api/code/symbol":
                root = (query.get("root") or ["."])[0]
                sym = (query.get("symbol") or [""])[0]
                self._send(200, APP.services.code_inspect_symbol(root, sym))
                return
            if path == "/api/code/find_symbol":
                root = (query.get("root") or ["."])[0]
                pat = (query.get("pattern") or query.get("name_path_pattern") or [""])[0]
                depth = int((query.get("depth") or [0])[0])
                include_body = _parse_include_body((query.get("include_body") or [None])[0], query=True)
                if include_body is None:
                    self._send(400, {"success": False, "error": "include_body must be a boolean"})
                    return
                rel_path = (query.get("path") or query.get("relative_path") or [None])[0]
                self._send(200, APP.services.code_find_symbol(root, pat, depth=depth, include_body=include_body, relative_path=rel_path))
                return
            if path == "/api/code/find_declaration":
                root = (query.get("root") or ["."])[0]
                sym = (query.get("symbol") or query.get("name") or [""])[0]
                rel_path = (query.get("path") or [None])[0]
                self._send(200, APP.services.code_find_declaration(root, sym, path=rel_path))
                return
            if path == "/api/code/find_implementations":
                root = (query.get("root") or ["."])[0]
                sym = (query.get("symbol") or query.get("name") or [""])[0]
                rel_path = (query.get("path") or [None])[0]
                self._send(200, APP.services.code_find_implementations(root, sym, path=rel_path))
                return
            if path == "/api/code/find_referencing_symbols":
                root = (query.get("root") or ["."])[0]
                sym = (query.get("symbol") or query.get("name") or [""])[0]
                rel_path = (query.get("path") or [None])[0]
                self._send(200, APP.services.code_find_referencing_symbols(root, sym, path=rel_path))
                return
            if path == "/api/code/symbols_overview":
                root = (query.get("root") or ["."])[0]
                fpath = (query.get("path") or [""])[0]
                depth = int((query.get("depth") or [1])[0])
                self._send(200, APP.services.code_symbols_overview(root, fpath, depth=depth))
                return
            if path == "/api/code/diagnostics":
                root = (query.get("root") or ["."])[0]
                fpath = (query.get("path") or [""])[0]
                self._send(200, APP.services.code_diagnostics(root, fpath))
                return
            if path == "/api/resolve_imports":
                root = (query.get("root") or ["."])[0]
                lang = (query.get("language") or ["auto"])[0]
                symbols = [s for s in (query.get("symbols") or (query.get("symbol") or [])) if s]
                if APP.deterministic is not None:
                    self._send(200, APP.services.resolve_imports(root, symbols, lang))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/coord/worktrees", "/api/worktrees"}:
                root = (query.get("root") or ["."])[0]
                self._send(200, APP.services.list_worktrees(root))
                return

            if path == "/api/git/status":
                root = (query.get("root") or ["."])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.git_status(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/repo/state", "/api/repo_state"}:
                root = (query.get("root") or ["."])[0]
                tracker = getattr(APP, "repo_state", None) or (getattr(APP.services, "repo_state", None) if getattr(APP, "services", None) else None)
                if tracker is not None:
                    try:
                        self._send(200, tracker.fingerprint(root))
                    except Exception:
                        self._send(200, {
                            "success": False,
                            "error": "repo state unavailable",
                            "error_code": "repo_state_unavailable",
                        })
                else:
                    self._send(200, {"success": False, "error": "repo_state tracker unavailable"})
                return
            if path == "/api/git/diff":
                root = (query.get("root") or ["."])[0]
                p = (query.get("path") or [None])[0]
                staged = (query.get("staged") or ["false"])[0].lower() in {"1", "true", "yes"}
                if APP.deterministic is not None:
                    revisions = {key: query[key][0] for key in ("rev1", "rev2") if key in query}
                    max_lines = int((query.get("max_lines") or [1000])[0])
                    self._send(200, APP.services.git_diff(root, path=p, staged=staged, max_lines=max_lines, **revisions))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/git/history_search":
                from .deterministic import _git_history_pathspec, _git_history_timestamp

                root = (query.get("root") or ["."])[0]
                q = (query.get("query") or [""])[0]
                raw_max_c = (query.get("max_commits") or ["20"])[0]
                if not isinstance(raw_max_c, str) or not raw_max_c.isascii() or not raw_max_c.isdigit():
                    self._send(400, {"success": False, "error": "max_commits must be an integer from 1 to 100", "terminal": True, "retryable": False}); return
                max_c = int(raw_max_c)
                if not 1 <= max_c <= 100:
                    self._send(400, {"success": False, "error": "max_commits must be an integer from 1 to 100", "terminal": True, "retryable": False}); return
                filters = {
                    name: (query.get(name) or [None])[0]
                    for name in ("author", "since", "until", "path")
                }
                if (
                    not isinstance(q, str)
                    or not q.strip()
                    or len(q) > 512
                    or any(ord(char) < 32 or ord(char) == 127 for char in q)
                ):
                    self._send(400, {"success": False, "error": "query must be a bounded literal string", "terminal": True, "retryable": False}); return
                for name, value in filters.items():
                    maximum = 256 if name == "author" else 64 if name in {"since", "until"} else 4096
                    if value is not None and (
                        not isinstance(value, str)
                        or len(value) > maximum
                        or any(ord(char) < 32 or ord(char) == 127 for char in value)
                    ):
                        self._send(400, {"success": False, "error": f"{name} must be a bounded string", "terminal": True, "retryable": False}); return
                try:
                    since_epoch, _since = _git_history_timestamp(filters["since"], "since", upper_bound=False)
                    until_epoch, _until = _git_history_timestamp(filters["until"], "until", upper_bound=True)
                    _git_history_pathspec(root, filters["path"])
                except (OSError, RuntimeError, TypeError, ValueError, OverflowError) as exc:
                    self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if since_epoch is not None and until_epoch is not None and since_epoch > until_epoch:
                    self._send(400, {"success": False, "error": "since must be earlier than or equal to until", "terminal": True, "retryable": False}); return
                if APP.deterministic is not None:
                    result = APP.services.git_history_search(
                        root,
                        q,
                        max_commits=max_c,
                        author=filters["author"],
                        since=filters["since"],
                        until=filters["until"],
                        path=filters["path"],
                    )
                    result_status = result.get("status_code") if isinstance(result, dict) else None
                    status = (
                        result_status
                        if isinstance(result_status, int) and not isinstance(result_status, bool)
                        and 400 <= result_status <= 599
                        else 200
                    )
                    self._send(status, result)
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/git/synthesize_commit":
                root = (query.get("root") or ["."])[0]
                hint = (query.get("hint") or [""])[0]
                task_id = (query.get("task_id") or [""])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.services.synthesize_commit(root, hint, task_id=task_id))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/models":
                models = APP.runtime.installed_models()
                self._send(200, {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "ollama"} for m in models]}); return
            self._send(404, {"error": "not found"})
        except (ValueError, TypeError, RequestBodyError) as exc:
            self._send(400, {"success": False, "error": str(exc), "status_code": 400, "terminal": True, "retryable": False})
        except KeyError as exc:
            self._send(404, {"success": False, "error": str(exc), "status_code": 404, "terminal": True, "retryable": False})
        except Exception as exc:
            if _is_client_disconnect(exc):
                self._finish_debug_trace(499, {"success": False, "terminal": True}, error="client disconnected")
                self._close_trace_context()
                return
            if is_busy_error(exc):
                self._send_database_locked()
                return
            try:
                logger = getattr(APP, "logger", None)
                if logger is not None:
                    logger.error("GET request failed error_type=%s", type(exc).__name__)
                self._send(500, {
                    "success": False,
                    "error": "internal server error",
                    "error_code": "internal_error",
                    "terminal": True,
                    "retryable": False,
                })
            except Exception:
                pass

    def _claim_recovery(self, path: str, payload: Any) -> bool:
        if APP is None:
            return True
        recovery = getattr(APP, "recovery", None)
        if recovery is None or not callable(getattr(recovery, "begin", None)):
            return True
        request_id = str(getattr(self, "_trace_request_id", ""))
        tenant = self._tenant()
        identity = str(self._agent() or "")
        self._journal_request_id = request_id
        self._journal_finished = False
        try:
            claim = recovery.begin(
                request_id,
                tenant,
                path,
                identity=identity,
                payload=payload,
            )
        except Exception:
            self._journal_finished = True
            self._send(503, {
                "success": False,
                "error": "request journal unavailable; mutation was not dispatched",
                "status_code": 503,
                "retryable": True,
                "outcome_unknown": False,
            })
            return False

        if not isinstance(claim, Mapping):
            self._journal_finished = True
            self._send(503, {
                "success": False,
                "error": "request journal unavailable; mutation was not dispatched",
                "status_code": 503,
                "retryable": True,
                "outcome_unknown": False,
            })
            return False
        if claim.get("claimed"):
            return True

        self._journal_finished = True
        state = str(claim.get("state", ""))
        if state == "conflict":
            self._send(409, {"success": False, "error": claim.get("error", "request id conflict"), "terminal": True})
            return False
        if state in {"done", "failed"} and claim.get("response") is not None:
            status = int(claim.get("status_code") or (200 if state == "done" else 500))
            self._send(status, claim["response"])
            return False
        if state == "running":
            app_cfg = getattr(APP, "config", None) if APP is not None else None
            singleflight_timeout = (
                app_cfg.get("resilience", {}).get("singleflight_wait_timeout_seconds", 1.0)
                if isinstance(app_cfg, dict) else 1.0
            )
            wait_seconds = min(
                2.0,
                max(0.05, float(singleflight_timeout)),
            )
            try:
                replay = APP.recovery.wait_for(
                    request_id,
                    tenant,
                    path,
                    timeout_seconds=wait_seconds,
                    identity=identity,
                    payload_fingerprint=APP.recovery.fingerprint_payload(payload),
                )
            except Exception:
                self._send(409, {
                    "success": False,
                    "error": "request outcome is unknown; mutation was not replayed",
                    "status_code": 409,
                    "terminal": True,
                    "retryable": False,
                    "outcome_unknown": True,
                    "request_id": request_id,
                })
                return False
            if replay and replay.get("state") in {"done", "failed"} and replay.get("response") is not None:
                status = int(replay.get("status_code") or (200 if replay.get("state") == "done" else 500))
                self._send(status, replay["response"])
                return False
            if replay and replay.get("outcome_unknown"):
                self._send(409, {
                    "success": False,
                    "error": "request outcome is unknown; mutation was not replayed",
                    "terminal": True,
                    "retryable": False,
                    "outcome_unknown": True,
                })
                return False
            self._send(409, {
                "success": False,
                "error": "request with this id is already running",
                "retryable": True,
                "in_progress": True,
                "retry_after_seconds": 1,
                "waited_seconds": wait_seconds,
            })
            return False
        if claim.get("outcome_unknown") or state == "abandoned":
            self._send(409, {
                "success": False,
                "error": "request outcome is unknown; mutation was not replayed",
                "terminal": True,
                "retryable": False,
                "outcome_unknown": True,
            })
            return False
        self._send(409, {"success": False, "error": "request journal returned an invalid state", "terminal": True})
        return False

    def _handle_post_artifact_get(self, payload: dict[str, Any], tenant: str) -> None:
        effective_tenant = tenant
        allowed_fields = {"artifact_id", "offset", "max_chars", "section", "binary", "slices"}
        if not isinstance(payload, dict) or set(payload) - allowed_fields:
            self._send(400, {"success": False, "error": "artifact request contains unsupported fields", "terminal": True, "retryable": False})
            return
        artifact_id = payload.get("artifact_id", "")
        offset = payload.get("offset", 0)
        max_chars = payload.get("max_chars", 6000)
        section = payload.get("section", "")
        binary = payload.get("binary", False)
        if not isinstance(artifact_id, str) or not artifact_id:
            self._send(400, {"success": False, "error": "artifact_id must be a non-empty string", "terminal": True, "retryable": False})
            return
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            self._send(400, {"success": False, "error": "offset must be a non-negative integer", "terminal": True, "retryable": False})
            return
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 1 <= max_chars <= 50_000:
            self._send(400, {"success": False, "error": "max_chars must be between 1 and 50000", "terminal": True, "retryable": False})
            return
        if not isinstance(section, str) or len(section) > 512:
            self._send(400, {"success": False, "error": "section must be a string of at most 512 characters", "terminal": True, "retryable": False})
            return
        if not isinstance(binary, bool):
            self._send(400, {"success": False, "error": "binary must be a boolean", "terminal": True, "retryable": False})
            return
        if "slices" in payload and not isinstance(payload["slices"], list):
            self._send(400, {"success": False, "error": "slices must be an array", "terminal": True, "retryable": False})
            return
        slices = payload.get("slices")
        if slices is not None:
            if binary or set(payload) - {"artifact_id", "slices", "binary"}:
                self._send(400, {"success": False, "error": "multi-slice retrieval accepts only artifact_id, slices, and binary=false", "terminal": True, "retryable": False})
                return
            if not 1 <= len(slices) <= 16:
                self._send(400, {"success": False, "error": "slices must contain 1 to 16 ranges", "terminal": True, "retryable": False})
                return
            requested = 0
            for item in slices:
                if not isinstance(item, dict) or set(item) != {"offset", "max_chars"}:
                    self._send(400, {"success": False, "error": "each slice must contain only offset and max_chars", "terminal": True, "retryable": False})
                    return
                item_offset, item_max = item["offset"], item["max_chars"]
                if isinstance(item_offset, bool) or not isinstance(item_offset, int) or item_offset < 0:
                    self._send(400, {"success": False, "error": "slice offset must be a non-negative integer", "terminal": True, "retryable": False})
                    return
                if isinstance(item_max, bool) or not isinstance(item_max, int) or not 1 <= item_max <= 50_000:
                    self._send(400, {"success": False, "error": "slice max_chars must be between 1 and 50000", "terminal": True, "retryable": False})
                    return
                requested += item_max
                if requested > 50_000:
                    self._send(400, {"success": False, "error": "combined slice max_chars cannot exceed 50000", "terminal": True, "retryable": False})
                    return
            self._send(200, APP.artifacts.get_slices(artifact_id, slices, tenant=effective_tenant))
            return
        if binary:
            if section:
                self._send(400, {"success": False, "error": "section is not valid for binary retrieval", "terminal": True, "retryable": False})
                return
            self._send(200, APP.artifacts.get_binary(artifact_id, tenant=effective_tenant))
            return
        self._send(200, APP.artifacts.get(
            artifact_id,
            offset,
            max_chars,
            section,
            tenant=effective_tenant,
        ))

    def _handle_post_artifact_list(self, payload: dict[str, Any], tenant: str) -> None:
        if not isinstance(payload, dict) or set(payload) - {"limit"}:
            self._send(400, {"success": False, "error": "artifact list accepts only limit", "terminal": True, "retryable": False})
            return
        limit = payload.get("limit", 20)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            self._send(400, {"success": False, "error": "limit must be a positive integer", "terminal": True, "retryable": False})
            return
        if not isinstance(tenant, str) or not tenant.strip():
            self._send(403, {"success": False, "error": "authenticated tenant is required", "terminal": True, "retryable": False})
            return
        self._send(200, {"success": True, "artifacts": APP.artifacts.list(tenant=tenant, limit=limit)})

    def _handle_post_lease_claim(self, payload: dict[str, Any], tenant: str) -> None:
        allowed_fields = {"root", "paths", "ttl_seconds", "purpose", "coordination_id"}
        if not isinstance(payload, dict) or set(payload) - allowed_fields:
            self._send(400, {"success": False, "error": "lease claim contains unsupported fields", "terminal": True, "retryable": False})
            return
        root = payload.get("root", ".")
        paths = payload.get("paths", [])
        ttl_seconds = payload.get("ttl_seconds", 900)
        purpose = payload.get("purpose", "agent edit")
        if not isinstance(root, str) or not root.strip() or "\x00" in root:
            self._send(400, {"success": False, "error": "root must be a non-empty string", "terminal": True, "retryable": False})
            return
        if not isinstance(paths, list) or any(not isinstance(path, str) or not path.strip() or "\x00" in path for path in paths):
            self._send(400, {"success": False, "error": "paths must be an array of non-empty strings", "terminal": True, "retryable": False})
            return
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds < 1:
            self._send(400, {"success": False, "error": "ttl_seconds must be a positive integer", "terminal": True, "retryable": False})
            return
        if not isinstance(purpose, str) or "\x00" in purpose:
            self._send(400, {"success": False, "error": "purpose must be a string", "terminal": True, "retryable": False})
            return
        if not isinstance(tenant, str) or not tenant.strip():
            self._send(403, {"success": False, "error": "authenticated tenant is required", "terminal": True, "retryable": False})
            return
        coordination_id = _lease_coordination_id(root)
        self._send(200, APP.leases.claim_batch(
            tenant, root, paths, ttl_seconds, purpose, coordination_id=coordination_id,
        ))

    def _handle_post_lease_release(self, payload: dict[str, Any], tenant: str) -> None:
        if not isinstance(payload, dict) or set(payload) != {"lease_id"}:
            self._send(400, {"success": False, "error": "lease release requires only lease_id", "terminal": True, "retryable": False})
            return
        lease_id = payload["lease_id"]
        if not isinstance(lease_id, str) or not lease_id.strip() or "\x00" in lease_id:
            self._send(400, {"success": False, "error": "lease_id must be a non-empty string", "terminal": True, "retryable": False})
            return
        if not isinstance(tenant, str) or not tenant.strip():
            self._send(403, {"success": False, "error": "authenticated tenant is required", "terminal": True, "retryable": False})
            return
        self._send(200, APP.leases.release(tenant, lease_id))

    def _handle_post_lease_renew(self, payload: dict[str, Any], tenant: str) -> None:
        if not isinstance(payload, dict) or set(payload) - {"lease_id", "ttl_seconds"}:
            self._send(400, {"success": False, "error": "lease renewal contains unsupported fields", "terminal": True, "retryable": False})
            return
        lease_id = payload.get("lease_id")
        ttl_seconds = payload.get("ttl_seconds", 900)
        if not isinstance(lease_id, str) or not lease_id.strip() or "\x00" in lease_id:
            self._send(400, {"success": False, "error": "lease_id must be a non-empty string", "terminal": True, "retryable": False})
            return
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds < 1:
            self._send(400, {"success": False, "error": "ttl_seconds must be a positive integer", "terminal": True, "retryable": False})
            return
        if not isinstance(tenant, str) or not tenant.strip():
            self._send(403, {"success": False, "error": "authenticated tenant is required", "terminal": True, "retryable": False})
            return
        self._send(200, APP.leases.renew(tenant, lease_id, ttl_seconds))

    @staticmethod
    def _context_retrieval_mode(payload: Mapping[str, Any]) -> str | None:
        raw_mode = payload.get("mode", "adaptive")
        return raw_mode if isinstance(raw_mode, str) and raw_mode in {"adaptive", "full", "fast"} else None

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        post_route_ids = select_http_routes("POST", path)
        if not post_route_ids:
            self._send(404, {
                "success": False,
                "error": "route not found",
                "terminal": True,
                "retryable": False,
            })
            return
        self._handler_execution_started = time.perf_counter()
        if APP is None:
            self._send(503, {"success": False, "error": "hub starting up; please retry", "status_code": 503, "retryable": True})
            return
        if not self._require_authorized():
            return
        early_mode_rejection = None
        if path != "/api/context/pack":
            early_mode_rejection = _http_mode_gate_error("POST", path)
        if early_mode_rejection is not None and early_mode_rejection.get("mode") == "maintenance":
            status = 423 if early_mode_rejection.get("error_code") == "operational_mode_blocked" else 503
            self._send(status, early_mode_rejection)
            return
        self._begin_trace(path)
        if getattr(APP, "recovery", None) is not None:
            try:
                request_id = RecoveryJournal.validate_request_id(self._ensure_trace_request_id())
            except (TypeError, ValueError) as exc:
                self._journal_finished = True
                self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False})
                return
            self._trace_request_id = request_id
        if path == "/api/admin/mode":
            try:
                payload = self._read_json()
            except RequestBodyError as exc:
                self._send(exc.status, {
                    "success": False, "error": str(exc), "error_code": "invalid_mode_request",
                    "terminal": True, "retryable": False,
                }); return
            mode = payload.get("mode")
            if set(payload) != {"mode"} or not isinstance(mode, str):
                self._send(400, {
                    "success": False, "error": "request must contain only a string mode",
                    "error_code": "invalid_mode_request", "terminal": True, "retryable": False,
                }); return
            async_jobs = getattr(APP, "async_jobs", None)
            mode_changed = getattr(async_jobs, "on_operational_mode_changed", None)
            guard_factory = getattr(async_jobs, "operational_mode_change_guard", None)
            guard = guard_factory() if callable(guard_factory) else nullcontext()
            cancellation_error = ""
            release_token = None
            api = _operational_mode_api()
            load_fn = getattr(api, "load_operational_mode", load_operational_mode)
            set_fn = getattr(api, "set_operational_mode", set_operational_mode)
            mode_changed_value = False
            try:
                with guard:
                    jobs_path = getattr(async_jobs, "path", None)
                    if jobs_path is not None:
                        state_dir = Path(jobs_path).parent
                    else:
                        app_cfg = getattr(APP, "config", None)
                        state_dir = app_cfg.get("server", {}).get("state_dir", "state") if isinstance(app_cfg, dict) else "state"
                    try:
                        current_mode = load_fn(state_dir=state_dir)
                    except TypeError:
                        current_mode = load_fn(state_dir)
                    requested_mode = str(mode).strip().lower().replace("-", "_")
                    release_active = getattr(async_jobs, "resource_release_active", None)
                    release_in_progress = bool(release_active()) if callable(release_active) else False
                    if (
                        requested_mode == "active" and current_mode.mode != "active"
                        and (release_in_progress or _ACTIVE_TRANSCRIPTIONS.active_count() or _ACTIVE_CONVERSATIONS.active_count())
                    ):
                        self._send(423, {
                            "success": False, "error": "cannot reactivate while inference or resource cleanup is active",
                            "error_code": "resource_release_in_progress" if release_in_progress else "inference_active", "mode_changed": False,
                            "mode": current_mode.mode, "revision": current_mode.revision,
                            "terminal": False, "retryable": True, "retry_after_seconds": 1,
                        }); return
                    try:
                        sig = inspect.signature(set_fn)
                        first_param = list(sig.parameters.keys())[0] if sig.parameters else ""
                        if first_param in {"state_dir", "state", "root"}:
                            snapshot = set_fn(state_dir, mode)
                        else:
                            snapshot = set_fn(mode, state_dir)
                    except Exception:
                        try:
                            snapshot = set_fn(state_dir, mode)
                        except (TypeError, ValueError):
                            snapshot = set_fn(mode, state_dir)
                    mode_changed_value = snapshot.mode != current_mode.mode
                    if snapshot.mode == "gaming":
                        _ACTIVE_TRANSCRIPTIONS.enter_gaming()
                        _ACTIVE_CONVERSATIONS.enter_gaming()
                    elif snapshot.mode == "active":
                        _ACTIVE_TRANSCRIPTIONS.enter_active()
                        _ACTIVE_CONVERSATIONS.enter_active()
                    if callable(mode_changed):
                        try:
                            mode_changed(snapshot)
                        except Exception as exc:
                            cancellation_error = type(exc).__name__
                    if snapshot.mode == "gaming" and async_jobs is not None:
                        begin_release = getattr(async_jobs, "begin_resource_release", None)
                        if callable(begin_release):
                            release_token = begin_release()
            except ValueError as exc:
                self._send(400, {
                    "success": False, "error": str(exc), "error_code": "invalid_mode_request",
                    "terminal": True, "retryable": False,
                }); return
            except OSError:
                self._send(503, {
                    "success": False, "error": "operational mode could not be persisted",
                    "error_code": "mode_persistence_failed", "terminal": True, "retryable": True,
                }); return
            self._telemetry_finished = True
            snap_dict = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot.__dict__)
            response = {"success": True, **snap_dict, "mode_changed": mode_changed_value}
            runtime_unload: dict[str, Any] | None = None
            whisper_release: dict[str, Any] = {"state": "not_applicable", "inference_active": False}
            conversation_release: dict[str, Any] = {"state": "not_applicable", "inference_active": False}
            admission_release: dict[str, Any] = {"state": "not_applicable", "inference_active": False}
            inference_active = False
            preprocessing_active = False
            preprocessor = getattr(APP, "preprocessor", None)
            if preprocessor is not None:
                try:
                    prep_status = preprocessor.status()
                    preprocessing_active = not isinstance(prep_status, dict) or prep_status.get("success") is not True or any(
                        isinstance(project, dict) and project.get("status") == "running"
                        for project in prep_status.get("projects", [])
                    )
                    inference_active = preprocessing_active
                except Exception:
                    preprocessing_active = True
                    inference_active = True
            if snapshot.mode == "gaming":
                drain_deadline = time.monotonic() + _GAMING_DRAIN_TIMEOUT_SECONDS
                whisper_release = _ACTIVE_TRANSCRIPTIONS.cancel_and_wait(max(0.0, drain_deadline - time.monotonic()))
                conversation_release = _ACTIVE_CONVERSATIONS.cancel_and_wait(max(0.0, drain_deadline - time.monotonic()))
                inference_active = inference_active or bool(whisper_release.get("inference_active")) or bool(conversation_release.get("inference_active"))
                drain_waiter = getattr(async_jobs, "wait_for_inference_actions", None)
                tracked_actions = {
                    "delegate", "reason", "review", "review_diff", "second_opinion", "compress",
                    "route", "batch", "embed", "rerank", "transcribe", "vision", "benchmark",
                    "complete_code", "scaffold", "speculative_draft", "generate_tests", "solve",
                    "eval_suite", "prompt_eval", "eval_drift",
                }
                if callable(drain_waiter):
                    try:
                        drained = bool(drain_waiter(
                            set(tracked_actions), max(0.0, drain_deadline - time.monotonic())
                        ))
                        admission_release = {
                            "state": "drained" if drained else "timed_out",
                            "inference_active": not drained,
                        }
                    except Exception as exc:
                        logger = getattr(APP, "logger", None)
                        if logger is not None:
                            logger.warning(
                                "gaming inference admission drain failed error_type=%s",
                                type(exc).__name__,
                            )
                        admission_release = {"state": "unavailable", "inference_active": True}
                else:
                    admission_release = {
                        "state": "unavailable", "inference_active": True,
                        "reason": "bounded_inference_drain_unavailable",
                    }
                active_checker = getattr(async_jobs, "inference_actions_active", None)
                if callable(active_checker):
                    try:
                        admission_active = bool(active_checker())
                        admission_release["inference_active"] = bool(
                            admission_release.get("inference_active") or admission_active
                        )
                        if admission_active:
                            admission_release["state"] = "active"
                    except Exception as exc:
                        logger = getattr(APP, "logger", None)
                        if logger is not None:
                            logger.warning(
                                "gaming inference admission status failed error_type=%s",
                                type(exc).__name__,
                            )
                        admission_release = {"state": "unavailable", "inference_active": True}
                else:
                    admission_release = {
                        "state": "unavailable", "inference_active": True,
                        "reason": "inference_admission_tracking_unavailable",
                    }
                inference_active = inference_active or bool(admission_release.get("inference_active"))
                if inference_active and release_token is not None:
                    manager_token = release_token
                    release_token = None
                    wait_for_drain = getattr(async_jobs, "when_inference_actions_drained", None)
                    if callable(wait_for_drain):
                        def release_after_drain() -> None:
                            wait_for_drain(
                                set(tracked_actions),
                                lambda: async_jobs.end_resource_release(manager_token),
                            )
                        _ACTIVE_TRANSCRIPTIONS.when_drained(
                            lambda: _ACTIVE_CONVERSATIONS.when_drained(release_after_drain)
                        )
                    else:
                        admission_release["release_ownership_retained"] = True
            response["whisper_process_release"] = whisper_release
            response["conversation_release"] = conversation_release
            response["inference_admission_release"] = admission_release
            if snapshot.mode == "gaming" and inference_active:
                runtime_unload = {"success": False, "state": "deferred", "reason": "inference_active", "inference_active": True}
                response["runtime_unload"] = runtime_unload
                response["accelerator_release"] = {"success": False, "state": "deferred", "verified": False}
            if snapshot.mode == "gaming" and not inference_active:
                stale_unload = {"success": False, "backend_available": False, "unloaded": [], "failed": {"mode": "stale mode transition"}}
                stale_accelerator = {"success": False, "verified": False, "released": [], "failed": {"mode": "stale mode transition"}}
                if not callable(guard_factory):
                    response["success"] = False
                    response["mode_transition_stale"] = True
                    response["runtime_unload"] = stale_unload
                    response["accelerator_release"] = stale_accelerator
                else:
                    release_current = False
                    with guard_factory():
                        release_snapshot = load_operational_mode(APP.config.get("server", {}).get("state_dir", "state"))
                        release_current = not (
                            release_snapshot.degraded
                            or release_snapshot.mode != snapshot.mode
                            or release_snapshot.revision != snapshot.revision
                        )
                    if not release_current:
                        response["success"] = False
                        response["mode_transition_stale"] = True
                        response["runtime_unload"] = stale_unload
                        response["accelerator_release"] = stale_accelerator
                        if release_token is not None:
                            async_jobs.end_resource_release(release_token)
                            release_token = None
                    else:
                        try:
                                runtime = getattr(APP, "runtime", None)
                                unload = getattr(runtime, "unload_configured_models", None)
                                if callable(unload):
                                    try:
                                        result = unload(timeout_seconds=3.0)
                                        runtime_unload = result if isinstance(result, dict) else {
                                            "success": False, "backend_available": False,
                                            "unloaded": [], "failed": {"backend": "invalid unload result"},
                                        }
                                    except Exception as exc:
                                        runtime_unload = {
                                            "success": False, "backend_available": False,
                                            "unloaded": [], "failed": {"backend": type(exc).__name__},
                                        }
                                else:
                                    runtime_unload = {
                                        "success": False, "backend_available": False,
                                        "unloaded": [], "failed": {"backend": "unload unavailable"},
                                    }
                                response["runtime_unload"] = runtime_unload
                                components = {
                                    "embeddings": getattr(APP, "embeddings", None),
                                    "reranker": getattr(APP, "reranker", None),
                                }
                                accelerator_release: dict[str, Any] = {
                                    "success": True, "verified": True, "released": [], "failed": {},
                                }
                                cuda_cleanup: dict[str, Any] = {
                                    "success": True, "state": "not_applicable", "verified": False,
                                }
                                cuda_cleanup_reported = False
                                release_deadline = time.monotonic() + 3.0
                                for name, component in components.items():
                                    if component is None:
                                        continue
                                    status_fn = getattr(component, "status", None)
                                    release_fn = getattr(component, "release", None)
                                    try:
                                        before = status_fn() if callable(status_fn) else None
                                        if not isinstance(before, dict):
                                            raise RuntimeError("component status unavailable")
                                        reported_cleanup = before.get("cache_cleanup")
                                        if (
                                            str(before.get("active_device", "")).lower().startswith("cuda")
                                            and isinstance(reported_cleanup, dict)
                                        ):
                                            cuda_cleanup = dict(reported_cleanup)
                                            cuda_cleanup_reported = True
                                        if not before.get("loaded") or str(before.get("active_backend", "")).lower() == "ollama":
                                            continue
                                        if not callable(release_fn):
                                            raise RuntimeError("accelerator release unavailable")
                                        timeout = max(0.0, release_deadline - time.monotonic())
                                        if timeout <= 0.0 or not release_fn(timeout_seconds=timeout):
                                            raise TimeoutError("accelerator release deadline reached")
                                        after = status_fn()
                                        if not isinstance(after, dict) or after.get("loaded"):
                                            raise RuntimeError("accelerator release was not verified")
                                        accelerator_release["released"].append(name)
                                    except Exception as exc:
                                        accelerator_release["success"] = False
                                        accelerator_release["verified"] = False
                                        accelerator_release["failed"][name] = type(exc).__name__
                                if not cuda_cleanup_reported:
                                    cuda_cleanup = api._empty_torch_cuda_cache(
                                        max(0.0, release_deadline - time.monotonic())
                                    )
                                accelerator_release["cuda_cleanup"] = cuda_cleanup
                                accelerator_release["state"] = (
                                    "complete" if accelerator_release["released"] else
                                    "failed" if accelerator_release["failed"] else "not_applicable"
                                )
                                response["accelerator_release"] = accelerator_release
                        finally:
                            if release_token is not None:
                                async_jobs.end_resource_release(release_token)
                                release_token = None
            if cancellation_error:
                response["job_cancellation"] = {"success": False, "error": cancellation_error}
            elif mode in {"gaming", "maintenance"} and not callable(mode_changed):
                response["job_cancellation"] = {
                    "success": False, "error": "operational mode cancellation hook is unavailable",
                }
            if snapshot.mode == "gaming":
                if (
                    admission_release.get("state") == "unavailable"
                    or whisper_release.get("state") == "timed_out"
                    or conversation_release.get("state") == "timed_out"
                ):
                    response["success"] = False
                runtime_unload = response.get("runtime_unload", runtime_unload or {})
                if runtime_unload.get("state") is None:
                    runtime_unload["state"] = "complete" if runtime_unload.get("success") else "failed"
                accelerator_release = response.get("accelerator_release", {
                    "success": True, "verified": False, "released": [], "failed": {},
                    "state": "not_applicable",
                })
                if accelerator_release.get("state") is None:
                    accelerator_release["state"] = (
                        "complete" if accelerator_release.get("released") else
                        "failed" if accelerator_release.get("failed") else "not_applicable"
                    )
                accelerator_release["verified"] = False
                response["resources"] = {
                    "in_process_cuda_release": accelerator_release,
                    "whisper_process_release": whisper_release,
                    "conversation_release": conversation_release,
                    "inference_admission_release": admission_release,
                    "ollama_unload": runtime_unload,
                }
                response["unload"] = runtime_unload
                response["transition"] = {"preprocessing_active": preprocessing_active}
                _store_mode_unload_status(APP, response["revision"], runtime_unload)
            self._send(200, response); return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if path == "/api/bundle/import":
            mode_rejection = _http_mode_gate_error("POST", path)
            if mode_rejection is not None:
                self._send(503, mode_rejection)
                return
            if content_type not in {"application/zip", "application/octet-stream"}:
                self._send(415, {"success": False, "error": "bundle import requires raw ZIP content"}); return
            try:
                limit = max(1024, int(APP.config.get("bundles", {}).get("max_bundle_bytes", 128 * 1024 * 1024)))
                raw_bundle = self._read_body(limit=limit)
                query = parse_qs(urlparse(self.path).query)
                target_root = (query.get("target_root") or [None])[0]
                if not self._claim_recovery(path, {
                    "bundle_sha256": hashlib.sha256(raw_bundle).hexdigest(),
                    "target_root": target_root,
                }):
                    return
                self._send(200, APP.import_bundle(raw_bundle, target_root)); return
            except RequestBodyError as exc:
                self._send(exc.status, {"success": False, "error": str(exc)}); return
            except Exception:
                self._send(500, {
                    "success": False,
                    "error": "bundle import failed; outcome may be partial",
                    "outcome_unknown": True,
                    "terminal": True,
                    "retryable": False,
                }); return
        try:
            payload = self._read_json()
            self._validate_payload(path, payload)
        except RequestBodyError as exc:
            self._send(exc.status, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        self._admin_payload = payload if isinstance(payload, dict) else {}
        mode_rejection = _http_mode_gate_error("POST", path, payload)
        if mode_rejection is not None:
            status = (
                503
                if path == "/api/context/pack"
                else 423 if mode_rejection.get("error_code") == "operational_mode_blocked" else 503
            )
            self._send(status, mode_rejection)
            return
        allowed_agent_state_post = {
            "/api/agent-state/memory",
            "/api/agent-state/tasks",
            "/api/agent-state/verification",
            "/api/agent-state/context",
            "/api/agent-state/events/delta",
            "/api/agent-state/blackboard",
            "/api/agent-state/incidents",
            "/api/agent-state/cleanup",
            "/api/agent-state/swarm/dispatch",
            "/api/agent-state/swarm/step",
            "/api/agent-state/swarm/cancel",
        }
        # Learning candidates are global operator state, not repository-scoped
        # task state. Keep the route behind normal authenticated POST access,
        # then reject direct/unbound dispatch before touching the store.
        if path == "/api/agent-state/learning" and getattr(self, "_authorization_actor", "unrecognized") == "unrecognized":
            self._send(403, {"success": False, "error": "learning route requires authenticated operator scope", "terminal": True, "retryable": False}); return
        if path == "/api/agent-state/cleanup" and getattr(self, "_authorization_actor", "unrecognized") == "unrecognized":
            self._send(403, {"success": False, "error": "cleanup route requires authenticated operator scope", "terminal": True, "retryable": False}); return
        if path.startswith("/api/agent-state/") and path not in allowed_agent_state_post and path != "/api/agent-state/learning":
            self._send(403, {"success": False, "error": "agent_state route has no root-scoped access contract", "terminal": True, "retryable": False}); return
        if path == "/api/agent-state/memory" and not self._bind_memory_payload(payload):
            return
        if path == "/api/agent-state/tasks" and not self._bind_task_payload(payload):
            return
        if path == "/api/agent-state/verification" and not self._bind_task_payload(payload):
            return
        if path == "/api/agent-state/incidents" and not self._bind_incident_payload(payload):
            return
        if path in {
            "/api/agent-state/swarm/dispatch",
            "/api/agent-state/swarm/step",
            "/api/agent-state/swarm/cancel",
        } and not self._bind_swarm_payload(payload):
            return
        if path in {
            "/api/code/ast_rename",
            "/api/ast_rename",
            "/api/code/batch_replace",
            "/api/repo/batch_replace",
        } and not self._bind_repository_root_payload(payload):
            return
        if path in {"/api/repo/cross_repo_contract", "/api/cross_repo_contract"} and not self._bind_multi_repository_payload(payload, cross_repo_contract=True):
            return
        if path in {"/api/cross_project_graph", "/api/cross_project_symbols", "/api/cross_project_impact"} and not self._bind_multi_repository_payload(payload):
            return
        root_scoped_repo_paths = {
            "/api/git/status", "/api/git/diff", "/api/git/history_search",
            "/api/repo/state", "/api/repo_state", "/api/repo/hotspots",
            "/api/hotspots", "/api/repo/generate_tests_for_diff",
            "/api/generate_tests_for_diff", "/api/repo/affected_tests",
            "/api/affected_tests", "/api/repo/topology", "/api/topology",
            "/api/git/synthesize_commit", "/api/test_matrix",
            "/api/security_audit", "/api/code-intelligence/query",
            "/api/code-intelligence/reset", "/api/repo/dead_code",
            "/api/dead_code", "/api/symbol_callgraph",
            "/api/repo/call_graph_diff", "/api/bundle/export",
            "/api/reachability_dead_code", "/api/mutation_test",
            "/api/type_stubs", "/api/split_changes", "/api/synthesize_rules",
            "/api/code_invariants", "/api/generate_dataset", "/api/callers",
            "/api/secret_scan", "/api/schema_inspect", "/api/explain_query",
            "/api/env_compat", "/api/worktree_lease", "/api/worktree_release",
            "/api/worktrees", "/api/worktree_prune", "/api/lint_fix",
        }
        if (
            path in root_scoped_repo_paths
            or (path.startswith("/api/repo/") and path not in {"/api/repo/cross_repo_contract"})
            or path.startswith("/api/code/")
        ) and not self._bind_repository_root_payload(payload):
            return
        if path == "/api/agent-state/verification":
            action = payload.get("action", "")
            if action in {"receipt", "completion"}:
                receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
                request_task_id = str(payload.get("task_id", "") or "").strip()
                receipt_task_id = str(receipt.get("task_id", "") or "").strip()
                if action == "receipt" and request_task_id and receipt_task_id and request_task_id != receipt_task_id:
                    self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False})
                    return
                scoped_task_id = receipt_task_id or request_task_id
                if scoped_task_id and not self._require_scoped_task(scoped_task_id):
                    return
        if path == "/api/agent-state/context" and not self._bind_context_payload(payload):
            return
        if path == "/api/agent-state/events/delta" and not self._bind_task_event_payload(payload):
            return
        if path == "/api/agent-state/blackboard" and not self._bind_task_board_payload(payload):
            return
        if path.startswith("/api/memory/") and not self._bind_workspace_memory_payload(path, payload):
            return
        if path == "/api/telemetry/tool-accounting":
            # Internal MCP reporter path: do not journal or recursively count this
            # metadata transport as an agent workload/tool call. Journal request IDs
            # so a lost response cannot duplicate an accepted batch.
            self._telemetry_finished = True
            if getattr(APP, "recovery", None) is not None and not self._claim_recovery(path, payload):
                return
            accepted = 0
            rejected = 0
            rejection_reasons: dict[str, int] = {}
            bound_tenant = str(getattr(self, "_authorization_tenant", "") or "").strip()
            if not bound_tenant:
                configured_tenant = self._configured_principal_tenant()
                if configured_tenant:
                    bound_tenant = configured_tenant
                else:
                    security = getattr(APP, "config", {}).get("security", {}) if APP is not None else {}
                    if isinstance(security, dict) and security.get("api_token"):
                        bound_tenant = self._principal_tenant()
            for event in payload.get("events", []):
                try:
                    scoped_event = dict(event) if isinstance(event, dict) else event
                    supplied_tenant = str(scoped_event.get("tenant", "") or "").strip() if isinstance(scoped_event, dict) else ""
                    if bound_tenant and supplied_tenant and supplied_tenant != bound_tenant:
                        rejected += 1
                        rejection_reasons["tenant_binding_mismatch"] = rejection_reasons.get("tenant_binding_mismatch", 0) + 1
                        continue
                    if isinstance(scoped_event, dict) and bound_tenant:
                        scoped_event["tenant"] = bound_tenant
                    recorded = APP.telemetry.record_tool_accounting(scoped_event)
                    if recorded is False:
                        rejected += 1
                        tool = event.get("tool") if isinstance(event, dict) else None
                        if isinstance(tool, str) and tool[:160] == "local_ai_telemetry":
                            reason = "self_accounting"
                        elif getattr(APP.telemetry, "enabled", True) is False:
                            reason = "telemetry_disabled"
                        else:
                            reason = "queue_full"
                        rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                        continue
                    accepted += 1
                except Exception as exc:
                    rejected += 1
                    reason = "invalid_event" if isinstance(exc, (TypeError, ValueError)) else "record_failed"
                    rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                    continue
            self._send(200, {
                "success": True,
                "accepted": accepted,
                "rejected": rejected,
                "rejection_reasons": rejection_reasons,
            }); return
        tenant = self._tenant()
        if not self._claim_recovery(path, payload):
            return
        self._request_evaluation = payload.get("evaluation")
        trace_store = getattr(APP, "debug_traces", None)
        api_trace_id = str(getattr(self, "_debug_trace_id", "") or "")
        if trace_store is not None and api_trace_id:
            try:
                trace_store.event(api_trace_id, "handler_started", {"action": path, "payload_keys": sorted(str(key) for key in payload)})
            except Exception:
                # Debug persistence is optional and must not strand a claimed request.
                pass
        try:
            post_handler_name = select_post_handler(post_route_ids)
            if post_handler_name is not None:
                post_handler = getattr(self, post_handler_name)
                if post_handler_name == "_handle_post_repository_analysis":
                    post_handler(payload, tenant=tenant, route_ids=post_route_ids)
                else:
                    post_handler(payload, tenant=tenant)
                return
            if 'post_config_update_1' in post_route_ids:
                action = str(payload.get("action", "update")).strip().lower()
                config_path = str(APP.config.get("_config_path", ""))
                if not config_path:
                    self._send(500, {"success": False, "error": "active config path unavailable"}); return
                if action == "reset":
                    target = save_runtime_overrides(config_path, {}, reset=True)
                    self._send(200, {
                        "success": True,
                        "restart_required": True,
                        "runtime_override_path": _safe_config_file_label(target),
                        "reset": True,
                    }); return
                requested = payload.get("settings", {})
                if not isinstance(requested, dict):
                    self._send(400, {"success": False, "error": "settings must be an object"}); return
                allowed = {
                    "hardware.profile": {"auto", "cpu", "integrated", "low", "balanced", "high", "max"},
                    "debug_traces.enabled": {True, False},
                    "preprocessing.enabled": {True, False},
                    "code_intelligence.enabled": {True, False},
                    "code_intelligence.serena_enabled": {True, False},
                                        "monitoring.dashboard_enabled": {True, False},
                    **{f"features.{feat_name}": {True, False} for feat_name in (
                        "status", "repo", "tasks", "rag", "commands", "coord",
                        "artifacts", "code_intelligence", "preprocessing",
                        "subagents", "agent_os", "dashboard", "work_orchestrator",
                    )},
                }
                patch: dict[str, Any] = {}
                for dotted, value in requested.items():
                    if dotted not in allowed or value not in allowed[dotted]:
                        self._send(400, {"success": False, "error": f"unsupported or invalid setting: {dotted}"}); return
                    cursor = patch
                    parts = dotted.split(".")
                    for part in parts[:-1]: cursor = cursor.setdefault(part, {})
                    cursor[parts[-1]] = value
                try:
                    prospective = deep_merge(APP.config, patch)
                    validate_config(prospective)
                    target = save_runtime_overrides(config_path, patch)
                except (ConfigError, OSError, ValueError) as exc:
                    logger = getattr(APP, "logger", None)
                    if logger is not None:
                        logger.error("config update rejected error_type=%s", type(exc).__name__)
                    self._send(400, {
                        "success": False,
                        "error": "configuration update rejected",
                        "error_code": "config_update_rejected",
                        "terminal": True,
                        "retryable": False,
                    }); return
                live_trace_toggle = _apply_live_debug_trace_toggle(APP, requested)
                self._send(200, {
                    "success": True,
                    "restart_required": not live_trace_toggle,
                    "applied_live": live_trace_toggle,
                    "runtime_override_path": _safe_config_file_label(target),
                    "settings": requested,
                }); return
            if 'post_browser_capability_1' in post_route_ids:
                if not APP.config.get("browser_bridge", {}).get("enabled", True):
                    self._send(501, capture_failure("unsupported")); return
                origin = str(payload.get("origin", ""))
                try:
                    capability = issue_capture_capability(
                        APP.config,
                        origin=origin,
                        tenant=tenant,
                        tab_id=payload.get("tab_id"),
                        window_id=payload.get("window_id"),
                        api_token_authorized=bool(APP.config.get("security", {}).get("api_token")) and self._authorized(),
                    )
                except Exception as exc:
                    code = getattr(exc, "error_code", "permission_denied")
                    status = int(getattr(exc, "status", 403))
                    self._send(status, {"success": False, "error": str(exc), "error_code": code, "terminal": True, "retryable": False}); return
                ttl = int(APP.config.get("browser_bridge", {}).get("capability_ttl_seconds", 60))
                self._send(200, {"success": True, "capability": capability, "one_use": True, "expires_in_seconds": ttl, "tab_id": payload.get("tab_id"), "window_id": payload.get("window_id")}); return
            if 'post_browser_capture_abandon_1' in post_route_ids:
                request = {
                    "origin": self.headers.get("Origin", payload.get("origin", "")),
                    "tenant": tenant,
                    "tab_id": payload.get("tab_id"),
                    "window_id": payload.get("window_id"),
                    "request_id": payload.get("request_id"),
                }
                capability = str(payload.get("capability", ""))
                if path == "/api/browser/capture/stage":
                    staged_payload = dict(payload)
                    staged_payload["origin"] = request["origin"]
                    result = stage_capture(capability, staged_payload, tenant=tenant, config=APP.config)
                elif path == "/api/browser/capture/commit":
                    result = commit_staged_capture(capability, request, artifacts=APP.artifacts, tenant=tenant, config=APP.config)
                else:
                    result = abandon_staged_capture(capability, request, tenant=tenant)
                self._send(int(result.get("status", 200 if result.get("success") else 400)), result); return
            if 'post_browser_capture_1' in post_route_ids:
                request = {
                    "origin": self.headers.get("Origin", payload.get("origin", "")),
                    "tenant": tenant,
                    "tab_id": payload.get("tab_id"),
                    "window_id": payload.get("window_id"),
                }
                checked = validate_capture_request(str(payload.get("capability", "")), request, tenant=tenant)
                if not checked.get("success"):
                    status = int(checked.get("status", 403))
                    self._send(status, checked); return
                if payload.get("capture_error"):
                    failure = capture_failure(str(payload["capture_error"]))
                    self._send(int(failure["status"]), failure); return
                self._send(200, capture_to_artifacts(payload, artifacts=APP.artifacts, tenant=tenant, config=APP.config)); return
            delivery = self._async_delivery(path, payload, tenant)
            if delivery is not None:
                self._send(*delivery); return
            if path == "/api/delegate":
                if bool(payload.get("conversation", False)):
                    result = _invoke_cancellable_request(_ACTIVE_CONVERSATIONS, APP.services.delegate, payload, tenant)
                    self._send(200, result); return
                self._send(200, APP.services.delegate(payload, tenant)); return
            if path == "/api/conversations/continue":
                result = _invoke_cancellable_request(_ACTIVE_CONVERSATIONS, APP.services.continue_conversation, payload, tenant)
                self._send(200, result); return
            if 'post_command_speculative_lint_1' in post_route_ids:
                action = str(payload.get("action", "submit")).strip().lower().replace("-", "_")
                if action == "submit":
                    self._send(200, APP.speculative_lint.submit(
                        tenant,
                        str(payload.get("root", ".")),
                        payload.get("paths") or [],
                        str(payload.get("command", "")),
                    )); return
                if action == "status":
                    self._send(200, APP.speculative_lint.status(tenant, str(payload.get("job_id", "")))); return
                if action == "cancel":
                    self._send(200, APP.speculative_lint.cancel(tenant, str(payload.get("job_id", "")))); return
            if 'post_agent_state_tasks_1' in post_route_ids:
                if not getattr(APP, "agent_tasks", None) or not APP.agent_tasks.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                action = payload.get("action", "")
                idempotency_key = str(payload.get("idempotency_key", "")).strip()
                actor = self._agent() or "agent"
                if action not in _AGENT_TASK_ACTIONS:
                    self._send(400, {
                        "success": False,
                        "error": f"unknown task action '{action}'",
                        "terminal": True,
                        "retryable": False,
                    }); return
                scoped_task_actions = {
                    "curate_dataset",
                    "ask", "answer",
                }
                repo_root = str(getattr(self, "_authorization_root", "") or "")
                tenant = self._tenant()
                if action in scoped_task_actions and (not repo_root or not tenant):
                    self._send(403, {"success": False, "error": "task root scope is required", "terminal": True, "retryable": False}); return
                if action == "curate_dataset":
                    task_id = str(payload.get("task_id", "")).strip() or None
                    output_path = str(payload.get("output_path", payload.get("path", "training_dataset.jsonl")))
                    min_receipts = int(payload.get("min_receipts", 1))
                    dataset_format = str(payload.get("format", "jsonl"))
                    try:
                        result = APP.agent_tasks.curate_training_dataset(
                            output_path,
                            min_receipts=min_receipts,
                            format=dataset_format,
                            repo_root=repo_root,
                            tenant=tenant,
                            task_id=task_id,
                        )
                        self._send(200, result); return
                    except Exception as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                request_root = str(payload.get("root", ""))
                request_tenant = str(payload.get("tenant") or self._tenant() or "")
                if action in {"ask", "answer"}:
                    try:
                        request_root, request_tenant = _agent_question_scope(
                            payload=payload,
                            authorized_root=repo_root,
                            authorized_tenant=tenant,
                        )
                    except ValueError as exc:
                        self._send(403, {
                            "success": False,
                            "error": str(exc),
                            "terminal": True,
                            "retryable": False,
                        }); return
                task_id = str(payload.get("task_id", "")).strip()
                if action not in {"create", "list", "reap_expired", "curate_dataset"} and task_id:
                    if self._request_task(task_id, request_root, request_tenant) is None:
                        return
                if action in {"ask", "answer"}:
                    try:
                        question_id = str(payload.get("question_id", "")).strip()
                        if action == "ask":
                            result = APP.agent_tasks.ask_question(
                                root=request_root,
                                tenant=request_tenant,
                                session_id=payload.get("session_id", ""),
                                question=payload.get("question", ""),
                                task_id=task_id,
                                actor=actor,
                                question_id=question_id,
                                response_budget_tokens=payload.get("response_budget_tokens"),
                            )
                        else:
                            result = APP.agent_tasks.answer_question(
                                question_id=question_id,
                                root=request_root,
                                tenant=request_tenant,
                                answer=payload.get("answer", ""),
                                actor=actor,
                                response_budget_tokens=payload.get("response_budget_tokens"),
                            )
                        if result is None:
                            self._send(404, {
                                "success": False,
                                "error": "question not found in this root, tenant and session",
                                "terminal": True,
                                "retryable": False,
                            }); return
                        self._send(200, {"success": True, "question": result}); return
                    except CheckpointResponseBudgetError as exc:
                        self._send(413, {
                            "success": False, "error": str(exc), "terminal": True, "retryable": False,
                            "mutation_applied": False, "operation_not_started": True,
                            "response_budget": {
                                "requested_tokens": exc.requested_tokens,
                                "required_tokens": exc.required_tokens,
                                "unit": "estimated_tokens",
                            },
                        }); return
                    except (TypeError, ValueError, RuntimeError) as exc:
                        self._send(400, {
                            "success": False,
                            "error": str(exc),
                            "terminal": True,
                            "retryable": False,
                        }); return
                if action == "create":
                    auto_worktree = payload.get("auto_worktree", False)
                    if not isinstance(auto_worktree, bool):
                        self._send(400, {
                            "success": False, "error": "auto_worktree must be a boolean",
                            "terminal": True, "retryable": False,
                        }); return
                    try:
                        contract = _task_create_contract(payload)
                    except (TypeError, ValueError) as exc:
                        self._send(400, {
                            "success": False, "error": str(exc),
                            "terminal": True, "retryable": False,
                        }); return
                    ctx_data = payload.get("context") or {}
                    context = ScopeContext(
                        repository_id=str(ctx_data.get("repository_id", "")),
                        clone_id=str(ctx_data.get("clone_id", "")),
                        worktree_id=str(ctx_data.get("worktree_id", "")),
                        branch=str(ctx_data.get("branch", "")),
                        task_id=str(ctx_data.get("task_id", "")),
                        session_id=str(ctx_data.get("session_id", "")),
                    )
                    try:
                        task = APP.agent_tasks.create(
                            contract,
                            context,
                            task_id=str(payload.get("task_id", "") or ""),
                            actor=actor,
                            idempotency_key=idempotency_key,
                            auto_worktree=auto_worktree,
                            repo_root=str(payload.get("repo_root", "")),
                            response_budget_tokens=payload.get("response_budget_tokens"),
                        )
                    except CheckpointResponseBudgetError as exc:
                        self._send(413, {
                            "success": False, "error": str(exc), "terminal": True, "retryable": False,
                            "mutation_applied": False, "operation_not_started": True,
                            "response_budget": {"requested_tokens": exc.requested_tokens,
                                                "required_tokens": exc.required_tokens,
                                                "unit": "estimated_tokens"},
                        }); return
                    except TaskWorktreeError as exc:
                        error_payload = {
                            "success": False, "error": str(exc), "terminal": True, "retryable": False,
                        }
                        if exc.mutation_applied is not None:
                            error_payload["mutation_applied"] = exc.mutation_applied
                        error_payload["operation_not_started"] = exc.operation_not_started
                        if exc.outcome_unknown:
                            error_payload["outcome_unknown"] = True
                        if exc.cleanup_succeeded is not None:
                            error_payload["cleanup_succeeded"] = exc.cleanup_succeeded
                        self._send(409 if exc.operation_not_started else 500, error_payload); return
                    except ValueError as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                    # A prediction is optional and must never fail task persistence.
                    try:
                        warm = getattr(APP.services, "schedule_task_context_warmup", None)
                        if callable(warm):
                            paths = payload.get("changed_paths")
                            if paths is not None and (not isinstance(paths, list) or any(not isinstance(p, str) for p in paths)):
                                paths = None
                            warm(task, root=repo_root, tenant=tenant, changed_paths=paths)
                    except Exception:
                        pass
                    self._send(200, {"success": True, "task": task.to_dict()}); return
                if action == "get":
                    task = APP.agent_tasks.get(str(payload.get("task_id", "")))
                    if not task:
                        self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False}); return
                    self._send(200, {"success": True, "task": task.to_dict()}); return
                if action == "transition":
                    target_status_str = str(payload.get("status", "")).strip().lower()
                    try:
                        target_status = TaskStatus(target_status_str)
                    except ValueError:
                        self._send(400, {"success": False, "error": f"invalid status {target_status_str}", "terminal": True, "retryable": False}); return
                    checkpoint_data = payload.get("checkpoint")
                    if checkpoint_data is not None and not isinstance(checkpoint_data, dict):
                        self._send(400, {"success": False, "error": "checkpoint must be an object", "terminal": True, "retryable": False}); return
                    checkpoint = TaskCheckpoint.from_dict(checkpoint_data) if checkpoint_data is not None else None
                    try:
                        task = APP.agent_tasks.transition(
                            str(payload.get("task_id", "")),
                            target_status,
                            reason=str(payload.get("reason", "")),
                            actor=actor,
                            idempotency_key=idempotency_key,
                            checkpoint=checkpoint,
                            response_budget_tokens=payload.get("response_budget_tokens"),
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except CheckpointResponseBudgetError as exc:
                        self._send(413, {
                            "success": False, "error": str(exc), "terminal": True, "retryable": False,
                            "mutation_applied": False, "operation_not_started": True,
                            "response_budget": {"requested_tokens": exc.requested_tokens,
                                                "required_tokens": exc.required_tokens,
                                                "unit": "estimated_tokens"},
                        }); return
                    except (KeyError, ValueError, CompletionGateError) as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "complete":
                    try:
                        task_id = str(payload.get("task_id", ""))
                        task_state = APP.agent_tasks.get(task_id)
                        if task_state is None:
                            raise KeyError(f"Task {task_id} not found")
                        task_owner = str(getattr(task_state, "owner", "") or "").strip()
                        if not task_owner or str(actor or "").strip() != task_owner:
                            self._send(403, {
                                "success": False,
                                "error": "task completion is restricted to its owner",
                                "error_code": "task_owner_mismatch",
                                "terminal": True,
                                "retryable": False,
                            }); return
                        task_context = getattr(task_state, "context", None)
                        root = str(
                            payload.get("root")
                            or getattr(task_context, "repository_id", "")
                            or ""
                        ).strip()
                        verification_store = getattr(APP, "agent_verification", None)
                        if verification_store is None:
                            raise CompletionGateError("completion verification store unavailable")
                        if not root:
                            self._send(400, {
                                "success": False,
                                "error": "project root is required for task completion verification",
                                "terminal": True,
                                "retryable": False,
                            }); return
                        current_revision, revision_stop = _completion_revision_or_stop(
                            root,
                            getattr(APP, "repo_tools", None),
                            getattr(APP, "repo_state", None),
                        )
                        if revision_stop:
                            self._send(409, revision_stop); return
                        from .verification_rules import complete_task_with_project_rules

                        task = complete_task_with_project_rules(
                            APP.agent_tasks,
                            verification_store,
                            task_id,
                            root=root,
                            state_dir=verification_store.state_store.db_path.parent,
                            current_revision=current_revision,
                            reason=str(payload.get("reason", "completed by agent")),
                            actor=actor,
                            idempotency_key=idempotency_key,
                            response_budget_tokens=payload.get("response_budget_tokens"),
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except CheckpointResponseBudgetError as exc:
                        self._send(413, {
                            "success": False, "error": str(exc), "terminal": True, "retryable": False,
                            "mutation_applied": False, "operation_not_started": True,
                            "response_budget": {"requested_tokens": exc.requested_tokens,
                                                "required_tokens": exc.required_tokens,
                                                "unit": "estimated_tokens"},
                        }); return
                    except (KeyError, ValueError, CompletionGateError) as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "fail":
                    try:
                        task = APP.agent_tasks.fail(
                            str(payload.get("task_id", "")),
                            reason=str(payload.get("reason", "failed by agent")),
                            actor=actor,
                            idempotency_key=idempotency_key,
                            response_budget_tokens=payload.get("response_budget_tokens"),
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except CheckpointResponseBudgetError as exc:
                        self._send(413, {
                            "success": False, "error": str(exc), "terminal": True, "retryable": False,
                            "mutation_applied": False, "operation_not_started": True,
                            "response_budget": {"requested_tokens": exc.requested_tokens,
                                                "required_tokens": exc.required_tokens,
                                                "unit": "estimated_tokens"},
                        }); return
                    except (KeyError, ValueError, CompletionGateError) as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "checkpoint":
                    chk_data = payload.get("checkpoint")
                    if not isinstance(chk_data, dict):
                        self._send(400, {
                            "success": False, "error": "checkpoint must be an object",
                            "terminal": True, "retryable": False,
                        }); return
                    checkpoint = TaskCheckpoint.from_dict(chk_data)
                    try:
                        task = APP.agent_tasks.checkpoint(
                            str(payload.get("task_id", "")),
                            checkpoint,
                            response_budget_tokens=payload.get("response_budget_tokens"),
                            actor=actor,
                            idempotency_key=idempotency_key,
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                    except CheckpointResponseBudgetError as exc:
                        self._send(413, {
                            "success": False,
                            "error": str(exc),
                            "terminal": True,
                            "retryable": False,
                            "mutation_applied": False,
                            "operation_not_started": True,
                            "response_budget": {
                                "requested_tokens": exc.requested_tokens,
                                "required_tokens": exc.required_tokens,
                                "unit": "estimated_tokens",
                            },
                        }); return
                    except ValueError as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                    except CompletionGateError as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "rollback":
                    try:
                        task = APP.agent_tasks.rollback(
                            str(payload.get("task_id", "")),
                            actor=actor,
                            idempotency_key=idempotency_key,
                            reason=str(payload.get("reason", "manual rollback")),
                            response_budget_tokens=payload.get("response_budget_tokens"),
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                    except CheckpointResponseBudgetError as exc:
                        self._send(413, {
                            "success": False, "error": str(exc), "terminal": True, "retryable": False,
                            "mutation_applied": False, "operation_not_started": True,
                            "response_budget": {"requested_tokens": exc.requested_tokens,
                                                "required_tokens": exc.required_tokens,
                                                "unit": "estimated_tokens"},
                        }); return
                    except Exception as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "resume":
                    try:
                        task = APP.agent_tasks.resume(
                            str(payload.get("task_id", "")),
                            actor=actor,
                            idempotency_key=idempotency_key,
                            response_budget_tokens=payload.get("response_budget_tokens"),
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                    except CheckpointResponseBudgetError as exc:
                        self._send(413, {
                            "success": False, "error": str(exc), "terminal": True, "retryable": False,
                            "mutation_applied": False, "operation_not_started": True,
                            "response_budget": {"requested_tokens": exc.requested_tokens,
                                                "required_tokens": exc.required_tokens,
                                                "unit": "estimated_tokens"},
                        }); return
                    except ValueError as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "heartbeat":
                    t_id = str(payload.get("task_id", "")).strip()
                    ttl_val = payload.get("ttl_seconds", payload.get("ttl"))
                    ttl_sec = float(ttl_val) if ttl_val is not None and float(ttl_val) > 0 else None
                    try:
                        task = APP.agent_tasks.heartbeat(
                            t_id,
                            ttl_seconds=ttl_sec,
                            actor=actor,
                            idempotency_key=idempotency_key,
                            response_budget_tokens=payload.get("response_budget_tokens"),
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                    except CheckpointResponseBudgetError as exc:
                        self._send(413, {
                            "success": False, "error": str(exc), "terminal": True, "retryable": False,
                            "mutation_applied": False, "operation_not_started": True,
                            "response_budget": {"requested_tokens": exc.requested_tokens,
                                                "required_tokens": exc.required_tokens,
                                                "unit": "estimated_tokens"},
                        }); return
                    except ValueError as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "cleanup_worktree":
                    t_id = str(payload.get("task_id", ""))
                    del_br = bool(payload.get("delete_branch", True))
                    try:
                        result = APP.agent_tasks.cleanup_worktree(
                            t_id,
                            delete_branch=del_br,
                            actor=self._agent(),
                            response_budget_tokens=payload.get("response_budget_tokens"),
                        )
                        self._send(200, result); return
                    except CheckpointResponseBudgetError as exc:
                        self._send(413, {
                            "success": False, "error": str(exc), "terminal": True, "retryable": False,
                            "mutation_applied": False, "operation_not_started": True,
                            "response_budget": {
                                "requested_tokens": exc.requested_tokens,
                                "required_tokens": exc.required_tokens,
                                "unit": "estimated_tokens",
                            },
                        }); return
                    except ValueError as exc:
                        self._send(400, {
                            "success": False, "error": str(exc), "terminal": True, "retryable": False,
                        }); return
                if action == "reap_expired":
                    requested_task_id = payload.get("task_id")
                    auto_recover = payload.get("auto_recover", False)
                    if (
                        not isinstance(requested_task_id, str)
                        or not requested_task_id
                        or requested_task_id != requested_task_id.strip()
                        or type(auto_recover) is not bool
                    ):
                        self._send(400, {"success": False, "error": "reap_expired requires a nonempty canonical task_id and boolean auto_recover", "terminal": True, "retryable": False}); return
                    if not repo_root or not tenant:
                        self._send(403, {"success": False, "error": "task root scope is required", "terminal": True, "retryable": False}); return
                    scoped_task = self._request_task(requested_task_id, repo_root, tenant)
                    if scoped_task is None:
                        return
                    if not self._task_matches_request(scoped_task, repo_root, tenant):
                        self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False}); return
                    try:
                        reaped = APP.agent_tasks.reap_expired_heartbeats(
                            auto_recover=auto_recover,
                            repo_root=repo_root,
                            tenant=tenant,
                            task_id=requested_task_id,
                            response_budget_tokens=payload.get("response_budget_tokens"),
                        )
                        self._send(200, {"success": True, "reaped": reaped}); return
                    except CheckpointResponseBudgetError as exc:
                        self._send(413, {
                            "success": False, "error": str(exc), "terminal": True, "retryable": False,
                            "mutation_applied": False, "operation_not_started": True,
                            "response_budget": {
                                "requested_tokens": exc.requested_tokens,
                                "required_tokens": exc.required_tokens,
                                "unit": "estimated_tokens",
                            },
                        }); return
                    except ValueError as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "list":
                    status_filter = None
                    if payload.get("status"):
                        try:
                            status_filter = TaskStatus(str(payload.get("status")).strip().lower())
                        except ValueError:
                            pass
                    limit = int(payload.get("limit", 100))
                    include_stale = bool(payload.get("include_stale", False))
                    task_query = payload.get("query")
                    if task_query is not None and not isinstance(task_query, str):
                        self._send(400, {
                            "success": False,
                            "error": "query must be a string",
                            "terminal": True,
                            "retryable": False,
                        }); return
                    tasks = APP.agent_tasks.list_tasks(
                        status=status_filter,
                        limit=limit,
                        include_stale=include_stale,
                        query=task_query,
                    )
                    response = {"success": True, "tasks": [t.to_dict() for t in tasks if self._task_matches_request(t, request_root, request_tenant)]}
                    if getattr(tasks, "query_truncated", False):
                        response["query_truncated"] = True
                    self._send(200, response); return
                self._send(400, {"success": False, "error": f"unknown task action '{action}'", "terminal": True, "retryable": False}); return
            if 'post_agent_state_memory_1' in post_route_ids:
                if not getattr(APP, "agent_memory", None) or not APP.agent_memory.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                action = payload.get("action", "")
                idempotency_key = str(payload.get("idempotency_key", "")).strip()
                actor = self._agent() or "agent"
                if action == "record":
                    rec_data = payload.get("record") or {}
                    if not rec_data:
                        rec_data = {
                            "kind": payload.get("kind", MemoryKind.FACT.value),
                            # Resolve the scope below from the supplied identity.
                            # Defaulting here to TASK made a repository-only
                            # write impossible to read back by root.
                            "scope": payload.get("scope"),
                            "key": str(payload.get("key") or payload.get("query") or ""),
                            "value": payload.get("value"),
                            "scope_id": str(payload.get("scope_id", "")),
                            "confidence": payload.get("confidence", 1.0),
                            "status": payload.get("status"),
                            "source": payload.get("source", actor),
                            "evidence_ids": payload.get("evidence_ids") or [],
                            "sensitivity": payload.get("sensitivity", "normal"),
                            "provenance": payload.get("provenance"),
                            "expires_at": payload.get("expires_at"),
                            "ttl_seconds": payload.get("ttl_seconds"),
                        }
                    try:
                        raw_kind = str(rec_data.get("kind", MemoryKind.FACT.value)).lower()
                        try:
                            kind_val = MemoryKind(raw_kind)
                        except ValueError:
                            kind_val = MemoryKind.FACT
                        raw_scope = str(rec_data.get("scope") or "").lower()
                        requested_scope = _parse_memory_scope(raw_scope)
                        provenance = dict(rec_data.get("provenance") or {})
                        requested_root = payload.get("root") or rec_data.get("root") or provenance.get("root")
                        project_identity = self._memory_project_identity(requested_root)
                        if requested_root and project_identity is None:
                            self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
                        root_val, repository_id_val = project_identity or (None, None)
                        if not root_val and not repository_id_val:
                            default_identity = self._memory_project_identity(".")
                            if default_identity and default_identity != ("", ""):
                                root_val, repository_id_val = default_identity
                        tenant_val = self._tenant()
                        scope_val, resolved_scope_id, ambiguous_scope = _resolve_memory_scope(
                            requested_scope,
                            scope_id=rec_data.get("scope_id") or payload.get("scope_id"),
                            root=root_val,
                            repository_id=repository_id_val,
                            tenant=tenant_val,
                            task_id=payload.get("task_id") or rec_data.get("task_id"),
                            session_id=payload.get("session_id") or rec_data.get("session_id"),
                            clone_id=payload.get("clone_id") or rec_data.get("clone_id"),
                            worktree_id=payload.get("worktree_id") or rec_data.get("worktree_id"),
                            branch=payload.get("branch") or rec_data.get("branch"),
                        )
                        if ambiguous_scope:
                            self._send(400, {"success": False, "error": "ambiguous memory scope identity", "terminal": True, "retryable": False}); return
                        if (
                            requested_scope is None
                            and (root_val or repository_id_val)
                            and kind_val in (
                                MemoryKind.FACT,
                                MemoryKind.DECISION,
                                MemoryKind.CONVENTION,
                                MemoryKind.PLAYBOOK,
                                MemoryKind.GOTCHA,
                            )
                        ):
                            scope_val = AgentScope.REPOSITORY
                            resolved_scope_id = str(root_val or repository_id_val)
                        else:
                            scope_val = scope_val or AgentScope.TASK
                        resolved_scope_id = self._bound_memory_scope_id(
                            scope_val,
                            resolved_scope_id,
                            payload.get("task_id") or rec_data.get("task_id"),
                        )
                        raw_status = rec_data.get("status")
                        status_val = None
                        if raw_status:
                            try:
                                status_val = MemoryStatus(str(raw_status).lower())
                            except ValueError:
                                status_val = None
                        record_expiry = rec_data.get("expires_at", payload.get("expires_at"))
                        record_ttl = rec_data.get("ttl_seconds", payload.get("ttl_seconds"))
                        if record_expiry is None and record_ttl is not None and float(record_ttl) > 0:
                            record_expiry = time.time() + float(record_ttl)
                        reserved_identity = {"root", "repository_id", "tenant"}
                        discarded_identity_fields = sorted(
                            identity_key
                            for identity_key in reserved_identity
                            if identity_key in payload
                            or identity_key in rec_data
                            or identity_key in provenance
                        )
                        for identity_key in reserved_identity:
                            provenance.pop(identity_key, None)
                        provenance.pop("discarded_identity_fields", None)
                        if root_val:
                            provenance["root"] = root_val
                        if repository_id_val:
                            provenance["repository_id"] = repository_id_val
                        provenance["tenant"] = tenant_val
                        if discarded_identity_fields:
                            provenance["discarded_identity_fields"] = discarded_identity_fields
                        for identity_key in (
                            "task_id", "session_id", "clone_id", "worktree_id", "branch",
                        ):
                            identity_value = payload.get(identity_key) or rec_data.get(identity_key)
                            if identity_value not in (None, ""):
                                provenance[identity_key] = str(identity_value)
                        if scope_val is AgentScope.REPOSITORY:
                            provenance = _bind_repository_memory_provenance(
                                provenance,
                                root=str(root_val or ""),
                                tenant=str(tenant_val or ""),
                                project_context=_trusted_project_context(str(root_val or "")),
                            )
                            project_context = _trusted_project_context(str(root_val or ""))
                            if project_context is not None and str(
                                getattr(project_context, "root", "") or ""
                            ).strip():
                                resolved_scope_id = str(project_context.root)
                        record = MemoryRecord.create(
                            kind=kind_val,
                            scope=scope_val,
                            key=str(rec_data.get("key", "")),
                            value=rec_data.get("value"),
                            scope_id=str(resolved_scope_id or rec_data.get("scope_id", "")),
                            confidence=float(rec_data.get("confidence", 1.0)),
                            status=status_val,
                            source=str(rec_data.get("source", actor)),
                            evidence_ids=tuple(rec_data.get("evidence_ids") or ()),
                            sensitivity=str(rec_data.get("sensitivity", "normal")),
                            provenance=provenance,
                            expires_at=(float(record_expiry) if record_expiry is not None else None),
                            contradicts_record_id=rec_data.get("contradicts_record_id", payload.get("contradicts_record_id")),
                            supersedes_record_id=rec_data.get("supersedes_record_id", payload.get("supersedes_record_id")),
                            quarantine_reason=rec_data.get("quarantine_reason", payload.get("quarantine_reason")),
                        )
                        saved = APP.agent_memory.record(record, actor=actor, idempotency_key=idempotency_key)
                        self._send(200, {"success": True, "record": saved.to_dict()}); return
                    except Exception as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "get":
                    scope_raw = payload.get("scope")
                    scope_val = _parse_memory_scope(scope_raw)
                    scope_id_val = payload.get("scope_id")
                    requested_root = payload.get("root")
                    project_identity = self._memory_project_identity(requested_root)
                    if requested_root and project_identity is None:
                        self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
                    root_val, repository_id_val = project_identity or (None, None)
                    explicit_tenant = self.headers.get("X-LocalAI-Tenant")
                    raw_tenant = payload.get("tenant") or (str(explicit_tenant).strip() if explicit_tenant else None)
                    tenant_val = str(raw_tenant).strip() if raw_tenant else None
                    task_id_val = payload.get("task_id")
                    session_id_val = payload.get("session_id")
                    clone_id_val = payload.get("clone_id")
                    worktree_id_val = payload.get("worktree_id")
                    branch_val = payload.get("branch")
                    # GLOBAL scope is intentionally independent of the
                    # authenticated transport tenant. Stored tenant
                    # provenance is still filtered by MemoryStore unless the
                    # caller explicitly opts into tenant-agnostic access.
                    if scope_val is AgentScope.GLOBAL:
                        tenant_val = None
                    scope_val, scope_id_val, ambiguous_scope = _resolve_memory_scope(
                        scope_val,
                        scope_id=scope_id_val,
                        root=root_val,
                        repository_id=repository_id_val,
                        tenant=tenant_val,
                        task_id=task_id_val,
                        session_id=session_id_val,
                        clone_id=clone_id_val,
                        worktree_id=worktree_id_val,
                        branch=branch_val,
                    )
                    if ambiguous_scope:
                        self._send(400, {"success": False, "error": "ambiguous memory scope identity", "terminal": True, "retryable": False}); return
                    if scope_val is None:
                        scope_val = AgentScope.GLOBAL
                    scope_id_val = self._bound_memory_scope_id(scope_val, scope_id_val, task_id_val)
                    if scope_val is AgentScope.TASK:
                        task_id_val = scope_id_val
                    elif scope_val is AgentScope.SESSION:
                        session_id_val = scope_id_val
                    rec = APP.agent_memory.get(
                        str(payload.get("record_id", "")),
                        scope=scope_val,
                        scope_id=str(scope_id_val) if scope_id_val is not None else None,
                        root=str(root_val) if root_val else None,
                        repository_id=str(repository_id_val) if repository_id_val else None,
                        tenant=str(tenant_val) if tenant_val else None,
                        task_id=str(task_id_val) if task_id_val else None,
                        session_id=str(session_id_val) if session_id_val else None,
                        clone_id=str(clone_id_val) if clone_id_val else None,
                        worktree_id=str(worktree_id_val) if worktree_id_val else None,
                        branch=str(branch_val) if branch_val else None,
                    )
                    if not rec:
                        self._send(404, {"success": False, "error": "memory record not found", "terminal": True, "retryable": False}); return
                    self._send(200, {"success": True, "record": rec.to_dict()}); return
                if action == "delete":
                    record_id_val = str(payload.get("record_id", "")).strip()
                    if not record_id_val:
                        self._send(400, {"success": False, "error": "memory delete requires record_id", "terminal": True, "retryable": False}); return
                    rec = self._get_bound_memory_record(payload, record_id_val)
                    if not rec:
                        if not payload.get("scope") and getattr(APP, "agent_memory", None) and getattr(APP.agent_memory, "state_store", None) and APP.agent_memory.state_store.db_path.exists():
                            try:
                                con = sqlite3.connect(APP.agent_memory.state_store.db_path)
                                try:
                                    row = con.execute("SELECT scope FROM agent_memory_records WHERE record_id = ?", (record_id_val,)).fetchone()
                                    if row:
                                        self._send(400, {"success": False, "error": "memory delete requires an explicit scope identity", "terminal": True, "retryable": False}); return
                                finally:
                                    con.close()
                            except Exception:
                                pass
                        self._send(404, {"success": False, "error": "memory record not found", "terminal": True, "retryable": False}); return
                    requested_root = payload.get("root")
                    project_identity = self._memory_project_identity(requested_root)
                    if requested_root and project_identity is None:
                        self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
                    root_val, repository_id_val = project_identity or (None, None)
                    requested_scope = _parse_memory_scope(payload.get("scope"))
                    explicit_tenant = self.headers.get("X-LocalAI-Tenant")
                    raw_tenant = (
                        self._tenant()
                        if requested_scope is AgentScope.GLOBAL
                        else payload.get("tenant") or (str(explicit_tenant).strip() if explicit_tenant else None) or self._tenant()
                    )
                    tenant_val = str(raw_tenant).strip() if raw_tenant else None
                    scope_val, scope_id_val, ambiguous_scope = _resolve_memory_scope(
                        requested_scope,
                        scope_id=payload.get("scope_id"),
                        root=root_val,
                        repository_id=repository_id_val,
                        tenant=tenant_val,
                        task_id=payload.get("task_id"),
                        session_id=payload.get("session_id"),
                        clone_id=payload.get("clone_id"),
                        worktree_id=payload.get("worktree_id"),
                        branch=payload.get("branch"),
                    )
                    if ambiguous_scope:
                        self._send(400, {"success": False, "error": "ambiguous memory scope identity", "terminal": True, "retryable": False}); return
                    if scope_val is None:
                        scope_val = AgentScope.GLOBAL
                    if scope_val is AgentScope.WORKTREE:
                        self._send(403, {"success": False, "error": "worktree-scoped memory delete requires verified worktree scope", "terminal": True, "retryable": False}); return
                    bound_scope_id = self._bound_memory_scope_id(
                        scope_val,
                        scope_id_val,
                        payload.get("task_id"),
                    )
                    bound_task_id = (
                        bound_scope_id
                        if scope_val is AgentScope.TASK
                        else payload.get("task_id")
                    )
                    deleted = APP.agent_memory.delete(
                        record_id_val,
                        scope=scope_val,
                        scope_id=str(bound_scope_id) if bound_scope_id is not None else None,
                        root=str(root_val or "") or None,
                        repository_id=str(repository_id_val or "") or None,
                        tenant=str(tenant_val or "") or None,
                        task_id=str(bound_task_id or "") or None,
                        session_id=str(payload.get("session_id") or "") or None,
                        clone_id=str(payload.get("clone_id") or "") or None,
                        worktree_id=str(payload.get("worktree_id") or "") or None,
                        branch=str(payload.get("branch") or "") or None,
                    )
                    self._send(200 if deleted else 404, {
                        "success": bool(deleted),
                        "deleted": bool(deleted),
                        "record_id": record_id_val,
                        **({} if deleted else {"error": "memory record not found", "terminal": True, "retryable": False}),
                    }); return
                if action == "find":
                    scope_raw = payload.get("scope")
                    scope_val = _parse_memory_scope(scope_raw)
                    key_val = str(payload["key"]) if payload.get("key") else None
                    query_val = str(payload["query"]) if payload.get("query") else None
                    status_val = MemoryStatus(str(payload["status"])) if payload.get("status") else None
                    limit_val = _memory_query_limit(payload.get("limit", 100))
                    scope_id_val = payload.get("scope_id")
                    requested_root = payload.get("root")
                    project_identity = self._memory_project_identity(requested_root)
                    if requested_root and project_identity is None:
                        self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
                    root_val, repository_id_val = project_identity or (None, None)
                    explicit_tenant = self.headers.get("X-LocalAI-Tenant")
                    raw_tenant = payload.get("tenant") or (str(explicit_tenant).strip() if explicit_tenant else None)
                    tenant_val = str(raw_tenant).strip() if raw_tenant else None
                    task_id_val = payload.get("task_id")
                    session_id_val = payload.get("session_id")
                    clone_id_val = payload.get("clone_id")
                    worktree_id_val = payload.get("worktree_id")
                    branch_val = payload.get("branch")
                    if not _memory_lookup_has_identity(
                        scope_id_val, root_val, repository_id_val, tenant_val, task_id_val,
                        session_id_val, clone_id_val, worktree_id_val, branch_val,
                    ):
                        self._send(400, {"success": False, "error": "memory lookup requires explicit root or identity", "terminal": True, "retryable": False}); return
                    scope_val, scope_id_val, ambiguous_scope = _resolve_memory_scope(
                        scope_val,
                        scope_id=scope_id_val,
                        root=root_val,
                        repository_id=repository_id_val,
                        tenant=tenant_val,
                        task_id=task_id_val,
                        session_id=session_id_val,
                        clone_id=clone_id_val,
                        worktree_id=worktree_id_val,
                        branch=branch_val,
                    )
                    if ambiguous_scope:
                        self._send(400, {"success": False, "error": "ambiguous memory scope identity", "terminal": True, "retryable": False}); return
                    scope_id_val = self._bound_memory_scope_id(scope_val, scope_id_val, task_id_val)
                    if scope_val is AgentScope.TASK:
                        task_id_val = scope_id_val
                    elif scope_val is AgentScope.SESSION:
                        session_id_val = scope_id_val
                    records = APP.agent_memory.find(
                        scope=scope_val if scope_raw is not None else None,
                        scope_id=str(scope_id_val) if scope_id_val is not None else None,
                        root=str(root_val) if root_val else None,
                        repository_id=str(repository_id_val) if repository_id_val else None,
                        tenant=str(tenant_val) if tenant_val else None,
                        task_id=str(task_id_val) if task_id_val else None,
                        session_id=str(session_id_val) if session_id_val else (str(scope_id_val) if (scope_raw is None and scope_val == AgentScope.SESSION) else None),
                        clone_id=str(clone_id_val) if clone_id_val else None,
                        worktree_id=str(worktree_id_val) if worktree_id_val else None,
                        branch=str(branch_val) if branch_val else None,
                        key=key_val,
                        query=query_val,
                        status=status_val,
                        limit=limit_val,
                    )
                    self._send(200, {"success": True, "records": [r.to_dict() for r in records]}); return
                def _memory_mutation_identity() -> tuple[dict[str, Any] | None, str | None]:
                    scope_val = _parse_memory_scope(payload.get("scope"))
                    scope_id_val = payload.get("scope_id")
                    requested_root = payload.get("root")
                    project_identity = self._memory_project_identity(requested_root)
                    if requested_root and project_identity is None:
                        return None, "memory project identity could not be resolved"
                    root_val, repository_id_val = project_identity or (None, None)
                    explicit_tenant = self.headers.get("X-LocalAI-Tenant")
                    raw_tenant = payload.get("tenant") or (str(explicit_tenant).strip() if explicit_tenant else None)
                    tenant_val = str(raw_tenant).strip() if raw_tenant else None
                    task_id_val = payload.get("task_id")
                    session_id_val = payload.get("session_id")
                    clone_id_val = payload.get("clone_id")
                    worktree_id_val = payload.get("worktree_id")
                    branch_val = payload.get("branch")
                    scope_val, scope_id_val, ambiguous_scope = _resolve_memory_scope(
                        scope_val,
                        scope_id=scope_id_val,
                        root=root_val,
                        repository_id=repository_id_val,
                        tenant=tenant_val,
                        task_id=task_id_val,
                        session_id=session_id_val,
                        clone_id=clone_id_val,
                        worktree_id=worktree_id_val,
                        branch=branch_val,
                    )
                    if ambiguous_scope:
                        return None, "ambiguous memory scope identity"
                    scope_id_val = self._bound_memory_scope_id(scope_val, scope_id_val, task_id_val)
                    if scope_val is AgentScope.TASK:
                        task_id_val = scope_id_val
                    elif scope_val is AgentScope.SESSION:
                        session_id_val = scope_id_val
                    if not _memory_lookup_has_identity(
                        scope_id_val,
                        root_val,
                        repository_id_val,
                        tenant_val,
                        task_id_val,
                        session_id_val,
                        clone_id_val,
                        worktree_id_val,
                        branch_val,
                    ) or scope_val is None:
                        return None, "memory mutation requires explicit scope identity"
                    return {
                        "scope": scope_val,
                        "scope_id": str(scope_id_val) if scope_id_val is not None else None,
                        "root": str(root_val) if root_val else None,
                        "repository_id": str(repository_id_val) if repository_id_val else None,
                        "tenant": str(tenant_val) if tenant_val else None,
                        "task_id": str(task_id_val) if task_id_val else None,
                        "session_id": str(session_id_val) if session_id_val else None,
                        "clone_id": str(clone_id_val) if clone_id_val else None,
                        "worktree_id": str(worktree_id_val) if worktree_id_val else None,
                        "branch": str(branch_val) if branch_val else None,
                    }, None

                if action == "promote":
                    identity, identity_error = _memory_mutation_identity()
                    if identity_error:
                        self._send(400, {"success": False, "error": identity_error, "terminal": True, "retryable": False}); return
                    target_scope_str = str(payload.get("target_scope", "")).strip().lower()
                    target_scope = AgentScope.parse(target_scope_str, default=None)
                    if not target_scope:
                        self._send(400, {"success": False, "error": f"invalid target scope '{target_scope_str}'", "terminal": True, "retryable": False}); return
                    record_id_val = str(payload.get("record_id", "")).strip()
                    if not record_id_val or not self._get_bound_memory_record(payload, record_id_val):
                        self._send(404, {"success": False, "error": "memory record not found", "terminal": True, "retryable": False}); return
                    if target_scope is AgentScope.GLOBAL:
                        self._send(403, {"success": False, "error": "global memory promotion is unavailable through this endpoint", "terminal": True, "retryable": False}); return
                    # Request payloads and agent headers are not user approval.
                    # Only server-authenticated actor classification may authorize
                    # a global promotion; current HTTP auth modes deliberately do
                    # not identify a human approver, so they fail closed.
                    approver = str(getattr(self, "_authorization_actor", "unrecognized"))
                    try:
                        root_input = str(payload.get("root") or "").strip()
                        project_context = _trusted_project_context(root_input)
                        root_value = getattr(project_context, "root", root_input)
                        repository_id_value = getattr(project_context, "coordination_id", None)
                        promotion_scope, promotion_scope_id, ambiguous_scope = _resolve_memory_scope(
                            _parse_memory_scope(payload.get("scope")),
                            scope_id=payload.get("scope_id"),
                            root=root_value,
                            repository_id=repository_id_value,
                            tenant=tenant,
                            task_id=payload.get("task_id"),
                            session_id=payload.get("session_id"),
                            clone_id=payload.get("clone_id"),
                            worktree_id=payload.get("worktree_id"),
                            branch=payload.get("branch"),
                        )
                        if ambiguous_scope or promotion_scope is None:
                            self._send(400, {"success": False, "error": "ambiguous memory scope identity", "terminal": True, "retryable": False}); return
                        promoted = APP.agent_memory.promote(
                            record_id_val,
                            target_scope,
                            approver=approver,
                            **(identity or {}),
                        )
                        self._send(200, {"success": True, "record": promoted.to_dict()}); return
                    except ApprovalRequiredError as exc:
                        self._send(403, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                    except ValueError as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "quarantine":
                    identity, identity_error = _memory_mutation_identity()
                    if identity_error:
                        self._send(400, {"success": False, "error": identity_error, "terminal": True, "retryable": False}); return
                    reason = str(payload.get("reason", "manual quarantine"))
                    record_id_val = str(payload.get("record_id", "")).strip()
                    if not record_id_val or not self._get_bound_memory_record(payload, record_id_val):
                        self._send(404, {"success": False, "error": "memory record not found", "terminal": True, "retryable": False}); return
                    try:
                        quarantined = APP.agent_memory.quarantine(
                            record_id_val,
                            reason=reason,
                            actor=actor,
                            **(identity or {}),
                        )
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                    self._send(200, {"success": True, "record": quarantined.to_dict()}); return
                if action == "compact":
                    self._send(403, {"success": False, "error": "memory compaction is unavailable through this endpoint", "terminal": True, "retryable": False}); return
                if action == "reap":
                    self._send(403, {"success": False, "error": "memory reaping is unavailable through this endpoint", "terminal": True, "retryable": False}); return
                if action in {"relation_record", "record_relation"}:
                    self._send(403, {"success": False, "error": "memory relations are unavailable through this endpoint", "terminal": True, "retryable": False}); return
                if action in {"relation_find", "find_relations"}:
                    self._send(403, {"success": False, "error": "memory relations are unavailable through this endpoint", "terminal": True, "retryable": False}); return
                if action in {"relation_traverse", "traverse_graph"}:
                    self._send(403, {"success": False, "error": "memory relations are unavailable through this endpoint", "terminal": True, "retryable": False}); return
                self._send(400, {"success": False, "error": f"unknown memory action '{action}'", "terminal": True, "retryable": False}); return

            if 'post_agent_state_incidents_1' in post_route_ids:
                if not getattr(APP, "agent_incidents", None) or not APP.agent_incidents.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                action = payload.get("action", "")
                if action not in {"decision", "record", "find"}:
                    self._send(403, {"success": False, "error": "incident action requires a scoped mutation contract", "terminal": True, "retryable": False}); return
                if action == "decision":
                    fp = IncidentFingerprint.from_dict(payload["fingerprint"])
                    rev = payload.get("state_revision", "")
                    decision = APP.agent_incidents.retry_decision(
                        fp,
                        rev,
                        root=str(payload.get("root", "")),
                        tenant=str(payload.get("tenant", "")),
                    )
                    self._send(200, {"success": True, "decision": decision.to_dict()}); return
                if action == "record":
                    root_cause = payload.get("root_cause", "")
                    verified_fix = payload.get("verified_fix", "")
                    msg = payload.get("message", "")
                    op = payload.get("operation_class", "agent")
                    rev = payload.get("state_revision", "")
                    evidence_ids = tuple(payload.get("evidence_ids", ()))
                    aff_paths = tuple(payload.get("affected_paths", ()))
                    outcome = ToolOutcome(
                        tool_name=op, error=msg or "recorded incident", exit_code=payload.get("exit_code", 1),
                        state_revision=rev, evidence_ids=evidence_ids,
                        metadata={"root_cause": root_cause, "verified_fix": verified_fix},
                        affected_paths=aff_paths,
                        repository_root=str(payload.get("root", "")),
                        tenant=str(payload.get("tenant", "")),
                    )
                    inc = APP.agent_incidents.capture(outcome)
                    if inc and (verified_fix or root_cause):
                        inc = APP.agent_incidents.resolve(inc.incident_id, verified_fix=verified_fix or "resolved", root_cause=root_cause or None)
                    self._send(200, {"success": True, "incident": inc.to_dict() if inc else None}); return
                if action == "find":
                    query = payload["query"]
                    limit_val = payload.get("limit", 100)
                    scoped = APP.agent_incidents.find_negative_knowledge(
                        query,
                        limit=limit_val,
                        root=payload["root"],
                        tenant=payload["tenant"],
                    )
                    self._send(200, {"success": True, "negative_knowledge": scoped, "incidents": scoped}); return
            if 'post_agent_state_verification_1' in post_route_ids:
                if not getattr(APP, "agent_verification", None) or not APP.agent_verification.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                action = payload.get("action", "")
                if action == "receipt":
                    rcpt_data = payload.get("receipt")
                    if not isinstance(rcpt_data, dict):
                        self._send(400, {"success": False, "error": "receipt must be an object", "terminal": True, "retryable": False}); return
                    receipt_task_id = str(rcpt_data.get("task_id", "") or "").strip()
                    request_task_id = str(payload.get("task_id", "") or "").strip()
                    if request_task_id and receipt_task_id and request_task_id != receipt_task_id:
                        self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False}); return
                    if not self._require_scoped_task(receipt_task_id or request_task_id):
                        return
                    if type(rcpt_data.get("passed")) is not bool:
                        self._send(400, {"success": False, "error": "receipt.passed must be boolean", "terminal": True, "retryable": False}); return
                    try:
                        if "receipt_id" in rcpt_data:
                            rcpt = VerificationReceipt.from_dict(rcpt_data)
                        else:
                            rcpt = VerificationReceipt.create(
                                task_id=str(rcpt_data.get("task_id", "")),
                                criterion=str(rcpt_data.get("criterion", "")),
                                passed=rcpt_data["passed"],
                                change_intent_id=str(rcpt_data.get("change_intent_id", "")),
                                evidence_id=str(rcpt_data.get("evidence_id", "")),
                                command_id=str(rcpt_data.get("command_id", "")),
                                repository_revision=str(rcpt_data.get("repository_revision", "")),
                                owner=self._agent() or "agent",
                                expires_at=rcpt_data.get("expires_at"),
                                details=rcpt_data.get("details"),
                            )
                        saved = APP.agent_verification.record(rcpt)
                        self._send(200, {"success": True, "receipt": saved.to_dict()}); return
                    except Exception as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "completion":
                    task_id = str(payload.get("task_id", "")).strip()
                    if not self._require_scoped_task(task_id):
                        return
                    current_revision = ""
                    root = str(payload.get("root", "")).strip()
                    requested_revision = payload.get("repository_revision", "")
                    has_requested_revision = bool(requested_revision)
                    repo_tools = getattr(APP, "repo_tools", None)
                    if root or requested_revision:
                        current_revision, revision_stop = _completion_revision_or_stop(
                            root, repo_tools, getattr(APP, "repo_state", None)
                        )
                        if revision_stop:
                            self._send(409, revision_stop); return
                    if has_requested_revision and requested_revision != current_revision:
                        self._send(409, {
                            "success": False,
                            "terminal": True,
                            "retryable": False,
                            "stop_code": "completion_repository_revision_mismatch",
                            "error": "requested repository revision does not match the current repository revision",
                        }); return
                    res = APP.agent_verification.completion(task_id, current_revision=current_revision)
                    if not current_revision and any(
                        str(getattr(receipt, "repository_revision", "") or "").strip()
                        for receipt in res.receipts
                    ):
                        _, revision_stop = _completion_revision_or_stop(
                            root, repo_tools, getattr(APP, "repo_state", None)
                        )
                        self._send(409, revision_stop or {
                            "success": False,
                            "terminal": True,
                            "retryable": False,
                            "stop_code": "completion_repository_revision_unavailable",
                            "error": "completion requires a repository snapshot with a non-empty revision",
                        }); return
                    self._send(200, {"success": True, "completion": res.to_dict()}); return
                if action == "export":
                    task_id = str(payload.get("task_id", "")).strip()
                    if not self._require_scoped_task(task_id):
                        return
                    format_val = str(payload.get("format", "markdown")).strip().lower()
                    res = APP.agent_verification.export_receipts(task_id, format=format_val)
                    self._send(200, res); return
                self._send(400, {"success": False, "error": f"unknown verification action '{action}'", "terminal": True, "retryable": False}); return
            if 'post_agent_state_context_1' in post_route_ids:
                if not getattr(APP, "agent_context", None) or not APP.agent_context.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                action = payload.get("action", "")
                if action == "compile":
                    requested_mode = self._context_retrieval_mode(payload)
                    if requested_mode is None:
                        self._send(400, {
                            "success": False,
                            "error": "context mode must be adaptive, full or fast",
                            "terminal": True,
                            "retryable": False,
                        }); return
                    req = build_context_request(
                        payload,
                        tenant=tenant,
                        project_context=_trusted_project_context(str(payload.get("root") or "")),
                    )
                    if not req.task_id:
                        self._send(400, {
                            "success": False,
                            "error": "task_id is required for context compilation",
                            "terminal": True,
                            "retryable": False,
                        }); return
                    compiled = APP.agent_context.compile(req)
                    since_hash = str(payload.get("since_hash") or "").strip()
                    compact_mode = bool(payload.get("compact", False))
                    root = req.root.strip()
                    if root:
                        from .agent_consistency import ConsistencyRequest

                        repository_query = str(payload.get("query", "")).strip()
                        if not repository_query:
                            repository_query = " ".join(req.focus[:8])
                        repository_mode = requested_mode

                        repository_request = ConsistencyRequest(
                            root=root,
                            task_id=req.task_id,
                            query=repository_query,
                            phase=req.phase,
                            focus=req.focus,
                            workspace=str(payload.get("workspace", "")),
                            preload_profile=req.preload_profile,
                            token_budget=req.token_budget,
                            changed_paths=req.changed_paths,
                            base=str(payload.get("base", "HEAD")),
                            staged=bool(payload.get("staged", False)),
                            tenant=tenant,
                            override_reason=str(payload.get("override_reason", "")),
                            approval=payload.get("approval", ""),
                        )
                        try:
                            repository = APP.services.adaptive_context_pack(
                                repository_request,
                                mode=repository_mode,
                                since_hash=str(payload.get("repo_since_hash", "")),
                            )
                        except Exception as exc:
                            repository = {
                                "success": False,
                                "terminal": False,
                                "retryable": True,
                                "error": f"repository context unavailable: {exc}",
                            }
                        task_context = compose_task_context(
                            task_id=req.task_id,
                            compiled=compiled,
                            repository=repository if isinstance(repository, dict) else {
                                "success": False,
                                "terminal": True,
                                "retryable": True,
                                "error": "repository context response must be an object",
                            },
                            token_budget=req.token_budget,
                            repository_required=True,
                        )
                        if since_hash and since_hash == task_context["etag"]:
                            self._send(200, {
                                "success": True,
                                "unchanged": True,
                                "etag": task_context["etag"],
                                "context_id": task_context["context_id"],
                                "estimated_tokens": 10,
                            }); return
                        response = {
                            "success": bool(task_context["success"]),
                            "complete": bool(task_context["complete"]),
                            "partial": bool(task_context["partial"]),
                            "context_id": task_context["context_id"],
                            "etag": task_context["etag"],
                            "context": compiled.to_dict(compact=compact_mode),
                            "task_context": task_context,
                            "text": task_context["text"],
                            "evidence_ids": task_context["evidence_ids"],
                            "repo_revision": task_context["repo_revision"],
                            "source_layers": task_context["source_layers"],
                            "stale": task_context["stale"],
                            "truncated": task_context["truncated"],
                            "omitted_sections": task_context["omitted_sections"],
                            "next_action": task_context["next_action"],
                            "estimated_tokens": task_context["estimated_tokens"],
                            "warnings": task_context["warnings"],
                        }
                        self._send(200, response); return
                    task_context = compose_task_context(
                        task_id=req.task_id,
                        compiled=compiled,
                        repository={},
                        token_budget=req.token_budget,
                        repository_required=False,
                    )
                    etag = task_context["etag"]
                    if since_hash and since_hash == etag:
                        self._send(200, {
                            "success": True,
                            "complete": True,
                            "unchanged": True,
                            "etag": etag,
                            "context_id": task_context["context_id"],
                            "estimated_tokens": 10,
                        }); return
                    self._send(200, {
                        "success": bool(task_context["success"]),
                        "complete": bool(task_context["complete"]),
                        "partial": bool(task_context["partial"]),
                        "context_id": task_context["context_id"],
                        "etag": etag,
                        "context": compiled.to_dict(compact=compact_mode),
                        "task_context": task_context,
                        "text": task_context["text"],
                        "evidence_ids": task_context["evidence_ids"],
                        "source_layers": task_context["source_layers"],
                        "stale": task_context["stale"],
                        "truncated": task_context["truncated"],
                        "omitted_sections": task_context["omitted_sections"],
                        "next_action": task_context["next_action"],
                        "estimated_tokens": task_context["estimated_tokens"],
                        "warnings": task_context["warnings"],
                    }); return
                self._send(400, {"success": False, "error": f"unknown context action '{action}'", "terminal": True, "retryable": False}); return
            if 'post_agent_state_learning_1' in post_route_ids:
                if not getattr(APP, "agent_learning", None) or not APP.agent_learning.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                action = payload.get("action", "")
                if action == "create_candidate":
                    cand_data = payload.get("candidate") or {}
                    try:
                        if "candidate_id" in cand_data:
                            cand = ImprovementCandidate.from_dict(cand_data)
                        else:
                            cand = ImprovementCandidate.create(
                                name=str(cand_data.get("name", "")),
                                baseline_version=str(cand_data.get("baseline_version", "baseline")),
                                candidate_version=str(cand_data.get("candidate_version", "candidate")),
                                slo_thresholds=cand_data.get("slo_thresholds"),
                                metrics=cand_data.get("metrics"),
                            )
                        saved = APP.agent_learning.create_candidate(cand)
                        self._send(200, {"success": True, "candidate": saved.to_dict()}); return
                    except Exception as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "promote":
                    candidate_id = str(payload.get("candidate_id", "")).strip()
                    approver = str(payload.get("approver", "")).strip()
                    try:
                        dec = APP.agent_learning.promote(candidate_id, approver=approver)
                        self._send(200, {"success": True, "decision": dec.to_dict()}); return
                    except ApprovalRequiredError as exc:
                        self._send(403, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "observe":
                    candidate_id = str(payload.get("candidate_id", "")).strip()
                    obs_data = payload.get("observation") or {}
                    obs = SLOObservation(
                        latency_ms=float(obs_data.get("latency_ms", 0.0)),
                        success=bool(obs_data.get("success", True)),
                        cost=float(obs_data.get("cost", 0.0)),
                        error_count=int(obs_data.get("error_count", 0)),
                    )
                    try:
                        trigger = APP.agent_learning.observe(candidate_id, obs)
                        self._send(200, {"success": True, "rollback_trigger": trigger.to_dict() if trigger else None}); return
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "list":
                    limit_val = int(payload.get("limit", 100))
                    candidates = APP.agent_learning.list_candidates(limit=limit_val)
                    self._send(200, {"success": True, "candidates": [c.to_dict() for c in candidates]}); return
                self._send(400, {"success": False, "error": f"unknown learning action '{action}'", "terminal": True, "retryable": False}); return
            if 'post_agent_state_cleanup_1' in post_route_ids:
                if not getattr(APP, "agent_state", None) or not APP.agent_state.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                retention = int(payload.get("retention_days") or APP.config.get("agent_state", {}).get("retention_days", 30))
                res = APP.agent_state.cleanup(retention_days=retention)
                self._send(200, res); return
            if 'post_agent_state_blackboard_1' in post_route_ids:
                if not getattr(APP, "agent_blackboard", None):
                    self._send(503, {"success": False, "error": "blackboard unavailable"}); return
                action = payload.get("action", "get")
                board_id = str(payload.get("board_id", payload.get("task_id", "default")))
                if action == "update":
                    section = str(payload.get("section", "main"))
                    content = payload.get("content")
                    author = str(payload.get("author", tenant or "agent"))
                    clock = payload.get("clock")
                    exp_v = payload.get("expected_version")
                    exp_v_int = int(exp_v) if exp_v is not None else None
                    res = APP.agent_blackboard.update(board_id, section, content, author, clock=clock, expected_version=exp_v_int)
                    self._send(200, res); return
                if action == "get":
                    section = payload.get("section")
                    res = APP.agent_blackboard.get(board_id, section=str(section) if section else None)
                    self._send(200, res); return
                if action == "list":
                    boards = APP.agent_blackboard.list_boards()
                    self._send(200, {"success": True, "boards": boards, "count": len(boards)}); return
                if action == "merge":
                    remote = payload.get("remote_sections", {})
                    res = APP.agent_blackboard.merge(board_id, remote)
                    self._send(200, res); return
                if action == "delete":
                    section = payload.get("section")
                    res = APP.agent_blackboard.delete(board_id, section=str(section) if section else None)
                    self._send(200, res); return
                self._send(400, {"success": False, "error": f"unknown blackboard action '{action}'"}); return
            if 'post_agent_state_swarm_dispatch_1' in post_route_ids:
                if not getattr(APP, "swarm", None):
                    self._send(503, {"success": False, "error": "swarm coordinator unavailable"}); return
                goal = str(payload.get("goal", payload.get("task", "")))
                target_paths = payload.get("target_paths", payload.get("paths", []))
                if not isinstance(target_paths, list):
                    target_paths = [str(target_paths)] if target_paths else []
                test_command = str(payload.get("test_command", payload.get("command", "")))
                author = str(payload.get("author", tenant or "agent"))
                root = str(payload.get("root", "."))
                res = APP.swarm.dispatch(goal=goal, target_paths=target_paths, test_command=test_command, author=author, root=root)
                self._send(200, res); return
            if 'post_agent_state_swarm_step_1' in post_route_ids:
                if not getattr(APP, "swarm", None):
                    self._send(503, {"success": False, "error": "swarm coordinator unavailable"}); return
                swarm_id = str(payload.get("swarm_id", payload.get("task_id", "")))
                role = str(payload.get("role", "Coder"))
                action = str(payload.get("action", "submit_patch"))
                step_payload = payload.get("payload", payload.get("content", {}))
                res = APP.swarm.step(
                    swarm_id=swarm_id, role=role, action=action, payload=step_payload,
                    root=str(payload.get("root", "")),
                )
                self._send(200, res); return
            if 'post_agent_state_swarm_cancel_1' in post_route_ids:
                if not getattr(APP, "swarm", None):
                    self._send(503, {"success": False, "error": "swarm coordinator unavailable"}); return
                swarm_id = str(payload.get("swarm_id", payload.get("task_id", "")))
                reason = str(payload.get("reason", ""))
                res = APP.swarm.cancel(
                    swarm_id=swarm_id, reason=reason,
                    root=str(payload.get("root", "")),
                )
                self._send(200, res); return
            if 'post_benchmark_run_1' in post_route_ids:
                if not getattr(APP, "benchmark_runner", None):
                    self._send(503, {"success": False, "error": "benchmark runner unavailable"}); return
                model = str(payload.get("model", ""))
                prompt = str(payload.get("prompt", payload.get("task", "")))
                num_tokens = int(payload.get("num_tokens", payload.get("max_tokens", 40)))
                res = APP.benchmark_runner.run(model=model, prompt=prompt or "def test(): pass\n", num_tokens=num_tokens)
                self._send(200, res); return
            if 'post_delegate_repo_1' in post_route_ids:
                self._send(200, APP.services.delegate_repo(payload, tenant)); return
            if 'post_solve_repo_1' in post_route_ids:
                self._send(200, APP.services.solve_repo(payload, tenant)); return
            if 'post_route_1' in post_route_ids:
                self._send(200, APP.services.route_context(payload, tenant)); return
            if 'post_delegate_batch_1' in post_route_ids:
                self._send(200, APP.services.batch_delegate(payload, tenant)); return
            if 'post_review_1' in post_route_ids:
                self._send(200, APP.services.review(payload, tenant)); return
            if 'post_review_diff_1' in post_route_ids:
                self._send(200, APP.services.review_diff(payload, tenant)); return
            if 'post_reason_1' in post_route_ids:
                self._send(200, APP.services.reason(payload, tenant)); return
            if 'post_second_opinion_1' in post_route_ids:
                self._send(200, APP.services.second_opinion(payload, tenant)); return
            if 'post_compress_1' in post_route_ids:
                self._send(200, APP.services.compress(payload, tenant)); return
            if 'post_generate_tests_1' in post_route_ids:
                self._send(200, APP.services.generate_tests(payload, tenant))
                return
            if 'post_patch_validate_1' in post_route_ids:
                self._send(200, APP.services.validate_patch(payload, tenant))
                return
            if 'post_query_expand_1' in post_route_ids:
                q = str(payload.get("query", ""))
                self._send(200, {"success": True, "query": q, "expanded_terms": APP.services.expand_query(q, tenant)})
                return
            if 'post_audit_dependencies_1' in post_route_ids:
                root = str(payload.get("root", "."))
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.audit_dependencies(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_refactor_impact_1' in post_route_ids:
                root = str(payload.get("root", "."))
                file_param = str(payload.get("file", payload.get("path", "")))
                symbol_param = payload.get("symbol")
                if APP.deterministic is not None:
                    self._send(200, APP.services.refactor_impact(root, file_param, symbol_param))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_resolve_imports_1' in post_route_ids:
                root = str(payload.get("root", "."))
                lang = str(payload.get("language", "auto"))
                syms = payload.get("symbols", [payload.get("symbol")] if payload.get("symbol") else [])
                if APP.deterministic is not None:
                    self._send(200, APP.services.resolve_imports(root, syms, lang))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_generate_tests_for_diff_1' in post_route_ids:
                root = str(payload.get("root", "."))
                diff = payload.get("diff")
                p = payload.get("path")
                if APP.deterministic is not None:
                    self._send(200, APP.services.generate_tests_for_diff(root, diff=diff, path=p))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_cross_repo_contract_1' in post_route_ids:
                b_root = str(payload.get("backend_root", payload.get("root", ".")))
                f_root = str(payload.get("frontend_root", payload.get("client_root", ".")))
                if APP.deterministic is not None:
                    self._send(200, APP.services.cross_repo_contract(b_root, f_root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_git_synthesize_commit_1' in post_route_ids:
                root = str(payload.get("root", "."))
                hint = str(payload.get("hint", payload.get("message", "")))
                task_id = str(payload.get("task_id", ""))
                if APP.deterministic is not None:
                    self._send(200, APP.services.synthesize_commit(root, hint, task_id=task_id))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_affected_tests_1' in post_route_ids:
                root = str(payload.get("root", "."))
                paths = payload.get("paths") or payload.get("changed_paths") or None
                if APP.deterministic is not None:
                    self._send(200, APP.services.affected_tests(root, changed_paths=paths))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_repo_topology_1' in post_route_ids:
                root = str(payload.get("root", "."))
                if APP.deterministic is not None:
                    self._send(200, APP.services.repo_topology(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_ast_rename_1' in post_route_ids:
                root = str(payload.get("root", "."))
                target_file = str(payload.get("file", payload.get("path", "")))
                old_sym = str(payload.get("old_symbol", payload.get("symbol", "")))
                new_sym = str(payload.get("new_symbol", payload.get("replacement", "")))
                apply_changes = bool(payload.get("apply", False))
                if APP.deterministic is not None:
                    self._send(200, APP.services.ast_rename(root, target_file, old_sym, new_sym, apply_changes=apply_changes))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_code_generate_mocks_1' in post_route_ids:
                root = str(payload.get("root", "."))
                target_file = str(payload.get("file", payload.get("path", "")))
                symbol = str(payload.get("symbol", ""))
                if APP.deterministic is not None:
                    self._send(200, APP.services.generate_mocks(root, target_file, symbol))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_security_audit_1' in post_route_ids:
                root = str(payload.get("root", "."))
                limit = int(payload.get("limit", 50))
                if APP.deterministic is not None:
                    self._send(200, APP.services.security_audit(root, limit))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_code_intelligence_query_1' in post_route_ids:
                root = str(payload.get("root", "."))
                self._send(200, APP.external_tools.query(
                    root, str(payload.get("query", "")),
                    backend=str(payload.get("backend", "auto")),
                    action=str(payload.get("action", "search")),
                    path=str(payload.get("path", "")),
                    limit=max(1, min(int(payload.get("limit", 20)), 50)),
                ))
                return
            if 'post_code_ast_outline_1' in post_route_ids:
                root = str(payload.get("root", "."))
                path_param = str(payload.get("path", payload.get("file", "")))
                if APP.deterministic is not None:
                    self._send(200, APP.services.ast_outline(root, path_param))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_code_batch_replace_1' in post_route_ids:
                root = str(payload.get("root", "."))
                edits = payload.get("edits") or payload.get("replacements") or []
                dry_run = bool(payload.get("dry_run", False))
                self._send(200, APP.services.batch_replace(root, edits if isinstance(edits, list) else [], dry_run=dry_run))
                return
            if 'post_maintenance_optimize_db_1' in post_route_ids:
                self._send(200, APP.services.optimize_databases())
                return
            if 'post_maintenance_purge_cache_1' in post_route_ids:
                days = int(payload.get("days", 7))
                self._send(200, APP.services.purge_stale_cache(days))
                return
            if 'post_maintenance_resolve_errors_1' in post_route_ids:
                result = APP.services.resolve_all_errors()
                status = 200 if result.get("success") is True else 503 if result.get("retryable") else 500
                self._send(status, result)
                return
            if 'post_doctor_1' in post_route_ids:
                self._send(200, APP.services.run_doctor())
                return
            if 'post_code_symbol_1' in post_route_ids:
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol", ""))
                self._send(200, APP.services.code_inspect_symbol(root, sym))
                return
            if 'post_code_find_symbol_1' in post_route_ids:
                root = str(payload.get("root", "."))
                pat = str(payload.get("pattern") or payload.get("name_path_pattern") or "")
                depth = int(payload.get("depth", 0))
                include_body = _parse_include_body(payload.get("include_body", False))
                if include_body is None:
                    self._send(400, {"success": False, "error": "include_body must be a boolean"})
                    return
                include_info = bool(payload.get("include_info", True))
                rel_path = payload.get("path") or payload.get("relative_path")
                limit = int(payload.get("limit", 30))
                self._send(200, APP.services.code_find_symbol(root, pat, depth=depth, include_body=include_body, include_info=include_info, relative_path=str(rel_path) if rel_path else None, limit=limit))
                return
            if 'post_code_find_declaration_1' in post_route_ids:
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol") or payload.get("name") or "")
                rel_path = payload.get("path")
                self._send(200, APP.services.code_find_declaration(root, sym, path=str(rel_path) if rel_path else None))
                return
            if 'post_code_find_implementations_1' in post_route_ids:
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol") or payload.get("name") or "")
                rel_path = payload.get("path")
                self._send(200, APP.services.code_find_implementations(root, sym, path=str(rel_path) if rel_path else None))
                return
            if 'post_code_find_referencing_symbols_1' in post_route_ids:
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol") or payload.get("name") or "")
                rel_path = payload.get("path")
                self._send(200, APP.services.code_find_referencing_symbols(root, sym, path=str(rel_path) if rel_path else None))
                return
            if 'post_code_symbols_overview_1' in post_route_ids:
                root = str(payload.get("root", "."))
                fpath = str(payload.get("path", ""))
                depth = int(payload.get("depth", 1))
                self._send(200, APP.services.code_symbols_overview(root, fpath, depth=depth))
                return
            if 'post_code_diagnostics_1' in post_route_ids:
                root = str(payload.get("root", "."))
                fpath = str(payload.get("path", ""))
                self._send(200, APP.services.code_diagnostics(root, fpath))
                return
            if 'post_code_intelligence_control_1' in post_route_ids:
                action = str(payload.get("action", "status")).strip().lower().replace("-", "_")
                if action == "status":
                    self._send(200, {"success": True, **APP.external_tools.status()}); return
                if action in {"rediscover", "refresh"}:
                    self._send(200, APP.external_tools.rediscover()); return
                if action in {"reset", "reset_sessions"}:
                    self._send(200, APP.external_tools.reset_sessions(str(payload.get("backend", "all")), str(payload.get("root")) if payload.get("root") else None)); return
                self._send(400, {"success": False, "error": f"unknown code-intelligence action: {action}"}); return
            if 'post_complete_1' in post_route_ids:
                # FIM completion routed through APP.services with caching / APP.scheduler.submit
                self._send(200, APP.services.complete_code(payload, tenant)); return
            if 'post_preprocess_1' in post_route_ids:
                self._send(200, APP.services.preprocess(payload)); return
            if 'post_dead_code_1' in post_route_ids:
                root = str(payload.get("root", "."))
                limit = int(payload.get("limit", 50))
                self._send(200, APP.services.dead_code(root, limit))
                return
            if 'post_symbol_callgraph_1' in post_route_ids:
                root = str(payload.get("root", "."))
                sym = payload.get("symbol")
                limit = int(payload.get("limit", 50))
                self._send(200, APP.services.symbol_callgraph(root, str(sym) if sym else None, limit))
                return
            if 'post_cross_project_graph_1' in post_route_ids:
                roots = payload.get("roots")
                if not isinstance(roots, list) or not roots:
                    roots = [str(p.get("root")) for p in APP.preprocessor.status().get("projects", []) if p.get("root")]
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.cross_project_graph([str(r) for r in roots]))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_cross_project_symbols_1' in post_route_ids:
                roots = payload.get("roots")
                if not isinstance(roots, list) or not roots:
                    roots = [str(p.get("root")) for p in APP.preprocessor.status().get("projects", []) if p.get("root")]
                query = str(payload.get("query", ""))
                limit = int(payload.get("limit", 50))
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.cross_repo_symbol_find([str(r) for r in roots], query, limit))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_cross_project_impact_1' in post_route_ids:
                roots = payload.get("roots")
                if not isinstance(roots, list) or not roots:
                    roots = [str(p.get("root")) for p in APP.preprocessor.status().get("projects", []) if p.get("root")]
                symbol = str(payload.get("symbol", payload.get("query", "")))
                origin_root = payload.get("origin_root")
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.cross_project_impact(symbol, [str(r) for r in roots], str(origin_root) if origin_root else None))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_repo_call_graph_diff_1' in post_route_ids:
                root = str(payload.get("root", "."))
                diff = payload.get("diff")
                if APP.deterministic is not None:
                    if "old_code" in payload or "new_code" in payload:
                        result = APP.deterministic.ast_diff(payload.get("old_code"), payload.get("new_code"))
                        if result.get("success"):
                            try:
                                artifact_id = APP.artifacts.put_json(result, tenant, "ast-structural-diff")
                                if not isinstance(artifact_id, str) or not artifact_id:
                                    raise ValueError("artifact ID unavailable")
                            except Exception:
                                self._send(503, {"success": False, "terminal": False, "retryable": True,
                                                 "error_code": "ast_diff_artifact_unavailable",
                                                 "error": "structural diff artifact could not be stored"}); return
                            changes = result["changes"]
                            preview: list[dict[str, Any]] = []
                            preview_chars = 0
                            for change in changes[:32]:
                                size = len(json.dumps(change, ensure_ascii=False, separators=(",", ":")))
                                if preview_chars + size > 8000:
                                    break
                                preview.append(change)
                                preview_chars += size
                            result = {**result, "artifact_id": artifact_id, "changes_total": len(changes),
                                      "changes_returned": len(preview), "changes": preview,
                                      "truncated": len(changes) > len(preview)}
                            if len(changes) > len(preview) or len(json.dumps(result["tree"], ensure_ascii=False, separators=(",", ":"))) + preview_chars > 8000:
                                result.pop("tree", None)
                                result["tree_in_artifact"] = True
                                result["truncated"] = True
                        self._send(200, result)
                    else:
                        self._send(200, APP.deterministic.call_graph_diff(root, diff=diff))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if 'post_bundle_export_1' in post_route_ids:
                root = str(payload.get("root", "."))
                try:
                    data = APP.export_bundle(root, tenant=self._tenant())
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self._common_headers()
                    self.send_header("Content-Disposition", 'attachment; filename="local-ai-hub-project.bundle.zip"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as exc:
                    if not _is_client_disconnect(exc):
                        self._send(500, {
                            "success": False,
                            "error": "bundle export unavailable",
                            "error_code": "bundle_export_unavailable",
                            "terminal": True,
                            "retryable": False,
                        })
                return
            if 'post_benchmark_1' in post_route_ids:
                self._send(200, APP.services.benchmark(tenant)); return
            if 'post_evaluation_1' in post_route_ids:
                self._send(200, APP.services.evaluation(payload)); return
            if 'post_repo_profile_1' in post_route_ids:
                self._send(200, APP.services.repo_profile(str(payload.get("root", ".")))); return
            if 'post_repo_map_1' in post_route_ids:
                self._send(200, APP.services.repo_map(str(payload.get("root", ".")), int(payload.get("max_symbols", 120)))); return
            if 'post_repo_code_index_1' in post_route_ids:
                result = APP.services.code_query(
                    str(payload.get("root", ".")), str(payload.get("query", "")),
                    payload.get("limit", 24), bool(payload.get("include_code", False)),
                    payload.get("offset", 0),
                )
                status = int(result.pop("status_code", 200))
                self._send(status, result); return
            if 'post_repo_investigate_1' in post_route_ids:
                self._send(200, APP.services.repo_investigate(
                    str(payload.get("root", ".")),
                    str(payload.get("query", "")),
                    str(payload.get("path", "")),
                    bool(payload.get("include_code", True)),
                    int(payload.get("limit", 10)),
                )); return
            if 'post_repo_diagnose_1' in post_route_ids:
                self._send(200, APP.services.repo_diagnose(
                    str(payload.get("root", ".")),
                    str(payload.get("text", payload.get("query", ""))),
                )); return
            if 'post_repo_briefing_1' in post_route_ids:
                self._send(200, APP.services.repo_briefing(str(payload.get("root", ".")))); return
            if 'post_command_preflight_1' in post_route_ids:
                raw_paths = payload.get("paths") or payload.get("files")
                paths_list = [str(p) for p in raw_paths] if isinstance(raw_paths, list) else ([str(raw_paths)] if raw_paths else None)
                self._send(200, APP.services.commands.preflight(
                    str(payload.get("cwd", payload.get("root", "."))),
                    str(payload.get("tenant", "default")),
                    paths=paths_list,
                    timeout=int(payload.get("timeout", 10) or 10),
                )); return
            if 'post_repo_deterministic_1' in post_route_ids:
                self._send(200, APP.services.deterministic_query(str(payload.get("root", ".")), str(payload.get("query", "")), int(payload.get("limit", 24)))); return
            if 'post_repo_impact_1' in post_route_ids:
                self._send(200, APP.services.repo_impact(
                    str(payload.get("root", ".")), str(payload.get("base", "HEAD")), bool(payload.get("staged", False)),
                    int(payload.get("max_symbols", APP.config.get("workflow", {}).get("impact_max_symbols", 48))),
                    int(payload.get("max_dependents", APP.config.get("workflow", {}).get("impact_max_dependents", 30))),
                )); return
            if 'post_search_1' in post_route_ids:
                result = APP.services.repo_search(
                    str(payload.get("root", ".")),
                    str(payload.get("query", "")),
                    int(payload.get("top_k", 12)),
                    context_lines=int(payload["context_lines"]) if payload.get("context_lines") is not None else None,
                    enrich=bool(payload.get("enrich", False)),
                    limit=payload.get("limit", 24),
                    offset=payload.get("offset", 0),
                    path_hints=payload.get("path_hints"),
                )
                status = int(result.pop("status_code", 200))
                self._send(status, result); return
            if path == "/api/context/pack":
                explicit_tenant = self.headers.get("X-LocalAI-Tenant")
                raw_tenant = payload.get("tenant") or (str(explicit_tenant).strip() if explicit_tenant else None)
                principal_tenant = self._configured_principal_tenant()
                if principal_tenant and raw_tenant and str(raw_tenant).strip() != principal_tenant:
                    self._send(403, {"success": False, "error": "tenant does not match authenticated principal", "error_code": "tenant_binding_mismatch", "terminal": True, "retryable": False}); return
                tenant = principal_tenant or (str(raw_tenant).strip() if raw_tenant else None) or self._tenant()
                root = str(payload.get("root", ".")); query_text = str(payload.get("query", ""))
                configured_tokens = APP.config.get("token_saving", {}).get("default_repo_context_tokens", 8000)
                raw_max_tokens = payload.get("max_tokens", payload.get("token_budget", configured_tokens))
                raw_token_budget = payload.get("token_budget")
                if isinstance(raw_max_tokens, bool) or not isinstance(raw_max_tokens, int):
                    self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "max_tokens must be an integer"}); return
                if raw_token_budget is not None:
                    if isinstance(raw_token_budget, bool) or not isinstance(raw_token_budget, int):
                        self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "token_budget must be an integer"}); return
                    if raw_max_tokens and raw_token_budget and raw_max_tokens != raw_token_budget:
                        self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "token_budget and max_tokens must match when both are provided"}); return
                    raw_max_tokens = raw_token_budget or raw_max_tokens
                if raw_max_tokens < 0:
                    self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "max_tokens must be non-negative"}); return
                if raw_max_tokens and not 128 <= raw_max_tokens <= 20_000:
                    self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "max_tokens must be 0 or between 128 and 20000"}); return
                max_tokens = raw_max_tokens or max(128, min(int(configured_tokens or 8000), 20_000))
                mode = self._context_retrieval_mode(payload)
                if mode is None:
                    self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "context mode must be adaptive, full or fast"}); return
                if "project_config_digest" in payload:
                    self._send(400, {
                        "success": False, "terminal": True, "retryable": False,
                        "error": "project_config_digest is server-resolved",
                    }); return
                path_control_fields = ("path_hints", "directory_hints", "exclude_paths", "force_include_paths")
                path_controls_requested = any(field in payload for field in path_control_fields)
                path_controls = None
                project_config_digest = ""
                project_retrieval_weights = None
                project_memory_revision = ""
                if path_controls_requested:
                    for field in path_control_fields:
                        if payload.get(field) is not None and not isinstance(payload.get(field), list):
                            self._send(400, {
                                "success": False, "terminal": True, "retryable": False,
                                "error": f"{field} must be a list",
                            }); return
                    from .project_config import resolve_project_context
                    from .state_paths import configured_state_dir
                    project_context = resolve_project_context(
                        root, configured_state_dir(APP.config, create=False)
                    )
                    project_config_digest = project_context.config_digest
                    from .agent_consistency import ConsistencyRequest
                    try:
                        path_controls = ConsistencyRequest(
                            root=root,
                            path_hints=payload.get("path_hints") or (),
                            directory_hints=payload.get("directory_hints") or (),
                            exclude_paths=payload.get("exclude_paths") or (),
                            force_include_paths=payload.get("force_include_paths") or (),
                            project_config_digest=project_config_digest,
                        )
                    except (TypeError, ValueError) as exc:
                        self._send(400, {
                            "success": False, "terminal": True, "retryable": False,
                            "error": str(exc),
                        }); return
                    project_retrieval_weights = dict(project_context.settings.retrieval_weights)
                    from .task_context import _project_context_hint_groups
                    try:
                        project_root = Path(root).expanduser().resolve(strict=False)
                        pinned_hints, entry_hints, saved_hints = _project_context_hint_groups(
                            project_context,
                            project_root=project_root,
                            repository_revision=(
                                payload.get("repository_revision")
                                if isinstance(payload.get("repository_revision"), str)
                                else ""
                            ),
                            config_digest=project_config_digest,
                        )
                        path_controls = ConsistencyRequest(
                            root=root,
                            path_hints=(
                                *pinned_hints,
                                *entry_hints,
                                *path_controls.path_hints,
                                *saved_hints,
                            ),
                            directory_hints=path_controls.directory_hints,
                            exclude_paths=path_controls.exclude_paths,
                            force_include_paths=path_controls.force_include_paths,
                            project_config_digest=project_config_digest,
                        )
                    except (OSError, RuntimeError, TypeError, ValueError) as exc:
                        self._send(400, {
                            "success": False, "terminal": True, "retryable": False,
                            "error": str(exc),
                        }); return
                    try:
                        project_memory_revision = APP.services._adaptive_memory_revision(ConsistencyRequest(
                            root=root,
                            query=query_text,
                            tenant=tenant,
                            workspace=str(payload.get("workspace") or ""),
                            token_budget=max_tokens,
                        ))
                    except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
                        self._send(200, {
                            "success": False,
                            "terminal": True,
                            "retryable": False,
                            "stop_code": "context_memory_revision_unavailable",
                            "error": f"context memory revision unavailable: {type(exc).__name__}",
                            "context": "",
                            "evidence": [],
                            "query": query_text,
                            "delivery_mode": mode,
                        }); return
                auto_injected_task = False
                if not str(payload.get("task_id", "")).strip() and getattr(APP, "agent_tasks", None):
                    try:
                        active_task = APP.agent_tasks.get_active_task(repo_root=root, tenant=tenant)
                        if active_task is not None:
                            payload["task_id"] = active_task.task_id
                            auto_injected_task = True
                    except Exception:
                        pass
                guarded = payload.get("guarded", False)
                if not isinstance(guarded, bool):
                    self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "guarded must be boolean"}); return
                guarded_requested = (
                    bool(guarded)
                    or bool(str(payload.get("task_id", "")).strip())
                    or bool(str(payload.get("phase", "")).strip())
                    or bool(str(payload.get("session_id", "")).strip())
                )
                if not guarded_requested:
                    guard_fields = (
                        "focus", "preload_profile", "changed_paths", "base", "staged", "since_hash",
                        "approval", "override_reason", "token_budget", "session_id", "clone_id",
                        "worktree_id", "branch", "repository_id", "repository_revision", "include_diagnostics",
                    )
                    unexpected = next((field for field in guard_fields if field in payload), None)
                    if unexpected is not None:
                        self._send(400, {"success": False, "terminal": True, "retryable": False, "error": f"guard-related fields require guarded=true, task_id, or phase: {unexpected}"}); return
                if guarded_requested:
                    if payload.get("focus") is not None and not isinstance(payload.get("focus"), list):
                        self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "focus must be a list"}); return
                    if payload.get("changed_paths") is not None and not isinstance(payload.get("changed_paths"), list):
                        self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "changed_paths must be a list"}); return
                    for field, limit in (("focus", 16), ("changed_paths", 64)):
                        values = payload.get(field)
                        if values is not None and len(values) > limit:
                            self._send(400, {"success": False, "terminal": True, "retryable": False, "error": f"{field} exceeds maximum of {limit} items"}); return
                        if values is not None and any(not isinstance(item, str) for item in values):
                            self._send(400, {"success": False, "terminal": True, "retryable": False, "error": f"{field} items must be strings"}); return
                    if payload.get("staged") is not None and not isinstance(payload.get("staged"), bool):
                        self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "staged must be boolean"}); return
                    for field in ("task_id", "session_id", "phase", "query", "preload_profile", "base", "since_hash", "override_reason"):
                        if payload.get(field) is not None and not isinstance(payload.get(field), str):
                            self._send(400, {"success": False, "terminal": True, "retryable": False, "error": f"{field} must be string"}); return
                    for field in ("clone_id", "worktree_id", "branch", "repository_id", "repository_revision"):
                        if payload.get(field) is not None and not isinstance(payload.get(field), str):
                            self._send(400, {"success": False, "terminal": True, "retryable": False, "error": f"{field} must be string"}); return
                    if payload.get("include_diagnostics") is not None and not isinstance(payload.get("include_diagnostics"), bool):
                        self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "include_diagnostics must be boolean"}); return
                    from .agent_consistency import ConsistencyRequest, normalize_context_phase
                    try:
                        phase = normalize_context_phase(payload.get("phase", ""))
                    except ValueError as exc:
                        self._send(400, {"success": False, "terminal": True, "retryable": False, "error": str(exc)}); return
                    approval = payload.get("approval", "")
                    if not isinstance(approval, (bool, str)):
                        self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "approval must be boolean or string"}); return
                    focus_values = tuple(str(item).strip() for item in (payload.get("focus") or []) if str(item).strip())
                    guarded_query = query_text.strip() or " ".join(focus_values[:8]).strip()
                    if not guarded_query:
                        guarded_query = f"repository context {str(payload.get('phase', '')).strip() or 'unspecified phase'}"

                    request = ConsistencyRequest(
                        root=root,
                        task_id=str(payload.get("task_id", "")),
                        session_id=str(payload.get("session_id", "")),
                        query=guarded_query,
                        phase=phase,
                        focus=focus_values,
                        workspace=str(payload.get("workspace", "")),
                        preload_profile=str(payload.get("preload_profile", "")),
                        token_budget=max_tokens,
                        changed_paths=tuple(str(item) for item in (payload.get("changed_paths") or [])),
                        base=str(payload.get("base", "HEAD")),
                        staged=bool(payload.get("staged", False)),
                        tenant=tenant,
                        override_reason=str(payload.get("override_reason", "")),
                        approval=approval,
                        path_hints=path_controls.path_hints if path_controls else (),
                        directory_hints=path_controls.directory_hints if path_controls else (),
                        exclude_paths=path_controls.exclude_paths if path_controls else (),
                        force_include_paths=path_controls.force_include_paths if path_controls else (),
                        project_config_digest=project_config_digest,
                    )
                    has_task_id = bool(str(payload.get("task_id", "")).strip())
                    try:
                        result = APP.services.adaptive_context_pack(
                            request,
                            mode=mode,
                            since_hash=str(payload.get("since_hash", "")),
                        )
                    except Exception as exc:
                        result = {
                            "success": False,
                            "terminal": False,
                            "retryable": True,
                            "degraded": True,
                            "degraded_reason": "repository_context_unavailable",
                            "error": f"repository context unavailable: {type(exc).__name__}",
                        }
                    repository_failed = isinstance(result, dict) and result.get("success") is False
                    if repository_failed and (not (guarded_requested and has_task_id) or auto_injected_task):
                        status_code = 503 if result.get("retryable") is True else 500
                        self._send(status_code, result); return
                    if guarded_requested and has_task_id and not getattr(APP, "agent_context", None):
                        if not auto_injected_task:
                            self._send(503, {
                                "success": False, "terminal": False, "retryable": True,
                                "stop_code": "context_task_context_unavailable",
                                "error": "task context compiler unavailable",
                            }); return
                    if guarded_requested and has_task_id and getattr(APP, "agent_context", None):
                        task_request_payload = {
                            "task_id": payload.get("task_id", ""),
                            "session_id": payload.get("session_id", ""),
                            "token_budget": max_tokens,
                            "root": root,
                            "phase": payload.get("phase", ""),
                            "focus": payload.get("focus") or [],
                            "preload_profile": payload.get("preload_profile", ""),
                            "changed_paths": payload.get("changed_paths") or [],
                            "repository_revision": payload.get("repository_revision", payload.get("repo_revision", "")),
                            "since_hash": payload.get("task_since_hash", ""),
                            "_scoped_task_only": True,
                            "clone_id": payload.get("clone_id", ""),
                            "worktree_id": payload.get("worktree_id", ""),
                            "branch": payload.get("branch", ""),
                            "repository_id": payload.get("repository_id", ""),
                            "include_diagnostics": payload.get("include_diagnostics", False),
                        }
                        task_request = build_context_request(
                            task_request_payload, tenant=tenant, identity=self._agent(),
                            project_context=_trusted_project_context(root),
                        )
                        unified = None
                        try:
                            compiled = APP.agent_context.compile(task_request)
                            unified = compose_task_context(
                                task_id=task_request.task_id,
                                compiled=compiled,
                                repository=result if isinstance(result, dict) else {"success": False, "error": "repository context response must be an object"},
                                token_budget=task_request.token_budget,
                            )
                        except Exception as exc:
                            if not auto_injected_task:
                                self._send(503, {
                                    "success": False, "terminal": False, "retryable": True,
                                    "stop_code": "context_task_context_unavailable",
                                    "error": f"task context receipt unavailable: {type(exc).__name__}",
                                }); return
                        if unified is not None:
                            provenance = unified.get("provenance") if isinstance(unified, dict) else None
                            receipt_complete = bool(
                                isinstance(unified, dict)
                                and unified.get("success") is True
                                and unified.get("complete") is True
                                and str(unified.get("context_id") or "").strip()
                                and str(unified.get("etag") or "").strip()
                                and isinstance(provenance, dict)
                                and str(provenance.get("repository_revision") or "").strip()
                                and provenance.get("status") == "success"
                            )
                            if not receipt_complete:
                                if not auto_injected_task:
                                    self._send(503, {
                                        "success": False, "terminal": True, "retryable": False,
                                        "stop_code": "context_task_context_incomplete",
                                        "error": "task context receipt is missing, stale, or incomplete",
                                        "task_context": unified if isinstance(unified, dict) else {},
                                    }); return
                            else:
                                if isinstance(result, dict):
                                    result["task_context"] = unified
                                    result["task_context_id"] = unified["context_id"]
                                    if auto_injected_task:
                                        result["task_id"] = payload.get("task_id", "")
                    if isinstance(result, dict) and "query" not in result:
                        result["query"] = guarded_query
                    self._send(200, result); return
                result = APP.services._hybrid_context(
                    root, query_text, tenant, payload.get("workspace"), max_tokens,
                    quality_first=True,
                    context_identity={
                            "tenant": tenant,
                            "path_hints": path_controls.path_hints if path_controls else (),
                            "directory_hints": path_controls.directory_hints if path_controls else (),
                            "exclude_paths": path_controls.exclude_paths if path_controls else (),
                            "force_include_paths": path_controls.force_include_paths if path_controls else (),
                            "project_config_digest": project_config_digest,
                            "memory_revision": project_memory_revision,
                    },
                    path_hints=path_controls.path_hints if path_controls else (),
                    directory_hints=path_controls.directory_hints if path_controls else (),
                    exclude_paths=path_controls.exclude_paths if path_controls else (),
                    force_include_paths=path_controls.force_include_paths if path_controls else (),
                    retrieval_weights=project_retrieval_weights,
                )
                if isinstance(result, dict):
                    result["delivery_mode"] = mode
                self._send(200, result); return
            if 'post_artifact_get_1' in post_route_ids:
                self._handle_post_artifact_get(payload, tenant)
                return
            if 'post_artifact_list_1' in post_route_ids:
                self._handle_post_artifact_list(payload, tenant)
                return
            if 'post_evidence_verify_1' in post_route_ids:
                evidence = payload.get("evidence", [])
                self._send(200, APP.repo_tools.verify_evidence(str(payload.get("root", ".")), evidence if isinstance(evidence, list) else [])); return
            if 'post_evidence_get_1' in post_route_ids:
                self._send(200, APP.evidence.get(str(payload.get("evidence_id", "")), verify=bool(payload.get("verify", True)))); return
            if 'post_leases_claim_1' in post_route_ids:
                self._handle_post_lease_claim(payload, tenant)
                return
            if path == "/api/leases/release":
                self._handle_post_lease_release(payload, tenant)
                return
            if 'post_leases_renew_1' in post_route_ids:
                self._handle_post_lease_renew(payload, tenant)
                return
            if 'post_memory_put_1' in post_route_ids:
                self._send(200, APP.memory.put(
                    str(payload.get("root", ".")), str(payload.get("key", "")), str(payload.get("value", "")), tenant,
                    ttl_seconds=payload.get("ttl_seconds"), metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
                    expected_version=payload.get("expected_version"),
                )); return
            if 'post_memory_get_1' in post_route_ids:
                self._send(200, APP.memory.get(str(payload.get("root", ".")), str(payload.get("key", "")))); return
            if 'post_memory_search_1' in post_route_ids:
                self._send(200, APP.memory.search(str(payload.get("root", ".")), str(payload.get("query", "")), int(payload.get("limit", 12)))); return
            if path == "/api/memory/delete":
                self._send(200, APP.memory.delete(
                    str(payload.get("root", ".")), str(payload.get("key", "")), tenant,
                    scope=payload.get("scope"),
                )); return
            if path == "/api/command":
                if payload.get("action", "run") == "run":
                    with _command_peer_cancellation(
                        getattr(self, "connection", None), getattr(self, "_request_cancel_event", None),
                    ) as request_cancel_event:
                        result = APP.services.command(payload, tenant, request_cancel_event=request_cancel_event)
                else:
                    result = APP.services.command(payload, tenant)
                status = 409 if isinstance(result, dict) and result.get("outcome_unknown") is True else 200
                self._send(status, result); return
            if path == "/api/embed":
                texts = payload.get("texts", payload.get("input", []))
                if isinstance(texts, str):
                    texts = [texts]
                self._send(200, APP.services.embed([str(x) for x in texts], tenant, query=bool(payload.get("query", False)))); return
            if 'post_rerank_1' in post_route_ids:
                docs = payload.get("documents", [])
                self._send(200, APP.reranker.rerank(str(payload.get("query", "")), [str(x) for x in docs], payload.get("top_k"))); return
            if 'post_rag_index_1' in post_route_ids:
                self._send(200, APP.rag.index(str(payload.get("root", ".")), tenant, payload.get("workspace"))); return
            if 'post_rag_search_1' in post_route_ids:
                workspace = str(payload.get("workspace", ""))
                if not workspace:
                    self._send(400, {"success": False, "error": "workspace is required"}); return
                self._send(200, APP.rag.search(str(payload.get("query", "")), tenant, workspace, int(payload.get("top_k", 8)), bool(payload.get("use_reranker", True)))); return
            if 'post_speculative_draft_1' in post_route_ids:
                self._send(200, APP.services.speculative_draft(payload, tenant)); return
            if 'post_scaffold_1' in post_route_ids:
                self._send(200, APP.services.task_scaffold(payload, tenant)); return
            if 'post_models_manage_1' in post_route_ids:
                action = str(payload.get("action", "list"))
                model_name = str(payload.get("model", ""))
                self._send(200, self._handle_models_action(action, model_name)); return
            if 'post_reachability_dead_code_1' in post_route_ids:
                root = str(payload.get("root", "."))
                eps = payload.get("entrypoints")
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.reachability_dead_code(root, entrypoints=eps)); return
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"}); return
            if 'post_mutation_test_1' in post_route_ids:
                root = str(payload.get("root", "."))
                tf = str(payload.get("file", payload.get("path", "")))
                diff = payload.get("diff")
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.ast_mutation_test(root, tf, diff=diff)); return
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"}); return
            if 'post_repo_type_stubs_1' in post_route_ids:
                root = str(payload.get("root", "."))
                fp = str(payload.get("file", payload.get("path", "")))
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.generate_type_stubs(root, fp)); return
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"}); return
            if 'post_repo_skeletonize_1' in post_route_ids:
                code = str(payload.get("code", ""))
                targets = payload.get("targets") or payload.get("target_symbols")
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.skeletonize_code(
                        code, target_symbols=targets, root=str(payload.get("root", "")),
                        path=str(payload.get("path", "")),
                    )); return
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"}); return
            if 'post_agent_state_events_delta_1' in post_route_ids:
                action = payload.get("action", "export")
                if action == "export":
                    stream_id = str(payload.get("stream_id", ""))
                    after_seq = int(payload.get("after_seq", 0))
                    limit = int(payload.get("limit", 1000))
                    self._send(200, APP.agent_state_store.export_delta(stream_id, after_seq, limit)); return
                else:
                    events = list(payload.get("events", []))
                    self._send(200, APP.agent_state_store.import_delta(events)); return
            if 'post_task_vision_1' in post_route_ids:
                self._send(200, APP.services.vision(payload, tenant)); return
            if 'post_task_browser_1' in post_route_ids:
                from .browser_bridge import capture_browser_page
                result = capture_browser_page(
                    payload.get("url", ""), artifacts=APP.artifacts, tenant=tenant,
                    state_dir=APP.config["server"]["state_dir"], viewport=payload.get("viewport"),
                )
                self._send(200, result); return
            if 'post_repo_split_changes_1' in post_route_ids:
                root = str(payload.get("root", "."))
                paths = payload.get("paths", payload.get("changed_files"))
                self._send(200, APP.services.split_changes(root, paths)); return
            if 'post_repo_synthesize_rules_1' in post_route_ids:
                root = str(payload.get("root", "."))
                limit = int(payload.get("limit", 10))
                self._send(200, APP.services.synthesize_rules(root, limit)); return
            if 'post_rag_docset_index_1' in post_route_ids:
                name = str(payload.get("name", payload.get("docset", "")))
                root = str(payload.get("root", payload.get("dir", ".")))
                self._send(200, APP.rag.docset_index(name, root, tenant)); return
            if 'post_rag_docset_search_1' in post_route_ids:
                name = str(payload.get("name", payload.get("docset", "")))
                query = str(payload.get("query", ""))
                top_k = int(payload.get("top_k", 8))
                self._send(200, APP.rag.docset_search(name, query, tenant, top_k=top_k)); return
            if 'post_task_transcribe_1' in post_route_ids:
                from .process_utils import ProcessCleanupUnverifiedError
                token, cancel_event = _ACTIVE_TRANSCRIPTIONS.begin()
                result: Any = {}
                cleanup_deferred = False
                try:
                    result = APP.services.transcribe(payload, tenant, cancel_event=cancel_event)
                    self._send(200, result); return
                except ProcessCleanupUnverifiedError as exc:
                    cleanup_deferred = True
                    result = {
                        "success": False, "reason": "cleanup_unverified", "error": str(exc),
                        "terminal": False, "retryable": True, "cleanup_unverified": True,
                    }
                    _ACTIVE_TRANSCRIPTIONS.defer_process_cleanup(
                        token, exc.process, tree_termination_confirmed=exc.tree_termination_confirmed,
                    )
                    self._send(503, result); return
                finally:
                    if not cleanup_deferred:
                        _ACTIVE_TRANSCRIPTIONS.finish(token, result)
            if path in {"/api/repo/code_invariants", "/api/code_invariants"}:
                self._send(200, APP.services.code_invariants(str(payload.get("root", ".")), payload.get("path"))); return
            if 'post_generate_dataset_1' in post_route_ids:
                self._send(200, APP.services.generate_dataset(str(payload.get("root", ".")), payload.get("schema_or_model") or payload.get("schema"), count=int(payload.get("count", 10)), format=str(payload.get("format", "json")))); return
            if 'post_profile_digest_1' in post_route_ids:
                self._send(200, APP.services.profile_digest(str(payload.get("profile_path") or payload.get("path") or ""), top_n=int(payload.get("top_n", 15)))); return
            if 'post_coord_worktree_lease_1' in post_route_ids:
                self._send(200, APP.services.worktree_lease(str(payload.get("root", ".")), branch_name=payload.get("branch"))); return
            if path == "/api/coord/worktree_release":
                self._send(200, APP.services.worktree_release(str(payload.get("root", ".")), str(payload.get("worktree_path", "")), delete_branch=bool(payload.get("delete_branch", True)), branch_name=payload.get("branch"), worktree_id=str(payload.get("worktree_id", "")))); return
            if path == "/api/coord/worktrees":
                self._send(200, APP.services.list_worktrees(str(payload.get("root", ".")))); return
            if 'post_coord_worktree_prune_1' in post_route_ids:
                self._send(200, APP.services.prune_worktrees(str(payload.get("root", ".")))); return

            if 'post_command_daemon_1' in post_route_ids:
                act = str(payload.get("action", "status")).lower()
                if act == "spawn":
                    self._send(200, APP.services.spawn_daemon(str(payload.get("command", "")), str(payload.get("cwd", ".")), name=str(payload.get("name", "")), env=payload.get("env"), task_id=str(payload.get("task_id", "")))); return
                elif act == "stop":
                    self._send(200, APP.services.stop_daemon(str(payload.get("daemon_id", "")), task_id=str(payload.get("task_id", "")))); return
                else:
                    self._send(200, APP.services.daemon_status(
                        payload.get("daemon_id"), task_id=str(payload.get("task_id", ""))
                    )); return
            if path == "/api/command/lint_fix":
                self._send(200, APP.services.lint_fix(str(payload.get("root", ".")), command=payload.get("command"), paths=payload.get("paths"), tenant=tenant, timeout=payload.get("timeout"))); return
            if 'post_command_http_probe_1' in post_route_ids:
                self._send(200, APP.services.http_probe(str(payload.get("url", "")), expected_status=int(payload.get("expected_status", 200)), json_path=payload.get("json_path"), timeout=float(payload.get("timeout", 5.0)), headers=payload.get("headers"))); return
            if 'post_callers_1' in post_route_ids:
                limit = payload.get("limit", 50); offset = payload.get("offset", 0)
                bounds_error = pagination_bounds_error(limit, offset)
                if bounds_error:
                    self._send(400, {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}); return
                self._send(200, APP.services.callers(str(payload.get("root", ".")), str(payload.get("symbol", "")), limit=limit, offset=offset)); return
            if 'post_callees_1' in post_route_ids:
                limit = payload.get("limit", 50); offset = payload.get("offset", 0)
                bounds_error = pagination_bounds_error(limit, offset)
                if bounds_error:
                    self._send(400, {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}); return
                self._send(200, APP.services.callees(str(payload.get("root", ".")), str(payload.get("symbol", "")), limit=limit, offset=offset)); return
            if 'post_implementations_1' in post_route_ids:
                limit = payload.get("limit", 50); offset = payload.get("offset", 0)
                bounds_error = pagination_bounds_error(limit, offset)
                if bounds_error:
                    self._send(400, {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}); return
                self._send(200, APP.services.code_find_implementations(str(payload.get("root", ".")), str(payload.get("symbol", "")), path=payload.get("path"), limit=limit, offset=offset)); return
            if 'post_declaration_1' in post_route_ids:
                self._send(200, APP.services.code_find_declaration(str(payload.get("root", ".")), str(payload.get("symbol", "")), path=payload.get("path"))); return
            if 'post_repo_secret_scan_1' in post_route_ids:
                if "git_history" in payload:
                    self._send(400, {
                        "success": False, "error": "git_history is not supported; use scan_git_history",
                        "status_code": 400, "terminal": True, "retryable": False,
                    }); return
                scan_git_history = payload.get("scan_git_history", False)
                if not isinstance(scan_git_history, bool):
                    self._send(400, {
                        "success": False, "error": "scan_git_history must be a boolean",
                        "status_code": 400, "terminal": True, "retryable": False,
                    }); return
                result = APP.services.secret_scan(
                    str(payload.get("root", ".")), payload.get("path"),
                    scan_git_history=scan_git_history,
                    commit_depth=payload.get("commit_depth", 20),
                )
                status = result.get("status_code", 200) if isinstance(result, dict) else 200
                self._send(status if status in {400, 409, 422, 500, 503} else 200, result); return
            if 'post_repo_schema_inspect_1' in post_route_ids:
                self._send(200, APP.services.schema_inspect(str(payload.get("root", ".")), payload.get("db_path"))); return
            if 'post_explain_query_1' in post_route_ids:
                self._send(200, APP.services.explain_query(str(payload.get("root", ".")), str(payload.get("query", "")), payload.get("db_path"))); return
            if 'post_env_compat_1' in post_route_ids:
                self._send(200, APP.services.env_compat(str(payload.get("root", ".")))); return
            if 'post_coord_pubsub_publish_1' in post_route_ids:
                self._send(200, APP.services.pubsub_publish(str(payload.get("topic", "default")), payload.get("message", ""), sender=str(payload.get("publisher", payload.get("sender", "agent"))))); return
            if path == "/api/coord/pubsub_poll":
                poll_kwargs: dict[str, Any] = {}
                if "after_seq" in payload:
                    poll_kwargs["after_seq"] = int(payload["after_seq"])
                if "after_ts" in payload:
                    poll_kwargs["since_timestamp"] = float(payload["after_ts"])
                if "limit" in payload:
                    poll_kwargs["limit"] = int(payload["limit"])
                self._send(200, APP.services.pubsub_poll(str(payload.get("topic", "default")), **poll_kwargs)); return
            if path == "/api/coord/simulate_merge":
                self._send(200, APP.services.simulate_merge(str(payload.get("root", ".")), str(payload.get("source_branch", "")), target_branch=str(payload.get("target_branch", "HEAD")))); return
            if 'post_eval_suite_1' in post_route_ids:
                self._send(200, APP.services.eval_suite(payload, tenant)); return
            if 'post_prompt_eval_1' in post_route_ids:
                self._send(200, APP.services.prompt_eval(payload, tenant)); return
            if 'post_eval_drift_1' in post_route_ids:
                self._send(200, APP.services.eval_drift(payload, tenant)); return
            if 'post_circular_dependencies_1' in post_route_ids:
                self._send(200, APP.services.circular_dependencies(str(payload.get("root", ".")), language=str(payload.get("language", "python")))); return
            if 'post_generate_types_1' in post_route_ids:
                if set(payload) - {"root", "path"}:
                    self._send(
                        400,
                        {
                            "success": False,
                            "error": "generate_types accepts only root and path",
                            "terminal": True,
                            "retryable": False,
                        },
                    )
                    return
                root = payload.get("root", ".")
                source_path = payload.get("path")
                if not isinstance(root, str) or not isinstance(source_path, str) or not source_path:
                    self._send(
                        400,
                        {
                            "success": False,
                            "error": "generate_types requires string root and nonempty path",
                            "terminal": True,
                            "retryable": False,
                        },
                    )
                    return
                self._send(200, APP.services.generate_types(root, source_path)); return
            if 'post_complexity_1' in post_route_ids:
                self._send(200, APP.services.code_complexity(
                    str(payload.get("root", ".")), path=payload.get("path"),
                    max_results=int(payload.get("max_results", 20)), include_tests=bool(payload.get("include_tests", False))
                )); return
            if 'post_api_spec_1' in post_route_ids:
                self._send(200, APP.services.extract_api_spec(str(payload.get("root", ".")), framework=payload.get("framework"))); return
            if 'post_dependency_slice_1' in post_route_ids:
                self._send(200, APP.services.slice_dependency_graph(str(payload.get("root", ".")), str(payload.get("symbol", "")), path=payload.get("path"), depth=int(payload.get("depth", 2)))); return
            if 'post_migration_drift_1' in post_route_ids:
                self._send(200, APP.services.migration_drift(str(payload.get("root", ".")), db_path=payload.get("db_path"))); return
            if 'post_package_audit_1' in post_route_ids:
                self._send(200, APP.services.package_audit(str(payload.get("root", ".")), lockfile_path=payload.get("lockfile_path"))); return
            if 'post_repo_structural_search_1' in post_route_ids:
                self._send(200, APP.services.structural_search(str(payload.get("root", ".")), str(payload.get("pattern", "")), path=payload.get("path"), max_results=int(payload.get("max_results", 30)))); return
            if 'post_context_budget_1' in post_route_ids:
                self._send(200, APP.services.context_budget(str(payload.get("root", ".")), files=payload.get("files"), max_tokens=int(payload.get("max_tokens", 4000)))); return
            if 'post_ingest_document_1' in post_route_ids:
                self._send(200, APP.rag.ingest_document(str(payload.get("workspace", "default")), str(payload.get("content", "")), title=str(payload.get("title", "")), metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None, tenant=tenant)); return
            if 'post_ingest_diagram_1' in post_route_ids:
                self._send(200, APP.rag.ingest_diagram(str(payload.get("workspace", "default")), str(payload.get("image_path", payload.get("path", ""))), caption=str(payload.get("caption", "")), metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None, tenant=tenant)); return
            if 'post_command_mock_server_1' in post_route_ids:
                act = str(payload.get("action", "status")).strip().lower()
                port = payload.get("port", 0 if act == "start" else 11440)
                if act == "start":
                    self._send(200, APP.services.mock_server_start(str(payload.get("root", ".")), spec_path=payload.get("spec_path"), port=port)); return
                elif act == "stop":
                    self._send(200, APP.services.mock_server_stop(port=port)); return
                else:
                    self._send(200, APP.services.mock_server_status(port=port)); return

            if 'post_command_diff_hunk_stage_1' in post_route_ids:
                self._send(200, APP.services.diff_hunk_stage(str(payload.get("root", payload.get("cwd", "."))), str(payload.get("patch", "")))); return
            if path == "/api/command/flaky_detect":
                self._send(200, APP.services.test_flaky_detect(str(payload.get("root", payload.get("cwd", "."))), str(payload.get("command", "")), runs=int(payload.get("runs", 5)), timeout_per_run=int(payload.get("timeout", 30)))); return
            if path == "/api/command/webhook_replay":
                self._send(200, APP.services.webhook_replay(str(payload.get("url", "")), payload.get("payload", {}), secret=str(payload.get("secret", "")), signature_header=str(payload.get("signature_header", "X-Hub-Signature-256")), timeout=float(payload.get("timeout", 10.0)))); return

            # Optional Ollama/OpenAI protocol proxy. Local AI applies
            # the same shared exact cache + single-flight before the Ollama queue.
            if 'post_chat_1' in post_route_ids:
                if payload.get("stream") is True:
                    self._send(400, {"error": "streaming is intentionally disabled through the affinity queue"}); return
                result = APP.services.proxy_request(path, payload, tenant, f"proxy:{path}")
                self._send(200 if "error" not in result else 500, result); return

            self._send(404, {"error": "not found"})
        except QueueFullError as exc:
            logger = getattr(APP, "logger", None)
            if logger is not None:
                logger.warning("queue full path=%s tenant=%s", path, tenant)
            self._send(429, {"success": False, "error": str(exc), "status_code": 429, "retryable": True})
        except ModelUnavailableError as exc:
            logger = getattr(APP, "logger", None)
            if logger is not None:
                logger.warning("model unavailable path=%s tenant=%s error=%s", path, tenant, exc)
            self._send(503, {"success": False, "error": str(exc), "status_code": 503, "retryable": True})
        except (ValueError, TypeError, RequestBodyError) as exc:
            logger = getattr(APP, "logger", None)
            if logger is not None:
                logger.warning("invalid request payload path=%s tenant=%s error=%s", path, tenant, exc)
            self._send(400, {"success": False, "error": str(exc), "status_code": 400, "terminal": True, "retryable": False})
        except KeyError as exc:
            logger = getattr(APP, "logger", None)
            if logger is not None:
                logger.warning("resource not found path=%s tenant=%s key=%s", path, tenant, exc)
            self._send(404, {"success": False, "error": str(exc), "status_code": 404, "terminal": True, "retryable": False})
        except Exception as exc:
            if _is_client_disconnect(exc):
                self._finish_debug_trace(499, {"success": False, "terminal": True}, error="client disconnected")
                self._close_trace_context()
            elif is_busy_error(exc):
                self._send_database_locked()
                return
            logger = getattr(APP, "logger", None)
            if logger is not None:
                logger.error("POST request failed error_type=%s", type(exc).__name__)
            try:
                self._send(500, {
                    "success": False,
                    "error": "internal server error",
                    "error_code": "internal_error",
                    "terminal": True,
                    "retryable": False,
                })
            except Exception:
                pass


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
    _require_owned_supervisor_parent(startup_state_dir)
    cfg = startup_config["server"]
    server = LocalAIHTTPServer(
        (cfg.get("bind", "127.0.0.1"), int(cfg.get("port", 11435))),
        Handler,
        max_handlers=int(cfg.get("max_concurrent_requests", 64)),
        overload_wait_seconds=float(cfg.get("overload_wait_seconds", 0.05)),
    )
    app: LocalAIApp | None = None
    pid_path: Path | None = None
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
        pid_path = state_dir / "hub.pid"
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        # Configure rate limiting from security config
        sec_cfg = APP.config.get("security", {})
        server.configure_rate_limit(
            requests=int(sec_cfg.get("rate_limit_requests", 600)),
            window_seconds=float(sec_cfg.get("rate_limit_window_seconds", 60.0)),
        )
        APP.logger.info("hub started version=%s bind=%s port=%s", __version__, cfg.get("bind", "127.0.0.1"), int(cfg.get("port", 11435)))
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
                        app.logger.info("hub stopping version=%s", __version__)
                    except Exception:
                        pass
                try:
                    app.close()
                except Exception:
                    pass
                finally:
                    if APP is app:
                        APP = None
            if pid_path is not None:
                try:
                    if pid_path.exists() and pid_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                        pid_path.unlink()
                except OSError:
                    pass


if __name__ == "__main__":
    serve(os.environ.get("LOCAL_AI_CONFIG"))
