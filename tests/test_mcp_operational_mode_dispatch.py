from __future__ import annotations

import asyncio
from types import SimpleNamespace

from local_ai_hub import mcp_server


def _mode(monkeypatch, name: str) -> None:
    def load_mode(state_dir=None):
        return SimpleNamespace(
            mode=name,
            revision=2,
            updated_at="2026-09-29T00:00:00Z",
            degraded=False,
            error="",
        )

    monkeypatch.setattr(mcp_server, "load_operational_mode", load_mode, raising=False)


def _dispatch(name: str, arguments: dict[str, object]):
    return asyncio.run(mcp_server._compact_mcp_call_tool(name, arguments))[1]


def test_gaming_policy_keeps_repo_search_lightweight_and_blocks_inference(monkeypatch) -> None:
    _mode(monkeypatch, "gaming")
    calls = []
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: calls.append(args))

    action, requires_heavy_work = mcp_server._classify_mcp_operation(
        "local_ai_repo", {"action": "search"}
    )
    read_rejection = mcp_server._operational_mode_rejection(
        action, requires_heavy_work=requires_heavy_work
    )
    inference = _dispatch("local_ai_task", {"action": "delegate", "task": "review"})

    assert action == "search"
    assert requires_heavy_work is False
    assert read_rejection is None
    assert inference["success"] is False
    assert inference["mode"] == "gaming"
    assert inference["error"] == "hub paused: gaming mode active"
    assert calls == []


def test_gaming_speculative_lint_policy_requires_opt_in(monkeypatch) -> None:
    _mode(monkeypatch, "gaming")
    monkeypatch.setattr(mcp_server.FEATURES, "speculative_lint", True)

    assert mcp_server._operational_mode_rejection("speculative_lint") is None
    assert mcp_server._operational_mode_rejection("run") is not None


def test_maintenance_mcp_dispatch_blocks_inference(monkeypatch) -> None:
    _mode(monkeypatch, "maintenance")
    calls = []
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: calls.append(args))

    result = _dispatch(
        "local_ai_task",
        {"action": "delegate", "task": "review"},
    )

    assert result["success"] is False
    assert result["mode"] == "maintenance"
    assert result["error"] == "hub paused: maintenance mode active"
    assert calls == []
