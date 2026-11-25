from __future__ import annotations

import pytest

from local_ai_hub.repo_knowledge_graph import process_flow_findings, project_dependency_freshness, validate_process_flow
from local_ai_hub.repo_plan.schema_validation import RepoPlanValidationError


def _item(record_id, revision, freshness="matching_sources", relations=(), kind="business_rule", payload=None):
    return {"record": {"kind": kind, "id": record_id, "relations": list(relations),
                       "payload": payload or {}}, "revision": revision, "freshness": freshness}


def _ref(record_id, digest):
    return {"type": "depends_on", "target_kind": "business_rule", "target_id": record_id,
            "target_revision": digest}


def test_revision_and_source_drift_propagate_without_writes():
    records = [
        _item("a", "1", relations=[_ref("b", "2")]),
        _item("b", "2", relations=[_ref("c", "3")]),
        _item("c", "3", freshness="stale"),
        _item("unrelated", "4"),
    ]
    projected, issues = project_dependency_freshness(records)
    assert [item["freshness"] for item in projected] == ["stale", "stale", "stale", "matching_sources"]
    assert records[0]["freshness"] == "matching_sources"
    assert issues == []
    records[-2] = _item("c", "new")
    projected, issues = project_dependency_freshness(records)
    assert projected[0]["freshness"] == "stale"
    assert issues == [{"kind": "business_rule", "id": "b", "code": "dependency_revision_changed"}]


def test_missing_and_unverified_dependency_cannot_establish_freshness():
    records = [_item("a", "1", relations=[_ref("missing", "2")])]
    projected, issues = project_dependency_freshness(records)
    assert projected[0]["freshness"] == "unknown"
    assert issues[0]["code"] == "dependency_missing_or_unpinned"
    records.append(_item("missing", "2", freshness="unknown"))
    projected, issues = project_dependency_freshness(records)
    assert projected[0]["dependency_status"] == "unknown"
    assert issues == []


def test_declared_process_anomalies_are_candidates():
    flow = {
        "entry": "start",
        "steps": [{"id": "start", "title": "Start", "kind": "action"},
                  {"id": "done", "title": "Done", "kind": "terminal"},
                  {"id": "lost", "title": "Unreachable", "kind": "action"}],
        "transitions": [{"from": "start", "to": "done", "condition": ""}],
    }
    validate_process_flow(flow)
    item = _item("order", "rev", kind="process", payload={"flow": flow})
    assert process_flow_findings({"records": [item]}) == [{
        "type": "unreachable_declared_step", "record_id": "order", "step_id": "lost",
        "record_revision": "rev", "status": "candidate", "freshness": "matching_sources",
    }]
    with pytest.raises(RepoPlanValidationError):
        validate_process_flow({**flow, "entry": "absent"})
