from __future__ import annotations

import copy
import json
import sys

import pytest

from tools import check_critical_coverage as critical_coverage


MODULE = "src/local_ai_hub/agent_memory.py"
FUNCTION = "src/local_ai_hub/agent_memory.py::MemoryStore.record"


def _summary(covered: int, total: int) -> dict[str, int]:
    return {"covered_branches": covered, "num_branches": total}


def _report(files: dict) -> dict:
    return {"meta": {"format": 3, "branch_coverage": True}, "files": files}


def _module(covered: int = 8, total: int = 10, *, functions: dict | None = None) -> dict:
    return {
        "summary": _summary(covered, total),
        "functions": {
            name: {"summary": _summary(*counts)}
            for name, counts in (functions or {}).items()
        },
    }


def _baseline(report: dict, *, modules=None, functions=()):
    return critical_coverage.make_baseline(
        report,
        list(modules if modules is not None else [MODULE]),
        "candidate-a",
        "cohort-a",
        functions,
    )


def test_optional_requirements_keep_isolated_fixture_valid_and_required_entries_fail_closed():
    report = _report({MODULE: _module(functions={"MemoryStore.record": (8, 10)})})
    baseline = _baseline(report, functions=[FUNCTION])

    assert critical_coverage.check_report(report, baseline)["success"] is True
    checked = critical_coverage.check_report(
        report,
        baseline,
        required_modules=[MODULE, "src/local_ai_hub/missing.py"],
        required_functions=[FUNCTION, "src/local_ai_hub/missing.py::Missing.call"],
    )
    assert checked["success"] is False
    assert any("required critical module missing" in error for error in checked["errors"])
    assert any("required critical function missing" in error for error in checked["errors"])


@pytest.mark.parametrize(
    ("function_entry", "error_fragment"),
    [
        pytest.param({"summary": _summary(7, 10)}, "function branch coverage regressed", id="regression"),
        pytest.param({"summary": {"covered_branches": True, "num_branches": 10}}, "invalid branch counts", id="boolean-count"),
        pytest.param({}, "critical function missing", id="missing-summary"),
    ],
)
def test_function_ratchet_reads_format3_counts_and_fails_closed(function_entry, error_fragment):
    baseline_report = _report({MODULE: _module(functions={"MemoryStore.record": (8, 10)})})
    baseline = _baseline(baseline_report, functions=[FUNCTION])
    current = _report({MODULE: {**_module(), "functions": {"MemoryStore.record": function_entry}}})

    checked = critical_coverage.check_report(current, baseline, required_functions=[FUNCTION])

    assert checked["success"] is False
    assert any(error_fragment in error for error in checked["errors"])


def test_existing_baseline_extension_preserves_old_metrics_and_adds_measured_provenance():
    existing_report = _report({MODULE: _module(9, 10)})
    existing = _baseline(existing_report)
    old_provenance = {
        key: copy.deepcopy(existing[key])
        for key in ("schema_version", "environment", "repository_revision", "cohort", "source_report_sha256")
    }
    new_module = "src/local_ai_hub/new_critical.py"
    current_report = _report({
        MODULE: _module(9, 10, functions={"MemoryStore.record": (3, 4)}),
        new_module: _module(4, 5),
    })

    extended = critical_coverage.extend_baseline(
        current_report,
        existing,
        [MODULE, new_module],
        [FUNCTION],
        "candidate-b",
        "cohort-b",
    )

    assert {key: extended[key] for key in old_provenance} == old_provenance
    assert extended["modules"][MODULE] == existing["modules"][MODULE]
    assert extended["modules"][new_module] == _summary(4, 5)
    assert extended["functions"][FUNCTION] == _summary(3, 4)
    assert extended["extension_provenance"] == [{
        "repository_revision": "candidate-b",
        "cohort": "cohort-b",
        "source_report_sha256": critical_coverage._report_sha256(current_report),
        "added_modules": [new_module],
        "added_functions": [FUNCTION],
    }]
    assert "functions" not in existing


def test_record_refuses_regressed_existing_threshold_without_rewriting_file(tmp_path, monkeypatch, capsys):
    previous_report = _report({MODULE: _module(9, 10)})
    baseline = _baseline(previous_report)
    baseline_path = tmp_path / "critical-baseline.json"
    original_text = json.dumps(baseline, indent=2) + "\n"
    baseline_path.write_text(original_text, encoding="utf-8")
    report_path = tmp_path / "coverage.json"
    report_path.write_text(json.dumps(_report({MODULE: _module(8, 10)})), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_critical_coverage.py", str(report_path), "--baseline", str(baseline_path), "--record-baseline", "--revision", "candidate-b", "--cohort", "cohort-b"],
    )

    assert critical_coverage.main() == 1
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is False
    assert "existing baseline cannot be extended" in output["errors"][0]
    assert baseline_path.read_text(encoding="utf-8") == original_text


def test_cli_check_requires_all_critical_modules_and_functions(tmp_path, monkeypatch, capsys):
    report_path = tmp_path / "coverage.json"
    baseline_path = tmp_path / "critical-baseline.json"
    only_module = critical_coverage.critical_module_paths()[0]
    report_path.write_text(json.dumps(_report({only_module: _module()})), encoding="utf-8")
    baseline_path.write_text(json.dumps(_baseline(_report({only_module: _module()}), modules=[only_module])), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check_critical_coverage.py", str(report_path), "--baseline", str(baseline_path)])

    assert critical_coverage.main() == 1
    errors = json.loads(capsys.readouterr().out)["errors"]
    assert any("required critical module missing" in error for error in errors)
    assert any("required critical function missing" in error for error in errors)


@pytest.mark.parametrize("format_value", [None, False, 1, 2, 4, "3"])
def test_function_counts_require_the_measured_format3_contract(format_value):
    report = _report({MODULE: _module(functions={"MemoryStore.record": (8, 10)})})
    report["meta"]["format"] = format_value
    with pytest.raises(ValueError, match="format 3"):
        _baseline(report, functions=[FUNCTION])


def test_normalized_source_path_collisions_and_boolean_schema_reject():
    report = _report({MODULE: _module()})
    baseline = _baseline(report)
    report["files"][MODULE.replace("/", "\\")] = _module(10, 10)
    assert critical_coverage.check_report(report, baseline)["success"] is False
    baseline["schema_version"] = True
    assert critical_coverage.check_report(_report({MODULE: _module()}), baseline)["success"] is False

