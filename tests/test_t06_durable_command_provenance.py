from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from local_ai_hub.commands import CommandBroker
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStore
from local_ai_hub.project_config import resolve_project_context


class _Artifacts:
    def __init__(self) -> None:
        self.records: list[tuple[dict[str, Any], str]] = []

    def put_json(self, value: dict[str, Any], *, kind: str) -> str:
        artifact_id = f"proof-{len(self.records) + 1}"
        self.records.append((value, kind))
        return artifact_id


class _VerificationStore:
    def __init__(self) -> None:
        self.receipts: list[Any] = []

    def record(self, receipt: Any) -> Any:
        self.receipts.append(receipt)
        return receipt


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, timeout=10)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "T06")
    _git(repo, "config", "user.email", "t06@example.invalid")
    (repo / "test_smoke.py").write_text("def test_smoke():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    _git(repo, "add", "test_smoke.py")
    _git(repo, "commit", "-qm", "seed")
    return repo


def _task_store(state_dir: Path, repo: Path, *, create: bool = False) -> TaskStore:
    store = TaskStore(AgentStateStore(state_dir / "agent_state.sqlite"))
    if create:
        coordination_id = resolve_project_context(repo, state_dir).coordination_id
        assert isinstance(coordination_id, str) and coordination_id
        store.create(
            GoalContract(goal="record actual command execution"),
            ScopeContext(
                task_id="task-1",
                repository_id=coordination_id,
                session_id="session-t06",
            ),
            task_id="task-1",
            actor="agent",
            repo_root=str(repo),
        )
    return store


def _new_broker(
    state_dir: Path, artifacts: _Artifacts, verification: _VerificationStore,
    task_store: TaskStore | None = None,
) -> CommandBroker:
    broker = CommandBroker(
        {"server": {"state_dir": str(state_dir)}, "commands": {"enabled": True}},
        artifacts=artifacts,
    )
    broker.set_verification_store(verification)
    if task_store is not None:
        broker.set_task_store(task_store)
    return broker


def _pytest_command() -> str:
    return subprocess.list2cmdline([
        sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_smoke.py"
    ])


def _run_pytest(broker: CommandBroker, repo: Path, *, bypass_cache: bool = False) -> dict[str, Any]:
    return broker.run(
        _pytest_command(), str(repo),  task_id="task-1", criterion="pytest",
        timeout=20, bypass_cache=bypass_cache,
    )


def test_real_broker_execution_record_survives_broker_restart(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    state_dir = tmp_path / "state"
    artifacts = _Artifacts()
    verification = _VerificationStore()
    broker = _new_broker(state_dir, artifacts, verification, _task_store(state_dir, repo, create=True))

    result = _run_pytest(broker, repo,  bypass_cache=True)

    assert result["success"] is True, result
    receipt = result["verification_receipt"]
    command_id = receipt["command_id"]
    assert len(command_id) == 32
    restarted = _new_broker(state_dir, _Artifacts(), _VerificationStore(), _task_store(state_dir, repo))
    record = restarted.get_command_execution_record(
        command_id,  task_id="task-1", repository_root=str(repo)
    )
    assert record is not None
    assert record["schema"] == "command_execution_record.v2"
    assert record["command_id"] == command_id
    assert record["task_id"] == "task-1"
    assert record["owner"] == "agent"
    assert record["repository_root"] == str(repo.resolve())
    assert record["repository_revision"] == receipt["repository_revision"]
    assert record["command_sha256"] == artifacts.records[0][0]["command_sha256"]
    assert record["evidence_id"] == receipt["evidence_id"]
    assert record["receipt_sha256"]
    assert record["repository_root_sha256"]
    assert record["exit_code"] == 0
    assert record["cached"] is False
    assert restarted.get_command_execution_record(
        command_id,  task_id="task-1", repository_root=str(repo)
    ) == record
    assert restarted.get_command_execution_record(
        command_id,  task_id="other-task", repository_root=str(repo)
    ) is None
    assert restarted.get_command_execution_record(
        command_id,  task_id="task-1", repository_root=str(tmp_path)
    ) is None


def test_self_consistent_client_receipt_has_no_broker_execution_record(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    state_dir = tmp_path / "state"
    artifacts = _Artifacts()
    verification = _VerificationStore()
    broker = _new_broker(state_dir, artifacts, verification, _task_store(state_dir, repo, create=True))
    fabricated_id = "a" * 32
    proof = {
        "kind": "work_command_verification", "passed": True, "task_id": "task-1",
        "command_id": fabricated_id, "command_sha256": "b" * 64, "exit_code": 0,
    }
    evidence_id = artifacts.put_json(proof, kind="command_verification")
    verification.record({"task_id": "task-1", "criterion": "pytest", "command_id": fabricated_id,
                         "evidence_id": evidence_id, "passed": True})

    assert broker.get_command_execution_record(
        fabricated_id, task_id="task-1", repository_root=str(repo)
    ) is None
    assert not (state_dir / "command-transactions" / "execution-records").exists()


def test_cache_hit_cannot_mint_a_second_execution_record(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    state_dir = tmp_path / "state"
    artifacts = _Artifacts()
    verification = _VerificationStore()
    broker = _new_broker(state_dir, artifacts, verification, _task_store(state_dir, repo, create=True))

    first = _run_pytest(broker, repo)
    assert first["success"] is True, first
    assert first.get("cache_hit") is False
    assert len(artifacts.records) == 1
    assert len(verification.receipts) == 1

    second = _run_pytest(broker, repo)
    assert second["success"] is True, second
    assert second["cache_hit"] is True
    assert len(artifacts.records) == 1
    assert len(verification.receipts) == 1
    assert len(list((state_dir / "command-transactions" / "execution-records").glob("*.json"))) == 1
