from __future__ import annotations

from typing import Any, Literal


def local_ai_status(
    detail: Literal["brief"] = "brief",
    extra_fields: list[str] | None = None,
    max_response_tokens: int = 0,
    response_profile: str = "",
    reuse_key: str = "",
) -> dict[str, Any]:
    import sys
    services_module = None
    for mod_name, mod in list(sys.modules.items()):
        if mod_name.startswith("local_ai_hub._mcp_server_") and mod is not None:
            services_module = mod
            break
    if services_module is None:
        from . import mcp_server as services_module
    """Compact Hub and local-model readiness: availability, active model, and VRAM pressure."""
    if detail != "brief":
        return services_module.contract_error("detail supports only brief")
    if not services_module.FEATURES.status:
        return {**services_module.contract_error("local_ai_status is disabled in configuration", status_code=403), "unsupported": True}
    status = services_module.CLIENT.get("/api/live/status?light=1")
    if not isinstance(status, dict):
        return services_module.contract_error("live status endpoint returned an invalid payload", status_code=502)
    scheduler = status.get("scheduler")
    scheduler = scheduler if isinstance(scheduler, dict) else {}
    raw_capabilities = status.get("capabilities")
    if not isinstance(raw_capabilities, dict):
        raw_capabilities = services_module.FEATURES.capability_status()
    else:
        raw_capabilities = services_module._effective_mcp_capabilities(raw_capabilities, services_module.FEATURES.capability_status())
    capabilities = {
        str(name): {
            key: item[key]
            for key in ("available", "state", "minimum_profile", "reason", "feature_gate", "provider_readiness")
            if key in item
        }
        for name, item in raw_capabilities.items()
        if isinstance(name, str) and isinstance(item, dict)
    } if isinstance(raw_capabilities, dict) else {}
    gpu_admission_state = scheduler.get("gpu_admission_state")
    if not isinstance(gpu_admission_state, str) or gpu_admission_state not in {
        "available", "external_reservation", "background_lease",
        "preparing_model", "inference_active", "outcome_unknown",
    }:
        gpu_admission_state = "unknown"
    hardware_profile = status.get("hardware_profile")
    if not isinstance(hardware_profile, str) or hardware_profile not in services_module.HARDWARE_PROFILE_ORDER:
        hardware_profile = services_module.FEATURES.hardware_profile
    result: dict[str, Any] = {
        "success": status.get("success", bool(status.get("hub_online", False))),
        "version": status.get("version"),
        "ollama_online": status.get("ollama_online"),
        "active_model": scheduler.get("active_model"),
        "gpu_admission_state": gpu_admission_state,
        "degraded": status.get("degraded") is True,
        "hardware_profile": hardware_profile,
        "capabilities": capabilities,
    }
    if "hub_online" in status:
        result["hub_online"] = status["hub_online"]
    for stale_key in ("snapshot_cached", "snapshot_stale", "status_age_ms"):
        if stale_key in status:
            result[stale_key] = status[stale_key]
    vram = status.get("vram_balancer")
    if isinstance(vram, dict):
        result["vram_pressure"] = vram.get("pressure_level", "unknown")
        result["context_budget_factor"] = vram.get("context_budget_factor", 1.0)
        telemetry_error = vram.get("telemetry_error")
        safe_telemetry_error = (
            telemetry_error
            if isinstance(telemetry_error, str) and telemetry_error in {
                "sample_failed", "sample_wait_timeout", "sample_pending",
                "sample_start_failed", "sample_invalid", "sample_unavailable",
            }
            else None
        )
        result["vram_telemetry"] = {
            "available": vram.get("available") if type(vram.get("available")) is bool else None,
            "error": safe_telemetry_error,
            "sampling": vram.get("telemetry_sampling") if type(vram.get("telemetry_sampling")) is bool else None,
            "stale": vram.get("telemetry_stale") if type(vram.get("telemetry_stale")) is bool else None,
            "wait_timed_out": vram.get("telemetry_wait_timed_out") if type(vram.get("telemetry_wait_timed_out")) is bool else None,
        }
    dependencies = status.get("dependency_status")
    if isinstance(dependencies, dict):
        failed = {
            name: diagnostic for name, diagnostic in dependencies.items()
            if isinstance(name, str) and isinstance(diagnostic, dict) and diagnostic.get("degraded") is True
        }
        if failed:
            result["dependency_status"] = failed
    if isinstance(extra_fields, list) and "endpoint_stats" in extra_fields:
        try:
            raw_endpoint_stats = services_module.CLIENT.get(
                "/api/telemetry/endpoint-stats?scope=active&buckets=0", timeout=2.0
            )
        except Exception:
            raw_endpoint_stats = None
        result["endpoint_stats"] = services_module._compact_endpoint_stats(raw_endpoint_stats)
    if isinstance(extra_fields, list) and "scheduler" in extra_fields:
        result["scheduler"] = services_module._compact_scheduler_status(scheduler)
    return services_module._preserve_contract_state(status, result)
