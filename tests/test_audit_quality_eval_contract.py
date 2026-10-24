"""Contracts for exact-symbol derivative grading in the audit evaluator."""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import audit_quality_eval as evaluator


def _captured_baseline():
    contracts = [
        (case, query, path, {path: [symbol]}, intent)
        for case, query, path, symbol, intent in evaluator.GOLD
    ] + [
        (case, query, path, {path: list(evaluator.ARCHITECTURE_TARGETS[case][0])},
         evaluator.ARCHITECTURE_TARGETS[case][1])
        for case, query, path in evaluator.ARCHITECTURE_QUERIES
    ]
    texts = {path: f"# captured source for {path}\n" for _, _, path, _, _ in contracts}
    hashes = {path: evaluator.hashlib.sha256(text.encode("utf-8")).hexdigest()
              for path, text in texts.items()}
    rows = [{"case": case, "query": query, "expected_path": path,
             "symbols": [{"path": path, "line": 1, "name": name, "kind": "function"}
                         for name in expected[path]]}
            for case, query, path, expected, _ in contracts]
    gold_count = len(evaluator.GOLD)
    return ({"source_hashes": dict(hashes), "retrieval": rows[:gold_count],
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
    assert derived["derivative_regrade"]["original_baseline_metric_scope"] == "path_only"
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
        symbols, intent = evaluator.ARCHITECTURE_TARGETS[case]
        assert ({path: list(symbols)}, intent) in graded_contracts
    assert evaluator.ARCHITECTURE_TARGETS["async-architecture"][0] == ("AsyncJobManager",)
    assert len(evaluator.ARCHITECTURE_TARGETS["mcp-architecture"][0]) == 7
