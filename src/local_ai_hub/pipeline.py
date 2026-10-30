from __future__ import annotations

from .json_utils import dumps as json_dumps

import copy
import math
from typing import Any

from . import __version__
from .cache import SQLiteCache, SingleFlightCache, TieredCache, stable_hash
from .planner import AdaptivePlanner
from .state_paths import configured_state_dir


def _safe_int(val: Any, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    if val is None or isinstance(val, bool):
        return default
    try:
        if isinstance(val, float) and not math.isfinite(val):
            return default
        res = int(val)
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res


def _safe_float(val: Any, default: float, min_val: float | None = None, max_val: float | None = None) -> float:
    if val is None or isinstance(val, bool):
        return default
    try:
        res = float(val)
        if not math.isfinite(res):
            return default
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res


def _is_repetition_loop(response: Any) -> bool:
    return isinstance(response, dict) and bool(
        response.get("repetition_loop_detected") or response.get("_lah_repetition_loop_detected")
    )


def _repetition_loop_failure(response: dict[str, Any], *, stage: str, mode: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": str(response.get("error") or "local reasoning stopped after repetitive model output"),
        "model": response.get("model"),
        "terminal": True,
        "retryable": False,
        "repetition_loop_detected": True,
        "pipeline": {"mode": mode, "degraded": True, "failed_stage": stage},
}


class LocalAgentPipeline:
    """Adaptive local explorer -> worker -> critic pipeline.

    The pipeline is deliberately bounded. It performs expensive local stages only
    when complexity/risk justifies them, and each stage is independently cached so
    repeated work from other cloud agents reuses the heavy local reasoning.
    """

    def __init__(self, config: dict[str, Any], services: Any, token_router: Any, tool_agent: Any | None = None):
        self.config = config if isinstance(config, dict) else {}
        self.services = services
        self.token_router = token_router
        self.tool_agent = tool_agent
        self.planner = AdaptivePlanner(self.config)
        cfg = self.config.get("local_pipeline", {}) if isinstance(self.config.get("local_pipeline"), dict) else {}
        self.enabled = bool(cfg.get("enabled", True))
        self.default_mode = str(cfg.get("default_mode", "adaptive"))
        self.critic_risk_score = _safe_int(cfg.get("critic_min_risk_score"), 4)
        self.critic_min_complexity_score = _safe_int(cfg.get("critic_min_complexity_score"), 3)
        self.worker_complexity_score = _safe_int(cfg.get("worker_min_complexity_score"), 2)
        self.max_explorer_tokens = _safe_int(cfg.get("explorer_max_tokens"), 650, min_val=1)
        self.max_worker_tokens = _safe_int(cfg.get("worker_max_tokens"), 1300, min_val=1)
        self.max_critic_tokens = _safe_int(cfg.get("critic_max_tokens"), 750, min_val=1)
        hw_prof = str(self.config.get("_hardware", {}).get("profile") if isinstance(self.config.get("_hardware"), dict) else (self.config.get("hardware", {}).get("profile") if isinstance(self.config.get("hardware"), dict) else "")).lower()
        default_passes = 1 if hw_prof in {"cpu", "integrated", "low"} else 2
        self.same_model_worker_passes = max(1, _safe_int(cfg.get("same_model_worker_passes"), default_passes))
        self.second_pass_min_complexity_score = _safe_int(cfg.get("second_pass_min_complexity_score"), 2)
        self.explorer_skip_worker_confidence = _safe_float(cfg.get("explorer_skip_worker_confidence"), 0.90, min_val=0.0, max_val=1.0)
        self.direct_smart_enabled = bool(cfg.get("direct_smart_enabled", "direct_smart_complexity_score" in cfg or "direct_smart_risk_score" in cfg))
        self.direct_smart_complexity_score = _safe_int(cfg.get("direct_smart_complexity_score"), 99)
        self.direct_smart_risk_score = _safe_int(cfg.get("direct_smart_risk_score"), 99)
        default_max_chars = self.config.get("token_saving", {}).get("max_inline_chars", 3600) if isinstance(self.config.get("token_saving"), dict) else 3600
        self.max_final_chars = _safe_int(cfg.get("max_final_chars"), _safe_int(default_max_chars, 3600))
        self.refine_runs = 0
        self.execution_policy_fp = stable_hash(self.config.get("model_execution", {}) if isinstance(self.config.get("model_execution"), dict) else {})
        state_dir = configured_state_dir(self.config)
        l2 = SQLiteCache(state_dir / "cache.sqlite", "pipeline-stage", _safe_int(cfg.get("ttl_seconds"), 604800), _safe_int(cfg.get("max_entries"), 12000))
        resilience_cfg = self.config.get("resilience", {}) if isinstance(self.config.get("resilience"), dict) else {}
        wait_timeout = _safe_float(resilience_cfg.get("singleflight_wait_timeout_seconds"), 45.0)
        self.cache = SingleFlightCache(TieredCache(l2, _safe_int(cfg.get("l1_entries"), 256), _safe_int(cfg.get("l1_ttl_seconds"), 1800)), wait_timeout_seconds=wait_timeout)
        self.runs = 0
        self.critic_runs = 0
        self.worker_runs = 0

    def _stage(self, key_payload: dict[str, Any], compute: Any) -> dict[str, Any]:
        from .client import CURRENT_REQUEST_CANCEL_EVENT
        cancel_event = CURRENT_REQUEST_CANCEL_EVENT.get()
        key = stable_hash(key_payload)
        def _wrapped_compute() -> dict[str, Any]:
            res = compute()
            if isinstance(res, dict):
                if not res.get("success", True):
                    res["_cacheable"] = False
                return res
            return {"success": False, "result": res, "_cacheable": False}

        if cancel_event is not None:
            result = ({"success": False, "cancelled": True, "reason": "cancelled"}
                      if cancel_event.is_set() else _wrapped_compute())
            hit, coalesced = False, False
            if cancel_event.is_set():
                result = {"success": False, "cancelled": True, "reason": "cancelled"}
        else:
            result, hit, coalesced = self.cache.get_or_compute(key, _wrapped_compute)
        out = copy.deepcopy(result) if isinstance(result, dict) else {"success": False, "result": result}
        out["stage_cache_hit"] = bool(hit)
        out["stage_coalesced"] = bool(coalesced)
        return out

    @staticmethod
    def _risk_score(impact: dict[str, Any] | None) -> int:
        if not isinstance(impact, dict):
            return 0
        risk = impact.get("risk", {})
        try:
            return int(risk.get("score", 0))
        except Exception:
            return 0

    @staticmethod
    def _select_worker_model(
        route: dict[str, Any] | None, mode: str, risk_score: int,
        direct_smart_risk_score: int, fast_model: str, heavy_model: str,
    ) -> str:
        """Keep ordinary repository workers on Qwen 2.5; escalate intentionally."""
        route_dict = route if isinstance(route, dict) else {}
        complexity_score = _safe_int(route_dict.get("complexity_score"), 0)
        smart_required = (
            mode == "quality"
            or route_dict.get("complexity") == "heavy"
            or complexity_score >= 3
            or risk_score >= direct_smart_risk_score
        )
        return heavy_model if smart_required else fast_model

    def solve_repo(self, args: dict[str, Any]) -> dict[str, Any]:
        from .client import CURRENT_REQUEST_CANCEL_EVENT
        cancel_event = CURRENT_REQUEST_CANCEL_EVENT.get()
        def cancelled() -> bool:
            return cancel_event is not None and cancel_event.is_set()
        def cancelled_result() -> dict[str, Any]:
            return {"success": False, "cancelled": True, "reason": "cancelled"}
        if cancelled():
            return cancelled_result()
        from .repository_scope import RepositoryScopeError, authorized_repository_root, reject_retired_tenancy_fields

        try:
            reject_retired_tenancy_fields(args)
            root = authorized_repository_root(self.services.config, args.get("root"))
        except RepositoryScopeError as exc:
            return {"success": False, "error": str(exc), "error_code": exc.code, "terminal": True, "retryable": False}
        if not self.enabled:
            return self.services.delegate_repo(args)
        self.runs += 1
        task = args.get("task", "")
        if not isinstance(task, str) or not task.strip():
            return {"success": False, "error": "task must be a nonempty string", "terminal": True, "retryable": False}
        task = task.strip()
        mode = args.get("mode", self.default_mode)
        if not isinstance(mode, str) or mode not in {"fast", "adaptive", "quality"}:
            return {"success": False, "error": "mode must be fast, adaptive or quality", "terminal": True, "retryable": False}

        route = self.services.router.classify(task, "", str(args.get("task_type", "auto") if isinstance(args, dict) else "auto"), str(args.get("complexity", "auto") if isinstance(args, dict) else "auto"))
        deterministic = self.services.deterministic_query(root, task, 30) if getattr(self.services, "deterministic", None) is not None else {"success": False, "confidence": 0.0}
        # Local AI fast path: pure lookup/discovery questions can be answered from parsed facts
        # and exact evidence without any RAG, reranker, embeddings or Ollama inference.
        if mode != "quality" and deterministic.get("success") and deterministic.get("direct_answer") and not route.get("semantic_required", False):
            text = self.services.deterministic.render_answer(deterministic)
            return {
                "success": True, "text": text,
                "canonical": {"task": task, "route": route, "deterministic": deterministic},
                "repo_context": {"root": deterministic.get("root", root), "evidence": deterministic.get("evidence", []), "local_context_tokens": 0, "semantic_used": False},
                "pipeline": {"mode": mode, "degraded": False, "stages": ["deterministic-script"], "confidence": deterministic.get("confidence"), "ollama_calls": 0},
            }
        low_task = task.lower()
        mutation_terms = set(self.config.get("local_pipeline", {}).get("mutation_terms", [
            "fix", "implement", "change", "modify", "refactor", "review diff", "regression", "patch", "rewrite", "add", "remove", "update"
        ]))
        needs_impact = route.get("task_type") in {"review", "patch"} or deterministic.get("intent") == "implementation" or any(
            token in low_task for token in mutation_terms
        ) or bool(args.get("staged", False) if isinstance(args, dict) else False)
        impact = self.services.repo_impact(root, str(args.get("base", "HEAD") if isinstance(args, dict) else "HEAD"), bool(args.get("staged", False) if isinstance(args, dict) else False)) if needs_impact else {
            "success": True, "changed_files": [], "suggested_tests": [], "risk": {"score": 0, "level": "low", "reasons": ["impact scan skipped for non-change task"]}
        }
        risk_score = self._risk_score(impact)
        graph = self.services.code_query(root, task, 24) if getattr(self.services, "code_index", None) is not None else {"success": False, "confidence": 0.0}
        graph_for_plan = dict(graph) if isinstance(graph, dict) else {}
        graph_for_plan["confidence"] = max(float(graph_for_plan.get("confidence", 0.0) or 0.0), float(deterministic.get("confidence", 0.0) or 0.0) * 0.92)
        det_ev = deterministic.get("evidence") if isinstance(deterministic, dict) else None
        det_ev_count = len(det_ev) if isinstance(det_ev, (list, tuple)) else 0
        preliminary = self.planner.plan(route, risk_score, graph_for_plan, det_ev_count, mode)
        workflow = self.config.get("workflow", {})
        high_conf_threshold = float(workflow.get("high_confidence_threshold", 0.90))
        budget = int(args.get("context_tokens", 0) or 0)
        if not budget:
            # Minimum-sufficient-context: deterministic graph confidence shrinks retrieval before any LLM call.
            if float(preliminary.get("confidence", 0)) >= high_conf_threshold:
                budget = int(workflow.get("direct_repo_context_tokens", 900))
            elif route.get("complexity") == "heavy":
                budget = int(workflow.get("heavy_repo_context_tokens", 4200))
            else:
                budget = int(workflow.get("fast_repo_context_tokens", 2200))
        det_cfg = self.config.get("deterministic", {})
        det_context_threshold = float(det_cfg.get("context_confidence", 0.80))
        use_det_context = (
            getattr(self.services, "deterministic", None) is not None
            and deterministic.get("success")
            and float(deterministic.get("confidence", 0.0) or 0.0) >= det_context_threshold
            and (deterministic.get("evidence") or deterministic.get("dependencies") or deterministic.get("scripts") or deterministic.get("facts") or deterministic.get("code_index"))
        )
        if use_det_context:
            packed = self.services.deterministic.context_pack(
                root, task,
                max_chars=int(det_cfg.get("context_max_chars", 5200)),
                max_raw_evidence=int(det_cfg.get("context_raw_evidence", 5)),
            )
            packed["context_source"] = "deterministic"
        else:
            packed = self.services._hybrid_context(root, task, workspace=args.get("workspace"), max_tokens=budget)
            if isinstance(packed, dict): packed["context_source"] = "hybrid"
        if not packed.get("success"):
            return packed
        packed_ev = packed.get("evidence") if isinstance(packed, dict) else None
        packed_ev_count = len(packed_ev) if isinstance(packed_ev, (list, tuple)) else 0
        plan = self.planner.plan(route, risk_score, graph_for_plan, packed_ev_count + det_ev_count, mode)
        # Local AI: if smart execution is inevitable, do not pay a fast-tier scout + model swap first.
        # Deterministic facts/search still run, so the smart worker receives scoped evidence.
        direct_smart = self.direct_smart_enabled and bool(plan.get("worker")) and self.config.get("models", {}).get("heavy_code") != self.config.get("models", {}).get("fast_code") and (
            mode == "quality"
            or risk_score >= self.direct_smart_risk_score
            or route.get("complexity") == "heavy"
            or int(route.get("complexity_score", 0) or 0) >= self.direct_smart_complexity_score
        )
        if direct_smart and plan.get("explorer"):
            plan = dict(plan)
            plan["explorer"] = False
            plan["reason"] = "direct-smart-no-redundant-scout"
        if not any(plan.get(x) for x in ("explorer", "worker", "critic")) and not deterministic.get("requires_synthesis", True):
            return {
                "success": True,
                "text": self.services.deterministic.render_answer(deterministic) if getattr(self.services, "deterministic", None) is not None else "Deterministic repository evidence is sufficient; no local LLM inference required.",
                "canonical": {"task": task, "route": route, "risk": impact.get("risk", {}), "plan": plan, "code_index": graph, "deterministic": deterministic},
                "repo_context": {"root": packed.get("root"), "evidence": packed.get("evidence", []), "local_context_tokens": packed.get("estimated_tokens", 0), "semantic_used": packed.get("semantic_used", False), "context_source": packed.get("context_source", "hybrid")},
                "pipeline": {"mode": mode, "degraded": False, "stages": ["deterministic"], "confidence": plan.get("confidence")},
            }

        if deterministic.get("requires_synthesis", False) and not any(plan.get(x) for x in ("explorer", "worker", "critic")):
            plan = dict(plan); plan["explorer"] = True; plan["reason"] = "deterministic-facts-need-synthesis"
        context_fp = stable_hash({"root": packed.get("root"), "evidence": packed.get("evidence"), "context": packed.get("context"), "deterministic": deterministic})
        # Stage caches need the exact assembled context. Semantic reuse only needs a
        # safe repository snapshot, otherwise minor ranking/order changes make every
        # paraphrase a miss. Degraded or stale repository state keeps the stricter
        # full-context scope to avoid reusing an answer across an unknown edit.
        semantic_context_fp = context_fp
        try:
            repo_state = self.services._repo_cache_state(root) or {}
            revision = str(repo_state.get("fingerprint") or "")
            if revision and not repo_state.get("stale") and not repo_state.get("degraded"):
                semantic_context_fp = stable_hash({"root": packed.get("root"), "revision": revision})
        except Exception:
            pass
        fast_model = str(self.config.get("models", {}).get("fast_code", "qwen2.5-coder:1.5b"))
        heavy_model = str(self.config.get("models", {}).get("heavy_code", fast_model))
        reasoning_model = str(self.config.get("models", {}).get("reasoning", heavy_model))

        if bool(plan.get("explorer")):
            explorer = self._stage(
                {"app_version": __version__, "execution": self.execution_policy_fp, "role": "explorer", "task": task, "context": context_fp, "model": fast_model},
                lambda: (
                    self.tool_agent.run(
                        fast_model, "explorer", task, root,
                        max_tokens=self.max_explorer_tokens, priority=7, workspace=args.get("workspace"),
                        seed_context=str(packed.get("context", "")),
                        bootstrap={"deterministic": deterministic, "code_index": graph},
                        system_suffix="Return compact JSON when possible: hypotheses[{claim,confidence,evidence_ids}], candidate_files, missing_evidence. Identify only the minimum relevant surface.",
                    ) if self.tool_agent is not None else
                    self.services._generate(
                        fast_model,
                        f"TASK:\n{task}\n\nREPO EVIDENCE:\n{packed.get('context','')}",
                        "You are a read-only repository explorer. Terse technical output only: zero conversational filler, pleasantries, or preamble. Identify the minimum relevant symbols/files, likely root cause or change points, and missing evidence. Return a concise flat list of at most 5 items. Never nest bullet points, never repeat section headers or categories, and do not quote large evidence blocks. Never invent unseen repository facts.",
                        self.max_explorer_tokens, 0.05, source="pipeline:explorer", priority=7,
                        semantic_query=task, semantic_context_fingerprint=semantic_context_fp, internal=True,
                    )
                ),
            )
        else:
            ev_list = packed.get("evidence") if isinstance(packed, dict) else None
            ev_items = ev_list if isinstance(ev_list, (list, tuple)) else []
            explorer = {
                "success": True, "model": "deterministic", "text": "", "stage_cache_hit": True,
                "structured": {"role": "explorer", "summary": "deterministic evidence/graph sufficient for exploration", "confidence": plan.get("confidence"), "evidence_ids": [str(x.get("evidence_id")) for x in ev_items if isinstance(x, dict) and x.get("evidence_id")][:10], "candidate_files": [str(x.get("path")) for x in ev_items if isinstance(x, dict) and x.get("path")][:12], "missing_evidence": []},
            }
        if cancelled():
            return cancelled_result()
        if bool(plan.get("explorer")) and not explorer.get("success") and self.tool_agent is not None and not _is_repetition_loop(explorer):
            # Tool-calling support varies by local model/template. Retry the exact same
            # bounded stage without tools before degrading the whole pipeline.
            explorer = self.services._generate(
                fast_model,
                f"TASK:\n{task}\n\nREPO EVIDENCE:\n{packed.get('context','')}",
                "You are a read-only repository explorer. Terse technical output only: zero conversational filler, pleasantries, or preamble. Identify the minimum relevant symbols/files, likely root cause or change points, and missing evidence. Return a concise flat list of at most 5 items. Never nest bullet points, never repeat section headers or categories, and do not quote large evidence blocks. Never invent unseen repository facts.",
                self.max_explorer_tokens, 0.05, source="pipeline:explorer-fallback", priority=7,
                semantic_query=task, semantic_context_fingerprint=semantic_context_fp, internal=True,
            )
        if cancelled():
            return cancelled_result()
        if not explorer.get("success"):
            if _is_repetition_loop(explorer):
                return _repetition_loop_failure(explorer, stage="explorer", mode=mode)
            # A failed explorer must not make the entire repo tool unusable; return the
            # single-model path which has its own runtime recovery/fallbacks.
            fallback = self.services.delegate_repo(args)
            fallback["pipeline"] = {"mode": mode, "degraded": True, "failed_stage": "explorer"}
            return fallback

        need_worker = bool(plan.get("worker"))
        # A successful fast-tier scout can terminate an adaptive low-risk task. This makes
        # escalation evidence-driven rather than a fixed fast-to-smart chain.
        if need_worker and bool(plan.get("explorer")) and mode == "adaptive" and risk_score < self.direct_smart_risk_score and route.get("task_type") != "review":
            structured = explorer.get("structured") if isinstance(explorer.get("structured"), dict) else {}
            try:
                explorer_confidence = float(structured.get("confidence", 0.0) or 0.0)
            except Exception:
                explorer_confidence = 0.0
            missing = structured.get("missing_evidence", []) if isinstance(structured, dict) else []
            if explorer_confidence >= self.explorer_skip_worker_confidence and not missing:
                need_worker = False
                plan = dict(plan)
                plan["worker"] = False
                if risk_score < self.critic_risk_score:
                    plan["critic"] = False
                plan["reason"] = "7b-confidence-sufficient"
        if need_worker:
            self.worker_runs += 1
            worker_model = self._select_worker_model(
                route, mode, risk_score, self.direct_smart_risk_score, fast_model, heavy_model
            )

            def compute_worker() -> dict[str, Any]:
                if self.tool_agent is not None:
                    tool_result = self.tool_agent.run(
                        worker_model, "worker", task, root, max_tokens=self.max_worker_tokens, priority=6,
                        workspace=args.get("workspace"),
                        seed_context=f"EXPLORER STATE:\n{json_dumps(explorer.get('structured') or {'summary': explorer.get('text','')}, ensure_ascii=False, separators=(',',':'))}\n\nEVIDENCE:\n{packed.get('context','')}",
                        bootstrap={"deterministic": deterministic, "code_index": graph},
                        system_suffix="Produce the smallest correct diagnosis/implementation plan, exact file/symbol actions, edge cases and validation. Return a concise flat list. Never nest bullet points or repeat section headers. Do not repeat evidence.",
                    )
                    if tool_result.get("success"):
                        return tool_result
                    if _is_repetition_loop(tool_result):
                        return tool_result
                    # Tool calling is an acceleration/quality path, never a hard dependency.
                    # Tool calling is optional; models without a usable tool-call response fall back to a plain prompt.
                return self.services._generate(
                    worker_model,
                    f"TASK:\n{task}\n\nEXPLORER STATE:\n{json_dumps(explorer.get('structured') or {'summary': explorer.get('text','')}, ensure_ascii=False, separators=(',',':'))}\n\nEXACT/RETRIEVED EVIDENCE:\n{packed.get('context','')}",
                    "You are the scoped implementation worker. Produce the smallest correct implementation/diagnosis plan, explicit file/symbol actions, edge cases and validation. Return a concise flat list. Never nest bullet points or repeat section headers. Do not repeat evidence. If evidence is insufficient, say exactly what is missing.",
                    self.max_worker_tokens, 0.08, source="pipeline:worker", priority=6,
                    semantic_query=task, semantic_context_fingerprint=semantic_context_fp, internal=True,
                )

            worker = self._stage(
                {"app_version": __version__, "execution": self.execution_policy_fp, "role": "worker", "task": task, "context": context_fp, "explorer": stable_hash(explorer.get("structured") or explorer.get("text", "")), "model": worker_model},
                compute_worker,
            )
            if cancelled():
                return cancelled_result()
            if not worker.get("success"):
                if _is_repetition_loop(worker):
                    return _repetition_loop_failure(worker, stage="worker", mode=mode)
                fallback = self.services.delegate_repo(args)
                fallback["pipeline"] = {"mode": mode, "degraded": True, "failed_stage": "worker"}
                return fallback

            # If heavy and fast intentionally share one model, an optional bounded second pass
            # can improve quality without introducing another model load.
            same_fast_model = worker_model == self.config.get("models", {}).get("fast_code")
            do_refine = same_fast_model and self.same_model_worker_passes > 1 and (
                mode == "quality" or int(route.get("complexity_score", 0) or 0) >= self.second_pass_min_complexity_score
            )
            if do_refine:
                self.refine_runs += 1
                first_state = worker.get("structured") or {"summary": worker.get("text", "")}
                def compute_refine() -> dict[str, Any]:
                    if self.tool_agent is not None:
                        refined = self.tool_agent.run(
                            worker_model, "worker", task, root, max_tokens=max(700, int(self.max_worker_tokens * 0.8)), priority=6,
                            workspace=args.get("workspace"),
                            seed_context=f"FIRST PASS:\n{json_dumps(first_state, ensure_ascii=False, separators=(',',':'))}\n\nEVIDENCE:\n{packed.get('context','')}",
                            bootstrap={"deterministic": deterministic, "code_index": graph},
                            system_suffix="Second pass: independently verify the first fast-tier result, correct concrete mistakes, remove unsupported claims, and return only the improved final actions/risks/validation as a concise flat list without nested bullets or repeating headers.",
                        )
                        if refined.get("success"):
                            return refined
                        if _is_repetition_loop(refined):
                            return refined
                    return self.services._generate(
                        worker_model,
                        f"TASK:\n{task}\n\nFIRST PASS:\n{json_dumps(first_state, ensure_ascii=False, separators=(',',':'))}\n\nEVIDENCE:\n{packed.get('context','')}",
                        "You are the second-pass verifier/refiner. Return a concise flat list. Never nest bullet points or repeat section headers. Correct concrete mistakes, remove unsupported claims and return only the improved final plan/actions/risks/validation. Do not restate evidence.",
                        max(700, int(self.max_worker_tokens * 0.8)), 0.03, source="pipeline:worker-refine", priority=6,
                        semantic_query=task, semantic_context_fingerprint=semantic_context_fp, internal=True,
                    )
                refined = self._stage(
                    {"app_version": __version__, "execution": self.execution_policy_fp, "role": "worker-refine", "task": task, "context": context_fp, "first": stable_hash(first_state), "model": worker_model},
                    compute_refine,
                )
                if cancelled():
                    return cancelled_result()
                if refined.get("success"):
                    worker = refined
        else:
            worker = explorer

        need_critic = bool(plan.get("critic"))
        if need_critic and mode != "quality" and (
            risk_score < self.critic_risk_score
            or int(route.get("complexity_score", 0) or 0) < self.critic_min_complexity_score
        ):
            need_critic = False
            plan = dict(plan)
            plan["critic"] = False
            plan["reason"] = "critic-risk-gated"
        critic: dict[str, Any] | None = None
        if need_critic:
            self.critic_runs += 1
            critic_model = self._select_worker_model(
                route, mode, risk_score, self.direct_smart_risk_score, fast_model, reasoning_model
            )
            def compute_critic() -> dict[str, Any]:
                if self.tool_agent is not None:
                    tool_result = self.tool_agent.run(
                        critic_model, "critic", task, root, max_tokens=self.max_critic_tokens, priority=6,
                        workspace=args.get("workspace"),
                        seed_context=f"CANDIDATE STATE:\n{json_dumps(worker.get('structured') or {'summary': worker.get('text','')}, ensure_ascii=False, separators=(',',':'))}\n\nEVIDENCE:\n{packed.get('context','')}",
                        bootstrap={"deterministic": deterministic, "code_index": graph},
                        system_suffix="Terse technical output only: zero conversational filler. Independently verify only material correctness gaps, unsafe assumptions, missed edge cases or missing validation. Return a flat list without nested bullets. If none, say NO_MATERIAL_ISSUE. Do not praise or restate.",
                    )
                    if tool_result.get("success"):
                        return tool_result
                    if _is_repetition_loop(tool_result):
                        return tool_result
                return self.services._generate(
                    critic_model,
                    f"TASK:\n{task}\n\nCANDIDATE STATE:\n{json_dumps(worker.get('structured') or {'summary': worker.get('text','')}, ensure_ascii=False, separators=(',',':'))}\n\nEVIDENCE:\n{packed.get('context','')}",
                    "You are an independent skeptical critic. Terse technical output only: zero conversational filler, pleasantries, or preamble. Return only concrete correctness gaps, unsafe assumptions, missed edge cases or missing validation as a flat list without nested bullets. If no material issue is found, say NO_MATERIAL_ISSUE. Do not praise or restate.",
                    self.max_critic_tokens, 0.05, source="pipeline:critic", priority=6,
                    semantic_query=task, semantic_context_fingerprint=semantic_context_fp, internal=True,
                )

            critic = self._stage(
                {"app_version": __version__, "execution": self.execution_policy_fp, "role": "critic", "task": task, "context": context_fp, "candidate": stable_hash(worker.get("structured") or worker.get("text", "")), "model": critic_model},
                compute_critic,
            )
            if cancelled():
                return cancelled_result()
            if _is_repetition_loop(critic):
                return _repetition_loop_failure(critic, stage="critic", mode=mode)

        if cancelled():
            return cancelled_result()
        worker_structured = worker.get("structured") if isinstance(worker.get("structured"), dict) else None
        canonical_text = str(worker_structured.get("summary", "") if worker_structured else worker.get("text", ""))
        if worker_structured and worker_structured.get("actions"):
            canonical_text += "\nACTIONS: " + json_dumps(worker_structured.get("actions"), ensure_ascii=False, separators=(",", ":"))
        if critic and critic.get("success"):
            critic_structured = critic.get("structured") if isinstance(critic.get("structured"), dict) else None
            critic_text = str(critic_structured.get("summary", "") if critic_structured else critic.get("text", ""))
            if "NO_MATERIAL_ISSUE" not in critic_text.upper() and critic_text:
                canonical_text += "\n\nLOCAL CRITIC:\n" + critic_text
        if len(canonical_text) > self.max_final_chars:
            canonical_text = canonical_text[: self.max_final_chars] + "\n[…canonical detail stored in stage cache/artifacts…]"

        return {
            "success": True,
            "text": canonical_text,
            "canonical": {
                "task": task,
                "route": route,
                "risk": impact.get("risk", {}) if isinstance(impact, dict) else {},
                "plan": plan,
                "code_index": {k: graph.get(k) for k in ("terms", "symbols", "references", "edges", "confidence") if isinstance(graph, dict) and k in graph},
                "deterministic": {k: deterministic.get(k) for k in ("intent", "confidence", "facts", "dependencies", "scripts", "test_candidates", "evidence") if isinstance(deterministic, dict) and k in deterministic},
                "explorer": {"model": explorer.get("model"), "cache_hit": explorer.get("stage_cache_hit", False)},
                "worker": {"used": need_worker, "model": worker.get("model"), "cache_hit": worker.get("stage_cache_hit", False)},
                "critic": {"used": bool(critic), "model": critic.get("model") if critic else None, "cache_hit": critic.get("stage_cache_hit", False) if critic else False},
                "structured": {"explorer": explorer.get("structured"), "worker": worker.get("structured"), "critic": critic.get("structured") if critic else None},
            },
            "repo_context": {
                "root": packed.get("root"), "evidence": packed.get("evidence", []),
                "local_context_tokens": packed.get("estimated_tokens", 0), "semantic_used": packed.get("semantic_used", False), "context_source": packed.get("context_source", "hybrid"),
                "scanned_files": packed.get("scanned_files", 0),
            },
            "impact": {k: impact.get(k) for k in ("changed_files", "suggested_tests", "risk") if isinstance(impact, dict) and k in impact},
            "pipeline": {"mode": mode, "degraded": False, "confidence": plan.get("confidence"), "stages": (["explorer"] if plan.get("explorer") else ["deterministic-explorer"]) + (["worker"] if need_worker else []) + (["critic"] if critic else [])},
        }

    def stats(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled, "runs": self.runs, "worker_runs": self.worker_runs, "refine_runs": self.refine_runs, "critic_runs": self.critic_runs,
            "tool_agent": self.tool_agent.stats() if self.tool_agent is not None else {"enabled": False},
            "cache": self.cache.cache.stats() if hasattr(self.cache.cache, "stats") else {},
            "singleflight": {"hits": self.cache.hits, "misses": self.cache.misses, "coalesced_waiters": self.cache.coalesced_waiters},
        }
