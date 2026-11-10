"""Typed, side-effect-free contracts for optional Laya decisions.

These shape checks do not authorize evidence IDs. Callers must resolve evidence
through an authorized Hub path before constructing a request. This module does
not load Laya, emit telemetry, execute tools, or change Hub decisions.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class DecisionCategory(StrEnum):
    CONTEXT_SOURCE = "context_source"
    CONTEXT_BUDGET = "context_budget"
    MODEL_ROUTE = "model_route"
    REDUNDANT_STEP = "redundant_step"
    NEXT_STEP = "next_step"
    DELEGATION = "delegation"
    COMPLETION_GAP = "completion_gap"
    WATCHDOG = "watchdog"


class DecisionMode(StrEnum):
    SHADOW = "shadow"
    ADVISORY = "advisory"


class DecisionStatus(StrEnum):
    SUCCESS = "success"
    ABSTAIN = "abstain"
    SKIPPED = "skipped"
    ERROR = "error"


class ContextSourceFreshness(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"


class ContextSourceCoverage(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


_REQUEST_KEYS = frozenset({"category", "evidence_ids", "options"})
_RESULT_KEYS = frozenset({"success", "status", "suggestion", "reason_codes"})
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_OPTION = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_CONTEXT_SOURCE_TYPES = frozenset({"indexed", "artifact", "memory", "rag"})
_CATEGORY_OPTIONS = {
    DecisionCategory.CONTEXT_SOURCE: frozenset(
        {"indexed", "artifact", "memory", "rag", "more_evidence"}
    ),
    DecisionCategory.CONTEXT_BUDGET: frozenset({"compact", "standard", "expanded"}),
    DecisionCategory.MODEL_ROUTE: frozenset({"fast", "smart", "background", "vision", "generic"}),
    DecisionCategory.REDUNDANT_STEP: frozenset({"possible_duplicate", "validation_still_required"}),
    DecisionCategory.NEXT_STEP: frozenset(
        {"inspect_source", "run_test", "retrieve_evidence", "ask_human"}
    ),
    DecisionCategory.DELEGATION: frozenset({"review_only", "delegate_bounded", "no_delegation"}),
    DecisionCategory.COMPLETION_GAP: frozenset({"missing_verification", "resolve_blocker", "request_human_review"}),
    DecisionCategory.WATCHDOG: frozenset(
        {"recommend_continue", "recommend_stop", "recommend_human_review"}
    ),
}
_REASON_CODES = frozenset(
    {
        "EVIDENCE_SUFFICIENT",
        "INSUFFICIENT_EVIDENCE",
        "OPTION_UNSUPPORTED",
        "LOW_SIGNAL",
        "MODEL_UNAVAILABLE",
        "INVALID_OUTPUT",
        "TIMEOUT",
        "OVERLOADED",
        "DISABLED",
        "DUPLICATE",
        "CACHE_HIT",
        "STALE_EVIDENCE",
    }
)


def allowed_decision_options(category: DecisionCategory | str) -> frozenset[str]:
    """Return the closed label options for a known decision category."""
    try:
        normalized = DecisionCategory(category)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid decision category") from exc
    return _CATEGORY_OPTIONS[normalized]


def _identifier(value: Any, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def _string_list(value: Any, field: str, pattern: re.Pattern[str], *, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"invalid {field}")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not pattern.fullmatch(item):
            raise ValueError(f"invalid {field}")
        items.append(item)
    if len(set(items)) != len(items):
        raise ValueError(f"duplicate {field}")
    return tuple(items)


@dataclass(frozen=True)
class ContextSourceEvidence:
    """Minimal, text-free context-source codes for a future approved evaluation.

    This validates shape only. It does not prove that evidence IDs are
    authorized or current; the calling Hub path must resolve each ID before use.
    """

    gap_code: str
    source_codes: tuple[str, ...]
    freshness_codes: tuple[ContextSourceFreshness, ...]
    coverage_codes: tuple[ContextSourceCoverage, ...]
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.gap_code != "unresolved_evidence_gap":
            raise ValueError("invalid context source gap code")
        if not isinstance(self.source_codes, tuple) or not 2 <= len(self.source_codes) <= 4:
            raise ValueError("context source codes must contain two to four entries")
        if any(not isinstance(item, str) or item not in _CONTEXT_SOURCE_TYPES for item in self.source_codes):
            raise ValueError("invalid context source code")
        if len(set(self.source_codes)) != len(self.source_codes):
            raise ValueError("duplicate context source code")
        if not isinstance(self.freshness_codes, tuple) or len(self.freshness_codes) != len(self.source_codes):
            raise ValueError("context source freshness codes must align with source codes")
        if any(not isinstance(item, ContextSourceFreshness) for item in self.freshness_codes):
            raise ValueError("invalid context source freshness code")
        if not isinstance(self.coverage_codes, tuple) or len(self.coverage_codes) != len(self.source_codes):
            raise ValueError("context source coverage codes must align with source codes")
        if any(not isinstance(item, ContextSourceCoverage) for item in self.coverage_codes):
            raise ValueError("invalid context source coverage code")
        if not isinstance(self.evidence_ids, tuple) or len(self.evidence_ids) != len(self.source_codes):
            raise ValueError("context source evidence IDs must align with source codes")
        if any(not isinstance(item, str) or not _IDENTIFIER.fullmatch(item) for item in self.evidence_ids):
            raise ValueError("invalid context source evidence IDs")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("duplicate context source evidence ID")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ContextSourceEvidence":
        """Validate the approved code-only shape without inferring authorization."""
        fields = {"gap_code", "source_codes", "freshness_codes", "coverage_codes", "evidence_ids"}
        if type(value) is not dict or set(value) != fields:
            raise ValueError("context source evidence fields invalid")
        if value["gap_code"] != "unresolved_evidence_gap":
            raise ValueError("invalid context source gap code")
        source_codes = _string_list(value["source_codes"], "source_codes", _OPTION, maximum=4)
        if not 2 <= len(source_codes) <= 4 or any(item not in _CONTEXT_SOURCE_TYPES for item in source_codes):
            raise ValueError("invalid context source codes")
        raw_freshness = value["freshness_codes"]
        raw_coverage = value["coverage_codes"]
        if type(raw_freshness) is not list or len(raw_freshness) != len(source_codes):
            raise ValueError("context source freshness codes must align with source codes")
        if type(raw_coverage) is not list or len(raw_coverage) != len(source_codes):
            raise ValueError("context source coverage codes must align with source codes")
        try:
            freshness_codes = tuple(ContextSourceFreshness(item) for item in raw_freshness)
            coverage_codes = tuple(ContextSourceCoverage(item) for item in raw_coverage)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid context source status code") from exc
        evidence_ids = _string_list(value["evidence_ids"], "evidence_ids", _IDENTIFIER, maximum=4)
        if len(evidence_ids) != len(source_codes):
            raise ValueError("context source evidence IDs must align with source codes")
        return cls(
            gap_code=value["gap_code"],
            source_codes=source_codes,
            freshness_codes=freshness_codes,
            coverage_codes=coverage_codes,
            evidence_ids=evidence_ids,
        )

    @property
    def decision_options(self) -> tuple[str, ...]:
        """Return the supplied choices so unsafe selections remain measurable false positives."""
        return self.source_codes

    def model_input(self) -> dict[str, Any]:
        """Project only approved codes and opaque IDs; the caller must resolve IDs before use."""
        return {
            "gap_code": self.gap_code,
            "source_codes": list(self.source_codes),
            "freshness_codes": [item.value for item in self.freshness_codes],
            "coverage_codes": [item.value for item in self.coverage_codes],
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class DecisionRequest:
    decision_id: str
    mode: DecisionMode
    category: DecisionCategory
    repository_id: str
    task_id: str | None
    session_id: str | None
    evidence_ids: tuple[str, ...]
    options: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.mode, DecisionMode) or not isinstance(self.category, DecisionCategory):
            raise ValueError("mode and category must use their closed enums")
        _identifier(self.decision_id, "decision_id")
        _identifier(self.repository_id, "repository_id")
        _identifier(self.session_id, "session_id")
        _identifier(self.task_id, "task_id", optional=True)
        if not isinstance(self.evidence_ids, tuple) or len(self.evidence_ids) > 64:
            raise ValueError("invalid evidence_ids")
        for evidence_id in self.evidence_ids:
            _identifier(evidence_id, "evidence_id")
        if not isinstance(self.options, tuple) or not 1 <= len(self.options) <= 32:
            raise ValueError("invalid decision options")
        if any(not isinstance(option, str) or not _OPTION.fullmatch(option) for option in self.options):
            raise ValueError("invalid decision options")
        if len(set(self.options)) != len(self.options):
            raise ValueError("duplicate decision options")
        if any(option not in _CATEGORY_OPTIONS[self.category] for option in self.options):
            raise ValueError("unsupported decision option for category")

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        decision_id: str,
        mode: DecisionMode,
        repository_id: str,
        task_id: str | None,
        session_id: str,
    ) -> "DecisionRequest":
        """Build request from closed caller data and server-bound identity.

        Mode and identity are keyword-only trusted context. They are never
        accepted from the request mapping supplied by an MCP/API caller.
        """
        if not isinstance(value, Mapping) or set(value) != _REQUEST_KEYS:
            raise ValueError("invalid decision request fields")
        if not isinstance(mode, DecisionMode):
            raise ValueError("mode must come from the decision service")
        try:
            category = DecisionCategory(value["category"])
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid decision category") from exc
        repository_id = _identifier(repository_id, "repository_id")
        session_id = _identifier(session_id, "session_id")
        task_id = _identifier(task_id, "task_id", optional=True)
        decision_id = _identifier(decision_id, "decision_id")
        evidence_ids = _string_list(value["evidence_ids"], "evidence_ids", _IDENTIFIER, maximum=64)
        options = _string_list(value["options"], "options", _OPTION, maximum=32)
        if not options:
            raise ValueError("decision options must not be empty")
        if any(option not in _CATEGORY_OPTIONS[category] for option in options):
            raise ValueError("unsupported decision option for category")
        return cls(
            decision_id=decision_id,
            mode=mode,
            category=category,
            repository_id=repository_id,
            task_id=task_id,
            session_id=session_id,
            evidence_ids=evidence_ids,
            options=options,
        )


@dataclass(frozen=True)
class DecisionResult:
    request: DecisionRequest
    success: bool
    status: DecisionStatus
    suggestion: str | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request, DecisionRequest):
            raise ValueError("decision result requires a validated request")
        if type(self.success) is not bool or not isinstance(self.status, DecisionStatus):
            raise ValueError("invalid decision result status")
        if self.suggestion is not None and (
            not isinstance(self.suggestion, str) or self.suggestion not in self.request.options
        ):
            raise ValueError("suggestion is outside the permitted options")
        if not isinstance(self.reason_codes, tuple) or len(self.reason_codes) > 8:
            raise ValueError("invalid reason_codes")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("duplicate reason_codes")
        if any(
            not isinstance(code, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}\Z", code)
            or code not in _REASON_CODES
            for code in self.reason_codes
        ):
            raise ValueError("unknown reason code")
        if self.status is not DecisionStatus.SUCCESS and not self.reason_codes:
            raise ValueError("non-success result requires a reason code")
        expected_success = self.status in {DecisionStatus.SUCCESS, DecisionStatus.ABSTAIN}
        if self.success is not expected_success:
            raise ValueError("success does not match status")
        if (self.status is DecisionStatus.SUCCESS) != (self.suggestion is not None):
            raise ValueError("suggestion does not match status")

    @classmethod
    def from_mapping(cls, request: DecisionRequest, value: Mapping[str, Any]) -> "DecisionResult":
        if not isinstance(value, Mapping) or set(value) != _RESULT_KEYS:
            raise ValueError("invalid decision result fields")
        if type(value["success"]) is not bool:
            raise ValueError("success must be a boolean")
        try:
            status = DecisionStatus(value["status"])
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid decision status") from exc
        suggestion = value["suggestion"]
        if suggestion is not None and (not isinstance(suggestion, str) or suggestion not in request.options):
            raise ValueError("suggestion is outside the permitted options")
        reason_codes = _string_list(
            value["reason_codes"],
            "reason_codes",
            re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z"),
            maximum=8,
        )
        if any(code not in _REASON_CODES for code in reason_codes):
            raise ValueError("unknown reason code")
        if status is not DecisionStatus.SUCCESS and not reason_codes:
            raise ValueError("non-success result requires a reason code")
        expected_success = status in {DecisionStatus.SUCCESS, DecisionStatus.ABSTAIN}
        if value["success"] is not expected_success:
            raise ValueError("success does not match status")
        if (status is DecisionStatus.SUCCESS) != (suggestion is not None):
            raise ValueError("suggestion does not match status")
        if status in {DecisionStatus.ABSTAIN, DecisionStatus.SKIPPED, DecisionStatus.ERROR} and suggestion is not None:
            raise ValueError("non-success result cannot include a suggestion")
        return cls(
            request=request,
            success=expected_success,
            status=status,
            suggestion=suggestion,
            reason_codes=reason_codes,
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "decision_id": self.request.decision_id,
            "success": self.success,
            "mode": self.request.mode.value,
            "status": self.status.value,
            "category": self.request.category.value,
            "repository_id": self.request.repository_id,
            "task_id": self.request.task_id,
            "session_id": self.request.session_id,
            "suggestion": self.suggestion,
            "reason_codes": list(self.reason_codes),
            "evidence_ids": list(self.request.evidence_ids),
            "model_estimate": self.status in {DecisionStatus.SUCCESS, DecisionStatus.ABSTAIN},
            "uncertainty": (
                "UNCALIBRATED"
                if self.status in {DecisionStatus.SUCCESS, DecisionStatus.ABSTAIN}
                else "NOT_APPLICABLE"
            ),
            "execution_verification": "NOT_VERIFIED",
        }
