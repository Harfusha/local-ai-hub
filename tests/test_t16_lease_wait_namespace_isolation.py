from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.sqlite_support import UnsupportedLegacyStateDatabase
from local_ai_hub.process_utils import run_hidden
from local_ai_hub.project_config import resolve_project_context


def _repository(parent: Path, name: str) -> Path:
    root = parent / name
    (root / "src").mkdir(parents=True)
    (root / "src" / "shared.py").write_text("baseline\n", encoding="utf-8")
    (root / ".local-ai.toml").write_text('shared_namespace = "team"\n', encoding="utf-8")
    run_hidden(["git", "init", "--quiet", str(root)], check=True, capture_output=True, text=True, timeout=10)
    run_hidden(["git", "-C", str(root), "add", ".local-ai.toml", "src/shared.py"], check=True, capture_output=True, text=True, timeout=10)
    run_hidden(
        ["git", "-C", str(root), "-c", "user.name=Lease Fixture", "-c", "user.email=lease-fixture@example.invalid", "commit", "--quiet", "-m", "lease fixture"],
        check=True, capture_output=True, text=True, timeout=10,
    )
    return root


def test_wait_edges_and_release_cleanup_are_scoped_by_repository_namespace(tmp_path: Path) -> None:
    root_a = _repository(tmp_path, "wait-project-a")
    root_c = _repository(tmp_path, "wait-project-c")
    state_dir = tmp_path / "state"
    id_a = resolve_project_context(root_a, state_dir).coordination_id
    id_c = resolve_project_context(root_c, state_dir).coordination_id
    assert id_a and id_c and id_a != id_c
    store = ScopeLeaseStore(state_dir)

    blocker_a = store.claim(owner="blocker", root=str(root_a), paths=["src/shared.py"], coordination_id=id_a)
    blocker_c = store.claim(owner="blocker", root=str(root_c), paths=["src/shared.py"], coordination_id=id_c)
    assert blocker_a["success"] is True
    assert blocker_c["success"] is True
    assert store.claim(owner="waiter", root=str(root_a), paths=["src/shared.py"], coordination_id=id_a)["success"] is False
    assert store.claim(owner="waiter", root=str(root_c), paths=["src/shared.py"], coordination_id=id_c)["success"] is False

    waits_a = store.waits(str(root_a), coordination_id=id_a)
    waits_c = store.waits(str(root_c), coordination_id=id_c)
    assert [(item["owner"], item["blocked_by"]) for item in waits_a] == [("waiter", "blocker")]
    assert [(item["owner"], item["blocked_by"]) for item in waits_c] == [("waiter", "blocker")]

    store.release(owner="blocker", lease_id=str(blocker_a["lease_id"]))
    assert store.waits(str(root_a), coordination_id=id_a) == []
    assert store.waits(str(root_c), coordination_id=id_c) == waits_c
    reclaimed_a = store.claim(owner="waiter", root=str(root_a), paths=["src/shared.py"], coordination_id=id_a)
    assert reclaimed_a["success"] is True
    assert store.waits(str(root_a), coordination_id=id_a) == []
    assert store.waits(str(root_c), coordination_id=id_c) == waits_c


def test_standalone_legacy_wait_edges_reject_without_writes(tmp_path: Path) -> None:
    state_dir = tmp_path / "legacy-state"
    state_dir.mkdir()
    db_path = state_dir / "leases.sqlite3"
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            "CREATE TABLE lease_waits (tenant TEXT NOT NULL, blocked_by TEXT NOT NULL, "
            "root_id TEXT NOT NULL, requested_path TEXT NOT NULL, updated_at REAL NOT NULL, "
            "PRIMARY KEY(tenant,blocked_by,requested_path))"
        )
        con.execute(
            "INSERT INTO lease_waits VALUES(?,?,?,?,?)",
            ("waiter", "blocker", "project:legacy", "src/shared.py", time.time()),
        )
        con.commit()
    finally:
        con.close()

    before = db_path.read_bytes()
    with pytest.raises(UnsupportedLegacyStateDatabase, match="unsupported legacy durable state database"):
        ScopeLeaseStore(state_dir)
    assert db_path.read_bytes() == before
    assert not (state_dir / "agent_state.sqlite").exists()
    assert not list(state_dir.glob("*-wal"))
    assert not list(state_dir.glob("*-shm"))


def test_concurrent_canonical_wait_initialization_preserves_namespace_rows(tmp_path: Path) -> None:
    state_dir = tmp_path / "concurrent-state"
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src/shared.py").write_text("baseline\n", encoding="utf-8")
    barrier = threading.Barrier(2, timeout=5)
    errors: list[BaseException] = []
    results = {}

    def initialize(namespace: str) -> None:
        try:
            barrier.wait()
            store = ScopeLeaseStore(state_dir)
            assert store.claim(owner="blocker", root=str(root), paths=["src/shared.py"], coordination_id=namespace)["success"] is True
            assert store.claim(owner="waiter", root=str(root), paths=["src/shared.py"], coordination_id=namespace)["success"] is False
            results[namespace] = store.waits(str(root), coordination_id=namespace)
        except BaseException as exc:
            errors.append(exc)

    workers = [threading.Thread(target=initialize, args=(namespace,), daemon=True) for namespace in ("first", "second")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
    assert not any(worker.is_alive() for worker in workers), "canonical initialization worker did not finish"
    assert errors == [], errors
    assert set(results) == {"first", "second"}
    assert all(len(waits) == 1 and waits[0]["owner"] == "waiter" for waits in results.values())

    con = sqlite3.connect(state_dir / "agent_state.sqlite")
    try:
        info = con.execute("PRAGMA table_info(lease_waits)").fetchall()
        primary_key = tuple(str(row[1]) for row in sorted(info, key=lambda row: int(row[5])) if int(row[5]) > 0)
        rows = con.execute(
            "SELECT root_id,owner,blocked_by,requested_path FROM lease_waits"
        ).fetchall()
    finally:
        con.close()

    assert primary_key == ("root_id", "owner", "blocked_by", "requested_path")
    assert sorted(rows) == [
        ("project:first", "waiter", "blocker", "src/shared.py"),
        ("project:second", "waiter", "blocker", "src/shared.py"),
    ]
    assert not (state_dir / "leases.sqlite3").exists()
