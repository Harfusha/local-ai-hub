from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error


class UsageLearner:
    """Metadata-only project demand model for idle preprocessing priority.

    No prompt bodies, source code, or model responses are stored here. Only short
    normalized query labels, intent buckets and counters are retained.
    """

    INTENT_TERMS = (
        ("security", ("auth", "security", "permission", "token", "csrf", "xss")),
        ("tests", ("test", "phpunit", "pytest", "spec", "lint", "static")),
        ("database", ("sql", "database", "migration", "schema", "repository")),
        ("api", ("api", "route", "controller", "endpoint")),
        ("concurrency", ("thread", "async", "queue", "lock", "race", "worker")),
        ("architecture", ("architecture", "design", "dependency", "module", "flow")),
        ("bug", ("bug", "fail", "error", "exception", "crash", "fix")),
    )

    def __init__(self, config: dict[str, Any]):
        cfg = config.get("learning", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.max_queries = max(8, int(cfg.get("max_queries_per_project", 64)))
        self.max_query_chars = max(64, int(cfg.get("max_query_chars", 240)))
        self.db_path = Path(config["server"]["state_dir"]) / "learning.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.db_path, timeout_seconds=0.75, row_factory=sqlite3.Row)

    def _create_schema(self) -> None:
        with self._lock, closing(self._connect()) as con:
            initialize_wal(con)
            con.execute(
                """CREATE TABLE IF NOT EXISTS intents(
                    root TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    query TEXT NOT NULL,
                    hits INTEGER NOT NULL,
                    last_seen REAL NOT NULL,
                    PRIMARY KEY(root,intent,query)
                )"""
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_intents_hot ON intents(root,hits DESC,last_seen DESC)")
            con.commit()

    def _init_db(self) -> None:
        try:
            self._create_schema()
            with self._lock, closing(self._connect()) as con:
                row = con.execute("PRAGMA quick_check").fetchone()
                if row and row[0] != "ok":
                    raise sqlite3.DatabaseError("learning quick_check failed")
        except sqlite3.DatabaseError as exc:
            if is_busy_error(exc):
                return
            stamp = int(time.time())
            try:
                if self.db_path.exists():
                    self.db_path.replace(self.db_path.with_name(self.db_path.name + f".corrupt-{stamp}"))
            except OSError:
                pass
            self._create_schema()

    @classmethod
    def intent(cls, query: str) -> str:
        lower = query.lower()
        return next((name for name, terms in cls.INTENT_TERMS if any(term in lower for term in terms)), "general")

    def record(self, root: str, query: str) -> None:
        if not self.enabled:
            return
        clean = " ".join(query.split())[: self.max_query_chars]
        if len(clean) < 6:
            return
        resolved = str(Path(root).expanduser().resolve())
        intent = self.intent(clean)
        try:
            with self._lock, closing(self._connect()) as con:
                con.execute(
                    """INSERT INTO intents(root,intent,query,hits,last_seen) VALUES(?,?,?,?,?)
                       ON CONFLICT(root,intent,query) DO UPDATE SET hits=hits+1,last_seen=excluded.last_seen""",
                    (resolved, intent, clean, 1, time.time()),
                )
                # Bound each project independently.
                con.execute(
                    """DELETE FROM intents WHERE rowid IN (
                         SELECT rowid FROM intents WHERE root=? ORDER BY hits DESC,last_seen DESC LIMIT -1 OFFSET ?
                       )""",
                    (resolved, self.max_queries),
                )
                con.commit()
        except sqlite3.DatabaseError:
            # Learning must never block foreground retrieval.
            return

    def hot_queries(self, root: str, limit: int = 12) -> list[str]:
        resolved = str(Path(root).expanduser().resolve())
        try:
            with self._lock, closing(self._connect()) as con:
                rows = con.execute(
                    "SELECT query FROM intents WHERE root=? ORDER BY hits DESC,last_seen DESC LIMIT ?",
                    (resolved, min(max(1, int(limit)), self.max_queries)),
                ).fetchall()
            return [str(row["query"]) for row in rows]
        except sqlite3.DatabaseError:
            return []

    def stats(self) -> dict[str, Any]:
        try:
            with self._lock, closing(self._connect()) as con:
                total = int(con.execute("SELECT COUNT(*) FROM intents").fetchone()[0])
                projects = int(con.execute("SELECT COUNT(DISTINCT root) FROM intents").fetchone()[0])
            return {"enabled": self.enabled, "intents": total, "projects": projects, "healthy": True}
        except sqlite3.DatabaseError:
            return {"enabled": self.enabled, "intents": 0, "projects": 0, "healthy": False}
