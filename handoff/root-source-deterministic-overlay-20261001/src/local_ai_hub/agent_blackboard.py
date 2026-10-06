from __future__ import annotations

from .json_utils import dumps as json_dumps

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import closing, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent_events import AgentEvent, AgentStateStore
from .sqlite_support import connect_sqlite, initialize_wal, retry_busy, validate_durable_schema


@dataclass(frozen=True)
class BlackboardSection:
    section: str
    content: Any
    author: str
    clock: dict[str, int] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "content": self.content,
            "author": self.author,
            "clock": dict(self.clock),
            "timestamp": self.timestamp,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_section: str = "") -> BlackboardSection:
        return cls(
            section=str(data.get("section") or default_section),
            content=data.get("content"),
            author=str(data.get("author") or "agent"),
            clock={str(k): int(v) for k, v in (data.get("clock") or {}).items()},
            timestamp=float(data.get("timestamp") or time.time()),
            version=int(data.get("version") or 1),
        )


def merge_sections(s1: BlackboardSection, s2: BlackboardSection) -> BlackboardSection:
    """CRDT merge function for two versions of the same blackboard section.

    Uses vector clock domination with deterministic Last-Write-Wins (LWW) tie-breaking.
    The resulting vector clock is the element-wise supremum of both clocks.
    """
    all_keys = set(s1.clock) | set(s2.clock)
    merged_clock = {k: max(s1.clock.get(k, 0), s2.clock.get(k, 0)) for k in all_keys}

    s1_dominates = bool(all_keys) and all(s1.clock.get(k, 0) >= s2.clock.get(k, 0) for k in all_keys) and s1.clock != s2.clock
    s2_dominates = bool(all_keys) and all(s2.clock.get(k, 0) >= s1.clock.get(k, 0) for k in all_keys) and s1.clock != s2.clock

    if s1_dominates:
        winner = s1
        version = s1.version
    elif s2_dominates:
        winner = s2
        version = s2.version
    else:
        # Concurrent or identical clocks: LWW on wall timestamp with author string tie-breaker
        if s1.timestamp > s2.timestamp:
            winner = s1
        elif s2.timestamp > s1.timestamp:
            winner = s2
        else:
            winner = s1 if str(s1.author) >= str(s2.author) else s2
        is_concurrent_conflict = s1.clock != s2.clock
        version = max(s1.version, s2.version) + (1 if is_concurrent_conflict else 0)

    return BlackboardSection(
        section=s1.section,
        content=winner.content,
        author=winner.author,
        clock=merged_clock,
        timestamp=max(s1.timestamp, s2.timestamp),
        version=version,
    )


class BlackboardStore:
    """Conflict-Free Replicated Data Type (CRDT) multi-agent blackboard store."""

    def __init__(self, db_path: Path | str, state_store: AgentStateStore | None = None) -> None:
        self.db_path = Path(db_path)
        self.state_store = state_store
        self._lock = threading.RLock()
        self._initialized = False
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.db_path, timeout_seconds=2.0)

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            if self.state_store is not None and self.state_store.enabled:
                self.state_store._ensure_schema()
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            expected = {
                "agent_blackboard": [
                    ("board_id", "TEXT", 1, 1), ("section", "TEXT", 1, 2),
                    ("content", "TEXT", 1, 0), ("author", "TEXT", 1, 0),
                    ("vector_clock", "TEXT", 1, 0), ("timestamp", "REAL", 1, 0),
                    ("version", "INTEGER", 1, 0),
                ],
            }

            def init_db() -> None:
                con = self._connect()
                try:
                    validate_durable_schema(
                        con,
                        self.db_path,
                        expected,
                        required_if_event_kinds={"agent_blackboard": ("blackboard.%",)},
                    )
                    initialize_wal(con)
                    with con:
                        con.execute("""
                        CREATE TABLE IF NOT EXISTS agent_blackboard (
                            board_id TEXT NOT NULL,
                            section TEXT NOT NULL,
                            content TEXT NOT NULL,
                            author TEXT NOT NULL,
                            vector_clock TEXT NOT NULL,
                            timestamp REAL NOT NULL,
                            version INTEGER NOT NULL,
                            PRIMARY KEY (board_id, section)
                        );
                        """)
                        con.execute("CREATE INDEX IF NOT EXISTS idx_blackboard_board ON agent_blackboard(board_id)")
                finally:
                    con.close()

            retry_busy(init_db, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    def update(
        self,
        board_id: str,
        section: str,
        content: Any,
        author: str,
        clock: dict[str, int] | None = None,
        expected_version: int | None = None,
        idempotency_key: str = "",
        *,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """CAS-update section; append change event in same transaction when stores share DB."""
        self._ensure_schema()
        clean_board = str(board_id).strip()
        clean_section = str(section).strip()
        clean_author = str(author).strip() or "agent"
        if connection is not None:
            return self._update_in_transaction(
                connection, clean_board, clean_section, content, clean_author,
                clock, expected_version, idempotency_key,
            )

        def _do_update() -> dict[str, Any]:
            with self._lock, closing(self._connect()) as con:
                con.isolation_level = None
                con.execute("BEGIN IMMEDIATE")
                try:
                    result = self._update_in_transaction(
                        con, clean_board, clean_section, content, clean_author,
                        clock, expected_version, idempotency_key,
                    )
                    con.execute("COMMIT")
                    return result
                except Exception:
                    try:
                        con.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise

        publication_lock = (
            self.state_store._append_publish_lock
            if self.state_store is not None
            else nullcontext()
        )
        with publication_lock:
            result = retry_busy(_do_update, retries=5, base_delay_seconds=0.02)
            event = result.pop("_event", None)
            if event is not None and self.state_store is not None:
                self.state_store._publish(event)
        return result

    def _update_in_transaction(
        self,
        con: sqlite3.Connection,
        board_id: str,
        section: str,
        content: Any,
        author: str,
        clock: dict[str, int] | None,
        expected_version: int | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        row = con.execute(
            "SELECT content, author, vector_clock, timestamp, version "
            "FROM agent_blackboard WHERE board_id=? AND section=?",
            (board_id, section),
        ).fetchone()
        if row:
            existing_clock = json.loads(str(row[2])) if row[2] else {}
            existing_version = int(row[4] or 1)
        else:
            existing_clock = {}
            existing_version = 0

        operation_key = idempotency_key
        event_stream = f"blackboard:{board_id}:{section}"
        if self.state_store is not None and self.state_store.enabled:
            key_payload = json_dumps({
                "board_id": board_id,
                "section": section,
                "author": author,
                "base_version": int(expected_version) if expected_version is not None else existing_version,
                "content": content,
                "clock": clock or {},
            }, separators=(",", ":"), ensure_ascii=False)
            operation_key = operation_key or (
                "bb_" + hashlib.sha256(key_payload.encode("utf-8")).hexdigest()[:24]
            )
            existing_event = con.execute(
                """
                SELECT stream_id, seq, event_id, kind, payload, idempotency_key,
                       correlation_id, actor, created_at
                FROM agent_events WHERE stream_id = ? AND idempotency_key = ?
                """,
                (event_stream, operation_key),
            ).fetchone()
            if existing_event:
                event = AgentEvent.from_row(existing_event)
                stored_section = event.payload.get("section")
                stored_clock = (stored_section or {}).get("clock", {})
                requested_expected_version = int(expected_version) if expected_version is not None else None
                if "expected_version" in event.payload:
                    expected_version_matches = event.payload.get("expected_version") == requested_expected_version
                else:
                    stored_version = int((stored_section or {}).get("version", existing_version))
                    expected_version_matches = (
                        requested_expected_version is None
                        or stored_version == requested_expected_version + 1
                    )
                requested_clock_matches = all(
                    int(stored_clock.get(str(key), 0)) >= int(value)
                    for key, value in (clock or {}).items()
                )
                if (
                    event.kind != "blackboard.updated"
                    or not stored_section
                    or stored_section.get("content") != content
                    or stored_section.get("author") != author
                    or not expected_version_matches
                    or not requested_clock_matches
                ):
                    return {
                        "success": False,
                        "error": "idempotency key was already used for different blackboard content",
                        "idempotency_conflict": True,
                        "current_version": existing_version,
                    }
                return {
                    "success": True,
                    "duplicate": True,
                    "board_id": board_id,
                    "section": stored_section,
                    "version": int((stored_section or {}).get("version", existing_version)),
                    "content": (stored_section or {}).get("content", content),
                }

        if expected_version is not None and existing_version != int(expected_version):
            return {
                "success": False,
                "error": f"Version conflict: current version {existing_version} does not match expected {expected_version}",
                "version_conflict": True,
                "current_version": existing_version,
                "expected_version": int(expected_version),
            }

        new_clock = dict(existing_clock)
        if clock:
            for key, value in clock.items():
                new_clock[str(key)] = max(new_clock.get(str(key), 0), int(value))
        new_clock[author] = new_clock.get(author, 0) + 1
        now = time.time()
        section_value = BlackboardSection(
            section=section,
            content=content,
            author=author,
            clock=new_clock,
            timestamp=now,
            version=existing_version + 1,
        )
        if row:
            cur = con.execute(
                """
                UPDATE agent_blackboard SET content=?, author=?, vector_clock=?, timestamp=?, version=?
                WHERE board_id=? AND section=? AND version=?
                """,
                (
                    json_dumps(content, ensure_ascii=False),
                    author,
                    json_dumps(new_clock),
                    now,
                    section_value.version,
                    board_id,
                    section,
                    existing_version,
                ),
            )
        else:
            cur = con.execute(
                """
                INSERT INTO agent_blackboard
                    (board_id, section, content, author, vector_clock, timestamp, version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    board_id,
                    section,
                    json_dumps(content, ensure_ascii=False),
                    author,
                    json_dumps(new_clock),
                    now,
                    section_value.version,
                ),
            )
        if cur.rowcount != 1:
            current = con.execute(
                "SELECT version FROM agent_blackboard WHERE board_id=? AND section=?",
                (board_id, section),
            ).fetchone()
            current_version = int(current[0]) if current else 0
            return {
                "success": False,
                "error": "Blackboard section changed during update",
                "version_conflict": True,
                "current_version": current_version,
                "expected_version": existing_version,
            }

        result: dict[str, Any] = {
            "success": True,
            "board_id": board_id,
            "section": section_value.to_dict(),
            "version": section_value.version,
            "content": section_value.content,
        }
        if self.state_store is not None and self.state_store.enabled:
            event = AgentEvent.create(
                stream_id=event_stream,
                kind="blackboard.updated",
                payload={
                    "board_id": board_id,
                    "section": section_value.to_dict(),
                    "expected_version": int(expected_version) if expected_version is not None else None,
                },
                idempotency_key=operation_key,
                actor=author,
            )
            append = self.state_store.append_in_transaction(con, event, strict_idempotency=True)
            if append.error or append.event is None:
                raise RuntimeError(append.error or "blackboard event append returned no persisted event")
            if append.duplicate:
                raise sqlite3.IntegrityError("blackboard projection/event idempotency mismatch")
            result["_event"] = append.event
        return result

    def get(self, board_id: str, section: str | None = None) -> dict[str, Any]:
        """Fetch full board state or a specific section."""
        self._ensure_schema()
        clean_board = str(board_id).strip()

        def _do_get() -> dict[str, Any]:
            with self._lock, closing(self._connect()) as con:
                cur = con.cursor()
                if section:
                    clean_sec = str(section).strip()
                    row = cur.execute(
                        "SELECT content, author, vector_clock, timestamp, version FROM agent_blackboard WHERE board_id=? AND section=?",
                        (clean_board, clean_sec),
                    ).fetchone()
                    if not row:
                        return {"success": False, "error": f"section '{clean_sec}' not found on board '{clean_board}'"}
                    content = json.loads(str(row[0])) if row[0] else None
                    clock = json.loads(str(row[2])) if row[2] else {}
                    sec = BlackboardSection(
                        section=clean_sec, content=content, author=str(row[1]),
                        clock=clock, timestamp=float(row[3]), version=int(row[4]),
                    )
                    return {"success": True, "board_id": clean_board, "section": sec.to_dict()}

                rows = cur.execute(
                    "SELECT section, content, author, vector_clock, timestamp, version FROM agent_blackboard WHERE board_id=?",
                    (clean_board,),
                ).fetchall()

                sections: dict[str, Any] = {}
                for r in rows:
                    s_name = str(r[0])
                    cnt = json.loads(str(r[1])) if r[1] else None
                    clk = json.loads(str(r[3])) if r[3] else {}
                    sections[s_name] = BlackboardSection(
                        section=s_name, content=cnt, author=str(r[2]),
                        clock=clk, timestamp=float(r[4]), version=int(r[5]),
                    ).to_dict()

                return {"success": True, "board_id": clean_board, "sections": sections, "count": len(sections)}

        return retry_busy(_do_get, retries=5, base_delay_seconds=0.02)

    def list_boards(self) -> list[str]:
        """List all active blackboard IDs."""
        self._ensure_schema()

        def _do_list() -> list[str]:
            with self._lock, closing(self._connect()) as con:
                rows = con.execute("SELECT DISTINCT board_id FROM agent_blackboard ORDER BY board_id").fetchall()
                return [str(r[0]) for r in rows]

        return retry_busy(_do_list, retries=5, base_delay_seconds=0.02)

    def merge(self, board_id: str, remote_sections: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
        """Merge external/remote sections into this blackboard using CRDT rules."""
        self._ensure_schema()
        clean_board = str(board_id).strip()

        if isinstance(remote_sections, list):
            items = {str(item.get("section", "")): item for item in remote_sections if isinstance(item, dict)}
        elif isinstance(remote_sections, dict):
            items = remote_sections
        else:
            return {"success": False, "error": "remote_sections must be a dict or list"}

        def _do_merge() -> dict[str, Any]:
            merged_results: list[dict[str, Any]] = []
            published: list[AgentEvent] = []

            with self._lock, closing(self._connect()) as con:
                con.isolation_level = None
                con.execute("BEGIN IMMEDIATE")
                cur = con.cursor()
                for sec_name, raw_data in items.items():
                    if not sec_name or not isinstance(raw_data, dict):
                        continue
                    remote_sec = BlackboardSection.from_dict(raw_data, default_section=sec_name)

                    row = cur.execute(
                        "SELECT content, author, vector_clock, timestamp, version FROM agent_blackboard WHERE board_id=? AND section=?",
                        (clean_board, sec_name),
                    ).fetchone()

                    if row:
                        cnt = json.loads(str(row[0])) if row[0] else None
                        clk = json.loads(str(row[2])) if row[2] else {}
                        local_sec = BlackboardSection(
                            section=sec_name, content=cnt, author=str(row[1]),
                            clock=clk, timestamp=float(row[3]), version=int(row[4]),
                        )
                        final_sec = merge_sections(local_sec, remote_sec)
                    else:
                        final_sec = remote_sec

                    cur.execute(
                        """
                        INSERT INTO agent_blackboard (board_id, section, content, author, vector_clock, timestamp, version)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(board_id, section) DO UPDATE SET
                            content=excluded.content,
                            author=excluded.author,
                            vector_clock=excluded.vector_clock,
                            timestamp=excluded.timestamp,
                            version=excluded.version
                        """,
                        (
                            clean_board,
                            final_sec.section,
                            json_dumps(final_sec.content, ensure_ascii=False),
                            final_sec.author,
                            json_dumps(final_sec.clock),
                            final_sec.timestamp,
                            final_sec.version,
                        ),
                    )
                    merged_results.append(final_sec.to_dict())
                    if self.state_store is not None and self.state_store.enabled:
                        merge_payload = json_dumps({
                            "board_id": clean_board,
                            "section": sec_name,
                            "remote": remote_sec.to_dict(),
                        }, separators=(",", ":"), ensure_ascii=False)
                        event = AgentEvent.create(
                            stream_id=f"blackboard:{clean_board}:{sec_name}",
                            kind="blackboard.merged",
                            payload={"board_id": clean_board, "section": final_sec.to_dict()},
                            idempotency_key="merge_" + hashlib.sha256(merge_payload.encode("utf-8")).hexdigest()[:24],
                            actor=remote_sec.author or "agent",
                        )
                        appended = self.state_store.append_in_transaction(
                            con, event, strict_idempotency=True
                        )
                        if appended.error or appended.event is None:
                            raise RuntimeError(appended.error or "blackboard merge event append returned no persisted event")
                        if not appended.duplicate and appended.event:
                            published.append(appended.event)

                con.execute("COMMIT")
                result = {
                    "success": True,
                    "board_id": clean_board,
                    "merged_count": len(merged_results),
                    "sections": merged_results,
                }
                result["_events"] = published
                return result

        publication_lock = (
            self.state_store._append_publish_lock
            if self.state_store is not None
            else nullcontext()
        )
        with publication_lock:
            result = retry_busy(_do_merge, retries=5, base_delay_seconds=0.02)
            for event in result.pop("_events", []):
                self.state_store._publish(event)
        return result

    def delete(self, board_id: str, section: str | None = None) -> dict[str, Any]:
        """Delete an entire blackboard or a specific section from it."""
        self._ensure_schema()
        clean_board = str(board_id).strip()
        clean_section = str(section).strip() if section is not None else None

        def _do_delete() -> dict[str, Any]:
            published: list[AgentEvent] = []
            with self._lock, closing(self._connect()) as con:
                con.isolation_level = None
                con.execute("BEGIN IMMEDIATE")
                try:
                    if clean_section:
                        rows = con.execute(
                            "SELECT section, version, vector_clock FROM agent_blackboard WHERE board_id = ? AND section = ?",
                            (clean_board, clean_section),
                        ).fetchall()
                        cur = con.execute(
                            "DELETE FROM agent_blackboard WHERE board_id = ? AND section = ?",
                            (clean_board, clean_section),
                        )
                    else:
                        rows = con.execute(
                            "SELECT section, version, vector_clock FROM agent_blackboard WHERE board_id = ?",
                            (clean_board,),
                        ).fetchall()
                        cur = con.execute("DELETE FROM agent_blackboard WHERE board_id = ?", (clean_board,))
                    deleted_count = max(0, cur.rowcount)
                    if self.state_store is not None and self.state_store.enabled:
                        for deleted_section, version, vector_clock in rows:
                            event = AgentEvent.create(
                                stream_id=f"blackboard:{clean_board}:{deleted_section}",
                                kind="blackboard.deleted",
                                payload={
                                    "board_id": clean_board,
                                    "section": str(deleted_section),
                                    "deleted_version": int(version),
                                    "clock": json.loads(str(vector_clock)) if vector_clock else {},
                                },
                                actor="system",
                            )
                            appended = self.state_store.append_in_transaction(
                                con, event, strict_idempotency=True
                            )
                            if appended.error or appended.event is None:
                                raise RuntimeError(appended.error or "blackboard tombstone event append returned no persisted event")
                            if not appended.duplicate and appended.event:
                                published.append(appended.event)
                    con.execute("COMMIT")
                except Exception:
                    try:
                        con.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise
                result = {
                    "success": True,
                    "board_id": clean_board,
                    "section": clean_section,
                    "deleted_count": deleted_count,
                }
                result["_events"] = published
                return result

        publication_lock = (
            self.state_store._append_publish_lock
            if self.state_store is not None
            else nullcontext()
        )
        with publication_lock:
            result = retry_busy(_do_delete, retries=5, base_delay_seconds=0.02)
            for event in result.pop("_events", []):
                if self.state_store is not None:
                    self.state_store._publish(event)
        return result
