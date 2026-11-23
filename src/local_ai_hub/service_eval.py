"""Evaluation suite, dynamic prompt evaluation, and regression drift tracking service."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any

from .json_utils import dumps as json_dumps
from .budget import estimate_tokens
from . import process_utils
from .state_paths import configured_state_dir
from .repository_scope import reject_retired_tenancy_fields
from .scheduler import SchedulerTimeoutError


def eval_suite(services: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Run bounded local agent benchmark evaluation test cases."""
    reject_retired_tenancy_fields(payload)
    suite_name = str(payload.get("suite_name", "default"))
    requested_model = str(
        payload.get("model")
        or getattr(services, "config", {}).get("models", {}).get("fast_code", "qwen2.5-coder:3b")
    )
    benchmark_kind = str(payload.get("benchmark_kind", "text") or "text").strip().lower()
    raw_cases = payload.get("cases")
    if raw_cases is None:
        cases = [
            {"id": "c1", "input": "def add(a, b):", "expected": "return a + b"},
            {"id": "c2", "input": "def is_even(n):", "expected": "return n % 2 == 0"},
        ]
    elif (
        not isinstance(raw_cases, list)
        or not 1 <= len(raw_cases) <= 32
        or any(not isinstance(item, dict) for item in raw_cases)
    ):
        return {
            "success": False,
            "status_code": 400,
            "terminal": True,
            "retryable": False,
            "error_code": "invalid_eval_suite_cases",
            "message": "cases must contain 1 to 32 objects; omit cases to use the built-in suite",
        }
    else:
        cases = raw_cases
    for case in cases:
        supported_case_fields = {
            "id",
            "input",
            "expected",
            "max_words",
            "allowed_citations",
            "required_citations",
            "forbidden_phrases",
            "include_response_text",
        }
        unknown_fields = set(case) - supported_case_fields
        if unknown_fields:
            return {
                "success": False,
                "status_code": 400,
                "terminal": True,
                "retryable": False,
                "error_code": "invalid_eval_case_rubric",
                "message": f"unsupported eval case fields: {', '.join(sorted(str(item) for item in unknown_fields))}",
            }
        max_words = case.get("max_words")
        if "max_words" in case and (type(max_words) is not int or not 1 <= max_words <= 1000):
            return {
                "success": False,
                "status_code": 400,
                "terminal": True,
                "retryable": False,
                "error_code": "invalid_eval_case_rubric",
                "message": "max_words must be an integer from 1 to 1000",
            }
        if "include_response_text" in case and type(case["include_response_text"]) is not bool:
            return {
                "success": False,
                "status_code": 400,
                "terminal": True,
                "retryable": False,
                "error_code": "invalid_eval_case_rubric",
                "message": "include_response_text must be a boolean",
            }
        rubric_lists: dict[str, list[str]] = {}
        for field in ("allowed_citations", "required_citations", "forbidden_phrases"):
            if field not in case:
                continue
            value = case[field]
            if (
                not isinstance(value, list)
                or not 1 <= len(value) <= 32
                or any(not isinstance(item, str) or not item.strip() or len(item) > 512 for item in value)
            ):
                return {
                    "success": False,
                    "status_code": 400,
                    "terminal": True,
                    "retryable": False,
                    "error_code": "invalid_eval_case_rubric",
                    "message": f"{field} must contain 1 to 32 nonempty strings of at most 512 characters",
                }
            rubric_lists[field] = value
        citation_pattern = re.compile(r"\[[^\[\]\r\n]+:\d+-\d+\]")
        allowed = rubric_lists.get("allowed_citations")
        for field in ("allowed_citations", "required_citations"):
            for citation in rubric_lists.get(field, []):
                if citation_pattern.fullmatch(citation) is None:
                    return {
                        "success": False,
                        "status_code": 400,
                        "terminal": True,
                        "retryable": False,
                        "error_code": "invalid_eval_case_rubric",
                        "message": f"{field} entries must use [path:start-end] form",
                    }
        if "required_citations" in rubric_lists and (
            allowed is None or any(item not in allowed for item in rubric_lists["required_citations"])
        ):
            return {
                "success": False,
                "status_code": 400,
                "terminal": True,
                "retryable": False,
                "error_code": "invalid_eval_case_rubric",
                "message": "required_citations must be included in allowed_citations",
            }
    configured_roles = tuple(
        str(role)
        for role, model in (getattr(services, "config", {}).get("models", {}) or {}).items()
        if str(model or "") == requested_model
        and str(role) not in {
            "embedding",
            "embedding_backend",
            "embedding_device",
            "reranker",
            "reranker_backend",
            "reranker_device",
        }
    )
    vision_only = bool(configured_roles) and all(role == "vision" for role in configured_roles)
    if vision_only and benchmark_kind != "vision":
        mismatch_cases = []
        for case in cases:
            case_id = str(case.get("id", "case"))
            mismatch_cases.append({
                "case_id": case_id,
                "model": requested_model,
                "status": "role_mismatch",
                "passed": False,
                "error": f"model is configured only for vision role: {', '.join(configured_roles)}",
                "response_chars": 0,
                "response_tokens_est": 0,
                "response_sha256": hashlib.sha256(b"").hexdigest(),
                "response_preview": "",
                "response_preview_truncated": False,
                "duration_ms": 0.0,
            })
        return {
            "success": True,
            "suite": suite_name,
            "model": requested_model,
            "model_roles": list(configured_roles),
            "benchmark_kind": benchmark_kind,
            "summary": {
                "total": len(cases),
                "passed": 0,
                "failed": len(cases),
                "pass_rate": 0.0,
                "execution_failures": 0,
                "benchmark_valid": False,
                "role_mismatch": True,
            },
            "cases": mismatch_cases,
        }
    results = []
    passed = 0
    execution_failures = 0
    model_digest = None
    digest_reader = getattr(getattr(services, "runtime", None), "model_digest", None)
    if callable(digest_reader):
        try:
            candidate_digest = digest_reader(requested_model)
            if isinstance(candidate_digest, str) and re.fullmatch(r"[0-9a-f]{64}", candidate_digest):
                model_digest = candidate_digest
        except Exception:
            model_digest = None
    for case in cases:
        c_id = str(case.get("id", "case"))
        c_in = str(case.get("input", ""))
        c_exp = str(case.get("expected", ""))
        started = time.perf_counter()
        try:
            request_payload = {
                "model": requested_model,
                "prompt": c_in,
                "system": "Return the shortest correct answer containing the requested completion. Output only the answer; no greeting, explanation, or generic advice.",
                "stream": False,
                "think": False,
                "options": {"num_predict": 128, "temperature": 0.0},
            }

            def execute_case() -> dict[str, Any]:
                return services.runtime.request("/api/generate", request_payload)

            scheduler = getattr(services, "scheduler", None)
            scheduler_submit = getattr(scheduler, "submit", None)
            if callable(scheduler_submit):
                response = scheduler_submit(
                    requested_model, source="eval_suite", execute=execute_case, priority=2,
                )
            else:
                llama_config = getattr(services, "config", {}).get("llama_cpp", {})
                if isinstance(llama_config, dict) and llama_config.get("managed_with_ollama") is True:
                    response = {
                        "error": "Scheduler required for managed mixed model evaluation; preparation unavailable",
                        "error_code": "scheduler_required",
                    }
                else:
                    response = execute_case()
            response = response if isinstance(response, dict) else {"error": "runtime returned a non-object response"}
            error = str(response.get("error", "") or "")
            response_text = str(response.get("response", response.get("text", "")) or "")
            message = response.get("message")
            if not response_text and isinstance(message, dict):
                response_text = str(message.get("content", "") or "")
            is_pass = bool(c_exp and not error and c_exp in response_text)
            if error:
                execution_failures += 1
                lowered = error.lower()
                status = "unavailable" if any(marker in lowered for marker in ("404", "not found", "unavailable", "no route")) else "error"
            else:
                status = "passed" if is_pass else "failed"
            lowered_text = response_text.casefold()
            generic_markers = ("certainly!", "below is", "here is", "this function", "hope this helps")
            generic_filler = any(marker in lowered_text for marker in generic_markers)
            response_words = len(response_text.split())
            max_words = case.get("max_words")
            concise = response_words <= max_words if type(max_words) is int else len(response_text.strip()) <= max(240, len(c_exp) * 6)
            style_quality = {
                "contains_expected": is_pass,
                "exact_expected": response_text.strip() == c_exp.strip(),
                "generic_filler": generic_filler,
                "concise": concise,
            }
            allowed_citations = case.get("allowed_citations")
            required_citations = case.get("required_citations")
            forbidden_phrases = case.get("forbidden_phrases")
            quality_checks = [is_pass, not generic_filler, concise]
            if isinstance(allowed_citations, list):
                found_citations = re.findall(r"\[[^\[\]\r\n]+:\d+-\d+\]", response_text)
                bracketed_items = re.findall(r"\[[^\[\]\r\n]*\]", response_text)
                citation_precision = (
                    bool(found_citations) and len(found_citations) == len(bracketed_items)
                    and all(item in allowed_citations for item in found_citations)
                )
                style_quality["citation_precision"] = citation_precision
                quality_checks.append(citation_precision)
            if isinstance(required_citations, list):
                required_present = all(item in response_text for item in required_citations)
                style_quality["required_citations_present"] = required_present
                quality_checks.append(required_present)
            if isinstance(forbidden_phrases, list):
                forbidden_absent = not any(item.casefold() in lowered_text for item in forbidden_phrases)
                style_quality["forbidden_phrases_absent"] = forbidden_absent
                quality_checks.append(forbidden_absent)
            style_quality["quality_pass"] = bool(all(quality_checks))
            result = {
                "case_id": c_id,
                "model": requested_model,
                "model_digest": model_digest,
                "model_digest_status": "verified_installed" if model_digest else "unavailable",
                "passed": is_pass,
                "status": status,
                "response_chars": len(response_text),
                "response_words": response_words,
                "response_tokens_est": estimate_tokens(response_text),
                "response_sha256": hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
                "response_preview": response_text[:240],
                "response_preview_truncated": len(response_text) > 240,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "style_quality": style_quality,
            }
            if case.get("include_response_text") is True:
                result["response_text"] = response_text[:4096]
                result["response_text_truncated"] = len(response_text) > 4096
            if error:
                result["error"] = error
            for key in (
                "error_code", "job_id", "scheduler_state", "timed_out", "outcome_unknown",
                "wait_reason", "request_not_sent", "operation_not_started", "in_progress", "retryable", "terminal",
            ):
                value = response.get(key)
                if key in {
                    "timed_out", "outcome_unknown", "request_not_sent", "operation_not_started",
                    "in_progress", "retryable", "terminal",
                } and type(value) is not bool:
                    continue
                if key in {"error_code", "scheduler_state", "wait_reason"} and not isinstance(value, str):
                    continue
                if key == "job_id" and not (
                    isinstance(value, str) and value
                ) and not (
                    isinstance(value, int) and not isinstance(value, bool) and value >= 0
                ):
                    continue
                if key in response:
                    result[key] = value
        except Exception as exc:
            is_pass = False
            execution_failures += 1
            result = {
                "case_id": c_id,
                "model": requested_model,
                "passed": False,
                "status": "error",
                "error": str(exc),
                "response_chars": 0,
                "response_tokens_est": 0,
                "response_sha256": hashlib.sha256(b"").hexdigest(),
                "response_preview": "",
                "response_preview_truncated": False,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }
            if isinstance(exc, TimeoutError):
                result["timed_out"] = True
                if isinstance(exc, SchedulerTimeoutError):
                    result["job_id"] = exc.job_id
                    result["scheduler_state"] = exc.state
                    if isinstance(exc.wait_reason, str):
                        result["wait_reason"] = exc.wait_reason
                    if exc.state == "pending":
                        result.update(request_not_sent=True, operation_not_started=True)
                    else:
                        result.update(outcome_unknown=True, retryable=False)
                else:
                    result.update(outcome_unknown=True, retryable=False)
        results.append(result)
        if is_pass:
            passed += 1

    quality_passed = sum(
        1 for item in results
        if isinstance(item, dict) and bool((item.get("style_quality") or {}).get("quality_pass"))
    )
    return {
        "success": True,
        "suite": suite_name,
        "model": requested_model,
        "model_roles": list(configured_roles),
        "benchmark_kind": benchmark_kind,
        "summary": {
            "total": len(cases),
            "passed": passed,
            "failed": len(cases) - passed,
            "pass_rate": round(passed / max(1, len(cases)), 2),
            "execution_failures": execution_failures,
            "benchmark_valid": True,
            "role_mismatch": False,
            "quality_passed": quality_passed,
            "quality_pass_rate": round(quality_passed / max(1, len(cases)), 2),
        },
        "cases": results,
    }


def prompt_eval(services: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate and render dynamic prompt templates with variable substitution and token estimation."""
    reject_retired_tenancy_fields(payload)
    template = str(payload.get("template", ""))
    variables = payload.get("variables", {}) if isinstance(payload.get("variables"), dict) else {}
    rendered = template
    for k, v in variables.items():
        rendered = rendered.replace(f"{{{{{k}}}}}", str(v))
        rendered = rendered.replace(f"{{{k}}}", str(v))

    token_est = estimate_tokens(rendered)
    return {
        "success": True,
        "template": template,
        "rendered_prompt": rendered,
        "token_estimate": token_est,
        "variables_applied": list(variables.keys()),
    }


def eval_drift(services: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Track accuracy and regression drift across benchmark runs."""
    reject_retired_tenancy_fields(payload)
    suite_name = str(payload.get("suite_name", "default"))
    state_dir = getattr(services, "state_dir", None)
    if not isinstance(state_dir, (str, os.PathLike)) or not str(state_dir).strip():
        config = getattr(services, "config", {})
        state_dir = configured_state_dir(config if isinstance(config, dict) else {})
    history_file = Path(state_dir) / "eval_history.json"

    history: dict[str, Any] = {}
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text(encoding="utf-8"))
            if not isinstance(history, dict):
                raise ValueError("history must be an object")
        except (OSError, ValueError, UnicodeError):
            return {"success": False, "error_code": "invalid_eval_history", "terminal": True, "retryable": False}

    if "current" in payload:
        current = payload["current"]
    else:
        current = services.eval_suite(payload)
        if isinstance(current, dict) and current.get("success") is False:
            return current

    def valid_summary(summary: Any) -> bool:
        if not isinstance(summary, dict):
            return False
        rate = summary.get("pass_rate")
        return (
            type(rate) in (int, float) and 0 <= rate <= 1 and math.isfinite(rate)
            and summary.get("benchmark_valid", True) is True
            and summary.get("role_mismatch", False) is False
            and type(summary.get("execution_failures", 0)) is int
            and summary.get("execution_failures", 0) == 0
        )

    if not isinstance(current, dict) or current.get("success", True) is not True:
        return {"success": False, "error_code": "invalid_eval_result", "terminal": True, "retryable": False}
    current_summary = current.get("summary")
    cases = current.get("cases", [])
    if not valid_summary(current_summary) or not isinstance(cases, list) or any(
        not isinstance(case, dict) or case.get("status") in ("error", "unavailable")
        or any(case.get(flag) is True for flag in
            ("timed_out", "outcome_unknown", "in_progress", "cancelled", "truncated"))
        for case in cases
    ):
        return {"success": False, "error_code": "invalid_eval_result", "terminal": True, "retryable": False}
    curr_rate = float(current_summary["pass_rate"])

    prev_entry = history.get(suite_name)
    if prev_entry is not None:
        if not isinstance(prev_entry, dict) or not valid_summary(prev_entry.get("summary")):
            return {"success": False, "error_code": "invalid_eval_history", "terminal": True, "retryable": False}
        prev_rate = float(prev_entry["summary"]["pass_rate"])
        delta = round(curr_rate - prev_rate, 3)
        if delta > 0.01:
            status = "improved"
        elif delta < -0.01:
            status = "regressed"
        else:
            status = "stable"
    else:
        prev_rate = curr_rate
        delta = 0.0
        status = "baseline"

    history[suite_name] = {
        "timestamp": time.time(),
        "summary": current_summary,
        "cases": current.get("cases", []),
    }
    try:
        process_utils.atomic_write_file(history_file, json_dumps(history, indent=2))
    except Exception:
        return {"success": False, "error_code": "eval_history_write_failed", "outcome_unknown": True, "retryable": False}

    return {
        "success": True,
        "suite": suite_name,
        "status": status,
        "current_pass_rate": curr_rate,
        "previous_pass_rate": prev_rate,
        "drift_delta": delta,
        "summary": current_summary,
    }
