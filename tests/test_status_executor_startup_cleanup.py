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


@pytest.mark.parametrize("finish", ["complete", "cancel", "shutdown"])
def test_submit_returns_while_worker_startup_is_blocked(monkeypatch, finish):
    from concurrent.futures import CancelledError, Future, ThreadPoolExecutor

    entered = threading.Event()
    release = threading.Event()
    returned = threading.Event()
    startup_threads = []
    submitted = []
    errors = []
    ran = threading.Event()
    original_adjust = ThreadPoolExecutor._adjust_thread_count

    def blocked_adjust(executor):
        startup_threads.append(threading.get_ident())
        entered.set()
        if not release.wait(timeout=5):
            raise TimeoutError("test worker startup gate was not released")
        original_adjust(executor)

    monkeypatch.setattr(ThreadPoolExecutor, "_adjust_thread_count", blocked_adjust)
    executor = app_module._new_status_dependency_executor()

    def submit():
        try:
            submitted.append(executor.submit(ran.set))
        except BaseException as exc:
            errors.append(exc)
        finally:
            returned.set()

    caller = threading.Thread(target=submit, daemon=True)
    shutdown_thread = None
    try:
        caller.start()
        assert entered.wait(timeout=1), "injected worker startup was not entered"
        assert returned.wait(timeout=0.1), "submit waited for blocked worker startup"
        assert not errors
        assert len(submitted) == 1
        future = submitted[0]
        assert isinstance(future, Future)
        assert startup_threads[0] != caller.ident
        assert not release.is_set()
        assert not future.done()
        assert not ran.is_set()

        if finish == "cancel":
            assert future.cancel()
        elif finish == "shutdown":
            shutdown_returned = threading.Event()
            shutdown_errors = []

            def shutdown():
                try:
                    executor.shutdown(wait=False, cancel_futures=True)
                except BaseException as exc:
                    shutdown_errors.append(exc)
                finally:
                    shutdown_returned.set()

            shutdown_thread = threading.Thread(target=shutdown, daemon=True)
            shutdown_thread.start()
            assert shutdown_returned.wait(timeout=0.1), "shutdown waited for worker startup"
            assert not shutdown_errors
            with pytest.raises(RuntimeError):
                executor.submit(lambda: None)

        release.set()
        if finish == "complete":
            assert future.result(timeout=1) is None
            assert ran.is_set()
        else:
            with pytest.raises(CancelledError):
                future.result(timeout=1)
            assert not ran.is_set()
    finally:
        release.set()
        caller.join(timeout=1)
        if shutdown_thread is not None:
            shutdown_thread.join(timeout=1)
        executor.shutdown(wait=False, cancel_futures=True)
    assert not caller.is_alive()
    assert shutdown_thread is None or not shutdown_thread.is_alive()
