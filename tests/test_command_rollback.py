from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
import pytest
from local_ai_hub import commands as commands_module
from local_ai_hub.commands import CommandBroker, _get_windows_dacl, _windows_dacl_bytes
from local_ai_hub.process_utils import hidden_run_kwargs


def test_patch_and_verify_failure_reverses_only_supplied_patch(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    target = tmp_path / "target.txt"
    unrelated = tmp_path / "unrelated.txt"
    target.write_text("committed target\nsecond line\n", encoding="utf-8")
    unrelated.write_text("committed unrelated\n", encoding="utf-8")
    subprocess.run(["git", "add", "target.txt", "unrelated.txt"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    target.write_text("user dirty baseline\nsecond line\n", encoding="utf-8")
    unrelated.write_text("staged unrelated edit\n", encoding="utf-8")
    subprocess.run(["git", "add", "unrelated.txt"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    unrelated.write_text("staged unrelated edit\nunstaged unrelated edit\n", encoding="utf-8")
    preexisting = tmp_path / "preexisting.tmp"
    preexisting.write_text("keep", encoding="utf-8")

    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)

    def fail_validation(*args, **kwargs):
        (tmp_path / "concurrent.tmp").write_text("foreign", encoding="utf-8")
        return {"success": False, "exit_code": 1}

    monkeypatch.setattr(broker, "run", fail_validation)
    patch = (
        "diff --git a/target.txt b/target.txt\n"
        "--- a/target.txt\n"
        "+++ b/target.txt\n"
        "@@ -1,2 +1,2 @@\n"
        "-user dirty baseline\n"
        "+patched target\n"
        " second line\n"
    )

    result = broker.patch_and_verify(patch, tmp_path, tenant="", command="pytest -q")

    staged = subprocess.run(
        ["git", "show", ":unrelated.txt"], cwd=str(tmp_path), capture_output=True, text=True, check=True, **hidden_run_kwargs()
    )
    assert result["success"] is False
    assert result["rolled_back"] is True
    assert target.read_text(encoding="utf-8") == "user dirty baseline\nsecond line\n"
    assert staged.stdout == "staged unrelated edit\n"
    assert unrelated.read_text(encoding="utf-8") == "staged unrelated edit\nunstaged unrelated edit\n"
    assert preexisting.read_text(encoding="utf-8") == "keep"
    assert (tmp_path / "concurrent.tmp").read_text(encoding="utf-8") == "foreign"


def test_patch_and_verify_reports_failed_reverse_without_clobbering_concurrent_edit(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    target = tmp_path / "target.txt"
    target.write_text("before patch\nsecond line\n", encoding="utf-8")
    subprocess.run(["git", "add", "target.txt"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)

    def fail_validation_with_concurrent_edit(*args, **kwargs):
        target.write_text("concurrent replacement\nsecond line\n", encoding="utf-8")
        return {"success": False, "exit_code": 1}

    monkeypatch.setattr(broker, "run", fail_validation_with_concurrent_edit)
    patch = (
        "diff --git a/target.txt b/target.txt\n"
        "--- a/target.txt\n"
        "+++ b/target.txt\n"
        "@@ -1,2 +1,2 @@\n"
        "-before patch\n"
        "+patched target\n"
        " second line\n"
    )

    original_run = commands_module.subprocess.run
    reverse_commands: list[list[str]] = []

    def observe_reverse(command, *args, **kwargs):
        if isinstance(command, list) and command[:3] == ["git", "apply", "--reverse"]:
            reverse_commands.append(command)
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(commands_module.subprocess, "run", observe_reverse)
    result = broker.patch_and_verify(patch, tmp_path, tenant="", command="pytest -q")

    assert result["success"] is False
    assert result["applied"] is True
    assert result["rolled_back"] is False
    assert "Patch rollback failed" in result["rollback_error"]
    assert len(reverse_commands) == 1
    assert "--check" not in reverse_commands[0]
    assert target.read_text(encoding="utf-8") == "concurrent replacement\nsecond line\n"


def test_patch_and_verify_syntax_failure_reverses_only_supplied_patch(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    target = tmp_path / "syntax_target.py"
    unrelated = tmp_path / "unrelated.txt"
    target.write_text("committed = 1\n", encoding="utf-8")
    unrelated.write_text("committed unrelated\n", encoding="utf-8")
    subprocess.run(["git", "add", "syntax_target.py", "unrelated.txt"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    target.write_text("user baseline = 1\n", encoding="utf-8")
    unrelated.write_text("unrelated user edit\n", encoding="utf-8")
    preexisting = tmp_path / "preexisting.tmp"
    preexisting.write_text("keep", encoding="utf-8")

    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)
    patch = (
        "diff --git a/syntax_target.py b/syntax_target.py\n"
        "--- a/syntax_target.py\n"
        "+++ b/syntax_target.py\n"
        "@@ -1 +1 @@\n"
        "-user baseline = 1\n"
        "+def broken(:\n"
    )

    result = broker.patch_and_verify(patch, tmp_path, tenant="", command="pytest -q")

    assert result["success"] is False
    assert result["rolled_back"] is True
    assert result["applied"] is False
    assert target.read_text(encoding="utf-8") == "user baseline = 1\n"
    assert unrelated.read_text(encoding="utf-8") == "unrelated user edit\n"
    assert preexisting.read_text(encoding="utf-8") == "keep"


def test_command_rollback_on_failure_preserves_unowned_changes(tmp_path: Path, monkeypatch) -> None:
    # Set up git repo
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())

    tracked = tmp_path / "app.py"
    tracked.write_text("initial content", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    # Rollback must restore the exact pre-run state, not the Git HEAD state.
    tracked.write_text("user's dirty baseline", encoding="utf-8")
    unrelated = tmp_path / "unrelated.py"
    unrelated.write_text("committed", encoding="utf-8")
    subprocess.run(["git", "add", "unrelated.py"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "-m", "unrelated"], cwd=str(tmp_path), capture_output=True, check=True, **hidden_run_kwargs())
    unrelated.write_text("pre-existing user edit", encoding="utf-8")
    preexisting = tmp_path / "preexisting.tmp"
    preexisting.write_text("keep", encoding="utf-8")
    external_alias = tmp_path / "external-alias.tmp"
    external_alias.write_text("foreign bytes", encoding="utf-8")

    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)
    original_execute = broker._execute

    def execute_with_concurrent_change(*args, **kwargs):
        result = original_execute(*args, **kwargs)
        # Simulate a separate actor changing the workspace after command exit.
        (tmp_path / "concurrent.tmp").write_text("foreign", encoding="utf-8")
        tracked.unlink()
        tracked.hardlink_to(external_alias)
        return result

    monkeypatch.setattr(broker, "_execute", execute_with_concurrent_change)

    # Command that changes tracked file, creates untracked file, and fails
    cmd = 'python -c "import sys, pathlib; pathlib.Path(\'app.py\').write_text(\'corrupted\'); pathlib.Path(\'unwanted.tmp\').write_text(\'trash\'); sys.exit(1)"'
    
    result = broker.run(
        cmd,
        str(tmp_path),
        force=True,
        rollback_on_failure=True,
        rollback_paths=["app.py", "unwanted.tmp"],
    )

    assert result["success"] is False
    assert result.get("rolled_back") is False
    assert "external aliases" in result.get("rollback_error", "")
    assert tracked.read_text(encoding="utf-8") == "user's dirty baseline"
    assert not (tmp_path / "unwanted.tmp").exists()
    assert unrelated.read_text(encoding="utf-8") == "pre-existing user edit"
    assert preexisting.read_text(encoding="utf-8") == "keep"
    assert (tmp_path / "concurrent.tmp").read_text(encoding="utf-8") == "foreign"
    assert external_alias.read_text(encoding="utf-8") == "foreign bytes"


def test_command_rollback_requires_explicit_scope(tmp_path: Path) -> None:
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)

    result = broker.run(
        'python -c "import pathlib, sys; pathlib.Path(\'keep.tmp\').write_text(\'keep\'); sys.exit(1)"',
        str(tmp_path),
        force=True,
        rollback_on_failure=True,
    )

    assert result["success"] is False
    assert result.get("rolled_back") is not True
    assert result.get("rollback_scope_required") is True
    assert not (tmp_path / "keep.tmp").exists()


def test_rollback_snapshot_does_not_change_file_access_time(tmp_path: Path) -> None:
    target = tmp_path / "preserve-atime.txt"
    target.write_text("baseline", encoding="utf-8")
    os.utime(target, ns=(1_000_000_000, 2_000_000_000))
    original_atime = target.stat().st_atime_ns
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})

    result = broker.run(
        'python -c "pass"',
        str(tmp_path),
        force=True,
        rollback_on_failure=True,
        rollback_paths=[target.name],
    )

    assert result["success"] is True
    assert target.stat().st_atime_ns == original_atime


def test_rollback_snapshot_requests_noatime_on_supported_posix(monkeypatch) -> None:
    monkeypatch.setattr(commands_module.os, "name", "posix")
    monkeypatch.setattr(commands_module.os, "O_NOATIME", 0x40000, raising=False)

    flags = commands_module._rollback_snapshot_open_flags()

    assert flags & 0x40000


def test_command_rollback_rejects_path_escape(tmp_path: Path) -> None:
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)

    result = broker.run(
        'python -c "import pathlib, sys; pathlib.Path(\'must_not_run.tmp\').touch(); sys.exit(1)"',
        str(tmp_path),
        force=True,
        rollback_on_failure=True,
        rollback_paths=["../outside.txt"],
    )

    assert result["success"] is False
    assert result.get("rollback_scope_invalid") is True
    assert result.get("rolled_back") is not True
    assert not (tmp_path / "must_not_run.tmp").exists()


def test_command_rollback_rejects_nested_paths(tmp_path: Path) -> None:
    (tmp_path / "subdir").mkdir()
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)

    result = broker.run(
        'python -c "import sys; sys.exit(1)"',
        str(tmp_path),
        force=True,
        rollback_on_failure=True,
        rollback_paths=["subdir/file.txt"],
    )

    assert result.get("rollback_scope_invalid") is True


def test_command_rollback_rejects_hardlinks(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("preserve", encoding="utf-8")
    try:
        (tmp_path / "owned.txt").hardlink_to(outside)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)

    result = broker.run(
        'python -c "import sys; sys.exit(1)"',
        str(tmp_path),
        force=True,
        rollback_on_failure=True,
        rollback_paths=["owned.txt"],
    )

    assert result.get("rollback_scope_invalid") is True
    assert outside.read_text(encoding="utf-8") == "preserve"


def test_command_rollback_rejects_auto_fix_combination(tmp_path: Path) -> None:
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)

    result = broker.run(
        'python -c "raise SystemExit(1)"',
        str(tmp_path),
        force=True,
        auto_fix=True,
        rollback_on_failure=True,
        rollback_paths=["owned.py"],
    )

    assert result.get("rollback_unsupported_action") is True
    assert result.get("rollback_scope_invalid") is not True


def test_command_rollback_preserves_filesystem_security_metadata(tmp_path: Path) -> None:
    target = tmp_path / "metadata.txt"
    target.write_text("baseline", encoding="utf-8")
    if os.name == "nt":
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            before = _get_windows_dacl(fd)
        finally:
            os.close(fd)
        metadata_name = None
    else:
        metadata_name = "user.local_ai_hub_rollback_test"
        try:
            os.setxattr(target, metadata_name, b"preserve-acl-xattr")
        except (AttributeError, OSError) as exc:
            pytest.skip(f"extended attributes unavailable: {exc}")
        before = os.getxattr(target, metadata_name)

    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)
    result = broker.run(
        'python -c "import pathlib, sys; pathlib.Path(\'metadata.txt\').write_text(\'changed\'); sys.exit(1)"',
        str(tmp_path),
        force=True,
        rollback_on_failure=True,
        rollback_paths=["metadata.txt"],
    )

    assert result.get("rolled_back") is True
    assert target.read_text(encoding="utf-8") == "baseline"
    if os.name == "nt":
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            assert _windows_dacl_bytes(_get_windows_dacl(fd)) == _windows_dacl_bytes(before)
        finally:
            os.close(fd)
    else:
        assert os.getxattr(target, metadata_name) == before


def test_command_rollback_runs_when_execution_raises_timeout(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "timed-out.txt"
    target.write_text("before", encoding="utf-8")
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=None, repo_state=None)

    def timeout_after_write(*_args, **_kwargs):
        target.write_text("partial", encoding="utf-8")
        raise subprocess.TimeoutExpired("test-command", 1)

    monkeypatch.setattr(broker, "_execute", timeout_after_write)
    result = broker.run(
        'python -c "print(1)"',
        str(tmp_path),
        force=True,
        rollback_on_failure=True,
        rollback_paths=["timed-out.txt"],
    )

    assert result.get("timed_out") is True
    assert result.get("rolled_back") is True
    assert target.read_text(encoding="utf-8") == "before"


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


def test_snapshot_git_operations_use_configured_timeout(tmp_path: Path, monkeypatch) -> None:
    class _RepoState:
        @staticmethod
        def fingerprint(_cwd: str) -> dict[str, str]:
            return {"fingerprint": "test"}

    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path)},
            "workspace_cache": {"git_status_timeout_seconds": 0.7},
        },
        repo_state=_RepoState(),
    )
    timeouts = []

    def fake_run(argv, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(commands_module.subprocess, "run", fake_run)
    monkeypatch.setattr(broker, "_execute", lambda *_args, **_kwargs: {"success": True, "exit_code": 0, "stdout": "", "stderr": ""})

    result = broker.run("python -c \"print('ok')\"", str(tmp_path), force=True, snapshot=True)

    assert result["success"] is True
    assert timeouts == [0.7, 0.7]


def test_successful_short_command_creates_auditable_verification_evidence(tmp_path: Path, monkeypatch) -> None:
    class _Artifacts:
        def __init__(self):
            self.records = []

        def put_json(self, value, tenant, kind):
            self.records.append((value, tenant, kind))
            return "ev-command-proof"

    class _VerificationStore:
        def __init__(self):
            self.receipts = []

        def record(self, receipt):
            self.receipts.append(receipt)
            return receipt

    artifacts = _Artifacts()
    verification = _VerificationStore()
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}}, artifacts=artifacts, repo_state=None)
    broker.set_verification_store(verification)
    monkeypatch.setattr(
        broker,
        "_key",
        lambda *_args: ("cache-key", {"fingerprint": "revision-1", "changed_paths": []}),
    )
    monkeypatch.setattr(
        broker,
        "_execute",
        lambda *_args, **_kwargs: {"success": True, "exit_code": 0, "stdout": "ok", "stderr": "", "duration_ms": 5},
    )

    result = broker.run(
        "python -m pytest -q",
        str(tmp_path),
        force=True,
        task_id="task-proof",
        criterion="tests",
        bypass_cache=True,
    )

    assert result["success"] is True
    assert len(artifacts.records) == 1
    proof, tenant, kind = artifacts.records[0]
    assert tenant == "agent"
    assert kind == "command_verification"
    assert proof["exit_code"] == 0
    assert "command" not in proof
    assert proof["command_sha256"] == hashlib.sha256(b"python -m pytest -q").hexdigest()
    assert len(verification.receipts) == 1
    receipt = verification.receipts[0]
    assert receipt.evidence_id == "ev-command-proof"
    assert receipt.command_id == result["execution_id"]
