import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.request import urlopen

import pytest

from local_ai_hub.opencode_inference_session import ExternalInferenceSession, InferenceSessionError
from local_ai_hub.scheduler import AffinityScheduler


@pytest.fixture
def scheduler(tmp_path):
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": str(tmp_path)}})
    yield scheduler
    scheduler.close()


def test_session_serializes_same_model_and_holds_gpu_between_requests(scheduler):
    session = ExternalInferenceSession.open(scheduler, "model-a")
    assert scheduler.foreground_busy()
    first = session.start_request("model-a")
    with pytest.raises(InferenceSessionError):
        session.start_request("model-a")
    with pytest.raises(InferenceSessionError):
        session.close()
    session.finish_request(first, terminal_confirmed=True)
    assert scheduler.foreground_busy()
    with pytest.raises(InferenceSessionError):
        session.start_request("model-b")
    second = session.start_request("model-a")
    session.finish_request(second, terminal_confirmed=True)
    session.close()
    assert not scheduler.foreground_busy()


def test_unknown_backend_outcome_never_releases_or_accepts_more_work(scheduler):
    session = ExternalInferenceSession.open(scheduler, "model-a")
    request = session.start_request("model-a")
    session.finish_request(request, terminal_confirmed=False)
    with pytest.raises(InferenceSessionError):
        session.start_request("model-a")
    with pytest.raises(InferenceSessionError):
        session.close()
    assert scheduler.foreground_busy()


def test_idle_timeout_releases_and_next_request_reacquires(scheduler, monkeypatch):
    timers = []

    class Timer:
        def __init__(self, delay, callback, args=()):
            self.delay, self.callback, self.args, self.cancelled = delay, callback, args, False
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

        def fire(self):
            if not self.cancelled:
                self.callback(*self.args)

    monkeypatch.setattr("local_ai_hub.opencode_inference_session.threading.Timer", Timer)
    session = ExternalInferenceSession.open(scheduler, "model-a", idle_timeout_seconds=60)
    assert timers[-1].delay == 60
    timers[-1].fire()
    assert not scheduler.foreground_busy()
    request = session.start_request("model-a")
    assert scheduler.foreground_busy()
    session.finish_request(request, terminal_confirmed=True)
    timers[-1].fire()
    assert not scheduler.foreground_busy()
    session.close()


def test_idle_timeout_never_releases_running_or_uncertain_request(scheduler, monkeypatch):
    timers = []

    class Timer:
        def __init__(self, delay, callback, args=()):
            self.callback, self.args = callback, args
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr("local_ai_hub.opencode_inference_session.threading.Timer", Timer)
    session = ExternalInferenceSession.open(scheduler, "model-a", idle_timeout_seconds=60)
    request = session.start_request("model-a")
    timers[0].callback(*timers[0].args)
    assert scheduler.foreground_busy()
    session.finish_request(request, terminal_confirmed=False)
    timers[0].callback(*timers[0].args)
    assert scheduler.foreground_busy()


def test_idle_timeout_release_failure_keeps_session_fenced(scheduler, monkeypatch):
    timers = []

    class Timer:
        def __init__(self, delay, callback, args=()):
            self.callback, self.args = callback, args
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr("local_ai_hub.opencode_inference_session.threading.Timer", Timer)
    session = ExternalInferenceSession.open(scheduler, "model-a", idle_timeout_seconds=60)
    monkeypatch.setattr(scheduler, "release_external_gpu", lambda _token: False)
    timers[0].callback(*timers[0].args)
    assert scheduler.foreground_busy()
    with pytest.raises(InferenceSessionError):
        session.start_request("model-a")


def test_concurrent_requests_have_only_one_winner(scheduler):
    session = ExternalInferenceSession.open(scheduler, "model-a")
    barrier, results = threading.Barrier(3), []
    def start():
        barrier.wait(timeout=2)
        try:
            results.append(session.start_request("model-a"))
        except InferenceSessionError:
            results.append(None)
    threads = [threading.Thread(target=start) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=2)
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert sum(value is not None for value in results) == 1
    session.finish_request(next(value for value in results if value), terminal_confirmed=True)
    session.close()


def test_invalid_completion_cannot_release_gpu(scheduler):
    session = ExternalInferenceSession.open(scheduler, "model-a")
    request = session.start_request("model-a")
    for wrong in ("wrong", "ž", ""):
        with pytest.raises(InferenceSessionError):
            session.finish_request(wrong, terminal_confirmed=True)
    for invalid in (None, 1, "true"):
        with pytest.raises(InferenceSessionError):
            session.finish_request(request, terminal_confirmed=invalid)
    with pytest.raises(InferenceSessionError):
        session.close()
    assert scheduler.foreground_busy()
    session.finish_request(request, terminal_confirmed=True)
    session.close()


def test_invalid_model_and_failed_reservation_do_not_start_session(scheduler):
    for invalid in (None, "", " other", "a\nmodel", "a" * 257):
        with pytest.raises(InferenceSessionError):
            ExternalInferenceSession.open(scheduler, invalid)
    first = ExternalInferenceSession.open(scheduler, "model-a")
    with pytest.raises(InferenceSessionError):
        ExternalInferenceSession.open(scheduler, "model-a")
    first.close()


def test_relay_requires_complete_upstream_stream_before_releasing_request(scheduler):
    session = ExternalInferenceSession.open(scheduler, "model-a")
    chunks = [b'data: {"choices":[]}\n\n', b'data: [DONE]\n\n']
    received = []
    session.relay_stream("model-a", lambda: iter(chunks), received.append)
    assert received == chunks
    assert scheduler.foreground_busy()
    session.close()


@pytest.mark.parametrize("mode", ["truncated", "source_error", "client_error"])
def test_unconfirmed_or_interrupted_relay_never_releases_gpu(scheduler, mode):
    session = ExternalInferenceSession.open(scheduler, "model-a")
    def source():
        yield b'data: {"choices":[]}\n\n'
        if mode == "source_error":
            raise OSError("upstream closed")
        if mode == "client_error":
            yield b'data: [DONE]\n\n'
    def sink(chunk):
        if mode == "client_error":
            raise OSError("client disconnected")
    with pytest.raises((InferenceSessionError, OSError)):
        session.relay_stream("model-a", source, sink)
    with pytest.raises(InferenceSessionError):
        session.close()
    assert scheduler.foreground_busy()


def test_relay_reads_real_loopback_http_stream_without_model_inference(scheduler):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'data: {"choices":[]}\n\ndata: [DONE]\n\n')
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = ExternalInferenceSession.open(scheduler, "model-a")
    try:
        def source():
            with urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=3) as response:
                while chunk := response.read(5):
                    yield chunk
        chunks = []
        session.relay_stream("model-a", source, chunks.append)
        assert b"".join(chunks).endswith(b"data: [DONE]\n\n")
        session.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
