from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.llama_cpp import (
    _InterruptibleSocketReader,
    _http_proxy_for_url,
    _open_interruptible_response,
    _read_response_body,
    _resolve_interruptibly,
)


class LlamaCppInterruptibleTransportTests(unittest.TestCase):
    def test_interruptible_response_cancels_before_headers(self):
        request_seen = threading.Event()
        release_handler = threading.Event()

        class _DelayedHeadersHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                request_seen.set()
                release_handler.wait(timeout=3)
                try:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ok")
                except OSError:
                    pass

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), _DelayedHeadersHandler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        cancelled = threading.Event()
        result: list[str] = []
        request = Request(f"http://127.0.0.1:{server.server_port}/slow", data=b"{}")

        def call() -> None:
            try:
                with _open_interruptible_response(request, time.monotonic() + 5, cancelled.is_set):
                    result.append("response")
            except InterruptedError:
                result.append("cancelled")

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        try:
            self.assertTrue(request_seen.wait(1))
            cancelled.set()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result, ["cancelled"])
        finally:
            release_handler.set()
            server.shutdown()
            server.server_close()
            server_thread.join(1)
            worker.join(1)
    def test_interruptible_response_cancels_during_dns_resolution(self):
        resolver_started = threading.Event()
        release_resolver = threading.Event()
        cancelled = threading.Event()
        result: list[str] = []

        def blocked_resolver(*_args):
            resolver_started.set()
            release_resolver.wait(timeout=2)
            return []

        def call() -> None:
            try:
                with _open_interruptible_response(
                    Request("http://slow-resolver.invalid/"),
                    time.monotonic() + 5,
                    cancelled.is_set,
                ):
                    result.append("response")
            except InterruptedError:
                result.append("cancelled")

        worker = threading.Thread(target=call, daemon=True)
        with patch("local_ai_hub.llama_cpp.socket.getaddrinfo", side_effect=blocked_resolver):
            worker.start()
            try:
                self.assertTrue(resolver_started.wait(1))
                cancelled.set()
                worker.join(0.5)
                self.assertFalse(worker.is_alive(), "DNS resolution held the cancelled request")
                self.assertEqual(result, ["cancelled"])
            finally:
                cancelled.set()
                release_resolver.set()
                worker.join(1)
    def test_interruptible_response_cancels_during_socket_connect(self):
        connect_started = threading.Event()
        socket_closed = threading.Event()

        class _BlockingConnectSocket:
            def settimeout(self, _timeout):
                pass

            def connect(self, _address):
                connect_started.set()
                if not socket_closed.wait(timeout=2):
                    raise TimeoutError("connect test exceeded deadline")
                raise OSError("socket closed by cancellation")

            def shutdown(self, _how):
                socket_closed.set()

            def close(self):
                socket_closed.set()

        client_socket = _BlockingConnectSocket()
        cancelled = threading.Event()
        result: list[str] = []
        request = Request("http://127.0.0.1:12345/slow")

        def call() -> None:
            try:
                with _open_interruptible_response(request, time.monotonic() + 5, cancelled.is_set):
                    result.append("response")
            except InterruptedError:
                result.append("cancelled")

        worker = threading.Thread(target=call, daemon=True)
        with patch("local_ai_hub.llama_cpp.socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 12345))]), \
             patch("local_ai_hub.llama_cpp.socket.socket", return_value=client_socket):
            worker.start()
            try:
                self.assertTrue(connect_started.wait(1))
                cancelled.set()
                worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(result, ["cancelled"])
                self.assertTrue(socket_closed.is_set())
            finally:
                cancelled.set()
                worker.join(1)

    def test_interruptible_response_cancels_during_tls_handshake(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        accepted = threading.Event()
        release_server = threading.Event()
        stop = threading.Event()
        request_done = threading.Event()
        outcomes: list[str] = []

        def serve_without_tls_handshake():
            try:
                connection, _ = listener.accept()
                with connection:
                    accepted.set()
                    release_server.wait(2)
            except OSError:
                pass

        server_thread = threading.Thread(target=serve_without_tls_handshake, daemon=True)
        server_thread.start()

        def open_request():
            try:
                with _open_interruptible_response(
                    Request(f"https://127.0.0.1:{listener.getsockname()[1]}/"),
                    time.monotonic() + 2,
                    stop.is_set,
                ):
                    outcomes.append("opened")
            except Exception as exc:
                outcomes.append(type(exc).__name__)
            finally:
                request_done.set()

        caller = threading.Thread(target=open_request, daemon=True)
        with patch.dict(
            "os.environ",
            {
                "http_proxy": "", "HTTP_PROXY": "", "https_proxy": "", "HTTPS_PROXY": "",
                "no_proxy": "127.0.0.1", "NO_PROXY": "127.0.0.1",
            },
        ):
            caller.start()
            try:
                self.assertTrue(accepted.wait(1))
                time.sleep(0.05)
                stop.set()
                self.assertTrue(request_done.wait(0.5), "TLS handshake did not stop promptly")
                self.assertNotEqual(outcomes, ["opened"])
            finally:
                release_server.set()
                caller.join(1)
                listener.close()
                server_thread.join(1)

    def test_interruptible_response_enforces_absolute_header_deadline(self):
        request_seen = threading.Event()
        release_handler = threading.Event()

        class _DelayedHeadersHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                request_seen.set()
                release_handler.wait(timeout=2)
                try:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"late")
                except OSError:
                    pass

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), _DelayedHeadersHandler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        result: list[str] = []
        request = Request(f"http://127.0.0.1:{server.server_port}/slow")

        def call() -> None:
            try:
                with _open_interruptible_response(request, time.monotonic() + 0.15, None):
                    result.append("response")
            except TimeoutError:
                result.append("timeout")

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        try:
            self.assertTrue(request_seen.wait(1))
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result, ["timeout"])
        finally:
            release_handler.set()
            server.shutdown()
            server.server_close()
            server_thread.join(1)
            worker.join(1)
    def test_interruptible_response_follows_redirect_and_caps_error_body(self):
        class _RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/ok")
                    self.end_headers()
                    return
                if self.path == "/large-error":
                    body = b"x" * 100_000
                    self.send_response(500)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                body = b"ok"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with _open_interruptible_response(Request(f"{base}/redirect"), time.monotonic() + 2, None) as response:
                self.assertEqual(response.read(), b"ok")
            with self.assertRaises(HTTPError) as raised:
                with _open_interruptible_response(Request(f"{base}/large-error"), time.monotonic() + 2, None):
                    self.fail("HTTP error must preserve urllib behavior")
            self.assertEqual(len(raised.exception.read()), 65_536)
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(1)

    def test_interruptible_response_body_supports_http_response_read1(self):
        body = b"ollama metadata"

        class _BodyHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), _BodyHandler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        deadline = time.monotonic() + 2
        try:
            request = Request(f"http://127.0.0.1:{server.server_port}/metadata")
            with _open_interruptible_response(request, deadline, None) as response:
                self.assertEqual(_read_response_body(response, deadline), body)
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(1)

    def test_interruptible_response_peek_is_non_consuming(self):
        body = b"ollama metadata"

        class _BodyHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), _BodyHandler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        deadline = time.monotonic() + 2
        try:
            request = Request(f"http://127.0.0.1:{server.server_port}/metadata")
            with _open_interruptible_response(request, deadline, None) as response:
                self.assertEqual(response.peek(6)[:6], body[:6])
                self.assertEqual(_read_response_body(response, deadline), body)
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(1)

    def test_interruptible_response_honors_configured_http_proxy(self):
        observed_targets: list[str] = []

        class _ProxyHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                observed_targets.append(self.path)
                body = b"proxied"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), _ProxyHandler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        proxy = f"http://127.0.0.1:{server.server_port}"
        request = Request("http://target.invalid/path?q=1")
        fake_addresses = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", server.server_port))
        ]
        try:
            with patch.dict(
                "os.environ",
                {"http_proxy": proxy, "HTTP_PROXY": proxy, "no_proxy": "", "NO_PROXY": ""},
            ), patch("local_ai_hub.llama_cpp.socket.getaddrinfo", return_value=fake_addresses):
                with _open_interruptible_response(request, time.monotonic() + 2, None) as response:
                    self.assertEqual(response.read(), b"proxied")
            self.assertEqual(observed_targets, ["http://target.invalid/path?q=1"])
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(1)

    def test_proxy_bypass_matches_host_and_explicit_port(self):
        target = urlsplit("http://127.0.0.1:12438/api/chat")
        with patch.dict(
            "os.environ",
            {
                "http_proxy": "http://127.0.0.1:3128",
                "HTTP_PROXY": "http://127.0.0.1:3128",
                "no_proxy": "127.0.0.1:12438",
                "NO_PROXY": "127.0.0.1:12438",
            },
        ):
            self.assertIsNone(_http_proxy_for_url(target))

    def test_interruptible_reader_drains_buffered_tls_plaintext(self):
        class _BufferedTLSLikeSocket:
            def __init__(self):
                self.buffer = bytearray(b"ready\n")

            def pending(self):
                return len(self.buffer)

            def recv(self, size):
                chunk = bytes(self.buffer[:size])
                del self.buffer[:size]
                return chunk

            def settimeout(self, _timeout):
                pass

        sock = _BufferedTLSLikeSocket()
        reader = _InterruptibleSocketReader(sock, time.monotonic() + 0.2, None)
        with patch("local_ai_hub.llama_cpp.select.select", return_value=([], [], [])):
            self.assertEqual(reader.read(6), b"ready\n")

    def test_numeric_host_resolves_without_waiting_for_dns_slot(self):
        slots = threading.BoundedSemaphore(1)
        self.assertTrue(slots.acquire(blocking=False))
        deadline = time.monotonic() + 0.2

        def remaining() -> float:
            value = deadline - time.monotonic()
            if value <= 0:
                raise TimeoutError("test deadline expired")
            return value

        with patch("local_ai_hub.llama_cpp._DNS_RESOLUTION_SLOTS", slots):
            addresses = _resolve_interruptibly(
                "127.0.0.1", 12438, remaining,
            )
        self.assertTrue(addresses)
        self.assertEqual(addresses[0][0], socket.AF_INET)
        self.assertEqual(addresses[0][4], ("127.0.0.1", 12438))
