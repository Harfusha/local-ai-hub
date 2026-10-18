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
import re
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterator, Sequence
from uuid import uuid4

from .sqlite_support import connect_sqlite, initialize_wal, retry_busy, readonly_sqlite_connection


MAX_TTL_SECONDS = 24 * 60 * 60


_FENCE_TABLE_DDL = {
    "writer_fence_counters": """CREATE TABLE IF NOT EXISTS writer_fence_counters (
        resource TEXT PRIMARY KEY,
        last_token INTEGER NOT NULL CHECK(last_token >= 0)
    )""",
    "writer_fence_leases": """CREATE TABLE IF NOT EXISTS writer_fence_leases (
        lease_id TEXT PRIMARY KEY,
        resource TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        fencing_token INTEGER NOT NULL CHECK(fencing_token > 0),
        expires_at REAL NOT NULL,
        paths_json TEXT NOT NULL,
        attempt_id TEXT NOT NULL DEFAULT '',
        attempt_token INTEGER NOT NULL DEFAULT 0,
        scope_id TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL CHECK(active IN (0, 1)),
        work_id TEXT NOT NULL DEFAULT ''
    )""",
    "writer_fence_attempts": """CREATE TABLE IF NOT EXISTS writer_fence_attempts (
        attempt_id TEXT PRIMARY KEY,
        resource TEXT NOT NULL,
        scope_id TEXT NOT NULL DEFAULT '',
        work_id TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        fencing_token INTEGER NOT NULL CHECK(fencing_token > 0),
        expires_at REAL NOT NULL,
        active INTEGER NOT NULL CHECK(active IN (0, 1)),
        UNIQUE(resource, work_id, fencing_token)
    )""",
}
_FENCE_INDEX_DDL = {
    "idx_writer_attempt_scope": "CREATE INDEX IF NOT EXISTS idx_writer_attempt_scope ON writer_fence_attempts(scope_id, work_id, active, expires_at)",
    "idx_writer_fence_scope_live": "CREATE INDEX IF NOT EXISTS idx_writer_fence_scope_live ON writer_fence_leases(scope_id, active, expires_at)",
    "idx_writer_attempt_current": "CREATE INDEX IF NOT EXISTS idx_writer_attempt_current ON writer_fence_attempts(resource, work_id, active, expires_at)",
    "idx_writer_fence_live": "CREATE INDEX IF NOT EXISTS idx_writer_fence_live ON writer_fence_leases(resource, active, expires_at)",
}


def _fence_ddl_identity(sql: str) -> str:
    value = " ".join(sql.upper().split()).rstrip(";")
    value = value.replace(" IF NOT EXISTS ", " ")
    return re.sub(r"\s*([(),])\s*", r"\1", value)


def _validate_fence_schema(connection: sqlite3.Connection) -> None:
    """Reject incompatible stored fences; runtime never repairs ownership."""
    deadline = time.monotonic() + 2.0
    connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    try:
        rows = connection.execute(
            "SELECT name, type, CASE WHEN length(CAST(sql AS BLOB)) <= 16384 THEN sql END "
            "FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
        ).fetchmany(65)
        if not rows:
            return
        expected = {**_FENCE_TABLE_DDL, **_FENCE_INDEX_DDL}
        if len(rows) != len(expected) or {str(row[0]) for row in rows} != set(expected):
            raise ValueError("writer fence schema requires explicit offline conversion")
        for name, kind, sql in rows:
            expected_kind = "table" if name in _FENCE_TABLE_DDL else "index"
            if kind != expected_kind or not isinstance(sql, str) or len(sql) > 16384:
                raise ValueError("invalid writer fence schema; offline conversion required")
            if _fence_ddl_identity(sql) != _fence_ddl_identity(expected[name]):
                raise ValueError("writer fence schema differs from the canonical contract; offline conversion required")
        for table in ("writer_fence_leases", "writer_fence_attempts"):
            if connection.execute(
                f"SELECT 1 FROM {table} WHERE scope_id IS NULL OR scope_id='' LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("writer fence has no scope; explicit offline conversion required")
    finally:
        connection.set_progress_handler(None, 0)


def _preflight_fence_schema(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        return
    with readonly_sqlite_connection(path) as connection:
        _validate_fence_schema(connection)


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
    if not isinstance(resource, (str, Path)):
        raise ValueError("resource must be a non-empty filesystem root")
    value = str(resource).strip()
    if not value or "\x00" in value:
        raise ValueError("resource must be a non-empty filesystem root")
    return os.path.normcase(str(Path(value).expanduser().resolve(strict=False)))


def _coordination_scope(
    resource: str | Path,
    coordination_id: str | None | object,
) -> tuple[str, str]:
    if coordination_id is None:
        raise ValueError("project coordination id is required")
    if coordination_id is _COORDINATION_ID_UNSET:
        physical = canonical_resource(resource)
        return physical, physical
    if not isinstance(coordination_id, str):
        raise ValueError("invalid project coordination id")
    namespace = coordination_id.strip()
    if not namespace or "\x00" in namespace or len(namespace) > 512:
        raise ValueError("invalid project coordination id")
    physical = canonical_resource(resource)
    return physical, f"project:{namespace}"


def is_safe_lease_path(path: Any) -> bool:
    """Return True if path is a safe relative lease path."""
    if not isinstance(path, str) or isinstance(path, bool):
        return False
    raw = path.replace("\\", "/")
    if not raw or "\x00" in raw:
        return False
    windows = PureWindowsPath(raw)
    posix = PurePosixPath(raw)
    parts = raw.split("/")
    if (
        windows.drive
        or windows.root
        or posix.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
    ):
        return False
    return True


def normalize_paths(
    paths: Sequence[str], *, root: str | Path | None = None
) -> tuple[str, ...]:
    if (
        not isinstance(paths, Sequence)
        or isinstance(paths, (str, bytes, bytearray))
        or not paths
    ):
        raise ValueError("writer lease paths must be a sequence of exact paths")
    if root is not None and (not isinstance(root, (str, Path)) or "\x00" in str(root)):
        raise ValueError("invalid root path")
    normalized: set[str] = set()
    resolved_root = Path(root).resolve(strict=False) if root is not None else None
    for value in paths:
        if not is_safe_lease_path(value):
            raise ValueError(f"unsafe lease path: {value!r}")
        raw = value.replace("\\", "/")
        parts = raw.split("/")
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
    if not left or not right:
        return False
    left_keys = tuple(os.path.normcase(path).replace("\\", "/") for path in left if isinstance(path, str))
    right_keys = tuple(os.path.normcase(path).replace("\\", "/") for path in right if isinstance(path, str))
    for first in left_keys:
        for second in right_keys:
            if (
                first == second
                or first.startswith(second + "/")
                or second.startswith(first + "/")
            ):
                return True
    return False


def are_paths_disjoint(left: Sequence[str], right: Sequence[str]) -> bool:
    """Return True if left and right path scopes do not overlap."""
    return not _overlaps(left, right)


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
            _preflight_fence_schema(self.path)

            def setup() -> None:
                with closing(self._connect()) as con:
                    _validate_fence_schema(con)
                    initialize_wal(con)
                    con.execute("BEGIN IMMEDIATE")
                    try:
                        _validate_fence_schema(con)
                        for ddl in _FENCE_TABLE_DDL.values():
                            con.execute(ddl)
                        for ddl in _FENCE_INDEX_DDL.values():
                            con.execute(ddl)
                        con.execute("COMMIT")
                    except BaseException:
                        if con.in_transaction:
                            con.execute("ROLLBACK")
                        raise

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
        if not isinstance(work_id, str) or not isinstance(owner_id, str):
            raise ValueError("work_id and owner_id must be non-empty strings")
        work = work_id.strip()
        owner = owner_id.strip()
        if not work or not owner or "\x00" in work + owner:
            raise ValueError("work_id and owner_id must be non-empty strings")
        root_id, scope_id = _coordination_scope(resource, coordination_id)
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
        if isinstance(ttl_seconds, bool):
            raise ValueError(f"ttl_seconds must be in (0, {MAX_TTL_SECONDS}]")
        try:
            ttl = float(ttl_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"ttl_seconds must be in (0, {MAX_TTL_SECONDS}]") from exc
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
        if not isinstance(owner_id, str):
            raise ValueError("owner_id must be a non-empty string")
        owner = owner_id.strip()
        if not owner or "\x00" in owner:
            raise ValueError("owner_id must be a non-empty string")
        scope = normalize_paths(paths)
        root_id = canonical_resource(resource)
        if coordination_id is _COORDINATION_ID_UNSET and attempt.scope_id:
            scope_id = attempt.scope_id
        else:
            root_id, scope_id = _coordination_scope(resource, coordination_id)
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
                        try:
                            decoded_paths = json.loads(raw_paths)
                            if not isinstance(decoded_paths, list):
                                raise ValueError("live lease paths are not a list")
                            existing = normalize_paths(decoded_paths)
                        except (json.JSONDecodeError, TypeError, ValueError) as exc:
                            raise LeaseUnavailableError(
                                "an active writer has a corrupt path scope"
                            ) from exc
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
                            lease_id, root_id, owner, token, expires_at, json.dumps(scope, separators=(",", ":")),
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
        outside = [
            req
            for req in sorted(requested_keys)
            if not any(req == lk or req.startswith(lk + "/") for lk in lease_keys)
        ]
        if outside:
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
            self._assert_current(con, lease, actual_paths)
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

    def get_active_attempt(
        self,
        resource: str | Path,
        work_id: str,
        *,
        coordination_id: str | None | object = _COORDINATION_ID_UNSET,
    ) -> WorkAttemptFence | None:
        """Return the active unexpired WorkAttemptFence for work_id, or None."""
        if type(work_id) is not str or not work_id.strip() or "\x00" in work_id:
            raise ValueError("work_id must be a non-empty string")
        clean_work_id = work_id.strip()
        root_id, scope_id = _coordination_scope(resource, coordination_id)
        now = float(self._clock())
        with closing(self._connect()) as con:
            row = con.execute(
                """SELECT resource,scope_id,work_id,owner_id,fencing_token,expires_at,attempt_id
                   FROM writer_fence_attempts
                   WHERE (scope_id=? OR (resource=? AND scope_id=resource))
                   AND work_id=? AND active=1 AND expires_at>?""",
                (scope_id, root_id, clean_work_id, now),
            ).fetchone()
            if row is None:
                return None
            res, sc_id, wk, own, tok, exp, att_id = row
            return WorkAttemptFence(
                resource=str(res),
                work_id=str(wk),
                attempt_id=str(att_id),
                owner_id=str(own),
                fencing_token=int(tok),
                expires_at=float(exp),
                scope_id=str(sc_id),
            )

    def get_active_leases(
        self,
        resource: str | Path,
        *,
        coordination_id: str | None | object = _COORDINATION_ID_UNSET,
    ) -> list[FencingLease]:
        """Return all active, unexpired FencingLease records for this resource scope."""
        root_id, scope_id = _coordination_scope(resource, coordination_id)
        now = float(self._clock())
        with closing(self._connect()) as con:
            rows = con.execute(
                """SELECT resource,lease_id,owner_id,fencing_token,expires_at,paths_json,
                          attempt_id,attempt_token,scope_id
                   FROM writer_fence_leases
                   WHERE (scope_id=? OR (resource=? AND scope_id=resource))
                   AND active=1 AND expires_at>?""",
                (scope_id, root_id, now),
            ).fetchall()
            leases: list[FencingLease] = []
            for r in rows:
                try:
                    decoded_paths = json.loads(str(r[5]))
                    if not isinstance(decoded_paths, list):
                        raise ValueError("live lease paths are not a list")
                    paths = tuple(normalize_paths(decoded_paths))
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    raise LeaseUnavailableError(
                        "an active writer has a corrupt path scope"
                    ) from exc
                leases.append(
                    FencingLease(
                        resource=str(r[0]),
                        lease_id=str(r[1]),
                        owner_id=str(r[2]),
                        fencing_token=int(r[3]),
                        expires_at=float(r[4]),
                        paths=paths,
                        attempt_id=str(r[6]),
                        attempt_token=int(r[7]),
                        scope_id=str(r[8]),
                    )
                )
            return leases

    def is_path_locked(
        self,
        resource: str | Path,
        path: str,
        *,
        coordination_id: str | None | object = _COORDINATION_ID_UNSET,
    ) -> bool:
        """Return True if path overlaps with any active live lease."""
        active_leases = self.get_active_leases(resource, coordination_id=coordination_id)
        norm = normalize_paths([path])
        return any(_overlaps(norm, lease.paths) for lease in active_leases)

    def prune_expired(self) -> int:
        """Deactivate expired attempts and leases across all resources, returning count."""
        now = float(self._clock())

        def write() -> int:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                try:
                    cur1 = con.execute(
                        "UPDATE writer_fence_attempts SET active=0 WHERE active=1 AND expires_at<=?",
                        (now,),
                    )
                    cur2 = con.execute(
                        "UPDATE writer_fence_leases SET active=0 WHERE active=1 AND expires_at<=?",
                        (now,),
                    )
                    con.execute("COMMIT")
                    return int(cur1.rowcount or 0) + int(cur2.rowcount or 0)
                except BaseException:
                    if con.in_transaction:
                        con.execute("ROLLBACK")
                    raise

        return retry_busy(write, retries=5, base_delay_seconds=0.02)

