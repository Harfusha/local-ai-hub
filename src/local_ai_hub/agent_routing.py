from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .agent_verification import ChangeIntent


VALID_ROUTING_KINDS: frozenset[str] = frozenset(
    {"cache", "index", "semantic", "local_model", "peer_agent", "deterministic"}
)


@dataclass(frozen=True)
class RouteRequest:
    query: str = ""
    task_type: str = ""
    has_fresh_cache: bool = False
    has_indexed_evidence: bool = False
    needs_semantic: bool = False
    needs_model: bool = False
    cost_limit: float = 1.0

    def __post_init__(self) -> None:
        q = str(self.query or "").replace("\x00", "").strip()
        tt = str(self.task_type or "").replace("\x00", "").strip()
        if isinstance(self.cost_limit, bool) or self.cost_limit is None:
            cl = 0.0
        else:
            try:
                cl = float(self.cost_limit)
                cl = max(0.0, cl) if math.isfinite(cl) else 0.0
            except (ValueError, TypeError, OverflowError):
                cl = 0.0
        object.__setattr__(self, "query", q)
        object.__setattr__(self, "task_type", tt)
        object.__setattr__(self, "has_fresh_cache", self.has_fresh_cache is True)
        object.__setattr__(self, "has_indexed_evidence", self.has_indexed_evidence is True)
        object.__setattr__(self, "needs_semantic", self.needs_semantic is True)
        object.__setattr__(self, "needs_model", self.needs_model is True)
        object.__setattr__(self, "cost_limit", cl)

    def is_cached(self) -> bool:
        return self.has_fresh_cache

    def is_indexed(self) -> bool:
        return self.has_indexed_evidence

    def requires_semantic(self) -> bool:
        return self.needs_semantic

    def requires_model(self) -> bool:
        return self.needs_model


@dataclass(frozen=True)
class RoutingDecision:
    kind: str  # "cache", "index", "semantic", "local_model", "peer_agent", "deterministic"
    target: str
    reason: str
    confidence: float = 1.0

    def __post_init__(self) -> None:
        k = str(self.kind or "").replace("\x00", "").strip().lower()
        if k not in VALID_ROUTING_KINDS:
            k = "deterministic"
        t = str(self.target or "").replace("\x00", "").strip()
        r = str(self.reason or "").replace("\x00", "").strip()
        if isinstance(self.confidence, bool) or self.confidence is None:
            conf = 0.0
        else:
            try:
                conf = float(self.confidence)
                if not math.isfinite(conf):
                    conf = 0.0
                else:
                    conf = max(0.0, min(1.0, conf))
            except (ValueError, TypeError, OverflowError):
                conf = 0.0
        object.__setattr__(self, "kind", k)
        object.__setattr__(self, "target", t)
        object.__setattr__(self, "reason", r)
        object.__setattr__(self, "confidence", conf)

    def is_cache(self) -> bool:
        return self.kind == "cache"

    def is_index(self) -> bool:
        return self.kind == "index"

    def is_semantic(self) -> bool:
        return self.kind == "semantic"

    def is_model(self) -> bool:
        return self.kind == "local_model"

    def is_deterministic(self) -> bool:
        return self.kind == "deterministic"

    def is_high_confidence(self, threshold: float = 0.9) -> bool:
        return self.confidence >= threshold

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

    def __post_init__(self) -> None:
        def _clean_tuple(items: Any) -> tuple[str, ...]:
            if not items or isinstance(items, bool):
                return ()
            if not hasattr(items, "__iter__") or isinstance(items, (str, bytes)):
                items = [items]
            cleaned: list[str] = []
            for item in items:
                if item is None or isinstance(item, bool):
                    continue
                s = str(item).replace("\x00", "").strip()
                if s:
                    cleaned.append(s)
            return tuple(cleaned)

        object.__setattr__(self, "selected_tests", _clean_tuple(self.selected_tests))
        object.__setattr__(self, "flaky_candidates", _clean_tuple(self.flaky_candidates))
        object.__setattr__(self, "synthetic_passes", ())  # Invariant: NEVER manufacture a pass

    def has_tests(self) -> bool:
        return bool(self.selected_tests)

    def test_count(self) -> int:
        return len(self.selected_tests)

    def has_flakes(self) -> bool:
        return bool(self.flaky_candidates)

    def flake_count(self) -> int:
        return len(self.flaky_candidates)

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

    def __post_init__(self) -> None:
        tn = str(self.tool_name or "").replace("\x00", "").strip()
        if isinstance(self.duration_ms, bool) or self.duration_ms is None:
            d = 0.0
        else:
            try:
                d = float(self.duration_ms)
                d = max(0.0, d) if math.isfinite(d) else 0.0
            except (ValueError, TypeError, OverflowError):
                d = 0.0
        if isinstance(self.cost_estimate, bool) or self.cost_estimate is None:
            c = 0.0
        else:
            try:
                c = float(self.cost_estimate)
                c = max(0.0, c) if math.isfinite(c) else 0.0
            except (ValueError, TypeError, OverflowError):
                c = 0.0
        object.__setattr__(self, "tool_name", tn)
        object.__setattr__(self, "duration_ms", d)
        object.__setattr__(self, "success", self.success is True)
        object.__setattr__(self, "cache_hit", self.cache_hit is True)
        object.__setattr__(self, "coalesced", self.coalesced is True)
        object.__setattr__(self, "cost_estimate", c)

    def is_cached(self) -> bool:
        return self.cache_hit or self.coalesced

    def is_successful(self) -> bool:
        return self.success

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
    def __init__(self, cfg: dict[str, Any] | None = None, state_store: Any | None = None) -> None:
        self.state_store = state_store
        self._fast_model: str = (
            (cfg or {}).get("models", {}).get("fast_code", "qwen2.5-coder:1.5b")
        )
        self._known_flakes: set[str] = set()
        self._observations: list[ToolObservation] = []

    def mark_flake(self, test_id: str) -> None:
        clean = str(test_id or "").replace("\x00", "").strip()
        if clean:
            self._known_flakes.add(clean)

    def unmark_flake(self, test_id: str) -> bool:
        clean = str(test_id or "").replace("\x00", "").strip()
        if clean in self._known_flakes:
            self._known_flakes.remove(clean)
            return True
        return False

    def is_flake(self, test_id: str) -> bool:
        clean = str(test_id or "").replace("\x00", "").strip()
        return clean in self._known_flakes

    def flake_count(self) -> int:
        return len(self._known_flakes)

    def known_flakes(self) -> tuple[str, ...]:
        return tuple(sorted(self._known_flakes))

    def clear_flakes(self) -> None:
        self._known_flakes.clear()

    def observations_count(self) -> int:
        return len(self._observations)

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
                target=self._fast_model,
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
        affected = getattr(change, "affected_paths", ()) or ()

        for raw_path in affected:
            path = str(raw_path or "").replace("\x00", "").strip()
            if not path:
                continue
            normalized = path.replace("\\", "/")
            base = normalized.split("/")[-1]
            name = base.rsplit(".", 1)[0]
            path_key = normalized.casefold()
            test_file = base.casefold()
            is_existing_python_test = (
                (path_key.startswith("tests/") or "/tests/" in path_key)
                and test_file.startswith("test_")
                and test_file.endswith(".py")
            )
            test_target = normalized if is_existing_python_test else f"tests/test_{name}.py"
            if test_target not in selected:
                selected.append(test_target)

            # Check if any known flakes match this test target
            for flake in self._known_flakes:
                if flake.startswith(test_target) or test_target.startswith(flake.split("::")[0]):
                    if flake not in flaky:
                        flaky.append(flake)

        return TestSelection(
            selected_tests=tuple(selected),
            flaky_candidates=tuple(flaky),
            synthetic_passes=(),  # Invariant: NEVER manufacture a pass
        )
