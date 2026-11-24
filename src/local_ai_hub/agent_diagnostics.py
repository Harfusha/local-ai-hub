"""Shared agent response policy; detailed observations require the dashboard toggle."""
from __future__ import annotations

import tomllib
import copy
from pathlib import Path
from typing import Any


_DETAIL_FIELDS = frozenset({
    # Telemetry, debug, diagnostic traces and raw outputs
    "telemetry", "debug", "diagnostic_artifacts", "raw", "stdout", "stderr",
    "phase_timings_ms", "token_efficiency", "retrieval", "routing",
    "model_trace", "trace", "prompt_budget", "net_cloud_token_delta_est", "cache_hits",
    "coalesced_waiters", "context_budget_factor", "path_hint_usage",
    "model_debug", "raw_model_output", "raw_output", "model_response", "full_trace",
    "raw_model_response", "model_output", "response_raw", "prompt",
    "traceback", "stacktrace", "stack_trace", "runtime", "capture_status", "capture_error_type",

    # Search, indexing & candidates internal state
    "candidate_count", "candidate_count_exact", "count_exact", "index_state", "index_coverage",
    "candidate_freshness", "stale_candidate_count", "index_revision",
    "lexical_total_matches", "lexical_count_exact", "lexical_priority",
    "lexical_candidate_source", "lexical_preprocessed_candidate_count", "query_expansion_applied",
    "source_validation", "stale_candidate_reasons",
    "rag_candidate_count", "rag_candidate_count_exact",
    "truncation_reasons", "confidence_basis",
    "admission", "review_consistency", "semantic_quality",
    "final_response_produced", "final_response_status", "advisory_only",
    "query_cache_hit", "requires_synthesis",

    # OS, low-level process, filesystem & durability internals
    "atime_ns", "mtime_ns", "windows_dacl", "xattrs", "directory_fsync_supported",
    "durability_warning", "process_tree_stopped", "registry_persisted", "tree_control_capability",
    "uptime_seconds", "log_chunks_dropped", "discarded_output_chars", "output_capture_unconfirmed",
    "whitespace_fallback_used",

    # Low-level cache states and hit/miss counters
    "failure_cache", "success_cache", "suppression_cache", "profile_cache",
    "coalesced_wait_timeouts", "coalesced_timeouts", "cache_decisions", "cache_domains",
    "fact_blob_hits", "parse_blob_hits", "preprocessed_hit", "preprocessed_query_hit_rate",
    "preprocessed_query_hits", "generation_cache_hit_rate", "generation_cache_hits",
    "l1_hits", "l2_hits", "persistent_hits", "runtime_hits", "runtime_misses",
    "cache_stats", "cache_outcomes", "cache_layer", "cache_layers", "cache_reuse_breakdown",
    "cache_hit_rate", "_lah_cache_origin", "cached_bytes",

    # Non-essential internal hashes
    "diff_sha256", "inventory_sha256", "current_sha256", "content_sha256",
    "payload_sha256", "reference_sha256", "target_sha256", "review_source_sha256",

    # Scan, inventory, coverage & progress details
    "analysis_coverage", "scanned_paths", "scanned_bytes", "scanned_git_history",
    "eligible_files", "eligible_files_total", "eligible_trigrams", "orphan_trigrams_available",
    "metadata_scanned_files", "modules_scanned", "packages_scanned", "roots_scanned", "commits_scanned",
    "unscanned_file_count", "untracked_inventory_complete", "untracked_files_excluded",
    "paths_complete", "parse_complete", "advisory_complete", "database_search_complete",
    "selection_complete", "stats_complete", "stat_summary", "triage_complete",
    "test_findings_count", "untriaged_high_severity_count", "coverage_scope",
    "matched_strategy", "index_available", "polyglot", "engine", "result_source", "search_mode",
    "syntax_error_count_truncated", "near_duplicates_skipped", "stop_reason",
    "git_history_status",

    # Token economics & financial estimations (unneeded by coding agents)
    "token_count_provenance", "token_savings_percent", "token_savings_breakdown", "savings_ratio",
    "savings_source", "input_savings_source", "output_savings_source",
    "compression_achievable_ratio", "original_chars", "skeleton_chars", "slice_chars",
    "outline_chars", "reduction_pct", "outline_verified",
    "slice_recommendations_estimated", "candidate_context_tokens_est", "original_estimated_tokens",
    "agent_protocol_tokens", "agent_protocol_tokens_est", "agent_tool_request_tokens_est", "agent_tool_response_tokens_est",
    "avoided_cloud_tokens", "gross_avoided_cloud_tokens", "gross_cloud_tokens_avoided_est",
    "gross_input_cloud_tokens_avoided_est", "gross_input_tokens_avoided", "gross_input_tokens_avoided_est",
    "gross_output_cloud_tokens_avoided_est", "gross_output_tokens_avoided", "gross_output_tokens_avoided_est",
    "cloud_cache_read_token_cost_usd_per_million", "cloud_cache_write_token_cost_usd_per_million",
    "cloud_input_token_cost_usd_per_million", "cloud_output_token_cost_usd_per_million",
    "cloud_token_overhead", "cloud_token_overhead_est",
    "estimated_input_savings_usd", "estimated_output_savings_usd", "estimated_savings_pricing_mode", "estimated_savings_usd",
    "tool_request_tokens", "tool_response_tokens", "tool_schema_tokens", "tool_schema_tokens_exposure_est",
    "realistic_net_cloud_token_delta_est", "realistic_savings_breakdown", "realistic_savings_usd",
    "local_compute_tokens_avoided", "local_compute_tokens_avoided_est",
    "effective_context_tokens", "effective_prompt_budget_tokens", "dynamic_depth_tokens",
    "largest_review_chunk_tokens", "review_chunk_token_budget",
    "tokens_per_second", "tokens_generated", "used_tokens", "total_tokens",
    "schema_token_reduction_verified",
    "net_after_schema_token_delta", "net_after_schema_token_delta_est",

    # Microsecond timings and hardware metrics
    "ttft_ms", "call_latency_ms", "db_wait_ms", "eval_duration_ns", "exec_ms", "fairness_wait_ms",
    "histogram_bucket_ceiling_ms", "latency_ms", "load_duration_ms", "load_duration_ns",
    "p50_duration_ms", "p95_duration_ms", "p99_duration_ms", "prompt_eval_duration_ns",
    "queue_age_ms", "queue_wait_ms", "avg_queue_wait_ms", "avg_ms", "serialization_ms", "service_ms",
    "throughput_per_second", "total_duration_ns", "wait_duration_ms", "wait_ms", "wall_ms",
    "foreground_idle_seconds", "idle_seconds", "idle_timeout_seconds", "idle_unload_seconds", "last_foreground_activity_ms",
    "cpu_utilization_pct", "gpu_utilization_pct", "igpu_utilization_pct", "npu_utilization_pct", "vram_used_pct",
    "vram_admission", "vram_admission_phase", "gpu_admission_state",

    # Candidate rejection and omitted lists
    "rejected_candidates", "rejected_candidates_truncated", "omitted_evidence", "omitted_files",
    "ingestion_reuse_rate", "scheduler_background_allowed",

    # Internal algorithm/heuristic formula explanations & analysis details
    "algorithm", "recency_half_life_days", "recency_weighting", "analysis",
    "bytes_read", "elapsed_seconds", "max_entries", "max_file_bytes",
    "excluded_dirs", "limits_hit", "indexed", "cache",
    "inventory_omissions_unknown", "scan_complete_within_scope", "dead_symbols",
    "max_files", "max_findings", "max_seconds", "max_total_bytes", "visited_entries", "max_depth",
    "trace_id",
})
# These fields are caller-owned documents, not Hub response metadata. Their keys
# can legitimately have names such as "debug" or "telemetry".
_DOCUMENT_FIELDS = frozenset({
    "value", "state_data", "metadata", "settings", "config", "schema", "inputSchema",
    "arguments", "receipt", "contract",
})

_STATUS_DETAIL_FIELDS = frozenset({
    "commands", "generation_cache", "semantic_cache", "repo_cache", "repo_snapshots",
    "code_index", "deterministic", "evidence_store", "lossless_router", "autotune",
    "circuit_breakers", "runtime_stats", "headless", "subagents", "learning", "recovery",
    "token_saving", "tool_agent", "http_concurrency", "hub_pid", "ollama_version",
    "global_diagnostic", "vram_telemetry", "vram_pressure", "context_budget_factor",
    "status_age_ms", "snapshot_cached", "snapshot_warming",
})


def detailed_diagnostics_enabled(config: dict[str, Any], *, store: Any = None) -> bool:
    """Use live server state, or re-read persisted settings in a separate MCP process.

    No cached true value survives a toggle/reset or unreadable settings file.
    This does not probe hardware, start a model or issue another HTTP request.
    """
    if store is not None:
        return getattr(store, "enabled", False) is True
    paths = [config.get(key) for key in ("_defaults_path", "_config_path", "_runtime_override_path")]
    telemetry_cfg = config.get("telemetry", {}) if isinstance(config, dict) else {}
    telemetry_mode = str(telemetry_cfg.get("mode") or "").strip().lower()
    enabled = telemetry_mode == "full"
    if not any(paths):
        return enabled
    # With a base config, reconstruct the boolean from the same overlay order
    # as load_config. A runtime-only fixture may use its supplied base value.
    if paths[0] or paths[1]:
        enabled = False
    try:
        for filename in paths:
            if not filename:
                continue
            try:
                with Path(filename).open("rb") as stream:
                    settings = tomllib.load(stream)
            except FileNotFoundError:
                continue
            telemetry = settings.get("telemetry", {})
            if isinstance(telemetry, dict) and "mode" in telemetry:
                mode = str(telemetry.get("mode") or "").strip().lower()
                enabled = mode == "full"
    except (OSError, ValueError, TypeError):
        return False
    return enabled


def agent_diagnostics_enabled(config: dict[str, Any], arguments: dict[str, Any] | None = None) -> bool:
    """Determine whether an agent response should include internal observations.

    By default, agent MCP responses are strictly sanitized to protect agent context.
    Background debug tracing operates independently under full telemetry mode
    and does not flood agent wire contexts.
    Detail is only emitted if explicitly requested via response_profile='debug'
    while full telemetry is active, or explicitly configured via
    [agent_output] detailed_diagnostics = true.
    """
    is_debug_profile = isinstance(arguments, dict) and str(arguments.get("response_profile") or "").strip().lower() == "debug"
    if isinstance(config, dict):
        if is_debug_profile and detailed_diagnostics_enabled(config):
            return True
        telemetry_cfg = config.get("telemetry", {})
        if isinstance(telemetry_cfg, dict) and telemetry_cfg.get("agent_diagnostics") is True:
            return True
        agent_cfg = config.get("agent_output", {})
        if isinstance(agent_cfg, dict) and agent_cfg.get("detailed_diagnostics") is True:
            return True
    return False


def project_agent_response(value: Any, *, enabled: bool, _aggregate: bool = False, extra_fields: Any = None) -> Any:
    """Remove internal observations without changing outcomes or caller documents."""
    if isinstance(value, list):
        return [project_agent_response(item, enabled=enabled, _aggregate=_aggregate, extra_fields=extra_fields) for item in value]
    if not isinstance(value, dict):
        return value
    requested_extra = set(extra_fields) if isinstance(extra_fields, (set, list, tuple)) else set()
    projected = {}
    for key, item in value.items():
        # Private accounting is consumed by telemetry, never part of the wire.
        if key == "_token_accounting":
            continue
        if not enabled and key == "routing":
            if "routing" not in requested_extra or not isinstance(item, dict):
                continue
            handoff = item.get("semantic_handoff")
            if (
                not isinstance(handoff, dict)
                or handoff.get("required") is not False
                or handoff.get("advisory") is not True
                or handoff.get("tool") != "local_ai_task"
                or not isinstance(handoff.get("actions"), list)
                or any(action not in {"delegate", "explore", "reason", "review", "second_opinion", "compress"} for action in handoff["actions"])
            ):
                continue
            safe_handoff = {
                name: handoff[name]
                for name in ("required", "advisory", "tool", "actions", "bypass_tool", "bypass_action", "purpose")
                if name in handoff and isinstance(handoff[name], (bool, str, list))
            }
            item = {"semantic_handoff": safe_handoff}
        aggregate_metric = _aggregate and key in {
            "cache_hits", "coalesced_waiters", "net_cloud_token_delta_est", "token_efficiency",
            "p50_duration_ms", "p95_duration_ms", "p99_duration_ms",
        }
        if not enabled and ((key in _DETAIL_FIELDS and not aggregate_metric and key != "routing")
                            or (str(key).startswith("_") and key not in _DOCUMENT_FIELDS)
                            or (key == "diagnostics" and isinstance(item, dict))):
            if key == "selection_complete" and item is False:
                pass
            elif key == "stop_reason" and bool(item):
                pass
            elif key in {"review_consistency", "semantic_quality"} and isinstance(item, dict) and item.get("usable") is False:
                pass
            elif key == "advisory_only" and bool(item):
                pass
            else:
                continue
        if not enabled and key in {"bypass_reason", "quality_warning"} and item is None:
            continue
        if not enabled and key in {"skipped_files", "skipped_directories", "parse_error_count", "read_error_count", "syntax_error_count"} and (item == 0 or not item):
            continue
        if not enabled and key == "read_errors" and (item == 0 or not item):
            continue
        if not enabled and key == "reranker" and isinstance(item, dict) and not item.get("used"):
            continue
        if not enabled and key in {"degradation_reason", "fallback_from"} and not item:
            continue
        if not enabled and key == "coverage" and isinstance(item, dict) and "limit" in value and "returned_count" in value and "matched_terms" not in item:
            continue
        if not enabled and key == "truncation" and isinstance(item, dict) and "truncated" in value and "candidate_cap" not in item:
            continue
        if not enabled and key == "freshness" and isinstance(item, dict) and item.get("status") in {"not_checked", "fresh"} and not item.get("stale_paths") and not item.get("unknown_paths") and value.get("error_code") != "declaration_not_found":
            continue
        if not enabled and key == "diagnostics" and isinstance(item, list):
            item = [entry for entry in item if isinstance(entry, dict) and entry.get("message")
                    and any(field in entry for field in ("path", "file", "field", "severity", "range", "uri", "code", "source"))]
            if not item:
                continue
        if not enabled and key == "pipeline" and isinstance(item, dict) and "stages" in item:
            # Retrieval stages are observations; failure/degradation flags still
            # inform the agent. A user-requested pipeline's results stay intact.
            item = {name: field for name, field in item.items()
                    if name not in {"stages", "ollama_calls", "mode"}}
            if not item:
                continue
        if not enabled and key == "response_budget" and isinstance(item, dict):
            clean_budget = {name: field for name, field in item.items() if name != "original_tokens"}
            if clean_budget.get("reused") is False:
                clean_budget.pop("reused", None)
            if clean_budget.get("truncated") is False:
                clean_budget.pop("truncated", None)
            item = clean_budget
        if not enabled and key == "results" and isinstance(item, list):
            clean_results = []
            for entry in item:
                if isinstance(entry, dict):
                    res = {k: v for k, v in entry.items() if k not in {"sources", "result_source", "score"}}
                    if isinstance(res.get("text"), str) and len(res["text"]) > 200:
                        lines = [l.strip() for l in res["text"].splitlines() if l.strip()]
                        res["text"] = lines[0][:160] if lines else res["text"][:160]
                    clean_results.append(res)
                else:
                    clean_results.append(entry)
            item = clean_results
        if not enabled and key == "symbols" and isinstance(item, list):
            item = [
                {k: v for k, v in entry.items() if k != "score"}
                if isinstance(entry, dict) else entry
                for entry in item
            ]
        if not enabled and key == "evidence" and isinstance(item, list):
            item = [
                {k: v for k, v in entry.items() if k != "file_sha256" and not (k == "source_verified" and v is False)}
                if isinstance(entry, dict) else entry
                for entry in item
            ]
        if not enabled and key == "records" and isinstance(item, list):
            clean_records = []
            for entry in item:
                if isinstance(entry, dict):
                    clean = {k: v for k, v in entry.items() if k not in {
                        "created_at", "updated_at", "expires_at", "sensitivity"
                    }}
                    prov = clean.get("provenance")
                    if prov == {} or (isinstance(prov, dict) and not prov.get("evidence_ids")):
                        clean.pop("provenance", None)
                    if isinstance(clean.get("evidence_ids"), list) and not clean["evidence_ids"]:
                        clean.pop("evidence_ids", None)
                    clean_records.append(clean)
                else:
                    clean_records.append(entry)
            item = clean_records
        if not enabled and key in {"heartbeat_expires_at", "state_data_omitted"}:
            continue
        if not enabled and key == "lease_id" and (item == "" or item is None):
            continue
        if not enabled and key == "stale" and item is False:
            continue
        if not enabled and key == "instruction" and isinstance(item, str) and item.startswith("Memory is advisory"):
            continue
        if not enabled and key in {"warnings", "blockers"} and isinstance(item, list) and not item:
            continue
        if not enabled and key == "context" and isinstance(item, dict):
            clean_ctx = {k: v for k, v in item.items() if v not in ("", None, {}, [])}
            if not clean_ctx:
                continue
            item = clean_ctx
        if not enabled and key == "items" and isinstance(item, list):
            item = [
                {k: v for k, v in entry.items() if k not in {"origin", "version", "validity"} and not (k == "volatile" and v is False) and not (k == "provenance" and v == {})}
                if isinstance(entry, dict) else entry
                for entry in item
            ]
        if not enabled and key == "total_matches" and (item is None or item == 0) and ("has_more" in value or "returned_count" in value):
            continue
        if not enabled and key == "coverage_complete" and "has_more" in value:
            continue
        if not enabled and key == "context_pack" and "adaptive_context_pack" in value:
            continue
        if not enabled and key == "deterministic" and isinstance(item, dict) and "context" in value and isinstance(value["context"], str):
            continue
        if not enabled and key == "warnings" and isinstance(item, list):
            clean_warnings = []
            for entry in item:
                if isinstance(entry, dict):
                    w = dict(entry)
                    if isinstance(w.get("affected_paths"), list):
                        w["affected_paths"] = list(dict.fromkeys(w["affected_paths"]))
                    clean_warnings.append(w)
                else:
                    clean_warnings.append(entry)
            item = clean_warnings
        if not enabled and key == "state_data" and isinstance(item, dict):
            item = {k: v for k, v in item.items() if not str(k).startswith("_") or k == "_agent_task_scope"}
            if isinstance(item.get("memory_context"), dict):
                mem = dict(item["memory_context"])
                mem.pop("instruction", None)
                if isinstance(mem.get("warnings"), list) and not mem["warnings"]:
                    mem.pop("warnings", None)
                if isinstance(mem.get("context"), dict):
                    clean_ctx = {k: v for k, v in mem["context"].items() if v not in ("", None, {}, [])}
                    mem["context"] = clean_ctx
                if isinstance(mem.get("items"), list):
                    mem["items"] = [
                        {k: v for k, v in entry.items() if k not in {"origin", "version", "validity"} and not (k == "volatile" and v is False) and not (k == "provenance" and v == {})}
                        if isinstance(entry, dict) else entry
                        for entry in mem["items"]
                    ]
                item["memory_context"] = mem
        projected[key] = item if key in _DOCUMENT_FIELDS else project_agent_response(item, enabled=enabled, _aggregate=_aggregate)
    return projected


def project_wait_event_response(value: Any, *, enabled: bool, **kwargs: Any) -> Any:
    """Preserve the caller's event payload independently of diagnostic keys."""
    projected = project_agent_response(value, enabled=enabled, **kwargs)
    if isinstance(value, dict) and isinstance(projected, dict) and value.get("success") is True:
        if "message" in value:
            projected["message"] = copy.deepcopy(value["message"])
        event, shown = value.get("event"), projected.get("event")
        if isinstance(event, dict) and isinstance(shown, dict):
            for field in ("payload", "message"):
                if field in event:
                    shown[field] = copy.deepcopy(event[field])
    return projected


def project_pubsub_poll_response(value: Any, *, enabled: bool, **kwargs: Any) -> Any:
    """Keep caller-authored message payloads while filtering envelope diagnostics."""
    projected = project_agent_response(value, enabled=enabled, **kwargs)
    if not isinstance(value, dict) or not isinstance(projected, dict) or value.get("success") is not True:
        return projected
    source, result = value.get("messages"), projected.get("messages")
    if not isinstance(source, list) or not isinstance(result, list) or len(source) != len(result):
        return projected
    for original, shown in zip(source, result):
        if isinstance(original, dict) and isinstance(shown, dict) and "payload" in original:
            shown["payload"] = copy.deepcopy(original["payload"])
    return projected


def project_aggregate_response(value: Any, *, enabled: bool, **kwargs: Any) -> Any:
    """Aggregate counts stay available; report detail has no filter exemption."""
    if not enabled and isinstance(value, dict):
        value = {key: item for key, item in value.items() if key not in {
            "runtime_snapshots", "error_messages", "error_fingerprints", "error_fingerprints_page",
            "payloads", "hotspots", "evaluation",
        }}
        # Report envelopes are explicit, so caller-owned documents in other
        # endpoints are never treated as operator reports.
        for key in ("report", "metrics"):
            if isinstance(value.get(key), dict):
                value[key] = project_aggregate_response(value[key], enabled=False)
    return project_agent_response(value, enabled=enabled, _aggregate=True, **kwargs)


def project_status_response(value: Any, *, enabled: bool, **kwargs: Any) -> Any:
    """Keep operational/dashboard health; component internals are opt-in detail."""
    projected = project_agent_response(value, enabled=enabled, **kwargs)
    if enabled or not isinstance(projected, dict):
        return projected
    for field in _STATUS_DETAIL_FIELDS:
        if field in {"status_age_ms", "snapshot_cached", "snapshot_stale"} and (
            projected.get("degraded") or projected.get("success") is False
        ):
            continue
        projected.pop(field, None)
    if isinstance(value, dict):
        # These compact values are already sanitized by local_ai_status and are
        # operational health, even though their names are also used by internal
        # diagnostic payloads elsewhere.
        gpu_state = value.get("gpu_admission_state")
        if isinstance(gpu_state, str) and gpu_state in {
            "available", "external_reservation", "background_lease",
            "preparing_model", "inference_active", "outcome_unknown", "unknown",
        }:
            projected["gpu_admission_state"] = gpu_state
        pressure = value.get("vram_pressure")
        if isinstance(pressure, str) and pressure in {"nominal", "moderate", "high", "critical", "unknown"}:
            projected["vram_pressure"] = pressure
        factor = value.get("context_budget_factor")
        if isinstance(factor, (int, float)) and not isinstance(factor, bool):
            projected["context_budget_factor"] = factor
        telemetry = value.get("vram_telemetry")
        if isinstance(telemetry, dict) and set(telemetry) <= {
            "available", "error", "sampling", "stale", "wait_timed_out",
        }:
            projected["vram_telemetry"] = telemetry
    dependencies = projected.get("dependency_status")
    if isinstance(dependencies, dict):
        operational = {"degraded", "status", "error", "error_type", "stale", "retryable", "available"}
        def _filter_dep(status: dict[str, Any]) -> dict[str, Any]:
            res = {key: item for key, item in status.items() if key in operational}
            if status.get("status") == "timeout" or status.get("error") == "timeout":
                if "deadline_ms" in status:
                    res["deadline_ms"] = status["deadline_ms"]
            return res

        projected["dependency_status"] = {
            name: _filter_dep(status) if isinstance(status, dict) else status
            for name, status in dependencies.items()
        }
    capabilities = projected.get("capabilities")
    if isinstance(capabilities, dict):
        projected["capabilities"] = {
            name: {
                k: v for k, v in cap.items()
                if not (k == "reason" and v is None)
                and not (k == "provider_readiness" and v == "not_checked")
                and k != "feature_gate"
                and not (k == "minimum_profile" and cap.get("available") is True)
            } if isinstance(cap, dict) else cap
            for name, cap in capabilities.items()
        }
    return projected
