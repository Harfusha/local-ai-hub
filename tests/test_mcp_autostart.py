from __future__ import annotations

from local_ai_hub import mcp_server


def test_mcp_main_starts_stdio_without_eager_hub_autostart(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(mcp_server.CLIENT, "ensure_server", lambda **_kwargs: calls.append("start"))
    monkeypatch.setattr(mcp_server.mcp, "run", lambda: calls.append("mcp"))

    mcp_server.main()

    assert calls == ["mcp"]
