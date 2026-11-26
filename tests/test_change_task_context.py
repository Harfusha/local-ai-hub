from __future__ import annotations

from types import SimpleNamespace

from local_ai_hub.change_task_context import attach_task_context, task_verification_candidates


def test_task_receipts_are_current_candidates_not_commit_proof(tmp_path):
    task = SimpleNamespace(
        task_id="task-1", checkpoint=SimpleNamespace(affected_paths=("src/a.py",)),
        contract=SimpleNamespace(goal="change a"),
    )
    receipt = SimpleNamespace(passed=True, repository_revision="r1", criterion="test", receipt_id="receipt-current")
    stale = SimpleNamespace(passed=True, repository_revision="r0", criterion="test", receipt_id="receipt-stale")
    verification = SimpleNamespace(completion=lambda task_id, current_revision: SimpleNamespace(
        complete=True, satisfied_criteria=("test",), unsatisfied_criteria=(), stale_criteria=(),
        receipts=(receipt, stale),
    ))
    service = SimpleNamespace(
        repo_state=SimpleNamespace(fingerprint=lambda root, force: {"fingerprint": "r1"}),
        verification_store=verification,
    )
    result = {"success": True, "clusters": [{"files": ["src/a.py"]}, {"files": ["src/b.py"]}]}
    attach_task_context(service, result, [task], str(tmp_path), revision_before="r1", truncated=False)
    match = result["clusters"][0]["task_candidates"][0]
    assert match["verification"]["receipt_ids"] == ["receipt-current"]
    assert match["verification"]["commit_verified"] is False
    assert not result["clusters"][1]["task_candidates"]
    assert result["task_context"]["commit_receipt_reuse_authorized"] is False
    assert task_verification_candidates(service, task, "")["status"] == "unknown"
