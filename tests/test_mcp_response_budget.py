from __future__ import annotations

from local_ai_hub import mcp_server
from local_ai_hub.token_accounting import json_tokens


def _options(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "max_response_tokens": 260,
        "response_profile": "compact",
        "reuse_key": "repo:search:test",
        "tool": "local_ai_repo",
    }
    value.update(overrides)
    return value


def test_existing_tools_expose_response_budget_options() -> None:
    for tool in (
        mcp_server.local_ai_status,
        mcp_server.local_ai_task,
        mcp_server.local_ai_repo,
        mcp_server.local_ai_rag,
        mcp_server.local_ai_command,
        mcp_server.local_ai_coord,
        mcp_server.local_ai_artifact,
        mcp_server.local_ai_work,
    ):
        names = set(__import__("inspect").signature(tool).parameters)
        assert {"max_response_tokens", "response_profile", "reuse_key"} <= names


def test_command_rollback_scope_reaches_api_payload(monkeypatch, tmp_path) -> None:
    captured_posts: list[tuple[str, dict[str, object], float]] = []

    def fake_post(path: str, payload: dict[str, object], timeout: float):
        captured_posts.append((path, payload, timeout))
        return {"success": True}

    monkeypatch.setattr(mcp_server.FEATURES, "commands", True)
    monkeypatch.setattr(mcp_server, "_client_root", lambda value: value)
    monkeypatch.setattr(mcp_server, "_timeout", lambda _kind: 60)
    monkeypatch.setattr(mcp_server.CLIENT, "post", fake_post)
    monkeypatch.setattr(mcp_server, "_compact", lambda value, _tool: value)

    result = mcp_server.local_ai_command(
        action="run",
        command="pytest -q",
        cwd=str(tmp_path),
        rollback_on_failure=True,
        paths=["owned.py", "new-output.txt"],
    )

    assert result == {"success": True}
    command_posts = [(payload, timeout) for path, payload, timeout in captured_posts if path == "/api/command"]
    assert len(command_posts) == 1
    assert command_posts[0][0]["paths"] == ["owned.py", "new-output.txt"]


def test_command_rollback_rejects_non_run_action_before_dispatch(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server.FEATURES, "commands", True)

    result = mcp_server.local_ai_command(
        action="speculative_lint",
        rollback_on_failure=True,
        paths=["owned.py"],
    )

    assert result["rollback_unsupported_action"] is True


def test_telemetry_status_projection_keeps_slow_paths_and_omits_bulk_report() -> None:
    report = {
        "success": True,
        "summary": {"events": 10, "avg_queue_wait_ms": 700, "failure_rate": 0.1, "raw": "drop"},
        "queue": {"p95_queue_age_ms": 900},
        "hotspots": [{"signal": "queue_wait"}],
        "by_operation": [{"action": "context", "avg_ms": 1200}],
        "error_fingerprints": [{"error_type": "timeout"}],
        "daily": [{"day": "bulk"}] * 100,
        "provider_token_usage": [{"prompt": "must not pass"}] * 100,
    }

    result = mcp_server._telemetry_status_projection({"success": True, "report": report})

    assert result["summary"] == {"events": 10, "avg_queue_wait_ms": 700, "failure_rate": 0.1}
    assert result["queue"]["p95_queue_age_ms"] == 900
    assert result["by_operation"][0]["action"] == "context"
    assert "daily" not in result
    assert "provider_token_usage" not in result


def test_context_projection_keeps_actual_context_text_after_budget() -> None:
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(
        {"max_response_tokens": 220, "response_profile": "compact", "reuse_key": "ctx-budget", "tool": "local_ai_repo"}
    )
    try:
        result = mcp_server._context_pack_projection(
            {
                "success": True,
                "guarded": True,
                "context": "deterministic facts about logs",
                "context_source": "deterministic-fast",
                "contract": {"goal": "inspect logs"},
                "context_pack": {"context_id": "ctx-1", "evidence": [{"evidence_id": "E1"}]},
                "evidence_ids": ["E1"],
                "repo_revision": "rev-1",
            }
        )
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)

    assert result["context"] == "deterministic facts about logs"
    assert result["contract"]["goal"] == "inspect logs"
    assert result["evidence_ids"] == ["E1"]
    assert json_tokens(result) <= 220


def test_context_projection_budget_rejection_keeps_bounded_identity_and_citation() -> None:
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(
        {"max_response_tokens": 220, "response_profile": "compact", "reuse_key": "ctx-citation", "tool": "local_ai_repo"}
    )
    try:
        result = mcp_server._context_pack_projection(
            {
                "success": True,
                "guarded": True,
                "adaptive_context_pack": {
                    "context_id": "ctx-123",
                    "repo_revision": "rev-7",
                    "changed_paths": [f"src/components/context-budget/evidence-{index:02d}.py" for index in range(32)],
                    "evidence": [
                        {
                            "evidence_id": "E123",
                            "path": "src/main.py",
                            "start_line": 4,
                            "end_line": 6,
                            "source": "deterministic",
                            "content": "private detail " * 500,
                        }
                        for _ in range(12)
                    ],
                    "warnings": [
                        {"code": "scope_drift", "message": "large warning " * 500}
                        for _ in range(12)
                    ],
                },
            }
        )
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)

    assert json_tokens(result) <= 220
    assert result["response_budget"]["original_tokens"] > 220
    assert result["response_budget"]["requested_tokens"] == 220
    assert result["response_budget"]["returned_tokens"] == json_tokens(result)
    assert result["context_id"] == "ctx-123"
    assert result["repo_revision"] == "rev-7"
    assert result["evidence_ids"] == ["E123"]
    assert result["adaptive_context_pack"]["evidence"][0] == {
        "evidence_id": "E123",
        "path": "src/main.py",
        "start_line": 4,
        "end_line": 6,
        "source": "deterministic",
    }
    assert "content" not in repr(result["adaptive_context_pack"])


def test_context_projection_preserves_incomplete_degraded_task_context() -> None:
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(
        {"max_response_tokens": 512, "response_profile": "compact", "reuse_key": "ctx-partial", "tool": "local_ai_repo"}
    )
    try:
        result = mcp_server._context_pack_projection({
            "success": False,
            "guarded": True,
            "status_code": 503,
            "terminal": False,
            "retryable": True,
            "stop_code": "context_task_context_incomplete",
            "degraded": True,
            "degraded_reason": "repository_context_unavailable",
            "task_context": {
                "success": False,
                "complete": False,
                "partial": True,
                "text": "Agent OS checkpoint remains available",
                "repository": {
                    "success": False,
                    "degraded": True,
                    "degraded_reason": "repository_context_unavailable",
                },
            },
        })
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)

    assert result["success"] is False
    assert result["status_code"] == 503
    assert result["retryable"] is True
    assert result["stop_code"] == "context_task_context_incomplete"
    assert result["task_context"]["complete"] is False
    assert "Agent OS checkpoint remains available" in result["task_context"]["text"]
    assert result["task_context"]["repository"]["degraded"] is True
    assert json_tokens(result) <= 512

def test_mcp_compact_applies_aggregate_budget(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", mcp_server.OrderedDict())
    value = {
        "success": True,
        "summary": "summary",
        "artifact_id": "artifact-1",
        "results": [{"path": f"src/{i}.py", "text": "x" * 500} for i in range(30)],
    }
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(_options())
    try:
        result = mcp_server._compact(value, "search")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)

    assert json_tokens(result) <= 300
    assert result["artifact_id"] == "artifact-1"
    assert result["response_budget"]["truncated"] is True


def test_async_job_status_compaction_preserves_lifecycle_fields(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", mcp_server.OrderedDict())
    value = {
        "success": True,
        "job_id": "job-123",
        "state": "completed",
        "artifact_id": "artifact-123",
        "cancel_requested": False,
        "wait_timeout_seconds": 0.0,
        "results": [{"text": "x" * 2000} for _ in range(20)],
    }
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(_options(
        max_response_tokens=180, tool="local_ai_task", reuse_key="async-status-budget",
    ))
    try:
        result = mcp_server._compact(value, "status")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)

    assert result["job_id"] == "job-123"
    assert result["state"] == "completed"
    assert result["artifact_id"] == "artifact-123"
    assert result["cancel_requested"] is False
    assert result["wait_timeout_seconds"] == 0.0


def test_mcp_compact_reuses_unchanged_payload(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", mcp_server.OrderedDict())
    value = {
        "success": True,
        "summary": "summary",
        "artifact_id": "artifact-1",
        "results": [{"path": f"src/{i}.py", "text": "x" * 500} for i in range(30)],
    }
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(_options())
    try:
        first = mcp_server._compact(value, "search")
        second = mcp_server._compact(value, "search")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)

    assert first["response_budget"]["truncated"] is True
    assert second["reused"] is True
    assert "results" not in second


def test_mcp_compact_delta_profile_returns_changed_payload_only(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", mcp_server.OrderedDict())
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(_options(response_profile="delta"))
    try:
        mcp_server._compact({"success": True, "summary": "old", "items": ["a"]}, "search")
        result = mcp_server._compact({"success": True, "summary": "new", "items": ["b"]}, "search")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)

    assert result["success"] is True
    assert result["delta"]["changed"] == {"summary": "new", "items": ["b"]}
    assert result["result_id"]


def test_mcp_compact_rejects_subminimum_budget_without_exceeding_request() -> None:
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(_options(max_response_tokens=64))
    try:
        result = mcp_server._compact({"success": True, "summary": "too small"}, "search")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)

    assert result["success"] is False
    assert result["response_budget"]["requested_tokens"] == 64
    assert json_tokens(result) <= 64
