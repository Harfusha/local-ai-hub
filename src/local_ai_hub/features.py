"""features.py — config-aware feature detection for Local AI Hub.

FeatureSet reads the merged config once and exposes clean boolean/string
attributes that drive dynamic MCP descriptions, policy text generation, and
internal routing decisions.  Nothing here makes network calls or touches disk
beyond the already-loaded config dict.
"""
from __future__ import annotations

from typing import Any


class FeatureSet:
    """Stable, read-only snapshot of which hub features are active.

    All attributes are derived from the merged config dict that is already
    built by :func:`local_ai_hub.config.load_config` before the hub starts.
    Instantiate once at module load time and share the instance.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        ci = cfg.get("code_intelligence", {})
        srv = cfg.get("server", {})
        feat = cfg.get("features", {})
        mdl = cfg.get("models", {})
        sub = cfg.get("ollama_subagents", {})
        cmd = cfg.get("commands", {})
        coord_cfg = cfg.get("coord", cfg.get("coordination", {}))
        tok = cfg.get("token_saving", {})
        art = cfg.get("artifacts", {})
        prep = cfg.get("preprocessing", {})
        work = cfg.get("work_orchestrator", {})

        # Primary tool toggles
        self.status: bool = bool(feat.get("status", True))
        self.repo: bool = bool(feat.get("repo", True))
        self.commands: bool = bool(feat.get("commands", True)) and bool(cmd.get("enabled", True))
        self.coord: bool = bool(feat.get("coord", True)) and bool(coord_cfg.get("enabled", True))
        self.artifacts: bool = (
            bool(feat.get("artifacts", True))
            and bool(art.get("enabled", True))
            and bool(tok.get("compact_responses", True))
        )
        self.rag: bool = bool(feat.get("rag", True))
        self.ollama: bool = bool(srv.get("auto_start_ollama", True))
        llama = cfg.get("llama_cpp", {}) if isinstance(cfg.get("llama_cpp", {}), dict) else {}
        llama_mode = str(llama.get("mode", "off")).strip().lower()
        llama_models = llama.get("models", {}) if isinstance(llama.get("models", {}), dict) else {}
        hardware = cfg.get("_hardware", {}) if isinstance(cfg.get("_hardware", {}), dict) else {}
        gpus = hardware.get("gpus", []) if isinstance(hardware.get("gpus", []), list) else []
        intel_gpu = any(
            str(gpu.get("vendor", "")).lower() == "intel" or "intel" in str(gpu.get("name", "")).lower()
            for gpu in gpus if isinstance(gpu, dict)
        )
        dedicated_other = any(
            str(gpu.get("vendor", "")).lower() in {"amd", "nvidia"} and not bool(gpu.get("integrated"))
            for gpu in gpus if isinstance(gpu, dict)
        )
        self.llama_cpp: bool = bool(llama_models) and (
            llama_mode == "on" or (llama_mode == "auto" and intel_gpu and not dedicated_other)
        )
        self.tasks: bool = (
            bool(feat.get("tasks", True))
            and bool(feat.get("local_models", True))
            and (self.ollama or self.llama_cpp)
        )

        # Code-intelligence backends
        self.code_intelligence: bool = self.repo and bool(feat.get("code_intelligence", True)) and bool(ci.get("enabled", True))
        self.serena: bool = self.code_intelligence and bool(ci.get("serena_enabled", True))
        self.codegraph: bool = self.code_intelligence and bool(ci.get("codegraph_enabled", True))

        # Preprocessing & Subagents & Agent OS & Dashboard
        self.preprocessing: bool = self.repo and bool(feat.get("preprocessing", True)) and bool(prep.get("enabled", True))
        self.subagents: bool = self.tasks and bool(feat.get("subagents", True)) and bool(sub.get("enabled", True))
        self.agent_os: bool = self.coord and bool(feat.get("agent_os", True))
        self.dashboard: bool = bool(feat.get("dashboard", True)) and bool(cfg.get("monitoring", {}).get("dashboard_enabled", True))
        self.work_orchestrator: bool = self.tasks and self.commands and self.coord and bool(feat.get("work_orchestrator", True)) and bool(work.get("enabled", True))

        # Model names — used in descriptions and routing
        self.fast_model: str = str(mdl.get("fast_code", "qwen2.5-coder:1.5b"))
        self.smart_model: str = str(mdl.get("heavy_code", "qwen2.5-coder:3b"))
        self.reasoning_model: str = str(mdl.get("reasoning", "qwen2.5-coder:7b"))
        self.general_model: str = str(mdl.get("general", self.smart_model))
        self.background_model: str = str(mdl.get("background_code", "qwen2.5-coder:0.5b"))
        self.embedding_model: str = str(mdl.get("embedding", "BAAI/bge-small-en-v1.5"))
        self.reranker_model: str = str(mdl.get("reranker", "BAAI/bge-reranker-v2-m3"))

        # Named advisory subagent profiles defined in config
        profiles_cfg = sub.get("profiles", {})
        self.subagent_profiles: tuple[str, ...] = tuple(profiles_cfg.keys()) if profiles_cfg else (
            "qwen-explorer", "qwen-drafter", "qwen-critic"
        )

    # ------------------------------------------------------------------
    # Convenience predicates & collections
    # ------------------------------------------------------------------

    def has_semantic(self) -> bool:
        """True if at least one semantic backend (Serena or CodeGraph) is on."""
        return self.serena or self.codegraph

    def has_any_model(self) -> bool:
        """True if any local-model execution is possible."""
        return (self.ollama or self.llama_cpp) and bool(self.fast_model)

    @property
    def enabled_tools(self) -> list[str]:
        """List of MCP tools that are enabled in this configuration."""
        tools: list[str] = []
        if self.status:
            tools.append("local_ai_status")
        if self.repo:
            tools.append("local_ai_repo")
        if self.tasks and self.has_any_model():
            tools.append("local_ai_task")
        if self.rag:
            tools.append("local_ai_rag")
        if self.commands:
            tools.append("local_ai_command")
        if self.coord:
            tools.append("local_ai_coord")
        if self.artifacts:
            tools.append("local_ai_artifact")
        if self.work_orchestrator:
            tools.append("local_ai_work")
        return tools

    @property
    def disabled_tools(self) -> list[str]:
        """List of standard MCP tools that are disabled in this configuration."""
        all_tools = [
            "local_ai_status", "local_ai_repo", "local_ai_task", "local_ai_rag",
            "local_ai_command", "local_ai_coord", "local_ai_artifact", "local_ai_work",
        ]
        active = set(self.enabled_tools)
        return [t for t in all_tools if t not in active]

    def supported_repo_actions(self) -> list[str]:
        """Return list of valid local_ai_repo actions supported by active backends."""
        if not self.repo:
            return []
        actions = [
            "profile", "search", "map", "code_index", "deterministic", "context",
            "route", "delegate", "solve", "review_diff", "impact", "refactor_impact",
            "resolve_imports", "generate_tests", "validate_patch", "audit_dependencies",
            "ast_outline", "test_matrix", "security_audit", "git_status", "repo_state",
            "synthesize_commit", "verify", "affected_tests", "topology", "ast_refactor",
            "generate_mocks", "split_changes", "synthesize_rules", "code_invariants",
            "generate_dataset", "profile_digest", "callers", "dead_code", "secret_scan",
            "schema_inspect", "explain_query", "env_compat", "circular_dependencies",
            "generate_types", "complexity", "api_spec", "dependency_slice",
            "migration_drift", "package_audit", "structural_search", "context_budget",
            "git_diff", "git_history_search", "hotspots", "generate_tests_for_diff", "cross_repo_contract",
            "reachability_dead_code", "mutation_test", "type_stubs", "skeletonize",
        ]
        if self.serena:
            actions.append("semantic")
        if self.codegraph:
            actions.append("graph")
        if self.has_semantic():
            actions.append("intelligence")
        if self.preprocessing:
            actions.extend([
                "preprocess", "preprocess_status", "preprocess_refresh",
                "preprocess_pause", "preprocess_resume", "preprocess_cancel",
                "preprocess_unregister",
            ])
        if self.agent_os:
            actions.extend([
                "context_compile", "verify_receipt", "verify_completion",
                "call_graph_diff", "semantic_diff",
                "cross_project_graph", "cross_project_symbols", "cross_project_impact",
                "cross_repo_graph", "cross_repo_symbols", "cross_repo_impact",
            ])
        return actions

    def supported_task_actions(self) -> list[str]:
        """Return list of valid local_ai_task actions supported by active backends."""
        if not self.tasks or not self.has_any_model():
            return []
        return [
            "delegate", "reason", "continue", "review", "second_opinion", "compress",
            "route", "batch", "benchmark", "hardware_benchmark", "evaluation_record", "evaluation_report",
            "submit", "status", "wait", "result", "cancel", "candidate_create",
            "candidate_promote", "speculative_draft", "vision", "transcribe",
            "eval_suite", "prompt_eval", "eval_drift", "complete_code",
        ]

    def supported_coord_actions(self) -> list[str]:
        """Return list of valid local_ai_coord actions supported by active backends."""
        if not self.coord:
            return []
        actions = [
            "claim", "renew", "release", "leases", "memo_put", "memo_get", "memo_search", "memo_delete",
        ]
        if self.agent_os:
            actions.extend([
                "task_create", "task_get", "task_checkpoint", "task_rollback", "task_transition",
                "task_resume", "task_list", "task_complete", "task_fail", "task_heartbeat",
                "memory_record", "memory_get", "memory_find", "memory_promote", "memory_reap",
                "relation_record", "relation_find", "relation_traverse",
                "context_compile", "verify_receipt", "verify_completion",
                "negative_knowledge_record", "negative_knowledge_find", "incident_decision",
                "blackboard_update", "blackboard_get", "blackboard_list", "blackboard_delete", "blackboard_merge",
                "swarm_dispatch", "swarm_step", "swarm_status", "swarm_list", "swarm_cancel",
                "worktree_lease", "worktree_release", "pubsub_publish", "pubsub_poll", "simulate_merge",
                "curate_dataset", "task_sync", "task_zombie_reap", "task_cleanup_worktree",
            ])
        return actions

    def supported_rag_actions(self) -> list[str]:
        """Return list of valid local_ai_rag actions supported by active backends."""
        if not self.rag:
            return []
        return ["index", "search", "list", "docset_index", "docset_search", "ingest_document", "ingest_diagram"]


    def supported_command_actions(self) -> list[str]:
        """Return list of valid local_ai_command actions supported by active broker."""
        if not self.commands:
            return []
        return [
            "run", "cancel", "classify", "discover", "stats", "repair_loop", "auto_fix",
            "run_affected", "format", "lint_fix", "spawn_daemon", "daemon_status", "stop_daemon",
            "http_probe", "stash_save", "stash_restore", "record_mock", "replay_mock",
            "diff_hunk_stage", "flaky_detect", "webhook_replay",
            "mock_server", "mock_server_start", "mock_server_stop", "mock_server_status",
        ]

    def semantic_hint(self) -> str:
        """Short label for the semantic action(s) available."""
        if self.serena and self.codegraph:
            return "semantic/graph"
        if self.serena:
            return "semantic"
        if self.codegraph:
            return "graph"
        return ""

    def cheapest_path_hint(self) -> str:
        """Human-readable cheapest-first escalation path for policy text."""
        parts = ["deterministic -> code_index/search"]
        if self.has_semantic():
            parts.append(f"-> {self.semantic_hint()}")
        parts.append("-> context/solve")
        if self.rag:
            parts.append("-> RAG")
        if self.tasks and self.has_any_model():
            parts.append(f"-> {self.fast_model} last")
        return " ".join(parts)

    def trigger_map_lines(self) -> list[str]:
        """Ordered trigger-map bullet lines for GLOBAL_POLICY and skills."""
        lines: list[str] = []
        if self.status:
            lines.append("- bounded health/cache/telemetry inspection (never poll): `local_ai_status`")
        if self.repo:
            lines.append("- repository facts/files/symbols: `local_ai_repo`")
        if self.commands:
            lines.append("- tests/lint/typecheck/build: `local_ai_command`")
        if self.artifacts:
            lines.append("- exact source/evidence text: `local_ai_artifact`")
        if self.coord:
            lines.append("- shared findings or overlapping edits: `local_ai_coord`")
            if self.agent_os:
                lines.append("- non-trivial multi-step, long-running, or acceptance-criteria work: `local_ai_coord` Agent OS task contracts, checkpoints, context, and verified completion")
        if self.rag:
            lines.append("- semantic retrieval after indexed paths are insufficient: `local_ai_rag`")
        if self.tasks and self.has_any_model():
            lines.append("- bounded local generation or second opinion: `local_ai_task`")
        if self.work_orchestrator:
            lines.append("- closed whole-task delegation with verified handoff: `local_ai_work`")
        lines.extend(self.specialized_trigger_lines())
        return lines

    def specialized_trigger_lines(self) -> list[str]:
        """Feature-specific routes that are easy to miss from the compact tool names."""
        lines: list[str] = []
        if self.code_intelligence and (self.serena or self.codegraph):
            backends = []
            if self.serena:
                backends.append("Serena symbol navigation")
            if self.codegraph:
                backends.append("CodeGraph relationship/call-graph analysis")
            lines.append(
                f"- symbol or code-relationship questions: `local_ai_repo` semantic/graph actions ({'; '.join(backends)}); indexed fallback remains available"
            )
        if self.status and self.agent_os:
            lines.append("- Agent OS task and incident state: `local_ai_status(detail=\"agent_state\")`")

        task_actions = set(self.supported_task_actions())
        if "vision" in task_actions:
            lines.append("- image understanding: `local_ai_task(action=\"vision\")`")
        if "transcribe" in task_actions:
            lines.append("- audio transcription: `local_ai_task(action=\"transcribe\")`")
        if task_actions & {"benchmark", "hardware_benchmark"}:
            lines.append("- local-model or device benchmarking: `local_ai_task` benchmark actions")
        if task_actions & {"eval_suite", "prompt_eval", "eval_drift", "evaluation_record", "evaluation_report"}:
            lines.append("- model/prompt evaluation and drift checks: `local_ai_task` evaluation actions")
        if task_actions & {"candidate_create", "candidate_promote", "speculative_draft"}:
            lines.append("- model/prompt candidate and speculative-draft workflows: `local_ai_task` candidate actions")
        if task_actions & {"submit", "wait", "result", "cancel"}:
            lines.append("- durable asynchronous local jobs: `local_ai_task` submit/status/wait/result/cancel; wait once, never poll")
        if self.subagents and self.subagent_profiles:
            lines.append("- named read-only local advisory profiles: `local_ai_task(action=\"delegate\", profile=...)`")

        rag_actions = set(self.supported_rag_actions())
        if rag_actions & {"docset_index", "docset_search", "ingest_document", "ingest_diagram"}:
            lines.append("- curated knowledge sets and document/diagram ingestion: `local_ai_rag` docset and ingest actions")

        command_actions = set(self.supported_command_actions())
        if command_actions & {"repair_loop", "auto_fix", "run_affected", "format", "lint_fix"}:
            lines.append("- requested automated repair, affected-test selection, formatting, or lint fixes: `local_ai_command` specialized actions")
        if command_actions & {"mock_server", "mock_server_start", "mock_server_stop", "mock_server_status", "record_mock", "replay_mock", "flaky_detect", "webhook_replay"}:
            lines.append("- local mock, replay, and flaky-test workflows: `local_ai_command` specialized actions")

        if self.dashboard:
            lines.append("- operator-facing live dashboard: `/dashboard` on the configured Hub server; use `local_ai_status` for bounded agent-side checks")
        return lines

    def recipe_lines(self) -> list[str]:
        """Guidance recipe lines reflecting active tools."""
        lines: list[str] = []
        if self.repo:
            prep_hint = "preprocess once, " if self.preprocessing else ""
            lines.append(f"- Recipe — Explore: {prep_hint}use the cheapest repository action, fetch only required evidence slices.")
            lease_hint = " claim `local_ai_coord` leases for overlapping paths," if self.coord else ""
            lines.append(f'- Recipe — Change: gather indexed evidence, use `local_ai_repo(action="solve")` before edits,{lease_hint} then run indexed impact/review before validation.')
        if self.commands:
            lines.append("- Recipe — Validate: route repeatable commands through `local_ai_command`, reuse cached results, use `review_diff` or `security_audit` when relevant.")
        if self.agent_os:
            lines.append("- Recipe — Durable execution: create a task contract before substantial work, checkpoint phase changes, attach validation receipts, and complete only after `verify_completion` passes.")
        elif self.repo:
            lines.append("- Recipe — Validate: run validation commands natively, review changes with `review_diff` or `security_audit`.")
        if self.rag:
            lines.append("- Recipe — Retrieve: use `local_ai_rag` only after deterministic/indexed paths are exhausted.")
        lines.append("- A recipe step may be skipped when irrelevant; one bounded fallback is allowed when Hub is unavailable.")
        return lines

    def selection_guide(self) -> str:
        """Single-sentence selection guide for GLOBAL_POLICY and skills."""
        parts: list[str] = []
        if self.repo:
            parts.append("`local_ai_repo` for bounded repository facts and checks (including `review_diff` and `security_audit`)")
        if self.commands:
            parts.append("`local_ai_command` for bounded repeatable commands")
        if self.tasks and self.has_any_model():
            parts.append("`local_ai_task` for small local-model work and second opinions")
        if self.work_orchestrator:
            parts.append("`local_ai_work` for a complete bounded repository task with planning, edits, validation and handoff")
        if self.rag:
            parts.append("`local_ai_rag` only after cheaper indexed evidence")
        if self.artifacts:
            parts.append("`local_ai_artifact` for exact slices")
        if self.coord:
            parts.append("`local_ai_coord` for leases/memos and Agent OS task, memory, context, and verification workflows" if self.agent_os else "`local_ai_coord` for leases/memos")
        if not parts:
            return "Selection guide: use native agent tools."
        return "Selection guide: " + ", ".join(parts) + "."

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "FeatureSet":
        """Construct from a merged hub config dict."""
        return cls(cfg)
