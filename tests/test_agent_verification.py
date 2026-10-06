from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, TaskStore
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
from local_ai_hub.sqlite_support import connect_sqlite


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


def test_completion_does_not_accept_orphaned_receipt_with_task_store(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    task_store = TaskStore(state_store)
    receipt = receipt_for("orphan-task", "tests")
    VerificationStore(state_store, task_store=task_store).record(receipt)

    completion = VerificationStore(state_store, task_store=task_store).completion("orphan-task")

    assert completion.complete is False
    assert completion.satisfied_criteria == ()
    assert completion.unsatisfied_criteria == ("tests",)
    assert completion.receipts[0].receipt_id == receipt.receipt_id
    assert [event.kind for event in state_store.events("verification:orphan-task")] == [
        "verification.receipt_recorded"
    ]


def test_receipt_identity_metadata_survives_restart(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    task_store = TaskStore(state_store)
    task = task_store.create(
        GoalContract(goal="receipt metadata", acceptance_criteria=("tests",)),
        ScopeContext(task_id="receipt-metadata-task"),
        task_id="receipt-metadata-task",
    )
    receipt = VerificationReceipt.create(
        task.task_id,
        "tests",
        evidence_id="evidence-metadata",
        owner=task.owner,
        mutation_generation=3,
        evidence_type="test",
        details={"source": "test"},
    )
    VerificationStore(state_store, task_store=task_store).record(receipt)

    restarted_store = AgentStateStore(db_path)
    completion = VerificationStore(
        restarted_store, task_store=TaskStore(restarted_store)
    ).completion(task.task_id)

    restored = completion.receipts[0]
    assert completion.complete is True
    assert (restored.owner, restored.mutation_generation, restored.evidence_type) == (
        task.owner,
        3,
        "test",
    )
    assert restored.details == {"source": "test"}


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


def test_verification_store_record_methods_are_noops_when_agent_state_disabled(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "disabled.sqlite3", enabled=False)
    store = VerificationStore(state_store)
    receipt = receipt_for("disabled-task", "tests")
    change = ChangeIntent.create("disabled-task", ("src/app.py",))
    outcome = OutcomeRecord.accepted(change.change_id, task_id="disabled-task")

    assert store.record(receipt) is receipt
    assert store.record_change(change) is change
    assert store.record_outcome(outcome) is outcome
    assert not state_store.db_path.exists()


@pytest.mark.parametrize(
    ("task_id", "criterion"),
    [("", "tests"), ("task-1", "")],
)
def test_verification_receipts_require_task_and_criterion(task_id: str, criterion: str):
    with pytest.raises(ValueError, match="requires"):
        VerificationReceipt.create(task_id, criterion)


def test_passed_verification_receipt_requires_evidence_id():
    with pytest.raises(ValueError, match="evidence_id"):
        VerificationReceipt.create("task-proof", "tests", evidence_id=" ")


def test_verification_receipt_parser_requires_explicit_boolean_passed():
    base = {"receipt_id": "receipt-1", "task_id": "task-1", "criterion": "tests"}
    payloads = (
        base,
        {**base, "passed": "false"},
        {**base, "passed": "true"},
        {**base, "passed": 1},
        {**base, "passed": None},
    )

    assert all(
        VerificationReceipt.from_dict(payload).passed is False
        for payload in payloads
    )


def test_verifier_exception_cannot_become_a_passing_receipt(
    stores: tuple[TaskStore, VerificationStore],
):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="verifier exception", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-verifier-exception"),
        task_id="task-verifier-exception",
    )

    try:
        raise RuntimeError("verifier unavailable")
    except RuntimeError as error:
        verifier_result = error

    receipt = VerificationReceipt.create(
        "task-verifier-exception",
        "tests",
        passed=verifier_result,
        evidence_id="ev-verifier-error",
    )
    assert receipt.passed is False

    verif_store.record(receipt)
    completion = verif_store.completion("task-verifier-exception")
    assert completion.complete is False
    assert "tests" in completion.unsatisfied_criteria


def test_explicit_verifier_failure_cannot_satisfy_completion(
    stores: tuple[TaskStore, VerificationStore],
):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="verifier failure", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-verifier-failure"),
        task_id="task-verifier-failure",
    )

    receipt = VerificationReceipt.create(
        "task-verifier-failure", "tests", passed=False, evidence_id="ev-failed"
    )
    verif_store.record(receipt)

    completion = verif_store.completion("task-verifier-failure")
    assert receipt.passed is False
    assert completion.complete is False
    assert "tests" in completion.unsatisfied_criteria


def test_completion_rejects_receipt_missing_from_store(stores: tuple[TaskStore, VerificationStore]):
    task_store, _ = stores
    task_store.create(
        GoalContract(goal="missing receipt", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-missing"),
        task_id="task-missing",
    )
    task_store.add_verification_receipt("task-missing", "tests", "missing-row")

    with pytest.raises(CompletionGateError, match="missing-row"):
        task_store.complete("task-missing")


@pytest.mark.parametrize(
    ("receipt_task_id", "receipt_criterion"),
    [("other-task", "tests"), ("task-mismatch", "lint")],
)
def test_completion_rejects_receipt_with_mismatched_identity(
    stores: tuple[TaskStore, VerificationStore],
    receipt_task_id: str,
    receipt_criterion: str,
):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="identity check", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-mismatch"),
        task_id="task-mismatch",
    )
    receipt = receipt_for(receipt_task_id, receipt_criterion)
    verif_store.record(receipt)
    task_store.add_verification_receipt("task-mismatch", "tests", receipt.receipt_id)

    with pytest.raises(CompletionGateError, match="task-mismatch|criterion"):
        task_store.complete("task-mismatch")


def test_completion_fails_closed_and_preserves_receipt_lookup_error(
    stores: tuple[TaskStore, VerificationStore], monkeypatch: pytest.MonkeyPatch
):
    task_store, _ = stores
    task_store.create(
        GoalContract(goal="database failure", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-db-error"),
        task_id="task-db-error",
    )
    task_store.add_verification_receipt("task-db-error", "tests", "receipt-db-error")

    from local_ai_hub.sqlite_support import connect_sqlite

    class FailingReceiptLookup:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, query, *args, **kwargs):
            if "agent_verification_receipts" in query:
                raise RuntimeError("receipt database unavailable")
            return self.connection.execute(query, *args, **kwargs)

        def close(self):
            self.connection.close()

        def __getattr__(self, name):
            return getattr(self.connection, name)

    def fail_lookup(*args, **kwargs):
        return FailingReceiptLookup(connect_sqlite(*args, **kwargs))

    monkeypatch.setattr("local_ai_hub.agent_tasks.connect_sqlite", fail_lookup)
    with pytest.raises(CompletionGateError, match="receipt-db-error") as error:
        task_store.complete("task-db-error")

    assert isinstance(error.value.__cause__, RuntimeError)
    assert "receipt database unavailable" in str(error.value.__cause__)


def test_failed_receipt_storage_cannot_satisfy_completion(
    stores: tuple[TaskStore, VerificationStore], monkeypatch: pytest.MonkeyPatch
):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="storage failure", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-store-error"),
        task_id="task-store-error",
    )

    def fail_store(*args, **kwargs):
        raise RuntimeError("receipt write failed")

    monkeypatch.setattr("local_ai_hub.agent_verification.connect_sqlite", fail_store)
    with pytest.raises(RuntimeError, match="receipt write failed"):
        verif_store.record(receipt_for("task-store-error", "tests"))
    monkeypatch.undo()

    with pytest.raises(CompletionGateError, match="tests"):
        task_store.complete("task-store-error")


def test_valid_receipt_allows_task_completion(stores: tuple[TaskStore, VerificationStore]):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="valid proof", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-valid"),
        task_id="task-valid",
    )
    receipt = receipt_for("task-valid", "tests")
    verif_store.record(receipt)

    completed = task_store.complete("task-valid")

    assert completed.status.value == "completed"
    assert completed.verification_receipts["tests"] == receipt.receipt_id


def test_verification_store_prunes_legacy_invalid_receipts(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "legacy.sqlite3")
    VerificationStore(state_store)
    con = connect_sqlite(state_store.db_path)
    try:
        con.execute(
            "INSERT INTO agent_verification_receipts "
            "(receipt_id, task_id, criterion, change_intent_id, evidence_id, command_id, "
            "repository_revision, observed_at, expires_at, passed, details) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy-invalid", "task-legacy", "", "", "", "", "", 1.0, None, 1, "{}"),
        )
    finally:
        con.close()

    VerificationStore(state_store)
    con = connect_sqlite(state_store.db_path)
    try:
        assert con.execute(
            "SELECT 1 FROM agent_verification_receipts WHERE receipt_id=?",
            ("legacy-invalid",),
        ).fetchone() is None
    finally:
        con.close()


def test_current_revision_rejects_fresh_receipt_from_other_revision(stores: tuple[TaskStore, VerificationStore]):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="revision task", acceptance_criteria=("tests",)),
        ScopeContext(task_id="revision-task"),
        task_id="revision-task",
    )
    verif_store.record(VerificationReceipt.create(
        "revision-task", "tests", evidence_id="ev-old-revision",
        repository_revision="old-revision", expires_at=100.0,
    ))

    result = verif_store.completion("revision-task", now=50.0, current_revision="new-revision")

    assert result.complete is False
    assert result.satisfied_criteria == ()
    assert result.stale_criteria == ("tests",)


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
