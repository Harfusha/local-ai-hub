from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from local_ai_hub.repo_knowledge import RepoKnowledgeStore, build_knowledge_context, detect_declared_claim_conflicts, query_declared_knowledge
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
    assert detect_declared_claim_conflicts(catalog) == [{
        "type": "declared_claim_conflict", "claim_key": "order.reschedule.paid",
        "intended_id": "order-paid", "observed_id": "order-paid", "status": "candidate",
    }]
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
