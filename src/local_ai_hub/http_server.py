from __future__ import annotations

import hmac
import json
import os
import queue
import socket
import uuid
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__
from .app import LocalAIApp
from .budget import estimate_tokens
from .scheduler import ModelUnavailableError, QueueFullError
from .debug_traces import DebugTraceObserver
from .trace_context import reset_context, reset_observer, set_context, set_observer
from .dashboard import DASHBOARD_HTML
from .config import ConfigError, deep_merge, load_config, save_runtime_overrides, validate_config
from .delivery import decide_delivery
from .agent_identity import AgentScope, ScopeContext
from .agent_tasks import CompletionGateError, GoalContract, InvalidTransitionError, TaskCheckpoint, TaskStatus
from .agent_memory import ApprovalRequiredError, MemoryKind, MemoryRecord, MemoryStatus
from .agent_incidents import IncidentFingerprint, ToolOutcome
from .agent_verification import VerificationReceipt
from .agent_context import ContextRequest
from .agent_learning import CandidateStatus, ImprovementCandidate, SLOObservation


os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

APP: LocalAIApp | None = None

# Monitoring/control reads must never appear as workload. Keep this hard safety set
# independent of user config so a dashboard refresh cannot create immortal active jobs.
MONITOR_PATHS = {
    "/health", "/dashboard", "/favicon.ico", "/v1/live", "/v1/live/status",
    "/v1/status", "/v1/capabilities", "/v1/metrics", "/v1/telemetry/report", "/v1/audit/tail", "/v1/control",
    "/v1/config", "/v1/logs/tail", "/v1/hardware/system", "/v1/hardware/gpu",
    "/v1/debug-traces",
}


def _json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _telemetry_http_outcome(status: int, data: Any) -> tuple[bool, str, bool]:
    """Return reliability success, safe outcome category, and error-record flag."""
    payload = data if isinstance(data, dict) else {}
    success = status < 400 and payload.get("success") is not False
    if payload.get("policy_blocked"):
        return True, "policy_block", False
    if payload.get("in_progress"):
        return True, "in_progress", False
    if payload.get("terminal") and status < 500:
        return True, "terminal_client_result", False
    if success:
        return True, "", False
    return False, "http_error", True


def _journal_outcome_success(status: int, data: Any) -> bool:
    payload = data if isinstance(data, dict) else {}
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
    # Windows socket error codes that indicate the peer closed the connection:
    #   32     – ERROR_BROKEN_PIPE  (mapped from POSIX EPIPE)
    #   10053  – WSAECONNABORTED    – software caused connection abort
    #   10054  – WSAECONNRESET      – connection reset by peer
    #   10038  – WSAENOTSOCK        – socket closed/invalidated before send
    return isinstance(exc, OSError) and getattr(exc, "winerror", None) in {32, 10038, 10053, 10054}


class RequestBodyError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class LocalAIHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server with a hard cap on live handler threads.

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
        self._overload_body = json.dumps(
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
        super().__init__(server_address, handler)

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
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        try:
            timeout = float(APP.config.get("server", {}).get("request_timeout_seconds", 210)) if APP is not None else 210.0
            self.connection.settimeout(max(1.0, timeout))
        except Exception:
            pass

    def _common_headers(self, *, html: bool = False, nonce: str | None = None) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if html:
            script_source = f"'nonce-{nonce}'" if nonce else "'none'"
            self.send_header("Content-Security-Policy", f"default-src 'none'; connect-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; script-src {script_source}; script-src-attr 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

    def _send_html(self, status: int, html: str) -> None:
        nonce = uuid.uuid4().hex
        body = html.replace("<script>", f'<script nonce="{nonce}">', 1).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self._common_headers(html=True, nonce=nonce)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError as exc:
            if not _is_client_disconnect(exc):
                raise

    server_version = f"LocalAIHub/{__version__}"

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
                if path not in MONITOR_PATHS and not path.startswith("/v1/debug-traces/") and path not in excluded:
                    APP.telemetry.record_live(kind="request", event_type="request_start", tenant=self._tenant(), agent=self._agent(), request_id=request_id, trace_id=trace_id, action=path, success=True)
                    trace_store = getattr(APP, "debug_traces", None)
                    if trace_store is not None:
                        self._debug_trace_id = trace_store.start(kind="api_request", tenant=self._tenant(), agent=self._agent(), action=path, source="http", request_id=request_id)
                        if self._debug_trace_id:
                            trace_store.event(self._debug_trace_id, "request_received", {"method": self.command, "path": path, "request_id": request_id})
                            self._debug_observer_token = set_observer(DebugTraceObserver(trace_store, self._debug_trace_id))
        except Exception:
            pass

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
        return self.headers.get("X-LocalAI-Tenant") or self.headers.get("X-Tenant-ID") or "http-default"

    def _agent(self) -> str:
        return self.headers.get("X-LocalAI-Agent") or "generic"

    def _authorized(self) -> bool:
        if APP is None:
            return True
        expected = str(APP.config.get("security", {}).get("api_token", ""))
        if not expected:
            return True
        supplied = self.headers.get("X-LocalAI-Token", "")
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        return hmac.compare_digest(supplied, expected)

    def _require_authorized(self) -> bool:
        if self._authorized():
            return True
        self._send(401, {"success": False, "error": "unauthorized"})
        return False

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

        if path == "/v1/chat/completions":
            messages = payload.get("messages")
            if not isinstance(messages, list) or not messages or len(messages) > 128:
                raise RequestBodyError("messages must be a non-empty list of at most 128 entries")
            if len(json.dumps(messages, ensure_ascii=False, default=str)) > 1_000_000:
                raise RequestBodyError("messages exceed 1000000 characters", 413)
        elif path == "/v1/embed":
            values = payload.get("texts", payload.get("input", []))
            values = [values] if isinstance(values, str) else values
            if not isinstance(values, list) or len(values) > 256:
                raise RequestBodyError("texts must be a list of at most 256 entries")
            for value in values:
                text(value, "embedding text", 200000)
        elif path == "/v1/command":
            text(payload.get("command", ""), "command", 8000)
        elif path in {"/v1/preprocess", "/v1/repo/profile", "/v1/repo/map", "/v1/repo/code-index", "/v1/repo/deterministic", "/v1/search"}:
            if "root" in payload:
                text(payload["root"], "root", 4096)
        elif path == "/v1/memory/put":
            required_text("key", maximum=160)
            required_text("value", maximum=1000000)
            if "root" in payload:
                text(payload["root"], "root", 4096)
        elif path in {"/v1/memory/get", "/v1/memory/delete"}:
            required_text("key", maximum=160)
            if "root" in payload:
                text(payload["root"], "root", 4096)
        elif path == "/v1/memory/search":
            if "root" in payload:
                text(payload["root"], "root", 4096)
            if "query" in payload:
                text(payload["query"], "query", 4096)
        elif path == "/v1/code/symbol":
            required_text("symbol", maximum=1024)
        elif path == "/v1/code/find_symbol":
            required_text("pattern", "name_path_pattern", maximum=1024)
        elif path in {"/v1/code/find_declaration", "/v1/code/find_implementations", "/v1/code/find_referencing_symbols"}:
            required_text("symbol", "name", maximum=1024)
        elif path in {"/v1/code/ast_outline", "/v1/code/symbols_overview", "/v1/code/diagnostics"}:
            required_text("path", "file", maximum=4096)
        elif path == "/v1/code-intelligence/query":
            action = text(payload.get("action", "search"), "action", 80).strip().lower().replace("-", "_")
            if action not in {"dead_code", "dead", "stats", "repository_stats"}:
                required_text("query", maximum=4096)
            if action in {"overview", "symbols_overview", "references", "find_references", "referencing"}:
                required_text("path", maximum=4096)
        evaluation = payload.get("evaluation")
        if evaluation is not None:
            if not isinstance(evaluation, dict):
                raise RequestBodyError("evaluation must be an object")
            if "task_id" not in evaluation or "cohort" not in evaluation:
                raise RequestBodyError("evaluation task_id and cohort are required")

    def _async_delivery(self, path: str, payload: dict[str, Any], tenant: str) -> tuple[int, dict[str, Any]] | None:
        """Convert eligible long foreground work into an existing durable job when requested."""
        if APP is None:
            return None
        action_by_path = {
            "/v1/delegate": "delegate", "/v1/reason": "reason", "/v1/review": "review",
            "/v1/second-opinion": "second_opinion", "/v1/compress": "compress",
            "/v1/route": "route", "/v1/delegate/batch": "batch",
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
            decision = decide_delivery(
                str(payload.get("delivery", "sync")), latency_budget_ms=payload.get("latency_budget_ms", 0),
                observed_p95_ms=estimate.get("p95_duration_ms", 0), samples=estimate.get("samples", 0),
            )
        except (TypeError, ValueError) as exc:
            return 400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}
        if decision["mode"] != "async":
            return None
        job_payload = dict(payload)
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
        result = APP.async_jobs.submit(tenant, job_action, job_payload)
        result["delivery"] = decision
        trace_store = getattr(APP, "debug_traces", None)
        api_trace_id = str(getattr(self, "_debug_trace_id", "") or "")
        if trace_store is not None and api_trace_id and isinstance(result, dict):
            if result.get("job_id"):
                trace_store.link(api_trace_id, async_job_id=str(result["job_id"]))
            trace_store.event(api_trace_id, "async_job_submitted", {"job_id": result.get("job_id", ""), "trace_id": result.get("trace_id", ""), "delivery": decision})
        return 200, result

    def _send(self, status: int, data: Any) -> None:
        request_id = getattr(self, "_journal_request_id", None)
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
                if path not in MONITOR_PATHS and not path.startswith("/v1/debug-traces/") and path not in excluded:
                    elapsed_ms = max(0.0, (time.perf_counter() - float(getattr(self, "_request_started", time.perf_counter()))) * 1000)
                    policy_blocked = bool(path == "/v1/command" and isinstance(data, dict) and data.get("policy_blocked"))
                    telemetry_data = dict(data) if isinstance(data, dict) else data
                    if policy_blocked and isinstance(telemetry_data, dict):
                        telemetry_data["policy_blocked"] = True
                    reliability_success, outcome_error_type, record_operational_error = _telemetry_http_outcome(status, telemetry_data)
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
            self._common_headers()
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

        last_seq = after_seq
        if stream_id and after_seq >= 0:
            past = APP.agent_state.events(stream_id=stream_id, after_seq=after_seq, limit=1000)
            for ev in past:
                if kind and ev.kind != kind:
                    continue
                last_seq = max(last_seq, ev.seq or 0)
                payload = json.dumps(ev.to_dict(), separators=(",", ":"))
                msg = f"id: {ev.seq}\nevent: {ev.kind}\ndata: {payload}\n\n".encode("utf-8")
                try:
                    self.wfile.write(msg)
                    self.wfile.flush()
                except OSError:
                    self._finish_stream_request(True)
                    return

        q = APP.agent_state.subscribe(maxsize=200)
        start_time = time.time()
        try:
            while True:
                if timeout > 0 and (time.time() - start_time) >= timeout:
                    break
                try:
                    ev = q.get(timeout=1.0)
                    if ev.seq is not None and ev.seq <= last_seq:
                        continue
                    if stream_id and ev.stream_id != stream_id:
                        continue
                    if kind and ev.kind != kind:
                        continue
                    if ev.seq is not None:
                        last_seq = max(last_seq, ev.seq)
                    payload = json.dumps(ev.to_dict(), separators=(",", ":"))
                    msg = f"id: {ev.seq or 0}\nevent: {ev.kind}\ndata: {payload}\n\n".encode("utf-8")
                    self.wfile.write(msg)
                    self.wfile.flush()
                except queue.Empty:
                    try:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                    except OSError:
                        break
        except (OSError, Exception):
            pass
        finally:
            APP.agent_state.unsubscribe(q)
            self._finish_stream_request(True)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/health":
            self._send(200, {"success": True, "hub_online": True, "version": __version__})
            return
        if APP is None:
            self._send(503, {"success": False, "error": "hub starting up; please retry", "status_code": 503, "retryable": True})
            return
        self._begin_trace(path)
        # The dashboard shell contains no runtime data. Keeping it public lets a
        # remote deployment prompt for an API token client-side; every data/control
        # endpoint remains authenticated.
        if path not in {"/dashboard", "/favicon.ico"} and not self._require_authorized():
            return
        query = parse_qs(parsed.query)
        try:
            if path == "/dashboard":
                if not bool(APP.config.get("monitoring", {}).get("dashboard_enabled", True)) or not bool(APP.config.get("features", {}).get("dashboard", True)):
                    self._send(404, {"error": "dashboard disabled"}); return
                self._telemetry_finished = True
                self._send_html(200, DASHBOARD_HTML); return
            if path == "/favicon.ico":
                self._telemetry_finished = True
                self.send_response(204); self.end_headers(); return
            if path == "/v1/live":
                after = int((query.get("after") or [0])[0]); limit = int((query.get("limit") or [200])[0])
                max_batch = int(APP.config.get("monitoring", {}).get("live_max_batch", 200))
                self._send(200, APP.telemetry.live(after, min(limit, max_batch))); return
            if path == "/v1/live/status":
                light = str((query.get("light") or ["0"])[0]).lower() in {"1", "true", "yes"}
                scope = str((query.get("scope") or ["process"])[0])
                status = APP.realtime_status(light=light, scope=scope)
                if isinstance(self.server, LocalAIHTTPServer):
                    status["http_concurrency"] = self.server.concurrency_stats()
                self._send(200, status); return
            if path == "/v1/status":
                detail = str((query.get("detail") or [""])[0]).strip().lower()
                if detail == "agent_state":
                    tasks = APP.agent_tasks.list_tasks() if getattr(APP, "agent_tasks", None) else []
                    active_tasks = [t.task_id for t in tasks if t.status == TaskStatus.ACTIVE]
                    incidents = APP.agent_incidents.list_incidents() if getattr(APP, "agent_incidents", None) else []
                    candidates = APP.agent_learning.list_candidates() if getattr(APP, "agent_learning", None) else []
                    self._send(200, {
                        "success": True,
                        "enabled": bool(getattr(APP, "agent_state", None) and APP.agent_state.enabled),
                        "active_tasks": active_tasks,
                        "tasks_count": len(tasks),
                        "incidents_count": len(incidents),
                        "candidates_count": len(candidates),
                        "status": "healthy",
                    }); return
                scope = str((query.get("scope") or ["process"])[0])
                status = APP.status(scope=scope)
                if isinstance(self.server, LocalAIHTTPServer):
                    status["http_concurrency"] = self.server.concurrency_stats()
                self._send(200, status); return
            if path == "/v1/agent-state/tasks":
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
                tasks = APP.agent_tasks.list_tasks(status=status_filter, limit=limit)
                self._send(200, {"success": True, "tasks": [t.to_dict() for t in tasks]}); return
            if path == "/v1/agent-state/memory":
                if not getattr(APP, "agent_memory", None) or not APP.agent_memory.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                rec_id = (query.get("record_id") or [""])[0]
                if rec_id:
                    rec = APP.agent_memory.get(rec_id)
                    if not rec:
                        self._send(404, {"success": False, "error": "memory record not found", "terminal": True, "retryable": False}); return
                    self._send(200, {"success": True, "record": rec.to_dict()}); return
                scope_raw = (query.get("scope") or [None])[0]
                scope_val = None
                if scope_raw:
                    try:
                        scope_val = AgentScope(str(scope_raw).lower())
                    except ValueError:
                        pass
                key_val = (query.get("key") or [None])[0]
                query_val = (query.get("query") or [None])[0]
                status_raw = (query.get("status") or [None])[0]
                status_val = None
                if status_raw:
                    try:
                        status_val = MemoryStatus(str(status_raw).lower())
                    except ValueError:
                        pass
                limit_val = int((query.get("limit") or [100])[0])
                records = APP.agent_memory.find(scope=scope_val, key=key_val, query=query_val, status=status_val, limit=limit_val)
                self._send(200, {"success": True, "records": [r.to_dict() for r in records]}); return
            if path == "/v1/agent-state/events":
                if not getattr(APP, "agent_state", None) or not APP.agent_state.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                stream_id = (query.get("stream_id") or [""])[0]
                after_seq = int((query.get("after_seq") or [0])[0])
                limit = int((query.get("limit") or [100])[0])
                evs = APP.agent_state.events(stream_id=stream_id, after_seq=after_seq, limit=limit)
                self._send(200, {"success": True, "events": [e.to_dict() for e in evs]}); return
            if path == "/v1/agent-state/events/stream":
                if not getattr(APP, "agent_state", None) or not APP.agent_state.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                stream_filter = (query.get("stream_id") or [""])[0]
                kind_filter = (query.get("kind") or [""])[0]
                after_seq = int((query.get("after_seq") or [0])[0])
                timeout = float((query.get("timeout") or [0.0])[0])
                self._stream_agent_events(stream_id=stream_filter, kind=kind_filter, after_seq=after_seq, timeout=timeout)
                return
            if path == "/v1/capabilities":
                self._send(200, APP.capabilities()); return
            if path == "/v1/metrics":
                days = int((query.get("days") or [30])[0])
                scope = str((query.get("scope") or ["window"])[0])
                self._send(200, {"success": True, "metrics": APP.telemetry.summary(days, scope=scope)}); return
            if path == "/v1/telemetry/report":
                days = int((query.get("days") or [30])[0])
                scope = str((query.get("scope") or ["window"])[0])
                self._send(200, {"success": True, "report": APP.telemetry.report(days, scope=scope)}); return
            if path == "/v1/audit/tail":
                limit = int((query.get("limit") or [20])[0])
                self._send(200, {"success": True, "events": APP.telemetry.tail(limit)}); return
            if path == "/v1/debug-traces":
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
            if path.startswith("/v1/debug-traces/"):
                trace_id = path.rsplit("/", 1)[-1]
                since_seq = int((query.get("since_seq") or [0])[0])
                result = APP.debug_traces.detail(trace_id, since_seq=max(0, since_seq))
                if result.get("success") and isinstance(result.get("session"), dict):
                    session = self._reconcile_debug_trace(result["session"])
                    result["terminal"] = session.get("state") in APP.debug_traces.TERMINAL_STATES
                self._send(200, result); return
            if path == "/v1/rag/workspaces":
                self._send(200, {"success": True, "workspaces": APP.rag.list_workspaces(self._tenant())}); return
            if path == "/v1/leases":
                root = (query.get("root") or [""])[0]
                self._send(200, {"success": True, "leases": APP.leases.list(root)}); return
            if path == "/v1/cross_project_graph":
                roots = [str(p.get("root")) for p in APP.preprocessor.status().get("projects", []) if p.get("root")]
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.cross_project_graph(roots))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/dead_code":
                root = (query.get("root") or ["."])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.services.dead_code(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/symbol_callgraph":
                root = (query.get("root") or ["."])[0]
                sym = (query.get("symbol") or [None])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.symbol_callgraph(root, sym))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/hardware/gpu":
                from .gpu_monitor import get_gpu_telemetry
                self._send(200, get_gpu_telemetry())
                return
            if path == "/v1/hardware/system":
                from .gpu_monitor import get_system_telemetry
                self._send(200, get_system_telemetry())
                return
            if path == "/v1/audit_dependencies":
                root = (query.get("root") or ["."])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.audit_dependencies(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/refactor_impact":
                root = (query.get("root") or ["."])[0]
                file_param = (query.get("file") or [""])[0]
                symbol_param = (query.get("symbol") or [None])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.services.refactor_impact(root, file_param, symbol_param))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/test_matrix":
                root = (query.get("root") or ["."])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.services.test_matrix(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/security_audit":
                root = (query.get("root") or ["."])[0]
                limit = int((query.get("limit") or [50])[0])
                if APP.deterministic is not None:
                    self._send(200, APP.services.security_audit(root, limit))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/code/ast_outline":
                root = (query.get("root") or ["."])[0]
                path_param = (query.get("path") or [""])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.services.ast_outline(root, path_param))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/maintenance/optimize_db":
                self._send(200, APP.services.optimize_databases())
                return
            if path == "/v1/maintenance/purge_cache":
                days = int((query.get("days") or [7])[0])
                self._send(200, APP.services.purge_stale_cache(days))
                return
            if path == "/v1/config":
                view = json.loads(json.dumps(APP.config, ensure_ascii=False, default=str))
                if isinstance(view.get("security"), dict) and view["security"].get("api_token"):
                    view["security"]["api_token"] = "***configured***"
                self._send(200, {"success": True, "config": view, "config_path": APP.config.get("_config_path", ""), "runtime_override_path": APP.config.get("_runtime_override_path", "")})
                return
            if path == "/v1/logs/tail":
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
            if path == "/v1/doctor":
                self._send(200, APP.services.run_doctor())
                return
            if path in {"/v1/preprocess", "/v1/preprocess/status"}:
                root = (query.get("root") or [None])[0]
                self._send(200, APP.preprocessor.status(root))
                return
            if path == "/v1/code/symbol":
                root = (query.get("root") or ["."])[0]
                sym = (query.get("symbol") or [""])[0]
                self._send(200, APP.services.code_inspect_symbol(root, sym))
                return
            if path == "/v1/code/find_symbol":
                root = (query.get("root") or ["."])[0]
                pat = (query.get("pattern") or query.get("name_path_pattern") or [""])[0]
                depth = int((query.get("depth") or [0])[0])
                include_body = bool((query.get("include_body") or [False])[0])
                rel_path = (query.get("path") or query.get("relative_path") or [None])[0]
                self._send(200, APP.services.code_find_symbol(root, pat, depth=depth, include_body=include_body, relative_path=rel_path))
                return
            if path == "/v1/code/find_declaration":
                root = (query.get("root") or ["."])[0]
                sym = (query.get("symbol") or query.get("name") or [""])[0]
                rel_path = (query.get("path") or [None])[0]
                self._send(200, APP.services.code_find_declaration(root, sym, path=rel_path))
                return
            if path == "/v1/code/find_implementations":
                root = (query.get("root") or ["."])[0]
                sym = (query.get("symbol") or query.get("name") or [""])[0]
                rel_path = (query.get("path") or [None])[0]
                self._send(200, APP.services.code_find_implementations(root, sym, path=rel_path))
                return
            if path == "/v1/code/find_referencing_symbols":
                root = (query.get("root") or ["."])[0]
                sym = (query.get("symbol") or query.get("name") or [""])[0]
                rel_path = (query.get("path") or [None])[0]
                self._send(200, APP.services.code_find_referencing_symbols(root, sym, path=rel_path))
                return
            if path == "/v1/code/symbols_overview":
                root = (query.get("root") or ["."])[0]
                fpath = (query.get("path") or [""])[0]
                depth = int((query.get("depth") or [1])[0])
                self._send(200, APP.services.code_symbols_overview(root, fpath, depth=depth))
                return
            if path == "/v1/code/diagnostics":
                root = (query.get("root") or ["."])[0]
                fpath = (query.get("path") or [""])[0]
                self._send(200, APP.services.code_diagnostics(root, fpath))
                return
            if path == "/v1/resolve_imports":
                root = (query.get("root") or ["."])[0]
                lang = (query.get("language") or ["auto"])[0]
                symbols = [s for s in (query.get("symbols") or (query.get("symbol") or [])) if s]
                if APP.deterministic is not None:
                    self._send(200, APP.services.resolve_imports(root, symbols, lang))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/git/status":
                root = (query.get("root") or ["."])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.git_status(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/git/synthesize_commit":
                root = (query.get("root") or ["."])[0]
                hint = (query.get("hint") or [""])[0]
                task_id = (query.get("task_id") or [""])[0]
                if APP.deterministic is not None:
                    self._send(200, APP.services.synthesize_commit(root, hint, task_id=task_id))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/models":
                models = APP.runtime.installed_models()
                self._send(200, {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "ollama"} for m in models]}); return
            self._send(404, {"error": "not found"})
        except (ValueError, RequestBodyError) as exc:
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

    def do_POST(self) -> None:
        if APP is None:
            self._send(503, {"success": False, "error": "hub starting up; please retry", "status_code": 503, "retryable": True})
            return
        path = urlparse(self.path).path
        self._begin_trace(path)
        if not self._require_authorized():
            return
        # Bundle imports use raw ZIP bytes so dashboard/API clients do not pay the
        # 33% base64 expansion and are governed by the bundle-specific safety cap.
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if path == "/v1/bundle/import" and content_type in {"application/zip", "application/octet-stream"}:
            try:
                limit = max(1024, int(APP.config.get("bundles", {}).get("max_bundle_bytes", 128 * 1024 * 1024)))
                raw_bundle = self._read_body(limit=limit)
                query = parse_qs(urlparse(self.path).query)
                target_root = (query.get("target_root") or [None])[0]
                self._send(200, APP.import_bundle(raw_bundle, target_root)); return
            except RequestBodyError as exc:
                self._send(exc.status, {"success": False, "error": str(exc)}); return
        try:
            payload = self._read_json()
            self._validate_payload(path, payload)
        except RequestBodyError as exc:
            self._send(exc.status, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
        self._request_evaluation = payload.get("evaluation")
        if path == "/v1/conversations/continue" or (
            path in {"/v1/delegate", "/v1/reason"} and bool(payload.get("conversation", False))
        ):
            self._redact_debug_trace()
        trace_store = getattr(APP, "debug_traces", None)
        api_trace_id = str(getattr(self, "_debug_trace_id", "") or "")
        if trace_store is not None and api_trace_id:
            trace_store.update(api_trace_id, state="running", request=payload)
            trace_store.event(api_trace_id, "handler_started", {"action": path, "payload_keys": sorted(str(key) for key in payload)})
        tenant = self._tenant()
        self._journal_request_id = str(getattr(self, "_trace_request_id", ""))
        self._journal_finished = False
        try:
            prior = APP.recovery.lookup(self._journal_request_id, tenant, path)
            if prior and prior.get("state") in {"done", "failed"} and prior.get("response") is not None:
                self._journal_finished = True
                self._send(int(prior.get("status_code") or (200 if prior.get("state") == "done" else 500)), prior["response"]); return
            if prior and prior.get("state") == "running":
                wait_seconds = min(2.0, max(0.05, float(APP.config.get("resilience", {}).get("singleflight_wait_timeout_seconds", 1.0))))
                replay = APP.recovery.wait_for(self._journal_request_id, tenant, path, timeout_seconds=wait_seconds)
                if replay and replay.get("state") in {"done", "failed"} and replay.get("response") is not None:
                    self._journal_finished = True
                    self._send(int(replay.get("status_code") or (200 if replay.get("state") == "done" else 500)), replay["response"]); return
                self._journal_finished = True
                self._send(409, {"success": False, "error": "request with this id is already running", "retryable": True, "in_progress": True, "retry_after_seconds": 1, "waited_seconds": wait_seconds}); return
            if prior and prior.get("state") == "conflict":
                self._journal_finished = True
                self._send(409, {"success": False, "error": prior.get("error", "request id conflict")}); return
            APP.recovery.begin(self._journal_request_id, tenant, path)
        except Exception:
            pass
        try:
            if path == "/v1/config/update":
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
                    "hardware.profile": {"auto", "cpu", "low", "balanced", "high", "max"},
                    "preprocessing.enabled": {True, False},
                    "code_intelligence.enabled": {True, False},
                    "code_intelligence.serena_enabled": {True, False},
                    "code_intelligence.codegraph_enabled": {True, False},
                    "monitoring.dashboard_enabled": {True, False},
                    **{f"features.{feat_name}": {True, False} for feat_name in (
                        "status", "repo", "tasks", "rag", "commands", "coord",
                        "artifacts", "code_intelligence", "preprocessing",
                        "subagents", "agent_os", "dashboard",
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
            if path == "/v1/control":
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
            delivery = self._async_delivery(path, payload, tenant)
            if delivery is not None:
                self._send(*delivery); return
            if path == "/v1/delegate":
                self._send(200, APP.services.delegate(payload, tenant)); return
            if path == "/v1/conversations/continue":
                self._send(200, APP.services.continue_conversation(payload, tenant)); return
            if path == "/v1/async-jobs":
                action = str(payload.get("action", "")).strip().lower().replace("-", "_")
                if action == "submit":
                    self._send(200, APP.async_jobs.submit(tenant, str(payload.get("job_action", "reason")), payload)); return
                if action == "status":
                    self._send(200, APP.async_jobs.status(tenant, str(payload.get("job_id", "")))); return
                if action == "wait":
                    self._send(200, APP.async_jobs.wait(tenant, str(payload.get("job_id", "")), float(payload.get("timeout_seconds", 90)))); return
                if action == "result":
                    self._send(200, APP.async_jobs.result(tenant, str(payload.get("job_id", "")))); return
                if action == "cancel":
                    self._send(200, APP.async_jobs.cancel(tenant, str(payload.get("job_id", "")))); return
                self._send(400, {"success": False, "error": "unknown async job action", "terminal": True, "retryable": False}); return
            if path == "/v1/agent-state/tasks":
                if not getattr(APP, "agent_tasks", None) or not APP.agent_tasks.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                action = str(payload.get("action", "")).strip().lower().replace("-", "_")
                idempotency_key = str(payload.get("idempotency_key", "")).strip()
                actor = self._agent() or "agent"
                if action == "create":
                    contract_data = payload.get("contract") or {}
                    if not contract_data:
                        goal = str(payload.get("goal") or payload.get("title") or payload.get("value") or payload.get("query") or payload.get("task") or "")
                        contract_data = {
                            "goal": goal,
                            "acceptance_criteria": payload.get("acceptance_criteria") or [],
                            "scope": payload.get("scope", "task"),
                            "non_goals": payload.get("non_goals") or [],
                            "constraints": payload.get("constraints") or [],
                            "risk_profile": payload.get("risk_profile", "normal"),
                        }
                    contract = GoalContract.from_dict(contract_data)
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
                    try:
                        task = APP.agent_tasks.transition(
                            str(payload.get("task_id", "")),
                            target_status,
                            reason=str(payload.get("reason", "")),
                            actor=actor,
                            idempotency_key=idempotency_key,
                        )
                        self._send(200, {"success": True, "task": task.to_dict()}); return
                    except (KeyError, InvalidTransitionError, CompletionGateError) as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "complete":
                    try:
                        task = APP.agent_tasks.complete(
                            str(payload.get("task_id", "")),
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
                if action == "list":
                    status_filter = None
                    if payload.get("status"):
                        try:
                            status_filter = TaskStatus(str(payload.get("status")).strip().lower())
                        except ValueError:
                            pass
                    limit = int(payload.get("limit", 100))
                    tasks = APP.agent_tasks.list_tasks(status=status_filter, limit=limit)
                    self._send(200, {"success": True, "tasks": [t.to_dict() for t in tasks]}); return
                self._send(400, {"success": False, "error": f"unknown task action '{action}'", "terminal": True, "retryable": False}); return
            if path == "/v1/agent-state/memory":
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
                            "scope": payload.get("scope", AgentScope.TASK.value),
                            "key": str(payload.get("key") or payload.get("query") or ""),
                            "value": payload.get("value"),
                            "scope_id": str(payload.get("scope_id", "")),
                            "confidence": payload.get("confidence", 1.0),
                            "status": payload.get("status"),
                            "source": payload.get("source", actor),
                            "evidence_ids": payload.get("evidence_ids") or [],
                            "sensitivity": payload.get("sensitivity", "normal"),
                            "provenance": payload.get("provenance"),
                        }
                    try:
                        raw_kind = str(rec_data.get("kind", MemoryKind.FACT.value)).lower()
                        try:
                            kind_val = MemoryKind(raw_kind)
                        except ValueError:
                            kind_val = MemoryKind.FACT
                        raw_scope = str(rec_data.get("scope", AgentScope.TASK.value)).lower()
                        try:
                            scope_val = AgentScope(raw_scope)
                        except ValueError:
                            scope_val = AgentScope.TASK
                        raw_status = rec_data.get("status")
                        status_val = None
                        if raw_status:
                            try:
                                status_val = MemoryStatus(str(raw_status).lower())
                            except ValueError:
                                status_val = None
                        record = MemoryRecord.create(
                            kind=kind_val,
                            scope=scope_val,
                            key=str(rec_data.get("key", "")),
                            value=rec_data.get("value"),
                            scope_id=str(rec_data.get("scope_id", "")),
                            confidence=float(rec_data.get("confidence", 1.0)),
                            status=status_val,
                            source=str(rec_data.get("source", actor)),
                            evidence_ids=tuple(rec_data.get("evidence_ids") or ()),
                            sensitivity=str(rec_data.get("sensitivity", "normal")),
                            provenance=rec_data.get("provenance"),
                        )
                        saved = APP.agent_memory.record(record, actor=actor, idempotency_key=idempotency_key)
                        self._send(200, {"success": True, "record": saved.to_dict()}); return
                    except Exception as exc:
                        self._send(400, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "get":
                    rec = APP.agent_memory.get(str(payload.get("record_id", "")))
                    if not rec:
                        self._send(404, {"success": False, "error": "memory record not found", "terminal": True, "retryable": False}); return
                    self._send(200, {"success": True, "record": rec.to_dict()}); return
                if action == "find":
                    scope_val = AgentScope(str(payload["scope"])) if payload.get("scope") else None
                    key_val = str(payload["key"]) if payload.get("key") else None
                    query_val = str(payload["query"]) if payload.get("query") else None
                    status_val = MemoryStatus(str(payload["status"])) if payload.get("status") else None
                    limit_val = int(payload.get("limit", 100))
                    records = APP.agent_memory.find(scope=scope_val, key=key_val, query=query_val, status=status_val, limit=limit_val)
                    self._send(200, {"success": True, "records": [r.to_dict() for r in records]}); return
                if action == "promote":
                    target_scope_str = str(payload.get("target_scope", "")).strip().lower()
                    try:
                        target_scope = AgentScope(target_scope_str)
                    except ValueError:
                        self._send(400, {"success": False, "error": f"invalid target scope '{target_scope_str}'", "terminal": True, "retryable": False}); return
                    approver = str(payload.get("approver", actor))
                    try:
                        promoted = APP.agent_memory.promote(
                            str(payload.get("record_id", "")),
                            target_scope,
                            approver=approver,
                        )
                        self._send(200, {"success": True, "record": promoted.to_dict()}); return
                    except ApprovalRequiredError as exc:
                        self._send(403, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                    except KeyError as exc:
                        self._send(404, {"success": False, "error": str(exc), "terminal": True, "retryable": False}); return
                if action == "quarantine":
                    reason = str(payload.get("reason", "manual quarantine"))
                    try:
                        quarantined = APP.agent_memory.quarantine(
                            str(payload.get("record_id", "")),
                            reason=reason,
                            actor=actor,
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
                self._send(400, {"success": False, "error": f"unknown memory action '{action}'", "terminal": True, "retryable": False}); return
            if path == "/v1/agent-state/incidents":
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
                    err_class = str(payload.get("error_class", payload.get("class", "AgentError")))
                    msg = str(payload.get("message", payload.get("redacted_message", payload.get("value", ""))))
                    op = str(payload.get("operation_class", payload.get("tool_name", payload.get("key", "agent"))))
                    root_cause = str(payload.get("root_cause", ""))
                    verified_fix = str(payload.get("verified_fix", payload.get("fix", "")))
                    rev = str(payload.get("state_revision", payload.get("revision", "")))
                    evidence_ids = tuple(payload.get("evidence_ids") or ())
                    outcome = ToolOutcome(
                        tool_name=op, error=msg or "recorded incident", exit_code=int(payload.get("exit_code", 1)),
                        state_revision=rev, evidence_ids=evidence_ids,
                        metadata={"root_cause": root_cause, "verified_fix": verified_fix},
                    )
                    inc = APP.agent_incidents.capture(outcome)
                    if inc and (verified_fix or root_cause):
                        inc = APP.agent_incidents.resolve_fix(inc.incident_id, verified_fix=verified_fix, root_cause=root_cause)
                    self._send(200, {"success": True, "incident": inc.to_dict() if inc else None}); return
                if action == "find":
                    query_str = str(payload.get("query", payload.get("key", ""))).strip().lower()
                    resolved_filter = payload.get("resolved")
                    limit_val = int(payload.get("limit", 100))
                    all_incs = APP.agent_incidents.list_incidents(resolved=resolved_filter, limit=limit_val * 2)
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
                    limit_val = int(payload.get("limit", 100))
                    incidents = APP.agent_incidents.list_incidents(resolved=resolved_filter, limit=limit_val)
                    self._send(200, {"success": True, "incidents": [i.to_dict() for i in incidents]}); return
                self._send(400, {"success": False, "error": f"unknown incident action '{action}'", "terminal": True, "retryable": False}); return
            if path == "/v1/agent-state/verification":
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
                    res = APP.agent_verification.completion(task_id)
                    self._send(200, {"success": True, "completion": res.to_dict()}); return
                self._send(400, {"success": False, "error": f"unknown verification action '{action}'", "terminal": True, "retryable": False}); return
            if path == "/v1/agent-state/context":
                if not getattr(APP, "agent_context", None) or not APP.agent_context.state_store.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                action = str(payload.get("action", "")).strip().lower().replace("-", "_")
                if action == "compile":
                    req = ContextRequest(
                        task_id=str(payload.get("task_id", "")),
                        token_budget=int(payload.get("token_budget", 4000)),
                        include_kinds=tuple(payload.get("include_kinds") or ()),
                        changed_paths=tuple(payload.get("changed_paths") or ()),
                    )
                    compiled = APP.agent_context.compile(req)
                    self._send(200, {"success": True, "context": compiled.to_dict(), "text": compiled.text()}); return
                self._send(400, {"success": False, "error": f"unknown context action '{action}'", "terminal": True, "retryable": False}); return
            if path == "/v1/agent-state/learning":
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
                                baseline_version=str(cand_data.get("baseline_version", "v1")),
                                candidate_version=str(cand_data.get("candidate_version", "v2")),
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
            if path == "/v1/agent-state/cleanup":
                if not getattr(APP, "agent_state", None) or not APP.agent_state.enabled:
                    self._send(403, {"success": False, "error": "agent_state is disabled", "terminal": True, "retryable": False}); return
                retention = int(payload.get("retention_days") or APP.config.get("agent_state", {}).get("retention_days", 30))
                res = APP.agent_state.cleanup(retention_days=retention)
                self._send(200, res); return
            if path == "/v1/delegate/repo":
                self._send(200, APP.services.delegate_repo(payload, tenant)); return
            if path == "/v1/solve/repo":
                self._send(200, APP.services.solve_repo(payload, tenant)); return
            if path == "/v1/route":
                self._send(200, APP.services.route_context(payload, tenant)); return
            if path == "/v1/delegate/batch":
                self._send(200, APP.services.batch_delegate(payload, tenant)); return
            if path == "/v1/review":
                self._send(200, APP.services.review(payload, tenant)); return
            if path == "/v1/review/diff":
                self._send(200, APP.services.review_diff(payload, tenant)); return
            if path == "/v1/reason":
                self._send(200, APP.services.reason(payload, tenant)); return
            if path == "/v1/second-opinion":
                self._send(200, APP.services.second_opinion(payload, tenant)); return
            if path == "/v1/compress":
                self._send(200, APP.services.compress(payload, tenant)); return
            if path == "/v1/generate_tests":
                self._send(200, APP.services.generate_tests(payload, tenant))
                return
            if path == "/v1/patch/validate":
                self._send(200, APP.services.validate_patch(payload, tenant))
                return
            if path == "/v1/query/expand":
                q = str(payload.get("query", ""))
                self._send(200, {"success": True, "query": q, "expanded_terms": APP.services.expand_query(q, tenant)})
                return
            if path == "/v1/audit_dependencies":
                root = str(payload.get("root", "."))
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.audit_dependencies(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/refactor_impact":
                root = str(payload.get("root", "."))
                file_param = str(payload.get("file", payload.get("path", "")))
                symbol_param = payload.get("symbol")
                if APP.deterministic is not None:
                    self._send(200, APP.services.refactor_impact(root, file_param, symbol_param))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/resolve_imports":
                root = str(payload.get("root", "."))
                lang = str(payload.get("language", "csharp"))
                syms = payload.get("symbols", [payload.get("symbol")] if payload.get("symbol") else [])
                if APP.deterministic is not None:
                    self._send(200, APP.services.resolve_imports(root, syms, lang))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/git/status":
                root = str(payload.get("root", "."))
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.git_status(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/git/synthesize_commit":
                root = str(payload.get("root", "."))
                hint = str(payload.get("hint", payload.get("message", "")))
                task_id = str(payload.get("task_id", ""))
                if APP.deterministic is not None:
                    self._send(200, APP.services.synthesize_commit(root, hint, task_id=task_id))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/test_matrix":
                root = str(payload.get("root", "."))
                if APP.deterministic is not None:
                    self._send(200, APP.services.test_matrix(root))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/security_audit":
                root = str(payload.get("root", "."))
                limit = int(payload.get("limit", 50))
                if APP.deterministic is not None:
                    self._send(200, APP.services.security_audit(root, limit))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/code-intelligence/query":
                root = str(payload.get("root", "."))
                self._send(200, APP.external_tools.query(
                    root, str(payload.get("query", "")),
                    backend=str(payload.get("backend", "auto")),
                    action=str(payload.get("action", "search")),
                    path=str(payload.get("path", "")),
                    limit=max(1, min(int(payload.get("limit", 20)), 50)),
                ))
                return
            if path == "/v1/code/ast_outline":
                root = str(payload.get("root", "."))
                path_param = str(payload.get("path", payload.get("file", "")))
                if APP.deterministic is not None:
                    self._send(200, APP.services.ast_outline(root, path_param))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/maintenance/optimize_db":
                self._send(200, APP.services.optimize_databases())
                return
            if path == "/v1/maintenance/purge_cache":
                days = int(payload.get("days", 7))
                self._send(200, APP.services.purge_stale_cache(days))
                return
            if path == "/v1/doctor":
                self._send(200, APP.services.run_doctor())
                return
            if path == "/v1/code/symbol":
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol", ""))
                self._send(200, APP.services.code_inspect_symbol(root, sym))
                return
            if path == "/v1/code/find_symbol":
                root = str(payload.get("root", "."))
                pat = str(payload.get("pattern") or payload.get("name_path_pattern") or "")
                depth = int(payload.get("depth", 0))
                include_body = bool(payload.get("include_body", False))
                include_info = bool(payload.get("include_info", True))
                rel_path = payload.get("path") or payload.get("relative_path")
                limit = int(payload.get("limit", 30))
                self._send(200, APP.services.code_find_symbol(root, pat, depth=depth, include_body=include_body, include_info=include_info, relative_path=str(rel_path) if rel_path else None, limit=limit))
                return
            if path == "/v1/code/find_declaration":
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol") or payload.get("name") or "")
                rel_path = payload.get("path")
                self._send(200, APP.services.code_find_declaration(root, sym, path=str(rel_path) if rel_path else None))
                return
            if path == "/v1/code/find_implementations":
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol") or payload.get("name") or "")
                rel_path = payload.get("path")
                self._send(200, APP.services.code_find_implementations(root, sym, path=str(rel_path) if rel_path else None))
                return
            if path == "/v1/code/find_referencing_symbols":
                root = str(payload.get("root", "."))
                sym = str(payload.get("symbol") or payload.get("name") or "")
                rel_path = payload.get("path")
                self._send(200, APP.services.code_find_referencing_symbols(root, sym, path=str(rel_path) if rel_path else None))
                return
            if path == "/v1/code/symbols_overview":
                root = str(payload.get("root", "."))
                fpath = str(payload.get("path", ""))
                depth = int(payload.get("depth", 1))
                self._send(200, APP.services.code_symbols_overview(root, fpath, depth=depth))
                return
            if path == "/v1/code/diagnostics":
                root = str(payload.get("root", "."))
                fpath = str(payload.get("path", ""))
                self._send(200, APP.services.code_diagnostics(root, fpath))
                return
            if path == "/v1/code-intelligence/control":
                action = str(payload.get("action", "status")).strip().lower().replace("-", "_")
                if action == "status":
                    self._send(200, {"success": True, **APP.external_tools.status()}); return
                if action in {"rediscover", "refresh"}:
                    self._send(200, APP.external_tools.rediscover()); return
                if action in {"reset", "reset_sessions"}:
                    self._send(200, APP.external_tools.reset_sessions(str(payload.get("backend", "all")), str(payload.get("root")) if payload.get("root") else None)); return
                self._send(400, {"success": False, "error": f"unknown code-intelligence action: {action}"}); return
            if path == "/v1/complete":
                # FIM completion routed through APP.services with caching / APP.scheduler.submit
                self._send(200, APP.services.complete_code(payload, tenant)); return
            if path == "/v1/preprocess":
                self._send(200, APP.services.preprocess(payload)); return
            if path == "/v1/dead_code":
                root = str(payload.get("root", "."))
                limit = int(payload.get("limit", 50))
                self._send(200, APP.services.dead_code(root, limit))
                return
            if path == "/v1/symbol_callgraph":
                root = str(payload.get("root", "."))
                sym = payload.get("symbol")
                limit = int(payload.get("limit", 50))
                self._send(200, APP.services.symbol_callgraph(root, str(sym) if sym else None, limit))
                return
            if path == "/v1/cross_project_graph":
                roots = payload.get("roots")
                if not isinstance(roots, list) or not roots:
                    roots = [str(p.get("root")) for p in APP.preprocessor.status().get("projects", []) if p.get("root")]
                if APP.deterministic is not None:
                    self._send(200, APP.deterministic.cross_project_graph([str(r) for r in roots]))
                else:
                    self._send(200, {"success": False, "error": "deterministic engine disabled"})
                return
            if path == "/v1/bundle/export":
                root = str(payload.get("root", "."))
                try:
                    data = APP.export_bundle(root)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self._common_headers()
                    self.send_header("Content-Disposition", 'attachment; filename="local-ai-hub-project.bundle.zip"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as exc:
                    self._send(500, {"success": False, "error": str(exc)})
                return
            if path == "/v1/bundle/import":
                data_b64 = payload.get("bundle_base64")
                target_root = payload.get("target_root")
                if data_b64:
                    import base64
                    try:
                        raw = base64.b64decode(str(data_b64), validate=True)
                        res = APP.import_bundle(raw, str(target_root) if target_root else None)
                        self._send(200 if res.get("success") else 400, res)
                    except Exception as exc:
                        self._send(400, {"success": False, "error": str(exc)})
                else:
                    self._send(400, {"success": False, "error": "missing bundle_base64 in json payload"})
                return
            if path == "/v1/benchmark":
                self._send(200, APP.services.benchmark(tenant)); return
            if path == "/v1/evaluation":
                self._send(200, APP.services.evaluation(payload)); return
            if path == "/v1/repo/profile":
                self._send(200, APP.services.repo_profile(str(payload.get("root", ".")))); return
            if path == "/v1/repo/map":
                self._send(200, APP.services.repo_map(str(payload.get("root", ".")), int(payload.get("max_symbols", 120)))); return
            if path == "/v1/repo/code-index":
                self._send(200, APP.services.code_query(str(payload.get("root", ".")), str(payload.get("query", "")), int(payload.get("limit", 20)))); return
            if path == "/v1/repo/deterministic":
                self._send(200, APP.services.deterministic_query(str(payload.get("root", ".")), str(payload.get("query", "")), int(payload.get("limit", 24)))); return
            if path == "/v1/repo/impact":
                self._send(200, APP.services.repo_impact(
                    str(payload.get("root", ".")), str(payload.get("base", "HEAD")), bool(payload.get("staged", False)),
                    int(payload.get("max_symbols", APP.config.get("workflow", {}).get("impact_max_symbols", 48))),
                    int(payload.get("max_dependents", APP.config.get("workflow", {}).get("impact_max_dependents", 30))),
                )); return
            if path == "/v1/search":
                self._send(200, APP.services.repo_search(str(payload.get("root", ".")), str(payload.get("query", "")), int(payload.get("top_k", 12)))); return
            if path == "/v1/context/pack":
                root = str(payload.get("root", ".")); query_text = str(payload.get("query", ""))
                max_tokens = int(payload.get("max_tokens", APP.config.get("token_saving", {}).get("default_repo_context_tokens", 4200)))
                mode = str(payload.get("mode", "fast")).strip().lower()
                if mode not in {"full", "fast"}:
                    self._send(400, {"success": False, "terminal": True, "retryable": False, "error": "context mode must be full or fast"}); return
                result = APP.services.fast_context(root, query_text, max_tokens) if mode == "fast" else APP.services._hybrid_context(
                    root, query_text, tenant, payload.get("workspace"), max_tokens,
                )
                if isinstance(result, dict):
                    result["delivery_mode"] = mode
                self._send(200, result); return
            if path == "/v1/artifact/get":
                self._send(200, APP.artifacts.get(str(payload.get("artifact_id", "")), int(payload.get("offset", 0)), int(payload.get("max_chars", 6000)), str(payload.get("section", "")))); return
            if path == "/v1/evidence/verify":
                evidence = payload.get("evidence", [])
                self._send(200, APP.repo_tools.verify_evidence(str(payload.get("root", ".")), evidence if isinstance(evidence, list) else [])); return
            if path == "/v1/evidence/get":
                self._send(200, APP.evidence.get(str(payload.get("evidence_id", "")), verify=bool(payload.get("verify", True)))); return
            if path == "/v1/leases/claim":
                paths = payload.get("paths", [])
                self._send(200, APP.leases.claim(tenant, str(payload.get("root", ".")), [str(x) for x in paths] if isinstance(paths, list) else [], int(payload.get("ttl_seconds", 900)), str(payload.get("purpose", "agent edit")))); return
            if path == "/v1/leases/release":
                self._send(200, APP.leases.release(tenant, str(payload.get("lease_id", "")))); return
            if path == "/v1/memory/put":
                self._send(200, APP.memory.put(
                    str(payload.get("root", ".")), str(payload.get("key", "")), str(payload.get("value", "")), tenant,
                    ttl_seconds=payload.get("ttl_seconds"), metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
                )); return
            if path == "/v1/memory/get":
                self._send(200, APP.memory.get(str(payload.get("root", ".")), str(payload.get("key", "")))); return
            if path == "/v1/memory/search":
                self._send(200, APP.memory.search(str(payload.get("root", ".")), str(payload.get("query", "")), int(payload.get("limit", 12)))); return
            if path == "/v1/memory/delete":
                self._send(200, APP.memory.delete(str(payload.get("root", ".")), str(payload.get("key", "")), tenant)); return
            if path == "/v1/command":
                self._send(200, APP.services.command(payload, tenant)); return
            if path == "/v1/embed":
                texts = payload.get("texts", payload.get("input", []))
                if isinstance(texts, str):
                    texts = [texts]
                self._send(200, APP.services.embed([str(x) for x in texts], tenant, query=bool(payload.get("query", False)))); return
            if path == "/v1/rerank":
                docs = payload.get("documents", [])
                self._send(200, APP.reranker.rerank(str(payload.get("query", "")), [str(x) for x in docs], payload.get("top_k"))); return
            if path == "/v1/rag/index":
                self._send(200, APP.rag.index(str(payload.get("root", ".")), tenant, payload.get("workspace"))); return
            if path == "/v1/rag/search":
                workspace = str(payload.get("workspace", ""))
                if not workspace:
                    self._send(400, {"success": False, "error": "workspace is required"}); return
                self._send(200, APP.rag.search(str(payload.get("query", "")), tenant, workspace, int(payload.get("top_k", 8)), bool(payload.get("use_reranker", True)))); return

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
        except (ValueError, RequestBodyError) as exc:
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
            self._send(500, {"success": False, "error": str(exc)})


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
    APP.logger.info("hub started version=%s bind=%s port=%s", __version__, cfg.get("bind", "127.0.0.1"), int(cfg.get("port", 11435)))
    APP.telemetry.record_system("hub_start", success=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        try:
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
