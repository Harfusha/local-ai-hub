"""Operational mode exceptions use exact canonical actions and booleans."""

import pytest

from local_ai_hub.operational_mode import (
    OperationalModeSnapshot,
    is_valid_operational_mode,
    load_operational_mode,
    operational_mode_gate_error,
    set_operational_mode,
)


@pytest.mark.parametrize("action", ["status", "wait", "result", "cancel", "evaluation_report"])
def test_exact_safe_action_remains_available_while_gaming(action):
    assert operational_mode_gate_error(OperationalModeSnapshot("gaming", 1, None), action) is None


@pytest.mark.parametrize("action", ["STATUS", " status", "status ", "sta\x00tus", "evaluation-report", None, 1, False])
def test_malformed_action_cannot_inherit_gaming_exception(action):
    result = operational_mode_gate_error(OperationalModeSnapshot("gaming", 1, None), action)
    assert result["success"] is False
    assert result["error_code"] == "operational_mode_blocked"
    assert result["mode"] == "gaming"


@pytest.mark.parametrize("value", [0, 1, "false", None, []])
def test_heavy_work_flag_cannot_be_coerced_into_read_only_exception(value):
    with pytest.raises(ValueError, match="boolean"):
        operational_mode_gate_error(OperationalModeSnapshot("gaming", 1, None), "delegate", requires_heavy_work=value)


def test_valid_read_only_and_active_work_are_unchanged():
    assert operational_mode_gate_error(OperationalModeSnapshot("gaming", 1, None), "search", requires_heavy_work=False) is None
    assert operational_mode_gate_error(OperationalModeSnapshot("active", 1, None), "delegate") is None


@pytest.mark.parametrize("snapshot", [None, OperationalModeSnapshot("maintenance", 1, None),
                                      OperationalModeSnapshot("gaming", 1, None, degraded=True)])
def test_safe_actions_do_not_bypass_maintenance_or_degraded_state(snapshot):
    assert operational_mode_gate_error(snapshot, "status")["success"] is False


@pytest.mark.parametrize("mode", ["active", "gaming", "maintenance"])
def test_canonical_mode_validator_accepts_supported_values(mode):
    assert is_valid_operational_mode(mode)


@pytest.mark.parametrize("mode", ["ACTIVE", "Gaming", " active", "active ", "act\x00ive", None, True, 1])
def test_mode_validator_does_not_normalize_aliases(mode):
    assert not is_valid_operational_mode(mode)


def test_null_state_path_is_rejected_without_storage_writes(tmp_path):
    path = str(tmp_path / "uncreated") + "\x00"
    assert load_operational_mode(path).degraded
    with pytest.raises(ValueError):
        set_operational_mode(path, "active")
    assert not list(tmp_path.iterdir())


def test_mode_subclass_cannot_impersonate_canonical_member(tmp_path):
    class ImpersonatedMode(str):
        def __hash__(self):
            return hash("active")

        def __eq__(self, other):
            return True

    mode = ImpersonatedMode("retired-mode")
    assert not is_valid_operational_mode(mode)
    with pytest.raises(ValueError):
        set_operational_mode(tmp_path, mode)
    assert not list(tmp_path.iterdir())
