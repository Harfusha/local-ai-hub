from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.process_utils import canonical_workspace_id


class CaptureClient:
    def __init__(self):
        self.posts = []

    def post(self, path, payload, **kwargs):
        self.posts.append((path, dict(payload)))
        return {"success": True, "results": []}


def _call_rag(arguments):
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_rag", arguments))
    contents = result[0] if isinstance(result, tuple) else result
    return json.loads(next(item.text for item in contents if item.type == "text"))


def _enable_rag(monkeypatch):
    monkeypatch.setattr(mcp_server, "FEATURES", type("Features", (), {"rag": True})())
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    client = CaptureClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    return client


def test_mcp_dispatch_uses_assigned_checkout_source():
    checkout = Path(__file__).resolve().parents[2]
    assert Path(mcp_server.__file__).resolve().is_relative_to(checkout / "src")


def test_workspace_id_uses_canonical_existing_format(tmp_path):
    from local_ai_hub.rag import RAGStore

    workspace_id = RAGStore.workspace_id(str(tmp_path))

    assert re.fullmatch(rf"{re.escape(tmp_path.name)}-[0-9a-f]{{12}}", workspace_id)
    assert workspace_id == canonical_workspace_id(tmp_path)


@pytest.mark.parametrize("workspace_kind", ["empty", "path"])
def test_public_rag_search_resolves_workspace_from_explicit_root(
    monkeypatch, tmp_path, workspace_kind
):
    monkeypatch.setitem(sys.modules, "local_ai_hub.rag", None)
    client = _enable_rag(monkeypatch)
    workspace = "" if workspace_kind == "empty" else str(tmp_path)

    response = _call_rag({
        "action": "search",
        "root": str(tmp_path),
        "workspace": workspace,
        "query": "needle",
    })

    assert len(client.posts) == 1
    endpoint, payload = client.posts[0]
    assert endpoint == "/api/rag/search"
    assert payload["root"] == mcp_server._client_root(str(tmp_path))
    assert payload["workspace"] == canonical_workspace_id(tmp_path)
    assert payload["query"] == "needle"
    assert response["success"] is True


def test_public_rag_search_preserves_explicit_workspace_id(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "local_ai_hub.rag", None)
    client = _enable_rag(monkeypatch)
    workspace_id = canonical_workspace_id(tmp_path)

    _call_rag({
        "action": "search",
        "root": str(tmp_path),
        "workspace": workspace_id,
        "query": "needle",
    })

    assert client.posts == [(
        "/api/rag/search",
        {
            "root": mcp_server._client_root(str(tmp_path)),
            "query": "needle",
            "workspace": workspace_id,
            "top_k": 6,
            "use_reranker": True,
        },
    )]


def test_public_rag_search_preserves_explicit_opaque_workspace_id(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "local_ai_hub.rag", None)
    client = _enable_rag(monkeypatch)
    workspace_id = "curated:handbook/v1"

    _call_rag({
        "action": "search",
        "root": str(tmp_path),
        "workspace": workspace_id,
        "query": "needle",
    })

    assert client.posts == [(
        "/api/rag/search",
        {
            "root": mcp_server._client_root(str(tmp_path)),
            "query": "needle",
            "workspace": workspace_id,
            "top_k": 6,
            "use_reranker": True,
        },
    )]


def test_public_rag_search_rejects_missing_root_before_transport(monkeypatch):
    client = _enable_rag(monkeypatch)

    response = _call_rag({"action": "search", "query": "needle"})

    assert response["success"] is False
    assert "explicit absolute project root" in response["error"]
    assert client.posts == []
