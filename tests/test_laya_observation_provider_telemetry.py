from types import SimpleNamespace

# Import the host module first: it imports this mixin near the end of its setup.
import local_ai_hub.app  # noqa: F401
from local_ai_hub.app_laya_observation import AppLayaObservationMixin
from local_ai_hub.telemetry import TelemetryStore


def _metadata(provider_label):
    return {
        "decision_id": "decision-provider-test",
        "success": True,
        "mode": "advisory",
        "status": "success",
        "category": "context_source",
        "repository_id": "repo-provider-test",
        "task_id": None,
        "session_id": None,
        "provider_label": provider_label,
        "suggestion": "indexed",
        "reason_codes": ["EVIDENCE_SUFFICIENT"],
        "evidence_ids": ["evidence-provider-test"],
        "model_estimate": True,
        "uncertainty": "UNCALIBRATED",
        "execution_verification": "NOT_VERIFIED",
        "baseline_available": False,
        "baseline_match": None,
        "runtime_latency_ms": None,
        "inference_latency_ms": None,
        "queue_wait_ms": None,
        "backend": None,
        "fallback_used": None,
        "fallback_reason": None,
    }


def test_runtime_decision_forwards_bound_provider_label_to_telemetry(tmp_path):
    telemetry = TelemetryStore(tmp_path)
    observation = AppLayaObservationMixin()
    observation.telemetry = telemetry
    observation.logger = None
    request = SimpleNamespace(
        provider_label="antigravity",
        repository_id="repo-provider-test",
        task_id=None,
        session_id=None,
        options=("indexed",),
    )
    decision = SimpleNamespace(
        metadata=lambda: _metadata(request.provider_label),
        suggestion="indexed",
        status=SimpleNamespace(value="success"),
    )

    try:
        assert observation._record_laya_runtime_decision(request, decision) is True
        assert telemetry.flush(2.0) is True
    finally:
        telemetry.close()
