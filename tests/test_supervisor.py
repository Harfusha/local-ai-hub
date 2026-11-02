from __future__ import annotations

import threading
from types import SimpleNamespace

from local_ai_hub.supervisor import Supervisor


def test_mixed_cuda_worker_is_single_owned_and_stops_cooperatively():
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.config = {"llama_cpp": {"managed_with_ollama": True}}
    supervisor.stopping = False
    supervisor._stop_event = threading.Event()
    supervisor._mixed_cuda_worker = None
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
    supervisor._start_mixed_cuda()
    assert entered.wait(2)
    supervisor._start_mixed_cuda()
    supervisor._stop_mixed_cuda()
    assert calls == ["start", "stop"]
    assert not supervisor._mixed_cuda_worker.is_alive()


def test_mixed_cuda_shutdown_never_stops_unowned_process():
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.config = {"llama_cpp": {"managed_with_ollama": True}}
    supervisor.stopping = False
    supervisor._stop_event = threading.Event()
    supervisor._mixed_cuda_worker = None
    calls = []
    owner = SimpleNamespace(ensure_running=lambda **_kw: True, stop=lambda: calls.append("stop"), _managed_process=None)
    supervisor.runtime = SimpleNamespace(llama_cpp_managed=owner)
    supervisor.log = lambda _message: None
    supervisor._start_mixed_cuda()
    supervisor._mixed_cuda_worker.join(timeout=2)
    supervisor._stop_mixed_cuda()
    assert calls == []


def test_mixed_cuda_delayed_worker_releases_owned_process_after_shutdown():
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.config = {"llama_cpp": {"managed_with_ollama": True}}
    supervisor.stopping = False
    supervisor._stop_event = threading.Event()
    supervisor._mixed_cuda_worker = None
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
    supervisor._start_mixed_cuda()
    assert entered.wait(2)
    worker = supervisor._mixed_cuda_worker
    original_join = worker.join
    worker.join = lambda timeout=None: None
    supervisor._stop_mixed_cuda()
    release.set()
    original_join(timeout=2)
    assert calls == ["stop"]
