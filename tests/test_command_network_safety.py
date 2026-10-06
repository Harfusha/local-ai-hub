from __future__ import annotations

import ctypes
import hashlib
import hmac
import http.server
import json
import os
import socket
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from local_ai_hub import commands as commands_module
from local_ai_hub.commands import CommandBroker


def _broker(tmp_path, **network):
    return CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True},
            "network": network,
        }
    )


def _serve(handler):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/hook",
        "http://user:password@example.com/hook",
    ],
)
def test_webhook_replay_rejects_unsupported_schemes_and_url_credentials(
    tmp_path, monkeypatch, url
):
    broker = _broker(tmp_path)
    dns_calls = []

    def record_dns(host, port, *args, **kwargs):
        dns_calls.append((host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", record_dns)
    result = broker.webhook_replay(url, {"event": "ping"})

    assert result["success"] is False
    assert result["error_code"] == "invalid_network_url"
    assert dns_calls == []


def test_http_probe_rejects_private_targets_without_explicit_scope(tmp_path, monkeypatch):
    broker = _broker(tmp_path)

    def forbidden_connect(*_args, **_kwargs):
        raise AssertionError("unscoped private target must be blocked before connect")

    monkeypatch.setattr(socket, "create_connection", forbidden_connect)
    result = broker.http_probe("http://127.0.0.1:11435/api/health")

    assert result["success"] is False
    assert result["error_code"] == "network_scope_denied"


def test_http_probe_rejects_dns_answers_outside_scope(tmp_path, monkeypatch):
    broker = _broker(tmp_path)
    original_getaddrinfo = socket.getaddrinfo
    seen = []

    def private_answer(host, port, *args, **kwargs):
        if host == "public.example":
            seen.append((host, port))
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", private_answer)

    def forbidden_connect(*_args, **_kwargs):
        raise AssertionError("private DNS answer must be blocked before connect")

    monkeypatch.setattr(socket, "create_connection", forbidden_connect)
    result = broker.http_probe("http://public.example:11435/health")

    assert result["success"] is False
    assert result["error_code"] == "network_scope_denied"
    assert seen == [("public.example", 11435)]


def test_dns_resolution_has_a_bounded_wait(tmp_path, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocked_resolver(*_args, **_kwargs):
        started.set()
        release.wait(1)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", blocked_resolver)

    def forbidden_connect(*_args, **_kwargs):
        raise AssertionError("DNS timeout must stop before connect")

    monkeypatch.setattr(socket, "create_connection", forbidden_connect)
    broker = _broker(tmp_path, timeout_seconds=0.05)
    before = time.monotonic()
    try:
        result = broker.http_probe("http://slow-resolver.test/", timeout=0.05)
        elapsed = time.monotonic() - before
    finally:
        release.set()

    assert started.is_set()
    assert elapsed < 0.5
    assert result["success"] is False
    assert result["error_code"] == "network_timeout"


def test_http_probe_allows_explicit_loopback_scope_and_redacts_secrets(tmp_path):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"access_token":"secret-value","ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", "session=secret-cookie")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server, thread = _serve(Handler)
    try:
        broker = _broker(tmp_path, allow_private_hosts=["127.0.0.1/32"])
        result = broker.http_probe(f"http://127.0.0.1:{server.server_port}/health")
    finally:
        _stop(server, thread)

    assert result["success"] is True
    assert "set-cookie" not in result["headers"]
    assert "secret-value" not in repr(result)
    assert "secret-cookie" not in repr(result)


def test_http_probe_rejects_redirect_to_unscoped_private_host(tmp_path, monkeypatch):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://192.0.2.1:11435/internal")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server, thread = _serve(Handler)
    original_connect = socket.create_connection

    def scoped_connect(address, *args, **kwargs):
        if address[0] != "127.0.0.1":
            raise AssertionError("redirect target escaped explicit private scope")
        return original_connect(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", scoped_connect)
    try:
        broker = _broker(tmp_path, allow_private_hosts=["127.0.0.1/32"])
        result = broker.http_probe(f"http://127.0.0.1:{server.server_port}/redirect")
    finally:
        _stop(server, thread)

    assert result["success"] is False
    assert result["error_code"] == "network_scope_denied"


def test_http_probe_strips_caller_headers_on_cross_origin_redirect(tmp_path):
    received_headers = {}

    class DestinationHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            received_headers.update({key.lower(): value for key, value in self.headers.items()})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            pass

    destination, destination_thread = _serve(DestinationHandler)

    class RedirectHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{destination.server_port}/sink")
            self.end_headers()

        def log_message(self, *_args):
            pass

    source, source_thread = _serve(RedirectHandler)
    try:
        broker = _broker(tmp_path, allow_private_hosts=["127.0.0.1/32"])
        result = broker.http_probe(
            f"http://127.0.0.1:{source.server_port}/redirect",
            headers={"X-API-Key": "secret", "X-Tenant": "private-tenant"},
        )
    finally:
        _stop(source, source_thread)
        _stop(destination, destination_thread)

    assert result["success"] is True
    assert "x-api-key" not in received_headers
    assert "x-tenant" not in received_headers


def test_http_probe_preserves_caller_headers_on_same_origin_redirect(tmp_path):
    received_headers = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/health")
                self.end_headers()
                return
            received_headers.append(self.headers.get("X-Tenant"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            pass

    server, thread = _serve(Handler)
    try:
        broker = _broker(tmp_path, allow_private_hosts=["127.0.0.1/32"])
        result = broker.http_probe(
            f"http://127.0.0.1:{server.server_port}/redirect",
            headers={"X-Tenant": "private-tenant"},
        )
    finally:
        _stop(server, thread)

    assert result["success"] is True
    assert received_headers == ["private-tenant"]


def test_http_probe_bounds_response_and_redacts_sensitive_headers(tmp_path):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"x" * 8192
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Set-Cookie", "session=private")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server, thread = _serve(Handler)
    try:
        broker = _broker(
            tmp_path,
            allow_private_hosts=["127.0.0.1/32"],
            max_response_bytes=1024,
        )
        result = broker.http_probe(f"http://127.0.0.1:{server.server_port}/large")
    finally:
        _stop(server, thread)

    assert result["success"] is False
    assert result["error_code"] == "response_too_large"
    assert result["body_length"] <= 1025
    assert "set-cookie" not in result["headers"]
    assert "private" not in repr(result)


def test_http_probe_enforces_total_deadline_for_slow_response(tmp_path):
    class SlowHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "6")
            self.end_headers()
            try:
                for _ in range(6):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.04)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_args):
            pass

    server, thread = _serve(SlowHandler)
    broker = _broker(
        tmp_path,
        allow_private_hosts=["127.0.0.1/32"],
        timeout_seconds=0.1,
    )
    before = time.monotonic()
    try:
        result = broker.http_probe(f"http://127.0.0.1:{server.server_port}/", timeout=0.1)
        elapsed = time.monotonic() - before
    finally:
        _stop(server, thread)

    assert elapsed < 0.6
    assert result["success"] is False
    assert result["error_code"] == "network_timeout"


def test_record_mock_rejects_cassette_path_traversal_before_network(tmp_path, monkeypatch):
    broker = _broker(tmp_path)
    monkeypatch.setattr(
        broker,
        "http_probe",
        lambda *_args, **_kwargs: pytest.fail("invalid cassette name must be rejected first"),
    )

    result = broker.record_mock("https://example.com/api", "../escape")

    assert result["success"] is False
    assert result["error_code"] == "invalid_cassette_name"
    assert not (tmp_path / "state" / "escape.json").exists()


def test_replay_mock_rejects_cassette_path_traversal(tmp_path):
    broker = _broker(tmp_path)
    outside = tmp_path / "state" / "secret.json"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text('{"token":"secret"}', encoding="utf-8")

    result = broker.replay_mock("../secret")

    assert result["success"] is False
    assert result["error_code"] == "invalid_cassette_name"
    assert "secret" not in repr(result)


def test_replay_mock_rejects_oversized_cassette(tmp_path):
    broker = _broker(tmp_path)
    paths = broker._cassette_paths("oversized", None, create=True)
    assert isinstance(paths, tuple)
    _cassette_dir, cassette_file = paths
    cassette_file.write_bytes(b"{" + b" " * (1024 * 1024))

    result = broker.replay_mock("oversized")

    assert result["success"] is False
    assert result["error_code"] == "cassette_too_large"


def test_replay_mock_rejects_symlink_cassette(tmp_path):
    broker = _broker(tmp_path)
    paths = broker._cassette_paths("linked", None, create=True)
    assert isinstance(paths, tuple)
    _cassette_dir, cassette_file = paths
    outside = tmp_path / "outside.json"
    outside.write_text('{"body":"private"}', encoding="utf-8")
    try:
        cassette_file.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    result = broker.replay_mock("linked")

    assert result["success"] is False
    assert result["error_code"] == "invalid_cassette_path"
    assert "private" not in repr(result)


def test_webhook_replay_rejects_oversized_payload_before_connect(tmp_path, monkeypatch):
    broker = _broker(tmp_path, max_payload_bytes=64)

    def forbidden_connect(*_args, **_kwargs):
        raise AssertionError("oversized payload must be rejected before connect")

    monkeypatch.setattr(socket, "create_connection", forbidden_connect)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )
    result = broker.webhook_replay("https://example.com/hook", {"data": "x" * 128})

    assert result["success"] is False
    assert result["error_code"] == "payload_too_large"


def test_webhook_replay_preflights_oversized_json_before_serializing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        commands_module,
        "json_dumps",
        lambda *_args, **_kwargs: pytest.fail("oversized JSON must be rejected before serialization"),
    )
    broker = _broker(tmp_path, max_payload_bytes=64)

    result = broker.webhook_replay(
        "https://example.com/hook",
        {"data": "x" * 128},
    )

    assert result["success"] is False
    assert result["error_code"] == "payload_too_large"


def test_webhook_replay_preflights_oversized_text_before_conversion(tmp_path):
    conversions: list[bool] = []

    class OversizedText(str):
        def __str__(self):
            conversions.append(True)
            return super().__str__()

    broker = _broker(tmp_path, max_payload_bytes=64)
    result = broker.webhook_replay(
        "https://example.com/hook",
        OversizedText("x" * 128),
    )

    assert result["success"] is False
    assert result["error_code"] == "payload_too_large"
    assert conversions == []


@pytest.mark.parametrize(
    "value",
    ["\x00" * 10, "😀" * 14],
    ids=["escaped-control", "multibyte-utf8"],
)
def test_webhook_replay_preflights_encoded_json_size_before_serializing(
    tmp_path, monkeypatch, value
):
    monkeypatch.setattr(
        commands_module,
        "json_dumps",
        lambda *_args, **_kwargs: pytest.fail(
            "oversized encoded JSON must be rejected before serialization"
        ),
    )
    broker = _broker(tmp_path, max_payload_bytes=64)

    result = broker.webhook_replay(
        "https://example.com/hook",
        {"data": value},
    )

    assert result["success"] is False
    assert result["error_code"] == "payload_too_large"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_webhook_preflight_matches_nonfinite_json_backend_size(tmp_path, value):
    payload = {"x": value}
    encoded_size = len(commands_module.json_dumps(payload).encode("utf-8"))
    broker = _broker(tmp_path, max_payload_bytes=encoded_size)

    assert broker._webhook_payload_preflight(payload, encoded_size) is None


def test_webhook_replay_rejects_non_string_object_keys_before_serializing(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        commands_module,
        "json_dumps",
        lambda *_args, **_kwargs: pytest.fail(
            "non-string JSON object keys must be rejected before serialization"
        ),
    )
    broker = _broker(tmp_path, max_payload_bytes=64)

    result = broker.webhook_replay(
        "https://example.com/hook",
        {"data": {1: "x"}},
    )

    assert result["success"] is False
    assert result["error_code"] == "invalid_webhook_payload"


def test_webhook_replay_rejects_overriding_string_subclass_before_serializing(
    tmp_path, monkeypatch
):
    class LyingText(str):
        def __iter__(self):
            return iter("")

    monkeypatch.setattr(
        commands_module,
        "json_dumps",
        lambda *_args, **_kwargs: pytest.fail(
            "custom string iteration must not control payload preflight"
        ),
    )
    broker = _broker(tmp_path, max_payload_bytes=64)

    result = broker.webhook_replay(
        "https://example.com/hook",
        {"data": LyingText("x" * 128)},
    )

    assert result["success"] is False
    assert result["error_code"] == "invalid_webhook_payload"


def test_webhook_replay_rejects_overriding_integer_subclass_before_serializing(
    tmp_path, monkeypatch
):
    class LyingInteger(int):
        def __abs__(self):
            return 0

        def __str__(self):
            return "0"

    monkeypatch.setattr(
        commands_module,
        "json_dumps",
        lambda *_args, **_kwargs: pytest.fail(
            "custom integer conversion must not control payload preflight"
        ),
    )
    broker = _broker(tmp_path, max_payload_bytes=64)

    result = broker.webhook_replay(
        "https://example.com/hook",
        {"data": LyingInteger(int("9" * 80))},
    )

    assert result["success"] is False
    assert result["error_code"] == "invalid_webhook_payload"


def test_webhook_preflight_bounds_large_escaped_payload_before_serializing(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        commands_module,
        "json_dumps",
        lambda *_args, **_kwargs: pytest.fail(
            "large escaped payload must be rejected before serialization"
        ),
    )
    broker = _broker(tmp_path, max_payload_bytes=64)

    result = broker.webhook_replay(
        "https://example.com/hook",
        {"data": "\x00" * 8_000_000},
    )

    assert result["success"] is False
    assert result["error_code"] == "payload_too_large"


def test_webhook_replay_posts_bounded_json_with_hmac(tmp_path):
    received: dict[str, object] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            received["body"] = self.rfile.read(length)
            received["signature"] = self.headers.get("X-Hub-Signature-256")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            pass

    server, thread = _serve(Handler)
    secret = "webhook-secret"
    try:
        broker = _broker(
            tmp_path,
            allow_private_hosts=["127.0.0.1/32"],
            max_payload_bytes=64,
        )
        result = broker.webhook_replay(
            f"http://127.0.0.1:{server.server_port}/hook",
            {"event": "ping"},
            secret=secret,
        )
    finally:
        _stop(server, thread)

    body = received["body"]
    assert isinstance(body, bytes)
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert received["signature"] == f"sha256={expected}"
    assert json.loads(body.decode("utf-8")) == {"event": "ping"}
    assert result["success"] is True


def test_webhook_replay_bounds_oversized_response(tmp_path):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"x" * 128)

        def log_message(self, *_args):
            pass

    server, thread = _serve(Handler)
    try:
        broker = _broker(
            tmp_path,
            allow_private_hosts=["127.0.0.1/32"],
            max_response_bytes=16,
        )
        result = broker.webhook_replay(
            f"http://127.0.0.1:{server.server_port}/hook",
            {"event": "ping"},
        )
    finally:
        _stop(server, thread)

    assert result["success"] is False
    assert result["error_code"] == "response_too_large"
    assert result["body_length"] == 17
    assert result["body_truncated"] is True
    assert "body_preview" not in result


def test_webhook_replay_blocks_redirect_without_contacting_destination(tmp_path):
    destination_hits: list[str] = []

    class DestinationHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            destination_hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    destination, destination_thread = _serve(DestinationHandler)

    class RedirectHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(307)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{destination.server_port}/sink",
            )
            self.end_headers()

        def log_message(self, *_args):
            pass

    source, source_thread = _serve(RedirectHandler)
    try:
        broker = _broker(tmp_path, allow_private_hosts=["127.0.0.1/32"])
        result = broker.webhook_replay(
            f"http://127.0.0.1:{source.server_port}/redirect",
            {"event": "ping"},
        )
    finally:
        _stop(source, source_thread)
        _stop(destination, destination_thread)

    assert result["success"] is False
    assert result["error_code"] == "network_redirect_blocked"
    assert destination_hits == []


def test_webhook_replay_enforces_total_request_deadline(tmp_path):
    headers_sent = threading.Event()

    class SlowHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.end_headers()
            headers_sent.set()
            time.sleep(0.3)
            try:
                self.wfile.write(b"late")
            except OSError:
                pass

        def log_message(self, *_args):
            pass

    server, thread = _serve(SlowHandler)
    try:
        broker = _broker(tmp_path, allow_private_hosts=["127.0.0.1/32"])
        started = time.monotonic()
        result = broker.webhook_replay(
            f"http://127.0.0.1:{server.server_port}/slow",
            {"event": "ping"},
            timeout=0.15,
        )
        elapsed = time.monotonic() - started
    finally:
        _stop(server, thread)

    assert headers_sent.is_set()
    assert result["success"] is False
    assert result["error_code"] == "network_timeout"
    assert elapsed < 0.5


def test_replay_mock_rejects_symlink_swap_without_nofollow(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("Windows reparse handles are covered by the native-handle test")

    broker = _broker(tmp_path)
    paths = broker._cassette_paths("race", None, create=True)
    assert isinstance(paths, tuple)
    _cassette_dir, cassette_file = paths
    cassette_file.write_text('{"body":"local"}', encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text('{"body":"outside-secret"}', encoding="utf-8")
    real_open = os.open

    def swap_target_during_open(path, flags, *args, **kwargs):
        if os.path.basename(os.fsdecode(path)) == cassette_file.name:
            return real_open(outside, flags, *args, **kwargs)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(commands_module.os, "O_NOFOLLOW", 0, raising=False)
    monkeypatch.setattr(commands_module.os, "open", swap_target_during_open)

    result = broker.replay_mock("race")

    assert result["success"] is False
    assert "outside-secret" not in repr(result)


def test_replay_mock_rejects_windows_reparse_handle_without_symlink_privilege(
    tmp_path, monkeypatch
):
    if os.name != "nt":
        pytest.skip("Windows handle validation is platform-specific")

    broker = _broker(tmp_path)
    paths = broker._cassette_paths("windows-race", None, create=True)
    assert isinstance(paths, tuple)
    cassette_dir, cassette_file = paths
    cassette_file.write_text('{"body":"local"}', encoding="utf-8")

    class FakeFunction:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    class FakeKernel32:
        pass

    kernel32 = FakeKernel32()
    kernel32.CreateFileW = FakeFunction(
        lambda path, *_args: 101 if str(path) == str(cassette_dir) else 102
    )

    def file_info(handle, info_pointer):
        info_pointer._obj.attributes = 0x10 if handle == 101 else 0x400
        return True

    kernel32.GetFileInformationByHandle = FakeFunction(file_info)
    kernel32.GetFileType = FakeFunction(lambda _handle: 1)
    kernel32.CloseHandle = FakeFunction(lambda _handle: True)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32)

    result = broker.replay_mock("windows-race")

    assert result["success"] is False
    assert result["error_code"] == "invalid_cassette_path"


def test_mock_server_cors_uses_configured_origin_allowlist(tmp_path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    broker = _broker(tmp_path, mock_server_cors_origins=["http://localhost:3000"])
    started = broker.mock_server_start(str(tmp_path), port=port)
    assert started["success"] is True
    try:
        allowed = Request(
            f"http://127.0.0.1:{port}/api/health",
            headers={"Origin": "http://localhost:3000"},
        )
        denied = Request(
            f"http://127.0.0.1:{port}/api/health",
            headers={"Origin": "https://attacker.example"},
        )
        with urlopen(allowed, timeout=2) as response:
            allowed_origin = response.headers.get("Access-Control-Allow-Origin")
        with urlopen(denied, timeout=2) as response:
            denied_origin = response.headers.get("Access-Control-Allow-Origin")
    finally:
        broker.mock_server_stop(port)

    assert allowed_origin == "http://localhost:3000"
    assert denied_origin is None


def test_http_probe_rejects_unscoped_ipv6_loopback_before_connect(tmp_path, monkeypatch):
    broker = _broker(tmp_path)

    def forbidden_connect(*_args, **_kwargs):
        raise AssertionError("unscoped IPv6 loopback must be blocked before connect")

    monkeypatch.setattr(socket, "create_connection", forbidden_connect)
    result = broker.http_probe("http://[::1]:11435/health")

    assert result["success"] is False
    assert result["error_code"] == "network_scope_denied"


def test_http_probe_blocks_https_to_http_redirect_downgrade(tmp_path, monkeypatch):
    class RedirectResponse:
        status = 302

        def getheaders(self):
            return [("Location", "http://public.example/downgrade")]

        def read(self, _limit):
            return b""

    class FakeConnection:
        def __init__(self, *_args, **_kwargs):
            self.sock = None

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return RedirectResponse()

        def close(self):
            pass

    resolved_urls: list[str] = []

    def resolve(_config, url: str, _timeout: float):
        resolved_urls.append(url)
        if url.startswith("https://"):
            return ("https", "public.example", 443, "93.184.216.34", "/start", None)
        return ("http", "public.example", 80, "93.184.216.34", "/downgrade", None)

    monkeypatch.setattr(commands_module, "_resolve_network_target", resolve)
    monkeypatch.setattr(commands_module, "_PinnedHTTPSConnection", FakeConnection)
    monkeypatch.setattr(commands_module, "_PinnedHTTPConnection", FakeConnection)
    result = _broker(tmp_path).http_probe("https://public.example/start")

    assert result["success"] is False
    assert result["error_code"] == "network_redirect_downgrade"
    assert len(resolved_urls) == 2


def test_http_probe_stops_at_configured_redirect_limit(tmp_path):
    hits: list[str] = []

    class RedirectHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(302)
            self.send_header("Location", f"/redirect-{len(hits)}")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server, thread = _serve(RedirectHandler)
    try:
        broker = _broker(
            tmp_path,
            allow_private_hosts=["127.0.0.1/32"],
            max_redirects=1,
        )
        result = broker.http_probe(f"http://127.0.0.1:{server.server_port}/start")
    finally:
        _stop(server, thread)

    assert result["success"] is False
    assert result["error_code"] == "network_redirect_limit"
    assert len(hits) == 2


def test_pinned_http_connection_connects_to_resolved_address(monkeypatch):
    calls = []

    class FakeSocket:
        def close(self):
            pass

    def connect(address, timeout, source_address):
        calls.append((address, timeout, source_address))
        return FakeSocket()

    monkeypatch.setattr(socket, "create_connection", connect)
    connection = commands_module._PinnedHTTPConnection(
        "public.example", 8080, "93.184.216.34", timeout=1.25
    )
    try:
        connection.connect()
        assert calls == [(('93.184.216.34', 8080), 1.25, None)]
    finally:
        connection.close()


def test_mock_server_cors_defaults_to_deny(tmp_path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    broker = _broker(tmp_path)
    started = broker.mock_server_start(str(tmp_path), port=port)
    assert started["success"] is True
    try:
        request = Request(
            f"http://127.0.0.1:{port}/api/health",
            headers={"Origin": "http://localhost:3000"},
        )
        with urlopen(request, timeout=2) as response:
            allow_origin = response.headers.get("Access-Control-Allow-Origin")
            vary = response.headers.get("Vary")
        plain_request = Request(f"http://127.0.0.1:{port}/api/health")
        with urlopen(plain_request, timeout=2) as response:
            no_origin_vary = response.headers.get("Vary")
    finally:
        broker.mock_server_stop(port)

    assert allow_origin is None
    assert vary == "Origin"
    assert no_origin_vary == "Origin"


def test_mock_server_cors_ignores_wildcard_origin(tmp_path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    broker = _broker(tmp_path, mock_server_cors_origins=["*"])
    started = broker.mock_server_start(str(tmp_path), port=port)
    assert started["success"] is True
    try:
        request = Request(
            f"http://127.0.0.1:{port}/api/health",
            headers={"Origin": "https://attacker.example"},
        )
        with urlopen(request, timeout=2) as response:
            allow_origin = response.headers.get("Access-Control-Allow-Origin")
            vary = response.headers.get("Vary")
    finally:
        broker.mock_server_stop(port)

    assert allow_origin is None
    assert vary == "Origin"


def test_mock_server_cors_preflight_uses_configured_origin_allowlist(tmp_path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    allowed_origin = "http://localhost:3000"
    broker = _broker(tmp_path, mock_server_cors_origins=[allowed_origin])
    started = broker.mock_server_start(str(tmp_path), port=port)
    assert started["success"] is True
    try:
        allowed = Request(
            f"http://127.0.0.1:{port}/api/health",
            headers={
                "Origin": allowed_origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
            method="OPTIONS",
        )
        denied = Request(
            f"http://127.0.0.1:{port}/api/health",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
            method="OPTIONS",
        )
        with urlopen(allowed, timeout=2) as response:
            allowed_status = response.status
            allowed_headers = response.headers
        with urlopen(denied, timeout=2) as response:
            denied_status = response.status
            denied_headers = response.headers
    finally:
        broker.mock_server_stop(port)

    assert allowed_status == 204
    assert allowed_headers.get("Access-Control-Allow-Origin") == allowed_origin
    assert allowed_headers.get("Access-Control-Allow-Methods") == "GET, POST, PUT, DELETE, OPTIONS"
    assert allowed_headers.get("Access-Control-Allow-Headers") == "Content-Type"
    assert allowed_headers.get("Vary") == "Origin"

    assert denied_status == 204
    assert denied_headers.get("Access-Control-Allow-Origin") is None
    assert denied_headers.get("Access-Control-Allow-Methods") is None
    assert denied_headers.get("Access-Control-Allow-Headers") is None
    assert denied_headers.get("Vary") == "Origin"


def test_record_mock_rejects_cassettes_directory_symlink_swap_before_write(
    tmp_path, monkeypatch
):
    broker = _broker(tmp_path)
    paths = broker._cassette_paths("swap", None, create=True)
    assert isinstance(paths, tuple)
    cassette_dir, _cassette_file = paths

    held_dir = cassette_dir.with_name(f"{cassette_dir.name}-held")
    outside_dir = cassette_dir.parent.parent / "outside-cassettes"
    outside_dir.mkdir()
    outside_file = outside_dir / "swap.json"
    outside_file.write_text("outside-sentinel", encoding="utf-8")

    def swap_directory_during_probe(*_args, **_kwargs):
        cassette_dir.rename(held_dir)
        try:
            cassette_dir.symlink_to(outside_dir, target_is_directory=True)
        except OSError as exc:
            held_dir.rename(cassette_dir)
            pytest.skip(f"directory symlink creation unavailable: {exc}")
        return {
            "success": True,
            "status_code": 200,
            "headers": {},
            "body_preview": "recorded",
            "body_length": 8,
        }

    monkeypatch.setattr(broker, "http_probe", swap_directory_during_probe)
    result = broker.record_mock("https://example.com/api", "swap")

    assert result["success"] is False
    assert outside_file.read_text(encoding="utf-8") == "outside-sentinel"
    assert list(outside_dir.glob(".swap.*.tmp")) == []
    assert not (held_dir / "swap.json").exists()
