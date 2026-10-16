from local_ai_hub.priority_gate import CooperativePriorityGate


def test_priority_gate_exposes_active_state_and_configured_priority() -> None:
    gate = CooperativePriorityGate(foreground_priority=5)

    assert gate.is_active is False
    assert gate.status() == {"active": False, "foreground_waiters": 0, "foreground_priority": 5}

    with gate.slot(priority=5, timeout=0):
        assert gate.is_active is True
        assert gate.status()["active"] is True

    assert gate.is_active is False
