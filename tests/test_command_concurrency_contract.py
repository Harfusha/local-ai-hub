from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import pytest

import local_ai_hub.commands as commands_module
import local_ai_hub.process_utils as process_utils_module
from local_ai_hub.commands import CommandBroker, CommandInvocation
from local_ai_hub.process_utils import pid_alive


class _Artifacts:
    def put(self, *_args, **_kwargs):
        return "artifact"


class _RevisionState:
    def __init__(self) -> None:
        self.revision = "revision-a"

    def fingerprint(self, _cwd):
        return {"fingerprint": self.revision}


def _broker(
    tmp_path,
    repo_state=None,
    *,
    max_output_chars: int = 4096,
    allow_mutating: bool = False,
) -> CommandBroker:
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {
                "enabled": True,
                "coalesced_wait_seconds": 2,
                "max_output_chars": max_output_chars,
                "allow_mutating": allow_mutating,
            },
        },
        _Artifacts(),
        repo_state or _RevisionState(),
    )
    broker._require_task_worktree = lambda *args, **kwargs: None
    broker._transaction_docker_ready = lambda: (True, "")
    broker._transaction_root_for_context = lambda _tid: Path(tmp_path)
    broker._transaction_source_for_context = lambda _tid: Path(tmp_path)
    broker._assert_work_attempt_fence = lambda *args, **kwargs: None

    def mock_run_private_transaction(*args, **kwargs):
        op = kwargs.get("operation")
        root = args[1] if len(args) > 1 else kwargs.get("source_root", tmp_path)
        with broker._transaction_roots_lock:
            broker._active_transaction_roots["test-tx"] = Path(root)
            broker._active_transaction_sources["test-tx"] = Path(root)
        if op:
            return op(root, "test-tx")
        cmd = args[0] if args else kwargs.get("command", "")
        return broker._execute(cmd, root, 30)

    broker._run_private_transaction = mock_run_private_transaction

    if allow_mutating:
        (tmp_path / "changed.py").write_text("x\n", encoding="utf-8")
        from local_ai_hub.work_fencing import WorkAttemptFence
        dummy_fence = WorkAttemptFence(
            resource=str(Path(tmp_path).resolve()),
            work_id="test",
            attempt_id="test",
            owner_id="test",
            fencing_token=1,
            expires_at=time.time() + 3600,
        )
        orig_run = broker.run

        def mutating_run(command, cwd, *args, **kwargs):
            if "paths" not in kwargs or kwargs["paths"] is None:
                kwargs["paths"] = ["changed.py"]
            if "_work_attempt_fence" not in kwargs or kwargs["_work_attempt_fence"] is None:
                kwargs["_work_attempt_fence"] = dummy_fence
                kwargs.setdefault("task_id", "test")
            return orig_run(command, cwd, *args, **kwargs)

        broker.run = mutating_run

    return broker


def _execution_result(stdout: str) -> dict:
    return {
        "success": True,
        "exit_code": 0,
        "stdout": stdout,
        "stderr": "",
        "duration_ms": 1,
        "timed_out": False,
        "cancelled": False,
        "aborted_interactive": False,
    }


def test_repeatable_command_cache_is_scoped_by_timeout(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    command = "python -m pytest -q"
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)
    executions: list[int] = []

    def execute(_command, _cwd, timeout, *_args, **_kwargs):
        executions.append(timeout)
        if timeout == 1:
            return {
                "success": False,
                "exit_code": -9,
                "stdout": "short timeout",
                "stderr": "timed out",
                "duration_ms": 1,
                "timed_out": True,
                "cancelled": False,
            }
        return _execution_result(f"run-{len(executions)}")

    monkeypatch.setattr(broker, "_execute", execute)

    first = broker.run(command, str(tmp_path), timeout=4)
    cached = broker.run(command, str(tmp_path), timeout=4)
    short = broker.run(command, str(tmp_path), timeout=1)
    long = broker.run(command, str(tmp_path), timeout=10)

    assert executions == [4, 1, 10]
    assert first["cache_hit"] is False
    assert cached["cache_hit"] is True
    assert cached["stdout"] == "run-1"
    assert short["success"] is False
    assert long["success"] is True
    assert long["cache_hit"] is False
    assert long["stdout"] == "run-3"


def test_overlapping_repeatable_calls_execute_once_and_return_same_result(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    command = "python -m pytest -q"
    assert broker.classify(command)["cacheable"] is True

    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)
    execution_started = threading.Event()
    release_execution = threading.Event()
    second_waiting_on_inflight = threading.Event()
    executions: list[str] = []
    results: dict[str, dict] = {}
    errors: list[BaseException] = []

    def execute(command, _cwd, _timeout, cancel_event=None, log_callback=None):
        executions.append(command)
        execution_started.set()
        assert release_execution.wait(3), "test did not release command execution"
        return _execution_result("same-result\n")

    monkeypatch.setattr(broker, "_execute", execute)

    def run(caller: str) -> None:
        try:
            results[caller] = broker.run(command, str(tmp_path))
        except BaseException as exc:  # surface worker failures in the test thread
            errors.append(exc)

    first = threading.Thread(target=run, args=("first",), name="first-caller", daemon=True)
    second = threading.Thread(target=run, args=("second",), name="second-caller", daemon=True)
    first.start()
    try:
        assert execution_started.wait(2)
        inflight = list(broker._inflight.items())
        assert len(inflight) == 1
        key, completion_event = inflight[0]
        assert broker._inflight[key] is completion_event

        class _ObservedWaiters(deque):
            def append(self, waiter):
                super().append(waiter)
                if threading.current_thread().name == "second-caller":
                    second_waiting_on_inflight.set()

        # Event.wait registers here before it releases the condition lock.
        completion_event._cond._waiters = _ObservedWaiters(completion_event._cond._waiters)
        second.start()
        assert second_waiting_on_inflight.wait(2)
        assert not release_execution.is_set()
    finally:
        release_execution.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert len(executions) == 1
    assert len(results) == 2
    assert results["first"]["success"] is True
    assert results["second"]["success"] is True
    assert results["first"]["coalesced"] is False
    assert results["first"]["cache_hit"] is False
    assert results["second"]["coalesced"] is True
    assert results["second"]["cache_hit"] is False
    assert (results["first"]["exit_code"], results["first"]["stdout"], results["first"]["stderr"]) == (
        results["second"]["exit_code"],
        results["second"]["stdout"],
        results["second"]["stderr"],
    ) == (0, "same-result\n", "")
    assert broker.stats()["active_count"] == 0


def test_inflight_waiter_is_not_reported_as_cache_hit(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    command = "python -m pytest -q"
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)
    execution_started = threading.Event()
    release_execution = threading.Event()
    waiter_registered = threading.Event()
    results: dict[str, dict] = {}
    errors: list[BaseException] = []

    def execute(_command, _cwd, _timeout, cancel_event=None, log_callback=None):
        execution_started.set()
        assert release_execution.wait(3), "test did not release command execution"
        return _execution_result("in-flight-result\n")

    monkeypatch.setattr(broker, "_execute", execute)

    def run(caller: str) -> None:
        try:
            results[caller] = broker.run(command, str(tmp_path))
        except BaseException as exc:  # surface worker failures in the test thread
            errors.append(exc)

    producer = threading.Thread(target=run, args=("producer",), name="cache-flag-producer", daemon=True)
    waiter = threading.Thread(target=run, args=("waiter",), name="cache-flag-waiter", daemon=True)
    producer.start()
    try:
        assert execution_started.wait(2)
        completion_event = next(iter(broker._inflight.values()))

        class _ObservedWaiters(deque):
            def append(self, waiter_condition):
                super().append(waiter_condition)
                if threading.current_thread().name == "cache-flag-waiter":
                    waiter_registered.set()

        completion_event._cond._waiters = _ObservedWaiters(completion_event._cond._waiters)
        waiter.start()
        assert waiter_registered.wait(2)
    finally:
        release_execution.set()
        producer.join(5)
        if waiter.ident is not None:
            waiter.join(5)

    assert not producer.is_alive()
    assert not waiter.is_alive()
    assert errors == []
    assert set(results) == {"producer", "waiter"}
    assert results["producer"]["cache_hit"] is False
    assert results["producer"]["coalesced"] is False
    assert results["waiter"]["cache_hit"] is False
    assert results["waiter"]["coalesced"] is True
    assert results["waiter"]["stdout"] == results["producer"]["stdout"] == "in-flight-result\n"


def test_repository_revision_change_during_flight_uses_distinct_execution(tmp_path, monkeypatch) -> None:
    repo_state = _RevisionState()
    broker = _broker(tmp_path, repo_state)
    command = "python -m pytest -q"
    assert broker.classify(command)["cacheable"] is True
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)
    executions: list[str] = []
    started = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]
    results: dict[str, dict] = {}
    errors: list[BaseException] = []
    call_lock = threading.Lock()

    def execute(_command, _cwd, _timeout, cancel_event=None, log_callback=None):
        with call_lock:
            index = len(executions)
            revision = repo_state.revision
            executions.append(revision)
        started[index].set()
        assert release[index].wait(3), "test did not release command execution"
        return _execution_result(f"{revision}\n")

    monkeypatch.setattr(broker, "_execute", execute)

    def run(caller: str) -> None:
        try:
            results[caller] = broker.run(command, str(tmp_path))
        except BaseException as exc:  # surface worker failures in the test thread
            errors.append(exc)

    first = threading.Thread(target=run, args=("first",), name="revision-a-caller", daemon=True)
    second = threading.Thread(target=run, args=("second",), name="revision-b-caller", daemon=True)
    first.start()
    try:
        assert started[0].wait(2)
        repo_state.revision = "revision-b"
        second.start()
        assert started[1].wait(2), "changed revision joined the old in-flight command"
    finally:
        for event in release:
            event.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert executions == ["revision-a", "revision-b"]
    assert results["first"]["cache_hit"] is False
    assert results["second"]["cache_hit"] is False
    assert results["second"].get("coalesced") is not True
    assert results["first"]["stdout"] == "revision-a\n"
    assert results["second"]["stdout"] == "revision-b\n"


def test_mutating_call_bypasses_existing_singleflight_entry(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path, allow_mutating=True)
    command = "git add changed.py"
    assert broker.classify(command)["class"] == "mutating"
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)
    started = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]
    executions: list[str] = []
    results: dict[str, dict] = {}
    errors: list[BaseException] = []
    call_lock = threading.Lock()

    def execute(command, _cwd, _timeout, cancel_event=None, log_callback=None):
        with call_lock:
            index = len(executions)
            executions.append(command)
        started[index].set()
        assert release[index].wait(3), "test did not release command execution"
        return _execution_result(f"execution-{index}\n")

    monkeypatch.setattr(broker, "_execute", execute)

    def run(caller: str) -> None:
        try:
            results[caller] = broker.run(command, str(tmp_path))
        except BaseException as exc:  # surface worker failures in the test thread
            errors.append(exc)

    first = threading.Thread(target=run, args=("first",), name="mutating-first", daemon=True)
    second = threading.Thread(target=run, args=("second",), name="mutating-second", daemon=True)
    first.start()
    try:
        assert started[0].wait(2)
        second.start()
        assert started[1].wait(2), "mutating call joined an existing single-flight entry"
    finally:
        for event in release:
            event.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert executions == [command, command]
    assert results["first"]["success"] is True
    assert results["second"]["success"] is True
    assert results["first"]["coalesced"] is False
    assert results["second"]["coalesced"] is False
    assert results["first"]["stdout"] != results["second"]["stdout"]


def test_timeout_drain_escalates_group_before_rejoining_pipe_readers(monkeypatch) -> None:
    events: list[tuple[str, object]] = []

    class Pipe:
        def close(self) -> None:
            events.append(("close", self))

    class StuckProcess:
        pid = 24569

        def __init__(self) -> None:
            self.stdout = Pipe()
            self.stderr = Pipe()
            self.communicate_calls = 0

        def poll(self) -> int | None:
            return None

        def kill(self) -> None:
            events.append(("kill_leader", self.pid))

        def wait(self, timeout: float) -> int:
            events.append(("wait", timeout))
            return 0

        def communicate(self, timeout: float) -> tuple[bytes, bytes]:
            self.communicate_calls += 1
            events.append((f"communicate_{self.communicate_calls}", timeout))
            if self.communicate_calls == 1:
                raise subprocess.TimeoutExpired(
                    "fake command", timeout, output=b"partial", stderr=b"partial-error"
                )
            return b"drained", b"drained-error"

    process = StuckProcess()
    cleanup_calls = 0

    def terminate_tree(pid: int, **kwargs) -> bool:
        nonlocal cleanup_calls
        cleanup_calls += 1
        events.append((f"terminate_group_{cleanup_calls}", (pid, kwargs)))
        return cleanup_calls > 1

    monkeypatch.setattr(process_utils_module, "terminate_tree", terminate_tree)

    output = process_utils_module._terminate_and_drain(process, process_group=process.pid)

    assert (output.stdout, output.stderr) == (b"drained", b"drained-error")
    assert output.cleanup_confirmed is True
    event_names = [name for name, _value in events]
    assert event_names.index("terminate_group_2") < event_names.index("communicate_2")
    assert "close" not in event_names


def test_stdout_and_stderr_flood_are_drained_without_blocking(tmp_path) -> None:
    broker = _broker(tmp_path, max_output_chars=2048)
    script = (
        "import sys; out_chunk = 'o' * 8192; err_chunk = 'e' * 8192; "
        "[(sys.stdout.write(out_chunk), sys.stdout.flush(), "
        "sys.stderr.write(err_chunk), sys.stderr.flush()) for _ in range(32)]; "
        "sys.stdout.write('OUT_TAIL_SENTINEL'); sys.stdout.flush(); "
        "sys.stderr.write('ERR_TAIL_SENTINEL'); sys.stderr.flush()"
    )
    command = f'"{sys.executable}" -c "{script}"'
    completed = threading.Event()
    result_holder: dict[str, dict] = {}
    errors: list[BaseException] = []

    def run() -> None:
        try:
            result_holder["result"] = broker.run(command, str(tmp_path), timeout=8)
        except BaseException as exc:  # surface worker failures in the test thread
            errors.append(exc)
        finally:
            completed.set()

    worker = threading.Thread(target=run, name="command-pipe-flood", daemon=True)
    worker.start()
    finished_within_bound = completed.wait(12)
    cancel_returned_within_bound = True
    cancel_errors: list[BaseException] = []

    def cancel() -> None:
        try:
            broker.cancel(command, str(tmp_path))
        except BaseException as exc:  # surface cleanup failures in the test thread
            cancel_errors.append(exc)
        finally:
            cancel_completed.set()

    cancel_completed = threading.Event()
    try:
        if not finished_within_bound:
            cancel_worker = threading.Thread(
                target=cancel,
                name="command-pipe-flood-cancel",
                daemon=True,
            )
            cancel_worker.start()
            cancel_returned_within_bound = cancel_completed.wait(1)
    finally:
        worker.join(3)

    assert cancel_returned_within_bound, "broker cancellation did not return within cleanup bound"
    assert cancel_errors == []
    assert finished_within_bound, "command broker did not finish within outer deadline"
    assert not worker.is_alive(), "command worker remained blocked after completion/cancel"
    assert errors == []
    result = result_holder["result"]
    assert result["success"] is True
    assert result["timed_out"] is not True
    assert len(result["stdout"]) == 2048  # configured per-stream tail cap
    assert len(result["stderr"]) == 2048
    assert result["stdout"].endswith("OUT_TAIL_SENTINEL")
    assert result["stderr"].endswith("ERR_TAIL_SENTINEL")
    assert result["discarded_output_chars"] >= 500_000
    assert "ERR_TAIL_SENTINEL" not in result["stdout"]
    assert "OUT_TAIL_SENTINEL" not in result["stderr"]


def test_interactive_prompt_hang_aborts_and_reaps_command(tmp_path) -> None:
    broker = _broker(tmp_path)
    script_path = tmp_path / "interactive_prompt_hang.py"
    script_path.write_text(
        "import os, time\n"
        "print(f'COMMAND_PID={os.getpid()}', flush=True)\n"
        "print('Enter password:', flush=True)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    started = time.monotonic()

    # Exercise process cleanup, not authorization of an arbitrary fixture script.
    result = broker._execute(
        f'"{sys.executable}" "{script_path}"',
        str(tmp_path),
        timeout=8,
    )
    elapsed = time.monotonic() - started

    pid_line = next(line for line in result["stdout"].splitlines() if line.startswith("COMMAND_PID="))
    command_pid = int(pid_line.split("=", 1)[1])
    assert result["success"] is False
    assert result["aborted_interactive"] is True
    assert result["cleanup_unconfirmed"] is False
    assert elapsed < 6
    assert not pid_alive(command_pid)


def test_pipe_reader_start_failure_kills_and_reaps_command(tmp_path, monkeypatch) -> None:
    import local_ai_hub.commands as commands_module

    broker = _broker(tmp_path)
    pid_path = tmp_path / "reader-start-child.pid"
    script_path = tmp_path / "reader_start_child.py"
    script_path.write_text(
        "import os, pathlib, time\n"
        f"pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))\n"
        "print('child-started', flush=True)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    real_start = commands_module.threading.Thread.start
    reader_start_count = 0

    def fail_reader_start(thread, *args, **kwargs):
        nonlocal reader_start_count
        if getattr(getattr(thread, "_target", None), "__name__", "") == "_reader":
            reader_start_count += 1
            if reader_start_count == 1:
                return real_start(thread, *args, **kwargs)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not pid_path.exists():
                time.sleep(0.01)
            assert pid_path.exists(), "child did not start before pipe reader failure injection"
            raise RuntimeError("injected reader thread startup failure")
        return real_start(thread, *args, **kwargs)

    monkeypatch.setattr(commands_module.threading.Thread, "start", fail_reader_start)

    result = broker._execute(f'"{sys.executable}" "{script_path}"', str(tmp_path), timeout=8)

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not pid_path.exists():
        time.sleep(0.02)
    assert reader_start_count == 2
    assert result["success"] is False
    assert result["cleanup_unconfirmed"] is False
    assert "reader" in result["error"].lower()
    assert pid_path.exists()
    assert not pid_alive(int(pid_path.read_text(encoding="utf-8")))


def test_pipe_read_error_fails_closed_and_is_not_cached(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    command = "python -m pytest -q"
    assert broker.classify(command)["cacheable"] is True
    script_path = tmp_path / "reader_error_at_eof.py"
    script_path.write_text(
        "print('PIPE_BEFORE_ERROR', flush=True)\n"
        "print('PIPE_AFTER_ERROR', flush=True)\n",
        encoding="utf-8",
    )
    real_popen = commands_module.subprocess.Popen
    spawned_pids: list[int] = []

    class ReadErrorAtEof:
        def __init__(self, stream):
            self._stream = stream
            self._raised = False

        def readline(self, size=-1):
            line = self._stream.readline(size)
            if line or self._raised:
                return line
            self._raised = True
            raise OSError("injected stdout pipe read failure")

        @property
        def closed(self):
            return self._stream.closed

        def close(self):
            self._stream.close()

    def popen_with_stdout_read_error(*_args, **kwargs):
        process = real_popen([sys.executable, str(script_path)], **kwargs)
        spawned_pids.append(process.pid)
        if process.stdout is not None:
            process.stdout = ReadErrorAtEof(process.stdout)
        return process

    monkeypatch.setattr(commands_module.subprocess, "Popen", popen_with_stdout_read_error)
    result = broker.run(command, str(tmp_path), timeout=8)

    assert result["success"] is False
    assert result["output_capture_unconfirmed"] is True
    assert "PIPE_BEFORE_ERROR" in result["stdout"]
    assert "PIPE_AFTER_ERROR" in result["stdout"]
    assert "stdout" in result["error"].lower()
    assert result["cleanup_unconfirmed"] is False

    retry = broker.run(command, str(tmp_path), timeout=8)
    assert retry["cache_hit"] is False
    assert len(spawned_pids) == 2


@pytest.mark.parametrize("uncertainty_field", ["cleanup_unconfirmed", "log_callback_delivery_unconfirmed"])
def test_uncertain_command_results_are_not_cached(tmp_path, monkeypatch, uncertainty_field) -> None:
    broker = _broker(tmp_path)
    command = "python -m pytest -q"
    assert broker.classify(command)["cacheable"] is True
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)
    executions: list[int] = []

    def execute(_command, _cwd, _timeout, *_args, **_kwargs):
        executions.append(len(executions) + 1)
        result = _execution_result(f"run-{len(executions)}\n")
        if len(executions) == 1:
            result[uncertainty_field] = True
            if uncertainty_field == "cleanup_unconfirmed":
                result["success"] = False
                result["exit_code"] = -9
        return result

    monkeypatch.setattr(broker, "_execute", execute)
    first = broker.run(command, str(tmp_path), timeout=4)
    second = broker.run(command, str(tmp_path), timeout=4)

    assert first["cache_hit"] is False
    assert second["cache_hit"] is False
    assert executions == [1, 2]
    assert second["stdout"] == "run-2\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object startup failure path")
def test_spawn_setup_failure_reports_unconfirmed_cleanup(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)
    monkeypatch.setattr(commands_module, "create_job_object_kill_on_close", lambda: object())
    monkeypatch.setattr(commands_module, "assign_process_to_job", lambda *_args: False)
    monkeypatch.setattr(commands_module, "_terminate_and_confirm_windows_job_empty", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(commands_module, "close_job_object", lambda *_args: False)

    class UnreapedProcess:
        pid = 4242
        returncode = None

        def kill(self):
            raise OSError("injected process kill failure")

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("fake command", timeout)

        def poll(self):
            return None

    monkeypatch.setattr(commands_module.subprocess, "Popen", lambda *_args, **_kwargs: UnreapedProcess())
    result = broker.run("python -m pytest -q", str(tmp_path), timeout=4)

    assert result["success"] is False
    assert result["cleanup_unconfirmed"] is True
    assert "failed to spawn process" in result["error"]


def test_slow_log_callback_does_not_block_command_pipe_drain(tmp_path) -> None:
    broker = _broker(tmp_path, max_output_chars=4096)
    broker.inline_chars = 100_000
    script_path = tmp_path / "slow_callback_flood.py"
    script_path.write_text(
        "import sys\n"
        "for index in range(1500):\n"
        " print('out-' + str(index))\n"
        " print('err-' + str(index), file=sys.stderr)\n"
        "print('OUT_SLOW_CALLBACK_TAIL', flush=True)\n"
        "print('ERR_SLOW_CALLBACK_TAIL', file=sys.stderr, flush=True)\n",
        encoding="utf-8",
    )
    callback_started = threading.Event()
    callback_release = threading.Event()

    def slow_callback(_stream: str, _text: str) -> None:
        callback_started.set()
        callback_release.wait(5)

    started = time.monotonic()
    try:
        result = broker._execute(
            f'"{sys.executable}" "{script_path}"',
            str(tmp_path),
            timeout=8,
            log_callback=slow_callback,
        )
        elapsed = time.monotonic() - started

        assert callback_started.wait(1)
        assert elapsed < 5, "slow log consumer blocked command stream drainage"
        assert result["success"] is True
        assert result["stdout"].endswith("OUT_SLOW_CALLBACK_TAIL\n")
        assert result["stderr"].endswith("ERR_SLOW_CALLBACK_TAIL\n")
        assert result.get("log_callback_dropped_chars", 0) > 0
    finally:
        callback_release.set()


def test_log_callback_delivery_respects_line_rate_cap(tmp_path) -> None:
    broker = _broker(tmp_path, max_output_chars=100_000)
    broker.inline_chars = 100_000
    script_path = tmp_path / "callback_rate_flood.py"
    script_path.write_text(
        "for index in range(4000):\n"
        " print('line-' + str(index))\n",
        encoding="utf-8",
    )
    callback_times: list[float] = []
    started = time.monotonic()
    result = broker._execute(
        f'"{sys.executable}" "{script_path}"',
        str(tmp_path),
        timeout=8,
        log_callback=lambda _stream, _text: callback_times.append(time.monotonic()),
    )
    elapsed = time.monotonic() - started

    assert result["success"] is True
    assert result["stdout"].endswith("line-3999\n")
    assert len(callback_times) > 1
    assert len(callback_times) <= int(elapsed / 0.005) + 3


def test_preflight_does_not_write_bytecode_and_reports_syntax_errors(tmp_path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    broker = _broker(tmp_path)

    valid = broker.preflight(tmp_path, paths=[source.name])

    assert valid["clean"] is True
    assert valid["checker"] == "py_compile"
    assert not (tmp_path / "__pycache__").exists()

    source.write_text("def broken(:\n    pass\n", encoding="utf-8")
    invalid = broker.preflight(tmp_path, paths=[source.name])

    assert invalid["clean"] is False
    assert invalid["errors_count"] == 1
    assert invalid["errors"][0]["file"] == source.name
    assert invalid["errors"][0]["line"] == 1
    assert invalid["errors"][0]["level"] == "syntax_error"
    assert invalid["errors"][0]["message"]
    assert not (tmp_path / "__pycache__").exists()

    source.write_bytes(b"# coding: ascii\n# \xff\n")
    invalid_encoding = broker.preflight(tmp_path, paths=[source.name])

    assert invalid_encoding["clean"] is False
    assert invalid_encoding["errors_count"] == 1
    assert invalid_encoding["errors"][0]["file"] == source.name
    assert invalid_encoding["errors"][0]["message"]
    assert not (tmp_path / "__pycache__").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cleanup contract")
def test_finished_leader_does_not_leave_descendant_holding_command_pipes(tmp_path) -> None:
    broker = _broker(tmp_path)
    script_path = tmp_path / "spawn_pipe_holder.py"
    script_path.write_text(
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(12)'])\n"
        "print(child.pid, flush=True)\n",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" "{script_path}"'
    child_pid: int | None = None

    try:
        result = broker.run(command, str(tmp_path), timeout=8)
        child_pid = int(result["stdout"].strip().splitlines()[-1])

        assert result["exit_code"] == 0
        assert result["success"] is True
        assert result["cleanup_unconfirmed"] is False
        assert result["duration_ms"] < 10_000
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if not pid_alive(child_pid):
                break
            time.sleep(0.05)
        else:
            pytest.fail("descendant remained alive after command leader exited")
    finally:
        if child_pid is not None and pid_alive(child_pid):
            try:
                os.kill(child_pid, signal.SIGTERM)
            except OSError:
                pass


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cleanup contract")
def test_finished_leader_kills_descendant_that_closed_command_pipes(tmp_path) -> None:
    broker = _broker(tmp_path)
    script_path = tmp_path / "spawn_detached_pipe_child.py"
    script_path.write_text(
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(12)'], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "print(child.pid, flush=True)\n",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" "{script_path}"'
    child_pid: int | None = None

    try:
        result = broker.run(command, str(tmp_path), timeout=8)
        child_pid = int(result["stdout"].strip().splitlines()[-1])

        assert result["exit_code"] == 0
        assert result["success"] is True
        assert result["cleanup_unconfirmed"] is False
        assert result["duration_ms"] < 10_000
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and pid_alive(child_pid):
            time.sleep(0.05)
        assert not pid_alive(child_pid), "descendant survived after closing command pipes"
    finally:
        if child_pid is not None and pid_alive(child_pid):
            try:
                os.kill(child_pid, signal.SIGTERM)
            except OSError:
                pass


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object ownership contract")
def test_windows_job_closes_descendants_after_command_leader_exits(tmp_path) -> None:
    broker = _broker(tmp_path)
    script_path = tmp_path / "spawn_job_child.py"
    script_path.write_text(
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(12)'])\n"
        "print(child.pid, flush=True)\n",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" "{script_path}"'
    child_pid: int | None = None

    try:
        result = broker._execute(command, str(tmp_path), timeout=8)
        child_pid = int(result["stdout"].strip().splitlines()[-1])

        assert result["success"] is True
        assert result["cleanup_unconfirmed"] is False
        assert result["duration_ms"] < 4_000
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and pid_alive(child_pid):
            time.sleep(0.05)
        assert not pid_alive(child_pid), "descendant survived its command Job Object"
    finally:
        if child_pid is not None and pid_alive(child_pid):
            try:
                os.kill(child_pid, signal.SIGTERM)
            except OSError:
                pass


def test_repeatable_cache_reuses_results_and_tracks_repository_revision(tmp_path, monkeypatch) -> None:
    repo_state = _RevisionState()
    broker = _broker(tmp_path, repo_state)
    command = "python -m pytest -q"
    executions: list[str] = []
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)

    def execute(_command, _cwd, _timeout, cancel_event=None, log_callback=None):
        executions.append(repo_state.revision)
        return _execution_result(f"{repo_state.revision}\n")

    monkeypatch.setattr(broker, "_execute", execute)

    first = broker.run(command, str(tmp_path))
    repeated = broker.run(command, str(tmp_path))
    repo_state.revision = "revision-b"
    revised = broker.run(command, str(tmp_path))

    assert executions == ["revision-a", "revision-b"]
    assert first["cache_hit"] is False
    assert repeated["cache_hit"] is True
    assert repeated["stdout"] == "revision-a\n"
    assert revised["cache_hit"] is False
    assert revised["stdout"] == "revision-b\n"


def test_repo_state_cache_does_not_reuse_result_after_immediate_file_change(tmp_path, monkeypatch) -> None:
    from local_ai_hub.repo_state import RepoStateTracker

    _init_patch_repo(tmp_path, {"src/app.py": "value = 1\n"})
    source = tmp_path / "src" / "app.py"
    repo_state = RepoStateTracker({"workspace_cache": {"fingerprint_ttl_seconds": 60.0}})
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path.parent / f"{tmp_path.name}-hub-state")},
            "commands": {
                "enabled": True,
                "coalesced_wait_seconds": 2,
                "max_output_chars": 4096,
                "allow_mutating": False,
            },
        },
        _Artifacts(),
        repo_state,
    )
    command = "python -m pytest -q"
    executions: list[str] = []
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)

    def execute(_command, _cwd, _timeout, cancel_event=None, log_callback=None):
        value = source.read_text(encoding="utf-8")
        executions.append(value)
        return _execution_result(value)

    monkeypatch.setattr(broker, "_execute", execute)

    first = broker.run(command, str(tmp_path))
    repeated = broker.run(command, str(tmp_path))
    source.write_text("value = 2\n", encoding="utf-8")
    changed = broker.run(command, str(tmp_path))

    assert first["cache_hit"] is False
    assert repeated["cache_hit"] is True
    assert changed["cache_hit"] is False
    assert changed["stdout"] == "value = 2\n"
    assert executions == ["value = 1\n", "value = 2\n"]


def test_environment_change_invalidates_repeatable_cache(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    broker.config["commands"]["environment_keys"] = ["T15_CACHE_SCOPE"]
    command = "python -m pytest -q"
    executions: list[str] = []
    monkeypatch.setenv("T15_CACHE_SCOPE", "scope-a")
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)

    def execute(_command, _cwd, _timeout, cancel_event=None, log_callback=None):
        value = os.environ["T15_CACHE_SCOPE"]
        executions.append(value)
        return _execution_result(f"{value}\n")

    monkeypatch.setattr(broker, "_execute", execute)

    first = broker.run(command, str(tmp_path))
    repeated = broker.run(command, str(tmp_path))
    monkeypatch.setenv("T15_CACHE_SCOPE", "scope-b")
    changed = broker.run(command, str(tmp_path))

    assert executions == ["scope-a", "scope-b"]
    assert first["cache_hit"] is False
    assert repeated["cache_hit"] is True
    assert changed["cache_hit"] is False
    assert changed["stdout"] == "scope-b\n"


def test_toolchain_change_invalidates_repeatable_cache(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    command = "python -m pytest -q"
    tool_identity = {"version": "tool-a"}
    executions: list[str] = []
    monkeypatch.setattr(broker, "_tool_identity", lambda _command, _cwd: dict(tool_identity))
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)

    def execute(_command, _cwd, _timeout, cancel_event=None, log_callback=None):
        executions.append(tool_identity["version"])
        return _execution_result(f"{tool_identity['version']}\n")

    monkeypatch.setattr(broker, "_execute", execute)

    first = broker.run(command, str(tmp_path))
    repeated = broker.run(command, str(tmp_path))
    tool_identity["version"] = "tool-b"
    changed = broker.run(command, str(tmp_path))

    assert executions == ["tool-a", "tool-b"]
    assert first["cache_hit"] is False
    assert repeated["cache_hit"] is True
    assert changed["cache_hit"] is False
    assert changed["stdout"] == "tool-b\n"


def test_run_reuses_tool_identity_and_reports_command_phase_timings(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    tool_identity = {"path": "synthetic-tool", "version": "v1"}
    identity_reads: list[dict[str, str]] = []
    monkeypatch.setattr(broker, "_tool_identity", lambda _command, _cwd: identity_reads.append(dict(tool_identity)) or dict(tool_identity))
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)
    monkeypatch.setattr(
        broker,
        "_execute",
        lambda *_args, **_kwargs: {
            **_execution_result("pass\n"),
            "phase_timings_ms": {"shell_startup_ms": 1.25, "stream_capture_ms": 2.5},
        },
    )

    result = broker.run("python -m pytest -q", str(tmp_path))

    assert result["success"] is True
    assert identity_reads == [tool_identity]
    timings = result["phase_timings_ms"]
    assert {"command_classification_ms", "repository_fingerprint_ms", "result_cache_lookup_ms", "shell_startup_ms", "stream_capture_ms"} <= set(timings)
    assert all(value >= 0 for value in timings.values())


def test_affected_test_selection_covers_transitive_dependency_graph(tmp_path) -> None:
    from local_ai_hub.deterministic import DeterministicEngine
    from local_ai_hub.repo_tools import RepositoryTools

    _init_patch_repo(
        tmp_path,
        {
            "pytest.ini": "[pytest]\ntestpaths = tests\n",
            "src/__init__.py": "",
            "src/shared.py": "VALUE = 1\n",
            "src/core.py": "from src.shared import VALUE\n\ndef core():\n    return VALUE\n",
            "src/app.py": "from src.core import core\n\ndef app():\n    return core()\n",
            "tests/__init__.py": "",
            "tests/test_shared.py": "from src.shared import VALUE\n\ndef test_shared():\n    assert VALUE == 1\n",
            "tests/test_core.py": "from src.core import core\n\ndef test_core():\n    assert core() == 1\n",
            "tests/test_app.py": "from src.app import app\n\ndef test_app():\n    assert app() == 1\n",
            "tests/test_unrelated.py": "def test_unrelated():\n    assert True\n",
        },
    )
    config = {
        "server": {"state_dir": str(tmp_path.parent / f"{tmp_path.name}-hub-state")},
    }
    engine = DeterministicEngine(config, RepositoryTools(config))

    result = engine.affected_tests(str(tmp_path), changed_paths=["src/shared.py"])

    assert result["success"] is True
    assert float(result.get("confidence", 0.0)) >= 0.95
    assert {
        "tests/test_shared.py",
        "tests/test_core.py",
        "tests/test_app.py",
    } == set(result["test_files"])


def test_cold_warm_command_benchmark_reports_paired_phase_percentiles(tmp_path) -> None:
    broker = _broker(tmp_path)
    stages = (
        "command_classification_ms",
        "repository_fingerprint_ms",
        "shell_startup_ms",
        "stream_capture_ms",
    )
    observations: list[dict] = []

    for pair in range(30):
        command = f'"{sys.executable}" -c "print(\'T15_PAIR_{pair}\')"'
        if pair % 2 == 0:
            cold_started = time.perf_counter()
            cold = broker.run(command, str(tmp_path),  force=True)
            cold_elapsed_ms = (time.perf_counter() - cold_started) * 1000
            warm_started = time.perf_counter()
            warm = broker.run(command, str(tmp_path))
            warm_elapsed_ms = (time.perf_counter() - warm_started) * 1000
        else:
            broker.run(command, str(tmp_path),  force=True)
            warm_started = time.perf_counter()
            warm = broker.run(command, str(tmp_path))
            warm_elapsed_ms = (time.perf_counter() - warm_started) * 1000
            cold_started = time.perf_counter()
            cold = broker.run(command, str(tmp_path),  force=True)
            cold_elapsed_ms = (time.perf_counter() - cold_started) * 1000
        observations.append({
            "pair": pair + 1,
            "command": command,
            "cold_elapsed_ms": round(cold_elapsed_ms, 3),
            "warm_elapsed_ms": round(warm_elapsed_ms, 3),
            "cold_success": cold.get("success"),
            "warm_success": warm.get("success"),
            "cold_cache_hit": cold.get("cache_hit", False),
            "cold_exit_code": cold.get("exit_code"),
            "warm_exit_code": warm.get("exit_code"),
            "cold_repository_revision": cold.get("repository_revision"),
            "warm_repository_revision": warm.get("repository_revision"),
            "cold_execution_id": cold.get("execution_id"),
            "warm_execution_id": warm.get("execution_id"),
            "cold_stdout": cold.get("stdout", ""),
            "warm_stdout": warm.get("stdout", ""),
            "cold_stderr": cold.get("stderr", ""),
            "warm_stderr": warm.get("stderr", ""),
            "cold_phase_timings_ms": cold.get("phase_timings_ms", {}),
            "warm_phase_timings_ms": warm.get("phase_timings_ms", {}),
            "warm_cache_hit": warm.get("cache_hit", False),
        })

    def percentile(values: list[float], fraction: float) -> float:
        ordered = sorted(values)
        position = (len(ordered) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    def phase_percentile(stage: str, sample: str, fraction: float) -> float:
        values = [item[f"{sample}_phase_timings_ms"].get(stage, 0.0) for item in observations]
        return percentile(values, fraction)

    report = {
        "pairs": len(observations),
        "worktree": str(tmp_path.resolve()),
        "toolchain": sys.executable,
        "cold_median_elapsed_ms": statistics.median(item["cold_elapsed_ms"] for item in observations),
        "warm_median_elapsed_ms": statistics.median(item["warm_elapsed_ms"] for item in observations),
        "phases_ms": {
            stage: {
                "cold_p50": phase_percentile(stage, "cold", 0.50),
                "cold_p95": phase_percentile(stage, "cold", 0.95),
                "warm_p50": phase_percentile(stage, "warm", 0.50),
                "warm_p95": phase_percentile(stage, "warm", 0.95),
            }
            for stage in stages
        },
        "observations": observations,
    }
    benchmark_summary = {
        "pairs": len(observations),
        "cold_median_elapsed_ms": round(report["cold_median_elapsed_ms"], 3),
        "warm_median_elapsed_ms": round(report["warm_median_elapsed_ms"], 3),
        "warm_median_lower": report["warm_median_elapsed_ms"] < report["cold_median_elapsed_ms"],
        "phases_ms": {
            stage: {key: round(value, 3) for key, value in values.items()}
            for stage, values in report["phases_ms"].items()
        },
        "all_runs_successful": all(item["cold_success"] and item["warm_success"] for item in observations),
        "all_cold_misses_warm_hits": all(not item["cold_cache_hit"] and item["warm_cache_hit"] for item in observations),
        "paired_outputs_match": all(item["cold_stdout"] == item["warm_stdout"] and item["cold_stderr"] == item["warm_stderr"] for item in observations),
        "paired_exit_codes_match": all(item["cold_exit_code"] == item["warm_exit_code"] for item in observations),
        "paired_revisions_match": all(item["cold_repository_revision"] == item["warm_repository_revision"] for item in observations),
    }
    print("T15_COMMAND_BENCHMARK " + json.dumps(benchmark_summary, sort_keys=True, separators=(",", ":")))
    assert len(observations) == 30
    assert all(item["cold_success"] and item["warm_success"] for item in observations)
    assert all(not item["cold_cache_hit"] and item["warm_cache_hit"] for item in observations)
    assert all(item["cold_exit_code"] == item["warm_exit_code"] == 0 for item in observations)
    assert all(item["cold_repository_revision"] == item["warm_repository_revision"] for item in observations)
    assert all(item["cold_stdout"] == item["warm_stdout"] for item in observations)
    assert all(item["cold_stderr"] == item["warm_stderr"] for item in observations)
    assert all(
        all(stage in item["cold_phase_timings_ms"] and stage in item["warm_phase_timings_ms"] for stage in stages)
        for item in observations
    )
    assert report["warm_median_elapsed_ms"] < report["cold_median_elapsed_ms"]


def test_mutating_calls_are_never_cached(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path, allow_mutating=True)
    command = "git add changed.py"
    executions: list[int] = []
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)

    def execute(_command, _cwd, _timeout, cancel_event=None, log_callback=None):
        executions.append(len(executions))
        return _execution_result(f"execution-{executions[-1]}\n")

    monkeypatch.setattr(broker, "_execute", execute)

    first = broker.run(command, str(tmp_path))
    second = broker.run(command, str(tmp_path))

    assert executions == [0, 1]
    assert first["cache_hit"] is False
    assert second["cache_hit"] is False
    assert first["stdout"] != second["stdout"]


def _init_patch_repo(root, files: dict[str, str]) -> None:
    subprocess.run(["git", "init"], cwd=str(root), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T15 Test"], cwd=str(root), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t15@example.invalid"], cwd=str(root), capture_output=True, check=True)
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(root), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=str(root), capture_output=True, check=True)


@pytest.mark.parametrize(
    ("confidence", "candidate_tests"),
    [(0.2, []), (0.99, ["tests/test_app.py"])],
)
def test_uncertain_affected_test_selection_widens_to_full_suite(tmp_path, monkeypatch, confidence, candidate_tests) -> None:
    from local_ai_hub.deterministic import DeterministicEngine

    _init_patch_repo(
        tmp_path,
        {"src/app.py": "value = 1\n", "tests/test_app.py": "def test_app():\n    assert True\n"},
    )
    def select_tests(*_args, **_kwargs):
        return {
            "success": True,
            "framework": "pytest",
            "test_files": candidate_tests,
            "confidence": confidence,
            "selection_complete": False,
        }

    monkeypatch.setattr(DeterministicEngine, "affected_tests", select_tests)
    monkeypatch.setattr(
        DeterministicEngine,
        "test_matrix",
        lambda *_args, **_kwargs: {
            "framework": "pytest",
            "run_all_command": "python -m pytest -q",
            "test_files": [{"path": "tests/test_app.py"}],
        },
    )
    broker = _broker(tmp_path)
    commands: list[str] = []

    def capture_run(command, *_args, **_kwargs):
        commands.append(command)
        return {"success": True, "exit_code": 0, "stdout": "ok", "stderr": "", "duration_ms": 1}

    monkeypatch.setattr(broker, "run", capture_run)
    patch = """--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-value = 1
+value = 2
"""

    result = broker.patch_and_verify(patch, str(tmp_path),  command="auto")

    assert commands == ["python -m pytest -q"]
    assert result["success"] is True
    assert result["affected_test_selection_widened"] is True
    assert result["affected_tests_run"] == ["tests/test_app.py"]


def test_uncertain_affected_test_selection_without_runner_rolls_back(tmp_path, monkeypatch) -> None:
    from local_ai_hub.deterministic import DeterministicEngine

    _init_patch_repo(
        tmp_path,
        {"src/app.py": "value = 1\n", "tests/test_app.py": "def test_app():\n    assert True\n"},
    )
    target = tmp_path / "src" / "app.py"
    selection_calls = {"affected_tests": 0, "test_matrix": 0}

    def affected_tests(*_args, **_kwargs):
        selection_calls["affected_tests"] += 1
        return {"success": True, "test_files": [], "confidence": 0.2}

    def test_matrix(*_args, **_kwargs):
        selection_calls["test_matrix"] += 1
        return {
            "framework": "pytest",
            "run_all_command": "",
            "test_files": [{"path": "tests/test_app.py"}],
        }

    monkeypatch.setattr(DeterministicEngine, "affected_tests", affected_tests)
    monkeypatch.setattr(DeterministicEngine, "test_matrix", test_matrix)
    broker = _broker(tmp_path)

    def forbidden_run(*_args, **_kwargs):
        raise AssertionError("validation must not run when no full-suite runner exists")

    monkeypatch.setattr(broker, "run", forbidden_run)
    patch = """--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-value = 1
+value = 2
"""

    result = broker.patch_and_verify(
        patch,
        str(tmp_path),

        command="auto",
        auto_rollback=True,
    )

    assert selection_calls == {
        "affected_tests": 1,
        "test_matrix": 1,
    }, (selection_calls, result)
    assert result["success"] is False
    assert result["applied"] is False, result
    assert result["rolled_back"] is True, result
    assert result["affected_test_selection_widened"] is True
    assert "no full-suite runner" in result["error"]
    assert target.read_text(encoding="utf-8") == "value = 1\n"


def test_affected_test_selection_exception_still_uses_full_suite(tmp_path, monkeypatch) -> None:
    from local_ai_hub.deterministic import DeterministicEngine

    _init_patch_repo(
        tmp_path,
        {"src/app.py": "value = 1\n", "tests/test_app.py": "def test_app():\n    assert True\n"},
    )
    monkeypatch.setattr(
        DeterministicEngine,
        "affected_tests",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("index unavailable")),
    )
    monkeypatch.setattr(
        DeterministicEngine,
        "test_matrix",
        lambda *_args, **_kwargs: {
            "framework": "pytest",
            "run_all_command": "python -m pytest -q",
            "test_files": [{"path": "tests/test_app.py"}],
        },
    )
    broker = _broker(tmp_path)
    commands: list[str] = []

    def capture_run(command, *_args, **_kwargs):
        commands.append(command)
        return {"success": True, "exit_code": 0, "stdout": "ok", "stderr": "", "duration_ms": 1}

    monkeypatch.setattr(broker, "run", capture_run)
    patch = """--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-value = 1
+value = 2
"""

    result = broker.patch_and_verify(patch, str(tmp_path),  command="auto")

    assert commands == ["python -m pytest -q"]
    assert result["success"] is True
    assert result["affected_test_selection_widened"] is True
    assert result["affected_tests_run"] == ["tests/test_app.py"]


def test_mock_server_port_collision_does_not_leak_socket_or_thread(tmp_path) -> None:
    broker = _broker(tmp_path)
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text('{"paths": {"/health": {"get": {"summary": "health"}}}}', encoding="utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        port = occupied.getsockname()[1]

        try:
            result = broker.mock_server_start(str(tmp_path), str(spec_path), port)

            assert result["success"] is False
            assert result["port"] == port
            assert port not in broker._mock_servers
            assert not any(thread.name == f"mock-srv-{port}" for thread in threading.enumerate())
        finally:
            server = broker._mock_servers.get(port)
            if server and server.get("alive"):
                broker.mock_server_stop(port)
                server["thread"].join(timeout=1)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))
        probe.listen(1)


def test_flaky_detection_preserves_each_attempt_and_identifies_instability(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    outcomes = [
        {
            "success": attempt != 11,
            "exit_code": 1 if attempt == 11 else 0,
            "stdout": f"attempt {attempt}",
            "stderr": "intermittent failure" if attempt == 11 else "",
            "duration_ms": 10 + attempt,
        }
        for attempt in range(1, 21)
    ]
    calls: list[tuple[str, str, int]] = []

    def execute(command, cwd, timeout, *_args, **_kwargs):
        calls.append((command, cwd, timeout))
        return outcomes[len(calls) - 1]

    monkeypatch.setattr(broker, "_execute", execute)

    result = broker.test_flaky_detect(str(tmp_path), "python -m pytest -q", runs=99, timeout_per_run=7)

    assert calls == [("python -m pytest -q", str(tmp_path.resolve()), 7)] * 20
    assert result["success"] is True
    assert result["total_runs"] == 20
    assert result["passed"] == 19
    assert result["failed"] == 1
    assert result["flaky"] is True
    assert result["status"] == "flaky"
    assert [attempt["run"] for attempt in result["runs"]] == list(range(1, 21))
    assert [attempt["success"] for attempt in result["runs"]].count(False) == 1
    assert [attempt["exit_code"] for attempt in result["runs"]][10] == 1
    assert [attempt["duration_ms"] for attempt in result["runs"]] == list(range(11, 31))
    assert [attempt["stdout_preview"] for attempt in result["runs"]] == [
        f"attempt {attempt}" for attempt in range(1, 21)
    ]
    assert result["runs"][10]["stderr_preview"] == "intermittent failure"


def test_patch_rollback_preserves_dirty_and_unrelated_files(tmp_path, monkeypatch) -> None:
    _init_patch_repo(tmp_path, {"src/target.py": "value = 1\n", "dirty.txt": "committed\n"})
    target = tmp_path / "src" / "target.py"
    dirty = tmp_path / "dirty.txt"
    target.write_text("value = 10\n", encoding="utf-8")
    dirty.write_text("local edit\n", encoding="utf-8")
    preexisting_untracked = tmp_path / "notes.txt"
    preexisting_untracked.write_text("keep me\n", encoding="utf-8")
    concurrent_untracked = tmp_path / "concurrent.log"
    generated = tmp_path / "new-dir" / "generated.txt"
    broker = _broker(tmp_path)

    def fail_validation(*_args, **_kwargs):
        concurrent_untracked.write_text("created during validation\n", encoding="utf-8")
        return {"success": False, "exit_code": 1, "stdout": "", "stderr": "expected failure"}

    monkeypatch.setattr(broker, "run", fail_validation)
    patch = """--- a/src/target.py
+++ b/src/target.py
@@ -1 +1 @@
-value = 10
+value = 20
--- /dev/null
+++ b/new-dir/generated.txt
@@ -0,0 +1 @@
+generated by patch
"""
    result = broker.patch_and_verify(patch, str(tmp_path),  command="python -m pytest -q")

    assert result["success"] is False
    assert result["rolled_back"] is True
    assert target.read_text(encoding="utf-8") == "value = 10\n"
    assert dirty.read_text(encoding="utf-8") == "local edit\n"
    assert preexisting_untracked.read_text(encoding="utf-8") == "keep me\n"
    assert concurrent_untracked.read_text(encoding="utf-8") == "created during validation\n"
    assert not generated.exists()
    assert not generated.parent.exists()


def test_patch_rollback_preserves_concurrent_edit_to_touched_file(tmp_path, monkeypatch) -> None:
    _init_patch_repo(tmp_path, {"src/target.py": "value = 1\n"})
    target = tmp_path / "src" / "target.py"
    broker = _broker(tmp_path)

    def fail_validation(*_args, **_kwargs):
        target.write_text("concurrent user edit\n", encoding="utf-8")
        return {"success": False, "exit_code": 1, "stdout": "", "stderr": "expected failure"}

    monkeypatch.setattr(broker, "run", fail_validation)
    patch = """--- a/src/target.py
+++ b/src/target.py
@@ -1 +1 @@
-value = 1
+value = 2
"""

    result = broker.patch_and_verify(patch, str(tmp_path),  command="python -m pytest -q")

    assert result["success"] is False
    assert result["rolled_back"] is False
    assert "changed during validation" in result["rollback_error"]
    assert target.read_text(encoding="utf-8") == "concurrent user edit\n"


def test_patch_path_rejects_nested_git_metadata() -> None:
    from local_ai_hub.commands import _patch_relative_parts

    with pytest.raises(ValueError, match="Git metadata"):
        _patch_relative_parts("vendor/subrepo/.git/config")


@pytest.mark.skipif(os.name != "nt", reason="Windows patch-root rename guard")
def test_patch_root_guard_blocks_rename_during_validation_and_releases_afterward(tmp_path, monkeypatch) -> None:
    _init_patch_repo(tmp_path, {"target.txt": "before\n"})
    moved = tmp_path.with_name(f"{tmp_path.name}-moved")
    broker = _broker(tmp_path)

    def check_root_lock(*_args, **_kwargs):
        with pytest.raises(OSError):
            tmp_path.rename(moved)
        return {"success": True, "exit_code": 0, "stdout": "ok", "stderr": "", "duration_ms": 1}

    monkeypatch.setattr(broker, "run", check_root_lock)
    patch = """--- a/target.txt
+++ b/target.txt
@@ -1 +1 @@
-before
+after
"""

    result = broker.patch_and_verify(patch, str(tmp_path),  command="python -m pytest -q")

    assert result["success"] is True
    tmp_path.rename(moved)
    try:
        assert (moved / "target.txt").read_text(encoding="utf-8") == "after\n"
    finally:
        if moved.exists():
            moved.rename(tmp_path)


def test_patch_snapshot_rejects_change_between_lstat_and_open(tmp_path, monkeypatch) -> None:
    import local_ai_hub.commands as commands_module

    target = tmp_path / "target.txt"
    target.write_text("small", encoding="utf-8")
    real_open = commands_module.os.open
    changed = False

    def change_before_open(path, *args, **kwargs):
        nonlocal changed
        if os.fspath(path) == os.fspath(target) and not changed:
            target.write_text("larger after lstat", encoding="utf-8")
            changed = True
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(commands_module.os, "open", change_before_open)

    with pytest.raises(ValueError, match="changed during snapshot"):
        commands_module._snapshot_patch_targets(tmp_path, ["target.txt"])


@pytest.mark.parametrize("stage", ["metadata", "check"])
def test_patch_git_preapply_timeout_returns_structured_failure(tmp_path, monkeypatch, stage) -> None:
    import local_ai_hub.commands as commands_module

    _init_patch_repo(tmp_path, {"target.txt": "before\n"})
    real_run = commands_module.subprocess.run
    patch = """--- a/target.txt
+++ b/target.txt
@@ -1 +1 @@
-before
+after
"""

    def timeout_selected_stage(args, *positional, **kwargs):
        command = list(args)
        if (stage == "metadata" and "--numstat" in command) or (stage == "check" and "--check" in command):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return real_run(args, *positional, **kwargs)

    monkeypatch.setattr(commands_module.subprocess, "run", timeout_selected_stage)
    result = _broker(tmp_path).patch_and_verify(patch, str(tmp_path),  command="python -m pytest -q")

    assert result["success"] is False
    assert result["timed_out"] is True
    assert result["applied"] is False
    assert result["rolled_back"] is False
    assert result["terminal"] is True
    assert (tmp_path / "target.txt").read_text(encoding="utf-8") == "before\n"


def test_patch_apply_timeout_reports_unknown_state_without_claiming_rollback(tmp_path, monkeypatch) -> None:
    import local_ai_hub.commands as commands_module

    _init_patch_repo(tmp_path, {"target.txt": "before\n"})
    real_run = commands_module.subprocess.run
    patch = """--- a/target.txt
+++ b/target.txt
@@ -1 +1 @@
-before
+after
"""

    def apply_then_timeout(args, *positional, **kwargs):
        command = list(args)
        result = real_run(args, *positional, **kwargs)
        if command == ["git", "apply", "--whitespace=nowarn"]:
            assert result.returncode == 0
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return result

    monkeypatch.setattr(commands_module.subprocess, "run", apply_then_timeout)
    result = _broker(tmp_path).patch_and_verify(patch, str(tmp_path),  command="python -m pytest -q")

    assert result["success"] is False
    assert result["timed_out"] is True
    assert result["apply_state_unknown"] is True
    assert result["applied"] is None
    assert result["rolled_back"] is False
    assert (tmp_path / "target.txt").read_text(encoding="utf-8") == "after\n"


def test_patch_rollback_fingerprints_postapply_file_above_preimage_cap(tmp_path, monkeypatch) -> None:
    import local_ai_hub.commands as commands_module

    _init_patch_repo(tmp_path, {"target.txt": "x\n"})
    target = tmp_path / "target.txt"
    broker = _broker(tmp_path)
    monkeypatch.setattr(commands_module, "_MAX_ROLLBACK_FILE_BYTES", 4)
    monkeypatch.setattr(commands_module, "_MAX_ROLLBACK_TOTAL_BYTES", 8)
    monkeypatch.setattr(
        broker,
        "run",
        lambda *_args, **_kwargs: {"success": False, "exit_code": 1, "stdout": "", "stderr": "expected failure"},
    )
    patch = """--- a/target.txt
+++ b/target.txt
@@ -1 +1 @@
-x
+a replacement longer than the snapshot cap
"""

    result = broker.patch_and_verify(patch, str(tmp_path),  command="python -m pytest -q")

    assert result["success"] is False
    assert result["rolled_back"] is True, result.get("rollback_error")
    assert target.read_text(encoding="utf-8") == "x\n"


def test_patch_scope_rejects_symlink_escape_without_touching_target(tmp_path) -> None:
    _init_patch_repo(tmp_path, {"tracked.txt": "baseline\n"})
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside data\n", encoding="utf-8")
    link = tmp_path / "escape.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        outside.unlink(missing_ok=True)
        pytest.skip(f"symlinks unavailable: {exc}")

    patch = """--- a/escape.txt
+++ b/escape.txt
@@ -1 +1 @@
-outside data
+changed data
"""
    try:
        result = _broker(tmp_path).patch_and_verify(patch, str(tmp_path),  command="python -m pytest -q")

        assert result["success"] is False
        assert result["applied"] is False
        assert "symlink" in result["error"].lower() or "escapes" in result["error"].lower()
        assert link.is_symlink()
        assert outside.read_text(encoding="utf-8") == "outside data\n"
    finally:
        link.unlink(missing_ok=True)
        outside.unlink(missing_ok=True)


def test_early_preflight_does_not_acquire_rollback_guard(tmp_path, monkeypatch) -> None:
    import local_ai_hub.commands as commands_module

    broker = _broker(tmp_path)
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: "missing-tool")

    def forbidden_snapshot(*_args, **_kwargs):
        raise AssertionError("early preflight must not acquire a rollback root guard")

    monkeypatch.setattr(commands_module, "_snapshot_rollback_scope", forbidden_snapshot)
    result = broker.run(
        "git status --short",
        str(tmp_path),

        rollback_on_failure=True,
        paths=["tracked.txt"],
    )

    assert result["success"] is False
    assert result["preflight"] is True
    assert broker._active_commands == {}
    assert broker._inflight == {}


def _project_context_for_tests(root, *, config_digest: str, env_references: dict[str, str]):
    settings = type("ProjectSettingsStub", (), {})()
    settings.commands = {}
    settings.affected_tests_mapping = {}
    settings.env_references = dict(env_references)
    settings.verification_rules = {}
    context = type("ProjectContextStub", (), {})()
    context.root = str(root)
    context.settings = settings
    context.config_digest = config_digest
    return context


def test_project_context_env_resolution_is_cached_by_config_and_env_fingerprint(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)
    monkeypatch.setenv("PROJECT_CI_TOKEN", "secret-a")
    envs: list[dict[str, str]] = []

    def execute(_command, _cwd, _timeout, cancel_event=None, log_callback=None, *, argv_override=None, env_overrides=None):
        envs.append(dict(env_overrides or {}))
        return _execution_result("ok\n")

    monkeypatch.setattr(broker, "_execute", execute)
    context = _project_context_for_tests(
        tmp_path,
        config_digest="config-a",
        env_references={"CI_TOKEN": "PROJECT_CI_TOKEN"},
    )

    first = broker.run("python -m pytest -q", str(tmp_path),  project_context=context)
    cached = broker.run("python -m pytest -q", str(tmp_path),  project_context=context)
    monkeypatch.setenv("PROJECT_CI_TOKEN", "secret-b")
    changed_env = broker.run("python -m pytest -q", str(tmp_path),  project_context=context)
    context.config_digest = "config-b"
    changed_config = broker.run("python -m pytest -q", str(tmp_path),  project_context=context)

    assert first["cache_hit"] is False
    assert cached["cache_hit"] is True
    assert changed_env["cache_hit"] is False
    assert changed_config["cache_hit"] is False
    assert envs == [
        {"CI_TOKEN": "secret-a"},
        {"CI_TOKEN": "secret-b"},
        {"CI_TOKEN": "secret-b"},
    ]
    assert "secret-a" not in json.dumps([first, cached, changed_env, changed_config])
    assert "secret-b" not in json.dumps([first, cached, changed_env, changed_config])


def test_project_context_missing_env_reference_fails_before_spawn(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd: None)
    monkeypatch.delenv("MISSING_PROJECT_TOKEN", raising=False)
    executions: list[str] = []
    monkeypatch.setattr(
        broker,
        "_execute",
        lambda command, *_args, **_kwargs: (executions.append(command) or _execution_result("unexpected\n")),
    )
    context = _project_context_for_tests(
        tmp_path,
        config_digest="config-a",
        env_references={"CI_TOKEN": "MISSING_PROJECT_TOKEN"},
    )

    result = broker.run("python -m pytest -q", str(tmp_path),  project_context=context)

    assert result["success"] is False
    assert executions == []
    assert "MISSING_PROJECT_TOKEN" not in json.dumps(result)


def test_structured_command_invocation_preserves_argv_without_shell_rendering(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    monkeypatch.setattr(broker, "_unavailable_executable", lambda _command, _cwd, **_kwargs: None)
    invocations: list[list[str] | None] = []

    def execute(_command, _cwd, _timeout, cancel_event=None, log_callback=None, *, argv_override=None, env_overrides=None):
        invocations.append(list(argv_override) if argv_override is not None else None)
        return _execution_result("ok\n")

    monkeypatch.setattr(broker, "_execute", execute)
    argv = ["python", "-m", "pytest", "-q", "--junitxml=literal;pipe|arg.xml"]
    invocation = CommandInvocation(argv=argv, cwd=str(tmp_path), shell=False)

    result = broker.run(invocation, str(tmp_path))

    assert result["success"] is True
    assert invocations == [argv]


@pytest.mark.parametrize(
    "command",
    [
        "pytest -q",
        "python -m pytest -q",
        "python -m coverage run -m pytest -q",
        "python tools/validate_report.py",
        ["python", "-m", "pytest", "-q", "--junitxml=literal;pipe|arg.xml"],
        'pwsh -NoProfile -Command "Invoke-Pester -Path tests"',
        'pwsh -NoProfile -Command "Test-RepositoryState"',
    ],
)
def test_explicit_python_and_powershell_validation_is_replay_safe(tmp_path, command) -> None:
    broker = _broker(tmp_path)

    result = broker.classify(command)

    assert result["class"] == "validation"
    assert result["replay_safe"] is True


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("python -m pytest -q && python -m unittest", True),
        ("python -m pytest -q && git add changed.py", False),
        ("python -m pytest -q | grep failed", True),
        ("python -m pytest -q | Out-File report.txt", False),
        ("python -m compileall -q src", False),
        ('python -c "assert True; open(\'changed.py\', \'w\').write(\'x\')"', False),
        ('pwsh -NoProfile -Command "Invoke-Pester; git add changed.py"', False),
        ("python -m unknown_module", False),
    ],
)
def test_replay_safety_composes_and_fails_closed(tmp_path, command, expected) -> None:
    broker = _broker(tmp_path, allow_mutating=True)

    assert broker.classify(command)["replay_safe"] is expected


def test_user_whitelisted_validation_is_not_replay_safe_or_cacheable(tmp_path) -> None:
    broker = _broker(tmp_path)
    broker.config["commands"]["extra_allowed_tools"] = ["custom-validator"]

    direct = broker.classify("custom-validator check")
    powershell = broker.classify(
        'pwsh -NoProfile -Command "Invoke-Pester; custom-validator -Target tests"'
    )

    assert direct["class"] == "validation"
    assert direct["replay_safe"] is False
    assert direct["cacheable"] is False
    assert powershell["replay_safe"] is False
    assert powershell["cacheable"] is False


@pytest.mark.parametrize(
    "command",
    ["python -m pytest -q", 'pwsh -NoProfile -Command "Test-RepositoryState"'],
)
def test_repair_loop_retries_explicit_validation(tmp_path, monkeypatch, command) -> None:
    broker = _broker(tmp_path)
    (tmp_path / "changed.py").write_text("value = 0\n", encoding="utf-8")
    executions: list[str] = []
    generator_calls: list[str] = []

    def run(actual_command: str, *_args, **_kwargs):
        executions.append(actual_command)
        return {"success": True, "exit_code": 0}

    def generate(actual_command: str, *_args):
        generator_calls.append(actual_command)
        return {"changed.py": "value = 1\n"}

    monkeypatch.setattr(broker, "run", run)
    result = broker.repair_loop(
        command,
        str(tmp_path),

        paths=["changed.py"],
        max_attempts=1,
        fix_generator=generate,
        initial_result={"success": False, "exit_code": 1, "stderr": "assertion failed"},
    )

    assert result["success"] is True
    assert result["attempts"] == 1
    assert executions == [command]
    assert generator_calls == [command]


@pytest.mark.parametrize(
    "initial_result",
    [
        {"success": False, "timed_out": True, "outcome_unknown": True},
        {"success": False, "cancelled": True, "outcome_unknown": True},
        {"success": False, "outcome_unknown": True},
    ],
)
def test_repair_loop_skips_uncertain_validation_result(tmp_path, monkeypatch, initial_result) -> None:
    broker = _broker(tmp_path)
    generator_calls: list[str] = []

    def generate(command: str, *_args):
        generator_calls.append(command)
        return {"changed.py": "value = 1\n"}

    result = broker.repair_loop(
        "python -m pytest -q",
        str(tmp_path),

        max_attempts=2,
        fix_generator=generate,
        initial_result=initial_result,
    )

    assert result["success"] is False
    assert result["repair_skipped"] is True
    assert result["outcome_unknown"] is True
    assert result["attempts"] == 0
    assert generator_calls == []


def test_repair_loop_skips_non_replay_safe_validation(tmp_path) -> None:
    broker = _broker(tmp_path)
    generator_calls: list[str] = []

    def generate(command: str, *_args):
        generator_calls.append(command)
        return {"changed.py": "value = 1\n"}

    result = broker.repair_loop(
        "python -m compileall -q src",
        str(tmp_path),

        max_attempts=2,
        fix_generator=generate,
        initial_result={"success": False, "exit_code": 1},
    )

    assert result["success"] is False
    assert result["repair_skipped"] is True
    assert result["outcome_unknown"] is True
    assert result["attempts"] == 0
    assert generator_calls == []


def test_structured_invocation_identity_uses_selected_executable(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    selected = str(tmp_path / "powershell.exe")
    alternative = str(tmp_path / "pwsh.exe")
    available = {"powershell": selected, "pwsh": alternative}
    monkeypatch.setattr(commands_module.shutil, "which", lambda name, *_args, **_kwargs: available.get(name))

    identity = broker._tool_identity("powershell", str(tmp_path), argv_override=["powershell", "-NoProfile"])
    assert identity["path"] == selected

    available["powershell"] = None
    unavailable = broker._unavailable_executable("powershell", str(tmp_path), argv_override=["powershell", "-NoProfile"])
    assert unavailable == "powershell"


def test_command_job_cleanup_requires_empty_job_confirmation(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(commands_module, "terminate_job_object", lambda handle: calls.append(("terminate", handle)) or True)
    monkeypatch.setattr(commands_module, "_wait_windows_job_empty", lambda handle, timeout_ms=2500: calls.append(("wait", handle)) or False)

    assert commands_module._terminate_and_confirm_windows_job_empty("job") is False
    assert calls == [("terminate", "job"), ("wait", "job")]


@pytest.mark.skipif(os.name == "nt", reason="POSIX daemon process groups only")
def test_recovered_daemon_requests_leaderless_group_cleanup_without_claiming_success(monkeypatch) -> None:
    pid = 24569
    identity = {"pid": pid, "executable": "test-daemon", "creation_identity": 2}
    digest = "a" * 64
    terminated: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(
        commands_module,
        "_daemon_process_group_owned",
        lambda group_id, token_digest: group_id == pid and token_digest == digest,
    )
    monkeypatch.setattr(
        commands_module,
        "terminate_tree",
        lambda *args, **kwargs: terminated.append((args, kwargs)) or False,
    )

    process = commands_module._RecoveredDaemonProcess(
        pid, identity, process_group_id=pid, ownership_token_digest=digest
    )

    assert process.poll() is None
    assert process.kill() is False
    assert terminated == [((pid,), {"process_group": pid, "grace_seconds": 0.1})]


@pytest.mark.skipif(os.name == "nt", reason="POSIX daemon process groups only")
def test_recovered_daemon_rejects_reused_leader_even_when_group_is_alive(monkeypatch) -> None:
    pid = 24569
    identity = {"pid": pid, "executable": "test-daemon", "creation_identity": 2}
    reused_identity = {**identity, "creation_identity": 999}
    terminated: list[int] = []
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: reused_identity)
    monkeypatch.setattr(
        commands_module, "_daemon_process_group_owned", lambda *_args: True
    )
    monkeypatch.setattr(
        commands_module,
        "terminate_tree",
        lambda current_pid, **_kwargs: terminated.append(current_pid) or True,
    )

    process = commands_module._RecoveredDaemonProcess(
        pid, identity, process_group_id=pid, ownership_token_digest="a" * 64
    )

    assert process.poll() == 0
    process.kill()
    assert terminated == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX daemon process groups only")
def test_recovered_daemon_rejects_leaderless_group_without_ownership_proof(monkeypatch) -> None:
    pid = 24569
    identity = {"pid": pid, "executable": "test-daemon", "creation_identity": 2}
    terminated: list[int] = []
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(
        commands_module, "_daemon_process_group_owned", lambda *_args: False
    )
    monkeypatch.setattr(
        commands_module,
        "terminate_tree",
        lambda current_pid, **_kwargs: terminated.append(current_pid) or True,
    )

    process = commands_module._RecoveredDaemonProcess(pid, identity, process_group_id=pid)

    assert process.poll() == 0
    process.kill()
    assert terminated == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX daemon process groups only")
@pytest.mark.parametrize("group_verified", [True, False])
def test_daemon_restart_requires_proof_for_leaderless_group(
    tmp_path, monkeypatch, group_verified: bool
) -> None:
    seed = _broker(tmp_path)
    daemon_id = "dmn_" + "b" * 32
    pid = 24570
    digest = "b" * 64
    log_path = seed._daemon_state_dir / f"{daemon_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes(b"")
    seed._daemon_registry_path.write_text(
        json.dumps(
            {
                "version": 2,
                "daemons": [
                    {
                        "daemon_id": daemon_id,
                        "pid": pid,
                        "identity": {
                            "pid": pid,
                            "executable": "test-daemon",
                            "creation_identity": 2,
                        },
                        "owner_id": seed._daemon_owner_id,
                        "process_group_id": pid,
                        "ownership_token_digest": digest,
                        "name": "daemon",
                        "command": "test-daemon",
                        "started_at": time.time(),
                        "expires_at": time.time() + 60,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(
        commands_module,
        "_daemon_process_group_owned",
        lambda group_id, token_digest: (
            group_verified and group_id == pid and token_digest == digest
        ),
    )

    recovered = _broker(tmp_path)
    try:
        status = recovered.daemon_status(daemon_id)
        assert status.get("running", False) is group_verified
        assert status.get("success", False) is group_verified
    finally:
        info = recovered._daemons.get(daemon_id)
        if info is not None:
            timer = info.get("ttl_timer")
            if timer is not None:
                timer.cancel()
            recovered._close_daemon_log(info)
            recovered._release_daemon_slot(info)


def test_linux_daemon_group_marker_requires_matching_group_and_digest(tmp_path) -> None:
    pid = 24569
    token = b"daemon-test-token"
    digest = hashlib.sha256(token).hexdigest()
    proc_dir = tmp_path / str(pid)
    proc_dir.mkdir()
    fields = ["S", "1", str(pid), *(["0"] * 16), "1234"]
    (proc_dir / "stat").write_bytes(
        f"{pid} (test-daemon) {' '.join(fields)}".encode()
    )
    (proc_dir / "environ").write_bytes(
        b"PATH=/usr/bin\0LOCAL_AI_HUB_DAEMON_OWNERSHIP_TOKEN=" + token + b"\0"
    )

    assert commands_module._linux_group_member_owns_token(pid, digest, tmp_path) is True
    assert commands_module._linux_group_member_owns_token(
        pid, "0" * 64, tmp_path
    ) is False
    assert commands_module._linux_group_member_owns_token(
        pid + 1, digest, tmp_path
    ) is False


def test_linux_group_marker_rejects_pgid_reuse_during_scan(tmp_path, monkeypatch) -> None:
    from io import BytesIO
    from pathlib import Path

    pid = 24569
    token = b"daemon-test-token"
    digest = hashlib.sha256(token).hexdigest()
    proc_dir = tmp_path / str(pid)
    proc_dir.mkdir()
    before_fields = ["S", "1", str(pid), *(["0"] * 16), "1234"]
    after_fields = ["S", "1", str(pid + 1), *(["0"] * 16), "1234"]
    before_stat = f"{pid} (test-daemon) {' '.join(before_fields)}".encode()
    reused_stat = f"{pid} (test-daemon) {' '.join(after_fields)}".encode()
    (proc_dir / "stat").write_bytes(before_stat)
    (proc_dir / "environ").write_bytes(
        b"PATH=/usr/bin\0LOCAL_AI_HUB_DAEMON_OWNERSHIP_TOKEN=" + token + b"\0"
    )
    original_open = Path.open
    stat_reads = 0

    def open_with_group_reuse(path, mode="r", *args, **kwargs):
        nonlocal stat_reads
        if path == proc_dir / "stat":
            stat_reads += 1
            return BytesIO(before_stat if stat_reads == 1 else reused_stat)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_with_group_reuse)

    assert commands_module._linux_group_member_owns_token(pid, digest, tmp_path) is False
    assert stat_reads == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX daemon process groups only")
def test_daemon_registry_persists_verified_leaderless_process_group(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    daemon_id = "dmn_" + "a" * 32
    pid = 24569
    digest = "a" * 64

    class ExitedProcess:
        def poll(self):
            return 0

    monkeypatch.setattr(commands_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(
        commands_module,
        "_daemon_process_group_owned",
        lambda group_id, token_digest: group_id == pid and token_digest == digest,
    )
    broker._daemons[daemon_id] = {
        "process": ExitedProcess(),
        "pid": pid,
        "identity": {"pid": pid, "executable": "test-daemon", "creation_identity": 2},
        "process_group_id": pid,
        "ownership_token_digest": digest,
        "owner_id": broker._daemon_owner_id,
        "name": "daemon",
        "command": "test-daemon",
        "started_at": 100.0,
        "expires_at": 200.0,
    }

    assert broker._persist_daemon_registry() is True
    payload = json.loads(broker._daemon_registry_path.read_text(encoding="utf-8"))
    row = payload["daemons"][0]
    assert row["pid"] == pid
    assert row["process_group_id"] == pid
    assert row["ownership_token_digest"] == digest


def test_posix_numeric_process_group_cleanup_fails_closed_without_signals(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    class PosixOsProxy:
        name = "posix"

        @staticmethod
        def killpg(group_id, _sig):
            calls.append(("killpg", group_id))
            raise ProcessLookupError

        @staticmethod
        def kill(pid, _sig):
            calls.append(("kill", pid))
            raise ProcessLookupError

    monkeypatch.setattr(process_utils_module, "os", PosixOsProxy())

    result = process_utils_module.terminate_tree(24569, process_group=24569, grace_seconds=0.1)

    assert result is False
    assert calls == []


def test_posix_group_cleanup_does_not_escalate_after_leader_identity_changes(monkeypatch) -> None:
    expected = {
        "pid": 24569,
        "executable": "/usr/bin/python",
        "creation_identity": 1234,
        "creation_identity_type": "linux_proc_starttime_ticks",
    }
    calls: list[tuple[int, int]] = []
    slept = False

    class PosixOsProxy:
        name = "posix"

        @staticmethod
        def getpgid(pid):
            assert pid == 24569
            return 24569

        @staticmethod
        def killpg(group_id, sig):
            calls.append((group_id, sig))
            if sig == 0:
                return None

    def process_identity(pid):
        assert pid == 24569
        return expected if not slept else None

    def sleep(_seconds):
        nonlocal slept
        slept = True

    monkeypatch.setattr(process_utils_module, "os", PosixOsProxy())
    monkeypatch.setattr(process_utils_module, "process_identity", process_identity)
    monkeypatch.setattr(process_utils_module.time, "sleep", sleep)
    monkeypatch.setattr(signal, "SIGKILL", 9, raising=False)

    process_handle = type("PopenHandle", (), {})()
    process_handle.pid = 24569
    process_handle.returncode = None
    process_handle._waitpid_lock = threading.Lock()
    result = process_utils_module.terminate_tree(
        24569,
        process_group=24569,
        expected_identity=expected,
        grace_seconds=0.1,
        process_handle=process_handle,
    )

    assert result is False
    assert calls == [(24569, signal.SIGTERM)]


def test_run_hidden_timeout_preserves_unconfirmed_posix_process_without_pid_kill(monkeypatch) -> None:
    release_readers = threading.Event()
    reader_threads: list[threading.Thread] = []

    class PosixOsProxy:
        name = "posix"

    class TimedOutProcess:
        pid = 24569

        class Pipe:
            def __init__(self) -> None:
                self.closed = False
                self.closed_event = threading.Event()

            def close(self) -> None:
                self.closed = True
                self.closed_event.set()

            def read(self, size: int) -> bytes:
                assert size > 0
                reader_threads.append(threading.current_thread())
                if not release_readers.wait(timeout=5):
                    raise TimeoutError("test-owned pipe reader was not released")
                return b""

        def __init__(self) -> None:
            self.stdout = self.Pipe()
            self.stderr = self.Pipe()
            self.kill_calls = 0
            self.wait_calls = 0
            self.communicate_calls = 0

        def communicate(self, input=None, timeout=None):
            self.communicate_calls += 1
            raise subprocess.TimeoutExpired(
                ["fake"], timeout, output=b"partial", stderr=b"partial-error"
            )

        def poll(self):
            return None

        def kill(self):
            self.kill_calls += 1

        def wait(self, timeout=None):
            self.wait_calls += 1
            raise subprocess.TimeoutExpired(["fake"], timeout)

    process = TimedOutProcess()
    termination_calls: list[tuple[int, dict[str, object]]] = []

    def refuse_numeric_group(pid: int, **kwargs) -> bool:
        termination_calls.append((pid, kwargs))
        return False

    monkeypatch.setattr(process_utils_module, "os", PosixOsProxy())
    monkeypatch.setattr(
        process_utils_module.subprocess, "Popen", lambda *_args, **_kwargs: process
    )
    monkeypatch.setattr(process_utils_module, "terminate_tree", refuse_numeric_group)

    try:
        with pytest.raises(subprocess.TimeoutExpired) as raised:
            process_utils_module.run_hidden(["fake"], timeout=0.01, capture_output=True)

        error = raised.value
        assert process.kill_calls == 0
        assert process.wait_calls == 0
        assert process.communicate_calls == 0
        assert process.stdout.closed is False
        assert process.stderr.closed is False
        assert len(termination_calls) in (1, 2)
        assert error.cleanup_unconfirmed is True
        assert error.cleanup_process is process
        assert error.cleanup_process_group == process.pid
    finally:
        release_readers.set()
        stdout_closed = process.stdout.closed_event.wait(timeout=2)
        stderr_closed = process.stderr.closed_event.wait(timeout=2)
        for reader in reader_threads:
            reader.join(timeout=2)
        assert stdout_closed and stderr_closed
        assert all(not reader.is_alive() for reader in reader_threads)


def test_posix_terminate_tree_refuses_unowned_numeric_pid_and_group(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    class PosixOsProxy:
        name = "posix"

        @staticmethod
        def killpg(group_id, sig):
            calls.append(("killpg", group_id, sig))

        @staticmethod
        def kill(pid, sig):
            calls.append(("kill", pid, sig))

    monkeypatch.setattr(process_utils_module, "os", PosixOsProxy())
    monkeypatch.setattr(process_utils_module.signal, "SIGKILL", 9, raising=False)

    assert process_utils_module.terminate_tree(24569, grace_seconds=0.1) is False
    assert process_utils_module.terminate_tree(
        24569, process_group=24569, grace_seconds=0.1
    ) is False
    assert calls == []


def test_explicit_process_group_reports_unknown_liveness_without_pid_fallback(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    class PosixOsProxy:
        name = "posix"

        @staticmethod
        def killpg(group_id, sig):
            calls.append(("killpg", group_id, sig))
            raise OSError(22, "group state unavailable")

        @staticmethod
        def kill(pid, _sig):
            calls.append(("kill", pid))
            raise ProcessLookupError

    monkeypatch.setattr(process_utils_module, "os", PosixOsProxy())
    monkeypatch.setattr(process_utils_module.signal, "SIGKILL", 9, raising=False)

    result = process_utils_module.terminate_tree(24569, process_group=24569, grace_seconds=0.1)

    assert result is False
    assert calls == []


def test_posix_cleanup_does_not_report_success_when_signals_are_denied(monkeypatch) -> None:
    calls: list[tuple[object, ...]] = []

    class PosixOsProxy:
        name = "posix"

        @staticmethod
        def killpg(group_id, sig):
            calls.append(("killpg", group_id, sig))
            raise PermissionError("group signal denied")

        @staticmethod
        def kill(pid, sig):
            calls.append(("kill", pid, sig))
            raise PermissionError("leader signal denied")

    monkeypatch.setattr(process_utils_module, "os", PosixOsProxy())
    monkeypatch.setattr(process_utils_module.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(process_utils_module, "pid_alive", lambda _pid: True)

    result = process_utils_module.terminate_tree(
        24569, process_group=24569, grace_seconds=0.1
    )

    assert result is False
    assert calls == []


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
