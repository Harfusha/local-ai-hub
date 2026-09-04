from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .agent_verification import ChangeIntent


@dataclass(frozen=True)
class RouteRequest:
    query: str = ""
    task_type: str = ""
    has_fresh_cache: bool = False
    has_indexed_evidence: bool = False
    needs_semantic: bool = False
    needs_model: bool = False
    cost_limit: float = 1.0


@dataclass(frozen=True)
class RoutingDecision:
    kind: str  # "cache", "index", "semantic", "local_model", "peer_agent", "deterministic"
    target: str
    reason: str
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "reason": self.reason,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class TestSelection:
    __test__ = False
    selected_tests: tuple[str, ...]
    flaky_candidates: tuple[str, ...] = ()
    synthetic_passes: tuple[str, ...] = ()  # Invariant: NEVER manufacture a pass; always ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_tests": list(self.selected_tests),
            "flaky_candidates": list(self.flaky_candidates),
            "synthetic_passes": list(self.synthetic_passes),
        }


@dataclass(frozen=True)
class ToolObservation:
    tool_name: str
    duration_ms: float
    success: bool
    cache_hit: bool = False
    coalesced: bool = False
    cost_estimate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "cache_hit": self.cache_hit,
            "coalesced": self.coalesced,
            "cost_estimate": self.cost_estimate,
        }


class RoutingEngine:
    def __init__(self, state_store: Any | None = None) -> None:
        self.state_store = state_store
        self._known_flakes: set[str] = set()
        self._observations: list[ToolObservation] = []

    def mark_flake(self, test_id: str) -> None:
        self._known_flakes.add(test_id.strip())

    def record_observation(self, obs: ToolObservation) -> None:
        self._observations.append(obs)
        if len(self._observations) > 1000:
            self._observations = self._observations[-500:]

    def select(self, request: RouteRequest) -> RoutingDecision:
        # Strict cheapest-sufficient escalation:
        # cache/deterministic -> index/exact -> semantic/graph -> local model -> peer
        if request.has_fresh_cache:
            return RoutingDecision(
                kind="cache",
                target="cache_hit",
                reason="fresh cached evidence available",
                confidence=1.0,
            )

        if request.has_indexed_evidence:
            return RoutingDecision(
                kind="index",
                target="code_index",
                reason="indexed/exact evidence sufficient",
                confidence=0.95,
            )

        if request.needs_semantic:
            return RoutingDecision(
                kind="semantic",
                target="rag",
                reason="semantic retrieval required",
                confidence=0.85,
            )

        if request.needs_model:
            return RoutingDecision(
                kind="local_model",
                target="qwen2.5-coder:7b",
                reason="local model reasoning selected",
                confidence=0.80,
            )

        return RoutingDecision(
            kind="deterministic",
            target="repo_state",
            reason="deterministic lookup sufficient",
            confidence=0.90,
        )

    def select_tests(self, change: ChangeIntent) -> TestSelection:
        selected: list[str] = []
        flaky: list[str] = []

        for path in change.affected_paths:
            # Map source paths to test paths (e.g. src/network.py -> tests/test_network.py)
            normalized = path.replace("\\", "/")
            base = normalized.split("/")[-1]
            name = base.rsplit(".", 1)[0]
            test_target = f"tests/test_{name}.py"
            selected.append(test_target)

            # Check if any known flakes match this test target
            for flake in self._known_flakes:
                if flake.startswith(test_target) or test_target.startswith(flake.split("::")[0]):
                    flaky.append(flake)

        return TestSelection(
            selected_tests=tuple(selected),
            flaky_candidates=tuple(flaky),
            synthetic_passes=(),  # Invariant: NEVER manufacture a pass
        )
