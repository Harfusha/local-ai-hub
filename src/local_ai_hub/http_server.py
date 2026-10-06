from __future__ import annotations

import hmac
import inspect
import ipaddress
import hashlib
import json
import os
import queue
import re
import socket
import sqlite3
import uuid
import time
import threading
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
import urllib.request
from urllib.parse import parse_qs, urlparse

from . import __version__
from .app import LocalAIApp
from .scheduler import ModelUnavailableError, QueueFullError
from .debug_traces import DebugTraceObserver
from .trace_context import reset_context, reset_observer, set_context, set_observer
from .http_route_registry import select_get_handler, select_http_routes, select_post_handler
from .dashboard import DASHBOARD_HTML
from .config import ConfigError, deep_merge, load_config, save_runtime_overrides, validate_config
from .delivery import decide_delivery
from .resilience import RecoveryJournal
from .agent_identity import AgentScope, ScopeContext
from .project_config import resolve_project_context, _git_common_dir as _real_git_common_dir
from .state_paths import configured_state_dir
from .agent_tasks import CompletionGateError, GoalContract, InvalidTransitionError, TaskCheckpoint, TaskStatus
from .agent_memory import ApprovalRequiredError, MAX_MEMORY_QUERY_LIMIT, MemoryKind, MemoryRecord, MemoryStatus
from .agent_incidents import IncidentFingerprint, ToolOutcome
from .agent_verification import VerificationReceipt
from .task_context import build_context_request, compose_task_context
from .agent_learning import ImprovementCandidate, SLOObservation
from .json_utils import dumps as json_dumps

_DB_QUERY_MAX_RESPONSE_BYTES = 256 * 1024
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


def _lease_coordination_id(root: str) -> str | None:
    """Resolve lease namespace from server-side project identity only."""
    if APP is None:
        return None
    try:
        state_dir = configured_state_dir(APP.config)
        return resolve_project_context(root, state_dir).coordination_id
    except Exception:
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
    "/health", "/dashboard", "/favicon.ico", "/api/live", "/api/live/status",
    "/api/status", "/api/capabilities", "/api/metrics", "/api/adoption", "/api/telemetry/report", "/api/telemetry/tool-accounting", "/api/telemetry/timeline", "/api/audit/tail", "/api/control",
    "/api/config", "/api/logs/tail", "/api/hardware/system", "/api/hardware/gpu",
    "/api/mode", "/api/admin/mode",
    "/api/debug-traces",
}

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
HTTP_MODE_OPERATOR_POST_PATHS = frozenset({"/api/admin/mode", "/api/control"})


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
            "/api/control": "control.read",
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
            "/api/control": "control",
            "/api/db/query": "db.query",
            "/api/models/manage": "model.manage",
        }.get(path)
    return None


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
    action_tokens = security.get("action_tokens")
    if isinstance(action_tokens, dict):
        security["action_tokens"] = {
            str(action): "***configured***"
            for action, token in action_tokens.items() if token
        }
    elif action_tokens:
        security["action_tokens"] = "***configured***"
    return view
HTTP_MODE_GAMING_READ_POST_PATHS = frozenset({
    "/api/artifact/get", "/api/artifact/list", "/api/db/query",
    "/api/evidence/get", "/api/memory/get", "/api/memory/search",
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
        if not snapshot.degraded and snapshot.mode == "gaming" and policy in {"gaming_read", "existing_job"}:
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


_MODE_UNLOAD_STATUS: dict[int, dict[str, Any]] = {}
_MODE_UNLOAD_DEADLINE_SECONDS: float = 5.0


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
    _MODE_UNLOAD_STATUS[revision] = dict(initial)

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

        deadline_sec = globals().get("_MODE_UNLOAD_DEADLINE_SECONDS", 5.0)
        if not worker_done.wait(timeout=max(0.001, float(deadline_sec))):
            _MODE_UNLOAD_STATUS[revision] = {
                "success": False,
                "state": "failed",
                "reason": "unload_deadline_exceeded",
                "unloaded": [],
                "remaining": None,
            }
            return

        final_res = dict(worker_result[0])
        unsupported_cuda: list[str] = []
        for name in ("embeddings", "reranker"):
            comp = getattr(app, name, None)
            if comp is not None:
                has_model = getattr(comp, "_model", None) is not None
                is_cuda = getattr(comp, "active_device", "") == "cuda"
                if has_model and is_cuda:
                    unsupported_cuda.append(name)
        if unsupported_cuda:
            final_res["success"] = False
            final_res["state"] = "partial"
            final_res["reason"] = "in_process_cuda_unload_unsupported"
            final_res["unsupported_in_process_cuda"] = unsupported_cuda
            rem = list(final_res.get("remaining") or [])
            for c in unsupported_cuda:
                rem.append(f"in_process_cuda:{c}")
            final_res["remaining"] = rem

        cur = _MODE_UNLOAD_STATUS.get(revision)
        if isinstance(cur, dict) and cur.get("reason") == "unload_deadline_exceeded":
            return
        _MODE_UNLOAD_STATUS[revision] = final_res

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
    return json_dumps(data).encode("utf-8")


AGENT_EVENT_PAGE_MAX_BYTES = 1024 * 1024
AGENT_EVENT_PAGE_MAX_LIMIT = 100
SSE_REPLAY_MAX_EVENTS = 10_000


def _minimum_json_bytes(value: Any, ceiling: int) -> int:
    """Return lower bound for UTF-8 JSON size without encoding huge strings."""
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
    if isinstance(value, dict):
        total = 2 + max(0, len(value) - 1)
        for key, item in value.items():
            total += _minimum_json_bytes(key, max(0, ceiling - total)) + 1
            total += _minimum_json_bytes(item, max(0, ceiling - total))
            if total > ceiling:
                return ceiling + 1
        return total
    if isinstance(value, (list, tuple)):
        total = 2 + max(0, len(value) - 1)
        for item in value:
            total += _minimum_json_bytes(item, max(0, ceiling - total))
            if total > ceiling:
                return ceiling + 1
        return total
    return 0


def _bound_agent_event_page(status: int, page: dict[str, Any], after_seq: Any) -> tuple[int, dict[str, Any]]:
    """Bound event responses without advancing past rows omitted by the byte cap."""
    try:
        cursor = max(0, int(after_seq))
    except (TypeError, ValueError, OverflowError):
        cursor = 0
    events = list(page.get("events") or [])
    if not events:
        if len(_json_bytes(page)) <= AGENT_EVENT_PAGE_MAX_BYTES:
            return status, page
        return 413, {
            **page,
            "events": [],
            "next_seq": cursor,
            "error": {
                "code": "agent_event_page_too_large",
                "message": "event page metadata exceeds serialized response byte limit",
                "max_bytes": AGENT_EVENT_PAGE_MAX_BYTES,
            },
        }

    accepted: list[dict[str, Any]] = []
    accepted_page: dict[str, Any] | None = None
    for index, event in enumerate(events):
        try:
            next_seq = max(0, int(event.get("seq") or 0))
        except (AttributeError, TypeError, ValueError, OverflowError):
            break
        candidate = dict(page)
        candidate["next_seq"] = next_seq
        candidate["has_more"] = bool(page.get("has_more")) or index + 1 < len(events)
        candidate["gap_ranges"] = [
            gap for gap in (page.get("gap_ranges") or [])
            if isinstance(gap, dict) and int(gap.get("to_seq") or 0) <= next_seq
        ]
        candidate["events"] = []
        if _minimum_json_bytes(event, AGENT_EVENT_PAGE_MAX_BYTES) > AGENT_EVENT_PAGE_MAX_BYTES:
            break
        trial_events = [*accepted, event]
        candidate["events"] = trial_events
        if len(_json_bytes(candidate)) > AGENT_EVENT_PAGE_MAX_BYTES:
            break
        accepted = trial_events
        accepted_page = candidate
    if accepted_page is not None:
        return status, accepted_page
    return 413, {
        "success": False,
        "events": [],
        "next_seq": cursor,
        "first_retained_seq": max(0, int(page.get("first_retained_seq") or 0)),
        "last_seq": max(0, int(page.get("last_seq") or 0)),
        "has_more": bool(page.get("has_more")) or bool(events),
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
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    aliases = {
        "code", "task", "tasks", "repo", "repository", "project", "workspace",
        "worktree", "worktrees", "clone", "branch", "branches", "session", "sessions",
        "global", "user",
    }
    if raw not in aliases:
        raise ValueError(f"invalid memory scope '{raw}'")
    return AgentScope.parse(raw, default=None)


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
            try:
                state = fingerprint(root_value, force=True)
            except TypeError:
                state = fingerprint(root_value)
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
    """Extract bounded phase timings from a local-generation response."""
    latency = data.get("latency", {}) if isinstance(data, dict) else {}
    latency = latency if isinstance(latency, dict) else {}
    def value(name: str) -> float:
        try:
            return max(0.0, float(latency.get(name, 0) or 0))
        except (TypeError, ValueError):
            return 0.0
    return {"queue_wait_ms": value("queue_wait_ms"), "service_ms": value("service_ms")}


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


class LocalAIHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server with a hard cap on live handler threads and per-tenant rate limiting.

    ``ThreadingHTTPServer`` is otherwise unbounded: a burst of local agents or a
    misbehaving remote client can create hundreds of handler threads before the model
    scheduler's own queue limits are reached. Overload is rejected immediately with a
    small 503 so the hub remains responsive to health checks and existing work.
    """

    daemon_threads = True
    allow_reuse_address = True
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


class Handler(BaseHTTPRequestHandler):
    DEBUG_TRACE_REQUEST_CAPTURE_BYTES = 8 * 1024
    _DEBUG_TRACE_SENSITIVE_KEY = re.compile(
        r"^(?:token|api[_-]?(?:key|token)|access[_-]?token|refresh[_-]?token|auth[_-]?token|id[_-]?token|bearer[_-]?token|authorization|secret|password|passwd|credential|cookie|set[-_]?cookie|private[-_]?key|privatekey|passphrase|pem|ssh[-_]?key|certificate)$",
        re.IGNORECASE,
    )
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        try:
            keepalive = float(APP.config.get("server", {}).get("keepalive_timeout_seconds", 5.0)) if APP is not None else 5.0
            self.connection.settimeout(max(1.0, keepalive))
        except Exception:
            pass

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
                return
            mname = 'do_' + self.command
            if not hasattr(self, mname):
                self.send_error(501, f"Unsupported method ({self.command!r})")
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
            "agent_state": state_dir / "agent_state.sqlite3",
            "cache": state_dir / "cache.sqlite3",
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
                with urllib.request.urlopen(req, timeout=120):
                    return {"success": True, "pulled": model_name}
            return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as exc:
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
        self._trace_context_token = set_context(request_id=request_id, trace_id=trace_id, agent=self._agent(), tenant=self._tenant())
        self._debug_trace_id = ""
        self._debug_observer_token = None
        try:
            if APP is not None:
                excluded = set(APP.config.get("observability", {}).get("exclude_http_paths", []))
                if path not in MONITOR_PATHS and not path.startswith("/api/debug-traces/") and path not in excluded:
                    APP.telemetry.record_live(kind="request", event_type="request_start", tenant=self._tenant(), agent=self._agent(), request_id=request_id, trace_id=trace_id, action=path, success=True)
                    trace_store = getattr(APP, "debug_traces", None)
                    if trace_store is not None:
                        self._debug_trace_id = trace_store.start(kind="api_request", tenant=self._tenant(), agent=self._agent(), action=path, source="http", request_id=request_id)
                        if self._debug_trace_id:
                            trace_store.event(self._debug_trace_id, "request_received", {"method": self.command, "path": path, "request_id": request_id})
                            self._debug_observer_token = set_observer(DebugTraceObserver(trace_store, self._debug_trace_id))
        except Exception:
            pass

    def _ensure_trace_request_id(self) -> str:
        request_id = getattr(self, "_trace_request_id", None)
        if not request_id:
            request_id = self.headers.get("X-LocalAI-Request-ID") or uuid.uuid4().hex
            self._trace_request_id = request_id
        return request_id

    @classmethod
    def _safe_debug_trace_request(cls, payload: Any) -> dict[str, Any]:
        """Return a small redacted JSON/form payload suitable for durable trace storage."""
        if not isinstance(payload, dict):
            return {"capture_status": "omitted", "reason": "unsupported request body"}

        def redact(value: Any, key: str = "") -> Any:
            if cls._DEBUG_TRACE_SENSITIVE_KEY.search(key):
                return "[redacted]"
            if isinstance(value, dict):
                return {str(child_key): redact(child_value, str(child_key)) for child_key, child_value in value.items()}
            if isinstance(value, list):
                return [redact(item) for item in value[:100]]
            if isinstance(value, (str, int, float, bool)) or value is None:
                return value
            return "[unsupported value]"

        captured = redact(payload)
        try:
            encoded = json_dumps(captured, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError):
            return {"capture_status": "omitted", "reason": "unserializable request body"}
        if len(encoded) > cls.DEBUG_TRACE_REQUEST_CAPTURE_BYTES:
            return {
                "capture_status": "omitted",
                "reason": "request body exceeds trace capture limit",
                "captured_limit_bytes": cls.DEBUG_TRACE_REQUEST_CAPTURE_BYTES,
            }
        return captured

    def _finish_debug_trace(self, status: int, data: Any, *, error: str = "") -> None:
        trace_id = str(getattr(self, "_debug_trace_id", "") or "")
        store = getattr(APP, "debug_traces", None) if APP is not None else None
        if not trace_id or store is None or getattr(self, "_debug_trace_finished", False):
            return
        try:
            failed = status >= 400 or (isinstance(data, dict) and data.get("success") is False)
            redacted = bool(getattr(self, "_debug_trace_redacted", False))
            detail = "" if redacted else error or (str(data.get("error", "")) if isinstance(data, dict) else "")
            if redacted:
                data = {"success": not failed, "conversation_redacted": True}
            state = "failed" if failed else "done"
            finished = store.finish(trace_id, state=state, response=data, error=detail)
            if not finished:
                # A concurrent event writer can briefly hold SQLite's write lock.
                # Do not mark the trace finished until the terminal write is real;
                # one bounded second attempt prevents successful requests from
                # being left visibly running without creating retry loops.
                time.sleep(0.02)
                finished = store.finish(trace_id, state=state, response=data, error=detail)
            if finished:
                self._debug_trace_finished = True
        except Exception:
            pass

    def _redact_debug_trace(self) -> None:
        """Keep in-memory conversation transcripts out of durable debug traces."""
        token = getattr(self, "_debug_observer_token", None)
        if token is not None:
            try:
                reset_observer(token)
            except Exception:
                pass
            self._debug_observer_token = None
        self._debug_trace_redacted = True

    def _reconcile_debug_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        """Make a stale trace follow the request journal when it is terminal."""
        if not isinstance(trace, dict) or trace.get("state") not in {"queued", "running"}:
            return trace
        store = getattr(APP, "debug_traces", None) if APP is not None else None
        recovery = getattr(APP, "recovery", None) if APP is not None else None
        if store is None or recovery is None or not trace.get("request_id"):
            return trace
        try:
            journal = recovery.lookup(str(trace.get("request_id")), str(trace.get("tenant", "")), str(trace.get("action", "")))
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
        requested = self.headers.get("X-LocalAI-Tenant") or self.headers.get("X-Tenant-ID") or "http-default"
        path = str(getattr(self, "path", ""))
        security = APP.config.get("security", {}) if APP is not None else {}
        if APP is not None and (path.startswith("/api/browser/") or path == "/api/vision/review") and security.get("api_token"):
            return str(APP.config.get("browser_bridge", {}).get("tenant", "http-default") or "http-default")
        return requested

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
            if hasattr(context, "resolution"):
                shared_ns = getattr(getattr(context, "settings", None), "shared_namespace", None)
                has_git = _real_git_common_dir(Path(context.root)) is not None
                if not shared_ns and not has_git:
                    return root, ""
            repository_id = str(getattr(context, "coordination_id", "") or "").strip()
            return root, repository_id
        except Exception:
            return None

    def _tenant_binding_allowed(self) -> bool:
        if APP is None:
            return True
        path = str(getattr(self, "path", ""))
        security = APP.config.get("security", {})
        if not (path.startswith("/api/browser/") or path == "/api/vision/review") or not security.get("api_token"):
            return True
        configured = str(APP.config.get("browser_bridge", {}).get("tenant", "http-default") or "http-default")
        requested = self.headers.get("X-LocalAI-Tenant") or self.headers.get("X-Tenant-ID")
        if requested and str(requested).strip() != configured:
            self._send(403, {"success": False, "error": "browser bridge tenant is bound to its configured token tenant", "error_code": "tenant_binding_mismatch", "terminal": True, "retryable": False})
            return False
        return True

    def _agent(self) -> str:
        return self.headers.get("X-LocalAI-Agent") or "generic"

    def _authorized(self, action: str | None = None) -> bool:
        if APP is None:
            return _is_loopback_client_address(getattr(self, "client_address", None))
        security = APP.config.get("security", {})
        if not isinstance(security, dict):
            self._authorization_actor = "unrecognized"
            return False
        expected = str(security.get("api_token", "") or "")
        action_tokens = security.get("action_tokens", {})
        if not isinstance(action_tokens, dict):
            self._authorization_actor = "unrecognized"
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
        scoped = str(action_tokens.get(action, "")) if action else ""
        scoped_valid = len(scoped) >= 16 and _token_matches(supplied, scoped)
        local_client = _is_loopback_client_address(getattr(self, "client_address", None))
        self._authorization_actor = (
            "api_token" if global_valid else
            "action_token" if scoped_valid else
            "local" if not expected and not action_tokens and local_client else
            "unrecognized"
        )
        if global_valid or scoped_valid:
            return True
        if expected or action_tokens:
            return False
        return local_client

    def _audit_admin_authorization(self, action: str, *, allowed: bool) -> bool:
        if APP is None:
            return False
        telemetry = getattr(APP, "telemetry", None)
        recorder = getattr(telemetry, "record_system", None)
        if not callable(recorder):
            return False
        try:
            recorder(
                "admin.authorization",
                success=allowed,
                component="http_admin",
                operation=action,
                path=urlparse(str(getattr(self, "path", ""))).path,
                actor=str(getattr(self, "_authorization_actor", "unknown")),
            )
            return True
        except Exception:
            return False

    def _audit_admin_result(self, status: int) -> None:
        action = str(getattr(self, "_admin_action", "") or "")
        if not action or getattr(self, "_admin_result_audited", False):
            return
        self._admin_result_audited = True
        telemetry = getattr(APP, "telemetry", None) if APP is not None else None
        recorder = getattr(telemetry, "record_system", None)
        if not callable(recorder):
            return
        try:
            recorder(
                "admin.action.result",
                success=200 <= int(status) < 400,
                component="http_admin",
                operation=action,
                path=urlparse(str(getattr(self, "path", ""))).path,
                status_code=int(status),
                actor=str(getattr(self, "_authorization_actor", "unknown")),
            )
        except Exception:
            pass

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
            client_host = str(server_cfg.get("client_host", "")).strip("[]").lower()
            if client_host:
                allowed_hosts.add(client_host)
            for extra in APP.config.get("security", {}).get("allowed_hosts", []):
                allowed_hosts.add(str(extra).strip("[]").lower())

            if not APP.config.get("security", {}).get("allow_remote", False):
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
            client_host = str(server_cfg.get("client_host", "")).strip("[]").lower()
            if client_host:
                allowed_origins.add(client_host)
            for extra in APP.config.get("security", {}).get("allowed_origins", []):
                allowed_origins.add(str(extra).strip("[]").lower())

            if not APP.config.get("security", {}).get("allow_remote", False):
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

    def _require_authorized(self) -> bool:
        if not self._validate_host_and_origin():
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
        authorized = self._authorized(action)
        if not authorized and local_mode_read:
            self._authorization_actor = "local"
            authorized = True
        if not authorized:
            if action:
                self._audit_admin_authorization(action, allowed=False)
            self._send(401, {"success": False, "error": "unauthorized"})
            return False
        if action and not self._audit_admin_authorization(action, allowed=True):
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

    def _handle_post_telemetry_timeline(self, payload: Any) -> None:
        limit = payload.get("limit", 100) if isinstance(payload, dict) else 100
        before_id = payload.get("before_id") if isinstance(payload, dict) else None
        self._send(200, {"success": True, **APP.telemetry.get_timeline_page(limit, before_id=before_id)})

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
        supplied_request_id = self.headers.get("X-LocalAI-Request-ID")
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

    def _send(self, status: int, data: Any, *, headers: Mapping[str, str] | None = None) -> None:
        self._audit_admin_result(status)
        if status >= 400 and isinstance(data, dict):
            data = dict(data)
            data.setdefault("success", False)
            data.setdefault("status_code", status)
            retryable = status in {408, 425, 429, 500, 502, 503, 504}
            data.setdefault("retryable", retryable)
            data.setdefault("terminal", not retryable)
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
        body = _json_bytes(data)
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
                        queue_wait_ms=phase_latency["queue_wait_ms"], service_ms=phase_latency["service_ms"],
                    )
                    request_evaluation = getattr(self, "_request_evaluation", None)
                    if reliability_success and request_evaluation is not None:
                        APP.telemetry.record_request_evaluation(request_evaluation, duration_ms=elapsed_ms)
                    if record_operational_error and err:
                        APP.telemetry.record_error("http", path, err, request_id=str(getattr(self, "_trace_request_id", "")), tenant=self._tenant(), agent=self._agent(), retryable=status in {429, 500, 502, 503, 504})
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
            if not getattr(self, "_debug_trace_finished", False):
                self._finish_debug_trace(status, data)
            self._close_trace_context()

    def _finish_stream_request(self, success: bool, error: str = "") -> None:
        """Finish journal/telemetry for responses whose headers/body were streamed manually."""
        if APP is None:
            return
        self._finish_debug_trace(200 if success else 500, {"success": success, "streamed": True, "error": error} if error else {"success": success, "streamed": True}, error=error)
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
                    APP.telemetry.record_error("http", path, error, request_id=str(getattr(self, "_trace_request_id", "")), tenant=self._tenant(), agent=self._agent(), retryable=True)
                self._telemetry_finished = True
            except Exception:
                pass
        self._close_trace_context()

    def _stream_agent_events(self, stream_id: str = "", kind: str = "", after_seq: int = 0, timeout: float = 0.0) -> None:
        if APP is None or not getattr(APP, "agent_state", None) or not APP.agent_state.enabled:
            self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False})
            return

        # EventSource reconnects carry the last numeric event ID automatically.
        # It is safe to apply only with an explicit stream filter; an unscoped
        # cursor could otherwise resume one stream inside another.
        headers = getattr(self, "headers", {})
        last_event_id = str(headers.get("Last-Event-ID", "") or "").strip()
        if stream_id and last_event_id.isascii() and last_event_id.isdecimal():
            try:
                resume_seq = int(last_event_id)
            except (TypeError, ValueError, OverflowError):
                resume_seq = -1
            if 0 <= resume_seq <= (1 << 63) - 1:
                after_seq = resume_seq

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
        q = APP.agent_state.subscribe(maxsize=200)
        try:
            # Subscribe before fetching history. An event appended in the replay
            # window is then either replayed or queued; duplicate queued events
            # are discarded by the sequence check below.
            last_seq = after_seq
            if stream_id and after_seq >= 0:
                replay_cursor = after_seq
                replay_through_seq = None
                replayed_events = 0
                while replayed_events < SSE_REPLAY_MAX_EVENTS:
                    page_limit = min(AGENT_EVENT_PAGE_MAX_LIMIT, SSE_REPLAY_MAX_EVENTS - replayed_events)
                    page = APP.agent_state.event_page(
                        stream_id=stream_id,
                        after_seq=replay_cursor,
                        limit=page_limit,
                        through_seq=replay_through_seq,
                    )
                    if page.get("success") is not True:
                        stream_success = False
                        stream_error = "event replay unavailable"
                        payload = json_dumps(page, separators=(",", ":"))
                        try:
                            self.wfile.write(f"event: replay_error\ndata: {payload}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        except OSError:
                            stream_error = "client disconnected"
                        return
                    if replay_through_seq is None:
                        raw_high_water = page.get("last_seq", replay_cursor)
                        replay_through_seq = max(0, int(replay_cursor if raw_high_water is None else raw_high_water))
                        if replay_cursor > replay_through_seq:
                            first_retained = max(0, int(page.get("first_retained_seq", 0) or 0))
                            checkpoint = min(max(0, first_retained - 1), replay_through_seq)
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
                            reset_msg = (
                                f"id: {checkpoint}\nevent: replay_cursor_reset\ndata: "
                                f"{json_dumps(cursor_reset, separators=(',', ':'))}\n\n"
                            ).encode("utf-8")
                            try:
                                self.wfile.write(reset_msg)
                                self.wfile.flush()
                            except OSError:
                                stream_success = False
                                stream_error = "client disconnected"
                                return
                            replay_cursor = checkpoint
                            last_seq = checkpoint
                            continue
                    page_payload = json_dumps(page, separators=(",", ":"))
                    page_msg = f"id: {page.get('next_seq', replay_cursor)}\nevent: replay_page\ndata: {page_payload}\n\n".encode("utf-8")
                    try:
                        self.wfile.write(page_msg)
                        self.wfile.flush()
                    except OSError:
                        stream_success = False
                        stream_error = "client disconnected"
                        return
                    if page.get("cursor_reset") is True:
                        first_retained = int(page.get("first_retained_seq", 0) or 0)
                        last_seq = max(0, first_retained - 1)
                    replay_events = page.get("events", [])
                    if not isinstance(replay_events, (list, tuple)):
                        replay_events = []
                    for raw_event in replay_events:
                        if not isinstance(raw_event, dict):
                            continue
                        event_seq = int(raw_event.get("seq", 0) or 0)
                        event_kind = str(raw_event.get("kind", ""))
                        if event_seq <= last_seq or (kind and event_kind != kind):
                            continue
                        last_seq = event_seq
                        payload = json_dumps(raw_event, separators=(",", ":"))
                        msg = f"id: {event_seq}\nevent: {event_kind}\ndata: {payload}\n\n".encode("utf-8")
                        try:
                            self.wfile.write(msg)
                            self.wfile.flush()
                        except OSError:
                            stream_success = False
                            stream_error = "client disconnected"
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
                                f"id: {last_seq}\nevent: replay_limit\ndata: "
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
                    try:
                        timeout_msg = f"event: stream_timeout\ndata: {{\"reconnect\":true,\"next_seq\":{last_seq},\"last_seq\":{last_seq}}}\n\n".encode("utf-8")
                        self.wfile.write(timeout_msg)
                        self.wfile.flush()
                    except OSError:
                        stream_success = False
                        stream_error = "client disconnected"
                    break
                try:
                    ev = q.get(timeout=min(1.0, remaining))
                    if ev.seq is not None and ev.seq <= last_seq:
                        continue
                    if stream_id and ev.stream_id != stream_id:
                        continue
                    if kind and ev.kind != kind:
                        continue
                    if ev.seq is not None:
                        last_seq = max(last_seq, ev.seq)
                    payload = json_dumps(ev.to_dict(), separators=(",", ":"))
                    msg = f"id: {ev.seq or 0}\nevent: {ev.kind}\ndata: {payload}\n\n".encode("utf-8")
                    self.wfile.write(msg)
                    self.wfile.flush()
                except queue.Empty:
                    try:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
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
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/health":
            self._send(200, {"success": True, "hub_online": True, "version": __version__})
            return
        if APP is None:
            self._send(503, {"success": False, "error": "hub starting up; please retry", "status_code": 503, "retryable": True})
            return
        # The dashboard shell contains no runtime data. Keeping it public lets a
        # remote deployment prompt for an API token client-side; every data/control
        # endpoint remains authenticated.
        loopback_mode_get = (
            path == "/api/mode"
            and _is_loopback_client_address(getattr(self, "client_address", None))
        )
        if (
            path not in {"/", "/dashboard", "/favicon.ico"}
            and not loopback_mode_get
            and not self._require_authorized()
        ):
            return
        mode_rejection = _http_mode_gate_error("GET", path)
        if mode_rejection is not None:
            self._send(503, mode_rejection)
            return
        self._begin_trace(path)
        query = parse_qs(parsed.query)
        try:
            get_handler_name = select_get_handler(path)
            if get_handler_name is not None:
                getattr(self, get_handler_name)(query)
                return
            if path in {"/", "/dashboard"}:
                if not bool(APP.config.get("monitoring", {}).get("dashboard_enabled", True)) or not bool(APP.config.get("features", {}).get("dashboard", True)):
                    self._send(404, {"error": "dashboard disabled"}); return
                self._telemetry_finished = True
                self._send_html(200, DASHBOARD_HTML); return
            if path == "/api/mode":
                api = _operational_mode_api()
                app_cfg = getattr(APP, "config", None)
                async_jobs = getattr(APP, "async_jobs", None)
                jobs_path = getattr(async_jobs, "path", None)
                if jobs_path is not None:
                    state_dir = Path(jobs_path).parent
                else:
                    state_dir = app_cfg.get("server", {}).get("state_dir", "state") if isinstance(app_cfg, dict) else "state"
                load_fn = getattr(api, "load_operational_mode", load_operational_mode)
                try:
                    snapshot = load_fn(state_dir=state_dir)
                except TypeError:
                    snapshot = load_fn(state_dir)
                snap_dict = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot.__dict__)
                unload_info = _MODE_UNLOAD_STATUS.get(snapshot.revision)
                if unload_info is not None:
                    snap_dict["runtime_unload"] = unload_info
                self._send(200, {"success": True, **snap_dict}); return
            if path == "/favicon.ico":
                self._telemetry_finished = True
                self.send_response(204); self.end_headers(); return
            if path == "/api/status":
                detail = str((query.get("detail") or [""])[0]).strip().lower()
                if detail == "agent_state":
                    agent_state = getattr(APP, "agent_state", None)
                    agent_state_enabled = bool(agent_state and getattr(agent_state, "enabled", False))
                    tasks = APP.agent_tasks.list_tasks() if getattr(APP, "agent_tasks", None) else []
                    active_tasks = [t.task_id for t in tasks if t.status == TaskStatus.ACTIVE]
                    incidents = APP.agent_incidents.list_incidents() if getattr(APP, "agent_incidents", None) else []
                    candidates = APP.agent_learning.list_candidates() if getattr(APP, "agent_learning", None) else []
                    self._send(200, {
                        "success": True,
                        "enabled": agent_state_enabled,
                        "active_tasks": active_tasks,
                        "tasks_count": len(tasks),
                        "incidents_count": len(incidents),
                        "candidates_count": len(candidates),
                        "status": "healthy" if agent_state_enabled else "disabled",
                    }); return
                scope = str((query.get("scope") or ["process"])[0])
                status = APP.status(scope=scope)
                if isinstance(self.server, LocalAIHTTPServer):
                    status["http_concurrency"] = self.server.concurrency_stats()
                self._send(200, status); return
            if path == "/api/agent-state/tasks":
                if not getattr(APP, "agent_tasks", None) or not APP.agent_tasks.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                task_id = (query.get("task_id") or [""])[0]
                if task_id:
                    task = APP.agent_tasks.get(task_id)
                    if not task:
                        self._send(404, {"success": False, "error": "task not found", "terminal": True, "retryable": False}); return
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
                response = {"success": True, "tasks": [t.to_dict() for t in tasks]}
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
                    requested_repository_id = (query.get("repository_id") or [None])[0]
                    project_identity = self._memory_project_identity(requested_root)
                    if requested_root and project_identity is None:
                        self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
                    root_val = project_identity[0] if project_identity else None
                    repository_id_val = None
                    if requested_repository_id:
                        repository_id_val = project_identity[1] if project_identity and project_identity[1] else str(requested_repository_id).strip()
                    explicit_tenant = self.headers.get("X-LocalAI-Tenant") or self.headers.get("X-Tenant-ID")
                    tenant_val = str(explicit_tenant).strip() if explicit_tenant else (query.get("tenant") or [None])[0]
                    if tenant_val:
                        tenant_val = str(tenant_val).strip() or None
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
                requested_repository_id = (query.get("repository_id") or [None])[0]
                project_identity = self._memory_project_identity(requested_root)
                if requested_root and project_identity is None:
                    self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
                root_val = project_identity[0] if project_identity else None
                repository_id_val = None
                if requested_repository_id:
                    repository_id_val = project_identity[1] if project_identity and project_identity[1] else str(requested_repository_id).strip()
                explicit_tenant = self.headers.get("X-LocalAI-Tenant") or self.headers.get("X-Tenant-ID")
                tenant_val = str(explicit_tenant).strip() if explicit_tenant else (query.get("tenant") or [None])[0]
                if tenant_val:
                    tenant_val = str(tenant_val).strip() or None
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
                legacy_unscoped = scope_val is None and not any(
                    str(value or "").strip()
                    for value in (
                        scope_id_val, task_id_val, session_id_val, clone_id_val, worktree_id_val,
                        branch_val, root_val, repository_id_val, tenant_val,
                    )
                )
                if legacy_unscoped:
                    records = APP.agent_memory.find(
                        scope=None,
                        allow_legacy_unscoped=True,
                        key=key_val,
                        query=query_val,
                        status=status_val,
                        limit=limit_val,
                    )
                if not legacy_unscoped:
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
                if agent_state is None:
                    self._send(503, {"success": False, "events": [], "next_seq": 0, "error": {"code": "event_page_unavailable", "message": "agent state is unavailable"}}); return
                stream_id = (query.get("stream_id") or [""])[0]
                after_seq = (query.get("after_seq") or ["0"])[0]
                try:
                    int(after_seq)
                except (TypeError, ValueError, OverflowError):
                    after_seq = "0"
                try:
                    requested_limit = int((query.get("limit") or [100])[0])
                except (TypeError, ValueError, OverflowError):
                    requested_limit = 100
                page_kwargs: dict[str, Any] = {
                    "stream_id": stream_id,
                    "after_seq": after_seq,
                    "limit": max(1, min(requested_limit, AGENT_EVENT_PAGE_MAX_LIMIT)),
                }
                through_seq = (query.get("through_seq") or [None])[0]
                if through_seq is not None:
                    page_kwargs["through_seq"] = through_seq
                page = agent_state.event_page(**page_kwargs)
                error = page.get("error") or {}
                status = 200 if page.get("success") is True else (
                    403 if error.get("code") == "agent_state_disabled" else 503
                )
                status, page = _bound_agent_event_page(status, page, after_seq)
                self._send(status, page); return
            if path == "/api/agent-state/blackboard":
                if not getattr(APP, "agent_blackboard", None):
                    self._send(503, {"success": False, "error": "blackboard unavailable"}); return
                board_id = (query.get("board_id") or ["default"])[0]
                section = (query.get("section") or [None])[0]
                self._send(200, APP.agent_blackboard.get(board_id, section=section)); return
            if path == "/api/agent-state/swarm":
                if not getattr(APP, "swarm", None):
                    self._send(503, {"success": False, "error": "swarm coordinator unavailable"}); return
                st = (query.get("state") or [None])[0]
                lim = int((query.get("limit") or [50])[0])
                self._send(200, APP.swarm.list_swarms(state=st, limit=lim)); return
            if path.startswith("/api/agent-state/swarm/"):
                swarm_id = path.split("/api/agent-state/swarm/", 1)[1].strip()
                if not getattr(APP, "swarm", None):
                    self._send(503, {"success": False, "error": "swarm coordinator unavailable"}); return
                self._send(200, APP.swarm.get_status(swarm_id)); return
            if path == "/api/agent-state/events/stream":
                if not getattr(APP, "agent_state", None) or not APP.agent_state.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                stream_filter = (query.get("stream_id") or [""])[0]
                kind_filter = (query.get("kind") or [""])[0]
                after_seq = int((query.get("after_seq") or [0])[0])
                timeout = float((query.get("timeout") or [0.0])[0])
                self._stream_agent_events(stream_id=stream_filter, kind=kind_filter, after_seq=after_seq, timeout=timeout)
                return
            if path == "/api/capabilities":
                self._send(200, APP.capabilities()); return
            if path == "/api/benchmark/summary":
                if not getattr(APP, "benchmark_runner", None):
                    self._send(200, {"available": False}); return
                self._send(200, APP.benchmark_runner.get_latest_summary()); return
            if path == "/api/metrics":
                days = int((query.get("days") or [30])[0])
                scope = str((query.get("scope") or ["window"])[0])
                self._send(200, {"success": True, "metrics": APP.telemetry.summary(days, scope=scope)}); return
            if path == "/api/adoption":
                store = getattr(getattr(APP, "services", None), "adoption_metrics", None)
                if store is None:
                    self._send(200, {"success": True, "available": False}); return
                self._send(200, {"success": True, "available": True, "adoption": store.report(days=7)}); return
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
                    recent_errors = int((query.get("recent_errors") or [25])[0])
                    error_offset = int((query.get("error_offset") or [0])[0])
                    error_cursor_values = parse_qs(parsed.query, keep_blank_values=True).get("error_cursor")
                    error_cursor = error_cursor_values[0] if error_cursor_values else None
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
                self._send(200, {"success": True, **APP.telemetry.get_timeline_page(limit, before_id=before_id)}); return
            if path == "/api/audit/tail":
                limit = int((query.get("limit") or [20])[0])
                self._send(200, {"success": True, "events": APP.telemetry.tail(limit)}); return
            if path == "/api/debug-traces":
                result = APP.debug_traces.list(
                    kind=str((query.get("kind") or [""])[0]),
                    state=str((query.get("state") or [""])[0]),
                    agent=str((query.get("agent") or [""])[0]),
                    model=str((query.get("model") or [""])[0]),
                    limit=int((query.get("limit") or [50])[0]),
                    offset=int((query.get("offset") or [0])[0]),
                )
                for item in result.get("items", []):
                    self._reconcile_debug_trace(item)
                self._send(200, result); return
            if path.startswith("/api/debug-traces/"):
                trace_id = path.rsplit("/", 1)[-1]
                since_seq = int((query.get("since_seq") or [0])[0])
                result = APP.debug_traces.detail(trace_id, since_seq=max(0, since_seq))
                if result.get("error") == "trace not found":
                    self._send(404, result); return
                if result.get("success") and isinstance(result.get("session"), dict):
                    session = self._reconcile_debug_trace(result["session"])
                    result["terminal"] = session.get("state") in APP.debug_traces.TERMINAL_STATES
                self._send(200, result); return
            if path == "/api/rag/workspaces":
                self._send(200, {"success": True, "workspaces": APP.rag.list_workspaces(self._tenant())}); return
            if path == "/api/leases":
                root = (query.get("root") or [""])[0]
                coordination_id = _lease_coordination_id(root)
                self._send(200, {"success": True, "leases": APP.leases.list(root, coordination_id=coordination_id), "waits": APP.leases.waits(root, coordination_id=coordination_id)}); return
            if path == "/api/cross_project_graph":
                roots = [str(p.get("root")) for p in APP.preprocessor.status().get("projects", []) if p.get("root")]
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
                self._send(200, {"success": True, "config": view, "config_path": APP.config.get("_config_path", ""), "runtime_override_path": APP.config.get("_runtime_override_path", "")})
                return
            if path == "/api/logs/tail":
                try:
                    lines = max(1, min(int((query.get("lines") or [200])[0]), 1000))
                    log_path = Path(APP.config["server"]["state_dir"]) / "logs" / "hub.log"
                    if not log_path.is_file():
                        self._send(200, {"success": True, "path": str(log_path), "lines": []}); return
                    with log_path.open("rb") as fh:
                        fh.seek(0, 2); size = fh.tell(); fh.seek(max(0, size - 512 * 1024))
                        text = fh.read(512 * 1024).decode("utf-8", errors="replace")
                    self._send(200, {"success": True, "path": str(log_path), "lines": text.splitlines()[-lines:]})
                except (OSError, ValueError) as exc:
                    self._send(400, {"success": False, "error": str(exc)})
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
                include_body = bool((query.get("include_body") or [False])[0])
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
                    except Exception as exc:
                        self._send(200, {"success": False, "error": str(exc)})
                else:
                    self._send(200, {"success": False, "error": "repo_state tracker unavailable"})
                return
            if path == "/api/git/diff":
                root = (query.get("root") or ["."])[0]
                p = (query.get("path") or [None])[0]
                staged = (query.get("staged") or ["false"])[0].lower() in {"1", "true", "yes"}
                if APP.deterministic is not None:
                    self._send(200, APP.services.git_diff(root, path=p, staged=staged))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/git/history_search":
                root = (query.get("root") or ["."])[0]
                q = (query.get("query") or [""])[0]
                max_c = int((query.get("max_commits") or [20])[0])
                if APP.deterministic is not None:
                    self._send(200, APP.services.git_history_search(root, q, max_commits=max_c))
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
            try:
                if APP is not None:
                    APP.logger.exception("GET request failed path=%s error=%s", path, type(exc).__name__)
                self._send(500, {"success": False, "error": str(exc)})
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

    def do_POST(self) -> None:
        if APP is None:
            self._send(503, {"success": False, "error": "hub starting up; please retry", "status_code": 503, "retryable": True})
            return
        path = urlparse(self.path).path
        if not self._require_authorized():
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
            changed_info = None
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
                    if snapshot.mode == "gaming":
                        _ACTIVE_TRANSCRIPTIONS.enter_gaming()
                        _ACTIVE_CONVERSATIONS.enter_gaming()
                    elif snapshot.mode == "active":
                        _ACTIVE_TRANSCRIPTIONS.enter_active()
                        _ACTIVE_CONVERSATIONS.enter_active()
                    if callable(mode_changed):
                        try:
                            changed_info = mode_changed(snapshot)
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
            unload_gaming_fn = getattr(api, "unload_ollama_models_for_gaming", None)
            if snapshot.mode == "gaming" and callable(unload_gaming_fn):
                sched = getattr(APP, "scheduler", None)
                sched_busy = sched.foreground_busy() if callable(getattr(sched, "foreground_busy", None)) else False
                inf_active = (isinstance(changed_info, dict) and bool(changed_info.get("inference_active"))) or sched_busy
                if inf_active:
                    runtime_unload = {
                        "success": False,
                        "state": "deferred",
                        "reason": "inference_active",
                        "unloaded": [],
                        "remaining": None,
                    }
                else:
                    runtime = getattr(APP, "runtime", None)
                    runtime_unload = _start_gaming_model_unload(
                        snapshot.revision, runtime, unload_gaming_fn, APP
                    )
                snap_dict = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot.__dict__)
                self._send(200, {
                    "success": True,
                    **snap_dict,
                    "runtime_unload": runtime_unload,
                })
                return
            self._telemetry_finished = True
            snap_dict = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot.__dict__)
            response = {"success": True, **snap_dict}
            runtime_unload: dict[str, Any] | None = None
            whisper_release: dict[str, Any] = {"state": "not_applicable", "inference_active": False}
            conversation_release: dict[str, Any] = {"state": "not_applicable", "inference_active": False}
            admission_release: dict[str, Any] = {"state": "not_applicable", "inference_active": False}
            inference_active = False
            preprocessor = getattr(APP, "preprocessor", None)
            if preprocessor is not None:
                try:
                    prep_status = preprocessor.status()
                    inference_active = not isinstance(prep_status, dict) or prep_status.get("success") is not True or any(
                        isinstance(project, dict) and project.get("status") == "running"
                        for project in prep_status.get("projects", [])
                    )
                except Exception:
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
                    except Exception:
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
                    except Exception:
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
                runtime_unload = {"success": False, "state": "skipped_active_inference", "inference_active": True}
                response["runtime_unload"] = runtime_unload
                response["accelerator_release"] = {"success": False, "state": "skipped_active_inference", "verified": False}
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
                                release_deadline = time.monotonic() + 3.0
                                for name, component in components.items():
                                    status_fn = getattr(component, "status", None)
                                    release_fn = getattr(component, "release", None)
                                    try:
                                        before = status_fn() if callable(status_fn) else None
                                        if not isinstance(before, dict):
                                            raise RuntimeError("component status unavailable")
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
        mode_rejection = _http_mode_gate_error("POST", path, payload)
        if mode_rejection is not None:
            self._send(503, mode_rejection)
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
            for event in payload.get("events", []):
                try:
                    APP.telemetry.record_tool_accounting(event)
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
        if path == "/api/conversations/continue" or (
            path in {"/api/delegate", "/api/reason"} and bool(payload.get("conversation", False))
        ):
            self._redact_debug_trace()
        trace_store = getattr(APP, "debug_traces", None)
        api_trace_id = str(getattr(self, "_debug_trace_id", "") or "")
        if trace_store is not None and api_trace_id:
            try:
                if not getattr(self, "_debug_trace_redacted", False):
                    captured_request = self._safe_debug_trace_request(payload)
                    trace_store.update(api_trace_id, state="running", request=captured_request)
                    trace_store.event(
                        api_trace_id,
                        "request_body_captured",
                        {"content_type": content_type, "capture_status": captured_request.get("capture_status", "captured")},
                    )
                trace_store.event(api_trace_id, "handler_started", {"action": path, "payload_keys": sorted(str(key) for key in payload)})
            except Exception:
                # Debug persistence is optional and must not strand a claimed request.
                pass
        try:
            post_route_ids = select_http_routes("POST", path)
            post_handler_name = select_post_handler(post_route_ids)
            if post_handler_name is not None:
                getattr(self, post_handler_name)(payload)
                return
            if path == "/api/work-orders":
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
            if path == "/api/config/update":
                action = str(payload.get("action", "update")).strip().lower()
                config_path = str(APP.config.get("_config_path", ""))
                if not config_path:
                    self._send(500, {"success": False, "error": "active config path unavailable"}); return
                if action == "reset":
                    target = save_runtime_overrides(config_path, {}, reset=True)
                    self._send(200, {"success": True, "restart_required": True, "runtime_override_path": str(target), "reset": True}); return
                requested = payload.get("settings", {})
                if not isinstance(requested, dict):
                    self._send(400, {"success": False, "error": "settings must be an object"}); return
                allowed = {
                    "hardware.profile": {"auto", "cpu", "integrated", "low", "balanced", "high", "max"},
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
                    self._send(400, {"success": False, "error": str(exc)}); return
                self._send(200, {"success": True, "restart_required": True, "runtime_override_path": str(target), "settings": requested}); return
            if path == "/api/control":
                action = str(payload.get("action", "")).strip().lower().replace("-", "_")
                state_dir = Path(APP.config["server"]["state_dir"])
                if action == "restart_hub":
                    self._journal_finished = True; self._telemetry_finished = True
                    self._send(200, {"success": True, "action": action, "message": "hub restart requested"})
                    def _graceful_restart():
                        time.sleep(0.3)
                        try:
                            if APP is not None: APP.close()
                        except Exception: pass
                        os._exit(0)
                    threading.Thread(target=_graceful_restart, daemon=True).start(); return
                if action == "stop_service":
                    try: (state_dir / "service.disabled").write_text(f"disabled from dashboard {time.time()}\n", encoding="utf-8")
                    except OSError: pass
                    self._journal_finished = True; self._telemetry_finished = True
                    self._send(200, {"success": True, "action": action, "message": "service disabled; supervisor will stop"})
                    def _graceful_stop():
                        time.sleep(0.35)
                        try:
                            if APP is not None: APP.close()
                        except Exception: pass
                        os._exit(0)
                    threading.Thread(target=_graceful_stop, daemon=True).start(); return
                self._send(400, {"success": False, "error": "unknown control action"}); return
            if path == "/api/browser/capability":
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
            if path in {"/api/browser/capture/stage", "/api/browser/capture/commit", "/api/browser/capture/abandon"}:
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
            if path == "/api/browser/capture":
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
            if path == "/api/async-jobs":
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
            if path in {"/api/speculative-lint", "/api/command/speculative-lint"}:
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
            if path == "/api/agent-state/tasks":
                if not getattr(APP, "agent_tasks", None) or not APP.agent_tasks.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                action = str(payload.get("action", "")).strip().lower().replace("-", "_")
                idempotency_key = str(payload.get("idempotency_key", "")).strip()
                actor = self._agent() or "agent"
                if action == "create":
                    contract_data = payload.get("contract") or {}
                    if not contract_data:
                        goal = str(
                            payload.get("goal")
                            or payload.get("title")
                            or payload.get("description")
                            or payload.get("summary")
                            or payload.get("intent")
                            or payload.get("prompt")
                            or payload.get("value")
                            or payload.get("query")
                            or payload.get("task")
                            or (f"Task {payload.get('task_id')}" if payload.get("task_id") else "")
                            or ""
                        )
                        contract_data = {
                            "goal": goal,
                            "acceptance_criteria": payload.get("acceptance_criteria") or [],
                            "scope": payload.get("scope", "task"),
                            "non_goals": payload.get("non_goals") or [],
                            "constraints": payload.get("constraints") or [],
                            "risk_profile": payload.get("risk_profile", "normal"),
                        }
                    elif isinstance(contract_data, str):
                        contract_data = {
                            "goal": contract_data,
                            "acceptance_criteria": payload.get("acceptance_criteria") or [],
                            "scope": payload.get("scope", "task"),
                            "non_goals": payload.get("non_goals") or [],
                            "constraints": payload.get("constraints") or [],
                            "risk_profile": payload.get("risk_profile", "normal"),
                        }
                    elif isinstance(contract_data, Mapping) and not str(contract_data.get("goal", "")).strip():
                        contract_data = dict(contract_data)
                        contract_data["goal"] = str(
                            contract_data.get("description")
                            or contract_data.get("summary")
                            or contract_data.get("title")
                            or contract_data.get("intent")
                            or payload.get("goal")
                            or payload.get("title")
                            or payload.get("value")
                            or payload.get("query")
                            or payload.get("task")
                            or ""
                        ).strip()
                    contract = GoalContract.from_dict(contract_data) if isinstance(contract_data, Mapping) else GoalContract(goal=str(contract_data))
                    ctx_data = payload.get("context") or {}
                    context = ScopeContext(
                        repository_id=str(ctx_data.get("repository_id", "")),
                        clone_id=str(ctx_data.get("clone_id", "")),
                        worktree_id=str(ctx_data.get("worktree_id", "")),
                        branch=str(ctx_data.get("branch", "")),
                        task_id=str(ctx_data.get("task_id", "")),
                        session_id=str(ctx_data.get("session_id", "")),
                    )
                    task = APP.agent_tasks.create(
                        contract,
                        context,
                        task_id=str(payload.get("task_id", "") or ""),
                        actor=actor,
                        idempotency_key=idempotency_key,
                        auto_worktree=bool(payload.get("auto_worktree", False)),
                        repo_root=str(payload.get("repo_root", "")),
                    )
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
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except (KeyError, InvalidTransitionError, CompletionGateError) as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "complete":
                    try:
                        task_id = str(payload.get("task_id", ""))
                        task_state = APP.agent_tasks.get(task_id)
                        if task_state is None:
                            raise KeyError(f"Task {task_id} not found")
                        task_owner = str(task_state.owner or "").strip()
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
                            reason=str(payload.get("reason", payload.get("value", "completed by agent"))),
                            actor=actor,
                            idempotency_key=idempotency_key,
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except (KeyError, InvalidTransitionError, CompletionGateError) as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "fail":
                    try:
                        task = APP.agent_tasks.fail(
                            str(payload.get("task_id", "")),
                            reason=str(payload.get("reason", payload.get("value", payload.get("error", "failed by agent")))),
                            actor=actor,
                            idempotency_key=idempotency_key,
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except (KeyError, InvalidTransitionError, CompletionGateError) as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "checkpoint":
                    chk_data = payload.get("checkpoint") or {}
                    if not chk_data:
                        chk_data = {
                            "phase": str(payload.get("phase") or payload.get("value") or payload.get("status") or ""),
                            "next_action": str(payload.get("next_action") or payload.get("query") or ""),
                            "affected_paths": payload.get("affected_paths") or payload.get("paths") or [],
                            "evidence_ids": payload.get("evidence_ids") or [],
                            "blockers": payload.get("blockers") or [],
                            "state_data": payload.get("state_data") or {},
                        }
                    checkpoint = TaskCheckpoint.from_dict(chk_data)
                    try:
                        task = APP.agent_tasks.checkpoint(
                            str(payload.get("task_id", "")),
                            checkpoint,
                            actor=actor,
                            idempotency_key=idempotency_key,
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                    except CompletionGateError as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "rollback":
                    try:
                        task = APP.agent_tasks.rollback(
                            str(payload.get("task_id", "")),
                            actor=actor,
                            idempotency_key=idempotency_key,
                            reason=str(payload.get("reason", "manual rollback")),
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                    except Exception as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "resume":
                    try:
                        task = APP.agent_tasks.resume(
                            str(payload.get("task_id", "")),
                            actor=actor,
                            idempotency_key=idempotency_key,
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
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
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action in {"curate_dataset", "curate_training_dataset"}:
                    out_p = str(payload.get("output_path", payload.get("path", "training_dataset.jsonl")))
                    min_rcpt = int(payload.get("min_receipts", 1))
                    fmt = str(payload.get("format", "jsonl"))
                    try:
                        res = APP.agent_tasks.curate_training_dataset(out_p, min_receipts=min_rcpt, format=fmt)
                        self._send(200, res); return
                    except Exception as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action in {"cleanup_worktree", "task_cleanup_worktree"}:
                    t_id = str(payload.get("task_id", ""))
                    del_br = bool(payload.get("delete_branch", True))
                    self._send(200, APP.agent_tasks.cleanup_worktree(t_id, delete_branch=del_br, actor=self._agent())); return
                if action in {"reap_expired", "zombie_reap", "recover_zombie_tasks"}:
                    auto_rec = bool(payload.get("auto_recover", False))
                    reaped = APP.agent_tasks.reap_expired_heartbeats(auto_recover=auto_rec)
                    self._send(200, {"success": True, "reaped": reaped, "count": len(reaped)}); return
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
                    response = {"success": True, "tasks": [t.to_dict() for t in tasks]}
                    if getattr(tasks, "query_truncated", False):
                        response["query_truncated"] = True
                    self._send(200, response); return
                self._send(400, {"success": False, "error": f"unknown task action '{action}'", "terminal": True, "retryable": False}); return
            if path == "/api/agent-state/memory":
                if not getattr(APP, "agent_memory", None) or not APP.agent_memory.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                action = str(payload.get("action", "")).strip().lower().replace("-", "_")
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
                        explicit_tenant = self.headers.get("X-LocalAI-Tenant") or self.headers.get("X-Tenant-ID")
                        tenant_val = (
                            str(explicit_tenant).strip()
                            if explicit_tenant
                            else (payload.get("tenant") or rec_data.get("tenant") or (provenance.get("tenant") if isinstance(provenance, Mapping) else None))
                        )
                        if tenant_val:
                            tenant_val = str(tenant_val).strip() or None
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
                        scope_val = scope_val or AgentScope.TASK
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
                        if tenant_val:
                            provenance["tenant"] = tenant_val
                        if discarded_identity_fields:
                            provenance["discarded_identity_fields"] = discarded_identity_fields
                        for identity_key in (
                            "task_id", "session_id", "clone_id", "worktree_id", "branch",
                        ):
                            identity_value = payload.get(identity_key) or rec_data.get(identity_key)
                            if identity_value not in (None, ""):
                                provenance[identity_key] = str(identity_value)
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
                    requested_repository_id = payload.get("repository_id")
                    project_identity = self._memory_project_identity(requested_root)
                    if requested_root and project_identity is None:
                        self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
                    root_val = project_identity[0] if project_identity else None
                    repository_id_val = None
                    if requested_repository_id:
                        repository_id_val = project_identity[1] if project_identity and project_identity[1] else str(requested_repository_id).strip()
                    explicit_tenant = self.headers.get("X-LocalAI-Tenant") or self.headers.get("X-Tenant-ID")
                    tenant_val = str(explicit_tenant).strip() if explicit_tenant else payload.get("tenant")
                    if tenant_val:
                        tenant_val = str(tenant_val).strip() or None
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
                        self._send(400, {"success": False, "error": "ambiguous memory scope identity", "terminal": True, "retryable": False}); return
                    if scope_val is None:
                        scope_val = AgentScope.GLOBAL
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
                    requested_root = payload.get("root")
                    requested_repository_id = payload.get("repository_id")
                    project_identity = self._memory_project_identity(requested_root)
                    if requested_root and project_identity is None:
                        self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
                    root_val = project_identity[0] if project_identity else None
                    repository_id_val = None
                    if requested_repository_id:
                        repository_id_val = project_identity[1] if project_identity and project_identity[1] else str(requested_repository_id).strip()
                    requested_scope = _parse_memory_scope(payload.get("scope"))
                    explicit_tenant = self.headers.get("X-LocalAI-Tenant") or self.headers.get("X-Tenant-ID")
                    raw_tenant = str(explicit_tenant).strip() if explicit_tenant else payload.get("tenant")
                    tenant_val = None if requested_scope is AgentScope.GLOBAL else (str(raw_tenant).strip() if raw_tenant else None)
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
                        self._send(400, {"success": False, "error": "memory delete requires an explicit scope identity", "terminal": True, "retryable": False}); return
                    deleted = APP.agent_memory.delete(
                        record_id_val,
                        scope=scope_val,
                        scope_id=str(scope_id_val) if scope_id_val is not None else None,
                        root=str(root_val or "") or None,
                        repository_id=str(repository_id_val or "") or None,
                        tenant=str(tenant_val or "") or None,
                        task_id=str(payload.get("task_id") or "") or None,
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
                    requested_repository_id = payload.get("repository_id")
                    project_identity = self._memory_project_identity(requested_root)
                    if requested_root and project_identity is None:
                        self._send(400, {"success": False, "error": "memory project identity could not be resolved", "terminal": True, "retryable": False}); return
                    root_val = project_identity[0] if project_identity else None
                    repository_id_val = None
                    if requested_repository_id:
                        repository_id_val = project_identity[1] if project_identity and project_identity[1] else str(requested_repository_id).strip()
                    explicit_tenant = self.headers.get("X-LocalAI-Tenant") or self.headers.get("X-Tenant-ID")
                    tenant_val = str(explicit_tenant).strip() if explicit_tenant else payload.get("tenant")
                    if tenant_val:
                        tenant_val = str(tenant_val).strip() or None
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
                    legacy_unscoped = scope_val is None and not any(
                        str(value or "").strip()
                        for value in (
                            scope_id_val, task_id_val, session_id_val, clone_id_val, worktree_id_val,
                            branch_val, root_val, repository_id_val, tenant_val,
                        )
                    )
                    if legacy_unscoped:
                        records = APP.agent_memory.find(
                            scope=None,
                            allow_legacy_unscoped=True,
                            key=key_val,
                            query=query_val,
                            status=status_val,
                            limit=limit_val,
                        )
                    if not legacy_unscoped:
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
                if action == "promote":
                    target_scope_str = str(payload.get("target_scope", "")).strip().lower()
                    target_scope = AgentScope.parse(target_scope_str, default=None)
                    if not target_scope:
                        self._send(400, {"success": False, "error": f"invalid target scope '{target_scope_str}'", "terminal": True, "retryable": False}); return
                    # Request payloads and agent headers are not user approval.
                    # Only server-authenticated actor classification may authorize
                    # a global promotion; current HTTP auth modes deliberately do
                    # not identify a human approver, so they fail closed.
                    approver = str(getattr(self, "_authorization_actor", "unrecognized"))
                    try:
                        promoted = APP.agent_memory.promote(
                            str(payload.get("record_id", "")),
                            target_scope,
                            approver=approver,
                            root=str(payload.get("root") or "") or None,
                            repository_id=str(payload.get("repository_id") or "") or None,
                            tenant=self._tenant(),
                            task_id=str(payload.get("task_id") or "") or None,
                            session_id=str(payload.get("session_id") or "") or None,
                            clone_id=str(payload.get("clone_id") or "") or None,
                            worktree_id=str(payload.get("worktree_id") or "") or None,
                            branch=str(payload.get("branch") or "") or None,
                        )
                        self._send(200, {"success": True, "record": promoted.to_dict()}); return
                    except ApprovalRequiredError as exc:
                        self._send(403, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "quarantine":
                    reason = str(payload.get("reason", "manual quarantine"))
                    try:
                        APP.agent_memory.quarantine(
                            str(payload.get("record_id", "")),
                            reason=reason,
                            actor=actor,
                            root=str(payload.get("root") or "") or None,
                            repository_id=str(payload.get("repository_id") or "") or None,
                            tenant=self._tenant(),
                            task_id=str(payload.get("task_id") or "") or None,
                            session_id=str(payload.get("session_id") or "") or None,
                            clone_id=str(payload.get("clone_id") or "") or None,
                            worktree_id=str(payload.get("worktree_id") or "") or None,
                            branch=str(payload.get("branch") or "") or None,
                        )
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "compact":
                    scope_val = payload.get("scope")
                    older_than = float(payload.get("older_than_seconds", 0.0))
                    min_recs = int(payload.get("min_records", 3))
                    target_scope = payload.get("target_scope")
                    res = APP.agent_memory.compact(
                        scope=scope_val,
                        older_than_seconds=older_than,
                        min_records=min_recs,
                        target_scope=target_scope,
                        actor=actor,
                    )
                    self._send(200, res); return
                if action == "reap":
                    count = APP.agent_memory.reap_expired()
                    self._send(200, {"success": True, "reaped_count": count}); return
                if action in {"relation_record", "record_relation"}:
                    source = str(payload.get("source_entity", payload.get("source", payload.get("key", ""))))
                    rel = str(payload.get("relation", payload.get("rel", "relates_to")))
                    target = str(payload.get("target_entity", payload.get("target", payload.get("value", ""))))
                    weight = float(payload.get("weight", 1.0))
                    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None
                    rec = APP.agent_memory.record_relation(source, rel, target, weight=weight, metadata=meta)
                    self._send(200, {"success": True, "relation": rec}); return
                if action in {"relation_find", "find_relations"}:
                    ent = payload.get("entity") or payload.get("source_entity") or payload.get("source") or payload.get("target_entity") or payload.get("target") or payload.get("key") or ""
                    source = payload.get("source_entity") or payload.get("source")
                    target = payload.get("target_entity") or payload.get("target")
                    rel = payload.get("relation") or payload.get("rel")
                    limit_val = int(payload.get("limit", 50))
                    rels = APP.agent_memory.find_relations(
                        str(ent) if ent and not (source or target) else "",
                        source_entity=str(source) if source else None,
                        target_entity=str(target) if target else None,
                        relation=str(rel) if rel else None,
                        limit=limit_val,
                    )
                    self._send(200, {"success": True, "relations": rels}); return
                if action in {"relation_traverse", "traverse_graph"}:
                    start = str(payload.get("start_entity", payload.get("start", payload.get("entity", payload.get("source_entity", payload.get("key", ""))))))
                    depth = int(payload.get("max_depth", payload.get("depth", 2)))
                    max_n = int(payload.get("max_nodes", 50))
                    res = APP.agent_memory.traverse_graph(start, max_depth=depth, max_nodes=max_n)
                    self._send(200, res); return
                self._send(400, {"success": False, "error": f"unknown memory action '{action}'", "terminal": True, "retryable": False}); return

            if path == "/api/agent-state/incidents":
                if not getattr(APP, "agent_incidents", None) or not APP.agent_incidents.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                action = str(payload.get("action", "")).strip().lower().replace("-", "_")
                if action == "decision":
                    fp_data = payload.get("fingerprint") or {}
                    fp = IncidentFingerprint.from_dict(fp_data)
                    rev = str(payload.get("state_revision", payload.get("revision", "")))
                    dec = APP.agent_incidents.retry_decision(fp, rev)
                    self._send(200, {"success": True, "decision": dec.to_dict()}); return
                if action == "record":
                    inc_id = str(payload.get("incident_id", payload.get("id", payload.get("record_id", ""))))
                    root_cause = str(payload.get("root_cause", payload.get("reason", "")))
                    verified_fix = str(payload.get("verified_fix", payload.get("fix", payload.get("status", ""))))
                    if inc_id and (verified_fix or root_cause):
                        try:
                            inc = APP.agent_incidents.resolve(inc_id, verified_fix=verified_fix or "resolved", root_cause=root_cause or None)
                            self._send(200, {"success": True, "incident": inc.to_dict()}); return
                        except KeyError:
                            pass
                    msg = str(payload.get("message", payload.get("redacted_message", payload.get("value", ""))))
                    op = str(payload.get("operation_class", payload.get("tool_name", payload.get("key", "agent"))))
                    rev = str(payload.get("state_revision", payload.get("revision", "")))
                    evidence_ids = tuple(payload.get("evidence_ids") or ())
                    raw_paths = payload.get("affected_paths") or payload.get("paths") or []
                    aff_paths = tuple(str(p) for p in raw_paths) if isinstance(raw_paths, (list, tuple)) else ()
                    outcome = ToolOutcome(
                        tool_name=op, error=msg or "recorded incident", exit_code=int(payload.get("exit_code", 1)),
                        state_revision=rev, evidence_ids=evidence_ids,
                        metadata={"root_cause": root_cause, "verified_fix": verified_fix},
                        affected_paths=aff_paths,
                    )
                    inc = APP.agent_incidents.capture(outcome)
                    if inc and (verified_fix or root_cause):
                        inc = APP.agent_incidents.resolve(inc.incident_id, verified_fix=verified_fix or "resolved", root_cause=root_cause or None)
                    self._send(200, {"success": True, "incident": inc.to_dict() if inc else None}); return
                if action == "resolve":
                    inc_id = str(payload.get("incident_id", payload.get("id", payload.get("record_id", ""))))
                    fix = str(payload.get("verified_fix", payload.get("fix", payload.get("status", "manually resolved"))))
                    rc = str(payload.get("root_cause", payload.get("reason", ""))) or None
                    conf = float(payload.get("confidence", 1.0))
                    try:
                        inc = APP.agent_incidents.resolve(inc_id, verified_fix=fix, confidence=conf, root_cause=rc)
                        self._send(200, {"success": True, "incident": inc.to_dict()}); return
                    except KeyError:
                        self._send(404, {"success": False, "error": f"incident {inc_id} not found", "terminal": True, "retryable": False}); return
                if action in {"ignore", "unignore"}:
                    inc_id = str(payload.get("incident_id", payload.get("id", payload.get("record_id", ""))))
                    try:
                        inc = APP.agent_incidents.set_ignored(inc_id, ignored=action == "ignore")
                        self._send(200, {"success": True, "incident": inc.to_dict()}); return
                    except KeyError:
                        self._send(404, {"success": False, "error": f"incident {inc_id} not found", "terminal": True, "retryable": False}); return
                if action == "find_regressions":
                    paths_param = payload.get("paths") or ([payload.get("path")] if payload.get("path") else [])
                    p_list = [str(x) for x in paths_param] if isinstance(paths_param, list) else []
                    regressions = APP.agent_incidents.find_regressions(p_list)
                    self._send(200, {"success": True, "regressions": regressions}); return
                if action == "find":
                    query_str = str(payload.get("query", payload.get("key", ""))).strip().lower()
                    resolved_filter = payload.get("resolved")
                    status_filter = str(payload.get("status", "") or "")
                    limit_val = int(payload.get("limit", 100))
                    all_incs = APP.agent_incidents.list_incidents(resolved=resolved_filter, limit=limit_val * 2, status=status_filter)
                    if query_str:
                        matched = [
                            i for i in all_incs
                            if query_str in i.error_class.lower() or query_str in i.redacted_message.lower() or (i.root_cause and query_str in i.root_cause.lower()) or (i.verified_fix and query_str in i.verified_fix.lower())
                        ][:limit_val]
                    else:
                        matched = all_incs[:limit_val]
                    self._send(200, {"success": True, "incidents": [i.to_dict() for i in matched]}); return
                if action == "list":
                    resolved_filter = payload.get("resolved")
                    status_filter = str(payload.get("status", "") or "")
                    limit_val = int(payload.get("limit", 100))
                    incidents = APP.agent_incidents.list_incidents(resolved=resolved_filter, limit=limit_val, status=status_filter)
                    self._send(200, {"success": True, "incidents": [i.to_dict() for i in incidents]}); return
                self._send(400, {"success": False, "error": f"unknown incident action '{action}'", "terminal": True, "retryable": False}); return
            if path == "/api/agent-state/verification":
                if not getattr(APP, "agent_verification", None) or not APP.agent_verification.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                action = str(payload.get("action", "")).strip().lower().replace("-", "_")
                if action == "receipt":
                    rcpt_data = payload.get("receipt") or {}
                    try:
                        if "receipt_id" in rcpt_data:
                            rcpt = VerificationReceipt.from_dict(rcpt_data)
                        else:
                            rcpt = VerificationReceipt.create(
                                task_id=str(rcpt_data.get("task_id", "")),
                                criterion=str(rcpt_data.get("criterion", "")),
                                passed=bool(rcpt_data.get("passed", True)),
                                change_intent_id=str(rcpt_data.get("change_intent_id", "")),
                                evidence_id=str(rcpt_data.get("evidence_id", "")),
                                command_id=str(rcpt_data.get("command_id", "")),
                                repository_revision=str(rcpt_data.get("repository_revision", "")),
                                expires_at=rcpt_data.get("expires_at"),
                                details=rcpt_data.get("details"),
                            )
                        saved = APP.agent_verification.record(rcpt)
                        self._send(200, {"success": True, "receipt": saved.to_dict()}); return
                    except Exception as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "completion":
                    task_id = str(payload.get("task_id", "")).strip()
                    current_revision = ""
                    root = str(payload.get("root", "")).strip()
                    requested_revision = str(payload.get("repository_revision", "")).strip()
                    repo_tools = getattr(APP, "repo_tools", None)
                    if root or requested_revision:
                        current_revision, revision_stop = _completion_revision_or_stop(
                            root, repo_tools, getattr(APP, "repo_state", None)
                        )
                        if revision_stop:
                            self._send(409, revision_stop); return
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
                self._send(400, {"success": False, "error": f"unknown verification action '{action}'", "terminal": True, "retryable": False}); return
            if path == "/api/agent-state/context":
                if not getattr(APP, "agent_context", None) or not APP.agent_context.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                action = str(payload.get("action", "")).strip().lower().replace("-", "_")
                if action == "compile":
                    req = build_context_request(payload, tenant=tenant)
                    if not req.task_id:
                        self._send(400, {
                            "success": False,
                            "error": "task_id is required for context compilation",
                            "terminal": True,
                            "retryable": False,
                        }); return
                    compiled = APP.agent_context.compile(req)
                    since_hash = str(payload.get("since_hash") or payload.get("etag") or "").strip()
                    compact_mode = bool(payload.get("compact", False))
                    root = req.root.strip()
                    if root:
                        from .agent_consistency import ConsistencyRequest

                        # A task context request often carries its intent only in
                        # focus. Feed that intent into repository retrieval instead
                        # of silently running an empty fast search. Focused task
                        # context gets the complete deterministic-first pack; callers
                        # can still force the bounded fast mode explicitly.
                        repository_query = str(payload.get("query", "")).strip()
                        if not repository_query:
                            repository_query = " ".join(req.focus[:8])
                        requested_mode = str(payload.get("mode", "")).strip().lower()
                        repository_mode = requested_mode if requested_mode in {"fast", "full"} else (
                            "full" if (repository_query or req.focus or req.changed_paths) else "fast"
                        )

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
            if path == "/api/agent-state/learning":
                if not getattr(APP, "agent_learning", None) or not APP.agent_learning.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                action = str(payload.get("action", "")).strip().lower().replace("-", "_")
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
            if path == "/api/agent-state/cleanup":
                if not getattr(APP, "agent_state", None) or not APP.agent_state.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                retention = int(payload.get("retention_days") or APP.config.get("agent_state", {}).get("retention_days", 30))
                res = APP.agent_state.cleanup(retention_days=retention)
                self._send(200, res); return
            if path == "/api/agent-state/blackboard":
                if not getattr(APP, "agent_blackboard", None):
                    self._send(503, {"success": False, "error": "blackboard unavailable"}); return
                action = str(payload.get("action", "get")).strip().lower().replace("-", "_")
                board_id = str(payload.get("board_id", payload.get("task_id", payload.get("key", "default"))))
                if action in {"update", "put", "blackboard_update"}:
                    section = str(payload.get("section", payload.get("key", "main")))
                    content = payload.get("content", payload.get("value"))
                    author = str(payload.get("author", payload.get("approver", tenant or "agent")))
                    clock = payload.get("clock")
                    exp_v = payload.get("expected_version")
                    exp_v_int = int(exp_v) if exp_v is not None else None
                    res = APP.agent_blackboard.update(board_id, section, content, author, clock=clock, expected_version=exp_v_int)
                    self._send(200, res); return
                if action in {"get", "read", "blackboard_get"}:
                    section = payload.get("section")
                    res = APP.agent_blackboard.get(board_id, section=str(section) if section else None)
                    self._send(200, res); return
                if action in {"list", "blackboard_list"}:
                    boards = APP.agent_blackboard.list_boards()
                    self._send(200, {"success": True, "boards": boards, "count": len(boards)}); return
                if action in {"merge", "blackboard_merge"}:
                    remote = payload.get("remote_sections", payload.get("sections", payload.get("record", {})))
                    res = APP.agent_blackboard.merge(board_id, remote)
                    self._send(200, res); return
                if action in {"delete", "remove", "blackboard_delete"}:
                    section = payload.get("section")
                    res = APP.agent_blackboard.delete(board_id, section=str(section) if section else None)
                    self._send(200, res); return
                self._send(400, {"success": False, "error": f"unknown blackboard action '{action}'"}); return
            if path == "/api/agent-state/swarm/dispatch":
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
            if path == "/api/agent-state/swarm/step":
                if not getattr(APP, "swarm", None):
                    self._send(503, {"success": False, "error": "swarm coordinator unavailable"}); return
                swarm_id = str(payload.get("swarm_id", payload.get("task_id", "")))
                role = str(payload.get("role", "Coder"))
                action = str(payload.get("action", "submit_patch"))
                step_payload = payload.get("payload", payload.get("content", {}))
                res = APP.swarm.step(swarm_id=swarm_id, role=role, action=action, payload=step_payload)
                self._send(200, res); return
            if path == "/api/agent-state/swarm/cancel":
                if not getattr(APP, "swarm", None):
                    self._send(503, {"success": False, "error": "swarm coordinator unavailable"}); return
                swarm_id = str(payload.get("swarm_id", payload.get("task_id", "")))
                reason = str(payload.get("reason", ""))
                res = APP.swarm.cancel(swarm_id=swarm_id, reason=reason)
                self._send(200, res); return
            if path == "/api/benchmark/run":
                if not getattr(APP, "benchmark_runner", None):
                    self._send(503, {"success": False, "error": "benchmark runner unavailable"}); return
                model = str(payload.get("model", ""))
                prompt = str(payload.get("prompt", payload.get("task", "")))
                num_tokens = int(payload.get("num_tokens", payload.get("max_tokens", 40)))
                res = APP.benchmark_runner.run(model=model, prompt=prompt or "def test(): pass\n", num_tokens=num_tokens)
                self._send(200, res); return
            if path == "/api/delegate/repo":
                self._send(200, APP.services.delegate_repo(payload, tenant)); return
            if path == "/api/solve/repo":
                self._send(200, APP.services.solve_repo(payload, tenant)); return
            if path == "/api/route":
                self._send(200, APP.services.route_context(payload, tenant)); return
            if path == "/api/delegate/batch":
                self._send(200, APP.services.batch_delegate(payload, tenant)); return
            if path == "/api/review":
                self._send(200, APP.services.review(payload, tenant)); return
            if path == "/api/review/diff":
                self._send(200, APP.services.review_diff(payload, tenant)); return
            if path == "/api/reason":
                self._send(200, APP.services.reason(payload, tenant)); return
            if path == "/api/second-opinion":
                self._send(200, APP.services.second_opinion(payload, tenant)); return
            if path == "/api/compress":
                self._send(200, APP.services.compress(payload, tenant)); return
            if path == "/api/generate_tests":
                self._send(200, APP.services.generate_tests(payload, tenant))
                return
            if path == "/api/patch/validate":
                self._send(200, APP.services.validate_patch(payload, tenant))
                return
            if path == "/api/query/expand":
                q = str(payload.get("query", ""))
                self._send(200, {"success": True, "query": q, "expanded_terms": APP.services.expand_query(q, tenant)})
                return
            if path == "/api/audit_dependencies":
                root = str(payload.get("root", "."))
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.audit_dependencies(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/refactor_impact":
                root = str(payload.get("root", "."))
                file_param = str(payload.get("file", payload.get("path", "")))
                symbol_param = payload.get("symbol")
                if APP.deterministic is not None:
                    self._send(200, APP.services.refactor_impact(root, file_param, symbol_param))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/resolve_imports":
                root = str(payload.get("root", "."))
                lang = str(payload.get("language", "auto"))
                syms = payload.get("symbols", [payload.get("symbol")] if payload.get("symbol") else [])
                if APP.deterministic is not None:
                    self._send(200, APP.services.resolve_imports(root, syms, lang))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/git/status":
                root = str(payload.get("root", "."))
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.git_status(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/repo/state", "/api/repo_state"}:
                root = str(payload.get("root", "."))
                tracker = getattr(APP, "repo_state", None) or (getattr(APP.services, "repo_state", None) if getattr(APP, "services", None) else None)
                if tracker is not None:
                    try:
                        self._send(200, tracker.fingerprint(root))
                    except Exception as exc:
                        self._send(200, {"success": False, "error": str(exc)})
                else:
                    self._send(200, {"success": False, "error": "repo_state tracker unavailable"})
                return
            if path == "/api/git/diff":
                root = str(payload.get("root", "."))
                p = payload.get("path")
                staged = bool(payload.get("staged", False))
                max_lines = int(payload.get("max_lines", 1000))
                if APP.deterministic is not None:
                    self._send(200, APP.services.git_diff(root, path=p, staged=staged, max_lines=max_lines))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/git/history_search":
                root = str(payload.get("root", "."))
                q = str(payload.get("query", ""))
                max_c = int(payload.get("max_commits", 20))
                if APP.deterministic is not None:
                    self._send(200, APP.services.git_history_search(root, q, max_commits=max_c))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/repo/hotspots", "/api/hotspots"}:
                root = str(payload.get("root", "."))
                days = int(payload.get("days", 30))
                limit = int(payload.get("limit", 20))
                if APP.deterministic is not None:
                    self._send(200, APP.services.find_hotspots(root, days=days, limit=limit))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/repo/generate_tests_for_diff", "/api/generate_tests_for_diff"}:
                root = str(payload.get("root", "."))
                diff = payload.get("diff")
                p = payload.get("path")
                if APP.deterministic is not None:
                    self._send(200, APP.services.generate_tests_for_diff(root, diff=diff, path=p))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/repo/cross_repo_contract", "/api/cross_repo_contract"}:
                b_root = str(payload.get("backend_root", payload.get("root", ".")))
                f_root = str(payload.get("frontend_root", payload.get("client_root", ".")))
                if APP.deterministic is not None:
                    self._send(200, APP.services.cross_repo_contract(b_root, f_root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/git/synthesize_commit":
                root = str(payload.get("root", "."))
                hint = str(payload.get("hint", payload.get("message", "")))
                task_id = str(payload.get("task_id", ""))
                if APP.deterministic is not None:
                    self._send(200, APP.services.synthesize_commit(root, hint, task_id=task_id))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/test_matrix":
                root = str(payload.get("root", "."))
                if APP.deterministic is not None:
                    self._send(200, APP.services.test_matrix(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/repo/affected_tests", "/api/affected_tests"}:
                root = str(payload.get("root", "."))
                paths = payload.get("paths") or payload.get("changed_paths") or None
                if APP.deterministic is not None:
                    self._send(200, APP.services.affected_tests(root, changed_paths=paths))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/repo/topology", "/api/topology"}:
                root = str(payload.get("root", "."))
                if APP.deterministic is not None:
                    self._send(200, APP.services.repo_topology(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/code/ast_rename", "/api/ast_rename"}:
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
            if path in {"/api/code/generate_mocks", "/api/generate_mocks"}:
                root = str(payload.get("root", "."))
                target_file = str(payload.get("file", payload.get("path", "")))
                symbol = str(payload.get("symbol", ""))
                if APP.deterministic is not None:
                    self._send(200, APP.services.generate_mocks(root, target_file, symbol))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/security_audit":
                root = str(payload.get("root", "."))
                limit = int(payload.get("limit", 50))
                if APP.deterministic is not None:
                    self._send(200, APP.services.security_audit(root, limit))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/code-intelligence/query":
                root = str(payload.get("root", "."))
                self._send(200, APP.external_tools.query(
                    root, str(payload.get("query", "")),
                    backend=str(payload.get("backend", "auto")),
                    action=str(payload.get("action", "search")),
                    path=str(payload.get("path", "")),
                    limit=max(1, min(int(payload.get("limit", 20)), 50)),
                ))
                return
            if path == "/api/code/ast_outline":
                root = str(payload.get("root", "."))
                path_param = str(payload.get("path", payload.get("file", "")))
                if APP.deterministic is not None:
                    self._send(200, APP.services.ast_outline(root, path_param))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path in {"/api/code/batch_replace", "/api/repo/batch_replace"}:
                root = str(payload.get("root", "."))
                edits = payload.get("edits") or payload.get("replacements") or []
                dry_run = bool(payload.get("dry_run", False))
                self._send(200, APP.services.batch_replace(root, edits if isinstance(edits, list) else [], dry_run=dry_run))
                return
            if path == "/api/maintenance/optimize_db":
                self._send(200, APP.services.optimize_databases())
                return
            if path == "/api/maintenance/purge_cache":
                days = int(payload.get("days", 7))
                self._send(200, APP.services.purge_stale_cache(days))
                return
            if path == "/api/maintenance/resolve_errors":
                self._send(200, APP.services.resolve_all_errors())
                return
            if path == "/api/doctor":
                self._send(200, APP.services.run_doctor())
                return
            if path == "/api/code/symbol":
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol", ""))
                self._send(200, APP.services.code_inspect_symbol(root, sym))
                return
            if path == "/api/code/find_symbol":
                root = str(payload.get("root", "."))
                pat = str(payload.get("pattern") or payload.get("name_path_pattern") or "")
                depth = int(payload.get("depth", 0))
                include_body = bool(payload.get("include_body", False))
                include_info = bool(payload.get("include_info", True))
                rel_path = payload.get("path") or payload.get("relative_path")
                limit = int(payload.get("limit", 30))
                self._send(200, APP.services.code_find_symbol(root, pat, depth=depth, include_body=include_body, include_info=include_info, relative_path=str(rel_path) if rel_path else None, limit=limit))
                return
            if path == "/api/code/find_declaration":
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol") or payload.get("name") or "")
                rel_path = payload.get("path")
                self._send(200, APP.services.code_find_declaration(root, sym, path=str(rel_path) if rel_path else None))
                return
            if path == "/api/code/find_implementations":
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol") or payload.get("name") or "")
                rel_path = payload.get("path")
                self._send(200, APP.services.code_find_implementations(root, sym, path=str(rel_path) if rel_path else None))
                return
            if path == "/api/code/find_referencing_symbols":
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol") or payload.get("name") or "")
                rel_path = payload.get("path")
                self._send(200, APP.services.code_find_referencing_symbols(root, sym, path=str(rel_path) if rel_path else None))
                return
            if path == "/api/code/symbols_overview":
                root = str(payload.get("root", "."))
                fpath = str(payload.get("path", ""))
                depth = int(payload.get("depth", 1))
                self._send(200, APP.services.code_symbols_overview(root, fpath, depth=depth))
                return
            if path == "/api/code/diagnostics":
                root = str(payload.get("root", "."))
                fpath = str(payload.get("path", ""))
                self._send(200, APP.services.code_diagnostics(root, fpath))
                return
            if path == "/api/code-intelligence/control":
                action = str(payload.get("action", "status")).strip().lower().replace("-", "_")
                if action == "status":
                    self._send(200, {"success": True, **APP.external_tools.status()}); return
                if action in {"rediscover", "refresh"}:
                    self._send(200, APP.external_tools.rediscover()); return
                if action in {"reset", "reset_sessions"}:
                    self._send(200, APP.external_tools.reset_sessions(str(payload.get("backend", "all")), str(payload.get("root")) if payload.get("root") else None)); return
                self._send(400, {"success": False, "error": f"unknown code-intelligence action: {action}"}); return
            if path == "/api/complete":
                # FIM completion routed through APP.services with caching / APP.scheduler.submit
                self._send(200, APP.services.complete_code(payload, tenant)); return
            if path == "/api/preprocess":
                self._send(200, APP.services.preprocess(payload)); return
            if path in {"/api/repo/dead_code", "/api/dead_code"}:
                root = str(payload.get("root", "."))
                limit = int(payload.get("limit", 50))
                self._send(200, APP.services.dead_code(root, limit))
                return
            if path == "/api/symbol_callgraph":
                root = str(payload.get("root", "."))
                sym = payload.get("symbol")
                limit = int(payload.get("limit", 50))
                self._send(200, APP.services.symbol_callgraph(root, str(sym) if sym else None, limit))
                return
            if path == "/api/cross_project_graph":
                roots = payload.get("roots")
                if not isinstance(roots, list) or not roots:
                    roots = [str(p.get("root")) for p in APP.preprocessor.status().get("projects", []) if p.get("root")]
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.cross_project_graph([str(r) for r in roots]))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/cross_project_symbols":
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
            if path == "/api/cross_project_impact":
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
            if path == "/api/repo/call_graph_diff":
                root = str(payload.get("root", "."))
                diff = payload.get("diff")
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.call_graph_diff(root, diff=diff))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/api/bundle/export":
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
                        self._send(500, {"success": False, "error": str(exc)})
                return
            if path == "/api/benchmark":
                self._send(200, APP.services.benchmark(tenant)); return
            if path == "/api/evaluation":
                self._send(200, APP.services.evaluation(payload)); return
            if path == "/api/repo/profile":
                self._send(200, APP.services.repo_profile(str(payload.get("root", ".")))); return
            if path == "/api/repo/map":
                self._send(200, APP.services.repo_map(str(payload.get("root", ".")), int(payload.get("max_symbols", 120)))); return
            if path == "/api/repo/code-index":
                self._send(200, APP.services.code_query(str(payload.get("root", ".")), str(payload.get("query", "")), int(payload.get("limit", 20)), bool(payload.get("include_code", False)))); return
            if path == "/api/repo/investigate":
                self._send(200, APP.services.repo_investigate(
                    str(payload.get("root", ".")),
                    str(payload.get("query", "")),
                    str(payload.get("path", "")),
                    bool(payload.get("include_code", True)),
                    int(payload.get("limit", 10)),
                )); return
            if path == "/api/repo/diagnose":
                self._send(200, APP.services.repo_diagnose(
                    str(payload.get("root", ".")),
                    str(payload.get("text", payload.get("query", ""))),
                )); return
            if path == "/api/repo/briefing":
                self._send(200, APP.services.repo_briefing(str(payload.get("root", ".")))); return
            if path == "/api/command/preflight":
                raw_paths = payload.get("paths") or payload.get("files")
                paths_list = [str(p) for p in raw_paths] if isinstance(raw_paths, list) else ([str(raw_paths)] if raw_paths else None)
                self._send(200, APP.services.commands.preflight(
                    str(payload.get("cwd", payload.get("root", "."))),
                    str(payload.get("tenant", "default")),
                    paths=paths_list,
                    timeout=int(payload.get("timeout", 10) or 10),
                )); return
            if path == "/api/repo/deterministic":
                self._send(200, APP.services.deterministic_query(str(payload.get("root", ".")), str(payload.get("query", "")), int(payload.get("limit", 24)))); return
            if path == "/api/repo/impact":
                self._send(200, APP.services.repo_impact(
                    str(payload.get("root", ".")), str(payload.get("base", "HEAD")), bool(payload.get("staged", False)),
                    int(payload.get("max_symbols", APP.config.get("workflow", {}).get("impact_max_symbols", 48))),
                    int(payload.get("max_dependents", APP.config.get("workflow", {}).get("impact_max_dependents", 30))),
                )); return
            if path == "/api/search":
                self._send(200, APP.services.repo_search(
                    str(payload.get("root", ".")),
                    str(payload.get("query", "")),
                    int(payload.get("top_k", 12)),
                    context_lines=int(payload["context_lines"]) if payload.get("context_lines") is not None else None,
                    enrich=bool(payload.get("enrich", False)),
                    path_hints=payload.get("path_hints"),
                )); return
            if path == "/api/context/pack":
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
                mode = str(payload.get("mode", "adaptive")).strip().lower()
                if mode not in {"full", "fast", "adaptive"}:
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
                    if mode != "adaptive":
                        self._send(400, {
                            "success": False, "terminal": True, "retryable": False,
                            "error": "path controls require adaptive context mode",
                        }); return
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
                guarded = payload.get("guarded", False)
                if not isinstance(guarded, bool):
                    self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "guarded must be boolean"}); return
                guarded_requested = (
                    bool(guarded) or bool(str(payload.get("task_id", "")).strip())
                    or bool(str(payload.get("phase", "")).strip())
                    or bool(str(payload.get("session_id", "")).strip())
                    or any(bool(str(payload.get(field, "")).strip()) for field in (
                        "clone_id", "worktree_id", "branch", "repository_id", "repository_revision",
                    ))
                    or bool(payload.get("include_diagnostics", False))
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
                    if repository_failed and not (guarded_requested and has_task_id):
                        status_code = 503 if result.get("retryable") is True else 500
                        self._send(status_code, result); return
                    if guarded_requested and has_task_id and not getattr(APP, "agent_context", None):
                        self._send(503, {
                            "success": False, "terminal": False, "retryable": True,
                            "stop_code": "context_task_context_unavailable",
                            "error": "task context compiler unavailable",
                        }); return
                    if guarded_requested and has_task_id and getattr(APP, "agent_context", None):
                        task_request = build_context_request({
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
                            "clone_id": payload.get("clone_id", ""),
                            "worktree_id": payload.get("worktree_id", ""),
                            "branch": payload.get("branch", ""),
                            "repository_id": payload.get("repository_id", ""),
                            "include_diagnostics": payload.get("include_diagnostics", False),
                        }, tenant=tenant, identity=self._agent())
                        try:
                            compiled = APP.agent_context.compile(task_request)
                            unified = compose_task_context(
                                task_id=task_request.task_id,
                                compiled=compiled,
                                repository=result if isinstance(result, dict) else {"success": False, "error": "repository context response must be an object"},
                                token_budget=task_request.token_budget,
                            )
                        except Exception as exc:
                            self._send(503, {
                                "success": False, "terminal": False, "retryable": True,
                                "stop_code": "context_task_context_unavailable",
                                "error": f"task context receipt unavailable: {type(exc).__name__}",
                            }); return
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
                            self._send(503, {
                                "success": False, "terminal": True, "retryable": False,
                                "stop_code": "context_task_context_incomplete",
                                "error": "task context receipt is missing, stale, or incomplete",
                                "task_context": unified if isinstance(unified, dict) else {},
                            }); return
                        if isinstance(result, dict):
                            result["task_context"] = unified
                            result["task_context_id"] = unified["context_id"]
                    self._send(200, result); return
                if mode == "fast":
                    result = APP.services.fast_context(root, query_text, max_tokens)
                else:
                    result = APP.services._hybrid_context(
                        root, query_text, tenant, payload.get("workspace"), max_tokens,
                        quality_first=mode == "adaptive",
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
            if path == "/api/artifact/get":
                artifact_id = str(payload.get("artifact_id", ""))
                if bool(payload.get("binary", False)):
                    self._send(200, APP.artifacts.get_binary(artifact_id, tenant=tenant)); return
                self._send(200, APP.artifacts.get(artifact_id, int(payload.get("offset", 0)), int(payload.get("max_chars", 6000)), str(payload.get("section", "")), tenant=tenant)); return
            if path == "/api/artifact/list":
                self._send(200, {"success": True, "artifacts": APP.artifacts.list(tenant=tenant, limit=int(payload.get("limit", 20)))}); return
            if path == "/api/evidence/verify":
                evidence = payload.get("evidence", [])
                self._send(200, APP.repo_tools.verify_evidence(str(payload.get("root", ".")), evidence if isinstance(evidence, list) else [])); return
            if path == "/api/evidence/get":
                self._send(200, APP.evidence.get(str(payload.get("evidence_id", "")), verify=bool(payload.get("verify", True)))); return
            if path in ("/api/leases/claim", "/api/leases/claim_batch"):
                paths = payload.get("paths", [])
                root = str(payload.get("root", "."))
                coordination_id = _lease_coordination_id(root)
                self._send(200, APP.leases.claim_batch(tenant, root, [str(x) for x in paths] if isinstance(paths, list) else [], int(payload.get("ttl_seconds", 900)), str(payload.get("purpose", "agent edit")), coordination_id=coordination_id)); return
            if path == "/api/leases/release":
                self._send(200, APP.leases.release(tenant, str(payload.get("lease_id", "")))); return
            if path == "/api/leases/renew":
                self._send(200, APP.leases.renew(tenant, str(payload.get("lease_id", "")), int(payload.get("ttl_seconds", 900)))); return
            if path == "/api/memory/put":
                self._send(200, APP.memory.put(
                    str(payload.get("root", ".")), str(payload.get("key", "")), str(payload.get("value", "")), tenant,
                    ttl_seconds=payload.get("ttl_seconds"), metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
                    expected_version=payload.get("expected_version"),
                )); return
            if path == "/api/memory/get":
                self._send(200, APP.memory.get(str(payload.get("root", ".")), str(payload.get("key", "")))); return
            if path == "/api/memory/search":
                self._send(200, APP.memory.search(str(payload.get("root", ".")), str(payload.get("query", "")), int(payload.get("limit", 12)))); return
            if path == "/api/memory/delete":
                self._send(200, APP.memory.delete(str(payload.get("root", ".")), str(payload.get("key", "")), tenant)); return
            if path == "/api/command":
                result = APP.services.command(payload, tenant)
                status = 409 if isinstance(result, dict) and result.get("outcome_unknown") is True else 200
                self._send(status, result); return
            if path == "/api/embed":
                texts = payload.get("texts", payload.get("input", []))
                if isinstance(texts, str):
                    texts = [texts]
                self._send(200, APP.services.embed([str(x) for x in texts], tenant, query=bool(payload.get("query", False)))); return
            if path == "/api/rerank":
                docs = payload.get("documents", [])
                self._send(200, APP.reranker.rerank(str(payload.get("query", "")), [str(x) for x in docs], payload.get("top_k"))); return
            if path == "/api/rag/index":
                self._send(200, APP.rag.index(str(payload.get("root", ".")), tenant, payload.get("workspace"))); return
            if path == "/api/rag/search":
                workspace = str(payload.get("workspace", ""))
                if not workspace:
                    self._send(400, {"success": False, "error": "workspace is required"}); return
                self._send(200, APP.rag.search(str(payload.get("query", "")), tenant, workspace, int(payload.get("top_k", 8)), bool(payload.get("use_reranker", True)))); return
            if path in {"/api/task/speculative_draft", "/api/speculative_draft"}:
                self._send(200, APP.services.speculative_draft(payload, tenant)); return
            if path in {"/api/task/scaffold", "/api/scaffold"}:
                self._send(200, APP.services.task_scaffold(payload, tenant)); return
            if path in {"/api/db/query"}:
                db_name = str(payload.get("db", "agent_state"))
                sql_q = str(payload.get("query", "SELECT name FROM sqlite_master WHERE type='table'"))
                self._send(200, self._handle_db_query(db_name, sql_q)); return
            if path in {"/api/models/manage"}:
                action = str(payload.get("action", "list"))
                model_name = str(payload.get("model", ""))
                self._send(200, self._handle_models_action(action, model_name)); return
            if path in {"/api/repo/reachability_dead_code", "/api/reachability_dead_code"}:
                root = str(payload.get("root", "."))
                eps = payload.get("entrypoints")
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.reachability_dead_code(root, entrypoints=eps)); return
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"}); return
            if path in {"/api/repo/mutation_test", "/api/mutation_test"}:
                root = str(payload.get("root", "."))
                tf = str(payload.get("file", payload.get("path", "")))
                diff = payload.get("diff")
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.ast_mutation_test(root, tf, diff=diff)); return
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"}); return
            if path in {"/api/repo/type_stubs", "/api/type_stubs"}:
                root = str(payload.get("root", "."))
                fp = str(payload.get("file", payload.get("path", "")))
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.generate_type_stubs(root, fp)); return
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"}); return
            if path in {"/api/repo/skeletonize", "/api/skeletonize"}:
                code = str(payload.get("code", ""))
                targets = payload.get("targets") or payload.get("target_symbols")
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.skeletonize_code(code, target_symbols=targets)); return
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"}); return
            if path == "/api/agent-state/events/delta":
                action = str(payload.get("action", "export"))
                if action == "export":
                    stream_id = str(payload.get("stream_id", ""))
                    after_seq = int(payload.get("after_seq", 0))
                    limit = int(payload.get("limit", 1000))
                    self._send(200, APP.agent_state_store.export_delta(stream_id, after_seq, limit)); return
                else:
                    events = list(payload.get("events", []))
                    self._send(200, APP.agent_state_store.import_delta(events)); return
            if path in {"/api/task/vision", "/api/vision", "/api/vision/review"}:
                self._send(200, APP.services.vision(payload, tenant)); return
            if path in {"/api/repo/split_changes", "/api/split_changes"}:
                root = str(payload.get("root", "."))
                paths = payload.get("paths", payload.get("changed_files"))
                self._send(200, APP.services.split_changes(root, paths)); return
            if path in {"/api/repo/synthesize_rules", "/api/synthesize_rules"}:
                root = str(payload.get("root", "."))
                limit = int(payload.get("limit", 10))
                self._send(200, APP.services.synthesize_rules(root, limit)); return
            if path in {"/api/rag/docset/index", "/api/rag/docset_index"}:
                name = str(payload.get("name", payload.get("docset", "")))
                root = str(payload.get("root", payload.get("dir", ".")))
                self._send(200, APP.rag.docset_index(name, root, tenant)); return
            if path in {"/api/rag/docset/search", "/api/rag/docset_search"}:
                name = str(payload.get("name", payload.get("docset", "")))
                query = str(payload.get("query", ""))
                top_k = int(payload.get("top_k", 8))
                self._send(200, APP.rag.docset_search(name, query, tenant, top_k=top_k)); return
            if path in {"/api/task/transcribe", "/api/transcribe"}:
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
            if path in {"/api/repo/generate_dataset", "/api/generate_dataset"}:
                self._send(200, APP.services.generate_dataset(str(payload.get("root", ".")), payload.get("schema_or_model") or payload.get("schema"), count=int(payload.get("count", 10)), format=str(payload.get("format", "json")))); return
            if path in {"/api/repo/profile_digest", "/api/profile_digest"}:
                self._send(200, APP.services.profile_digest(str(payload.get("profile_path") or payload.get("path") or ""), top_n=int(payload.get("top_n", 15)))); return
            if path in {"/api/coord/worktree_lease", "/api/worktree_lease"}:
                self._send(200, APP.services.worktree_lease(str(payload.get("root", ".")), branch_name=payload.get("branch"))); return
            if path in {"/api/coord/worktree_release", "/api/worktree_release"}:
                self._send(200, APP.services.worktree_release(str(payload.get("root", ".")), str(payload.get("worktree_path", "")), delete_branch=bool(payload.get("delete_branch", True)), branch_name=payload.get("branch"))); return
            if path in {"/api/coord/worktrees", "/api/worktrees"}:
                self._send(200, APP.services.list_worktrees(str(payload.get("root", ".")))); return
            if path in {"/api/coord/worktree_prune", "/api/worktree_prune"}:
                self._send(200, APP.services.prune_worktrees(str(payload.get("root", ".")))); return

            if path in {"/api/command/daemon", "/api/daemon"}:
                act = str(payload.get("action", "status")).lower()
                if act == "spawn":
                    self._send(200, APP.services.spawn_daemon(str(payload.get("command", "")), str(payload.get("cwd", ".")), name=str(payload.get("name", "")), env=payload.get("env"))); return
                elif act == "stop":
                    self._send(200, APP.services.stop_daemon(str(payload.get("daemon_id", "")), task_id=str(payload.get("task_id", "")))); return
                else:
                    self._send(200, APP.services.daemon_status(payload.get("daemon_id"))); return
            if path in {"/api/command/lint_fix", "/api/lint_fix"}:
                self._send(200, APP.services.lint_fix(str(payload.get("root", ".")), command=payload.get("command"), paths=payload.get("paths"), tenant=tenant, timeout=payload.get("timeout"))); return
            if path in {"/api/command/http_probe", "/api/http_probe"}:
                self._send(200, APP.services.http_probe(str(payload.get("url", "")), expected_status=int(payload.get("expected_status", 200)), json_path=payload.get("json_path"), timeout=float(payload.get("timeout", 5.0)), headers=payload.get("headers"))); return
            if path in {"/api/repo/callers", "/api/callers"}:
                self._send(200, APP.services.callers(str(payload.get("root", ".")), str(payload.get("symbol", "")), limit=int(payload.get("limit", 50)))); return
            if path in {"/api/repo/secret_scan", "/api/secret_scan"}:
                self._send(200, APP.services.secret_scan(str(payload.get("root", ".")), payload.get("path"), scan_git_history=bool(payload.get("scan_git_history", payload.get("git_history", False))), commit_depth=int(payload.get("commit_depth", 20)))); return
            if path in {"/api/repo/schema_inspect", "/api/schema_inspect"}:
                self._send(200, APP.services.schema_inspect(str(payload.get("root", ".")), payload.get("db_path"))); return
            if path in {"/api/repo/explain_query", "/api/explain_query"}:
                self._send(200, APP.services.explain_query(str(payload.get("root", ".")), str(payload.get("query", "")), payload.get("db_path"))); return
            if path in {"/api/repo/env_compat", "/api/env_compat"}:
                self._send(200, APP.services.env_compat(str(payload.get("root", ".")))); return
            if path in {"/api/coord/pubsub_publish", "/api/pubsub_publish"}:
                self._send(200, APP.services.pubsub_publish(str(payload.get("topic", "default")), payload.get("message", ""), sender=str(payload.get("publisher", payload.get("sender", "agent"))))); return
            if path in {"/api/coord/pubsub_poll", "/api/pubsub_poll"}:
                self._send(200, APP.services.pubsub_poll(str(payload.get("topic", "default")), since_timestamp=float(payload.get("since_timestamp", 0.0)), limit=int(payload.get("limit", 50)))); return
            if path in {"/api/coord/simulate_merge", "/api/simulate_merge"}:
                self._send(200, APP.services.simulate_merge(str(payload.get("root", ".")), str(payload.get("source_branch", "")), target_branch=str(payload.get("target_branch", "HEAD")))); return
            if path in {"/api/task/eval_suite", "/api/eval_suite"}:
                self._send(200, APP.services.eval_suite(payload, tenant)); return
            if path in {"/api/task/prompt_eval", "/api/prompt_eval"}:
                self._send(200, APP.services.prompt_eval(payload, tenant)); return
            if path in {"/api/task/eval_drift", "/api/eval_drift"}:
                self._send(200, APP.services.eval_drift(payload, tenant)); return
            if path in {"/api/repo/circular_dependencies", "/api/circular_dependencies"}:
                self._send(200, APP.services.circular_dependencies(str(payload.get("root", ".")), language=str(payload.get("language", "python")))); return
            if path in {"/api/repo/generate_types", "/api/generate_types"}:
                self._send(200, APP.services.generate_types(str(payload.get("root", ".")), str(payload.get("file", payload.get("path", ""))), write_stub=bool(payload.get("write_stub", False)))); return
            if path in {"/api/repo/complexity", "/api/complexity"}:
                self._send(200, APP.services.code_complexity(
                    str(payload.get("root", ".")), path=payload.get("path"),
                    max_results=int(payload.get("max_results", 20)), include_tests=bool(payload.get("include_tests", False))
                )); return
            if path in {"/api/repo/api_spec", "/api/api_spec"}:
                self._send(200, APP.services.extract_api_spec(str(payload.get("root", ".")), framework=payload.get("framework"))); return
            if path in {"/api/repo/dependency_slice", "/api/dependency_slice"}:
                self._send(200, APP.services.slice_dependency_graph(str(payload.get("root", ".")), str(payload.get("symbol", "")), path=payload.get("path"), depth=int(payload.get("depth", 2)))); return
            if path in {"/api/repo/migration_drift", "/api/migration_drift"}:
                self._send(200, APP.services.migration_drift(str(payload.get("root", ".")), db_path=payload.get("db_path"))); return
            if path in {"/api/repo/package_audit", "/api/package_audit"}:
                self._send(200, APP.services.package_audit(str(payload.get("root", ".")), lockfile_path=payload.get("lockfile_path"))); return
            if path in {"/api/repo/structural_search", "/api/structural_search"}:
                self._send(200, APP.services.structural_search(str(payload.get("root", ".")), str(payload.get("pattern", "")), path=payload.get("path"), max_results=int(payload.get("max_results", 30)))); return
            if path in {"/api/repo/context_budget", "/api/context_budget"}:
                self._send(200, APP.services.context_budget(str(payload.get("root", ".")), files=payload.get("files"), max_tokens=int(payload.get("max_tokens", 4000)))); return
            if path in {"/api/rag/ingest_document", "/api/ingest_document"}:
                self._send(200, APP.rag.ingest_document(str(payload.get("workspace", "default")), str(payload.get("content", "")), title=str(payload.get("title", "")), metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None, tenant=tenant)); return
            if path in {"/api/rag/ingest_diagram", "/api/ingest_diagram"}:
                self._send(200, APP.rag.ingest_diagram(str(payload.get("workspace", "default")), str(payload.get("image_path", payload.get("path", ""))), caption=str(payload.get("caption", "")), metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None, tenant=tenant)); return
            if path in {"/api/command/mock_server", "/api/mock_server"}:
                act = str(payload.get("action", "status")).strip().lower()
                port = int(payload.get("port", 11440))
                if act == "start":
                    self._send(200, APP.services.mock_server_start(str(payload.get("root", ".")), spec_path=payload.get("spec_path"), port=port)); return
                elif act == "stop":
                    self._send(200, APP.services.mock_server_stop(port=port)); return
                else:
                    self._send(200, APP.services.mock_server_status(port=port)); return

            if path in {"/api/command/diff_hunk_stage", "/api/diff_hunk_stage"}:
                self._send(200, APP.services.diff_hunk_stage(str(payload.get("root", payload.get("cwd", "."))), str(payload.get("patch", "")))); return
            if path in {"/api/command/flaky_detect", "/api/flaky_detect"}:
                self._send(200, APP.services.test_flaky_detect(str(payload.get("root", payload.get("cwd", "."))), str(payload.get("command", "")), runs=int(payload.get("runs", 5)), timeout_per_run=int(payload.get("timeout", 30)))); return
            if path in {"/api/command/webhook_replay", "/api/webhook_replay"}:
                self._send(200, APP.services.webhook_replay(str(payload.get("url", "")), payload.get("payload", {}), secret=str(payload.get("secret", "")), signature_header=str(payload.get("signature_header", "X-Hub-Signature-256")), timeout=float(payload.get("timeout", 10.0)))); return

            # Optional Ollama/OpenAI protocol proxy. Local AI applies
            # the same shared exact cache + single-flight before the Ollama queue.
            if path in {"/api/generate", "/api/chat", "/api/embed"}:
                if payload.get("stream") is True:
                    self._send(400, {"error": "streaming is intentionally disabled through the affinity queue"}); return
                result = APP.services.proxy_request(path, payload, tenant, f"proxy:{path}")
                self._send(200 if "error" not in result else 500, result); return

            self._send(404, {"error": "not found"})
        except QueueFullError as exc:
            APP.logger.warning("queue full path=%s tenant=%s", path, tenant)
            self._send(429, {"success": False, "error": str(exc), "status_code": 429, "retryable": True})
        except ModelUnavailableError as exc:
            APP.logger.warning("model unavailable path=%s tenant=%s error=%s", path, tenant, exc)
            self._send(503, {"success": False, "error": str(exc), "status_code": 503, "retryable": True})
        except (ValueError, TypeError, RequestBodyError) as exc:
            if APP is not None:
                APP.logger.warning("invalid request payload path=%s tenant=%s error=%s", path, tenant, exc)
            self._send(400, {"success": False, "error": str(exc), "status_code": 400, "terminal": True, "retryable": False})
        except KeyError as exc:
            if APP is not None:
                APP.logger.warning("resource not found path=%s tenant=%s key=%s", path, tenant, exc)
            self._send(404, {"success": False, "error": str(exc), "status_code": 404, "terminal": True, "retryable": False})
        except Exception as exc:
            if _is_client_disconnect(exc):
                self._finish_debug_trace(499, {"success": False, "terminal": True}, error="client disconnected")
                self._close_trace_context()
                return
            APP.logger.exception("request failed path=%s error=%s", path, type(exc).__name__)
            try:
                self._send(500, {"success": False, "error": str(exc)})
            except Exception:
                pass


def validate_network_security(config: dict[str, Any]) -> None:
    bind = str(config.get("server", {}).get("bind", "127.0.0.1")).strip().lower()
    loopback = bind in {"127.0.0.1", "localhost", "::1"}
    if loopback:
        return
    security = config.get("security", {})
    if not bool(security.get("allow_remote", False)):
        raise RuntimeError("Refusing non-loopback Local AI Hub bind: set [security].allow_remote=true explicitly")
    token = str(security.get("api_token", ""))
    if len(token) < 16:
        raise RuntimeError("Remote Local AI Hub bind requires [security].api_token with at least 16 characters")


def serve(config_path: str | None = None) -> None:
    global APP
    # Bind the public port before constructing LocalAIApp. A duplicate/stale service
    # process therefore fails before it starts preprocessing threads or opens the
    # shared SQLite stores, eliminating a major source of lock storms during restart.
    startup_config = load_config(config_path)
    validate_network_security(startup_config)
    cfg = startup_config["server"]
    server = LocalAIHTTPServer(
        (cfg.get("bind", "127.0.0.1"), int(cfg.get("port", 11435))),
        Handler,
        max_handlers=int(cfg.get("max_concurrent_requests", 64)),
        overload_wait_seconds=float(cfg.get("overload_wait_seconds", 0.05)),
    )
    try:
        APP = LocalAIApp(config_path)
        validate_network_security(APP.config)
    except Exception:
        server.server_close()
        if APP is not None:
            try:
                APP.close()
            finally:
                APP = None
        raise
    cfg = APP.config["server"]
    state_dir = Path(cfg["state_dir"])
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
    APP.telemetry.session_start(os.getpid(), __version__)
    APP.telemetry.record_system("hub_start", success=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        try:
            APP.telemetry.session_stop()
            APP.telemetry.record_system("hub_stop", success=True)
            APP.telemetry.flush(1.0)
            APP.logger.info("hub stopping version=%s", __version__)
        except Exception:
            pass
        try:
            APP.close()
        except Exception:
            pass
        try:
            if pid_path.exists() and pid_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                pid_path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    serve(os.environ.get("LOCAL_AI_CONFIG"))
