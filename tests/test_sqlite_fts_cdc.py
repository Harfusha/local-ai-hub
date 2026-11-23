"""Unit tests for Differential SQLite FTS5 Change-Data-Capture."""

import tempfile
from pathlib import Path
from local_ai_hub.sqlite_fts_cdc import SQLiteFTSCDC


def test_sqlite_fts_cdc_lifecycle() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_fts.db"
        engine = SQLiteFTSCDC(db_path)

        # 1. Record changes
        changed1 = engine.record_change(
            doc_id="doc_1",
            path="src/engine.py",
            content="def compute_trajectory(): return 42",
        )
        assert changed1

        # Identical change should be ignored (dirty check)
        changed_duplicate = engine.record_change(
            doc_id="doc_1",
            path="src/engine.py",
            content="def compute_trajectory(): return 42",
        )
        assert not changed_duplicate

        # Record second document
        changed2 = engine.record_change(
            doc_id="doc_2",
            path="src/storage.py",
            content="class MemoryDatabase: pass",
        )
        assert changed2

        # 2. Flush CDC
        flushed = engine.flush_cdc(max_batch=10)
        assert flushed == 2

        # 3. Search FTS5
        results = engine.search("trajectory")
        assert len(results) == 1
        assert results[0].doc_id == "doc_1"
        assert "engine.py" in results[0].path

        results_db = engine.search("Database")
        assert len(results_db) == 1
        assert results_db[0].doc_id == "doc_2"

        # 4. Update doc_1 content
        engine.record_change(
            doc_id="doc_1",
            path="src/engine.py",
            content="def compute_trajectory_v2(): return 100",
        )
        engine.flush_cdc()

        # Search should find new content
        results_v2 = engine.search("trajectory_v2")
        assert len(results_v2) == 1
        assert results_v2[0].doc_id == "doc_1"

        # 5. Delete document
        engine.record_change(doc_id="doc_2", path="src/storage.py", content=None)
        engine.flush_cdc()

        assert len(engine.search("Database")) == 0
