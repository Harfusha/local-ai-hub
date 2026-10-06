from __future__ import annotations

from pathlib import Path
import hashlib
import local_ai_hub.agent_verification as agent_verification_module
from typing import Any
from contextlib import closing
import sqlite3
import json
from dataclasses import replace
import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, InvalidTransitionError, TaskCheckpoint, TaskStatus, TaskStore
from local_ai_hub.agent_verification import (
    ChangeIntent,
    CompletionResult,
    OutcomeRecord,
    VerificationReceipt,
    VerificationStore,
    classify_verification_command,
    criterion_evidence_type,
)
from local_ai_hub.agent_consistency import AgentConsistencyGuard, ConsistencyRequest, GuardWarning
from local_ai_hub.agent_memory import MemoryStore
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.sqlite_support import connect_sqlite


@pytest.fixture
def stores(tmp_path: Path) -> tuple[TaskStore, VerificationStore]:
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    task_store = TaskStore(state_store)
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    verif_store = VerificationStore(state_store, task_store=task_store, artifact_store=artifact_store)
    return task_store, verif_store


def receipt_for(
    task_id: str,
    criterion: str,
    passed: bool = True,
    expires_at: float | None = None,
    *,
    owner: str = "agent",
    repository_revision: str = "rev-1",
    mutation_generation: int = 0,
    evidence_type: str | None = None,
    evidence_id: str = "ev-123",
    command_id: str | None = None,
    artifact_store: ArtifactStore | None = None,
) -> VerificationReceipt:
    kind = evidence_type or criterion_evidence_type(criterion)
    command_key = command_id or ("cmd-123" if kind in {"test", "benchmark"} else "")
    if passed is True and artifact_store is not None:
        proof = {
            "kind": "work_command_verification" if command_key else "work_source_review",
            "passed": True,
            "task_id": task_id,
            "owner": owner,
            "repository_revision": repository_revision,
            "mutation_generation": mutation_generation,
        }
        if command_key:
            proof.update(
                criterion=criterion,
                command_id=command_key,
                exit_code=0,
                result={"success": True, "exit_code": 0},
            )
        else:
            proof["criteria"] = [criterion]
        evidence_id = artifact_store.put_json(
            proof, owner, "command_verification" if command_key else "source_review"
        )
    return VerificationReceipt.create(
        task_id=task_id,
        criterion=criterion,
        passed=passed,
        expires_at=expires_at,
        evidence_id=evidence_id,
        command_id=command_key,
        owner=owner,
        repository_revision=repository_revision,
        mutation_generation=mutation_generation,
        evidence_type=kind,
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
    verif_store.record(receipt_for("task-1", "tests", expires_at=10.0, artifact_store=verif_store.artifact_store))
    # Check at now=11: expired!
    res = verif_store.completion("task-1", now=11.0)
    assert res.complete is False
    assert "tests" in res.stale_criteria

    # Check at now=9: fresh!
    res_fresh = verif_store.completion("task-1", now=9.0)
    assert res_fresh.complete is True
    assert "tests" in res_fresh.satisfied_criteria

def test_generic_benchmark_receipt_without_project_binding_satisfies_completion(
    stores: tuple[TaskStore, VerificationStore],
):
    task_store, verif_store = stores
    task = task_store.create(
        GoalContract(goal="generic benchmark", acceptance_criteria=("benchmark tests",)),
        ScopeContext(task_id="generic-benchmark"),
        task_id="generic-benchmark",
    )
    verif_store.record(
        receipt_for(
            task.task_id,
            "benchmark tests",
            evidence_type="benchmark",
            artifact_store=verif_store.artifact_store,
        )
    )

    result = verif_store.completion(task.task_id)

    assert result.complete is True
    assert "benchmark tests" in result.satisfied_criteria

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
    receipt = receipt_for(receipt_task_id, receipt_criterion, artifact_store=verif_store.artifact_store)
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
        verif_store.record(receipt_for("task-store-error", "tests", artifact_store=verif_store.artifact_store))
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
    receipt = receipt_for("task-valid", "tests", artifact_store=verif_store.artifact_store)
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
    verif_store.record(receipt_for(
        "revision-task", "tests", artifact_store=verif_store.artifact_store,
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
    verif_store.record(receipt_for("task-2", "tests", passed=True, artifact_store=verif_store.artifact_store))
    verif_store.record(receipt_for("task-2", "lint", passed=False, artifact_store=verif_store.artifact_store))

    comp = verif_store.completion("task-2", now=100.0)
    assert comp.complete is False
    assert "lint" in comp.unsatisfied_criteria
    assert "tests" in comp.satisfied_criteria


def test_newer_failed_receipt_supersedes_older_pass(stores: tuple[TaskStore, VerificationStore]):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="latest receipt wins", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-latest-receipt"),
        task_id="task-latest-receipt",
    )
    passing = replace(
        receipt_for("task-latest-receipt", "tests", artifact_store=verif_store.artifact_store),
        observed_at=10.0,
    )
    failing = VerificationReceipt.create(
        "task-latest-receipt", "tests", passed=False, owner="agent",
        command_id="cmd-failed", evidence_type="test",
    )
    failing = replace(failing, observed_at=20.0)
    verif_store.record(passing)
    verif_store.record(failing)

    completion = verif_store.completion("task-latest-receipt", now=30.0)

    assert completion.complete is False
    assert completion.unsatisfied_criteria == ("tests",)
    assert completion.receipts[0].receipt_id == failing.receipt_id


def test_completion_rejects_receipt_from_previous_mutation_generation(
    stores: tuple[TaskStore, VerificationStore],
):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="changed task", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-generation"),
        task_id="task-generation",
    )
    receipt = receipt_for(
        "task-generation", "tests", artifact_store=verif_store.artifact_store,
        mutation_generation=0,
    )
    verif_store.record(receipt)
    task_store.checkpoint(
        "task-generation",
        TaskCheckpoint(state_data={"mutation_generation": 1}),
        actor="agent", idempotency_key="changed-generation",
    )

    completion = verif_store.completion("task-generation", now=receipt.observed_at + 1)

    assert completion.complete is False
    assert completion.stale_criteria == ("tests",)


def test_completion_audit_maps_criteria_to_evidence_and_receipts(stores: tuple[TaskStore, VerificationStore], tmp_path: Path):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="audited task", acceptance_criteria=("tests", "lint")),
        ScopeContext(task_id="task-audit"),
        task_id="task-audit",
    )
    verif_store.record(receipt_for("task-audit", "tests", artifact_store=verif_store.artifact_store, repository_revision="rev-1"))
    verif_store.record(receipt_for("task-audit", "lint", artifact_store=verif_store.artifact_store, repository_revision="rev-1"))
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
    test_receipt = next(receipt for receipt in result.receipts if receipt.criterion == "tests")
    assert audit["criteria"]["tests"]["evidence_ids"] == [test_receipt.evidence_id]
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
    verif_store.record(receipt_for("task-contract", "tests", artifact_store=verif_store.artifact_store, repository_revision="rev-2"))
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


def test_verification_evidence_classification_is_conservative():
    assert criterion_evidence_type("benchmark tests") == "benchmark"
    assert classify_verification_command("python -m pytest -q") == "test"
    assert classify_verification_command(
        "python -m pyflakes C:/tmp/pytest-of-user/pytest-0/lint_target.py"
    ) == "source_review"
    assert classify_verification_command("python -m ruff check src") == "source_review"
    assert classify_verification_command("python -m compileall -q src tests") == "source_review"
    assert criterion_evidence_type("tests") == "test"
    assert criterion_evidence_type("tests_pass") == "test"
    assert criterion_evidence_type("unit_test") == "test"
    assert criterion_evidence_type("document testing instructions") == "source_review"
    receipt = VerificationReceipt.create(
        "task-classifier",
        "benchmark tests",
        evidence_id="ev-benchmark",
        command_id="cmd-benchmark",
    )
    assert receipt.evidence_type == "benchmark"


@pytest.mark.parametrize("record_kind", ["change", "outcome"])
def test_verifier_projection_rolls_back_when_event_projection_write_fails(
    tmp_path: Path, record_kind: str
):
    state_store = AgentStateStore(tmp_path / f"{record_kind}.sqlite3")
    verifier = VerificationStore(state_store)
    change = ChangeIntent.create("atomic-record", ["src/app.py"])
    if record_kind == "change":
        stream_id = f"change:{change.task_id}"
        with closing(connect_sqlite(state_store.db_path, isolation_level=None)) as con:
            con.execute(
                "CREATE TRIGGER reject_change BEFORE INSERT ON agent_change_intents "
                "BEGIN SELECT RAISE(ABORT, 'projection rejected'); END"
            )
        with pytest.raises(sqlite3.IntegrityError, match="projection rejected"):
            verifier.record_change(change)
        with closing(connect_sqlite(state_store.db_path, isolation_level=None)) as con:
            assert con.execute("SELECT COUNT(*) FROM agent_change_intents").fetchone()[0] == 0
    else:
        outcome = OutcomeRecord.accepted(change.change_id, task_id=change.task_id)
        stream_id = f"outcome:{change.change_id}"
        with closing(connect_sqlite(state_store.db_path, isolation_level=None)) as con:
            con.execute(
                "CREATE TRIGGER reject_outcome BEFORE INSERT ON agent_outcomes "
                "BEGIN SELECT RAISE(ABORT, 'projection rejected'); END"
            )
        with pytest.raises(sqlite3.IntegrityError, match="projection rejected"):
            verifier.record_outcome(outcome)
        with closing(connect_sqlite(state_store.db_path, isolation_level=None)) as con:
            assert con.execute("SELECT COUNT(*) FROM agent_outcomes").fetchone()[0] == 0
    assert state_store.events(stream_id=stream_id) == []


def test_separate_task_receipt_projection_recovers_from_durable_outbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    receipt_state = AgentStateStore(tmp_path / "verification.sqlite3")
    task_store = TaskStore(AgentStateStore(tmp_path / "tasks.sqlite3"))
    task = task_store.create(
        GoalContract(goal="recover receipt", acceptance_criteria=("tests",)),
        ScopeContext(task_id="separate-receipt-task"),
        task_id="separate-receipt-task",
    )
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    verifier = VerificationStore(
        receipt_state, task_store=task_store, artifact_store=artifact_store
    )
    receipt = receipt_for(task.task_id, "tests", artifact_store=artifact_store)
    original_add = task_store.add_verification_receipt

    def fail_once(*args, **kwargs):
        monkeypatch.setattr(task_store, "add_verification_receipt", original_add)
        raise OSError("task database unavailable")

    monkeypatch.setattr(task_store, "add_verification_receipt", fail_once)
    with pytest.raises(RuntimeError, match="reconciliation required"):
        verifier.record(receipt)

    with closing(connect_sqlite(receipt_state.db_path)) as con:
        pending = con.execute(
            "SELECT COUNT(*) FROM agent_verification_task_outbox WHERE status = 'pending'"
        ).fetchone()[0]
    assert pending == 1

    VerificationStore(
        receipt_state, task_store=task_store, artifact_store=artifact_store
    )
    recovered_task = task_store.get(task.task_id)
    assert recovered_task is not None
    assert recovered_task.verification_receipts["tests"] == receipt.receipt_id
    with closing(connect_sqlite(receipt_state.db_path)) as con:
        pending = con.execute(
            "SELECT COUNT(*) FROM agent_verification_task_outbox WHERE status = 'pending'"
        ).fetchone()[0]
    assert pending == 0


def test_record_in_transaction_updates_same_database_task_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    state_store = AgentStateStore(tmp_path / "same-database.sqlite3")
    task_store = TaskStore(state_store)
    task = task_store.create(
        GoalContract(goal="same-store receipt", acceptance_criteria=("tests",)),
        ScopeContext(task_id="same-store-receipt-task"),
        task_id="same-store-receipt-task",
    )
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    verifier = VerificationStore(
        state_store, task_store=task_store, artifact_store=artifact_store
    )
    receipt = receipt_for(task.task_id, "tests", artifact_store=artifact_store)
    original_add_in_transaction = task_store.add_verification_receipt_in_transaction
    transaction_calls = []

    def track_add_in_transaction(con, task_id, criterion, receipt_id):
        assert con.in_transaction
        transaction_calls.append((con, task_id, criterion, receipt_id))
        return original_add_in_transaction(con, task_id, criterion, receipt_id)

    monkeypatch.setattr(
        task_store,
        "add_verification_receipt_in_transaction",
        track_add_in_transaction,
    )
    task_events_before = state_store.events(stream_id=f"task:{task.task_id}")

    with closing(connect_sqlite(state_store.db_path, isolation_level=None)) as con:
        with state_store.ordered_event_publication(con) as publish_committed:
            con.execute("BEGIN IMMEDIATE")
            events = verifier.record_in_transaction(con, receipt, update_task=True)
            replayed_events = verifier.record_in_transaction(
                con, receipt, update_task=True
            )
            con.execute("COMMIT")
            publish_committed(events)
    assert replayed_events == []
    assert len(transaction_calls) == 2
    assert transaction_calls[0][0] is transaction_calls[1][0]
    assert all(
        call[1:] == (task.task_id, "tests", receipt.receipt_id)
        for call in transaction_calls
    )

    recovered = task_store.get(task.task_id)
    assert recovered is not None
    assert recovered.verification_receipts["tests"] == receipt.receipt_id
    completion = verifier.completion(task.task_id)
    assert completion.complete is True
    verification_events = state_store.events(
        stream_id=f"verification:{task.task_id}"
    )
    assert len(verification_events) == 1
    assert verification_events[0].kind == "verification.receipt_recorded"
    task_events_after = state_store.events(stream_id=f"task:{task.task_id}")
    assert len(task_events_after) == len(task_events_before) + 1
    assert task_events_after[-1].kind == "task.verified"


def test_record_uses_public_t08_transaction_api_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    state_store = AgentStateStore(tmp_path / "public-t08-api.sqlite3")
    task_store = TaskStore(state_store)
    task = task_store.create(
        GoalContract(goal="public transaction API", acceptance_criteria=("tests",)),
        ScopeContext(task_id="public-t08-api"),
        task_id="public-t08-api",
    )
    artifacts = ArtifactStore(tmp_path / "artifacts")
    verifier = VerificationStore(
        state_store, task_store=task_store, artifact_store=artifacts
    )
    receipt = receipt_for(task.task_id, "tests", artifact_store=artifacts)

    append_calls: list[tuple[Any, bool]] = []
    publication_calls: list[Any] = []
    projection_calls: list[tuple[Any, str, str, str]] = []
    original_append = state_store.append_in_transaction
    original_publication = state_store.ordered_event_publication
    original_projection = task_store.add_verification_receipt_in_transaction

    def append_in_transaction(con, event, *, strict_idempotency=False):
        append_calls.append((con, strict_idempotency))
        return original_append(con, event, strict_idempotency=strict_idempotency)

    def ordered_event_publication(con):
        publication_calls.append(con)
        return original_publication(con)

    def add_verification_receipt_in_transaction(con, task_id, criterion, receipt_id):
        projection_calls.append((con, task_id, criterion, receipt_id))
        return original_projection(con, task_id, criterion, receipt_id)

    monkeypatch.setattr(state_store, "append_in_transaction", append_in_transaction)
    monkeypatch.setattr(
        state_store, "ordered_event_publication", ordered_event_publication
    )
    monkeypatch.setattr(
        task_store,
        "add_verification_receipt_in_transaction",
        add_verification_receipt_in_transaction,
    )

    saved = verifier.record(receipt)

    assert saved.receipt_id == receipt.receipt_id
    assert len(publication_calls) == 1
    assert len(append_calls) == 2
    assert all(
        con is publication_calls[0] and strict_idempotency
        for con, strict_idempotency in append_calls
    )
    assert projection_calls == [
        (publication_calls[0], task.task_id, "tests", receipt.receipt_id)
    ]
    projected = task_store.get(task.task_id)
    assert projected is not None
    assert projected.verification_receipts["tests"] == receipt.receipt_id


def test_record_in_transaction_skips_missing_task_projection(
    tmp_path: Path,
):
    state_store = AgentStateStore(tmp_path / "missing-task-receipt.sqlite3")
    task_store = TaskStore(state_store)
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    verifier = VerificationStore(
        state_store, task_store=task_store, artifact_store=artifact_store
    )
    receipt = receipt_for(
        "missing-task-receipt", "tests", artifact_store=artifact_store
    )

    with closing(connect_sqlite(state_store.db_path, isolation_level=None)) as con:
        con.execute("BEGIN IMMEDIATE")
        events = verifier.record_in_transaction(con, receipt, update_task=True)
        con.execute("COMMIT")

    assert [event.kind for event in events] == ["verification.receipt_recorded"]
    assert state_store.events(stream_id="verification:missing-task-receipt") == events
    assert state_store.events(stream_id="task:missing-task-receipt") == []
    with closing(connect_sqlite(state_store.db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_verification_receipts "
            "WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()[0] == 1


def test_caller_owned_transaction_rolls_back_event_when_receipt_insert_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    state_store = AgentStateStore(tmp_path / "caller-transaction-rollback.sqlite3")
    task_store = TaskStore(state_store)
    task = task_store.create(
        GoalContract(goal="caller transaction rollback", acceptance_criteria=("tests",)),
        ScopeContext(task_id="caller-transaction-rollback"),
        task_id="caller-transaction-rollback",
    )
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    verifier = VerificationStore(
        state_store, task_store=task_store, artifact_store=artifact_store
    )
    receipt = receipt_for(task.task_id, "tests", artifact_store=artifact_store)
    append_calls = []
    original_append = state_store.append_in_transaction

    def append_in_transaction(con, event, *, strict_idempotency=False):
        assert con.in_transaction
        append_calls.append((event.kind, strict_idempotency))
        return original_append(
            con, event, strict_idempotency=strict_idempotency
        )

    # Wrap T08's public transaction seam to record its call contract.
    monkeypatch.setattr(
        state_store, "append_in_transaction", append_in_transaction, raising=False
    )
    with closing(connect_sqlite(state_store.db_path, isolation_level=None)) as con:
        con.execute(
            "CREATE TRIGGER reject_verification_receipt "
            "BEFORE INSERT ON agent_verification_receipts "
            "BEGIN SELECT RAISE(ABORT, 'receipt insert rejected'); END"
        )
        con.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.IntegrityError, match="receipt insert rejected"):
            verifier.record_in_transaction(con, receipt, update_task=False)
        assert con.in_transaction
        con.execute("ROLLBACK")

    assert append_calls == [("verification.receipt_recorded", True)]
    assert state_store.events(stream_id=f"verification:{task.task_id}") == []
    with closing(connect_sqlite(state_store.db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_verification_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()[0] == 0


def test_caller_transaction_api_rolls_back_receipt_event_and_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    state_store = AgentStateStore(tmp_path / "receipt-atomicity.sqlite3")
    task_store = TaskStore(state_store)
    task = task_store.create(
        GoalContract(goal="atomic receipt", acceptance_criteria=("tests",)),
        ScopeContext(task_id="atomic-receipt-task"),
        task_id="atomic-receipt-task",
    )
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    verifier = VerificationStore(
        state_store, task_store=task_store, artifact_store=artifact_store
    )
    receipt = receipt_for(task.task_id, "tests", artifact_store=artifact_store)
    append_calls = []
    original_append = state_store.append_in_transaction

    def append_in_transaction(con, event, *, strict_idempotency=False):
        assert con.in_transaction
        append_calls.append((event.kind, con.in_transaction, strict_idempotency))
        return original_append(
            con, event, strict_idempotency=strict_idempotency
        )

    # Wrap T08's public transaction seam to record its call contract.
    monkeypatch.setattr(
        state_store, "append_in_transaction", append_in_transaction, raising=False
    )

    with closing(connect_sqlite(state_store.db_path, isolation_level=None)) as con:
        con.execute(
            "CREATE TRIGGER reject_task_verified BEFORE INSERT ON agent_events "
            "WHEN NEW.kind = 'task.verified' "
            "BEGIN SELECT RAISE(ABORT, 'task event rejected'); END"
        )

    with pytest.raises((sqlite3.IntegrityError, RuntimeError)):
        verifier.record(receipt)

    assert append_calls == [
        ("verification.receipt_recorded", True, True),
        ("task.verified", True, True),
    ]
    recovered = task_store.get(task.task_id)
    assert recovered is not None
    assert "tests" not in recovered.verification_receipts
    assert state_store.events(stream_id=f"verification:{task.task_id}") == []
    assert not any(
        event.kind == "task.verified"
        for event in state_store.events(stream_id=f"task:{task.task_id}")
    )
    with closing(connect_sqlite(state_store.db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_verification_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()[0] == 0


def test_receipt_id_reuse_cannot_upgrade_failed_receipt_to_pass(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "receipt-identity.sqlite3")
    task_store = TaskStore(state_store)
    task = task_store.create(
        GoalContract(goal="receipt identity", acceptance_criteria=("tests",)),
        ScopeContext(task_id="receipt-identity-task"),
        task_id="receipt-identity-task",
    )
    verifier = VerificationStore(state_store, task_store=task_store)
    failed = replace(
        receipt_for(task.task_id, "tests", passed=False),
        details={"items": ("a", "b")},
    )

    verifier.record(failed)
    verifier.record(failed)
    forged_pass = replace(failed, passed=True, evidence_id="ev-upgraded")

    with pytest.raises(ValueError, match="trusted evidence|receipt ID.*conflicting"):
        verifier.record(forged_pass)

    recovered = task_store.get(task.task_id)
    assert recovered is not None
    assert "tests" not in recovered.verification_receipts
    assert verifier.completion(task.task_id).complete is False
    with closing(connect_sqlite(state_store.db_path)) as con:
        row = con.execute(
            "SELECT passed, evidence_id FROM agent_verification_receipts WHERE receipt_id = ?",
            (failed.receipt_id,),
        ).fetchone()
    assert row is not None
    assert (row[0], row[1]) == (0, failed.evidence_id)
    assert len(state_store.events(stream_id=f"verification:{task.task_id}")) == 1


def test_record_can_skip_task_projection_for_external_work_orders(tmp_path: Path):
    receipt_state = AgentStateStore(tmp_path / "verification.sqlite3")
    task_store = TaskStore(AgentStateStore(tmp_path / "tasks.sqlite3"))
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    verifier = VerificationStore(
        receipt_state, task_store=task_store, artifact_store=artifact_store
    )
    receipt = receipt_for(
        "work-order-1", "tests", owner="tenant", command_id="cmd-work-tests",
        artifact_store=artifact_store,
    )

    saved = verifier.record(receipt, update_task=False)

    assert saved.receipt_id == receipt.receipt_id
    with closing(connect_sqlite(receipt_state.db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_verification_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()[0] == 1
        assert con.execute(
            "SELECT COUNT(*) FROM agent_verification_task_outbox WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()[0] == 0


def test_startup_replays_pending_task_projection_outbox(tmp_path: Path):
    receipt_state = AgentStateStore(tmp_path / "verification.sqlite3")
    verifier = VerificationStore(receipt_state)
    task_store = TaskStore(AgentStateStore(tmp_path / "tasks.sqlite3"))
    task = task_store.create(
        GoalContract(goal="startup receipt", acceptance_criteria=("docs",)),
        ScopeContext(task_id="startup-receipt-task"),
        task_id="startup-receipt-task",
    )
    with closing(connect_sqlite(receipt_state.db_path, isolation_level=None)) as con:
        con.execute(
            "INSERT INTO agent_verification_task_outbox "
            "(receipt_id, task_id, criterion, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            ("rcpt-startup", task.task_id, "docs", 1.0),
        )

    restarted = VerificationStore(receipt_state, task_store=task_store)

    updated = task_store.get(task.task_id)
    assert updated is not None
    assert updated.verification_receipts["docs"] == "rcpt-startup"
    with closing(connect_sqlite(receipt_state.db_path)) as con:
        assert con.execute(
            "SELECT status FROM agent_verification_task_outbox WHERE receipt_id = ?",
            ("rcpt-startup",),
        ).fetchone()[0] == "completed"
    assert restarted._reconcile_task_outbox() == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("passed", 1),
        ("passed", "true"),
        ("exit_code", True),
        ("exit_code", 1),
        ("task_id", "other-task"),
        ("owner", "other-owner"),
        ("criterion", "lint"),
        ("command_id", "other-command"),
        ("repository_revision", "other-revision"),
        ("mutation_generation", 1),
        ("result.success", "true"),
    ],
)
def test_positive_receipt_rejects_non_boolean_pass_and_nonzero_exit(
    tmp_path: Path, field: str, value: Any
):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    task_store = TaskStore(state_store)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    verifier = VerificationStore(state_store, task_store=task_store, artifact_store=artifacts)
    task = task_store.create(
        GoalContract(goal="strict command proof", acceptance_criteria=("tests",)),
        ScopeContext(task_id="strict-command-proof"),
        task_id="strict-command-proof",
    )
    proof = {
        "kind": "work_command_verification",
        "passed": True,
        "task_id": task.task_id,
        "owner": "agent",
        "criterion": "tests",
        "command_id": "cmd-1",
        "repository_revision": "rev-1",
        "mutation_generation": 0,
        "exit_code": 0,
        "result": {"success": True, "exit_code": 0},
    }
    if field.startswith("result."):
        proof["result"][field.split(".", 1)[1]] = value
    else:
        proof[field] = value
    evidence_id = artifacts.put(json.dumps(proof), "agent", "command_verification")
    receipt = VerificationReceipt.create(
        task.task_id,
        "tests",
        evidence_id=evidence_id,
        command_id="cmd-1",
        repository_revision="rev-1",
        owner="agent",
        evidence_type="test",
    )

    with pytest.raises(ValueError, match="trusted evidence"):
        verifier.record(receipt)


def test_positive_receipt_artifact_must_be_visible_to_receipt_tenant(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    task_store = TaskStore(state_store)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    verifier = VerificationStore(state_store, task_store=task_store, artifact_store=artifacts)
    task = task_store.create(
        GoalContract(goal="tenant-bound proof", acceptance_criteria=("tests",)),
        ScopeContext(task_id="tenant-bound-proof"),
        task_id="tenant-bound-proof",
    )
    proof = {
        "kind": "work_command_verification",
        "passed": True,
        "task_id": task.task_id,
        "owner": "agent",
        "criterion": "tests",
        "command_id": "cmd-1",
        "repository_revision": "rev-1",
        "mutation_generation": 0,
        "exit_code": 0,
        "result": {"success": True, "exit_code": 0},
    }
    evidence_id = artifacts.put(json.dumps(proof), "other-tenant", "command_verification")
    receipt = VerificationReceipt.create(
        task.task_id,
        "tests",
        evidence_id=evidence_id,
        command_id="cmd-1",
        repository_revision="rev-1",
        owner="agent",
        evidence_type="test",
    )

    with pytest.raises(ValueError, match="trusted evidence"):
        verifier.record(receipt)


def test_completion_rereads_and_rejects_deleted_proof_artifact(
    stores: tuple[TaskStore, VerificationStore],
):
    task_store, verifier = stores
    task = task_store.create(
        GoalContract(goal="proof retention", acceptance_criteria=("tests",)),
        ScopeContext(task_id="proof-retention"),
        task_id="proof-retention",
    )
    receipt = receipt_for(task.task_id, "tests", artifact_store=verifier.artifact_store)
    verifier.record(receipt)
    with closing(verifier.artifact_store._connect()) as con:
        with con:
            con.execute(
                f"DELETE FROM {verifier.artifact_store._table} WHERE artifact_id = ?",
                (receipt.evidence_id,),
            )

    completion = verifier.completion(task.task_id)

    assert completion.complete is False
    assert completion.unsatisfied_criteria == ("tests",)


def test_completion_fails_closed_when_artifact_resolver_is_missing(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    task_store = TaskStore(state_store)
    verifier = VerificationStore(state_store, task_store=task_store)
    task = task_store.create(
        GoalContract(goal="no resolver", acceptance_criteria=("tests",)),
        ScopeContext(task_id="no-resolver"),
        task_id="no-resolver",
    )
    verifier.record(receipt_for(task.task_id, "tests"))

    completion = verifier.completion(task.task_id)

    assert completion.complete is False
    assert completion.unsatisfied_criteria == ("tests",)






def test_completion_selects_latest_receipt_when_input_is_oldest_first(tmp_path: Path):
    from dataclasses import replace

    from local_ai_hub.agent_verification import evaluate_completion_receipts

    artifact_store = ArtifactStore(tmp_path / "artifacts")
    old = replace(
        receipt_for(
            "task-latest", "tests", expires_at=100.0,
            repository_revision="rev-old", mutation_generation=0,
            command_id="cmd-old", artifact_store=artifact_store,
        ),
        observed_at=10.0,
    )
    current = replace(
        receipt_for(
            "task-latest", "tests", expires_at=100.0,
            repository_revision="rev-new", mutation_generation=1,
            command_id="cmd-current", artifact_store=artifact_store,
        ),
        observed_at=20.0,
    )

    result = evaluate_completion_receipts(
        "task-latest",
        ("tests",),
        (old, current),
        owner="agent",
        repository_revision="rev-new",
        mutation_generation=1,
        mapped_receipt_ids={"tests": current.receipt_id},
        artifact_store=artifact_store,
        now=30.0,
    )
    stale_mapping = evaluate_completion_receipts(
        "task-latest",
        ("tests",),
        (old, current),
        owner="agent",
        repository_revision="rev-new",
        mutation_generation=1,
        mapped_receipt_ids={"tests": old.receipt_id},
        artifact_store=artifact_store,
        now=30.0,
    )

    assert result.complete is True
    assert result.receipts == (current,)
    assert stale_mapping.complete is False
    assert stale_mapping.unsatisfied_criteria == ("tests",)


def test_completion_fails_closed_when_sqlite_receipt_store_cannot_open(
    tmp_path: Path, stores: tuple[TaskStore, VerificationStore]
):
    task_store, verification_store = stores
    task = task_store.create(
        GoalContract(goal="offline receipt database", acceptance_criteria=("tests",)),
        ScopeContext(task_id="offline-receipt-database"),
        task_id="offline-receipt-database",
    )
    task_store.transition(
        task.task_id,
        TaskStatus.ACTIVE,
        reason="prepare completion check",
        actor="agent",
        idempotency_key="activate-offline-receipt-task",
    )
    verification_store.record(
        receipt_for(
            task.task_id, "tests", owner=task.owner,
            artifact_store=verification_store.artifact_store,
        )
    )

    unavailable_state = AgentStateStore(tmp_path / "unavailable" / "agent_state.sqlite3")
    unavailable_verifier = VerificationStore(
        unavailable_state, artifact_store=verification_store.artifact_store
    )
    unavailable_path = tmp_path / "database-is-a-directory.sqlite3"
    unavailable_path.mkdir()
    unavailable_state.db_path = unavailable_path
    task_store.set_verification_store(unavailable_verifier)

    with pytest.raises(CompletionGateError, match="verification storage could not validate"):
        task_store.complete(task.task_id)

    current = task_store.get(task.task_id)
    assert current is not None and current.status != TaskStatus.COMPLETED


def test_verification_store_forwards_project_rules_to_completion_evaluator(
    stores: tuple[TaskStore, VerificationStore], monkeypatch: pytest.MonkeyPatch
):
    task_store, verifier = stores
    task = task_store.create(
        GoalContract(goal="project-rule task", acceptance_criteria=("test",)),
        ScopeContext(task_id="project-rule-task"),
        task_id="project-rule-task",
    )
    forwarded: dict[str, Any] = {}
    evaluate = agent_verification_module.evaluate_completion_receipts

    def capture(*args: Any, **kwargs: Any) -> CompletionResult:
        forwarded.update(kwargs)
        return evaluate(*args, **kwargs)

    monkeypatch.setattr(
        agent_verification_module, "evaluate_completion_receipts", capture
    )
    result = verifier.completion(
        task.task_id,
        now=100.0,
        current_revision="rev-1",
        verification_rules={"test": True},
        configured_criteria=("lint", "test"),
    )

    assert not result.complete
    assert forwarded["verification_rules"] == {"test": True}
    assert forwarded["configured_criteria"] == ("lint", "test")


@pytest.mark.parametrize(
    ("command_text", "command_classification", "proof_tamper", "expected_complete"),
    [
        ("python -m ruff check src", "source_review", "", True),
        ("echo lint", "source_review", "", False),
        ("python -m ruff check src", "test", "", False),
        ("python -m ruff check src", "source_review", "environment", False),
        ("python -m ruff check src", "source_review", "arguments", False),
        ("python -m ruff check src", "source_review", "execution_binding", False),
    ],
)
def test_project_lint_command_receipt_binds_runner_to_configured_alias(
    stores: tuple[TaskStore, VerificationStore],
    command_text: str,
    command_classification: str,
    proof_tamper: str,
    expected_complete: bool,
):
    task_store, verifier = stores
    task = task_store.create(
        GoalContract(goal="project lint rule", acceptance_criteria=("lint",)),
        ScopeContext(task_id="project-lint-rule"),
        task_id="project-lint-rule",
    )
    lint_command_id = "cmd-lint"
    configured_command = "python -m ruff check src"
    environment_sha256 = hashlib.sha256(b"{}").hexdigest()
    configured_command_sha256 = hashlib.sha256(
        configured_command.encode("utf-8")
    ).hexdigest()
    command_sha256 = hashlib.sha256(command_text.encode("utf-8")).hexdigest()
    caller_arguments_sha256 = hashlib.sha256(b"[]").hexdigest()
    binding_fields = {
        "project_alias": "lint",
        "project_config_digest": "cfg-current",
        "configured_command_sha256": configured_command_sha256,
        "caller_arguments_sha256": caller_arguments_sha256,
        "command_sha256": command_sha256,
        "project_environment_sha256": environment_sha256,
    }
    execution_binding_sha256 = hashlib.sha256(
        json.dumps(binding_fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if proof_tamper == "environment":
        environment_sha256 = hashlib.sha256(b'{"ENV":"changed"}').hexdigest()
        binding_fields["project_environment_sha256"] = environment_sha256
        execution_binding_sha256 = hashlib.sha256(
            json.dumps(binding_fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    elif proof_tamper == "arguments":
        caller_arguments_sha256 = hashlib.sha256(b'["--help"]').hexdigest()
        binding_fields["caller_arguments_sha256"] = caller_arguments_sha256
        execution_binding_sha256 = hashlib.sha256(
            json.dumps(binding_fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    elif proof_tamper == "execution_binding":
        execution_binding_sha256 = "0" * 64
    lint_evidence_id = verifier.artifact_store.put_json(
        {
            "kind": "work_command_verification",
            "passed": True,
            "task_id": task.task_id,
            "owner": "agent",
            "repository_revision": "rev-1",
            "mutation_generation": 0,
            "criterion": "lint",
            "command_id": lint_command_id,
            "command_classification": command_classification,
            "command": command_text,
            "project_alias": "lint",
            "project_config_digest": "cfg-current",
            "project_environment_sha256": environment_sha256,
            "configured_command_sha256": configured_command_sha256,
            "caller_arguments_sha256": caller_arguments_sha256,
            "project_execution_binding_sha256": execution_binding_sha256,
            "command_sha256": command_sha256,
            "exit_code": 0,
            "result": {"success": True, "exit_code": 0},
        },
        "agent",
        "command_verification",
    )
    receipt = VerificationReceipt.create(
        task.task_id,
        "lint",
        evidence_id=lint_evidence_id,
        command_id=lint_command_id,
        owner="agent",
        repository_revision="rev-1",
    )
    record_rejected = False
    try:
        verifier.record(receipt)
    except ValueError:
        record_rejected = True
    assert record_rejected is (command_classification != "source_review")

    result = verifier.completion(
        task.task_id,
        current_revision="rev-1",
        verification_rules={"lint": ["lint"]},
        configured_criteria=("lint",),
        configured_commands={"lint": configured_command},
        configured_environment_sha256={"lint": hashlib.sha256(b"{}").hexdigest()},
        project_config_digest="cfg-current",
    )

    assert result.complete is expected_complete
    assert result.satisfied_criteria == (("lint",) if expected_complete else ())


def test_receipt_and_task_projection_publish_after_atomic_commit(
    stores: tuple[TaskStore, VerificationStore], monkeypatch: pytest.MonkeyPatch
):
    task_store, verifier = stores
    task = task_store.create(
        GoalContract(goal="ordered receipt publication", acceptance_criteria=("tests",)),
        ScopeContext(task_id="ordered-receipt-publication"),
        task_id="ordered-receipt-publication",
    )
    state_store = verifier.state_store
    subscriber = state_store.subscribe()
    receipt = receipt_for(
        task.task_id, "tests", artifact_store=verifier.artifact_store
    )

    delivered: list[Any] = []
    callback_errors: list[Exception] = []
    original_put_nowait = subscriber.put_nowait

    def check_durable_before_delivery(event: Any) -> None:
        try:
            if event.kind in {"verification.receipt_recorded", "task.verified"}:
                current = task_store.get(task.task_id)
                assert current is not None
                assert current.verification_receipts["tests"] == receipt.receipt_id
                verification_events = state_store.event_page(
                    f"verification:{task.task_id}"
                )["events"]
                task_events = state_store.event_page(f"task:{task.task_id}")["events"]
                assert any(
                    row.get("kind") == "verification.receipt_recorded"
                    and row.get("payload", {}).get("receipt_id") == receipt.receipt_id
                    for row in verification_events
                )
                assert any(
                    row.get("kind") == "task.verified"
                    and row.get("payload", {}).get("receipt_id") == receipt.receipt_id
                    for row in task_events
                )
                with closing(connect_sqlite(state_store.db_path)) as con:
                    assert con.execute(
                        "SELECT 1 FROM agent_verification_receipts WHERE receipt_id = ?",
                        (receipt.receipt_id,),
                    ).fetchone() is not None
        except Exception as exc:
            callback_errors.append(exc)
        finally:
            delivered.append(event)
            original_put_nowait(event)

    monkeypatch.setattr(subscriber, "put_nowait", check_durable_before_delivery)
    try:
        verifier.record(receipt)

        assert callback_errors == [], callback_errors
        queued = [subscriber.get_nowait(), subscriber.get_nowait()]
        assert queued == delivered
        assert {event.kind for event in queued} == {
            "verification.receipt_recorded",
            "task.verified",
        }
        for stream_id in {event.stream_id for event in queued}:
            stream_events = [event for event in queued if event.stream_id == stream_id]
            persisted = state_store.event_page(stream_id)["events"]
            queued_ids = [event.event_id for event in stream_events]
            persisted_events = [row for row in persisted if row.get("event_id") in queued_ids]
            assert [event.to_dict() for event in stream_events] == persisted_events
            assert [event.seq for event in stream_events] == sorted(
                event.seq for event in stream_events
            )
    finally:
        state_store.unsubscribe(subscriber)


def test_receipt_writer_waits_for_shared_publication_lock(
    stores: tuple[TaskStore, VerificationStore], monkeypatch: pytest.MonkeyPatch
):
    from threading import Event, Thread, current_thread

    task_store, verifier = stores
    task = task_store.create(
        GoalContract(goal="ordered receipt writer", acceptance_criteria=("tests",)),
        ScopeContext(task_id="ordered-receipt-writer"),
        task_id="ordered-receipt-writer",
    )
    state_store = verifier.state_store
    subscriber = state_store.subscribe()
    receipt = receipt_for(
        task.task_id, "tests", artifact_store=verifier.artifact_store
    )
    publication_attempted = Event()
    receipt_transaction_started = Event()
    original_ordered_publication = state_store.ordered_event_publication
    original_record_in_transaction = verifier.record_in_transaction

    def observe_ordered_publication(con: Any):
        if current_thread().name == "receipt-writer":
            publication_attempted.set()
        return original_ordered_publication(con)

    def observe_receipt_transaction(con: Any, *args: Any, **kwargs: Any):
        receipt_transaction_started.set()
        return original_record_in_transaction(con, *args, **kwargs)

    monkeypatch.setattr(
        state_store, "ordered_event_publication", observe_ordered_publication
    )
    monkeypatch.setattr(
        verifier, "record_in_transaction", observe_receipt_transaction
    )
    errors: list[BaseException] = []

    def record_receipt() -> None:
        try:
            verifier.record(receipt)
        except BaseException as exc:
            errors.append(exc)

    worker = Thread(target=record_receipt, name="receipt-writer")
    try:
        with closing(connect_sqlite(state_store.db_path, isolation_level=None)) as con:
            with state_store.ordered_event_publication(con):
                worker.start()
                assert publication_attempted.wait(timeout=2)
                assert not receipt_transaction_started.is_set()
                assert subscriber.empty()
                with closing(connect_sqlite(state_store.db_path)) as read_con:
                    assert read_con.execute(
                        "SELECT 1 FROM agent_verification_receipts WHERE receipt_id = ?",
                        (receipt.receipt_id,),
                    ).fetchone() is None
    finally:
        if worker.ident is not None:
            worker.join(timeout=5)
        state_store.unsubscribe(subscriber)

    assert not worker.is_alive()
    assert not errors
    assert receipt_transaction_started.is_set()
    queued = [subscriber.get_nowait(), subscriber.get_nowait()]
    assert {event.kind for event in queued} == {
        "verification.receipt_recorded",
        "task.verified",
    }
    for stream_id in {event.stream_id for event in queued}:
        stream_events = [event for event in queued if event.stream_id == stream_id]
        persisted = state_store.events(stream_id)
        queued_ids = [event.event_id for event in stream_events]
        persisted_events = [event for event in persisted if event.event_id in queued_ids]
        assert stream_events == persisted_events
        assert [event.seq for event in stream_events] == sorted(
            event.seq for event in stream_events
        )


def test_receipt_rollback_never_publishes_or_changes_projection(
    stores: tuple[TaskStore, VerificationStore], monkeypatch: pytest.MonkeyPatch
):
    task_store, verifier = stores
    task = task_store.create(
        GoalContract(goal="rollback receipt", acceptance_criteria=("tests",)),
        ScopeContext(task_id="rollback-receipt"),
        task_id="rollback-receipt",
    )
    state_store = verifier.state_store
    subscriber = state_store.subscribe()
    receipt = receipt_for(
        task.task_id, "tests", artifact_store=verifier.artifact_store
    )
    verification_before = state_store.event_page(
        f"verification:{task.task_id}"
    )["events"]
    task_before = state_store.event_page(f"task:{task.task_id}")["events"]
    record_in_transaction = verifier.record_in_transaction

    def fail_before_commit(con: Any, *args: Any, **kwargs: Any) -> list[Any]:
        record_in_transaction(con, *args, **kwargs)
        raise sqlite3.IntegrityError("forced receipt transaction rollback")

    monkeypatch.setattr(verifier, "record_in_transaction", fail_before_commit)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="forced receipt transaction rollback"):
            verifier.record(receipt)

        assert subscriber.empty()
        assert state_store.event_page(f"verification:{task.task_id}")["events"] == verification_before
        assert state_store.event_page(f"task:{task.task_id}")["events"] == task_before
        assert task_store.get(task.task_id).verification_receipts == {}
        with closing(connect_sqlite(state_store.db_path)) as con:
            assert con.execute(
                "SELECT 1 FROM agent_verification_receipts WHERE receipt_id = ?",
                (receipt.receipt_id,),
            ).fetchone() is None
    finally:
        state_store.unsubscribe(subscriber)


def test_task_completion_forwards_project_rules_and_durable_generation(
    stores: tuple[TaskStore, VerificationStore],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    task_store, verifier = stores
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (repo_root / ".local-ai.toml").write_text(
        '[commands]\nlint = "ruff check"\ntest = "python -m pytest"\n'
        '[verification_rules]\ntest = ["test", "lint"]\n',
        encoding="utf-8",
    )
    task = task_store.create(
        GoalContract(goal="project completion rules", acceptance_criteria=("test",)),
        ScopeContext(task_id="project-completion-rules"),
        task_id="project-completion-rules",
        repo_root=str(repo_root),
        repository_revision="rev-1",
    )
    task_store.checkpoint(
        task.task_id, TaskCheckpoint(state_data={"mutation_generation": 3})
    )
    verifier.record(
        receipt_for(
            task.task_id,
            "test",
            mutation_generation=3,
            artifact_store=verifier.artifact_store,
        )
    )

    forwarded: dict[str, Any] = {}
    complete = verifier.completion

    def capture(*args: Any, **kwargs: Any) -> CompletionResult:
        forwarded.update(kwargs)
        return complete(*args, **kwargs)

    monkeypatch.setattr(verifier, "completion", capture)

    from local_ai_hub.verification_rules import complete_task_with_project_rules

    with pytest.raises(CompletionGateError, match="lint"):
        complete_task_with_project_rules(
            task_store, verifier, task.task_id,
            root=repo_root, state_dir=state_dir, current_revision="rev-1",
        )

    assert forwarded["current_revision"] == "rev-1"
    assert forwarded["current_mutation_generation"] == 3
    assert tuple(forwarded["verification_rules"]["test"]) == ("test", "lint")
    assert forwarded["configured_criteria"] == ("lint", "test")


def test_task_completion_rejects_receipt_from_wrong_owner(stores: tuple[TaskStore, VerificationStore]):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="owner gate", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-owner"),
        task_id="task-owner",
        actor="owner-a",
    )
    verif_store.record(receipt_for(
        "task-owner", "tests", owner="owner-b",
        artifact_store=verif_store.artifact_store,
    ))

    with pytest.raises(CompletionGateError, match="owner"):
        task_store.complete("task-owner", actor="owner-a")


def test_task_completion_rejects_receipt_from_old_mutation_generation(
    stores: tuple[TaskStore, VerificationStore],
):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="generation gate", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-generation"),
        task_id="task-generation",
    )
    verif_store.record(receipt_for(
        "task-generation", "tests", mutation_generation=0,
        artifact_store=verif_store.artifact_store,
    ))
    task_store.checkpoint(
        "task-generation",
        TaskCheckpoint(state_data={"mutation_generation": 1}),
    )

    with pytest.raises(CompletionGateError, match="generation|stale"):
        task_store.complete("task-generation")


def test_recorded_change_advances_generation_and_invalidates_existing_receipt(
    stores: tuple[TaskStore, VerificationStore],
):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="change generation", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-change-generation"),
        task_id="task-change-generation",
    )
    task_store.checkpoint(
        "task-change-generation",
        TaskCheckpoint(state_data={"repository_revision": "rev-1", "mutation_generation": 0}),
    )
    verif_store.record(receipt_for(
        "task-change-generation", "tests", repository_revision="rev-1",
        artifact_store=verif_store.artifact_store,
    ))
    verif_store.record_change(
        ChangeIntent.create("task-change-generation", ("src/module.py",))
    )

    task = task_store.get("task-change-generation")
    assert task.checkpoint.state_data["mutation_generation"] == 1
    with pytest.raises(CompletionGateError, match="generation|stale"):
        task_store.complete("task-change-generation")


def test_task_completion_rejects_receipt_from_old_repository_revision(
    stores: tuple[TaskStore, VerificationStore],
):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="revision gate", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-current-revision"),
        task_id="task-current-revision",
    )
    task_store.checkpoint(
        "task-current-revision",
        TaskCheckpoint(state_data={"repository_revision": "rev-current"}),
    )
    verif_store.record(
        receipt_for(
            "task-current-revision", "tests", repository_revision="rev-old",
            artifact_store=verif_store.artifact_store,
        )
    )

    with pytest.raises(CompletionGateError, match="revision|stale"):
        task_store.complete("task-current-revision")


def test_model_review_receipt_cannot_satisfy_test_criterion(
    stores: tuple[TaskStore, VerificationStore],
):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="test evidence gate", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-model-pass"),
        task_id="task-model-pass",
    )
    receipt = VerificationReceipt.create(
        "task-model-pass",
        "tests",
        evidence_id="model-review-only",
        owner="agent",
        evidence_type="source_review",
    )
    with pytest.raises(ValueError, match="trusted evidence"):
        verif_store.record(receipt)

    with pytest.raises(CompletionGateError, match="receipt"):
        task_store.complete("task-model-pass")
    rejected = task_store.get("task-model-pass")
    assert rejected is not None
    assert rejected.verification_receipts == {}
    assert rejected.status is not TaskStatus.COMPLETED


def test_documentation_source_review_does_not_require_command_id(
    stores: tuple[TaskStore, VerificationStore],
):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="documentation task", acceptance_criteria=("document recovery steps",)),
        ScopeContext(task_id="task-docs"),
        task_id="task-docs",
        actor="docs-owner",
    )
    receipt = receipt_for(
        "task-docs", "document recovery steps", owner="docs-owner",
        evidence_type="source_review", artifact_store=verif_store.artifact_store,
    )
    assert receipt.command_id == ""
    verif_store.record(receipt)

    assert task_store.complete("task-docs", actor="docs-owner").status == TaskStatus.COMPLETED


def test_documentation_source_review_rejects_test_receipt(
    stores: tuple[TaskStore, VerificationStore],
):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="documentation task", acceptance_criteria=("document recovery steps",)),
        ScopeContext(task_id="task-docs"),
        task_id="task-docs",
        actor="docs-owner",
    )
    receipt = receipt_for(
        "task-docs", "document recovery steps", owner="docs-owner",
        evidence_type="test", artifact_store=verif_store.artifact_store,
    )
    verif_store.record(receipt)

    with pytest.raises(CompletionGateError, match="document recovery steps"):
        task_store.complete("task-docs", actor="docs-owner")


def test_test_evidence_requires_real_command_id():
    with pytest.raises(ValueError, match="command_id"):
        VerificationReceipt.create(
            "task-test-command",
            "tests",
            evidence_id="ev-test",
            owner="agent",
            evidence_type="test",
        )


def test_cancelled_task_cannot_complete_from_receipt(
    stores: tuple[TaskStore, VerificationStore],
):
    task_store, verif_store = stores
    task_store.create(
        GoalContract(goal="cancelled task", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-cancelled"),
        task_id="task-cancelled",
    )
    verif_store.record(receipt_for(
        "task-cancelled", "tests", artifact_store=verif_store.artifact_store
    ))
    task_store.transition(
        "task-cancelled", TaskStatus.CANCELLED, reason="cancelled", actor="agent", idempotency_key="cancel"
    )

    with pytest.raises(InvalidTransitionError):
        task_store.complete("task-cancelled")


@pytest.mark.parametrize(
    ("actual_command", "caller_arguments", "expected_complete"),
    [
        ("python -m pytest -q tests/test_smoke.py", ["tests/test_smoke.py"], True),
        ("python -m pytest -q --collect-only", ["--collect-only"], False),
    ],
)
def test_structured_project_receipt_recomputes_argv_env_and_arguments(
    tmp_path: Path,
    stores: tuple[TaskStore, VerificationStore],
    actual_command: str,
    caller_arguments: list[str],
    expected_complete: bool,
):
    from types import SimpleNamespace

    task_store, verifier = stores
    task = task_store.create(
        GoalContract(goal="structured project command", acceptance_criteria=("test",)),
        ScopeContext(task_id="structured-project-command"),
        task_id="structured-project-command",
    )
    configured = SimpleNamespace(
        argv=("python", "-m", "pytest", "-q"),
        env_references={"T06_PRIVATE": "T06_PRIVATE"},
    )
    project_environment = {"T06_PRIVATE": "private-current-value"}
    project_environment_sha256 = hashlib.sha256(
        json.dumps(
            project_environment, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    configured_command = json.dumps(
        {
            "argv": list(configured.argv),
            "cwd": str(tmp_path.resolve()),
            "shell": False,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    configured_command_sha256 = hashlib.sha256(
        configured_command.encode("utf-8")
    ).hexdigest()
    command_sha256 = hashlib.sha256(actual_command.encode("utf-8")).hexdigest()
    caller_arguments_sha256 = hashlib.sha256(
        json.dumps(caller_arguments, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    binding_fields = {
        "project_alias": "test",
        "project_config_digest": "cfg-structured",
        "configured_command_sha256": configured_command_sha256,
        "caller_arguments_sha256": caller_arguments_sha256,
        "command_sha256": command_sha256,
        "project_environment_sha256": project_environment_sha256,
    }
    binding_sha256 = hashlib.sha256(
        json.dumps(binding_fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    evidence_id = verifier.artifact_store.put_json(
        {
            "kind": "work_command_verification",
            "passed": True,
            "task_id": task.task_id,
            "owner": "agent",
            "repository_revision": "rev-structured",
            "mutation_generation": 0,
            "criterion": "test",
            "command_id": "cmd-structured",
            "command_classification": "test",
            "command": actual_command,
            "project_alias": "test",
            "project_config_digest": "cfg-structured",
            "project_environment_sha256": project_environment_sha256,
            "configured_command_sha256": configured_command_sha256,
            "caller_arguments_sha256": caller_arguments_sha256,
            "project_execution_binding_sha256": binding_sha256,
            "command_sha256": command_sha256,
            "exit_code": 0,
            "result": {"success": True, "exit_code": 0},
        },
        "agent",
        "command_verification",
    )
    verifier.record(
        VerificationReceipt.create(
            task.task_id,
            "test",
            evidence_id=evidence_id,
            command_id="cmd-structured",
            owner="agent",
            repository_revision="rev-structured",
            evidence_type="test",
        )
    )

    result = verifier.completion(
        task.task_id,
        current_revision="rev-structured",
        verification_rules={"test": ["test"]},
        configured_criteria=("test",),
        configured_commands={"test": configured},
        configured_environment_sha256={"test": project_environment_sha256},
        project_config_digest="cfg-structured",
        project_root=tmp_path,
    )

    assert result.complete is expected_complete
