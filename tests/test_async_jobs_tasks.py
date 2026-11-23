from __future__ import annotations

import threading
from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStatus, TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.debug_traces import DebugTraceStore


class _Job:
    def __init__(self) -> None:
        self.id = 1
        self.done = threading.Event()
        self.error = None


class _Scheduler:
    config = {"models": {"heavy_code": "test-model"}}

    def enqueue(self, model, source, execute, priority=1, *, background=True):
        return _Job()


class _Artifacts:
    def put(self, _content, *, kind):
        return "art-123"

    def get(self, _artifact_id, *, offset=0, max_chars=256):
        return {"success": True, "text": "{}"}


@pytest.mark.parametrize("durable_state", ["done", "failed", "queued", "cancelled", "outcome_unknown"])
def test_async_job_receipt_requires_committed_success(tmp_path: Path, monkeypatch, durable_state: str):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    task_store = TaskStore(state_store)
    verification_store = VerificationStore(state_store, task_store=task_store)
    receipt_attempts = []
    create_receipt = VerificationReceipt.create

    def track_receipt(**fields):
        receipt_attempts.append(fields["evidence_id"])
        return create_receipt(**fields)

    monkeypatch.setattr(VerificationReceipt, "create", track_receipt)

    # Create an Agent OS task
    contract = GoalContract(goal="Analyze repo architecture", acceptance_criteria=("async_job:reason",), scope=AgentScope.TASK)
    context = ScopeContext(repository_id="repo-1", branch="main", task_id="task-1")
    task = task_store.create(contract=contract, context=context, task_id="task-1")
    assert task.status == TaskStatus.PLANNED
    task_store.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="key-1")

    scheduler = _Scheduler()
    artifacts = _Artifacts()
    executor_succeeded = durable_state in {"done", "cancelled"}
    config = {"server": {"state_dir": str(tmp_path / "state")}, "debug_traces": {"enabled": True}}
    traces = DebugTraceStore(config)
    with AsyncJobManager(
        config,
        scheduler,
        artifacts,
        lambda _action, _payload: {
            "success": executor_succeeded, "state": "done", "retryable": durable_state == "queued",
            "outcome_unknown": durable_state == "outcome_unknown",
        },
        debug_traces=traces,
        task_store=task_store,
        verification_store=verification_store,
    ) as manager:
        monkeypatch.setattr(manager, "_dispatch_background", lambda _job_id: None)
        submitted = manager.submit("reason", {"task": "do work", "task_id": task.task_id})
        assert submitted["success"] is True
        assert submitted["task_id"] == task.task_id
        job_id = submitted["job_id"]
        cancellations = []

        if durable_state == "cancelled":
            put = artifacts.put

            def cancel_during_put(content, *, kind):
                cancellations.append(manager.cancel(job_id))
                return put(content, kind=kind)

            monkeypatch.setattr(artifacts, "put", cancel_during_put)

        result = manager._execute(job_id)
        assert result["success"] is (durable_state == "done")
        assert manager.status(job_id)["state"] == durable_state
        if durable_state == "cancelled":
            assert len(cancellations) == 1
            assert cancellations[0]["state"] == "running" and cancellations[0]["cancel_requested"] is True

        receipts = verification_store.completion(task.task_id).receipts
        assert receipt_attempts == (["art-123"] if durable_state == "done" else [])
        if durable_state == "done":
            assert len(receipts) == 1
            assert receipts[0].criterion == "async_job:reason"
            assert receipts[0].evidence_id == "art-123"
            assert receipts[0].passed is True
        else:
            assert not receipts
        updated_task = task_store.get(task.task_id)
        assert updated_task is not None
        assert (updated_task.checkpoint.phase == "async_job:reason:done") is (durable_state == "done")
        assert traces.detail(submitted["trace_id"])["session"]["state"] == durable_state


def test_async_batch_persists_sixteen_ordered_partial_outcomes(tmp_path: Path):
    expected = [
        {"index": index, "success": index != 7, **({} if index != 7 else {"error": "item failed"})}
        for index in range(16)
    ]

    def execute(_action, payload):
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
            "batch", {"tasks": [{"task": f"task-{index}"} for index in range(16)]}
        )
        assert submitted["success"] is True
        assert manager.wait(submitted["job_id"], 3)["state"] == "done"

        result = manager.result(submitted["job_id"])

        assert result["success"] is True
        assert result["result"]["results"] == expected
        assert result["result"]["results"][7] == {"index": 7, "success": False, "error": "item failed"}
    finally:
        manager.close()
