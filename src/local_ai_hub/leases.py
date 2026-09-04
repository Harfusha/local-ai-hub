from __future__ import annotations

import hashlib
import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, retry_busy


def _norm_rel(value: str) -> str:
    normalized = value.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized or ".")
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"lease path must be repository-relative: {value}")
    return "." if str(path) == "." else str(path)


def _overlap(a: str, b: str) -> bool:
    na = a.replace("\\", "/").rstrip("/")
    nb = b.replace("\\", "/").rstrip("/")
    if os.name == "nt":
        na = na.lower()
        nb = nb.lower()
    if na == nb:
        return True
    return na.startswith(nb + "/") or nb.startswith(na + "/")


class ScopeLeaseStore:
    """Advisory cross-agent write-scope leases for avoiding obvious concurrent edit collisions."""

    def __init__(self, state_dir: Path):
        self.path = state_dir / "leases.sqlite3"
        state_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=0.75, isolation_level=None)

    def _init_db(self) -> None:
        with closing(self._connect()) as con:
            initialize_wal(con)
            con.execute(
                """CREATE TABLE IF NOT EXISTS leases (
                    lease_id TEXT NOT NULL,
                    tenant TEXT NOT NULL,
                    root_id TEXT NOT NULL,
                    root_path TEXT NOT NULL,
                    path TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    PRIMARY KEY(lease_id, path)
                )"""
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_leases_root ON leases(root_id, expires_at)")

    @staticmethod
    def _root(root: str) -> tuple[str, str]:
        resolved = str(Path(root).expanduser().resolve())
        root_id = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:20]
        return resolved, root_id

    def claim(self, tenant: str, root: str, paths: list[str], ttl_seconds: int = 900, purpose: str = "agent edit") -> dict[str, Any]:
        if not paths:
            return {"success": False, "error": "paths must not be empty"}
        rels = sorted({_norm_rel(str(p)) for p in paths})
        root_path, root_id = self._root(root)
        now = time.time()
        expires = now + max(30, min(int(ttl_seconds), 7200))
        lease_id = f"lease_{uuid.uuid4().hex[:20]}"
        def write() -> dict[str, Any]:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                con.execute("DELETE FROM leases WHERE expires_at <= ?", (now,))
                existing = con.execute(
                    "SELECT lease_id,tenant,path,purpose,expires_at FROM leases WHERE root_id=? AND tenant<>?",
                    (root_id, tenant),
                ).fetchall()
                conflicts = []
                for requested in rels:
                    for row in existing:
                        if _overlap(requested, row[2]):
                            conflicts.append({
                                "requested": requested, "held_path": row[2], "tenant": row[1],
                                "lease_id": row[0], "purpose": row[3], "expires_at": row[4],
                            })
                if conflicts:
                    con.execute("ROLLBACK")
                    return {"success": False, "error": "write scope overlaps another active agent lease", "conflicts": conflicts}
                con.executemany(
                    "INSERT INTO leases(lease_id,tenant,root_id,root_path,path,purpose,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)",
                    [(lease_id, tenant, root_id, root_path, p, purpose[:300], now, expires) for p in rels],
                )
                con.execute("COMMIT")
                return {"success": True, "lease_id": lease_id, "root": root_path, "paths": rels, "expires_at": expires}
        return retry_busy(write, retries=4)

    def release(self, tenant: str, lease_id: str = "") -> dict[str, Any]:
        def write() -> int:
            with closing(self._connect()) as con:
                if lease_id:
                    cur = con.execute("DELETE FROM leases WHERE tenant=? AND lease_id=?", (tenant, lease_id))
                else:
                    cur = con.execute("DELETE FROM leases WHERE tenant=?", (tenant,))
                return int(cur.rowcount or 0)
        return {"success": True, "released_rows": retry_busy(write, retries=4)}

    def list(self, root: str = "") -> list[dict[str, Any]]:
        now = time.time()
        def read():
            with closing(self._connect()) as con:
                if root:
                    _, root_id = self._root(root)
                    return con.execute(
                        "SELECT lease_id,tenant,root_path,path,purpose,expires_at FROM leases WHERE root_id=? AND expires_at>? ORDER BY expires_at",
                        (root_id, now),
                    ).fetchall()
                return con.execute(
                    "SELECT lease_id,tenant,root_path,path,purpose,expires_at FROM leases WHERE expires_at>? ORDER BY expires_at",
                    (now,),
                ).fetchall()
        rows = retry_busy(read, retries=3)
        return [
            {"lease_id": r[0], "tenant": r[1], "root": r[2], "path": r[3], "purpose": r[4], "expires_at": r[5]}
            for r in rows
        ]
