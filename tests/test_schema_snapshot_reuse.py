from __future__ import annotations

import os
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub import agent_events
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore
from local_ai_hub.sqlite_support import DurableSchemaMismatchError


@pytest.fixture
def state(tmp_path):
    path = tmp_path / "agent_state.sqlite"
    IncidentStore(AgentStateStore(path))
    return AgentStateStore(path)


def count_source_copies(monkeypatch, state):
    original = Path.open
    copies = []

    def opened(path, mode="r", *args, **kwargs):
        if path == state.db_path and mode == "rb":
            copies.append(path)
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    return copies


def test_unchanged_preflight_reuses_proof_and_reports_zero_copy_bytes(state, monkeypatch, caplog):
    copies = count_source_copies(monkeypatch, state)
    caplog.set_level(logging.INFO, logger=agent_events.__name__)
    state._preflight_schema_read_only()
    first = dict(state._last_schema_preflight)
    assert first["copied_bytes"] == state.db_path.stat().st_size
    assert first["status"] == "ok"
    assert first["copy_seconds"] >= 0
    assert first["validation_seconds"] >= 0
    assert first["total_seconds"] >= first["copy_seconds"] + first["validation_seconds"]
    state._preflight_schema_read_only()
    assert len(copies) == 1
    assert state._last_schema_preflight["cache_hit"] is True
    assert state._last_schema_preflight["copied_bytes"] == 0
    assert state._last_schema_preflight["validation_seconds"] == 0
    assert "phase=reuse cache_hit=True" in caplog.text
    assert "copied_bytes=0" in caplog.text


@pytest.mark.parametrize("populated", [False, True])
def test_existing_schema_initializers_share_unchanged_preflight(state, monkeypatch, populated):
    if populated:
        with closing(sqlite3.connect(state.db_path)) as con:
            con.execute("INSERT INTO agent_events VALUES ('stream', 1, 'event', 'kind', '{}', 'once', '', 'agent', 1.0)")
            con.execute("INSERT INTO agent_event_cursors VALUES ('stream', 1, 1)")
            con.commit()
    copies = count_source_copies(monkeypatch, state)
    state._ensure_schema()
    IncidentStore(state)
    assert len(copies) == 1
    assert state._last_schema_preflight["cache_hit"] is True


def test_changed_database_rejects_invalid_schema_even_after_cache_hit(state, monkeypatch):
    copies = count_source_copies(monkeypatch, state)
    state._preflight_schema_read_only()
    state._preflight_schema_read_only()
    with closing(sqlite3.connect(state.db_path)) as con:
        con.execute("CREATE TABLE tenants (id TEXT)")
        con.commit()
    with pytest.raises(DurableSchemaMismatchError):
        state._preflight_schema_read_only()
    assert len(copies) == 2
    assert state._schema_preflight_cache is None
    assert state._last_schema_preflight["status"] == "error"


def test_live_wal_updates_invalidate_proof_and_preserve_original_files(state, monkeypatch):
    copies = count_source_copies(monkeypatch, state)
    with closing(sqlite3.connect(state.db_path)) as writer:
        writer.execute("INSERT INTO agent_event_cursors VALUES ('first', 0, 1)")
        writer.commit()
        wal = Path(f"{state.db_path}-wal")
        before = [(p.stat().st_size, p.stat().st_mtime_ns) for p in (state.db_path, wal)]
        state._preflight_schema_read_only()
        state._preflight_schema_read_only()
        assert len(copies) == 1
        assert [(p.stat().st_size, p.stat().st_mtime_ns) for p in (state.db_path, wal)] == before
        writer.execute("INSERT INTO agent_event_cursors VALUES ('second', 0, 1)")
        writer.commit()
        state._preflight_schema_read_only()
        assert len(copies) == 2
        assert state._last_schema_preflight["source_bytes"] == sum(p.stat().st_size for p in (state.db_path, wal))
        assert state._last_schema_preflight["cache_hit"] is False


@pytest.mark.parametrize("suffix", ["-wal", "-journal"])
def test_sidecar_creation_touch_replacement_and_removal_invalidate_proof(state, monkeypatch, suffix):
    copies = count_source_copies(monkeypatch, state)
    state._preflight_schema_read_only()
    sidecar = Path(f"{state.db_path}{suffix}")
    sidecar.touch()
    state._preflight_schema_read_only()
    metadata = sidecar.stat()
    os.utime(sidecar, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000_000))
    state._preflight_schema_read_only()
    replacement = sidecar.with_name("replacement")
    replacement.touch()
    replacement.replace(sidecar)
    state._preflight_schema_read_only()
    sidecar.unlink()
    state._preflight_schema_read_only()
    assert len(copies) == 5


def test_drift_during_copy_fails_closed_and_reports_copied_bytes(state, monkeypatch, caplog):
    original = Path.open

    def opened(path, mode="r", *args, **kwargs):
        stream = original(path, mode, *args, **kwargs)
        if path == state.db_path and mode == "rb":
            metadata = path.stat()
            os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000_000))
        return stream

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(sqlite3.OperationalError, match="snapshot changed"):
        state._preflight_schema_read_only()
    assert state._schema_preflight_cache is None
    assert state._last_schema_preflight["copied_bytes"] > 0
    assert "copied_bytes=" in caplog.text


def test_timeout_retains_copy_measurements_and_never_caches_success(state, monkeypatch, caplog):
    original = Path.open
    clock = [0.0]
    monkeypatch.setattr(agent_events.time, "monotonic", lambda: clock[0])

    class SlowRead:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size):
            data = self.stream.read(size)
            clock[0] = 6.0
            return data

    def opened(path, mode="r", *args, **kwargs):
        stream = original(path, mode, *args, **kwargs)
        return SlowRead(stream) if path == state.db_path and mode == "rb" else stream

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(TimeoutError, match="preflight time limit exceeded"):
        state._preflight_schema_read_only()
    metrics = state._last_schema_preflight
    assert metrics["status"] == "error"
    assert metrics["error_type"] == "TimeoutError"
    assert metrics["copied_bytes"] > 0
    assert metrics["copy_seconds"] == 6.0
    assert metrics["total_seconds"] == 6.0
    assert state._schema_preflight_cache is None
    assert "TimeoutError" in caplog.text


def test_changed_validation_policy_cannot_reuse_old_success(state, monkeypatch):
    state._preflight_schema_read_only()
    monkeypatch.setattr(AgentStateStore, "_SCHEMA_OBJECT_SQL_MAX_BYTES", 1)
    with pytest.raises(DurableSchemaMismatchError):
        state._preflight_schema_read_only()


def test_cache_hit_rechecks_identity_before_returning(state, monkeypatch):
    state._preflight_schema_read_only()
    original = Path.stat
    checks = 0

    def checked(path, *args, **kwargs):
        nonlocal checks
        if path == state.db_path:
            checks += 1
            if checks == 2:
                metadata = original(path)
                os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000_000))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", checked)
    with pytest.raises(sqlite3.OperationalError, match="snapshot changed"):
        state._preflight_schema_read_only()
    assert state._schema_preflight_cache is None


def test_proof_is_bound_to_database_path_even_for_same_inode(state, monkeypatch):
    copies = count_source_copies(monkeypatch, state)
    state._preflight_schema_read_only()
    alias = state.db_path.with_name("alias.sqlite")
    os.link(state.db_path, alias)
    state.db_path = alias
    state._preflight_schema_read_only()
    assert len(copies) == 2
    assert state._last_schema_preflight["cache_hit"] is False


def test_parallel_preflights_only_copy_once(state, monkeypatch):
    copies = count_source_copies(monkeypatch, state)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(state._preflight_schema_read_only) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)
    assert len(copies) == 1


def test_live_write_during_classification_does_not_publish_stale_proof(state, monkeypatch):
    copies = count_source_copies(monkeypatch, state)
    original = state._classify_schema
    wrote = False

    def classify(connection):
        nonlocal wrote
        result = original(connection)
        if not wrote:
            wrote = True
            with closing(sqlite3.connect(state.db_path)) as writer:
                writer.execute("INSERT INTO agent_event_cursors VALUES ('concurrent', 0, 1)")
                writer.commit()
        return result

    monkeypatch.setattr(state, "_classify_schema", classify)
    state._preflight_schema_read_only()
    assert state._schema_preflight_cache is None
    state._preflight_schema_read_only()
    assert len(copies) == 2
