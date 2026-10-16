from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from local_ai_hub.work_fencing import (
    FencingLeaseStore,
    LeaseUnavailableError,
    WorkAttemptFence,
    canonical_resource,
    normalize_paths,
)


def test_normalize_paths_edge_cases() -> None:
    # None paths collection
    with pytest.raises(ValueError, match="writer lease requires at least one exact path"):
        normalize_paths(None)  # type: ignore[arg-type]

    # None or non-string elements in paths collection
    with pytest.raises(ValueError, match="unsafe lease path"):
        normalize_paths([None])  # type: ignore[list-item]

    with pytest.raises(ValueError, match="unsafe lease path"):
        normalize_paths(["valid/path.py", 123])  # type: ignore[list-item]


def test_claim_attempt_rejects_none_types(tmp_path: Path) -> None:
    store = FencingLeaseStore(tmp_path / "fence.sqlite3")

    # None work_id or owner_id must be rejected
    with pytest.raises(ValueError, match="work_id and owner_id must be non-empty strings"):
        store.claim_attempt(tmp_path, work_id=None, owner_id="agent", ttl_seconds=60)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="work_id and owner_id must be non-empty strings"):
        store.claim_attempt(tmp_path, work_id="task-1", owner_id=None, ttl_seconds=60)  # type: ignore[arg-type]


def test_acquire_rejects_none_owner(tmp_path: Path) -> None:
    store = FencingLeaseStore(tmp_path / "fence.sqlite3")
    attempt = store.claim_attempt(tmp_path, work_id="task-1", owner_id="agent", ttl_seconds=60)
    with pytest.raises(ValueError, match="work_id"):
        store.get_active_attempt(tmp_path, 1)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="owner_id must be a non-empty string"):
        store.acquire(tmp_path, owner_id=None, paths=["src/a.py"], ttl_seconds=60, attempt=attempt)  # type: ignore[arg-type]


def test_corrupt_live_lease_paths_json_fails_closed(tmp_path: Path) -> None:
    db_file = tmp_path / "corrupt_fence.sqlite3"
    clock_time = [100.0]
    store = FencingLeaseStore(db_file, clock=lambda: clock_time[0])
    attempt = store.claim_attempt(tmp_path, work_id="task-1", owner_id="agent", ttl_seconds=60)

    # First acquire a valid lease
    lease = store.acquire(tmp_path, owner_id="agent", paths=["src/a.py"], ttl_seconds=60, attempt=attempt)
    assert lease.paths == ("src/a.py",)

    # Corrupt the paths_json in the database
    con = sqlite3.connect(db_file)
    with con:
        con.execute(
            "UPDATE writer_fence_leases SET paths_json = '{invalid json' WHERE lease_id = ?",
            (lease.lease_id,),
        )
    con.close()

    # Corrupt live path ownership must never disappear from overlap checks.
    with pytest.raises(LeaseUnavailableError, match="corrupt path scope"):
        store.is_path_locked(tmp_path, "src/a.py")
    attempt2 = store.claim_attempt(tmp_path, work_id="task-2", owner_id="agent-2", ttl_seconds=60)
    with pytest.raises(LeaseUnavailableError, match="corrupt path scope"):
        store.acquire(tmp_path, owner_id="agent-2", paths=["src/b.py"], ttl_seconds=60, attempt=attempt2)


def test_fencing_lease_store_inspection_and_prune(tmp_path: Path) -> None:
    db_file = tmp_path / "inspect_fence.sqlite3"
    clock_time = [100.0]
    store = FencingLeaseStore(db_file, clock=lambda: clock_time[0])

    # Nothing active initially
    assert store.get_active_attempt(tmp_path, "task-1") is None
    assert store.get_active_leases(tmp_path) == []
    assert store.is_path_locked(tmp_path, "src/a.py") is False

    # Claim attempt and lease
    attempt = store.claim_attempt(tmp_path, work_id="task-1", owner_id="agent-1", ttl_seconds=30)
    lease = store.acquire(tmp_path, owner_id="agent-1", paths=["src/a.py"], ttl_seconds=30, attempt=attempt)

    # Query active
    active_attempt = store.get_active_attempt(tmp_path, "task-1")
    assert active_attempt is not None
    assert active_attempt.work_id == "task-1"
    assert active_attempt.attempt_id == attempt.attempt_id

    active_leases = store.get_active_leases(tmp_path)
    assert len(active_leases) == 1
    assert active_leases[0].lease_id == lease.lease_id

    assert store.is_path_locked(tmp_path, "src/a.py") is True
    assert store.is_path_locked(tmp_path, "src/other.py") is False
    with pytest.raises(ValueError):
        store.is_path_locked(tmp_path, "src/\x00invalid")

    # Advance clock past expiry
    clock_time[0] = 200.0

    # prune_expired should deactivate both
    pruned = store.prune_expired()
    assert pruned >= 2

    assert store.get_active_attempt(tmp_path, "task-1") is None
    assert store.get_active_leases(tmp_path) == []
    assert store.is_path_locked(tmp_path, "src/a.py") is False
