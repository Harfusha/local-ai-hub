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
