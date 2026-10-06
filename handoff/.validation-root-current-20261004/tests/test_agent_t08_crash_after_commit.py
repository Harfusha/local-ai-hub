import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStatus, TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
import pytest


def test_process_exit_after_commit_before_publish_recovers_event(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    repo_root = Path(__file__).resolve().parents[1]
    script = """
import os
import sys
sys.path.insert(0, sys.argv[2])
from local_ai_hub.agent_events import AgentEvent, AgentStateStore
store = AgentStateStore(sys.argv[1])
store._publish = lambda _event: os._exit(73)
store.append(AgentEvent.create(
    "task:hard-crash", "task.updated", {"version": 1},
    idempotency_key="hard-crash-after-commit",
))
os._exit(74)
"""

    child = subprocess.run(
        [sys.executable, "-B", "-c", script, str(db_path), str(repo_root / "src")],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert child.returncode == 73, child.stderr
    recovered = AgentStateStore(db_path).event_page("task:hard-crash")
    assert recovered["success"] is True
    assert [event["kind"] for event in recovered["events"]] == ["task.updated"]
    assert recovered["events"][0]["seq"] == 1
    assert recovered["last_seq"] == recovered["next_seq"] == 1


@pytest.mark.parametrize("operation", ["create", "transition"])
def test_process_exit_after_task_commit_before_publish_recovers_projection_and_cursor(
    tmp_path, operation
):
    db_path = tmp_path / "agent_state.sqlite3"
    repo_root = Path(__file__).resolve().parents[1]
    task_id = f"task-hard-crash-{operation}"
    if operation == "transition":
        TaskStore(AgentStateStore(db_path)).create(
            GoalContract(goal="recover committed task transition"),
            ScopeContext(task_id=task_id),
            task_id=task_id,
        )

    script = """
import os
import sys
sys.path.insert(0, sys.argv[4])
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStatus, TaskStore
store = AgentStateStore(sys.argv[1])
store._publish = lambda _event: os._exit(73)
tasks = TaskStore(store)
task_id = sys.argv[3]
if sys.argv[2] == "create":
    tasks.create(
        GoalContract(goal="recover committed task creation"),
        ScopeContext(task_id=task_id),
        task_id=task_id,
    )
else:
    tasks.transition(
        task_id, TaskStatus.ACTIVE, reason="hard crash", actor="test",
        idempotency_key="hard-crash-task-transition",
    )
os._exit(74)
"""
    child = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            script,
            str(db_path),
            operation,
            task_id,
            str(repo_root / "src"),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert child.returncode == 73, child.stderr
    state_store = AgentStateStore(db_path)
    recovered_task = TaskStore(state_store).get(task_id)
    assert recovered_task is not None
    expected_status = TaskStatus.PLANNED if operation == "create" else TaskStatus.ACTIVE
    assert recovered_task.status is expected_status
    page = state_store.event_page(f"task:{task_id}")
    expected_kinds = ["task.created"]
    if operation == "transition":
        expected_kinds.append("task.transitioned")
    assert [event["kind"] for event in page["events"]] == expected_kinds
    assert [event["seq"] for event in page["events"]] == list(range(1, len(expected_kinds) + 1))
    assert page["last_seq"] == page["next_seq"] == len(expected_kinds)


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_process_exit_during_receipt_write_recovers_atomically(tmp_path, phase):
    db_path = tmp_path / "agent_state.sqlite3"
    repo_root = Path(__file__).resolve().parents[1]
    task_id = f"task-receipt-hard-crash-{phase}"
    TaskStore(AgentStateStore(db_path)).create(
        GoalContract(
            goal="recover receipt write after process exit",
            acceptance_criteria=("tests",),
        ),
        ScopeContext(task_id=task_id),
        task_id=task_id,
    )

    script = """
import inspect
import os
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_tasks import TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore

store = AgentStateStore(sys.argv[1])
task_store = TaskStore(store)
task = task_store.get(sys.argv[4])
owner = task.owner
command_id = "cmd-hard-exit-tests"
repository_revision = sys.argv[5]
proof = {
    "kind": "work_command_verification",
    "passed": True,
    "task_id": sys.argv[4],
    "owner": owner,
    "criterion": "tests",
    "command_id": command_id,
    "exit_code": 0,
    "repository_revision": repository_revision,
    "mutation_generation": 0,
    "result": {"success": True, "exit_code": 0},
}
artifacts = ArtifactStore(Path(sys.argv[1]).parent)
evidence_id = artifacts.put_json(proof, owner, "command_verification")
if sys.argv[2] == "before_commit":
    original = VerificationStore.record_in_transaction
    def exit_before_commit(self, con, receipt, **kwargs):
        result = original(self, con, receipt, **kwargs)
        os._exit(73)
    VerificationStore.record_in_transaction = exit_before_commit
else:
    store._publish = lambda _event: os._exit(73)

receipt_kwargs = {
    "command_id": command_id,
    "repository_revision": repository_revision,
}
if "owner" in VerificationReceipt.__dataclass_fields__:
    receipt_kwargs.update(owner=owner, mutation_generation=0, evidence_type="test")
receipt = VerificationReceipt.create(
    sys.argv[4], "tests", passed=True, evidence_id=evidence_id, **receipt_kwargs
)
verification_kwargs = {"task_store": task_store}
if "artifact_store" in inspect.signature(VerificationStore).parameters:
    verification_kwargs["artifact_store"] = artifacts
VerificationStore(store, **verification_kwargs).record(receipt)
os._exit(74)
"""
    child = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            script,
            str(db_path),
            phase,
            str(repo_root / "src"),
            task_id,
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_root,
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip(),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert child.returncode == 73, child.stderr
    recovered_store = AgentStateStore(db_path)
    recovered_task = TaskStore(recovered_store).get(task_id)
    assert recovered_task is not None
    with closing(sqlite3.connect(db_path)) as con:
        receipt_rows = con.execute(
            "SELECT receipt_id FROM agent_verification_receipts WHERE task_id=?",
            (task_id,),
        ).fetchall()

    if phase == "before_commit":
        assert recovered_task.verification_receipts == {}
        assert receipt_rows == []
        assert recovered_store.events(f"verification:{task_id}") == []
        assert not any(
            event.kind == "task.verified"
            for event in recovered_store.events(f"task:{task_id}")
        )
    else:
        receipt_id = recovered_task.verification_receipts["tests"]
        assert receipt_rows == [(receipt_id,)]
        assert [event.kind for event in recovered_store.events(f"verification:{task_id}")].count(
            "verification.receipt_recorded"
        ) == 1
        assert [event.kind for event in recovered_store.events(f"task:{task_id}")].count(
            "task.verified"
        ) == 1
