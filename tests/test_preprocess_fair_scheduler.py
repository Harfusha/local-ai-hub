import sqlite3
import threading
from contextlib import closing

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    db = tmp_path / "projects.sqlite"

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    with closing(connect()) as con:
        con.execute("""CREATE TABLE projects (
            root TEXT PRIMARY KEY, status TEXT, phase TEXT, paused INTEGER DEFAULT 0,
            force_refresh INTEGER DEFAULT 0, last_requested_at REAL DEFAULT 0,
            updated_at REAL DEFAULT 0, retry_after REAL DEFAULT 0, next_check_at REAL DEFAULT 0
        )""")
        con.commit()

    instance = ProjectPreprocessor.__new__(ProjectPreprocessor)
    instance._connect = connect
    instance._db_lock = threading.RLock()
    instance.max_preprocessing_projects = 4
    instance._watcher_active = True
    now = [1_000_000.0]
    monkeypatch.setattr("local_ai_hub.preprocess.time.time", lambda: now[0])
    instance._test_now = now
    return instance, connect


def add(connect, root, phase, *, updated_at, last_requested_at, status="running"):
    with closing(connect()) as con:
        con.execute(
            "INSERT INTO projects(root,status,phase,updated_at,last_requested_at) VALUES(?,?,?,?,?)",
            (root, status, phase, updated_at, last_requested_at),
        )
        con.commit()


def test_active_inventory_precedes_hash_even_when_hash_is_older(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "hash-active", "hash", updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "inventory-active", "inventory", updated_at=now - 10, last_requested_at=now - 5)

    assert instance._next_cpu_project()["root"] == "inventory-active"


def test_active_base_layer_precedes_rag(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "rag-active", "rag", updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "deterministic-active", "deterministic", updated_at=now - 10, last_requested_at=now - 5)

    assert instance._next_cpu_project()["root"] == "deterministic-active"


def test_active_rag_precedes_files_within_second_layer(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "files-active", "files", updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "rag-active", "rag", updated_at=now - 10, last_requested_at=now - 5)

    assert instance._next_cpu_project()["root"] == "rag-active"


def test_active_files_precede_optional_phases(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "modules-active", "modules", updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "files-active", "files", updated_at=now - 10, last_requested_at=now - 5)

    assert instance._next_cpu_project()["root"] == "files-active"


def test_gpu_worker_waits_for_active_cpu_layer(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "files-active", "files", updated_at=now - 5, last_requested_at=now - 5)
    add(connect, "inventory-active", "inventory", updated_at=now - 10, last_requested_at=now - 5)

    assert instance._next_gpu_project() is None


def test_project_expires_at_24_hours_and_foreground_touch_reactivates_it(scheduler, tmp_path):
    instance, connect = scheduler
    now = instance._test_now[0]
    active_root = str(tmp_path / "active")
    inactive_root = str(tmp_path / "inactive")
    (tmp_path / "active").mkdir()
    (tmp_path / "inactive").mkdir()
    add(connect, active_root, "inventory", updated_at=now - 10, last_requested_at=now - 86_400 + 1)
    add(connect, inactive_root, "inventory", updated_at=now - 11, last_requested_at=now - 86_400 - 1)

    assert instance._next_cpu_project()["root"] == active_root

    instance._test_now[0] += 2
    assert instance._next_cpu_project()["root"] == inactive_root

    instance._touch_lock = threading.Lock()
    instance._last_touch = {}
    instance._touch_debounce_seconds = 15.0

    def write_retry(attempt):
        with closing(connect()) as con:
            cur = attempt(con)
            con.commit()
            return cur

    instance._write_retry = write_retry
    assert instance.touch_if_registered(active_root) is True
    assert instance._next_cpu_project()["root"] == active_root


def test_touch_updates_only_matching_absolute_root(scheduler, tmp_path):
    instance, connect = scheduler
    now = instance._test_now[0]
    root_a = str(tmp_path / "project-a")
    root_b = str(tmp_path / "project-b")
    (tmp_path / "project-a").mkdir()
    (tmp_path / "project-b").mkdir()
    old = now - 86_401
    add(connect, root_a, "inventory", updated_at=now - 10, last_requested_at=old)
    add(connect, root_b, "inventory", updated_at=now - 10, last_requested_at=old)
    instance._touch_lock = threading.Lock()
    instance._last_touch = {}
    instance._touch_debounce_seconds = 15.0

    def write_retry(attempt):
        with closing(connect()) as con:
            cur = attempt(con)
            con.commit()
            return cur

    instance._write_retry = write_retry

    assert instance.touch_if_registered(root_a) is True
    with closing(connect()) as con:
        rows = {str(row["root"]): float(row["last_requested_at"]) for row in con.execute(
            "SELECT root,last_requested_at FROM projects"
        )}
    assert rows[root_a] == now
    assert rows[root_b] == old


def test_background_step_does_not_refresh_foreground_activity(scheduler, tmp_path):
    instance, connect = scheduler
    root = str(tmp_path / "repo")
    (tmp_path / "repo").mkdir()
    now = instance._test_now[0]
    add(connect, root, "inventory", updated_at=now - 10, last_requested_at=now - 100)
    instance._background_work_allowed = lambda: True
    instance._yield = lambda: False
    instance._set_project = lambda *_args, **_kwargs: None
    instance._step_inventory = lambda _row: True
    instance.touch_if_registered = lambda _root: pytest.fail("background step refreshed foreground activity")

    assert instance._step({"root": root, "phase": "inventory", "status": "queued"}) is True

    with closing(connect()) as con:
        row = con.execute("SELECT last_requested_at FROM projects WHERE root=?", (root,)).fetchone()
    assert float(row[0]) == now - 100


def test_project_limit_bounds_candidates_and_does_not_skip_locked_head(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "locked-head", "inventory", updated_at=now - 20, last_requested_at=now - 5)
    add(connect, "over-limit", "inventory", updated_at=now - 10, last_requested_at=now - 5)
    instance._rebalance_processing_slots = lambda _con, preferred_root=None: None
    instance._project_limit = lambda: 1
    lock = threading.Lock()
    lock.acquire()
    instance._step_locks_guard = threading.Lock()
    instance._step_locks = {"locked-head": lock}

    try:
        assert instance._next_cpu_project() is None
    finally:
        lock.release()


def test_stale_project_ages_ahead_of_new_active_work(scheduler):
    instance, connect = scheduler
    now = instance._test_now[0]
    add(connect, "new-active", "inventory", updated_at=now - 10, last_requested_at=now - 5)
    add(connect, "aged-inactive", "modules", updated_at=now - 301, last_requested_at=now - 86_401)

    assert instance._next_cpu_project()["root"] == "aged-inactive"
