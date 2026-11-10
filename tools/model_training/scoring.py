from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import Draft202012Validator


def parse_json_output(text: str) -> Any | None:
    candidate = text.strip()
    candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE)
    try:
        value, _ = json.JSONDecoder().raw_decode(candidate)
        return value
    except json.JSONDecodeError:
        start = candidate.find("{")
        if start < 0:
            return None
        try:
            value, _ = json.JSONDecoder().raw_decode(candidate[start:])
            return value
        except json.JSONDecodeError:
            return None


def _field_value(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _normal(value: Any) -> str:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    return re.sub(r"\s+", " ", str(value)).casefold().strip()


def score_prediction(text: str, row: dict[str, Any], output_schema: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_json_output(text)
    schema_pass = parsed is not None and not list(Draft202012Validator(output_schema).iter_errors(parsed))
    expected_present = "expected" in row
    expected = row.get("expected")
    exact_match = (parsed == expected) if expected_present else None
    required_facts = row.get("required_facts", [])
    if not isinstance(required_facts, list):
        raise ValueError("required_facts must be a list")
    hits = 0
    for fact in required_facts:
        if not isinstance(fact, dict) or not isinstance(fact.get("field"), str) or "value" not in fact:
            raise ValueError("each required fact needs field and value")
        actual = _field_value(parsed, fact["field"]) if parsed is not None else None
        hits += int(_normal(fact["value"]) in _normal(actual))
    forbidden = row.get("forbidden_claims", [])
    if not isinstance(forbidden, list) or any(not isinstance(item, str) for item in forbidden):
        raise ValueError("forbidden_claims must be a list of strings")
    folded_text = text.casefold()
    forbidden_hits = [item for item in forbidden if item.casefold() in folded_text]
    return {
        "schema_pass": bool(schema_pass),
        "exact_match": exact_match,
        "required_fact_hits": hits,
        "required_fact_total": len(required_facts),
        "required_fact_recall": hits / len(required_facts) if required_facts else None,
        "forbidden_claim_hits": forbidden_hits,
        "forbidden_claim_count": len(forbidden_hits),
    }
