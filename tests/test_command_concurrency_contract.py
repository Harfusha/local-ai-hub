from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from local_ai_hub import commands as commands_module
from local_ai_hub.commands import CommandBroker


def test_log_dispatcher_waits_for_queue_signal_without_polling(tmp_path, monkeypatch) -> None:
    queue_timeouts: list[float | None] = []
    original_queue = commands_module.queue.Queue

    class ObservedQueue(original_queue):
        def get(self, block: bool = True, timeout: float | None = None):
            queue_timeouts.append(timeout)
            return super().get(block=block, timeout=timeout)

    monkeypatch.setattr(commands_module.queue, "Queue", ObservedQueue)
    broker = CommandBroker({"commands": {"enabled": True}})
    result = broker._execute(
        "short-log-command",
        str(tmp_path),
        3,
        log_callback=lambda _stream, _text: None,
        argv_override=[sys.executable, "-B", "-c", "print('done')"],
    )

    assert result["success"] is True
    assert result["log_dispatch_incomplete"] is False
    assert queue_timeouts
    assert all(timeout is None for timeout in queue_timeouts)


def test_slow_log_consumer_does_not_block_child_pipes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(commands_module, "_COMMAND_LOG_QUEUE_MAX_CHUNKS", 1)
    broker = CommandBroker(
        {"commands": {"enabled": True, "max_output_chars": 512 * 1024}}
    )
    callback_started = threading.Event()

    def slow_consumer(_stream: str, _text: str) -> None:
        if not callback_started.is_set():
            callback_started.set()
            time.sleep(4.0)

    child = (
        "import sys; "
        "chunk=b'x'*1023+b'\\n'; "
        "[(sys.stdout.buffer.write(chunk), sys.stderr.buffer.write(chunk)) "
        "for _ in range(12000)]; "
        "sys.stdout.flush(); sys.stderr.flush()"
    )
    started = time.perf_counter()
    result = broker._execute(
        "slow-stream-child",
        str(tmp_path),
        3,
        log_callback=slow_consumer,
        argv_override=[sys.executable, "-B", "-c", child],
    )
    elapsed = time.perf_counter() - started

    assert callback_started.is_set()
    assert result["success"] is True
    assert result["timed_out"] is False
    assert len(result["stdout"]) > 0
    assert len(result["stderr"]) > 0
    assert result["log_chunks_dropped"] > 0
    assert elapsed < 6.0


def test_timeout_reaps_command_descendants(tmp_path: Path) -> None:
    broker = CommandBroker({"commands": {"enabled": True}})
    child_pid_file = tmp_path / "child.pid"
    parent = (
        "import pathlib, subprocess, sys, time; "
        "child=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(60)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid),encoding='ascii'); "
        "time.sleep(60)"
    )
    result = broker._execute(
        "timeout-parent",
        str(tmp_path),
        1,
        argv_override=[sys.executable, "-B", "-c", parent, str(child_pid_file)],
    )

    assert result["timed_out"] is True
    assert child_pid_file.exists()
    child_pid = int(child_pid_file.read_text(encoding="ascii"))
    deadline = time.monotonic() + 3.0
    while commands_module.process_identity(child_pid) is not None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert commands_module.process_identity(child_pid) is None


def test_cancel_reaps_command_descendants(tmp_path: Path) -> None:
    broker = CommandBroker({"commands": {"enabled": True}})
    child_pid_file = tmp_path / "cancel-child.pid"
    parent = (
        "import pathlib, subprocess, sys, time; "
        "child=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(60)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid),encoding='ascii'); "
        "time.sleep(60)"
    )
    cancel_event = threading.Event()
    result: dict[str, object] = {}

    def run_child() -> None:
        result.update(
            broker._execute(
                "cancel-parent",
                str(tmp_path),
                10,
                cancel_event=cancel_event,
                argv_override=[sys.executable, "-B", "-c", parent, str(child_pid_file)],
            )
        )

    worker = threading.Thread(target=run_child)
    worker.start()
    try:
        deadline = time.monotonic() + 5.0
        while (not child_pid_file.exists() or not child_pid_file.stat().st_size) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child_pid_file.exists() and child_pid_file.stat().st_size
        child_pid = int(child_pid_file.read_text(encoding="ascii"))
    finally:
        cancel_event.set()
        worker.join(timeout=15.0)

    assert worker.is_alive() is False
    assert result.get("cancelled") is True
    deadline = time.monotonic() + 3.0
    while commands_module.process_identity(child_pid) is not None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert commands_module.process_identity(child_pid) is None


def test_prompt_hang_is_aborted_and_reaped(tmp_path: Path) -> None:
    broker = CommandBroker({"commands": {"enabled": True}})
    pid_file = tmp_path / "prompt.pid"
    child = (
        "import os,pathlib,sys,time; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()),encoding='ascii'); "
        "sys.stdout.write('Enter password: '); sys.stdout.flush(); time.sleep(60)"
    )
    result = broker._execute(
        "prompt-child",
        str(tmp_path),
        5,
        argv_override=[sys.executable, "-B", "-c", child, str(pid_file)],
    )

    assert result["aborted_interactive"] is True
    assert pid_file.exists()
    pid = int(pid_file.read_text(encoding="ascii"))
    deadline = time.monotonic() + 3.0
    while commands_module.process_identity(pid) is not None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert commands_module.process_identity(pid) is None


def test_python_preflight_does_not_write_bytecode(tmp_path: Path) -> None:
    source = tmp_path / "probe.py"
    source.write_text("value = 1\n", encoding="utf-8")
    broker = CommandBroker({"commands": {"enabled": True}})

    result = broker.preflight(str(tmp_path), paths=["probe.py"])

    assert result["success"] is True
    assert result["clean"] is True
    assert list(tmp_path.rglob("__pycache__")) == []


def test_python_preflight_still_reports_syntax_errors(tmp_path: Path) -> None:
    (tmp_path / "invalid.py").write_text("def broken(:\n", encoding="utf-8")
    broker = CommandBroker({"commands": {"enabled": True}})

    result = broker.preflight(str(tmp_path), paths=["invalid.py"])

    assert result["success"] is True
    assert result["clean"] is False
    assert result["errors"][0]["level"] == "syntax_error"
    assert result["errors"][0]["line"] == 1
    assert list(tmp_path.rglob("__pycache__")) == []


def test_mock_server_port_collision_does_not_claim_running(tmp_path: Path) -> None:
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]

        started = broker.mock_server_start(root=str(tmp_path), port=port)
        status = broker.mock_server_status(port)

    assert started["success"] is False
    assert started["port"] == port
    assert status["running"] is False


def test_daemon_registry_recovers_live_group_after_leader_exit(tmp_path: Path) -> None:
    if sys.platform != "linux":
        import pytest

        pytest.skip("Linux /proc process identity required")

    state_dir = tmp_path / "state"
    broker = CommandBroker({"server": {"state_dir": str(state_dir)}})
    daemon_id = "dmn_" + "a" * 32
    child_pid_file = tmp_path / "child.pid"
    child = (
        "import os,pathlib,sys,time; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()),encoding='ascii'); "
        "time.sleep(60)"
    )
    leader_code = (
        "import subprocess,sys; "
        "subprocess.Popen([sys.executable,'-B','-c',sys.argv[1],sys.argv[2]], "
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
    )
    leader = subprocess.Popen(
        [sys.executable, "-B", "-c", leader_code, child, str(child_pid_file)],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    process_group_id = leader.pid
    identity = commands_module.process_identity(leader.pid)
    assert identity is not None
    try:
        leader.wait(timeout=5)
        deadline = time.monotonic() + 3
        while not child_pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child_pid_file.exists()
        child_pid = int(child_pid_file.read_text(encoding="ascii"))
        assert commands_module.process_identity(leader.pid) is None

        daemon_dir = state_dir / "daemons"
        daemon_dir.mkdir(parents=True, exist_ok=True)
        log_path = daemon_dir / f"{daemon_id}.log"
        log_path.write_bytes(b"")
        row = {
            "daemon_id": daemon_id,
            "pid": leader.pid,
            "process_group_id": process_group_id,
            "identity": identity,
            "owner_id": broker._daemon_owner_id,
            "name": "orphaned leader test",
            "command": "test-daemon",
            "started_at": time.time() - 1,
            "expires_at": time.time() + 30,
        }
        broker._daemon_registry_path.write_text(
            json.dumps({"version": 3, "daemons": [row]}), encoding="utf-8"
        )

        recovered = CommandBroker({"server": {"state_dir": str(state_dir)}})
        status = recovered.daemon_status(daemon_id)
        assert status["alive"] is True
        assert recovered.stop_daemon(daemon_id)["success"] is True
        deadline = time.monotonic() + 3
        while commands_module.process_identity(child_pid) is not None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert commands_module.process_identity(child_pid) is None
    finally:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_recovered_daemon_accepts_dead_leader_only_for_verified_group(monkeypatch) -> None:
    pid = 12345
    identity = {"pid": pid, "created": 1.0}
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(commands_module, "_process_group_alive", lambda group_id: group_id == pid, raising=False)
    monkeypatch.setattr(commands_module, "_process_group_leader_gone", lambda _pid: True, raising=False)

    process = commands_module._RecoveredDaemonProcess(
        pid, identity, process_group_id=pid
    )

    assert process.poll() is None


def test_recovered_daemon_rejects_reused_leader_pid(monkeypatch) -> None:
    pid = 12345
    identity = {"pid": pid, "created": 1.0}
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: {"pid": pid, "created": 2.0})
    monkeypatch.setattr(commands_module, "_process_group_alive", lambda _group_id: True, raising=False)

    process = commands_module._RecoveredDaemonProcess(
        pid, identity, process_group_id=pid
    )

    assert process.poll() == 0


def test_process_group_permission_denied_is_not_verified(monkeypatch) -> None:
    if os.name == "nt":
        import pytest

        pytest.skip("POSIX process groups only")

    def deny_signal(_process_group_id: int, _signal_number: int) -> None:
        raise PermissionError("process group is not manageable by this owner")

    monkeypatch.setattr(commands_module.os, "killpg", deny_signal)

    assert commands_module._process_group_alive(12345) is False


def test_daemon_registry_rejects_unverifiable_leader_with_live_group(
    tmp_path: Path, monkeypatch
) -> None:
    if os.name == "nt":
        import pytest

        pytest.skip("POSIX process groups only")

    state_dir = tmp_path / "state"
    broker = CommandBroker({"server": {"state_dir": str(state_dir)}})
    daemon_id = "dmn_" + "b" * 32
    pid = 12345
    identity = {"pid": pid, "created": 1.0}
    daemon_dir = state_dir / "daemons"
    daemon_dir.mkdir(parents=True, exist_ok=True)
    (daemon_dir / f"{daemon_id}.log").write_bytes(b"")
    row = {
        "daemon_id": daemon_id,
        "pid": pid,
        "process_group_id": pid,
        "identity": identity,
        "owner_id": broker._daemon_owner_id,
        "name": "unverifiable leader test",
        "command": "test-daemon",
        "started_at": time.time() - 1,
        "expires_at": time.time() + 30,
    }
    broker._daemon_registry_path.write_text(
        json.dumps({"version": 3, "daemons": [row]}), encoding="utf-8"
    )
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(
        commands_module, "_process_group_alive", lambda group_id: group_id == pid
    )
    monkeypatch.setattr(
        commands_module,
        "_process_group_leader_gone",
        lambda _pid: False,
        raising=False,
    )

    recovered = CommandBroker({"server": {"state_dir": str(state_dir)}})

    assert daemon_id not in recovered._daemons
