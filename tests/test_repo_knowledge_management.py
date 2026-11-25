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


def test_handoff_detects_uncommitted_changes_missing_in_second_clone(tmp_path, monkeypatch):
    import shutil
    import subprocess

    import pytest

    from local_ai_hub.repo_task_handoff import attach_source_dependencies, build_task_handoff, inspect_handoff_dependencies
    from local_ai_hub.repo_plan.schema_validation import RepoPlanValidationError

    if shutil.which("git") is None:
        pytest.skip("Git unavailable")

    def git(root, *args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, timeout=15).stdout

    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init")
    git(origin, "config", "user.name", "Fixture")
    git(origin, "config", "user.email", "fixture@example.invalid")
    (origin / ".local-ai-hub").mkdir()
    (origin / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb", "mode": "shared",
    }), encoding="utf-8")
    (origin / ".local-ai-hub/.gitignore").write_text("local/\n", encoding="utf-8")
    (origin / "order.py").write_bytes(b"paid = False\n")
    git(origin, "add", ".")
    git(origin, "commit", "-m", "base")
    (origin / "order.py").write_bytes(b"paid = True\n")
    before = git(origin, "status", "--porcelain")
    store = RepoKnowledgeStore(origin)
    task = {"task_id": "task-1", "repo_root": str(origin), "status": "blocked",
            "contract": {"goal": "Fix order"}, "checkpoint": {"affected_paths": ["order.py"]}}
    legacy = build_task_handoff(store, task)
    assert inspect_handoff_dependencies(store, legacy)["resume_allowed"] is False
    record = attach_source_dependencies(store, legacy)
    assert inspect_handoff_dependencies(store, record)["resume_allowed"] is True
    assert before == git(origin, "status", "--porcelain")
    store.save(record, expected_revision="", owner="operator",
               idempotency_key="handoff", authorize_write=lambda: True)
    git(origin, "add", ".local-ai-hub/agent-os/handoffs")
    git(origin, "commit", "-m", "handoff only")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", str(origin), str(clone))
    copy = RepoKnowledgeStore(clone)
    item = copy.get("handoff", record["id"], verify_sources=False)
    request = {"root": str(clone), "action": "preview_handoff_resume",
               "handoff_id": record["id"], "expected_revision": item["revision"]}
    blocked = manage_repository_knowledge({}, request, authorize_operator_write=lambda: False)
    assert blocked["success"] is True
    assert blocked["resume_allowed"] is False
    assert blocked["dependencies"]["paths"][0]["status"] == "different"
    assert blocked["dependencies"]["runtime_verified"] is False
    (clone / "order.py").write_bytes(b"paid = True\n")
    allowed = manage_repository_knowledge({}, request, authorize_operator_write=lambda: False)
    assert allowed["resume_allowed"] is True
    assert allowed["preview_digest"] != blocked["preview_digest"]
    assert allowed["dependencies"]["coverage"] == "declared_affected_paths_only"
    from local_ai_hub.repo_task_handoff import validate_resume_creation

    creation = {
        "action": "create", "root": str(clone), "repo_root": str(clone),
        "task_id": "task-new", "contract": allowed["contract"],
        "handoff_resume": {"handoff_id": record["id"], "revision": allowed["revision"],
                           "preview_digest": allowed["preview_digest"]},
    }
    validate_resume_creation(creation)
    with pytest.raises(RepoPlanValidationError):
        validate_resume_creation({**creation, "task_id": task["task_id"]})
    with pytest.raises(RepoPlanValidationError):
        validate_resume_creation({**creation, "contract": {"goal": "Different goal"}})
    (clone / "order.py").unlink()
    assert manage_repository_knowledge({}, request, authorize_operator_write=lambda: False)["resume_allowed"] is False
    with pytest.raises(RepoPlanValidationError):
        validate_resume_creation(creation)

    # The real HTTP create handler must reject before invoking the existing store.
    from types import SimpleNamespace
    from local_ai_hub import http_server
    from local_ai_hub.http_post_tasks import handle_agent_state_tasks

    created = []
    responses = []
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        agent_tasks=SimpleNamespace(state_store=SimpleNamespace(enabled=True),
                                    create=lambda *args, **kwargs: created.append((args, kwargs))),
    ))
    handler = SimpleNamespace(_agent=lambda: "agent", _authorization_root=str(clone),
                              _send=lambda status, body: responses.append((status, body)))
    handle_agent_state_tasks(handler, creation)
    assert responses[0][0] == 409
    assert responses[0][1]["operation_not_started"] is True
    assert not created
    assert not (clone / ".local-ai-hub/local").exists()
    assert "paid = True" not in str(record)
    bad = {**record, "payload": {**record["payload"], "source_dependencies": []}}
    with pytest.raises(RepoPlanValidationError):
        inspect_handoff_dependencies(store, bad)


def test_handoff_untracked_private_and_unsafe_dependency_is_not_hashed(tmp_path):
    import shutil
    import subprocess

    import pytest

    from local_ai_hub.repo_task_handoff import attach_source_dependencies, build_task_handoff, inspect_handoff_dependencies

    if shutil.which("git") is None:
        pytest.skip("Git unavailable")
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True, timeout=15)
    (root / ".local-ai-hub").mkdir()
    (root / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb", "mode": "shared",
    }), encoding="utf-8")
    (root / "untracked.py").write_bytes(b"data")
    (root / ".env").write_bytes(b"example")
    subprocess.run(["git", "-C", str(root), "add", ".env"], check=True, capture_output=True, timeout=15)
    store = RepoKnowledgeStore(root)
    task = {"task_id": "task-private", "repo_root": str(root), "status": "planned",
            "contract": {"goal": "Review source"}, "checkpoint": {"affected_paths": ["untracked.py", ".env"]}}
    record = attach_source_dependencies(store, build_task_handoff(store, task))
    assert record["payload"]["source_dependencies"] == [
        {"path": ".env", "content_digest": ""}, {"path": "untracked.py", "content_digest": ""},
    ]
    assert inspect_handoff_dependencies(store, record)["resume_allowed"] is False


def test_agent_state_inventory_reads_only_schema_and_rejects_unknown_fields(tmp_path):
    import sqlite3
    from contextlib import closing

    from local_ai_hub.agent_state_inventory import inspect_agent_state_inventory

    db = tmp_path / "agent_state.sqlite"
    assert inspect_agent_state_inventory(tmp_path)["reason"] == "database_unavailable"
    assert not db.exists()
    with closing(sqlite3.connect(db)) as con:
        con.execute("""CREATE TABLE agent_tasks_projection (
            task_id TEXT PRIMARY KEY, status TEXT NOT NULL, owner TEXT NOT NULL,
            lease_id TEXT NOT NULL, contract TEXT NOT NULL, context TEXT NOT NULL,
            checkpoint TEXT NOT NULL, receipts TEXT NOT NULL, heartbeat_expires_at REAL NOT NULL,
            created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
        con.execute("INSERT INTO agent_tasks_projection VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    ("task-a", "planned", "private-owner", "private-lease", "private-contract",
                     "{}", "{}", "{}", 0, 0, 0))
        con.commit()
    before = db.read_bytes()
    report = inspect_agent_state_inventory(tmp_path)
    assert report["success"] and report["complete"]
    assert not report["canonical_cutover_supported"]
    assert not report["row_values_read"]
    assert not report["classification_is_export_authority"]
    fields = {row["field"]: row["classification"] for row in report["tables"][0]["fields"]}
    assert fields["contract"] == "G+L"
    assert fields["lease_id"] == "L"
    assert fields["receipts"] == "L"
    assert "private-contract" not in str(report) and "private-lease" not in str(report)
    assert db.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["agent_state.sqlite"]
    with closing(sqlite3.connect(db)) as con:
        con.execute("ALTER TABLE agent_tasks_projection ADD COLUMN new_durable_field TEXT")
        con.execute("CREATE TABLE new_store (value TEXT)")
        con.commit()
    report = inspect_agent_state_inventory(tmp_path)
    assert report["success"] and not report["complete"]
    rows = {row["table"]: row for row in report["tables"]}
    assert rows["new_store"]["state"] == "unclassified"
    assert {"field": "new_durable_field", "classification": "unclassified"} in rows["agent_tasks_projection"]["fields"]
    sidecar = tmp_path / "agent_state.sqlite-wal"
    sidecar.write_bytes(b"pending")
    assert inspect_agent_state_inventory(tmp_path)["reason"] == "offline_snapshot_required"
    assert sidecar.read_bytes() == b"pending"


def test_batch_http_requires_exact_scope_authorization_and_reviewed_content(tmp_path):
    root = tmp_path / "repo"
    (root / ".local-ai-hub").mkdir(parents=True)
    project = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    (root / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project, "mode": "shared",
    }), encoding="utf-8")
    record = {"schema_version": 1, "project_id": project, "kind": "business_rule", "id": "rule",
              "payload": {"title": "Rule", "statement": "Current intent", "layer": "intended"},
              "provenance": {"origin_kind": "manual"}, "evidence": [], "relations": []}
    records = [{"record": record, "expected_revision": ""},
               {"record": {**record, "id": "other-rule"}, "expected_revision": ""}]
    request = {"root": str(root), "action": "preview_batch", "records": records}
    preview = manage_repository_knowledge({}, request, authorize_operator_write=lambda: False)
    assert preview["success"]
    assert not (root / ".local-ai-hub/local").exists()
    apply = {**request, "action": "save_batch", "preview_digest": preview["preview_digest"],
             "operation_id": "batch", "apply": True}
    assert manage_repository_knowledge({}, apply, authorize_operator_write=lambda: False)["status_code"] == 403
    assert manage_repository_knowledge(
        {"security": {"allowed_roots": []}}, apply, authorize_operator_write=lambda: True
    )["status_code"] == 403
    assert manage_repository_knowledge(
        {}, {**apply, "records": records[:1]}, authorize_operator_write=lambda: True
    )["status_code"] == 409
    result = manage_repository_knowledge({}, apply, authorize_operator_write=lambda: True)
    assert result["success"] and len(result["file_revisions"]) == 2
    assert not result["canonical_cutover_supported"]
    assert RepoKnowledgeStore(root).get("business_rule", "rule")["record"] == record
