from __future__ import annotations

import sqlite3

import pytest

from local_ai_hub.commands import CommandBroker


def test_rollback_reports_suppressed_sqlite_cache_delete_failure(
    tmp_path, monkeypatch
) -> None:
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}},
        artifacts=None,
        repo_state=None,
    )

    def busy_connect():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(broker.success_cache.l2, "_connect", busy_connect)
    result: dict[str, object] = {}
    broker._mark_rollback_outcome_unknown(
        result,
        command_key="command-key",
        attempt_key="attempt-key",
        error=OSError("rollback failed"),
    )

    assert result["outcome_unknown"] is True
    assert result.get("cache_invalidation_failed") is True
    assert result.get("cache_invalidation_errors") == ["database is locked"]


def test_failed_sqlite_delete_does_not_serve_stale_cached_value(
    tmp_path, monkeypatch
) -> None:
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}},
        artifacts=None,
        repo_state=None,
    )
    cache = broker.success_cache
    cache.set("command-key", {"success": True, "stdout": "pre-rollback"})
    original_connect = cache.l2._connect

    def always_busy():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache.l2, "_connect", always_busy)
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        cache.delete("command-key")
    monkeypatch.setattr(cache.l2, "_connect", original_connect)

    assert cache.get("command-key") is None


def test_incident_capture_failure_is_reported_without_masking_unknown_outcome(
    tmp_path,
) -> None:
    broker = CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}},
        artifacts=None,
        repo_state=None,
    )

    class FailingIncidentStore:
        def capture(self, outcome):
            raise sqlite3.OperationalError("database is locked")

    broker.set_incident_store(FailingIncidentStore())
    result: dict[str, object] = {
        "outcome_unknown": True,
        "incident_required": True,
    }
    broker._capture_rollback_unknown_incident(
        result,
        command="unit-test",
    )

    assert result["outcome_unknown"] is True
    assert result["incident_required"] is True
    assert result["incident_recording_failed"] is True
    assert result["incident_recording_error_type"] == "OperationalError"
    assert "database is locked" not in str(result)
