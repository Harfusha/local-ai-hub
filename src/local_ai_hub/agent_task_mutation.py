from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
import time
from typing import Any
import uuid

from .agent_events import AgentEvent
from .agent_task_models import (
    TaskCheckpoint,
    TaskState,
    TaskStatus,
    _canonical_repository_root,
    _preserve_checkpoint_memory_state,
    _task_scope_root,
)


TaskStore = None


class TaskMutationMixin:
    def checkpoint(
        self,
        task_id: str,
        checkpoint: TaskCheckpoint,
        *,
        response_budget_tokens: int | None = None,
        capture_files: bool = False,
        actor: str = "agent",
        idempotency_key: str = "",
        _prepared_updated_at: float | None = None,
        _allow_server_memory_refresh: bool = False,
    ) -> TaskState:
        if response_budget_tokens is not None and (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")

        from .execution_problems import (PROBLEM_DISPOSITION_KEY, PROBLEM_REPORT_KEY, PROBLEM_STATE_KEY,
                                         record_disposition, record_problem, validate_resolution_order)
        from .verified_execution import EXECUTION_KEY

        has_problem_report = PROBLEM_REPORT_KEY in checkpoint.state_data
        has_disposition = PROBLEM_DISPOSITION_KEY in checkpoint.state_data
        if has_disposition and has_problem_report:
            raise ValueError("report and disposition require separate checkpoints")
        disposition = None
        if has_disposition:
            if (EXECUTION_KEY not in current.contract.slo_profile
                    or actor != current.owner or current.is_terminal()):
                raise ValueError("execution problem disposition requires an owned nonterminal verified execution")
            incoming = dict(checkpoint.state_data)
            disposition = incoming.pop(PROBLEM_DISPOSITION_KEY)
            checkpoint = replace(checkpoint, state_data=incoming)
        problem_report = None
        if has_problem_report:
            if (EXECUTION_KEY not in current.contract.slo_profile
                    or actor != current.owner or current.is_terminal()):
                raise ValueError("execution problem reporting requires an owned nonterminal verified execution")
            incoming = dict(checkpoint.state_data)
            problem_report = incoming.pop(PROBLEM_REPORT_KEY)
            validate_resolution_order(
                problem_report, current.contract.slo_profile[EXECUTION_KEY],
                current.checkpoint.state_data.get(PROBLEM_STATE_KEY, {}),
            )
            checkpoint = replace(checkpoint, state_data=incoming)

        checkpoint = _preserve_checkpoint_memory_state(
            current.checkpoint.state_data,
            checkpoint,
            allow_server_memory_refresh=_allow_server_memory_refresh,
        )
        if has_problem_report:
            updated_data = dict(checkpoint.state_data)
            updated_data[PROBLEM_STATE_KEY] = record_problem(
                current.checkpoint.state_data.get(PROBLEM_STATE_KEY, {}),
                problem_report, criteria=current.contract.acceptance_criteria,
                receipt_ids=current.verification_receipts, reporter=actor, now=time.time(),
            )
            checkpoint = replace(checkpoint, state_data=updated_data)
        if has_disposition:
            updated_data = dict(checkpoint.state_data)
            updated_data[PROBLEM_STATE_KEY] = record_disposition(
                current.checkpoint.state_data.get(PROBLEM_STATE_KEY, {}),
                disposition, actor=actor, now=time.time(),
            )
            checkpoint = replace(checkpoint, state_data=updated_data)
        if not _allow_server_memory_refresh:
            self._validate_memory_audit(replace(current, checkpoint=checkpoint))

        return self._persist_checkpoint(
            current, checkpoint, capture_files=capture_files,
            actor=actor, idempotency_key=idempotency_key,
            response_budget_tokens=response_budget_tokens,
            _prepared_updated_at=_prepared_updated_at,
            _allow_server_memory_refresh=_allow_server_memory_refresh,
            _allow_server_execution_update=has_problem_report or has_disposition,
        )

    def _persist_checkpoint(
        self,
        current: TaskState,
        checkpoint: TaskCheckpoint,
        *,
        response_budget_tokens: int | None = None,
        capture_files: bool = False,
        actor: str = "agent",
        idempotency_key: str = "",
        _prepared_updated_at: float | None = None,
        _allow_server_memory_refresh: bool = False,
        _allow_server_execution_update: bool = False,
    ) -> TaskState:
        """Persist a validated agent checkpoint or server-owned bookkeeping."""
        task_id = current.task_id

        now = _prepared_updated_at if _prepared_updated_at is not None else time.time()
        heartbeat = now + self.default_heartbeat_ttl if current.status == TaskStatus.ACTIVE else current.heartbeat_expires_at

        updated = TaskState(
            task_id=current.task_id,
            status=current.status,
            contract=current.contract,
            context=current.context,
            owner=current.owner,
            lease_id=current.lease_id,
            created_at=current.created_at,
            updated_at=now,
            heartbeat_expires_at=heartbeat,
            checkpoint=checkpoint,
            verification_receipts=current.verification_receipts,
        )

        self._preflight_response_budget(updated, response_budget_tokens)

        # File reads are optional checkpoint enrichment. Complete the response
        # preflight first so an undersized MCP budget has no filesystem work.
        capture_requested = capture_files or checkpoint.state_data.get("capture_files")
        if capture_requested:
            snaps = dict(checkpoint.state_data.get("file_snapshots") or {})
            for p_str in checkpoint.affected_paths:
                if p_str not in snaps:
                    try:
                        p = Path(p_str)
                        if p.exists() and p.is_file():
                            snaps[p_str] = p.read_text(encoding="utf-8", errors="ignore")
                        else:
                            snaps[p_str] = None
                    except OSError:
                        pass
            new_sd = dict(checkpoint.state_data)
            new_sd["file_snapshots"] = snaps
            checkpoint = TaskCheckpoint(
                phase=checkpoint.phase,
                next_action=checkpoint.next_action,
                affected_paths=checkpoint.affected_paths,
                evidence_ids=checkpoint.evidence_ids,
                blockers=checkpoint.blockers,
                state_data=new_sd,
            )
            updated = replace(updated, checkpoint=checkpoint)
            # Captured snapshots affect accounting of the full HTTP result.
            # Recheck the final exact envelope before policy handling/events.
            self._preflight_response_budget(updated, response_budget_tokens)

        if self.policy_engine and current.status == TaskStatus.ACTIVE:
            budget = self.policy_engine.get_budget(task_id)
            if budget.is_exhausted():
                return self.fail(
                    task_id,
                    reason=f"TASK_BUDGET_EXCEEDED: used_tokens={budget.used_tokens}/{budget.max_tokens}, used_compute_seconds={budget.used_compute_seconds:.1f}/{budget.max_compute_seconds:.1f}s",
                    actor="watchdog",
                    response_budget_tokens=response_budget_tokens,
                )

        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.checkpointed",
            payload=checkpoint.to_dict(),
            idempotency_key=idempotency_key or f"chk_{task_id}_{time.time_ns()}",
            actor=actor,
        )
        committed = self._commit_update(
            current,
            updated,
            event,
            allow_server_memory_refresh=_allow_server_memory_refresh,
            allow_server_execution_update=_allow_server_execution_update,
        )
        try:
            from .repo_plan.host_adapters import (
                HostOperationStatus,
                record_agent_task_checkpoint_shadow,
            )

            source_event = self.state_store.event_by_idempotency_key(
                event.stream_id, event.idempotency_key
            )
            if source_event is None:
                return committed
            shadow_result = record_agent_task_checkpoint_shadow(
                committed, source_event, self.state_store
            )
            if shadow_result is not None and shadow_result.status is HostOperationStatus.UNCERTAIN:
                import logging

                logging.getLogger(__name__).warning(
                    "task checkpoint shadow observation unavailable: %s",
                    shadow_result.reason,
                )
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "task checkpoint shadow observation unavailable (%s)",
                type(exc).__name__,
            )
        return committed

    def _begin_fenced_work_mutation(
        self, task_id: str, *, root: str, owner: str, fencing_store: Any,
        lease: Any, attempt: Any, paths: list[str],
    ) -> TaskState:
        """Persist a completion barrier before a fenced work mutation begins."""
        from .work_fencing import FencingLease, FencingLeaseStore, WorkAttemptFence, canonical_resource

        if (not isinstance(fencing_store, FencingLeaseStore) or not isinstance(lease, FencingLease)
                or not isinstance(attempt, WorkAttemptFence) or not isinstance(owner, str) or not owner
                or lease.resource != canonical_resource(root) or attempt.resource != lease.resource
                or lease.attempt_id != attempt.attempt_id or lease.attempt_token != attempt.fencing_token):
            raise ValueError("invalid fenced work identity")
        with fencing_store.commit_guard(lease, paths):
            current = self.get(task_id)
            if (current is None or current.status is not TaskStatus.ACTIVE or current.owner != owner
                    or _task_scope_root(current) != _canonical_repository_root(root)):
                raise PermissionError("task owner, state, or root does not match fenced work")
            state_data = dict(current.checkpoint.state_data)
            if "_pending_fenced_work" in state_data:
                expected = {"work_id": attempt.work_id, "attempt_id": attempt.attempt_id,
                            "attempt_token": attempt.fencing_token}
                if state_data["_pending_fenced_work"] != expected:
                    raise ValueError("another fenced work mutation is pending")
            generation = state_data.get("mutation_generation", 0)
            if type(generation) is not int or generation < 0:
                raise ValueError("invalid task mutation generation")
            state_data["mutation_generation"] = generation + 1
            state_data["_pending_fenced_work"] = {"work_id": attempt.work_id, "attempt_id": attempt.attempt_id,
                                                   "attempt_token": attempt.fencing_token}
            updated = replace(current, checkpoint=replace(current.checkpoint, state_data=state_data),
                              updated_at=time.time())
            event = AgentEvent.create(stream_id=f"task:{task_id}", kind="task.fenced_work_started",
                                      payload=state_data["_pending_fenced_work"], actor=owner,
                                      idempotency_key=f"fenced_work_{uuid.uuid4().hex}")
            return self._commit_update(current, updated, event, allow_server_work_update=True)

    def _adopt_fenced_work_mutation(
        self, task_id: str, *, root: str, owner: str, fencing_store: Any,
        lease: Any, attempt: Any, paths: list[str],
    ) -> TaskState:
        """Transfer a pending barrier to a newer fenced attempt of the same work."""
        from .work_fencing import FencingLease, FencingLeaseStore, WorkAttemptFence, canonical_resource

        if (not isinstance(fencing_store, FencingLeaseStore) or not isinstance(lease, FencingLease)
                or not isinstance(attempt, WorkAttemptFence) or not isinstance(owner, str) or not owner
                or lease.resource != canonical_resource(root) or attempt.resource != lease.resource
                or lease.attempt_id != attempt.attempt_id or lease.attempt_token != attempt.fencing_token):
            raise ValueError("invalid fenced work identity")
        with fencing_store.commit_guard(lease, paths):
            current = self.get(task_id)
            if (current is None or current.owner != owner
                    or _task_scope_root(current) != _canonical_repository_root(root)):
                raise PermissionError("task owner or root does not match fenced work")
            state = dict(current.checkpoint.state_data)
            marker = state.get("_pending_fenced_work")
            if (not isinstance(marker, dict) or set(marker) != {"work_id", "attempt_id", "attempt_token"}
                    or marker.get("work_id") != attempt.work_id or not isinstance(marker.get("attempt_id"), str)
                    or type(marker.get("attempt_token")) is not int or marker["attempt_token"] <= 0):
                raise ValueError("pending fenced work identity does not match")
            if marker["attempt_id"] == attempt.attempt_id and marker["attempt_token"] == attempt.fencing_token:
                return current
            if attempt.fencing_token <= marker["attempt_token"]:
                raise ValueError("recovery attempt is not newer")
            generation = state.get("mutation_generation")
            if type(generation) is not int or generation < 0:
                raise ValueError("invalid task mutation generation")
            state["mutation_generation"] = generation + 1
            state["_pending_fenced_work"] = {"work_id": attempt.work_id, "attempt_id": attempt.attempt_id,
                                               "attempt_token": attempt.fencing_token}
            updated = replace(current, checkpoint=replace(current.checkpoint, state_data=state), updated_at=time.time())
            event = AgentEvent.create(stream_id=f"task:{task_id}", kind="task.fenced_work_recovered",
                                      payload=state["_pending_fenced_work"], actor=owner,
                                      idempotency_key=f"fenced_work_{uuid.uuid4().hex}")
            return self._commit_update(current, updated, event, allow_server_work_update=True)

    def _finish_fenced_work_mutation(
        self, task_id: str, *, root: str, owner: str, fencing_store: Any,
        lease: Any, attempt: Any, paths: list[str], rollback: bool, finalize: Any,
    ) -> TaskState:
        """Finalize the journal under its fence before removing the completion barrier."""
        from .work_fencing import FencingLease, FencingLeaseStore, WorkAttemptFence, canonical_resource

        if (not isinstance(fencing_store, FencingLeaseStore) or not isinstance(lease, FencingLease)
                or not isinstance(attempt, WorkAttemptFence) or not isinstance(owner, str) or not owner
                or type(rollback) is not bool or not callable(finalize)
                or lease.resource != canonical_resource(root) or attempt.resource != lease.resource
                or lease.attempt_id != attempt.attempt_id or lease.attempt_token != attempt.fencing_token):
            raise ValueError("invalid fenced work identity")
        with fencing_store.commit_guard(lease, paths):
            current = self.get(task_id)
            if (current is None or current.owner != owner
                    or _task_scope_root(current) != _canonical_repository_root(root)):
                raise PermissionError("task owner or root does not match fenced work")
            state = dict(current.checkpoint.state_data)
            expected = {"work_id": attempt.work_id, "attempt_id": attempt.attempt_id,
                        "attempt_token": attempt.fencing_token}
            if state.get("_pending_fenced_work") != expected:
                raise ValueError("pending fenced work identity does not match")
            generation = state.get("mutation_generation")
            if type(generation) is not int or generation < 0:
                raise ValueError("invalid task mutation generation")
            if rollback:
                state["mutation_generation"] = generation + 1
                updated = replace(current, checkpoint=replace(current.checkpoint, state_data=state), updated_at=time.time())
                event = AgentEvent.create(stream_id=f"task:{task_id}", kind="task.fenced_work_rollback_started",
                                          payload=expected, actor=owner, idempotency_key=f"fenced_work_{uuid.uuid4().hex}")
                current = self._commit_update(current, updated, event, allow_server_work_update=True)
            finalize()
            state = dict(current.checkpoint.state_data)
            del state["_pending_fenced_work"]
            updated = replace(current, checkpoint=replace(current.checkpoint, state_data=state), updated_at=time.time())
            event = AgentEvent.create(stream_id=f"task:{task_id}", kind="task.fenced_work_finalized",
                                      payload={**expected, "rollback": rollback}, actor=owner,
                                      idempotency_key=f"fenced_work_{uuid.uuid4().hex}")
            return self._commit_update(current, updated, event, allow_server_work_update=True)

    def advance_mutation_generation(
        self,
        task_id: str,
        *,
        repository_revision: str = "",
        actor: str = "agent",
    ) -> TaskState:
        """Advance receipt freshness without discarding checkpoint or owned state."""
        current = self.get(task_id)
        if current is None:
            raise KeyError(f"Task {task_id} not found")
        state_data = dict(current.checkpoint.state_data)
        generation = state_data.get("mutation_generation", 0)
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise ValueError("task mutation_generation must be a non-negative integer")
        generation += 1
        state_data["mutation_generation"] = generation
        if repository_revision:
            state_data["repository_revision"] = str(repository_revision).strip()
        checkpoint = replace(current.checkpoint, state_data=state_data)
        return self._persist_checkpoint(
            current,
            checkpoint,
            actor=actor,
            # Separate concurrent advances must not be mistaken for a replay
            # merely because they read the same previous generation.
            idempotency_key=f"mutation_{task_id}_{generation}_{uuid.uuid4().hex}",
        )

    def rollback(
        self,
        task_id: str,
        *,
        actor: str = "agent",
        idempotency_key: str = "",
        reason: str = "rolled back to previous checkpoint",
        response_budget_tokens: int | None = None,
    ) -> TaskState:
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")

        events = self.state_store.events(f"task:{task_id}")
        chk_events = [e for e in events if e.kind == "task.checkpointed"]
        if len(chk_events) >= 2:
            restored_checkpoint = TaskCheckpoint.from_dict(chk_events[-2].payload)
        else:
            restored_checkpoint = TaskCheckpoint()

        # Checkpoint rollback may rewind working context, never issue history.
        from .execution_problems import PROBLEM_DISPOSITION_KEY, PROBLEM_REPORT_KEY, PROBLEM_STATE_KEY

        restored_data = dict(restored_checkpoint.state_data)
        restored_data.pop(PROBLEM_REPORT_KEY, None)
        restored_data.pop(PROBLEM_DISPOSITION_KEY, None)
        restored_data.pop(PROBLEM_STATE_KEY, None)
        if PROBLEM_STATE_KEY in current.checkpoint.state_data:
            restored_data[PROBLEM_STATE_KEY] = current.checkpoint.state_data[PROBLEM_STATE_KEY]
        restored_checkpoint = replace(restored_checkpoint, state_data=restored_data)

        now = time.time()
        new_status = TaskStatus.ACTIVE if current.status in (TaskStatus.VERIFYING, TaskStatus.FAILED, TaskStatus.BLOCKED) else current.status
        updated = TaskState(
            task_id=current.task_id,
            status=new_status,
            contract=current.contract,
            context=current.context,
            owner=current.owner,
            lease_id=current.lease_id,
            created_at=current.created_at,
            updated_at=now,
            heartbeat_expires_at=now + self.default_heartbeat_ttl if new_status == TaskStatus.ACTIVE else current.heartbeat_expires_at,
            checkpoint=restored_checkpoint,
            verification_receipts=current.verification_receipts,
        )
        self._preflight_response_budget(updated, response_budget_tokens)

        snapshots = restored_checkpoint.state_data.get("file_snapshots")
        if isinstance(snapshots, dict):
            for fpath, orig_content in snapshots.items():
                try:
                    p = Path(fpath)
                    if orig_content is None:
                        if p.exists():
                            p.unlink()
                    else:
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_text(str(orig_content), encoding="utf-8")
                except Exception:
                    pass

        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.rolled_back",
            payload={
                "restored_checkpoint": restored_checkpoint.to_dict(),
                "reason": reason,
                "reverted_from_status": current.status.value,
            },
            idempotency_key=idempotency_key or f"rb_{task_id}_{int(now)}",
            actor=actor,
        )
        return self._commit_update(current, updated, event)

    def repair_missing_session(
        self, task_id: str, *, session_id: str, repo_root: str, actor: str, reason: str = "session recovery",
        authorization_actor: str = "", response_budget_tokens: int | None = None,
    ) -> TaskState:
        """Bind a sessionless task once, preserving its identity and audit history."""
        if not isinstance(session_id, str) or not session_id or session_id != session_id.strip() or "\x00" in session_id:
            raise ValueError("session_id must be a nonempty canonical string")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason is required")
        current = self.get(task_id)
        if current is None:
            raise KeyError(f"Task {task_id} not found")
        if not isinstance(actor, str) or not actor or actor != current.owner:
            raise ValueError("task owner mismatch")
        if not repo_root or _canonical_repository_root(repo_root) != _task_scope_root(current):
            raise ValueError("repository root mismatch")
        if current.context.session_id:
            raise ValueError("task already has a session")
        if current.status not in (TaskStatus.PLANNED, TaskStatus.ACTIVE) or current.verification_receipts:
            raise ValueError("task status or verification receipts prevent session repair")
        context = replace(current.context, session_id=session_id)
        state_data = dict(current.checkpoint.state_data)
        previous_audit = state_data.get("memory_audit")
        if isinstance(previous_audit, Mapping):
            history = list(state_data.get("memory_audit_history", ()))
            history.append(dict(previous_audit))
            state_data["memory_audit_history"] = history[-20:]
        state_data["memory_context"] = self._task_memory_context(
            task_id, current.contract, context, root_override=_task_scope_root(current), previous=None
        )
        state_data["memory_audit"] = {
            "used_ids": [],
            "not_used_reason": "Refreshed memory context has not yet been reviewed or used by the resumed task.",
        }
        checkpoint = replace(current.checkpoint, state_data=state_data)
        updated = replace(current, context=context, checkpoint=checkpoint, updated_at=time.time())
        self._preflight_response_budget(updated, response_budget_tokens)
        event = AgentEvent.create(
            stream_id=f"task:{task_id}", kind="task.session_repaired",
            payload={"session_id": session_id, "reason": reason, "authorization_actor": authorization_actor},
            idempotency_key=f"session_repair:{task_id}:{session_id}", actor=actor,
        )
        return self._commit_update(current, updated, event, allow_server_memory_refresh=True)

    def resume(
        self,
        task_id: str,
        *,
        actor: str = "agent",
        idempotency_key: str = "",
        response_budget_tokens: int | None = None,
    ) -> TaskState:
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")
        resume_key = idempotency_key or f"resume_{task_id}_{int(time.time())}"
        if current.status == TaskStatus.ACTIVE and idempotency_key:
            return self._replay_same_status_transition(
                task_id,
                TaskStatus.ACTIVE,
                reason="resumed from checkpoint",
                actor=actor,
                idempotency_key=resume_key,
                response_budget_tokens=response_budget_tokens,
            )
        state_data = dict(current.checkpoint.state_data)
        previous_audit = state_data.pop("memory_audit", None)
        if isinstance(previous_audit, Mapping):
            history = list(state_data.get("memory_audit_history", ()))
            history.append(dict(previous_audit))
            state_data["memory_audit_history"] = history[-20:]
        memory_context = self._task_memory_context(
            task_id,
            current.contract,
            current.context,
            root_override=_task_scope_root(current),
            previous=state_data.get("memory_context") if isinstance(state_data.get("memory_context"), Mapping) else None,
        )
        if memory_context is not None:
            state_data["memory_context"] = memory_context
        elif "memory_context" in state_data:
            # Explicit server refresh: omission would preserve the old snapshot
            # through the existing immutable-checkpoint merge.
            state_data["memory_context"] = None
        state_data["memory_audit"] = {
            "used_ids": [],
            "not_used_reason": "Refreshed memory context has not yet been reviewed or used by the resumed task.",
        }
        resumed_checkpoint = TaskCheckpoint(
            phase=current.checkpoint.phase,
            next_action=current.checkpoint.next_action,
            affected_paths=current.checkpoint.affected_paths,
            evidence_ids=current.checkpoint.evidence_ids,
            blockers=current.checkpoint.blockers,
            state_data=state_data,
        )
        return self.transition(
            task_id,
            TaskStatus.ACTIVE,
            reason="resumed from checkpoint",
            actor=actor,
            idempotency_key=resume_key,
            checkpoint=resumed_checkpoint,
            response_budget_tokens=response_budget_tokens,
            _allow_server_memory_refresh=True,
        )

    def heartbeat(
        self,
        task_id: str,
        ttl_seconds: float | None = None,
        *,
        actor: str = "agent",
        idempotency_key: str = "",
        response_budget_tokens: int | None = None,
    ) -> TaskState:
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")

        now = time.time()
        ttl = float(ttl_seconds) if ttl_seconds is not None and float(ttl_seconds) > 0 else self.default_heartbeat_ttl
        new_expiry = now + ttl

        updated = TaskState(
            task_id=current.task_id,
            status=current.status,
            contract=current.contract,
            context=current.context,
            owner=current.owner,
            lease_id=current.lease_id,
            created_at=current.created_at,
            updated_at=now,
            heartbeat_expires_at=new_expiry,
            checkpoint=current.checkpoint,
            verification_receipts=current.verification_receipts,
        )
        self._preflight_response_budget(updated, response_budget_tokens)

        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.heartbeat",
            payload={"heartbeat_expires_at": new_expiry, "ttl_seconds": ttl},
            idempotency_key=idempotency_key or f"hb_{task_id}_{int(now)}",
            actor=actor,
        )
        return self._commit_update(current, updated, event)

