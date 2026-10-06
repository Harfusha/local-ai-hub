from __future__ import annotations

import asyncio
from types import SimpleNamespace

from local_ai_hub import mcp_server


def _mode(monkeypatch, name: str) -> None:
    monkeypatch.setattr(
        mcp_server,
        "load_operational_mode",
        lambda _state_dir: SimpleNamespace(
            mode=name,
            revision=2,
            updated_at="2026-09-29T00:00:00Z",
            degraded=False,
            error="",
        ),
    )


def _dispatch(name: str, arguments: dict[str, object]):
    return asyncio.run(mcp_server._compact_mcp_call_tool(name, arguments))[1]


def test_gaming_mcp_dispatch_allows_only_speculative_lint(monkeypatch) -> None:
    _mode(monkeypatch, "gaming")
    monkeypatch.setattr(mcp_server.FEATURES, "speculative_lint", True)
    calls = []

    def post(path, payload, *, timeout):
        calls.append((path, payload, timeout))
        return {"success": True, "state": "queued", "job_id": "lint-1"}

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)

    lint = _dispatch(
        "local_ai_command",
        {"action": "speculative_lint", "cwd": ".", "command": "lint"},
    )
    inference = _dispatch("local_ai_task", {"action": "delegate", "task": "review"})

    assert lint["success"] is True
    assert calls and calls[0][0] == "/api/speculative-lint"
    assert inference["success"] is False
    assert inference["error_code"] == "operational_mode_blocked"
    assert len(calls) == 1


def test_maintenance_mcp_dispatch_still_blocks_speculative_lint(monkeypatch) -> None:
    _mode(monkeypatch, "maintenance")
    monkeypatch.setattr(mcp_server.FEATURES, "speculative_lint", True)
    calls = []
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: calls.append(args))

    result = _dispatch(
        "local_ai_command",
        {"action": "speculative_lint", "cwd": ".", "command": "lint"},
    )

    assert result["success"] is False
    assert result["error_code"] == "operational_mode_blocked"
    assert calls == []
