from __future__ import annotations

import threading
import time
import pytest

from local_ai_hub.priority_gate import CooperativePriorityGate


def test_cooperative_priority_gate_zero_timeout_succeeds_when_free():
    gate = CooperativePriorityGate(foreground_priority=3)
    acquired = False
    with gate.slot(priority=1, timeout=0.0):
        acquired = True
        assert gate.is_active is True
        status = gate.status()
        assert status["active"] is True
        assert status["foreground_waiters"] == 0
        assert status["foreground_priority"] == 3
    assert acquired is True
    assert gate.is_active is False


def test_cooperative_priority_gate_zero_timeout_raises_immediately_when_busy():
    gate = CooperativePriorityGate(foreground_priority=3)
    entered = threading.Event()
    release = threading.Event()

    def holder():
        with gate.slot(priority=1, timeout=1.0):
            entered.set()
            release.wait(timeout=2.0)

    t = threading.Thread(target=holder)
    t.start()
    try:
        assert entered.wait(timeout=1.0)
        start = time.monotonic()
        with pytest.raises(TimeoutError, match="timed out"):
            with gate.slot(priority=1, timeout=0.0):
                pass
        duration = time.monotonic() - start
        assert duration < 0.2, f"Expected near-instant timeout, took {duration}s"
    finally:
        release.set()
        t.join(timeout=2.0)


def test_cooperative_priority_gate_foreground_priority_ordering():
    gate = CooperativePriorityGate(foreground_priority=3)
    holder_entered = threading.Event()
    release_holder = threading.Event()
    acquisition_order: list[str] = []

    def holder():
        with gate.slot(priority=1, timeout=2.0):
            holder_entered.set()
            release_holder.wait(timeout=2.0)

    t_holder = threading.Thread(target=holder)
    t_holder.start()
    assert holder_entered.wait(timeout=1.0)

    bg_started = threading.Event()
    def bg_worker():
        bg_started.set()
        with gate.slot(priority=1, timeout=2.0):
            acquisition_order.append("bg")

    fg_started = threading.Event()
    def fg_worker():
        fg_started.set()
        with gate.slot(priority=4, timeout=2.0):
            acquisition_order.append("fg")

    t_bg = threading.Thread(target=bg_worker)
    t_bg.start()
    assert bg_started.wait(timeout=1.0)
    time.sleep(0.05)

    t_fg = threading.Thread(target=fg_worker)
    t_fg.start()
    assert fg_started.wait(timeout=1.0)
    time.sleep(0.05)

    release_holder.set()
    t_holder.join(timeout=2.0)
    t_fg.join(timeout=2.0)
    t_bg.join(timeout=2.0)

    assert acquisition_order == ["fg", "bg"]
