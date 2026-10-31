from __future__ import annotations

import hashlib
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
        ("lease_id", "TEXT", 1, 1), ("owner", "TEXT", 1, 0),
        ("root_id", "TEXT", 1, 0), ("root_path", "TEXT", 1, 0),
        ("path", "TEXT", 1, 2), ("purpose", "TEXT", 1, 0),
        ("created_at", "REAL", 1, 0), ("expires_at", "REAL", 1, 0),
    ],
    "lease_waits": [
        ("owner", "TEXT", 1, 2), ("blocked_by", "TEXT", 1, 3),
        ("root_id", "TEXT", 1, 1), ("requested_path", "TEXT", 1, 4),
        ("updated_at", "REAL", 1, 0),
    ],
}
_LEASE_REQUIRED_UNIQUE = {
    "leases": (("lease_id", "path"),),
    "lease_waits": (("root_id", "owner", "blocked_by", "requested_path"),),
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
    if not isinstance(value, str):
        raise ValueError(f"lease path must be repository-relative: {value}")
    raw = value.strip()
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
    if Path(root).is_absolute() and not (os.name != "nt" and PureWindowsPath(root).is_absolute()):
        try:
            resolved_root = Path(root).resolve(strict=False)
            resolved_path = (resolved_root / norm_path).resolve(strict=False)
            norm_path = resolved_path.relative_to(resolved_root).as_posix() or "."
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(f"lease path must be repository-relative: {value}") from exc
    return norm_path


def _overlap(a: str, b: str, *, case_insensitive: bool | None = None) -> bool:
    try:
        na = _norm_rel(a)
        nb = _norm_rel(b)
    except (TypeError, ValueError):
        return True
    if na == "." or nb == ".":
        return True
    insensitive = os.name == "nt" if case_insensitive is None else case_insensitive
    if insensitive:
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


def _bounded_lease_ttl(value: object) -> int | None:
    if type(value) is not int or value < 1:
        return None
    return max(30, min(value, 7200))


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
                                owner TEXT NOT NULL,
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
                                owner TEXT NOT NULL,
                                blocked_by TEXT NOT NULL,
                                root_id TEXT NOT NULL,
                                requested_path TEXT NOT NULL,
                                updated_at REAL NOT NULL,
                                PRIMARY KEY(root_id, owner, blocked_by, requested_path)
                            )"""
                        )
                        con.execute("CREATE INDEX IF NOT EXISTS idx_lease_waits_owner ON lease_waits(owner)")
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
        *,
        owner: str,
        root: str,
        paths: list[str],
        ttl_seconds: int = 900,
        purpose: str = "agent edit",
        coordination_id: str | None | object = _COORDINATION_ID_UNSET,
    ) -> dict[str, Any]:
        if not isinstance(owner, str) or not owner.strip() or owner != owner.strip() or "\x00" in owner:
            return {"success": False, "error": "invalid owner"}
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
        windows_root = PureWindowsPath(root)
        if not Path(root).is_absolute() and not windows_root.is_absolute():
            return {"success": False, "error": "root must be an absolute repository root"}
        root_path, physical_root_id = self._root(root)
        case_insensitive_paths = os.name == "nt" or windows_root.is_absolute()
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
        ttl = _bounded_lease_ttl(ttl_seconds)
        if ttl is None:
            return {"success": False, "error": "ttl_seconds must be a positive integer"}
        expires = now + ttl
        lease_id = f"lease_{uuid.uuid4().hex[:20]}"

        def write() -> dict[str, Any]:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                con.execute("DELETE FROM leases WHERE expires_at <= ?", (now,))
                con.execute("DELETE FROM lease_waits WHERE updated_at <= ?", (now - 7200,))
                if coordination_id is _COORDINATION_ID_UNSET:
                    existing = con.execute(
                        "SELECT lease_id,owner,path,purpose,expires_at FROM leases WHERE root_id=? AND owner<>?",
                        (root_id, owner),
                    ).fetchall()
                else:
                    existing = con.execute(
                        "SELECT lease_id,owner,path,purpose,expires_at FROM leases "
                        "WHERE owner<>? AND (root_id=? OR (root_id=? AND root_path=?))",
                        (owner, root_id, physical_root_id, root_path),
                    ).fetchall()
                conflicts = []
                for requested in rels:
                    for row in existing:
                        if _overlap(
                            requested,
                            row[2],
                            case_insensitive=case_insensitive_paths,
                        ):
                            conflicts.append({
                                "requested": requested, "held_path": row[2], "owner": row[1],
                                "lease_id": row[0], "purpose": row[3], "expires_at": row[4],
                            })
                if conflicts:
                    conflicting_owners = {c["owner"] for c in conflicts if c.get("owner")}

                    # Build wait-for graph from persistent waits and proposed contention
                    wait_rows = con.execute(
                        "SELECT owner, blocked_by FROM lease_waits WHERE root_id=? AND updated_at>?",
                        (root_id, now - 3600),
                    ).fetchall()
                    graph: dict[str, set[str]] = {}
                    for u, v in wait_rows:
                        graph.setdefault(u, set()).add(v)
                    for b in conflicting_owners:
                        graph.setdefault(owner, set()).add(b)

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

                    cycle = detect_cycle(owner)
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
                            "INSERT OR REPLACE INTO lease_waits(owner, blocked_by, root_id, requested_path, updated_at) VALUES(?,?,?,?,?)",
                            (owner, c["owner"], root_id, c["requested"], now),
                        )
                    con.execute("COMMIT")
                    return {
                        "success": False,
                        "error": "write scope overlaps another active agent lease",
                        "deadlock": False,
                        "conflicts": conflicts,
                    }

                # Successfully acquire all requested paths atomically
                con.execute("DELETE FROM lease_waits WHERE owner=? AND root_id=?", (owner, root_id))
                con.executemany(
                    "INSERT INTO leases(lease_id,owner,root_id,root_path,path,purpose,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)",
                    [(lease_id, owner, root_id, root_path, p, purpose[:300], now, expires) for p in rels],
                )
                con.execute("COMMIT")
                return {"success": True, "lease_id": lease_id, "root": root_path, "paths": rels, "expires_at": expires}

        return retry_busy(write, retries=4)

    def claim_batch(
        self,
        *,
        owner: str,
        root: str,
        paths: list[str],
        ttl_seconds: int = 900,
        purpose: str = "agent edit",
        coordination_id: str | None | object = _COORDINATION_ID_UNSET,
    ) -> dict[str, Any]:
        """Atomic multi-path batch lease claim with rollback and cycle detection."""
        return self.claim(
            owner=owner,
            root=root,
            paths=paths,
            ttl_seconds=ttl_seconds,
            purpose=purpose,
            coordination_id=coordination_id,
        )

    def release(self, *, owner: str, lease_id: str) -> dict[str, Any]:
        if not isinstance(owner, str) or not owner.strip() or owner != owner.strip() or "\x00" in owner:
            return {"success": False, "error": "invalid owner"}
        if not isinstance(lease_id, str):
            return {"success": False, "error": "lease_id must be a string"}
        if not lease_id or lease_id != lease_id.strip() or "\x00" in lease_id:
            return {"success": False, "error": "invalid lease_id"}

        return self._release_matching(owner, lease_id)

    def release_owner(self, *, owner: str) -> dict[str, Any]:
        """Release this writer's advisory leases; owner is an actual task/execution ID."""
        if not isinstance(owner, str) or not owner.strip() or owner != owner.strip() or "\x00" in owner:
            return {"success": False, "error": "invalid owner"}
        return self._release_matching(owner, None)

    def _release_matching(self, owner: str, lease_id: str | None) -> dict[str, Any]:

        def write() -> int:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                released_scopes: list[tuple[str, str]] = []
                if lease_id is not None:
                    p_rows = con.execute(
                        "SELECT root_id,path FROM leases WHERE lease_id=? AND owner=?",
                        (lease_id, owner),
                    ).fetchall()
                    released_scopes = [(str(r[0]), str(r[1])) for r in p_rows]
                    cur = con.execute(
                        "DELETE FROM leases WHERE lease_id=? AND owner=?",
                        (lease_id, owner),
                    )
                else:
                    p_rows = con.execute(
                        "SELECT DISTINCT root_id,path FROM leases WHERE owner=?",
                        (owner,),
                    ).fetchall()
                    released_scopes = [(str(r[0]), str(r[1])) for r in p_rows]
                    cur = con.execute("DELETE FROM leases WHERE owner=?", (owner,))
                count = int(cur.rowcount or 0)
                # Keep wait dependencies scoped to the released project namespace.
                roots = {scope_id for scope_id, _ in released_scopes}
                for scope_id in roots:
                    con.execute(
                        "DELETE FROM lease_waits WHERE owner=? AND root_id=?",
                        (owner, scope_id),
                    )
                for scope_id, path in released_scopes:
                    con.execute(
                        "DELETE FROM lease_waits WHERE blocked_by=? AND root_id=? AND requested_path=?",
                        (owner, scope_id, path),
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

    def renew(self, *, owner: str, lease_id: str, ttl_seconds: int = 900) -> dict[str, Any]:
        """Atomically extend the expiration TTL of an existing held lease."""
        if not isinstance(owner, str) or not owner.strip() or owner != owner.strip() or "\x00" in owner:
            return {"success": False, "error": "invalid owner"}
        if not isinstance(lease_id, str):
            return {"success": False, "error": "lease_id must be a string"}
        if not lease_id or lease_id != lease_id.strip() or "\x00" in lease_id:
            return {"success": False, "error": "invalid lease_id"}
        ttl = _bounded_lease_ttl(ttl_seconds)
        if ttl is None:
            return {"success": False, "error": "ttl_seconds must be a positive integer"}
        now = time.time()
        new_expires = now + ttl

        def write() -> dict[str, Any]:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                rows = con.execute(
                    "SELECT path FROM leases WHERE lease_id=? AND owner=? AND expires_at>?",
                    (lease_id, owner, now),
                ).fetchall()
                if not rows:
                    con.execute("ROLLBACK")
                    return {"success": False, "error": "lease not found, expired, or belongs to another owner"}
                con.execute(
                    "UPDATE leases SET expires_at=? WHERE lease_id=? AND owner=?",
                    (new_expires, lease_id, owner),
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
                            "SELECT lease_id,owner,root_path,path,purpose,expires_at FROM leases "
                            "WHERE (root_id=? OR root_path=?) AND expires_at>? ORDER BY expires_at",
                            (physical_root_id, root_path, now),
                        ).fetchall()
                    root_id = f"project:{coordination_id}"
                    return con.execute(
                        "SELECT lease_id,owner,root_path,path,purpose,expires_at FROM leases "
                        "WHERE (root_id=? OR (root_id=? AND root_path=?)) AND expires_at>? ORDER BY expires_at",
                        (root_id, physical_root_id, root_path, now),
                    ).fetchall()
                if coordination_id is not _COORDINATION_ID_UNSET:
                    return con.execute(
                        "SELECT lease_id,owner,root_path,path,purpose,expires_at FROM leases "
                        "WHERE root_id=? AND expires_at>? ORDER BY expires_at",
                        (f"project:{coordination_id}", now),
                    ).fetchall()
                return con.execute(
                    "SELECT lease_id,owner,root_path,path,purpose,expires_at FROM leases WHERE expires_at>? ORDER BY expires_at",
                    (now,),
                ).fetchall()
        rows = retry_busy(read, retries=3)
        return [
            {"lease_id": r[0], "owner": r[1], "root": r[2], "path": r[3], "purpose": r[4], "expires_at": r[5]}
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
                        f"SELECT owner, blocked_by, requested_path, updated_at FROM lease_waits "
                        f"WHERE root_id IN ({placeholders}) AND updated_at>? ORDER BY updated_at DESC",
                        (*root_ids, now - 3600),
                    ).fetchall()
                if coordination_id is not _COORDINATION_ID_UNSET:
                    return con.execute(
                        "SELECT owner, blocked_by, requested_path, updated_at FROM lease_waits "
                        "WHERE root_id=? AND updated_at>? ORDER BY updated_at DESC",
                        (f"project:{coordination_id}", now - 3600),
                    ).fetchall()
                return con.execute(
                    "SELECT owner, blocked_by, requested_path, updated_at FROM lease_waits WHERE updated_at>? ORDER BY updated_at DESC",
                    (now - 3600,),
                ).fetchall()
        rows = retry_busy(read, retries=3)
        return [
            {"owner": r[0], "blocked_by": r[1], "requested_path": r[2], "updated_at": r[3]}
            for r in rows
        ]

    def check_path(
        self,
        path: str,
        root: str = "",
        *,
        owner: str | None = None,
        coordination_id: str | None | object = _COORDINATION_ID_UNSET,
    ) -> dict[str, Any]:
        """Check if a specific file or directory path is leased or in conflict."""
        if not isinstance(path, str):
            return {
                "leased": False, "conflict": False, "path": "",
                "error": "path must be a string", "owner": None,
                "lease_id": None, "expires_at": None, "purpose": None,
            }
        if not isinstance(root, str) or root != root.strip() or "\x00" in root:
            return {
                "leased": False, "conflict": False, "path": path,
                "error": "invalid root", "owner": None,
                "lease_id": None, "expires_at": None, "purpose": None,
            }
        if owner is not None and (not isinstance(owner, str) or not owner.strip() or owner != owner.strip() or "\x00" in owner):
            return {
                "leased": False, "conflict": False, "path": path,
                "error": "invalid owner", "owner": None,
                "lease_id": None, "expires_at": None, "purpose": None,
            }
        if coordination_id is not _COORDINATION_ID_UNSET and coordination_id is not None and not _is_canonical_coordination_id(coordination_id):
            return {
                "leased": False, "conflict": False, "path": path,
                "error": "invalid project coordination id", "owner": None,
                "lease_id": None, "expires_at": None, "purpose": None,
            }
        if not path:
            return {"leased": False, "conflict": False, "path": "", "owner": None, "lease_id": None, "expires_at": None, "purpose": None}
        try:
            root_path, physical_root_id = self._root(root)
            rel_path = _norm_rel(path, root=root_path)
        except Exception as exc:
            return {"leased": False, "conflict": False, "path": path, "error": str(exc), "owner": None, "lease_id": None, "expires_at": None, "purpose": None}

        if coordination_id is _COORDINATION_ID_UNSET:
            root_id = physical_root_id
        elif coordination_id is None:
            return {"leased": False, "conflict": False, "path": rel_path, "owner": None, "lease_id": None, "expires_at": None, "purpose": None}
        else:
            root_id = f"project:{coordination_id}"
        case_insensitive_paths = os.name == "nt" or PureWindowsPath(root).is_absolute()

        now = time.time()

        def read() -> tuple[Any, ...] | None:
            with closing(self._connect()) as con:
                if coordination_id is _COORDINATION_ID_UNSET:
                    rows = con.execute(
                        "SELECT lease_id, owner, path, purpose, expires_at FROM leases "
                        "WHERE root_id=? AND expires_at>?",
                        (root_id, now),
                    ).fetchall()
                else:
                    rows = con.execute(
                        "SELECT lease_id, owner, path, purpose, expires_at FROM leases "
                        "WHERE (root_id=? OR (root_id=? AND root_path=?)) AND expires_at>?",
                        (root_id, physical_root_id, root_path, now),
                    ).fetchall()
                for row in rows:
                    if _overlap(
                        rel_path,
                        row[2],
                        case_insensitive=case_insensitive_paths,
                    ):
                        return row
                return None

        matched = retry_busy(read, retries=3)
        if matched is None:
            return {
                "leased": False,
                "conflict": False,
                "path": rel_path,
                "owner": None,
                "lease_id": None,
                "expires_at": None,
                "purpose": None,
            }

        held_lease_id, held_owner, held_path, held_purpose, held_expires_at = matched
        conflict = bool(owner is not None and held_owner != owner)
        return {
            "leased": True,
            "conflict": conflict,
            "path": rel_path,
            "held_path": held_path,
            "owner": held_owner,
            "lease_id": held_lease_id,
            "expires_at": held_expires_at,
            "purpose": held_purpose,
        }

    acquire = claim
