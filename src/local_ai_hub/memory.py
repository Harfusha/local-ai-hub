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
        hours = _safe_positive_int(default_ttl_hours, 168, minimum=1)
        self.default_ttl = max(3600, hours * 3600)
        self.max_value_chars = _safe_positive_int(max_value_chars, 6000, minimum=512)
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
        key = " ".join(_clean_text(key).strip().split())
        if not key or len(key) > 160:
            raise ValueError("memo key must be 1..160 characters")
        return key

    @staticmethod
    def _clean_tenant(tenant: str) -> str:
        if not isinstance(tenant, str):
            raise ValueError("memo tenant label must be a string")
        tenant = _clean_text(tenant).strip()
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
                    """INSERT INTO memos(workspace,memo_key,value,tenant,metadata,updated_at,expires_at,version)
                       VALUES(?,?,?,?,?,?,?,?)
                       ON CONFLICT(workspace,memo_key) DO UPDATE SET
                           value=excluded.value, tenant=excluded.tenant, metadata=excluded.metadata,
                           updated_at=excluded.updated_at, expires_at=excluded.expires_at,
                           version=excluded.version""",
                    (workspace, key, value, tenant, meta_json, now, now + ttl, version),
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
            "metadata": _safe_metadata_dict(row[2]),
            "updated_at": row[3],
            "expires_at": row[4],
            "version": int(row[5]),
        }

    def search(self, root: str, query: str = "", limit: int = 12) -> dict[str, Any]:
        workspace = self.workspace_id(root)
        terms = [x.lower() for x in _clean_text(query).split() if len(x) >= 2][:12]
        safe_limit = _safe_positive_int(limit, 12, minimum=1, maximum=50)
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
                "metadata": _safe_metadata_dict(row[3]), "updated_at": row[4], "expires_at": row[5], "score": score,
                "version": int(row[6]),
            })
        items.sort(key=lambda x: (-x["score"], -x["updated_at"]))
        return {"success": True, "workspace": workspace, "scope": "workspace-shared", "results": items[:safe_limit]}

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
