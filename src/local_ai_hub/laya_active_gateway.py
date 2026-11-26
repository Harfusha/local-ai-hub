"""Active Laya Decision & Fast-Path Routing Gateway.

Provides active inline advisory routing for Local AI Hub operations:
1. Retrieval Strategy Dispatcher (AST, BM25, HNSW, GraphRAG, Hybrid).
2. Model Tier Router (hardware-profile `fast_code`, `heavy_code`, and `reasoning`).
3. Context Pruning Gate (Full, AST Skeleton, Drop).
4. Pre-Verification Fast-Reject Gate.

Maintains deterministic fallback when Laya ONNX/checkpoint is uninitialized.
Integrates with laya_rl for continuous feedback tracking.
"""

from __future__ import annotations

import logging
# import math
import os
import re
from dataclasses import dataclass
from enum import StrEnum
# from pathlib import Path
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)


class RetrievalStrategy(StrEnum):
    AST_SYMBOL = "ast_symbol"
    LEXICAL_BM25 = "lexical_bm25"
    SEMANTIC_HNSW = "semantic_hnsw"
    GRAPHRAG = "graphrag"
    HYBRID = "hybrid"


class ModelTier(StrEnum):
    FAST = "fast"
    SMART = "smart"
    REASONING = "reasoning"


class ContextAction(StrEnum):
    KEEP_FULL = "keep_full"
    SKELETONIZE = "skeletonize"
    DROP = "drop"


@dataclass(frozen=True)
class RetrievalRecommendation:
    strategy: RetrievalStrategy
    confidence: float
    reasons: tuple[str, ...]
    skip_branches: tuple[str, ...] = ()
    estimated_latency_saved_ms: float = 0.0


@dataclass(frozen=True)
class ModelRouteRecommendation:
    tier: ModelTier
    model_name: str
    confidence: float
    reasons: tuple[str, ...]
    speculative_window: int = 4
    suggested_temperature: float = 0.2


@dataclass(frozen=True)
class PreVerificationResult:
    passed: bool
    confidence: float
    findings: tuple[str, ...]
    recommended_action: str


class LayaActiveGateway:
    """Active decision gateway providing sub-5ms routing advisory."""

    def __init__(
        self,
        laya_runtime_adapter: Any = None,
        rl_feedback_recorder: Any = None,
        model_roles: Mapping[str, Any] | None = None,
    ) -> None:
        self._adapter = laya_runtime_adapter
        self._rl_recorder = rl_feedback_recorder
        self._decision_counter = 0
        self.model_roles = dict(model_roles or {})

    def _model_for(self, role: str, fallback: str) -> str:
        model = self.model_roles.get(role)
        return model.strip() if isinstance(model, str) and model.strip() else fallback

    def route_retrieval(
        self,
        query: str,
        repo_stats: Mapping[str, Any] | None = None,
    ) -> RetrievalRecommendation:
        """Recommend retrieval strategy in <2ms, skipping irrelevant indexing pipelines."""
        q = query.strip()
        reasons: list[str] = []
        skip_branches: list[str] = []

        # 1. Exact symbol or identifier query (e.g., def func_name, class MyClass, method.call)
        symbol_match = re.match(
            r"^((def|class)\s+)?[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*(\(\))?$",
            q,
        )
        if symbol_match:
            reasons.append("Query matches exact identifier/symbol definition pattern")
            skip_branches.extend(["semantic_hnsw", "graphrag"])
            return RetrievalRecommendation(
                strategy=RetrievalStrategy.AST_SYMBOL,
                confidence=0.95,
                reasons=tuple(reasons),
                skip_branches=tuple(skip_branches),
                estimated_latency_saved_ms=25.0,
            )

        # 2. Error message, stack trace or log excerpt (hex codes, line numbers, Traceback)
        if "Traceback" in q or "Error:" in q or re.search(r"line \d+", q) or "0x" in q:
            reasons.append("Query matches error trace or exact string token pattern")
            skip_branches.extend(["semantic_hnsw", "graphrag"])
            return RetrievalRecommendation(
                strategy=RetrievalStrategy.LEXICAL_BM25,
                confidence=0.92,
                reasons=tuple(reasons),
                skip_branches=tuple(skip_branches),
                estimated_latency_saved_ms=30.0,
            )

        # 3. High-level architectural or relationship query (architecture, dependency, workflow, subsystem)
        arch_keywords = ("architecture", "component", "subsystem", "cluster", "dependency", "hierarchy", "workflow")
        if any(kw in q.lower() for kw in arch_keywords):
            reasons.append("Query is high-level architectural / dependency concept")
            skip_branches.extend(["ast_symbol"])
            return RetrievalRecommendation(
                strategy=RetrievalStrategy.GRAPHRAG,
                confidence=0.88,
                reasons=tuple(reasons),
                skip_branches=tuple(skip_branches),
                estimated_latency_saved_ms=15.0,
            )

        # 4. Pure semantic question without explicit symbol or code
        if len(q.split()) > 6 and not any(ch in q for ch in ("(", ")", "_", "{", "}", ";")):
            reasons.append("Long natural language conceptual question")
            skip_branches.append("ast_symbol")
            return RetrievalRecommendation(
                strategy=RetrievalStrategy.SEMANTIC_HNSW,
                confidence=0.85,
                reasons=tuple(reasons),
                skip_branches=tuple(skip_branches),
                estimated_latency_saved_ms=10.0,
            )

        # 5. Default hybrid
        return RetrievalRecommendation(
            strategy=RetrievalStrategy.HYBRID,
            confidence=0.90,
            reasons=("Broad query requiring multi-signal hybrid fusion",),
            skip_branches=(),
            estimated_latency_saved_ms=0.0,
        )

    def route_model(
        self,
        task_prompt: str,
        context_token_count: int = 0,
    ) -> ModelRouteRecommendation:
        """Route to optimal model tier based on task complexity and token budget."""
        p_lower = task_prompt.lower()

        # Complex reasoning & deep multi-component architecture
        reasoning_patterns = (
            "design architecture", "formal proof", "mathematical derivation",
            "concurrency deadlock", "distributed consensus", "complex protocol",
        )
        if any(pat in p_lower for pat in reasoning_patterns) or context_token_count > 24000:
            return ModelRouteRecommendation(
                tier=ModelTier.REASONING,
                model_name=self._model_for("reasoning", "qwen2.5-coder:7b"),
                confidence=0.92,
                reasons=("Complex reasoning or large context requirements detected",),
                speculative_window=2,
                suggested_temperature=0.1,
            )

        # Fast tasks: simple fixes, typings, comments, unit test stubs, single function
        fast_patterns = (
            "add type annotation", "fix typo", "format docstring", "add comment",
            "synthesize return type", "rename variable", "simple test case",
        )
        if any(pat in p_lower for pat in fast_patterns) and context_token_count < 4000:
            return ModelRouteRecommendation(
                tier=ModelTier.FAST,
                model_name=self._model_for("fast_code", "qwen2.5-coder:3b"),
                confidence=0.94,
                reasons=("Task matched low-complexity localized code transform pattern",),
                speculative_window=6,
                suggested_temperature=0.0,
            )

        # Default standard coding & refactoring uses the active heavy_code route.
        return ModelRouteRecommendation(
            tier=ModelTier.SMART,
            model_name=self._model_for("heavy_code", "qwen2.5-coder:7b"),
            confidence=0.90,
            reasons=("Standard software engineering implementation and validation",),
            speculative_window=4,
            suggested_temperature=0.2,
        )

    def evaluate_context_pruning(
        self,
        file_paths: Sequence[str],
        query: str,
    ) -> dict[str, ContextAction]:
        """Categorize files into keep_full, skeletonize, or drop to optimize prompt budget."""
        q_tokens = set(re.findall(r"[A-Za-z0-9_]+", query.lower()))
        results: dict[str, ContextAction] = {}

        for p in file_paths:
            p_clean = p.replace("\\", "/")
            basename = os.path.basename(p_clean).lower()
            name_no_ext = os.path.splitext(basename)[0]

            # Direct match in query
            if any(tok in name_no_ext for tok in q_tokens if len(tok) > 2):
                results[p] = ContextAction.KEEP_FULL
            elif "test" in basename:
                # Tests for unrelated files can be dropped or skeletonized
                results[p] = ContextAction.DROP
            elif any(sub in p_clean for sub in ("src/", "lib/", "core/")):
                # Core libraries are useful for signatures
                results[p] = ContextAction.SKELETONIZE
            else:
                results[p] = ContextAction.DROP

        # Ensure at least one file is kept full if input is not empty
        if results and ContextAction.KEEP_FULL not in results.values():
            first_path = next(iter(results))
            results[first_path] = ContextAction.KEEP_FULL

        return results

    def pre_verify_output(self, code_diff: str) -> PreVerificationResult:
        """Fast-reject dangerous or corrupted code before expensive test suites."""
        findings: list[str] = []

        if not code_diff.strip():
            return PreVerificationResult(
                passed=False,
                confidence=1.0,
                findings=("Empty code diff proposal",),
                recommended_action="reject_empty",
            )

        # Check for dangerous constructs
        if re.search(r"\beval\s*\(", code_diff):
            findings.append("Unsafe dynamic code execution: eval()")
        if re.search(r"\bexec\s*\(", code_diff):
            findings.append("Unsafe dynamic code execution: exec()")
        if re.search(r"os\.system\s*\(", code_diff):
            findings.append("Unsafe shell execution: os.system()")
        if re.search(r"while\s+True\s*:(?!.*break)", code_diff, re.DOTALL):
            findings.append("Potential infinite loop: while True without visible break")

        # Check unclosed brackets / quotes
        for open_ch, close_ch in (("(", ")"), ("[", "]"), ("{", "}")):
            if code_diff.count(open_ch) != code_diff.count(close_ch):
                findings.append(f"Mismatched bracket count for '{open_ch}' vs '{close_ch}'")

        if findings:
            return PreVerificationResult(
                passed=False,
                confidence=0.98,
                findings=tuple(findings),
                recommended_action="reject_and_request_fix",
            )

        return PreVerificationResult(
            passed=True,
            confidence=0.95,
            findings=("Fast-path syntax and safety checks passed",),
            recommended_action="proceed_to_test_suite",
        )

    def record_feedback(self, decision_id: str, success: bool, latency_ms: float = 0.0) -> None:
        """Record outcome feedback into laya_rl if available."""
        self._decision_counter += 1
        if self._rl_recorder and hasattr(self._rl_recorder, "record_outcome"):
            try:
                self._rl_recorder.record_outcome(
                    decision_id=decision_id,
                    success=success,
                    latency_ms=latency_ms,
                )
            except Exception as exc:
                logger.debug("Failed to record RL outcome: %s", exc)
