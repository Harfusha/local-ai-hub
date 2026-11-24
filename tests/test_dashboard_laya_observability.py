import pytest

from local_ai_hub.dashboard import DASHBOARD_HTML
from tools.check_dashboard import validate_dashboard_html


def test_dashboard_contains_laya_observability_surfaces():
    # Verify unique IDs for Laya components in the dashboard
    for element_id in (
        'id="layaSection"',
        'id="layaStatusPill"',
        'id="layaRuntimeVal"',
        'id="layaRuntimeSub"',
        'id="layaDecisionsCount"',
        'id="layaDecisionsSub"',
        'id="layaCoverageVal"',
        'id="layaCoverageSub"',
        'id="layaLatencyVal"',
        'id="layaLatencySub"',
        'id="layaDecisionsBody"',
        'id="layaCaptureBody"',
    ):
        assert element_id in DASHBOARD_HTML, f"Expected {element_id} in DASHBOARD_HTML"

    # Verify Laya feature pill
    assert "k:'laya'" in DASHBOARD_HTML
    assert "label:'Laya'" in DASHBOARD_HTML

    # Verify HTML structure validity and uniqueness of IDs
    valid, errors = validate_dashboard_html(DASHBOARD_HTML)
    assert valid, f"Dashboard validation failed: {errors}"


def test_realtime_status_exposes_laya_runtime_and_features():
    from tests.test_status_snapshot_quality import make_realtime_app

    app = make_realtime_app()
    app.config.update({"laya": {"enabled": True}})
    status = app.realtime_status(light=True)

    assert "laya_runtime" in status
    assert status["laya_runtime"]["available"] is False
    assert status["laya_runtime"]["model_configuration"] == "unconfigured"
    assert status["features"]["laya"] is True
    assert "mode" not in status["laya"]
    assert status["laya"]["enabled"] is True


def test_telemetry_realtime_summary_forwards_laya_reports(tmp_path):
    from local_ai_hub.telemetry import TelemetryStore

    store = TelemetryStore(tmp_path)
    try:
        store.session_start(1234, "1.0")
        store.record_laya_eligibility(
            decision_id="decision-1", mode="advisory", category="context_source"
        )
        store.record_laya_decision(
            {
                "decision_id": "decision-1",
                "success": True,
                "mode": "advisory",
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
                "runtime_latency_ms": 15.0,
                "inference_latency_ms": 12.0,
                "queue_wait_ms": 3.0,
                "backend": "onnx",
                "fallback_used": False,
                "fallback_reason": None,
            },
            repository_id="repo-1", task_id="task-1", session_id="session-1",
        )
        store.flush(1.0)
        summary = store.realtime_summary(scope="process")
        assert "laya_decisions" in summary
        assert "laya_capture_stages" in summary
        assert "laya_capture_reasons" in summary
        assert summary["laya_decisions"]["records"] == 1
        assert summary["laya_decisions"]["by_mode"]["advisory"]["records"] == 1
    finally:
        store.close()


def test_dashboard_contains_all_subsystems_observability_surfaces():
    for element_id in (
        'id="circuitBreakersBody"',
        'id="recoveryJournalSummary"',
        'id="recoveryJournalBody"',
        'id="dedicatedModelsSection"',
        'id="embeddingsRuntimeVal"',
        'id="embeddingsRuntimeSub"',
        'id="rerankerRuntimeVal"',
        'id="rerankerRuntimeSub"',
        'id="vramBalancerVal"',
        'id="vramBalancerSub"',
        'id="dedicatedRuntimesBody"',
        'id="optimizationSection"',
        'id="autotuneVal"',
        'id="autotuneSub"',
        'id="learningVal"',
        'id="learningSub"',
        'id="evidenceStoreVal"',
        'id="evidenceStoreSub"',
        'id="losslessRouterVal"',
        'id="losslessRouterSub"',
        'id="asyncJobsSummary"',
        'id="asyncJobsBody"',
        'id="workOrchestratorSummary"',
        'id="workOrchestratorBody"',
    ):
        assert element_id in DASHBOARD_HTML, f"Expected {element_id} in DASHBOARD_HTML"

    valid, errors = validate_dashboard_html(DASHBOARD_HTML)
    assert valid, f"Dashboard validation failed: {errors}"


def test_realtime_status_exposes_all_subsystems():
    from tests.test_status_snapshot_quality import make_realtime_app

    app = make_realtime_app()
    status = app.realtime_status(light=True)

    expected_keys = [
        "circuit_breakers",
        "recovery",
        "embeddings",
        "reranker",
        "async_jobs",
        "work_orchestrator",
        "autotune",
        "learning",
        "evidence_store",
        "lossless_router",
        "vram_balancer",
    ]
    for key in expected_keys:
        assert key in status, f"Expected key '{key}' in realtime_status snapshot"


