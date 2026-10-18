from __future__ import annotations

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
        self.records.append((value, kind))
        return "artifact-server-stub"


class _VerificationStore:
    def __init__(self) -> None:
        self.receipts: list[Any] = []

    def record(self, receipt: Any) -> Any:
        self.receipts.append(receipt)
        return receipt


def test_cached_success_does_not_mint_command_verification_receipt(tmp_path: Path) -> None:
    artifacts = _Artifacts()
    verification = _VerificationStore()
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}}, artifacts=artifacts)
    broker.set_verification_store(verification)

    broker._record_command_verification(
        {"success": True, "exit_code": 0},

        task_id="task-a",
        criterion="pytest",
        command="pytest -q",
        command_id="cache_fabricated-id",
        command_digest="a" * 64,
        repository_revision="revision-1",
        duration_ms=2.0,
        project_alias="pytest",
        project_config_digest="config-digest",
        project_environment_sha256="environment-digest",
        cached=True,
    )

    assert artifacts.records == []
    assert verification.receipts == []


def test_command_verification_records_server_run_by_command_id(tmp_path: Path) -> None:
    artifacts = _Artifacts()
    verification = _VerificationStore()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    repository_root = str(tmp_path.resolve())
    coordination_id = resolve_project_context(tmp_path, state_dir).coordination_id
    task_store = TaskStore(AgentStateStore(state_dir / "agent_state.sqlite"))
    task_store.create(
        GoalContract(goal="record command verification"),
        ScopeContext(
            repository_id=coordination_id,
            task_id="task-a",
            session_id="session-t06-server",
        ),
        task_id="task-a",
        actor="agent",
        repo_root=repository_root,
    )
    broker = CommandBroker({"server": {"state_dir": str(state_dir)}}, artifacts=artifacts)
    broker.set_verification_store(verification)
    broker.set_task_store(task_store)
    command_id = "1" * 32

    result = {"success": True, "exit_code": 0}
    broker._record_command_verification(
        result,

        task_id="task-a",
        criterion="pytest",
        command="pytest -q",
        command_id=command_id,
        command_digest="b" * 64,
        repository_revision="revision-2",
        duration_ms=3.0,
        project_alias="pytest",
        project_config_digest="config-digest",
        project_environment_sha256="environment-digest",
        configured_command_sha256="configured-command-digest",
        caller_arguments_sha256="caller-arguments-digest",
        cached=False,
        repository_root=repository_root,
    )

    assert "verification_receipt_warning" not in result, result
    assert len(artifacts.records) == 1
    assert len(verification.receipts) == 1
    scoped_record = broker.get_command_execution_record(
        command_id,  task_id="task-a", repository_root=str(tmp_path)
    )
    assert scoped_record is not None
    assert scoped_record["repository_root"] == str(tmp_path.resolve())
    assert broker.get_command_execution_record(
        command_id,  task_id="task-a", repository_root=str(tmp_path)
    ) == scoped_record
    assert broker.get_command_execution_record(
        command_id,  task_id="other-task", repository_root=str(tmp_path)
    ) is None
    assert broker.get_command_execution_record(
        command_id,  task_id="task-a", repository_root=str(tmp_path.parent)
    ) is None

    record = broker._get_server_command_execution_record(command_id)
    assert record is not None
    assert record["command_id"] == command_id
    assert record["task_id"] == "task-a"
    assert record["schema"] == "command_execution_record.v2"
    assert "tenant_identity" not in record
    assert record["command_sha256"] == "b" * 64
    assert record["evidence_id"] == "artifact-server-stub"
    assert "issuer" not in record
    record["task_id"] = "forged-task"
    restarted = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}}, artifacts=artifacts)
    persisted = restarted._get_server_command_execution_record(command_id)
    assert persisted is not None
    assert persisted["task_id"] == "task-a"
    assert persisted["schema"] == "command_execution_record.v2"
    assert "tenant_identity" not in persisted
