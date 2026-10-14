from __future__ import annotations

from .json_utils import dumps as json_dumps

import hashlib
import json
import math
import os
import re
import shlex
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from .agent_events import AgentEvent, AgentStateStore
from .sqlite_support import connect_sqlite, retry_busy


class VerificationStoreIntegrationError(RuntimeError):
    """Raised when the verification store cannot use an event/task transaction seam."""


VERIFICATION_RECEIPT_METADATA_SCHEMA = "verification_receipt_metadata.v1"


def criterion_evidence_type(criterion: str) -> str:
    text = str(criterion or "").replace("\x00", "").lower()
    if "benchmark" in text:
        return "benchmark"
    if any(
        re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", text)
        for marker in ("test", "tests", "pytest", "suite", "unit", "unittest", "integration", "regression", "regressions")
    ):
        return "test"
    return "source_review"


def classify_verification_command(command: str) -> str:
    """Return the evidence kind a command can support, defaulting conservatively."""
    text = str(command or "").replace("\x00", "").lower()
    try:
        tokens = shlex.split(text, posix=False)
    except ValueError:
        tokens = text.split()
    command_tokens = [Path(token.strip("\"'")).stem.lower() for token in tokens]
    if any(token in {"benchmark", "bench", "hyperfine", "pytest-benchmark"} for token in command_tokens):
        return "benchmark"
    test_tools = {
        "pytest", "py.test", "unittest", "ctest", "tox", "nox", "jest",
        "vitest", "mocha", "phpunit", "pester",
    }
    if any(token in test_tools for token in command_tokens):
        return "test"
    for index, token in enumerate(command_tokens[:-1]):
        if token in {"dotnet", "cargo", "go"} and command_tokens[index + 1] == "test":
            return "test"
        if token in {"npm", "pnpm", "yarn"}:
            following = command_tokens[index + 1 : index + 3]
            if following[:1] == ["test"] or following == ["run", "test"]:
                return "test"
    if any(
        command_tokens[index : index + 2] == ["-m", module]
        for index in range(len(command_tokens) - 1)
        for module in ("pytest", "unittest")
    ):
        return "test"
    return "source_review"


@dataclass(frozen=True)
class VerificationReceipt:
    receipt_id: str
    task_id: str
    criterion: str
    owner: str = ""
    change_intent_id: str = ""
    evidence_id: str = ""
    command_id: str = ""
    repository_revision: str = ""
    mutation_generation: int = 0
    evidence_type: str = "source_review"
    observed_at: float = 0.0
    expires_at: float | None = None
    passed: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "passed", self.passed is True)
        if isinstance(self.mutation_generation, bool) or not isinstance(self.mutation_generation, int) or self.mutation_generation < 0:
            raise ValueError("verification receipt mutation_generation must be a non-negative integer")
        rid = str(self.receipt_id or "").replace("\x00", "").strip()
        tid = str(self.task_id or "").replace("\x00", "").strip()
        crit = str(self.criterion or "").replace("\x00", "").strip()
        eid = str(self.evidence_id or "").replace("\x00", "").strip()
        cid = str(self.command_id or "").replace("\x00", "").strip()
        ci_id = str(self.change_intent_id or "").replace("\x00", "").strip()
        object.__setattr__(self, "receipt_id", rid)
        object.__setattr__(self, "task_id", tid)
        object.__setattr__(self, "criterion", crit)
        object.__setattr__(self, "evidence_id", eid)
        object.__setattr__(self, "command_id", cid)
        object.__setattr__(self, "change_intent_id", ci_id)
        object.__setattr__(self, "owner", str(self.owner or "").replace("\x00", "").strip())
        object.__setattr__(self, "repository_revision", str(self.repository_revision or "").replace("\x00", "").strip())
        evidence_type = str(self.evidence_type or "").replace("\x00", "").strip().lower()
        if evidence_type not in {"test", "benchmark", "source_review"}:
            raise ValueError("verification receipt has unsupported evidence_type")
        object.__setattr__(self, "evidence_type", evidence_type)
        if self.expires_at is not None:
            try:
                exp = float(self.expires_at)
                if not math.isfinite(exp):
                    exp = None
            except (ValueError, TypeError):
                exp = None
            object.__setattr__(self, "expires_at", exp)

    def is_expired(self, now: float) -> bool:
        return not self.is_fresh(now)

    def is_test(self) -> bool:
        return self.evidence_type == "test"

    def is_benchmark(self) -> bool:
        return self.evidence_type == "benchmark"

    def is_source_review(self) -> bool:
        return self.evidence_type == "source_review"

    @classmethod
    def create(
        cls,
        task_id: str,
        criterion: str,
        passed: bool = True,
        change_intent_id: str = "",
        evidence_id: str = "",
        command_id: str = "",
        repository_revision: str = "",
        owner: str = "",
        mutation_generation: int = 0,
        evidence_type: str | None = None,
        expires_at: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> VerificationReceipt:
        task_key = str(task_id or "").strip()
        criterion_text = str(criterion or "").strip()
        if not task_key:
            raise ValueError("verification receipt requires task_id")
        if not criterion_text:
            raise ValueError("verification receipt requires criterion")
        owner_text = str(owner or "").strip()
        passed_value = passed is True
        evidence_key = str(evidence_id or "").strip()
        command_key = str(command_id or "").strip()
        inferred_kind = criterion_evidence_type(criterion_text)
        evidence_kind = str(evidence_type or inferred_kind).strip().lower()
        if evidence_kind not in {"test", "benchmark", "source_review"}:
            raise ValueError("verification receipt has unsupported evidence_type")
        try:
            generation = int(mutation_generation)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("verification receipt requires valid mutation_generation") from exc
        if generation < 0:
            raise ValueError("verification receipt mutation_generation must be non-negative")
        if passed_value and not evidence_key:
            raise ValueError("passed verification receipt requires evidence_id")
        if passed_value and evidence_kind in {"test", "benchmark"} and not command_key:
            raise ValueError(f"passed {evidence_kind} verification receipt requires command_id")
        now = time.time()
        return cls(
            receipt_id=f"rcpt_{uuid.uuid4().hex[:12]}",
            task_id=task_key,
            criterion=criterion_text,
            owner=owner_text,
            change_intent_id=change_intent_id,
            evidence_id=evidence_key,
            command_id=command_key,
            repository_revision=repository_revision,
            mutation_generation=generation,
            evidence_type=evidence_kind,
            observed_at=now,
            expires_at=expires_at,
            passed=passed_value,
            details=dict(details or {}),
        )

    def is_fresh(self, now: float) -> bool:
        if not self.passed:
            return False
        if self.expires_at is None:
            return True
        return float(self.expires_at) >= float(now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "task_id": self.task_id,
            "criterion": self.criterion,
            "owner": self.owner,
            "change_intent_id": self.change_intent_id,
            "evidence_id": self.evidence_id,
            "command_id": self.command_id,
            "repository_revision": self.repository_revision,
            "mutation_generation": self.mutation_generation,
            "evidence_type": self.evidence_type,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "passed": self.passed,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> VerificationReceipt:
        if not isinstance(data, Mapping):
            raise TypeError("verification receipt data must be a mapping")
        passed = data.get("passed")
        if type(passed) is not bool:
            raise ValueError("verification receipt passed must be a boolean")
        mutation_generation = data.get("mutation_generation", 0)
        if isinstance(mutation_generation, bool) or not isinstance(mutation_generation, int) or mutation_generation < 0:
            raise ValueError("verification receipt mutation_generation must be a non-negative integer")
        details = data.get("details", {})
        if not isinstance(details, Mapping):
            raise ValueError("verification receipt details must be a mapping")
        return cls(
            receipt_id=str(data["receipt_id"]),
            task_id=str(data["task_id"]),
            criterion=str(data["criterion"]),
            owner=str(data.get("owner", "")),
            change_intent_id=str(data.get("change_intent_id", "")),
            evidence_id=str(data.get("evidence_id", "")),
            command_id=str(data.get("command_id", "")),
            repository_revision=str(data.get("repository_revision", "")),
            mutation_generation=mutation_generation,
            evidence_type=str(data.get("evidence_type", "source_review")),
            observed_at=float(data.get("observed_at", 0.0)),
            expires_at=float(data["expires_at"]) if data.get("expires_at") is not None else None,
            passed=passed,
            details=dict(details),
        )


_RECEIPT_METADATA_KEY = "__agent_os_receipt_metadata_v1__"


def _receipt_details_for_storage(receipt: VerificationReceipt) -> dict[str, Any]:
    if not (receipt.owner or receipt.mutation_generation is not None or receipt.evidence_type):
        return dict(receipt.details)
    return {
        _RECEIPT_METADATA_KEY: {
            "details": dict(receipt.details),
            "owner": receipt.owner,
            "mutation_generation": receipt.mutation_generation,
            "evidence_type": receipt.evidence_type,
        }
    }


def _receipt_details_from_storage(raw: str) -> tuple[dict[str, Any], str, int | None, str]:
    details = json.loads(raw) if raw else {}
    metadata = details.get(_RECEIPT_METADATA_KEY) if isinstance(details, Mapping) else None
    if not isinstance(metadata, Mapping):
        return dict(details or {}), "", None, ""
    generation = metadata.get("mutation_generation")
    return (
        dict(metadata.get("details") or {}),
        str(metadata.get("owner", "") or ""),
        generation,
        str(metadata.get("evidence_type", "") or ""),
    )


@dataclass(frozen=True)
class ChangeIntent:
    change_id: str
    task_id: str
    affected_paths: tuple[str, ...]
    affected_symbols: tuple[str, ...] = ()
    expected_impact: str = ""
    rollback_description: str = ""
    created_at: float = 0.0

    def __post_init__(self) -> None:
        cid = str(self.change_id or "").replace("\x00", "").strip()
        tid = str(self.task_id or "").replace("\x00", "").strip()
        ap = tuple(str(x).replace("\x00", "").strip() for x in (self.affected_paths or ()) if str(x).replace("\x00", "").strip())
        asym = tuple(str(x).replace("\x00", "").strip() for x in (self.affected_symbols or ()) if str(x).replace("\x00", "").strip())
        imp = str(self.expected_impact or "").replace("\x00", "").strip()
        rb = str(self.rollback_description or "").replace("\x00", "").strip()
        try:
            ca = float(self.created_at)
            ca = max(0.0, ca) if math.isfinite(ca) else 0.0
        except (ValueError, TypeError):
            ca = 0.0
        object.__setattr__(self, "change_id", cid)
        object.__setattr__(self, "task_id", tid)
        object.__setattr__(self, "affected_paths", ap)
        object.__setattr__(self, "affected_symbols", asym)
        object.__setattr__(self, "expected_impact", imp)
        object.__setattr__(self, "rollback_description", rb)
        object.__setattr__(self, "created_at", ca)

    @classmethod
    def create(
        cls,
        task_id: str,
        affected_paths: tuple[str, ...] | list[str],
        affected_symbols: tuple[str, ...] | list[str] = (),
        expected_impact: str = "",
        rollback_description: str = "",
    ) -> ChangeIntent:
        return cls(
            change_id=f"chg_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            affected_paths=tuple(affected_paths),
            affected_symbols=tuple(affected_symbols),
            expected_impact=expected_impact,
            rollback_description=rollback_description,
            created_at=time.time(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "task_id": self.task_id,
            "affected_paths": list(self.affected_paths),
            "affected_symbols": list(self.affected_symbols),
            "expected_impact": self.expected_impact,
            "rollback_description": self.rollback_description,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ChangeIntent:
        if not isinstance(data, Mapping):
            raise TypeError("change intent data must be a mapping")
        return cls(
            change_id=str(data["change_id"]),
            task_id=str(data["task_id"]),
            affected_paths=tuple(data.get("affected_paths") or ()),
            affected_symbols=tuple(data.get("affected_symbols") or ()),
            expected_impact=str(data.get("expected_impact", "")),
            rollback_description=str(data.get("rollback_description", "")),
            created_at=float(data.get("created_at", 0.0)),
        )


@dataclass(frozen=True)
class OutcomeRecord:
    outcome_id: str
    change_id: str = ""
    task_id: str = ""
    kind: str = "accepted"
    actor: str = "user"
    details: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def __post_init__(self) -> None:
        oid = str(self.outcome_id or "").replace("\x00", "").strip()
        cid = str(self.change_id or "").replace("\x00", "").strip()
        tid = str(self.task_id or "").replace("\x00", "").strip()
        knd = str(self.kind or "accepted").replace("\x00", "").strip().lower()
        act = str(self.actor or "user").replace("\x00", "").strip()
        det = dict(self.details) if isinstance(self.details, Mapping) else {}
        try:
            ca = float(self.created_at)
            ca = max(0.0, ca) if math.isfinite(ca) else 0.0
        except (ValueError, TypeError):
            ca = 0.0
        object.__setattr__(self, "outcome_id", oid)
        object.__setattr__(self, "change_id", cid)
        object.__setattr__(self, "task_id", tid)
        object.__setattr__(self, "kind", knd)
        object.__setattr__(self, "actor", act)
        object.__setattr__(self, "details", det)
        object.__setattr__(self, "created_at", ca)

    def is_accepted(self) -> bool:
        return self.kind == "accepted"

    def is_reverted(self) -> bool:
        return self.kind == "reverted"

    def is_corrected(self) -> bool:
        return self.kind == "corrected"

    def is_regressed(self) -> bool:
        return self.kind == "regressed"

    def is_rejected(self) -> bool:
        return self.kind == "rejected"

    @classmethod
    def reverted(
        cls,
        change_id: str,
        *,
        actor: str = "user",
        task_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> OutcomeRecord:
        return cls(
            outcome_id=f"outc_{uuid.uuid4().hex[:12]}",
            change_id=change_id,
            task_id=task_id,
            kind="reverted",
            actor=actor,
            details=dict(details or {}),
            created_at=time.time(),
        )

    @classmethod
    def accepted(
        cls,
        change_id: str,
        *,
        actor: str = "user",
        task_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> OutcomeRecord:
        return cls(
            outcome_id=f"outc_{uuid.uuid4().hex[:12]}",
            change_id=change_id,
            task_id=task_id,
            kind="accepted",
            actor=actor,
            details=dict(details or {}),
            created_at=time.time(),
        )

    @classmethod
    def corrected(
        cls,
        change_id: str,
        *,
        actor: str = "user",
        task_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> OutcomeRecord:
        return cls(
            outcome_id=f"outc_{uuid.uuid4().hex[:12]}",
            change_id=change_id,
            task_id=task_id,
            kind="corrected",
            actor=actor,
            details=dict(details or {}),
            created_at=time.time(),
        )

    @classmethod
    def regressed(
        cls,
        change_id: str,
        *,
        actor: str = "user",
        task_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> OutcomeRecord:
        return cls(
            outcome_id=f"outc_{uuid.uuid4().hex[:12]}",
            change_id=change_id,
            task_id=task_id,
            kind="regressed",
            actor=actor,
            details=dict(details or {}),
            created_at=time.time(),
        )

    @classmethod
    def rejected(
        cls,
        change_id: str,
        *,
        actor: str = "user",
        task_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> OutcomeRecord:
        return cls(
            outcome_id=f"outc_{uuid.uuid4().hex[:12]}",
            change_id=change_id,
            task_id=task_id,
            kind="rejected",
            actor=actor,
            details=dict(details or {}),
            created_at=time.time(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "change_id": self.change_id,
            "task_id": self.task_id,
            "kind": self.kind,
            "actor": self.actor,
            "details": dict(self.details),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> OutcomeRecord:
        if not isinstance(data, Mapping):
            raise TypeError("outcome record data must be a mapping")
        return cls(
            outcome_id=str(data["outcome_id"]),
            change_id=str(data.get("change_id", "")),
            task_id=str(data.get("task_id", "")),
            kind=str(data.get("kind", "accepted")),
            actor=str(data.get("actor", "user")),
            details=dict(data.get("details") or {}),
            created_at=float(data.get("created_at", 0.0)),
        )


@dataclass(frozen=True)
class CompletionResult:
    task_id: str
    complete: bool
    satisfied_criteria: tuple[str, ...]
    unsatisfied_criteria: tuple[str, ...]
    stale_criteria: tuple[str, ...]
    receipts: tuple[VerificationReceipt, ...]
    consistency: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        tid = str(self.task_id or "").replace("\x00", "").strip()
        sat = tuple(str(x).replace("\x00", "").strip() for x in (self.satisfied_criteria or ()) if str(x).replace("\x00", "").strip())
        unsat = tuple(str(x).replace("\x00", "").strip() for x in (self.unsatisfied_criteria or ()) if str(x).replace("\x00", "").strip())
        stale = tuple(str(x).replace("\x00", "").strip() for x in (self.stale_criteria or ()) if str(x).replace("\x00", "").strip())
        rcpts = tuple(self.receipts or ())
        cons = dict(self.consistency) if isinstance(self.consistency, Mapping) else {}
        object.__setattr__(self, "task_id", tid)
        object.__setattr__(self, "complete", self.complete is True)
        object.__setattr__(self, "satisfied_criteria", sat)
        object.__setattr__(self, "unsatisfied_criteria", unsat)
        object.__setattr__(self, "stale_criteria", stale)
        object.__setattr__(self, "receipts", rcpts)
        object.__setattr__(self, "consistency", cons)

    def is_complete(self) -> bool:
        return self.complete

    def has_receipts(self) -> bool:
        return bool(self.receipts)

    def receipt_count(self) -> int:
        return len(self.receipts)

    def satisfied_count(self) -> int:
        return len(self.satisfied_criteria)

    def unsatisfied_count(self) -> int:
        return len(self.unsatisfied_criteria)

    def stale_count(self) -> int:
        return len(self.stale_criteria)

    def all_criteria(self) -> tuple[str, ...]:
        return self.satisfied_criteria + self.unsatisfied_criteria + self.stale_criteria

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "task_id": self.task_id,
            "complete": self.complete,
            "satisfied_criteria": list(self.satisfied_criteria),
            "unsatisfied_criteria": list(self.unsatisfied_criteria),
            "stale_criteria": list(self.stale_criteria),
            "receipts": [r.to_dict() for r in self.receipts],
        }
        if self.consistency:
            payload["consistency"] = dict(self.consistency)
        return payload


def evaluate_completion_receipts(
    task_id: str,
    required_criteria: tuple[str, ...] | list[str],
    receipts: tuple[VerificationReceipt, ...] | list[VerificationReceipt],
    *,
    owner: str,
    repository_revision: str = "",
    mutation_generation: int = 0,
    mapped_receipt_ids: Mapping[str, str] | None = None,
    artifact_store: Any | None = None,
    require_repository_revision: bool = False,
    verification_rules: (
        bool | tuple[str, ...] | list[str] | Mapping[str, bool | tuple[str, ...]] | None
    ) = None,
    configured_criteria: tuple[str, ...] | list[str] | None = None,
    configured_commands: Mapping[str, Any] | None = None,
    configured_environment_sha256: Mapping[str, str] | None = None,
    project_config_digest: str = "",
    project_root: str | Path = "",
    command_execution_record_lookup: Any | None = None,
    trusted_tenant: str = "",
    trusted_repository_root: str | Path = "",
    require_execution_provenance: bool = False,
    now: float | None = None,
    evidence_store: Any | None = None,
) -> CompletionResult:
    """Apply shared receipt gates to durable tasks and work-order handoffs.

    Project-rule keys apply to matching task acceptance criteria. A ``True``
    value requires configured lint and test receipts; tuple values name exact
    configured receipt criteria.
    """
    criteria = tuple(str(item) for item in required_criteria if str(item).strip())
    active_verification_rules = False
    invalid_verification_rules = False
    unavailable_rule_criteria: set[str] = set()
    rule_criteria_list: list[str] = []
    if isinstance(verification_rules, Mapping):
        required_names = set(criteria)
        matching_rules = (
            value
            for key, value in verification_rules.items()
            if str(key).strip() in required_names
        )
        for rule in matching_rules:
            active_verification_rules = True
            if rule is True:
                rule_criteria_list.extend(("lint", "test"))
            elif isinstance(rule, (tuple, list)):
                normalized = tuple(str(item).strip() for item in rule if str(item).strip())
                if not normalized:
                    invalid_verification_rules = True
                rule_criteria_list.extend(normalized)
            else:
                invalid_verification_rules = True
    elif verification_rules is True:
        active_verification_rules = True
        rule_criteria_list.extend(("lint", "test"))
    elif verification_rules is False or verification_rules is None:
        pass
    elif isinstance(verification_rules, (tuple, list)):
        active_verification_rules = True
        normalized = tuple(str(item).strip() for item in verification_rules if str(item).strip())
        invalid_verification_rules = not normalized
        rule_criteria_list.extend(normalized)
    else:
        active_verification_rules = True
        invalid_verification_rules = True

    rule_criteria = tuple(dict.fromkeys(rule_criteria_list))
    if active_verification_rules:
        configured = {
            str(item).strip()
            for item in (configured_criteria or ())
            if str(item).strip()
        }
        unavailable_rule_criteria = set(rule_criteria).difference(configured)
        criteria = tuple(dict.fromkeys((*criteria, *rule_criteria)))

    current_time = float(time.time() if now is None else now)
    latest_by_criterion: dict[str, VerificationReceipt] = {}
    for receipt in receipts:
        previous = latest_by_criterion.get(receipt.criterion)
        if previous is None or receipt.observed_at > previous.observed_at:
            latest_by_criterion[receipt.criterion] = receipt

    satisfied: list[str] = []
    unsatisfied: list[str] = []
    stale: list[str] = []
    if invalid_verification_rules:
        unsatisfied.append("verification_rules")
    expected_owner = str(owner or "").strip()
    expected_revision = str(repository_revision or "").strip()
    expected_generation = int(mutation_generation)
    mappings = mapped_receipt_ids or {}

    for criterion in criteria:
        if criterion in unavailable_rule_criteria:
            unsatisfied.append(criterion)
            continue
        receipt = latest_by_criterion.get(criterion)
        if (
            receipt is None
            or receipt.task_id != task_id
            or receipt.criterion != criterion
            or not receipt.passed
            or not str(receipt.evidence_id or "").strip()
        ):
            unsatisfied.append(criterion)
        elif not expected_owner or receipt.owner != expected_owner:
            unsatisfied.append(criterion)
        elif active_verification_rules and (
            not expected_revision
            or str(getattr(receipt, "repository_revision", "") or "").strip() != expected_revision
        ):
            unsatisfied.append(criterion)
        elif mapped_receipt_ids is not None and mappings.get(criterion) != receipt.receipt_id:
            unsatisfied.append(criterion)
        elif not _receipt_evidence_matches(
            receipt,
            artifact_store,
            expected_owner=expected_owner,
            require_repository_revision=require_repository_revision,
            expected_project_command=(configured_commands or {}).get(criterion),
            expected_project_config_digest=(
                project_config_digest if criterion in (configured_commands or {}) else ""
            ),
            expected_project_environment_sha256=(configured_environment_sha256 or {}).get(criterion, ""),
            expected_project_root=project_root,
            command_execution_record_lookup=command_execution_record_lookup,
            trusted_tenant=trusted_tenant,
            trusted_repository_root=trusted_repository_root,
            require_execution_provenance=require_execution_provenance,
            evidence_store=evidence_store,
        ):
            unsatisfied.append(criterion)
        elif criterion_evidence_type(criterion) == "test" and (
            receipt.evidence_type != "test" or not str(receipt.command_id or "").strip()
        ):
            unsatisfied.append(criterion)
        elif active_verification_rules and criterion == "lint" and not str(receipt.command_id or "").strip():
            unsatisfied.append(criterion)
        elif criterion_evidence_type(criterion) == "benchmark" and (
            receipt.evidence_type != "benchmark" or not str(receipt.command_id or "").strip()
        ):
            unsatisfied.append(criterion)
        elif criterion_evidence_type(criterion) == "source_review" and (
            receipt.evidence_type != "source_review"
        ):
            unsatisfied.append(criterion)
        elif not receipt.is_fresh(current_time):
            stale.append(criterion)
        elif expected_revision and receipt.repository_revision != expected_revision:
            stale.append(criterion)
        elif receipt.mutation_generation != expected_generation:
            stale.append(criterion)
        else:
            satisfied.append(criterion)

    return CompletionResult(
        task_id=task_id,
        complete=(
            bool(criteria)
            and not invalid_verification_rules
            and len(satisfied) == len(criteria)
        ),
        satisfied_criteria=tuple(satisfied),
        unsatisfied_criteria=tuple(unsatisfied),
        stale_criteria=tuple(stale),
        receipts=tuple(latest_by_criterion.values()),
    )


def _receipt_evidence_matches(
    receipt: VerificationReceipt,
    artifact_store: Any | None,
    *,
    expected_owner: str,
    require_repository_revision: bool,
    expected_project_command: Any | None = None,
    expected_project_config_digest: str = "",
    expected_project_environment_sha256: str = "",
    expected_project_root: str | Path = "",
    command_execution_record_lookup: Any | None = None,
    trusted_tenant: str = "",
    trusted_repository_root: str | Path = "",
    require_execution_provenance: bool = False,
    evidence_store: Any | None = None,
) -> bool:
    """Re-read and bind positive receipts to complete, tenant-scoped proof artifacts."""
    if artifact_store is None or not expected_owner or receipt.owner != expected_owner:
        return False
    if require_repository_revision and not receipt.repository_revision.strip():
        return False
    if receipt.evidence_type in {"test", "benchmark"} or (
        receipt.evidence_type == "source_review" and receipt.command_id.strip()
    ):
        if not receipt.repository_revision.strip():
            return False
        expected_kind = "command_verification"
    else:
        expected_kind = "source_review"
    try:
        artifact = artifact_store.get(
            receipt.evidence_id,
            max_chars=50_000,
            tenant=expected_owner,
        )
    except Exception:
        return False
    if (
        not isinstance(artifact, Mapping)
        or artifact.get("success") is not True
        or artifact.get("artifact_id") != receipt.evidence_id
        or artifact.get("kind") != expected_kind
        or artifact.get("next_offset") is not None
        or not isinstance(artifact.get("text"), str)
    ):
        return False
    try:
        proof = json.loads(artifact["text"])
    except (TypeError, ValueError):
        return False
    if not isinstance(proof, Mapping) or proof.get("passed") is not True:
        return False
    if (
        proof.get("task_id") != receipt.task_id
            or proof.get("owner") != expected_owner
            or proof.get("repository_revision") != receipt.repository_revision
            or proof.get("mutation_generation") != receipt.mutation_generation
    ):
        return False
    if expected_kind == "command_verification":
        command_classification = proof.get("command_classification")
        if command_classification is not None and command_classification != receipt.evidence_type:
            return False
        if expected_project_config_digest:
            command_digest = proof.get("command_sha256")
            actual_command = proof.get("command")
            actual_tokens: list[str] | None = None
            environment_digest = proof.get("project_environment_sha256")
            configured_digest = proof.get("configured_command_sha256")
            arguments_digest = proof.get("caller_arguments_sha256")
            broker_attests_command = bool(
                require_execution_provenance
                and receipt.command_id
                and callable(command_execution_record_lookup)
            )
            if (
                command_classification != receipt.evidence_type
                or
                proof.get("project_alias") != receipt.criterion
                or proof.get("project_config_digest") != expected_project_config_digest
                or not isinstance(command_digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", command_digest) is None
                or (actual_command is None and not broker_attests_command)
                or (actual_command is not None and not isinstance(actual_command, str))
                or (
                    isinstance(actual_command, str)
                    and hashlib.sha256(actual_command.encode("utf-8")).hexdigest() != command_digest
                )
                or not isinstance(expected_project_environment_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected_project_environment_sha256) is None
                or environment_digest != expected_project_environment_sha256
                or not isinstance(configured_digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", configured_digest) is None
                or not isinstance(arguments_digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", arguments_digest) is None
            ):
                return False
            if isinstance(expected_project_command, str):
                expected_command_digest = hashlib.sha256(
                    expected_project_command.encode("utf-8")
                ).hexdigest()
                if (
                    command_digest != expected_command_digest
                    or configured_digest != expected_command_digest
                    or arguments_digest != hashlib.sha256(b"[]").hexdigest()
                ):
                    return False
                if actual_command is not None or not broker_attests_command:
                    if actual_command != expected_project_command:
                        return False
                    try:
                        actual_tokens = shlex.split(actual_command, posix=(os.name != "nt"))
                    except ValueError:
                        return False
            elif expected_project_command is not None:
                argv = getattr(expected_project_command, "argv", None)
                if not isinstance(argv, (tuple, list)) or not expected_project_root:
                    return False
                configured_text = json.dumps(
                    {
                        "argv": list(argv),
                        "cwd": str(Path(expected_project_root).expanduser().resolve(strict=False)),
                        "shell": False,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if configured_digest != hashlib.sha256(configured_text.encode("utf-8")).hexdigest():
                    return False
                if isinstance(actual_command, str):
                    try:
                        actual_tokens = [
                            token.strip("\"'")
                            for token in shlex.split(actual_command, posix=(os.name != "nt"))
                        ]
                    except ValueError:
                        return False
                    configured_tokens = [str(token) for token in argv]
                    if actual_tokens[: len(configured_tokens)] != configured_tokens:
                        return False
                    caller_arguments = actual_tokens[len(configured_tokens) :]
                    if (
                        len(caller_arguments) > 32
                        or any(not isinstance(token, str) or len(token) > 4096 or "\x00" in token for token in caller_arguments)
                        or any(token in {";", "&&", "||", "|", ">", "<"} for token in caller_arguments)
                        or arguments_digest
                        != hashlib.sha256(
                            json.dumps(caller_arguments, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                        ).hexdigest()
                    ):
                        return False
                elif not broker_attests_command:
                    return False
            else:
                return False
            if actual_tokens is not None:
                lowered_tokens = [token.lower() for token in actual_tokens]
                no_execution_options = {
                    "-h", "--help", "--version", "-version",
                    "--collect-only", "--co", "--fixtures", "--fixtures-per-test",
                    "--list-tests", "--dry-run",
                }
                if any(
                    token in no_execution_options
                    or token.startswith(("--help=", "--version="))
                    for token in lowered_tokens
                ):
                    return False
                if classify_verification_command(actual_command) != receipt.evidence_type:
                    return False
            binding_fields = {
                "project_alias": receipt.criterion,
                "project_config_digest": expected_project_config_digest,
                "configured_command_sha256": configured_digest,
                "caller_arguments_sha256": arguments_digest,
                "command_sha256": command_digest,
                "project_environment_sha256": environment_digest,
            }
            expected_binding = hashlib.sha256(
                json.dumps(binding_fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if proof.get("project_execution_binding_sha256") != expected_binding:
                return False
        if require_execution_provenance and receipt.command_id:
            if (
                not callable(command_execution_record_lookup)
                or not trusted_tenant
                or not trusted_repository_root
            ):
                return False
            try:
                canonical_root = str(
                    Path(trusted_repository_root).expanduser().resolve(strict=False)
                )
                execution_record = command_execution_record_lookup(
                    receipt.command_id,
                    tenant=trusted_tenant,
                    task_id=receipt.task_id,
                    repository_root=canonical_root,
                )
            except Exception:
                return False
            if not isinstance(execution_record, Mapping):
                return False
            receipt_sha256 = hashlib.sha256(
                json.dumps(
                    receipt.to_dict(), sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            root_sha256 = hashlib.sha256(canonical_root.encode("utf-8")).hexdigest()
            project_fields = (
                "project_alias",
                "project_config_digest",
                "project_environment_sha256",
                "project_execution_binding_sha256",
            )
            if (
                execution_record.get("schema") != "command_execution_record.v1"
                or execution_record.get("command_id") != receipt.command_id
                or execution_record.get("task_id") != receipt.task_id
                or execution_record.get("owner") != expected_owner
                or execution_record.get("criterion") != receipt.criterion
                or execution_record.get("evidence_id") != receipt.evidence_id
                or execution_record.get("receipt_sha256") != receipt_sha256
                or execution_record.get("command_sha256") != proof.get("command_sha256")
                or execution_record.get("evidence_type") != receipt.evidence_type
                or execution_record.get("repository_root") != canonical_root
                or execution_record.get("repository_root_sha256") != root_sha256
                or execution_record.get("repository_revision") != receipt.repository_revision
                or execution_record.get("mutation_generation") != receipt.mutation_generation
                or execution_record.get("configured_command_sha256", "") != proof.get("configured_command_sha256", "")
                or execution_record.get("caller_arguments_sha256", "") != proof.get("caller_arguments_sha256", "")
                or type(execution_record.get("exit_code")) is not int
                or execution_record.get("exit_code") != 0
                or execution_record.get("cached") is not False
                or proof.get("cached") is not False
                or any(
                    execution_record.get(name, "") != proof.get(name, "")
                    for name in project_fields
                )
            ):
                return False
        result = proof.get("result")
        return bool(
            proof.get("kind") == "work_command_verification"
            and proof.get("criterion") == receipt.criterion
            and proof.get("command_id") == receipt.command_id
            and bool(receipt.command_id)
            and type(proof.get("exit_code")) is int
            and proof.get("exit_code") == 0
            and isinstance(result, Mapping)
            and result.get("success") is True
            and type(result.get("exit_code")) is int
            and result.get("exit_code") == 0
        )
    criteria = proof.get("criteria")
    return bool(
        proof.get("kind") == "work_source_review"
        and isinstance(criteria, list)
        and all(isinstance(item, str) for item in criteria)
        and receipt.criterion in criteria
    )


class VerificationStore:
    def __init__(
        self,
        state_store: AgentStateStore,
        *,
        task_store: Any | None = None,
        artifact_store: Any | None = None,
        evidence_store: Any | None = None,
    ) -> None:
        self.state_store = state_store
        self.task_store = task_store
        self.artifact_store = artifact_store
        self.evidence_store = evidence_store
        self.command_execution_record_lookup: Any | None = None
        self.require_execution_provenance = False
        if task_store is not None:
            set_verification_store = getattr(task_store, "set_verification_store", None)
            if callable(set_verification_store):
                set_verification_store(self)
            else:
                task_store.verification_store = self
        self._lock = threading.RLock()
        self._initialized = False
        self._init_tables()
        self._reconcile_task_outbox(raise_on_error=False)

    def set_command_execution_record_lookup(self, lookup: Any | None) -> None:
        """Install the trusted CommandBroker scope-checking provenance lookup."""
        self.command_execution_record_lookup = lookup if callable(lookup) else None
        self.require_execution_provenance = True

    def _init_tables(self) -> None:
        if self._initialized or not self.state_store.enabled:
            return
        with self._lock:
            if self._initialized or not self.state_store.enabled:
                return
            self.state_store._ensure_schema()
            def _setup() -> None:
                con = connect_sqlite(self.state_store.db_path)
                try:
                    from .sqlite_support import validate_durable_schema

                    validate_durable_schema(
                        con,
                        self.state_store.db_path,
                        {
                            "agent_verification_receipts": [
                                ("receipt_id", "TEXT", 0, 1), ("task_id", "TEXT", 1, 0),
                                ("criterion", "TEXT", 1, 0), ("change_intent_id", "TEXT", 1, 0),
                                ("evidence_id", "TEXT", 1, 0), ("command_id", "TEXT", 1, 0),
                                ("repository_revision", "TEXT", 1, 0), ("observed_at", "REAL", 1, 0),
                                ("expires_at", "REAL", 0, 0), ("passed", "INTEGER", 1, 0),
                                ("details", "TEXT", 1, 0),
                            ],
                            "agent_change_intents": [
                                ("change_id", "TEXT", 0, 1), ("task_id", "TEXT", 1, 0),
                                ("affected_paths", "TEXT", 1, 0), ("affected_symbols", "TEXT", 1, 0),
                                ("expected_impact", "TEXT", 1, 0),
                                ("rollback_description", "TEXT", 1, 0), ("created_at", "REAL", 1, 0),
                            ],
                            "agent_outcomes": [
                                ("outcome_id", "TEXT", 0, 1), ("change_id", "TEXT", 1, 0),
                                ("task_id", "TEXT", 1, 0), ("kind", "TEXT", 1, 0),
                                ("actor", "TEXT", 1, 0), ("details", "TEXT", 1, 0),
                                ("created_at", "REAL", 1, 0),
                            ],
                        },
                        complete_groups=(
                            ("agent_verification_receipts", "agent_change_intents", "agent_outcomes"),
                        ),
                        required_if_event_kinds={
                            "agent_verification_receipts": ("verification.%",),
                            "agent_change_intents": ("change.%",),
                            "agent_outcomes": ("outcome.%",),
                        },
                    )
                    con.execute("BEGIN IMMEDIATE")
                    with con:
                        con.execute(
                            """
                            CREATE TABLE IF NOT EXISTS agent_verification_receipts (
                                receipt_id TEXT PRIMARY KEY,
                                task_id TEXT NOT NULL,
                                criterion TEXT NOT NULL,
                                change_intent_id TEXT NOT NULL,
                                evidence_id TEXT NOT NULL,
                                command_id TEXT NOT NULL,
                                repository_revision TEXT NOT NULL,
                                observed_at REAL NOT NULL,
                                expires_at REAL,
                                passed INTEGER NOT NULL,
                                details TEXT NOT NULL
                            );
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_verif_task
                            ON agent_verification_receipts (task_id, criterion, observed_at DESC);
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_verif_task_observed
                            ON agent_verification_receipts (task_id, observed_at DESC);
                            """
                        )
                        con.execute(
                            """
                            CREATE TABLE IF NOT EXISTS agent_verification_task_outbox (
                                receipt_id TEXT PRIMARY KEY,
                                task_id TEXT NOT NULL,
                                criterion TEXT NOT NULL,
                                status TEXT NOT NULL DEFAULT 'pending',
                                created_at REAL NOT NULL,
                                completed_at REAL
                            );
                            """
                        )
                        con.execute(
                            "CREATE INDEX IF NOT EXISTS idx_agent_verif_task_outbox_pending "
                            "ON agent_verification_task_outbox(status, created_at)"
                        )
                        con.execute(
                            """
                            CREATE TABLE IF NOT EXISTS agent_change_intents (
                                change_id TEXT PRIMARY KEY,
                                task_id TEXT NOT NULL,
                                affected_paths TEXT NOT NULL,
                                affected_symbols TEXT NOT NULL,
                                expected_impact TEXT NOT NULL,
                                rollback_description TEXT NOT NULL,
                                created_at REAL NOT NULL
                            );
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_change_task
                            ON agent_change_intents (task_id);
                            """
                        )
                        con.execute(
                            """
                            CREATE TABLE IF NOT EXISTS agent_outcomes (
                                outcome_id TEXT PRIMARY KEY,
                                change_id TEXT NOT NULL,
                                task_id TEXT NOT NULL,
                                kind TEXT NOT NULL,
                                actor TEXT NOT NULL,
                                details TEXT NOT NULL,
                                created_at REAL NOT NULL
                            );
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_outcomes_task
                            ON agent_outcomes (task_id);
                            """
                        )
                        con.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_agent_outcomes_change
                            ON agent_outcomes (change_id);
                            """
                        )
                finally:
                    con.close()
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    def _same_task_database(self) -> bool:
        return bool(
            self.task_store is not None
            and self.task_store.state_store.db_path.resolve()
            == self.state_store.db_path.resolve()
        )
    def _reconcile_task_outbox(
        self, *, receipt_id: str = "", raise_on_error: bool = False
    ) -> int:
        if not self.state_store.enabled or self.task_store is None:
            return 0
        with self._lock:
            def _pending() -> list[tuple[str, str, str]]:
                with closing(connect_sqlite(self.state_store.db_path)) as con:
                    if receipt_id:
                        rows = con.execute(
                            "SELECT receipt_id, task_id, criterion "
                            "FROM agent_verification_task_outbox "
                            "WHERE status = 'pending' AND receipt_id = ? ORDER BY created_at",
                            (receipt_id,),
                        ).fetchall()
                    else:
                        rows = con.execute(
                            "SELECT receipt_id, task_id, criterion "
                            "FROM agent_verification_task_outbox "
                            "WHERE status = 'pending' ORDER BY created_at"
                        ).fetchall()
                    return [(str(row[0]), str(row[1]), str(row[2])) for row in rows]

            rows = retry_busy(_pending, retries=5, base_delay_seconds=0.02)
            completed = 0
            for pending_receipt_id, task_id, criterion in rows:
                try:
                    self.task_store.add_verification_receipt(
                        task_id, criterion, pending_receipt_id
                    )

                    def _mark_complete() -> int:
                        con = connect_sqlite(
                            self.state_store.db_path,
                            isolation_level=None,
                            timeout_seconds=0.25,
                        )
                        try:
                            con.execute("BEGIN IMMEDIATE")
                            cur = con.execute(
                                "UPDATE agent_verification_task_outbox "
                                "SET status = 'completed', completed_at = ? "
                                "WHERE receipt_id = ? AND status = 'pending'",
                                (time.time(), pending_receipt_id),
                            )
                            con.execute("COMMIT")
                            return int(cur.rowcount)
                        except Exception:
                            try:
                                con.execute("ROLLBACK")
                            except Exception:
                                pass
                            raise
                        finally:
                            con.close()

                    completed += retry_busy(
                        _mark_complete, retries=5, base_delay_seconds=0.02
                    )
                except Exception:
                    if raise_on_error:
                        raise
            return completed
    def record_in_transaction(
        self,
        con: Any,
        receipt: VerificationReceipt,
        *,
        event: AgentEvent | None = None,
        update_task: bool = True,
    ) -> list[AgentEvent]:
        """Write receipt event/projection and optional same-store task projection atomically."""
        if not self.state_store.enabled:
            raise RuntimeError("verification storage is disabled")
        if not str(receipt.task_id or "").strip():
            raise ValueError("verification receipt requires task_id")
        if not str(receipt.criterion or "").strip():
            raise ValueError("verification receipt requires criterion")
        if receipt.passed and not str(receipt.evidence_id or "").strip():
            raise ValueError("passed verification receipt requires evidence_id")
        if receipt.passed and self.artifact_store is not None and not _receipt_evidence_matches(
            receipt,
            self.artifact_store,
            expected_owner=receipt.owner,
            require_repository_revision=bool(receipt.repository_revision),
            evidence_store=self.evidence_store,
        ):
            raise ValueError("passed verification receipt requires matching trusted evidence")
        if update_task and self.task_store is not None and not self._same_task_database():
            raise ValueError("transactional task receipt projection requires a shared database")
        stored_details = dict(receipt.details)
        stored_details["_verification_receipt"] = {
            "schema": VERIFICATION_RECEIPT_METADATA_SCHEMA,
            "owner": receipt.owner,
            "mutation_generation": receipt.mutation_generation,
            "evidence_type": receipt.evidence_type,
        }
        stored_details_json = json_dumps(stored_details)
        normalized_details = json.loads(stored_details_json)
        existing = con.execute(
            """
            SELECT task_id, criterion, change_intent_id, evidence_id,
                   command_id, repository_revision, observed_at, expires_at,
                   passed, details
            FROM agent_verification_receipts
            WHERE receipt_id = ?
            """,
            (receipt.receipt_id,),
        ).fetchone()
        if existing is not None:
            try:
                existing_details = json.loads(existing[9] or "{}")
            except (TypeError, ValueError):
                existing_details = None
            existing_values = tuple(existing)
            existing_content = existing_values[:8] + (bool(existing_values[8]), existing_details)
            incoming_content = (
                receipt.task_id,
                receipt.criterion,
                receipt.change_intent_id,
                receipt.evidence_id,
                receipt.command_id,
                receipt.repository_revision,
                receipt.observed_at,
                receipt.expires_at,
                bool(receipt.passed),
                normalized_details,
            )
            if existing_content != incoming_content:
                raise ValueError("verification receipt ID reused with conflicting content")
        event = event or AgentEvent.create(
            stream_id=f"verification:{receipt.task_id}",
            kind="verification.receipt_recorded",
            payload=receipt.to_dict(),
            idempotency_key=f"rcpt_{receipt.receipt_id}",
            actor=receipt.owner or "verifier",
        )
        # Store rows round-trip through JSON; normalize tuples and other JSON
        # containers before the ordered publisher verifies the committed event.
        event = replace(event, payload=json.loads(json_dumps(event.payload)))
        append_in_transaction = getattr(self.state_store, "append_in_transaction", None)
        if not callable(append_in_transaction):
            raise VerificationStoreIntegrationError(
                "state store has no public event append transaction API"
            )
        persisted = append_in_transaction(con, event, strict_idempotency=True)
        if persisted.error or persisted.event is None:
            raise RuntimeError(persisted.error or "verification event could not be stored")
        con.execute(
            """
            INSERT INTO agent_verification_receipts (
                receipt_id, task_id, criterion, change_intent_id, evidence_id,
                command_id, repository_revision, observed_at, expires_at,
                passed, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(receipt_id) DO UPDATE SET
                expires_at = excluded.expires_at,
                passed = excluded.passed,
                details = excluded.details
            """,
            (
                receipt.receipt_id, receipt.task_id, receipt.criterion,
                receipt.change_intent_id, receipt.evidence_id, receipt.command_id,
                receipt.repository_revision, receipt.observed_at, receipt.expires_at,
                1 if receipt.passed else 0, stored_details_json,
            ),
        )
        published: list[AgentEvent] = []
        if not persisted.duplicate:
            published.append(persisted.event)
        if update_task and self.task_store is not None and receipt.passed:
            add_receipt_in_transaction = getattr(
                self.task_store, "add_verification_receipt_in_transaction", None
            )
            if callable(add_receipt_in_transaction):
                task_state, task_event = add_receipt_in_transaction(
                    con, receipt.task_id, receipt.criterion, receipt.receipt_id
                )
            else:
                raise VerificationStoreIntegrationError(
                    "task store has no public verification receipt transaction API"
                )
            if task_state is not None and task_event is not None:
                published.append(
                    replace(task_event, payload=json.loads(json_dumps(task_event.payload)))
                )
        return published

    def record(
        self, receipt: VerificationReceipt, *, update_task: bool = True
    ) -> VerificationReceipt:
        if not self.state_store.enabled:
            return receipt
        if update_task and not receipt.owner and self.task_store is not None:
            task = self.task_store.get(receipt.task_id)
            if task is not None and task.owner:
                receipt = replace(receipt, owner=task.owner)
        if not str(receipt.task_id or "").strip():
            raise ValueError("verification receipt requires task_id")
        if not str(receipt.criterion or "").strip():
            raise ValueError("verification receipt requires criterion")
        if receipt.passed and not str(receipt.evidence_id or "").strip():
            raise ValueError("passed verification receipt requires evidence_id")
        if receipt.passed and self.artifact_store is not None and not _receipt_evidence_matches(
            receipt,
            self.artifact_store,
            expected_owner=receipt.owner,
            require_repository_revision=bool(receipt.repository_revision),
            evidence_store=self.evidence_store,
        ):
            raise ValueError("passed verification receipt requires matching trusted evidence")
        self._init_tables()
        self._reconcile_task_outbox(raise_on_error=False)
        event = AgentEvent.create(
            stream_id=f"verification:{receipt.task_id}",
            kind="verification.receipt_recorded",
            payload=receipt.to_dict(),
            idempotency_key=f"rcpt_{receipt.receipt_id}",
            actor=receipt.owner or "verifier",
        )
        same_task_database = bool(update_task and self._same_task_database())

        def _save_transaction(con: Any) -> list[AgentEvent]:
            try:
                con.execute("BEGIN IMMEDIATE")
                published = self.record_in_transaction(
                    con, receipt, event=event, update_task=same_task_database
                )
                if update_task and self.task_store is not None and receipt.passed and not same_task_database:
                    con.execute(
                        "INSERT INTO agent_verification_task_outbox "
                        "(receipt_id, task_id, criterion, status, created_at) "
                        "VALUES (?, ?, ?, 'pending', ?) "
                        "ON CONFLICT(receipt_id) DO NOTHING",
                        (receipt.receipt_id, receipt.task_id, receipt.criterion, time.time()),
                    )
                con.execute("COMMIT")
                return published
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise

        def _do_save() -> list[AgentEvent]:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                ordered_publication = getattr(
                    self.state_store, "ordered_event_publication", None
                )
                if not callable(ordered_publication):
                    raise VerificationStoreIntegrationError(
                        "state store has no ordered event publication API"
                    )
                with ordered_publication(con) as publish_committed:
                    published_events = retry_busy(
                        lambda: _save_transaction(con),
                        retries=5,
                        base_delay_seconds=0.02,
                    )
                    publish_committed(published_events)
                    return published_events
            finally:
                con.close()

        _do_save()

        if update_task and self.task_store is not None and receipt.passed and not same_task_database:
            try:
                self._reconcile_task_outbox(receipt_id=receipt.receipt_id, raise_on_error=True)
            except Exception as exc:
                raise RuntimeError(
                    f"verification receipt persisted; task receipt projection reconciliation required: {exc}"
                ) from exc

        return receipt

    def record_change(self, change: ChangeIntent) -> ChangeIntent:
        if not self.state_store.enabled:
            return change
        self._init_tables()
        event = AgentEvent.create(
            stream_id=f"change:{change.task_id}",
            kind="change.intended",
            payload=change.to_dict(),
            idempotency_key=f"chg_{change.change_id}",
            actor="agent",
        )
        expected = (
            change.task_id,
            json_dumps(list(change.affected_paths)),
            json_dumps(list(change.affected_symbols)),
            change.expected_impact,
            change.rollback_description,
            change.created_at,
        )
        def _do_save(con: Any) -> list[AgentEvent]:
            published: list[AgentEvent] = []
            try:
                con.execute("BEGIN IMMEDIATE")
                appended = self.state_store.append_in_transaction(
                    con, event, strict_idempotency=True
                )
                if appended.error or appended.event is None:
                    raise RuntimeError(appended.error or "change intent append returned no persisted event")
                if not appended.duplicate and appended.event:
                    published.append(appended.event)
                con.execute(
                    """
                    INSERT OR IGNORE INTO agent_change_intents (
                        change_id, task_id, affected_paths, affected_symbols,
                        expected_impact, rollback_description, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        change.change_id,
                        change.task_id,
                        json_dumps(list(change.affected_paths)),
                        json_dumps(list(change.affected_symbols)),
                        change.expected_impact,
                        change.rollback_description,
                        change.created_at,
                    ),
                )
                saved = con.execute(
                    "SELECT task_id, affected_paths, affected_symbols, expected_impact, rollback_description, created_at "
                    "FROM agent_change_intents WHERE change_id = ?",
                    (change.change_id,),
                ).fetchone()
                if not saved or tuple(saved) != expected:
                    raise ValueError("change_id already belongs to different change intent")
                con.execute("COMMIT")
                return published
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        con = connect_sqlite(self.state_store.db_path, isolation_level=None)
        try:
            with self.state_store.ordered_event_publication(con) as publish_committed:
                published = retry_busy(
                    lambda: _do_save(con), retries=5, base_delay_seconds=0.02
                )
                publish_committed(published)
        finally:
            con.close()
        if self.task_store is not None and change.task_id:
            try:
                task = self.task_store.get(change.task_id)
                if task is not None:
                    current_sd = dict(task.checkpoint.state_data or {})
                    gen = int(current_sd.get("mutation_generation", 0) or 0) + 1
                    current_sd["mutation_generation"] = gen
                    affected = list(dict.fromkeys(list(task.checkpoint.affected_paths or ()) + list(change.affected_paths or ())))
                    from .agent_tasks import TaskCheckpoint

                    new_chk = TaskCheckpoint(
                        phase=task.checkpoint.phase,
                        next_action=task.checkpoint.next_action,
                        affected_paths=tuple(affected),
                        evidence_ids=task.checkpoint.evidence_ids,
                        state_data=current_sd,
                    )
                    self.task_store.checkpoint(change.task_id, new_chk, actor="agent", idempotency_key=f"chg_gen_{change.change_id}")
            except KeyError:
                pass
        return change

    def record_outcome(self, outcome: OutcomeRecord) -> OutcomeRecord:
        if not self.state_store.enabled:
            return outcome
        self._init_tables()
        event = AgentEvent.create(
            stream_id=f"outcome:{outcome.change_id or outcome.task_id or 'global'}",
            kind="outcome.recorded",
            payload=outcome.to_dict(),
            idempotency_key=f"outc_{outcome.outcome_id}",
            actor=outcome.actor,
        )
        expected = (
            outcome.change_id,
            outcome.task_id,
            outcome.kind,
            outcome.actor,
            json_dumps(outcome.details),
            outcome.created_at,
        )
        def _do_save(con: Any) -> list[AgentEvent]:
            published: list[AgentEvent] = []
            try:
                con.execute("BEGIN IMMEDIATE")
                appended = self.state_store.append_in_transaction(
                    con, event, strict_idempotency=True
                )
                if appended.error or appended.event is None:
                    raise RuntimeError(appended.error or "verification outcome append returned no persisted event")
                if not appended.duplicate and appended.event:
                    published.append(appended.event)
                con.execute(
                    """
                    INSERT OR IGNORE INTO agent_outcomes (
                        outcome_id, change_id, task_id, kind, actor, details, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        outcome.outcome_id,
                        outcome.change_id,
                        outcome.task_id,
                        outcome.kind,
                        outcome.actor,
                        json_dumps(outcome.details),
                        outcome.created_at,
                    ),
                )
                saved = con.execute(
                    "SELECT change_id, task_id, kind, actor, details, created_at "
                    "FROM agent_outcomes WHERE outcome_id = ?",
                    (outcome.outcome_id,),
                ).fetchone()
                if not saved or tuple(saved) != expected:
                    raise ValueError("outcome_id already belongs to different outcome")
                con.execute("COMMIT")
                return published
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        con = connect_sqlite(self.state_store.db_path, isolation_level=None)
        try:
            with self.state_store.ordered_event_publication(con) as publish_committed:
                published = retry_busy(
                    lambda: _do_save(con), retries=5, base_delay_seconds=0.02
                )
                publish_committed(published)
        finally:
            con.close()
        return outcome

    def completion(
        self,
        task_id: str,
        now: float | None = None,
        *,
        include_consistency: bool = False,
        consistency_guard: Any | None = None,
        repository_revision: str = "",
        current_revision: str = "",
        current_mutation_generation: int | None = None,
        verification_rules: (
            bool | tuple[str, ...] | list[str] | Mapping[str, bool | tuple[str, ...]] | None
        ) = None,
        configured_criteria: tuple[str, ...] | list[str] | None = None,
        configured_commands: Mapping[str, Any] | None = None,
        project_config_digest: str = "",
        configured_environment_sha256: Mapping[str, str] | None = None,
        project_root: str | Path = "",
        warnings: Any = (),
        mappings: Any = (),
        records: Any = (),
        consistency: Mapping[str, Any] | None = None,
    ) -> CompletionResult:
        wants_consistency = bool(include_consistency or consistency_guard is not None or consistency is not None)
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return CompletionResult(
                task_id=task_id,
                complete=False,
                satisfied_criteria=(),
                unsatisfied_criteria=(),
                stale_criteria=(),
                receipts=(),
                consistency=dict(consistency) if isinstance(consistency, Mapping) and wants_consistency else {},
            )
        self._init_tables()
        current_time = float(time.time() if now is None else now)
        task_state = None
        required_criteria: list[str] = []
        task_missing = False
        if self.task_store is not None:
            task_state = self.task_store.get(task_id)
            if task_state:
                required_criteria = list(task_state.contract.acceptance_criteria)
            else:
                task_missing = True
        state_data = task_state.checkpoint.state_data if task_state else {}
        trusted_current_revision = str(current_revision or repository_revision or "").strip()
        expected_revision = trusted_current_revision or str(
            state_data.get("repository_revision", "")
        ).strip()
        expected_generation = int(
            state_data.get("mutation_generation", 0)
            if current_mutation_generation is None
            else current_mutation_generation
        )
        expected_owner = str(task_state.owner or "").strip() if task_state else ""
        # HTTP task creation binds session_id to the authenticated tenant. Broker
        # provenance uses that identity; artifact ownership remains the agent.
        trusted_tenant = (
            str(task_state.context.session_id or "").strip() if task_state else ""
        ) or expected_owner
        trusted_repository_root: str | Path = ""
        if isinstance(state_data, Mapping):
            trusted_repository_root = str(state_data.get("repo_root", "") or "").strip()
            worktree_data = state_data.get("worktree")
            if not trusted_repository_root and isinstance(worktree_data, Mapping):
                trusted_repository_root = str(worktree_data.get("repo_root", "") or "").strip()
        if not trusted_repository_root and project_root:
            trusted_repository_root = project_root
        if not trusted_repository_root and task_state:
            context_root = str(task_state.context.repository_id or "").strip()
            if context_root and Path(context_root).is_absolute():
                trusted_repository_root = context_root
        repo_bound = bool(
            state_data.get("repo_root")
            or (task_state and task_state.context.repository_id)
            or (task_state and task_state.checkpoint.affected_paths)
        )
        has_trusted_current_revision = bool(trusted_current_revision)

        def _fetch_receipts() -> list[Any]:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                cur = con.execute(
                    """
                    SELECT receipt_id, task_id, criterion, change_intent_id, evidence_id,
                           command_id, repository_revision, observed_at, expires_at,
                           passed, details
                    FROM agent_verification_receipts
                    WHERE task_id = ?
                    ORDER BY observed_at DESC
                    """,
                    (task_id,),
                )
                return cur.fetchall()

        rows = retry_busy(_fetch_receipts, retries=5, base_delay_seconds=0.02)

        latest_by_criterion: dict[str, VerificationReceipt] = {}
        for row in rows:
            stored_details = json.loads(row[10]) if row[10] else {}
            stored_details = dict(stored_details) if isinstance(stored_details, Mapping) else {}
            receipt_metadata = stored_details.pop("_verification_receipt", {})
            receipt_metadata = dict(receipt_metadata) if isinstance(receipt_metadata, Mapping) else {}
            metadata_schema = str(receipt_metadata.get("schema", "") or "")
            if metadata_schema not in {"", VERIFICATION_RECEIPT_METADATA_SCHEMA}:
                receipt_metadata = {}
            r = VerificationReceipt(
                receipt_id=row[0],
                task_id=row[1],
                criterion=row[2],
                owner=str(receipt_metadata.get("owner", "")),
                change_intent_id=row[3],
                evidence_id=row[4],
                command_id=row[5],
                repository_revision=row[6],
                mutation_generation=int(receipt_metadata.get("mutation_generation", 0) or 0),
                evidence_type=str(receipt_metadata.get("evidence_type", "source_review")),
                observed_at=row[7],
                expires_at=row[8],
                passed=bool(row[9]),
                details=stored_details,
            )
            if r.criterion not in latest_by_criterion:
                latest_by_criterion[r.criterion] = r

        visible_receipts = tuple(
            receipt
            for receipt in latest_by_criterion.values()
            if not expected_owner or receipt.owner == expected_owner
        )
        target_criteria = required_criteria
        gated = evaluate_completion_receipts(
            task_id,
            target_criteria,
            visible_receipts,
            owner=expected_owner,
            repository_revision=expected_revision,
            mutation_generation=expected_generation,
            mapped_receipt_ids=(task_state.verification_receipts if task_state else None),
            artifact_store=self.artifact_store,
            require_repository_revision=repo_bound and has_trusted_current_revision,
            verification_rules=verification_rules,
            configured_criteria=configured_criteria,
            configured_commands=configured_commands,
            configured_environment_sha256=configured_environment_sha256,
            project_config_digest=project_config_digest,
            project_root=project_root,
            command_execution_record_lookup=self.command_execution_record_lookup,
            trusted_tenant=trusted_tenant,
            trusted_repository_root=trusted_repository_root,
            require_execution_provenance=self.require_execution_provenance,
            now=current_time,
            evidence_store=self.evidence_store,
        )
        if repo_bound and not has_trusted_current_revision:
            gated = CompletionResult(
                task_id=task_id,
                complete=False,
                satisfied_criteria=(),
                unsatisfied_criteria=tuple(required_criteria),
                stale_criteria=tuple(),
                receipts=visible_receipts,
            )
        elif task_missing:
            gated = CompletionResult(
                task_id=task_id,
                complete=False,
                satisfied_criteria=(),
                unsatisfied_criteria=tuple(dict.fromkeys(
                    receipt.criterion for receipt in visible_receipts
                )),
                stale_criteria=tuple(),
                receipts=visible_receipts,
            )
        satisfied = list(gated.satisfied_criteria)
        unsatisfied = list(gated.unsatisfied_criteria)
        stale = list(gated.stale_criteria)
        is_complete = gated.complete

        audit: dict[str, Any] = dict(consistency) if isinstance(consistency, Mapping) else {}
        if wants_consistency and not audit and consistency_guard is not None:
            auditor = getattr(consistency_guard, "completion_audit", None)
            if callable(auditor):
                try:
                    audit = dict(auditor(
                        criteria=target_criteria,
                        receipts=visible_receipts,
                        warnings=warnings,
                        mappings=mappings,
                        records=records,
                        repository_revision=expected_revision,
                        current_revision=expected_revision,
                    ) or {})
                except Exception:
                    audit = {}

        return CompletionResult(
            task_id=task_id,
            complete=is_complete,
            satisfied_criteria=tuple(satisfied),
            unsatisfied_criteria=tuple(unsatisfied),
            stale_criteria=tuple(stale),
            receipts=visible_receipts,
            consistency=audit,
        )

    def export_receipts(
        self,
        task_id: str,
        *,
        format: str = "markdown",
    ) -> dict[str, Any]:
        task_key = str(task_id or "").strip()
        fmt = str(format or "markdown").strip().lower()
        if not task_key:
            return {
                "success": False,
                "error": "task_id required",
                "task_id": "",
                "count": 0,
                "output": "",
                "format": fmt,
            }
        if not self.state_store.enabled or not self.state_store.db_path.exists():
            return {
                "success": False,
                "error": "state store not available",
                "task_id": task_key,
                "count": 0,
                "output": "",
                "format": fmt,
            }
        self._init_tables()

        def _fetch() -> list[Any]:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                cur = con.execute(
                    """
                    SELECT receipt_id, task_id, criterion, change_intent_id, evidence_id,
                           command_id, repository_revision, observed_at, expires_at,
                           passed, details
                    FROM agent_verification_receipts
                    WHERE task_id = ?
                    ORDER BY observed_at ASC
                    """,
                    (task_key,),
                )
                return cur.fetchall()

        rows = retry_busy(_fetch, retries=5, base_delay_seconds=0.02)
        receipts: list[VerificationReceipt] = []
        for row in rows:
            stored_details = json.loads(row[10]) if row[10] else {}
            stored_details = dict(stored_details) if isinstance(stored_details, Mapping) else {}
            receipt_metadata = stored_details.pop("_verification_receipt", {})
            receipt_metadata = dict(receipt_metadata) if isinstance(receipt_metadata, Mapping) else {}
            metadata_schema = str(receipt_metadata.get("schema", "") or "")
            if metadata_schema not in {"", VERIFICATION_RECEIPT_METADATA_SCHEMA}:
                receipt_metadata = {}
            r = VerificationReceipt(
                receipt_id=row[0],
                task_id=row[1],
                criterion=row[2],
                owner=str(receipt_metadata.get("owner", "")),
                change_intent_id=row[3],
                evidence_id=row[4],
                command_id=row[5],
                repository_revision=row[6],
                mutation_generation=int(receipt_metadata.get("mutation_generation", 0) or 0),
                evidence_type=str(receipt_metadata.get("evidence_type", "source_review")),
                observed_at=row[7],
                expires_at=row[8],
                passed=bool(row[9]),
                details=stored_details,
            )
            receipts.append(r)

        if fmt == "trailers":
            lines = [f"Verified-by: {r.criterion} ({r.receipt_id})" for r in receipts]
            output = "\n".join(lines)
        elif fmt == "markdown":
            header = [
                f"### Verification Receipts for Task `{task_key}`",
                "",
                "| Criterion | Status | Evidence | Revision | Command | Receipt ID |",
                "|---|---|---|---|---|---|",
            ]
            rows_md = []
            for r in receipts:
                status = "PASSED" if r.passed else "FAILED"
                ev_str = f"`{r.evidence_id}`" if r.evidence_id else "-"
                rev_str = f"`{r.repository_revision[:12]}`" if r.repository_revision else "-"
                cmd_str = f"`{r.command_id}`" if r.command_id else "-"
                rcpt_str = f"`{r.receipt_id}`" if r.receipt_id else "-"
                rows_md.append(f"| {r.criterion} | {status} | {ev_str} | {rev_str} | {cmd_str} | {rcpt_str} |")
            output = "\n".join(header + rows_md)
        elif fmt == "json":
            output = json_dumps([r.to_dict() for r in receipts])
        else:
            return {
                "success": False,
                "error": f"unsupported format: {fmt}",
                "task_id": task_key,
                "count": len(receipts),
                "output": "",
                "format": fmt,
            }

        return {
            "success": True,
            "task_id": task_key,
            "format": fmt,
            "count": len(receipts),
            "output": output,
            "receipts": [r.to_dict() for r in receipts],
        }


def export_verification_receipts(
    store: VerificationStore,
    task_id: str,
    *,
    format: str = "markdown",
) -> dict[str, Any]:
    return store.export_receipts(task_id, format=format)
