"""Data models for repository-owned plan files (repo-plan.v1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _require_object(
    data: Any, label: str, *, required: set[str], allowed: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be an object")
    allowed = allowed if allowed is not None else required
    missing = required - data.keys()
    unknown = data.keys() - allowed
    if missing:
        raise ValueError(f"{label} is missing required fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{label} has unknown fields: {', '.join(sorted(unknown))}")
    return data


def _require_list(data: Any, label: str) -> list[Any]:
    if not isinstance(data, list):
        raise ValueError(f"{label} must be an array")
    return data


class PlanLifecycle(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class TaskKind(str, Enum):
    CODE = "code"
    DOCUMENTATION = "documentation"
    ANALYSIS = "analysis"
    OPERATION = "operation"


class TaskWorkStatus(str, Enum):
    PLANNED = "planned"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    SOURCE_READY = "source_ready"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskWorkPhase(str, Enum):
    DISCOVERY = "discovery"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    INTEGRATION = "integration"


class ClarificationAdoption(str, Enum):
    PENDING = "pending"
    ADOPTED = "adopted"
    SUPERSEDED = "superseded"


class DeliveryDisposition(str, Enum):
    PENDING = "pending"
    DECLARED_INTEGRATED = "declared_integrated"
    WAIVED = "waived"


class RevisionKind(str, Enum):
    GIT_COMMIT = "git_commit"
    WORKING = "working"


class ResultRefKind(str, Enum):
    GIT_COMMIT = "git_commit"
    EVIDENCE_REFERENCE = "evidence_reference"


@dataclass(frozen=True)
class Revision:
    kind: str
    commit: str | None = None
    content_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind}
        if self.kind == "git_commit":
            data["commit"] = self.commit or ""
        elif self.kind == "working":
            data["content_sha256"] = self.content_sha256 or ""
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Revision:
        if not isinstance(data, dict):
            raise ValueError("revision must be an object")
        kind = data.get("kind")
        fields = {"git_commit": {"kind", "commit"}, "working": {"kind", "content_sha256"}}
        if kind not in fields:
            raise ValueError(f"revision has unsupported kind: {kind!r}")
        _require_object(data, "revision", required=fields[kind])
        return cls(kind=kind, commit=data.get("commit"), content_sha256=data.get("content_sha256"))


@dataclass(frozen=True)
class SpecRef:
    path: str
    revision: Revision

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "revision": self.revision.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpecRef:
        data = _require_object(data, "spec_ref", required={"path", "revision"})
        return cls(
            path=data["path"],
            revision=Revision.from_dict(data["revision"]),
        )


@dataclass(frozen=True)
class Dependency:
    plan_id: str
    task_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Dependency:
        data = _require_object(data, "dependency", required={"plan_id", "task_id"})
        return cls(
            plan_id=data["plan_id"],
            task_id=data["task_id"],
        )


@dataclass(frozen=True)
class ResultRef:
    kind: str
    commit: str | None = None
    evidence_id: str | None = None
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind}
        if self.kind == "git_commit":
            data["commit"] = self.commit or ""
        elif self.kind == "evidence_reference":
            data["evidence_id"] = self.evidence_id or ""
            data["summary"] = self.summary
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResultRef:
        if not isinstance(data, dict):
            raise ValueError("result_ref must be an object")
        kind = data.get("kind")
        if kind == "git_commit":
            _require_object(data, "result_ref", required={"kind", "commit"})
        elif kind == "evidence_reference":
            _require_object(data, "result_ref", required={"kind", "evidence_id", "summary"})
        else:
            raise ValueError(f"result_ref has unsupported kind: {kind!r}")
        return cls(
            kind=kind,
            commit=data.get("commit"),
            evidence_id=data.get("evidence_id"),
            summary=data.get("summary", ""),
        )


@dataclass(frozen=True)
class TaskScope:
    paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"paths": list(self.paths)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskScope:
        data = _require_object(data, "scope", required={"paths"})
        return cls(paths=list(_require_list(data["paths"], "scope.paths")))


@dataclass
class Clarification:
    id: str
    summary: str
    adoption: str = "pending"
    spec_refs: list[SpecRef] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "adoption": self.adoption,
            "spec_refs": [ref.to_dict() for ref in self.spec_refs],
            "supersedes": list(self.supersedes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Clarification:
        data = _require_object(data, "clarification", required={"id", "summary", "adoption", "spec_refs", "supersedes"})
        return cls(
            id=data["id"],
            summary=data["summary"],
            adoption=data["adoption"],
            spec_refs=[SpecRef.from_dict(r) for r in _require_list(data["spec_refs"], "clarification.spec_refs")],
            supersedes=list(_require_list(data["supersedes"], "clarification.supersedes")),
        )


@dataclass
class Delivery:
    target_ref: str
    accountable_role: str
    disposition: str = "pending"
    reason: str = ""
    results: list[ResultRef] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_ref": self.target_ref,
            "accountable_role": self.accountable_role,
            "disposition": self.disposition,
            "reason": self.reason,
            "results": [res.to_dict() for res in self.results],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Delivery:
        data = _require_object(data, "delivery", required={"target_ref", "accountable_role", "disposition", "reason", "results"})
        return cls(
            target_ref=data["target_ref"],
            accountable_role=data["accountable_role"],
            disposition=data["disposition"],
            reason=data["reason"],
            results=[ResultRef.from_dict(r) for r in _require_list(data["results"], "delivery.results")],
        )


@dataclass
class RepoPlanTask:
    id: str
    title: str
    description: str = ""
    kind: str = "code"
    work_status: str = "planned"
    depends_on: list[Dependency] = field(default_factory=list)
    clarifications: list[Clarification] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    next_action: str = ""
    blocker: str | None = None
    order: int | None = None
    accountable_role: str | None = None
    work_phase: str | None = None
    spec_refs: list[SpecRef] = field(default_factory=list)
    scope: TaskScope | None = None
    results: list[ResultRef] = field(default_factory=list)
    deliveries: dict[str, Delivery] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "work_status": self.work_status,
            "depends_on": [dep.to_dict() for dep in self.depends_on],
            "clarifications": [c.to_dict() for c in self.clarifications],
            "acceptance_criteria": list(self.acceptance_criteria),
            "next_action": self.next_action,
            "blocker": self.blocker,
        }
        if self.order is not None:
            data["order"] = self.order
        if self.accountable_role is not None:
            data["accountable_role"] = self.accountable_role
        if self.work_phase is not None:
            data["work_phase"] = self.work_phase
        if self.spec_refs:
            data["spec_refs"] = [s.to_dict() for s in self.spec_refs]
        if self.scope is not None:
            data["scope"] = self.scope.to_dict()
        if self.results:
            data["results"] = [r.to_dict() for r in self.results]
        if self.deliveries:
            data["deliveries"] = {k: v.to_dict() for k, v in self.deliveries.items()}
        return data

    @classmethod
    def from_dict(cls, task_id: str, data: dict[str, Any]) -> RepoPlanTask:
        data = _require_object(data, "task", required={"title", "description", "kind", "work_status", "depends_on", "clarifications", "acceptance_criteria", "next_action", "blocker"}, allowed={"title", "description", "kind", "work_status", "depends_on", "clarifications", "acceptance_criteria", "next_action", "blocker", "order", "accountable_role", "work_phase", "spec_refs", "scope", "results", "deliveries"})
        deliveries_raw = data.get("deliveries", {})
        if not isinstance(deliveries_raw, dict):
            raise ValueError("task.deliveries must be an object")
        deliveries = {
            del_id: Delivery.from_dict(d_data)
            for del_id, d_data in deliveries_raw.items()
        }
        scope_data = data.get("scope")
        scope = TaskScope.from_dict(scope_data) if scope_data is not None else None

        return cls(
            id=task_id,
            title=data["title"],
            description=data["description"],
            kind=data["kind"],
            work_status=data["work_status"],
            depends_on=[Dependency.from_dict(d) for d in _require_list(data["depends_on"], "task.depends_on")],
            clarifications=[Clarification.from_dict(c) for c in _require_list(data["clarifications"], "task.clarifications")],
            acceptance_criteria=list(_require_list(data["acceptance_criteria"], "task.acceptance_criteria")),
            next_action=data["next_action"],
            blocker=data.get("blocker"),
            order=data.get("order"),
            accountable_role=data.get("accountable_role"),
            work_phase=data.get("work_phase"),
            spec_refs=[SpecRef.from_dict(s) for s in _require_list(data.get("spec_refs", []), "task.spec_refs")],
            scope=scope,
            results=[ResultRef.from_dict(r) for r in _require_list(data.get("results", []), "task.results")],
            deliveries=deliveries,
        )


@dataclass
class RepoPlan:
    id: str
    title: str
    description: str = ""
    lifecycle: str = "draft"
    default_target_ref: str | None = None
    spec_refs: list[SpecRef] = field(default_factory=list)
    tasks: dict[str, RepoPlanTask] = field(default_factory=dict)
    schema_version: int = 1
    accountable_role: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "lifecycle": self.lifecycle,
            "default_target_ref": self.default_target_ref,
            "spec_refs": [s.to_dict() for s in self.spec_refs],
            "tasks": {task_id: task.to_dict() for task_id, task in self.tasks.items()},
        }
        if self.accountable_role is not None:
            data["accountable_role"] = self.accountable_role
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoPlan:
        from .schema_validation import validate_plan_dict

        validate_plan_dict(data)
        tasks_raw = data.get("tasks", {})
        tasks = {
            task_id: RepoPlanTask.from_dict(task_id, task_data)
            for task_id, task_data in tasks_raw.items()
        }
        return cls(
            schema_version=data["schema_version"],
            id=data["id"],
            title=data["title"],
            description=data["description"],
            lifecycle=data["lifecycle"],
            default_target_ref=data["default_target_ref"],
            spec_refs=[SpecRef.from_dict(s) for s in _require_list(data["spec_refs"], "plan.spec_refs")],
            tasks=tasks,
            accountable_role=data.get("accountable_role"),
        )
