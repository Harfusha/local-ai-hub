import asyncio
import json

from local_ai_hub import mcp_server
from local_ai_hub.mcp_server import mcp


def _call_repo_tool(arguments):
    return asyncio.run(mcp.call_tool("local_ai_repo", arguments))


def test_skeletonize_mcp_payload_forwards_canonical_query(
    monkeypatch, tmp_path
):
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    monkeypatch.setattr(
        mcp_server,
        "load_operational_mode",
        lambda _state_dir: OperationalModeSnapshot("active", 1, None),
    )
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url == "/api/repo/skeletonize":
                captured.update(url=url, payload=payload, kwargs=kwargs)
            return {"success": True, "skeleton": "def foo(): ..."}

    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())

    _call_repo_tool(
        {
            "action": "skeletonize",
            "root": str(tmp_path),
            "query": "def from_query(): pass",
            "path": "module.py",
        }
    )

    assert captured["url"] == "/api/repo/skeletonize"
    assert captured["payload"] == {
        "root": str(tmp_path),
        "code": "def from_query(): pass",
        "targets": ["module.py"],
    }


def test_skeletonize_mcp_payload_rejects_retired_task_alias(
    monkeypatch, tmp_path
):
    class DummyClient:
        def post(self, url, payload, **kwargs):
            raise AssertionError("retired task alias must be rejected before dispatch")

    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())

    wire_result = _call_repo_tool(
        {
            "action": "skeletonize",
            "root": str(tmp_path),
            "task": "def from_task(): pass",
        }
    )
    contents = wire_result[0] if isinstance(wire_result, tuple) else wire_result
    projected = json.loads(next(item.text for item in contents if item.type == "text"))
    assert projected["success"] is False
    assert not projected.get("skeleton")
