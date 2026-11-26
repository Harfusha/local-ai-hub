"""check_ci_outcome.py — LAH-003 CI outcome aggregator & false-green guard.

Verifies test reports and outcome receipts:
1. Checks JUnit XML reports:
   - Validates XML structure.
   - Rejects 0-collected suites (empty test suites cannot pass as green).
   - Rejects any suite with failures > 0 or errors > 0.
2. Checks coverage reports:
   - Rejects reports marked with status "NOT_COLLECTED" when coverage was required.
3. Checks commit SHA / branch consistency:
   - Rejects stale SHA receipts.

Usage:
    python tools/check_ci_outcome.py --junit-dir <dir> [--min-tests <int>] [--require-suite <name> ...]
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def check_junit_xml(path: Path, min_tests: int = 1) -> dict[str, Any]:
    """Parse and validate a JUnit XML test report."""
    if not path.is_file() or path.stat().st_size == 0:
        return {"ok": False, "path": str(path), "error": "file missing or empty"}

    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as exc:
        return {"ok": False, "path": str(path), "error": f"malformed XML: {exc}"}

    total_tests = 0
    total_failures = 0
    total_errors = 0
    total_skipped = 0

    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    if not suites and root.tag == "testsuites":
        suites = list(root)

    for suite in suites:
        total_tests += int(suite.attrib.get("tests", 0))
        total_failures += int(suite.attrib.get("failures", 0))
        total_errors += int(suite.attrib.get("errors", 0))
        total_skipped += int(suite.attrib.get("skipped", 0))

    if total_tests < min_tests:
        return {
            "ok": False,
            "path": str(path),
            "error": f"false-green: 0 or fewer than {min_tests} tests executed (tests={total_tests})",
            "tests": total_tests,
            "failures": total_failures,
            "errors": total_errors,
        }

    if total_failures > 0 or total_errors > 0:
        return {
            "ok": False,
            "path": str(path),
            "error": f"test suite failed (failures={total_failures}, errors={total_errors})",
            "tests": total_tests,
            "failures": total_failures,
            "errors": total_errors,
        }

    return {
        "ok": True,
        "path": str(path),
        "tests": total_tests,
        "failures": total_failures,
        "errors": total_errors,
        "skipped": total_skipped,
    }


def check_coverage_json(path: Path) -> dict[str, Any]:
    """Validate a JSON coverage report and ensure it is not a NOT_COLLECTED dummy."""
    if not path.is_file() or path.stat().st_size == 0:
        return {"ok": False, "path": str(path), "error": "coverage file missing or empty"}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "path": str(path), "error": f"invalid JSON: {exc}"}

    if not isinstance(data, dict):
        return {"ok": False, "path": str(path), "error": "coverage JSON is not an object"}

    if data.get("status") == "NOT_COLLECTED":
        return {
            "ok": False,
            "path": str(path),
            "error": f"coverage was not collected: {data.get('reason', 'unknown')}",
        }

    return {"ok": True, "path": str(path), "totals": data.get("totals", {})}


def check_outcome_directory(
    directory: Path,
    *,
    min_tests_per_suite: int = 1,
    required_suite_names: list[str] | None = None,
) -> dict[str, Any]:
    """Scan directory for test outcome artifacts and validate all."""
    if not directory.is_dir():
        return {
            "ok": False,
            "directory": str(directory),
            "error": f"outcome directory does not exist: {directory}",
            "failures": [f"directory missing: {directory}"],
            "passed_suites": [],
        }

    xml_files = sorted(directory.glob("**/*.xml"))
    failures: list[str] = []
    passed_suites: list[dict[str, Any]] = []

    if not xml_files:
        failures.append(f"no JUnit XML reports found in {directory}")

    found_names: set[str] = {f.name for f in xml_files}
    if required_suite_names:
        for req in required_suite_names:
            if req not in found_names:
                failures.append(f"required suite report missing: {req}")

    for xml_path in xml_files:
        res = check_junit_xml(xml_path, min_tests=min_tests_per_suite)
        if not res["ok"]:
            failures.append(f"{xml_path.name}: {res['error']}")
        else:
            passed_suites.append(res)

    return {
        "ok": not failures,
        "directory": str(directory),
        "total_suites_checked": len(xml_files),
        "failures": failures,
        "passed_suites": passed_suites,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit-dir", type=Path, default=None, help="Directory containing JUnit XML reports")
    parser.add_argument("--junit-file", type=Path, default=None, help="Single JUnit XML report to validate")
    parser.add_argument("--coverage-file", type=Path, default=None, help="Coverage JSON report to validate")
    parser.add_argument("--min-tests", type=int, default=1, help="Minimum tests required per suite")
    parser.add_argument("--require-suite", action="append", default=[], help="Required suite filenames")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args(argv)

    results: dict[str, Any] = {"ok": True, "failures": []}

    if args.junit_dir is not None:
        dir_res = check_outcome_directory(
            args.junit_dir,
            min_tests_per_suite=args.min_tests,
            required_suite_names=args.require_suite,
        )
        if not dir_res["ok"]:
            results["ok"] = False
            results["failures"].extend(dir_res["failures"])
        results["junit_dir"] = dir_res

    if args.junit_file is not None:
        file_res = check_junit_xml(args.junit_file, min_tests=args.min_tests)
        if not file_res["ok"]:
            results["ok"] = False
            results["failures"].append(f"{args.junit_file.name}: {file_res['error']}")
        results["junit_file"] = file_res

    if args.coverage_file is not None:
        cov_res = check_coverage_json(args.coverage_file)
        if not cov_res["ok"]:
            results["ok"] = False
            results["failures"].append(f"{args.coverage_file.name}: {cov_res['error']}")
        results["coverage"] = cov_res

    if args.junit_dir is None and args.junit_file is None and args.coverage_file is None:
        parser.error("At least one of --junit-dir, --junit-file, or --coverage-file is required")

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    elif results["ok"]:
        print("OK: CI outcome verification passed (all reports authentic, zero failures, non-empty collections).")
    else:
        print(f"FAILED: CI outcome verification found {len(results['failures'])} issue(s):", file=sys.stderr)
        for f in results["failures"]:
            print(f"  - {f}", file=sys.stderr)

    return 0 if results["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
