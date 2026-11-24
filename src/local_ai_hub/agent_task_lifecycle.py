from __future__ import annotations

from collections.abc import Mapping
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any

from .agent_events import AgentEvent
from .agent_task_models import (
    VALID_TRANSITIONS,
    CheckpointResponseBudgetError,
    CompletionGateError,
    ConcurrentTaskUpdateError,
    InvalidTransitionError,
    TaskCheckpoint,
    TaskState,
    TaskStatus,
    _checkpoint_with_scheduled_worktree_cleanup,
    _preserve_checkpoint_memory_state,
    _task_matches_scope,
)
from .json_utils import dumps as json_dumps
from .sqlite_support import connect_sqlite, retry_busy, write_transaction
from .task_memory_wire import task_memory_wire_tokens


TaskStore = None


class TaskLifecycleMixin:
    def _run_ordered_task_write(
        self,
        write: Any,
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        connection_options: dict[str, Any] = {"isolation_level": None}
        if timeout_seconds is not None:
            connection_options["timeout_seconds"] = timeout_seconds
        con = connect_sqlite(self.state_store.db_path, **connection_options)
        try:
            with self.state_store.ordered_event_publication(con) as publish_committed:
                result, events = retry_busy(
                    lambda: write(con), retries=5, base_delay_seconds=0.02
                )
                publish_committed(events)
                return result
        finally:
            con.close()

    def add_verification_receipt(self, task_id: str, criterion: str, receipt_id: str) -> TaskState:
        if not self._db_path_available():
            raise RuntimeError("agent task storage is unavailable")
        self._init_projection_table()
        def _write(con: sqlite3.Connection) -> tuple[TaskState | None, list[AgentEvent]]:
            with write_transaction(con, rollback_label="agent task receipt"):
                state, event = self.add_verification_receipt_in_transaction(
                    con, task_id, criterion, receipt_id
                )
            return state, [event] if event is not None else []
        state = self._run_ordered_task_write(_write)
        if state is None:
            raise KeyError(f"Task {task_id} not found")
        return state

    def add_verification_receipt_in_transaction(
        self,
        con: sqlite3.Connection,
        task_id: str,
        criterion: str,
        receipt_id: str,
    ) -> tuple[TaskState | None, AgentEvent | None]:
        """Update task receipt projection and event using caller's SQLite transaction."""
        if not bool(getattr(con, "in_transaction", False)):
            raise RuntimeError(
                "add_verification_receipt_in_transaction requires a caller-owned transaction"
            )
        row = con.execute(
            "SELECT * FROM agent_tasks_projection WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            return None, None
        current = self._row_to_state(row)
        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.verified",
            payload={"criterion": criterion, "receipt_id": receipt_id},
            idempotency_key=f"ver_{task_id}_{criterion}_{receipt_id}",
            actor="verifier",
        )
        existing = con.execute(
            "SELECT seq FROM agent_events WHERE stream_id = ? AND idempotency_key = ?",
            (event.stream_id, event.idempotency_key),
        ).fetchone()
        current_receipt = current.verification_receipts.get(criterion)
        if existing and current_receipt not in (None, receipt_id):
            appended = self.state_store.append_in_transaction(con, event, strict_idempotency=True)
            if appended.error or appended.event is None:
                raise RuntimeError(appended.error or "task receipt replay returned no persisted event")
            return current, None
        if current_receipt == receipt_id:
            appended = self.state_store.append_in_transaction(con, event, strict_idempotency=True)
            if appended.error or appended.event is None:
                raise RuntimeError(appended.error or "task receipt append returned no persisted event")
            return current, appended.event if not appended.duplicate else None

        updated_receipts = dict(current.verification_receipts)
        updated_receipts[criterion] = receipt_id
        updated_at = time.time()
        cur = con.execute(
            """
            UPDATE agent_tasks_projection
            SET receipts = ?, updated_at = ?
            WHERE task_id = ? AND receipts = ? AND updated_at = ?
            """,
            (
                json_dumps(updated_receipts),
                updated_at,
                current.task_id,
                json_dumps(current.verification_receipts),
                current.updated_at,
            ),
        )
        if cur.rowcount != 1:
            raise ConcurrentTaskUpdateError(
                f"Task {task_id} changed while recording verification receipt"
            )
        appended = self.state_store.append_in_transaction(con, event, strict_idempotency=True)
        if appended.error or appended.event is None:
            raise RuntimeError(appended.error or "task receipt append returned no persisted event")
        updated = TaskState(
            task_id=current.task_id,
            status=current.status,
            contract=current.contract,
            context=current.context,
            owner=current.owner,
            lease_id=current.lease_id,
            created_at=current.created_at,
            updated_at=updated_at,
            heartbeat_expires_at=current.heartbeat_expires_at,
            checkpoint=current.checkpoint,
            verification_receipts=updated_receipts,
        )
        return updated, appended.event if not appended.duplicate else None

    def validate_completion(self, task_id: str) -> TaskState:
        """Validate persisted completion gates without changing task state."""
        task = self.get(task_id)
        if task is None:
            raise KeyError(f"Task {task_id} not found")
        self._verify_completion(task)
        return task

    def _verify_completion(self, task: TaskState, *, current_revision: str = "", _waive_receipts: bool = False) -> None:
        completion_started_at = time.monotonic()
        if "_pending_fenced_work" in task.checkpoint.state_data:
            raise CompletionGateError("Cannot transition to COMPLETED: fenced work mutation is pending")
        memory_audit_validator = getattr(self, "_validate_memory_audit", None)
        if callable(memory_audit_validator):
            memory_audit_validator(task)
        if not task.contract.acceptance_criteria:
            return

        state_data = task.checkpoint.state_data
        try:
            from .verification_rules import (
                _task_created_state_data,
                _task_project_root,
                project_command_environment_sha256,
            )

            initial_state_data = _task_created_state_data(self, task.task_id)
            repo_root = _task_project_root(task, initial_state_data)
        except Exception as exc:
            raise CompletionGateError(
                "Cannot transition to COMPLETED: trusted task project root is unavailable"
            ) from exc
        has_repo_root = isinstance(repo_root, (str, Path)) and bool(str(repo_root).strip())
        repository_revision = str(
            current_revision or state_data.get("repository_revision", "") or ""
        ).strip()
        mutation_generation = state_data.get("mutation_generation", 0)
        if isinstance(mutation_generation, bool) or not isinstance(mutation_generation, int) or mutation_generation < 0:
            raise CompletionGateError(
                "Cannot transition to COMPLETED: task mutation_generation is invalid"
            )

        configured_commands: Mapping[str, Any] = {}
        configured_environment_sha256: Mapping[str, str] = {}
        project_config_digest = ""
        if has_repo_root:
            try:
                from .project_config import resolve_project_context

                project = resolve_project_context(repo_root, Path(self.state_store.db_path).parent)
                settings = project.settings
                verification_rules = settings.verification_rules
                configured_criteria = tuple(settings.commands)
                configured_commands = settings.commands
                configured_environment_sha256 = {
                    name: project_command_environment_sha256(settings, name)
                    for name in settings.commands
                }
                project_config_digest = project.config_digest
                if not isinstance(verification_rules, Mapping) or not isinstance(settings.commands, Mapping):
                    raise ValueError("project verification settings are invalid")
            except Exception as exc:
                raise CompletionGateError(
                    "Cannot transition to COMPLETED: project verification config could not be resolved"
                ) from exc
        else:
            verification_rules = {}
            configured_criteria = ()
        acceptance = set(task.contract.acceptance_criteria)
        active_rules = any(str(key).strip() in acceptance for key in verification_rules)

        verifier = getattr(self, "verification_store", None)
        from .agent_verification import VerificationStore

        if verifier is None:
            try:
                verifier = VerificationStore(self.state_store, task_store=self)
                self.verification_store = verifier
            except Exception as exc:
                raise CompletionGateError(
                    "Cannot transition to COMPLETED: verification evaluator is unavailable"
                ) from exc
        if not isinstance(verifier, VerificationStore):
            raise CompletionGateError(
                "Cannot transition to COMPLETED: verification evaluator is unsupported"
            )

        completion = getattr(verifier, "completion", None)
        if not callable(completion):
            raise CompletionGateError(
                "Cannot transition to COMPLETED: verification evaluator has no completion method"
            )
        try:
            if active_rules and not repository_revision:
                raise CompletionGateError(
                    "Cannot transition to COMPLETED: trusted repository_revision is unavailable"
                )
            result = completion(
                task.task_id,
                current_revision=repository_revision,
                current_mutation_generation=mutation_generation,
                verification_rules=verification_rules,
                configured_criteria=configured_criteria,
                configured_commands=configured_commands,
                project_config_digest=project_config_digest,
                configured_environment_sha256=configured_environment_sha256,
                project_root=repo_root or "",
            )
        except CompletionGateError:
            raise
        except Exception as exc:
            raise CompletionGateError(
                "Cannot transition to COMPLETED: verification completion evaluation failed"
            ) from exc

        complete = result.get("complete", False) if isinstance(result, Mapping) else getattr(result, "complete", False)
        if complete is not True:
            if _waive_receipts and complete is False:
                self._observe_laya_completion(
                    task,
                    repository_root=repo_root,
                    status="waived",
                    reason_code="operator_waiver",
                    started_at=completion_started_at,
                    repository_revision=repository_revision,
                    mutation_generation=mutation_generation,
                )
                return
            self._observe_laya_completion(
                task,
                repository_root=repo_root,
                status="rejected",
                reason_code="completion_gate_rejected",
                started_at=completion_started_at,
                repository_revision=repository_revision,
                mutation_generation=mutation_generation,
            )
            unsatisfied = (
                result.get("unsatisfied_criteria", ())
                if isinstance(result, Mapping)
                else getattr(result, "unsatisfied_criteria", ())
            )
            stale = result.get("stale_criteria", ()) if isinstance(result, Mapping) else getattr(result, "stale_criteria", ())
            details = []
            if unsatisfied:
                details.append(f"unsatisfied={tuple(unsatisfied)}")
            if stale:
                details.append(f"stale={tuple(stale)}")
            suffix = f" ({'; '.join(details)})" if details else ""
            invalid = [
                f"criterion '{criterion}' receipt '{task.verification_receipts.get(criterion, 'missing')}': missing, failed, spoofed, wrong owner, or wrong evidence type"
                for criterion in unsatisfied
            ]
            invalid.extend(
                f"criterion '{criterion}' receipt '{task.verification_receipts.get(criterion, 'missing')}': expired or stale revision/mutation generation"
                for criterion in stale
            )
            raise CompletionGateError(
                "Cannot transition to COMPLETED: " + ("; ".join(invalid) or f"verification evaluator rejected completion{suffix}")
            )
        self._observe_laya_completion(
            task,
            repository_root=repo_root,
            status="passed",
            reason_code="completion_gate_passed",
            started_at=completion_started_at,
            repository_revision=repository_revision,
            mutation_generation=mutation_generation,
        )

    def transition(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        reason: str,
        actor: str,
        idempotency_key: str,
        checkpoint: TaskCheckpoint | None = None,
        response_budget_tokens: int | None = None,
        _allow_server_memory_refresh: bool = False,
        _expected_reap: tuple[str, TaskStatus, float, float] | None = None,
        _prepared_updated_at: float | None = None,
        _expected_completion_content: tuple[Any, Any, str, float, TaskCheckpoint, dict[str, str], str] | None = None,
        _operator_waiver: Mapping[str, Any] | None = None,
    ) -> TaskState:
        if _operator_waiver is not None and (
            target is not TaskStatus.COMPLETED
            or not isinstance(_operator_waiver, Mapping)
            or set(_operator_waiver) != {"consent", "reason"}
            or _operator_waiver.get("consent") is not True
            or not isinstance(_operator_waiver.get("reason"), str)
            or not _operator_waiver["reason"].strip()
        ):
            raise ValueError("operator waiver requires explicit consent and a nonempty reason")
        if response_budget_tokens is not None and (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")
        if _expected_completion_content is not None and (
            current.contract != _expected_completion_content[0]
            or current.context != _expected_completion_content[1]
            or current.lease_id != _expected_completion_content[2]
            or current.created_at != _expected_completion_content[3]
            or current.checkpoint != _expected_completion_content[4]
            or current.verification_receipts != _expected_completion_content[5]
            or current.owner not in (_expected_completion_content[6], actor)
        ):
            raise ConcurrentTaskUpdateError("task completion content changed after response preflight")

        if _expected_reap is not None:
            expected_root, expected_status, expected_expiry, deadline = _expected_reap
            if (
                not _task_matches_scope(current, expected_root, task_id)
                or current.status is not expected_status
                or current.heartbeat_expires_at != expected_expiry
                or expected_expiry <= 0
                or expected_expiry >= deadline
            ):
                raise ConcurrentTaskUpdateError(
                    f"Task {task_id} changed scope or heartbeat before reap transition"
                )

        if checkpoint is not None:
            checkpoint = _preserve_checkpoint_memory_state(
                current.checkpoint.state_data,
                checkpoint,
                allow_server_memory_refresh=_allow_server_memory_refresh,
            )

        if target == current.status:
            if target == TaskStatus.COMPLETED:
                completed_checkpoint = _checkpoint_with_scheduled_worktree_cleanup(
                    checkpoint or current.checkpoint
                )
                checkpoint = (
                    completed_checkpoint
                    if completed_checkpoint != current.checkpoint
                    else None
                )
                candidate = (
                    replace(
                        current,
                        checkpoint=checkpoint,
                        updated_at=(
                            _prepared_updated_at
                            if _prepared_updated_at is not None
                            else current.updated_at
                        ),
                    )
                    if checkpoint is not None
                    else current
                )
                if checkpoint is not None or not idempotency_key:
                    self._preflight_response_budget(candidate, response_budget_tokens)
                # No-op retries must not trust an old terminal projection alone.
                if _operator_waiver is not None:
                    recorded = current.checkpoint.state_data.get("completion_waiver")
                    if not isinstance(recorded, Mapping) or recorded.get("reason") != _operator_waiver["reason"].strip():
                        raise ValueError("operator waiver does not match completed task")
                self._verify_completion(current, _waive_receipts=_operator_waiver is not None)
                if checkpoint is not None:
                    self._verify_completion(replace(current, checkpoint=checkpoint), _waive_receipts=_operator_waiver is not None)
            if checkpoint is not None:
                return self.checkpoint(
                    task_id,
                    checkpoint,
                    response_budget_tokens=response_budget_tokens,
                    actor=actor,
                    idempotency_key=idempotency_key,
                    _prepared_updated_at=_prepared_updated_at,
                    _allow_server_memory_refresh=_allow_server_memory_refresh,
                )
            if not idempotency_key:
                self._preflight_response_budget(current, response_budget_tokens)
                return current
            return self._replay_same_status_transition(
                task_id, target, reason=reason, actor=actor,
                idempotency_key=idempotency_key,
                response_budget_tokens=response_budget_tokens,
                _operator_waiver=_operator_waiver,
            )

        allowed = VALID_TRANSITIONS.get(current.status, set())
        if target not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition task {task_id} from {current.status.value} to {target.value}"
            )

        if target == TaskStatus.COMPLETED and _operator_waiver is None:
            now_check = time.time()
            for criterion in current.contract.acceptance_criteria:
                if criterion not in current.verification_receipts:
                    raise CompletionGateError(
                        f"Cannot transition to COMPLETED: criterion '{criterion}' has no verified receipt"
                    )
                rcpt_id = current.verification_receipts[criterion]
                if not self.state_store.enabled or not self.state_store.db_path.exists():
                    raise CompletionGateError(
                        f"Cannot transition to COMPLETED: receipt '{rcpt_id}' for criterion '{criterion}' cannot be validated because verification storage is unavailable"
                    )
                try:
                    with closing(connect_sqlite(self.state_store.db_path)) as con:
                        row = con.execute(
                            """
                            SELECT task_id, criterion, evidence_id, passed, expires_at
                            FROM agent_verification_receipts WHERE receipt_id = ?
                            """,
                            (rcpt_id,),
                        ).fetchone()
                    if row is None:
                        raise CompletionGateError(
                            f"Cannot transition to COMPLETED: receipt '{rcpt_id}' for criterion '{criterion}' is missing from verification storage"
                        )
                    receipt_task_id, receipt_criterion, evidence_id, passed, expires_at = row
                    if receipt_task_id != task_id:
                        raise CompletionGateError(
                            f"Cannot transition to COMPLETED: receipt '{rcpt_id}' belongs to task '{receipt_task_id}', expected '{task_id}'"
                        )
                    if receipt_criterion != criterion:
                        raise CompletionGateError(
                            f"Cannot transition to COMPLETED: receipt '{rcpt_id}' belongs to criterion '{receipt_criterion}', expected '{criterion}'"
                        )
                    if not str(evidence_id or "").strip():
                        raise CompletionGateError(
                            f"Cannot transition to COMPLETED: receipt '{rcpt_id}' for criterion '{criterion}' has no evidence_id"
                        )
                    if not bool(passed):
                        raise CompletionGateError(
                            f"Cannot transition to COMPLETED: receipt '{rcpt_id}' for criterion '{criterion}' is marked failed"
                        )
                    if expires_at is not None and float(expires_at) < now_check:
                        raise CompletionGateError(
                            f"Cannot transition to COMPLETED: receipt '{rcpt_id}' for criterion '{criterion}' is expired (stale)"
                        )
                except CompletionGateError:
                    raise
                except Exception as exc:
                    raise CompletionGateError(
                        f"Cannot transition to COMPLETED: could not validate receipt '{rcpt_id}' for criterion '{criterion}': {exc}"
                    ) from exc

        now = _prepared_updated_at if _prepared_updated_at is not None else time.time()
        heartbeat = (
            now + self.default_heartbeat_ttl
            if target == TaskStatus.ACTIVE
            else (0.0 if target in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.ABANDONED, TaskStatus.FAILED) else current.heartbeat_expires_at)
        )
        if target == TaskStatus.COMPLETED:
            checkpoint = _checkpoint_with_scheduled_worktree_cleanup(
                checkpoint or current.checkpoint
            )

        updated = TaskState(
            task_id=current.task_id,
            status=target,
            contract=current.contract,
            context=current.context,
            owner=actor,
            lease_id=current.lease_id,
            created_at=current.created_at,
            updated_at=now,
            heartbeat_expires_at=heartbeat,
            checkpoint=checkpoint or current.checkpoint,
            verification_receipts=current.verification_receipts,
        )

        self._preflight_response_budget(updated, response_budget_tokens)
        if target == TaskStatus.COMPLETED:
            self._verify_completion(updated, _waive_receipts=_operator_waiver is not None)

        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.transitioned",
            payload={"from_status": current.status.value, "to_status": target.value, "reason": reason,
                     **({"operator_waiver": dict(_operator_waiver)} if _operator_waiver is not None else {})},
            idempotency_key=idempotency_key,
            actor=actor,
        )
        if _allow_server_memory_refresh:
            return self._commit_update(
                current, updated, event, allow_server_memory_refresh=True
            )
        return self._commit_update(current, updated, event)

    def _replay_same_status_transition(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        reason: str,
        actor: str,
        idempotency_key: str,
        response_budget_tokens: int | None = None,
        _operator_waiver: Mapping[str, Any] | None = None,
    ) -> TaskState:
        """Serialize a no-op retry with writers and validate its original operation."""
        def _read_retry() -> TaskState:
            con = connect_sqlite(
                self.state_store.db_path, isolation_level=None, timeout_seconds=5.0
            )
            try:
                with write_transaction(con, rollback_label="Agent task transition replay"):
                    row = con.execute(
                        "SELECT * FROM agent_tasks_projection WHERE task_id = ?", (task_id,)
                    ).fetchone()
                    if not row:
                        raise KeyError(f"Task {task_id} not found")
                    persisted = self._row_to_state(row)
                    if persisted.status != target:
                        raise ConcurrentTaskUpdateError(
                            f"Task {task_id} changed during transition; reload and retry"
                        )
                    self._preflight_response_budget(persisted, response_budget_tokens)
                    existing = con.execute(
                        """SELECT stream_id, seq, event_id, kind, payload, idempotency_key,
                                  correlation_id, actor, created_at
                           FROM agent_events WHERE stream_id = ? AND idempotency_key = ?""",
                        (f"task:{task_id}", idempotency_key),
                    ).fetchone()
                    if existing:
                        event = AgentEvent.from_row(existing)
                        payload = dict(event.payload)
                        try:
                            source_status = TaskStatus(payload.get("from_status"))
                            valid_transition = target in VALID_TRANSITIONS.get(source_status, set())
                        except (TypeError, ValueError):
                            valid_transition = False
                        if (
                            event.actor != actor
                            or event.kind != "task.transitioned"
                            or set(payload) != ({"from_status", "to_status", "reason", "operator_waiver"} if _operator_waiver is not None else {"from_status", "to_status", "reason"})
                            or (_operator_waiver is not None and payload.get("operator_waiver") != dict(_operator_waiver))
                            or payload.get("to_status") != target.value
                            or payload.get("reason") != reason
                            or not valid_transition
                        ):
                            raise ValueError("idempotency key was already used")
                    if target == TaskStatus.COMPLETED:
                        # Recheck the serialized projection/receipts, not the earlier read.
                        self._verify_completion(persisted, _waive_receipts=_operator_waiver is not None)
                    return persisted
            finally:
                con.close()

        return retry_busy(_read_retry, retries=5, base_delay_seconds=0.02)

    def complete(
        self,
        task_id: str,
        *,
        reason: str = "completed by agent",
        actor: str = "agent",
        idempotency_key: str = "",
        response_budget_tokens: int | None = None,
        checkpoint: TaskCheckpoint | None = None,
        _prepared_completion_updated_at: float | None = None,
        _expected_completion_content: tuple[Any, Any, str, float, TaskCheckpoint, dict[str, str], str] | None = None,
        operator_waiver: Mapping[str, Any] | None = None,
    ) -> TaskState:
        if operator_waiver is not None:
            if (not isinstance(operator_waiver, Mapping)
                or set(operator_waiver) != {"consent", "reason"}
                or operator_waiver.get("consent") is not True
                or not isinstance(operator_waiver.get("reason"), str)
                or not operator_waiver["reason"].strip()):
                raise ValueError("operator waiver requires explicit consent and a nonempty reason")
        if response_budget_tokens is not None and (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")
        if _expected_completion_content is not None and (
            current.contract != _expected_completion_content[0]
            or current.context != _expected_completion_content[1]
            or current.lease_id != _expected_completion_content[2]
            or current.created_at != _expected_completion_content[3]
            or current.checkpoint != _expected_completion_content[4]
            or current.verification_receipts != _expected_completion_content[5]
            or current.owner not in (_expected_completion_content[6], actor)
        ):
            raise ConcurrentTaskUpdateError("task completion content changed after response preflight")
        requested_checkpoint = current.checkpoint
        if checkpoint is not None:
            requested_checkpoint = _preserve_checkpoint_memory_state(current.checkpoint.state_data, checkpoint)
        if operator_waiver is not None:
            waiver_state = dict(requested_checkpoint.state_data)
            waiver_state["completion_waiver"] = {
                "reason": operator_waiver["reason"].strip(),
                "unverified_criteria": list(current.contract.acceptance_criteria),
            }
            requested_checkpoint = replace(requested_checkpoint, state_data=waiver_state)
        completion_checkpoint = _checkpoint_with_scheduled_worktree_cleanup(requested_checkpoint)
        expected_completion_content = (
            _expected_completion_content or self._completion_content_snapshot(current)
        )
        if current.status == TaskStatus.COMPLETED and completion_checkpoint == current.checkpoint:
            return self.transition(
                task_id,
                TaskStatus.COMPLETED,
                reason=reason,
                actor=actor,
                idempotency_key=idempotency_key,
                response_budget_tokens=response_budget_tokens,
                _expected_completion_content=expected_completion_content,
                _operator_waiver=operator_waiver,
            )
        completion_updated_at = _prepared_completion_updated_at
        if completion_updated_at is None:
            completion_updated_at = self.preflight_completion_response_budget(
                task_id, response_budget_tokens, actor=actor, checkpoint=completion_checkpoint,
            )
        if current.status == TaskStatus.COMPLETED:
            checkpoint_for_transition = (
                completion_checkpoint if completion_checkpoint != current.checkpoint else None
            )
            completed = self.transition(
                task_id,
                TaskStatus.COMPLETED,
                reason=reason,
                actor=actor,
                idempotency_key=idempotency_key,
                checkpoint=checkpoint_for_transition,
                response_budget_tokens=response_budget_tokens,
                _prepared_updated_at=completion_updated_at,
                _expected_completion_content=expected_completion_content,
            )
            return completed
        if current.status not in (TaskStatus.PLANNED, TaskStatus.ACTIVE, TaskStatus.VERIFYING,
                                  TaskStatus.WAITING, TaskStatus.BLOCKED):
            raise InvalidTransitionError(f"Cannot complete task {task_id} from {current.status.value}")
        self.preflight_completion_response_budget(
            task_id, response_budget_tokens, actor=actor, checkpoint=completion_checkpoint,
            completion_updated_at=completion_updated_at,
        )
        if response_budget_tokens is not None:
            candidate = replace(
                current, status=TaskStatus.COMPLETED, owner=actor,
                updated_at=completion_updated_at, heartbeat_expires_at=0.0,
                checkpoint=completion_checkpoint,
            )
            self._verify_completion(candidate, _waive_receipts=operator_waiver is not None)
        if current.status == TaskStatus.PLANNED:
            current = self.transition(
                task_id,
                TaskStatus.ACTIVE,
                reason="auto-activated before completion",
                actor=actor,
                idempotency_key=f"{idempotency_key}_act" if idempotency_key else "",
                _prepared_updated_at=completion_updated_at,
                _expected_completion_content=expected_completion_content,
            )
        if current.status in (TaskStatus.WAITING, TaskStatus.BLOCKED):
            current = self.transition(
                task_id,
                TaskStatus.ACTIVE,
                reason="auto-resumed before completion",
                actor=actor,
                idempotency_key=f"{idempotency_key}_res" if idempotency_key else "",
                _prepared_updated_at=completion_updated_at,
                _expected_completion_content=expected_completion_content,
            )
        if current.status == TaskStatus.ACTIVE:
            current = self.transition(
                task_id,
                TaskStatus.VERIFYING,
                reason="auto-verifying before completion",
                actor=actor,
                idempotency_key=f"{idempotency_key}_ver" if idempotency_key else "",
                _prepared_updated_at=completion_updated_at,
                _expected_completion_content=expected_completion_content,
            )
        if current.status != TaskStatus.VERIFYING:
            raise InvalidTransitionError(
                f"Cannot complete task {task_id} from {current.status.value}"
            )
        completed = self.transition(
            task_id,
            TaskStatus.COMPLETED,
            reason=reason,
            actor=actor,
            idempotency_key=idempotency_key,
            checkpoint=completion_checkpoint,
            response_budget_tokens=response_budget_tokens,
            _prepared_updated_at=completion_updated_at,
            _expected_completion_content=expected_completion_content,
            _operator_waiver=operator_waiver,
        )
        return completed

    def claim(self, task_id: str, new_owner: str, *, actor: str) -> TaskState:
        """Adopt or claim task ownership by an authorized agent on this single-owner installation."""
        current = self.get(task_id)
        if not current:
            raise KeyError(f"Task {task_id} not found")
        if current.is_terminal():
            raise ValueError(f"Cannot claim terminal task {task_id}")
        owner_name = str(new_owner or actor or "").strip()
        if not owner_name:
            raise ValueError("new_owner cannot be empty")
        if current.owner == owner_name:
            return current
        sd = dict(current.checkpoint.state_data or {})
        adopted = list(sd.get("adopted_owners", []))
        if current.owner and current.owner not in adopted:
            adopted.append(current.owner)
        sd["adopted_owners"] = adopted
        updated_chk = replace(current.checkpoint, state_data=sd)
        updated = replace(current, owner=owner_name, updated_at=time.time(), checkpoint=updated_chk)
        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.claimed",
            payload={
                "task_id": task_id,
                "previous_owner": current.owner,
                "new_owner": owner_name,
                "adopted_at": time.time(),
                "approval_basis": "authorized_task_claim",
            },
            actor=actor,
        )
        res = self._commit_update(current, updated, event)
        self._record_task_adoption(task_id, current.owner, owner_name)
        return res

    def _record_task_adoption(self, task_id: str, previous_owner: str, new_owner: str) -> None:
        """Record task adoption lineage. Proof artifacts and execution records remain immutable."""
        pass

    def preflight_completion_response_budget(
        self,
        task_id: str,
        response_budget_tokens: int | None,
        *,
        actor: str,
        checkpoint: TaskCheckpoint | None = None,
        completion_updated_at: float | None = None,
    ) -> float | None:
        """Check the final completion projection before any completion writes."""
        if response_budget_tokens is None and completion_updated_at is None:
            return None
        if response_budget_tokens is not None and (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        current = self.get(task_id)
        if current is None:
            raise KeyError(f"Task {task_id} not found")
        prepared_updated_at = completion_updated_at if completion_updated_at is not None else time.time()
        candidate_checkpoint = current.checkpoint
        if checkpoint is not None:
            candidate_checkpoint = _preserve_checkpoint_memory_state(
                current.checkpoint.state_data, checkpoint
            )
        candidate_checkpoint = _checkpoint_with_scheduled_worktree_cleanup(candidate_checkpoint)
        candidate = replace(
            current,
            status=TaskStatus.COMPLETED,
            owner=current.owner if current.status is TaskStatus.COMPLETED else actor,
            updated_at=prepared_updated_at,
            heartbeat_expires_at=(
                current.heartbeat_expires_at
                if current.status is TaskStatus.COMPLETED
                else 0.0
            ),
            checkpoint=candidate_checkpoint,
        )
        self._preflight_response_budget(candidate, response_budget_tokens)
        return prepared_updated_at

    def _mark_cleanup_pending(self, task: TaskState, reason: str, *, actor: str) -> TaskState:
        wt = task.checkpoint.state_data.get("worktree")
        if not isinstance(wt, dict):
            return task
        state_data = dict(task.checkpoint.state_data)
        state_data["worktree"] = {**wt, "cleanup_pending": True, "cleanup_warning": reason[:240]}
        cp = TaskCheckpoint(
            phase=task.checkpoint.phase, next_action=task.checkpoint.next_action,
            affected_paths=task.checkpoint.affected_paths, evidence_ids=task.checkpoint.evidence_ids,
            blockers=task.checkpoint.blockers, state_data=state_data,
        )
        try:
            return self.checkpoint(task.task_id, cp, actor=actor,
                                   idempotency_key=f"cleanup_pending_{task.task_id}_{wt.get('worktree_id', '')}")
        except Exception:
            return self.get(task.task_id) or task

    def cleanup_idle_worktrees(self, *, limit: int = 32, deadline_seconds: float = 8.0) -> dict[str, int]:
        """Reap scheduled or expired terminal worktrees after ownership and cleanliness checks."""
        from .process_utils import process_owner_state
        from .worktrees import is_hub_temporary_worktree, worktree_is_clean_ancestor

        budget = max(0.0, min(float(deadline_seconds), 8.0))
        deadline = time.monotonic() + budget
        counts = {"cleaned": 0, "preserved": 0, "scanned": 0}
        terminal = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.ABANDONED)
        cap = max(1, min(int(limit), 32))
        with closing(connect_sqlite(self.state_store.db_path)) as con:
            statuses = tuple(status.value for status in terminal)
            placeholders = ",".join("?" for _ in statuses)
            cursor_time, cursor_id = self._idle_worktree_cursor
            rows = con.execute(
                f"SELECT task_id, updated_at FROM agent_tasks_projection "
                f"WHERE status IN ({placeholders}) AND checkpoint LIKE '%worktree_path%' "
                "AND (updated_at > ? OR (updated_at = ? AND task_id > ?)) "
                "ORDER BY updated_at, task_id LIMIT ?",
                (*statuses, cursor_time, cursor_time, cursor_id, cap),
            ).fetchall()
            if not rows:
                rows = con.execute(
                    f"SELECT task_id, updated_at FROM agent_tasks_projection "
                    f"WHERE status IN ({placeholders}) AND checkpoint LIKE '%worktree_path%' "
                    "ORDER BY updated_at, task_id LIMIT ?",
                    (*statuses, cap),
                ).fetchall()
            if rows:
                self._idle_worktree_cursor = (float(rows[-1][1]), str(rows[-1][0]))
        for task_id, _updated_at in rows:
            if time.monotonic() >= deadline:
                return counts
            candidate = self.get(str(task_id))
            if candidate is None:
                continue
            counts["scanned"] += 1
            wt = candidate.checkpoint.state_data.get("worktree")
            if not isinstance(wt, dict) or wt.get("cleanup_success"):
                counts["preserved"] += 1
                continue
            try:
                expires_at = float(wt["expires_at"])
                creator = {
                    "pid": int(wt["creator_pid"]), "creation_identity": wt["creator_creation_identity"],
                    "creation_identity_type": wt["creator_creation_identity_type"],
                    "executable": wt["creator_executable"], "state_dir": str(Path(tempfile.gettempdir()).resolve()),
                    "role": "worktree",
                }
                repo = Path(str(wt["repo_root"])).resolve(strict=True)
                path = Path(str(wt["worktree_path"]))
                cleanup_scheduled = wt.get("cleanup_scheduled") is True
                if not cleanup_scheduled and (
                    expires_at >= time.time()
                    or process_owner_state(creator, tempfile.gettempdir(), "worktree") != "stale"
                ):
                    counts["preserved"] += 1
                    continue
                if not is_hub_temporary_worktree(path):
                    counts["preserved"] += 1
                    continue
                if time.monotonic() >= deadline:
                    counts["preserved"] += 1
                    return counts
                remaining = max(0.5, min(3.0, deadline - time.monotonic()))
                safe, _reason = worktree_is_clean_ancestor(
                    repo, path, str(wt["base_commit"]), timeout_seconds=remaining,
                    deadline_monotonic=deadline,
                )
                if not safe:
                    counts["preserved"] += 1
                    continue
                if time.monotonic() >= deadline:
                    counts["preserved"] += 1
                    return counts
                remaining = max(0.5, min(3.0, deadline - time.monotonic()))
                result = self.cleanup_worktree(
                    candidate.task_id, actor=candidate.owner, _timeout_seconds=remaining,
                    _required_base_commit=str(wt["base_commit"]),
                    _deadline_monotonic=deadline,
                )
                if result.get("success"):
                    counts["cleaned"] += 1
                else:
                    self._mark_cleanup_pending(candidate, str(result.get("error") or "idle cleanup failed"), actor=candidate.owner)
                    counts["preserved"] += 1
            except Exception:
                counts["preserved"] += 1
        return counts

    @staticmethod
    def _include_current_request_id(response: dict[str, Any]) -> dict[str, Any]:
        from .trace_context import current as current_trace_context

        request_id = str(current_trace_context().get("request_id") or "")
        if request_id:
            response.setdefault("request_id", request_id)
        return response

    @staticmethod
    def _preflight_response_budget(task: TaskState, response_budget_tokens: int | None) -> None:
        if response_budget_tokens is None:
            return
        if (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        raw_result = TaskStore._include_current_request_id({"success": True, "task": task.to_dict()})
        required_tokens = task_memory_wire_tokens(raw_result, response_budget_tokens)
        if required_tokens > response_budget_tokens:
            raise CheckpointResponseBudgetError(response_budget_tokens, required_tokens)

    def fail(
        self,
        task_id: str,
        *,
        reason: str = "failed by agent",
        actor: str = "agent",
        idempotency_key: str = "",
        response_budget_tokens: int | None = None,
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
        if current.status == TaskStatus.FAILED:
            self._preflight_response_budget(current, response_budget_tokens)
            return current
        if current.status in (
            TaskStatus.PLANNED,
            TaskStatus.ACTIVE,
            TaskStatus.VERIFYING,
            TaskStatus.WAITING,
            TaskStatus.BLOCKED,
            TaskStatus.ABANDONED,
        ):
            now = time.time()
            updated = TaskState(
                task_id=current.task_id,
                status=TaskStatus.FAILED,
                contract=current.contract,
                context=current.context,
                owner=actor,
                lease_id=current.lease_id,
                created_at=current.created_at,
                updated_at=now,
                heartbeat_expires_at=0.0,
                checkpoint=current.checkpoint,
                verification_receipts=current.verification_receipts,
            )
            self._preflight_response_budget(updated, response_budget_tokens)
            event = AgentEvent.create(
                stream_id=f"task:{task_id}",
                kind="task.transitioned",
                payload={"from_status": current.status.value, "to_status": TaskStatus.FAILED.value, "reason": reason},
                idempotency_key=idempotency_key,
                actor=actor,
            )
            return self._commit_update(current, updated, event)
        raise InvalidTransitionError(
            f"Cannot fail task {task_id} from {current.status.value}"
        )

    def revise_contract(
        self,
        task_id: str,
        acceptance_criteria: list[str] | tuple[str, ...],
        *,
        actor: str,
        reason: str,
        expected_revision: int,
    ) -> TaskState:
        """Persist a requirements revision and invalidate prior receipt mappings by CAS."""
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected_revision must be a positive contract revision")
        if type(reason) is not str or not reason.strip() or "\x00" in reason:
            raise ValueError("reason must be a nonempty string")
        if type(acceptance_criteria) not in (list, tuple):
            raise ValueError("acceptance_criteria must be an array of strings")
        current = self.get(task_id)
        if current is None:
            raise KeyError(f"Task {task_id} not found")
        if actor != current.owner:
            raise PermissionError("only the current task owner can revise its contract")
        if current.status in {TaskStatus.COMPLETED, TaskStatus.FAILED,
                              TaskStatus.CANCELLED, TaskStatus.ABANDONED}:
            raise InvalidTransitionError("terminal task contracts cannot be revised")
        state_data = dict(current.checkpoint.state_data)
        revision = state_data.get("contract_revision", 1)
        if type(revision) is not int or revision != expected_revision:
            raise ConcurrentTaskUpdateError("contract revision changed; reload and retry")
        history = state_data.get("contract_history", [])
        if not isinstance(history, list) or len(history) >= 100:
            raise ValueError("contract history is corrupt or reached its 100-entry limit")
        history = [*history, {
            "revision": revision,
            "contract": current.contract.to_dict(),
            "receipt_ids": dict(current.verification_receipts),
            "recorded_at": time.time(),
            "reason": reason.strip(),
        }]
        criteria = tuple(acceptance_criteria)
        contract = replace(current.contract, acceptance_criteria=criteria)
        state_data["contract_history"] = history
        state_data["contract_revision"] = revision + 1
        checkpoint = replace(current.checkpoint, state_data=state_data)
        status = TaskStatus.VERIFYING if current.status == TaskStatus.COMPLETED else current.status
        updated = replace(current, contract=contract, checkpoint=checkpoint,
                          verification_receipts={}, status=status, updated_at=time.time())
        event = AgentEvent.create(
            stream_id=f"task:{task_id}",
            kind="task.contract_revised",
            payload={"task_id": task_id, "contract_revision": revision + 1,
                     "acceptance_criteria": list(contract.acceptance_criteria),
                     "reason": reason.strip()},
            idempotency_key=f"contract_revision_{task_id}_{revision + 1}",
            actor=actor,
        )
        return self._commit_update(current, updated, event)

