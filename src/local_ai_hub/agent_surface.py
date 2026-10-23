"""Reviewed boundary between agent work and operator diagnostics.

This policy does not authorize requests. Existing mode, capability, owner and
repository checks still run. Diagnostic requests must additionally pass the
dashboard's live detailed-diagnostics gate before starting any work.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DIAGNOSTIC_MCP_ACTIONS = {
    "local_ai_task": frozenset({
        "route", "benchmark", "hardware_benchmark", "evaluation_record", "evaluation_report",
        "candidate_create", "candidate_promote", "eval_suite", "prompt_eval", "eval_drift",
    }),
    "local_ai_repo": frozenset({"route", "generate_dataset"}),
    "local_ai_coord": frozenset({"curate_dataset"}),
}

# These operations inspect or experiment with the Hub itself. Repository code
# diagnostics, review/security findings, model inventory and aggregate dashboard
# metrics are useful work and deliberately remain outside this set.
DIAGNOSTIC_HTTP_ROUTES = frozenset({
    ("GET", "/api/doctor"), ("POST", "/api/doctor"),
    ("GET", "/api/hardware/gpu"), ("GET", "/api/hardware/system"),
    ("GET", "/api/db/query"), ("POST", "/api/db/query"),
    ("GET", "/api/audit/tail"), ("GET", "/api/logs/tail"),
    ("GET", "/api/benchmark/summary"),
    ("GET", "/api/telemetry/timeline"), ("POST", "/api/telemetry/timeline"),
    ("POST", "/api/benchmark"), ("POST", "/api/benchmark/run"),
    ("POST", "/api/evaluation"), ("POST", "/api/route"),
    ("POST", "/api/task/eval_suite"), ("POST", "/api/task/prompt_eval"),
    ("POST", "/api/task/eval_drift"), ("POST", "/api/repo/generate_dataset"),
    ("POST", "/api/agent-state/learning"),
})

RETIRED_REPO_ACTIONS = frozenset({"context_compile", "verify_receipt", "verify_completion"})

# Disposition history, not compatibility redirects or alternate dispatch paths.
RETIRED_HTTP_ALIASES = {
    ("GET", "/api/repo/config"): "/api/project/config",
    ("GET", "/api/repo_state"): "/api/repo/state",
    ("GET", "/api/worktrees"): "/api/coord/worktrees",
    ("GET", "/api/affected_tests"): "/api/repo/affected_tests",
    ("GET", "/api/topology"): "/api/repo/topology",
    ("GET", "/api/dead_code"): "/api/repo/dead_code",
    ("POST", "/api/leases/claim"): "/api/leases/claim_batch",
}


def diagnostic_mcp_operation(tool: str, arguments: Mapping[str, Any]) -> bool:
    action = arguments.get("action", arguments.get("detail", ""))
    if not isinstance(action, str):
        return False  # The authored input validator reports malformed selectors.
    if arguments.get("include_diagnostics") is True and (
        (tool == "local_ai_repo" and action == "context")
        or (tool == "local_ai_coord" and action == "context_compile")
    ):
        return True
    if action in DIAGNOSTIC_MCP_ACTIONS.get(tool, ()):
        return True
    if tool == "local_ai_task" and action == "submit":
        return arguments.get("job_action") in DIAGNOSTIC_MCP_ACTIONS["local_ai_task"]
    if tool == "local_ai_task" and action == "batch":
        items = arguments.get("tasks")
        return isinstance(items, list) and any(
            isinstance(item, Mapping) and diagnostic_mcp_operation(tool, item) for item in items
        )
    if tool == "local_ai_repo" and action == "pipeline":
        items = arguments.get("steps")
        return isinstance(items, list) and any(
            isinstance(item, Mapping) and diagnostic_mcp_operation(tool, item) for item in items
        )
    return False


def diagnostic_http_operation(method: str, path: str, payload: Mapping[str, Any] | None = None) -> bool:
    if (method, path) in DIAGNOSTIC_HTTP_ROUTES:
        return True
    payload = payload or {}
    # Match the existing HTTP/job dispatcher normalization. This classifies
    # accepted spellings, without introducing a new alias or acceptance rule.
    selector = payload.get("action", "")
    action = selector.strip().lower().replace("-", "_") if isinstance(selector, str) else ""
    if method == "POST" and path in {"/api/context/pack", "/api/agent-state/context"}:
        return payload.get("include_diagnostics") is True
    if method == "POST" and path == "/api/async-jobs" and action == "submit":
        job_action = payload.get("job_action", "")
        job_action = job_action.strip().lower().replace("-", "_") if isinstance(job_action, str) else ""
        return job_action in DIAGNOSTIC_MCP_ACTIONS["local_ai_task"]
    if method == "POST" and path == "/api/agent-state/tasks":
        return action == "curate_dataset"
    return False


def diagnostics_disabled_response() -> dict[str, Any]:
    return {
        "success": False, "status_code": 409, "error_code": "detailed_diagnostics_disabled",
        "error": "Enable detailed diagnostics in the dashboard to use this operator diagnostic.",
        "terminal": True, "retryable": False,
    }
