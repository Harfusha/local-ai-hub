from types import SimpleNamespace

import pytest

from local_ai_hub.services import LocalAIServices


class _Guard:
    def structured_evidence(self, evidence, *, limit):
        return [{"evidence_id": "evidence-1", "path": "src/main.py"}]


def test_adaptive_relevance_prefers_configured_context_relevance_model():
    service = LocalAIServices.__new__(LocalAIServices)
    service.consistency_guard = _Guard()
    service.config = {
        "models": {
            "context_relevance_model": "qwen2.5-coder:3b",
            "fast_code": "qwen2.5-coder:7b",
        }
    }
    captured = {}
    service._generate = lambda model, *_args, **_kwargs: captured.update(model=model) or {
        "success": False,
        "error_type": "TimeoutError",
        "error_code": "model_request_timeout",
        "timed_out": True,
    }
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

    service._adaptive_relevance(
        request, ({"evidence_id": "evidence-1", "path": "src/main.py"},), "rev-1", "mem-1"
    )

    assert captured["model"] == "qwen2.5-coder:3b"


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
    assert captured.get("request_timeout_seconds") == 3.0


def test_adaptive_relevance_skips_model_while_scheduler_has_pending_work():
    service = LocalAIServices.__new__(LocalAIServices)
    service.consistency_guard = _Guard()
    service.config = {"models": {"fast_code": "qwen2.5-coder:3b"}}
    service.scheduler = SimpleNamespace(pending_count=lambda: 1)
    calls = []
    service._generate = lambda *_args, **_kwargs: calls.append(1)
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
    assert result["degraded_reason"] == "backend_busy"
    assert calls == []


def test_adaptive_relevance_skips_optional_model_switch():
    service = LocalAIServices.__new__(LocalAIServices)
    service.consistency_guard = _Guard()
    service.config = {
        "models": {"context_relevance_model": "qwen2.5-coder:3b"}
    }
    service.scheduler = SimpleNamespace(
        pending_count=lambda: 0,
        active_model=lambda: "qwen3.5:9b-nvfp4",
    )
    calls = []
    service._generate = lambda *_args, **_kwargs: calls.append(1)
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
    assert result["degraded_reason"] == "backend_model_mismatch"
    assert calls == []


def test_adaptive_relevance_cools_down_after_queue_full(monkeypatch):
    from local_ai_hub import services as services_module

    now = [100.0]
    monkeypatch.setattr(services_module.time, "monotonic", lambda: now[0])
    service = LocalAIServices.__new__(LocalAIServices)
    service.consistency_guard = _Guard()
    service.config = {"models": {"fast_code": "qwen2.5-coder:3b"}}
    service._repo_cached = lambda _op, _root, _params, compute: compute()
    calls = []

    def generate(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            return {
                "success": False,
                "error_type": "QueueFullError",
                "error_code": "local_backend_transport",
                "retryable": True,
            }
        return {"success": True, "text": "{}"}

    service._generate = generate
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
    args = (request, ({"evidence_id": "evidence-1", "path": "src/main.py"},), "rev-1", "mem-1")

    first = service._adaptive_relevance(*args)
    now[0] += 1.0
    during_cooldown = service._adaptive_relevance(*args)

    assert first["degraded_reason"] == "backend_queue_full"
    assert during_cooldown["degraded_reason"] == "backend_queue_full"
    assert len(calls) == 1

    now[0] += 10.0
    after_cooldown = service._adaptive_relevance(*args)

    assert after_cooldown["success"] is True
    assert len(calls) == 2


def test_adaptive_relevance_cools_down_after_timeout(monkeypatch):
    from local_ai_hub import services as services_module

    now = [200.0]
    monkeypatch.setattr(services_module.time, "monotonic", lambda: now[0])
    service = LocalAIServices.__new__(LocalAIServices)
    service.consistency_guard = _Guard()
    service.config = {"models": {"fast_code": "qwen2.5-coder:3b"}}
    service._repo_cached = lambda _op, _root, _params, compute: compute()
    calls = []

    def generate(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            return {
                "success": False,
                "error_type": "TimeoutError",
                "error_code": "model_request_timeout",
                "timed_out": True,
            }
        return {"success": True, "text": "{}"}

    service._generate = generate
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
    args = (request, ({"evidence_id": "evidence-1", "path": "src/main.py"},), "rev-1", "mem-1")

    timed_out = service._adaptive_relevance(*args)
    during_cooldown = service._adaptive_relevance(*args)

    assert timed_out["degraded_reason"] == "backend_timeout"
    assert during_cooldown["degraded_reason"] == "backend_timeout"
    assert len(calls) == 1

    now[0] += 31.0
    after_cooldown = service._adaptive_relevance(*args)

    assert after_cooldown["success"] is True
    assert len(calls) == 2
