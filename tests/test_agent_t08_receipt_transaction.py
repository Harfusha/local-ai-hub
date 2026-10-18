from contextlib import closing
from pathlib import Path
import subprocess
import sys

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskCheckpoint, TaskStore
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.commands import CommandBroker
from local_ai_hub.sqlite_support import connect_sqlite
from local_ai_hub.project_config import resolve_project_context
from local_ai_hub.process_utils import hidden_run_kwargs


def _repository_fixture(tmp_path):
    repo_root = tmp_path / "repository"
    (repo_root / "tests").mkdir(parents=True)
    (repo_root / ".local-ai.toml").write_text(
        '[commands.test]\nargv = ["python", "-B", "-c", "print(1)"]\n',
        encoding="utf-8",
    )
    _write_passing_test(repo_root)
    subprocess.run(["git", "init", "--quiet"], cwd=repo_root, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.name", "Hub test"], cwd=repo_root, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "config", "user.email", "hub-test@example.invalid"], cwd=repo_root, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "add", ".local-ai.toml", "tests/test_receipt_fixture.py"], cwd=repo_root, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(["git", "commit", "--quiet", "-m", "initialize receipt fixture"], cwd=repo_root, check=True, timeout=10, **hidden_run_kwargs())
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, timeout=10, **hidden_run_kwargs(text=True)
    ).stdout.strip()
    coordination_id = resolve_project_context(repo_root, tmp_path / "state").coordination_id
    return repo_root, revision, coordination_id


def _write_passing_test(repo_root):
    tests = repo_root / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "test_receipt_fixture.py").write_text(
        "import unittest\n"
        "class ReceiptFixture(unittest.TestCase):\n"
        "    def test_arithmetic(self):\n"
        "        self.assertEqual(2 + 2, 4)\n",
        encoding="utf-8",
    )


class _RepoState:
    def fingerprint(self, cwd):
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, check=True,
            capture_output=True, timeout=10, **hidden_run_kwargs(text=True),
        ).stdout.strip()
        return {"fingerprint": revision, "root": str(Path(cwd).resolve())}


def _command_broker_for_task(tmp_path, task_id):
    repo_root, revision, coordination_id = _repository_fixture(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    state_store = AgentStateStore(state_dir / "agent_state.sqlite")
    tasks = TaskStore(state_store)
    artifacts = ArtifactStore(state_dir)
    verifier = VerificationStore(state_store, task_store=tasks, artifact_store=artifacts)
    tasks.set_verification_store(verifier)
    tasks.create(
        GoalContract(goal="command receipt contract", acceptance_criteria=("tests",)),
        ScopeContext(repository_id=coordination_id, task_id=task_id),
        task_id=task_id,
        actor="agent",
        repo_root=str(repo_root.resolve()),
        repository_revision=revision,
    )
    broker = CommandBroker(
        {
            "server": {"state_dir": str(state_dir)},
            "commands": {"enabled": True, "allow_read": True, "allow_validation": True},
        },
        artifacts,
        repo_state=_RepoState(),
    )
    broker.set_verification_store(verifier)
    return broker, verifier, artifacts


def _passing_test_command(_repo_root):
    return f'"{sys.executable}" -m unittest discover -s tests -q'


def test_receipt_projection_helper_is_caller_transaction_atomic(tmp_path):
    db_path = tmp_path / "agent_state.sqlite"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    task_id = "task-caller-owned-receipt"
    tasks.create(
        GoalContract(goal="caller-owned receipt", acceptance_criteria=("tests",)),
        ScopeContext(task_id=task_id),
        task_id=task_id,
    )
    stream_id = f"task:{task_id}"

    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        con.execute("BEGIN IMMEDIATE")
        pending, pending_event = tasks.add_verification_receipt_in_transaction(
            con, task_id, "tests", "receipt-rolled-back"
        )
        assert con.in_transaction is True
        assert pending is not None
        assert pending.verification_receipts == {"tests": "receipt-rolled-back"}
        assert pending_event is not None
        assert pending_event.kind == "task.verified"
        con.execute("ROLLBACK")

    rolled_back = tasks.get(task_id)
    assert rolled_back is not None
    assert rolled_back.verification_receipts == {}
    assert not any(event.kind == "task.verified" for event in state_store.events(stream_id))

    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        con.execute("BEGIN IMMEDIATE")
        committed, committed_event = tasks.add_verification_receipt_in_transaction(
            con, task_id, "tests", "receipt-committed"
        )
        assert con.in_transaction is True
        assert committed_event is not None
        con.execute("COMMIT")

    saved = tasks.get(task_id)
    assert saved is not None
    assert saved.verification_receipts == {"tests": "receipt-committed"}
    verified = [event for event in state_store.events(stream_id) if event.kind == "task.verified"]
    assert [event.event_id for event in verified] == [committed_event.event_id]


def test_command_receipt_is_durable_and_allows_task_completion(tmp_path, monkeypatch):
    repo_root, revision, coordination_id = _repository_fixture(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    state_store = AgentStateStore(state_dir / "agent_state.sqlite")
    tasks = TaskStore(state_store)
    artifacts = ArtifactStore(state_dir)
    verifier = VerificationStore(state_store, task_store=tasks, artifact_store=artifacts)
    tasks.set_verification_store(verifier)
    task_id = "command-receipt-completion"
    tasks.create(
        GoalContract(goal="command receipt completion", acceptance_criteria=("tests",)),
        ScopeContext(repository_id=coordination_id, task_id=task_id),
        task_id=task_id,
        actor="agent",
        repo_root=str(repo_root.resolve()),
        repository_revision=revision,
    )
    broker = CommandBroker(
        {
            "server": {"state_dir": str(state_dir)},
            "commands": {"enabled": True, "allow_read": True, "allow_validation": True},
        },
        artifacts,
        repo_state=_RepoState(),
    )
    broker.set_verification_store(verifier)

    publication_calls = 0
    ordered_publication = state_store.ordered_event_publication

    def tracked_publication(con):
        nonlocal publication_calls
        publication_calls += 1
        return ordered_publication(con)

    monkeypatch.setattr(state_store, "ordered_event_publication", tracked_publication)
    result = broker.run(
        _passing_test_command(repo_root),
        str(repo_root),
        task_id=task_id,
        criterion="tests",
    )

    assert result["exit_code"] == 0
    assert "verification_receipt_warning" not in result
    assert publication_calls == 1
    receipt_data = result["verification_receipt"]
    assert receipt_data["evidence_id"] == result["verification_evidence_id"]
    assert artifacts.get(receipt_data["evidence_id"])["success"] is True

    reloaded_state_store = AgentStateStore(state_dir / "agent_state.sqlite")
    reloaded_tasks = TaskStore(reloaded_state_store)
    reloaded_verifier = VerificationStore(
        reloaded_state_store, task_store=reloaded_tasks, artifact_store=ArtifactStore(state_dir),
    )
    reloaded_tasks.set_verification_store(reloaded_verifier)
    reloaded_broker = CommandBroker(
        {
            "server": {"state_dir": str(state_dir)},
            "commands": {"enabled": True, "allow_read": True, "allow_validation": True},
        },
        ArtifactStore(state_dir),
        repo_state=_RepoState(),
    )
    reloaded_broker.set_task_store(reloaded_tasks)
    reloaded_broker.set_verification_store(reloaded_verifier)
    reloaded_verifier.set_command_execution_record_lookup(
        reloaded_broker.get_command_execution_record
    )
    current_revision = _RepoState().fingerprint(repo_root)["fingerprint"]
    completion = reloaded_verifier.completion(
        task_id, current_revision=current_revision, project_root=repo_root,
    )
    assert completion.complete is True
    assert len(completion.receipts) == 1
    assert any(
        event.kind == "verification.receipt_recorded"
        for event in reloaded_state_store.events(f"verification:{task_id}")
    )
    current_task = reloaded_tasks.get(task_id)
    assert current_task is not None
    completion_state_data = dict(current_task.checkpoint.state_data)
    completion_state_data["repository_revision"] = current_revision
    completion_checkpoint = TaskCheckpoint(
        phase=current_task.checkpoint.phase,
        next_action=current_task.checkpoint.next_action,
        affected_paths=current_task.checkpoint.affected_paths,
        evidence_ids=current_task.checkpoint.evidence_ids,
        blockers=current_task.checkpoint.blockers,
        state_data=completion_state_data,
    )
    completed = reloaded_tasks.complete(
        task_id,
        actor="agent",
        reason="verified command receipt",
        idempotency_key="command-receipt-completion",
        checkpoint=completion_checkpoint,
    )
    assert completed.status.value == "completed"


def test_failed_command_does_not_create_passed_verification_receipt(tmp_path):
    task_id = "failed-command-no-receipt"
    broker, verifier, _artifacts = _command_broker_for_task(tmp_path, task_id)
    command = _passing_test_command(tmp_path / "repository")
    (tmp_path / "repository" / "tests" / "test_receipt_fixture.py").write_text(
        "import unittest\nclass FailingReceiptFixture(unittest.TestCase):\n"
        "    def test_failure(self):\n        self.fail('intentional failure')\n",
        encoding="utf-8",
    )

    result = broker.run(
        command,
        str(tmp_path / "repository"),
        task_id=task_id,
        criterion="tests",
    )

    assert result["success"] is False
    assert result["exit_code"] == 1
    assert "verification_receipt" not in result
    assert "verification_receipt_warning" not in result
    completion = verifier.completion(task_id)
    assert completion.complete is False
    assert completion.receipts == ()


@pytest.mark.parametrize("failure_point", ("evidence", "receipt"))
def test_receipt_persistence_failure_warns_without_overwriting_command_result(
    tmp_path, monkeypatch, failure_point
):
    task_id = f"receipt-write-failure-{failure_point}"
    broker, verifier, artifacts = _command_broker_for_task(tmp_path, task_id)

    def fail_write(*_args, **_kwargs):
        raise RuntimeError(f"synthetic {failure_point} persistence failure")

    if failure_point == "evidence":
        monkeypatch.setattr(artifacts, "put_json", fail_write)
    else:
        monkeypatch.setattr(verifier, "record", fail_write)
    command = _passing_test_command(tmp_path / "repository")

    result = broker.run(
        command,
        str(tmp_path / "repository"),
        task_id=task_id,
        criterion="tests",
    )

    assert result["success"] is True
    assert result["exit_code"] == 0
    assert result["verification_receipt_warning"] == (
        "command succeeded but durable verification evidence was unavailable"
    )
    assert "verification_receipt" not in result
    assert verifier.completion(task_id).receipts == ()


@pytest.mark.parametrize("command", ("python -m compileall tests", "python -c pass"))
def test_success_without_test_execution_does_not_mint_test_receipt(tmp_path, command):
    task_id = "no-tests-no-receipt"
    broker, verifier, _artifacts = _command_broker_for_task(tmp_path, task_id)
    (tmp_path / "repository" / "tests").mkdir(exist_ok=True)
    result = broker.run(command, str(tmp_path / "repository"), task_id=task_id, criterion="tests")
    assert result["success"] is True
    assert result["exit_code"] == 0
    assert "verification_receipt" not in result
    assert verifier.completion(task_id).complete is False
