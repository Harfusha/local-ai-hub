from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, retry_busy
from .process_utils import canonical_root


def _norm_rel(value: str, root: str = "") -> str:
    raw = str(value or "").strip()
    if root and (raw.startswith(("/", "\\")) or PureWindowsPath(raw).is_absolute() or bool(PureWindowsPath(raw).drive)):
        try:
            rel = Path(raw).resolve().relative_to(Path(root).resolve())
            raw = str(rel)
        except Exception:
            pass
    if raw.startswith(("/", "\\")):
        raise ValueError(f"lease path must be repository-relative: {value}")
    wp = PureWindowsPath(raw)
    if wp.is_absolute() or bool(wp.drive):
        raise ValueError(f"lease path must be repository-relative: {value}")
    normalized = raw.replace("\\", "/").strip("/")
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
        self._lock = threading.RLock()
        self._initialized = False
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=0.75, isolation_level=None)

    def _init_db(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            def _setup() -> None:
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
                    con.execute(
                        """CREATE TABLE IF NOT EXISTS lease_waits (
                            tenant TEXT NOT NULL,
                            blocked_by TEXT NOT NULL,
                            root_id TEXT NOT NULL,
                            requested_path TEXT NOT NULL,
                            updated_at REAL NOT NULL,
                            PRIMARY KEY(tenant, blocked_by, requested_path)
                        )"""
                    )
                    con.execute("CREATE INDEX IF NOT EXISTS idx_lease_waits_tenant ON lease_waits(tenant)")
                    con.execute("CREATE INDEX IF NOT EXISTS idx_lease_waits_blocked ON lease_waits(blocked_by)")
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    @staticmethod
    def _root(root: str) -> tuple[str, str]:
        resolved = canonical_root(root)
        root_id = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:20]
        return resolved, root_id

    def claim(self, tenant: str, root: str, paths: list[str], ttl_seconds: int = 900, purpose: str = "agent edit") -> dict[str, Any]:
        if not paths:
            return {"success": False, "error": "paths must not be empty"}
        root_path, root_id = self._root(root)
        rels = sorted({_norm_rel(str(p), root=root_path) for p in paths})
        now = time.time()
        expires = now + max(30, min(int(ttl_seconds), 7200))
        lease_id = f"lease_{uuid.uuid4().hex[:20]}"

        def write() -> dict[str, Any]:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                con.execute("DELETE FROM leases WHERE expires_at <= ?", (now,))
                con.execute("DELETE FROM lease_waits WHERE updated_at <= ?", (now - 7200,))
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
                    conflicting_tenants = {c["tenant"] for c in conflicts if c.get("tenant")}

                    # Build wait-for graph from persistent waits and proposed contention
                    wait_rows = con.execute(
                        "SELECT tenant, blocked_by FROM lease_waits WHERE root_id=? AND updated_at>?",
                        (root_id, now - 3600),
                    ).fetchall()
                    graph: dict[str, set[str]] = {}
                    for u, v in wait_rows:
                        graph.setdefault(u, set()).add(v)
                    for b in conflicting_tenants:
                        graph.setdefault(tenant, set()).add(b)

                    # Cycle detection via DFS
                    def detect_cycle(start_node: str) -> list[str] | None:
                        visited: set[str] = set()
                        stack: list[str] = []

                        def dfs(curr: str) -> list[str] | None:
                            visited.add(curr)
                            stack.append(curr)
                            for nxt in graph.get(curr, ()):
                                if nxt in stack:
                                    idx = stack.index(nxt)
                                    return stack[idx:] + [nxt]
                                if nxt not in visited:
                                    cyc = dfs(nxt)
                                    if cyc:
                                        return cyc
                            stack.pop()
                            return None

                        return dfs(start_node)

                    cycle = detect_cycle(tenant)
                    if cycle:
                        con.execute("ROLLBACK")
                        return {
                            "success": False,
                            "error": "deadlock detected in lease dependency graph",
                            "deadlock": True,
                            "cycle": cycle,
                            "conflicts": conflicts,
                        }

                    # No deadlock: record wait edges and return standard contention error
                    for c in conflicts:
                        con.execute(
                            "INSERT OR REPLACE INTO lease_waits(tenant, blocked_by, root_id, requested_path, updated_at) VALUES(?,?,?,?,?)",
                            (tenant, c["tenant"], root_id, c["requested"], now),
                        )
                    con.execute("COMMIT")
                    return {
                        "success": False,
                        "error": "write scope overlaps another active agent lease",
                        "deadlock": False,
                        "conflicts": conflicts,
                    }

                # Successfully acquire all requested paths atomically
                con.execute("DELETE FROM lease_waits WHERE tenant=?", (tenant,))
                con.executemany(
                    "INSERT INTO leases(lease_id,tenant,root_id,root_path,path,purpose,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)",
                    [(lease_id, tenant, root_id, root_path, p, purpose[:300], now, expires) for p in rels],
                )
                con.execute("COMMIT")
                return {"success": True, "lease_id": lease_id, "root": root_path, "paths": rels, "expires_at": expires}

        return retry_busy(write, retries=4)

    def claim_batch(self, tenant: str, root: str, paths: list[str], ttl_seconds: int = 900, purpose: str = "agent edit") -> dict[str, Any]:
        """Atomic multi-path batch lease claim with rollback and cycle detection."""
        return self.claim(tenant=tenant, root=root, paths=paths, ttl_seconds=ttl_seconds, purpose=purpose)

    def release(self, tenant: str, lease_id: str = "") -> dict[str, Any]:
        def write() -> int:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                paths_released: list[str] = []
                if lease_id:
                    p_rows = con.execute("SELECT path FROM leases WHERE lease_id=?", (lease_id,)).fetchall()
                    paths_released = [r[0] for r in p_rows]
                    if tenant in {"http-default", "system", "admin", "*"}:
                        cur = con.execute("DELETE FROM leases WHERE lease_id=?", (lease_id,))
                    else:
                        cur = con.execute("DELETE FROM leases WHERE lease_id=? AND (tenant=? OR tenant='http-default')", (lease_id, tenant))
                        if (cur.rowcount or 0) == 0 and not tenant:
                            cur = con.execute("DELETE FROM leases WHERE lease_id=?", (lease_id,))
                else:
                    cur = con.execute("DELETE FROM leases WHERE tenant=?", (tenant,))
                count = int(cur.rowcount or 0)
                # Clear wait dependencies involving this tenant when releasing leases
                if tenant:
                    if lease_id and paths_released:
                        placeholders = ",".join("?" for _ in paths_released)
                        con.execute(
                            f"DELETE FROM lease_waits WHERE blocked_by=? AND requested_path IN ({placeholders})",
                            (tenant, *paths_released),
                        )
                    elif not lease_id:
                        con.execute("DELETE FROM lease_waits WHERE tenant=? OR blocked_by=?", (tenant, tenant))
                con.execute("COMMIT")
                return count
        return {"success": True, "released_rows": retry_busy(write, retries=4)}

    def renew(self, tenant: str, lease_id: str, ttl_seconds: int = 900) -> dict[str, Any]:
        """Atomically extend the expiration TTL of an existing held lease."""
        if not lease_id:
            return {"success": False, "error": "lease_id is required"}
        now = time.time()
        new_expires = now + max(30, min(int(ttl_seconds), 7200))

        def write() -> dict[str, Any]:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                if tenant in {"http-default", "system", "admin", "*"}:
                    rows = con.execute(
                        "SELECT path FROM leases WHERE lease_id=? AND expires_at>?",
                        (lease_id, now),
                    ).fetchall()
                    if not rows:
                        con.execute("ROLLBACK")
                        return {"success": False, "error": "lease not found or expired"}
                    con.execute(
                        "UPDATE leases SET expires_at=? WHERE lease_id=?",
                        (new_expires, lease_id),
                    )
                else:
                    rows = con.execute(
                        "SELECT path FROM leases WHERE lease_id=? AND (tenant=? OR tenant='http-default') AND expires_at>?",
                        (lease_id, tenant, now),
                    ).fetchall()
                    if not rows:
                        con.execute("ROLLBACK")
                        return {"success": False, "error": "lease not found, expired, or belongs to another tenant"}
                    con.execute(
                        "UPDATE leases SET expires_at=? WHERE lease_id=? AND (tenant=? OR tenant='http-default')",
                        (new_expires, lease_id, tenant),
                    )
                con.execute("COMMIT")
                paths = [r[0] for r in rows]
                return {"success": True, "lease_id": lease_id, "expires_at": new_expires, "paths": paths}

        return retry_busy(write, retries=4)

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

    def waits(self, root: str = "") -> list[dict[str, Any]]:
        now = time.time()
        def read():
            with closing(self._connect()) as con:
                if root:
                    _, root_id = self._root(root)
                    return con.execute(
                        "SELECT tenant, blocked_by, requested_path, updated_at FROM lease_waits WHERE root_id=? AND updated_at>? ORDER BY updated_at DESC",
                        (root_id, now - 3600),
                    ).fetchall()
                return con.execute(
                    "SELECT tenant, blocked_by, requested_path, updated_at FROM lease_waits WHERE updated_at>? ORDER BY updated_at DESC",
                    (now - 3600,),
                ).fetchall()
        rows = retry_busy(read, retries=3)
        return [
            {"tenant": r[0], "blocked_by": r[1], "requested_path": r[2], "updated_at": r[3]}
            for r in rows
        ]
