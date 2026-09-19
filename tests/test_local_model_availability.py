from __future__ import annotations

from types import SimpleNamespace

from local_ai_hub.model_policy import ModelExecutionPolicy
from local_ai_hub.services import LocalAIServices


class _OfflineRuntime:
    def is_online(self) -> bool:
        return False


class _NoSubmitScheduler:
    def submit(self, *_args, **_kwargs):
        raise AssertionError("offline runtime must not enqueue model work")


class _PassthroughCache:
    def get_or_compute(self, _key, compute):
        return compute(), False, False


class _NoSemanticCache:
    def get(self, *_args, **_kwargs):
        return None, 0.0


class _NoStaleCache:
    def get(self, _key):
        return None


class _Breakers:
    def allow(self, _key):
        return True

    def failure(self, _key):
        return None


class _Telemetry:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


def _offline_services() -> LocalAIServices:
    services = object.__new__(LocalAIServices)
    services.config = {
        "models": {"fast_code": "fast", "general": "general"},
        "token_saving": {"max_local_input_tokens": 4096, "max_local_output_tokens": 512},
        "model_execution": {"fast": {"context_tokens": 4096, "max_context_tokens": 4096}},
        "resilience": {"model_fallback_enabled": True, "max_model_fallbacks": 2},
        "ollama": {"keep_alive": "-1"},
    }
    services.runtime = _OfflineRuntime()
    services.scheduler = _NoSubmitScheduler()
    services.model_policy = ModelExecutionPolicy(services.config)
    services.semantic_cache = _NoSemanticCache()
    services.generation_cache = _PassthroughCache()
    services.stale_generation_cache = _NoStaleCache()
    services.breakers = _Breakers()
    services.telemetry = _Telemetry()
    services.artifacts = SimpleNamespace(compact=lambda result, *_args: result)
    services.tuner = None
    services.vram_balancer = None
    services.fallback_count = 0
    return services


def test_generate_fails_fast_without_backend_and_skips_scheduler() -> None:
    services = _offline_services()

    result = LocalAIServices._generate(
        services,
        "fast",
        "tiny",
        "",
        64,
        0.0,
        "tenant",
        "delegate:general",
        5,
    )

    assert result["success"] is False
    assert result["retryable"] is True
    assert result["error_code"] == "local_backend_unavailable"
