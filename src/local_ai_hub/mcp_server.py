from __future__ import annotations

import atexit
import asyncio
import copy
import contextvars
import functools
import hashlib
import inspect
import json
import ntpath
import os
import queue
import re
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path, PureWindowsPath
from typing import Any, Literal, TypeAlias
from urllib.parse import quote

from local_ai_hub.client import HubClient
try:
    from local_ai_hub.inprocess_transport import InProcessTransport
except ModuleNotFoundError as exc:
    if exc.name != "local_ai_hub.inprocess_transport":
        raise
    InProcessTransport = None  # type: ignore[assignment,misc]
from local_ai_hub.compact import compact_result
from local_ai_hub.response_budget import (
    _CONTEXT_PROTECTED_KEYS,
    _budget_rejection,
    _reconcile_existing_budget,
    budget_response,
    delta_response,
    result_id,
)
from local_ai_hub.context_ledger import ContextLedger
from local_ai_hub.budget import RootFamilyBudget
from local_ai_hub.projection import AgentProjector
from local_ai_hub.config import load_config
from local_ai_hub.features import FeatureSet
from local_ai_hub.operation_contracts import (
    MAX_EVENT_SEQUENCE,
    MAX_REPO_PIPELINE_PARALLEL_STEPS,
    REPO_PHASES,
    REPO_PIPELINE_MUTATING_ACTIONS,
    contract_error,
    repo_pipeline_step_schema,
    validate_repo_pipeline_step,
)
from local_ai_hub.ollama_subagents import OllamaSubagentCatalog
from local_ai_hub.process_utils import canonical_root, is_rooted_path
from local_ai_hub.token_accounting import account_projection, attach_accounting, context_digest, finalize_tool_accounting, json_tokens, pop_accounting, tool_request_tokens
from local_ai_hub.trace_context import efficiency_metadata, reset_metadata, set_metadata
from local_ai_hub.adoption_metrics import AdoptionMetricsStore
from local_ai_hub.routing import semantic_handoff_hint
from local_ai_hub.operation_contracts import (
    operation_actions,
    operation_enabled,
    operation_tool_output_schema,
    operation_tool_input_schema,
    validate_operation_arguments,
    validate_operation_call,
    validate_operation_output,
)
from local_ai_hub.state_paths import configured_state_dir
from local_ai_hub.semantic_quality import assess_semantic_result
from local_ai_hub.evidence_contract import evidence_meta
from local_ai_hub.telemetry import _safe_error_metadata
from local_ai_hub.operational_mode import (
    OperationalModeSnapshot,
    load_operational_mode,
    operational_mode_gate_error,
)

try:
    from mcp.server.fastmcp import FastMCP
    import mcp.types as mcp_types
except ImportError:
    FastMCP = None  # type: ignore[assignment,misc]
    mcp_types = None  # type: ignore[assignment]

class _MissingMCP:
    """Import-safe stand-in used only when the optional MCP SDK is unavailable.

    Keeping module import side-effect free lets diagnostics, tests, and packaging
    tooling inspect the MCP surface without requiring the transport dependency.
    Actual server execution still fails fast with an actionable dependency error.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.tools: list[Any] = []

    def tool(self):
        def decorator(fn: Any) -> Any:
            self.tools.append(fn)
            return fn

        return decorator

    def run(self) -> None:
        raise SystemExit("Missing MCP dependency. Re-run setup or install requirements-core.txt")

# Module-level initialisation: FastMCP requires tool decorators at import
# time, so HubClient, config and projectors must be created here. Any failure
# produces a clear SystemExit instead of a confusing AttributeError later.
AGENT_NAME = os.environ.get("LOCAL_AI_AGENT", "agent")
_workspace = canonical_root(Path.cwd())
_workspace_hash = hashlib.sha1(_workspace.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
TENANT = os.environ.get("LOCAL_AI_TENANT") or f"{AGENT_NAME}:{_workspace_hash}"
CONFIG_PATH = os.environ.get("LOCAL_AI_CONFIG")
_CURRENT_OPERATIONAL_CONTEXT: contextvars.ContextVar[tuple[str, bool]] = contextvars.ContextVar(
    "mcp_operational_context", default=("", True)
)


class _MCPHubClientAdapter:
    """Pass MCP action policy metadata through HubClient without changing wire payloads."""

    def __init__(self, client: HubClient) -> None:
        self._client = client
        try:
            parameters = inspect.signature(client.request).parameters
        except (AttributeError, TypeError, ValueError):
            parameters = {}
        self._supports_operational_metadata = {
            "operational_action", "requires_heavy_work"
        } <= set(parameters)
        if self._supports_operational_metadata:
            original_request = client.request

            def request_with_policy(
                path: str, payload: dict[str, Any] | None = None, **kwargs: Any
            ) -> Any:
                action, requires_heavy_work = _CURRENT_OPERATIONAL_CONTEXT.get()
                kwargs.setdefault("operational_action", action or None)
                kwargs.setdefault("requires_heavy_work", requires_heavy_work)
                return original_request(path, payload, **kwargs)

            # HubClient.post() calls self.request(), so metadata reaches in-process
            # transport without bypassing post's replay-safety and payload handling.
            client.request = request_with_policy  # type: ignore[method-assign]

    def get(self, path: str, **kwargs: Any) -> Any:
        if self._supports_operational_metadata:
            action, requires_heavy_work = _CURRENT_OPERATIONAL_CONTEXT.get()
            kwargs.setdefault("operational_action", action or None)
            kwargs.setdefault("requires_heavy_work", requires_heavy_work)
        try:
            parameters = inspect.signature(self._client.get).parameters
            has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
            if not has_var_keyword:
                kwargs = {k: v for k, v in kwargs.items() if k in parameters}
        except (AttributeError, TypeError, ValueError):
            pass
        return self._client.get(path, **kwargs)

    def status(self, detail: str = "brief", scope: str = "process") -> Any:
        if detail == "agent_state":
            return self.get("/api/status?detail=agent_state")
        return self.get(f"/api/live/status?light=1&scope={scope}&detail={detail}")

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_client", "_supports_operational_metadata"}:
            super().__setattr__(name, value)
        elif hasattr(self, "_client") and self._client is not None:
            setattr(self._client, name, value)
        else:
            super().__setattr__(name, value)


def _build_mcp_client(tenant: str, config_path: str | None) -> _MCPHubClientAdapter:
    client = HubClient(tenant=tenant, config_path=config_path, auto_start=True)
    return _MCPHubClientAdapter(client)


def _classify_mcp_operation(tool_name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    if tool_name == "local_ai_status":
        action = str(arguments.get("detail") or arguments.get("action") or "brief")
    else:
        action = str(arguments.get("action") or tool_name)
    action = action.strip().lower().replace("-", "_")
    if tool_name == "local_ai_status" and action in {"status", "health", "check", "info"}:
        action = "brief"
    lightweight_read = (
        tool_name == "local_ai_artifact"
        or (tool_name == "local_ai_status" and action in {"brief", "cache", "telemetry"})
        or (tool_name == "local_ai_repo" and action in {"map", "code_index"})
        or (
            tool_name == "local_ai_command"
            and action in {
                "cancel", "classify", "discover", "stats", "daemon_status",
                "mock_server_status", "preflight",
            }
        )
    )
    return action, not lightweight_read


def _operational_mode_rejection(
    action: str, *, requires_heavy_work: bool = True,
) -> dict[str, Any] | None:
    try:
        snapshot = load_operational_mode(configured_state_dir(CFG, create=False))
    except Exception:
        snapshot = OperationalModeSnapshot(
            "maintenance", 0, None, degraded=True,
            error="operational mode state is unavailable",
        )
    if (
        snapshot.mode == "gaming"
        and not snapshot.degraded
        and bool(getattr(FEATURES, "speculative_lint", False))
        and action == "speculative_lint"
    ):
        return None
    return operational_mode_gate_error(
        snapshot, action, requires_heavy_work=requires_heavy_work,
    )


try:
    # CLIENT = HubClient(tenant=TENANT)
    CLIENT = _build_mcp_client(TENANT, CONFIG_PATH)
    CFG = load_config(CONFIG_PATH)
    atexit.register(CLIENT.close)
    FEATURES = FeatureSet.from_config(CFG)
    MCP_CFG = CFG.get("mcp", {})
    PROJECTOR = AgentProjector(CFG)
    PROFILE_CATALOG = OllamaSubagentCatalog(CFG)
    MAX_TEXT = int(MCP_CFG.get("compact_max_text_chars", 6000))
    MAX_EVIDENCE = int(MCP_CFG.get("compact_max_evidence", 16))
    LEAN_SCHEMAS = bool(MCP_CFG.get("lean_schemas", True))
    RESPONSE_BUDGET_CFG = MCP_CFG.get("response_budget", {}) if isinstance(MCP_CFG.get("response_budget", {}), dict) else {}
    RESPONSE_BUDGET_ENABLED = bool(RESPONSE_BUDGET_CFG.get("enabled", True))
    RESPONSE_DEFAULT_TOKENS = max(128, int(RESPONSE_BUDGET_CFG.get("default_tokens", 6400)))
    RESPONSE_TOOL_TOKENS = RESPONSE_BUDGET_CFG.get("tool_tokens", {}) if isinstance(RESPONSE_BUDGET_CFG.get("tool_tokens", {}), dict) else {}
    RESPONSE_REUSE_LIMIT = max(16, int(RESPONSE_BUDGET_CFG.get("reuse_cache_size", 256)))
    CONTEXT_LEDGER = ContextLedger(max_entries=int(RESPONSE_BUDGET_CFG.get("ledger_size", 512)))
    ROOT_FAMILY_BUDGET = RootFamilyBudget(
        default_limit=int(CFG.get("workflow", {}).get("root_family_token_budget", 0) or 0),
        max_active_scopes=int(CFG.get("workflow", {}).get("root_family_max_active_scopes", 1) or 1),
    )
    ADOPTION_METRICS = AdoptionMetricsStore(configured_state_dir(CFG))
except Exception as _init_exc:  # pragma: no cover
    import sys
    print(f"[local-ai-hub] MCP server init failed: {_init_exc}", file=sys.stderr)
    raise SystemExit(1) from _init_exc


def _timeout(kind: str) -> float:
    defaults = {"quick": 180.0, "context": 600.0, "model": 1800.0, "long": 2400.0}
    return max(1.0, float(MCP_CFG.get(f"{kind}_timeout_seconds", defaults[kind])))


def _client_root(r: str = "") -> str:
    cleaned = str(r or "").strip()
    if not cleaned or cleaned == ".":
        return _workspace
    try:
        p = Path(cleaned)
        if not is_rooted_path(cleaned):
            return canonical_root(Path(_workspace) / p)
        # Preserve foreign-platform rooted paths. Calling Path.resolve() on a
        # Windows drive path while running on POSIX would incorrectly prefix cwd.
        if not p.is_absolute():
            return cleaned.replace("\\", "/")
        return canonical_root(p)
    except Exception:
        return _workspace


def _normalize_repo_search_path_hints(
    root: str, path_hints: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not isinstance(path_hints, list):
        return None, "path_hints must be an array"
    if len(path_hints) > 64:
        return None, "path_hints exceeds 64 items"
    canonical = _client_root(root)
    windows_root = PureWindowsPath(canonical)
    normalized: list[dict[str, Any]] = []
    for index, hint in enumerate(path_hints):
        if not isinstance(hint, Mapping):
            return None, f"path_hints[{index}] must be an object"
        raw_path = hint.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None, f"path_hints[{index}].path must be a non-empty string"
        try:
            if windows_root.drive:
                raw_windows = PureWindowsPath(raw_path.strip())
                if raw_windows.drive and not raw_windows.is_absolute():
                    raise ValueError("drive-relative hint")
                if raw_windows.drive or raw_windows.root:
                    candidate_text = str(raw_windows)
                    if raw_windows.root and not raw_windows.drive:
                        candidate_text = windows_root.drive + candidate_text
                else:
                    candidate_text = ntpath.join(str(windows_root), str(raw_windows))
                root_text = ntpath.normpath(str(windows_root))
                candidate_text = ntpath.normpath(candidate_text)
                common = ntpath.commonpath((root_text, candidate_text))
                if ntpath.normcase(common) != ntpath.normcase(root_text):
                    raise ValueError("hint escapes repository root")
                if os.name == "nt":
                    relative = Path(candidate_text).resolve().relative_to(Path(root_text).resolve())
                    relative_text = relative.as_posix()
                else:
                    relative_text = ntpath.relpath(candidate_text, root_text).replace("\\", "/")
            else:
                if PureWindowsPath(raw_path).drive:
                    raise ValueError("foreign drive hint")
                root_path = Path(canonical).resolve()
                raw_candidate = Path(raw_path.replace("\\", "/")).expanduser()
                if is_rooted_path(raw_path) and not raw_candidate.is_absolute():
                    raise ValueError("foreign rooted hint")
                candidate = raw_candidate if raw_candidate.is_absolute() else root_path / raw_candidate
                relative = candidate.resolve().relative_to(root_path)
                relative_text = relative.as_posix()
        except (OSError, RuntimeError, ValueError):
            return None, f"path_hints[{index}].path must resolve within root"
        hint_copy = dict(hint)
        hint_copy["path"] = relative_text or "."
        normalized.append(hint_copy)
    return normalized, None


_ACTION_ALIASES: dict[str, dict[str, str]] = {
    "coord": {
        "ctx": "context_compile",
        "compile_ctx": "context_compile",
        "neg_rec": "negative_knowledge_record",
        "neg_find": "negative_knowledge_find",
        "mem_put": "memory_record",
        "mem_rec": "memory_record",
        "mem_get": "memory_get",
        "mem_find": "memory_find",
        "mem_search": "memory_find",
        "task_new": "task_create",
        "task_chk": "task_checkpoint",
        "task_done": "task_complete",
    },
    "command": {
        "patch": "patch_and_verify",
        "fix": "auto_fix",
        "repair": "repair_loop",
        "fmt": "format",
    },
    "repo": {
        "idx": "code_index",
        "review": "review_diff",
        "sec": "security_audit",
        "ctx": "context",
    },
    "task": {
        "gen": "delegate",
        "rev": "review",
        "del": "delegate",
    },
}


def _resolve_action(tool_kind: str, action: str) -> str:
    cleaned = str(action or "").strip().lower().replace("-", "_")
    tool_aliases = _ACTION_ALIASES.get(tool_kind, {})
    return tool_aliases.get(cleaned, cleaned)


def _action_kind_for_tool(tool_name: str) -> str:
    return {
        "local_ai_coord": "coord",
        "local_ai_command": "command",
        "local_ai_repo": "repo",
        "local_ai_task": "task",
    }.get(tool_name, "")


def _action_values_with_aliases(tool_name: str, features: Any = None) -> tuple[str, ...]:
    tool_kind = _action_kind_for_tool(tool_name)
    actions = operation_actions(tool_name, features)
    aliases = _ACTION_ALIASES.get(tool_kind, {})
    return tuple(dict.fromkeys((
        *actions,
        *(alias for alias, canonical in aliases.items() if canonical in actions),
    )))


def _input_schema_with_action_aliases(tool_name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Publish short actions with the same conditional schema as their canonical action."""
    tool_kind = _action_kind_for_tool(tool_name)
    aliases = _ACTION_ALIASES.get(tool_kind, {})
    if not aliases:
        return schema

    result = copy.deepcopy(schema)
    actions = set(operation_actions(tool_name, FEATURES))
    selector_schema = result.get("properties", {}).get("action")
    if not isinstance(selector_schema, dict):
        return result
    selector_schema["enum"] = list(_action_values_with_aliases(tool_name, FEATURES))

    if tool_name == "local_ai_task":
        result.setdefault("properties", {})["request_id"] = {
            "type": "string",
            "default": "",
            "description": "Stable async-job idempotency key and request correlation ID.",
        }
        non_async_actions = sorted(actions - {"submit", "status", "wait", "result", "cancel"})
        if non_async_actions:
            result.setdefault("allOf", []).append({
                "if": {
                    "properties": {"action": {"enum": non_async_actions}},
                    "required": ["action"],
                },
                "then": {"not": {"required": ["request_id"]}},
            })

    conditions = result.setdefault("allOf", [])
    by_action = {
        row.get("if", {}).get("properties", {}).get("action", {}).get("const"): row
        for row in conditions
        if isinstance(row, dict)
    }
    for alias, canonical in aliases.items():
        canonical_rule = by_action.get(canonical)
        if canonical not in actions or canonical_rule is None:
            continue
        alias_rule = copy.deepcopy(canonical_rule)
        alias_rule["if"]["properties"]["action"]["const"] = alias
        conditions.append(alias_rule)
    return result


def _normalize_deterministic(val: Any) -> Any:
    """Sort dictionary keys and normalize microsecond timestamps to maintain stable prompt caches."""
    if isinstance(val, dict):
        out = {}
        for k in sorted(val.keys()):
            out[k] = _normalize_deterministic(val[k])
        return out
    if isinstance(val, list):
        return [_normalize_deterministic(x) for x in val]
    return val


mcp = FastMCP("Local AI Hub (compact)") if FastMCP is not None else _MissingMCP("Local AI Hub (compact)")


# ---------------------------------------------------------------------------
# Dynamic tool description builders — read FEATURES (from config) at import
# time so tool schemas reflect only the active backends.
# ---------------------------------------------------------------------------

def _actions_note(actions: list[str]) -> str:
    """Expose the action surface supported by this installation's feature gates."""
    return f" Supported actions: {', '.join(actions)}." if actions else " No actions are enabled."


def _specialized_note(tool_name: str) -> str:
    """Expose enabled feature-specific triggers alongside compact tool names."""
    notes = [line[2:] for line in FEATURES.specialized_trigger_lines() if f"`{tool_name}" in line]
    return f" Specialized triggers: {'; '.join(notes)}." if notes else ""


def _desc_status() -> str:
    if LEAN_SCHEMAS:
        return (
            "Health, cache, telemetry, and agent_state inspector. Aggregate-bounded responses; optional max_response_tokens, response_profile, reuse_key. Actions: brief, cache, telemetry, full, agent_state."
            " Use when: make one bounded health, cache, or telemetry check."
            " Skip when: repository evidence or task work is needed."
        )
    ollama_note = " ollama_online," if FEATURES.ollama else ""
    agent_state_note = " With Agent OS enabled, `detail=agent_state` summarizes durable task state." if FEATURES.agent_os else ""
    return (
        "Health/queue/token-saving status. detail: brief, cache, telemetry, full, agent_state. scope: process (default) or window."
        f" Telemetry is metadata-only.{ollama_note}"
        f"{agent_state_note}"
        f"{_specialized_note('local_ai_status')}"
        " Do not poll status during normal repository work or while preprocessing/model startup is in progress;"
        " one bounded health check is enough before native fallback."
        " Use when: make one bounded health, cache, or telemetry check."
        " Skip when: repository evidence or task work is needed."
    )


def _semantic_handoff_contract(enabled: bool, status_enabled: bool = True) -> str:
    if not enabled:
        return " Semantic delegation is unavailable because local inference is disabled."
    return (
        " Semantic delegation is on-demand: after deterministic/indexed evidence, use `local_ai_task`"
        " selectively for bounded generation, review, independent second opinions, test-log compression,"
        " commit message generation, and drafting where helpful. Cloud reasoning and planning"
        " are never blocked by mandatory local handoffs. Deterministic/indexed tools remain authoritative"
        " for exact facts, symbols, diff and tests."
    )


def _async_job_lifecycle_contract(*, include_mcp_tool: bool = True) -> str:
    contract = (
        " Async status, wait, result, and cancel work with model execution disabled; wait defaults to 90 seconds and is capped by async_jobs.wait_max_seconds and the client transport budget. A timed-out wait returns current state with wait_timeout_seconds and does not cancel the job; call result after completion instead of polling."
        " Compact lifecycle responses preserve job_id, state, artifact_id (empty until available), and expires_at (Unix timestamp seconds). Terminal job state expires at expires_at; async_jobs.result_ttl_seconds defaults to 259,200 seconds (72 hours), and artifact-store TTL must cover it."
        " Queued cancellation immediately returns terminal cancelled. Running cancellation returns running with cancel_requested=true as acknowledgement; worker completion supplies final state."
        " Direct HTTP lifecycle requests use `POST /api/async-jobs`: submit sends action=submit, job_action, and optional stable request_id; controls send action=status|wait|result|cancel with job_id, and wait also sends timeout_seconds."
    )
    if include_mcp_tool:
        contract += (
            " MCP exposes `local_ai_task(action=submit|status|wait|result|cancel, ...)`;"
            " `HubClient.submit_async_job`, `async_job_status`, `wait_async_job`, `async_job_result`, and `cancel_async_job` call the same HTTP path."
        )
    else:
        contract += (
            " MCP and HubClient retain status, wait, result, and cancel controls when model execution is disabled."
        )
    return contract + (
        " Recovery may replay only explicitly replay-safe actions with a stable request_id and remaining attempts;"
        " command-backed and unclassified actions become terminal `outcome_unknown`."
    )


def _task_delivery_contract() -> str:
    return (
        " Delivery: `sync` is default; `async` submits immediately on mapped HTTP routes; `auto` needs a positive `latency_budget_ms` and at least ten endpoint observations with p95 above budget, while sparse history stays inline."
        " HTTP delivery maps `/api/delegate`, `/api/reason`, `/api/review`, `/api/review/diff`, `/api/second-opinion`, `/api/compress`, `/api/route`, and `/api/delegate/batch` to durable actions."
        " For `delivery=auto` on `/api/review/diff`, a positive `review.max_queue_age_ms` exceeded by queue age returns a terminal 503 before cold-start handling; otherwise positive budget with fewer than five samples selects async as `cold_start_review_diff`."
        " Direct `submit` job_action accepts `batch`, `compress`, `delegate`, `reason`, `review`, `review_diff`, `route`, `second_opinion`, or `speculative_lint`; body `request_id` is the idempotency key and `X-LocalAI-Request-ID` is a separate journal ID."
        f"{_async_job_lifecycle_contract()}"
        " Start synchronously with HTTP POST `/api/delegate` or `/api/reason` or MCP `local_ai_task(action=delegate|explore|reason, conversation=true, delivery=sync)`; continue via HTTP `POST /api/conversations/continue` (`conversation_id`, `task`, optional `context`) or MCP `local_ai_task(action=continue, conversation_id=..., task=..., context=...)`."
        " `HubClient` has no dedicated start helper; use `HubClient.post` for `/api/delegate` or `/api/reason`. `HubClient.continue_conversation(conversation_id, prompt, context=...)` sends `conversation_id`, maps `prompt` to `task`, and includes optional `context`."
        " Conversation IDs are tenant-scoped; model settings stay pinned and only one turn runs at a time. Defaults: 12 turns, prompt limit from `model_conversations.max_prompt_tokens` (fallback `token_saving.max_local_input_tokens`, default 56,000), idle/active TTLs of 900/1,800 seconds, and capacity 1,000. State is process-memory only and lost on restart."
    )
def _desc_task() -> str:
    local_enabled = FEATURES.tasks and FEATURES.has_any_model()
    if not local_enabled:
        return (
            "Local inference is disabled on this installation for this tool."
            " Returns unsupported=true for local-model actions."
            " Semantic generation, exploration, reasoning, review, independent second opinions, and semantic compression are unavailable until a local model backend is enabled."
            " Use deterministic/indexed evidence only."
            " Use when: a bounded semantic task requires a local model backend."
            " Skip when: the task is trivial, pure evidence lookup, security/privacy constrained, or local-model tasks are disabled."
        )
    if LEAN_SCHEMAS:
        return (
            "Bounded local-model worker for semantic generation, exploration, reasoning, review, independent second opinions, and semantic compression. "
            "Use deterministic/indexed tools for exact facts, symbols, diff and tests; they are not substitutes for these semantic tasks. "
            f"{_semantic_handoff_contract(local_enabled, FEATURES.status)}"
            "Command failure diagnosis remains disabled by default; never pass raw logs or open-ended coding. "
            "Local AI Hub does not route or manage native Codex agents. "
            "Use when: bounded local generation, compression, review, routing, second opinion, or named advisory subagent work is needed. "
            "Skip when: task is trivial, pure evidence lookup, security/privacy constrained, no useful independent scope, or Codex-owned subagent orchestration is the right owner. "
            f"{_actions_note(FEATURES.supported_task_actions())}"
        )
    profile_note = ""
    if FEATURES.subagents and FEATURES.subagent_profiles:
        profile_names = ", ".join(f"`{p}`" for p in FEATURES.subagent_profiles)
        profile_note = (
            f" Named advisory profiles ({profile_names}) use Local AI Hub read-only tooling"
            " directly when `root` is supplied."
        )
    return (
        f"Bounded local-model worker for the main agent."
        f" Route preprocessing through `{FEATURES.background_model}`, quick tasks through `{FEATURES.fast_model}`, complex tasks through `{FEATURES.smart_model}`, and the hardest reasoning through `{FEATURES.reasoning_model}`."
        f" Explicit model overrides must match a configured model tag."
        f"{profile_note}"
        " Use deterministic/indexed tools for exact facts, symbols, diff and tests; use this worker for semantic generation, exploration, reasoning, review, independent second opinions and semantic compression after any needed evidence."
        f"{_semantic_handoff_contract(local_enabled, FEATURES.status)}"
        " Command failure diagnosis is disabled by default; enable `features.local_diagnostic_dispatch=true` only for one local diagnostic after low-confidence deterministic command parsing with an artifact reference and narrow preview, never raw logs."
        " Never automatically dispatch local inference for architecture, security, mutations, or open-ended coding."
        " Use it for bounded generation, exploration, reasoning, boilerplate, review, independent second opinions and semantic compression after any needed indexed evidence."
         " Local AI Hub does not route or manage native Codex subagents; those are managed directly by Codex outside Local AI Hub."
        f"{_actions_note(FEATURES.supported_task_actions())}"
        f"{_specialized_note('local_ai_task')}"
        " `delivery=sync` preserves the foreground contract; `async` returns a durable job now;"
        " `auto` requires a positive `latency_budget_ms` and only defers after sufficient endpoint history shows p95 above it."
        " Evaluation stores only opaque ids, booleans, and numeric metadata; it never stores prompts or source text."
        " Async wait is bounded to 90 seconds; never poll loops."
        " Start a short-lived conversation with `conversation=true` on delegate or reason, then use `continue` with its opaque `conversation_id`; conversations are sync-only and process-memory only."
        " Use when: bounded local generation, compression, review, routing, second opinion, or named advisory subagent work is needed."
        " Skip when: task is trivial, pure evidence lookup, security/privacy constrained, no useful independent scope,"
        " or Codex-owned subagent orchestration is the right owner."
    )


def _desc_repo() -> str:
    local_enabled = FEATURES.tasks and FEATURES.has_any_model()
    if not local_enabled:
        return (
            "Primary repository worker for repository navigation, symbols, and impact."
            " Local inference is disabled on this installation."
            " Semantic generation, reasoning, review, independent second opinions, and compression are unavailable until a local model backend is enabled."
            " Use deterministic/indexed evidence only for exact facts, symbols, diff, tests, and verification."
            " Native fallback requires terminal=true and retryable=false."
            " Use when: indexed repository evidence is needed."
            " Skip when: the task is not repository-scoped or fresh evidence already answers it."
        )
    if LEAN_SCHEMAS:
        return (
            "Primary repository worker for repository navigation, symbols, and impact with aggregate-bounded responses; optional max_response_tokens, response_profile, reuse_key. CALL `context` first for every non-trivial repository task: its adaptive orchestrator fuses deterministic/indexed evidence, Serena, bounded lexical search, and RAG, then returns grounded diverse context. Send the task/context rather than handmade grep terms. It accepts guarded task/phase/focus fields, requires evidence IDs and reuse candidates first, treats deterministic/indexed evidence as authoritative, limits local models to ranking/compression of structured evidence, and requires `override_reason` plus approval when requested. Raw model/debug fields stay omitted unless requested through extra_fields. Omit guarded fields to preserve legacy fast/full behavior. Use deterministic/indexed actions for exact facts, symbols, diff and tests; use `local_ai_task` for semantic generation, reasoning, review, independent second opinions and compression. `solve` preserves one bounded local pass for explicit semantic requests even when exact evidence is strong. Native fallback requires terminal=true and retryable=false. Actions: search, code_index, context, solve, review_diff, symbols, callers, dead_code."
            " Use when: every non-trivial repository task needs indexed evidence or a bounded Hub operation."
            " Skip when: the task is not repository-scoped or fresh evidence already answers it and no independent Hub scope exists."
        )
    _ = ""
    if FEATURES.has_semantic():
        _ = f" -> {FEATURES.semantic_hint()} for relationships"
    _ = ""
    if FEATURES.has_any_model():
        _ = f" -> {FEATURES.fast_model} -> smart model"
    _ = " -> RAG" if FEATURES.rag else ""
    return (
        "Primary bounded repository worker for repository navigation, symbols, and impact."
        " CALL THIS FIRST before broad repository reads/searches for any non-trivial repo task. MANDATORY GATE."
        f" Use the adaptive context orchestrator: deterministic, code_index, Serena, bounded lexical search, and RAG are fused when available;"
        " agreement is ranked, paths are deduplicated/diversified, and optional local models only rerank/compress grounded evidence."
        f" Use deterministic, code_index/search,{' ' + FEATURES.semantic_hint() + ',' if FEATURES.has_semantic() else ''}"
        " context and solve for bounded evidence and implementation support."
        " `context` is the default adaptive context pack before non-trivial planning, edit, review or test; send the task/context, not handmade grep terms. Reuse existing evidence and reuse candidates first, require evidence IDs, and treat deterministic/indexed evidence as authoritative. Guarded overrides require `override_reason` and approval when requested. Raw model/debug fields stay omitted unless requested through `extra_fields`; omitting guarded fields preserves legacy fast/full behavior."
        " For implementation, diagnosis, refactoring or complex review, call `solve` after evidence and before native edits."
        f"{' When generating, use `' + FEATURES.fast_model + '` for quick tasks, `' + FEATURES.smart_model + '` for complex work, and `' + FEATURES.reasoning_model + '` for hardest reasoning.' if local_enabled else ''}"
        " `review_diff` and `security_audit` are targeted local checks."
        f"{'  After any needed indexed evidence, use `local_ai_task` for semantic generation, reasoning, review, independent second opinions and compression. `solve` preserves one bounded local pass for explicit semantic requests even when exact evidence is strong.' if local_enabled else ''}"
        f"{_semantic_handoff_contract(local_enabled, FEATURES.status)}"
        " Codex separately decides whether to use native Codex subagents;"
        " Local AI Hub does not route or manage those agents."
        " On first use of a stable absolute root call action=preprocess exactly once and continue immediately;"
        " never poll/wait/force-refresh preprocessing."
        f" Retrieval path: context first for quality; it fans out only bounded independent backends, fuses their ranked paths, and stops optional layers on timeout/degradation. Semantic generation, reasoning, review, independent second opinions and compression use `local_ai_task` after evidence;"
        " never fan out duplicate native searches or manually translate a task into a long grep-term list."
        " Reuse fresh evidence/artifact slices and never repeat an identical root/query/action while repo state is unchanged."
        " `in_progress` means another owner is doing identical work; retryable/429/503 means back off;"
        " degraded/stale means verify only the affected slice."
        " Native fallback requires terminal=true and retryable=false."
        " Always pass the stable absolute project root; never rely on MCP cwd. Never loop or increase timeouts indefinitely."
        " Use when: every non-trivial repository task needs indexed evidence or a bounded Hub operation."
        " Skip when: the task is not repository-scoped or fresh evidence already answers it and no independent Hub scope exists."
        f"{_actions_note(FEATURES.supported_repo_actions())}"
        f"{_specialized_note('local_ai_repo')}"
    )



def _desc_rag() -> str:
    if LEAN_SCHEMAS:
        return (
            "Semantic RAG and documentation search with aggregate-bounded responses; response controls: max_response_tokens, response_profile (minimal, compact, delta), reuse_key, extra_fields for additional safe response fields. Actions: search, index, list, docset_index, docset_search, ingest_document, ingest_diagram."
            " Document ingestion requires non-empty content; title and metadata are optional."
            " Use when: cheaper indexed repository paths cannot answer a bounded semantic retrieval question."
            " Skip when: deterministic/indexed evidence is sufficient or RAG is disabled."
        )
    if not FEATURES.rag:
        return (
            "Semantic retrieval — RAG backend is disabled on this installation (`features.rag=false`)."
            " All actions return unsupported=true. Enable RAG in config.toml to activate."
            " Skip when: always (RAG disabled). Use when: never."
        )
    return (
        "Fallback semantic retrieval for the main agent only after deterministic, code_index, search"
        " and preprocessed evidence are insufficient."
        " Keep queries bounded and use it only for bounded semantic retrieval, not open-ended agent orchestration."
        f"{_actions_note(FEATURES.supported_rag_actions())}"
        f"{_specialized_note('local_ai_rag')}"
        " Response controls: max_response_tokens; response_profile minimal|compact|delta; reuse_key; extra_fields selects additional safe response fields retained by the compact projector."
        " Index is file-incremental and query-cached."
        " Do not trigger index repeatedly for a fresh stable workspace."
        " Use when: cheaper indexed repository paths cannot answer a bounded semantic retrieval question."
        " Skip when: deterministic/indexed evidence is sufficient or Codex-owned subagent orchestration is the right owner."
        " Document ingestion requires non-empty content; title and metadata are optional."
    )


def _desc_command() -> str:
    if LEAN_SCHEMAS:
        return (
            "Safe CLI command broker for test, lint, typecheck, or build commands with aggregate-bounded responses; optional max_response_tokens, response_profile, reuse_key. Native fallback requires terminal=true and retryable=false. Mutations never cache or single-flight. Speculative lint is opt-in, read-only, debounced, changed-path scoped, and cancellable. Actions: run, auto_fix, format, patch_and_verify, repair_loop, speculative_lint."
            " Use when: a repeatable test, lint, typecheck, build, analysis, or safe read-only command is needed."
            " Skip when: no command is needed or a fresh cached result already answers it."
        )
    agent_os_note = " Optional task_id and criterion link passing validation commands directly to evidence-backed VerificationReceipts." if FEATURES.agent_os else ""
    return (
        "Bounded broker for test, lint, typecheck, or build commands; also repeatable analysis/read-only commands."
        " Shared safe CLI broker."
        f"{_actions_note(FEATURES.supported_command_actions())}"
        f"{_specialized_note('local_ai_command')}"
        f"{agent_os_note}"
        " Results are keyed by command + bounded repo state and duplicate runs coalesce across agents. Reuse fresh results."
        " Mutations never cache or single-flight."
        " If run returns in_progress=true, DO NOT start the command natively or with force; continue independent work and retry later so the owner can populate the cache."
        " Native fallback requires terminal=true and retryable=false."
        " cancel only stops an active matching command. force=true is exceptional recovery/admin behavior, never a retry button."
        " Use when: a repeatable test, lint, typecheck, build, analysis, or safe read-only command is needed."
        " Skip when: no command is needed or a fresh cached result already answers it."
    )


def _desc_coord() -> str:
    if LEAN_SCHEMAS:
        return (
            "Agent OS coordination for task contracts, ownership, checkpoints, and verification receipts with aggregate-bounded responses; optional max_response_tokens, response_profile, reuse_key. Actions: claim, release, memory_record, memory_find, context_compile, task_create, task_checkpoint."
            " Use when: any non-trivial task benefits from durable state/verification, or Hub workers share edit paths or reusable findings."
            " Skip when: task is a trivial one-step lookup with no shared state to preserve."
        )
    if FEATURES.agent_os:
        agent_os_note = (
            " For non-trivial multi-step, long-running, delegated, or acceptance-criteria work, create an Agent OS task contract first;"
            " checkpoint meaningful phases, search/record durable memory as useful, compile context when resuming,"
            " and gate task completion on verification receipts."
        )
        usage_note = (
            " Use when: any non-trivial task benefits from durable state/verification, or Hub workers share edit paths or reusable findings."
            " Skip when: task is a trivial one-step lookup with no shared state to preserve."
        )
    else:
        agent_os_note = ""
        usage_note = (
            " Use when: Hub workers share edit paths, leases, or reusable findings."
            " Skip when: work is isolated and no shared Hub state or memo is involved."
        )
    return (
        "Cross-agent coordination for ownership, checkpoints, and verification receipts."
        f"{_actions_note(FEATURES.supported_coord_actions())}"
        f"{agent_os_note}"
        " Claim overlapping edit paths before concurrent Hub work."
        " Search/get memos before repeating expensive investigation and store concise reusable findings after discovery."
        " Native peer subagents are coordinated by Codex rather than by this Hub tool."
        f"{usage_note}"
    )


def _desc_work() -> str:
    if LEAN_SCHEMAS:
        return "Delegate closed, low-risk work with a verified handoff and aggregate-bounded response. Common controls: max_response_tokens, response_profile (minimal, compact, delta), reuse_key, extra_fields for additional safe response fields. Work projection controls: return_fields selects top-level fields; max_output_tokens bounds handoff text; work profiles are minimal, compact, standard, debug. Skip micro-edits and live discussion. Actions: submit, status, wait, get, cancel, continue."
    return (
        "Delegate one closed, low-risk work item with a verified handoff to Local AI Hub: plan a bounded dependency DAG, execute the smallest independently verifiable steps, "
        "apply transactional leased edits, run safe validation, verify the integrated result against the original request, and return a compact handoff. "
        "Actions: submit, status, wait, get, cancel, continue. Common response controls: max_response_tokens, response_profile=minimal|compact|delta, reuse_key, extra_fields; work projection profile=minimal|compact|standard|debug; return_fields selects only needed top-level fields; "
        "max_output_tokens bounds the handoff while full details remain artifact-backed. Use when: the task can be delegated as a self-contained repository outcome. "
        "Skip when: the agent must make an unresolved product decision, credentials/network are required, only one tiny lookup is needed, or work is micro-edits/live discussion."
    )


def _desc_artifact() -> str:
    if LEAN_SCHEMAS:
        actions = ", ".join(operation_actions("local_ai_artifact"))
        return (
            f"Fetch an exact source or log slice or bounded binary artifact metadata; binary retrieval never inlines payloads; optional max_response_tokens, response_profile, reuse_key. Actions: {actions}."
            " Use when: exact source or evidence text is required after indexed discovery."
            " Skip when: no source slice is needed or the existing compact result is sufficient."
        )
    return (
        "Fetch one exact source or log slice or bounded binary artifact metadata. Binary payloads are never inlined in MCP responses. Evidence IDs start with E."
        " Use when: exact source or evidence text is required after indexed discovery."
        " Skip when: no source slice is needed or the existing compact result is sufficient."
    )


TaskAction: TypeAlias = Literal.__getitem__(_action_values_with_aliases("local_ai_task", FEATURES))


_REPO_ACTIONS = (
    "profile", "search", "map", "code_index", "semantic", "intelligence",
    "deterministic", "context", "route", "delegate", "solve", "review_diff", "impact",
    "refactor_impact", "resolve_imports", "generate_tests", "validate_patch",
    "audit_dependencies", "ast_outline", "test_matrix", "security_audit", "git_status", "repo_state",
    "synthesize_commit", "verify", "preprocess", "preprocess_status", "preprocess_refresh",
    "preprocess_pause", "preprocess_resume", "preprocess_cancel", "preprocess_unregister",
    "context_compile", "verify_receipt", "verify_completion",
    "cross_project_graph", "cross_project_symbols", "cross_project_impact",
    "cross_repo_graph", "cross_repo_symbols", "cross_repo_impact",
    "call_graph_diff", "semantic_diff",
    "affected_tests", "topology", "ast_refactor",
    "generate_mocks", "split_changes", "synthesize_rules",
    "code_invariants", "generate_dataset", "profile_digest",
    "callers", "dead_code", "secret_scan", "schema_inspect", "explain_query", "env_compat",
    "circular_dependencies", "generate_types", "complexity", "api_spec", "dependency_slice", "migration_drift", "package_audit",
    "structural_search", "context_budget",
    "git_diff", "git_history_search", "hotspots", "generate_tests_for_diff", "cross_repo_contract",
    "reachability_dead_code", "mutation_test", "type_stubs", "skeletonize", "investigate",
    "diagnose", "briefing", "pipeline",
)


def _repo_action_type(features: Any) -> Any:
    return Literal.__getitem__(_action_values_with_aliases("local_ai_repo", features))


RepoAction: TypeAlias = _repo_action_type(None)
RagAction: TypeAlias = Literal.__getitem__(operation_actions("local_ai_rag"))
CommandAction: TypeAlias = Literal.__getitem__(_action_values_with_aliases("local_ai_command", FEATURES))
CoordAction: TypeAlias = Literal.__getitem__(_action_values_with_aliases("local_ai_coord", None))
StatusDetail: TypeAlias = Literal.__getitem__(operation_actions("local_ai_status"))
_STATUS_ACTION_ALIASES = ("status", "health", "check", "info")
StatusAction: TypeAlias = Literal.__getitem__(
    tuple(dict.fromkeys((*operation_actions("local_ai_status"), *_STATUS_ACTION_ALIASES)))
)
STATUS_DETAILS = operation_actions("local_ai_status")
STATUS_ALIASES = _STATUS_ACTION_ALIASES
STATUS_ACTIONS = ("", *StatusAction.__args__)
RepoPhase: TypeAlias = Literal.__getitem__(REPO_PHASES)
StatusScope: TypeAlias = Literal["process", "window"]
WorkAction: TypeAlias = Literal.__getitem__(operation_actions("local_ai_work"))
ArtifactAction: TypeAlias = Literal[*operation_actions("local_ai_artifact")]


def _invalid_action(tool: str, action: str, valid: tuple[str, ...], guidance: str) -> dict[str, Any]:
    if tool == "local_ai_task":
        return contract_error(
            f"Unknown {tool} action '{action}'. Use the action enum advertised by the MCP schema. {guidance}"
        )
    return contract_error(
        f"Unknown {tool} action '{action}'. Valid actions: {', '.join(valid)}. {guidance}"
    )


def _release_root_family_reservation() -> None:
    reservation = _CURRENT_ROOT_FAMILY_RESERVATION.get()
    if not reservation:
        return
    ROOT_FAMILY_BUDGET.release(
        str(reservation.get("family", "")),
        tokens=int(reservation.get("tokens", 0) or 0),
        scope=str(reservation.get("scope", "")),
    )
    _CURRENT_ROOT_FAMILY_RESERVATION.set(None)


def _release_root_family_on_exit(fn: Any) -> Any:
    @functools.wraps(fn)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        finally:
            _release_root_family_reservation()

    return wrapped



_CURRENT_EXTRA_FIELDS: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("_CURRENT_EXTRA_FIELDS", default=None)
_CURRENT_RESPONSE_OPTIONS: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("_CURRENT_RESPONSE_OPTIONS", default={})
_PENDING_MCP_ACCOUNTING: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar("_PENDING_MCP_ACCOUNTING", default=None)
_CURRENT_ROOT_FAMILY_RESERVATION: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "_CURRENT_ROOT_FAMILY_RESERVATION", default=None
)
_STATUS_PROTECTED_KEYS = (
    "success", "status_code", "error", "warning", "version", "ollama_online",
    "active_model", "queued", "inflight", "cache_hits", "coalesced_waiters",
    "net_cloud_token_delta_est", "vram_pressure", "context_budget_factor",
    "summary", "window", "queue", "hotspots", "by_operation", "error_fingerprints",
    "job_id", "trace_id", "task_id", "state", "artifact_id", "cancel_requested",
    "expires_at", "wait_timeout_seconds", "outcome_unknown", "coalesced", "idempotent_replay",
    "admission_state", "terminal", "retryable", "in_progress",
    "worktree_id", "worktree_path", "lease_id", "branch",
    "enabled", "active_tasks", "tasks_count", "incidents_count", "candidates_count", "status",
)
_RELIABILITY_PROTECTED_KEYS = (
    "success", "terminal", "retryable", "degraded", "stale",
    "fallback_used", "evidence", "evidence_ids", "cancelled", "cancel_requested", "cancel_reason",
)
_REUSE_DIGESTS: OrderedDict[str, str] = OrderedDict()
_REUSE_VALUES: OrderedDict[str, Any] = OrderedDict()
_GUARDED_CONTEXT_TOP_LEVEL = frozenset({
    "success", "status", "status_code", "terminal", "retryable", "error", "warning", "message", "stop_code",
    "context", "context_source", "continuation", "evidence", "evidence_ids", "warnings", "warning_ids",
    "adaptive_context_pack", "context_pack", "context_id", "repo_revision", "revision", "memory_revision", "degraded_reason",
    "changed_paths", "stale", "since_hash", "delta_from", "guarded", "delivery_mode", "degraded",
    "fallback_used", "requires_override", "requires_approval", "decision_recorded", "decision_persisted",
    "task_status", "waiting", "contract", "reuse", "reuse_candidates", "mappings", "model_warnings",
    "relevance", "model_degraded", "model_degraded_reason", "response_budget", "reuse_key", "reused",
    "unchanged", "preload_profile", "preload_evidence_ids",
    "task_context", "complete", "partial", "text", "source_layers", "agent_state", "repository",
    "provenance", "omitted_sections", "next_action", "estimated_tokens", "truncated",
})
_GUARDED_CONTEXT_PACK = frozenset({
    "success", "status", "status_code", "terminal", "retryable", "error", "warning", "message",
    "degraded", "fallback_used", "requires_override", "requires_approval", "decision_recorded",
    "decision_persisted", "task_status", "waiting",
    "contract", "reuse_candidates", "mappings", "warnings", "evidence", "evidence_ids", "repo_revision", "changed_paths",
    "stale", "context_id", "phase", "focus", "preload_profile", "memory_revision", "model_warnings",
    "delta_from", "since_hash", "unchanged", "reuse_pointer",
})
_GUARDED_RAW_FIELDS = frozenset({
    "raw", "prompt", "model_debug", "raw_model_output", "raw_output", "model_output", "model_response",
    "debug", "debug_trace", "trace", "full_trace", "completion", "response_raw",
})


def _guarded_field_is_safe(name: str, extra_fields: set[str]) -> bool:
    normalized = re.sub(r"[-\s]+", "_", name.strip().lower())
    if normalized in extra_fields:
        return True
    if normalized in _GUARDED_RAW_FIELDS:
        return False
    return not any(marker in normalized for marker in ("raw_", "_raw", "prompt", "debug", "trace"))


def _guarded_context_input(value: Any, *, extra_fields: list[str] | None = None, depth: int = 0, parent: str = "") -> Any:
    extra = {re.sub(r"[-\s]+", "_", str(item).strip().lower()) for item in (extra_fields or ()) if str(item).strip()}
    if isinstance(value, list):
        return [_guarded_context_input(item, extra_fields=list(extra), depth=depth + 1, parent=parent) for item in value[:64]]
    if not isinstance(value, dict):
        return value
    safe: dict[str, Any] = {}
    for raw_key, item in list(value.items())[:64]:
        key = str(raw_key)
        normalized = re.sub(r"[-\s]+", "_", key.strip().lower())
        if not _guarded_field_is_safe(key, extra):
            continue
        if depth == 0 and normalized not in _GUARDED_CONTEXT_TOP_LEVEL and normalized not in extra:
            continue
        if depth == 1 and parent in {"adaptive_context_pack", "context_pack"} and normalized not in _GUARDED_CONTEXT_PACK and normalized not in extra:
            continue
        safe[key] = _guarded_context_input(item, extra_fields=list(extra), depth=depth + 1, parent=normalized)
    return safe


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


def _response_budget(task_kind: str, options: dict[str, Any]) -> tuple[int, str, str, bool]:
    requested_profile = str(options.get("response_profile") or "").strip().lower()
    profile = requested_profile or "compact"
    if profile not in {"minimal", "compact", "standard", "debug", "delta"}:
        profile = "compact"
    if not requested_profile:
        profile = CONTEXT_LEDGER.adaptive_profile(profile)
    try:
        requested = int(options.get("max_response_tokens") or 0)
    except (TypeError, ValueError, OverflowError):
        requested = 0
    tool_name = str(options.get("tool") or "")
    configured = RESPONSE_TOOL_TOKENS.get(tool_name) or RESPONSE_TOOL_TOKENS.get(task_kind) or RESPONSE_DEFAULT_TOKENS
    if not requested:
        try:
            requested = int(configured)
        except (TypeError, ValueError, OverflowError):
            requested = RESPONSE_DEFAULT_TOKENS
    try:
        max_allowed = max(RESPONSE_DEFAULT_TOKENS, int(RESPONSE_BUDGET_CFG.get("max_tokens", RESPONSE_DEFAULT_TOKENS * 2)))
    except (TypeError, ValueError, OverflowError):
        max_allowed = RESPONSE_DEFAULT_TOKENS * 2
    requested = min(requested, max_allowed)
    if profile == "minimal":
        requested = min(requested, max(256, RESPONSE_DEFAULT_TOKENS // 2))
    elif profile == "standard":
        requested = max(requested, RESPONSE_DEFAULT_TOKENS)
    elif profile == "debug":
        requested = max(requested, int(RESPONSE_DEFAULT_TOKENS * 2))
    return max(128, requested), profile, str(options.get("reuse_key") or "")[:160], RESPONSE_BUDGET_ENABLED


def _reuse_only(key: str, value: Any) -> bool:
    return _reuse_state(key, value)[0]


def _reuse_state(key: str, value: Any) -> tuple[bool, Any]:
    if not key:
        return False, None
    digest = hashlib.sha256(repr(_normalize_deterministic(value)).encode("utf-8", errors="replace")).hexdigest()
    previous = _REUSE_DIGESTS.get(key)
    previous_value = _REUSE_VALUES.get(key)
    _REUSE_DIGESTS[key] = digest
    _REUSE_VALUES[key] = value
    _REUSE_DIGESTS.move_to_end(key)
    _REUSE_VALUES.move_to_end(key)
    while len(_REUSE_DIGESTS) > RESPONSE_REUSE_LIMIT:
        _REUSE_DIGESTS.popitem(last=False)
    while len(_REUSE_VALUES) > RESPONSE_REUSE_LIMIT:
        _REUSE_VALUES.popitem(last=False)
    return previous == digest, previous_value


def _compact(value: Any, task_kind: str = "general", extra_fields: list[str] | None = None) -> Any:
    # Capture measured savings before the projector intentionally removes internal
    # token_saving/runtime fields. Private accounting metadata is stripped by the
    # instrumented MCP boundary and never enters agent context.
    if extra_fields is None:
        extra_fields = _CURRENT_EXTRA_FIELDS.get()
    options = _CURRENT_RESPONSE_OPTIONS.get()
    rejection = _subminimum_budget_rejection(options)
    if rejection is not None:
        return rejection
    raw_value = value
    exact_artifact_text = None
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
        if len(raw_value["text"]) <= MAX_TEXT:
            exact_artifact_text = raw_value["text"]
        else:
            oversized_artifact_page = True
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
    value = attach_accounting(projected_value)
    projected = PROJECTOR.project(value, AGENT_NAME, task_kind, extra_fields=extra_fields)
    if exact_artifact_text is not None and isinstance(projected, dict):
        projected = dict(projected)
        projected["text"] = exact_artifact_text
    compact_extra_fields = extra_fields
    if task_kind == "status":
        compact_extra_fields = list(dict.fromkeys([*(extra_fields or ()), "job_id"]))
    compacted = compact_result(
        projected,
        max_text_chars=MAX_TEXT,
        max_evidence=MAX_EVIDENCE,
        extra_fields=compact_extra_fields,
    )
    compacted = _preserve_contract_state(raw_value, compacted)
    requested, profile, reuse_key, enabled = _response_budget(task_kind, options)
    if enabled:
        repeated, previous = _reuse_state(reuse_key, compacted)
        if profile == "delta" and previous is not None and not repeated:
            compacted = delta_response(previous, compacted, result_id=result_id(compacted))
        protected_keys = tuple(dict.fromkeys((
            *_RELIABILITY_PROTECTED_KEYS,
            *(_CONTEXT_PROTECTED_KEYS if task_kind in {"context", "context_compile"} else ()),
            *(_STATUS_PROTECTED_KEYS if task_kind == "status" else ()),
        )))
        compacted = budget_response(
            compacted,
            max_tokens=requested,
            profile=profile,
            reuse_key=reuse_key,
            reuse_only=repeated and json_tokens(compacted) > requested // 2,
            protected_keys=protected_keys,
            token_metadata=efficiency_metadata(),
        )
    return _normalize_deterministic(account_projection(raw_value, compacted))


_TELEMETRY_DETAIL_LABELS = {
    "status": frozenset({"complete", "incomplete"}),
    "omitted_sections": frozenset({"decision_grade_lists", "pending_events", "writer_failures"}),
}
_TELEMETRY_HOTSPOT_LABELS = {
    "type": frozenset({"reliability", "latency", "efficiency", "quality", "observability"}),
    "signal": frozenset({
        "inference_failure_rate", "queue_wait", "low_cache_hit_rate",
        "frequent_model_fallbacks", "frequent_ollama_retries", "telemetry_queue_drops",
    }),
}
_TELEMETRY_SENSITIVE_TEXT_FIELD_RE = re.compile(
    r"(?i)(error|message|exception|reason|prompt|source|body|payload|content|token|secret|password|authorization|note|raw)"
)


def _sanitize_telemetry_payload(value: Any, *, field: str = "", context: str = "") -> Any:
    """Preserve metrics and known labels while removing untrusted diagnostic text."""
    if field in {"detail", "queue", "hotspots", "decision_grade"}:
        context = field
    if isinstance(value, dict):
        return {
            str(key): _sanitize_telemetry_payload(item, field=str(key), context=context)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_telemetry_payload(item, field=field, context=context) for item in value]
    if not isinstance(value, str):
        return value

    if _TELEMETRY_SENSITIVE_TEXT_FIELD_RE.search(field):
        return "Error details omitted"
    if context == "detail":
        if field == "omitted_sections":
            return value if value in _TELEMETRY_DETAIL_LABELS["omitted_sections"] else "Error details omitted"
        return value if value in _TELEMETRY_DETAIL_LABELS.get(field, frozenset()) else "Error details omitted"
    if context == "queue":
        return "Error details omitted"
    if context == "hotspots":
        return value if value in _TELEMETRY_HOTSPOT_LABELS.get(field, frozenset()) else "Error details omitted"
    if context == "decision_grade":
        if field in {"action", "component", "error_type", "operation", "route", "signal", "type"}:
            return _safe_error_metadata(value)
        return "Error details omitted"
    if context == "error_fingerprints" and field in {"component", "error_type", "operation"}:
        return _safe_error_metadata(value)
    if context == "by_operation" and field in {"action", "event_type"}:
        return _safe_error_metadata(value)
    if context == "window" and field == "scope":
        return value if value in {"window", "process"} else "Error details omitted"
    return _safe_error_metadata(value)


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
    state_keys = {
        "success", "status_code", "error", "terminal", "retryable", "degraded",
        "stale", "evidence", "cancel", "cancelled", "timed_out",
    }
    if isinstance(raw, dict) and isinstance(projected, dict):
        for key in state_keys:
            if key not in raw:
                continue
            value = raw[key]
            if key == "error" and isinstance(value, str):
                value = value[:500]
            elif key == "evidence" and isinstance(value, list):
                value = _bound_context_json(value[:MAX_EVIDENCE])
            elif key == "cancel":
                value = _bound_context_json(value)
            projected[key] = value
        for key, value in raw.items():
            if key in projected and key not in state_keys:
                projected[key] = _preserve_contract_state(value, projected[key])
        return projected
    if isinstance(raw, list) and isinstance(projected, list):
        for index, value in enumerate(raw[:len(projected)]):
            projected[index] = _preserve_contract_state(value, projected[index])
    return projected


def _telemetry_status_projection(value: Any) -> dict[str, Any]:
    """Keep status telemetry decision-grade instead of returning the full report."""
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
    projected: dict[str, Any] = {
        "success": envelope_success and bool(report.get("success", True)),
        "window": _sanitize_telemetry_payload(report.get("window") if isinstance(report.get("window"), dict) else {}, field="window"),
        "summary": _sanitize_telemetry_payload({key: summary[key] for key in keep_summary if key in summary}, field="summary"),
        "queue": _sanitize_telemetry_payload(report.get("queue") if isinstance(report.get("queue"), dict) else summary.get("queue", {}), field="queue"),
        "hotspots": _sanitize_telemetry_payload(list(report.get("hotspots") or [])[:12], field="hotspots"),
        "by_operation": _sanitize_telemetry_payload(list(report.get("by_operation") or [])[:20], field="by_operation"),
        "error_fingerprints": _sanitize_telemetry_payload(list(report.get("error_fingerprints") or [])[:12], field="error_fingerprints"),
        "detail": _sanitize_telemetry_payload(report.get("detail") if isinstance(report.get("detail"), dict) else {}, field="detail"),
        "decision_grade": _sanitize_telemetry_payload(report.get("decision_grade") if isinstance(report.get("decision_grade"), dict) else {}, field="decision_grade"),
    }
    if value.get("error") or report.get("error"):
        projected.update(_telemetry_failure(value if value.get("error") else report))
    return projected


def _load_task_context(
    *,
    task_id: str,
    root: str,
    context: str,
    phase: str = "",
    focus: list[str] | None = None,
    preload_profile: str = "",
    changed_paths: list[str] | None = None,
    repository_revision: str = "",
    token_budget: int = 0,
) -> tuple[str, dict[str, Any]]:
    """Fetch one unified Agent OS + repository context for a model call."""
    if not task_id.strip():
        return context, {}
    payload = {
        "action": "compile",
        "task_id": task_id,
        "token_budget": token_budget or 4000,
        "root": _client_root(root),
        "phase": phase,
        "focus": list(focus or []),
        "preload_profile": preload_profile,
        "changed_paths": list(changed_paths or []),
        "repository_revision": repository_revision,
        "compact": True,
    }
    raw = CLIENT.post("/api/agent-state/context", payload, timeout=_timeout("context"))
    if not isinstance(raw, dict):
        return "", {
            "success": False,
            "terminal": True,
            "retryable": True,
            "error": "task context response must be a JSON object",
        }
    task_context = raw.get("task_context")
    if not isinstance(task_context, dict):
        # Keep legacy endpoint responses usable for callers that do not request
        # repository context, while making the missing unified layer explicit.
        task_context = {}
    if not raw.get("success", False) or not raw.get("complete", bool(task_context)):
        return "", {
            "success": False,
            "terminal": bool(raw.get("terminal", False)),
            "retryable": bool(raw.get("retryable", True)),
            "error": str(raw.get("error") or "task context is incomplete"),
            "task_context": task_context,
        }
    task_text = str(task_context.get("text") or raw.get("text") or "").strip()
    if not task_text:
        return "", {
            "success": False,
            "terminal": True,
            "retryable": False,
            "error": "task context is empty",
            "task_context": task_context,
        }
    context_id = str(task_context.get("context_id") or "")[:80]
    context_etag = str(task_context.get("etag") or "")[:80]
    evidence_ids = [str(item)[:120] for item in (task_context.get("evidence_ids") or [])[:64] if str(item)]
    receipt = (
        f"Task context receipt: context_id={context_id or 'unknown'} "
        f"etag={context_etag or 'unknown'} evidence_ids={','.join(evidence_ids) or 'none'}"
    )
    merged = "\n\n".join(part for part in (context.strip(), "Task-scoped context:\n" + task_text, receipt) if part)
    return merged, {
        "success": True,
        "context_id": context_id,
        "etag": context_etag,
        "evidence_ids": evidence_ids,
    }


def _attach_task_context_receipt(result: Any, metadata: dict[str, Any]) -> Any:
    """Expose the exact task-context receipt used by a semantic model call."""
    if not isinstance(result, dict) or not metadata.get("success"):
        return result
    enriched = dict(result)
    enriched["task_context_id"] = str(metadata.get("context_id") or "")[:80]
    enriched["task_context_etag"] = str(metadata.get("etag") or "")[:80]
    enriched["task_context_evidence_ids"] = [
        str(item)[:120] for item in (metadata.get("evidence_ids") or [])[:64] if str(item)
    ]
    return enriched


_SEMANTIC_PATH_RE = re.compile(r"(?<![\w./-])[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)+(?:\.[A-Za-z0-9_-]+)(?::\d+)?")


def _quality_check_semantic_result(
    result: Any,
    *,
    task: str,
    context: str,
    changed_paths: list[str] | None = None,
) -> Any:
    if not isinstance(result, dict) or not result.get("success", "error" not in result):
        return result
    # A semantic success is only meaningful when it carries a usable payload.
    # Empty model output used to leak through as success=true and poisoned
    # caches/async handoffs with no evidence for the caller.
    # ``answer`` is a legacy/provider-neutral text field and is valid content;
    # normalize it so the public projection has one canonical text surface.
    if result.get("answer") not in (None, "") and result.get("text") in (None, ""):
        result = dict(result)
        result["text"] = str(result.get("answer"))
    content_keys = ("text", "summary", "artifact_id", "job_id", "result", "results", "task_context", "candidate")
    has_content = any(
        key in result and result.get(key) not in (None, "", [], {})
        for key in content_keys
    )
    if not has_content:
        result = dict(result)
        result.update({
            "success": False,
            "terminal": False,
            "retryable": True,
            "error_code": "empty_semantic_result",
            "error": "Local semantic backend returned success without text, summary, result, or artifact reference.",
        })
        return result
    evidence_paths = [str(path) for path in (changed_paths or []) if str(path).strip()]
    if not evidence_paths:
        evidence_paths = list(dict.fromkeys(_SEMANTIC_PATH_RE.findall(context)))[:64]
    if not evidence_paths:
        return result
    quality = assess_semantic_result(task, evidence_paths, result)
    result["advisory_only"] = True
    result["semantic_quality"] = quality
    if not quality.get("usable", False):
        reason = quality.get("bypass_reason", quality.get("reason", "quality_gate"))
        result["quality_warning"] = f"advisory semantic output requires verification: {reason}"
        result["bypass_reason"] = reason
    return result


class _ProtocolAccountingReporter:
    """Non-blocking MCP-boundary telemetry reporter.

    Tool accounting must never add foreground latency, so calls enqueue a tiny
    metadata-only event. A lazy daemon batches events to the hub. If the hub is
    unavailable, accounting is dropped rather than delaying the agent.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=2048)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="local-ai-token-accounting", daemon=True)
            self._thread.start()

    def record(self, event: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            return
        self._ensure_worker()

    def _send(self, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        try:
            mode_state_dir = configured_state_dir(CFG, create=False)
            mode_snapshot = load_operational_mode(mode_state_dir)
            if mode_snapshot.mode != "active":
                return
        except Exception:
            pass
        operational_context = _CURRENT_OPERATIONAL_CONTEXT
        operational_token = operational_context.set(("telemetry", False))
        try:
            # batch_id prevents HubClient single-flight from coalescing two
            # numerically identical accounting batches from concurrent MCP clients.
            CLIENT.post(
                "/api/telemetry/tool-accounting",
                {"batch_id": f"{os.getpid()}-{time.time_ns()}", "events": list(events)},
                timeout=0.25,
            )
        except Exception:
            # Observability is best effort and must never become a retry/backpressure
            # path for the MCP foreground request.
            return
        finally:
            operational_context.reset(operational_token)

    def _run(self) -> None:
        batch: list[dict[str, Any]] = []
        idle_since = time.monotonic()
        while not self._stop.is_set():
            try:
                batch.append(self._queue.get(timeout=0.35))
                idle_since = time.monotonic()
            except queue.Empty:
                pass
            while len(batch) < 32:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            if batch:
                self._send(batch)
                batch.clear()
            if time.monotonic() - idle_since > 15.0:
                # Retire atomically with submit/start. A record that races with
                # retirement either makes the queue non-empty here or observes
                # _thread=None in _ensure_worker and starts a replacement.
                with self._lock:
                    if self._queue.empty() and self._thread is threading.current_thread():
                        self._thread = None
                        return
        if batch:
            self._send(batch)
        with self._lock:
            if self._thread is threading.current_thread():
                self._thread = None

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.35)
        remaining: list[dict[str, Any]] = []
        while len(remaining) < 64:
            try:
                remaining.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if remaining:
            self._send(remaining)
        client = getattr(self, "_client", None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


_ACCOUNTING_REPORTER = _ProtocolAccountingReporter()
atexit.register(_ACCOUNTING_REPORTER.close)


@functools.lru_cache(maxsize=32)
def _schema_descriptor(tool_name: str) -> dict[str, Any]:
    """Return one stable public-tool descriptor for token-cost estimation."""
    try:
        fn = globals().get(tool_name)
        desc_map = globals().get("_all_desc_map", {})
        builder = desc_map.get(tool_name) if isinstance(desc_map, dict) else None
        description = builder() if callable(builder) else (getattr(fn, "__doc__", "") or "")
        signature = str(inspect.signature(fn)) if callable(fn) else ""
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
    try:
        desc_map = globals().get("_all_desc_map", {})
        names = [name for name in desc_map if name not in set(getattr(FEATURES, "disabled_tools", []) or [])]
        return json_tokens({"tools": [_schema_descriptor(name) for name in names]})
    except Exception:
        return 0


def _record_tool_accounting(
    *, tool_name: str, arguments: dict[str, Any], response: Any,
    measured: dict[str, Any], metadata: dict[str, Any], result_id_value: str = "",
) -> None:
    try:
        event = finalize_tool_accounting(
            tool_name=tool_name, arguments=arguments, response=response, measured=measured,
            schema_tokens_est=_tool_catalog_schema_tokens(), metadata=metadata,
        )
        event.update({"tenant": TENANT, "agent": AGENT_NAME, "created_at": time.time()})
        CONTEXT_LEDGER.record(
            tool=tool_name,
            operation=str(arguments.get("action") or "default"),
            request_tokens=event["agent_tool_request_tokens_est"],
            response_tokens=event["agent_tool_response_tokens_est"],
            saved_tokens=event["projected_response_saved_tokens_est"],
            cache_outcome=event["cache_outcome"],
            result_id=result_id_value,
            session_id=TENANT,
        )
        _ACCOUNTING_REPORTER.record(event)
    except Exception:
        pass


_AGENT_DIAGNOSTIC_FIELDS = frozenset({
    "telemetry", "debug", "diagnostics", "diagnostic_artifacts", "raw", "stdout", "stderr",
    "phase_timings_ms", "duration_ms", "token_efficiency", "retrieval", "routing",
    "model_trace", "trace", "prompt_budget", "net_cloud_token_delta_est", "cache_hits",
    "coalesced_waiters", "context_budget_factor",
})


def _agent_output(value: Any, tool: str, arguments: dict[str, Any]) -> Any:
    """Keep internal observations out of ordinary agent responses.

    Canonical API results and telemetry stay intact. Explicit debug/status requests
    and individually requested extra fields retain their existing access controls.
    """
    if not isinstance(value, dict):
        return value
    if str(arguments.get("response_profile") or "").lower() == "debug":
        return _reconcile_existing_budget(value) or value
    action = str(arguments.get("action") or arguments.get("detail") or "").lower()
    if tool == "local_ai_status" and action in {"cache", "telemetry", "full", "agent_state"}:
        return _reconcile_existing_budget(value) or value
    requested = set(arguments.get("extra_fields") or ())
    if action in {"diagnostics", "route", "stats"}:
        requested.update({"diagnostics", "routing", "telemetry"})
    result = {key: item for key, item in value.items()
              if key not in _AGENT_DIAGNOSTIC_FIELDS or key in requested}
    return _reconcile_existing_budget(result) or result


def _instrumented_tool():
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
            try:
                mode_state_dir = configured_state_dir(CFG, create=False)
                mode_snapshot = load_operational_mode(mode_state_dir)
            except Exception:
                mode_snapshot = OperationalModeSnapshot(
                    "maintenance", 0, None, degraded=True,
                    error="operational mode state is unavailable",
                )
            action_name, requires_heavy_work = _classify_mcp_operation(fn.__name__, arguments)
            mode_rejection = operational_mode_gate_error(
                mode_snapshot,
                action_name,
                requires_heavy_work=requires_heavy_work,
            )
            gaming_lint = (
                mode_rejection is not None
                and mode_snapshot.mode == "gaming"
                and not mode_snapshot.degraded
                and fn.__name__ == "local_ai_command"
                and bool(getattr(FEATURES, "speculative_lint", False))
                and action_name == "speculative_lint"
            )
            operator_status = fn.__name__ == "local_ai_status" and not requires_heavy_work
            if mode_rejection is not None and not (gaming_lint or operator_status):
                return mode_rejection
            extra = arguments.get("extra_fields") or kwargs.get("extra_fields")
            token = _CURRENT_EXTRA_FIELDS.set(extra) if extra is not None else None
            response_token = _CURRENT_RESPONSE_OPTIONS.set({
                "max_response_tokens": arguments.get("max_response_tokens", 0),
                "response_profile": arguments.get("response_profile", ""),
                "reuse_key": arguments.get("reuse_key", ""),
                "tool": fn.__name__,
            })
            operational_token = _CURRENT_OPERATIONAL_CONTEXT.set(
                (action_name, requires_heavy_work)
            )
            metadata_token = set_metadata(
                task_id=arguments.get("task_id", ""),
                parent_task=arguments.get("parent_task_id", ""),
                phase=arguments.get("phase", ""),
                activity=f"{fn.__name__}:{arguments.get('action', 'default')}",
                revision=arguments.get("repository_revision") or arguments.get("repo_revision", ""),
                context_digest=context_digest(arguments.get("context", "")) if arguments.get("context") else "",
                fanout_count=len(arguments.get("tasks") or []) if isinstance(arguments.get("tasks"), list) else 0,
            )
            metadata = {}
            try:
                result = fn(*args, **kwargs)
            except Exception:
                _record_adoption(fn.__name__, arguments, None, (time.monotonic() - started) * 1000, failed=True)
                raise
            finally:
                metadata = efficiency_metadata()
                reset_metadata(metadata_token)
                if token is not None:
                    _CURRENT_EXTRA_FIELDS.reset(token)
                _CURRENT_RESPONSE_OPTIONS.reset(response_token)
                _CURRENT_OPERATIONAL_CONTEXT.reset(operational_token)
            clean, measured = pop_accounting(result)
            if (isinstance(clean, dict) and clean.get("success") is True
                    and ("routing" in (arguments.get("extra_fields") or ())
                         or arguments.get("response_profile") == "debug")):
                hint = semantic_handoff_hint(
                    fn.__name__,
                    str(arguments.get("action") or "").lower(),
                    FEATURES.tasks and FEATURES.has_any_model(),
                    FEATURES.status,
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
                    if routing_added and (requested_tokens <= 0 or json_tokens(candidate) <= requested_tokens):
                        clean = candidate
                        handoff_added = True
            clean = _agent_output(clean, fn.__name__, arguments)
            _record_adoption(fn.__name__, arguments, clean, (time.monotonic() - started) * 1000, recommended=handoff_added)
            pending = _PENDING_MCP_ACCOUNTING.get()
            if pending is None:
                _record_tool_accounting(
                    tool_name=fn.__name__, arguments=arguments, response=clean,
                    measured=measured, metadata=metadata,
                    result_id_value=clean["result_id"] if isinstance(clean, dict) and "result_id" in clean else "",
                )
            else:
                pending.append({
                    "tool_name": fn.__name__, "arguments": arguments, "response": clean,
                    "measured": measured, "metadata": metadata,
                })
            return clean

        return wrapped
    return decorator


def _adoption_reason(value: Any) -> str:
    text = str(value or "").lower()
    if "timeout" in text: return "timeout"
    if "unsupported" in text or "disabled" in text: return "unsupported"
    if "policy" in text or "forbidden" in text or "denied" in text: return "policy"
    if "validation" in text or "invalid" in text or "required" in text: return "validation"
    if "unavailable" in text or "connection" in text: return "unavailable"
    return "other"


_ADOPTION_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ADOPTION_TOOLS = {"local_ai_status", "local_ai_task", "local_ai_repo", "local_ai_rag", "local_ai_command", "local_ai_coord", "local_ai_work", "local_ai_artifact"}
_ADOPTION_ACTIONS = {
    "local_ai_status": set(operation_actions("local_ai_status")),
    "local_ai_task": set(operation_actions("local_ai_task")),
    "local_ai_repo": set(operation_actions("local_ai_repo")),
    "local_ai_rag": set(operation_actions("local_ai_rag")),
    "local_ai_command": set(operation_actions("local_ai_command")),
    "local_ai_coord": set(operation_actions("local_ai_coord")),
    "local_ai_work": set(operation_actions("local_ai_work")),
    "local_ai_artifact": set(operation_actions("local_ai_artifact")),
}


def _adoption_target(arguments: dict[str, Any]) -> tuple[str, str] | None:
    if arguments.get("adoption_signal") != "bypassed":
        return None
    tool = str(arguments.get("target_tool") or "").strip().lower()
    action = str(arguments.get("target_action") or "").strip().lower()
    if tool not in _ADOPTION_TOOLS or not _ADOPTION_IDENTIFIER.fullmatch(action) or action not in _ADOPTION_ACTIONS[tool]:
        return None
    return tool, action


def _record_adoption(tool: str, arguments: dict[str, Any], result: Any, duration_ms: float, *, failed: bool = False, recommended: bool = False) -> None:
    """Best-effort aggregate telemetry; never retain request/response values."""
    try:
        action = str(arguments.get("action") or "default").lower()
        target = _adoption_target(arguments)
        if target is not None:
            tool, action = target
        intent = {"local_ai_repo": "repository", "local_ai_command": "validation", "local_ai_coord": "coordination"}.get(tool, "hub")
        payload = result if isinstance(result, dict) else {}
        if target is not None:
            outcome, reason = "bypassed", "explicit_client_signal"
        elif failed:
            outcome, reason = "failed", "other"
        elif payload.get("fallback_used") is True:
            outcome, reason = "fallback_used", _adoption_reason(payload.get("error"))
        elif payload.get("success") is True:
            outcome, reason = "used", None
        elif payload.get("blocked") is True or payload.get("unsupported") is True:
            outcome, reason = "blocked", _adoption_reason(payload.get("error"))
        else:
            outcome, reason = "failed", _adoption_reason(payload.get("error"))
        # Do not serialize payloads merely to measure them: they can contain source,
        # prompts, paths, or secrets.  A bounded structural estimate is enough for a
        # coarse output-size bucket and never reads any value.
        output_size = min(4096, len(payload) * 64)
        ADOPTION_METRICS.record(tool, action, intent, outcome, fallback_reason=reason, duration_ms=duration_ms, output_size=output_size)
        if recommended:
            ADOPTION_METRICS.record(tool, action, intent, "recommended", duration_ms=duration_ms, output_size=output_size)
    except Exception:
        pass


@mcp.tool()
@_instrumented_tool()
def local_ai_status(action: StatusAction = "", detail: StatusDetail = "brief", scope: str = "process", extra_fields: list[str] | None = None, adoption_signal: Literal["", "bypassed"] = "", target_tool: str = "", target_action: str = "", max_response_tokens: int = 0, response_profile: str = "", reuse_key: str = "") -> dict[str, Any]:
    """Health/queue/token-saving status. detail: brief, cache, telemetry, full, agent_state. scope: process (default) or window. action is an alias for detail. To report a deliberate bypass, set adoption_signal=bypassed with validated target_tool and target_action; omitted means no bypass. Telemetry is metadata-only. Do not poll status during normal repository work or while preprocessing/model startup is in progress; one bounded health check is enough before native fallback. Use when: make one bounded health, cache, or telemetry check. Skip when: repository evidence or task work is needed."""
    if not isinstance(action, str) or action not in STATUS_ACTIONS:
        return contract_error(f"action must be one of: {', '.join(STATUS_ACTIONS[1:])}")
    if not isinstance(detail, str) or detail not in StatusDetail.__args__:
        return contract_error(f"detail must be one of: {', '.join(STATUS_DETAILS)}")
    if not isinstance(scope, str) or scope.strip().lower() not in {"process", "window"}:
        return contract_error("scope must be process or window")
    if not isinstance(max_response_tokens, int) or isinstance(max_response_tokens, bool) or not 0 <= max_response_tokens <= 100000:
        return contract_error("max_response_tokens must be between 0 and 100000")
    if action:
        act = action.strip().lower()
        if act in STATUS_DETAILS:
            detail = act  # type: ignore
        elif act in STATUS_ALIASES:
            detail = "brief"
        else:
            return contract_error(
                f"Unknown local_ai_status action '{act}'. Valid actions: {', '.join(STATUS_ACTIONS[1:])}."
            )
    if adoption_signal not in {"", "bypassed"}:
        return contract_error("adoption_signal must be empty or bypassed")
    if adoption_signal == "bypassed" and _adoption_target({"adoption_signal": adoption_signal, "target_tool": target_tool, "target_action": target_action}) is None:
        return contract_error("bypass report requires a supported target_tool and safe target_action")
    if adoption_signal == "" and (target_tool or target_action):
        return contract_error("target_tool and target_action require adoption_signal=bypassed")
    if not FEATURES.status:
        return {**contract_error("local_ai_status is disabled in configuration", status_code=403), "unsupported": True}
    scope = scope.strip().lower()
    if scope not in {"process", "window"}:
        return contract_error("scope must be process or window")
    if detail == "agent_state":
        return _compact(CLIENT.status(detail="agent_state"), "status")
    if detail == "telemetry":
        try:
            report = CLIENT.get(f"/api/telemetry/report?days=30&scope={scope}")
        except Exception as exc:
            return _compact(_telemetry_failure(exc), "status")
        projected = _telemetry_status_projection(report)
        safe_state = _sanitize_telemetry_payload(report)
        if isinstance(safe_state, dict) and "error" in projected:
            safe_state["error"] = projected["error"]
        projected = _preserve_contract_state(safe_state, projected)
        return _compact(projected, "status")
    if detail == "full":
        status = CLIENT.get(f"/api/status?scope={scope}")
        if not isinstance(status, dict):
            return contract_error("full status endpoint returned an invalid payload", status_code=502)
        status["capabilities"] = CLIENT.get("/api/capabilities")
        return _compact(status, "status")
    # Brief and cache stay on the bounded, cached live status path.
    status = CLIENT.get(f"/api/live/status?light=1&scope={scope}")
    runtime_stats = status.get("runtime_stats") if isinstance(status, dict) else {}
    if not isinstance(runtime_stats, dict):
        runtime_stats = {}
    if detail == "cache":
        projected = {
            "success": bool(status.get("hub_online", False)),
            "generation_cache": runtime_stats.get("generation_cache"),
            "semantic_cache": runtime_stats.get("semantic_cache"),
            "repo_cache": runtime_stats.get("repo_cache"),
            "repo_snapshots": runtime_stats.get("repo_snapshots"),
            "commands": runtime_stats.get("commands"),
            "lossless_router": status.get("lossless_router"),
            "pipeline": runtime_stats.get("pipeline"),
            "preprocessing": status.get("preprocessing"),
            "tool_agent": runtime_stats.get("tool_agent"),
            "circuit_breakers": status.get("circuit_breakers"),
            "fallback_count": status.get("fallback_count"),
            "embeddings": status.get("embeddings"),
            "reranker": status.get("reranker"),
            "token_saving": status.get("observability"),
            "context_ledger": CONTEXT_LEDGER.snapshot(),
        }
        return _compact(_preserve_contract_state(status, projected), "status")
    sched = status.get("scheduler", {}) if isinstance(status, dict) else {}
    saving = status.get("observability", {}) if isinstance(status, dict) else {}
    vram = status.get("vram_balancer") if isinstance(status, dict) else None
    res = {
        "success": bool(status.get("hub_online", False)),
        "version": status.get("version"),
        "ollama_online": status.get("ollama_online"),
        "active_model": sched.get("active_model"),
        "queued": sched.get("queued"),
        "inflight": sched.get("inflight"),
        "net_cloud_token_delta_est": saving.get("net_cloud_token_delta_est", 0),
        "cache_hits": saving.get("cache_hits", 0),
        "coalesced_waiters": saving.get("coalesced_waiters", 0),
    }
    if vram and isinstance(vram, dict):
        res["vram_pressure"] = vram.get("pressure_level", "nominal")
        res["context_budget_factor"] = vram.get("context_budget_factor", 1.0)
    return _preserve_contract_state(status, res)


@mcp.tool()
@_instrumented_tool()
@_release_root_family_on_exit
def local_ai_task(
    action: TaskAction,
    task: str = "",
    prompt: str = "",
    model: str = "",
    context: str = "",
    candidate: str = "",
    image_artifact_id: str = "",
    screenshot_artifact_id: str = "",
    bundle_artifact_id: str = "",
    dom_artifact_id: str = "",
    accessibility_artifact_id: str = "",
    computed_styles_artifact_id: str = "",
    runtime_artifact_id: str = "",
    network_artifact_id: str = "",
    source: str = "",
    cloud_fallback: bool = False,
    dom: str | dict[str, Any] | None = None,
    accessibility: str | dict[str, Any] | None = None,
    computed_styles: str | dict[str, Any] | None = None,
    runtime: str | dict[str, Any] | None = None,
    bundle: str | dict[str, Any] | None = None,
    html: str | None = None,
    accessibility_snapshot: str | dict[str, Any] | None = None,
    computed_style_data: str | dict[str, Any] | None = None,
    runtime_context: str | dict[str, Any] | None = None,
    viewport: dict[str, Any] | None = None,
    page: dict[str, Any] | None = None,
    complexity: str = "auto",
    max_tokens: int = 0,
    tasks: list[dict[str, Any]] | None = None,
    cases: list[dict[str, Any]] | None = None,
    delivery: str = "sync",
    latency_budget_ms: float = 0.0,
    job_action: str = "reason",
    job_id: str = "",
    request_id: str = "",
    timeout_seconds: float = 90,
    evaluation_task_id: str = "",
    evaluation_cohort: str = "",
    quality_pass: bool | None = None,
    test_pass: bool | None = None,
    evaluation_duration_ms: float = 0.0,
    evaluation_days: int = 30,
    profile: str = "",
    root: str = "",
    workspace: str = "",
    task_id: str = "",
    phase: str = "",
    focus: list[str] | None = None,
    preload_profile: str = "",
    changed_paths: list[str] | None = None,
    repository_revision: str = "",
    conversation: bool = False,
    conversation_id: str = "",
    approver: str = "",
    candidate_data: dict[str, Any] | None = None,
    format: str | dict[str, Any] | None = None,
    json_schema: dict[str, Any] | None = None,
    language: str = "auto",
    extra_fields: list[str] | None = None,
    max_response_tokens: int = 0,
    response_profile: str = "",
    reuse_key: str = "",
) -> dict[str, Any]:
    """Run one bounded semantic local-model task.

    Use deterministic/indexed tools for exact facts, symbols, diffs and tests;
    use this worker for semantic generation, exploration, reasoning, review, independent
    second opinions and semantic compression. Explicit model overrides must
    match a configured model role. Named advisory profiles use read-only
    repository tooling. Command-failure diagnosis remains opt-in and accepts
    only a narrow artifact-backed preview, never raw logs. This tool is not the
    orchestrator for native Codex subagents. The public action enum is
    feature-gated and exposed by the MCP schema, so callers must use the
    advertised actions rather than an inferred alias. Delivery and async
    constraints remain bounded; conversations are sync-only and process-memory
    only. Use when one bounded semantic task should run on a configured local
    model. Use when: one bounded semantic task should run on a configured
    local model. Skip when: local-model tasks are disabled or Codex-owned
    subagent orchestration is the right owner; Local AI Hub does not route or manage native Codex agents."""
    action = _resolve_action("task", action)
    if action not in _action_values_with_aliases("local_ai_task", FEATURES):
        return _invalid_action(
            "local_ai_task",
            action,
            _action_values_with_aliases("local_ai_task", FEATURES),
            "Use Local AI Hub only for bounded local-model work; use Codex-owned orchestration for peer subagents.",
        )
    try:
        from local_ai_hub.operational_mode import (
            load_operational_mode,
            operational_mode_gate_error,
        )

        mode_snapshot = load_operational_mode(configured_state_dir(CFG, create=False))
    except Exception:
        # Missing or unreadable mode state must fail closed for agent work.
        mode_snapshot = None
        from local_ai_hub.operational_mode import operational_mode_gate_error

    deterministic_actions = {"status", "wait", "result", "cancel", "evaluation_report"}
    mode_rejection = operational_mode_gate_error(
        mode_snapshot,
        action,
        requires_heavy_work=action not in deterministic_actions,
    )
    if mode_rejection is not None:
        return mode_rejection
    if conversation and action not in {"delegate", "explore", "reason"}:
        return {"success": False, "error": "Conversations support delegate, explore, reason and continue only", "terminal": True, "retryable": False}
    if conversation and delivery.strip().lower() != "sync":
        return {"success": False, "error": "Conversations require delivery=sync", "terminal": True, "retryable": False}
    if action in {"submit", "status", "wait", "result", "cancel"} and not getattr(FEATURES, "async_jobs", False):
        return {
            "success": False,
            "unsupported": True,
            "error": "Async job lifecycle is disabled (async_jobs.enabled=false)",
        }
    if action in {"status", "wait", "result", "cancel"}:
        payload: dict[str, Any] = {"action": action, "job_id": job_id}
        transport_timeout = _timeout("quick")
        if action == "wait":
            quick_timeout = max(0.0, float(_timeout("quick")))
            client_timeout = max(
                0.0,
                float(getattr(CLIENT, "max_request_timeout", quick_timeout)),
            )
            configured_wait = max(
                0.0,
                float(CFG.get("async_jobs", {}).get("wait_max_seconds", 90)),
            )
            requested_wait = max(0.0, float(timeout_seconds or 90))
            effective_wait = min(
                requested_wait,
                configured_wait,
                max(0.0, client_timeout - quick_timeout),
            )
            payload["timeout_seconds"] = effective_wait
            transport_timeout = min(client_timeout, effective_wait + quick_timeout)
        return _compact(
            CLIENT.post(
                "/api/async-jobs",
                payload,
                timeout=transport_timeout,
                request_id=request_id or None,
            ),
            "status",
        )
    # The static contract requires summary, evidence, analysis, limitations
    # and next step. Requests below this floor routinely truncate after a
    # generic preamble, especially on 7b/9b models. Clamp instead of rejecting
    # the task so callers keep the operation and receive a complete answer.
    if action in {"delegate", "explore", "reason", "review", "second_opinion"} and max_tokens:
        max_tokens = max(160, int(max_tokens))
    if action in {"candidate_create", "candidate_promote"}:
        if action == "candidate_create":
            cand = candidate_data or ({"name": task, "baseline_version": "baseline", "candidate_version": "candidate"} if not candidate else {"name": candidate, "baseline_version": "baseline", "candidate_version": "candidate"})
            return _compact(CLIENT.post("/api/agent-state/learning", {
                "action": "create_candidate", "candidate": cand,
            }, timeout=_timeout("quick")), "status")
        return _compact(CLIENT.post("/api/agent-state/learning", {
            "action": "promote", "candidate_id": candidate or evaluation_task_id or task, "approver": approver or "user",
        }, timeout=_timeout("quick")), "status")
    if not FEATURES.tasks or not FEATURES.has_any_model():
        return {"success": False, "unsupported": True, "error": "Local model execution is disabled (features.tasks=false or no Ollama runtime configured)"}
    context, task_context_meta = _load_task_context(
        task_id=task_id,
        root=root,
        context=context,
        phase=phase,
        focus=focus,
        preload_profile=preload_profile,
        changed_paths=changed_paths,
        repository_revision=repository_revision,
        token_budget=max_tokens,
    )
    if task_id.strip() and not task_context_meta.get("success", False):
        return task_context_meta
    context_evidence_ids = list(task_context_meta.get("evidence_ids") or [])
    if profile:
        if not PROFILE_CATALOG.enabled:
            return {"success": False, "unsupported": True, "error": "Ollama subagent profiles disabled"}
        try:
            PROFILE_CATALOG.resolve(profile)
        except ValueError as exc:
            return {"success": False, "unsupported": True, "error": str(exc)}
        if not root or not is_rooted_path(root):
            return {
                "success": False,
                "unsupported": True,
                "error": "Named Ollama profiles require an explicit absolute repository root",
            }
        if action not in {"delegate", "explore", "reason", "review", "second_opinion", "submit"}:
            return {"success": False, "unsupported": True, "error": "Ollama profiles support delegate, explore, reason, review, second_opinion and submit only"}
    if action == "submit":
        submit_payload: dict[str, Any] = {
            "action": action, "job_action": job_action, "job_id": job_id, "timeout_seconds": timeout_seconds,
            "task": task, "context": context, "candidate": candidate, "complexity": complexity,
            "max_tokens": max_tokens, "tasks": tasks or [], "profile": profile, "root": root, "workspace": workspace,
        }
        if request_id:
            submit_payload["request_id"] = request_id
        return _compact(
            CLIENT.post(
                "/api/async-jobs",
                submit_payload,
                timeout=_timeout("quick"),
                request_id=request_id or None,
            ),
            "status",
        )
    budgeted_actions = {"continue", "delegate", "explore", "reason", "review", "second_opinion", "compress"}
    if task_id.strip() and action in budgeted_actions and ROOT_FAMILY_BUDGET.default_limit:
        family_key = hashlib.sha1(_client_root(root).encode("utf-8", "replace"), usedforsecurity=False).hexdigest()[:16]
        budget_tokens = max_tokens or 4096
        budget_scope = f"{task_id}:{action}"
        admission = ROOT_FAMILY_BUDGET.reserve(
            family_key,
            input_tokens=budget_tokens,
            limit=ROOT_FAMILY_BUDGET.default_limit,
            task_id=task_id,
            scope=budget_scope,
        )
        if admission.get("status") == "rejected":
            return {
                "success": False,
                "terminal": not bool(admission.get("retryable", False)),
                "retryable": bool(admission.get("retryable", False)),
                "error": str(admission.get("reason", "root family budget denied")),
                "budget": admission,
            }
        _CURRENT_ROOT_FAMILY_RESERVATION.set({"family": family_key, "tokens": budget_tokens, "scope": budget_scope})
    if action == "continue":
        if profile:
            return {"success": False, "unsupported": True, "error": "Conversations do not support profiles"}
        if not conversation_id.strip():
            return {"success": False, "error": "conversation_id is required", "terminal": True, "retryable": False}
        return _compact(_attach_task_context_receipt(_quality_check_semantic_result(CLIENT.post("/api/conversations/continue", {
            "conversation_id": conversation_id, "task": task, "context": context,
        }, timeout=_timeout("model")), task=task, context=context, changed_paths=changed_paths), task_context_meta), "delegate")
    if profile:
        payload = {
            "profile": profile, "task": task, "context": context, "candidate": candidate,
            "complexity": complexity, "max_tokens": max_tokens, "priority": 5,
            "root": root, "workspace": workspace or None,
            "operation": action,
            "changed_paths": changed_paths or [],
            "evidence_ids": context_evidence_ids,
            "repository_revision": repository_revision,
        }
        endpoint = "/api/delegate/repo" if root else "/api/delegate"
        return _compact(_attach_task_context_receipt(_quality_check_semantic_result(CLIENT.post(endpoint, payload, timeout=_timeout("model")), task=task, context=context, changed_paths=changed_paths), task_context_meta), "delegate")
    if action in {"delegate", "explore"}:
        payload = {
            "task": task, "context": context, "complexity": complexity, "max_tokens": max_tokens or 4096,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms, "model": model,
            "operation": action, "changed_paths": changed_paths or [], "repository_revision": repository_revision,
            "evidence_ids": context_evidence_ids,
        }
        if format or json_schema:
            payload["format"] = format or json_schema
        if conversation:
            payload["conversation"] = True
        return _compact(_attach_task_context_receipt(_quality_check_semantic_result(CLIENT.post("/api/delegate", payload), task=task, context=context, changed_paths=changed_paths), task_context_meta), "explore" if action == "explore" else "delegate")
    if action == "reason":
        payload = {
            "problem": task, "context": context, "max_tokens": max_tokens or 4096,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms, "model": model,
            "operation": "reason", "changed_paths": changed_paths or [], "repository_revision": repository_revision,
            "evidence_ids": context_evidence_ids,
        }
        if format or json_schema:
            payload["format"] = format or json_schema
        if conversation:
            payload["conversation"] = True
        return _compact(_attach_task_context_receipt(_quality_check_semantic_result(CLIENT.post("/api/reason", payload), task=task, context=context, changed_paths=changed_paths), task_context_meta), "reason")
    if action == "review":
        payload = {
            "code": context, "instructions": task or "Report actionable defects only.",
            "complexity": complexity, "max_tokens": max_tokens or 4096,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms, "model": model,
            "operation": "review", "changed_paths": changed_paths or [], "repository_revision": repository_revision,
            "evidence_ids": context_evidence_ids,
        }
        if format or json_schema:
            payload["format"] = format or json_schema
        return _compact(_attach_task_context_receipt(_quality_check_semantic_result(CLIENT.post("/api/review", payload), task=task, context=context, changed_paths=changed_paths), task_context_meta), "review")
    if action == "second_opinion":
        return _compact(_attach_task_context_receipt(_quality_check_semantic_result(CLIENT.post("/api/second-opinion", {
            "question": task, "candidate": candidate, "context": context, "max_tokens": max_tokens or 4096,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms, "model": model,
            "changed_paths": changed_paths or [], "repository_revision": repository_revision,
            "evidence_ids": context_evidence_ids,
        }), task=task, context=context, changed_paths=changed_paths), task_context_meta), "second_opinion")
    if action == "compress":
        return _compact(_attach_task_context_receipt(_quality_check_semantic_result(CLIENT.post("/api/compress", {
            "text": context, "instruction": task or "Compress while preserving facts, identifiers, numbers, errors, decisions and uncertainty.",
            "target_tokens": max_tokens or 650,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms,
        }, timeout=_timeout("model")), task=task, context=context, changed_paths=changed_paths), task_context_meta), "compress")
    if action == "route":
        return _compact(CLIENT.post("/api/route", {"text": context, "query": task, "delivery": delivery, "latency_budget_ms": latency_budget_ms}, timeout=_timeout("model")), "route")
    if action == "batch":
        return _compact(CLIENT.post("/api/delegate/batch", {"tasks": tasks or [], "delivery": delivery, "latency_budget_ms": latency_budget_ms}, timeout=_timeout("long")), "delegate")
    if action == "benchmark":
        return _compact(CLIENT.post("/api/benchmark", {}, timeout=_timeout("long")), "status")
    if action == "hardware_benchmark":
        return _compact(CLIENT.post("/api/benchmark/run", {"model": model or "", "prompt": prompt or task, "num_tokens": max_tokens or 40}, timeout=_timeout("long")), "status")
    if action == "evaluation_record":
        return _compact(CLIENT.post("/api/evaluation", {
            "action": "record", "task_id": evaluation_task_id, "cohort": evaluation_cohort,
            "quality_pass": quality_pass, "test_pass": test_pass, "duration_ms": evaluation_duration_ms,
        }), "status")
    if action == "evaluation_report":
        return _compact(CLIENT.post("/api/evaluation", {"action": "report", "days": evaluation_days}), "status")
    if action == "speculative_draft":
        return _compact(CLIENT.post("/api/task/speculative_draft", {
            "task": task or prompt, "file": candidate or workspace, "context": context, "root": root,
        }, timeout=_timeout("model")), "delegate")
    if action == "vision":
        payload = {
            "prompt": prompt or task,
            "image": candidate or context,
            "model": model,
            "image_artifact_id": image_artifact_id,
            "screenshot_artifact_id": screenshot_artifact_id,
            "bundle_artifact_id": bundle_artifact_id,
            "dom_artifact_id": dom_artifact_id,
            "accessibility_artifact_id": accessibility_artifact_id,
            "computed_styles_artifact_id": computed_styles_artifact_id,
            "runtime_artifact_id": runtime_artifact_id,
            "network_artifact_id": network_artifact_id,
            "source": source,
            "cloud_fallback": cloud_fallback,
            "root": root,
        }
        if json_schema:
            payload["json_schema"] = json_schema
        for name, value in {
            "dom": dom,
            "accessibility": accessibility,
            "computed_styles": computed_styles,
            "runtime": runtime,
            "viewport": viewport,
            "page": page,
            "bundle": bundle,
            "html": html,
            "accessibility_snapshot": accessibility_snapshot,
            "computed_style_data": computed_style_data,
            "runtime_context": runtime_context,
        }.items():
            if value is not None:
                payload[name] = value
        return _compact(CLIENT.post("/api/task/vision", payload, timeout=_timeout("model")), "delegate")
    if action == "transcribe":
        transcribe_payload = {
            "audio_path": candidate or context or task or prompt,
            "model": model,
        }
        language_hint = str(language or "").strip()
        if language_hint and language_hint.casefold() != "auto":
            transcribe_payload["language"] = language_hint
        return _compact(CLIENT.post("/api/task/transcribe", transcribe_payload, timeout=_timeout("long")), "delegate")
    if action == "eval_suite":
        eval_payload: dict[str, Any] = {"suite_name": task or prompt or "default"}
        if model:
            eval_payload["model"] = model[:160]
        if cases:
            bounded_cases: list[dict[str, Any]] = []
            for raw_case in cases[:32]:
                if not isinstance(raw_case, dict):
                    continue
                bounded_cases.append({
                    "id": str(raw_case.get("id", "case"))[:120],
                    "input": str(raw_case.get("input", ""))[:4000],
                    "expected": str(raw_case.get("expected", ""))[:2000],
                })
            if bounded_cases:
                eval_payload["cases"] = bounded_cases
        return _compact(CLIENT.post("/api/task/eval_suite", eval_payload, timeout=_timeout("long")), "status")
    if action == "prompt_eval":
        return _compact(CLIENT.post("/api/task/prompt_eval", {
            "template": prompt or task, "variables": candidate_data or ({"input": context} if context else {}),
        }, timeout=_timeout("model")), "delegate")
    if action == "eval_drift":
        return _compact(CLIENT.post("/api/task/eval_drift", {
            "suite_name": task or prompt or "default",
        }, timeout=_timeout("long")), "status")
    if action == "complete_code":
        return _compact(CLIENT.post("/api/complete", {
            "prefix": prompt or context or "", "suffix": task or candidate or "", "max_tokens": max_tokens or 80,
        }, timeout=_timeout("quick")), "status")
    if action == "scaffold":
        return _compact(CLIENT.post("/api/task/scaffold", {
            "spec": prompt or task, "context": context, "language": language if (language and language != "auto") else (candidate or "python"),
            "max_tokens": max_tokens or 4096, "model": model,
        }, timeout=_timeout("model")), "delegate")
    return _invalid_action("local_ai_task", action, tuple(TaskAction.__args__), "Use Local AI Hub only for bounded local-model work; use Codex-owned orchestration for peer subagents.")


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
    if not isinstance(guarded, bool):
        return _context_input_error("guarded must be boolean")
    for name, value in (
        ("task_id", task_id), ("session_id", session_id), ("phase", phase), ("preload_profile", preload_profile),
        ("base", base), ("since_hash", since_hash), ("override_reason", override_reason),
        ("clone_id", clone_id), ("worktree_id", worktree_id), ("branch", branch),
        ("repository_id", repository_id), ("repository_revision", repository_revision),
    ):
        if not isinstance(value, str):
            return _context_input_error(f"{name} must be string")
    from .agent_consistency import normalize_context_phase
    try:
        normalize_context_phase(phase)
    except ValueError as exc:
        return _context_input_error(str(exc))
    for name, value, limit in (("focus", focus, 16), ("changed_paths", changed_paths, 64)):
        if value is not None:
            if not isinstance(value, list):
                return _context_input_error(f"{name} must be a list")
            if len(value) > limit:
                return _context_input_error(f"{name} exceeds maximum of {limit} items")
            if any(not isinstance(item, str) for item in value):
                return _context_input_error(f"{name} items must be strings")
    if not isinstance(staged, bool):
        return _context_input_error("staged must be boolean")
    if not isinstance(approval, (bool, str)):
        return _context_input_error("approval must be boolean or string")
    for name, value in (("max_tokens", max_tokens), ("token_budget", token_budget)):
        if not isinstance(value, int) or isinstance(value, bool):
            return _context_input_error(f"{name} must be integer")
        if value < 0:
            return _context_input_error(f"{name} must be non-negative")
        if value and not 128 <= value <= 20_000:
            return _context_input_error(f"{name} must be 0 or between 128 and 20000")
    if not isinstance(include_diagnostics, bool):
        return _context_input_error("include_diagnostics must be boolean")
    if token_budget and max_tokens and token_budget != max_tokens:
        return _context_input_error("token_budget and max_tokens must match when both are provided")
    guarded_requested = (
        guarded or bool(task_id.strip()) or bool(phase.strip()) or bool(session_id.strip())
        or bool(str(clone_id).strip()) or bool(str(worktree_id).strip()) or bool(str(branch).strip())
        or bool(str(repository_id).strip()) or bool(str(repository_revision).strip()) or include_diagnostics
    )
    guarded_only_values = (
        focus is not None or bool(preload_profile) or changed_paths is not None or base != "HEAD"
        or staged or bool(since_hash) or approval != "" or bool(override_reason) or bool(token_budget)
        or bool(str(clone_id).strip()) or bool(str(worktree_id).strip()) or bool(str(branch).strip())
        or bool(str(repository_id).strip()) or bool(str(repository_revision).strip()) or include_diagnostics
    )
    if guarded_only_values and not guarded_requested:
        return _context_input_error("guarded context fields require guarded=true, task_id, or phase")
    return None


def _bound_context_json(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return "[…depth…]"
    if isinstance(value, str):
        return value[:6000]
    if isinstance(value, list):
        return [_bound_context_json(item, depth + 1) for item in value[:64]]
    if isinstance(value, dict):
        return {str(key)[:160]: _bound_context_json(item, depth + 1) for key, item in list(value.items())[:64]}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:600]


def _context_pack_projection(value: Any, *, extra_fields: list[str] | None = None) -> Any:
    if not isinstance(value, dict):
        return {"success": False, "status_code": 502, "terminal": True, "retryable": True, "error": "context pack response must be a JSON object"}
    options = _CURRENT_RESPONSE_OPTIONS.get()
    rejection = _subminimum_budget_rejection(options)
    if rejection is not None:
        return rejection
    safe_value = _guarded_context_input(value, extra_fields=extra_fields) if (
        bool(value.get("guarded")) or "adaptive_context_pack" in value or "context_pack" in value
    ) else value
    projected = _compact(safe_value, "context", extra_fields=extra_fields)
    if not isinstance(projected, dict):
        return projected

    # Guard output is deterministic. Reattach its decision-grade fields after the
    # generic response budget so model/postprocess fields cannot replace them.
    pack = safe_value.get("adaptive_context_pack") or safe_value.get("context_pack")
    pack = pack if isinstance(pack, dict) else {}
    pack_key = "adaptive_context_pack" if isinstance(safe_value.get("adaptive_context_pack"), dict) else "context_pack"
    authoritative: dict[str, Any] = {}
    for key in (
        "context_id", "warnings", "repo_revision", "changed_paths", "stale",
        "delta_from", "since_hash", "unchanged", "reuse_pointer",
    ):
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
        {key: _bound_context_json(pack[key]) for key in nested_pack_fields if key in pack}
        if carries_nested_decision else {}
    )
    for key in ("error", "warning", "message"):
        if isinstance(nested_pack.get(key), str):
            nested_pack[key] = nested_pack[key][:192]
    if nested_pack and isinstance(pack.get("evidence"), list):
        nested_pack["evidence"] = [
            {
                key: _bound_context_json(item[key])
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
        if key in safe_value and key not in authoritative:
            authoritative[key] = safe_value[key]
    for key, item in authoritative.items():
        projected[key] = _bound_context_json(item)

    # Authoritative fields were attached after _compact's response budget. Run
    # the final projection through the same bounds so they cannot bypass it.
    final = compact_result(
        projected,
        max_text_chars=MAX_TEXT,
        max_evidence=MAX_EVIDENCE,
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
        final["provenance"] = evidence_meta(
            "repo.context",
            str(authoritative.get("repo_revision", safe_value.get("repo_revision", ""))),
            authoritative.get("evidence_ids", []),
            bool(authoritative.get("stale", safe_value.get("stale", False))),
            "stale" if bool(authoritative.get("stale", safe_value.get("stale", False))) else ("success" if safe_value.get("success", True) else "incomplete"),
        )
    options = _CURRENT_RESPONSE_OPTIONS.get()
    requested, profile, reuse_key, enabled = _response_budget("context", options)
    if enabled:
        protected_context_keys = (
            "success", "context_id", "repo_revision", "evidence_ids",
            "adaptive_context_pack" if "adaptive_context_pack" in final else "context_pack",
        )
        protected_context_keys += tuple(
            key for key in (
                "complete", "partial", "task_context", "etag", "omitted_sections",
                "stop_code", "degraded_reason", "context_truncated", "context_chars",
                "requires_override", "requires_approval", "decision_recorded",
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
        final = _normalize_deterministic(final)
        final = budget_response(
            final,
            max_tokens=requested,
            profile=profile,
            reuse_key=reuse_key,
            protected_keys=protected_context_keys,
            token_metadata=efficiency_metadata(),
        )
        budget_meta = final.get("response_budget") if isinstance(final, dict) else None
        if isinstance(budget_meta, dict) and "returned_tokens" in budget_meta:
            budget_meta["returned_tokens"] = json_tokens(final)
            if json_tokens(final) > requested:
                return _context_input_error("response budget metadata exceeds max_response_tokens")
        return final
    return _normalize_deterministic(final)


def _repo_pipeline_step_contract() -> dict[str, Any]:
    tool_manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(tool_manager, "_tools", {}) if tool_manager is not None else {}
    repo_tool = tools.get("local_ai_repo") if isinstance(tools, dict) else None
    parameters = getattr(repo_tool, "parameters", {}) if repo_tool is not None else {}
    properties = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
    return repo_pipeline_step_schema(properties, FEATURES.supported_repo_actions())


def _local_ai_repo_impl(
    action: RepoAction,
    root: str = ".",
    query: str = "",
    diff: str = "",
    task: str = "",
    workspace: str = "",
    path: str = "",
    base: str = "HEAD",
    staged: bool = False,
    dry_run: bool = False,
    max_tokens: int = 0,
    evidence: list[dict[str, Any]] | None = None,
    mode: str = "adaptive",
    relation: str = "",
    language: str = "auto",
    profile: str = "",
    receipt: dict[str, Any] | None = None,
    task_id: str = "",
    include_code: bool = False,
    include_tests: bool = False,
    edits: list[dict[str, Any]] | None = None,
    extra_fields: list[str] | None = None,
    max_response_tokens: int = 0,
    response_profile: str = "",
    reuse_key: str = "",
    include_diagnostics: bool = False,
    clone_id: str = "",
    worktree_id: str = "",
    branch: str = "",
    repository_id: str = "",
    session_id: str = "",
    repository_revision: str = "",
    changed_paths: list[str] | None = None,
    phase: RepoPhase = "",
    focus: list[str] | None = None,
    preload_profile: str = "",
    guarded: bool = False,
    since_hash: str = "",
    approval: str | bool = "",
    override_reason: str = "",
    token_budget: int = 0,
    is_worktree: bool = False,
    parent_root: str = "",
    steps: list[dict[str, Any]] | None = None,
    path_hints: list[dict[str, str]] | None = None,
    directory_hints: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    force_include_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Primary bounded repository worker for the main agent.

    Call this before broad repository reads/searches for any non-trivial repo
    task. Use deterministic, code-index/search, semantic, context and
    solve for repository evidence and implementation support. After needed
    evidence, route semantic generation, reasoning, review, independent second
    opinions and compression to local_ai_task; use local_ai_artifact for exact
    slices and local_ai_command for repeatable validation. Use review_diff and
    security_audit for targeted local checks. Never use this
    evidence path as a substitute for semantic local-model work. Codex manages
    native Codex subagents separately. Preprocess once per stable absolute root;
    never poll or force-refresh it. Reuse fresh evidence and respect
    in_progress, retryable and degraded states. Use when a non-trivial
    repository task needs indexed evidence or bounded Hub support; skip when
    the task is not repository-scoped and no independent Hub scope exists."""
    if not FEATURES.repo:
        return {**contract_error("local_ai_repo is disabled in configuration", status_code=403), "unsupported": True}
    if not isinstance(phase, str) or phase not in REPO_PHASES:
        return contract_error(f"phase must be one of: {', '.join(REPO_PHASES[1:])}")
    for numeric_name, numeric_value in (
        ("max_tokens", max_tokens),
        ("max_response_tokens", max_response_tokens),
        ("token_budget", token_budget),
    ):
        if isinstance(numeric_value, bool) or not isinstance(numeric_value, int):
            return contract_error(f"{numeric_name} must be an integer")
        if numeric_value < 0 or numeric_value > 100000:
            return contract_error(f"{numeric_name} must be between 0 and 100000")
    action = _resolve_action("repo", action)
    context_query = ""
    if action == "context":
        context_query = str(query).strip() or str(task).strip()
        if not context_query:
            return contract_error("context query cannot be empty")
    if action in {"preprocess", "preprocess_refresh", "preprocess_cancel", "preprocess_unregister"}:
        candidate = Path(root).expanduser()
        if not candidate.is_absolute():
            return {"success": False, "error": "Preprocessing requires an explicit absolute stable project root; do not use MCP process cwd"}
    else:
        root = _client_root(root)
    if action == "profile":
        return _compact(CLIENT.post("/api/repo/profile", {"root": root}, timeout=_timeout("quick")), "profile")
    if action == "investigate":
        return _compact(CLIENT.post("/api/repo/investigate", {
            "root": root, "query": query or task, "path": path, "include_code": include_code, "limit": 10,
        }, timeout=_timeout("quick")), "architecture")
    if action == "diagnose":
        return _compact(CLIENT.post("/api/repo/diagnose", {
            "root": root, "text": query or diff or task,
        }, timeout=_timeout("quick")), "verify")
    if action == "briefing":
        return _compact(CLIENT.post("/api/repo/briefing", {
            "root": root,
        }, timeout=_timeout("quick")), "architecture")
    if action == "batch_replace":
        if not FEATURES.batch_replacement:
            return {
                "success": False,
                "unsupported": True,
                "feature": "batch_replacement",
                "error": "batch replacement is disabled (features.batch_replacement=false)",
            }
        if not isinstance(edits, list) or not edits:
            return {"success": False, "error": "batch_replace requires a non-empty edits list"}
        return _compact(CLIENT.post("/api/code/batch_replace", {
            "root": root, "edits": edits, "dry_run": dry_run,
        }, timeout=_timeout("quick")), "verify")
    if action == "search":
        enrich = bool(include_code)
        if enrich and not FEATURES.enriched_search:
            return {
                "success": False,
                "unsupported": True,
                "feature": "enriched_search",
                "error": "enriched search is disabled (features.enriched_search=false)",
            }
        extra = list(extra_fields or [])
        if enrich:
            extra.extend(["text", "raw"])
        search_path_hints = ([{
            "path": path,
            "purpose": "repository_search",
            "scope": "repo_search",
        }] if path else [])
        search_path_hints.extend((path_hints or [])[:64])
        normalized_hints, hint_error = _normalize_repo_search_path_hints(root, search_path_hints)
        if hint_error is not None:
            return {
                "success": False, "error": hint_error, "status_code": 400,
                "terminal": True, "retryable": False,
            }
        return _compact(CLIENT.post("/api/search", {
            "root": root, "query": query or task, "top_k": 12, "enrich": enrich,
        }, timeout=min(120, _timeout("quick")), path_hints=normalized_hints or None), "search", extra_fields=extra if extra else None)
    if action == "map":
        return _compact(CLIENT.post("/api/repo/map", {"root": root, "max_symbols": 100}, timeout=_timeout("quick")), "architecture")
    if action == "code_index":
        return _compact(CLIENT.post("/api/repo/code-index", {"root": root, "query": query or task, "limit": 24, "include_code": include_code}, timeout=_timeout("quick")), "architecture")
    if action in {"semantic", "intelligence"}:
        backend = "serena" if action == "semantic" else "auto"
        operation = relation or ("find_symbol" if backend == "serena" else "search")
        return _compact(CLIENT.post("/api/code-intelligence/query", {
            "root": root, "query": query or task, "path": path, "backend": backend, "action": operation, "limit": 24,
        }, timeout=_timeout("quick")), "architecture")
    if action == "deterministic":
        return _compact(CLIENT.post("/api/repo/deterministic", {"root": root, "query": query or task, "limit": 30}, timeout=_timeout("quick")), "context")
    if action == "context":
        if mode not in {"full", "fast", "adaptive"}:
            return _context_input_error("context mode must be adaptive, full or fast")
        path_controls = {
            "path_hints": path_hints,
            "directory_hints": directory_hints,
            "exclude_paths": exclude_paths,
            "force_include_paths": force_include_paths,
        }
        supplied_path_controls = any(value is not None for value in path_controls.values())
        if supplied_path_controls and mode != "adaptive":
            return _context_input_error("path controls require mode=adaptive")
        for name, value in path_controls.items():
            if value is None:
                continue
            if not isinstance(value, list):
                return _context_input_error(f"{name} must be a list")
            if len(value) > 64:
                return _context_input_error(f"{name} exceeds maximum of 64 items")
        if path_hints is not None and any(
            not isinstance(item, dict)
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in item.items())
            for item in path_hints
        ):
            return _context_input_error("path_hints items must be string maps")
        for name, values in (("directory_hints", directory_hints), ("exclude_paths", exclude_paths), ("force_include_paths", force_include_paths)):
            if values is not None and any(not isinstance(item, str) for item in values):
                return _context_input_error(f"{name} items must be strings")
        validation = _validate_context_pack_inputs(
            task_id=task_id, session_id=session_id, phase=phase, focus=focus, preload_profile=preload_profile,
            changed_paths=changed_paths, base=base, staged=staged, guarded=guarded,
            since_hash=since_hash, approval=approval, override_reason=override_reason,
            max_tokens=max_tokens, token_budget=token_budget,
            clone_id=clone_id, worktree_id=worktree_id, branch=branch,
            repository_id=repository_id, repository_revision=repository_revision,
            include_diagnostics=include_diagnostics,
        )
        if validation is not None:
            return validation
        guarded_requested = (
            bool(guarded) or bool(str(task_id).strip()) or bool(str(phase).strip())
            or bool(str(session_id).strip()) or bool(str(clone_id).strip())
            or bool(str(worktree_id).strip()) or bool(str(branch).strip())
            or bool(str(repository_id).strip()) or bool(str(repository_revision).strip())
            or bool(include_diagnostics)
        )
        configured_tokens = CFG.get("token_saving", {}).get("default_repo_context_tokens", 8000)
        effective_tokens = token_budget or max_tokens or configured_tokens
        payload: dict[str, Any] = {
            "root": root, "query": context_query, "workspace": workspace or None,
            "max_tokens": effective_tokens,
            # Preserve adaptive as the quality-first multi-backend context path.
            # Do not silently downgrade the public default to deterministic-fast.
            "mode": "full" if mode == "full" else "adaptive" if mode == "adaptive" else "fast",
        }
        if guarded_requested:
            payload.update({
                "guarded": bool(guarded),
                "task_id": task_id,
                "phase": phase,
                "focus": list(focus or []),
                "preload_profile": preload_profile,
                "changed_paths": list(changed_paths or []),
                "base": base,
                "staged": bool(staged),
                "since_hash": since_hash,
                "approval": approval,
                "override_reason": override_reason,
                "token_budget": effective_tokens,
            })
            if session_id:
                payload["session_id"] = session_id
        for name, value in (
            ("clone_id", clone_id),
            ("worktree_id", worktree_id),
            ("branch", branch),
            ("repository_id", repository_id),
            ("repository_revision", repository_revision),
        ):
            if value:
                payload[name] = value
        if include_diagnostics:
            payload["include_diagnostics"] = True
        if supplied_path_controls:
            payload.update({name: value for name, value in path_controls.items() if value is not None})
        raw = CLIENT.post("/api/context/pack", payload, timeout=_timeout("context"))
        return _context_pack_projection(raw, extra_fields=extra_fields)
    if action == "route":
        if not path:
            return {"success": False, "error": "path is required for repo route"}
        return _compact(CLIENT.post("/api/route", {"root": root, "path": path, "query": query or task}, timeout=_timeout("model")), "route")
    if action == "delegate":
        return _compact(CLIENT.post("/api/delegate/repo", {
            "root": root, "task": task or query, "workspace": workspace or None,
            "complexity": "auto", "context_tokens": max_tokens or 0, "max_tokens": max_tokens or 4096, "profile": profile,
        }, timeout=_timeout("model")), "delegate")
    if action == "solve":
        return _compact(CLIENT.post("/api/solve/repo", {
            "root": root, "task": task or query, "workspace": workspace or None, "mode": mode,
            "complexity": "auto", "context_tokens": max_tokens or 0, "base": base, "staged": staged,
        }, timeout=_timeout("long")), "solve")
    if action == "review_diff":
        return _compact(CLIENT.post("/api/review/diff", {
            "root": root, "base": base, "staged": staged,
            "instructions": task or "Report actionable defects, regressions, security/concurrency issues and missing tests only.",
            "complexity": "auto", "max_tokens": max_tokens or 4096, "mode": mode,
            # `local_ai_repo(action="review_diff")` is a targeted repository
            # check. Return its bounded result directly; callers needing
            # durable background execution can use local_ai_task submit/wait.
            "delivery": "sync", "latency_budget_ms": 30000,
        }, timeout=_timeout("long")), "review_diff")
    if action == "impact":
        return _compact(CLIENT.post("/api/repo/impact", {"root": root, "base": base, "staged": staged}, timeout=_timeout("context")), "impact")
    if action == "refactor_impact":
        return _compact(CLIENT.post("/api/refactor_impact", {"root": root, "file": path, "symbol": query or task}, timeout=_timeout("quick")), "impact")
    if action == "resolve_imports":
        syms = [s.strip() for s in (query or task).split(",") if s.strip()]
        return _compact(CLIENT.post("/api/resolve_imports", {"root": root, "symbols": syms, "language": language or "auto"}, timeout=_timeout("quick")), "context")
    if action == "generate_tests":
        return _compact(CLIENT.post("/api/generate_tests", {"root": root, "file": path, "symbol": query or task}, timeout=_timeout("context")), "delegate")
    if action == "validate_patch":
        return _compact(CLIENT.post("/api/patch/validate", {"root": root, "patch": query or task}, timeout=_timeout("quick")), "verify")
    if action == "audit_dependencies":
        return _compact(CLIENT.post("/api/audit_dependencies", {"root": root}, timeout=_timeout("quick")), "context")
    if action == "ast_outline":
        return _compact(CLIENT.post("/api/code/ast_outline", {"root": root, "path": path or query or task}, timeout=_timeout("quick")), "architecture")
    if action == "affected_tests":
        paths_arg = [path] if path else ([query] if query and not query.startswith("-") else None)
        return _compact(CLIENT.post("/api/repo/affected_tests", {"root": root, "paths": paths_arg}, timeout=_timeout("quick")), "architecture")
    if action == "topology":
        return _compact(CLIENT.post("/api/repo/topology", {"root": root}, timeout=_timeout("quick")), "architecture")
    if action == "ast_refactor":
        return _compact(CLIENT.post("/api/code/ast_rename", {
            "root": root, "file": path, "old_symbol": query or task, "new_symbol": diff, "apply": staged,
        }, timeout=_timeout("quick")), "verify")
    if action == "generate_mocks":
        return _compact(CLIENT.post("/api/code/generate_mocks", {
            "root": root, "file": path, "symbol": query or task,
        }, timeout=_timeout("quick")), "architecture")
    if action == "split_changes":
        return _compact(CLIENT.post("/api/repo/split_changes", {
            "root": root, "paths": [path] if path else ([query] if query and not query.startswith("-") else None),
        }, timeout=_timeout("quick")), "architecture")
    if action == "synthesize_rules":
        return _compact(CLIENT.post("/api/repo/synthesize_rules", {
            "root": root, "limit": 10,
        }, timeout=_timeout("quick")), "architecture")
    if action == "test_matrix":
        return _compact(CLIENT.post("/api/test_matrix", {"root": root}, timeout=_timeout("quick")), "architecture")
    if action == "security_audit":
        return _compact(CLIENT.post("/api/security_audit", {"root": root}, timeout=_timeout("quick")), "architecture")
    if action == "git_status":
        return _compact(CLIENT.get(f"/api/git/status?root={quote(root)}"), "status")
    if action == "repo_state":
        return _compact(CLIENT.post("/api/repo/state", {"root": root}, timeout=_timeout("quick")), "status")
    if action == "synthesize_commit":
        synth_payload = {"root": root, "hint": query or task}
        if task and str(task).startswith("task-"):
            synth_payload["task_id"] = str(task)
        return _compact(CLIENT.post("/api/git/synthesize_commit", synth_payload, timeout=_timeout("quick")), "status")
    if action == "verify":
        return _compact(CLIENT.post("/api/evidence/verify", {"root": root, "evidence": evidence or []}), "verify")
    if action == "pipeline":
        pipeline_steps = steps or edits or []
        if not isinstance(pipeline_steps, list) or not pipeline_steps:
            return contract_error("pipeline action requires a non-empty 'steps' list of actions")

        step_schema = _repo_pipeline_step_contract()
        step_actions = set(step_schema["properties"]["action"].get("enum", []))
        parent_params: dict[str, Any] = {
            "root": root,
            "query": query,
            "diff": diff,
            "task": task,
            "workspace": workspace,
            "path": path,
            "base": base,
            "staged": staged,
            "dry_run": dry_run,
            "max_tokens": max_tokens,
            "evidence": evidence,
            "mode": mode,
            "relation": relation,
            "language": language,
            "profile": profile,
            "receipt": receipt,
            "task_id": task_id,
            "include_code": include_code,
            "include_tests": include_tests,
            "edits": edits,
            "extra_fields": extra_fields,
            "max_response_tokens": max_response_tokens,
            "response_profile": response_profile,
            "reuse_key": reuse_key,
            "include_diagnostics": include_diagnostics,
            "clone_id": clone_id,
            "worktree_id": worktree_id,
            "branch": branch,
            "repository_id": repository_id,
            "session_id": session_id,
            "repository_revision": repository_revision,
            "changed_paths": changed_paths,
            "phase": phase,
            "focus": focus,
            "preload_profile": preload_profile,
            "guarded": guarded,
            "since_hash": since_hash,
            "approval": approval,
            "override_reason": override_reason,
            "token_budget": token_budget,
            "is_worktree": is_worktree,
            "parent_root": parent_root,
            "path_hints": path_hints,
            "directory_hints": directory_hints,
            "exclude_paths": exclude_paths,
            "force_include_paths": force_include_paths,
        }

        def _exec_step(index: int, raw_step: Any) -> dict[str, Any]:
            step, validation_error = validate_repo_pipeline_step(
                raw_step, index=index, step_schema=step_schema, features=FEATURES
            )
            raw_action = raw_step.get("action", "") if isinstance(raw_step, Mapping) else ""
            step_action = raw_action[:128] if isinstance(raw_action, str) else ""
            step_id = raw_step.get("id", "") if isinstance(raw_step, Mapping) else ""
            step_id = step_id if isinstance(step_id, str) and step_id else f"step-{index}"
            if validation_error:
                return {
                    "index": index,
                    "id": step_id[:128],
                    "action": step_action,
                    "result": contract_error(validation_error),
                }
            assert step is not None
            step_action = step["action"]
            if step_action not in step_actions:
                return {
                    "index": index,
                    "id": step_id[:128],
                    "action": step_action,
                    "result": contract_error(f"unsupported repo pipeline action '{step_action}'"),
                }
            step_params = dict(parent_params)
            step_params.update({key: value for key, value in step.items() if key not in {"id", "action"}})
            try:
                result = _local_ai_repo_impl(action=step_action, **step_params)
            except Exception as exc:
                result = contract_error(f"pipeline step failed: {type(exc).__name__}", status_code=500)
            if not isinstance(result, dict):
                result = contract_error("pipeline step returned an invalid result", status_code=500)
            return {"index": index, "id": step_id[:128], "action": step_action, "result": result}

        has_mutations = any(
            isinstance(step, Mapping) and step.get("action") in REPO_PIPELINE_MUTATING_ACTIONS
            for step in pipeline_steps
        )
        if has_mutations or len(pipeline_steps) <= 1:
            step_results = [_exec_step(index, step) for index, step in enumerate(pipeline_steps)]
        else:
            with ThreadPoolExecutor(
                max_workers=min(MAX_REPO_PIPELINE_PARALLEL_STEPS, len(pipeline_steps)),
                thread_name_prefix="repo-pipeline",
            ) as pool:
                step_results = list(pool.map(lambda pair: _exec_step(*pair), enumerate(pipeline_steps)))
        results: dict[str, Any] = {}
        for record in step_results:
            key = record["action"] or f"step-{record['index']}"
            results[key] = record["result"]
        steps_failed = sum(record["result"].get("success") is False for record in step_results)
        return {
            "success": steps_failed == 0,
            "pipeline": True,
            "steps_total": len(pipeline_steps),
            "steps_attempted": len(pipeline_steps),
            "steps_completed": len(step_results),
            "steps_failed": steps_failed,
            "results": results,
            "step_results": step_results,
        }
    if action == "preprocess":
        return _compact(CLIENT.post("/api/preprocess", {
            "action": "start",
            "root": root,
            "is_worktree": bool(is_worktree),
            "parent_root": parent_root or "",
        }), "preprocess")
    if action == "preprocess_status":
        return _compact(CLIENT.post("/api/preprocess", {"action": "status", "root": root}), "status")
    if action == "preprocess_refresh":
        return _compact(CLIENT.post("/api/preprocess", {"action": "refresh", "root": root}), "preprocess")
    if action == "preprocess_pause":
        return _compact(CLIENT.post("/api/preprocess", {"action": "pause", "root": root}), "preprocess")
    if action == "preprocess_resume":
        return _compact(CLIENT.post("/api/preprocess", {"action": "resume", "root": root}), "preprocess")
    if action == "preprocess_cancel":
        return _compact(CLIENT.post("/api/preprocess", {"action": "cancel", "root": root}), "preprocess")
    if action == "preprocess_unregister":
        return _compact(CLIENT.post("/api/preprocess", {"action": "unregister", "root": root}), "preprocess")
    if action == "context_compile":
        return _compact(CLIENT.post("/api/agent-state/context", {
            "action": "compile", "task_id": task_id or query or task,
            "token_budget": max_tokens or 4000, "root": root,
            "include_diagnostics": bool(include_diagnostics),
            "clone_id": clone_id,
            "worktree_id": worktree_id,
            "branch": branch,
            "repository_id": repository_id,
            "session_id": session_id,
            "repository_revision": repository_revision,
            "changed_paths": changed_paths or [],
        }, timeout=_timeout("context")), "context")
    if action == "verify_receipt":
        return _compact(CLIENT.post("/api/agent-state/verification", {
            "action": "receipt", "receipt": receipt or {}, "root": root,
        }, timeout=_timeout("quick")), "verify")
    if action == "verify_completion":
        return _compact(CLIENT.post("/api/agent-state/verification", {
            "action": "completion", "task_id": task_id or query or task, "root": root,
        }, timeout=_timeout("quick")), "verify")
    if action in {"cross_project_graph", "cross_repo_graph"}:
        return _compact(CLIENT.post("/api/cross_project_graph", {"roots": [root] if root else []}, timeout=_timeout("quick")), "architecture")
    if action in {"cross_project_symbols", "cross_repo_symbols"}:
        return _compact(CLIENT.post("/api/cross_project_symbols", {"roots": [root] if root else [], "query": query or task, "limit": 50}, timeout=_timeout("quick")), "architecture")
    if action in {"cross_project_impact", "cross_repo_impact"}:
        return _compact(CLIENT.post("/api/cross_project_impact", {"roots": [root] if root else [], "symbol": query or task}, timeout=_timeout("quick")), "impact")
    if action in {"call_graph_diff", "semantic_diff"}:
        return _compact(CLIENT.post("/api/repo/call_graph_diff", {"root": root or ".", "diff": diff or "" if diff else None}, timeout=_timeout("quick")), "impact")
    if action == "code_invariants":
        return _compact(CLIENT.post("/api/repo/code_invariants", {
            "root": root, "path": path or query or task or None,
        }, timeout=_timeout("quick")), "architecture")
    if action == "generate_dataset":
        return _compact(CLIENT.post("/api/repo/generate_dataset", {
            "root": root, "schema_or_model": query or task or path,
            "count": max_tokens or 10,
            "format": relation or "json",
        }, timeout=_timeout("quick")), "architecture")
    if action == "profile_digest":
        profile_path = path or query or task
        if profile_path and not is_rooted_path(profile_path):
            profile_path = str(Path(_client_root(root)) / profile_path)
        return _compact(CLIENT.post("/api/repo/profile_digest", {
            "profile_path": profile_path, "top_n": max_tokens or 15,
        }, timeout=_timeout("quick")), "architecture")
    if action == "callers":
        return _compact(CLIENT.post("/api/repo/callers", {
            "root": root, "symbol": query or task or path, "limit": max_tokens or 50,
        }, timeout=_timeout("quick")), "architecture")
    if action == "dead_code":
        return _compact(CLIENT.post("/api/repo/dead_code", {
            "root": root, "limit": max_tokens or 50,
        }, timeout=_timeout("quick")), "architecture")
    if action == "secret_scan":
        scan_git = bool(staged or (query and ("git" in query.lower() or "history" in query.lower())))
        return _compact(CLIENT.post("/api/repo/secret_scan", {
            "root": root, "path": path or query or task or None,
            "scan_git_history": scan_git,
        }, timeout=_timeout("quick")), "architecture")
    if action == "schema_inspect":
        return _compact(CLIENT.post("/api/repo/schema_inspect", {
            "root": root, "db_path": path or query or task or None,
        }, timeout=_timeout("quick")), "architecture")
    if action == "explain_query":
        return _compact(CLIENT.post("/api/repo/explain_query", {
            "root": root, "query": query or task, "db_path": path or None,
        }, timeout=_timeout("quick")), "architecture")
    if action == "env_compat":
        return _compact(CLIENT.post("/api/repo/env_compat", {
            "root": root,
        }, timeout=_timeout("quick")), "architecture")
    if action == "circular_dependencies":
        return _compact(CLIENT.post("/api/repo/circular_dependencies", {
            "root": root, "language": query or task or "python",
        }, timeout=_timeout("quick")), "architecture")
    if action == "generate_types":
        return _compact(CLIENT.post("/api/repo/generate_types", {
            "root": root, "file": path or query or task, "write_stub": bool(diff),
        }, timeout=_timeout("quick")), "architecture")
    if action == "complexity":
        return _compact(CLIENT.post("/api/repo/complexity", {
            "root": root, "path": path or query or task or None, "max_results": max_tokens or 20,
            "include_tests": bool(include_tests),
        }, timeout=_timeout("quick")), "architecture")
    if action == "api_spec":
        return _compact(CLIENT.post("/api/repo/api_spec", {
            "root": root, "framework": query or task or None,
        }, timeout=_timeout("quick")), "architecture")
    if action == "dependency_slice":
        return _compact(CLIENT.post("/api/repo/dependency_slice", {
            "root": root, "symbol": query or task or relation, "path": path or None, "depth": max(1, min(max_tokens or 2, 8)),
        }, timeout=_timeout("quick")), "architecture")
    if action == "migration_drift":
        return _compact(CLIENT.post("/api/repo/migration_drift", {
            "root": root, "db_path": path or query or task or None,
        }, timeout=_timeout("quick")), "architecture")
    if action == "package_audit":
        return _compact(CLIENT.post("/api/repo/package_audit", {
            "root": root, "lockfile_path": path or query or task or None,
        }, timeout=_timeout("quick")), "architecture")
    if action == "structural_search":
        return _compact(CLIENT.post("/api/repo/structural_search", {
            "root": root, "pattern": query or task, "path": path or None, "max_results": max_tokens or 30,
        }, timeout=_timeout("quick")), "architecture")
    if action == "context_budget":
        files_arg = [path] if path else ([query] if query and not query.startswith("-") else [])
        return _compact(CLIENT.post("/api/repo/context_budget", {
            "root": root, "files": files_arg, "max_tokens": max_tokens or 4000,
        }, timeout=_timeout("quick")), "architecture")
    if action == "git_diff":
        return _compact(CLIENT.get(f"/api/git/diff?root={quote(root)}&path={quote(path or query or '')}&staged={'true' if staged else 'false'}&max_lines={max_tokens or 500}"), "diff")
    if action == "git_history_search":
        return _compact(CLIENT.post("/api/git/history_search", {
            "root": root, "query": query or task, "max_commits": max_tokens or 50,
        }, timeout=_timeout("quick")), "architecture")
    if action == "hotspots":
        days_val = int(diff) if (diff and diff.isdigit()) else 30
        return _compact(CLIENT.post("/api/repo/hotspots", {
            "root": root, "days": days_val, "limit": max_tokens or 20,
        }, timeout=_timeout("quick")), "architecture")
    if action == "generate_tests_for_diff":
        return _compact(CLIENT.post("/api/repo/generate_tests_for_diff", {
            "root": root, "diff": diff or query or task, "path": path or None,
        }, timeout=_timeout("context")), "delegate")
    if action == "cross_repo_contract":
        return _compact(CLIENT.post("/api/repo/cross_repo_contract", {
            "backend_root": root, "frontend_root": path or workspace or query,
        }, timeout=_timeout("quick")), "architecture")
    if action == "reachability_dead_code":
        return _compact(CLIENT.post("/api/repo/reachability_dead_code", {
            "root": root, "entrypoints": [path] if path else None,
        }, timeout=_timeout("context")), "architecture")
    if action == "mutation_test":
        return _compact(CLIENT.post("/api/repo/mutation_test", {
            "root": root, "file": path or query, "diff": diff or None,
        }, timeout=_timeout("context")), "delegate")
    if action == "type_stubs":
        return _compact(CLIENT.post("/api/repo/type_stubs", {
            "root": root, "file": path or query,
        }, timeout=_timeout("quick")), "code")
    if action == "skeletonize":
        return _compact(CLIENT.post("/api/repo/skeletonize", {
            "code": query or diff, "targets": [path] if path else None,
        }, timeout=_timeout("quick")), "code")
    return _invalid_action("local_ai_repo", action, tuple(FEATURES.supported_repo_actions()), "Keep work bounded in Local AI Hub; use Codex-owned orchestration for peer subagents.")


@mcp.tool()
@_instrumented_tool()
def local_ai_repo(
    action: RepoAction,
    root: str = ".",
    query: str = "",
    diff: str = "",
    task: str = "",
    workspace: str = "",
    path: str = "",
    base: str = "HEAD",
    staged: bool = False,
    dry_run: bool = False,
    max_tokens: int = 0,
    evidence: list[dict[str, Any]] | None = None,
    mode: str = "adaptive",
    relation: str = "",
    language: str = "auto",
    profile: str = "",
    receipt: dict[str, Any] | None = None,
    task_id: str = "",
    include_code: bool = False,
    include_tests: bool = False,
    edits: list[dict[str, Any]] | None = None,
    extra_fields: list[str] | None = None,
    max_response_tokens: int = 0,
    response_profile: str = "",
    reuse_key: str = "",
    include_diagnostics: bool = False,
    clone_id: str = "",
    worktree_id: str = "",
    branch: str = "",
    repository_id: str = "",
    session_id: str = "",
    repository_revision: str = "",
    changed_paths: list[str] | None = None,
    phase: RepoPhase = "",
    focus: list[str] | None = None,
    preload_profile: str = "",
    guarded: bool = False,
    since_hash: str = "",
    approval: str | bool = "",
    override_reason: str = "",
    token_budget: int = 0,
    is_worktree: bool = False,
    parent_root: str = "",
    steps: list[dict[str, Any]] | None = None,
    path_hints: list[dict[str, str]] | None = None,
    directory_hints: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    force_include_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Primary bounded repository worker. Use when: indexed repository evidence is needed. Skip when: fresh evidence already answers it."""
    forward: dict[str, Any] = {}
    context_controls = {
        "path_hints": path_hints,
        "directory_hints": directory_hints,
        "exclude_paths": exclude_paths,
        "force_include_paths": force_include_paths,
    }
    resolved_action = _resolve_action("repo", action)
    if any(value is not None for value in context_controls.values()):
        if resolved_action == "context":
            validation_error = validate_operation_arguments(
                "local_ai_repo", resolved_action,
                {name: value for name, value in context_controls.items() if value is not None},
            )
            if validation_error is not None:
                return {"success": False, "error": validation_error, "status_code": 400,
                        "terminal": True, "retryable": False}
            forward.update({name: value for name, value in context_controls.items() if value is not None})
        elif any(value is not None for name, value in context_controls.items() if name != "path_hints"):
            return {"success": False, "error": "directory/exclude/force path controls require action=context",
                    "status_code": 400, "terminal": True, "retryable": False}
        elif path_hints is not None:
            validation_error = validate_operation_arguments(
                "local_ai_repo", resolved_action, {"path_hints": path_hints}
            )
            if validation_error is not None:
                return {"success": False, "error": validation_error, "status_code": 400,
                        "terminal": True, "retryable": False}
            normalized_hints, error = _normalize_repo_search_path_hints(root, path_hints)
            if error is not None:
                return {"success": False, "error": error, "status_code": 400,
                        "terminal": True, "retryable": False}
            if normalized_hints:
                forward["path_hints"] = normalized_hints
    return _local_ai_repo_impl(
        action, root, query, diff, task, workspace, path, base, staged, dry_run,
        max_tokens, evidence, mode, relation, language, profile, receipt, task_id,
        include_code, include_tests, edits, extra_fields, max_response_tokens, response_profile, reuse_key,
        include_diagnostics, clone_id, worktree_id, branch, repository_id, session_id, repository_revision,
        changed_paths, phase, focus, preload_profile, guarded, since_hash, approval, override_reason,
        token_budget, is_worktree, parent_root, steps, **forward,
    )


local_ai_repo.__doc__ = _local_ai_repo_impl.__doc__


def _hide_disabled_batch_schema(mcp_runtime: Any, tool: Any) -> None:
    """Project rollout-only repository fields out of optional FastMCP schemas."""
    if hasattr(mcp_runtime, "_tool_manager") and hasattr(mcp_runtime._tool_manager, "_tools"):
        repo_tool = mcp_runtime._tool_manager._tools.get("local_ai_repo")
        if repo_tool is not None:
            properties = repo_tool.parameters.get("properties", {})
            schema = operation_tool_input_schema("local_ai_repo", FEATURES)
            repo_tool.parameters.clear()
            repo_tool.parameters.update(schema)
            properties = repo_tool.parameters.get("properties", {})
            properties.pop("edits", None)
            properties.pop("dry_run", None)
    action_type = _repo_action_type(FEATURES)
    annotations = getattr(tool, "__annotations__", None)
    if isinstance(annotations, dict):
        annotations["action"] = action_type
    parameters = []
    for parameter in inspect.signature(tool).parameters.values():
        if parameter.name in {"edits", "dry_run"}:
            continue
        if parameter.name == "action":
            parameter = parameter.replace(annotation=action_type)
        parameters.append(parameter)
    tool.__signature__ = inspect.Signature(parameters)


# Keep one public MCP tool while exposing rollout fields only in enabled schemas.
# FastMCP builds its schema at decoration time, so disabled fields need both a
# runtime-schema and introspection-signature projection after registration.
if not FEATURES.batch_replacement:
    _hide_disabled_batch_schema(mcp, local_ai_repo)


@mcp.tool()
@_instrumented_tool()
def local_ai_rag(
    action: RagAction,
    root: str = ".",
    workspace: str = "",
    query: str = "",
    top_k: int = 6,
    extra_fields: list[str] | None = None,
    max_response_tokens: int = 0,
    response_profile: str = "",
    reuse_key: str = "",
    content: str = "",
    title: str = "",
    metadata: dict[str, Any] | None = None,
    image_path: str = "",
    caption: str = "",
) -> dict[str, Any]:
    """Fallback semantic retrieval after deterministic and indexed repository evidence. Search defaults workspace to the explicit repository root. Document ingestion requires non-empty content; title and metadata are optional. Diagram ingestion requires image_path; caption and metadata are optional. Raster diagrams are indexed as metadata-only; SVG text nodes are indexed with their extraction provenance. Use when: cheaper indexed paths are insufficient. Skip when: deterministic or indexed evidence already answers the question."""
    if not FEATURES.rag:
        return {"success": False, "unsupported": True, "error": "RAG backend is disabled (features.rag=false in config.toml)"}
    action = action.strip().lower().replace("-", "_")
    root = _client_root(root)
    effective_workspace = workspace.strip() or root
    if action == "index":
        return _compact(CLIENT.post("/api/rag/index", {"root": root, "workspace": effective_workspace}, timeout=_timeout("long")))
    if action == "search":
        return _compact(CLIENT.post("/api/rag/search", {
            "query": query, "workspace": effective_workspace, "top_k": max(1, min(top_k, 12)), "use_reranker": True,
        }))
    if action == "list":
        return _compact(CLIENT.get("/api/rag/workspaces"))
    if action == "docset_index":
        return _compact(CLIENT.post("/api/rag/docset/index", {
            "name": workspace or query or "default", "root": root,
        }, timeout=_timeout("long")))
    if action == "docset_search":
        return _compact(CLIENT.post("/api/rag/docset/search", {
            "name": workspace or "default", "query": query, "top_k": max(1, min(top_k, 12)),
        }))
    if action == "ingest_document":
        if not isinstance(content, str) or not content.strip():
            return _compact({
                "success": False,
                "terminal": True,
                "retryable": False,
                "error": "content is required for ingest_document",
            }, "status")
        return _compact(CLIENT.post("/api/rag/ingest_document", {
            "workspace": workspace or "default",
            "content": content,
            "title": title,
            "metadata": metadata if isinstance(metadata, dict) else None,
        }, timeout=_timeout("quick")), "status")
    if action == "ingest_diagram":
        if not isinstance(image_path, str) or not image_path.strip():
            return _compact({
                "success": False,
                "terminal": True,
                "retryable": False,
                "error": "image_path is required for ingest_diagram",
            }, "status")
        return _compact(CLIENT.post("/api/rag/ingest_diagram", {
            "workspace": workspace or "default",
            "image_path": image_path,
            "caption": caption,
            "metadata": metadata if isinstance(metadata, dict) else None,
        }, timeout=_timeout("quick")), "status")
    return _invalid_action("local_ai_rag", action, tuple(RagAction.__args__), "Use RAG only when cheaper Local AI Hub evidence is insufficient.")



@mcp.tool()
@_instrumented_tool()
def local_ai_command(
    action: CommandAction,
    command: str = "",
    cwd: str = ".",
    timeout: int = 0,
    force: bool = False,
    task_id: str = "",
    criterion: str = "",
    auto_fix: bool = False,
    max_attempts: int = 3,
    stream: bool = False,
    stream_id: str = "",
    execution_id: str = "",
    snapshot: bool = False,
    rollback_on_failure: bool = False,
    patch: str = "",
    auto_rollback: bool = True,
    paths: list[str] | None = None,
    job_id: str = "",
    lint_action: str = "submit",
    extra_fields: list[str] | None = None,
    max_response_tokens: int = 0,
    response_profile: str = "",
    reuse_key: str = "",
) -> dict[str, Any]:
    """Bounded command broker. Set snapshot=true to record a best-effort Git snapshot. For action=run only, rollback_on_failure=true requires paths to list the flat, relative files directly under cwd that may be restored or removed; missing/unsafe paths reject execution. It cannot be combined with auto_fix. Rollback preserves all files outside that explicit scope. Other command and streaming behavior remains bounded and tenant-scoped. Use when: a repeatable test, lint, typecheck, build, analysis, or safe read-only command is needed. Skip when: no command is needed or a fresh cached result already answers it."""
    action = _resolve_action("command", action)
    _, requires_heavy_work = _classify_mcp_operation(
        "local_ai_command", {"action": action},
    )
    mode_rejection = _operational_mode_rejection(
        action, requires_heavy_work=requires_heavy_work,
    )
    if mode_rejection is not None:
        return mode_rejection
    if not FEATURES.commands:
        return {"success": False, "unsupported": True, "error": "local_ai_command is disabled in configuration"}
    eff_cwd = _client_root(cwd)
    host_timeout = _timeout("long")
    configured_command_timeout = int(CFG.get("commands", {}).get("timeout_seconds", 1800))
    requested_timeout = int(timeout or configured_command_timeout)
    # The command itself must finish before the MCP/HTTP caller's hard deadline so
    # there is always time to serialize the cached result instead of timing out at
    # exactly the same instant as the child process.
    effective_command_timeout = max(1, min(requested_timeout, max(1, int(host_timeout) - 30)))
    if action not in CommandAction.__args__:
        return _invalid_action("local_ai_command", action, tuple(CommandAction.__args__), "Use this broker for bounded commands; keep peer-agent orchestration in Codex.")
    if rollback_on_failure and (action != "run" or auto_fix):
        return {
            "success": False,
            "error": "rollback_on_failure is supported only for direct run actions",
            "rollback_unsupported_action": True,
            "terminal": True,
            "retryable": False,
        }
    if action == "speculative_lint":
        payload = {
            "action": str(lint_action or "submit").strip().lower().replace("-", "_"),
            "root": eff_cwd,
            "paths": paths or [],
            "command": command,
            "job_id": job_id or execution_id,
        }
        return _compact(CLIENT.post("/api/speculative-lint", payload, timeout=host_timeout), "command")
    if action.startswith("mock_server"):
        sub_act = "start" if action in {"mock_server", "mock_server_start"} else "stop" if action == "mock_server_stop" else "status"
        port_val = int(command) if (command and command.isdigit()) else 11440
        return _compact(CLIENT.post("/api/command/mock_server", {
            "action": sub_act, "root": eff_cwd, "port": port_val, "spec_path": criterion or None,
        }, timeout=host_timeout), "command")
    paths_payload = (
        paths if rollback_on_failure else
        ([command] if (action == "format" and command and not command.startswith("-")) else None)
    )
    return _compact(CLIENT.post("/api/command", {
        "action": action, "command": command, "cwd": eff_cwd, "root": eff_cwd,
        "timeout": effective_command_timeout, "force": force,
        "task_id": task_id, "criterion": criterion,
        "auto_fix": auto_fix, "max_attempts": max_attempts,
        "stream": stream, "stream_id": stream_id, "execution_id": execution_id,
        "snapshot": snapshot, "rollback_on_failure": rollback_on_failure,
        "paths": paths_payload,
        "patch": patch,
        "auto_rollback": auto_rollback,
    }, timeout=host_timeout), "command")


@mcp.tool()
@_instrumented_tool()
def local_ai_coord(
    action: CoordAction,
    root: str = ".",
    paths: list[str] | None = None,
    lease_id: str = "",
    key: str = "",
    value: str = "",
    query: str = "",
    command: str = "",
    ttl_seconds: int = 0,
    max_tokens: int = 0,
    task: str = "",
    task_id: str = "",
    contract: dict[str, Any] | None = None,
    checkpoint: dict[str, Any] | None = None,
    status: str = "",
    reason: str = "",
    record: dict[str, Any] | None = None,
    record_id: str = "",
    criterion: str = "",
    board_id: str = "",
    section: str = "",
    scope: str = "",
    scope_id: str = "",
    target_scope: str = "",
    approver: str = "",
    fingerprint: dict[str, Any] | None = None,
    tool_outcome: dict[str, Any] | None = None,
    extra_fields: list[str] | None = None,
    max_response_tokens: int = 0,
    response_profile: str = "",
    reuse_key: str = "",
    include_diagnostics: bool = False,
    include_stale: bool = False,
    clone_id: str = "",
    worktree_id: str = "",
    branch: str = "",
    repository_id: str = "",
    session_id: str = "",
    tenant: str = "",
    repository_revision: str = "",
    phase: str = "",
    focus: list[str] | None = None,
    preload_profile: str = "",
    since_hash: str = "",
    expected_version: int | None = None,
    after_seq: int = 0,
) -> dict[str, Any]:
    """Cross-agent coordination for the main agent and bounded Hub workers. Actions: claim, release, leases, memo_put, memo_get, memo_search, memo_delete, task_create, task_get, task_checkpoint, task_rollback, task_transition, task_resume, task_list, task_complete, task_fail, task_heartbeat, memory_record, memory_get, memory_find, memory_delete, memory_promote, memory_reap, context_compile, verify_receipt, verify_completion, negative_knowledge_record, negative_knowledge_find, incident_decision, blackboard_update, blackboard_get, blackboard_list, blackboard_merge, blackboard_delete, swarm_dispatch, swarm_step, swarm_status, swarm_list, swarm_cancel. Claim overlapping edit paths before concurrent Hub work. Search/get memos before repeating expensive investigation and store concise reusable findings after discovery. Native peer subagents are coordinated by Codex rather than by this Hub tool. Use when: Hub workers share edit paths, leases, or reusable findings. Skip when: work is isolated and no shared Hub state or memo is involved."""
    if not FEATURES.coord:
        return {"success": False, "unsupported": True, "error": "local_ai_coord is disabled in configuration"}
    if isinstance(after_seq, bool) or not isinstance(after_seq, int) or not 0 <= after_seq <= MAX_EVENT_SEQUENCE:
        return contract_error(f"after_seq must be an integer between 0 and {MAX_EVENT_SEQUENCE}")
    action = _resolve_action("coord", action)
    requested_root = str(root or "").strip()
    root = _client_root(root)
    if action == "task_sync":
        sync_act = status.lower() if status in ("export", "import") else "export"
        if sync_act == "export":
            return _compact(CLIENT.post("/api/agent-state/events/delta", {
                "action": "export", "stream_id": key or task_id or "", "after_seq": int(ttl_seconds or 0), "limit": max_tokens or 1000,
            }, timeout=_timeout("quick")), "status")
        else:
            return _compact(CLIENT.post("/api/agent-state/events/delta", {
                "action": "import", "events": record or [],
            }, timeout=_timeout("quick")), "status")
    if action == "task_zombie_reap":
        return _compact(CLIENT.post("/api/agent-state/tasks", {
            "action": "reap_expired", "auto_recover": True,
        }, timeout=_timeout("quick")), "status")
    if action == "task_cleanup_worktree":
        return _compact(CLIENT.post("/api/agent-state/tasks", {
            "action": "cleanup_worktree", "task_id": task_id or key or "",
        }, timeout=_timeout("quick")), "status")
    if action.startswith("task_"):
        task_kwargs = {
            "action": action, "task_id": task_id, "contract": contract,
            "checkpoint": checkpoint, "status": status, "reason": reason,
            "root": root, "ttl_seconds": ttl_seconds, "include_stale": include_stale,
        }
        if action == "task_list":
            task_kwargs["query"] = query
        if action == "task_create" and task:
            task_kwargs["task"] = task
        return _compact(CLIENT.coord(
            **task_kwargs,
        ), "status")
    if action.startswith("memory_"):
        memory_kwargs = dict(
            action=action, record=record, record_id=record_id,
            target_scope=target_scope, approver=approver, key=key,
            value=value, query=query, root=(root if requested_root else ""), scope=scope, scope_id=scope_id,
            task_id=task_id, session_id=session_id, clone_id=clone_id,
            worktree_id=worktree_id, branch=branch, repository_id=repository_id, tenant=tenant,
        )
        if ttl_seconds is not None and ttl_seconds > 0:
            memory_kwargs["ttl_seconds"] = ttl_seconds
        return _compact(CLIENT.coord(**memory_kwargs), "status")
    if action.startswith("relation_"):
        return _compact(CLIENT.coord(
            action=action, source_entity=key or task_id or query or task,
            relation=reason or status or "relates_to",
            target_entity=value or target_scope or "",
            weight=float(ttl_seconds or 1.0) if ttl_seconds else 1.0,
            metadata=record,
            start_entity=key or task_id or query or task,
            max_depth=max_tokens or 2,
            limit=max_tokens or 50,
        ), "status")
    if action == "context_compile":
        since_hash = str(since_hash or fingerprint or record_id or status or "")
        return _compact(CLIENT.post("/api/agent-state/context", {
            "action": "compile", "task_id": task_id or query or value or key,
            "token_budget": max_tokens or ttl_seconds or 4000, "root": root,
            "changed_paths": paths or [],
            "since_hash": since_hash,
            "compact": True,
            "include_diagnostics": bool(include_diagnostics),
            "clone_id": clone_id,
            "worktree_id": worktree_id,
            "branch": branch,
            "repository_id": repository_id,
            "session_id": session_id,
            "repository_revision": repository_revision,
            "phase": phase,
            "focus": list(focus or []),
            "preload_profile": preload_profile,
        }, timeout=_timeout("context")), "context")
    if action == "verify_receipt":
        receipt_payload = checkpoint or {
            "task_id": task_id,
            "criterion": criterion or key or value or query,
            "passed": status.lower() in {"passed", "true", "1", "pass", "ok"} if status else True,
        }
        if checkpoint:
            receipt_payload = dict(checkpoint)
            receipt_payload.setdefault("task_id", task_id)
            receipt_payload.setdefault("criterion", criterion or key or value or query)
        if not str(receipt_payload.get("task_id", "")).strip() or not str(receipt_payload.get("criterion", "")).strip():
            return {
                "success": False,
                "terminal": True,
                "retryable": False,
                "error": "verify_receipt requires task_id and criterion",
            }
        return _compact(CLIENT.post("/api/agent-state/verification", {
            "action": "receipt", "receipt": receipt_payload, "root": root,
        }, timeout=_timeout("quick")), "verify")
    if action == "verify_completion":
        return _compact(CLIENT.post("/api/agent-state/verification", {
            "action": "completion", "task_id": task_id or query or value or key, "root": root,
            "repository_revision": repository_revision,
        }, timeout=_timeout("quick")), "verify")
    if action.startswith("negative_knowledge_"):
        sub_act = "record" if action == "negative_knowledge_record" else "find"
        return _compact(CLIENT.post("/api/agent-state/incidents", {
            "action": sub_act, "error_class": key or "AgentError", "message": value or query,
            "query": query or key or value, "root": root,
            "root_cause": reason, "verified_fix": status,
            "incident_id": record_id,
        }, timeout=_timeout("quick")), "status")
    if action == "incident_decision":
        return _compact(CLIENT.coord(
            action="incident_decision", fingerprint=fingerprint or {},
            tool_outcome=tool_outcome or {}, root=root,
        ), "status")
    if action in ("claim", "claim_batch"):
        claim_root = root
        if (not requested_root or requested_root == ".") and paths:
            first_abs = next((str(p) for p in paths if os.path.isabs(str(p)) or ":" in str(p)), None)
            if first_abs:
                try:
                    candidate = Path(first_abs).resolve()
                    for parent in [candidate.parent, *candidate.parents]:
                        if any((parent / marker).exists() for marker in (".git", "pyproject.toml", "package.json", "Cargo.toml", ".local-ai")):
                            claim_root = str(parent)
                            break
                except Exception:
                    pass
        return _compact(CLIENT.post("/api/leases/claim_batch", {
            "root": claim_root, "paths": paths or [], "ttl_seconds": ttl_seconds or 900, "purpose": value or "agent edit",
        }))
    if action == "release":
        return _compact(CLIENT.post("/api/leases/release", {"lease_id": lease_id}))
    if action in ("renew", "lease_renew"):
        return _compact(CLIENT.post("/api/leases/renew", {"lease_id": lease_id, "ttl_seconds": ttl_seconds or 900}))
    if action == "leases":
        return _compact(CLIENT.get(f"/api/leases?root={quote(root)}"))
    if action == "memo_put":
        payload = {
            "root": root, "key": key, "value": value, "ttl_seconds": ttl_seconds or 604800,
        }
        if expected_version is not None:
            payload["expected_version"] = expected_version
        return _compact(CLIENT.post("/api/memory/put", payload))
    if action == "memo_get":
        return _compact(CLIENT.post("/api/memory/get", {"root": root, "key": key}))
    if action == "memo_search":
        return _compact(CLIENT.post("/api/memory/search", {"root": root, "query": query, "limit": 12}))
    if action == "memo_delete":
        return _compact(CLIENT.post("/api/memory/delete", {"root": root, "key": key}))
    if action.startswith("blackboard_"):
        sub = action[len("blackboard_"):]
        board = board_id.strip() or task_id or (key if sub in {"get", "list", "merge", "delete"} and not value else "") or "default"
        sec = section.strip() or (key if (value and sub == "delete") else (key or target_scope or ("" if sub in {"get", "delete"} else "main")))
        content = record if record is not None else (value or query)
        author = approver or "agent"
        exp_v = None
        if isinstance(checkpoint, dict) and "expected_version" in checkpoint:
            exp_v = checkpoint["expected_version"]
        elif status and status.isdigit():
            exp_v = int(status)
        return _compact(CLIENT.post("/api/agent-state/blackboard", {
            "action": sub, "board_id": board, "section": sec or None,
            "content": content, "author": author,
            "remote_sections": record or {},
            "expected_version": exp_v,
        }, timeout=_timeout("quick")), "status")
    if action == "swarm_dispatch":
        return _compact(CLIENT.post("/api/agent-state/swarm/dispatch", {
            "goal": task or value or query,
            "target_paths": paths or [],
            "test_command": command or target_scope or "",
            "author": approver or "agent",
            "root": root or ".",
        }, timeout=_timeout("quick")), "status")
    if action == "swarm_step":
        return _compact(CLIENT.post("/api/agent-state/swarm/step", {
            "swarm_id": task_id or key or "",
            "role": target_scope or "Coder",
            "action": query or "submit_patch",
            "payload": record or ({"value": value} if value else {}),
        }, timeout=_timeout("quick")), "status")
    if action == "swarm_status":
        sid = task_id or key or ""
        return _compact(CLIENT.get(f"/api/agent-state/swarm/{quote(sid)}", timeout=_timeout("quick")), "status")
    if action == "swarm_list":
        st_param = f"?state={quote(status)}" if status else ""
        return _compact(CLIENT.get(f"/api/agent-state/swarm{st_param}", timeout=_timeout("quick")), "status")
    if action == "swarm_cancel":
        sid = task_id or key or ""
        return _compact(CLIENT.post("/api/agent-state/swarm/cancel", {"swarm_id": sid, "reason": reason or value or "cancelled by agent"}, timeout=_timeout("quick")), "status")
    if action == "worktree_lease":
        return _compact(CLIENT.coord(action="worktree_lease", root=root, branch=key or task or task_id or None), "status")
    if action == "worktree_release":
        del_branch = status.lower() not in {"false", "0", "no"} if status else True
        return _compact(CLIENT.coord(action="worktree_release", root=root, worktree_path=value or lease_id or key or "", worktree_id=worktree_id, delete_branch=del_branch, branch=key or task or task_id or None), "status")
    if action == "pubsub_publish":
        return _compact(CLIENT.coord(action="pubsub_publish", topic=key or target_scope or "default", message=value or query or record or {}, publisher=approver or "agent", root=root), "status")
    if action == "pubsub_poll":
        return _compact(CLIENT.coord(action="pubsub_poll", topic=key or target_scope or "default", after_seq=after_seq, limit=ttl_seconds or 50, root=root), "status")
    if action == "simulate_merge":
        return _compact(CLIENT.coord(action="simulate_merge", root=root, source_branch=key or task_id or value, target_branch=target_scope or "HEAD"), "status")
    if action in {"curate_dataset", "curate_training_dataset"}:
        return _compact(CLIENT.post("/api/agent-state/tasks", {
            "action": "curate_dataset",
            "output_path": key or value or query or "training_dataset.jsonl",
            "min_receipts": int(status) if (status and status.isdigit()) else 1,
            "format": target_scope or "jsonl",
        }, timeout=_timeout("quick")), "status")
    return _invalid_action("local_ai_coord", action, tuple(CoordAction.__args__), "Use coordination for bounded shared state; the main agent remains the owner of final integration.")


@mcp.tool()
@_instrumented_tool()
def local_ai_work(
    action: WorkAction,
    root: str = ".",
    task: str = "",
    work_id: str = "",
    acceptance_criteria: list[str] | None = None,
    constraints: list[str] | None = None,
    mode: str = "execute",
    permissions: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
    timeout_seconds: float = 90.0,
    answer: str = "",
    response_profile: str = "compact",
    return_fields: list[str] | None = None,
    max_output_tokens: int = 0,
    keep_failed_workspace: bool = False,
    extra_fields: list[str] | None = None,
    max_response_tokens: int = 0,
    reuse_key: str = "",
) -> dict[str, Any]:
    """Whole-task local execution with durable verified handoff. See dynamic description for policy and response projection."""
    if not getattr(FEATURES, "work_orchestrator", False):
        return {"success": False, "unsupported": True, "error": "local_ai_work is disabled in configuration"}
    action = action.strip().lower().replace("-", "_")
    if action not in WorkAction.__args__:
        return _invalid_action("local_ai_work", action, tuple(WorkAction.__args__), "Use submit for a closed task and one bounded wait/get for handoff.")
    payload: dict[str, Any] = {
        "action": action, "root": _client_root(root), "task": task, "work_id": work_id,
        "acceptance_criteria": acceptance_criteria or [], "constraints": constraints or [], "mode": mode,
        "permissions": permissions or {}, "budget": budget or {}, "timeout_seconds": timeout_seconds, "answer": answer,
        "response_profile": response_profile, "return_fields": return_fields or [], "max_output_tokens": max_output_tokens,
        "keep_failed_workspace": keep_failed_workspace,
    }
    return _compact(CLIENT.post("/api/work-orders", payload, timeout=_timeout("long") if action in {"wait"} else _timeout("quick")), "status")


@mcp.tool()
@_instrumented_tool()
def local_ai_artifact(action: ArtifactAction = "get", artifact_id: str = "", offset: int = 0, max_chars: int = 4000, section: str = "", extra_fields: list[str] | None = None, max_response_tokens: int = 0, response_profile: str = "", reuse_key: str = "", binary: bool = False) -> dict[str, Any]:
    """Fetch an artifact operation defined by the shared contract. Evidence IDs start with E."""
    if not operation_enabled(FEATURES, "local_ai_artifact"):
        return {"success": False, "unsupported": True, "error": "local_ai_artifact is disabled in configuration"}
    validation_arguments: dict[str, Any] = {}
    if action in {"get", "slice"}:
        validation_arguments.update({
            "artifact_id": artifact_id,
            "offset": offset,
            "max_chars": max_chars,
            "section": section,
            "binary": binary,
        })
    if extra_fields is not None:
        validation_arguments["extra_fields"] = extra_fields
    validation_error = validate_operation_arguments("local_ai_artifact", action, validation_arguments)
    if validation_error is not None:
        return {"success": False, "error": validation_error}
    if action == "list":
        return _compact(CLIENT.post("/api/artifact/list", {"limit": 20}), "artifact")
    if artifact_id.startswith("E"):
        return _compact(CLIENT.post("/api/evidence/get", {"evidence_id": artifact_id, "verify": True}), "artifact")
    result = CLIENT.post("/api/artifact/get", {
        "artifact_id": artifact_id,
        "offset": offset,
        "max_chars": min(MAX_TEXT, max(512, min(max_chars, 12000))),
        "section": section,
        "binary": bool(binary),
    })
    if binary and isinstance(result, dict) and result.get("success"):
        result = {key: value for key, value in result.items() if key != "data_base64"}
        result["binary_payload"] = "available through /api/artifact/get with binary=true"
    return _compact(result, "artifact")


# Unregister tools that are disabled in current configuration so MCP clients do not receive them
for _disabled in FEATURES.disabled_tools:
    if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools"):
        mcp._tool_manager._tools.pop(_disabled, None)
    if hasattr(mcp, "tools") and isinstance(mcp.tools, list):
        mcp.tools = [t for t in mcp.tools if getattr(t, "__name__", "") != _disabled]


# Ensure tool descriptions registered in FastMCP carry the complete dynamic guidance
_all_desc_map = {
    "local_ai_status": _desc_status,
    "local_ai_task": _desc_task,
    "local_ai_repo": _desc_repo,
    "local_ai_rag": _desc_rag,
    "local_ai_command": _desc_command,
    "local_ai_coord": _desc_coord,
    "local_ai_artifact": _desc_artifact,
    "local_ai_work": _desc_work,
}
if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools"):
    def _async_mcp_adapter(sync_fn: Any) -> Any:
        @functools.wraps(sync_fn)
        async def _call(*args: Any, **kwargs: Any) -> Any:
            return await asyncio.to_thread(sync_fn, *args, **kwargs)

        return _call

    # FastMCP invokes sync callables on its event loop. Keep direct Python
    # functions synchronous, but offload registered MCP callables so one
    # blocking tool cannot stall other requests on the same server.
    for _registered_tool in mcp._tool_manager._tools.values():
        if not _registered_tool.is_async:
            _registered_tool.fn = _async_mcp_adapter(_registered_tool.fn)
            _registered_tool.is_async = True

    for _tool_name, _desc_fn in _all_desc_map.items():
        if _tool_name in mcp._tool_manager._tools:
            description = _desc_fn()
            mcp._tool_manager._tools[_tool_name].description = description

if hasattr(mcp, "_tool_manager") and hasattr(mcp, "_mcp_server") and mcp_types is not None:
    from local_ai_hub.json_utils import dumps as json_dumps

    # FastMCP 1.x reads `parameters` and `fn_metadata.output_schema` when listing
    # tools. Publish the feature-aware conditional input schema and shared output
    # envelope while keeping per-action output contracts in operation metadata.
    for _tool_name in _all_desc_map:
        _registered_tool = mcp._tool_manager._tools.get(_tool_name)
        _actions = operation_actions(_tool_name, FEATURES)
        if _registered_tool is None or not _actions:
            continue
        if hasattr(_registered_tool, "parameters"):
            _registered_tool.parameters = _input_schema_with_action_aliases(
                _tool_name, operation_tool_input_schema(_tool_name, FEATURES)
            )
        _output_schema = operation_tool_output_schema(_tool_name, FEATURES)
        _fn_metadata = getattr(_registered_tool, "fn_metadata", None)
        if hasattr(_fn_metadata, "output_schema"):
            _fn_metadata.output_schema = _output_schema
            getattr(_registered_tool, "__dict__", {}).pop("output_schema", None)

    def _mcp_wire_view(value: Any, *, structured: bool) -> dict[str, Any]:
        wire: dict[str, Any] = {"content": [{"type": "text", "text": json_dumps(value)}]}
        if structured:
            wire["structuredContent"] = value
            wire["isError"] = False
        return wire

    def _mcp_bounded_error(value: dict[str, Any], requested: int) -> Any:
        original = json_tokens(_mcp_wire_view(value, structured=True))
        error = str(value.get("error") or "tool failed")
        metadata_variants = (
            {"requested_tokens": requested, "returned_tokens": 0, "unit": "estimated_tokens"},
            {"requested_tokens": requested, "returned_tokens": 0},
        )
        field_drops = ((), ("status_code",), ("status_code", "terminal", "retryable"))
        for error_chars in (512, 256, 128, 64, 48, 40, 32, 24, 16, 8, 1):
            for dropped in field_drops:
                candidate = {
                    "success": False,
                    "error": error[:error_chars],
                    **{
                        key: value[key]
                        for key in ("status", "status_code", "terminal", "retryable")
                        if key in value and key not in dropped
                    },
                }
                for key in (*_CONTEXT_PROTECTED_KEYS, "evidence_id", "evidence_ids", "artifact_id", "artifact_ids"):
                    if key != "error" and key in value and key not in dropped:
                        candidate[key] = value[key]
                for metadata in metadata_variants:
                    trial = dict(candidate)
                    trial["response_budget"] = dict(metadata)
                    for _ in range(16):
                        returned = json_tokens(_mcp_wire_view(trial, structured=True))
                        trial["response_budget"]["returned_tokens"] = returned
                        if json_tokens(_mcp_wire_view(trial, structured=True)) == returned:
                            break
                    if json_tokens(_mcp_wire_view(trial, structured=True)) <= requested:
                        content = [mcp_types.TextContent(type="text", text=json_dumps(trial))]
                        return content, trial
        return None

    def _mcp_budget_payload(name: str, arguments: dict[str, Any], value: Any) -> Any:
        value = _agent_output(value, name, arguments)
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
        rejection = _subminimum_budget_rejection(options)
        if rejection is not None:
            requested, profile, reuse_key, enabled = explicit_limit, "minimal", str(options.get("reuse_key") or ""), RESPONSE_BUDGET_ENABLED
            value = rejection
        else:
            requested, profile, reuse_key, enabled = _response_budget(
                str(arguments.get("action") or name), options
            )
            if explicit_limit > 0:
                requested = explicit_limit
        if not enabled:
            return ([mcp_types.TextContent(type="text", text=json_dumps(value))], value)

        if (
            isinstance(value, dict)
            and value.get("success") is False
            and "error" in value
            and json_tokens(_mcp_wire_view(value, structured=True)) > requested
        ):
            bounded_error = _mcp_bounded_error(value, requested)
            if bounded_error is not None:
                return bounded_error

        action = str(arguments.get("action") or "").lower()
        protected = (
            _CONTEXT_PROTECTED_KEYS if action in {"context", "context_compile"}
            else _STATUS_PROTECTED_KEYS if name == "local_ai_status"
            else ()
        )
        original_tokens = json_tokens(_mcp_wire_view(value, structured=True))
        raw_efficiency = value.get("token_efficiency") if isinstance(value, dict) else None
        token_metadata = raw_efficiency if isinstance(raw_efficiency, dict) else None

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
                        returned = json_tokens(_mcp_wire_view(compact_value, structured=structured))
                        compact_value["response_budget"]["returned_tokens"] = returned
                        finalized = json_tokens(_mcp_wire_view(compact_value, structured=structured))
                        if finalized == returned and finalized <= requested:
                            content = [mcp_types.TextContent(type="text", text=json_dumps(compact_value))]
                            return content, compact_value if structured else None

        inner_limits = list(dict.fromkeys((requested, max(64, requested - 32), max(64, requested // 2), 64)))
        for inner_limit in inner_limits:
            candidate = budget_response(
                copy.deepcopy(value),
                max_tokens=inner_limit,
                profile=profile,
                reuse_key=reuse_key,
                protected_keys=protected,
                token_metadata=token_metadata,
                evidence_store=None,
            )
            if isinstance(candidate, dict):
                previous_meta = candidate.get("response_budget")
                previous_meta = previous_meta if isinstance(previous_meta, dict) else {}
                candidate["response_budget"] = {
                    "requested_tokens": requested,
                    "original_tokens": original_tokens,
                    "returned_tokens": 0,
                    "truncated": original_tokens > requested,
                    "reused": bool(previous_meta.get("reused")),
                    "unit": "estimated_tokens",
                    **({"rejected": True} if previous_meta.get("rejected") else {}),
                }
            for _ in range(16):
                returned_tokens = json_tokens(_mcp_wire_view(candidate, structured=True))
                if isinstance(candidate, dict):
                    accounting = candidate.get("token_efficiency")
                    if isinstance(accounting, dict):
                        accounting["protocol_tokens_est"] = tool_request_tokens(name, arguments) + returned_tokens
                        baseline = accounting.get("baseline_tokens_est")
                        if isinstance(baseline, int) and not isinstance(baseline, bool):
                            signed_delta = baseline - returned_tokens
                            accounting["token_savings_delta_est"] = signed_delta
                            accounting["avoided_payload_tokens_est"] = max(0, signed_delta)
                    candidate["response_budget"]["returned_tokens"] = returned_tokens
                    candidate["response_budget"]["truncated"] = returned_tokens < original_tokens
                finalized = json_tokens(_mcp_wire_view(candidate, structured=True))
                if finalized == returned_tokens and finalized <= requested:
                    content = [mcp_types.TextContent(type="text", text=json_dumps(candidate))]
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
            rejection_value = _budget_rejection(
                requested=inner_limit,
                original=original_tokens,
                source=value,
                protected_keys=tuple(dict.fromkeys(("error", "evidence_id", "evidence_ids", *_CONTEXT_PROTECTED_KEYS, *protected))),
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
                candidate = copy.deepcopy(rejection_value)
                if metadata:
                    candidate["response_budget"] = dict(metadata)
                else:
                    candidate.pop("response_budget", None)
                for _ in range(16):
                    wire = _mcp_wire_view(candidate, structured=True)
                    returned_tokens = json_tokens(wire)
                    if isinstance(candidate.get("response_budget"), dict):
                        candidate["response_budget"]["returned_tokens"] = returned_tokens
                    finalized = json_tokens(_mcp_wire_view(candidate, structured=True))
                    if finalized == returned_tokens and finalized <= requested:
                        content = [mcp_types.TextContent(type="text", text=json_dumps(candidate))]
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
            returned_tokens = json_tokens(_mcp_wire_view(fallback, structured=True))
            fallback["response_budget"]["returned_tokens"] = returned_tokens
            finalized = json_tokens(_mcp_wire_view(fallback, structured=True))
            if finalized == returned_tokens and finalized <= requested:
                content = [mcp_types.TextContent(type="text", text=json_dumps(fallback))]
                return content, fallback
        minimal = {
            "success": False, "error": "budget",
            "response_budget": {"requested_tokens": requested, "returned_tokens": 0},
        }
        for structured in (True, False):
            for _ in range(16):
                returned_tokens = json_tokens(_mcp_wire_view(minimal, structured=structured))
                minimal["response_budget"]["returned_tokens"] = returned_tokens
                finalized = json_tokens(_mcp_wire_view(minimal, structured=structured))
                if finalized == returned_tokens and finalized <= requested:
                    content = [mcp_types.TextContent(type="text", text=json_dumps(minimal))]
                    return content, minimal if structured else None
        return [mcp_types.TextContent(type="text", text=json_dumps(minimal))], None

    async def _compact_mcp_call_tool(name: str, arguments: dict[str, Any]) -> Any:
        pending_accounting: list[dict[str, Any]] = []
        pending_token = _PENDING_MCP_ACCOUNTING.set(pending_accounting)

        def finalize(result: Any, *, account_unwrapped_error: bool = False) -> Any:
            if not isinstance(result, tuple) or len(result) != 2:
                return result
            contents, structured_value = result
            if structured_value is None:
                text_value = contents[0].text
                candidate_value = json.loads(text_value)
                emitted_response = {"content": [{"type": "text", "text": text_value}]}
            else:
                candidate_value = structured_value
                emitted_response = _mcp_wire_view(candidate_value, structured=True)
            emitted_tokens = json_tokens(emitted_response)
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
                metadata["protocol_tokens_est"] = tool_request_tokens(name, arguments) + emitted_tokens
                item_response = item["response"]
                _record_tool_accounting(
                    tool_name=item["tool_name"], arguments=item["arguments"], response=emitted_response,
                    measured=measured, metadata=metadata,
                    result_id_value=item_response["result_id"] if isinstance(item_response, dict) and "result_id" in item_response else "",
                )
            if account_unwrapped_error and not pending_accounting:
                _record_tool_accounting(
                    tool_name=name, arguments=arguments, response=emitted_response, measured={},
                    metadata={"protocol_tokens_est": tool_request_tokens(name, arguments) + emitted_tokens},
                )
            return result

        try:
            selector = "detail" if name == "local_ai_status" else "action"
            validation_arguments = dict(arguments)
            requested_action = validation_arguments.get(selector)
            action_kind = _action_kind_for_tool(name)
            canonical_action = (
                _resolve_action(action_kind, requested_action)
                if action_kind and isinstance(requested_action, str)
                else requested_action
            )
            if isinstance(canonical_action, str):
                validation_arguments[selector] = canonical_action
            validation = validate_operation_call(name, validation_arguments, features=FEATURES)
            if validation is not None:
                status_code, error = validation
                payload = {
                    "success": False, "status_code": status_code,
                    "terminal": True, "retryable": False, "error": error,
                }
                return finalize(_mcp_budget_payload(name, arguments, payload), account_unwrapped_error=True)
            try:
                raw = await mcp._tool_manager.call_tool(name, arguments, convert_result=False)
            except Exception as exc:
                text = str(exc).strip().splitlines()[0][:500]
                payload = {
                    "success": False,
                    "status_code": 400 if type(exc).__name__ == "ValidationError" else 500,
                    "terminal": True, "retryable": False,
                    "error": f"MCP input validation failed: {text}" if type(exc).__name__ == "ValidationError" else f"MCP tool failed: {text}",
                }
                return finalize(_mcp_budget_payload(name, arguments, payload), account_unwrapped_error=True)
            selector = "detail" if name == "local_ai_status" else "action"
            action = arguments.get(selector)
            if action_kind and isinstance(action, str):
                action = _resolve_action(action_kind, action)
            if name == "local_ai_status":
                alias = arguments.get("action")
                if isinstance(alias, str) and alias in {"status", "health", "check", "info"}:
                    action = "brief"
                elif isinstance(alias, str) and alias in operation_actions(name, FEATURES):
                    action = alias
            if not isinstance(action, str) or action not in operation_actions(name, FEATURES):
                available_actions = operation_actions(name, FEATURES)
                action = available_actions[0] if available_actions else ""
            output_error = validate_operation_output(name, action, raw)
            if output_error is not None:
                payload = {
                    "success": False, "status_code": 500,
                    "terminal": True, "retryable": False,
                    "error": f"MCP output contract failed: {output_error}",
                }
                return finalize(_mcp_budget_payload(name, arguments, payload), account_unwrapped_error=True)
            if isinstance(raw, (dict, list)):
                return finalize(_mcp_budget_payload(name, arguments, raw))
            if isinstance(raw, str):
                return finalize(_mcp_budget_payload(name, arguments, {"text": raw}))
            return finalize(_mcp_budget_payload(name, arguments, {
                "success": False, "status_code": 500, "terminal": True,
                "retryable": False, "error": "MCP tool returned unsupported result type",
            }), account_unwrapped_error=True)
        finally:
            _PENDING_MCP_ACCOUNTING.reset(pending_token)

    mcp.call_tool = _compact_mcp_call_tool
    mcp._mcp_server.call_tool(validate_input=False)(_compact_mcp_call_tool)


def main() -> None:
    """Run MCP stdio; HubClient starts the HTTP daemon when a tool needs it."""
    mcp.run()


if __name__ == "__main__":
    main()
