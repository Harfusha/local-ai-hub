from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub import supervisor
from local_ai_hub.supervisor import atomic_json, Supervisor
from local_ai_hub.swarm import SwarmCoordinator, SwarmState


def test_supervisor_atomic_json_edge_cases(tmp_path: Path):
    # Null byte in path
    assert atomic_json(f"{tmp_path}\x00bad.json", {"a": 1}) is False  # type: ignore

    # Non-dict data
    assert atomic_json(tmp_path / "valid.json", "not-a-dict") is False  # type: ignore
    assert atomic_json(tmp_path / "valid.json", None) is False  # type: ignore

    # Valid atomic_json
    target = tmp_path / "data.json"
    assert atomic_json(target, {"ok": True}) is True
    assert target.exists()


def test_swarm_coordinator_edge_cases(tmp_path: Path):
    coordinator = SwarmCoordinator(tmp_path / "swarm.sqlite")

    # Swarm ID validation helper
    assert coordinator.is_valid_swarm_id("swarm_abcdef123456") is True
    assert coordinator.is_valid_swarm_id("bad_prefix") is False
    assert coordinator.is_valid_swarm_id("swarm_\x00bad") is False
    assert coordinator.is_valid_swarm_id(None) is False  # type: ignore

    # Active swarms count
    assert coordinator.active_swarms_count() == 0

    # Dispatch with invalid goal
    with pytest.raises(ValueError, match="invalid goal"):
        coordinator.dispatch(None)  # type: ignore

    with pytest.raises(ValueError, match="invalid goal"):
        coordinator.dispatch("   ")

    with pytest.raises(ValueError, match="invalid goal"):
        coordinator.dispatch("goal with \x00 null byte")

    # Dispatch with null bytes in target_paths
    with pytest.raises(ValueError, match="null bytes"):
        coordinator.dispatch("valid goal", target_paths=["path\x00bad.py"])

    # Valid dispatch
    res = coordinator.dispatch("valid goal", target_paths=["src/a.py"])
    assert res.get("swarm_id")
    assert coordinator.active_swarms_count() == 1
