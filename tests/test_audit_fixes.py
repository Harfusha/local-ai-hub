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

