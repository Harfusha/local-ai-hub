import inspect
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from local_ai_hub.agent_blackboard import BlackboardStore
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_memory import (
    AgentScope,
    MemoryKind,
    MemoryRecord,
    MemoryStatus,
    MemoryStore,
    _memory_event_stream_id,
)
from local_ai_hub.agent_tasks import (
    GoalContract,
    ScopeContext,
    TaskCheckpoint,
    TaskStatus,
    TaskStore,
)
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.swarm import SwarmCoordinator, SwarmState


def _interrupt_before_publish(*_args, **_kwargs):
    raise SystemExit("simulated process interruption after commit")


def _interrupt_before_lease_recovery(*_args, **_kwargs):
    raise SystemExit("simulated process interruption after dispatch commit")


def _interrupt_after_lease_claim(*_args, **_kwargs):
    raise SystemExit("simulated process interruption after lease claim")


def _make_trusted_repository(parent: Path) -> tuple[Path, str]:
    root = parent / "trusted-repo"
    root.mkdir()
    (root / ".local-ai.toml").write_text(
        '[commands.test]\nargv = ["python", "-B", "-c", "print(1)"]\n'
        '[verification_rules]\ntests = ["test"]\n',
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


def test_committed_event_append_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    event = AgentEvent.create(
        "task:restart-event",
        "task.updated",
        {"version": 1},
        idempotency_key="restart-event-append",
    )

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        state_store.append(event)

    restarted_store = AgentStateStore(db_path)
    saved = restarted_store.events("task:restart-event")
    assert len(saved) == 1
    assert saved[0].event_id == event.event_id
    assert saved[0].seq == 1


def test_committed_task_creation_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    contract = GoalContract(goal="restart task", acceptance_criteria=("durable",))
    context = ScopeContext(task_id="task-restart-create")

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        tasks.create(
            contract,
            context,
            task_id="task-restart-create",
            idempotency_key="create-restart-task",
        )

    restarted_store = AgentStateStore(db_path)
    restarted_tasks = TaskStore(restarted_store)
    saved = restarted_tasks.get("task-restart-create")
    assert saved is not None
    assert saved.contract.goal == "restart task"
    assert [event.kind for event in restarted_store.events("task:task-restart-create")] == [
        "task.created"
    ]


def test_committed_task_transition_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    task_id = "task-restart-transition"
    tasks.create(
        GoalContract(goal="restart transition"),
        ScopeContext(task_id=task_id),
        task_id=task_id,
    )

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        tasks.transition(
            task_id,
            TaskStatus.ACTIVE,
            reason="crash window coverage",
            actor="test",
            idempotency_key="transition-restart-task",
        )

    restarted_store = AgentStateStore(db_path)
    saved = TaskStore(restarted_store).get(task_id)
    assert saved is not None and saved.status is TaskStatus.ACTIVE
    assert [event.kind for event in restarted_store.events(f"task:{task_id}")] == [
        "task.created",
        "task.transitioned",
    ]


def test_crash_after_task_event_append_before_commit_rolls_back_projection_and_event(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    task_id = "task-crash-before-commit"
    tasks.create(
        GoalContract(goal="rollback interrupted transition"),
        ScopeContext(task_id=task_id),
        task_id=task_id,
    )
    append_in_transaction = state_store.append_in_transaction

    def interrupt_after_append(con, event, **kwargs):
        appended = append_in_transaction(con, event, **kwargs)
        assert appended.event is not None
        raise SystemExit("simulated process interruption before commit")

    monkeypatch.setattr(state_store, "append_in_transaction", interrupt_after_append)
    with pytest.raises(SystemExit, match="before commit"):
        tasks.transition(
            task_id,
            TaskStatus.ACTIVE,
            reason="interrupt after event insert",
            actor="test",
            idempotency_key="transition-crash-before-commit",
        )

    restarted_store = AgentStateStore(db_path)
    saved = TaskStore(restarted_store).get(task_id)
    assert saved is not None and saved.status is TaskStatus.PLANNED
    assert [event.kind for event in restarted_store.events(f"task:{task_id}")] == [
        "task.created"
    ]
    page = restarted_store.event_page(f"task:{task_id}")
    assert page["last_seq"] == 1
    assert page["next_seq"] == 1


def test_os_exit_after_task_event_insert_rolls_back_projection_and_event(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    task_id = "task-os-exit-before-commit"
    state_store = AgentStateStore(db_path)
    TaskStore(state_store).create(
        GoalContract(goal="rollback on process death"),
        ScopeContext(task_id=task_id),
        task_id=task_id,
    )

    child_code = """
import inspect
import os
import sys
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_tasks import TaskStatus, TaskStore

store = AgentStateStore(sys.argv[1])
append = store.append_in_transaction
def exit_after_event_insert(con, event, **kwargs):
    append(con, event, **kwargs)
    os._exit(73)
store.append_in_transaction = exit_after_event_insert
TaskStore(store).transition(
    sys.argv[2], TaskStatus.ACTIVE, reason="abrupt exit", actor="test",
    idempotency_key="os-exit-before-commit",
)
"""
    env = os.environ.copy()
    source_root = Path(__file__).resolve().parents[1] / "src"
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(source_root), env.get("PYTHONPATH", "")) if value
    )
    child = subprocess.run(
        [sys.executable, "-B", "-c", child_code, str(db_path), task_id],
        cwd=source_root.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert child.returncode == 73, child.stderr

    restarted_store = AgentStateStore(db_path)
    saved = TaskStore(restarted_store).get(task_id)
    assert saved is not None and saved.status is TaskStatus.PLANNED
    assert [event.kind for event in restarted_store.events(f"task:{task_id}")] == [
        "task.created"
    ]
    page = restarted_store.event_page(f"task:{task_id}")
    assert page["last_seq"] == page["next_seq"] == 1


def test_committed_task_checkpoint_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    task_id = "task-restart-checkpoint"
    tasks.create(
        GoalContract(goal="restart checkpoint"),
        ScopeContext(task_id=task_id),
        task_id=task_id,
    )
    checkpoint = TaskCheckpoint(
        phase="verification",
        next_action="inspect recovery receipt",
        state_data={"recovery_marker": "durable"},
    )

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        tasks.checkpoint(
            task_id,
            checkpoint,
            actor="test",
            idempotency_key="checkpoint-restart-task",
        )

    restarted_store = AgentStateStore(db_path)
    saved = TaskStore(restarted_store).get(task_id)
    assert saved is not None
    assert saved.checkpoint.phase == "verification"
    assert saved.checkpoint.state_data["recovery_marker"] == "durable"
    assert [event.kind for event in restarted_store.events(f"task:{task_id}")] == [
        "task.created",
        "task.checkpointed",
    ]


def test_committed_task_completion_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    task_id = "task-restart-completion"
    repo_root, revision = _make_trusted_repository(tmp_path)
    task = tasks.create(
        GoalContract(goal="restart completion", acceptance_criteria=("tests",)),
        ScopeContext(repository_id=str(repo_root), task_id=task_id),
        task_id=task_id,
        actor="test",
        repo_root=str(repo_root),
    )
    tasks.checkpoint(
        task_id,
        TaskCheckpoint(
            state_data={"repository_revision": revision, "mutation_generation": 0}
        ),
        actor="test",
        idempotency_key="trusted-completion-revision",
    )
    artifacts = ArtifactStore(tmp_path / "artifacts")
    verifications = VerificationStore(state_store, task_store=tasks)
    verifications.artifact_store = artifacts
    command_id = f"cmd-{task_id}"
    receipt_owner = task.owner
    evidence_id = artifacts.put_json(
        {
            "kind": "work_command_verification",
            "passed": True,
            "task_id": task_id,
            "owner": receipt_owner,
            "criterion": "tests",
            "command_id": command_id,
            "command_classification": "test",
            "command": "python -m pytest -q",
            "repository_revision": revision,
            "mutation_generation": 0,
            "exit_code": 0,
            "cached": False,
            "result": {"success": True, "exit_code": 0},
        },
        receipt_owner,
        "command_verification",
    )
    receipt_kwargs = {
        "passed": True,
        "evidence_id": evidence_id,
        "command_id": command_id,
        "repository_revision": revision,
    }
    supported = inspect.signature(VerificationReceipt.create).parameters
    for key, value in {
        "owner": receipt_owner,
        "mutation_generation": 0,
        "evidence_type": "test",
    }.items():
        if key in supported:
            receipt_kwargs[key] = value
    verifications.record(VerificationReceipt.create(task_id, "tests", **receipt_kwargs))
    from local_ai_hub import project_config

    monkeypatch.setattr(
        project_config,
        "resolve_project_context",
        lambda root, state_dir: SimpleNamespace(
            settings=SimpleNamespace(verification_rules={}, commands={}),
            config_digest="cfg-test",
        ),
    )
    tasks.transition(
        task_id,
        TaskStatus.ACTIVE,
        reason="start before completion crash window",
        actor="test",
        idempotency_key="completion-active",
    )
    tasks.transition(
        task_id,
        TaskStatus.VERIFYING,
        reason="receipt verified",
        actor="test",
        idempotency_key="completion-verifying",
    )

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        tasks.complete(
            task_id,
            reason="verified completion",
            actor="test",
            idempotency_key="completion-final",
        )

    restarted_store = AgentStateStore(db_path)
    saved = TaskStore(restarted_store).get(task_id)
    assert saved is not None and saved.status is TaskStatus.COMPLETED
    task_events = restarted_store.events(f"task:{task_id}")
    assert task_events[-1].kind == "task.transitioned"
    assert [event.kind for event in task_events].count("task.transitioned") == 3


def test_committed_task_failure_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    task_id = "task-restart-failure"
    tasks.create(
        GoalContract(goal="restart failure"),
        ScopeContext(task_id=task_id),
        task_id=task_id,
    )

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        tasks.fail(task_id, reason="verifier failed", actor="test")

    restarted_store = AgentStateStore(db_path)
    saved = TaskStore(restarted_store).get(task_id)
    assert saved is not None and saved.status is TaskStatus.FAILED
    assert [event.kind for event in restarted_store.events(f"task:{task_id}")] == [
        "task.created",
        "task.transitioned",
    ]


def test_committed_memory_record_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    memory = MemoryStore(state_store)
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.TASK,
        scope_id="task-restart-memory",
        key="durable-fact",
        value={"value": 42},
        provenance={"root": str(tmp_path), "repository_id": "repository-crash", "tenant": "tenant-a"},
    )

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        memory.record(record)

    restarted_store = AgentStateStore(db_path)
    restarted_memory = MemoryStore(restarted_store)
    saved = restarted_memory.get(
        record.record_id,
        task_id="task-restart-memory",
        root=str(tmp_path),
        repository_id="repository-crash",
        tenant="tenant-a",
    )
    assert saved is not None and saved.value == {"value": 42}
    stream_id = _memory_event_stream_id(
        AgentScope.TASK, "task-restart-memory", "durable-fact"
    )
    assert [event.kind for event in restarted_store.events(stream_id)] == ["memory.recorded"]


def test_committed_receipt_and_task_projection_survive_restart_before_publish(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    tasks.create(
        GoalContract(goal="verify after restart", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-restart-receipt"),
        task_id="task-restart-receipt",
    )
    verifications = VerificationStore(state_store, task_store=tasks)
    receipt = VerificationReceipt.create(
        "task-restart-receipt",
        "tests",
        passed=True,
        evidence_id="evidence-restart",
        command_id="t08-crash-recovery-test",
    )

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        verifications.record(receipt)

    restarted_store = AgentStateStore(db_path)
    restarted_tasks = TaskStore(restarted_store)
    task = restarted_tasks.get("task-restart-receipt")
    assert task is not None
    assert task.verification_receipts == {"tests": receipt.receipt_id}
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_verification_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()[0] == 1
    assert [event.kind for event in restarted_store.events("verification:task-restart-receipt")] == [
        "verification.receipt_recorded"
    ]
    assert [event.kind for event in restarted_store.events("task:task-restart-receipt")].count(
        "task.verified"
    ) == 1


def test_committed_swarm_step_and_blackboard_survive_restart_before_publish(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    blackboard = BlackboardStore(db_path, state_store=state_store)
    coordinator = SwarmCoordinator(db_path, blackboard=blackboard, state_store=state_store)
    swarm_id = coordinator.dispatch("restart swarm", root=str(tmp_path))["swarm_id"]

    monkeypatch.setattr(coordinator, "_publish_after_commit", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        coordinator.step(
            swarm_id,
            "Coder",
            "submit_patch",
            {"patch": "durable"},
            idempotency_key="coder-step-restart",
        )

    restarted_store = AgentStateStore(db_path)
    restarted_board = BlackboardStore(db_path, state_store=restarted_store)
    restarted = SwarmCoordinator(
        db_path, blackboard=restarted_board, state_store=restarted_store
    )
    status = restarted.get_status(swarm_id)
    assert status["state"] == SwarmState.TESTING.value
    assert status["version"] == 2
    assert len(status["history"]) == 2
    section = restarted_board.get(f"swarm:{swarm_id}", "code")["section"]
    assert section["content"] == {"patch": "durable"}
    assert [event.kind for event in restarted_store.events(f"swarm:{swarm_id}")].count(
        "swarm.step"
    ) == 1
    duplicate = restarted.step(
        swarm_id,
        "Coder",
        "submit_patch",
        {"patch": "durable"},
        idempotency_key="coder-step-restart",
    )
    assert duplicate["success"] is True and duplicate["duplicate"] is True


def test_committed_blackboard_update_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    board = BlackboardStore(db_path, state_store=state_store)

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        board.update(
            "restart-board",
            "section",
            {"value": "durable"},
            author="agent",
            expected_version=0,
        )

    restarted_store = AgentStateStore(db_path)
    restarted_board = BlackboardStore(db_path, state_store=restarted_store)
    section = restarted_board.get("restart-board", "section")["section"]
    assert section["content"] == {"value": "durable"}
    assert section["version"] == 1
    assert [event.kind for event in restarted_store.events("blackboard:restart-board:section")] == [
        "blackboard.updated"
    ]


def test_committed_blackboard_delete_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    board = BlackboardStore(db_path, state_store=state_store)
    board.update("restart-board", "section", {"value": "before delete"}, author="agent")

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        board.delete("restart-board", "section")

    restarted_store = AgentStateStore(db_path)
    restarted_board = BlackboardStore(db_path, state_store=restarted_store)
    assert restarted_board.get("restart-board", "section")["success"] is False
    assert [event.kind for event in restarted_store.events("blackboard:restart-board:section")] == [
        "blackboard.updated",
        "blackboard.deleted",
    ]


def test_committed_blackboard_merge_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    board = BlackboardStore(db_path, state_store=state_store)
    remote_sections = {
        name: {
            "content": {"value": name},
            "author": "remote-agent",
            "clock": {"remote-agent": 1},
            "timestamp": 1.0,
            "version": 1,
        }
        for name in ("first", "second")
    }

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        board.merge("restart-merge-board", remote_sections)

    restarted_store = AgentStateStore(db_path)
    restarted_board = BlackboardStore(db_path, state_store=restarted_store)
    sections = restarted_board.get("restart-merge-board")["sections"]
    assert {name: section["content"] for name, section in sections.items()} == {
        "first": {"value": "first"},
        "second": {"value": "second"},
    }
    assert [
        restarted_store.events(f"blackboard:restart-merge-board:{name}")[-1].kind
        for name in ("first", "second")
    ] == ["blackboard.merged", "blackboard.merged"]


def test_committed_swarm_cancel_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    coordinator = SwarmCoordinator(db_path, state_store=state_store)
    dispatched = coordinator.dispatch("restart cancelled swarm", root=str(tmp_path))
    swarm_id = dispatched["swarm_id"]

    monkeypatch.setattr(coordinator, "_publish_after_commit", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        coordinator.cancel(
            swarm_id,
            "operator stop",
            expected_version=dispatched["version"],
        )

    restarted_store = AgentStateStore(db_path)
    restarted = SwarmCoordinator(db_path, state_store=restarted_store)
    status = restarted.get_status(swarm_id)
    assert status["state"] == SwarmState.FAILED.value
    assert status["version"] == dispatched["version"] + 1
    assert [event.kind for event in restarted_store.events(f"swarm:{swarm_id}")] == [
        "swarm.dispatched",
        "swarm.cancelled",
    ]


@pytest.mark.parametrize(
    "crash_point",
    ("before_lease_claim", "after_lease_claim", "after_recovery_commit"),
)
def test_committed_swarm_dispatch_phases_recover_lease_after_restart(
    tmp_path, monkeypatch, crash_point
):
    db_path = tmp_path / "agent_state.sqlite3"
    lease_dir = tmp_path / "leases"
    root = tmp_path / "repo"
    root.mkdir()
    state_store = AgentStateStore(db_path)
    leases = ScopeLeaseStore(lease_dir)
    coordinator = SwarmCoordinator(db_path, leases=leases, state_store=state_store)
    if crash_point == "before_lease_claim":
        monkeypatch.setattr(
            coordinator, "_reconcile_leases", _interrupt_before_lease_recovery
        )
    elif crash_point == "after_lease_claim":
        monkeypatch.setattr(
            coordinator, "_recover_swarm_state", _interrupt_after_lease_claim
        )
    else:
        publish_after_commit = coordinator._publish_after_commit
        publish_calls = 0

        def interrupt_after_recovery_publish(events):
            nonlocal publish_calls
            publish_calls += 1
            if publish_calls == 2:
                raise SystemExit("simulated process interruption after recovery commit")
            publish_after_commit(events)

        monkeypatch.setattr(
            coordinator, "_publish_after_commit", interrupt_after_recovery_publish
        )

    expected_error = {
        "before_lease_claim": "after dispatch commit",
        "after_lease_claim": "after lease claim",
        "after_recovery_commit": "after recovery commit",
    }[crash_point]
    with pytest.raises(SystemExit, match=expected_error):
        coordinator.dispatch(
            "restart leased swarm",
            target_paths=["src/module.py"],
            root=str(root),
        )

    with closing(sqlite3.connect(db_path)) as con:
        row = con.execute(
            "SELECT swarm_id, state, version FROM agent_swarms"
        ).fetchone()
    assert row is not None
    swarm_id = str(row[0])
    expected_state, expected_version, expected_lease_count, expected_events = {
        "before_lease_claim": (
            SwarmState.PENDING.value,
            1,
            0,
            ["swarm.dispatched"],
        ),
        "after_lease_claim": (
            SwarmState.PENDING.value,
            1,
            1,
            ["swarm.dispatched"],
        ),
        "after_recovery_commit": (
            SwarmState.CODING.value,
            2,
            1,
            ["swarm.dispatched", "swarm.reconciled"],
        ),
    }[crash_point]
    assert row[1:] == (expected_state, expected_version)
    assert [event.kind for event in state_store.events(f"swarm:{swarm_id}")] == expected_events
    assert len(leases.list(str(root))) == expected_lease_count

    restarted_store = AgentStateStore(db_path)
    restarted_leases = ScopeLeaseStore(lease_dir)
    restarted = SwarmCoordinator(
        db_path, leases=restarted_leases, state_store=restarted_store
    )

    status = restarted.get_status(swarm_id)
    assert status["state"] == SwarmState.CODING.value
    assert status["version"] == 2
    active = restarted_leases.list(str(root))
    assert len(active) == 1
    assert active[0]["tenant"] == f"swarm:{swarm_id}"
    assert [event.kind for event in restarted_store.events(f"swarm:{swarm_id}")] == [
        "swarm.dispatched",
        "swarm.reconciled",
    ]


def test_committed_compaction_group_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    memory = MemoryStore(state_store)
    for index in range(2):
        memory.record(
            MemoryRecord.create(
                kind=MemoryKind.FACT,
                scope=AgentScope.TASK,
                scope_id="task-restart-compact",
                key=f"source-{index}",
                value={"index": index},
                provenance={"root": str(tmp_path), "repository_id": "repository-crash", "tenant": "tenant-a"},
            )
        )

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        memory.compact(min_records=2, actor="crash-test")

    restarted_store = AgentStateStore(db_path)
    restarted_memory = MemoryStore(restarted_store)
    active = restarted_memory.find(
        scope=AgentScope.TASK,
        scope_id="task-restart-compact",
        task_id="task-restart-compact",
        root=str(tmp_path),
        repository_id="repository-crash",
        tenant="tenant-a",
        status=MemoryStatus.ACTIVE,
    )
    superseded = restarted_memory.find(
        scope=AgentScope.TASK,
        scope_id="task-restart-compact",
        task_id="task-restart-compact",
        root=str(tmp_path),
        tenant="tenant-a",
        status=MemoryStatus.SUPERSEDED,
    )
    assert len(active) == 1 and active[0].key.startswith("compacted_fact_")
    assert active[0].scope_id == "task-restart-compact"
    assert active[0].provenance == {
        "root": str(tmp_path), "repository_id": "repository-crash", "tenant": "tenant-a"
    }
    assert {item.key for item in superseded} == {"source-0", "source-1"}
    assert all(item.status is MemoryStatus.SUPERSEDED for item in superseded)
    assert all(item.supersedes_record_id == active[0].record_id for item in superseded)
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_entity_relations WHERE relation = 'compacted_into'"
        ).fetchone()[0] == 2
    compact_events = restarted_store.events(
        _memory_event_stream_id(active[0].scope, active[0].scope_id, active[0].key)
    )
    assert any(event.kind == "memory.compacted" for event in compact_events)
    assert restarted_memory.compact(min_records=2)["compacted_groups"] == 0


def test_compaction_preserves_scope_identity_and_never_merges_tasks(tmp_path):
    memory = MemoryStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    for task_id in ("task-a", "task-b"):
        for index in range(2):
            memory.record(
                MemoryRecord.create(
                    kind=MemoryKind.FACT,
                    scope=AgentScope.TASK,
                    scope_id=task_id,
                    key=f"{task_id}-fact-{index}",
                    value={"index": index},
                    provenance={"root": str(tmp_path), "repository_id": "repository-crash", "tenant": "tenant-a"},
                )
            )

    compacted = memory.compact(min_records=2)

    assert compacted["compacted_groups"] == 2
    digests = compacted["created_records"]
    assert {record["scope_id"] for record in digests} == {"task-a", "task-b"}
    for task_id in ("task-a", "task-b"):
        scoped = memory.find(
            scope=AgentScope.TASK,
            scope_id=task_id,
            task_id=task_id,
            root=str(tmp_path),
            tenant="tenant-a",
            status=MemoryStatus.ACTIVE,
        )
        assert len(scoped) == 1
        assert scoped[0].key.startswith("compacted_fact_")


def test_compaction_digest_keys_are_unique_across_provenance_groups(tmp_path):
    memory = MemoryStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    for root in ("C:/repo/one", "C:/repo/two"):
        for index in range(2):
            memory.record(
                MemoryRecord.create(
                    kind=MemoryKind.FACT,
                    scope=AgentScope.TASK,
                    scope_id="task-same-scope-id",
                    key=f"{root}-fact-{index}",
                    value={"index": index},
                    provenance={"root": root},
                )
            )

    compacted = memory.compact(min_records=2)

    assert compacted["compacted_groups"] == 2
    digests = compacted["created_records"]
    assert len({record["key"] for record in digests}) == 2
    assert {record["scope_id"] for record in digests} == {"task-same-scope-id"}
    assert {record["provenance"]["root"] for record in digests} == {
        "C:/repo/one",
        "C:/repo/two",
    }
    assert {record["provenance"]["root"] for record in digests} == {
        "C:/repo/one",
        "C:/repo/two",
    }


def test_committed_memory_relation_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    memory = MemoryStore(state_store)

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        memory.record_relation("entity-a", "depends_on", "entity-b")

    restarted_store = AgentStateStore(db_path)
    restarted_memory = MemoryStore(restarted_store)
    relations = restarted_memory.find_relations(source_entity="entity-a")
    assert len(relations) == 1
    assert relations[0]["relation"] == "depends_on"
    assert relations[0]["target_entity"] == "entity-b"
    assert [
        event.kind
        for event in restarted_store.events("relation:entity-a:entity-b")
    ] == ["relation.recorded"]


def test_committed_memory_expiration_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    memory = MemoryStore(state_store)
    record = memory.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            scope_id="task-restart-expired",
            key="expires",
            value={"keep_until": 1},
            expires_at=1,
        )
    )

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        memory.reap_expired(now=2)

    restarted_store = AgentStateStore(db_path)
    restarted_memory = MemoryStore(restarted_store)
    assert restarted_memory.get(record.record_id) is None
    assert [
        event.kind
        for event in restarted_store.events(
            _memory_event_stream_id(record.scope, record.scope_id, record.key)
        )
    ] == ["memory.recorded", "memory.expired"]


def test_committed_memory_revision_staleness_survives_restart_before_publish(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    memory = MemoryStore(state_store)
    record = memory.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="parser",
            value="old evidence",
            status=MemoryStatus.CONFIRMED,
            provenance={
                "root": str(tmp_path),
                "repository_id": "repository-crash",
                "tenant": "tenant-a",
                "repository_revision": "rev-1",
                "path_refs": ["src/parser.py"],
            },
        )
    )

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        memory.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/parser.py"])

    restarted_store = AgentStateStore(db_path)
    restarted_memory = MemoryStore(restarted_store)
    stale = restarted_memory.get(
        record.record_id,
        scope=AgentScope.REPOSITORY,
        root=str(tmp_path),
        repository_id="repository-crash",
        tenant="tenant-a",
    )
    assert stale is not None and stale.status is MemoryStatus.STALE
    events = restarted_store.events(
        _memory_event_stream_id(record.scope, record.scope_id, record.key)
    )
    assert [event.kind for event in events] == ["memory.recorded", "memory.staled"]


def test_committed_memory_quarantine_survives_restart_before_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    memory = MemoryStore(state_store)
    record = memory.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.TASK,
            scope_id="task-restart-quarantine",
            key="conflict",
            value={"answer": "old"},
            provenance={"root": str(tmp_path), "repository_id": "repository-crash", "tenant": "tenant-a"},
        )
    )

    monkeypatch.setattr(state_store, "_publish", _interrupt_before_publish)
    with pytest.raises(SystemExit, match="after commit"):
        memory.quarantine(
            record.record_id,
            "conflicting evidence",
            actor="test",
            task_id="task-restart-quarantine",
            root=str(tmp_path),
            repository_id="repository-crash",
            tenant="tenant-a",
        )

    restarted_store = AgentStateStore(db_path)
    restarted_memory = MemoryStore(restarted_store)
    quarantined = restarted_memory.get(
        record.record_id,
        task_id="task-restart-quarantine",
        root=str(tmp_path),
        repository_id="repository-crash",
        tenant="tenant-a",
    )
    assert quarantined is not None and quarantined.status is MemoryStatus.QUARANTINED
    events = restarted_store.events(
        _memory_event_stream_id(record.scope, record.scope_id, record.key)
    )
    assert [event.kind for event in events] == ["memory.recorded", "memory.quarantined"]
