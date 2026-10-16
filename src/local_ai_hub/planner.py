from __future__ import annotations

import math
from typing import Any


def _safe_float(val: Any, default: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    if val is None or isinstance(val, bool):
        return default
    try:
        f = float(val)
        if not math.isfinite(f):
            return default
        return max(min_val, min(max_val, f))
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: int, min_val: int = 0) -> int:
    if val is None or isinstance(val, bool):
        return default
    try:
        i = int(val)
        return max(min_val, i)
    except (ValueError, TypeError):
        return default


class AdaptivePlanner:
    """Cheap deterministic execution-DAG planner.

    The planner intentionally runs before local LLM inference. It estimates whether
    deterministic graph/retrieval evidence is already sufficient, then enables only
    the minimum expensive stages required by complexity, risk and confidence.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config.get("execution_planner", {}) if isinstance(config, dict) else {}
        if not isinstance(cfg, dict):
            cfg = {}
        self.enabled = bool(cfg.get("enabled", True))
        self.direct_confidence = _safe_float(cfg.get("direct_confidence"), 0.93)
        self.worker_below = _safe_float(cfg.get("worker_below_confidence"), 0.78)
        self.critic_below = _safe_float(cfg.get("critic_below_confidence"), 0.68)
        self.critic_risk_score = _safe_int(cfg.get("critic_risk_score"), 4)
        self.graph_weight = _safe_float(cfg.get("graph_weight"), 0.65)
        self.evidence_weight_per_item = _safe_float(cfg.get("evidence_weight_per_item"), 0.045, 0.0, 10.0)
        self.max_evidence_confidence = _safe_float(cfg.get("max_evidence_confidence"), 0.35)

    def is_enabled(self) -> bool:
        return self.enabled

    def is_heavy(self, route: dict[str, Any] | None) -> bool:
        if not isinstance(route, dict):
            return False
        return route.get("complexity") == "heavy" or _safe_int(route.get("complexity_score"), 0) >= 3

    def should_use_critic(self, risk: int, task_type: str = "") -> bool:
        return _safe_int(risk, 0) >= self.critic_risk_score or str(task_type or "").strip().lower() == "review"

    def _confidence(self, graph: dict[str, Any] | None, evidence_count: int) -> tuple[float, dict[str, float]]:
        if isinstance(graph, dict):
            raw_conf = graph.get("confidence")
            if raw_conf is None or isinstance(raw_conf, bool):
                graph_conf = 0.0
            else:
                try:
                    f = float(raw_conf)
                    graph_conf = max(0.0, min(1.0, f)) if math.isfinite(f) else 0.0
                except (ValueError, TypeError):
                    graph_conf = 0.0
        else:
            graph_conf = 0.0

        ev_count = _safe_int(evidence_count, 0)
        evidence_conf = min(self.max_evidence_confidence, ev_count * self.evidence_weight_per_item)
        confidence = min(0.99, max(0.0, graph_conf * self.graph_weight + evidence_conf))
        return confidence, {
            "graph": round(graph_conf, 4),
            "evidence": round(evidence_conf, 4),
        }

    def plan(
        self,
        route: dict[str, Any] | None,
        risk: int,
        graph: dict[str, Any] | None,
        evidence_count: int,
        mode: str = "adaptive",
    ) -> dict[str, Any]:
        route_dict = route if isinstance(route, dict) else {}
        mode_str = str(mode or "adaptive").strip().lower()
        risk_int = _safe_int(risk, 0)

        confidence, components = self._confidence(graph, evidence_count)
        heavy = self.is_heavy(route_dict)
        task_type = str(route_dict.get("task_type") or "general").strip().lower()
        semantic_required = bool(route_dict.get("semantic_required", False))

        # Explicit semantic requests must not be short-circuited by strong exact
        # evidence. One bounded explorer pass is enough in fast/adaptive mode;
        # quality mode retains its normal multi-stage plan below.
        if semantic_required and mode_str != "quality":
            return {
                "confidence": round(confidence, 4),
                "confidence_components": components,
                "explorer": True,
                "worker": False,
                "critic": False,
                "reason": "semantic-request",
            }

        if not self.enabled:
            return {
                "confidence": confidence,
                "confidence_components": components,
                "explorer": True,
                "worker": heavy,
                "critic": risk_int >= self.critic_risk_score or task_type == "review",
                "reason": "planner-disabled-default",
            }

        if mode_str == "quality":
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
        critic = risk_int >= self.critic_risk_score or confidence < self.critic_below or task_type == "review"

        # A fast request may terminate entirely on strong deterministic evidence.
        # Adaptive mode receives the same benefit when no risk/complexity gate needs
        # an LLM stage; this is the common zero-inference path after preprocessing.
        if confidence >= self.direct_confidence and not heavy and risk_int < self.critic_risk_score and task_type != "review":
            explorer = worker = critic = False
            reason = "deterministic-evidence-sufficient"
        else:
            reason = "adaptive-confidence"

        if mode_str == "fast":
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
