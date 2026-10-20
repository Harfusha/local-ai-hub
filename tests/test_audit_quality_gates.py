from __future__ import annotations

import copy

import pytest


def test_retrieval_baseline_reports_signed_decrease_and_rejects_changed_queries():
    from local_ai_hub.evaluation_quality import paired_retrieval_delta
    baseline = {"retrieval": [{"case": "entry", "query": "entry", "expected_path": "src/main.py", "metrics": {
        "status": "measured", "recall_at_k": 1.0, "reciprocal_rank": 1.0, "citation_validity": 1.0}}]}
    candidate = copy.deepcopy(baseline)
    candidate["retrieval"][0]["metrics"]["recall_at_k"] = 0.0
    result = paired_retrieval_delta(baseline, candidate)
    assert result["success"] is True
    assert result["signed_deltas"]["recall_at_k"] == -1.0
    assert result["signed_deltas"]["answer_sufficiency"] == -1.0
    candidate["retrieval"][0]["query"] = "different"
    assert paired_retrieval_delta(baseline, candidate)["success"] is False

from tools.check_critical_coverage import check_report, make_baseline
from local_ai_hub.evaluation_quality import retrieval_metrics, review_metrics


def coverage():
    return {"meta": {"branch_coverage": True}, "files": {
        "src/local_ai_hub/agent_policy.py": {
            "summary": {"num_branches": 10, "covered_branches": 8},
        },
    }}


def test_coverage_gate_rejects_regression_and_missing_module():
    report = coverage()
    baseline = make_baseline(report, ["src/local_ai_hub/agent_policy.py"], "candidate", "test")
    assert check_report(report, baseline)["success"] is True
    report["files"]["src/local_ai_hub/agent_policy.py"]["summary"]["covered_branches"] = 7
    assert check_report(report, baseline)["success"] is False
    report["files"] = {}
    assert check_report(report, baseline)["success"] is False


@pytest.mark.parametrize("bad", [False, -1, 1.5, "8", 11])
def test_coverage_gate_rejects_malformed_counts(bad):
    report = coverage()
    report["files"]["src/local_ai_hub/agent_policy.py"]["summary"]["covered_branches"] = bad
    with pytest.raises(ValueError):
        make_baseline(report, ["src/local_ai_hub/agent_policy.py"], "candidate", "test")


def test_coverage_gate_rejects_unknown_branch_evidence():
    report = coverage()
    report["meta"]["branch_coverage"] = False
    with pytest.raises(ValueError):
        make_baseline(report, ["src/local_ai_hub/agent_policy.py"], "candidate", "test")


def test_coverage_baseline_requires_provenance_and_matching_environment():
    with pytest.raises(ValueError):
        make_baseline(coverage(), ["src/local_ai_hub/agent_policy.py"], "", "test")
    baseline = make_baseline(coverage(), ["src/local_ai_hub/agent_policy.py"], "candidate", "test")
    baseline["environment"] = "foreign"
    assert check_report(coverage(), baseline)["success"] is False


def test_retrieval_metrics_count_unique_hits_and_rank():
    result = retrieval_metrics(
        {"success": True, "symbols": [{"path": "src/main.py", "line": 1}, {"path": "src/main.py", "line": 1}]},
        {"src/main.py"}, {"src/main.py": "def main():\n    pass\n"}, k=3,
    )
    assert result["recall_at_k"] == 1
    assert result["reciprocal_rank"] == 1
    assert result["unique_relevant_hits"] == 1
    assert result["citation_validity"] == 1


def test_stale_or_failed_retrieval_never_proves_quality():
    for report in ({"success": False}, {"success": True, "stale": True, "symbols": []}):
        assert retrieval_metrics(report, {"src/main.py"}, {"src/main.py": "x"})["status"] == "unverified"


def test_review_eval_catches_invented_paths_lines_and_verdict_conflict():
    valid = {"success": True, "verdict": "fail", "findings": [
        {"citation": {"path": "src/main.py", "line": 1}, "severity": "P1"},
    ]}
    sources = {"src/main.py": "def main():\n    pass\n"}
    assert review_metrics(valid, sources)["success"] is True
    for change in ("path", "line", "verdict"):
        report = copy.deepcopy(valid)
        if change == "verdict":
            report["verdict"] = "pass"
        else:
            report["findings"][0]["citation"][change] = "invented.rs" if change == "path" else 300
        assert review_metrics(report, sources)["success"] is False
    assert review_metrics({"success": False}, sources)["status"] == "unverified"
