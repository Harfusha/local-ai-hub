"""Bridge between Agent OS execution tasks and repository-owned plan files."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from local_ai_hub.agent_verification import (
    VerificationReceipt,
    VerificationStore,
)
from local_ai_hub.file_locks import exclusive_file_update

from .models import (
    ClarificationAdoption,
    TaskWorkPhase,
    TaskWorkStatus,
)
from .schema_validation import RepoPlanConflictError, RepoPlanNotFoundError, validate_repo_path
from .storage import RepoPlanStorage, compute_file_sha256, get_git_context

logger = logging.getLogger(__name__)

DISALLOWED_PASS_COMMANDS = frozenset({"echo pass", "echo ok", "echo true", "echo 1", "true", ":"})
# We will define it as regex or set:
DISALLOWED_COMMAND_REGEX = re.compile(r"^\s*(?:echo\s+pass|echo\s+ok|echo\s+true|echo\s+1|true|:)\s*$", re.IGNORECASE)


@dataclass
class TaskBinding:
    task_id: str  # Agent OS task_id
    repo_root: str
    plan_id: str
    plan_task_id: str
    plan_rel_path: str
    session_id: str = ""
    branch_at_bind: str = ""
    adopted_plan_revision: str = ""
    contract_revision: int = 1
    bound_at: float = field(default_factory=time.time)
    lineage: list[str] = field(default_factory=list)  # previous superseded task_ids

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskBinding:
        return cls(**data)


class TaskBindingManager:
    """Manages associations between Agent OS execution tasks and plan file tasks."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self._binding_rel_path = ".local-ai-hub/local/task_bindings.json"
        validate_repo_path(self._binding_rel_path, repo_root=self.repo_root)
        self._binding_file = self.repo_root / self._binding_rel_path
        self._bindings: dict[str, TaskBinding] = {}
        self._load()

    def _load(self) -> None:
        self._bindings = self._read_disk()

    def _read_disk(self) -> dict[str, TaskBinding]:
        if not self._binding_file.exists():
            return {}
        if self._binding_file.is_symlink() or self._binding_file.stat().st_size > 1024 * 1024:
            raise ValueError("task binding file is unsafe or exceeds 1 MiB")
        raw = self._binding_file.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("task binding file must be an object")
        bindings: dict[str, TaskBinding] = {}
        for tid, bdata in data.items():
            if not isinstance(tid, str) or not isinstance(bdata, dict):
                raise ValueError("task binding file contains an invalid entry")
            binding = TaskBinding.from_dict(bdata)
            if tid != binding.task_id or binding.repo_root != str(self.repo_root):
                raise ValueError("task binding identity or repository root mismatch")
            bindings[tid] = binding
        return bindings

    def _save(
        self, binding: TaskBinding, task_store: Any | None = None, *, check_plan_ownership: bool = True
    ) -> TaskBinding:
        validate_repo_path(self._binding_rel_path, repo_root=self.repo_root)
        self._binding_file.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_file_update(self._binding_file):
            current = self._read_disk()
            previous_self = current.get(binding.task_id)
            if previous_self and (previous_self.plan_id, previous_self.plan_task_id) != (
                binding.plan_id, binding.plan_task_id
            ):
                raise ValueError("execution task is already bound to another plan task")
            if previous_self and binding.contract_revision < previous_self.contract_revision:
                raise ValueError("contract revision cannot move backwards")
            if previous_self:
                if previous_self.plan_rel_path != binding.plan_rel_path:
                    raise ValueError("execution binding cannot move to a different plan file")
                if previous_self.session_id and binding.session_id and previous_self.session_id != binding.session_id:
                    raise ValueError("execution binding session cannot be replaced")
                binding.session_id = binding.session_id or previous_self.session_id
                binding.branch_at_bind = previous_self.branch_at_bind or binding.branch_at_bind
                prior_lineage = previous_self.lineage
                proposed_lineage = binding.lineage
                if prior_lineage[:len(proposed_lineage)] == proposed_lineage:
                    binding.lineage = list(prior_lineage)
                elif proposed_lineage[:len(prior_lineage)] != prior_lineage:
                    raise ValueError("execution binding lineage conflicts with recorded history")
                binding.bound_at = previous_self.bound_at
            for existing in current.values():
                if existing.task_id == binding.task_id:
                    continue
                if binding.session_id and existing.session_id == binding.session_id:
                    raise ValueError("session is already bound to another execution task")
                if not check_plan_ownership and previous_self is not None:
                    continue
                if (existing.plan_id, existing.plan_task_id) != (binding.plan_id, binding.plan_task_id):
                    continue
                prior = task_store.get(existing.task_id) if task_store is not None else None
                if prior is None:
                    raise ValueError("plan task has an unresolved prior binding; reconcile it before starting")
                prior_status = getattr(getattr(prior, "status", None), "value", None)
                if prior_status == "failed":
                    raise ValueError("plan task has a failed execution binding that can resume; reconcile it before starting")
                if prior_status not in {"completed", "cancelled"}:
                    raise ValueError("plan task already has an active execution binding")
            if previous_self and binding.to_dict() == previous_self.to_dict():
                self._bindings = current
                return previous_self
            current[binding.task_id] = binding
            raw = json.dumps({k: v.to_dict() for k, v in current.items()}, indent=2, sort_keys=True)
            temp_path = self._binding_file.parent / f".tmp_bindings_{uuid.uuid4().hex}"
            try:
                with temp_path.open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_path, self._binding_file)
                self._bindings = current
            finally:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
            return binding

    def bind_task(
        self,
        task_id: str,
        plan_id: str,
        plan_task_id: str,
        plan_rel_path: str,
        contract_revision: int = 1,
        lineage: list[str] | None = None,
        session_id: str = "",
        branch_at_bind: str = "",
        adopted_plan_revision: str = "",
        task_store: Any | None = None,
    ) -> TaskBinding:
        for label, value in (("task_id", task_id), ("plan_id", plan_id),
                             ("plan_task_id", plan_task_id), ("plan_rel_path", plan_rel_path)):
            if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
                raise ValueError(f"{label} must be a canonical nonempty string")
        if not isinstance(session_id, str) or session_id != session_id.strip() or "\x00" in session_id:
            raise ValueError("session_id must be a canonical string")
        binding = TaskBinding(
            task_id=task_id,
            repo_root=str(self.repo_root),
            plan_id=plan_id,
            plan_task_id=plan_task_id,
            plan_rel_path=plan_rel_path,
            session_id=session_id,
            branch_at_bind=branch_at_bind,
            adopted_plan_revision=adopted_plan_revision,
            contract_revision=contract_revision,
            bound_at=time.time(),
            lineage=list(lineage or []),
        )
        return self._save(binding, task_store=task_store)

    def get_binding(self, task_id: str) -> TaskBinding | None:
        return self._bindings.get(task_id)

    def get_session_binding(self, session_id: str) -> TaskBinding | None:
        if not isinstance(session_id, str) or not session_id or session_id != session_id.strip():
            return None
        matches = [binding for binding in self._bindings.values()
                   if binding.session_id == session_id]
        if len(matches) > 1:
            raise RuntimeError("session has ambiguous task bindings")
        return matches[0] if matches else None

def _persist_pending_contract_reconciliation(
    storage: RepoPlanStorage, binding: TaskBinding, payload: dict[str, Any]
) -> Path:
    """Persist a safe, atomic local retry record when the task DB update fails."""
    root = storage.repo_root.resolve(strict=True)
    hub_dir = root / ".local-ai-hub"
    local_dir = hub_dir / "local"
    pending_dir = local_dir / "pending-contract-reconciliation"
    for directory in (hub_dir, local_dir, pending_dir):
        if directory.is_symlink():
            raise ValueError("pending reconciliation path cannot traverse a symlink")
    pending_dir.mkdir(parents=True, exist_ok=True)
    resolved_pending = pending_dir.resolve(strict=True)
    if not resolved_pending.is_relative_to(root):
        raise ValueError("pending reconciliation path escapes repository root")
    # Task IDs are untrusted identifiers and never become path components.
    name = hashlib.sha256(binding.task_id.encode("utf-8")).hexdigest() + ".json"
    target = resolved_pending / name
    encoded = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")
    with exclusive_file_update(target):
        temporary = resolved_pending / f".{name}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    return target


def bind_plan_execution(
    task_store: Any,
    *,
    root: str,
    task_id: str,
    plan_id: str,
    plan_task_id: str,
    expected_revision: str | None = None,
    session_id: str = "",
) -> dict[str, Any]:
    """Bind a saved plan task to one real Agent OS task and session."""
    from local_ai_hub.agent_tasks import _task_scope_root
    from local_ai_hub.repository_scope import canonical_repository_root
    from .workspace import RepoPlanWorkspace

    canonical = str(canonical_repository_root(str(root)))
    if not isinstance(task_id, str) or not task_id or task_id != task_id.strip():
        raise ValueError("task_id must be a canonical nonempty string")
    execution = task_store.get(task_id)
    if execution is None:
        raise KeyError(f"Task '{task_id}' not found in task store")
    if _task_scope_root(execution) != canonical:
        raise ValueError("root does not match the server-managed task scope")
    actual_session = execution.context.session_id
    if not actual_session or (session_id and session_id != actual_session):
        raise ValueError("session_id must match the execution task's persisted session")

    workspace = RepoPlanWorkspace(canonical)
    plan = workspace.get_plan(plan_id)
    current_revision = plan["file_revision"]
    if expected_revision is not None and expected_revision != current_revision:
        raise ValueError("expected_revision conflicts with the current plan revision")
    task_data = plan["plan"].get("tasks", {}).get(plan_task_id)
    if task_data is None:
        raise RepoPlanNotFoundError(f"Task '{plan_task_id}' not found in plan '{plan_id}'")
    if tuple(task_data.get("acceptance_criteria", ())) != tuple(execution.contract.acceptance_criteria):
        raise ValueError("plan task criteria must match the Agent OS contract before binding")

    manager = TaskBindingManager(canonical)
    existing_task = manager.get_binding(task_id)
    if existing_task and (existing_task.plan_id, existing_task.plan_task_id) != (plan_id, plan_task_id):
        raise ValueError("execution task is already bound to another plan task")
    branch, _ = get_git_context(Path(canonical))
    binding = manager.bind_task(
        task_id=task_id,
        plan_id=plan_id,
        plan_task_id=plan_task_id,
        plan_rel_path=plan["rel_path"],
        session_id=actual_session,
        branch_at_bind=branch or "",
        adopted_plan_revision=current_revision,
        contract_revision=int(execution.checkpoint.state_data.get("contract_revision", 1)),
        task_store=task_store,
    )
    try:
        sync_state = task_store._sync_project_plan_checkpoint(execution, only_if_pending=existing_task is not None)
        current_revision = workspace.get_plan(plan_id)["file_revision"]
    except RepoPlanConflictError as exc:
        raise RepoPlanConflictError(
            "Plan binding was persisted; checkpoint sync conflict preserved newer plan edits"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            "Plan binding was persisted, but checkpoint synchronization failed; "
            "retry this same binding after resolving the error"
        ) from exc
    return {"success": True, "root": canonical, "task_id": task_id,
            "plan_id": plan_id, "plan_task_id": plan_task_id,
            "session_id": actual_session, "file_revision": current_revision,
            "binding": binding.to_dict(), "checkpoint_sync": sync_state}


def map_agent_status_to_plan_status(
    agent_status: str,
    has_open_deliveries: bool = False,
    phase: str = "",
    next_action: str = "",
) -> str:
    """Map Agent OS task status to repo plan task work_status."""
    status = str(agent_status or "").lower()
    phase_clean = str(phase or "").lower()
    next_clean = str(next_action or "").lower()

    if status in {"completed", "done"}:
        # If open deliveries remain, it is source_ready; if all integrated, done.
        return TaskWorkStatus.SOURCE_READY.value if has_open_deliveries else TaskWorkStatus.DONE.value
    if status == "cancelled":
        return TaskWorkStatus.CANCELLED.value
    if status in {"failed", "blocked"}:
        return TaskWorkStatus.BLOCKED.value
    if has_open_deliveries and (
        phase_clean in {"source_ready", "integration"}
        or (phase_clean == "verification" and ("integration" in next_clean or "await" in next_clean or "ready" in next_clean))
    ):
        return TaskWorkStatus.SOURCE_READY.value
    if status in {"active", "in_progress", "verifying"}:
        return TaskWorkStatus.IN_PROGRESS.value
    if phase_clean and phase_clean in {"implementing", "review", "discovery", "verification", "implementation"}:
        return TaskWorkStatus.IN_PROGRESS.value
    if status == "waiting":
        return TaskWorkStatus.READY.value
    return TaskWorkStatus.PLANNED.value


def project_checkpoint_fields(
    task_data: dict[str, Any],
    agent_status: str,
    phase: str = "",
    next_action: str = "",
    blocker: str | None = None,
) -> None:
    """Project checkpoint fields onto an already-loaded plan task."""
    deliveries = task_data.get("deliveries", {})
    has_open_deliveries = any(
        isinstance(d, dict) and d.get("disposition") == "pending"
        for d in deliveries.values()
    )

    new_work_status = map_agent_status_to_plan_status(agent_status, has_open_deliveries, phase=phase, next_action=next_action)
    task_data["work_status"] = new_work_status

    if phase:
        # map common phases
        phase_clean = str(phase).lower()
        if "discovery" in phase_clean or "baseline" in phase_clean:
            task_data["work_phase"] = TaskWorkPhase.DISCOVERY.value
        elif "verif" in phase_clean or "test" in phase_clean:
            task_data["work_phase"] = TaskWorkPhase.VERIFICATION.value
        elif "integrat" in phase_clean or "merge" in phase_clean:
            task_data["work_phase"] = TaskWorkPhase.INTEGRATION.value
        else:
            task_data["work_phase"] = TaskWorkPhase.IMPLEMENTATION.value

    if next_action is not None:
        task_data["next_action"] = str(next_action)
    if blocker is not None:
        task_data["blocker"] = str(blocker) if blocker else None


def sync_checkpoint_to_plan(
    storage: RepoPlanStorage,
    binding: TaskBinding,
    agent_status: str,
    phase: str = "",
    next_action: str = "",
    blocker: str | None = None,
    owner: str = "agent",
    expected_plan_revision: str | None = None,
) -> dict[str, Any]:
    """Update bound repo plan file task from an Agent OS checkpoint."""
    plan_dict, current_rev = storage.read_plan_file(binding.plan_rel_path)
    if expected_plan_revision is not None and expected_plan_revision != current_rev:
        raise RepoPlanConflictError("plan changed before checkpoint synchronization")
    tasks = plan_dict.get("tasks", {})
    if binding.plan_task_id not in tasks:
        raise RepoPlanNotFoundError(
            f"Bound task '{binding.plan_task_id}' not found in plan '{binding.plan_id}'"
        )
    project_checkpoint_fields(tasks[binding.plan_task_id], agent_status, phase, next_action, blocker)
    return storage.save_plan_file(
        binding.plan_rel_path,
        plan_dict,
        expected_revision=current_rev,
        owner=owner,
    )


def reconcile_contract_revision(
    storage: RepoPlanStorage,
    binding: TaskBinding,
    new_acceptance_criteria: list[str],
    reason: str,
    *,
    task_store: Any | None = None,
    spec_rel_path: str | None = None,
    spec_content: str | None = None,
    owner: str = "agent",
    idempotency_key: str = "",
    expected_plan_revision: str | None = None,
    expected_spec_revision: str | None = None,
    clarification_id: str | None = None,
) -> tuple[dict[str, Any], int]:
    """Persist an operator clarification into both the Git plan and real task contract."""
    if task_store is None:
        raise ValueError("task_store is required to reconcile the actual execution contract")
    if not isinstance(new_acceptance_criteria, list) or any(
        type(item) is not str or not item or item != item.strip() or "\x00" in item
        for item in new_acceptance_criteria
    ):
        raise ValueError("new acceptance criteria must be canonical nonempty strings")
    if not isinstance(reason, str) or not reason.strip() or "\x00" in reason:
        raise ValueError("reason must be a nonempty string")
    plan_dict, current_rev = storage.read_plan_file(binding.plan_rel_path)
    if expected_plan_revision is not None and current_rev != expected_plan_revision:
        raise RepoPlanConflictError("plan revision changed before reconciliation")
    tasks = plan_dict.get("tasks", {})
    if binding.plan_task_id not in tasks:
        raise RepoPlanNotFoundError(
            f"Bound task '{binding.plan_task_id}' not found in plan '{binding.plan_id}'"
        )

    task_data = tasks[binding.plan_task_id]
    execution = task_store.get(binding.task_id)
    if execution is None:
        raise KeyError(f"Task '{binding.task_id}' not found in task store")
    from local_ai_hub.agent_tasks import _task_scope_root

    if _task_scope_root(execution) != str(storage.repo_root):
        raise ValueError("bound task repository scope no longer matches plan workspace")
    if owner and execution.owner and owner != execution.owner:
        raise ValueError("task owner mismatch during contract reconciliation")
    if tuple(task_data.get("acceptance_criteria", ())) != tuple(execution.contract.acceptance_criteria):
        raise ValueError("plan and Agent OS criteria diverged before reconciliation")
    current_contract_revision = execution.checkpoint.state_data.get("contract_revision", 1)
    if type(current_contract_revision) is not int or current_contract_revision != binding.contract_revision:
        raise ValueError("binding contract revision is stale; reload before reconciling")

    # Create Clarification
    change_id = clarification_id or f"change_{uuid.uuid4().hex[:10]}"
    spec_refs = []
    if spec_rel_path:
        validate_repo_path(spec_rel_path, repo_root=storage.repo_root)
        full_spec = storage.repo_root / spec_rel_path
        if spec_content is None:
            raise ValueError("spec_content is required when spec_rel_path is supplied")
        if full_spec.is_symlink():
            raise ValueError("spec path cannot be a symlink")
        spec_sha = hashlib.sha256(spec_content.encode("utf-8")).hexdigest()
        rev_dict = {"kind": "working", "content_sha256": spec_sha}
        spec_refs.append({"path": spec_rel_path, "revision": rev_dict})

    clarification = {
        "id": change_id,
        "summary": reason,
        "adoption": ClarificationAdoption.ADOPTED.value,
        "spec_refs": spec_refs,
        "supersedes": [],
    }
    clarifications = task_data.setdefault("clarifications", [])
    clarifications.append(clarification)

    # Update acceptance criteria
    task_data["acceptance_criteria"] = list(new_acceptance_criteria)

    # Plan/spec become the durable user clarification before execution resumes.
    if spec_rel_path and spec_content is not None:
        spec_path = storage.repo_root / spec_rel_path
        expected_spec_rev = (expected_spec_revision if expected_spec_revision is not None
                             else compute_file_sha256(spec_path) if spec_path.exists() else "")
        save_res = storage.save_spec_and_plan(
            spec_rel_path,
            spec_content,
            binding.plan_rel_path,
            plan_dict,
            expected_spec_rev=expected_spec_rev,
            expected_plan_rev=current_rev,
            owner=owner,
            idempotency_key=idempotency_key,
        )
    else:
        save_res = storage.save_plan_file(
            binding.plan_rel_path,
            plan_dict,
            expected_revision=current_rev,
            owner=owner,
            idempotency_key=idempotency_key,
        )
    try:
        revised = task_store.revise_contract(
            binding.task_id,
            new_acceptance_criteria,
            actor=execution.owner,
            reason=reason,
            expected_revision=current_contract_revision,
        )
    except Exception as exc:
        payload = {"task_id": binding.task_id, "plan_id": binding.plan_id,
                   "plan_task_id": binding.plan_task_id,
                   "contract_revision": current_contract_revision + 1,
                   "acceptance_criteria": new_acceptance_criteria,
                   "reason": reason, "plan_revision": save_res.get("plan_revision", save_res.get("file_revision", "")),
                   "error": str(exc)}
        try:
            _persist_pending_contract_reconciliation(storage, binding, payload)
        except Exception as persist_exc:
            raise RuntimeError(
                "clarification is saved to the Git plan/spec, but both Agent OS reconciliation "
                "and its local retry record failed"
            ) from persist_exc
        raise RuntimeError(
            "clarification is saved to the Git plan/spec, but Agent OS contract reconciliation is pending"
        ) from exc
    binding.contract_revision = revised.checkpoint.state_data["contract_revision"]
    binding.adopted_plan_revision = save_res.get("plan_revision", save_res.get("file_revision", ""))
    binding_manager = TaskBindingManager(storage.repo_root)
    try:
        binding_manager._save(binding, task_store=task_store, check_plan_ownership=False)
    except Exception as exc:
        payload = {"task_id": binding.task_id, "plan_id": binding.plan_id,
                   "plan_task_id": binding.plan_task_id,
                   "contract_revision": binding.contract_revision,
                   "acceptance_criteria": new_acceptance_criteria,
                   "reason": reason, "plan_revision": binding.adopted_plan_revision,
                   "error": str(exc)}
        try:
            _persist_pending_contract_reconciliation(storage, binding, payload)
        except Exception as persist_exc:
            raise RuntimeError("contract was revised but binding and retry-record persistence failed") from persist_exc
        raise RuntimeError("contract was revised, but binding reconciliation is pending") from exc
    return save_res, binding.contract_revision


def reconcile_task_steering(
    task_store: Any, *, root: str, task_id: str, steering_id: str,
    spec_rel_path: str, spec_content: str, acceptance_criteria: list[str],
    expected_revision: str, expected_spec_revision: str, summary: str = "",
) -> dict[str, Any]:
    """Reconcile an explicitly revision-bound operator clarification."""
    from local_ai_hub.agent_tasks import _task_scope_root
    from local_ai_hub.repository_scope import canonical_repository_root
    from .workspace import RepoPlanWorkspace

    if type(root) is not str or not root:
        raise ValueError("root must be an explicit absolute path")
    canonical = str(canonical_repository_root(root))
    if type(task_id) is not str or not task_id or task_id != task_id.strip() or "\x00" in task_id:
        raise ValueError("task_id must be a canonical nonempty string")
    if type(steering_id) is not str or not steering_id or steering_id != steering_id.strip() or len(steering_id) > 256 or "\x00" in steering_id:
        raise ValueError("steering_id must be a canonical nonempty string")
    if type(expected_revision) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected_revision):
        raise ValueError("expected_revision must be a SHA-256 revision")
    if type(expected_spec_revision) is not str or (expected_spec_revision != "" and not re.fullmatch(r"[0-9a-f]{64}", expected_spec_revision)):
        raise ValueError("expected_spec_revision must be empty or a SHA-256 revision")
    if type(spec_content) is not str or type(acceptance_criteria) is not list or type(summary) is not str:
        raise ValueError("invalid steering content or criteria")
    validate_repo_path(spec_rel_path, repo_root=Path(canonical))
    requested_spec = Path(canonical) / spec_rel_path
    for component in (requested_spec, *requested_spec.parents):
        if component == Path(canonical).parent:
            break
        if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
            raise ValueError("steering spec path contains a link")
    execution = task_store.get(task_id)
    if execution is None:
        raise KeyError(f"Task '{task_id}' not found in task store")
    if _task_scope_root(execution) != canonical:
        raise ValueError("root does not match the server-managed task scope")
    manager = TaskBindingManager(canonical)
    binding = manager.get_binding(task_id)
    if binding is None or not execution.context.session_id or binding.session_id != execution.context.session_id:
        raise ValueError("task must have a matching bound session")

    payload = {"root": canonical, "task_id": task_id, "session_id": binding.session_id,
               "steering_id": steering_id, "spec_rel_path": spec_rel_path,
               "spec_sha256": hashlib.sha256(spec_content.encode("utf-8")).hexdigest(),
               "acceptance_criteria": acceptance_criteria, "expected_revision": expected_revision,
               "expected_spec_revision": expected_spec_revision, "summary": summary}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                             separators=(",", ":")).encode("utf-8")).hexdigest()
    prefix = "change_" + hashlib.sha256(steering_id.encode("utf-8")).hexdigest()[:20] + "_"
    change_base = prefix + fingerprint[:32] + "_r"
    storage = RepoPlanWorkspace(canonical).storage
    plan, current_revision = storage.read_plan_file(binding.plan_rel_path)
    task_data = plan.get("tasks", {}).get(binding.plan_task_id)
    if not isinstance(task_data, dict):
        raise RepoPlanNotFoundError("bound plan task no longer exists")
    matches = [item for item in task_data.get("clarifications", [])
               if isinstance(item, dict) and str(item.get("id", "")).startswith(prefix)]
    if matches:
        change_id = matches[0].get("id") if len(matches) == 1 else None
        if type(change_id) is not str or not re.fullmatch(re.escape(change_base) + r"[1-9][0-9]*", change_id):
            raise RepoPlanConflictError("steering_id was already used for another request")
        expected_clarification = {
            "id": change_id,
            "summary": summary.strip() or f"Operator steering {steering_id}",
            "adoption": ClarificationAdoption.ADOPTED.value,
            "spec_refs": [{"path": spec_rel_path, "revision": {
                "kind": "working", "content_sha256": payload["spec_sha256"]}}],
            "supersedes": [],
        }
        if matches[0] != expected_clarification:
            raise RepoPlanConflictError("persisted steering clarification no longer matches the request")
        intended_revision = int(change_id[len(change_base):])
        spec_path = Path(canonical) / spec_rel_path
        if (not spec_path.is_file() or spec_path.is_symlink()
                or compute_file_sha256(spec_path) != payload["spec_sha256"]
                or task_data.get("acceptance_criteria") != acceptance_criteria):
            raise RepoPlanConflictError("persisted steering no longer matches the request")
        revision = execution.checkpoint.state_data.get("contract_revision", 1)
        pending_name = hashlib.sha256(task_id.encode("utf-8")).hexdigest() + ".json"
        pending_rel = f".local-ai-hub/local/pending-contract-reconciliation/{pending_name}"
        validate_repo_path(pending_rel, repo_root=Path(canonical))
        pending_path = Path(canonical) / pending_rel
        for directory in (pending_path, *pending_path.parents):
            if directory == Path(canonical).parent:
                break
            if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)():
                raise ValueError("pending reconciliation path contains a link")
        if (pending_path.exists() or tuple(execution.contract.acceptance_criteria) != tuple(acceptance_criteria)
                or revision != binding.contract_revision or revision != intended_revision):
            if not pending_path.is_file() or pending_path.stat().st_size > 1024 * 1024:
                raise RuntimeError("persisted steering reconciliation is pending without a safe retry record")
            with exclusive_file_update(pending_path):
                pending = json.loads(pending_path.read_text(encoding="utf-8"))
                if not isinstance(pending, dict):
                    raise ValueError("pending reconciliation record must be an object")
                target_revision = pending.get("contract_revision")
                reason = summary.strip() or f"Operator steering {steering_id}"
                if (pending.get("task_id") != task_id or pending.get("plan_id") != binding.plan_id
                        or pending.get("plan_task_id") != binding.plan_task_id
                        or pending.get("acceptance_criteria") != acceptance_criteria
                        or pending.get("reason") != reason
                        or type(target_revision) is not int or target_revision != intended_revision):
                    raise RepoPlanConflictError("pending reconciliation record does not match steering")
                execution = task_store.get(task_id)
                projected_revision = pending.get("projected_plan_revision")
                if projected_revision is not None:
                    from .schema_validation import serialize_plan_json

                    baseline = pending.get("projection_base_plan")
                    if (not isinstance(baseline, dict)
                            or hashlib.sha256(serialize_plan_json(baseline).encode("utf-8")).hexdigest() != pending.get("plan_revision")):
                        raise RepoPlanConflictError("pending projection baseline does not match plan revision")
                    projected = json.loads(json.dumps(baseline))
                    projected_task = projected.get("tasks", {}).get(binding.plan_task_id)
                    if not isinstance(projected_task, dict):
                        raise RepoPlanConflictError("pending projection has no bound plan task")
                    project_checkpoint_fields(
                        projected_task, execution.status.value, execution.checkpoint.phase,
                        execution.checkpoint.next_action,
                        execution.checkpoint.blockers[0] if execution.checkpoint.blockers else "",
                    )
                    if hashlib.sha256(serialize_plan_json(projected).encode("utf-8")).hexdigest() != projected_revision:
                        raise RepoPlanConflictError("pending projected plan revision is invalid")
                if (pending.get("plan_revision") != current_revision
                        and not (projected_revision == current_revision
                                 and execution.checkpoint.state_data.get("contract_revision") == target_revision
                                 and tuple(execution.contract.acceptance_criteria) == tuple(acceptance_criteria))):
                    raise RepoPlanConflictError("pending reconciliation record does not match steering")

                def save_pending() -> None:
                    encoded = json.dumps(pending, sort_keys=True, indent=2).encode("utf-8")
                    if len(encoded) > 1024 * 1024:
                        raise ValueError("pending reconciliation record exceeds size limit")
                    temporary = pending_path.parent / f".{pending_path.name}.{uuid.uuid4().hex}.tmp"
                    try:
                        with temporary.open("xb") as stream:
                            stream.write(encoded)
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.replace(temporary, pending_path)
                    finally:
                        temporary.unlink(missing_ok=True)

                # Serialize the fresh check and contract update with plan writers.
                with exclusive_file_update(storage._lock_path, reentrant=True):
                    latest_plan, latest_revision = storage.read_plan_file(binding.plan_rel_path)
                    latest_task = latest_plan.get("tasks", {}).get(binding.plan_task_id, {})
                    if (latest_revision != current_revision
                            or latest_task.get("acceptance_criteria") != acceptance_criteria
                            or not any(item == expected_clarification
                                       for item in latest_task.get("clarifications", []))
                            or not spec_path.is_file() or spec_path.is_symlink()
                            or compute_file_sha256(spec_path) != payload["spec_sha256"]):
                        raise RepoPlanConflictError("plan or spec changed during pending reconciliation")
                    revision = execution.checkpoint.state_data.get("contract_revision", 1)
                    if revision == target_revision - 1 and binding.contract_revision == revision:
                        from .schema_validation import serialize_plan_json

                        projected_plan = json.loads(json.dumps(latest_plan))
                        project_checkpoint_fields(
                            projected_plan["tasks"][binding.plan_task_id], execution.status.value,
                            execution.checkpoint.phase, execution.checkpoint.next_action,
                            execution.checkpoint.blockers[0] if execution.checkpoint.blockers else "",
                        )
                        projected_revision = hashlib.sha256(serialize_plan_json(projected_plan).encode("utf-8")).hexdigest()
                        if pending.get("projected_plan_revision") not in (None, projected_revision):
                            raise RepoPlanConflictError("pending projected plan revision changed")
                        if pending.get("projected_plan_revision") is None:
                            pending["projected_plan_revision"] = projected_revision
                            pending["projection_base_plan"] = latest_plan
                            save_pending()
                        execution = task_store.revise_contract(
                            task_id, acceptance_criteria, actor=execution.owner,
                            reason=reason, expected_revision=revision,
                        )
                        revision = execution.checkpoint.state_data.get("contract_revision")
                    if (revision != target_revision
                            or tuple(execution.contract.acceptance_criteria) != tuple(acceptance_criteria)
                            or binding.contract_revision not in {target_revision - 1, target_revision}):
                        raise RepoPlanConflictError("task contract does not match pending reconciliation")
                    latest_plan, latest_revision = storage.read_plan_file(binding.plan_rel_path)
                    latest_task = latest_plan.get("tasks", {}).get(binding.plan_task_id, {})
                    if (latest_task.get("acceptance_criteria") != acceptance_criteria
                            or not any(item == expected_clarification
                                       for item in latest_task.get("clarifications", []))
                            or not spec_path.is_file() or spec_path.is_symlink()
                            or compute_file_sha256(spec_path) != payload["spec_sha256"]):
                        raise RepoPlanConflictError("plan or spec changed during pending reconciliation")
                    if pending.get("plan_revision") != latest_revision:
                        pending["plan_revision"] = latest_revision
                        pending.pop("projected_plan_revision", None)
                        pending.pop("projection_base_plan", None)
                        save_pending()
                    binding.contract_revision = target_revision
                    binding.adopted_plan_revision = latest_revision
                    manager._save(binding, task_store=task_store, check_plan_ownership=False)
                    pending_path.unlink()
                return {"success": True, "reused": True, "recovered": True,
                        "file_revision": latest_revision, "task_id": task_id,
                        "contract_revision": target_revision}
        return {"success": True, "reused": True, "file_revision": current_revision,
                "task_id": task_id, "contract_revision": revision}

    change_id = change_base + str(binding.contract_revision + 1)
    result, revision = reconcile_contract_revision(
        storage, binding, acceptance_criteria, summary.strip() or f"Operator steering {steering_id}",
        task_store=task_store, spec_rel_path=spec_rel_path, spec_content=spec_content,
        owner=execution.owner, idempotency_key="steering_" + fingerprint,
        expected_plan_revision=expected_revision, expected_spec_revision=expected_spec_revision,
        clarification_id=change_id,
    )
    return {"success": True, "reused": False, "file_revision": result.get("plan_revision", result.get("file_revision", "")),
            "task_id": task_id, "contract_revision": revision}


def record_authentic_native_receipt(
    task_store: Any,
    verification_store: VerificationStore,
    artifact_store: Any,
    task_id: str,
    criterion: str,
    command: str | None,
    root: str | Path,
    *,
    command_id: str | None = None,
    owner: str = "",
    binding: TaskBinding | None = None,
    plan_storage: RepoPlanStorage | None = None,
) -> dict[str, Any]:
    """Import an existing broker receipt; this function cannot execute or mint proof."""
    if not isinstance(command_id, str) or not re.fullmatch(r"[0-9a-f]{32}", command_id):
        raise ValueError("a trusted command_id is required; caller success cannot mint a receipt")
    from local_ai_hub.agent_tasks import _task_scope_root
    from local_ai_hub.repository_scope import canonical_repository_root

    canonical_root = str(canonical_repository_root(str(root)))
    task_state = task_store.get(task_id)
    if task_state is None:
        raise KeyError(f"Task '{task_id}' not found in task store")
    if _task_scope_root(task_state) != canonical_root:
        raise ValueError("Root mismatch: task has a different server-managed repository scope")
    if owner and task_state.owner and owner != task_state.owner:
        raise ValueError("task owner mismatch")
    if not isinstance(criterion, str) or criterion not in task_state.contract.acceptance_criteria:
        raise ValueError("criterion is not in the active Agent OS contract")
    if not verification_store.require_execution_provenance or not callable(
        verification_store.command_execution_record_lookup
    ):
        raise ValueError("trusted CommandBroker provenance lookup is unavailable")
    record = verification_store.command_execution_record_lookup(
        command_id, task_id=task_id, repository_root=canonical_root
    )
    if not isinstance(record, dict):
        raise ValueError("command_id has no persisted broker execution record for this task/root")
    if (
        record.get("schema") != "command_execution_record.v2"
        or record.get("command_id") != command_id
        or record.get("task_id") != task_id
        or record.get("owner") != task_state.owner
        or record.get("criterion") != criterion
        or record.get("repository_root") != canonical_root
        or record.get("exit_code") != 0
        or type(record.get("exit_code")) is not int
        or record.get("cached") is not False
        or not record.get("evidence_id")
        or not record.get("receipt_sha256")
    ):
        raise ValueError("broker command record does not prove a passing current task execution")
    if command is not None and hashlib.sha256(command.encode("utf-8")).hexdigest() != record.get("command_sha256"):
        raise ValueError("command text does not match the persisted broker command digest")
    exported = verification_store.export_receipts(task_id, format="json")
    if not exported.get("success"):
        raise RuntimeError("stored verification receipts are unavailable")
    try:
        receipts = json.loads(exported["output"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("stored verification receipt export is malformed") from exc
    matches = [item for item in receipts if isinstance(item, dict)
               and item.get("command_id") == command_id
               and item.get("task_id") == task_id
               and item.get("criterion") == criterion]
    if len(matches) != 1:
        raise ValueError("no unique persisted receipt matches this broker command")
    receipt = VerificationReceipt.from_dict(matches[0])
    receipt_digest = hashlib.sha256(
        json.dumps(receipt.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if (
        not receipt.passed
        or receipt.owner != task_state.owner
        or receipt.evidence_id != record["evidence_id"]
        or receipt.receipt_id != task_state.verification_receipts.get(criterion)
        or receipt.mutation_generation != task_state.checkpoint.state_data.get("mutation_generation", 0)
        or receipt_digest != record["receipt_sha256"]
    ):
        raise ValueError("persisted receipt is stale or does not match current task mapping")
    if plan_storage is not None and binding is not None:
        if binding.task_id != task_id or binding.repo_root != canonical_root:
            raise ValueError("plan binding does not match the receipt task/root")
    return {"success": True, "receipt_id": receipt.receipt_id, "receipt": receipt,
            "evidence_id": receipt.evidence_id, "command_id": command_id,
            "criterion": criterion, "passed": receipt.passed,
            "evidence_type": receipt.evidence_type}
