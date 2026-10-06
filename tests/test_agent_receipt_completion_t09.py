from __future__ import annotations

import json
import hashlib
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_tasks import CompletionGateError, GoalContract, TaskCheckpoint, TaskStatus, TaskStore
from local_ai_hub.agent_verification import (
    VERIFICATION_RECEIPT_METADATA_SCHEMA,
    VerificationReceipt,
    VerificationStore,
)
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.sqlite_support import connect_sqlite


@pytest.fixture
def stores(tmp_path: Path):
    state = AgentStateStore(tmp_path / "agent-state.sqlite3", enabled=True)
    tasks = TaskStore(state)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    verifier = VerificationStore(state, task_store=tasks, artifact_store=artifacts)
    return tasks, verifier, artifacts


def task_ready_for_completion(
    tasks: TaskStore,
    task_id: str,
    *,
    owner: str = "tenant-a",
    repository_id: str = "repo-receipts",
):
    contract = GoalContract(
        goal="Verify durable receipt completion",
        acceptance_criteria=("tests",),
        scope=AgentScope.TASK,
    )
    tasks.create(
        contract,
        ScopeContext(repository_id=repository_id, task_id=task_id),
        task_id=task_id,
        actor=owner,
    )
    tasks.transition(
        task_id,
        TaskStatus.ACTIVE,
        reason="begin verification",
        actor=owner,
        idempotency_key=f"{task_id}-active",
    )
    tasks.transition(
        task_id,
        TaskStatus.VERIFYING,
        reason="receipt expected",
        actor=owner,
        idempotency_key=f"{task_id}-verifying",
    )
    tasks.checkpoint(
        task_id,
        TaskCheckpoint(
            state_data={"repository_revision": "rev-1", "mutation_generation": 0}
        ),
        actor=owner,
        idempotency_key=f"{task_id}-revision",
    )
    return tasks.get(task_id)


def passing_receipt(
    tasks: TaskStore,
    verifier: VerificationStore,
    artifacts: ArtifactStore,
    task_id: str,
    *,
    owner: str | None = None,
    revision: str = "rev-1",
) -> VerificationReceipt:
    task = tasks.get(task_id)
    assert task is not None
    receipt_owner = owner or task.owner
    command_id = hashlib.sha256(
        f"{task_id}:{receipt_owner}:{revision}:tests".encode()
    ).hexdigest()[:32]
    proof = {
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
    }
    evidence_id = artifacts.put_json(proof, receipt_owner, "command_verification")
    return VerificationReceipt.create(
        task_id,
        "tests",
        passed=True,
        evidence_id=evidence_id,
        command_id=command_id,
        owner=receipt_owner,
        repository_revision=revision,
        mutation_generation=0,
        evidence_type="test",
    )



def test_description_round_trip_and_description_terms_are_indexed(stores):
    tasks, _verifier, _artifacts = stores
    contract = GoalContract.from_dict(
        {
            "goal": "Harden receipt freshness",
            "title": "Receipt freshness",
            "description": "quasar evidence provenance",
            "acceptance_criteria": ["tests"],
        }
    )
    task = tasks.create(
        contract,
        ScopeContext(repository_id="repo-receipts", task_id="task-description-search"),
        task_id="task-description-search",
        actor="tenant-a",
    )

    fetched = tasks.get(task.task_id)
    matches = tasks.list_tasks(query="quasar provenance")

    assert fetched is not None
    assert fetched.contract.goal == "Harden receipt freshness"
    assert fetched.contract.description == "quasar evidence provenance"
    assert [match.task_id for match in matches] == [task.task_id]


def test_keyword_query_matches_across_indexed_task_fields(stores):
    tasks, _verifier, _artifacts = stores
    target = tasks.create(
        GoalContract(
            goal="Receipt freshness gate",
            description="Evidence from closed runs",
            acceptance_criteria=("generation",),
            scope=AgentScope.TASK,
        ),
        ScopeContext(repository_id="repo-receipts", task_id="task-search-target"),
        task_id="task-search-target",
        actor="tenant-a",
    )
    tasks.create(
        GoalContract(
            goal="Unrelated task",
            description="No matching evidence",
            acceptance_criteria=("other",),
            scope=AgentScope.TASK,
        ),
        ScopeContext(repository_id="repo-receipts", task_id="task-search-other"),
        task_id="task-search-other",
        actor="tenant-a",
    )
    tasks.checkpoint(
        target.task_id,
        TaskCheckpoint(next_action="Review signed handoff"),
        actor="tenant-a",
        idempotency_key="task-search-checkpoint",
    )

    matches = tasks.list_tasks(query="CEIPT generation signed")

    assert [match.task_id for match in matches] == [target.task_id]


def test_keyword_search_respects_requested_result_bound(stores):
    tasks, _verifier, _artifacts = stores
    task_ids = ("task-bounded-search-a", "task-bounded-search-b")
    for task_id in task_ids:
        tasks.create(
            GoalContract(
                goal="bounded quasar receipt search",
                acceptance_criteria=("tests",),
                scope=AgentScope.TASK,
            ),
            ScopeContext(repository_id="repo-receipts", task_id=task_id),
            task_id=task_id,
            actor="tenant-a",
        )

    matches = tasks.list_tasks(query="quasar", limit=1)

    assert len(matches) == 1
    assert matches[0].task_id in task_ids
    assert matches.query_truncated is False


def test_passing_test_receipt_requires_command_id():
    with pytest.raises(ValueError, match="requires command_id"):
        VerificationReceipt.create(
            "task-missing-command",
            "tests",
            passed=True,
            evidence_id="ev-without-command",
            evidence_type="test",
        )


def test_recorded_receipt_retrieves_after_verifier_restart(stores):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(tasks, "task-retrieval")
    receipt = passing_receipt(tasks, verifier, artifacts, task.task_id)
    verifier.record(receipt)

    reopened = VerificationStore(tasks.state_store, task_store=tasks, artifact_store=artifacts)
    completion = reopened.completion(task.task_id, current_revision="rev-1")

    assert completion.complete is True
    assert completion.satisfied_criteria == ("tests",)
    assert len(completion.receipts) == 1
    assert completion.receipts[0].to_dict() == receipt.to_dict()
    retrieved = completion.receipts[0]
    assert (
        retrieved.task_id,
        retrieved.owner,
        retrieved.command_id,
        retrieved.evidence_id,
        retrieved.repository_revision,
    ) == (
        receipt.task_id,
        receipt.owner,
        receipt.command_id,
        receipt.evidence_id,
        receipt.repository_revision,
    )


def test_recording_same_receipt_twice_is_idempotent(stores):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(tasks, "task-idempotent-receipt")
    receipt = passing_receipt(tasks, verifier, artifacts, task.task_id)

    first = verifier.record(receipt)
    second = verifier.record(receipt)
    completion = verifier.completion(task.task_id, current_revision="rev-1")

    assert first.to_dict() == second.to_dict() == receipt.to_dict()
    assert completion.complete is True
    assert [item.receipt_id for item in completion.receipts] == [receipt.receipt_id]


def test_receipt_owner_metadata_uses_versioned_existing_details_envelope(stores):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(tasks, "task-versioned-receipt-metadata")
    receipt = passing_receipt(tasks, verifier, artifacts, task.task_id)
    verifier.record(receipt)

    with closing(connect_sqlite(tasks.state_store.db_path)) as con:
        row = con.execute(
            "SELECT details FROM agent_verification_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()

    assert row is not None
    metadata = json.loads(row[0])["_verification_receipt"]
    assert metadata == {
        "schema": VERIFICATION_RECEIPT_METADATA_SCHEMA,
        "owner": task.owner,
        "mutation_generation": 0,
        "evidence_type": "test",
    }


def test_legacy_receipt_owner_metadata_remains_valid(stores):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(tasks, "task-legacy-receipt-metadata")
    receipt = passing_receipt(tasks, verifier, artifacts, task.task_id)
    verifier.record(receipt)

    with closing(connect_sqlite(tasks.state_store.db_path)) as con:
        row = con.execute(
            "SELECT details FROM agent_verification_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()
        details = json.loads(row[0])
        details["_verification_receipt"].pop("schema")
        con.execute(
            "UPDATE agent_verification_receipts SET details = ? WHERE receipt_id = ?",
            (json.dumps(details, sort_keys=True), receipt.receipt_id),
        )
        con.commit()

    completion = verifier.completion(task.task_id, current_revision="rev-1")

    assert completion.complete is True
    assert completion.receipts[0].owner == task.owner


def test_unknown_receipt_metadata_schema_fails_closed(stores):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(tasks, "task-unknown-receipt-metadata")
    receipt = passing_receipt(tasks, verifier, artifacts, task.task_id)
    verifier.record(receipt)

    with closing(connect_sqlite(tasks.state_store.db_path)) as con:
        row = con.execute(
            "SELECT details FROM agent_verification_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()
        details = json.loads(row[0])
        details["_verification_receipt"]["schema"] = "verification_receipt_metadata.v99"
        con.execute(
            "UPDATE agent_verification_receipts SET details = ? WHERE receipt_id = ?",
            (json.dumps(details, sort_keys=True), receipt.receipt_id),
        )
        con.commit()

    completion = verifier.completion(task.task_id, current_revision="rev-1")

    assert completion.complete is False
    assert completion.unsatisfied_criteria == ("tests",)
    assert completion.receipts == ()


def test_repo_bound_task_rejects_receipt_at_different_revision(stores, tmp_path):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(
        tasks,
        "task-repository-isolation",
        repository_id=str(tmp_path / "repository-a"),
    )
    receipt = passing_receipt(
        tasks, verifier, artifacts, task.task_id, revision="repository-b-rev"
    )
    verifier.record(receipt)

    completion = verifier.completion(task.task_id, current_revision="repository-a-rev")

    assert completion.complete is False
    assert completion.stale_criteria == ("tests",)
    assert [item.receipt_id for item in completion.receipts] == [receipt.receipt_id]


def test_foreign_task_receipt_cannot_complete_target(stores):
    tasks, verifier, artifacts = stores
    target = task_ready_for_completion(tasks, "task-target")
    foreign = task_ready_for_completion(tasks, "task-foreign")
    verifier.record(passing_receipt(tasks, verifier, artifacts, foreign.task_id))

    completion = verifier.completion(target.task_id, current_revision="rev-1")

    assert completion.complete is False
    assert completion.unsatisfied_criteria == ("tests",)
    assert completion.receipts == ()
    with pytest.raises(CompletionGateError):
        tasks.complete(target.task_id, actor=target.owner, idempotency_key="target-complete")


def test_foreign_tenant_receipt_cannot_complete_task(stores):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(tasks, "task-tenant-scope", owner="tenant-a")
    verifier.record(
        passing_receipt(tasks, verifier, artifacts, task.task_id, owner="tenant-b")
    )

    completion = verifier.completion(task.task_id, current_revision="rev-1")

    assert completion.complete is False
    assert completion.unsatisfied_criteria == ("tests",)
    assert completion.receipts == ()
    with pytest.raises(CompletionGateError):
        tasks.complete(task.task_id, actor=task.owner, idempotency_key="tenant-complete")


def test_newer_foreign_tenant_receipt_is_hidden_and_supersedes_owner_receipt(stores):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(tasks, "task-tenant-latest", owner="tenant-a")
    owner_receipt = replace(
        passing_receipt(tasks, verifier, artifacts, task.task_id), observed_at=10.0
    )
    foreign_receipt = replace(
        passing_receipt(tasks, verifier, artifacts, task.task_id, owner="tenant-b"),
        observed_at=20.0,
    )
    verifier.record(owner_receipt)
    verifier.record(foreign_receipt)

    completion = verifier.completion(task.task_id, current_revision="rev-1")

    assert completion.complete is False
    assert completion.unsatisfied_criteria == ("tests",)
    assert completion.receipts == ()
    with pytest.raises(CompletionGateError):
        tasks.complete(task.task_id, actor=task.owner, idempotency_key="tenant-latest-complete")


def test_stale_revision_receipt_cannot_complete_task(stores):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(tasks, "task-stale-revision")
    verifier.record(
        passing_receipt(tasks, verifier, artifacts, task.task_id, revision="rev-1")
    )
    tasks.checkpoint(
        task.task_id,
        TaskCheckpoint(
            state_data={"repository_revision": "rev-2", "mutation_generation": 0}
        ),
        actor=task.owner,
        idempotency_key="stale-revision-current",
    )

    completion = verifier.completion(task.task_id, current_revision="rev-2")

    assert completion.complete is False
    assert completion.stale_criteria == ("tests",)
    with pytest.raises(CompletionGateError):
        tasks.complete(task.task_id, actor=task.owner, idempotency_key="stale-complete")


def test_valid_durable_receipt_completes_task(stores):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(tasks, "task-valid-completion")
    receipt = passing_receipt(tasks, verifier, artifacts, task.task_id)
    verifier.record(receipt)

    completed = tasks.complete(
        task.task_id,
        actor=task.owner,
        idempotency_key="valid-receipt-complete",
    )

    assert completed.status is TaskStatus.COMPLETED
    persisted = verifier.completion(task.task_id, current_revision="rev-1")
    assert persisted.complete is True
    assert persisted.receipts[0].receipt_id == receipt.receipt_id
