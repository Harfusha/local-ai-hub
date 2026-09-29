from __future__ import annotations

from urllib.error import URLError


def test_mcp_client_keeps_hub_owned_auto_start_enabled() -> None:
    from local_ai_hub import mcp_server

    assert mcp_server.CLIENT.auto_start is True


def test_mcp_client_bounds_auto_start_after_daemon_connection_refusal(monkeypatch) -> None:
    from local_ai_hub import mcp_server

    client = mcp_server.CLIENT
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

    result = client.get("/api/live/status", timeout=0.8)

    assert result == {"success": True, "hub_online": True}
    assert len(opened) == 2
    assert len(startup_budgets) == 1
    assert 0 < startup_budgets[0] <= 0.8
    assert opened[1] <= 0.8
