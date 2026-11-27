"""Evaluate paired provider-usage and independently adjudicated Git review runs.

No model calls, source reads or network access. Inputs must come from real,
approved provider usage exports and a human-adjudicated finding manifest.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_ID = re.compile(r"[A-Za-z0-9_.:/@-]{1,160}")
_HEX = re.compile(r"[a-f0-9]{64}")
_MAX_BYTES = 1024 * 1024


def _ids(value: Any) -> set[str]:
    if (not isinstance(value, list) or len(value) > 256
            or any(not isinstance(item, str) or not _ID.fullmatch(item) for item in value)
            or len(set(value)) != len(value)):
        raise ValueError("Invalid or duplicate adjudicated finding IDs")
    return set(value)


def _run(value: Any, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "input_tokens", "output_tokens", "cached_input_tokens", "calls",
        "finding_ids", "completed", "usage_source",
    }:
        raise ValueError("Each run requires complete provider usage and adjudicated findings")
    if value["usage_source"] != "provider_reported" or type(value["completed"]) is not bool:
        raise ValueError("Provider-reported usage and explicit completion are required")
    for key in ("input_tokens", "output_tokens", "cached_input_tokens", "calls"):
        if type(value[key]) is not int or not 0 <= value[key] <= 100_000_000:
            raise ValueError("Invalid provider usage count")
    if not value["calls"] or value["cached_input_tokens"] > value["input_tokens"]:
        raise ValueError("Missing calls or inconsistent cached token count")
    found = _ids(value["finding_ids"])
    return {
        **{key: value[key] for key in ("input_tokens", "output_tokens", "cached_input_tokens", "calls", "completed")},
        "true_positive": len(found & expected), "false_positive": len(found - expected),
        "false_negative": len(expected - found),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def evaluate(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or set(document) != {"schema", "cases"} or document["schema"] != 1:
        raise ValueError("Expected paired evaluation schema 1")
    cases = document["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= 128:
        raise ValueError("Provide 1–128 paired cases")
    seen = set()
    paired = []
    totals = {name: {key: 0 for key in (
        "input_tokens", "output_tokens", "cached_input_tokens", "calls",
        "true_positive", "false_positive", "false_negative", "completed_cases",
    )} for name in ("raw", "compact")}
    for case in cases:
        if not isinstance(case, dict) or set(case) != {
            "case_id", "task_digest", "revision", "provider_model", "expected_finding_ids", "raw", "compact",
        }:
            raise ValueError("Every paired case requires a shared task, revision, model and adjudication")
        case_id, task, revision, model = (case[k] for k in ("case_id", "task_digest", "revision", "provider_model"))
        if (not isinstance(case_id, str) or not _ID.fullmatch(case_id) or case_id in seen
                or not isinstance(task, str) or not _HEX.fullmatch(task)
                or not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", revision)
                or not isinstance(model, str) or not _ID.fullmatch(model)):
            raise ValueError("Invalid or duplicate evaluation identity")
        seen.add(case_id)
        expected = _ids(case["expected_finding_ids"])
        runs = {name: _run(case[name], expected) for name in ("raw", "compact")}
        for name, run in runs.items():
            for key, amount in run.items():
                if key == "completed":
                    totals[name]["completed_cases"] += int(amount)
                else:
                    totals[name][key] += amount
        paired.append({
            "case_id": case_id, "provider_model": model,
            "input_token_difference": runs["raw"]["input_tokens"] - runs["compact"]["input_tokens"],
            "output_token_difference": runs["raw"]["output_tokens"] - runs["compact"]["output_tokens"],
            "compact_additional_missed_findings": runs["compact"]["false_negative"] - runs["raw"]["false_negative"],
            "raw_completed": runs["raw"]["completed"], "compact_completed": runs["compact"]["completed"],
        })
    scores = {}
    for name, total in totals.items():
        tp, fp, fn = (total[k] for k in ("true_positive", "false_positive", "false_negative"))
        scores[name] = {**total, "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn)}
    raw, compact = scores["raw"], scores["compact"]
    return {
        "case_count": len(cases), "aggregate": scores, "pairs": paired,
        "input_token_difference": raw["input_tokens"] - compact["input_tokens"],
        "output_token_difference": raw["output_tokens"] - compact["output_tokens"],
        "uncached_input_token_difference": (
            raw["input_tokens"] - raw["cached_input_tokens"]
            - compact["input_tokens"] + compact["cached_input_tokens"]
        ),
        "all_pairs_completed": all(p["raw_completed"] and p["compact_completed"] for p in paired),
        "compact_no_additional_missed_findings_per_case": all(
            p["compact_additional_missed_findings"] <= 0 for p in paired
        ),
        "usage_provenance": "caller_supplied_provider_reported_counters_not_independently_authenticated",
        "limitations": "No billing or statistical significance claim. Include every request, schema, retry and detail follow-up in the provider usage totals. Finding IDs require independent adjudication; this evaluator cannot verify it.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    try:
        with args.results.open("rb") as stream:
            raw = stream.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise ValueError("Evaluation file exceeds byte budget")
        report = evaluate(json.loads(raw))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
