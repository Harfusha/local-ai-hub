from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Any
import pytest

from local_ai_hub import process_utils


class _MockProcess:
    def __init__(self, exit_after_terminate: bool = True, exit_after_kill: bool = True) -> None:
        self.pid = 9999
        self.returncode: int | None = None
        self.events: list[tuple[str, Any]] = []
        self._exit_after_terminate = exit_after_terminate
        self._exit_after_kill = exit_after_kill

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.events.append(("terminate", None))
        if self._exit_after_terminate:
            self.returncode = 0

    def kill(self) -> None:
        self.events.append(("kill", None))
        if self._exit_after_kill:
            self.returncode = -9

    def wait(self, timeout: float | None = None) -> int | None:
        self.events.append(("wait", timeout))
        if self.returncode is not None:
            return self.returncode
        raise subprocess.TimeoutExpired(["proc"], timeout or 0.0)


def test_process_already_exited_returns_true_immediately() -> None:
    proc = _MockProcess()
    proc.returncode = 0
    result = process_utils.terminate_subprocess_grace_window(proc, grace_seconds=2.0)
    assert result is True
    assert proc.events == []


def test_graceful_exit_within_window_does_not_escalate_to_kill() -> None:
    proc = _MockProcess(exit_after_terminate=True)
    clock = 100.0

    def mock_time() -> float:
        nonlocal clock
        clock += 0.05
        return clock

    result = process_utils.terminate_subprocess_grace_window(
        proc,
        grace_seconds=1.0,
        kill_timeout=0.5,
        time_fn=mock_time,
    )
    assert result is True
    event_names = [ev[0] for ev in proc.events]
    assert "terminate" in event_names
    assert "kill" not in event_names
    assert proc.returncode == 0


def test_unresponsive_process_escalates_to_kill_after_grace_window() -> None:
    proc = _MockProcess(exit_after_terminate=False, exit_after_kill=True)
    clock = 1000.0

    def mock_time() -> float:
        nonlocal clock
        clock += 0.3
        return clock

    result = process_utils.terminate_subprocess_grace_window(
        proc,
        grace_seconds=1.0,
        kill_timeout=0.5,
        time_fn=mock_time,
    )
    assert result is True
    event_names = [ev[0] for ev in proc.events]
    assert event_names[0] == "terminate"
    assert "kill" in event_names
    assert proc.returncode == -9


def test_process_ignoring_both_terminate_and_kill_returns_false() -> None:
    proc = _MockProcess(exit_after_terminate=False, exit_after_kill=False)
    clock = 2000.0

    def mock_time() -> float:
        nonlocal clock
        clock += 0.4
        return clock

    result = process_utils.terminate_subprocess_grace_window(
        proc,
        grace_seconds=1.0,
        kill_timeout=0.5,
        time_fn=mock_time,
    )
    assert result is False
    event_names = [ev[0] for ev in proc.events]
    assert "terminate" in event_names
    assert "kill" in event_names
    assert proc.returncode is None


def test_zero_grace_seconds_escalates_immediately_to_kill() -> None:
    proc = _MockProcess(exit_after_terminate=False, exit_after_kill=True)
    result = process_utils.terminate_subprocess_grace_window(
        proc,
        grace_seconds=0.0,
        kill_timeout=0.5,
    )
    assert result is True
    event_names = [ev[0] for ev in proc.events]
    assert event_names[0] == "terminate"
    assert "kill" in event_names


def test_real_subprocess_graceful_termination() -> None:
    # Spawn a sleeping python process that exits cleanly
    cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
    proc = subprocess.Popen(cmd)
    try:
        t0 = time.monotonic()
        res = process_utils.terminate_subprocess_grace_window(proc, grace_seconds=3.0, kill_timeout=1.0)
        elapsed = time.monotonic() - t0
        assert res is True
        assert proc.poll() is not None
        # Should finish well before the 3s grace window expires
        assert elapsed < 2.5
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
