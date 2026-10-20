import json

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
