from __future__ import annotations

import asyncio
import copy
import json

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.token_accounting import json_tokens


@pytest.mark.parametrize("source_success", [True, False])
def test_real_context_evidence_shape_keeps_outcome_and_citations(tmp_path, monkeypatch, source_success):
    # Match the HTTP retrieval shape: source excerpts are named raw, not text.
    evidence = [
        {"path": f"docs/contracts/retrieval-{index}.md", "start_line": 100,
         "end_line": 110, "score": 20.0, "file_sha256": "a" * 64,
         "raw": "retained source excerpt " * 220, "evidence_id": f"E{index:020x}"}
        for index in range(6)
    ]
    source = {"success": source_success, "root": str(tmp_path),
              "context": "Grounded repository context. " * 300,
              "evidence": evidence, "estimated_tokens": 8000,
              "context_source": "deterministic-fast"}
    if not source_success:
        source.update(error="repository unavailable", terminal=True, retryable=False, status_code=503)
    original = copy.deepcopy(source)
    requests = []

    def post(path, payload, **_options):
        requests.append((path, payload))
        assert path == "/api/context/pack"
        return copy.deepcopy(source)

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    contents, structured = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
        "action": "context", "root": str(tmp_path), "mode": "adaptive",
        "query": "Inspect grounded retrieval contracts", "max_response_tokens": 3200,
        "response_profile": "compact",
    }))
    result = structured if structured is not None else json.loads(contents[0].text)
    wire = {"content": [{"type": "text", "text": item.text} for item in contents]}
    if structured is not None:
        wire.update(structuredContent=structured, isError=False)
    assert json_tokens(wire) <= 3200
    assert result["response_budget"]["returned_tokens"] == json_tokens(wire)
    assert result["success"] is source_success
    assert result.get("error") == source.get("error")
    if not source_success:
        assert result["terminal"] is True and result["retryable"] is False
    assert result["evidence"]
    by_id = {item["evidence_id"]: item for item in evidence}
    for item in result["evidence"]:
        citation = by_id[item["evidence_id"]]
        assert all(item[key] == citation[key] for key in ("path", "start_line", "end_line"))
        assert "raw" not in item
    assert len(requests) == 1
    assert requests[0][1]["mode"] == "adaptive"
    assert source == original
