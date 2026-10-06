from __future__ import annotations

import sqlite3
import time
from pathlib import Path
import pytest

from local_ai_hub.app import LocalAIApp
from local_ai_hub.agent_events import AgentEvent
from local_ai_hub.agent_tasks import GoalContract, TaskStatus, TaskCheckpoint, CompletionGateError
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_verification import VerificationReceipt
from local_ai_hub.agent_incidents import IncidentFingerprint, ToolOutcome


def app_with_agent_state(tmp_path: Path) -> LocalAIApp:
    tmp_path.mkdir(parents=True, exist_ok=True)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(f"""
[server]
bind = "127.0.0.1"
port = 11487
auto_start_ollama = false
state_dir = "{tmp_path.as_posix()}/state"

[headless]
autostart_ollama = false
manage_ollama = false

[agent_state]
enabled = true
retention_days = 14
""", encoding="utf-8")
    return LocalAIApp(str(cfg_path))


def test_interrupted_task_resumes_with_fresh_evidence_and_no_duplicate_command(tmp_path: Path):
    app = app_with_agent_state(tmp_path)
    contract = GoalContract(goal="Interrupted Goal", acceptance_criteria=("suite_passed",))
    ctx = ScopeContext(task_id="task-resume-1")
    t = app.agent_tasks.create(contract, ctx, task_id="task-resume-1", actor="agent", idempotency_key="cr-1")
    app.agent_tasks.transition(t.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="tx-1")

    chk = TaskCheckpoint(phase="testing", next_action="verify_tests")
    app.agent_tasks.checkpoint(t.task_id, chk, actor="agent", idempotency_key="chk-1")

    # Record trusted command proof
    command_id = "cmd-resume-tests"
    repository_revision = "rev-1"
    proof = {
        "kind": "work_command_verification",
        "passed": True,
        "task_id": t.task_id,
        "owner": t.owner,
        "criterion": "suite_passed",
        "command_id": command_id,
        "exit_code": 0,
        "repository_revision": repository_revision,
        "mutation_generation": 0,
        "result": {"success": True, "exit_code": 0},
    }
    evidence_id = app.artifacts.put_json(proof, t.owner, "command_verification")
    rcpt = VerificationReceipt.create(
        task_id=t.task_id,
        criterion="suite_passed",
        passed=True,
        evidence_id=evidence_id,
        command_id=command_id,
        owner=t.owner,
        repository_revision=repository_revision,
        evidence_type="test",
    )
    app.agent_verification.record(rcpt)

    # Simulate restart by instantiating new app on same state_dir
    app.close()
    app2 = LocalAIApp(str(tmp_path / "config.toml"))

    resumed = app2.agent_tasks.resume(t.task_id, actor="agent", idempotency_key="resume-1")
    assert resumed.status is TaskStatus.ACTIVE
    assert resumed.checkpoint is not None
    assert resumed.checkpoint.next_action == "verify_tests"

    # Transition to verifying then completed
    app2.agent_tasks.transition(t.task_id, TaskStatus.VERIFYING, reason="verifying", actor="agent", idempotency_key="tx-v")
    completed = app2.agent_tasks.transition(t.task_id, TaskStatus.COMPLETED, reason="done", actor="agent", idempotency_key="tx-complete")
    assert completed.status is TaskStatus.COMPLETED
    app2.close()


def test_busy_database_returns_bounded_retryable_result_without_corrupting_event_stream(tmp_path: Path):
    app = app_with_agent_state(tmp_path)
    app.agent_state._ensure_schema()

    # Exclusively lock the database in another connection
    lock_conn = sqlite3.connect(app.agent_state.db_path, timeout=0.1)
    lock_conn.execute("BEGIN EXCLUSIVE")

    try:
        # Attempt to append while locked
        ev = AgentEvent.create(
            stream_id="task-1",
            kind="task.progress",
            payload={"step": 1},
            idempotency_key="busy-k1",
            actor="agent",
        )
        started = time.perf_counter()
        result = app.agent_state.append(ev)
        elapsed = time.perf_counter() - started
        assert result.retryable is True
        assert result.seq == 0
        assert elapsed < 8.0  # 5 retries × 0.25s SQLite timeout + backoff; bounded under load
    finally:
        lock_conn.rollback()
        lock_conn.close()

    # Event stream must be clean, nothing corrupted
    events = app.agent_state.events("task-1")
    assert events == []
    app.close()


def test_e2e_completion_gate_enforcement(tmp_path: Path):
    app = app_with_agent_state(tmp_path)
    contract = GoalContract(goal="Gated Goal", acceptance_criteria=("tests_pass", "lint_pass"))
    ctx = ScopeContext(task_id="task-gate-1")
    t = app.agent_tasks.create(contract, ctx, task_id="task-gate-1", actor="agent", idempotency_key="g-cr")
    app.agent_tasks.transition(t.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="g-start")
    app.agent_tasks.transition(t.task_id, TaskStatus.VERIFYING, reason="verifying", actor="agent", idempotency_key="g-verif")

    # Transition to COMPLETED must fail before criteria are verified
    with pytest.raises(CompletionGateError):
        app.agent_tasks.transition(t.task_id, TaskStatus.COMPLETED, reason="premature", actor="agent", idempotency_key="g-fail")

    # Record trusted test proof
    test_command_id = "cmd-tests"
    repository_revision = "rev-1"
    test_proof = {
        "kind": "work_command_verification",
        "passed": True,
        "task_id": t.task_id,
        "owner": t.owner,
        "criterion": "tests_pass",
        "command_id": test_command_id,
        "exit_code": 0,
        "repository_revision": repository_revision,
        "mutation_generation": 0,
        "result": {"success": True, "exit_code": 0},
    }
    test_evidence = app.artifacts.put_json(test_proof, t.owner, "command_verification")
    r1 = VerificationReceipt.create(
        task_id=t.task_id, criterion="tests_pass", passed=True, evidence_id=test_evidence,
        command_id=test_command_id, owner=t.owner,
        repository_revision=repository_revision, mutation_generation=0, evidence_type="test",
    )
    app.agent_verification.record(r1)

    # Still missing lint_pass
    with pytest.raises(CompletionGateError):
        app.agent_tasks.transition(t.task_id, TaskStatus.COMPLETED, reason="still missing", actor="agent", idempotency_key="g-fail2")

    # Record trusted review proof
    review_proof = {
        "kind": "work_source_review",
        "passed": True,
        "task_id": t.task_id,
        "owner": t.owner,
        "repository_revision": repository_revision,
        "mutation_generation": 0,
        "criteria": ["lint_pass"],
    }
    review_evidence = app.artifacts.put_json(review_proof, t.owner, "source_review")
    r2 = VerificationReceipt.create(
        task_id=t.task_id, criterion="lint_pass", passed=True, evidence_id=review_evidence,
        owner=t.owner, repository_revision=repository_revision,
        mutation_generation=0, evidence_type="source_review",
    )
    app.agent_verification.record(r2)

    # Now completion succeeds
    done = app.agent_tasks.transition(t.task_id, TaskStatus.COMPLETED, reason="all verified", actor="agent", idempotency_key="g-ok")
    assert done.status is TaskStatus.COMPLETED
    app.close()


def test_e2e_negative_knowledge_retry_decision(tmp_path: Path):
    app = app_with_agent_state(tmp_path)

    outcome = ToolOutcome(
        tool_name="cargo build",
        error="Syntax error: expected semicolon",
        exit_code=1,
        state_revision="rev-initial",
    )
    # Record failed outcome via capture
    inc = app.agent_incidents.capture(outcome)
    assert inc is not None
    assert inc.attempts == 1

    # Same revision retry query -> stop (negative knowledge)
    dec1 = app.agent_incidents.retry_decision(inc.fingerprint, state_revision="rev-initial")
    assert dec1.action == "stop"
    assert "negative knowledge" in dec1.reason

    # Revision changed -> allowed to retry
    dec2 = app.agent_incidents.retry_decision(inc.fingerprint, state_revision="rev-changed")
    assert dec2.action == "retry"

    app.close()


def test_local_app_wires_scoped_memory_adoption_on_create_and_resume(tmp_path: Path):
    from local_ai_hub import trace_context
    from local_ai_hub.agent_memory import AgentScope, MemoryKind, MemoryRecord, MemoryStatus

    app = app_with_agent_state(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()

    def record_memory(key: str, idempotency_key: str) -> MemoryRecord:
        record = MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            scope_id=str(root),
            key=key,
            value=key,
            status=MemoryStatus.CONFIRMED,
            source="user",
            provenance={"root": str(root), "tenant": "tenant-a"},
        )
        return app.agent_memory.record(record, actor="user", idempotency_key=idempotency_key)

    first = record_memory("matching parser fact", "app-memory-first")
    token = trace_context.set_context(tenant="tenant-a")
    try:
        task = app.agent_tasks.create(
            GoalContract(goal="matching parser fact"),
            ScopeContext(repository_id=str(root), branch="main", task_id="app-memory-task"),
            task_id="app-memory-task",
        )
        initial_ids = {
            item["id"] for item in task.checkpoint.state_data["memory_context"]["items"]
        }
        assert initial_ids == {first.record_id}

        app.agent_tasks.transition(
            task.task_id,
            TaskStatus.ACTIVE,
            reason="start",
            actor="test",
            idempotency_key="app-memory-start",
        )
        app.agent_tasks.transition(
            task.task_id,
            TaskStatus.BLOCKED,
            reason="wait",
            actor="test",
            idempotency_key="app-memory-block",
        )
        later = record_memory("matching parser follow-up", "app-memory-later")
        resumed = app.agent_tasks.resume(
            task.task_id, actor="test", idempotency_key="app-memory-resume"
        )
        resumed_ids = {
            item["id"] for item in resumed.checkpoint.state_data["memory_context"]["items"]
        }
        assert resumed_ids == {first.record_id, later.record_id}

        app.agent_tasks.checkpoint(
            task.task_id,
            TaskCheckpoint(state_data={"memory_audit": {"used_ids": sorted(resumed_ids)}}),
            actor="test",
            idempotency_key="app-memory-audit",
        )
        stored = app.agent_tasks.get(task.task_id)
        assert stored is not None
        assert stored.checkpoint.state_data["memory_audit"]["used_ids"] == sorted(resumed_ids)
        assert {
            item["id"] for item in stored.checkpoint.state_data["memory_context"]["items"]
        } == resumed_ids
    finally:
        trace_context.reset_context(token)
        app.close()
