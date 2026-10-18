from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.leases import ScopeLeaseStore


def test_lease_claim_batch_atomic_rollback(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path)
    root = str(tmp_path)

    # Task 1 claims file1.py
    r1 = store.claim(owner="task-1", root=root, paths=["src/file1.py"])
    assert r1["success"] is True

    # Task 2 attempts to claim file1.py AND file2.py
    r2 = store.claim_batch(owner="task-2", root=root, paths=["src/file1.py", "src/file2.py"])
    assert r2["success"] is False
    assert "overlaps" in r2["error"]
    assert len(r2["conflicts"]) == 1

    # Ensure atomic rollback: file2.py must NOT be held by task-2
    r3 = store.claim(owner="task-3", root=root, paths=["src/file2.py"])
    assert r3["success"] is True, "file2.py should have remained free after task-2 failed batch"


def test_lease_wait_for_deadlock_detection(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path)
    root = str(tmp_path)

    # Task A holds resource 1
    r_a1 = store.claim(owner="task-a", root=root, paths=["res1.txt"])
    assert r_a1["success"] is True

    # Task B holds resource 2
    r_b1 = store.claim(owner="task-b", root=root, paths=["res2.txt"])
    assert r_b1["success"] is True

    # Task A attempts to acquire resource 2 (held by B).
    # This creates dependency edge: task-a -> task-b
    r_a2 = store.claim(owner="task-a", root=root, paths=["res2.txt"])
    assert r_a2["success"] is False
    assert r_a2.get("deadlock") is False
    assert len(store.waits(root)) >= 1

    # Now Tenant B attempts to acquire resource 1 (held by A).
    # This would create cycle: task-b -> task-a -> task-b
    r_b2 = store.claim(owner="task-b", root=root, paths=["res1.txt"])
    assert r_b2["success"] is False
    assert r_b2.get("deadlock") is True
    assert "deadlock detected" in r_b2["error"]
    assert r_b2["cycle"] == ["task-b", "task-a", "task-b"]

    # When task A releases resource 1, dependency is cleared
    store.release_owner(owner="task-a")
    waits_after = store.waits(root)
    assert len(waits_after) == 0

    # Task B can now acquire resource 1 successfully
    r_b3 = store.claim(owner="task-b", root=root, paths=["res1.txt"])
    assert r_b3["success"] is True
