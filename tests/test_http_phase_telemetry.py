import pytest

from local_ai_hub.http_server import Handler, RequestBodyError, _journal_outcome_success, _response_phase_latency
from local_ai_hub.token_accounting import finalize_tool_accounting


def test_response_phase_latency_reads_only_nonnegative_latency_metadata():
    assert _response_phase_latency({"latency": {"queue_wait_ms": 12.5, "service_ms": -1}}) == {
        "queue_wait_ms": 12.5,
        "service_ms": 0.0,
    }


def test_response_phase_latency_ignores_malformed_metadata():
    assert _response_phase_latency({"latency": "not-an-object"}) == {
        "queue_wait_ms": 0.0,
        "service_ms": 0.0,
    }


def test_terminal_client_result_is_not_stored_as_recovery_failure():
    assert _journal_outcome_success(200, {"success": False, "terminal": True}) is True


def test_tool_accounting_accepts_current_signed_event_shape():
    event = finalize_tool_accounting(
        tool_name="local_ai_repo",
        arguments={"action": "search", "root": "C:/repo"},
        response={"success": True},
        measured={"gross_cloud_tokens_avoided_est": 100},
    )
    event.update({"tenant": "tenant", "agent": "agent", "created_at": 1.0})

    assert len(event) > 24
    Handler._validate_payload("/api/telemetry/tool-accounting", {"events": [event]})


@pytest.mark.parametrize(("path", "payload", "field"), [
    ("/api/code/symbol", {"root": ".", "symbol": ""}, "symbol"),
    ("/api/code-intelligence/query", {"root": ".", "action": "callers", "query": ""}, "query"),
    ("/api/code/diagnostics", {"root": ".", "path": ""}, "path"),
])
def test_code_requests_reject_empty_required_inputs(path, payload, field):
    with pytest.raises(RequestBodyError, match=field):
        Handler._validate_payload(path, payload)
