from __future__ import annotations

import subprocess
import threading
import time
import os

import pytest

from local_ai_hub import client as client_module


class FakeProcess:
    def __init__(self, pid: int = 94123) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake-hub", timeout)
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


def make_client(monkeypatch, state_dir, *, startup_wait: float = 0.5):
    config = {
        "_config_path": str(state_dir / "hub.toml"),
        "server": {"state_dir": str(state_dir), "bind": "127.0.0.1", "port": 11435},
        "client": {"startup_wait_seconds": startup_wait, "startup_poll_seconds": 0.005},
        "headless": {"respect_disabled_marker": True},
        "security": {"api_token": ""},
    }
    monkeypatch.setattr(client_module, "load_config", lambda _path: dict(config))
    monkeypatch.setattr(client_module, "bounded_startup_wait", lambda value: float(value))
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(client_module, "_DETACHED_CHILDREN", [])
    client = client_module.HubClient(auto_start=True)
    client.health_timeout = 0.01
    client.startup_poll = 0.005
    client.start_lock_stale = startup_wait
    return client


def install_process_mocks(monkeypatch, process, *, identity=None, terminate=None):
    identities = identity or (lambda pid: {"creation_identity_type": "test", "creation_identity": str(pid)})
    monkeypatch.setattr(client_module, "process_identity", identities)
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        client_module,
        "terminate_tree",
        terminate or (lambda *_args, **_kwargs: setattr(process, "returncode", 0)),
    )


def test_matching_failed_child_is_terminated_and_reaped_once(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, startup_wait=0.05)
    process = FakeProcess()
    terminations = []
    install_process_mocks(
        monkeypatch,
        process,
        terminate=lambda pid, **_kwargs: (terminations.append(pid), setattr(process, "returncode", 0)),
    )
    client._online = lambda _timeout=None: False

    assert client.ensure_server(timeout=0.05) is False
    assert terminations == [process.pid]
    assert process.returncode == 0


def test_spawn_failure_clears_only_startup_lock_metadata(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, startup_wait=0.05)
    monkeypatch.setattr(client_module, "process_identity", lambda pid: {"creation_identity_type": "test", "creation_identity": str(pid)})
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("spawn failed")))
    client._online = lambda _timeout=None: False

    assert client.ensure_server(timeout=0.05) is False
    assert not (tmp_path / "hub.start.lock").exists()
    assert not list(tmp_path.glob("hub.start.lock.*.pid"))


@pytest.mark.parametrize("marker", ["service.disabled", "service.managed"])
def test_service_markers_never_spawn_direct_child(monkeypatch, tmp_path, marker):
    client = make_client(monkeypatch, tmp_path, startup_wait=0.05)
    (tmp_path / marker).write_text("managed", encoding="ascii")
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("unexpected child spawn"))
    client._online = lambda _timeout=None: False

    assert client.ensure_server(timeout=0.05) is False


def test_live_supervisor_and_existing_listener_never_spawn_direct_child(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, startup_wait=0.05)
    (tmp_path / "supervisor.pid").write_text(str(os.getpid()), encoding="ascii")
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("unexpected child spawn"))
    client._online = lambda _timeout=None: False

    assert client.ensure_server(timeout=0.05) is False

    (tmp_path / "supervisor.pid").unlink()
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: 99999)
    assert client.ensure_server(timeout=0.05) is False


def test_startup_wait_never_exceeds_remaining_request_budget(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, startup_wait=0.5)
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("zero budget must not spawn"))
    client._online = lambda _timeout=None: False
    started = time.monotonic()

    assert client.ensure_server(timeout=0) is False
    assert time.monotonic() - started < 0.1


def test_bounded_startup_wait_rejects_nonfinite_and_caps_values():
    assert client_module.bounded_startup_wait(float("inf")) == 15.0
    assert client_module.bounded_startup_wait(-100) == 1.0
    assert client_module.bounded_startup_wait(10_000) == client_module.MAX_STARTUP_WAIT_SECONDS


def test_concurrent_callers_share_one_child_and_observe_ready_hub(monkeypatch, tmp_path):
    ready = threading.Event()
    both_entered = threading.Barrier(2)
    spawn_started = threading.Event()
    process = FakeProcess()
    calls = []
    calls_lock = threading.Lock()

    def popen(*_args, **_kwargs):
        with calls_lock:
            calls.append(1)
        spawn_started.set()
        return process

    monkeypatch.setattr(client_module.subprocess, "Popen", popen)
    monkeypatch.setattr(client_module, "process_identity", lambda pid: {"creation_identity_type": "test", "creation_identity": str(pid)})
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(client_module, "_DETACHED_CHILDREN", [])
    clients = [make_client(monkeypatch, tmp_path, startup_wait=0.5) for _ in range(2)]
    online_seen = threading.local()

    def online(_timeout=None):
        if not getattr(online_seen, "entered", False):
            online_seen.entered = True
            both_entered.wait(timeout=1.0)
        return ready.is_set()

    for client in clients:
        client._online = online
    results = {}

    def run(index):
        results[index] = clients[index].ensure_server(timeout=0.5)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    assert spawn_started.wait(timeout=1.0)
    time.sleep(0.03)
    ready.set()
    for thread in threads:
        thread.join(timeout=1.0)

    assert all(not thread.is_alive() for thread in threads)
    assert results == {0: True, 1: True}
    assert len(calls) == 1
    assert process.returncode is None


def test_short_timeout_defers_child_cleanup_until_last_live_waiter(monkeypatch, tmp_path):
    short_client = make_client(monkeypatch, tmp_path, startup_wait=0.6)
    long_client = make_client(monkeypatch, tmp_path, startup_wait=0.6)
    process = FakeProcess()
    spawn_started = threading.Event()
    long_waiting = threading.Event()
    short_done = threading.Event()
    long_done = threading.Event()
    calls = []
    terminations = []
    online_calls: dict[str, int] = {}
    calls_lock = threading.Lock()

    def popen(*_args, **_kwargs):
        with calls_lock:
            calls.append(1)
        spawn_started.set()
        return process

    monkeypatch.setattr(client_module.subprocess, "Popen", popen)
    monkeypatch.setattr(client_module, "process_identity", lambda pid: {"creation_identity_type": "test", "creation_identity": str(pid)})
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(client_module, "_DETACHED_CHILDREN", [])
    monkeypatch.setattr(
        client_module,
        "terminate_tree",
        lambda pid, **_kwargs: (terminations.append(pid), setattr(process, "returncode", 0)),
    )

    def short_online(_timeout=None):
        return False

    def long_online(_timeout=None):
        name = threading.current_thread().name
        with calls_lock:
            online_calls[name] = online_calls.get(name, 0) + 1
            if online_calls[name] >= 3:
                long_waiting.set()
        return False

    short_client._online = short_online
    long_client._online = long_online

    results = {}

    def run_short():
        results["short"] = short_client.ensure_server(timeout=0.18)
        short_done.set()

    def run_long():
        results["long"] = long_client.ensure_server(timeout=0.55)
        long_done.set()

    short_thread = threading.Thread(target=run_short, name="short-waiter")
    short_thread.start()
    assert spawn_started.wait(timeout=1.0)
    long_thread = threading.Thread(target=run_long, name="long-waiter")
    long_thread.start()
    assert long_waiting.wait(timeout=1.0)
    assert short_done.wait(timeout=1.0)

    assert terminations == []
    assert long_done.is_set() is False
    assert long_thread.is_alive()
    long_thread.join(timeout=1.0)
    short_thread.join(timeout=1.0)

    assert results == {"short": False, "long": False}
    assert len(calls) == 1
    assert terminations == [process.pid]
    assert process.returncode == 0


def test_guard_contention_does_not_leave_completed_waiter_record(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, startup_wait=0.05)
    process = FakeProcess()
    install_process_mocks(monkeypatch, process)
    client._online = lambda _timeout=None: False
    acquire = client_module._try_start_lock_guard
    calls = 0

    def briefly_contended(path):
        nonlocal calls
        calls += 1
        if 3 <= calls <= 7:
            return None
        return acquire(path)

    monkeypatch.setattr(client_module, "_try_start_lock_guard", briefly_contended)

    assert client.ensure_server(timeout=0.05) is False
    assert calls >= 8
    assert not list((tmp_path / "hub.start.waiters").glob("*.json"))
    assert not (tmp_path / "hub.start.lock").exists()
    assert process.returncode == 0


def test_pid_reuse_mismatch_never_terminates_replacement_process(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, startup_wait=0.05)
    process = FakeProcess()
    child_identity_reads = 0
    terminations = []

    def identity(pid):
        nonlocal child_identity_reads
        if pid != process.pid:
            return {"creation_identity_type": "test", "creation_identity": str(pid)}
        child_identity_reads += 1
        value = "original-child" if child_identity_reads == 1 else "replacement-process"
        return {"creation_identity_type": "test", "creation_identity": value}

    install_process_mocks(
        monkeypatch,
        process,
        identity=identity,
        terminate=lambda pid, **_kwargs: terminations.append(pid),
    )
    client._online = lambda _timeout=None: False

    assert client.ensure_server(timeout=0.05) is False
    assert terminations == []
    assert process.returncode is None
