from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, retry_busy

logger = logging.getLogger(__name__)


class BoardStore:
    """Project board, milestones, and session briefing store."""

    def __init__(self, db_path: Path | str, services: Any | None = None) -> None:
        self.db_path = Path(db_path)
        self.services = services
        self._lock = threading.RLock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return connect_sqlite(self.db_path)

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return

            def init_db() -> None:
                con = self._connect()
                try:
                    initialize_wal(con)
                    with con:
                        con.execute("""
                        CREATE TABLE IF NOT EXISTS agent_board_items (
                            item_id TEXT PRIMARY KEY,
                            title TEXT NOT NULL,
                            status TEXT NOT NULL,
                            priority TEXT NOT NULL DEFAULT 'medium',
                            labels_json TEXT NOT NULL DEFAULT '[]',
                            assignee TEXT NOT NULL DEFAULT '',
                            milestone TEXT NOT NULL DEFAULT '',
                            linked_task_id TEXT NOT NULL DEFAULT '',
                            details_json TEXT NOT NULL DEFAULT '{}',
                            created_at REAL NOT NULL,
                            updated_at REAL NOT NULL
                        );
                        """)
                        con.execute("CREATE INDEX IF NOT EXISTS idx_board_status ON agent_board_items(status);")
                        con.execute("CREATE INDEX IF NOT EXISTS idx_board_milestone ON agent_board_items(milestone);")
                        con.execute("""
                        CREATE TABLE IF NOT EXISTS agent_milestones (
                            name TEXT PRIMARY KEY,
                            target_date TEXT NOT NULL DEFAULT '',
                            description TEXT NOT NULL DEFAULT '',
                            created_at REAL NOT NULL
                        );
                        """)
                finally:
                    con.close()

            retry_busy(init_db, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    def item_create(
        self,
        title: str,
        status: str = "planned",
        priority: str = "medium",
        labels: list[str] | None = None,
        assignee: str = "",
        milestone: str = "",
        linked_task_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._ensure_schema()
        item_id = f"item_{uuid.uuid4().hex[:10]}"
        now = time.time()
        valid_status = status.lower() if status else "planned"
        if valid_status not in {"planned", "in_progress", "done", "blocked", "cancelled"}:
            valid_status = "planned"

        with self._lock:
            con = self._connect()
            try:
                with con:
                    con.execute(
                        """
                        INSERT INTO agent_board_items (
                            item_id, title, status, priority, labels_json,
                            assignee, milestone, linked_task_id, details_json,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item_id,
                            title.strip(),
                            valid_status,
                            priority.lower(),
                            json.dumps(labels or [], separators=(",", ":")),
                            assignee.strip(),
                            milestone.strip(),
                            linked_task_id.strip(),
                            json.dumps(details or {}, separators=(",", ":")),
                            now,
                            now,
                        ),
                    )
            finally:
                con.close()
        return {
            "success": True,
            "item": {
                "item_id": item_id,
                "title": title.strip(),
                "status": valid_status,
                "priority": priority.lower(),
                "labels": labels or [],
                "assignee": assignee.strip(),
                "milestone": milestone.strip(),
                "linked_task_id": linked_task_id.strip(),
                "created_at": now,
                "updated_at": now,
            },
        }

    def item_update(
        self,
        item_id: str,
        status: str | None = None,
        priority: str | None = None,
        labels: list[str] | None = None,
        assignee: str | None = None,
        milestone: str | None = None,
        linked_task_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._ensure_schema()
        now = time.time()
        with self._lock:
            con = self._connect()
            try:
                row = con.execute("SELECT * FROM agent_board_items WHERE item_id = ?", (item_id,)).fetchone()
                if row is None:
                    return {"success": False, "error": f"item '{item_id}' not found"}

                new_status = status.lower() if status else row[2]
                new_priority = priority.lower() if priority else row[3]
                new_labels = json.dumps(labels, separators=(",", ":")) if labels is not None else row[4]
                new_assignee = assignee.strip() if assignee is not None else row[5]
                new_milestone = milestone.strip() if milestone is not None else row[6]
                new_linked = linked_task_id.strip() if linked_task_id is not None else row[7]
                new_details = json.dumps(details, separators=(",", ":")) if details is not None else row[8]

                with con:
                    con.execute(
                        """
                        UPDATE agent_board_items SET
                            status = ?, priority = ?, labels_json = ?,
                            assignee = ?, milestone = ?, linked_task_id = ?,
                            details_json = ?, updated_at = ?
                        WHERE item_id = ?
                        """,
                        (new_status, new_priority, new_labels, new_assignee, new_milestone, new_linked, new_details, now, item_id),
                    )
            finally:
                con.close()
        return {
            "success": True,
            "item_id": item_id,
            "status": new_status,
            "updated_at": now,
            "item": {
                "item_id": item_id,
                "title": row[1] if row else "",
                "status": new_status,
                "priority": new_priority,
                "assignee": new_assignee,
                "milestone": new_milestone,
                "linked_task_id": new_linked,
                "updated_at": now,
            },
        }

    def item_get(self, item_id: str) -> dict[str, Any]:
        self._ensure_schema()
        with self._lock:
            con = self._connect()
            try:
                con.row_factory = sqlite3.Row
                row = con.execute("SELECT * FROM agent_board_items WHERE item_id = ?", (item_id,)).fetchone()
                if row is None:
                    return {"success": False, "error": f"item '{item_id}' not found"}
                item = dict(row)
                item["labels"] = json.loads(item.pop("labels_json", "[]"))
                item["details"] = json.loads(item.pop("details_json", "{}"))
                return {"success": True, "item": item}
            finally:
                con.close()

    def item_delete(self, item_id: str) -> dict[str, Any]:
        self._ensure_schema()
        with self._lock:
            con = self._connect()
            try:
                with con:
                    cursor = con.execute("DELETE FROM agent_board_items WHERE item_id = ?", (item_id,))
                    deleted = cursor.rowcount > 0
            finally:
                con.close()
        return {"success": True, "deleted": deleted, "item_id": item_id}

    def item_list(
        self,
        status: str | None = None,
        priority: str | None = None,
        milestone: str | None = None,
        assignee: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        self._ensure_schema()
        query = "SELECT * FROM agent_board_items WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status.lower())
        if priority:
            query += " AND priority = ?"
            params.append(priority.lower())
        if milestone:
            query += " AND milestone = ?"
            params.append(milestone)
        if assignee:
            query += " AND assignee = ?"
            params.append(assignee)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(min(max(1, limit), 200))

        with self._lock:
            con = self._connect()
            try:
                con.row_factory = sqlite3.Row
                rows = con.execute(query, params).fetchall()
                items = []
                for r in rows:
                    item = dict(r)
                    item["labels"] = json.loads(item.pop("labels_json", "[]"))
                    item["details"] = json.loads(item.pop("details_json", "{}"))
                    items.append(item)
                return {"success": True, "items": items, "count": len(items), "total": len(items)}
            finally:
                con.close()

    def summary(self) -> dict[str, Any]:
        self._ensure_schema()
        with self._lock:
            con = self._connect()
            try:
                rows = con.execute("SELECT status, count(*) FROM agent_board_items GROUP BY status").fetchall()
                counts = {r[0]: r[1] for r in rows}
                con.row_factory = sqlite3.Row
                blocked_rows = con.execute(
                    "SELECT item_id, title, priority, assignee FROM agent_board_items WHERE status = 'blocked' LIMIT 10"
                ).fetchall()
                blocked = [dict(r) for r in blocked_rows]
                status_counts = {
                    "planned": counts.get("planned", 0),
                    "in_progress": counts.get("in_progress", 0),
                    "done": counts.get("done", 0),
                    "blocked": counts.get("blocked", 0),
                    "cancelled": counts.get("cancelled", 0),
                    "total": sum(counts.values()),
                }
                return {
                    "success": True,
                    "counts": status_counts,
                    "by_status": status_counts,
                    "total_items": sum(counts.values()),
                    "blocked_items": blocked,
                }
            finally:
                con.close()

    def milestone_create(self, name: str, target_date: str = "", description: str = "") -> dict[str, Any]:
        self._ensure_schema()
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("milestone name must be a non-empty string")
        now = time.time()
        with self._lock:
            con = self._connect()
            try:
                with con:
                    con.execute(
                        """
                        INSERT INTO agent_milestones (name, target_date, description, created_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(name) DO UPDATE SET
                            target_date = excluded.target_date,
                            description = excluded.description
                        """,
                        (clean_name, target_date.strip(), description.strip(), now),
                    )
            finally:
                con.close()
        return {"success": True, "milestone": {"name": clean_name, "target_date": target_date, "description": description}}

    def milestone_status(self, name: str) -> dict[str, Any]:
        self._ensure_schema()
        clean_name = str(name).strip()
        with self._lock:
            con = self._connect()
            try:
                m_row = con.execute("SELECT * FROM agent_milestones WHERE name = ?", (clean_name,)).fetchone()
                rows = con.execute(
                    "SELECT status, count(*) FROM agent_board_items WHERE milestone = ? GROUP BY status",
                    (clean_name,),
                ).fetchall()
                counts = {r[0]: r[1] for r in rows}
                total = sum(counts.values())
                done = counts.get("done", 0)
                progress_pct = round((done / total * 100), 1) if total > 0 else 0.0
                return {
                    "success": True,
                    "milestone": clean_name,
                    "exists": m_row is not None,
                    "target_date": m_row[1] if m_row else "",
                    "total": total,
                    "total_items": total,
                    "done": done,
                    "done_items": done,
                    "in_progress": counts.get("in_progress", 0),
                    "planned": counts.get("planned", 0),
                    "blocked": counts.get("blocked", 0),
                    "progress_percent": progress_pct,
                    "progress_percentage": progress_pct,
                }
            finally:
                con.close()

    def session_briefing(self, include: list[str] | None = None, root: str = "") -> dict[str, Any]:
        """Aggregate high-level project briefing for newly started agents."""
        inc = set(include) if include else {"board", "active_tasks", "semaphores"}
        briefing: dict[str, Any] = {"success": True, "timestamp": time.time()}

        if "board" in inc:
            summ = self.summary()
            recent = self.item_list(limit=5).get("items", [])
            briefing["board"] = {
                "summary": summ,
                "recent_items": recent,
            }
            briefing["board_summary"] = summ

        if "active_tasks" in inc and self.services is not None and getattr(self.services, "task_store", None):
            try:
                active = self.services.task_store.list_tasks(status=None, limit=5)
                briefing["active_tasks"] = [
                    {
                        "task_id": t.get("task_id"),
                        "goal": t.get("contract", {}).get("goal", ""),
                        "status": t.get("status"),
                        "phase": t.get("checkpoint", {}).get("phase", ""),
                    }
                    for t in active if isinstance(t, dict) and t.get("status") in {"planned", "in_progress", "ready"}
                ]
            except Exception as exc:
                logger.warning("session_briefing active_tasks failed: %s", exc)

        if "semaphores" in inc and self.services is not None and getattr(self.services, "semaphores", None):
            try:
                briefing["semaphores"] = self.services.semaphores.status()
            except Exception as exc:
                logger.warning("session_briefing semaphores failed: %s", exc)

        return briefing
