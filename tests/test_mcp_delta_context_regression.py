import asyncio
from collections import OrderedDict

import mcp.types as mcp_types

from local_ai_hub import mcp_server


def test_repeated_repository_context_delta_does_not_repeat_body(monkeypatch):
    monkeypatch.setattr(mcp_server, "RESPONSE_BUDGET_ENABLED", True)
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", OrderedDict())
    marker = "unchanged repository context marker"
    value = {
        "success": True, "context": marker, "request_id": "first",
        "context_id": "ctx-051", "evidence_ids": ["evidence-051"],
    }
    options = {"response_profile": "compact", "reuse_key": "case-051", "max_response_tokens": 800}
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(options)
    try:
        first = mcp_server._context_pack_projection(value)
        mcp_server._CURRENT_RESPONSE_OPTIONS.set({**options, "response_profile": "delta"})
        second = mcp_server._context_pack_projection({**value, "request_id": "second"})
        changed = mcp_server._context_pack_projection({**value, "request_id": "third", "context": "new context"})
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)
    assert marker in str(first)
    assert second["unchanged"] is True
    assert second["request_id"] == "second"
    assert second["context_id"] == "ctx-051"
    assert second["evidence_ids"] == ["evidence-051"]
    assert marker not in str(second)
    assert changed.get("unchanged") is not True
    assert "new context" in str(changed)


def test_repository_tool_returns_delta_through_dispatcher(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "RESPONSE_BUDGET_ENABLED", True)
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", OrderedDict())
    client = mcp_server.HubClient(auto_start=False)
    marker = "stable repository context for case 051"
    calls = []

    def post(path, payload, timeout=None, **kwargs):
        calls.append((path, payload))
        return {"success": True, "context": marker, "context_id": "ctx-051", "evidence_ids": ["e-051"]}

    monkeypatch.setattr(client, "post", post)
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    args = {"action": "context", "root": str(tmp_path), "query": "inspect", "mode": "adaptive", "reuse_key": "case-051-dispatch", "max_response_tokens": 800}
    first = mcp_server.local_ai_repo(**args, response_profile="compact")
    second = mcp_server.local_ai_repo(**args, response_profile="delta")
    assert len(calls) == 2
    assert marker in str(first)
    assert second["unchanged"] is True
    assert second["context_id"] == "ctx-051"
    assert second["evidence_ids"] == ["e-051"]
    assert marker not in str(second)


def test_local_delta_decision_is_not_overwritten_by_upstream_flag(monkeypatch):
    monkeypatch.setattr(mcp_server, "RESPONSE_BUDGET_ENABLED", True)
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", OrderedDict())
    value = {"success": True, "context": "stable", "unchanged": False}
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set({"response_profile": "compact", "reuse_key": "case-051-upstream", "max_response_tokens": 800})
    try:
        mcp_server._context_pack_projection(value)
        mcp_server._CURRENT_RESPONSE_OPTIONS.set({"response_profile": "delta", "reuse_key": "case-051-upstream", "max_response_tokens": 800})
        second = mcp_server._context_pack_projection(value)
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)
    assert second["unchanged"] is True
    assert "stable" not in str(second)


def test_repository_context_delta_at_registered_mcp_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "RESPONSE_BUDGET_ENABLED", True)
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", OrderedDict())
    client = mcp_server.HubClient(auto_start=False)
    marker = "case-051 registered boundary content"
    monkeypatch.setattr(client, "post", lambda *_args, **_kwargs: {
        "success": True, "context": marker, "context_id": "wire-ctx", "evidence_ids": ["wire-evidence"]
    })
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    args = {"action": "context", "root": str(tmp_path), "query": "inspect", "reuse_key": "case-051-wire", "max_response_tokens": 800}

    async def call(profile):
        request = mcp_types.CallToolRequest(method="tools/call", params=mcp_types.CallToolRequestParams(
            name="local_ai_repo", arguments={**args, "response_profile": profile}
        ))
        return (await mcp_server.mcp._mcp_server.request_handlers[mcp_types.CallToolRequest](request)).root

    async def both():
        return await call("compact"), await call("delta")

    first, second = asyncio.run(both())
    assert first.isError is False and second.isError is False
    assert marker in str(first.structuredContent)
    assert second.structuredContent["unchanged"] is True
    assert second.structuredContent["context_id"] == "wire-ctx"
    assert second.structuredContent["evidence_ids"] == ["wire-evidence"]
    assert marker not in str(second.structuredContent)
    assert marker not in str(second.content)
