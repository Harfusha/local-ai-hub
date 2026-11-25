from __future__ import annotations

import json

from local_ai_hub.repo_knowledge import RepoKnowledgeStore
from local_ai_hub.repo_knowledge_management import manage_repository_knowledge


def test_preview_requires_current_revision_and_explicit_authorized_save(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai-hub").mkdir()
    project = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    (root / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project, "mode": "shared",
    }))
    record = {"schema_version": 1, "project_id": project, "kind": "business_rule", "id": "rule",
              "payload": {"title": "Rule", "statement": "Current intent", "layer": "intended"},
              "provenance": {"origin_kind": "manual"}, "evidence": [], "relations": []}
    request = {"root": str(root), "action": "preview_edit", "record": record, "expected_revision": ""}
    preview = manage_repository_knowledge({}, request, authorize_operator_write=lambda: False)
    assert preview["success"] and preview["before"] is None
    assert not (root / ".local-ai-hub/local").exists()
    apply = {**request, "action": "save_edit", "preview_digest": preview["preview_digest"],
             "operation_id": "op1", "apply": True}
    assert manage_repository_knowledge({}, apply, authorize_operator_write=lambda: False)["status_code"] == 403
    changed = {**record, "payload": {**record["payload"], "statement": "Changed after preview"}}
    assert manage_repository_knowledge({}, {**apply, "record": changed}, authorize_operator_write=lambda: True)["status_code"] == 409
    assert manage_repository_knowledge({}, apply, authorize_operator_write=lambda: True)["success"]
    assert RepoKnowledgeStore(root).get("business_rule", "rule")["record"] == record
    assert manage_repository_knowledge({}, request, authorize_operator_write=lambda: True)["status_code"] == 409
    report = manage_repository_knowledge({}, {"root": str(root), "action": "audit"}, authorize_operator_write=lambda: False)
    assert report["findings"][0]["type"] == "unverified_knowledge"
    assert manage_repository_knowledge({"security": {"allowed_roots": []}}, request,
                                       authorize_operator_write=lambda: True)["status_code"] == 403


def test_handoff_inventory_includes_only_valid_project_records(tmp_path):
    import hashlib

    from local_ai_hub.repo_task_handoff import list_task_handoffs

    root = tmp_path / "repo"
    directory = root / ".local-ai-hub/agent-os/handoffs"
    directory.mkdir(parents=True)
    project = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    (root / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project, "mode": "shared",
    }), encoding="utf-8")
    origin = "task-original"
    handoff_id = "handoff-" + hashlib.sha256(origin.encode()).hexdigest()[:24]
    record = {
        "schema_version": 1, "project_id": project, "kind": "handoff", "id": handoff_id,
        "payload": {
            "origin_task_id": origin, "historical_status": "planned",
            "contract": {"goal": "Resume work", "description": "", "acceptance_criteria": [],
                         "non_goals": [], "constraints": [], "risk_profile": "normal"},
            "checkpoint": {"phase": "", "next_action": "", "blockers": [], "affected_paths": []},
        },
        "provenance": {"origin_kind": "manual"}, "evidence": [], "relations": [],
    }
    (directory / (handoff_id + ".json")).write_text(json.dumps(record), encoding="utf-8")
    (directory / "invalid.json").write_text("not JSON", encoding="utf-8")
    result = list_task_handoffs(RepoKnowledgeStore(root))
    assert result["complete"] is False
    assert result["issues"] == ["invalid_or_unavailable_handoff"]
    assert len(result["handoffs"]) == 1
    item = result["handoffs"][0]
    assert item["id"] == handoff_id
    assert item["requires_revalidation"] is True
    assert item["revision"]
    request = {"root": str(root), "action": "handoff_list", "limit": 32}
    response = manage_repository_knowledge({}, request, authorize_operator_write=lambda: False)
    assert response["success"] is True
    assert response["handoffs"] == result["handoffs"]
    preview_request = {"root": str(root), "action": "preview_handoff_resume",
                       "handoff_id": handoff_id, "expected_revision": item["revision"]}
    preview = manage_repository_knowledge({}, preview_request, authorize_operator_write=lambda: False)
    assert preview["success"] is True
    assert preview["requires_revalidation"] is True
    assert preview["contract"]["goal"] == "Resume work"
    assert "verification_receipts" not in preview["contract"]
    assert preview["historical_verification"] == []
    assert preview["preview_digest"]
    assert manage_repository_knowledge(
        {}, {**preview_request, "expected_revision": "0" * 64}, authorize_operator_write=lambda: False
    )["status_code"] == 409
    assert manage_repository_knowledge(
        {"security": {"allowed_roots": []}}, preview_request, authorize_operator_write=lambda: False
    )["status_code"] == 403
    assert manage_repository_knowledge(
        {"security": {"allowed_roots": []}}, request, authorize_operator_write=lambda: False
    )["status_code"] == 403
    assert not (root / ".local-ai-hub/local").exists()


def test_handoff_preflight_is_scoped_read_only_and_never_imports_runtime_state(tmp_path):
    from local_ai_hub.repo_task_handoff import build_task_handoff, preflight_task_handoffs

    root = tmp_path / "repo"
    directory = root / ".local-ai-hub/agent-os/handoffs"
    directory.mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    project = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    (root / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project, "mode": "shared",
    }), encoding="utf-8")
    store = RepoKnowledgeStore(root)

    def task(task_id, **changes):
        return {
            "task_id": task_id, "status": "planned", "repo_root": str(root),
            "contract": {"goal": "Private task details", "description": ""},
            "checkpoint": {}, "verification_receipts": {"criterion": "local-receipt"},
            **changes,
        }

    existing = task("existing")
    record = build_task_handoff(store, existing)
    (directory / (record["id"] + ".json")).write_text(json.dumps(record), encoding="utf-8")
    result = preflight_task_handoffs(store, [
        existing, task("new"), task("live", status="active", lease_id="local-lease"),
        task("outside", repo_root=str(other)), task("new"),
    ], inventory_complete=False)
    assert [row["state"] for row in result["records"]] == [
        "already_published", "review_required", "blocked_live_attempt",
        "blocked_invalid_or_out_of_scope", "blocked_duplicate_task",
    ]
    assert not result["complete"]
    assert not result["canonical_cutover_supported"]
    assert not result["runtime_state_imported"]
    assert "Private task details" not in str(result)
    assert "local-receipt" not in str(result)
    assert "local-lease" not in str(result)
    assert "outside" not in str(result)
    assert len(list(directory.iterdir())) == 1
    assert not (root / ".local-ai-hub/local").exists()


def test_portable_handoff_receipt_summary_never_grants_current_verification(tmp_path):
    from local_ai_hub.repo_task_handoff import (
        attach_historical_verification, build_task_handoff, handoff_resume_contract,
    )
    from local_ai_hub.repo_plan.schema_validation import RepoPlanValidationError
    import pytest

    root = tmp_path / "repo"
    (root / ".local-ai-hub").mkdir(parents=True)
    (root / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb", "mode": "shared",
    }), encoding="utf-8")
    store = RepoKnowledgeStore(root)
    task = {
        "task_id": "task-demo", "status": "completed", "repo_root": str(root),
        "contract": {"goal": "Review the order", "acceptance_criteria": ["Run order tests"]},
        "checkpoint": {}, "verification_receipts": {"Run order tests": "local-receipt"},
    }
    receipt = {
        "task_id": "task-demo", "receipt_id": "local-receipt",
        "criterion": "Run order tests", "repository_revision": "local-revision",
        "passed": True, "evidence_type": "test", "command_id": "local-command",
        "details": {"raw": "private output"},
    }
    record = build_task_handoff(store, task)
    shared = attach_historical_verification(record, task, [receipt])
    summary = shared["payload"]["historical_verification"][0]
    assert summary["reported_pass"] is True
    assert len(summary["revision_digest"]) == 64
    for value in ("local-receipt", "local-command", "local-revision", "private output"):
        assert value not in str(shared)
    contract = handoff_resume_contract(shared)
    assert contract["acceptance_criteria"] == ["Run order tests"]
    assert "verification_receipts" not in contract
    assert "none are valid verification" in contract["description"]
    for bad in (
        {**receipt, "task_id": "other-task"},
        {**receipt, "criterion": "Different criterion"},
        {**receipt, "repository_revision": ""},
        {**receipt, "passed": "true"},
    ):
        with pytest.raises(RepoPlanValidationError):
            attach_historical_verification(record, task, [bad])
    with pytest.raises(RepoPlanValidationError):
        attach_historical_verification(record, task, [])
