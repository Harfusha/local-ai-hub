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

GOLD = (
    ("mcp-entrypoint", "local_ai_status", "src/local_ai_hub/mcp_server.py"),
    ("http-deadline", "RequestHeadReader", "src/local_ai_hub/http_transport.py"),
    ("budget-failure", "BudgetUnavailableError", "src/local_ai_hub/agent_policy.py"),
    ("async-owner", "AsyncJobManager", "src/local_ai_hub/async_jobs.py"),
    ("context-artifact", "persist_compiled_context", "src/local_ai_hub/context_delivery.py"),
    ("review-entrypoint", "LocalAIServices", "src/local_ai_hub/services.py"),
    ("explicit-test-intent", "test_public_guide_uses_explicit_help_fields_without_health_queries",
     "tests/test_audit_action_guide_remediation.py"),
)

ARCHITECTURE_QUERIES = (
    ("http-architecture", "HTTP server request header deadline", "src/local_ai_hub/http_transport.py"),
    ("async-architecture", "asynchronous job lifecycle cancellation ownership", "src/local_ai_hub/async_jobs.py"),
    ("mcp-architecture", "MCP public tool entrypoints", "src/local_ai_hub/mcp_server.py"),
)


def run(root):
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("authorized absolute repository root required")
    sources, hashes = {}, {}
    paths = sorted({path for _, _, path in GOLD} | {
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
    results, architecture = [], []
    with tempfile.TemporaryDirectory(prefix="hub-audit-eval-") as state:
        config = {"server": {"state_dir": state}, "search": {"max_files": len(paths)}}
        repository = RepositoryTools(config)
        index = CodeIndex(config, repository)
        try:
            built = index.update_files_batch(str(root), list(hashes.items()))
            if built.get("success") is not True:
                raise RuntimeError("bounded goldset index build failed")
            for case, query, relevant in GOLD:
                report = index.query(str(root), query, limit=5, verify_freshness=True)
                metrics = retrieval_metrics(report, {relevant}, sources, k=5)
                results.append({"case": case, "query": query, "expected_path": relevant,
                                "metrics": metrics, "symbols": report.get("symbols", [])})
            for case, query, relevant in ARCHITECTURE_QUERIES:
                report = index.query(str(root), query, limit=5, verify_freshness=True)
                architecture.append({"case": case, "query": query, "expected_path": relevant,
                    "metrics": retrieval_metrics(report, {relevant}, sources, k=5),
                    "symbols": report.get("symbols", [])})
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
    valid = all(item["metrics"]["status"] == "measured"
                and item["metrics"]["recall_at_k"] == 1
                and item["metrics"]["citation_validity"] == 1 for item in results)
    return {
        "success": valid and all(item["measurement"]["success"] == item["expected_accepted"] for item in faithfulness),
        "scope": "bounded_named_current_source_goldset_not_full_repository_or_model_quality",
        "source_hashes": hashes, "retrieval": results, "review_contract_cases": faithfulness,
        "architecture_diagnostics": architecture,
        "answer_sufficiency_scope": "expected_symbol_locations_only_not_generated_answers",
        "model_quality_verified": False, "ranking_changed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    result = run(args.root)
    if args.baseline:
        baseline_bytes = args.baseline.read_bytes()
        result["baseline_sha256"] = hashlib.sha256(baseline_bytes).hexdigest()
        result["baseline_comparison"] = paired_retrieval_delta(json.loads(baseline_bytes), result)
        result["success"] = result["success"] and result["baseline_comparison"]["success"]
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"success": result["success"], "cases": len(result["retrieval"]),
                      "scope": result["scope"]}))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
