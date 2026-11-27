from __future__ import annotations

# import copy
from pathlib import Path, PureWindowsPath
import sys
import time
from typing import Any
# import uuid


def _get_services_module() -> Any:
    for mod_name, mod in list(sys.modules.items()):
        if mod_name.startswith("local_ai_hub._mcp_server_") and mod is not None:
            return mod
    from . import mcp_server
    return mcp_server


def _mcp_wire_view(value: Any, *, structured: bool) -> dict[str, Any]:
    services_module = _get_services_module()
    wire: dict[str, Any] = {"content": [{"type": "text", "text": services_module.json_dumps(value)}]}
    if structured:
        wire["structuredContent"] = value
        wire["isError"] = False
    return wire

def _mcp_task_memory_wire(value: dict[str, Any], requested: int) -> Any:
    """Fit complete adoption advice or explicitly reject its delivery."""
    services_module = _get_services_module()
    sanitized_value = services_module._task_private_state_projection(value)
    memory_projection = services_module._task_memory_projection(sanitized_value)
    canonical = services_module._normalize_task_memory_response(
        memory_projection if memory_projection is not None else sanitized_value
    )
    original = services_module._task_memory_original_tokens(canonical)

    def emit(payload: dict[str, Any], *, compact_error_text: bool = False,
             minimal_error_text: bool = False) -> Any:
        payload = services_module.copy.deepcopy(payload)

        def text_payload() -> dict[str, Any]:
            if minimal_error_text:
                return {"success": False, "error": payload["error"]}
            return ({key: item for key, item in payload.items() if key != "response_budget"}
                    if compact_error_text else payload)

        for _ in range(16):
            text = services_module.json_dumps(text_payload())
            returned = services_module._task_memory_mcp_wire_tokens(payload, text_payload=text_payload())
            payload["response_budget"]["returned_tokens"] = returned
            text = services_module.json_dumps(text_payload())
            measured = services_module._task_memory_mcp_wire_tokens(payload, text_payload=text_payload())
            if measured == returned and measured <= requested:
                return [services_module.mcp_types.TextContent(type="text", text=text)], payload
        return None

    essential = services_module._task_memory_essential_response(canonical)
    for key in ("reused", "unchanged"):
        if key in value:
            essential[key] = value[key]
    # Preserve optional envelope metadata, but never bypass the task projection.
    # The complete memory bundle remains equivalent in every successful candidate.
    safe_value = services_module.copy.deepcopy(sanitized_value)
    if isinstance(canonical.get("task"), dict):
        safe_value["task"] = services_module.copy.deepcopy(canonical["task"])
    if isinstance(canonical.get("tasks"), list):
        safe_value["tasks"] = services_module.copy.deepcopy(canonical["tasks"])
    for source in (safe_value, essential):
        candidate = services_module.copy.deepcopy(source)
        candidate["response_budget"] = {
            "requested_tokens": requested, "original_tokens": original,
            "returned_tokens": 0, "unit": "estimated_tokens",
        }
        fitted = emit(candidate)
        if fitted is not None:
            return fitted
    rejection = {
        "success": False, "error": "budget_too_small", "terminal": True, "retryable": False,
    }
    if requested >= 512:
        rejection["next_action"] = "request_larger_response_budget"
    for key in (
        "request_id", "outcome_unknown", "request_not_sent",
        "mutation_applied", "operation_not_started",
    ):
        if key in value:
            rejection[key] = value[key]
    if "task_id" in value:
        rejection["task_id"] = value["task_id"]
    elif "context_id" in value:
        rejection["context_id"] = value["context_id"]
    else:
        rejection["result_id"] = services_module.result_id(value)
    if value.get("success") is False:
        if "status_code" in value:
            rejection["status_code"] = value["status_code"]
        if "error" in value:
            rejection["source_error"] = str(value["error"])
    # Unbounded external identifiers may themselves exceed the wire quota.
    # In that case carry the existing content-addressed result identity,
    # never a shortened task ID or a successful memory-free pointer.
    compact_identity = {key: item for key, item in rejection.items() if key not in {"task_id", "context_id"}}
    compact_identity["result_id"] = services_module.result_id(value)
    identities = [rejection, compact_identity]
    for identity in identities:
        for source_error_chars in (500, 128, 64, 32, 8):
            bounded_identity = dict(identity)
            if "source_error" in bounded_identity:
                bounded_identity["source_error"] = bounded_identity["source_error"][:source_error_chars]
            for metadata in (
                {"requested_tokens": requested, "returned_tokens": 0, "rejected": True, "unit": "estimated_tokens"},
                {"requested_tokens": requested, "returned_tokens": 0},
                {"returned_tokens": 0},
            ):
                candidate = {**bounded_identity, "response_budget": metadata}
                fitted = emit(candidate, compact_error_text=True)
                if fitted is not None:
                    return fitted
                # Structured error retains status, original failure and full
                # identity. A compact text error avoids duplicating these
                # fields when only 128 protocol tokens are available.
                fitted = emit(candidate, minimal_error_text=True)
                if fitted is not None:
                    return fitted
    raise ValueError("Task-memory budget cannot represent the rejection envelope")

def _mcp_bounded_error(value: dict[str, Any], requested: int) -> Any:
    services_module = _get_services_module()
    command_failure = value.get("success") is False and (
        "execution_id" in value or value.get("exit_code") not in (None, 0)
    )
    if not command_failure:
        if value.get("next_action") == "request_larger_response_budget":
            rejection = dict(value)
            rejection["response_budget"] = {
                "requested_tokens": requested, "returned_tokens": 0, "rejected": True,
            }
            content = [services_module.mcp_types.TextContent(type="text", text="Increase max_response_tokens.")]
            wire = {
                "content": [item.model_dump(mode="json", exclude_none=True) for item in content],
                "structuredContent": rejection, "isError": False,
            }
            for _ in range(16):
                returned = services_module.json_tokens(wire)
                rejection["response_budget"]["returned_tokens"] = returned
                if services_module.json_tokens(wire) == returned:
                    break
            if services_module.json_tokens(wire) <= requested:
                return content, rejection
        # Preserve the existing context/evidence projection for other tools;
        # the compact command envelope below must not consume their fields.
        error = str(value.get("error") or "tool failed")
        for include_optional in (True, False):
            for dropped in ((), ("status_code",), ("status_code", "terminal", "retryable")):
                for error_chars in (512, 256, 128, 64, 48, 40, 32, 24, 16, 8, 4, 1):
                    candidate = {
                        "success": False,
                        "error": error[:error_chars],
                        **{
                            key: value[key]
                            for key in ("status", "status_code", "terminal", "retryable", "request_id", "execution_id",
                                        "hub_online", "degraded",
                                        "mutation_applied", "operation_not_started", "outcome_unknown",
                                        "request_not_sent", "in_progress", "output_artifact_id",
                                        "review_scope_complete", "untracked_inventory_complete",
                                        "total_matches", "has_more", "offset", "limit",
                                        "task_context_artifact_id", "next_action",
                                        "plan_id", "file_revision", "rel_path", "task_id", "plan_task_id")
                            if key in value and key not in dropped
                        },
                    }
                    if include_optional:
                        for key in (*services_module._CONTEXT_PROTECTED_KEYS, "evidence", "evidence_id", "evidence_ids", "artifact_id", "artifact_ids"):
                            if key != "error" and key in value and key not in dropped:
                                candidate[key] = value[key]
                    for text_mode in ("full", "compact", "minimal"):
                        for metadata in (
                            {"requested_tokens": requested, "returned_tokens": 0, "unit": "estimated_tokens"},
                            {"requested_tokens": requested, "returned_tokens": 0},
                        ):
                            trial = dict(candidate)
                            trial["response_budget"] = dict(metadata)

                            def wire_payload() -> dict[str, Any]:
                                wire = services_module._mcp_wire_view(trial, structured=True)
                                if text_mode == "minimal":
                                    wire["content"][0]["text"] = services_module.json_dumps({
                                        "success": False, "error": trial["error"],
                                        **{
                                            key: trial[key]
                                            for key in (
                                                "hub_online", "degraded",
                                                "evidence", "evidence_id", "evidence_ids",
                                                "mutation_applied", "operation_not_started", "outcome_unknown",
                                                "request_not_sent", "in_progress", "output_artifact_id",
                                                "total_matches", "has_more", "offset", "limit",
                                                "plan_id", "file_revision", "rel_path", "task_id", "plan_task_id",
                                            )
                                            if key in trial
                                        },
                                        "response_budget": trial["response_budget"],
                                    })
                                elif text_mode == "compact":
                                    wire["content"][0]["text"] = services_module.json_dumps({
                                        "success": False, "error": trial["error"],
                                        **{
                                            key: trial[key]
                                            for key in (
                                                "status", "status_code", "terminal", "retryable",
                                                "hub_online", "degraded",
                                                "mutation_applied", "operation_not_started", "outcome_unknown",
                                                "request_not_sent", "in_progress", "output_artifact_id",
                                                "request_id", "execution_id",
                                                "evidence", "evidence_id", "evidence_ids", "artifact_id", "artifact_ids",
                                                "total_matches", "has_more", "offset", "limit",
                                                "plan_id", "file_revision", "rel_path", "task_id", "plan_task_id",
                                            )
                                            if key in trial
                                        },
                                        "response_budget": trial["response_budget"],
                                    })
                                return wire

                            for _ in range(16):
                                returned = services_module.json_tokens(wire_payload())
                                trial["response_budget"]["returned_tokens"] = returned
                                if services_module.json_tokens(wire_payload()) == returned:
                                    break
                            wire = wire_payload()
                            if services_module.json_tokens(wire) <= requested:
                                return [services_module.mcp_types.TextContent(type="text", text=wire["content"][0]["text"])], trial
        return None
    error = str(value.get("error") or "")
    metadata_variants = (
        {"requested_tokens": requested, "returned_tokens": 0, "unit": "estimated_tokens"},
        {"requested_tokens": requested, "returned_tokens": 0},
    )
    protocol_keys = (
        "status", "status_code", "terminal", "retryable", "request_id", "execution_id",
        "exit_code", "outcome_unknown", "request_not_sent", "in_progress", "timed_out",
        "mutation_applied", "operation_not_started",
        "total_matches", "has_more", "offset", "limit",
    )
    for include_optional in (True, False):
        for error_chars in (None, 512, 256, 128, 64, 32, 16, 8, 1):
            for summary_chars in (None, 512, 256, 128, 64, 32, 16, 8, 1):
                candidate: dict[str, Any] = {"success": False}
                if "error" in value:
                    candidate["error"] = error if error_chars is None else error[:error_chars]
                for key in protocol_keys:
                    if key not in value:
                        continue
                    item = value[key]
                    candidate[key] = str(item)[:160] if key in {"request_id", "execution_id"} else item
                if "summary" in value:
                    summary = str(value["summary"])
                    candidate["summary"] = summary if summary_chars is None else summary[:summary_chars]
                if include_optional:
                    for key in (*services_module._CONTEXT_PROTECTED_KEYS, "evidence_id", "evidence_ids", "artifact_id", "artifact_ids"):
                        if key in candidate or key not in value:
                            continue
                        item = value[key]
                        if isinstance(item, (list, tuple)):
                            candidate[key] = [str(part)[:160] for part in item[:8]]
                        elif isinstance(item, (str, int, float, bool)) or item is None:
                            candidate[key] = item[:160] if isinstance(item, str) else item
                for metadata in metadata_variants:
                    trial = dict(candidate)
                    trial["response_budget"] = dict(metadata)
                    for _ in range(16):
                        returned = services_module.json_tokens(services_module._mcp_wire_view(trial, structured=True))
                        trial["response_budget"]["returned_tokens"] = returned
                        if services_module.json_tokens(services_module._mcp_wire_view(trial, structured=True)) == returned:
                            break
                    if services_module.json_tokens(services_module._mcp_wire_view(trial, structured=True)) <= requested:
                        content = [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(trial))]
                        return content, trial
    return None

def _build_mcp_budget_payload(name: str, arguments: dict[str, Any], value: Any) -> Any:
    services_module = _get_services_module()
    if name == "local_ai_coord" and str(arguments.get("action") or "").startswith("task_"):
        value = services_module._task_private_state_projection(value)
    value = services_module._agent_output(value, name, arguments)
    options = {
        "max_response_tokens": arguments.get("max_response_tokens", 0),
        "response_profile": arguments.get("response_profile", ""),
        "reuse_key": arguments.get("reuse_key", ""),
        "tool": name,
    }
    try:
        explicit_limit = int(options["max_response_tokens"] or 0)
    except (TypeError, ValueError, OverflowError):
        explicit_limit = 0
    rejection = services_module._subminimum_budget_rejection(options)
    if rejection is not None:
        requested, profile, reuse_key, enabled = explicit_limit, "minimal", str(options.get("reuse_key") or ""), services_module.RESPONSE_BUDGET_ENABLED
        value = rejection
    else:
        requested, profile, reuse_key, enabled = services_module._response_budget(
            str(arguments.get("action") or name), options
        )
    action = str(arguments.get("action") or "").lower()
    if not enabled:
        return ([services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(value))], value)

    if (name == "local_ai_coord" and action == "plan_task_edit"
            and isinstance(value, dict) and isinstance(value.get("mutation_applied"), bool)
            and isinstance(value.get("plan_id"), str) and value.get("plan_id")
            and isinstance(value.get("task_id"), str) and value.get("task_id")
            and isinstance(value.get("file_revision"), str) and value.get("file_revision")
            and (value.get("projection_incomplete") is True
                 or services_module.json_tokens(services_module._mcp_wire_view(value, structured=True)) > requested)):
        acknowledgement = {
            "success": False,
            "error": "Plan edit response shortened; inspect file_revision before continuing.",
            "terminal": True,
            "retryable": False,
            "mutation_applied": value["mutation_applied"],
            "plan_id": value["plan_id"],
            "task_id": value["task_id"],
            "file_revision": value["file_revision"],
            "response_budget": {
                "requested_tokens": requested,
                "returned_tokens": 0,
                "truncated": True,
            },
        }
        for _ in range(16):
            returned = services_module.json_tokens(services_module._mcp_wire_view(acknowledgement, structured=True))
            acknowledgement["response_budget"]["returned_tokens"] = returned
            finalized = services_module.json_tokens(services_module._mcp_wire_view(acknowledgement, structured=True))
            if finalized == returned and finalized <= requested:
                content = [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(acknowledgement))]
                return content, acknowledgement
        # The action-specific preflight guarantees sufficient room for this
        # acknowledgement before the underlying plan mutation starts.
        return services_module._build_mcp_budget_payload(name, arguments, {
            "success": False,
            "error": "The write acknowledgement exceeds the configured response budget.",
            "terminal": True,
            "retryable": False,
            "operation_not_started": True,
            "mutation_applied": False,
        })

    if name == "local_ai_coord" and str(arguments.get("action") or "").startswith("task_"):
        memory_wire = services_module._mcp_task_memory_wire(value, requested)
        if memory_wire is not None:
            return memory_wire

    if (
        isinstance(value, dict)
        and value.get("success") is False
        and "error" in value
        and ("review_scope_complete" in value or services_module.json_tokens(services_module._mcp_wire_view(value, structured=True)) > requested)
    ):
        bounded_error = services_module._mcp_bounded_error(value, requested)
        if bounded_error is not None:
            return bounded_error

    protected = (
        *services_module._RELIABILITY_PROTECTED_KEYS,
        *(services_module._COORD_PROTECTED_KEYS if name == "local_ai_coord" else ()),
        *(services_module._CONTEXT_PROTECTED_KEYS if action in {"context", "context_compile"} else ()),
        *(services_module._STATUS_PROTECTED_KEYS if name == "local_ai_status" else ()),
    )
    if name == "local_ai_artifact" and action == "source":
        from .source_slice import SOURCE_SLICE_FIELDS
        protected = (*protected, *SOURCE_SLICE_FIELDS)
    if name == "local_ai_repo" and action in {"security_audit", "secret_scan"}:
        protected = (*protected, *services_module._SECURITY_PROTECTED_KEYS)
    if name == "local_ai_repo" and action == "complexity":
        protected = (*protected, *services_module._COMPLEXITY_PROTECTED_KEYS)
    if name == "local_ai_repo" and action == "topology":
        protected = (*protected, *services_module._TOPOLOGY_PROTECTED_KEYS)
    original_tokens = services_module.json_tokens(services_module._mcp_wire_view(value, structured=True))
    raw_efficiency = value.get("token_efficiency") if isinstance(value, dict) else None
    token_metadata = raw_efficiency if isinstance(raw_efficiency, dict) else None

    if name == "local_ai_repo" and action == "code_index" and isinstance(value, dict) \
            and value.get("success") is True and isinstance(value.get("symbols"), list):
        outer_metadata = {
            "requested_tokens": requested,
            "original_tokens": original_tokens,
            "returned_tokens": 0,
            "truncated": original_tokens > requested,
            "reused": bool((value.get("response_budget") or {}).get("reused"))
            if isinstance(value.get("response_budget"), dict) else False,
            "unit": "estimated_tokens",
        }
        for _ in range(16):
            base = dict(value)
            base["response_budget"] = dict(outer_metadata)
            fitted = services_module._code_index_prefix_fitting(
                base, value, value["symbols"], requested, wire_budget=True,
                identity={"root": arguments.get("root"), "query": arguments.get("query")},
            )
            if fitted is None or (value["symbols"] and not fitted.get("symbols")):
                failure = {
                    "success": False, "status_code": 413, "terminal": True,
                    "retryable": False,
                    "error": (
                        "The first complete code-index symbol exceeds the configured MCP response budget."
                        if value["symbols"] else
                        "The code-index response exceeds the configured MCP response budget."
                    ),
                }
                bounded = services_module._mcp_bounded_error(failure, requested)
                if bounded is not None:
                    return bounded
                break
            returned = services_module.json_tokens(services_module._mcp_wire_view(fitted, structured=True))
            fitted["response_budget"]["returned_tokens"] = returned
            fitted["response_budget"]["truncated"] = returned < original_tokens
            accounting = fitted.get("token_efficiency")
            if isinstance(accounting, dict):
                accounting["protocol_tokens_est"] = services_module.tool_request_tokens(name, arguments) + returned
                baseline = accounting.get("baseline_tokens_est")
                if isinstance(baseline, int) and not isinstance(baseline, bool):
                    signed_delta = baseline - returned
                    accounting["token_savings_delta_est"] = signed_delta
                    accounting["avoided_payload_tokens_est"] = max(0, signed_delta)
            finalized = services_module.json_tokens(services_module._mcp_wire_view(fitted, structured=True))
            if finalized == returned and finalized <= requested:
                content = [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(fitted))]
                return content, fitted
            outer_metadata["returned_tokens"] = returned
            if finalized > requested:
                outer_metadata["returned_tokens"] = 0

    relation_page_key = action if action in {"callers", "callees", "implementations"} else None
    if (name == "local_ai_repo" and relation_page_key and isinstance(value, dict)
            and value.get("success") is True and isinstance(value.get(relation_page_key), list)):
        items = value[relation_page_key]
        outer_metadata = {
            "requested_tokens": requested,
            "original_tokens": original_tokens,
            "returned_tokens": 0,
            "truncated": original_tokens > requested,
            "reused": bool((value.get("response_budget") or {}).get("reused"))
            if isinstance(value.get("response_budget"), dict) else False,
            "unit": "estimated_tokens",
        }
        fitted_page = None
        for count in range(len(items), -1, -1):
            candidate = services_module._normalize_deterministic(services_module.account_projection(
                value, services_module._relation_page_with_prefix(value, value, relation_page_key, items, count),
            ))
            candidate["response_budget"] = dict(outer_metadata)
            for _ in range(16):
                returned = services_module.json_tokens(services_module._mcp_wire_view(candidate, structured=True))
                candidate["response_budget"]["returned_tokens"] = returned
                candidate["response_budget"]["truncated"] = returned < original_tokens
                accounting = candidate.get("token_efficiency")
                if isinstance(accounting, dict):
                    accounting["protocol_tokens_est"] = services_module.tool_request_tokens(name, arguments) + returned
                    baseline = accounting.get("baseline_tokens_est")
                    if isinstance(baseline, int) and not isinstance(baseline, bool):
                        signed_delta = baseline - returned
                        accounting["token_savings_delta_est"] = signed_delta
                        accounting["avoided_payload_tokens_est"] = max(0, signed_delta)
                finalized = services_module.json_tokens(services_module._mcp_wire_view(candidate, structured=True))
                if finalized == returned and finalized <= requested:
                    fitted_page = candidate
                    break
                if finalized > requested:
                    break
            if fitted_page is not None:
                break
        if fitted_page is None or (items and not fitted_page.get(relation_page_key)):
            failure = {
                "success": False, "status_code": 413, "terminal": True,
                "retryable": False,
                "error": f"The first complete {relation_page_key[:-1]} result exceeds the configured MCP response budget.",
            }
            bounded = services_module._mcp_bounded_error(failure, requested)
            if bounded is not None:
                return bounded
            minimal_failure = {
                "success": False, "status_code": 413, "terminal": True,
                "retryable": False, "error": "response budget exceeded",
            }
            return [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(minimal_failure))], None
        else:
            content = [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(fitted_page))]
            return content, fitted_page

    if (name == "local_ai_repo" and action == "search" and isinstance(value, dict)
            and value.get("success") is True and isinstance(value.get("results"), list)):
        items = value["results"]
        outer_metadata = {
            "requested_tokens": requested,
            "original_tokens": original_tokens,
            "returned_tokens": 0,
            "truncated": original_tokens > requested,
            "reused": bool((value.get("response_budget") or {}).get("reused"))
            if isinstance(value.get("response_budget"), dict) else False,
            "unit": "estimated_tokens",
        }
        for _ in range(16):
            base = dict(value)
            base["response_budget"] = dict(outer_metadata)
            fitted = services_module._search_prefix_fitting(
                base, value, items, requested, wire_budget=True,
            )
            if fitted is None or (items and not fitted.get("results")):
                failure = {
                    "success": False, "status_code": 413, "terminal": True,
                    "retryable": False,
                    "error": "No complete search result fits the requested response budget; omit max_response_tokens or use a larger cap.",
                    "root": value.get("root"),
                    "offset": value.get("offset", 0),
                    "limit": value.get("limit", 24),
                    "total_matches": value.get("total_matches", 0),
                    "has_more": value.get("has_more", False),
                    "results": [],
                }
                bounded = services_module._mcp_bounded_error(failure, requested)
                if bounded is not None:
                    return bounded
                break
            returned = services_module.json_tokens(services_module._mcp_wire_view(fitted, structured=True))
            fitted["response_budget"]["returned_tokens"] = returned
            fitted["response_budget"]["truncated"] = returned < original_tokens
            accounting = fitted.get("token_efficiency")
            if isinstance(accounting, dict):
                accounting["protocol_tokens_est"] = services_module.tool_request_tokens(name, arguments) + returned
                baseline = accounting.get("baseline_tokens_est")
                if isinstance(baseline, int) and not isinstance(baseline, bool):
                    signed_delta = baseline - returned
                    accounting["token_savings_delta_est"] = signed_delta
                    accounting["avoided_payload_tokens_est"] = max(0, signed_delta)
            finalized = services_module.json_tokens(services_module._mcp_wire_view(fitted, structured=True))
            if finalized == returned and finalized <= requested:
                content = [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(fitted))]
                return content, fitted
            outer_metadata["returned_tokens"] = returned
            if finalized > requested:
                outer_metadata["returned_tokens"] = 0

    if action in {"context", "context_compile"} and requested <= 128 and isinstance(value, dict):
        pack = value.get("adaptive_context_pack")
        evidence = pack.get("evidence") if isinstance(pack, dict) else None
        file_line_items = [
            item for item in evidence
            if isinstance(item, dict) and any(key in item for key in ("path", "start_line", "end_line"))
        ] if isinstance(evidence, list) else []
        if file_line_items:
            compact_pack = {
                key: pack[key] for key in ("context_id", "repo_revision", "stale") if key in pack
            }
            compact_pack["evidence"] = [
                {key: item[key] for key in ("evidence_id", "path", "start_line", "end_line", "source") if key in item}
                for item in file_line_items[:1]
            ]
            compact_value = {
                key: value[key] for key in ("success",) if key in value
            }
            compact_value["adaptive_context_pack"] = compact_pack
            compact_value["response_budget"] = {
                "requested_tokens": requested, "original_tokens": original_tokens,
                "returned_tokens": 0, "truncated": True, "unit": "estimated_tokens",
            }
            for structured in (True, False):
                for _ in range(16):
                    returned = services_module.json_tokens(services_module._mcp_wire_view(compact_value, structured=structured))
                    compact_value["response_budget"]["returned_tokens"] = returned
                    finalized = services_module.json_tokens(services_module._mcp_wire_view(compact_value, structured=structured))
                    if finalized == returned and finalized <= requested:
                        content = [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(compact_value))]
                        return content, compact_value if structured else None

    inner_limits = list(dict.fromkeys((requested, max(64, requested - 32), max(64, requested // 2), 64)))
    for inner_limit in inner_limits:
        candidate = services_module.budget_response(
            services_module.copy.deepcopy(value),
            max_tokens=inner_limit,
            profile=profile,
            reuse_key=reuse_key,
            protected_keys=protected,
            token_metadata=token_metadata,
            evidence_store=None,
        )
        if name == "local_ai_artifact" and action == "source" and isinstance(value, dict) and value.get("success") is True:
            if isinstance(candidate, dict) and candidate.get("success") is True and any(candidate.get(key) != value.get(key) for key in SOURCE_SLICE_FIELDS):
                candidate = {
                    "success": False, "status_code": 413, "terminal": True, "retryable": False,
                    "error": "Exact source slice exceeds response budget; increase max_response_tokens or reduce the range/max_chars",
                }
        if isinstance(candidate, dict):
            previous_meta = candidate.get("response_budget")
            previous_meta = previous_meta if isinstance(previous_meta, dict) else {}
            candidate["response_budget"] = {
                "requested_tokens": requested,
                "original_tokens": previous_meta.get("original_tokens", original_tokens),
                "returned_tokens": 0,
                "truncated": previous_meta.get("truncated", original_tokens > requested),
                "reused": bool(previous_meta.get("reused")),
                "unit": "estimated_tokens",
                **({"rejected": True} if previous_meta.get("rejected") else {}),
            }
        for _ in range(16):
            returned_tokens = services_module.json_tokens(services_module._mcp_wire_view(candidate, structured=True))
            if isinstance(candidate, dict):
                accounting = candidate.get("token_efficiency")
                if isinstance(accounting, dict):
                    accounting["protocol_tokens_est"] = services_module.tool_request_tokens(name, arguments) + returned_tokens
                    baseline = accounting.get("baseline_tokens_est")
                    if isinstance(baseline, int) and not isinstance(baseline, bool):
                        signed_delta = baseline - returned_tokens
                        accounting["token_savings_delta_est"] = signed_delta
                        accounting["avoided_payload_tokens_est"] = max(0, signed_delta)
                candidate["response_budget"]["returned_tokens"] = returned_tokens
                candidate["response_budget"]["truncated"] = bool(previous_meta.get("truncated")) or returned_tokens < original_tokens
                if previous_meta.get("rejected"):
                    candidate["response_budget"]["rejected"] = True
            finalized = services_module.json_tokens(services_module._mcp_wire_view(candidate, structured=True))
            if finalized == returned_tokens and finalized <= requested:
                content = [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(candidate))]
                return content, candidate
            budget_meta = candidate.get("response_budget") if isinstance(candidate, dict) else None
            if (
                finalized > requested
                and isinstance(budget_meta, dict)
                and budget_meta.get("reused") is False
            ):
                budget_meta.pop("reused", None)

    # The normal compactor has a 64-token floor. At the smallest transport
    # budgets, build a tighter protected rejection so MCP's required
    # structured result still fits its actual CallToolResult envelope.
    for inner_limit in dict.fromkeys((max(32, requested // 3), max(24, requested // 4), 16, 8)):
        rejection_value = services_module._budget_rejection(
            requested=inner_limit,
            original=original_tokens,
            source=value,
            protected_keys=tuple(dict.fromkeys(("error", "evidence_id", "evidence_ids", *services_module._CONTEXT_PROTECTED_KEYS, *protected))),
        )
        metadata_variants = (
            {
                "requested_tokens": requested, "original_tokens": original_tokens,
                "returned_tokens": 0, "truncated": True, "rejected": True,
                "unit": "estimated_tokens",
            },
            {"requested_tokens": requested, "returned_tokens": 0, "unit": "estimated_tokens", "rejected": True},
            {"requested_tokens": requested, "returned_tokens": 0},
            {"returned_tokens": 0, "unit": "est"},
            {"returned_tokens": 0},
            {},
        )
        for metadata in metadata_variants:
            candidate = services_module.copy.deepcopy(rejection_value)
            if metadata:
                candidate["response_budget"] = dict(metadata)
            else:
                candidate.pop("response_budget", None)
            for _ in range(16):
                wire = services_module._mcp_wire_view(candidate, structured=True)
                returned_tokens = services_module.json_tokens(wire)
                if isinstance(candidate.get("response_budget"), dict):
                    candidate["response_budget"]["returned_tokens"] = returned_tokens
                finalized = services_module.json_tokens(services_module._mcp_wire_view(candidate, structured=True))
                if finalized == returned_tokens and finalized <= requested:
                    content = [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(candidate))]
                    return content, candidate

    # A tiny deterministic error is safer than exposing an over-budget MCP
    # result or claiming a payload was retained when it was not.
    fallback: dict[str, Any] = {"success": False, "error": "tool response exceeds response budget"}
    if isinstance(value, dict):
        ids = value.get("evidence_ids")
        if isinstance(ids, (list, tuple)) and ids:
            fallback["evidence_ids"] = [str(ids[0])[:160]]
        elif value.get("evidence_id"):
            fallback["evidence_id"] = str(value["evidence_id"])[:160]
    fallback["response_budget"] = {
        "requested_tokens": requested,
        "original_tokens": original_tokens,
        "returned_tokens": 0,
        "truncated": True,
        "rejected": True,
        "unit": "estimated_tokens",
    }
    for _ in range(16):
        returned_tokens = services_module.json_tokens(services_module._mcp_wire_view(fallback, structured=True))
        fallback["response_budget"]["returned_tokens"] = returned_tokens
        finalized = services_module.json_tokens(services_module._mcp_wire_view(fallback, structured=True))
        if finalized == returned_tokens and finalized <= requested:
            content = [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(fallback))]
            return content, fallback
    minimal = {
        "success": False, "error": "budget",
        "response_budget": {"requested_tokens": requested, "returned_tokens": 0},
    }
    for structured in (True, False):
        for _ in range(16):
            returned_tokens = services_module.json_tokens(services_module._mcp_wire_view(minimal, structured=structured))
            minimal["response_budget"]["returned_tokens"] = returned_tokens
            finalized = services_module.json_tokens(services_module._mcp_wire_view(minimal, structured=structured))
            if finalized == returned_tokens and finalized <= requested:
                content = [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(minimal))]
                return content, minimal if structured else None
    return [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(minimal))], None

def _mcp_budget_payload(name: str, arguments: dict[str, Any], value: Any) -> Any:
    """Project again after pagination/accounting and measure the exact wire."""
    services_module = _get_services_module()
    def batch_recovery_wire(source: dict[str, Any]) -> Any:
        artifact_id = source.get("output_artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id or source.get("request_not_sent") is True:
            return None
        requested, _, _, enabled = services_module._response_budget("batch", {
            "max_response_tokens": arguments.get("max_response_tokens", 0),
            "response_profile": arguments.get("response_profile", ""),
            "reuse_key": arguments.get("reuse_key", ""), "tool": name,
        })
        if not enabled:
            return None
        recover = {"success": False, "error": "batch result truncated", "outcome_unknown": True,
                   "output_artifact_id": artifact_id}
        if isinstance(source.get("request_id"), str):
            recover["request_id"] = source["request_id"]
        recover["response_budget"] = {"requested_tokens": requested, "returned_tokens": 0, "truncated": True}
        text_value = {"outcome_unknown": True, "output_artifact_id": artifact_id}
        content = [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(text_value))]
        wire = {"content": [item.model_dump(mode="json", exclude_none=True) for item in content],
                "structuredContent": recover, "isError": False}
        for _ in range(16):
            actual = services_module.json_tokens(wire)
            recover["response_budget"]["returned_tokens"] = actual
            if services_module.json_tokens(wire) == actual:
                break
        return (content, recover) if services_module.json_tokens(wire) <= requested else None

    if (name == "local_ai_task" and arguments.get("action") == "batch"
            and isinstance(value, dict) and value.get("outcome_unknown") is True):
        recovery = batch_recovery_wire(value)
        if recovery is not None:
            return recovery
    contents, structured = services_module._build_mcp_budget_payload(name, arguments, value)
    if (name == "local_ai_coord" and arguments.get("action") == "wait_for_event"
            and isinstance(value, dict) and value.get("success") is True):
        try:
            text_value = services_module.json.loads(next(item.text for item in contents if item.type == "text"))
        except (StopIteration, ValueError, TypeError):
            text_value = None
        expected = {key: value[key] for key in ("message", "event") if key in value}
        def exact_wait_payload(candidate: Any) -> bool:
            return isinstance(candidate, dict) and all(
                key in candidate and services_module.json.dumps(candidate[key], sort_keys=True, separators=(",", ":"))
                == services_module.json.dumps(item, sort_keys=True, separators=(",", ":"))
                for key, item in expected.items()
            )
        if not exact_wait_payload(structured) or not exact_wait_payload(text_value):
            rejection = {"success": False, "status_code": 413, "terminal": True, "retryable": False,
                         "error": "Event exceeds response budget; increase max_response_tokens"}
            return services_module._build_mcp_budget_payload(name, arguments, rejection)
    if (name == "local_ai_coord" and arguments.get("action") == "pubsub_poll"
            and isinstance(value, dict) and value.get("success") is True
            and isinstance(value.get("messages"), list)):
        try:
            text_value = services_module.json.loads(next(item.text for item in contents if item.type == "text"))
        except (StopIteration, ValueError, TypeError):
            text_value = None
        expected_messages = services_module.json.dumps(value["messages"], sort_keys=True, separators=(",", ":"))
        if (not isinstance(structured, dict)
                or services_module.json.dumps(structured.get("messages"), sort_keys=True, separators=(",", ":")) != expected_messages
                or not isinstance(text_value, dict)
                or services_module.json.dumps(text_value.get("messages"), sort_keys=True, separators=(",", ":")) != expected_messages):
            rejection = {"success": False, "status_code": 413, "terminal": True, "retryable": False,
                         "error": "Pubsub messages exceed response budget; reduce limit or increase max_response_tokens"}
            return services_module._build_mcp_budget_payload(name, arguments, rejection)
    if (name == "local_ai_artifact" and arguments.get("action") == "get"
            and isinstance(value, dict) and value.get("success") is True
            and isinstance(value.get("text"), str)
            and (not isinstance(structured, dict)
                 or any(structured.get(key) != value.get(key) for key in ("text", "offset", "next_offset")))):
        rejection = {"success": False, "status_code": 413, "terminal": True, "retryable": False,
                     "error": "Reduce max_chars or increase max_response_tokens: artifact page exceeds response budget",
                     "artifact_id": value.get("artifact_id", "")}
        return services_module._build_mcp_budget_payload(name, arguments, rejection)
    if name == "local_ai_task" and arguments.get("action") == "batch" and isinstance(value, dict):
        original_items = value.get("results")
        returned_items = structured.get("results") if isinstance(structured, dict) else None
        if isinstance(original_items, list):
            items_retained = services_module._batch_items_retained(original_items, returned_items)
            if not items_retained:
                rejection = {"success": False, "error": "batch result unavailable in bounded response"}
                if value.get("request_not_sent") is True:
                    rejection["request_not_sent"] = True
                else:
                    rejection["outcome_unknown"] = True
                if isinstance(value.get("request_id"), str):
                    rejection["request_id"] = value["request_id"]
                if isinstance(value.get("output_artifact_id"), str):
                    rejection["output_artifact_id"] = value["output_artifact_id"]
                recovery = batch_recovery_wire(rejection)
                if recovery is not None:
                    return recovery
                requested, _, _, _ = services_module._response_budget("batch", {
                    "max_response_tokens": arguments.get("max_response_tokens", 0),
                    "response_profile": arguments.get("response_profile", ""),
                    "reuse_key": arguments.get("reuse_key", ""), "tool": name,
                })
                bounded = services_module._mcp_bounded_error(rejection, requested)
                return bounded if bounded is not None else services_module._build_mcp_budget_payload(name, arguments, rejection)
    if not isinstance(structured, dict):
        return contents, structured
    projector = (services_module.project_pubsub_poll_response if name == "local_ai_coord" and arguments.get("action") == "pubsub_poll"
                 else services_module.project_wait_event_response if name == "local_ai_coord" and arguments.get("action") == "wait_for_event"
                 else services_module.project_agent_response)
    detail_checker = getattr(services_module, "agent_diagnostics_enabled", None)
    detail_enabled = detail_checker(services_module.CFG, arguments) if detail_checker else False
    # Full telemetry capture is internal. It must not enable diagnostics on
    # ordinary MCP responses; only explicit agent-output diagnostics do that.
    safe = projector(structured, enabled=detail_enabled, extra_fields=arguments.get("extra_fields"))
    if safe == structured:
        return contents, structured
    try:
        mirror = len(contents) == 1 and services_module.json.loads(contents[0].text) == structured
    except (ValueError, AttributeError):
        mirror = False
    # Task-memory responses can have a short human-readable text companion.
    # Keep that companion; JSON mirrors must match the structured result.
    budget = safe.get("response_budget")
    for _ in range(16):
        if mirror:
            contents = [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(safe))]
        wire = {
            "content": [item.model_dump(mode="json", exclude_none=True) for item in contents],
            "structuredContent": safe, "isError": False,
        }
        returned = services_module.json_tokens(wire)
        if isinstance(budget, dict):
            budget["returned_tokens"] = returned
        accounting = safe.get("token_efficiency")
        if isinstance(accounting, dict):
            accounting["protocol_tokens_est"] = services_module.tool_request_tokens(name, arguments) + returned
            baseline = accounting.get("baseline_tokens_est")
            if isinstance(baseline, int) and not isinstance(baseline, bool):
                accounting["token_savings_delta_est"] = baseline - returned
                accounting["avoided_payload_tokens_est"] = max(0, baseline - returned)
        if mirror:
            contents = [services_module.mcp_types.TextContent(type="text", text=services_module.json_dumps(safe))]
        wire["content"] = [item.model_dump(mode="json", exclude_none=True) for item in contents]
        if services_module.json_tokens(wire) == returned:
            break
    return contents, safe

async def _compact_mcp_call_tool(name: str, arguments: dict[str, Any]) -> Any:
    services_module = _get_services_module()
    call_started = time.monotonic()
    arguments = dict(arguments)
    # Strip whitespace from string arguments to prevent random rejection on trailing spaces
    for k, v in list(arguments.items()):
        if isinstance(v, str):
            arguments[k] = v.strip()
    # Resolve relative roots gracefully to avoid artificial 'must be absolute' rejections
    if "root" in arguments and isinstance(arguments["root"], str):
        r = arguments["root"]
        if r in {".", "", "./", ".\\"} or (not Path(r).is_absolute() and not PureWindowsPath(r).is_absolute()):
            try:
                arguments["root"] = str(Path(r).resolve())
            except Exception:
                pass
    if name == "local_ai_coord":
        coord_action = str(arguments.get("action") or "").lower()
        if coord_action in {"task_view", "task_status", "task_info", "task_show", "view"}:
            coord_action = "task_get"
        elif coord_action in {"plan_view", "board_view"}:
            coord_action = "plan_board_view"
        elif coord_action in {"tasks", "task_all"}:
            coord_action = "task_list"
        arguments["action"] = coord_action
        owner_global_actions = {
            "gpu_reservation_status",
            "gpu_reservation_release",
            "gpu_reservation_release_authorized",
            "gpu_capacity_lease_release",
            "gpu_scheduler_capacity_lease_release",
        }
        if coord_action in owner_global_actions:
            # Global GPU operations reject a repository root attached by some MCP hosts.
            arguments.pop("root", None)
        else:
            coord_contract = services_module.operation_contract("local_ai_coord") or {}
            action_contract = coord_contract.get("actions", {}).get(coord_action, {})
            if not arguments.get("root") and "root" in action_contract.get("required", ()):
                arguments["root"] = str(Path(".").resolve())
        if arguments.get("action") == "memory_record":
            if not arguments.get("scope"):
                arguments["scope"] = "repository"
    elif name == "local_ai_repo":
        if not arguments.get("root"):
            arguments["root"] = str(Path(".").resolve())

    if (name == "local_ai_coord" and str(arguments.get("action") or "").startswith("plan_")
            and "acceptance_criteria" not in services_module.operation_contract("local_ai_coord")["actions"].get(
                arguments.get("action"), {}).get("allowed", ())):
        # MCP hosts can append the active task's acceptance criteria to
        # every call. Keep them when the plan action explicitly accepts them.
        arguments.pop("acceptance_criteria", None)
    pending_accounting: list[dict[str, Any]] = []
    pending_token = services_module._PENDING_MCP_ACCOUNTING.set(pending_accounting)
    call_token = services_module._CURRENT_MCP_CALL_ARGUMENTS.set((name, dict(arguments)))

    def finalize(result: Any, *, account_unwrapped_error: bool = False) -> Any:
        if not isinstance(result, tuple) or len(result) != 2:
            return result
        contents, structured_value = result
        active_adapter = services_module.ClientRegistry.get(agent_header=services_module.os.environ.get("LOCAL_AI_AGENT"))
        if active_adapter.capabilities.prompt_cache_shield:
            if structured_value is not None:
                structured_value = active_adapter.normalize_for_cache(structured_value)
            elif contents and hasattr(contents[0], "text"):
                try:
                    parsed = services_module.json.loads(contents[0].text)
                    norm_text = services_module.json_dumps(active_adapter.normalize_for_cache(parsed))
                    contents = [services_module.mcp_types.TextContent(type="text", text=norm_text)]
                except Exception:
                    pass
        if structured_value is None:
            text_value = contents[0].text
            try:
                candidate_value = services_module.json.loads(text_value)
            except Exception:
                candidate_value = {}
            emitted_response = {"content": [{"type": "text", "text": text_value}], "structuredContent": candidate_value}
            result = (contents, candidate_value)
        else:
            candidate_value = structured_value
            result = (contents, candidate_value)
            if name == "local_ai_coord" and str(arguments.get("action") or "").startswith("task_"):
                emitted_response = {
                    "content": [{"type": "text", "text": item.text} for item in contents],
                    "structuredContent": candidate_value, "isError": False,
                }
            else:
                emitted_response = services_module._mcp_wire_view(candidate_value, structured=True)
        emitted_tokens = services_module.json_tokens(emitted_response)
        for item in pending_accounting:
            measured = dict(item["measured"])
            raw_tokens = max(0, int(measured.get("raw_response_tokens_est", 0) or 0))
            input_saved = max(0, int(measured.get("gross_input_tokens_avoided_est", 0) or 0))
            measured["projected_response_tokens_est"] = emitted_tokens
            if raw_tokens:
                output_saved = max(0, raw_tokens - emitted_tokens)
                measured["gross_output_tokens_avoided_est"] = output_saved
                measured["output_savings_source"] = "response_compaction" if output_saved else ""
                if input_saved:
                    measured["gross_cloud_tokens_avoided_est"] = input_saved
                    source_name = str(measured.get("input_savings_source", ""))
                    measured["savings_breakdown"] = {source_name: input_saved} if source_name else {}
                else:
                    measured["gross_cloud_tokens_avoided_est"] = output_saved
                    measured["savings_breakdown"] = {"response_compaction": output_saved} if output_saved else {}
            metadata = dict(item["metadata"])
            metadata["protocol_tokens_est"] = services_module.tool_request_tokens(name, arguments) + emitted_tokens
            item_response = item["response"]
            services_module._record_tool_accounting(
                tool_name=item["tool_name"], arguments=item["arguments"], response=emitted_response,
                measured=measured, metadata=metadata,
                event_id=item.get("event_id", ""), duration_ms=item.get("duration_ms", 0.0),
                call_success=item.get("call_success"),
                result_id_value=item_response["result_id"] if isinstance(item_response, dict) and "result_id" in item_response else "",
            )
        if not pending_accounting:
            services_module._record_tool_accounting(
                tool_name=name, arguments=arguments, response=emitted_response, measured={},
                metadata={"protocol_tokens_est": services_module.tool_request_tokens(name, arguments) + emitted_tokens},
                event_id=services_module.uuid.uuid4().hex,
                duration_ms=(services_module.time.monotonic() - call_started) * 1000,
                call_success=isinstance(candidate_value, dict) and candidate_value.get("success") is True,
            )
        return result

    try:
        selector = "detail" if name == "local_ai_status" else "action"
        validation_arguments = dict(arguments)
        validation = services_module.validate_operation_call(name, validation_arguments, features=services_module.FEATURES)
        if validation is not None:
            status_code, error = validation
            if "expected one of " in error and error.count(",") > 8:
                import difflib
                supplied_act = str(validation_arguments.get(selector, ""))
                available = [x.strip() for x in error.split("expected one of ", 1)[1].split(",")]
                matches = difflib.get_close_matches(supplied_act, available, n=3, cutoff=0.4)
                if matches:
                    error = f"invalid action {supplied_act!r} for {name}; did you mean: {', '.join(matches)}?"
                else:
                    error = f"invalid action {supplied_act!r} for {name}; choose from {len(available)} registered actions (e.g. {', '.join(available[:5])}, ...)"
            from .operation_contracts import operation_argument_hint
            hint = operation_argument_hint(name, validation_arguments.get(selector, ""), services_module.FEATURES) if status_code == 400 else {}
            if hint and "allowed_arguments" in hint:
                import difflib
                unknown_keys = [k for k in validation_arguments if k not in hint["allowed_arguments"] and k != selector]
                if unknown_keys:
                    matches = difflib.get_close_matches(unknown_keys[0], hint["allowed_arguments"], n=1, cutoff=0.55)
                    if matches:
                        hint["suggestion"] = f"Did you mean '{matches[0]}'?" 
            payload = {
                "success": False, "status_code": status_code,
                "terminal": True, "retryable": False, "error": error,
                **({"unsupported": True} if status_code == 403 and "disabled" in error.casefold() else {}),
                **({"argument_help": hint} if hint else {}),
            }
            return finalize(services_module._mcp_budget_payload(name, arguments, payload), account_unwrapped_error=True)
        raw = None
        for attempt in range(3):
            try:
                tool_obj = services_module.mcp._tool_manager.get_tool(name) if hasattr(services_module.mcp, "_tool_manager") else None
                if tool_obj is None and name in services_module._ALL_REGISTERED_TOOLS:
                    tool_obj = services_module._ALL_REGISTERED_TOOLS[name]
                if tool_obj is not None:
                    raw = await tool_obj.run(arguments, convert_result=False)
                else:
                    raw = await services_module.mcp._tool_manager.call_tool(name, arguments, convert_result=False)
                break
            except Exception as exc:
                err_msg = str(exc).lower()
                is_transient = (
                    "locked" in err_msg
                    or "busy" in err_msg
                    or isinstance(exc, (ConnectionResetError, TimeoutError))
                )
                if is_transient and attempt < 2:
                    import asyncio
                    await asyncio.sleep(0.15 * (attempt + 1))
                    continue
                text = str(exc).strip().splitlines()[0][:500] if str(exc).strip() else type(exc).__name__
                is_val_err = type(exc).__name__ == "ValidationError"
                payload = {
                    "success": False,
                    "status_code": 400 if is_val_err else 500,
                    "terminal": not is_transient,
                    "retryable": is_transient,
                    "error": f"MCP input validation failed: {text}" if is_val_err else f"MCP tool failed: {text}",
                }
                return finalize(services_module._mcp_budget_payload(name, arguments, payload), account_unwrapped_error=True)
        selector = "detail" if name == "local_ai_status" else "action"
        action = arguments.get(selector)
        if not isinstance(action, str) or action not in services_module.operation_actions(name, services_module.FEATURES):
            available_actions = services_module.operation_actions(name, services_module.FEATURES)
            action = available_actions[0] if available_actions else ""
        output_error = services_module.validate_operation_output(name, action, raw)
        if output_error is not None:
            payload = {
                "success": False, "status_code": 500,
                "terminal": True, "retryable": False,
                "error": f"MCP output contract failed: {output_error}",
            }
            # Keep validated correlation metadata for diagnostic-mode callers.
            # Do not echo malformed output or fabricate a request identity.
            request_id = raw.get("request_id") if isinstance(raw, dict) else None
            if isinstance(request_id, str) and 0 < len(request_id) <= 200 and not any(
                ord(char) < 32 or ord(char) == 127 for char in request_id
            ):
                payload["request_id"] = request_id
            return finalize(services_module._mcp_budget_payload(name, arguments, payload), account_unwrapped_error=True)
        if isinstance(raw, (dict, list)):
            return finalize(services_module._mcp_budget_payload(name, arguments, raw))
        if isinstance(raw, str):
            return finalize(services_module._mcp_budget_payload(name, arguments, {"text": raw}))
        return finalize(services_module._mcp_budget_payload(name, arguments, {
            "success": False, "status_code": 500, "terminal": True,
            "retryable": False, "error": "MCP tool returned unsupported result type",
        }), account_unwrapped_error=True)
    finally:
        services_module._CURRENT_MCP_CALL_ARGUMENTS.reset(call_token)
        services_module._PENDING_MCP_ACCOUNTING.reset(pending_token)
