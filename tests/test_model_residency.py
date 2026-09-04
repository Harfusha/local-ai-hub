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


def test_resident_router_reuses_quality_compatible_model_after_calibration():
    route = _service(_Tuner(ready=True, prefer_resident=True))._resident_optimize(_fast_route(), "auto", "auto")

    assert route["model"] == "qwen3.5:9b"
    assert route["resident_optimization"] == "resident-heavy-substitutes-fast-autotuned"


def test_resident_router_never_promotes_general_work_to_smart_model():
    route = _service(_Tuner(ready=True, prefer_resident=True))._resident_optimize(
        {"task_type": "general", "complexity_score": 0, "model": "qwen2.5-coder:7b"}, "auto", "auto"
    )

    assert route["model"] == "qwen2.5-coder:7b"
    assert "resident_optimization" not in route
