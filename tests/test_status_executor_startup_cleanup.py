from __future__ import annotations

import threading

import pytest

from local_ai_hub import app as app_module
from test_t04_current_root_acceptance import _live_api_resources


def test_status_executor_startup_survives_injected_barrier_failure(monkeypatch):
    class BrokenStartupBarrier:
        def wait(self, timeout=None):
            raise threading.BrokenBarrierError

    monkeypatch.setattr(
        app_module.threading,
        "Barrier",
        lambda *_args, **_kwargs: BrokenStartupBarrier(),
    )

    executor = app_module._new_status_dependency_executor()
    try:
        assert executor.submit(lambda: "ready").result(timeout=1) == "ready"
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def test_t04_resources_close_server_when_app_constructor_fails(tmp_path, monkeypatch):
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    servers = []
    original_server = http_server.LocalAIHTTPServer

    def capture_server(*args, **kwargs):
        server = original_server(*args, **kwargs)
        servers.append(server)
        return server

    def fail_constructor(_self, *_args, **_kwargs):
        raise RuntimeError("injected app constructor failure")

    monkeypatch.setattr(http_server, "LocalAIHTTPServer", capture_server)
    monkeypatch.setattr(LocalAIApp, "__init__", fail_constructor)
    resources = _live_api_resources(tmp_path, monkeypatch)

    with pytest.raises(RuntimeError, match="injected app constructor failure"):
        next(resources)

    assert len(servers) == 1
    assert servers[0].socket.fileno() == -1
