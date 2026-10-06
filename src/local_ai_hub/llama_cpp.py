"""Optional loopback llama.cpp SYCL adapter for Ollama-shaped Hub calls.

This adapter translates inference requests for explicitly mapped models when a
configured loopback llama.cpp server is healthy. Managed server installation
and process lifecycle live in :mod:`llama_cpp_runtime`.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import queue
import select
import socket
import ssl
import threading
import time
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPResponse
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, getproxies, proxy_bypass, urlopen
from .json_utils import dumps as json_dumps

_ORIGINAL_URLOPEN = urlopen


def _response_socket(response: Any) -> Any | None:
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    return getattr(raw, "_sock", None) or getattr(fp, "_sock", None)


def _set_response_timeout(response: Any, timeout: float) -> None:
    """Clamp the next blocking stream read to the request's remaining budget."""
    sock = _response_socket(response)
    set_timeout = getattr(sock, "settimeout", None)
    if callable(set_timeout):
        try:
            set_timeout(max(0.001, float(timeout)))
        except (OSError, TypeError, ValueError):
            pass


class _InterruptibleSocketReader:
    """File-like socket reader that checks cancellation during response reads."""

    _POLL_SECONDS = 0.05

    def __init__(self, sock: Any, deadline: float, should_stop: Any | None):
        self._sock = sock
        self._deadline = float(deadline)
        self._should_stop = should_stop
        self._buffer = bytearray()
        self._eof = False
        self._closed = False

    def _receive(self) -> None:
        while not self._eof:
            if self._closed:
                raise ValueError("read from closed response")
            if _stop_requested(self._should_stop):
                raise InterruptedError("request cancelled")
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("request deadline expired")
            try:
                pending = getattr(self._sock, "pending", None)
                if pending is not None and pending() > 0:
                    readable, exceptional = [self._sock], []
                else:
                    readable, _, exceptional = select.select(
                        [self._sock], [], [self._sock], min(self._POLL_SECONDS, remaining),
                    )
            except (OSError, ValueError):
                if _stop_requested(self._should_stop):
                    raise InterruptedError("request cancelled")
                if time.monotonic() >= self._deadline:
                    raise TimeoutError("request deadline expired")
                raise
            if exceptional:
                if _stop_requested(self._should_stop):
                    raise InterruptedError("request cancelled")
                raise OSError("response socket became exceptional")
            if not readable:
                continue
            try:
                self._sock.settimeout(min(self._POLL_SECONDS, remaining))
                chunk = self._sock.recv(65_536)
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                if _stop_requested(self._should_stop):
                    raise InterruptedError("request cancelled")
                raise
            if not chunk:
                self._eof = True
                break
            self._buffer.extend(chunk)
            return

    def read(self, size: int = -1) -> bytes:
        if size == 0:
            return b""
        if size is None or size < 0:
            while not self._eof:
                self._receive()
            size = len(self._buffer)
        while len(self._buffer) < size and not self._eof:
            self._receive()
        take = min(size, len(self._buffer))
        value = bytes(self._buffer[:take])
        del self._buffer[:take]
        return value

    def readline(self, size: int = -1) -> bytes:
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                take = newline + 1
                if size >= 0:
                    take = min(take, size)
                break
            if size >= 0 and len(self._buffer) >= size:
                take = size
                break
            if self._eof:
                take = len(self._buffer)
                break
            self._receive()
        value = bytes(self._buffer[:take])
        del self._buffer[:take]
        return value

    def flush(self) -> None:
        """Satisfy HTTPResponse's file-like cleanup contract; reads are unbuffered."""

    def close(self) -> None:
        self._closed = True
        self._buffer.clear()


def _stop_requested(should_stop: Any | None) -> bool:
    if should_stop is None:
        return False
    try:
        return bool(should_stop())
    except Exception:
        return False


_DNS_RESOLUTION_SLOTS = threading.BoundedSemaphore(4)


def _is_ip_literal(host: str) -> bool:
    clean = host.strip("[]")
    try:
        ipaddress.ip_address(clean)
        return True
    except (ValueError, TypeError):
        return False


def _resolve_interruptibly(host: str, port: int, remaining: Any) -> list[tuple[Any, ...]]:
    """Resolve a host without letting a stalled system resolver hold the request."""
    if _is_ip_literal(host):
        try:
            return socket.getaddrinfo(
                host, port, 0, socket.SOCK_STREAM, 0, socket.AI_NUMERICHOST,
            )
        except socket.gaierror:
            pass

    while not _DNS_RESOLUTION_SLOTS.acquire(timeout=min(0.025, remaining())):
        remaining()

    result: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def resolve() -> None:
        try:
            result.put((True, socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)))
        except Exception as exc:
            result.put((False, exc))
        finally:
            _DNS_RESOLUTION_SLOTS.release()

    resolver = threading.Thread(target=resolve, name="lah-dns", daemon=True)
    try:
        resolver.start()
    except Exception:
        _DNS_RESOLUTION_SLOTS.release()
        raise

    while True:
        try:
            resolved, value = result.get(timeout=min(0.025, remaining()))
        except queue.Empty:
            continue
        if resolved:
            return value
        raise value

def _tls_handshake_interruptibly(sock: ssl.SSLSocket, remaining: Any) -> None:
    """Complete TLS setup while honoring the request's cancellation and deadline."""
    sock.setblocking(False)
    while True:
        timeout = remaining()
        try:
            sock.do_handshake()
        except ssl.SSLWantReadError:
            _, _, exceptional = select.select([sock], [], [sock], min(0.025, timeout))
        except ssl.SSLWantWriteError:
            _, _, exceptional = select.select([], [sock], [sock], min(0.025, timeout))
        except (OSError, ValueError):
            remaining()
            raise
        else:
            sock.settimeout(remaining())
            return
        if exceptional:
            remaining()
            raise OSError("TLS handshake socket became exceptional")



def _http_proxy_for_url(parsed: Any) -> tuple[str, int, str | None] | None:
    """Return configured HTTP proxy host, port and optional Basic credentials."""
    host = parsed.hostname
    if proxy_bypass(host):
        return None
    if parsed.port is not None:
        authority = f"[{host}]:{parsed.port}" if ":" in host and not host.startswith("[") else f"{host}:{parsed.port}"
        if proxy_bypass(authority):
            return None
    configured = getproxies().get(parsed.scheme.lower())
    if not configured:
        return None
    proxy = urlsplit(configured if "://" in configured else f"http://{configured}")
    if proxy.scheme.lower() != "http" or not proxy.hostname:
        raise ValueError("interruptible transport requires an HTTP proxy URL")
    authorization = None
    if proxy.username is not None:
        credentials = f"{unquote(proxy.username)}:{unquote(proxy.password or '')}".encode("utf-8")
        authorization = "Basic " + base64.b64encode(credentials).decode("ascii")
    return proxy.hostname, proxy.port or 80, authorization


def _read_response_body(response: Any, deadline: float, should_stop: Any | None = None) -> bytes:
    """Read metadata bodies in chunks while honoring cancellation and deadline."""
    read_chunk = getattr(response, "read1", None)
    if not callable(read_chunk):
        if _stop_requested(should_stop):
            raise InterruptedError("request cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("request deadline expired")
        _set_response_timeout(response, remaining)
        return response.read()

    chunks: list[bytes] = []
    while True:
        if _stop_requested(should_stop):
            raise InterruptedError("request cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("request deadline expired")
        _set_response_timeout(response, remaining)
        chunk = read_chunk(65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


@contextmanager
def _cancel_response_on_stop(response: Any, should_stop: Any | None, deadline: float | None = None):
    """Close a blocked response socket when cancelled or its deadline expires."""
    sock = _response_socket(response)
    if (should_stop is None and deadline is None) or sock is None or not (callable(getattr(sock, "shutdown", None)) or callable(getattr(sock, "close", None))):
        yield
        return

    done = threading.Event()

    def close_when_stopped() -> None:
        while not done.wait(0.05):
            if not _stop_requested(should_stop) and (deadline is None or time.monotonic() < deadline):
                continue
            try:
                shutdown = getattr(sock, "shutdown", None)
                if callable(shutdown):
                    shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                close = getattr(sock, "close", None)
                if callable(close):
                    close()
            except Exception:
                pass
            return

    monitor = threading.Thread(target=close_when_stopped, name="lah-stream-cancel", daemon=True)
    monitor.start()
    try:
        yield
    finally:
        done.set()
        monitor.join(timeout=0.2)


@contextmanager
def _open_interruptible_response(request: Request, deadline: float, should_stop: Any | None):
    """Open HTTP request with absolute-deadline and cancellation enforcement."""
    import urllib.request
    active_urlopen = urlopen if urlopen is not _ORIGINAL_URLOPEN else urllib.request.urlopen
    if active_urlopen is not _ORIGINAL_URLOPEN:
        remaining_time = max(0.001, float(deadline) - time.monotonic())
        resp = active_urlopen(request, timeout=remaining_time)
        try:
            yield resp
        finally:
            if hasattr(resp, "close"):
                try:
                    resp.close()
                except Exception:
                    pass
        return

    current_url = request.full_url
    method = request.get_method()
    body = request.data
    headers = dict(request.header_items())

    def remaining() -> float:
        if _stop_requested(should_stop):
            raise InterruptedError("request cancelled")
        value = float(deadline) - time.monotonic()
        if value <= 0:
            raise TimeoutError("request deadline expired")
        return value

    for redirect_count in range(11):
        parsed = urlsplit(current_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("interruptible request requires an HTTP URL")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        proxy_info = _http_proxy_for_url(parsed)
        connect_host, connect_port = (proxy_info[0], proxy_info[1]) if proxy_info else (parsed.hostname, port)
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        connection = HTTPConnection(connect_host, connect_port, timeout=max(0.001, remaining()))
        if proxy_info is not None and parsed.scheme == "https":
            tunnel_headers = {}
            if proxy_info[2]:
                tunnel_headers["Proxy-Authorization"] = proxy_info[2]
            connection.set_tunnel(parsed.hostname, port, headers=tunnel_headers)
        finished = threading.Event()
        monitor = threading.Thread(
            target=lambda: _interrupt_connection_when_stopped(connection, should_stop, deadline, finished),
            name="lah-open-cancel",
            daemon=True,
        )
        response = None
        opened = False
        redirect_url = None
        monitor.start()
        try:
            connection.timeout = remaining()
            _connect_interruptibly(connection, remaining)
            if proxy_info is not None and parsed.scheme == "https":
                connection._tunnel()
            if parsed.username is not None and not any(name.lower() == "authorization" for name in headers):
                credentials = f"{unquote(parsed.username)}:{unquote(parsed.password or '')}".encode("utf-8")
                headers["Authorization"] = "Basic " + base64.b64encode(credentials).decode("ascii")
            if parsed.scheme == "https":
                connection.sock.settimeout(remaining())
                tls_sock = ssl.create_default_context().wrap_socket(
                    connection.sock, server_hostname=parsed.hostname,
                    do_handshake_on_connect=False,
                )
                connection.sock = tls_sock
                _tls_handshake_interruptibly(tls_sock, remaining)
            request_headers = dict(headers)
            request_target = target
            if proxy_info is not None and parsed.scheme == "http":
                host = parsed.hostname
                if ":" in host and not host.startswith("["):
                    host = f"[{host}]"
                authority = f"{host}:{parsed.port}" if parsed.port is not None else host
                request_headers.setdefault("Host", authority)
                if proxy_info[2]:
                    request_headers["Proxy-Authorization"] = proxy_info[2]
                request_target = urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, ""))
            elif proxy_info is not None:
                request_headers = {
                    key: value for key, value in request_headers.items()
                    if key.lower() != "proxy-authorization"
                }
            connection.sock.settimeout(remaining())
            connection.request(method, request_target, body=body, headers=request_headers)
            connection.sock.settimeout(remaining())
            response = HTTPResponse(connection.sock, method=method)
            response.fp.close()
            response.fp = _InterruptibleSocketReader(connection.sock, deadline, should_stop)
            response.begin()
            remaining()
            if response.status in {301, 302, 303, 307, 308} and response.getheader("Location"):
                redirect_url = urljoin(current_url, response.getheader("Location"))
            elif response.status >= 400:
                error_body = response.read(65_537)[:65_536]
                raise HTTPError(current_url, response.status, response.reason, response.headers, BytesIO(error_body))
            else:
                opened = True
        except Exception as exc:
            try:
                remaining()
            except InterruptedError as cancelled:
                raise cancelled from exc
            except TimeoutError as expired:
                raise expired from exc
            raise
        finally:
            finished.set()
            monitor.join(timeout=0.2)
            if not opened:
                if response is not None:
                    response.close()
                connection.close()

        if redirect_url is not None:
            if redirect_count >= 10:
                raise HTTPError(current_url, response.status, "redirect limit exceeded", response.headers, BytesIO())
            next_origin = urlsplit(redirect_url)
            if (parsed.scheme.lower(), parsed.hostname.lower(), port) != (
                next_origin.scheme.lower(), (next_origin.hostname or "").lower(),
                next_origin.port or (443 if next_origin.scheme == "https" else 80),
            ):
                headers = {key: value for key, value in headers.items() if key.lower() not in {"authorization", "cookie"}}
            headers = {key: value for key, value in headers.items() if key.lower() != "host"}
            if (response.status in {301, 302} and method.upper() == "POST") or (
                response.status == 303 and method.upper() != "HEAD"
            ):
                method = "GET"
                body = None
                headers = {key: value for key, value in headers.items() if key.lower() not in {"content-length", "content-type", "transfer-encoding"}}
            current_url = redirect_url
            continue

        try:
            remaining()
            yield response
        finally:
            try:
                response.close()
            except Exception:
                pass
            connection.close()
        return


def _connect_interruptibly(connection: HTTPConnection, remaining: Any) -> None:
    """Publish the socket before connect so the monitor can close it on stop."""
    last_error: OSError | None = None
    addresses = _resolve_interruptibly(connection.host, connection.port, remaining)
    for family, socktype, proto, _canonname, sockaddr in addresses:
        timeout = remaining()
        sock = socket.socket(family, socktype, proto)
        connection.sock = sock
        try:
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            return
        except OSError as exc:
            last_error = exc
            connection.sock = None
            sock.close()
            remaining()
    if last_error is not None:
        raise last_error
    raise OSError("no address returned for HTTP host")


def _interrupt_connection_when_stopped(connection: Any, should_stop: Any, deadline: float, finished: threading.Event) -> None:
    while not finished.wait(0.025):
        cancelled = _stop_requested(should_stop)
        expired = time.monotonic() >= float(deadline)
        if not cancelled and not expired:
            continue
        sock = getattr(connection, "sock", None)
        if sock is None:
            # connect() may not have published its socket yet; keep watching so
            # a just-created socket cannot proceed to request headers unchecked.
            continue
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass
        return


def _loopback_url(value: Any) -> str:
    url = str(value or "").strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return ""
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        return ""
    return url


class LlamaCppRouter:
    """Translate mapped Ollama chat/generate calls to local OpenAI-compatible APIs."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.settings = config.get("llama_cpp", {}) if isinstance(config.get("llama_cpp", {}), dict) else {}
        self._health_lock = threading.Lock()
        self._health: dict[str, tuple[float, bool]] = {}
        self._models: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}

    def _hardware_allows(self) -> bool:
        mode = str(self.settings.get("mode", "auto")).strip().lower()
        if mode == "off":
            return False
        if mode == "on":
            return True
        # Auto mode is external-only, not hardware-gated: a loopback endpoint
        # explicitly present in config is the operator's provider choice.
        return mode == "auto"

    def hardware_enabled(self) -> bool:
        """Expose whether this adapter can serve routes on the current host."""
        return self._hardware_allows()

    def _entry(self, model: str) -> tuple[dict[str, Any], str] | None:
        if not self._hardware_allows():
            return None
        models = self.settings.get("models", {})
        raw = models.get(str(model or "").strip()) if isinstance(models, dict) else None
        if not isinstance(raw, dict):
            return None
        url = _loopback_url(raw.get("url"))
        if not url:
            return None
        return raw, url

    def supports_model(self, model: str) -> bool:
        models = self.settings.get("models", {})
        return isinstance(models, dict) and isinstance(models.get(str(model or "").strip()), dict)

    def _healthy(
        self,
        url: str,
        timeout: float,
        should_stop: Any | None = None,
        deadline: float | None = None,
    ) -> bool:
        now = time.monotonic()
        request_deadline = now + max(0.001, float(timeout))
        if deadline is not None:
            request_deadline = min(request_deadline, float(deadline))
        if request_deadline <= now or _stop_requested(should_stop):
            return False
        with self._health_lock:
            cached = self._health.get(url)
            if cached and now - cached[0] < 1.0:
                return cached[1]
        healthy = False
        try:
            req = Request(f"{url}/health", headers={"Accept": "application/json"})
            remaining = request_deadline - time.monotonic()
            if remaining <= 0:
                return False
            with _open_interruptible_response(req, request_deadline, should_stop) as response, _cancel_response_on_stop(response, should_stop, request_deadline):
                healthy = 200 <= int(getattr(response, "status", 200)) < 300
        except Exception:
            healthy = False
        if _stop_requested(should_stop) or time.monotonic() >= request_deadline:
            return False
        with self._health_lock:
            self._health[url] = (time.monotonic(), healthy)
        return healthy

    def _model_info(
        self,
        url: str,
        timeout: float = 0.8,
        should_stop: Any | None = None,
        deadline: float | None = None,
        *,
        force_refresh: bool = False,
        strict: bool = False,
    ) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        request_deadline = now + min(max(0.001, float(timeout)), 1.0)
        if deadline is not None:
            request_deadline = min(request_deadline, float(deadline))
        if request_deadline <= now or _stop_requested(should_stop):
            if strict:
                raise TimeoutError("llama.cpp model inventory deadline expired")
            return {}
        with self._health_lock:
            cached = self._models.get(url)
            if not force_refresh and cached and now - cached[0] < 1.0:
                return cached[1]
        result: dict[str, dict[str, Any]] = {}
        try:
            req = Request(f"{url}/models", headers={"Accept": "application/json"})
            remaining = request_deadline - time.monotonic()
            if remaining <= 0:
                if strict:
                    raise TimeoutError("llama.cpp model inventory deadline expired")
                return {}
            with _open_interruptible_response(req, request_deadline, should_stop) as response, _cancel_response_on_stop(response, should_stop, request_deadline):
                body = json.loads(_read_response_body(response, request_deadline, should_stop).decode("utf-8", errors="replace") or "{}")
            rows = body.get("data") if isinstance(body, dict) else None
            if not isinstance(rows, list):
                if strict:
                    raise ValueError("llama.cpp model inventory response is incomplete")
            else:
                for row in rows:
                    if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip():
                        if strict:
                            raise ValueError("llama.cpp model inventory contains an invalid model row")
                        continue
                    result[row["id"].strip()] = row
        except TimeoutError:
            if strict:
                raise
        except Exception as exc:
            if strict:
                raise RuntimeError("llama.cpp model inventory unavailable") from exc
        if _stop_requested(should_stop) or time.monotonic() >= request_deadline:
            if strict:
                raise TimeoutError("llama.cpp model inventory deadline expired")
            return {}
        with self._health_lock:
            self._models[url] = (time.monotonic(), result)
        return result

    def ready_for_model(
        self,
        model: str,
        *,
        should_stop: Any | None = None,
        deadline: float | None = None,
    ) -> bool:
        selected = self._entry(model)
        if not selected:
            return False
        entry, url = selected
        if not self._healthy(url, 0.6, should_stop=should_stop, deadline=deadline):
            return False
        alias = str(entry.get("served_model") or model)
        return alias in self._model_info(url, should_stop=should_stop, deadline=deadline)

    def ensure_model(
        self,
        model: str,
        timeout: float | None = None,
        should_stop: Any | None = None,
        *,
        deadline: float | None = None,
    ) -> bool:
        def stopped() -> bool:
            if should_stop is None:
                return False
            try:
                return bool(should_stop())
            except Exception:
                return False

        if stopped():
            return False
        selected = self._entry(model)
        if not selected:
            return False
        entry, url = selected
        total_timeout = min(max(0.05, float(timeout if timeout is not None else 60.0)), 300.0)
        started = time.monotonic()
        deadline = min(started + total_timeout, float(deadline)) if deadline is not None else started + total_timeout

        def remaining() -> float:
            return max(0.0, deadline - time.monotonic())

        budget = remaining()
        if budget <= 0 or not self._healthy(url, min(budget, 0.6), should_stop=should_stop, deadline=deadline):
            return False
        alias = str(entry.get("served_model") or model)
        budget = remaining()
        if budget <= 0:
            return False
        models = self._model_info(url, timeout=min(budget, 0.8), should_stop=should_stop, deadline=deadline)
        if alias not in models:
            return False
        row = models[alias]
        status = row.get("status", {}) if isinstance(row.get("status"), dict) else {}
        state = str(status.get("value", "")).lower()
        if state == "loaded":
            return True
        if state != "loading":
            try:
                budget = remaining()
                if budget <= 0 or stopped():
                    return False
                body = json_dumps({"model": alias}).encode("utf-8")
                req = Request(f"{url}/models/load", data=body, headers={"Content-Type": "application/json"})
                with _open_interruptible_response(req, deadline, should_stop) as response, _cancel_response_on_stop(response, should_stop, deadline):
                    loaded = json.loads(_read_response_body(response, deadline, should_stop).decode("utf-8", errors="replace") or "{}")
                if isinstance(loaded, dict) and loaded.get("success") is False:
                    return False
            except Exception:
                return False
        while remaining() > 0:
            if stopped():
                return False
            budget = remaining()
            if budget <= 0:
                break
            self._models.pop(url, None)
            current = self._model_info(
                url, timeout=min(budget, 0.8), should_stop=should_stop, deadline=deadline,
            ).get(alias, {})
            current_status = current.get("status", {}) if isinstance(current.get("status"), dict) else {}
            value = str(current_status.get("value", "")).lower()
            if value == "loaded":
                return True
            if current_status.get("failed"):
                return False
            time.sleep(min(0.25, remaining()))
        return False

    def available_models(
        self,
        *,
        should_stop: Any | None = None,
        deadline: float | None = None,
    ) -> list[str]:
        models = self.settings.get("models", {})
        if not isinstance(models, dict) or not self._hardware_allows():
            return []
        available: list[str] = []
        for model, entry in models.items():
            if _stop_requested(should_stop) or (deadline is not None and time.monotonic() >= deadline):
                break
            if not isinstance(entry, dict):
                continue
            selected = self._entry(str(model))
            if selected and self._healthy(selected[1], 0.6, should_stop=should_stop, deadline=deadline):
                alias = str(entry.get("served_model") or model)
                if alias in self._model_info(selected[1], should_stop=should_stop, deadline=deadline):
                    available.append(str(model))
        return available

    def is_online(self) -> bool:
        return bool(self.available_models())

    def loaded_model_inventory(
        self,
        *,
        should_stop: Any | None = None,
        deadline: float | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        models = self.settings.get("models", {})
        mode = str(self.settings.get("mode", "auto")).strip().lower()
        if mode == "off" or not models:
            return {"complete": True, "models": [], "errors": {}, "endpoint_status": {}}
        if not isinstance(models, dict):
            return {"complete": False, "models": [], "errors": {"configuration": "invalid model map"}, "endpoint_status": {}}

        by_endpoint: dict[str, list[str]] = {}
        errors: dict[str, str] = {}
        endpoint_status: dict[str, str] = {}
        for model, entry in models.items():
            selected = self._entry(str(model))
            if selected is None:
                errors[str(model)] = "configured endpoint unavailable"
                endpoint_status[str(model)] = "unknown"
                continue
            by_endpoint.setdefault(selected[1], []).append(str(model))

        rows: list[dict[str, Any]] = []
        for url, configured_names in by_endpoint.items():
            if _stop_requested(should_stop) or (deadline is not None and time.monotonic() >= deadline):
                for name in configured_names:
                    errors[name] = "inventory cancelled or deadline exceeded"
                    endpoint_status[name] = "unknown"
                continue
            try:
                served = self._model_info(
                    url, should_stop=should_stop, deadline=deadline,
                    force_refresh=force_refresh, strict=True,
                )
                active_rows: list[dict[str, Any]] = []
                for served_id, detail in served.items():
                    status = detail.get("status") if isinstance(detail, dict) else None
                    state = str(status.get("value", "")).strip().lower() if isinstance(status, dict) else ""
                    if state not in {"loaded", "loading", "unloaded", "failed", "unavailable"}:
                        raise ValueError("llama.cpp model inventory omitted a usable load status")
                    if state in {"loaded", "loading"}:
                        active_rows.append({
                            "name": served_id,
                            "model": served_id,
                            "status": state,
                            "parameter_size": "",
                            "quantization": "GGUF",
                            "size_bytes": 0,
                            "vram_bytes": 0,
                            "cpu_bytes": 0,
                            "gpu_fraction": 0.0,
                            "cpu_offload_fraction": 0.0,
                            "context_length": 0,
                            "backend": "llama.cpp-sycl",
                            "endpoint_url": url,
                        })
                rows.extend(active_rows)
                for name in configured_names:
                    endpoint_status[name] = "complete"
            except Exception as exc:
                reason = "cancelled" if _stop_requested(should_stop) else (
                    "deadline exceeded" if isinstance(exc, TimeoutError) else type(exc).__name__
                )
                for name in configured_names:
                    errors[name] = reason
                    endpoint_status[name] = "unknown"
        return {
            "complete": not errors and len(endpoint_status) == len(models),
            "models": rows,
            "errors": errors,
            "endpoint_status": endpoint_status,
        }

    def loaded_model_details(
        self,
        *,
        should_stop: Any | None = None,
        deadline: float | None = None,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        if not force_refresh:
            now = time.monotonic()
            if now - self._models.get("__loaded_details__", (0.0, {}))[0] < 1.0:
                cached = self._models.get("__loaded_details__", (0.0, {}))[1]
                if isinstance(cached, list):
                    return list(cached)
        inventory = self.loaded_model_inventory(
            should_stop=should_stop, deadline=deadline, force_refresh=force_refresh,
        )
        if inventory["complete"] is not True:
            raise RuntimeError("llama.cpp loaded-model inventory is incomplete")
        rows = inventory["models"]
        self._models["__loaded_details__"] = (time.monotonic(), rows)
        return list(rows)

    def model_capabilities(self, model: str) -> dict[str, Any] | None:
        """Expose Ollama-shaped capability metadata for a mapped model.

        The local llama.cpp router publishes model metadata through its
        OpenAI-compatible ``/models`` endpoint, not Ollama's ``/api/show``.
        Keep this adapter-specific so callers can run capability preflights
        without enabling or starting Ollama.
        """
        selected = self._entry(model)
        if not selected:
            return None
        entry, url = selected
        if not self._healthy(url, 0.6):
            return None
        alias = str(entry.get("served_model") or model)
        row = self._model_info(url).get(alias)
        if not isinstance(row, dict):
            return {"error": f"model not found: {model}"}
        architecture = row.get("architecture", {})
        architecture = architecture if isinstance(architecture, dict) else {}
        modalities = architecture.get("input_modalities", [])
        modalities = modalities if isinstance(modalities, list) else []
        lowered = {str(value).strip().lower() for value in modalities}
        capabilities = ["completion"]
        if lowered.intersection({"image", "video"}):
            capabilities.append("vision")
        if "audio" in lowered:
            capabilities.append("audio")
        return {
            "model": model,
            "capabilities": capabilities,
            "details": {"architecture": architecture},
        }

    def unload_model(
        self,
        model: str,
        *,
        endpoint_url: str | None = None,
        should_stop: Any | None = None,
        deadline: float | None = None,
    ) -> bool:
        selected = self._entry(model)
        if selected is None:
            models = self.settings.get("models", {})
            if isinstance(models, dict):
                for configured_name, configured_entry in models.items():
                    if not isinstance(configured_entry, dict):
                        continue
                    if str(configured_entry.get("served_model") or "") == str(model):
                        selected = self._entry(str(configured_name))
                        if selected:
                            break
        if endpoint_url is not None:
            requested_url = _loopback_url(endpoint_url)
            configured_urls = {
                _loopback_url(entry.get("url"))
                for entry in self.settings.get("models", {}).values()
                if isinstance(entry, dict)
            } if isinstance(self.settings.get("models", {}), dict) else set()
            if not requested_url or requested_url not in configured_urls:
                return False
            selected = ({}, requested_url)
            alias = str(model or "").strip()
        elif selected:
            entry, _url = selected
            alias = str(model) if str(entry.get("served_model") or "") == str(model) else str(entry.get("served_model") or model)
        else:
            return False
        if not selected or not alias:
            return False
        _entry, url = selected
        try:
            body = json_dumps({"model": alias}).encode("utf-8")
            req = Request(f"{url}/models/unload", data=body, headers={"Content-Type": "application/json"})
            if should_stop is not None or deadline is not None:
                request_deadline = time.monotonic() + 5.0
                if deadline is not None:
                    request_deadline = min(request_deadline, float(deadline))
                if _stop_requested(should_stop) or request_deadline <= time.monotonic():
                    return False
                with _open_interruptible_response(req, request_deadline, should_stop) as response, _cancel_response_on_stop(
                    response, should_stop, request_deadline,
                ):
                    raw = _read_response_body(response, request_deadline, should_stop)
                result = json.loads(raw.decode("utf-8", errors="replace") or "{}")
            else:
                with urlopen(req, timeout=5.0) as response:
                    result = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
            self._models.pop(url, None)
            return bool(isinstance(result, dict) and result.get("success", False))
        except Exception:
            return False

    @staticmethod
    def _messages(endpoint: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if endpoint == "/api/chat":
            messages = payload.get("messages", [])
            if not isinstance(messages, list):
                return []
            converted: list[dict[str, Any]] = []
            for item in messages:
                if not isinstance(item, dict):
                    continue
                message = dict(item)
                if message.get("role") == "tool" and message.get("tool_name") and not message.get("name"):
                    message["name"] = message.pop("tool_name")
                converted.append(message)
            return converted
        messages = []
        system = str(payload.get("system", "") or "")
        prompt = str(payload.get("prompt", "") or "")
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    @staticmethod
    def _openai_payload(endpoint: str, payload: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
        options = payload.get("options", {})
        options = options if isinstance(options, dict) else {}
        result: dict[str, Any] = {
            "model": str(entry.get("served_model") or payload.get("model") or ""),
            "messages": LlamaCppRouter._messages(endpoint, payload),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        for source, target in (
            ("num_predict", "max_tokens"), ("temperature", "temperature"), ("top_p", "top_p"),
            ("top_k", "top_k"), ("seed", "seed"), ("stop", "stop"),
            ("repeat_penalty", "repeat_penalty"),
        ):
            if source in options:
                result[target] = options[source]
        if isinstance(payload.get("tools"), list):
            result["tools"] = payload["tools"]
        fmt = payload.get("format")
        if fmt == "json":
            result["response_format"] = {"type": "json_object"}
        elif isinstance(fmt, dict):
            if fmt.get("type") == "json_schema" or fmt.get("type") == "json_object":
                result["response_format"] = fmt
            else:
                result["response_format"] = {"type": "json_schema", "schema": fmt}
        return result

    @staticmethod
    def _tool_calls(state: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        for index in sorted(state):
            item = state[index]
            function = item.get("function", {})
            raw_args = str(function.get("arguments", "") or "")
            try:
                arguments: Any = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                arguments = raw_args
            calls.append({
                "id": str(item.get("id", "")),
                "type": "function",
                "function": {"name": str(function.get("name", "")), "arguments": arguments},
            })
        return calls

    def request_stream(
        self,
        endpoint: str,
        payload: dict[str, Any] | None,
        on_chunk: Any,
        timeout: float | None = None,
        should_stop: Any | None = None,
        on_thinking: Any | None = None,
        deadline: float | None = None,
    ) -> dict[str, Any] | None:
        if endpoint not in {"/api/chat", "/api/generate"} or not isinstance(payload, dict):
            return None
        selected = self._entry(str(payload.get("model", "")))
        if not selected:
            return None
        entry, url = selected
        options = payload.get("options", {})
        try:
            requested_ctx = int(options.get("num_ctx", 0) or 0) if isinstance(options, dict) else 0
        except (TypeError, ValueError):
            requested_ctx = 0
        configured_ctx = int(entry.get("context_length", 0) or 0)
        if requested_ctx and configured_ctx and requested_ctx > configured_ctx:
            return {"_lah_backend_unavailable": f"SYCL server context is {configured_ctx}, request needs {requested_ctx}"}
        started = time.monotonic()
        timeout_budget = max(0.05, float(timeout if timeout is not None else self.config.get("server", {}).get("request_timeout_seconds", 300)))
        request_deadline = started + timeout_budget
        if deadline is not None:
            request_deadline = min(request_deadline, float(deadline))
        deadline = request_deadline
        total_timeout = max(0.0, deadline - started)

        def stopped() -> bool:
            if should_stop is None:
                return False
            try:
                return bool(should_stop())
            except Exception:
                return False

        def timed_out() -> dict[str, Any]:
            return {
                "error": f"llama.cpp request timed out after {total_timeout:g}s",
                "timed_out": True,
                "_lah_provider": "llama.cpp-sycl",
            }

        if total_timeout <= 0:
            return timed_out()
        if stopped():
            return {"success": False, "preempted": True, "error": "background request preempted before model readiness", "_lah_provider": "llama.cpp-sycl"}
        load_timeout = min(total_timeout, max(0.05, float(self.settings.get("model_load_timeout_seconds", 600))))
        load_deadline = min(deadline, time.monotonic() + load_timeout)
        if not self.ensure_model(
            str(payload.get("model", "")), timeout=load_timeout, should_stop=should_stop,
            deadline=load_deadline,
        ):
            if time.monotonic() >= deadline:
                return timed_out()
            if stopped():
                return {"success": False, "preempted": True, "error": "background request preempted during model readiness", "_lah_provider": "llama.cpp-sycl"}
            if time.monotonic() >= load_deadline:
                return {
                    "error": "llama.cpp model readiness timed out",
                    "timed_out": True,
                    "_lah_provider": "llama.cpp-sycl",
                }
            return {"_lah_backend_unavailable": "local llama.cpp SYCL server is not ready"}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return timed_out()
        try:
            from .ollama import RepetitionWatchdog
        except Exception:
            return {"error": "repetition watchdog unavailable"}

        body = json_dumps(self._openai_payload(endpoint, payload, entry)).encode("utf-8")
        req = Request(
            urljoin(f"{url.rstrip('/')}/", "v1/chat/completions"), data=body,
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        )
        watchdog = RepetitionWatchdog(max_repeat=3)
        text_parts: list[str] = []
        tool_state: dict[int, dict[str, Any]] = {}
        prompt_tokens = output_tokens = 0
        finish_reason: str | None = None
        try:
            with _open_interruptible_response(req, deadline, should_stop) as response, _cancel_response_on_stop(response, should_stop, deadline):
                response_lines = iter(response)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return timed_out()
                    if stopped():
                        return {"success": False, "preempted": True, "error": "background request preempted by foreground work", "_lah_provider": "llama.cpp-sycl"}
                    _set_response_timeout(response, remaining)
                    try:
                        raw_line = next(response_lines)
                    except StopIteration:
                        break
                    except socket.timeout:
                        if stopped():
                            return {"success": False, "preempted": True, "error": "background request preempted by foreground work", "_lah_provider": "llama.cpp-sycl"}
                        return timed_out()
                    if time.monotonic() >= deadline:
                        return timed_out()
                    if stopped():
                        return {"success": False, "preempted": True, "error": "background request preempted by foreground work", "_lah_provider": "llama.cpp-sycl"}
                    line = (raw_line if isinstance(raw_line, str) else raw_line.decode("utf-8", errors="replace")).strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk, dict) and chunk.get("error"):
                        return {"error": f"llama.cpp: {chunk['error']}", "_lah_provider": "llama.cpp-sycl"}
                    usage = chunk.get("usage", {}) if isinstance(chunk, dict) else {}
                    if isinstance(usage, dict):
                        prompt_tokens = int(usage.get("prompt_tokens", prompt_tokens) or prompt_tokens)
                        output_tokens = int(usage.get("completion_tokens", output_tokens) or output_tokens)
                    choices = chunk.get("choices", []) if isinstance(chunk, dict) else []
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0] if isinstance(choices[0], dict) else {}
                    delta = choice.get("delta", {}) if isinstance(choice.get("delta"), dict) else {}
                    content = delta.get("content")
                    if content:
                        text = str(content)
                        text_parts.append(text)
                        try:
                            on_chunk(text)
                        except Exception:
                            pass
                        if watchdog.push(text):
                            return {"error": "model output repetition loop detected", "_lah_repetition_loop_detected": True, "_lah_provider": "llama.cpp-sycl"}
                    for tool in delta.get("tool_calls", []) if isinstance(delta.get("tool_calls"), list) else []:
                        if not isinstance(tool, dict):
                            continue
                        index = int(tool.get("index", 0) or 0)
                        accumulated = tool_state.setdefault(index, {"id": "", "function": {"name": "", "arguments": ""}})
                        if tool.get("id"):
                            accumulated["id"] = str(tool["id"])
                        fn = tool.get("function", {})
                        if isinstance(fn, dict):
                            if fn.get("name"):
                                accumulated["function"]["name"] += str(fn["name"])
                            if fn.get("arguments"):
                                accumulated["function"]["arguments"] += str(fn["arguments"])
                    if choice.get("finish_reason"):
                        finish_reason = str(choice["finish_reason"])
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            return {"error": f"llama.cpp HTTP {exc.code}: {detail}", "_lah_provider": "llama.cpp-sycl"}
        except (URLError, socket.timeout, TimeoutError) as exc:
            if stopped():
                return {"success": False, "preempted": True, "error": "background request preempted by foreground work", "_lah_provider": "llama.cpp-sycl"}
            if time.monotonic() >= deadline:
                return timed_out()
            reason = getattr(exc, "reason", None)
            if isinstance(exc, (socket.timeout, TimeoutError)) or isinstance(reason, (socket.timeout, TimeoutError)):
                return timed_out()
            return {"error": f"llama.cpp request failed: {exc}", "_lah_provider": "llama.cpp-sycl"}
        except Exception as exc:
            if stopped():
                return {"success": False, "preempted": True, "error": "background request preempted by foreground work", "_lah_provider": "llama.cpp-sycl"}
            if time.monotonic() >= deadline:
                return timed_out()
            return {"error": f"llama.cpp request failed: {type(exc).__name__}: {exc}", "_lah_provider": "llama.cpp-sycl"}

        text = "".join(text_parts)
        result: dict[str, Any] = {
            "done": True,
            "response": text,
            "prompt_eval_count": prompt_tokens,
            "eval_count": output_tokens,
            "_lah_retry_count": 0,
            "_lah_provider": "llama.cpp-sycl",
        }
        if endpoint == "/api/chat":
            result["message"] = {"role": "assistant", "content": text}
            if tool_state:
                result["message"]["tool_calls"] = self._tool_calls(tool_state)
        if finish_reason:
            result["done_reason"] = finish_reason
        return result
