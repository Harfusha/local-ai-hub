"""Regression test suite for Audit Round 3 findings (T01 through T21).
Documented in docs/AUDIT_ROUND_3_2026-11-08.md.
"""
from __future__ import annotations

import time
import multiprocessing
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_ai_hub.agent_blackboard import BlackboardSection, merge_sections
from local_ai_hub.agent_board import BoardStore
from local_ai_hub.agent_events import AgentEvent, AgentStateStore, SwarmPubSub
from local_ai_hub.agent_semaphores import SemaphoreStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskCheckpoint, TaskStore
from local_ai_hub.source_slice import read_source_slice
from local_ai_hub.swarm import execute_swarm_dag


def _acquire_semaphore_process(db_path: str, owner: str, barrier, results) -> None:
    store = SemaphoreStore(db_path=Path(db_path))
    barrier.wait(timeout=10)
    results.put(store.acquire("shared-gpu", owner=owner, capacity=1, ttl_seconds=60))


def test_t3_01_swarm_dag_error_dict_fails_step(tmp_path: Path):
    """T3-01 (T09): execute_swarm_dag treats error dict without success key as step failure."""
    steps = [
        {
            "id": "step1",
            "fn": lambda: {"error": "compilation failed", "code": 1},
        }
    ]
    res = execute_swarm_dag(steps=steps, worktree_path=str(tmp_path))
    assert res["success"] is False
    assert "step1" in res["failed_steps"]
    assert res["step_results"]["step1"]["error"] == "compilation failed"


def test_t3_02_session_briefing_handles_taskstate_objects(tmp_path: Path):
    """T3-02 (T10): BoardStore.session_briefing populates active_tasks from TaskState objects."""
    db_path = tmp_path / "state.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    state_store._ensure_schema()
    task_store = TaskStore(state_store=state_store)

    contract = GoalContract(goal="Audit Round 3 test task", acceptance_criteria=("tested",))
    context = ScopeContext(task_id="t3_task")
    task = task_store.create(contract=contract, context=context)
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    local_task = replace(task, checkpoint=TaskCheckpoint(state_data={
        "_agent_task_scope": {"version": 2, "repo_root": str(repo_a)},
    }))
    foreign_task = replace(
        task,
        task_id="foreign_task",
        contract=GoalContract(goal="Foreign repository task", acceptance_criteria=("tested",)),
        checkpoint=TaskCheckpoint(state_data={
            "_agent_task_scope": {"version": 2, "repo_root": str(repo_b)},
        }),
    )
    task_store.list_tasks = MagicMock(return_value=[foreign_task, task, local_task])

    services = MagicMock()
    services.task_store = task_store
    services.board_store = MagicMock()
    services.board_summary = MagicMock(return_value={"counts": {}})
    services.board_item_list = MagicMock(return_value={"items": []})
    services.semaphores = None
    services.plan_list = MagicMock(return_value={"plans": []})

    board_store = BoardStore(db_path=tmp_path / "board.sqlite3", services=services)
    briefing = board_store.session_briefing(include=["active_tasks"], root=str(repo_a))
    assert [item["task_id"] for item in briefing["active_tasks"]] == [local_task.task_id]
    assert briefing["active_tasks"][0]["goal"] == "Audit Round 3 test task"
    assert board_store.session_briefing(include=["active_tasks"])["active_tasks"] == []


def test_t3_03_semaphore_release_checks_owner(tmp_path: Path):
    """T3-03 (T11): SemaphoreStore.release() verifies owner before releasing slot."""
    db_path = tmp_path / "semaphores.sqlite3"
    sem_store = SemaphoreStore(db_path=db_path)

    acq = sem_store.acquire("exclusive_res", owner="agent-real", ttl_seconds=60)
    assert acq["success"] is True
    assert acq["acquired"] is True
    lease_id = acq["lease_id"]

    # Attempt release with wrong owner
    rel_wrong = sem_store.release("exclusive_res", lease_id=lease_id, owner="agent-fake")
    assert rel_wrong["released"] is False

    # Status still shows lease is held
    status = sem_store.status("exclusive_res")
    assert status["found"] is True
    assert len(status["semaphore"]["holders"]) == 1

    # Attempt release with matching owner
    rel_real = sem_store.release("exclusive_res", lease_id=lease_id, owner="agent-real")
    assert rel_real["released"] is True


def test_t11_semaphore_release_requires_owner(tmp_path: Path):
    db_path = tmp_path / "semaphores.sqlite3"
    sem_store = SemaphoreStore(db_path=db_path)
    acq = sem_store.acquire("exclusive_res", owner="agent-real", ttl_seconds=60)
    assert acq["acquired"] is True

    rel_missing = sem_store.release("exclusive_res", lease_id=acq["lease_id"])

    assert rel_missing["released"] is False
    status = sem_store.status("exclusive_res")
    assert len(status["semaphore"]["holders"]) == 1


def test_t3_04_blackboard_merge_does_not_lower_cas_version():
    """T3-04 (T03): CRDT merge preserves the higher local CAS version even when remote clock dominates."""
    s_local = BlackboardSection(
        section="notes",
        content="local content",
        author="agent1",
        clock={"agent1": 1},
        timestamp=100.0,
        version=5,
    )
    s_remote = BlackboardSection(
        section="notes",
        content="remote content",
        author="agent2",
        clock={"agent1": 1, "agent2": 3},  # dominates clock
        timestamp=105.0,
        version=2,  # lower version
    )

    merged = merge_sections(s_local, s_remote)
    assert merged.version >= 5
    assert merged.content == "remote content"


def test_t3_05_source_slice_empty_file_line_bounds(tmp_path: Path):
    """T3-05 (T18): read_source_slice on empty file fails when line_start exceeds source line count."""
    empty_file = tmp_path / "empty.py"
    empty_file.write_text("", encoding="utf-8")

    # Empty files have no line 1, so reject every requested source line.
    res_ok = read_source_slice(str(tmp_path), "empty.py", line_start=1)
    assert res_ok["success"] is False

    # line_start=5 on empty file must fail
    res_err = read_source_slice(str(tmp_path), "empty.py", line_start=5)
    assert res_err["success"] is False
    assert "exceeds" in res_err["error"].lower()


def test_t3_06_semaphore_acquire_respects_capacity(tmp_path: Path):
    """T3-06 (T01): SemaphoreStore enforces capacity=1 as exclusive lock."""
    db_path = tmp_path / "semaphores.sqlite3"
    sem_store = SemaphoreStore(db_path=db_path)

    acq1 = sem_store.acquire("res_limit", owner="agent-1", capacity=1, ttl_seconds=60)
    assert acq1["success"] is True
    assert acq1["acquired"] is True

    acq2 = sem_store.acquire("res_limit", owner="agent-2", capacity=1, ttl_seconds=60)
    assert acq2["success"] is True
    assert acq2["acquired"] is False
    assert acq2["reason"] == "capacity_reached"


def test_t3_10_two_processes_cannot_claim_one_semaphore_slot(tmp_path: Path):
    """T01: Independent processes still serialize capacity=1 admission."""
    db_path = tmp_path / "semaphores-process-race.sqlite3"
    SemaphoreStore(db_path=db_path)  # Create schema before the concurrent race.
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_acquire_semaphore_process,
            args=(str(db_path), f"agent-{index}", barrier, results),
        )
        for index in range(2)
    ]
    for process in processes:
        process.start()
    try:
        outcomes = [results.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
        assert all(outcome["success"] for outcome in outcomes)
        assert sum(bool(outcome["acquired"]) for outcome in outcomes) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()


def test_t3_07_blackboard_section_name_validation():
    """T3-07 (T14): merge_sections raises ValueError on mismatched section names."""
    s1 = BlackboardSection(section="secA", content="a", author="x", clock={}, timestamp=1.0, version=1)
    s2 = BlackboardSection(section="secB", content="b", author="y", clock={}, timestamp=2.0, version=1)
    with pytest.raises(ValueError, match="different names"):
        merge_sections(s1, s2)


def test_t3_08_semaphore_queue_pruned_on_acquire(tmp_path: Path):
    """T3-08 (T02): SemaphoreStore prunes active owner from wait_queue once acquired."""
    from local_ai_hub.agent_semaphores import SemaphoreStore
    db_path = tmp_path / "sem_queue.sqlite3"
    store = SemaphoreStore(db_path=db_path)

    acq1 = store.acquire("slot", owner="agent-1", capacity=1, ttl_seconds=60)
    assert acq1["acquired"] is True

    acq2 = store.acquire("slot", owner="agent-2", capacity=1, ttl_seconds=60)
    assert acq2["acquired"] is False
    assert acq2["position"] == 1

    store.release("slot", lease_id=acq1["lease_id"], owner="agent-1")

    acq2_retry = store.acquire("slot", owner="agent-2", capacity=1, ttl_seconds=60)
    assert acq2_retry["acquired"] is True
    status = store.status("slot")
    assert not any(w["owner"] == "agent-2" for w in status["semaphore"]["queue"])


def test_t3_09_blackboard_merge_skips_mismatched_section_payload(tmp_path: Path):
    """T3-09 (T14): BlackboardStore.merge rejects payload where internal section name mismatches dict key."""
    from local_ai_hub.agent_blackboard import BlackboardStore
    db_path = tmp_path / "bb.sqlite3"
    store = BlackboardStore(db_path=db_path)
    res = store.merge("board-1", {
        "architecture": {
            "section": "performance",
            "content": "conflict",
            "author": "agent-x",
        }
    })
    assert res["success"] is True
    sec = store.get("board-1", "architecture")
    assert sec.get("success") is False
    assert "not found" in sec.get("error", "")


def test_t3_11_swarm_dag_requires_explicit_success_for_dict_result(tmp_path: Path):
    """T09: A dictionary callback result without an explicit success key must fail."""
    steps = [
        {
            "id": "step1",
            "fn": lambda: {"status": "completed"},
        }
    ]

    result = execute_swarm_dag(steps=steps, worktree_path=str(tmp_path))

    assert result["success"] is False
    assert result["failed_steps"] == ["step1"]
