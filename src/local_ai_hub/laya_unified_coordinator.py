"""Laya Unified Optimization Coordinator.

Orchestrates all specialized Laya neural decision engines into one unified,
high-performance entrypoint (<5ms latency):
- Active Gateway (Retrieval & Model routing)
- Cross-Lingual Semantic Reranker & Query Expander
- Edit Intent & Blast-Radius Classifier
- Token-Budget Predictive Allocator
- Negative-Knowledge & Anti-Pattern Detector
- Real-Time Code Quality & Complexity Scorer
- Test Edge-Case & Invariant Suggester
- Semantic Deduplicator & Paraphrase Cache Indexer
- Universal Telemetry & Self-Supervised Training Collector
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .laya_active_gateway import LayaActiveGateway, RetrievalRecommendation, ModelRouteRecommendation
from .laya_crosslingual_reranker import LayaCrossLingualReranker, CrossLingualExpansion
from .laya_edit_intent import LayaEditIntentClassifier, IntentAnalysisResult
from .laya_budget_allocator import LayaBudgetAllocator, BudgetAllocationPlan
from .laya_antipattern_detector import LayaAntiPatternDetector, AntiPatternScanResult
from .laya_code_scorer import LayaCodeScorer, CodeQualityScore
from .laya_test_suggester import LayaTestSuggester, TestSuggestion
from .laya_semantic_dedup import LayaSemanticDeduplicator, SemanticMatchResult
from .laya_training_collector import LayaTrainingCollector

logger = logging.getLogger(__name__)

VALID_LAYA_MODES = frozenset({"off", "shadow", "advisory", "active"})


@dataclass(frozen=True)
class UnifiedLayaPlan:
    crosslingual_expansion: CrossLingualExpansion
    retrieval_recommendation: RetrievalRecommendation
    model_recommendation: ModelRouteRecommendation
    intent_analysis: IntentAnalysisResult
    budget_plan: BudgetAllocationPlan
    overall_confidence: float
    total_latency_saved_est_ms: float
    cached_match: SemanticMatchResult | None = None
    mode: str = "advisory"
    provenance: str = "laya_advisory"
    is_actionable: bool = False
    abstained: bool = False
    abstention_reason: str | None = None
    calibrated_head_confidences: dict[str, float] | None = None


class LayaUnifiedCoordinator:
    """Master coordinator combining all Laya fast-path optimizations and continuous training capture."""

    def __init__(
        self,
        mode: str = "advisory",
        default_budget: int = 8192,
        laya_runtime_adapter: Any = None,
        training_collector: LayaTrainingCollector | None = None,
        training_capture_enabled: bool = False,
        active_confidence_threshold: float = 0.65,
    ) -> None:
        self.mode = mode if mode in VALID_LAYA_MODES else "advisory"
        self.active_confidence_threshold = float(active_confidence_threshold)
        self.gateway = LayaActiveGateway(laya_runtime_adapter=laya_runtime_adapter)
        self.reranker = LayaCrossLingualReranker()
        self.intent_classifier = LayaEditIntentClassifier()
        self.budget_allocator = LayaBudgetAllocator(default_budget=default_budget)
        self.antipattern_detector = LayaAntiPatternDetector()
        self.code_scorer = LayaCodeScorer()
        self.test_suggester = LayaTestSuggester()
        self.semantic_dedup = LayaSemanticDeduplicator()
        self.collector = training_collector or LayaTrainingCollector(enabled=training_capture_enabled)
        self._total_inferences = 0
        self._lock = threading.Lock()

    def analyze_task(
        self,
        instruction: str,
        query: str | None = None,
        affected_paths: Sequence[str] = (),
        incoming_context_tokens: int = 0,
        max_budget: int | None = None,
        *,
        repo_root: str | None = None,
        worktree_id: str | None = None,
        revision: str | None = None,
        operation: str = "query",
        is_mutation: bool = False,
    ) -> UnifiedLayaPlan:
        """Run complete multi-signal decision suite respecting state machine and strict replay admissibility."""
        with self._lock:
            self._total_inferences += 1

        effective_query = query if query is not None else instruction

        # State machine mode: "off" -> Zero neural/heuristic inference, zero training capture, instant deterministic baseline
        if self.mode == "off":
            expansion = CrossLingualExpansion(
                original_query=effective_query,
                detected_language="en",
                expanded_terms=(),
                composite_query=effective_query,
            )
            retrieval_rec = RetrievalRecommendation(
                strategy="ast_symbol",
                confidence=1.0,
                reasons=("laya_mode_off",),
                skip_branches=(),
                estimated_latency_saved_ms=0.0,
            )
            model_rec = ModelRouteRecommendation(
                tier="fast",
                model_name="deterministic",
                confidence=1.0,
                reasons=("laya_mode_off",),
                speculative_window=0,
                suggested_temperature=0.0,
            )
            intent_res = IntentAnalysisResult(
                intent="unknown",
                blast_radius="single_file",
                validation_level="syntax",
                confidence=1.0,
                reasons=("laya_mode_off",),
                target_files_hint=(),
            )
            budget_plan = self.budget_allocator.allocate(
                requested_budget=max_budget,
                task_complexity="standard",
                incoming_context_tokens=incoming_context_tokens,
            )
            return UnifiedLayaPlan(
                crosslingual_expansion=expansion,
                retrieval_recommendation=retrieval_rec,
                model_recommendation=model_rec,
                intent_analysis=intent_res,
                budget_plan=budget_plan,
                overall_confidence=1.0,
                total_latency_saved_est_ms=0.0,
                cached_match=None,
                mode="off",
                provenance="deterministic_default_mode_off",
                is_actionable=False,
                abstained=False,
                abstention_reason=None,
                calibrated_head_confidences={"retrieval": 1.0, "model": 1.0, "intent": 1.0},
            )

        # 0. Check semantic deduplication cache with scope and replay admissibility checks
        cached_match = self.semantic_dedup.find_match(
            effective_query,
            repo_root=repo_root,
            worktree_id=worktree_id,
            revision=revision,
            operation=operation,
            allow_mutation=not is_mutation,
        )

        # 1. Cross-Lingual expansion
        expansion = self.reranker.expand_query(effective_query)

        # 2. Retrieval routing
        retrieval_rec = self.gateway.route_retrieval(expansion.composite_query)

        # 3. Model routing
        model_rec = self.gateway.route_model(instruction, context_token_count=incoming_context_tokens)

        # 4. Intent & Blast radius
        intent_res = self.intent_classifier.classify(instruction, affected_paths=affected_paths)

        # 5. Budget allocation
        complexity_tier = "heavy" if intent_res.blast_radius == "cross_file_architecture" else "standard"
        if intent_res.intent == "typing_docs":
            complexity_tier = "simple"

        budget_plan = self.budget_allocator.allocate(
            requested_budget=max_budget,
            task_complexity=complexity_tier,
            incoming_context_tokens=incoming_context_tokens,
        )

        # 6. Per-head confidence calibration & OOD detection (LAH-032)
        cal_r = min(1.0, max(0.0, round(retrieval_rec.confidence * 0.95 + 0.02, 3)))
        cal_m = min(1.0, max(0.0, round(model_rec.confidence * 0.95 + 0.02, 3)))
        cal_i = min(1.0, max(0.0, round(intent_res.confidence * 0.95 + 0.02, 3)))
        head_calibrations = {"retrieval": cal_r, "model": cal_m, "intent": cal_i}

        clean_text = effective_query.strip()
        is_ood = (
            len(clean_text) < 2
            or len(clean_text) > 8000
            or (cal_r < 0.35 and cal_m < 0.35 and cal_i < 0.35)
        )

        overall_conf = round(cal_r * 0.35 + cal_m * 0.35 + cal_i * 0.30, 3)

        # Mode-specific execution and actionability
        if self.mode == "shadow":
            plan_mode = "shadow"
            provenance = "laya_shadow_evaluation_only"
            is_actionable = False
            abstained = True
            abstention_reason = "shadow_mode_non_binding"
        elif self.mode == "active":
            plan_mode = "active"
            if is_ood or overall_conf < self.active_confidence_threshold:
                provenance = "laya_active_abstained_to_baseline"
                is_actionable = False
                abstained = True
                abstention_reason = "out_of_distribution" if is_ood else "low_confidence"
            else:
                provenance = "laya_active_calibrated"
                is_actionable = True
                abstained = False
                abstention_reason = None
        else:  # advisory
            plan_mode = "advisory"
            provenance = "laya_advisory_recommendation"
            is_actionable = False
            abstained = False
            abstention_reason = None

        return UnifiedLayaPlan(
            crosslingual_expansion=expansion,
            retrieval_recommendation=retrieval_rec,
            model_recommendation=model_rec,
            intent_analysis=intent_res,
            budget_plan=budget_plan,
            overall_confidence=overall_conf,
            total_latency_saved_est_ms=retrieval_rec.estimated_latency_saved_ms,
            cached_match=cached_match,
            mode=plan_mode,
            provenance=provenance,
            is_actionable=is_actionable,
            abstained=abstained,
            abstention_reason=abstention_reason,
            calibrated_head_confidences=head_calibrations,
        )

    def scan_code(self, code: str) -> AntiPatternScanResult:
        """Fast pre-execution anti-pattern inspection."""
        if self.mode == "off":
            return AntiPatternScanResult(has_violations=False, risk_score=0.0, violations=(), status="clean")
        return self.antipattern_detector.scan_code(code)

    def score_code(self, source_code: str) -> CodeQualityScore:
        """Fast sub-2ms maintainability and complexity scoring."""
        if self.mode == "off":
            return CodeQualityScore(
                overall_score=1.0,
                maintainability_index=100.0,
                cyclomatic_complexity=1,
                lines_of_code=len(source_code.splitlines()),
                has_docstrings=True,
                type_coverage_percent=100.0,
                recommendations=(),
            )
        return self.code_scorer.score_code(source_code)

    def suggest_tests(self, function_code: str) -> TestSuggestion:
        """Predict boundary condition edge-cases and invariants."""
        if self.mode == "off":
            return TestSuggestion(
                target_function="deterministic",
                hypotheses=(),
                potential_exceptions=(),
                suggested_test_code="",
            )
        return self.test_suggester.analyze_function(function_code)

    def index_completed_task(
        self,
        prompt: str,
        result_payload: Any,
        *,
        repo_root: str | None = None,
        worktree_id: str | None = None,
        revision: str | None = None,
        operation: str | None = None,
        is_mutation: bool = False,
        ttl_seconds: float | None = None,
    ) -> str:
        """Index verified prompt/result into semantic cache with unique ID."""
        if self.mode == "off":
            return ""
        pid = f"prompt_{uuid.uuid4().hex[:12]}"
        self.semantic_dedup.index_prompt(
            pid,
            prompt,
            result_payload,
            repo_root=repo_root,
            worktree_id=worktree_id,
            revision=revision,
            operation=operation,
            is_mutation=is_mutation,
            ttl_seconds=ttl_seconds,
        )
        return pid

    def record_verification_receipt(
        self,
        prompt: str,
        chosen_code: str,
        rejected_code: str = "",
        passed: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Capture downstream execution outcome as a DPO preference pair (if enabled)."""
        if self.mode == "off" or not self.collector.enabled:
            return
        self.collector.record_dpo_pair(
            category="code_verification",
            prompt=prompt,
            chosen=chosen_code,
            rejected=rejected_code,
            verification_passed=passed,
            metadata=metadata,
        )
