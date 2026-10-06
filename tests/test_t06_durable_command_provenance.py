from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from local_ai_hub.commands import CommandBroker


class _Artifacts:
    def __init__(self) -> None:
        self.records: list[tuple[dict[str, Any], str, str]] = []

    def put_json(self, value: dict[str, Any], owner: str, kind: str) -> str:
        artifact_id = f"proof-{len(self.records) + 1}"
        self.records.append((value, owner, kind))
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


def _new_broker(state_dir: Path, artifacts: _Artifacts, verification: _VerificationStore) -> CommandBroker:
    broker = CommandBroker(
        {"server": {"state_dir": str(state_dir)}, "commands": {"enabled": True}},
        artifacts=artifacts,
    )
    broker.set_verification_store(verification)
    return broker


def _pytest_command() -> str:
    return subprocess.list2cmdline([
        sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_smoke.py"
    ])


def _run_pytest(broker: CommandBroker, repo: Path, *, tenant: str, bypass_cache: bool = False) -> dict[str, Any]:
    return broker.run(
        _pytest_command(), str(repo), tenant=tenant, task_id="task-1", criterion="pytest",
        timeout=20, bypass_cache=bypass_cache,
    )


def test_real_broker_execution_record_survives_broker_restart(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    state_dir = tmp_path / "state"
    artifacts = _Artifacts()
    verification = _VerificationStore()
    broker = _new_broker(state_dir, artifacts, verification)

    result = _run_pytest(broker, repo, tenant="tenant-a", bypass_cache=True)

    assert result["success"] is True, result
    receipt = result["verification_receipt"]
    command_id = receipt["command_id"]
    assert len(command_id) == 32
    restarted = _new_broker(state_dir, _Artifacts(), _VerificationStore())
    record = restarted.get_command_execution_record(
        command_id, tenant="tenant-a", task_id="task-1", repository_root=str(repo)
    )
    assert record is not None
    assert record["command_id"] == command_id
    assert record["tenant_identity"] == restarted._tenant_identity("tenant-a")
    assert record["task_id"] == "task-1"
    assert record["repository_root"] == str(repo.resolve())
    assert record["command_sha256"] == artifacts.records[0][0]["command_sha256"]
    assert record["evidence_id"] == receipt["evidence_id"]
    assert record["receipt_sha256"]
    assert record["repository_root_sha256"]
    assert record["exit_code"] == 0
    assert record["cached"] is False
    assert restarted.get_command_execution_record(
        command_id, tenant="other-tenant", task_id="task-1", repository_root=str(repo)
    ) is None
    assert restarted.get_command_execution_record(
        command_id, tenant="tenant-a", task_id="other-task", repository_root=str(repo)
    ) is None
    assert restarted.get_command_execution_record(
        command_id, tenant="tenant-a", task_id="task-1", repository_root=str(tmp_path)
    ) is None


def test_self_consistent_client_receipt_has_no_broker_execution_record(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    artifacts = _Artifacts()
    verification = _VerificationStore()
    broker = _new_broker(state_dir, artifacts, verification)
    fabricated_id = "a" * 32
    proof = {
        "kind": "work_command_verification", "passed": True, "task_id": "task-1",
        "command_id": fabricated_id, "command_sha256": "b" * 64, "exit_code": 0,
    }
    evidence_id = artifacts.put_json(proof, "tenant-a", "command_verification")
    verification.record({"task_id": "task-1", "criterion": "pytest", "command_id": fabricated_id,
                         "evidence_id": evidence_id, "passed": True})

    assert broker.get_command_execution_record(
        fabricated_id, tenant="tenant-a", task_id="task-1", repository_root=str(tmp_path / "repo")
    ) is None
    assert not (state_dir / "command-transactions" / "execution-records").exists()


def test_cache_hit_cannot_mint_a_second_execution_record(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    state_dir = tmp_path / "state"
    artifacts = _Artifacts()
    verification = _VerificationStore()
    broker = _new_broker(state_dir, artifacts, verification)

    first = _run_pytest(broker, repo, tenant="tenant-a")
    assert first["success"] is True, first
    assert first.get("cache_hit") is False
    assert len(artifacts.records) == 1
    assert len(verification.receipts) == 1

    second = _run_pytest(broker, repo, tenant="tenant-a")
    assert second["success"] is True, second
    assert second["cache_hit"] is True
    assert len(artifacts.records) == 1
    assert len(verification.receipts) == 1
    assert len(list((state_dir / "command-transactions" / "execution-records").glob("*.json"))) == 1
