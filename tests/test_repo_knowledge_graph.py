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
    assert issues == [{
        "kind": "business_rule", "id": "b", "code": "dependency_revision_changed",
        "relation": "depends_on", "target_kind": "business_rule", "target_id": "c",
        "expected_revision": "3", "actual_revision": "new",
    }]


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


def test_closed_process_branch_has_no_declared_exit():
    flow = {
        "entry": "start",
        "steps": [
            {"id": "start", "title": "Start", "kind": "decision"},
            {"id": "done", "title": "Done", "kind": "terminal"},
            {"id": "retry", "title": "Retry", "kind": "action"},
            {"id": "loop", "title": "Loop", "kind": "action"},
        ],
        "transitions": [
            {"from": "start", "to": "done", "condition": "success"},
            {"from": "start", "to": "retry", "condition": "failure"},
            {"from": "retry", "to": "loop", "condition": ""},
            {"from": "loop", "to": "retry", "condition": ""},
        ],
    }
    item = _item("order", "rev", kind="process", payload={"flow": flow})
    findings = process_flow_findings({"records": [item]})
    assert {(row["type"], row["step_id"]) for row in findings} == {
        ("no_declared_exit_path", "retry"),
        ("no_declared_exit_path", "loop"),
    }
    assert all(row["status"] == "candidate" for row in findings)
    # A retry cycle with an exit must not be treated as a closed loop.
    flow["transitions"].append({"from": "loop", "to": "done", "condition": "recovered"})
    assert process_flow_findings({"records": [item]}) == []


def test_external_leaf_is_a_possible_process_handoff():
    flow = {
        "entry": "start",
        "steps": [
            {"id": "start", "title": "Start", "kind": "action"},
            {"id": "external", "title": "External process", "kind": "external"},
        ],
        "transitions": [{"from": "start", "to": "external", "condition": ""}],
    }
    item = _item("order", "rev", kind="process", payload={"flow": flow})
    assert process_flow_findings({"records": [item]}) == []


def test_graph_findings_have_distinct_subjects_and_track_target_revision():
    from local_ai_hub.repo_knowledge_quality import quality_report

    records = [
        _item("a", "1", relations=[_ref("b", "old-b"), _ref("c", "old-c")]),
        _item("b", "new-b"),
        _item("c", "new-c"),
    ]
    for row in records:
        row["record"]["payload"]["layer"] = "intended"
        row["record"]["evidence"] = []

    def dependency_findings():
        projected, issues = project_dependency_freshness(records)
        report = quality_report({
            "project_id": "project", "complete": True, "records": projected,
            "issues": [], "graph_issues": issues,
        })
        return {row["dependency"]["target_id"]: row for row in report["findings"]
                if row["type"] == "dependency_revision_changed"}

    initial = dependency_findings()
    assert set(initial) == {"b", "c"}
    assert initial["b"]["id"] != initial["c"]["id"]
    records[1]["revision"] = "newer-b"
    changed = dependency_findings()
    assert changed["b"]["id"] == initial["b"]["id"]
    assert changed["b"]["subject_digest"] != initial["b"]["subject_digest"]
    assert changed["c"]["subject_digest"] == initial["c"]["subject_digest"]
