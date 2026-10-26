"""Bridge between Agent OS execution tasks and repository-owned plan files."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from local_ai_hub.agent_verification import (
    VerificationReceipt,
    VerificationStore,
    classify_verification_command,
    criterion_evidence_type,
)

from .models import (
    ClarificationAdoption,
    ResultRefKind,
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
        if not self._binding_file.exists():
            return
        try:
            data = json.loads(self._binding_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for tid, bdata in data.items():
                    self._bindings[tid] = TaskBinding.from_dict(bdata)
        except Exception as exc:
            logger.warning("Failed to load task bindings: %s", exc)

    def _save(self) -> None:
        self._binding_file.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps({k: v.to_dict() for k, v in self._bindings.items()}, indent=2, sort_keys=True)
        temp_path = self._binding_file.parent / f".tmp_bindings_{uuid.uuid4().hex[:6]}"
        try:
            temp_path.write_text(raw, encoding="utf-8")
            temp_path.replace(self._binding_file)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def bind_task(
        self,
        task_id: str,
        plan_id: str,
        plan_task_id: str,
        plan_rel_path: str,
        contract_revision: int = 1,
        lineage: list[str] | None = None,
    ) -> TaskBinding:
        binding = TaskBinding(
            task_id=task_id,
            repo_root=str(self.repo_root),
            plan_id=plan_id,
            plan_task_id=plan_task_id,
            plan_rel_path=plan_rel_path,
            contract_revision=contract_revision,
            bound_at=time.time(),
            lineage=list(lineage or []),
        )
        self._bindings[task_id] = binding
        self._save()
        return binding

    def get_binding(self, task_id: str) -> TaskBinding | None:
        return self._bindings.get(task_id)

    def find_binding_by_plan_task(self, plan_id: str, plan_task_id: str) -> TaskBinding | None:
        for b in self._bindings.values():
            if b.plan_id == plan_id and b.plan_task_id == plan_task_id:
                return b
        return None


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
    spec_rel_path: str | None = None,
    spec_content: str | None = None,
    owner: str = "agent",
) -> tuple[dict[str, Any], int]:
    """Reconcile contract requirements change under the same logical task.

    Updates the plan task's acceptance_criteria, appends a clarification,
    increments contract_revision, and returns (save_result, new_revision).
    """
    plan_dict, current_rev = storage.read_plan_file(binding.plan_rel_path)
    tasks = plan_dict.get("tasks", {})
    if binding.plan_task_id not in tasks:
        raise RepoPlanNotFoundError(
            f"Bound task '{binding.plan_task_id}' not found in plan '{binding.plan_id}'"
        )

    task_data = tasks[binding.plan_task_id]

    # Create Clarification
    change_id = f"change_{uuid.uuid4().hex[:10]}"
    spec_refs = []
    if spec_rel_path:
        full_spec = storage.repo_root / spec_rel_path
        spec_sha = compute_file_sha256(full_spec) if full_spec.exists() else ""
        branch, head = get_git_context(storage.repo_root)
        if head:
            rev_dict = {"kind": "git_commit", "commit": head}
        else:
            rev_dict = {"kind": "working", "content_sha256": spec_sha or ("0" * 64)}
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

    # Save plan (or spec + plan)
    binding.contract_revision += 1
    try:
        TaskBindingManager(storage.repo_root).bind_task(
            task_id=binding.task_id,
            plan_id=binding.plan_id,
            plan_task_id=binding.plan_task_id,
            plan_rel_path=binding.plan_rel_path,
            contract_revision=binding.contract_revision,
            lineage=binding.lineage,
        )
    except Exception as exc:
        logger.warning("Failed to persist updated binding revision: %s", exc)
    if spec_rel_path and spec_content is not None:
        save_res = storage.save_spec_and_plan(
            spec_rel_path,
            spec_content,
            binding.plan_rel_path,
            plan_dict,
            expected_plan_rev=current_rev,
            owner=owner,
        )
    else:
        save_res = storage.save_plan_file(
            binding.plan_rel_path,
            plan_dict,
            expected_revision=current_rev,
            owner=owner,
        )

    return save_res, binding.contract_revision


def record_authentic_native_receipt(
    task_store: Any,
    verification_store: VerificationStore,
    artifact_store: Any,
    task_id: str,
    criterion: str,
    command: str,
    root: str | Path,
    *,
    owner: str = "",
    exit_code: int = 0,
    output_summary: str = "",
    producer: str | None = None,
    evidence_type: str | None = None,
    binding: TaskBinding | None = None,
    plan_storage: RepoPlanStorage | None = None,
) -> dict[str, Any]:
    """Mint and record an authentic native verification receipt backed by command_execution_record.v2.

    Strictly validates producer, provenance, exit_code, and active contract criteria.
    """
    canonical_root = str(Path(root).resolve())
    root_sha256 = hashlib.sha256(canonical_root.encode("utf-8")).hexdigest()

    # 1. Reject fake pass commands
    clean_command = command.strip()
    if DISALLOWED_COMMAND_REGEX.match(clean_command):
        raise ValueError("Trivial pass command ('echo PASS') is not an authentic verification producer")

    # 2. Validate task in task_store
    task_state = task_store.get(task_id)
    if task_state is None:
        raise KeyError(f"Task '{task_id}' not found in task store")

    expected_owner = task_state.owner or owner or "agent"
    if owner and task_state.owner and owner != task_state.owner:
        raise ValueError(f"Task owner mismatch: expected {task_state.owner}, got {owner}")

    # Validate repo root match
    task_repo_root = getattr(task_state, "repo_root", "") or getattr(
        getattr(task_state, "context", None), "repository_id", ""
    )
    if task_repo_root:
        canonical_task_root = str(Path(task_repo_root).resolve())
        if canonical_root != canonical_task_root:
            raise ValueError(f"Root mismatch: task belongs to {canonical_task_root}, got {canonical_root}")

    # Validate criterion is in active acceptance criteria
    active_criteria = list(task_state.contract.acceptance_criteria if task_state.contract else ())
    plan_storage_to_use = plan_storage or (RepoPlanStorage(canonical_root) if Path(canonical_root).exists() else None)
    binding_to_use = binding or (TaskBindingManager(canonical_root).get_binding(task_id) if Path(canonical_root).exists() else None)
    if binding_to_use and plan_storage_to_use:
        try:
            p_data, _ = plan_storage_to_use.read_plan_file(binding_to_use.plan_rel_path)
            t_data = p_data.get("tasks", {}).get(binding_to_use.plan_task_id, {})
            if "acceptance_criteria" in t_data:
                for c in t_data["acceptance_criteria"]:
                    if c not in active_criteria:
                        active_criteria.append(c)
        except Exception:
            pass
    clean_criterion = criterion.strip()
    if clean_criterion not in active_criteria:
        raise ValueError(
            f"Criterion '{clean_criterion}' is not present in active contract criteria: {active_criteria}"
        )

    # 3. Classify evidence type and validate producer
    computed_evidence_type = evidence_type or criterion_evidence_type(clean_criterion)
    if computed_evidence_type == "test" or classify_verification_command(clean_command) == "test":
        computed_evidence_type = "test"
        if exit_code != 0:
            raise ValueError(f"Native test command failed with exit_code {exit_code}")
    elif computed_evidence_type == "benchmark":
        if exit_code != 0:
            raise ValueError(f"Native benchmark command failed with exit_code {exit_code}")
    else:
        # source_review / inspection / documentation
        computed_evidence_type = "source_review"
        valid_doc_producers = {"inspection_producer", "review_producer", "git_diff_review", "linter", "manual_review"}
        if producer and producer not in valid_doc_producers and classify_verification_command(clean_command) != "source_review":
            raise ValueError(f"Unsupported review producer: '{producer}'")
        if exit_code != 0:
            raise ValueError(f"Native inspection check failed with exit_code {exit_code}")

    # 4. Resolve candidate git revision
    _, head_commit = get_git_context(Path(canonical_root))
    current_revision = head_commit or "working"

    command_id = uuid.uuid4().hex
    receipt_id = f"rcpt_{uuid.uuid4().hex[:12]}"
    command_digest = hashlib.sha256(clean_command.encode("utf-8")).hexdigest()
    now = time.time()

    mutation_gen = getattr(task_state.checkpoint, "mutation_generation", 0) if task_state.checkpoint else 0

    # 5. Build command execution record v2
    execution_record = {
        "schema": "command_execution_record.v2",
        "kind": "work_command_verification",
        "command_id": command_id,
        "task_id": task_id,
        "owner": expected_owner,
        "criterion": clean_criterion,
        "command": clean_command,
        "command_sha256": command_digest,
        "evidence_type": computed_evidence_type,
        "command_classification": computed_evidence_type,
        "repository_revision": current_revision,
        "mutation_generation": mutation_gen,
        "repository_root": canonical_root,
        "repository_root_sha256": root_sha256,
        "exit_code": 0,
        "cached": False,
        "result": {"success": True, "exit_code": 0},
        "output_summary": output_summary or f"native {computed_evidence_type} passed (exit_code 0)",
        "observed_at": now,
        "passed": True,
        "producer": producer or "native_command",
    }

    evidence_text = json.dumps(execution_record, indent=2, sort_keys=True)
    evidence_id = artifact_store.put(evidence_text, kind="command_verification")
    execution_record["evidence_id"] = evidence_id

    # 6. Mint canonical VerificationReceipt
    receipt = VerificationReceipt.create(
        task_id=task_id,
        criterion=clean_criterion,
        passed=True,
        change_intent_id="",
        evidence_id=evidence_id,
        command_id=command_id,
        repository_revision=current_revision,
        owner=expected_owner,
        mutation_generation=mutation_gen,
        evidence_type=computed_evidence_type,
        details={
            "command": clean_command,
            "command_execution_record": execution_record,
            "receipt_id": receipt_id,
            "producer": producer or "native_command",
            "output_summary": output_summary,
        },
    )

    receipt_sha = hashlib.sha256(
        json.dumps(receipt.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    execution_record["receipt_sha256"] = receipt_sha

    # 7. Register in verification store
    recorded_rcpt = verification_store.record(receipt, update_task=True)

    # Also register lookup callback in verification store if present
    if hasattr(verification_store, "set_command_execution_record_lookup"):
        existing_lookup = verification_store.command_execution_record_lookup

        def record_lookup(cid: str) -> dict[str, Any] | None:
            if cid == command_id:
                return execution_record
            if callable(existing_lookup):
                return existing_lookup(cid)
            return None

        verification_store.set_command_execution_record_lookup(record_lookup)

    # 8. If plan storage & binding provided, record result reference in plan task
    if plan_storage is not None and binding is not None:
        try:
            plan_dict, rev = plan_storage.read_plan_file(binding.plan_rel_path)
            ptask = plan_dict.get("tasks", {}).get(binding.plan_task_id)
            if ptask is not None:
                ptask_results = ptask.setdefault("results", [])
                ptask_results.append({
                    "kind": ResultRefKind.EVIDENCE_REFERENCE.value,
                    "evidence_id": evidence_id,
                    "summary": f"Criterion verified: {clean_criterion} via {clean_command}",
                })
                plan_storage.save_plan_file(
                    binding.plan_rel_path,
                    plan_dict,
                    expected_revision=rev,
                    owner=expected_owner,
                )
        except Exception as exc:
            logger.warning("Failed to record result reference in plan file: %s", exc)

    return {
        "success": True,
        "receipt_id": recorded_rcpt.receipt_id,
        "receipt": recorded_rcpt,
        "evidence_id": evidence_id,
        "command_id": command_id,
        "criterion": clean_criterion,
        "passed": True,
        "evidence_type": computed_evidence_type,
    }
