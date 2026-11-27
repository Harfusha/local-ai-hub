from __future__ import annotations

from contextlib import closing
import math
from pathlib import Path
import threading
import time
from typing import Any

from .agent_task_models import (
    MAX_TASK_REAP_BATCH,
    CheckpointResponseBudgetError,
    ConcurrentTaskUpdateError,
    TaskCheckpoint,
    TaskState,
    TaskStatus,
    _canonical_repository_root,
    _task_matches_scope,
    _task_scope_root,
)
from .sqlite_support import connect_sqlite, retry_busy
from .task_memory_wire import mcp_wire_tokens
from .project_identity import project_scope_id, repository_snapshot_id, worktree_scope_id


TaskStore = None


class TaskWorktreeMixin:
    def cleanup_worktree(
        self,
        task_id: str,
        delete_branch: bool = True,
        *,
        actor: str = "http-default",
        response_budget_tokens: int | None = None,
        _timeout_seconds: float = 30.0,
        _required_base_commit: str = "",
        _deadline_monotonic: float | None = None,
    ) -> dict[str, Any]:
        task = self.get(task_id)
        if not task:
            return {"success": False, "error": f"Task {task_id} not found"}
        if response_budget_tokens is not None and (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        wt = task.checkpoint.state_data.get("worktree")
        if not isinstance(wt, dict) or not wt.get("worktree_path"):
            return {"success": True, "had_worktree": False}
        actor_value = str(actor or "").strip()
        if not actor_value or actor_value.lower() in {"http-default", "system", "admin", "*"}:
            return {"success": False, "error": "cleanup requires a non-reserved owner actor"}
        if actor_value != task.owner:
            return {"success": False, "error": "cleanup actor does not own task"}

        try:
            from .git_worktrees import (
                get_git_worktree_ownership,
                remove_git_worktree,
                verify_git_worktree_cleanup_complete,
            )

            task_id_value = str(wt.get("task_id", ""))
            owner_value = str(wt.get("owner", ""))
            repo_value = Path(_canonical_repository_root(wt.get("repo_root")))
            worktree_id = str(wt.get("worktree_id", ""))
            branch = str(wt.get("branch", ""))
            worktree_path = Path(str(wt.get("worktree_path", ""))).expanduser()
            if not task_id_value or task_id_value != task.task_id:
                return {"success": False, "error": "worktree task identity mismatch"}
            if not owner_value or owner_value != task.owner:
                return {"success": False, "error": "worktree owner identity mismatch"}
            if not worktree_id or not branch or worktree_path.is_symlink():
                return {"success": False, "error": "worktree ownership metadata is incomplete"}
            scope_root = _task_scope_root(task)
            if not scope_root:
                return {"success": False, "error": "worktree cleanup requires the server-managed task scope root"}
            expected_repo = Path(scope_root)
            if repo_value != expected_repo:
                return {"success": False, "error": "worktree repository does not match the server-managed task scope"}
            created_at = float(wt["created_at"])
            ttl_seconds = float(wt["ttl_seconds"])
            expires_at = float(wt["expires_at"])
            if (
                not math.isfinite(created_at)
                or not math.isfinite(ttl_seconds)
                or not math.isfinite(expires_at)
                or ttl_seconds < 60.0
                or ttl_seconds > 30 * 24 * 60 * 60.0
                or abs(expires_at - (created_at + ttl_seconds)) > 0.001
            ):
                return {"success": False, "error": "worktree lifetime metadata is inconsistent"}
            if wt.get("cleanup_success") and not worktree_path.exists():
                return {"success": True, "had_worktree": True, "already_cleaned": True}

            cleaned_at = time.time()
            cleaned_wt = {**wt, "cleanup_success": True, "cleaned_at": cleaned_at}
            cleaned_wt.pop("cleanup_pending", None)
            cleaned_wt.pop("cleanup_warning", None)
            cleaned_wt.pop("cleanup_intent", None)
            projected_data = {**task.checkpoint.state_data, "worktree": cleaned_wt}
            projected_checkpoint = TaskCheckpoint(
                phase=task.checkpoint.phase,
                next_action=task.checkpoint.next_action,
                affected_paths=task.checkpoint.affected_paths,
                evidence_ids=task.checkpoint.evidence_ids,
                blockers=task.checkpoint.blockers,
                state_data=projected_data,
            )
            projected_task = TaskState(
                task_id=task.task_id,
                status=task.status,
                contract=task.contract,
                context=task.context,
                owner=task.owner,
                lease_id=task.lease_id,
                created_at=task.created_at,
                updated_at=cleaned_at,
                heartbeat_expires_at=task.heartbeat_expires_at,
                checkpoint=projected_checkpoint,
                verification_receipts=task.verification_receipts,
            )
            self._preflight_response_budget(projected_task, response_budget_tokens)
            if response_budget_tokens is not None:
                projected_cleanup = {
                    "success": True,
                    "worktree_removed": True,
                    "branch_deleted": bool(delete_branch),
                    "repo_root": str(repo_value),
                    "worktree_path": str(worktree_path.resolve(strict=False)),
                    "worktree_id": worktree_id,
                }
                projected_response = self._include_current_request_id({
                    "success": True,
                    "had_worktree": True,
                    "cleanup": projected_cleanup,
                    "cleaned_at": cleaned_at,
                    "task": projected_task.to_dict(),
                })
                required_tokens = mcp_wire_tokens(
                    projected_response, text_payload=projected_response,
                )
                if required_tokens > response_budget_tokens:
                    raise CheckpointResponseBudgetError(response_budget_tokens, required_tokens)
            cleanup_intent = wt.get("cleanup_intent")
            expected_intent = {
                "task_id": task_id_value,
                "owner": owner_value,
                "worktree_id": worktree_id,
                "branch": branch,
                "delete_branch": bool(delete_branch),
                "repo_root": str(repo_value),
                "worktree_path": str(worktree_path.resolve(strict=False)),
            }
            if cleanup_intent is not None and cleanup_intent != expected_intent:
                return {"success": False, "error": "worktree cleanup intent does not match this request"}
            if cleanup_intent == expected_intent and not worktree_path.exists():
                reconciled = verify_git_worktree_cleanup_complete(
                    repo_value,
                    worktree_path,
                    branch_name=branch,
                    delete_branch=bool(delete_branch),
                    timeout_seconds=_timeout_seconds,
                    deadline_monotonic=_deadline_monotonic,
                )
                if not reconciled.get("success"):
                    return {
                        "success": False,
                        "had_worktree": True,
                        "cleanup": reconciled,
                        "error": reconciled.get("error", "cleanup outcome could not be reconciled"),
                    }
                updated = self.checkpoint(
                    task_id,
                    projected_checkpoint,
                    actor=actor_value,
                    idempotency_key=f"cleanup_{task_id}_{worktree_id}",
                    response_budget_tokens=response_budget_tokens,
                )
                return {
                    "success": True,
                    "had_worktree": True,
                    "already_cleaned": True,
                    "cleanup": reconciled,
                    "cleaned_at": cleaned_at,
                    "task": updated.to_dict(),
                }
            ownership = get_git_worktree_ownership(
                repo_value, worktree_path, deadline_monotonic=_deadline_monotonic
            )
            if ownership is None:
                return {"success": False, "error": "live worktree ownership marker is missing"}
            expected_fields = (
                "worktree_id",
                "task_id",
                "owner",
                "repo_root",
                "worktree_path",
                "branch",
                "created_at",
                "ttl_seconds",
                "expires_at",
                "base_commit",
                "creator_pid",
                "creator_creation_identity",
                "creator_creation_identity_type",
                "creator_executable",
            )
            if any(ownership.get(field) != wt.get(field) for field in expected_fields):
                return {"success": False, "error": "worktree ownership metadata was tampered"}

            if cleanup_intent is None:
                intent_wt = {**wt, "cleanup_intent": expected_intent, "cleanup_pending": True}
                intent_checkpoint = TaskCheckpoint(
                    phase=task.checkpoint.phase,
                    next_action=task.checkpoint.next_action,
                    affected_paths=task.checkpoint.affected_paths,
                    evidence_ids=task.checkpoint.evidence_ids,
                    blockers=task.checkpoint.blockers,
                    state_data={**task.checkpoint.state_data, "worktree": intent_wt},
                )
                self.checkpoint(
                    task_id,
                    intent_checkpoint,
                    actor=actor_value,
                    idempotency_key=f"cleanup_intent_{task_id}_{worktree_id}_{int(bool(delete_branch))}",
                    response_budget_tokens=response_budget_tokens,
                )

            rm_res = remove_git_worktree(
                repo_value,
                worktree_path,
                delete_branch=delete_branch,
                branch_name=branch,
                worktree_id=worktree_id,
                expected_task_id=task_id,
                expected_owner=str(wt.get("owner", "")),
                expected_created_at=created_at,
                expected_ttl_seconds=ttl_seconds,
                expected_expires_at=expires_at,
                timeout_seconds=_timeout_seconds,
                required_base_commit=_required_base_commit,
                deadline_monotonic=_deadline_monotonic,
            )
            if not rm_res.get("success"):
                return {"success": False, "had_worktree": True, "cleanup": rm_res, "error": rm_res.get("error", "cleanup failed")}

            updated = self.checkpoint(
                task_id,
                projected_checkpoint,
                actor=actor_value,
                idempotency_key=f"cleanup_{task_id}_{worktree_id}",
            )
            return {
                "success": True,
                "had_worktree": True,
                "cleanup": rm_res,
                "cleaned_at": cleaned_at,
                "task": updated.to_dict(),
            }
        except CheckpointResponseBudgetError:
            raise
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _expired_repository_roots(self, *, now: float, limit: int = 16, after_root: str = "") -> list[str]:
        """Bounded watchdog inventory from the server-managed task scope."""
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
            raise ValueError("now must be a finite timestamp")
        if type(limit) is not int or not 1 <= limit <= 64:
            raise ValueError("root limit must be an integer between 1 and 64")
        if not isinstance(after_root, str) or after_root != after_root.strip() or "\x00" in after_root:
            raise ValueError("after_root must be a canonical string")
        if not self._db_path_available():
            return []
        self._init_projection_table()
        def _read() -> list[str]:
            document = "CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END"
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                rows = con.execute(
                    "SELECT json_extract(" + document + ", '$.state_data._agent_task_scope.repo_root') AS scoped_root "
                    "FROM agent_tasks_projection "
                    "WHERE status IN ('planned', 'active', 'verifying', 'waiting', 'blocked') "
                    "AND heartbeat_expires_at > 0 AND heartbeat_expires_at < ? "
                    "AND json_type(" + document + ", '$.state_data._agent_task_scope.version') = 'integer' "
                    "AND json_extract(" + document + ", '$.state_data._agent_task_scope.version') = 4 "
                    "AND json_type(" + document + ", '$.state_data._agent_task_scope.repo_root') = 'text' "
                    "AND json_extract(" + document + ", '$.state_data._agent_task_scope.repo_root') != '' "
                    "GROUP BY scoped_root HAVING scoped_root > ? ORDER BY scoped_root LIMIT ?",
                    (now, after_root, limit),
                ).fetchall()
            return [row[0] for row in rows]
        return retry_busy(_read, retries=5, base_delay_seconds=0.02)

    def reap_expired_heartbeats(
        self,
        now: float | None = None,
        *,
        auto_recover: bool = False,
        repo_root: str | Path | None = None,
        task_id: str | None = None,
        response_budget_tokens: int | None = None,
        _deadline_monotonic: float | None = None,
        _cancel_event: threading.Event | None = None,
    ) -> list[str]:
        if task_id is not None and (not isinstance(task_id, str) or not task_id or task_id != task_id.strip() or "\x00" in task_id):
            raise ValueError("task_id must be a nonempty canonical string when supplied")
        if now is not None and (isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now)):
            raise ValueError("now must be a finite timestamp")
        if _deadline_monotonic is not None and (isinstance(_deadline_monotonic, bool) or not isinstance(_deadline_monotonic, (int, float)) or not math.isfinite(_deadline_monotonic)):
            raise ValueError("deadline must be finite")
        if response_budget_tokens is not None:
            if (
                isinstance(response_budget_tokens, bool)
                or not isinstance(response_budget_tokens, int)
                or response_budget_tokens < 1
            ):
                raise ValueError("response_budget_tokens must be a positive integer")
            if not isinstance(task_id, str) or not task_id or task_id != task_id.strip():
                raise ValueError("response budget requires a nonempty canonical task_id")
            projected_response = self._include_current_request_id({"success": True, "reaped": [task_id]})
            required_tokens = mcp_wire_tokens(
                projected_response, text_payload=projected_response,
            )
            if required_tokens > response_budget_tokens:
                raise CheckpointResponseBudgetError(response_budget_tokens, required_tokens)
        try:
            scoped_root = _canonical_repository_root(repo_root)
            scoped_project_id = project_scope_id(scoped_root)
            scoped_worktree_id = worktree_scope_id(scoped_root)
            scoped_snapshot_id = repository_snapshot_id(scoped_root)
        except ValueError:
            return []
        if not self._db_path_available():
            return []
        self._init_projection_table()
        current_time = float(time.time() if now is None else now)
        def _fetch_expired() -> list[str]:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                task_filter = " AND task_id = ?" if task_id is not None else ""
                parameters = (
                    (current_time, scoped_project_id, scoped_worktree_id, scoped_snapshot_id, task_id, MAX_TASK_REAP_BATCH)
                    if task_id is not None
                    else (current_time, scoped_project_id, scoped_worktree_id, scoped_snapshot_id, MAX_TASK_REAP_BATCH)
                )
                cur = con.execute(
                    """
                    SELECT task_id FROM agent_tasks_projection
                    WHERE status IN ('planned', 'active', 'verifying', 'waiting', 'blocked')
                      AND heartbeat_expires_at > 0 AND heartbeat_expires_at < ?
                      AND json_type(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.version') = 'integer'
                      AND json_extract(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.version') = 4
                      AND json_extract(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.project_id') = ?
                      AND (owner='canonical-git' OR json_extract(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.worktree_id') = ?)
                      AND json_extract(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.snapshot_id') = ?
                    """ + task_filter + " ORDER BY heartbeat_expires_at, task_id LIMIT ?",
                    parameters,
                )
                return [row[0] for row in cur.fetchall()]

        expired_ids = retry_busy(_fetch_expired, retries=5, base_delay_seconds=0.02)

        reaped: list[str] = []
        for t_id in expired_ids:
            if (_cancel_event is not None and _cancel_event.is_set()) or (
                _deadline_monotonic is not None and time.monotonic() >= _deadline_monotonic
            ):
                break
            try:
                current = self.get(t_id)
                if (
                    current is None
                    or not _task_matches_scope(current, scoped_root, task_id)
                    or current.status not in {
                        TaskStatus.PLANNED,
                        TaskStatus.ACTIVE,
                        TaskStatus.VERIFYING,
                        TaskStatus.WAITING,
                        TaskStatus.BLOCKED,
                    }
                    or current.heartbeat_expires_at <= 0
                    or current.heartbeat_expires_at >= current_time
                ):
                    continue
                target_status = TaskStatus.WAITING if auto_recover and current and current.status != TaskStatus.PLANNED else TaskStatus.ABANDONED
                reason = "heartbeat expired - auto-recovered to waiting" if auto_recover else "heartbeat expired"
                self.transition(
                    t_id,
                    target_status,
                    reason=reason,
                    actor="system",
                    idempotency_key=f"reap_{t_id}_{int(current_time)}",
                    _expected_reap=(
                        scoped_root,
                        current.status,
                        current.heartbeat_expires_at,
                        current_time,
                    ),
                )
                reaped.append(t_id)
            except (ConcurrentTaskUpdateError, KeyError):
                pass
        return reaped

    def recover_zombie_tasks(
        self,
        now: float | None = None,
        *,
        repo_root: str | Path | None = None,
        task_id: str | None = None,
    ) -> list[str]:
        """Automatically detect timed-out zombie tasks and recover them to WAITING state for re-assignment."""
        return self.reap_expired_heartbeats(
            now=now,
            auto_recover=True,
            repo_root=repo_root,
            task_id=task_id,
        )

