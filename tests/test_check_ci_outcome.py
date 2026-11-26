"""Tests for tools/check_ci_outcome.py — LAH-003 regression tests.

Verifies that the outcome aggregator:
- Rejects 0-collected test runs (false green).
- Rejects suites with failures or errors.
- Rejects missing required suites.
- Rejects coverage reports marked with NOT_COLLECTED status.
- Accepts authentic passing suites with >0 tests.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from tools.check_ci_outcome import (
    check_coverage_json,
    check_junit_xml,
    check_outcome_directory,
)


def _write_junit(path: Path, tests: int, failures: int = 0, errors: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    xml = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="utf-8"?>
        <testsuites>
          <testsuite name="pytest" tests="{tests}" failures="{failures}" errors="{errors}" time="1.0">
            {'<testcase classname="test_mod" name="test_foo" time="0.01"/>' * (tests - failures - errors)}
            {'<testcase classname="test_mod" name="test_fail"><failure message="boom">trace</failure></testcase>' * failures}
            {'<testcase classname="test_mod" name="test_err"><error message="crash">trace</error></testcase>' * errors}
          </testsuite>
        </testsuites>
    """)
    path.write_text(xml, encoding="utf-8")


def test_junit_rejects_zero_collected_tests(tmp_path: Path) -> None:
    xml_path = tmp_path / "junit-empty.xml"
    _write_junit(xml_path, tests=0)
    result = check_junit_xml(xml_path, min_tests=1)
    assert not result["ok"]
    assert "false-green: 0 or fewer than 1 tests executed" in result["error"]


def test_junit_rejects_failures_and_errors(tmp_path: Path) -> None:
    xml_fail = tmp_path / "junit-fail.xml"
    _write_junit(xml_fail, tests=10, failures=1)
    res_fail = check_junit_xml(xml_fail)
    assert not res_fail["ok"]
    assert "failures=1" in res_fail["error"]

    xml_err = tmp_path / "junit-err.xml"
    _write_junit(xml_err, tests=5, errors=2)
    res_err = check_junit_xml(xml_err)
    assert not res_err["ok"]
    assert "errors=2" in res_err["error"]


def test_junit_accepts_passing_suite(tmp_path: Path) -> None:
    xml_pass = tmp_path / "junit-pass.xml"
    _write_junit(xml_pass, tests=25, failures=0, errors=0)
    result = check_junit_xml(xml_pass)
    assert result["ok"]
    assert result["tests"] == 25


def test_coverage_json_rejects_not_collected_dummy(tmp_path: Path) -> None:
    cov_path = tmp_path / "coverage.json"
    cov_path.write_text(json.dumps({
        "status": "NOT_COLLECTED",
        "reason": "coverage_data_absent",
    }), encoding="utf-8")
    result = check_coverage_json(cov_path)
    assert not result["ok"]
    assert "coverage was not collected" in result["error"]


def test_coverage_json_accepts_valid_report(tmp_path: Path) -> None:
    cov_path = tmp_path / "coverage.json"
    cov_path.write_text(json.dumps({
        "meta": {"branch_coverage": True},
        "totals": {"percent_covered": 85.5},
        "files": {},
    }), encoding="utf-8")
    result = check_coverage_json(cov_path)
    assert result["ok"]


def test_outcome_directory_checks_all_and_enforces_required_suites(tmp_path: Path) -> None:
    suite_a = tmp_path / "suite-a.xml"
    suite_b = tmp_path / "sub" / "suite-b.xml"
    _write_junit(suite_a, tests=5)
    _write_junit(suite_b, tests=12)

    res = check_outcome_directory(tmp_path, required_suite_names=["suite-a.xml", "suite-b.xml"])
    assert res["ok"]
    assert res["total_suites_checked"] == 2

    # Fails when a required suite is missing
    res_missing = check_outcome_directory(tmp_path, required_suite_names=["suite-c.xml"])
    assert not res_missing["ok"]
    assert any("required suite report missing: suite-c.xml" in f for f in res_missing["failures"])
