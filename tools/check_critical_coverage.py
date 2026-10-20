"""Fail-closed, environment-specific branch coverage ratchet."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

CRITICAL = (
    "agent_policy", "async_jobs", "file_locks", "http_transport",
    "context_delivery", "command_batches", "dashboard_contracts", "shutdown",
    "owned_model", "model_lifecycle", "semantic_quality",
)


def environment():
    return f"{sys.platform}-py{sys.version_info.major}.{sys.version_info.minor}"


def _counts(report, path):
    if not isinstance(report, dict) or report.get("meta", {}).get("branch_coverage") is not True:
        raise ValueError("measured branch coverage is required")
    files = report.get("files")
    if not isinstance(files, dict):
        raise ValueError("coverage files are missing")
    normalized = {key.replace("\\", "/"): value for key, value in files.items()}
    item = normalized.get(path)
    if not isinstance(item, dict) or not isinstance(item.get("summary"), dict):
        raise ValueError(f"critical module missing: {path}")
    summary = item["summary"]
    covered, total = summary.get("covered_branches"), summary.get("num_branches")
    if type(total) is not int or total <= 0 or type(covered) is not int or not 0 <= covered <= total:
        raise ValueError(f"invalid branch counts: {path}")
    return covered, total


def make_baseline(report, paths, revision, cohort):
    if not isinstance(revision, str) or not revision.strip() or not isinstance(cohort, str) or not cohort.strip():
        raise ValueError("revision and test cohort provenance are required")
    if not paths or len(set(paths)) != len(paths):
        raise ValueError("explicit unique critical modules are required")
    modules = {}
    for path in paths:
        covered, total = _counts(report, path)
        modules[path] = {"covered_branches": covered, "num_branches": total}
    return {
        "schema_version": 1, "environment": environment(), "repository_revision": revision,
        "cohort": cohort, "modules": modules,
        "source_report_sha256": hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest(),
    }


def check_report(report, baseline):
    errors = []
    if not isinstance(baseline, dict) or baseline.get("schema_version") != 1:
        return {"success": False, "errors": ["unsupported baseline schema"]}
    if baseline.get("environment") != environment():
        errors.append("baseline environment differs")
    if not baseline.get("repository_revision") or not baseline.get("cohort") or not baseline.get("source_report_sha256"):
        errors.append("baseline provenance is missing")
    modules = baseline.get("modules")
    if not isinstance(modules, dict) or not modules:
        return {"success": False, "errors": [*errors, "critical modules missing"]}
    for path, target in modules.items():
        try:
            covered, total = _counts(report, path)
            previous, denominator = target["covered_branches"], target["num_branches"]
            if type(previous) is not int or type(denominator) is not int or denominator <= 0 or not 0 <= previous <= denominator:
                raise ValueError(f"invalid baseline counts: {path}")
            if covered * denominator < previous * total:
                errors.append(f"branch coverage regressed: {path} ({covered}/{total} < {previous}/{denominator})")
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc))
    return {"success": not errors, "environment": environment(), "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--record-baseline", action="store_true")
    parser.add_argument("--revision", default="")
    parser.add_argument("--cohort", default="")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        if args.record_baseline:
            value = make_baseline(report, [f"src/local_ai_hub/{name}.py" for name in CRITICAL], args.revision, args.cohort)
            args.baseline.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            result = {"success": True, "baseline_recorded": str(args.baseline)}
        else:
            result = check_report(report, json.loads(args.baseline.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        result = {"success": False, "errors": [str(exc)]}
    print(json.dumps(result))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
