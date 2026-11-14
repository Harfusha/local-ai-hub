from __future__ import annotations

import time
from pathlib import Path

from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.agent_verification import (
    VerificationReceipt,
    criterion_evidence_type,
    evaluate_completion_receipts,
)


def make_proof_receipt(
    task_id: str,
    criterion: str,
    artifact_store: ArtifactStore,
    *,
    passed: bool = True,
    owner: str = "agent",
    repository_revision: str = "rev-1",
    mutation_generation: int = 1,
    command_id: str | None = None,
) -> VerificationReceipt:
    kind = criterion_evidence_type(criterion)
    cmd_key = command_id or ("cmd-1" if kind in {"test", "benchmark"} else "")
    proof = {
        "kind": "work_command_verification" if cmd_key else "work_source_review",
        "passed": passed,
        "task_id": task_id,
        "owner": owner,
        "repository_revision": repository_revision,
        "mutation_generation": mutation_generation,
    }
    if cmd_key:
        proof.update(
            criterion=criterion,
            command_id=cmd_key,
            exit_code=0 if passed else 1,
            result={"success": passed, "exit_code": 0 if passed else 1},
        )
    else:
        proof["criteria"] = [criterion]

    evidence_id = artifact_store.put_json(
        proof, kind="command_verification" if cmd_key else "source_review"
    )
    return VerificationReceipt.create(
        task_id=task_id,
        criterion=criterion,
        passed=passed,
        expires_at=time.time() + 3600,
        evidence_id=evidence_id,
        command_id=cmd_key,
        owner=owner,
        repository_revision=repository_revision,
        mutation_generation=mutation_generation,
        evidence_type=kind,
    )


def test_stale_receipt_rejected(tmp_path: Path):
    """DoD: Stale receipt (older mutation_generation) is rejected."""
    art_store = ArtifactStore(tmp_path / "artifacts")
    receipt = make_proof_receipt(
        task_id="t-stale",
        criterion="test_suite_passes",
        artifact_store=art_store,
        owner="owner-1",
        repository_revision="rev-abc",
        mutation_generation=1,
    )
    # Current task mutation_generation is 2
    result = evaluate_completion_receipts(
        task_id="t-stale",
        required_criteria=["test_suite_passes"],
        receipts=[receipt],
        owner="owner-1",
        repository_revision="rev-abc",
        mutation_generation=2,
        artifact_store=art_store,
    )
    assert result.complete is False
    assert "test_suite_passes" in result.stale_criteria


def test_wrong_scope_or_owner_receipt_rejected(tmp_path: Path):
    """DoD: Receipt with wrong owner is rejected."""
    art_store = ArtifactStore(tmp_path / "artifacts")
    receipt = make_proof_receipt(
        task_id="t-scope",
        criterion="lint_clean",
        artifact_store=art_store,
        owner="foreign_agent",
        repository_revision="rev-abc",
        mutation_generation=1,
    )
    result = evaluate_completion_receipts(
        task_id="t-scope",
        required_criteria=["lint_clean"],
        receipts=[receipt],
        owner="authorized_owner",
        repository_revision="rev-abc",
        mutation_generation=1,
        artifact_store=art_store,
    )
    assert result.complete is False
    assert "lint_clean" in result.unsatisfied_criteria


def test_deleted_or_missing_artifact_receipt_rejected(tmp_path: Path):
    """DoD: Receipt referencing missing/deleted artifact is rejected."""
    empty_art_store = ArtifactStore(tmp_path / "artifacts_empty")
    receipt = VerificationReceipt.create(
        task_id="t-art",
        criterion="build_artifact_verified",
        passed=True,
        expires_at=time.time() + 3600,
        evidence_id="art_missing_nonexistent",
        command_id="",
        owner="owner-3",
        repository_revision="rev-abc",
        mutation_generation=1,
        evidence_type="source_review",
    )
    result = evaluate_completion_receipts(
        task_id="t-art",
        required_criteria=["build_artifact_verified"],
        receipts=[receipt],
        owner="owner-3",
        repository_revision="rev-abc",
        mutation_generation=1,
        artifact_store=empty_art_store,
    )
    assert result.complete is False
    assert "build_artifact_verified" in result.unsatisfied_criteria


def test_tampered_hash_or_mismatched_revision_rejected(tmp_path: Path):
    """DoD: Tampered revision / mismatched source revision is rejected."""
    art_store = ArtifactStore(tmp_path / "artifacts")
    receipt = make_proof_receipt(
        task_id="t-rev",
        criterion="critical_security_check",
        artifact_store=art_store,
        owner="owner-4",
        repository_revision="rev-old-123",
        mutation_generation=1,
    )
    result = evaluate_completion_receipts(
        task_id="t-rev",
        required_criteria=["critical_security_check"],
        receipts=[receipt],
        owner="owner-4",
        repository_revision="rev-fresh-456",  # Different expected revision
        mutation_generation=1,
        artifact_store=art_store,
        require_repository_revision=True,
    )
    assert result.complete is False
    assert "critical_security_check" in result.stale_criteria


def test_incomplete_criteria_rejected(tmp_path: Path):
    """DoD: Incomplete verification rejected when criteria missing."""
    art_store = ArtifactStore(tmp_path / "artifacts")
    receipt1 = make_proof_receipt(
        task_id="t-inc",
        criterion="criterion_1_done",
        artifact_store=art_store,
        owner="owner-5",
        repository_revision="rev-ok",
        mutation_generation=1,
    )
    # Task requires criterion_1_done AND criterion_2_done
    result = evaluate_completion_receipts(
        task_id="t-inc",
        required_criteria=["criterion_1_done", "criterion_2_done"],
        receipts=[receipt1],
        owner="owner-5",
        repository_revision="rev-ok",
        mutation_generation=1,
        artifact_store=art_store,
    )
    assert result.complete is False
    assert "criterion_1_done" in result.satisfied_criteria
    assert "criterion_2_done" in result.unsatisfied_criteria


def test_strong_receipt_schema_with_source_revision_and_artifacts(tmp_path: Path):
    """DoD: Complete, valid, fresh verification with matching revision succeeds."""
    art_store = ArtifactStore(tmp_path / "artifacts")
    receipt1 = make_proof_receipt(
        task_id="t-valid",
        criterion="test_passes",
        artifact_store=art_store,
        owner="owner-valid",
        repository_revision="rev-valid-100",
        mutation_generation=1,
    )
    receipt2 = make_proof_receipt(
        task_id="t-valid",
        criterion="lint_passes",
        artifact_store=art_store,
        owner="owner-valid",
        repository_revision="rev-valid-100",
        mutation_generation=1,
    )
    result = evaluate_completion_receipts(
        task_id="t-valid",
        required_criteria=["test_passes", "lint_passes"],
        receipts=[receipt1, receipt2],
        owner="owner-valid",
        repository_revision="rev-valid-100",
        mutation_generation=1,
        artifact_store=art_store,
        require_repository_revision=True,
    )
    assert result.complete is True
    assert set(result.satisfied_criteria) == {"test_passes", "lint_passes"}
    assert len(result.unsatisfied_criteria) == 0
    assert len(result.stale_criteria) == 0
