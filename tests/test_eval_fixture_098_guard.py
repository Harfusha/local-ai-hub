from pathlib import Path
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-098' / 'run.py'


def test_sandbox_runner_rejects_foreign_interpreter_before_writes(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'sandbox venv interpreter' in result.stderr
    assert not (tmp_path / 'state').exists()


def test_sandbox_runner_rejects_noncanonical_task_id_before_writes(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), '--task-id', '../escape'], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'invalid task ID' in result.stderr
    assert not (tmp_path / 'state').exists()


def test_sandbox_runner_accepts_noninteractive_option_before_sandbox_checks(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), '--no-wait'], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'sandbox venv interpreter' in result.stderr
    assert not (tmp_path / 'state').exists()
