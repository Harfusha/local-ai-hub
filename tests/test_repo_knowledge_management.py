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
