from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from local_ai_hub import commands as commands_module
from local_ai_hub.agent_policy import PolicyEngine
from local_ai_hub.commands import CommandBroker


class _FakeTaskStore:
    def __init__(self, worktree_path: str) -> None:
        self.worktree_path = worktree_path

    def get(self, task_id: str):
        if task_id != "daemon-test":
            return None
        return SimpleNamespace(
            checkpoint=SimpleNamespace(
                state_data={"worktree": {"success": True, "worktree_path": self.worktree_path}}
            )
        )


def _broker(tmp_path: Path, **command_config: object) -> CommandBroker:
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, **command_config},
            "agent_policy": {"enabled": True, "allow_developer_authorized_mutations": True},
        }
    )
    broker.set_task_store(_FakeTaskStore(str(tmp_path)))
    broker.set_policy_engine(PolicyEngine())
    return broker


def test_daemon_environment_filters_inherited_secrets_but_keeps_explicit_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCAL_AI_DAEMON_TEST_API_TOKEN", "inherited-secret")
    monkeypatch.setenv("LOCAL_AI_DAEMON_TEST_VISIBLE", "inherited-visible")
    broker = _broker(tmp_path)

    env = broker._daemon_environment({"LOCAL_AI_DAEMON_EXPLICIT_SECRET": "caller-approved"})

    assert env.get("PATH") == os.environ.get("PATH")
    assert "LOCAL_AI_DAEMON_TEST_VISIBLE" not in env
    assert "LOCAL_AI_DAEMON_TEST_API_TOKEN" not in env
    assert env["LOCAL_AI_DAEMON_EXPLICIT_SECRET"] == "caller-approved"


@pytest.mark.parametrize(
    "extra_env",
    [
        {"BAD=NAME": "value"},
        {"GOOD": "contains\x00nul"},
        {"GOOD": 1},
        {"GIT_COMMON_DIR": "outside/.git"},
    ],
)
def test_daemon_environment_rejects_invalid_explicit_entries(
    tmp_path: Path, extra_env: dict[str, object]
) -> None:
    broker = _broker(tmp_path)

    with pytest.raises(ValueError):
        broker._daemon_environment(extra_env)  # type: ignore[arg-type]


def test_spawn_daemon_requires_auxiliary_policy_before_process_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    broker.config["agent_policy"]["allow_developer_authorized_mutations"] = False
    broker.set_policy_engine(PolicyEngine())
    launches: list[object] = []

    def fail_if_launched(*args: object, **_kwargs: object) -> None:
        launches.append(args)
        raise AssertionError("unauthorized daemon reached process launch")

    monkeypatch.setattr(commands_module.subprocess, "Popen", fail_if_launched)
    result = broker.spawn_daemon(
        [sys.executable, "-c", "pass"], str(tmp_path), task_id="daemon-test"
    )

    assert result["success"] is False
    assert result["policy"]["allowed"] is False
    assert not launches


def test_spawn_daemon_applies_command_policy_before_process_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    launches: list[object] = []

    def fail_if_launched(*args: object, **_kwargs: object) -> None:
        launches.append(args)
        raise AssertionError("dangerous daemon reached process launch")

    monkeypatch.setattr(commands_module.subprocess, "Popen", fail_if_launched)
    result = broker.spawn_daemon(["rm", "-rf", "/"], str(tmp_path), task_id="daemon-test")

    assert result["success"] is False
    assert result["policy_blocked"] is True
    assert not launches


def test_spawn_daemon_rejects_git_shared_worktree_override_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = tmp_path.parent / f"{tmp_path.name}-shared"
    shared.mkdir()
    broker = _broker(tmp_path)
    launches: list[object] = []

    def fail_if_launched(*args: object, **_kwargs: object) -> None:
        launches.append(args)
        raise AssertionError("daemon Git override reached process launch")

    monkeypatch.setattr(commands_module.subprocess, "Popen", fail_if_launched)
    result = broker.spawn_daemon(
        ["git", "-C", str(shared), "status"], str(tmp_path), task_id="daemon-test"
    )

    assert result["success"] is False
    assert "outside the registered task worktree" in result["error"]
    assert not launches


def test_daemon_log_retains_bounded_recent_output(tmp_path: Path) -> None:
    max_log_bytes = 1024
    broker = _broker(tmp_path, daemon_log_max_bytes=max_log_bytes)
    code = "import sys; sys.stdout.write('x' * 8192 + 'TAIL_MARKER')"
    daemon = broker.spawn_daemon(
        f'"{sys.executable}" -c "{code}"',
        str(tmp_path),
        name="bounded-log-test",
        task_id="daemon-test",
    )
    assert daemon["success"] is True

    deadline = time.monotonic() + 5
    status = broker.daemon_status(daemon["daemon_id"])
    while status.get("running") and time.monotonic() < deadline:
        time.sleep(0.02)
        status = broker.daemon_status(daemon["daemon_id"])

    assert status["running"] is False
    log = Path(daemon["log_path"]).read_bytes()
    assert len(log) <= max_log_bytes
    assert log.endswith(b"TAIL_MARKER")


def test_stop_daemon_does_not_report_success_while_process_is_alive(tmp_path: Path) -> None:
    class UnstoppableProcess:
        pid = 12345

        def poll(self) -> None:
            return None

        def wait(self, timeout: float) -> None:
            raise subprocess.TimeoutExpired("daemon", timeout)

        def kill(self) -> None:
            raise OSError("kill denied")

    broker = _broker(tmp_path)
    broker._daemons["stuck"] = {
        "daemon_id": "stuck",
        "process": UnstoppableProcess(),
        "pid": 12345,
        "name": "stuck",
        "command": "sleep forever",
        "cwd": str(tmp_path),
        "log_path": str(tmp_path / "stuck.log"),
        "log_fh": mock.MagicMock(),
        "_log_closed": False,
    }

    with mock.patch("local_ai_hub.commands.terminate_tree"):
        result = broker.stop_daemon("stuck")

    assert result["success"] is False
    assert result["running"] is True
    assert result["error"] == "daemon did not stop within the bounded termination window"


def test_daemon_status_redacts_sensitive_command_arguments(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=2)
    broker._daemons["redact"] = {
        "daemon_id": "redact",
        "process": process,
        "pid": process.pid,
        "name": "redact",
        "command": "tool --api-token super-secret",
        "cwd": str(tmp_path),
        "log_path": str(tmp_path / "redact.log"),
        "log_fh": mock.MagicMock(),
        "_log_closed": False,
        "started_at": time.time(),
    }

    result = broker.daemon_status("redact")

    assert result["success"] is True
    assert "super-secret" not in result["command"]


def test_daemon_accepts_structured_argv_without_shell(tmp_path: Path) -> None:
    broker = _broker(tmp_path)

    daemon = broker.spawn_daemon(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        str(tmp_path),
        name="structured-argv-test",
        task_id="daemon-test",
    )

    assert daemon["success"] is True
    assert broker.stop_daemon(daemon["daemon_id"])["success"] is True


def test_stop_daemon_does_not_claim_tree_stopped_when_cleanup_is_unconfirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(CommandBroker, "_watch_daemon_exit", lambda *_args: None)
    broker = _broker(tmp_path)
    daemon = broker.spawn_daemon([sys.executable, "-c", "pass"], str(tmp_path), task_id="daemon-test")
    assert daemon["success"] is True
    process = broker._daemons[daemon["daemon_id"]]["process"]
    process.wait(timeout=5)
    terminate_calls: list[int] = []

    def unconfirmed(info: dict[str, object]) -> bool:
        terminate_calls.append(int(info["pid"]))
        return False

    monkeypatch.setattr(commands_module, "_stop_daemon_tree", unconfirmed, raising=False)
    result = broker.stop_daemon(daemon["daemon_id"])

    assert terminate_calls == [daemon["pid"], daemon["pid"]]
    assert result["success"] is False
    assert result["status"] == "cleanup_unconfirmed"
    assert result["running"] is False

    monkeypatch.setattr(commands_module, "_stop_daemon_tree", lambda *_args, **_kwargs: True)
    assert broker.stop_daemon(daemon["daemon_id"])["success"] is True


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object process-tree integration")
def test_daemon_job_stops_descendants_after_leader_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop_tree = commands_module._stop_daemon_tree
    attempts = 0

    def fail_once(info: dict[str, object]) -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return False
        return stop_tree(info)

    monkeypatch.setattr(commands_module, "_stop_daemon_tree", fail_once)
    broker = _broker(tmp_path)
    child_pid_file = tmp_path / "daemon-child.pid"
    parent_code = (
        "import pathlib, subprocess, sys; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='ascii')"
    )
    daemon = broker.spawn_daemon(
        [sys.executable, "-c", parent_code, str(child_pid_file)], str(tmp_path), name="orphan-child-test", task_id="daemon-test"
    )
    assert daemon["success"] is True
    child_pid: int | None = None
    try:
        deadline = time.monotonic() + 5
        while (not child_pid_file.exists() or not child_pid_file.stat().st_size) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child_pid_file.exists() and child_pid_file.stat().st_size, "daemon leader did not start its child"
        child_pid = int(child_pid_file.read_text(encoding="ascii"))
        broker._daemons[daemon["daemon_id"]]["process"].wait(timeout=5)

        deadline = time.monotonic() + 3
        while commands_module.process_identity(child_pid) is not None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert commands_module.process_identity(child_pid) is None, "orphaned daemon descendant was not reaped automatically"
        assert attempts >= 2

        status = broker.daemon_status(daemon["daemon_id"])

        assert status["success"] is True
        assert status["status"] == "stopped"
        assert status["process_tree_stopped"] is True
        assert broker.stop_daemon(daemon["daemon_id"])["success"] is True
    finally:
        if child_pid is not None and commands_module.process_identity(child_pid) is not None:
            subprocess.run(
                ["taskkill", "/PID", str(child_pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )


def test_daemon_ttl_retries_unconfirmed_tree_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(CommandBroker, "_watch_daemon_exit", lambda *_args: None)
    broker = _broker(tmp_path)
    daemon = broker.spawn_daemon([sys.executable, "-c", "pass"], str(tmp_path), task_id="daemon-test")
    assert daemon["success"] is True
    broker._daemons[daemon["daemon_id"]]["process"].wait(timeout=5)
    attempts: list[str] = []
    monkeypatch.setattr(
        commands_module,
        "_stop_daemon_tree",
        lambda info: attempts.append(str(info["daemon_id"])) or False,
        raising=False,
    )

    broker._expire_daemon(daemon["daemon_id"])

    assert attempts == [daemon["daemon_id"]] * 6
    assert broker._daemons[daemon["daemon_id"]]["ttl_stop_failed"] is True
    monkeypatch.undo()
    broker.stop_daemon(daemon["daemon_id"])


def test_daemon_rejects_implicit_shell_operators(tmp_path: Path) -> None:
    broker = _broker(tmp_path)

    result = broker.spawn_daemon(
        f'"{sys.executable}" -c "pass" && "{sys.executable}" -c "pass"',
        str(tmp_path),
        task_id="daemon-test",
    )

    try:
        assert result["success"] is False
        assert "implicit shell" in result["error"]
    finally:
        if result.get("success"):
            broker.stop_daemon(result["daemon_id"])


def test_daemon_ttl_stops_process_and_records_owner(tmp_path: Path) -> None:
    broker = _broker(tmp_path, daemon_ttl_seconds=1)
    daemon = broker.spawn_daemon(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        str(tmp_path),
        name="ttl-test",
        task_id="daemon-test",
    )
    assert daemon["success"] is True
    try:
        initial = broker.daemon_status(daemon["daemon_id"])
        assert initial["owner_id"]
        assert initial["ttl_remaining_seconds"] > 0

        deadline = time.monotonic() + 6
        status = initial
        while status.get("running") and time.monotonic() < deadline:
            time.sleep(0.05)
            status = broker.daemon_status(daemon["daemon_id"])

        assert status["running"] is False
        assert status["status"] == "stopped"
    finally:
        if broker.daemon_status(daemon["daemon_id"]).get("running"):
            broker.stop_daemon(daemon["daemon_id"])


def test_live_daemon_is_reconciled_after_broker_restart(tmp_path: Path) -> None:
    first = _broker(tmp_path)
    daemon = first.spawn_daemon(
        f'"{sys.executable}" -c "import time; time.sleep(30)"',
        str(tmp_path),
        name="restart-reconcile-test",
        task_id="daemon-test",
    )
    assert daemon["success"] is True

    second = _broker(tmp_path)
    try:
        status = second.daemon_status(daemon["daemon_id"])
        assert status["success"] is True
        assert status["running"] is True
        assert status["pid"] == daemon["pid"]
        stopped = second.stop_daemon(daemon["daemon_id"])
        assert stopped["success"] is True
    finally:
        if first.daemon_status(daemon["daemon_id"]).get("running"):
            first.stop_daemon(daemon["daemon_id"])


def test_restart_reconciliation_rejects_pid_reuse(tmp_path: Path) -> None:
    first = _broker(tmp_path)
    daemon = first.spawn_daemon(
        f'"{sys.executable}" -c "import time; time.sleep(30)"',
        str(tmp_path),
        name="pid-reuse-test",
        task_id="daemon-test",
    )
    assert daemon["success"] is True

    try:
        with mock.patch.object(commands_module, "process_identity", return_value={"pid": daemon["pid"], "creation_identity": -1}):
            second = _broker(tmp_path)
        result = second.daemon_status(daemon["daemon_id"])
        assert result["success"] is False
        assert first.daemon_status(daemon["daemon_id"])["running"] is True
    finally:
        first.stop_daemon(daemon["daemon_id"])
