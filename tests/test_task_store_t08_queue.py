"""T08 owned queue: bounded TTL, terminal listing, trusted replay, generation."""
from __future__ import annotations

from contextlib import closing
import json
import sqlite3

import pytest

from local_ai_hub import agent_tasks, process_utils, trace_context
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import (
    CompletionGateError, GoalContract, TaskCheckpoint, TaskStatus, TaskStore,
)
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.sqlite_support import connect_sqlite


@pytest.fixture
def tasks(tmp_path):
    return TaskStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))


@pytest.mark.parametrize("requested,expected", [
    (-1, 60), (59, 60), (60, 60), (7200, 7200),
    (30 * 86400, 30 * 86400), (31 * 86400, 30 * 86400),
])
def test_worktree_ttl_clamp_preserves_owned_metadata(tasks, tmp_path, monkeypatch, requested, expected):
    calls = []

    def prepare_owned(root, *, branch_name, task_id, owner, created_at, ttl_seconds, expires_at):
        return process_utils.PreparedGitWorktree(
            repo_root=str(root), base_commit_ref="HEAD", base_commit_sha="a" * 40,
            branch=branch_name, worktree_path=str(tmp_path / "owned-worktree"),
            lease_id="owned-lease", worktree_id="owned-id", task_id=task_id,
            owner=owner, created_at=created_at, ttl_seconds=ttl_seconds,
            expires_at=expires_at, creator_pid=123,
            creator_creation_identity="test-creator", creator_creation_identity_type="test",
            creator_executable="test-python",
        )

    def create_owned(root, **metadata):
        calls.append((root, metadata))
        return metadata["prepared_plan"].response_metadata()

    monkeypatch.setattr(process_utils, "prepare_git_worktree", prepare_owned)
    monkeypatch.setattr(process_utils, "create_git_worktree", create_owned)
    task = tasks.create(
        GoalContract(goal="bounded owned worktree"), ScopeContext(repository_id=str(tmp_path)),
        task_id="ttl-task", actor="owner", auto_worktree=True, repo_root=str(tmp_path),
        worktree_ttl_seconds=requested,
    )
    assert len(calls) == 1
    assert calls[0][1]["prepared_plan"].ttl_seconds == expected
    metadata = task.checkpoint.state_data["worktree"]
    assert metadata["ttl_seconds"] == expected
    assert metadata["expires_at"] == task.created_at + expected
    assert metadata["task_id"] == task.task_id
    assert metadata["owner"] == task.owner == "owner"
    assert metadata["worktree_id"] == "owned-id"


@pytest.mark.parametrize("status", [TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.ABANDONED])
def test_no_query_list_keeps_expired_terminal_status(tasks, status):
    task = tasks.create(GoalContract(goal="terminal retained"), ScopeContext(), task_id="terminal")
    with closing(connect_sqlite(tasks.state_store.db_path)) as con, con:
        con.execute(
            "UPDATE agent_tasks_projection SET status=?, heartbeat_expires_at=1 WHERE task_id=?",
            (status.value, task.task_id),
        )
    for status_filter in (None, status):
        listed = tasks.list_tasks(status=status_filter)
        assert [(item.task_id, item.status) for item in listed] == [(task.task_id, status)]


def test_terminal_listing_keeps_active_stale_filter_and_query_scan_limit(tasks, monkeypatch):
    monkeypatch.setattr(agent_tasks, "MAX_TASK_QUERY_SCAN_ROWS", 2)
    for task_id in ("one", "two", "three"):
        tasks.create(GoalContract(goal="terminal retained"), ScopeContext(), task_id=task_id)
    with closing(connect_sqlite(tasks.state_store.db_path)) as con, con:
        con.execute("UPDATE agent_tasks_projection SET status='completed', heartbeat_expires_at=1")
        con.execute("UPDATE agent_tasks_projection SET status='active' WHERE task_id='one'")
    assert {t.task_id for t in tasks.list_tasks()} == {"two", "three"}
    assert len(tasks.list_tasks(limit=1)) == 1
    assert len(tasks.list_tasks(include_stale=True)) == 3
    unmatched = tasks.list_tasks(query="missing")
    assert unmatched == []
    assert unmatched.query_truncated is True


def _completed_with_trusted_review(tasks, tmp_path):
    task = tasks.create(
        GoalContract(goal="trusted completion replay", acceptance_criteria=("review",)),
        ScopeContext(), task_id="review-task", actor="owner", repository_revision="rev-1",
    )
    artifacts = ArtifactStore(tmp_path / "artifacts")
    verifier = VerificationStore(tasks.state_store, task_store=tasks, artifact_store=artifacts)
    evidence = artifacts.put_json({
        "kind": "work_source_review", "passed": True, "criteria": ["review"],
        "task_id": task.task_id, "owner": task.owner,
        "repository_revision": "rev-1", "mutation_generation": 0,
    }, kind="source_review")
    receipt = verifier.record(VerificationReceipt.create(
        task.task_id, "review", evidence_id=evidence, owner=task.owner,
        repository_revision="rev-1", mutation_generation=0, evidence_type="source_review",
    ))
    completed = tasks.complete(task.task_id, actor="owner", reason="verified", idempotency_key="done")
    assert completed.status is TaskStatus.COMPLETED
    return completed, receipt


@pytest.mark.parametrize("entry", ["complete", "transition", "checkpoint-transition"])
@pytest.mark.parametrize("key", ["", "done"])
@pytest.mark.parametrize("invalidated", ["receipt", "generation", "revision"])
def test_completed_retry_revalidates_trusted_receipt_without_mutation(tasks, tmp_path, entry, key, invalidated):
    completed, receipt = _completed_with_trusted_review(tasks, tmp_path)
    with closing(connect_sqlite(tasks.state_store.db_path)) as con, con:
        if invalidated == "receipt":
            con.execute("UPDATE agent_verification_receipts SET passed=0 WHERE receipt_id=?", (receipt.receipt_id,))
        else:
            data = dict(completed.checkpoint.state_data)
            data["mutation_generation" if invalidated == "generation" else "repository_revision"] = (
                1 if invalidated == "generation" else "rev-2"
            )
            checkpoint = TaskCheckpoint(state_data=data).to_dict()
            con.execute("UPDATE agent_tasks_projection SET checkpoint=? WHERE task_id=?", (json.dumps(checkpoint), completed.task_id))
    before = tasks.get(completed.task_id)
    events_before = tasks.state_store.events(f"task:{completed.task_id}")
    with pytest.raises(CompletionGateError):
        if entry == "complete":
            tasks.complete(completed.task_id, actor="owner", reason="verified", idempotency_key=key)
        else:
            kwargs = {"checkpoint": before.checkpoint} if entry == "checkpoint-transition" else {}
            tasks.transition(completed.task_id, TaskStatus.COMPLETED, actor="owner", reason="verified", idempotency_key=key, **kwargs)
    assert tasks.get(completed.task_id) == before
    assert tasks.state_store.events(f"task:{completed.task_id}") == events_before


def test_completed_retry_preserves_events_and_checks_original_operation(tasks, tmp_path):
    completed, _ = _completed_with_trusted_review(tasks, tmp_path)
    before = tasks.state_store.events(f"task:{completed.task_id}")
    assert tasks.complete(completed.task_id, actor="owner", reason="verified", idempotency_key="done") == completed
    assert tasks.transition(completed.task_id, TaskStatus.COMPLETED, actor="owner", reason="verified", idempotency_key="done") == completed
    assert tasks.complete(completed.task_id, actor="owner") == completed
    assert tasks.state_store.events(f"task:{completed.task_id}") == before
    for changes in ({"actor": "other", "reason": "verified"}, {"actor": "owner", "reason": "different"}):
        with pytest.raises(ValueError, match="idempotency key"):
            tasks.complete(completed.task_id, idempotency_key="done", **changes)
    assert tasks.state_store.events(f"task:{completed.task_id}") == before


def test_mutation_generation_keeps_entire_checkpoint_and_revision(tasks):
    task = tasks.create(GoalContract(goal="preserve checkpoint"), ScopeContext(), task_id="generation")
    checkpoint = TaskCheckpoint(
        phase="implementation", next_action="verify", affected_paths=("module.py",),
        evidence_ids=("evidence",), blockers=("waiting for owner",),
        state_data={"mutation_generation": 4, "repository_revision": "rev-1", "custom": {"keep": True}},
    )
    tasks.checkpoint(task.task_id, checkpoint, actor="agent")
    for revision, expected_revision, generation in (("", "rev-1", 5), ("rev-2", "rev-2", 6)):
        updated = tasks.advance_mutation_generation(task.task_id, repository_revision=revision)
        assert updated.checkpoint == TaskCheckpoint(
            phase=checkpoint.phase, next_action=checkpoint.next_action,
            affected_paths=checkpoint.affected_paths, evidence_ids=checkpoint.evidence_ids,
            blockers=checkpoint.blockers,
            state_data={**checkpoint.state_data, "mutation_generation": generation, "repository_revision": expected_revision},
        )


@pytest.mark.parametrize("failure", [RuntimeError("unexpected"), sqlite3.OperationalError("disk error")])
def test_mutation_generation_does_not_swallow_checkpoint_failures(tasks, monkeypatch, failure):
    task = tasks.create(GoalContract(goal="propagate writer failure"), ScopeContext())

    def fail_checkpoint(*args, **kwargs):
        raise failure

    monkeypatch.setattr(tasks, "_persist_checkpoint", fail_checkpoint)
    with pytest.raises(type(failure), match=str(failure)):
        tasks.advance_mutation_generation(task.task_id)
    assert "mutation_generation" not in tasks.get(task.task_id).checkpoint.state_data


def test_mutation_generation_missing_task_is_not_silently_ignored(tasks):
    with pytest.raises(KeyError, match="missing"):
        tasks.advance_mutation_generation("missing")


@pytest.mark.parametrize("bad_generation", [True, -1, "bad", None])
def test_mutation_generation_rejects_invalid_counter_without_reset(tasks, bad_generation):
    task = tasks.create(GoalContract(goal="invalid counter"), ScopeContext())
    tasks.checkpoint(task.task_id, TaskCheckpoint(state_data={"mutation_generation": bad_generation}))
    before = tasks.get(task.task_id)
    with pytest.raises(ValueError, match="mutation_generation"):
        tasks.advance_mutation_generation(task.task_id)
    assert tasks.get(task.task_id) == before


def test_mutation_generation_preserves_server_owned_scope_and_memory(tasks, tmp_path, monkeypatch):
    memory_context = {"items": [{"id": "server-memory"}]}
    monkeypatch.setattr(tasks, "_task_memory_context", lambda *args, **kwargs: memory_context)
    token = trace_context.set_context(agent="trace-agent", request_id="trace-request")
    try:
        created = tasks.create(
            GoalContract(goal="owned generation"), ScopeContext(repository_id=str(tmp_path)),
            repo_root=str(tmp_path), actor="owner", repository_revision="rev-1",
        )
    finally:
        trace_context.reset_context(token)
    before_scope = dict(created.checkpoint.state_data["_agent_task_scope"])
    before_events = tasks.state_store.events(f"task:{created.task_id}")
    with pytest.raises(CompletionGateError, match="memory_audit"):
        tasks.checkpoint(created.task_id, created.checkpoint, actor="owner")
    assert tasks.get(created.task_id) == created
    assert tasks.state_store.events(f"task:{created.task_id}") == before_events
    updated = tasks.advance_mutation_generation(created.task_id, actor="owner")
    assert updated.checkpoint.state_data == {**created.checkpoint.state_data, "mutation_generation": 1}
    assert updated.checkpoint.state_data["memory_context"] == memory_context
    assert updated.checkpoint.state_data["_agent_task_scope"] == before_scope
    assert updated.owner == created.owner


def test_completed_keyed_retry_revalidates_after_serialized_reload(tasks, tmp_path, monkeypatch):
    completed, receipt = _completed_with_trusted_review(tasks, tmp_path)
    original_retry = tasks._replay_same_status_transition

    def revoke_before_serialized_read(*args, **kwargs):
        with closing(connect_sqlite(tasks.state_store.db_path)) as con, con:
            con.execute("UPDATE agent_verification_receipts SET passed=0 WHERE receipt_id=?", (receipt.receipt_id,))
        return original_retry(*args, **kwargs)

    monkeypatch.setattr(tasks, "_replay_same_status_transition", revoke_before_serialized_read)
    before_events = tasks.state_store.events(f"task:{completed.task_id}")
    with pytest.raises(CompletionGateError):
        tasks.complete(completed.task_id, actor="owner", reason="verified", idempotency_key="done")
    assert tasks.get(completed.task_id) == completed
    assert tasks.state_store.events(f"task:{completed.task_id}") == before_events


def test_completed_retry_uses_server_verifier_and_rejects_caller_rules(tasks, tmp_path):
    completed, _ = _completed_with_trusted_review(tasks, tmp_path)
    before_events = tasks.state_store.events(f"task:{completed.task_id}")
    with pytest.raises(TypeError, match="verification_rules"):
        tasks.complete(completed.task_id, verification_rules={"review": True})
    tasks.set_verification_store(object())
    with pytest.raises(CompletionGateError, match="verification evaluator is unsupported"):
        tasks.complete(completed.task_id, actor="owner")
    assert tasks.state_store.events(f"task:{completed.task_id}") == before_events
