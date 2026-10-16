"""features.py — config-aware feature detection for Local AI Hub.

FeatureSet reads the merged config once and exposes clean boolean/string
attributes that drive dynamic MCP descriptions, policy text generation, and
internal routing decisions.  Nothing here makes network calls or touches disk
beyond the already-loaded config dict.
"""
from __future__ import annotations

from typing import Any

from local_ai_hub.operation_contracts import OPERATION_CONTRACTS, operation_actions, operation_enabled


def rollout_feature_enabled(config: dict[str, Any], name: str) -> bool:
    """Enable a rollout capability only for an explicit TOML boolean true."""
    if not isinstance(config, dict) or isinstance(name, bool) or not isinstance(name, str):
        return False
    features = config.get("features", {})
    return isinstance(features, dict) and features.get(name) is True


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
        speculative = cfg.get("speculative_lint", {})

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
        self.vision: bool = self.tasks and bool(feat.get("vision", True)) and bool(mdl.get("vision", "qwen3-vl:4b"))

        # Code-intelligence backends
        self.code_intelligence: bool = self.repo and bool(feat.get("code_intelligence", True)) and bool(ci.get("enabled", True))
        self.serena: bool = self.code_intelligence and bool(ci.get("serena_enabled", True))
        # Preprocessing & Subagents & Agent OS & Dashboard
        self.preprocessing: bool = self.repo and bool(feat.get("preprocessing", True)) and bool(prep.get("enabled", True))
        self.subagents: bool = self.tasks and bool(feat.get("subagents", True)) and bool(sub.get("enabled", True))
        self.agent_os: bool = self.coord and bool(feat.get("agent_os", True))
        self.dashboard: bool = bool(feat.get("dashboard", True)) and bool(cfg.get("monitoring", {}).get("dashboard_enabled", True))
        self.work_orchestrator: bool = self.tasks and self.commands and self.coord and bool(feat.get("work_orchestrator", True)) and bool(work.get("enabled", True))

        # Cost-bearing rollout capabilities start disabled. Use strict identity so
        # malformed config values cannot accidentally enable writes or persistence.
        self.enriched_search: bool = rollout_feature_enabled(cfg, "enriched_search")
        self.batch_replacement: bool = rollout_feature_enabled(cfg, "batch_replacement")
        self.diagnostic_artifacts: bool = rollout_feature_enabled(cfg, "diagnostic_artifacts")
        self.local_diagnostic_dispatch: bool = rollout_feature_enabled(cfg, "local_diagnostic_dispatch")
        self.speculative_lint: bool = bool(speculative.get("enabled", False)) if isinstance(speculative, dict) else False

        def _model_str(val: Any, default: str) -> str:
            if val is None or isinstance(val, bool) or not str(val).strip():
                return default
            return str(val).strip()

        # Model names — used in descriptions and routing
        self.fast_model: str = _model_str(mdl.get("fast_code"), "qwen2.5-coder:1.5b")
        self.smart_model: str = _model_str(mdl.get("heavy_code"), "qwen2.5-coder:3b")
        self.reasoning_model: str = _model_str(mdl.get("reasoning"), "qwen2.5-coder:7b")
        self.general_model: str = _model_str(mdl.get("general"), self.smart_model)
        self.background_model: str = _model_str(mdl.get("background_code"), "qwen2.5-coder:0.5b")
        self.vision_model: str = _model_str(mdl.get("vision"), "qwen3-vl:4b") if self.vision else ""
        self.embedding_model: str = _model_str(mdl.get("embedding"), "BAAI/bge-small-en-v1.5")
        self.reranker_model: str = _model_str(mdl.get("reranker"), "BAAI/bge-reranker-v2-m3")

        # Named advisory subagent profiles defined in config
        profiles_cfg = sub.get("profiles")
        if isinstance(profiles_cfg, dict) and profiles_cfg:
            self.subagent_profiles: tuple[str, ...] = tuple(
                str(k) for k in profiles_cfg.keys() if k and not isinstance(k, bool)
            )
        elif isinstance(profiles_cfg, (list, tuple)) and profiles_cfg:
            self.subagent_profiles = tuple(
                str(k) for k in profiles_cfg if k and not isinstance(k, bool)
            )
        else:
            self.subagent_profiles = ("qwen-explorer", "qwen-drafter", "qwen-critic")

    # ------------------------------------------------------------------
    # Convenience predicates & collections
    # ------------------------------------------------------------------

    def has_semantic(self) -> bool:
        """True if semantic backend (Serena) is on."""
        return self.serena

    def has_any_model(self) -> bool:
        """True if any local-model execution is possible."""
        return (self.ollama or self.llama_cpp) and bool(self.fast_model)

    @property
    def enabled_tools(self) -> list[str]:
        """List of MCP tools that are enabled in this configuration."""
        return [tool for tool in OPERATION_CONTRACTS if operation_enabled(self, tool)]

    @property
    def disabled_tools(self) -> list[str]:
        """List of standard MCP tools that are disabled in this configuration."""
        all_tools = list(OPERATION_CONTRACTS)
        active = set(self.enabled_tools)
        return [t for t in all_tools if t not in active]

    def supported_repo_actions(self) -> list[str]:
        """Return list of valid local_ai_repo actions supported by active backends."""
        return list(operation_actions("local_ai_repo", self)) if operation_enabled(self, "local_ai_repo") else []

    def supported_task_actions(self) -> list[str]:
        """Return list of valid local_ai_task actions supported by active backends."""
        return list(operation_actions("local_ai_task", self)) if operation_enabled(self, "local_ai_task") else []

    def supported_coord_actions(self) -> list[str]:
        """Return list of valid local_ai_coord actions supported by active backends."""
        return list(operation_actions("local_ai_coord", self)) if operation_enabled(self, "local_ai_coord") else []

    def supported_rag_actions(self) -> list[str]:
        """Return list of valid local_ai_rag actions supported by active backends."""
        return list(operation_actions("local_ai_rag", self)) if operation_enabled(self, "local_ai_rag") else []


    def supported_command_actions(self) -> list[str]:
        """Return list of valid local_ai_command actions supported by active broker."""
        return list(operation_actions("local_ai_command", self)) if operation_enabled(self, "local_ai_command") else []

    def supported_status_actions(self) -> list[str]:
        """Return status detail values from the shared operation registry."""
        return list(operation_actions("local_ai_status", self)) if operation_enabled(self, "local_ai_status") else []

    def supported_work_actions(self) -> list[str]:
        """Return work-order actions from the shared operation registry."""
        return list(operation_actions("local_ai_work", self)) if operation_enabled(self, "local_ai_work") else []

    def supported_artifact_actions(self) -> list[str]:
        """Return artifact actions when their feature gate is active."""
        return list(operation_actions("local_ai_artifact", self)) if operation_enabled(self, "local_ai_artifact") else []

    def semantic_hint(self) -> str:
        """Short label for the semantic action(s) available."""
        if self.serena:
            return "semantic"
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
                lines.append("- Agent OS lifecycle (contracts, milestones, verification): `local_ai_coord(action=\"task_create\"|\"task_checkpoint\"|\"task_complete\"|\"verify_completion\")`. Default to initializing task contracts for coding, bugfixing, and refactoring tasks.")
                lines.append("- durable project memory & architecture facts: `local_ai_coord(action=\"memory_record\"|\"memory_find\")`. Actively persist and consult project facts, conventions, and user preferences.")
                lines.append("- anti-pattern & incident tracking: `local_ai_coord(action=\"negative_knowledge_record\"|\"negative_knowledge_find\")`. Record failed approaches, error classes, and root causes to avoid repeating mistakes.")
        if self.rag:
            lines.append("- semantic retrieval after indexed paths are insufficient: `local_ai_rag`")
        if self.tasks and self.has_any_model():
            lines.append('- semantic generation, exploration, reasoning, review, second opinion and compression: `local_ai_task(action="delegate"|"explore"|"reason"|"review"|"second_opinion"|"compress")`')
        if self.work_orchestrator:
            lines.append("- `local_ai_work`: only when the user explicitly requests closed delegation; routine work stays with the primary agent")
        lines.extend(self.specialized_trigger_lines())
        return lines

    def specialized_trigger_lines(self) -> list[str]:
        """Feature-specific routes that are easy to miss from the compact tool names."""
        lines: list[str] = []
        if self.code_intelligence and self.serena:
            lines.append(
                "- symbol or code-relationship questions: `local_ai_repo` semantic actions (Serena symbol navigation); indexed fallback remains available"
            )
        if self.status and self.agent_os:
            lines.append("- Agent OS task and incident state: `local_ai_status(detail=\"agent_state\")`")

        task_actions = set(self.supported_task_actions())
        if "vision" in task_actions:
            lines.append(f"- image understanding/frontend review via `{self.vision_model}`: `local_ai_task(action=\"vision\")`")
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

        coord_actions = set(self.supported_coord_actions())
        if coord_actions & {"swarm_dispatch", "blackboard_update", "worktree_lease"}:
            lines.append("- multi-agent swarms, shared blackboard, and isolated worktrees: `local_ai_coord` swarm, blackboard, and worktree actions")

        repo_actions = set(self.supported_repo_actions())
        if repo_actions & {"cross_project_graph", "cross_project_symbols", "cross_project_impact", "cross_repo_contract"}:
            lines.append("- cross-project dependencies and contracts: `local_ai_repo` cross_project and cross_repo actions")
        if repo_actions & {"security_audit", "dead_code", "secret_scan", "test_matrix"}:
            lines.append("- repository audits, dead code, secret scanning, and test matrices: `local_ai_repo(action=\"security_audit\"|\"dead_code\"|\"secret_scan\"|\"test_matrix\")`")

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
            contract_hint = " initialize an Agent OS contract," if self.agent_os else ""
            lines.append(f'- Recipe — Change: gather indexed evidence,{contract_hint} use `local_ai_repo(action="solve")` before edits,{lease_hint} then run indexed impact/review before validation.')
        if self.commands:
            receipt_note = " (pass `task_id` for receipt minting)" if self.agent_os else ""
            lines.append(f"- Recipe — Validate: route repeatable commands through `local_ai_command`{receipt_note}, reuse cached results, use `review_diff` or `security_audit` when relevant.")
        if self.tasks and self.has_any_model():
            lines.append('- Recipe — Semantic work: actively use `local_ai_task` for code review (`action="review"`), second opinion on non-trivial logic (`action="second_opinion"`), exploration (`action="explore"`), and compressing noisy test outputs (`action="compress"`).')
        if self.agent_os:
            receipt_part = "route tests via `local_ai_command(task_id=..., criterion=...)` to auto-mint receipts; " if self.commands else ""
            lines.append(f"- Recipe — Agent OS Execution (Default for Non-Trivial Tasks): Initialize a task contract via `local_ai_coord(action=\"task_create\")` with concrete acceptance criteria; query existing memory via `memory_find`; checkpoint milestones via `task_checkpoint`; persist reusable findings via `memory_record`; record failures via `negative_knowledge_record`; {receipt_part}and verify completion (`verify_completion`) before closure.")
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
            parts.append("`local_ai_task` for bounded semantic generation, exploration, reasoning, review, independent second opinions and semantic compression")
        if self.work_orchestrator:
            parts.append("`local_ai_work` only for closed delegation explicitly requested by the user")
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
