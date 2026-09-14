from __future__ import annotations

from typing import Any


class AdaptivePlanner:
    """Cheap deterministic execution-DAG planner.

    The planner intentionally runs before local LLM inference. It estimates whether
    deterministic graph/retrieval evidence is already sufficient, then enables only
    the minimum expensive stages required by complexity, risk and confidence.
    """

    def __init__(self, config: dict[str, Any]):
        cfg = config.get("execution_planner", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.direct_confidence = float(cfg.get("direct_confidence", 0.93))
        self.worker_below = float(cfg.get("worker_below_confidence", 0.78))
        self.critic_below = float(cfg.get("critic_below_confidence", 0.68))
        self.critic_risk_score = int(cfg.get("critic_risk_score", 4))
        self.graph_weight = float(cfg.get("graph_weight", 0.65))
        self.evidence_weight_per_item = float(cfg.get("evidence_weight_per_item", 0.045))
        self.max_evidence_confidence = float(cfg.get("max_evidence_confidence", 0.35))

    def _confidence(self, graph: dict[str, Any], evidence_count: int) -> tuple[float, dict[str, float]]:
        graph_conf = max(0.0, min(1.0, float(graph.get("confidence", 0.0)))) if isinstance(graph, dict) else 0.0
        evidence_conf = min(self.max_evidence_confidence, max(0, evidence_count) * self.evidence_weight_per_item)
        confidence = min(0.99, graph_conf * self.graph_weight + evidence_conf)
        return confidence, {
            "graph": round(graph_conf, 4),
            "evidence": round(evidence_conf, 4),
        }

    def plan(
        self,
        route: dict[str, Any],
        risk: int,
        graph: dict[str, Any],
        evidence_count: int,
        mode: str,
    ) -> dict[str, Any]:
        confidence, components = self._confidence(graph, evidence_count)
        heavy = route.get("complexity") == "heavy" or int(route.get("complexity_score", 0)) >= 3
        task_type = str(route.get("task_type", "general"))

        if not self.enabled:
            return {
                "confidence": confidence,
                "confidence_components": components,
                "explorer": True,
                "worker": heavy,
                "critic": risk >= self.critic_risk_score or task_type == "review",
                "reason": "planner-disabled-default",
            }

        if mode == "quality":
            return {
                "confidence": confidence,
                "confidence_components": components,
                "explorer": True,
                "worker": True,
                "critic": True,
                "reason": "quality-mode",
            }

        explorer = confidence < self.direct_confidence
        worker = heavy or confidence < self.worker_below
        critic = risk >= self.critic_risk_score or confidence < self.critic_below or task_type == "review"

        # A fast request may terminate entirely on strong deterministic evidence.
        # Adaptive mode receives the same benefit when no risk/complexity gate needs
        # an LLM stage; this is the common zero-inference path after preprocessing.
        if confidence >= self.direct_confidence and not heavy and risk < self.critic_risk_score and task_type != "review":
            explorer = worker = critic = False
            reason = "deterministic-evidence-sufficient"
        else:
            reason = "adaptive-confidence"

        if mode == "fast":
            # Fast mode never escalates merely because confidence is low; at most one
            # explorer stage is allowed. Correctness-critical callers should use adaptive/quality.
            worker = False
            critic = False
            explorer = confidence < self.direct_confidence
            reason = "fast-bounded" if explorer else "deterministic-evidence-sufficient"

        return {
            "confidence": round(confidence, 4),
            "confidence_components": components,
            "explorer": explorer,
            "worker": worker,
            "critic": critic,
            "reason": reason,
        }
