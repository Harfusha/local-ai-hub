from __future__ import annotations

from local_ai_hub.context_ledger import ContextLedger


def test_ledger_keeps_bounded_metadata_only_summary() -> None:
    ledger = ContextLedger(max_entries=2)
    ledger.record(
        tool="local_ai_repo",
        operation="search",
        request_tokens=100,
        response_tokens=40,
        saved_tokens=60,
        cache_outcome="miss",
        result_id="r1",
        session_id="session-a",
    )
    ledger.record(
        tool="local_ai_command",
        operation="run",
        request_tokens=80,
        response_tokens=20,
        saved_tokens=10,
        cache_outcome="hit",
        result_id="r2",
        session_id="session-a",
    )
    ledger.record(
        tool="local_ai_artifact",
        operation="slice",
        request_tokens=30,
        response_tokens=10,
        saved_tokens=5,
        cache_outcome="miss",
        result_id="r3",
        session_id="session-a",
    )

    snapshot = ledger.snapshot()
    assert snapshot["entries"] == 2
    assert snapshot["totals"]["request_tokens"] == 110
    assert snapshot["totals"]["response_tokens"] == 30
    assert snapshot["last"]["result_id"] == "r3"
    assert "session-a" not in str(snapshot["last"].get("prompt", ""))
    assert "source" not in str(snapshot).lower()


def test_ledger_adaptive_profile_drops_repeated_calls_to_minimal() -> None:
    ledger = ContextLedger(max_entries=8)
    for index in range(4):
        ledger.record(
            tool="local_ai_repo",
            operation="search",
            request_tokens=10,
            response_tokens=100,
            saved_tokens=20,
            cache_outcome="hit",
            result_id=f"r{index}",
        )
    assert ledger.adaptive_profile("compact") == "minimal"
