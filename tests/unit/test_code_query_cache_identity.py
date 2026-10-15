"""Deferred F13 service-cache identity contract; no index or database access."""

from types import SimpleNamespace

from local_ai_hub.services import LocalAIServices


def test_exact_and_token_equivalent_fuzzy_queries_have_different_cache_keys():
    captured = []

    def cached(namespace, root, canonical, compute):
        captured.append(canonical)
        return {"success": True, "symbols": []}

    service = SimpleNamespace(
        code_index=SimpleNamespace(_query_terms=lambda query: ["generate", "tests"]),
        learner=None, _repo_cached=cached,
    )
    LocalAIServices.code_query(service, "C:/fixture/repo", "generate_tests")
    LocalAIServices.code_query(service, "C:/fixture/repo", "generate tests")
    assert captured[0]["terms"] == captured[1]["terms"]
    assert captured[0] != captured[1]
