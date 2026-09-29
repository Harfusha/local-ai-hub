from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
import pytest

import local_ai_hub.async_jobs as async_jobs
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStatus, TaskStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.async_jobs import AsyncJobManager


class _Job:
    def __init__(self) -> None:
        self.id = 1
        self.done = threading.Event()
        self.error = None


class _Scheduler:
    config = {"models": {"heavy_code": "test-model"}}

    def enqueue(self, model, tenant, source, execute, priority=1, *, background=True):
        return _Job()


class _Artifacts:
    def put(self, _content, _tenant, _kind):
        return "art-123"


@pytest.fixture(autouse=True)
def _active_operational_mode(monkeypatch):
    snapshot = SimpleNamespace(
        mode="active", revision=0, updated_at=None, degraded=False, error=""
    )
    monkeypatch.setattr(
        async_jobs,
        "load_operational_mode",
        lambda _state_dir: snapshot,
        raising=False,
    )
    monkeypatch.setattr(
        async_jobs,
        "operational_mode_gate_error",
        lambda _snapshot: None,
        raising=False,
    )


def test_async_job_updates_agent_task_and_mints_receipt(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    task_store = TaskStore(state_store)
    verification_store = VerificationStore(state_store, task_store=task_store)

    # Create an Agent OS task
    contract = GoalContract(goal="Analyze repo architecture", acceptance_criteria=("async_job:reason",), scope=AgentScope.TASK)
    context = ScopeContext(repository_id="repo-1", branch="main", task_id="task-1")
    task = task_store.create(contract=contract, context=context, task_id="task-1")
    assert task.status == TaskStatus.PLANNED
    task_store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="key-1")

    scheduler = _Scheduler()
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        scheduler,
        _Artifacts(),
        lambda action, payload, tenant: {"success": True, "action": action, "task": payload.get("task")},
        task_store=task_store,
        verification_store=verification_store,
    )

    submitted = manager.submit("tenant-test", "reason", {"task": "do work", "task_id": task.task_id})
    assert submitted["success"] is True
    assert submitted["task_id"] == task.task_id

    # Execute the job
    res = manager._execute(submitted["job_id"])
    assert res["success"] is True

    # Verify task state got checkpointed
    updated_task = task_store.get(task.task_id)
    assert updated_task is not None
    assert updated_task.checkpoint.phase == "async_job:reason:done"

    # Verify receipt got recorded
    receipts = verification_store.completion(task.task_id).receipts
    assert len(receipts) >= 1
    assert receipts[0].criterion == "async_job:reason"
    manager.close()
    assert receipts[0].passed is True


def test_async_batch_persists_sixteen_ordered_partial_outcomes(tmp_path: Path):
    expected = [
        {"index": index, "success": index != 7, **({} if index != 7 else {"error": "item failed"})}
        for index in range(16)
    ]

    def execute(_action, payload, _tenant):
        assert len(payload["tasks"]) == 16
        return {"success": True, "results": expected}

    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path / "state")}, "async_jobs": {"wait_max_seconds": 90}},
        _Scheduler(),
        _Artifacts(),
        execute,
    )
    try:
        submitted = manager.submit(
            "tenant-test", "batch", {"tasks": [{"task": f"task-{index}"} for index in range(16)]}
        )
        assert submitted["success"] is True
        assert manager.wait("tenant-test", submitted["job_id"], 3)["state"] == "done"

        result = manager.result("tenant-test", submitted["job_id"])

        assert result["success"] is True
        assert result["result"]["results"] == expected
        assert result["result"]["results"][7] == {"index": 7, "success": False, "error": "item failed"}
    finally:
        manager.close()
