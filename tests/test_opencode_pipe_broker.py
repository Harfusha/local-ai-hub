import importlib.util
import json
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import local_ai_hub.opencode_pipe_broker as pipe_broker

from local_ai_hub.opencode_pipe_broker import (
    MAX_PIPE_FRAME_BYTES,
    build_pipe_sddl,
    encode_response_frame,
    parse_hub_chat_request,
    verify_client_identity,
    verify_session_secret,
)


def test_pipe_acl_preserves_owner_and_grants_only_minimum_package_rights():
    sid = "S-1-15-2-123-456"
    owner = "S-1-5-21-123-456-789-1001"

    assert build_pipe_sddl(sid, owner) == (
        f"D:P(A;;GA;;;SY)(A;;GA;;;{owner})(A;;0x12019B;;;{sid})"
    )
    with pytest.raises(ValueError, match="AppContainer SID"):
        build_pipe_sddl("S-1-5-21-123", owner)
    with pytest.raises(ValueError, match="owner SID"):
        build_pipe_sddl(sid, "Everyone")


def test_pipe_acl_sddl_is_accepted_by_windows_security_api():
    if importlib.util.find_spec("win32security") is None:
        pytest.skip("pywin32 is unavailable")
    import win32security

    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        build_pipe_sddl("S-1-15-2-123-456", "S-1-5-21-123-456-789-1001"), 1
    )

    assert descriptor is not None


def test_pipe_identity_requires_exact_appcontainer_and_session():
    sid = "S-1-15-2-123-456"

    logon = "S-1-5-5-0-12345"
    assert verify_client_identity(sid, sid, 7, 7, logon, logon)
    assert not verify_client_identity(sid, sid, 7, 8, logon, logon)
    assert not verify_client_identity("S-1-15-2-123-999", sid, 7, 7, logon, logon)
    assert not verify_client_identity(None, sid, 7, 7, logon, logon)
    assert not verify_client_identity(sid, sid, 7, 7, "S-1-5-5-0-9", logon)


def test_pipe_name_uses_unqualified_cross_trust_path():
    session_id = "0123456789abcdef0123456789abcdef"

    builder = getattr(pipe_broker, "build_pipe_name", None)
    assert callable(builder)
    expected = chr(92) * 2 + "." + chr(92) + chr(92).join(("pipe", f"lah-opencode-{session_id}"))
    assert builder(session_id) == expected
    with pytest.raises(ValueError, match="session ID"):
        builder("../pipe")


def test_session_secret_uses_constant_time_exact_32_byte_match():
    expected = bytes(range(32))

    assert verify_session_secret(expected, expected)
    assert not verify_session_secret(expected[:-1], expected)
    assert not verify_session_secret(expected[:-1] + b"!", expected)


def test_response_frames_are_bounded_and_zero_length_marks_end():
    assert encode_response_frame(b"data") == b"\x00\x00\x00\x04data"
    assert encode_response_frame(b"x" * MAX_PIPE_FRAME_BYTES)[:4] == MAX_PIPE_FRAME_BYTES.to_bytes(4, "big")
    assert encode_response_frame(b"", end=True) == b"\x00\x00\x00\x00"
    with pytest.raises(ValueError, match="frame"):
        encode_response_frame(b"x" * (MAX_PIPE_FRAME_BYTES + 1))


def test_hub_request_parser_accepts_only_fixed_origin_form_chat_route():
    raw = (
        b"POST /api/chat/completions HTTP/1.1\r\n"
        b"Host: attacker.invalid\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: 2\r\n\r\n{}"
    )

    request = parse_hub_chat_request(raw)

    assert request == b"{}"


@pytest.mark.parametrize("target", [
    b"http://127.0.0.1:11434/api/chat/completions",
    b"/api/chat/completions?next=http://127.0.0.1:11434/",
    b"/api/models",
    b"//127.0.0.1:11434/api/chat/completions",
])
def test_hub_request_parser_rejects_other_targets(target):
    raw = b"POST " + target + b" HTTP/1.1\r\nContent-Length: 0\r\n\r\n"

    with pytest.raises(ValueError, match="route"):
        parse_hub_chat_request(raw)


def test_hub_request_parser_rejects_chunked_and_ambiguous_http():
    with pytest.raises(ValueError, match="transfer encoding"):
        parse_hub_chat_request(
            b"POST /api/chat/completions HTTP/1.1\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n"
        )
    with pytest.raises(ValueError, match="duplicate"):
        parse_hub_chat_request(
            b"POST /api/chat/completions HTTP/1.1\r\n"
            b"Content-Length: 0\r\nContent-Length: 0\r\n\r\n"
        )
    with pytest.raises(ValueError, match="length"):
        parse_hub_chat_request(
            b"POST /api/chat/completions HTTP/1.1\r\n"
            b"Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}x"
        )


def test_hub_forwarder_uses_only_loopback_fixed_route_and_configured_token():
    observed = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            observed["path"] = self.path
            observed["host"] = self.headers.get("Host")
            observed["authorization"] = self.headers.get("Authorization")
            observed["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            body = b"data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    payload = {"model": "gemma4:12b-128k", "messages": [{"role": "user", "content": "Hi"}]}
    body = json.dumps(payload, separators=(",", ":")).encode()
    try:
        forward = getattr(pipe_broker, "forward_hub_chat", None)
        assert callable(forward)
        result = forward(body, hub_port=server.server_port, api_token="session-hub-token")
    finally:
        server.shutdown()
        worker.join(timeout=2)
        server.server_close()

    assert observed == {
        "path": "/api/chat/completions",
        "host": f"127.0.0.1:{server.server_port}",
        "authorization": "Bearer session-hub-token",
        "body": body,
    }
    assert result == (200, "text/event-stream; charset=utf-8", b"data: [DONE]\n\n")


@pytest.mark.parametrize("port", [0, -1, 65536, True, "1234"])
def test_hub_forwarder_rejects_invalid_ports_before_connecting(port):
    forward = getattr(pipe_broker, "forward_hub_chat", None)
    assert callable(forward)

    with pytest.raises(ValueError, match="port"):
        forward(b"{}", hub_port=port)


def test_pipe_response_builds_bounded_http_and_terminal_frames():
    build = getattr(pipe_broker, "frame_http_response", None)
    assert callable(build)

    frames = build(200, "text/event-stream; charset=utf-8", b"x" * (MAX_PIPE_FRAME_BYTES + 3))

    assert frames[-1] == b"\x00\x00\x00\x00"
    chunks = [frame[4:] for frame in frames[:-1]]
    assert all(1 <= len(chunk) <= MAX_PIPE_FRAME_BYTES for chunk in chunks)
    response = b"".join(chunks)
    assert response.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b"Content-Type: text/event-stream; charset=utf-8\r\n" in response
    assert f"Content-Length: {MAX_PIPE_FRAME_BYTES + 3}\r\n".encode() in response
    assert response.endswith(b"x" * (MAX_PIPE_FRAME_BYTES + 3))


@pytest.mark.parametrize("content_type", ["text/plain", "application/json\r\nX-Evil: yes"])
def test_pipe_response_rejects_unsupported_or_injected_headers(content_type):
    build = getattr(pipe_broker, "frame_http_response", None)
    assert callable(build)

    with pytest.raises(ValueError, match="content type"):
        build(200, content_type, b"body")


def test_pipe_reader_collects_exact_http_message_from_fragmented_byte_pipe():
    reader = getattr(pipe_broker, "_read_pipe_http_request", None)
    assert callable(reader)
    message = (
        b"POST /api/chat/completions HTTP/1.1\r\n"
        b"Content-Type: application/json\r\nContent-Length: 7\r\n\r\n{\"x\":1}"
    )
    source = bytearray(message)

    def read_some(limit):
        count = min(limit, 3, len(source))
        result = bytes(source[:count])
        del source[:count]
        return result

    def read_exact(length):
        result = bytearray()
        while len(result) < length:
            result.extend(read_some(length - len(result)))
        return bytes(result)

    assert reader(read_some, read_exact) == message
    assert not source


def test_pipe_reader_rejects_unframed_or_extra_http_bytes():
    reader = getattr(pipe_broker, "_read_pipe_http_request", None)
    assert callable(reader)

    def make_reader(data):
        source = bytearray(data)

        def read_some(limit):
            count = min(limit, len(source))
            result = bytes(source[:count])
            del source[:count]
            return result

        def read_exact(length):
            result = bytearray()
            while len(result) < length:
                result.extend(read_some(length - len(result)))
            return bytes(result)

        return read_some, read_exact

    missing_length = make_reader(b"POST /api/chat/completions HTTP/1.1\r\n\r\n{}")
    with pytest.raises(ValueError, match="content length"):
        reader(*missing_length)
    extra = make_reader(
        b"POST /api/chat/completions HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}x"
    )
    with pytest.raises(ValueError, match="unexpected bytes"):
        reader(*extra)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named-pipe API required")
def test_windows_pipe_acl_allows_owner_to_connect_for_identity_rejection():
    import win32api
    import win32con
    import win32file

    name = pipe_broker.build_pipe_name(uuid.uuid4().hex)
    handle = pipe_broker._create_windows_opencode_pipe(name, "S-1-15-2-123-456")
    try:
        client = win32file.CreateFile(
            name,
            win32con.GENERIC_READ | win32con.GENERIC_WRITE,
            0,
            None,
            win32con.OPEN_EXISTING,
            0,
            None,
        )
        win32api.CloseHandle(client)
    finally:
        win32api.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows token API required")
def test_windows_token_appcontainer_lookup_fails_closed_for_desktop_token():
    import win32api
    import win32security

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32security.TOKEN_QUERY
    )
    try:
        assert pipe_broker._token_appcontainer_sid(int(token)) is None
    finally:
        win32api.CloseHandle(token)
