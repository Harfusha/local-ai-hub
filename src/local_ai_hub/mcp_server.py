from __future__ import annotations

import atexit
import functools
import hashlib
import inspect
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Literal, TypeAlias
from urllib.parse import quote

from local_ai_hub.client import HubClient
from local_ai_hub.compact import compact_result
from local_ai_hub.projection import AgentProjector
from local_ai_hub.config import load_config
from local_ai_hub.features import FeatureSet
from local_ai_hub.ollama_subagents import OllamaSubagentCatalog
from local_ai_hub.process_utils import canonical_root, is_rooted_path
from local_ai_hub.token_accounting import account_projection, attach_accounting, finalize_tool_accounting, json_tokens, pop_accounting

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[assignment,misc]

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

try:
    CLIENT = HubClient(tenant=TENANT)
    CFG = load_config(os.environ.get("LOCAL_AI_CONFIG"))
    FEATURES = FeatureSet.from_config(CFG)
    MCP_CFG = CFG.get("mcp", {})
    PROJECTOR = AgentProjector(CFG)
    PROFILE_CATALOG = OllamaSubagentCatalog(CFG)
    MAX_TEXT = int(MCP_CFG.get("compact_max_text_chars", 1800))
    MAX_EVIDENCE = int(MCP_CFG.get("compact_max_evidence", 10))
except Exception as _init_exc:  # pragma: no cover
    import sys
    print(f"[local-ai-hub] MCP server init failed: {_init_exc}", file=sys.stderr)
    raise SystemExit(1) from _init_exc


def _timeout(kind: str) -> float:
    defaults = {"quick": 60.0, "context": 240.0, "model": 600.0, "long": 900.0}
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


mcp = FastMCP("Local AI Hub (compact)") if FastMCP is not None else _MissingMCP("Local AI Hub (compact)")


# ---------------------------------------------------------------------------
# Dynamic tool description builders — read FEATURES (from config) at import
# time so tool schemas reflect only the active backends.
# ---------------------------------------------------------------------------

def _desc_status() -> str:
    ollama_note = " ollama_online," if FEATURES.ollama else ""
    return (
        "Health/queue/token-saving status. detail: brief, cache, telemetry, full. scope: process (default) or window."
        f" Telemetry is metadata-only.{ollama_note}"
        " Do not poll status during normal repository work or while preprocessing/model startup is in progress;"
        " one bounded health check is enough before native fallback."
        " Use when: make one bounded health, cache, or telemetry check."
        " Skip when: repository evidence or task work is needed."
    )


def _desc_task() -> str:
    if not FEATURES.has_any_model():
        return (
            "Local-model worker — disabled on this installation (no Ollama runtime configured)."
            " Returns unsupported=true for all actions."
            " Use when: never (no local inference available). Skip when: always use indexed evidence only."
            " Local AI Hub does not route or manage external agents."
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
        f" Ordinary delegate/reason/review/second-opinion work uses the `{FEATURES.fast_model}` fast tier;"
        f" configured smart models are reserved for genuinely complex routes."
        f"{profile_note}"
        " Deterministic compression and repository evidence run first when sufficient."
        " Use it for one bounded local-model worker, review or second opinion after indexed evidence."
        " It is not the orchestrator for native Codex subagents; those are managed directly by Codex outside Local AI Hub."
        " Actions: delegate, reason, continue, review, second_opinion, compress, route, batch,"
        " benchmark, evaluation_record, evaluation_report, submit, status, wait, result, cancel."
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
    semantic_hint = ""
    if FEATURES.has_semantic():
        semantic_hint = f" -> {FEATURES.semantic_hint()} for relationships"
    model_hint = ""
    if FEATURES.has_any_model():
        model_hint = f" -> {FEATURES.fast_model} -> smart model"
    rag_hint = " -> RAG" if FEATURES.rag else ""
    return (
        "Primary bounded repository worker for the main agent."
        " CALL THIS BEFORE broad repository reads/searches for any non-trivial repo task. MANDATORY GATE."
        f" Use deterministic, code_index/search,{' ' + FEATURES.semantic_hint() + ',' if FEATURES.has_semantic() else ''}"
        " context and solve for bounded evidence and implementation support."
        " For implementation, diagnosis, refactoring or complex review, call `solve` after evidence and before native edits."
        f"{' When generation is needed, seed the basic `' + FEATURES.fast_model + '` fast tier before smart escalation.' if FEATURES.has_any_model() else ''}"
        " `review_diff` and `security_audit` are targeted local checks."
        f"{'  After indexed evidence, use `local_ai_task` for one bounded local-model worker/review/second opinion.' if FEATURES.has_any_model() else ''}"
        " Codex separately decides whether to use native Codex subagents;"
        " Local AI Hub does not route or manage those agents."
        " On first use of a stable absolute root call action=preprocess exactly once and continue immediately;"
        " never poll/wait/force-refresh preprocessing."
        f" Cheapest sufficient path: deterministic -> code_index/search{semantic_hint} -> context/solve{rag_hint}{model_hint} last;"
        " STOP as soon as a cheaper layer is sufficient and never fan out overlapping retrieval layers for the same question."
        " Reuse fresh evidence/artifact slices and never repeat an identical root/query/action while repo state is unchanged."
        " `in_progress` means another owner is doing identical work; retryable/429/503 means back off;"
        " degraded/stale means verify only the affected slice."
        " Always pass the stable absolute project root; never rely on MCP cwd. Never loop or increase timeouts indefinitely."
        " Use when: every non-trivial repository task needs indexed evidence or a bounded Hub operation."
        " Skip when: the task is not repository-scoped or fresh evidence already answers it and no independent Hub scope exists."
    )


def _desc_rag() -> str:
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
        " Actions: index, search, list. Index is file-incremental and query-cached."
        " Do not trigger index repeatedly for a fresh stable workspace."
        " Use when: cheaper indexed repository paths cannot answer a bounded semantic retrieval question."
        " Skip when: deterministic/indexed evidence is sufficient or Codex-owned subagent orchestration is the right owner."
    )


def _desc_command() -> str:
    agent_os_note = " Optional task_id and criterion link passing validation commands directly to evidence-backed VerificationReceipts." if FEATURES.agent_os else ""
    return (
        "Bounded command broker for the main agent. MANDATORY for repeatable test/lint/typecheck/static-analysis/build/read-only commands whenever possible."
        " Shared safe CLI broker. Actions: run, cancel, classify, discover, stats."
        f"{agent_os_note}"
        " Results are keyed by command + bounded repo state and duplicate runs coalesce across agents. Reuse fresh results."
        " If run returns in_progress=true, DO NOT start the command natively or with force; continue independent work and retry later so the owner can populate the cache."
        " cancel only stops an active matching command. force=true is exceptional recovery/admin behavior, never a retry button."
        " Use when: a repeatable test, lint, typecheck, build, analysis, or safe read-only command is needed."
        " Skip when: no command is needed or a fresh cached result already answers it."
    )


def _desc_coord() -> str:
    agent_os_note = " task_create, task_get, task_checkpoint, task_transition, task_resume, task_list, memory_record, memory_get, memory_find, memory_promote, incident_decision," if FEATURES.agent_os else ""
    return (
        "Cross-agent coordination for the main agent and bounded Hub workers. Actions: claim, release, leases, memo_put, memo_get, memo_search, memo_delete,"
        f"{agent_os_note}"
        " Claim overlapping edit paths before concurrent Hub work."
        " Search/get memos before repeating expensive investigation and store concise reusable findings after discovery."
        " Native peer subagents are coordinated by Codex rather than by this Hub tool."
        " Use when: Hub workers share edit paths, leases, or reusable findings."
        " Skip when: work is isolated and no shared Hub state or memo is involved."
    )


def _desc_work() -> str:
    return (
        "Delegate one closed repository task to Local AI Hub: plan a bounded dependency DAG, execute the smallest independently verifiable steps, "
        "apply transactional leased edits, run safe validation, verify the integrated result against the original request, and return a compact handoff. "
        "Actions: submit, status, wait, get, cancel, continue. response_profile=minimal|compact|standard|debug; return_fields selects only needed top-level fields; "
        "max_output_tokens bounds the handoff while full details remain artifact-backed. Use when: the task can be delegated as a self-contained repository outcome. "
        "Skip when: the agent must make an unresolved product decision, credentials/network are required, or only one tiny lookup is needed."
    )


def _desc_artifact() -> str:
    return (
        "Fetch one needed artifact section or exact evidence slice. Evidence IDs start with E."
        " Use when: exact source or evidence text is required after indexed discovery."
        " Skip when: no source slice is needed or the existing compact result is sufficient."
    )


TaskAction: TypeAlias = Literal[
    "delegate", "reason", "continue", "review", "second_opinion", "compress", "route", "batch",
    "benchmark", "hardware_benchmark", "evaluation_record", "evaluation_report", "submit", "status", "wait",
    "result", "cancel", "candidate_create", "candidate_promote",
]
RepoAction: TypeAlias = Literal[
    "profile", "search", "map", "code_index", "semantic", "graph", "intelligence",
    "deterministic", "context", "route", "delegate", "solve", "review_diff", "impact",
    "refactor_impact", "resolve_imports", "generate_tests", "validate_patch",
    "audit_dependencies", "ast_outline", "test_matrix", "security_audit", "git_status",
    "synthesize_commit", "verify", "preprocess", "preprocess_status", "preprocess_refresh",
    "preprocess_pause", "preprocess_resume", "preprocess_cancel", "preprocess_unregister",
    "context_compile", "verify_receipt", "verify_completion",
    "cross_project_graph", "cross_project_symbols", "cross_project_impact",
    "cross_repo_graph", "cross_repo_symbols", "cross_repo_impact",
    "call_graph_diff", "semantic_diff",
]
RagAction: TypeAlias = Literal["index", "search", "list"]
CommandAction: TypeAlias = Literal["run", "cancel", "classify", "discover", "stats", "repair_loop", "auto_fix"]
CoordAction: TypeAlias = Literal[
    "claim", "renew", "release", "leases", "memo_put", "memo_get", "memo_search", "memo_delete",
    "task_create", "task_get", "task_checkpoint", "task_transition", "task_resume", "task_list", "task_complete", "task_fail", "task_heartbeat",
    "memory_record", "memory_get", "memory_find", "memory_promote", "memory_reap",
    "context_compile", "verify_receipt", "verify_completion",
    "negative_knowledge_record", "negative_knowledge_find", "incident_decision",
    "blackboard_update", "blackboard_get", "blackboard_list", "blackboard_merge", "blackboard_delete",
    "swarm_dispatch", "swarm_step", "swarm_status",
]
StatusDetail: TypeAlias = Literal["brief", "cache", "telemetry", "full", "agent_state"]
StatusScope: TypeAlias = Literal["process", "window"]
WorkAction: TypeAlias = Literal["submit", "status", "wait", "get", "cancel", "continue"]


def _invalid_action(tool: str, action: str, valid: tuple[str, ...], guidance: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": f"Unknown {tool} action '{action}'. Valid actions: {', '.join(valid)}. {guidance}",
    }



def _compact(value: Any, task_kind: str = "general") -> Any:
    # Capture measured savings before the projector intentionally removes internal
    # token_saving/runtime fields. Private accounting metadata is stripped by the
    # instrumented MCP boundary and never enters agent context.
    raw_value = value
    value = attach_accounting(value)
    projected = PROJECTOR.project(value, AGENT_NAME, task_kind)
    compacted = compact_result(projected, max_text_chars=MAX_TEXT, max_evidence=MAX_EVIDENCE)
    return account_projection(raw_value, compacted)


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
        self._client: HubClient | None = None

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
            if self._client is None:
                self._client = HubClient(tenant=TENANT, auto_start=False)
            # batch_id prevents HubClient single-flight from coalescing two
            # numerically identical accounting batches from concurrent MCP clients.
            self._client.post(
                "/api/telemetry/tool-accounting",
                {"batch_id": f"{os.getpid()}-{time.time_ns()}", "events": events},
                timeout=0.25,
            )
        except Exception:
            # Observability is best effort and must never become a retry/backpressure
            # path for the MCP foreground request.
            return

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
        if self._client is not None:
            try:
                self._client.close()
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


def _instrumented_tool():
    def decorator(fn: Any) -> Any:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            try:
                bound = signature.bind_partial(*args, **kwargs)
                # Do not apply Python defaults: omitted optional arguments are not
                # emitted by the model and therefore must not inflate tool-call cost.
                arguments = dict(bound.arguments)
            except Exception:
                arguments = dict(kwargs)
            result = fn(*args, **kwargs)
            clean, measured = pop_accounting(result)
            try:
                event = finalize_tool_accounting(
                    tool_name=fn.__name__, arguments=arguments, response=clean, measured=measured,
                    schema_tokens_est=_tool_catalog_schema_tokens(),
                )
                event.update({"tenant": TENANT, "agent": AGENT_NAME, "created_at": time.time()})
                _ACCOUNTING_REPORTER.record(event)
            except Exception:
                pass
            return clean

        return wrapped
    return decorator


@mcp.tool()
@_instrumented_tool()
def local_ai_status(detail: StatusDetail = "brief", scope: str = "process") -> dict[str, Any]:
    """Health/queue/token-saving status. detail: brief, cache, telemetry, full, agent_state. scope: process (default) or window. Telemetry is metadata-only. Do not poll status during normal repository work or while preprocessing/model startup is in progress; one bounded health check is enough before native fallback. Use when: make one bounded health, cache, or telemetry check. Skip when: repository evidence or task work is needed."""
    if not FEATURES.status:
        return {"success": False, "unsupported": True, "error": "local_ai_status is disabled in configuration"}
    scope = scope.strip().lower()
    if scope not in {"process", "window"}:
        return {"success": False, "error": "scope must be process or window"}
    # Status stays on the foreground agent path; live/light keeps this read
    # local, bounded, and independent of a slow user-managed runtime.
    status = CLIENT.get(f"/api/live/status?light=1&scope={scope}")
    runtime_stats = status.get("runtime_stats") if isinstance(status, dict) else {}
    if not isinstance(runtime_stats, dict):
        runtime_stats = {}
    if detail == "full":
        status["capabilities"] = CLIENT.get("/api/capabilities")
        return _compact(status, "status")
    if detail == "telemetry":
        return _compact(CLIENT.get(f"/api/telemetry/report?days=30&scope={scope}"), "status")
    if detail == "agent_state":
        return _compact(CLIENT.status(detail="agent_state"), "status")
    if detail == "cache":
        return _compact({
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
        }, "status")
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
    return res


@mcp.tool()
@_instrumented_tool()
def local_ai_task(
    action: TaskAction,
    task: str = "",
    prompt: str = "",
    model: str = "",
    context: str = "",
    candidate: str = "",
    complexity: str = "auto",
    max_tokens: int = 0,
    tasks: list[dict[str, Any]] | None = None,
    delivery: str = "sync",
    latency_budget_ms: float = 0.0,
    job_action: str = "reason",
    job_id: str = "",
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
    conversation: bool = False,
    conversation_id: str = "",
    approver: str = "",
    candidate_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bounded local-model worker for the main agent. Ordinary delegate/reason/review/second-opinion work uses the fast coding tier; configured smart models are reserved for genuinely complex routes. Named advisory profiles (qwen-explorer, qwen-drafter, qwen-critic) use Local AI Hub read-only tooling directly when root is supplied. Deterministic compression and repository evidence run first when sufficient. Use it for one bounded local-model worker, review or second opinion after indexed evidence. It is not the orchestrator for native Codex subagents; those are managed directly by Codex outside Local AI Hub. Actions: delegate, reason, continue, review, second_opinion, compress, route, batch, benchmark, evaluation_record, evaluation_report, submit, status, wait, result, cancel, candidate_create, candidate_promote. delivery=sync preserves the foreground contract; async returns a durable job now; auto requires a positive latency_budget_ms and only defers after sufficient endpoint history shows p95 above it. Evaluation stores only opaque ids, booleans, and numeric metadata; it never stores prompts or source text. Async wait is bounded to 90 seconds; never poll loops. Start a short-lived conversation with conversation=true on delegate or reason, then use continue with its opaque conversation_id; conversations are sync-only and process-memory only. Use when: bounded local generation, compression, review, routing, second opinion, or named advisory subagent work is needed. Skip when: repository evidence or safe commands are sufficient without model inference, or independent peer-agent work is managed by Codex."""
    if not FEATURES.tasks or not FEATURES.has_any_model():
        return {"success": False, "unsupported": True, "error": "Local model execution is disabled (features.tasks=false or no Ollama runtime configured)"}
    action = action.strip().lower().replace("-", "_")
    if action == "continue":
        if profile:
            return {"success": False, "unsupported": True, "error": "Conversations do not support profiles"}
        if not conversation_id.strip():
            return {"success": False, "error": "conversation_id is required", "terminal": True, "retryable": False}
        return _compact(CLIENT.post("/api/conversations/continue", {
            "conversation_id": conversation_id, "task": task, "context": context,
        }, timeout=_timeout("model")), "delegate")
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
        if action not in {"delegate", "reason", "review", "second_opinion", "submit"}:
            return {"success": False, "unsupported": True, "error": "Ollama profiles support delegate, reason, review, second_opinion and submit only"}
    if conversation and action not in {"delegate", "reason"}:
        return {"success": False, "error": "Conversations support delegate, reason and continue only", "terminal": True, "retryable": False}
    if conversation and delivery.strip().lower() != "sync":
        return {"success": False, "error": "Conversations require delivery=sync", "terminal": True, "retryable": False}
    if action in {"submit", "status", "wait", "result", "cancel"}:
        return _compact(CLIENT.post("/api/async-jobs", {
            "action": action, "job_action": job_action, "job_id": job_id, "timeout_seconds": timeout_seconds,
            "task": task, "context": context, "candidate": candidate, "complexity": complexity,
            "max_tokens": max_tokens, "tasks": tasks or [], "profile": profile, "root": root, "workspace": workspace,
        }, timeout=_timeout("quick")), "status")
    if profile:
        payload = {
            "profile": profile, "task": task, "context": context, "candidate": candidate,
            "complexity": complexity, "max_tokens": max_tokens, "priority": 5,
            "root": root, "workspace": workspace or None,
        }
        endpoint = "/api/delegate/repo" if root else "/api/delegate"
        return _compact(CLIENT.post(endpoint, payload, timeout=_timeout("model")), "delegate")
    if action == "delegate":
        payload = {
            "task": task, "context": context, "complexity": complexity, "max_tokens": max_tokens or 1100,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms,
        }
        if conversation:
            payload["conversation"] = True
        return _compact(CLIENT.post("/api/delegate", payload), "delegate")
    if action == "reason":
        payload = {
            "problem": task, "context": context, "max_tokens": max_tokens or 1200,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms,
        }
        if conversation:
            payload["conversation"] = True
        return _compact(CLIENT.post("/api/reason", payload), "reason")
    if action == "review":
        return _compact(CLIENT.post("/api/review", {
            "code": context, "instructions": task or "Report actionable defects only.",
            "complexity": complexity, "max_tokens": max_tokens or 1300,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms,
        }), "review")
    if action == "second_opinion":
        return _compact(CLIENT.post("/api/second-opinion", {
            "question": task, "candidate": candidate, "context": context, "max_tokens": max_tokens or 1100,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms,
        }), "review")
    if action == "compress":
        return _compact(CLIENT.post("/api/compress", {
            "text": context, "instruction": task or "Compress while preserving facts, identifiers, numbers, errors, decisions and uncertainty.",
            "target_tokens": max_tokens or 650,
            "delivery": delivery, "latency_budget_ms": latency_budget_ms,
        }, timeout=_timeout("model")), "compress")
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
    if action == "candidate_create":
        cand = candidate_data or ({"name": task, "baseline_version": "baseline", "candidate_version": "candidate"} if not candidate else {"name": candidate, "baseline_version": "baseline", "candidate_version": "candidate"})
        return _compact(CLIENT.post("/api/agent-state/learning", {
            "action": "create_candidate", "candidate": cand,
        }, timeout=_timeout("quick")), "status")
    if action == "candidate_promote":
        return _compact(CLIENT.post("/api/agent-state/learning", {
            "action": "promote", "candidate_id": candidate or evaluation_task_id or task, "approver": approver or "user",
        }, timeout=_timeout("quick")), "status")
    return _invalid_action("local_ai_task", action, tuple(TaskAction.__args__), "Use Local AI Hub only for bounded local-model work; use Codex-owned orchestration for peer subagents.")


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
    max_tokens: int = 0,
    evidence: list[dict[str, Any]] | None = None,
    mode: str = "adaptive",
    relation: str = "",
    language: str = "auto",
    profile: str = "",
    receipt: dict[str, Any] | None = None,
    task_id: str = "",
) -> dict[str, Any]:
    """Primary bounded repository worker for the main agent. CALL THIS BEFORE broad repository reads/searches for any non-trivial repo task. MANDATORY GATE. Use deterministic, code_index/search, semantic/graph, context and solve for bounded evidence and implementation support. For implementation, diagnosis, refactoring or complex review, call solve after evidence and before native edits. When generation is needed, seed the basic fast tier before smart escalation. review_diff and security_audit are targeted local checks. After indexed evidence, use local_ai_task for one bounded local-model worker/review/second opinion. Codex separately decides whether to use native Codex subagents; Local AI Hub does not route or manage those agents. On first use of a stable absolute root call action=preprocess exactly once and continue immediately; never poll/wait/force-refresh preprocessing. Cheapest sufficient path: deterministic -> code_index/search -> semantic/graph for relationships -> context/solve -> RAG -> local model last; STOP as soon as a cheaper layer is sufficient and never fan out overlapping retrieval layers for the same question. Reuse fresh evidence/artifact slices and never repeat an identical root/query/action while repo state is unchanged. in_progress means another owner is doing identical work; retryable/429/503 means back off; degraded/stale means verify only the affected slice. Always pass the stable absolute project root; never rely on MCP cwd. Never loop or increase timeouts indefinitely. Use when: every non-trivial repository task needs indexed evidence or a bounded Hub operation. Skip when: the task is not repository-scoped or fresh evidence already answers it and no independent Hub scope exists."""
    if not FEATURES.repo:
        return {"success": False, "unsupported": True, "error": "local_ai_repo is disabled in configuration"}
    action = action.strip().lower().replace("-", "_")
    if action in {"preprocess", "preprocess_refresh", "preprocess_cancel", "preprocess_unregister"}:
        candidate = Path(root).expanduser()
        if not candidate.is_absolute():
            return {"success": False, "error": "Preprocessing requires an explicit absolute stable project root; do not use MCP process cwd"}
    else:
        root = _client_root(root)
    if action == "profile":
        return _compact(CLIENT.post("/api/repo/profile", {"root": root}, timeout=_timeout("quick")), "profile")
    if action == "search":
        return _compact(CLIENT.post("/api/search", {"root": root, "query": query or task, "top_k": 12}, timeout=_timeout("quick")), "search")
    if action == "map":
        return _compact(CLIENT.post("/api/repo/map", {"root": root, "max_symbols": 100}, timeout=_timeout("quick")), "architecture")
    if action == "code_index":
        return _compact(CLIENT.post("/api/repo/code-index", {"root": root, "query": query or task, "limit": 24}, timeout=_timeout("quick")), "architecture")
    if action in {"semantic", "graph", "intelligence"}:
        backend = "serena" if action == "semantic" else "codegraph" if action == "graph" else "auto"
        operation = relation or ("find_symbol" if backend == "serena" else "relationships" if backend == "codegraph" else "search")
        return _compact(CLIENT.post("/api/code-intelligence/query", {
            "root": root, "query": query or task, "path": path, "backend": backend, "action": operation, "limit": 24,
        }, timeout=_timeout("quick")), "architecture")
    if action == "deterministic":
        return _compact(CLIENT.post("/api/repo/deterministic", {"root": root, "query": query or task, "limit": 30}, timeout=_timeout("quick")), "context")
    if action == "context":
        return _compact(CLIENT.post("/api/context/pack", {
            "root": root, "query": query or task, "workspace": workspace or None,
            "max_tokens": max_tokens or CFG.get("token_saving", {}).get("default_repo_context_tokens", 3200),
            "mode": "full" if mode == "full" else "fast",
        }, timeout=_timeout("context")), "context")
    if action == "route":
        if not path:
            return {"success": False, "error": "path is required for repo route"}
        return _compact(CLIENT.post("/api/route", {"root": root, "path": path, "query": query or task}, timeout=_timeout("model")), "route")
    if action == "delegate":
        return _compact(CLIENT.post("/api/delegate/repo", {
            "root": root, "task": task or query, "workspace": workspace or None,
            "complexity": "auto", "context_tokens": max_tokens or 0, "max_tokens": 1200, "profile": profile,
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
            "complexity": "auto", "max_tokens": max_tokens or 1400,
        }, timeout=_timeout("model")), "review_diff")
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
    if action == "test_matrix":
        return _compact(CLIENT.post("/api/test_matrix", {"root": root}, timeout=_timeout("quick")), "architecture")
    if action == "security_audit":
        return _compact(CLIENT.post("/api/security_audit", {"root": root}, timeout=_timeout("quick")), "architecture")
    if action == "git_status":
        return _compact(CLIENT.get(f"/api/git/status?root={quote(root)}"), "status")
    if action == "synthesize_commit":
        synth_payload = {"root": root, "hint": query or task}
        if task and str(task).startswith("task-"):
            synth_payload["task_id"] = str(task)
        return _compact(CLIENT.post("/api/git/synthesize_commit", synth_payload, timeout=_timeout("quick")), "status")
    if action == "verify":
        return _compact(CLIENT.post("/api/evidence/verify", {"root": root, "evidence": evidence or []}), "verify")
    if action == "preprocess":
        return _compact(CLIENT.post("/api/preprocess", {"action": "start", "root": root}), "preprocess")
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
    return _invalid_action("local_ai_repo", action, tuple(RepoAction.__args__), "Keep work bounded in Local AI Hub; use Codex-owned orchestration for peer subagents.")


@mcp.tool()
@_instrumented_tool()
def local_ai_rag(
    action: RagAction,
    root: str = ".",
    workspace: str = "",
    query: str = "",
    top_k: int = 6,
) -> dict[str, Any]:
    """Fallback semantic retrieval after deterministic and indexed repository evidence. Use RAG only when cheaper Local AI Hub evidence is insufficient. Actions: index, search, list. Workspace is required for rag search. Use when: semantic retrieval is needed after cheaper code_index and search paths are insufficient. Skip when: deterministic manifests, symbols, or exact ripgrep search already locate the evidence."""
    if not FEATURES.rag:
        return {"success": False, "unsupported": True, "error": "RAG backend is disabled (features.rag=false in config.toml)"}
    action = action.strip().lower().replace("-", "_")
    root = _client_root(root)
    if action == "index":
        return _compact(CLIENT.post("/api/rag/index", {"root": root, "workspace": workspace or None}, timeout=_timeout("long")))
    if action == "search":
        if not workspace:
            return {"success": False, "error": "workspace is required for rag search"}
        return _compact(CLIENT.post("/api/rag/search", {
            "query": query, "workspace": workspace, "top_k": max(1, min(top_k, 12)), "use_reranker": True,
        }))
    if action == "list":
        return _compact(CLIENT.get("/api/rag/workspaces"))
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
) -> dict[str, Any]:
    """Bounded command broker for the main agent. MANDATORY for repeatable test/lint/typecheck/static-analysis/build/read-only commands whenever possible. Shared safe CLI broker. Actions: run, cancel, classify, discover, stats, repair_loop, auto_fix. Optional auto_fix=true or action=repair_loop runs autonomous self-healing test loop with safe rollback on failure. Optional task_id and criterion link passing validation commands directly to evidence-backed VerificationReceipts. Optional stream=true or stream_id streams real-time stdout/stderr lines as command.log SSE events. Results are keyed by command + bounded repo state and duplicate runs coalesce across agents. Reuse fresh results. If run returns in_progress=true, DO NOT start the command natively or with force; continue independent work and retry later so the owner can populate the cache. cancel only stops an active matching command. force=true is exceptional recovery/admin behavior, never a retry button. Use when: a repeatable test, lint, typecheck, build, analysis, or safe read-only command is needed. Skip when: no command is needed or a fresh cached result already answers it."""
    if not FEATURES.commands:
        return {"success": False, "unsupported": True, "error": "local_ai_command is disabled in configuration"}
    action = action.strip().lower().replace("-", "_")
    eff_cwd = _client_root(cwd)
    host_timeout = _timeout("long")
    configured_command_timeout = int(CFG.get("commands", {}).get("timeout_seconds", 900))
    requested_timeout = int(timeout or configured_command_timeout)
    # The command itself must finish before the MCP/HTTP caller's hard deadline so
    # there is always time to serialize the cached result instead of timing out at
    # exactly the same instant as the child process.
    effective_command_timeout = max(1, min(requested_timeout, max(1, int(host_timeout) - 30)))
    if action not in CommandAction.__args__:
        return _invalid_action("local_ai_command", action, tuple(CommandAction.__args__), "Use this broker for bounded commands; keep peer-agent orchestration in Codex.")
    return _compact(CLIENT.post("/api/command", {
        "action": action, "command": command, "cwd": eff_cwd, "root": eff_cwd,
        "timeout": effective_command_timeout, "force": force,
        "task_id": task_id, "criterion": criterion,
        "auto_fix": auto_fix, "max_attempts": max_attempts,
        "stream": stream, "stream_id": stream_id,
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
    target_scope: str = "",
    approver: str = "",
    fingerprint: dict[str, Any] | None = None,
    tool_outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cross-agent coordination for the main agent and bounded Hub workers. Actions: claim, release, leases, memo_put, memo_get, memo_search, memo_delete, task_create, task_get, task_checkpoint, task_transition, task_resume, task_list, task_complete, task_fail, task_heartbeat, memory_record, memory_get, memory_find, memory_promote, memory_reap, context_compile, verify_receipt, verify_completion, negative_knowledge_record, negative_knowledge_find, incident_decision, blackboard_update, blackboard_get, blackboard_list, blackboard_merge, blackboard_delete. Claim overlapping edit paths before concurrent Hub work. Search/get memos before repeating expensive investigation and store concise reusable findings after discovery. Native peer subagents are coordinated by Codex rather than by this Hub tool. Use when: Hub workers share edit paths, leases, or reusable findings. Skip when: work is isolated and no shared Hub state or memo is involved."""
    if not FEATURES.coord:
        return {"success": False, "unsupported": True, "error": "local_ai_coord is disabled in configuration"}
    action = action.strip().lower().replace("-", "_")
    root = _client_root(root)
    if action.startswith("task_"):
        return _compact(CLIENT.coord(
            action=action, task_id=task_id, contract=contract,
            checkpoint=checkpoint, status=status, reason=reason,
            root=root, ttl_seconds=ttl_seconds,
        ), "status")
    if action.startswith("memory_"):
        return _compact(CLIENT.coord(
            action=action, record=record, record_id=record_id,
            target_scope=target_scope, approver=approver, key=key,
            value=value, query=query, root=root, ttl_seconds=ttl_seconds,
        ), "status")
    if action == "context_compile":
        return _compact(CLIENT.post("/api/agent-state/context", {
            "action": "compile", "task_id": task_id or query or value or key,
            "token_budget": max_tokens or ttl_seconds or 4000, "root": root,
            "changed_paths": paths or [],
        }, timeout=_timeout("context")), "context")
    if action == "verify_receipt":
        return _compact(CLIENT.post("/api/agent-state/verification", {
            "action": "receipt", "receipt": checkpoint or {
                "task_id": task_id,
                "criterion": key or value or query,
                "passed": status.lower() in {"passed", "true", "1", "pass", "ok"} if status else True,
            }, "root": root,
        }, timeout=_timeout("quick")), "verify")
    if action == "verify_completion":
        return _compact(CLIENT.post("/api/agent-state/verification", {
            "action": "completion", "task_id": task_id or query or value or key, "root": root,
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
        return _compact(CLIENT.post("/api/leases/claim_batch", {
            "root": root, "paths": paths or [], "ttl_seconds": ttl_seconds or 900, "purpose": value or "agent edit",
        }))
    if action == "release":
        return _compact(CLIENT.post("/api/leases/release", {"lease_id": lease_id}))
    if action in ("renew", "lease_renew"):
        return _compact(CLIENT.post("/api/leases/renew", {"lease_id": lease_id, "ttl_seconds": ttl_seconds or 900}))
    if action == "leases":
        return _compact(CLIENT.get(f"/api/leases?root={quote(root)}"))
    if action == "memo_put":
        return _compact(CLIENT.post("/api/memory/put", {
            "root": root, "key": key, "value": value, "ttl_seconds": ttl_seconds or 604800,
        }))
    if action == "memo_get":
        return _compact(CLIENT.post("/api/memory/get", {"root": root, "key": key}))
    if action == "memo_search":
        return _compact(CLIENT.post("/api/memory/search", {"root": root, "query": query, "limit": 12}))
    if action == "memo_delete":
        return _compact(CLIENT.post("/api/memory/delete", {"root": root, "key": key}))
    if action.startswith("blackboard_"):
        sub = action[len("blackboard_"):]
        board = task_id or (key if sub in {"get", "list", "merge", "delete"} and not value else "") or "default"
        sec = key if (value and sub == "delete") else (key or target_scope or ("" if sub in {"get", "delete"} else "main"))
        content = record if record is not None else (value or query)
        author = approver or "agent"
        return _compact(CLIENT.post("/api/agent-state/blackboard", {
            "action": sub, "board_id": board, "section": sec or None,
            "content": content, "author": author,
            "remote_sections": record or {},
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
def local_ai_artifact(artifact_id: str, offset: int = 0, max_chars: int = 4000, section: str = "") -> dict[str, Any]:
    """Fetch one needed artifact section or exact evidence slice. Evidence IDs start with E. Use when: exact source or evidence text is required after indexed discovery. Skip when: no source slice is needed or the existing compact result is sufficient."""
    if not FEATURES.artifacts:
        return {"success": False, "unsupported": True, "error": "local_ai_artifact is disabled in configuration"}
    if artifact_id.startswith("E"):
        return _compact(CLIENT.post("/api/evidence/get", {"evidence_id": artifact_id, "verify": True}), "artifact")
    return _compact(CLIENT.post("/api/artifact/get", {
        "artifact_id": artifact_id, "offset": offset, "max_chars": max(512, min(max_chars, 12000)), "section": section,
    }), "artifact")


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
    for _tool_name, _desc_fn in _all_desc_map.items():
        if _tool_name in mcp._tool_manager._tools:
            mcp._tool_manager._tools[_tool_name].description = _desc_fn()


if __name__ == "__main__":
    mcp.run()
