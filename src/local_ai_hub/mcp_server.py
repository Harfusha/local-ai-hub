from __future__ import annotations

import atexit
import asyncio
import copy
import contextvars
import functools
import hashlib
import inspect
import json
import math
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

from local_ai_hub.client import CURRENT_REQUEST_CANCEL_EVENT, HubClient
from local_ai_hub.repository_scope import (
    RepositoryScopeError, canonical_repository_root, reject_retired_tenancy_fields,
)
from local_ai_hub.compact import compact_result
from local_ai_hub.agent_diagnostics import detailed_diagnostics_enabled, project_agent_response
from local_ai_hub.agent_surface import diagnostic_mcp_operation, diagnostics_disabled_response
from local_ai_hub.response_budget import (
    LIFECYCLE_PROTECTED_KEYS,
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
from local_ai_hub.process_utils import canonical_root, canonical_workspace_id, is_rooted_path
from local_ai_hub.token_accounting import account_projection, attach_accounting, context_digest, finalize_tool_accounting, json_tokens, pop_accounting, tool_request_tokens
from local_ai_hub.trace_context import efficiency_metadata, reset_metadata, set_metadata
from local_ai_hub.search_pagination import MAX_PAGE_SIZE, pagination_bounds_error
from local_ai_hub.adoption_metrics import AdoptionMetricsStore
from local_ai_hub.task_memory_wire import (
    mcp_wire_tokens as _task_memory_mcp_wire_tokens,
    normalize_task_memory_response as _normalize_task_memory_response,
    task_memory_essential_response as _task_memory_essential_response,
    task_memory_original_tokens as _task_memory_original_tokens,
    task_memory_projection as _task_memory_projection,
)
from local_ai_hub.routing import semantic_handoff_hint
from local_ai_hub.operation_contracts import (
    operation_contract,
    operation_actions,
    operation_enabled,
    operation_tool_output_schema,
    operation_tool_input_schema,
    validate_operation_arguments,
    validate_operation_call,
    validate_operation_output,
)
from local_ai_hub.state_paths import configured_state_dir
from local_ai_hub.semantic_quality import assess_semantic_result, constrain_semantic_quality
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
if "LOCAL_AI_TENANT" in os.environ:
    raise SystemExit("LOCAL_AI_TENANT is retired; this installation has one local owner")
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

    def status(
        self, detail: str = "brief", scope: str = "process", *,
        min_duration_ms: int = 0, trace_action: str = "",
    ) -> Any:
        if detail == "agent_state":
            return self.get("/api/status?detail=agent_state")
        if detail == "traces":
            return self._client.status(
                detail, scope, min_duration_ms=min_duration_ms, trace_action=trace_action,
            )
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
        elif callable(getattr(type(self), name, None)):
            # Keep adapter method overrides on the adapter. Test monkeypatches
            # and instrumentation must not replace HubClient.get with this
            # bound proxy method, which would recurse through __getattr__.
            super().__setattr__(name, value)
        elif hasattr(self, "_client") and self._client is not None:
            setattr(self._client, name, value)
        else:
            super().__setattr__(name, value)


def _build_mcp_client(config_path: str | None) -> _MCPHubClientAdapter:
    client = HubClient(config_path=config_path, auto_start=True)
    return _MCPHubClientAdapter(client)


def _classify_mcp_operation(tool_name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    if tool_name == "local_ai_status":
        action = arguments.get("detail", "brief")
    else:
        action = arguments.get("action", tool_name)
    if not isinstance(action, str):
        action = ""
    lightweight_read = (
        tool_name == "local_ai_artifact"
        or (tool_name == "local_ai_status" and action == "brief")
        or (tool_name == "local_ai_repo" and action in {"map", "code_index", "search"})
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
    CLIENT = _build_mcp_client(CONFIG_PATH)
    CFG = load_config(CONFIG_PATH, probe_hardware=False)
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
    RESPONSE_DEFAULT_TOKENS = max(128, int(RESPONSE_BUDGET_CFG.get("default_tokens", 3200)))
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
    return (
        "Compact Hub and local-model readiness: online state, active model, and VRAM pressure. detail supports only brief."
        " Use once when Hub or local inference availability affects the next action; skip routine checks."
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
        " Conversation IDs identify reservations in this installation; model settings stay pinned and only one turn runs at a time. Defaults: 12 turns, prompt limit from `model_conversations.max_prompt_tokens` (fallback `token_saving.max_local_input_tokens`, default 56,000), idle/active TTLs of 900/1,800 seconds, and capacity 1,000. State is process-memory only and lost on restart."
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
            "Primary repository worker for repository navigation, symbols, and impact with aggregate-bounded responses; optional max_response_tokens, response_profile, reuse_key. Reuse fresh sufficient evidence; use bounded indexed/source lookup directly for exact facts. When non-trivial work lacks sufficient fresh evidence, adaptive context fuses deterministic/indexed evidence, Serena, bounded lexical search and RAG, then returns grounded diverse context. Send the task/context rather than handmade grep terms. It accepts guarded task/phase/focus fields, requires evidence IDs and reuse candidates first, treats deterministic/indexed evidence as authoritative, limits local models to ranking/compression of structured evidence, and requires `override_reason` plus approval when requested. Raw model/debug fields require dashboard detailed diagnostics; extra_fields cannot enable them. Omitted mode selects adaptive; explicit fast and full modes retain distinct retrieval paths. Use deterministic/indexed actions for exact facts, symbols, diff and tests; use `local_ai_task` for semantic generation, reasoning, review, independent second opinions and compression. `solve` preserves one bounded local pass for explicit semantic requests even when exact evidence is strong. Native fallback requires terminal=true and retryable=false. Use `code_index` for indexed symbol lookup. Actions: search, code_index, context, solve, review_diff, callers, dead_code."
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
        " Reuse fresh evidence and bounded indexed/source lookup for exact facts; use adaptive context when non-trivial work lacks sufficient fresh evidence."
        f" Use the adaptive context orchestrator: deterministic, code_index, Serena, bounded lexical search, and RAG are fused when available;"
        " agreement is ranked, paths are deduplicated/diversified, and optional local models only rerank/compress grounded evidence."
        f" Use deterministic, code_index/search,{' ' + FEATURES.semantic_hint() + ',' if FEATURES.has_semantic() else ''}"
        " context and solve for bounded evidence and implementation support."
        " Reuse fresh sufficient repository evidence. For exact file or symbol lookups, use bounded indexed/source lookup directly. Use `context` in adaptive mode only when non-trivial planning, editing, review or testing lacks sufficient fresh evidence; send the task/context, not handmade grep terms. Reuse existing evidence and reuse candidates first, require evidence IDs, and treat deterministic/indexed evidence as authoritative. Guarded overrides require `override_reason` and approval when requested. Raw model/debug fields stay omitted unless requested through `extra_fields`. Omitted mode selects adaptive; explicit fast and full modes retain distinct retrieval paths."
        " For implementation, diagnosis, refactoring or complex review, call `solve` after evidence and before native edits."
        f"{' When generating, use `' + FEATURES.fast_model + '` for quick tasks, `' + FEATURES.smart_model + '` for complex work, and `' + FEATURES.reasoning_model + '` for hardest reasoning.' if local_enabled else ''}"
        " `review_diff` and `security_audit` are targeted local checks."
        f"{'  After any needed indexed evidence, use `local_ai_task` for semantic generation, reasoning, review, independent second opinions and compression. `solve` preserves one bounded local pass for explicit semantic requests even when exact evidence is strong.' if local_enabled else ''}"
        f"{_semantic_handoff_contract(local_enabled, FEATURES.status)}"
        " Codex separately decides whether to use native Codex subagents;"
        " Local AI Hub does not route or manage those agents."
        " Preprocess only when a stable absolute root is unindexed or its evidence is stale; preprocessing is asynchronous, so never wait/poll/force-refresh it."
        f" Retrieval path: reuse fresh evidence; use bounded deterministic/indexed/source lookup for exact facts and adaptive context only when evidence is insufficient. Context fans out only bounded independent backends, fuses their ranked paths, and stops optional layers on timeout/degradation. Semantic generation, reasoning, review, independent second opinions and compression use `local_ai_task` after evidence;"
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
            " Project search/index and ingestion require an explicit absolute authorized root and root-bound workspace. Search ingested documents with action=search in that workspace; docset_index/docset_search use a separate owner-global docset namespace. Document ingestion requires non-empty content; diagram files stay inside that root."
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
        " Project search/index and ingestion require an explicit absolute authorized root and root-bound workspace. Search ingested documents with action=search in that workspace; docset_index/docset_search use a separate owner-global docset namespace. Document ingestion requires non-empty content; diagram files stay inside that root."
    )


def _desc_coord() -> str:
    if LEAN_SCHEMAS:
        supported = set(FEATURES.supported_coord_actions())
        actions = [name for name in (
            "claim", "release", "memory_record",
            "memory_find", "context_compile", "task_create", "task_checkpoint", "ask", "answer",
        ) if name in supported]
        purpose = (
            "Agent OS coordination for task contracts, ownership, checkpoints, and verification receipts"
            if FEATURES.agent_os else "Coordination for leases"
        )
        return (
            f"{purpose} with aggregate-bounded responses; optional max_response_tokens, response_profile, reuse_key."
            f"{_actions_note(actions)}"
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
        " Use scoped Agent OS memory_find/memory_record for reusable findings; workspace memo actions are operator-only and unavailable through this tool."
        " Native peer subagents are coordinated by Codex rather than by this Hub tool."
        f"{usage_note}"
    )


def _desc_work() -> str:
    if LEAN_SCHEMAS:
        return "Delegate closed, low-risk work with a verified handoff and aggregate-bounded response. Common controls: max_response_tokens, response_profile (minimal, compact, delta), reuse_key, extra_fields for additional safe response fields. Work projection controls: return_fields selects top-level fields; max_output_tokens bounds handoff text; work profiles are minimal, compact, standard, debug. Actions: submit, status, wait, get, cancel, continue. Use when: the task can be delegated as a self-contained repository outcome. Skip when: work is micro-edits or live discussion."
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
            " Source: action=source, path, line_start/line_end; workspace-confined, file/range/output bounded with SHA-256 provenance."
            " Use when: exact source or evidence text is required after indexed discovery."
            " Skip when: no source slice is needed or the existing compact result is sufficient."
        )
    return (
        "Fetch one exact source or log slice or bounded binary artifact metadata. Binary payloads are never inlined in MCP responses. Evidence IDs start with E."
        " Use when: exact source or evidence text is required after indexed discovery."
        " Skip when: no source slice is needed or the existing compact result is sufficient."
    )


TaskAction: TypeAlias = Literal.__getitem__(operation_actions("local_ai_task", None))


_REPO_ACTIONS = (
    "profile", "search", "map", "code_index", "semantic", "intelligence",
    "deterministic", "context", "route", "delegate", "solve", "review_diff", "impact",
    "refactor_impact", "resolve_imports", "generate_tests", "validate_patch",
    "audit_dependencies", "ast_outline", "test_matrix", "security_audit", "git_status", "repo_state",
    "synthesize_commit", "verify", "preprocess", "preprocess_status", "preprocess_refresh",
    "preprocess_pause", "preprocess_resume", "preprocess_cancel", "preprocess_unregister",
    "context_compile", "verify_receipt", "verify_completion",
    "cross_project_graph", "cross_project_symbols", "cross_project_impact",
    "call_graph_diff", "semantic_diff",
    "affected_tests", "topology", "ast_refactor",
    "generate_mocks", "split_changes", "synthesize_rules",
    "code_invariants", "generate_dataset", "profile_digest",
    "callers", "callees", "implementations", "declaration", "dead_code", "secret_scan", "schema_inspect", "explain_query", "env_compat",
    "circular_dependencies", "generate_types", "complexity", "api_spec", "dependency_slice", "migration_drift", "package_audit",
    "structural_search", "context_budget",
    "git_diff", "git_history_search", "hotspots", "generate_tests_for_diff", "cross_repo_contract",
    "reachability_dead_code", "mutation_test", "type_stubs", "skeletonize", "investigate",
    "diagnose", "briefing", "pipeline", "definition", "references", "find_references", "find_symbol",
)


def _repo_action_type(features: Any) -> Any:
    return Literal.__getitem__(operation_actions("local_ai_repo", features))


RepoAction: TypeAlias = _repo_action_type(None)
RagAction: TypeAlias = Literal.__getitem__(operation_actions("local_ai_rag"))
CoordAction: TypeAlias = Literal.__getitem__(operation_actions("local_ai_coord", None))
StatusDetail: TypeAlias = Literal.__getitem__(operation_actions("local_ai_status"))
STATUS_DETAILS = operation_actions("local_ai_status")
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
_CURRENT_MCP_CALL_ARGUMENTS: contextvars.ContextVar[tuple[str, dict[str, Any]] | None] = contextvars.ContextVar(
    "_CURRENT_MCP_CALL_ARGUMENTS", default=None
)
_PENDING_MCP_ACCOUNTING: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar("_PENDING_MCP_ACCOUNTING", default=None)
_CURRENT_ROOT_FAMILY_RESERVATION: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "_CURRENT_ROOT_FAMILY_RESERVATION", default=None
)
_STATUS_PROTECTED_KEYS = (
    "guide_cards", "guide_scope", "guide_tips", "schema_token_reduction_verified",
    "success", "status_code", "error", "warning", "version", "hub_online", "ollama_online",
    "active_model", "queued", "inflight", "cache_hits", "coalesced_waiters",
    "net_cloud_token_delta_est", "vram_pressure", "context_budget_factor",
    "summary", "window", "queue", "hotspots", "by_operation", "error_fingerprints",
    "job_id", "trace_id", "task_id", "state", "artifact_id", "cancel_requested",
    "expires_at", "wait_timeout_seconds", "outcome_unknown", "coalesced", "idempotent_replay",
    "admission_state", "terminal", "retryable", "in_progress",
    "mutation_applied", "operation_not_started", "dependency_status",
    "worktree_id", "worktree_path", "lease_id", "branch",
    "enabled", "active_tasks", "tasks_count", "incidents_count", "candidates_count", "status",
)
_SECURITY_PROTECTED_KEYS = (
    "clean", "leak_count", "real_leaks_count", "secrets_count", "test_findings_count",
    "scanned_git_history", "git_history_status", "coverage",
    "is_clean", "findings_present", "release_blocking_findings", "triage_complete",
    "scan_complete", "limit_reached", "findings_count", "scanned_files", "eligible_files",
    "eligible_files_total", "skipped_files", "scanned_bytes", "coverage_scope", "stop_reason",
)

_RELIABILITY_PROTECTED_KEYS = (
    *LIFECYCLE_PROTECTED_KEYS,
    "request_id", "context_id",
    "success", "terminal", "retryable", "unsupported", "degraded", "stale", "unchanged",
    "fallback_used", "evidence", "evidence_ids", "cancelled", "cancel_requested", "cancel_reason",
    "mutation_applied", "operation_not_started",
    "semantic_quality", "review_consistency", "advisory_only", "quality_warning", "bypass_reason",
)
_COORD_PROTECTED_KEYS = (
    "tasks", "task", "records", "matches", "items", "negative_knowledge",
    "receipts", "missing_criteria", "unverified_criteria", "total_count",
    "active_count", "offset", "limit", "has_more", "next_offset",
    "board", "columns", "summary", "checkpoint_sync",
)
_REPO_PROTECTED_KEYS = (
    "symbols", "files", "results", "evidence", "findings", "issues", "diff",
)
_VERIFY_PROTECTED_KEYS = ("missing_criteria", "unverified_criteria", "receipts", "completion")
_TOPOLOGY_PROTECTED_KEYS = (
    "coverage", "architecture_pattern_hypothesis", "architecture_pattern_verified",
    "heuristic_layers", "module_graph", "import_scope",
)
_COMPLEXITY_PROTECTED_KEYS = (
    "complete", "scope", "coverage", "limits", "files_analyzed", "eligible_files",
    "skipped_files", "skipped_directories", "parse_error_count", "read_error_count",
    "total_functions", "high_risk_count", "include_tests",
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
    "task_context", "task_context_artifact_id", "task_id", "complete", "partial", "text", "source_layers", "agent_state", "repository",
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
    requested_profile = str(options.get("response_profile") or "").strip().lower()
    profile = requested_profile or "compact"
    if profile not in {"minimal", "compact", "standard", "debug", "delta", "dense"}:
        profile = "compact"
    if not requested_profile:
        profile = CONTEXT_LEDGER.adaptive_profile(profile)
    explicit_budget = type(options.get("max_response_tokens")) is int and options["max_response_tokens"] >= 128
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
    if profile == "minimal" and not explicit_budget:
        requested = min(requested, max(256, RESPONSE_DEFAULT_TOKENS // 2))
    elif profile == "standard" and not explicit_budget:
        requested = max(requested, RESPONSE_DEFAULT_TOKENS)
    elif profile == "debug" and not explicit_budget:
        requested = max(requested, int(RESPONSE_DEFAULT_TOKENS * 2))
    return max(128, requested), profile, str(options.get("reuse_key") or "")[:160], RESPONSE_BUDGET_ENABLED


def _reuse_only(key: str, value: Any) -> bool:
    return _reuse_state(key, value)[0]


def _reuse_state(key: str, value: Any) -> tuple[bool, Any]:
    if not key:
        return False, None
    # Transport correlation changes for each request, even when its answer does
    # not. Retain the current identity in the response and stored snapshot.
    identity = {field: item for field, item in value.items() if field != "request_id"} if isinstance(value, dict) else value
    digest = hashlib.sha256(repr(_normalize_deterministic(identity)).encode("utf-8", errors="replace")).hexdigest()
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


def _code_index_page_with_prefix(
    base: dict[str, Any], raw: dict[str, Any], symbols: list[Any], count: int,
    *, identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an honest code-index page containing a whole-symbol prefix."""
    candidate = copy.deepcopy(raw if raw.get("success") is True and base.get("success") is False else base)
    for key in ("root", "query"):
        candidate.pop(key, None)
        value = identity.get(key) if isinstance(identity, dict) else None
        if isinstance(value, str):
            candidate[key] = value
    if raw.get("success") is True:
        for key in ("error", "status_code", "terminal", "retryable", "failure_kind"):
            candidate.pop(key, None)
            if key in raw:
                candidate[key] = copy.deepcopy(raw[key])
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
            candidate = _code_index_page_with_prefix(
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
            candidate = _normalize_deterministic(account_projection(raw, candidate))
            if json_tokens(candidate) > requested:
                continue
            if wire_budget:
                wire = {
                    "content": [{"type": "text", "text": json_dumps(candidate)}],
                    "structuredContent": candidate,
                    "isError": False,
                }
                if json_tokens(wire) > requested:
                    continue
            return candidate
    return None


def _relation_page_with_prefix(
    base: dict[str, Any], raw: dict[str, Any], page_key: str, items: list[Any], count: int,
) -> dict[str, Any]:
    """Keep relation page metadata aligned with the whole-item prefix that fits."""
    candidate = copy.deepcopy(raw if raw.get("success") is True and base.get("success") is False else base)
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
    for count in range(len(items), -1, -1):
        candidate = _normalize_deterministic(account_projection(
            raw, _relation_page_with_prefix(base, raw, page_key, items, count),
        ))
        if json_tokens(candidate) > requested:
            continue
        wire = {
            "content": [{"type": "text", "text": json_dumps(candidate)}],
            "structuredContent": candidate,
            "isError": False,
        }
        if json_tokens(wire) <= requested:
            return candidate
    return None


def _search_page_with_prefix(
    base: dict[str, Any], raw: dict[str, Any], results: list[Any], count: int,
) -> dict[str, Any]:
    """Keep search page metadata aligned with the whole-result prefix that fits."""
    candidate = copy.deepcopy(raw if raw.get("success") is True and base.get("success") is False else base)
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
    projected_results = []
    for item in results:
        if not isinstance(item, dict):
            projected_results.append(item)
            continue
        projected = PROJECTOR.project(item, AGENT_NAME, "search", extra_fields=extra_fields)
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
            candidate = _search_page_with_prefix(base, raw, source_results, count)
            if compact_metadata:
                for key in ("workspace_cache", "path_hint_usage", "engine", "scanned_files", "terms"):
                    candidate.pop(key, None)
            candidate = _normalize_deterministic(account_projection(raw, candidate))
            if json_tokens(candidate) > requested:
                continue
            if wire_budget:
                wire = {
                    "content": [{"type": "text", "text": json_dumps(candidate)}],
                    "structuredContent": candidate,
                    "isError": False,
                }
                if json_tokens(wire) > requested:
                    continue
            return candidate
    return None



def _compact(
    value: Any, task_kind: str = "general", extra_fields: list[str] | None = None,
    *, page_key: str | None = None, identity: dict[str, Any] | None = None,
) -> Any:
    # Capture measured savings before the projector intentionally removes internal
    # token_saving/runtime fields. Private accounting metadata is stripped by the
    # instrumented MCP boundary and never enters agent context.
    if extra_fields is None:
        extra_fields = _CURRENT_EXTRA_FIELDS.get()
    options = _CURRENT_RESPONSE_OPTIONS.get()
    if task_kind == "command":
        extra_fields = list(dict.fromkeys([
            *(extra_fields or ()), "cache_hit", "coalesced", "output_recovery",
            *(("classification",) if options.get("action") == "classify" else ()),
        ]))
    rejection = _subminimum_budget_rejection(options)
    if rejection is not None:
        return rejection
    memory_projection = (
        _task_memory_projection(value) if task_kind == "task_memory" else None
    )
    if memory_projection is not None:
        # The MCP boundary below owns the *wire* budget, including both text
        # and structuredContent. Generic status/pointer clipping loses memory.
        _requested, profile, reuse_key, enabled = _response_budget(task_kind, options)
        if enabled:
            repeated, previous = _reuse_state(reuse_key, memory_projection)
            if profile == "delta" and previous is not None and not repeated:
                current = memory_projection
                memory_projection = delta_response(previous, current, result_id=result_id(current))
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
        return _normalize_task_memory_response(account_projection(value, memory_projection))
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
        if len(raw_value["text"]) <= MAX_TEXT:
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
    value = attach_accounting(projected_value)
    projected = PROJECTOR.project(value, AGENT_NAME, task_kind, extra_fields=extra_fields)
    if exact_artifact_text is not None and isinstance(projected, dict):
        projected = dict(projected)
        projected["text"] = exact_artifact_text
    if exact_artifact_slices is not None and isinstance(projected, dict):
        projected = dict(projected)
        projected["slices"] = exact_artifact_slices
    compact_extra_fields = extra_fields
    if task_kind == "status":
        compact_extra_fields = list(dict.fromkeys([*(extra_fields or ()), "job_id"]))
    compacted = compact_result(
        projected,
        max_text_chars=MAX_TEXT,
        max_evidence=MAX_EVIDENCE,
        max_items=(
            max(1, min(raw_value["limit"], MAX_PAGE_SIZE))
            if (task_kind in {"search", "code_index"} or page_key in {"callers", "callees", "implementations"}) and isinstance(raw_value, dict)
            and isinstance(raw_value.get("limit"), int)
            and not isinstance(raw_value.get("limit"), bool)
            else 50
        ),
        extra_fields=compact_extra_fields,
    )
    compacted = _preserve_contract_state(raw_value, compacted)
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
        compacted.update({key: raw_value[key] for key in _SECURITY_PROTECTED_KEYS if key in raw_value})
    if task_kind == "complexity" and isinstance(raw_value, dict) and isinstance(compacted, dict):
        compacted.update({key: raw_value[key] for key in _COMPLEXITY_PROTECTED_KEYS if key in raw_value})
    if task_kind == "topology" and isinstance(raw_value, dict) and isinstance(compacted, dict):
        compacted.update({key: raw_value[key] for key in _TOPOLOGY_PROTECTED_KEYS if key in raw_value})
    source_slice = task_kind == "artifact" and isinstance(raw_value, dict) and raw_value.get("action") == "source"
    if source_slice and isinstance(compacted, dict) and raw_value.get("success") is True:
        from .source_slice import SOURCE_SLICE_FIELDS
        compacted.update({key: raw_value[key] for key in SOURCE_SLICE_FIELDS if key in raw_value})
    if exact_artifact_slices is not None and isinstance(compacted, dict):
        compacted["slices"] = exact_artifact_slices
        for field in ("truncated", "budget_limited"):
            if field in raw_value:
                compacted[field] = raw_value[field]
    requested, profile, reuse_key, enabled = _response_budget(task_kind, options)
    if enabled:
        repeated, previous = _reuse_state(reuse_key, compacted)
        if profile == "delta" and previous is not None:
            if repeated and isinstance(compacted, dict):
                compacted["unchanged"] = True
            elif not repeated:
                compacted = delta_response(previous, compacted, result_id=result_id(compacted))
        if task_kind == "coord" and isinstance(raw_value, dict) and isinstance(compacted, dict):
            if "checkpoint_sync" in raw_value:
                compacted["checkpoint_sync"] = raw_value["checkpoint_sync"]
        protected_keys = tuple(dict.fromkeys((
            *_RELIABILITY_PROTECTED_KEYS,
            *(_COORD_PROTECTED_KEYS if task_kind in {"task_memory", "coord", "verify"} else ()),
            *(_SECURITY_PROTECTED_KEYS if task_kind == "security" else ()),
            *(_COMPLEXITY_PROTECTED_KEYS if task_kind == "complexity" else ()),
            *(_TOPOLOGY_PROTECTED_KEYS if task_kind == "topology" else ()),
            *(('offset', 'limit', 'total_matches', 'has_more') if task_kind in {"search", "code_index"} or page_key in {"callers", "callees", "implementations"} else ()),
            *(('slices', 'truncated', 'budget_limited') if task_kind == "artifact" else ()),
            *(SOURCE_SLICE_FIELDS if source_slice and raw_value.get("success") is True else ()),
            *(_CONTEXT_PROTECTED_KEYS if task_kind in {"context", "context_compile"} else ()),
            *(_STATUS_PROTECTED_KEYS if task_kind == "status" else ()),
            *(_VERIFY_PROTECTED_KEYS if task_kind == "verify" else ()),
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
    if source_slice and raw_value.get("success") is True and isinstance(compacted, dict) and compacted.get("success") is True:
        if any(compacted.get(key) != raw_value.get(key) for key in SOURCE_SLICE_FIELDS):
            compacted = {
                "success": False, "status_code": 413, "terminal": True, "retryable": False,
                "error": "Exact source slice exceeds response budget; reduce the range or max_chars",
            }
    if (
        task_kind == "code_index"
        and isinstance(raw_value, dict)
        and raw_value.get("success") is True
        and isinstance(raw_value.get("symbols"), list)
    ):
        requested, _profile, _reuse_key, enabled = _response_budget(task_kind, options)
        if enabled:
            fitted = _code_index_prefix_fitting(
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
                    "error": "The first complete code-index symbol exceeds the configured response budget.",
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
        requested, _profile, _reuse_key, enabled = _response_budget(task_kind, options)
        if enabled:
            raw_items = raw_value[page_key]
            fitted = _relation_prefix_fitting(compacted if isinstance(compacted, dict) else {}, raw_value, page_key, raw_items, requested)
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
        requested, _profile, _reuse_key, enabled = _response_budget(task_kind, options)
        if enabled:
            raw_items = raw_value[page_key]
            fitted = _search_prefix_fitting(
                compacted if isinstance(compacted, dict) else {},
                raw_value,
                raw_items,
                requested,
                wire_budget=True,
                extra_fields=extra_fields,
            )
            if fitted is None or (raw_items and not fitted.get(page_key)):
                compacted = {
                    "success": False,
                    "status_code": 413,
                    "terminal": True,
                    "retryable": False,
                    "error": f"The requested {task_kind} page exceeds the configured MCP response budget; reduce limit.",
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
    return _normalize_deterministic(account_projection(raw_value, compacted))


_TELEMETRY_DETAIL_LABELS = {
    "status": frozenset({"complete", "incomplete"}),
    "omitted_sections": frozenset({
        "decision_grade_lists", "pending_events", "writer_failures",
        "writer_activity_unobserved", "writer_accounting_unbalanced", "cached_summary_data",
    }),
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

    if field == "writer_error_attempts_unit" and value == "attempts":
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
        *_RELIABILITY_PROTECTED_KEYS,
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
                value = _bound_context_json(value[:MAX_EVIDENCE])
            elif key == "evidence_ids" and isinstance(value, (list, tuple)):
                value = [str(item)[:160] for item in value[:MAX_EVIDENCE] if str(item)]
            elif key == "cancel":
                value = _bound_context_json(value)
            projected[key] = value
        if not projected.get("evidence_ids"):
            context_pack = raw.get("adaptive_context_pack") or raw.get("context_pack")
            evidence = context_pack.get("evidence") if isinstance(context_pack, dict) else None
            if isinstance(evidence, list):
                ids = [
                    str(item.get("evidence_id"))[:160]
                    for item in evidence[:MAX_EVIDENCE]
                    if isinstance(item, dict) and item.get("evidence_id")
                ]
                if ids:
                    projected["evidence_ids"] = ids
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
            elif type(item) in {int, float} and math.isfinite(item):
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
        "window": _sanitize_telemetry_payload(report.get("window") if isinstance(report.get("window"), dict) else {}, field="window"),
        "summary": _sanitize_telemetry_payload(projected_summary, field="summary"),
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
    if type(raw.get("success")) is not bool or (
        raw.get("success") is True and type(raw.get("complete")) is not bool
    ):
        return "", {
            "success": False, "terminal": True, "retryable": False,
            "error": "task context response requires explicit boolean success and completeness",
        }
    if raw["success"] is False or raw["complete"] is False:
        return "", {
            "success": False,
            "terminal": bool(raw.get("terminal", False)),
            "retryable": bool(raw.get("retryable", True)),
            "error": str(raw.get("error") or "task context is incomplete"),
            "task_context": task_context if isinstance(task_context, dict) else {},
        }
    if not isinstance(task_context, dict) or (
        task_context.get("success") is not True or task_context.get("complete") is not True
    ):
        return "", {
            "success": False, "terminal": True, "retryable": False,
            "error": "task context response requires a complete canonical task_context object",
        }
    task_text = task_context.get("text")
    if not isinstance(task_text, str):
        return "", {
            "success": False, "terminal": True, "retryable": False,
            "error": "task_context.text must be a string",
        }
    task_text = task_text.strip()
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
    if not isinstance(result, dict) or type(result.get("success")) is not bool:
        return {
            "success": False, "terminal": True, "retryable": False,
            "error_code": "invalid_semantic_result",
            "error": "Local semantic backend must return an object with explicit boolean success.",
        }
    if result["success"] is False:
        return result
    # A semantic success is only meaningful when it carries a usable payload.
    # Empty model output used to leak through as success=true and poisoned
    # caches/async handoffs with no evidence for the caller.
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
        if "semantic_quality" not in result and "review_consistency" not in result:
            return result
        quality = constrain_semantic_quality(
            {"usable": False, "reason": "source_evidence_unavailable"}, result,
        )
    else:
        quality = constrain_semantic_quality(assess_semantic_result(task, evidence_paths, result), result)
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
        self._queue: queue.Queue[tuple[dict[str, Any], Any]] = queue.Queue(maxsize=2048)
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
            # A queued report must keep the client that owned it at enqueue time;
            # CLIENT can be replaced during controlled reconfiguration or tests.
            self._queue.put_nowait((dict(event), CLIENT))
        except queue.Full:
            return
        self._ensure_worker()

    def _send(self, events: list[dict[str, Any]], *, client: Any = None) -> None:
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
            (CLIENT if client is None else client).post(
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

    def _send_batch(self, batch: list[tuple[dict[str, Any], Any]]) -> None:
        client_batches: dict[int, tuple[Any, list[dict[str, Any]]]] = {}
        for event, client in batch:
            client_batches.setdefault(id(client), (client, []))[1].append(event)
        for client, events in client_batches.values():
            self._send(events, client=client)

    def _run(self) -> None:
        batch: list[tuple[dict[str, Any], Any]] = []
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
                self._send_batch(batch)
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
            self._send_batch(batch)
        with self._lock:
            if self._thread is threading.current_thread():
                self._thread = None

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.35)
        remaining: list[tuple[dict[str, Any], Any]] = []
        while len(remaining) < 64:
            try:
                remaining.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if remaining:
            self._send_batch(remaining)
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
        event.update({"agent": AGENT_NAME, "created_at": time.time()})
        CONTEXT_LEDGER.record(
            tool=tool_name,
            operation=str(arguments.get("action") or "default"),
            request_tokens=event["agent_tool_request_tokens_est"],
            response_tokens=event["agent_tool_response_tokens_est"],
            saved_tokens=event["projected_response_saved_tokens_est"],
            cache_outcome=event["cache_outcome"],
            result_id=result_id_value,
            session_id=arguments.get("session_id", ""),
        )
        _ACCOUNTING_REPORTER.record(event)
    except Exception:
        pass


def _agent_output(value: Any, tool: str, arguments: dict[str, Any]) -> Any:
    """The dashboard toggle is authoritative; request profiles cannot enable detail."""
    result = project_agent_response(value, enabled=detailed_diagnostics_enabled(CFG))
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
            budget_rejection = _explicit_budget_rejection(arguments)
            if budget_rejection is not None:
                return budget_rejection
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
            operator_status = fn.__name__ == "local_ai_status" and not requires_heavy_work
            if mode_rejection is not None and not operator_status:
                return mode_rejection
            if not detailed_diagnostics_enabled(CFG) and diagnostic_mcp_operation(fn.__name__, arguments):
                return diagnostics_disabled_response()
            extra = arguments.get("extra_fields") or kwargs.get("extra_fields")
            token = _CURRENT_EXTRA_FIELDS.set(extra) if extra is not None else None
            response_profile = arguments.get("response_profile", "")
            if (not response_profile and fn.__name__ == "local_ai_repo"
                    and arguments.get("action") in {"context", "search", "code_index"}):
                response_profile = "compact"
            response_token = _CURRENT_RESPONSE_OPTIONS.set({
                "action": arguments.get("action", ""),
                "max_response_tokens": arguments.get("max_response_tokens", 0),
                "response_profile": response_profile,
                "reuse_key": arguments.get("reuse_key", ""),
                "tool": fn.__name__,
                "arguments": arguments,
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
            selector = "detail" if fn.__name__ == "local_ai_status" else "action"
            parameter = signature.parameters.get(selector)
            contract_action = arguments.get(selector, parameter.default if parameter is not None else "")
            output_error = validate_operation_output(fn.__name__, str(contract_action), clean)
            if output_error is not None:
                clean = {
                    "success": False, "status_code": 500, "terminal": True, "retryable": False,
                    "error": f"MCP output contract failed: {output_error}",
                    "failure_kind": "output_contract_violation",
                    **({"request_id": clean["request_id"]} if isinstance(clean, dict) and isinstance(clean.get("request_id"), str) else {}),
                }
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
_ADOPTION_TOOLS = {"local_ai_status", "local_ai_task", "local_ai_repo", "local_ai_rag", "local_ai_coord", "local_ai_work", "local_ai_artifact"}
_ADOPTION_ACTIONS = {
    "local_ai_status": set(operation_actions("local_ai_status")),
    "local_ai_task": set(operation_actions("local_ai_task")),
    "local_ai_repo": set(operation_actions("local_ai_repo")),
    "local_ai_rag": set(operation_actions("local_ai_rag")),
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
        intent = {"local_ai_repo": "repository", "local_ai_coord": "coordination"}.get(tool, "hub")
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
def local_ai_status(
    detail: Literal["brief"] = "brief",
    extra_fields: list[str] | None = None,
    max_response_tokens: int = 0,
    response_profile: str = "",
    reuse_key: str = "",
) -> dict[str, Any]:
    """Compact Hub and local-model readiness: availability, active model, and VRAM pressure."""
    if detail != "brief":
        return contract_error("detail supports only brief")
    if not FEATURES.status:
        return {**contract_error("local_ai_status is disabled in configuration", status_code=403), "unsupported": True}
    status = CLIENT.get("/api/live/status?light=1")
    if not isinstance(status, dict):
        return contract_error("live status endpoint returned an invalid payload", status_code=502)
    scheduler = status.get("scheduler")
    scheduler = scheduler if isinstance(scheduler, dict) else {}
    result: dict[str, Any] = {
        "success": bool(status.get("hub_online", False)),
        "version": status.get("version"),
        "ollama_online": status.get("ollama_online"),
        "active_model": scheduler.get("active_model"),
        "degraded": status.get("degraded") is True,
    }
    vram = status.get("vram_balancer")
    if isinstance(vram, dict):
        result["vram_pressure"] = vram.get("pressure_level", "nominal")
        result["context_budget_factor"] = vram.get("context_budget_factor", 1.0)
    dependencies = status.get("dependency_status")
    if result["degraded"] and isinstance(dependencies, dict):
        failed = {
            name: diagnostic for name, diagnostic in dependencies.items()
            if isinstance(name, str) and isinstance(diagnostic, dict) and diagnostic.get("degraded") is True
        }
        if failed:
            result["dependency_status"] = _bound_context_json(failed)
    return _preserve_contract_state(status, result)


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
    baseline_screenshot_artifact_id: str = "",
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
    url: str = "",
    page: dict[str, Any] | None = None,
    automation: dict[str, Any] | None = None,
    complexity: str = "auto",
    max_tokens: int = 0,
    tasks: list[dict[str, Any]] | None = None,
    items: list[Any] | None = None,
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
    path: str = "",
    image_path: str = "",
    audio_path: str = "",
    file: str = "",
    code: str = "",
    diff: str = "",
    problem: str = "",
    query: str = "",
    question: str = "",
    text: str = "",
) -> dict[str, Any]:
    """Run a bounded semantic task or an explicitly authorized UI automation session.

    automation uses root, task_id and a closed automation object with op
    open/act/status/close. Browser/desktop targets are default-deny; use the
    returned session_id and session_key, and a unique request_id for each act.
    Backends are installed explicitly. Unknown outcomes must never be replayed.

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
    if items and not tasks:
        tasks = items
    if action not in operation_actions("local_ai_task", FEATURES):
        return _invalid_action(
            "local_ai_task",
            action,
            operation_actions("local_ai_task", FEATURES),
            "Use Local AI Hub only for bounded local-model work; use Codex-owned orchestration for peer subagents.",
        )
    retired_inputs = {
        "hardware_benchmark": {"task"},
        "speculative_draft": {"prompt", "workspace"},
        "vision": {"task", "context"},
        "eval_drift": {"prompt"},
        "complete_code": {"context", "task"},
        "scaffold": {"task", "candidate"},
        "transcribe": {"context", "task", "prompt"},
        "eval_suite": {"prompt"},
        "prompt_eval": {"task", "context"},
        "candidate_create": {"task", "candidate", "prompt", "evaluation_task_id"},
        "candidate_promote": {"task", "prompt", "evaluation_task_id", "candidate_data"},
    }
    input_values = {
        "task": task, "prompt": prompt, "context": context,
        "candidate": candidate, "workspace": workspace, "model": model,
        "root": root, "language": language, "candidate_data": candidate_data,
        "evaluation_task_id": evaluation_task_id,
    }
    for field in retired_inputs.get(action, ()):
        if input_values[field] not in (None, ""):
            return {
                "success": False, "status_code": 400, "terminal": True, "retryable": False,
                "error": f"{action} accepts its canonical input; {field} is not an alias",
            }
    canonical_string_fields = {
        "hardware_benchmark": ("prompt", "model"),
        "speculative_draft": ("task", "candidate", "context", "root"),
        "vision": ("prompt", "candidate"),
        "eval_drift": ("task",),
        "complete_code": ("prompt", "candidate"),
        "scaffold": ("prompt", "context", "language", "model"),
        "transcribe": ("candidate", "model", "language"),
        "eval_suite": ("task", "model"),
        "prompt_eval": ("prompt",),
    }
    for field in canonical_string_fields.get(action, ()):
        if not isinstance(input_values[field], str):
            return {
                "success": False, "status_code": 400, "terminal": True, "retryable": False,
                "error": f"{action} {field} must be a string",
            }
    if action == "prompt_eval" and candidate_data is not None and not isinstance(candidate_data, dict):
        return {
            "success": False, "status_code": 400, "terminal": True, "retryable": False,
            "error": "prompt_eval candidate_data must be an object",
        }
    if action == "candidate_create" and not isinstance(candidate_data, dict):
        return {
            "success": False, "status_code": 400, "terminal": True, "retryable": False,
            "error": "candidate_create requires candidate_data object",
        }
    if action == "candidate_promote":
        for field, value in (("candidate", candidate), ("approver", approver)):
            if not isinstance(value, str) or not value.strip():
                return {
                    "success": False, "status_code": 400, "terminal": True, "retryable": False,
                    "error": f"candidate_promote requires non-empty {field}",
                }
    try:
        mode_snapshot = load_operational_mode(configured_state_dir(CFG, create=False))
    except Exception:
        # Missing or unreadable mode state must fail closed for agent work.
        mode_snapshot = None

    deterministic_actions = {"status", "wait", "result", "cancel", "evaluation_report"}
    mode_rejection = operational_mode_gate_error(
        mode_snapshot,
        action,
        requires_heavy_work=action not in deterministic_actions,
    )
    if mode_rejection is not None:
        return mode_rejection
    if action == "automation":
        if delivery != "sync" or conversation:
            return {"success": False, "error": "automation sessions require synchronous delivery without conversations", "terminal": True, "retryable": False}
        if not isinstance(automation, dict) or not root or not task_id:
            return {"success": False, "error": "automation requires root, task_id and automation object", "terminal": True, "retryable": False}
        return _compact(
            CLIENT.post("/api/task/automation", {"root": root, "task_id": task_id, "automation": automation}, timeout=_timeout("long")),
            "general", extra_fields=["automation"],
        )
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
            extra_fields=[*(extra_fields or []), "progress_percent", "current_stage", "progress_available"],
        )
    # The static contract requires summary, evidence, analysis, limitations
    # and next step. Requests below this floor routinely truncate after a
    # generic preamble, especially on 7b/9b models. Clamp instead of rejecting
    # the task so callers keep the operation and receive a complete answer.
    if action in {"delegate", "explore", "reason", "review", "second_opinion", "compress"}:
        if max_tokens:
            max_tokens = max(160, int(max_tokens))
        if not task and prompt:
            task = prompt
        if not task and query:
            task = query
        if not task and problem:
            task = problem
    if action in {"candidate_create", "candidate_promote"}:
        if action == "candidate_create":
            return _compact(CLIENT.post("/api/agent-state/learning", {
                "action": "create_candidate", "candidate": candidate_data,
            }, timeout=_timeout("quick")), "status")
        return _compact(CLIENT.post("/api/agent-state/learning", {
            "action": "promote", "candidate_id": candidate, "approver": approver,
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
        problem_input = problem or task or prompt or query or context or ""
        payload = {
            "problem": problem_input, "context": context, "max_tokens": max_tokens or 4096,
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
        code_input = code or diff or context or candidate or prompt
        instructions_input = task if code_input != task else (prompt if code_input != prompt else "Report actionable defects only.")
        payload = {
            "code": code_input, "instructions": instructions_input,
            "complexity": complexity, "max_tokens": max_tokens or 4096,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms, "model": model,
            "operation": "review", "changed_paths": changed_paths or [], "repository_revision": repository_revision,
            "evidence_ids": context_evidence_ids,
        }
        if format or json_schema:
            payload["format"] = format or json_schema
        return _compact(_attach_task_context_receipt(_quality_check_semantic_result(CLIENT.post("/api/review", payload), task=task, context=code_input, changed_paths=changed_paths), task_context_meta), "review")
    if action == "second_opinion":
        question_input = question or task or prompt or query or ""
        candidate_input = candidate or prompt or context or code or ""
        return _compact(_attach_task_context_receipt(_quality_check_semantic_result(CLIENT.post("/api/second-opinion", {
            "question": question_input, "candidate": candidate_input, "context": context if candidate_input != context else "", "max_tokens": max_tokens or 4096,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms, "model": model,
            "changed_paths": changed_paths or [], "repository_revision": repository_revision,
            "evidence_ids": context_evidence_ids,
        }), task=task, context=context, changed_paths=changed_paths), task_context_meta), "second_opinion")
    if action == "compress":
        text_input = text or context or prompt or candidate or task
        instructions_input = task if text_input != task else (prompt if text_input != prompt else "Compress while preserving facts, identifiers, numbers, errors, decisions and uncertainty.")
        return _compact(_attach_task_context_receipt(_quality_check_semantic_result(CLIENT.post("/api/compress", {
            "text": text_input, "instruction": instructions_input,
            "target_tokens": max_tokens or 650,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms,
        }, timeout=_timeout("model")), task=task, context=text_input, changed_paths=changed_paths), task_context_meta), "compress")
    if action == "route":
        return _compact(CLIENT.post("/api/route", {"text": context, "query": task, "delivery": delivery, "latency_budget_ms": latency_budget_ms}, timeout=_timeout("model")), "route")
    if action == "batch":
        return _compact(CLIENT.post("/api/delegate/batch", {"tasks": tasks or [], "delivery": delivery, "latency_budget_ms": latency_budget_ms}, timeout=_timeout("long")), "delegate")
    if action == "benchmark":
        return _compact(CLIENT.post("/api/benchmark", {}, timeout=_timeout("long")), "status")
    if action == "hardware_benchmark":
        return _compact(CLIENT.post("/api/benchmark/run", {"model": model or "", "prompt": prompt, "num_tokens": max_tokens or 40}, timeout=_timeout("long")), "status")
    if action == "evaluation_record":
        return _compact(CLIENT.post("/api/evaluation", {
            "action": "record", "task_id": evaluation_task_id, "cohort": evaluation_cohort,
            "quality_pass": quality_pass, "test_pass": test_pass, "duration_ms": evaluation_duration_ms,
        }), "status")
    if action == "evaluation_report":
        return _compact(CLIENT.post("/api/evaluation", {"action": "report", "days": evaluation_days}), "status")
    if action == "speculative_draft":
        return _compact(CLIENT.post("/api/task/speculative_draft", {
            "task": task, "file": candidate, "context": context, "root": root,
        }, timeout=_timeout("model")), "delegate")
    if action == "vision":
        effective_image = image_artifact_id or image_path or path or candidate or ""
        payload = {
            "prompt": prompt,
            "image": candidate,
            "model": model,
            "image_artifact_id": effective_image,
            "screenshot_artifact_id": screenshot_artifact_id,
            "baseline_screenshot_artifact_id": baseline_screenshot_artifact_id,
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
    if action == "browser":
        capture = CLIENT.post("/api/task/browser", {"url": url, "viewport": viewport}, timeout=_timeout("quick"))
        return _compact(
            capture,
            "general",
            extra_fields=["url", "title", "dom_snapshot", "dom_truncated", "dom_preview_truncated",
                          "dom_artifact_id", "screenshot_artifact_id", "screenshot_mime_type", "screenshot_size_bytes",
                          "network_requests_denied"],
        )
    if action == "transcribe":
        audio = candidate or audio_path or file or path or ""
        transcribe_payload = {
            "audio_path": audio,
            "model": model,
        }
        language_hint = str(language or "").strip()
        if language_hint and language_hint.casefold() != "auto":
            transcribe_payload["language"] = language_hint
        return _compact(CLIENT.post("/api/task/transcribe", transcribe_payload, timeout=_timeout("long")), "delegate")
    if action == "eval_suite":
        eval_payload: dict[str, Any] = {"suite_name": task or "default"}
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
            "template": prompt, "variables": candidate_data if candidate_data is not None else {},
        }, timeout=_timeout("model")), "delegate")
    if action == "eval_drift":
        return _compact(CLIENT.post("/api/task/eval_drift", {
            "suite_name": task or "default",
        }, timeout=_timeout("long")), "status")
    if action == "complete_code":
        return _compact(CLIENT.post("/api/complete", {
            "prefix": prompt, "suffix": candidate, "max_tokens": max_tokens or 80,
        }, timeout=_timeout("quick")), "status")
    if action == "scaffold":
        return _compact(CLIENT.post("/api/task/scaffold", {
            "spec": prompt, "context": context, "language": language if language and language.casefold() != "auto" else "python",
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
        or changed_paths is not None or focus is not None
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
    from .context_delivery import prepare_context_delivery
    requested_context_budget, _, _, _ = _response_budget("context", options)
    value = prepare_context_delivery(value, requested_context_budget)
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
        "context_id", "task_context_artifact_id", "task_id", "next_action", "warnings", "repo_revision", "changed_paths", "stale",
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
                "complete", "partial", "task_context", "task_context_artifact_id", "task_id", "next_action", "etag", "omitted_sections",
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
        pointer = safe_value.get("task_context_artifact_id")
        if isinstance(pointer, str) and final.get("task_context_artifact_id") != pointer:
            return {
                "success": False, "error": "max_response_tokens too small",
                "next_action": "request_larger_response_budget",
                "response_budget": {"requested_tokens": requested, "returned_tokens": 0, "rejected": True},
            }
        return final
    return _normalize_deterministic(final)


def _repo_pipeline_step_contract() -> dict[str, Any]:
    tool_manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(tool_manager, "_tools", {}) if tool_manager is not None else {}
    repo_tool = tools.get("local_ai_repo") if isinstance(tools, dict) else None
    parameters = getattr(repo_tool, "parameters", {}) if repo_tool is not None else {}
    properties = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
    return repo_pipeline_step_schema(properties, FEATURES.supported_repo_actions())


def _repo_validation_arguments(action: str, candidates: dict[str, Any]) -> dict[str, Any]:
    """Keep action-required canonical inputs in every scoped validation call."""
    contract = operation_contract("local_ai_repo")
    action_contract = contract.get("actions", {}).get(action) if contract else None
    if not isinstance(action_contract, dict):
        return candidates
    allowed = action_contract.get("allowed")
    scoped_names = {"max_commits", "author", "since", "until", "days", "limit"}
    required_names = tuple(action_contract.get("required", ()))
    if allowed is None:
        relevant_names = set(required_names) | scoped_names
        return {
            name: value for name, value in candidates.items()
            if name in relevant_names and value is not None
        }
    allowed_names = set(allowed)
    selected = {
        name: candidates[name]
        for name in required_names
        if name in candidates and name in allowed_names
    }
    selected.update({
        name: value for name, value in candidates.items()
        if (name in allowed_names or name in scoped_names) and value is not None
    })
    return selected


def _local_ai_repo_impl(
    action: RepoAction,
    root: str = ".",
    query: str | None = None,
    diff: str | None = None,
    task: str | None = None,
    workspace: str | None = None,
    path: str | None = None,
    base: str = "HEAD",
    staged: bool = False,
    dry_run: bool = False,
    max_tokens: int | None = None,
    evidence: list[dict[str, Any]] | None = None,
    mode: str = "adaptive",
    relation: str | None = None,
    language: str = "auto",
    profile: str = "",
    task_id: str | None = None,
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
    *,
    limit: int | None = None,
    offset: int = 0,
    old_symbol: str | None = None,
    new_symbol: str | None = None,
    old_code: str | None = None,
    new_code: str | None = None,
    rev1: str | None = None,
    rev2: str | None = None,
    max_commits: int | None = None,
    author: str | None = None,
    since: str | None = None,
    until: str | None = None,
    days: int | None = None,
    depth: int = 1,
    pattern: str | None = None,
    target: str | None = None,
    replacement: str | None = None,
    head: str | None = None,
    start_line: int = 1,
    end_line: int = 0,
    line_start: int = 1,
    line_end: int = 0,
    symbol: str | None = None,
    file: str | None = None,
) -> dict[str, Any]:
    """Primary bounded repository worker for the main agent.

    Reuse fresh repository evidence; use bounded indexed/source lookup for
    exact facts and adaptive context when non-trivial work lacks sufficient
    fresh evidence. Use deterministic, code-index/search, semantic, context and
    solve for repository evidence and implementation support. After needed
    evidence, route semantic generation, reasoning, review, independent second
    opinions and compression to local_ai_task; use local_ai_artifact for exact
    slices; use the host's native command tool for repeatable validation. Use review_diff and
    security_audit for targeted local checks. Never use this
    evidence path as a substitute for semantic local-model work. Codex manages
    native Codex subagents separately. Reuse fresh evidence. Preprocess only
    when the stable absolute root is unindexed or its evidence is stale; never
    poll or force-refresh preprocessing. Respect
    in_progress, retryable and degraded states. Use when a non-trivial
    repository task needs indexed evidence or bounded Hub support; skip when
    the task is not repository-scoped and no independent Hub scope exists."""
    secret_scan_query_supplied = query is not None
    secret_scan_task_supplied = task is not None
    secret_scan_path_supplied = path is not None
    if not FEATURES.repo:
        return {**contract_error("local_ai_repo is disabled in configuration", status_code=403), "unsupported": True}
    if action == "diff":
        action = "git_diff"
    elif action == "status":
        action = "git_status"
    elif action in {"file_info", "stat"}:
        action = "file_info"
    elif action in {"read_file", "source"}:
        action = "source"
    elif action in {"definition", "declaration"}:
        action = "declaration"
    elif action in {"references", "find_references"}:
        action = "callers"
    elif action in {"find_symbol", "symbol"}:
        action = "code_index"
    if symbol and not query:
        query = symbol
    if pattern and not query:
        query = pattern
    if file and not path:
        path = file
    if not path and changed_paths and len(changed_paths) > 0 and action == "generate_tests_for_diff":
        path = changed_paths[0]
    if not edits and path and ((target and replacement) or (old_code and new_code)):
        edits = [{"path": path, "target": target or old_code, "replacement": replacement or new_code}]
    if not isinstance(phase, str) or phase not in REPO_PHASES:
        return contract_error(f"phase must be one of: {', '.join(REPO_PHASES[1:])}")
    scoped_error = validate_operation_arguments(
        "local_ai_repo", action,
        _repo_validation_arguments(action, locals()),
    )
    if scoped_error is not None:
        return contract_error(scoped_error, status_code=400)
    retired_input_fields = {
        "hotspots": ("diff", "max_tokens"),
        **{name: ("task", "diff", "workspace") for name in (
            "investigate", "search", "semantic", "intelligence", "route", "refactor_impact",
            "generate_tests", "generate_mocks", "explain_query", "dependency_slice", "structural_search",
        )},
        "diagnose": ("diff", "task", "workspace", "path"),
        **{name: ("query", "task", "workspace", "diff") for name in (
            "migration_drift", "package_audit", "git_diff", "type_stubs", "split_changes",
        )},
        "mutation_test": ("query", "task", "workspace"),
        "generate_tests_for_diff": ("query", "task"),
        "dependency_slice": ("relation",),
        "cross_repo_contract": ("query", "workspace", "task", "diff"),
        "circular_dependencies": ("query", "task", "workspace", "diff", "path"),
        "skeletonize": ("diff", "task"),
        "context": ("task", "diff", "path"),
        "solve": ("query", "diff", "path", "task_id"),
        "delegate": ("query", "diff", "path", "task_id"),
        "code_index": ("task", "diff", "workspace", "path"),
        "deterministic": ("task", "diff", "workspace", "path"),
        "resolve_imports": ("task", "diff", "workspace", "path"),
        "validate_patch": ("task", "diff", "workspace", "path"),
        "synthesize_commit": ("task", "diff", "workspace", "path"),
        "cross_project_symbols": ("task", "diff", "workspace", "path"),
        "cross_project_impact": ("task", "diff", "workspace", "path"),
        "generate_dataset": ("task", "diff", "workspace", "path"),
        "api_spec": ("task", "diff", "workspace", "path"),
        "git_history_search": ("task", "diff", "workspace", "max_tokens"),
        "generate_types": ("diff",),
    }
    query_supplied = query is not None
    task_supplied = task is not None
    path_supplied = path is not None
    input_values = {
        "query": query, "diff": diff, "task": task, "workspace": workspace,
        "path": path, "task_id": task_id, "max_tokens": max_tokens, "relation": relation,
    }
    for field in retired_input_fields.get(action, ()):
        if input_values[field] is not None:
            if action == "generate_types" and field == "diff":
                return contract_error("generate_types is read-only; diff is not allowed and not an alias")
            return contract_error(f"{action} accepts its canonical input field; {field} is not an alias")
    query = "" if query is None else query
    diff = "" if diff is None else diff
    task = "" if task is None else task
    workspace = "" if workspace is None else workspace
    path = "" if path is None else path
    task_id = "" if task_id is None else task_id
    max_tokens = 0 if max_tokens is None else max_tokens
    max_response_tokens = 0 if max_response_tokens is None else max_response_tokens
    relation = "" if relation is None else relation
    max_commits = 50 if max_commits is None else max_commits
    author = "" if author is None else author
    since = "" if since is None else since
    until = "" if until is None else until
    days = 30 if days is None else days
    explicit_limit = limit is not None
    limit = (20 if action == "hotspots" else 24) if limit is None else limit
    for numeric_name, numeric_value in (
        ("max_tokens", max_tokens),
        ("max_response_tokens", max_response_tokens),
        ("token_budget", token_budget),
    ):
        if isinstance(numeric_value, bool) or not isinstance(numeric_value, int):
            return contract_error(f"{numeric_name} must be an integer")
        if numeric_value < 0 or numeric_value > 100000:
            return contract_error(f"{numeric_name} must be between 0 and 100000")
    context_query = ""
    if action == "context":
        if not isinstance(query, str):
            return contract_error("context query must be a string")
        context_query = query.strip()
        if not context_query:
            return contract_error("context query cannot be empty")
    if action not in FEATURES.supported_repo_actions():
        return _invalid_action(
            "local_ai_repo",
            action,
            tuple(FEATURES.supported_repo_actions()),
            "Keep work bounded in Local AI Hub; use Codex-owned orchestration for peer subagents.",
        )
    required_input_fields = {
        **{name: ("query",) for name in (
            "diagnose", "semantic", "intelligence", "resolve_imports",
            "validate_patch", "generate_mocks", "cross_project_impact",
            "generate_dataset", "explain_query", "dependency_slice", "structural_search",
        )},
        "context": ("query",), "solve": ("task",), "delegate": ("task",),
        "cross_repo_contract": ("path",), "type_stubs": ("path",),
        "refactor_impact": ("path",), "generate_mocks": ("query", "path"),
    }
    for required_field in required_input_fields.get(action, ()):
        value = input_values[required_field]
        if not isinstance(value, str) or not value.strip():
            return contract_error(f"{action} requires non-empty {required_field}")
    if action == "synthesize_commit" and task_id != "" and (
        not isinstance(task_id, str) or not task_id.strip()
    ):
        return contract_error("synthesize_commit task_id must be a non-empty string when supplied")
    if action == "skeletonize" and not (isinstance(query, str) and query.strip()) and not (isinstance(path, str) and path.strip()):
        return contract_error("skeletonize requires query code or a path")
    if action == "circular_dependencies" and not isinstance(language, str):
        return contract_error("language must be a string")
    if action == "mutation_test" and not path and not diff:
        return contract_error("mutation_test requires path or diff")
    if action in {
        "ast_outline", "affected_tests", "code_invariants", "profile_digest", "schema_inspect",
        "generate_types", "complexity", "declaration", "ast_refactor",
    }:
        operation_inputs: dict[str, Any] = {"root": root}
        path_actions = {
            "ast_outline", "affected_tests", "code_invariants", "profile_digest", "schema_inspect",
            "generate_types", "complexity", "declaration", "ast_refactor",
        }
        if action in path_actions:
            operation_inputs["path"] = path
        if action == "declaration":
            operation_inputs["query"] = query
        elif query:
            operation_inputs["query"] = query
        if task:
            operation_inputs["task"] = task
        if action == "ast_refactor":
            operation_inputs.update(old_symbol=old_symbol, new_symbol=new_symbol, staged=staged)
        if action in {"profile_digest", "complexity"}:
            operation_inputs["max_tokens"] = max_tokens
        if action == "complexity":
            operation_inputs["include_tests"] = include_tests
        if action == "ast_refactor" and diff:
            operation_inputs["diff"] = diff
        validation_error = validate_operation_arguments(
            "local_ai_repo", action, operation_inputs, features=FEATURES,
        )
        if validation_error is not None:
            return contract_error(validation_error)
    if action in {"preprocess", "preprocess_refresh", "preprocess_cancel", "preprocess_unregister"}:
        candidate = Path(root).expanduser()
        if not candidate.is_absolute():
            return {"success": False, "error": "Preprocessing requires an explicit absolute stable project root; do not use MCP process cwd"}
    elif action == "skeletonize":
        if path and not query:
            if not is_rooted_path(str(root or "").strip()):
                return contract_error("indexed skeleton requires an explicit absolute project root")
            root = _client_root(str(root).strip())
    else:
        explicit_root = str(root or "").strip()
        if not is_rooted_path(explicit_root):
            return {
                "success": False,
                "error": "Repository actions require an explicit absolute project root; do not use MCP process cwd",
            }
        root = _client_root(explicit_root)
    if action == "profile":
        return _compact(CLIENT.post("/api/repo/profile", {"root": root}, timeout=_timeout("quick")), "profile")
    if action == "investigate":
        return _compact(CLIENT.post("/api/repo/investigate", {
            "root": root, "query": query, "path": path, "include_code": include_code, "limit": 10,
        }, timeout=_timeout("quick")), "architecture")
    if action == "diagnose":
        return _compact(CLIENT.post("/api/repo/diagnose", {
            "root": root, "text": query,
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
        search_payload: dict[str, Any] = {
            "root": root,
            "query": query,
            "top_k": 12,
            "enrich": enrich,
            "limit": limit if explicit_limit else 24,
            "offset": offset,
        }
        return _compact(CLIENT.post("/api/search", search_payload, timeout=float(min(120, _timeout("quick"))), path_hints=normalized_hints or None), "search", extra_fields=extra if extra else None)
    if action == "map":
        return _compact(CLIENT.post("/api/repo/map", {"root": root, "max_symbols": 100}, timeout=_timeout("quick")), "architecture")
    if action == "code_index":
        return _compact(
            CLIENT.post("/api/repo/code-index", {"root": root, "query": query, "limit": limit, "offset": offset, "include_code": include_code}, timeout=_timeout("quick")),
            "code_index", identity={"root": root, "query": query},
        )
    if action in {"semantic", "intelligence"}:
        backend = "serena" if action == "semantic" else "auto"
        operation = relation or ("find_symbol" if backend == "serena" else "search")
        return _compact(CLIENT.post("/api/code-intelligence/query", {
            "root": root, "query": query, "path": path, "backend": backend, "action": operation, "limit": 24,
        }, timeout=_timeout("quick")), "architecture")
    if action == "deterministic":
        return _compact(CLIENT.post("/api/repo/deterministic", {"root": root, "query": query, "limit": 30}, timeout=_timeout("quick")), "context")
    if action == "context":
        if not isinstance(mode, str) or mode not in {"full", "fast", "adaptive"}:
            return _context_input_error("context mode must be adaptive, full or fast")
        path_controls = {
            "path_hints": path_hints,
            "directory_hints": directory_hints,
            "exclude_paths": exclude_paths,
            "force_include_paths": force_include_paths,
        }
        supplied_path_controls = any(value is not None for value in path_controls.values())
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
            or bool(changed_paths) or bool(focus)
        )
        configured_tokens = CFG.get("token_saving", {}).get("default_repo_context_tokens", 8000)
        effective_tokens = token_budget or max_tokens or configured_tokens
        payload: dict[str, Any] = {
            "root": root, "query": context_query, "workspace": workspace or None,
            "max_tokens": effective_tokens,
            "mode": "full" if mode == "full" else "adaptive" if mode == "adaptive" else "fast",
        }
        if guarded_requested:
            payload.update({
                "guarded": True if (changed_paths or focus) else bool(guarded),
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
        return _compact(CLIENT.post("/api/route", {"root": root, "path": path, "query": query}, timeout=_timeout("model")), "route")
    if action == "delegate":
        return _compact(CLIENT.post("/api/delegate/repo", {
            "root": root, "task": task, "workspace": workspace or None,
            "complexity": "auto", "context_tokens": max_tokens or 0, "max_tokens": max_tokens or 4096, "profile": profile,
        }, timeout=_timeout("model")), "delegate")
    if action == "solve":
        return _compact(CLIENT.post("/api/solve/repo", {
            "root": root, "task": task, "workspace": workspace or None, "mode": mode,
            "complexity": "auto", "context_tokens": max_tokens or 0, "base": base, "staged": staged,
        }, timeout=_timeout("long")), "solve")
    if action == "review_diff":
        payload = {
            "root": root, "base": base, "staged": staged,
            "instructions": task or "Report actionable defects, regressions, security/concurrency issues and missing tests only.",
            "complexity": "auto", "max_tokens": max_tokens or 4096, "mode": mode,
            # `local_ai_repo(action="review_diff")` is a targeted repository
            # check. Return its bounded result directly; callers needing
            # durable background execution can use local_ai_task submit/wait.
            "delivery": "sync", "latency_budget_ms": 30000,
        }
        if diff:
            payload["diff"] = diff
        return _compact(CLIENT.post("/api/review/diff", payload, timeout=_timeout("long")), "review_diff")
    if action == "impact":
        return _compact(CLIENT.post("/api/repo/impact", {"root": root, "base": base, "staged": staged}, timeout=_timeout("context")), "impact")
    if action == "refactor_impact":
        return _compact(CLIENT.post("/api/refactor_impact", {"root": root, "file": path, "symbol": query}, timeout=_timeout("quick")), "impact")
    if action == "resolve_imports":
        syms = [s.strip() for s in query.split(",") if s.strip()]
        return _compact(CLIENT.post("/api/resolve_imports", {"root": root, "symbols": syms, "language": language or "auto"}, timeout=_timeout("quick")), "context",
                        extra_fields=[*(extra_fields or []), "resolved_imports", "unresolved_symbols", "rejected_candidates",
                                      "rejected_candidates_truncated", "validation", "complete"])
    if action == "generate_tests":
        return _compact(CLIENT.post("/api/generate_tests", {"root": root, "file": path, "symbol": query}, timeout=_timeout("context")), "delegate")
    if action == "validate_patch":
        return _compact(CLIENT.post("/api/patch/validate", {"root": root, "patch": query}, timeout=_timeout("quick")), "verify")
    if action == "audit_dependencies":
        return _compact(CLIENT.post("/api/audit_dependencies", {"root": root}, timeout=_timeout("quick")), "context")
    if action == "ast_outline":
        return _compact(CLIENT.post("/api/code/ast_outline", {"root": root, "path": path}, timeout=_timeout("quick")), "architecture")
    if action == "affected_tests":
        paths_arg = [path] if path else None
        return _compact(CLIENT.post("/api/repo/affected_tests", {"root": root, "paths": paths_arg}, timeout=_timeout("quick")), "architecture")
    if action == "topology":
        return _compact(CLIENT.post("/api/repo/topology", {"root": root}, timeout=_timeout("quick")), "topology")
    if action == "ast_refactor":
        old_name = old_symbol
        new_name = new_symbol
        if any(not isinstance(name, str) or not name.strip() or "\x00" in name or len(name) > 512
               for name in (old_name, new_name)):
            return contract_error("ast_refactor requires non-empty old_symbol and new_symbol (at most 512 characters each)")
        return _compact(CLIENT.post("/api/code/ast_rename", {
            "root": root, "file": path, "old_symbol": old_name.strip(), "new_symbol": new_name.strip(), "apply": staged,
        }, timeout=_timeout("quick")), "verify")
    if action == "generate_mocks":
        return _compact(CLIENT.post("/api/code/generate_mocks", {
            "root": root, "file": path, "symbol": query,
        }, timeout=_timeout("quick")), "architecture")
    if action == "split_changes":
        return _compact(CLIENT.post("/api/repo/split_changes", {
            "root": root, "paths": [path] if path else None,
        }, timeout=_timeout("quick")), "architecture")
    if action == "synthesize_rules":
        return _compact(CLIENT.post("/api/repo/synthesize_rules", {
            "root": root, "limit": 10,
        }, timeout=_timeout("quick")), "architecture")
    if action == "test_matrix":
        return _compact(CLIENT.post("/api/test_matrix", {"root": root}, timeout=_timeout("quick")), "architecture")
    if action == "security_audit":
        return _compact(CLIENT.post("/api/security_audit", {"root": root}, timeout=_timeout("quick")), "security")
    if action == "git_status":
        raw_status = CLIENT.get(f"/api/git/status?root={quote(root)}")
        if path and isinstance(raw_status, dict):
            clean_p = path.strip().replace("\\", "/").rstrip("/")
            def _filter_p(items: Any) -> Any:
                if isinstance(items, list):
                    return [x for x in items if isinstance(x, str) and (x == clean_p or x.startswith(clean_p + "/"))]
                return items
            filtered_status = dict(raw_status)
            for k in ("changed_paths", "modified", "untracked", "staged", "deleted", "unmerged", "files"):
                if k in filtered_status:
                    filtered_status[k] = _filter_p(filtered_status[k])
            filtered_status["clean"] = not any(filtered_status.get(k) for k in ("changed_paths", "modified", "untracked", "staged", "deleted", "unmerged", "files"))
            return _compact(filtered_status, "status")
        return _compact(raw_status, "status")
    if action == "repo_state":
        return _compact(CLIENT.post("/api/repo/state", {"root": root}, timeout=_timeout("quick")), "status")
    if action == "synthesize_commit":
        synth_payload = {"root": root, "hint": query}
        if task_id:
            synth_payload["task_id"] = task_id
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
    if action == "cross_project_graph":
        return _compact(CLIENT.post("/api/cross_project_graph", {"roots": [root] if root else []}, timeout=_timeout("quick")), "architecture")
    if action == "cross_project_symbols":
        return _compact(CLIENT.post("/api/cross_project_symbols", {"roots": [root] if root else [], "query": query, "limit": 50}, timeout=_timeout("quick")), "architecture")
    if action == "cross_project_impact":
        return _compact(CLIENT.post("/api/cross_project_impact", {"roots": [root] if root else [], "symbol": query}, timeout=_timeout("quick")), "impact")
    if action in {"call_graph_diff", "semantic_diff"}:
        if action == "semantic_diff" and (old_code is not None or new_code is not None):
            if old_code is None or new_code is None:
                return contract_error("semantic_diff requires both old_code and new_code")
            return _compact(CLIENT.post("/api/repo/call_graph_diff", {
                "root": root, "old_code": old_code, "new_code": new_code,
            }, timeout=_timeout("quick")), "impact", extra_fields=[
                "changes", "tree", "summary", "source_hashes", "structural_equal", "formatting_only",
                "logic_edits_detected", "behavior_equivalence_proven", "changes_total", "changes_returned",
                "artifact_id", "truncated", "tree_in_artifact", "ambiguous_rename_groups", "ambiguous_identity_groups",
            ])
        return _compact(CLIENT.post("/api/repo/call_graph_diff", {"root": root or ".", "diff": diff or "" if diff else None}, timeout=_timeout("quick")), "impact")
    if action == "code_invariants":
        return _compact(CLIENT.post("/api/repo/code_invariants", {
            "root": root, "path": path or None,
        }, timeout=_timeout("quick")), "architecture")
    if action == "generate_dataset":
        return _compact(CLIENT.post("/api/repo/generate_dataset", {
            "root": root, "schema_or_model": query,
            "count": max_tokens or 10,
            "format": relation or "json",
        }, timeout=_timeout("quick")), "architecture")
    if action == "profile_digest":
        profile_path = path
        if profile_path and not is_rooted_path(profile_path):
            profile_path = str(Path(_client_root(root)) / profile_path)
        return _compact(CLIENT.post("/api/repo/profile_digest", {
            "profile_path": profile_path, "top_n": max_tokens or 15,
        }, timeout=_timeout("quick")), "architecture")
    if action == "callers":
        if not isinstance(query, str) or not query.strip() or task or path or isinstance(max_tokens, bool) or max_tokens != 0:
            return contract_error("callers requires query and uses limit/offset; task, path, and max_tokens are not supported aliases")
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return contract_error(bounds_error)
        return _compact(CLIENT.post("/api/repo/callers", {
            "root": root, "symbol": query, "limit": limit, "offset": offset,
        }, timeout=_timeout("quick")), "architecture", page_key="callers")
    if action == "callees":
        if not isinstance(query, str) or not query.strip() or task or path or isinstance(max_tokens, bool) or max_tokens != 0:
            return contract_error("callees requires query and uses limit/offset; task, path, and max_tokens are not supported aliases")
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return contract_error(bounds_error)
        return _compact(CLIENT.post("/api/code/callees", {
            "root": root, "symbol": query, "limit": limit, "offset": offset,
        }, timeout=_timeout("quick")), "architecture", page_key="callees")
    if action == "implementations":
        if not isinstance(query, str) or not query.strip() or task or isinstance(max_tokens, bool) or max_tokens != 0:
            return contract_error("implementations requires query and uses limit/offset; task and max_tokens are not supported aliases")
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return contract_error(bounds_error)
        return _compact(CLIENT.post("/api/code/implementations", {
            "root": root, "symbol": query, "path": path or None, "limit": limit, "offset": offset,
        }, timeout=_timeout("quick")), "architecture", page_key="implementations")
    if action == "declaration":
        return _compact(CLIENT.post("/api/code/declaration", {
            "root": root, "symbol": query, "path": path or None,
        }, timeout=_timeout("quick")), "architecture")
    if action == "revert":
        if not path:
            return contract_error("revert requires path")
        return _compact(CLIENT.post("/api/repo/revert", {"root": root, "path": path}, timeout=_timeout("quick")), "status")
    if action == "patch":
        target_code = old_code if old_code is not None else (target if target is not None else (query or ""))
        replacement_code = new_code if new_code is not None else (replacement if replacement is not None else (task if task is not None else ""))
        if not path or target_code is None or target_code == "":
            return contract_error("patch requires path and old_code/target")
        return _compact(CLIENT.post("/api/repo/patch", {
            "root": root, "path": path, "old_code": target_code, "new_code": replacement_code,
        }, timeout=_timeout("quick")), "repository result")
    if action in {"find_files", "glob"}:
        file_pat = pattern or query or "*"
        return _compact(CLIENT.post("/api/repo/find_files", {
            "root": root, "pattern": file_pat, "limit": limit or 100, "offset": offset or 0,
        }, timeout=_timeout("quick")), "repository result")
    if action == "call_graph":
        target_sym = query or task or ""
        if not target_sym:
            return contract_error("call_graph requires query (symbol name)")
        return _compact(CLIENT.post("/api/repo/call_graph", {
            "root": root, "symbol": target_sym, "path": path, "depth": depth or 1, "limit": limit or 50,
        }, timeout=_timeout("quick")), "architecture")
    if action == "dead_code":
        return _compact(CLIENT.post("/api/repo/dead_code", {
            "root": root, "limit": max_tokens or 50,
        }, timeout=_timeout("quick")), "architecture")
    if action == "secret_scan":
        if not isinstance(staged, bool):
            return _context_input_error("staged must be boolean for secret_scan")
        if secret_scan_query_supplied or secret_scan_task_supplied:
            return _context_input_error("secret_scan accepts path; query and task are not path aliases")
        if secret_scan_path_supplied and (not isinstance(path, str) or not path.strip()):
            return _context_input_error("path must be a non-empty string for secret_scan")
        return _compact(CLIENT.post("/api/repo/secret_scan", {
            "root": root, "path": path if secret_scan_path_supplied else None,
            "scan_git_history": staged,
        }, timeout=_timeout("quick")), "security")
    if action == "schema_inspect":
        return _compact(CLIENT.post("/api/repo/schema_inspect", {
            "root": root, "db_path": path or None,
        }, timeout=_timeout("quick")), "architecture")
    if action == "explain_query":
        return _compact(CLIENT.post("/api/repo/explain_query", {
            "root": root, "query": query, "db_path": path or None,
        }, timeout=_timeout("quick")), "architecture")
    if action == "env_compat":
        return _compact(CLIENT.post("/api/repo/env_compat", {
            "root": root,
        }, timeout=_timeout("quick")), "architecture")
    if action == "circular_dependencies":
        return _compact(CLIENT.post("/api/repo/circular_dependencies", {
            "root": root, "language": "python" if language in {"", "auto"} else language,
        }, timeout=_timeout("quick")), "architecture")
    if action == "generate_types":
        return _compact(CLIENT.post("/api/repo/generate_types", {
            "root": root, "path": path,
        }, timeout=_timeout("quick")), "architecture")
    if action == "complexity":
        return _compact(CLIENT.post("/api/repo/complexity", {
            "root": root, "path": path or None, "max_results": max_tokens or 20,
            "include_tests": bool(include_tests),
        }, timeout=_timeout("quick")), "complexity")
    if action == "api_spec":
        return _compact(CLIENT.post("/api/repo/api_spec", {
            "root": root, "framework": query or None,
        }, timeout=_timeout("quick")), "architecture")
    if action == "dependency_slice":
        return _compact(CLIENT.post("/api/repo/dependency_slice", {
            "root": root, "symbol": query, "path": path or None, "depth": max(1, min(max_tokens or 2, 8)),
        }, timeout=_timeout("quick")), "architecture")
    if action == "migration_drift":
        return _compact(CLIENT.post("/api/repo/migration_drift", {
            "root": root, "db_path": path or None,
        }, timeout=_timeout("quick")), "architecture")
    if action == "package_audit":
        return _compact(CLIENT.post("/api/repo/package_audit", {
            "root": root, "lockfile_path": path or None,
        }, timeout=_timeout("quick")), "architecture")
    if action == "structural_search":
        return _compact(CLIENT.post("/api/repo/structural_search", {
            "root": root, "pattern": query, "path": path or None, "max_results": max_tokens or 30,
        }, timeout=_timeout("quick")), "architecture")
    if action == "context_budget":
        files_arg = [path] if path else ([query] if query and not query.startswith("-") else [])
        return _compact(CLIENT.post("/api/repo/context_budget", {
            "root": root, "files": files_arg, "max_tokens": max_tokens or 4000,
        }, timeout=_timeout("quick")), "architecture", extra_fields=[
            *(extra_fields or []), "token_count_provenance", "omitted_files", "complete", "slice_recommendations_estimated",
        ])
    if action in {"file_info", "stat"}:
        return _compact(CLIENT.post("/api/repo/file_info", {"root": root, "path": path or ""}), "repository")
    if action in {"read_file", "source"}:
        from .source_slice import read_source_slice
        eff_start = start_line if start_line > 1 else line_start
        eff_end = end_line if end_line > 0 else line_end
        target_root = Path(root or _workspace)
        slice_res = read_source_slice(target_root, path=path or "", line_start=eff_start, line_end=eff_end, max_chars=max_tokens or 4000)
        if isinstance(slice_res, dict) and "text" in slice_res and "content" not in slice_res:
            slice_res["content"] = slice_res["text"]
        return _compact(slice_res, "artifact")
    if action == "git_diff":
        eff_rev1 = rev1 or (base if (head or (base and base != "HEAD")) else None)
        eff_rev2 = rev2 or head
        if eff_rev1 is not None or eff_rev2 is not None:
            eff_rev1 = eff_rev1 or "HEAD~1"
            eff_rev2 = eff_rev2 or "HEAD"
            if staged or any(not isinstance(value, str) or not value.strip() or len(value) > 512
                             or value.startswith("-") or "\0" in value for value in (eff_rev1, eff_rev2)):
                return contract_error("git_diff requires valid rev1 and rev2 together, without staged")
            return _compact(CLIENT.post("/api/git/diff", {
                "root": root, "path": path or None, "staged": False,
                "max_lines": max_tokens or 500, "rev1": eff_rev1, "rev2": eff_rev2, "base": base, "head": eff_rev2,
            }, timeout=_timeout("context")), "diff", extra_fields=[
                *(extra_fields or []), "comparison", "rev1", "rev2", "resolved_rev1", "resolved_rev2",
                "stats_complete", "paths_complete", "diff_sha256",
            ])
        return _compact(CLIENT.get(f"/api/git/diff?root={quote(root)}&path={quote(path or '')}&staged={'true' if staged else 'false'}&max_lines={max_tokens or 500}&base={quote(base or 'HEAD')}"), "diff",
                        extra_fields=[*(extra_fields or []), "stats_complete", "paths_complete", "diff_sha256", "comparison"])
    if action in {"git_history_search", "git_log"}:
        max_c = limit or max_commits or 20
        return _compact(CLIENT.post("/api/git/history_search", {
            "root": root, "query": query or "", "max_commits": max_c,
            "author": author or None, "since": since or None, "until": until or None,
            "path": path or None,
        }, timeout=_timeout("quick")), "architecture", extra_fields=[
            *(extra_fields or []), "author", "since", "until", "path", "max_commits",
            "count", "commits", "complete", "incomplete_reasons",
        ])
    if action == "hotspots":
        if diff or max_tokens:
            return contract_error("hotspots accepts only canonical days and limit fields")
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650:
            return contract_error("days must be an integer from 1 to 3650 for action='hotspots'")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            return contract_error("limit must be an integer from 1 to 50 for action='hotspots'")
        return _compact(CLIENT.post("/api/repo/hotspots", {
            "root": root, "days": days, "limit": limit,
        }, timeout=_timeout("quick")), "architecture", extra_fields=[
            *(extra_fields or []), "days", "algorithm", "recency_half_life_days",
            "recency_weighting", "complete", "incomplete_reasons", "analysis", "hotspots",
        ])
    if action == "generate_tests_for_diff":
        eff_path = path or (changed_paths[0] if changed_paths and len(changed_paths) > 0 else None)
        return _compact(CLIENT.post("/api/repo/generate_tests_for_diff", {
            "root": root, "diff": diff or None, "path": eff_path,
        }, timeout=_timeout("context")), "delegate")
    if action == "cross_repo_contract":
        return _compact(CLIENT.post("/api/repo/cross_repo_contract", {
            "backend_root": root, "frontend_root": path,
        }, timeout=_timeout("quick")), "architecture")
    if action == "reachability_dead_code":
        return _compact(CLIENT.post("/api/repo/reachability_dead_code", {
            "root": root, "entrypoints": [path] if path else None,
        }, timeout=_timeout("context")), "architecture")
    if action == "mutation_test":
        return _compact(CLIENT.post("/api/repo/mutation_test", {
            "root": root, "file": path or None, "diff": diff or None,
        }, timeout=_timeout("context")), "delegate")
    if action == "type_stubs":
        return _compact(CLIENT.post("/api/repo/type_stubs", {
            "root": root, "file": path or None,
        }, timeout=_timeout("quick")), "code")
    if action == "skeletonize":
        source_code = query
        skeleton_payload: dict[str, Any] = {
            "code": source_code,
            "targets": [path] if path and source_code else None,
        }
        if path and not source_code:
            skeleton_payload["path"] = path
        if root and is_rooted_path(str(root).strip()):
            skeleton_payload["root"] = _client_root(str(root).strip())
        return _compact(CLIENT.post("/api/repo/skeletonize", skeleton_payload, timeout=_timeout("quick")), "code")
    return _invalid_action("local_ai_repo", action, tuple(FEATURES.supported_repo_actions()), "Keep work bounded in Local AI Hub; use Codex-owned orchestration for peer subagents.")


@mcp.tool()
@_instrumented_tool()
def local_ai_repo(
    action: RepoAction,
    root: str = ".",
    query: str | None = None,
    diff: str | None = None,
    task: str | None = None,
    workspace: str | None = None,
    path: str | None = None,
    base: str = "HEAD",
    staged: bool = False,
    dry_run: bool = False,
    max_tokens: int | None = None,
    evidence: list[dict[str, Any]] | None = None,
    mode: str = "adaptive",
    relation: str | None = None,
    language: str = "auto",
    profile: str = "",
    task_id: str | None = None,
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
    *,
    limit: int | None = None,
    offset: int = 0,
    old_symbol: str | None = None,
    new_symbol: str | None = None,
    old_code: str | None = None,
    new_code: str | None = None,
    rev1: str | None = None,
    rev2: str | None = None,
    max_commits: int | None = None,
    author: str | None = None,
    since: str | None = None,
    until: str | None = None,
    days: int | None = None,
    depth: int = 1,
    pattern: str | None = None,
    target: str | None = None,
    replacement: str | None = None,
    head: str | None = None,
    start_line: int = 1,
    end_line: int = 0,
    line_start: int = 1,
    line_end: int = 0,
    file: str | None = None,
) -> dict[str, Any]:
    """Primary bounded repository worker. For simple fact/location questions, use one concise `context` query for natural language, `search` for a known filename/term, or `code_index` for a known symbol. These lookup actions default to compact output; an explicit `response_profile` overrides that default. Stop when source-backed evidence answers the question; inspect only the exact candidate path if needed. Avoid generic one-word searches, repeated retrieval layers, unrelated call sites, and language-specific actions unsupported by the project."""
    if pattern and not query:
        query = pattern
    if file and not path:
        path = file
    if not path and changed_paths and len(changed_paths) > 0 and action == "generate_tests_for_diff":
        path = changed_paths[0]
    if not edits and path and ((target and replacement) or (old_code and new_code)):
        edits = [{"path": path, "target": target or old_code, "replacement": replacement or new_code}]
    if action == "context" and not query and task:
        query = task
    elif action in {"solve", "delegate"} and not task and query:
        task = query
    elif action == "diff":
        action = "git_diff"
    elif action == "status":
        action = "git_status"
    elif action in {"file_info", "stat"}:
        action = "file_info"
    elif action in {"read_file", "source"}:
        action = "source"
    elif action == "glob":
        action = "find_files"
    elif action == "patch":
        if target is not None and old_code is None:
            old_code = target
        if replacement is not None and new_code is None:
            new_code = replacement
    forward: dict[str, Any] = {}
    context_controls = {
        "path_hints": path_hints,
        "directory_hints": directory_hints,
        "exclude_paths": exclude_paths,
        "force_include_paths": force_include_paths,
    }
    resolved_action = action
    if not isinstance(resolved_action, str) or resolved_action not in operation_actions("local_ai_repo", FEATURES):
        return _invalid_action(
            "local_ai_repo", resolved_action, operation_actions("local_ai_repo", FEATURES),
            "Use a canonical advertised repository action.",
        )
    scoped_validation = validate_operation_arguments(
        "local_ai_repo", resolved_action,
        _repo_validation_arguments(resolved_action, locals()),
    )
    if scoped_validation is not None:
        return {"success": False, "error": scoped_validation, "status_code": 400,
                "terminal": True, "retryable": False}
    if not response_profile and resolved_action in {"context", "search", "code_index"}:
        response_profile = "compact"
    if resolved_action == "hotspots" and (diff is not None or max_tokens is not None):
        return {"success": False, "error": "hotspots accepts only canonical days and limit fields",
                "status_code": 400, "terminal": True, "retryable": False}
    if resolved_action in {"search", "code_index", "callers", "callees", "implementations"}:
        effective_limit = 24 if limit is None else limit
        pagination_error = validate_operation_arguments(
            "local_ai_repo", resolved_action,
            _repo_validation_arguments(resolved_action, {**locals(), "limit": effective_limit}),
        )
        if pagination_error is not None:
            return {"success": False, "error": pagination_error, "status_code": 400,
                    "terminal": True, "retryable": False}
    if resolved_action == "hotspots":
        hotspot_error = validate_operation_arguments(
            "local_ai_repo", resolved_action,
            _repo_validation_arguments(resolved_action, {
                **locals(), "days": 30 if days is None else days,
                "limit": 20 if limit is None else limit,
            }),
        )
        if hotspot_error is not None:
            return {"success": False, "error": hotspot_error, "status_code": 400,
                    "terminal": True, "retryable": False}
    if resolved_action in {"git_history_search", "git_log"}:
        if query is None:
            query = ""
        if (
            not isinstance(query, str)
            or len(query) > 512
            or any(ord(char) < 32 or ord(char) == 127 for char in query)
        ):
            return {"success": False, "error": "query must be a bounded literal string", "status_code": 400,
                    "terminal": True, "retryable": False}
        history_error = validate_operation_arguments(
            "local_ai_repo", resolved_action,
            {
                "query": query, "max_commits": 50 if max_commits is None else max_commits,
                "author": "" if author is None else author,
                "since": "" if since is None else since,
                "until": "" if until is None else until, "path": path,
            },
        )
        if history_error is not None:
            return {"success": False, "error": history_error, "status_code": 400,
                    "terminal": True, "retryable": False}
    if any(value is not None for value in context_controls.values()):
        if resolved_action == "context":
            validation_error = validate_operation_arguments(
                "local_ai_repo", resolved_action,
                _repo_validation_arguments(resolved_action, {**locals(), **context_controls}),
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
                "local_ai_repo", resolved_action,
                _repo_validation_arguments(resolved_action, {**locals(), "path_hints": path_hints}),
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
        max_tokens, evidence, mode, relation, language, profile, task_id,
        include_code, include_tests, edits, extra_fields, max_response_tokens, response_profile, reuse_key,
        include_diagnostics, clone_id, worktree_id, branch, repository_id, session_id, repository_revision,
        changed_paths, phase, focus, preload_profile, guarded, since_hash, approval, override_reason,
        token_budget, is_worktree, parent_root, steps, limit=limit, offset=offset,
        old_symbol=old_symbol, new_symbol=new_symbol, old_code=old_code, new_code=new_code, rev1=rev1, rev2=rev2,
        max_commits=max_commits, author=author, since=since, until=until, days=days, depth=depth, pattern=pattern, target=target, replacement=replacement, head=head, start_line=start_line, end_line=end_line, line_start=line_start, line_end=line_end, file=file, **forward,
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
    limit: int = 0,
    task: str = "",
    extra_fields: list[str] | None = None,
    max_response_tokens: int = 0,
    response_profile: str = "",
    reuse_key: str = "",
    content: str = "",
    title: str = "",
    metadata: dict[str, Any] | None = None,
    image_path: str = "",
    caption: str = "",
    name: str = "",
    text: str = "",
    path: str = "",
    file: str = "",
) -> dict[str, Any]:
    """Fallback semantic retrieval after deterministic and indexed repository evidence. Search defaults workspace to the explicit repository root. Document ingestion requires non-empty content; title and metadata are optional. Diagram ingestion requires image_path; caption and metadata are optional. Raster diagrams are indexed as metadata-only; SVG text nodes are indexed with their extraction provenance. Use when: cheaper indexed paths are insufficient. Skip when: deterministic or indexed evidence already answers the question."""
    if not FEATURES.rag:
        return {"success": False, "unsupported": True, "error": "RAG backend is disabled (features.rag=false in config.toml)"}
    valid_actions = tuple(RagAction.__args__)
    if not isinstance(action, str) or action not in valid_actions:
        action_label = action if isinstance(action, str) else f"<{type(action).__name__}>"
        return _invalid_action("local_ai_rag", action_label, valid_actions, "Use RAG only when cheaper Local AI Hub evidence is insufficient.")
    if name and not workspace:
        workspace = name
    if limit > 0:
        top_k = limit
    if task and not query:
        query = task
    if action == "search" and not query and content:
        query = content
    if action == "search" and not query and text:
        query = text
    if (path or file) and not image_path and action == "ingest_diagram":
        image_path = path or file
    if (path or file) and not content and action == "ingest_document":
        doc_p = path or file
        from pathlib import Path as _P
        cand_p = _P(doc_p) if _P(doc_p).is_absolute() else (_P(root) / doc_p)
        if cand_p.is_file():
            try:
                content = cand_p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
    if action == "ingest_document" and not content and text:
        content = text
    if action in {"index", "search", "docset_index", "ingest_document", "ingest_diagram"}:
        explicit_root = str(root or "").strip()
        if not is_rooted_path(explicit_root):
            return {
                "success": False,
                "error": "RAG repository actions require an explicit absolute project root; do not use MCP process cwd",
            }
        root = _client_root(explicit_root)
    else:
        root = _client_root(root)
    effective_workspace = workspace.strip() or root
    if action in {"index", "search", "ingest_document", "ingest_diagram"} and (
        not workspace.strip() or is_rooted_path(workspace.strip())
    ):
        effective_workspace = canonical_workspace_id(root)
    if action == "index":
        return _compact(CLIENT.post("/api/rag/index", {"root": root, "workspace": effective_workspace}, timeout=_timeout("long")))
    if action == "search":
        return _compact(CLIENT.post("/api/rag/search", {
            "root": root, "query": query, "workspace": effective_workspace,
            "top_k": max(1, min(top_k, 12)), "use_reranker": True,
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
            "root": root, "workspace": effective_workspace,
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
            "root": root, "workspace": effective_workspace,
            "image_path": image_path,
            "caption": caption,
            "metadata": metadata if isinstance(metadata, dict) else None,
        }, timeout=_timeout("quick")), "status")
    return _invalid_action("local_ai_rag", action, tuple(RagAction.__args__), "Use RAG only when cheaper Local AI Hub evidence is insufficient.")





@mcp.tool()
@_instrumented_tool()
def local_ai_coord(
    action: CoordAction,
    root: str = ".",
    paths: list[str] | None = None,
    lease_id: str = "",
    owner: str = "",
    purpose: str = "agent edit",
    key: str = "",
    value: str = "",
    query: str = "",
    command: str = "",
    command_id: str = "",
    ttl_seconds: int | None = None,
    max_tokens: int = 0,
    task: str = "",
    task_id: str = "",
    question_id: str = "",
    question: str = "",
    answer: str = "",
    contract: dict[str, Any] | None = None,
    receipt: dict[str, Any] | None = None,
    checkpoint: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
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
    state_revision: str = "",
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
    repository_revision: str = "",
    phase: str = "",
    focus: list[str] | None = None,
    preload_profile: str = "",
    since_hash: str = "",
    expected_version: int | None = None,
    after_seq: int | None = None,
    after_ts: float | None = None,
    format: str | None = None,
    sync_action: str | None = None,
    stream_id: str | None = None,
    events: list[dict[str, Any]] | None = None,
    limit: int | None = None,
    content: Any = None,
    author: str = "agent",
    remote_sections: dict[str, Any] | None = None,
    topic: str = "default",
    message: Any = None,
    publisher: str = "agent",
    goal: str = "",
    target_paths: list[str] | None = None,
    test_command: str = "",
    swarm_id: str = "",
    role: str = "Coder",
    swarm_action: str = "submit_patch",
    payload: dict[str, Any] | None = None,
    state: str = "",
    source_branch: str = "",
    target_branch: str = "HEAD",
    worktree_path: str = "",
    delete_branch: bool = True,
    output_path: str = "training_dataset.jsonl",
    min_receipts: int = 1,
    name: str = "",
    item_id: str = "",
    title: str = "",
    priority: str = "",
    labels: list[str] | None = None,
    assignee: str = "",
    milestone: str = "",
    linked_task_id: str = "",
    details: dict[str, Any] | None = None,
    target_date: str = "",
    description: str = "",
    capacity: int = 1,
    timeout: float = 0.0,
    filter: dict[str, Any] | None = None,
    filter_payload: dict[str, Any] | None = None,
    include: list[str] | None = None,
    confidence: float | None = None,
    allow_adopt: bool = False,
    acceptance_criteria: list[str] | None = None,
    criteria: list[str] | None = None,
    error: str = "",
    kind: str = "",
    changed_paths: list[str] | None = None,
    path: str = "",
    file: str = "",
    next_action: str = "",
    blockers: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    id: str = "",
    summary: str = "",
    result: str = "",
    timeout_seconds: float = 0.0,
    notes: str = "",
    state_data: dict[str, Any] | None = None,
    resource: str = "",
    plan_id: str = "",
    expected_revision: str | None = None,
    idempotency_key: str = "",
    task_data: dict[str, Any] | None = None,
    lifecycle: str | None = None,
    default_target_ref: str | None = None,
    spec_refs: list[dict[str, Any]] | None = None,
    accountable_role: str | None = None,
    tasks: dict[str, Any] | None = None,
    plan_task_id: str = "",
    steering_id: str = "",
    spec_rel_path: str = "",
    spec_content: str = "",
    expected_spec_revision: str = "",
) -> dict[str, Any]:
    """Cross-agent coordination for the main agent and bounded Hub workers. ask persists a repository/session-scoped question; retrieve it later with the same question_id, root and session_id. answer records an operator response under the authorized repository root. Public actions are limited to the contract enum; unscoped memory relation/reaping storage remains private. Claim overlapping edit paths before concurrent Hub work. Use scoped Agent OS memory_find/memory_record for reusable findings; workspace memo actions are operator-only and unavailable through this tool. Native peer subagents are coordinated by Codex rather than by this Hub tool."""
    if not FEATURES.coord:
        return {"success": False, "unsupported": True, "error": "local_ai_coord is disabled in configuration"}
    if isinstance(action, str) and action.startswith("plan_"):
        # Preserve omission versus explicit null; do not inject other actions' defaults.
        options = _CURRENT_RESPONSE_OPTIONS.get() or {}
        raw_call = _CURRENT_MCP_CALL_ARGUMENTS.get()
        supplied = (
            raw_call[1] if raw_call is not None and raw_call[0] == "local_ai_coord"
            else options.get("arguments") if options.get("tool") == "local_ai_coord" else None
        )
        if not isinstance(supplied, dict):
            current = locals().copy()
            signature = inspect.signature(local_ai_coord)
            supplied = {name: value for name, value in current.items()
                        if name in signature.parameters and value != signature.parameters[name].default}
        else:
            supplied = dict(supplied)
        # Some MCP hosts attach current-task metadata to every coordination
        # call. Plans have their own task/path contract, so these envelope
        # fields must not make plan actions fail strict per-action validation.
        supplied.pop("changed_paths", None)
        error = validate_operation_arguments("local_ai_coord", action, supplied)
        if error:
            return contract_error(error, status_code=400)
        metadata = operation_contract("local_ai_coord")["actions"][action]
        arguments = {name: value for name, value in supplied.items() if name in metadata["allowed"]}
        return _compact(CLIENT.coord(action=action, **arguments), "coord" if action == "plan_bind_task" else "status")
    if changed_paths is not None and not paths:
        paths = changed_paths
    if (path or file) and not paths:
        paths = [p for p in (path, file) if p]
    if id and not task_id and (action.startswith("task_") or action in {"verify_completion", "verify_export"}):
        task_id = id
    if id and not item_id and action.startswith("board_item_"):
        item_id = id
    if id and not question_id and action in {"ask", "answer"}:
        question_id = id
    if (summary or result) and not reason:
        reason = summary or result
    if timeout_seconds and not timeout:
        timeout = timeout_seconds
    if isinstance(labels, str):
        labels = [labels]
    if action.startswith("board_item_") and task_id and not linked_task_id:
        linked_task_id = task_id
    if resource and not name:
        name = resource
    if state and not status and action == "task_list":
        status = state
    if notes and not next_action:
        next_action = notes
    if after_seq is not None and (isinstance(after_seq, bool) or not isinstance(after_seq, int) or not 0 <= after_seq <= MAX_EVENT_SEQUENCE):
        return contract_error(f"after_seq must be an integer between 0 and {MAX_EVENT_SEQUENCE}")
    if not isinstance(action, str) or action not in operation_actions("local_ai_coord", None):
        return _invalid_action(
            "local_ai_coord", action, operation_actions("local_ai_coord", None),
            "Use a canonical advertised coordination action.",
        )
    if action in {"memory_reap", "relation_record", "relation_find", "relation_traverse"}:
        return _invalid_action(
            "local_ai_coord",
            action,
            tuple(CoordAction.__args__),
            "Unscoped memory maintenance and relations remain private until explicit repository scope is supported.",
        )
    if action in {"negative_knowledge_record", "negative_knowledge_find", "incident_decision"}:
        try:
            if not isinstance(root, str) or not root.strip() or root != root.strip() or not is_rooted_path(root):
                raise RepositoryScopeError(
                    "incident operations require an explicit absolute repository root",
                    "incident_root_required",
                )
            root = str(canonical_repository_root(root))
            if isinstance(record, dict):
                reject_retired_tenancy_fields(record)
                if "root" in record:
                    raise RepositoryScopeError("record cannot override root", "invalid_incident_root")
        except RepositoryScopeError as exc:
            return contract_error(str(exc), status_code=exc.status_code)
    if action == "task_sync":
        rejection = _subminimum_budget_rejection({"max_response_tokens": max_response_tokens})
        if rejection is not None:
            return rejection
    if action == "task_sync":
        if status or key or task_id or ttl_seconds is not None or max_tokens != 0 or record is not None:
            return contract_error("task_sync accepts only sync_action, stream_id, after_seq, limit, and events")
        sync_inputs = {
            name: value for name, value in {
                "sync_action": sync_action,
                "stream_id": stream_id,
                "after_seq": after_seq,
                "limit": limit,
                "events": events,
            }.items() if value is not None
        }
        sync_error = validate_operation_arguments("local_ai_coord", action, sync_inputs)
        if sync_error is not None:
            return contract_error(sync_error, status_code=400)
        sync_act = "export" if sync_action is None else sync_action
        if sync_act == "export":
            sync_stream = "" if stream_id is None else stream_id
            sync_after_seq = 0 if after_seq is None else after_seq
            sync_limit = 1000 if limit is None else limit
            return _compact(CLIENT.post("/api/agent-state/events/delta", {
                "action": "export", "stream_id": sync_stream,
                "after_seq": sync_after_seq, "limit": sync_limit,
            }, timeout=_timeout("quick")), "status")
        return _compact(CLIENT.post("/api/agent-state/events/delta", {
            "action": "import", "events": events,
        }, timeout=_timeout("quick")), "status")
    incident_legacy_values: dict[str, dict[str, Any]] = {
        "negative_knowledge_record": {
            "key": key, "value": value, "query": query, "reason": reason, "status": status,
            "record_id": record_id, "tool_outcome": tool_outcome, "fingerprint": fingerprint,
            "state_revision": state_revision, "limit": limit,
        },
        "negative_knowledge_find": {
            "key": key, "value": value, "reason": reason, "status": status,
            "record_id": record_id, "tool_outcome": tool_outcome, "fingerprint": fingerprint,
            "record": record, "state_revision": state_revision,
        },
        "incident_decision": {
            "value": value, "query": query, "reason": reason, "status": status,
            "record_id": record_id, "tool_outcome": tool_outcome, "record": record,
            "repository_revision": repository_revision, "key": key, "limit": limit,
        },
    }
    if action in incident_legacy_values and any(
        item is not None and item != "" and item != 0
        for item in incident_legacy_values[action].values()
    ):
        return contract_error(f"action='{action}' accepts only canonical incident fields", status_code=400)
    sync_only_inputs = {
        name: value for name, value in {
            "sync_action": sync_action,
            "stream_id": stream_id,
            "events": events,
        }.items() if value is not None
    }
    if sync_only_inputs:
        sync_error = validate_operation_arguments("local_ai_coord", action, sync_only_inputs)
        if sync_error is not None:
            return contract_error(sync_error, status_code=400)
    board_actions = {
        "blackboard_update", "blackboard_get", "blackboard_list",
        "blackboard_merge", "blackboard_delete",
    }
    pubsub_actions = {"pubsub_publish", "pubsub_poll"}
    if action in board_actions | pubsub_actions:
        ignored_values = {
            "paths": paths, "lease_id": lease_id, "key": key, "value": value,
            "query": query, "command": command, "ttl_seconds": ttl_seconds,
            "max_tokens": max_tokens, "task": task, "question_id": question_id,
            "question": question, "answer": answer, "contract": contract,
            "receipt": receipt, "checkpoint": checkpoint, "status": status,
            "reason": reason, "record": record, "record_id": record_id,
            "criterion": criterion, "scope": scope, "scope_id": scope_id,
            "target_scope": target_scope, "approver": approver,
            "fingerprint": fingerprint, "tool_outcome": tool_outcome,
            "include_diagnostics": include_diagnostics, "include_stale": include_stale,
            "clone_id": clone_id, "worktree_id": worktree_id, "branch": branch,
            "repository_id": repository_id, "session_id": session_id,
            "repository_revision": repository_revision,
            "phase": phase, "focus": focus, "preload_profile": preload_profile,
            "since_hash": since_hash, "sync_action": sync_action,
            "stream_id": stream_id, "events": events, "format": format,
        }
        unexpected_values = {
            name: supplied for name, supplied in ignored_values.items()
            if supplied is not None and supplied is not False and supplied != "" and supplied != 0
            and not (name == "format" and supplied == "markdown")
        }
        if unexpected_values:
            return contract_error(
                f"action='{action}' accepts only canonical fields; unexpected field {sorted(unexpected_values)[0]!r}",
                status_code=400,
            )
        canonical_inputs: dict[str, Any] = {"root": root}
        if action in board_actions:
            if not isinstance(task_id, str) or not isinstance(board_id, str) or not isinstance(section, str):
                return contract_error("task_id, board_id, and section must be strings", status_code=400)
            if task_id:
                canonical_inputs["task_id"] = task_id
            if action != "blackboard_list":
                canonical_inputs["board_id"] = board_id or task_id or "default"
            if action in {"blackboard_update", "blackboard_get", "blackboard_delete"} and section:
                canonical_inputs["section"] = section
            if action == "blackboard_update":
                canonical_inputs.update(content=content, author=author)
                if expected_version is not None:
                    canonical_inputs["expected_version"] = expected_version
            elif action == "blackboard_merge" and remote_sections is not None:
                canonical_inputs["remote_sections"] = remote_sections
            if action != "blackboard_update" and (
                content is not None or author != "agent" or expected_version is not None
            ):
                return contract_error("content, author, and expected_version are only valid for action='blackboard_update'", status_code=400)
            if action != "blackboard_merge" and remote_sections is not None:
                return contract_error("remote_sections is only valid for action='blackboard_merge'", status_code=400)
            if action in {"blackboard_list", "blackboard_merge"} and section:
                return contract_error(f"section is not valid for action='{action}'", status_code=400)
            if action == "blackboard_list" and board_id:
                return contract_error("board_id is not valid for action='blackboard_list'", status_code=400)
        else:
            if task_id or board_id or section or content is not None or author != "agent" or remote_sections is not None or expected_version is not None:
                return contract_error(f"task and blackboard fields are not valid for action='{action}'", status_code=400)
            canonical_inputs.update(topic=topic)
            if action == "pubsub_publish":
                canonical_inputs.update(message=message, publisher=publisher)
                if after_seq is not None or limit is not None or after_ts is not None:
                    return contract_error("after_seq, limit, and after_ts are only valid for action='pubsub_poll'", status_code=400)
            else:
                if message is not None or publisher != "agent":
                    return contract_error("message and publisher are only valid for action='pubsub_publish'", status_code=400)
                if after_seq is not None:
                    canonical_inputs["after_seq"] = after_seq
                if limit is not None:
                    canonical_inputs["limit"] = limit
                if after_ts is not None:
                    canonical_inputs["after_ts"] = after_ts
        validation_error = validate_operation_arguments(
            "local_ai_coord", action, canonical_inputs,
        )
        if validation_error is not None:
            return contract_error(validation_error, status_code=400)
    legacy_coord_values: dict[str, dict[str, Any]] = {
        "ask": {"record_id": record_id, "key": key, "query": query, "value": value, "answer": answer},
        "answer": {"record_id": record_id, "key": key, "query": query, "value": value, "question": question},
        "task_cleanup_worktree": {"key": key},
        "context_compile": {
            "query": query, "value": value, "key": key, "record_id": record_id,
            "status": status, "fingerprint": fingerprint, "ttl_seconds": ttl_seconds,
        },
        "verify_receipt": {
            "checkpoint": checkpoint, "task_id": task_id, "criterion": criterion,
            "key": key, "value": value, "query": query, "status": status, "record": record,
        },
        "verify_completion": {"query": query, "value": value, "key": key},
        "verify_export": {"query": query, "value": value, "key": key, "section": section, "status": status},
        "swarm_dispatch": {
            "task": task, "value": value, "query": query, "paths": paths,
            "command": command, "approver": approver, "target_scope": target_scope,
            "key": key, "task_id": task_id,
        },
        "swarm_step": {
            "task": task, "task_id": task_id, "key": key, "target_scope": target_scope,
            "query": query, "record": record, "value": value, "paths": paths,
            "command": command, "approver": approver,
        },
        "swarm_status": {"task_id": task_id, "key": key, "task": task},
        "swarm_list": {"status": status},
        "swarm_cancel": {
            "task": task, "task_id": task_id, "key": key, "target_scope": target_scope,
            "query": query, "record": record, "value": value,
        },
        "worktree_lease": {"task": task, "task_id": task_id, "key": key, "value": value, "lease_id": lease_id, "worktree_path": worktree_path},
        "worktree_release": {
            "task": task, "task_id": task_id, "key": key, "value": value,
            "lease_id": lease_id, "target_scope": target_scope, "status": status,
        },
        "simulate_merge": {
            "task": task, "task_id": task_id, "key": key, "value": value,
            "branch": branch, "target_scope": target_scope, "query": query,
        },
        "curate_dataset": {
            "task": task, "task_id": task_id, "key": key, "value": value,
            "query": query, "status": status, "target_scope": target_scope,
        },
        "negative_knowledge_record": {
            "key": key, "value": value, "query": query, "reason": reason,
            "status": status, "record_id": record_id, "tool_outcome": tool_outcome,
            "fingerprint": fingerprint, "state_revision": state_revision,
            "repository_revision": repository_revision,
        },
        "negative_knowledge_find": {
            "key": key, "value": value, "reason": reason, "status": status,
            "record_id": record_id, "tool_outcome": tool_outcome, "fingerprint": fingerprint,
            "record": record, "state_revision": state_revision,
            "repository_revision": repository_revision,
        },
        "incident_decision": {
            "value": value, "query": query, "reason": reason, "status": status,
            "record_id": record_id, "tool_outcome": tool_outcome, "record": record,
            "repository_revision": repository_revision, "key": key,
        },
    }
    if action in legacy_coord_values and any(
        (value != "" if isinstance(value, str) else value != 0 if type(value) is int else value is not None)
        for value in legacy_coord_values[action].values()
    ):
        return contract_error(f"action='{action}' accepts only canonical fields", status_code=400)
    if action in {"negative_knowledge_record", "incident_decision"} and limit is not None:
        return contract_error(f"limit is not valid for action='{action}'", status_code=400)
    if receipt is not None and action != "verify_receipt":
        return contract_error("receipt is only valid for action='verify_receipt'", status_code=400)
    if since_hash != "" and action != "context_compile":
        return contract_error("since_hash is only valid for action='context_compile'", status_code=400)
    if format is not None and action not in {"verify_export", "curate_dataset"}:
        return contract_error("format is only valid for action='verify_export' or 'curate_dataset'", status_code=400)
    if action == "curate_dataset" and type(min_receipts) is not int:
        return contract_error("min_receipts must be an integer for action='curate_dataset'", status_code=400)
    coord_canonical_inputs: dict[str, dict[str, Any]] = {
        "ask": {
            "root": root, "session_id": session_id,
            "question_id": question_id, "question": question, "task_id": task_id,
        },
        "answer": {"root": root, "question_id": question_id, "answer": answer, "task_id": task_id},
        "task_cleanup_worktree": {"root": root, "task_id": task_id},
        "task_zombie_reap": {"root": root, "task_id": task_id},
        "context_compile": {
            "root": root, "task_id": task_id, "since_hash": since_hash,
            "max_tokens": max_tokens or 4000, "include_diagnostics": include_diagnostics,
            "clone_id": clone_id, "worktree_id": worktree_id, "branch": branch,
            "repository_id": repository_id, "session_id": session_id,
            "repository_revision": repository_revision, "phase": phase,
            "focus": focus or [], "preload_profile": preload_profile,
        },
        "verify_receipt": {"root": root, "receipt": receipt},
        "verify_completion": {"root": root, "task_id": task_id, "repository_revision": repository_revision},
        "verify_export": {"root": root, "task_id": task_id, "format": "markdown" if format is None else format},
        "swarm_dispatch": {
            "root": root, "goal": goal,
            "target_paths": [] if target_paths is None else target_paths,
            "test_command": test_command, "author": author,
        },
        "swarm_step": {
            "root": root, "swarm_id": swarm_id, "role": role,
            "swarm_action": swarm_action, "payload": {} if payload is None else payload,
        },
        "swarm_status": {"root": root, "swarm_id": swarm_id},
        "swarm_list": {"root": root, "state": state},
        "swarm_cancel": {"root": root, "swarm_id": swarm_id, "reason": reason},
        "worktree_lease": {"root": root, "branch": branch},
        "worktree_release": {
            "root": root, "worktree_path": worktree_path,
            "worktree_id": worktree_id, "delete_branch": delete_branch, "branch": branch,
        },
        "simulate_merge": {"root": root, "source_branch": source_branch, "target_branch": target_branch},
        "curate_dataset": {
            "root": root,
            "output_path": output_path,
            "min_receipts": min_receipts,
            "format": "jsonl" if format is None else format,
        },
        "negative_knowledge_record": {"root": root, "record": record},
        "negative_knowledge_find": {
            "root": root, "query": query,
            "limit": 100 if limit is None else limit,
        },
        "incident_decision": {
            "root": root, "fingerprint": fingerprint,
            "state_revision": state_revision,
        },
        "wait_for_event": {k: v for k, v in {"root": root, "topic": topic, "timeout": timeout, "filter": filter or filter_payload}.items() if v is not None and v != ""},
        "semaphore_acquire": {k: v for k, v in {"root": root, "name": name, "capacity": capacity, "timeout": timeout, "ttl_seconds": ttl_seconds, "purpose": purpose, "owner": owner}.items() if v is not None and v != ""},
        "semaphore_release": {k: v for k, v in {"root": root, "name": name, "lease_id": lease_id, "owner": owner}.items() if v is not None and v != ""},
        "semaphore_status": {k: v for k, v in {"root": root, "name": name}.items() if v is not None and v != ""},
        "board_item_create": {k: v for k, v in {"root": root, "title": title or name, "status": status, "priority": priority, "labels": labels, "assignee": assignee, "milestone": milestone, "linked_task_id": linked_task_id or task_id, "details": details or ({"description": description} if description else None)}.items() if v is not None and v != ""},
        "board_item_update": {k: v for k, v in {"root": root, "item_id": item_id or id, "title": title or name, "status": status, "priority": priority, "labels": labels, "assignee": assignee, "milestone": milestone, "linked_task_id": linked_task_id or task_id, "details": details or ({"description": description} if description else None)}.items() if v is not None and v != ""},
        "board_item_get": {"root": root, "item_id": item_id},
        "board_item_delete": {"root": root, "item_id": item_id},
        "board_item_list": {k: v for k, v in {"root": root, "status": status, "priority": priority, "milestone": milestone, "assignee": assignee, "limit": limit}.items() if v is not None and v != ""},
        "board_summary": {"root": root},
        "milestone_create": {k: v for k, v in {"root": root, "name": name, "target_date": target_date, "description": description}.items() if v is not None and v != ""},
        "milestone_status": {"root": root, "name": name},
        "session_briefing": {k: v for k, v in {"root": root, "session_id": session_id, "include": include}.items() if v is not None and v != ""},
    }
    if action in coord_canonical_inputs:
        canonical_inputs = coord_canonical_inputs[action]
        if action == "context_compile" and paths is not None:
            canonical_inputs["paths"] = paths
        validation_error = validate_operation_arguments(
            "local_ai_coord", action, canonical_inputs,
        )
        if validation_error is not None:
            return contract_error(validation_error, status_code=400)
    if action == "worktree_release" and not worktree_path and not worktree_id:
        return contract_error("worktree_path or worktree_id is required for action='worktree_release'", status_code=400)
    requested_root = str(root or "").strip()
    if action in {"curate_dataset", "task_budget_increase"} and not is_rooted_path(requested_root):
        return contract_error(f"explicit absolute root is required for action='{action}'", status_code=400)
    root = _client_root(root)
    if action.startswith("task_"):
        rejection = _subminimum_budget_rejection({"max_response_tokens": max_response_tokens})
        if rejection is not None:
            return rejection
    if action == "task_zombie_reap":
        reap_payload = {
            "action": "reap_expired", "auto_recover": True,
            "root": root, "task_id": task_id,
        }
        requested, _, _, budget_enabled = _response_budget(action, {
            "max_response_tokens": max_response_tokens,
            "response_profile": response_profile,
            "reuse_key": reuse_key,
            "tool": action,
        })
        if budget_enabled:
            reap_payload["response_budget_tokens"] = requested
        return _compact(CLIENT.post(
            "/api/agent-state/tasks", reap_payload, timeout=_timeout("quick")
        ), "status")
    if action == "task_cleanup_worktree":
        cleanup_payload = {
            "action": "cleanup_worktree", "task_id": task_id,
        }
        requested, _, _, budget_enabled = _response_budget(action, {
            "max_response_tokens": max_response_tokens,
            "response_profile": response_profile,
            "reuse_key": reuse_key,
            "tool": action,
        })
        if budget_enabled:
            cleanup_payload["response_budget_tokens"] = requested
        return _compact(CLIENT.post(
            "/api/agent-state/tasks", cleanup_payload, timeout=_timeout("quick")
        ), "status")
    if action in {"ask", "answer"}:
        question_payload = {
            "action": action, "root": root,
            "question_id": question_id, "task_id": task_id,
        }
        if action == "ask":
            question_payload.update(session_id=session_id, question=question)
        else:
            question_payload["answer"] = answer
        requested, _, _, budget_enabled = _response_budget(action, {
            "max_response_tokens": max_response_tokens,
            "response_profile": response_profile,
            "reuse_key": reuse_key,
            "tool": action,
        })
        if budget_enabled:
            question_payload["response_budget_tokens"] = requested
        return _compact(CLIENT.coord(**question_payload), "status", extra_fields=["question"])
    if action.startswith("task_"):
        if action == "task_checkpoint" and not checkpoint:
            checkpoint = {
                "phase": phase,
                "next_action": next_action or reason,
                "affected_paths": paths or [],
                "evidence_ids": evidence_ids or [],
                "blockers": blockers or [],
                "state_data": state_data or {},
            }
        task_kwargs: dict[str, Any] = {
            "action": action, "task_id": task_id, "contract": contract,
            "checkpoint": checkpoint, "status": status, "reason": reason,
            "root": root, "include_stale": include_stale,
        }
        if ttl_seconds is not None:
            task_kwargs["ttl_seconds"] = ttl_seconds
        if action == "task_budget_increase":
            task_kwargs = {"action": action, "root": root, "task_id": task_id,
                           "reason": reason, "budget": budget}
        if action in {
            "task_create", "task_checkpoint", "task_fail", "task_transition", "task_complete",
            "task_rollback", "task_resume", "task_heartbeat", "task_budget_increase",
        }:
            budget_options = {
                "max_response_tokens": max_response_tokens,
                "response_profile": response_profile,
                "reuse_key": reuse_key,
                "tool": action,
            }
            subminimum = _subminimum_budget_rejection(budget_options)
            if subminimum is not None:
                return subminimum
            requested, _, _, budget_enabled = _response_budget(action, budget_options)
            if budget_enabled:
                task_kwargs["response_budget_tokens"] = requested
        if action == "task_list":
            task_kwargs["query"] = query
            if status:
                task_kwargs["status"] = status
            if owner:
                task_kwargs["owner"] = owner
        if action == "task_fail":
            fail_reason = reason or error or message or "Task failed"
            task_kwargs["reason"] = fail_reason
        if action == "task_create":
            task_goal = goal or task or title or description or ""
            crit_list = acceptance_criteria if acceptance_criteria is not None else criteria
            if crit_list is None:
                crit_list = [criterion] if criterion else []
            if contract is None and (task_goal or crit_list):
                contract = {
                    "goal": task_goal,
                    "acceptance_criteria": crit_list,
                    "scope": scope or "task",
                    "non_goals": [],
                    "constraints": [],
                    "risk_profile": "normal",
                }
                task_kwargs["contract"] = contract
            elif contract is not None and isinstance(contract, dict):
                task_kwargs["contract"] = dict(contract)
            if task:
                task_kwargs["task"] = task
            if paths:
                task_kwargs["changed_paths"] = paths[:64]
        if action == "task_complete" and allow_adopt:
            task_kwargs["allow_adopt"] = True
        if action in {"task_claim", "task_adopt"}:
            return _compact(CLIENT.coord(
                action="task_claim", task_id=task_id, owner=owner, root=root,
            ), "task_memory")
        task_result = CLIENT.coord(
            **task_kwargs,
        )
        return _compact(task_result, "task_memory")
    if action.startswith("memory_"):
        if not key and name:
            key = name
        if not value and content:
            value = str(content) if not isinstance(content, str) else content
        mem_root = root if (requested_root and requested_root != ".") else _workspace
        if not repository_id and mem_root:
            from .project_config import resolve_project_context
            from .state_paths import configured_state_dir
            try:
                ctx = resolve_project_context(mem_root, configured_state_dir(load_config()))
                repository_id = getattr(ctx, "coordination_id", "")
                if not scope_id and getattr(ctx, "root", None):
                    scope_id = str(ctx.root)
            except Exception:
                pass
        mem_include_all = True if (action == "memory_find" and not requested_root and not scope) else False
        memory_kwargs = dict(
            action=action, record=record, record_id=record_id,
            target_scope=target_scope, approver=approver, key=key,
            value=value, query=query, root=mem_root, scope=scope, scope_id=scope_id,
            task_id=task_id, session_id=session_id, clone_id=clone_id,
            worktree_id=worktree_id, branch=branch, repository_id=repository_id,
        )
        if kind:
            memory_kwargs["kind"] = kind
        if mem_include_all:
            memory_kwargs["include_all_scopes"] = True
        if ttl_seconds is not None:
            memory_kwargs["ttl_seconds"] = ttl_seconds
        if confidence is not None:
            memory_kwargs["confidence"] = confidence
        return _compact(CLIENT.coord(**memory_kwargs), "task_memory")
    if action == "context_compile":
        return _context_pack_projection(CLIENT.post("/api/agent-state/context", {
            "action": "compile", "task_id": task_id,
            "token_budget": max_tokens or 4000, "root": root,
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
        }, timeout=_timeout("context")))
    if action == "record_native_receipt":
        if not task_id or not criterion or not command_id:
            return contract_error("record_native_receipt requires task_id, criterion, and command_id")
        return _compact(CLIENT.post("/api/agent-state/verification", {
            "action": "native_receipt", "root": root, "task_id": task_id,
            "criterion": criterion, "command_id": command_id,
        }, timeout=_timeout("quick")), "verify")
    if action == "verify_receipt":
        return _compact(CLIENT.post("/api/agent-state/verification", {
            "action": "receipt", "receipt": receipt, "root": root,
        }, timeout=_timeout("quick")), "verify")
    if action == "verify_completion":
        return _compact(CLIENT.post("/api/agent-state/verification", {
            "action": "completion", "task_id": task_id, "root": root,
            "repository_revision": repository_revision,
        }, timeout=_timeout("quick")), "verify")
    if action == "verify_export":
        return _compact(CLIENT.post("/api/agent-state/verification", {
            "action": "export", "task_id": task_id, "root": root,
            "format": "markdown" if format is None else format,
        }, timeout=_timeout("quick")), "verify")
    if action == "negative_knowledge_record":
        rec = dict(record) if isinstance(record, dict) else {}
        if "paths" in rec and "affected_paths" not in rec:
            rec["affected_paths"] = rec.pop("paths")
        if "description" in rec and "message" not in rec:
            rec["message"] = rec.pop("description")
        if "reason" in rec and "root_cause" not in rec:
            rec["root_cause"] = rec.pop("reason")
        if "fix" in rec and "verified_fix" not in rec:
            rec["verified_fix"] = rec.pop("fix")
        if "error_class" in rec and "operation_class" not in rec:
            rec["operation_class"] = rec.pop("error_class")
        if paths and "affected_paths" not in rec:
            rec["affected_paths"] = paths
        if reason and "root_cause" not in rec:
            rec["root_cause"] = reason
        return _compact(CLIENT.post("/api/agent-state/incidents", {
            **rec, "action": "record", "root": root,
        }, timeout=_timeout("quick")), "task_memory")
    if action == "negative_knowledge_find":
        return _compact(CLIENT.post("/api/agent-state/incidents", {
            "action": "find", "root": root,
            "query": query, "limit": 100 if limit is None else limit,
        }, timeout=_timeout("quick")), "task_memory")
    if action == "incident_decision":
        return _compact(CLIENT.coord(
            action=action, fingerprint=fingerprint, state_revision=state_revision,
            root=root,
        ), "status")
    if action == "claim":
        return _compact(CLIENT.post("/api/leases/claim_batch", {
            "owner": owner, "root": root, "paths": paths or [], "ttl_seconds": 900 if ttl_seconds is None else ttl_seconds, "purpose": purpose,
        }))
    if action == "release":
        return _compact(CLIENT.post("/api/leases/release", {"owner": owner, "lease_id": lease_id}))
    if action == "renew":
        return _compact(CLIENT.post("/api/leases/renew", {"owner": owner, "lease_id": lease_id, "ttl_seconds": 900 if ttl_seconds is None else ttl_seconds}))
    if action == "leases":
        return _compact(CLIENT.get(f"/api/leases?root={quote(root)}"))
    if action.startswith("blackboard_"):
        sub = action[len("blackboard_"):]
        payload: dict[str, Any] = {
            "action": sub,
            "root": root,
        }
        if sub != "list":
            payload["board_id"] = board_id or task_id or "default"
        if task_id:
            payload["task_id"] = task_id
        if sub in {"update", "get", "delete"}:
            payload["section"] = (section or "main") if sub == "update" else (section or None)
        if sub == "update":
            payload.update(content=content, author=author)
            if expected_version is not None:
                payload["expected_version"] = expected_version
        elif sub == "merge":
            payload["remote_sections"] = remote_sections
        return _compact(CLIENT.post(
            "/api/agent-state/blackboard", payload, timeout=_timeout("quick")
        ), "status")
    if action == "swarm_dispatch":
        return _compact(CLIENT.post("/api/agent-state/swarm/dispatch", {
            "goal": goal,
            "target_paths": [] if target_paths is None else target_paths,
            "test_command": test_command,
            "author": author,
            "root": root or ".",
        }, timeout=_timeout("quick")), "status")
    if action == "swarm_step":
        return _compact(CLIENT.post("/api/agent-state/swarm/step", {
            "swarm_id": swarm_id,
            "role": role,
            "action": swarm_action,
            "payload": {} if payload is None else payload,
            "root": root or ".",
        }, timeout=_timeout("quick")), "status")
    if action == "swarm_status":
        return _compact(CLIENT.get(f"/api/agent-state/swarm/{quote(swarm_id)}?root={quote(root)}", timeout=_timeout("quick")), "status")
    if action == "swarm_list":
        params = [f"root={quote(root)}"]
        if state:
            params.append(f"state={quote(state)}")
        return _compact(CLIENT.get(f"/api/agent-state/swarm?{'&'.join(params)}", timeout=_timeout("quick")), "status")
    if action == "swarm_cancel":
        return _compact(CLIENT.post("/api/agent-state/swarm/cancel", {"swarm_id": swarm_id, "reason": reason, "root": root or "."}, timeout=_timeout("quick")), "status")
    if action == "worktree_lease":
        return _compact(CLIENT.coord(action="worktree_lease", root=root, branch=branch or None), "status")
    if action == "worktree_release":
        return _compact(CLIENT.coord(action="worktree_release", root=root, worktree_path=worktree_path, worktree_id=worktree_id, delete_branch=delete_branch, branch=branch or None), "status")
    if action == "pubsub_publish":
        return _compact(CLIENT.coord(
            action="pubsub_publish", topic=topic, message=message,
            publisher=publisher, root=root,
        ), "status")
    if action == "pubsub_poll":
        return _compact(CLIENT.coord(
            action="pubsub_poll", topic=topic, after_seq=after_seq,
            limit=limit, after_ts=after_ts, root=root,
        ), "status")
    if action == "simulate_merge":
        return _compact(
            CLIENT.coord(
                action="simulate_merge",
                root=root,
                source_branch=source_branch,
                target_branch=target_branch,
            ),
            "general",
            extra_fields=["mergeable", "conflicts", "exit_code"],
        )
    if action == "curate_dataset":
        return _compact(CLIENT.post("/api/agent-state/tasks", {
            "action": "curate_dataset",
            "root": root,
            "output_path": output_path,
            "min_receipts": min_receipts,
            "format": "jsonl" if format is None else format,
        }, timeout=_timeout("quick")), "status")
    if action in {
        "wait_for_event", "semaphore_acquire", "semaphore_release", "semaphore_status",
        "board_item_create", "board_item_update", "board_item_get", "board_item_delete",
        "board_item_list", "board_summary", "milestone_create", "milestone_status", "session_briefing",
    }:
        item_title = (title or name) if action.startswith("board_item_") else title
        item_details = (details or ({"description": description} if description else None)) if action.startswith("board_item_") else details
        coord_kwargs = dict(
            action=action, root=root,
            name=name, item_id=item_id, title=item_title, status=status, priority=priority,
            labels=labels, assignee=assignee, milestone=milestone, linked_task_id=linked_task_id,
            details=item_details, target_date=target_date, description=description,
            capacity=capacity, timeout=timeout, ttl_seconds=ttl_seconds, purpose=purpose,
            owner=owner, lease_id=lease_id, topic=topic,
            filter=filter or filter_payload, limit=limit, include=include, session_id=session_id,
            query=query,
        )
        return _compact(CLIENT.coord(**coord_kwargs), "status")
    return _invalid_action("local_ai_coord", action, tuple(CoordAction.__args__), "Use coordination for bounded shared state; the main agent remains the owner of final integration.")


@mcp.tool()
@_instrumented_tool()
def local_ai_work(
    action: WorkAction,
    root: str = ".",
    task: str = "",
    work_id: str = "",
    task_id: str = "",
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
    id: str = "",
    goal: str = "",
    prompt: str = "",
    workspace: str = "",
) -> dict[str, Any]:
    """Whole-task local execution with durable verified handoff. See dynamic description for policy and response projection."""
    if not getattr(FEATURES, "work_orchestrator", False):
        return {"success": False, "unsupported": True, "error": "local_ai_work is disabled in configuration"}
    if id and not work_id:
        work_id = id
    if (goal or prompt) and not task:
        task = goal or prompt
    if workspace and (not root or root == "."):
        root = workspace
    if isinstance(acceptance_criteria, str):
        acceptance_criteria = [acceptance_criteria]
    if isinstance(constraints, str):
        constraints = [constraints]
    valid_actions = tuple(WorkAction.__args__)
    if not isinstance(action, str) or action not in valid_actions:
        action_label = action if isinstance(action, str) else f"<{type(action).__name__}>"
        return _invalid_action("local_ai_work", action_label, valid_actions, "Use submit for a closed task and one bounded wait/get for handoff.")
    payload: dict[str, Any] = {
        "action": action, "root": _client_root(root), "task": task, "work_id": work_id, "task_id": task_id,
        "acceptance_criteria": acceptance_criteria or [], "constraints": constraints or [], "mode": mode,
        "permissions": permissions or {}, "budget": budget or {}, "timeout_seconds": timeout_seconds, "answer": answer,
        "response_profile": response_profile, "return_fields": return_fields or [], "max_output_tokens": max_output_tokens,
        "keep_failed_workspace": keep_failed_workspace,
    }
    return _compact(CLIENT.post("/api/work-orders", payload, timeout=_timeout("long") if action in {"wait"} else _timeout("quick")), "status")


@mcp.tool()
@_instrumented_tool()
def local_ai_artifact(action: ArtifactAction = "get", artifact_id: str = "", offset: int = 0, max_chars: int = 4000, section: str = "", extra_fields: list[str] | None = None, max_response_tokens: int = 0, response_profile: str = "", reuse_key: str = "", binary: bool = False, slices: list[dict[str, int]] | None = None, path: str = "", line_start: int = 1, line_end: int = 0, start_line: int = 1, end_line: int = 0, id: str = "", file: str = "", root: str = "", workspace: str = "") -> dict[str, Any]:
    """Fetch an artifact operation defined by the shared contract. Evidence IDs start with E."""
    if not operation_enabled(FEATURES, "local_ai_artifact"):
        return {"success": False, "unsupported": True, "error": "local_ai_artifact is disabled in configuration"}
    if id and not artifact_id:
        artifact_id = id
    if file and not path:
        path = file
    is_source_slices = bool(slices and isinstance(slices, list) and len(slices) > 0 and isinstance(slices[0], dict) and ("path" in slices[0] or "file" in slices[0]))
    if action in {"get", "slice"} and (path or is_source_slices) and not artifact_id:
        action = "source"
    target_workspace = root or workspace or _workspace
    if action == "source":
        from .source_slice import read_source_slice
        eff_start = start_line if start_line > 1 else line_start
        eff_end = end_line if end_line > 0 else line_end
        if is_source_slices:
            results = []
            for item in slices[:16]:
                if not isinstance(item, dict):
                    continue
                s_path = str(item.get("path") or item.get("file") or "")
                s_start = int(item.get("start_line") or item.get("line_start") or 1)
                s_end = int(item.get("end_line") or item.get("line_end") or 0)
                s_chars = int(item.get("max_chars", 4000))
                results.append(read_source_slice(target_workspace, path=s_path, line_start=s_start, line_end=s_end, max_chars=s_chars))
            return _compact({"success": True, "slices": results, "count": len(results)}, "artifact")
        eff_chars = max(512, min(max_chars, 12000)) if max_chars else 4000
        arguments = {"path": path, "line_start": eff_start, "line_end": eff_end, "max_chars": eff_chars}
        error = validate_operation_arguments("local_ai_artifact", "source", arguments)
        if error is not None:
            return {"success": False, "error": error, "terminal": True, "retryable": False}
        return _compact(read_source_slice(target_workspace, **arguments), "artifact")
    if slices is not None:
        if action not in {"get", "slice"}:
            return {"success": False, "error": "slices are only valid for get or slice actions"}
        if not isinstance(slices, list) or not slices or len(slices) > 16:
            return {"success": False, "error": "slices must contain 1 to 16 ranges"}
        aggregate_max_chars = min(MAX_TEXT, 50_000)
        total_requested = 0
        for item in slices:
            if not isinstance(item, dict) or set(item) != {"offset", "max_chars"}:
                return {"success": False, "error": "each slice must contain only offset and max_chars"}
            item_offset, item_max_chars = item["offset"], item["max_chars"]
            if isinstance(item_offset, bool) or not isinstance(item_offset, int) or item_offset < 0:
                return {"success": False, "error": "slice offset must be a non-negative integer"}
            if isinstance(item_max_chars, bool) or not isinstance(item_max_chars, int) or not 1 <= item_max_chars <= 50_000:
                return {"success": False, "error": "slice max_chars must be between 1 and 50000"}
            total_requested += item_max_chars
            if total_requested > aggregate_max_chars:
                return {"success": False, "error": f"combined slice max_chars cannot exceed {aggregate_max_chars}"}
    validation_arguments: dict[str, Any] = {}
    if action in {"get", "slice"}:
        validation_arguments.update({
            "artifact_id": artifact_id,
            "offset": offset,
            "max_chars": max_chars,
            "section": section,
            "binary": binary,
        })
        if slices is not None:
            validation_arguments["slices"] = slices
    if extra_fields is not None:
        validation_arguments["extra_fields"] = extra_fields
    validation_error = validate_operation_arguments("local_ai_artifact", action, validation_arguments)
    if validation_error is not None:
        return {"success": False, "error": validation_error}
    if action in {"get", "slice"}:
        if not isinstance(binary, bool):
            return {"success": False, "error": "binary must be a boolean"}
        if slices is None and not binary and max_chars > min(MAX_TEXT, 50_000):
            return {"success": False, "error": f"max_chars cannot exceed the MCP text limit of {min(MAX_TEXT, 50_000)}"}
    if slices is not None:
        if section or binary or offset != 0 or max_chars != 4000:
            return {"success": False, "error": "multi-slice retrieval cannot be combined with section, binary, offset, or max_chars"}
    if action == "list":
        return _compact(CLIENT.post("/api/artifact/list", {"limit": 20}), "artifact")
    if artifact_id.startswith("E"):
        if slices is not None:
            return {"success": False, "error": "multi-slice retrieval does not support evidence IDs"}
        return _compact(CLIENT.post("/api/evidence/get", {"evidence_id": artifact_id, "verify": True}), "artifact")
    if slices is not None:
        return _compact(CLIENT.post("/api/artifact/get", {
            "artifact_id": artifact_id,
            "slices": slices,
            "binary": False,
        }), "artifact")
    result = CLIENT.post("/api/artifact/get", {
        "artifact_id": artifact_id,
        "offset": offset,
        "max_chars": max_chars,
        "section": section,
        "binary": binary,
    })
    if binary and isinstance(result, dict) and result.get("success"):
        result = {key: value for key, value in result.items() if key != "data_base64"}
        result["binary_payload"] = "available through /api/artifact/get with binary=true"
    return _compact(result, "artifact")


# Unregister tools that are disabled in current configuration so MCP clients do not receive them
_ALL_REGISTERED_TOOLS: dict[str, Any] = (
    dict(mcp._tool_manager._tools)
    if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools")
    else {}
)
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
    "local_ai_coord": _desc_coord,
    "local_ai_artifact": _desc_artifact,
    "local_ai_work": _desc_work,
}
if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools"):
    def _async_mcp_adapter(sync_fn: Any) -> Any:
        @functools.wraps(sync_fn)
        async def _call(*args: Any, **kwargs: Any) -> Any:
            cancel_event = threading.Event()
            token = CURRENT_REQUEST_CANCEL_EVENT.set(cancel_event)
            try:
                return await asyncio.to_thread(sync_fn, *args, **kwargs)
            finally:
                cancel_event.set()
                CURRENT_REQUEST_CANCEL_EVENT.reset(token)

        return _call

    # FastMCP invokes sync callables on its event loop. Keep direct Python
    # functions synchronous, but offload registered MCP callables so one
    # blocking tool cannot stall other requests on the same server.
    for _registered_tool in _ALL_REGISTERED_TOOLS.values():
        if not _registered_tool.is_async:
            _registered_tool.fn = _async_mcp_adapter(_registered_tool.fn)
            _registered_tool.is_async = True

    for _tool_name, _desc_fn in _all_desc_map.items():
        if _tool_name in _ALL_REGISTERED_TOOLS:
            description = _desc_fn()
            _ALL_REGISTERED_TOOLS[_tool_name].description = description

if hasattr(mcp, "_tool_manager") and hasattr(mcp, "_mcp_server") and mcp_types is not None:
    from local_ai_hub.json_utils import dumps as json_dumps

    # FastMCP 1.x reads `parameters` and `fn_metadata.output_schema` when listing
    # tools. Publish the feature-aware conditional input schema and shared output
    # envelope while keeping per-action output contracts in operation metadata.
    for _tool_name in _all_desc_map:
        _registered_tool = _ALL_REGISTERED_TOOLS.get(_tool_name)
        _actions = operation_actions(_tool_name, FEATURES)
        if _registered_tool is None or not _actions:
            continue
        if hasattr(_registered_tool, "parameters"):
            _input_schema = operation_tool_input_schema(_tool_name, FEATURES)
            if _tool_name == "local_ai_task":
                _input_schema.setdefault("properties", {})["request_id"] = {
                    "type": "string", "default": "",
                    "description": "Stable async-job idempotency key and request correlation ID.",
                }
                _non_async_actions = sorted(set(_actions) - {"submit", "status", "wait", "result", "cancel"})
                if _non_async_actions:
                    _input_schema.setdefault("allOf", []).append({
                        "if": {
                            "properties": {"action": {"enum": _non_async_actions}},
                            "required": ["action"],
                        },
                        "then": {"not": {"required": ["request_id"]}},
                    })
            _registered_tool.parameters = _input_schema
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

    def _mcp_task_memory_wire(value: dict[str, Any], requested: int) -> Any:
        """Fit complete adoption advice or explicitly reject its delivery."""
        canonical = _normalize_task_memory_response(_task_memory_projection(value) or value)
        original = _task_memory_original_tokens(canonical)

        def emit(payload: dict[str, Any], *, compact_error_text: bool = False,
                 minimal_error_text: bool = False) -> Any:
            payload = copy.deepcopy(payload)

            def text_payload() -> dict[str, Any]:
                if minimal_error_text:
                    return {"success": False, "error": payload["error"]}
                return ({key: item for key, item in payload.items() if key != "response_budget"}
                        if compact_error_text else payload)

            for _ in range(16):
                text = json_dumps(text_payload())
                returned = _task_memory_mcp_wire_tokens(payload, text_payload=text_payload())
                payload["response_budget"]["returned_tokens"] = returned
                text = json_dumps(text_payload())
                measured = _task_memory_mcp_wire_tokens(payload, text_payload=text_payload())
                if measured == returned and measured <= requested:
                    return [mcp_types.TextContent(type="text", text=text)], payload
            return None

        essential = _task_memory_essential_response(canonical)
        for key in ("reused", "unchanged"):
            if key in value:
                essential[key] = value[key]
        # Strip only optional task metadata. The complete memory bundle remains
        # byte-for-byte equivalent JSON in every successful candidate.
        for source in (value, essential):
            candidate = copy.deepcopy(source)
            candidate["response_budget"] = {
                "requested_tokens": requested, "original_tokens": original,
                "returned_tokens": 0, "unit": "estimated_tokens",
            }
            fitted = emit(candidate)
            if fitted is not None:
                return fitted
        rejection = {"success": False, "error": "budget_too_small", "terminal": True, "retryable": False}
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
            rejection["result_id"] = result_id(value)
        if value.get("success") is False:
            if "status_code" in value:
                rejection["status_code"] = value["status_code"]
            if "error" in value:
                rejection["source_error"] = str(value["error"])
        # Unbounded external identifiers may themselves exceed the wire quota.
        # In that case carry the existing content-addressed result identity,
        # never a shortened task ID or a successful memory-free pointer.
        compact_identity = {key: item for key, item in rejection.items() if key not in {"task_id", "context_id"}}
        compact_identity["result_id"] = result_id(value)
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
        command_failure = value.get("success") is False and (
            "execution_id" in value or value.get("exit_code") not in (None, 0)
        )
        if not command_failure:
            if value.get("next_action") == "request_larger_response_budget":
                rejection = dict(value)
                rejection["response_budget"] = {
                    "requested_tokens": requested, "returned_tokens": 0, "rejected": True,
                }
                content = [mcp_types.TextContent(type="text", text="Increase max_response_tokens.")]
                wire = {
                    "content": [item.model_dump(mode="json", exclude_none=True) for item in content],
                    "structuredContent": rejection, "isError": False,
                }
                for _ in range(16):
                    returned = json_tokens(wire)
                    rejection["response_budget"]["returned_tokens"] = returned
                    if json_tokens(wire) == returned:
                        break
                if json_tokens(wire) <= requested:
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
                                            "mutation_applied", "operation_not_started",
                                            "total_matches", "has_more", "offset", "limit",
                                            "task_context_artifact_id", "next_action")
                                if key in value and key not in dropped
                            },
                        }
                        if include_optional:
                            for key in (*_CONTEXT_PROTECTED_KEYS, "evidence", "evidence_id", "evidence_ids", "artifact_id", "artifact_ids"):
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
                                    wire = _mcp_wire_view(trial, structured=True)
                                    if text_mode == "minimal":
                                        wire["content"][0]["text"] = json_dumps({
                                            "success": False, "error": trial["error"],
                                            **{
                                                key: trial[key]
                                                for key in (
                                                    "evidence", "evidence_id", "evidence_ids",
                                                    "mutation_applied", "operation_not_started",
                                                    "total_matches", "has_more", "offset", "limit",
                                                )
                                                if key in trial
                                            },
                                            "response_budget": trial["response_budget"],
                                        })
                                    elif text_mode == "compact":
                                        wire["content"][0]["text"] = json_dumps({
                                            "success": False, "error": trial["error"],
                                            **{
                                                key: trial[key]
                                                for key in (
                                                    "status", "status_code", "terminal", "retryable",
                                                    "mutation_applied", "operation_not_started",
                                                    "request_id", "execution_id",
                                                    "evidence", "evidence_id", "evidence_ids", "artifact_id", "artifact_ids",
                                                    "total_matches", "has_more", "offset", "limit",
                                                )
                                                if key in trial
                                            },
                                            "response_budget": trial["response_budget"],
                                        })
                                    return wire

                                for _ in range(16):
                                    returned = json_tokens(wire_payload())
                                    trial["response_budget"]["returned_tokens"] = returned
                                    if json_tokens(wire_payload()) == returned:
                                        break
                                wire = wire_payload()
                                if json_tokens(wire) <= requested:
                                    return [mcp_types.TextContent(type="text", text=wire["content"][0]["text"])], trial
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
                        for key in (*_CONTEXT_PROTECTED_KEYS, "evidence_id", "evidence_ids", "artifact_id", "artifact_ids"):
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
                            returned = json_tokens(_mcp_wire_view(trial, structured=True))
                            trial["response_budget"]["returned_tokens"] = returned
                            if json_tokens(_mcp_wire_view(trial, structured=True)) == returned:
                                break
                        if json_tokens(_mcp_wire_view(trial, structured=True)) <= requested:
                            content = [mcp_types.TextContent(type="text", text=json_dumps(trial))]
                            return content, trial
        return None

    def _build_mcp_budget_payload(name: str, arguments: dict[str, Any], value: Any) -> Any:
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
        if not enabled:
            return ([mcp_types.TextContent(type="text", text=json_dumps(value))], value)

        if name == "local_ai_coord" and str(arguments.get("action") or "").startswith("task_"):
            memory_wire = _mcp_task_memory_wire(value, requested)
            if memory_wire is not None:
                return memory_wire

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
            *_RELIABILITY_PROTECTED_KEYS,
            *(_COORD_PROTECTED_KEYS if name == "local_ai_coord" else ()),
            *(_CONTEXT_PROTECTED_KEYS if action in {"context", "context_compile"} else ()),
            *(_STATUS_PROTECTED_KEYS if name == "local_ai_status" else ()),
        )
        if name == "local_ai_artifact" and action == "source":
            from .source_slice import SOURCE_SLICE_FIELDS
            protected = (*protected, *SOURCE_SLICE_FIELDS)
        if name == "local_ai_repo" and action in {"security_audit", "secret_scan"}:
            protected = (*protected, *_SECURITY_PROTECTED_KEYS)
        if name == "local_ai_repo" and action == "complexity":
            protected = (*protected, *_COMPLEXITY_PROTECTED_KEYS)
        if name == "local_ai_repo" and action == "topology":
            protected = (*protected, *_TOPOLOGY_PROTECTED_KEYS)
        original_tokens = json_tokens(_mcp_wire_view(value, structured=True))
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
                fitted = _code_index_prefix_fitting(
                    base, value, value["symbols"], requested, wire_budget=True,
                    identity={"root": arguments.get("root"), "query": arguments.get("query")},
                )
                if fitted is None or (value["symbols"] and not fitted.get("symbols")):
                    failure = {
                        "success": False, "status_code": 413, "terminal": True,
                        "retryable": False,
                        "error": "The first complete code-index symbol exceeds the configured MCP response budget.",
                    }
                    bounded = _mcp_bounded_error(failure, requested)
                    if bounded is not None:
                        return bounded
                    break
                returned = json_tokens(_mcp_wire_view(fitted, structured=True))
                fitted["response_budget"]["returned_tokens"] = returned
                fitted["response_budget"]["truncated"] = returned < original_tokens
                accounting = fitted.get("token_efficiency")
                if isinstance(accounting, dict):
                    accounting["protocol_tokens_est"] = tool_request_tokens(name, arguments) + returned
                    baseline = accounting.get("baseline_tokens_est")
                    if isinstance(baseline, int) and not isinstance(baseline, bool):
                        signed_delta = baseline - returned
                        accounting["token_savings_delta_est"] = signed_delta
                        accounting["avoided_payload_tokens_est"] = max(0, signed_delta)
                finalized = json_tokens(_mcp_wire_view(fitted, structured=True))
                if finalized == returned and finalized <= requested:
                    content = [mcp_types.TextContent(type="text", text=json_dumps(fitted))]
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
                candidate = _normalize_deterministic(account_projection(
                    value, _relation_page_with_prefix(value, value, relation_page_key, items, count),
                ))
                candidate["response_budget"] = dict(outer_metadata)
                for _ in range(16):
                    returned = json_tokens(_mcp_wire_view(candidate, structured=True))
                    candidate["response_budget"]["returned_tokens"] = returned
                    candidate["response_budget"]["truncated"] = returned < original_tokens
                    accounting = candidate.get("token_efficiency")
                    if isinstance(accounting, dict):
                        accounting["protocol_tokens_est"] = tool_request_tokens(name, arguments) + returned
                        baseline = accounting.get("baseline_tokens_est")
                        if isinstance(baseline, int) and not isinstance(baseline, bool):
                            signed_delta = baseline - returned
                            accounting["token_savings_delta_est"] = signed_delta
                            accounting["avoided_payload_tokens_est"] = max(0, signed_delta)
                    finalized = json_tokens(_mcp_wire_view(candidate, structured=True))
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
                bounded = _mcp_bounded_error(failure, requested)
                if bounded is not None:
                    return bounded
                minimal_failure = {
                    "success": False, "status_code": 413, "terminal": True,
                    "retryable": False, "error": "response budget exceeded",
                }
                return [mcp_types.TextContent(type="text", text=json_dumps(minimal_failure))], None
            else:
                content = [mcp_types.TextContent(type="text", text=json_dumps(fitted_page))]
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
                fitted = _search_prefix_fitting(
                    base, value, items, requested, wire_budget=True,
                )
                if fitted is None or (items and not fitted.get("results")):
                    failure = {
                        "success": False, "status_code": 413, "terminal": True,
                        "retryable": False,
                        "error": "The requested search page exceeds the configured MCP response budget; reduce limit.",
                        "root": value.get("root"),
                        "offset": value.get("offset", 0),
                        "limit": value.get("limit", 24),
                        "total_matches": value.get("total_matches", 0),
                        "has_more": value.get("has_more", False),
                        "results": [],
                    }
                    bounded = _mcp_bounded_error(failure, requested)
                    if bounded is not None:
                        return bounded
                    break
                returned = json_tokens(_mcp_wire_view(fitted, structured=True))
                fitted["response_budget"]["returned_tokens"] = returned
                fitted["response_budget"]["truncated"] = returned < original_tokens
                accounting = fitted.get("token_efficiency")
                if isinstance(accounting, dict):
                    accounting["protocol_tokens_est"] = tool_request_tokens(name, arguments) + returned
                    baseline = accounting.get("baseline_tokens_est")
                    if isinstance(baseline, int) and not isinstance(baseline, bool):
                        signed_delta = baseline - returned
                        accounting["token_savings_delta_est"] = signed_delta
                        accounting["avoided_payload_tokens_est"] = max(0, signed_delta)
                finalized = json_tokens(_mcp_wire_view(fitted, structured=True))
                if finalized == returned and finalized <= requested:
                    content = [mcp_types.TextContent(type="text", text=json_dumps(fitted))]
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
            if name == "local_ai_artifact" and action == "source" and isinstance(value, dict) and value.get("success") is True:
                if isinstance(candidate, dict) and candidate.get("success") is True and any(candidate.get(key) != value.get(key) for key in SOURCE_SLICE_FIELDS):
                    candidate = {
                        "success": False, "status_code": 413, "terminal": True, "retryable": False,
                        "error": "Exact source slice exceeds response budget; reduce the range or max_chars",
                    }
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

    def _mcp_budget_payload(name: str, arguments: dict[str, Any], value: Any) -> Any:
        """Project again after pagination/accounting and measure the exact wire."""
        contents, structured = _build_mcp_budget_payload(name, arguments, value)
        if not isinstance(structured, dict):
            return contents, structured
        safe = project_agent_response(structured, enabled=detailed_diagnostics_enabled(CFG))
        if safe == structured:
            return contents, structured
        try:
            mirror = len(contents) == 1 and json.loads(contents[0].text) == structured
        except (ValueError, AttributeError):
            mirror = False
        # Task-memory responses can have a short human-readable text companion.
        # Keep that companion; JSON mirrors must match the structured result.
        budget = safe.get("response_budget")
        for _ in range(16):
            if mirror:
                contents = [mcp_types.TextContent(type="text", text=json_dumps(safe))]
            wire = {
                "content": [item.model_dump(mode="json", exclude_none=True) for item in contents],
                "structuredContent": safe, "isError": False,
            }
            returned = json_tokens(wire)
            if isinstance(budget, dict):
                budget["returned_tokens"] = returned
            accounting = safe.get("token_efficiency")
            if isinstance(accounting, dict):
                accounting["protocol_tokens_est"] = tool_request_tokens(name, arguments) + returned
                baseline = accounting.get("baseline_tokens_est")
                if isinstance(baseline, int) and not isinstance(baseline, bool):
                    accounting["token_savings_delta_est"] = baseline - returned
                    accounting["avoided_payload_tokens_est"] = max(0, baseline - returned)
            if mirror:
                contents = [mcp_types.TextContent(type="text", text=json_dumps(safe))]
            wire["content"] = [item.model_dump(mode="json", exclude_none=True) for item in contents]
            if json_tokens(wire) == returned:
                break
        return contents, safe

    async def _compact_mcp_call_tool(name: str, arguments: dict[str, Any]) -> Any:
        arguments = dict(arguments)
        if (name == "local_ai_coord" and str(arguments.get("action") or "").startswith("plan_")
                and "acceptance_criteria" not in operation_contract("local_ai_coord")["actions"].get(
                    arguments.get("action"), {}).get("allowed", ())):
            # MCP hosts can append the active task's acceptance criteria to
            # every call. Keep them when the plan action explicitly accepts them.
            arguments.pop("acceptance_criteria", None)
        pending_accounting: list[dict[str, Any]] = []
        pending_token = _PENDING_MCP_ACCOUNTING.set(pending_accounting)
        call_token = _CURRENT_MCP_CALL_ARGUMENTS.set((name, dict(arguments)))

        def finalize(result: Any, *, account_unwrapped_error: bool = False) -> Any:
            if not isinstance(result, tuple) or len(result) != 2:
                return result
            contents, structured_value = result
            if structured_value is None:
                text_value = contents[0].text
                try:
                    candidate_value = json.loads(text_value)
                except Exception:
                    candidate_value = {}
                emitted_response = {"content": [{"type": "text", "text": text_value}], "structuredContent": candidate_value}
                result = (contents, candidate_value)
            else:
                candidate_value = structured_value
                if name == "local_ai_coord" and str(arguments.get("action") or "").startswith("task_"):
                    emitted_response = {
                        "content": [{"type": "text", "text": item.text} for item in contents],
                        "structuredContent": candidate_value, "isError": False,
                    }
                else:
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
            validation = validate_operation_call(name, validation_arguments, features=FEATURES)
            if validation is not None:
                status_code, error = validation
                from .operation_contracts import operation_argument_hint
                hint = operation_argument_hint(name, validation_arguments.get(selector, "")) if status_code == 400 else {}
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
                return finalize(_mcp_budget_payload(name, arguments, payload), account_unwrapped_error=True)
            try:
                tool_obj = mcp._tool_manager.get_tool(name) if hasattr(mcp, "_tool_manager") else None
                if tool_obj is None and name in _ALL_REGISTERED_TOOLS:
                    tool_obj = _ALL_REGISTERED_TOOLS[name]
                if tool_obj is not None:
                    raw = await tool_obj.run(arguments, convert_result=False)
                else:
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
            _CURRENT_MCP_CALL_ARGUMENTS.reset(call_token)
            _PENDING_MCP_ACCOUNTING.reset(pending_token)

    mcp.call_tool = _compact_mcp_call_tool
    mcp._mcp_server.call_tool(validate_input=False)(_compact_mcp_call_tool)


def main() -> None:
    """Run MCP stdio; HubClient starts the HTTP daemon when a tool needs it."""
    mcp.run()


if __name__ == "__main__":
    main()
