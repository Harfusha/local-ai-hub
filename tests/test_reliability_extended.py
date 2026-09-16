from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.config import load_config
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_state import RepoStateTracker
from local_ai_hub.repo_tools import RepositoryTools


def _config(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        f'''[server]\nstate_dir="{(tmp_path / 'state').as_posix()}"\n[hardware]\nprofile="cpu"\nauto_tune=false\n[prewarm]\nenabled=false\n[preprocessing]\nenabled=false\nfs_watcher_enabled=false\nsqlite_busy_timeout_seconds=0.05\nsqlite_write_retries=5\n[workspace_cache]\nfingerprint_ttl_seconds=0.1\ngit_probe_timeout_seconds=0.1\ngit_status_timeout_seconds=0.1\nslow_git_cooldown_seconds=2\n''',
        encoding="utf-8",
    )
    return load_config(str(path))


class _Rag:
    index_reset = False
    def workspace_id(self, root): return "w"


class _Scheduler:
    def foreground_busy(self): return False
    def background_allowed(self): return True
    def note_background_yield(self): pass


class _Noop:
    def __getattr__(self, name): return lambda *a, **k: None


def test_repo_state_git_timeout_degrades_instead_of_raising(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "repo"; repo.mkdir(); (repo / "a.py").write_text("x=1\n", encoding="utf-8")
    tracker = RepoStateTracker(_config(tmp_path))

    def fake_git(root: Path, *args: str, timeout: float = 8.0):
        if args[:2] == ("rev-parse", "--is-inside-work-tree"):
            return subprocess.CompletedProcess([], 0, b"true\n", b"")
        if args[:2] == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess([], 0, b"abc123\n", b"")
        raise subprocess.TimeoutExpired(["git", *args], timeout)

    monkeypatch.setattr(tracker, "_run_git", fake_git)
    started = time.perf_counter()
    state = tracker.fingerprint(str(repo), force=True)
    elapsed = time.perf_counter() - started
    assert state["success"] is True
    assert state["degraded"] is True
    assert "timed out" in state["degraded_reason"]
    assert elapsed < 0.5


def test_repo_state_dirty_signature_changes_without_hashing_file_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "repo"; repo.mkdir(); source = repo / "a.py"; source.write_text("x=1\n", encoding="utf-8")
    tracker = RepoStateTracker(_config(tmp_path))

    def fake_git(root: Path, *args: str, timeout: float = 8.0):
        if args[:2] == ("rev-parse", "--is-inside-work-tree"):
            return subprocess.CompletedProcess([], 0, b"true\n", b"")
        if args[:2] == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess([], 0, b"abc123\n", b"")
        return subprocess.CompletedProcess([], 0, b" M a.py\0", b"")

    monkeypatch.setattr(tracker, "_run_git", fake_git)
    first = tracker.fingerprint(str(repo), force=True)["fingerprint"]
    source.write_text("x=123456\n", encoding="utf-8")
    second = tracker.fingerprint(str(repo), force=True)["fingerprint"]
    assert first != second


def _insert_project(pre: ProjectPreprocessor, root: Path) -> None:
    now = time.time()
    with closing(pre._connect()) as con:
        con.execute(
            "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(root), "w", "running", "inventory", 0, 0, now, now, 0, 0, now, "test"),
        )
        con.commit()


def test_watcher_edit_uses_incremental_inventory_and_invalidates_fast_fingerprint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _config(tmp_path)
    repo = tmp_path / "repo"; repo.mkdir(); source = repo / "a.py"; source.write_text("x=1\n", encoding="utf-8")
    tools = RepositoryTools(config)
    pre = ProjectPreprocessor(config, _Noop(), _Rag(), _Scheduler(), _Noop(), tools)
    try:
        _insert_project(pre, repo)
        assert pre._step_inventory(dict(pre._project_row(str(repo))))
        assert pre._step_hash(dict(pre._project_row(str(repo))))
        with closing(pre._connect()) as con:
            con.execute("UPDATE projects SET phase='complete',status='complete',last_complete_at=?,next_check_at=? WHERE root=?", (time.time(), time.time()+1800, str(repo)))
            con.commit()
        pre._watcher_active = True
        before = pre.cache_fingerprint(str(repo))["fingerprint"]
        source.write_text("x=2\n", encoding="utf-8")
        assert pre.notify_path_changed(str(source)) is True
        after = pre.cache_fingerprint(str(repo))
        assert after["fingerprint"] != before
        assert after["changed_paths"] == ["a.py"]
        assert pre._project_row(str(repo))["phase"] == "inventory"

        monkeypatch.setattr(tools, "file_inventory", lambda *a, **k: (_ for _ in ()).throw(AssertionError("full inventory must not run")))
        assert pre._step_inventory(dict(pre._project_row(str(repo)))) is True
        with closing(pre._connect()) as con:
            row = con.execute("SELECT content_hash,needs_hash FROM file_refs WHERE root=? AND path='a.py'", (str(repo),)).fetchone()
            stats = con.execute("SELECT stats_json FROM projects WHERE root=?", (str(repo),)).fetchone()[0]
        assert row[0]
        assert row[1] == 0
        assert '"incremental_watcher": true' in stats
    finally:
        pre.close()


def test_watcher_metadata_only_event_does_not_requeue_preprocessing(tmp_path: Path):
    config = _config(tmp_path)
    repo = tmp_path / "repo"; repo.mkdir(); source = repo / "a.py"; source.write_text("x=1\n", encoding="utf-8")
    tools = RepositoryTools(config)
    pre = ProjectPreprocessor(config, _Noop(), _Rag(), _Scheduler(), _Noop(), tools)
    try:
        _insert_project(pre, repo)
        assert pre._step_inventory(dict(pre._project_row(str(repo))))
        assert pre._step_hash(dict(pre._project_row(str(repo))))
        with closing(pre._connect()) as con:
            con.execute(
                "UPDATE projects SET phase='complete',status='complete',generation=4,last_complete_at=?,next_check_at=? WHERE root=?",
                (time.time(), time.time() + 1800, str(repo)),
            )
            con.commit()
        pre._watcher_active = True
        stat = source.stat()
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000))
        assert pre.notify_path_changed(str(source)) is True

        assert pre._step_inventory(dict(pre._project_row(str(repo)))) is True
        with closing(pre._connect()) as con:
            row = con.execute(
                "SELECT status,phase,generation,next_check_at,stats_json FROM projects WHERE root=?",
                (str(repo),),
            ).fetchone()
        assert row[0:3] == ("complete", "complete", 4)
        assert row[3] > time.time()
        stats = json.loads(row[4])
        assert stats["changed_files"] == 0
        assert stats["ignored_metadata_events"] == 1
    finally:
        pre.close()


def test_preprocess_write_retry_recovers_from_transient_locked_writer(tmp_path: Path):
    config = _config(tmp_path)
    pre = ProjectPreprocessor(config, _Noop(), _Rag(), _Scheduler(), _Noop(), RepositoryTools(config))
    attempts = {"n": 0}
    try:
        def op(con: sqlite3.Connection):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise sqlite3.OperationalError("database is locked")
            return con.execute("SELECT 1").fetchone()[0]
        assert pre._write_retry(op) == 1
        assert attempts["n"] == 3
    finally:
        pre.close()


def test_complete_preprocess_project_sleeps_until_recheck(tmp_path: Path):
    config = _config(tmp_path)
    repo = tmp_path / "repo"; repo.mkdir(); (repo / "a.py").write_text("x=1\n", encoding="utf-8")
    pre = ProjectPreprocessor(config, _Noop(), _Rag(), _Scheduler(), _Noop(), RepositoryTools(config))
    try:
        _insert_project(pre, repo)
        with closing(pre._connect()) as con:
            con.execute(
                "UPDATE projects SET phase='complete',status='complete',last_complete_at=?,next_check_at=? WHERE root=?",
                (time.time(), time.time() + 1800, str(repo)),
            )
            con.commit()
        assert pre._next_cpu_project() is None
        with closing(pre._connect()) as con:
            con.execute("UPDATE projects SET next_check_at=? WHERE root=?", (time.time() - 1, str(repo)))
            con.commit()
        due = pre._next_cpu_project()
        assert due is not None and due["phase"] == "complete"
        assert pre._step_complete(dict(due)) is True
        row = pre._project_row(str(repo))
        assert row["phase"] == "inventory" and row["status"] == "queued"
    finally:
        pre.close()

def test_http_server_binds_before_constructing_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from local_ai_hub import http_server

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    cfg = tmp_path / "server.toml"
    cfg.write_text(
        f'''[server]\nbind="127.0.0.1"\nport={port}\nstate_dir="{(tmp_path / 'state').as_posix()}"\n[hardware]\nprofile="cpu"\nauto_tune=false\n''',
        encoding="utf-8",
    )
    constructed = {"n": 0}
    def forbidden(*a, **k):
        constructed["n"] += 1
        raise AssertionError("LocalAIApp must not be constructed when port is already owned")
    monkeypatch.setattr(http_server, "LocalAIApp", forbidden)
    try:
        with pytest.raises(OSError):
            http_server.serve(str(cfg))
        assert constructed["n"] == 0
    finally:
        listener.close()
