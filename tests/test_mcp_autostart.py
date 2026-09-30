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
