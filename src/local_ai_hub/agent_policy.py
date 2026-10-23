from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
import logging
import json
import math
import numbers
import sqlite3
import threading
import time
from typing import Any, Mapping
import uuid

from .agent_tasks import TaskState, TaskStore, CheckpointResponseBudgetError, _canonical_repository_root
from .task_memory_wire import mcp_wire_tokens
from .agent_events import AgentEvent
from .sqlite_support import connect_sqlite, retry_busy


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


class BudgetUnavailableError(RuntimeError):
    """Durable budget authority is unavailable; execution must fail closed."""

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

    def __post_init__(self) -> None:
        nm = str(self.name or "").replace("\x00", "").strip()
        desc = str(self.description or "").replace("\x00", "").strip()
        rc = self.risk_class
        if isinstance(rc, str):
            try:
                rc = RiskClass(rc)
            except ValueError:
                raise ValueError("risk_class must be a canonical RiskClass") from None
        elif not isinstance(rc, RiskClass):
            raise ValueError("risk_class must be a canonical RiskClass")
        object.__setattr__(self, "name", nm)
        object.__setattr__(self, "risk_class", rc)
        object.__setattr__(self, "description", desc)
        object.__setattr__(self, "requires_approval", self.requires_approval is True)
        object.__setattr__(self, "default_allowed", self.default_allowed is True)


@dataclass(frozen=True)
class CapabilityGrant:
    grant_id: str
    task_id: str = ""
    allowed: frozenset[str] = frozenset()
    denied: frozenset[str] = frozenset()
    expires_at: float | None = None
    max_delegation_depth: int = 1

    def __post_init__(self) -> None:
        for name, value in (("grant_id", self.grant_id), ("task_id", self.task_id)):
            if type(value) is not str or value.strip() != value or "\x00" in value:
                raise ValueError(f"{name} must be a canonical string")
        if not self.grant_id:
            raise ValueError("grant_id must be a nonempty string")
        for field_name, values in (("allowed", self.allowed), ("denied", self.denied)):
            if type(values) is not frozenset:
                raise ValueError(f"{field_name} must be an immutable frozenset")
            for value in values:
                if (
                    type(value) is not str
                    or not value
                    or value.strip() != value
                    or "\x00" in value
                ):
                    raise ValueError(f"{field_name} entries must be nonempty canonical strings")
        if (
            isinstance(self.max_delegation_depth, bool)
            or not isinstance(self.max_delegation_depth, int)
            or self.max_delegation_depth < 0
        ):
            raise ValueError("max_delegation_depth must be a nonnegative integer")
        if self.expires_at is not None:
            if isinstance(self.expires_at, bool) or not isinstance(self.expires_at, numbers.Real):
                raise ValueError("expires_at must be a finite numeric value or None")
            try:
                finite_expiry = math.isfinite(self.expires_at)
            except (OverflowError, TypeError, ValueError):
                finite_expiry = False
            if not finite_expiry:
                raise ValueError("expires_at must be a finite numeric value or None")
    def is_expired(self, now: float | None = None) -> bool:
        if self.expires_at is None:
            return False
        current = time.time() if now is None else now
        if isinstance(current, bool) or not isinstance(current, numbers.Real):
            raise ValueError("now must be a finite numeric value")
        try:
            if not math.isfinite(current):
                raise ValueError("now must be a finite numeric value")
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("now must be a finite numeric value") from exc
        return current > self.expires_at

    def allows(self, action: str) -> bool:
        if type(action) is not str or not action or action.strip() != action or "\x00" in action:
            raise ValueError("action must be a canonical string")
        return action in self.allowed and action not in self.denied

    def denies(self, action: str) -> bool:
        if type(action) is not str or not action or action.strip() != action or "\x00" in action:
            raise ValueError("action must be a canonical string")
        return action in self.denied

    def can_delegate(self) -> bool:
        return self.max_delegation_depth > 0 and not self.is_expired()

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
        if not isinstance(data, Mapping):
            raise ValueError("capability grant data must be a mapping")
        if "grant_id" not in data:
            raise ValueError("grant_id is required")
        allowed_data = data.get("allowed", [])
        denied_data = data.get("denied", [])
        if type(allowed_data) is not list or type(denied_data) is not list:
            raise ValueError("allowed and denied must be JSON arrays")
        for values in (allowed_data, denied_data):
            for value in values:
                if type(value) is not str:
                    raise ValueError("allowed and denied entries must be strings")
        return cls(
            grant_id=data["grant_id"],
            task_id=data.get("task_id", ""),
            allowed=frozenset(allowed_data),
            denied=frozenset(denied_data),
            expires_at=data.get("expires_at"),
            max_delegation_depth=data.get("max_delegation_depth", 1),
        )


def _safe_int(val: Any, default: int = 0, min_val: int | None = None) -> int:
    if isinstance(val, bool):
        return default
    try:
        i = int(val)
        return max(min_val, i) if min_val is not None else i
    except (ValueError, TypeError, OverflowError):
        return default


def _safe_float(val: Any, default: float = 0.0, min_val: float | None = None) -> float:
    if isinstance(val, bool):
        return default
    try:
        f = float(val)
        if not math.isfinite(f):
            return default
        return max(min_val, f) if min_val is not None else f
    except (ValueError, TypeError, OverflowError):
        return default


@dataclass(frozen=True)
class BudgetCost:
    tokens: int = 0
    compute_seconds: float = 0.0
    external_calls: int = 0

    def __post_init__(self) -> None:
        tok = _safe_int(self.tokens, default=0, min_val=0)
        cs = _safe_float(self.compute_seconds, default=0.0, min_val=0.0)
        ec = _safe_int(self.external_calls, default=0, min_val=0)
        object.__setattr__(self, "tokens", tok)
        object.__setattr__(self, "compute_seconds", cs)
        object.__setattr__(self, "external_calls", ec)

    def is_zero(self) -> bool:
        return self.tokens == 0 and self.compute_seconds == 0.0 and self.external_calls == 0


@dataclass(frozen=True)
class Budget:
    task_id: str
    max_tokens: int = 100_000
    used_tokens: int = 0
    max_compute_seconds: float = 600.0
    used_compute_seconds: float = 0.0
    max_external_calls: int = 50
    used_external_calls: int = 0

    def __post_init__(self) -> None:
        tid = str(self.task_id or "").replace("\x00", "").strip()
        mt = _safe_int(self.max_tokens, default=100_000, min_val=0)
        ut = _safe_int(self.used_tokens, default=0, min_val=0)
        mcs = _safe_float(self.max_compute_seconds, default=600.0, min_val=0.0)
        ucs = _safe_float(self.used_compute_seconds, default=0.0, min_val=0.0)
        mec = _safe_int(self.max_external_calls, default=50, min_val=0)
        uec = _safe_int(self.used_external_calls, default=0, min_val=0)
        object.__setattr__(self, "task_id", tid)
        object.__setattr__(self, "max_tokens", mt)
        object.__setattr__(self, "used_tokens", ut)
        object.__setattr__(self, "max_compute_seconds", mcs)
        object.__setattr__(self, "used_compute_seconds", ucs)
        object.__setattr__(self, "max_external_calls", mec)
        object.__setattr__(self, "used_external_calls", uec)

    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self.used_tokens)

    def remaining_compute_seconds(self) -> float:
        return max(0.0, self.max_compute_seconds - self.used_compute_seconds)

    def remaining_external_calls(self) -> int:
        return max(0, self.max_external_calls - self.used_external_calls)

    def token_utilization(self) -> float:
        if self.max_tokens <= 0:
            return 1.0
        return min(1.0, self.used_tokens / self.max_tokens)

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

    def __post_init__(self) -> None:
        if (
            type(self.action) is not str
            or not self.action
            or self.action != self.action.strip()
            or "\x00" in self.action
        ):
            raise ValueError("action must be a canonical nonempty string")
        act = self.action
        tgt = str(self.target or "").replace("\x00", "").strip()
        rc = self.risk_class
        if isinstance(rc, str):
            try:
                rc = RiskClass(rc)
            except ValueError:
                raise ValueError("risk_class must be a canonical RiskClass") from None
        elif not isinstance(rc, RiskClass):
            raise ValueError("risk_class must be a canonical RiskClass")
        det = dict(self.details) if isinstance(self.details, Mapping) else {}
        object.__setattr__(self, "action", act)
        object.__setattr__(self, "target", tgt)
        object.__setattr__(self, "risk_class", rc)
        object.__setattr__(self, "details", det)

    def is_read(self) -> bool:
        return self.risk_class == RiskClass.READ

    def is_write(self) -> bool:
        return self.risk_class == RiskClass.WRITE

    def is_network(self) -> bool:
        return self.risk_class == RiskClass.NETWORK


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool = False
    reason: str = ""
    receipt_id: str = ""
    owner: str = POLICY_OWNER
    side_effect_class: str = "read"

    def __post_init__(self) -> None:
        rsn = str(self.reason or "").replace("\x00", "").strip()
        rid = str(self.receipt_id or "").replace("\x00", "").strip()
        own = str(self.owner or POLICY_OWNER).replace("\x00", "").strip()
        sec = str(self.side_effect_class or "read").replace("\x00", "").strip()
        object.__setattr__(self, "allowed", self.allowed is True)
        object.__setattr__(self, "requires_approval", self.requires_approval is True)
        object.__setattr__(self, "reason", rsn)
        object.__setattr__(self, "receipt_id", rid)
        object.__setattr__(self, "owner", own)
        object.__setattr__(self, "side_effect_class", sec)

    def is_allowed(self) -> bool:
        return self.allowed

    def is_denied(self) -> bool:
        return not self.allowed and not self.requires_approval

    def needs_approval(self) -> bool:
        return self.requires_approval

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "owner": self.owner,
            "side_effect_class": self.side_effect_class,
        }


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
                raise BudgetUnavailableError("budget state unavailable") from None

    def authorize(
        self,
        request: ActionRequest,
        task: TaskState,
        grant: CapabilityGrant | None = None,
    ) -> PolicyDecision:
        action_name = request.action
        auxiliary_marked = bool(request.details.get("auxiliary_action"))
        if type(action_name) is not str:
            return PolicyDecision(
                allowed=False,
                reason="unknown auxiliary action with invalid name type denied",
                owner=POLICY_OWNER,
                side_effect_class="unknown",
            )

        auxiliary_policy = AUXILIARY_ACTION_POLICIES.get(action_name)
        normalized_action = action_name.strip().lower().replace("-", "_")
        if (
            normalized_action in AUXILIARY_ACTION_POLICIES
            and normalized_action != action_name
        ):
            return PolicyDecision(
                allowed=False,
                reason=f"unknown auxiliary action '{action_name}' denied",
                owner=POLICY_OWNER,
                side_effect_class="unknown",
            )

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
            try:
                budget = self.get_budget(task.task_id)
            except BudgetUnavailableError:
                return PolicyDecision(allowed=False, reason="budget state unavailable", owner=POLICY_OWNER, side_effect_class=side_effect_class)
            if budget.is_exhausted():
                return PolicyDecision(
                    allowed=False,
                    requires_approval=False,
                    reason=f"task budget exhausted ({task.task_id}): tokens={budget.used_tokens}/{budget.max_tokens}, time={budget.used_compute_seconds:.1f}/{budget.max_compute_seconds:.1f}s, external_calls={budget.used_external_calls}/{budget.max_external_calls}",
                    owner=POLICY_OWNER,
                    side_effect_class=side_effect_class,
                )

        if grant is not None:
            if grant.is_expired():
                return PolicyDecision(
                    allowed=False,
                    requires_approval=True,
                    reason=f"capability grant '{grant.grant_id}' has expired",
                    owner=POLICY_OWNER,
                    side_effect_class=side_effect_class,
                )
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
        if not isinstance(parent_grant, CapabilityGrant):
            raise ValueError("parent_grant must be a CapabilityGrant")
        if type(requested) not in (set, frozenset):
            raise ValueError("requested actions must be a set of canonical strings")
        for action in requested:
            if type(action) is not str or not action or action.strip() != action or "\x00" in action:
                raise ValueError("requested actions must be canonical strings")
        if parent_grant.max_delegation_depth <= 0 or parent_grant.is_expired():
            return CapabilityGrant(
                grant_id=f"grant_{uuid.uuid4().hex[:12]}",
                task_id=parent_grant.task_id,
                allowed=frozenset(),
                denied=parent_grant.denied | frozenset(requested),
                expires_at=parent_grant.expires_at,
                max_delegation_depth=0,
            )
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
                raise BudgetUnavailableError("budget state unavailable") from None

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
        return self._mutate_budget(task_id, limits={
            key: value for key, value in {
                "max_tokens": max_tokens,
                "max_compute_seconds": max_compute_seconds,
                "max_external_calls": max_external_calls,
            }.items() if value is not None
        })

    def increase_task_budget(
        self, task_id: str, *, actor: str, repo_root: str,
        reason: str, limits: Mapping[str, Any], authorization_actor: str,
        response_budget_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Storage operation; transport must supply its authenticated task actor.

        Recheck persisted ownership and scope under the same write lock as the
        budget and audit. Never create a task/budget or reset consumption here.
        """
        if type(authorization_actor) is not str or authorization_actor not in {"api_token", "action_token", "local"}:
            raise PermissionError("verified transport authorization required")
        if response_budget_tokens is not None and (type(response_budget_tokens) is not int or response_budget_tokens < 128):
            raise ValueError("response budget must be an integer of at least 128")
        for name, value in (("task_id", task_id), ("actor", actor)):
            if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
                raise ValueError(f"{name} must be a canonical nonempty string")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 4096:
            raise ValueError("reason must be nonempty and at most 4096 characters")
        if not isinstance(limits, Mapping) or not limits:
            raise ValueError("limits must be a nonempty mapping")
        proposed = dict(limits)
        allowed = {"max_tokens", "max_compute_seconds", "max_external_calls"}
        if proposed.keys() - allowed:
            raise ValueError("unknown budget limit")
        for name, value in proposed.items():
            if name == "max_compute_seconds":
                valid = type(value) in (int, float)
                if valid:
                    try:
                        valid = math.isfinite(value) and value >= 0
                    except OverflowError:
                        valid = False
            else:
                valid = type(value) is int and 0 <= value <= 2**63 - 1
            if not valid:
                raise ValueError(f"invalid {name}")
        root = _canonical_repository_root(repo_root)
        store = self.state_store
        if not store or not store.enabled or not callable(getattr(store, "append_in_transaction", None)):
            raise BudgetUnavailableError("persistent budget audit unavailable")
        with self._lock:
            self._init_table()

            def mutate() -> dict[str, Any]:
                with closing(connect_sqlite(store.db_path)) as con, con:
                    con.execute("BEGIN IMMEDIATE")
                    task = con.execute(
                        "SELECT owner,status,checkpoint FROM agent_tasks_projection WHERE task_id=?",
                        (task_id,),
                    ).fetchone()
                    if task is None:
                        raise KeyError(task_id)
                    owner, status, checkpoint = task
                    scope = json.loads(checkpoint).get("state_data", {}).get("_agent_task_scope", {})
                    if (owner != actor or type(scope.get("version")) is not int
                            or scope["version"] != 2 or scope.get("repo_root") != root):
                        raise PermissionError("task owner or repository scope mismatch")
                    if status not in {"planned", "active", "waiting", "blocked", "verifying", "failed"}:
                        raise PermissionError("task is not resumable by this budget action")
                    row = con.execute(
                        "SELECT task_id,max_tokens,used_tokens,max_compute_seconds,used_compute_seconds,max_external_calls,used_external_calls FROM agent_budgets WHERE task_id=?",
                        (task_id,),
                    ).fetchone()
                    if row is None:
                        raise BudgetUnavailableError("existing task budget required")
                    before = Budget(*row)
                    if tuple(asdict(before).values()) != tuple(row):
                        raise BudgetUnavailableError("corrupt budget cannot be normalized during an increase")
                    if any(value <= getattr(before, name) for name, value in proposed.items()):
                        raise ValueError("every supplied limit must strictly increase")
                    after = replace(before, **proposed)
                    event = AgentEvent.create(
                        stream_id=f"budget:{task_id}", kind="task.budget_increased",
                        actor=authorization_actor,
                        payload={"task_id": task_id, "repo_root": root,
                                 "task_owner": actor,
                                 "reason": reason, "before": asdict(before), "after": asdict(after)},
                    )
                    result = {"success": True, "task_id": task_id, "budget": asdict(after),
                              "audit_event_id": event.event_id, "before": asdict(before)}
                    if response_budget_tokens is not None:
                        preview = TaskStore._include_current_request_id(result)
                        # Reserve bounded final response/accounting envelope overhead.
                        required = mcp_wire_tokens(preview, text_payload=preview) + 512
                        if required > response_budget_tokens:
                            raise CheckpointResponseBudgetError(response_budget_tokens, required)
                    self._write_budget(con, after)
                    store.append_in_transaction(con, event)
                return result

            try:
                result = retry_busy(mutate, retries=5, base_delay_seconds=0.01)
            except sqlite3.Error as exc:
                raise BudgetUnavailableError("budget update or audit unavailable") from exc
            self._budgets[task_id] = Budget(**result["budget"])
            return result

    def consume(self, task_id: str, cost: BudgetCost) -> Budget:
        return self._mutate_budget(task_id, cost=cost)

    def _mutate_budget(
        self, task_id: str, *, cost: BudgetCost | None = None,
        limits: dict[str, Any] | None = None, reset: bool = False,
    ) -> Budget:
        def updated(current: Budget) -> Budget:
            return replace(
                current, **(limits or {}),
                used_tokens=0 if reset else current.used_tokens + (cost.tokens if cost else 0),
                used_compute_seconds=0.0 if reset else current.used_compute_seconds + (cost.compute_seconds if cost else 0),
                used_external_calls=0 if reset else current.used_external_calls + (cost.external_calls if cost else 0),
            )

        with self._lock:
            if self.state_store and getattr(self.state_store, "enabled", False) and getattr(self.state_store, "db_path", None):
                self._init_table()

                def mutate() -> Budget:
                    with closing(connect_sqlite(self.state_store.db_path)) as con, con:
                        # Serialize the complete read/modify/write across engine instances.
                        con.execute("BEGIN IMMEDIATE")
                        row = con.execute(
                            "SELECT task_id,max_tokens,used_tokens,max_compute_seconds,used_compute_seconds,max_external_calls,used_external_calls FROM agent_budgets WHERE task_id=?",
                            (task_id,),
                        ).fetchone()
                        current = Budget(*row) if row is not None else Budget(task_id=task_id)
                        candidate = updated(current)
                        self._write_budget(con, candidate)
                    return candidate

                try:
                    result = retry_busy(mutate, retries=5, base_delay_seconds=0.01)
                except sqlite3.Error as exc:
                    LOGGER.warning("budget state persistence failed (%s)", type(exc).__name__)
                    raise BudgetUnavailableError("budget state unavailable") from None
            else:
                result = updated(self.get_budget(task_id))
                self._persist_budget(result)
            self._budgets[task_id] = result
            return result

    @staticmethod
    def _write_budget(con: sqlite3.Connection, budget: Budget) -> None:
        con.execute(
            "INSERT INTO agent_budgets(task_id,max_tokens,used_tokens,max_compute_seconds,used_compute_seconds,max_external_calls,used_external_calls,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET "
            "max_tokens=excluded.max_tokens,used_tokens=excluded.used_tokens,"
            "max_compute_seconds=excluded.max_compute_seconds,used_compute_seconds=excluded.used_compute_seconds,"
            "max_external_calls=excluded.max_external_calls,used_external_calls=excluded.used_external_calls,updated_at=excluded.updated_at",
            (budget.task_id, budget.max_tokens, budget.used_tokens, budget.max_compute_seconds,
             budget.used_compute_seconds, budget.max_external_calls, budget.used_external_calls, time.time()),
        )

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
            raise BudgetUnavailableError("budget state unavailable") from None

    def has_budget(self, task_id: str) -> bool:
        clean_id = str(task_id or "").replace("\x00", "").strip()
        if not clean_id:
            return False
        with self._lock:
            if clean_id in self._budgets:
                return True
        if self.state_store and getattr(self.state_store, "enabled", False) and getattr(self.state_store, "db_path", None):
            self._init_table()
            def _check():
                with closing(connect_sqlite(self.state_store.db_path)) as con:
                    row = con.execute("SELECT 1 FROM agent_budgets WHERE task_id = ?", (clean_id,)).fetchone()
                    return bool(row)
            try:
                return bool(retry_busy(_check, retries=3, base_delay_seconds=0.01))
            except sqlite3.Error:
                return False
        return False

    def reset_budget(self, task_id: str) -> Budget:
        clean_id = str(task_id or "").replace("\x00", "").strip()
        return self._mutate_budget(clean_id, reset=True)

    def delete_budget(self, task_id: str) -> bool:
        clean_id = str(task_id or "").replace("\x00", "").strip()
        with self._lock:
            existed = clean_id in self._budgets
            self._budgets.pop(clean_id, None)
        if self.state_store and getattr(self.state_store, "enabled", False) and getattr(self.state_store, "db_path", None):
            self._init_table()
            def _del():
                with closing(connect_sqlite(self.state_store.db_path)) as con:
                    with con:
                        cur = con.execute("DELETE FROM agent_budgets WHERE task_id = ?", (clean_id,))
                        return cur.rowcount > 0
            try:
                db_deleted = bool(retry_busy(_del, retries=5, base_delay_seconds=0.01))
                return existed or db_deleted
            except sqlite3.Error:
                return existed
        return existed
