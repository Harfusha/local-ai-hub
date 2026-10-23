"""Shared agent response policy; detailed observations require the dashboard toggle."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


_DETAIL_FIELDS = frozenset({
    "telemetry", "debug", "diagnostic_artifacts", "raw", "stdout", "stderr",
    "phase_timings_ms", "duration_ms", "token_efficiency", "retrieval", "routing",
    "model_trace", "trace", "prompt_budget", "net_cloud_token_delta_est", "cache_hits",
    "coalesced_waiters", "context_budget_factor", "path_hint_usage",
    "model_debug", "raw_model_output", "raw_output", "model_response", "full_trace",
    "raw_model_response", "model_output", "response_raw", "prompt",
    "traceback", "stacktrace", "stack_trace",
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
    "global_diagnostic",
})


def detailed_diagnostics_enabled(config: dict[str, Any], *, store: Any = None) -> bool:
    """Use live server state, or re-read persisted settings in a separate MCP process.

    No cached true value survives a toggle/reset or unreadable settings file.
    This does not probe hardware, start a model or issue another HTTP request.
    """
    if store is not None:
        return getattr(store, "enabled", False) is True
    paths = [config.get(key) for key in ("_defaults_path", "_config_path", "_runtime_override_path")]
    section = config.get("debug_traces", {})
    enabled = isinstance(section, dict) and section.get("enabled") is True
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
            section = settings.get("debug_traces", {})
            if not isinstance(section, dict):
                return False
            if "enabled" in section:
                enabled = section["enabled"] is True
    except (OSError, ValueError, TypeError):
        return False
    return enabled


def project_agent_response(value: Any, *, enabled: bool, _aggregate: bool = False) -> Any:
    """Remove internal observations without changing outcomes or caller documents."""
    if isinstance(value, list):
        return [project_agent_response(item, enabled=enabled, _aggregate=_aggregate) for item in value]
    if not isinstance(value, dict):
        return value
    projected = {}
    for key, item in value.items():
        # Canonical pagination counts replace equal legacy aliases. Distinct
        # observed counts still describe bounded/inexact searches.
        if "returned_count" in value:
            if key in {"matches_count", "returned_limit"} and item == value["returned_count"]:
                continue
            if key == "observed_match_count" and item == value.get("total_matches"):
                continue
        # Private accounting is consumed by telemetry, never part of the wire.
        if key == "_token_accounting":
            continue
        aggregate_metric = _aggregate and key in {"cache_hits", "coalesced_waiters", "net_cloud_token_delta_est", "token_efficiency"}
        if not enabled and ((key in _DETAIL_FIELDS and not aggregate_metric) or str(key).startswith("_lah_")
                            or (key == "diagnostics" and isinstance(item, dict))):
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
            item = {name: field for name, field in item.items() if name != "original_tokens"}
        projected[key] = item if key in _DOCUMENT_FIELDS else project_agent_response(item, enabled=enabled, _aggregate=_aggregate)
    return projected


def project_aggregate_response(value: Any, *, enabled: bool) -> Any:
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
    return project_agent_response(value, enabled=enabled, _aggregate=True)


def project_status_response(value: Any, *, enabled: bool) -> Any:
    """Keep operational/dashboard health; component internals are opt-in detail."""
    projected = project_agent_response(value, enabled=enabled)
    if enabled or not isinstance(projected, dict):
        return projected
    for field in _STATUS_DETAIL_FIELDS:
        projected.pop(field, None)
    dependencies = projected.get("dependency_status")
    if isinstance(dependencies, dict):
        operational = {"degraded", "status", "error", "error_type", "stale", "retryable", "available"}
        projected["dependency_status"] = {
            name: {key: item for key, item in status.items() if key in operational}
            if isinstance(status, dict) else status
            for name, status in dependencies.items()
        }
    return projected
