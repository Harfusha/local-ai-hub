from __future__ import annotations

import hashlib
import json

from local_ai_hub.repo_knowledge import RepoKnowledgeStore
from local_ai_hub.repo_knowledge_discovery import publish_file_card_candidate


def test_candidate_is_opt_in_source_bound_and_preserves_human_edit(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai-hub").mkdir()
    (root / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb", "mode": "shared",
    }))
    path = root / "order.py"
    path.write_bytes(b"paid = True\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    card = {"evidence": [{"field": "side_effects", "value": "Paid order flag", "quote": "paid = True"}]}
    assert publish_file_card_candidate({}, str(root), "order.py", digest, card, "model") == "not_authorized"
    assert publish_file_card_candidate({"security": {"knowledge_auto_publish_roots": [str(tmp_path)]}},
                                       str(root), "order.py", digest, card, "model") == "not_authorized"
    config = {"security": {"knowledge_auto_publish_roots": [str(root)]}}
    assert publish_file_card_candidate(config, str(root), "order.py", digest, card, "model") == "published"
    store = RepoKnowledgeStore(root)
    item = store.catalog()["records"][0]
    assert item["record"]["payload"]["layer"] == "interpretation"
    assert item["freshness"] == "matching_sources"
    assert "claim_value" not in item["record"]["payload"]
    assert publish_file_card_candidate(config, str(root), "order.py", digest, card, "model") == "unchanged"
    edited = item["record"]
    edited["payload"]["statement"] = "Human correction"
    store.save(edited, expected_revision=item["revision"], owner="operator", idempotency_key="edit",
               authorize_write=lambda: True)
    path.write_bytes(b"paid = False\n")
    new_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    new_card = {"evidence": [{"field": "side_effects", "value": "Paid order flag changed", "quote": "paid = False"}]}
    assert publish_file_card_candidate(config, str(root), "order.py", new_digest, new_card, "model") == "human_preserved"
    assert store.catalog()["records"][0]["record"]["payload"]["statement"] == "Human correction"


def test_source_card_without_exact_quote_cannot_publish(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai-hub").mkdir()
    (root / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb", "mode": "shared",
    }))
    path = root / "order.py"
    path.write_bytes(b"paid = True\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    config = {"security": {"knowledge_auto_publish_roots": [str(root)]}}
    card = {"evidence": [{"field": "purpose", "value": "Paid order", "quote": "missing code"}]}
    assert publish_file_card_candidate(config, str(root), "order.py", digest, card, "model") == "no_candidate"
    assert RepoKnowledgeStore(root).catalog()["records"] == []
