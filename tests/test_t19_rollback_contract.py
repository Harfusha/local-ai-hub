from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_upgrade_rollback_requires_a_matched_code_config_and_durable_state_snapshot() -> None:
    operations = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")

    assert "## Rollback and durable-state recovery" in operations
    assert "stop the Hub service" in operations
    assert "complete configured `server.state_dir`" in operations
    assert "`-wal` and `-shm` files" in operations
    assert "matching Hub configuration, matching state directory" in operations
    assert "Do not run older code against state written by a newer release." in operations
    assert "tools/rollback_snapshot.py create" in operations
    assert "tools/rollback_snapshot.py restore" in operations
    assert "--covers code config state" in operations
    assert "pre-rollback-<id>" in operations
    assert "The installer does not create a Hub code/configuration/state rollback snapshot." in operations
    assert "preserve the current database files and logs" in operations


def test_rollback_snapshot_tool_and_executable_state_restore_coverage_exist() -> None:
    assert (ROOT / "tools" / "rollback_snapshot.py").is_file()
    test_source = (ROOT / "tests" / "test_t19_rollback_snapshot.py").read_text(encoding="utf-8")
    assert "test_rollback_snapshot_restores_code_config_and_sqlite_state" in test_source
    assert "journal_mode=WAL" in test_source
    assert '"-wal"' in test_source
    assert '"-shm"' in test_source
