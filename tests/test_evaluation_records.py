from __future__ import annotations

from local_ai_hub.telemetry import TelemetryStore
from local_ai_hub.services import LocalAIServices


def test_unmatched_evaluation_is_not_claimed_as_quality_gain(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_evaluation(
            task_id="case-1",
            cohort="hub_on",
            quality_pass=True,
            test_pass=True,
            duration_ms=8,
        )
        store.flush(1)
        report = store.report(1)
    finally:
        store.close()

    assert report["evaluation"]["verdict"] == "insufficient_evidence"
    assert report["evaluation"]["matched_tasks"] == 0


def test_matched_evaluation_compares_hub_on_and_off(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_evaluation(task_id="case-2", cohort="hub_on", quality_pass=True, test_pass=True, duration_ms=8)
        store.record_evaluation(task_id="case-2", cohort="hub_off", quality_pass=True, test_pass=True, duration_ms=12)
        store.flush(1)
        report = store.report(1)
    finally:
        store.close()

    assert report["evaluation"]["verdict"] == "comparison_ready"
    assert report["evaluation"]["matched_tasks"] == 1
    assert report["evaluation"]["cohorts"]["hub_on"]["avg_duration_ms"] == 8
    assert report["evaluation"]["cohorts"]["hub_off"]["avg_duration_ms"] == 12


def test_evaluation_gate_promotes_only_after_ten_matched_quality_safe_faster_tasks(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        for index in range(10):
            task_id = f"case-{index}"
            store.record_evaluation(task_id=task_id, cohort="hub_on", quality_pass=True, test_pass=True, duration_ms=8)
            store.record_evaluation(task_id=task_id, cohort="hub_off", quality_pass=True, test_pass=True, duration_ms=12)
        store.flush(1)
        gate = store.report(1)["evaluation"]["gate"]
    finally:
        store.close()

    assert gate == {"verdict": "promote", "reason": "quality_test_safe_and_faster", "minimum_matched_tasks": 10}


def test_evaluation_service_exposes_existing_task_surface(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    service = object.__new__(LocalAIServices)
    service.telemetry = store
    try:
        recorded = service.evaluation({
            "action": "record",
            "task_id": "case-3",
            "cohort": "hub_on",
            "quality_pass": True,
            "test_pass": True,
            "duration_ms": 5,
        })
        store.flush(1)
        reported = service.evaluation({"action": "report", "days": 1})
    finally:
        store.close()

    assert recorded["success"] is True
    assert reported["evaluation"]["verdict"] == "insufficient_evidence"


def test_evaluation_service_rejects_non_numeric_duration(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    service = object.__new__(LocalAIServices)
    service.telemetry = store
    try:
        result = service.evaluation({
            "action": "record",
            "task_id": "case-4",
            "cohort": "hub_on",
            "duration_ms": "not-a-number",
        })
    finally:
        store.close()

    assert result == {"success": False, "error": "duration_ms must be numeric", "terminal": True}


def test_request_evaluation_uses_measured_duration(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        result = store.record_request_evaluation(
            {"task_id": "case-request", "cohort": "hub_on", "quality_pass": True, "test_pass": True},
            duration_ms=17.5,
        )
    finally:
        store.close()

    assert result == {"success": True, "task_id": "case-request", "cohort": "hub_on", "duration_ms": 17.5}
