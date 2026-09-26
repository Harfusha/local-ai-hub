from __future__ import annotations

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

import pytest

from local_ai_hub.commands import CommandBroker
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
    return CommandBroker(
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


def test_repeatable_command_cache_is_scoped_by_tenant_and_timeout(tmp_path, monkeypatch) -> None:
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

    tenant_a = broker.run(command, str(tmp_path), "tenant-a", timeout=4)
    tenant_b = broker.run(command, str(tmp_path), "tenant-b", timeout=4)
    short = broker.run(command, str(tmp_path), "tenant-timeout", timeout=1)
    long = broker.run(command, str(tmp_path), "tenant-timeout", timeout=10)

    assert executions == [4, 4, 1, 10]
    assert tenant_a["cache_hit"] is False
    assert tenant_b["cache_hit"] is False
    assert tenant_b["stdout"] == "run-2"
    assert short["success"] is False
    assert long["success"] is True
    assert long["cache_hit"] is False
    assert long["stdout"] == "run-4"


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
            results[caller] = broker.run(command, str(tmp_path), "tenant")
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
            results[caller] = broker.run(command, str(tmp_path), "tenant")
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
            results[caller] = broker.run(command, str(tmp_path), "tenant")
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
            results[caller] = broker.run(command, str(tmp_path), "tenant")
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
            result_holder["result"] = broker.run(command, str(tmp_path), "tenant", timeout=8)
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
            broker.cancel(command, str(tmp_path), "tenant")
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

    result = broker.run(
        f'"{sys.executable}" "{script_path}"',
        str(tmp_path),
        "tenant",
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

    def fail_reader_start(thread, *args, **kwargs):
        if getattr(getattr(thread, "_target", None), "__name__", "") == "_reader":
            raise RuntimeError("injected reader thread startup failure")
        return real_start(thread, *args, **kwargs)

    monkeypatch.setattr(commands_module.threading.Thread, "start", fail_reader_start)

    result = broker.run(f'"{sys.executable}" "{script_path}"', str(tmp_path), "tenant", timeout=8)

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not pid_path.exists():
        time.sleep(0.02)
    assert result["success"] is False
    assert result["cleanup_unconfirmed"] is False
    assert "reader" in result["error"].lower()
    assert pid_path.exists()
    assert not pid_alive(int(pid_path.read_text(encoding="utf-8")))


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
        result = broker.run(
            f'"{sys.executable}" "{script_path}"',
            str(tmp_path),
            "tenant",
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
    result = broker.run(
        f'"{sys.executable}" "{script_path}"',
        str(tmp_path),
        "tenant",
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
        result = broker.run(command, str(tmp_path), "tenant", timeout=8)
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
        result = broker.run(command, str(tmp_path), "tenant", timeout=8)
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
        result = broker.run(command, str(tmp_path), "tenant", timeout=8)
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

    first = broker.run(command, str(tmp_path), "tenant")
    repeated = broker.run(command, str(tmp_path), "tenant")
    repo_state.revision = "revision-b"
    revised = broker.run(command, str(tmp_path), "tenant")

    assert executions == ["revision-a", "revision-b"]
    assert first["cache_hit"] is False
    assert repeated["cache_hit"] is True
    assert repeated["stdout"] == "revision-a\n"
    assert revised["cache_hit"] is False
    assert revised["stdout"] == "revision-b\n"


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

    first = broker.run(command, str(tmp_path), "tenant")
    repeated = broker.run(command, str(tmp_path), "tenant")
    monkeypatch.setenv("T15_CACHE_SCOPE", "scope-b")
    changed = broker.run(command, str(tmp_path), "tenant")

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

    first = broker.run(command, str(tmp_path), "tenant")
    repeated = broker.run(command, str(tmp_path), "tenant")
    tool_identity["version"] = "tool-b"
    changed = broker.run(command, str(tmp_path), "tenant")

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

    result = broker.run("python -m pytest -q", str(tmp_path), "tenant")

    assert result["success"] is True
    assert identity_reads == [tool_identity]
    timings = result["phase_timings_ms"]
    assert {"command_classification_ms", "tool_identity_ms", "repository_fingerprint_ms", "result_cache_lookup_ms", "shell_startup_ms", "stream_capture_ms"} <= set(timings)
    assert all(value >= 0 for value in timings.values())


def test_affected_test_selection_covers_transitive_dependency_graph(tmp_path) -> None:
    from local_ai_hub.deterministic import DeterministicEngine
    from local_ai_hub.repo_tools import RepositoryTools

    _init_patch_repo(
        tmp_path,
        {
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
        "tool_identity_ms",
        "repository_fingerprint_ms",
        "shell_startup_ms",
        "stream_capture_ms",
    )
    observations: list[dict] = []

    for pair in range(10):
        command = f'"{sys.executable}" -c "print(\'T15_PAIR_{pair}\')"'
        if pair % 2 == 0:
            cold_started = time.perf_counter()
            cold = broker.run(command, str(tmp_path), "tenant", force=True)
            cold_elapsed_ms = (time.perf_counter() - cold_started) * 1000
            warm_started = time.perf_counter()
            warm = broker.run(command, str(tmp_path), "tenant")
            warm_elapsed_ms = (time.perf_counter() - warm_started) * 1000
        else:
            broker.run(command, str(tmp_path), "tenant", force=True)
            warm_started = time.perf_counter()
            warm = broker.run(command, str(tmp_path), "tenant")
            warm_elapsed_ms = (time.perf_counter() - warm_started) * 1000
            cold_started = time.perf_counter()
            cold = broker.run(command, str(tmp_path), "tenant", force=True)
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
    print("T15_COMMAND_BENCHMARK " + json.dumps(report, sort_keys=True, separators=(",", ":")))
    assert len(observations) == 10
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

    first = broker.run(command, str(tmp_path), "tenant")
    second = broker.run(command, str(tmp_path), "tenant")

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


def test_uncertain_affected_test_selection_widens_to_full_suite(tmp_path, monkeypatch) -> None:
    from local_ai_hub.deterministic import DeterministicEngine

    _init_patch_repo(
        tmp_path,
        {"src/app.py": "value = 1\n", "tests/test_app.py": "def test_app():\n    assert True\n"},
    )
    monkeypatch.setattr(
        DeterministicEngine,
        "affected_tests",
        lambda *_args, **_kwargs: {
            "success": True,
            "framework": "pytest",
            "test_files": [],
            "confidence": 0.2,
        },
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

    result = broker.patch_and_verify(patch, str(tmp_path), "tenant", command="auto")

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
    monkeypatch.setattr(
        DeterministicEngine,
        "affected_tests",
        lambda *_args, **_kwargs: {"success": True, "test_files": [], "confidence": 0.2},
    )
    monkeypatch.setattr(
        DeterministicEngine,
        "test_matrix",
        lambda *_args, **_kwargs: {
            "framework": "pytest",
            "run_all_command": "",
            "test_files": [{"path": "tests/test_app.py"}],
        },
    )
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
        "tenant",
        command="auto",
        auto_rollback=True,
    )

    assert result["success"] is False
    assert result["applied"] is False
    assert result["rolled_back"] is True
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

    result = broker.patch_and_verify(patch, str(tmp_path), "tenant", command="auto")

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
    result = broker.patch_and_verify(patch, str(tmp_path), "tenant", command="python -m pytest -q")

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

    result = broker.patch_and_verify(patch, str(tmp_path), "tenant", command="python -m pytest -q")

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

    result = broker.patch_and_verify(patch, str(tmp_path), "tenant", command="python -m pytest -q")

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
    result = _broker(tmp_path).patch_and_verify(patch, str(tmp_path), "tenant", command="python -m pytest -q")

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
    result = _broker(tmp_path).patch_and_verify(patch, str(tmp_path), "tenant", command="python -m pytest -q")

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

    result = broker.patch_and_verify(patch, str(tmp_path), "tenant", command="python -m pytest -q")

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
        result = _broker(tmp_path).patch_and_verify(patch, str(tmp_path), "tenant", command="python -m pytest -q")

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
        "missing-tool --version",
        str(tmp_path),
        "tenant",
        rollback_on_failure=True,
        rollback_paths=["tracked.txt"],
    )

    assert result["success"] is False
    assert result["preflight"] is True
    assert broker._active_commands == {}
    assert broker._inflight == {}
