from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from tools import ci_diagnostics


def test_annotation_escapes_workflow_syntax_and_bounds_payload(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    ci_diagnostics.emit_error("start%\r\n::notice::injection\n" + "x" * 20_000 + "END")
    output = capsys.readouterr().out
    assert output.startswith("::error title=Local AI Hub CI failure::start%25%0D%0A")
    assert output.count("\n") == 1
    assert "%0A::notice::injection%0A" in output
    assert output.endswith("END\n")
    assert len(output) < 12_000


def test_annotation_handles_console_encodings_without_emoji(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    buffer = io.BytesIO()
    stdout = io.TextIOWrapper(buffer, encoding="cp1252")
    monkeypatch.setattr(ci_diagnostics.sys, "stdout", stdout)

    ci_diagnostics.emit_error("failure 🚀")
    stdout.flush()

    assert buffer.getvalue().decode("ascii").rstrip("\r\n").endswith(r"failure \U0001f680")


def test_tail_tee_preserves_full_output_with_bounded_memory():
    target = io.StringIO()
    tee = ci_diagnostics.TailTee(target)
    text = "before" + "x" * 20_000 + "after"
    assert tee.write(text) == len(text)
    tee.flush()
    assert target.getvalue() == text
    assert len(tee.tail) <= ci_diagnostics.MAX_MESSAGE_CHARS
    assert tee.tail.endswith("after")


@pytest.mark.parametrize("code", [0, 1, 7])
def test_selftest_preserves_output_and_exit_code(monkeypatch, capsys, code):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    def main():
        print("actual selftest output")
        return code

    assert ci_diagnostics.run_selftest(main) == code
    output = capsys.readouterr().out
    assert output.startswith("actual selftest output\n")
    assert ("::error" in output) is (code != 0)


def test_selftest_exception_is_reported_and_reraised(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    error = ValueError("original failure")

    def main():
        raise error

    with pytest.raises(ValueError) as caught:
        ci_diagnostics.run_selftest(main)
    assert caught.value is error
    assert "ValueError: original failure" in capsys.readouterr().out


@pytest.mark.parametrize("error", [SystemExit(4), KeyboardInterrupt()])
def test_selftest_preserves_control_flow_exceptions(monkeypatch, capsys, error):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    def main():
        raise error

    with pytest.raises(type(error)) as caught:
        ci_diagnostics.run_selftest(main)
    assert caught.value is error
    assert capsys.readouterr().out == ""


def test_pytest_annotations_are_failure_only_and_count_bounded(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(ci_diagnostics, "_emitted", 0)
    passed = SimpleNamespace(failed=False, nodeid="passed", longreprtext="")
    failed = SimpleNamespace(failed=True, nodeid="tests/test_example.py::test_failed", longreprtext="actual assertion")
    ci_diagnostics.pytest_runtest_logreport(passed)
    for _ in range(ci_diagnostics.MAX_FAILURES + 3):
        ci_diagnostics.pytest_runtest_logreport(failed)
    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(lines) == ci_diagnostics.MAX_FAILURES
    assert all("actual assertion" in line and "test_failed" in line for line in lines)


def test_pytest_annotation_starts_after_progress_line(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(ci_diagnostics, "_emitted", 0)
    print("F", end="")
    ci_diagnostics.pytest_runtest_logreport(
        SimpleNamespace(failed=True, nodeid="test_failed", longreprtext="actual assertion")
    )
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "F"
    assert lines[1].startswith("::error title=Local AI Hub CI failure::")


def test_annotations_are_opt_in(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    ci_diagnostics.emit_error("local failure")
    assert capsys.readouterr().out == ""


def test_worker_stderr_tail_keeps_child_and_parent_failure(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(ci_diagnostics, "_emitted", 0)
    report = SimpleNamespace(
        failed=True, nodeid="test_worker",
        longreprtext="parent failure begins\n" + "x" * 10_000 + "\nparent assertion ends",
        sections=[("Captured stderr call", "y" * 10_000 + "\nchild traceback: DATABASE_LOCKED"),
                  ("Captured stdout call", "unneeded stdout")],
    )
    ci_diagnostics.pytest_runtest_logreport(report)
    output = capsys.readouterr().out
    annotations = [line for line in output.splitlines() if line.startswith("::error ")]
    assert len(annotations) == 1 and len(annotations[0]) < 12_000
    assert "parent failure begins" in annotations[0]
    assert "parent assertion ends" in annotations[0]
    assert "child traceback: DATABASE_LOCKED" in annotations[0]
    assert "unneeded stdout" not in annotations[0]


def test_absent_capture_sections_do_not_mask_failure(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(ci_diagnostics, "_emitted", 0)
    ci_diagnostics.pytest_runtest_logreport(
        SimpleNamespace(failed=True, nodeid="test_worker", longreprtext="parent failure", sections=None)
    )
    assert "parent failure" in capsys.readouterr().out
