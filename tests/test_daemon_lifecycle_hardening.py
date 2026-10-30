from __future__ import annotations

import os
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from local_ai_hub import commands as commands_module
from local_ai_hub.agent_policy import PolicyEngine
from local_ai_hub.commands import CommandBroker
from local_ai_hub.process_utils import hidden_run_kwargs
from local_ai_hub.services import LocalAIServices


class _FakeTaskStore:
    def __init__(self, worktree_path: str) -> None:
        path = Path(worktree_path).resolve()
        path.mkdir(parents=True, exist_ok=True)
        probe = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False, timeout=10, **hidden_run_kwargs()
        )
        if probe.returncode != 0:
            subprocess.run(
                ["git", "init"], cwd=str(path), capture_output=True, check=True, timeout=10,
                **hidden_run_kwargs()
            )
        self.worktree = {
            "success": True,
            "worktree_path": str(path),
            "repo_root": subprocess.run(
                ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=True, timeout=10, **hidden_run_kwargs()
            ).stdout.strip(),
            "branch": subprocess.run(
                ["git", "-C", str(path), "symbolic-ref", "--quiet", "--short", "HEAD"],
                capture_output=True, text=True, check=True, timeout=10, **hidden_run_kwargs()
            ).stdout.strip(),
        }

    def get(self, task_id: str):
        if task_id != "daemon-test":
            return None
        return SimpleNamespace(
            task_id=task_id,
            checkpoint=SimpleNamespace(
                state_data={"worktree": self.worktree}
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


def _registry_row(broker: CommandBroker, *, process_group_id: int = 4321) -> dict[str, object]:
    return {
        "daemon_id": "dmn_" + "a" * 32,
        "pid": 4321,
        "process_group_id": process_group_id,
        "job_name": commands_module._daemon_job_name("dmn_" + "a" * 32) if os.name == "nt" else None,
        "identity": {"pid": 4321, "start_time": "leader-start"},
        "owner_id": broker._daemon_owner_id,
        "task_id": "daemon-test",
        "name": "recovered-test",
        "command": "worker",
        "started_at": 1.0,
        "expires_at": time.time() + 60.0,
    }


def _write_registry_row(
    broker: CommandBroker, row: dict[str, object], *, version: int | None = None
) -> None:
    if version is None:
        version = 4 if os.name == "nt" else 3
    broker._daemon_state_dir.mkdir(parents=True, exist_ok=True)
    (broker._daemon_state_dir / f"{row['daemon_id']}.log").write_bytes(b"log\\n")
    persisted_row = dict(row)
    if version == 2:
        persisted_row.pop("process_group_id", None)
    broker._daemon_registry_path.write_text(
        json.dumps({"version": version, "daemons": [persisted_row]}), encoding="utf-8"
    )


def test_daemon_registry_persists_process_group_id(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    daemon_id = "dmn_" + "b" * 32

    class LiveProcess:
        pid = 4321

        @staticmethod
        def poll() -> None:
            return None

    broker._daemons[daemon_id] = {
        "daemon_id": daemon_id,
        "process": LiveProcess(),
        "pid": 4321,
        "process_group_id": 4321,
        "job_name": commands_module._daemon_job_name(daemon_id) if os.name == "nt" else None,
        "identity": {"pid": 4321, "start_time": "leader-start"},
        "owner_id": broker._daemon_owner_id,
        "task_id": "daemon-test",
        "name": "persist-test",
        "command": "worker",
        "started_at": 1.0,
        "expires_at": time.time() + 60.0,
    }

    assert broker._persist_daemon_registry() is True
    registry = json.loads(broker._daemon_registry_path.read_text(encoding="utf-8"))
    assert registry["version"] == (4 if os.name == "nt" else 3)
    assert registry["daemons"][0]["process_group_id"] == 4321


@pytest.mark.skipif(os.name == "nt", reason="Windows orphan recovery uses named Job Objects")
def test_recovery_accepts_exited_leader_only_when_group_is_verified_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    _write_registry_row(broker, _registry_row(broker))
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(commands_module, "_process_leader_exited", lambda _pid: True, raising=False)
    monkeypatch.setattr(commands_module, "_process_group_liveness", lambda _pgid: True, raising=False)
    monkeypatch.setattr(commands_module, "_daemon_process_group_owned", lambda _pgid, _token: True, raising=False)

    try:
        broker._load_daemon_registry()

        recovered = broker._daemons["dmn_" + "a" * 32]
        assert recovered["process_group_id"] == 4321
        assert recovered["process"].poll() is None
    finally:
        for info in broker._daemons.values():
            broker._close_daemon_log(info)
            broker._release_daemon_slot(info)


@pytest.mark.skipif(os.name != "nt", reason="Windows named Job Object recovery")
@pytest.mark.parametrize("job_has_processes", [True, False])
def test_windows_recovery_requires_live_named_job_for_exited_leader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, job_has_processes: bool
) -> None:
    broker = _broker(tmp_path)
    _write_registry_row(broker, _registry_row(broker), version=4)
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(commands_module, "_open_named_daemon_job", lambda _name: 1234)
    monkeypatch.setattr(commands_module, "_windows_job_has_processes", lambda _handle: job_has_processes)
    monkeypatch.setattr(commands_module, "close_job_object", lambda _handle: None)

    try:
        broker._load_daemon_registry()

        daemon_id = "dmn_" + "a" * 32
        if job_has_processes:
            assert daemon_id in broker._daemons
            assert broker._daemons[daemon_id]["process"].poll() is None
        else:
            assert daemon_id not in broker._daemons
    finally:
        # These recovered processes/Job handles are test doubles, so release
        # local resources without signaling a numeric PID or stopping a tree.
        for info in broker._daemons.values():
            timer = info.get("ttl_timer")
            if timer is not None:
                timer.cancel()
                timer.join(timeout=1.0)
            broker._close_daemon_log(info)
            process = info["process"]
            if process._local_ai_job_handle:
                commands_module.close_job_object(process._local_ai_job_handle)
                process._local_ai_job_handle = None
            broker._release_daemon_slot(info)


@pytest.mark.skipif(os.name != "nt", reason="Windows named Job Object recovery")
def test_windows_recovery_test_closes_its_adopted_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = []
    original_open = Path.open

    def track_open(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if mode == "r+b" and path.suffix == ".log":
            opened.append(stream)
        return stream

    monkeypatch.setattr(Path, "open", track_open)
    # Isolate file ownership from the real expiry thread in this cleanup proof.
    monkeypatch.setattr(CommandBroker, "_schedule_daemon_expiry", lambda *_args: None)
    try:
        with pytest.MonkeyPatch.context() as recovery_patch:
            test_windows_recovery_requires_live_named_job_for_exited_leader(
                tmp_path, recovery_patch, True
            )
        assert opened
        assert all(stream.closed for stream in opened)
    finally:
        for stream in opened:
            stream.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows named Job Object recovery")
@pytest.mark.parametrize("failed_operation", ["seek", "tell", "read"])
def test_windows_recovery_log_failure_releases_unadopted_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_operation: str
) -> None:
    broker = _broker(tmp_path)
    broker._daemon_slots = threading.BoundedSemaphore(1)
    row = _registry_row(broker)
    _write_registry_row(broker, row, version=4)
    log_path = broker._daemon_state_dir / f"{row['daemon_id']}.log"
    stream = log_path.open("r+b")
    failing_stream = mock.Mock(wraps=stream)
    getattr(failing_stream, failed_operation).side_effect = OSError("log read failure")
    original_open = Path.open

    def open_log(path, mode="r", *args, **kwargs):
        if path == log_path and mode == "r+b":
            return failing_stream
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_log)
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(commands_module, "_open_named_daemon_job", lambda _name: 77)
    monkeypatch.setattr(commands_module, "_windows_job_has_processes", lambda _handle: True)
    close_job = mock.Mock()
    monkeypatch.setattr(commands_module, "close_job_object", close_job)
    try:
        broker._load_daemon_registry()
        assert broker._daemons == {}
        assert stream.closed
        close_job.assert_called_once_with(77)
        assert broker._daemon_slots.acquire(blocking=False)
        broker._daemon_slots.release()
    finally:
        stream.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows named Job Object recovery")
def test_windows_recovery_admission_failure_closes_job_without_opening_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    _write_registry_row(broker, _registry_row(broker), version=4)
    broker._daemon_slots = threading.BoundedSemaphore(1)
    assert broker._daemon_slots.acquire(blocking=False)
    original_open = Path.open

    def reject_log_open(path, mode="r", *args, **kwargs):
        if mode == "r+b" and path.suffix == ".log":
            pytest.fail("admission rejection must not open a daemon log")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_log_open)
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(commands_module, "_open_named_daemon_job", lambda _name: 77)
    monkeypatch.setattr(commands_module, "_windows_job_has_processes", lambda _handle: True)
    close_job = mock.Mock()
    monkeypatch.setattr(commands_module, "close_job_object", close_job)
    try:
        broker._load_daemon_registry()
        assert broker._daemons == {}
        close_job.assert_called_once_with(77)
        assert not broker._daemon_slots.acquire(blocking=False)
    finally:
        broker._daemon_slots.release()


@pytest.mark.skipif(os.name == "nt", reason="legacy Windows rows lack stable tree ownership")
def test_recovery_accepts_live_version_two_registry_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    _write_registry_row(broker, _registry_row(broker), version=2)
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: {"pid": 4321, "start_time": "leader-start"})

    broker._load_daemon_registry()

    recovered = broker._daemons["dmn_" + "a" * 32]
    try:
        assert recovered["process_group_id"] == 4321
        assert recovered["process"].poll() is None
    finally:
        timer = recovered.get("ttl_timer")
        if timer is not None:
            timer.cancel()
        recovered["log_fh"].close()
        broker._daemon_slots.release()


@pytest.mark.skipif(os.name != "nt", reason="Windows rejects legacy daemon registry rows")
@pytest.mark.parametrize("version", [2, 3])
def test_windows_recovery_rejects_legacy_registry_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: int
) -> None:
    broker = _broker(tmp_path)
    _write_registry_row(broker, _registry_row(broker), version=version)
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: {"pid": 4321, "start_time": "leader-start"})

    broker._load_daemon_registry()

    assert "dmn_" + "a" * 32 not in broker._daemons


@pytest.mark.parametrize("group_state", [False, None])
def test_recovery_rejects_exited_leader_when_group_is_gone_or_indeterminate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, group_state: bool | None
) -> None:
    broker = _broker(tmp_path)
    _write_registry_row(broker, _registry_row(broker))
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(commands_module, "_process_leader_exited", lambda _pid: True, raising=False)
    monkeypatch.setattr(commands_module, "_process_group_liveness", lambda _pgid: group_state, raising=False)

    broker._load_daemon_registry()

    assert "dmn_" + "a" * 32 not in broker._daemons


def test_recovery_rejects_pid_reuse_even_when_group_is_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    _write_registry_row(broker, _registry_row(broker))
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: {"pid": 4321, "start_time": "reused"})
    monkeypatch.setattr(commands_module, "_process_group_liveness", lambda _pgid: True, raising=False)
    monkeypatch.setattr(
        commands_module, "_process_leader_exited",
        lambda _pid: pytest.fail("reused PID must not enter orphan recovery"), raising=False,
    )

    broker._load_daemon_registry()

    assert "dmn_" + "a" * 32 not in broker._daemons


def test_windows_recovery_rejects_reused_pid_outside_named_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    row = _registry_row(broker)
    row["job_name"] = commands_module._daemon_job_name(str(row["daemon_id"]))
    _write_registry_row(broker, row, version=4)
    monkeypatch.setattr(commands_module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        commands_module, "process_identity",
        lambda pid: {"pid": pid, "creation_identity": 9999},
    )
    monkeypatch.setattr(commands_module, "_open_named_daemon_job", lambda _name: 77)
    close_job = mock.Mock(return_value=True)
    monkeypatch.setattr(commands_module, "close_job_object", close_job)
    membership = mock.Mock(side_effect=AssertionError("reused PID must not be trusted"))
    monkeypatch.setattr(commands_module, "_windows_job_contains_process", membership)

    broker._load_daemon_registry()

    assert str(row["daemon_id"]) not in broker._daemons
    close_job.assert_called_once_with(77)
    membership.assert_not_called()


@pytest.mark.parametrize(
    ("failure", "expected"),
    [(None, True), (ProcessLookupError, False), (PermissionError, None), (OSError, None)],
)
def test_process_group_liveness_is_tristate(
    monkeypatch: pytest.MonkeyPatch, failure: type[BaseException] | None, expected: bool | None
) -> None:
    def killpg(_pgid: int, _signal: int) -> None:
        if failure is not None:
            raise failure()

    monkeypatch.setattr(commands_module, "os", SimpleNamespace(name="posix", killpg=killpg))

    assert commands_module._process_group_liveness(4321) is expected


def test_recovered_daemon_stop_fails_closed_without_process_tree_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = {"pid": 4321, "start_time": "leader-start"}
    process = commands_module._RecoveredDaemonProcess(4321, identity, 4321)
    info = {"process": process, "pid": 4321, "identity": identity}
    monkeypatch.setattr(
        commands_module, "terminate_tree",
        lambda *_args, **_kwargs: pytest.fail("recovered daemon must not be signaled"),
    )

    if os.name == "nt":
        with pytest.raises(OSError, match="no stable process-tree ownership handle"):
            process.kill()
    else:
        assert process.kill() is False
    assert commands_module._stop_daemon_tree(info) is False


def _patch_daemon_popen(monkeypatch: pytest.MonkeyPatch, launch):
    original_popen = subprocess.Popen

    def dispatch(args, *positional, **kwargs):
        argv = list(args) if isinstance(args, (list, tuple)) else str(args).split()
        executable = str(argv[0]).replace("\\", "/").rsplit("/", 1)[-1].casefold() if argv else ""
        if executable in {"git", "git.exe"} and any(
            value in argv for value in ("rev-parse", "symbolic-ref", "worktree")
        ):
            return original_popen(args, *positional, **kwargs)
        return launch(args, *positional, **kwargs)

    monkeypatch.setattr(commands_module.subprocess, "Popen", dispatch)


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


def test_spawn_daemon_rejects_disallowed_command_when_policy_blocking_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path, policy_blocking=False)
    monkeypatch.setattr(
        broker,
        "classify",
        lambda _command: {"class": "mutating", "allowed": False, "reason": "restricted command"},
    )
    launches: list[object] = []

    def fail_if_launched(*args: object, **_kwargs: object) -> None:
        launches.append(args)
        raise AssertionError("policy-disallowed daemon reached process launch")

    monkeypatch.setattr(commands_module.subprocess, "Popen", fail_if_launched)
    result = broker.spawn_daemon(
        [sys.executable, "-c", "pass"], str(tmp_path), task_id="daemon-test"
    )

    assert result["success"] is False
    assert result["policy_blocked"] is True
    assert result["classification"]["allowed"] is False
    assert not launches


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


def test_spawn_daemon_policy_enforces_task_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    broker = _broker(tmp_path)
    exhausted_budget = SimpleNamespace(
        is_exhausted=lambda: True,
        used_tokens=12,
        max_tokens=12,
        used_compute_seconds=5.0,
        max_compute_seconds=5.0,
        used_external_calls=0,
        max_external_calls=50,
    )
    monkeypatch.setattr(broker.policy_engine, "get_budget", lambda task_id: exhausted_budget)

    result = broker.authorize_auxiliary_action(
        "spawn_daemon", endpoint="commands.spawn_daemon", task_id="daemon-test"
    )

    assert result["allowed"] is False
    assert "task budget exhausted (daemon-test)" in result["reason"]


def test_spawn_daemon_policy_fails_closed_for_missing_task(tmp_path: Path) -> None:
    broker = _broker(tmp_path)

    result = broker.authorize_auxiliary_action(
        "spawn_daemon", endpoint="commands.spawn_daemon", task_id="missing-task"
    )

    assert result["allowed"] is False
    assert result["terminal"] is True
    assert "task" in result["reason"].lower()


def test_spawn_daemon_reauthorizes_immediately_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    launches: list[object] = []
    original_environment = broker._daemon_environment

    def revoke_after_preflight(extra: dict[str, str] | None = None) -> dict[str, str]:
        environment = original_environment(extra)
        broker.config["agent_policy"]["allow_developer_authorized_mutations"] = False
        return environment

    def fail_if_launched(*args: object, **_kwargs: object) -> None:
        launches.append(args)
        raise AssertionError("revoked daemon reached process launch")

    monkeypatch.setattr(broker, "_daemon_environment", revoke_after_preflight)
    monkeypatch.setattr(commands_module.subprocess, "Popen", fail_if_launched)

    result = broker.spawn_daemon(
        [sys.executable, "-c", "pass"], str(tmp_path), task_id="daemon-test"
    )

    assert result["success"] is False
    assert result["policy_blocked"] is True
    assert result["policy"]["allowed"] is False
    assert not launches
    assert not list((tmp_path / "state" / "daemons").glob("*.log"))


def test_spawn_daemon_blocks_worktree_replacement_before_process_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    original_require = broker._require_task_worktree
    checks = 0
    launches: list[object] = []

    def replace_registration_after_preflight(task_id, cwd, command=None):
        nonlocal checks
        checks += 1
        if checks == 1:
            return original_require(task_id, cwd, command)
        return "registered task worktree changed after preflight"

    def fail_if_launched(*args: object, **_kwargs: object) -> None:
        launches.append(args)
        raise AssertionError("daemon reached process launch after worktree replacement")

    monkeypatch.setattr(broker, "_require_task_worktree", replace_registration_after_preflight)
    monkeypatch.setattr(commands_module.subprocess, "Popen", fail_if_launched)

    result = broker.spawn_daemon(
        [sys.executable, "-c", "pass"], str(tmp_path), task_id="daemon-test"
    )

    assert checks == 2
    assert result["success"] is False
    assert "worktree" in result["error"].lower()
    assert not launches


@pytest.mark.skipif(
    os.name != "nt",
    reason="suspended-process worktree revalidation is Windows-specific",
)
def test_spawn_daemon_revalidates_task_worktree_before_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    resume_calls: list[int] = []
    job_anchored = False
    original_require = broker._require_task_worktree

    def require_worktree_until_job_anchor(task_id, cwd, command=None):
        if job_anchored:
            return "registered task worktree changed after job anchor"
        return original_require(task_id, cwd, command)

    monkeypatch.setattr(broker, "_require_task_worktree", require_worktree_until_job_anchor)

    class SuspendedProcess:
        pid = 43211
        _local_ai_job_handle = None

        def __init__(self) -> None:
            self.alive = True

        def poll(self) -> int | None:
            return None if self.alive else 1

        def kill(self) -> None:
            self.alive = False

        def wait(self, timeout: float | None = None) -> int:
            self.alive = False
            return 1

    process = SuspendedProcess()

    def replace_worktree_after_job_anchor(_handle: object, _child: object) -> bool:
        nonlocal job_anchored
        job_anchored = True
        return True

    def terminate_suspended_job(_handle: object) -> bool:
        process.alive = False
        return True

    monkeypatch.setattr(
        commands_module, "_create_named_daemon_job", lambda _daemon_id: 77
    )
    monkeypatch.setattr(commands_module, "assign_process_to_job", lambda *_args: True)
    monkeypatch.setattr(
        commands_module,
        "_duplicate_job_handle_into_process",
        replace_worktree_after_job_anchor,
    )
    monkeypatch.setattr(
        commands_module,
        "_resume_suspended_process",
        lambda child: resume_calls.append(child.pid) or True,
    )
    monkeypatch.setattr(
        commands_module,
        "process_identity",
        lambda pid: {"pid": pid, "start_time": "spawned"},
    )
    monkeypatch.setattr(
        commands_module, "terminate_job_object", terminate_suspended_job
    )
    monkeypatch.setattr(commands_module, "close_job_object", lambda _handle: True)
    monkeypatch.setattr(commands_module.subprocess, "Popen", lambda *_args, **_kwargs: process)

    result = broker.spawn_daemon(
        [sys.executable, "-c", "pass"], str(tmp_path), task_id="daemon-test"
    )

    assert result["success"] is False
    assert "worktree" in result["error"].lower()
    assert "before daemon resume" in result["error"].lower()
    assert not resume_calls
    assert not process.alive
    assert broker._daemons == {}


@pytest.mark.skipif(os.name != "nt", reason="suspended-process authorization is Windows-specific")
def test_spawn_daemon_reauthorizes_after_suspended_process_creation_before_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    authorization_calls = 0
    resume_calls: list[int] = []
    original_authorize = broker.authorize_auxiliary_action

    def revoke_after_create(action: str, **kwargs: object) -> dict[str, object]:
        nonlocal authorization_calls
        authorization_calls += 1
        if authorization_calls == 3:
            return {"allowed": False, "reason": "grant revoked before resume"}
        return original_authorize(action, **kwargs)

    class SuspendedProcess:
        pid = 43210
        _local_ai_job_handle = None

        def __init__(self) -> None:
            self.alive = True

        def poll(self) -> int | None:
            return None if self.alive else 1

        def kill(self) -> None:
            self.alive = False

        def wait(self, timeout: float | None = None) -> int:
            self.alive = False
            return 1

    process = SuspendedProcess()
    monkeypatch.setattr(broker, "authorize_auxiliary_action", revoke_after_create)
    monkeypatch.setattr(commands_module, "_create_named_daemon_job", lambda _daemon_id: 77)
    monkeypatch.setattr(commands_module, "assign_process_to_job", lambda *_args: True)
    monkeypatch.setattr(commands_module, "_duplicate_job_handle_into_process", lambda *_args: True)
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: "fake-identity")

    def stop_suspended_tree(info: dict[str, object]) -> bool:
        setattr(info["process"], "_local_ai_job_handle", None)
        return True

    monkeypatch.setattr(
        commands_module,
        "_stop_daemon_tree",
        stop_suspended_tree,
    )
    _patch_daemon_popen(monkeypatch, lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        commands_module,
        "_resume_suspended_process",
        lambda child: resume_calls.append(child.pid) or True,
    )

    original_start = commands_module.threading.Thread.start

    def fail_log_reader(thread: object) -> None:
        if str(getattr(thread, "name", "")).startswith("local-ai-daemon-log-"):
            raise RuntimeError("simulated reader startup failure")
        original_start(thread)  # type: ignore[arg-type]

    monkeypatch.setattr(commands_module.threading.Thread, "start", fail_log_reader)
    result = broker.spawn_daemon(
        [sys.executable, "-c", "pass"], str(tmp_path), task_id="daemon-test"
    )

    assert authorization_calls == 3
    assert result["success"] is False
    assert result.get("policy_blocked") is True, result
    assert result.get("policy", {}).get("reason") == "grant revoked before resume", result
    assert resume_calls == []
    assert process.alive is False
    assert broker._daemons == {}


def test_spawn_daemon_rejects_foreign_worktree_registration_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    foreign_worktree = tmp_path.parent / f"{tmp_path.name}-foreign"
    foreign_worktree.mkdir()
    original_require = broker._require_task_worktree
    checks = 0
    launches: list[object] = []

    def replace_registration_after_preflight(task_id, cwd, command=None):
        nonlocal checks
        checks += 1
        result = original_require(task_id, cwd, command)
        if checks == 1:
            broker.task_store.worktree["worktree_path"] = str(foreign_worktree)
        return result

    def fail_if_launched(*args: object, **_kwargs: object) -> None:
        launches.append(args)
        raise AssertionError("daemon reached process launch after worktree replacement")

    monkeypatch.setattr(broker, "_require_task_worktree", replace_registration_after_preflight)
    _patch_daemon_popen(monkeypatch, fail_if_launched)

    result = broker.spawn_daemon(
        [sys.executable, "-c", "pass"], str(tmp_path), task_id="daemon-test"
    )

    assert checks == 2
    assert result["success"] is False
    assert "worktree" in result["error"].lower()
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


def test_spawn_daemon_blocks_python_file_write_misclassified_as_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path, policy_blocking=True, allow_mutating=False, allow_unknown=False)
    launches: list[object] = []

    def fail_if_launched(*args: object, **_kwargs: object) -> None:
        launches.append(args)
        raise AssertionError("Python file-writing daemon bypassed command policy")

    monkeypatch.setattr(commands_module.subprocess, "Popen", fail_if_launched)
    result = broker.spawn_daemon(
        [sys.executable, "-c", "from pathlib import Path; Path('daemon-write.txt').write_text('x')"],
        str(tmp_path),
        task_id="daemon-test",
    )

    assert result["policy_blocked"] is True
    assert not launches


def test_spawn_daemon_blocks_disallowed_mutation_when_policy_blocking_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path, policy_blocking=False, allow_mutating=False, allow_unknown=False)
    launches: list[object] = []

    def fail_if_launched(*args: object, **_kwargs: object) -> None:
        launches.append(args)
        raise AssertionError("disallowed mutation reached daemon process launch")

    monkeypatch.setattr(commands_module.subprocess, "Popen", fail_if_launched)
    result = broker.spawn_daemon(
        [sys.executable, "-c", "from pathlib import Path; Path('daemon-write.txt').write_text('x')"],
        str(tmp_path),
        task_id="daemon-test",
    )

    assert result["success"] is False
    assert result["policy_blocked"] is True
    assert result["classification"]["allowed"] is False
    assert not launches


@pytest.mark.parametrize(
    "snippet",
    ["print('Path.write_text(')", "print('Path.write_bytes(')"],
)
def test_spawn_daemon_allows_python_that_only_mentions_file_write_methods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snippet: str
) -> None:
    broker = _broker(tmp_path, policy_blocking=True, allow_mutating=False, allow_unknown=False)
    launches: list[object] = []

    def record_launch(*args: object, **_kwargs: object) -> None:
        launches.append(args)
        raise OSError("test launch boundary")

    monkeypatch.setattr(commands_module.subprocess, "Popen", record_launch)
    result = broker.spawn_daemon(
        [sys.executable, "-c", snippet], str(tmp_path), task_id="daemon-test"
    )

    assert result["success"] is False
    assert result.get("policy_blocked") is not True
    assert len(launches) == 1


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
    broker = _broker(tmp_path, daemon_log_max_bytes=max_log_bytes, allow_unknown=True)
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
        "owner_id": broker._daemon_owner_id,
        "task_id": "daemon-test",
        "name": "stuck",
        "command": "sleep forever",
        "cwd": str(tmp_path),
        "log_path": str(tmp_path / "stuck.log"),
        "log_fh": mock.MagicMock(),
        "_log_closed": False,
    }

    with mock.patch("local_ai_hub.commands.terminate_tree"):
        result = broker.stop_daemon("stuck", task_id="daemon-test")

    assert result["success"] is False
    assert result["running"] is True
    assert result["error"] == "daemon did not stop within the bounded termination window"


def test_stop_daemon_requires_policy_before_tree_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    broker._daemons["other-owner-daemon"] = {
        "process": SimpleNamespace(pid=54321, poll=lambda: None),
        "pid": 54321,
        "process_tree_stopped": False,
    }
    monkeypatch.setattr(
        broker,
        "authorize_auxiliary_action",
        lambda *_args, **_kwargs: {"allowed": False, "reason": "stop grant required"},
    )
    cleanup_calls: list[int] = []
    monkeypatch.setattr(
        commands_module,
        "_stop_daemon_tree",
        lambda info: cleanup_calls.append(int(info["pid"])) or True,
    )

    result = broker.stop_daemon("other-owner-daemon")

    assert result["success"] is False
    assert result["policy_blocked"] is True
    assert result["policy"]["reason"] == "stop grant required"
    assert cleanup_calls == []


def test_stop_daemon_rejects_a_different_task_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path, allow_unknown=True)
    daemon = broker.spawn_daemon(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        str(tmp_path),
        task_id="daemon-test",
    )
    assert daemon["success"] is True
    monkeypatch.setattr(
        broker,
        "authorize_auxiliary_action",
        lambda *_args, **_kwargs: {"allowed": True},
    )
    cleanup_calls: list[str] = []
    with monkeypatch.context() as patch:
        patch.setattr(
            commands_module,
            "_stop_daemon_tree",
            lambda info: cleanup_calls.append(str(info["daemon_id"])) or True,
        )
        result = broker.stop_daemon(daemon["daemon_id"], task_id="other-task")
        missing_owner = broker.stop_daemon(daemon["daemon_id"])

    assert result["policy_blocked"] is True
    assert result["error"] == "daemon belongs to a different or unknown task"
    assert missing_owner["policy_blocked"] is True
    assert missing_owner["error"] == "daemon belongs to a different or unknown task"
    assert cleanup_calls == []
    assert broker.stop_daemon(daemon["daemon_id"], task_id="daemon-test")["success"] is True


def test_daemon_stop_task_id_flows_through_internal_service() -> None:
    from local_ai_hub.services import LocalAIServices

    calls: list[tuple[str, str]] = []

    class BrokerStub:
        def authorize_auxiliary_action(
            self, action: str, *, endpoint: str = "", task_id: str = ""
        ) -> dict[str, Any]:
            return {"allowed": action == "stop_daemon" and task_id == "daemon-test"}

        def stop_daemon(self, daemon_id: str, *, task_id: str = "") -> dict[str, Any]:
            calls.append((daemon_id, task_id))
            return {"success": True}

    service = object.__new__(LocalAIServices)
    service.commands = BrokerStub()

    daemon_id = "dmn_" + "a" * 32
    task_id = "daemon-test"
    result = service.command(
        {"action": "stop_daemon", "daemon_id": daemon_id, "task_id": task_id},
    )
    assert result["success"] is True
    assert calls == [(daemon_id, task_id)]


def test_daemon_status_is_observational_and_redacts_sensitive_command_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    cleanup_calls: list[str] = []
    monkeypatch.setattr(
        commands_module,
        "_stop_daemon_tree",
        lambda info: cleanup_calls.append(str(info["daemon_id"])) or True,
    )
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
    assert result["status"] == "cleanup_unconfirmed"
    assert cleanup_calls == []


def test_daemon_accepts_structured_argv_without_shell(tmp_path: Path) -> None:
    broker = _broker(tmp_path, allow_unknown=True)

    daemon = broker.spawn_daemon(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        str(tmp_path),
        name="structured-argv-test",
        task_id="daemon-test",
    )

    assert daemon["success"] is True
    assert broker.stop_daemon(daemon["daemon_id"], task_id="daemon-test")["success"] is True


def test_stop_daemon_does_not_claim_tree_stopped_when_cleanup_is_unconfirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(CommandBroker, "_watch_daemon_exit", lambda *_args: None)
    broker = _broker(tmp_path, allow_unknown=True)
    daemon = broker.spawn_daemon([sys.executable, "-c", "pass"], str(tmp_path), task_id="daemon-test")
    assert daemon["success"] is True
    process = broker._daemons[daemon["daemon_id"]]["process"]
    process.wait(timeout=5)
    terminate_calls: list[int] = []

    def unconfirmed(info: dict[str, object]) -> bool:
        terminate_calls.append(int(info["pid"]))
        return False

    monkeypatch.setattr(commands_module, "_stop_daemon_tree", unconfirmed, raising=False)
    result = broker.stop_daemon(daemon["daemon_id"], task_id="daemon-test")

    assert terminate_calls == [daemon["pid"], daemon["pid"]]
    assert result["success"] is False
    assert result["status"] == "cleanup_unconfirmed"
    assert result["running"] is False

    monkeypatch.setattr(commands_module, "_stop_daemon_tree", lambda *_args, **_kwargs: True)
    assert broker.stop_daemon(daemon["daemon_id"], task_id="daemon-test")["success"] is True


def test_daemon_status_requires_policy_and_scopes_result_to_task() -> None:
    class _ScopedBroker:
        status_calls: list[tuple[str | None, str | None]] = []

        def authorize_auxiliary_action(self, action: str, *, endpoint: str, task_id: str):
            return {"allowed": action == "daemon_status" and task_id == "task-a"}

        def daemon_status(self, daemon_id: str | None = None, *, task_id: str | None = None):
            self.status_calls.append((daemon_id, task_id))
            return {"success": True, "daemon_id": daemon_id, "task_id": task_id}

    broker = _ScopedBroker()
    services = object.__new__(LocalAIServices)
    services.commands = broker

    denied = services.daemon_status("daemon-a")
    assert denied["policy_blocked"] is True
    assert broker.status_calls == []

    scoped = services.daemon_status("daemon-a", task_id="task-a")
    assert scoped == {"success": True, "daemon_id": "daemon-a", "task_id": "task-a"}
    assert broker.status_calls == [("daemon-a", "task-a")]


def test_spawn_daemon_retains_tracking_when_registry_and_cleanup_retry_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)

    class UnstoppableProcess:
        pid = 43211

        def __init__(self) -> None:
            self.alive = True
            self.wait_calls = 0

        def poll(self) -> int | None:
            return None if self.alive else 1

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls += 1
            raise subprocess.TimeoutExpired(["daemon"], timeout)

        def kill(self) -> None:
            self.alive = False

    process = UnstoppableProcess()
    _patch_daemon_popen(monkeypatch, lambda *_args, **_kwargs: process)
    monkeypatch.setattr(commands_module, "process_identity", lambda pid: {"pid": pid, "creation_identity": 1})
    monkeypatch.setattr(commands_module, "_create_named_daemon_job", lambda _daemon_id: 77)
    monkeypatch.setattr(commands_module, "assign_process_to_job", lambda *_args: True)
    monkeypatch.setattr(commands_module, "_duplicate_job_handle_into_process", lambda *_args: True)
    monkeypatch.setattr(commands_module, "_resume_suspended_process", lambda _child: True)
    monkeypatch.setattr(commands_module, "close_job_object", lambda _handle: True)
    stop_calls = 0

    def fail_stop(_info: dict[str, Any]) -> bool:
        nonlocal stop_calls
        stop_calls += 1
        return False

    monkeypatch.setattr(commands_module, "_stop_daemon_tree", fail_stop)
    persistence_results = iter((True, False) if os.name == "nt" else (False,))
    monkeypatch.setattr(broker, "_persist_daemon_registry", lambda: next(persistence_results, False))
    expiry_calls: list[str] = []
    monkeypatch.setattr(
        broker,
        "_schedule_daemon_expiry",
        lambda info: expiry_calls.append(str(info["daemon_id"])),
    )
    original_start = commands_module.threading.Thread.start

    def fail_log_reader(thread: object) -> None:
        if str(getattr(thread, "name", "")).startswith("local-ai-daemon-log-"):
            raise RuntimeError("simulated reader startup failure")
        original_start(thread)  # type: ignore[arg-type]

    monkeypatch.setattr(commands_module.threading.Thread, "start", fail_log_reader)
    result = broker.spawn_daemon(
        [sys.executable, "-c", "pass"], str(tmp_path), task_id="daemon-test"
    )

    assert result["success"] is False
    assert result.get("outcome_unknown") is True, result
    assert result.get("cleanup_unconfirmed") is True, result
    assert result.get("registry_persisted") is False, result
    assert stop_calls == 2
    daemon_id = str(result["daemon_id"])
    info = broker._daemons[daemon_id]
    assert process.alive is True
    assert process.wait_calls == 0
    assert info["_slot_released"] is False
    assert expiry_calls == [daemon_id]

    process.alive = False
    broker._close_daemon_log(info)
    broker._release_daemon_slot(info)
    broker._daemons.pop(daemon_id, None)


def test_retry_stop_unpersisted_daemon_removes_tracking_after_confirmed_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)

    class StoppableProcess:
        def __init__(self) -> None:
            self.alive = True
            self.wait_calls = 0

        def poll(self) -> int | None:
            return None if self.alive else 0

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls += 1
            self.alive = False
            return 0

    process = StoppableProcess()
    daemon_id = "unpersisted-daemon"
    info = {"daemon_id": daemon_id, "process": process, "_slot_released": False}
    broker._daemons[daemon_id] = info
    monkeypatch.setattr(commands_module, "_stop_daemon_tree", lambda _info: True)
    monkeypatch.setattr(broker, "_persist_daemon_registry", lambda: True)

    stopped = broker._retry_stop_unpersisted_daemon(daemon_id, info)

    assert stopped is True
    assert process.wait_calls == 1
    assert daemon_id not in broker._daemons
    assert info["_slot_released"] is False


@pytest.mark.parametrize("final_registry_persisted", [False, True])
def test_spawn_daemon_retries_cleanup_when_registry_persistence_fails(
    final_registry_persisted: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = _broker(tmp_path)

    class StoppableProcess:
        pid = 43212

        def __init__(self) -> None:
            self.alive = True
            self.wait_calls = 0

        def poll(self) -> int | None:
            return None if self.alive else 0

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls += 1
            self.alive = False
            return 0

    process = StoppableProcess()
    _patch_daemon_popen(monkeypatch, lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        commands_module,
        "process_identity",
        lambda pid: {"pid": pid, "creation_identity": 1},
    )
    monkeypatch.setattr(commands_module, "_create_named_daemon_job", lambda _daemon_id: 77)
    monkeypatch.setattr(commands_module, "assign_process_to_job", lambda *_args: True)
    monkeypatch.setattr(commands_module, "_duplicate_job_handle_into_process", lambda *_args: True)
    monkeypatch.setattr(commands_module, "_resume_suspended_process", lambda _child: True)
    monkeypatch.setattr(commands_module, "close_job_object", lambda _handle: True)
    stop_calls = 0
    original_stop_daemon_tree = commands_module._stop_daemon_tree

    def stop_then_confirm(candidate_info: dict[str, Any]) -> bool:
        nonlocal stop_calls
        if candidate_info.get("process") is not process:
            return original_stop_daemon_tree(candidate_info)
        stop_calls += 1
        return stop_calls > 1

    monkeypatch.setattr(commands_module, "_stop_daemon_tree", stop_then_confirm)
    persistence_results = iter(
        (True, False, final_registry_persisted)
        if os.name == "nt"
        else (False, final_registry_persisted)
    )
    monkeypatch.setattr(
        broker,
        "_persist_daemon_registry",
        lambda: next(persistence_results),
    )
    original_start = commands_module.threading.Thread.start

    def fail_log_reader(thread: object) -> None:
        if str(getattr(thread, "name", "")).startswith("local-ai-daemon-log-"):
            raise RuntimeError("simulated reader startup failure")
        original_start(thread)  # type: ignore[arg-type]

    monkeypatch.setattr(commands_module.threading.Thread, "start", fail_log_reader)
    result = broker.spawn_daemon(
        [sys.executable, "-c", "pass"], str(tmp_path), task_id="daemon-test"
    )

    assert result["success"] is False
    assert result["registry_persisted"] is final_registry_persisted
    assert result.get("outcome_unknown") is not True
    assert stop_calls == 2
    assert process.wait_calls == 1
    assert process.alive is False
    assert broker._daemons == {}


@pytest.mark.skipif(
    os.name != "nt",
    reason="suspended-process worktree revalidation is Windows-specific",
)
def test_spawn_daemon_rejects_foreign_worktree_registration_before_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path)
    foreign_worktree = tmp_path.parent / f"{tmp_path.name}-foreign"
    foreign_worktree.mkdir()
    resume_calls: list[int] = []

    class SuspendedProcess:
        pid = 43211
        _local_ai_job_handle = None

        def __init__(self) -> None:
            self.alive = True

        def poll(self) -> int | None:
            return None if self.alive else 1

        def kill(self) -> None:
            self.alive = False

        def wait(self, timeout: float | None = None) -> int:
            self.alive = False
            return 1

    process = SuspendedProcess()

    def replace_worktree_after_job_anchor(_handle: object, _child: object) -> bool:
        broker.task_store.worktree["worktree_path"] = str(foreign_worktree)
        return True

    def terminate_suspended_job(_handle: object) -> bool:
        process.alive = False
        return True

    monkeypatch.setattr(
        commands_module, "_create_named_daemon_job", lambda _daemon_id: 77
    )
    monkeypatch.setattr(commands_module, "assign_process_to_job", lambda *_args: True)
    monkeypatch.setattr(
        commands_module,
        "_duplicate_job_handle_into_process",
        replace_worktree_after_job_anchor,
    )
    monkeypatch.setattr(
        commands_module,
        "_resume_suspended_process",
        lambda child: resume_calls.append(child.pid) or True,
    )
    monkeypatch.setattr(
        commands_module,
        "process_identity",
        lambda pid: {"pid": pid, "start_time": "spawned"},
    )
    monkeypatch.setattr(
        commands_module, "terminate_job_object", terminate_suspended_job
    )
    monkeypatch.setattr(commands_module, "close_job_object", lambda _handle: True)
    _patch_daemon_popen(monkeypatch, lambda *_args, **_kwargs: process)

    result = broker.spawn_daemon(
        [sys.executable, "-c", "pass"], str(tmp_path), task_id="daemon-test"
    )

    assert result["success"] is False
    assert "worktree" in result["error"].lower()
    assert "before daemon resume" in result["error"].lower()
    assert not resume_calls
    assert not process.alive
    assert broker._daemons == {}


def test_recovered_daemon_fails_closed_without_live_kernel_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = {"pid": 4321, "start_time": "stable-looking-but-not-a-handle"}
    recovered = commands_module._RecoveredDaemonProcess(4321, identity)
    monkeypatch.setattr(commands_module, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: identity)
    terminate = mock.Mock(side_effect=AssertionError("recovered PID must not be signaled"))
    monkeypatch.setattr(commands_module, "terminate_tree", terminate)

    assert recovered.poll() is None
    assert commands_module._stop_daemon_tree(
        {"process": recovered, "pid": 4321, "identity": identity, "process_group_id": 4321}
    ) is False
    with pytest.raises(OSError, match="no stable process-tree ownership handle"):
        recovered.kill()
    terminate.assert_not_called()


def test_recovered_daemon_fails_closed_on_windows_without_job_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = {"pid": 4321, "creation_identity": 1234}
    recovered = commands_module._RecoveredDaemonProcess(4321, identity)
    monkeypatch.setattr(commands_module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: identity)
    terminate = mock.Mock(side_effect=AssertionError("recovered PID must not be signaled"))
    monkeypatch.setattr(commands_module, "terminate_tree", terminate)

    assert commands_module._stop_daemon_tree(
        {"process": recovered, "pid": 4321, "identity": identity}
    ) is False
    with pytest.raises(OSError, match="no stable process-tree ownership handle"):
        recovered.kill()
    terminate.assert_not_called()


def test_live_windows_daemon_uses_stable_job_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LiveProcess:
        _local_ai_job_handle = 77

    monkeypatch.setattr(commands_module, "os", SimpleNamespace(name="nt"))
    terminate = mock.Mock()
    close = mock.Mock(return_value=True)
    monkeypatch.setattr(commands_module, "terminate_job_object", terminate)
    monkeypatch.setattr(commands_module, "_wait_windows_job_empty", lambda *_args: True)
    monkeypatch.setattr(commands_module, "close_job_object", close)

    assert commands_module._stop_daemon_tree({"process": LiveProcess(), "pid": 4321}) is True
    terminate.assert_called_once_with(77)
    close.assert_called_once_with(77)


@pytest.mark.skipif(os.name != "nt", reason="Windows Popen cleanup fallback")
def test_stop_daemon_does_not_kill_only_leader_when_tree_stop_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path, allow_unknown=True)
    daemon = broker.spawn_daemon(
        f'"{sys.executable}" -c "import time; time.sleep(60)"',
        str(tmp_path), name="tree-stop-failure-test", task_id="daemon-test",
    )
    assert daemon["success"] is True
    process = broker._daemons[daemon["daemon_id"]]["process"]
    kill = mock.Mock()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(commands_module, "_stop_daemon_tree", lambda *_args: False)
            patch.setattr(process, "kill", kill)
            patch.setattr(
                process, "wait",
                mock.Mock(side_effect=subprocess.TimeoutExpired("daemon", 2.0)),
            )
            result = broker.stop_daemon(daemon["daemon_id"], task_id="daemon-test")

        assert result["success"] is False
        assert result["status"] == "running"
        kill.assert_not_called()
    finally:
        if process.poll() is None:
            assert broker.stop_daemon(daemon["daemon_id"], task_id="daemon-test")["success"] is True


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object process-tree integration")
def test_stop_daemon_leaves_no_child_process_orphan(
    tmp_path: Path,
) -> None:
    # The launcher creates a child and writes its PID inside the registered
    # task worktree, so this integration fixture explicitly permits mutation.
    broker = _broker(tmp_path, allow_mutating=True)
    child_pid_file = tmp_path / "daemon-child.pid"
    parent_code = (
        "import pathlib, subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='ascii'); "
        "time.sleep(60)"
    )
    parent_script = tmp_path / "daemon_parent.py"
    parent_script.write_text(parent_code, encoding="utf-8")
    daemon = broker.spawn_daemon(
        [sys.executable, str(parent_script), str(child_pid_file)],
        str(tmp_path),
        name="explicit-tree-stop-test",
        task_id="daemon-test",
    )
    assert daemon["success"] is True, daemon
    process = broker._daemons[daemon["daemon_id"]]["process"]
    child_pid: int | None = None
    child_identity: object | None = None
    try:
        deadline = time.monotonic() + 5
        while (not child_pid_file.exists() or not child_pid_file.stat().st_size) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child_pid_file.exists() and child_pid_file.stat().st_size, "daemon leader did not start its child"
        child_pid = int(child_pid_file.read_text(encoding="ascii"))
        child_identity = commands_module.process_identity(child_pid)
        assert child_identity is not None, "daemon child exited before broker stop"

        stopped = broker.stop_daemon(daemon["daemon_id"], task_id="daemon-test")

        assert stopped["success"] is True
        assert stopped["status"] == "stopped"
        assert stopped["process_tree_stopped"] is True
        assert process.poll() is not None, "daemon leader remained alive after stop"
        deadline = time.monotonic() + 5
        while commands_module.process_identity(child_pid) is not None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert commands_module.process_identity(child_pid) != child_identity, "daemon child remained alive after stop"
    finally:
        if process.poll() is None:
            broker.stop_daemon(daemon["daemon_id"], task_id="daemon-test")


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
    # The launcher creates a child and publishes its PID in the task worktree.
    broker = _broker(tmp_path, allow_mutating=True)
    child_pid_file = tmp_path / "daemon-child.pid"
    parent_code = (
        "import pathlib, subprocess, sys; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='ascii')"
    )
    parent_script = tmp_path / "daemon_parent.py"
    parent_script.write_text(parent_code, encoding="utf-8")
    daemon = broker.spawn_daemon(
        [sys.executable, str(parent_script), str(child_pid_file)], str(tmp_path), name="orphan-child-test", task_id="daemon-test"
    )
    assert daemon["success"] is True, daemon
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
        assert broker.stop_daemon(daemon["daemon_id"], task_id="daemon-test")["success"] is True
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

    assert [attempt for attempt in attempts if attempt == daemon["daemon_id"]] == [daemon["daemon_id"]] * 6
    assert broker._daemons[daemon["daemon_id"]]["ttl_stop_failed"] is True
    monkeypatch.undo()
    broker.stop_daemon(daemon["daemon_id"], task_id="daemon-test")


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
            broker.stop_daemon(result["daemon_id"], task_id="daemon-test")


def test_daemon_ttl_schedules_remaining_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path, daemon_ttl_seconds=1, allow_unknown=True)
    timers: list[object] = []

    class RecordingTimer:
        def __init__(self, interval, function, *, args):
            self.interval = interval
            self.function = function
            self.args = args
            self.daemon = False
            self.started = False
            self.cancelled = False
            timers.append(self)

        def start(self):
            self.started = True

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(commands_module, "threading", SimpleNamespace(Timer=RecordingTimer))
    monkeypatch.setattr(commands_module, "time", SimpleNamespace(time=lambda: 100.0))
    daemon_id = "dmn_ttl_schedule"
    expires_at = 100.5
    info = {"daemon_id": daemon_id, "expires_at": expires_at}

    broker._schedule_daemon_expiry(info)

    timer = timers[0]
    assert timer.interval == 0.5
    assert timer.daemon is True
    assert timer.started is True
    assert timer.function.__self__ is broker
    assert timer.function.__func__ is CommandBroker._expire_daemon
    assert timer.args == (daemon_id,)
    assert info["ttl_timer"] is timer

    info["expires_at"] = 99.9
    broker._schedule_daemon_expiry(info)
    expired_timer = timers[1]
    assert timer.cancelled is True
    assert expired_timer.interval == 0.0
    assert expired_timer.function.__self__ is broker
    assert expired_timer.function.__func__ is CommandBroker._expire_daemon
    assert expired_timer.args == (daemon_id,)
    assert expired_timer.started is True
    assert info["ttl_timer"] is expired_timer


def test_daemon_ttl_stops_owned_process_and_records_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = _broker(tmp_path, daemon_ttl_seconds=1, allow_unknown=True)
    expiry_calls: list[str] = []
    timer_expiry_started = threading.Event()
    timer_expiry_finished = threading.Event()
    original_expire = CommandBroker._expire_daemon

    def record_expiry(self, daemon_id: str) -> None:
        expiry_calls.append(daemon_id)
        is_timer_thread = isinstance(threading.current_thread(), threading.Timer)
        if is_timer_thread:
            timer_expiry_started.set()
        try:
            original_expire(self, daemon_id)
        finally:
            if is_timer_thread:
                timer_expiry_finished.set()

    monkeypatch.setattr(CommandBroker, "_expire_daemon", record_expiry)
    daemon = broker.spawn_daemon(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        str(tmp_path),
        name="ttl-test",
        task_id="daemon-test",
    )
    assert daemon["success"] is True
    daemon_id = daemon["daemon_id"]
    try:
        initial = broker.daemon_status(daemon_id)
        info = broker._daemons[daemon_id]
        assert daemon["owner_id"] == broker._daemon_owner_id
        assert initial["owner_id"] == broker._daemon_owner_id
        assert info["owner_id"] == broker._daemon_owner_id
        assert info["expires_at"] == info["started_at"] + broker.daemon_ttl_seconds

        deadline = time.monotonic() + 6
        diagnostic = {
            "initial_status": initial,
            "elapsed_since_spawn": time.time() - info["started_at"],
            "configured_ttl_seconds": broker.daemon_ttl_seconds,
            "timer_expiry_started": timer_expiry_started.is_set(),
        }
        assert timer_expiry_started.wait(timeout=max(0.0, deadline - time.monotonic())), diagnostic
        assert timer_expiry_finished.wait(timeout=max(0.0, deadline - time.monotonic())), diagnostic
        status = broker.daemon_status(daemon_id)
        while status.get("running") and time.monotonic() < deadline:
            time.sleep(0.05)
            status = broker.daemon_status(daemon_id)

        assert daemon_id in expiry_calls, diagnostic
        assert status["running"] is False, diagnostic
        assert status["status"] == "stopped", diagnostic
        assert status["process_tree_stopped"] is True, diagnostic
        assert status["owner_id"] == broker._daemon_owner_id
    finally:
        if broker.daemon_status(daemon_id).get("running"):
            broker.stop_daemon(daemon_id, task_id="daemon-test")


_DAEMON_CHILD_PID_PUBLICATION = (
    "temporary = sys.argv[1] + '.tmp'\n"
    "with open(temporary, 'w', encoding='ascii') as stream: stream.write(str(child.pid))\n"
    "os.replace(temporary, sys.argv[1])\n"
)


def test_daemon_child_pid_is_not_visible_before_payload_is_complete(tmp_path: Path) -> None:
    pid_path = tmp_path / "child.pid"

    def observed_open(path, *args, **kwargs):
        stream = open(path, *args, **kwargs)
        if pid_path.exists():
            stream.close()
            pytest.fail("PID path visible before its payload is complete")
        return stream

    exec(
        _DAEMON_CHILD_PID_PUBLICATION,
        {"sys": SimpleNamespace(argv=["launcher", str(pid_path)]),
         "child": SimpleNamespace(pid=12345), "os": os, "open": observed_open},
    )
    assert pid_path.read_text(encoding="ascii") == "12345"
    assert not pid_path.with_name(pid_path.name + ".tmp").exists()


@pytest.mark.skipif(os.name != "nt", reason="named Job Object persistence is Windows-only")
def test_named_daemon_job_survives_restart_and_stops_descendants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Model a stopped broker: its exit watcher cannot race the replacement
    # broker and reap descendants before named-Job recovery is exercised.
    # Live-broker automatic reaping is covered separately by
    # test_daemon_job_stops_descendants_after_leader_exits.
    monkeypatch.setattr(CommandBroker, "_watch_daemon_exit", lambda *_args: None)
    launcher = tmp_path / "daemon_parent.py"
    child_pid_path = tmp_path / "daemon-child.pid"
    launcher.write_text(
        "import os, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(12)'])\n"
        + _DAEMON_CHILD_PID_PUBLICATION +
        "time.sleep(12)\n",
        encoding="utf-8",
    )
    first = _broker(tmp_path, allow_unknown=True, allow_mutating=True)
    sequence: list[str] = []
    persist = first._persist_daemon_registry
    duplicate = commands_module._duplicate_job_handle_into_process
    resume = commands_module._resume_suspended_process

    def persist_in_order() -> bool:
        result = persist()
        if result:
            sequence.append("registry")
        return result

    def duplicate_in_order(job: int, process: subprocess.Popen[bytes]) -> bool:
        sequence.append("duplicate")
        return duplicate(job, process)

    def resume_in_order(process: subprocess.Popen[bytes]) -> bool:
        sequence.append("resume")
        return resume(process)

    with monkeypatch.context() as patch:
        patch.setattr(first, "_persist_daemon_registry", persist_in_order)
        patch.setattr(commands_module, "_duplicate_job_handle_into_process", duplicate_in_order)
        patch.setattr(commands_module, "_resume_suspended_process", resume_in_order)
        daemon = first.spawn_daemon(
            [sys.executable, str(launcher), str(child_pid_path)],
            str(tmp_path),
            name="named-job-restart-test",
            task_id="daemon-test",
        )
        assert daemon["success"] is True
        assert sequence[:3] == ["registry", "duplicate", "resume"]
    assert daemon["success"] is True
    assert daemon["tree_control_capability"] == "named_job_object"
    deadline = time.monotonic() + 5.0
    while not child_pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.025)
    assert child_pid_path.exists()
    child_pid = int(child_pid_path.read_text(encoding="ascii"))
    assert commands_module.process_identity(child_pid) is not None

    first_process = first._daemons[daemon["daemon_id"]]["process"]
    old_job_handle = getattr(first_process, "_local_ai_job_handle", None)
    assert isinstance(old_job_handle, int) and not isinstance(old_job_handle, bool)
    assert commands_module.close_job_object(old_job_handle) is True
    first_process._local_ai_job_handle = None

    second = _broker(tmp_path)
    try:
        status = second.daemon_status(daemon["daemon_id"])
        assert status["success"] is True
        assert status["running"] is True
        assert status["tree_control_capability"] == "named_job_object"
        assert status["pid"] == daemon["pid"]
        assert commands_module.process_identity(child_pid) is not None

        stopped = second.stop_daemon(daemon["daemon_id"], task_id="daemon-test")
        assert stopped["success"] is True
        deadline = time.monotonic() + 5.0
        while commands_module.process_identity(child_pid) is not None and time.monotonic() < deadline:
            time.sleep(0.025)
        assert commands_module.process_identity(child_pid) is None
    finally:
        if second.daemon_status(daemon["daemon_id"]).get("running"):
            second.stop_daemon(daemon["daemon_id"], task_id="daemon-test")
        elif first.daemon_status(daemon["daemon_id"]).get("running"):
            first.stop_daemon(daemon["daemon_id"], task_id="daemon-test")

    # A dead leader closes its keeper handle; the broker's remaining handle
    # keeps the named Job reopenable so a new broker can stop surviving children.
    exit_launcher = tmp_path / "daemon_parent_exits.py"
    exit_child_path = tmp_path / "daemon-exit-child.pid"
    exit_launcher.write_text(
        "import os, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(12)'])\n"
        "temporary = sys.argv[1] + '.tmp'\n"
        "with open(temporary, 'w', encoding='ascii') as stream: stream.write(str(child.pid))\n"
        "os.replace(temporary, sys.argv[1])\n",
        encoding="utf-8",
    )
    exited = first.spawn_daemon(
        [sys.executable, str(exit_launcher), str(exit_child_path)],
        str(tmp_path), name="named-job-dead-leader", task_id="daemon-test",
    )
    assert exited["success"] is True
    deadline = time.monotonic() + 5.0
    while not exit_child_path.exists() and time.monotonic() < deadline:
        time.sleep(0.025)
    assert exit_child_path.exists()
    exit_child_pid = int(exit_child_path.read_text(encoding="ascii"))
    deadline = time.monotonic() + 5.0
    while commands_module.process_identity(exited["pid"]) is not None and time.monotonic() < deadline:
        time.sleep(0.025)
    assert commands_module.process_identity(exited["pid"]) is None
    assert commands_module.process_identity(exit_child_pid) is not None
    third = _broker(tmp_path)
    recovered = third.daemon_status(exited["daemon_id"])
    assert recovered["success"] is True
    assert recovered["running"] is True, recovered
    assert third.stop_daemon(exited["daemon_id"], task_id="daemon-test")["success"] is True
    deadline = time.monotonic() + 5.0
    while commands_module.process_identity(exit_child_pid) is not None and time.monotonic() < deadline:
        time.sleep(0.025)
    assert commands_module.process_identity(exit_child_pid) is None
    owner_process = first._daemons[exited["daemon_id"]]["process"]
    owner_handle = getattr(owner_process, "_local_ai_job_handle", None)
    if isinstance(owner_handle, int) and not isinstance(owner_handle, bool):
        assert commands_module.close_job_object(owner_handle) is True
        owner_process._local_ai_job_handle = None

    # If the dead daemon's duplicate and the broker's final handle close, the
    # kill-on-close limit must terminate any descendants still in that Job.
    last_launcher = tmp_path / "daemon_last_handle.py"
    last_child_path = tmp_path / "daemon-last-child.pid"
    last_launcher.write_text(
        "import os, subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(12)'])\n"
        + _DAEMON_CHILD_PID_PUBLICATION,
        encoding="utf-8",
    )
    last = first.spawn_daemon(
        [sys.executable, str(last_launcher), str(last_child_path)],
        str(tmp_path), name="named-job-last-handle", task_id="daemon-test",
    )
    assert last["success"] is True
    deadline = time.monotonic() + 5.0
    while not last_child_path.exists() and time.monotonic() < deadline:
        time.sleep(0.025)
    assert last_child_path.exists()
    last_child_pid = int(last_child_path.read_text(encoding="ascii"))
    deadline = time.monotonic() + 5.0
    while commands_module.process_identity(last["pid"]) is not None and time.monotonic() < deadline:
        time.sleep(0.025)
    assert commands_module.process_identity(last["pid"]) is None
    last_process = first._daemons[last["daemon_id"]]["process"]
    last_handle = getattr(last_process, "_local_ai_job_handle", None)
    assert isinstance(last_handle, int) and not isinstance(last_handle, bool)
    assert commands_module.close_job_object(last_handle) is True
    last_process._local_ai_job_handle = None
    deadline = time.monotonic() + 5.0
    while commands_module.process_identity(last_child_pid) is not None and time.monotonic() < deadline:
        time.sleep(0.025)
    assert commands_module.process_identity(last_child_pid) is None

    # Registration and keeper duplication failures are fail-closed: a
    # suspended process is never resumed and dies with its Job handle.
    real_subprocess = commands_module.subprocess

    def assert_start_failure(failure: str) -> None:
        failed_broker = _broker(tmp_path, allow_unknown=True, allow_mutating=True)
        captured: list[subprocess.Popen[bytes]] = []
        resumed: list[bool] = []

        def capture_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
            child = real_subprocess.Popen(*args, **kwargs)
            if int(kwargs.get("creationflags", 0)) & 0x00000004:
                captured.append(child)
            return child

        class _SubprocessProxy:
            def __getattr__(self, name: str) -> object:
                return capture_popen if name == "Popen" else getattr(real_subprocess, name)

        with monkeypatch.context() as patch:
            patch.setattr(commands_module, "subprocess", _SubprocessProxy())
            patch.setattr(commands_module, "_resume_suspended_process", lambda _proc: resumed.append(True) or True)
            if failure == "registry":
                patch.setattr(failed_broker, "_persist_daemon_registry", lambda: False)
            else:
                patch.setattr(commands_module, "_duplicate_job_handle_into_process", lambda *_args: False)
            result = failed_broker.spawn_daemon(
                [sys.executable, "-c", "import time; time.sleep(12)"],
                str(tmp_path), name=f"named-job-{failure}-failure", task_id="daemon-test",
            )
        assert result["success"] is False
        assert resumed == []
        assert len(captured) == 1
        captured[0].wait(timeout=5.0)
        assert captured[0].poll() is not None

    assert_start_failure("registry")
    assert_start_failure("duplicate")


def test_live_daemon_is_reconciled_after_broker_restart(tmp_path: Path) -> None:
    first = _broker(tmp_path, allow_unknown=True)
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
        assert second._daemons[daemon["daemon_id"]]["task_id"] == "daemon-test"
        stopped = second.stop_daemon(daemon["daemon_id"], task_id="daemon-test")
        assert stopped["success"] is True
        assert stopped["process_tree_stopped"] is True
        assert second._daemons[daemon["daemon_id"]]["process"].poll() is not None
        third = _broker(tmp_path)
        assert third.daemon_status(daemon["daemon_id"])["success"] is False
    finally:
        process = first._daemons[daemon["daemon_id"]]["process"]
        if process.poll() is None:
            first.stop_daemon(daemon["daemon_id"], task_id="daemon-test")
def test_restart_reconciliation_rejects_pid_reuse(tmp_path: Path) -> None:
    first = _broker(tmp_path, allow_unknown=True)
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
        first.stop_daemon(daemon["daemon_id"], task_id="daemon-test")


@pytest.mark.skipif(sys.platform != "linux", reason="Linux /proc ownership proof required")
def test_restart_recovers_and_stops_owned_group_after_leader_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(CommandBroker, "_watch_daemon_exit", lambda *_args: None)
    first = _broker(tmp_path, allow_mutating=True)
    child_pid_file = tmp_path / "daemon-child.pid"
    parent_code = (
        "import pathlib, subprocess, sys; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='ascii')"
    )
    parent_script = tmp_path / "daemon_parent.py"
    parent_script.write_text(parent_code, encoding="utf-8")
    daemon = first.spawn_daemon(
        [sys.executable, str(parent_script), str(child_pid_file)],
        str(tmp_path),
        name="leaderless-group-recovery",
        task_id="daemon-test",
    )
    assert daemon["success"] is True

    recovered: CommandBroker | None = None
    try:
        deadline = time.monotonic() + 5
        while (not child_pid_file.exists() or not child_pid_file.stat().st_size) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child_pid_file.exists() and child_pid_file.stat().st_size
        child_pid = int(child_pid_file.read_text(encoding="ascii"))
        first._daemons[daemon["daemon_id"]]["process"].wait(timeout=5)
        assert commands_module.process_identity(daemon["pid"]) is None

        recovered = _broker(tmp_path, allow_mutating=True)
        status = recovered.daemon_status(daemon["daemon_id"])
        assert status["success"] is True
        assert status["running"] is True
        assert status["pid"] == daemon["pid"]

        stopped = recovered.stop_daemon(daemon["daemon_id"], task_id="daemon-test")
        assert stopped["success"] is True
        assert stopped["process_tree_stopped"] is True
        assert commands_module.process_identity(child_pid) is None
    finally:
        if recovered is not None and daemon["daemon_id"] in recovered._daemons:
            recovered.stop_daemon(daemon["daemon_id"], task_id="daemon-test")
        if daemon["daemon_id"] in first._daemons:
            first.stop_daemon(daemon["daemon_id"], task_id="daemon-test")


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group lifecycle")
def test_posix_daemon_stop_preserves_process_group_lifecycle(tmp_path: Path) -> None:
    broker = _broker(tmp_path, allow_mutating=True)
    child_pid_file = tmp_path / "posix-daemon-child.pid"
    parent_code = (
        "import pathlib, subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='ascii'); "
        "time.sleep(60)"
    )
    parent_script = tmp_path / "daemon_parent.py"
    parent_script.write_text(parent_code, encoding="utf-8")
    daemon = broker.spawn_daemon(
        [sys.executable, str(parent_script), str(child_pid_file)],
        str(tmp_path),
        task_id="daemon-test",
    )
    assert daemon["success"] is True
    info = broker._daemons[daemon["daemon_id"]]
    child_pid: int | None = None
    try:
        deadline = time.monotonic() + 5
        while (not child_pid_file.exists() or not child_pid_file.stat().st_size) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child_pid_file.exists() and child_pid_file.stat().st_size
        child_pid = int(child_pid_file.read_text(encoding="ascii"))
        stopped = broker.stop_daemon(daemon["daemon_id"], task_id="daemon-test")
        assert stopped["success"] is True
        assert stopped["process_tree_stopped"] is True
        assert info["process"].poll() is not None
        deadline = time.monotonic() + 5
        while commands_module.process_identity(child_pid) is not None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert commands_module.process_identity(child_pid) is None
    finally:
        if info["process"].poll() is None:
            broker.stop_daemon(daemon["daemon_id"], task_id="daemon-test")


def test_live_posix_daemon_tree_preserves_process_group_termination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LiveProcess:
        pid = 4321
        _waitpid_lock = object()

        def poll(self) -> None:
            return None

    monkeypatch.setattr(commands_module, "os", SimpleNamespace(name="posix"))
    terminate = mock.Mock(return_value=True)
    monkeypatch.setattr(commands_module, "terminate_tree", terminate)

    result = commands_module._stop_daemon_tree(
        {"process": LiveProcess(), "pid": 4321, "identity": {"pid": 4321}, "process_group_id": 4321}
    )

    assert result is True
    terminate.assert_called_once_with(
        4321,
        process_group=4321,
        expected_identity={"pid": 4321},
        grace_seconds=1.5,
        process_handle=mock.ANY,
    )
