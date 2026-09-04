from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, retry_busy


class WorkspaceMemoryStore:
    """Small shared, TTL-bounded handoff memo store for concurrent agents.

    This intentionally stores only data agents explicitly write to it. It is not an
    automatic conversation logger and is not used as hidden long-term memory.
    """

    def __init__(self, state_dir: Path, default_ttl_hours: int = 168, max_value_chars: int = 6000):
        self.path = state_dir / "workspace_memory.sqlite3"
        self.default_ttl = max(3600, int(default_ttl_hours) * 3600)
        self.max_value_chars = max(512, int(max_value_chars))
        state_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=0.75)

    def _init_db(self) -> None:
        with closing(self._connect()) as con:
            initialize_wal(con)
            con.execute(
                """CREATE TABLE IF NOT EXISTS memos (
                    workspace TEXT NOT NULL,
                    memo_key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    tenant TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    PRIMARY KEY(workspace, memo_key)
                )"""
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_memos_expiry ON memos(expires_at)")
            con.commit()

    @staticmethod
    def workspace_id(root: str) -> str:
        resolved = str(Path(root).expanduser().resolve())
        digest = hashlib.sha1(resolved.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
        return f"{Path(resolved).name}-{digest}"

    @staticmethod
    def _clean_key(key: str) -> str:
        key = " ".join(str(key).strip().split())
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
        tenant: str,
        *,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workspace = self.workspace_id(root)
        key = self._clean_key(key)
        value = str(value).strip()
        if not value:
            raise ValueError("memo value must not be empty")
        truncated = len(value) > self.max_value_chars
        if truncated:
            value = value[: self.max_value_chars] + "\n[... memo truncated ...]"
        ttl = self.default_ttl if ttl_seconds is None else max(300, min(int(ttl_seconds), 30 * 86400))
        now = time.time()
        meta = metadata if isinstance(metadata, dict) else {}
        def write() -> None:
            with closing(self._connect()) as con:
                self._purge(con)
                con.execute(
                    "INSERT OR REPLACE INTO memos(workspace,memo_key,value,tenant,metadata,updated_at,expires_at) VALUES(?,?,?,?,?,?,?)",
                    (workspace, key, value, tenant, json.dumps(meta, ensure_ascii=False), now, now + ttl),
                )
                con.commit()
        retry_busy(write, retries=4)
        return {"success": True, "workspace": workspace, "key": key, "truncated": truncated, "expires_in_seconds": ttl}

    def get(self, root: str, key: str) -> dict[str, Any]:
        workspace = self.workspace_id(root)
        key = self._clean_key(key)
        now = time.time()
        def read():
            with closing(self._connect()) as con:
                return con.execute(
                    "SELECT value,tenant,metadata,updated_at,expires_at FROM memos WHERE workspace=? AND memo_key=? AND expires_at>?",
                    (workspace, key, now),
                ).fetchone()
        row = retry_busy(read, retries=3)
        if not row:
            return {"success": False, "error": "memo not found", "workspace": workspace, "key": key}
        return {
            "success": True,
            "workspace": workspace,
            "key": key,
            "value": row[0],
            "tenant": row[1],
            "metadata": json.loads(row[2] or "{}"),
            "updated_at": row[3],
            "expires_at": row[4],
        }

    def search(self, root: str, query: str = "", limit: int = 12) -> dict[str, Any]:
        workspace = self.workspace_id(root)
        terms = [x.lower() for x in str(query).split() if len(x) >= 2][:12]
        limit = max(1, min(int(limit), 50))
        now = time.time()
        def read():
            with closing(self._connect()) as con:
                return con.execute(
                    "SELECT memo_key,value,tenant,metadata,updated_at,expires_at FROM memos WHERE workspace=? AND expires_at>? ORDER BY updated_at DESC LIMIT 200",
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
                "key": row[0], "value": row[1], "tenant": row[2],
                "metadata": json.loads(row[3] or "{}"), "updated_at": row[4], "expires_at": row[5], "score": score,
            })
        items.sort(key=lambda x: (-x["score"], -x["updated_at"]))
        return {"success": True, "workspace": workspace, "results": items[:limit]}

    def delete(self, root: str, key: str, tenant: str = "") -> dict[str, Any]:
        workspace = self.workspace_id(root)
        key = self._clean_key(key)
        def write() -> int:
            with closing(self._connect()) as con:
                if tenant:
                    cur = con.execute("DELETE FROM memos WHERE workspace=? AND memo_key=? AND tenant=?", (workspace, key, tenant))
                else:
                    cur = con.execute("DELETE FROM memos WHERE workspace=? AND memo_key=?", (workspace, key))
                con.commit()
                return int(cur.rowcount or 0)
        deleted = retry_busy(write, retries=4)
        return {"success": True, "workspace": workspace, "key": key, "deleted": deleted > 0}
