"""Bounded append-only problem reports embedded in the existing task checkpoint.

A report is an observation, not a verified finding. Its resolution is a
projection of fresh, canonically validated receipts, never an agent-set flag.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .verified_execution import _canonical

PROBLEM_STATE_KEY = "_verified_execution_problems"
PROBLEM_REPORT_KEY = "execution_problem_report"
PROBLEM_DISPOSITION_KEY = "execution_problem_disposition"
MAX_DISPOSITIONS = 16
MAX_PROBLEMS = 64


def _normalize_report(raw: Any, criteria: Sequence[str]) -> dict[str, Any]:
    if type(raw) is not dict or set(raw) - {"id", "title", "criterion", "blocking", "evidence_ids", "resolution_criterion", "require_distinct_owner"}:
        raise ValueError("invalid execution problem report")
    problem_id = _canonical(raw.get("id"), "problem id", 80)
    title = _canonical(raw.get("title"), "problem title", 240)
    criterion = raw.get("criterion", "")
    if type(criterion) is not str or (criterion and criterion not in criteria):
        raise ValueError("problem criterion must refer to a current acceptance criterion")
    blocking = raw.get("blocking", True)
    if type(blocking) is not bool or (blocking and not criterion):
        raise ValueError("blocking problems require an acceptance criterion")
    resolution = raw.get("resolution_criterion", "")
    if ("resolution_criterion" in raw and
            (type(resolution) is not str or not resolution or not criterion
             or resolution == criterion or resolution not in criteria)):
        raise ValueError("resolution criterion must be a distinct current acceptance criterion")
    distinct_owner = raw.get("require_distinct_owner", False)
    if type(distinct_owner) is not bool or (distinct_owner and not resolution):
        raise ValueError("distinct owner confirmation requires a resolution criterion")
    evidence_ids = raw.get("evidence_ids", [])
    if type(evidence_ids) is not list or len(evidence_ids) > 8:
        raise ValueError("problem evidence references must be a bounded list")
    for evidence_id in evidence_ids:
        _canonical(evidence_id, "reported evidence reference", 160)
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ValueError("duplicate problem evidence reference")
    return {
        "id": problem_id, "title": title, "criterion": criterion,
        "blocking": blocking, "evidence_ids": list(evidence_ids),
        **({"resolution_criterion": resolution} if resolution else {}),
        **({"require_distinct_owner": True} if distinct_owner else {}),
    }


def problem_confirmation_dependencies(raw: Any) -> dict[str, list[str]]:
    """Derive ordering edges from the immutable server-managed problem registry."""
    result: dict[str, list[str]] = {}
    for record in _validated_records(raw).values():
        report = record["report"]
        resolution = report.get("resolution_criterion")
        if resolution and report["blocking"]:
            predecessors = result.setdefault(resolution, [])
            if report["criterion"] not in predecessors:
                predecessors.append(report["criterion"])
    return {criterion: sorted(dependencies) for criterion, dependencies in sorted(result.items())}


def validate_resolution_order(
    report: Any, config: Mapping[str, Any], existing: Any = None,
) -> None:
    """Reject cycles across declared dependencies and problem confirmation edges."""
    if type(report) is not dict or "resolution_criterion" not in report:
        return
    primary = report.get("criterion")
    resolution = report["resolution_criterion"]
    if type(primary) is not str or type(resolution) is not str:
        raise ValueError("invalid resolution criterion")
    units = config.get("units", {})
    dependencies: dict[str, set[str]] = {
        name: set(metadata.get("depends_on", [])) for name, metadata in units.items()
    }
    for name, predecessors in problem_confirmation_dependencies(existing if existing is not None else {}).items():
        dependencies.setdefault(name, set()).update(predecessors)
    pending = [primary]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == resolution:
            raise ValueError("resolution criterion cannot be a prerequisite of the primary criterion")
        if current not in visited:
            visited.add(current)
            pending.extend(dependencies.get(current, set()))


def record_problem(
    existing: Any,
    report: Any,
    *,
    criteria: Sequence[str],
    receipt_ids: Mapping[str, str],
    reporter: str,
    now: float,
) -> dict[str, Any]:
    """Append a report; duplicate IDs are idempotent only for identical reports."""
    normalized = _normalize_report(report, criteria)
    records = _validated_records(existing)
    problem_id = normalized["id"]
    prior = records.get(problem_id)
    if prior is not None:
        if prior["report"] != normalized:
            raise ValueError("problem id already used for a different report")
        return records
    if len(records) >= MAX_PROBLEMS:
        raise ValueError("problem registry is full; split the work without discarding reports")
    records[problem_id] = {
        "report": normalized,
        "reported_at": float(now),
        "reporter": _canonical(reporter, "reporter", 200),
        "baseline_receipt_id": receipt_ids.get(normalized["criterion"], ""),
    }
    return records


def record_disposition(
    existing: Any, decision: Any, *, actor: str, now: float,
) -> dict[str, Any]:
    """Append a review decision without deleting reports or bypassing receipts."""
    records = _validated_records(existing)
    if type(decision) is not dict or set(decision) != {"id", "decision_id", "action", "reason"}:
        raise ValueError("invalid execution problem disposition")
    problem_id = _canonical(decision["id"], "problem id", 80)
    decision_id = _canonical(decision["decision_id"], "decision id", 80)
    action = decision["action"]
    if action not in ("defer", "reject", "resume"):
        raise ValueError("invalid execution problem disposition action")
    reason = _canonical(decision["reason"], "disposition reason", 1000)
    owner = _canonical(actor, "disposition owner", 200)
    record = records.get(problem_id)
    if record is None:
        raise ValueError("execution problem not found")
    if action == "reject" and owner == record["reporter"]:
        raise ValueError("rejecting a report requires a different authorized task owner")
    history = list(record.get("dispositions", []))
    for entry in history:
        if entry["decision_id"] == decision_id:
            if (entry["action"], entry["reason"], entry["actor"]) != (action, reason, owner):
                raise ValueError("disposition id already used for another decision")
            return records
    if len(history) >= MAX_DISPOSITIONS:
        raise ValueError("execution problem disposition history is full")
    history.append({"decision_id": decision_id, "action": action, "reason": reason,
                    "actor": owner, "observed_at": float(now)})
    records[problem_id] = {**record, "dispositions": history}
    return _validated_records(records)


def _validated_records(raw: Any) -> dict[str, Any]:
    if type(raw) is not dict or len(raw) > MAX_PROBLEMS:
        raise ValueError("invalid persisted execution problem registry")
    for problem_id, record in raw.items():
        if (type(record) is not dict or not {"report", "reported_at", "reporter", "baseline_receipt_id"}.issubset(record)
                or set(record) - {"report", "reported_at", "reporter", "baseline_receipt_id", "dispositions"}):
            raise ValueError("invalid persisted execution problem")
        report = record["report"]
        criterion = report.get("criterion", "") if type(report) is dict else ""
        resolution = report.get("resolution_criterion", "") if type(report) is dict else ""
        normalized = _normalize_report(report, tuple(c for c in (criterion, resolution) if c))
        if problem_id != normalized["id"] or report != normalized:
            raise ValueError("invalid persisted execution problem identity")
        observed = record["reported_at"]
        if type(observed) not in (int, float) or not math.isfinite(observed) or observed < 0:
            raise ValueError("invalid persisted problem time")
        _canonical(record["reporter"], "reporter", 200)
        baseline = record["baseline_receipt_id"]
        if type(baseline) is not str or "\x00" in baseline:
            raise ValueError("invalid persisted problem baseline")
        history = record.get("dispositions", [])
        if type(history) is not list or len(history) > MAX_DISPOSITIONS:
            raise ValueError("invalid persisted problem disposition history")
        ids: set[str] = set()
        last_time = observed
        for entry in history:
            if type(entry) is not dict or set(entry) != {"decision_id", "action", "reason", "actor", "observed_at"}:
                raise ValueError("invalid persisted problem disposition")
            decision_id = _canonical(entry["decision_id"], "decision id", 80)
            _canonical(entry["reason"], "disposition reason", 1000)
            actor = _canonical(entry["actor"], "disposition owner", 200)
            timestamp = entry["observed_at"]
            if (decision_id in ids or entry["action"] not in ("defer", "reject", "resume")
                    or (entry["action"] == "reject" and actor == record["reporter"])
                    or type(timestamp) not in (int, float) or not math.isfinite(timestamp)
                    or timestamp < last_time):
                raise ValueError("invalid persisted problem disposition sequence")
            ids.add(decision_id)
            last_time = timestamp
    return dict(raw)


def project_problems(
    raw: Any,
    *,
    satisfied: Sequence[str],
    receipts: Mapping[str, Any],
    current_owner: str = "",
) -> dict[str, Any]:
    """Resolve only via a new, fresh receipt and optional separate confirmation.

    A later stale or failed receipt reopens the report automatically. Reported
    evidence references are unverified leads; they never satisfy the gate.
    """
    records = _validated_records(raw)
    valid = set(satisfied)
    open_count = blocking = resolved = 0
    deferred = rejected = pending_rejection = 0
    disposition_preview: list[dict[str, Any]] = []
    blocking_criteria: set[str] = set()
    handoff_criteria: set[str] = set()
    preview: list[dict[str, Any]] = []
    for record in records.values():
        report = record["report"]
        criterion = report["criterion"]
        receipt = receipts.get(criterion) if criterion in valid else None
        receipt_id = getattr(receipt, "receipt_id", "")
        observation = getattr(receipt, "observed_at", 0.0)
        primary_closed = bool(
            receipt is not None and receipt_id
            and receipt_id != record["baseline_receipt_id"]
            and observation >= record["reported_at"]
        )
        resolution = report.get("resolution_criterion", "")
        confirmation = receipts.get(resolution) if resolution in valid else None
        confirmation_id = getattr(confirmation, "receipt_id", "")
        primary_evidence = getattr(receipt, "evidence_id", "")
        confirmation_evidence = getattr(confirmation, "evidence_id", "")
        confirmed = not resolution or bool(
            confirmation is not None and confirmation_id and confirmation_id != receipt_id
            and primary_evidence and confirmation_evidence and confirmation_evidence != primary_evidence
            and getattr(confirmation, "observed_at", 0.0) >= max(observation, record["reported_at"])
        )
        distinct_owner = report.get("require_distinct_owner", False)
        repair_owner = getattr(receipt, "owner", "")
        review_owner = getattr(confirmation, "owner", "")
        owner_confirmed = not distinct_owner or bool(
            repair_owner and review_owner and review_owner != repair_owner
        )
        closed = primary_closed and confirmed and owner_confirmed
        needs_handoff = bool(primary_closed and distinct_owner and not closed
                             and current_owner and current_owner == repair_owner)
        history = record.get("dispositions", [])
        decision = history[-1] if history else None
        disposition = decision["action"] if decision else "resume"
        if disposition == "defer" and not closed:
            deferred += 1
        rejection_proof = confirmation if resolution else receipt
        rejection_verified = bool(
            decision and disposition == "reject" and closed
            and getattr(rejection_proof, "owner", "") == decision["actor"]
            and getattr(rejection_proof, "observed_at", 0.0) >= decision["observed_at"]
        )
        if disposition == "reject":
            if rejection_verified:
                rejected += 1
            else:
                pending_rejection += 1
        if decision and len(disposition_preview) < 12:
            disposition_preview.append({"id": report["id"], **decision,
                                        "verified": rejection_verified})
        if closed:
            resolved += 1
        else:
            open_count += 1
            blocking += int(report["blocking"])
            if report["blocking"]:
                # Do not block a freshly verified primary while waiting for its
                # confirmation, which may itself depend on the primary.
                blocking_criteria.add(criterion if not primary_closed else resolution)
                if needs_handoff:
                    handoff_criteria.add(resolution)
            if len(preview) < 12:
                preview.append({"id": report["id"], "title": report["title"],
                                "criterion": criterion, "blocking": report["blocking"],
                                **({"disposition": disposition} if decision else {}),
                                **({"resolution_criterion": resolution,
                                    "resolution_status": ("awaiting_primary" if not primary_closed else
                                                          "awaiting_distinct_owner" if needs_handoff or (confirmed and not owner_confirmed) else
                                                          "awaiting_confirmation")}
                                   if resolution else {}),
                                **({"require_distinct_owner": True} if distinct_owner else {})})
    return {
        "total": len(records), "open": open_count, "resolved": resolved,
        "blocking_open": blocking, "blocking_criteria": sorted(blocking_criteria),
        **({"owner_handoff_criteria": sorted(handoff_criteria)} if handoff_criteria else {}),
        "open_preview": preview,
        "preview_truncated": open_count > len(preview),
        **({"deferred_open": deferred, "rejected_verified": rejected,
            "rejection_pending_evidence": pending_rejection,
            "dispositions_preview": disposition_preview} if disposition_preview else {}),
    }
