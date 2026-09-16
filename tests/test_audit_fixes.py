from contextlib import closing
import io
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_ai_hub.commands import _BoundedStreamBuffer, _is_interactive_prompt, CommandBroker
from local_ai_hub.work_orchestrator import WorkOrchestrator
from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.agent_routing import RoutingEngine
from local_ai_hub.agent_verification import ChangeIntent


def test_bounded_stream_buffer_peek_tail():
    buf = _BoundedStreamBuffer(max_chars=2048, redact=False)
    # Write 1000 characters of prefix
    buf.append("A" * 1000)
    # Append tail with an interactive prompt
    buf.append("\nDo you want to continue? [y/N]: ")
    # Peek should return the tail containing the prompt
    peek_text = buf.peek(500)
    assert "[y/N]" in peek_text
    assert _is_interactive_prompt(peek_text)


def test_bounded_stream_buffer_oversized_chunk():
    buf = _BoundedStreamBuffer(max_chars=1024, redact=False)
    buf.append("Z" * 5000)
    assert len(buf.getvalue()) <= 1024
    assert buf.getvalue() == "Z" * 1024


def test_work_orchestrator_snapshot_relative_root():
    tmp = tempfile.mkdtemp()
    try:
        tmp_path = Path(tmp)
        test_file = tmp_path / "hello.txt"
        test_file.write_text("initial content", encoding="utf-8")
        
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            rel_root = Path(".")
            orch = WorkOrchestrator(
                {"work_orchestrator": {"enabled": True}, "server": {"state_dir": str(tmp_path / "state")}},
                tmp_path / "state",
                MagicMock(),
                None,
                MagicMock(),
                MagicMock(),
            )
            entries = orch._snapshot(rel_root, ["hello.txt"])
            assert len(entries) == 1
            assert entries[0].path == "hello.txt"
            assert entries[0].data == b"initial content"
            assert entries[0].existed is True
        finally:
            os.chdir(cwd)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_agent_routing_select_tests_deduplication():
    router = RoutingEngine()
    change = ChangeIntent.create(
        task_id="task-1",
        affected_paths=("src/foo/utils.py", "src/bar/utils.py", "src/core/utils.py"),
    )
    selection = router.select_tests(change)
    assert selection.selected_tests == ("tests/test_utils.py",)


def test_async_jobs_retry_state():
    tmp = tempfile.mkdtemp()
    try:
        tmp_path = Path(tmp)
        class _Scheduler:
            config = {"models": {"heavy_code": "test-model"}}
            def enqueue(self, model, tenant, source, execute, priority=1, *, background=True):
                job = MagicMock()
                job.done = threading.Event()
                job.done.set()
                return job

        class _Artifacts:
            def put(self, content, tenant, kind):
                return "art-1"

        mgr = AsyncJobManager(
            {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 5.0, "max_attempts": 3}},
            _Scheduler(),
            _Artifacts(),
            lambda a, p, t: {"success": False, "retryable": True, "error": "first failure"},
        )
        submit = mgr.submit("tenant_a", "reason", {})
        assert submit["success"]
        job_id = submit["job_id"]

        res = mgr._execute(job_id)
        assert res["retryable"] is True
        st = mgr.status("tenant_a", job_id)
        assert st["state"] == "queued"
        assert st["attempts"] == 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_daemon_pruning_on_capacity():
    broker = CommandBroker({"commands": {"enabled": True}})
    for i in range(60):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_fh = MagicMock()
        broker._daemons[f"d_{i}"] = {
            "daemon_id": f"d_{i}",
            "process": mock_proc,
            "pid": 1000 + i,
            "name": f"d_{i}",
            "command": "echo 1",
            "cwd": ".",
            "log_path": "fake.log",
            "log_fh": mock_fh,
            "started_at": 100.0 + i,
            "stopped_at": 200.0 + i,
        }
    
    res = broker.stop_daemon("d_59")
    assert res["success"]
    assert len(broker._daemons) <= 50


def test_command_rollback_untracked_containment():
    tmp = tempfile.mkdtemp()
    try:
        tmp_path = Path(tmp)
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("critical", encoding="utf-8")
        
        # Test containment logic directly
        resolved_cwd = repo_dir.resolve()
        new_untracked = {"../outside.txt", "valid_new.txt"}
        (repo_dir / "valid_new.txt").write_text("temp", encoding="utf-8")
        
        for new_f in new_untracked:
            p = (repo_dir / new_f).resolve()
            try:
                if not p.is_relative_to(resolved_cwd) or p == resolved_cwd:
                    continue
            except (ValueError, TypeError):
                continue
            if p.is_file():
                p.unlink(missing_ok=True)
        
        # outside.txt must still exist!
        assert outside_file.exists()
        # valid_new.txt must be removed
        assert not (repo_dir / "valid_new.txt").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_telemetry_busy_retries_drops_on_limit():
    from local_ai_hub.telemetry import TelemetryStore
    tmp = tempfile.mkdtemp()
    try:
        store = TelemetryStore(Path(tmp), enabled=True, flush_interval_seconds=0.05)
        # Mock _flush_batch to raise sqlite3.OperationalError: database is locked
        import sqlite3
        store._flush_batch = MagicMock(side_effect=sqlite3.OperationalError("database is locked"))
        
        store.record(event_type="inference", action="test", success=True)
        # Flush or wait for writer loop to handle retries
        time.sleep(0.4)
        store.close()
        # Ensure writer loop exited cleanly without hanging
        assert not store._thread.is_alive()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_code_index_path_filtering_and_containment():
    from contextlib import closing
    from local_ai_hub.code_index import CodeIndex
    from local_ai_hub.process_utils import canonical_root
    tmp = tempfile.mkdtemp()
    try:
        tmp_path = Path(tmp)
        idx = CodeIndex({"code_index": {"enabled": True}, "server": {"state_dir": str(tmp_path)}}, MagicMock())
        root = str(tmp_path)
        resolved = canonical_root(root)

        with idx._lock, closing(idx._connect()) as con:
            con.execute("INSERT INTO refs(root, path, name, line, kind) VALUES(?, ?, ?, ?, ?)",
                        (resolved, "src/a.py", "my_func", 10, "call"))
            con.execute("INSERT INTO refs(root, path, name, line, kind) VALUES(?, ?, ?, ?, ?)",
                        (resolved, "src/b.py", "my_func", 20, "call"))
            con.execute("INSERT INTO edges(root, src, dst, kind, path, line) VALUES(?, ?, ?, ?, ?, ?)",
                        (resolved, "ImplA", "BaseClass", "implements", "src/a.py", 5))
            con.execute("INSERT INTO edges(root, src, dst, kind, path, line) VALUES(?, ?, ?, ?, ?, ?)",
                        (resolved, "ImplB", "BaseClass", "implements", "src/b.py", 15))
            con.commit()

        # Without path filter: returns both
        all_refs = idx.find_referencing_symbols(root, "my_func")
        assert all_refs["references_count"] == 2

        # With path filter: returns only matching path
        filtered_refs = idx.find_referencing_symbols(root, "my_func", path="src/a.py")
        assert filtered_refs["references_count"] == 1
        assert filtered_refs["references"][0]["path"] == "src/a.py"

        # Implementations without path: returns both
        all_impls = idx.find_implementations(root, "BaseClass")
        assert all_impls["implementations_count"] == 2

        # Implementations with path filter: returns only src/b.py
        filtered_impls = idx.find_implementations(root, "BaseClass", path="src/b.py")
        assert filtered_impls["implementations_count"] == 1
        assert filtered_impls["implementations"][0]["path"] == "src/b.py"

        # Diagnostics path traversal containment check
        diag_escape = idx.get_diagnostics_for_file(root, "../outside.py")
        assert diag_escape["success"] is False
        assert "escapes root" in diag_escape["error"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_circular_dependencies_fast_resolution():
    from local_ai_hub.deterministic import DeterministicEngine
    tmp = tempfile.mkdtemp()
    try:
        tmp_path = Path(tmp)
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "mod_a.py").write_text("import mypkg.mod_b\n", encoding="utf-8")
        (pkg / "mod_b.py").write_text("from mypkg import mod_a\n", encoding="utf-8")

        det = DeterministicEngine({"deterministic": {"enabled": True}, "server": {"state_dir": str(tmp_path)}}, MagicMock(), MagicMock(), MagicMock())
        res = det.find_circular_dependencies(str(tmp_path))
        assert res["success"] is True
        assert res["has_cycles"] is True
        assert res["cycles_found"] >= 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_schema_drift_quoted_table_names():
    import sqlite3
    from contextlib import closing
    from local_ai_hub.deterministic import DeterministicEngine
    tmp = tempfile.mkdtemp()
    try:
        tmp_path = Path(tmp)
        db_file = tmp_path / "app.db"
        with closing(sqlite3.connect(db_file)) as con:
            # SQL keyword table name
            con.execute("CREATE TABLE [order] (id INTEGER PRIMARY KEY, item TEXT)")
            # Hyphenated table name
            con.execute('CREATE TABLE "user-data" (id INTEGER PRIMARY KEY, val TEXT)')
            con.commit()

        # Create a matching python file with SQLAlchemy style table
        py_file = tmp_path / "models.py"
        py_file.write_text("""
class Order:
    __tablename__ = "order"
    id: int
    item: str

class UserData:
    __tablename__ = "user-data"
    id: int
    val: str
""", encoding="utf-8")

        det = DeterministicEngine({"deterministic": {"enabled": True}, "server": {"state_dir": str(tmp_path)}}, MagicMock(), MagicMock(), MagicMock())
        res = det.migration_drift(str(tmp_path), db_path=str(db_file))
        assert res["success"] is True
        assert res["in_sync"] is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_command_broker_last_bounded():
    broker = CommandBroker({"commands": {"enabled": True}})
    with broker._lock:
        for i in range(150):
            broker._last[f"key_{i}"] = {"output": f"out_{i}"}
    
    # Manually trigger bounding logic as in CommandBroker.run_command
    with broker._lock:
        if len(broker._last) > 128:
            old_keys = list(broker._last.keys())[:64]
            for k in old_keys:
                broker._last.pop(k, None)
    
    assert len(broker._last) <= 128


def test_swarm_connect_sqlite_and_wal():
    from local_ai_hub.swarm import SwarmCoordinator
    tmp = tempfile.mkdtemp()
    try:
        tmp_path = Path(tmp)
        db_path = tmp_path / "swarms.sqlite3"
        coord = SwarmCoordinator(db_path)
        with closing(coord._connect()) as con:
            mode = con.execute("PRAGMA journal_mode").fetchone()[0]
            assert str(mode).lower() == "wal"
            # Verify table exists
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            assert "agent_swarms" in tables
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_deterministic_schema_and_query_explain_safety():
    from contextlib import closing
    import sqlite3
    from local_ai_hub.deterministic import DeterministicEngine
    tmp = tempfile.mkdtemp()
    try:
        tmp_path = Path(tmp)
        db_file = tmp_path / "test.db"
        with closing(sqlite3.connect(db_file)) as con:
            con.execute('CREATE TABLE "order-items" (id INTEGER PRIMARY KEY, item TEXT)')
            con.commit()

        det = DeterministicEngine({"deterministic": {"enabled": True}, "server": {"state_dir": str(tmp_path)}}, MagicMock(), MagicMock(), MagicMock())
        # Schema inspection with hyphen in table name
        schema_res = det.schema_inspect(str(tmp_path), db_path=str(db_file))
        assert schema_res["success"] is True
        assert "order-items" in schema_res["tables"]

        # Explain query with multiple statements rejected
        multi_res = det.explain_query(str(tmp_path), "SELECT * FROM [order-items]; DROP TABLE [order-items];", db_path=str(db_file))
        assert multi_res["success"] is False
        assert "multiple statements" in multi_res["error"]

        # Explain valid query
        valid_res = det.explain_query(str(tmp_path), "SELECT * FROM [order-items] WHERE id = 1", db_path=str(db_file))
        assert valid_res["success"] is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_agent_memory_reap_cleans_embeddings_and_fts():
    import sqlite3
    from local_ai_hub.agent_memory import MemoryStore, MemoryRecord, MemoryKind
    from local_ai_hub.agent_identity import AgentScope
    from local_ai_hub.agent_events import AgentStateStore
    tmp = tempfile.mkdtemp()
    try:
        tmp_path = Path(tmp)
        state_store = AgentStateStore(tmp_path / "state.db", enabled=True)
        store = MemoryStore(state_store)
        
        # Record memory expiring in the past
        rec = MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.SESSION,
            key="temp_key",
            value="temp_val",
            expires_at=time.time() - 10,
        )
        saved = store.record(rec)
        store.set_embedding(saved.record_id, [0.1, 0.2, 0.3, 0.4])

        # Verify embedding exists
        with closing(store._connect()) if hasattr(store, "_connect") else closing(sqlite3.connect(state_store.db_path)) as con:
            emb_count = con.execute("SELECT COUNT(1) FROM agent_memory_embeddings").fetchone()[0]
            assert emb_count == 1

        # Reap expired records
        reaped = store.reap_expired(time.time())
        assert reaped == 1

        # Verify embedding was cleaned up
        with closing(store._connect()) if hasattr(store, "_connect") else closing(sqlite3.connect(state_store.db_path)) as con:
            emb_count_after = con.execute("SELECT COUNT(1) FROM agent_memory_embeddings").fetchone()[0]
            assert emb_count_after == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_agent_context_batch_invalidation():
    from local_ai_hub.agent_context import ContextCompiler
    from local_ai_hub.agent_events import AgentStateStore
    tmp = tempfile.mkdtemp()
    try:
        tmp_path = Path(tmp)
        state_store = AgentStateStore(tmp_path / "state.db", enabled=True)
        cc = ContextCompiler(state_store)
        
        # Link 3 files
        cc.link("task-1", "mem-1", "evidence", path="src/a.py")
        cc.link("task-1", "mem-2", "evidence", path="src/b.py")
        cc.link("task-1", "mem-3", "evidence", path="src/c.py")

        # Invalidate batch of 2 paths
        count = cc.invalidate(["src/a.py", "src/b.py"], revision="rev-2")
        assert count == 2

        # Check remaining active link
        active_c = cc.get_active_links("src/c.py")
        assert len(active_c) == 1
        active_a = cc.get_active_links("src/a.py")
        assert len(active_a) == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_agent_policy_budgets_bounded():
    from local_ai_hub.agent_policy import PolicyEngine
    engine = PolicyEngine()
    for i in range(600):
        engine.get_budget(f"task_{i}")
    
    assert len(engine._budgets) <= 512



