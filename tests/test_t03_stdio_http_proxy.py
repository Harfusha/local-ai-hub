from __future__ import annotations

import asyncio

from local_ai_hub import mcp_server as local_ai_mcp


def test_stdio_initialize_tools_list_and_call_use_root_http_proxy(monkeypatch) -> None:
    from mcp.shared.memory import create_connected_server_and_client_session

    http_calls = []

    class HttpHubClientProbe:
        auto_start = True
        startup_wait = 2.0

        def get(self, path, **kwargs):
            http_calls.append((path, dict(kwargs)))
            return {"hub_online": True, "scheduler": {}, "observability": {}}

    monkeypatch.setattr(local_ai_mcp, "CLIENT", HttpHubClientProbe())
    monkeypatch.setattr(
        local_ai_mcp,
        "load_operational_mode",
        lambda *_args, **_kwargs: local_ai_mcp.OperationalModeSnapshot("active", 0, None),
    )
    monkeypatch.setattr(local_ai_mcp, "operational_mode_gate_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(local_ai_mcp._ACCOUNTING_REPORTER, "record", lambda *_args: None)

    async def protocol_round_trip():
        async with create_connected_server_and_client_session(local_ai_mcp.mcp) as session:
            listed = await session.list_tools()
            calls_after_list = list(http_calls)
            called = await session.call_tool("local_ai_status", {"detail": "brief"})
            return listed, called, calls_after_list

    listed, called, calls_after_list = asyncio.run(protocol_round_trip())
    tool_names = {tool.name for tool in listed.tools}
    assert "local_ai_status" in tool_names
    assert calls_after_list == []
    assert called.content
    assert http_calls == [("/api/live/status?light=1", {})]
