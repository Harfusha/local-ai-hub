from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error, retry_busy


@dataclass(frozen=True)
class AgentEvent:
    event_id: str
    stream_id: str
    kind: str
    payload: Mapping[str, Any]
    idempotency_key: str
    correlation_id: str
    actor: str
    schema_version: int
    created_at: float
    seq: int | None = None

    @classmethod
    def create(
        cls,
        stream_id: str,
        kind: str,
        payload: Mapping[str, Any] | None = None,
        idempotency_key: str = "",
        actor: str = "agent",
        correlation_id: str = "",
        schema_version: int = 1,
        created_at: float | None = None,
    ) -> AgentEvent:
        return cls(
            event_id=f"evt_{uuid.uuid4().hex[:16]}",
            stream_id=stream_id,
            kind=kind,
            payload=dict(payload or {}),
            idempotency_key=idempotency_key or f"idemp_{uuid.uuid4().hex[:12]}",
            correlation_id=correlation_id,
            actor=actor,
            schema_version=schema_version,
            created_at=time.time() if created_at is None else float(created_at),
            seq=None,
        )

    def with_seq(self, seq: int) -> AgentEvent:
        return AgentEvent(
            event_id=self.event_id,
            stream_id=self.stream_id,
            kind=self.kind,
            payload=self.payload,
            idempotency_key=self.idempotency_key,
            correlation_id=self.correlation_id,
            actor=self.actor,
            schema_version=self.schema_version,
            created_at=self.created_at,
            seq=int(seq),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "stream_id": self.stream_id,
            "kind": self.kind,
            "payload": dict(self.payload),
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "actor": self.actor,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "seq": self.seq,
        }

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> AgentEvent:
        stream_id, seq, event_id, kind, payload_raw, idempotency_key, correlation_id, actor, schema_version, created_at = row
        payload = json.loads(payload_raw) if isinstance(payload_raw, str) else dict(payload_raw)
        return cls(
            event_id=event_id,
            stream_id=stream_id,
            kind=kind,
            payload=payload,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            actor=actor,
            schema_version=schema_version,
            created_at=created_at,
            seq=seq,
        )


@dataclass(frozen=True)
class AppendResult:
    seq: int
    duplicate: bool
    event: AgentEvent | None = None
    retryable: bool = False
    error: str | None = None


SCHEMA_VERSION = 1

MIGRATIONS = [
    (
        1,
        "initial agent events, snapshots, and migrations schema",
        """
        CREATE TABLE IF NOT EXISTS agent_schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL,
            description TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_events (
            stream_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (stream_id, seq),
            UNIQUE (stream_id, idempotency_key)
        );

        CREATE INDEX IF NOT EXISTS idx_agent_events_created
            ON agent_events (created_at);

        CREATE INDEX IF NOT EXISTS idx_agent_events_kind
            ON agent_events (kind);

        CREATE TABLE IF NOT EXISTS agent_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            state TEXT NOT NULL,
            created_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_agent_snapshots_stream
            ON agent_snapshots (stream_id, seq DESC);
        """,
    )
]


class AgentStateStore:
    def __init__(
        self,
        db_path: Path | str,
        *,
        enabled: bool = True,
        max_payload_bytes: int = 65536,
    ) -> None:
        self.db_path = Path(db_path)
        self.enabled = bool(enabled)
        self.max_payload_bytes = int(max_payload_bytes)
        self._initialized = False

    def _ensure_schema(self) -> None:
        if self._initialized or not self.enabled:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = connect_sqlite(self.db_path)
        try:
            initialize_wal(con)
            con.execute("BEGIN IMMEDIATE")
            for version, description, ddl in MIGRATIONS:
                applied = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_schema_migrations'"
                ).fetchone()
                if applied:
                    row = con.execute(
                        "SELECT version FROM agent_schema_migrations WHERE version = ?",
                        (version,),
                    ).fetchone()
                    if row:
                        continue
                con.executescript(ddl)
                con.execute(
                    "INSERT INTO agent_schema_migrations (version, applied_at, description) VALUES (?, ?, ?)",
                    (version, time.time(), description),
                )
            con.commit()
            self._initialized = True
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def append(self, event: AgentEvent) -> AppendResult:
        if not self.enabled:
            return AppendResult(seq=0, duplicate=False, error="agent_state is disabled")

        payload_bytes = json.dumps(event.payload, separators=(",", ":")).encode("utf-8")
        if len(payload_bytes) > self.max_payload_bytes:
            raise ValueError(
                f"payload exceeds maximum allowed {self.max_payload_bytes} bytes (got {len(payload_bytes)})"
            )

        self._ensure_schema()

        def _do_append() -> AppendResult:
            con = connect_sqlite(self.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                existing = con.execute(
                    """
                    SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, schema_version, created_at
                    FROM agent_events
                    WHERE stream_id = ? AND idempotency_key = ?
                    """,
                    (event.stream_id, event.idempotency_key),
                ).fetchone()
                if existing:
                    con.execute("COMMIT")
                    existing_ev = AgentEvent.from_row(existing)
                    return AppendResult(seq=existing_ev.seq or 0, duplicate=True, event=existing_ev)

                row = con.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM agent_events WHERE stream_id = ?",
                    (event.stream_id,),
                ).fetchone()
                new_seq = int(row[0]) if row else 1

                con.execute(
                    """
                    INSERT INTO agent_events (
                        stream_id, seq, event_id, kind, payload, idempotency_key,
                        correlation_id, actor, schema_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.stream_id,
                        new_seq,
                        event.event_id,
                        event.kind,
                        payload_bytes.decode("utf-8"),
                        event.idempotency_key,
                        event.correlation_id,
                        event.actor,
                        event.schema_version,
                        event.created_at,
                    ),
                )
                con.execute("COMMIT")
                persisted = event.with_seq(new_seq)
                return AppendResult(seq=new_seq, duplicate=False, event=persisted)
            except Exception as exc:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                if is_busy_error(exc):
                    raise
                return AppendResult(seq=0, duplicate=False, error=str(exc))
            finally:
                con.close()

        try:
            return retry_busy(_do_append, retries=5, base_delay_seconds=0.02)
        except Exception as exc:
            if is_busy_error(exc):
                return AppendResult(seq=0, duplicate=False, retryable=True, error=str(exc))
            raise

    def events(self, stream_id: str, after_seq: int = 0, limit: int = 1000) -> list[AgentEvent]:
        if not self.enabled or not self.db_path.exists():
            return []
        self._ensure_schema()
        con = connect_sqlite(self.db_path)
        try:
            cur = con.execute(
                """
                SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, schema_version, created_at
                FROM agent_events
                WHERE stream_id = ? AND seq > ?
                ORDER BY seq ASC
                LIMIT ?
                """,
                (stream_id, int(after_seq), max(1, int(limit))),
            )
            return [AgentEvent.from_row(row) for row in cur.fetchall()]
        finally:
            con.close()

    def snapshot(self, stream_id: str, state: Mapping[str, Any], seq: int | None = None) -> int:
        if not self.enabled:
            return 0
        self._ensure_schema()
        raw_state = json.dumps(state, separators=(",", ":"))

        def _do_snapshot() -> int:
            con = connect_sqlite(self.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                target_seq = seq
                if target_seq is None:
                    row = con.execute(
                        "SELECT COALESCE(MAX(seq), 0) FROM agent_events WHERE stream_id = ?",
                        (stream_id,),
                    ).fetchone()
                    target_seq = int(row[0]) if row else 0

                cur = con.execute(
                    """
                    INSERT INTO agent_snapshots (stream_id, seq, state, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (stream_id, target_seq, raw_state, time.time()),
                )
                snap_id = cur.lastrowid or 0
                con.execute("COMMIT")
                return snap_id
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()

        return retry_busy(_do_snapshot, retries=5, base_delay_seconds=0.02)

    def latest_snapshot(self, stream_id: str) -> dict[str, Any] | None:
        if not self.enabled or not self.db_path.exists():
            return None
        self._ensure_schema()
        con = connect_sqlite(self.db_path)
        try:
            row = con.execute(
                """
                SELECT snapshot_id, seq, state, created_at
                FROM agent_snapshots
                WHERE stream_id = ?
                ORDER BY seq DESC, snapshot_id DESC
                LIMIT 1
                """,
                (stream_id,),
            ).fetchone()
            if not row:
                return None
            snap_id, seq, raw_state, created_at = row
            return {
                "snapshot_id": snap_id,
                "seq": seq,
                "state": json.loads(raw_state),
                "created_at": created_at,
            }
        finally:
            con.close()
