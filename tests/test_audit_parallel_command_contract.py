"""Acceptance coverage for complete, preflighted parallel command batches."""

from __future__ import annotations

import threading

import pytest

from local_ai_hub.command_batches import _OPTIONS, run_parallel
from local_ai_hub.commands import StreamMultiplexer


def _run_batch(run, commands, tmp_path, *, max_concurrency=2):
    return run_parallel(
        run,
        commands,
        cwd=str(tmp_path),
        max_concurrency=max_concurrency,
        timeout=41,
        multiplexer=StreamMultiplexer(),
    )


def test_parallel_batch_forwards_every_supported_execution_context(tmp_path):
    calls = []
    call_lock = threading.Lock()
    fix_generator = object()
    fence = object()
    project_context = object()
    project_command_context = object()
    cancel_event = threading.Event()
    options = {
        "cwd": str(tmp_path),
        "timeout": 17,
        "force": True,
        "task_id": "task-explicit",
        "criterion": "acceptance",
        "record_verification": False,
        "auto_fix": True,
        "fix_generator": fix_generator,
        "max_repair_attempts": 2,
        "snapshot": True,
        "rollback_on_failure": True,
        "sandbox": "docker",
        "docker_image": "python:3.11-slim",
        "bypass_cache": True,
        "paths": ["src/sample.py"],
        "rollback_paths": ["src/sample.py"],
        "project_context": project_context,
        "env": {"MODE": "test"},
        "_environment_overrides": {"SETTING": "value"},
        "_cache_context": "cache-context",
        "_transaction_context": "a" * 32,
        "_work_attempt_fence": fence,
        "_project_command_context": project_command_context,
        "request_cancel_event": cancel_event,
        "stdin": "stdin-data",
        "input": "input-data",
    }

    assert set(options) == _OPTIONS

    def run_spy(command, **kwargs):
        with call_lock:
            calls.append((command, kwargs))
        kwargs["log_callback"]("stdout", "captured\n")
        return {"success": True}

    result = _run_batch(run_spy, [{"id": "one", "command": "probe", **options}], tmp_path)

    assert result["success"] is True
    assert len(calls) == 1
    command, forwarded = calls[0]
    assert command == "probe"
    for name, value in options.items():
        assert forwarded[name] is value if name in {
            "fix_generator", "project_context", "_work_attempt_fence",
            "_project_command_context", "request_cancel_event",
        } else forwarded[name] == value
    assert callable(forwarded["log_callback"])
    assert "captured" in result["multiplexed_output"]


def test_unknown_parallel_option_rejects_whole_batch_before_dispatch(tmp_path):
    calls = []

    def run_spy(command, **kwargs):
        calls.append((command, kwargs))
        return {"success": True}

    result = _run_batch(
        run_spy,
        [
            {"id": "valid", "cmd": "would-run"},
            {"id": "invalid", "cmd": "also-would-run", "unrecognized": True},
        ],
        tmp_path,
    )

    assert result["preflight"] is True
    assert result["request_not_sent"] is True
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert calls == []


@pytest.mark.parametrize(
    "commands",
    [
        [{"id": "duplicate", "cmd": "fail"}, {"id": "duplicate", "cmd": "pass"}],
        [{"id": "duplicate", "cmd": "pass"}, {"id": "duplicate", "cmd": "fail"}],
    ],
)
def test_duplicate_ids_reject_before_dispatch_in_either_order(commands, tmp_path):
    calls = []

    def run_spy(command, **kwargs):
        calls.append(command)
        return {"success": command == "pass"}

    result = _run_batch(run_spy, commands, tmp_path)

    assert result["preflight"] is True
    assert result["request_not_sent"] is True
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert calls == []


def test_unique_mixed_batch_finishing_out_of_order_is_not_overall_success(tmp_path):
    fast_finished = threading.Event()
    completion_order = []
    order_lock = threading.Lock()

    def run_spy(command, **kwargs):
        if command == "wait-for-fast":
            assert fast_finished.wait(timeout=3), "second command did not finish"
            with order_lock:
                completion_order.append(command)
            return {"success": True}
        with order_lock:
            completion_order.append(command)
        fast_finished.set()
        return {"success": False, "error": "expected fixture failure"}

    result = _run_batch(
        run_spy,
        [
            {"id": "slow-first", "cmd": "wait-for-fast"},
            {"id": "fast-second", "cmd": "fail"},
        ],
        tmp_path,
    )

    assert completion_order == ["fail", "wait-for-fast"]
    assert set(result["results"]) == {"fast-second", "slow-first"}
    assert result["results"]["slow-first"]["success"] is True
    assert result["results"]["fast-second"]["success"] is False
    assert result["commands_completed"] == 2
    assert result["success"] is False
