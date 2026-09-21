"""Deterministic quality scoring and in-memory model candidate registry."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any


CANDIDATE = "candidate"
CHAMPION = "champion"
REJECTED = "rejected"

DEFAULT_QUALITY_FLOOR = {
    "grounded_rate": 0.90,
    "schema_pass_rate": 0.95,
    "abstention_accuracy": 0.90,
    "hallucinated_path_rate": 0.0,
    "false_positive_rate": 0.05,
}

_CONTROL_KEYS = {"abstain", "should_abstain", "valid", "is_valid"}
_ABSTENTION_LABELS = {"abstain", "abstained", "unknown", "insufficient_evidence"}
_PATH_KEYS = {
    "file",
    "files",
    "path",
    "paths",
    "reference",
    "references",
    "source",
    "sources",
    "evidence_path",
    "evidence_paths",
    "referenced_path",
    "referenced_paths",
}
_PATH_TOKEN = re.compile(r"(?<![\w.-])(?:[A-Za-z]:[\\/])?[\w.-]+(?:[\\/][\w .-]+)+")


def _normalise_path(path: str) -> str:
    value = path.strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value.casefold()


def _looks_like_path(value: str) -> bool:
    return bool(_PATH_TOKEN.search(value)) or "." in value.rsplit("/", 1)[-1]


def _extract_paths(value: Any, key_hint: str | None = None) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_name = str(key).casefold()
            found.extend(_extract_paths(item, key_name))
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            found.extend(_extract_paths(item, key_hint))
    elif isinstance(value, str):
        if key_hint in _PATH_KEYS:
            if value.strip():
                found.append(value.strip())
        else:
            found.extend(match.group(0) for match in _PATH_TOKEN.finditer(value))
    return found


def _is_abstention(value: Mapping[str, Any]) -> bool:
    if bool(value.get("abstain", value.get("abstained", False))):
        return True
    label = value.get("label", value.get("status"))
    return isinstance(label, str) and label.casefold() in _ABSTENTION_LABELS


def _expected_matches(output: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    for key, expected_value in expected.items():
        if str(key).casefold() in _CONTROL_KEYS:
            continue
        if key not in output or output[key] != expected_value:
            return False
    return True


def _schema_pass(output: Any, expected: Mapping[str, Any]) -> bool:
    if not isinstance(output, Mapping):
        return False
    for key, expected_value in expected.items():
        if str(key).casefold() in _CONTROL_KEYS:
            continue
        if key not in output:
            return False
        actual_value = output[key]
        if expected_value is not None and not isinstance(actual_value, type(expected_value)):
            return False
    return True


def _actual_positive(output: Mapping[str, Any]) -> bool:
    for key in ("valid", "is_valid", "positive", "is_positive"):
        if key in output:
            return bool(output[key])
    label = output.get("label", output.get("status"))
    return not (isinstance(label, str) and label.casefold() in _ABSTENTION_LABELS | {"invalid", "none"})


def evaluate_case(
    task: str,
    evidence_paths: Iterable[str],
    output: Any,
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    """Score one synthetic case without using model self-ratings or text heuristics."""
    del task  # Task identity is caller metadata; scoring uses structured values only.
    expected_map = expected if isinstance(expected, Mapping) else {}
    output_map = output if isinstance(output, Mapping) else {}
    evidence = {_normalise_path(path) for path in evidence_paths}
    hallucinated = sorted(
        {_normalise_path(path) for path in _extract_paths(output) if _normalise_path(path) not in evidence}
    )
    expected_abstention = bool(
        expected_map.get("abstain", expected_map.get("should_abstain", False))
    )
    actual_abstention = _is_abstention(output_map)
    abstention_correct = actual_abstention == expected_abstention
    schema_pass = _schema_pass(output, expected_map)
    grounded = schema_pass and _expected_matches(output_map, expected_map) and not hallucinated
    expected_valid = expected_map.get("valid", expected_map.get("is_valid"))
    false_positive = (
        isinstance(expected_valid, bool) and not expected_valid and _actual_positive(output_map)
    )
    return {
        "grounded": grounded,
        "grounded_relevance": 1.0 if grounded else 0.0,
        "schema_pass": schema_pass,
        "abstention": actual_abstention,
        "abstention_correct": abstention_correct,
        "hallucinated_paths": hallucinated,
        "false_positive": false_positive,
    }


def _rate(results: list[Mapping[str, Any]], key: str) -> float:
    return sum(bool(result.get(key, False)) for result in results) / len(results) if results else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, round((percentile / 100) * (len(values) - 1))))
    return values[index]


def aggregate_metrics(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate case receipts into stable rates and optional resource metrics."""
    rows = list(results)
    metrics: dict[str, Any] = {
        "case_count": len(rows),
        "grounded_rate": _rate(rows, "grounded"),
        "schema_pass_rate": _rate(rows, "schema_pass"),
        "abstention_accuracy": _rate(rows, "abstention_correct"),
        "hallucinated_path_rate": sum(bool(row.get("hallucinated_paths")) for row in rows) / len(rows)
        if rows
        else 0.0,
        "false_positive_rate": _rate(rows, "false_positive"),
    }
    latencies = [float(row["latency_ms"]) for row in rows if "latency_ms" in row]
    if latencies:
        metrics.update(p50_latency_ms=_percentile(latencies, 50), p95_latency_ms=_percentile(latencies, 95))
    timeouts = [row for row in rows if "timeout" in row]
    if timeouts:
        metrics["timeout_rate"] = _rate(timeouts, "timeout")
    for source_key, metric_key in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens")):
        values = [float(row[source_key]) for row in rows if source_key in row]
        if values:
            metrics[metric_key] = sum(values) / len(values)
    return metrics


def quality_floor_failures(
    metrics: Mapping[str, Any], quality_floor: Mapping[str, float] | None = None
) -> list[str]:
    floor = quality_floor or DEFAULT_QUALITY_FLOOR
    failures: list[str] = []
    for key, threshold in floor.items():
        value = metrics.get(key)
        if value is None:
            failures.append(key)
        elif key.endswith("_rate") and key in {"hallucinated_path_rate", "false_positive_rate"}:
            if float(value) > threshold:
                failures.append(key)
        elif float(value) < threshold:
            failures.append(key)
    return failures


def _receipt_id(receipt: Mapping[str, Any]) -> str | None:
    value = receipt.get("receipt_id", receipt.get("id"))
    return str(value) if value else None


def _reproducible_receipt(receipt: Any) -> bool:
    if not isinstance(receipt, Mapping) or not _receipt_id(receipt):
        return False
    return bool(
        receipt.get("reproducible")
        or receipt.get("evaluation_hash")
        or receipt.get("case_ids")
        or receipt.get("suite_version")
    )


def promote_candidate(
    candidate: Mapping[str, Any],
    receipt: Mapping[str, Any] | None = None,
    quality_floor: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Return a promotion decision; quality floor is checked before receipt gate."""
    payload = dict(candidate)
    metrics = payload.get("metrics", payload)
    failures = quality_floor_failures(metrics, quality_floor)
    if failures:
        return {
            "status": REJECTED,
            "reason": "quality_floor_not_met",
            "failed_metrics": failures,
            "metrics": dict(metrics),
        }
    receipt = receipt or payload.get("receipt")
    if not _reproducible_receipt(receipt):
        return {
            "status": REJECTED,
            "reason": "evaluation_receipt_required",
            "metrics": dict(metrics),
        }
    result = {"status": CHAMPION, "metrics": dict(metrics), "receipt_id": _receipt_id(receipt)}
    if payload.get("candidate_id", payload.get("id")) is not None:
        result["candidate_id"] = payload.get("candidate_id", payload.get("id"))
    return result


class CandidateRegistry:
    """Small process-local registry for candidate lifecycle decisions."""

    def __init__(self, quality_floor: Mapping[str, float] | None = None) -> None:
        self.quality_floor = dict(quality_floor or DEFAULT_QUALITY_FLOOR)
        self._candidates: dict[str, dict[str, Any]] = {}

    def register_candidate(
        self,
        candidate_id: str,
        metrics: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if candidate_id in self._candidates:
            raise ValueError(f"candidate already registered: {candidate_id}")
        record = {
            "candidate_id": candidate_id,
            "status": CANDIDATE,
            "metrics": dict(metrics or {}),
            "metadata": dict(metadata or {}),
        }
        self._candidates[candidate_id] = record
        return deepcopy(record)

    def promote_candidate(
        self,
        candidate_id: str,
        metrics: Mapping[str, Any] | None = None,
        receipt: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = self._candidates.get(candidate_id)
        if record is None:
            return {"status": REJECTED, "reason": "candidate_not_found", "candidate_id": candidate_id}
        if metrics is not None:
            record["metrics"] = dict(metrics)
        decision = promote_candidate(record, receipt=receipt, quality_floor=self.quality_floor)
        record.update(decision)
        return deepcopy(record)

    def get(self, candidate_id: str) -> dict[str, Any] | None:
        record = self._candidates.get(candidate_id)
        return deepcopy(record) if record is not None else None
