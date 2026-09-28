from __future__ import annotations

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

    assert result == {
        "success": False,
        "status_code": 400,
        "retryable": False,
        "terminal": True,
        "error": "content is required for document ingestion",
    }
    assert client.calls == []


def test_document_ingest_maps_explicit_content_on_first_call(monkeypatch):
    client = _CapturingClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server.FEATURES, "rag", True)

    result = mcp_server.local_ai_rag(
        action="ingest_document",
        content="specific document text",
        query="different query text",
        title="SDK guide",
    )

    assert result["success"] is True
    assert len(client.calls) == 1
    path, payload, _timeout = client.calls[0]
    assert path == "/api/rag/ingest_document"
    assert payload == {
        "workspace": "default",
        "content": "specific document text",
        "title": "SDK guide",
        "metadata": None,
    }
