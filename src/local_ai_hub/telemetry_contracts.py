"""Canonical persisted telemetry field contracts shared by runtime and updater."""

import json


def _object_from_unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate telemetry JSON key: {key}")
        result[key] = value
    return result


def load_telemetry_json(raw: str) -> object:
    """Parse persisted telemetry JSON without silently collapsing duplicate keys."""
    return json.loads(raw, object_pairs_hook=_object_from_unique_pairs)

_LAYA_DECISION_FIELDS = frozenset({
    "decision_id", "success", "mode", "status", "category", "repository_id", "task_id",
    "session_id", "provider_label", "suggestion", "reason_codes", "evidence_ids", "model_estimate",
    "uncertainty", "execution_verification", "runtime_latency_ms", "inference_latency_ms",
    "queue_wait_ms", "backend", "fallback_used", "fallback_reason",
})

_LAYA_ELIGIBILITY_FIELDS = frozenset({"decision_id", "mode", "category", "provider_label"})

_LAYA_DECISION_RUNTIME_FIELDS = frozenset({
    "runtime_latency_ms", "inference_latency_ms", "queue_wait_ms", "backend",
    "fallback_used", "fallback_reason",
})

_LAYA_DECISION_PRE_RUNTIME_FIELDS = _LAYA_DECISION_FIELDS - _LAYA_DECISION_RUNTIME_FIELDS
