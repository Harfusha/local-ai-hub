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


class LayaUnifiedCoordinator:
    """Master coordinator combining all Laya fast-path optimizations and continuous training capture."""

    def __init__(
        self,
        default_budget: int = 8192,
        laya_runtime_adapter: Any = None,
        training_collector: LayaTrainingCollector | None = None,
        training_capture_enabled: bool = False,
    ) -> None:
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

    def analyze_task(
        self,
        instruction: str,
        query: str | None = None,
        affected_paths: Sequence[str] = (),
        incoming_context_tokens: int = 0,
        max_budget: int | None = None,
    ) -> UnifiedLayaPlan:
        """Run complete multi-signal decision suite and automatically record training samples in <5ms."""
        self._total_inferences += 1
        effective_query = query if query is not None else instruction

        # 0. Check semantic deduplication cache
        cached_match = self.semantic_dedup.find_match(effective_query)

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

        overall_conf = (
            retrieval_rec.confidence * 0.35 +
            model_rec.confidence * 0.35 +
            intent_res.confidence * 0.30
        )

        # 6. Automatic Training Data Capture (if enabled)
        if self.collector.enabled:
            try:
                self.collector.record_laya_decision(
                    category="task_routing",
                    state={
                        "instruction_len": len(instruction),
                        "context_tokens": incoming_context_tokens,
                        "blast_radius": str(intent_res.blast_radius),
                    },
                    question_text=effective_query,
                    expected_choice=str(retrieval_rec.strategy),
                    confidence_distribution={
                        str(retrieval_rec.strategy): retrieval_rec.confidence,
                        "model_tier": model_rec.confidence,
                    },
                )
            except Exception as exc:
                logger.debug("Failed recording laya decision sample: %s", exc)

        return UnifiedLayaPlan(
            crosslingual_expansion=expansion,
            retrieval_recommendation=retrieval_rec,
            model_recommendation=model_rec,
            intent_analysis=intent_res,
            budget_plan=budget_plan,
            overall_confidence=round(overall_conf, 3),
            total_latency_saved_est_ms=retrieval_rec.estimated_latency_saved_ms,
            cached_match=cached_match,
        )

    def scan_code(self, code: str) -> AntiPatternScanResult:
        """Fast pre-execution anti-pattern inspection."""
        return self.antipattern_detector.scan_code(code)

    def score_code(self, source_code: str) -> CodeQualityScore:
        """Fast sub-2ms maintainability and complexity scoring."""
        return self.code_scorer.score_code(source_code)

    def suggest_tests(self, function_code: str) -> TestSuggestion:
        """Predict boundary condition edge-cases and invariants."""
        return self.test_suggester.analyze_function(function_code)

    def index_completed_task(self, prompt: str, result_payload: Any) -> None:
        """Index verified prompt/result into semantic cache for future instant deduplication."""
        pid = f"prompt_{self._total_inferences}"
        self.semantic_dedup.index_prompt(pid, prompt, result_payload)

    def record_verification_receipt(
        self,
        prompt: str,
        chosen_code: str,
        rejected_code: str = "",
        passed: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Capture downstream execution outcome as a DPO preference pair (if enabled)."""
        if not self.collector.enabled:
            return
        self.collector.record_dpo_pair(
            category="code_verification",
            prompt=prompt,
            chosen=chosen_code,
            rejected=rejected_code,
            verification_passed=passed,
            metadata=metadata,
        )
