from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, ScopeContext, TaskCheckpoint, TaskStatus, TaskStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.app import LocalAIApp
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.commands import CommandBroker


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def _actual_broker_task(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "T09")
    _git(repo, "config", "user.email", "t09@example.invalid")
    (repo / "test_smoke.py").write_text(
        "def test_smoke():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )
    _git(repo, "add", "test_smoke.py")
    _git(repo, "commit", "-qm", "seed")
    revision = _git(repo, "rev-parse", "HEAD")

    state_dir = tmp_path / "state"
    state = AgentStateStore(state_dir / "agent_state.sqlite3", enabled=True)
    tasks = TaskStore(state)
    artifacts = ArtifactStore(state_dir / "artifacts")
    task_id = "broker-backed-completion"
    tenant = "agent"
    tasks.create(
        GoalContract(goal="broker-backed completion", acceptance_criteria=("pytest",)),
        ScopeContext(repository_id=str(repo.resolve()), task_id=task_id),
        task_id=task_id,
        actor=tenant,
        repo_root=str(repo.resolve()),
    )
    tasks.checkpoint(
        task_id,
        TaskCheckpoint(state_data={
            "repo_root": str(repo.resolve()),
            "repository_revision": revision,
            "mutation_generation": 0,
        }),
        actor=tenant,
        idempotency_key="trusted-revision",
    )
    verifier = VerificationStore(state, task_store=tasks, artifact_store=artifacts)
    broker = CommandBroker(
        {"server": {"state_dir": str(state_dir)}, "commands": {"enabled": True}},
        artifacts=artifacts,
    )
    broker.set_task_store(tasks)
    broker.set_verification_store(verifier)
    verifier.set_command_execution_record_lookup(broker.get_command_execution_record)
    command = subprocess.list2cmdline(
        [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_smoke.py"]
    )
    result = broker.run(
        command,
        str(repo),
        tenant=tenant,
        task_id=task_id,
        criterion="pytest",
        timeout=30,
        bypass_cache=True,
    )
    assert result.get("success") is True, result
    receipt = result.get("verification_receipt")
    assert isinstance(receipt, dict)
    assert receipt.get("command_id")
    task_state = tasks.get(task_id)
    assert task_state is not None
    task_state_data = dict(task_state.checkpoint.state_data)
    task_state_data["repository_revision"] = str(receipt["repository_revision"])
    tasks.checkpoint(
        task_id,
        TaskCheckpoint(
            phase=task_state.checkpoint.phase,
            next_action=task_state.checkpoint.next_action,
            affected_paths=task_state.checkpoint.affected_paths,
            evidence_ids=task_state.checkpoint.evidence_ids,
            blockers=task_state.checkpoint.blockers,
            state_data=task_state_data,
        ),
        actor=tenant,
        idempotency_key="broker-revision",
    )
    return tasks, verifier, broker, task_id, tenant, repo, receipt



def test_app_wires_scoped_broker_lookup_into_completion(tmp_path: Path):
    state_dir = tmp_path / "app-state"
    config_path = tmp_path / "hub.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11499\nstate_dir = "{state_dir.as_posix()}"\n'
        "\n[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    try:
        lookup = app.agent_verification.command_execution_record_lookup
        assert getattr(lookup, "__self__", None) is app.commands
        assert getattr(lookup, "__func__", None) is app.commands.get_command_execution_record.__func__
        assert app.agent_verification.require_execution_provenance is True
    finally:
        app.close()

def test_actual_broker_receipt_completes_agent_task(tmp_path: Path):
    tasks, verifier, broker, task_id, tenant, repo, receipt = _actual_broker_task(tmp_path)
    stored = broker.get_command_execution_record(
        receipt["command_id"],
        tenant=tenant,
        task_id=task_id,
        repository_root=str(repo),
    )
    assert stored is not None
    assert stored["evidence_id"] == receipt["evidence_id"]
    assert stored["receipt_sha256"]
    completed = tasks.complete(task_id)
    assert completed.status == TaskStatus.COMPLETED


@pytest.mark.parametrize("damage", ["missing", "receipt", "evidence", "generation", "cache"])
def test_actual_broker_completion_rejects_missing_or_forged_sidecar(
    tmp_path: Path, damage: str
):
    tasks, verifier, broker, task_id, tenant, repo, receipt = _actual_broker_task(tmp_path)
    path = broker._command_execution_record_path(receipt["command_id"])
    if damage == "missing":
        path.unlink()
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("record_sha256", None)
        if damage == "receipt":
            payload["receipt_sha256"] = "f" * 64
        elif damage == "evidence":
            payload["evidence_id"] = "fabricated-evidence"
        elif damage == "generation":
            payload["mutation_generation"] = int(payload["mutation_generation"]) + 1
        elif damage == "cache":
            payload["cached"] = True
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        payload["record_sha256"] = hashlib.sha256(canonical).hexdigest()
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    with pytest.raises(CompletionGateError):
        tasks.complete(task_id)
    current = tasks.get(task_id)
    assert current is not None
    assert current.status != TaskStatus.COMPLETED
