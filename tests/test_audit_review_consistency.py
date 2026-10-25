import json
from types import SimpleNamespace

import pytest

from local_ai_hub import semantic_quality


def test_review_rejects_pass_verdict_with_findings():
    output = json.dumps({"verdict": "pass", "findings": [{"citation": {"path": "src/example.py", "line": 1}}]})
    result = semantic_quality.assess_review_consistency(output, ["src/example.py"])
    assert result["verdict_consistent"] is False
    assert result["usable"] is False
    assert result["semantic_truth_verified"] is False


def test_review_rejects_unsupported_citations_without_claiming_truth():
    output = json.dumps({"verdict": "fail", "findings": [{"citation": {"path": "made/up.rs", "line": 1}}]})
    result = semantic_quality.assess_review_consistency(output, ["src/example.py"])
    assert result["usable"] is False
    assert result["invalid_citation_indices"] == [0]


def test_review_plain_text_consistency_stays_explicitly_unverified():
    result = semantic_quality.assess_review_consistency("Review prose without a structured verdict.")
    assert result["verdict_consistent"] is None
    assert result["status"] == "unverified"
    assert result["semantic_truth_verified"] is False


def test_review_delivery_adds_consistency_warning_before_returning():
    from local_ai_hub.services import LocalAIServices
    service = object.__new__(LocalAIServices)
    service.delegate = lambda _args: {"success": True, "text": '{"verdict":"pass","findings":[{"citation":{"path":"src/example.py","line":1}}]}'}
    result = service.review({"code": "pass", "changed_paths": ["src/example.py"]})
    assert result["advisory_only"] is True
    assert result["review_consistency"]["verdict_consistent"] is False
    assert "quality_warning" in result


@pytest.mark.parametrize("supplied, expected", [({}, "json"), ({"format": "text"}, "text"), ({"format": {"type": "object"}}, {"type": "object"})])
def test_review_defaults_to_json_and_preserves_explicit_format(supplied, expected):
    from local_ai_hub.services import LocalAIServices
    service = object.__new__(LocalAIServices)
    captured = {}
    def delegate(args):
        captured.update(args)
        return {"success": True, "text": '{"verdict":"pass","findings":[]}'}
    service.delegate = delegate
    result = service.review({"code": "pass", **supplied})
    assert captured["format"] == expected
    assert result["review_consistency"]["usable"] is True
    assert result["review_consistency"]["semantic_truth_verified"] is False


def test_ast_review_reports_actual_diff_counts():
    from local_ai_hub.services import LocalAIServices
    service = object.__new__(LocalAIServices)
    service.config = {}
    service.repo_diff = lambda *args, **kwargs: {"success": True, "diff": "+new\n-old", "changed_files": ["example.py"]}
    service.deterministic = SimpleNamespace(diff_facts=lambda diff: {"additions": 3, "deletions": 2, "hunks": 1, "breaking_changes": []})
    result = service.review_diff({"root": ".", "mode": "ast"})
    assert "3 additions, 2 deletions across 1 hunks" in result["summary"]


@pytest.mark.parametrize("facts", [None, {}, {"additions": True, "deletions": 0, "hunks": 0}, {"additions": -1, "deletions": 0, "hunks": 1}])
def test_ast_review_fails_explicitly_when_metadata_unavailable(facts):
    from local_ai_hub.services import LocalAIServices
    service = object.__new__(LocalAIServices)
    service.config = {}
    service.repo_diff = lambda *args, **kwargs: {"success": True, "diff": "+new", "changed_files": ["example.py"]}
    service.deterministic = None if facts is None else SimpleNamespace(diff_facts=lambda diff: facts)
    result = service.review_diff({"root": ".", "mode": "ast"})
    assert result["success"] is False
    assert "unavailable" in result["error"].lower()


def test_ast_review_uses_real_unified_diff_parser():
    from local_ai_hub.deterministic import DeterministicEngine
    from local_ai_hub.services import LocalAIServices
    service = object.__new__(LocalAIServices)
    service.config = {}
    diff = "--- a/example.txt\n+++ b/example.txt\n@@ -1 +1,2 @@\n-old\n+new\n+second\n"
    service.repo_diff = lambda *args, **kwargs: {"success": True, "diff": diff, "changed_files": ["example.txt"]}
    service.deterministic = object.__new__(DeterministicEngine)
    result = service.review_diff({"root": ".", "mode": "ast"})
    assert result["success"] is True
    assert result["diff_facts"]["files"] == ["example.txt"]
    assert "2 additions, 1 deletions across 1 hunks" in result["summary"]
