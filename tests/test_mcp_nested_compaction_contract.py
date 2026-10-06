from __future__ import annotations

from local_ai_hub import mcp_server


def test_adaptive_context_pack_preserves_decision_metadata_through_full_projection(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", mcp_server.OrderedDict())
    options_token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(
        {
            "max_response_tokens": 220,
            "response_profile": "compact",
            "reuse_key": "test:mcp-nested-context-contract",
            "tool": "local_ai_repo",
        }
    )
    try:
        result = mcp_server._context_pack_projection(
            {
                "success": True,
                "guarded": True,
                "adaptive_context_pack": {
                    "success": True,
                    "terminal": True,
                    "retryable": False,
                    "degraded": True,
                    "stale": True,
                    "evidence": [{"evidence_id": "E-context-contract", "source": "deterministic"}],
                    "evidence_ids": ["E-context-contract"],
                    "context_id": "context-contract",
                },
            }
        )
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(options_token)

    pack = result["adaptive_context_pack"]
    assert pack["success"] is True
    assert pack["terminal"] is True
    assert pack["retryable"] is False
    assert pack["degraded"] is True
    assert pack["stale"] is True
    assert pack["evidence_ids"] == ["E-context-contract"]
    assert pack["evidence"][0]["evidence_id"] == "E-context-contract"
    assert result["evidence_ids"] == ["E-context-contract"]
