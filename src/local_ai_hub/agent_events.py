from __future__ import annotations

from .json_utils import dumps as json_dumps

import json
import queue
import threading
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

            def _remove_state_files() -> None:
                for suffix in ("", "-wal", "-shm"):
                    try:
                        Path(str(self.db_path) + suffix).unlink(missing_ok=True)
                    except OSError:
                        pass

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
                    if not current:
                        con.close()
                        _remove_state_files()
                        con = connect_sqlite(self.db_path)
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
                finally:
                    con.close()

            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    def append(self, event: AgentEvent) -> AppendResult:
        if not self.enabled:
            return AppendResult(seq=0, duplicate=False, error="agent_state is disabled")

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
                existing = con.execute(
                    """
                    SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at
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
                        correlation_id, actor, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            res = retry_busy(_do_append, retries=5, base_delay_seconds=0.02)
            if not res.duplicate and res.event is not None:
                self._publish(res.event)
            return res
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
        dead_queues: list[queue.Queue[AgentEvent]] = []
        with self._subscribers_lock:
            for q in list(self._subscribers):
                try:
                    q.put_nowait(event)
                except queue.Full:
                    try:
                        evicted = q.get_nowait()
                    except queue.Empty:
                        try:
                            q.put_nowait(event)
                        except queue.Full:
                            dead_queues.append(q)
                        continue

                    ranges_by_stream: dict[str, list[tuple[int, int]]] = {}
                    unknown_streams: list[str] = []
                    max_gap_ranges = 128
                    gap_ranges_truncated = False

                    def add_range(stream_id: Any, start: Any, end: Any) -> None:
                        name = str(stream_id or "uncategorized")[:160]
                        if type(start) is int and type(end) is int and start <= end:
                            ranges_by_stream.setdefault(name, []).append((start, end))
                        elif name not in unknown_streams:
                            unknown_streams.append(name)

                    def include_lost_event(lost: AgentEvent) -> None:
                        nonlocal gap_ranges_truncated
                        if lost.kind == "agent_state.gap" and lost.stream_id == "agent_state":
                            prior_ranges = lost.payload.get("streams", ())
                            if isinstance(prior_ranges, (list, tuple)):
                                gap_ranges_truncated = gap_ranges_truncated or bool(
                                    lost.payload.get("streams_truncated")
                                )
                                if len(prior_ranges) > max_gap_ranges:
                                    gap_ranges_truncated = True
                                for item in prior_ranges[:max_gap_ranges]:
                                    if isinstance(item, Mapping):
                                        add_range(item.get("stream_id"), item.get("from_seq"), item.get("to_seq"))
                            return
                        add_range(lost.stream_id, lost.seq, lost.seq)

                    include_lost_event(evicted)
                    include_lost_event(event)
                    gap_ranges: list[dict[str, Any]] = []
                    for stream_id, intervals in ranges_by_stream.items():
                        merged: list[list[int]] = []
                        for start, end in sorted(intervals):
                            if merged and start <= merged[-1][1] + 1:
                                merged[-1][1] = max(merged[-1][1], end)
                            else:
                                merged.append([start, end])
                        gap_ranges.extend(
                            {"stream_id": stream_id, "from_seq": start, "to_seq": end}
                            for start, end in merged
                        )
                    gap_ranges.extend(
                        {"stream_id": stream_id, "from_seq": None, "to_seq": None}
                        for stream_id in unknown_streams
                    )
                    if len(gap_ranges) > max_gap_ranges:
                        gap_ranges = gap_ranges[:max_gap_ranges]
                        gap_ranges_truncated = True
                    gap_event = AgentEvent.create(
                        "agent_state",
                        "agent_state.gap",
                        {"streams": gap_ranges, "streams_truncated": gap_ranges_truncated},
                        actor="system",
                    )
                    dropped = sum(
                        1
                        for lost in (evicted, event)
                        if not (lost.kind == "agent_state.gap" and lost.stream_id == "agent_state")
                    )
                    if dropped:
                        with self._drop_count_lock:
                            self._dropped_event_count += dropped
                    try:
                        q.put_nowait(gap_event)
                    except queue.Full:
                        dead_queues.append(q)
                except Exception:
                    dead_queues.append(q)
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
        try:
            cursor = 0 if isinstance(after_seq, bool) else max(0, int(after_seq))
        except (TypeError, ValueError, OverflowError):
            cursor = 0
        try:
            page_limit = 1000 if isinstance(limit, bool) else max(1, min(int(limit), 10_000))
        except (TypeError, ValueError, OverflowError):
            page_limit = 1000

        def page_error(code: str, message: str) -> dict[str, Any]:
            return {
                "success": False,
                "events": [],
                "next_seq": cursor,
                "first_retained_seq": 0,
                "last_seq": 0,
                "has_more": False,
                "gap_ranges": [],
                "cursor_reset": False,
                "error": {"code": code, "message": message},
            }

        if not self.enabled:
            return page_error("agent_state_disabled", "agent state is disabled")
        if not self.db_path.exists():
            reset = cursor > 0
            return {
                "success": True,
                "events": [],
                "next_seq": 0 if reset else cursor,
                "first_retained_seq": 0,
                "last_seq": 0,
                "has_more": False,
                "gap_ranges": [],
                "cursor_reset": reset,
            }

        try:
            self._ensure_schema()
            con = connect_sqlite(self.db_path)
            try:
                con.execute("BEGIN")
                retained = con.execute(
                    "SELECT MIN(seq), MAX(seq) FROM agent_events WHERE stream_id = ?",
                    (str(stream_id or ""),),
                ).fetchone()
                first_retained_seq = int(retained[0]) if retained and retained[0] is not None else 0
                last_seq = int(retained[1]) if retained and retained[1] is not None else 0
                cursor_reset = cursor > last_seq
                effective_cursor = max(0, first_retained_seq - 1) if cursor_reset else cursor
                gap_ranges: list[dict[str, int]] = []
                if first_retained_seq and effective_cursor < first_retained_seq - 1:
                    gap_ranges.append({
                        "from_seq": max(1, effective_cursor + 1),
                        "to_seq": first_retained_seq - 1,
                    })
                    effective_cursor = first_retained_seq - 1
                rows = con.execute(
                    """
                    SELECT stream_id, seq, event_id, kind, payload, idempotency_key, correlation_id, actor, created_at
                    FROM agent_events WHERE stream_id = ? AND seq > ? ORDER BY seq ASC LIMIT ?
                    """,
                    (str(stream_id or ""), effective_cursor, page_limit + 1),
                ).fetchall()
                con.execute("COMMIT")
            finally:
                con.close()

            has_more = len(rows) > page_limit
            events = [AgentEvent.from_row(row).to_dict() for row in rows[:page_limit]]
            expected_seq = effective_cursor + 1
            for event in events:
                seq = int(event["seq"] or 0)
                if seq > expected_seq:
                    gap_ranges.append({"from_seq": expected_seq, "to_seq": seq - 1})
                expected_seq = seq + 1
            next_seq = int(events[-1]["seq"] or 0) if events else effective_cursor
            return {
                "success": True,
                "events": events,
                "next_seq": next_seq,
                "first_retained_seq": first_retained_seq,
                "last_seq": last_seq,
                "has_more": has_more,
                "gap_ranges": gap_ranges,
                "cursor_reset": cursor_reset,
            }
        except Exception:
            return page_error("event_page_unavailable", "event page is unavailable")

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
