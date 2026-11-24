from __future__ import annotations

import os
from local_ai_hub import mcp_server


def test_mcp_client_status_default(monkeypatch):
    monkeypatch.delenv("LOCAL_AI_AGENT", raising=False)
    for env_var in ("ANTIGRAVITY_ENV", "CODEX_HOME", "CLAUDE_ENV", "OPENCODE_SESSION", "CURSOR_ENV", "VSCODE_CWD", "GEMINI_CLI_HOME"):
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)

    res = mcp_server.local_ai_coord(action="client_status")
    assert res.get("success") is True
    assert res.get("client_id") == "generic_mcp"
    assert res.get("adapter_version") == "5.0-pragmatic"
    assert "hook_support" in res
    assert "instruction_targets" in res


def test_mcp_client_status_opencode(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_AGENT", "opencode")
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)

    res = mcp_server.local_ai_coord(action="client_status")
    assert res.get("success") is True
    assert res.get("client_id") == "opencode"
    assert res.get("display_name") == "OpenCode"
    assert res.get("hook_support") == "js_plugin"
    assert res.get("prompt_cache_shield") is True
    assert res.get("has_goal_system") is True
    assert "local_ai_work" in (res.get("tool_filter") or [])
    assert "local_ai_status" in (res.get("tool_filter") or [])


def test_mcp_client_status_claude(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_AGENT", "claude")
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)

    res = mcp_server.local_ai_coord(action="client_status")
    assert res.get("success") is True
    assert res.get("client_id") == "claude"
    assert res.get("display_name") == "Anthropic Claude Code"
    assert res.get("prompt_cache_shield") is True
    assert "CLAUDE.md" in res.get("instruction_targets", [])


def test_mcp_client_status_codex(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_AGENT", "codex")
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)

    res = mcp_server.local_ai_coord(action="client_status")
    assert res.get("success") is True
    assert res.get("client_id") == "codex"
    assert res.get("has_token_tracking") is True
    assert res.get("has_reasoning_tokens") is True
    assert res.get("prompt_cache_shield") is True
