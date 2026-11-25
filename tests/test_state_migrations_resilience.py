import hashlib
import json
import os
import sqlite3
import pytest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

from tools.state_migrations import (
    discard_stale_migration_artifacts,
    restore_state_backup,
    run_state_migrations,
    _make_backup,
    _is_process_alive,
    StateMigrationError,
)
from tools.setup import migrate_release_state
from local_ai_hub.state_lifecycle import write_state_version, read_state_version
from tests.test_state_migration_registry import _state_with_v6_agent_schema


def _create_verified_backup(parent: Path, state_name: str, version: int, timestamp_ns: int) -> Path:
    backup = parent / f"{state_name}.backup-v{version}-{timestamp_ns}"
    backup.mkdir(parents=True, exist_ok=True)
    write_state_version(backup, version=version)
    ver_file = backup / "state_version.json"
    ver_hash = hashlib.sha256(ver_file.read_bytes()).hexdigest()
    manifest = {
        "format": 1,
        "kind": "state_migration_backup",
        "source_version": version,
        "timestamp_ns": timestamp_ns,
        "files": {
            "state_version.json": {"sha256": ver_hash, "size_bytes": ver_file.stat().st_size}
        }
    }
    (backup / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return backup


def test_spoofed_prefix_dir_is_not_deleted(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=6)

    # Spoofed directory matching backup name prefix but without valid manifest
    spoofed = tmp_path / "state.backup-v6-1795512446287817100"
    spoofed.mkdir()
    (spoofed / "user_data.txt").write_text("critical data", encoding="utf-8")

    removed = discard_stale_migration_artifacts(state)

    assert removed == []
    assert spoofed.is_dir()
    assert (spoofed / "user_data.txt").read_text(encoding="utf-8") == "critical data"


def test_partial_or_corrupt_manifest_is_not_deleted(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=6)

    # Backup with invalid manifest JSON
    corrupt1 = tmp_path / "state.backup-v6-1795512446287817100"
    corrupt1.mkdir()
    (corrupt1 / "manifest.json").write_text("{bad json", encoding="utf-8")

    # Backup with wrong manifest kind
    corrupt2 = tmp_path / "state.backup-v6-1795512446287817200"
    corrupt2.mkdir()
    (corrupt2 / "manifest.json").write_text('{"format": 1, "kind": "unknown"}', encoding="utf-8")

    # Backup where file size doesn't match manifest
    corrupt3 = tmp_path / "state.backup-v6-1795512446287817300"
    corrupt3.mkdir()
    (corrupt3 / "state_version.json").write_text('{"version": 6}', encoding="utf-8")
    (corrupt3 / "manifest.json").write_text(json.dumps({
        "format": 1,
        "kind": "state_migration_backup",
        "source_version": 6,
        "timestamp_ns": 1795512446287817300,
        "files": {"state_version.json": {"sha256": "fake", "size_bytes": 99999}}
    }), encoding="utf-8")

    removed = discard_stale_migration_artifacts(state)

    assert removed == []
    assert corrupt1.is_dir()
    assert corrupt2.is_dir()
    assert corrupt3.is_dir()


def test_active_staging_directory_with_running_pid_is_not_deleted(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=6)

    stage = tmp_path / ".state.migration-active"
    stage.mkdir()
    # Use current process PID which is guaranteed alive
    (stage / ".migration_lock.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    (stage / "data.tmp").write_text("in progress", encoding="utf-8")

    removed = discard_stale_migration_artifacts(state)

    assert removed == []
    assert stage.is_dir()


def test_stale_staging_directory_with_dead_pid_is_deleted(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=6)

    stage = tmp_path / ".state.migration-stale"
    stage.mkdir()
    (stage / ".migration_lock.json").write_text(json.dumps({"pid": 99999999}), encoding="utf-8")
    (stage / "data.tmp").write_text("abandoned", encoding="utf-8")

    removed = discard_stale_migration_artifacts(state)

    assert removed == [str(stage)]
    assert not stage.exists()


def test_retention_policy_never_deletes_single_recovery_snapshot(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=6)

    # Only one verified backup exists
    single_backup = _create_verified_backup(tmp_path, "state", 6, 1795512446287817100)

    removed = discard_stale_migration_artifacts(state, retention_count=1)

    assert removed == []
    assert single_backup.is_dir()


def test_retention_policy_prunes_older_verified_backups_exceeding_retention(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=6)

    b1 = _create_verified_backup(tmp_path, "state", 6, 1000)
    b2 = _create_verified_backup(tmp_path, "state", 6, 2000)
    b3 = _create_verified_backup(tmp_path, "state", 6, 3000)

    # retention_count=1 -> keep newest (b3), prune b1 and b2
    removed = discard_stale_migration_artifacts(state, retention_count=1)

    assert set(removed) == {str(b1), str(b2)}
    assert not b1.exists()
    assert not b2.exists()
    assert b3.is_dir()


def test_restore_state_backup_refuses_corrupted_manifest_file(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=6)

    backup = _create_verified_backup(tmp_path, "state", 6, 1000)
    # Corrupt a file in the backup
    (backup / "state_version.json").write_text('{"corrupted": true}', encoding="utf-8")

    with pytest.raises(OSError, match="verification failed"):
        restore_state_backup(state, backup)


def test_disk_space_preflight_blocks_backup_if_insufficient_space(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=6)

    with patch("tools.state_migrations.shutil.disk_usage", return_value=type("Usage", (), {"free": 100})()):
        with pytest.raises(OSError, match="insufficient disk space"):
            _make_backup(state, 6)


def test_sqlite_wal_checkpoint_and_quickcheck_in_backup(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    write_state_version(state, version=6)
    db_file = state / "test_data.sqlite3"
    con = sqlite3.connect(db_file)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE items (id INT, val TEXT)")
        con.execute("INSERT INTO items VALUES (1, 'alpha'), (2, 'beta')")
        con.commit()

        # Sidecar file should be ignored during backup in favor of SQLite backup API
        wal_file = state / "test_data.sqlite3-wal"
        if not wal_file.exists():
            wal_file.write_bytes(b"dummy uncheckpointed wal bytes")

        backup = _make_backup(state, 6)
        assert backup.is_dir()
        assert (backup / "manifest.json").is_file()

        # Verify backup database is healthy and has all records
        with closing(sqlite3.connect(backup / "test_data.sqlite3")) as backup_con:
            assert backup_con.execute("PRAGMA quick_check").fetchone() == ("ok",)
            rows = backup_con.execute("SELECT id, val FROM items ORDER BY id").fetchall()
            assert rows == [(1, "alpha"), (2, "beta")]
    finally:
        con.close()


def test_migrate_release_state_creates_backup_on_existing_state(tmp_path: Path):
    state = tmp_path / "state"
    _state_with_v6_agent_schema(state)

    result = migrate_release_state(state, create_backup=True)

    assert result["status"] == "migrated"
    assert len(result["backups"]) == 1
    backup_path = Path(result["backups"][0])
    assert backup_path.is_dir()
    assert (backup_path / "manifest.json").is_file()


def test_migrate_release_state_unbacked_mode_skips_backup_when_requested(tmp_path: Path):
    state = tmp_path / "state"
    _state_with_v6_agent_schema(state)

    result = migrate_release_state(state, create_backup=False)

    assert result["status"] == "migrated"
    assert result["backups"] == []
    assert not list(tmp_path.glob("state.backup-v*"))

