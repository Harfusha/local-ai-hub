from __future__ import annotations

from local_ai_hub.services import LocalAIServices


class _Flight:
    def get_or_compute(self, _key, compute):
        return compute(), True, True


def test_repo_cache_outcome_is_promoted_to_top_level_response():
    services = LocalAIServices.__new__(LocalAIServices)
    services.repo_flight = _Flight()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {"fingerprint": "rev", "kind": "filesystem"}

    result = services._repo_cached("search", "C:/repo", {"query": "x"}, lambda: {"success": True})

    assert result["cache_hit"] is True
    assert result["coalesced"] is True
    assert result["cache_layer"] == "workspace"
