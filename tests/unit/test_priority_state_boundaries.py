from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType

import pytest

from local_ai_hub import state_paths
from local_ai_hub.priority_gate import CooperativePriorityGate


class FakeCondition:
    def __init__(self, on_wait: Callable[[], None] | None = None):
        self.wait_calls = []
        self.notify_calls = 0
        self.on_wait = on_wait

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self.on_wait is not None:
            self.on_wait()

    def notify_all(self):
        self.notify_calls += 1


def test_priority_gate_zero_timeout_admits_free_slot_without_waiting():
    gate = CooperativePriorityGate()
    condition = FakeCondition()
    gate._cond = condition

    with gate.slot(priority=3, timeout=0):
        assert gate.status() == {"active": True, "foreground_waiters": 0, "foreground_priority": 3}

    assert condition.wait_calls == []
    assert gate.status() == {"active": False, "foreground_waiters": 0, "foreground_priority": 3}
    assert condition.notify_calls == 1


def test_priority_gate_zero_timeout_fails_immediately_when_busy():
    gate = CooperativePriorityGate()
    condition = FakeCondition()
    gate._cond = condition
    gate._active = True

    with pytest.raises(TimeoutError):
        with gate.slot(priority=3, timeout=0):
            pytest.fail("busy zero-timeout slot must not be entered")

    assert condition.wait_calls == []
    assert gate.status() == {"active": True, "foreground_waiters": 0, "foreground_priority": 3}


@pytest.mark.parametrize(
    "timeout_factory",
    [
        lambda: None,
        lambda: True,
        lambda: float("nan"),
        lambda: float("inf"),
        lambda: float("-inf"),
        lambda: 10**10000,
        lambda: "1",
        lambda: -0.1,
        lambda: object(),
    ],
    ids=["none", "bool", "nan", "positive-infinity", "negative-infinity", "overflow", "string", "negative", "nonnumeric"],
)
def test_priority_gate_invalid_timeout_does_not_change_state_or_waiters(timeout_factory):
    gate = CooperativePriorityGate()
    condition = FakeCondition()
    gate._cond = condition
    gate._active = True
    gate._foreground_waiters = 2

    with pytest.raises(ValueError):
        with gate.slot(priority=3, timeout=timeout_factory()):
            pytest.fail("invalid timeout must be rejected before slot entry")

    assert condition.wait_calls == []
    assert gate.status() == {"active": True, "foreground_waiters": 2, "foreground_priority": 3}


def test_priority_gate_caps_condition_waits_to_thirty_seconds():
    gate = CooperativePriorityGate()
    gate._active = True
    condition = FakeCondition(on_wait=lambda: setattr(gate, "_active", False))
    gate._cond = condition

    with gate.slot(priority=3, timeout=120):
        assert gate.status() == {"active": True, "foreground_waiters": 0, "foreground_priority": 3}

    assert condition.wait_calls == [pytest.approx(30.0)]


def test_priority_gate_body_exception_releases_slot():
    gate = CooperativePriorityGate()
    condition = FakeCondition()
    gate._cond = condition

    with pytest.raises(RuntimeError, match="body failed"):
        with gate.slot(priority=3, timeout=0):
            raise RuntimeError("body failed")

    assert gate.status() == {"active": False, "foreground_waiters": 0, "foreground_priority": 3}
    assert condition.notify_calls == 1


@pytest.mark.parametrize(
    ("config", "error_type"),
    [
        ([], TypeError),
        ({"server": []}, TypeError),
        ({"server": {"state_dir": True}}, TypeError),
        ({"server": {"state_dir": 7}}, TypeError),
        ({"server": {"state_dir": "bad\x00path"}}, ValueError),
    ],
    ids=["invalid-root", "invalid-server", "boolean-path", "numeric-path", "nul-path"],
)
def test_configured_state_dir_rejects_invalid_values_before_filesystem_changes(
    config, error_type, monkeypatch
):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("invalid config reached filesystem mutation")

    monkeypatch.setattr(state_paths.tempfile, "mkdtemp", fail_if_called)
    monkeypatch.setattr(Path, "mkdir", fail_if_called)

    with pytest.raises(error_type):
        state_paths.configured_state_dir(config)


def test_configured_state_dir_accepts_read_only_mapping_and_preserves_path_spaces(tmp_path):
    state_dir = tmp_path / "  state directory  "
    config = MappingProxyType(
        {"server": MappingProxyType({"state_dir": str(state_dir)})}
    )

    result = state_paths.configured_state_dir(config)

    assert result == state_dir
    assert result.is_dir()
