from __future__ import annotations

import pytest

from local_ai_hub.repo_knowledge_quality import build_remediation_contract, knowledge_impact, quality_report
from local_ai_hub.repo_plan.schema_validation import RepoPlanValidationError


def _row(kind, ident, path, relations=(), freshness="matching_sources"):
    return {"record": {"kind": kind, "id": ident, "payload": {"title": ident},
                       "relations": list(relations), "evidence": [{"path": path}]},
            "revision": ident + "-rev", "freshness": freshness}


def _link(kind, ident, relation="depends_on"):
    return {"type": relation, "target_kind": kind, "target_id": ident}


def _catalog(rows):
    return {"project_id": "project", "complete": True, "records": rows, "issues": []}


def test_impact_distinguishes_direct_dependency_and_related():
    catalog = _catalog([
        _row("business_rule", "paid", "order.py"),
        _row("process", "reschedule", "service.py", [_link("business_rule", "paid")]),
        _row("feature", "customer", "ui.py", [_link("process", "reschedule")]),
        _row("glossary", "order", "docs.md", [_link("business_rule", "paid", "mentions")]),
        _row("business_rule", "unrelated", "other.py"),
    ])
    result = knowledge_impact(catalog, ["order.py", "missing.py"])
    assert {item["id"]: item["classification"] for item in result["impacts"]} == {
        "paid": "direct_source", "reschedule": "declared_dependency",
        "customer": "declared_dependency", "order": "related_candidate",
    }
    assert result["unmapped_paths"] == ["missing.py"]
    assert result["impact_digest"]
    with pytest.raises(RepoPlanValidationError):
        knowledge_impact(catalog, ["../outside"])


def test_stale_knowledge_creates_remediation_candidate_not_completion():
    item = _row("business_rule", "paid", "order.py", freshness="stale")
    catalog = _catalog([item])
    report = quality_report(catalog)
    finding = report["findings"][0]
    assert finding["type"] == "stale_knowledge"
    contract = build_remediation_contract(catalog, finding["id"], finding["subject_digest"])
    assert "order.py" in contract["description"]
    assert len(contract["acceptance_criteria"]) == 4
    assert "status" not in contract
    item["revision"] = "new"
    with pytest.raises(RepoPlanValidationError):
        build_remediation_contract(catalog, finding["id"], finding["subject_digest"])
