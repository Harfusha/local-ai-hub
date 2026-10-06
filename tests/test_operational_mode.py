from __future__ import annotations

from local_ai_hub.operational_mode import (
    load_operational_mode,
    operational_mode_gate_error,
    set_operational_mode,
)


def test_missing_state_defaults_active_and_persists_revisions(tmp_path):
    state_dir = tmp_path / "state"

    initial = load_operational_mode(state_dir)
    assert (initial.mode, initial.revision, initial.degraded) == ("active", 0, False)

    maintenance = set_operational_mode("maintenance", state_dir)
    assert (maintenance.mode, maintenance.revision) == ("maintenance", 1)
    assert load_operational_mode(state_dir) == maintenance

    active = set_operational_mode("active", state_dir)
    assert (active.mode, active.revision) == ("active", 2)
    assert load_operational_mode(state_dir) == active


def test_maintenance_and_gaming_gates_preserve_deterministic_reads(tmp_path):
    state_dir = tmp_path / "state"
    set_operational_mode("maintenance", state_dir)
    snapshot = load_operational_mode(state_dir)

    blocked = operational_mode_gate_error(snapshot, "delegate")
    assert blocked is not None
    assert blocked["success"] is False
    assert blocked["error_code"] == "operational_mode_blocked"
    assert blocked["operational_mode"] == "maintenance"
    assert blocked["retryable"] is True
    assert blocked["terminal"] is False
    assert operational_mode_gate_error(
        snapshot,
        "local_ai_repo",
        requires_heavy_work=False,
    ) is None

    set_operational_mode("gaming", state_dir)
    gaming = load_operational_mode(state_dir)
    gaming_blocked = operational_mode_gate_error(gaming, "delegate")
    assert gaming_blocked is not None
    assert gaming_blocked["operational_mode"] == "gaming"
    assert operational_mode_gate_error(gaming, "speculative_lint") is None
