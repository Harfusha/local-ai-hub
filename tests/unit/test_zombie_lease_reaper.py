"""Test automatic and explicit reaping of expired zombie leases and wait dependencies."""
import time
from pathlib import Path

import pytest
from local_ai_hub.leases import ScopeLeaseStore


def test_reap_expired_leases_removes_zombies(tmp_path):
    store = ScopeLeaseStore(tmp_path)
    root = str(tmp_path / "repo")
    Path(root).mkdir()

    # Claim lease with very short TTL
    res = store.claim(
        owner="task:reap-expired-zombie", root=root, paths=["src/module.py"],
        ttl_seconds=30, purpose="test expired lease reaping",
    )
    assert res["success"] is True
    lease_id = res["lease_id"]

    # Before expiry, lease is active
    active = store.list(root=root)
    assert any(item["lease_id"] == lease_id for item in active)

    # Simulate future time past expiration (e.g. now + 60s)
    future_time = time.time() + 100
    reap_res = store.reap_expired(now=future_time)
    assert reap_res["success"] is True
    assert reap_res["reaped_leases"] >= 1

    # Lease is now completely reaped from database
    after_reap = store.list(root=root)
    assert not any(item["lease_id"] == lease_id for item in after_reap)


def test_reap_expired_leaves_active_leases_intact(tmp_path):
    store = ScopeLeaseStore(tmp_path)
    root = str(tmp_path / "repo")
    Path(root).mkdir()

    now = time.time()
    # Claim lease with 1 hour TTL
    res = store.claim(
        owner="task:reap-active-lease", root=root, paths=["src/active.py"],
        ttl_seconds=3600, purpose="test active lease preservation",
    )
    assert res["success"] is True
    lease_id = res["lease_id"]

    # Reap with current time
    reap_res = store.reap_expired(now=now)
    assert reap_res["success"] is True
    assert reap_res["reaped_leases"] == 0

    # Active lease is still present
    active = store.list(root=root)
    assert any(item["lease_id"] == lease_id for item in active)
