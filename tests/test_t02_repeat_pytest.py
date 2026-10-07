import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import repeat_t02_pytest


def test_repeat_count_is_bounded() -> None:
    assert repeat_t02_pytest._validate_repeat_count(1) == 1
    assert repeat_t02_pytest._validate_repeat_count(25) == 25
    assert repeat_t02_pytest._validate_repeat_count(50) == 50
    for value in (0, 51, True):
        with pytest.raises(ValueError, match="between 1 and 50"):
            repeat_t02_pytest._validate_repeat_count(value)


def test_output_directory_must_be_outside_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    with pytest.raises(ValueError, match="outside the repository"):
        repeat_t02_pytest._resolve_external_output(repository / "receipts", repository)


def test_attempt_command_pins_pytest_and_allowed_selector(tmp_path: Path) -> None:
    selector = repeat_t02_pytest._TARGET_SELECTOR
    scratch = tmp_path / "attempt-001"
    command = repeat_t02_pytest._command_for_attempt("python", selector, scratch)

    assert command == [
        "python", "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "--tb=short", "--basetemp", str(scratch), selector,
    ]
    with pytest.raises(ValueError, match="unsupported T02 selector"):
        repeat_t02_pytest._command_for_attempt("python", "tests/test_anything.py", scratch)


def test_run_repetitions_persists_failed_attempt_log_and_receipt(tmp_path: Path, monkeypatch) -> None:
    stdout = "1 failed in 0.20s\nFAILED tests/test_sample.py::test_case\n"
    real_run = subprocess.run

    def fake_run(command, **kwargs):
        if command[0] == "git":
            return real_run(command, **kwargs)
        return subprocess.CompletedProcess(command, 1, stdout, "failure detail")

    monkeypatch.setattr(repeat_t02_pytest.subprocess, "run", fake_run)
    output_dir = tmp_path / "receipts"
    result = repeat_t02_pytest.run_repetitions(
        selector=repeat_t02_pytest._TARGET_SELECTOR,
        repeat_count=1,
        output_dir=output_dir,
        time_budget_seconds=10,
    )

    receipt = json.loads((output_dir / "receipt.json").read_text(encoding="utf-8"))
    attempt = receipt["attempts"][0]
    log_path = Path(attempt["log"])
    log = log_path.read_text(encoding="utf-8")
    assert result == 1
    assert receipt["status"] == "failed"
    assert attempt["outcome"] == "failed"
    assert attempt["return_code"] == 1
    assert attempt["failed_node_ids"] == ["tests/test_sample.py::test_case"]
    assert stdout in log
    assert "failure detail" in log
    assert attempt["log_sha256"] == hashlib.sha256(log_path.read_bytes()).hexdigest()


def test_run_repetitions_preserves_partial_output_after_timeout(tmp_path: Path, monkeypatch) -> None:
    real_run = subprocess.run

    def fake_run(command, **kwargs):
        if command[0] == "git":
            return real_run(command, **kwargs)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"partial stdout", stderr=b"partial stderr")

    monkeypatch.setattr(repeat_t02_pytest.subprocess, "run", fake_run)
    output_dir = tmp_path / "receipts"
    result = repeat_t02_pytest.run_repetitions(
        selector=repeat_t02_pytest._TARGET_SELECTOR,
        repeat_count=1,
        output_dir=output_dir,
        time_budget_seconds=10,
    )

    receipt = json.loads((output_dir / "receipt.json").read_text(encoding="utf-8"))
    attempt = receipt["attempts"][0]
    log = Path(attempt["log"]).read_text(encoding="utf-8")
    assert result == 1
    assert receipt["status"] == "incomplete"
    assert attempt["outcome"] == "timeout"
    assert "partial stdout" in log
    assert "partial stderr" in log


@pytest.mark.parametrize("timeout", ["nan", "inf", "-inf"])
def test_main_rejects_nonfinite_integer_time_budget(
    tmp_path: Path, capsys, timeout: str
) -> None:
    with pytest.raises(SystemExit) as error:
        repeat_t02_pytest.main([
            "--output-dir", str(tmp_path / "receipts"),
            f"--time-budget-seconds={timeout}",
        ])

    assert error.value.code == 2
    assert "invalid int value" in capsys.readouterr().err
