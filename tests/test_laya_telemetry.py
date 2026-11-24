import json
import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.telemetry import TelemetryStore, _laya_decision_report


def _metadata(**changes):
    value = {
        "decision_id": "decision-1",
        "success": True,
        "mode": "advisory",
        "status": "success",
        "category": "context_source",
        "repository_id": "repo-1",
        "task_id": "task-1",
        "session_id": "session-1",
        "provider_label": "generic_mcp",
        "suggestion": "indexed",
        "reason_codes": ["EVIDENCE_SUFFICIENT"],
        "evidence_ids": ["evidence-1"],
        "model_estimate": True,
        "uncertainty": "UNCALIBRATED",
        "execution_verification": "NOT_VERIFIED",
        "runtime_latency_ms": None,
        "inference_latency_ms": None,
        "queue_wait_ms": None,
        "backend": None,
        "fallback_used": None,
        "fallback_reason": None,
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
        assert saved["task_id"] == "task-1"
        assert saved["session_id"] == "session-1"
        assert saved["provider_label"] == "generic_mcp"
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
        with pytest.raises(ValueError, match="identity"):
            store.record_laya_decision(
                _metadata(provider_label="codex"), repository_id="repo-1", task_id="task-1",
                session_id="session-1", provider_label="claude",
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
        for decision_id, mode in (
            ("decision-1", "advisory"), ("decision-2", "advisory"),
            ("decision-3", "advisory"), ("decision-4", "advisory"),
        ):
            store.record_laya_eligibility(
                decision_id=decision_id, mode=mode, category="context_source"
            )

        report = store.report(days=1)

        summary = report["laya_decisions"]
        assert summary["records"] == 4
        assert summary["counts_by_mode"] == {"advisory": 4}
        assert summary["counts_by_status"] == {"abstain": 1, "error": 1, "skipped": 1, "success": 1}
        assert summary["by_mode"]["advisory"]["abstentions"] == 1
        assert summary["by_mode"]["advisory"]["errors"] == 1
        assert summary["by_mode"]["advisory"]["skips"] == 1
        assert summary["by_mode"]["advisory"]["counts_by_reason_code"] == {
            "DISABLED": 1,
            "EVIDENCE_SUFFICIENT": 1,
            "INSUFFICIENT_EVIDENCE": 1,
            "TIMEOUT": 1,
        }
        mode_report = summary["by_mode"]["advisory"]
        assert mode_report["coverage"] == {
            "available": True,
            "eligible_decisions": 4,
            "recorded_decisions": 4,
            "rate": 1.0,
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


def test_laya_report_measures_eligibility_runtime_latency_backend_and_fallback(tmp_path):
    store = TelemetryStore(tmp_path)
    try:
        store.record_laya_eligibility(
            decision_id="decision-1", mode="advisory", category="context_source", provider_label="codex"
        )
        store.record_laya_eligibility(
            decision_id="decision-2", mode="advisory", category="context_source", provider_label="claude"
        )
        store.record_laya_decision(
            _metadata(
                runtime_latency_ms=22.0,
                inference_latency_ms=19.0,
                queue_wait_ms=3.0,
                backend="onnx",
                fallback_used=True,
                fallback_reason="EARLIER_DEVICE_UNAVAILABLE",
            ),
            repository_id="repo-1", task_id="task-1", session_id="session-1",
        )

        summary = store.report(days=1)["laya_decisions"]["by_mode"]["advisory"]

        assert summary["coverage"] == {
            "available": True, "eligible_decisions": 2,
            "recorded_decisions": 1, "rate": 0.5,
        }
        assert summary["latency_ms"] == {
            "available": True, "samples": 1,
            "mean": 22.0, "max": 22.0,
            "inference_samples": 1,
            "inference_mean": 19.0, "queue_wait_mean": 3.0,
            "queue_wait_samples": 1,
        }
        assert summary["backend"] == {"available": True, "counts": {"onnx": 1}}
        assert summary["fallbacks"] == {
            "available": True, "used": 1, "not_used": 0, "unknown": 0,
            "reasons": {"EARLIER_DEVICE_UNAVAILABLE": 1},
        }
    finally:
        store.close()


def test_laya_report_deduplicates_retried_eligibility_and_matches_decision_ids():
    decision = json.dumps(_metadata())
    eligible = json.dumps({
        "decision_id": "decision-1", "mode": "advisory", "category": "context_source",
        "provider_label": "generic_mcp",
    })
    missing = json.dumps({
        "decision_id": "decision-missing", "mode": "advisory", "category": "context_source",
        "provider_label": "generic_mcp",
    })

    report = _laya_decision_report(
        [(decision,), (decision,)],
        [(eligible,), (eligible,), (missing,)],
        scope="window",
    )

    assert report["records"] == 1
    assert report["by_mode"]["advisory"]["coverage"] == {
        "available": True, "eligible_decisions": 2,
        "recorded_decisions": 1, "rate": 0.5,
    }


def test_laya_report_rejects_pre_runtime_persisted_shape():
    old = _metadata()
    for field in ("runtime_latency_ms", "inference_latency_ms", "queue_wait_ms", "backend", "fallback_used", "fallback_reason"):
        old.pop(field)

    report = _laya_decision_report([(json.dumps(old),)], [], scope="window")

    assert report["records"] == 0
    assert report["invalid_records"] == 1


def test_laya_report_rejects_duplicate_json_keys():
    canonical = json.dumps(_metadata())
    ambiguous = canonical.replace('"decision_id": "decision-1"', '"decision_id": "shadowed", "decision_id": "decision-1"')

    report = _laya_decision_report([(ambiguous,)], [], scope="window")

    assert report["records"] == 0
    assert report["invalid_records"] == 1
