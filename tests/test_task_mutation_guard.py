import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import (CompletionGateError, ConcurrentTaskUpdateError, GoalContract,
                                     TaskCheckpoint, TaskStatus, TaskStore)
from local_ai_hub.work_fencing import FencingLeaseStore, LeaseLostError


def test_fenced_mutation_blocks_completion_and_checkpoint_tampering(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    fences = FencingLeaseStore(tmp_path / "fences.sqlite3")
    attempt = fences.claim_attempt(str(root), "work-1", "worker", ttl_seconds=60)
    lease = fences.acquire(str(root), "writer", ["a.txt"], ttl_seconds=60, attempt=attempt)
    guarded = tasks._begin_fenced_work_mutation(task.task_id, root=str(root), owner="owner",
                                                 fencing_store=fences, lease=lease, attempt=attempt, paths=["a.txt"])
    assert guarded.checkpoint.state_data["mutation_generation"] == 1
    next_patch = tasks._begin_fenced_work_mutation(task.task_id, root=str(root), owner="owner",
                                                   fencing_store=fences, lease=lease, attempt=attempt, paths=["a.txt"])
    assert next_patch.checkpoint.state_data["mutation_generation"] == 2
    with pytest.raises(CompletionGateError):
        tasks.validate_completion(task.task_id)
    tasks.transition(task.task_id, TaskStatus.VERIFYING, reason="review", actor="owner", idempotency_key="verify")
    with pytest.raises(CompletionGateError):
        tasks.transition(task.task_id, TaskStatus.COMPLETED, reason="done", actor="owner", idempotency_key="done")
    with pytest.raises(ValueError):
        tasks.checkpoint(task.task_id, TaskCheckpoint(state_data={"_pending_fenced_work": None}))
    tasks.checkpoint(task.task_id, TaskCheckpoint(phase="working"))
    assert tasks.get(task.task_id).checkpoint.state_data["_pending_fenced_work"]["work_id"] == "work-1"
    restarted = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    with pytest.raises(CompletionGateError):
        restarted.validate_completion(task.task_id)


def test_untrusted_checkpoint_cannot_forge_barrier(tmp_path):
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"), task_id="task")
    with pytest.raises(ValueError):
        tasks.checkpoint(task.task_id, TaskCheckpoint(state_data={"_pending_fenced_work": None}))


def test_expired_fence_never_creates_barrier(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    fences = FencingLeaseStore(tmp_path / "fences.sqlite3")
    attempt = fences.claim_attempt(str(root), "work-1", "worker", ttl_seconds=60)
    lease = fences.acquire(str(root), "writer", ["a.txt"], ttl_seconds=60, attempt=attempt)
    fences.release(lease)
    with pytest.raises(LeaseLostError):
        tasks._begin_fenced_work_mutation(task.task_id, root=str(root), owner="owner",
                                          fencing_store=fences, lease=lease, attempt=attempt, paths=["a.txt"])
    assert "_pending_fenced_work" not in tasks.get(task.task_id).checkpoint.state_data


@pytest.mark.parametrize("rollback", [False, True])
def test_finalization_keeps_barrier_until_fenced_action_succeeds(tmp_path, rollback):
    root = tmp_path / "repo"
    root.mkdir()
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    fences = FencingLeaseStore(tmp_path / "fences.sqlite3")
    attempt = fences.claim_attempt(str(root), "work-1", "worker", ttl_seconds=60)
    lease = fences.acquire(str(root), "writer", ["a.txt"], ttl_seconds=60, attempt=attempt)
    args = dict(root=str(root), owner="owner", fencing_store=fences, lease=lease, attempt=attempt, paths=["a.txt"])
    tasks._begin_fenced_work_mutation(task.task_id, **args)
    def fails():
        assert "_pending_fenced_work" in tasks.get(task.task_id).checkpoint.state_data
        raise RuntimeError("finalization failed")
    with pytest.raises(RuntimeError, match="finalization failed"):
        tasks._finish_fenced_work_mutation(task.task_id, rollback=rollback, finalize=fails, **args)
    with pytest.raises(CompletionGateError):
        tasks.validate_completion(task.task_id)
    previous_generation = tasks.get(task.task_id).checkpoint.state_data["mutation_generation"]
    result = tasks._finish_fenced_work_mutation(task.task_id, rollback=rollback, finalize=lambda: None, **args)
    assert "_pending_fenced_work" not in result.checkpoint.state_data
    assert result.checkpoint.state_data["mutation_generation"] == previous_generation + int(rollback)
    tasks.validate_completion(task.task_id)


def test_recovery_adopts_only_same_work_and_rejects_old_fence(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    fences = FencingLeaseStore(tmp_path / "fences.sqlite3")
    old = fences.claim_attempt(str(root), "work-1", "old-worker", ttl_seconds=60)
    old_lease = fences.acquire(str(root), "old-writer", ["a.txt"], ttl_seconds=60, attempt=old)
    base = dict(root=str(root), owner="owner", fencing_store=fences, paths=["a.txt"])
    tasks._begin_fenced_work_mutation(task.task_id, lease=old_lease, attempt=old, **base)
    fences.release(old_lease)
    fences.release_attempt(old)
    foreign = fences.claim_attempt(str(root), "work-other", "foreign", ttl_seconds=60)
    foreign_lease = fences.acquire(str(root), "foreign-writer", ["a.txt"], ttl_seconds=60, attempt=foreign)
    with pytest.raises(ValueError):
        tasks._adopt_fenced_work_mutation(task.task_id, lease=foreign_lease, attempt=foreign, **base)
    fences.release(foreign_lease)
    fences.release_attempt(foreign)
    new = fences.claim_attempt(str(root), "work-1", "new-worker", ttl_seconds=60)
    new_lease = fences.acquire(str(root), "new-writer", ["a.txt"], ttl_seconds=60, attempt=new)
    adopted = tasks._adopt_fenced_work_mutation(task.task_id, lease=new_lease, attempt=new, **base)
    assert adopted.checkpoint.state_data["mutation_generation"] == 2
    assert adopted.checkpoint.state_data["_pending_fenced_work"]["attempt_id"] == new.attempt_id
    with pytest.raises(LeaseLostError):
        tasks._finish_fenced_work_mutation(task.task_id, lease=old_lease, attempt=old,
                                            rollback=True, finalize=lambda: None, **base)
    tasks._finish_fenced_work_mutation(task.task_id, lease=new_lease, attempt=new,
                                        rollback=True, finalize=lambda: None, **base)
    tasks.validate_completion(task.task_id)


def test_fenced_barrier_and_concurrent_transition_cannot_overwrite_each_other(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    tasks = TaskStore(AgentStateStore(tmp_path / "agent.sqlite3"))
    task = tasks.create(GoalContract(goal="change"), ScopeContext(task_id="task"),
                        task_id="task", actor="owner", repo_root=str(root))
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key="start")
    fences = FencingLeaseStore(tmp_path / "fences.sqlite3")
    attempt = fences.claim_attempt(str(root), "work-1", "worker", ttl_seconds=60)
    lease = fences.acquire(str(root), "writer", ["a.txt"], ttl_seconds=60, attempt=attempt)
    original_get = tasks.get
    sync = Barrier(2)
    seen = local()

    def synchronized_get(task_id):
        result = original_get(task_id)
        if not getattr(seen, "waited", False):
            seen.waited = True
            sync.wait(timeout=5)
        return result

    def begin():
        try:
            return tasks._begin_fenced_work_mutation(task.task_id, root=str(root), owner="owner",
                fencing_store=fences, lease=lease, attempt=attempt, paths=["a.txt"])
        except ConcurrentTaskUpdateError as exc:
            return exc

    def transition():
        try:
            return tasks.transition(task.task_id, TaskStatus.VERIFYING, reason="review", actor="owner", idempotency_key="review")
        except ConcurrentTaskUpdateError as exc:
            return exc

    tasks.get = synchronized_get
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(begin), pool.submit(transition)]
            outcomes = [f.result(timeout=10) for f in futures]
    finally:
        tasks.get = original_get
    assert sum(isinstance(outcome, ConcurrentTaskUpdateError) for outcome in outcomes) == 1
    final = original_get(task.task_id)
    assert ("_pending_fenced_work" in final.checkpoint.state_data) != (final.status is TaskStatus.VERIFYING)
