"""Measure a bounded, fresh source-symbol goldset; never infer model quality."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.evaluation_quality import paired_retrieval_delta, retrieval_metrics, review_metrics
from local_ai_hub.repo_tools import RepositoryTools

GOLDSET_VERSION = 2
GOLD = (
    ("mcp-entrypoint", "local_ai_status", "src/local_ai_hub/mcp_server.py", "local_ai_status", "production"),
    ("http-deadline", "RequestHeadReader", "src/local_ai_hub/http_transport.py", "RequestHeadReader", "production"),
    ("budget-failure", "BudgetUnavailableError", "src/local_ai_hub/agent_policy.py", "BudgetUnavailableError", "production"),
    ("async-owner", "AsyncJobManager", "src/local_ai_hub/async_jobs.py", "AsyncJobManager", "production"),
    ("context-artifact", "persist_compiled_context", "src/local_ai_hub/context_delivery.py", "persist_compiled_context", "production"),
    ("review-entrypoint", "LocalAIServices", "src/local_ai_hub/services.py", "LocalAIServices", "production"),
    ("explicit-test-intent", "test_retired_public_guide_rejects_before_health_queries",
     "tests/test_audit_action_guide_remediation.py",
     "test_retired_public_guide_rejects_before_health_queries", "test"),
)
LEGACY_GOLD = (
    ("explicit-test-intent", "test_public_guide_uses_explicit_help_fields_without_health_queries",
     "tests/test_audit_action_guide_remediation.py",
     "test_public_guide_uses_explicit_help_fields_without_health_queries", "test"),
)
LEGACY_ARCHITECTURE_TARGETS = {
    "http-architecture": ("RequestHeadReader", "production"),
    "async-architecture": ("_cancellation_callback", "production"),
    "mcp-architecture": ("_compact_mcp_call_tool", "production"),
}

ARCHITECTURE_QUERIES = (
    ("http-architecture", "HTTP server request header deadline", "src/local_ai_hub/http_transport.py"),
    ("async-architecture", "asynchronous job lifecycle cancellation ownership", "src/local_ai_hub/async_jobs.py"),
    ("mcp-architecture", "MCP public tool entrypoints", "src/local_ai_hub/mcp_server.py"),
)
ARCHITECTURE_TARGETS = {
    "http-architecture": (("RequestHeadReader",), "production"),
    "async-architecture": (("AsyncJobManager",), "production"),
    "mcp-architecture": (("local_ai_status", "local_ai_task", "local_ai_repo",
                          "local_ai_rag", "local_ai_coord", "local_ai_work",
                          "local_ai_artifact"), "production"),
}
GOLD_K = {case: 5 for case, *_ in GOLD}
ARCHITECTURE_K = {"http-architecture": 5, "async-architecture": 5, "mcp-architecture": 7}


def goldset_contract():
    contracts = [
        {"case": case, "query": query, "expected_path": path,
         "expected_symbols": {path: [symbol]}, "intent": intent, "k": GOLD_K[case]}
        for case, query, path, symbol, intent in GOLD
    ]
    contracts.extend(
        {"case": case, "query": query, "expected_path": path,
         "expected_symbols": {path: list(ARCHITECTURE_TARGETS[case][0])},
         "intent": ARCHITECTURE_TARGETS[case][1], "k": ARCHITECTURE_K[case]}
        for case, query, path in ARCHITECTURE_QUERIES
    )
    return contracts


def run(root, baseline=None, baseline_source_root=None):
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("authorized absolute repository root required")
    sources, hashes = {}, {}
    paths = sorted({path for _, _, path, _, _ in GOLD} | {
        "tests/test_audit_remediation.py", "tests/test_audit_transport_remediation.py",
    })
    for path in paths:
        target = root / path
        current = target
        while current != root:
            if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
                raise ValueError("goldset files cannot traverse links")
            current = current.parent
        data = target.read_bytes()
        if len(data) > 4 * 1024 * 1024:
            raise ValueError("goldset source exceeds bound")
        sources[path] = data.decode("utf-8")
        hashes[path] = hashlib.sha256(data).hexdigest()
    if any(hashlib.sha256(text.encode("utf-8")).hexdigest() != hashes[path]
           for path, text in sources.items()):
        raise ValueError("current source snapshot hash mismatch")
    results, architecture = [], []
    with tempfile.TemporaryDirectory(prefix="hub-audit-eval-") as state:
        config = {"server": {"state_dir": state}, "search": {"max_files": len(paths)}}
        repository = RepositoryTools(config)
        index = CodeIndex(config, repository)
        try:
            built = index.update_files_batch(str(root), list(hashes.items()))
            if built.get("success") is not True:
                raise RuntimeError("bounded goldset index build failed")
            for case, query, relevant, expected_symbol, intent in GOLD:
                k = GOLD_K[case]
                report = index.query(str(root), query, limit=k, verify_freshness=True)
                expected_symbols = {relevant: [expected_symbol]}
                metrics = retrieval_metrics(
                    report, {relevant}, sources, k=k,
                    expected_symbols=expected_symbols, intent=intent,
                )
                metrics["k"] = k
                results.append({"case": case, "query": query, "expected_path": relevant,
                                "expected_symbols": expected_symbols, "intent": intent,
                                "k": k,
                                "target_status": "declared_exact_target",
                                "metrics": metrics, "symbols": report.get("symbols", [])})
            for case, query, relevant in ARCHITECTURE_QUERIES:
                k = ARCHITECTURE_K[case]
                report = index.query(str(root), query, limit=k, verify_freshness=True)
                expected_names, intent = ARCHITECTURE_TARGETS[case]
                expected_symbols = {relevant: list(expected_names)}
                metrics = retrieval_metrics(
                    report, {relevant}, sources, k=k,
                    expected_symbols=expected_symbols, intent=intent,
                )
                metrics["k"] = k
                architecture.append({"case": case, "query": query, "expected_path": relevant,
                    "expected_symbols": expected_symbols, "intent": intent, "k": k,
                    "metrics": metrics,
                    "symbols": report.get("symbols", [])})
            legacy = []
            for case, query, relevant, symbol, intent in LEGACY_GOLD:
                report = index.query(str(root), query, limit=5, verify_freshness=True)
                legacy.append({"case": case, "query": query, "expected_path": relevant,
                    "expected_symbols": {relevant: [symbol]}, "intent": intent, "k": 5,
                    "status": "legacy_only_never_paired",
                    "metrics": retrieval_metrics(
                        report, {relevant}, sources, k=5,
                        expected_symbols={relevant: [symbol]}, intent=intent,
                    ), "symbols": report.get("symbols", [])})
        finally:
            index.close()
    reference = {"citation": {"path": GOLD[0][2], "line": 1}, "severity": "P2"}
    cases = [
        ({"success": True, "verdict": "fail", "findings": [reference]}, True),
        ({"success": True, "verdict": "pass", "findings": [reference]}, False),
        ({"success": True, "verdict": "fail", "findings": [
            {"citation": {"path": "invented.rs", "line": 1}}]}, False),
        ({"success": False}, False),
    ]
    faithfulness = [{"expected_accepted": expected, "measurement": review_metrics(value, sources)}
                    for value, expected in cases]
    valid = all(
        item["metrics"].get("status") == "measured"
        and item["metrics"].get("measurement_scope") == "symbol_ast"
        and item["metrics"].get("recall_at_k") == 1
        and item["metrics"].get("citation_validity") == 1
        and item["metrics"].get("expected_symbol_recall_at_k") == 1
        and item["metrics"].get("citation_precision") == 1
        and item["metrics"].get("test_source_contamination_count") == 0
        and item["metrics"].get("source_evidence_sufficient") is True
        for item in results
    )
    architecture_measured = all(
        item["metrics"].get("status") == "measured"
        and item["metrics"].get("measurement_scope") == "symbol_ast"
        and item["metrics"].get("expected_symbol_recall_at_k") == 1
        and item["metrics"].get("citation_precision") == 1
        and item["metrics"].get("test_source_contamination_count") == 0
        and item["metrics"].get("source_evidence_sufficient") is True
        for item in architecture
    )
    ranker_path = root / "src/local_ai_hub/code_index.py"
    current = ranker_path
    while current != root:
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise ValueError("ranker source cannot traverse links")
        current = current.parent
    with ranker_path.open("rb") as stream:
        ranker_bytes = stream.read(4 * 1024 * 1024 + 1)
    if len(ranker_bytes) > 4 * 1024 * 1024:
        raise ValueError("ranker source exceeds bound")
    result = {
        "success": valid and architecture_measured and all(
            item["measurement"]["success"] == item["expected_accepted"] for item in faithfulness
        ),
        "scope": "bounded_named_current_source_goldset_not_full_repository_or_model_quality",
        "source_hashes": hashes, "retrieval": results, "review_contract_cases": faithfulness,
        "architecture_diagnostics": architecture,
        "goldset_version": GOLDSET_VERSION, "goldset_contract": goldset_contract(),
        "legacy_gold_diagnostics": legacy,
        "architecture_metric_scope": "symbol_ast_exact_targets_existing_queries_unchanged",
        "answer_sufficiency_scope": "expected_symbol_locations_only_not_generated_answers",
        "model_quality_verified": False,
        "ranker_source_sha256": hashlib.sha256(ranker_bytes).hexdigest(),
        "ranking_changed": None,
    }
    if baseline is not None:
        if isinstance(baseline.get("ranker_source_sha256"), str):
            result["ranking_changed"] = baseline["ranker_source_sha256"] != result["ranker_source_sha256"]
        original_sources, original_hashes = _read_baseline_sources(
            baseline, baseline_source_root
        ) if baseline_source_root is not None else (sources, hashes)
        derivative = regrade_captured_baseline_symbols(baseline, original_sources, original_hashes)
        result["baseline_symbol_regrade"] = {
            key: value for key, value in derivative.items() if key != "baseline"
        }
        if derivative.get("success") is True:
            result["baseline_symbol_regrade"]["retrieval"] = derivative["baseline"]["retrieval"]
            current_paired = {**result, "retrieval": results + architecture}
            result["baseline_comparison"] = paired_retrieval_delta(
                derivative["baseline"], current_paired
            )
        else:
            result["baseline_comparison"] = {
                "success": False,
                "reason": derivative.get("reason", "baseline_symbols_unavailable"),
            }
            if "goldset_version" not in baseline:
                legacy = regrade_legacy_path_only_baseline(
                    baseline, original_sources, original_hashes
                )
                result["legacy_baseline_path_only_diagnostic"] = {
                    key: value for key, value in legacy.items() if key != "rows"
                }
                result["legacy_baseline_path_only_diagnostic"]["rows"] = legacy.get("rows", [])
        result["success"] = result["success"] and result["baseline_comparison"]["success"]
    return result


def regrade_captured_baseline_symbols(baseline, source_text_by_path, current_hashes):
    """Regrade v2 captures only when source hashes and the full case contract match."""
    if not isinstance(baseline, dict) or not isinstance(baseline.get("source_hashes"), dict):
        return {"success": False, "status": "unavailable", "reason": "baseline_source_hashes_missing"}
    if baseline.get("goldset_version") != GOLDSET_VERSION:
        return {"success": False, "status": "unavailable", "reason": "goldset_version_mismatch"}
    expected_contracts = goldset_contract()
    if baseline.get("goldset_contract") != expected_contracts:
        return {"success": False, "status": "unavailable", "reason": "goldset_contract_mismatch"}
    if not isinstance(source_text_by_path, dict) or not isinstance(current_hashes, dict):
        return {"success": False, "status": "unavailable", "reason": "source_snapshot_invalid"}
    if set(source_text_by_path) != set(current_hashes) or set(current_hashes) != set(baseline["source_hashes"]):
        return {"success": False, "status": "unavailable", "reason": "source_snapshot_keys_mismatch"}
    for path, text in source_text_by_path.items():
        if (not isinstance(text, str) or not isinstance(current_hashes.get(path), str)
                or hashlib.sha256(text.encode("utf-8")).hexdigest() != current_hashes[path]):
            return {"success": False, "status": "unavailable", "reason": "source_snapshot_hash_mismatch", "path": path}
    for path in baseline["source_hashes"]:
        if baseline["source_hashes"].get(path) != current_hashes.get(path):
            return {
                "success": False,
                "status": "unavailable",
                "reason": "baseline_source_hash_mismatch",
                "path": path,
            }

    rows = baseline.get("retrieval")
    architecture_rows = baseline.get("architecture_diagnostics")
    if not isinstance(rows, list) or not isinstance(architecture_rows, list):
        return {"success": False, "status": "unavailable", "reason": "baseline_retrieval_rows_missing"}
    captured_rows = rows + architecture_rows
    by_case = {row.get("case"): row for row in captured_rows if isinstance(row, dict)}
    if (len(by_case) != len(captured_rows)
            or set(by_case) != {item["case"] for item in expected_contracts}):
        return {"success": False, "status": "unavailable", "reason": "baseline_retrieval_cases_invalid"}

    regraded_rows = []
    for contract in expected_contracts:
        case = contract["case"]
        query = contract["query"]
        relevant = contract["expected_path"]
        expected_symbols = contract["expected_symbols"]
        intent = contract["intent"]
        k = contract["k"]
        original = by_case.get(case)
        if (not isinstance(original, dict) or original.get("query") != query
                or original.get("expected_path") != relevant
                or original.get("expected_symbols") != expected_symbols
                or original.get("intent") != intent or original.get("k") != k
                or not isinstance(original.get("symbols"), list)):
            return {
                "success": False,
                "status": "unavailable",
                "reason": "baseline_symbol_capture_missing_or_contract_changed",
                "case": case,
            }
        measured = retrieval_metrics(
            {"success": True, "symbols": original["symbols"]},
            {relevant},
            source_text_by_path,
            k=k,
            expected_symbols=expected_symbols,
            intent=intent,
        )
        measured["k"] = k
        regraded_rows.append({
            "case": case,
            "query": query,
            "expected_path": relevant,
            "expected_symbols": expected_symbols,
            "intent": intent,
            "k": k,
            "target_status": "declared_exact_target",
            "metrics": measured,
            "symbols": original["symbols"],
        })

    derived = {
        **baseline,
        "retrieval": regraded_rows,
        "architecture_diagnostics": [],
        "source_hashes": dict(current_hashes),
        "derivative_regrade": {
            "scope": "regraded_captured_v2_baseline_symbols_against_verified_original_source",
            "original_baseline_modified": False,
            "source_hashes_verified": True,
            "goldset_version": GOLDSET_VERSION,
            "regraded_case_count": len(regraded_rows),
        },
    }
    return {"success": True, "status": "regraded", "baseline": derived}


def _read_baseline_sources(baseline, source_root):
    """Load a caller-provided original source snapshot and verify every pinned hash."""
    if (not isinstance(source_root, Path) or not source_root.is_absolute()
            or not source_root.is_dir() or source_root.is_symlink()
            or getattr(source_root, "is_junction", lambda: False)()):
        return {}, {}
    pinned = baseline.get("source_hashes") if isinstance(baseline, dict) else None
    if not isinstance(pinned, dict) or not pinned:
        return {}, {}
    texts, hashes = {}, {}
    resolved_root = source_root.resolve(strict=True)
    for relative, expected_hash in pinned.items():
        if (not isinstance(relative, str) or not isinstance(expected_hash, str)
                or len(expected_hash) != 64
                or any(char not in "0123456789abcdef" for char in expected_hash.lower())):
            return {}, {}
        candidate = source_root / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            return {}, {}
        try:
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
                return {}, {}
            current = candidate
            while current != source_root:
                if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
                    return {}, {}
                current = current.parent
            data = resolved.read_bytes()
        except (OSError, ValueError):
            return {}, {}
        if len(data) > 4 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected_hash:
            return {}, {}
        try:
            texts[relative] = data.decode("utf-8")
        except UnicodeDecodeError:
            return {}, {}
        hashes[relative] = expected_hash
    return texts, hashes


def regrade_legacy_path_only_baseline(baseline, source_text_by_path, current_hashes):
    """Retain v1 symbol regrading as historical diagnostics, never as a v2 pair."""
    if (not isinstance(baseline, dict) or "goldset_version" in baseline
            or not isinstance(baseline.get("source_hashes"), dict)):
        return {"status": "unavailable", "reason": "not_legacy_path_only_baseline",
                "paired_comparable": False, "rows": []}
    if (set(source_text_by_path) != set(baseline["source_hashes"])
            or set(current_hashes) != set(baseline["source_hashes"])):
        return {"status": "unavailable", "reason": "source_snapshot_keys_mismatch",
                "paired_comparable": False, "rows": []}
    for path, text in source_text_by_path.items():
        if (not isinstance(text, str)
                or hashlib.sha256(text.encode("utf-8")).hexdigest() != current_hashes[path]
                or current_hashes[path] != baseline["source_hashes"].get(path)):
            return {"status": "unavailable", "reason": "baseline_source_hash_mismatch",
                    "paired_comparable": False, "rows": []}
    contracts = [
        {"case": case, "query": query, "expected_path": path,
         "expected_symbols": {path: [symbol]}, "intent": intent, "k": 5}
        for case, query, path, symbol, intent in GOLD if case != "explicit-test-intent"
    ] + [
        {"case": case, "query": query, "expected_path": path,
         "expected_symbols": {path: [symbol]}, "intent": intent, "k": 5}
        for case, query, path, symbol, intent in LEGACY_GOLD
    ] + [
        {"case": case, "query": query, "expected_path": path,
         "expected_symbols": {path: [LEGACY_ARCHITECTURE_TARGETS[case][0]]},
         "intent": LEGACY_ARCHITECTURE_TARGETS[case][1], "k": 5}
        for case, query, path in ARCHITECTURE_QUERIES
    ]
    captured = baseline.get("retrieval")
    architecture = baseline.get("architecture_diagnostics")
    if not isinstance(captured, list) or not isinstance(architecture, list):
        return {"status": "unavailable", "reason": "legacy_symbol_capture_missing",
                "paired_comparable": False, "rows": []}
    by_case = {row.get("case"): row for row in captured + architecture if isinstance(row, dict)}
    if len(by_case) != len(captured) + len(architecture) or set(by_case) != {c["case"] for c in contracts}:
        return {"status": "unavailable", "reason": "legacy_case_set_mismatch",
                "paired_comparable": False, "rows": []}
    rows = []
    for contract in contracts:
        source = by_case[contract["case"]]
        if (source.get("query") != contract["query"]
                or source.get("expected_path") != contract["expected_path"]
                or not isinstance(source.get("symbols"), list)):
            return {"status": "unavailable", "reason": "legacy_capture_contract_mismatch",
                    "paired_comparable": False, "rows": []}
        metrics = retrieval_metrics(
            {"success": True, "symbols": source["symbols"]},
            {contract["expected_path"]}, source_text_by_path, k=contract["k"],
            expected_symbols=contract["expected_symbols"], intent=contract["intent"],
        )
        metrics["k"] = contract["k"]
        rows.append({**contract, "metrics": metrics, "symbols": source["symbols"]})
    return {"status": "regraded_limited_legacy_path_only", "paired_comparable": False,
            "original_baseline_modified": False, "row_count": len(rows), "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-source-root", type=Path)
    args = parser.parse_args()
    baseline_bytes = args.baseline.read_bytes() if args.baseline else None
    baseline = json.loads(baseline_bytes) if baseline_bytes is not None else None
    result = run(args.root, baseline=baseline, baseline_source_root=args.baseline_source_root)
    if baseline_bytes is not None:
        result["baseline_sha256"] = hashlib.sha256(baseline_bytes).hexdigest()
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"success": result["success"], "cases": len(result["retrieval"]),
                      "scope": result["scope"]}))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
