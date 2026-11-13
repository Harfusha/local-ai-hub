from types import SimpleNamespace

import pytest

from local_ai_hub.services import LocalAIServices


class _Guard:
    def structured_evidence(self, evidence, *, limit):
        return [{"evidence_id": "evidence-1", "path": "src/main.py"}]


@pytest.mark.parametrize(("failure", "expected_reason"), [
    ({"error_type": "QueueFullError", "error_code": "local_backend_transport", "retryable": True}, "backend_queue_full"),
    ({"error_type": "TimeoutError", "error_code": "model_request_timeout", "timed_out": True}, "backend_timeout"),
    ({"error_type": "ConnectionError", "error_code": "local_backend_transport", "retryable": True}, "backend_transport"),
    ({"error_type": "ValueError", "error_code": "local_model_error", "retryable": False}, "model_unavailable"),
])
def test_adaptive_relevance_preserves_backend_degraded_reason(failure, expected_reason):
    service = LocalAIServices.__new__(LocalAIServices)
    service.consistency_guard = _Guard()
    service.config = {"models": {"fast_code": "qwen2.5-coder:3b"}}
    service._generate = lambda *_args, **_kwargs: {"success": False, **failure}
    service._repo_cached = lambda _op, _root, _params, compute: compute()
    request = SimpleNamespace(
        root="C:/repo",
        task_id="task-1",
        session_id="session-1",
        phase="edit",
        preload_profile="default",
        focus=(),
        changed_paths=(),
        query="inspect code",
        token_budget=512,
    )

    result = service._adaptive_relevance(
        request, ({"evidence_id": "evidence-1", "path": "src/main.py"},), "rev-1", "mem-1"
    )

    assert result["success"] is False
    assert result["degraded"] is True
    assert result["degraded_reason"] == expected_reason
    assert result["warnings"] == []


def test_adaptive_relevance_bounds_optional_model_request_time():
    service = LocalAIServices.__new__(LocalAIServices)
    service.consistency_guard = _Guard()
    service.config = {"models": {"fast_code": "qwen2.5-coder:3b"}}
    captured = {}

    def generate(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "success": False,
            "error_type": "TimeoutError",
            "error_code": "model_request_timeout",
            "timed_out": True,
        }

    service._generate = generate
    service._repo_cached = lambda _op, _root, _params, compute: compute()
    request = SimpleNamespace(
        root="C:/repo",
        task_id="task-1",
        session_id="session-1",
        phase="edit",
        preload_profile="default",
        focus=(),
        changed_paths=(),
        query="inspect code",
        token_budget=512,
    )

    result = service._adaptive_relevance(
        request, ({"evidence_id": "evidence-1", "path": "src/main.py"},), "rev-1", "mem-1"
    )

    assert result["degraded"] is True
    assert result["degraded_reason"] == "backend_timeout"
    assert captured.get("request_timeout_seconds") == 15.0
