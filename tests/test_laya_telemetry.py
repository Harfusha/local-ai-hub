import json
import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.telemetry import TelemetryStore


def _metadata(**changes):
    value = {
        "decision_id": "decision-1",
        "success": True,
        "mode": "shadow",
        "status": "success",
        "category": "context_source",
        "repository_id": "repo-1",
        "task_id": "task-1",
        "session_id": "session-1",
        "suggestion": "indexed",
        "reason_codes": ["EVIDENCE_SUFFICIENT"],
        "evidence_ids": ["evidence-1"],
        "model_estimate": True,
        "uncertainty": "UNCALIBRATED",
        "execution_verification": "NOT_VERIFIED",
    }
    value.update(changes)
    return value


def test_laya_decision_metadata_uses_existing_snapshot_table_without_raw_payload(tmp_path):
    store = TelemetryStore(tmp_path)
    try:
        assert store.record_laya_decision(
            _metadata(), repository_id="repo-1", task_id="task-1", session_id="session-1"
        ) is True
        assert store.flush(2.0) is True
        with closing(sqlite3.connect(store.path)) as con:
            row = con.execute(
                "SELECT name, metrics_json FROM snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row is not None
        assert row[0] == "laya_decision"
        saved = json.loads(row[1])
        assert saved["decision_id"] == "decision-1"
        assert saved["repository_id"] == "repo-1"
        assert saved["suggestion"] == "indexed"
        assert "raw_output" not in saved
    finally:
        store.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"raw_output": "private model output"},
        {"mode": "guarded"},
        {"category": "arbitrary"},
        {"suggestion": "stop"},
        {"execution_verification": "verified"},
        {"repository_id": "C:/private/path"},
        {"evidence_ids": ["evidence-1", "private prompt"]},
        {"reason_codes": [{"private": "payload"}]},
        {"evidence_ids": [["nested"]]},
        {"model": "unverified-model"},
    ],
)
def test_laya_decision_metadata_rejects_unknown_or_unsafe_values(tmp_path, changes):
    store = TelemetryStore(tmp_path)
    try:
        with pytest.raises(ValueError):
            store.record_laya_decision(
                _metadata(**changes), repository_id="repo-1", task_id="task-1", session_id="session-1"
            )
        assert store.flush(2.0) is True
        with closing(sqlite3.connect(store.path)) as con:
            count = con.execute(
                "SELECT COUNT(*) FROM snapshots WHERE name='laya_decision'"
            ).fetchone()[0]
        assert count == 0
    finally:
        store.close()


def test_laya_decision_metadata_requires_canonical_repository_and_session(tmp_path):
    store = TelemetryStore(tmp_path)
    try:
        with pytest.raises(ValueError):
            store.record_laya_decision(
                _metadata(session_id=""), repository_id="repo-1", task_id="task-1", session_id="session-1"
            )
        with pytest.raises(ValueError):
            store.record_laya_decision(
                _metadata(repository_id=""), repository_id="repo-1", task_id="task-1", session_id="session-1"
            )
        with pytest.raises(ValueError):
            store.record_laya_decision(
                _metadata(repository_id="other-repo"), repository_id="repo-1", task_id="task-1", session_id="session-1"
            )
        with pytest.raises(ValueError):
            store.record_laya_decision(
                _metadata(task_id="other-task"), repository_id="repo-1", task_id="task-1", session_id="session-1"
            )
        with pytest.raises(ValueError):
            store.record_laya_decision(
                _metadata(session_id="other-session"), repository_id="repo-1", task_id="task-1", session_id="session-1"
            )
    finally:
        store.close()


def test_laya_decision_metadata_returns_false_when_telemetry_is_disabled(tmp_path):
    store = TelemetryStore(tmp_path, enabled=False)
    try:
        assert store.record_laya_decision(
            _metadata(), repository_id="repo-1", task_id="task-1", session_id="session-1"
        ) is False
    finally:
        store.close()


def test_report_summarizes_laya_decisions_by_mode_category_and_status(tmp_path):
    store = TelemetryStore(tmp_path)
    try:
        store.record_laya_decision(
            _metadata(), repository_id="repo-1", task_id="task-1", session_id="session-1"
        )
        store.record_laya_decision(
            _metadata(
                decision_id="decision-2",
                mode="advisory",
                status="abstain",
                suggestion=None,
                reason_codes=["INSUFFICIENT_EVIDENCE"],
            ),
            repository_id="repo-1",
            task_id="task-1",
            session_id="session-1",
        )
        store.record_laya_decision(
            _metadata(
                decision_id="decision-3",
                status="error",
                success=False,
                suggestion=None,
                reason_codes=["TIMEOUT"],
                model_estimate=False,
                uncertainty="NOT_APPLICABLE",
            ),
            repository_id="repo-1",
            task_id="task-1",
            session_id="session-1",
        )
        store.record_laya_decision(
            _metadata(
                decision_id="decision-4",
                mode="advisory",
                status="skipped",
                success=False,
                suggestion=None,
                reason_codes=["DISABLED"],
                model_estimate=False,
                uncertainty="NOT_APPLICABLE",
            ),
            repository_id="repo-1",
            task_id="task-1",
            session_id="session-1",
        )

        report = store.report(days=1)

        summary = report["laya_decisions"]
        assert summary["records"] == 4
        assert summary["counts_by_mode"] == {"shadow": 2, "advisory": 2}
        assert summary["counts_by_status"] == {"abstain": 1, "error": 1, "skipped": 1, "success": 1}
        assert summary["by_mode"]["shadow"]["abstentions"] == 0
        assert summary["by_mode"]["shadow"]["errors"] == 1
        assert summary["by_mode"]["shadow"]["skips"] == 0
        assert summary["by_mode"]["shadow"]["counts_by_reason_code"] == {
            "EVIDENCE_SUFFICIENT": 1,
            "TIMEOUT": 1,
        }
        assert summary["by_mode"]["advisory"]["abstentions"] == 1
        assert summary["by_mode"]["advisory"]["errors"] == 0
        assert summary["by_mode"]["advisory"]["skips"] == 1
        assert summary["by_mode"]["advisory"]["counts_by_reason_code"] == {
            "DISABLED": 1,
            "INSUFFICIENT_EVIDENCE": 1,
        }
        for mode in ("shadow", "advisory"):
            mode_report = summary["by_mode"][mode]
            assert mode_report["coverage"] == {
                "available": False,
                "reason": "eligible_decision_count_not_recorded",
            }
            assert mode_report["latency_ms"] == {
                "available": False,
                "reason": "runtime_latency_not_recorded",
            }
            assert mode_report["backend"] == {
                "available": False,
                "reason": "runtime_backend_not_recorded",
            }
            assert mode_report["fallbacks"] == {
                "available": False,
                "reason": "fallback_outcome_not_recorded",
            }
    finally:
        store.close()


def test_report_marks_laya_process_scope_unavailable_without_process_identity(tmp_path):
    store = TelemetryStore(tmp_path)
    try:
        report = store.report(days=1, scope="process")

        assert report["laya_decisions"]["available"] is False
        assert report["laya_decisions"]["reason"] == "process_identity_not_recorded"
    finally:
        store.close()


def test_report_reports_empty_and_unrecognized_laya_snapshots_explicitly(tmp_path):
    store = TelemetryStore(tmp_path)
    try:
        empty = store.report(days=1)["laya_decisions"]
        assert empty["records"] == 0
        assert empty["invalid_records"] == 0
        assert empty["truncated"] is False

        store.record_snapshot("laya_decision", {"status": "error"})
        report = store.report(days=1)["laya_decisions"]
        assert report["records"] == 0
        assert report["invalid_records"] == 1
    finally:
        store.close()
