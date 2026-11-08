"""features.py — config-aware feature detection for Local AI Hub.

FeatureSet reads the merged config once and exposes clean boolean/string
attributes that drive dynamic MCP descriptions, policy text generation, and
internal routing decisions.  Nothing here makes network calls or touches disk
beyond the already-loaded config dict.
"""
from __future__ import annotations

from typing import Any

from local_ai_hub.operation_contracts import (
    HARDWARE_PROFILE_ORDER,
    OPERATION_CONTRACTS,
    capability_definition,
    capability_minimum_profile,
    capability_profile_available,
    operation_actions,
    operation_enabled,
)


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
        clean_cfg = cfg if isinstance(cfg, dict) else {}
        def _tbl(k: str) -> dict[str, Any]:
            v = clean_cfg.get(k)
            return v if isinstance(v, dict) else {}

        ci = _tbl("code_intelligence")
        feat = _tbl("features")
        mdl = _tbl("models")
        sub = _tbl("ollama_subagents")
        cmd = _tbl("commands")
        coord_raw = clean_cfg.get("coord")
        coord_cfg = coord_raw if isinstance(coord_raw, dict) else _tbl("coordination")
        tok = _tbl("token_saving")
        art = _tbl("artifacts")
        prep = _tbl("preprocessing")
        work = _tbl("work_orchestrator")
        hardware = _tbl("hardware")
        speculative = _tbl("speculative_lint")
        mon = _tbl("monitoring")
        detected_hardware = _tbl("_hardware")

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
        self.async_jobs: bool = _tbl("async_jobs").get("enabled", False) is True
        # Startup ownership and permission to use an existing backend are
        # independent: an externally managed Ollama may already be online.
        ollama_table = _tbl("ollama")
        if "enabled" in ollama_table:
            self.ollama: bool = ollama_table["enabled"] is True
        else:
            self.ollama: bool = True
        llama = _tbl("llama_cpp")
        llama_mode = str(llama.get("mode", "off")).strip().lower()
        llama_models = llama.get("models") if isinstance(llama.get("models"), dict) else {}
        # An explicitly configured external auto route is hardware independent;
        # endpoint validity and health are checked by LlamaCppRouter at use time.
        self.llama_cpp: bool = bool(llama_models) and llama_mode in {"on", "auto"}
        self.tasks: bool = (
            bool(feat.get("tasks", True))
            and bool(feat.get("local_models", True))
            and (self.ollama or self.llama_cpp)
        )
        vision_model = mdl.get("vision", "qwen3-vl:4b")
        vision_model_is_valid = (
            type(vision_model) is str
            and bool(vision_model)
            and vision_model.strip() == vision_model
            and "\x00" not in vision_model
        )
        self.vision: bool = self.tasks and bool(feat.get("vision", True)) and vision_model_is_valid

        # Code-intelligence backends
        self.code_intelligence: bool = self.repo and bool(feat.get("code_intelligence", True)) and bool(ci.get("enabled", True))
        self.serena: bool = self.code_intelligence and bool(ci.get("serena_enabled", True))
        # Preprocessing & Subagents & Agent OS & Dashboard
        self.preprocessing: bool = self.repo and bool(feat.get("preprocessing", True)) and bool(prep.get("enabled", True))
        self.subagents: bool = self.tasks and bool(feat.get("subagents", True)) and bool(sub.get("enabled", True))
        self.agent_os: bool = self.coord and bool(feat.get("agent_os", True))
        self.dashboard: bool = bool(feat.get("dashboard", True)) and bool(mon.get("dashboard_enabled", True))
        self.work_orchestrator: bool = self.tasks and self.commands and self.coord and bool(feat.get("work_orchestrator", True)) and bool(work.get("enabled", True))
        # load_config resolves auto-detection and overrides into `_hardware`.
        # Prefer that effective profile; raw user config is a conservative
        # fallback for isolated builders and hand-authored test fixtures.
        profile = detected_hardware.get("profile", hardware.get("profile", "low"))
        self.hardware_profile: str = profile if type(profile) is str and profile in HARDWARE_PROFILE_ORDER else "low"
        self.bounded_work_tier: bool = capability_profile_available(
            self.hardware_profile, capability_minimum_profile("local_ai_work", "submit")
        )
        self.local_semantic_analysis: bool = rollout_feature_enabled(clean_cfg, "local_semantic_analysis")
        self.local_code_generation_qualified: bool = rollout_feature_enabled(clean_cfg, "local_code_generation")
        self.local_automation_qualified: bool = rollout_feature_enabled(clean_cfg, "local_automation")
        self.local_vision_qualified: bool = rollout_feature_enabled(clean_cfg, "local_vision") and self.vision
        self.local_reranking_qualified: bool = rollout_feature_enabled(clean_cfg, "local_reranking")
        self.bounded_work_qualified: bool = (
            self.bounded_work_tier
            and self.work_orchestrator
            and rollout_feature_enabled(clean_cfg, "bounded_local_work")
        )
        self.search_summaries_opt_in: bool = rollout_feature_enabled(clean_cfg, "search_summaries")
        self.search_summaries: bool = self.tasks and self.search_summaries_opt_in and capability_profile_available(
            self.hardware_profile, capability_minimum_profile("local_ai_repo", "search_summaries")
        )

        # Cost-bearing rollout capabilities start disabled. Use strict identity so
        # malformed config values cannot accidentally enable writes or persistence.
        self.enriched_search: bool = rollout_feature_enabled(cfg, "enriched_search")
        self.batch_replacement: bool = rollout_feature_enabled(cfg, "batch_replacement")
        self.diagnostic_artifacts: bool = rollout_feature_enabled(cfg, "diagnostic_artifacts")
        self.local_diagnostic_dispatch: bool = rollout_feature_enabled(cfg, "local_diagnostic_dispatch")
        self.speculative_lint: bool = bool(speculative.get("enabled", False)) if isinstance(speculative, dict) else False

        def _model_str(val: Any, default: str) -> str:
            if type(val) is not str or not val or val.strip() != val or "\x00" in val:
                return default
            return val

        # Model names — used in descriptions and routing
        self.fast_model: str = _model_str(mdl.get("fast_code"), "qwen2.5-coder:1.5b")
        self.smart_model: str = _model_str(mdl.get("heavy_code"), "qwen2.5-coder:3b")
        self.reasoning_model: str = _model_str(mdl.get("reasoning"), "qwen2.5-coder:7b")
        self.general_model: str = _model_str(mdl.get("general"), self.smart_model)
        self.background_model: str = _model_str(mdl.get("background_code"), "qwen2.5-coder:0.5b")
        self.vision_model: str = vision_model if self.vision else ""
        self.embedding_model: str = _model_str(mdl.get("embedding"), "BAAI/bge-small-en-v1.5")
        self.reranker_model: str = _model_str(mdl.get("reranker"), "BAAI/bge-reranker-v2-m3")

        # Named advisory subagent profiles defined in config
        profiles_cfg = sub.get("profiles")
        if isinstance(profiles_cfg, dict) and profiles_cfg:
            self.subagent_profiles: tuple[str, ...] = tuple(
                k
                for k in profiles_cfg.keys()
                if type(k) is str and k and k.strip() == k and "\x00" not in k
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

    def capability_status(self) -> dict[str, dict[str, Any]]:
        """Return public, configuration-only capability decisions and reasons."""
        declarations = {
            "search_summaries": ("local_ai_repo", "search_summaries", self.tasks and self.search_summaries_opt_in),
            "semantic_analysis": ("local_ai_task", "reason", self.tasks and self.local_semantic_analysis),
            "repository_review": ("local_ai_repo", "review_diff", self.repo and self.tasks and self.local_semantic_analysis),
            "cross_file_design": ("local_ai_repo", "solve", self.repo and self.tasks and self.local_semantic_analysis),
            "vision": ("local_ai_task", "vision", self.tasks and self.local_vision_qualified),
            "code_generation": ("local_ai_task", "scaffold", self.tasks and self.local_code_generation_qualified),
            "automation": ("local_ai_task", "automation", self.tasks and self.local_automation_qualified),
            "reranking": ("local_ai_rag", "rerank", self.rag and self.local_reranking_qualified),
            "bounded_local_work": ("local_ai_work", "submit", self.bounded_work_qualified),
        }
        result: dict[str, dict[str, Any]] = {}
        for capability_id, (tool, action, enabled) in declarations.items():
            minimum = capability_minimum_profile(tool, action)
            definition = capability_definition(tool, action)
            tier_ok = capability_profile_available(self.hardware_profile, minimum)
            usable = bool(enabled and tier_ok)
            reason = None if usable else (
                f"requires_{minimum}_profile" if not tier_ok else "qualification_or_feature_gate_disabled"
            )
            result[capability_id] = {
                "available": usable,
                "state": "profile_blocked" if not tier_ok else "enabled_by_operator" if enabled else "feature_disabled",
                "minimum_profile": minimum,
                "reason": reason,
                "backend": definition.get("backend", "local_model"),
                "feature_gate": definition.get("feature_gate"),
                "provider_readiness": "not_checked",
                "authority": definition.get("authority", "advisory"),
                "quality_gate": definition.get("quality_gate", "task_specific_review"),
            }
        # High tier permits discovery of bounded work only. The existing work
        # executor still enforces explicit permissions and task-quality gates.
        if result["bounded_local_work"]["available"]:
            result["bounded_local_work"]["reason"] = "task_quality_and_explicit_permissions_required"
        return result

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


    def supported_status_actions(self) -> list[str]:
        """Return status detail values from the shared operation registry."""
        return list(operation_actions("local_ai_status", self)) if operation_enabled(self, "local_ai_status") else []

    def supported_work_actions(self) -> list[str]:
        """Return work-order actions from the shared operation registry."""
        actions = list(operation_actions("local_ai_work", self)) if operation_enabled(self, "local_ai_work") else []
        if not self.bounded_work_tier:
            actions = [action for action in actions if action != "submit"]
        return actions

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
            lines.append("- compact Hub and local-model readiness check (never poll): `local_ai_status`")
        if self.repo:
            lines.append("- repository facts/files/symbols: `local_ai_repo`")
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
        task_actions = set(self.supported_task_actions())
        semantic_actions = task_actions & {"delegate", "explore", "reason", "review", "second_opinion", "compress"}
        if semantic_actions:
            action_list = "|".join(f'"{action}"' for action in (
                "delegate", "explore", "reason", "review", "second_opinion", "compress"
            ) if action in semantic_actions)
            lines.append(
                f"- tier-available semantic actions only: `local_ai_task(action={action_list})`; deterministic/indexed evidence remains authoritative"
            )
        work_actions = set(self.supported_work_actions())
        if self.work_orchestrator and "submit" in work_actions:
            lines.append("- `local_ai_work(action=\"submit\")`: high/max profile only, after task-specific quality evaluation and explicit scope/permission checks; primary agent reviews diff, tests and integration")
        elif self.work_orchestrator:
            lines.append("- `local_ai_work`: existing work status, wait, get and cancel actions only; new work submission is unavailable at this profile")
        lines.extend(self.specialized_trigger_lines())
        return lines

    def specialized_trigger_lines(self) -> list[str]:
        """Feature-specific routes that are easy to miss from the compact tool names."""
        lines: list[str] = []
        if self.repo and self.search_summaries:
            lines.append(
                "- optional, bounded local-model summary for repository search: `local_ai_repo(action=\"search\", summarize_results=true)`; exact results and pagination stay authoritative, summary is advisory and cites source paths."
            )
        if self.code_intelligence and self.serena:
            lines.append(
                "- symbol or code-relationship questions: `local_ai_repo` semantic actions (Serena symbol navigation); indexed fallback remains available"
            )
        task_actions = set(self.supported_task_actions())
        if "vision" in task_actions:
            lines.append(f"- image understanding/frontend review via `{self.vision_model}`: `local_ai_task(action=\"vision\")`")
        if "transcribe" in task_actions:
            lines.append("- audio transcription: `local_ai_task(action=\"transcribe\")`")

        if task_actions & {"submit", "wait", "result", "cancel"}:
            lines.append("- durable asynchronous local jobs: `local_ai_task` submit/status/wait/result/cancel; wait once, never poll")
        if self.subagents and self.subagent_profiles:
            lines.append("- named read-only local advisory profiles: `local_ai_task(action=\"delegate\", profile=...)`")

        rag_actions = set(self.supported_rag_actions())
        if rag_actions & {"docset_index", "docset_search", "ingest_document", "ingest_diagram"}:
            lines.append("- curated knowledge sets and document/diagram ingestion: `local_ai_rag` docset and ingest actions")

        coord_actions = set(self.supported_coord_actions())
        if coord_actions & {"swarm_dispatch", "blackboard_update", "worktree_lease"}:
            lines.append("- multi-agent swarms, shared blackboard, and isolated worktrees: `local_ai_coord` swarm, blackboard, and worktree actions")
        if coord_actions & {"semaphore_acquire", "wait_for_event"}:
            lines.append("- cross-agent resource semaphores and signal sync: `local_ai_coord(action=\"semaphore_acquire\"|\"semaphore_release\"|\"semaphore_status\"|\"wait_for_event\")`. Guard exclusive resources and await events without polling.")
        if coord_actions & {"board_item_create", "board_summary", "session_briefing"}:
            lines.append("- project board, milestones, and session briefing: `local_ai_coord(action=\"board_item_create\"|\"board_item_update\"|\"board_item_list\"|\"board_summary\"|\"milestone_create\"|\"milestone_status\"|\"session_briefing\")`. Track Kanban deliverables and query briefings.")

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
            lines.append(
                "- Recipe — Explore: on first work in a stable root, inspect project config and register with one idempotent preprocess call; use bounded indexed/source lookup for exact file or symbol facts and adaptive context when evidence is insufficient; never force-refresh or poll preprocessing."
            )
            lease_hint = " claim `local_ai_coord` leases for overlapping paths," if self.coord else ""
            contract_hint = " initialize an Agent OS contract," if self.agent_os else ""
            repo_actions = set(self.supported_repo_actions())
            analysis = '`local_ai_repo(action="solve")`' if "solve" in repo_actions else '`local_ai_repo(action="context")`'
            lines.append(f"- Recipe — Change: gather indexed evidence,{contract_hint} use {analysis} when exposed,{lease_hint} then run indexed impact/review before validation.")
        if self.repo:
            review = "`review_diff` or `security_audit`" if "review_diff" in set(self.supported_repo_actions()) else "`security_audit`"
            lines.append(f"- Recipe — Validate: run bounded repeatable commands with the host-native command tool; use {review} when relevant.")
        if self.tasks and self.has_any_model():
            available = set(self.supported_task_actions())
            semantic = [action for action in ("review", "second_opinion", "explore", "reason", "compress") if action in available]
            if semantic:
                lines.append(f"- Recipe — Semantic work: use exposed `local_ai_task` actions ({'|'.join(semantic)}) after deterministic/indexed evidence.")
        if self.agent_os:
            receipt_part = "attach explicit verification receipts; "
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
            actions = set(self.supported_repo_actions())
            review = "including `review_diff` and `security_audit`" if "review_diff" in actions else "including `security_audit`"
            parts.append(f"`local_ai_repo` for bounded repository facts and checks ({review})")
        if self.tasks and self.has_any_model():
            actions = self.supported_task_actions()
            parts.append(f"`local_ai_task` for exposed bounded local actions ({'|'.join(actions)})")
        if self.work_orchestrator and "submit" in self.supported_work_actions():
            parts.append("`local_ai_work` only for explicitly requested closed delegation with primary-agent review")
        elif self.work_orchestrator:
            parts.append("`local_ai_work` for existing work status and recovery only")
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
