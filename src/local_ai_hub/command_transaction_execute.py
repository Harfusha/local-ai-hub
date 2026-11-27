from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from typing import Any
import uuid

from .command_rollback import (
    _capture_rollback_postimages,
    _close_rollback_root,
    _restore_rollback_scope,
    _snapshot_rollback_scope,
)
from .command_transactions import (
    RollbackFileSnapshot,
    RollbackSnapshot,
    create_private_transaction_snapshot_with_manifest,
    validate_transaction_output,
    verify_transaction_source_unchanged,
)
from .process_utils import canonical_root
from .work_fencing import WorkAttemptFence

class CommandTransactionExecuteMixin:
    def _run_private_transaction(
        self,
        command: str,
        source_root: str | Path,
        *,
        task_id: str,
        paths: list[str],
        timeout: int,
        docker_image: str,
        work_attempt_fence: WorkAttemptFence | None = None,
        cancel_event: threading.Event | None = None,
        log_callback: Any | None = None,
        operation: Any | None = None,
        command_key: str = "",
        attempt_key: str = "",
    ) -> dict[str, Any]:
        transaction_id = uuid.uuid4().hex
        if not isinstance(docker_image, str) or not docker_image.strip() or "\x00" in docker_image:
            return {
                "success": False, "transaction_id": transaction_id,
                "transaction_status": "discarded", "failure_kind": "sandbox_unavailable",
                "error": "invalid Docker image for private command transaction",
                "terminal": True, "retryable": False,
            }
        ready, ready_error = self._transaction_docker_ready()
        if not ready:
            return {
                "success": False, "transaction_id": transaction_id,
                "transaction_status": "discarded", "failure_kind": "sandbox_unavailable",
                "error": ready_error, "mutation_sandbox_required": True,
                "terminal": True, "retryable": False,
            }

        source = Path(canonical_root(source_root)).resolve(strict=True)
        if work_attempt_fence is None:
            return {
                "success": False,
                "transaction_id": transaction_id,
                "transaction_status": "discarded",
                "failure_kind": "work_attempt_fence_required",
                "mutation_fence_required": True,
                "outcome_unknown": False,
                "terminal": True,
                "retryable": False,
            }
        try:
            attempt_payload = self._assert_work_attempt_fence(
                work_attempt_fence, task_id=task_id, resource=source
            )
        except (AttributeError, OSError, TypeError, ValueError, RuntimeError) as exc:
            return {
                "success": False,
                "transaction_id": transaction_id,
                "transaction_status": "discarded",
                "failure_kind": "work_attempt_fence_invalid",
                "mutation_fence_required": True,
                "outcome_unknown": False,
                "terminal": True,
                "retryable": False,
                "error": str(exc)[:512],
            }
        if not attempt_key:
            attempt_key = self._attempt_key(command, str(source), timeout=timeout)
        if not command_key:
            try:
                command_key, _transaction_state = self._key(
                    command, str(source), self.classify(command), timeout=timeout,
                )
            except (OSError, ValueError, RuntimeError):
                command_key = ""
        transaction_name = f"command-transaction:{transaction_id}"
        transaction_parent = self._transaction_state_dir
        source_resolved = source.resolve(strict=True)
        transaction_parent_resolved = transaction_parent.resolve(strict=False)
        try:
            transaction_parent_resolved.relative_to(source_resolved)
            overlaps_source = True
        except ValueError:
            try:
                source_resolved.relative_to(transaction_parent_resolved)
                overlaps_source = True
            except ValueError:
                overlaps_source = False
        if overlaps_source:
            fallback = Path(tempfile.gettempdir()) / "local-ai-hub-command-transactions"
            state_key = hashlib.sha256(str(self._transaction_state_dir.resolve()).encode("utf-8")).hexdigest()[:20]
            transaction_parent = fallback / state_key
        transaction_parent.mkdir(parents=True, exist_ok=True)
        try:
            namespace_kwargs = self._transaction_namespace_kwargs(
                source, self.fencing_lease_store
            )
        except Exception as exc:
            return {
                "success": False, "transaction_id": transaction_id,
                "transaction_status": "recovery_required",
                "failure_kind": "mutation_namespace_unavailable",
                "outcome_unknown": True, "terminal": True, "retryable": False,
                "error": str(exc)[:512],
            }
        try:
            recovery = self._recover_transaction_journals(
                source, task_id, transaction_parent,
                f"recovery:{task_id}:{hashlib.sha256(str(source).encode()).hexdigest()[:16]}",
                work_attempt_fence, namespace_kwargs,
            )
        except OSError as exc:
            return {
                "success": False,
                "transaction_id": transaction_id,
                "transaction_status": "recovery_required",
                "failure_kind": "destination_conflict",
                "outcome_unknown": True,
                "retryable": False,
                "terminal": True,
                "error": str(exc)[:512],
            }
        if recovery is not None:
            recovery.setdefault("transaction_id", transaction_id)
            if recovery.get("outcome_unknown"):
                recovery_paths = recovery.get("rollback_paths", paths)
                if not isinstance(recovery_paths, list):
                    recovery_paths = paths
                recovery_error = RuntimeError(str(recovery.get("error") or "transaction recovery outcome is unknown"))
                self._mark_rollback_outcome_unknown(
                    recovery,
                    command_key=command_key,
                    attempt_key=attempt_key,
                    error=recovery_error,
                    rollback_paths=recovery_paths,
                )
                self._capture_rollback_unknown_incident(
                    recovery, command=command, affected_paths=recovery_paths
                )
            return recovery
        lease = self._transaction_leases.claim(
            owner=transaction_name,
            root=str(source),
            paths=paths,
            ttl_seconds=min(7200, max(30, int(timeout) + 60)),
            purpose=f"command transaction task={task_id}",
            **namespace_kwargs,
        )
        if not lease.get("success"):
            return {
                "success": False, "transaction_id": transaction_id,
                "transaction_status": "discarded", "failure_kind": "destination_conflict",
                "error": str(lease.get("error") or "transaction write-set lease denied")[:512],
                "terminal": True, "retryable": False,
            }

        transaction_root = transaction_parent / transaction_id
        source_snapshot: RollbackSnapshot | None = None
        transaction_snapshot: RollbackSnapshot | None = None
        retain_transaction = False
        retain_lease = False
        result: dict[str, Any] = {
            "success": False, "transaction_id": transaction_id,
            "transaction_status": "discarded", "failure_kind": "command_failed",
            "terminal": True, "retryable": False,
        }
        directory_fsync_supported = True
        try:
            source_snapshot, scope_error = _snapshot_rollback_scope(str(source), paths)
            if scope_error or source_snapshot is None:
                result.update({
                    "error": scope_error or "cannot snapshot transaction write set",
                    "failure_kind": "destination_conflict",
                })
                return result
            _capture_rollback_postimages(source_snapshot)
            if any(not entry.safe for entry in source_snapshot.postimages.values()):
                result.update({
                    "error": "transaction source write set could not be verified",
                    "failure_kind": "destination_conflict",
                })
                return result

            transaction_parent.mkdir(parents=True, exist_ok=True)
            transaction_root, baseline = create_private_transaction_snapshot_with_manifest(
                source, transaction_root
            )
            with self._transaction_roots_lock:
                self._active_transaction_roots[transaction_id] = transaction_root.resolve(strict=True)
                self._active_transaction_sources[transaction_id] = source
            if callable(operation):
                try:
                    execution = operation(transaction_root, transaction_id)
                except subprocess.TimeoutExpired as exc:
                    execution = {
                        "success": False,
                        "exit_code": -1,
                        "timed_out": True,
                        "cleanup_unconfirmed": True,
                        "error": f"transaction operation timed out: {exc}",
                        "stdout": "",
                        "stderr": "",
                    }
            else:
                argv = self._transaction_docker_argv(
                    transaction_id, transaction_root, command, docker_image
                )
                try:
                    execution = self._execute(
                        argv, str(transaction_root), timeout, cancel_event,
                        log_callback=log_callback,
                    )
                except subprocess.TimeoutExpired as exc:
                    execution = {
                        "success": False,
                        "exit_code": -1,
                        "timed_out": True,
                        "cleanup_unconfirmed": True,
                        "error": f"transaction command timed out: {exc}",
                        "stdout": "",
                        "stderr": "",
                    }
            result.update(execution)
            result["transaction_id"] = transaction_id

            cleanup_confirmed = not bool(execution.get("cleanup_unconfirmed"))
            if execution.get("timed_out") or execution.get("cancelled") or not cleanup_confirmed:
                cleanup_confirmed = self._transaction_stop_container(transaction_id)
            if not cleanup_confirmed:
                retain_transaction = True
                retain_lease = True
                self._mark_rollback_outcome_unknown(
                    result,
                    command_key=command_key,
                    attempt_key=attempt_key,
                    error=OSError("transaction container termination could not be confirmed"),
                    rollback_paths=paths,
                )
                self._capture_rollback_unknown_incident(
                    result, command=command, affected_paths=paths
                )
                result.update({
                    "success": False,
                    "transaction_status": "recovery_required",
                    "failure_kind": "child_termination_unconfirmed",
                    "outcome_unknown": True,
                    "retryable": False,
                    "terminal": True,
                    "error": "transaction container termination could not be confirmed",
                })
                return result
            if execution.get("cleanup_unconfirmed"):
                execution["cleanup_unconfirmed"] = False
                result["cleanup_unconfirmed"] = False

            if not execution.get("success"):
                try:
                    verify_transaction_source_unchanged(source, baseline, paths)
                except (OSError, ValueError) as exc:
                    retain_transaction = True
                    retain_lease = True
                    self._mark_rollback_outcome_unknown(
                        result,
                        command_key=command_key,
                        attempt_key=attempt_key,
                        error=exc,
                        rollback_paths=paths,
                    )
                    self._capture_rollback_unknown_incident(
                        result, command=command, affected_paths=paths
                    )
                    result.update({
                        "success": False,
                        "transaction_status": "recovery_required",
                        "failure_kind": "destination_conflict",
                        "rolled_back": False,
                        "fail_closed": True,
                        "incident_required": True,
                        "rollback_paths": list(paths),
                        "outcome_unknown": True,
                        "retryable": False,
                        "terminal": True,
                        "error": str(exc)[:512],
                    })
                    return result
                if execution.get("outcome_unknown") or execution.get("cleanup_unconfirmed"):
                    if not result.get("incident_required"):
                        self._mark_rollback_outcome_unknown(
                            result,
                            command_key=command_key,
                            attempt_key=attempt_key,
                            error=OSError(str(result.get("error") or "transaction outcome is unknown")),
                            rollback_paths=paths,
                        )
                        self._capture_rollback_unknown_incident(
                            result, command=command, affected_paths=paths
                        )
                    result.update({
                        "success": False,
                        "transaction_status": "discarded",
                        "failure_kind": "command_outcome_unknown",
                        "rolled_back": bool(result.get("rolled_back", True)),
                        "source_unchanged": True,
                        "outcome_unknown": True,
                        "fail_closed": True,
                        "incident_required": True,
                        "retryable": False,
                        "terminal": True,
                    })
                    return result
                result.update({
                    "success": False,
                    "transaction_status": "discarded",
                    "failure_kind": (
                        "timeout" if execution.get("timed_out") else
                        "cancelled" if execution.get("cancelled") else "command_failed"
                    ),
                    "outcome_unknown": False,
                    "rolled_back": True,
                    "source_unchanged": True,
                    "retryable": False,
                    "terminal": True,
                })
                return result

            try:
                verify_transaction_source_unchanged(source, baseline, paths)
                changes = validate_transaction_output(baseline, transaction_root, paths)
            except (OSError, ValueError) as exc:
                source_conflict = "source path changed while command was running" in str(exc)
                if source_conflict:
                    retain_transaction = True
                    retain_lease = True
                    self._mark_rollback_outcome_unknown(
                        result,
                        command_key=command_key,
                        attempt_key=attempt_key,
                        error=exc,
                        rollback_paths=paths,
                    )
                    self._capture_rollback_unknown_incident(
                        result, command=command, affected_paths=paths
                    )
                result.update({
                    "success": False,
                    "transaction_status": "recovery_required" if source_conflict else "discarded",
                    "failure_kind": (
                        "undeclared_output" if "undeclared transaction output" in str(exc)
                        else "destination_conflict" if source_conflict
                        else "import_failed"
                    ),
                    "outcome_unknown": source_conflict,
                    "rolled_back": not source_conflict,
                    "source_unchanged": not source_conflict,
                    "retryable": False,
                    "terminal": True,
                    "error": str(exc)[:512],
                })
                return result

            changed_paths = list(changes)
            try:
                if changed_paths:
                    transaction_snapshot, output_error = _snapshot_rollback_scope(
                        str(transaction_root), changed_paths
                    )
                    if output_error or transaction_snapshot is None:
                        raise OSError(output_error or "cannot snapshot transaction outputs")
                    expected_preimages = {
                        path: source_snapshot.postimages[path]
                        for path in changed_paths
                    }
                    imported_files = {
                        path: RollbackFileSnapshot(
                            content=transaction_snapshot.files[path].content,
                            mode=transaction_snapshot.files[path].mode,
                            xattrs=transaction_snapshot.files[path].xattrs,
                            windows_dacl=source_snapshot.files[path].windows_dacl,
                            atime_ns=transaction_snapshot.files[path].atime_ns,
                            mtime_ns=transaction_snapshot.files[path].mtime_ns,
                        )
                        for path in changed_paths
                    }
                    import_snapshot = RollbackSnapshot(
                        root=source_snapshot.root,
                        root_identity=source_snapshot.root_identity,
                        files=imported_files,
                        root_guard=source_snapshot.root_guard,
                        postimages=expected_preimages,
                    )
                    journal_path = transaction_parent / f"{transaction_id}.journal.json"
                    journal_payload = {
                        "schema": 1,
                        "transaction_id": transaction_id,
                        "task_id": task_id,
                        "attempt_fence": attempt_payload,
                        "source_root": str(source),
                        "transaction_root": str(transaction_root),
                        "paths": changed_paths,
                        "files": {
                            path: {
                                "before": self._transaction_file_payload(source_snapshot.files[path]),
                                "after": self._transaction_file_payload(imported_files[path]),
                            }
                            for path in changed_paths
                        },
                    }
                    commit_started = False
                    try:
                        with self._fenced_transaction_commit(
                            work_attempt_fence,
                            task_id=task_id,
                            source=source,
                            paths=changed_paths,
                            owner_id=f"command-import:{task_id}:{transaction_id}:{uuid.uuid4().hex}",
                            namespace_kwargs=namespace_kwargs,
                        ) as (fencing_lease, commit_attempt_payload):
                            journal_payload["attempt_fence"] = commit_attempt_payload
                            journal_payload["fencing"] = {
                                "lease_id": fencing_lease.lease_id,
                                "fencing_token": fencing_lease.fencing_token,
                            }
                            directory_fsync_supported = self._persist_transaction_journal(
                                journal_path, journal_payload
                            )
                            commit_started = True
                            try:
                                _restore_rollback_scope(str(source), import_snapshot)
                            except Exception as import_error:
                                restored = self._recover_partial_transaction_import(
                                    source, source_snapshot, transaction_snapshot, changed_paths
                                )
                                if restored:
                                    directory_fsync_supported = (
                                        self._fsync_rollback_directories(source, changed_paths)
                                        and directory_fsync_supported
                                    )
                                    self._remove_transaction_journal(journal_path, journal_payload)
                                    result.update({
                                        "success": False,
                                        "transaction_status": "discarded",
                                        "failure_kind": "import_failed",
                                        "outcome_unknown": False,
                                        "retryable": False,
                                        "terminal": True,
                                        "rolled_back": True,
                                        "error": f"transaction output import failed; source restored: {str(import_error)[:384]}",
                                    })
                                    return result
                                raise OSError(f"transaction output import failed: {str(import_error)[:384]}") from import_error
                            verify_snapshot, verify_error = _snapshot_rollback_scope(
                                str(source), changed_paths
                            )
                            if verify_error or verify_snapshot is None:
                                raise OSError(verify_error or "cannot verify imported transaction outputs")
                            try:
                                for path in changed_paths:
                                    if not self._transaction_file_matches(
                                        verify_snapshot.files[path], transaction_snapshot.files[path]
                                    ):
                                        raise OSError(f"imported transaction output changed: {path}")
                            finally:
                                _close_rollback_root(verify_snapshot.root_guard)
                            directory_fsync_supported = (
                                self._fsync_rollback_directories(source, changed_paths)
                                and directory_fsync_supported
                            )
                            directory_fsync_supported = (
                                self._remove_transaction_journal(journal_path, journal_payload)
                                and directory_fsync_supported
                            )
                            # Observational provenance must not change an already
                            # committed import into a retryable mutation failure.
                            try:
                                from .change_ledger import ChangeLedger

                                receipt_count = ChangeLedger(self._transaction_state_dir.parent).record_broker_postimages(
                                    str(source), task_id=task_id, attempt_id=work_attempt_fence.attempt_id,
                                    transaction_id=transaction_id, files=imported_files,
                                )
                                result["broker_postimage_receipts"] = receipt_count
                            except Exception:
                                result["broker_postimage_receipts_unavailable"] = True
                    except (RuntimeError, ValueError) as exc:
                        if commit_started:
                            raise
                        result.update({
                            "success": False,
                            "transaction_status": "discarded",
                            "failure_kind": "mutation_fence_lost",
                            "outcome_unknown": False,
                            "rolled_back": True,
                            "source_unchanged": True,
                            "retryable": False,
                            "terminal": True,
                            "error": str(exc)[:512],
                        })
                        return result

                result.update({
                    "success": True,
                    "transaction_status": "committed",
                    "failure_kind": "",
                    "outcome_unknown": False,
                    "retryable": False,
                    "terminal": True,
                    "imported_paths": changed_paths if 'changed_paths' in locals() else [],
                    "directory_fsync_supported": directory_fsync_supported,
                })
                if not directory_fsync_supported:
                    result["durability_warning"] = (
                        "Directory fsync is unsupported on Windows; transaction crash durability is not guaranteed."
                    )
            except Exception as exc:
                retain_transaction = True
                retain_lease = True
                self._mark_rollback_outcome_unknown(
                    result,
                    command_key=command_key,
                    attempt_key=attempt_key,
                    error=exc,
                    rollback_paths=paths,
                )
                self._capture_rollback_unknown_incident(
                    result, command=command, affected_paths=paths
                )
                result.update({
                    "success": False,
                    "transaction_status": "recovery_required",
                    "failure_kind": "durability_sync_failed" if "sync" in str(exc).lower() else "import_failed",
                    "outcome_unknown": True,
                    "fail_closed": True,
                    "incident_required": True,
                    "retryable": False,
                    "terminal": True,
                    "error": str(exc)[:512],
                })
            return result
        except Exception as exc:
            result.update({
                "success": False,
                "transaction_status": "discarded",
                "failure_kind": "command_failed",
                "error": str(exc)[:512],
                "retryable": False,
                "terminal": True,
            })
            return result
        finally:
            if transaction_snapshot is not None:
                try:
                    _close_rollback_root(transaction_snapshot.root_guard)
                except OSError:
                    pass
            if source_snapshot is not None:
                try:
                    _close_rollback_root(source_snapshot.root_guard)
                except OSError:
                    pass
            if not retain_transaction:
                shutil.rmtree(transaction_root, ignore_errors=True)
            with self._transaction_roots_lock:
                self._active_transaction_roots.pop(transaction_id, None)
                self._active_transaction_sources.pop(transaction_id, None)
            if not retain_lease:
                self._transaction_leases.release(owner=transaction_name, lease_id=str(lease.get("lease_id") or ""))
