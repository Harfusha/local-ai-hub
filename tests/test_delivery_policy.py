import re
from pathlib import Path

from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.delivery import decide_delivery
from local_ai_hub.telemetry import TelemetryStore
from local_ai_hub import http_server
from local_ai_hub.mcp_server import _task_delivery_contract


def test_async_delivery_docs_match_supported_actions_and_cold_start_rules():
    docs_path = Path(__file__).resolve().parents[1] / "docs" / "MCP_AND_AGENTS.md"
    docs = docs_path.read_text(encoding="utf-8")

    action_line = re.search(r"^Durable async actions: (.+)$", docs, re.MULTILINE)
    assert action_line is not None
    actions = re.findall(r"`([^`]+)`", action_line.group(1))
    assert actions == sorted(AsyncJobManager.ACTIONS)
    assert len(actions) == len(set(actions))
    assert "at least ten observations" in docs
    assert "sparse history stays inline" in docs
    assert "fewer than 5 telemetry samples" in docs
    assert "`cold_start_review_diff`" in docs


def test_install_and_update_prompts_cover_async_and_conversation_contracts():
    root = Path(__file__).resolve().parents[1]
    prompt_docs = [
        (root / "docs" / "INSTALL_PROMPT.md").read_text(encoding="utf-8"),
        (root / "docs" / "UPDATE_PROMPT.md").read_text(encoding="utf-8"),
    ]

    for docs in prompt_docs:
        for action in AsyncJobManager.ACTIONS:
            assert f"`{action}`" in docs
        for path in (
            "/api/delegate",
            "/api/reason",
            "/api/review",
            "/api/review/diff",
            "/api/second-opinion",
            "/api/compress",
            "/api/route",
            "/api/delegate/batch",
        ):
            assert f"`{path}`" in docs
        for phrase in (
            "`POST /api/async-jobs`",
            '`action="submit"`',
            '`action="status"|"wait"|"result"|"cancel"`',
            "`job_action`",
            "`request_id`",
            "`job_id`",
            "`timeout_seconds`",
            "`HubClient.submit_async_job`",
            "`cold_start_review_diff`",
            "fewer than five telemetry samples",
            "at least ten",
            "sparse history stays inline",
            "`review.max_queue_age_ms`",
            "`/api/conversations/continue`",
            "local_ai_task(action=\"continue\"",
            "conversation_id=..., task=..., context=...",
            "HubClient.continue_conversation",
            "HubClient has no dedicated start helper",
            "`POST /api/delegate`",
            "`POST /api/reason`",
            "tenant-scoped",
            "12 user turns",
            "56,000",
            "900 seconds",
            "1,800 seconds",
            "artifact_id",
            "expires_at",
            "259,200 seconds",
            "wait_timeout_seconds",
            "cancel_requested=true",
            "restart",
        ):
            assert phrase in docs


def test_mcp_task_description_exposes_async_and_conversation_contracts():
    contract = _task_delivery_contract()
    for phrase in (
        "`POST /api/async-jobs`",
        "`local_ai_task(action=submit|status|wait|result|cancel, ...)`",
        "`HubClient.submit_async_job`",
        "job_action",
        "request_id",
        "job_id",
        "timeout_seconds",
        "`/api/delegate/batch`",
        "`delivery=auto`",
        "`review.max_queue_age_ms`",
        "`cold_start_review_diff`",
        "`speculative_lint`",
        "`X-LocalAI-Request-ID`",
        "tenant-scoped",
        "12 turns",
        "`model_conversations.max_prompt_tokens`",
        "default 56,000",
        "900/1,800 seconds",
        "capacity 1,000",
        "lost on restart",
        "conversation_id=..., task=..., context=...",
        "artifact_id",
        "expires_at",
        "259,200 seconds",
        "wait_timeout_seconds",
        "cancel_requested=true",
    ):
        assert phrase in contract


def test_auto_delivery_uses_async_when_observed_p95_exceeds_budget():
    decision = decide_delivery("auto", latency_budget_ms=5_000, observed_p95_ms=5_001, samples=20)

    assert decision == {
        "mode": "async",
        "reason": "p95_latency_budget_exceeded",
        "observed_p95_ms": 5_001.0,
        "samples": 20,
    }


def test_auto_delivery_stays_sync_without_enough_history():
    decision = decide_delivery("auto", latency_budget_ms=5_000, observed_p95_ms=9_000, samples=3)

    assert decision["mode"] == "sync"
    assert decision["reason"] == "insufficient_latency_history"


def test_sync_is_default_even_when_tail_is_high():
    decision = decide_delivery("sync", latency_budget_ms=1, observed_p95_ms=9_000, samples=100)

    assert decision["mode"] == "sync"
    assert decision["reason"] == "sync_requested"


def test_http_latency_estimate_uses_bounded_endpoint_history(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_http(action="/api/reason", duration_ms=100)
        store.record_http(action="/api/reason", duration_ms=200)
        store.flush(1)
        assert store.http_latency_estimate("/api/reason") == {"samples": 2, "p95_duration_ms": 200.0}
    finally:
        store.close()


def test_async_delivery_maps_reason_payload_to_the_existing_job_contract(monkeypatch):
    submitted = {}

    class _Telemetry:
        def http_latency_estimate(self, _action):
            return {"samples": 12, "p95_duration_ms": 9_000}

    class _Jobs:
        def submit(self, tenant, action, payload):
            submitted.update(tenant=tenant, action=action, payload=payload)
            return {"success": True, "job_id": "job-1", "state": "queued"}

    class _App:
        telemetry = _Telemetry()
        async_jobs = _Jobs()

    monkeypatch.setattr(http_server, "APP", _App())
    handler = object.__new__(http_server.Handler)
    status, response = handler._async_delivery(
        "/api/reason", {"delivery": "auto", "latency_budget_ms": 5_000, "problem": "find cause", "context": "facts"}, "tenant-a"
    )

    assert status == 200
    assert response["delivery"]["reason"] == "p95_latency_budget_exceeded"
    assert submitted == {"tenant": "tenant-a", "action": "reason", "payload": {"problem": "find cause", "context": "facts", "task": "find cause"}}


def test_async_delivery_maps_review_diff_to_durable_review_job(monkeypatch):
    submitted = {}

    class _Telemetry:
        def http_latency_estimate(self, _action):
            return {"samples": 20, "p95_duration_ms": 70_000}

    class _Jobs:
        def submit(self, tenant, action, payload):
            submitted.update(tenant=tenant, action=action, payload=payload)
            return {"success": True, "job_id": "job-review", "state": "queued"}

    class _App:
        telemetry = _Telemetry()
        async_jobs = _Jobs()

    monkeypatch.setattr(http_server, "APP", _App())
    handler = object.__new__(http_server.Handler)
    status, response = handler._async_delivery(
        "/api/review/diff",
        {"delivery": "auto", "latency_budget_ms": 5_000, "instructions": "find defects", "context": "large diff"},
        "tenant-a",
    )

    assert status == 200
    assert response["job_id"] == "job-review"
    assert submitted == {
        "tenant": "tenant-a",
        "action": "review_diff",
        "payload": {"instructions": "find defects", "context": "large diff", "_async_job": True},
    }


def test_cold_start_review_diff_auto_delivery_is_async(monkeypatch):
    submitted = {}

    class _Telemetry:
        def http_latency_estimate(self, _action):
            return {"samples": 0, "p95_duration_ms": 0}

    class _Jobs:
        def submit(self, tenant, action, payload):
            submitted.update(tenant=tenant, action=action, payload=payload)
            return {"success": True, "job_id": "job-cold-review", "state": "queued"}

    class _App:
        telemetry = _Telemetry()
        async_jobs = _Jobs()

    monkeypatch.setattr(http_server, "APP", _App())
    handler = object.__new__(http_server.Handler)
    status, response = handler._async_delivery(
        "/api/review/diff",
        {"delivery": "auto", "latency_budget_ms": 30_000, "instructions": "find defects"},
        "tenant-a",
    )

    assert status == 200
    assert response["job_id"] == "job-cold-review"
    assert submitted["action"] == "review_diff"
