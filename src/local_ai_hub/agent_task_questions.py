from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import time
from typing import Any
import uuid

from .agent_events import AgentEvent
from .agent_task_models import (
    MAX_AGENT_QUESTION_BYTES,
    CheckpointResponseBudgetError,
    _canonical_repository_root,
)
from .sqlite_support import connect_sqlite, retry_busy, write_transaction
from .task_memory_wire import mcp_wire_tokens


TaskStore = None


class TaskQuestionMixin:
    def _db_path_available(self) -> bool:
        """Return whether the projection database path is usable.

        AgentStateStore intentionally creates its database lazily in _ensure_schema().
        Requiring the file to exist here creates a bootstrap cycle on clean installs:
        the projection refuses to initialize because the file is absent, while the
        state store is never asked to create it.  Validate the path object instead
        and let _ensure_schema() create the parent/database atomically.
        """
        if not self.state_store.enabled:
            return False
        try:
            path = Path(self.state_store.db_path)
            return bool(path.name)
        except (RecursionError, OSError, ValueError, TypeError):
            return False

    def _init_projection_table(self) -> None:
        if self._initialized or not self._db_path_available():
            return
        with self._lock:
            if self._initialized or not self._db_path_available():
                return
            self.state_store._ensure_schema()
            def _setup() -> None:
                with closing(connect_sqlite(self.state_store.db_path)) as con:
                    from .sqlite_support import validate_durable_schema

                    validate_durable_schema(
                        con,
                        self.state_store.db_path,
                        {
                            "agent_tasks_projection": [
                                ("task_id", "TEXT", 0, 1), ("status", "TEXT", 1, 0),
                                ("owner", "TEXT", 1, 0), ("lease_id", "TEXT", 1, 0),
                                ("contract", "TEXT", 1, 0), ("context", "TEXT", 1, 0),
                                ("checkpoint", "TEXT", 1, 0), ("receipts", "TEXT", 1, 0),
                                ("heartbeat_expires_at", "REAL", 1, 0),
                                ("created_at", "REAL", 1, 0), ("updated_at", "REAL", 1, 0),
                            ],
                            "agent_questions": [
                                ("question_id", "TEXT", 0, 1),
                                ("root", "TEXT", 1, 0),
                                ("session_id", "TEXT", 1, 0), ("task_id", "TEXT", 1, 0),
                                ("question", "TEXT", 1, 0), ("answer", "TEXT", 1, 0),
                                ("status", "TEXT", 1, 0), ("asked_by", "TEXT", 1, 0),
                                ("answered_by", "TEXT", 1, 0),
                                ("created_at", "REAL", 1, 0), ("answered_at", "REAL", 0, 0),
                            ],
                        },
                        required_if_event_kinds={"agent_tasks_projection": ("task.%",)},
                    )
                    if con.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'agent_tasks_projection'"
                    ).fetchone() is not None:
                        document = "CASE WHEN json_valid(checkpoint) THEN checkpoint ELSE '{}' END"
                        invalid_contracts = ["NOT json_valid(checkpoint)"]
                        for path in ("$.state_data._agent_task_scope", "$.state_data.memory_context"):
                            checks = [
                                f"json_type({document}, '{path}') != 'object'",
                                f"COALESCE(json_type({document}, '{path}.{'version' if path.endswith('_agent_task_scope') else 'schema_version'}'), '') != 'integer'",
                                f"COALESCE(json_extract({document}, '{path}.{'version' if path.endswith('_agent_task_scope') else 'schema_version'}'), 0) != 2",
                                f"json_type({document}, '{path}.tenant') IS NOT NULL",
                                f"json_type({document}, '{path}.tenant_key') IS NOT NULL",
                            ]
                            if path.endswith("memory_context"):
                                checks.extend([
                                    f"COALESCE(json_type({document}, '{path}.context'), '') != 'object'",
                                    f"json_type({document}, '{path}.context.tenant') IS NOT NULL",
                                    f"json_type({document}, '{path}.context.tenant_key') IS NOT NULL",
                                ])
                            invalid_contracts.append(
                                f"(json_type({document}, '{path}') IS NOT NULL "
                                f"AND json_type({document}, '{path}') != 'null' AND ({' OR '.join(checks)}))"
                            )
                        invalid = con.execute(
                            "SELECT 1 FROM agent_tasks_projection WHERE " + " OR ".join(invalid_contracts) + " LIMIT 1"
                        ).fetchone()
                        if invalid is not None:
                            raise RuntimeError("retired task checkpoint contract requires explicit offline conversion")
                    con.execute(
                        """
                        CREATE TABLE IF NOT EXISTS agent_tasks_projection (
                            task_id TEXT PRIMARY KEY,
                            status TEXT NOT NULL,
                            owner TEXT NOT NULL,
                            lease_id TEXT NOT NULL,
                            contract TEXT NOT NULL,
                            context TEXT NOT NULL,
                            checkpoint TEXT NOT NULL,
                            receipts TEXT NOT NULL,
                            heartbeat_expires_at REAL NOT NULL,
                            created_at REAL NOT NULL,
                            updated_at REAL NOT NULL
                        );
                        """
                    )
                    con.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_agent_tasks_status
                        ON agent_tasks_projection (status, heartbeat_expires_at);
                        """
                    )
                    con.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_agent_tasks_updated
                        ON agent_tasks_projection (updated_at DESC);
                        """
                    )
                    con.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_agent_tasks_status_updated
                        ON agent_tasks_projection (status, updated_at DESC);
                        """
                    )
                    con.execute(
                        """
                        CREATE TABLE IF NOT EXISTS agent_questions (
                            question_id TEXT PRIMARY KEY,
                            root TEXT NOT NULL,
                            session_id TEXT NOT NULL,
                            task_id TEXT NOT NULL DEFAULT '',
                            question TEXT NOT NULL,
                            answer TEXT NOT NULL DEFAULT '',
                            status TEXT NOT NULL,
                            asked_by TEXT NOT NULL,
                            answered_by TEXT NOT NULL DEFAULT '',
                            created_at REAL NOT NULL,
                            answered_at REAL
                        );
                        """
                    )
                    con.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_agent_questions_session
                        ON agent_questions (root, session_id, created_at DESC);
                        """
                    )
                    self._backfill_task_search_index(con)
                    con.commit()
            with self.state_store._schema_init_lock:
                retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    @staticmethod
    def _question_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        names = (
            "question_id", "root", "session_id", "task_id", "question",
            "answer", "status", "asked_by", "answered_by", "created_at", "answered_at",
        )
        if len(row) != len(names):
            raise ValueError("unsupported question row contract")
        result = dict(zip(names, row))
        result.pop("root", None)
        return result

    @staticmethod
    def _validate_question_text(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ValueError(f"{label} must be a non-empty string without null bytes")
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError(f"{label} must contain valid UTF-8 text") from exc
        if len(encoded) > MAX_AGENT_QUESTION_BYTES:
            raise ValueError(f"{label} exceeds {MAX_AGENT_QUESTION_BYTES} UTF-8 bytes")
        return value.strip()

    @staticmethod
    def _validate_question_scope(root: Any, session_id: Any) -> tuple[str, str]:
        if any(not isinstance(value, str) or not value or value != value.strip() or "\x00" in value for value in (root, session_id)):
            raise ValueError("canonical root and session_id are required for agent questions")
        if len(session_id.encode("utf-8")) > 256:
            raise ValueError("session_id exceeds 256 UTF-8 bytes")
        return _canonical_repository_root(root), session_id

    @staticmethod
    def _validate_question_response_budget(response_budget_tokens: int | None) -> None:
        if response_budget_tokens is None:
            return
        if (
            isinstance(response_budget_tokens, bool)
            or not isinstance(response_budget_tokens, int)
            or response_budget_tokens < 1
        ):
            raise ValueError("response_budget_tokens must be a positive integer")

    @staticmethod
    def _preflight_question_response(
        question: dict[str, Any], response_budget_tokens: int | None,
    ) -> None:
        TaskStore._validate_question_response_budget(response_budget_tokens)
        if response_budget_tokens is None:
            return
        payload = TaskStore._include_current_request_id({"success": True, "question": question})
        required_tokens = mcp_wire_tokens(payload, text_payload=payload)
        if required_tokens > response_budget_tokens:
            raise CheckpointResponseBudgetError(response_budget_tokens, required_tokens)

    def ask_question(
        self,
        *,
        root: str,
        session_id: str,
        question: str = "",
        task_id: str = "",
        actor: str = "agent",
        question_id: str = "",
        response_budget_tokens: int | None = None,
    ) -> dict[str, Any] | None:
        """Persist a session-bound question or retrieve it within the same scope."""
        if not self._db_path_available():
            raise RuntimeError("agent question storage is unavailable")
        root_value, session_value = self._validate_question_scope(
            root, session_id
        )
        self._validate_question_response_budget(response_budget_tokens)
        if not isinstance(question_id, str) or question_id != question_id.strip() or "\x00" in question_id:
            raise ValueError("question_id must be a canonical string")
        if not isinstance(task_id, str) or task_id != task_id.strip() or "\x00" in task_id:
            raise ValueError("task_id must be a canonical string")
        question_key, task_value = question_id, task_id
        if len(question_key) > 80:
            raise ValueError("question_id exceeds 80 characters")
        if question_key:
            self._init_projection_table()
            def _read() -> dict[str, Any] | None:
                with closing(connect_sqlite(self.state_store.db_path)) as con:
                    row = con.execute(
                        """
                        SELECT question_id, root, session_id, task_id, question,
                               answer, status, asked_by, answered_by, created_at, answered_at
                        FROM agent_questions
                        WHERE question_id = ? AND root = ? AND session_id = ?
                        """,
                        (question_key, root_value, session_value),
                    ).fetchone()
                if row is None:
                    return None
                question_record = self._question_row_to_dict(row)
                return question_record if not task_value or question_record["task_id"] == task_value else None

            result = retry_busy(_read, retries=5, base_delay_seconds=0.02)
            if result is not None:
                self._preflight_question_response(result, response_budget_tokens)
            return result

        question_value = self._validate_question_text(question, "question")
        actor_value = str(actor or "agent").strip() or "agent"
        question_key = f"q_{uuid.uuid4().hex}"
        created_at = time.time()
        projected_question = {
            "question_id": question_key,
            "session_id": session_value,
            "task_id": task_value,
            "question": question_value,
            "answer": "",
            "status": "pending",
            "asked_by": actor_value,
            "answered_by": "",
            "created_at": created_at,
            "answered_at": None,
        }
        self._preflight_question_response(projected_question, response_budget_tokens)
        self._init_projection_table()

        def _write(con: sqlite3.Connection) -> tuple[dict[str, Any], list[AgentEvent]]:
            with write_transaction(con, rollback_label="agent task question"):
                con.execute(
                    """
                    INSERT INTO agent_questions (
                        question_id, root, session_id, task_id, question, answer,
                        status, asked_by, answered_by, created_at, answered_at
                    ) VALUES (?, ?, ?, ?, ?, '', 'pending', ?, '', ?, NULL)
                    """,
                    (
                        question_key, root_value, session_value, task_value,
                        question_value, actor_value, created_at,
                    ),
                )
            return projected_question, []

        return self._run_ordered_task_write(_write)

    def answer_question(
        self,
        *,
        question_id: str,
        root: str,
        answer: str,
        task_id: str = "",
        actor: str = "operator",
        response_budget_tokens: int | None = None,
    ) -> dict[str, Any] | None:
        """Record an answer in the authorized repository; retain the stored session."""
        if not self._db_path_available():
            raise RuntimeError("agent question storage is unavailable")
        if any(not isinstance(value, str) or value != value.strip() or "\x00" in value for value in (root, question_id, task_id)) or not root or not question_id:
            raise ValueError("canonical question_id and root are required")
        root_value = _canonical_repository_root(root)
        question_key, task_value = question_id, task_id
        if len(question_key) > 80:
            raise ValueError("question_id exceeds 80 characters")
        self._validate_question_response_budget(response_budget_tokens)
        answer_value = self._validate_question_text(answer, "answer")
        actor_value = str(actor or "operator").strip() or "operator"
        answered_at = time.time()
        self._init_projection_table()

        def _write(con: sqlite3.Connection) -> tuple[dict[str, Any] | None, list[AgentEvent]]:
            with write_transaction(con, rollback_label="agent task question"):
                row = con.execute(
                    """
                    SELECT question_id, root, session_id, task_id, question,
                           answer, status, asked_by, answered_by, created_at, answered_at
                    FROM agent_questions
                    WHERE question_id = ? AND root = ?
                    """,
                    (question_key, root_value),
                ).fetchone()
                if row is None:
                    return None, []
                current = self._question_row_to_dict(row)
                if task_value and current["task_id"] != task_value:
                    return None, []
                if current["status"] not in {"pending", "answered"}:
                    raise ValueError("unsupported question status")
                if current["status"] == "answered":
                    if current["answer"] == answer_value:
                        self._preflight_question_response(current, response_budget_tokens)
                        return current, []
                    raise ValueError("question has already been answered")
                projected_question = {
                    **current,
                    "answer": answer_value,
                    "status": "answered",
                    "answered_by": actor_value,
                    "answered_at": answered_at,
                }
                self._preflight_question_response(projected_question, response_budget_tokens)
                con.execute(
                    """
                    UPDATE agent_questions
                    SET answer = ?, status = 'answered', answered_by = ?, answered_at = ?
                    WHERE question_id = ? AND root = ? AND status = 'pending'
                    """,
                    (answer_value, actor_value, answered_at, question_key, root_value),
                )
                updated_row = con.execute(
                    """
                    SELECT question_id, root, session_id, task_id, question,
                           answer, status, asked_by, answered_by, created_at, answered_at
                    FROM agent_questions
                    WHERE question_id = ? AND root = ?
                    """,
                    (question_key, root_value),
                ).fetchone()
            return self._question_row_to_dict(updated_row), []

        return self._run_ordered_task_write(_write)

