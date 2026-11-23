from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import stat
import sys
import threading
import time as _real_time
import uuid
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any


class _TimeProxy:
    def __getattr__(self, name: str) -> Any:
        mod = sys.modules.get("local_ai_hub.work_orchestrator")
        t = getattr(mod, "time", _real_time) if mod is not None else _real_time
        return getattr(t, name)


time = _TimeProxy()

from .json_utils import dumps as json_dumps
from .sqlite_support import begin_write_transaction
from .work_contracts import (
    _bounded_work_scope,
    _FinalizationLookupTimeout,
    _JournalEntry,
    _safe_work_target,
)
from .work_fencing import (
    FencingLease,
    LeaseLostError,
    LeaseUnavailableError,
    WorkAttemptFence,
    canonical_resource,
    normalize_paths,
)

logger = logging.getLogger(__name__)


class WorkRecoveryMixin:
    def _journal_path(self, work_id: str) -> Path:
        text = str(work_id)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", text)[:48] or "work"
        digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
        return self.journal_dir / f"{safe}-{digest}.json"

    def _persist_journal(self, work_id: str, journal: list[_JournalEntry]) -> None:
        path = self._journal_path(work_id)
        if not journal:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.journal_dir, 0o700)
        except OSError:
            pass
        payload = [
            {
                "path": entry.path,
                "existed": entry.existed,
                "data": base64.b64encode(entry.data).decode("ascii"),
                "postimage_existed": entry.postimage_existed,
                "postimage_sha256": entry.postimage_sha256,
                "fencing_resource": entry.fencing_resource,
                "fencing_lease_id": entry.fencing_lease_id,
                "fencing_owner": entry.fencing_owner,
                "fencing_token": entry.fencing_token,
                "attempt_id": entry.attempt_id,
                "attempt_token": entry.attempt_token,
            }
            for entry in journal
        ]
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json_dumps(payload, separators=(",", ":")), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)

    def _load_journal(self, work_id: str) -> list[_JournalEntry] | None:
        path = self._journal_path(work_id)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return []
        except OSError:
            return None
        if (not stat.S_ISREG(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0) & 0x400):
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("invalid work journal root")
            entries: list[_JournalEntry] = []
            for item in raw:
                if not isinstance(item, dict):
                    raise ValueError("invalid work journal entry")
                rel = str(item.get("path", "")).replace("\\", "/")
                if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:/", rel) or any(x in {"", ".", ".."} for x in rel.split("/")):
                    raise ValueError("unsafe work journal path")
                existed = item.get("existed")
                if type(existed) is not bool:
                    raise ValueError("invalid work journal preimage state")
                data = base64.b64decode(str(item.get("data", "")), validate=True)
                if not existed and data:
                    raise ValueError("absent work journal preimage contains data")
                postimage_existed = item.get("postimage_existed")
                postimage_sha256 = str(item.get("postimage_sha256", ""))
                fencing_resource = str(item.get("fencing_resource", ""))
                fencing_lease_id = str(item.get("fencing_lease_id", ""))
                fencing_owner = str(item.get("fencing_owner", ""))
                fencing_token = item.get("fencing_token", 0)
                attempt_id = str(item.get("attempt_id", ""))
                attempt_token = item.get("attempt_token", 0)
                if type(fencing_token) is not int or fencing_token < 0:
                    raise ValueError("invalid work journal fencing token")
                if type(attempt_token) is not int or attempt_token < 0:
                    raise ValueError("invalid work journal attempt token")
                if fencing_token and not all((fencing_resource, fencing_lease_id, fencing_owner)):
                    raise ValueError("incomplete work journal fencing identity")
                if fencing_token and (not attempt_id or attempt_token <= 0):
                    raise ValueError("incomplete work journal attempt identity")
                if postimage_existed is not None and type(postimage_existed) is not bool:
                    raise ValueError("invalid work journal postimage state")
                if (
                    postimage_existed is None and postimage_sha256
                    or postimage_existed is not None
                    and not re.fullmatch(r"[0-9a-f]{64}", postimage_sha256)
                ):
                    raise ValueError("invalid work journal postimage digest")
                entries.append(
                    _JournalEntry(
                        rel,
                        existed,
                        data,
                        postimage_existed,
                        postimage_sha256,
                        fencing_resource,
                        fencing_lease_id,
                        fencing_owner,
                        fencing_token,
                        attempt_id,
                        attempt_token,
                    )
                )
            return entries
        except Exception:
            # A corrupt recovery journal must never be used to write repository files.
            return None

    def _clear_journal(
        self, work_id: str, *, attempt: WorkAttemptFence | None = None
    ) -> None:
        guard = self._state_attempt_guard(work_id, attempt)
        with guard:
            self._persist_journal(work_id, [])

    def _record_recovery_checkpoint(self, work_id: str, journal: list[_JournalEntry]) -> bool:
        manifest = [
            {
                "path": entry.path,
                "existed": entry.existed,
                "content_sha256": hashlib.sha256(entry.data).hexdigest(),
                "postimage_existed": entry.postimage_existed,
                "postimage_sha256": entry.postimage_sha256,
                "fencing_resource": entry.fencing_resource,
                "fencing_lease_id": entry.fencing_lease_id,
                "fencing_owner": entry.fencing_owner,
                "fencing_token": entry.fencing_token,
                "attempt_id": entry.attempt_id,
                "attempt_token": entry.attempt_token,
            }
            for entry in journal
        ]
        checkpoint = {
            "version": 1,
            "work_id": work_id,
            "rollback_complete": True,
            "journal_sha256": hashlib.sha256(
                json_dumps(manifest, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
        with closing(self._connect()) as con:
            transaction = begin_write_transaction(
                con, max_duration_seconds=5.0, rollback_label="work-order recovery checkpoint"
            )
            try:
                row = con.execute(
                    "SELECT result_json,state FROM work_orders WHERE work_id=?",
                    (work_id,),
                ).fetchone()
                if row is None or str(row["state"]) not in {
                    "planning", "executing", "verifying", "integrating"
                }:
                    transaction.rollback()
                    return False
                result = json.loads(str(row["result_json"] or "{}"))
                result["_recovery_checkpoint"] = checkpoint
                updated = con.execute(
                    "UPDATE work_orders SET result_json=?,updated_at=? WHERE work_id=? AND state=?",
                    (
                        json_dumps(result, ensure_ascii=False, separators=(",", ":")),
                        time.time(),
                        work_id,
                        str(row["state"]),
                    ),
                )
                transaction.commit()
                return int(updated.rowcount or 0) == 1
            except BaseException:
                transaction.rollback()
                raise

    def _recovery_task_barrier_unresolved(self, payload: Any) -> bool:
        """Do not replay work while its task barrier needs reconciliation."""
        if not isinstance(payload, dict):
            return True
        task_id = payload.get("task_id", "")
        if task_id == "" or task_id is None:
            return False
        if not isinstance(task_id, str) or not task_id.strip() or task_id != task_id.strip():
            return True
        try:
            store = getattr(self.verification_store, "task_store", None)
            task = store.get(task_id) if store is not None else None
            state = task.checkpoint.state_data if task is not None else None
            return not isinstance(state, dict) or "_pending_fenced_work" in state
        except Exception:
            return True

    @staticmethod
    def _handoff_postimage_manifest(journal: list[_JournalEntry]) -> dict[str, Any]:
        latest = {entry.path: entry for entry in journal}
        if not latest or any(type(entry.postimage_existed) is not bool
                             or re.fullmatch(r"[0-9a-f]{64}", entry.postimage_sha256) is None
                             for entry in latest.values()):
            raise ValueError("handoff journal lacks postimage evidence")
        return {"schema": "bounded_handoff_postimages.v1", "files": [
            {"path": path, "existed": latest[path].postimage_existed, "sha256": latest[path].postimage_sha256}
            for path in sorted(latest)
        ]}

    def _verify_handoff_postimages(self, root: Path, manifest: Any, allowed_paths: list[str]) -> None:
        if (not isinstance(manifest, dict) or set(manifest) != {"schema", "files"}
                or manifest.get("schema") != "bounded_handoff_postimages.v1"
                or not isinstance(manifest.get("files"), list) or not manifest["files"]
                or len(manifest["files"]) > len(allowed_paths)):
            raise ValueError("invalid bounded handoff manifest")
        paths = []
        for item in manifest["files"]:
            if (not isinstance(item, dict) or set(item) != {"path", "existed", "sha256"}
                    or not isinstance(item.get("path"), str) or item["path"] not in allowed_paths
                    or item["path"] in paths or type(item.get("existed")) is not bool
                    or not isinstance(item.get("sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
                raise ValueError("invalid bounded handoff postimage")
            _safe_work_target(root, item["path"])
            paths.append(item["path"])
        actual = self._snapshot(root, paths)
        if len(actual) != len(paths):
            raise RuntimeError("handoff postimage snapshot incomplete")
        for item, image in zip(manifest["files"], actual):
            if (image.path != item["path"] or image.existed is not item["existed"]
                    or hashlib.sha256(image.data).hexdigest() != item["sha256"]):
                raise RuntimeError(f"handoff postimage changed for {item['path']}")

    def _recover_terminal_handoff(self, root: str, work_id: str, payload: dict[str, Any],
                                  result: dict[str, Any], task: Any, attempt: WorkAttemptFence) -> bool:
        """Reconcile only a committed bounded handoff with unchanged postimages."""
        fence = None
        advisory_id = ""
        lease_owner = f"terminal-recovery:{work_id}"
        try:
            if payload.get("mode") != "bounded" or result.get("task_barrier_status") != "pending_finalization":
                return False
            root_path = Path(root)
            allowed, _ = _bounded_work_scope(root_path, payload.get("allowed_paths"), payload.get("approved_commands"))
            manifest = result.get("_task_handoff_manifest")
            if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
                return False
            manifest_paths = [item.get("path") for item in manifest["files"] if isinstance(item, dict)]
            if len(manifest_paths) != len(manifest["files"]) or not manifest_paths:
                return False
            paths = normalize_paths(manifest_paths, root=root_path)
            journal = self._load_journal(work_id)
            if journal is None or (journal and self._handoff_postimage_manifest(journal) != manifest):
                return False
            coordination_id = self._coordination_id(root)
            claim = self.leases.claim_batch(owner=lease_owner, root=root, paths=list(paths), ttl_seconds=900,
                                            purpose=f"terminal-recovery:{work_id}", coordination_id=coordination_id)
            if not claim.get("success"):
                raise LeaseUnavailableError("terminal recovery path lease unavailable")
            advisory_id = str(claim.get("lease_id", ""))
            fence = self.fencing_store.acquire(root, f"terminal-recovery:{work_id}:{uuid.uuid4().hex}",
                                                paths, ttl_seconds=900, attempt=attempt, coordination_id=coordination_id)
            store = self.verification_store.task_store
            args = {"root": root, "owner": task.owner, "fencing_store": self.fencing_store,
                    "lease": fence, "attempt": attempt, "paths": list(paths)}
            store._adopt_fenced_work_mutation(task.task_id, **args)
            def finalize() -> None:
                self._verify_handoff_postimages(root_path, manifest, allowed)
                self._clear_journal(work_id)
            store._finish_fenced_work_mutation(task.task_id, rollback=False, finalize=finalize, **args)
            return True
        except (LeaseUnavailableError, LeaseLostError):
            raise
        except Exception:
            return False
        finally:
            if fence is not None:
                try:
                    self.fencing_store.release(fence)
                except Exception:
                    pass
            if advisory_id:
                try:
                    self.leases.release(owner=lease_owner, lease_id=advisory_id)
                except Exception:
                    pass

    def _recover_finalized_handoff_status(self, root: str, work_id: str, payload: dict[str, Any],
                                           result: dict[str, Any], task: Any, attempt: WorkAttemptFence) -> bool:
        """Confirm a released barrier using its persisted task event and postimages."""
        fence = None
        advisory_id = ""
        lease_owner = f"terminal-status:{work_id}"
        try:
            identity = result.get("_task_handoff_identity")
            if (payload.get("mode") != "bounded" or not isinstance(identity, dict)
                    or set(identity) != {"work_id", "attempt_id", "attempt_token", "mutation_generation"}
                    or identity.get("work_id") != work_id or not isinstance(identity.get("attempt_id"), str)
                    or not identity["attempt_id"] or type(identity.get("attempt_token")) is not int
                    or identity["attempt_token"] <= 0 or type(identity.get("mutation_generation")) is not int
                    or identity["mutation_generation"] < 0):
                return False
            expected = {"work_id": work_id, "attempt_id": identity["attempt_id"],
                        "attempt_token": identity["attempt_token"], "rollback": False}
            try:
                matched = self.verification_store.task_store.state_store.has_exact_event(
                    f"task:{task.task_id}", "task.fenced_work_finalized", expected, actor=task.owner)
            except TimeoutError as exc:
                raise _FinalizationLookupTimeout(str(exc)) from exc
            if not matched:
                return False
            allowed, _ = _bounded_work_scope(Path(root), payload.get("allowed_paths"), payload.get("approved_commands"))
            manifest = result.get("_task_handoff_manifest")
            if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
                return False
            names = [item.get("path") for item in manifest["files"] if isinstance(item, dict)]
            if len(names) != len(manifest["files"]) or not names:
                return False
            paths = normalize_paths(names, root=Path(root))
            coordination = self._coordination_id(root)
            claim = self.leases.claim_batch(owner=lease_owner, root=root, paths=list(paths), ttl_seconds=900,
                                            purpose=f"terminal-status:{work_id}", coordination_id=coordination)
            if not claim.get("success"):
                raise LeaseUnavailableError("terminal status path lease unavailable")
            advisory_id = str(claim.get("lease_id", ""))
            fence = self.fencing_store.acquire(root, f"terminal-status:{work_id}:{uuid.uuid4().hex}", paths,
                                                ttl_seconds=900, attempt=attempt, coordination_id=coordination)
            with self.fencing_store.commit_guard(fence, paths):
                current = self.verification_store.task_store.get(task.task_id)
                state = getattr(getattr(current, "checkpoint", None), "state_data", None)
                from .agent_tasks import _task_matches_scope
                if (current is None or current.owner != task.owner or not _task_matches_scope(current, root, task.task_id)
                        or not isinstance(state, dict)
                        or "_pending_fenced_work" in state
                        or type(state.get("mutation_generation")) is not int
                        or state["mutation_generation"] != identity["mutation_generation"]
                        or self._load_journal(work_id) != []):
                    return False
                self._verify_handoff_postimages(Path(root), manifest, allowed)
            return True
        except (LeaseUnavailableError, LeaseLostError, _FinalizationLookupTimeout):
            raise
        except Exception:
            return False
        finally:
            if fence is not None:
                try:
                    self.fencing_store.release(fence)
                except Exception:
                    pass
            if advisory_id:
                try:
                    self.leases.release(owner=lease_owner, lease_id=advisory_id)
                except Exception:
                    pass

    def _report_terminal_task_barriers(self) -> None:
        """Expose terminal work whose task barrier still needs reconciliation."""
        store = getattr(self.verification_store, "task_store", None)
        if store is None:
            return
        with self._lock:
            with closing(self._connect()) as con:
                rows = con.execute(
                    "SELECT work_id,root,state,payload_json,result_json FROM work_orders "
                    "WHERE state IN ('complete','needs_agent','failed','cancelled') AND work_id>? "
                    "ORDER BY work_id LIMIT 129", (self._terminal_recovery_cursor,)
                ).fetchall()
            if len(rows) > 128:
                self._terminal_recovery_cursor = str(rows[127]["work_id"])
                self._recovery_retry_requested = True
                rows = rows[:128]
            else:
                self._terminal_recovery_cursor = ""
        for row in rows:
            attempt = None
            try:
                payload = json.loads(str(row["payload_json"] or "{}"))
                result = json.loads(str(row["result_json"] or "{}"))
                if not isinstance(payload, dict) or not isinstance(result, dict):
                    continue
                task_id = payload.get("task_id")
                if not isinstance(task_id, str) or not task_id:
                    continue
                task = store.get(task_id)
                from .agent_tasks import _task_matches_scope
                root = str(Path(str(row["root"])).resolve(strict=False))
                state_data = getattr(getattr(task, "checkpoint", None), "state_data", None)
                marker = state_data.get("_pending_fenced_work") if isinstance(state_data, dict) else None
                if task is None or not _task_matches_scope(task, root, task_id):
                    continue
                marker_absent = isinstance(state_data, dict) and "_pending_fenced_work" not in state_data
                if marker_absent:
                    if result.get("task_barrier_status") != "pending_finalization":
                        continue
                elif not isinstance(marker, dict) or marker.get("work_id") != str(row["work_id"]):
                    continue
                if result.get("task_barrier_status") == "reconciliation_required" and row["state"] != "complete":
                    continue
                attempt = self.fencing_store.claim_attempt(root, str(row["work_id"]),
                    f"terminal-recovery:{row['work_id']}:{uuid.uuid4().hex}", ttl_seconds=900,
                    coordination_id=self._coordination_id(root))
                try:
                    reconciled = (self._recover_finalized_handoff_status(root, str(row["work_id"]), payload, result, task, attempt)
                                  if marker_absent else self._recover_terminal_handoff(root, str(row["work_id"]), payload, result, task, attempt))
                except _FinalizationLookupTimeout:
                    result["task_barrier_status"] = "pending_finalization"
                    result["task_barrier_error"] = "finalization_event_lookup_timeout"
                    self._recovery_retry_requested = True
                else:
                    result["task_barrier_status"] = "released" if reconciled else "reconciliation_required"
                    result.pop("task_barrier_error", None)
                result["requires_primary_review"] = True
                target = "needs_agent" if row["state"] == "complete" else row["state"]
                with self.fencing_store.attempt_guard(attempt):
                    with closing(self._connect()) as con:
                        con.execute("UPDATE work_orders SET state=?,result_json=?,updated_at=? "
                                    "WHERE work_id=? AND state=? AND result_json=?",
                                    (target, json_dumps(result, ensure_ascii=False, separators=(",", ":")),
                                     time.time(), row["work_id"], row["state"], row["result_json"]))
            except (LeaseUnavailableError, LeaseLostError):
                self._recovery_retry_requested = True
                continue
            except Exception:
                continue
            finally:
                if attempt is not None:
                    try:
                        self.fencing_store.release_attempt(attempt)
                    except Exception:
                        pass

    def _recover(self) -> None:
        self._recovery_retry_requested = False
        self._report_terminal_task_barriers()
        transient = ("planning", "executing", "verifying", "integrating")
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT work_id,root,state,result_json,payload_json FROM work_orders WHERE state IN (?,?,?,?)", transient
            ).fetchall()
        now = time.time()
        for row in rows:
            work_id = str(row["work_id"])
            lease_owner = f"work-recovery:{work_id}"
            state = str(row["state"])
            try:
                prior_result = json.loads(str(row["result_json"] or "{}"))
            except Exception:
                prior_result = {}
            checkpoint = prior_result.get("_recovery_checkpoint")
            try:
                recovery_payload = json.loads(str(row["payload_json"] or "{}"))
                barrier_unresolved = self._recovery_task_barrier_unresolved(recovery_payload)
            except (TypeError, ValueError):
                recovery_payload = {}
                barrier_unresolved = True
            journal = self._load_journal(work_id)
            recovered = journal is not None
            deferred = False
            state_attempt: WorkAttemptFence | None = None
            if journal:
                fence: FencingLease | None = None
                attempt: WorkAttemptFence | None = None
                advisory_lease_id = ""
                try:
                    root = Path(str(row["root"])).resolve(strict=False)
                    coordination_id = self._coordination_id(root)
                    if any(
                        entry.fencing_token <= 0
                        or entry.fencing_resource != canonical_resource(root)
                        or not entry.fencing_lease_id
                        or not entry.fencing_owner
                        or not entry.attempt_id
                        or entry.attempt_token <= 0
                        for entry in journal
                    ):
                        raise RuntimeError("work journal lacks authoritative writer fencing metadata")
                    paths = normalize_paths([entry.path for entry in journal], root=root)
                    claim = self.leases.claim_batch(
                        owner=lease_owner,
                        root=str(root),
                        paths=list(paths),
                        ttl_seconds=900,
                        purpose=f"work-recovery:{work_id}",
                        coordination_id=coordination_id,
                    )
                    if not claim.get("success"):
                        raise LeaseUnavailableError("recovery path lease unavailable")
                    advisory_lease_id = str(claim.get("lease_id", ""))
                    try:
                        attempt = self.fencing_store.claim_attempt(
                            str(root),
                            work_id,
                            f"recovery:{work_id}:{uuid.uuid4().hex}",
                            ttl_seconds=900,
                            coordination_id=coordination_id,
                        )
                    except LeaseUnavailableError:
                        raise
                    except Exception:
                        deferred = True
                        raise
                    state_attempt = attempt
                    fence = self.fencing_store.acquire(
                        str(root),
                        f"recovery:{work_id}:{uuid.uuid4().hex}",
                        paths,
                        ttl_seconds=900,
                        attempt=attempt,
                        coordination_id=coordination_id,
                    )
                    def restore_journal() -> None:
                        self._rollback(root, journal)
                        if not self._record_recovery_checkpoint(work_id, journal):
                            raise RuntimeError("work recovery state changed before checkpoint")
                        self._clear_journal(work_id)
                    if barrier_unresolved:
                        store = getattr(self.verification_store, "task_store", None)
                        task_id = recovery_payload.get("task_id") if isinstance(recovery_payload, dict) else None
                        task = store.get(task_id) if store is not None and isinstance(task_id, str) else None
                        owner = getattr(task, "owner", None)
                        if not isinstance(owner, str) or not owner:
                            raise RuntimeError("task mutation barrier requires reconciliation")
                        guard_args = {"root": str(root), "owner": owner, "fencing_store": self.fencing_store,
                                      "lease": fence, "attempt": attempt, "paths": list(paths)}
                        store._adopt_fenced_work_mutation(task_id, **guard_args)
                        store._finish_fenced_work_mutation(task_id, rollback=True, finalize=restore_journal, **guard_args)
                        barrier_unresolved = False
                    else:
                        with self.fencing_store.commit_guard(fence, paths):
                            restore_journal()
                except LeaseUnavailableError:
                    # A live owner may still be committing. Preserve the transient
                    # row and journal so the scheduled retry can recover after its TTL.
                    deferred = True
                except Exception:
                    recovered = False
                finally:
                    if fence is not None:
                        try:
                            self.fencing_store.release(fence)
                        except Exception:
                            pass
                    if advisory_lease_id:
                        try:
                            self.leases.release(owner=lease_owner, lease_id=advisory_lease_id)
                        except Exception:
                            pass
            else:
                try:
                    recovery_root = str(Path(str(row["root"])).resolve(strict=False))
                    state_attempt = self.fencing_store.claim_attempt(
                        recovery_root,
                        work_id,
                        f"recovery-empty:{work_id}:{uuid.uuid4().hex}",
                        ttl_seconds=900,
                        coordination_id=self._coordination_id(recovery_root),
                    )
                except LeaseUnavailableError:
                    # A running attempt may not have written its journal yet.
                    deferred = True
                except Exception:
                    recovered = False
                    deferred = True
            if journal == [] and not deferred:
                # A missing journal is safe only when there is no evidence that a
                # prior process had already mutated the workspace.
                checkpoint_valid = (
                    isinstance(checkpoint, dict)
                    and set(checkpoint) == {"version", "work_id", "rollback_complete", "journal_sha256"}
                    and type(checkpoint.get("version")) is int and checkpoint.get("version") == 1
                    and checkpoint.get("work_id") == work_id
                    and checkpoint.get("rollback_complete") is True
                    and isinstance(checkpoint.get("journal_sha256"), str)
                    and re.fullmatch(r"[0-9a-f]{64}", checkpoint["journal_sha256"]) is not None
                )
                if not checkpoint_valid and prior_result.get("changed_files"):
                    recovered = False
                if barrier_unresolved and checkpoint_valid and state_attempt is not None:
                    fence = None
                    advisory_lease_id = ""
                    try:
                        if not isinstance(recovery_payload, dict) or recovery_payload.get("mode") != "bounded":
                            raise ValueError("bounded work contract required")
                        recovery_root = Path(str(row["root"])).resolve(strict=False)
                        allowed_paths, _ = _bounded_work_scope(recovery_root, recovery_payload.get("allowed_paths"),
                                                              recovery_payload.get("approved_commands"))
                        paths = normalize_paths(allowed_paths, root=recovery_root)
                        coordination_id = self._coordination_id(recovery_root)
                        claim = self.leases.claim_batch(owner=lease_owner, root=str(recovery_root), paths=list(paths),
                                                        ttl_seconds=900, purpose=f"work-recovery:{work_id}",
                                                        coordination_id=coordination_id)
                        if not claim.get("success"):
                            raise LeaseUnavailableError("recovery path lease unavailable")
                        advisory_lease_id = str(claim.get("lease_id", ""))
                        fence = self.fencing_store.acquire(str(recovery_root), f"recovery:{work_id}:{uuid.uuid4().hex}",
                                                           paths, ttl_seconds=900, attempt=state_attempt,
                                                           coordination_id=coordination_id)
                        store = getattr(self.verification_store, "task_store", None)
                        task_id = recovery_payload.get("task_id")
                        task = store.get(task_id) if store is not None and isinstance(task_id, str) else None
                        owner = getattr(task, "owner", None)
                        if not isinstance(owner, str) or not owner:
                            raise ValueError("task mutation barrier requires reconciliation")
                        guard_args = {"root": str(recovery_root), "owner": owner, "fencing_store": self.fencing_store,
                                      "lease": fence, "attempt": state_attempt, "paths": list(paths)}
                        store._adopt_fenced_work_mutation(task_id, **guard_args)
                        store._finish_fenced_work_mutation(task_id, rollback=False, finalize=lambda: None, **guard_args)
                        barrier_unresolved = False
                    except LeaseUnavailableError:
                        deferred = True
                    except Exception:
                        recovered = False
                    finally:
                        if fence is not None:
                            try:
                                self.fencing_store.release(fence)
                            except Exception:
                                pass
                        if advisory_lease_id:
                            try:
                                self.leases.release(owner=lease_owner, lease_id=advisory_lease_id)
                            except Exception:
                                pass
            if barrier_unresolved:
                recovered = False
            if deferred:
                if state_attempt is not None:
                    try:
                        self.fencing_store.release_attempt(state_attempt)
                    except Exception:
                        pass
                self._recovery_retry_requested = True
                continue
            try:
                guard = (
                    self.fencing_store.attempt_guard(state_attempt)
                    if state_attempt is not None else nullcontext()
                )
                with guard:
                    with closing(self._connect()) as con:
                        transaction = begin_write_transaction(
                            con, max_duration_seconds=5.0, rollback_label="work-order recovery finalization"
                        )
                        try:
                            if recovered and isinstance(recovery_payload, dict) and recovery_payload.get("mode") == "bounded":
                                current = con.execute(
                                    "SELECT cancel_requested FROM work_orders WHERE work_id=? AND state=?", (work_id, state)
                                ).fetchone()
                                cancelled = current is not None and bool(current["cancel_requested"])
                                result = json_dumps({
                                    "summary": "interrupted bounded work recovered; primary review required",
                                    "error": "interrupted bounded work was not rerun; inspect the workspace and test evidence",
                                    "needs_agent": not cancelled, "requires_primary_review": True, "outcome_unknown": True,
                                }, separators=(",", ":"))
                                con.execute(
                                    "UPDATE work_orders SET state=?,result_json=?,updated_at=? WHERE work_id=? AND state=?",
                                    ("cancelled" if cancelled else "needs_agent", result, now, work_id, state),
                                )
                            elif recovered:
                                con.execute(
                                    "UPDATE work_orders SET state='queued',result_json='{}',updated_at=? WHERE work_id=? AND state=?",
                                    (now, work_id, state),
                                )
                            else:
                                recovery_result = {
                                    "summary": "work order recovery failed",
                                    "error": ("task mutation barrier requires reconciliation; manual inspection required"
                                              if barrier_unresolved else "transaction journal could not be safely restored; manual inspection required"),
                                    "needs_agent": True,
                                }
                                if isinstance(recovery_payload, dict) and recovery_payload.get("mode") == "bounded":
                                    recovery_result.update({"outcome_unknown": True, "requires_primary_review": True,
                                                            "rollback_status": "reconciliation_required"})
                                    if barrier_unresolved:
                                        recovery_result["task_barrier_status"] = "reconciliation_required"
                                result = json_dumps(recovery_result, separators=(",", ":"))
                                con.execute(
                                    "UPDATE work_orders SET state='needs_agent',result_json=?,updated_at=? WHERE work_id=? AND state=?",
                                    (result, now, work_id, state),
                                )
                            transaction.commit()
                        except BaseException:
                            transaction.rollback()
                            raise
            except LeaseLostError:
                self._recovery_retry_requested = True
                continue
            finally:
                if state_attempt is not None:
                    try:
                        self.fencing_store.release_attempt(state_attempt)
                    except Exception:
                        pass

        # Completion is durable before its journal is removed. If the process
        # stops between those writes, keep committed workspace and discard only
        # the now-obsolete rollback snapshot on restart.
        with self._lock:
            with closing(self._connect()) as con:
                completed = con.execute(
                    "SELECT work_id,root,payload_json FROM work_orders WHERE state='complete' AND work_id>? "
                    "ORDER BY work_id LIMIT 129", (self._terminal_cleanup_cursor,)
                ).fetchall()
            if len(completed) > 128:
                self._terminal_cleanup_cursor = str(completed[127]["work_id"])
                self._recovery_retry_requested = True
                completed = completed[:128]
            else:
                self._terminal_cleanup_cursor = ""
        for row in completed:
            work_id = str(row["work_id"])
            if not self._load_journal(work_id):
                # Empty and corrupt journals need no destructive cleanup.
                continue
            cleanup_attempt = None
            try:
                payload = json.loads(str(row["payload_json"] or "{}"))
                if self._recovery_task_barrier_unresolved(payload):
                    continue
                root = str(Path(str(row["root"])).resolve(strict=False))
                cleanup_attempt = self.fencing_store.claim_attempt(
                    root, work_id, f"terminal-cleanup:{work_id}:{uuid.uuid4().hex}", ttl_seconds=900,
                    coordination_id=self._coordination_id(root),
                )
                with self.fencing_store.attempt_guard(cleanup_attempt):
                    with closing(self._connect()) as con:
                        current = con.execute("SELECT state,payload_json FROM work_orders WHERE work_id=?", (work_id,)).fetchone()
                    if current is None or current["state"] != "complete":
                        continue
                    current_payload = json.loads(str(current["payload_json"] or "{}"))
                    if self._recovery_task_barrier_unresolved(current_payload):
                        continue
                    journal = self._load_journal(work_id)
                    if journal:
                        self._clear_journal(work_id)
            except (LeaseUnavailableError, LeaseLostError):
                self._recovery_retry_requested = True
            except (OSError, ValueError, TypeError):
                # Preserve corrupt or unavailable evidence for explicit inspection.
                pass
            except Exception:
                self._recovery_retry_requested = True
            finally:
                if cleanup_attempt is not None:
                    try:
                        self.fencing_store.release_attempt(cleanup_attempt)
                    except Exception:
                        pass
        if self._recovery_retry_requested:
            self._schedule_recovery_retry()

    def _schedule_recovery_retry(self) -> None:
        """Retry deferred crash recovery while a prior writer's lease is live."""
        if self._stop.is_set():
            return
        with self._lock:
            if self._recovery_timer is not None and self._recovery_timer.is_alive():
                return
            timer = threading.Timer(30.0, self._retry_deferred_recovery)
            timer.name = "local-ai-work-recovery-retry"
            timer.daemon = True
            self._recovery_timer = timer
            timer.start()

    def _retry_deferred_recovery(self) -> None:
        with self._lock:
            self._recovery_timer = None
        if self._stop.is_set():
            return
        self._recover()
        if self._has_queued_work():
            self._ensure_workers()
