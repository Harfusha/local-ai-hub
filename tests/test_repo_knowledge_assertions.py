from __future__ import annotations

import hashlib
import json

import pytest

from local_ai_hub.repo_knowledge import RepoKnowledgeStore, build_finding_review
from local_ai_hub.repo_knowledge_assertions import inspect_source_assertion, validate_source_assertion
from local_ai_hub.repo_knowledge_quality import quality_report
from local_ai_hub.repo_plan.schema_validation import RepoPlanValidationError


def test_documented_intent_detects_current_source_literal_drift(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai-hub").mkdir()
    project = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    (root / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project, "mode": "shared",
    }))
    doc = root / "requirements.md"
    doc.write_bytes(b"Paid orders may be rescheduled.\n")
    code = root / "settings.py"
    code.write_bytes(b"ALLOW_RESCHEDULE = False\n")
    record = {
        "schema_version": 1, "project_id": project, "kind": "business_rule", "id": "paid-reschedule",
        "payload": {"title": "Paid order policy", "statement": "Paid orders may be rescheduled",
                    "layer": "intended", "claim_key": "order.reschedule.paid", "claim_value": True,
                    "source_assertion": {"path": "settings.py", "format": "python_literal", "key": ["ALLOW_RESCHEDULE"]}},
        "provenance": {"origin_kind": "manual"}, "relations": [],
        "evidence": [{"schema_version": 1, "path": "requirements.md",
                      "content_digest": hashlib.sha256(doc.read_bytes()).hexdigest(), "start_line": 1, "end_line": 1}],
    }
    store = RepoKnowledgeStore(root)
    store.save(record, expected_revision="", owner="operator", idempotency_key="rule", authorize_write=lambda: True)
    catalog = store.catalog()
    finding = quality_report(catalog)["findings"][0]
    assert finding["type"] == "source_literal_mismatch"
    assert finding["expected"] is True and finding["actual"] is False
    review = build_finding_review(catalog, finding["id"], finding["subject_digest"], "expected", "Temporary deviation")
    store.save(review, expected_revision="", owner="operator", idempotency_key="review", authorize_write=lambda: True)
    assert quality_report(store.catalog())["findings"][0]["review_disposition"] == "expected"
    code.write_bytes(b"# Changed implementation\nALLOW_RESCHEDULE = False\n")
    changed = quality_report(store.catalog())["findings"][0]
    assert changed["id"] == finding["id"] and changed["subject_digest"] != finding["subject_digest"]
    assert changed["review_disposition"] == "needs_revalidation"
    code.write_bytes(b"ALLOW_RESCHEDULE = True\n")
    assert not quality_report(store.catalog())["findings"]


def test_dynamic_and_private_assertions_never_execute(tmp_path):
    source = tmp_path / "settings.py"
    source.write_text("FLAG = False\nif condition:\n    FLAG = True\n", encoding="utf-8")
    assertion = {"path": "settings.py", "format": "python_literal", "key": ["FLAG"]}
    assert inspect_source_assertion(tmp_path, assertion, True)["status"] == "unknown"
    source.write_text("FLAG = __import__('os').system('not executed')\n", encoding="utf-8")
    assert inspect_source_assertion(tmp_path, assertion, True)["status"] == "unknown"
    with pytest.raises(RepoPlanValidationError):
        validate_source_assertion({**assertion, "path": ".local-ai-hub/local/settings.py"})
