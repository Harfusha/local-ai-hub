import asyncio

from local_ai_hub.mcp_server import mcp


def _call_repo_tool(arguments):
    return asyncio.run(mcp.call_tool("local_ai_repo", arguments))


def test_skeletonize_mcp_payload_forwards_root_and_preserves_query_precedence(
    monkeypatch, tmp_path
):
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
            "diff": "def from_diff(): pass",
            "task": "def from_task(): pass",
            "path": "module.py",
        }
    )

    assert captured["url"] == "/api/repo/skeletonize"
    assert captured["payload"] == {
        "root": str(tmp_path),
        "code": "def from_query(): pass",
        "targets": ["module.py"],
    }


def test_skeletonize_mcp_payload_uses_task_when_query_and_diff_are_empty(
    monkeypatch, tmp_path
):
    captured = {}

    class DummyClient:
        def post(self, url, payload, **kwargs):
            if url == "/api/repo/skeletonize":
                captured.update(url=url, payload=payload)
            return {"success": True, "skeleton": "def foo(): ..."}

    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())

    _call_repo_tool(
        {
            "action": "skeletonize",
            "root": str(tmp_path),
            "task": "def from_task(): pass",
        }
    )

    assert captured["payload"] == {
        "root": str(tmp_path),
        "code": "def from_task(): pass",
        "targets": None,
    }
