from __future__ import annotations

from .json_utils import dumps as json_dumps

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, retry_busy
from .process_utils import canonical_root

_WORKSPACE_MEMORY_BACKUP_SUFFIX = ".pre-memo-version.bak"


class WorkspaceMemoryStore:
    """Small shared, TTL-bounded handoff memo store for concurrent agents.

    This intentionally stores only data agents explicitly write to it. It is not an
    automatic conversation logger and is not used as hidden long-term memory.

    This is trusted-local shared state, not a multi-tenant authorization boundary.
    Memos are shared by every local agent using the same canonical workspace and key;
    the tenant field records provenance and can select deletes, but it does not
    restrict reads or prove caller identity. A later write replaces the earlier
    value (last writer wins) unless a writer supplies an expected version to reject
    stale replacement. Compact per-key version rows remain after deletion so stale
    writers cannot recreate older generations. Private identity-scoped memory needs
    authenticated identity in every key and access check.
    """

    def __init__(self, state_dir: Path, default_ttl_hours: int = 168, max_value_chars: int = 6000):
        self.path = state_dir / "workspace_memory.sqlite3"
        self.default_ttl = max(3600, int(default_ttl_hours) * 3600)
        self.max_value_chars = max(512, int(max_value_chars))
        self._lock = threading.RLock()
        self._initialized = False
        state_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=0.75)
    @staticmethod
    def _database_content_digest(database: sqlite3.Connection) -> bytes:
        digest = hashlib.sha256()
        for statement in database.iterdump():
            digest.update(statement.encode("utf-8"))
            digest.update(b"\n")
        return digest.digest()

    def _create_migration_backup(self) -> None:
        backup_path = self.path.with_name(self.path.name + _WORKSPACE_MEMORY_BACKUP_SUFFIX)
        if backup_path.exists():
            if not backup_path.is_file():
                raise sqlite3.DatabaseError("workspace memory migration backup path is not a file")
            if not backup_path.is_symlink() and not backup_path.samefile(self.path):
                with closing(sqlite3.connect(str(backup_path))) as existing:
                    integrity = existing.execute("PRAGMA integrity_check").fetchone()
                    if integrity != ("ok",):
                        raise sqlite3.DatabaseError("workspace memory migration backup integrity check failed")
                    with closing(sqlite3.connect(str(self.path))) as current:
                        if self._database_content_digest(existing) == self._database_content_digest(current):
                            return

        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=backup_path.name + ".",
            suffix=".tmp",
            dir=str(backup_path.parent),
        )
        os.close(file_descriptor)
        temporary_path = Path(temporary_name)
        try:
            with closing(sqlite3.connect(str(self.path))) as source, closing(
                sqlite3.connect(str(temporary_path))
            ) as backup:
                source.backup(backup)
                backup.commit()
                integrity = backup.execute("PRAGMA integrity_check").fetchone()
                snapshot_digest = self._database_content_digest(source)
                backup_digest = self._database_content_digest(backup)
            if integrity != ("ok",) or backup_digest != snapshot_digest:
                raise sqlite3.DatabaseError("workspace memory migration backup verification failed")
            os.replace(temporary_path, backup_path)
            with closing(sqlite3.connect(str(backup_path))) as verified:
                integrity = verified.execute("PRAGMA integrity_check").fetchone()
                verified_digest = self._database_content_digest(verified)
            if integrity != ("ok",) or verified_digest != snapshot_digest:
                raise sqlite3.DatabaseError("workspace memory migration backup verification failed")
            if backup_path.samefile(self.path):
                raise sqlite3.DatabaseError("workspace memory migration backup aliases the live database")
        except BaseException:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _init_db(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            def _setup() -> None:
                with closing(self._connect()) as con:
                    initialize_wal(con)
                    con.execute("BEGIN IMMEDIATE")
                    memo_table_exists = bool(con.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memos'"
                    ).fetchone())
                    versions_table_exists = bool(con.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memo_versions'"
                    ).fetchone())
                    columns = {str(row[1]) for row in con.execute("PRAGMA table_info(memos)")} if memo_table_exists else set()
                    missing_generations = False
                    if memo_table_exists and versions_table_exists:
                        missing_generations = con.execute(
                            """SELECT 1 FROM memos AS m
                               LEFT JOIN memo_versions AS v
                                 ON v.workspace=m.workspace AND v.memo_key=m.memo_key
                               WHERE v.memo_key IS NULL LIMIT 1"""
                        ).fetchone() is not None
                    if memo_table_exists and (
                        "version" not in columns or not versions_table_exists or missing_generations
                    ):
                        self._create_migration_backup()
                    con.execute(
                        """CREATE TABLE IF NOT EXISTS memos (
                            workspace TEXT NOT NULL,
                            memo_key TEXT NOT NULL,
                            value TEXT NOT NULL,
                            tenant TEXT NOT NULL,
                            metadata TEXT NOT NULL,
                            updated_at REAL NOT NULL,
                            expires_at REAL NOT NULL,
                            version INTEGER NOT NULL DEFAULT 1,
                            PRIMARY KEY(workspace, memo_key)
                        )"""
                    )
                    columns = {str(row[1]) for row in con.execute("PRAGMA table_info(memos)")}
                    if "version" not in columns:
                        con.execute("ALTER TABLE memos ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
                    con.execute(
                        """CREATE TABLE IF NOT EXISTS memo_versions (
                            workspace TEXT NOT NULL,
                            memo_key TEXT NOT NULL,
                            version INTEGER NOT NULL,
                            PRIMARY KEY(workspace, memo_key)
                        )"""
                    )
                    con.execute(
                        """INSERT OR IGNORE INTO memo_versions(workspace,memo_key,version)
                           SELECT workspace,memo_key,version FROM memos"""
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
        key = " ".join(key.strip().split())
        if not key or len(key) > 160:
            raise ValueError("memo key must be 1..160 characters")
        return key

    @staticmethod
    def _clean_tenant(tenant: str) -> str:
        if not isinstance(tenant, str):
            raise ValueError("memo tenant label must be a string")
        tenant = tenant.strip()
        if not tenant or len(tenant) > 128:
            raise ValueError("memo tenant label must be 1..128 characters")
        return tenant

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
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        workspace = self.workspace_id(root)
        key = self._clean_key(key)
        tenant = self._clean_tenant(tenant)
        if not isinstance(value, str):
            raise ValueError("memo value must be a string")
        value = value.strip()
        if not value:
            raise ValueError("memo value must not be empty")
        if expected_version is not None and (type(expected_version) is not int or expected_version < 0):
            raise ValueError("memo expected_version must be a non-negative integer")
        truncated = len(value) > self.max_value_chars
        if truncated:
            value = value[: self.max_value_chars] + "\n[... memo truncated ...]"
        ttl = self.default_ttl if ttl_seconds is None else max(300, min(int(ttl_seconds), 30 * 86400))
        now = time.time()
        meta = metadata if isinstance(metadata, dict) else {}
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
                    """INSERT INTO memos(workspace,memo_key,value,tenant,metadata,updated_at,expires_at,version)
                       VALUES(?,?,?,?,?,?,?,?)
                       ON CONFLICT(workspace,memo_key) DO UPDATE SET
                           value=excluded.value, tenant=excluded.tenant, metadata=excluded.metadata,
                           updated_at=excluded.updated_at, expires_at=excluded.expires_at,
                           version=excluded.version""",
                    (workspace, key, value, tenant, json_dumps(meta, ensure_ascii=False), now, now + ttl, version),
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
            "tenant": tenant,
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
                    "SELECT value,tenant,metadata,updated_at,expires_at,version FROM memos WHERE workspace=? AND memo_key=? AND expires_at>?",
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
            "tenant": row[1],
            "metadata": json.loads(row[2] or "{}"),
            "updated_at": row[3],
            "expires_at": row[4],
            "version": int(row[5]),
        }

    def search(self, root: str, query: str = "", limit: int = 12) -> dict[str, Any]:
        workspace = self.workspace_id(root)
        terms = [x.lower() for x in str(query).split() if len(x) >= 2][:12]
        limit = max(1, min(int(limit), 50))
        now = time.time()
        def read():
            with closing(self._connect()) as con:
                return con.execute(
                    "SELECT memo_key,value,tenant,metadata,updated_at,expires_at,version FROM memos WHERE workspace=? AND expires_at>? ORDER BY updated_at DESC LIMIT 200",
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
                "scope": "workspace-shared",
                "metadata": json.loads(row[3] or "{}"), "updated_at": row[4], "expires_at": row[5], "score": score,
                "version": int(row[6]),
            })
        items.sort(key=lambda x: (-x["score"], -x["updated_at"]))
        return {"success": True, "workspace": workspace, "scope": "workspace-shared", "results": items[:limit]}

    def delete(self, root: str, key: str, tenant: str = "", *, scope: str | None = None) -> dict[str, Any]:
        workspace = self.workspace_id(root)
        key = self._clean_key(key)
        if tenant != "":
            tenant = self._clean_tenant(tenant)
        if scope is not None:
            if not isinstance(scope, str) or scope.strip().lower() not in {"global", "tenant"}:
                raise ValueError("memo delete scope must be 'global' or 'tenant'")
            scope = scope.strip().lower()
            if scope == "tenant" and not tenant:
                return {
                    "success": False,
                    "error": "tenant is required for tenant-scoped memory delete",
                    "workspace": workspace,
                    "key": key,
                    "scope": "workspace-shared",
                    "deleted": False,
                }
            if scope == "global":
                tenant = ""
        def write() -> tuple[int, int]:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                if tenant:
                    row = con.execute("SELECT version FROM memos WHERE workspace=? AND memo_key=? AND tenant=?", (workspace, key, tenant)).fetchone()
                else:
                    row = con.execute("SELECT version FROM memos WHERE workspace=? AND memo_key=?", (workspace, key)).fetchone()
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
                if tenant:
                    cur = con.execute("DELETE FROM memos WHERE workspace=? AND memo_key=? AND tenant=?", (workspace, key, tenant))
                else:
                    cur = con.execute("DELETE FROM memos WHERE workspace=? AND memo_key=?", (workspace, key))
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
