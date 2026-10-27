from __future__ import annotations

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.token_accounting import json_tokens


@pytest.fixture(autouse=True)
def isolate_budget_tests_from_background_transport(monkeypatch):
    # CLIENT.post spies cover foreground dispatch, not asynchronous telemetry.
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda event: None)


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
        mcp_server.local_ai_coord,
        mcp_server.local_ai_artifact,
        mcp_server.local_ai_work,
    ):
        names = set(__import__("inspect").signature(tool).parameters)
        assert {"max_response_tokens", "response_profile", "reuse_key"} <= names






def test_telemetry_status_projection_keeps_slow_paths_and_omits_bulk_report() -> None:
    report = {
        "success": True,
        "summary": {
            "events": 10, "avg_queue_wait_ms": 700, "failure_rate": 0.1, "raw": "drop",
            "scope": "process", "summary_cache_stale": True,
            "writer": {
                "scope": "current_process", "process_started_at": 1000.0,
                "snapshot_end_at": 1010.0, "interval_seconds": 10.0,
                "attempted": 8, "accepted": 7, "rejected_overflow": 1,
                "lost_after_acceptance": 0, "processed": 7, "written": 7,
                "pending": 0, "dropped": 1, "writer_errors": 0,
                "writer_error_attempts": 0, "writer_errors_unit": "raw explanation",
                "accounting_balanced": True, "activity_observed": True,
                "accepted_rate": 0.875, "overflow_rejection_rate": 0.125,
                "post_acceptance_loss_rate": 0.0, "written_rate": 1.0,
                "pending_rate": None, "writer_error_attempts_unit": "untrusted text",
            },
        },
        "queue": {"p95_queue_age_ms": 900},
        "hotspots": [{"signal": "queue_wait"}],
        "by_operation": [{"action": "context", "avg_ms": 1200}],
        "error_fingerprints": [{"error_type": "timeout"}],
        "detail": {"omitted_sections": [
            "writer_activity_unobserved", "writer_accounting_unbalanced", "cached_summary_data",
        ]},
        "daily": [{"day": "bulk"}] * 100,
        "provider_token_usage": [{"prompt": "must not pass"}] * 100,
    }

    result = mcp_server._telemetry_status_projection({"success": True, "report": report})

    assert result["summary"]["events"] == 10
    assert result["summary"]["avg_queue_wait_ms"] == 700
    assert result["summary"]["failure_rate"] == 0.1
    assert "raw" not in result["summary"]
    assert result["queue"]["p95_queue_age_ms"] == 900
    assert result["by_operation"][0]["action"] == "context"
    assert result["summary"]["scope"] == "process"
    assert result["summary"]["summary_cache_stale"] is True
    assert result["summary"]["writer"] == {
        "scope": "current_process", "process_started_at": 1000.0,
        "snapshot_end_at": 1010.0, "interval_seconds": 10.0,
        "attempted": 8, "accepted": 7, "rejected_overflow": 1,
        "lost_after_acceptance": 0, "processed": 7, "written": 7,
        "pending": 0, "dropped": 1, "writer_errors": 0,
        "writer_error_attempts": 0, "writer_error_attempts_unit": "attempts",
        "accounting_balanced": True, "activity_observed": True,
        "accepted_rate": 0.875, "overflow_rejection_rate": 0.125,
        "post_acceptance_loss_rate": 0.0, "written_rate": 1.0,
        "pending_rate": None,
    }
    assert "writer_errors_unit" not in result["summary"]["writer"]
    assert result["detail"]["omitted_sections"] == [
        "writer_activity_unobserved", "writer_accounting_unbalanced", "cached_summary_data",
    ]
    assert "daily" not in result
    assert "provider_token_usage" not in result


def test_telemetry_writer_projection_rejects_nonfinite_and_absent_rates() -> None:
    result = mcp_server._telemetry_status_projection({
        "success": True,
        "summary": {"writer": {
            "accepted_rate": float("nan"), "written_rate": float("inf"),
            "pending_rate": None, "attempted": -1,
        }},
    })

    assert result["summary"]["writer"] == {"pending_rate": None}


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


def test_task_memory_delta_marks_unchanged_without_dropping_adoption_context(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "RESPONSE_BUDGET_ENABLED", True)
    memory = {
        "schema_version": 2,
        "context": {"root": "C:/fixture", "coordination_id": "repo-1", "task_id": "task-1"},
        "instruction": "Use scoped memory.",
        "items": [{"id": "mem-1", "content": "fixture fact"}],
        "warnings": [],
        "estimated_tokens": 8,
    }
    response = {
        "success": True,
        "request_id": "request-1",
        "task_id": "task-1",
        "task": {"task_id": "task-1", "status": "active", "checkpoint": {"state_data": {"memory_context": memory}}},
    }
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(_options(
        tool="local_ai_coord", action="task_get", response_profile="delta",
        reuse_key="task-get-unchanged", max_response_tokens=2000,
    ))
    try:
        first = mcp_server._compact(response, "task_memory")
        second = mcp_server._compact({**response, "request_id": "request-2"}, "task_memory")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)

    assert first.get("unchanged") is not True
    assert second["unchanged"] is True
    assert second["request_id"] == "request-2"
    assert second["task_id"] == "task-1"
    assert second["task"]["checkpoint"]["state_data"]["memory_context"] == memory


def test_coord_delta_marks_unchanged_and_retains_request_identity(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "RESPONSE_BUDGET_ENABLED", True)
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(_options(
        tool="local_ai_coord", action="task_get", response_profile="delta",
        reuse_key="coord-get-unchanged", max_response_tokens=2000,
    ))
    try:
        first = mcp_server._compact({"success": True, "task_id": "task-1", "status": "active", "request_id": "r1"}, "coord")
        second = mcp_server._compact({"success": True, "task_id": "task-1", "status": "active", "request_id": "r2"}, "coord")
        changed = mcp_server._compact({"success": True, "task_id": "task-1", "status": "done", "request_id": "r3"}, "coord")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)

    assert first.get("unchanged") is not True
    assert second["unchanged"] is True
    assert second["request_id"] == "r2"
    assert second["task_id"] == "task-1"
    assert changed.get("unchanged") is not True
    assert changed["status"] == "done"


def test_delta_pointer_keeps_unchanged_marker_with_tight_budget(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_REUSE_DIGESTS", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "_REUSE_VALUES", mcp_server.OrderedDict())
    monkeypatch.setattr(mcp_server, "RESPONSE_BUDGET_ENABLED", True)
    value = {"success": True, "artifact_id": "artifact-1", "results": [
        {"path": f"src/{i}.py", "text": "x" * 500} for i in range(30)
    ]}
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set(_options(response_profile="delta"))
    try:
        mcp_server._compact(value, "search")
        repeated = mcp_server._compact(value, "search")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)
    assert repeated["unchanged"] is True
    assert repeated["artifact_id"] == "artifact-1"
    public = {key: value for key, value in repeated.items() if key != "_token_accounting"}
    assert json_tokens(public) <= 260
