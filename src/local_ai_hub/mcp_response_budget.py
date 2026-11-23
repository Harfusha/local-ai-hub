from __future__ import annotations

from typing import Any

from .mcp_context_guard import get_mcp_server_module


def _subminimum_budget_rejection(options: dict[str, Any]) -> dict[str, Any] | None:
    try:
        requested = int(options.get("max_response_tokens") or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if requested <= 0 or requested >= 128:
        return None
    return {
        "success": False,
        "status_code": 400,
        "terminal": True,
        "retryable": False,
        "error": "max_response_tokens must be at least 128",
        "response_budget": {"requested_tokens": requested, "minimum_tokens": 128, "rejected": True},
    }

def _explicit_budget_rejection(arguments: dict[str, Any]) -> dict[str, Any] | None:
    if "max_response_tokens" not in arguments:
        return None
    requested = arguments["max_response_tokens"]
    if requested is None or requested == 0:
        return None
    if type(requested) is not int or requested < 128:
        return {
            "success": False,
            "status_code": 400,
            "terminal": True,
            "retryable": False,
            "error": "max_response_tokens must be an integer of at least 128",
        }
    return None

def _response_budget(task_kind: str, options: dict[str, Any]) -> tuple[int, str, str, bool]:
    services_module = get_mcp_server_module()
    requested_profile = str(options.get("response_profile") or "").strip().lower()
    profile = requested_profile or "compact"
    if profile not in {"minimal", "compact", "standard", "debug", "delta", "dense"}:
        profile = "compact"
    if not requested_profile:
        profile = services_module.CONTEXT_LEDGER.adaptive_profile(profile)
    explicit_budget = type(options.get("max_response_tokens")) is int and options["max_response_tokens"] >= 128
    try:
        requested = int(options.get("max_response_tokens") or 0)
    except (TypeError, ValueError, OverflowError):
        requested = 0
    tool_name = str(options.get("tool") or "")
    configured = services_module.RESPONSE_TOOL_TOKENS.get(tool_name) or services_module.RESPONSE_TOOL_TOKENS.get(task_kind) or services_module.RESPONSE_DEFAULT_TOKENS
    if not requested:
        try:
            requested = int(configured)
        except (TypeError, ValueError, OverflowError):
            requested = services_module.RESPONSE_DEFAULT_TOKENS
    try:
        max_allowed = max(services_module.RESPONSE_DEFAULT_TOKENS, int(services_module.RESPONSE_BUDGET_CFG.get("max_tokens", services_module.RESPONSE_DEFAULT_TOKENS * 2)))
    except (TypeError, ValueError, OverflowError):
        max_allowed = services_module.RESPONSE_DEFAULT_TOKENS * 2
    requested = min(requested, max_allowed)
    if profile == "minimal" and not explicit_budget:
        requested = min(requested, max(256, services_module.RESPONSE_DEFAULT_TOKENS // 2))
    elif profile == "standard" and not explicit_budget:
        requested = max(requested, services_module.RESPONSE_DEFAULT_TOKENS)
    elif profile == "debug" and not explicit_budget:
        requested = max(requested, int(services_module.RESPONSE_DEFAULT_TOKENS * 2))
    return max(128, requested), profile, str(options.get("reuse_key") or "")[:160], services_module.RESPONSE_BUDGET_ENABLED

def _reuse_only(key: str, value: Any) -> bool:
    services_module = get_mcp_server_module()
    return services_module._reuse_state(key, value)[0]

def _reuse_state(key: str, value: Any) -> tuple[bool, Any]:
    services_module = get_mcp_server_module()
    if not key:
        return False, None
    # Transport correlation changes for each request, even when its answer does
    # not. Retain the current identity in the response and stored snapshot.
    identity = {field: item for field, item in value.items() if field != "request_id"} if isinstance(value, dict) else value
    digest = services_module.hashlib.sha256(repr(services_module._normalize_deterministic(identity)).encode("utf-8", errors="replace")).hexdigest()
    previous = services_module._REUSE_DIGESTS.get(key)
    previous_value = services_module._REUSE_VALUES.get(key)
    services_module._REUSE_DIGESTS[key] = digest
    services_module._REUSE_VALUES[key] = value
    services_module._REUSE_DIGESTS.move_to_end(key)
    services_module._REUSE_VALUES.move_to_end(key)
    while len(services_module._REUSE_DIGESTS) > services_module.RESPONSE_REUSE_LIMIT:
        services_module._REUSE_DIGESTS.popitem(last=False)
    while len(services_module._REUSE_VALUES) > services_module.RESPONSE_REUSE_LIMIT:
        services_module._REUSE_VALUES.popitem(last=False)
    return previous == digest, previous_value

def _context_delta_budget_error(value: Any, requested: int, reuse_key: str) -> dict[str, Any]:
    # A rejected delta was never delivered. Forget its snapshot so a later call
    # cannot incorrectly tell the caller that it already has the new context.
    services_module = get_mcp_server_module()
    if reuse_key:
        services_module._REUSE_DIGESTS.pop(reuse_key, None)
        services_module._REUSE_VALUES.pop(reuse_key, None)
    result = {"success": False, "status_code": 413, "terminal": True, "retryable": False,
              "error": services_module._CONTEXT_DELTA_BUDGET_ERROR}
    if isinstance(value, dict):
        for key in ("root", "request_id"):
            if isinstance(value.get(key), str) and value[key]:
                result[key] = value[key]
    result["response_budget"] = {"requested_tokens": requested, "original_tokens": services_module.json_tokens(value),
                                 "returned_tokens": 0, "truncated": True, "reused": False,
                                 "unit": "estimated_tokens"}
    return services_module.budget_response(result, max_tokens=requested, profile="compact", reuse_key=reuse_key,
                           protected_keys=tuple(result), token_metadata=services_module.efficiency_metadata())

def _code_index_page_with_prefix(
    base: dict[str, Any], raw: dict[str, Any], symbols: list[Any], count: int,
    *, identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an honest code-index page containing a whole-symbol prefix."""
    services_module = get_mcp_server_module()
    candidate = services_module.copy.deepcopy(raw if raw.get("success") is True and base.get("success") is False else base)
    for key in ("root", "query"):
        candidate.pop(key, None)
        value = identity.get(key) if isinstance(identity, dict) else None
        if isinstance(value, str):
            candidate[key] = value
    if raw.get("success") is True:
        for key in ("error", "status_code", "terminal", "retryable", "failure_kind"):
            candidate.pop(key, None)
            if key in raw:
                candidate[key] = services_module.copy.deepcopy(raw[key])
    offset = raw.get("offset", 0)
    total = raw.get("total_matches", 0)
    requested_limit = raw.get("limit", 24)
    has_more = bool(raw.get("has_more")) or count < len(symbols)
    candidate.update({
        "success": True,
        "symbols": symbols[:count],
        "offset": offset,
        "limit": requested_limit,
        "returned_limit": count,
        "returned_count": count,
        "matches_count": count,
        "total_matches": total,
        "has_more": has_more,
    })
    if has_more and isinstance(offset, int) and not isinstance(offset, bool):
        candidate["next_offset"] = offset + count
    else:
        candidate.pop("next_offset", None)
    if has_more or count < len(symbols):
        matched_terms = sorted({
            str(term)
            for symbol in symbols[:count]
            if isinstance(symbol, dict) and isinstance(symbol.get("matched_terms"), list)
            for term in symbol["matched_terms"]
        })
        terms = raw.get("terms") if isinstance(raw.get("terms"), list) else []
        raw_coverage = raw.get("coverage") if isinstance(raw.get("coverage"), dict) else {}
        declared_count = raw_coverage.get("query_term_count")
        query_term_count = len(terms) if terms else declared_count if type(declared_count) is int and declared_count >= 0 else 0
        coverage_available = 0 < query_term_count and len(matched_terms) <= query_term_count
        candidate["coverage"] = {
            "query_term_count": query_term_count,
            "matched_term_count": len(matched_terms),
            "matched_terms": matched_terms,
            "query_term_coverage": round(len(matched_terms) / query_term_count, 3) if coverage_available else 0.0,
            "coverage_available": coverage_available,
            "candidate_match_count": total,
            "returned_symbol_count": count,
            "complete": False,
            "scope": "indexed_symbol_candidates",
        }
        candidate_paths = list(dict.fromkeys(
            str(symbol["path"]) for symbol in symbols[:count]
            if isinstance(symbol, dict) and symbol.get("path")
        ))
        candidate["freshness"] = {
            "status": "not_checked", "scope": "returned_symbol_candidates",
            "checked_paths": 0, "stale_paths": [],
            "unknown_paths": candidate_paths[:64], "complete": False,
        }
        if raw.get("stale") is True:
            candidate["stale"] = True
        else:
            candidate.pop("stale", None)
        candidate.pop("parse_outcomes", None)
        candidate["omitted_fields"] = list(dict.fromkeys([
            *(candidate.get("omitted_fields") if isinstance(candidate.get("omitted_fields"), list) else []),
            "parse_outcomes",
        ]))
        coverage = candidate["coverage"]["query_term_coverage"]
        support = min(1.0, count / 3.0)
        derived_confidence = round(0.65 * coverage + 0.20 * support, 3) if candidate_paths else 0.0
        raw_confidence = raw.get("confidence")
        if (isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool)
                and 0 <= raw_confidence <= 1):
            candidate["confidence"] = min(float(raw_confidence), derived_confidence, 0.50)
        else:
            candidate.pop("confidence", None)
            candidate.pop("confidence_basis", None)
            candidate["omitted_fields"] = list(dict.fromkeys([
                *candidate["omitted_fields"], "confidence", "confidence_basis",
            ]))
        candidate["truncated"] = has_more
        candidate["observed_match_count"] = total
        truncation = raw.get("truncation")
        truncation = dict(truncation) if isinstance(truncation, dict) else {}
        truncation.update({
            "result_limit": requested_limit,
            "returned_count": count,
            "observed_match_count": raw.get("observed_match_count", total),
        })
        candidate["truncation"] = truncation
        response_budget = candidate.get("response_budget")
        if isinstance(response_budget, dict):
            response_budget.pop("rejected", None)
    return candidate

def _code_index_prefix_fitting(
    base: dict[str, Any], raw: dict[str, Any], symbols: list[Any], requested: int,
    *, wire_budget: bool, identity: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Fit a whole-symbol prefix, reducing optional symbol detail only as needed."""
    services_module = get_mcp_server_module()
    minimal_keys = ("name", "kind", "path", "line", "end_line", "matched_terms")
    minimal_symbols = [
        {key: symbol[key] for key in minimal_keys if key in symbol}
        if isinstance(symbol, dict) else symbol
        for symbol in symbols
    ]
    essential_keys = ("name", "path", "line")
    essential_symbols = [
        {key: symbol[key] for key in essential_keys if key in symbol}
        if isinstance(symbol, dict) else symbol
        for symbol in symbols
    ]
    symbol_shapes = (
        (symbols, False, False),
        (minimal_symbols, True, False),
        (essential_symbols, True, True),
    )
    for source_symbols, reduced, compact_metadata in symbol_shapes:
        if reduced and source_symbols == symbols and not compact_metadata:
            continue
        min_count = 1 if source_symbols else 0
        for count in range(len(source_symbols), min_count - 1, -1):
            candidate = services_module._code_index_page_with_prefix(
                base, raw, source_symbols, count, identity=identity,
            )
            if reduced:
                omitted = sorted({
                    f"symbols.{key}"
                    for original, projected in zip(symbols[:count], source_symbols[:count])
                    if isinstance(original, dict) and isinstance(projected, dict)
                    for key in original
                    if key not in projected
                })
                if omitted:
                    candidate["omitted_fields"] = list(dict.fromkeys([
                        *(candidate.get("omitted_fields") if isinstance(candidate.get("omitted_fields"), list) else []),
                        *omitted,
                    ]))
            if compact_metadata:
                omitted = [
                    key for key in (
                        "parse_outcomes", "confidence_basis", "confidence",
                        "freshness", "coverage", "truncation",
                    )
                    if key in candidate
                ]
                for key in omitted:
                    candidate.pop(key, None)
                if omitted:
                    candidate["omitted_fields"] = list(dict.fromkeys([
                        *(candidate.get("omitted_fields") if isinstance(candidate.get("omitted_fields"), list) else []),
                        *omitted,
                    ]))
            candidate = services_module._normalize_deterministic(services_module.account_projection(raw, candidate))
            if services_module.json_tokens(candidate) > requested:
                continue
            if wire_budget:
                wire = {
                    "content": [{"type": "text", "text": services_module.json_dumps(candidate)}],
                    "structuredContent": candidate,
                    "isError": False,
                }
                if services_module.json_tokens(wire) > requested:
                    continue
            return candidate
    return None

def _relation_page_with_prefix(
    base: dict[str, Any], raw: dict[str, Any], page_key: str, items: list[Any], count: int,
) -> dict[str, Any]:
    """Keep relation page metadata aligned with the whole-item prefix that fits."""
    services_module = get_mcp_server_module()
    candidate = services_module.copy.deepcopy(raw if raw.get("success") is True and base.get("success") is False else base)
    candidate[page_key] = items[:count]
    candidate["count"] = count
    candidate["returned_count"] = count
    if page_key == "implementations":
        candidate["implementations_count"] = count
    offset = raw.get("offset", 0)
    if isinstance(offset, int) and not isinstance(offset, bool):
        candidate["offset"] = offset
    if "limit" in raw:
        candidate["limit"] = raw["limit"]
    if "total_matches" in raw:
        candidate["total_matches"] = raw["total_matches"]
    elif "total_matches" in candidate:
        candidate.pop("total_matches", None)
    total = raw.get("total_matches")
    known_more = count < len(items)
    if "has_more" in raw or known_more:
        candidate["has_more"] = bool(raw.get("has_more")) or known_more or (
            isinstance(total, int) and not isinstance(total, bool)
            and isinstance(offset, int) and not isinstance(offset, bool)
            and offset + count < total
        )
    elif "has_more" not in raw:
        candidate.pop("has_more", None)
    has_more = candidate.get("has_more") is True
    if has_more and isinstance(offset, int) and not isinstance(offset, bool):
        candidate["next_offset"] = offset + count
    else:
        candidate.pop("next_offset", None)
    candidate["truncated"] = bool(raw.get("truncated")) or known_more or has_more
    raw_truncation = raw.get("truncation")
    truncation = dict(raw_truncation) if isinstance(raw_truncation, dict) else {}
    truncation[page_key] = candidate["truncated"]
    if "returned_count" in truncation:
        truncation["returned_count"] = count
    if truncation:
        candidate["truncation"] = truncation
    elif "truncation" in candidate:
        candidate.pop("truncation", None)
    raw_coverage = raw.get("coverage")
    coverage = dict(raw_coverage) if isinstance(raw_coverage, dict) else {}
    coverage.update({"returned": count, "offset": offset, "limit": raw.get("limit")})
    if not isinstance(raw_coverage, dict) or raw_coverage.get("complete") is not True or count < len(items):
        coverage["complete"] = False
    candidate["coverage"] = coverage
    return candidate

def _relation_prefix_fitting(
    base: dict[str, Any], raw: dict[str, Any], page_key: str, items: list[Any], requested: int,
) -> dict[str, Any] | None:
    services_module = get_mcp_server_module()
    for count in range(len(items), -1, -1):
        candidate = services_module._normalize_deterministic(services_module.account_projection(
            raw, services_module._relation_page_with_prefix(base, raw, page_key, items, count),
        ))
        if services_module.json_tokens(candidate) > requested:
            continue
        wire = {
            "content": [{"type": "text", "text": services_module.json_dumps(candidate)}],
            "structuredContent": candidate,
            "isError": False,
        }
        if services_module.json_tokens(wire) <= requested:
            return candidate
    return None

def _search_page_with_prefix(
    base: dict[str, Any], raw: dict[str, Any], results: list[Any], count: int,
) -> dict[str, Any]:
    """Keep search page metadata aligned with the whole-result prefix that fits."""
    services_module = get_mcp_server_module()
    candidate = services_module.copy.deepcopy(raw if raw.get("success") is True and base.get("success") is False else base)
    offset = raw.get("offset", 0)
    total = raw.get("total_matches", raw.get("matches_count", 0))
    requested_limit = raw.get("limit", 24)
    has_more = bool(raw.get("has_more")) or count < len(results) or (
        isinstance(total, int) and not isinstance(total, bool)
        and isinstance(offset, int) and not isinstance(offset, bool)
        and offset + count < total
    )
    candidate.update({
        "success": True,
        "results": results[:count],
        "offset": offset,
        "limit": requested_limit,
        "returned_limit": count,
        "returned_count": count,
        "matches_count": count,
        "total_matches": total,
        "has_more": has_more,
    })
    if has_more and isinstance(offset, int) and not isinstance(offset, bool):
        candidate["next_offset"] = offset + count
    else:
        candidate.pop("next_offset", None)
    candidate["truncated"] = bool(raw.get("truncated")) or count < len(results) or has_more
    raw_truncation = raw.get("truncation")
    truncation = dict(raw_truncation) if isinstance(raw_truncation, dict) else {}
    truncation.update({
        "results": candidate["truncated"],
        "returned_count": count,
        "total_matches": total,
    })
    candidate["truncation"] = truncation
    raw_coverage = raw.get("coverage")
    coverage = dict(raw_coverage) if isinstance(raw_coverage, dict) else {}
    coverage.update({"returned": count, "offset": offset, "limit": requested_limit})
    if not isinstance(raw_coverage, dict) or raw_coverage.get("complete") is not True or count < len(results):
        coverage["complete"] = False
    candidate["coverage"] = coverage
    candidate.pop("error", None)
    candidate.pop("status_code", None)
    candidate.pop("terminal", None)
    candidate.pop("retryable", None)
    response_budget = candidate.get("response_budget")
    if isinstance(response_budget, dict):
        response_budget.pop("rejected", None)
    return candidate

def _search_prefix_fitting(
    base: dict[str, Any], raw: dict[str, Any], results: list[Any], requested: int,
    *, wire_budget: bool = False, extra_fields: list[str] | None = None,
) -> dict[str, Any] | None:
    """Fit a whole-result prefix, reducing optional result detail only as needed."""
    services_module = get_mcp_server_module()
    projected_results = []
    for item in results:
        if not isinstance(item, dict):
            projected_results.append(item)
            continue
        projected = services_module.PROJECTOR.project(item, services_module.AGENT_NAME, "search", extra_fields=extra_fields)
        if isinstance(projected, dict):
            for exact_field in ("text", "raw"):
                if isinstance(item.get(exact_field), str):
                    projected[exact_field] = item[exact_field]
        projected_results.append(projected)
    minimal_results = [
        {
            key: (
                item[key][:160] + "..."
                if key == "text" and isinstance(item.get("text"), str) and len(item[key]) > 160
                else item[key]
            )
            for key in ("path", "start_line", "end_line", "score", "evidence_id", "text")
            if key in item
        }
        if isinstance(item, dict) else item
        for item in projected_results
    ]
    essential_results = [
        {
            key: item[key] for key in ("path", "start_line", "end_line", "score", "evidence_id")
            if key in item
        }
        if isinstance(item, dict) else item
        for item in projected_results
    ]

    shapes = (
        (projected_results, False, False),
        (minimal_results, True, False),
        (essential_results, True, True),
    )

    for source_results, reduced, compact_metadata in shapes:
        if reduced and source_results == results and not compact_metadata:
            continue
        min_count = 1 if source_results else 0
        for count in range(len(source_results), min_count - 1, -1):
            candidate = services_module._search_page_with_prefix(base, raw, source_results, count)
            if compact_metadata:
                omitted = [
                    key for key in (
                        "workspace_cache", "path_hint_usage", "engine", "scanned_files", "terms",
                        "source_validation", "stale_candidate_details",
                    )
                    if key in candidate
                ]
                for key in omitted:
                    candidate.pop(key, None)
                if omitted:
                    candidate["omitted_fields"] = list(dict.fromkeys([
                        *(candidate.get("omitted_fields") if isinstance(candidate.get("omitted_fields"), list) else []),
                        *omitted,
                    ]))
            candidate = services_module._normalize_deterministic(services_module.account_projection(raw, candidate))
            if services_module.json_tokens(candidate) > requested:
                continue
            if wire_budget:
                wire = {
                    "content": [{"type": "text", "text": services_module.json_dumps(candidate)}],
                    "structuredContent": candidate,
                    "isError": False,
                }
                if services_module.json_tokens(wire) > requested:
                    continue
            return candidate
    return None

def _batch_items_retained(original: Any, projected: Any) -> bool:
    if not isinstance(original, list):
        return True
    return (
        isinstance(projected, list) and len(projected) == len(original)
        and all(
            isinstance(before, dict) and isinstance(after, dict)
            and all(after.get(key) == before[key] for key in (
                "id", "success", "text", "result", "output", "error", "terminal", "retryable",
                "artifact_id", "output_artifact_id", "evidence_id", "evidence_ids", "job_id",
                "request_not_sent", "outcome_unknown", "in_progress", "cancelled",
            ) if key in before)
            for before, after in zip(original, projected)
        )
    )

def _context_input_error(message: str) -> dict[str, Any]:
    return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": message[:400]}

def _validate_context_pack_inputs(
    *,
    task_id: Any,
    session_id: Any,
    phase: Any,
    focus: Any,
    preload_profile: Any,
    changed_paths: Any,
    base: Any,
    staged: Any,
    guarded: Any,
    since_hash: Any,
    approval: Any,
    override_reason: Any,
    max_tokens: Any,
    token_budget: Any,
    clone_id: Any = "",
    worktree_id: Any = "",
    branch: Any = "",
    repository_id: Any = "",
    repository_revision: Any = "",
    include_diagnostics: Any = False,
) -> dict[str, Any] | None:
    services_module = get_mcp_server_module()
    if not isinstance(guarded, bool):
        return services_module._context_input_error("guarded must be boolean")
    for name, value in (
        ("task_id", task_id), ("session_id", session_id), ("phase", phase), ("preload_profile", preload_profile),
        ("base", base), ("since_hash", since_hash), ("override_reason", override_reason),
        ("clone_id", clone_id), ("worktree_id", worktree_id), ("branch", branch),
        ("repository_id", repository_id), ("repository_revision", repository_revision),
    ):
        if not isinstance(value, str):
            return services_module._context_input_error(f"{name} must be string")
    from .agent_consistency import normalize_context_phase
    try:
        normalize_context_phase(phase)
    except ValueError as exc:
        return services_module._context_input_error(str(exc))
    for name, value, limit in (("focus", focus, 16), ("changed_paths", changed_paths, 64)):
        if value is not None:
            if not isinstance(value, list):
                return services_module._context_input_error(f"{name} must be a list")
            if len(value) > limit:
                return services_module._context_input_error(f"{name} exceeds maximum of {limit} items")
            if any(not isinstance(item, str) for item in value):
                return services_module._context_input_error(f"{name} items must be strings")
    if not isinstance(staged, bool):
        return services_module._context_input_error("staged must be boolean")
    if not isinstance(approval, (bool, str)):
        return services_module._context_input_error("approval must be boolean or string")
    for name, value in (("max_tokens", max_tokens), ("token_budget", token_budget)):
        if not isinstance(value, int) or isinstance(value, bool):
            return services_module._context_input_error(f"{name} must be integer")
        if value < 0:
            return services_module._context_input_error(f"{name} must be non-negative")
        if value and not 128 <= value <= 20_000:
            return services_module._context_input_error(f"{name} must be 0 or between 128 and 20000")
    if not isinstance(include_diagnostics, bool):
        return services_module._context_input_error("include_diagnostics must be boolean")
    if token_budget and max_tokens and token_budget != max_tokens:
        return services_module._context_input_error("token_budget and max_tokens must match when both are provided")
    guarded_requested = (
        guarded or bool(task_id.strip()) or bool(phase.strip()) or bool(session_id.strip())
        or bool(str(clone_id).strip()) or bool(str(worktree_id).strip()) or bool(str(branch).strip())
        or bool(str(repository_id).strip()) or bool(str(repository_revision).strip()) or include_diagnostics
        or changed_paths is not None or focus is not None
    )
    guarded_only_values = (
        focus is not None or bool(preload_profile) or changed_paths is not None or base != "HEAD"
        or staged or bool(since_hash) or approval != "" or bool(override_reason) or bool(token_budget)
        or bool(str(clone_id).strip()) or bool(str(worktree_id).strip()) or bool(str(branch).strip())
        or bool(str(repository_id).strip()) or bool(str(repository_revision).strip()) or include_diagnostics
    )
    if guarded_only_values and not guarded_requested:
        return services_module._context_input_error("guarded context fields require guarded=true, task_id, or phase")
    if (guarded or phase.strip() or focus is not None or changed_paths is not None) and not task_id.strip():
        return services_module._context_input_error("guarded context requires a non-empty task_id")
    return None

def _bound_context_json(value: Any, depth: int = 0) -> Any:
    services_module = get_mcp_server_module()
    if depth > 5:
        return "[…depth…]"
    if isinstance(value, str):
        return value[:6000]
    if isinstance(value, list):
        return [services_module._bound_context_json(item, depth + 1) for item in value[:64]]
    if isinstance(value, dict):
        return {str(key)[:160]: services_module._bound_context_json(item, depth + 1) for key, item in list(value.items())[:64]}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:600]
