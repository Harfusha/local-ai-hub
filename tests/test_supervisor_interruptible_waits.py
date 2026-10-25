from __future__ import annotations

import signal
import socket as _socket
import threading

from local_ai_hub import supervisor as supervisor_module


class _FakeChild:
    pid = 424242

    def __init__(self) -> None:
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, *, timeout: float) -> int:
        assert timeout > 0
        return 0 if self.returncode is None else self.returncode


class _FakeRuntime:
    def ensure_running(self) -> bool:
        return True


class _ObservedEvent(threading.Event):
    def __init__(self, long_wait_entered: threading.Event) -> None:
        super().__init__()
        self._long_wait_entered = long_wait_entered

    def wait(self, timeout: float | None = None) -> bool:
        # Keep a failed implementation bounded while preserving a real Event wakeup.
        if timeout is not None and timeout >= 0.1:
            self._long_wait_entered.set()
            if timeout >= 5:
                timeout = min(timeout, 1.25)
        return super().wait(timeout)


class _ThreadingProxy:
    def __init__(self, long_wait_entered: threading.Event, relay_threads: list[threading.Thread]) -> None:
        self._long_wait_entered = long_wait_entered
        self._relay_threads = relay_threads

    def __getattr__(self, name: str):
        return getattr(threading, name)

    def Event(self) -> _ObservedEvent:
        return _ObservedEvent(self._long_wait_entered)

    def Thread(self, *args, **kwargs) -> threading.Thread:
        thread = threading.Thread(*args, **kwargs)
        if kwargs.get("name") == "local-ai-supervisor-signal-wakeup":
            self._relay_threads.append(thread)
        return thread


class _SocketProxy:
    def __init__(self, socket_pairs: list[tuple[_socket.socket, _socket.socket]]) -> None:
        self._socket_pairs = socket_pairs

    def socketpair(self, *args, **kwargs) -> tuple[_socket.socket, _socket.socket]:
        pair = _socket.socketpair(*args, **kwargs)
        self._socket_pairs.append(pair)
        return pair


def _run_shutdown_during_long_wait(tmp_path, monkeypatch, *, wait_status: str) -> None:
    state_dir = tmp_path / "state"
    config = tmp_path / "hub.toml"
    config.write_text(
        f'[server]\nstate_dir = "{state_dir.as_posix()}"\nport = 11435\n'
        '[headless]\nrespect_disabled_marker = false\nmanage_ollama = false\n'
        'health_check_interval_seconds = 15\n'
        'rapid_crash_window_seconds = 10\nrapid_crash_limit = 2\n'
        'rapid_crash_cooldown_seconds = 15\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(supervisor_module, "OllamaRuntime", lambda _config: _FakeRuntime())
    monkeypatch.setattr(supervisor_module, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(
        supervisor_module,
        "process_owner_record",
        lambda pid, path, role: {
            "pid": pid,
            "executable": "python",
            "creation_identity": "test",
            "creation_identity_type": "test",
            "state_dir": str(path.resolve()),
            "role": role,
        },
    )
    monkeypatch.setattr(
        supervisor_module,
        "process_owner_state",
        lambda owner, _path, role: "owned"
        if isinstance(owner, dict) and owner.get("pid") == supervisor_module.os.getpid()
        and role == "supervisor"
        else "unknown",
    )

    status_reached = threading.Event()
    long_wait_entered = threading.Event()
    relay_threads: list[threading.Thread] = []
    socket_pairs: list[tuple[_socket.socket, _socket.socket]] = []
    spawn_calls: list[None] = []
    termination_calls: list[_FakeChild] = []
    monkeypatch.setattr(
        supervisor_module,
        "threading",
        _ThreadingProxy(long_wait_entered, relay_threads),
    )
    monkeypatch.setattr(
        supervisor_module,
        "socket",
        _SocketProxy(socket_pairs),
    )

    supervisor = supervisor_module.Supervisor(str(config))
    child = _FakeChild()
    if wait_status == "running":
        supervisor.child = child
        supervisor.child_ready = True
    elif wait_status == "cooldown":
        supervisor.crashes = [supervisor_module.time.time(), supervisor_module.time.time()]
    else:
        raise AssertionError(f"unexpected status {wait_status}")

    def write_status(status: str, *_args, **_kwargs) -> None:
        if status == wait_status:
            status_reached.set()

    def start_child() -> None:
        spawn_calls.append(None)

    def terminate_process_handle(_child, _pidfd, *, grace_seconds: float) -> bool:
        assert grace_seconds > 0
        termination_calls.append(_child)
        child.returncode = 0
        return True

    supervisor.write_status = write_status
    supervisor.hub_online = lambda: True
    supervisor._start_child = start_child
    monkeypatch.setattr(supervisor_module, "terminate_process_handle", terminate_process_handle)

    result: list[int] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            result.append(supervisor.run())
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert status_reached.wait(timeout=2), f"run loop never reached {wait_status} status"
        assert long_wait_entered.wait(timeout=2), "run loop did not enter its long wait"
        supervisor._handle_signal(signal.SIGTERM)
        worker.join(timeout=0.75)
        assert not worker.is_alive(), "shutdown did not wake the supervisor's long wait promptly"
    finally:
        supervisor._handle_signal(signal.SIGTERM)
        worker.join(timeout=2)

    assert not worker.is_alive(), "supervisor thread did not finish after bounded cleanup"
    assert errors == []
    assert result == [0]
    assert supervisor.child is None
    assert spawn_calls == []
    if wait_status == "running":
        assert child.returncode == 0
        assert termination_calls == [child]
    else:
        assert child.returncode is None
        assert termination_calls == []
    assert not supervisor.lock_path.exists()
    assert len(socket_pairs) == 1
    assert all(sock.fileno() == -1 for sock in socket_pairs[0])
    assert len(relay_threads) == 1
    assert not relay_threads[0].is_alive()


def test_shutdown_interrupts_healthy_interval_and_cleans_up(tmp_path, monkeypatch):
    _run_shutdown_during_long_wait(tmp_path, monkeypatch, wait_status="running")


def test_shutdown_interrupts_crash_cooldown_without_respawning(tmp_path, monkeypatch):
    _run_shutdown_during_long_wait(tmp_path, monkeypatch, wait_status="cooldown")


def test_disabled_marker_returns_without_creating_wakeup_resources(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    config = tmp_path / "hub.toml"
    config.write_text(
        f'[server]\nstate_dir = "{state_dir.as_posix()}"\nport = 11435\n'
        '[headless]\nrespect_disabled_marker = true\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(supervisor_module, "OllamaRuntime", lambda _config: _FakeRuntime())
    supervisor = supervisor_module.Supervisor(str(config))
    supervisor.disabled_path.write_text("disabled", encoding="utf-8")
    relay_threads: list[threading.Thread] = []
    socket_pairs: list[tuple[_socket.socket, _socket.socket]] = []
    monkeypatch.setattr(supervisor_module, "threading", _ThreadingProxy(threading.Event(), relay_threads))
    monkeypatch.setattr(supervisor_module, "socket", _SocketProxy(socket_pairs))

    assert supervisor.run() == 0
    assert socket_pairs == []
    assert relay_threads == []
