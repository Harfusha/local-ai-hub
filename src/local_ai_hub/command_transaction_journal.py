from __future__ import annotations

import base64
from collections.abc import Sequence
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
import uuid

from . import command_broker as services_module
from .command_rollback import (
    _capture_rollback_postimages,
    _close_rollback_root,
    _restore_rollback_scope,
    _snapshot_rollback_scope,
)
from .command_transactions import (
    RollbackFileSnapshot,
    RollbackSnapshot,
)
from .process_utils import hidden_run_kwargs
from .work_fencing import WorkAttemptFence

class CommandTransactionJournalMixin:
    @staticmethod
    def _fsync_rollback_directories(root: Path, paths: Sequence[str]) -> bool:
        """Sync directories containing write-set entries, including created parents."""
        if os.name == "nt":
            return False
        root = root.resolve(strict=True)
        directories = {root}
        for relative in paths:
            parent = (root / relative).parent
            while parent == root or root in parent.parents:
                if parent.exists():
                    directories.add(parent)
                if parent == root:
                    break
                parent = parent.parent
        supported = True
        for directory in sorted(directories, key=lambda item: (len(item.parts), str(item))):
            supported = services_module.CommandBroker._fsync_transaction_directory(directory) and supported
        return supported
    @staticmethod
    def _fsync_transaction_directory(path: Path) -> bool:
        """Sync directory entries where supported; Windows has no portable directory fsync."""
        if os.name == "nt":
            return False
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True
    @staticmethod
    def _persist_transaction_journal(path: Path, payload: dict[str, Any]) -> bool:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                fd = -1
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            return services_module.CommandBroker._fsync_transaction_directory(path.parent)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    def _recover_partial_transaction_import(
        self,
        source: Path,
        source_snapshot: RollbackSnapshot,
        transaction_snapshot: RollbackSnapshot,
        paths: list[str],
    ) -> bool:
        current, error = _snapshot_rollback_scope(str(source), paths)
        if error or current is None:
            return False
        try:
            _capture_rollback_postimages(current)
            restore_paths: list[str] = []
            for path in paths:
                observed = current.files[path]
                before = source_snapshot.files[path]
                after = transaction_snapshot.files[path]
                if self._transaction_file_matches(observed, before):
                    continue
                if not self._transaction_file_matches(observed, after):
                    return False
                source_snapshot.postimages[path] = current.postimages[path]
                restore_paths.append(path)
            if restore_paths:
                rollback = RollbackSnapshot(
                    root=source_snapshot.root,
                    root_identity=source_snapshot.root_identity,
                    files={path: source_snapshot.files[path] for path in restore_paths},
                    root_guard=source_snapshot.root_guard,
                    postimages={path: source_snapshot.postimages[path] for path in restore_paths},
                )
                _restore_rollback_scope(str(source), rollback)
            verified, verify_error = _snapshot_rollback_scope(str(source), paths)
            if verify_error or verified is None:
                return False
            try:
                return all(
                    self._transaction_file_matches(verified.files[path], source_snapshot.files[path])
                    for path in paths
                )
            finally:
                _close_rollback_root(verified.root_guard)
        except (OSError, ValueError):
            return False
        finally:
            _close_rollback_root(current.root_guard)
    def _recover_transaction_journals(
        self,
        source: Path,
        task_id: str,
        transaction_parent: Path,
        lease_owner: str,
        work_attempt_fence: WorkAttemptFence,
        namespace_kwargs: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        self._assert_work_attempt_fence(
            work_attempt_fence, task_id=task_id, resource=source
        )
        journal_paths = sorted(transaction_parent.glob("*.journal.json"))
        if not journal_paths:
            return None
        if namespace_kwargs is None:
            try:
                namespace_kwargs = self._transaction_namespace_kwargs(
                    source, self.fencing_lease_store
                )
            except Exception as exc:
                return {
                    "success": False, "transaction_status": "recovery_required",
                    "failure_kind": "mutation_namespace_unavailable",
                    "outcome_unknown": True, "terminal": True, "retryable": False,
                    "error": str(exc)[:512],
                }
        directory_fsync_supported = True
        for journal_path in journal_paths:
            lease: dict[str, Any] | None = None
            journal: dict[str, Any] = {}
            try:
                if journal_path.stat().st_size > 96 * 1024 * 1024:
                    raise ValueError("transaction journal exceeds size limit")
                journal = json.loads(journal_path.read_text(encoding="utf-8"))
                if not isinstance(journal, dict):
                    raise ValueError("transaction journal is invalid")
                if journal.get("schema") != 1:
                    raise ValueError("transaction journal schema is unsupported")
                if journal.get("source_root") != str(source) or journal.get("task_id") != task_id:
                    continue
                files = journal.get("files")
                paths = journal.get("paths")
                if (
                    not isinstance(files, dict)
                    or not isinstance(paths, list)
                    or len(paths) != len(set(paths))
                    or set(paths) != set(files)
                ):
                    raise ValueError("transaction journal write set is invalid")
                if any(not isinstance(path, str) or not isinstance(entries, dict) for path, entries in files.items()):
                    raise ValueError("transaction journal file entry is invalid")
                if any(
                    not isinstance(path, str)
                    or not path
                    or Path(path).is_absolute()
                    or ".." in Path(path).parts
                    for path in paths
                ):
                    raise ValueError("transaction journal path is invalid")
                before = {path: self._transaction_file_from_payload(files[path].get("before")) for path in paths}
                after = {path: self._transaction_file_from_payload(files[path].get("after")) for path in paths}
                lease = self._transaction_leases.claim(
                    owner=lease_owner,
                    root=str(source),
                    paths=list(paths),
                    ttl_seconds=300,
                    purpose=f"recover command transaction {journal.get('transaction_id', '')}",
                    **namespace_kwargs,
                )
                if not lease.get("success"):
                    return {
                        "success": False,
                        "transaction_id": str(journal.get("transaction_id", "")),
                        "transaction_status": "recovery_required",
                        "failure_kind": "destination_conflict",
                        "outcome_unknown": True,
                        "retryable": False,
                        "terminal": True,
                        "error": str(lease.get("error") or "transaction recovery lease denied")[:512],
                    }
                original_fencing = journal.get("fencing")
                original_attempt = journal.get("attempt_fence")
                if not isinstance(original_fencing, dict) or not isinstance(original_attempt, dict):
                    raise ValueError("transaction journal lacks mutation fence identity")
                original_fence_token = original_attempt.get("fencing_token")
                original_work_id = original_attempt.get("work_id")
                original_resource = original_attempt.get("resource")
                if (
                    type(original_fence_token) is not int
                    or original_fence_token <= 0
                    or original_work_id != task_id
                    or not isinstance(original_resource, str)
                    or os.path.normcase(str(Path(original_resource).resolve(strict=True)))
                    != os.path.normcase(str(source))
                    or work_attempt_fence.fencing_token <= original_fence_token
                ):
                    raise ValueError("transaction recovery attempt is stale or mismatched")
                original_writer_token = original_fencing.get("fencing_token")
                prior_recovery = journal.get("recovery_fencing")
                prior_recovery_token = (
                    prior_recovery.get("fencing_token")
                    if isinstance(prior_recovery, dict) else 0
                )
                if (
                    type(original_writer_token) is not int or original_writer_token <= 0
                    or type(prior_recovery_token) is not int or prior_recovery_token < 0
                ):
                    raise ValueError("transaction journal fencing token is invalid")
                highest_writer_token = max(original_writer_token, prior_recovery_token)
                with self._fenced_transaction_commit(
                    work_attempt_fence,
                    task_id=task_id,
                    source=source,
                    paths=list(paths),
                    owner_id=f"command-recovery:{task_id}:{journal.get('transaction_id', '')}:{uuid.uuid4().hex}",
                    namespace_kwargs=namespace_kwargs,
                ) as (fencing_lease, recovery_attempt_payload):
                    if fencing_lease.fencing_token <= highest_writer_token:
                        raise ValueError("transaction recovery writer fence is stale")
                    journal["recovery_fencing"] = {
                        "lease_id": fencing_lease.lease_id,
                        "fencing_token": fencing_lease.fencing_token,
                    }
                    journal["recovery_attempt_fence"] = recovery_attempt_payload
                    directory_fsync_supported = (
                        self._persist_transaction_journal(journal_path, journal)
                        and directory_fsync_supported
                    )
                    current, scope_error = _snapshot_rollback_scope(str(source), list(paths))
                    if scope_error or current is None:
                        raise OSError(scope_error or "cannot inspect transaction recovery targets")
                    try:
                        _capture_rollback_postimages(current)
                        pending: list[str] = []
                        for path in paths:
                            observed = current.files[path]
                            if self._transaction_file_matches(observed, after[path]):
                                continue
                            if not self._transaction_file_matches(observed, before[path]):
                                raise OSError(f"transaction recovery conflict at {path}")
                            pending.append(path)
                        if pending:
                            import_files = {
                                path: RollbackFileSnapshot(
                                    after[path].content,
                                    after[path].mode,
                                    after[path].xattrs,
                                    current.files[path].windows_dacl,
                                    after[path].atime_ns,
                                    after[path].mtime_ns,
                                )
                                for path in pending
                            }
                            import_snapshot = RollbackSnapshot(
                                current.root,
                                current.root_identity,
                                import_files,
                                current.root_guard,
                                {path: current.postimages[path] for path in pending},
                            )
                            _restore_rollback_scope(str(source), import_snapshot)
                        verified, verify_error = _snapshot_rollback_scope(str(source), list(paths))
                        if verify_error or verified is None:
                            raise OSError(verify_error or "cannot verify recovered transaction outputs")
                        try:
                            if not all(
                                self._transaction_file_matches(verified.files[path], after[path])
                                for path in paths
                            ):
                                raise OSError("transaction recovery postimages did not verify")
                        finally:
                            _close_rollback_root(verified.root_guard)
                    finally:
                        _close_rollback_root(current.root_guard)
                    directory_fsync_supported = (
                        self._fsync_rollback_directories(source, list(paths))
                        and directory_fsync_supported
                    )
                    directory_fsync_supported = (
                        self._remove_transaction_journal(journal_path, journal)
                        and directory_fsync_supported
                    )
                transaction_root_value = journal.get("transaction_root")
                if isinstance(transaction_root_value, str):
                    transaction_root = Path(transaction_root_value).resolve(strict=False)
                    try:
                        transaction_relative = transaction_root.relative_to(
                            transaction_parent.resolve(strict=True)
                        )
                    except ValueError:
                        pass
                    else:
                        if transaction_relative.parts:
                            shutil.rmtree(transaction_root, ignore_errors=True)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                return {
                    "success": False,
                    "transaction_id": str(journal.get("transaction_id", "")),
                    "transaction_status": "recovery_required",
                    "failure_kind": "destination_conflict",
                    "outcome_unknown": True,
                    "retryable": False,
                    "terminal": True,
                    "error": str(exc)[:512],
                }
            finally:
                if lease is not None and lease.get("success"):
                    self._transaction_leases.release(owner=lease_owner, lease_id=str(lease.get("lease_id") or ""))
        if not directory_fsync_supported:
            return {
                "success": True,
                "transaction_status": "recovered",
                "rollback_paths": list(paths),
                "command_not_run": True,
                "directory_fsync_supported": False,
                "durability_warning": "filesystem directory fsync is unsupported; crash durability is not guaranteed",
            }
        return None
    @staticmethod
    def _remove_transaction_journal(path: Path, payload: dict[str, Any]) -> bool:
        path.unlink(missing_ok=True)
        try:
            return services_module.CommandBroker._fsync_transaction_directory(path.parent)
        except OSError:
            try:
                services_module.CommandBroker._persist_transaction_journal(path, payload)
            except OSError:
                pass
            raise
    @staticmethod
    def _transaction_docker_argv(
        transaction_id: str,
        transaction_root: Path,
        command: str,
        image: str,
        *,
        read_only_mount: bool = False,
    ) -> list[str]:
        mount_mode = "ro" if read_only_mount else "rw"
        return [
            "docker", "run", "--rm", "--init", "--name", f"local-ai-{transaction_id}",
            "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--pids-limit=256", "--memory=2g",
            "--cpus=2", "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m",
            "--env", "HOME=/tmp", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "PYTEST_ADDOPTS=-p no:cacheprovider",
            "--env", "GIT_CONFIG_GLOBAL=/workspace/.git/transaction-global-config",
            "--env", "GIT_CONFIG_SYSTEM=/dev/null", "--env", "GIT_CONFIG_NOSYSTEM=1",
            "--volume", f"{transaction_root}:/workspace:{mount_mode}", "--workdir", "/workspace",
            image, "/bin/sh", "-lc", command,
        ]
    @staticmethod
    def _transaction_docker_ready() -> tuple[bool, str]:
        executable = shutil.which("docker")
        if not executable:
            return False, "docker executable not found for private command transaction"
        try:
            probe = subprocess.run(
                [executable, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
                **hidden_run_kwargs(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"Docker engine unavailable for private command transaction: {str(exc)[:240]}"
        if probe.returncode != 0 or not probe.stdout.strip():
            detail = (probe.stderr or probe.stdout or "Docker engine unavailable").strip()[:240]
            return False, f"Docker engine unavailable for private command transaction: {detail}"
        return True, ""
    @staticmethod
    def _transaction_file_from_payload(payload: Any) -> RollbackFileSnapshot:
        if not isinstance(payload, dict):
            raise ValueError("transaction journal file entry is invalid")
        encoded_content = payload.get("content")
        content = base64.b64decode(encoded_content, validate=True) if encoded_content is not None else None
        raw_xattrs = payload.get("xattrs", {})
        if not isinstance(raw_xattrs, dict) or len(raw_xattrs) > 256:
            raise ValueError("transaction journal metadata is invalid")
        xattrs = {
            str(name): base64.b64decode(value, validate=True)
            for name, value in raw_xattrs.items()
        }
        encoded_dacl = payload.get("windows_dacl")
        windows_dacl = base64.b64decode(encoded_dacl, validate=True) if encoded_dacl is not None else None
        mode = payload.get("mode")
        atime_ns = payload.get("atime_ns")
        mtime_ns = payload.get("mtime_ns")
        if mode is not None and not isinstance(mode, int):
            raise ValueError("transaction journal mode is invalid")
        if atime_ns is not None and not isinstance(atime_ns, int):
            raise ValueError("transaction journal atime is invalid")
        if mtime_ns is not None and not isinstance(mtime_ns, int):
            raise ValueError("transaction journal mtime is invalid")
        return RollbackFileSnapshot(content, mode, xattrs, windows_dacl, atime_ns, mtime_ns)
    @staticmethod
    def _transaction_file_matches(left: RollbackFileSnapshot, right: RollbackFileSnapshot) -> bool:
        return (
            left.content == right.content
            and left.mode == right.mode
            and left.xattrs == right.xattrs
            and left.mtime_ns == right.mtime_ns
        )
    @staticmethod
    def _transaction_file_payload(snapshot: RollbackFileSnapshot) -> dict[str, Any]:
        return {
            "content": base64.b64encode(snapshot.content).decode("ascii") if snapshot.content is not None else None,
            "mode": snapshot.mode,
            "xattrs": {
                name: base64.b64encode(value).decode("ascii")
                for name, value in snapshot.xattrs.items()
            },
            "windows_dacl": base64.b64encode(snapshot.windows_dacl).decode("ascii")
            if snapshot.windows_dacl is not None else None,
            "atime_ns": snapshot.atime_ns,
            "mtime_ns": snapshot.mtime_ns,
        }
    def _transaction_root_for_context(self, transaction_id: str) -> Path:
        with self._transaction_roots_lock:
            active = self._active_transaction_roots.get(transaction_id)
        return active if active is not None else (self._transaction_state_dir / transaction_id)
    def _transaction_source_for_context(self, transaction_id: str) -> Path | None:
        with self._transaction_roots_lock:
            return self._active_transaction_sources.get(transaction_id)
    @staticmethod
    def _transaction_stop_container(transaction_id: str) -> bool:
        executable = shutil.which("docker")
        if not executable:
            return False
        name = f"local-ai-{transaction_id}"
        try:
            probe = subprocess.run(
                [executable, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
                **hidden_run_kwargs(),
            )
            if probe.returncode != 0 or not probe.stdout.strip():
                return False
            subprocess.run(
                [executable, "rm", "--force", name],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
                **hidden_run_kwargs(),
            )
            remaining = subprocess.run(
                [executable, "inspect", name],
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
                **hidden_run_kwargs(),
            )
            return remaining.returncode != 0
        except (OSError, subprocess.SubprocessError):
            return False
