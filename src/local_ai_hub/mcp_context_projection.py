from __future__ import annotations

from typing import Any


def _context_pack_projection(value: Any, *, extra_fields: list[str] | None = None) -> Any:
    from . import mcp_server as services_module
    if not isinstance(value, dict):
        return {"success": False, "status_code": 502, "terminal": True, "retryable": True, "error": "context pack response must be a JSON object"}
    options = services_module._CURRENT_RESPONSE_OPTIONS.get()
    from .context_delivery import prepare_context_delivery
    requested_context_budget, _, _, _ = services_module._response_budget("context", options)
    value = prepare_context_delivery(value, requested_context_budget)
    rejection = services_module._subminimum_budget_rejection(options)
    if rejection is not None:
        return rejection
    safe_value = services_module._guarded_context_input(value, extra_fields=extra_fields) if (
        bool(value.get("guarded")) or "adaptive_context_pack" in value or "context_pack" in value
    ) else value
    projected = services_module._compact(safe_value, "context", extra_fields=extra_fields)
    if not isinstance(projected, dict):
        return projected
    if projected.get("error") == services_module._CONTEXT_DELTA_BUDGET_ERROR:
        return projected
    expected_context_delta = services_module.copy.deepcopy(projected.get("delta")) if isinstance(projected.get("delta"), dict) else None

    # Guard output is deterministic. Reattach its decision-grade fields after the
    # generic response budget so model/postprocess fields cannot replace them.
    pack = safe_value.get("adaptive_context_pack") or safe_value.get("context_pack")
    pack = pack if isinstance(pack, dict) else {}
    pack_key = "adaptive_context_pack" if isinstance(safe_value.get("adaptive_context_pack"), dict) else "context_pack"
    authoritative: dict[str, Any] = {}
    for key in (
        "context_id", "task_context_artifact_id", "task_id", "next_action", "warnings", "repo_revision", "changed_paths", "stale",
        "delta_from", "since_hash", "unchanged", "reuse_pointer",
    ):
        if key == "unchanged" and options.get("response_profile") == "delta" and projected.get("unchanged") is True:
            continue
        if key in pack:
            authoritative[key] = pack[key]
        elif key in safe_value:
            authoritative[key] = safe_value[key]
    evidence = pack.get("evidence")
    if isinstance(evidence, list):
        ids = list(dict.fromkeys(
            item.get("evidence_id") for item in evidence
            if isinstance(item, dict) and item.get("evidence_id")
        ))
        authoritative["evidence_ids"] = ids[:24]
    if "evidence_ids" not in authoritative:
        if "evidence_ids" in pack:
            authoritative["evidence_ids"] = pack["evidence_ids"]
        elif "evidence_ids" in safe_value:
            authoritative["evidence_ids"] = safe_value["evidence_ids"]
    nested_pack_fields = (
        "success", "status", "status_code", "terminal", "retryable", "error", "warning", "message",
        "degraded", "stale", "fallback_used", "requires_override", "requires_approval",
        "decision_recorded", "decision_persisted", "task_status", "waiting", "context_id", "evidence_ids",
    )
    carries_nested_decision = any(
        key in pack
        for key in ("success", "status", "status_code", "terminal", "retryable", "error", "degraded", "fallback_used")
    )
    nested_pack = (
        {key: services_module._bound_context_json(pack[key]) for key in nested_pack_fields if key in pack}
        if carries_nested_decision else {}
    )
    for key in ("error", "warning", "message"):
        if isinstance(nested_pack.get(key), str):
            nested_pack[key] = nested_pack[key][:192]
    if nested_pack and isinstance(pack.get("evidence"), list):
        nested_pack["evidence"] = [
            {
                key: services_module._bound_context_json(item[key])
                for key in ("evidence_id", "source")
                if key in item
            }
            for item in pack["evidence"]
            if isinstance(item, dict)
        ][:24]
    if nested_pack:
        prior_pack = projected.get(pack_key)
        merged_pack = dict(prior_pack) if isinstance(prior_pack, dict) else {}
        merged_pack.update(nested_pack)
        authoritative[pack_key] = merged_pack
    for key in (
        "revision", "guarded", "delivery_mode", "since_hash", "delta_from", "degraded", "stale",
        "fallback_used", "requires_override", "requires_approval", "decision_recorded",
        "decision_persisted", "task_status", "waiting",
    ):
        if key in safe_value and key not in authoritative:
            authoritative[key] = safe_value[key]
    # Preserve actual deterministic context, not only its provenance pointer.
    # Without this, the final budget pass could return IDs/status while silently
    # dropping the context text needed by the next bounded agent step.
    for key in ("context", "query", "context_source", "estimated_tokens", "contract", "retrieval"):
        if key == "context" and options.get("response_profile") == "delta" and expected_context_delta is not None:
            continue
        if key in safe_value and key not in authoritative:
            authoritative[key] = safe_value[key]
    for key, item in authoritative.items():
        projected[key] = services_module._bound_context_json(item)

    # Authoritative fields were attached after _compact's response budget. Run
    # the final projection through the same bounds so they cannot bypass it.
    final = services_module.compact_result(
        projected,
        max_text_chars=services_module.MAX_TEXT,
        max_evidence=services_module.MAX_EVIDENCE,
        extra_fields=extra_fields,
    )
    if isinstance(final, dict) and ("adaptive_context_pack" in safe_value or "context_pack" in safe_value or safe_value.get("guarded")):
        pack_key = "adaptive_context_pack" if "adaptive_context_pack" in final else "context_pack"
        context_pack = final.get(pack_key)
        if isinstance(context_pack, dict) and isinstance(context_pack.get("evidence"), list):
            context_pack = dict(context_pack)
            context_pack["evidence"] = [
                {key: item[key] for key in ("evidence_id", "path", "start_line", "end_line", "source") if key in item}
                for item in context_pack["evidence"][:24]
                if isinstance(item, dict)
            ]
            final[pack_key] = context_pack
        final["provenance"] = services_module.evidence_meta(
            "repo.context",
            str(authoritative.get("repo_revision", safe_value.get("repo_revision", ""))),
            authoritative.get("evidence_ids", []),
            bool(authoritative.get("stale", safe_value.get("stale", False))),
            "stale" if bool(authoritative.get("stale", safe_value.get("stale", False))) else ("success" if safe_value.get("success", True) else "incomplete"),
        )
    options = services_module._CURRENT_RESPONSE_OPTIONS.get()
    requested, profile, reuse_key, enabled = services_module._response_budget("context", options)
    if enabled:
        protected_context_keys = (
            "success", "context_id", "repo_revision", "evidence_ids",
            "adaptive_context_pack" if "adaptive_context_pack" in final else "context_pack",
        )
        protected_context_keys += tuple(
            key for key in (
                "complete", "partial", "task_context", "task_context_artifact_id", "task_id", "next_action", "etag", "omitted_sections",
                "stop_code", "degraded_reason", "context_truncated", "context_chars",
                "requires_override", "requires_approval", "decision_recorded", "delta",
                "decision_persisted", "task_status", "waiting", "unchanged", "reuse_pointer",
            ) if key in final
        )
        if requested >= 256:
            protected_context_keys += tuple(
                key for key in (
                    "changed_paths", "stale", "delta_from", "since_hash", "warnings", "degraded",
                    "fallback_used",
                ) if key in final
            )
        elif requested <= 160:
            protected_context_keys += tuple(
                key for key in ("stale", "warnings", "delta_from", "since_hash") if key in final
            )
        if requested >= 512:
            protected_context_keys += tuple(
                key for key in ("contract", "provenance") if key in final
            )
        protected_context_keys = tuple(
            key for key in protected_context_keys if key in final
        )
        # Match the token count to the exact key order returned to the MCP
        # serializer. Sorting after budgeting can change tokenization.
        final = services_module._normalize_deterministic(final)
        final = services_module.budget_response(
            final,
            max_tokens=requested,
            profile=profile,
            reuse_key=reuse_key,
            protected_keys=protected_context_keys,
            token_metadata=services_module.efficiency_metadata(),
        )
        if expected_context_delta is not None and (
            not isinstance(final, dict) or final.get("delta") != expected_context_delta
        ):
            return services_module._context_delta_budget_error(safe_value, requested, reuse_key)
        budget_meta = final.get("response_budget") if isinstance(final, dict) else None
        if isinstance(budget_meta, dict) and "returned_tokens" in budget_meta:
            budget_meta["returned_tokens"] = services_module.json_tokens(final)
            if services_module.json_tokens(final) > requested:
                return services_module._context_input_error("response budget metadata exceeds max_response_tokens")
        pointer = safe_value.get("task_context_artifact_id")
        if isinstance(pointer, str) and final.get("task_context_artifact_id") != pointer:
            recovery = {
                "success": False, "complete": False, "partial": True,
                "error": "compiled context requires artifact retrieval",
                "next_action": "read_task_context_artifact",
                "task_context_artifact_id": pointer,
            }
            if services_module.json_tokens(recovery) <= requested:
                return recovery
            return {
                "success": False, "error": "max_response_tokens too small",
                "next_action": "request_larger_response_budget",
                "response_budget": {"requested_tokens": requested, "returned_tokens": 0, "rejected": True},
            }
        return final
    return services_module._normalize_deterministic(final)
