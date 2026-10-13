from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from local_ai_hub.cache import _CommandCacheCoordinator
from local_ai_hub.process_utils import hidden_run_kwargs


def test_cache_constructor_waits_for_other_process_schema_owner(tmp_path):
    database = tmp_path / "cache.sqlite3"
    database.write_bytes(b"corrupt derived database")
    ready = tmp_path / "ready"
    opened = tmp_path / "opened"
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from local_ai_hub.cache import SQLiteCache
database, ready, opened = map(Path, sys.argv[2:])
create = SQLiteCache._create_schema
def mark_open(self):
    opened.touch()
    return create(self)
SQLiteCache._create_schema = mark_open
ready.touch()
SQLiteCache(database, 'independent-namespace')
"""
    coordinator = _CommandCacheCoordinator(database, "sqlite-derived-schema")
    worker = None
    try:
        with coordinator.locked():
            worker = subprocess.Popen(
                [sys.executable, "-B", "-c", script,
                 str(Path(__file__).resolve().parents[1] / "src"),
                 str(database), str(ready), str(opened)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                **hidden_run_kwargs(),
            )
            deadline = time.monotonic() + 5
            while not ready.exists() and worker.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready.exists(), "worker did not reach constructor"
            with pytest.raises(subprocess.TimeoutExpired):
                worker.communicate(timeout=0.25)
            assert not opened.exists(), "constructor opened corrupt SQLite while another owner held the lock"
        output = worker.communicate(timeout=10)
        assert worker.returncode == 0, output
        assert opened.exists()
        with closing(sqlite3.connect(database)) as con:
            assert con.execute("PRAGMA quick_check").fetchone() == ("ok",)
    finally:
        if worker is not None:
            if worker.poll() is None:
                worker.kill()
            worker.communicate(timeout=5)
