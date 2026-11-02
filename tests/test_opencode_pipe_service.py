import threading

import pytest

from local_ai_hub.opencode_pipe_bridge import BridgeError
from local_ai_hub.opencode_pipe_service import PipeService


def test_service_rejects_invalid_target_and_secret():
    for port in (0, 65536, True, "12"):
        with pytest.raises(ValueError):
            PipeService("sid", b"x" * 32, port)
    with pytest.raises(ValueError):
        PipeService("sid", b"short", 42)


def test_service_survives_rejected_client_and_stops(monkeypatch):
    import local_ai_hub.opencode_pipe_service as service
    calls = []
    finished = threading.Event()

    class Pipe:
        def close(self):
            calls.append("pipe_closed")

    class Listener:
        name = "pipe-name"
        def __init__(self, sid):
            assert sid == "sid"
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            calls.append("listener_closed")
        def accept(self, *, timeout, stop):
            if not calls:
                calls.append("accepted")
                return Pipe()
            finished.set()
            stop.wait(timeout)
            raise InterruptedError()

    def reject(pipe, secret, connect, *, timeout):
        assert secret == b"x" * 32
        calls.append("rejected")
        raise BridgeError("bad peer")

    monkeypatch.setattr(service, "WindowsPipeListener", Listener)
    monkeypatch.setattr(service, "relay_connection", reject)
    with PipeService("sid", b"x" * 32, 1234) as server:
        assert server.name == "pipe-name"
        assert finished.wait(2)
    assert calls == ["accepted", "rejected", "pipe_closed", "listener_closed"]


def test_service_reports_unexpected_worker_failure(monkeypatch):
    import local_ai_hub.opencode_pipe_service as service
    failed = threading.Event()

    class Listener:
        name = "pipe-name"
        def __init__(self, sid): pass
        def __enter__(self): return self
        def __exit__(self, *_args): failed.set()
        def accept(self, *, timeout, stop): raise OSError("broken")

    monkeypatch.setattr(service, "WindowsPipeListener", Listener)
    server = PipeService("sid", b"x" * 32, 1234).__enter__()
    assert failed.wait(2)
    with pytest.raises(RuntimeError, match="relay service failed"):
        server.check_health()
    with pytest.raises(RuntimeError, match="relay service failed"):
        server.close()


def test_close_interrupts_active_relay(monkeypatch):
    import local_ai_hub.opencode_pipe_service as service
    active = threading.Event()
    stopped = threading.Event()

    class Pipe:
        def close(self): stopped.set()
    class Listener:
        name = "pipe-name"
        def __init__(self, sid): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def accept(self, *, timeout, stop): return Pipe()
    def relay(pipe, secret, connect, *, timeout):
        active.set()
        assert stopped.wait(2)

    monkeypatch.setattr(service, "WindowsPipeListener", Listener)
    monkeypatch.setattr(service, "relay_connection", relay)
    server = PipeService("sid", b"x" * 32, 1234).__enter__()
    assert active.wait(2)
    server.close()
    assert stopped.is_set()
