from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

from local_ai_hub import commands as commands_module
from local_ai_hub.commands import CommandBroker


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
        worker.join(timeout=6.0)

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
