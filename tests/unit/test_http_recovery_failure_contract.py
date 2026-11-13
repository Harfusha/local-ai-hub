import sqlite3
from types import SimpleNamespace

from local_ai_hub import http_server


def test_unavailable_recovery_journal_is_terminal_and_not_retryable():
    response_factory = getattr(http_server, "_recovery_claim_failure_response", None)
    assert callable(response_factory), "recovery claim failures need a typed response contract"

    response = response_factory(
        SimpleNamespace(_journal_unavailable=True),
        sqlite3.DatabaseError("private internal detail"),
    )

    assert response["status_code"] == 503
    assert response["error_code"] == "request_journal_unavailable"
    assert response["error"] == "request was not dispatched because recovery journal is unavailable"
    assert response["terminal"] is True
    assert response["retryable"] is False
    assert response["outcome_unknown"] is False
    assert "private internal detail" not in str(response)


def test_transient_recovery_journal_lock_is_retryable_with_backoff():
    response_factory = getattr(http_server, "_recovery_claim_failure_response", None)
    assert callable(response_factory), "recovery claim failures need a typed response contract"

    response = response_factory(
        SimpleNamespace(_journal_unavailable=False),
        sqlite3.OperationalError("database is locked"),
    )

    assert response["status_code"] == 503
    assert response["error_code"] == "request_journal_busy"
    assert response["terminal"] is False
    assert response["retryable"] is True
    assert response["retry_after_seconds"] == 1
    assert response["outcome_unknown"] is False


def test_invalid_recovery_claim_is_terminal_without_internal_details():
    response_factory = getattr(http_server, "_recovery_claim_failure_response", None)
    assert callable(response_factory), "recovery claim failures need a typed response contract"

    response = response_factory(
        SimpleNamespace(_journal_unavailable=False),
        invalid_claim=True,
    )

    assert response["status_code"] == 503
    assert response["error_code"] == "request_journal_invalid"
    assert response["terminal"] is True
    assert response["retryable"] is False
    assert response["outcome_unknown"] is False
