from __future__ import annotations

import subprocess
from pathlib import Path
from local_ai_hub.commands import CommandBroker
from local_ai_hub.process_utils import hidden_run_kwargs


def test_command_rollback_on_failure(tmp_path: Path) -> None:
    # Set up git repo
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    tracked = tmp_path / "app.py"
    tracked.write_text("initial content", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)

    # Command that changes tracked file, creates untracked file, and fails
    cmd = 'python -c "import sys, pathlib; pathlib.Path(\'app.py\').write_text(\'corrupted\'); pathlib.Path(\'unwanted.tmp\').write_text(\'trash\'); sys.exit(1)"'
    
    result = broker.run(
        cmd,
        str(tmp_path),
        force=True,
        rollback_on_failure=True,
    )

    assert result["success"] is False
    assert result.get("rolled_back") is True
    # Tracked file should be restored
    assert tracked.read_text(encoding="utf-8") == "initial content"
    # Untracked file created during command should be deleted
    assert not (tmp_path / "unwanted.tmp").exists()


def test_command_snapshot_on_success(tmp_path: Path) -> None:
    # Set up git repo
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    tracked = tmp_path / "app.py"
    tracked.write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)

    # Command succeeds
    cmd = 'python -c "print(\'everything ok\')"'
    result = broker.run(
        cmd,
        str(tmp_path),
        force=True,
        snapshot=True,
    )

    assert result["success"] is True
    assert result.get("snapshot_taken") is True
    assert result.get("rolled_back") is None
