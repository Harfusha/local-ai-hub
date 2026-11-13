from __future__ import annotations

import threading
from unittest.mock import MagicMock

from local_ai_hub.resilience import CircuitBreakerAdmission
from local_ai_hub.services import LocalAIServices


class _PassthroughCache:
    def get_or_compute(self, _key, compute):
        return compute(), False, False


class _NoStaleCache:
    def get(self, _key):
        return None

    def set(self, *_args, **_kwargs):
        return None


def _make_services(tmp_path):
    config = {
        "server": {"state_dir": str(tmp_path)},
        "models": {"fast": "test-fast", "reasoning": "test-reasoning"},
        "token_saving": {},
    }
    services = object.__new__(LocalAIServices)
    services.config = config
    services.runtime = MagicMock()
    services.runtime.is_online.return_value = True
    services.scheduler = MagicMock()
    services.embeddings = MagicMock()
    services.artifacts = type("ArtifactStore", (), {"compact": staticmethod(lambda res, **_: res)})()
    services.telemetry = MagicMock()
    services.model_policy = MagicMock()
    profile_mock = MagicMock()
    profile_mock.prompt_budget_tokens = 4096
    profile_mock.cache_scope.return_value = {"tier": "fast"}
    services.model_policy.profile.return_value = profile_mock
    services.model_policy.apply_payload.return_value = ({"options": {}}, profile_mock)
    services.exact_cache = MagicMock()
    services.exact_cache.get.return_value = None
    services.semantic_cache = MagicMock()
    services.semantic_cache.get.return_value = (None, 0.0)
    services.generation_cache = _PassthroughCache()
    services.stale_generation_cache = _NoStaleCache()
    services.tuner = None
    services.breakers = MagicMock()
    services.breakers.allow.return_value = CircuitBreakerAdmission(True)
    services.conversations = MagicMock()
    services._semantic_lock_guard = threading.Lock()
    services._semantic_scope_locks = {}
    return services


def test_semantic_scope_differs_by_repository_revision_without_digests(tmp_path):
    services = _make_services(tmp_path)
    
    captured_scopes = []
    def fake_get(scope, query):
        captured_scopes.append(scope)
        return (None, 0.0)
    services.semantic_cache.get.side_effect = fake_get

    # Call with rev1
    services._generate(
        model="test-fast",
        prompt="Explain this code",
        system="System prompt",
        max_tokens=100,
        temperature=0.0,
        source="general:query",
        priority=1,
        semantic_query="explain this code",
        repository_revision="rev-commit-1",
        project_config_digest="",
        project_namespace="",
    )

    # Call with rev2
    services._generate(
        model="test-fast",
        prompt="Explain this code",
        system="System prompt",
        max_tokens=100,
        temperature=0.0,
        source="general:query",
        priority=1,
        semantic_query="explain this code",
        repository_revision="rev-commit-2",
        project_config_digest="",
        project_namespace="",
    )

    assert len(captured_scopes) == 4
    assert captured_scopes[0] == captured_scopes[1]
    assert captured_scopes[2] == captured_scopes[3]
    assert captured_scopes[0] != captured_scopes[2], "semantic_scope must differ when repository_revision differs"


def test_code_bound_task_without_revision_disables_semantic_reuse(tmp_path):
    services = _make_services(tmp_path)
    
    services.semantic_cache.get.return_value = ({"text": "cached review"}, 0.95)

    # Code-bound task: source="review" and no repository_revision
    result = services._generate(
        model="test-fast",
        prompt="Review this patch",
        system="System prompt",
        max_tokens=100,
        temperature=0.0,
        source="review",
        priority=1,
        semantic_query="review this patch",
        repository_revision="",
    )

    assert result.get("_lah_cache_origin") != "semantic", "Code-bound task without repository_revision must disallow semantic reuse"
    assert services.semantic_cache.get.call_count == 0


def test_code_bound_task_with_revision_allows_semantic_reuse(tmp_path):
    services = _make_services(tmp_path)
    
    services.semantic_cache.get.return_value = ({"text": "cached review"}, 0.95)

    # Code-bound task: source="review" WITH repository_revision
    result = services._generate(
        model="test-fast",
        prompt="Review this patch",
        system="System prompt",
        max_tokens=100,
        temperature=0.0,
        source="review",
        priority=1,
        semantic_query="review this patch",
        repository_revision="commit-xyz",
    )

    assert result.get("cache_layer") == "semantic"
    assert result.get("cache_hit") is True
    assert services.semantic_cache.get.call_count > 0
