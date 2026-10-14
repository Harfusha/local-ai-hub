import asyncio
from pathlib import Path
import pytest

from local_ai_hub import mcp_server
from local_ai_hub.mcp_server import mcp, local_ai_repo


def _call_tool(name, arguments):
    return asyncio.run(mcp.call_tool(name, arguments))


@pytest.fixture(autouse=True)
def _allow_test_roots(monkeypatch):
    monkeypatch.setattr(mcp_server, "is_rooted_path", lambda p: True)
    monkeypatch.setattr(mcp_server, "_client_root", lambda p: p)


def test_mcp_callees_action_dispatches_correctly(monkeypatch):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url != "/api/telemetry/tool-accounting":
                captured.update({"url": url, "payload": payload})
            return {"success": True, "callees": [{"symbol": "bar", "path": "test.py"}]}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    res = local_ai_repo(action="callees", root=".", query="foo")
    assert captured["url"] == "/api/code/callees"
    assert captured["payload"]["symbol"] == "foo"
    assert captured["payload"]["root"] == "."
    assert res.get("success") is True


def test_mcp_implementations_action_dispatches_correctly(monkeypatch):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url != "/api/telemetry/tool-accounting":
                captured.update({"url": url, "payload": payload})
            return {"success": True, "implementations": [{"symbol": "FooImpl", "path": "impl.py"}]}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    res = local_ai_repo(action="implementations", root=".", query="IFoo", path="src/interface.py")
    assert captured["url"] == "/api/code/implementations"
    assert captured["payload"]["symbol"] == "IFoo"
    assert captured["payload"]["path"] == "src/interface.py"
    assert res.get("success") is True


def test_mcp_declaration_action_dispatches_correctly(monkeypatch):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url != "/api/telemetry/tool-accounting":
                captured.update({"url": url, "payload": payload})
            return {"success": True, "declaration": {"symbol": "bar", "line": 42, "path": "test.py"}}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    res = local_ai_repo(action="declaration", root=".", query="bar")
    assert captured["url"] == "/api/code/declaration"
    assert captured["payload"]["symbol"] == "bar"
    assert res.get("success") is True


def test_mcp_call_tool_symbol_graph_actions(monkeypatch):
    captured = []

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url != "/api/telemetry/tool-accounting":
                captured.append((url, payload))
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())

    for act in ("callees", "implementations", "declaration"):
        result = _call_tool("local_ai_repo", {"action": act, "root": ".", "query": "target"})
        assert not any(err in str(result) for err in ("invalid action", "Unknown action", "ValidationError")), f"Action {act} rejected: {result}"

    assert len(captured) == 3
    assert captured[0][0] == "/api/code/callees"
    assert captured[1][0] == "/api/code/implementations"
    assert captured[2][0] == "/api/code/declaration"
