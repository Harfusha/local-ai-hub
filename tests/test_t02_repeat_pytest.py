from __future__ import annotations

import hashlib
import subprocess
import sys

import pytest

from tools import repeat_t02_pytest


def test_run_attempt_persists_logs_and_failure_nodes(tmp_path, monkeypatch) -> None:
    stdout = "1 failed, 2 passed in 0.20s\nFAILED tests/test_sample.py::test_case\n"

    def fake_run(command, *, cwd, capture_output, text, timeout, check):
        assert command[-1] == "tests/test_sample.py"
        assert cwd == tmp_path
        assert capture_output is True and text is True and check is False
        return subprocess.CompletedProcess(command, 1, stdout, "")

    monkeypatch.setattr(repeat_t02_pytest.subprocess, "run", fake_run)
    result = repeat_t02_pytest.run_attempt(
        [sys.executable, "-m", "pytest", "tests/test_sample.py"],
        repo_root=tmp_path,
        out_dir=tmp_path / "receipts",
        label="ordered-01",
        timeout_seconds=5,
    )

    assert result["status"] == "failed"
    assert result["exit_code"] == 1
    assert result["timeout_seconds"] == 5
    assert result["finished_utc"]
    assert result["failed_node_ids"] == ["tests/test_sample.py::test_case"]
    stdout_path = tmp_path / "receipts" / result["stdout_file"]
    assert stdout_path.read_text(encoding="utf-8") == stdout
    assert result["stdout_sha256"] == hashlib.sha256(stdout.encode()).hexdigest()


def test_run_attempt_records_timeout_and_partial_output(tmp_path, monkeypatch) -> None:
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 0.01, output=b"partial", stderr=b"late")

    monkeypatch.setattr(repeat_t02_pytest.subprocess, "run", fake_run)
    result = repeat_t02_pytest.run_attempt(
        [sys.executable, "-m", "pytest"],
        repo_root=tmp_path,
        out_dir=tmp_path / "receipts",
        label="ordered-01",
        timeout_seconds=0.01,
    )

    assert result["status"] == "timeout"
    assert result["exit_code"] == 124
    assert result["timeout_seconds"] == 0.01
    assert (tmp_path / "receipts" / result["stdout_file"]).read_text(encoding="utf-8") == "partial"
    assert (tmp_path / "receipts" / result["stderr_file"]).read_text(encoding="utf-8") == "late"


@pytest.mark.parametrize("timeout", ["nan", "inf", "-inf"])
def test_main_rejects_nonfinite_timeout(tmp_path, capsys, timeout: str) -> None:
    with pytest.raises(SystemExit) as error:
        repeat_t02_pytest.main([
            "--out-dir", str(tmp_path / "receipt"),
            f"--timeout-seconds={timeout}",
        ])

    assert error.value.code == 2
    assert "timeout must be finite and positive" in capsys.readouterr().err
