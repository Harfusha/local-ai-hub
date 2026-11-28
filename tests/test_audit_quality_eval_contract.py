"""Contracts for exact-symbol derivative grading in the audit evaluator."""
from __future__ import annotations

import ast
import copy
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import audit_quality_eval as evaluator


def _captured_baseline():
    contracts = evaluator.goldset_contract()
    texts = {path: f"# captured source for {path}\n"
             for contract in contracts for path in contract["expected_symbols"]}
    hashes = {path: evaluator.hashlib.sha256(text.encode("utf-8")).hexdigest()
              for path, text in texts.items()}
    rows = [{**contract,
             "symbols": [{"path": path, "line": 1, "name": name, "kind": "function"}
                         for path, names in contract["expected_symbols"].items() for name in names]}
            for contract in contracts]
    gold_count = len(evaluator.GOLD)
    return ({"goldset_version": evaluator.GOLDSET_VERSION,
             "goldset_contract": copy.deepcopy(contracts),
             "source_hashes": dict(hashes), "retrieval": rows[:gold_count],
             "architecture_diagnostics": rows[gold_count:]}, texts, hashes, rows)


def test_derivative_regrades_all_ten_captured_symbol_cases_without_mutating_baseline():
    baseline, texts, hashes, captured = _captured_baseline()
    original = copy.deepcopy(baseline)
    measured = {"status": "measured", "measurement_scope": "symbol_ast",
                "expected_symbol_recall_at_k": 1, "citation_precision": 1,
                "test_source_contamination_count": 0, "source_evidence_sufficient": True}
    with patch.object(evaluator, "retrieval_metrics", return_value=measured):
        result = evaluator.regrade_captured_baseline_symbols(
            baseline, texts, hashes
        )
    assert result["success"] is True
    derived = result["baseline"]
    assert len(derived["retrieval"]) == 10
    assert derived["architecture_diagnostics"] == []
    assert [row["case"] for row in derived["retrieval"]] == [row["case"] for row in captured]
    assert derived["derivative_regrade"]["goldset_version"] == evaluator.GOLDSET_VERSION
    assert derived["derivative_regrade"]["original_baseline_modified"] is False
    assert baseline == original


def test_derivative_refuses_source_hash_drift():
    baseline, texts, hashes, _ = _captured_baseline()
    hashes = dict(hashes)
    texts = dict(texts)
    path = evaluator.ARCHITECTURE_QUERIES[0][2]
    texts[path] += "# changed\n"
    hashes[path] = evaluator.hashlib.sha256(texts[path].encode("utf-8")).hexdigest()
    result = evaluator.regrade_captured_baseline_symbols(
        baseline, texts, hashes
    )
    assert result["success"] is False
    assert result["reason"] == "baseline_source_hash_mismatch"
    assert result["path"] == path


def test_derivative_requires_all_architecture_captures_and_preserves_query_targets():
    baseline, texts, hashes, _ = _captured_baseline()
    baseline["architecture_diagnostics"].pop()
    result = evaluator.regrade_captured_baseline_symbols(
        baseline, texts, hashes
    )
    assert result["success"] is False
    assert result["reason"] == "baseline_retrieval_cases_invalid"

    baseline, texts, hashes, _ = _captured_baseline()
    measured = {"status": "measured", "measurement_scope": "symbol_ast"}
    with patch.object(evaluator, "retrieval_metrics", return_value=measured) as grade:
        result = evaluator.regrade_captured_baseline_symbols(
            baseline, texts, hashes
        )
    assert result["success"] is True
    graded_contracts = [(call.kwargs["expected_symbols"], call.kwargs["intent"])
                        for call in grade.call_args_list]
    for case, _, path in evaluator.ARCHITECTURE_QUERIES:
        _, intent = evaluator.ARCHITECTURE_TARGETS[case]
        assert (evaluator.architecture_symbols(case, path), intent) in graded_contracts
    assert evaluator.ARCHITECTURE_TARGETS["async-architecture"][0] == ("AsyncJobManager",)
    assert len(evaluator.ARCHITECTURE_TARGETS["mcp-architecture"][0]) == 7


def test_current_contract_binds_explicit_test_target_and_mcp_recall_k():
    contract = evaluator.goldset_contract()
    by_case = {row["case"]: row for row in contract}
    current = by_case["explicit-test-intent"]
    assert current["query"] == "test_retired_public_guide_rejects_before_health_queries"
    assert current["expected_symbols"][current["expected_path"]] == [
        "test_retired_public_guide_rejects_before_health_queries"
    ]
    assert by_case["mcp-architecture"]["k"] == 7
    assert evaluator.LEGACY_GOLD[0][1] == (
        "test_public_guide_uses_explicit_help_fields_without_health_queries"
    )

    baseline, texts, hashes, _ = _captured_baseline()
    baseline["goldset_contract"][0]["k"] += 1
    result = evaluator.regrade_captured_baseline_symbols(baseline, texts, hashes)
    assert result["success"] is False
    assert result["reason"] == "goldset_contract_mismatch"


def test_mcp_goldset_cites_real_definitions_after_module_extraction():
    root = Path(__file__).resolve().parents[1]
    contract = {row["case"]: row for row in evaluator.goldset_contract()}
    expected = contract["mcp-architecture"]["expected_symbols"]
    assert len(expected) == 7
    assert sum(map(len, expected.values())) == 7
    for path, names in expected.items():
        module = ast.parse((root / path).read_text(encoding="utf-8"))
        for name in names:
            matches = [node for node in module.body
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
            assert len(matches) == 1, (path, name)
            assert "MCP public tool entrypoint" in (ast.get_docstring(matches[0]) or "")
    assert contract["mcp-entrypoint"]["expected_symbols"] == {
        "src/local_ai_hub/mcp_tools_status.py": ["local_ai_status"]}


def test_old_single_file_goldset_cannot_be_paired_with_extracted_contract():
    baseline, texts, hashes, _ = _captured_baseline()
    baseline["goldset_version"] = 2
    result = evaluator.regrade_captured_baseline_symbols(baseline, texts, hashes)
    assert result["success"] is False
    assert result["reason"] == "goldset_version_mismatch"
