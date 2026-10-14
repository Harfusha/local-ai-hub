from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
import pytest
from local_ai_hub.sqlite_support import (
    backup_durable_database,
    rotate_database_backups,
)


def test_rotate_database_backups_prunes_excess_snapshots(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    # Create live database
    live_db = state_dir / "agent_state.sqlite"
    live_db.write_text("live db content", encoding="utf-8")

    # Create 6 backup snapshots for agent_state
    now = time.time()
    created_backups = []
    for i in range(6):
        b = state_dir / f"agent_state.sqlite.path-migration-{1_000_000_000_000_000_000 + i}.sqlite3"
        b.write_text(f"backup {i}", encoding="utf-8")
        # Ensure distinct mtimes
        mtime = now - (60 * (10 - i))
        os.utime(b, (mtime, mtime))
        created_backups.append(b)

    # Create 4 .bak files for deterministic
    bak_files = []
    for i in range(4):
        b = state_dir / f"deterministic.sqlite3.migration-v0-v1-{i:032x}.bak"
        b.write_text(f"bak {i}", encoding="utf-8")
        mtime = now - (60 * (10 - i))
        os.utime(b, (mtime, mtime))
        bak_files.append(b)

    # Rotate with max_copies=3
    pruned = rotate_database_backups(state_dir, max_copies=3)

    assert len(pruned) >= 4  # 3 from agent_state + 1 from deterministic
    # Live db must remain intact
    assert live_db.exists()

    # Remaining backups for agent_state should be exactly 3 newest (indices 3, 4, 5)
    remaining_agent = sorted(state_dir.glob("agent_state.sqlite.path-migration-*.sqlite3"))
    assert len(remaining_agent) == 3
    assert remaining_agent == [created_backups[3], created_backups[4], created_backups[5]]

    # Remaining bak files for deterministic should be exactly 3 newest (indices 1, 2, 3)
    remaining_bak = sorted(state_dir.glob("deterministic.sqlite3.migration-v0-v1-*.bak"))
    assert len(remaining_bak) == 3
    assert remaining_bak == [bak_files[1], bak_files[2], bak_files[3]]


def test_backup_durable_database_auto_rotates(tmp_path: Path) -> None:
    db_path = tmp_path / "test_durable.sqlite"
    con = sqlite3.connect(db_path)
    try:
        con.execute("CREATE TABLE t (id INT)")
        con.commit()
    finally:
        con.close()

    # Create 5 backups
    backups = []
    for i in range(5):
        b = backup_durable_database(db_path)
        backups.append(b)
        time.sleep(0.01)

    # After 5 backups, automated rotation should keep at most 3
    existing_backups = [p for p in tmp_path.glob("test_durable.sqlite.*.sqlite3") if p.exists()]
    assert len(existing_backups) <= 3
    # The newest backup must exist
    assert backups[-1].exists()
    assert backups[-2].exists()
    assert backups[-3].exists()
    # The oldest backup must have been rotated away
    assert not backups[0].exists()


def test_rotate_database_backups_prunes_by_max_age(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    now = time.time()
    # 1 old backup (10 days old)
    old_b = state_dir / "app.sqlite.path-migration-1000000000000000000.sqlite3"
    old_b.write_text("old", encoding="utf-8")
    t_old = now - (10 * 86400)
    os.utime(old_b, (t_old, t_old))

    # 1 fresh backup (1 hour old)
    fresh_b = state_dir / "app.sqlite.path-migration-1000000000000000001.sqlite3"
    fresh_b.write_text("fresh", encoding="utf-8")
    t_fresh = now - 3600
    os.utime(fresh_b, (t_fresh, t_fresh))

    # Rotate with 7-day max_age
    pruned = rotate_database_backups(state_dir, max_copies=3, max_age_seconds=7 * 86400)

    assert old_b in pruned
    assert not old_b.exists()
    assert fresh_b.exists()


def test_rotate_database_backups_cleans_wal_shm_sidecars(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    now = time.time()
    # Create 4 backups so 1 gets pruned with max_copies=3
    files = []
    for i in range(4):
        b = state_dir / f"db.sqlite.path-migration-{1_000_000_000_000_000_000 + i}.sqlite3"
        b.write_text("db", encoding="utf-8")
        wal = Path(f"{b}-wal")
        wal.write_text("wal", encoding="utf-8")
        shm = Path(f"{b}-shm")
        shm.write_text("shm", encoding="utf-8")
        t = now - 100 * (4 - i)
        os.utime(b, (t, t))
        files.append((b, wal, shm))

    pruned = rotate_database_backups(state_dir, max_copies=3)

    # files[0] should be pruned along with its wal and shm
    oldest_b, oldest_wal, oldest_shm = files[0]
    assert oldest_b in pruned
    assert not oldest_b.exists()
    assert not oldest_wal.exists()
    assert not oldest_shm.exists()

    # Newer files remain
    assert files[-1][0].exists()
    assert files[-1][1].exists()
    assert files[-1][2].exists()


def test_rotate_database_backups_handles_missing_dir(tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist"
    assert rotate_database_backups(non_existent) == []


def test_rotation_only_prunes_verified_helper_backups(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    live_db = state_dir / "agent_state.sqlite"
    connection = sqlite3.connect(live_db)
    try:
        connection.execute("CREATE TABLE state (value TEXT)")
        connection.execute("INSERT INTO state VALUES ('live')")
    finally:
        connection.close()

    backups = [backup_durable_database(live_db) for _ in range(3)]
    foreign = state_dir / "agent_state.sqlite.notes"
    foreign.write_text("keep", encoding="utf-8")
    journal = state_dir / "agent_state.sqlite-journal"
    journal.write_text("active journal", encoding="utf-8")
    old = time.time() - 60
    os.utime(foreign, (old, old))
    os.utime(journal, (old, old))

    pruned = rotate_database_backups(state_dir, prefix=live_db.name, max_copies=1)

    assert len(pruned) == 2
    assert foreign.exists()
    assert journal.exists()
    assert live_db.exists()
    assert sum(path.exists() for path in backups) == 1
