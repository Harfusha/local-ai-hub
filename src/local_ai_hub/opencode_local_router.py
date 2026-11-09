"""Fixed-target loopback router for a future isolated OpenCode process.

The router itself is not a sandbox and must not be presented as one. It never
accepts proxy-form requests or selects a destination from client input.
"""
from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .opencode_boundary import path_allowed

_MAX_BODY = 4 * 1024 * 1024
_MAX_RESPONSE = 64 * 1024 * 1024
_REQUEST_HEADERS = ("Authorization", "X-LocalAI-Agent", "X-LocalAI-Request-ID", "Content-Type", "Accept")
_RESPONSE_HEADERS = ("Content-Type", "Cache-Control", "Content-Length")


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("invalid JSON constant")


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, hub_port: int, provider_port: int):
        self.hub_port = hub_port
        self.provider_port = provider_port
        self.slots = threading.BoundedSemaphore(16)
        self.client_port = None
        self.client_port_lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), _Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *_args):
        pass

    def _reject(self, status: int):
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_CONNECT(self):
        self._reject(403)

    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route()

    def _route(self):
        self.close_connection = True
        self.connection.settimeout(10)
        hosts = self.headers.get_all("Host", [])
        allowed_hosts = {f"127.0.0.1:{self.server.server_port}"}
        if self.server.client_port is not None:
            allowed_hosts.add(f"127.0.0.1:{self.server.client_port}")
        if (len(hosts) != 1 or hosts[0] not in allowed_hosts or self.headers.get("Origin") is not None
                or self.headers.get("Transfer-Encoding") is not None or self.headers.get("Expect") is not None):
            self._reject(400)
            return
        if self.command == "POST" and self.path == "/v1/chat/completions":
            port = self.server.provider_port
        elif (not self.path.startswith("/api/opencode/provider/")
              and path_allowed("opencode-local", self.command, self.path)):
            port = self.server.hub_port
        else:
            self._reject(403)
            return
        lengths = self.headers.get_all("Content-Length", [])
        if (len(lengths) > 1 or (self.command == "POST" and len(lengths) != 1)
                or (lengths and (not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 8))):
            self._reject(400)
            return
        length = int(lengths[0]) if lengths else 0
        if length > _MAX_BODY or (self.command == "GET" and length):
            self._reject(413)
            return
        headers = {}
        for name in _REQUEST_HEADERS:
            values = self.headers.get_all(name, [])
            if len(values) > 1:
                self._reject(400)
                return
            if values and not (port == self.server.hub_port and name == "Authorization"):
                headers[name] = values[0]
        try:
            body = self.rfile.read(length) if length else b""
            if len(body) != length:
                self._reject(400)
                return
            if self.path == "/api/agent-state/verification":
                try:
                    payload = json.loads(body.decode("utf-8"), object_pairs_hook=_strict_object, parse_constant=_reject_constant)
                except (UnicodeError, ValueError, RecursionError):
                    self._reject(400)
                    return
                # Project commands run in the host broker. Until an isolated
                # receipt producer exists, they would escape the sandbox.
                if not isinstance(payload, dict) or payload.get("action") != "completion":
                    self._reject(403)
                    return
            headers["Connection"] = "close"
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
            try:
                conn.request(self.command, self.path, body=body if self.command == "POST" else None, headers=headers)
                response = conn.getresponse()
                self.send_response(response.status)
                for name in _RESPONSE_HEADERS:
                    value = response.getheader(name)
                    if value is not None:
                        self.send_header(name, value)
                self.send_header("Connection", "close")
                self.end_headers()
                total = 0
                while True:
                    chunk = response.read1(min(65536, _MAX_RESPONSE + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_RESPONSE:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            finally:
                conn.close()
        except (OSError, http.client.HTTPException):
            self.close_connection = True


class LocalRouter:
    """Own a short-lived router. All target hosts are fixed to 127.0.0.1."""

    def __init__(self, hub_port: int, provider_port: int):
        if any(type(port) is not int or not 1 <= port <= 65535 for port in (hub_port, provider_port)):
            raise ValueError("valid loopback service ports are required")
        self._server = _Server(hub_port, provider_port)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self.port = self._server.server_port
        self._started = False

    def register_client_port(self, port: int):
        """Register the isolated bridge port once, from the trusted launcher."""
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("a valid loopback client port is required")
        with self._server.client_port_lock:
            if self._server.client_port is not None:
                raise RuntimeError("client port already registered")
            self._server.client_port = port

    def __enter__(self):
        self._thread.start()
        self._started = True
        return self

    def __exit__(self, *_args):
        if self._started:
            self._server.shutdown()
            self._thread.join(timeout=5)
        self._server.server_close()
