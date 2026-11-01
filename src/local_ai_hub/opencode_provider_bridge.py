"""Experimental loopback OpenAI-compatible streaming bridge; not auto-started."""
from __future__ import annotations

import http.client
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .opencode_inference_session import ExternalInferenceSession, InferenceSessionError

_MAX_BODY = 4 * 1024 * 1024
_MAX_RESPONSE = 64 * 1024 * 1024
_MAX_STATUS = 64 * 1024


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _preflight_connection(connection: http.client.HTTPConnection, model: str, peer_verifier: Any) -> Any:
    """Check the exact connection that will carry the inference request."""
    from .opencode_models import canonical_model

    connection.connect()
    original = connection.sock
    if original is None:
        raise OSError("upstream connection unavailable")
    if not callable(peer_verifier):
        raise OSError("upstream peer verification unavailable")
    peer_verifier(original)
    def get_json(path: str) -> Any:
        if connection.sock is not original:
            raise OSError("upstream connection changed")
        connection.request("GET", path, headers={"Connection": "keep-alive"})
        response = connection.getresponse()
        if response.status != 200 or response.will_close:
            raise OSError("upstream preflight unavailable")
        expected_length = response.length
        deadline = time.monotonic() + 10
        data = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("upstream preflight timeout")
            chunk = response.read1(min(65536, _MAX_STATUS + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > _MAX_STATUS:
                raise ValueError("upstream preflight too large")
        if expected_length is not None and len(data) != expected_length:
            raise OSError("incomplete upstream preflight")
        if connection.sock is not original:
            raise OSError("upstream connection changed")
        return json.loads(data, object_pairs_hook=_no_duplicate_keys)
    version = get_json("/api/version")
    if not isinstance(version, dict) or version.get("version") != "0.34.0":
        raise ValueError("unsupported Ollama version")
    status = get_json("/api/ps")
    rows = status.get("models") if isinstance(status, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"] for row in rows):
        raise ValueError("invalid loaded-model inventory")
    if any(canonical_model(row["name"]) != canonical_model(model) for row in rows):
        raise ValueError("another model is resident")
    return original


class ProviderBridge(ThreadingHTTPServer):
    """Caller owns lifecycle and releases the session only after server shutdown."""
    daemon_threads = False
    block_on_close = True

    def __init__(self, scheduler: Any, model: str, *, token: str, upstream_port: int, port: int = 0, peer_verifier: Any = None) -> None:
        if (not isinstance(token, str) or not token.isascii() or not 32 <= len(token) <= 256
                or any(character.isspace() for character in token)):
            raise ValueError("provider token must be a nonempty ASCII secret")
        if type(upstream_port) is not int or not 1 <= upstream_port <= 65535 or type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("invalid loopback port")
        self.access_token = token
        self.upstream_port = upstream_port
        self.model = model
        self.peer_verifier = peer_verifier
        self._request_slots = threading.BoundedSemaphore(16)
        super().__init__(("127.0.0.1", port), _Handler)
        try:
            if self.server_port == upstream_port:
                raise ValueError("provider and upstream ports must differ")
            self.session = ExternalInferenceSession.open(scheduler, model)
        except BaseException:
            self.server_close()
            raise

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args: Any) -> None:
        pass

    def _error(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        # On Windows, closing a socket with unread request bytes can reset the
        # response. Drain only a small bounded body after sending the rejection.
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) == 1 and len(lengths[0]) <= 8 and lengths[0].isascii() and lengths[0].isdigit() and int(lengths[0]) <= 65536:
            self.connection.settimeout(0.1)
            remaining = int(lengths[0])
            try:
                while remaining:
                    chunk = self.rfile.read1(min(remaining, 65536))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except OSError:
                pass

    def do_POST(self) -> None:
        self.close_connection = True
        self.connection.settimeout(10)
        if self.path != "/v1/chat/completions":
            self._error(404)
            return
        auth = self.headers.get_all("Authorization", [])
        expected = f"Bearer {self.server.access_token}"
        if (len(auth) != 1 or not auth[0].isascii() or not secrets.compare_digest(auth[0], expected)
                or self.headers.get("Origin") is not None):
            self._error(401)
            return
        lengths = self.headers.get_all("Content-Length", [])
        if (len(lengths) != 1 or len(lengths[0]) > 8 or not lengths[0].isascii() or not lengths[0].isdigit()
                or self.headers.get("Transfer-Encoding") is not None
                or self.headers.get_content_type() != "application/json"):
            self._error(400)
            return
        length = int(lengths[0])
        if not 0 < length <= _MAX_BODY:
            self._error(413)
            return
        try:
            deadline = time.monotonic() + 15
            parts = []
            remaining = length
            while remaining:
                if time.monotonic() > deadline:
                    raise TimeoutError("request body timeout")
                chunk = self.rfile.read1(min(65536, remaining))
                if not chunk:
                    raise ValueError("incomplete request")
                parts.append(chunk)
                remaining -= len(chunk)
            body = b"".join(parts)
            def reject_constant(_value: str) -> None:
                raise ValueError("nonfinite JSON number")
            payload = json.loads(body.decode("utf-8"), object_pairs_hook=_no_duplicate_keys, parse_constant=reject_constant)
            if not isinstance(payload, dict) or payload.get("model") != self.server.model or payload.get("stream") is not True:
                raise ValueError("model or streaming request is invalid")
        except (ValueError, UnicodeError, OSError, TimeoutError):
            self._error(400)
            return

        try:
            payload["model"] = self.server.model + ":local"
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            if len(body) > _MAX_BODY:
                raise ValueError("upstream request exceeds limit")
        except (ValueError, UnicodeError):
            self._error(503)
            return

        headers_sent = False
        connection = http.client.HTTPConnection("127.0.0.1", self.server.upstream_port, timeout=10)
        checked_socket = None
        def preflight():
            nonlocal checked_socket
            checked_socket = _preflight_connection(connection, self.server.model, self.server.peer_verifier)
        def source():
            nonlocal headers_sent
            deadline = time.monotonic() + 900
            try:
                if checked_socket is None or connection.sock is not checked_socket:
                    raise OSError("upstream connection changed")
                checked_socket.settimeout(30)
                connection.request("POST", "/v1/chat/completions", body=body, headers={"Content-Type": "application/json", "Accept": "text/event-stream", "Connection": "close"})
                response = connection.getresponse()
                if (response.status != 200 or response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "text/event-stream"
                        or response.getheader("Content-Encoding", "identity").lower() != "identity"):
                    raise OSError("upstream response not accepted")
                expected_length = response.length
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                headers_sent = True
                count = 0
                while True:
                    if time.monotonic() > deadline:
                        raise TimeoutError("upstream timeout")
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > _MAX_RESPONSE:
                        raise OSError("upstream response exceeds limit")
                    yield chunk
                if expected_length is not None and count != expected_length:
                    raise OSError("incomplete upstream response")
            finally:
                connection.close()

        try:
            self.server.session.relay_stream(self.server.model, source, self.wfile.write, preflight=preflight)
        except (InferenceSessionError, OSError, TimeoutError, ValueError, http.client.HTTPException):
            if not headers_sent:
                try:
                    self._error(503)
                except OSError:
                    pass
        finally:
            connection.close()
