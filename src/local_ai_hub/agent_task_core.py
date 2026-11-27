from __future__ import annotations

from collections.abc import Mapping
from contextlib import closing
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any
import unicodedata
import uuid

from .agent_events import AgentEvent
from .agent_identity import ScopeContext
from .agent_task_models import (
    MAX_TASK_QUERY_SCAN_ROWS,
    GoalContract,
    TaskCheckpoint,
    TaskPage,
    TaskState,
    TaskStatus,
    TaskWorktreeError,
    _canonical_repository_root,
    _task_matches_scope,
)
from .json_utils import dumps as json_dumps
from .project_identity import project_scope_id, repository_snapshot_id, worktree_scope_id
from .sqlite_support import connect_sqlite, retry_busy


TaskStore = None


class TaskCoreMixin:
    def create(
        self,
        contract: GoalContract,
        context: ScopeContext,
        *,
        task_id: str | None = None,
        actor: str = "agent",
        idempotency_key: str = "",
        auto_worktree: bool = False,
        repo_root: str = "",
        root: str = "",
        repository_revision: str = "",
        worktree_ttl_seconds: float = 24 * 60 * 60.0,
        response_budget_tokens: int | None = None,
        _handoff_resume: dict[str, Any] | None = None,
    ) -> TaskState:
        if not isinstance(auto_worktree, bool):
            raise ValueError("auto_worktree must be a boolean")
        if response_budget_tokens is not None and (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")
        repo_root = repo_root or root
        t_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
        now = time.time()
        initial_status = TaskStatus.PLANNED
        initial_sd: dict[str, Any] = {"contract_revision": 1}
        try:
            canonical_root = _canonical_repository_root(repo_root) if repo_root else ""
            if auto_worktree and not canonical_root:
                raise ValueError("automatic worktree preparation requires an explicit repository root")
        except ValueError as exc:
            if auto_worktree:
                raise TaskWorktreeError(
                    f"automatic worktree preparation failed: {exc}",
                    mutation_applied=False,
                    operation_not_started=True,
                    outcome_unknown=False,
                ) from exc
            raise
        if _handoff_resume is not None:
            from .repo_task_handoff import validate_resume_creation

            initial_sd["_portable_attempt"] = validate_resume_creation({
                "root": canonical_root, "repo_root": canonical_root,
                "task_id": t_id, "contract": contract.to_dict(),
                "handoff_resume": _handoff_resume, "auto_worktree": auto_worktree,
            })
        worktree_plan = None
        if canonical_root:
            initial_sd["repo_root"] = canonical_root
        if repository_revision:
            initial_sd["repository_revision"] = str(repository_revision).strip()

        if auto_worktree:
            try:
                from .git_worktrees import prepare_git_worktree
                r_root = canonical_root
                worktree_ttl = max(60.0, min(float(worktree_ttl_seconds), 30 * 24 * 60 * 60.0))
                worktree_expiry = now + worktree_ttl
                worktree_plan = prepare_git_worktree(
                    r_root,
                    branch_name=f"hub/task-{t_id}",
                    task_id=t_id,
                    owner=actor,
                    created_at=now,
                    ttl_seconds=worktree_ttl,
                    expires_at=worktree_expiry,
                )
                initial_sd["worktree"] = worktree_plan.response_metadata()
                if not canonical_root:
                    canonical_root = worktree_plan.repo_root
                    initial_sd["repo_root"] = canonical_root
            except Exception as exc:
                raise TaskWorktreeError(
                    f"automatic worktree preparation failed: {type(exc).__name__}: {exc}",
                    mutation_applied=False,
                    operation_not_started=True,
                    outcome_unknown=False,
                    cleanup_succeeded=None,
                ) from exc

        if canonical_root:
            initial_sd["_agent_task_scope"] = {
                "version": 4,
                "project_id": project_scope_id(canonical_root),
                "worktree_id": worktree_scope_id(canonical_root),
                "repo_root": canonical_root,
                "snapshot_id": repository_snapshot_id(canonical_root),
            }

        memory_context = self._task_memory_context(
            t_id, contract, context, root_override=canonical_root or repo_root
        )
        if memory_context is not None:
            initial_sd["memory_context"] = memory_context

        initial_state = TaskState(
            task_id=t_id,
            status=initial_status,
            contract=contract,
            context=context,
            owner=actor,
            lease_id="",
            created_at=now,
            updated_at=now,
            heartbeat_expires_at=0.0,
            checkpoint=TaskCheckpoint(state_data=initial_sd),
            verification_receipts={},
        )

        self._preflight_response_budget(initial_state, response_budget_tokens)
        if worktree_plan is not None:
            try:
                from .git_worktrees import create_git_worktree
                r_root = canonical_root
                wt_res = create_git_worktree(
                    r_root,
                    branch_name=f"hub/task-{t_id}",
                    task_id=t_id,
                    owner=actor,
                    created_at=now,
                    ttl_seconds=worktree_plan.ttl_seconds,
                    expires_at=worktree_plan.expires_at,
                    prepared_plan=worktree_plan,
                )
            except Exception as exc:
                raise TaskWorktreeError(
                    f"automatic worktree creation outcome is unknown: {type(exc).__name__}: {exc}",
                    mutation_applied=None,
                    operation_not_started=False,
                    outcome_unknown=True,
                ) from exc
            if not wt_res.get("success"):
                raise TaskWorktreeError(
                    str(wt_res.get("error") or "automatic worktree creation failed"),
                    mutation_applied=wt_res.get("mutation_applied"),
                    operation_not_started=wt_res.get("operation_not_started") is True,
                    outcome_unknown=wt_res.get("outcome_unknown") is True,
                    cleanup_succeeded=wt_res.get("cleanup_succeeded"),
                )
            if wt_res != worktree_plan.response_metadata():
                raise TaskWorktreeError(
                    "automatic worktree creation metadata differed from its preflight plan",
                    mutation_applied=True,
                    operation_not_started=False,
                    outcome_unknown=True,
                )

        event = AgentEvent.create(
            stream_id=f"task:{t_id}",
            kind="task.created",
            payload=initial_state.to_dict(),
            idempotency_key=idempotency_key or f"create_{t_id}",
            actor=actor,
        )
        try:
            return self._commit_create(initial_state, event)
        except Exception as exc:
            if worktree_plan is not None:
                raise TaskWorktreeError(
                    f"task persistence failed after automatic worktree creation: {type(exc).__name__}: {exc}",
                    mutation_applied=True,
                    operation_not_started=False,
                    outcome_unknown=True,
                    cleanup_succeeded=None,
                ) from exc
            raise

    def has_task(self, task_id: str) -> bool:
        clean_id = str(task_id or "").replace("\x00", "").strip()
        if not clean_id:
            return False
        if not self._db_path_available():
            return False
        self._init_projection_table()

        def _do_check() -> bool:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                row = con.execute(
                    "SELECT 1 FROM agent_tasks_projection WHERE task_id = ?",
                    (clean_id,),
                ).fetchone()
                return bool(row)

        try:
            return bool(retry_busy(_do_check, retries=5, base_delay_seconds=0.02))
        except sqlite3.Error:
            return False

    def get(self, task_id: str, *, repo_root: str | None = None) -> TaskState | None:
        if not self._db_path_available():
            return None
        self._init_projection_table()
        canonical_root: str | None = None
        if repo_root is not None:
            try:
                canonical_root = _canonical_repository_root(repo_root)
            except ValueError:
                return None
            project_dir = Path(canonical_root) / ".local-ai-hub"
            if (project_dir / "project.json").is_file() and (project_dir / "agent-os").is_dir():
                from .repo_agent_state import ensure_agent_state_projection_current

                projection = ensure_agent_state_projection_current(
                    canonical_root, Path(self.state_store.db_path).parent,
                )
                if projection.get("success") is not True:
                    raise RuntimeError(projection.get("error", "Agent OS projection refresh failed"))
        def _fetch_task() -> Any:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                return con.execute(
                    """
                    SELECT task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                           heartbeat_expires_at, created_at, updated_at
                    FROM agent_tasks_projection
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()

        row = retry_busy(_fetch_task, retries=5, base_delay_seconds=0.02)
        if not row:
            return None
        task = self._row_to_state(row)
        if canonical_root is not None and not _task_matches_scope(task, canonical_root, task_id):
            return None
        return task

    @staticmethod
    def _normalize_search_text(value: Any) -> str:
        return unicodedata.normalize("NFKC", str(value or "")).casefold()

    @staticmethod
    def _collect_search_values(value: Any, fields: list[str]) -> None:
        if isinstance(value, Mapping):
            for item in value.values():
                TaskStore._collect_search_values(item, fields)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                TaskStore._collect_search_values(item, fields)
        elif value is not None:
            text = str(value).strip()
            if text:
                fields.append(text)

    @staticmethod
    def _searchable_task_fields(
        task_id: str,
        contract: Mapping[str, Any],
        checkpoint: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
        owner: str = "",
    ) -> tuple[str, ...]:
        fields = [str(task_id)]
        if owner:
            fields.append(str(owner))
        for source in (contract, context or {}, checkpoint):
            TaskStore._collect_search_values(source, fields)
        return tuple(fields)

    @classmethod
    def _search_grams(cls, values: Any) -> set[str]:
        if isinstance(values, str):
            values = (values,)
        grams: set[str] = set()
        for value in values:
            normalized = cls._normalize_search_text(value)
            grams.update(normalized[index:index + 3] for index in range(max(0, len(normalized) - 2)))
        return grams

    @staticmethod
    def _task_search_source_digest(
        task_id: str,
        owner: Any,
        contract_raw: Any,
        context_raw: Any,
        checkpoint_raw: Any,
    ) -> str:
        source = json_dumps(
            [task_id, owner, contract_raw or "{}", context_raw or "{}", checkpoint_raw or "{}"],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    @staticmethod
    def _task_search_gram_digest(grams: Any) -> tuple[str, int]:
        digest = hashlib.sha256()
        count = 0
        for value in grams:
            gram = value if isinstance(value, str) else value[0]
            encoded = str(gram).encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            count += 1
        return digest.hexdigest(), count

    @classmethod
    def _write_task_search_index(
        cls,
        con: sqlite3.Connection,
        task_id: str,
        fields: tuple[str, ...],
        source_digest: str,
    ) -> None:
        fields_json = json_dumps(list(fields))
        grams = cls._search_grams(fields)
        ordered_grams = sorted(grams)
        grams_digest, grams_count = cls._task_search_gram_digest(ordered_grams)
        existing_grams = {
            str(row[0])
            for row in con.execute(
                "SELECT gram FROM agent_task_search_grams WHERE task_id = ?", (task_id,)
            )
        }
        previous_index = con.execute(
            "SELECT grams_digest, grams_count FROM agent_task_search_index_state WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not (
            previous_index is not None
            and len(existing_grams) == int(previous_index[1])
            and cls._task_search_gram_digest(sorted(existing_grams))
            == (str(previous_index[0]), int(previous_index[1]))
        ):
            con.execute("DELETE FROM agent_task_search_grams WHERE task_id = ?", (task_id,))
            existing_grams.clear()
        removed_grams = sorted(existing_grams - grams)
        if removed_grams:
            con.executemany(
                "DELETE FROM agent_task_search_grams WHERE task_id = ? AND gram = ?",
                ((task_id, gram) for gram in removed_grams),
            )
        con.execute(
            "INSERT OR REPLACE INTO agent_task_search_documents(task_id, fields) VALUES (?, ?)",
            (task_id, fields_json),
        )
        added_grams = [gram for gram in ordered_grams if gram not in existing_grams]
        if added_grams:
            con.executemany(
                "INSERT INTO agent_task_search_grams(task_id, gram) VALUES (?, ?)",
                ((task_id, gram) for gram in added_grams),
            )
        con.execute(
            "INSERT OR REPLACE INTO agent_task_search_index_state "
            "(task_id, source_digest, fields_digest, grams_digest, grams_count) VALUES (?, ?, ?, ?, ?)",
            (
                task_id,
                source_digest,
                hashlib.sha256(fields_json.encode("utf-8")).hexdigest(),
                grams_digest,
                grams_count,
            ),
        )

    @classmethod
    def _backfill_task_search_index(cls, con: sqlite3.Connection) -> None:
        con.execute(
            "CREATE TABLE IF NOT EXISTS agent_task_search_documents "
            "(task_id TEXT PRIMARY KEY, fields TEXT NOT NULL)"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS agent_task_search_grams "
            "(task_id TEXT NOT NULL, gram TEXT NOT NULL, PRIMARY KEY(task_id, gram))"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS agent_task_search_index_state "
            "(task_id TEXT PRIMARY KEY, source_digest TEXT NOT NULL, fields_digest TEXT NOT NULL, "
            "grams_digest TEXT NOT NULL, grams_count INTEGER NOT NULL)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_task_search_grams_gram "
            "ON agent_task_search_grams(gram, task_id)"
        )
        rows = con.execute(
            "SELECT task_id, owner, contract, context, checkpoint FROM agent_tasks_projection"
        ).fetchall()
        for task_id, owner, contract_raw, context_raw, checkpoint_raw in rows:
            source_digest = cls._task_search_source_digest(
                str(task_id), owner, contract_raw, context_raw, checkpoint_raw
            )
            document = con.execute(
                "SELECT fields FROM agent_task_search_documents WHERE task_id = ?", (task_id,)
            ).fetchone()
            index_state = con.execute(
                "SELECT source_digest, fields_digest, grams_digest, grams_count "
                "FROM agent_task_search_index_state WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if document is not None and index_state is not None and index_state[0] == source_digest:
                stored_fields = str(document[0] or "")
                fields_digest = hashlib.sha256(stored_fields.encode("utf-8")).hexdigest()
                if fields_digest == index_state[1]:
                    grams_digest, grams_count = cls._task_search_gram_digest(
                        con.execute(
                            "SELECT gram FROM agent_task_search_grams WHERE task_id = ? ORDER BY gram",
                            (task_id,),
                        )
                    )
                    if grams_digest == index_state[2] and grams_count == int(index_state[3]):
                        continue
            contract = json.loads(contract_raw or "{}")
            context = json.loads(context_raw or "{}")
            checkpoint = json.loads(checkpoint_raw or "{}")
            fields = cls._searchable_task_fields(task_id, contract, checkpoint, context, owner)
            cls._write_task_search_index(con, task_id, fields, source_digest)
        con.execute(
            "DELETE FROM agent_task_search_documents WHERE task_id NOT IN "
            "(SELECT task_id FROM agent_tasks_projection)"
        )
        con.execute(
            "DELETE FROM agent_task_search_grams WHERE task_id NOT IN "
            "(SELECT task_id FROM agent_tasks_projection)"
        )
        con.execute(
            "DELETE FROM agent_task_search_index_state WHERE task_id NOT IN "
            "(SELECT task_id FROM agent_tasks_projection)"
        )

    @classmethod
    def _refresh_task_search_index(cls, con: sqlite3.Connection, task_id: str) -> None:
        row = con.execute(
            "SELECT owner, contract, context, checkpoint FROM agent_tasks_projection WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            con.execute("DELETE FROM agent_task_search_documents WHERE task_id = ?", (task_id,))
            con.execute("DELETE FROM agent_task_search_grams WHERE task_id = ?", (task_id,))
            con.execute("DELETE FROM agent_task_search_index_state WHERE task_id = ?", (task_id,))
            return
        owner = row[0]
        source_digest = cls._task_search_source_digest(task_id, owner, *row[1:])
        contract, context, checkpoint = (json.loads(value or "{}") for value in row[1:])
        fields = cls._searchable_task_fields(task_id, contract, checkpoint, context, owner)
        cls._write_task_search_index(con, task_id, fields, source_digest)

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        limit: int = 100,
        include_stale: bool = False,
        query: str | None = None,
        *,
        offset: int = 0,
        repo_root: str | None = None,
    ) -> TaskPage:
        if not self._db_path_available():
            return TaskPage()
        self._init_projection_table()
        canonical_root: str | None = None
        canonical_project_id: str | None = None
        canonical_worktree_id: str | None = None
        canonical_snapshot_id: str | None = None
        if repo_root is not None:
            try:
                canonical_root = _canonical_repository_root(repo_root)
                canonical_project_id = project_scope_id(canonical_root)
                canonical_worktree_id = worktree_scope_id(canonical_root)
                canonical_snapshot_id = repository_snapshot_id(canonical_root)
            except ValueError:
                return TaskPage()
            project_dir = Path(canonical_root) / ".local-ai-hub"
            if (project_dir / "project.json").is_file() and (project_dir / "agent-os").is_dir():
                from .repo_agent_state import ensure_agent_state_projection_current

                projection = ensure_agent_state_projection_current(
                    canonical_root, Path(self.state_store.db_path).parent,
                )
                if projection.get("success") is not True:
                    raise RuntimeError(projection.get("error", "Agent OS projection refresh failed"))
        now = time.time()
        normalized_query = self._normalize_search_text(query or "")
        query_terms = [term for term in normalized_query.split() if term]
        page_size = max(1, int(limit))
        page_offset = max(0, int(offset))

        def matches_query(row: tuple[Any, ...]) -> bool:
            contract_data = json.loads(row[4] or "{}")
            context_data = json.loads(row[5] or "{}")
            checkpoint_data = json.loads(row[6] or "{}")
            fields = self._searchable_task_fields(
                row[0], contract_data, checkpoint_data, context_data, row[2]
            )
            normalized_fields = tuple(self._normalize_search_text(value) for value in fields)
            return all(any(term in value for value in normalized_fields) for term in query_terms)

        def _fetch_tasks() -> tuple[list[Any], bool]:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                where_clauses: list[str] = []
                params: list[Any] = []
                if status is not None:
                    where_clauses.append("status = ?")
                    params.append(status.value)
                if canonical_root is not None:
                    where_clauses.append(
                        "json_type(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.version') = 'integer' "
                        "AND json_extract(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.version') = 4 "
                        "AND json_extract(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.project_id') = ? "
                        "AND (owner='canonical-git' OR json_extract(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.worktree_id') = ?) "
                        "AND json_extract(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.snapshot_id') = ?"
                    )
                    params.extend((canonical_project_id, canonical_worktree_id, canonical_snapshot_id))
                if not query_terms and not include_stale:
                    where_clauses.append(
                        "(status IN ('completed', 'cancelled', 'failed', 'abandoned') "
                        "OR NOT (heartbeat_expires_at > 0 AND heartbeat_expires_at < ?))"
                    )
                    params.append(now)
                scan_where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                scan_params = list(params)
                query_grams = sorted(self._search_grams(query_terms))
                if query_grams:
                    placeholders = ", ".join("?" for _ in query_grams)
                    where_clauses.append(
                        "task_id IN (SELECT task_id FROM agent_task_search_grams "
                        f"WHERE gram IN ({placeholders}) GROUP BY task_id "
                        "HAVING COUNT(DISTINCT gram) = ?)"
                    )
                    params.extend(query_grams)
                    params.append(len(query_grams))
                where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                sql = f"""
                    SELECT task_id, status, owner, lease_id, contract, context, checkpoint, receipts,
                           heartbeat_expires_at, created_at, updated_at
                    FROM agent_tasks_projection
                    {where_sql}
                    ORDER BY updated_at DESC, task_id DESC
                """
                if not query_terms:
                    cur = con.execute(sql + " LIMIT ? OFFSET ?", (*params, page_size, page_offset))
                    return cur.fetchall(), False

                scan_count = con.execute(
                    f"SELECT COUNT(1) FROM agent_tasks_projection {scan_where_sql}", scan_params
                ).fetchone()
                cur = con.execute(sql + " LIMIT ?", (*params, MAX_TASK_QUERY_SCAN_ROWS + 1))
                candidates = cur.fetchmany(MAX_TASK_QUERY_SCAN_ROWS + 1)
                query_truncated = (
                    len(candidates) > MAX_TASK_QUERY_SCAN_ROWS
                    or bool(scan_count and int(scan_count[0]) > MAX_TASK_QUERY_SCAN_ROWS)
                )
                matched: list[Any] = []
                terminal_statuses = {
                    TaskStatus.COMPLETED.value,
                    TaskStatus.CANCELLED.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.ABANDONED.value,
                }
                skipped = 0
                for row in candidates[:MAX_TASK_QUERY_SCAN_ROWS]:
                    heartbeat_expires_at = float(row[8] or 0.0)
                    if (
                        not include_stale
                        and heartbeat_expires_at > 0
                        and heartbeat_expires_at < now
                        and row[1] not in terminal_statuses
                    ):
                        continue
                    if matches_query(row):
                        if skipped < page_offset:
                            skipped += 1
                            continue
                        matched.append(row)
                        if len(matched) >= page_size:
                            return matched, False
                return matched, query_truncated

        rows, query_truncated = retry_busy(_fetch_tasks, retries=5, base_delay_seconds=0.02)
        tasks = [self._row_to_state(row) for row in rows]
        return TaskPage(tuple(tasks[:page_size]), query_truncated=query_truncated)

    def count(self, status: TaskStatus | None = None, *, include_stale: bool = True, repo_root: str | None = None) -> int:
        if not self._db_path_available():
            return 0
        self._init_projection_table()
        canonical_root: str | None = None
        canonical_project_id: str | None = None
        canonical_worktree_id: str | None = None
        canonical_snapshot_id: str | None = None
        if repo_root is not None:
            try:
                canonical_root = _canonical_repository_root(repo_root)
                canonical_project_id = project_scope_id(canonical_root)
                canonical_worktree_id = worktree_scope_id(canonical_root)
                canonical_snapshot_id = repository_snapshot_id(canonical_root)
            except ValueError:
                return 0
            project_dir = Path(canonical_root) / ".local-ai-hub"
            if (project_dir / "project.json").is_file() and (project_dir / "agent-os").is_dir():
                from .repo_agent_state import ensure_agent_state_projection_current

                projection = ensure_agent_state_projection_current(
                    canonical_root, Path(self.state_store.db_path).parent,
                )
                if projection.get("success") is not True:
                    raise RuntimeError(projection.get("error", "Agent OS projection refresh failed"))
        def _fetch_count() -> int:
            with closing(connect_sqlite(self.state_store.db_path)) as con:
                where_clauses = []
                params = []
                if status is not None:
                    where_clauses.append("status = ?")
                    params.append(status.value)
                if canonical_root is not None:
                    where_clauses.append(
                        "json_type(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.version') = 'integer' "
                        "AND json_extract(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.version') = 4 "
                        "AND json_extract(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.project_id') = ? "
                        "AND (owner='canonical-git' OR json_extract(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.worktree_id') = ?) "
                        "AND json_extract(CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END, '$.state_data._agent_task_scope.snapshot_id') = ?"
                    )
                    params.extend((canonical_project_id, canonical_worktree_id, canonical_snapshot_id))
                if not include_stale:
                    where_clauses.append(
                        "(status IN ('completed', 'cancelled', 'failed', 'abandoned') "
                        "OR NOT (heartbeat_expires_at > 0 AND heartbeat_expires_at < ?))"
                    )
                    params.append(time.time())
                where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                row = con.execute(
                    f"SELECT COUNT(1) FROM agent_tasks_projection{where_sql}", params
                ).fetchone()
                return int(row[0]) if row else 0

        return retry_busy(_fetch_count, retries=5, base_delay_seconds=0.02)

    def get_active_task(
        self,
        repo_root: str | None = None,
    ) -> TaskState | None:
        """Find the most recently updated active/planned task matching the declared repository scope."""
        if not self._db_path_available():
            return None
        target_root = self._canonical_memory_root(repo_root) if repo_root else ""
        def _matches(task: TaskState) -> bool:
            if task.is_stale or task.is_terminal():
                return False
            if target_root and not _task_matches_scope(task, target_root):
                return False
            return True

        for st in (TaskStatus.ACTIVE, TaskStatus.VERIFYING, TaskStatus.PLANNED):
            tasks = self.list_tasks(status=st, limit=20, include_stale=False, repo_root=repo_root)
            for t in tasks.tasks:
                if _matches(t):
                    return t
        return None

