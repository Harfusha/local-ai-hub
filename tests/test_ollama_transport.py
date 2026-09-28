from __future__ import annotations

import threading
from contextlib import contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

import local_ai_hub.ollama as ollama_module
from local_ai_hub.ollama import OllamaRuntime


def _runtime(base_url: str = "http://ollama", *, attempts: int = 1) -> OllamaRuntime:
    runtime = object.__new__(OllamaRuntime)
    runtime.config = {
        "ollama": {
            "enabled": True,
            "request_attempts": attempts,
            "retry_delay_seconds": 0,
        }
    }
    runtime.base_url = base_url
    runtime.timeout = 3
    runtime.llama_cpp = None
    return runtime


class _RecordingHTTPError(HTTPError):
    def __init__(self, body: bytes):
        super().__init__("http://ollama/error", 500, "failure", {}, BytesIO(body))
        self.read_sizes: list[int] = []

    def read(self, amt: int = -1) -> bytes:
        self.read_sizes.append(amt)
        return super().read(amt)


def _raise_http_error(error: HTTPError):
    @contextmanager
    def open_response(*_args, **_kwargs):
        raise error
        yield  # pragma: no cover

    return open_response


@pytest.mark.parametrize("entrypoint", ["request", "request_stream", "request_interruptible"])
def test_http_error_body_read_is_bounded(entrypoint: str, monkeypatch: pytest.MonkeyPatch):
    error = _RecordingHTTPError(b"x" * 100_000)
    runtime = _runtime()
    if entrypoint == "request":
        monkeypatch.setattr(ollama_module, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
        runtime.request("/api/version", timeout=2)
    else:
        monkeypatch.setattr(ollama_module, "_open_interruptible_response", _raise_http_error(error))
        if entrypoint == "request_stream":
            runtime.request_stream("/api/generate", {"model": "test"}, lambda _text: None, timeout=2)
        else:
            runtime.request_interruptible("/api/generate", {"model": "test"}, lambda: False, timeout=2)

    assert error.read_sizes == [65_537]


def test_request_interruptible_cancels_while_waiting_for_headers():
    request_received = threading.Event()
    release_handler = threading.Event()

    class SlowHeadersHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            request_received.set()
            release_handler.wait(3)
            try:
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHeadersHandler)
    server.daemon_threads = True
    server.block_on_close = False
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    cancelled = threading.Event()
    result: dict[str, object] = {}
    request_thread = threading.Thread(
        target=lambda: result.setdefault(
            "value",
            _runtime(f"http://127.0.0.1:{server.server_port}").request_interruptible(
                "/api/generate", {"model": "test"}, cancelled.is_set, timeout=2
            ),
        ),
        daemon=True,
    )
    request_thread.start()
    try:
        assert request_received.wait(1)
        cancelled.set()
        request_thread.join(0.75)
        stopped_before_headers = not request_thread.is_alive()
    finally:
        release_handler.set()
        server.shutdown()
        server.server_close()
        request_thread.join(1)

    assert stopped_before_headers
    assert isinstance(result.get("value"), dict)
    assert result["value"].get("preempted") is True


def test_stream_retry_does_not_replay_emitted_partial_text(monkeypatch: pytest.MonkeyPatch):
    attempts = 0

    class Response:
        def __init__(self, lines):
            self.lines = lines

        def __iter__(self):
            return self.lines

    @contextmanager
    def open_response(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            def broken_stream():
                yield b'{"response":"partial","done":false}\n'
                raise URLError("connection reset")

            yield Response(broken_stream())
        else:
            yield Response(iter([b'{"response":"restarted","done":true}\n']))

    monkeypatch.setattr(ollama_module, "_open_interruptible_response", open_response)
    monkeypatch.setattr(ollama_module, "_cancel_response_on_stop", lambda *_args, **_kwargs: nullcontext())
    emitted: list[str] = []

    result = _runtime(attempts=2).request_stream(
        "/api/generate", {"model": "test"}, emitted.append, timeout=2
    )

    assert attempts == 1
    assert emitted == ["partial"]
    assert result.get("error")
    assert result.get("_lah_partial_response") is True


def test_non_stream_request_can_retry_without_exposing_partial_chunks(monkeypatch: pytest.MonkeyPatch):
    attempts = 0

    class Response:
        def __init__(self, lines):
            self.lines = lines

        def __iter__(self):
            return self.lines

    @contextmanager
    def open_response(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            def broken_stream():
                yield b'{"response":"discarded","done":false}\n'
                raise URLError("connection reset")

            yield Response(broken_stream())
        else:
            yield Response(iter([b'{"response":"complete","done":true}\n']))

    monkeypatch.setattr(ollama_module, "_open_interruptible_response", open_response)
    monkeypatch.setattr(ollama_module, "_cancel_response_on_stop", lambda *_args, **_kwargs: nullcontext())

    result = _runtime(attempts=2).request("/api/generate", {"model": "test"}, timeout=2)

    assert attempts == 2
    assert result["response"] == "complete"
