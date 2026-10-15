from __future__ import annotations

from .json_utils import dumps as json_dumps

import base64
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, retry_busy


DEFAULT_MAX_BINARY_BYTES = 4_000_000
DEFAULT_MAX_JSON_BYTES = 4_000_000
_ARTIFACT_TABLE = "artifacts"
_ARTIFACT_V2_TABLE = "artifacts_v2"
_ARTIFACT_PAGING_TABLE = "artifact_paging_metadata"
MAX_ARTIFACT_SLICES = 16
MAX_ARTIFACT_SLICE_CHARS = 50_000
_ARTIFACT_MIGRATION_BACKUP_SUFFIX = ".pre-tenant-identity.bak"


class ArtifactTransportError(ValueError):
    """Bounded, caller-safe artifact transport failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ArtifactBatchCancelled(RuntimeError):
    """Raised when a caller cancels an artifact batch before commit."""


class _ArtifactBatch:
    def __init__(self, store: "ArtifactStore", tenant: str, cancel_check=None):
        self._store = store
        self._tenant = tenant
        self._tenant_identity = store._tenant_identity(self._tenant)
        self._cancel_check = cancel_check
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> "_ArtifactBatch":
        def _begin() -> None:
            connection = self._store._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
            except BaseException:
                connection.close()
                raise
            self._connection = connection

        retry_busy(_begin, retries=4)
        try:
            self._store._purge(self._connection)
            self._check_cancelled()
            return self
        except BaseException:
            self._rollback_and_close()
            raise

    def __exit__(self, exc_type, exc, traceback) -> bool:
        connection = self._connection
        if connection is None:
            return False
        try:
            if exc_type is None:
                self._check_cancelled()
                connection.commit()
            else:
                connection.rollback()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
            self._connection = None
        return False

    def _rollback_and_close(self) -> None:
        connection = self._connection
        if connection is not None:
            try:
                if connection.in_transaction:
                    connection.rollback()
            finally:
                connection.close()
                self._connection = None

    def _check_cancelled(self) -> None:
        if self._cancel_check is not None and self._cancel_check():
            raise ArtifactBatchCancelled("artifact batch cancelled")

    def put(self, text: str, kind: str) -> str:
        if self._connection is None:
            raise RuntimeError("artifact batch is not active")
        self._check_cancelled()
        digest = hashlib.sha256((kind + "\0" + text).encode("utf-8")).hexdigest()[:24]
        artifact_id = self._store._scoped_artifact_id(self._connection, f"art_{digest}", self._tenant_identity)
        section_names = self._store._section_names(text)
        page_text, nul_mask = self._store._page_text_metadata(text)
        self._connection.execute(
            f"INSERT OR REPLACE INTO {self._store._table}(artifact_id, created_at, tenant, tenant_identity, kind, text) VALUES(?,?,?,?,?,?)",
            (artifact_id, time.time(), self._tenant_identity, self._tenant_identity, kind, text),
        )
        self._store._write_paging_metadata(
            self._connection, artifact_id, text, section_names, page_text, nul_mask,
        )
        return artifact_id

    def put_json(self, value: dict[str, Any], kind: str) -> str:
        if not isinstance(value, dict):
            raise ArtifactTransportError("invalid_json", "JSON artifact must be an object")
        text = json_dumps(value, ensure_ascii=False, sort_keys=True)
        if len(text.encode("utf-8")) > self._store.max_json_bytes:
            raise ArtifactTransportError("artifact_too_large", "JSON artifact size exceeds configured limit")
        return self.put(text, kind)

    def put_bytes(self, data: bytes, kind: str, mime_type: str) -> str:
        if self._connection is None:
            raise RuntimeError("artifact batch is not active")
        self._check_cancelled()
        if not isinstance(data, bytes):
            raise ArtifactTransportError("invalid_bytes", "artifact bytes must be bytes")
        normalized_mime = str(mime_type or "").strip().lower()
        if not normalized_mime.startswith("image/"):
            raise ArtifactTransportError("invalid_mime_type", "image MIME type required")
        if len(data) > self._store.max_binary_bytes:
            raise ArtifactTransportError("artifact_too_large", "artifact size exceeds configured limit")

        checksum = hashlib.sha256(data).hexdigest()
        base_id = "art_" + hashlib.sha256(
            (str(kind) + "\0" + normalized_mime + "\0" + checksum).encode("utf-8")
        ).hexdigest()[:24]
        artifact_id = self._store._scoped_artifact_id(self._connection, base_id, self._tenant_identity)
        identity = {
            "artifact_id": artifact_id,
            "kind": str(kind),
            "mime_type": normalized_mime,
            "encoding": "base64",
            "size_bytes": len(data),
            "checksum": checksum,
        }
        self._connection.execute(
            f"DELETE FROM {_ARTIFACT_PAGING_TABLE} WHERE artifact_id=?", (artifact_id,),
        )
        self._connection.execute(
            f"""INSERT OR REPLACE INTO {self._store._table}(
                artifact_id, created_at, tenant, tenant_identity, kind, text, mime_type,
                encoding, blob, size_bytes, checksum, identity_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                artifact_id, time.time(), self._tenant_identity, self._tenant_identity,
                str(kind), "", normalized_mime, "base64", sqlite3.Binary(data), len(data), checksum,
                json_dumps(identity, ensure_ascii=False),
            ),
        )
        return artifact_id


class ArtifactStore:
    """Store verbose local outputs and return compact references.

    Tenant labels partition trusted-local data but do not authenticate callers.
    """

    def __init__(
        self,
        state_dir: Path,
        ttl_hours: int = 72,
        max_inline_chars: int = 6000,
        max_binary_bytes: int = DEFAULT_MAX_BINARY_BYTES,
        max_json_bytes: int = DEFAULT_MAX_JSON_BYTES,
    ):
        self.path = state_dir / "artifacts.sqlite3"
        self.ttl_seconds = max(3600, int(ttl_hours) * 3600)
        self.max_inline_chars = max(1000, int(max_inline_chars))
        self.max_binary_bytes = max(1, int(max_binary_bytes))
        self.max_json_bytes = max(1, int(max_json_bytes))
        self._last_purge = 0.0
        self._purge_interval = 1800.0
        state_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialized = False
        self._table = _ARTIFACT_TABLE
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = connect_sqlite(self.path, timeout_seconds=0.75)
        try:
            con.execute("PRAGMA cache_size=-32768")
            con.execute("PRAGMA mmap_size=268435456")
        except sqlite3.OperationalError:
            pass
        return con

    def _ensure_paging_metadata(self, con: sqlite3.Connection) -> None:
        table = self._table
        con.execute(
            f"""CREATE TABLE IF NOT EXISTS {_ARTIFACT_PAGING_TABLE} (
                artifact_id TEXT PRIMARY KEY,
                char_count INTEGER NOT NULL,
                section_names TEXT NOT NULL,
                page_text TEXT,
                nul_mask BLOB
            )"""
        )
        cutoff = time.time() - self.ttl_seconds
        # Bound work per initialization and fetch only IDs before loading bodies.
        artifact_ids = [str(row[0]) for row in con.execute(
            f"""SELECT a.artifact_id FROM {table} AS a
                LEFT JOIN {_ARTIFACT_PAGING_TABLE} AS p ON p.artifact_id=a.artifact_id
                WHERE p.artifact_id IS NULL AND a.mime_type IS NULL AND a.created_at>=?
                ORDER BY a.created_at, a.artifact_id LIMIT 128""",
            (cutoff,),
        ).fetchall()]
        for artifact_id in artifact_ids:
            row = con.execute(f"SELECT text FROM {table} WHERE artifact_id=?", (artifact_id,)).fetchone()
            if row is None:
                continue
            text = str(row[0] or "")
            section_names = self._section_names(text)
            page_text, nul_mask = self._page_text_metadata(text)
            self._write_paging_metadata(
                con, artifact_id, text, section_names, page_text, nul_mask,
            )

    @staticmethod
    def _write_paging_metadata(
        con: sqlite3.Connection,
        artifact_id: str,
        text: str,
        section_names: list[str],
        page_text: str | None,
        nul_mask: bytes | None,
    ) -> None:
        con.execute(
            f"""INSERT INTO {_ARTIFACT_PAGING_TABLE}
                (artifact_id, char_count, section_names, page_text, nul_mask)
                VALUES(?,?,?,?,?) ON CONFLICT(artifact_id) DO UPDATE SET
                char_count=excluded.char_count, section_names=excluded.section_names,
                page_text=excluded.page_text, nul_mask=excluded.nul_mask""",
            (artifact_id, len(text), json.dumps(section_names, ensure_ascii=False, separators=(",", ":")), page_text, nul_mask),
        )

    @staticmethod
    def _page_text_metadata(text: str) -> tuple[str | None, bytes | None]:
        """Make SQLite substr lossless for NUL while keeping its paging payload bounded."""
        if "\x00" not in text:
            return None, None
        mask = bytearray((len(text) + 7) // 8)
        for index, character in enumerate(text):
            if character == "\x00":
                mask[index // 8] |= 1 << (index % 8)
        return text.replace("\x00", "\ufffd"), bytes(mask)

    @staticmethod
    def _tenant_identity(tenant: str) -> str:
        """Hash a trusted-local namespace label without retaining its caller-controlled text."""
        if not isinstance(tenant, str):
            raise ValueError("tenant label must be a string")
        return hashlib.sha256(tenant.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_tenant_identity(value: str) -> bool:
        return len(value) == 64 and all(character in "0123456789abcdef" for character in value)

    @staticmethod
    def _database_content_digest(database: sqlite3.Connection) -> bytes:
        digest = hashlib.sha256()
        for statement in database.iterdump():
            digest.update(statement.encode("utf-8"))
            digest.update(b"\n")
        return digest.digest()

    def _create_migration_backup(self) -> None:
        """Create and verify one pre-migration SQLite backup without using the writer connection."""
        backup_path = self.path.with_name(self.path.name + _ARTIFACT_MIGRATION_BACKUP_SUFFIX)
        if backup_path.exists():
            if not backup_path.is_file():
                raise sqlite3.DatabaseError("artifact migration backup path is not a file")
            if not backup_path.is_symlink() and not backup_path.samefile(self.path):
                with closing(sqlite3.connect(str(backup_path))) as existing:
                    integrity = existing.execute("PRAGMA integrity_check").fetchone()
                    if integrity != ("ok",):
                        raise sqlite3.DatabaseError("artifact migration backup integrity check failed")
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
            # Use a second source connection: SQLite backup on the active writer can stall.
            with closing(sqlite3.connect(str(self.path))) as source, closing(
                sqlite3.connect(str(temporary_path))
            ) as backup:
                source.backup(backup)
                backup.commit()
                integrity = backup.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                raise sqlite3.DatabaseError("artifact migration backup integrity check failed")
            os.replace(temporary_path, backup_path)
            with closing(sqlite3.connect(str(backup_path))) as verified:
                integrity = verified.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                raise sqlite3.DatabaseError("artifact migration backup integrity check failed")
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
                    meta_exists = bool(con.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='artifact_schema_meta'"
                    ).fetchone())
                    marker = con.execute(
                        "SELECT value FROM artifact_schema_meta WHERE key=?",
                        ("tenant_storage",),
                    ).fetchone() if meta_exists else None
                    marker_value = str(marker[0]) if marker else ""
                    v2_exists = bool(con.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (_ARTIFACT_V2_TABLE,),
                    ).fetchone())
                    full_schema = {
                        "artifact_id", "created_at", "tenant", "tenant_identity", "kind", "text",
                        "mime_type", "encoding", "blob", "size_bytes", "checksum", "identity_json",
                    }
                    table_info = list(con.execute("PRAGMA table_info(artifacts)"))
                    existing_columns = {str(row[1]) for row in table_info}
                    if marker_value not in {"", "legacy-raw-v1", "sha256-v1"}:
                        raise sqlite3.DatabaseError("unsupported artifact tenant storage marker")

                    primary_identity_conflict = False
                    if marker_value == "sha256-v1" and full_schema.issubset(existing_columns):
                        primary_identity_conflict = any(
                            not self._is_tenant_identity(str(tenant))
                            or str(tenant_identity) != str(tenant)
                            for tenant, tenant_identity in con.execute(
                                "SELECT tenant, tenant_identity FROM artifacts"
                            )
                        )
                    v2_repair_needed = False
                    if (
                        marker_value == "sha256-v1"
                        and v2_exists
                        and existing_columns
                        and not full_schema.issubset(existing_columns)
                    ):
                        source_tenants = {
                            str(artifact_id): str(tenant)
                            for artifact_id, tenant in con.execute("SELECT artifact_id, tenant FROM artifacts")
                        }
                        v2_repair_needed = any(
                            not self._is_tenant_identity(source_tenant)
                            for source_tenant in source_tenants.values()
                        )
                        v2_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(artifacts_v2)")}
                        if {"artifact_id", "tenant", "tenant_identity"}.issubset(v2_columns):
                            for artifact_id, tenant, tenant_identity in con.execute(
                                "SELECT artifact_id, tenant, tenant_identity FROM artifacts_v2"
                            ):
                                source_tenant = source_tenants.get(str(artifact_id))
                                if source_tenant is not None and (
                                    not self._is_tenant_identity(source_tenant)
                                    or str(tenant) != source_tenant
                                    or str(tenant_identity) != source_tenant
                                ):
                                    v2_repair_needed = True
                                    break
                    migration_needs_backup = bool(existing_columns or v2_exists) and (
                        marker_value in {"", "legacy-raw-v1"}
                        or (
                            bool(existing_columns)
                            and not full_schema.issubset(existing_columns)
                            and not v2_exists
                        )
                        or v2_repair_needed
                        or primary_identity_conflict
                    )
                    if migration_needs_backup:
                        self._create_migration_backup()
                    if primary_identity_conflict:
                        raise sqlite3.IntegrityError("artifact migration conflict for primary table tenant identity")

                    con.execute(
                        "CREATE TABLE IF NOT EXISTS artifact_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                    )
                    if not existing_columns and not v2_exists:
                        con.execute(
                            """CREATE TABLE IF NOT EXISTS artifacts (
                            artifact_id TEXT PRIMARY KEY,
                            created_at REAL NOT NULL,
                            tenant TEXT NOT NULL,
                            tenant_identity TEXT,
                            kind TEXT NOT NULL,
                            text TEXT NOT NULL DEFAULT '',
                            mime_type TEXT,
                            encoding TEXT,
                            blob BLOB,
                            size_bytes INTEGER,
                            checksum TEXT,
                            identity_json TEXT
                        )"""
                        )
                        self._table = _ARTIFACT_TABLE
                    elif full_schema.issubset(existing_columns):
                        self._table = _ARTIFACT_TABLE
                    else:
                        con.execute(
                            """CREATE TABLE IF NOT EXISTS artifacts_v2 (
                                artifact_id TEXT PRIMARY KEY,
                                created_at REAL NOT NULL,
                                tenant TEXT NOT NULL,
                                tenant_identity TEXT NOT NULL,
                                kind TEXT NOT NULL,
                                text TEXT NOT NULL DEFAULT '',
                                mime_type TEXT,
                                encoding TEXT,
                                blob BLOB,
                                size_bytes INTEGER,
                                checksum TEXT,
                                identity_json TEXT
                            )"""
                        )
                        if existing_columns:
                            optional_columns = (
                                "mime_type", "encoding", "blob", "size_bytes", "checksum", "identity_json",
                            )
                            copied_columns = ["artifact_id", "created_at", "tenant", "kind", "text"]
                            copied_columns.extend(column for column in optional_columns if column in existing_columns)
                            selected_columns = ", ".join(copied_columns)
                            legacy_rows = list(con.execute(f"SELECT {selected_columns} FROM artifacts"))
                            for legacy_row in legacy_rows:
                                values = dict(zip(copied_columns, legacy_row))
                                source_tenant = str(values["tenant"])
                                if marker_value == "sha256-v1" and not self._is_tenant_identity(source_tenant):
                                    raise sqlite3.IntegrityError(
                                        f"artifact migration conflict for {values['artifact_id']}"
                                    )
                                optional_values = [values.get(column) for column in optional_columns]
                                existing = con.execute(
                                    """SELECT tenant, tenant_identity, kind, text, mime_type, encoding,
                                              blob, size_bytes, checksum, identity_json
                                       FROM artifacts_v2 WHERE artifact_id=?""",
                                    (values["artifact_id"],),
                                ).fetchone()
                                if existing is not None:
                                    expected_payload = (
                                        values["kind"], values["text"], *optional_values,
                                    )
                                    if tuple(existing[2:]) != expected_payload:
                                        raise sqlite3.IntegrityError(
                                            f"artifact migration conflict for {values['artifact_id']}"
                                        )
                                    existing_tenants_match = all(
                                        str(stored_tenant) == source_tenant
                                        or self._tenant_identity(str(stored_tenant)) == source_tenant
                                        for stored_tenant in existing[:2]
                                    )
                                    if not existing_tenants_match:
                                        raise sqlite3.IntegrityError(
                                            f"artifact migration conflict for {values['artifact_id']}"
                                        )
                                    # Same-owner raw/hash representations are normalized below.
                                    continue
                                con.execute(
                                    """INSERT INTO artifacts_v2(
                                        artifact_id, created_at, tenant, tenant_identity, kind, text,
                                        mime_type, encoding, blob, size_bytes, checksum, identity_json
                                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                                    (
                                        values["artifact_id"], values["created_at"], source_tenant, source_tenant,
                                        values["kind"], values["text"], *optional_values,
                                    ),
                                )
                        self._table = _ARTIFACT_V2_TABLE
                    def _repair_tenants(table: str, *, has_identity: bool) -> None:
                        rows = list(con.execute(f"SELECT rowid, tenant FROM {table}"))
                        for rowid, tenant in rows:
                            digest = self._tenant_identity(str(tenant))
                            if has_identity:
                                con.execute(
                                    f"UPDATE {table} SET tenant=?, tenant_identity=? WHERE rowid=?",
                                    (digest, digest, rowid),
                                )
                            else:
                                con.execute(
                                    f"UPDATE {table} SET tenant=? WHERE rowid=?",
                                    (digest, rowid),
                                )

                    if marker_value in {"", "legacy-raw-v1"}:
                        if existing_columns:
                            _repair_tenants(
                                _ARTIFACT_TABLE,
                                has_identity=full_schema.issubset(existing_columns),
                            )
                        if v2_exists or self._table == _ARTIFACT_V2_TABLE:
                            _repair_tenants(_ARTIFACT_V2_TABLE, has_identity=True)
                    elif marker_value == "sha256-v1" and v2_exists and existing_columns and not full_schema.issubset(existing_columns):
                        source_tenants = {
                            str(artifact_id): str(tenant)
                            for artifact_id, tenant in con.execute("SELECT artifact_id, tenant FROM artifacts")
                        }
                        for rowid, artifact_id, tenant, tenant_identity in con.execute(
                            "SELECT rowid, artifact_id, tenant, tenant_identity FROM artifacts_v2"
                        ):
                            source_tenant = source_tenants.get(str(artifact_id))
                            if source_tenant is None:
                                continue
                            if str(tenant) != source_tenant or str(tenant_identity) != source_tenant:
                                repaired = source_tenant if str(tenant) == source_tenant else self._tenant_identity(str(tenant))
                                con.execute(
                                    "UPDATE artifacts_v2 SET tenant=?, tenant_identity=? WHERE rowid=?",
                                    (repaired, repaired, rowid),
                                )
                    con.execute(
                        "INSERT OR REPLACE INTO artifact_schema_meta(key, value) VALUES(?, ?)",
                        ("tenant_storage", "sha256-v1"),
                    )
                    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{self._table}_created ON {self._table}(created_at)")
                    self._ensure_paging_metadata(con)
                    con.commit()
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    def _purge(self, con: sqlite3.Connection, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_purge) < self._purge_interval:
            return
        self._last_purge = now
        cutoff = now - self.ttl_seconds
        con.execute(
            f"DELETE FROM {_ARTIFACT_PAGING_TABLE} WHERE artifact_id IN "
            f"(SELECT artifact_id FROM {self._table} WHERE created_at < ?)",
            (cutoff,),
        )
        con.execute(f"DELETE FROM {self._table} WHERE created_at < ?", (cutoff,))

    def _scoped_artifact_id(self, con: sqlite3.Connection, base_id: str, tenant_identity: str) -> str:
        row = con.execute(
            f"SELECT tenant_identity, tenant FROM {self._table} WHERE artifact_id=?",
            (base_id,),
        ).fetchone()
        existing_identity = str((row[0] if row and row[0] else row[1]) if row else "")
        if not row or existing_identity == tenant_identity:
            return base_id
        return f"{base_id}_{tenant_identity}"

    def batch(self, tenant: str, *, cancel_check=None) -> _ArtifactBatch:
        """Write a related artifact set in one transaction, including its final bundle."""
        return _ArtifactBatch(self, tenant, cancel_check=cancel_check)

    def put(self, text: str, tenant: str, kind: str) -> str:
        with self.batch(tenant) as batch:
            return batch.put(text, kind)

    def put_bytes(
        self,
        data: bytes,
        tenant: str,
        kind: str,
        mime_type: str,
    ) -> str:
        """Store complete image bytes without interpreting or truncating them."""
        with self.batch(tenant) as batch:
            return batch.put_bytes(data, kind, mime_type)

    def put_json(self, value: dict[str, Any], tenant: str, kind: str) -> str:
        """Store a bounded JSON artifact, preserving full DOM payload semantics."""
        with self.batch(tenant) as batch:
            return batch.put_json(value, kind)

    @staticmethod
    def _binary_failure(message: str) -> dict[str, Any]:
        return {"success": False, "error": message[:160]}

    def get_binary(self, artifact_id: str, tenant: str | None = None) -> dict[str, Any]:
        """Return one complete, integrity-checked binary artifact or a safe failure."""
        cutoff = time.time() - self.ttl_seconds

        def _do_get() -> tuple[Any, ...] | None:
            with closing(self._connect()) as con:
                query = (
                    """SELECT artifact_id, kind, mime_type, encoding, blob,
                              size_bytes, checksum, identity_json
                       FROM """ + self._table + " WHERE artifact_id=? AND created_at>=?"
                )
                params: list[Any] = [str(artifact_id), cutoff]
                if tenant is not None:
                    query += " AND tenant_identity=?"
                    params.append(self._tenant_identity(tenant))
                return con.execute(query, params).fetchone()

        row = retry_busy(_do_get, retries=3)
        if not row:
            return self._binary_failure("artifact not found or expired")
        if row[4] is None or not row[2] or not row[3]:
            return self._binary_failure("artifact is not binary")

        data = bytes(row[4])
        mime_type = str(row[2])
        encoding = str(row[3])
        try:
            expected_size = int(row[5]) if row[5] is not None else -1
        except (TypeError, ValueError, OverflowError):
            return self._binary_failure("artifact integrity check failed")
        if expected_size < 0:
            return self._binary_failure("artifact integrity check failed")
        checksum = str(row[6] or "")
        if not mime_type.startswith("image/") or encoding != "base64":
            return self._binary_failure("artifact integrity check failed")
        if expected_size != len(data) or checksum != hashlib.sha256(data).hexdigest():
            return self._binary_failure("artifact integrity check failed")
        try:
            identity = json.loads(str(row[7] or "{}"))
        except (TypeError, ValueError):
            return self._binary_failure("artifact identity is invalid")
        if not isinstance(identity, dict):
            return self._binary_failure("artifact identity is invalid")

        expected_identity = {
            "artifact_id": str(row[0]),
            "kind": str(row[1]),
            "mime_type": mime_type,
            "encoding": encoding,
            "size_bytes": expected_size,
            "checksum": checksum,
        }
        if any(identity.get(key) != value for key, value in expected_identity.items()):
            return self._binary_failure("artifact integrity check failed")

        return {
            "success": True,
            "artifact_id": str(row[0]),
            "kind": str(row[1]),
            "mime_type": mime_type,
            "encoding": encoding,
            "size_bytes": len(data),
            "checksum": checksum,
            "sha256": checksum,
            "identity": identity,
            "data_base64": base64.b64encode(data).decode("ascii"),
        }

    @staticmethod
    def _section_names(text: str) -> list[str]:
        """Return the bounded section-name projection exposed by paged reads."""
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            names: list[str] = []
            for key in parsed:
                names.append(f"json:{str(key)}")
                if len(names) == 50:
                    break
            return names

        names: list[str] = []
        heading = re.compile(r"(?m)^(?:#{1,6}\s+([^\n#].*?)|([A-Z][A-Z0-9 _/.-]{2,48}):)\s*$")
        for match in heading.finditer(text):
            label = (match.group(1) or match.group(2) or "").strip().rstrip(":")
            if not label:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:64] or "section"
            base = slug
            suffix = 2
            while slug in names:
                slug = f"{base}-{suffix}"
                suffix += 1
            names.append(slug)
            if len(names) == 50:
                break
        return names

    @staticmethod
    def _section_map(text: str) -> dict[str, tuple[int, int]]:
        """Return deterministic, addressable sections without asking an LLM to rewrite anything."""
        sections: dict[str, tuple[int, int]] = {}
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            # JSON artifacts are uncommon, but top-level keys are useful addresses. The offsets
            # below are intentionally omitted because serializing one value is cheaper/safer.
            return {f"json:{str(k)}": (-1, -1) for k in parsed.keys()}

        matches: list[tuple[str, int]] = []
        heading = re.compile(r"(?m)^(?:#{1,6}\s+([^\n#].*?)|([A-Z][A-Z0-9 _/.-]{2,48}):)\s*$")
        for m in heading.finditer(text):
            label = (m.group(1) or m.group(2) or "").strip().rstrip(":")
            if label:
                slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:64] or "section"
                base = slug; n = 2
                while slug in sections or any(name == slug for name, _ in matches):
                    slug = f"{base}-{n}"; n += 1
                matches.append((slug, m.start()))
        for i, (name, start) in enumerate(matches):
            end = matches[i + 1][1] if i + 1 < len(matches) else len(text)
            sections[name] = (start, end)
        return sections

    def compact(self, result: dict[str, Any], tenant: str, kind: str, *, field: str = "text") -> dict[str, Any]:
        if field not in result or not isinstance(result.get(field), str):
            return result
        text = result[field]
        if len(text) <= self.max_inline_chars:
            result.setdefault("artifact", None)
            return result
        artifact_id = self.put(text, tenant, kind)
        head = int(self.max_inline_chars * 0.82)
        tail = self.max_inline_chars - head
        preview = text[:head] + "\n\n[... full local output stored as artifact ...]\n\n" + text[-tail:]
        sections = list(self._section_map(text).keys())[:24]
        result[field] = preview
        result["artifact"] = {
            "id": artifact_id,
            "full_chars": len(text),
            "inline_chars": len(preview),
            "sections": sections,
            "hint": "Fetch only the needed section/slice if the compact preview is insufficient.",
        }
        return result

    def get(self, artifact_id: str, offset: int = 0, max_chars: int = 6000, section: str = "", tenant: str | None = None) -> dict[str, Any]:
        offset = max(0, int(offset))
        max_chars = max(256, min(int(max_chars), 50_000))
        section = str(section or "").strip()
        cutoff = time.time() - self.ttl_seconds

        def _do_get() -> tuple[Any, ...] | None:
            with closing(self._connect()) as con:
                # Reads stay read-only; expiry cleanup happens on writes. This avoids
                # turning every artifact slice fetch into a WAL writer.
                if section:
                    query = (
                        f"SELECT a.kind, a.text, a.mime_type, a.created_at, p.char_count, "
                        f"p.section_names, NULL, CASE WHEN p.artifact_id IS NULL THEN a.text END "
                        f"FROM {self._table} AS a LEFT JOIN {_ARTIFACT_PAGING_TABLE} AS p "
                        "ON p.artifact_id=a.artifact_id WHERE a.artifact_id=? AND a.created_at>=?"
                    )
                    params: list[Any] = [artifact_id, cutoff]
                else:
                    query = (
                        f"SELECT a.kind, substr(COALESCE(p.page_text, a.text), ?, ?), "
                        f"a.mime_type, a.created_at, p.char_count, p.section_names, "
                        f"substr(p.nul_mask, ?, ?), CASE WHEN p.artifact_id IS NULL THEN a.text END "
                        f"FROM {self._table} AS a LEFT JOIN {_ARTIFACT_PAGING_TABLE} AS p "
                        "ON p.artifact_id=a.artifact_id WHERE a.artifact_id=? AND a.created_at>=?"
                    )
                    nul_byte_offset = offset % 8
                    nul_byte_count = (nul_byte_offset + max_chars + 7) // 8
                    sqlite_max_int = (1 << 63) - 1
                    params = [
                        min(offset + 1, sqlite_max_int),
                        max_chars,
                        min(offset // 8 + 1, sqlite_max_int),
                        nul_byte_count,
                        artifact_id,
                        cutoff,
                    ]
                if tenant is not None:
                    query += " AND a.tenant_identity=?"
                    params.append(self._tenant_identity(tenant))
                return con.execute(query, params).fetchone()

        row = retry_busy(_do_get, retries=3)
        if not row:
            return {"success": False, "error": "artifact not found or expired", "artifact_id": artifact_id}
        if row[2]:
            return {"success": False, "error": "binary artifact requires binary retrieval"}

        if section:
            text = row[1]
            sections = self._section_map(text)
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if section.startswith("json:") and isinstance(parsed, dict):
                key = section[5:]
                if key not in parsed:
                    return {"success": False, "error": "artifact section not found", "artifact_id": artifact_id, "sections": list(sections)[:50]}
                value = json_dumps(parsed[key], ensure_ascii=False, indent=2) if not isinstance(parsed[key], str) else parsed[key]
                piece = value[offset:offset + max_chars]
                return {"success": True, "artifact_id": artifact_id, "kind": row[0], "section": section, "text": piece,
                        "offset": offset, "next_offset": offset + len(piece) if offset + len(piece) < len(value) else None,
                        "total_chars": len(value), "sections": list(sections)[:50]}
            if section not in sections:
                return {"success": False, "error": "artifact section not found", "artifact_id": artifact_id, "sections": list(sections)[:50]}
            start, end = sections[section]
            section_text = text[start:end]
            piece = section_text[offset:offset + max_chars]
            return {"success": True, "artifact_id": artifact_id, "kind": row[0], "section": section, "text": piece,
                    "offset": offset, "next_offset": offset + len(piece) if offset + len(piece) < len(section_text) else None,
                    "total_chars": len(section_text), "sections": list(sections)[:50]}

        if row[4] is None or row[5] is None:
            text = str(row[7] or "")
            sections = self._section_names(text)
            piece = text[offset:offset + max_chars]
            total_chars = len(text)
            return {
                "success": True, "artifact_id": artifact_id, "kind": row[0], "text": piece,
                "offset": offset,
                "next_offset": offset + len(piece) if offset + len(piece) < total_chars else None,
                "total_chars": total_chars, "sections": sections,
            }
        try:
            sections = json.loads(row[5])
        except Exception:
            return {"success": False, "error": "artifact paging metadata unavailable", "artifact_id": artifact_id}
        if not isinstance(sections, list) or any(not isinstance(name, str) for name in sections):
            return {"success": False, "error": "artifact paging metadata unavailable", "artifact_id": artifact_id}
        piece = row[1] or ""
        nul_mask = row[6] or b""
        if nul_mask:
            chars = list(piece)
            bit_offset = offset % 8
            for index in range(len(chars)):
                bit_index = bit_offset + index
                mask_index = bit_index // 8
                if mask_index < len(nul_mask) and nul_mask[mask_index] & (1 << (bit_index % 8)):
                    chars[index] = "\x00"
            piece = "".join(chars)
        total_chars = int(row[4])
        return {
            "success": True,
            "artifact_id": artifact_id,
            "kind": row[0],
            "text": piece,
            "offset": offset,
            "next_offset": offset + len(piece) if offset + len(piece) < total_chars else None,
            "total_chars": total_chars,
            "sections": sections,
        }

    def get_slices(
        self,
        artifact_id: str,
        slices: list[dict[str, int]],
        tenant: str | None = None,
    ) -> dict[str, Any]:
        """Fetch several bounded text spans in caller order with one SQLite read."""
        if not isinstance(slices, list) or not slices or len(slices) > MAX_ARTIFACT_SLICES:
            return {"success": False, "error": f"slices must contain 1 to {MAX_ARTIFACT_SLICES} ranges", "artifact_id": artifact_id}

        normalized: list[tuple[int, int]] = []
        total_requested = 0
        for item in slices:
            if not isinstance(item, dict) or set(item) != {"offset", "max_chars"}:
                return {"success": False, "error": "each slice must contain only offset and max_chars", "artifact_id": artifact_id}
            offset, max_chars = item.get("offset"), item.get("max_chars")
            if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                return {"success": False, "error": "slice offset must be a non-negative integer", "artifact_id": artifact_id}
            if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 1 <= max_chars <= MAX_ARTIFACT_SLICE_CHARS:
                return {"success": False, "error": f"slice max_chars must be between 1 and {MAX_ARTIFACT_SLICE_CHARS}", "artifact_id": artifact_id}
            total_requested += max_chars
            if total_requested > MAX_ARTIFACT_SLICE_CHARS:
                return {"success": False, "error": f"combined slice max_chars cannot exceed {MAX_ARTIFACT_SLICE_CHARS}", "artifact_id": artifact_id}
            normalized.append((offset, max_chars))

        cutoff = time.time() - self.ttl_seconds
        expressions: list[str] = []
        params: list[Any] = []
        sqlite_max_int = (1 << 63) - 1
        for offset, max_chars in normalized:
            expressions.append("substr(COALESCE(p.page_text, a.text), ?, ?)")
            params.extend((min(offset + 1, sqlite_max_int), max_chars))
            nul_byte_offset = offset % 8
            nul_byte_count = (nul_byte_offset + max_chars + 7) // 8
            expressions.append("substr(p.nul_mask, ?, ?)")
            params.extend((min(offset // 8 + 1, sqlite_max_int), nul_byte_count))
        query = (
            f"SELECT a.kind, a.mime_type, p.char_count, p.section_names, "
            f"CASE WHEN p.artifact_id IS NULL THEN a.text END, {', '.join(expressions)} "
            f"FROM {self._table} AS a LEFT JOIN {_ARTIFACT_PAGING_TABLE} AS p "
            "ON p.artifact_id=a.artifact_id WHERE a.artifact_id=? AND a.created_at>=?"
        )
        params.extend((artifact_id, cutoff))
        if tenant is not None:
            query += " AND a.tenant_identity=?"
            params.append(self._tenant_identity(tenant))

        def _do_get_slices() -> tuple[Any, ...] | None:
            with closing(self._connect()) as con:
                return con.execute(query, params).fetchone()

        row = retry_busy(_do_get_slices, retries=3)
        if not row:
            return {"success": False, "error": "artifact not found or expired", "artifact_id": artifact_id}
        if row[1]:
            return {"success": False, "error": "binary artifact requires binary retrieval", "artifact_id": artifact_id}
        fallback_text = row[4]
        if row[2] is None or row[3] is None:
            text = str(fallback_text or "")
            sections = self._section_names(text)
            total_chars = len(text)
        else:
            try:
                sections = json.loads(row[3])
            except Exception:
                return {"success": False, "error": "artifact paging metadata unavailable", "artifact_id": artifact_id}
            if not isinstance(sections, list) or any(not isinstance(name, str) for name in sections):
                return {"success": False, "error": "artifact paging metadata unavailable", "artifact_id": artifact_id}
            total_chars = int(row[2])
        result_slices: list[dict[str, Any]] = []
        for index, (offset, _max_chars) in enumerate(normalized):
            piece = str(fallback_text or "")[offset:offset + normalized[index][1]] if fallback_text is not None else (row[5 + index * 2] or "")
            nul_mask = b"" if fallback_text is not None else (row[6 + index * 2] or b"")
            if nul_mask:
                chars = list(piece)
                bit_offset = offset % 8
                for char_index in range(len(chars)):
                    bit_index = bit_offset + char_index
                    mask_index = bit_index // 8
                    if mask_index < len(nul_mask) and nul_mask[mask_index] & (1 << (bit_index % 8)):
                        chars[char_index] = "\x00"
                piece = "".join(chars)
            result_slices.append({"offset": offset, "text": piece})
        return {
            "success": True,
            "artifact_id": artifact_id,
            "kind": row[0],
            "slices": result_slices,
            "total_chars": total_chars,
            "sections": sections,
            "truncated": False,
            "budget_limited": False,
        }

    def list(self, tenant: str = "", limit: int = 20) -> list[dict[str, Any]]:
        if not isinstance(tenant, str):
            raise ValueError("tenant label must be a string")
        self._init_db()
        with closing(self._connect()) as con:
            lim = max(1, min(limit, 100))
            if tenant:
                tenant_identity = self._tenant_identity(tenant)
                if self._table == _ARTIFACT_V2_TABLE:
                    rows = con.execute(
                        "SELECT artifact_id, kind, size_bytes, created_at, mime_type FROM artifacts_v2 WHERE tenant_identity=? ORDER BY created_at DESC LIMIT ?",
                        (tenant_identity, lim),
                    ).fetchall()
                else:
                    rows = con.execute(
                        "SELECT artifact_id, kind, size_bytes, created_at, mime_type FROM artifacts WHERE tenant_identity=? ORDER BY created_at DESC LIMIT ?",
                        (tenant_identity, lim),
                    ).fetchall()
            else:
                table = self._table
                rows = con.execute(
                    f"SELECT artifact_id, kind, size_bytes, created_at, mime_type FROM {table} ORDER BY created_at DESC LIMIT ?",
                    (lim,),
                ).fetchall()
            return [
                {
                    "artifact_id": str(r[0]),
                    "kind": str(r[1]),
                    "size_bytes": int(r[2] or 0),
                    "created_at": float(r[3] or 0.0),
                    "mime_type": str(r[4] or ""),
                }
                for r in rows
            ]
