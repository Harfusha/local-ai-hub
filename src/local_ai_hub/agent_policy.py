from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .agent_tasks import TaskState


class RiskClass(str, Enum):
    READ = "read"
    WRITE = "write"
    NETWORK = "network"
    GIT_MUTATION = "git_mutation"
    SECRET_ACCESS = "secret_access"
    SYSTEM_CONFIG = "system_config"
    PRIVILEGE_CHANGE = "privilege_change"


@dataclass(frozen=True)
class CapabilityDescriptor:
    name: str
    risk_class: RiskClass
    description: str = ""
    requires_approval: bool = False
    default_allowed: bool = True


@dataclass(frozen=True)
class CapabilityGrant:
    grant_id: str
    task_id: str = ""
    allowed: frozenset[str] = frozenset()
    denied: frozenset[str] = frozenset()
    expires_at: float | None = None
    max_delegation_depth: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "task_id": self.task_id,
            "allowed": list(self.allowed),
            "denied": list(self.denied),
            "expires_at": self.expires_at,
            "max_delegation_depth": self.max_delegation_depth,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CapabilityGrant:
        return cls(
            grant_id=str(data["grant_id"]),
            task_id=str(data.get("task_id", "")),
            allowed=frozenset(data.get("allowed") or ()),
            denied=frozenset(data.get("denied") or ()),
            expires_at=float(data["expires_at"]) if data.get("expires_at") is not None else None,
            max_delegation_depth=int(data.get("max_delegation_depth", 1)),
        )


@dataclass(frozen=True)
class BudgetCost:
    tokens: int = 0
    compute_seconds: float = 0.0
    external_calls: int = 0


@dataclass(frozen=True)
class Budget:
    task_id: str
    max_tokens: int = 100_000
    used_tokens: int = 0
    max_compute_seconds: float = 600.0
    used_compute_seconds: float = 0.0
    max_external_calls: int = 50
    used_external_calls: int = 0

    def is_exhausted(self) -> bool:
        return (
            self.used_tokens >= self.max_tokens
            or self.used_compute_seconds >= self.max_compute_seconds
            or self.used_external_calls >= self.max_external_calls
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "max_tokens": self.max_tokens,
            "used_tokens": self.used_tokens,
            "max_compute_seconds": self.max_compute_seconds,
            "used_compute_seconds": self.used_compute_seconds,
            "max_external_calls": self.max_external_calls,
            "used_external_calls": self.used_external_calls,
            "exhausted": self.is_exhausted(),
        }


@dataclass(frozen=True)
class ActionRequest:
    action: str
    target: str = ""
    risk_class: RiskClass = RiskClass.READ
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool = False
    reason: str = ""
    receipt_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
        }


class PolicyEngine:
    def __init__(self, state_store: Any | None = None) -> None:
        self.state_store = state_store
        self._budgets: dict[str, Budget] = {}

    def authorize(
        self,
        request: ActionRequest,
        task: TaskState,
        grant: CapabilityGrant | None = None,
    ) -> PolicyDecision:
        if grant is not None:
            if request.action in grant.denied or request.risk_class.value in grant.denied:
                return PolicyDecision(
                    allowed=False,
                    requires_approval=False,
                    reason=f"action '{request.action}' explicitly denied by capability grant",
                )
            if request.action in grant.allowed or request.risk_class.value in grant.allowed:
                return PolicyDecision(
                    allowed=True,
                    requires_approval=False,
                    reason="action permitted by capability grant",
                )

        if request.risk_class in (
            RiskClass.WRITE,
            RiskClass.NETWORK,
            RiskClass.GIT_MUTATION,
            RiskClass.SECRET_ACCESS,
            RiskClass.SYSTEM_CONFIG,
            RiskClass.PRIVILEGE_CHANGE,
        ):
            return PolicyDecision(
                allowed=False,
                requires_approval=True,
                reason=f"{request.risk_class.value} requires explicit approval or grant",
            )

        return PolicyDecision(
            allowed=True,
            requires_approval=False,
            reason="read-only action permitted by default",
        )

    def delegate(
        self,
        parent_grant: CapabilityGrant,
        requested: set[str] | frozenset[str],
    ) -> CapabilityGrant:
        req = frozenset(requested)
        child_allowed = req & parent_grant.allowed
        child_denied = parent_grant.denied | (req - parent_grant.allowed)
        return CapabilityGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:12]}",
            task_id=parent_grant.task_id,
            allowed=child_allowed,
            denied=child_denied,
            expires_at=parent_grant.expires_at,
            max_delegation_depth=max(0, parent_grant.max_delegation_depth - 1),
        )

    def get_budget(self, task_id: str) -> Budget:
        if task_id not in self._budgets:
            self._budgets[task_id] = Budget(task_id=task_id)
        return self._budgets[task_id]

    def consume(self, task_id: str, cost: BudgetCost) -> Budget:
        curr = self.get_budget(task_id)
        updated = Budget(
            task_id=task_id,
            max_tokens=curr.max_tokens,
            used_tokens=curr.used_tokens + cost.tokens,
            max_compute_seconds=curr.max_compute_seconds,
            used_compute_seconds=curr.used_compute_seconds + cost.compute_seconds,
            max_external_calls=curr.max_external_calls,
            used_external_calls=curr.used_external_calls + cost.external_calls,
        )
        self._budgets[task_id] = updated
        return updated
