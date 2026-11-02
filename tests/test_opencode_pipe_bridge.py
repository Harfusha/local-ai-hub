import queue
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from local_ai_hub.opencode_pipe_bridge import BridgeError, relay_connection


class Pipe:
    def __init__(self, chunks, identities):
        self.chunks = queue.Queue()
        for chunk in chunks:
            self.chunks.put(chunk)
        self.identities = iter(identities)
        self.output = bytearray()
        self.closed = threading.Event()

    def read(self, _limit, timeout):
        try:
            return self.chunks.get(timeout=timeout)
        except queue.Empty:
            return b""

    def matches_identity(self):
        return next(self.identities)

    def write(self, data, _timeout):
        self.output.extend(data)
        if data == b"\x00\x00\x00\x00":
            self.chunks.put(b"\x06")

    def close(self):
        self.closed.set()


class Socket:
    def __init__(self):
        self.input = bytearray()
        self.sent = threading.Event()
        self.closed = False

    def settimeout(self, _value):
        pass

    def sendall(self, data):
        self.input.extend(data)
        self.sent.set()

    def recv(self, _limit):
        if not self.sent.wait(1):
            raise TimeoutError()
        if not self.closed:
            self.closed = True
            return b"HTTP/1.0 200 OK\r\n\r\n"
        return b""

    def shutdown(self, _how):
        self.sent.set()

    def close(self):
        self.closed = True


def test_requires_identity_and_secret_before_router_connection():
    connects = []
    pipe = Pipe([b"x" * 32], [False])
    with pytest.raises(BridgeError):
        relay_connection(pipe, b"x" * 32, lambda: connects.append(True), timeout=1)
    assert not connects and pipe.closed.is_set()
    pipe = Pipe([b"wrong"], [True])
    with pytest.raises(BridgeError):
        relay_connection(pipe, b"x" * 32, lambda: connects.append(True), timeout=1)
    assert not connects and pipe.closed.is_set()


def test_rechecks_identity_before_every_forwarded_chunk():
    target = Socket()
    pipe = Pipe([b"x" * 32, b"GET /health HTTP/1.0\r\n\r\n"], [True, False])
    with pytest.raises(BridgeError):
        relay_connection(pipe, b"x" * 32, lambda: target, timeout=1)
    assert not target.input and pipe.closed.is_set()


def test_forwards_authenticated_request_and_streams_response():
    target = Socket()
    pipe = Pipe([b"x" * 32, b"GET /health HTTP/1.0\r\n\r\n"], [True, True, True])
    relay_connection(pipe, b"x" * 32, lambda: target, timeout=2)
    assert target.input == b"GET /health HTTP/1.0\r\n\r\n"
    response = b"HTTP/1.0 200 OK\r\n\r\n"
    assert pipe.output == len(response).to_bytes(4, "big") + response + b"\x00\x00\x00\x00"
    assert pipe.closed.is_set()


def test_secret_can_arrive_split_across_messages():
    target = Socket()
    pipe = Pipe([b"x" * 10, b"x" * 22 + b"GET /health HTTP/1.0\r\n\r\n"], [True, True, True])
    relay_connection(pipe, b"x" * 32, lambda: target, timeout=2)
    assert target.input == b"GET /health HTTP/1.0\r\n\r\n"


def test_bad_or_missing_acknowledgement_does_not_report_success():
    class BadAck(Pipe):
        def write(self, data, _timeout):
            self.output.extend(data)
            if data == b"\x00\x00\x00\x00":
                self.chunks.put(b"\x15")

    pipe = BadAck([b"x" * 32, b"GET / HTTP/1.0\r\n\r\n"], [True, True, True])
    with pytest.raises(BridgeError, match="acknowledgement"):
        relay_connection(pipe, b"x" * 32, Socket, timeout=1)
    assert pipe.closed.is_set()

    class NoAck(Pipe):
        def write(self, data, _timeout):
            self.output.extend(data)

    pipe = NoAck([b"x" * 32, b"GET / HTTP/1.0\r\n\r\n"], [True, True])
    with pytest.raises(BridgeError, match="deadline"):
        relay_connection(pipe, b"x" * 32, Socket, timeout=0.2)
    assert pipe.closed.is_set()


def test_routes_authenticated_stream_through_real_loopback_router():
    from local_ai_hub.opencode_local_router import LocalRouter

    class Health(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with LocalRouter(server.server_port, server.server_port) as router:
            request = f"GET /health HTTP/1.0\r\nHost: 127.0.0.1:{router.port}\r\n\r\n".encode()
            pipe = Pipe([b"x" * 32, request], [True, True, True])
            relay_connection(pipe, b"x" * 32, lambda: socket.create_connection(("127.0.0.1", router.port), timeout=1), timeout=3)
            assert b"200 OK" in pipe.output and b"ok" in pipe.output and pipe.output.endswith(b"\x00\x00\x00\x00")
    finally:
        server.shutdown()
        server.server_close()
