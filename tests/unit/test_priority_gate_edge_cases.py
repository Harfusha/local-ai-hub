from __future__ import annotations

import math
import threading
import time

import pytest

from local_ai_hub.priority_gate import CooperativePriorityGate


def test_priority_gate_defensive_initialization_and_params() -> None:
    # Non-integer foreground_priority raises ValueError
    with pytest.raises(ValueError, match="foreground_priority must be an integer"):
        CooperativePriorityGate("invalid")  # type: ignore[arg-type]
    gate = CooperativePriorityGate()
    assert gate.foreground_priority == 3

    with pytest.raises(ValueError):
        with gate.slot(priority="bad"):  # type: ignore[arg-type]
            raise AssertionError("invalid priority must not acquire the gate")

    with pytest.raises(ValueError, match="timeout"):
        with gate.slot(priority=1, timeout=float("nan")):
            raise AssertionError("invalid timeout must not acquire the gate")

    with gate.slot(priority=1, timeout=1):
        assert gate.is_active is True

    assert gate.is_active is False


def test_priority_gate_try_acquire_and_release() -> None:
    gate = CooperativePriorityGate(foreground_priority=3)
    assert gate.is_active is False

    # Immediate non-blocking acquire
    assert gate.try_acquire(priority=1) is True
    assert gate.is_active is True

    # Busy - subsequent try_acquire returns False
    assert gate.try_acquire(priority=1) is False
    assert gate.try_acquire(priority=4) is False

    # Manual release
    gate.release()
    assert gate.is_active is False

    # Can acquire again
    assert gate.try_acquire(priority=4) is True
    gate.release()
    assert gate.is_active is False


def test_priority_gate_foreground_cut_in() -> None:
    gate = CooperativePriorityGate(foreground_priority=3)
    order: list[str] = []
    started = threading.Event()
    release_blocker = threading.Event()

    def blocker() -> None:
        with gate.slot(priority=1):
            started.set()
            release_blocker.wait(timeout=2.0)
            order.append("blocker")

    def background_worker() -> None:
        started.wait(timeout=1.0)
        time.sleep(0.01)
        with gate.slot(priority=1, timeout=2.0):
            order.append("background")

    def foreground_worker() -> None:
        started.wait(timeout=1.0)
        time.sleep(0.02)
        with gate.slot(priority=4, timeout=2.0):
            order.append("foreground")

    t_block = threading.Thread(target=blocker)
    t_bg = threading.Thread(target=background_worker)
    t_fg = threading.Thread(target=foreground_worker)

    t_block.start()
    t_bg.start()
    t_fg.start()

    time.sleep(0.1)
    assert gate.foreground_waiters_count() >= 1

    release_blocker.set()
    t_block.join(timeout=2.0)
    t_fg.join(timeout=2.0)
    t_bg.join(timeout=2.0)

    # Foreground must have executed before background
    assert order == ["blocker", "foreground", "background"]


def test_priority_gate_reset() -> None:
    gate = CooperativePriorityGate()
    assert gate.try_acquire() is True
    assert gate.is_active is True

    gate.reset()
    assert gate.is_active is False
    assert gate.foreground_waiters_count() == 0
