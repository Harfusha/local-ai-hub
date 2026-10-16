from __future__ import annotations

import math
from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_tasks import (
    GoalContract,
    TaskCheckpoint,
    TaskList,
    TaskState,
    TaskStatus,
    TaskStore,
)


def test_goal_contract_canonical_fields_and_helpers() -> None:
    gc = GoalContract(
        goal=" achieve goal ",
        description=" desc ",
        acceptance_criteria=(" crit1 ", ""),
        scope=AgentScope.TASK,
        non_goals=(" nongoal1 ",),
        constraints=(" constr1 ",),
        risk_profile=" high ",
    )
    assert gc.goal == "achieve goal"
    assert gc.description == "desc"
    assert gc.acceptance_criteria == ("crit1",)
    assert gc.non_goals == ("nongoal1",)
    assert gc.constraints == ("constr1",)
    assert gc.risk_profile == "high"

    # Helpers
    assert gc.has_criteria() is True
    assert gc.criteria_count() == 1
    assert gc.is_high_risk() is True
    assert gc.has_non_goals() is True
    assert gc.has_constraints() is True

    # Empty goal raises ValueError
    with pytest.raises(ValueError):
        GoalContract(goal=" \x00 ")

    with pytest.raises(ValueError, match="description must be a string without null bytes"):
        GoalContract(goal="valid goal", description="bad\x00description")


def test_task_checkpoint_sanitization_and_helpers() -> None:
    chk = TaskCheckpoint(
        phase=" plan\x00 ",
        next_action=" edit\x00 ",
        affected_paths=(" src/app.py\x00 ", ""),
        evidence_ids=(" ev1\x00 ",),
        blockers=(" b1\x00 ", ""),
    )
    assert chk.phase == "plan"
    assert chk.next_action == "edit"
    assert chk.affected_paths == ("src/app.py",)
    assert chk.evidence_ids == ("ev1",)
    assert chk.blockers == ("b1",)

    # Helpers
    assert chk.has_blockers() is True
    assert chk.has_evidence() is True
    assert chk.has_affected_paths() is True

    empty_chk = TaskCheckpoint()
    assert empty_chk.has_blockers() is False
    assert empty_chk.has_evidence() is False
    assert empty_chk.has_affected_paths() is False


def test_task_state_post_init_and_helpers() -> None:
    gc = GoalContract(goal="test")
    ctx = ScopeContext(task_id="t1")

    # Non-canonical string rejection
    with pytest.raises(ValueError, match="task_id must be a canonical string"):
        TaskState(
            task_id=" task-1\x00 ",
            status="active",
            contract=gc,
            context=ctx,
        )

    ts = TaskState(
        task_id="task-1",
        status=TaskStatus.ACTIVE,
        contract=gc,
        context=ctx,
        owner="worker-1",
        lease_id="lease-1",
        created_at=0.0,
        updated_at=0.0,
        heartbeat_expires_at=0.0,
        verification_receipts={"c1": "r1"},
    )
    assert ts.task_id == "task-1"
    assert ts.status == TaskStatus.ACTIVE
    assert ts.owner == "worker-1"
    assert ts.lease_id == "lease-1"
    assert ts.created_at == 0.0
    assert ts.updated_at == 0.0
    assert ts.heartbeat_expires_at == 0.0

    # Helpers
    assert ts.is_active() is True
    assert ts.is_terminal() is False
    assert ts.is_verifying() is False
    assert ts.has_owner() is True
    assert ts.has_lease() is True
    assert ts.receipt_count() == 1
    assert ts.has_receipt("c1") is True
    assert ts.has_receipt("c2") is False

    # Terminal state check
    ts_done = TaskState(
        task_id="task-2",
        status=TaskStatus.COMPLETED,
        contract=gc,
        context=ctx,
    )
    assert ts_done.is_terminal() is True
    assert ts_done.is_active() is False


def test_task_list_helpers() -> None:
    gc = GoalContract(goal="test")
    ctx = ScopeContext(task_id="t1")
    t1 = TaskState(task_id="t1", status=TaskStatus.ACTIVE, contract=gc, context=ctx)

    tl_empty = TaskList()
    assert tl_empty.has_tasks() is False
    assert tl_empty.is_truncated() is False

    tl_full = TaskList([t1], query_truncated=True)
    assert tl_full.has_tasks() is True
    assert tl_full.is_truncated() is True


def test_task_store_has_task(tmp_path: Path) -> None:
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    store = TaskStore(state_store)

    assert store.has_task("nonexistent") is False
    assert store.has_task("") is False

    created = store.create(GoalContract(goal="test_task"), ScopeContext(task_id="test_task"))
    assert store.has_task(created.task_id) is True
