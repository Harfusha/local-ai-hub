"""Tests for Windows Named Pipe message framing and client/server IPC."""

import sys
import time

from src.local_ai_hub.named_pipe_ipc import (
    NamedPipeClient,
    NamedPipeMessage,
    NamedPipeServer,
)


def test_named_pipe_message_encode_decode():
    payload = {"action": "ping", "data": [1, 2, 3], "correlation_id": "req_99"}
    msg = NamedPipeMessage(payload=payload, correlation_id="req_99")
    encoded = msg.encode()

    assert len(encoded) > 4
    decoded, remaining = NamedPipeMessage.decode(encoded)
    assert decoded is not None
    assert decoded.payload == payload
    assert decoded.correlation_id == "req_99"
    assert remaining == b""


def test_named_pipe_client_server_ipc():
    if sys.platform != "win32":
        return

    test_pipe = r"\\.\pipe\local-ai-hub-test-ipc"

    def echo_handler(req: dict) -> dict:
        return {"echo": req.get("msg", ""), "status": "ok"}

    server = NamedPipeServer(pipe_name=test_pipe, handler=echo_handler)
    started = server.start()
    assert started is True

    try:
        time.sleep(0.1)  # Allow server thread to initialize
        client = NamedPipeClient(pipe_name=test_pipe)
        resp = client.call({"msg": "hello_pipe"})
        assert resp.get("status") == "ok"
        assert resp.get("echo") == "hello_pipe"
    finally:
        server.stop()
