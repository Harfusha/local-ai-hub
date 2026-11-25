from __future__ import annotations

import threading
from types import SimpleNamespace

from local_ai_hub.supervisor import Supervisor


def test_managed_llama_worker_is_single_owned_and_stops_cooperatively():
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.config = {"llama_cpp": {"mode": "on", "managed_with_ollama": True}}
    supervisor.stopping = False
    supervisor._stop_event = threading.Event()
    supervisor._managed_llama_worker = None
    entered = threading.Event()
    calls = []

    def ensure_running(*, should_stop):
        calls.append("start")
        entered.set()
        supervisor._stop_event.wait(2)
        assert should_stop()
        return False

    owner = SimpleNamespace(ensure_running=ensure_running, _managed_process=object())
    def stop():
        calls.append("stop")
        owner._managed_process = None
        return True
    owner.stop = stop
    supervisor.runtime = SimpleNamespace(llama_cpp_managed=owner)
    supervisor.log = lambda _message: None
    supervisor._start_managed_llama_cpp()
    assert entered.wait(2)
    supervisor._start_managed_llama_cpp()
    supervisor._stop_managed_llama_cpp()
    assert calls == ["start", "stop"]
    assert not supervisor._managed_llama_worker.is_alive()


def test_managed_llama_worker_does_not_require_ollama_mixed_mode():
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.config = {"llama_cpp": {"mode": "on"}}
    supervisor.stopping = False
    supervisor._stop_event = threading.Event()
    supervisor._managed_llama_worker = None
    entered = threading.Event()

    def ensure_running(*, should_stop):
        entered.set()
        while not should_stop():
            supervisor._stop_event.wait(0.01)
        return False

    owner = SimpleNamespace(ensure_running=ensure_running, _managed_process=None)
    supervisor.runtime = SimpleNamespace(llama_cpp_managed=owner)
    supervisor.log = lambda _message: None

    supervisor._start_managed_llama_cpp()

    assert entered.wait(1)
    assert supervisor._managed_llama_worker.is_alive()
    supervisor._stop_managed_llama_cpp()
    assert not supervisor._managed_llama_worker.is_alive()


def test_managed_llama_shutdown_never_stops_unowned_process():
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.config = {"llama_cpp": {"mode": "on", "managed_with_ollama": True}}
    supervisor.stopping = False
    supervisor._stop_event = threading.Event()
    supervisor._managed_llama_worker = None
    calls = []
    owner = SimpleNamespace(ensure_running=lambda **_kw: True, stop=lambda: calls.append("stop"), _managed_process=None)
    supervisor.runtime = SimpleNamespace(llama_cpp_managed=owner)
    supervisor.log = lambda _message: None
    supervisor._start_managed_llama_cpp()
    supervisor._managed_llama_worker.join(timeout=2)
    supervisor._stop_managed_llama_cpp()
    assert calls == []


def test_managed_llama_false_start_result_is_logged_once():
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.config = {"llama_cpp": {"mode": "on", "managed_with_ollama": True}}
    supervisor.stopping = False
    supervisor._stop_event = threading.Event()
    supervisor._managed_llama_worker = None
    messages = []
    owner = SimpleNamespace(
        ensure_running=lambda **_kw: False,
        _managed_process=None,
        _last_error="port bind failed",
    )
    supervisor.runtime = SimpleNamespace(llama_cpp_managed=owner)
    supervisor.log = messages.append

    supervisor._start_managed_llama_cpp()
    supervisor._managed_llama_worker.join(timeout=2)
    supervisor._start_managed_llama_cpp()
    supervisor._managed_llama_worker.join(timeout=2)

    assert messages == ["managed llama.cpp startup incomplete: port bind failed"]


def test_managed_llama_delayed_worker_releases_owned_process_after_shutdown():
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.config = {"llama_cpp": {"mode": "on", "managed_with_ollama": True}}
    supervisor.stopping = False
    supervisor._stop_event = threading.Event()
    supervisor._managed_llama_worker = None
    entered, release = threading.Event(), threading.Event()
    calls = []
    owner = SimpleNamespace(_managed_process=None)

    def ensure_running(*, should_stop):
        entered.set()
        release.wait(2)
        owner._managed_process = object()
        return True

    def stop():
        calls.append("stop")
        owner._managed_process = None
        return True

    owner.ensure_running, owner.stop = ensure_running, stop
    supervisor.runtime = SimpleNamespace(llama_cpp_managed=owner)
    supervisor.log = lambda _message: None
    supervisor._start_managed_llama_cpp()
    assert entered.wait(2)
    worker = supervisor._managed_llama_worker
    original_join = worker.join
    worker.join = lambda timeout=None: None
    supervisor._stop_managed_llama_cpp()
    release.set()
    original_join(timeout=2)
    assert calls == ["stop"]
