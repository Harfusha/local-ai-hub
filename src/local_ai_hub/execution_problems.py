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
MAX_PROBLEMS = 64


def _normalize_report(raw: Any, criteria: Sequence[str]) -> dict[str, Any]:
    if type(raw) is not dict or set(raw) - {"id", "title", "criterion", "blocking", "evidence_ids", "resolution_criterion"}:
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
    }


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


def _validated_records(raw: Any) -> dict[str, Any]:
    if type(raw) is not dict or len(raw) > MAX_PROBLEMS:
        raise ValueError("invalid persisted execution problem registry")
    for problem_id, record in raw.items():
        if type(record) is not dict or set(record) != {"report", "reported_at", "reporter", "baseline_receipt_id"}:
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
    return dict(raw)


def project_problems(
    raw: Any,
    *,
    satisfied: Sequence[str],
    receipts: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve only via a new, fresh receipt for the linked criterion.

    A later stale or failed receipt reopens the report automatically. Reported
    evidence references are unverified leads; they never satisfy the gate.
    """
    records = _validated_records(raw)
    valid = set(satisfied)
    open_count = blocking = resolved = 0
    blocking_criteria: set[str] = set()
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
        closed = primary_closed and confirmed
        if closed:
            resolved += 1
        else:
            open_count += 1
            blocking += int(report["blocking"])
            if report["blocking"]:
                # Do not block a freshly verified primary while waiting for its
                # confirmation, which may itself depend on the primary.
                blocking_criteria.add(criterion if not primary_closed else resolution)
            if len(preview) < 12:
                preview.append({"id": report["id"], "title": report["title"],
                                "criterion": criterion, "blocking": report["blocking"],
                                **({"resolution_criterion": resolution,
                                    "resolution_status": "awaiting_confirmation" if primary_closed else "awaiting_primary"}
                                   if resolution else {})})
    return {
        "total": len(records), "open": open_count, "resolved": resolved,
        "blocking_open": blocking, "blocking_criteria": sorted(blocking_criteria),
        "open_preview": preview,
        "preview_truncated": open_count > len(preview),
    }
