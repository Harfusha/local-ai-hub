from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, retry_busy
from .process_utils import canonical_root

def _clean_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    raw = str(value).replace("\x00", "")
    return raw.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _safe_positive_int(
    value: Any,
    default: int,
    *,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    if value is None or isinstance(value, bool):
        parsed = max(minimum, default)
    else:
        try:
            parsed = max(minimum, int(value))
        except (TypeError, ValueError, OverflowError):
            parsed = max(minimum, default)
    if maximum is not None:
        return min(parsed, maximum)
    return parsed


def _safe_metadata_dict(raw: Any) -> dict[str, Any]:
    if not raw or not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class WorkspaceMemoryStore:
    """Small shared, TTL-bounded handoff memo store for concurrent agents.

    This intentionally stores only data agents explicitly write to it. It is not an
    automatic conversation logger and is not used as hidden long-term memory.

    Memos are shared by every local agent using the same canonical workspace and
    key. A later write replaces the earlier value unless a writer supplies an
    expected version to reject stale replacement. Compact per-key version rows
    remain after deletion so stale writers cannot recreate older generations.
    """

    def __init__(self, state_dir: Path, default_ttl_hours: int = 168, max_value_chars: int = 6000):
        self.path = state_dir / "workspace_memory.sqlite3"
        hours = _safe_positive_int(default_ttl_hours, 168, minimum=1)
        self.default_ttl = max(3600, hours * 3600)
        self.max_value_chars = _safe_positive_int(max_value_chars, 6000, minimum=512)
        self._lock = threading.RLock()
        self._initialized = False
        state_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=0.75)

    def _init_db(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return

            expected_memos = (
                ("workspace", "TEXT", 1, 1), ("memo_key", "TEXT", 1, 2),
                ("value", "TEXT", 1, 0), ("metadata", "TEXT", 1, 0),
                ("updated_at", "REAL", 1, 0), ("expires_at", "REAL", 1, 0),
                ("version", "INTEGER", 1, 0),
            )
            expected_versions = (
                ("workspace", "TEXT", 1, 1), ("memo_key", "TEXT", 1, 2),
                ("version", "INTEGER", 1, 0),
            )

            def table_shape(con: sqlite3.Connection, table: str):
                if not con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone():
                    return None
                return tuple(
                    (str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5]))
                    for row in con.execute(f"PRAGMA table_info({table})")
                )

            if self.path.exists() and self.path.stat().st_size:
                uri = f"{self.path.resolve().as_uri()}?mode=ro"
                try:
                    with closing(sqlite3.connect(uri, uri=True, timeout=5.0)) as read_only:
                        tables = {
                            str(row[0])
                            for row in read_only.execute(
                                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                            )
                        }
                        if tables - {"memos", "memo_versions"}:
                            raise RuntimeError(
                                "workspace memo schema requires explicit offline conversion; original data preserved"
                            )
                        memo_shape = table_shape(read_only, "memos")
                        version_shape = table_shape(read_only, "memo_versions")
                        if (memo_shape is None) != (version_shape is None) or (
                            memo_shape is not None
                            and (memo_shape != expected_memos or version_shape != expected_versions)
                        ):
                            raise RuntimeError(
                                "workspace memo schema requires explicit offline conversion; original data preserved"
                            )
                        if memo_shape is not None:
                            deadline = time.monotonic() + 0.5
                            read_only.set_progress_handler(
                                lambda: int(time.monotonic() >= deadline), 1000
                            )
                            try:
                                missing_generation = read_only.execute(
                                    """SELECT 1 FROM memos AS m
                                       LEFT JOIN memo_versions AS v
                                         ON v.workspace=m.workspace AND v.memo_key=m.memo_key
                                       WHERE v.memo_key IS NULL LIMIT 1"""
                                ).fetchone()
                            except sqlite3.OperationalError as exc:
                                if "interrupt" in str(exc).lower():
                                    raise RuntimeError(
                                        "workspace memo generation preflight timed out; original data preserved"
                                    ) from exc
                                raise
                            finally:
                                read_only.set_progress_handler(None, 0)
                            if missing_generation:
                                raise RuntimeError(
                                    "workspace memo generations require explicit offline conversion; original data preserved"
                                )
                except sqlite3.DatabaseError as exc:
                    raise RuntimeError(
                        "workspace memo database cannot be safely inspected; original database and sidecars preserved"
                    ) from exc

            def _setup() -> None:
                with closing(self._connect()) as con:
                    initialize_wal(con)
                    con.execute("BEGIN IMMEDIATE")
                    con.execute(
                        """CREATE TABLE IF NOT EXISTS memos (
                            workspace TEXT NOT NULL,
                            memo_key TEXT NOT NULL,
                            value TEXT NOT NULL,
                            metadata TEXT NOT NULL,
                            updated_at REAL NOT NULL,
                            expires_at REAL NOT NULL,
                            version INTEGER NOT NULL DEFAULT 1,
                            PRIMARY KEY(workspace, memo_key)
                        )"""
                    )
                    con.execute(
                        """CREATE TABLE IF NOT EXISTS memo_versions (
                            workspace TEXT NOT NULL,
                            memo_key TEXT NOT NULL,
                            version INTEGER NOT NULL,
                            PRIMARY KEY(workspace, memo_key)
                        )"""
                    )
                    con.execute("CREATE INDEX IF NOT EXISTS idx_memos_expiry ON memos(expires_at)")
                    con.commit()
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    @staticmethod
    def workspace_id(root: str) -> str:
        resolved = canonical_root(root)
        digest = hashlib.sha1(resolved.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
        return f"{Path(resolved).name}-{digest}"

    @staticmethod
    def _clean_key(key: str) -> str:
        if not isinstance(key, str):
            raise ValueError("memo key must be a string")
        key = " ".join(_clean_text(key).strip().split())
        if not key or len(key) > 160:
            raise ValueError("memo key must be 1..160 characters")
        return key

    def _purge(self, con: sqlite3.Connection) -> None:
        con.execute("DELETE FROM memos WHERE expires_at <= ?", (time.time(),))

    def put(
        self,
        root: str,
        key: str,
        value: str,
        *,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        workspace = self.workspace_id(root)
        key = self._clean_key(key)
        if not isinstance(value, str):
            raise ValueError("memo value must be a string")
        value = _clean_text(value).strip()
        if not value:
            raise ValueError("memo value must not be empty")
        if expected_version is not None and (type(expected_version) is not int or expected_version < 0):
            raise ValueError("memo expected_version must be a non-negative integer")
        truncated = len(value) > self.max_value_chars
        if truncated:
            value = value[: self.max_value_chars] + "\n[... memo truncated ...]"
        ttl = (
            self.default_ttl
            if ttl_seconds is None
            else _safe_positive_int(ttl_seconds, self.default_ttl, minimum=300, maximum=30 * 86400)
        )
        now = time.time()
        meta = metadata if isinstance(metadata, dict) else {}
        if "tenant" in meta:
            raise ValueError("memo metadata field 'tenant' is retired")
        meta_json = _clean_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":"), default=str))
        def write() -> int | dict[str, Any]:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                self._purge(con)
                row = con.execute(
                    "SELECT version FROM memo_versions WHERE workspace=? AND memo_key=?",
                    (workspace, key),
                ).fetchone()
                current_version = int(row[0]) if row else 0
                if expected_version is not None and current_version != expected_version:
                    con.rollback()
                    return {
                        "success": False,
                        "error": "memo version conflict",
                        "version_conflict": True,
                        "workspace": workspace,
                        "key": key,
                        "scope": "workspace-shared",
                        "expected_version": expected_version,
                        "current_version": current_version,
                    }
                con.execute(
                    """INSERT INTO memo_versions(workspace,memo_key,version) VALUES(?,?,?)
                       ON CONFLICT(workspace,memo_key) DO UPDATE SET version=excluded.version""",
                    (workspace, key, current_version + 1),
                )
                version = current_version + 1
                con.execute(
                    """INSERT INTO memos(workspace,memo_key,value,metadata,updated_at,expires_at,version)
                       VALUES(?,?,?,?,?,?,?)
                       ON CONFLICT(workspace,memo_key) DO UPDATE SET
                           value=excluded.value, metadata=excluded.metadata,
                           updated_at=excluded.updated_at, expires_at=excluded.expires_at,
                           version=excluded.version""",
                    (workspace, key, value, meta_json, now, now + ttl, version),
                )
                con.commit()
                return version
        result = retry_busy(write, retries=4)
        if isinstance(result, dict):
            return result
        return {
            "success": True,
            "workspace": workspace,
            "key": key,
            "scope": "workspace-shared",
            "truncated": truncated,
            "expires_in_seconds": ttl,
            "version": result,
        }

    def get(self, root: str, key: str) -> dict[str, Any]:
        workspace = self.workspace_id(root)
        key = self._clean_key(key)
        now = time.time()
        def read():
            with closing(self._connect()) as con:
                con.execute("BEGIN")
                row = con.execute(
                    "SELECT value,metadata,updated_at,expires_at,version FROM memos WHERE workspace=? AND memo_key=? AND expires_at>?",
                    (workspace, key, now),
                ).fetchone()
                generation = con.execute(
                    "SELECT version FROM memo_versions WHERE workspace=? AND memo_key=?",
                    (workspace, key),
                ).fetchone()
                con.commit()
                return row, (int(generation[0]) if generation else 0)
        row, current_version = retry_busy(read, retries=3)
        if not row:
            return {"success": False, "error": "memo not found", "workspace": workspace, "key": key, "scope": "workspace-shared", "version": current_version}
        return {
            "success": True,
            "workspace": workspace,
            "key": key,
            "scope": "workspace-shared",
            "value": row[0],
            "metadata": _safe_metadata_dict(row[1]),
            "updated_at": row[2],
            "expires_at": row[3],
            "version": int(row[4]),
        }

    def search(self, root: str, query: str = "", limit: int = 12) -> dict[str, Any]:
        workspace = self.workspace_id(root)
        terms = [x.lower() for x in _clean_text(query).split() if len(x) >= 2][:12]
        safe_limit = _safe_positive_int(limit, 12, minimum=1, maximum=50)
        now = time.time()
        def read():
            with closing(self._connect()) as con:
                return con.execute(
                    "SELECT memo_key,value,metadata,updated_at,expires_at,version FROM memos WHERE workspace=? AND expires_at>? ORDER BY updated_at DESC LIMIT 200",
                    (workspace, now),
                ).fetchall()
        rows = retry_busy(read, retries=3)
        items = []
        for row in rows:
            hay = f"{row[0]}\n{row[1]}".lower()
            score = sum(1 for t in terms if t in hay)
            if terms and score == 0:
                continue
            items.append({
                "key": row[0], "value": row[1],
                "scope": "workspace-shared",
                "metadata": _safe_metadata_dict(row[2]), "updated_at": row[3], "expires_at": row[4], "score": score,
                "version": int(row[5]),
            })
        items.sort(key=lambda x: (-x["score"], -x["updated_at"]))
        return {"success": True, "workspace": workspace, "scope": "workspace-shared", "results": items[:safe_limit]}

    def delete(self, root: str, key: str) -> dict[str, Any]:
        workspace = self.workspace_id(root)
        key = self._clean_key(key)
        def write() -> tuple[int, int]:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                row = con.execute(
                    "SELECT version FROM memos WHERE workspace=? AND memo_key=?",
                    (workspace, key),
                ).fetchone()
                if not row:
                    generation = con.execute(
                        "SELECT version FROM memo_versions WHERE workspace=? AND memo_key=?",
                        (workspace, key),
                    ).fetchone()
                    con.rollback()
                    return 0, (int(generation[0]) if generation else 0)
                current = con.execute(
                    "SELECT version FROM memo_versions WHERE workspace=? AND memo_key=?",
                    (workspace, key),
                ).fetchone()
                next_version = (int(current[0]) if current else int(row[0])) + 1
                cur = con.execute(
                    "DELETE FROM memos WHERE workspace=? AND memo_key=?", (workspace, key)
                )
                if cur.rowcount:
                    con.execute(
                        """INSERT INTO memo_versions(workspace,memo_key,version) VALUES(?,?,?)
                           ON CONFLICT(workspace,memo_key) DO UPDATE SET version=excluded.version""",
                        (workspace, key, next_version),
                    )
                con.commit()
                return int(cur.rowcount or 0), next_version
        deleted, version = retry_busy(write, retries=4)
        return {"success": True, "workspace": workspace, "key": key, "scope": "workspace-shared", "deleted": deleted > 0, "version": version}

    def count(self, root: str | None = None) -> int:
        now = time.time()
        def read() -> int:
            with closing(self._connect()) as con:
                if root is not None:
                    workspace = self.workspace_id(root)
                    row = con.execute(
                        "SELECT COUNT(*) FROM memos WHERE workspace=? AND expires_at>?",
                        (workspace, now),
                    ).fetchone()
                else:
                    row = con.execute(
                        "SELECT COUNT(*) FROM memos WHERE expires_at>?",
                        (now,),
                    ).fetchone()
                return int(row[0]) if row else 0
        try:
            return retry_busy(read, retries=3)
        except sqlite3.DatabaseError:
            return 0

    def clear(self, root: str | None = None) -> None:
        def write() -> None:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                if root is not None:
                    workspace = self.workspace_id(root)
                    con.execute("DELETE FROM memos WHERE workspace=?", (workspace,))
                else:
                    con.execute("DELETE FROM memos")
                con.commit()
        try:
            retry_busy(write, retries=3)
        except sqlite3.DatabaseError:
            pass
