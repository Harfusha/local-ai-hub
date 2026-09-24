from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error, retry_busy


class AgentStateSchemaMismatchError(RuntimeError):
    def __init__(self, backup_path: Path) -> None:
        self.backup_path = backup_path
        super().__init__(
            f"agent state schema mismatch; durable data preserved in {backup_path.name}; explicit recovery required"
        )


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
                    initialize_wal(con)
                    existing = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    current = True
                    if "agent_events" in existing:
                        current = [str(row[1]) for row in con.execute("PRAGMA table_info(agent_events)")] == expected_events
                    if current and "agent_snapshots" in existing:
                        current = [str(row[1]) for row in con.execute("PRAGMA table_info(agent_snapshots)")] == expected_snapshots
                    if current and ("agent_events" in existing or "agent_snapshots" in existing) and "agent_stream_cursors" not in existing:
                        current = False
                    if current and "agent_stream_cursors" in existing:
                        current = [str(row[1]) for row in con.execute("PRAGMA table_info(agent_stream_cursors)")] == expected_cursors
                    if not current:
                        backup_path = self.db_path.with_name(
                            f"{self.db_path.name}.recovery-{uuid.uuid4().hex}.bak.sqlite3"
                        )
                        backup_con = sqlite3.connect(str(backup_path))
                        try:
                            con.backup(backup_con)
                        finally:
                            backup_con.close()
                        raise AgentStateSchemaMismatchError(backup_path)
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
                        CREATE TABLE IF NOT EXISTS agent_stream_cursors (
                            stream_id TEXT PRIMARY KEY,
                            last_seq INTEGER NOT NULL,
                            first_retained_seq INTEGER NOT NULL
                        );
                        """)
                finally:
                    con.close()

            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    def append(self, event: AgentEvent, *, retention_limit: int | None = None) -> AppendResult:
        if not self.enabled:
            return AppendResult(seq=0, duplicate=False, error="agent_state is disabled")
        if retention_limit is not None and int(retention_limit) < 1:
            raise ValueError("retention_limit must be positive")

        payload_bytes = json_dumps(event.payload, separators=(",", ":")).encode("utf-8")
        if len(payload_bytes) > self.max_payload_bytes:
            raise ValueError(
                f"payload exceeds maximum allowed {self.max_payload_bytes} bytes (got {len(payload_bytes)})"
            )

        self._ensure_schema()

        def _do_append() -> AppendResult:
            # Keep each busy wait short; retry_busy provides bounded recovery for
            # transient locks, while persistent locks must return retryable quickly.
            con = connect_sqlite(self.db_path, isolation_level=None, timeout_seconds=0.25)
            try:
                con.execute("BEGIN IMMEDIATE")
                result = self._append_event_in_transaction(
                    con,
                    event,
                    payload=payload_bytes.decode("utf-8"),
                    retention_limit=retention_limit,
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
            res = retry_busy(_do_append, retries=5, base_delay_seconds=0.02)
            if not res.duplicate and res.event is not None:
                self._publish(res.event)
            return res
        except Exception as exc:
            if is_busy_error(exc):
                return AppendResult(seq=0, duplicate=False, retryable=True, error=str(exc))
            raise

    def _append_event_in_transaction(
        self,
        con: sqlite3.Connection,
        event: AgentEvent,
        *,
        payload: str | None = None,
        retention_limit: int | None = None,
    ) -> AppendResult:
        """Insert an event and advance its durable cursor using a caller-owned transaction."""
        event_payload = payload if payload is not None else json_dumps(event.payload, separators=(",", ":"))
        existing = con.execute(
            """
            SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at
            FROM agent_events WHERE stream_id = ? AND idempotency_key = ?
            """,
            (event.stream_id, event.idempotency_key),
        ).fetchone()
        if existing:
            existing_event = AgentEvent.from_row(existing)
            try:
                same_payload = existing_event.payload == json.loads(event_payload)
            except (TypeError, ValueError):
                same_payload = False
            if existing_event.kind != event.kind or not same_payload:
                return AppendResult(
                    seq=existing_event.seq or 0,
                    duplicate=False,
                    error=f"idempotency key conflict for stream {event.stream_id}",
                )
            return AppendResult(seq=existing_event.seq or 0, duplicate=True, event=existing_event)

        cursor = con.execute(
            "SELECT last_seq, first_retained_seq FROM agent_stream_cursors WHERE stream_id = ?",
            (event.stream_id,),
        ).fetchone()
        if cursor:
            new_seq = int(cursor[0]) + 1
            first_retained_seq = min(int(cursor[1]), new_seq)
        else:
            row = con.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM agent_events WHERE stream_id = ?",
                (event.stream_id,),
            ).fetchone()
            new_seq = (int(row[0]) if row else 0) + 1
            first_retained_seq = new_seq

        if retention_limit is not None:
            retention_limit = int(retention_limit)
            if retention_limit < 1:
                raise ValueError("retention_limit must be positive")
            first_retained_seq = max(first_retained_seq, new_seq - retention_limit + 1)

        con.execute(
            """
            INSERT INTO agent_events (
                stream_id, seq, event_id, kind, payload, idempotency_key,
                correlation_id, actor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.stream_id, new_seq, event.event_id, event.kind, event_payload,
                event.idempotency_key, event.correlation_id, event.actor, event.created_at,
            ),
        )
        if retention_limit is not None and first_retained_seq > 1:
            con.execute(
                "DELETE FROM agent_events WHERE stream_id = ? AND seq < ?",
                (event.stream_id, first_retained_seq),
            )
        con.execute(
            """
            INSERT INTO agent_stream_cursors(stream_id, last_seq, first_retained_seq)
            VALUES (?, ?, ?)
            ON CONFLICT(stream_id) DO UPDATE SET last_seq = excluded.last_seq,
                first_retained_seq = excluded.first_retained_seq
            """,
            (event.stream_id, new_seq, first_retained_seq),
        )
        return AppendResult(seq=new_seq, duplicate=False, event=event.with_seq(new_seq))

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
                dropped: list[AgentEvent] = []
                while True:
                    try:
                        dropped.append(q.get_nowait())
                    except queue.Empty:
                        break
                ranges: dict[str, list[int]] = {}
                dropped_count = 0
                for item in dropped:
                    if item.kind == "agent_state.gap":
                        dropped_count += int(item.payload.get("dropped_count", 0))
                        for value in item.payload.get("streams", []):
                            if isinstance(value, dict):
                                stream = str(value.get("stream_id", ""))
                                start = int(value.get("from_seq", 0) or 0)
                                end = int(value.get("to_seq", 0) or 0)
                                if stream and start:
                                    prior = ranges.get(stream)
                                    ranges[stream] = [min(prior[0], start), max(prior[1], end)] if prior else [start, end]
                    else:
                        dropped_count += 1
                        if item.seq is not None:
                            prior = ranges.get(item.stream_id)
                            ranges[item.stream_id] = [min(prior[0], item.seq), max(prior[1], item.seq)] if prior else [item.seq, item.seq]
                with self._drop_count_lock:
                    self._dropped_event_count += dropped_count
                gap = AgentEvent.create(
                    stream_id="agent_state",
                    kind="agent_state.gap",
                    payload={
                        "reason": "subscriber_queue_overflow",
                        "dropped_count": dropped_count,
                        "streams": [
                            {"stream_id": stream, "from_seq": bounds[0], "to_seq": bounds[1]}
                            for stream, bounds in sorted(ranges.items())
                        ],
                    },
                    actor="system",
                )
                try:
                    q.put_nowait(gap)
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

    def event_page(self, stream_id: str, after_seq: int = 0, limit: int = 1000) -> dict[str, Any]:
        """Read one replay page with durable retention bounds and gap metadata."""
        if not self.enabled:
            return {"success": False, "events": [], "has_gap": False, "error": "agent_state is unavailable"}
        self._ensure_schema()
        if not self.db_path.exists():
            return {"success": False, "events": [], "has_gap": False, "error": "agent_state is unavailable"}
        cursor_seq = max(0, int(after_seq))
        page_limit = max(1, min(int(limit), 5000))
        con = connect_sqlite(self.db_path)
        try:
            con.execute("BEGIN")
            cursor = con.execute(
                "SELECT first_retained_seq, last_seq FROM agent_stream_cursors WHERE stream_id = ?",
                (stream_id,),
            ).fetchone()
            first_seq, last_seq = (int(cursor[0]), int(cursor[1])) if cursor else (0, 0)
            rows = con.execute(
                """
                SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at
                FROM agent_events WHERE stream_id = ? AND seq > ? ORDER BY seq ASC LIMIT ?
                """,
                (stream_id, cursor_seq, page_limit + 1),
            ).fetchall()
            has_more = len(rows) > page_limit
            events = [AgentEvent.from_row(row) for row in rows[:page_limit]]
            has_gap = bool(first_seq and cursor_seq < first_seq - 1)
            return {
                "success": True,
                "events": events,
                "has_gap": has_gap,
                "first_retained_seq": first_seq,
                "last_seq": last_seq,
                "has_more": has_more,
            }
        finally:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
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
                cur_snap = con.execute("DELETE FROM agent_snapshots WHERE created_at < ?", (cutoff,))
                deleted_snaps = cur_snap.rowcount if cur_snap else 0
                con.execute(
                    """
                    UPDATE agent_stream_cursors
                    SET first_retained_seq = COALESCE(
                        (SELECT MIN(seq) FROM agent_events WHERE stream_id = agent_stream_cursors.stream_id),
                        last_seq + 1
                    )
                    """
                )
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
    DEFAULT_MAX_RETAINED_MESSAGES = 1000

    def __init__(
        self,
        state_store: AgentStateStore | None = None,
        max_age_seconds: float = 3600.0,
        *,
        max_retained_messages: int = DEFAULT_MAX_RETAINED_MESSAGES,
    ):
        self.state_store = state_store
        if isinstance(max_retained_messages, bool) or not isinstance(max_retained_messages, int):
            raise TypeError("max_retained_messages must be an integer")
        if not 1 <= max_retained_messages <= self.DEFAULT_MAX_RETAINED_MESSAGES:
            raise ValueError(
                f"max_retained_messages must be between 1 and {self.DEFAULT_MAX_RETAINED_MESSAGES}"
            )
        self.max_retained_messages = max_retained_messages
        self._subscribers: dict[str, dict[str, queue.Queue[dict[str, Any]]]] = {}
        self._mu = threading.Lock()

    @classmethod
    def get_default(cls, state_store: AgentStateStore | None = None) -> SwarmPubSub:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(state_store)
            elif state_store is not None and cls._instance.state_store is not state_store:
                cls._instance.state_store = state_store
            return cls._instance

    def subscribe(self, topic: str, maxsize: int = 100) -> tuple[str, queue.Queue[dict[str, Any]]]:
        """Register a bounded listener queue for a topic."""
        clean_topic = topic.strip().lower()
        sub_id = f"sub_{uuid.uuid4().hex[:10]}"
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max(2, min(int(maxsize), 1000)))
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

    def publish(self, topic: str, message: dict[str, Any] | str, sender: str = "agent") -> dict[str, Any]:
        """Persist a topic message before notifying bounded in-process subscribers."""
        clean_topic = topic.strip().lower()
        if not clean_topic:
            return {"success": False, "error": "topic is required"}
        if self.state_store is None or not self.state_store.enabled:
            return {"success": False, "error": "durable agent state storage is unavailable"}
        msg_payload = message if isinstance(message, dict) else {"text": str(message)}
        event = AgentEvent.create(
            stream_id=f"pubsub:{clean_topic}",
            kind="pubsub_message",
            payload={"sender": sender, "message": msg_payload},
            actor=sender,
        )
        try:
            result = self.state_store.append(event, retention_limit=self.max_retained_messages)
        except Exception as exc:
            return {"success": False, "topic": clean_topic, "error": f"message persistence failed: {exc}"}
        if result.error or result.retryable or result.event is None:
            return {
                "success": False,
                "topic": clean_topic,
                "retryable": bool(result.retryable),
                "error": result.error or "message persistence failed",
            }
        persisted = result.event
        stored_message = {
            "id": persisted.event_id,
            "topic": clean_topic,
            "sender": sender,
            "timestamp": persisted.created_at,
            "seq": persisted.seq,
            "payload": msg_payload,
        }
        with self._mu:
            for q in list(self._subscribers.get(clean_topic, {}).values()):
                try:
                    q.put_nowait(stored_message)
                except queue.Full:
                    dropped: list[dict[str, Any]] = []
                    while True:
                        try:
                            dropped.append(q.get_nowait())
                        except queue.Empty:
                            break
                    first_seq = int(persisted.seq or 0)
                    last_seq = first_seq - 1
                    for item in dropped:
                        gap = item.get("gap") if isinstance(item, dict) else None
                        if isinstance(gap, dict):
                            first_seq = min(first_seq, int(gap.get("from_seq", first_seq)))
                            last_seq = max(last_seq, int(gap.get("to_seq", last_seq)))
                        else:
                            seq = int(item.get("seq", 0) or 0)
                            if seq:
                                first_seq = min(first_seq, seq)
                                last_seq = max(last_seq, seq)
                    try:
                        q.put_nowait({
                            "id": "gap",
                            "topic": clean_topic,
                            "sender": "system",
                            "timestamp": persisted.created_at,
                            "gap": {"reason": "subscriber_queue_overflow", "from_seq": first_seq, "to_seq": max(first_seq, last_seq)},
                        })
                        q.put_nowait(stored_message)
                    except queue.Full:
                        pass
                except Exception:
                    continue

        return {
            "success": True,
            "topic": clean_topic,
            "message_id": persisted.event_id,
            "seq": persisted.seq,
            "timestamp": persisted.created_at,
        }

    def poll(self, topic: str, after_seq: int = 0, limit: int = 50) -> dict[str, Any]:
        """Poll durable topic messages after a per-topic sequence cursor."""
        clean_topic = topic.strip().lower()
        if self.state_store is None or not self.state_store.enabled:
            return {"success": False, "topic": clean_topic, "error": "durable agent state storage is unavailable"}
        page = self.state_store.event_page(
            f"pubsub:{clean_topic}", after_seq=max(0, int(after_seq)), limit=max(1, min(int(limit), 1000))
        )
        if not page.get("success"):
            return {"success": False, "topic": clean_topic, "error": page.get("error", "message history is unavailable")}
        events = page.get("events", [])
        msgs = [
            {
                "id": event.event_id,
                "topic": clean_topic,
                "sender": str(event.payload.get("sender") or "agent"),
                "timestamp": event.created_at,
                "seq": event.seq,
                "payload": event.payload.get("message", {}),
            }
            for event in events
        ]
        has_gap = bool(page.get("has_gap"))
        gap = None
        if has_gap:
            gap = {
                "reason": "retention",
                "requested_after_seq": max(0, int(after_seq)),
                "first_retained_seq": int(page.get("first_retained_seq", 0)),
                "last_seq": int(page.get("last_seq", 0)),
            }
        next_seq = int(msgs[-1]["seq"] or after_seq) if msgs else max(0, int(after_seq))
        if gap is not None and not msgs:
            next_seq = int(page.get("last_seq", next_seq))
        return {
            "success": True,
            "topic": clean_topic,
            "count": len(msgs),
            "messages": msgs,
            "after_seq": max(0, int(after_seq)),
            "next_seq": next_seq,
            "last_seq": int(page.get("last_seq", 0)),
            "first_retained_seq": int(page.get("first_retained_seq", 0)),
            "has_gap": has_gap,
            "has_more": bool(page.get("has_more")),
            "gap": gap,
        }
