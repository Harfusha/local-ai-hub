from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, retry_busy


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

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self._initialized = False
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        con = connect_sqlite(self.db_path, timeout_seconds=2.0)
        return con

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            def init_db() -> None:
                with closing(self._connect()) as con:
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
                        con.execute("""
                        CREATE INDEX IF NOT EXISTS idx_blackboard_board ON agent_blackboard(board_id);
                        """)
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
    ) -> dict[str, Any]:
        """Update a section on the blackboard, advancing the author's vector clock. Supports optimistic concurrency via expected_version."""
        self._ensure_schema()
        clean_board = str(board_id).strip()
        clean_section = str(section).strip()
        clean_author = str(author).strip() or "agent"

        def _do_update() -> dict[str, Any]:
            with self._lock, closing(self._connect()) as con:
                cur = con.cursor()
                row = cur.execute(
                    "SELECT content, author, vector_clock, timestamp, version FROM agent_blackboard WHERE board_id=? AND section=?",
                    (clean_board, clean_section),
                ).fetchone()

                if row:
                    existing_clock = json.loads(str(row[2])) if row[2] else {}
                    existing_version = int(row[4] or 1)
                else:
                    existing_clock = {}
                    existing_version = 0

                if expected_version is not None:
                    if existing_version != int(expected_version):
                        return {
                            "success": False,
                            "error": f"Version conflict: current version {existing_version} does not match expected {expected_version}",
                            "version_conflict": True,
                            "current_version": existing_version,
                            "expected_version": int(expected_version),
                        }

                new_clock = dict(existing_clock)
                if clock:
                    for k, v in clock.items():
                        new_clock[str(k)] = max(new_clock.get(str(k), 0), int(v))
                new_clock[clean_author] = new_clock.get(clean_author, 0) + 1

                now = time.time()
                sec = BlackboardSection(
                    section=clean_section,
                    content=content,
                    author=clean_author,
                    clock=new_clock,
                    timestamp=now,
                    version=existing_version + 1,
                )

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
                        clean_section,
                        json.dumps(content, ensure_ascii=False),
                        clean_author,
                        json.dumps(new_clock),
                        now,
                        sec.version,
                    ),
                )
                con.commit()
                return {"success": True, "board_id": clean_board, "section": sec.to_dict(), "version": sec.version, "content": sec.content}

        return retry_busy(_do_update, retries=5, base_delay_seconds=0.02)

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

            with self._lock, closing(self._connect()) as con:
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
                            json.dumps(final_sec.content, ensure_ascii=False),
                            final_sec.author,
                            json.dumps(final_sec.clock),
                            final_sec.timestamp,
                            final_sec.version,
                        ),
                    )
                    merged_results.append(final_sec.to_dict())

                con.commit()
                return {"success": True, "board_id": clean_board, "merged_count": len(merged_results), "sections": merged_results}

        return retry_busy(_do_merge, retries=5, base_delay_seconds=0.02)

    def delete(self, board_id: str, section: str | None = None) -> dict[str, Any]:
        """Delete an entire blackboard or a specific section from it."""
        self._ensure_schema()
        clean_board = str(board_id).strip()
        clean_section = str(section).strip() if section is not None else None

        def _do_delete() -> dict[str, Any]:
            with self._lock, closing(self._connect()) as con:
                cur = con.cursor()
                if clean_section:
                    cur.execute(
                        "DELETE FROM agent_blackboard WHERE board_id = ? AND section = ?",
                        (clean_board, clean_section),
                    )
                else:
                    cur.execute(
                        "DELETE FROM agent_blackboard WHERE board_id = ?",
                        (clean_board,),
                    )
                deleted_count = cur.rowcount
                con.commit()
                return {
                    "success": True,
                    "board_id": clean_board,
                    "section": clean_section,
                    "deleted_count": deleted_count,
                }

        return retry_busy(_do_delete, retries=5, base_delay_seconds=0.02)
