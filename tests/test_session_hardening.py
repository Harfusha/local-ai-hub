import pytest
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.external_tools import ExternalCodeIntelligence
from local_ai_hub.services import LocalAIServices


def test_serena_default_soft_timeout():
    eci = ExternalCodeIntelligence({})
    assert eci.soft_timeout == 10.0


def test_search_snippet_truncation():
    rt = RepositoryTools({})
    long_line = "x" * 2500
    lines = ["normal line", long_line, "another normal line"]
    snippet = rt._format_search_snippet(lines, 0, len(lines))
    assert "... [line truncated]" in snippet
    assert len(snippet) < 2000


def test_review_diff_custom_diff_truncated_key():
    class DummyPolicy:
        def tier_for(self, model):
            return "fast"
        def profile(self, *args, **kwargs):
            return type("Profile", (), {
                "context_window": 8000,
                "output_token_limit": 2048,
                "model": "dummy",
                "prompt_budget_tokens": 4000,
            })()

    class DummyRouter:
        def classify(self, *args, **kwargs):
            return {"model": "dummy", "complexity": "fast"}

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {}
    services.model_policy = DummyPolicy()
    services.router = DummyRouter()
    services.deterministic = None
    services.incident_store = None
    services._resident_optimize = lambda route, *a, **kw: route
    services.delegate = lambda payload, **kwargs: {
        "success": True,
        "text": "SUMMARY: Minor changes\n\n### Findings:\n- No security issues found.",
    }

    res = services.review_diff({"diff": "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"})
    assert res.get("success") is True, f"Failed: {res}"
    diff_info = res.get("diff", {})
    assert "truncated" in diff_info
    assert diff_info["truncated"] is False
    assert diff_info["local_diff_tokens"] > 0
