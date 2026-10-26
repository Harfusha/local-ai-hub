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
from .schema_validation import RepoPlanNotFoundError
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
        self._binding_file = self.repo_root / ".local-ai-hub" / "local" / "task_bindings.json"
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

    def _save(self) -> None:
        self._binding_file.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_file_update(self._binding_file):
            current = self._read_disk()
            current.update(self._bindings)
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
        for current in self._bindings.values():
            if session_id and current.session_id == session_id and current.task_id != task_id:
                raise ValueError("session is already bound to another execution task")
        self._bindings[task_id] = binding
        self._save()
        return binding

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

    def find_binding_by_plan_task(self, plan_id: str, plan_task_id: str) -> TaskBinding | None:
        for b in self._bindings.values():
            if b.plan_id == plan_id and b.plan_task_id == plan_task_id:
                return b
        return None


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
    current_owner = manager.find_binding_by_plan_task(plan_id, plan_task_id)
    if current_owner and current_owner.task_id != task_id:
        previous = task_store.get(current_owner.task_id)
        if previous is not None and previous.status.value not in {"completed", "failed", "cancelled"}:
            raise ValueError("plan task already has an active execution binding")

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
    )
    return {"success": True, "root": canonical, "task_id": task_id,
            "plan_id": plan_id, "plan_task_id": plan_task_id,
            "session_id": actual_session, "file_revision": current_revision,
            "binding": binding.to_dict()}


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


def sync_checkpoint_to_plan(
    storage: RepoPlanStorage,
    binding: TaskBinding,
    agent_status: str,
    phase: str = "",
    next_action: str = "",
    blocker: str | None = None,
    owner: str = "agent",
) -> dict[str, Any]:
    """Update bound repo plan file task from an Agent OS checkpoint."""
    plan_dict, current_rev = storage.read_plan_file(binding.plan_rel_path)
    tasks = plan_dict.get("tasks", {})
    if binding.plan_task_id not in tasks:
        raise RepoPlanNotFoundError(
            f"Bound task '{binding.plan_task_id}' not found in plan '{binding.plan_id}'"
        )

    task_data = tasks[binding.plan_task_id]
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
    change_id = f"change_{uuid.uuid4().hex[:10]}"
    spec_refs = []
    if spec_rel_path:
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
        expected_spec_rev = compute_file_sha256(spec_path) if spec_path.exists() else ""
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
                   "reason": reason, "plan_revision": save_res.get("file_revision", ""),
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
    binding.adopted_plan_revision = save_res.get("file_revision", "")
    binding_manager = TaskBindingManager(storage.repo_root)
    binding_manager._bindings[binding.task_id] = binding
    binding_manager._save()
    return save_res, binding.contract_revision


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
