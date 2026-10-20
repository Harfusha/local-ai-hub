"""Deterministic citation/ranking checks; these do not prove model truthfulness."""
from __future__ import annotations

import math


def paired_retrieval_delta(baseline, candidate):
    """Compare measured matching location queries; report signed raw deltas."""
    def cases(report):
        items = report.get("retrieval") if isinstance(report, dict) else None
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise ValueError("bounded measured baseline and candidate required")
        mapped = {}
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("case"), str):
                raise ValueError("explicit case identity required")
            key = item["case"]
            if key in mapped or not item.get("query") or not item.get("expected_path"):
                raise ValueError("unique case/query/path required")
            metrics = item.get("metrics", {})
            if metrics.get("status") != "measured":
                raise ValueError("unverified metrics cannot establish a delta")
            values = {name: metrics.get(name) for name in ("recall_at_k", "reciprocal_rank", "citation_validity")}
            if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1 for value in values.values()):
                raise ValueError("finite measured fractions required")
            values["answer_sufficiency"] = float(values["recall_at_k"] == 1 and values["citation_validity"] == 1)
            mapped[key] = (item["query"], item["expected_path"], values)
        return mapped
    try:
        before, after = cases(baseline), cases(candidate)
        if before.keys() != after.keys() or any(before[key][:2] != after[key][:2] for key in before):
            raise ValueError("baseline query identities differ")
        deltas = {name: sum(after[key][2][name] - before[key][2][name] for key in before) / len(before)
                  for name in next(iter(before.values()))[2]}
    except (ValueError, TypeError, AttributeError) as exc:
        return {"success": False, "status": "unverified", "reason": str(exc)}
    return {"success": True, "status": "paired", "case_count": len(before),
            "signed_deltas": deltas, "answer_scope": "expected_symbol_locations_only",
            "model_quality_verified": False}


def _citation_valid(citation, sources):
    if not isinstance(citation, dict):
        return False
    path, line = citation.get("path"), citation.get("line")
    return (
        isinstance(path, str) and path in sources
        and type(line) is int and 1 <= line <= len(sources[path].splitlines())
    )


def retrieval_metrics(report, relevant, sources, *, k=5):
    if type(k) is not int or k < 1 or not relevant:
        raise ValueError("positive k and explicit relevant paths are required")
    if not isinstance(report, dict) or report.get("success") is not True or report.get("stale") is True:
        return {"success": False, "status": "unverified"}
    symbols = report.get("symbols")
    if not isinstance(symbols, list) or any(not isinstance(item, dict) for item in symbols):
        return {"success": False, "status": "unverified"}
    ranked = symbols[:k]
    hits = {item.get("path") for item in ranked if item.get("path") in relevant}
    first = next((rank for rank, item in enumerate(ranked, 1) if item.get("path") in relevant), None)
    valid = sum(_citation_valid(item, sources) for item in ranked)
    return {
        "success": True, "status": "measured", "k": k,
        "unique_relevant_hits": len(hits), "recall_at_k": len(hits) / len(relevant),
        "reciprocal_rank": 1 / first if first else 0,
        "citation_validity": valid / len(ranked) if ranked else None,
        "answer_sufficiency": len(hits) == len(relevant) and bool(ranked) and valid == len(ranked),
        "citation_scope": "path_exists_and_line_in_supplied_source_snapshot",
    }


def review_metrics(report, sources):
    if not isinstance(report, dict) or report.get("success") is not True:
        return {"success": False, "status": "unverified", "semantic_truth_verified": False}
    findings, verdict = report.get("findings"), report.get("verdict")
    if not isinstance(findings, list) or verdict not in {"pass", "fail"}:
        return {"success": False, "status": "unverified", "semantic_truth_verified": False}
    invalid = [i for i, item in enumerate(findings) if not isinstance(item, dict) or not _citation_valid(item.get("citation"), sources)]
    consistent = (verdict == "pass") == (not findings)
    return {
        "success": not invalid and consistent, "status": "measured",
        "findings_count": len(findings), "invalid_citation_indices": invalid,
        "verdict_consistent": consistent,
        "semantic_truth_verified": False, "advisory_only": True,
    }
