from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from contextlib import closing
from pathlib import Path
import pytest

from local_ai_hub.debug_traces import DebugTraceStore
from local_ai_hub.client import HubClient
from urllib.parse import parse_qs, urlsplit


@pytest.fixture
def isolated_mcp_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[server]\n"
        'bind = "127.0.0.1"\n'
        "port = 49173\n"
        "auto_start_ollama = false\n"
        f'state_dir = "{state_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCAL_AI_CONFIG", str(config_path))
    module_name = "local_ai_hub._mcp_server_debug_trace_search"
    source_path = Path(__file__).resolve().parents[2] / "src" / "local_ai_hub" / "mcp_server.py"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    assert spec is not None and spec.loader is not None
    server = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, server)
    spec.loader.exec_module(server)
    monkeypatch.setattr(server.FEATURES, "status", True)
    monkeypatch.setattr(server._ACCOUNTING_REPORTER, "record", lambda event: None)
    monkeypatch.setattr(server.CONTEXT_LEDGER, "record", lambda **kwargs: None)
    return server


def test_trace_list_filters_by_minimum_duration_and_action(tmp_path: Path) -> None:
    store = DebugTraceStore({
        "server": {"state_dir": str(tmp_path)},
        "observability": {"debug_traces": {"enabled": True}},
    })
    slow_id = store.start(kind="mcp", tenant="test", action="search")
    fast_id = store.start(kind="mcp", tenant="test", action="index")
    with closing(store._connect()) as con:
        con.execute(
            "UPDATE traces SET created_at=?, updated_at=?, finished_at=? WHERE trace_id=?",
            (100.0, 103.0, 103.0, slow_id),
        )
        con.execute(
            "UPDATE traces SET created_at=?, updated_at=?, finished_at=? WHERE trace_id=?",
            (200.0, 200.25, 200.25, fast_id),
        )
        con.commit()

    result = store.list(min_duration_ms=1000, action="search")

    assert result["success"] is True
    assert result["total"] == 1
    assert result["items"][0]["trace_id"] == slow_id
    assert result["items"][0]["duration_ms"] == 3000


def test_client_trace_status_routes_filters_without_health_query(monkeypatch):
    client = object.__new__(HubClient)
    calls = []
    monkeypatch.setattr(client, "get", lambda path: calls.append(path) or {"success": True})
    assert client.status("traces", min_duration_ms=1000, trace_action="search & inspect")["success"]
    assert len(calls) == 1
    parsed = urlsplit(calls[0])
    assert parsed.path == "/api/debug-traces"
    assert parse_qs(parsed.query) == {"min_duration_ms": ["1000"], "action": ["search & inspect"], "limit": ["20"]}


@pytest.mark.parametrize("filters", [
    {"min_duration_ms": True}, {"min_duration_ms": -1}, {"min_duration_ms": 86_400_001},
    {"min_duration_ms": "1000"}, {"trace_action": "x" * 65}, {"trace_action": None},
])
def test_client_trace_status_rejects_invalid_filters_before_transport(monkeypatch, filters):
    client = object.__new__(HubClient)
    monkeypatch.setattr(client, "get", lambda path: pytest.fail("invalid filter reached transport"))
    result = client.status("traces", **filters)
    assert not result["success"] and result["status_code"] == 400
    assert result["terminal"] and not result["retryable"]


def test_local_ai_status_traces_queries_filtered_debug_traces(isolated_mcp_server, monkeypatch) -> None:
    server = isolated_mcp_server
    calls: list[str] = []

    def get(path: str, **kwargs):
        calls.append(path)
        return {
            "success": True,
            "items": [{"trace_id": "slow-search", "action": "search", "duration_ms": 1500}],
            "total": 1,
            "limit": 20,
            "offset": 0,
        }

    monkeypatch.setattr(server.CLIENT, "get", get)
    contents, structured = asyncio.run(server.mcp.call_tool(
        "local_ai_status",
        {
            "action": "traces",
            "min_duration_ms": 1000,
            "trace_action": "search",
            "response_profile": "compact",
            "max_response_tokens": 1200,
        },
    ))

    payload = json.loads(contents[0].text)
    assert calls == ["/api/debug-traces?min_duration_ms=1000&action=search&limit=20"]
    assert payload["items"][0]["trace_id"] == "slow-search"
    assert structured["items"][0]["duration_ms"] == 1500
