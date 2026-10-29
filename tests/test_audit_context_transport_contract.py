"""Canonical identity rejection and recoverable context on real MCP/HTTP paths."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from local_ai_hub import mcp_server
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract
from local_ai_hub.task_context import build_context_request
from local_ai_hub.token_accounting import json_tokens
import test_audit_live_session_isolation as isolation

isolated_hub = isolation.isolated_hub


@pytest.mark.parametrize("field,limit", [
    ("task_id", 200), ("session_id", 200), ("repository_id", 200),
    ("clone_id", 200), ("worktree_id", 200), ("branch", 200),
    ("repository_revision", 200), ("repo_revision", 200),
])
def test_distinct_context_identities_are_neither_coerced_nor_collapsed(field, limit):
    left = "x" * (limit - 1) + "A"
    right = "x" * (limit - 1) + "B"
    assert getattr(build_context_request({field: left}), field) == left
    assert getattr(build_context_request({field: right}), field) == right
    for invalid in (None, 123, False, [], " padded", "bad\0id", left + "overflow"):
        with pytest.raises(ValueError):
            build_context_request({field: invalid})


def _value(result):
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


def test_http_and_mcp_reject_invalid_identity_without_context_compilation(isolated_hub, monkeypatch):
    app, roots, post, _retrievals = isolated_hub
    compile_calls = []

    def forbidden_compile(*args, **kwargs):
        compile_calls.append((args, kwargs))
        raise AssertionError("invalid context reached compiler")

    monkeypatch.setattr(app.agent_context, "compile", forbidden_compile)
    base = {"action": "compile", "root": str(roots[0]), "task_id": "isolated-task-0",
            "session_id": "isolated-chat-0"}
    for field in ("task_id", "session_id", "repository_id", "clone_id", "worktree_id", "branch"):
        for invalid in (123, " padded", "bad\0id", "x" * 201):
            status, result = post("/api/agent-state/context", {**base, field: invalid})
            assert status in {400, 403, 404, 422}, result
            assert result["success"] is False, result
    for field in ("include_diagnostics", "_scoped_task_only"):
        for invalid in ("false", 0, [], None):
            status, result = post("/api/agent-state/context", {**base, field: invalid})
            assert status in {400, 403, 422}, result
            assert result["success"] is False, result

    async def mcp_rejections():
        async with create_connected_server_and_client_session(
            mcp_server.mcp, read_timeout_seconds=timedelta(seconds=8),
        ) as session:
            for invalid in (123, " padded", "bad\0id", "x" * 201):
                result = await session.call_tool("local_ai_coord", {
                    "action": "context_compile", "root": str(roots[0]), "task_id": invalid,
                    "max_response_tokens": 1024, "response_profile": "compact",
                })
                if not result.isError:
                    assert _value(result)["success"] is False, result

    asyncio.run(mcp_rejections())
    assert compile_calls == []


def test_large_task_context_is_recoverable_with_exact_artifact_identity(isolated_hub):
    app, roots, _post, _retrievals = isolated_hub
    original = app.agent_tasks.get("isolated-task-0")
    large_goal = " ".join(f"large-context-item-{index:04d}" for index in range(1100))
    task = app.agent_tasks.create(
        GoalContract(goal=large_goal, acceptance_criteria=()),
        ScopeContext(repository_id=original.context.repository_id, session_id="large-context-session"),
        repo_root=str(roots[0]),
    )

    async def request_and_recover():
        async with create_connected_server_and_client_session(
            mcp_server.mcp, read_timeout_seconds=timedelta(seconds=20),
        ) as session:
            for profile in ("compact", "minimal"):
                for budget in (3200, 1024, 128):
                    result = await session.call_tool("local_ai_coord", {
                        "action": "context_compile", "root": str(roots[0]), "task_id": task.task_id,
                        "session_id": "large-context-session",
                        "max_response_tokens": budget, "response_profile": profile,
                    })
                    assert not result.isError, result
                    value = _value(result)
                    wire = {"content": [item.model_dump(mode="json", exclude_none=True) for item in result.content],
                            "structuredContent": result.structuredContent, "isError": result.isError}
                    if result.structuredContent is None:
                        wire.pop("structuredContent")
                    assert json_tokens(wire) <= budget, value
                    assert value["response_budget"]["requested_tokens"] == budget
                    artifact_id = value.get("task_context_artifact_id")
                    if not artifact_id:
                        artifact_id = (value.get("task_context") or {}).get("artifact_id")
                    if budget == 128 and not artifact_id:
                        assert value["success"] is False
                        assert value["error"] == "max_response_tokens too small"
                        assert value["next_action"] == "request_larger_response_budget"
                        assert value["response_budget"]["rejected"] is True
                        continue
                    if not isinstance(artifact_id, str) or not artifact_id:
                        pytest.fail(f"{profile}/{budget}: {json.dumps(value)}", pytrace=False)
                    pages = []
                    offset = 0
                    for _ in range(1000):
                        recovered = await session.call_tool("local_ai_artifact", {
                            "action": "get", "artifact_id": artifact_id, "offset": offset,
                            "max_chars": 2800, "max_response_tokens": 3200, "response_profile": "compact",
                        })
                        assert not recovered.isError, recovered
                        page = _value(recovered)
                        assert page["success"] is True, page
                        pages.append(page["text"])
                        if page["next_offset"] is None:
                            break
                        assert page["next_offset"] > offset
                        offset = page["next_offset"]
                    else:
                        pytest.fail("context artifact recovery exceeded bounded pages")
                    stored = json.loads("".join(pages))
                    assert stored["task_id"] == task.task_id
                    assert stored["root"] == str(roots[0].resolve())
                    assert stored["session_id"] == "large-context-session"
                    assert stored["success"] is True and stored["complete"] is True
                    assert stored["omitted_task_goal"] == f"Task Goal: {large_goal}\nCriteria: "
                    assert stored["truncated"] is True
                    assert stored["context_id"] and stored["etag"]

    asyncio.run(request_and_recover())
