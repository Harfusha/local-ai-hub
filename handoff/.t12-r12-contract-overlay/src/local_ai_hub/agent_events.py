from __future__ import annotations

from .json_utils import dumps as json_dumps

from contextlib import contextmanager
import json
import os
import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

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
            "created_at": self.created_at,
            "seq": self.seq,
        }

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> AgentEvent:
        stream_id, seq, event_id, kind, payload_raw, idempotency_key, correlation_id, actor, created_at = row
        payload = json.loads(payload_raw) if isinstance(payload_raw, str) else dict(payload_raw)
        return cls(
            event_id=event_id,
            stream_id=stream_id,
            kind=kind,
            payload=payload,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            actor=actor,
            created_at=created_at,
            seq=seq,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AgentEvent:
        return cls(
            event_id=str(data.get("event_id") or f"evt_{uuid.uuid4().hex[:16]}"),
            stream_id=str(data.get("stream_id", "")),
            kind=str(data.get("kind", "")),
            payload=dict(data.get("payload") or {}),
            idempotency_key=str(data.get("idempotency_key") or f"idemp_{uuid.uuid4().hex[:12]}"),
            correlation_id=str(data.get("correlation_id", "")),
            actor=str(data.get("actor", "agent")),
            created_at=float(data.get("created_at") or time.time()),
            seq=int(data["seq"]) if data.get("seq") is not None else None,
        )


@dataclass(frozen=True)
class AppendResult:
    seq: int
    duplicate: bool
    event: AgentEvent | None = None
    retryable: bool = False
    error: str | None = None



class AgentStateStore:
    _append_publish_locks_guard = threading.Lock()
    _append_publish_locks: dict[str, threading.Lock] = {}
    _SCHEMA_VERSION = 1

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
        lock_key = os.path.normcase(str(self.db_path.resolve()))
        with self._append_publish_locks_guard:
            self._append_publish_lock = self._append_publish_locks.setdefault(
                lock_key, threading.Lock()
            )
        self._lock = threading.RLock()
        self._initialized = False
        self._subscribers: list[queue.Queue[AgentEvent]] = []
        self._subscribers_lock = threading.Lock()
        self._dropped_event_count = 0
        self._drop_count_lock = threading.Lock()

    @property
    def dropped_event_count(self) -> int:
        with self._drop_count_lock:
            return self._dropped_event_count

    def _ensure_schema(self) -> None:
        if self._initialized or not self.enabled:
            return
        with self._lock:
            if self._initialized or not self.enabled:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            expected_events = [
                "stream_id", "seq", "event_id", "kind", "payload", "idempotency_key",
                "correlation_id", "actor", "created_at",
            ]
            expected_snapshots = ["snapshot_id", "stream_id", "seq", "state", "created_at"]
            expected_cursors = ["stream_id", "last_seq", "first_retained_seq"]

            def _setup() -> None:
                con = connect_sqlite(self.db_path)
                try:
                    version = int(con.execute("PRAGMA user_version").fetchone()[0])
                    if version < 0 or version > self._SCHEMA_VERSION:
                        raise RuntimeError(f"unsupported agent state schema version: {version}")
                    existing = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    current = True
                    if "agent_events" in existing:
                        current = [str(row[1]) for row in con.execute("PRAGMA table_info(agent_events)")] == expected_events
                    if current and "agent_snapshots" in existing:
                        current = [str(row[1]) for row in con.execute("PRAGMA table_info(agent_snapshots)")] == expected_snapshots
                    if "agent_event_cursors" in existing:
                        cursor_columns = [str(row[1]) for row in con.execute("PRAGMA table_info(agent_event_cursors)")]
                        if cursor_columns != expected_cursors:
                            raise RuntimeError("agent event cursor schema mismatch; refusing to alter durable database")
                    if not current or (version == self._SCHEMA_VERSION and not {"agent_events", "agent_snapshots"}.issubset(existing)):
                        raise RuntimeError(
                            "agent state schema mismatch; refusing to delete or recreate durable database"
                        )
                    if version == 0 and {"agent_events", "agent_snapshots"}.issubset(existing):
                        self._verified_migration_backup(con)
                    initialize_wal(con)
                    with con:
                        con.execute("""
                        CREATE TABLE IF NOT EXISTS agent_events (
                            stream_id TEXT NOT NULL,
                            seq INTEGER NOT NULL,
                            event_id TEXT NOT NULL,
                            kind TEXT NOT NULL,
                            payload TEXT NOT NULL,
                            idempotency_key TEXT NOT NULL,
                            correlation_id TEXT NOT NULL,
                            actor TEXT NOT NULL,
                            created_at REAL NOT NULL,
                            PRIMARY KEY (stream_id, seq),
                            UNIQUE (stream_id, idempotency_key)
                        );
                        """)
                        con.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_created ON agent_events (created_at)")
                        con.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_kind ON agent_events (kind)")
                        con.execute("""
                        CREATE TABLE IF NOT EXISTS agent_snapshots (
                            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                            stream_id TEXT NOT NULL,
                            seq INTEGER NOT NULL,
                            state TEXT NOT NULL,
                            created_at REAL NOT NULL
                        );
                        """)
                        con.execute("CREATE INDEX IF NOT EXISTS idx_agent_snapshots_stream ON agent_snapshots (stream_id, seq DESC)")
                        con.execute("""
                        CREATE TABLE IF NOT EXISTS agent_event_cursors (
                            stream_id TEXT PRIMARY KEY,
                            last_seq INTEGER NOT NULL,
                            first_retained_seq INTEGER NOT NULL
                        );
                        """)
                        if "agent_event_cursors" not in existing:
                            con.execute("""
                            INSERT INTO agent_event_cursors (stream_id, last_seq, first_retained_seq)
                            SELECT stream_id, MAX(seq), MIN(seq) FROM agent_events GROUP BY stream_id
                            """)
                        con.execute(f"PRAGMA user_version={self._SCHEMA_VERSION}")
                finally:
                    con.close()

            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    def _verified_migration_backup(self, source: sqlite3.Connection) -> Path:
        """Create and verify a snapshot before changing a legacy durable database."""
        backup_path = self.db_path.with_name(
            f"{self.db_path.name}.migration-v0-v1-{time.time_ns()}.bak"
        )
        with backup_path.open("xb"):
            pass
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
            quick_check = destination.execute("PRAGMA quick_check").fetchone()
            if not quick_check or str(quick_check[0]).lower() != "ok":
                raise sqlite3.DatabaseError("agent state migration backup failed quick_check")
            source_schema = source.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
            ).fetchall()
            backup_schema = destination.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
            ).fetchall()
            if source_schema != backup_schema:
                raise sqlite3.DatabaseError("agent state migration backup schema mismatch")
        except Exception:
            destination.close()
            backup_path.unlink(missing_ok=True)
            raise
        destination.close()
        return backup_path

    def append_in_transaction(
        self,
        con: Any,
        event: AgentEvent,
        *,
        strict_idempotency: bool = False,
    ) -> AppendResult:
        """Append event and advance durable sequence cursor in caller transaction."""
        if not self.enabled:
            raise RuntimeError("agent_state is disabled")
        if not bool(getattr(con, "in_transaction", False)):
            raise RuntimeError("append_in_transaction requires a caller-owned transaction")
        payload = json_dumps(event.payload, separators=(",", ":"))
        payload_bytes = payload.encode("utf-8")
        if len(payload_bytes) > self.max_payload_bytes:
            raise ValueError(
                f"payload exceeds maximum allowed {self.max_payload_bytes} bytes (got {len(payload_bytes)})"
            )
        existing = con.execute(
            """
            SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at
            FROM agent_events WHERE stream_id = ? AND idempotency_key = ?
            """,
            (event.stream_id, event.idempotency_key),
        ).fetchone()
        if existing:
            stored = AgentEvent.from_row(existing)
            if strict_idempotency and (
                stored.kind != event.kind
                or dict(stored.payload) != dict(event.payload)
                or stored.actor != event.actor
                or stored.correlation_id != event.correlation_id
            ):
                raise ValueError(
                    "idempotency key was already used for a different event payload"
                )
            bounds = con.execute(
                "SELECT MIN(seq), MAX(seq) FROM agent_events WHERE stream_id = ?",
                (event.stream_id,),
            ).fetchone()
            cursor = con.execute(
                "SELECT last_seq, first_retained_seq FROM agent_event_cursors WHERE stream_id = ?",
                (event.stream_id,),
            ).fetchone()
            retained = int(bounds[0]) if bounds and bounds[0] is not None else (stored.seq or 1)
            stream_high_water = int(bounds[1]) if bounds and bounds[1] is not None else 0
            high_water = max(
                int(cursor[0]) if cursor else 0,
                stream_high_water,
                int(stored.seq or 0),
            )
            first_retained = min(int(cursor[1]), retained) if cursor else retained
            con.execute(
                """
                INSERT INTO agent_event_cursors (stream_id, last_seq, first_retained_seq)
                VALUES (?, ?, ?)
                ON CONFLICT(stream_id) DO UPDATE SET
                    last_seq = MAX(agent_event_cursors.last_seq, excluded.last_seq),
                    first_retained_seq = MIN(agent_event_cursors.first_retained_seq, excluded.first_retained_seq)
                """,
                (event.stream_id, high_water, first_retained),
            )
            return AppendResult(seq=stored.seq or 0, duplicate=True, event=stored)

        cursor = con.execute(
            "SELECT last_seq, first_retained_seq FROM agent_event_cursors WHERE stream_id = ?",
            (event.stream_id,),
        ).fetchone()
        if cursor is None:
            bounds = con.execute(
                "SELECT MIN(seq), MAX(seq) FROM agent_events WHERE stream_id = ?",
                (event.stream_id,),
            ).fetchone()
            if bounds and bounds[1] is not None:
                last_seq = int(bounds[1])
                first_retained = int(bounds[0])
            else:
                last_seq = 0
                first_retained = 1
            con.execute(
                "INSERT INTO agent_event_cursors (stream_id, last_seq, first_retained_seq) VALUES (?, ?, ?)",
                (event.stream_id, last_seq, first_retained),
            )
        else:
            last_seq, first_retained = int(cursor[0]), int(cursor[1])

        new_seq = last_seq + 1
        if first_retained > last_seq:
            first_retained = new_seq
        persisted = event.with_seq(new_seq)
        con.execute(
            """
            INSERT INTO agent_events (
                stream_id, seq, event_id, kind, payload, idempotency_key,
                correlation_id, actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.stream_id,
                new_seq,
                event.event_id,
                event.kind,
                payload,
                event.idempotency_key,
                event.correlation_id,
                event.actor,
                event.created_at,
            ),
        )
        con.execute(
            "UPDATE agent_event_cursors SET last_seq = ?, first_retained_seq = ? WHERE stream_id = ?",
            (new_seq, first_retained, event.stream_id),
        )
        return AppendResult(seq=new_seq, duplicate=False, event=persisted)

    @contextmanager
    def ordered_event_publication(
        self, con: Any
    ) -> Iterator[Callable[[Sequence[AgentEvent]], None]]:
        """Serialize a caller-owned commit with publication to live subscribers.

        Enter before the caller starts its transaction. The caller retains ownership
        of BEGIN, COMMIT, and ROLLBACK; call the yielded publisher only after COMMIT.
        The publisher verifies committed rows before emitting any event. A rollback
        therefore cannot produce a live event, even if the caller mistakenly tries
        to publish its pending result.
        """
        if not self.enabled:
            raise RuntimeError("agent_state is disabled")
        if bool(getattr(con, "in_transaction", False)):
            raise RuntimeError(
                "ordered_event_publication must be entered before caller transaction begins"
            )
        with self._append_publish_lock:
            scope_active = True

            def publish_committed(events: Sequence[AgentEvent]) -> None:
                if not scope_active:
                    raise RuntimeError("ordered event publication scope is closed")
                if bool(getattr(con, "in_transaction", False)):
                    raise RuntimeError("caller transaction is still open")
                committed: list[AgentEvent] = []
                last_seq_by_stream: dict[str, int] = {}
                for event in events:
                    if event.seq is None:
                        raise RuntimeError("event is not committed")
                    prior_seq = last_seq_by_stream.get(event.stream_id)
                    if prior_seq is not None and event.seq <= prior_seq:
                        raise ValueError("committed events must be supplied in stream sequence order")
                    last_seq_by_stream[event.stream_id] = event.seq
                    row = con.execute(
                        """
                        SELECT stream_id, seq, event_id, kind, payload, idempotency_key,
                               correlation_id, actor, created_at
                        FROM agent_events
                        WHERE stream_id = ? AND seq = ? AND event_id = ?
                        """,
                        (event.stream_id, event.seq, event.event_id),
                    ).fetchone()
                    if row is None or AgentEvent.from_row(row) != event:
                        raise RuntimeError("event is not committed")
                    committed.append(event)
                for event in committed:
                    self._publish(event)

            try:
                yield publish_committed
            finally:
                scope_active = False

    def append(self, event: AgentEvent, *, strict_idempotency: bool = False) -> AppendResult:
        if not self.enabled:
            return AppendResult(seq=0, duplicate=False, error="agent_state is disabled")
        payload_bytes = json_dumps(event.payload, separators=(",", ":")).encode("utf-8")
        if len(payload_bytes) > self.max_payload_bytes:
            raise ValueError(
                f"payload exceeds maximum allowed {self.max_payload_bytes} bytes (got {len(payload_bytes)})"
            )
        self._ensure_schema()

        def _do_append() -> AppendResult:
            con = connect_sqlite(self.db_path, isolation_level=None, timeout_seconds=0.25)
            try:
                con.execute("BEGIN IMMEDIATE")
                result = self.append_in_transaction(
                    con, event, strict_idempotency=strict_idempotency
                )
                con.execute("COMMIT")
                return result
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
            with self._append_publish_lock:
                result = retry_busy(_do_append, retries=5, base_delay_seconds=0.02)
                if not result.duplicate and result.event is not None:
                    self._publish(result.event)
                return result
        except Exception as exc:
            if is_busy_error(exc):
                return AppendResult(seq=0, duplicate=False, retryable=True, error=str(exc))
            raise

    def subscribe(self, maxsize: int = 100) -> queue.Queue[AgentEvent]:
        q: queue.Queue[AgentEvent] = queue.Queue(maxsize=maxsize)
        with self._subscribers_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[AgentEvent]) -> None:
        with self._subscribers_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _publish(self, event: AgentEvent) -> None:
        with self._subscribers_lock:
            subscribers = list(self._subscribers)
        dead_queues: list[queue.Queue[AgentEvent]] = []
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                try:
                    q.get_nowait()
                except Exception:
                    pass
                else:
                    with self._drop_count_lock:
                        self._dropped_event_count += 1
                try:
                    q.put_nowait(event)
                except Exception:
                    dead_queues.append(q)
            except Exception:
                dead_queues.append(q)
        if dead_queues:
            with self._subscribers_lock:
                for q in dead_queues:
                    if q in self._subscribers:
                        self._subscribers.remove(q)

    def event_page(
        self,
        stream_id: str,
        after_seq: int = 0,
        limit: int = 1000,
        through_seq: int | None = None,
    ) -> dict[str, Any]:
        """Read a bounded sequence page and report replay gaps explicitly."""
        try:
            requested_after = max(0, int(after_seq))
        except (TypeError, ValueError, OverflowError):
            requested_after = 0
            return self._event_page_error(requested_after)
        try:
            page_limit = max(1, min(int(limit), 10000))
        except (TypeError, ValueError, OverflowError):
            return self._event_page_error(requested_after)
        try:
            requested_through = (
                None if through_seq is None else max(0, int(through_seq))
            )
        except (TypeError, ValueError, OverflowError):
            return self._event_page_error(requested_after)
        if not self.enabled:
            return {
                "success": False,
                "events": [],
                "next_seq": requested_after,
                "first_retained_seq": 0,
                "last_seq": 0,
                "has_more": False,
                "gap_ranges": [],
                "cursor_reset": False,
                "error": {
                    "code": "agent_state_disabled",
                    "message": "agent state is disabled",
                },
            }
        if not self.db_path.exists():
            return {
                "success": True,
                "events": [],
                "next_seq": requested_after,
                "first_retained_seq": 0,
                "last_seq": 0,
                "has_more": False,
                "gap_ranges": [],
                "cursor_reset": False,
            }
        con: sqlite3.Connection | None = None
        try:
            self._ensure_schema()
            con = connect_sqlite(self.db_path, isolation_level=None)
            con.execute("BEGIN")
            cursor = con.execute(
                "SELECT last_seq, first_retained_seq FROM agent_event_cursors WHERE stream_id = ?",
                (stream_id,),
            ).fetchone()
            bounds = con.execute(
                "SELECT MIN(seq), MAX(seq) FROM agent_events WHERE stream_id = ?",
                (stream_id,),
            ).fetchone()
            if cursor is None:
                if bounds and bounds[1] is not None:
                    current_last_seq = int(bounds[1])
                else:
                    current_last_seq = 0
            else:
                current_last_seq = max(
                    int(cursor[0]),
                    int(bounds[1]) if bounds and bounds[1] is not None else 0,
                )
            last_seq = (
                current_last_seq
                if requested_through is None
                else min(current_last_seq, requested_through)
            )
            first_retained = int(bounds[0]) if bounds and bounds[0] is not None else None
            cursor_reset = requested_after > current_last_seq
            effective_after = requested_after
            if cursor_reset:
                effective_after = (
                    max(0, first_retained - 1)
                    if first_retained is not None
                    else current_last_seq
                )
            rows = con.execute(
                """
                SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at
                FROM agent_events
                WHERE stream_id = ? AND seq > ? AND seq <= ?
                ORDER BY seq ASC
                LIMIT ?
                """,
                (stream_id, effective_after, last_seq, page_limit + 1),
            ).fetchall()
            has_more = len(rows) > page_limit
            events = [AgentEvent.from_row(row) for row in rows[:page_limit]]
            next_seq = events[-1].seq if events else effective_after
            gap_ranges: list[dict[str, int]] = []
            expected_seq = effective_after + 1
            for event in events:
                if event.seq > expected_seq:
                    gap_ranges.append({"from_seq": expected_seq, "to_seq": event.seq - 1})
                expected_seq = event.seq + 1
            if not has_more and expected_seq <= last_seq:
                trailing_gap = {"from_seq": expected_seq, "to_seq": last_seq}
                gap_ranges.append(trailing_gap)
                next_seq = trailing_gap["to_seq"]
            result = {
                "success": True,
                "events": [event.to_dict() for event in events],
                "next_seq": next_seq,
                "first_retained_seq": first_retained,
                "last_seq": last_seq,
                "has_more": has_more,
                "gap_ranges": gap_ranges,
                "cursor_reset": cursor_reset,
            }
            con.execute("COMMIT")
            return result
        except Exception as exc:
            if con is not None:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
            detail = (
                str(exc)
                if isinstance(exc, (TimeoutError,))
                else None
            )
            return self._event_page_error(requested_after, detail)
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    def _event_page_error(next_seq: int, message: str | None = None) -> dict[str, Any]:
        return {
            "success": False,
            "events": [],
            "next_seq": next_seq,
            "first_retained_seq": None,
            "last_seq": 0,
            "has_more": False,
            "gap_ranges": [],
            "cursor_reset": False,
            "error": {
                "code": "event_page_unavailable",
                "message": message or "Event page could not be read.",
            },
        }

    def events(self, stream_id: str, after_seq: int = 0, limit: int = 1000) -> list[AgentEvent]:
        if not self.enabled or not self.db_path.exists():
            return []
        self._ensure_schema()
        con = connect_sqlite(self.db_path)
        try:
            cur = con.execute(
                """
                SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at
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
        raw_state = json_dumps(state, separators=(",", ":"))

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

    def cleanup(self, retention_days: int = 30) -> dict[str, Any]:
        if not self.enabled or not self.db_path.exists():
            return {"success": True, "deleted_events": 0, "deleted_snapshots": 0}
        self._ensure_schema()
        cutoff = time.time() - (max(1, int(retention_days)) * 86400)

        def _do_cleanup() -> dict[str, Any]:
            con = connect_sqlite(self.db_path, isolation_level=None)
            try:
                con.execute("BEGIN IMMEDIATE")
                cur_ev = con.execute("DELETE FROM agent_events WHERE created_at < ?", (cutoff,))
                deleted_events = cur_ev.rowcount if cur_ev else 0
                con.execute("""
                    UPDATE agent_event_cursors
                    SET first_retained_seq = COALESCE(
                        (SELECT MIN(seq) FROM agent_events WHERE stream_id = agent_event_cursors.stream_id),
                        last_seq + 1
                    )
                """)
                cur_snap = con.execute("DELETE FROM agent_snapshots WHERE created_at < ?", (cutoff,))
                deleted_snaps = cur_snap.rowcount if cur_snap else 0
                con.execute("COMMIT")
                return {"success": True, "deleted_events": deleted_events, "deleted_snapshots": deleted_snaps}
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                con.close()

        return retry_busy(_do_cleanup, retries=5, base_delay_seconds=0.02)

    def export_delta(self, stream_id: str = "", after_seq: int = 0, limit: int = 1000) -> dict[str, Any]:
        if not self.enabled or not self.db_path.exists():
            return {"success": True, "events": [], "count": 0}
        self._ensure_schema()
        con = connect_sqlite(self.db_path)
        try:
            if stream_id:
                cur = con.execute(
                    """
                    SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at
                    FROM agent_events
                    WHERE stream_id = ? AND seq > ?
                    ORDER BY seq ASC LIMIT ?
                    """,
                    (stream_id, int(after_seq), max(1, int(limit))),
                )
            else:
                cur = con.execute(
                    """
                    SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at
                    FROM agent_events
                    WHERE seq > ?
                    ORDER BY seq ASC LIMIT ?
                    """,
                    (int(after_seq), max(1, int(limit))),
                )
            rows = cur.fetchall()
            evs = [AgentEvent.from_row(row).to_dict() for row in rows]
            return {"success": True, "events": evs, "count": len(evs)}
        finally:
            con.close()

    def import_delta(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "error": "agent state store disabled"}
        imported = 0
        duplicates = 0
        for ev_data in events:
            try:
                ev = AgentEvent.from_dict(ev_data)
                res = self.append(ev)
                if res.duplicate:
                    duplicates += 1
                elif res.seq > 0:
                    imported += 1
            except Exception:
                continue
        return {"success": True, "imported_count": imported, "duplicate_count": duplicates}


class SwarmPubSub:
    """Lightweight in-memory and SQLite-backed pubsub topic bus for swarm agent workers."""

    _instance: SwarmPubSub | None = None
    _lock = threading.Lock()

    def __init__(self, state_store: AgentStateStore | None = None, max_age_seconds: float = 3600.0):
        self.state_store = state_store
        self.max_age_seconds = float(max_age_seconds)
        self._topics: dict[str, list[dict[str, Any]]] = {}
        self._subscribers: dict[str, dict[str, queue.Queue[dict[str, Any]]]] = {}
        self._mu = threading.Lock()

    @classmethod
    def get_default(cls, state_store: AgentStateStore | None = None) -> SwarmPubSub:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(state_store)
            elif state_store is not None and cls._instance.state_store is None:
                cls._instance.state_store = state_store
            return cls._instance

    def subscribe(self, topic: str, maxsize: int = 100) -> tuple[str, queue.Queue[dict[str, Any]]]:
        """Register a bounded listener queue for a topic."""
        clean_topic = topic.strip().lower()
        sub_id = f"sub_{uuid.uuid4().hex[:10]}"
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max(10, min(int(maxsize), 1000)))
        with self._mu:
            if clean_topic not in self._subscribers:
                self._subscribers[clean_topic] = {}
            self._subscribers[clean_topic][sub_id] = q
        return sub_id, q

    def unsubscribe(self, topic: str, sub_id: str) -> bool:
        """Unregister a listener queue from a topic."""
        clean_topic = topic.strip().lower()
        with self._mu:
            subs = self._subscribers.get(clean_topic, {})
            if sub_id in subs:
                del subs[sub_id]
                return True
        return False

    def _prune_expired_locked(self, clean_topic: str, now: float) -> None:
        cutoff = now - self.max_age_seconds
        msgs = self._topics.get(clean_topic, [])
        if msgs and msgs[0]["timestamp"] < cutoff:
            self._topics[clean_topic] = [m for m in msgs if m["timestamp"] >= cutoff]

    def publish(self, topic: str, message: dict[str, Any] | str, sender: str = "agent") -> dict[str, Any]:
        """Publish a message to an ephemeral topic channel with memory bounds and TTL pruning."""
        clean_topic = topic.strip().lower()
        now = time.time()
        msg_payload = message if isinstance(message, dict) else {"text": str(message)}
        event = {
            "id": f"pub_{uuid.uuid4().hex[:12]}",
            "topic": clean_topic,
            "sender": sender,
            "timestamp": now,
            "payload": msg_payload,
        }
        with self._mu:
            if clean_topic not in self._topics:
                if len(self._topics) > 128:
                    empty = [t for t, ms in self._topics.items() if not ms or (now - ms[-1]["timestamp"] > self.max_age_seconds)]
                    for t in empty:
                        self._topics.pop(t, None)
                self._topics[clean_topic] = []
            self._topics[clean_topic].append(event)
            if len(self._topics[clean_topic]) > 200:
                self._topics[clean_topic] = self._topics[clean_topic][-200:]
            self._prune_expired_locked(clean_topic, now)

            # Fan out to bounded subscriber queues without leaking
            for sub_id, q in list(self._subscribers.get(clean_topic, {}).items()):
                try:
                    q.put_nowait(event)
                except queue.Full:
                    try:
                        q.get_nowait()
                        q.put_nowait(event)
                    except Exception:
                        pass
                except Exception:
                    pass

        if self.state_store and self.state_store.enabled:
            try:
                self.state_store.append(
                    AgentEvent.create(
                        stream_id=f"pubsub:{clean_topic}",
                        kind="pubsub_message",
                        payload={"sender": sender, "message": msg_payload},
                        actor=sender,
                    )
                )
            except Exception:
                pass

        return {"success": True, "topic": clean_topic, "message_id": event["id"], "timestamp": now}

    def poll(self, topic: str, since_timestamp: float = 0.0, limit: int = 50) -> dict[str, Any]:
        """Poll messages from a topic published after since_timestamp."""
        clean_topic = topic.strip().lower()
        now = time.time()
        with self._mu:
            self._prune_expired_locked(clean_topic, now)
            msgs = [m for m in self._topics.get(clean_topic, []) if m["timestamp"] > since_timestamp]
        return {
            "success": True,
            "topic": clean_topic,
            "count": len(msgs[:limit]),
            "messages": msgs[:limit],
        }
