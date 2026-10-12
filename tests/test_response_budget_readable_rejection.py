from local_ai_hub.response_budget import _budget_rejection
from local_ai_hub.token_accounting import json_tokens


def test_large_protected_envelope_does_not_reduce_budget_error_to_one_character():
    protected = tuple(f"diagnostic_{index:02d}" for index in range(100))
    source = {
        "success": False,
        "error": "max_response_tokens too small",
        "terminal": True,
        "retryable": False,
        **{key: {str(n): "payload" * 100 for n in range(20)} for key in protected},
    }
    result = _budget_rejection(
        requested=6400, original=20000, source=source,
        protected_keys=("error", "terminal", "retryable", *protected),
    )
    assert result["error"] == source["error"]
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["response_budget"]["rejected"] is True
    assert result["response_budget"]["returned_tokens"] == json_tokens(result)
    assert json_tokens(result) <= 6400


def test_budget_rejection_retains_readable_error_and_original_protocol_at_minimum_cap():
    error = "root cause: command failed because the upstream service rejected the request. " * 24
    protected = tuple(f"diagnostic_{index:02d}" for index in range(32))
    source = {
        "success": False,
        "error": error,
        "status": "error",
        "status_code": 503,
        "terminal": True,
        "retryable": False,
        "outcome_unknown": True,
        "in_progress": False,
        "request_id": "request-7f1a",
        **{key: "oversized diagnostic payload " * 200 for key in protected},
    }

    result = _budget_rejection(
        requested=128,
        original=7582,
        source=source,
        protected_keys=(
            "error", "status", "status_code", "terminal", "retryable",
            "outcome_unknown", "in_progress", "request_id", *protected,
        ),
    )

    assert result["success"] is False
    assert result["error"].startswith("root cause:")
    assert 12 < len(result["error"]) <= 512
    assert result["status"] == source["status"]
    assert result["status_code"] == source["status_code"]
    assert result["terminal"] is source["terminal"]
    assert result["retryable"] is source["retryable"]
    assert result["outcome_unknown"] is source["outcome_unknown"]
    assert result["in_progress"] is source["in_progress"]
    assert result["request_id"] == source["request_id"]
    assert result["response_budget"]["returned_tokens"] == json_tokens(result)
    assert result["response_budget"]["requested_tokens"] == 128
    assert result["response_budget"]["rejected"] is True
    assert json_tokens(result) <= 128


def test_budget_rejection_supplies_readable_error_when_source_error_is_empty_or_absent():
    protected = tuple(f"diagnostic_{index:02d}" for index in range(32))
    protected_keys = ("error", "status", "outcome_unknown", "request_id", *protected)

    for source_error in ("", None):
        source = {
            "success": False,
            "status": "error",
            "outcome_unknown": True,
            "request_id": "request-empty-error",
            **{key: "oversized diagnostic payload " * 200 for key in protected},
        }
        if source_error is not None:
            source["error"] = source_error

        result = _budget_rejection(
            requested=128,
            original=7582,
            source=source,
            protected_keys=protected_keys,
        )

        assert result["error"] == "max_response_tokens too small"
        assert result["outcome_unknown"] is True
        assert result["request_id"] == source["request_id"]
        assert result["response_budget"]["requested_tokens"] == 128
        assert result["response_budget"]["rejected"] is True
        assert result["response_budget"]["returned_tokens"] == json_tokens(result)
        assert json_tokens(result) <= 128


def test_minimum_budget_keeps_decision_flags_when_long_ids_and_evidence_do_not_fit():
    request_id = "r" * 160
    execution_id = "e" * 160
    source = {
        "success": False,
        "error": "root cause: owner could not reconcile the failed execution and receipt.",
        "terminal": True,
        "retryable": False,
        "outcome_unknown": True,
        "in_progress": True,
        "request_id": request_id,
        "execution_id": execution_id,
        "evidence_ids": ["E" * 160],
        "context_id": "context-identity-" * 30,
        **{f"diagnostic_{index:02d}": "oversized payload " * 200 for index in range(32)},
    }

    result = _budget_rejection(
        requested=128,
        original=7582,
        source=source,
        protected_keys=(
            "error", "terminal", "retryable", "outcome_unknown", "in_progress",
            "request_id", "execution_id", "evidence_ids", "context_id",
            *(f"diagnostic_{index:02d}" for index in range(32)),
        ),
    )

    assert result["success"] is False
    assert len(result["error"]) >= 12
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["outcome_unknown"] is True
    assert result["in_progress"] is True
    assert result.get("request_id") in (None, request_id)
    assert result.get("execution_id") in (None, execution_id)
    assert result["response_budget"]["requested_tokens"] == 128
    assert result["response_budget"]["rejected"] is True
    assert result["response_budget"]["returned_tokens"] == json_tokens(result)
    assert json_tokens(result) <= 128
