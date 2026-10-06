from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices


def test_external_context_candidates_skips_when_budget_is_exhausted(tmp_path) -> None:
    services = LocalAIServices.__new__(LocalAIServices)
    calls = []

    class FakeExternal:
        def query(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"success": True, "result": []}

    services.external_tools = FakeExternal()
    services.repo_tools = RepositoryTools({"search": {"max_terms": 8}})
    services.config = {"search": {"context_backend_timeout_seconds": 3}}

    groups, warnings, states = services._external_context_candidates(
        str(tmp_path), "Find the route", timeout_budget=0
    )

    assert groups == {}
    assert warnings == []
    assert states == {"serena": "skipped"}
    assert calls == []


def test_external_context_candidates_clamps_timeout_to_remaining_budget(tmp_path) -> None:
    services = LocalAIServices.__new__(LocalAIServices)
    timeouts = []

    class FakeExternal:
        def query(self, *_args, timeout=None, **_kwargs):
            timeouts.append(timeout)
            return {"success": True, "results": []}

    services.external_tools = FakeExternal()
    services.repo_tools = RepositoryTools({"search": {"max_terms": 8}})
    services.config = {"search": {"context_backend_timeout_seconds": 5}}

    groups, warnings, states = services._external_context_candidates(
        str(tmp_path), "Find the route", timeout_budget=0.08
    )

    assert groups == {}
    assert warnings == []
    assert states == {"serena": "used"}
    assert len(timeouts) == 1
    assert 0 < timeouts[0] <= 0.08
