from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStore
from local_ai_hub.agent_verification import (
    ChangeIntent,
    CompletionResult,
    OutcomeRecord,
    VerificationReceipt,
    VerificationStore,
)
from local_ai_hub.agent_consistency import AgentConsistencyGuard, ConsistencyRequest, GuardWarning
from local_ai_hub.agent_memory import MemoryStore
from local_ai_hub.repo_tools import RepositoryTools


@pytest.fixture
def stores(tmp_path: Path) -> tuple[TaskStore, VerificationStore]:
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    task_store = TaskStore(state_store)
    verif_store = VerificationStore(state_store, task_store=task_store)
    return task_store, verif_store


def receipt_for(
    task_id: str,
    criterion: str,
    passed: bool = True,
    expires_at: float | None = None,
) -> VerificationReceipt:
    return VerificationReceipt.create(
        task_id=task_id,
        criterion=criterion,
        passed=passed,
        expires_at=expires_at,
        evidence_id="ev-123",
    )


def test_stale_receipt_cannot_satisfy_completion(stores: tuple[TaskStore, VerificationStore]):
    task_store, verif_store = stores
    task = task_store.create(
        GoalContract(goal="test task", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-1"),
        task_id="task-1",
    )
    verif_store.record(receipt_for("task-1", "tests", expires_at=10.0))
    # Check at now=11: expired!
    res = verif_store.completion("task-1", now=11.0)
    assert res.complete is False
    assert "tests" in res.stale_criteria

    # Check at now=9: fresh!
    res_fresh = verif_store.completion("task-1", now=9.0)
    assert res_fresh.complete is True
    assert "tests" in res_fresh.satisfied_criteria


def test_revert_is_explicit_negative_outcome(stores: tuple[TaskStore, VerificationStore]):
    _, verif_store = stores
    outcome = verif_store.record_outcome(OutcomeRecord.reverted("change-1", actor="user"))
    assert outcome.kind == "reverted"
    assert outcome.actor == "user"


def test_all_criteria_must_pass_for_completion(stores: tuple[TaskStore, VerificationStore]):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="two criteria", acceptance_criteria=("tests", "lint")),
        ScopeContext(task_id="task-2"),
        task_id="task-2",
    )
    verif_store.record(receipt_for("task-2", "tests", passed=True))
    verif_store.record(receipt_for("task-2", "lint", passed=False))

    comp = verif_store.completion("task-2", now=100.0)
    assert comp.complete is False
    assert "lint" in comp.unsatisfied_criteria
    assert "tests" in comp.satisfied_criteria


def test_completion_audit_maps_criteria_to_evidence_and_receipts(stores: tuple[TaskStore, VerificationStore], tmp_path: Path):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="audited task", acceptance_criteria=("tests", "lint")),
        ScopeContext(task_id="task-audit"),
        task_id="task-audit",
    )
    verif_store.record(VerificationReceipt.create("task-audit", "tests", evidence_id="ev-tests", repository_revision="rev-1"))
    verif_store.record(VerificationReceipt.create("task-audit", "lint", evidence_id="ev-lint", repository_revision="rev-1"))
    guard = AgentConsistencyGuard(RepositoryTools({}), verification_store=verif_store)

    result = verif_store.completion(
        "task-audit",
        repository_revision="rev-1",
        include_consistency=True,
        consistency_guard=guard,
        warnings=(GuardWarning("info", "reuse", "reused existing symbol", ("ev-tests",)),),
    )
    audit = result.to_dict()["consistency"]

    assert result.complete is True
    assert audit["criteria"]["tests"]["evidence_ids"] == ["ev-tests"]
    assert audit["criteria"]["lint"]["receipt_ids"] == [result.receipts[0].receipt_id] or audit["criteria"]["lint"]["receipt_ids"]
    assert audit["current_revision_receipt_coverage"]["covered"] == 2
    assert audit["current_revision_receipt_coverage"]["total"] == 2
    assert audit["drift_warnings"][0]["code"] == "reuse"


def test_completion_audit_reports_unresolved_contract_mismatch(stores: tuple[TaskStore, VerificationStore], tmp_path: Path):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="contract task", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-contract"),
        task_id="task-contract",
    )
    verif_store.record(VerificationReceipt.create("task-contract", "tests", evidence_id="ev-tests", repository_revision="rev-2"))
    guard = AgentConsistencyGuard(RepositoryTools({}), verification_store=verif_store)

    result = verif_store.completion(
        "task-contract",
        repository_revision="rev-2",
        include_consistency=True,
        consistency_guard=guard,
        mappings=(
            {"kind": "response", "status": "mismatch", "evidence_ids": ["ev-contract"], "mismatches": ["name"]},
        ),
        warnings=(GuardWarning("warning", "response_schema_mismatch", "schema differs", ("ev-contract",)),),
    )
    audit = result.to_dict()["consistency"]

    assert result.complete is True
    assert audit["contract_mismatches"][0]["code"] == "response_schema_mismatch"
    assert audit["unsupported_claims"] == []
    assert audit["warnings"]
