from __future__ import annotations

import errno
import json
import multiprocessing
import os
import socket
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient, _TransportFailure


def _client(tmp_path: Path) -> HubClient:
    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"[server]\nport=39123\nstate_dir='{state_dir.as_posix()}'\n"
        "[client]\nstartup_wait_seconds=1.0\nstartup_poll_seconds=0.01\n",
        encoding="utf-8",
    )
    return HubClient(config_path=str(config_path), auto_start=True)


def _install_mode(monkeypatch, mode: str, *, degraded: bool = False) -> list[Path]:
    module = types.ModuleType("local_ai_hub.operational_mode")
    loaded: list[Path] = []

    def load_operational_mode(state_dir: str | Path):
        loaded.append(Path(state_dir))
        return SimpleNamespace(mode=mode, degraded=degraded)

    module.load_operational_mode = load_operational_mode
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return loaded


def _refused() -> _TransportFailure:
    return _TransportFailure(ConnectionRefusedError(errno.ECONNREFUSED, "offline"), request_not_sent=True)


def _cross_process_start_worker(config_path, ready_path, launch_dir, barrier, result_queue):
    from local_ai_hub import client as worker_client_module
    from local_ai_hub.client import HubClient

    mode_module = types.ModuleType("local_ai_hub.operational_mode")
    mode_module.load_operational_mode = lambda _state_dir: SimpleNamespace(mode="active", degraded=False)
    sys.modules[mode_module.__name__] = mode_module

    client = HubClient(config_path=config_path, auto_start=True)
    client.startup_wait = 1.0
    client.startup_poll = 0.01
    # Make the lock-age threshold shorter than the simulated cold start so this
    # exercises the live-owner behavior that previously allowed duplicate starts.
    client.start_lock_stale = 0.05
    ready_file = Path(ready_path)
    client._online = lambda _timeout=None: ready_file.exists()
    worker_client_module.find_listening_pid = lambda _port: False

    def start_service(command, **kwargs):
        assert command[-1] == "start"
        assert kwargs["stdin"] == -3
        assert kwargs["stdout"] == -3
        assert kwargs["stderr"] == -3
        (Path(launch_dir) / f"launch-{os.getpid()}").write_text("started", encoding="ascii")

        def publish_ready():
            time.sleep(0.15)
            ready_file.write_text("ready", encoding="ascii")

        threading.Thread(target=publish_ready, daemon=True).start()
        return SimpleNamespace(returncode=0)

    # Don't mutate Python's process-global subprocess module: subprocess.run()
    # itself needs its real Popen context-manager implementation.
    worker_client_module.subprocess = SimpleNamespace(
        run=start_service,
        DEVNULL=-3,
        TimeoutExpired=TimeoutError,
    )
    try:
        barrier.wait(timeout=5)
        result_queue.put(("ok", client.ensure_server(timeout=0.8)))
    except BaseException as exc:
        result_queue.put(("error", repr(exc)))


def test_first_post_starts_daemon_and_retries_same_id_and_path_hints(tmp_path, monkeypatch):
    client = _client(tmp_path)
    client.tenant = "tenant-context"
    assert client._inprocess_transport is None
    attempts: list[tuple[str, dict[str, str], dict[str, object]]] = []
    starts: list[float] = []

    def pooled_open(method, path, body, headers, timeout):
        payload = json.loads(body.decode("utf-8"))
        attempts.append((method, dict(headers), payload))
        if len(attempts) == 1:
            raise _refused()
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    monkeypatch.setattr(client, "ensure_server", lambda timeout=None: starts.append(timeout) or True)

    hint = {"path": "src", "purpose": "source", "scope": "repository"}
    payload = {"query": "needle", "root": "C:/repo", "task": "task-context"}
    result = client.post("/api/search", payload, request_id="stable-id", path_hints=[hint])

    assert result == {"success": True}
    assert len(starts) == 1 and 0 < starts[0] <= 360
    assert [headers["X-LocalAI-Request-ID"] for _, headers, _ in attempts] == ["stable-id", "stable-id"]
    assert [headers["X-LocalAI-Tenant"] for _, headers, _ in attempts] == ["tenant-context", "tenant-context"]
    assert attempts[0][2] == attempts[1][2] == {**payload, "path_hints": [hint]}


def test_unclassified_mutation_pre_send_failure_does_not_autostart_or_retry(tmp_path, monkeypatch):
    client = _client(tmp_path)
    state_dir = Path(client.config["server"]["state_dir"])
    loaded = _install_mode(monkeypatch, "active")
    spawn_attempts: list[bool] = []
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_a, **_k: spawn_attempts.append(True))
    monkeypatch.setattr(client, "_pooled_open", lambda *_a, **_k: (_ for _ in ()).throw(_refused()))

    result = client.post("/api/command", {"command": "status"}, request_id="stable-id")

    assert result["success"] is False
    assert result["outcome_unknown"] is False
    assert result["request_not_sent"] is True
    assert result["request_id"] == "stable-id"
    assert "error" in result
    assert spawn_attempts == []
    assert not state_dir.exists()
    assert not (state_dir / "hub.start.lock").exists()


def test_readiness_timeout_cleans_lock_after_service_start(tmp_path, monkeypatch):
    client = _client(tmp_path)
    state_dir = Path(client.config["server"]["state_dir"])
    loaded = _install_mode(monkeypatch, "active")
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    starts = []

    def start_service(command, **kwargs):
        starts.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(client_module.subprocess, "run", start_service)

    assert client.ensure_server(timeout=1.0) is False
    assert loaded == [state_dir]
    assert len(starts) == 1
    assert starts[0][0][-1] == "start"
    assert 0 < starts[0][1]["timeout"] <= 1.0
    assert not (state_dir / "hub.start.lock").exists()


@pytest.mark.parametrize("mode", ["gaming", "maintenance"])
def test_blocked_operational_modes_never_spawn_for_offline_request(tmp_path, monkeypatch, mode):
    client = _client(tmp_path)
    state_dir = Path(client.config["server"]["state_dir"])
    loaded = _install_mode(monkeypatch, mode)
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    starts: list[bool] = []
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_a, **_k: starts.append(True))
    monkeypatch.setattr(client, "_pooled_open", lambda *_a, **_k: (_ for _ in ()).throw(_refused()))

    result = client.post("/api/command", {"command": "status"}, request_id="stable-id")

    assert result["request_not_sent"] is True
    assert starts == []
    assert not state_dir.exists()


@pytest.mark.parametrize("mode", ["gaming", "maintenance"])
def test_blocked_operational_modes_prevent_managed_client_autostart(tmp_path, monkeypatch, mode):
    client = _client(tmp_path)
    state_dir = Path(client.config["server"]["state_dir"])
    state_dir.mkdir(parents=True)
    (state_dir / "service.managed").write_text("managed", encoding="utf-8")
    _install_mode(monkeypatch, mode)
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    starts = []
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: starts.append(True))

    assert client.ensure_server(timeout=1.0) is False
    assert starts == []


def test_managed_marker_refuses_client_supervisor_and_returns_exact_offline_error(tmp_path, monkeypatch):
    client = _client(tmp_path)
    client.tenant = "tenant-context"
    state_dir = Path(client.config["server"]["state_dir"])
    state_dir.mkdir(parents=True)
    (state_dir / "service.managed").write_text("managed", encoding="utf-8")
    (state_dir / "supervisor.pid").write_text("987654321", encoding="ascii")
    _install_mode(monkeypatch, "active")
    starts = []
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "pid_alive", lambda _pid: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)

    child = SimpleNamespace(pid=24680, poll=lambda: 0)

    def popen(*_args, **_kwargs):
        starts.append(True)
        return child

    monkeypatch.setattr(client_module.subprocess, "Popen", popen)

    attempts = []

    def pooled_open(_method, _path, body, headers, _timeout):
        attempts.append((json.loads(body.decode("utf-8")), dict(headers)))
        raise _refused()

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    result = client.post(
        "/api/search",
        {"query": "needle", "root": "C:/repo", "task": "task-context"},
        request_id="managed-offline-id",
    )

    assert result == {
        "success": False,
        "error": "request was not sent because transport failed before write",
        "request_not_sent": True,
        "outcome_unknown": False,
        "request_id": "managed-offline-id",
    }
    assert len(attempts) == 1
    assert attempts[0][0] == {"query": "needle", "root": "C:/repo", "task": "task-context"}
    assert attempts[0][1]["X-LocalAI-Tenant"] == "tenant-context"
    assert attempts[0][1]["X-LocalAI-Request-ID"] == "managed-offline-id"
    assert starts == []
    assert not (state_dir / "hub.start.lock").exists()


def test_managed_client_preserves_offline_error_contract_without_autostart(tmp_path, monkeypatch):
    client = _client(tmp_path)
    client.tenant = "tenant-context"
    state_dir = Path(client.config["server"]["state_dir"])
    state_dir.mkdir(parents=True)
    (state_dir / "service.managed").write_text("managed", encoding="utf-8")
    _install_mode(monkeypatch, "active")
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "pid_alive", lambda _pid: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    starts = []
    child = SimpleNamespace(pid=24680, poll=lambda: 0)
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: starts.append(True) or child)
    attempts = []

    def pooled_open(_method, _path, body, headers, _timeout):
        attempts.append((json.loads(body.decode("utf-8")), dict(headers)))
        if len(attempts) == 1:
            raise _refused()
        raise OSError("connection reset after write")

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    payload = {"query": "needle", "root": "C:/repo", "task": "task-context"}
    not_sent = client.post(
        "/api/search",
        payload,
        request_id="managed-not-sent-id",
    )
    unknown = client.post(
        "/api/search",
        payload,
        request_id="managed-disconnect-id",
    )

    assert not_sent == {
        "success": False,
        "error": "request was not sent because transport failed before write",
        "request_not_sent": True,
        "outcome_unknown": False,
        "request_id": "managed-not-sent-id",
    }
    assert unknown == {
        "success": False,
        "error": "request outcome is unknown after a transport failure",
        "outcome_unknown": True,
        "request_id": "managed-disconnect-id",
    }
    assert len(attempts) == 2
    assert attempts[0][0] == attempts[1][0] == payload
    assert [headers["X-LocalAI-Tenant"] for _, headers in attempts] == ["tenant-context", "tenant-context"]
    assert [headers["X-LocalAI-Request-ID"] for _, headers in attempts] == [
        "managed-not-sent-id",
        "managed-disconnect-id",
    ]
    assert starts == []
    assert not (state_dir / "hub.start.lock").exists()
    assert not (state_dir / "hub.start.guard").exists()


def test_managed_marker_published_during_lock_acquisition_blocks_client_spawn(tmp_path, monkeypatch):
    client = _client(tmp_path)
    state_dir = Path(client.config["server"]["state_dir"])
    state_dir.mkdir(parents=True)
    _install_mode(monkeypatch, "active")
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "pid_alive", lambda _pid: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    starts = []
    monkeypatch.setattr(
        client_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: starts.append(True),
    )
    original_guard = client_module._try_start_lock_guard
    published = []

    def publish_managed_before_guard(path):
        if not published:
            (state_dir / "service.managed").write_text("managed", encoding="utf-8")
            published.append(True)
        return original_guard(path)

    monkeypatch.setattr(client_module, "_try_start_lock_guard", publish_managed_before_guard)

    assert client.ensure_server(timeout=1.0) is False
    assert published == [True]
    assert starts == []
    assert not (state_dir / "hub.start.lock").exists()
    guard_fd = client_module._try_start_lock_guard(state_dir / "hub.start.guard")
    assert guard_fd is not None
    client_module._release_start_lock_guard(guard_fd)


@pytest.mark.parametrize("blocker", ["supervisor_pid", "supervisor_lock", "port_listener"])
def test_managed_marker_never_spawns_alongside_live_supervisor_or_listener(
    tmp_path, monkeypatch, blocker
):
    client = _client(tmp_path)
    state_dir = Path(client.config["server"]["state_dir"])
    state_dir.mkdir(parents=True)
    (state_dir / "service.managed").write_text("managed", encoding="utf-8")
    if blocker == "supervisor_pid":
        (state_dir / "supervisor.pid").write_text("321", encoding="ascii")
    elif blocker == "supervisor_lock":
        (state_dir / "supervisor.lock").write_text("321", encoding="ascii")
    _install_mode(monkeypatch, "active")
    starts = []
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "pid_alive", lambda _pid: blocker != "port_listener")
    monkeypatch.setattr(
        client_module,
        "find_listening_pid",
        lambda _port: 6543 if blocker == "port_listener" else False,
    )
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: starts.append(True))

    assert client.ensure_server(timeout=1.0) is False
    assert starts == []


def test_disabled_marker_blocks_managed_client_autostart(tmp_path, monkeypatch):
    client = _client(tmp_path)
    state_dir = Path(client.config["server"]["state_dir"])
    state_dir.mkdir(parents=True)
    (state_dir / "service.managed").write_text("managed", encoding="utf-8")
    (state_dir / "service.disabled").write_text("disabled", encoding="utf-8")
    _install_mode(monkeypatch, "active")
    starts = []
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: starts.append(True))

    assert client.ensure_server(timeout=1.0) is False
    assert starts == []


@pytest.mark.parametrize("blocker", ["supervisor_pid", "supervisor_lock", "port_listener"])
def test_orphaned_managed_recovery_preserves_live_supervisor_and_port_singletons(
    tmp_path, monkeypatch, blocker
):
    client = _client(tmp_path)
    state_dir = Path(client.config["server"]["state_dir"])
    state_dir.mkdir(parents=True)
    (state_dir / "service.managed").write_text("managed", encoding="utf-8")
    if blocker == "supervisor_pid":
        (state_dir / "supervisor.pid").write_text("321", encoding="ascii")
    elif blocker == "supervisor_lock":
        (state_dir / "supervisor.lock").write_text("321", encoding="ascii")
    _install_mode(monkeypatch, "active")
    starts = []
    monkeypatch.setattr(client, "_online", lambda *_args: False)
    monkeypatch.setattr(client_module, "pid_alive", lambda _pid: blocker != "port_listener")
    monkeypatch.setattr(
        client_module,
        "find_listening_pid",
        lambda _port: 6543 if blocker == "port_listener" else False,
    )
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: starts.append(True))

    assert client.ensure_server(timeout=1.0) is False
    assert starts == []


def test_30_concurrent_offline_clients_share_one_startup(tmp_path, monkeypatch):
    seed = _client(tmp_path)
    config_path = str(seed.config["_config_path"])
    _install_mode(monkeypatch, "active")
    lock = threading.Lock()
    running = False
    starts: list[list[str]] = []
    attempts: dict[str, int] = {}
    all_first_attempts = threading.Barrier(30)
    clients = [seed] + [HubClient(config_path=config_path, auto_start=True) for _ in range(29)]

    def online(_client, *_args):
        with lock:
            return running

    def start_service(command, **kwargs):
        nonlocal running
        with lock:
            starts.append(command)
            running = True
        assert command[-1] == "start"
        assert kwargs["stdin"] is client_module.subprocess.DEVNULL
        assert kwargs["stdout"] is client_module.subprocess.DEVNULL
        assert kwargs["stderr"] is client_module.subprocess.DEVNULL
        assert 0 < kwargs["timeout"] <= seed.startup_wait
        return SimpleNamespace(returncode=0)

    def pooled_open(_method, _path, _body, headers, _timeout):
        request_id = headers["X-LocalAI-Request-ID"]
        with lock:
            attempts[request_id] = attempts.get(request_id, 0) + 1
            attempt = attempts[request_id]
        if attempt == 1:
            all_first_attempts.wait(timeout=5)
            raise _refused()
        return b'{"success":true}'

    monkeypatch.setattr(HubClient, "_online", online)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    monkeypatch.setattr(client_module.subprocess, "run", start_service)
    for client in clients:
        client._pooled_open = pooled_open

    with ThreadPoolExecutor(max_workers=30) as pool:
        futures = [
            pool.submit(
                client.post,
                "/api/search",
                {"root": str(tmp_path), "query": "needle"},
                request_id=f"request-{i}",
            )
            for i, client in enumerate(clients)
        ]
        results = [future.result(timeout=8) for future in futures]

    assert results == [{"success": True}] * 30
    assert len(starts) == 1
    assert starts[0][-1] == "start"
    assert attempts == {f"request-{i}": 2 for i in range(30)}




def test_cross_process_offline_clients_share_one_unmanaged_autostart(tmp_path):
    client = _client(tmp_path)
    state_dir = Path(client.config["server"]["state_dir"])
    launch_dir = tmp_path / "launches"
    launch_dir.mkdir()
    ready_path = tmp_path / "ready"
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    result_queue = context.Queue()
    workers = [
        context.Process(
            target=_cross_process_start_worker,
            args=(str(client.config["_config_path"]), str(ready_path), str(launch_dir), barrier, result_queue),
        )
        for _ in range(2)
    ]

    try:
        for worker in workers:
            worker.start()
        results = [result_queue.get(timeout=12) for _ in workers]
        for worker in workers:
            worker.join(timeout=2)

        assert results == [("ok", True), ("ok", True)]
        assert all(worker.exitcode == 0 for worker in workers)
        assert len(list(launch_dir.glob("launch-*"))) == 1
        assert ready_path.read_text(encoding="ascii") == "ready"
        assert not (state_dir / "hub.start.lock").exists()
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=2)
        result_queue.close()


def test_recent_empty_start_lock_is_treated_as_in_progress(tmp_path):
    lock_path = tmp_path / "hub.start.lock"
    lock_path.touch()

    assert client_module._live_start_lock(lock_path, stale_seconds=20)

    old_time = time.time() - 21
    os.utime(lock_path, (old_time, old_time))
    assert not client_module._live_start_lock(lock_path, stale_seconds=20)


def test_recent_partially_published_start_lock_sidecar_stays_live(tmp_path) -> None:
    lock_path = tmp_path / "hub.start.lock"
    lock_path.write_text("123 1 nonce", encoding="ascii")
    sidecar = lock_path.with_name(f"{lock_path.name}.nonce.pid")
    sidecar.write_text("", encoding="ascii")

    assert client_module._live_start_lock(lock_path, stale_seconds=1) is True


def test_stale_incomplete_sidecar_does_not_pin_dead_start_lock(tmp_path, monkeypatch) -> None:
    lock_path = tmp_path / "hub.start.lock"
    lock_path.write_text("123 1 nonce test_start_id 7", encoding="ascii")
    sidecar = lock_path.with_name(f"{lock_path.name}.nonce.pid")
    sidecar.write_text("", encoding="ascii")
    os.utime(lock_path, (0, 0))
    monkeypatch.setattr(client_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(client_module, "pid_alive", lambda _pid: False)

    assert client_module._live_start_lock(lock_path, stale_seconds=1) is False


def test_start_lock_rejects_reused_pid_with_different_creation_identity(tmp_path, monkeypatch) -> None:
    lock_path = tmp_path / "hub.start.lock"
    lock_path.write_text("123 1 nonce test_start_id 7", encoding="ascii")
    os.utime(lock_path, (0, 0))
    monkeypatch.setattr(
        client_module,
        "process_identity",
        lambda _pid: {
            "pid": 123,
            "creation_identity_type": "test_start_id",
            "creation_identity": 8,
        },
    )
    monkeypatch.setattr(client_module, "pid_alive", lambda _pid: True)

    assert client_module._live_start_lock(lock_path, stale_seconds=20) is False


def test_aged_start_lock_is_kept_while_launcher_identity_matches(tmp_path, monkeypatch) -> None:
    lock_path = tmp_path / "hub.start.lock"
    lock_path.write_text("123 1 nonce test_start_id 7", encoding="ascii")
    os.utime(lock_path, (0, 0))
    monkeypatch.setattr(
        client_module,
        "process_identity",
        lambda pid: {
            "pid": pid,
            "creation_identity_type": "test_start_id",
            "creation_identity": 7,
        }
        if pid == 123
        else None,
    )

    assert client_module._live_start_lock(lock_path, stale_seconds=1) is True


def test_dead_daemon_sidecar_overrides_live_launcher_identity(tmp_path, monkeypatch) -> None:
    lock_path = tmp_path / "hub.start.lock"
    lock_path.write_text("123 1 nonce test_start_id 7", encoding="ascii")
    sidecar = lock_path.with_name(f"{lock_path.name}.nonce.pid")
    sidecar.write_text("456 test_start_id 8", encoding="ascii")
    os.utime(lock_path, (0, 0))
    monkeypatch.setattr(
        client_module,
        "process_identity",
        lambda pid: {
            "pid": 123,
            "creation_identity_type": "test_start_id",
            "creation_identity": 7,
        }
        if pid == 123
        else None,
    )

    assert client_module._live_start_lock(lock_path, stale_seconds=1) is False


def test_service_start_timeout_releases_start_lock(tmp_path, monkeypatch) -> None:
    from subprocess import TimeoutExpired

    state_dir = tmp_path / "state"
    config = tmp_path / "service-start-timeout.toml"
    config.write_text(
        "[server]\nbind='127.0.0.1'\nport=39131\nstate_dir='"
        + state_dir.as_posix()
        + "'\n[client]\nstartup_wait_seconds=1\nstartup_poll_seconds=0.005\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config))
    client.startup_wait = 0.05
    _install_mode(monkeypatch, "active")
    monkeypatch.setattr(client, "_online", lambda _timeout=None: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: False)
    starts = []

    def timeout_start(command, **kwargs):
        starts.append((command, kwargs))
        raise TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(client_module.subprocess, "run", timeout_start)

    assert client.ensure_server(timeout=0.05) is False
    assert len(starts) == 1
    assert starts[0][0][-1] == "start"
    assert starts[0][1]["timeout"] >= 0.1
    assert not (state_dir / "hub.start.lock").exists()


def test_autostart_launches_real_hub_child_and_returns_http_search_result(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "needle.py").write_text(
        'def find_marker():\n    return "T04_REAL_CHILD_MARKER"\n',
        encoding="utf-8",
    )
    state_dir = tmp_path / "state"
    config_path = tmp_path / "real-child.toml"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {port}\nstate_dir = "{state_dir.as_posix()}"\n'
        "[client]\nstartup_wait_seconds = 15\nstartup_poll_seconds = 0.05\nhealth_timeout_seconds = 0.25\n"
        "[ollama]\nenabled = false\n"
        "[smart_ollama]\nenabled = false\n"
        "[llama_cpp]\nmode = \"off\"\n"
        "[code_intelligence]\nenabled = false\nserena_enabled = false\npreprocess_serena = false\n"
        "[preprocessing]\nenabled = false\n",
        encoding="utf-8",
    )
    client = HubClient(tenant="t04-real-child", config_path=str(config_path), auto_start=True)
    sent_request_ids = []
    real_open = client._open

    def observe_open(method, path, body, headers, timeout, **kwargs):
        sent_request_ids.append(headers["X-LocalAI-Request-ID"])
        return real_open(method, path, body, headers, timeout, **kwargs)

    client._open = observe_open
    assert client.config["llama_cpp"]["mode"] == "off"
    assert client.config["ollama"]["enabled"] is False
    assert client.config["smart_ollama"]["enabled"] is False
    assert client.config["code_intelligence"]["enabled"] is False
    assert client.config["code_intelligence"]["serena_enabled"] is False
    assert client.config["code_intelligence"]["preprocess_serena"] is False
    assert client.config["preprocessing"]["enabled"] is False
    with client_module._DETACHED_CHILDREN_LOCK:
        existing_child_ids = {id(child) for child in client_module._DETACHED_CHILDREN}

    try:
        result = client.post(
            "/api/search",
            {"root": str(repo), "query": "T04_REAL_CHILD_MARKER", "top_k": 3},
            request_id="t04-real-child-search",
            timeout=30,
        )
        assert len(sent_request_ids) >= 2
        assert set(sent_request_ids) == {"t04-real-child-search"}
        assert result["success"] is True
        assert any(
            hit.get("path") == "needle.py" and "T04_REAL_CHILD_MARKER" in hit.get("text", "")
            for hit in result.get("results", [])
        )
        with client_module._DETACHED_CHILDREN_LOCK:
            started_children = [
                child
                for child in client_module._DETACHED_CHILDREN
                if id(child) not in existing_child_ids
            ]
        assert len(started_children) == 1
        child = started_children[0]
        assert isinstance(child, client_module.subprocess.Popen)
        assert child.poll() is None
        assert (state_dir / "hub.pid").read_text(encoding="utf-8").strip() == str(child.pid)
        assert not (state_dir / "hub.start.lock").exists()
    finally:
        client._drop_connection()
        with client_module._DETACHED_CHILDREN_LOCK:
            started_children = [
                child
                for child in client_module._DETACHED_CHILDREN
                if id(child) not in existing_child_ids
            ]
        for child in started_children:
            client_module._stop_owned_child(child)
        assert all(child.poll() is not None for child in started_children), (
            "test-owned Hub child remained alive after exact-handle cleanup"
        )
        with client_module._DETACHED_CHILDREN_LOCK:
            client_module._DETACHED_CHILDREN[:] = [
                child
                for child in client_module._DETACHED_CHILDREN
                if id(child) in existing_child_ids or child.poll() is None
            ]
