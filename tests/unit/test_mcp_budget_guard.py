from __future__ import annotations

import json

from local_ai_hub import mcp_server
from local_ai_hub.token_accounting import json_tokens


def test_task_mutation_budget_is_clamped_before_dispatch(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    def fake_post(_path: str, payload: dict[str, object], **_kwargs: object):
        captured.append(payload)
        return {"success": True}

    monkeypatch.setattr(mcp_server.CLIENT, "post", fake_post)
    monkeypatch.setattr(mcp_server, "_compact", lambda value, *_args, **_kwargs: value)

    mcp_server.local_ai_coord.__wrapped__(
        action="task_cleanup_worktree",
        task_id="task-budget-bound",
        max_response_tokens=10_000_000,
    )

    assert len(captured) == 1
    assert captured[0]["response_budget_tokens"] <= max(
        mcp_server.RESPONSE_DEFAULT_TOKENS,
        int(mcp_server.RESPONSE_BUDGET_CFG.get("max_tokens", mcp_server.RESPONSE_DEFAULT_TOKENS * 2)),
    )


def test_fractional_explicit_budget_rejects_before_tool_execution(monkeypatch) -> None:
    monkeypatch.setattr(
        mcp_server,
        "configured_state_dir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("tool executed")),
    )

    result = mcp_server.local_ai_coord(action="task_create", max_response_tokens=128.5)

    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["terminal"] is True and result["retryable"] is False
    assert "integer" in result["error"]


def test_registered_mcp_wire_budget_is_clamped(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", mcp_server.OrderedDict())

    content, structured = mcp_server._mcp_budget_payload(
        "local_ai_status",
        {"max_response_tokens": 10_000_000},
        {"success": True, "status": "ready"},
    )

    text = content[0].text
    payload = json.loads(text)
    requested = payload["response_budget"]["requested_tokens"]
    assert requested <= max(
        mcp_server.RESPONSE_DEFAULT_TOKENS,
        int(mcp_server.RESPONSE_BUDGET_CFG.get("max_tokens", mcp_server.RESPONSE_DEFAULT_TOKENS * 2)),
    )
    assert json_tokens({"content": [{"type": "text", "text": text}],
                        "structuredContent": structured, "isError": False}) <= requested
