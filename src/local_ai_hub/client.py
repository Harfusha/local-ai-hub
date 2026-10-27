from __future__ import annotations

from .repository_scope import (
    RepositoryScopeError, authorized_repository_root, reject_retired_tenancy_fields,
)

from .json_utils import dumps as json_dumps

import copy
import contextvars
import errno
import http.client
import inspect
import io
import json
import math
import os
import socket
import threading
import uuid
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from .process_utils import find_listening_pid, pid_alive, popen_managed, process_identity, retain_process_job_in_child, terminate_tree
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import load_config
from .operation_contracts import normalize_transport_error, operation_actions, validate_operation_arguments


CURRENT_REQUEST_CANCEL_EVENT: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "hub_request_cancel_event", default=None,
)


class PathHint(Protocol):
    """Typed request-scoped path hint, compatible with project_config.PathHint."""

    path: str
    purpose: str
    scope: str
    evidence_id: str | None
    provenance: str | None
    repository_revision: str | None
    config_digest: str | None
    expires_at: str | None


_PATH_HINT_FIELDS = frozenset(
    {"path", "purpose", "scope", "evidence_id", "provenance", "repository_revision", "config_digest", "expires_at"}
)
_PATH_HINT_REQUIRED_FIELDS = ("path", "purpose", "scope")


class _InProcessTransport(Protocol):
    def open(
        self, method: str, path: str, body: bytes | None,
        headers: Mapping[str, str], timeout: float,
        operational_action: str | None = None,
        requires_heavy_work: bool = True,
        cancel_event: threading.Event | None = None,
    ) -> bytes: ...

    def close(self) -> None: ...


class _TransportFailure(OSError):
    """Transport error with evidence whether any request bytes could be sent."""

    def __init__(self, cause: BaseException, *, request_not_sent: bool, cancelled: bool = False) -> None:
        super().__init__(str(cause))
        self.request_not_sent = request_not_sent
        self.cancelled = cancelled


class _SingleflightCancelled(Exception):
    """A coalesced caller stopped waiting while shared work may still run."""


_DETACHED_CHILDREN_LOCK = threading.Lock()
_DETACHED_CHILDREN: list[subprocess.Popen[Any]] = []
_ORIGINAL_SUBPROCESS_RUN = getattr(subprocess, "run", None)


def _retain_detached_child(process: subprocess.Popen[Any]) -> None:
    """Keep intentionally detached hub children alive for later polling/reaping."""
    with _DETACHED_CHILDREN_LOCK:
        _DETACHED_CHILDREN[:] = [child for child in _DETACHED_CHILDREN if child.poll() is None]
        _DETACHED_CHILDREN.append(process)


def _stop_owned_child(process: subprocess.Popen[Any]) -> None:
    """Stop and reap only the child created by this startup attempt."""
    try:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=0.25)
    except Exception:
        pass


def _write_start_lock_owner(handle: Any) -> None:
    handle.seek(0)
    handle.truncate()
    fields = [str(os.getpid()), str(time.time())]
    identity = process_identity(os.getpid())
    if identity is not None:
        identity_type = str(identity.get("creation_identity_type", ""))
        creation_identity = str(identity.get("creation_identity", ""))
        if identity_type and creation_identity:
            fields.extend((identity_type, creation_identity))
    handle.write(" ".join(fields).encode("ascii", errors="ignore"))
    handle.flush()


def _acquire_start_lock(path: Path, stale_seconds: float = 20.0) -> Any | None:
    """Serialize marker recovery; a held OS lock cannot expire during startup."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            if not handle.read(1):
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        handle.seek(0)
        marker = handle.read().decode("ascii", errors="ignore").split()
        try:
            owner_pid = int(marker[0]) if marker else 0
        except ValueError:
            owner_pid = 0
        age = max(0.0, time.time() - path.stat().st_mtime)
        owner_is_live = bool(owner_pid and age <= max(1.0, stale_seconds) and pid_alive(owner_pid))
        if owner_is_live and len(marker) >= 4:
            identity = process_identity(owner_pid)
            if identity is not None:
                owner_is_live = bool(
                    identity.get("creation_identity_type") == marker[2]
                    and str(identity.get("creation_identity")) == marker[3]
                )
        if owner_is_live:
            handle.close()
            return None
        _write_start_lock_owner(handle)
        return handle
    except OSError as exc:
        handle.close()
        if not locked and exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            return None
        raise
    except BaseException:
        handle.close()
        raise


class HubClient:
    def __init__(
        self,
        *,
        config_path: str | None = None,
        auto_start: bool = True,
        inprocess_transport: _InProcessTransport | None = None,
    ):
        if "LOCAL_AI_TENANT" in os.environ:
            raise ValueError("LOCAL_AI_TENANT is retired; this installation has one local owner")
        self.config = load_config(config_path, probe_hardware=False)
        server = self.config["server"]
        self.base_url = f"http://127.0.0.1:{int(server.get('port', 11435))}"
        endpoint = urlsplit(self.base_url)
        self._http_host = str(endpoint.hostname or "127.0.0.1")
        self._http_port = int(endpoint.port or 80)
        self.api_token = str(self.config.get("security", {}).get("api_token", ""))
        self.agent = os.environ.get("LOCAL_AI_AGENT_PROFILE") or os.environ.get("LOCAL_AI_AGENT") or "generic"
        self.auto_start = bool(auto_start)
        self._inprocess_transport = inprocess_transport
        client_cfg = self.config.get("client", {})
        self.health_timeout = max(0.2, float(client_cfg.get("health_timeout_seconds", 0.75)))
        self.startup_wait = max(1.0, float(client_cfg.get("startup_wait_seconds", 30.0)))
        self.startup_poll = max(0.05, float(client_cfg.get("startup_poll_seconds", 0.15)))
        self.start_lock_stale = max(self.startup_wait, float(client_cfg.get("start_lock_stale_seconds", 20.0)))
        self.max_request_timeout = max(5.0, float(client_cfg.get("max_request_timeout_seconds", 1800.0)))
        self._transport_local = threading.local()
        self._connections_lock = threading.Lock()
        self._connections: dict[int, http.client.HTTPConnection] = {}
        self._flight_lock = threading.RLock()
        self._flights: dict[str, dict[str, Any]] = {}

    def _drop_connection(self) -> None:
        conn = getattr(self._transport_local, "connection", None)
        self._transport_local.connection = None
        with self._connections_lock:
            if conn is not None and self._connections.get(threading.get_ident()) is conn:
                self._connections.pop(threading.get_ident(), None)
        if conn is not None:
            try: conn.close()
            except Exception: pass

    def close(self) -> None:
        current = getattr(self._transport_local, "connection", None)
        self._transport_local.connection = None
        with self._connections_lock:
            connections = list(self._connections.values())
            self._connections.clear()
        if current is not None and current not in connections:
            connections.append(current)
        for conn in connections:
            try: conn.close()
            except Exception: pass
        if self._inprocess_transport is not None:
            try:
                self._inprocess_transport.close()
            except Exception:
                pass

    def __del__(self) -> None:
        try: self.close()
        except Exception: pass

    def _connection(self, timeout: float) -> http.client.HTTPConnection:
        conn = getattr(self._transport_local, "connection", None)
        if conn is None:
            conn = http.client.HTTPConnection(self._http_host, self._http_port, timeout=timeout)
            self._transport_local.connection = conn
            with self._connections_lock:
                previous = self._connections.get(threading.get_ident())
                self._connections[threading.get_ident()] = conn
            if previous is not None and previous is not conn:
                try: previous.close()
                except Exception: pass
        elif getattr(conn, "sock", None) is not None:
            conn.sock.settimeout(timeout)
        return conn

    def _pooled_open(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str],
        timeout: float,
        *,
        cancel_event: threading.Event | None = None,
    ) -> bytes:
        if cancel_event is not None and cancel_event.is_set():
            raise _TransportFailure(TimeoutError("request cancelled"), request_not_sent=True, cancelled=True)
        conn: http.client.HTTPConnection | None = None
        original_send: Any = None
        request_send_started = False
        deadline_expired = threading.Event()
        request_cancelled = threading.Event()
        watchdog_stopped = threading.Event()
        response = None
        try:
            conn = self._connection(timeout)
            original_send = getattr(conn, "send", None)

            deadline = time.monotonic() + max(0.0, timeout)

            def interrupt_connection() -> None:
                # close() alone does not interrupt a concurrent blocking recv.
                active_socket = getattr(conn, "sock", None)
                if active_socket is None and response is not None:
                    active_socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                try:
                    shutdown = getattr(active_socket, "shutdown", None)
                    if callable(shutdown):
                        try:
                            shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                finally:
                    # Optional/custom transports can expose a non-socket sock.
                    # Always retain their close-based cancellation contract.
                    try:
                        conn.close()
                    except Exception:
                        pass

            def close_on_deadline_or_cancel() -> None:
                while not watchdog_stopped.is_set():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        deadline_expired.set()
                        interrupt_connection()
                        return
                    if cancel_event is not None and cancel_event.wait(min(0.05, remaining)):
                        request_cancelled.set()
                        interrupt_connection()
                        return
                    watchdog_stopped.wait(min(0.05, remaining))

            watchdog = threading.Thread(target=close_on_deadline_or_cancel, daemon=True)
            watchdog.start()

            def tracked_send(data: Any) -> None:
                nonlocal request_send_started
                # Connect before marking the request as potentially written. Once sendall
                # starts, an OSError may follow a partial write, so outcome is uncertain.
                if conn.sock is None:
                    # An absent loopback listener must not spend the response
                    # budget on Windows' delayed connection refusal before
                    # autostart can run. Reads retain the caller's deadline.
                    has_connect_timeout = hasattr(conn, "timeout")
                    response_timeout = getattr(conn, "timeout", None)
                    if has_connect_timeout:
                        conn.timeout = min(self.health_timeout, max(0.001, deadline - time.monotonic()))
                    try:
                        conn.connect()
                    except ConnectionRefusedError:
                        raise
                    except (OSError, http.client.HTTPException):
                        raise
                    finally:
                        if has_connect_timeout:
                            conn.timeout = response_timeout
                    settimeout = getattr(conn.sock, "settimeout", None)
                    if callable(settimeout):
                        settimeout(max(0.001, deadline - time.monotonic()))
                request_send_started = True
                return original_send(data)

            if original_send is not None:
                conn.send = tracked_send  # type: ignore[method-assign]
            else:
                # A nonstandard transport has no send hook; fail closed once
                # request() begins because write state cannot be observed.
                request_send_started = True
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            if request_cancelled.is_set():
                raise TimeoutError("request cancelled")
            if deadline_expired.is_set():
                raise TimeoutError("request deadline exceeded")
        except (OSError, http.client.HTTPException) as exc:
            self._drop_connection()
            raise _TransportFailure(
                exc,
                request_not_sent=not request_send_started,
                cancelled=request_cancelled.is_set(),
            ) from exc
        finally:
            watchdog_stopped.set()
            if conn is not None and original_send is not None:
                conn.send = original_send  # type: ignore[method-assign]
        if bool(getattr(response, "will_close", False)):
            self._drop_connection()
        if int(response.status) >= 400:
            response_headers = getattr(response, "headers", {})
            raise HTTPError(f"{self.base_url}{path}", int(response.status), str(response.reason), response_headers, io.BytesIO(raw))
        return raw

    def _open(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str],
        timeout: float,
        *,
        operational_action: str | None = None,
        requires_heavy_work: bool = True,
        cancel_event: threading.Event | None = None,
    ) -> bytes:
        transport = self._inprocess_transport
        if transport is not None:
            if cancel_event is not None and cancel_event.is_set():
                raise _TransportFailure(TimeoutError("request cancelled"), request_not_sent=True, cancelled=True)
            open_options: dict[str, Any] = {
                "operational_action": operational_action,
                "requires_heavy_work": requires_heavy_work,
            }
            if cancel_event is not None:
                try:
                    parameters = inspect.signature(transport.open).parameters.values()
                    supports_cancel = any(
                        parameter.name == "cancel_event"
                        or parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters
                    )
                except (TypeError, ValueError):
                    supports_cancel = False
                if supports_cancel:
                    open_options["cancel_event"] = cancel_event
            response = transport.open(method, path, body, headers, timeout, **open_options)
            if cancel_event is not None and cancel_event.is_set():
                raise _TransportFailure(
                    TimeoutError("request cancelled"), request_not_sent=False, cancelled=True
                )
            return response
        if cancel_event is not None:
            return self._pooled_open(method, path, body, headers, timeout, cancel_event=cancel_event)
        return self._pooled_open(method, path, body, headers, timeout)
    @staticmethod
    def _error_response(exc: HTTPError, request_id: str) -> dict[str, Any]:
        try:
            parsed = json.loads(exc.read().decode("utf-8"))
            if isinstance(parsed, dict):
                parsed.setdefault("request_id", request_id)
                return normalize_transport_error(exc.code, parsed)
            return normalize_transport_error(
                exc.code, {"error": str(parsed), "request_id": request_id}
            )
        except Exception:
            return normalize_transport_error(
                exc.code,
                {"error": f"HTTP {exc.code}: {exc.reason}", "request_id": request_id},
            )
        finally:
            try:
                exc.close()
            except Exception:
                pass

    @staticmethod
    def _invalid_json_response(request_id: str, *, outcome_unknown: bool = False) -> dict[str, Any]:
        result = {
            "success": False,
            "error": "invalid JSON response",
            "status_code": 502,
            "request_id": request_id,
        }
        if outcome_unknown:
            result.update({"outcome_unknown": True, "retryable": False, "terminal": True})
        else:
            result.update({"retryable": True, "terminal": False})
        return result

    @staticmethod
    def _uncertain_response(request_id: str, *, retried: bool = False) -> dict[str, Any]:
        result = {
            "success": False,
            "error": "request outcome is unknown after a transport failure",
            "outcome_unknown": True,
            "terminal": True,
            "retryable": False,
            "request_id": request_id,
        }
        if retried:
            result["retried"] = True
        return result

    @staticmethod
    def _cancelled_response(request_id: str, *, request_not_sent: bool) -> dict[str, Any]:
        result: dict[str, Any] = {
            "success": False,
            "error": "request cancelled",
            "cancelled": True,
            "terminal": True,
            "retryable": False,
            "request_id": request_id,
        }
        if request_not_sent:
            result.update({"request_not_sent": True, "outcome_unknown": False})
        else:
            result["outcome_unknown"] = True
        return result

    @staticmethod
    def _transport_failure_response(
        request_id: str,
        *failures: BaseException,
        retried: bool = False,
        prior_send_possible: bool = False,
    ) -> dict[str, Any]:
        if not prior_send_possible and failures and all(
            (isinstance(exc, _TransportFailure) and exc.request_not_sent)
            or bool(getattr(exc, "request_not_sent", False))
            for exc in failures
        ):
            result = {
                "success": False,
                "error": "request was not sent because transport failed before write",
                "request_not_sent": True,
                "outcome_unknown": False,
                "terminal": True,
                "retryable": False,
                "request_id": request_id,
            }
            if retried:
                result["retried"] = True
            return result
        return HubClient._uncertain_response(request_id, retried=retried)

    def _singleflight(
        self,
        key: str,
        timeout: float,
        execute: Any,
        *,
        request_id: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        with self._flight_lock:
            flight = self._flights.get(key)
            if flight is None:
                flight = {"event": threading.Event(), "result": None, "error": None, "request_id": request_id}
                self._flights[key] = flight
                owner = True
            else:
                owner = False
        if owner:
            try:
                flight["result"] = execute()
            except BaseException as exc:
                flight["error"] = exc
            finally:
                with self._flight_lock:
                    self._flights.pop(key, None)
                flight["event"].set()
            if flight["error"] is not None:
                raise flight["error"]
            return flight["result"]
        deadline = time.monotonic() + timeout
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise _SingleflightCancelled("coalesced hub request cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                error = TimeoutError("coalesced hub request timed out")
                owner_request_id = flight.get("request_id", request_id)
                if owner_request_id is not None:
                    error.request_id = owner_request_id
                raise error
            if flight["event"].wait(min(0.05, remaining)):
                break
        if flight["error"] is not None:
            raise flight["error"]
        result = copy.deepcopy(flight["result"])
        if isinstance(result, dict):
            result["coalesced"] = True
            if flight.get("request_id") is not None:
                result.setdefault("request_id", flight["request_id"])
        return result

    def _online(self, timeout: float | None = None) -> bool:
        try:
            health_timeout = self.health_timeout if timeout is None else max(0.0, float(timeout))
            if health_timeout <= 0:
                return False
            headers = {"X-LocalAI-Token": self.api_token} if self.api_token else {}
            with urlopen(Request(f"{self.base_url}/ready", headers=headers), timeout=health_timeout) as response:
                try:
                    response.read()
                except Exception:
                    pass
                return response.status == 200
        except HTTPError as exc:
            # Readiness 503 means the app is still initializing; liveness alone
            # must not let MCP requests race partially initialized services.
            with exc:
                return False
        except Exception:
            return False

    def ensure_server(self, timeout: float | None = None) -> bool:
        budget = self.startup_wait if timeout is None else min(self.startup_wait, max(0.0, float(timeout)))
        deadline = time.monotonic() + budget

        def remaining() -> float:
            return max(0.0, deadline - time.monotonic())

        def probe_timeout() -> float:
            return min(self.health_timeout, remaining())

        def wait_until_ready() -> bool:
            while remaining() > 0:
                if self._online(probe_timeout()):
                    return True
                time.sleep(min(self.startup_poll, remaining()))
            return self._online(probe_timeout())

        # A failed first health check must not consume the caller's entire short
        # autostart budget before we get a chance to acquire the startup lock.
        initial_probe_timeout = min(self.health_timeout, budget * 0.25)
        if initial_probe_timeout > 0 and self._online(initial_probe_timeout):
            return True
        state_dir = Path(self.config["server"]["state_dir"])
        try:
            from .operational_mode import load_operational_mode

            operational_mode = load_operational_mode(state_dir)
        except Exception:
            return False
        if getattr(operational_mode, "mode", None) != "active" or getattr(operational_mode, "degraded", True):
            return False
        if (state_dir / "service.managed").exists():
            return False
        config_path = self.config["_config_path"]
        state_dir.mkdir(parents=True, exist_ok=True)
        if bool(self.config.get("headless", {}).get("respect_disabled_marker", True)) and (state_dir / "service.disabled").exists():
            return False
        def live_supervisor() -> bool:
            for supervisor_marker in (state_dir / "supervisor.pid", state_dir / "supervisor.lock"):
                try:
                    supervisor_pid = int(supervisor_marker.read_text(encoding="utf-8").strip() or 0)
                except (OSError, ValueError):
                    continue
                if pid_alive(supervisor_pid):
                    return True
            return False

        # A live supervisor owns startup, even during its short interval before
        # publishing supervisor.pid. Check both supervisor markers before autostart.
        if live_supervisor():
            return wait_until_ready()
        # A listener can be alive before its health endpoint is ready (cold model/
        # index startup). Starting another hub in that gap creates duplicate pythonw
        # trees and competing supervisors; let the caller retry its request instead.
        port = int(self.config.get("server", {}).get("port", 11435))
        if find_listening_pid(port):
            return wait_until_ready()
        lock_path = state_dir / "hub.start.lock"
        owner = False
        owner_lock = None

        # The OS lock protects startup while held. After a failed bounded attempt,
        # its PID marker blocks duplicates only for the configured retry cooldown.
        for _ in range(2):
            try:
                owner_lock = _acquire_start_lock(lock_path, self.start_lock_stale)
            except OSError:
                continue
            if owner_lock is not None:
                owner = True
                break

            lock_deadline = min(deadline, time.monotonic() + self.startup_wait)
            while time.monotonic() < lock_deadline:
                if self._online(probe_timeout()):
                    return True
                try:
                    owner_lock = _acquire_start_lock(lock_path, self.start_lock_stale)
                except OSError:
                    owner_lock = None
                if owner_lock is not None:
                    owner = True
                    break
                time.sleep(min(self.startup_poll, max(0.0, lock_deadline - time.monotonic())))
            if owner:
                break
            return self._online(probe_timeout())

        if not owner:
            return self._online(probe_timeout())
        ready = False
        keep_lock = False
        try:
            if self._online(probe_timeout()):
                return True
            if remaining() <= 0:
                return False
            if bool(self.config.get("headless", {}).get("respect_disabled_marker", True)) and (state_dir / "service.disabled").exists():
                return False
            if live_supervisor() or find_listening_pid(port):
                return wait_until_ready()
            if (state_dir / "service.managed").exists():
                return False
            env = os.environ.copy()
            env["LOCAL_AI_CONFIG"] = config_path
            src_dir = str(Path(__file__).resolve().parents[1])
            env["PYTHONPATH"] = src_dir + (os.pathsep + env["PYTHONPATH"] if "PYTHONPATH" in env else "")
            service_script = Path(__file__).resolve().parents[2] / "tools" / "service.py"
            launch_timeout = remaining()
            if launch_timeout <= 0:
                return False
            process: subprocess.Popen[Any] | None = None
            if hasattr(subprocess, "run") and subprocess.run is not _ORIGINAL_SUBPROCESS_RUN:
                if not service_script.is_file():
                    return False
                try:
                    from .process_utils import hidden_run_kwargs
                    kwargs = hidden_run_kwargs()
                except Exception:
                    if sys.platform == "win32":
                        return False
                    kwargs = {}
                try:
                    completed = subprocess.run(
                        [sys.executable, str(service_script), "start"],
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=launch_timeout,
                        **kwargs,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    ready = wait_until_ready()
                    keep_lock = not ready
                    return ready
                if completed.returncode != 0:
                    ready = wait_until_ready()
                    keep_lock = not ready
                    return ready
            else:
                py_exe = sys.executable
                if sys.platform == "win32":
                    pyw_candidate = Path(sys.executable).parent / "pythonw.exe"
                    if pyw_candidate.exists():
                        py_exe = str(pyw_candidate)
                cmd = [py_exe, "-m", "local_ai_hub.supervisor", "--config", config_path]
                try:
                    from .process_utils import hidden_run_kwargs
                    popen_kwargs = hidden_run_kwargs(detached=True)
                except Exception:
                    if sys.platform == "win32":
                        return False
                    popen_kwargs = {}
                if sys.platform != "win32":
                    popen_kwargs["start_new_session"] = True
                try:
                    starter = popen_managed if sys.platform == "win32" else subprocess.Popen
                    process = starter(
                        cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **popen_kwargs
                    )
                    if sys.platform == "win32" and not retain_process_job_in_child(process):
                        terminate_tree(process.pid, process_handle=process, grace_seconds=1.0)
                        try:
                            process.wait(timeout=1.0)
                        except (OSError, subprocess.TimeoutExpired):
                            _retain_detached_child(process)
                        return False
                except OSError:
                    return False
                if sys.platform != "win32":
                    process._local_ai_process_identity = process_identity(process.pid)
                _retain_detached_child(process)
            while remaining() > 0:
                if self._online(probe_timeout()):
                    ready = True
                    return True
                time.sleep(min(self.startup_poll, remaining()))
            ready = self._online(probe_timeout())
            if (
                not ready
                and process is not None
                and process.poll() is None
                and not find_listening_pid(port)
            ):
                # Reap only the child created by this attempt. A listener may
                # belong to a Hub that is still warming, so never kill then.
                try:
                    terminate_tree(
                        process.pid,
                        process_group=process.pid,
                        process_handle=process,
                        expected_identity=getattr(
                            process, "_local_ai_process_identity", None
                        ),
                        grace_seconds=1.0,
                    )
                except OSError:
                    pass
                try:
                    process.wait(timeout=1.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            keep_lock = not ready
            return ready
        finally:
            if owner_lock is not None:
                if not keep_lock:
                    try:
                        owner_lock.seek(0)
                        owner_lock.truncate()
                        owner_lock.flush()
                    except OSError:
                        pass
                owner_lock.close()

    @staticmethod
    def _terminal_preflight(path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Reject deterministic client mistakes before opening a loopback socket."""
        if path == "/api/code/symbol" and not str(payload.get("symbol", payload.get("query", ""))).strip():
            return {"success": False, "terminal": True, "retryable": False, "preflight": True, "error": "symbol is required"}
        if path in {"/api/review/diff", "/api/repo/impact"}:
            root = str(payload.get("root", "")).strip()
            if root:
                try:
                    candidate = Path(root).expanduser().resolve(strict=False)
                    if candidate.is_dir() and not (candidate / ".git").exists():
                        return {
                            "success": False, "terminal": True, "retryable": False, "preflight": True,
                            "error": "operation requires a Git repository; use deterministic/code-index review for this root",
                        }
                except OSError:
                    pass
        return None

    @staticmethod
    def _valid_request_id(request_id: Any) -> bool:
        return (
            isinstance(request_id, str)
            and 1 <= len(request_id) <= 128
            and request_id.isascii()
            and all(0x21 <= ord(char) <= 0x7E for char in request_id)
        )


    @staticmethod
    def _identity_preflight(error: str, error_code: str) -> dict[str, Any]:
        return {
            "success": False,
            "error": error,
            "error_code": error_code,
            "terminal": True,
            "retryable": False,
            "preflight": True,
            "request_not_sent": True,
            "operation_not_started": True,
        }





    def _request_scope(
        self, path: str, payload: dict[str, Any] | None,
        *, query: dict[str, list[str]] | None = None,
    ) -> dict[str, Any] | None:
        """Reject retired identity inputs and preserve repository confinement."""
        data = payload if isinstance(payload, dict) else {}
        query_values = query if query is not None else parse_qs(urlsplit(path).query, keep_blank_values=True)
        try:
            reject_retired_tenancy_fields(data)
            reject_retired_tenancy_fields(query_values)
            route = urlsplit(path).path.lower()
            if route == "/api/agent-state/incidents":
                if query is None:
                    authorized_repository_root(self.config, data.get("root"))
                else:
                    for root in query_values.get("root", []):
                        authorized_repository_root(self.config, root)
                return None
            if route not in {"/api/agent-state/tasks", "/api/agent-state/memory"}:
                return None
            if query is not None:
                roots = list(query_values.get("root", []))
                scopes = query_values.get("scope", [])
                containers = [query_values]
            else:
                record = data.get("record") if isinstance(data.get("record"), dict) else {}
                containers = [data, record]
                for container in tuple(containers):
                    provenance = container.get("provenance")
                    if isinstance(provenance, dict):
                        containers.append(provenance)
                roots = [item["root"] for item in containers if "root" in item]
                scopes = [item["scope"] for item in containers if "scope" in item]
                if route == "/api/agent-state/tasks":
                    if "root" not in data:
                        raise RepositoryScopeError("root is required for tasks", "root_required")
                    context = data.get("context")
                    if isinstance(context, dict):
                        for name in ("repository_id", "clone_id", "worktree_id", "branch", "task_id", "session_id"):
                            if name in context and (
                                not isinstance(context[name], str)
                                or context[name] != context[name].strip()
                                or "\x00" in context[name]
                            ):
                                raise RepositoryScopeError(
                                    f"context.{name} must be a canonical string", "invalid_identity"
                                )
                    if "repo_root" in data:
                        roots.append(data["repo_root"])
            has_identity = any(
                item.get(name) for item in containers
                for name in ("task_id", "repository_id", "clone_id", "worktree_id", "branch")
            )
            allowed_scopes = {"", "global", "repository", "clone", "worktree", "branch", "task", "session"}
            if any(not isinstance(value, str) or value not in allowed_scopes for value in scopes):
                raise RepositoryScopeError("scope must be a canonical scope value", "invalid_scope")
            explicit_scopes = {value for value in scopes if value}
            if len(explicit_scopes) > 1:
                raise RepositoryScopeError("scope identity mismatch", "invalid_scope")
            scope = next(iter(explicit_scopes), "")
            if not roots and (
                route == "/api/agent-state/tasks" or has_identity
                or scope in {"repository", "clone", "worktree", "branch", "task"}
            ):
                raise RepositoryScopeError("root is required for repository or task access", "root_required")
            canonical = [authorized_repository_root(self.config, root) for root in roots]
            if canonical and any(root != canonical[0] for root in canonical[1:]):
                raise RepositoryScopeError("root identity mismatch", "root_not_allowed", 403)
        except RepositoryScopeError as exc:
            return self._identity_preflight(str(exc), exc.code)
        return None


    def request(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
        replay_safe: bool = False,
        request_id: str | None = None,
        operational_action: str | None = None,
        requires_heavy_work: bool = True,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        if cancel_event is None:
            cancel_event = CURRENT_REQUEST_CANCEL_EVENT.get()
        explicit_request_id = request_id is not None
        if request_id is not None and not self._valid_request_id(request_id):
            return {
                "success": False,
                "error": "request_id must be 1-128 visible ASCII characters without whitespace",
                "terminal": True,
                "retryable": False,
                "preflight": True,
            }
        timeout = min(self.max_request_timeout, max(0.2, float(timeout)))
        clean_payload = payload or {}
        identity_error = self._request_scope(path, clean_payload)
        if identity_error is not None:
            return identity_error
        preflight = self._terminal_preflight(path, clean_payload)
        if preflight is not None:
            return preflight
        # Private accounting is best effort; metadata alone must not start a Hub.
        allow_start = self.auto_start and urlsplit(path).path != "/api/telemetry/tool-accounting"
        body = json_dumps(clean_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")
        request_id = request_id if request_id is not None else f"req_{uuid.uuid4().hex[:12]}"
        if cancel_event is not None and cancel_event.is_set():
            return self._cancelled_response(request_id, request_not_sent=True)

        def once(attempt_timeout: float) -> dict[str, Any]:
            headers = {
                "Content-Type": "application/json",
                "X-LocalAI-Agent": self.agent, "X-LocalAI-Request-ID": request_id,
            }
            if self.api_token:
                headers["X-LocalAI-Token"] = self.api_token
            try:
                open_options = {
                    "operational_action": operational_action,
                    "requires_heavy_work": requires_heavy_work,
                }
                if cancel_event is not None:
                    open_options["cancel_event"] = cancel_event
                result = json.loads(
                    self._open(
                        "POST",
                        path,
                        body,
                        headers,
                        attempt_timeout,
                        **open_options,
                    ).decode("utf-8")
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._invalid_json_response(request_id, outcome_unknown=not replay_safe)
            if not isinstance(result, dict):
                return self._invalid_json_response(request_id, outcome_unknown=not replay_safe)
            return result

        def execute() -> dict[str, Any]:
            duplicate_deadline = time.monotonic() + timeout
            server_reported_in_progress = False

            def request_until_terminal() -> dict[str, Any]:
                nonlocal server_reported_in_progress
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        return self._cancelled_response(
                            request_id,
                            request_not_sent=not server_reported_in_progress,
                        )
                    remaining = duplicate_deadline - time.monotonic()
                    if remaining <= 0:
                        return {
                            "success": False,
                            "error": "retry deadline exceeded while request remains in progress",
                            "retryable": True,
                            "in_progress": True,
                            "retry_timeout": True,
                            "request_id": request_id,
                        }
                    try:
                        return once(min(timeout, remaining))
                    except HTTPError as exc:
                        result = self._error_response(exc, request_id)
                        if not (
                            replay_safe
                            and result.get("in_progress")
                            and result.get("retryable")
                        ):
                            return result
                        server_reported_in_progress = True
                        remaining = duplicate_deadline - time.monotonic()
                        if remaining <= 0:
                            result["retry_timeout"] = True
                            return result
                        retry_after = max(0.01, float(result.get("retry_after_seconds", 0.1) or 0.1))
                        delay = min(retry_after, remaining)
                        if cancel_event is not None:
                            if cancel_event.wait(delay):
                                return self._cancelled_response(request_id, request_not_sent=False)
                        else:
                            time.sleep(delay)

            try:
                return request_until_terminal()
            except HTTPError as exc:
                return self._error_response(exc, request_id)
            except (URLError, OSError, http.client.HTTPException, AttributeError) as exc:
                self._drop_connection()
                if getattr(exc, "cancelled", False):
                    return self._cancelled_response(request_id, request_not_sent=bool(getattr(exc, "request_not_sent", False)) and not server_reported_in_progress)
                pre_send_refusal = bool(getattr(exc, "request_not_sent", False))
                if replay_safe or (allow_start and pre_send_refusal):
                    remaining = duplicate_deadline - time.monotonic()
                    try:
                        if self._inprocess_transport is not None:
                            server_ready = bool(replay_safe or pre_send_refusal)
                        else:
                            server_ready = self.ensure_server(timeout=remaining) if allow_start and remaining > 0 else not allow_start
                    except Exception:
                        server_ready = False
                    if server_ready:
                        if cancel_event is not None and cancel_event.is_set():
                            return self._cancelled_response(request_id, request_not_sent=pre_send_refusal and not server_reported_in_progress)
                        remaining = duplicate_deadline - time.monotonic()
                        if remaining <= 0:
                            return self._transport_failure_response(
                                request_id,
                                exc,
                                prior_send_possible=server_reported_in_progress or not pre_send_refusal,
                            )
                        try:
                            retried_result = request_until_terminal()
                            if retried_result.get("outcome_unknown"):
                                retried_result["retried"] = True
                            return retried_result
                        except HTTPError as retry_http:
                            return self._error_response(retry_http, request_id)
                        except (URLError, OSError, http.client.HTTPException) as retry_exc:
                            self._drop_connection()
                            if getattr(retry_exc, "cancelled", False):
                                return self._cancelled_response(request_id, request_not_sent=bool(getattr(retry_exc, "request_not_sent", False)) and not server_reported_in_progress)
                            return self._transport_failure_response(
                                request_id,
                                exc,
                                retry_exc,
                                retried=True,
                                prior_send_possible=server_reported_in_progress or not pre_send_refusal,
                            )
                        except Exception:
                            return self._uncertain_response(request_id, retried=True)
                return self._transport_failure_response(
                    request_id, exc, prior_send_possible=server_reported_in_progress
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._invalid_json_response(request_id, outcome_unknown=not replay_safe)
            except Exception:
                return self._uncertain_response(request_id)

        if not replay_safe:
            return execute()

        key = f"POST|{self.agent}|{path}|{body.decode('utf-8')}"
        if explicit_request_id:
            key += f"|explicit-request-id|{request_id}"
        if cancel_event is not None:
            key += f"|cancel-event|{id(cancel_event)}"
        try:
            return self._singleflight(
                key, timeout, execute, request_id=request_id, cancel_event=cancel_event
            )
        except _SingleflightCancelled:
            return self._cancelled_response(request_id, request_not_sent=False)
        except TimeoutError as exc:
            return {
                "success": False,
                "error": "coalesced request timed out before result was available",
                "retry_timeout": True,
                "coalesced": True,
                "outcome_unknown": True,
                "in_progress": True,
                "retryable": True,
                "terminal": False,
                "request_id": getattr(exc, "request_id", request_id),
            }

    def get(
        self,
        path: str,
        timeout: float = 15.0,
        *,
        operational_action: str | None = None,
        requires_heavy_work: bool = True,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        query = parse_qs(urlsplit(path).query, keep_blank_values=True)
        identity_error = self._request_scope(path, None, query=query)
        if identity_error is not None:
            return identity_error
        timeout = min(self.max_request_timeout, max(0.2, float(timeout)))
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        if cancel_event is not None and cancel_event.is_set():
            return self._cancelled_response(request_id, request_not_sent=True)
        headers = {
            "X-LocalAI-Agent": self.agent,
            "X-LocalAI-Request-ID": request_id,
        }
        if self.api_token:
            headers["X-LocalAI-Token"] = self.api_token

        def once(attempt_timeout: float) -> dict[str, Any]:
            try:
                open_options = {
                    "operational_action": operational_action,
                    "requires_heavy_work": requires_heavy_work,
                }
                if cancel_event is not None:
                    open_options["cancel_event"] = cancel_event
                result = json.loads(
                    self._open(
                        "GET",
                        path,
                        None,
                        headers,
                        attempt_timeout,
                        **open_options,
                    ).decode("utf-8")
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._invalid_json_response(request_id, outcome_unknown=False)
            return result if isinstance(result, dict) else self._invalid_json_response(request_id, outcome_unknown=False)

        def once_ready(attempt_timeout: float, deadline: float) -> dict[str, Any]:
            result = once(attempt_timeout)
            for _ in range(3):
                if not result.get("snapshot_warming"):
                    return result
                if cancel_event is not None and cancel_event.is_set():
                    return self._cancelled_response(request_id, request_not_sent=False)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return result
                retry_after_ms = result.get("retry_after_ms", 100)
                try:
                    delay = min(0.25, max(0.01, float(retry_after_ms) / 1000.0))
                except (TypeError, ValueError, OverflowError):
                    delay = 0.1
                delay = min(delay, remaining)
                if cancel_event is not None:
                    if cancel_event.wait(delay) or cancel_event.is_set():
                        return self._cancelled_response(request_id, request_not_sent=False)
                else:
                    time.sleep(delay)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return result
                if cancel_event is not None and cancel_event.is_set():
                    return self._cancelled_response(request_id, request_not_sent=False)
                result = once(remaining)
            return result

        def execute() -> dict[str, Any]:
            deadline = time.monotonic() + timeout
            try:
                return once_ready(timeout, deadline)
            except HTTPError as exc:
                return self._error_response(exc, request_id)
            except (URLError, OSError, http.client.HTTPException, AttributeError) as exc:
                self._drop_connection()
                if getattr(exc, "cancelled", False):
                    return self._cancelled_response(
                        request_id,
                        request_not_sent=bool(getattr(exc, "request_not_sent", False)),
                    )
                if cancel_event is not None and cancel_event.is_set():
                    return self._cancelled_response(
                        request_id,
                        request_not_sent=bool(getattr(exc, "request_not_sent", False)),
                    )
                remaining = deadline - time.monotonic()
                if self._inprocess_transport is not None:
                    server_ready = remaining > 0
                else:
                    server_ready = self.ensure_server(timeout=remaining) if self.auto_start and remaining > 0 else not self.auto_start
                if server_ready:
                    for attempt in range(4):
                        if cancel_event is not None and cancel_event.is_set():
                            return self._cancelled_response(
                                request_id,
                                request_not_sent=bool(getattr(exc, "request_not_sent", False)),
                            )
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        try:
                            return once_ready(remaining, deadline)
                        except HTTPError as retry_http:
                            return self._error_response(retry_http, request_id)
                        except (URLError, OSError, http.client.HTTPException) as transient_exc:
                            self._drop_connection()
                            if getattr(transient_exc, "cancelled", False):
                                return self._cancelled_response(
                                    request_id,
                                    request_not_sent=bool(getattr(transient_exc, "request_not_sent", False)),
                                )
                            if attempt < 3 and self.auto_start:
                                remaining = deadline - time.monotonic()
                                if remaining > 0:
                                    try:
                                        self.ensure_server(timeout=remaining)
                                    except Exception:
                                        pass
                                    remaining = deadline - time.monotonic()
                                    if remaining > 0:
                                        delay = min(0.05, remaining)
                                        request_not_sent = bool(
                                            getattr(transient_exc, "request_not_sent", False)
                                        )
                                        if cancel_event is not None:
                                            if cancel_event.wait(delay) or cancel_event.is_set():
                                                return self._cancelled_response(
                                                    request_id, request_not_sent=request_not_sent
                                                )
                                        else:
                                            time.sleep(delay)
                        except Exception:
                            return self._uncertain_response(request_id, retried=True)
                unavailable = {
                    "success": False,
                    "error": "read request unavailable after bounded transport retries",
                    "status_code": 503,
                    "retryable": True,
                    "terminal": False,
                    "request_id": request_id,
                }
                if server_ready:
                    unavailable["retried"] = True
                if bool(getattr(exc, "request_not_sent", False)):
                    unavailable.update({"request_not_sent": True, "outcome_unknown": False})
                return unavailable
            except Exception:
                return self._uncertain_response(request_id)

        key = f"GET|{self.agent}|{path}"
        if cancel_event is not None:
            key += f"|cancel-event|{id(cancel_event)}"
        try:
            return self._singleflight(
                key, timeout, execute, request_id=request_id, cancel_event=cancel_event
            )
        except _SingleflightCancelled:
            return self._cancelled_response(request_id, request_not_sent=False)
        except TimeoutError as exc:
            return {
                "success": False,
                "error": "coalesced request timed out before result was available",
                "retry_timeout": True,
                "coalesced": True,
                "outcome_unknown": True,
                "in_progress": True,
                "retryable": True,
                "terminal": False,
                "request_id": getattr(exc, "request_id", request_id),
            }

    @staticmethod
    def _post_replay_safe(path: str, payload: dict[str, Any] | None) -> bool:
        """Fail closed: only known read-only or explicitly idempotent POSTs replay."""
        path = path.lower().split("?", 1)[0]
        if path == "/api/async-jobs":
            action = str((payload or {}).get("action", "")).strip().lower().replace("-", "_")
            if action in {"status", "wait", "result", "cancel"}:
                return True
            request_id = (payload or {}).get("request_id")
            return action == "submit" and bool(str(request_id or "").strip())
        if path in {
            "/api/search",
            "/api/memory/get",
            "/api/memory/search",
            "/api/repo/circular_dependencies",
            "/api/repo/generate_types",
            "/api/repo/complexity",
            "/api/repo/api_spec",
            "/api/repo/dependency_slice",
            "/api/repo/migration_drift",
            "/api/repo/package_audit",
            "/api/repo/generate_tests_for_diff",
            "/api/repo/cross_repo_contract",
            "/api/repo/hotspots",
            "/api/git/diff",
            "/api/git/history_search",
            "/api/agent-state/context",
        }:
            return True
        action = str((payload or {}).get("action", "")).strip().lower()
        read_actions = {
            "/api/agent-state/tasks": {"get", "list", "count"},
            "/api/agent-state/memory": {"get", "find"},
            "/api/agent-state/blackboard": {"get", "list"},
            "/api/agent-state/incidents": {"find"},
            "/api/agent-state/verification": {"completion"},
        }
        return action in read_actions.get(path, set())

    def post(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout: float = 360.0,
        *,
        request_id: str | None = None,
        path_hints: Sequence[PathHint | Mapping[str, str]] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        clean_payload = dict(payload or {})
        route = path.lower().split("?", 1)[0]
        if route == "/api/search":
            explicit_path = isinstance(clean_payload.get("path"), str) and bool(clean_payload["path"].strip())
            if explicit_path:
                clean_payload.pop("path_hints", None)
            else:
                raw_path_hints = path_hints if path_hints is not None else clean_payload.get("path_hints")
                if raw_path_hints is not None:
                    records = []
                    if isinstance(raw_path_hints, Sequence) and not isinstance(
                        raw_path_hints, (str, bytes, bytearray)
                    ):
                        for hint in raw_path_hints[:64]:
                            if isinstance(hint, Mapping):
                                record = dict(hint)
                            else:
                                record = {
                                    key: getattr(hint, key)
                                    for key in _PATH_HINT_FIELDS
                                    if hasattr(hint, key) and getattr(hint, key) is not None
                                }
                            if any(not isinstance(record.get(key), str) for key in _PATH_HINT_REQUIRED_FIELDS):
                                continue
                            if any(key in record and not isinstance(record[key], str) for key in _PATH_HINT_FIELDS):
                                continue
                            records.append({key: value for key, value in record.items() if key in _PATH_HINT_FIELDS})
                    clean_payload["path_hints"] = records
        else:
            clean_payload.pop("path_hints", None)
        replay_safe = self._post_replay_safe(path, clean_payload)
        if request_id is None:
            return self.request(
                path,
                clean_payload,
                timeout=timeout,
                replay_safe=replay_safe,
                cancel_event=cancel_event,
            )
        return self.request(
            path,
            clean_payload,
            timeout=timeout,
            replay_safe=replay_safe,
            request_id=request_id,
            cancel_event=cancel_event,
        )

    def status(self, detail: str = "brief", scope: str = "process", *,
               min_duration_ms: int = 0, trace_action: str = "") -> dict[str, Any]:
        if not isinstance(min_duration_ms, int) or isinstance(min_duration_ms, bool) or not 0 <= min_duration_ms <= 86_400_000:
            return {"success": False, "error": "min_duration_ms must be an integer between 0 and 86400000", "status_code": 400, "terminal": True, "retryable": False}
        if not isinstance(trace_action, str) or len(trace_action) > 64:
            return {"success": False, "error": "trace_action must be a string of at most 64 characters", "status_code": 400, "terminal": True, "retryable": False}
        if detail == "traces":
            query = urlencode({"min_duration_ms": min_duration_ms, "action": trace_action.strip(), "limit": 20})
            return self.get(f"/api/debug-traces?{query}")
        if min_duration_ms or trace_action:
            return {"success": False, "error": "trace filters require detail=traces", "status_code": 400, "terminal": True, "retryable": False}
        if detail == "agent_state":
            return self.get("/api/status?detail=agent_state")
        return self.get(f"/api/live/status?light=1&scope={scope}&detail={detail}")

    def callers(self, root: str, symbol: str, limit: int = 50) -> dict[str, Any]:
        return self.post("/api/repo/callers", {"root": root, "symbol": symbol, "limit": limit})

    def context_pack(
        self,
        root: str,
        query: str,
        max_tokens: int = 4200,
        mode: str = "adaptive",
        **options: Any,
    ) -> dict[str, Any]:
        if not isinstance(mode, str) or mode not in {"adaptive", "full", "fast"}:
            return {
                "success": False,
                "status_code": 400,
                "terminal": True,
                "retryable": False,
                "error": "context mode must be adaptive, full or fast",
            }
        mode = mode.strip().lower()
        payload = dict(options)
        payload.update({"root": root, "query": query, "max_tokens": max_tokens, "mode": mode})
        return self.post("/api/context/pack", payload)

    def coord(
        self,
        action: str,
        *,
        response_budget_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if isinstance(action, str) and action.startswith("memo_"):
            return {
                "success": False, "status_code": 400, "terminal": True, "retryable": False,
                "error": f"retired coord action '{action}'",
            }
        if not isinstance(action, str) or action not in operation_actions("local_ai_coord"):
            return {
                "success": False, "status_code": 400, "terminal": True, "retryable": False,
                "error": f"unknown coord action '{action}'",
            }
        act = action
        try:
            reject_retired_tenancy_fields(kwargs)
        except RepositoryScopeError as exc:
            return self._identity_preflight(str(exc), exc.code)
        if act in {"incident_decision", "negative_knowledge_record", "negative_knowledge_find"}:
            try:
                reject_retired_tenancy_fields(kwargs)
                record = kwargs.get("record")
                if isinstance(record, dict) and "root" in record:
                    raise RepositoryScopeError("record cannot override root", "invalid_incident_root")
            except RepositoryScopeError as exc:
                return self._identity_preflight(str(exc), exc.code)
        if act in {"context_compile", "verify_receipt", "verify_completion", "verify_export"}:
            validation_error = validate_operation_arguments("local_ai_coord", act, dict(kwargs))
            if validation_error:
                return {
                    "success": False, "status_code": 400, "terminal": True, "retryable": False,
                    "error": validation_error,
                }
        if act in {"ask", "answer"}:
            payload = {
                "action": act,
                "root": kwargs.get("root", "."),
                "session_id": kwargs.get("session_id", ""),
                "task_id": kwargs.get("task_id", ""),
                "question_id": kwargs.get("question_id", ""),
                "question": kwargs.get("question", ""),
                "answer": kwargs.get("answer", ""),
            }
            if response_budget_tokens is not None:
                payload["response_budget_tokens"] = response_budget_tokens
            return self.post("/api/agent-state/tasks", payload)
        if act.startswith("task_"):
            task_action = act.replace("task_", "")
            payload = {**kwargs, "action": task_action}
            if response_budget_tokens is not None:
                payload["response_budget_tokens"] = response_budget_tokens
            return self.post("/api/agent-state/tasks", payload)
        if act.startswith("memory_") and act != "memory_reap":
            mem_action = act.replace("memory_", "")
            payload = dict(kwargs)
            # The server resolves repository identity from the authorized root.
            for identity_field in ("repository_id", "coordination_id"):
                payload.pop(identity_field, None)
            record = payload.get("record")
            repository_scope = payload.get("scope") == "repository"
            if repository_scope:
                payload.pop("scope_id", None)
            if isinstance(record, dict):
                record = dict(record)
                for identity_field in ("repository_id", "coordination_id"):
                    record.pop(identity_field, None)
                if repository_scope or record.get("scope") == "repository":
                    record.pop("scope_id", None)
                payload["record"] = record
            payload["action"] = mem_action
            return self.post("/api/agent-state/memory", payload)
        if act in {"incident_decision", "negative_knowledge_record", "negative_knowledge_find"}:
            validation_error = validate_operation_arguments(
                "local_ai_coord",
                act,
                dict(kwargs),
            )
            if validation_error:
                return {
                    "success": False,
                    "status_code": 400,
                    "terminal": True,
                    "retryable": False,
                    "error": validation_error,
                }
        if act == "incident_decision":
            payload = {
                "action": "decision",
                "fingerprint": kwargs.get("fingerprint"),
                "state_revision": kwargs.get("state_revision", ""),
            }
            if "root" in kwargs:
                payload["root"] = kwargs["root"]
            return self.post("/api/agent-state/incidents", payload)
        if act == "context_compile":
            payload = dict(kwargs)
            max_tokens = payload.pop("max_tokens", 4000)
            paths = payload.pop("paths", [])
            payload.update({
                "action": "compile",
                "token_budget": max_tokens,
                "changed_paths": paths,
                "root": kwargs.get("root", "."),
            })
            return self.post("/api/agent-state/context", {
                **payload,
            })
        if act == "verify_receipt":
            return self.post("/api/agent-state/verification", {
                "action": "receipt",
                "receipt": kwargs["receipt"],
                "root": kwargs.get("root", "."),
            })
        if act == "verify_completion":
            payload = {
                "action": "completion",
                "task_id": kwargs["task_id"],
                "root": kwargs.get("root", "."),
            }
            if "repository_revision" in kwargs:
                payload["repository_revision"] = kwargs["repository_revision"]
            return self.post("/api/agent-state/verification", payload)
        if act == "verify_export":
            return self.post("/api/agent-state/verification", {
                "action": "export",
                "task_id": kwargs["task_id"],
                "root": kwargs.get("root", "."),
                "format": kwargs.get("format", "markdown"),
            })
        if act == "negative_knowledge_record":
            record = kwargs.get("record")
            if not isinstance(record, dict):
                return {"success": False, "terminal": True, "retryable": False, "error": "record must be an object"}
            return self.post("/api/agent-state/incidents", {
                **record,
                "action": "record",
                "root": kwargs.get("root"),
            })
        if act == "negative_knowledge_find":
            return self.post("/api/agent-state/incidents", {
                "action": "find",
                "query": kwargs.get("query"),
                "limit": kwargs.get("limit", 100),
                "root": kwargs.get("root"),
            })
        if act in ("claim", "claim_batch"):
            if "value" in kwargs:
                raise ValueError("lease claim accepts purpose; value is not an alias")
            return self.post("/api/leases/claim_batch", {
                "owner": kwargs.get("owner"),
                "root": kwargs.get("root"),
                "paths": kwargs.get("paths") or [],
                "ttl_seconds": kwargs.get("ttl_seconds", 900),
                "purpose": kwargs.get("purpose", "agent edit"),
            })
        if act.startswith("blackboard_"):
            bb_action = act.replace("blackboard_", "")
            board_id = kwargs.get("board_id") or kwargs.get("task_id") or "default"
            payload = {
                "action": bb_action,
                "board_id": board_id,
                "section": kwargs.get("section") or kwargs.get("key"),
                "content": kwargs.get("content") or kwargs.get("value"),
                "author": kwargs.get("author", "agent"),
                "remote_sections": kwargs.get("remote_sections") or kwargs.get("sections") or {},
                "clock": kwargs.get("clock"),
            }
            if kwargs.get("expected_version") is not None:
                payload["expected_version"] = kwargs["expected_version"]
            return self.post("/api/agent-state/blackboard", payload)
        if act == "release":
            return self.post("/api/leases/release", {"owner": kwargs.get("owner"), "lease_id": kwargs.get("lease_id", "")})
        if act == "renew":
            return self.post("/api/leases/renew", {"owner": kwargs.get("owner"), "lease_id": kwargs.get("lease_id", ""), "ttl_seconds": kwargs.get("ttl_seconds", 900)})
        if act == "leases":
            return self.get(f"/api/leases?root={quote(str(kwargs.get('root', '')))}")
        if act == "worktree_lease":
            return self.post("/api/coord/worktree_lease", {
                "root": kwargs.get("root", "."),
                "branch": kwargs.get("branch") or None,
            })
        if act in {"worktree_release"}:
            return self.post("/api/coord/worktree_release", {
                "root": kwargs.get("root", "."),
                "worktree_path": kwargs.get("worktree_path", ""),
                "worktree_id": kwargs.get("worktree_id", ""),
                "delete_branch": kwargs.get("delete_branch", True),
                "branch": kwargs.get("branch") or None,
            })
        if act == "pubsub_publish":
            allowed = {"root", "topic", "message", "publisher"}
            if set(kwargs) - allowed:
                return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                        "error": "pubsub_publish accepts only root, topic, message, and publisher"}
            if "message" not in kwargs:
                return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                        "error": "pubsub_publish requires message"}
            topic = kwargs.get("topic", "default")
            publisher = kwargs.get("publisher", "agent")
            if not isinstance(topic, str) or not isinstance(publisher, str):
                return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                        "error": "pubsub topic and publisher must be strings"}
            return self.post("/api/coord/pubsub_publish", {
                "root": kwargs.get("root", "."),
                "topic": topic,
                "message": kwargs["message"],
                "publisher": publisher,
            })
        if act == "pubsub_poll":
            allowed = {"root", "topic", "after_seq", "limit", "after_ts"}
            if set(kwargs) - allowed:
                return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                        "error": "pubsub_poll accepts only root, topic, after_seq, limit, and after_ts"}
            topic = kwargs.get("topic", "default")
            limit = kwargs.get("limit")
            after_seq = kwargs.get("after_seq")
            after_ts = kwargs.get("after_ts")
            if not isinstance(topic, str):
                return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                        "error": "pubsub topic must be a string"}
            if after_ts is not None and (
                isinstance(after_ts, bool)
                or not isinstance(after_ts, (int, float))
                or not 0 <= after_ts <= 1e12
                or not math.isfinite(after_ts)
            ):
                return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                        "error": "pubsub after_ts must be a finite number from 0 through 1e12"}
            if after_seq is not None and (type(after_seq) is not int or not 0 <= after_seq <= 2**63 - 1):
                return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                        "error": "pubsub after_seq must be a nonnegative 64-bit integer"}
            if limit is not None and (type(limit) is not int or not 1 <= limit <= 1000):
                return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                        "error": "pubsub limit must be an integer from 1 through 1000"}
            payload = {
                "root": kwargs.get("root", "."),
                "topic": topic,
                "limit": limit if limit is not None else 50,
                "after_seq": after_seq if after_seq is not None else 0,
            }
            if after_ts is not None:
                payload["after_ts"] = after_ts
            return self.post("/api/coord/pubsub_poll", payload)
        if act == "simulate_merge":
            return self.post("/api/coord/simulate_merge", {
                "root": kwargs.get("root", "."),
                "source_branch": kwargs.get("source_branch", ""),
                "target_branch": kwargs.get("target_branch", "HEAD"),
            })
        if act == "wait_for_event":
            timeout_val = float(kwargs.get("timeout", 60.0))
            return self.post("/api/coord/wait_for_event", {
                "topic": kwargs.get("topic", "default"),
                "timeout": timeout_val,
                "filter": kwargs.get("filter") or kwargs.get("filter_payload"),
            }, timeout=max(timeout_val + 5.0, 180.0))
        if act == "semaphore_acquire":
            timeout_val = float(kwargs.get("timeout", 0.0))
            return self.post("/api/coord/semaphore_acquire", {
                "name": kwargs.get("name", ""),
                "owner": kwargs.get("owner", "agent"),
                "capacity": int(kwargs.get("capacity", 1)),
                "ttl_seconds": float(kwargs.get("ttl_seconds", 300.0)),
                "purpose": kwargs.get("purpose", ""),
                "timeout": timeout_val,
            }, timeout=max(timeout_val + 5.0, 180.0))
        if act == "semaphore_release":
            return self.post("/api/coord/semaphore_release", {
                "name": kwargs.get("name", ""),
                "lease_id": kwargs.get("lease_id", ""),
                "owner": kwargs.get("owner", ""),
            })
        if act == "semaphore_status":
            return self.post("/api/coord/semaphore_status", {
                "name": kwargs.get("name") or None,
            })
        if act == "board_item_create":
            return self.post("/api/coord/board_item_create", {
                "title": kwargs.get("title", ""),
                "status": kwargs.get("status", "planned"),
                "priority": kwargs.get("priority", "medium"),
                "labels": kwargs.get("labels"),
                "assignee": kwargs.get("assignee", ""),
                "milestone": kwargs.get("milestone", ""),
                "linked_task_id": kwargs.get("linked_task_id", ""),
                "details": kwargs.get("details"),
            })
        if act == "board_item_update":
            return self.post("/api/coord/board_item_update", {
                "item_id": kwargs.get("item_id", ""),
                "title": kwargs.get("title"),
                "status": kwargs.get("status"),
                "priority": kwargs.get("priority"),
                "labels": kwargs.get("labels"),
                "assignee": kwargs.get("assignee"),
                "milestone": kwargs.get("milestone"),
                "linked_task_id": kwargs.get("linked_task_id"),
                "details": kwargs.get("details"),
            })
        if act == "board_item_get":
            return self.post("/api/coord/board_item_get", {
                "item_id": kwargs.get("item_id", ""),
            })
        if act == "board_item_delete":
            return self.post("/api/coord/board_item_delete", {
                "item_id": kwargs.get("item_id", ""),
            })
        if act == "board_item_list":
            return self.post("/api/coord/board_item_list", {
                "status": kwargs.get("status"),
                "priority": kwargs.get("priority"),
                "milestone": kwargs.get("milestone"),
                "assignee": kwargs.get("assignee"),
                "limit": kwargs.get("limit", 50),
            })
        if act == "board_summary":
            return self.post("/api/coord/board_summary", {})
        if act == "milestone_create":
            return self.post("/api/coord/milestone_create", {
                "name": kwargs.get("name", ""),
                "target_date": kwargs.get("target_date", ""),
                "description": kwargs.get("description", ""),
            })
        if act == "milestone_status":
            return self.post("/api/coord/milestone_status", {
                "name": kwargs.get("name", ""),
            })
        if act == "session_briefing":
            return self.post("/api/coord/session_briefing", {
                "include": kwargs.get("include"),
                "root": kwargs.get("root", ""),
            })
        if act.startswith("plan_"):
            # The MCP host may append active-task path hints to every
            # coordination call. They belong to task/repository context and
            # are not part of the file-backed plan operation contract.
            plan_arguments = dict(kwargs)
            plan_arguments.pop("changed_paths", None)
            error = validate_operation_arguments("local_ai_coord", act, plan_arguments)
            if error:
                return {"success": False, "status_code": 400, "terminal": True,
                        "retryable": False, "error": error}
            return self.post(f"/api/coord/{act}", plan_arguments)
        return {"success": False, "error": f"unknown coord action '{action}'"}


    def plan_init(self, root: str) -> dict[str, Any]:
        return self.coord(action="plan_init", root=root)

    def list_plans(self, root: str, query: str = "", lifecycle: str | None = None,
                   limit: int = 50) -> dict[str, Any]:
        arguments = dict(root=root, query=query, limit=limit)
        if lifecycle is not None:
            arguments["lifecycle"] = lifecycle
        return self.coord(action="plan_list", **arguments)

    def get_plan(self, plan_id: str, *, root: str) -> dict[str, Any]:
        return self.coord(action="plan_get", plan_id=plan_id, root=root)

    def create_plan(self, plan_id: str, title: str, *, root: str,
                    description: str = "", lifecycle: str = "draft",
                    default_target_ref: str | None = "refs/heads/master",
                    spec_refs: list[dict[str, Any]] | None = None,
                    tasks: dict[str, Any] | None = None, accountable_role: str | None = None,
                    owner: str = "agent", idempotency_key: str = "") -> dict[str, Any]:
        arguments = dict(root=root, plan_id=plan_id, title=title, description=description,
                         lifecycle=lifecycle, default_target_ref=default_target_ref,
                         owner=owner, idempotency_key=idempotency_key)
        for field, value in (("spec_refs", spec_refs), ("tasks", tasks), ("accountable_role", accountable_role)):
            if value is not None:
                arguments[field] = value
        return self.coord(action="plan_create", **arguments)

    def update_plan(self, plan_id: str, *, root: str, expected_revision: str,
                    owner: str = "agent", idempotency_key: str = "", **changes: Any) -> dict[str, Any]:
        return self.coord(action="plan_update", root=root, plan_id=plan_id,
                          expected_revision=expected_revision, owner=owner,
                          idempotency_key=idempotency_key, **changes)

    def edit_plan_task(self, plan_id: str, task_id: str, task_data: dict[str, Any], *,
                       root: str, expected_revision: str, idempotency_key: str = "",
                       owner: str = "agent") -> dict[str, Any]:
        return self.coord(action="plan_task_edit", root=root, plan_id=plan_id, task_id=task_id,
                          task_data=task_data, expected_revision=expected_revision,
                          idempotency_key=idempotency_key, owner=owner)

    def delete_plan_task(self, plan_id: str, task_id: str, *, root: str,
                         expected_revision: str, idempotency_key: str = "",
                         owner: str = "agent") -> dict[str, Any]:
        return self.coord(action="plan_task_delete", root=root, plan_id=plan_id, task_id=task_id,
                          expected_revision=expected_revision, idempotency_key=idempotency_key, owner=owner)

    def validate_plan(self, plan_id: str, *, root: str) -> dict[str, Any]:
        return self.coord(action="plan_validate", plan_id=plan_id, root=root)

    def archive_plan(self, plan_id: str, *, root: str, expected_revision: str,
                     idempotency_key: str = "", owner: str = "agent") -> dict[str, Any]:
        return self.coord(action="plan_archive", root=root, plan_id=plan_id,
                          expected_revision=expected_revision, idempotency_key=idempotency_key, owner=owner)

    def get_plan_board_view(self, root: str, plan_id: str = "", query: str = "",
                            worktree_id: str = "") -> dict[str, Any]:
        return self.coord(action="plan_board_view", root=root, plan_id=plan_id,
                          query=query, worktree_id=worktree_id)

    def adopt_legacy_board(self, plan_id: str, *, root: str, title: str = "",
                           owner: str = "agent", idempotency_key: str = "") -> dict[str, Any]:
        return self.coord(action="plan_adopt_legacy_board", root=root, plan_id=plan_id,
                          title=title, owner=owner, idempotency_key=idempotency_key)

    def bind_plan_task(self, task_id: str, plan_id: str, plan_task_id: str, *, root: str,
                       expected_revision: str | None = None, session_id: str = "") -> dict[str, Any]:
        arguments = dict(root=root, task_id=task_id, plan_id=plan_id,
                         plan_task_id=plan_task_id, session_id=session_id)
        if expected_revision is not None:
            arguments["expected_revision"] = expected_revision
        return self.coord(action="plan_bind_task", **arguments)

    def reconcile_plan_steering(self, task_id: str, steering_id: str, *, root: str,
                                spec_rel_path: str, spec_content: str, acceptance_criteria: list[str],
                                expected_revision: str, expected_spec_revision: str,
                                summary: str = "") -> dict[str, Any]:
        return self.coord(action="plan_reconcile_steering", root=root, task_id=task_id,
                          steering_id=steering_id, spec_rel_path=spec_rel_path, spec_content=spec_content,
                          acceptance_criteria=acceptance_criteria, expected_revision=expected_revision,
                          expected_spec_revision=expected_spec_revision, summary=summary)

    def context_compile(self, task_id: str, token_budget: int = 4000, changed_paths: list[str] | None = None, since_hash: str = "", compact: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": "compile",
            "task_id": task_id,
            "token_budget": token_budget,
            "changed_paths": changed_paths or [],
            "compact": compact,
        }
        if since_hash:
            payload["since_hash"] = since_hash
        return self.post("/api/agent-state/context", payload)

    def get_evidence(self, evidence_id: str, verify: bool = True) -> dict[str, Any]:
        return self.post("/api/evidence/get", {"evidence_id": evidence_id, "verify": verify})

    def verify_receipt(
        self,
        task_id: str,
        criterion: str,
        passed: bool = True,
        command_id: str = "",
        evidence_id: str = "",
        details: dict[str, Any] | None = None,
        root: str | None = None,
        repository_revision: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": "receipt",
            "receipt": {
                "task_id": task_id,
                "criterion": criterion,
                "passed": passed,
                "command_id": command_id,
                "evidence_id": evidence_id,
                "details": details or {},
            },
        }
        if root is not None:
            payload["root"] = root
        if repository_revision is not None:
            payload["receipt"]["repository_revision"] = repository_revision
        return self.post("/api/agent-state/verification", payload)

    def verify_completion(self, task_id: str, root: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": "completion",
            "task_id": task_id,
        }
        if root is not None:
            payload["root"] = root
        return self.post("/api/agent-state/verification", payload)

    def create_task(
        self,
        goal: str,
        acceptance_criteria: list[str] | None = None,
        task_id: str = "",
        scope: str = "task",
        root: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = {
            **kwargs,
            "action": "create",
            "goal": goal,
            "acceptance_criteria": acceptance_criteria or [],
            "task_id": task_id,
            "scope": scope,
        }
        if root is not None:
            payload["root"] = root
        return self.post("/api/agent-state/tasks", payload)

    def get_task(self, task_id: str, root: str | None = None) -> dict[str, Any]:
        payload = {"action": "get", "task_id": task_id}
        if root is not None:
            payload["root"] = root
        return self.post("/api/agent-state/tasks", payload)

    def list_tasks(
        self,
        status: str | None = None,
        limit: int = 100,
        query: str | None = None,
        root: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": "list", "limit": limit}
        if root is not None:
            payload["root"] = root
        if status:
            payload["status"] = status
        if query is not None:
            payload["query"] = query
        return self.post("/api/agent-state/tasks", payload)

    def complete_task(self, task_id: str, reason: str = "completed by agent", root: str | None = None) -> dict[str, Any]:
        payload = {"action": "complete", "task_id": task_id, "reason": reason}
        if root is not None:
            payload["root"] = root
        return self.post("/api/agent-state/tasks", payload)

    def fail_task(self, task_id: str, reason: str = "failed by agent", root: str | None = None) -> dict[str, Any]:
        payload = {"action": "fail", "task_id": task_id, "reason": reason}
        if root is not None:
            payload["root"] = root
        return self.post("/api/agent-state/tasks", payload)

    def checkpoint_task(
        self,
        task_id: str,
        phase: str = "",
        next_action: str = "",
        affected_paths: list[str] | None = None,
        root: str | None = None,
        response_budget_tokens: int | None = None,
        *,
        evidence_ids: list[str] | None = None,
        blockers: list[str] | None = None,
        state_data: dict[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        for name, items in (("affected_paths", affected_paths), ("evidence_ids", evidence_ids), ("blockers", blockers)):
            if items is not None and (not isinstance(items, list) or any(not isinstance(item, str) for item in items)):
                raise TypeError(f"{name} must be a list of strings")
        if state_data is not None and not isinstance(state_data, dict):
            raise TypeError("state_data must be an object")
        payload = {
            "action": "checkpoint",
            "task_id": task_id,
            "checkpoint": {
                "phase": phase,
                "next_action": next_action,
                "affected_paths": [] if affected_paths is None else affected_paths,
                "evidence_ids": [] if evidence_ids is None else evidence_ids,
                "blockers": [] if blockers is None else blockers,
                "state_data": {} if state_data is None else state_data,
            },
        }
        if response_budget_tokens is not None:
            payload["response_budget_tokens"] = response_budget_tokens
        if root is not None:
            payload["root"] = root
        if not isinstance(idempotency_key, str):
            raise TypeError("idempotency_key must be a string")
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        return self.post("/api/agent-state/tasks", payload)

    def record_memory(self, key: str, value: Any, scope: str = "task", kind: str = "fact", **kwargs: Any) -> dict[str, Any]:
        payload = {
            **kwargs,
            "action": "record",
            "key": key,
            "value": value,
            "scope": scope,
            "kind": kind,
        }
        return self.post("/api/agent-state/memory", payload)

    def find_memory(
        self,
        scope: str | None = None,
        key: str | None = None,
        query: str | None = None,
        limit: int = 100,
        root: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": "find", "limit": limit}
        if root is not None:
            payload["root"] = root
        if scope:
            payload["scope"] = scope
        if key:
            payload["key"] = key
        if query:
            payload["query"] = query
        return self.post("/api/agent-state/memory", payload)

    def submit_async_job(
        self,
        job_action: str,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
        timeout: float = 360.0,
    ) -> dict[str, Any]:
        body = dict(payload)
        body["action"] = "submit"
        body["job_action"] = str(job_action)
        if request_id is not None:
            body["request_id"] = str(request_id)
        return self.post("/api/async-jobs", body, timeout=timeout)

    def async_job_status(self, job_id: str, *, timeout: float = 360.0) -> dict[str, Any]:
        return self.post("/api/async-jobs", {"action": "status", "job_id": job_id}, timeout=timeout)

    def wait_async_job(
        self,
        job_id: str,
        timeout_seconds: float = 90.0,
        *,
        transport_timeout: float | None = None,
    ) -> dict[str, Any]:
        requested_wait = max(0.0, float(timeout_seconds))
        client_timeout_limit = max(0.2, float(getattr(self, "max_request_timeout", 360.0)))
        requested_transport = transport_timeout if transport_timeout is not None else requested_wait + 30.0
        request_timeout = min(client_timeout_limit, max(0.2, float(requested_transport)))
        margin = max(0.2, min(30.0, request_timeout * 0.1))
        wait_seconds = min(requested_wait, max(0.0, request_timeout - margin))
        return self.post(
            "/api/async-jobs",
            {"action": "wait", "job_id": job_id, "timeout_seconds": wait_seconds},
            timeout=request_timeout,
        )

    def async_job_result(self, job_id: str, *, timeout: float = 360.0) -> dict[str, Any]:
        return self.post("/api/async-jobs", {"action": "result", "job_id": job_id}, timeout=timeout)

    def cancel_async_job(self, job_id: str, *, timeout: float = 360.0) -> dict[str, Any]:
        return self.post("/api/async-jobs", {"action": "cancel", "job_id": job_id}, timeout=timeout)

    def continue_conversation(
        self,
        conversation_id: str,
        prompt: str,
        *,
        context: str | None = None,
        timeout: float = 360.0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "conversation_id": conversation_id,
            "task": prompt,
        }
        if context is not None:
            payload["context"] = context
        return self.post("/api/conversations/continue", payload, timeout=timeout)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self.post("/api/async-jobs", {"action": "cancel", "job_id": job_id})

    def doctor(self) -> dict[str, Any]:
        return self.get("/api/doctor")

    def logs(self, lines: int = 200) -> dict[str, Any]:
        return self.get(f"/api/logs/tail?lines={max(1, min(int(lines), 1000))}")

    def events(self, stream_id: str = "", after_seq: int = 0, limit: int = 100) -> dict[str, Any]:
        import urllib.parse
        params = []
        if stream_id:
            params.append(f"stream_id={urllib.parse.quote(stream_id)}")
        if after_seq > 0:
            params.append(f"after_seq={after_seq}")
        if limit != 100:
            params.append(f"limit={limit}")
        qs = ("?" + "&".join(params)) if params else ""
        return self.get(f"/api/agent-state/events{qs}")

    def stream_events(
        self,
        stream_id: str = "",
        kind: str = "",
        after_seq: int = 0,
        timeout: float = 30.0,
        *,
        root: str = "",
        cancel_event: threading.Event | None = None,
    ):
        """Yield parsed SSE events (event_type, data_dict) from /api/agent-state/events/stream."""
        import urllib.parse
        requested_timeout = max(0.0, float(timeout))
        max_request_timeout = float(getattr(self, "max_request_timeout", 1800.0))
        stream_timeout = min(max_request_timeout, requested_timeout)
        transport_timeout = min(
            max_request_timeout,
            max(0.2, stream_timeout + 5.0 if stream_timeout > 0 else 60.0),
        )
        params = []
        if stream_id:
            params.append(f"stream_id={urllib.parse.quote(stream_id)}")
        if root:
            params.append(f"root={urllib.parse.quote(root)}")
        if kind:
            params.append(f"kind={urllib.parse.quote(kind)}")
        if after_seq > 0:
            params.append(f"after_seq={after_seq}")
        if stream_timeout > 0:
            params.append(f"timeout={stream_timeout:g}")
        qs = ("?" + "&".join(params)) if params else ""
        url = f"{self.base_url}/api/agent-state/events/stream{qs}"
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        headers = {
            "X-LocalAI-Agent": self.agent,
            "X-LocalAI-Request-ID": request_id,
        }
        if self.api_token:
            headers["X-LocalAI-Token"] = self.api_token
            headers["Authorization"] = f"Bearer {self.api_token}"
        req = Request(url, headers=headers)
        monitor_stopped = threading.Event()
        deadline_expired = threading.Event()
        watcher = None
        try:
            if cancel_event is not None and cancel_event.is_set():
                return
            response = urlopen(req, timeout=transport_timeout)
            with response as resp:
                def interrupt_response() -> None:
                    fp = getattr(resp, "fp", None)
                    raw = getattr(fp, "raw", None)
                    stream_socket = getattr(raw, "_sock", None)
                    connection = getattr(resp, "_connection", None)
                    if stream_socket is not None:
                        try: stream_socket.shutdown(socket.SHUT_RDWR)
                        except OSError: pass
                    try: resp.close()
                    except OSError: pass
                    if connection is not None:
                        try: connection.close()
                        except OSError: pass
                def close_on_interrupt() -> None:
                    deadline = time.monotonic() + transport_timeout
                    while not monitor_stopped.is_set():
                        if cancel_event is not None and cancel_event.is_set():
                            interrupt_response()
                            return
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            if not monitor_stopped.is_set():
                                deadline_expired.set()
                                interrupt_response()
                            return
                        monitor_stopped.wait(min(0.05, remaining))

                watcher = threading.Thread(target=close_on_interrupt, daemon=True)
                watcher.start()
                cur_event = ""
                cur_data = []
                for raw_line in resp:
                    if cancel_event is not None and cancel_event.is_set():
                        return
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        if cur_data:
                            data_str = "\n".join(cur_data)
                            try:
                                parsed_data = json.loads(data_str)
                            except Exception:
                                parsed_data = {"raw": data_str}
                            if not isinstance(parsed_data, dict):
                                parsed_data = {"raw": data_str}
                            yield cur_event or "message", parsed_data
                        cur_event = ""
                        cur_data = []
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        cur_event = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        cur_data.append(line[len("data:"):].strip())
        except HTTPError:
            raise
        except (URLError, OSError, http.client.HTTPException, AttributeError) as exc:
            if isinstance(exc, TimeoutError):
                deadline_expired.set()
            if cancel_event is not None and cancel_event.is_set():
                return
            result = self._uncertain_response(request_id)
            if deadline_expired.is_set():
                result["retry_timeout"] = True
            yield "error", result
        finally:
            monitor_stopped.set()
            if watcher is not None:
                watcher.join(timeout=0.1)

    def circular_dependencies(self, root: str = ".", language: str = "python") -> dict[str, Any]:
        return self.post("/api/repo/circular_dependencies", {"root": root, "language": language})

    def generate_types(self, path: str, root: str = ".") -> dict[str, Any]:
        return self.post("/api/repo/generate_types", {"root": root, "path": path})

    def complexity(self, root: str = ".", path: str | None = None, max_results: int = 20) -> dict[str, Any]:
        return self.post("/api/repo/complexity", {"root": root, "path": path, "max_results": max_results})

    def api_spec(self, root: str = ".", framework: str | None = None) -> dict[str, Any]:
        return self.post("/api/repo/api_spec", {"root": root, "framework": framework})

    def dependency_slice(self, root: str = ".", symbol: str = "", path: str | None = None, depth: int = 2) -> dict[str, Any]:
        return self.post("/api/repo/dependency_slice", {"root": root, "symbol": symbol, "path": path, "depth": depth})

    def migration_drift(self, root: str = ".", db_path: str | None = None) -> dict[str, Any]:
        return self.post("/api/repo/migration_drift", {"root": root, "db_path": db_path})

    def package_audit(self, root: str = ".", lockfile_path: str | None = None) -> dict[str, Any]:
        return self.post("/api/repo/package_audit", {"root": root, "lockfile_path": lockfile_path})

    def eval_drift(self, suite_name: str = "default") -> dict[str, Any]:
        return self.post("/api/task/eval_drift", {"suite_name": suite_name})

    def git_diff(self, root: str = ".", path: str | None = None, staged: bool = False, max_lines: int = 1000,
                 *, rev1: str | None = None, rev2: str | None = None) -> dict[str, Any]:
        payload = {"root": root, "path": path, "staged": staged, "max_lines": max_lines}
        if rev1 is not None or rev2 is not None:
            payload.update(rev1=rev1, rev2=rev2)
        return self.post("/api/git/diff", payload)

    def git_history_search(
        self,
        root: str = ".",
        query: str = "",
        max_commits: int = 20,
        *,
        author: str | None = None,
        since: str | None = None,
        until: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        return self.post("/api/git/history_search", {
            "root": root,
            "query": query,
            "max_commits": max_commits,
            "author": author,
            "since": since,
            "until": until,
            "path": path,
        })

    def hotspots(self, root: str = ".", days: int = 30, limit: int = 20) -> dict[str, Any]:
        return self.post("/api/repo/hotspots", {"root": root, "days": days, "limit": limit})

    def generate_tests_for_diff(self, root: str = ".", diff: str | None = None, path: str | None = None) -> dict[str, Any]:
        return self.post("/api/repo/generate_tests_for_diff", {"root": root, "diff": diff, "path": path})

    def cross_repo_contract(self, backend_root: str = ".", frontend_root: str = ".") -> dict[str, Any]:
        return self.post("/api/repo/cross_repo_contract", {"backend_root": backend_root, "frontend_root": frontend_root})

    def ingest_diagram(
        self,
        workspace: str = "default",
        image_path: str = "",
        caption: str = "",
        metadata: dict[str, Any] | None = None,
        *,
        root: str,
    ) -> dict[str, Any]:
        return self.post(
            "/api/rag/ingest_diagram",
            {"root": root, "workspace": workspace, "image_path": image_path, "caption": caption, "metadata": metadata},
        )

    def curate_training_dataset(
        self,
        output_path: str = "training_dataset.jsonl",
        min_receipts: int = 1,
        format: str = "jsonl",
        *,
        root: str,
    ) -> dict[str, Any]:
        return self.post(
            "/api/agent-state/tasks",
            {
                "action": "curate_dataset",
                "root": root,
                "output_path": output_path,
                "min_receipts": min_receipts,
                "format": format,
            },
        )
