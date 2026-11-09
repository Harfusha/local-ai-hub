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
    instance.max_preprocessing_projects = 2
    instance._watcher_active = True
    monkeypatch.setattr("local_ai_hub.preprocess.time.time", lambda: 10000.0)
    return instance, connect


def add(connect, root, status, updated, requested, phase="files"):
    with closing(connect()) as con:
        con.execute("INSERT INTO projects(root,status,phase,updated_at,last_requested_at) VALUES(?,?,?,?,?)",
                    (root, status, phase, updated, requested))
        con.commit()


def test_recent_repository_wins_next_step(scheduler):
    instance, connect = scheduler
    add(connect, "older", "running", 9990, 9000)
    add(connect, "active", "running", 9995, 9999)
    assert instance._next_cpu_project()["root"] == "active"
    assert instance._next_gpu_project()["root"] == "active"


def test_waiting_project_outside_admitted_slots_cannot_run_on_gpu(scheduler):
    instance, connect = scheduler
    instance.max_preprocessing_projects = 1
    add(connect, "active", "running", 9999, 9999, phase="hash")
    add(connect, "waiting", "waiting", 9998, 9000)
    assert instance._next_gpu_project() is None


def test_stale_waiting_project_eventually_gets_slot(scheduler):
    instance, connect = scheduler
    instance.max_preprocessing_projects = 1
    add(connect, "active", "running", 9999, 9999)
    add(connect, "waiting", "waiting", 9600, 9000)
    assert instance._next_cpu_project()["root"] == "waiting"


def test_recent_activity_does_not_permanently_starve_another_project(scheduler, monkeypatch):
    instance, connect = scheduler
    instance.max_preprocessing_projects = 1
    now = [10000.0]
    monkeypatch.setattr("local_ai_hub.preprocess.time.time", lambda: now[0])
    add(connect, "active", "running", 9990, 9999)
    add(connect, "waiting", "waiting", 9990, 9000)
    assert instance._next_cpu_project()["root"] == "active"
    now[0] += 301
    with closing(connect()) as con:
        con.execute("UPDATE projects SET updated_at=?,last_requested_at=? WHERE root='active'", (now[0], now[0]))
        con.commit()
    assert instance._next_cpu_project()["root"] == "waiting"


def test_gpu_does_not_select_a_project_in_retry_cooldown(scheduler):
    instance, connect = scheduler
    add(connect, "cooldown", "error", 9990, 9999)
    with closing(connect()) as con:
        con.execute("UPDATE projects SET retry_after=10100 WHERE root='cooldown'")
        con.commit()
    assert instance._next_gpu_project() is None
