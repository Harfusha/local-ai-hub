from __future__ import annotations

from pathlib import Path

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_tasks import TaskStore, GoalContract
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_verification import VerificationStore, VerificationReceipt


class _DummyDeterministic:
    def __init__(self):
        self.last_call = None

    def synthesize_commit(self, root, hint="", *, task_id="", tasks=None, receipts=None):
        self.last_call = {
            "root": root,
            "hint": hint,
            "task_id": task_id,
            "tasks": tasks,
            "receipts": receipts,
        }
        return {"success": True, "tasks": tasks, "receipts": receipts}


def test_deterministic_synthesize_commit_with_tasks_and_receipts(tmp_path: Path):
    engine = DeterministicEngine({})

    tasks = [
        {"task_id": "task-42", "goal": "implement payment gateway"},
    ]
    receipts = [
        {"criterion": "test_checkout_flow", "evidence_id": "E-check-1", "passed": True},
    ]

    res = engine.synthesize_commit(
        str(tmp_path),
        message_hint="",
        task_id="task-42",
        tasks=tasks,
        receipts=receipts,
    )

    assert res["success"] is True
    assert "implement payment gateway" in res["header"]
    assert "Tasks:" in res["body"]
    assert "- [task-42]: implement payment gateway" in res["body"]
    assert "Verified Criteria:" in res["body"]
    assert "- [x] test_checkout_flow (evidence: E-check-1)" in res["body"]
    assert res["tasks"] == tasks
    assert res["receipts"] == receipts


def test_services_synthesize_commit_queries_task_and_verification_stores(tmp_path: Path):
    from local_ai_hub.services import LocalAIServices

    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    task_store = TaskStore(state_store)
    verification_store = VerificationStore(state_store, task_store=task_store)

    # Create task
    t = task_store.create(
        GoalContract(goal="support sse events stream", acceptance_criteria=("stream_events_live",)),
        ScopeContext(task_id="task-sse-1"),
        task_id="task-sse-1",
    )
    # Record verification receipt
    rcpt = VerificationReceipt.create(
        task_id="task-sse-1",
        criterion="stream_events_live",
        passed=True,
        evidence_id="E-sse-stream",
    )
    verification_store.record(rcpt)

    dummy_det = _DummyDeterministic()

    # Create services object
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(tmp_path / "state")}}
    services.deterministic = dummy_det
    services.task_store = task_store
    services.verification_store = verification_store
    services.deterministic_operation = lambda op, root, params, fn: fn()

    res = services.synthesize_commit(str(tmp_path), task_id="task-sse-1")
    assert res["success"] is True
    assert dummy_det.last_call is not None
    assert len(dummy_det.last_call["tasks"]) == 1
    assert dummy_det.last_call["tasks"][0]["task_id"] == "task-sse-1"
    assert len(dummy_det.last_call["receipts"]) == 1
    assert dummy_det.last_call["receipts"][0]["criterion"] == "stream_events_live"
    assert dummy_det.last_call["receipts"][0]["evidence_id"] == "E-sse-stream"
