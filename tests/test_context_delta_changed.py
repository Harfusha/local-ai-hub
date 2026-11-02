from collections import OrderedDict

import pytest

from local_ai_hub import mcp_server


def _project_pair(monkeypatch, first, second, budget=1000):
    monkeypatch.setattr(mcp_server, "RESPONSE_BUDGET_ENABLED", True)
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", OrderedDict())
    options = {"response_profile": "compact", "reuse_key": "delta-changed-regression", "max_response_tokens": budget}
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(options)
    try:
        mcp_server._context_pack_projection(first)
        mcp_server._CURRENT_RESPONSE_OPTIONS.set({**options, "response_profile": "delta"})
        return mcp_server._context_pack_projection(second)
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)


def test_changed_metadata_does_not_repeat_unchanged_context(monkeypatch):
    first = {"success": True, "context": "stable context marker", "request_id": "first", "context_id": "ctx", "revision": "1"}
    result = _project_pair(monkeypatch, first, {**first, "request_id": "second", "revision": "2"})
    assert "context" not in result
    assert result["delta"]["changed"]["revision"] == "2"
    assert result["request_id"] == "second"
    assert "request_id" not in result["delta"]["changed"]


@pytest.mark.parametrize("budget", [128, 256, 512, 3200])
def test_changed_context_must_be_delivered_or_explicitly_rejected(monkeypatch, budget):
    first = {"success": True, "context": "x" * 22000, "request_id": "first", "context_id": "ctx", "root": "C:/fixture", "evidence_ids": ["evidence"]}
    result = _project_pair(monkeypatch, first, {**first, "request_id": "second", "context": "y" * 22000}, budget=budget)
    assert result.get("success") is False or "context" in result.get("delta", {}).get("changed", {})
    if result.get("success") is False:
        assert result["status_code"] == 413
        assert result["request_id"] == "second"
        assert result["root"] == "C:/fixture"
        assert result["response_budget"]["returned_tokens"] == mcp_server.json_tokens(result)
        assert result["response_budget"]["returned_tokens"] <= budget
        assert "delta-changed-regression" not in mcp_server._REUSE_DIGESTS
        assert "delta-changed-regression" not in mcp_server._REUSE_VALUES
