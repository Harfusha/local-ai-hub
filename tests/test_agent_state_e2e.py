from __future__ import annotations

import sqlite3
import json
import subprocess
import sys
import time
from pathlib import Path
import pytest

from local_ai_hub.app import LocalAIApp
from local_ai_hub.agent_events import AgentEvent
from local_ai_hub.agent_tasks import GoalContract, TaskStatus, TaskCheckpoint, CompletionGateError
from local_ai_hub.agent_identity import ScopeContext
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


def make_trusted_repository(parent: Path, rules: str) -> tuple[Path, str]:
    root = parent / "repo"
    test_dir = root / "tests"
    test_dir.mkdir(parents=True)
    (test_dir / "test_smoke.py").write_text(
        "def test_smoke():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )
    (root / "lint_target.py").write_text("value = 1\n", encoding="utf-8")
    python = json.dumps(sys.executable)
    test_argv = f'[{python}, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_smoke.py"]'
    lint_argv = f'[{python}, "-B", "-m", "pyflakes", "lint_target.py"]'
    (root / ".local-ai.toml").write_text(
        f"[commands.test]\nargv = {test_argv}\n"
        f"[commands.lint]\nargv = {lint_argv}\n"
        f"[verification_rules]\n{rules}\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T08 test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t08-test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "add", ".local-ai.toml"], cwd=root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "test project config"], cwd=root, check=True)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    return root, revision


def test_interrupted_task_resumes_with_fresh_evidence_and_no_duplicate_command(
    tmp_path: Path,
):
    repo_root, revision = make_trusted_repository(tmp_path, 'test = ["test"]')
    app = app_with_agent_state(tmp_path)
    contract = GoalContract(goal="Interrupted Goal", acceptance_criteria=("test",))
    ctx = ScopeContext(repository_id=str(repo_root), task_id="task-resume-1")
    t = app.agent_tasks.create(
        contract, ctx, task_id="task-resume-1", actor="agent", idempotency_key="cr-1",
        repo_root=str(repo_root),
    )
    app.agent_tasks.transition(t.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="tx-1")

    chk = TaskCheckpoint(
        phase="testing",
        next_action="verify_tests",
        state_data={
            "repo_root": str(repo_root),
            "repository_revision": revision,
            "mutation_generation": 0,
        },
    )
    app.agent_tasks.checkpoint(t.task_id, chk, actor="agent", idempotency_key="chk-1")

    command_result = app.commands.run_project_command(
        "test",
        str(repo_root),
        tenant=t.owner,
        task_id=t.task_id,
        criterion="test",
        timeout=30,
        force=True,
    )
    assert command_result.get("success") is True, {
        key: command_result.get(key)
        for key in ("error", "project_command_error", "reason", "status", "message", "retryable", "terminal")
    }
    receipt = command_result.get("verification_receipt")
    assert isinstance(receipt, dict), {
        key: command_result.get(key)
        for key in ("success", "error", "verification_receipt_warning", "task_id", "criterion", "project_command_error")
    }
    assert receipt["evidence_type"] == "test"
    state = app.agent_tasks.get(t.task_id)
    assert state is not None
    state_data = dict(state.checkpoint.state_data)
    state_data["repository_revision"] = receipt["repository_revision"]
    app.agent_tasks.checkpoint(
        t.task_id,
        TaskCheckpoint(
            phase=state.checkpoint.phase,
            next_action=state.checkpoint.next_action,
            affected_paths=state.checkpoint.affected_paths,
            evidence_ids=state.checkpoint.evidence_ids,
            blockers=state.checkpoint.blockers,
            state_data=state_data,
        ),
        actor="agent",
        idempotency_key="command-revision",
    )

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
    assert app2.commands.get_command_execution_record(
        receipt["command_id"], tenant=t.owner, task_id=t.task_id, repository_root=str(repo_root)
    ) is not None
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
    repo_root, revision = make_trusted_repository(
        tmp_path,
        'test = ["test"]\nlint = ["lint"]',
    )
    app = app_with_agent_state(tmp_path)
    contract = GoalContract(goal="Gated Goal", acceptance_criteria=("test", "lint"))
    ctx = ScopeContext(repository_id=str(repo_root), task_id="task-gate-1")
    t = app.agent_tasks.create(
        contract, ctx, task_id="task-gate-1", actor="agent", idempotency_key="g-cr",
        repo_root=str(repo_root),
    )
    app.agent_tasks.transition(t.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="g-start")
    app.agent_tasks.checkpoint(
        t.task_id,
        TaskCheckpoint(state_data={
            "repo_root": str(repo_root),
            "repository_revision": revision,
            "mutation_generation": 0,
        }),
        actor="agent",
        idempotency_key="g-root",
    )
    app.agent_tasks.transition(t.task_id, TaskStatus.VERIFYING, reason="verifying", actor="agent", idempotency_key="g-verif")

    # Transition to COMPLETED must fail before criteria are verified
    with pytest.raises(CompletionGateError):
        app.agent_tasks.transition(t.task_id, TaskStatus.COMPLETED, reason="premature", actor="agent", idempotency_key="g-fail")

    test_result = app.commands.run_project_command(
        "test",
        str(repo_root),
        tenant=t.owner,
        task_id=t.task_id,
        criterion="test",
        timeout=30,
        force=True,
    )
    assert test_result.get("success") is True, {
        key: test_result.get(key)
        for key in ("error", "project_command_error", "reason", "status", "message", "retryable", "terminal")
    }
    test_receipt = test_result.get("verification_receipt")
    assert isinstance(test_receipt, dict), {
        key: test_result.get(key)
        for key in ("success", "error", "verification_receipt_warning", "task_id", "criterion", "project_command_error")
    }
    state = app.agent_tasks.get(t.task_id)
    assert state is not None
    state_data = dict(state.checkpoint.state_data)
    state_data["repository_revision"] = test_receipt["repository_revision"]
    app.agent_tasks.checkpoint(
        t.task_id,
        TaskCheckpoint(
            phase=state.checkpoint.phase,
            next_action=state.checkpoint.next_action,
            affected_paths=state.checkpoint.affected_paths,
            evidence_ids=state.checkpoint.evidence_ids,
            blockers=state.checkpoint.blockers,
            state_data=state_data,
        ),
        actor="agent",
        idempotency_key="test-command-revision",
    )

    # Still missing lint receipt.
    with pytest.raises(CompletionGateError):
        app.agent_tasks.transition(t.task_id, TaskStatus.COMPLETED, reason="still missing", actor="agent", idempotency_key="g-fail2")

    lint_result = app.commands.run_project_command(
        "lint",
        str(repo_root),
        tenant=t.owner,
        task_id=t.task_id,
        criterion="lint",
        timeout=30,
        force=True,
    )
    assert lint_result.get("success") is True, {
        key: lint_result.get(key)
        for key in ("error", "project_command_error", "reason", "status", "message", "retryable", "terminal")
    }
    lint_receipt = lint_result.get("verification_receipt")
    assert isinstance(lint_receipt, dict), lint_result
    assert lint_receipt["evidence_type"] == "source_review"
    assert lint_receipt["repository_revision"] == test_receipt["repository_revision"]

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
    assert app.agent_tasks.state_store is app.agent_memory.state_store

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

        completed = app.agent_tasks.complete(
            task.task_id,
            reason="task completed before confirming its learning",
            actor="test",
            idempotency_key="app-memory-complete",
        )
        assert completed.status is TaskStatus.COMPLETED

        learned = record_memory(
            "confirmed post-task learning sentinel",
            "app-memory-post-task-learning",
        )
        assert learned.status is MemoryStatus.CONFIRMED
        follow_up = app.agent_tasks.create(
            GoalContract(goal="confirmed post-task learning sentinel"),
            ScopeContext(repository_id=str(root), branch="main", task_id="app-memory-follow-up"),
            task_id="app-memory-follow-up",
        )
        follow_up_ids = {
            item["id"] for item in follow_up.checkpoint.state_data["memory_context"]["items"]
        }
        assert follow_up_ids == {first.record_id, later.record_id, learned.record_id}
    finally:
        trace_context.reset_context(token)
        app.close()
