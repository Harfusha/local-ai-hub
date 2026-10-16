from __future__ import annotations

from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error, quick_sanity_check


def _clean_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    raw = str(value).replace("\x00", "")
    return raw.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _safe_positive_int(value: Any, default: int, *, minimum: int = 1) -> int:
    if value is None or isinstance(value, bool):
        return max(minimum, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return max(minimum, default)
    return max(minimum, parsed)


def _resolve_root(root: Any) -> str:
    cleaned = _clean_text(root).strip()
    if not cleaned:
        return ""
    try:
        return str(Path(cleaned).expanduser().resolve())
    except (OSError, ValueError):
        return ""


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
        raw_cfg = config.get("learning") if isinstance(config, Mapping) else {}
        cfg = raw_cfg if isinstance(raw_cfg, Mapping) else {}
        self.enabled = bool(cfg.get("enabled", True))
        self.max_queries = _safe_positive_int(cfg.get("max_queries_per_project", 64), 64, minimum=8)
        self.max_query_chars = _safe_positive_int(cfg.get("max_query_chars", 240), 240, minimum=64)
        self.db_path = Path(config["server"]["state_dir"]) / "learning.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.db_path, timeout_seconds=5.0, row_factory=sqlite3.Row)

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
                if not quick_sanity_check(con):
                    raise sqlite3.DatabaseError("learning sanity check failed")
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
        lower = _clean_text(query).lower()
        return next((name for name, terms in cls.INTENT_TERMS if any(term in lower for term in terms)), "general")

    def record(self, root: str, query: str) -> None:
        if not self.enabled:
            return
        resolved = _resolve_root(root)
        if not resolved:
            return
        clean = " ".join(_clean_text(query).split())[: self.max_query_chars]
        if len(clean) < 6:
            return
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
        resolved = _resolve_root(root)
        if not resolved:
            return []
        safe_limit = min(_safe_positive_int(limit, 12, minimum=1), self.max_queries)
        try:
            with self._lock, closing(self._connect()) as con:
                rows = con.execute(
                    "SELECT query FROM intents WHERE root=? ORDER BY hits DESC,last_seen DESC LIMIT ?",
                    (resolved, safe_limit),
                ).fetchall()
            return [str(row["query"]) for row in rows]
        except sqlite3.DatabaseError:
            return []

    def count(self, root: str | None = None) -> int:
        try:
            with self._lock, closing(self._connect()) as con:
                if root is not None:
                    resolved = _resolve_root(root)
                    if not resolved:
                        return 0
                    row = con.execute("SELECT COUNT(*) FROM intents WHERE root=?", (resolved,)).fetchone()
                else:
                    row = con.execute("SELECT COUNT(*) FROM intents").fetchone()
            return int(row[0]) if row else 0
        except sqlite3.DatabaseError:
            return 0

    def clear(self, root: str | None = None) -> None:
        try:
            with self._lock, closing(self._connect()) as con:
                if root is not None:
                    resolved = _resolve_root(root)
                    if not resolved:
                        return
                    con.execute("DELETE FROM intents WHERE root=?", (resolved,))
                else:
                    con.execute("DELETE FROM intents")
                con.commit()
        except sqlite3.DatabaseError:
            pass

    def stats(self) -> dict[str, Any]:
        try:
            with self._lock, closing(self._connect()) as con:
                total = int(con.execute("SELECT COUNT(*) FROM intents").fetchone()[0])
                projects = int(con.execute("SELECT COUNT(DISTINCT root) FROM intents").fetchone()[0])
            return {"enabled": self.enabled, "intents": total, "projects": projects, "healthy": True}
        except sqlite3.DatabaseError:
            return {"enabled": self.enabled, "intents": 0, "projects": 0, "healthy": False}
