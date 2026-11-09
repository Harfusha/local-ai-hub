from __future__ import annotations

import json

from local_ai_hub import mcp_server
from local_ai_hub.token_accounting import json_tokens


def test_task_memory_wire_preserves_checkpoint_or_rejects_budget() -> None:
    checkpoint = {
        "phase": "verification", "next_action": "review",
        "affected_paths": ["README.md"], "evidence_ids": ["ev-1"], "blockers": ["pending"],
        "state_data": {"memory_context": {"schema_version": 2, "context": {}, "items": []},
                       "marker": "x" * 4000},
    }
    value = {"success": True, "task": {"task_id": "task-1", "checkpoint": checkpoint}}
    args = {"action": "task_get", "max_response_tokens": 8192}
    content, structured = mcp_server._mcp_budget_payload("local_ai_coord", args, value)
    assert structured["task"]["checkpoint"] == checkpoint
    wire = {"content": [{"type": "text", "text": content[0].text}],
            "structuredContent": structured, "isError": False}
    assert json_tokens(wire) <= 8192

    _, limited = mcp_server._mcp_budget_payload(
        "local_ai_coord", {"action": "task_get", "max_response_tokens": 512}, value,
    )
    assert limited["success"] is False
    assert limited["error"] == "budget_too_small"


def test_task_memory_wire_reports_omissions_without_exposing_fencing_token() -> None:
    for include_memory in (False, True):
        state = {"_pending_fenced_work": {"attempt_token": "secret-token"},
                 "memory_audit_history": [{"content": "private-history"}]}
        if include_memory:
            state["memory_context"] = {"schema_version": 2, "context": {}, "items": []}
        value = {"success": True, "task": {"task_id": "task-1", "checkpoint": {"state_data": state}}}
        for budget in (512, 4096):
            content, structured = mcp_server._mcp_budget_payload(
                "local_ai_coord", {"action": "task_get", "max_response_tokens": budget}, value,
            )
            assert "secret-token" not in json.dumps(structured) + content[0].text
            assert "private-history" not in json.dumps(structured) + content[0].text
            if structured["success"]:
                assert structured["task"]["checkpoint"]["state_data_omitted"] == [
                    "_pending_fenced_work", "memory_audit_history",
                ]
            else:
                assert structured["error"] == "budget_too_small"


def test_task_wire_ignores_invalid_omission_metadata_without_memory() -> None:
    value = {"success": True, "task": {"task_id": "task-1", "checkpoint": {
        "state_data": {}, "state_data_omitted": [{}, None, "unknown"],
    }}}
    _, structured = mcp_server._mcp_budget_payload(
        "local_ai_coord", {"action": "task_get", "max_response_tokens": 4096}, value,
    )
    assert "state_data_omitted" not in structured["task"]["checkpoint"]


def test_task_list_wire_never_exposes_private_state_or_drops_items() -> None:
    state = {"_pending_fenced_work": {"attempt_token": "secret-token"},
             "memory_audit_history": [{"content": "private-history"}]}
    value = {"success": True, "has_more": True, "next_offset": 2, "tasks": [
        {"task_id": "task-1", "checkpoint": {"state_data": state}},
        {"task_id": "task-2", "checkpoint": {"state_data": {
            **state, "memory_context": {"schema_version": 2, "context": {}, "items": []},
        }}},
    ]}
    for budget in (512, 4096):
        content, structured = mcp_server._mcp_budget_payload(
            "local_ai_coord", {"action": "task_list", "max_response_tokens": budget}, value,
        )
        assert "secret-token" not in json.dumps(structured) + content[0].text
        assert "private-history" not in json.dumps(structured) + content[0].text
        if budget == 4096:
            assert structured["success"] is True
        if structured["success"]:
            assert [item["task_id"] for item in structured["tasks"]] == ["task-1", "task-2"]
            assert structured["has_more"] is True and structured["next_offset"] == 2
            for item in structured["tasks"]:
                assert item["checkpoint"]["state_data_omitted"] == [
                    "_pending_fenced_work", "memory_audit_history",
                ]
        else:
            assert structured["error"] == "budget_too_small"
    value["tasks"][0]["checkpoint"]["state_data"]["marker"] = "x" * 4000
    _, limited = mcp_server._mcp_budget_payload(
        "local_ai_coord", {"action": "task_list", "max_response_tokens": 512}, value,
    )
    assert limited["success"] is False and limited["error"] == "budget_too_small"


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
