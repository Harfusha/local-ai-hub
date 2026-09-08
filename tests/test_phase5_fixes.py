from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.client import HubClient
from local_ai_hub.commands import CommandBroker
from local_ai_hub.leases import ScopeLeaseStore, _norm_rel
import local_ai_hub.mcp_server as mcp_mod
from local_ai_hub.agent_blackboard import BlackboardStore


class _Job:
    def __init__(self) -> None:
        self.id = 1
        self.done = threading.Event()
        self.error = None


class _Scheduler:
    config = {"models": {"heavy_code": "test-model"}}

    def __init__(self) -> None:
        self.calls = []

    def enqueue(self, model, tenant, source, execute, priority=1, *, background=True):
        self.calls.append({"model": model, "tenant": tenant, "source": source, "execute": execute, "priority": priority, "background": background})
        return _Job()


class _Artifacts:
    def put(self, _content, _tenant, _kind):
        return "artifact-1"


def test_async_jobs_retry_on_execution_failure(tmp_path: Path):
    call_count = 0

    def _fail_first(action, payload, tenant):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient worker crash")
        return {"success": True, "action": action}

    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"max_attempts": 2}},
        _Scheduler(),
        _Artifacts(),
        _fail_first,
    )
    submitted = manager.submit("tenant-a", "reason", {"task": "retry-job"})
    job_id = submitted["job_id"]

    # First attempt fails -> should requeue because attempts (1) < max_attempts (2)
    manager._execute(job_id)
    st = manager.status("tenant-a", job_id)
    assert st["state"] == "queued"
    assert st["attempts"] == 1

    # Second attempt succeeds
    manager._execute(job_id)
    st2 = manager.status("tenant-a", job_id)
    assert st2["state"] == "done"
    assert st2["attempts"] == 2
    manager.close()


def test_async_jobs_tick_reclaims_stuck_running_job(tmp_path: Path):
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"max_attempts": 2, "lease_seconds": 10}},
        _Scheduler(),
        _Artifacts(),
        lambda a, p, t: {"success": True},
    )
    submitted = manager.submit("tenant-a", "reason", {"task": "stuck-job"})
    job_id = submitted["job_id"]

    # Artificially set job to running with an expired lease
    from contextlib import closing
    with manager._lock, closing(manager._connect()) as con:
        con.execute(
            "UPDATE async_jobs SET state = 'running', lease_until = ? WHERE job_id = ?",
            (time.time() - 100, job_id),
        )
        con.commit()

    manager.tick()
    # Expired lease reclaimed -> re-queued
    st = manager.status("tenant-a", job_id)
    assert st["state"] == "queued"
    manager.close()


def test_windows_batch_execution(tmp_path: Path):
    if os.name != "nt":
        pytest.skip("Windows-specific batch execution test")

    bat_file = tmp_path / "test_echo.bat"
    bat_file.write_text("@echo OFF\necho phase5_batch_ok\n", encoding="utf-8")

    broker = CommandBroker({"commands": {"allow_validation": True, "allow_read": True, "allow_unknown": True}})
    res = broker.run(f'"{bat_file}"', cwd=str(tmp_path))
    assert res.get("success") is True, f"Command failed: {res}"
    assert "phase5_batch_ok" in res["stdout"]


def test_client_mutating_endpoints_not_replay_safe():
    client = HubClient(auto_start=False)
    captured = []

    def mock_request(path, payload=None, timeout=None, replay_safe=False):
        captured.append({"path": path, "payload": payload, "replay_safe": replay_safe})
        return {"success": True}

    client.request = mock_request

    # Mutating command
    client.post("/v1/command", {"command": "pytest"})
    assert captured[-1]["replay_safe"] is False

    # Leases
    client.post("/v1/leases/claim", {"root": ".", "paths": ["a.py"]})
    assert captured[-1]["replay_safe"] is False

    # Mutating agent-state
    client.post("/v1/agent-state/tasks", {"action": "create", "name": "t1"})
    assert captured[-1]["replay_safe"] is False

    # Non-mutating agent-state
    client.post("/v1/agent-state/tasks", {"action": "get", "task_id": "1"})
    assert captured[-1]["replay_safe"] is True

    client.post("/v1/agent-state/context", {"action": "compile", "task_id": "1"})
    assert captured[-1]["replay_safe"] is True

    # Root quoting in coord
    mock_get = MagicMock(return_value={"success": True})
    client.get = mock_get
    client.coord("leases", root="C:\\test dir\\project")
    mock_get.assert_called_once()
    called_url = mock_get.call_args[0][0]
    assert "C%3A" in called_url or "test%20dir" in called_url


def test_mcp_server_client_root_normalization(monkeypatch):
    monkeypatch.setattr(mcp_mod, "_workspace", "C:/my/workspace")

    # Default "." or empty root resolves to client workspace
    assert mcp_mod._client_root(".") == "C:/my/workspace"
    assert mcp_mod._client_root("") == "C:/my/workspace"
    assert mcp_mod._client_root("   ") == "C:/my/workspace"

    # Specific root is preserved
    assert Path(mcp_mod._client_root("D:/other/project")) == Path("D:/other/project")


def test_leases_norm_rel_windows_drive_rejection():
    # Leading slash
    with pytest.raises(ValueError, match="lease path must be repository-relative"):
        _norm_rel("/etc/passwd")

    # Windows drive paths
    with pytest.raises(ValueError, match="lease path must be repository-relative"):
        _norm_rel("C:\\evil\\escape.txt")

    with pytest.raises(ValueError, match="lease path must be repository-relative"):
        _norm_rel("D:/evil/escape.txt")

    # Valid relative paths
    assert _norm_rel("src/main.py") == "src/main.py"
    assert _norm_rel("foo/bar/baz.txt") == "foo/bar/baz.txt"


def test_leases_cross_tenant_release_by_id(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path)
    root = str(tmp_path)

    # Tenant-1 claims a file
    claim = store.claim("tenant-1", root, ["src/worker.py"])
    assert claim["success"] is True
    lease_id = claim["lease_id"]

    # Another tenant attempts claim -> fails
    claim2 = store.claim("tenant-2", root, ["src/worker.py"])
    assert claim2["success"] is False

    # Cross-tenant release using http-default or * by lease_id
    rel = store.release(tenant="http-default", lease_id=lease_id)
    assert rel["success"] is True
    assert rel["released_rows"] >= 1

    # Now tenant-2 can claim successfully
    claim3 = store.claim("tenant-2", root, ["src/worker.py"])
    assert claim3["success"] is True


def test_agent_blackboard_retry_busy(tmp_path: Path):
    board = BlackboardStore(tmp_path / "blackboard.sqlite3")

    # Update works smoothly
    r1 = board.update("board-1", "plan", {"step": 1}, author="agent-a")
    assert r1["success"] is True

    # Merge works smoothly
    r2 = board.merge("board-1", [{"section": "plan", "content": {"step": 2}, "author": "agent-b", "clock": {"agent-b": 1}, "timestamp": time.time(), "version": 2}])
    assert r2["success"] is True
