"""Deterministic dependency and process projections over the Git-native catalog.

No separate graph database, source claim promotion, or background writes.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .repo_plan.schema_validation import RepoPlanValidationError

_DEPENDENCY_TYPES = frozenset({"depends_on", "derived_from", "verified_by"})
_STATE_RANK = {"matching_sources": 0, "unknown": 1, "stale": 2}


def project_dependency_freshness(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Project dependency freshness by monotone propagation on a bounded graph.

    A relation with no pinned target revision is not proof of freshness.
    Missing or unverified targets produce unknown; changed target revisions
    or stale source dependencies propagate stale. Other links are navigation.
    """
    items = {(row["record"]["kind"], row["record"]["id"]): dict(row) for row in records}
    states = {key: row["freshness"] for key, row in items.items()}
    edges: dict[tuple[str, str], list[tuple[str, str]]] = {}
    direct: dict[tuple[str, str], str] = {}
    issues = []
    for key, row in items.items():
        relations = row["record"]["relations"]
        targets = []
        status = "not_applicable"
        for ref in relations:
            target = (ref["target_kind"], ref["target_id"])
            if ref["type"] not in _DEPENDENCY_TYPES:
                continue
            if status == "not_applicable":
                status = "matching_sources"
            target_row = items.get(target)
            if target_row is None or not ref.get("target_revision"):
                if status != "stale":
                    status = "unknown"
                issues.append({"kind": key[0], "id": key[1], "code": "dependency_missing_or_unpinned"})
            elif target_row["revision"] != ref["target_revision"]:
                status = "stale"
                issues.append({"kind": key[0], "id": key[1], "code": "dependency_revision_changed"})
            if target_row is not None:
                targets.append(target)
        if status != "not_applicable":
            direct[key] = status
            edges[key] = targets
            states[key] = max((states[key], status), key=_STATE_RANK.__getitem__)
    # At most |V| rounds are needed for transitive monotone propagation.
    for _ in range(len(items)):
        changed = False
        for key, targets in edges.items():
            candidate = max((states[key], *(states[target] for target in targets)), key=_STATE_RANK.__getitem__)
            if candidate != states[key]:
                states[key] = candidate
                changed = True
        if not changed:
            break
    result = []
    for key, row in items.items():
        if key in direct:
            dependency_status = max((direct[key], *(states[target] for target in edges[key])), key=_STATE_RANK.__getitem__)
            row["dependency_status"] = dependency_status
            row["freshness"] = states[key]
        result.append(row)
    return result, issues[:128]


def validate_process_flow(flow: Any) -> None:
    """Check explicit flow declarations without inferring actual execution."""
    from .repo_knowledge import _identifier, _text

    def fail() -> None:
        raise RepoPlanValidationError("Invalid structured process flow")

    if not isinstance(flow, dict) or set(flow) != {"entry", "steps", "transitions"}:
        fail()
    steps = flow["steps"]
    transitions = flow["transitions"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 24:
        fail()
    if not isinstance(transitions, list) or len(transitions) > 48:
        fail()
    identifiers: set[str] = set()
    for step in steps:
        if not isinstance(step, dict) or set(step) != {"id", "title", "kind"}:
            fail()
        if not _identifier(step["id"]) or not _text(step["title"], 160):
            fail()
        if step["kind"] not in ("action", "decision", "terminal", "external"):
            fail()
        if step["id"] in identifiers:
            fail()
        identifiers.add(step["id"])
    if not _identifier(flow["entry"]) or flow["entry"] not in identifiers:
        fail()
    seen: set[tuple[str, str, str]] = set()
    for transition in transitions:
        if not isinstance(transition, dict) or set(transition) != {"from", "to", "condition"}:
            fail()
        if not _identifier(transition["from"]) or not _identifier(transition["to"]):
            fail()
        if transition["from"] not in identifiers or transition["to"] not in identifiers:
            fail()
        if transition["condition"] != "" and not _text(transition["condition"], 240):
            fail()
        key = (transition["from"], transition["to"], transition["condition"])
        if key in seen:
            fail()
        seen.add(key)


def process_flow_findings(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Find declared graph anomalies; never treat graph topology as runtime proof."""
    findings = []
    for item in catalog["records"]:
        record = item["record"]
        flow = record["payload"].get("flow")
        if record["kind"] != "process" or not flow:
            continue
        validate_process_flow(flow)
        successors: dict[str, set[str]] = {step["id"]: set() for step in flow["steps"]}
        for transition in flow["transitions"]:
            successors[transition["from"]].add(transition["to"])
        reachable = {flow["entry"]}
        frontier = list(reachable)
        while frontier:
            for target in successors[frontier.pop()]:
                if target not in reachable:
                    reachable.add(target)
                    frontier.append(target)
        # Reverse reachability from declared exits detects closed loops and
        # upstream branches with no possible exit. External leaf steps may
        # hand control to another process; they are not proof of completion.
        predecessors: dict[str, set[str]] = {step_id: set() for step_id in successors}
        for source, targets in successors.items():
            for target in targets:
                predecessors[target].add(source)
        can_exit = {
            step["id"] for step in flow["steps"]
            if step["kind"] == "terminal"
            or (step["kind"] == "external" and not successors[step["id"]])
        }
        frontier = list(can_exit)
        while frontier:
            for source in predecessors[frontier.pop()]:
                if source not in can_exit:
                    can_exit.add(source)
                    frontier.append(source)
        for step in flow["steps"]:
            step_id = step["id"]
            code = ""
            if step_id not in reachable:
                code = "unreachable_declared_step"
            elif step["kind"] == "terminal" and successors[step_id]:
                code = "terminal_has_successors"
            elif step["kind"] in {"action", "decision"} and not successors[step_id]:
                code = "nonterminal_without_transition"
            elif step_id not in can_exit:
                code = "no_declared_exit_path"
            if code:
                findings.append({"type": code, "record_id": record["id"], "step_id": step_id,
                                 "record_revision": item["revision"], "status": "candidate",
                                 "freshness": item["freshness"]})
                if len(findings) >= 128:
                    return findings
    return findings
