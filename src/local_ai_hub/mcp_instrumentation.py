from __future__ import annotations

import functools
import inspect
import sys
import time
from typing import Any
import uuid


def _get_services_module() -> Any:
    for mod_name, mod in list(sys.modules.items()):
        if mod_name.startswith("local_ai_hub._mcp_server_") and mod is not None:
            return mod
    from . import mcp_server
    return mcp_server


def _sanitize_telemetry_payload(value: Any, *, field: str = "", context: str = "") -> Any:
    """Preserve metrics and known labels while removing untrusted diagnostic text."""
    services_module = _get_services_module()
    if field in {"detail", "queue", "hotspots", "decision_grade"}:
        context = field
    if isinstance(value, dict):
        return {
            str(key): services_module._sanitize_telemetry_payload(item, field=str(key), context=context)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [services_module._sanitize_telemetry_payload(item, field=field, context=context) for item in value]
    if not isinstance(value, str):
        return value

    if field == "writer_error_attempts_unit" and value == "attempts":
        return value
    if services_module._TELEMETRY_SENSITIVE_TEXT_FIELD_RE.search(field):
        return "Error details omitted"
    if context == "detail":
        if field == "omitted_sections":
            return value if value in services_module._TELEMETRY_DETAIL_LABELS["omitted_sections"] else "Error details omitted"
        return value if value in services_module._TELEMETRY_DETAIL_LABELS.get(field, frozenset()) else "Error details omitted"
    if context == "queue":
        return "Error details omitted"
    if context == "hotspots":
        return value if value in services_module._TELEMETRY_HOTSPOT_LABELS.get(field, frozenset()) else "Error details omitted"
    if context == "decision_grade":
        if field in {"action", "component", "error_type", "operation", "route", "signal", "type"}:
            return services_module._safe_error_metadata(value)
        return "Error details omitted"
    if context == "error_fingerprints" and field in {"component", "error_type", "operation"}:
        return services_module._safe_error_metadata(value)
    if context == "by_operation" and field in {"action", "event_type"}:
        return services_module._safe_error_metadata(value)
    if context == "window" and field == "scope":
        return value if value in {"window", "process"} else "Error details omitted"
    return services_module._safe_error_metadata(value)

def _telemetry_failure(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseException):
        retryable = isinstance(value, (TimeoutError, ConnectionError, OSError))
        status_code = 503 if retryable else 500
        terminal = not retryable
    else:
        status = value if isinstance(value, dict) else {}
        supplied_status = status.get("status_code")
        status_code = supplied_status if type(supplied_status) is int and 100 <= supplied_status <= 599 else 500
        retryable = status.get("retryable") if type(status.get("retryable")) is bool else status_code >= 500
        terminal = status.get("terminal") if type(status.get("terminal")) is bool else not retryable
    result: dict[str, Any] = {
        "success": False,
        "status_code": status_code,
        "terminal": terminal,
        "retryable": retryable,
        "error": "Telemetry report failed; details omitted",
    }
    if isinstance(value, dict):
        for key in ("degraded", "stale"):
            if type(value.get(key)) is bool:
                result[key] = value[key]
    return result

def _preserve_contract_state(raw: Any, projected: Any) -> Any:
    """Restore bounded result-state fields after projection and compaction."""
    services_module = _get_services_module()
    state_keys = {
        *services_module._RELIABILITY_PROTECTED_KEYS,
        "hub_online", "status_code", "error", "cancel", "timed_out",
    }
    if isinstance(raw, dict) and isinstance(projected, dict):
        for key in state_keys:
            if key not in raw:
                continue
            value = raw[key]
            if key == "success" and projected.get("success") is False and value is True:
                continue
            if key == "error" and isinstance(value, str):
                value = value[:500]
            elif key == "evidence" and isinstance(value, list):
                value = services_module._bound_context_json(value[:services_module.MAX_EVIDENCE])
            elif key == "evidence_ids" and isinstance(value, (list, tuple)):
                value = [str(item)[:160] for item in value[:services_module.MAX_EVIDENCE] if str(item)]
            elif key == "cancel":
                value = services_module._bound_context_json(value)
            elif key == "retry_after_seconds":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not services_module.math.isfinite(value) or value < 0:
                    continue
            projected[key] = value
        if not projected.get("evidence_ids"):
            context_pack = raw.get("adaptive_context_pack") or raw.get("context_pack")
            evidence = context_pack.get("evidence") if isinstance(context_pack, dict) else None
            if isinstance(evidence, list):
                ids = [
                    str(item.get("evidence_id"))[:160]
                    for item in evidence[:services_module.MAX_EVIDENCE]
                    if isinstance(item, dict) and item.get("evidence_id")
                ]
                if ids:
                    projected["evidence_ids"] = ids
        for key, value in raw.items():
            if key in projected and key not in state_keys:
                projected[key] = services_module._preserve_contract_state(value, projected[key])
        return projected
    if isinstance(raw, list) and isinstance(projected, list):
        for index, value in enumerate(raw[:len(projected)]):
            projected[index] = services_module._preserve_contract_state(value, projected[index])
    return projected

def _telemetry_status_projection(value: Any) -> dict[str, Any]:
    """Keep status telemetry decision-grade instead of returning the full report."""
    services_module = _get_services_module()
    if not isinstance(value, dict):
        return {"success": False, "terminal": True, "retryable": True, "error": "telemetry response must be an object"}
    envelope_success = bool(value.get("success", True))
    report = value.get("report") if isinstance(value.get("report"), dict) else value
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    keep_summary = (
        "events", "cache_hits", "coalesced", "input_tokens", "output_tokens",
        "avoided_cloud_tokens", "avg_duration_ms", "failure_rate", "avg_queue_wait_ms",
        "fallback_count", "degraded_count", "retry_count", "cache_hit_rate", "net_cloud_token_delta_est",
    )
    projected_summary = {key: summary[key] for key in keep_summary if key in summary}
    scope = summary.get("scope", report.get("scope"))
    if isinstance(scope, str) and scope in {"window", "process"}:
        projected_summary["scope"] = scope
    summary_cache_stale = summary.get("summary_cache_stale", report.get("summary_cache_stale"))
    if type(summary_cache_stale) is bool:
        projected_summary["summary_cache_stale"] = summary_cache_stale
    writer = summary.get("writer")
    if isinstance(writer, dict):
        projected_writer: dict[str, Any] = {}
        numeric_fields = {
            "process_started_at", "snapshot_end_at", "interval_seconds",
            "accepted_rate", "overflow_rejection_rate", "post_acceptance_loss_rate",
            "written_rate", "pending_rate",
        }
        count_fields = {
            "attempted", "accepted", "rejected_overflow", "lost_after_acceptance",
            "processed", "written", "pending", "dropped", "writer_errors", "writer_error_attempts",
        }
        for key in numeric_fields:
            if key not in writer:
                continue
            item = writer[key]
            if key.endswith("_rate") and item is None:
                projected_writer[key] = item
            elif type(item) in {int, float} and services_module.math.isfinite(item):
                lower, upper = (0.0, 1.0) if key.endswith("_rate") else (0.0, None)
                if item >= lower and (upper is None or item <= upper):
                    projected_writer[key] = item
        for key in count_fields:
            item = writer.get(key)
            if type(item) is int and item >= 0:
                projected_writer[key] = item
        if isinstance(writer.get("scope"), str) and writer["scope"] == "current_process":
            projected_writer["scope"] = "current_process"
        for key in ("accounting_balanced", "activity_observed"):
            if type(writer.get(key)) is bool:
                projected_writer[key] = writer[key]
        if "writer_error_attempts" in projected_writer:
            projected_writer["writer_error_attempts_unit"] = "attempts"
        projected_summary["writer"] = projected_writer
    projected: dict[str, Any] = {
        "success": envelope_success and bool(report.get("success", True)),
        "window": services_module._sanitize_telemetry_payload(report.get("window") if isinstance(report.get("window"), dict) else {}, field="window"),
        "summary": services_module._sanitize_telemetry_payload(projected_summary, field="summary"),
        "queue": services_module._sanitize_telemetry_payload(report.get("queue") if isinstance(report.get("queue"), dict) else summary.get("queue", {}), field="queue"),
        "hotspots": services_module._sanitize_telemetry_payload(list(report.get("hotspots") or [])[:12], field="hotspots"),
        "by_operation": services_module._sanitize_telemetry_payload(list(report.get("by_operation") or [])[:20], field="by_operation"),
        "error_fingerprints": services_module._sanitize_telemetry_payload(list(report.get("error_fingerprints") or [])[:12], field="error_fingerprints"),
        "detail": services_module._sanitize_telemetry_payload(report.get("detail") if isinstance(report.get("detail"), dict) else {}, field="detail"),
        "decision_grade": services_module._sanitize_telemetry_payload(report.get("decision_grade") if isinstance(report.get("decision_grade"), dict) else {}, field="decision_grade"),
    }
    if value.get("error") or report.get("error"):
        projected.update(services_module._telemetry_failure(value if value.get("error") else report))
    return projected

@functools.lru_cache(maxsize=32)
def _schema_descriptor(tool_name: str) -> dict[str, Any]:
    """Return one stable public-tool descriptor for token-cost estimation."""
    services_module = _get_services_module()
    try:
        fn = services_module.__dict__.get(tool_name)
        desc_map = services_module.__dict__.get("_all_desc_map", {})
        builder = desc_map.get(tool_name) if isinstance(desc_map, dict) else None
        description = builder() if callable(builder) else (getattr(fn, "__doc__", "") or "")
        signature = str(services_module.inspect.signature(fn)) if callable(fn) else ""
        return {"name": tool_name, "description": description, "signature": signature}
    except Exception:
        return {"name": tool_name}

@functools.lru_cache(maxsize=1)
def _tool_catalog_schema_tokens() -> int:
    """Estimate enabled MCP schema exposure once per process.

    Hosts differ in how often the catalog is re-injected, so this value is kept as
    a separate conservative/upper-bound adjustment rather than folded into the
    default protocol cost.  Caching avoids repeated inspect/description work on
    every foreground tool call.
    """
    services_module = _get_services_module()
    try:
        desc_map = services_module.__dict__.get("_all_desc_map", {})
        names = [name for name in desc_map if name not in set(getattr(services_module.FEATURES, "disabled_tools", []) or [])]
        return services_module.json_tokens({"tools": [services_module._schema_descriptor(name) for name in names]})
    except Exception:
        return 0

def _record_tool_accounting(
    *, tool_name: str, arguments: dict[str, Any], response: Any,
    measured: dict[str, Any], metadata: dict[str, Any], result_id_value: str = "",
    event_id: str = "", duration_ms: float = 0.0, call_success: bool | None = None,
) -> None:
    services_module = _get_services_module()
    try:
        event = services_module.finalize_tool_accounting(
            tool_name=tool_name, arguments=arguments, response=response, measured=measured,
            schema_tokens_est=services_module._tool_catalog_schema_tokens(), metadata=metadata,
        )
        event.update({"agent": services_module.AGENT_NAME, "created_at": services_module.time.time()})
        if event_id and type(call_success) is bool:
            raw_root = arguments.get("root", "")
            root = raw_root if isinstance(raw_root, str) and (services_module.os.path.isabs(raw_root) or services_module.ntpath.isabs(raw_root)) else ""
            event.update({"event_id": event_id, "operation": str(arguments.get("action") or "default").lower(),
                          "root": root, "duration_ms": duration_ms, "success": call_success})
        services_module.CONTEXT_LEDGER.record(
            tool=tool_name,
            operation=str(arguments.get("action") or "default"),
            request_tokens=event["agent_tool_request_tokens_est"],
            response_tokens=event["agent_tool_response_tokens_est"],
            saved_tokens=event["projected_response_saved_tokens_est"],
            cache_outcome=event["cache_outcome"],
            result_id=result_id_value,
            session_id=arguments.get("session_id", ""),
        )
        services_module._ACCOUNTING_REPORTER.record(event)

        try:
            from .agent_telemetry import record_agent_event
            record_agent_event(
                agent=arguments.get("agent") or services_module.AGENT_NAME or "generic",
                tool=tool_name,
                action=str(arguments.get("action") or "default"),
                profile=arguments.get("response_profile") or "compact",
                outcome="success" if call_success else "error",
                duration_ms=duration_ms,
                tokens_est=event.get("agent_tool_response_tokens_est", 0),
                tokens_saved_est=event.get("projected_response_saved_tokens_est", 0),
            )
        except Exception:
            pass
    except Exception:
        pass


def _project_minimal_agent_response(result: dict[str, Any], tool: str, action: str) -> dict[str, Any]:
    """Strict minimal profile projection: returns ONLY core decision-grade payload."""
    minimal: dict[str, Any] = {}
    if "success" in result:
        minimal["success"] = result["success"]
    if "error" in result:
        minimal["error"] = result["error"]
    if "terminal" in result:
        minimal["terminal"] = result["terminal"]

    if "task" in result and isinstance(result["task"], dict):
        t = result["task"]
        min_task = {
            "task_id": t.get("task_id"),
            "status": t.get("status"),
        }
        if "checkpoint" in t and isinstance(t["checkpoint"], dict):
            cp = t["checkpoint"]
            if "phase" in cp:
                min_task["phase"] = cp["phase"]
            if "next_action" in cp:
                min_task["next_action"] = cp["next_action"]
        minimal["task"] = min_task

    if "completion" in result:
        minimal["completion"] = result["completion"]
    if "unsatisfied_criteria" in result:
        minimal["unsatisfied_criteria"] = result["unsatisfied_criteria"]

    for key in ("matches", "symbols", "results", "files", "references"):
        if key in result and isinstance(result[key], list):
            minimal[key] = [
                {"path": it.get("path") or it.get("file"), "line": it.get("line") or it.get("lineno")}
                if isinstance(it, dict) and ("path" in it or "file" in it)
                else it
                for it in result[key][:24]
            ]
            minimal["count"] = len(result[key])

    for key in ("text", "content"):
        if key in result:
            minimal[key] = result[key]
    for key in ("path", "line_start", "line_end", "total_lines", "virtualized", "lease_id", "released_rows", "lease", "mutation_applied"):
        if key in result:
            minimal[key] = result[key]
    for key in ("advisory_only", "semantic_quality", "review_consistency", "quality_warning", "bypass_reason", "response_budget"):
        if key in result:
            minimal[key] = result[key]

    return minimal if len(minimal) > 1 else result


def _agent_output(value: Any, tool: str, arguments: dict[str, Any]) -> Any:
    """Keep internal observations out of ordinary agent responses.

    Agent MCP responses are clean by default. Background debug traces (SQLite)
    operate independently and do not pollute agent context windows.
    """
    services_module = _get_services_module()
    detail_checker = getattr(services_module, "agent_diagnostics_enabled", None)
    detail_enabled = detail_checker(services_module.CFG, arguments) if detail_checker else False
    if not detail_enabled:
        detailed_checker = getattr(services_module, "detailed_diagnostics_enabled", None)
        if detailed_checker and detailed_checker(services_module.CFG):
            detail_enabled = True
    projector = (services_module.project_status_response if tool == "local_ai_status"
                 else services_module.project_pubsub_poll_response if tool == "local_ai_coord" and arguments.get("action") == "pubsub_poll"
                 else services_module.project_wait_event_response if tool == "local_ai_coord" and arguments.get("action") == "wait_for_event"
                 else services_module.project_agent_response)
    extra = arguments.get("extra_fields") or ()
    result = projector(value, enabled=detail_enabled, extra_fields=extra)
    operation = arguments.get("laya_operation")
    if (tool == "local_ai_coord" and arguments.get("action") == "curate_dataset"
            and isinstance(operation, dict) and operation.get("action") == "runtime_status"
            and isinstance(value, dict) and isinstance(value.get("runtime"), dict)
            and isinstance(result, dict)):
        allowed = {
            "model_configuration", "missing_configuration_fields", "provider_close_configured",
            "idle_unload_seconds", "inflight", "loading", "closing", "runtime_verification",
        }
        result["runtime"] = {key: item for key, item in value["runtime"].items() if key in allowed}

    if isinstance(result, dict) and not detail_enabled:
        task = result.get("task")
        if isinstance(task, dict):
            cp = task.get("checkpoint")
            if isinstance(cp, dict) and isinstance(cp.get("state_data"), dict):
                mem = cp["state_data"].get("memory_context")
                if isinstance(mem, dict):
                    mem.pop("instruction", None)

    profile = str(arguments.get("response_profile") or "").strip().lower()
    # local_ai_status already has a dedicated compact projection above. The
    # generic minimal projection drops its required readiness identity fields.
    if profile == "minimal" and tool != "local_ai_status" and isinstance(result, dict) and result.get("success") is True:
        result = _project_minimal_agent_response(result, tool=tool, action=str(arguments.get("action", "")))

    return services_module._reconcile_existing_budget(result) or result

def _instrumented_tool(services_module: Any = None):
    if services_module is None:
        services_module = _get_services_module()
    def decorator(fn: Any) -> Any:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.monotonic()
            handoff_added = False
            try:
                bound = signature.bind_partial(*args, **kwargs)
                # Do not apply Python defaults: omitted optional arguments are not
                # emitted by the model and therefore must not inflate tool-call cost.
                arguments = dict(bound.arguments)
            except Exception:
                arguments = dict(kwargs)
            budget_rejection = services_module._explicit_budget_rejection(arguments)
            if budget_rejection is not None:
                return budget_rejection
            if (fn.__name__ == "local_ai_coord" and arguments.get("action") in {"claim", "release", "gpu_reservation_release", "gpu_reservation_release_authorized", "gpu_capacity_lease_release", "gpu_scheduler_capacity_lease_release"}
                    and type(arguments.get("max_response_tokens")) is int
                    and 0 < arguments["max_response_tokens"] < 512):
                return {"success": False, "error": "lease mutation requires max_response_tokens >= 512",
                        "operation_not_started": True}

            # Universal MCP-level Token Economy hard guard for all connected agents
            if fn.__name__ == "local_ai_repo":
                act = arguments.get("action")
                if act == "search" and ("limit" not in arguments or arguments.get("limit") is None):
                    arguments["limit"] = 24
                elif act in ("read_file", "source"):
                    line_start = arguments.get("line_start") or arguments.get("start_line")
                    line_end = arguments.get("line_end") or arguments.get("end_line")
                    if line_start is not None and line_end is not None:
                        try:
                            start_i = int(line_start)
                            end_i = int(line_end)
                            # Transparently clamp to max 200 lines instead of hard-failing with retry loop
                            if end_i - start_i > 200:
                                clamped_end = start_i + 199
                                if "line_end" in arguments:
                                    arguments["line_end"] = clamped_end
                                if "end_line" in arguments:
                                    arguments["end_line"] = clamped_end
                        except (ValueError, TypeError):
                            pass
            try:
                mode_state_dir = services_module.configured_state_dir(services_module.CFG, create=False)
                mode_snapshot = services_module.load_operational_mode(mode_state_dir)
            except Exception:
                mode_snapshot = services_module.OperationalModeSnapshot(
                    "maintenance", 0, None, degraded=True,
                    error="operational mode state is unavailable",
                )
            action_name, requires_heavy_work = services_module._classify_mcp_operation(fn.__name__, arguments)
            mode_rejection = services_module.operational_mode_gate_error(
                mode_snapshot,
                action_name,
                requires_heavy_work=requires_heavy_work,
            )
            operator_status = fn.__name__ == "local_ai_status" and not requires_heavy_work
            reservation_control = (fn.__name__ == "local_ai_coord" and arguments.get("action") in {
                "gpu_reservation_status", "gpu_reservation_release", "gpu_reservation_release_authorized", "gpu_capacity_lease_release", "gpu_scheduler_capacity_lease_release",
            })
            if mode_rejection is not None and not operator_status and not reservation_control:
                return mode_rejection
            if not services_module.detailed_diagnostics_enabled(services_module.CFG) and services_module.diagnostic_mcp_operation(fn.__name__, arguments):
                return services_module.diagnostics_disabled_response()
            if fn.__name__ == "local_ai_task" and arguments.get("action") == "benchmark":
                validation_error = services_module.validate_operation_arguments(
                    "local_ai_task", "benchmark", arguments, features=services_module.FEATURES,
                )
                if validation_error is not None:
                    return services_module.contract_error(
                        f"{validation_error}; benchmark runs the configured model suite with a fixed "
                        "prompt and does not accept per-input model, prompt, or deadline options",
                        status_code=400,
                    )
            extra = arguments.get("extra_fields") or kwargs.get("extra_fields")
            token = services_module._CURRENT_EXTRA_FIELDS.set(extra) if extra is not None else None
            response_profile = arguments.get("response_profile", "")
            if (not response_profile and fn.__name__ == "local_ai_repo"
                    and arguments.get("action") in {"context", "search", "code_index"}):
                response_profile = "compact"
            response_token = services_module._CURRENT_RESPONSE_OPTIONS.set({
                "action": arguments.get("action", ""),
                "max_response_tokens": arguments.get("max_response_tokens", 0),
                "response_profile": response_profile,
                "reuse_key": arguments.get("reuse_key", ""),
                "tool": fn.__name__,
                "arguments": arguments,
            })
            operational_token = services_module._CURRENT_OPERATIONAL_CONTEXT.set(
                (action_name, requires_heavy_work)
            )
            metadata_token = services_module.set_metadata(
                task_id=arguments.get("task_id", ""),
                parent_task=arguments.get("parent_task_id", ""),
                phase=arguments.get("phase", ""),
                activity=f"{fn.__name__}:{arguments.get('action', 'default')}",
                revision=arguments.get("repository_revision") or arguments.get("repo_revision", ""),
                context_digest=services_module.context_digest(arguments.get("context", "")) if arguments.get("context") else "",
                fanout_count=len(arguments.get("tasks") or []) if isinstance(arguments.get("tasks"), list) else 0,
            )
            metadata = {}
            call_event_id = uuid.uuid4().hex
            try:
                result = fn(*args, **kwargs)
            except Exception:
                duration_ms = (time.monotonic() - started) * 1000
                services_module._record_adoption(fn.__name__, arguments, None, duration_ms, failed=True, event_id=call_event_id)
                pending = services_module._PENDING_MCP_ACCOUNTING.get()
                if pending is None:
                    services_module._record_tool_accounting(tool_name=fn.__name__, arguments=arguments, response={"success": False},
                                            measured={}, metadata={}, event_id=call_event_id,
                                            duration_ms=duration_ms, call_success=False)
                else:
                    pending.append({"tool_name": fn.__name__, "arguments": arguments,
                                    "response": {"success": False}, "measured": {}, "metadata": {},
                                    "event_id": call_event_id, "duration_ms": duration_ms, "call_success": False})
                raise
            finally:
                metadata = services_module.efficiency_metadata()
                services_module.reset_metadata(metadata_token)
                if token is not None:
                    services_module._CURRENT_EXTRA_FIELDS.reset(token)
                services_module._CURRENT_RESPONSE_OPTIONS.reset(response_token)
                services_module._CURRENT_OPERATIONAL_CONTEXT.reset(operational_token)
            clean, measured = services_module.pop_accounting(result)
            proactive_hint = None
            if fn.__name__ == "local_ai_repo" and arguments.get("action") in {"affected_tests", "test_matrix"}:
                proactive_hint = services_module.targeted_semantic_handoff(
                    fn.__name__, str(arguments.get("action") or "").lower(), clean,
                    services_module.FEATURES.tasks and services_module.FEATURES.has_any_model(),
                )
            if proactive_hint is not None and isinstance(clean, dict) and "local_handoff" not in clean:
                candidate = {**clean, "local_handoff": proactive_hint}
                requested_tokens = int(arguments.get("max_response_tokens") or 0)
                if requested_tokens <= 0 or services_module.json_tokens(candidate) <= requested_tokens:
                    clean = candidate
                    handoff_added = True
            if (isinstance(clean, dict) and clean.get("success") is True
                    and ("routing" in (arguments.get("extra_fields") or ())
                         or arguments.get("response_profile") == "debug")):
                hint = proactive_hint or services_module.semantic_handoff_hint(
                    fn.__name__,
                    str(arguments.get("action") or "").lower(),
                    services_module.FEATURES.tasks and services_module.FEATURES.has_any_model(),
                    services_module.FEATURES.status,
                )
                if hint is not None:
                    candidate = dict(clean)
                    routing = candidate.get("routing")
                    routing_added = False
                    if routing is None:
                        candidate["routing"] = {"semantic_handoff": hint}
                        routing_added = True
                    elif isinstance(routing, dict) and "semantic_handoff" not in routing:
                        candidate["routing"] = {**routing, "semantic_handoff": hint}
                        routing_added = True
                    elif not isinstance(routing, dict):
                        candidate["routing"] = {"value": routing, "semantic_handoff": hint}
                        routing_added = True
                    requested_tokens = int(arguments.get("max_response_tokens") or 0)
                    if routing_added and (requested_tokens <= 0 or services_module.json_tokens(candidate) <= requested_tokens):
                        clean = candidate
                        handoff_added = True
            clean = services_module._agent_output(clean, fn.__name__, arguments)
            if (
                isinstance(clean, dict)
                and clean.get("unsupported") is True
                and clean.get("blocked") is not True
                and clean.get("status_code") not in {401, 403}
            ):
                clean = dict(clean)
                clean.setdefault("terminal", True)
                clean.setdefault("retryable", False)
            selector = "detail" if fn.__name__ == "local_ai_status" else "action"
            parameter = signature.parameters.get(selector)
            contract_action = arguments.get(selector, parameter.default if parameter is not None else "")
            output_error = services_module.validate_operation_output(fn.__name__, str(contract_action), clean)
            if output_error is not None:
                clean = {
                    "success": False, "status_code": 500, "terminal": True, "retryable": False,
                    "error": f"MCP output contract failed: {output_error}",
                    "failure_kind": "output_contract_violation",
                    **({"request_id": clean["request_id"]} if isinstance(clean, dict) and isinstance(clean.get("request_id"), str) else {}),
                }
            duration_ms = (services_module.time.monotonic() - started) * 1000
            call_success = isinstance(clean, dict) and clean.get("success") is True
            services_module._record_adoption(fn.__name__, arguments, clean, duration_ms, recommended=handoff_added, event_id=call_event_id)
            pending = services_module._PENDING_MCP_ACCOUNTING.get()
            if pending is None:
                services_module._record_tool_accounting(
                    tool_name=fn.__name__, arguments=arguments, response=clean,
                    measured=measured, metadata=metadata,
                    event_id=call_event_id, duration_ms=duration_ms, call_success=call_success,
                    result_id_value=clean["result_id"] if isinstance(clean, dict) and "result_id" in clean else "",
                )
            else:
                pending.append({
                    "tool_name": fn.__name__, "arguments": arguments, "response": clean,
                    "measured": measured, "metadata": metadata,
                    "event_id": call_event_id, "duration_ms": duration_ms, "call_success": call_success,
                })
            return clean

        return wrapped
    return decorator
