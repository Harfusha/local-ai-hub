from __future__ import annotations

import time
from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import (
    CompletionGateError,
    GoalContract,
    TaskStatus,
    TaskStore,
)
from local_ai_hub.work_fencing import FencingLeaseStore, LeaseLostError
from local_ai_hub.agent_semaphores import SemaphoreStore
from local_ai_hub.resilience import RecoveryJournal


def test_failure_point_1_pre_fence_failure(tmp_path: Path):
    """Failure Point 1: Pre-fence failure (lease expired or lost prior to begin mutation).

    Verifies no partial barrier, zero state committed, no double commit.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(
        GoalContract(goal="atomic change"),
        ScopeContext(task_id="t-1"),
        task_id="t-1",
        actor="owner",
        repo_root=str(repo),
    )
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="k1")

    fences = FencingLeaseStore(tmp_path / "fences.sqlite3")
    attempt = fences.claim_attempt(str(repo), "work-1", "worker-1", ttl_seconds=60)
    lease = fences.acquire(str(repo), "writer-1", ["file.py"], ttl_seconds=60, attempt=attempt)

    # Simulate pre-fence loss/release
    fences.release(lease)

    with pytest.raises(LeaseLostError):
        tasks._begin_fenced_work_mutation(
            task.task_id,
            root=str(repo),
            owner="owner",
            fencing_store=fences,
            lease=lease,
            attempt=attempt,
            paths=["file.py"],
        )

    # State must be completely intact: no barrier set, mutation_generation untouched
    current = tasks.get(task.task_id)
    assert "_pending_fenced_work" not in current.checkpoint.state_data
    assert current.checkpoint.state_data.get("mutation_generation", 0) == 0


def test_failure_point_2_in_guard_write_failure_and_rollback(tmp_path: Path):
    """Failure Point 2: In-guard write/patch failure.

    Verifies barrier is held, rollback advances generation, no double commit occurs.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(
        GoalContract(goal="atomic change"),
        ScopeContext(task_id="t-2"),
        task_id="t-2",
        actor="owner",
        repo_root=str(repo),
    )
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="k2")

    fences = FencingLeaseStore(tmp_path / "fences.sqlite3")
    attempt = fences.claim_attempt(str(repo), "work-2", "worker-2", ttl_seconds=60)
    lease = fences.acquire(str(repo), "writer-2", ["mod.py"], ttl_seconds=60, attempt=attempt)

    guarded = tasks._begin_fenced_work_mutation(
        task.task_id,
        root=str(repo),
        owner="owner",
        fencing_store=fences,
        lease=lease,
        attempt=attempt,
        paths=["mod.py"],
    )
    assert guarded.checkpoint.state_data["mutation_generation"] == 1
    assert "_pending_fenced_work" in guarded.checkpoint.state_data

    # Completion must be blocked while barrier is active
    with pytest.raises(CompletionGateError):
        tasks.validate_completion(task.task_id)

    # Simulate write failure in guard -> rollback
    rolled_back = tasks._finish_fenced_work_mutation(
        task.task_id,
        root=str(repo),
        owner="owner",
        fencing_store=fences,
        lease=lease,
        attempt=attempt,
        paths=["mod.py"],
        rollback=True,
        finalize=lambda: None,
    )
    # Barrier removed, generation incremented to invalidate stale receipts
    assert "_pending_fenced_work" not in rolled_back.checkpoint.state_data
    assert rolled_back.checkpoint.state_data["mutation_generation"] == 2


def test_failure_point_3_unfinalized_barrier_crash_recovery(tmp_path: Path):
    """Failure Point 3: Unfinalized barrier crash.

    Simulates crash when barrier is active; on process restart completion remains blocked.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    db_path = tmp_path / "agent.sqlite3"
    tasks1 = TaskStore(AgentStateStore(db_path))
    task = tasks1.create(
        GoalContract(goal="atomic change"),
        ScopeContext(task_id="t-3"),
        task_id="t-3",
        actor="owner",
        repo_root=str(repo),
    )
    tasks1.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="k3")

    fences = FencingLeaseStore(tmp_path / "fences.sqlite3")
    attempt = fences.claim_attempt(str(repo), "work-3", "worker-3", ttl_seconds=60)
    lease = fences.acquire(str(repo), "writer-3", ["src.py"], ttl_seconds=60, attempt=attempt)

    tasks1._begin_fenced_work_mutation(
        task.task_id,
        root=str(repo),
        owner="owner",
        fencing_store=fences,
        lease=lease,
        attempt=attempt,
        paths=["src.py"],
    )

    # Process crashes abruptly without calling _finish_fenced_work_mutation
    # Fresh process restarts and opens TaskStore
    tasks2 = TaskStore(AgentStateStore(db_path))
    recovered = tasks2.get(task.task_id)
    assert "_pending_fenced_work" in recovered.checkpoint.state_data
    assert recovered.checkpoint.state_data["_pending_fenced_work"]["work_id"] == "work-3"

    # Completion gate MUST block completion
    with pytest.raises(CompletionGateError):
        tasks2.validate_completion(task.task_id)
    tasks2.transition(task.task_id, TaskStatus.VERIFYING, reason="verify", actor="owner", idempotency_key="k3_verify")
    with pytest.raises(CompletionGateError):
        tasks2.transition(task.task_id, TaskStatus.COMPLETED, reason="premature", actor="owner", idempotency_key="k3_done")


def test_failure_point_4_stale_fence_token_injection(tmp_path: Path):
    """Failure Point 4: Stale fence token injection.

    Superseded worker attempt token is rejected when trying to mutate or finalize.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(
        GoalContract(goal="atomic change"),
        ScopeContext(task_id="t-4"),
        task_id="t-4",
        actor="owner",
        repo_root=str(repo),
    )
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="k4")

    fences = FencingLeaseStore(tmp_path / "fences.sqlite3")
    old_attempt = fences.claim_attempt(str(repo), "work-4", "old-worker", ttl_seconds=60)
    old_lease = fences.acquire(str(repo), "writer-4", ["x.py"], ttl_seconds=60, attempt=old_attempt)

    base = dict(root=str(repo), owner="owner", fencing_store=fences, paths=["x.py"])
    tasks._begin_fenced_work_mutation(task.task_id, lease=old_lease, attempt=old_attempt, **base)

    # Old worker loses lease / attempt expires
    fences.release(old_lease)
    fences.release_attempt(old_attempt)

    # New worker claims attempt
    new_attempt = fences.claim_attempt(str(repo), "work-4", "new-worker", ttl_seconds=60)
    new_lease = fences.acquire(str(repo), "writer-4", ["x.py"], ttl_seconds=60, attempt=new_attempt)

    # Old worker attempts to finish: MUST fail with LeaseLostError
    with pytest.raises(LeaseLostError):
        tasks._finish_fenced_work_mutation(
            task.task_id,
            lease=old_lease,
            attempt=old_attempt,
            rollback=True,
            finalize=lambda: None,
            **base,
        )

    # New worker adopts mutation barrier and finishes cleanly
    tasks._adopt_fenced_work_mutation(task.task_id, lease=new_lease, attempt=new_attempt, **base)
    tasks._finish_fenced_work_mutation(
        task.task_id,
        lease=new_lease,
        attempt=new_attempt,
        rollback=False,
        finalize=lambda: None,
        **base,
    )
    tasks.validate_completion(task.task_id)


def test_failure_point_5_finalization_callback_failure(tmp_path: Path):
    """Failure Point 5: Finalization callback failure.

    When finalization callback raises exception, barrier remains intact and
    completion remains blocked.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(
        GoalContract(goal="atomic change"),
        ScopeContext(task_id="t-5"),
        task_id="t-5",
        actor="owner",
        repo_root=str(repo),
    )
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="k5")

    fences = FencingLeaseStore(tmp_path / "fences.sqlite3")
    attempt = fences.claim_attempt(str(repo), "work-5", "worker-5", ttl_seconds=60)
    lease = fences.acquire(str(repo), "writer-5", ["y.py"], ttl_seconds=60, attempt=attempt)

    args = dict(
        root=str(repo),
        owner="owner",
        fencing_store=fences,
        paths=["y.py"],
        lease=lease,
        attempt=attempt,
    )
    tasks._begin_fenced_work_mutation(task.task_id, **args)

    def failing_finalize():
        raise IOError("Disk IO error during finalization")

    with pytest.raises(IOError):
        tasks._finish_fenced_work_mutation(task.task_id, rollback=False, finalize=failing_finalize, **args)

    # Barrier MUST still be held, completion MUST be blocked
    with pytest.raises(CompletionGateError):
        tasks.validate_completion(task.task_id)

    # Successive retry with valid finalization clears barrier
    tasks._finish_fenced_work_mutation(task.task_id, rollback=False, finalize=lambda: None, **args)
    tasks.validate_completion(task.task_id)


def test_unknown_state_never_reported_as_success(tmp_path: Path):
    """Verifies that interrupted, abandoned, or crash recovery states report outcome_unknown=True and never success=True."""
    journal = RecoveryJournal(tmp_path / "journal.sqlite3")
    req_id = "req_1234567890abcdef"
    payload = {"query": "hello"}
    journal.begin(req_id, action="solve", payload=payload)

    # Mark interrupted on startup (simulating hub crash during in-flight request)
    changed = journal.mark_interrupted_on_startup()
    assert changed >= 1

    fp = journal.fingerprint_payload(payload)
    entry = journal.lookup(req_id, action="solve", payload_fingerprint=fp)
    assert entry is not None
    assert entry.get("state") == "abandoned"
    assert entry.get("outcome_unknown") is True
    # Never report success for interrupted/unknown state
    assert (entry.get("response") or {}).get("success") is not True


def test_semaphore_crash_and_expiry_recovery(tmp_path: Path):
    """Verifies SemaphoreStore handles crash/stale holders without double commit or deadlocks."""
    sem_db = tmp_path / "semaphores.sqlite3"
    store1 = SemaphoreStore(sem_db)

    # Acquire with short TTL = 0.1s
    res1 = store1.acquire("gpu_worker", owner="worker_1", capacity=1, ttl_seconds=0.1)
    assert res1["success"] is True
    assert res1["acquired"] is True
    lease1 = res1["lease_id"]

    # Immediate second acquire must fail (queue or rejected)
    res2 = store1.acquire("gpu_worker", owner="worker_2", capacity=1, ttl_seconds=0.1)
    assert res2["acquired"] is False

    # Simulate crash of worker_1 and passage of time (stale lease expiry)
    time.sleep(0.15)

    # Fresh store connection acquires after expiry
    store2 = SemaphoreStore(sem_db)
    res3 = store2.acquire("gpu_worker", owner="worker_3", capacity=1, ttl_seconds=10.0)
    assert res3["success"] is True
    assert res3["acquired"] is True
    assert res3["lease_id"] != lease1

    # Worker_1 attempts to release stale lease: cannot free active worker_3
    rel1 = store2.release("gpu_worker", lease_id=lease1, owner="worker_1")
    assert rel1["released"] is False
    status = store2.status("gpu_worker")
    assert status["semaphore"]["active_count"] == 1
    assert status["semaphore"]["active_holders"][0]["owner"] == "worker_3"
