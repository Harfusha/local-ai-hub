from __future__ import annotations

import sqlite3
import queue
import threading
import time
from pathlib import Path

from local_ai_hub.leases import ScopeLeaseStore
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

    blocker_a = store.claim("blocker", str(root_a), ["src/shared.py"], coordination_id=id_a)
    blocker_c = store.claim("blocker", str(root_c), ["src/shared.py"], coordination_id=id_c)
    assert blocker_a["success"] is True
    assert blocker_c["success"] is True
    assert store.claim("waiter", str(root_a), ["src/shared.py"], coordination_id=id_a)["success"] is False
    assert store.claim("waiter", str(root_c), ["src/shared.py"], coordination_id=id_c)["success"] is False

    waits_a = store.waits(str(root_a), coordination_id=id_a)
    waits_c = store.waits(str(root_c), coordination_id=id_c)
    assert [(item["tenant"], item["blocked_by"]) for item in waits_a] == [("waiter", "blocker")]
    assert [(item["tenant"], item["blocked_by"]) for item in waits_c] == [("waiter", "blocker")]

    store.release("blocker", str(blocker_a["lease_id"]))
    assert store.waits(str(root_a), coordination_id=id_a) == []
    assert store.waits(str(root_c), coordination_id=id_c) == waits_c
    reclaimed_a = store.claim("waiter", str(root_a), ["src/shared.py"], coordination_id=id_a)
    assert reclaimed_a["success"] is True
    assert store.waits(str(root_a), coordination_id=id_a) == []
    assert store.waits(str(root_c), coordination_id=id_c) == waits_c


def test_legacy_wait_edges_migrate_to_namespace_inclusive_primary_key(tmp_path: Path) -> None:
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

    store = ScopeLeaseStore(state_dir)
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            "INSERT INTO lease_waits VALUES(?,?,?,?,?)",
            ("waiter", "blocker", "project:other", "src/shared.py", time.time()),
        )
        con.commit()
        rows = con.execute(
            "SELECT root_id FROM lease_waits WHERE tenant='waiter' ORDER BY root_id"
        ).fetchall()
    finally:
        con.close()

    assert rows == [("project:legacy",), ("project:other",)]
    legacy_waits = store.waits(coordination_id="legacy")
    assert len(legacy_waits) == 1
    assert {key: legacy_waits[0][key] for key in ("tenant", "blocked_by", "requested_path")} == {
        "tenant": "waiter", "blocked_by": "blocker", "requested_path": "src/shared.py"
    }


def test_concurrent_legacy_wait_migrations_do_not_rename_over_new_table(tmp_path: Path) -> None:
    state_dir = tmp_path / "concurrent-legacy-state"
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

    dropped_legacy_table = threading.Event()
    allow_rename = threading.Event()
    second_progress: queue.Queue[str] = queue.Queue()
    second_done = threading.Event()
    errors: list[tuple[str, str]] = []

    class PauseBeforeRename(sqlite3.Connection):
        def execute(self, sql: str, parameters=()):
            cursor = super().execute(sql, parameters)
            if sql.strip().upper() == "DROP TABLE LEASE_WAITS":
                dropped_legacy_table.set()
                if not allow_rename.wait(timeout=10):
                    raise TimeoutError("migration interleave was not released")
            return cursor

    class ObserveSecondInitializer(sqlite3.Connection):
        def execute(self, sql: str, parameters=()):
            normalized = " ".join(sql.strip().upper().split())
            if normalized == "BEGIN IMMEDIATE":
                second_progress.put("begin-immediate")
            cursor = super().execute(sql, parameters)
            if normalized.startswith("CREATE TABLE IF NOT EXISTS LEASE_WAITS"):
                second_progress.put("created-lease-waits")
            return cursor

    first = object.__new__(ScopeLeaseStore)
    first.path = db_path
    first._lock = threading.RLock()
    first._initialized = False
    first._connect = lambda: sqlite3.connect(
        db_path, timeout=0.75, isolation_level=None, factory=PauseBeforeRename
    )
    second = object.__new__(ScopeLeaseStore)
    second.path = db_path
    second._lock = threading.RLock()
    second._initialized = False
    second._connect = lambda: sqlite3.connect(
        db_path, timeout=0.75, isolation_level=None, factory=ObserveSecondInitializer
    )

    def initialize(name: str, store: ScopeLeaseStore, *, done: threading.Event | None = None) -> None:
        try:
            store._init_db()
        except BaseException as exc:
            errors.append((name, repr(exc)))
        finally:
            if done is not None:
                done.set()

    first_thread = threading.Thread(target=initialize, args=("first", first))
    second_thread = threading.Thread(
        target=initialize, args=("second", second), kwargs={"done": second_done}
    )
    first_thread.start()
    try:
        assert dropped_legacy_table.wait(timeout=5), "first migration did not reach legacy-table rename"
        second_thread.start()
        progress = second_progress.get(timeout=5)
        assert progress in {"begin-immediate", "created-lease-waits"}
        if progress == "created-lease-waits":
            assert second_done.wait(timeout=5), "second initializer did not finish legacy-table recreation"
    finally:
        allow_rename.set()
        first_thread.join(timeout=10)
        if second_thread.ident is not None:
            second_thread.join(timeout=10)

    assert not first_thread.is_alive(), "first migration thread did not finish"
    assert not second_thread.is_alive(), "second migration thread did not finish"
    assert errors == [], errors

    con = sqlite3.connect(db_path)
    try:
        info = con.execute("PRAGMA table_info(lease_waits)").fetchall()
        primary_key = tuple(str(row[1]) for row in sorted(info, key=lambda row: int(row[5])) if int(row[5]) > 0)
        rows = con.execute(
            "SELECT root_id,tenant,blocked_by,requested_path FROM lease_waits"
        ).fetchall()
    finally:
        con.close()

    assert primary_key == ("root_id", "tenant", "blocked_by", "requested_path")
    assert rows == [("project:legacy", "waiter", "blocker", "src/shared.py")]
