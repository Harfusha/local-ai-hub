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


def test_review_requires_source_backed_citation_for_findings():
    output = json.dumps({'verdict':'fail','findings':[{'citation':{'path':'src/example.py','line':5}}]})
    result = semantic_quality.assess_review_consistency(output, ['src/example.py'])
    assert result['usable'] is False
    assert result['reason'] == 'source_citation_unverified'
    assert result['semantic_truth_verified'] is False


def test_review_checks_path_line_and_exact_quote_against_diff():
    diff = 'diff --git a/src/example.py b/src/example.py\n--- a/src/example.py\n+++ b/src/example.py\n@@ -4,2 +4,3 @@\n old = 1\n+value = 2\n return value\n'
    def assess(line, quote, path='src/example.py'):
        output = json.dumps({'verdict':'fail','findings':[{'citation':{'path':path,'line':line,'quote':quote}}]})
        return semantic_quality.assess_review_consistency(output, ['src/example.py'], source_diff=diff)
    valid = assess(5, 'value = 2')
    assert valid['usable'] is True
    assert valid['citation_scope'] == 'supplied_diff_line_and_quote'
    assert valid['semantic_truth_verified'] is False
    assert assess(4, 'value = 2')['usable'] is False
    assert assess(5, 'fabricated')['usable'] is False
    assert assess(500, 'value = 2')['usable'] is False
    assert assess(5, 'value = 2', path='other.py')['usable'] is False


def test_review_does_not_ground_deleted_or_oversized_diff_lines():
    report = json.dumps({'verdict':'fail','findings':[{'citation':{'path':'src/example.py','line':4,'quote':'old = 1'}}]})
    deleted = 'diff --git a/src/example.py b/src/example.py\n--- a/src/example.py\n+++ b/src/example.py\n@@ -4 +4 @@\n-old = 1\n+new = 2\n'
    assert semantic_quality.assess_review_consistency(report, source_diff=deleted)['usable'] is False
    assert semantic_quality.assess_review_consistency(report, source_diff=deleted + ('x' * 200_001))['usable'] is False


def test_review_does_not_ground_malformed_hunk():
    report = json.dumps({'verdict':'fail','findings':[{'citation':{'path':'src/example.py','line':5,'quote':'forged'}}]})
    diff = '--- a/src/example.py\n+++ b/src/example.py\n@@ -4,0 +4,1 @@\n+valid\n+forged\n'
    assert semantic_quality.assess_review_consistency(report, source_diff=diff)['usable'] is False


def test_review_does_not_carry_path_to_next_malformed_file():
    report = json.dumps({'verdict':'fail','findings':[{'citation':{'path':'src/a.py','line':9,'quote':'other'}}]})
    diff = 'diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1,0 +1,1 @@\n+first\ndiff --git a/src/b.py b/src/b.py\n@@ -9,0 +9,1 @@\n+other\n'
    assert semantic_quality.assess_review_consistency(report, source_diff=diff)['usable'] is False


def test_review_does_not_resolve_parent_segments_in_citation_or_diff():
    report = json.dumps({'verdict':'fail','findings':[{'citation':{'path':'other.py','line':1,'quote':'value'}}]})
    diff = '--- a/src/../other.py\n+++ b/src/../other.py\n@@ -0,0 +1,1 @@\n+value\n'
    assert semantic_quality.assess_review_consistency(report, source_diff=diff)['usable'] is False


def test_review_rejects_unbounded_hunk_numbers_without_exception():
    report = json.dumps({'verdict':'fail','findings':[{'citation':{'path':'a.py','line':1,'quote':'value'}}]})
    diff = '--- a/a.py\n+++ b/a.py\n@@ -1 +'+('9' * 5000)+' @@\n-value\n+value\n'
    assert semantic_quality.assess_review_consistency(report, source_diff=diff)['usable'] is False


def test_review_handles_source_lines_that_resemble_diff_headers():
    report = json.dumps({'verdict':'fail','findings':[{'citation':{'path':'a.py','line':1,'quote':'++ added'}}]})
    diff = '--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n--- removed\n+++ added\n'
    assert semantic_quality.assess_review_consistency(report, source_diff=diff)['usable'] is True


@pytest.mark.parametrize('separator', ['\u2028', '\u2029', '\x85', '\v', '\f'])
def test_review_rejects_citation_fabricated_with_unicode_line_separator(separator):
    content = separator.join(['real', '+++ b/fake.py', '@@ -0,0 +1 @@', '+fabricated'])
    diff = '--- /dev/null\n+++ b/real.py\n@@ -0,0 +1 @@\n+' + content + '\n'
    fake = json.dumps({'verdict': 'fail', 'findings': [{'citation': {'path': 'fake.py', 'line': 1, 'quote': 'fabricated'}}]})
    real = json.dumps({'verdict': 'fail', 'findings': [{'citation': {'path': 'real.py', 'line': 1, 'quote': content}}]})
    assert semantic_quality.assess_review_consistency(fake, source_diff=diff)['usable'] is False
    assert semantic_quality.assess_review_consistency(real, source_diff=diff)['usable'] is True


def test_review_delivery_adds_consistency_warning_before_returning():
    from local_ai_hub.services import LocalAIServices
    service = object.__new__(LocalAIServices)
    service.delegate = lambda _args: {"success": True, "text": '{"verdict":"pass","findings":[{"citation":{"path":"src/example.py","line":1}}]}'}
    result = service.review({"code": "pass", "changed_paths": ["src/example.py"]})
    assert result["advisory_only"] is True
    assert result["review_consistency"]["verdict_consistent"] is False
    assert "quality_warning" in result


def test_review_delivery_grounds_citation_in_supplied_diff():
    from local_ai_hub.services import LocalAIServices
    service = object.__new__(LocalAIServices)
    captured = {}
    def delegate(payload):
        captured.update(payload)
        return {'success':True, 'text':json.dumps({'verdict':'fail','findings':[{'citation':{'path':'a.py','line':1,'quote':'value = 2'}}]})}
    service.delegate = delegate
    diff = '--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n'
    result = service.review({'code':diff, 'changed_paths':['a.py']})
    assert result['review_consistency']['usable'] is True
    assert result['review_consistency']['citation_scope'] == 'supplied_diff_line_and_quote'
    assert result['review_consistency']['semantic_truth_verified'] is False
    assert 'quote' in captured['task']


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
