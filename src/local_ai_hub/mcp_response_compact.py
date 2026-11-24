from __future__ import annotations

from typing import Any


def _compact(
    value: Any, task_kind: str = "general", extra_fields: list[str] | None = None,
    *, page_key: str | None = None, identity: dict[str, Any] | None = None,
) -> Any:
    # Capture measured savings before the projector intentionally removes internal
    # token_saving/runtime fields. Private accounting metadata is stripped by the
    # instrumented MCP boundary and never enters agent context.
    from . import mcp_server as services_module
    if extra_fields is None:
        extra_fields = services_module._CURRENT_EXTRA_FIELDS.get()
    options = services_module._CURRENT_RESPONSE_OPTIONS.get()
    if task_kind == "command":
        extra_fields = list(dict.fromkeys([
            *(extra_fields or ()), "cache_hit", "coalesced", "output_recovery",
            *(("classification",) if options.get("action") == "classify" else ()),
        ]))
    rejection = services_module._subminimum_budget_rejection(options)
    if rejection is not None:
        return rejection
    memory_projection = (
        services_module._task_memory_projection(value) if task_kind == "task_memory" else None
    )
    if (memory_projection is None and task_kind == "task_memory"
            and isinstance(value, dict) and value.get("success") is True
            and (isinstance(value.get("task"), dict) or isinstance(value.get("tasks"), list))):
        # Generic compaction removes meaningful empty checkpoint fields. Keep
        # task responses intact and sanitized even when no memory is attached;
        # the MCP boundary still enforces the full wire budget.
        memory_projection = services_module._task_private_state_projection(value)
    if memory_projection is not None:
        # The MCP boundary below owns the *wire* budget, including both text
        # and structuredContent. Generic status/pointer clipping loses memory.
        _requested, profile, reuse_key, enabled = services_module._response_budget(task_kind, options)
        if enabled:
            repeated, previous = services_module._reuse_state(reuse_key, memory_projection)
            if profile == "delta" and previous is not None and not repeated:
                current = memory_projection
                memory_projection = services_module.delta_response(previous, current, result_id=services_module.result_id(current))
                for key in ("task", "task_id", "context_id", "request_id"):
                    if key in current:
                        memory_projection[key] = current[key]
                # Carry the authoritative task once, also when memory did not
                # change; a delta must not require a separate memory_find.
                for section in ("changed", "added"):
                    memory_projection["delta"][section].pop("task", None)
            elif repeated:
                memory_projection["reused"] = True
                if profile == "delta":
                    memory_projection["unchanged"] = True
        return services_module._normalize_task_memory_response(services_module.account_projection(value, memory_projection))
    raw_value = value
    exact_artifact_text = None
    exact_artifact_slices = None
    oversized_artifact_page = False
    artifact_page = (
        task_kind == "artifact"
        and isinstance(raw_value, dict)
        and raw_value.get("success") is True
        and isinstance(raw_value.get("artifact_id"), str)
        and isinstance(raw_value.get("offset"), int)
        and isinstance(raw_value.get("text"), str)
    )
    if artifact_page:
        if len(raw_value["text"]) <= services_module.MAX_TEXT:
            exact_artifact_text = raw_value["text"]
        else:
            oversized_artifact_page = True
    if task_kind == "artifact" and isinstance(raw_value, dict) and isinstance(raw_value.get("slices"), list):
        exact_artifact_slices = raw_value["slices"]
    projected_value = value
    if oversized_artifact_page:
        projected_value = dict(value)
        projected_value["success"] = False
        projected_value["error"] = (
            "Artifact page exceeds configured MCP text limit; "
            "increase compact_max_text_chars and retry."
        )
        projected_value.pop("text", None)
        projected_value.pop("next_offset", None)
    value = services_module.attach_accounting(projected_value)
    projected = services_module.PROJECTOR.project(value, services_module.AGENT_NAME, task_kind, extra_fields=extra_fields)
    if (
        task_kind == "coord"
        and options.get("action") == "plan_get"
        and isinstance(raw_value, dict)
        and raw_value.get("success") is True
        and isinstance(raw_value.get("plan"), dict)
        and isinstance(projected, dict)
        and projected.get("success") is True
    ):
        # Empty plan fields (for example tasks/spec_refs) are meaningful state.
        projected["plan"] = services_module.copy.deepcopy(raw_value["plan"])
    if exact_artifact_text is not None and isinstance(projected, dict):
        projected = dict(projected)
        projected["text"] = exact_artifact_text
    if exact_artifact_slices is not None and isinstance(projected, dict):
        projected = dict(projected)
        projected["slices"] = exact_artifact_slices
    compact_extra_fields = extra_fields
    if task_kind == "status":
        compact_extra_fields = list(dict.fromkeys([*(extra_fields or ()), "job_id"]))
    compact_max_items = 50
    if (
        task_kind == "coord"
        and options.get("action") == "plan_board_view"
        and isinstance(raw_value, dict)
        and type(raw_value.get("total_items")) is int
        and raw_value["total_items"] >= 0
    ):
        compact_max_items = max(compact_max_items, raw_value["total_items"])
    compacted = services_module.compact_result(
        projected,
        max_text_chars=services_module.MAX_TEXT,
        max_evidence=services_module.MAX_EVIDENCE,
        max_items=(
            max(1, min(raw_value["limit"], services_module.MAX_PAGE_SIZE))
            if (task_kind in {"search", "code_index"} or page_key in {"callers", "callees", "implementations"}) and isinstance(raw_value, dict)
            and isinstance(raw_value.get("limit"), int)
            and not isinstance(raw_value.get("limit"), bool)
            else compact_max_items
        ),
        extra_fields=compact_extra_fields,
    )
    compacted = services_module._preserve_contract_state(raw_value, compacted)
    pubsub_messages = (
        services_module.copy.deepcopy(raw_value["messages"])
        if options.get("action") == "pubsub_poll" and isinstance(raw_value, dict)
        and raw_value.get("success") is True and isinstance(raw_value.get("messages"), list)
        else None
    )
    if pubsub_messages is not None and isinstance(compacted, dict):
        # Empty/null JSON payloads carry meaning and must survive projection.
        compacted["messages"] = pubsub_messages
    wait_event = (services_module.project_wait_event_response(raw_value, enabled=services_module.detailed_diagnostics_enabled(services_module.CFG))
                  if options.get("action") == "wait_for_event" and isinstance(raw_value, dict)
                  and raw_value.get("success") is True else None)
    if wait_event is not None and isinstance(compacted, dict):
        for key in ("message", "event"):
            if key in wait_event:
                compacted[key] = services_module.copy.deepcopy(wait_event[key])
    if task_kind == "status" and isinstance(projected, dict) and isinstance(compacted, dict):
        for key in ("modified", "staged", "untracked", "deleted", "unmerged", "changed_paths", "files"):
            original, shown = projected.get(key), compacted.get(key)
            if isinstance(original, list) and isinstance(shown, list) and len(original) > len(shown):
                compacted["truncated"] = True
    if task_kind == "coord" and isinstance(raw_value, dict) and isinstance(compacted, dict):
        if "checkpoint_sync" in raw_value:
            compacted["checkpoint_sync"] = raw_value["checkpoint_sync"]
    if isinstance(raw_value, dict) and isinstance(compacted, dict):
        compacted.update({
            key: raw_value[key] for key in ("request_id", "context_id") if key in raw_value
        })
    if task_kind == "status" and isinstance(raw_value, dict) and "guide_cards" in raw_value:
        # Empty required-field arrays are meaningful in authored guide cards.
        # Generic empty-value pruning must not invalidate their wire schema.
        compacted.update({key: raw_value[key] for key in (
            "guide_cards", "guide_scope", "guide_tips", "schema_token_reduction_verified",
        ) if key in raw_value})
    if task_kind == "command" and isinstance(raw_value, dict) and isinstance(compacted, dict):
        if isinstance(raw_value.get("test_summary"), dict):
            compacted["test_summary"] = raw_value["test_summary"]
    if task_kind == "security" and isinstance(raw_value, dict) and isinstance(compacted, dict):
        compacted.update({key: raw_value[key] for key in services_module._SECURITY_PROTECTED_KEYS if key in raw_value})
    if task_kind == "complexity" and isinstance(raw_value, dict) and isinstance(compacted, dict):
        compacted.update({key: raw_value[key] for key in services_module._COMPLEXITY_PROTECTED_KEYS if key in raw_value})
    if task_kind == "topology" and isinstance(raw_value, dict) and isinstance(compacted, dict):
        compacted.update({key: raw_value[key] for key in services_module._TOPOLOGY_PROTECTED_KEYS if key in raw_value})
    if task_kind == "hardware_benchmark" and isinstance(raw_value, dict) and isinstance(compacted, dict):
        compacted.update({
            key: raw_value[key]
            for key in services_module._HARDWARE_BENCHMARK_PROTECTED_KEYS
            if key in raw_value
        })
    source_slice = task_kind == "artifact" and isinstance(raw_value, dict) and raw_value.get("action") == "source"
    if source_slice and isinstance(compacted, dict) and raw_value.get("success") is True:
        from .source_slice import SOURCE_SLICE_FIELDS
        compacted.update({key: raw_value[key] for key in SOURCE_SLICE_FIELDS if key in raw_value})
    if exact_artifact_slices is not None and isinstance(compacted, dict):
        compacted["slices"] = exact_artifact_slices
        for field in ("truncated", "budget_limited"):
            if field in raw_value:
                compacted[field] = raw_value[field]
    requested, profile, reuse_key, enabled = services_module._response_budget(task_kind, options)
    if enabled:
        expected_context_delta = None
        repeated, previous = services_module._reuse_state(reuse_key, compacted)
        if profile == "delta" and previous is not None:
            if repeated and isinstance(compacted, dict):
                if task_kind == "context":
                    current = compacted
                    compacted = {
                        key: current[key]
                        for key in (*services_module._RELIABILITY_PROTECTED_KEYS, *services_module._CONTEXT_PROTECTED_KEYS, "request_id", "root")
                        if key in current
                    }
                    compacted["result_id"] = services_module.result_id({key: value for key, value in current.items() if key != "request_id"})
                    compacted["delta"] = {"changed": {}, "added": {}, "removed": []}
                compacted["unchanged"] = True
            elif not repeated:
                if task_kind == "context" and isinstance(previous, dict) and isinstance(compacted, dict):
                    current = compacted
                    previous_content = {key: value for key, value in previous.items() if key != "request_id"}
                    current_content = {key: value for key, value in current.items() if key != "request_id"}
                    compacted = services_module.delta_response(previous_content, current_content, result_id=services_module.result_id(current_content))
                    if "request_id" in current:
                        compacted["request_id"] = current["request_id"]
                else:
                    compacted = services_module.delta_response(previous, compacted, result_id=services_module.result_id(compacted))
            if task_kind == "context" and isinstance(compacted, dict) and isinstance(compacted.get("delta"), dict):
                expected_context_delta = services_module.copy.deepcopy(compacted["delta"])
        if task_kind == "coord" and isinstance(raw_value, dict) and isinstance(compacted, dict):
            if "checkpoint_sync" in raw_value:
                compacted["checkpoint_sync"] = raw_value["checkpoint_sync"]
        protected_keys = tuple(dict.fromkeys((
            *services_module._RELIABILITY_PROTECTED_KEYS,
            *(services_module._COORD_PROTECTED_KEYS if task_kind in {"task_memory", "coord", "verify"} else ()),
            *(services_module._SECURITY_PROTECTED_KEYS if task_kind == "security" else ()),
            *(services_module._COMPLEXITY_PROTECTED_KEYS if task_kind == "complexity" else ()),
            *(services_module._TOPOLOGY_PROTECTED_KEYS if task_kind == "topology" else ()),
            *(('offset', 'limit', 'total_matches', 'has_more') if task_kind in {"search", "code_index"} or page_key in {"callers", "callees", "implementations"} else ()),
            *(('search_mode', 'result_source', 'count_exact', 'coverage_complete', 'index_state', 'index_coverage',
               'candidate_freshness', 'stale_candidate_count', 'index_revision',
               'lexical_total_matches', 'lexical_count_exact', 'lexical_priority', 'candidate_count', 'candidate_count_exact',
               'rag_candidate_count', 'rag_candidate_count_exact', 'degraded', 'degradation_reason', 'reranker',
               'sources') if task_kind == "search" else ()),
            *(('slices', 'truncated', 'budget_limited') if task_kind == "artifact" else ()),
            *(SOURCE_SLICE_FIELDS if source_slice and raw_value.get("success") is True else ()),
            *(services_module._CONTEXT_PROTECTED_KEYS if task_kind in {"context", "context_compile"} else ()),
            *(services_module._STATUS_PROTECTED_KEYS if task_kind == "status" else ()),
            *(("messages",) if pubsub_messages is not None else ()),
            *(("message", "event") if wait_event is not None else ()),
            *(services_module._HARDWARE_BENCHMARK_PROTECTED_KEYS if task_kind == "hardware_benchmark" else ()),
            *(services_module._VERIFY_PROTECTED_KEYS if task_kind == "verify" else ()),
        )))
        compacted = services_module.budget_response(
            compacted,
            max_tokens=requested,
            profile=profile,
            reuse_key=reuse_key,
            reuse_only=repeated and services_module.json_tokens(compacted) > requested // 2,
            protected_keys=protected_keys,
            token_metadata=services_module.efficiency_metadata(),
        )
        if pubsub_messages is not None and (
            not isinstance(compacted, dict)
            or services_module.json.dumps(compacted.get("messages"), sort_keys=True, separators=(",", ":"))
            != services_module.json.dumps(pubsub_messages, sort_keys=True, separators=(",", ":"))
        ):
            return {"success": False, "status_code": 413, "terminal": True, "retryable": False,
                    "error": "Pubsub messages exceed response budget; reduce limit or increase max_response_tokens"}
        if wait_event is not None and any(
            key in wait_event and (not isinstance(compacted, dict) or key not in compacted
                or services_module.json.dumps(compacted[key], sort_keys=True, separators=(",", ":"))
                != services_module.json.dumps(wait_event[key], sort_keys=True, separators=(",", ":")))
            for key in ("message", "event")
        ):
            return {"success": False, "status_code": 413, "terminal": True, "retryable": False,
                    "error": "Event exceeds response budget; increase max_response_tokens"}
        if expected_context_delta is not None and (
            not isinstance(compacted, dict) or compacted.get("delta") != expected_context_delta
        ):
            return services_module._context_delta_budget_error(raw_value, requested, reuse_key)
    if artifact_page and exact_artifact_text is not None and (
        not isinstance(compacted, dict)
        or compacted.get("text") != exact_artifact_text
        or compacted.get("offset") != raw_value.get("offset")
        or compacted.get("next_offset") != raw_value.get("next_offset")
    ):
        compacted = {
            "success": False, "status_code": 413, "terminal": True, "retryable": False,
            "error": "Reduce max_chars or increase max_response_tokens: artifact page exceeds response budget",
            "artifact_id": raw_value["artifact_id"],
        }
    if source_slice and raw_value.get("success") is True and isinstance(compacted, dict) and compacted.get("success") is True:
        if any(compacted.get(key) != raw_value.get(key) for key in SOURCE_SLICE_FIELDS):
            compacted = {
                "success": False, "status_code": 413, "terminal": True, "retryable": False,
                "error": "Exact source slice exceeds response budget; increase max_response_tokens or reduce the range/max_chars",
            }
    if (
        task_kind == "code_index"
        and isinstance(raw_value, dict)
        and raw_value.get("success") is True
        and isinstance(raw_value.get("symbols"), list)
    ):
        requested, _profile, _reuse_key, enabled = services_module._response_budget(task_kind, options)
        if enabled:
            fitted = services_module._code_index_prefix_fitting(
                compacted if isinstance(compacted, dict) else {},
                raw_value,
                raw_value["symbols"],
                requested,
                wire_budget=True,
                identity=identity,
            )
            if fitted is None or (raw_value["symbols"] and not fitted.get("symbols")):
                compacted = {
                    "success": False, "status_code": 413, "terminal": True,
                    "retryable": False,
                    "error": (
                        "The first complete code-index symbol exceeds the configured response budget."
                        if raw_value["symbols"] else
                        "The code-index response exceeds the configured response budget."
                    ),
                    "root": raw_value.get("root"), "offset": raw_value.get("offset", 0),
                    "limit": raw_value.get("limit", 24),
                    "total_matches": raw_value.get("total_matches", 0),
                    "has_more": raw_value.get("has_more", False), "symbols": [],
                }
            else:
                compacted = fitted
    if (
        page_key in {"callers", "callees", "implementations"}
        and isinstance(raw_value, dict)
        and raw_value.get("success") is True
        and isinstance(raw_value.get(page_key), list)
    ):
        requested, _profile, _reuse_key, enabled = services_module._response_budget(task_kind, options)
        if enabled:
            raw_items = raw_value[page_key]
            fitted = services_module._relation_prefix_fitting(compacted if isinstance(compacted, dict) else {}, raw_value, page_key, raw_items, requested)
            if fitted is None or (raw_items and not fitted.get(page_key)):
                compacted = {
                    "success": False, "status_code": 413, "terminal": True,
                    "retryable": False,
                    "error": f"The first complete {page_key[:-1] if page_key.endswith('s') else page_key} result exceeds the configured response budget.",
                    "offset": raw_value.get("offset", 0), "limit": raw_value.get("limit"),
                    page_key: [], "count": 0, "returned_count": 0,
                }
            else:
                compacted = fitted
    if (
        task_kind == "search"
        and isinstance(raw_value, dict)
        and raw_value.get("success") is True
        and isinstance(raw_value.get("results"), list)
        and not raw_value.get("artifact_id")
    ):
        page_key = "results"
        requested, _profile, _reuse_key, enabled = services_module._response_budget(task_kind, options)
        if enabled:
            raw_items = raw_value[page_key]
            fitted = services_module._search_prefix_fitting(
                compacted if isinstance(compacted, dict) else {},
                raw_value,
                raw_items,
                requested,
                wire_budget=True,
                extra_fields=extra_fields,
            )
            if fitted is None or (raw_items and not fitted.get(page_key)):
                requested_limit = raw_value.get("limit", 24)
                recovery = (
                    "reduce limit or omit max_response_tokens/use a larger cap"
                    if isinstance(requested_limit, int) and not isinstance(requested_limit, bool) and requested_limit > 1
                    else "omit max_response_tokens or use a larger cap"
                )
                compacted = {
                    "success": False,
                    "status_code": 413,
                    "terminal": True,
                    "retryable": False,
                    "error": f"The requested {task_kind} page exceeds the configured MCP response budget; {recovery}.",
                    "root": raw_value.get("root"),
                    "offset": raw_value.get("offset", 0),
                    "limit": raw_value.get("limit", 24),
                    "total_matches": raw_value.get("total_matches", 0),
                    "has_more": raw_value.get("has_more", False),
                    page_key: [],
                }
            else:
                compacted = fitted
    if profile == "dense" and isinstance(compacted, dict) and compacted.get("success") is True:
        for key in ("path_hint_usage", "token_efficiency", "workspace_cache", "engine", "scanned_files", "terms"):
            compacted.pop(key, None)
    return services_module._normalize_deterministic(services_module.account_projection(raw_value, compacted))
