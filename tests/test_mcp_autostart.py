from __future__ import annotations

import pytest

from local_ai_hub import mcp_server


def test_mcp_main_uses_hubclient_autostart_before_serving_tools(monkeypatch, tmp_path) -> None:
    from local_ai_hub import client as client_module
    from local_ai_hub.client import HubClient

    state_dir = (tmp_path / "state").resolve()
    config = tmp_path / "mcp-autostart.toml"
    config.write_text(
        "[server]\nbind='127.0.0.1'\nport=39126\nstate_dir='"
        + state_dir.as_posix()
        + "'\n[client]\nstartup_wait_seconds=1\nstartup_poll_seconds=0.05\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=True)
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    events: list[str] = []

    class FakeProcess:
        @staticmethod
        def poll():
            return None

    spawned: list[FakeProcess] = []

    def popen(*_args, **_kwargs):
        events.append("spawn")
        process = FakeProcess()
        spawned.append(process)
        return process

    monkeypatch.setattr(client, "_online", lambda _timeout=None: bool(spawned))
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(client_module.subprocess, "Popen", popen)
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)
    monkeypatch.setattr(mcp_server.mcp, "run", lambda: events.append("mcp"))

    mcp_server.main()

    assert events == ["spawn", "mcp"]
    assert not (state_dir / "hub.start.lock").exists()


def test_mcp_main_does_not_serve_tools_when_hub_start_fails(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(mcp_server.CLIENT, "auto_start", True)
    monkeypatch.setattr(mcp_server.CLIENT, "ensure_server", lambda **_kwargs: False)
    monkeypatch.setattr(mcp_server.mcp, "run", lambda: calls.append("mcp"))

    with pytest.raises(SystemExit, match="Hub did not become ready"):
        mcp_server.main()

    assert calls == []


def test_client_startup_wait_is_capped_and_non_finite_budget_uses_default(tmp_path) -> None:
    from local_ai_hub.client import HubClient, bounded_startup_wait

    config = tmp_path / "mcp-autostart-invalid-timeout.toml"
    config.write_text(
        "[server]\nbind='127.0.0.1'\nport=39127\nstate_dir='"
        + (tmp_path / "state").as_posix()
        + "'\n[client]\nstartup_wait_seconds=300\n",
        encoding="utf-8",
    )

    client = HubClient(config_path=str(config), auto_start=True)

    assert client.startup_wait == 60.0
    assert bounded_startup_wait(float("inf")) == 15.0


def test_mcp_main_clamps_manually_unbounded_startup_budget(monkeypatch) -> None:
    budgets: list[float] = []
    monkeypatch.setattr(mcp_server.CLIENT, "auto_start", True)
    monkeypatch.setattr(mcp_server.CLIENT, "startup_wait", float("inf"))
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "ensure_server",
        lambda *, timeout=None: budgets.append(float(timeout)) or True,
    )
    monkeypatch.setattr(mcp_server.mcp, "run", lambda: None)

    mcp_server.main()

    assert budgets == [15.0]


def test_concurrent_daemon_off_clients_share_one_startup_child(tmp_path, monkeypatch) -> None:
    import os
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from urllib.error import URLError

    from local_ai_hub import client as client_module
    from local_ai_hub.client import HubClient

    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    stale_lock = state_dir / "hub.start.lock"
    stale_lock.write_text("0 1 stale", encoding="ascii")
    os.utime(stale_lock, (0, 0))
    config = tmp_path / "mcp-concurrent-autostart.toml"
    config.write_text(
        "[server]\nbind='127.0.0.1'\nport=39128\nstate_dir='"
        + state_dir.as_posix()
        + "'\n[client]\nstartup_wait_seconds=1\nstartup_poll_seconds=0.01\n",
        encoding="utf-8",
    )
    clients = [HubClient(config_path=str(config)), HubClient(config_path=str(config))]
    ready = threading.Event()
    initial_requests = threading.Barrier(2)
    launched: list[object] = []

    class Child:
        pid = 43831

        @staticmethod
        def poll():
            return None

    child = Child()

    def pooled_open(_method, _path, _body, _headers, _timeout):
        if not ready.is_set():
            initial_requests.wait(timeout=3)
            raise URLError("daemon is not listening")
        return b'{"success":true,"hub_online":true}'

    def launch(*_args, **_kwargs):
        launched.append(child)
        ready.set()
        return child

    for client in clients:
        monkeypatch.setattr(client, "_pooled_open", pooled_open)
        monkeypatch.setattr(client, "_online", lambda _timeout=None: ready.is_set())
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(client_module.subprocess, "Popen", launch)
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda pair: pair[0].get(pair[1], timeout=0.8),
                zip(clients, ("/api/live/status?cold=1", "/api/live/status?cold=2")),
            )
        )

    assert results == [
        {"success": True, "hub_online": True},
        {"success": True, "hub_online": True},
    ]
    assert launched == [child]
    assert not (state_dir / "hub.start.lock").exists()


def test_startup_timeout_reaps_only_created_child_and_releases_lock(tmp_path, monkeypatch) -> None:
    from local_ai_hub import client as client_module
    from local_ai_hub.client import HubClient

    state_dir = tmp_path / "state"
    config = tmp_path / "mcp-timeout-autostart.toml"
    config.write_text(
        "[server]\nbind='127.0.0.1'\nport=39129\nstate_dir='"
        + state_dir.as_posix()
        + "'\n[client]\nstartup_wait_seconds=1\nstartup_poll_seconds=0.005\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config))
    client.startup_wait = 0.05
    terminated: list[int] = []

    class Child:
        pid = 43832
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = -15
            return self.returncode

    child = Child()
    monkeypatch.setattr(client, "_online", lambda _timeout=None: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: child)
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)
    monkeypatch.setattr(
        client_module,
        "terminate_tree",
        lambda pid, **_kwargs: terminated.append(pid) or True,
    )

    assert client.ensure_server(timeout=0.05) is False
    assert terminated == [child.pid]
    assert child.returncode is not None
    assert not (state_dir / "hub.start.lock").exists()


def test_failed_start_marks_lock_stale_when_windows_blocks_cleanup(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from local_ai_hub import client as client_module
    from local_ai_hub.client import HubClient

    state_dir = tmp_path / "state"
    config = tmp_path / "mcp-blocked-cleanup.toml"
    config.write_text(
        "[server]\nbind='127.0.0.1'\nport=39130\nstate_dir='"
        + state_dir.as_posix()
        + "'\n[client]\nstartup_wait_seconds=1\nstartup_poll_seconds=0.005\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config))
    child = type("Child", (), {"pid": 43833, "returncode": None, "poll": lambda self: self.returncode})()
    child.wait = lambda timeout=None: setattr(child, "returncode", -15) or child.returncode
    lock_path = state_dir / "hub.start.lock"
    original_unlink = Path.unlink

    def deny_lock_cleanup(path: Path, *, missing_ok: bool = False) -> None:
        if path == lock_path:
            raise PermissionError("simulated Windows sharing violation")
        original_unlink(path, missing_ok=missing_ok)

    client.startup_wait = 0.05
    monkeypatch.setattr(client, "_online", lambda _timeout=None: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: child)
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)
    monkeypatch.setattr(client_module, "terminate_tree", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(Path, "unlink", deny_lock_cleanup)

    assert client.ensure_server(timeout=0.05) is False
    assert lock_path.exists()
    lock_parts = lock_path.read_text(encoding="ascii").split()
    pid_path = lock_path.with_name(f"{lock_path.name}.{lock_parts[2]}.pid")
    assert pid_path.read_text(encoding="ascii") == "0"
    assert client_module._live_start_lock(lock_path, client.start_lock_stale) is False


def test_partially_published_start_lock_sidecar_stays_live(tmp_path) -> None:
    import os

    from local_ai_hub import client as client_module

    lock_path = tmp_path / "hub.start.lock"
    lock_path.write_text("123 1 nonce", encoding="ascii")
    sidecar = lock_path.with_name(f"{lock_path.name}.nonce.pid")
    sidecar.write_text("", encoding="ascii")
    os.utime(lock_path, (0, 0))

    assert client_module._live_start_lock(lock_path, stale_seconds=1) is True


def test_aged_start_lock_is_kept_while_launcher_identity_matches(tmp_path, monkeypatch) -> None:
    import os

    from local_ai_hub import client as client_module

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
    import os

    from local_ai_hub import client as client_module

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


def test_timeout_keeps_lock_while_unreaped_child_is_alive(tmp_path, monkeypatch) -> None:
    import os
    from subprocess import TimeoutExpired

    from local_ai_hub import client as client_module
    from local_ai_hub.client import HubClient

    state_dir = tmp_path / "state"
    config = tmp_path / "mcp-unreaped-child.toml"
    config.write_text(
        "[server]\nbind='127.0.0.1'\nport=39131\nstate_dir='"
        + state_dir.as_posix()
        + "'\n[client]\nstartup_wait_seconds=1\nstartup_poll_seconds=0.005\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config))
    client.startup_wait = 0.05

    class Child:
        pid = 43834

        @staticmethod
        def poll():
            return None

        @staticmethod
        def wait(timeout=None):
            raise TimeoutExpired("hub", timeout)

        @staticmethod
        def kill():
            raise OSError("simulated child that cannot be reaped")

    child = Child()
    monkeypatch.setattr(client, "_online", lambda _timeout=None: False)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(client_module, "pid_alive", lambda pid: pid == child.pid)
    monkeypatch.setattr(
        client_module,
        "process_identity",
        lambda pid: {
            "pid": pid,
            "creation_identity_type": "test_start_id",
            "creation_identity": 17,
        }
        if pid == child.pid
        else None,
    )
    monkeypatch.setattr(client_module.subprocess, "Popen", lambda *_args, **_kwargs: child)
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)
    monkeypatch.setattr(client_module, "terminate_tree", lambda *_args, **_kwargs: True)

    assert client.ensure_server(timeout=0.05) is False
    lock_path = state_dir / "hub.start.lock"
    assert lock_path.exists()
    os.utime(lock_path, (0, 0))
    assert client_module._live_start_lock(lock_path, client.start_lock_stale) is True
    monkeypatch.setattr(
        client_module,
        "process_identity",
        lambda pid: {
            "pid": pid,
            "creation_identity_type": "test_start_id",
            "creation_identity": 18,
        }
        if pid == child.pid
        else None,
    )
    assert client_module._live_start_lock(lock_path, client.start_lock_stale) is False


def test_http_call_recovers_after_daemon_refusal_with_remaining_budget(monkeypatch) -> None:
    from urllib.error import URLError

    opened: list[float] = []
    startup_budgets: list[float] = []

    def pooled_open(_method, _path, _body, _headers, timeout):
        opened.append(float(timeout))
        if len(opened) == 1:
            raise URLError("daemon is not listening")
        return b'{"success":true,"hub_online":true}'

    def ensure_server(*, timeout=None):
        startup_budgets.append(float(timeout))
        return True

    monkeypatch.setattr(mcp_server.CLIENT, "_pooled_open", pooled_open)
    monkeypatch.setattr(mcp_server.CLIENT, "ensure_server", ensure_server)

    result = mcp_server.CLIENT.get("/api/live/status", timeout=0.8)

    assert result == {"success": True, "hub_online": True}
    assert len(opened) == 2
    assert len(startup_budgets) == 1
    assert 0 < startup_budgets[0] <= 0.8
    assert opened[1] <= 0.8


def test_http_call_returns_bounded_failure_when_daemon_start_fails(monkeypatch) -> None:
    from urllib.error import URLError

    opened: list[float] = []
    startup_budgets: list[float] = []

    def pooled_open(_method, _path, _body, _headers, timeout):
        opened.append(float(timeout))
        raise URLError("daemon is not listening")

    def ensure_server(*, timeout=None):
        startup_budgets.append(float(timeout))
        return False

    monkeypatch.setattr(mcp_server.CLIENT, "_pooled_open", pooled_open)
    monkeypatch.setattr(mcp_server.CLIENT, "ensure_server", ensure_server)

    result = mcp_server.CLIENT.get("/api/live/status", timeout=0.35)

    assert result["success"] is False
    assert result["outcome_unknown"] is True
    assert "retried" not in result
    assert len(opened) == 1
    assert opened[0] <= 0.35
    assert len(startup_budgets) == 1
    assert 0 < startup_budgets[0] <= 0.35
