from __future__ import annotations

import io
import socket
import threading
from email.message import Message
from http import HTTPStatus
from typing import Any, Mapping
from urllib.error import HTTPError

from .config import load_config
from .json_utils import dumps as json_dumps
from .operational_mode import load_operational_mode, operational_mode_gate_error


_APP_LOCK = threading.RLock()


class InProcessTransportFailure(OSError):
    """In-process setup failed before the request reached a route handler."""

    request_not_sent = True


class _MemoryConnection:
    def __init__(self, timeout: float):
        self._timeout = timeout

    def gettimeout(self) -> float:
        return self._timeout

    def settimeout(self, timeout: float | None) -> None:
        self._timeout = timeout


class _AdmissionState:
    """Reuse the HTTP server's per-tenant limiter without binding a socket."""

    def __init__(self, security: Mapping[str, Any]):
        self._rate_limit_requests = max(1, int(security.get("rate_limit_requests", 600)))
        self._rate_limit_window = max(1.0, float(security.get("rate_limit_window_seconds", 60.0)))
        self._rate_windows: dict[str, list[float]] = {}
        self._rate_lock = threading.Lock()

    def check_rate_limit(self, tenant: str) -> bool:
        from .http_server import LocalAIHTTPServer

        return LocalAIHTTPServer.check_rate_limit(self, tenant)


class InProcessTransport:
    """Run the existing HTTP handler dispatch in this process using memory streams."""

    def __init__(self, config_path: str | None = None):
        self.config = load_config(config_path)
        self.config_path = str(self.config.get("_config_path", config_path or ""))
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._app: Any = None
        self._http_server: Any = None
        self._owns_app = False
        self._closed = False
        self._close_when_idle = False
        self._active: set[threading.Thread] = set()
        self._admission = _AdmissionState(self.config.get("security", {}))
        server_cfg = self.config.get("server", {})
        self._handler_slots = threading.BoundedSemaphore(
            max(4, int(server_cfg.get("max_concurrent_requests", 64)))
        )
        self._overload_wait_seconds = max(0.0, float(server_cfg.get("overload_wait_seconds", 0.05)))

    def _create_app(self) -> Any:
        from .app import LocalAIApp

        return LocalAIApp(self.config_path or None)

    def _get_app(self) -> tuple[Any, Any]:
        from . import http_server

        with _APP_LOCK:
            with self._lock:
                if self._closed:
                    raise InProcessTransportFailure("in-process transport is closed")
                if self._app is not None:
                    return self._app, self._http_server
                current = http_server.APP
                if current is not None:
                    self._app = current
                    self._http_server = http_server
                    self._owns_app = False
                    return current, http_server
                try:
                    app = self._create_app()
                except Exception as exc:
                    raise InProcessTransportFailure(str(exc)) from exc
                if http_server.APP is not None:
                    try:
                        app.close()
                    except Exception:
                        pass
                    raise InProcessTransportFailure("HTTP handler app changed during in-process startup")
                http_server.APP = app
                self._app = app
                self._http_server = http_server
                self._owns_app = True
                return app, http_server

    def _mode_rejection(self, operational_action: str | None, requires_heavy_work: bool) -> dict[str, Any] | None:
        state_dir = self.config.get("server", {}).get("state_dir")
        snapshot = load_operational_mode(state_dir)
        return operational_mode_gate_error(
            snapshot,
            operational_action,
            requires_heavy_work=requires_heavy_work,
        )

    def _dispatch(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
        operational_action: str | None,
        requires_heavy_work: bool,
        dispatched: threading.Event,
        cancel_before_dispatch: threading.Event,
        dispatch_lock: Any,
    ) -> tuple[int, bytes, dict[str, str]]:
        with dispatch_lock:
            if cancel_before_dispatch.is_set():
                raise InProcessTransportFailure("in-process request timed out before dispatch")
        try:
            app, http_server = self._get_app()
        except InProcessTransportFailure:
            raise
        except Exception as exc:
            raise InProcessTransportFailure(str(exc)) from exc
        if cancel_before_dispatch.is_set():
            raise InProcessTransportFailure("in-process request timed out before dispatch")

        if method not in {"GET", "POST"}:
            payload = {"success": False, "error": "method not allowed", "terminal": True, "retryable": False}
            return 405, json_dumps(payload).encode("utf-8"), {"content-type": "application/json; charset=utf-8"}

        transport = self

        class MemoryHandler(http_server.Handler):
            def _require_authorized(self) -> bool:
                if not super()._require_authorized():
                    return False
                rejection = transport._mode_rejection(operational_action, requires_heavy_work)
                if rejection is not None:
                    self._send(503, rejection)
                    return False
                return True

            def send_response(self, code: int, message: str | None = None) -> None:
                self._memory_status = int(code)

            def send_header(self, keyword: str, value: str) -> None:
                self._memory_headers[str(keyword).lower()] = str(value)

            def end_headers(self) -> None:
                return None

            def log_message(self, _fmt: str, *_args: Any) -> None:
                return None

        server_cfg = self.config.get("server", {})
        conn = _MemoryConnection(timeout)
        handler = MemoryHandler.__new__(MemoryHandler)
        handler.command = method
        handler.path = path
        handler.request_version = "HTTP/1.1"
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.close_connection = True
        handler.server = self._admission
        handler.request = conn
        handler.connection = conn
        client_host = str(server_cfg.get("client_host", "") or server_cfg.get("bind", "127.0.0.1"))
        if client_host in {"0.0.0.0", "::", "[::]"}:
            client_host = "127.0.0.1"
        if ":" in client_host and not client_host.startswith("["):
            host_value = f"[{client_host}]:{int(server_cfg.get('port', 11435))}"
        else:
            host_value = f"{client_host}:{int(server_cfg.get('port', 11435))}"
        handler.client_address = (client_host.strip("[]"), 0)
        handler.headers = Message()
        for key, value in headers.items():
            handler.headers[str(key)] = str(value)
        if handler.headers.get("Host") is None:
            handler.headers["Host"] = host_value
        if handler.headers.get("Content-Type") is None and body is not None:
            handler.headers["Content-Type"] = "application/json"
        if handler.headers.get("Content-Length") is None and body is not None:
            handler.headers["Content-Length"] = str(len(body))
        handler.rfile = io.BytesIO(body or b"")
        handler.wfile = io.BytesIO()
        handler._memory_status = 200
        handler._memory_headers = {}
        handler._headers_buffer = []
        with dispatch_lock:
            if cancel_before_dispatch.is_set():
                raise InProcessTransportFailure("in-process request timed out before dispatch")
            dispatched.set()
        if method == "GET":
            handler.do_GET()
        else:
            handler.do_POST()
        return handler._memory_status, handler.wfile.getvalue(), handler._memory_headers

    def open(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
        operational_action: str | None = None,
        requires_heavy_work: bool = True,
    ) -> bytes:
        method = str(method).upper()
        path = str(path)
        request_timeout = max(0.0, float(timeout))
        result: dict[str, Any] = {}
        completed = threading.Event()
        dispatched = threading.Event()
        cancel_before_dispatch = threading.Event()
        dispatch_lock = threading.Lock()

        def run() -> None:
            try:
                if not self._handler_slots.acquire(timeout=self._overload_wait_seconds):
                    overload = {
                        "success": False,
                        "error": "hub overloaded; retry later",
                        "status_code": 503,
                        "retryable": True,
                        "retry_after_seconds": 1,
                    }
                    result["response"] = (
                        503,
                        json_dumps(overload).encode("utf-8"),
                        {"content-type": "application/json; charset=utf-8"},
                    )
                else:
                    try:
                        result["response"] = self._dispatch(
                            method,
                            path,
                            body,
                            headers,
                            request_timeout,
                            operational_action,
                            requires_heavy_work,
                            dispatched,
                            cancel_before_dispatch,
                            dispatch_lock,
                        )
                    finally:
                        self._handler_slots.release()
            except BaseException as exc:
                result["error"] = exc
            finally:
                with self._condition:
                    self._active.discard(threading.current_thread())
                    close_now = self._close_when_idle and not self._active
                    self._condition.notify_all()
                if close_now:
                    self._dispose_app()
                completed.set()

        worker = threading.Thread(target=run, name="local-ai-inprocess-request", daemon=True)
        with self._condition:
            if self._closed:
                raise InProcessTransportFailure("in-process transport is closed")
            self._active.add(worker)
        worker.start()
        if not completed.wait(request_timeout):
            with dispatch_lock:
                was_dispatched = dispatched.is_set()
                if not was_dispatched:
                    cancel_before_dispatch.set()
            if was_dispatched:
                raise socket.timeout("in-process request timed out after dispatch")
            raise InProcessTransportFailure("in-process request timed out before dispatch")
        if "error" in result:
            raise result["error"]
        status, response_body, response_headers = result["response"]
        if status >= 400:
            try:
                reason = HTTPStatus(status).phrase
            except ValueError:
                reason = "Request Failed"
            raise HTTPError(
                f"inprocess://{path}",
                status,
                reason,
                response_headers,
                io.BytesIO(response_body),
            )
        return response_body

    def _dispose_app(self) -> None:
        with _APP_LOCK:
            with self._lock:
                app = self._app
                module = self._http_server
                owns_app = self._owns_app
                self._app = None
                self._http_server = None
                self._owns_app = False
                self._close_when_idle = False
            if owns_app and app is not None:
                if module is not None and getattr(module, "APP", None) is app:
                    module.APP = None
                try:
                    app.close()
                except Exception:
                    pass

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            if self._active:
                self._close_when_idle = True
                return
        self._dispose_app()
