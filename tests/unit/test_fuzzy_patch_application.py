import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest

from local_ai_hub.commands import CommandBroker
from tests.fencing_lease_support import FakeFencingLeaseStore, install_test_work_attempt_fence


def _register_test_worktree(broker, root, task_id, monkeypatch):
    repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(root), capture_output=True, text=True, check=True
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(root), capture_output=True, text=True, check=True
    ).stdout.strip()

    class TaskStore:
        def get(self, requested_task_id: str):
            if requested_task_id != task_id:
                return None
            return SimpleNamespace(checkpoint=SimpleNamespace(state_data={
                "worktree": {
                    "success": True,
                    "worktree_path": str(root),
                    "repo_root": repo_root,
                    "branch": branch,
                }
            }))

    broker.set_task_store(TaskStore())
    install_test_work_attempt_fence(broker, FakeFencingLeaseStore())
    monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

    def execute(argv, cwd, timeout, *_args, **_kwargs):
        completed = subprocess.run(
            argv[-1], cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        return {
            "success": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_ms": 1,
            "timed_out": False,
        }

    monkeypatch.setattr(broker, "_execute", execute)


def test_patch_and_verify_crlf_whitespace_tolerance(tmp_path: Path, monkeypatch):
    # Setup git repo
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=str(tmp_path), capture_output=True, check=True)

    # File on disk has CRLF endings
    target_file = tmp_path / "app.py"
    target_file.write_bytes(b"def compute():\r\n    x = 10\r\n    return 42\r\n")

    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    # Patch has LF endings
    diff = (
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,3 +1,3 @@\n"
        " def compute():\n"
        "     x = 10\n"
        "-    return 42\n"
        "+    return 84\n"
    )

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    broker = CommandBroker(cfg)
    _register_test_worktree(broker, tmp_path, "task-fuzzy", monkeypatch)

    res = broker.patch_and_verify(
        patch=diff,
        cwd=str(tmp_path),
        tenant="test-agent",
        command="git -c core.whitespace=cr-at-eol diff --check",
        task_id="task-fuzzy",
        criterion="quick pass",
    )

    assert res["success"] is True, {key: res.get(key) for key in ("error", "command", "exit_code", "stdout", "stderr")}
    assert res["applied"] is True
    assert res["tests_passed"] is True
    content = target_file.read_bytes()
    assert b"return 84" in content


def test_patch_and_verify_whitespace_change_tolerance(tmp_path: Path, monkeypatch):
    # Setup git repo
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True)

    target_file = tmp_path / "calc.py"
    target_file.write_text("def add(a,  b):\n    return a + b\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    # Patch has single space 'a, b' instead of double space 'a,  b'
    diff = (
        "--- a/calc.py\n"
        "+++ b/calc.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n"
        "-    return a + b\n"
        "+    return (a + b) * 2\n"
    )

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    broker = CommandBroker(cfg)
    _register_test_worktree(broker, tmp_path, "task-ws", monkeypatch)

    res = broker.patch_and_verify(
        patch=diff,
        cwd=str(tmp_path),
        tenant="test-agent",
        command="git diff --check",
        task_id="task-ws",
        criterion="quick pass",
    )

    assert res["success"] is True, res.get("error")
    assert res["applied"] is True
    assert res["tests_passed"] is True
    content = target_file.read_text(encoding="utf-8")
    assert "return (a + b) * 2" in content

