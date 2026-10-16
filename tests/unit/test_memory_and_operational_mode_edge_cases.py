from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.memory import WorkspaceMemoryStore
from local_ai_hub.operational_mode import (
    OperationalModeSnapshot,
    is_valid_operational_mode,
    load_operational_mode,
    operational_mode_gate_error,
    set_operational_mode,
)


def test_workspace_memory_store_nan_inf_bool_surrogates_and_helpers(tmp_path: Path) -> None:
    store = WorkspaceMemoryStore(
        tmp_path / "state",
        default_ttl_hours=float("nan"),  # type: ignore[arg-type]
        max_value_chars=float("inf"),  # type: ignore[arg-type]
    )
    assert store.default_ttl == 168 * 3600
    assert store.max_value_chars == 6000
    assert store.count() == 0

    bool_store = WorkspaceMemoryStore(
        tmp_path / "state_bool",
        default_ttl_hours=False,  # type: ignore[arg-type]
        max_value_chars=False,  # type: ignore[arg-type]
    )
    assert bool_store.default_ttl == 168 * 3600
    assert bool_store.max_value_chars == 6000

    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError, match="memo key"):
        store.put(str(repo), "\x00  \x00", "valid", "tenant-a")

    with pytest.raises(ValueError, match="memo tenant"):
        store.put(str(repo), "valid-key", "valid", "\x00  ")

    with pytest.raises(ValueError, match="memo value"):
        store.put(str(repo), "valid-key", "\x00  \x00", "tenant-a")

    put_res = store.put(
        str(repo),
        "  key\x00-1  ",
        "value with surrogate \ud800 and null \x00 byte",
        "  ten\x00ant-a  ",
        ttl_seconds=float("nan"),  # type: ignore[arg-type]
        metadata={"path": Path("a/b"), "text": "meta\ud800\x00"},
    )
    assert put_res["success"] is True
    assert put_res["key"] == "key-1"
    assert put_res["tenant"] == "tenant-a"
    assert put_res["expires_in_seconds"] == store.default_ttl
    assert store.count() == 1
    assert store.count(str(repo)) == 1

    fetched = store.get(str(repo), "key\x00-1")
    assert fetched["success"] is True
    assert "\x00" not in fetched["value"]
    assert "\ud800" not in fetched["value"]
    assert isinstance(fetched["metadata"], dict)

    search_nan = store.search(
        str(repo),
        query=None,  # type: ignore[arg-type]
        limit=float("nan"),  # type: ignore[arg-type]
    )
    assert search_nan["success"] is True
    assert len(search_nan["results"]) == 1

    search_bool = store.search(
        str(repo),
        query=True,  # type: ignore[arg-type]
        limit=False,  # type: ignore[arg-type]
    )
    assert search_bool["success"] is True
    assert len(search_bool["results"]) == 1

    store.clear(str(repo))
    assert store.count(str(repo)) == 0
    assert store.count() == 0


def test_operational_mode_helpers_and_gate_error_resilience(tmp_path: Path) -> None:
    assert is_valid_operational_mode("active") is True
    assert is_valid_operational_mode("  GAMING\x00 ") is True
    assert is_valid_operational_mode("maintenance") is True
    assert is_valid_operational_mode("invalid") is False
    assert is_valid_operational_mode(True) is False
    assert is_valid_operational_mode(None) is False

    snap = load_operational_mode(tmp_path / "state")
    assert snap.is_active() is True
    assert snap.is_gaming() is False
    assert snap.is_maintenance() is False
    assert snap.is_healthy() is True

    gaming_snap = set_operational_mode(tmp_path / "state", "gaming")
    assert gaming_snap.is_gaming() is True
    assert gaming_snap.is_active() is False
    assert gaming_snap.is_healthy() is True

    # Null bytes and non-string action in operational_mode_gate_error
    assert operational_mode_gate_error(gaming_snap, "  status\x00 ") is None
    err = operational_mode_gate_error(gaming_snap, None)  # type: ignore[arg-type]
    assert err is not None
    assert err["action"] == ""

    err_null = operational_mode_gate_error(gaming_snap, "  heavy-task\x00 ")
    assert err_null is not None
    assert err_null["action"] == "heavy_task"

    degraded = OperationalModeSnapshot("maintenance", 0, None, degraded=True, error="bad")
    assert degraded.is_maintenance() is True
    assert degraded.is_healthy() is False
