from __future__ import annotations

import logging
import math
import numbers
import sqlite3
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


POLICY_OWNER = "agent_policy"
LOGGER = logging.getLogger(__name__)

# Auxiliary command names are normalized at the policy boundary so callers
# cannot lower their risk by supplying a read-only ActionRequest.
AUXILIARY_ACTION_POLICIES: dict[str, tuple[RiskClass, str]] = {
    "run": (RiskClass.WRITE, "process_execution"),
    "run_affected": (RiskClass.WRITE, "process_execution"),
    "cancel": (RiskClass.WRITE, "process_lifecycle"),
    "classify": (RiskClass.READ, "command_metadata"),
    "discover": (RiskClass.READ, "command_discovery"),
    "stats": (RiskClass.READ, "command_metrics"),
    "repair": (RiskClass.WRITE, "workspace_write"),
    "repair_loop": (RiskClass.WRITE, "workspace_write"),
    "auto_fix": (RiskClass.WRITE, "workspace_write"),
    "lint_fix": (RiskClass.WRITE, "workspace_write"),
    "patch_and_verify": (RiskClass.WRITE, "workspace_write"),
    "format": (RiskClass.WRITE, "workspace_write"),
    "spawn_daemon": (RiskClass.SYSTEM_CONFIG, "process_lifecycle"),
    "stop_daemon": (RiskClass.SYSTEM_CONFIG, "process_lifecycle"),
    "daemon_status": (RiskClass.READ, "process_status"),
    "http_probe": (RiskClass.NETWORK, "network_access"),
    "webhook_replay": (RiskClass.NETWORK, "network_access"),
    "stash_save": (RiskClass.GIT_MUTATION, "git_mutation"),
    "stash_restore": (RiskClass.GIT_MUTATION, "git_mutation"),
    "diff_hunk_stage": (RiskClass.GIT_MUTATION, "git_mutation"),
    "record_mock": (RiskClass.WRITE, "test_fixture_write"),
    "replay_mock": (RiskClass.WRITE, "test_fixture_write"),
    "mock_server": (RiskClass.NETWORK, "network_listener"),
    "mock_server_start": (RiskClass.NETWORK, "network_listener"),
    "mock_server_stop": (RiskClass.NETWORK, "network_listener"),
    "mock_server_status": (RiskClass.READ, "process_status"),
    "flaky_detect": (RiskClass.WRITE, "process_execution"),
    "preflight": (RiskClass.WRITE, "process_execution"),
    "speculative_lint": (RiskClass.WRITE, "process_execution"),
    "bundle": (RiskClass.WRITE, "artifact_write"),
    "bundle_create": (RiskClass.WRITE, "artifact_write"),
    "config": (RiskClass.SYSTEM_CONFIG, "system_configuration"),
    "config_update": (RiskClass.SYSTEM_CONFIG, "system_configuration"),
    "model": (RiskClass.NETWORK, "model_execution"),
    "model_inference": (RiskClass.NETWORK, "model_execution"),
}


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
    owner: str = POLICY_OWNER
    side_effect_class: str = "read"

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "owner": self.owner,
            "side_effect_class": self.side_effect_class,
        }


import threading
import time
from contextlib import closing
from .sqlite_support import connect_sqlite, retry_busy


class PolicyEngine:
    def __init__(
        self,
        state_store: Any | None = None,
        *,
        auxiliary_actions_enabled: bool = True,
    ) -> None:
        self.state_store = state_store
        self.auxiliary_actions_enabled = bool(auxiliary_actions_enabled)
        self._lock = threading.RLock()
        self._budgets: dict[str, Budget] = {}
        self._initialized = False
        self._init_table()

    def _init_table(self) -> None:
        if self._initialized or not self.state_store or not getattr(self.state_store, "enabled", False):
            return
        with self._lock:
            if self._initialized or not self.state_store or not getattr(self.state_store, "enabled", False):
                return
            if hasattr(self.state_store, "_ensure_schema"):
                self.state_store._ensure_schema()
            def _setup() -> None:
                with closing(connect_sqlite(self.state_store.db_path)) as con:
                    with con:
                        con.execute(
                            """
                            CREATE TABLE IF NOT EXISTS agent_budgets (
                                task_id TEXT PRIMARY KEY,
                                max_tokens INTEGER NOT NULL DEFAULT 100000,
                                used_tokens INTEGER NOT NULL DEFAULT 0,
                                max_compute_seconds REAL NOT NULL DEFAULT 600.0,
                                used_compute_seconds REAL NOT NULL DEFAULT 0.0,
                                max_external_calls INTEGER NOT NULL DEFAULT 50,
                                used_external_calls INTEGER NOT NULL DEFAULT 0,
                                updated_at REAL NOT NULL
                            )
                            """
                        )
                        con.execute(
                            "CREATE INDEX IF NOT EXISTS idx_agent_budgets_task ON agent_budgets(task_id)"
                        )
            try:
                retry_busy(_setup, retries=5, base_delay_seconds=0.02)
                self._initialized = True
            except sqlite3.Error as exc:
                LOGGER.warning(
                    "budget state initialization failed (%s)", type(exc).__name__
                )

    def authorize(
        self,
        request: ActionRequest,
        task: TaskState,
        grant: CapabilityGrant | None = None,
    ) -> PolicyDecision:
        action_name = request.action.strip().lower().replace("-", "_")
        auxiliary_policy = AUXILIARY_ACTION_POLICIES.get(action_name)
        auxiliary_marked = bool(request.details.get("auxiliary_action"))
        side_effect_class = (
            auxiliary_policy[1]
            if auxiliary_policy
            else ("unknown" if auxiliary_marked else request.risk_class.value)
        )
        risk_class = auxiliary_policy[0] if auxiliary_policy else request.risk_class

        if auxiliary_policy and (
            not self.auxiliary_actions_enabled
            or request.details.get("policy_enabled") is False
        ):
            return PolicyDecision(
                allowed=False,
                reason="auxiliary action policy is disabled",
                owner=POLICY_OWNER,
                side_effect_class=side_effect_class,
            )
        if auxiliary_marked and auxiliary_policy is None:
            return PolicyDecision(
                allowed=False,
                reason=f"unknown auxiliary action '{request.action}' denied",
                owner=POLICY_OWNER,
                side_effect_class="unknown",
            )

        # 1. Check budget expiration
        if task and task.task_id:
            budget = self.get_budget(task.task_id)
            if budget.is_exhausted():
                return PolicyDecision(
                    allowed=False,
                    requires_approval=False,
                    reason=f"task budget exhausted ({task.task_id}): tokens={budget.used_tokens}/{budget.max_tokens}, time={budget.used_compute_seconds:.1f}/{budget.max_compute_seconds:.1f}s",
                    owner=POLICY_OWNER,
                    side_effect_class=side_effect_class,
                )

        if grant is not None:
            if request.action in grant.denied or risk_class.value in grant.denied:
                return PolicyDecision(
                    allowed=False,
                    requires_approval=False,
                    reason=f"action '{request.action}' explicitly denied by capability grant",
                    owner=POLICY_OWNER,
                    side_effect_class=side_effect_class,
                )
            if request.action in grant.allowed or risk_class.value in grant.allowed:
                expiry = grant.expires_at
                if expiry is not None:
                    try:
                        expiry_value = float(expiry)
                        expiry_valid = (
                            not isinstance(expiry, bool)
                            and isinstance(expiry, numbers.Real)
                            and math.isfinite(expiry_value)
                        )
                    except (OverflowError, TypeError, ValueError):
                        expiry_valid = False
                        expiry_value = 0.0
                    if not expiry_valid:
                        return PolicyDecision(
                            allowed=False,
                            requires_approval=False,
                            reason="capability grant has invalid expiry",
                            owner=POLICY_OWNER,
                            side_effect_class=side_effect_class,
                        )
                    if time.time() >= expiry_value:
                        return PolicyDecision(
                            allowed=False,
                            requires_approval=False,
                            reason="capability grant has expired",
                            owner=POLICY_OWNER,
                            side_effect_class=side_effect_class,
                        )
                return PolicyDecision(
                    allowed=True,
                    requires_approval=False,
                    reason="action permitted by capability grant",
                    owner=POLICY_OWNER,
                    side_effect_class=side_effect_class,
                )

        if risk_class in (
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
                reason=f"{risk_class.value} requires explicit approval or grant",
                owner=POLICY_OWNER,
                side_effect_class=side_effect_class,
            )

        return PolicyDecision(
            allowed=True,
            requires_approval=False,
            reason="read-only action permitted by default",
            owner=POLICY_OWNER,
            side_effect_class=side_effect_class,
        )

    def delegate(
        self,
        parent_grant: CapabilityGrant,
        requested: set[str] | frozenset[str],
    ) -> CapabilityGrant:
        req = frozenset(requested)
        expiry = parent_grant.expires_at
        expiry_valid = expiry is None
        if expiry is not None:
            try:
                expiry_valid = (
                    not isinstance(expiry, bool)
                    and isinstance(expiry, numbers.Real)
                    and math.isfinite(float(expiry))
                    and time.time() < float(expiry)
                )
            except (OverflowError, TypeError, ValueError):
                expiry_valid = False
        depth = parent_grant.max_delegation_depth
        depth_valid = (
            isinstance(depth, int)
            and not isinstance(depth, bool)
            and depth > 0
        )
        can_delegate = expiry_valid and depth_valid
        child_denied = parent_grant.denied | (req - parent_grant.allowed)
        if not can_delegate:
            child_denied |= req
        child_allowed = (
            req & (parent_grant.allowed - child_denied)
            if can_delegate
            else frozenset()
        )
        return CapabilityGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:12]}",
            task_id=parent_grant.task_id,
            allowed=child_allowed,
            denied=child_denied,
            expires_at=parent_grant.expires_at,
            max_delegation_depth=max(0, depth - 1) if depth_valid else 0,
        )

    def get_budget(self, task_id: str) -> Budget:
        self._init_table()
        if self.state_store and getattr(self.state_store, "enabled", False) and getattr(self.state_store, "db_path", None):
            def _fetch():
                with closing(connect_sqlite(self.state_store.db_path)) as con:
                    row = con.execute(
                        "SELECT task_id, max_tokens, used_tokens, max_compute_seconds, used_compute_seconds, max_external_calls, used_external_calls FROM agent_budgets WHERE task_id = ?",
                        (task_id,),
                    ).fetchone()
                    if row:
                        return Budget(
                            task_id=str(row[0]),
                            max_tokens=int(row[1]),
                            used_tokens=int(row[2]),
                            max_compute_seconds=float(row[3]),
                            used_compute_seconds=float(row[4]),
                            max_external_calls=int(row[5]),
                            used_external_calls=int(row[6]),
                        )
                    return None
            try:
                b = retry_busy(_fetch, retries=3, base_delay_seconds=0.01)
                if b is not None:
                    self._budgets[task_id] = b
                    return b
            except sqlite3.Error as exc:
                LOGGER.warning("budget state read failed (%s)", type(exc).__name__)

        with self._lock:
            if len(self._budgets) > 512:
                for k in list(self._budgets.keys())[:256]:
                    self._budgets.pop(k, None)
            if task_id not in self._budgets:
                self._budgets[task_id] = Budget(task_id=task_id)
            return self._budgets[task_id]

    def set_budget(
        self,
        task_id: str,
        max_tokens: int | None = None,
        max_compute_seconds: float | None = None,
        max_external_calls: int | None = None,
    ) -> Budget:
        curr = self.get_budget(task_id)
        updated = Budget(
            task_id=task_id,
            max_tokens=max_tokens if max_tokens is not None else curr.max_tokens,
            used_tokens=curr.used_tokens,
            max_compute_seconds=max_compute_seconds if max_compute_seconds is not None else curr.max_compute_seconds,
            used_compute_seconds=curr.used_compute_seconds,
            max_external_calls=max_external_calls if max_external_calls is not None else curr.max_external_calls,
            used_external_calls=curr.used_external_calls,
        )
        self._persist_budget(updated)
        self._budgets[task_id] = updated
        return updated

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
        self._persist_budget(updated)
        self._budgets[task_id] = updated
        return updated

    def _persist_budget(self, budget: Budget) -> None:
        if not self.state_store or not getattr(self.state_store, "enabled", False) or not getattr(self.state_store, "db_path", None):
            return
        self._init_table()
        now = time.time()
        def _save():
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                with con:
                    con.execute(
                        """
                        INSERT INTO agent_budgets (
                            task_id, max_tokens, used_tokens, max_compute_seconds,
                            used_compute_seconds, max_external_calls, used_external_calls, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(task_id) DO UPDATE SET
                            max_tokens = excluded.max_tokens,
                            used_tokens = excluded.used_tokens,
                            max_compute_seconds = excluded.max_compute_seconds,
                            used_compute_seconds = excluded.used_compute_seconds,
                            max_external_calls = excluded.max_external_calls,
                            used_external_calls = excluded.used_external_calls,
                            updated_at = excluded.updated_at
                        """,
                        (
                            budget.task_id, budget.max_tokens, budget.used_tokens,
                            budget.max_compute_seconds, budget.used_compute_seconds,
                            budget.max_external_calls, budget.used_external_calls, now,
                        ),
                    )
        try:
            retry_busy(_save, retries=5, base_delay_seconds=0.01)
        except sqlite3.Error as exc:
            LOGGER.warning("budget state persistence failed (%s)", type(exc).__name__)
