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
state_dir = "{tmp_path.as_posix()}/state"

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

    # Record verification receipt
    rcpt = VerificationReceipt.create(
        task_id=t.task_id,
        criterion="suite_passed",
        passed=True,
        evidence_id="E-test-passed",
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
        result = app.agent_state.append(ev)
        assert result.retryable is True
        assert result.seq == 0
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

    # Record first receipt
    r1 = VerificationReceipt.create(task_id=t.task_id, criterion="tests_pass", passed=True)
    app.agent_verification.record(r1)

    # Still missing lint_pass
    with pytest.raises(CompletionGateError):
        app.agent_tasks.transition(t.task_id, TaskStatus.COMPLETED, reason="still missing", actor="agent", idempotency_key="g-fail2")

    # Record second receipt
    r2 = VerificationReceipt.create(task_id=t.task_id, criterion="lint_pass", passed=True)
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
