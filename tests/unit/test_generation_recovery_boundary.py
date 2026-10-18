"""Deferred service boundary cases; inline fake provider, all state under tmp_path."""
from unittest.mock import MagicMock

import pytest

from local_ai_hub.operational_mode import set_operational_mode
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices
from local_ai_hub import services as services_module


def _service(tmp_path, response):
    config = {
        "server": {"state_dir": str(tmp_path), "request_timeout_seconds": 5},
        "ollama": {"enabled": True},
        "models": {"fast_code": "requested", "general": "alternate", "heavy_code": "heavy", "reasoning": "reason"},
        "hardware": {"profile": "balanced"},
        "_hardware": {"profile": "balanced", "ram": {"total_gb": 32}, "gpus": []},
        "cache": {"generation": False, "embeddings": False},
        "resilience": {"model_fallback_enabled": True, "serve_stale_on_error": True},
        "token_saving": {"compact_responses": False},
    }
    set_operational_mode(tmp_path, "active")

    class Runtime:
        def __init__(self):
            self.calls = []

        def is_online(self):
            return True

        def request(self, endpoint, payload, **kwargs):
            self.calls.append(payload["model"])
            return response

    class Scheduler:
        def status(self):
            return {}

        def submit(self, model, *, source, execute, **kwargs):
            return execute()

    runtime = Runtime()
    service = LocalAIServices(config, runtime, Scheduler(), MagicMock(), MagicMock(), MagicMock(), RepositoryTools(config))
    service.stale_generation_cache = MagicMock()
    service.stale_generation_cache.get.return_value = {"success": True, "text": "STALE"}
    return service, runtime


@pytest.mark.parametrize("state", [{"_lah_partial_response": True}, {"outcome_unknown": True, "cleanup_unconfirmed": True}])
def test_partial_or_unknown_failure_never_replays_another_model_or_stale_cache(tmp_path, state):
    service, runtime = _service(tmp_path, {"error": "provider interrupted", **state})
    result = service._generate("requested", "prompt", "system", 32, 0.0, source="delegate:test", priority=5)
    assert not result["success"] and result["terminal"] and not result["retryable"]
    assert all(result[key] for key in state)
    assert runtime.calls == ["requested"]
    service.stale_generation_cache.get.assert_not_called()


def test_recovered_context_provenance_survives_service_boundary_without_caching(tmp_path):
    metadata = {"original_num_ctx": 8192, "effective_num_ctx": 4096, "input_truncated": False}
    service, runtime = _service(tmp_path, {"done": True, "response": "ok", "context_recovery": metadata, "_lah_provider": "llama.cpp-sycl", "_lah_retry_count": 1})
    service.semantic_cache = MagicMock()
    service.semantic_cache.get.return_value = (None, 0.0)
    result = service._generate("requested", "prompt", "system", 32, 0.0, source="delegate:test", priority=5,
                               use_cache=True, semantic_query="query")
    assert result["success"] and result["context_recovery"] == metadata
    assert result["_lah_provider"] == "llama.cpp-sycl" and not result["_cacheable"]
    assert runtime.calls == ["requested"]
    service.stale_generation_cache.set.assert_not_called()
    service.semantic_cache.set.assert_not_called()


@pytest.mark.parametrize("state", [{"preempted": True}, {"timed_out": True}])
def test_cancel_and_timeout_do_not_substitute_stale_response(tmp_path, state):
    service, runtime = _service(tmp_path, {"error": "provider stopped", **state})
    result = service._generate("requested", "prompt", "system", 32, 0.0, source="delegate:test", priority=5)
    assert not result["success"] and runtime.calls == ["requested"]
    service.stale_generation_cache.get.assert_not_called()


def test_completion_contract_separates_legacy_exact_semantic_and_stale_cache_keys(tmp_path, monkeypatch):
    service, runtime = _service(tmp_path, {"done": True, "response": "fresh"})
    original_hash = services_module.stable_hash
    legacy = {}
    storage = {}
    scopes = []

    def hash_with_legacy_entry(value):
        if isinstance(value, dict) and isinstance(value.get("execution"), dict) and "stream_completion_contract" in value["execution"]:
            scopes.append(dict(value["execution"]))
            previous = {**value, "execution": {key: item for key, item in value["execution"].items() if key != "stream_completion_contract"}}
            old_key = original_hash(previous)
            obsolete = {"success": True, "text": "UNSAFE LEGACY", "model": "requested"}
            legacy[old_key] = obsolete
            storage[old_key] = obsolete
        return original_hash(value)

    monkeypatch.setattr(services_module, "stable_hash", hash_with_legacy_entry)
    cache = MagicMock()
    cache.get.side_effect = storage.get
    cache.set.side_effect = lambda key, value: storage.__setitem__(key, value)
    service.generation_cache.enabled = True
    service.generation_cache.cache = cache
    service.semantic_cache = MagicMock()
    service.semantic_cache.get.side_effect = lambda scope, query: (legacy.get(scope), 1.0)
    service.stale_generation_cache.get.side_effect = legacy.get
    result = service._generate("requested", "prompt", "system", 32, 0.0, source="delegate:test", priority=5,
                               semantic_query="query")
    assert legacy and scopes and all(scope["stream_completion_contract"] == 2 for scope in scopes)
    assert result["text"] == "fresh" and runtime.calls == ["requested"]
    assert all(value["text"] == "UNSAFE LEGACY" for value in legacy.values())
