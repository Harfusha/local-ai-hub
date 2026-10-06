"""Cross-process writer leases with monotonic fencing tokens.

The lease store is authoritative only when every writer uses the same database
and enters ``commit_guard`` around its final write-set import and journal commit.
``assert_current`` is a preflight check; it does not by itself protect a later
write from a lease expiry/reacquisition race.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Iterator, Sequence
from uuid import uuid4

from .sqlite_support import connect_sqlite, initialize_wal, retry_busy


MAX_TTL_SECONDS = 24 * 60 * 60
_COORDINATION_ID_UNSET = object()


class LeaseLostError(RuntimeError):
    """The lease expired, was superseded, or no longer belongs to its owner."""


class LeaseUnavailableError(RuntimeError):
    """A live lease already owns an overlapping path scope."""


class LeaseScopeError(PermissionError):
    """A writer attempted to mutate a path outside its declared lease scope."""


@dataclass(frozen=True)
class WorkAttemptFence:
    """Execution epoch held for one work ID; stale epochs cannot renew or commit."""

    resource: str
    work_id: str
    attempt_id: str
    owner_id: str
    fencing_token: int
    expires_at: float
    scope_id: str = ""


@dataclass(frozen=True)
class FencingLease:
    """Exact path lease, optionally bound to its work attempt epoch."""

    resource: str
    lease_id: str
    owner_id: str
    fencing_token: int
    expires_at: float
    paths: tuple[str, ...]
    attempt_id: str = ""
    attempt_token: int = 0
    scope_id: str = ""


def canonical_resource(resource: str | Path) -> str:
    value = str(resource).strip()
    if not value or "\x00" in value:
        raise ValueError("resource must be a non-empty filesystem root")
    return os.path.normcase(str(Path(value).expanduser().resolve(strict=False)))


def _coordination_scope(
    resource: str | Path,
    coordination_id: str | None | object,
) -> tuple[str, str]:
    physical = canonical_resource(resource)
    if coordination_id is None:
        raise ValueError("project coordination id is required")
    if coordination_id is _COORDINATION_ID_UNSET:
        return physical, physical
    namespace = str(coordination_id).strip()
    if not namespace or "\x00" in namespace or len(namespace) > 512:
        raise ValueError("invalid project coordination id")
    return physical, f"project:{namespace}"


def normalize_paths(
    paths: Sequence[str], *, root: str | Path | None = None
) -> tuple[str, ...]:
    normalized: set[str] = set()
    resolved_root = Path(root).resolve(strict=False) if root is not None else None
    for value in paths:
        raw = str(value).replace("\\", "/")
        windows = PureWindowsPath(raw)
        posix = PurePosixPath(raw)
        parts = raw.split("/")
        if (
            not raw
            or "\x00" in raw
            or windows.drive
            or windows.root
            or posix.is_absolute()
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError(f"unsafe lease path: {value!r}")
        identity = "/".join(parts)
        if resolved_root is not None:
            target = (resolved_root / Path(*parts)).resolve(strict=False)
            try:
                target = target.relative_to(resolved_root)
            except ValueError as exc:
                raise ValueError(f"lease path escapes filesystem root: {value!r}") from exc
            identity = target.as_posix()
        normalized.add(identity)
    if not normalized:
        raise ValueError("writer lease requires at least one exact path")
    return tuple(sorted(normalized))


def _overlaps(left: Sequence[str], right: Sequence[str]) -> bool:
    left_keys = tuple(os.path.normcase(path).replace("\\", "/") for path in left)
    right_keys = tuple(os.path.normcase(path).replace("\\", "/") for path in right)
    for first in left_keys:
        for second in right_keys:
            if (
                first == second
                or first.startswith(second + "/")
                or second.startswith(first + "/")
            ):
                return True
    return False


class FencingLeaseStore:
    """SQLite-backed, cross-process lease and commit fence.

    Tokens increase monotonically per canonical resource. Disjoint path scopes
    may hold live leases together. The SQLite ``BEGIN IMMEDIATE`` transaction in
    ``commit_guard`` serializes lease changes with the caller's protected write
    and remains open until the caller's write/journal commit finishes.
    """

    def __init__(
        self,
        database_path: Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._init_lock = threading.RLock()
        self._initialized = False
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=5.0, isolation_level=None)

    def _initialize(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return

            def setup() -> None:
                with closing(self._connect()) as con:
                    initialize_wal(con)
                    con.execute(
                        """CREATE TABLE IF NOT EXISTS writer_fence_counters (
                            resource TEXT PRIMARY KEY,
                            last_token INTEGER NOT NULL CHECK(last_token >= 0)
                        )"""
                    )
                    con.execute(
                        """CREATE TABLE IF NOT EXISTS writer_fence_leases (
                            lease_id TEXT PRIMARY KEY,
                            resource TEXT NOT NULL,
                            owner_id TEXT NOT NULL,
                            fencing_token INTEGER NOT NULL CHECK(fencing_token > 0),
                            expires_at REAL NOT NULL,
                            paths_json TEXT NOT NULL,
                            attempt_id TEXT NOT NULL DEFAULT '',
                            attempt_token INTEGER NOT NULL DEFAULT 0,
                            scope_id TEXT NOT NULL DEFAULT '',
                            active INTEGER NOT NULL CHECK(active IN (0, 1))
                        )"""
                    )
                    lease_columns = {
                        str(row[1]) for row in con.execute("PRAGMA table_info(writer_fence_leases)")
                    }
                    if "attempt_id" not in lease_columns:
                        con.execute("ALTER TABLE writer_fence_leases ADD COLUMN attempt_id TEXT NOT NULL DEFAULT ''")
                    if "attempt_token" not in lease_columns:
                        con.execute("ALTER TABLE writer_fence_leases ADD COLUMN attempt_token INTEGER NOT NULL DEFAULT 0")
                    if "scope_id" not in lease_columns:
                        con.execute("ALTER TABLE writer_fence_leases ADD COLUMN scope_id TEXT NOT NULL DEFAULT ''")
                    con.execute("UPDATE writer_fence_leases SET scope_id=resource WHERE scope_id='' ")
                    con.execute(
                        """CREATE TABLE IF NOT EXISTS writer_fence_attempts (
                            attempt_id TEXT PRIMARY KEY,
                            resource TEXT NOT NULL,
                            scope_id TEXT NOT NULL DEFAULT '',
                            work_id TEXT NOT NULL,
                            owner_id TEXT NOT NULL,
                            fencing_token INTEGER NOT NULL CHECK(fencing_token > 0),
                            expires_at REAL NOT NULL,
                            active INTEGER NOT NULL CHECK(active IN (0, 1)),
                            UNIQUE(resource, work_id, fencing_token)
                        )"""
                    )
                    attempt_columns = {
                        str(row[1]) for row in con.execute("PRAGMA table_info(writer_fence_attempts)")
                    }
                    if "scope_id" not in attempt_columns:
                        con.execute("ALTER TABLE writer_fence_attempts ADD COLUMN scope_id TEXT NOT NULL DEFAULT ''")
                    con.execute("UPDATE writer_fence_attempts SET scope_id=resource WHERE scope_id='' ")
                    con.execute(
                        "CREATE INDEX IF NOT EXISTS idx_writer_attempt_scope "
                        "ON writer_fence_attempts(scope_id, work_id, active, expires_at)"
                    )
                    con.execute(
                        "CREATE INDEX IF NOT EXISTS idx_writer_fence_scope_live "
                        "ON writer_fence_leases(scope_id, active, expires_at)"
                    )
                    con.execute(
                        "CREATE INDEX IF NOT EXISTS idx_writer_attempt_current "
                        "ON writer_fence_attempts(resource, work_id, active, expires_at)"
                    )
                    con.execute(
                        "CREATE INDEX IF NOT EXISTS idx_writer_fence_live "
                        "ON writer_fence_leases(resource, active, expires_at)"
                    )

            retry_busy(setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    @staticmethod
    def _attempt_counter_key(resource: str, work_id: str) -> str:
        return f"{resource}\nwork-order:{work_id}"

    def _assert_attempt(self, con: sqlite3.Connection, attempt: WorkAttemptFence) -> None:
        now = float(self._clock())
        row = con.execute(
            """SELECT resource,scope_id,work_id,owner_id,fencing_token,expires_at,active
               FROM writer_fence_attempts WHERE attempt_id=?""",
            (attempt.attempt_id,),
        ).fetchone()
        if row is None:
            raise LeaseLostError("work attempt fence no longer exists")
        resource, scope_id, work_id, owner, token, expires_at, active = row
        if (
            str(resource) != attempt.resource
            or str(scope_id) != (attempt.scope_id or attempt.resource)
            or str(work_id) != attempt.work_id
            or str(owner) != attempt.owner_id
            or int(token) != attempt.fencing_token
        ):
            raise LeaseLostError("work attempt identity or fencing token changed")
        if not bool(active) or float(expires_at) <= now:
            raise LeaseLostError("work attempt fence expired or was superseded")

    @contextmanager
    def attempt_guard(self, attempt: WorkAttemptFence) -> Iterator[None]:
        """Fence one durable work-order state transition against attempt expiry."""
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            self._assert_attempt(con, attempt)
            yield
            con.execute("COMMIT")
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def assert_attempt_current(self, attempt: WorkAttemptFence) -> None:
        """Check an execution epoch before starting work with external side effects."""
        with closing(self._connect()) as con:
            con.execute("BEGIN")
            try:
                self._assert_attempt(con, attempt)
                con.execute("COMMIT")
            except BaseException:
                if con.in_transaction:
                    con.execute("ROLLBACK")
                raise

    def claim_attempt(
        self,
        resource: str | Path,
        work_id: str,
        owner_id: str,
        *,
        ttl_seconds: float,
        coordination_id: str | None | object = _COORDINATION_ID_UNSET,
    ) -> WorkAttemptFence:
        """Claim a new execution epoch after the previous owner is inactive/expired.

        Call once at execution start or recovery. Continue a live attempt only by
        renewing its returned token; never mint a replacement from a stale worker.
        """
        root_id, scope_id = _coordination_scope(resource, coordination_id)
        work = str(work_id).strip()
        owner = str(owner_id).strip()
        if not work or not owner or "\x00" in work + owner:
            raise ValueError("work_id and owner_id must be non-empty")
        now = float(self._clock())
        expires_at = now + self._ttl(ttl_seconds)
        attempt_id = uuid4().hex
        counter_key = self._attempt_counter_key(scope_id, work)

        def write() -> WorkAttemptFence:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                try:
                    con.execute(
                        "UPDATE writer_fence_attempts SET active=0 "
                        "WHERE (scope_id=? OR (resource=? AND scope_id=resource)) "
                        "AND work_id=? AND active=1 AND expires_at<=?",
                        (scope_id, root_id, work, now),
                    )
                    current = con.execute(
                        "SELECT attempt_id FROM writer_fence_attempts "
                        "WHERE (scope_id=? OR (resource=? AND scope_id=resource)) "
                        "AND work_id=? AND active=1 AND expires_at>?",
                        (scope_id, root_id, work, now),
                    ).fetchone()
                    if current is not None:
                        raise LeaseUnavailableError("work order already has a live execution owner")
                    row = con.execute(
                        "SELECT last_token FROM writer_fence_counters WHERE resource=?",
                        (counter_key,),
                    ).fetchone()
                    physical_row = con.execute(
                        "SELECT MAX(fencing_token) FROM writer_fence_attempts "
                        "WHERE resource=? AND work_id=?",
                        (root_id, work),
                    ).fetchone()
                    prior_token = max(
                        int(row[0]) if row is not None else 0,
                        int(physical_row[0]) if physical_row and physical_row[0] is not None else 0,
                    )
                    token = prior_token + 1
                    con.execute(
                        "INSERT INTO writer_fence_counters(resource,last_token) VALUES(?,?) "
                        "ON CONFLICT(resource) DO UPDATE SET last_token=excluded.last_token",
                        (counter_key, token),
                    )
                    con.execute(
                        """INSERT INTO writer_fence_attempts(
                            attempt_id,resource,scope_id,work_id,owner_id,fencing_token,expires_at,active
                        ) VALUES(?,?,?,?,?,?,?,1)""",
                        (attempt_id, root_id, scope_id, work, owner, token, expires_at),
                    )
                    con.execute("COMMIT")
                    return WorkAttemptFence(root_id, work, attempt_id, owner, token, expires_at, scope_id)
                except BaseException:
                    if con.in_transaction:
                        con.execute("ROLLBACK")
                    raise

        return retry_busy(write, retries=5, base_delay_seconds=0.02)

    def renew_attempt(
        self,
        attempt: WorkAttemptFence,
        *,
        ttl_seconds: float,
    ) -> WorkAttemptFence:
        """Extend only the current, unexpired attempt without changing its token."""
        now = float(self._clock())
        expires_at = now + self._ttl(ttl_seconds)

        def write() -> WorkAttemptFence:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                try:
                    self._assert_attempt(con, attempt)
                    updated = con.execute(
                        "UPDATE writer_fence_attempts SET expires_at=? "
                        "WHERE attempt_id=? AND owner_id=? AND fencing_token=? AND active=1",
                        (expires_at, attempt.attempt_id, attempt.owner_id, attempt.fencing_token),
                    )
                    if int(updated.rowcount or 0) != 1:
                        raise LeaseLostError("work attempt fence could not be renewed")
                    con.execute("COMMIT")
                    return replace(attempt, expires_at=expires_at)
                except BaseException:
                    if con.in_transaction:
                        con.execute("ROLLBACK")
                    raise

        return retry_busy(write, retries=5, base_delay_seconds=0.02)

    def release_attempt(self, attempt: WorkAttemptFence) -> bool:
        """Release this exact attempt; a stale token cannot release a newer epoch."""
        def write() -> bool:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                try:
                    updated = con.execute(
                        "UPDATE writer_fence_attempts SET active=0 "
                        "WHERE attempt_id=? AND resource=? AND work_id=? AND owner_id=? "
                        "AND fencing_token=? AND active=1",
                        (
                            attempt.attempt_id,
                            attempt.resource,
                            attempt.work_id,
                            attempt.owner_id,
                            attempt.fencing_token,
                        ),
                    )
                    con.execute("COMMIT")
                    return int(updated.rowcount or 0) == 1
                except BaseException:
                    if con.in_transaction:
                        con.execute("ROLLBACK")
                    raise

        return retry_busy(write, retries=5, base_delay_seconds=0.02)

    @staticmethod
    def _ttl(ttl_seconds: float) -> float:
        ttl = float(ttl_seconds)
        if not math.isfinite(ttl) or ttl <= 0 or ttl > MAX_TTL_SECONDS:
            raise ValueError(f"ttl_seconds must be in (0, {MAX_TTL_SECONDS}]")
        return ttl

    def acquire(
        self,
        resource: str | Path,
        owner_id: str,
        paths: Sequence[str],
        *,
        ttl_seconds: float,
        attempt: WorkAttemptFence,
        coordination_id: str | None | object = _COORDINATION_ID_UNSET,
    ) -> FencingLease:
        """Acquire a normalized exact path scope, bound to ``attempt`` for writes.

        Overlapping live scopes fail closed; disjoint scopes may coexist. Mutating
        callers must pass the current ``WorkAttemptFence`` and use ``commit_guard``.
        """
        root_id = canonical_resource(resource)
        if coordination_id is _COORDINATION_ID_UNSET and attempt.scope_id:
            scope_id = attempt.scope_id
        else:
            root_id, scope_id = _coordination_scope(resource, coordination_id)
        owner = str(owner_id).strip()
        if not owner or "\x00" in owner:
            raise ValueError("owner_id must be non-empty")
        scope = normalize_paths(paths)
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("lease clock must return a finite timestamp")
        expires_at = now + self._ttl(ttl_seconds)
        lease_id = uuid4().hex

        def write() -> FencingLease:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                try:
                    if attempt.resource != root_id or (attempt.scope_id or attempt.resource) != scope_id:
                        raise LeaseLostError("work attempt resource does not match path lease")
                    self._assert_attempt(con, attempt)
                    con.execute(
                        "UPDATE writer_fence_leases SET active=0 "
                        "WHERE (scope_id=? OR (resource=? AND scope_id=resource)) "
                        "AND active=1 AND expires_at<=?",
                        (scope_id, root_id, now),
                    )
                    parented = con.execute(
                        "SELECT lease_id,attempt_id,attempt_token FROM writer_fence_leases "
                        "WHERE (scope_id=? OR (resource=? AND scope_id=resource)) "
                        "AND active=1 AND expires_at>? AND attempt_id!=''",
                        (scope_id, root_id, now),
                    ).fetchall()
                    for old_lease_id, attempt_id, attempt_token in parented:
                        parent = con.execute(
                            "SELECT fencing_token,expires_at,active FROM writer_fence_attempts "
                            "WHERE attempt_id=?",
                            (str(attempt_id),),
                        ).fetchone()
                        if (
                            parent is None
                            or int(parent[0]) != int(attempt_token)
                            or float(parent[1]) <= now
                            or not bool(parent[2])
                        ):
                            con.execute(
                                "UPDATE writer_fence_leases SET active=0 WHERE lease_id=?",
                                (str(old_lease_id),),
                            )
                    live = con.execute(
                        "SELECT paths_json FROM writer_fence_leases "
                        "WHERE (scope_id=? OR (resource=? AND scope_id=resource)) "
                        "AND active=1 AND expires_at>?",
                        (scope_id, root_id, now),
                    ).fetchall()
                    for (raw_paths,) in live:
                        existing = tuple(json.loads(str(raw_paths)))
                        if _overlaps(scope, existing):
                            raise LeaseUnavailableError(
                                "an active writer owns an overlapping path scope"
                            )
                    row = con.execute(
                        "SELECT last_token FROM writer_fence_counters WHERE resource=?",
                        (scope_id,),
                    ).fetchone()
                    physical_row = con.execute(
                        "SELECT MAX(fencing_token) FROM writer_fence_leases "
                        "WHERE resource=? AND scope_id=resource",
                        (root_id,),
                    ).fetchone()
                    prior_token = max(
                        int(row[0]) if row is not None else 0,
                        int(physical_row[0])
                        if physical_row is not None and physical_row[0] is not None
                        else 0,
                    )
                    token = prior_token + 1
                    con.execute(
                        "INSERT INTO writer_fence_counters(resource,last_token) VALUES(?,?) "
                        "ON CONFLICT(resource) DO UPDATE SET last_token=excluded.last_token",
                        (scope_id, token),
                    )
                    con.execute(
                        """INSERT INTO writer_fence_leases(
                            lease_id,resource,owner_id,fencing_token,expires_at,paths_json,
                            attempt_id,attempt_token,scope_id,active
                        ) VALUES(?,?,?,?,?,?,?,?,?,1)""",
                        (
                            lease_id, root_id, owner, token, expires_at, json.dumps(scope),
                            attempt.attempt_id,
                            attempt.fencing_token,
                            scope_id,
                        ),
                    )
                    con.execute("COMMIT")
                    return FencingLease(
                        root_id,
                        lease_id,
                        owner,
                        token,
                        expires_at,
                        scope,
                        attempt.attempt_id,
                        attempt.fencing_token,
                        scope_id,
                    )
                except BaseException:
                    if con.in_transaction:
                        con.execute("ROLLBACK")
                    raise

        return retry_busy(write, retries=5, base_delay_seconds=0.02)

    def _assert_current(
        self,
        con: sqlite3.Connection,
        lease: FencingLease,
        actual_paths: Sequence[str],
    ) -> None:
        requested = normalize_paths(actual_paths) if actual_paths else ()
        requested_keys = {os.path.normcase(path).replace("\\", "/") for path in requested}
        lease_keys = {os.path.normcase(path).replace("\\", "/") for path in lease.paths}
        if not requested_keys.issubset(lease_keys):
            outside = sorted(requested_keys.difference(lease_keys))
            raise LeaseScopeError(f"write escaped fenced lease scope: {outside[0]}")
        now = float(self._clock())
        row = con.execute(
            """SELECT resource,owner_id,fencing_token,expires_at,paths_json,attempt_id,attempt_token,scope_id,active
               FROM writer_fence_leases WHERE lease_id=?""",
            (lease.lease_id,),
        ).fetchone()
        if row is None:
            raise LeaseLostError("writer lease no longer exists")
        resource, owner, token, expires_at, raw_paths, attempt_id, attempt_token, scope_id, active = row
        try:
            persisted_paths = tuple(json.loads(str(raw_paths)))
        except Exception as exc:
            raise LeaseLostError("writer lease scope is corrupt") from exc
        if (
            str(resource) != lease.resource
            or str(owner) != lease.owner_id
            or int(token) != lease.fencing_token
            or persisted_paths != lease.paths
            or str(attempt_id) != lease.attempt_id
            or int(attempt_token) != lease.attempt_token
            or str(scope_id) != (lease.scope_id or lease.resource)
        ):
            raise LeaseLostError("writer lease identity or fencing token changed")
        if not bool(active) or float(expires_at) <= now:
            raise LeaseLostError("writer lease expired or was superseded")
        if not lease.attempt_id or lease.attempt_token <= 0:
            raise LeaseLostError("writer lease requires a parent work attempt fencing token")
        attempt_row = con.execute(
            """SELECT resource,scope_id,fencing_token,expires_at,active
               FROM writer_fence_attempts WHERE attempt_id=?""",
            (lease.attempt_id,),
        ).fetchone()
        if attempt_row is None:
            raise LeaseLostError("parent work attempt fence no longer exists")
        attempt_resource, attempt_scope, attempt_token, attempt_expiry, attempt_active = attempt_row
        if (
            str(attempt_resource) != lease.resource
            or str(attempt_scope) != (lease.scope_id or lease.resource)
            or int(attempt_token) != lease.attempt_token
            or not bool(attempt_active)
            or float(attempt_expiry) <= now
        ):
            raise LeaseLostError("parent work attempt fence expired or was superseded")

    def assert_current(
        self,
        lease: FencingLease,
        actual_paths: Sequence[str] = (),
    ) -> None:
        """Preflight-only lease check; it is advisory and cannot guard a later write."""
        with closing(self._connect()) as con:
            con.execute("BEGIN")
            try:
                self._assert_current(con, lease, actual_paths)
                con.execute("COMMIT")
            except BaseException:
                if con.in_transaction:
                    con.execute("ROLLBACK")
                raise

    @contextmanager
    def commit_guard(
        self,
        lease: FencingLease,
        actual_paths: Sequence[str],
    ) -> Iterator[None]:
        """Fence a complete write/journal commit against expiry and reacquisition.

        The caller must perform every protected filesystem write and durable
        journal transition before leaving this context. Other lease operations
        use the same SQLite database and cannot change ownership until it exits.
        """
        if not actual_paths:
            raise ValueError("commit_guard requires the exact non-empty write set")
        if not lease.attempt_id or lease.attempt_token <= 0:
            raise LeaseLostError("commit requires a parent work attempt fencing token")
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            self._assert_current(con, lease, actual_paths)
            yield
            con.execute("COMMIT")
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def renew(self, lease: FencingLease, *, ttl_seconds: float) -> FencingLease:
        now = float(self._clock())
        expires_at = now + self._ttl(ttl_seconds)

        def write() -> FencingLease:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                try:
                    self._assert_current(con, lease, ())
                    updated = con.execute(
                        "UPDATE writer_fence_leases SET expires_at=? "
                        "WHERE lease_id=? AND owner_id=? AND fencing_token=? AND active=1",
                        (expires_at, lease.lease_id, lease.owner_id, lease.fencing_token),
                    )
                    if int(updated.rowcount or 0) != 1:
                        raise LeaseLostError("writer lease could not be renewed")
                    con.execute("COMMIT")
                    return replace(lease, expires_at=expires_at)
                except BaseException:
                    if con.in_transaction:
                        con.execute("ROLLBACK")
                    raise

        return retry_busy(write, retries=5, base_delay_seconds=0.02)

    def release(self, lease: FencingLease) -> bool:
        def write() -> bool:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                try:
                    updated = con.execute(
                        "UPDATE writer_fence_leases SET active=0 "
                        "WHERE lease_id=? AND resource=? AND owner_id=? "
                        "AND fencing_token=? AND active=1",
                        (lease.lease_id, lease.resource, lease.owner_id, lease.fencing_token),
                    )
                    con.execute("COMMIT")
                    return int(updated.rowcount or 0) == 1
                except BaseException:
                    if con.in_transaction:
                        con.execute("ROLLBACK")
                    raise

        return retry_busy(write, retries=5, base_delay_seconds=0.02)
