from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from local_ai_hub.repo_knowledge import RepoKnowledgeStore, build_finding_review, build_knowledge_context, detect_declared_claim_conflicts, query_declared_knowledge
from local_ai_hub.repo_plan.schema_validation import RepoPlanConflictError, RepoPlanValidationError

PROJECT = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"


def _setup(root: Path) -> None:
    root.mkdir()
    folder = root / ".local-ai-hub"
    folder.mkdir()
    (folder / "project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": PROJECT, "mode": "shared"
    }), encoding="utf-8")
    (root / "order.py").write_bytes(b"paid = True\n")


def _rule(root: Path, *, kind: str = "business_rule", layer: str = "intended", value: bool = True) -> dict:
    return {
        "schema_version": 1, "project_id": PROJECT, "kind": kind, "id": "order-paid",
        "payload": {"title": "Paid order", "statement": "Paid order rescheduling",
                    "layer": layer, "claim_key": "order.reschedule.paid", "claim_value": value},
        "provenance": {"origin_kind": "manual"},
        "evidence": [{"schema_version": 1, "path": "order.py",
                      "content_digest": hashlib.sha256((root / "order.py").read_bytes()).hexdigest(),
                      "start_line": 1, "end_line": 1}],
        "relations": [],
    }


def _save(store, record, expected="", key="create"):
    return store.save(record, expected_revision=expected, owner="operator",
                      idempotency_key=key, authorize_write=lambda: True)


def test_clone_read_and_freshness_without_original_database(tmp_path):
    root = tmp_path / "first"
    _setup(root)
    store = RepoKnowledgeStore(root)
    result = _save(store, _rule(root))
    assert result["success"]
    item = store.get("business_rule", "order-paid")
    assert item["freshness"] == "matching_sources"
    clone = tmp_path / "second"
    shutil.copytree(root, clone, ignore=shutil.ignore_patterns("local"))
    clone_store = RepoKnowledgeStore(clone)
    assert clone_store.get("business_rule", "order-paid") == item
    assert not (clone / ".local-ai-hub/local").exists()
    (clone / "unrelated.py").write_text("x = 1", encoding="utf-8")
    assert clone_store.get("business_rule", "order-paid")["freshness"] == "matching_sources"
    (clone / "order.py").write_bytes(b"paid = False\n")
    assert clone_store.get("business_rule", "order-paid")["freshness"] == "stale"


def test_revision_conflict_no_op_and_denied_write(tmp_path):
    root = tmp_path / "repo"
    _setup(root)
    store = RepoKnowledgeStore(root)
    record = _rule(root)
    first = _save(store, record)
    revision = first["file_revision"]
    assert _save(store, record, revision, "noop")["no_op"]
    changed = {**record, "payload": {**record["payload"], "statement": "New expectation"}}
    with pytest.raises(RepoPlanConflictError):
        _save(store, changed, "", "conflict")
    with pytest.raises(RepoPlanConflictError):
        store.save(changed, expected_revision=revision, owner="operator",
                   idempotency_key="denied", authorize_write=lambda: False)
    assert store.get("business_rule", "order-paid")["record"] == record
    _save(store, changed, revision, "edit")
    assert store.get("business_rule", "order-paid")["record"] == changed


def test_structured_conflict_is_candidate_and_stale_sources_excluded(tmp_path):
    root = tmp_path / "repo"
    _setup(root)
    store = RepoKnowledgeStore(root)
    _save(store, _rule(root))
    _save(store, _rule(root, kind="observation", layer="observed", value=False), key="observed")
    catalog = store.catalog()
    assert catalog["complete"]
    findings = detect_declared_claim_conflicts(catalog)
    assert len(findings) == 1
    assert findings[0]["claim_key"] == "order.reschedule.paid"
    assert findings[0]["review_disposition"] == "unreviewed"
    assert findings[0]["status"] == "candidate"
    (root / "order.py").write_bytes(b"paid = False\n")
    assert detect_declared_claim_conflicts(store.catalog()) == []


def test_bad_record_not_silently_treated_as_empty(tmp_path):
    root = tmp_path / "repo"
    _setup(root)
    store = RepoKnowledgeStore(root)
    bad = _rule(root)
    bad["project_id"] = "b6ea81c9-bcb9-4666-8916-e059a8fe9632"
    with pytest.raises(RepoPlanValidationError):
        _save(store, bad)
    folder = root / ".local-ai-hub/knowledge/rules"
    folder.mkdir(parents=True)
    (folder / "broken.json").write_text("<<<<<<< HEAD", encoding="utf-8")
    result = store.catalog()
    assert not result["complete"]
    assert result["issues"] == [{"kind": "business_rule", "code": "invalid_or_unavailable_record"}]

def test_bootstrap_identity_requires_authority_and_cannot_overwrite(tmp_path):
    root = tmp_path / "new"
    root.mkdir()
    store = RepoKnowledgeStore(root)
    with pytest.raises(RepoPlanConflictError):
        store.bootstrap(PROJECT, mode="shared", owner="operator",
                        idempotency_key="denied", authorize_write=lambda: False)
    assert not (root / ".local-ai-hub/project.json").exists()
    store.bootstrap(PROJECT, mode="shared", owner="operator",
                    idempotency_key="init", authorize_write=lambda: True)
    assert store.manifest()[0]["project_id"] == PROJECT
    with pytest.raises(RepoPlanConflictError):
        store.bootstrap("b6ea81c9-bcb9-4666-8916-e059a8fe9632",
                        mode="shared", owner="operator", idempotency_key="other",
                        authorize_write=lambda: True)


def test_declared_knowledge_query_preserves_freshness_and_authority(tmp_path):
    root = tmp_path / "repo"
    _setup(root)
    store = RepoKnowledgeStore(root)
    _save(store, _rule(root))
    result = query_declared_knowledge(store.catalog(), "paid order")
    assert result["answer_status"] == "declarations_only"
    assert result["match_count"] == 1
    assert result["records"][0]["authority"] == "repository_declaration"
    assert query_declared_knowledge(store.catalog(), "unrelated")["records"] == []


def test_business_context_is_bounded_and_untrusted(tmp_path):
    root = tmp_path / "repo"
    _setup(root)
    _save(RepoKnowledgeStore(root), _rule(root))
    from local_ai_hub.budget import estimate_tokens

    context = build_knowledge_context(str(root), "paid order", token_budget=400)
    assert context["records"] == 1
    assert "untrusted data" in context["text"]
    assert "matching_sources" in context["text"]
    assert estimate_tokens(context["text"]) <= 400
    assert not build_knowledge_context(str(root), "unrelated", token_budget=400)["text"]
    assert not build_knowledge_context(str(root), "paid order", token_budget=32)["text"]
    (root / "order.py").write_bytes(b"paid = False\n")
    assert '"freshness":"stale"' in build_knowledge_context(str(root), "paid order", token_budget=400)["text"]


def test_finding_review_is_bound_to_current_subject_and_preserved(tmp_path):
    root = tmp_path / "repo"
    _setup(root)
    store = RepoKnowledgeStore(root)
    first = _save(store, _rule(root))
    _save(store, _rule(root, kind="observation", layer="observed", value=False), key="observation")
    catalog = store.catalog()
    finding = detect_declared_claim_conflicts(catalog)[0]
    review = build_finding_review(catalog, finding["id"], finding["subject_digest"], "expected", "Intentional temporary deviation")
    _save(store, review, key="review")
    reviewed = detect_declared_claim_conflicts(store.catalog())[0]
    assert reviewed["review_disposition"] == "expected"
    assert reviewed["review_authority"] == "repository_declaration"
    changed = _rule(root)
    changed["payload"]["statement"] = "New business requirement"
    _save(store, changed, first["file_revision"], "changed")
    updated = detect_declared_claim_conflicts(store.catalog())[0]
    assert updated["id"] == finding["id"]
    assert updated["subject_digest"] != finding["subject_digest"]
    assert updated["review_disposition"] == "needs_revalidation"
    with pytest.raises(RepoPlanValidationError):
        build_finding_review(store.catalog(), finding["id"], finding["subject_digest"], "expected", "Old review")
    assert store.get("review", review["id"])["record"] == review


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True,
        text=True, timeout=15,
    ).stdout.strip()


def test_real_git_clone_and_checkout_keep_shared_knowledge_without_local_journal(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    root = tmp_path / "origin"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "Knowledge fixture")
    (root / ".local-ai-hub").mkdir()
    (root / ".local-ai-hub/.gitignore").write_text("local/\n", encoding="utf-8")
    (root / "order.py").write_bytes(b"paid = True\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "source")
    store = RepoKnowledgeStore(root)
    store.bootstrap(PROJECT, mode="shared", owner="operator",
                    idempotency_key="init", authorize_write=lambda: True)
    _save(store, _rule(root))
    _git(root, "add", ".")
    _git(root, "commit", "-m", "knowledge")
    assert not _git(root, "ls-files", ".local-ai-hub/local")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(root), str(clone))
    copied = RepoKnowledgeStore(clone)
    assert copied.get("business_rule", "order-paid")["freshness"] == "matching_sources"
    assert not (clone / ".local-ai-hub/local").exists()
    _git(clone, "checkout", "--detach", "HEAD~1")
    with pytest.raises(FileNotFoundError):
        copied.manifest()
    _git(clone, "checkout", "main")
    assert copied.get("business_rule", "order-paid")["freshness"] == "matching_sources"


def test_git_project_without_ignored_local_journal_rejects_publication(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    store = RepoKnowledgeStore(root)
    with pytest.raises(RepoPlanValidationError, match="ignored and untracked"):
        store.bootstrap(PROJECT, mode="shared", owner="operator",
                        idempotency_key="init", authorize_write=lambda: True)
    assert not (root / ".local-ai-hub/local").exists()


def test_common_knowledge_budget_and_attachment_does_not_mint_evidence(tmp_path):
    from local_ai_hub.repo_knowledge import attach_knowledge_context, reserve_knowledge_context
    from local_ai_hub.budget import estimate_tokens

    root = tmp_path / "repo"
    _setup(root)
    _save(RepoKnowledgeStore(root), _rule(root))
    knowledge, technical = reserve_knowledge_context({}, str(root), "paid order", token_budget=2000)
    assert 1600 <= technical < 2000
    packed = {"success": True, "context": "technical source", "evidence": [{"evidence_id": "existing"}]}
    result = attach_knowledge_context(packed, knowledge, token_budget=2000)
    assert result["evidence"] == packed["evidence"]
    assert packed["context"] == "technical source"
    assert "untrusted data" in result["context"]
    assert estimate_tokens(result["context"]) <= 2000
    assert result["knowledge_context_digest"]
    failure = {"success": False, "error": "index unavailable"}
    assert attach_knowledge_context(failure, knowledge, token_budget=2000) is failure
    too_large = {"success": True, "context": "a" * 8000}
    omitted = attach_knowledge_context(too_large, knowledge, token_budget=2000)
    assert omitted["context"] == too_large["context"]
    assert omitted["retrieval"]["knowledge_context_status"] == "budget_omitted"
    denied, unchanged = reserve_knowledge_context(
        {"security": {"allowed_roots": []}}, str(root), "paid order", token_budget=2000,
    )
    assert denied["status"] == "unavailable"
    assert unchanged == 2000


def test_native_query_reuses_authorized_root_and_preserves_declaration(tmp_path):
    from local_ai_hub.repo_knowledge import query_repository_knowledge

    root = tmp_path / "repo"
    _setup(root)
    _save(RepoKnowledgeStore(root), _rule(root))
    payload = {"root": str(root), "query": "paid order", "limit": 4}
    result = query_repository_knowledge({}, payload)
    assert result["success"]
    assert result["records"][0]["freshness"] == "matching_sources"
    assert result["records"][0]["authority"] == "repository_declaration"
    assert not result["evidence_ids"]
    assert query_repository_knowledge({"security": {"allowed_roots": []}}, payload)["status_code"] == 403
    assert query_repository_knowledge({}, {**payload, "limit": True})["status_code"] == 400
    assert query_repository_knowledge({}, {**payload, "unexpected": 1})["status_code"] == 400
    (root / "order.py").write_bytes(b"paid = False\n")
    assert query_repository_knowledge({}, payload)["records"][0]["freshness"] == "stale"


def test_portable_task_handoff_uses_fresh_attempt_without_local_state(tmp_path):
    from local_ai_hub.repo_task_handoff import build_task_handoff, handoff_resume_contract

    root = tmp_path / "repo"
    _setup(root)
    store = RepoKnowledgeStore(root)
    task = {
        "task_id": "task_123", "repo_root": str(root), "status": "completed",
        "contract": {"goal": "Reschedule paid service", "acceptance_criteria": ["tests pass"]},
        "checkpoint": {"phase": "verify", "next_action": "Run focused tests",
                       "affected_paths": ["order.py"], "blockers": [],
                       "state_data": {"secret": "private-state"}, "evidence_ids": ["local-id"]},
        "owner": "local-owner", "lease_id": "old-lease", "verification_receipts": {"tests pass": "old-receipt"},
    }
    record = build_task_handoff(store, task)
    result = _save(store, record, key="handoff")
    assert result["success"]
    serialized = json.dumps(record)
    for private in (str(root), "old-lease", "old-receipt", "private-state", "local-id", "local-owner"):
        assert private not in serialized
    clone = tmp_path / "clone"
    shutil.copytree(root, clone, ignore=shutil.ignore_patterns("local"))
    imported = RepoKnowledgeStore(clone).get("handoff", record["id"])
    contract = handoff_resume_contract(imported["record"])
    assert contract["goal"] == task["contract"]["goal"]
    assert contract["acceptance_criteria"] == ["tests pass"]
    assert "Revalidate" in contract["constraints"][-1]
    assert "status" not in contract
    assert "verification_receipts" not in contract
    assert not RepoKnowledgeStore(clone).catalog()["records"]
    with pytest.raises(RepoPlanValidationError):
        build_task_handoff(store, {**task, "repo_root": str(clone)})
    with pytest.raises(RepoPlanValidationError):
        build_task_handoff(store, {**task, "checkpoint": {**task["checkpoint"], "affected_paths": ["../outside"]}})


def test_knowledge_query_operation_contract_agrees_with_service(tmp_path):
    from local_ai_hub.operation_contracts import operation_input_schema, validate_operation_arguments
    from local_ai_hub.http_route_registry import select_http_routes

    schema = operation_input_schema("local_ai_repo", "knowledge_query")
    assert schema["properties"]["limit"]["maximum"] == 8
    assert schema["properties"]["limit"]["default"] == 4
    payload = {"root": str(tmp_path), "query": "service", "limit": 4}
    assert validate_operation_arguments("local_ai_repo", "knowledge_query", payload) is None
    assert validate_operation_arguments("local_ai_repo", "knowledge_query", {**payload, "limit": 9})
    assert validate_operation_arguments("local_ai_repo", "knowledge_query", {**payload, "query": " "})
    assert select_http_routes("POST", "/api/repo/knowledge/query") == ("post_repo_knowledge_query_1",)


def test_czech_query_and_changed_paths_select_business_context(tmp_path):
    root = tmp_path / "repo"
    _setup(root)
    store = RepoKnowledgeStore(root)
    _save(store, _rule(root))
    catalog = store.catalog()
    assert query_declared_knowledge(catalog, "zaplacené objednávky")["records"][0]["record"]["id"] == "order-paid"
    assert query_declared_knowledge(catalog, "unrelated", changed_paths=("order.py",))["records"][0]["record"]["id"] == "order-paid"
    assert not query_declared_knowledge(catalog, "unrelated", changed_paths=("../order.py",))["records"]
    assert build_knowledge_context(str(root), "unrelated", token_budget=400, changed_paths=("order.py",))["records"] == 1
    (root / "order.py").write_bytes(b"paid = False\n")
    assert build_knowledge_context(str(root), "unrelated", token_budget=400, changed_paths=("order.py",))["needs_revalidation"]


def test_bounded_catalog_retains_records_and_reports_unknown_coverage(tmp_path):
    root = tmp_path / "repo"
    _setup(root)
    folder = root / ".local-ai-hub/knowledge/rules"
    folder.mkdir(parents=True)
    for i in range(60):
        record = _rule(root)
        record["id"] = f"order-{i:03d}"
        (folder / (record["id"] + ".json")).write_text(json.dumps(record), encoding="utf-8")
    store = RepoKnowledgeStore(root)
    catalog = store.catalog(verify_sources=False, max_records=2)
    assert len(catalog["records"]) == 2
    assert not catalog["complete"]
    assert {"kind": "business_rule", "code": "inventory_limit"} in catalog["issues"]
    context = build_knowledge_context(str(root), "paid order", token_budget=400)
    assert context["records"] >= 1
    assert context["status"] == "partial"
    assert context["needs_revalidation"] is True
    missing = build_knowledge_context(str(root), "irrelevant keyword", token_budget=400)
    assert missing["status"] == "partial"
    assert missing["needs_revalidation"] is True


def test_context_rechecks_selected_revision_after_source_read(tmp_path, monkeypatch):
    from local_ai_hub.evidence import EvidenceStore
    from local_ai_hub.repo_knowledge import query_repository_knowledge

    root = tmp_path / "repo"
    _setup(root)
    store = RepoKnowledgeStore(root)
    _save(store, _rule(root))
    path = root / ".local-ai-hub/knowledge/rules/order-paid.json"
    original = EvidenceStore.portable_source_status

    def edit_during_read(ref, *, root):
        result = original(ref, root=root)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["payload"]["statement"] += " Changed."
        path.write_text(json.dumps(record), encoding="utf-8")
        return result

    monkeypatch.setattr(EvidenceStore, "portable_source_status", staticmethod(edit_during_read))
    context = build_knowledge_context(str(root), "paid order", token_budget=400)
    assert context["status"] == "changed_during_read"
    assert not context["text"]
    assert context["needs_revalidation"] is True
    result = query_repository_knowledge({}, {"root": str(root), "query": "paid order"})
    assert result["status_code"] == 409
    assert result["retryable"] is True
