"""Data models for repository-owned plan files (repo-plan.v1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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
        return cls(
            kind=data.get("kind", ""),
            commit=data.get("commit"),
            content_sha256=data.get("content_sha256"),
        )


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
        return cls(
            path=data.get("path", ""),
            revision=Revision.from_dict(data.get("revision", {})),
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
        return cls(
            plan_id=data.get("plan_id", ""),
            task_id=data.get("task_id", ""),
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
        return cls(
            kind=data.get("kind", ""),
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
        return cls(paths=list(data.get("paths", [])))


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
        return cls(
            id=data.get("id", ""),
            summary=data.get("summary", ""),
            adoption=data.get("adoption", "pending"),
            spec_refs=[SpecRef.from_dict(r) for r in data.get("spec_refs", [])],
            supersedes=list(data.get("supersedes", [])),
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
        return cls(
            target_ref=data.get("target_ref", ""),
            accountable_role=data.get("accountable_role", ""),
            disposition=data.get("disposition", "pending"),
            reason=data.get("reason", ""),
            results=[ResultRef.from_dict(r) for r in data.get("results", [])],
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
        deliveries_raw = data.get("deliveries", {})
        deliveries = {
            del_id: Delivery.from_dict(d_data)
            for del_id, d_data in deliveries_raw.items()
        }
        scope_data = data.get("scope")
        scope = TaskScope.from_dict(scope_data) if scope_data is not None else None

        return cls(
            id=task_id,
            title=data.get("title", ""),
            description=data.get("description", ""),
            kind=data.get("kind", "code"),
            work_status=data.get("work_status", "planned"),
            depends_on=[Dependency.from_dict(d) for d in data.get("depends_on", [])],
            clarifications=[Clarification.from_dict(c) for c in data.get("clarifications", [])],
            acceptance_criteria=list(data.get("acceptance_criteria", [])),
            next_action=data.get("next_action", ""),
            blocker=data.get("blocker"),
            order=data.get("order"),
            accountable_role=data.get("accountable_role"),
            work_phase=data.get("work_phase"),
            spec_refs=[SpecRef.from_dict(s) for s in data.get("spec_refs", [])],
            scope=scope,
            results=[ResultRef.from_dict(r) for r in data.get("results", [])],
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
        tasks_raw = data.get("tasks", {})
        tasks = {
            task_id: RepoPlanTask.from_dict(task_id, task_data)
            for task_id, task_data in tasks_raw.items()
        }
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            id=data.get("id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            lifecycle=data.get("lifecycle", "draft"),
            default_target_ref=data.get("default_target_ref"),
            spec_refs=[SpecRef.from_dict(s) for s in data.get("spec_refs", [])],
            tasks=tasks,
            accountable_role=data.get("accountable_role"),
        )
