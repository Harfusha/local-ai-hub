from __future__ import annotations

import pytest

from local_ai_hub import mcp_server


class _CapturingClient:
    def __init__(self):
        self.calls = []

    def post(self, path, payload, timeout=None):
        self.calls.append((path, payload, timeout))
        return {"success": True, "workspace": payload.get("workspace")}


def test_registered_rag_description_states_explicit_content_requirement(monkeypatch):
    monkeypatch.setattr(mcp_server.FEATURES, "rag", True)

    description = mcp_server._all_desc_map["local_ai_rag"]()

    assert "Document ingestion requires non-empty content" in description


def test_document_ingest_requires_explicit_content_and_does_not_use_query_or_root(monkeypatch):
    client = _CapturingClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server.FEATURES, "rag", True)

    result = mcp_server.local_ai_rag(
        action="ingest_document",
        root="C:/source",
        query="query text must not become document content",
    )

    expected = {
        "success": False,
        "retryable": False,
        "terminal": True,
        "error": "content is required for ingest_document",
    }
    assert {key: result[key] for key in expected} == expected
    # Rejected tool calls still emit telemetry; only forbid RAG ingestion.
    assert all(path != "/api/rag/ingest_document" for path, _, _ in client.calls)


def test_document_ingest_maps_explicit_content_on_first_call(monkeypatch, tmp_path):
    client = _CapturingClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server.FEATURES, "rag", True)

    result = mcp_server.local_ai_rag(
        action="ingest_document",
        root=str(tmp_path.resolve()),
        content="specific document text",
        query="different query text",
        title="SDK guide",
    )

    assert result["success"] is True
    assert len(client.calls) == 1
    path, payload, _timeout = client.calls[0]
    assert path == "/api/rag/ingest_document"
    assert payload == {
        "root": str(tmp_path.resolve()),
        "workspace": mcp_server.canonical_workspace_id(str(tmp_path.resolve())),
        "content": "specific document text",
        "title": "SDK guide",
        "metadata": None,
    }


@pytest.mark.parametrize(
    ("profile", "qualified", "expected"),
    [("low", True, True), ("balanced", False, False), ("balanced", True, True), ("high", True, True)],
)
def test_rag_search_only_requests_reranking_when_capability_is_available(
    monkeypatch, tmp_path, profile, qualified, expected
):
    client = _CapturingClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server.FEATURES, "rag", True)
    monkeypatch.setattr(mcp_server.FEATURES, "hardware_profile", profile)
    monkeypatch.setattr(mcp_server.FEATURES, "local_reranking_qualified", qualified, raising=False)

    result = mcp_server.local_ai_rag(action="search", root=str(tmp_path.resolve()), query="needle")

    assert result["success"] is True
    assert client.calls[0][0] == "/api/rag/search"
    assert client.calls[0][1]["use_reranker"] is expected
