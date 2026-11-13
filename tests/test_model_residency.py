from __future__ import annotations


class _Scheduler:
    def __init__(self, active_model: str):
        self.active_model = active_model

    def status(self) -> dict:
        return {"active_model": self.active_model}


class _Tuner:
    def __init__(self, ready: bool, prefer_resident: bool):
        self._ready = ready
        self._prefer_resident = prefer_resident

    def ready(self, *_models: str) -> bool:
        return self._ready

    def prefer_resident(self, *_models: str) -> bool:
        return self._prefer_resident


def _service(tuner):
    from local_ai_hub.services import LocalAIServices

    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {
        "routing": {"prefer_resident_model": True, "heavy_min_score": 3},
        "models": {"fast_code": "qwen2.5-coder:7b", "heavy_code": "qwen3.5:9b", "general": "qwen2.5-coder:7b"},
    }
    service.scheduler = _Scheduler("qwen3.5:9b")
    service.tuner = tuner
    return service


def _fast_route() -> dict:
    return {"task_type": "code", "complexity_score": 0, "model": "qwen2.5-coder:7b"}


def test_resident_router_keeps_requested_fast_model_until_calibrated():
    route = _service(_Tuner(ready=False, prefer_resident=True))._resident_optimize(_fast_route(), "auto", "auto")

    assert route["model"] == "qwen2.5-coder:7b"
    assert "resident_optimization" not in route


def test_resident_router_reuses_quality_equivalent_model_after_calibration():
    route = _service(_Tuner(ready=True, prefer_resident=True))._resident_optimize(_fast_route(), "auto", "auto")

    assert route["model"] == "qwen3.5:9b"
    assert route["resident_optimization"] == "resident-heavy-substitutes-fast-autotuned"


def test_resident_router_never_promotes_general_work_to_smart_model():
    route = _service(_Tuner(ready=True, prefer_resident=True))._resident_optimize(
        {"task_type": "general", "complexity_score": 0, "model": "qwen2.5-coder:7b"}, "auto", "auto"
    )

    assert route["model"] == "qwen2.5-coder:7b"
    assert "resident_optimization" not in route


def test_auto_reasoning_may_reuse_resident_fast_model_with_fast_execution_role():
    service = _service(_Tuner(ready=False, prefer_resident=True))
    service.config["routing"]["reasoning_resident_fallback"] = True
    service.scheduler = _Scheduler("qwen2.5-coder:7b")

    route = service._resident_optimize(
        {"task_type": "reasoning", "complexity_score": 4, "model": "qwen3.5:9b"},
        "auto", "auto",
    )

    assert route["model"] == "qwen2.5-coder:7b"
    assert route["resident_optimization"] == "resident-fast-reasoning-fallback"
    assert route["resident_execution_role"] == "fast_code"


def test_generate_accepts_route_with_resident_execution_role():
    from unittest.mock import MagicMock
    from local_ai_hub.resilience import CircuitBreakerAdmission
    from local_ai_hub.services import LocalAIServices

    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"server": {}, "token_saving": {}, "resilience": {}, "models": {}}
    service.model_policy = MagicMock()
    service.model_policy.profile.return_value = MagicMock(prompt_budget_tokens=4000, cache_scope=lambda: {})
    service.model_policy.apply_payload.return_value = (
        {"model": "qwen2.5-coder:7b"},
        MagicMock(prompt_budget_tokens=4000, cache_scope=lambda: {}),
    )
    service._available_vram_mb = lambda: 10000
    service.semantic_cache = MagicMock()
    service.generation_cache = MagicMock()
    service.runtime = MagicMock()
    service.runtime.is_online.return_value = True
    service.runtime.request_stream.return_value = {
        "response": "ok",
        "done": True,
        "outcome_unknown": False,
        "cleanup_unconfirmed": False,
        "_lah_partial_response": False,
    }
    service._fallback_models = lambda m: []
    service.breakers = MagicMock()
    service.breakers.allow.return_value = CircuitBreakerAdmission(True)
    service.scheduler = MagicMock()
    service.scheduler.submit.side_effect = lambda candidate, execute, **kw: execute()
    service.telemetry = MagicMock()
    service.artifacts = MagicMock()
    service.artifacts.compact = lambda r, **kw: r
    service.tuner = None

    route = {
        "model": "qwen2.5-coder:7b",
        "resident_execution_role": "fast_code",
    }
    res = service._generate(
        "qwen2.5-coder:7b",
        "hello",
        "system",
        100,
        0.1,
        source="delegate:reasoning",
        priority=5,
        use_cache=False,
        route=route,
    )
    assert res.get("success") is True
    roles = [c[1]["role"] for c in service.model_policy.profile.call_args_list]
    assert "fast_code" in roles
