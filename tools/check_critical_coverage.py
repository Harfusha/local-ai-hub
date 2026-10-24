"""Fail-closed, environment-specific branch coverage ratchet."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

CRITICAL = (
    "agent_policy", "async_jobs", "file_locks", "http_transport",
    "context_delivery", "command_batches", "dashboard_contracts", "shutdown",
    "owned_model", "model_lifecycle", "semantic_quality",
    "agent_identity", "agent_memory", "commands", "http_server",
)
REQUIRED_FUNCTIONS = (
    "src/local_ai_hub/http_server.py::Handler._require_authorized",
    "src/local_ai_hub/http_server.py::Handler._authorized",
    "src/local_ai_hub/commands.py::CommandBroker.run",
    "src/local_ai_hub/agent_memory.py::MemoryStore.record",
)


def critical_module_paths():
    return tuple(f"src/local_ai_hub/{name}.py" for name in CRITICAL)


def environment():
    return f"{sys.platform}-py{sys.version_info.major}.{sys.version_info.minor}"


def _files(report):
    meta = report.get("meta") if isinstance(report, dict) else None
    if not isinstance(meta, dict) or meta.get("branch_coverage") is not True:
        raise ValueError("measured branch coverage is required")
    files = report.get("files")
    if not isinstance(files, dict):
        raise ValueError("coverage files are missing")
    if any(not isinstance(key, str) for key in files):
        raise ValueError("coverage file paths are malformed")
    normalized = {key.replace("\\", "/"): value for key, value in files.items()}
    if len(normalized) != len(files):
        raise ValueError("coverage file paths collide after normalization")
    return normalized


def _validated_counts(covered, total, label):
    if type(total) is not int or total <= 0 or type(covered) is not int or not 0 <= covered <= total:
        raise ValueError(f"invalid branch counts: {label}")
    return covered, total


def _counts(report, path):
    normalized = _files(report)
    item = normalized.get(path)
    if not isinstance(item, dict) or not isinstance(item.get("summary"), dict):
        raise ValueError(f"critical module missing: {path}")
    summary = item["summary"]
    covered, total = summary.get("covered_branches"), summary.get("num_branches")
    return _validated_counts(covered, total, path)


def _function_counts(report, identifier):
    meta = report.get("meta") if isinstance(report, dict) else None
    if not isinstance(meta, dict) or type(meta.get("format")) is not int or meta["format"] != 3:
        raise ValueError("coverage format 3 is required for function branch counts")
    path, separator, name = identifier.partition("::") if isinstance(identifier, str) else ("", "", "")
    if not separator or not path or not name:
        raise ValueError(f"invalid required function identifier: {identifier}")
    item = _files(report).get(path)
    functions = item.get("functions") if isinstance(item, dict) else None
    function = functions.get(name) if isinstance(functions, dict) else None
    summary = function.get("summary") if isinstance(function, dict) else None
    if not isinstance(summary, dict):
        raise ValueError(f"critical function missing: {identifier}")
    return _validated_counts(
        summary.get("covered_branches"), summary.get("num_branches"), identifier,
    )


def _report_sha256(report):
    return hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()


def make_baseline(report, paths, revision, cohort, functions=()):
    if not isinstance(revision, str) or not revision.strip() or not isinstance(cohort, str) or not cohort.strip():
        raise ValueError("revision and test cohort provenance are required")
    if not paths or len(set(paths)) != len(paths):
        raise ValueError("explicit unique critical modules are required")
    modules = {}
    for path in paths:
        covered, total = _counts(report, path)
        modules[path] = {"covered_branches": covered, "num_branches": total}
    function_ids = list(functions)
    if len(function_ids) != len(set(function_ids)):
        raise ValueError("explicit unique critical functions are required")
    function_metrics = {}
    for identifier in function_ids:
        covered, total = _function_counts(report, identifier)
        function_metrics[identifier] = {"covered_branches": covered, "num_branches": total}
    baseline = {
        "schema_version": 1, "environment": environment(), "repository_revision": revision,
        "cohort": cohort, "modules": modules,
        "source_report_sha256": _report_sha256(report),
    }
    if function_metrics:
        baseline["functions"] = function_metrics
    return baseline


def _compare_metrics(report, baseline_metrics, counter, label, errors):
    for identifier, target in baseline_metrics.items():
        try:
            covered, total = counter(report, identifier)
            if not isinstance(target, dict):
                raise ValueError(f"invalid baseline counts: {identifier}")
            previous, denominator = target["covered_branches"], target["num_branches"]
            _validated_counts(previous, denominator, f"baseline {identifier}")
            if covered * denominator < previous * total:
                errors.append(
                    f"{label} regressed: {identifier} ({covered}/{total} < {previous}/{denominator})"
                )
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            errors.append(str(exc))


def check_report(report, baseline, *, required_modules=None, required_functions=None):
    errors = []
    if not isinstance(baseline, dict) or type(baseline.get("schema_version")) is not int or baseline["schema_version"] != 1:
        return {"success": False, "errors": ["unsupported baseline schema"]}
    if baseline.get("environment") != environment():
        errors.append("baseline environment differs")
    if not baseline.get("repository_revision") or not baseline.get("cohort") or not baseline.get("source_report_sha256"):
        errors.append("baseline provenance is missing")
    modules = baseline.get("modules")
    if not isinstance(modules, dict) or not modules:
        return {"success": False, "errors": [*errors, "critical modules missing"]}
    for path in required_modules or ():
        if path not in modules:
            errors.append(f"required critical module missing from baseline: {path}")
    _compare_metrics(report, modules, _counts, "branch coverage", errors)

    functions = baseline.get("functions", {})
    if not isinstance(functions, dict):
        errors.append("critical functions missing")
        functions = {}
    for identifier in required_functions or ():
        if identifier not in functions:
            errors.append(f"required critical function missing from baseline: {identifier}")
    _compare_metrics(report, functions, _function_counts, "function branch coverage", errors)
    return {"success": not errors, "environment": environment(), "errors": errors}


def extend_baseline(report, existing, paths, functions, revision, cohort):
    """Preserve every existing threshold and provenance while adding measured metrics."""
    checked = check_report(report, existing)
    if not checked["success"]:
        raise ValueError("existing baseline cannot be extended: " + "; ".join(checked["errors"]))
    if not isinstance(revision, str) or not revision.strip() or not isinstance(cohort, str) or not cohort.strip():
        raise ValueError("revision and test cohort provenance are required")

    value = copy.deepcopy(existing)
    modules = value["modules"]
    stored_functions = value.setdefault("functions", {})
    if not isinstance(stored_functions, dict):
        raise ValueError("baseline functions are malformed")
    extension_provenance = value.setdefault("extension_provenance", [])
    if not isinstance(extension_provenance, list):
        raise ValueError("baseline extension provenance is malformed")
    added_modules = []
    added_functions = []
    for path in paths:
        if path not in modules:
            covered, total = _counts(report, path)
            modules[path] = {"covered_branches": covered, "num_branches": total}
            added_modules.append(path)
    for identifier in functions:
        if identifier not in stored_functions:
            covered, total = _function_counts(report, identifier)
            stored_functions[identifier] = {"covered_branches": covered, "num_branches": total}
            added_functions.append(identifier)
    if added_modules or added_functions:
        extension_provenance.append({
            "repository_revision": revision,
            "cohort": cohort,
            "source_report_sha256": _report_sha256(report),
            "added_modules": added_modules,
            "added_functions": added_functions,
        })
    return value


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
            paths = critical_module_paths()
            if args.baseline.exists():
                existing = json.loads(args.baseline.read_text(encoding="utf-8"))
                value = extend_baseline(report, existing, paths, REQUIRED_FUNCTIONS, args.revision, args.cohort)
            else:
                value = make_baseline(report, paths, args.revision, args.cohort, REQUIRED_FUNCTIONS)
            args.baseline.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            result = {"success": True, "baseline_recorded": str(args.baseline)}
        else:
            result = check_report(
                report,
                json.loads(args.baseline.read_text(encoding="utf-8")),
                required_modules=critical_module_paths(),
                required_functions=REQUIRED_FUNCTIONS,
            )
    except (OSError, ValueError, TypeError) as exc:
        result = {"success": False, "errors": [str(exc)]}
    print(json.dumps(result))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
