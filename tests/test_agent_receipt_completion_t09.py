from __future__ import annotations

import json
import subprocess
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
from local_ai_hub.commands import CommandBroker
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
    owner: str = "task-owner-a",
    repository_id: str = "repo-coordination",
):
    contract = GoalContract(
        goal="Verify durable receipt completion",
        acceptance_criteria=("tests",),
        scope=AgentScope.TASK,
    )
    repo_root = Path(tasks.state_store.db_path).parent / "receipt-repositories" / task_id
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / ".gitignore").write_text("", encoding="utf-8")
    (repo_root / ".local-ai.toml").write_text(
        '[commands.test]\nargv = ["python", "-B", "-c", "print(1)"]\n', encoding="utf-8"
    )
    subprocess.run(["git", "init", "--quiet"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "T09 test"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "t09-test@example.invalid"], cwd=repo_root, check=True)
    subprocess.run(["git", "add", ".gitignore", ".local-ai.toml"], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initialize receipt repository"], cwd=repo_root, check=True)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, text=True, capture_output=True
    ).stdout.strip()
    tasks.create(
        contract,
        ScopeContext(repository_id=repository_id, task_id=task_id),
        task_id=task_id,
        actor=owner,
        repo_root=str(repo_root),
        repository_revision=revision,
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
            state_data={"repository_revision": revision, "mutation_generation": 0}
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
    revision: str | None = None,
) -> VerificationReceipt:
    task = tasks.get(task_id)
    assert task is not None
    repo_root = Path(task.checkpoint.state_data["_agent_task_scope"]["repo_root"])
    actual_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, text=True, capture_output=True
    ).stdout.strip()
    assert revision is None or revision == actual_revision
    (repo_root / "test_receipt.py").write_text("def test_receipt_command():\n    assert True\n", encoding="utf-8")

    class _RepoState:
        def fingerprint(self, cwd):
            current = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=cwd, check=True, text=True, capture_output=True
            ).stdout.strip()
            return {"fingerprint": current, "root": str(cwd)}

    broker = CommandBroker(
        {
            "server": {"state_dir": str(Path(tasks.state_store.db_path).parent / "receipt-command-state")},
            "commands": {"enabled": True, "allow_validation": True, "allow_read": True},
        },
        artifacts,
        _RepoState(),
    )
    broker.set_task_store(tasks)
    broker.set_verification_store(verifier)
    verifier.set_command_execution_record_lookup(broker.get_command_execution_record)
    result = broker.run(
        "python -m pytest -q test_receipt.py",
        str(repo_root),
        task_id=task_id,
        criterion="tests",
        timeout=60,
    )
    assert result.get("success") is True, result.get("error")
    receipt_data = result.get("verification_receipt")
    assert isinstance(receipt_data, dict)
    return VerificationReceipt.from_dict(receipt_data)



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
        actor="task-owner-a",
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
        actor="task-owner-a",
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
        actor="task-owner-a",
    )
    tasks.checkpoint(
        target.task_id,
        TaskCheckpoint(next_action="Review signed handoff"),
        actor="task-owner-a",
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
            actor="task-owner-a",
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
    completion = reopened.completion(
        task.task_id, current_revision=task.checkpoint.state_data["repository_revision"]
    )

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
    completion = verifier.completion(
        task.task_id, current_revision=task.checkpoint.state_data["repository_revision"]
    )

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


def test_legacy_receipt_owner_metadata_requires_offline_conversion(stores):
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

    with pytest.raises(ValueError, match="offline conversion required"):
        verifier.completion(
            task.task_id, current_revision=task.checkpoint.state_data["repository_revision"]
        )

    with closing(connect_sqlite(tasks.state_store.db_path)) as con:
        preserved = con.execute(
            "SELECT details FROM agent_verification_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()
    assert preserved is not None
    assert "schema" not in json.loads(preserved[0])["_verification_receipt"]


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

    with pytest.raises(ValueError, match="unsupported stored verification receipt metadata; offline conversion required"):
        verifier.completion(
            task.task_id, current_revision=task.checkpoint.state_data["repository_revision"]
        )

    with closing(connect_sqlite(tasks.state_store.db_path)) as con:
        preserved = con.execute(
            "SELECT details FROM agent_verification_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone()
    assert preserved is not None
    assert json.loads(preserved[0])["_verification_receipt"]["schema"] == "verification_receipt_metadata.v99"


def test_repo_bound_task_rejects_receipt_at_different_revision(stores, tmp_path):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(
        tasks,
        "task-repository-isolation",
        repository_id="repo-coordination-a",
    )
    receipt = passing_receipt(tasks, verifier, artifacts, task.task_id)
    verifier.record(receipt)
    tasks.checkpoint(
        task.task_id,
        TaskCheckpoint(
            state_data={
                **task.checkpoint.state_data,
                "repository_revision": "different-current-revision",
            }
        ),
        actor=task.owner,
        idempotency_key="different-current-revision",
    )

    completion = verifier.completion(task.task_id, current_revision="different-current-revision")

    assert completion.complete is False
    assert completion.stale_criteria == ("tests",)
    assert [item.receipt_id for item in completion.receipts] == [receipt.receipt_id]


def test_foreign_task_receipt_cannot_complete_target(stores):
    tasks, verifier, artifacts = stores
    target = task_ready_for_completion(tasks, "task-target")
    foreign = task_ready_for_completion(tasks, "task-foreign")
    verifier.record(passing_receipt(tasks, verifier, artifacts, foreign.task_id))

    completion = verifier.completion(
        target.task_id, current_revision=target.checkpoint.state_data["repository_revision"]
    )

    assert completion.complete is False
    assert completion.unsatisfied_criteria == ("tests",)
    assert completion.receipts == ()
    with pytest.raises(CompletionGateError):
        tasks.complete(target.task_id, actor=target.owner, idempotency_key="target-complete")


def test_wrong_owner_receipt_cannot_complete_task(stores):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(tasks, "task-owner-scope", owner="task-owner-a")
    receipt = passing_receipt(tasks, verifier, artifacts, task.task_id)
    with closing(connect_sqlite(tasks.state_store.db_path)) as con:
        row = con.execute(
            "SELECT details FROM agent_verification_receipts WHERE receipt_id=?",
            (receipt.receipt_id,),
        ).fetchone()
        assert row is not None
        details = json.loads(row[0])
        details["_verification_receipt"]["owner"] = "other-agent"
        con.execute(
            "UPDATE agent_verification_receipts SET details=? WHERE receipt_id=?",
            (json.dumps(details, sort_keys=True, separators=(",", ":")), receipt.receipt_id),
        )
        con.commit()

    completion = verifier.completion(
        task.task_id, current_revision=task.checkpoint.state_data["repository_revision"]
    )

    assert completion.complete is False
    assert completion.unsatisfied_criteria == ("tests",)
    assert completion.receipts == ()
    with pytest.raises(CompletionGateError):
        tasks.complete(task.task_id, actor=task.owner, idempotency_key="owner-complete")


def test_newer_wrong_owner_receipt_is_hidden_and_supersedes_owner_receipt(stores):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(tasks, "task-owner-latest", owner="task-owner-a")
    owner_receipt = passing_receipt(tasks, verifier, artifacts, task.task_id)
    verifier.record(owner_receipt)
    forged_newer = replace(owner_receipt, owner="other-agent", observed_at=owner_receipt.observed_at + 1)
    with pytest.raises(ValueError, match="matching trusted evidence"):
        verifier.record(forged_newer)

    completion = verifier.completion(
        task.task_id, current_revision=task.checkpoint.state_data["repository_revision"]
    )

    assert completion.complete is True
    assert completion.receipts[0].receipt_id == owner_receipt.receipt_id
    assert tasks.complete(task.task_id, actor=task.owner, idempotency_key="owner-latest-complete").status is TaskStatus.COMPLETED


def test_stale_revision_receipt_cannot_complete_task(stores):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(tasks, "task-stale-revision")
    verifier.record(
        passing_receipt(tasks, verifier, artifacts, task.task_id)
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
    persisted = verifier.completion(
        task.task_id, current_revision=task.checkpoint.state_data["repository_revision"]
    )
    assert persisted.complete is True
    assert persisted.receipts[0].receipt_id == receipt.receipt_id


def test_cancelled_task_with_valid_receipt_cannot_complete(stores):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(tasks, "task-cancelled-receipt")
    verifier.record(passing_receipt(tasks, verifier, artifacts, task.task_id))
    tasks.transition(
        task.task_id,
        TaskStatus.CANCELLED,
        reason="cancel before completion",
        actor=task.owner,
        idempotency_key="cancel-before-complete",
    )

    with pytest.raises(ValueError, match=f"Cannot complete task {task.task_id} from cancelled"):
        tasks.complete(
            task.task_id,
            actor=task.owner,
            idempotency_key="cancelled-receipt-complete",
        )

    assert tasks.get(task.task_id).status is TaskStatus.CANCELLED

def test_keyword_search_backfills_missing_index_after_reopen(stores):
    tasks, _verifier, _artifacts = stores
    task = tasks.create(
        GoalContract(
            goal="Search index recovery",
            description="nebula retrieval after reopen",
            acceptance_criteria=("index repair",),
            scope=AgentScope.TASK,
        ),
        ScopeContext(repository_id="repo-index-recovery", task_id="task-index-recovery"),
        task_id="task-index-recovery",
        actor="task-owner-a",
    )
    with closing(connect_sqlite(tasks.state_store.db_path)) as con:
        con.execute("DROP TABLE agent_task_search_grams")
        con.execute("DROP TABLE agent_task_search_documents")
        con.commit()

    reopened = TaskStore(AgentStateStore(tasks.state_store.db_path, enabled=True))
    matches = reopened.list_tasks(query="nebula retrieval")

    assert [match.task_id for match in matches] == [task.task_id]

def test_source_review_receipt_without_command_completes_documentation_task(stores):
    tasks, verifier, artifacts = stores
    task_id = "task-documentation-review"
    owner = "documentation-reviewer"
    tasks.create(
        GoalContract(
            goal="Document release evidence",
            acceptance_criteria=("documentation review",),
            scope=AgentScope.TASK,
        ),
        ScopeContext(repository_id="repo-documentation", task_id=task_id),
        task_id=task_id,
        actor=owner,
    )
    tasks.transition(
        task_id,
        TaskStatus.ACTIVE,
        reason="start documentation review",
        actor=owner,
        idempotency_key="documentation-active",
    )
    tasks.transition(
        task_id,
        TaskStatus.VERIFYING,
        reason="document review evidence ready",
        actor=owner,
        idempotency_key="documentation-verifying",
    )
    tasks.checkpoint(
        task_id,
        TaskCheckpoint(state_data={"repository_revision": "rev-docs", "mutation_generation": 0}),
        actor=owner,
        idempotency_key="documentation-revision",
    )
    evidence_id = artifacts.put_json(
        {
            "kind": "work_source_review",
            "passed": True,
            "task_id": task_id,
            "owner": owner,
            "criteria": ["documentation review"],
            "repository_revision": "rev-docs",
            "mutation_generation": 0,
            "review_summary": "release docs checked against acceptance criteria",
        },
        kind="source_review",
    )
    receipt = VerificationReceipt.create(
        task_id,
        "documentation review",
        passed=True,
        evidence_id=evidence_id,
        repository_revision="rev-docs",
        owner=owner,
        mutation_generation=0,
    )
    assert receipt.evidence_type == "source_review"
    assert receipt.command_id == ""
    verifier.record(receipt)

    completed = tasks.complete(
        task_id,
        actor=owner,
        idempotency_key="documentation-complete",
    )

    assert completed.status is TaskStatus.COMPLETED
    assert verifier.completion(task_id, current_revision="rev-docs").complete is True


def test_model_assessment_artifact_cannot_satisfy_test_receipt(stores):
    tasks, verifier, artifacts = stores
    task = task_ready_for_completion(tasks, "task-model-is-not-test-proof")
    model_evidence_id = artifacts.put_json(
        {
            "passed": True,
            "task_id": task.task_id,
            "owner": task.owner,
            "criterion": "tests",
            "command_id": "claimed-model-command",
            "repository_revision": "rev-1",
            "mutation_generation": 0,
            "assessment": {"score": 1.0, "summary": "model says tests passed"},
        },
        kind="source_review",
    )
    receipt = VerificationReceipt.create(
        task.task_id,
        "tests",
        passed=True,
        evidence_id=model_evidence_id,
        command_id="claimed-model-command",
        repository_revision="rev-1",
        owner=task.owner,
        mutation_generation=0,
        evidence_type="test",
    )
    with pytest.raises(ValueError, match="requires matching trusted evidence"):
        verifier.record(receipt)

    completion = verifier.completion(
        task.task_id, current_revision=task.checkpoint.state_data["repository_revision"]
    )

    assert completion.complete is False
    assert completion.unsatisfied_criteria == ("tests",)


def test_passed_benchmark_receipt_requires_command_id():
    with pytest.raises(ValueError, match="passed benchmark verification receipt requires command_id"):
        VerificationReceipt.create(
            "task-benchmark-receipt",
            "latency benchmark",
            passed=True,
            evidence_id="benchmark-evidence",
        )
