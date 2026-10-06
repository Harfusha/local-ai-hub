from __future__ import annotations

from urllib.error import URLError


def test_mcp_main_enters_stdio_without_eager_hub_autostart(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    calls: list[str] = []
    monkeypatch.setattr(
        mcp_server.CLIENT,
        "ensure_server",
        lambda **_kwargs: calls.append("start"),
    )
    monkeypatch.setattr(mcp_server.mcp, "run", lambda: calls.append("stdio"))

    mcp_server.main()

    assert calls == ["stdio"]


def test_mcp_client_keeps_hub_owned_auto_start_enabled() -> None:
    from local_ai_hub import mcp_server

    assert mcp_server.CLIENT.auto_start is True


def test_mcp_client_bounds_auto_start_after_daemon_connection_refusal(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    adapter = mcp_server.CLIENT
    client = adapter._client
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

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    monkeypatch.setattr(client, "ensure_server", ensure_server)

    result = adapter.get("/api/live/status", timeout=0.8)

    assert result == {"success": True, "hub_online": True}
    assert len(opened) == 2
    assert len(startup_budgets) == 1
    assert 0 < startup_budgets[0] <= 0.8
    assert opened[1] <= 0.8


def test_mcp_client_bounds_daemon_off_start_failure_without_second_request(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    adapter = mcp_server.CLIENT
    client = adapter._client
    opened: list[float] = []
    startup_budgets: list[float] = []

    def pooled_open(_method, _path, _body, _headers, timeout):
        opened.append(float(timeout))
        raise URLError("daemon is not listening")

    def ensure_server(*, timeout=None):
        startup_budgets.append(float(timeout))
        return False

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    monkeypatch.setattr(client, "ensure_server", ensure_server)

    result = adapter.get("/api/live/status", timeout=0.35)

    assert result["success"] is False
    assert result["outcome_unknown"] is True
    assert "retried" not in result
    assert len(opened) == 1
    assert opened[0] <= 0.35
    assert len(startup_budgets) == 1
    assert 0 < startup_budgets[0] <= 0.35


def test_daemon_off_concurrent_mcp_clients_share_cold_start(tmp_path, monkeypatch) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from urllib.error import URLError

    from local_ai_hub import client as client_module
    from local_ai_hub.client import HubClient

    state_dir = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=39123\nstate_dir='" + state_dir.as_posix() + "'\n"
        "[client]\nmax_request_timeout_seconds=5\n",
        encoding="utf-8",
    )
    clients = [HubClient(config_path=str(config)), HubClient(config_path=str(config))]
    for client in clients:
        client.startup_wait = 0.7
    ready = threading.Event()
    cold_requests = threading.Barrier(2)
    opened: list[str] = []
    startup_health_budgets: list[float] = []
    launched: list[object] = []

    class Child:
        pid = 43821

        def poll(self):
            return None

    child = Child()

    def pooled_open(_method, path, _body, _headers, _timeout):
        if not ready.is_set():
            opened.append(path)
            cold_requests.wait(timeout=3)
            raise URLError("daemon is not listening")
        return b'{"success":true,"hub_online":true}'

    def launch(*_args, **_kwargs):
        launched.append(child)
        ready.set()
        return child

    for client in clients:
        monkeypatch.setattr(client, "_pooled_open", pooled_open)
        monkeypatch.setattr(
            client,
            "_online",
            lambda timeout=None: startup_health_budgets.append(float(timeout or 0)) or ready.is_set(),
        )
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(client_module.subprocess, "Popen", launch)
    monkeypatch.setattr(client_module, "_retain_detached_child", lambda _process: None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda pair: pair[0].get(pair[1], timeout=0.6),
                zip(clients, ("/api/live/status?a", "/api/live/status?b")),
            )
        )

    assert len(opened) == 2
    assert results == [
        {"success": True, "hub_online": True},
        {"success": True, "hub_online": True},
    ]
    assert launched == [child]
    assert startup_health_budgets
    assert all(0 <= budget <= 0.6 for budget in startup_health_budgets)
    assert not (state_dir / "hub.start.lock").exists()


def test_daemon_off_start_timeout_reaps_only_owned_child(tmp_path, monkeypatch) -> None:
    from local_ai_hub import client as client_module
    from local_ai_hub.client import HubClient

    state_dir = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=39124\nstate_dir='" + state_dir.as_posix() + "'\n"
        "[client]\nmax_request_timeout_seconds=5\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config))
    client.startup_wait = 0.06
    client.startup_poll = 0.005
    terminated: list[int] = []

    class Child:
        pid = 43822
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

    assert client.ensure_server(timeout=0.06) is False
    assert terminated == [child.pid]
    assert child.returncode is not None
    assert not (state_dir / "hub.start.lock").exists()
