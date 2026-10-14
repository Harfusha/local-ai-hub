from __future__ import annotations

import time
from pathlib import Path
import pytest

from local_ai_hub.leases import ScopeLeaseStore


def test_check_path_unleased_returns_false(tmp_path: Path) -> None:
    store = ScopeLeaseStore(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()

    res = store.check_path("src/module.py", root=str(repo))
    assert res["leased"] is False
    assert res["conflict"] is False
    assert res["tenant"] is None
    assert res["path"] == "src/module.py"


def test_check_path_active_lease_detected(tmp_path: Path) -> None:
    store = ScopeLeaseStore(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()

    # Acquire lease on directory
    acq = store.claim("agent-1", str(repo), ["src/controllers"], ttl_seconds=300, purpose="refactor")
    assert acq["success"] is True

    # Check child path -> should detect lease overlap
    res = store.check_path("src/controllers/auth.py", root=str(repo))
    assert res["leased"] is True
    assert res["tenant"] == "agent-1"
    assert res["purpose"] == "refactor"
    assert res["lease_id"] == acq["lease_id"]


def test_check_path_conflict_flag_relative_to_queried_tenant(tmp_path: Path) -> None:
    store = ScopeLeaseStore(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()

    store.claim("agent-owner", str(repo), ["src/config.py"], ttl_seconds=300)

    # Queried by same tenant -> leased=True, conflict=False
    same_tenant = store.check_path("src/config.py", root=str(repo), tenant="agent-owner")
    assert same_tenant["leased"] is True
    assert same_tenant["conflict"] is False

    # Queried by another tenant -> leased=True, conflict=True
    other_tenant = store.check_path("src/config.py", root=str(repo), tenant="agent-intruder")
    assert other_tenant["leased"] is True
    assert other_tenant["conflict"] is True


def test_check_path_expired_lease_ignored(tmp_path: Path, monkeypatch) -> None:
    store = ScopeLeaseStore(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()

    now = 10000.0
    monkeypatch.setattr(time, "time", lambda: now)
    store.claim("agent-temp", str(repo), ["temp.txt"], ttl_seconds=60)

    # Forward time past TTL
    monkeypatch.setattr(time, "time", lambda: now + 120.0)
    res = store.check_path("temp.txt", root=str(repo))
    assert res["leased"] is False
    assert res["conflict"] is False
