from __future__ import annotations

from contextlib import closing, nullcontext
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping
import uuid

from .agent_events import AgentEvent
from .agent_task_models import (
    _AGENT_TASK_WRITE_TIMEOUT_SECONDS,
    ConcurrentTaskUpdateError,
    TaskIdempotencyConflictError,
    TaskState,
    TaskStatus,
    _canonical_repository_root,
    _preserve_checkpoint_memory_state,
    _task_scope_root,
)
from .json_utils import dumps as json_dumps
from .sqlite_support import connect_sqlite, retry_busy, write_transaction


TaskStore = None


class TaskPlanSyncMixin:
    def preview_missing_task_projection_recovery(
        self, repo_root: str, *, limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        """Return bounded, root-owned recovery candidates without task payloads."""
        try:
            canonical_root = _canonical_repository_root(repo_root)
        except (OSError, ValueError):
            return {"success": False, "error": "invalid_repository_root"}
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            return {"success": False, "error": "limit_must_be_between_1_and_100"}
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            return {"success": False, "error": "offset_must_be_nonnegative"}
        with closing(connect_sqlite(self.state_store.db_path)) as con:
            rows = con.execute(
                """SELECT DISTINCT e.stream_id
                   FROM agent_events AS e
                   WHERE e.kind = 'task.created'
                     AND e.stream_id LIKE 'task:%'
                     AND json_extract(
                         CASE WHEN json_valid(e.payload) THEN e.payload ELSE '{}' END,
                         '$.checkpoint.state_data._agent_task_scope.repo_root'
                     ) = ?
                     AND NOT EXISTS (
                         SELECT 1 FROM agent_tasks_projection AS p
                         WHERE p.task_id = substr(e.stream_id, 6)
                     )
                   ORDER BY e.stream_id
                   LIMIT ? OFFSET ?""",
                (canonical_root, limit, offset),
            ).fetchall()
        entries: list[dict[str, Any]] = []
        skipped: dict[str, int] = {}
        for (stream_id,) in rows:
            task_id = str(stream_id)[5:]
            result = self.preview_task_projection_restore(task_id, canonical_root)
            if result.get("reason") == "repository_scope_mismatch":
                continue
            if result.get("reason") in {"invalid_event_history", "event_history_unavailable"}:
                skipped["unverified_scope"] = skipped.get("unverified_scope", 0) + 1
                continue
            if result.get("eligible") is True:
                entries.append({"task_id": task_id, "event_digest": result["event_digest"]})
            else:
                reason = str(result.get("reason", "not_eligible"))
                skipped[reason] = skipped.get(reason, 0) + 1
        return {
            "success": True,
            "entries": entries,
            "eligible_count": len(entries),
            "skipped": skipped,
            "scanned": len(rows),
            "offset": offset,
            "next_offset": offset + len(rows),
            "has_more": len(rows) == limit,
        }

    def restore_task_projections(self, repo_root: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Restore a bounded reviewed batch; each stream commits independently."""
        if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
            return {"success": False, "error": "entries_must_contain_1_to_100_items"}
        task_ids: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"task_id", "event_digest"}:
                return {"success": False, "error": "invalid_recovery_entry"}
            task_id = entry["task_id"]
            digest = entry["event_digest"]
            if (
                not isinstance(task_id, str) or not task_id.strip() or "\x00" in task_id
                or task_id in task_ids or not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                return {"success": False, "error": "invalid_or_duplicate_task_id"}
            task_ids.add(task_id)
        results = []
        for entry in entries:
            try:
                result = self.restore_task_projection(entry["task_id"], repo_root, entry["event_digest"])
            except (OSError, RuntimeError, ValueError, sqlite3.Error):
                result = {"success": False, "restored": False, "reason": "storage_write_failed", "task_id": str(entry["task_id"])}
            results.append(result)
        restored = [item["task_id"] for item in results if item.get("restored") is True]
        skipped: dict[str, int] = {}
        for item in results:
            if item.get("restored") is not True:
                reason = str(item.get("reason", "restore_failed"))
                skipped[reason] = skipped.get(reason, 0) + 1
        return {"success": not any(item.get("success") is False for item in results), "restored": restored, "restored_count": len(restored), "skipped": skipped}

    def preview_task_projection_restore(self, task_id: str, repo_root: str) -> dict[str, Any]:
        """Preview restore only when a task's complete history is its creation event."""
        task_id = str(task_id or "").strip()
        try:
            canonical_root = _canonical_repository_root(repo_root)
        except (OSError, ValueError):
            return {"success": False, "eligible": False, "reason": "invalid_repository_root"}
        if not task_id or "\x00" in task_id:
            return {"success": False, "eligible": False, "reason": "invalid_task_id"}
        with closing(connect_sqlite(self.state_store.db_path)) as con:
            row = con.execute(
                "SELECT * FROM agent_tasks_projection WHERE task_id = ?", (task_id,)
            ).fetchone()
        existing = self._row_to_state(row) if row else None
        if existing is not None:
            if _task_scope_root(existing) == canonical_root:
                return {"success": True, "eligible": False, "reason": "projection_exists", "task_id": task_id}
            return {"success": False, "eligible": False, "reason": "task_not_found"}
        try:
            page = self.state_store.event_page(f"task:{task_id}", after_seq=0, limit=2)
            if page.get("success") is not True:
                return {"success": False, "eligible": False, "reason": "event_history_unavailable", "task_id": task_id}
            events = page.get("events", [])
            if (
                page.get("has_more") is True
                or page.get("gap_ranges")
                or page.get("first_retained_seq") != 1
                or page.get("last_seq") != 1
                or len(events) != 1
            ):
                return {"success": True, "eligible": False, "reason": "history_not_creation_only", "task_id": task_id}
            event = AgentEvent.from_dict(events[0])
            if event.seq != 1 or event.stream_id != f"task:{task_id}" or event.kind != "task.created":
                return {"success": True, "eligible": False, "reason": "invalid_creation_event", "task_id": task_id}
            state = TaskState.from_dict(event.payload)
            if (
                state.task_id != task_id
                or state.status is not TaskStatus.PLANNED
                or state.lease_id
                or state.verification_receipts
                or state.heartbeat_expires_at != 0
                or state.checkpoint.state_data.get("worktree") is not None
            ):
                return {"success": True, "eligible": False, "reason": "invalid_initial_state", "task_id": task_id}
            if _task_scope_root(state) != canonical_root:
                return {"success": True, "eligible": False, "reason": "repository_scope_mismatch", "task_id": task_id}
            canonical_event = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            digest = hashlib.sha256(canonical_event.encode("utf-8")).hexdigest()
            return {"success": True, "eligible": True, "reason": "complete_creation_only_history", "task_id": task_id, "event_digest": digest}
        except (KeyError, TypeError, ValueError, RuntimeError, OSError, sqlite3.Error):
            return {"success": True, "eligible": False, "reason": "invalid_event_history", "task_id": task_id}

    def restore_task_projection(self, task_id: str, repo_root: str, event_digest: str) -> dict[str, Any]:
        """Restore one creation-only task through the task store's ordered write path."""
        preview = self.preview_task_projection_restore(task_id, repo_root)
        if preview.get("reason") == "projection_exists":
            return {"success": True, "restored": False, "reason": "projection_exists", "task_id": task_id}
        if preview.get("eligible") is not True:
            return {"success": False, "restored": False, "reason": preview.get("reason", "not_eligible"), "task_id": task_id}
        if not isinstance(event_digest, str) or event_digest != preview.get("event_digest"):
            return {"success": False, "restored": False, "reason": "preview_changed", "task_id": task_id}
        self._init_projection_table()
        event_page = self.state_store.event_page(f"task:{task_id}", after_seq=0, limit=2)
        event = AgentEvent.from_dict(event_page["events"][0])
        state = TaskState.from_dict(event.payload)
        context = json_dumps({
            "repository_id": state.context.repository_id,
            "clone_id": state.context.clone_id,
            "worktree_id": state.context.worktree_id,
            "branch": state.context.branch,
            "task_id": state.context.task_id,
            "session_id": state.context.session_id,
        })

        def _write(con: sqlite3.Connection) -> tuple[dict[str, Any], list[AgentEvent]]:
            with write_transaction(con, rollback_label="Agent task projection recovery"):
                if con.execute("SELECT 1 FROM agent_tasks_projection WHERE task_id = ?", (task_id,)).fetchone():
                    return {"success": True, "restored": False, "reason": "projection_exists", "task_id": task_id}, []
                rows = con.execute(
                    """SELECT stream_id, seq, event_id, kind, payload, idempotency_key,
                              correlation_id, actor, created_at
                       FROM agent_events WHERE stream_id = ? ORDER BY seq LIMIT 2""",
                    (f"task:{task_id}",),
                ).fetchall()
                if len(rows) != 1:
                    return {"success": False, "restored": False, "reason": "preview_changed", "task_id": task_id}, []
                current_event = AgentEvent.from_row(rows[0])
                current_digest = hashlib.sha256(json.dumps(
                    current_event.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8")).hexdigest()
                if current_digest != event_digest or current_event.kind != "task.created" or current_event.seq != 1:
                    return {"success": False, "restored": False, "reason": "preview_changed", "task_id": task_id}, []
                con.execute(
                    """INSERT INTO agent_tasks_projection (
                        task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                        heartbeat_expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (state.task_id, state.status.value, state.owner, state.lease_id,
                     json_dumps(state.contract.to_dict()), context,
                     json_dumps(state.checkpoint.to_dict()), json_dumps(state.verification_receipts),
                     state.heartbeat_expires_at, state.created_at, state.updated_at),
                )
                self._refresh_task_search_index(con, task_id)
                return {"success": True, "restored": True, "reason": "restored", "task_id": task_id}, []

        try:
            return self._run_ordered_task_write(_write)
        except (OSError, RuntimeError, ValueError, sqlite3.Error):
            return {"success": False, "restored": False, "reason": "storage_write_failed", "task_id": task_id}

    def _save_projection(self, state: TaskState) -> None:
        if not self._db_path_available():
            return
        self._init_projection_table()

        def _do_save() -> None:
            con = connect_sqlite(self.state_store.db_path, isolation_level=None)
            try:
                with write_transaction(con, rollback_label="Agent task projection"):
                    con.execute(
                        """
                        INSERT INTO agent_tasks_projection (
                            task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                            heartbeat_expires_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(task_id) DO UPDATE SET
                            status = excluded.status,
                            owner = excluded.owner,
                            lease_id = excluded.lease_id,
                            contract = excluded.contract,
                            context = excluded.context,
                            checkpoint = excluded.checkpoint,
                            receipts = excluded.receipts,
                            heartbeat_expires_at = excluded.heartbeat_expires_at,
                            updated_at = excluded.updated_at
                        """,
                        (
                            state.task_id,
                            state.status.value,
                            state.owner,
                            state.lease_id,
                            json_dumps(state.contract.to_dict()),
                            json_dumps({
                                "repository_id": state.context.repository_id,
                                "clone_id": state.context.clone_id,
                                "worktree_id": state.context.worktree_id,
                                "branch": state.context.branch,
                                "task_id": state.context.task_id,
                                "session_id": state.context.session_id,
                            }),
                            json_dumps(state.checkpoint.to_dict()),
                            json_dumps(state.verification_receipts),
                            state.heartbeat_expires_at,
                            state.created_at,
                            state.updated_at,
                        ),
                    )
                    self._refresh_task_search_index(con, state.task_id)
            finally:
                con.close()

        retry_busy(_do_save, retries=5, base_delay_seconds=0.02)

    def _plan_sync_paths(self, task_id: str) -> tuple[Path, Path]:
        import hashlib

        digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
        db_path = Path(self.state_store.db_path)
        return (db_path.parent / f".{db_path.name}.plan-sync-{int(digest[:8], 16) % 64}",
                db_path.parent / f".{db_path.name}.plan-sync-pending-{digest}.json")

    @staticmethod
    def _plan_commit_lock(lock_target: Path) -> Path:
        return lock_target.with_name(lock_target.name + "-commit")

    def _read_plan_sync_intent(self, pending: Path) -> dict[str, Any]:
        if pending.is_symlink() or getattr(pending, "is_junction", lambda: False)():
            raise ValueError("checkpoint recovery record is a link")
        if pending.stat().st_size > 65536:
            raise ValueError("checkpoint recovery record is too large")
        record = json.loads(pending.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("checkpoint recovery record is invalid")
        return record

    def _committed_plan_intents(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        entries = record.get("entries")
        if not isinstance(entries, list) or not entries or len(entries) > 64:
            raise ValueError("checkpoint recovery entries are invalid")
        committed = []
        seen = set()
        with closing(connect_sqlite(self.state_store.db_path)) as con:
            for index, entry in enumerate(entries):
                if (not isinstance(entry, dict) or not isinstance(entry.get("event_id"), str)
                        or not isinstance(entry.get("stream_id"), str)
                        or not isinstance(entry.get("previous_task_digest"), str)
                        or not isinstance(entry.get("next_task_digest"), str)
                        or not isinstance(entry.get("after"), dict)):
                    raise ValueError("checkpoint recovery entry is invalid")
                if (entry["event_id"] in seen or (index and
                        entry["previous_task_digest"] != entries[index - 1]["next_task_digest"])):
                    raise ValueError("checkpoint recovery chain is invalid")
                seen.add(entry["event_id"])
                found = con.execute(
                    "SELECT 1 FROM agent_events WHERE stream_id = ? AND event_id = ?",
                    (entry["stream_id"], entry["event_id"]),
                ).fetchone() is not None
                if found:
                    if len(committed) != index:
                        raise ValueError("checkpoint recovery events are out of order")
                    committed.append(entry)
                elif index != len(entries) - 1:
                    raise ValueError("checkpoint recovery has a missing event")
        return committed

    @staticmethod
    def _plan_sync_task_digest(state: TaskState) -> str:
        import hashlib

        data = state.to_dict()
        data.pop("stale", None)
        data.pop("stale_reason", None)
        return hashlib.sha256(json_dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    @staticmethod
    def _write_plan_sync_intent(path: Path, record: dict[str, Any]) -> None:
        payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(payload) > 65536:
            raise ValueError("checkpoint recovery record is too large")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            if os.name != "nt":
                descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)

    def _sync_plan_intents(self, state: TaskState, lock_target: Path, pending: Path) -> str:
        from .file_locks import exclusive_file_update
        from .repo_plan.agent_bridge import TaskBindingManager, project_checkpoint_fields, sync_checkpoint_to_plan
        from .repo_plan.schema_validation import RepoPlanConflictError
        from .repo_plan.storage import RepoPlanStorage

        root = _task_scope_root(state)
        commit_lock = self._plan_commit_lock(lock_target)
        with exclusive_file_update(commit_lock):
            record = self._read_plan_sync_intent(pending)
            latest = self.get(state.task_id)
            binding = TaskBindingManager(root).get_binding(state.task_id)
            if (record.get("version") != 3 or latest is None or binding is None
                    or _task_scope_root(latest) != root or record.get("task_id") != state.task_id
                    or record.get("root") != root or record.get("plan_id") != binding.plan_id
                    or record.get("plan_task_id") != binding.plan_task_id):
                raise ValueError("checkpoint recovery record identity is invalid")
            entries = record["entries"]
            committed = self._committed_plan_intents(record)
            digest = self._plan_sync_task_digest(latest)
            if not committed:
                if digest != entries[0]["previous_task_digest"]:
                    raise RepoPlanConflictError("task changed since checkpoint intent; reconcile the conflict")
                pending.unlink()
                return "not_pending"
            if digest != committed[-1]["next_task_digest"]:
                raise RepoPlanConflictError("task changed since checkpoint intent; reconcile the conflict")
            storage = RepoPlanStorage(root)
            plan, revision = storage.read_plan_file(binding.plan_rel_path)
            task = plan.get("tasks", {}).get(binding.plan_task_id)
            if not isinstance(task, dict) or not isinstance(record.get("baseline"), dict):
                raise ValueError("bound plan task or checkpoint baseline is unavailable")
            fields = ("work_status", "work_phase", "next_action", "blocker")
            before = {name: task.get(name) for name in fields}
            if before != record["baseline"] and not any(before == item["after"] for item in committed):
                raise RepoPlanConflictError("plan changed since checkpoint intent; reconcile the conflict")
            projected = dict(task)
            project_checkpoint_fields(
                projected, latest.status.value, latest.checkpoint.phase, latest.checkpoint.next_action,
                latest.checkpoint.blockers[0] if latest.checkpoint.blockers else "",
            )
            after = {name: projected.get(name) for name in fields}
            committed[-1]["after"] = after
            record["entries"] = committed
            self._write_plan_sync_intent(pending, record)
            selected = [entry["event_id"] for entry in committed]

        if before != after:
            sync_checkpoint_to_plan(
                storage=storage, binding=binding, agent_status=latest.status.value,
                phase=latest.checkpoint.phase, next_action=latest.checkpoint.next_action,
                blocker=latest.checkpoint.blockers[0] if latest.checkpoint.blockers else "",
                owner=latest.owner or "agent", expected_plan_revision=revision,
            )
        with exclusive_file_update(commit_lock):
            record = self._read_plan_sync_intent(pending)
            entries = record.get("entries")
            if (record.get("version") != 3 or not isinstance(entries, list)
                    or [entry.get("event_id") for entry in entries[:len(selected)]] != selected):
                raise RepoPlanConflictError("checkpoint intents changed during projection")
            remaining = entries[len(selected):]
            if remaining:
                record["baseline"] = after
                record["entries"] = remaining
                self._write_plan_sync_intent(pending, record)
            else:
                pending.unlink()
        return "reconciled"

    def _sync_project_plan_checkpoint(self, state: TaskState, *, only_if_pending: bool = False,
                                      _lock_held: bool = False) -> str:
        """Serialize projection writes and project the latest persisted checkpoint."""
        from .file_locks import exclusive_file_update

        root = _task_scope_root(state)
        if not root:
            return "not_bound"
        lock_target, pending = self._plan_sync_paths(state.task_id)
        with nullcontext() if _lock_held else exclusive_file_update(lock_target):
            if pending.is_symlink() or getattr(pending, "is_junction", lambda: False)():
                raise ValueError("checkpoint recovery record is a link")
            if only_if_pending and not pending.exists():
                return "not_pending"
            if pending.exists() and self._read_plan_sync_intent(pending).get("version") == 3:
                return self._sync_plan_intents(state, lock_target, pending)
            latest = self.get(state.task_id)
            if latest is None or _task_scope_root(latest) != root:
                raise RuntimeError("persisted task or repository scope changed during plan sync")
            from local_ai_hub.repo_plan.agent_bridge import TaskBindingManager, sync_checkpoint_to_plan
            from local_ai_hub.repo_plan.schema_validation import RepoPlanConflictError
            from local_ai_hub.repo_plan.storage import RepoPlanStorage
            binding = TaskBindingManager(root).get_binding(latest.task_id)
            if binding is None and pending.exists():
                raise ValueError("checkpoint recovery record has no matching plan binding")
            if binding:
                storage = RepoPlanStorage(root)
                before = None
                try:
                    plan, revision = storage.read_plan_file(binding.plan_rel_path)
                    task = plan.get("tasks", {}).get(binding.plan_task_id)
                    if not isinstance(task, dict):
                        raise ValueError("bound plan task is unavailable")
                    fields = ("work_status", "work_phase", "next_action", "blocker")
                    before = {field: task.get(field) for field in fields}
                    if pending.exists():
                        if pending.stat().st_size > 65536:
                            raise ValueError("checkpoint recovery record is too large")
                        record = json.loads(pending.read_text(encoding="utf-8"))
                        if (not isinstance(record, dict) or record.get("task_id") != latest.task_id
                                or record.get("root") != root or record.get("plan_id") != binding.plan_id
                                or record.get("plan_task_id") != binding.plan_task_id):
                            raise ValueError("checkpoint recovery record identity is invalid")
                        if record.get("version") == 2:
                            with closing(connect_sqlite(self.state_store.db_path)) as con:
                                committed = con.execute(
                                    "SELECT 1 FROM agent_events WHERE stream_id = ? AND event_id = ?",
                                    (record.get("stream_id"), record.get("event_id")),
                                ).fetchone() is not None
                            digest = self._plan_sync_task_digest(latest)
                            if not committed:
                                if digest != record.get("previous_task_digest"):
                                    raise RepoPlanConflictError("task changed since checkpoint intent; reconcile the conflict")
                                pending.unlink()
                                return "not_pending"
                            if digest != record.get("next_task_digest"):
                                raise RepoPlanConflictError("task changed since checkpoint intent; reconcile the conflict")
                            if record.get("after") == before:
                                pending.unlink()
                                return "reconciled"
                        if record.get("before") != before:
                            raise RepoPlanConflictError("plan changed since failed checkpoint sync; reconcile the conflict")
                    sync_checkpoint_to_plan(
                        storage=storage, binding=binding, agent_status=latest.status.value,
                        phase=latest.checkpoint.phase, next_action=latest.checkpoint.next_action,
                        blocker=latest.checkpoint.blockers[0] if latest.checkpoint.blockers else "",
                        owner=latest.owner or "agent", expected_plan_revision=revision,
                    )
                except Exception:
                    if not pending.exists():
                        record = {"task_id": latest.task_id, "root": root, "plan_id": binding.plan_id,
                                  "plan_task_id": binding.plan_task_id, "before": before}
                        self._write_plan_sync_intent(pending, record)
                    raise
                if pending.exists():
                    pending.unlink()
                return "reconciled"
            return "not_bound"

    def _commit_create(
        self, state: TaskState, event: AgentEvent, *, canonical_project_root: str = "",
    ) -> TaskState:
        """Atomically create initial projection, sequence cursor, and task event."""
        if not self.state_store.enabled:
            return state
        self._init_projection_table()
        context = json_dumps({
            "repository_id": state.context.repository_id,
            "clone_id": state.context.clone_id,
            "worktree_id": state.context.worktree_id,
            "branch": state.context.branch,
            "task_id": state.context.task_id,
            "session_id": state.context.session_id,
        })
        published: list[AgentEvent] = []

        def _do_commit(con: sqlite3.Connection) -> tuple[TaskState, list[AgentEvent]]:
            published.clear()
            if canonical_project_root:
                ownership_db = Path(self.state_store.db_path).parent / "agent_project_projection.sqlite"
                attached = {str(row[1]) for row in con.execute("PRAGMA database_list")}
                if "project_projection_meta" not in attached:
                    con.execute("ATTACH DATABASE ? AS project_projection_meta", (str(ownership_db),))
                con.execute(
                    """CREATE TABLE IF NOT EXISTS project_projection_meta.records (
                        repo_root TEXT NOT NULL,
                        record_kind TEXT NOT NULL,
                        record_id TEXT NOT NULL,
                        PRIMARY KEY (repo_root, record_kind, record_id)
                    )"""
                )
            with write_transaction(
                con, max_duration_seconds=_AGENT_TASK_WRITE_TIMEOUT_SECONDS,
                rollback_label="Agent task create"
            ):
                existing = con.execute(
                    """
                    SELECT stream_id, seq, event_id, kind, payload, idempotency_key,
                           correlation_id, actor, created_at
                    FROM agent_events WHERE stream_id = ? AND idempotency_key = ?
                    """,
                    (event.stream_id, event.idempotency_key),
                ).fetchone()
                if existing:
                    existing_event = AgentEvent.from_row(existing)
                    if existing_event.kind != event.kind or dict(existing_event.payload) != dict(event.payload):
                        if canonical_project_root:
                            current = con.execute(
                                "SELECT * FROM agent_tasks_projection WHERE task_id = ?",
                                (state.task_id,),
                            ).fetchone()
                            owner = con.execute(
                                "SELECT 1 FROM project_projection_meta.records "
                                "WHERE repo_root = ? AND record_kind = 'task' AND record_id = ?",
                                (canonical_project_root, state.task_id),
                            ).fetchone()
                            if current and owner and self._row_to_state(current).contract.to_dict() == state.contract.to_dict():
                                return self._row_to_state(current), []
                        raise TaskIdempotencyConflictError(
                            "task create idempotency key conflicts with a different event"
                        )
                    current = con.execute(
                        "SELECT * FROM agent_tasks_projection WHERE task_id = ?",
                        (state.task_id,),
                    ).fetchone()
                    if current:
                        if canonical_project_root:
                            con.execute(
                                "INSERT OR IGNORE INTO project_projection_meta.records "
                                "(repo_root, record_kind, record_id) VALUES (?, 'task', ?)",
                                (canonical_project_root, state.task_id),
                            )
                        return self._row_to_state(current), []
                    if str(existing_event.payload.get("task_id", "")) != state.task_id:
                        raise TaskIdempotencyConflictError(
                            "task create event conflicts with requested task identity"
                        )

                con.execute(
                    """
                    INSERT INTO agent_tasks_projection (
                        task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                        heartbeat_expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.task_id,
                        state.status.value,
                        state.owner,
                        state.lease_id,
                        json_dumps(state.contract.to_dict()),
                        context,
                        json_dumps(state.checkpoint.to_dict()),
                        json_dumps(state.verification_receipts),
                        state.heartbeat_expires_at,
                        state.created_at,
                        state.updated_at,
                    ),
                )
                if canonical_project_root:
                    con.execute(
                        "INSERT OR IGNORE INTO project_projection_meta.records "
                        "(repo_root, record_kind, record_id) VALUES (?, 'task', ?)",
                        (canonical_project_root, state.task_id),
                    )
                self._refresh_task_search_index(con, state.task_id)
                if not existing:
                    appended = self.state_store.append_in_transaction(
                        con, event, strict_idempotency=True
                    )
                    if appended.error or appended.event is None:
                        raise RuntimeError(appended.error or "task creation append returned no persisted event")
                    if appended.duplicate:
                        raise RuntimeError("task projection/event idempotency mismatch")
                    if appended.event:
                        published.append(appended.event)
                return state, published
        res = self._run_ordered_task_write(
            _do_commit, timeout_seconds=_AGENT_TASK_WRITE_TIMEOUT_SECONDS
        )
        try:
            self._sync_project_plan_checkpoint(res)
        except Exception as exc:
            raise RuntimeError(
                f"Agent OS task {res.task_id} was persisted, but its project-plan checkpoint sync failed; "
                "the durable checkpoint is available; if bound, reread the plan and use plan_bind_task "
                "with the same task and session after resolving the error"
            ) from exc
        return res

    def _commit_update(
        self,
        current: TaskState,
        updated: TaskState,
        event: AgentEvent,
        *,
        allow_server_memory_refresh: bool = False,
        allow_server_work_update: bool = False,
    ) -> TaskState:
        """CAS-update projection and append its event/cursor in one transaction."""
        checkpoint = _preserve_checkpoint_memory_state(
            current.checkpoint.state_data,
            updated.checkpoint,
            allow_server_memory_refresh=allow_server_memory_refresh,
            allow_server_work_update=allow_server_work_update,
        )
        if checkpoint != updated.checkpoint:
            updated = replace(updated, checkpoint=checkpoint)
        if not self._db_path_available():
            raise RuntimeError("agent task storage is unavailable")
        expected_context = json_dumps({
            "repository_id": current.context.repository_id,
            "clone_id": current.context.clone_id,
            "worktree_id": current.context.worktree_id,
            "branch": current.context.branch,
            "task_id": current.context.task_id,
            "session_id": current.context.session_id,
        })
        context = json_dumps({
            "repository_id": updated.context.repository_id,
            "clone_id": updated.context.clone_id,
            "worktree_id": updated.context.worktree_id,
            "branch": updated.context.branch,
            "task_id": updated.context.task_id,
            "session_id": updated.context.session_id,
        })
        values = (
            updated.status.value,
            updated.owner,
            updated.lease_id,
            json_dumps(updated.contract.to_dict()),
            context,
            json_dumps(updated.checkpoint.to_dict()),
            json_dumps(updated.verification_receipts),
            updated.heartbeat_expires_at,
            updated.updated_at,
        )
        expected_values = (
            current.task_id,
            current.status.value,
            current.owner,
            current.lease_id,
            json_dumps(current.contract.to_dict()),
            expected_context,
            json_dumps(current.checkpoint.to_dict()),
            json_dumps(current.verification_receipts),
            current.heartbeat_expires_at,
            current.updated_at,
        )
        published: list[AgentEvent] = []

        def _do_commit(con: sqlite3.Connection) -> tuple[TaskState, list[AgentEvent]]:
            published.clear()
            with write_transaction(
                con, max_duration_seconds=_AGENT_TASK_WRITE_TIMEOUT_SECONDS,
                rollback_label="Agent task update"
            ):
                if event.idempotency_key:
                    existing = con.execute(
                        "SELECT stream_id, seq, event_id, kind, payload, idempotency_key, "
                        "correlation_id, actor, created_at FROM agent_events "
                        "WHERE stream_id = ? AND idempotency_key = ?",
                        (event.stream_id, event.idempotency_key),
                    ).fetchone()
                    if existing:
                        existing_event = AgentEvent.from_row(existing)
                        if existing_event.actor != event.actor:
                            raise ValueError("idempotency key was already used")
                        if (
                            existing_event.kind != event.kind
                            or dict(existing_event.payload) != dict(event.payload)
                            or existing_event.correlation_id != event.correlation_id
                        ):
                            raise ValueError(
                                "idempotency key was already used for a different event payload"
                            )
                        current_row = con.execute(
                            "SELECT * FROM agent_tasks_projection WHERE task_id = ?",
                            (current.task_id,),
                        ).fetchone()
                        if not current_row:
                            raise RuntimeError("task event exists without its durable projection")
                        replayed = self._row_to_state(current_row)
                        return replayed, []

                con.execute(
                    """
                    UPDATE agent_tasks_projection SET
                        status = ?, owner = ?, lease_id = ?, contract = ?, context = ?, checkpoint = ?,
                        receipts = ?, heartbeat_expires_at = ?, updated_at = ?
                    WHERE task_id = ? AND status = ? AND owner = ? AND lease_id = ? AND contract = ?
                      AND context = ? AND checkpoint = ? AND receipts = ? AND heartbeat_expires_at = ?
                      AND updated_at = ?
                    """,
                    (*values, *expected_values),
                )
                if con.execute("SELECT changes()").fetchone()[0] != 1:
                    current_row = con.execute(
                        "SELECT task_id, status, owner, lease_id, contract, context, checkpoint, receipts, "
                        "heartbeat_expires_at, updated_at FROM agent_tasks_projection WHERE task_id = ?",
                        (current.task_id,),
                    ).fetchone()
                    columns = (
                        "task_id", "status", "owner", "lease_id", "contract", "context",
                        "checkpoint", "receipts", "heartbeat_expires_at", "updated_at",
                    )
                    changed_fields = [
                        name for name, actual, expected in zip(columns, current_row or (), expected_values)
                        if actual != expected
                    ]
                    raise ConcurrentTaskUpdateError(
                        f"Task {current.task_id} changed during transition; fields changed: "
                        f"{', '.join(changed_fields) or 'projection unavailable'}; reload and retry"
                    )
                if (
                    updated.owner != current.owner
                    or updated.contract != current.contract
                    or updated.context != current.context
                    or updated.checkpoint != current.checkpoint
                ):
                    self._refresh_task_search_index(con, updated.task_id)
                appended = self.state_store.append_in_transaction(
                    con, event, strict_idempotency=True
                )
                if appended.error or appended.event is None:
                    raise RuntimeError(appended.error or "task transition append returned no persisted event")
                if appended.duplicate:
                    raise RuntimeError("task projection/event idempotency mismatch")
                if appended.event:
                    published.append(appended.event)
                return updated, published
        root = _task_scope_root(current)
        if not root:
            return self._run_ordered_task_write(
                _do_commit, timeout_seconds=_AGENT_TASK_WRITE_TIMEOUT_SECONDS
            )

        from .file_locks import exclusive_file_update
        from .repo_plan.agent_bridge import TaskBindingManager, project_checkpoint_fields
        from .repo_plan.storage import RepoPlanStorage

        lock_target, pending = self._plan_sync_paths(current.task_id)
        with exclusive_file_update(self._plan_commit_lock(lock_target)):
            if pending.is_symlink() or getattr(pending, "is_junction", lambda: False)():
                raise ValueError("checkpoint recovery record is a link")
            latest = self.get(current.task_id)
            if latest is None or self._plan_sync_task_digest(latest) != self._plan_sync_task_digest(current):
                raise ConcurrentTaskUpdateError(f"Task {current.task_id} changed during transition; reload and retry")
            self._publish_project_task_update(current, updated, event, root)
            binding = TaskBindingManager(root).get_binding(current.task_id)
            if binding is None and pending.exists():
                raise ValueError("checkpoint recovery binding is unavailable")
            if binding is not None:
                storage = RepoPlanStorage(root)
                plan, _revision = storage.read_plan_file(binding.plan_rel_path)
                task = plan.get("tasks", {}).get(binding.plan_task_id)
                if not isinstance(task, dict):
                    raise ValueError("bound plan task is unavailable")
                fields = ("work_status", "work_phase", "next_action", "blocker")
                before = {name: task.get(name) for name in fields}
                projected = dict(task)
                project_checkpoint_fields(
                    projected, updated.status.value, updated.checkpoint.phase,
                    updated.checkpoint.next_action,
                    updated.checkpoint.blockers[0] if updated.checkpoint.blockers else "",
                )
                if pending.exists():
                    record = self._read_plan_sync_intent(pending)
                    if (record.get("version") != 3 or record.get("task_id") != current.task_id
                            or record.get("root") != root or record.get("plan_id") != binding.plan_id
                            or record.get("plan_task_id") != binding.plan_task_id):
                        raise ValueError("checkpoint recovery requires reconciliation before another update")
                    committed = self._committed_plan_intents(record)
                    entries = record["entries"]
                    expected = committed[-1]["next_task_digest"] if committed else entries[0]["previous_task_digest"]
                    if expected != self._plan_sync_task_digest(current):
                        raise ConcurrentTaskUpdateError("checkpoint recovery task state changed")
                    record["entries"] = committed
                else:
                    record = {"version": 3, "task_id": current.task_id, "root": root,
                              "plan_id": binding.plan_id, "plan_task_id": binding.plan_task_id,
                              "baseline": before, "entries": []}
                record["entries"].append({
                    "stream_id": event.stream_id, "event_id": event.event_id,
                    "previous_task_digest": self._plan_sync_task_digest(current),
                    "next_task_digest": self._plan_sync_task_digest(updated),
                    "after": {name: projected.get(name) for name in fields},
                })
                if len(record["entries"]) > 64:
                    raise ValueError("too many pending checkpoint updates")
                self._write_plan_sync_intent(pending, record)
            res = self._run_ordered_task_write(
                _do_commit, timeout_seconds=_AGENT_TASK_WRITE_TIMEOUT_SECONDS
            )
        try:
            self._sync_project_plan_checkpoint(res)
        except Exception as exc:
            raise RuntimeError(
                f"Agent OS task {res.task_id} was persisted, but its project-plan checkpoint sync failed; "
                "the durable checkpoint is available; if bound, reread the plan and use plan_bind_task "
                "with the same task and session after resolving the error"
            ) from exc
        return res

    def _publish_project_task_update(
        self, current: TaskState, updated: TaskState, event: AgentEvent, root: str,
    ) -> None:
        """CAS-publish shared task progress before updating its SQLite projection."""
        project_dir = Path(root) / ".local-ai-hub"
        if not project_dir.exists():
            return
        manifest_path = project_dir / "project.json"
        if not manifest_path.is_file():
            raise ValueError("A stable project identity must be bootstrapped before updating a project task")

        from .repo_knowledge import RepoKnowledgeStore
        from .repo_plan.schema_validation import RepoPlanConflictError
        from .repo_project_tasks import build_project_task_record, validate_project_task_payload

        store = RepoKnowledgeStore(root)
        manifest, _ = store.manifest()
        if manifest["mode"] != "shared":
            return
        scope = current.checkpoint.state_data.get("_agent_task_scope", {})
        if scope.get("project_id") != manifest["project_id"]:
            raise ValueError("Task project identity no longer matches its repository manifest")

        try:
            existing = store.get("task", current.task_id, verify_sources=False)
        except FileNotFoundError as exc:
            raise RepoPlanConflictError(
                "Canonical project task is missing; complete the one-time project migration before updating it"
            ) from exc
        existing_record = existing["record"]
        if existing_record.get("project_id") != manifest["project_id"]:
            raise RepoPlanConflictError("Canonical task belongs to a different project")

        def durable_projection(state: TaskState) -> dict[str, Any]:
            candidate = build_project_task_record(store, {
                "task_id": state.task_id,
                "status": state.status.value,
                "contract": state.contract.to_dict(),
                "checkpoint": state.checkpoint.to_dict(),
            })
            return candidate["payload"]

        current_payload = durable_projection(current)
        updated_payload = durable_projection(updated)
        actual_payload = existing_record.get("payload", {})
        durable_fields = ("task_id", "status", "contract", "checkpoint")

        def has_payload(payload: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
            return all(payload.get(key) == expected.get(key) for key in durable_fields)

        if has_payload(actual_payload, updated_payload):
            return
        if not has_payload(actual_payload, current_payload):
            raise ConcurrentTaskUpdateError(
                f"Canonical task {current.task_id} changed in Git; reload before retrying"
            )

        candidate_record = dict(existing_record)
        candidate_record["payload"] = {**actual_payload, **updated_payload}
        validate_project_task_payload(candidate_record)
        try:
            saved = store.save(
                candidate_record,
                expected_revision=existing["revision"],
                owner=event.actor or "agent-task-update",
                idempotency_key=event.idempotency_key,
                authorize_write=lambda: True,
            )
        except RepoPlanConflictError as exc:
            expected_target = f".local-ai-hub/agent-os/tasks/{current.task_id}.json"
            if str(exc).startswith(f"Content revision conflict on {expected_target}:"):
                raise ConcurrentTaskUpdateError(
                    f"Canonical task {current.task_id} changed in Git; reload before retrying"
                ) from exc
            raise
        if saved.get("success") is True:
            return

        # A same-checkout agent may have published the identical safe state
        # after our read. Only that exact result counts as an idempotent retry.
        try:
            latest_record = store.get("task", current.task_id, verify_sources=False)["record"]
        except FileNotFoundError:
            latest_record = None
        if latest_record is not None and has_payload(latest_record.get("payload", {}), updated_payload):
            return
        raise ConcurrentTaskUpdateError(
            f"Canonical task {current.task_id} changed in Git; reload before retrying"
        )

    def _row_to_state(self, row: tuple[Any, ...]) -> TaskState:
        (
            task_id,
            status_val,
            owner,
            lease_id,
            contract_raw,
            context_raw,
            checkpoint_raw,
            receipts_raw,
            heartbeat_expires_at,
            created_at,
            updated_at,
        ) = row
        # Persisted corruption is explicit; never manufacture task provenance.
        return TaskState.from_dict({
            "task_id": task_id,
            "status": status_val,
            "owner": owner,
            "lease_id": lease_id,
            "contract": json.loads(contract_raw),
            "context": json.loads(context_raw),
            "checkpoint": json.loads(checkpoint_raw),
            "verification_receipts": json.loads(receipts_raw),
            "heartbeat_expires_at": heartbeat_expires_at,
            "created_at": created_at,
            "updated_at": updated_at,
        })

