from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.leases import ScopeLeaseStore


def test_lease_claim_batch_atomic_rollback(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path)
    root = str(tmp_path)

    # Tenant 1 claims file1.py
    r1 = store.claim("tenant-1", root, ["src/file1.py"])
    assert r1["success"] is True

    # Tenant 2 attempts to claim file1.py AND file2.py
    r2 = store.claim_batch("tenant-2", root, ["src/file1.py", "src/file2.py"])
    assert r2["success"] is False
    assert "overlaps" in r2["error"]
    assert len(r2["conflicts"]) == 1

    # Ensure atomic rollback: file2.py must NOT be held by tenant-2
    r3 = store.claim("tenant-3", root, ["src/file2.py"])
    assert r3["success"] is True, "file2.py should have remained free after tenant-2 failed batch"


def test_lease_wait_for_deadlock_detection(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path)
    root = str(tmp_path)

    # Tenant A holds resource 1
    r_a1 = store.claim("tenant-a", root, ["res1.txt"])
    assert r_a1["success"] is True

    # Tenant B holds resource 2
    r_b1 = store.claim("tenant-b", root, ["res2.txt"])
    assert r_b1["success"] is True

    # Tenant A attempts to acquire resource 2 (held by B).
    # This creates dependency edge: tenant-a -> tenant-b
    r_a2 = store.claim("tenant-a", root, ["res2.txt"])
    assert r_a2["success"] is False
    assert r_a2.get("deadlock") is False
    assert len(store.waits(root)) >= 1

    # Now Tenant B attempts to acquire resource 1 (held by A).
    # This would create cycle: tenant-b -> tenant-a -> tenant-b
    r_b2 = store.claim("tenant-b", root, ["res1.txt"])
    assert r_b2["success"] is False
    assert r_b2.get("deadlock") is True
    assert "deadlock detected" in r_b2["error"]
    assert r_b2["cycle"] == ["tenant-b", "tenant-a", "tenant-b"]

    # When Tenant A releases resource 1, dependency is cleared
    store.release("tenant-a")
    waits_after = store.waits(root)
    assert len(waits_after) == 0

    # Tenant B can now acquire resource 1 successfully
    r_b3 = store.claim("tenant-b", root, ["res1.txt"])
    assert r_b3["success"] is True
