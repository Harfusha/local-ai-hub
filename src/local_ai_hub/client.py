from __future__ import annotations

from .json_utils import dumps as json_dumps

import copy
import errno
import http.client
import io
import json
import os
import threading
import uuid
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

from .process_utils import find_listening_pid, pid_alive
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import load_config


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
    ) -> bytes: ...

    def close(self) -> None: ...


class _TransportFailure(OSError):
    """Transport error with evidence whether any request bytes could be sent."""

    def __init__(self, cause: BaseException, *, request_not_sent: bool) -> None:
        super().__init__(str(cause))
        self.request_not_sent = request_not_sent


_DETACHED_CHILDREN_LOCK = threading.Lock()
_DETACHED_CHILDREN: list[subprocess.Popen[Any]] = []


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
    handle.write(f"{os.getpid()} {time.time()}".encode("ascii", errors="ignore"))
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
        if pid_alive(owner_pid) and age <= max(1.0, stale_seconds):
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
        tenant: str | None = None,
        config_path: str | None = None,
        *,
        auto_start: bool = True,
        inprocess_transport: _InProcessTransport | None = None,
    ):
        self.config = load_config(config_path)
        server = self.config["server"]
        bind_host = str(server.get("bind", "127.0.0.1"))
        client_host = str(server.get("client_host", "")).strip() or ("127.0.0.1" if bind_host in {"0.0.0.0", "::", "[::]"} else bind_host)
        self.base_url = f"http://{client_host}:{int(server.get('port', 11435))}"
        endpoint = urlsplit(self.base_url)
        self._http_host = str(endpoint.hostname or "127.0.0.1")
        self._http_port = int(endpoint.port or 80)
        self.api_token = str(self.config.get("security", {}).get("api_token", ""))
        self.tenant = tenant or os.environ.get("LOCAL_AI_TENANT") or f"agent-{os.getpid()}"
        self.agent = os.environ.get("LOCAL_AI_AGENT_PROFILE") or os.environ.get("LOCAL_AI_AGENT") or "generic"
        self.auto_start = bool(auto_start)
        self._inprocess_transport = inprocess_transport
        client_cfg = self.config.get("client", {})
        self.health_timeout = max(0.2, float(client_cfg.get("health_timeout_seconds", 0.75)))
        self.startup_wait = max(1.0, float(client_cfg.get("startup_wait_seconds", 15.0)))
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

    def _pooled_open(self, method: str, path: str, body: bytes | None, headers: dict[str, str], timeout: float) -> bytes:
        conn: http.client.HTTPConnection | None = None
        original_send: Any = None
        request_send_started = False
        connect_refused_before_write = False
        try:
            conn = self._connection(timeout)
            original_send = getattr(conn, "send", None)

            def tracked_send(data: Any) -> None:
                nonlocal connect_refused_before_write, request_send_started
                if conn.sock is None:
                    try:
                        conn.connect()
                    except OSError as exc:
                        connect_refused_before_write = (
                            isinstance(exc, ConnectionRefusedError)
                            or getattr(exc, "errno", None) == errno.ECONNREFUSED
                        )
                        raise
                request_send_started = True
                return original_send(data)

            if original_send is not None:
                conn.send = tracked_send  # type: ignore[method-assign]
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read()
        except (OSError, http.client.HTTPException) as exc:
            self._drop_connection()
            raise _TransportFailure(
                exc,
                request_not_sent=connect_refused_before_write and not request_send_started,
            ) from exc
        finally:
            if conn is not None and original_send is not None:
                conn.send = original_send  # type: ignore[method-assign]
        if bool(getattr(response, "will_close", False)):
            self._drop_connection()
        if int(response.status) >= 400:
            response_headers = getattr(response, "headers", {})
            raise HTTPError(f"{self.base_url}{path}", int(response.status), str(response.reason), response_headers, io.BytesIO(raw))
        return raw

    def _open(
        self, method: str, path: str, body: bytes | None,
        headers: dict[str, str], timeout: float, *,
        operational_action: str | None = None,
        requires_heavy_work: bool = True,
    ) -> bytes:
        transport = self._inprocess_transport
        if transport is not None:
            return transport.open(
                method, path, body, headers, timeout,
                operational_action=operational_action,
                requires_heavy_work=requires_heavy_work,
            )
        return self._pooled_open(method, path, body, headers, timeout)
    @staticmethod
    def _error_response(exc: HTTPError, request_id: str) -> dict[str, Any]:
        try:
            parsed = json.loads(exc.read().decode("utf-8"))
            if isinstance(parsed, dict):
                parsed.setdefault("success", False)
                parsed.setdefault("status_code", exc.code)
                if exc.code in {408, 425, 429, 500, 502, 503, 504}:
                    parsed.setdefault("retryable", True)
                parsed.setdefault("request_id", request_id)
                return parsed
            return {"success": False, "error": str(parsed), "status_code": exc.code, "request_id": request_id}
        except Exception:
            return {"success": False, "error": f"HTTP {exc.code}: {exc.reason}", "status_code": exc.code, "request_id": request_id}

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
            "request_id": request_id,
        }
        if retried:
            result["retried"] = True
        return result

    @staticmethod
    def _transport_failure_response(
        request_id: str,
        *failures: BaseException,
        retried: bool = False,
        prior_send_possible: bool = False,
    ) -> dict[str, Any]:
        if (
            not prior_send_possible
            and failures
            and all(bool(getattr(exc, "request_not_sent", False)) for exc in failures)
        ):
            result = {
                "success": False,
                "error": "request was not sent because transport failed before write",
                "request_not_sent": True,
                "outcome_unknown": False,
                "request_id": request_id,
            }
            if retried:
                result["retried"] = True
            return result
        return HubClient._uncertain_response(request_id, retried=retried)

    def _singleflight(self, key: str, timeout: float, execute: Any, *, request_id: str = "") -> dict[str, Any]:
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
        if not flight["event"].wait(timeout):
            error = TimeoutError("coalesced hub request timed out")
            error.request_id = flight.get("request_id", request_id)
            raise error
        if flight["error"] is not None:
            raise flight["error"]
        result = copy.deepcopy(flight["result"])
        if isinstance(result, dict): result["coalesced"] = True
        return result

    def _online(self, timeout: float | None = None) -> bool:
        try:
            health_timeout = self.health_timeout if timeout is None else min(self.health_timeout, max(0.0, timeout))
            if health_timeout <= 0:
                return False
            headers = {"X-LocalAI-Token": self.api_token} if self.api_token else {}
            with urlopen(Request(f"{self.base_url}/health", headers=headers), timeout=health_timeout) as response:
                return response.status == 200
        except HTTPError as exc:
            # 503 from the bounded HTTP admission gate proves the singleton is alive
            # but busy. Treat it as online so clients do not spawn/restart another hub.
            return exc.code == 503
        except Exception:
            return False

    def ensure_server(self, timeout: float | None = None) -> bool:
        budget = self.startup_wait if timeout is None else min(self.startup_wait, max(0.0, float(timeout)))
        deadline = time.monotonic() + budget

        def remaining() -> float:
            return max(0.0, deadline - time.monotonic())

        def wait_until_ready() -> bool:
            while remaining() > 0:
                if self._online(remaining()):
                    return True
                time.sleep(min(self.startup_poll, remaining()))
            return self._online(remaining())

        if self._online(remaining()):
            return True
        state_dir = Path(self.config["server"]["state_dir"])
        try:
            from .operational_mode import load_operational_mode

            operational_mode = load_operational_mode(state_dir)
        except Exception:
            return False
        if getattr(operational_mode, "mode", None) != "active" or getattr(operational_mode, "degraded", True):
            return False
        config_path = self.config["_config_path"]
        state_dir.mkdir(parents=True, exist_ok=True)
        if bool(self.config.get("headless", {}).get("respect_disabled_marker", True)) and (state_dir / "service.disabled").exists():
            return False
        # Managed mode has one supervisor responsible for startup/recovery. During
        # its cold-start interval MCP clients must not bypass it with direct pythonw
        # spawns, otherwise every client can create a competing hub tree.
        try:
            supervisor_pid = int((state_dir / "supervisor.pid").read_text(encoding="utf-8").strip() or 0)
            if pid_alive(supervisor_pid):
                return wait_until_ready()
        except (OSError, ValueError):
            pass
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
                if self._online(remaining()):
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
            return self._online(remaining())

        if not owner:
            return self._online(remaining())
        ready = False
        keep_lock = False
        try:
            if self._online(remaining()):
                return True
            if remaining() <= 0:
                return False
            env = os.environ.copy()
            env["LOCAL_AI_CONFIG"] = config_path
            src_dir = str(Path(__file__).resolve().parents[1])
            env["PYTHONPATH"] = src_dir + (os.pathsep + env["PYTHONPATH"] if "PYTHONPATH" in env else "")
            service_script = Path(__file__).resolve().parents[2] / "tools" / "service.py"
            if not service_script.is_file():
                return False
            try:
                from .process_utils import hidden_run_kwargs
                kwargs = hidden_run_kwargs()
            except Exception:
                kwargs = {}
            try:
                completed = subprocess.run(
                    [sys.executable, str(service_script), "start"],
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=max(0.1, remaining()),
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
            while remaining() > 0:
                if self._online(remaining()):
                    ready = True
                    return True
                time.sleep(min(self.startup_poll, remaining()))
            ready = self._online(remaining())
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
    ) -> dict[str, Any]:
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
        preflight = self._terminal_preflight(path, clean_payload)
        if preflight is not None:
            return preflight
        body = json_dumps(clean_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")
        request_id = request_id if request_id is not None else f"req_{uuid.uuid4().hex[:12]}"

        def once(attempt_timeout: float) -> dict[str, Any]:
            headers = {
                "Content-Type": "application/json", "X-LocalAI-Tenant": self.tenant,
                "X-LocalAI-Agent": self.agent, "X-LocalAI-Request-ID": request_id,
            }
            if self.api_token:
                headers["X-LocalAI-Token"] = self.api_token
            try:
                result = json.loads(
                    self._open(
                        "POST", path, body, headers, attempt_timeout,
                        operational_action=operational_action,
                        requires_heavy_work=requires_heavy_work,
                    ).decode("utf-8")
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._invalid_json_response(request_id, outcome_unknown=not replay_safe)
            if not isinstance(result, dict):
                return self._invalid_json_response(request_id, outcome_unknown=not replay_safe)
            return result

        def execute() -> dict[str, Any]:
            duplicate_deadline = time.monotonic() + timeout
            try:
                while True:
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
                        if not (result.get("in_progress") and result.get("retryable")):
                            return result
                        remaining = duplicate_deadline - time.monotonic()
                        if remaining <= 0:
                            result["retry_timeout"] = True
                            return result
                        retry_after = max(0.01, float(result.get("retry_after_seconds", 0.1) or 0.1))
                        time.sleep(min(retry_after, remaining))
            except HTTPError as exc:
                return self._error_response(exc, request_id)
            except (URLError, OSError, http.client.HTTPException) as exc:
                self._drop_connection()
                pre_send_refusal = bool(getattr(exc, "request_not_sent", False))
                if self._inprocess_transport is not None and pre_send_refusal:
                    return self._transport_failure_response(request_id, exc)
                if replay_safe or (self.auto_start and pre_send_refusal):
                    remaining = duplicate_deadline - time.monotonic()
                    try:
                        if self._inprocess_transport is not None:
                            server_ready = bool(replay_safe or pre_send_refusal)
                        else:
                            server_ready = self.ensure_server(timeout=remaining) if self.auto_start and remaining > 0 else not self.auto_start
                    except Exception:
                        server_ready = False
                    if server_ready:
                        remaining = duplicate_deadline - time.monotonic()
                        if remaining <= 0:
                            return self._transport_failure_response(
                                request_id, exc, prior_send_possible=not pre_send_refusal
                            )
                        try:
                            retry_result = once(remaining)
                            if retry_result.get("outcome_unknown"):
                                retry_result["retried"] = True
                            return retry_result
                        except HTTPError as retry_http: return self._error_response(retry_http, request_id)
                        except (URLError, OSError, http.client.HTTPException) as retry_exc:
                            self._drop_connection()
                            return self._transport_failure_response(
                                request_id, exc, retry_exc, retried=True,
                                prior_send_possible=not pre_send_refusal,
                            )
                        except Exception:
                            return self._uncertain_response(request_id, retried=True)
                return self._transport_failure_response(request_id, exc)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._invalid_json_response(request_id, outcome_unknown=not replay_safe)
            except Exception:
                return self._uncertain_response(request_id)

        if not replay_safe:
            return execute()

        key = f"POST|{self.tenant}|{self.agent}|{path}|{body.decode('utf-8')}"
        try:
            return self._singleflight(key, timeout, execute, request_id=request_id)
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
        self, path: str, timeout: float = 15.0, *,
        operational_action: str | None = None,
        requires_heavy_work: bool = True,
    ) -> dict[str, Any]:
        timeout = min(self.max_request_timeout, max(0.2, float(timeout)))
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        headers = {
            "X-LocalAI-Tenant": self.tenant,
            "X-LocalAI-Agent": self.agent,
            "X-LocalAI-Request-ID": request_id,
        }
        if self.api_token:
            headers["X-LocalAI-Token"] = self.api_token

        def once(attempt_timeout: float) -> dict[str, Any]:
            try:
                result = json.loads(
                    self._open(
                        "GET", path, None, headers, attempt_timeout,
                        operational_action=operational_action,
                        requires_heavy_work=requires_heavy_work,
                    ).decode("utf-8")
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._invalid_json_response(request_id, outcome_unknown=False)
            return result if isinstance(result, dict) else self._invalid_json_response(request_id, outcome_unknown=False)

        def execute() -> dict[str, Any]:
            deadline = time.monotonic() + timeout
            try:
                return once(timeout)
            except HTTPError as exc:
                return self._error_response(exc, request_id)
            except (URLError, OSError, http.client.HTTPException):
                self._drop_connection()
                remaining = deadline - time.monotonic()
                if self._inprocess_transport is not None:
                    server_ready = remaining > 0
                else:
                    server_ready = self.ensure_server(timeout=remaining) if self.auto_start and remaining > 0 else not self.auto_start
                if server_ready:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return self._uncertain_response(request_id)
                    try: return once(remaining)
                    except HTTPError as retry_http: return self._error_response(retry_http, request_id)
                    except (URLError, OSError, http.client.HTTPException):
                        self._drop_connection()
                        return self._uncertain_response(request_id, retried=True)
                    except Exception:
                        return self._uncertain_response(request_id, retried=True)
                return self._uncertain_response(request_id)
            except Exception:
                return self._uncertain_response(request_id)

        key = f"GET|{self.tenant}|{self.agent}|{path}"
        try:
            return self._singleflight(key, timeout, execute, request_id=request_id)
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
        """Fail closed: only known read-only POST endpoints may be replayed."""
        path = path.lower().split("?", 1)[0]
        if path in {
            "/api/memory/get",
            "/api/memory/search",
            "/api/repo/circular_dependencies",
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
        if path == "/api/repo/generate_types":
            return not bool((payload or {}).get("write_stub"))
        action = str((payload or {}).get("action", "")).strip().lower()
        read_actions = {
            "/api/agent-state/tasks": {"get", "list", "count"},
            "/api/agent-state/memory": {"get", "find", "relation_find", "relation_traverse"},
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
    ) -> dict[str, Any]:
        clean_payload = dict(payload or {})
        route = path.lower().split("?", 1)[0]
        if route in {"/api/search", "/api/command"}:
            explicit_path = isinstance(clean_payload.get("path"), str) and bool(clean_payload["path"].strip())
            if explicit_path:
                clean_payload.pop("path_hints", None)
            elif path_hints is not None:
                records = []
                for hint in path_hints[:64]:
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
        replay_safe = self._post_replay_safe(path, clean_payload)
        if request_id is None:
            return self.request(path, clean_payload, timeout=timeout, replay_safe=replay_safe)
        return self.request(path, clean_payload, timeout=timeout, replay_safe=replay_safe, request_id=request_id)

    def status(self, detail: str = "brief", scope: str = "process") -> dict[str, Any]:
        if detail == "agent_state":
            return self.get("/api/status?detail=agent_state")
        return self.get(f"/api/live/status?light=1&scope={scope}&detail={detail}")

    def coord(self, action: str, **kwargs: Any) -> dict[str, Any]:
        act = action.strip().lower().replace("-", "_")
        if act.startswith("task_"):
            task_action = act.replace("task_", "")
            payload = {"action": task_action, **kwargs}
            return self.post("/api/agent-state/tasks", payload)
        if act in ("memo_put", "memo_get", "memo_search", "memo_delete"):
            if act == "memo_put":
                return self.post("/api/memory/put", {
                    "root": kwargs.get("root", "."),
                    "key": kwargs.get("key", ""),
                    "value": kwargs.get("value", ""),
                    "ttl_seconds": kwargs.get("ttl_seconds", 604800),
                })
            if act == "memo_get":
                return self.post("/api/memory/get", {"root": kwargs.get("root", "."), "key": kwargs.get("key", "")})
            if act == "memo_search":
                return self.post("/api/memory/search", {"root": kwargs.get("root", "."), "query": kwargs.get("query", ""), "limit": kwargs.get("limit", 12)})
            if act == "memo_delete":
                return self.post("/api/memory/delete", {"root": kwargs.get("root", "."), "key": kwargs.get("key", "")})
        if act.startswith("memory_"):
            mem_action = act.replace("memory_", "")
            payload = {"action": mem_action, **kwargs}
            return self.post("/api/agent-state/memory", payload)
        if act.startswith("relation_"):
            payload = {"action": act, **kwargs}
            return self.post("/api/agent-state/memory", payload)
        if act == "incident_decision":

            return self.post("/api/agent-state/incidents", {
                "action": "decision",
                "fingerprint": kwargs.get("fingerprint") or {},
                "state_revision": kwargs.get("state_revision", kwargs.get("revision", "")),
            })
        if act == "context_compile":
            return self.post("/api/agent-state/context", {
                "action": "compile",
                "task_id": kwargs.get("task_id") or kwargs.get("query") or kwargs.get("task") or "",
                "token_budget": kwargs.get("token_budget") or kwargs.get("max_tokens") or 4000,
                "changed_paths": kwargs.get("changed_paths") or kwargs.get("paths") or [],
                "root": kwargs.get("root", "."),
            })
        if act == "verify_receipt":
            receipt = kwargs.get("receipt") or {
                "task_id": kwargs.get("task_id", ""),
                "criterion": kwargs.get("criterion", kwargs.get("key", "")),
                "passed": kwargs.get("passed", True),
            }
            if not str(receipt.get("task_id", "")).strip() or not str(receipt.get("criterion", "")).strip():
                return {
                    "success": False,
                    "terminal": True,
                    "retryable": False,
                    "error": "verify_receipt requires task_id and criterion",
                }
            return self.post("/api/agent-state/verification", {
                "action": "receipt",
                "receipt": receipt,
                "root": kwargs.get("root", "."),
            })
        if act == "verify_completion":
            return self.post("/api/agent-state/verification", {
                "action": "completion",
                "task_id": kwargs.get("task_id") or kwargs.get("query") or kwargs.get("task") or "",
                "root": kwargs.get("root", "."),
            })
        if act in {"negative_knowledge_record", "negative_knowledge_find"}:
            sub_act = "record" if act == "negative_knowledge_record" else "find"
            return self.post("/api/agent-state/incidents", {
                "action": sub_act,
                **kwargs,
            })
        if act in ("claim", "claim_batch"):
            return self.post("/api/leases/claim_batch", {
                "root": kwargs.get("root", "."),
                "paths": kwargs.get("paths") or [],
                "ttl_seconds": kwargs.get("ttl_seconds", 900),
                "purpose": kwargs.get("value", "agent edit"),
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
            return self.post("/api/leases/release", {"lease_id": kwargs.get("lease_id", "")})
        if act == "leases":
            return self.get(f"/api/leases?root={quote(str(kwargs.get('root', '')))}")
        if act in {"worktree_lease", "worktree_claim"}:
            return self.post("/api/coord/worktree_lease", {
                "root": kwargs.get("root", "."),
                "branch": kwargs.get("branch") or kwargs.get("key") or kwargs.get("task_id"),
            })
        if act in {"worktree_release"}:
            return self.post("/api/coord/worktree_release", {
                "root": kwargs.get("root", "."),
                "worktree_path": kwargs.get("worktree_path") or kwargs.get("value") or kwargs.get("lease_id") or "",
                "delete_branch": kwargs.get("delete_branch", True),
                "branch": kwargs.get("branch") or kwargs.get("key") or kwargs.get("task_id"),
            })
        if act == "pubsub_publish":
            return self.post("/api/coord/pubsub_publish", {
                "root": kwargs.get("root", "."),
                "topic": kwargs.get("topic") or kwargs.get("key", "default"),
                "message": kwargs.get("message") or kwargs.get("value", ""),
                "publisher": kwargs.get("publisher") or kwargs.get("approver", "agent"),
            })
        if act == "pubsub_poll":
            return self.post("/api/coord/pubsub_poll", {
                "root": kwargs.get("root", "."),
                "topic": kwargs.get("topic") or kwargs.get("key", "default"),
                "after_seq": kwargs.get("after_seq", 0),
                "limit": int(kwargs.get("limit", 50)),
            })
        if act == "simulate_merge":
            return self.post("/api/coord/simulate_merge", {
                "root": kwargs.get("root", "."),
                "source_branch": kwargs.get("source_branch") or kwargs.get("key") or kwargs.get("branch", ""),
                "target_branch": kwargs.get("target_branch") or kwargs.get("target_scope", "HEAD"),
            })
        return {"success": False, "error": f"unknown coord action '{action}'"}

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

    def verify_receipt(self, task_id: str, criterion: str, passed: bool = True, command_id: str = "", evidence_id: str = "", details: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.post("/api/agent-state/verification", {
            "action": "receipt",
            "receipt": {
                "task_id": task_id,
                "criterion": criterion,
                "passed": passed,
                "command_id": command_id,
                "evidence_id": evidence_id,
                "details": details or {},
            },
        })

    def verify_completion(self, task_id: str) -> dict[str, Any]:
        return self.post("/api/agent-state/verification", {
            "action": "completion",
            "task_id": task_id,
        })

    def create_task(self, goal: str, acceptance_criteria: list[str] | None = None, task_id: str = "", scope: str = "task", **kwargs: Any) -> dict[str, Any]:
        payload = {
            "action": "create",
            "goal": goal,
            "acceptance_criteria": acceptance_criteria or [],
            "task_id": task_id,
            "scope": scope,
            **kwargs,
        }
        return self.post("/api/agent-state/tasks", payload)

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self.post("/api/agent-state/tasks", {"action": "get", "task_id": task_id})

    def list_tasks(
        self,
        status: str | None = None,
        limit: int = 100,
        query: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": "list", "limit": limit}
        if status:
            payload["status"] = status
        if query is not None:
            payload["query"] = query
        return self.post("/api/agent-state/tasks", payload)

    def complete_task(self, task_id: str, reason: str = "completed by agent") -> dict[str, Any]:
        return self.post("/api/agent-state/tasks", {"action": "complete", "task_id": task_id, "reason": reason})

    def fail_task(self, task_id: str, reason: str = "failed by agent") -> dict[str, Any]:
        return self.post("/api/agent-state/tasks", {"action": "fail", "task_id": task_id, "reason": reason})

    def checkpoint_task(self, task_id: str, phase: str = "", next_action: str = "", affected_paths: list[str] | None = None, **kwargs: Any) -> dict[str, Any]:
        payload = {
            "action": "checkpoint",
            "task_id": task_id,
            "phase": phase,
            "next_action": next_action,
            "affected_paths": affected_paths or [],
            **kwargs,
        }
        return self.post("/api/agent-state/tasks", payload)

    def record_memory(self, key: str, value: Any, scope: str = "task", kind: str = "fact", **kwargs: Any) -> dict[str, Any]:
        payload = {
            "action": "record",
            "key": key,
            "value": value,
            "scope": scope,
            "kind": kind,
            **kwargs,
        }
        return self.post("/api/agent-state/memory", payload)

    def find_memory(self, scope: str | None = None, key: str | None = None, query: str | None = None, limit: int = 100) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": "find", "limit": limit}
        if scope:
            payload["scope"] = scope
        if key:
            payload["key"] = key
        if query:
            payload["query"] = query
        return self.post("/api/agent-state/memory", payload)

    def continue_conversation(self, conversation_id: str, prompt: str, model: str | None = None, system: str | None = None, max_tokens: int | None = None, temperature: float | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "conversation_id": conversation_id,
            "task": prompt,
        }
        if model:
            payload["model"] = model
        if system:
            payload["system"] = system
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        return self.post("/api/conversations/continue", payload)

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
            "X-LocalAI-Tenant": self.tenant,
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
                def close_on_interrupt() -> None:
                    deadline = time.monotonic() + transport_timeout
                    while not monitor_stopped.is_set():
                        if cancel_event is not None and cancel_event.is_set():
                            try: resp.close()
                            except Exception: pass
                            return
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            if not monitor_stopped.is_set():
                                deadline_expired.set()
                                try: resp.close()
                                except Exception: pass
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
        except (URLError, OSError, http.client.HTTPException):
            if cancel_event is None or not cancel_event.is_set():
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

    def generate_types(self, root: str = ".", file: str = "", write_stub: bool = False) -> dict[str, Any]:
        return self.post("/api/repo/generate_types", {"root": root, "file": file, "write_stub": write_stub})

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

    def diff_hunk_stage(self, cwd: str = ".", patch: str = "") -> dict[str, Any]:
        return self.post("/api/command/diff_hunk_stage", {"cwd": cwd, "root": cwd, "patch": patch})

    def flaky_detect(self, cwd: str = ".", command: str = "", runs: int = 5, timeout: int = 30) -> dict[str, Any]:
        return self.post("/api/command/flaky_detect", {"cwd": cwd, "root": cwd, "command": command, "runs": runs, "timeout": timeout})

    def webhook_replay(self, url: str = "", payload: dict[str, Any] | str = "", secret: str = "", signature_header: str = "X-Hub-Signature-256") -> dict[str, Any]:
        return self.post("/api/command/webhook_replay", {"url": url, "payload": payload, "secret": secret, "signature_header": signature_header})

    def eval_drift(self, suite_name: str = "default") -> dict[str, Any]:
        return self.post("/api/task/eval_drift", {"suite_name": suite_name})

    def git_diff(self, root: str = ".", path: str | None = None, staged: bool = False, max_lines: int = 1000) -> dict[str, Any]:
        return self.post("/api/git/diff", {"root": root, "path": path, "staged": staged, "max_lines": max_lines})

    def git_history_search(self, root: str = ".", query: str = "", max_commits: int = 20) -> dict[str, Any]:
        return self.post("/api/git/history_search", {"root": root, "query": query, "max_commits": max_commits})

    def hotspots(self, root: str = ".", days: int = 30, limit: int = 20) -> dict[str, Any]:
        return self.post("/api/repo/hotspots", {"root": root, "days": days, "limit": limit})

    def generate_tests_for_diff(self, root: str = ".", diff: str | None = None, path: str | None = None) -> dict[str, Any]:
        return self.post("/api/repo/generate_tests_for_diff", {"root": root, "diff": diff, "path": path})

    def cross_repo_contract(self, backend_root: str = ".", frontend_root: str = ".") -> dict[str, Any]:
        return self.post("/api/repo/cross_repo_contract", {"backend_root": backend_root, "frontend_root": frontend_root})

    def mock_server(self, action: str = "status", root: str = ".", spec_path: str | None = None, port: int = 11440) -> dict[str, Any]:
        return self.post("/api/command/mock_server", {"action": action, "root": root, "spec_path": spec_path, "port": port})

    def ingest_diagram(self, workspace: str = "default", image_path: str = "", caption: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.post("/api/rag/ingest_diagram", {"workspace": workspace, "image_path": image_path, "caption": caption, "metadata": metadata})

    def curate_training_dataset(self, output_path: str = "training_dataset.jsonl", min_receipts: int = 1, format: str = "jsonl") -> dict[str, Any]:
        return self.post("/api/agent-state/tasks", {"action": "curate_dataset", "output_path": output_path, "min_receipts": min_receipts, "format": format})
