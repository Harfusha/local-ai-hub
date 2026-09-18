from __future__ import annotations

import asyncio
import json
from pathlib import Path
import pytest

from local_ai_hub import mcp_server as local_ai_mcp
import mcp.types as t
from local_ai_hub.token_accounting import json_tokens


def test_python_direct_invocation_returns_dict() -> None:
    res = local_ai_mcp.local_ai_status()
    assert isinstance(res, dict)
    assert "success" in res


def test_mcp_call_tool_returns_compact_minified_json(monkeypatch) -> None:
    monkeypatch.setattr(local_ai_mcp, "CLIENT", local_ai_mcp.HubClient(tenant="test", auto_start=False))
    monkeypatch.setattr(local_ai_mcp.CLIENT, "get", lambda path, timeout=None: {"hub_online": True, "scheduler": {}, "observability": {}})

    # Call via FastMCP call_tool (the MCP protocol entrypoint)
    result = asyncio.run(local_ai_mcp.mcp.call_tool("local_ai_status", {"detail": "brief"}))

    if isinstance(result, tuple):
        content = result[0][0]
    else:
        assert isinstance(result, list)
        assert len(result) >= 1
        content = result[0]
    assert isinstance(content, t.TextContent)
    assert content.type == "text"

    # Text must be compact (no newline formatting, no spacing around separators)
    assert "\n" not in content.text
    assert ": " not in content.text
    assert ", " not in content.text

    parsed = json.loads(content.text)
    assert isinstance(parsed, dict)
    assert parsed["success"] is True


def test_lowlevel_request_handler_returns_compact_minified_json(monkeypatch) -> None:
    monkeypatch.setattr(local_ai_mcp, "CLIENT", local_ai_mcp.HubClient(tenant="test", auto_start=False))
    monkeypatch.setattr(local_ai_mcp.CLIENT, "get", lambda path, timeout=None: {"hub_online": True, "scheduler": {}, "observability": {}})

    req = t.CallToolRequest(method="tools/call", params=t.CallToolRequestParams(name="local_ai_status", arguments={"detail": "brief"}))
    server_res = asyncio.run(local_ai_mcp.mcp._mcp_server.request_handlers[t.CallToolRequest](req))

    assert hasattr(server_res, "root")
    tool_res = server_res.root
    assert isinstance(tool_res, t.CallToolResult)
    assert len(tool_res.content) >= 1
    content = tool_res.content[0]
    assert isinstance(content, t.TextContent)

    assert "\n" not in content.text
    assert ": " not in content.text
    assert ", " not in content.text

    parsed = json.loads(content.text)
    assert parsed["success"] is True


def _capture_client(monkeypatch, response):
    client = local_ai_mcp.HubClient(tenant="test", auto_start=False)
    calls = []

    def post(path, payload, timeout=None):
        calls.append((path, payload, timeout))
        return response

    monkeypatch.setattr(local_ai_mcp, "CLIENT", client)
    monkeypatch.setattr(client, "post", post)
    return calls


def test_local_ai_repo_context_forwards_guarded_pack_fields(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True, "evidence_ids": ["e1"]})

    result = local_ai_mcp.local_ai_repo(
        action="context",
        root="C:/repo",
        query="find route",
        workspace="ws",
        mode="full",
        task_id="task-1",
        phase="implementation",
        focus=["reuse", "contract"],
        preload_profile="default",
        changed_paths=["src/app.py"],
        base="main",
        staged=True,
        guarded=True,
        since_hash="rev-1",
        approval=True,
        override_reason="approved test scope",
        token_budget=777,
    )

    assert result["success"] is True
    assert len(calls) == 1
    path, payload, _ = calls[0]
    assert path == "/api/context/pack"
    assert payload == {
        "root": str(Path("C:/repo")),
        "query": "find route",
        "workspace": "ws",
        "max_tokens": 777,
        "mode": "full",
        "guarded": True,
        "task_id": "task-1",
        "phase": "implementation",
        "focus": ["reuse", "contract"],
        "preload_profile": "default",
        "changed_paths": ["src/app.py"],
        "base": "main",
        "staged": True,
        "since_hash": "rev-1",
        "approval": True,
        "override_reason": "approved test scope",
        "token_budget": 777,
    }


def test_local_ai_repo_context_preserves_legacy_fast_full_payload(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True, "context": "legacy"})

    local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="legacy", mode="full", max_tokens=512,
    )

    assert calls == [(
        "/api/context/pack",
        {"root": str(Path("C:/repo")), "query": "legacy", "workspace": None, "max_tokens": 512, "mode": "full"},
        600.0,
    )]


def test_local_ai_repo_context_returns_bounded_deterministic_projection(monkeypatch) -> None:
    response = {
        "success": True,
        "context": "x" * 20000,
        "evidence": [{"evidence_id": f"e{i}", "content": "y" * 1000} for i in range(40)],
        "evidence_ids": ["deterministic-1"],
        "warnings": [{"code": "scope_drift", "message": "warning"}],
        "repo_revision": "revision-1",
        "changed_paths": ["src/app.py"],
        "degraded": True,
        "fallback_used": True,
        "adaptive_context_pack": {
            "evidence": [{"evidence_id": "deterministic-pack"}],
            "warnings": [{"code": "pack-warning", "message": "pack warning"}],
            "repo_revision": "revision-pack",
            "changed_paths": ["pack.py"],
        },
        "postprocess": {"evidence_ids": ["model-claim"], "changed_paths": ["model.py"]},
    }
    calls = _capture_client(monkeypatch, response)

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="guarded", task_id="task-1", phase="review",
        guarded=True, max_response_tokens=500,
    )

    assert len(json.dumps(result, separators=(",", ":"))) <= 8000
    assert result["evidence_ids"] == ["deterministic-pack"]
    assert result["changed_paths"] == ["pack.py"]
    assert result["repo_revision"] == "revision-pack"
    assert result["warnings"][0]["code"] == "pack-warning"
    assert result["degraded"] is True
    assert result["fallback_used"] is True
    assert calls[0][1]["guarded"] is True


def test_local_ai_repo_context_bounds_oversized_authoritative_fields(monkeypatch) -> None:
    response = {
        "success": True,
        "context": "context",
        "adaptive_context_pack": {
            "warnings": [{"code": "scope_drift", "message": "w" * 10000} for _ in range(24)],
            "evidence": [{"evidence_id": f"evidence-{i}-" + ("e" * 10000)} for i in range(24)],
            "repo_revision": "revision-" + ("r" * 10000),
            "changed_paths": ["src/" + ("p" * 10000) for _ in range(24)],
        },
    }
    _capture_client(monkeypatch, response)

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="guarded", task_id="task-1", phase="review",
        guarded=True, max_response_tokens=220,
    )

    assert json_tokens(result) <= 220
    assert result["response_budget"]["requested_tokens"] == 220


def test_local_ai_repo_context_propagates_bounded_http_error(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {
        "success": False, "status_code": 400, "terminal": True, "retryable": False,
        "error": "focus must be a list",
    })

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", query="bad", guarded=True, task_id="task-1",
    )

    assert result == {
        "success": False,
        "status_code": 400,
        "terminal": True,
        "retryable": False,
        "error": "focus must be a list",
    }
    assert calls[0][0] == "/api/context/pack"


def test_local_ai_repo_context_rejects_non_object_route_response(monkeypatch) -> None:
    _capture_client(monkeypatch, "not-json-object")

    result = local_ai_mcp.local_ai_repo(action="context", root="C:/repo", query="bad")

    assert result == {
        "success": False,
        "status_code": 502,
        "terminal": True,
        "retryable": True,
        "error": "context pack response must be a JSON object",
    }


def test_local_ai_repo_context_rejects_malformed_guard_input_before_http(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True})

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", guarded="yes", task_id="task-1",
    )

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["terminal"] is True
    assert "guarded must be boolean" in result["error"]
    assert calls == []


def test_local_ai_repo_context_rejects_guard_fields_without_guard_trigger(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True})

    result = local_ai_mcp.local_ai_repo(
        action="context", root="C:/repo", changed_paths=["src/app.py"],
    )

    assert result["success"] is False
    assert result["status_code"] == 400
    assert "require guarded=true" in result["error"]
    assert calls == []


def test_context_compile_compatibility_stays_on_agent_state_route(monkeypatch) -> None:
    calls = _capture_client(monkeypatch, {"success": True, "task_id": "task-1"})

    local_ai_mcp.local_ai_repo(action="context_compile", root="C:/repo", task_id="task-1", max_tokens=900)

    assert calls[0][0] == "/api/agent-state/context"
    assert calls[0][1]["task_id"] == "task-1"
    assert calls[0][1]["token_budget"] == 900
