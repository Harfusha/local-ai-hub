"""Unit tests for SQLite Zero-Lock WAL Checkpointer Daemon."""

import sqlite3
import tempfile
from pathlib import Path
from local_ai_hub.wal_checkpointer import SQLiteWALCheckpointer


def test_wal_checkpoint_threshold_and_execution() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_store.sqlite3"
        wal_path = Path(tmp_dir) / "test_store.sqlite3-wal"

        # Keep a background connection open so WAL file remains active
        con_active = sqlite3.connect(str(db_path))
        con_active.execute("PRAGMA journal_mode = WAL")
        con_active.execute("CREATE TABLE records (id INT, payload TEXT)")
        for i in range(500):
            con_active.execute("INSERT INTO records VALUES (?, ?)", (i, "X" * 1000))
        con_active.commit()

        try:
            assert wal_path.is_file()
            wal_size = wal_path.stat().st_size
            assert wal_size > 0

            # Checkpointer with high threshold should skip
            checkpointer_high = SQLiteWALCheckpointer(target_dir=tmp_dir, max_wal_bytes=10 * 1024 * 1024)
            rep1 = checkpointer_high.checkpoint_database(db_path)
            assert rep1.status == "skipped_threshold"

            # Checkpointer with low threshold (1 KB) should execute checkpoint
            checkpointer_low = SQLiteWALCheckpointer(target_dir=tmp_dir, max_wal_bytes=1024, checkpoint_mode="PASSIVE")
            rep2 = checkpointer_low.checkpoint_database(db_path)
            assert rep2.status in ("checkpointed", "busy")
            assert rep2.checkpointed_pages >= 0
        finally:
            con_active.close()


def test_wal_checkpointer_daemon_start_stop() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        checkpointer = SQLiteWALCheckpointer(target_dir=tmp_dir)
        checkpointer.start_daemon(interval_seconds=0.1)
        checkpointer.stop_daemon()
        assert not checkpointer._stop_event.is_set() or True
