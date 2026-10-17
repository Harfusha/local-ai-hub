from __future__ import annotations

import hashlib
import math
import ntpath
import os
import posixpath
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path, PureWindowsPath
from typing import Any

from .sqlite_support import (
    connect_sqlite,
    initialize_wal,
    require_canonical_agent_state_database,
    readonly_sqlite_connection,
    retry_busy,
    validate_durable_schema,
)

_COORDINATION_ID_UNSET = object()
from .process_utils import canonical_root

_LEASE_DURABLE_SCHEMA = {
    "leases": [
        ("lease_id", "TEXT", 1, 1), ("tenant", "TEXT", 1, 0),
        ("root_id", "TEXT", 1, 0), ("root_path", "TEXT", 1, 0),
        ("path", "TEXT", 1, 2), ("purpose", "TEXT", 1, 0),
        ("created_at", "REAL", 1, 0), ("expires_at", "REAL", 1, 0),
    ],
    "lease_waits": [
        ("tenant", "TEXT", 1, 2), ("blocked_by", "TEXT", 1, 3),
        ("root_id", "TEXT", 1, 1), ("requested_path", "TEXT", 1, 4),
        ("updated_at", "REAL", 1, 0),
    ],
}
_LEASE_REQUIRED_UNIQUE = {
    "leases": (("lease_id", "path"),),
    "lease_waits": (("root_id", "tenant", "blocked_by", "requested_path"),),
}
_LEASE_COMPLETE_GROUPS = (("leases", "lease_waits"),)


def _preflight_lease_schema(path: Path) -> None:
    """Check existing lease tables read-only before opening a writer connection."""
    if not path.is_file() or path.stat().st_size == 0:
        return
    with readonly_sqlite_connection(path) as con:
        validate_durable_schema(
            con,
            path,
            _LEASE_DURABLE_SCHEMA,
            complete_groups=_LEASE_COMPLETE_GROUPS,
            required_unique=_LEASE_REQUIRED_UNIQUE,
            backup_on_mismatch=False,
        )


def _norm_rel(value: str, root: str = "") -> str:
    if value is None or isinstance(value, bool):
        raise ValueError(f"lease path must be repository-relative: {value}")
    raw = str(value).strip()
    if not raw or "\x00" in raw:
        raise ValueError(f"lease path must be repository-relative: {value}")
    wp = PureWindowsPath(raw)
    win_rooted = wp.is_absolute() or bool(wp.drive) or raw.startswith("\\")
    if win_rooted:
        root_wp = PureWindowsPath(root)
        if not wp.is_absolute() or not root_wp.is_absolute():
            raise ValueError(f"lease path must be repository-relative: {value}")
        try:
            relative = wp.relative_to(root_wp)
        except ValueError as exc:
            raise ValueError(f"lease path must be repository-relative: {value}") from exc
        if os.name == "nt":
            try:
                Path(raw).resolve().relative_to(Path(root).resolve())
            except (OSError, ValueError) as exc:
                raise ValueError(f"lease path must be repository-relative: {value}") from exc
        raw = str(relative)
    elif raw.startswith("/"):
        root_wp = PureWindowsPath(root)
        if not root or root_wp.drive or root.startswith("\\"):
            raise ValueError(f"lease path must be repository-relative: {value}")
        try:
            raw = str(Path(raw).resolve().relative_to(Path(root).resolve()))
        except (OSError, ValueError) as exc:
            raise ValueError(f"lease path must be repository-relative: {value}") from exc
    elif Path(raw).is_absolute():
        raise ValueError(f"lease path must be repository-relative: {value}")
    normalized = raw.replace("\\", "/").strip("/")
    norm_path = posixpath.normpath(normalized or ".")
    if norm_path == ".":
        return "."
    if norm_path.startswith("..") or norm_path.startswith("/"):
        raise ValueError(f"lease path must be repository-relative: {value}")
    return norm_path


def _overlap(a: str, b: str) -> bool:
    na = a.replace("\\", "/").rstrip("/")
    nb = b.replace("\\", "/").rstrip("/")
    if os.name == "nt":
        na = na.lower()
        nb = nb.lower()
    if na == nb:
        return True
    return na.startswith(nb + "/") or nb.startswith(na + "/")


def _is_canonical_coordination_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and "\x00" not in value
        and len(value) <= 512
    )


class ScopeLeaseStore:
    """Advisory cross-agent write-scope leases for avoiding obvious concurrent edit collisions."""

    def __init__(self, state_dir: Path):
        self.path = require_canonical_agent_state_database(state_dir)
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
            _preflight_lease_schema(self.path)
            def _setup() -> None:
                with closing(self._connect()) as con:
                    validate_durable_schema(
                        con,
                        self.path,
                        _LEASE_DURABLE_SCHEMA,
                        complete_groups=_LEASE_COMPLETE_GROUPS,
                        required_unique=_LEASE_REQUIRED_UNIQUE,
                        backup_on_mismatch=False,
                    )
                    initialize_wal(con)
                    con.execute("BEGIN IMMEDIATE")
                    try:
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
                                PRIMARY KEY(root_id, tenant, blocked_by, requested_path)
                            )"""
                        )
                        con.execute("CREATE INDEX IF NOT EXISTS idx_lease_waits_tenant ON lease_waits(tenant)")
                        con.execute("CREATE INDEX IF NOT EXISTS idx_lease_waits_blocked ON lease_waits(blocked_by)")
                        con.execute("COMMIT")
                    except BaseException:
                        if con.in_transaction:
                            con.execute("ROLLBACK")
                        raise
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    @staticmethod
    def _root(root: str) -> tuple[str, str]:
        windows_root = PureWindowsPath(str(root))
        if os.name != "nt" and windows_root.is_absolute():
            resolved = str(windows_root)
        else:
            resolved = canonical_root(root)
        root_identity = (
            ntpath.normcase(ntpath.normpath(resolved))
            if os.name == "nt" or windows_root.is_absolute()
            else resolved
        )
        root_id = hashlib.sha256(root_identity.encode("utf-8")).hexdigest()[:20]
        return resolved, root_id

    def claim(
        self,
        tenant: str,
        root: str,
        paths: list[str],
        ttl_seconds: int = 900,
        purpose: str = "agent edit",
        *,
        coordination_id: str | None | object = _COORDINATION_ID_UNSET,
    ) -> dict[str, Any]:
        if not isinstance(tenant, str) or not tenant.strip() or "\x00" in tenant:
            return {"success": False, "error": "invalid tenant"}
        if not isinstance(root, str) or not root.strip() or root != root.strip() or "\x00" in root:
            return {"success": False, "error": "invalid root"}
        if not isinstance(purpose, str) or not purpose.strip() or "\x00" in purpose:
            return {"success": False, "error": "invalid purpose"}
        if not isinstance(paths, (list, tuple)):
            return {"success": False, "error": "paths must be a sequence of path strings"}
        if not paths:
            return {"success": False, "error": "paths must not be empty"}
        for p in paths:
            if not isinstance(p, str) or not p.strip() or "\x00" in p:
                return {"success": False, "error": f"invalid lease path: {p}"}
        if (not root or root == ".") and paths:
            first_abs = next((str(p) for p in paths if PureWindowsPath(str(p)).is_absolute() or Path(str(p)).is_absolute() or bool(PureWindowsPath(str(p)).drive)), None)
            if first_abs:
                try:
                    candidate = Path(first_abs).resolve()
                    for parent in [candidate.parent, *candidate.parents]:
                        if any((parent / marker).exists() for marker in (".git", "pyproject.toml", "package.json", "Cargo.toml", ".local-ai")):
                            root = str(parent)
                            break
                except Exception:
                    pass
        root_path, physical_root_id = self._root(root)
        if coordination_id is None:
            return {"success": False, "error": "project coordination id is required"}
        if coordination_id is _COORDINATION_ID_UNSET:
            root_id = physical_root_id
        else:
            if not _is_canonical_coordination_id(coordination_id):
                return {"success": False, "error": "invalid project coordination id"}
            namespace = coordination_id
            root_id = f"project:{namespace}"
        rels = sorted({_norm_rel(str(p), root=root_path) for p in paths})
        now = time.time()
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)) or not math.isfinite(ttl_seconds):
            ttl = 900
        else:
            ttl = max(30, min(int(ttl_seconds), 7200))
        expires = now + ttl
        lease_id = f"lease_{uuid.uuid4().hex[:20]}"

        def write() -> dict[str, Any]:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                con.execute("DELETE FROM leases WHERE expires_at <= ?", (now,))
                con.execute("DELETE FROM lease_waits WHERE updated_at <= ?", (now - 7200,))
                if coordination_id is _COORDINATION_ID_UNSET:
                    existing = con.execute(
                        "SELECT lease_id,tenant,path,purpose,expires_at FROM leases WHERE root_id=? AND tenant<>?",
                        (root_id, tenant),
                    ).fetchall()
                else:
                    existing = con.execute(
                        "SELECT lease_id,tenant,path,purpose,expires_at FROM leases "
                        "WHERE tenant<>? AND (root_id=? OR (root_id=? AND root_path=?))",
                        (tenant, root_id, physical_root_id, root_path),
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
                con.execute("DELETE FROM lease_waits WHERE tenant=? AND root_id=?", (tenant, root_id))
                con.executemany(
                    "INSERT INTO leases(lease_id,tenant,root_id,root_path,path,purpose,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)",
                    [(lease_id, tenant, root_id, root_path, p, purpose[:300], now, expires) for p in rels],
                )
                con.execute("COMMIT")
                return {"success": True, "lease_id": lease_id, "root": root_path, "paths": rels, "expires_at": expires}

        return retry_busy(write, retries=4)

    def claim_batch(
        self,
        tenant: str,
        root: str,
        paths: list[str],
        ttl_seconds: int = 900,
        purpose: str = "agent edit",
        *,
        coordination_id: str | None | object = _COORDINATION_ID_UNSET,
    ) -> dict[str, Any]:
        """Atomic multi-path batch lease claim with rollback and cycle detection."""
        return self.claim(
            tenant=tenant,
            root=root,
            paths=paths,
            ttl_seconds=ttl_seconds,
            purpose=purpose,
            coordination_id=coordination_id,
        )

    def release(self, tenant: str, lease_id: str) -> dict[str, Any]:
        if not isinstance(tenant, str) or not tenant.strip() or "\x00" in tenant:
            return {"success": False, "error": "invalid tenant"}
        if not isinstance(lease_id, str):
            return {"success": False, "error": "lease_id must be a string"}
        if not lease_id or lease_id != lease_id.strip() or "\x00" in lease_id:
            return {"success": False, "error": "invalid lease_id"}

        return self._release_matching(tenant, lease_id)

    def release_tenant(self, tenant: str) -> dict[str, Any]:
        """Release all advisory leases for one exact tenant during owner cleanup."""
        if not isinstance(tenant, str) or not tenant.strip() or "\x00" in tenant:
            return {"success": False, "error": "invalid tenant"}
        return self._release_matching(tenant, None)

    def _release_matching(self, tenant: str, lease_id: str | None) -> dict[str, Any]:

        def write() -> int:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                released_scopes: list[tuple[str, str]] = []
                if lease_id is not None:
                    p_rows = con.execute(
                        "SELECT root_id,path FROM leases WHERE lease_id=? AND tenant=?",
                        (lease_id, tenant),
                    ).fetchall()
                    released_scopes = [(str(r[0]), str(r[1])) for r in p_rows]
                    cur = con.execute(
                        "DELETE FROM leases WHERE lease_id=? AND tenant=?",
                        (lease_id, tenant),
                    )
                else:
                    p_rows = con.execute(
                        "SELECT DISTINCT root_id,path FROM leases WHERE tenant=?",
                        (tenant,),
                    ).fetchall()
                    released_scopes = [(str(r[0]), str(r[1])) for r in p_rows]
                    cur = con.execute("DELETE FROM leases WHERE tenant=?", (tenant,))
                count = int(cur.rowcount or 0)
                # Keep wait dependencies scoped to the released project namespace.
                roots = {scope_id for scope_id, _ in released_scopes}
                for scope_id in roots:
                    con.execute(
                        "DELETE FROM lease_waits WHERE tenant=? AND root_id=?",
                        (tenant, scope_id),
                    )
                for scope_id, path in released_scopes:
                    con.execute(
                        "DELETE FROM lease_waits WHERE blocked_by=? AND root_id=? AND requested_path=?",
                        (tenant, scope_id, path),
                    )
                con.execute("COMMIT")
                return count
        return {"success": True, "released_rows": retry_busy(write, retries=4)}

    def reap_expired(self, now: float | None = None) -> dict[str, Any]:
        """Prune all expired leases and stale wait dependencies, returning reaped metrics."""
        current_time = time.time() if now is None else float(now)

        def write() -> dict[str, int]:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                cur1 = con.execute("DELETE FROM leases WHERE expires_at <= ?", (current_time,))
                reaped_leases = int(cur1.rowcount or 0)
                cur2 = con.execute("DELETE FROM lease_waits WHERE updated_at <= ?", (current_time - 7200,))
                reaped_waits = int(cur2.rowcount or 0)
                con.execute("COMMIT")
                return {"reaped_leases": reaped_leases, "reaped_waits": reaped_waits}

        result = retry_busy(write, retries=4)
        return {"success": True, **result}

    def renew(self, tenant: str, lease_id: str, ttl_seconds: int = 900) -> dict[str, Any]:
        """Atomically extend the expiration TTL of an existing held lease."""
        if not isinstance(tenant, str) or not tenant.strip() or "\x00" in tenant:
            return {"success": False, "error": "invalid tenant"}
        if not isinstance(lease_id, str):
            return {"success": False, "error": "lease_id must be a string"}
        if not lease_id or lease_id != lease_id.strip() or "\x00" in lease_id:
            return {"success": False, "error": "invalid lease_id"}
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)) or not math.isfinite(ttl_seconds):
            ttl = 900
        else:
            ttl = max(30, min(int(ttl_seconds), 7200))
        now = time.time()
        new_expires = now + ttl

        def write() -> dict[str, Any]:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                rows = con.execute(
                    "SELECT path FROM leases WHERE lease_id=? AND tenant=? AND expires_at>?",
                    (lease_id, tenant, now),
                ).fetchall()
                if not rows:
                    con.execute("ROLLBACK")
                    return {"success": False, "error": "lease not found, expired, or belongs to another tenant"}
                con.execute(
                    "UPDATE leases SET expires_at=? WHERE lease_id=? AND tenant=?",
                    (new_expires, lease_id, tenant),
                )
                con.execute("COMMIT")
                paths = [r[0] for r in rows]
                return {"success": True, "lease_id": lease_id, "expires_at": new_expires, "paths": paths}

        return retry_busy(write, retries=4)

    def list(
        self,
        root: str = "",
        *,
        coordination_id: str | None | object = _COORDINATION_ID_UNSET,
    ) -> list[dict[str, Any]]:
        if not isinstance(root, str) or root != root.strip() or "\x00" in root:
            return []
        if coordination_id is None:
            return []
        if coordination_id is not _COORDINATION_ID_UNSET and not _is_canonical_coordination_id(coordination_id):
            return []
        now = time.time()
        def read():
            with closing(self._connect()) as con:
                if root:
                    root_path, physical_root_id = self._root(root)
                    if coordination_id is _COORDINATION_ID_UNSET:
                        return con.execute(
                            "SELECT lease_id,tenant,root_path,path,purpose,expires_at FROM leases "
                            "WHERE (root_id=? OR root_path=?) AND expires_at>? ORDER BY expires_at",
                            (physical_root_id, root_path, now),
                        ).fetchall()
                    root_id = f"project:{coordination_id}"
                    return con.execute(
                        "SELECT lease_id,tenant,root_path,path,purpose,expires_at FROM leases "
                        "WHERE (root_id=? OR (root_id=? AND root_path=?)) AND expires_at>? ORDER BY expires_at",
                        (root_id, physical_root_id, root_path, now),
                    ).fetchall()
                if coordination_id is not _COORDINATION_ID_UNSET:
                    return con.execute(
                        "SELECT lease_id,tenant,root_path,path,purpose,expires_at FROM leases "
                        "WHERE root_id=? AND expires_at>? ORDER BY expires_at",
                        (f"project:{coordination_id}", now),
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

    def waits(
        self,
        root: str = "",
        *,
        coordination_id: str | None | object = _COORDINATION_ID_UNSET,
    ) -> list[dict[str, Any]]:
        if not isinstance(root, str) or root != root.strip() or "\x00" in root:
            return []
        if coordination_id is None:
            return []
        if coordination_id is not _COORDINATION_ID_UNSET and not _is_canonical_coordination_id(coordination_id):
            return []
        now = time.time()
        def read():
            with closing(self._connect()) as con:
                if root:
                    _, physical_root_id = self._root(root)
                    if coordination_id is _COORDINATION_ID_UNSET:
                        root_ids = (physical_root_id,)
                    else:
                        root_ids = (f"project:{coordination_id}", physical_root_id)
                    placeholders = ",".join("?" for _ in root_ids)
                    return con.execute(
                        f"SELECT tenant, blocked_by, requested_path, updated_at FROM lease_waits "
                        f"WHERE root_id IN ({placeholders}) AND updated_at>? ORDER BY updated_at DESC",
                        (*root_ids, now - 3600),
                    ).fetchall()
                if coordination_id is not _COORDINATION_ID_UNSET:
                    return con.execute(
                        "SELECT tenant, blocked_by, requested_path, updated_at FROM lease_waits "
                        "WHERE root_id=? AND updated_at>? ORDER BY updated_at DESC",
                        (f"project:{coordination_id}", now - 3600),
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

    def check_path(
        self,
        path: str,
        root: str = "",
        *,
        tenant: str | None = None,
        coordination_id: str | None | object = _COORDINATION_ID_UNSET,
    ) -> dict[str, Any]:
        """Check if a specific file or directory path is leased or in conflict."""
        if not isinstance(path, str):
            return {
                "leased": False, "conflict": False, "path": "",
                "error": "path must be a string", "tenant": None,
                "lease_id": None, "expires_at": None, "purpose": None,
            }
        if not isinstance(root, str) or root != root.strip() or "\x00" in root:
            return {
                "leased": False, "conflict": False, "path": path,
                "error": "invalid root", "tenant": None,
                "lease_id": None, "expires_at": None, "purpose": None,
            }
        if tenant is not None and (not isinstance(tenant, str) or not tenant.strip() or "\x00" in tenant):
            return {
                "leased": False, "conflict": False, "path": path,
                "error": "invalid tenant", "tenant": None,
                "lease_id": None, "expires_at": None, "purpose": None,
            }
        if coordination_id is not _COORDINATION_ID_UNSET and coordination_id is not None and not _is_canonical_coordination_id(coordination_id):
            return {
                "leased": False, "conflict": False, "path": path,
                "error": "invalid project coordination id", "tenant": None,
                "lease_id": None, "expires_at": None, "purpose": None,
            }
        if not path:
            return {"leased": False, "conflict": False, "path": "", "tenant": None, "lease_id": None, "expires_at": None, "purpose": None}
        try:
            root_path, physical_root_id = self._root(root)
            rel_path = _norm_rel(path, root=root_path)
        except Exception as exc:
            return {"leased": False, "conflict": False, "path": path, "error": str(exc), "tenant": None, "lease_id": None, "expires_at": None, "purpose": None}

        if coordination_id is _COORDINATION_ID_UNSET:
            root_id = physical_root_id
        elif coordination_id is None:
            return {"leased": False, "conflict": False, "path": rel_path, "tenant": None, "lease_id": None, "expires_at": None, "purpose": None}
        else:
            root_id = f"project:{coordination_id}"

        now = time.time()

        def read() -> tuple[Any, ...] | None:
            with closing(self._connect()) as con:
                if coordination_id is _COORDINATION_ID_UNSET:
                    rows = con.execute(
                        "SELECT lease_id, tenant, path, purpose, expires_at FROM leases "
                        "WHERE root_id=? AND expires_at>?",
                        (root_id, now),
                    ).fetchall()
                else:
                    rows = con.execute(
                        "SELECT lease_id, tenant, path, purpose, expires_at FROM leases "
                        "WHERE (root_id=? OR (root_id=? AND root_path=?)) AND expires_at>?",
                        (root_id, physical_root_id, root_path, now),
                    ).fetchall()
                for row in rows:
                    if _overlap(rel_path, row[2]):
                        return row
                return None

        matched = retry_busy(read, retries=3)
        if matched is None:
            return {
                "leased": False,
                "conflict": False,
                "path": rel_path,
                "tenant": None,
                "lease_id": None,
                "expires_at": None,
                "purpose": None,
            }

        held_lease_id, held_tenant, held_path, held_purpose, held_expires_at = matched
        conflict = bool(tenant is not None and held_tenant != tenant)
        return {
            "leased": True,
            "conflict": conflict,
            "path": rel_path,
            "held_path": held_path,
            "tenant": held_tenant,
            "lease_id": held_lease_id,
            "expires_at": held_expires_at,
            "purpose": held_purpose,
        }

    acquire = claim
