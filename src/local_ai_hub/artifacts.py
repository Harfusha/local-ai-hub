from __future__ import annotations

from .json_utils import dumps as json_dumps

import base64
import codecs
import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, retry_busy


DEFAULT_MAX_BINARY_BYTES = 4_000_000
DEFAULT_MAX_JSON_BYTES = 4_000_000
_ARTIFACT_TABLE = "artifacts"
_ARTIFACT_PAGING_TABLE = "artifact_paging_metadata"
_ARTIFACTS_SCHEMA_SQL = """CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY, created_at REAL NOT NULL,
    tenant TEXT NOT NULL, tenant_identity TEXT, kind TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '', mime_type TEXT, encoding TEXT, blob BLOB,
    size_bytes INTEGER, checksum TEXT, identity_json TEXT
)"""
_ARTIFACT_SCHEMA_META_SQL = "CREATE TABLE artifact_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
_ARTIFACT_PAGING_SCHEMA_SQL = """CREATE TABLE artifact_paging_metadata (
    artifact_id TEXT PRIMARY KEY,
    char_count INTEGER NOT NULL,
    section_json TEXT NOT NULL,
    section_checksum TEXT NOT NULL,
    page_text TEXT,
    nul_mask BLOB
)"""
MAX_ARTIFACT_SLICES = 16
MAX_ARTIFACT_SLICE_CHARS = 50_000
MAX_ARTIFACT_TEXT_CHUNK_BYTES = 64 * 1024
MAX_ARTIFACT_JSON_SOURCE_BYTES = 1_000_000
MAX_ARTIFACT_SECTION_JSON_CHARS = 250_000
MAX_ARTIFACT_HEADING_CHARS = 512
MAX_ARTIFACT_SECTION_NAMES = 50
MAX_ARTIFACT_SECTION_METADATA_BYTES = 128 * 1024
MAX_ARTIFACT_JSON_SECTION_KEYS_SCANNED = 256
MAX_ARTIFACT_READ_SECONDS = 5.0


def _normalize_artifact_create_sql(statement: str) -> str:
    normalized = " ".join(statement.upper().split()).rstrip(";")
    normalized = normalized.replace("CREATE TABLE IF NOT EXISTS ", "CREATE TABLE ", 1)
    return re.sub(r"\s*([(),])\s*", r"\1", normalized)


class UnsupportedArtifactSchema(sqlite3.DatabaseError):
    """An existing artifact database does not use the current durable schema."""


class ArtifactTransportError(ValueError):
    """Bounded, caller-safe artifact transport failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ArtifactBatchCancelled(RuntimeError):
    """Raised when a caller cancels an artifact batch before commit."""


class ArtifactTextReadError(RuntimeError):
    """Bounded, typed failure when artifact TEXT cannot be read safely."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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
        section_map, sections_truncated = self._store._section_data(text)
        section_names = list(section_map)
        page_text, nul_mask = self._store._page_text_metadata(text)
        self._connection.execute(
            f"INSERT OR REPLACE INTO {self._store._table}(artifact_id, created_at, tenant, tenant_identity, kind, text) VALUES(?,?,?,?,?,?)",
            (artifact_id, time.time(), self._tenant_identity, self._tenant_identity, kind, text),
        )
        self._store._write_paging_metadata(
            self._connection, artifact_id, text, section_names, page_text, nul_mask, sections_truncated,
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
        state_dir: Path | str,
        ttl_hours: int = 72,
        max_inline_chars: int = 6000,
        max_binary_bytes: int = DEFAULT_MAX_BINARY_BYTES,
        max_json_bytes: int = DEFAULT_MAX_JSON_BYTES,
    ):
        if not isinstance(state_dir, (str, Path)) or not str(state_dir).strip() or "\x00" in str(state_dir):
            raise ValueError("invalid state_dir")
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "artifacts.sqlite3"
        ttl = 72 if isinstance(ttl_hours, bool) or not isinstance(ttl_hours, (int, float)) or not math.isfinite(ttl_hours) else int(ttl_hours)
        self.ttl_seconds = max(3600, ttl * 3600)
        self.max_inline_chars = max(1000, int(max_inline_chars))
        self.max_binary_bytes = max(1, int(max_binary_bytes))
        self.max_json_bytes = max(1, int(max_json_bytes))
        self._last_purge = 0.0
        self._purge_interval = 1800.0
        if not self.path.exists():
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

    def _connect_for_initialization(self, *, fresh: bool) -> sqlite3.Connection:
        mode = "rwc" if fresh else "rw"
        uri = f"{self.path.resolve().as_uri()}?mode={mode}"
        con = sqlite3.connect(uri, uri=True, timeout=0.75)
        try:
            con.execute("PRAGMA busy_timeout=750")
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA cache_size=-32768")
            try:
                con.execute("PRAGMA mmap_size=268435456")
            except sqlite3.OperationalError:
                pass
            return con
        except BaseException:
            con.close()
            raise

    @staticmethod
    def _write_paging_metadata(
        con: sqlite3.Connection,
        artifact_id: str,
        text: str,
        section_names: list[str],
        page_text: str | None,
        nul_mask: bytes | None,
        sections_truncated: bool,
    ) -> None:
        section_json = json.dumps(
            {"artifact_id": artifact_id, "names": section_names, "truncated": sections_truncated},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        section_checksum = hashlib.sha256(section_json.encode("utf-8")).hexdigest()
        con.execute(
            f"""INSERT INTO {_ARTIFACT_PAGING_TABLE}
                (artifact_id, char_count, section_json, section_checksum, page_text, nul_mask)
                VALUES(?,?,?,?,?,?) ON CONFLICT(artifact_id) DO UPDATE SET
                char_count=excluded.char_count, section_json=excluded.section_json,
                section_checksum=excluded.section_checksum,
                page_text=excluded.page_text, nul_mask=excluded.nul_mask""",
            (
                artifact_id,
                len(text),
                section_json,
                section_checksum,
                page_text,
                nul_mask,
            ),
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
    def _decode_section_metadata(
        value: str, expected_artifact_id: str, expected_checksum: str | None,
    ) -> tuple[list[str], bool | None] | None:
        if (
            not isinstance(expected_checksum, str)
            or hashlib.sha256(value.encode("utf-8")).hexdigest() != expected_checksum
        ):
            return None
        try:
            parsed = json.loads(value)
        except Exception:
            return None
        if isinstance(parsed, dict):
            if set(parsed) != {"artifact_id", "names", "truncated"}:
                return None
            artifact_id = parsed.get("artifact_id")
            names = parsed.get("names")
            truncated = parsed.get("truncated")
            if (
                artifact_id == expected_artifact_id
                and isinstance(names, list)
                and len(names) <= MAX_ARTIFACT_SECTION_NAMES
                and not any(not isinstance(name, str) for name in names)
                and all(len(name) <= MAX_ARTIFACT_HEADING_CHARS for name in names)
                and len(set(names)) == len(names)
                and isinstance(truncated, bool)
            ):
                return names, truncated
        return None

    @staticmethod
    def _json_object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    @staticmethod
    def _json_section_names(parsed: dict[str, Any]) -> tuple[list[str], bool]:
        names: list[str] = []
        truncated = False
        for index, key in enumerate(parsed):
            if index >= MAX_ARTIFACT_JSON_SECTION_KEYS_SCANNED:
                truncated = True
                break
            if len(names) == MAX_ARTIFACT_SECTION_NAMES:
                truncated = True
                break
            name = f"json:{key}"
            if len(name) > MAX_ARTIFACT_HEADING_CHARS:
                truncated = True
                continue
            names.append(name)
        return names, truncated

    @staticmethod
    def _sqlite_text_codec(encoding: str) -> str:
        normalized = encoding.strip().casefold()
        codec = {"utf-8": "utf-8", "utf-16le": "utf-16-le", "utf-16be": "utf-16-be"}.get(normalized)
        if codec is None:
            raise ArtifactTextReadError("artifact_text_encoding_unsupported", "unsupported SQLite text encoding")
        return codec

    @staticmethod
    def _check_read_deadline(deadline: float) -> None:
        if time.monotonic() >= deadline:
            raise ArtifactTextReadError("artifact_text_read_timeout", "artifact text read exceeded its time limit")

    def _configure_read_deadline(self, con: sqlite3.Connection, deadline: float) -> None:
        self._check_read_deadline(deadline)
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        con.execute(f"PRAGMA busy_timeout={min(100, remaining_ms)}")
        con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)

    def _read_small_text(
        self, con: sqlite3.Connection, rowid: int, encoding: str, max_bytes: int, deadline: float,
    ) -> str:
        self._check_read_deadline(deadline)
        codec = self._sqlite_text_codec(encoding)
        try:
            with con.blobopen(self._table, "text", rowid, readonly=True) as text_blob:
                size_bytes = len(text_blob)
                if size_bytes > max_bytes:
                    raise ArtifactTextReadError("artifact_section_too_large", "JSON section exceeds bounded parsing limit")
                text = text_blob.read(size_bytes).decode(codec, errors="strict")
                self._check_read_deadline(deadline)
                return text
        except UnicodeError as exc:
            raise ArtifactTextReadError("artifact_text_decode_failed", "artifact text could not be decoded safely") from exc
        except sqlite3.Error as exc:
            if time.monotonic() >= deadline:
                raise ArtifactTextReadError("artifact_text_read_timeout", "artifact text read exceeded its time limit") from exc
    def _stream_text(
        self,
        con: sqlite3.Connection,
        rowid: int,
        encoding: str,
        spans: list[tuple[int, int]] | None = None,
        *,
        target_section: str = "",
        parse_sections: bool = True,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        deadline = deadline if deadline is not None else time.monotonic() + MAX_ARTIFACT_READ_SECONDS
        self._check_read_deadline(deadline)
        spans = spans or []
        codec = self._sqlite_text_codec(encoding)
        decoder = codecs.getincrementaldecoder(codec)(errors="strict")
        span_parts: list[list[str]] = [[] for _ in spans]
        names: list[str] = []
        seen_names: set[str] = set()
        sections: dict[str, tuple[int, int]] = {}
        truncated = False
        current_name = ""
        line_start = 0
        line_chars: list[str] = []
        line_overflow = False
        target_start: int | None = None
        target_end: int | None = None
        total_chars = 0

        def finish_line() -> None:
            nonlocal current_name, truncated, target_start, target_end
            line = "".join(line_chars) if not line_overflow else ""
            if line_overflow or len(line) > MAX_ARTIFACT_HEADING_CHARS:
                prefix = "".join(line_chars)
                if re.match(r"^#{1,6}\s+", prefix):
                    if current_name:
                        start, _end = sections[current_name]
                        sections[current_name] = (start, line_start)
                        current_name = ""
                    if target_start is not None and target_end is None:
                        target_end = line_start
                    truncated = True
                return
            label = self._section_label(line) if line else None
            if label is None:
                if line_overflow:
                    truncated = True
                return
            if current_name:
                start, _end = sections[current_name]
                sections[current_name] = (start, line_start)
            if target_start is not None and target_end is None:
                target_end = line_start
            current_name = ""
            if len(names) < MAX_ARTIFACT_SECTION_NAMES:
                base = self._section_slug(label)
                slug = base
                suffix = 2
                while slug in seen_names:
                    slug = f"{base}-{suffix}"
                    suffix += 1
                names.append(slug)
                seen_names.add(slug)
                sections[slug] = (line_start, -1)
                current_name = slug
                if slug == target_section and target_start is None:
                    target_start = line_start
            else:
                truncated = True

        def consume(decoded: str) -> None:
            nonlocal total_chars, line_start, line_overflow
            chunk_start = total_chars
            chunk_end = chunk_start + len(decoded)
            for index, (span_start, span_length) in enumerate(spans):
                overlap_start = max(chunk_start, span_start)
                overlap_end = min(chunk_end, span_start + span_length)
                if overlap_start < overlap_end:
                    span_parts[index].append(decoded[overlap_start - chunk_start:overlap_end - chunk_start])
            if parse_sections:
                for local_index, character in enumerate(decoded):
                    if character == "\n":
                        finish_line()
                        line_start = chunk_start + local_index + 1
                        line_chars.clear()
                        line_overflow = False
                    elif not line_overflow:
                        if len(line_chars) < MAX_ARTIFACT_HEADING_CHARS + 1:
                            line_chars.append(character)
                        else:
                            line_overflow = True
            total_chars = chunk_end

        try:
            with con.blobopen(self._table, "text", rowid, readonly=True) as text_blob:
                size_bytes = len(text_blob)
                while True:
                    self._check_read_deadline(deadline)
                    chunk = text_blob.read(MAX_ARTIFACT_TEXT_CHUNK_BYTES)
                    if not chunk:
                        break
                    consume(decoder.decode(chunk, final=False))
                self._check_read_deadline(deadline)
                consume(decoder.decode(b"", final=True))
        except sqlite3.Error as exc:
            if time.monotonic() >= deadline:
                raise ArtifactTextReadError("artifact_text_read_timeout", "artifact text read exceeded its time limit") from exc
            raise ArtifactTextReadError("artifact_text_stream_failed", "artifact text could not be streamed safely") from exc
        except UnicodeError as exc:
            raise ArtifactTextReadError("artifact_text_decode_failed", "artifact text could not be decoded safely") from exc

        self._check_read_deadline(deadline)
        if parse_sections and (line_chars or line_overflow):
            finish_line()
        if current_name:
            start, _end = sections[current_name]
            sections[current_name] = (start, total_chars)
        if target_start is not None and target_end is None:
            target_end = total_chars
        return {
            "total_chars": total_chars,
            "pieces": ["".join(parts) for parts in span_parts],
            "section_names": names,
            "sections": sections,
            "sections_truncated": truncated,
            "target_start": target_start,
            "target_end": target_end,
            "size_bytes": size_bytes,
        }

    @staticmethod
    def _tenant_identity(tenant: str) -> str:
        """Hash a trusted-local namespace label without retaining its caller-controlled text."""
        if not isinstance(tenant, str) or "\x00" in tenant:
            raise ValueError("tenant label must be a string without null bytes")
        return hashlib.sha256(tenant.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_tenant_identity(value: str) -> bool:
        return len(value) == 64 and all(character in "0123456789abcdef" for character in value)

    def _init_db(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            full_schema = {
                "artifact_id": ("TEXT", 1, 0, None, 0), "created_at": ("REAL", 0, 1, None, 0),
                "tenant": ("TEXT", 0, 1, None, 0), "tenant_identity": ("TEXT", 0, 0, None, 0),
                "kind": ("TEXT", 0, 1, None, 0), "text": ("TEXT", 0, 1, "''", 0),
                "mime_type": ("TEXT", 0, 0, None, 0), "encoding": ("TEXT", 0, 0, None, 0),
                "blob": ("BLOB", 0, 0, None, 0), "size_bytes": ("INTEGER", 0, 0, None, 0),
                "checksum": ("TEXT", 0, 0, None, 0), "identity_json": ("TEXT", 0, 0, None, 0),
            }
            canonical_sql = {
                "artifacts": _normalize_artifact_create_sql(_ARTIFACTS_SCHEMA_SQL),
                "artifact_schema_meta": _normalize_artifact_create_sql(_ARTIFACT_SCHEMA_META_SQL),
                _ARTIFACT_PAGING_TABLE: _normalize_artifact_create_sql(_ARTIFACT_PAGING_SCHEMA_SQL),
            }
            def _validate_connection(con: sqlite3.Connection) -> None:
                objects = {
                    str(row[0]): (str(row[1]), str(row[2] or ""))
                    for row in con.execute(
                        """SELECT name, type,
                                  CASE WHEN length(CAST(sql AS BLOB))<=8192 THEN sql END
                           FROM sqlite_master
                           WHERE name IN ('artifacts', 'artifact_schema_meta', 'artifact_paging_metadata')"""
                    )
                }
                if set(objects) != {"artifacts", "artifact_schema_meta", _ARTIFACT_PAGING_TABLE}:
                    raise UnsupportedArtifactSchema("unsupported artifact database schema")
                for name in objects:
                    object_type, statement = objects[name]
                    normalized = _normalize_artifact_create_sql(statement)
                    if (object_type != "table" or "WITHOUT ROWID" in normalized
                            or normalized.startswith("CREATE VIRTUAL TABLE")):
                        raise UnsupportedArtifactSchema("unsupported artifact table storage")
                    if normalized != canonical_sql[name]:
                        raise UnsupportedArtifactSchema("unsupported artifact table definition")
                if con.execute("SELECT 1 FROM sqlite_master WHERE name='artifacts_v2'").fetchone():
                    raise UnsupportedArtifactSchema("unsupported artifact database schema")
                columns = list(con.execute("PRAGMA table_xinfo(artifacts)"))
                actual = {
                    str(row[1]): (
                        str(row[2]).upper(), int(row[5]), int(row[3]), row[4], int(row[6]),
                    ) for row in columns
                }
                if actual != full_schema:
                    raise UnsupportedArtifactSchema("unsupported artifact database schema")
                meta_columns = list(con.execute("PRAGMA table_xinfo(artifact_schema_meta)"))
                actual_meta = {
                    str(row[1]): (str(row[2]).upper(), int(row[5]), int(row[3]), row[4], int(row[6]))
                    for row in meta_columns
                }
                if actual_meta != {
                    "key": ("TEXT", 1, 0, None, 0),
                    "value": ("TEXT", 0, 1, None, 0),
                }:
                    raise UnsupportedArtifactSchema("unsupported artifact schema metadata table")
                paging_columns = list(con.execute(f"PRAGMA table_xinfo({_ARTIFACT_PAGING_TABLE})"))
                actual_paging = {
                    str(row[1]): (str(row[2]).upper(), int(row[5]), int(row[3]), row[4], int(row[6]))
                    for row in paging_columns
                }
                canonical_paging_columns = {
                    "artifact_id": ("TEXT", 1, 0, None, 0),
                    "char_count": ("INTEGER", 0, 1, None, 0),
                    "section_json": ("TEXT", 0, 1, None, 0),
                    "section_checksum": ("TEXT", 0, 1, None, 0),
                    "page_text": ("TEXT", 0, 0, None, 0),
                    "nul_mask": ("BLOB", 0, 0, None, 0),
                }
                if actual_paging != canonical_paging_columns:
                    raise UnsupportedArtifactSchema("unsupported artifact paging metadata table")
                marker = con.execute(
                    """SELECT 1 FROM artifact_schema_meta
                       WHERE key='tenant_storage' AND typeof(value)='text'
                         AND length(CAST(value AS BLOB))=9 AND value='sha256-v1' LIMIT 1"""
                ).fetchone()
                if marker is None:
                    raise UnsupportedArtifactSchema("unsupported artifact tenant storage marker")
                deadline = time.monotonic() + MAX_ARTIFACT_READ_SECONDS
                con.set_progress_handler(
                    lambda: int(time.monotonic() >= deadline), 1000,
                )
                missing_paging = None
                stale_paging = None
                try:
                    invalid = con.execute(
                        """SELECT 1 FROM artifacts WHERE CASE
                             WHEN typeof(tenant)='text' AND length(CAST(tenant AS BLOB))=64
                               AND typeof(tenant_identity)='text'
                               AND length(CAST(tenant_identity AS BLOB))=64
                             THEN tenant GLOB '*[^0-9a-f]*' OR tenant_identity != tenant
                             ELSE 1 END LIMIT 1"""
                    ).fetchone()
                    missing_paging = con.execute(
                        f"""SELECT 1 FROM artifacts AS a
                             LEFT JOIN {_ARTIFACT_PAGING_TABLE} AS p ON p.artifact_id=a.artifact_id
                             WHERE a.mime_type IS NULL AND p.artifact_id IS NULL LIMIT 1"""
                    ).fetchone()
                    invalid_mime_type = con.execute(
                        """SELECT 1 FROM artifacts
                             WHERE mime_type IS NOT NULL
                               AND (typeof(mime_type)!='text' OR length(CAST(mime_type AS BLOB))=0)
                             LIMIT 1"""
                    ).fetchone()
                    stale_paging = con.execute(
                        f"""SELECT 1 FROM {_ARTIFACT_PAGING_TABLE} AS p
                             LEFT JOIN artifacts AS a ON a.artifact_id=p.artifact_id
                             WHERE a.artifact_id IS NULL OR a.mime_type IS NOT NULL LIMIT 1"""
                    ).fetchone()
                except sqlite3.OperationalError as exc:
                    if time.monotonic() >= deadline:
                        raise UnsupportedArtifactSchema("artifact schema validation exceeded its time limit") from exc
                    raise
                finally:
                    con.set_progress_handler(None, 0)
                if invalid is not None:
                    raise UnsupportedArtifactSchema("invalid artifact tenant identity")
                if missing_paging is not None or invalid_mime_type is not None or stale_paging is not None:
                    raise UnsupportedArtifactSchema("incomplete artifact paging metadata")

            def _validate_existing() -> None:
                # SQLite may create -shm when a WAL-mode DB has no shared-memory file. With no
                # WAL data present, immutable mode avoids that write; with only one sidecar,
                # fail closed rather than let SQLite rebuild either file during inspection.
                with self.path.open("rb") as source:
                    header = source.read(20)
                uri = f"{self.path.resolve().as_uri()}?mode=ro"
                if (
                    len(header) >= 20
                    and header[:16] == b"SQLite format 3\x00"
                    and header[18:20] == b"\x02\x02"
                ):
                    wal_path = self.path.with_name(self.path.name + "-wal")
                    shm_path = self.path.with_name(self.path.name + "-shm")
                    wal_exists, shm_exists = wal_path.exists(), shm_path.exists()
                    if wal_exists != shm_exists:
                        raise UnsupportedArtifactSchema("artifact WAL state cannot be inspected without side effects")
                    if not wal_exists:
                        uri += "&immutable=1"
                with closing(sqlite3.connect(uri, uri=True)) as con:
                    _validate_connection(con)

            fresh = not self.path.exists() or self.path.stat().st_size == 0
            if not fresh:
                try:
                    _validate_existing()
                except sqlite3.Error as exc:
                    if isinstance(exc, UnsupportedArtifactSchema):
                        raise
                    raise UnsupportedArtifactSchema("unable to inspect artifact database schema") from exc

            fresh_database = fresh

            def _setup() -> None:
                nonlocal fresh_database
                with closing(self._connect_for_initialization(fresh=fresh_database)) as con:
                    if fresh_database:
                        objects_exist = con.execute(
                            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') LIMIT 1"
                        ).fetchone()
                        if objects_exist is not None:
                            _validate_connection(con)
                            fresh_database = False
                    else:
                        # Recheck after opening the no-create writer handle, before persistent PRAGMAs.
                        _validate_connection(con)
                    initialize_wal(con)
                    con.execute("BEGIN IMMEDIATE")
                    if not fresh_database:
                        # Recheck under the write lock before mutating artifact state.
                        _validate_connection(con)
                    if fresh_database:
                        con.execute(_ARTIFACTS_SCHEMA_SQL)
                        con.execute(_ARTIFACT_SCHEMA_META_SQL)
                        con.execute(_ARTIFACT_PAGING_SCHEMA_SQL)
                        con.execute(
                            "INSERT INTO artifact_schema_meta(key, value) VALUES('tenant_storage', 'sha256-v1')"
                        )
                    con.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_created ON artifacts(created_at)")
                    self._table = _ARTIFACT_TABLE
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
        if not isinstance(artifact_id, str) or not artifact_id or "\x00" in artifact_id:
            return self._binary_failure("invalid artifact_id")
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
    def _section_label(line: str) -> str | None:
        if len(line) > MAX_ARTIFACT_HEADING_CHARS:
            return None
        match = re.match(r"^(?:#{1,6}\s+([^\n#].*?)|([A-Z][A-Z0-9 _/.-]{2,48}):)\s*$", line.rstrip("\r"))
        label = (match.group(1) or match.group(2) or "").strip().rstrip(":") if match else ""
        return label or None

    @staticmethod
    def _section_slug(label: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:64] or "section"

    @classmethod
    def _section_data(cls, text: str) -> tuple[dict[str, tuple[int, int]], bool]:
        """Build bounded section metadata; `True` means names were omitted."""
        sections: dict[str, tuple[int, int]] = {}
        if len(text) <= MAX_ARTIFACT_SECTION_JSON_CHARS:
            try:
                parsed = json.loads(text, object_pairs_hook=cls._json_object_without_duplicate_keys)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                names, truncated = cls._json_section_names(parsed)
                return {name: (-1, -1) for name in names}, truncated

        names: list[str] = []
        seen: set[str] = set()
        truncated = False
        active_name: str | None = None
        active_start = 0
        cursor = 0
        while cursor < len(text):
            newline = text.find("\n", cursor)
            end = len(text) if newline < 0 else newline
            if end - cursor > MAX_ARTIFACT_HEADING_CHARS:
                truncated = True
                prefix = text[cursor:min(end, cursor + MAX_ARTIFACT_HEADING_CHARS + 1)]
                if re.match(r"^#{1,6}\s+", prefix) and active_name is not None:
                    sections[active_name] = (active_start, cursor)
                    active_name = None
            else:
                label = cls._section_label(text[cursor:end])
                if label is not None:
                    if active_name is not None:
                        sections[active_name] = (active_start, cursor)
                        active_name = None
                    if len(names) < MAX_ARTIFACT_SECTION_NAMES:
                        base = cls._section_slug(label)
                        slug = base
                        suffix = 2
                        while slug in seen:
                            slug = f"{base}-{suffix}"
                            suffix += 1
                        names.append(slug)
                        seen.add(slug)
                        active_name = slug
                        active_start = cursor
                    else:
                        truncated = True
            cursor = end + 1 if newline >= 0 else len(text)
        if active_name is not None:
            sections[active_name] = (active_start, len(text))
        return sections, truncated

    @classmethod
    def _section_names(cls, text: str) -> list[str]:
        sections, _truncated = cls._section_data(text)
        return list(sections)

    @classmethod
    def _section_map(cls, text: str) -> dict[str, tuple[int, int]]:
        sections, _truncated = cls._section_data(text)
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
        section_map, sections_truncated = self._section_data(text)
        sections = list(section_map)[:24]
        sections_truncated = sections_truncated or len(section_map) > len(sections)
        result[field] = preview
        result["artifact"] = {
            "id": artifact_id,
            "full_chars": len(text),
            "inline_chars": len(preview),
            "sections": sections,
            "sections_truncated": sections_truncated,
            "hint": "Fetch only the needed section/slice if the compact preview is insufficient.",
        }
        return result

    def get(self, artifact_id: str, offset: int = 0, max_chars: int = 6000, section: str = "", tenant: str | None = None) -> dict[str, Any]:
        if not isinstance(artifact_id, str) or not artifact_id or "\x00" in artifact_id:
            return {"success": False, "error": "invalid artifact_id", "error_code": "artifact_read_invalid"}
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            return {"success": False, "error": "artifact offset must be a non-negative integer",
                    "error_code": "artifact_read_invalid", "artifact_id": artifact_id}
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 1 <= max_chars <= 50_000:
            return {"success": False, "error": "artifact max_chars must be between 1 and 50000",
                    "error_code": "artifact_read_invalid", "artifact_id": artifact_id}
        if not isinstance(section, str):
            return {"success": False, "error": "artifact section must be a string",
                    "error_code": "artifact_read_invalid", "artifact_id": artifact_id}
        cutoff = time.time() - self.ttl_seconds
        deadline = time.monotonic() + MAX_ARTIFACT_READ_SECONDS
        tenant_identity = self._tenant_identity(tenant) if tenant is not None else None
        if len(section) > MAX_ARTIFACT_HEADING_CHARS:
            return {"success": False, "error": "artifact section name exceeds its limit",
                    "error_code": "artifact_section_invalid", "artifact_id": artifact_id}

        def _do_get() -> dict[str, Any]:
            with closing(self._connect()) as con:
                self._configure_read_deadline(con, deadline)
                con.execute("BEGIN")
                params: list[Any] = [artifact_id, cutoff]
                query = (
                    f"SELECT a.rowid, a.kind, a.mime_type, typeof(a.text), p.artifact_id, "
                    f"CASE WHEN length(CAST(p.section_json AS BLOB)) <= {MAX_ARTIFACT_SECTION_METADATA_BYTES} "
                    "THEN p.section_json END, p.section_checksum "
                    f"FROM {self._table} AS a LEFT JOIN {_ARTIFACT_PAGING_TABLE} AS p "
                    "ON p.artifact_id=a.artifact_id WHERE a.artifact_id=? AND a.created_at>=?"
                )
                if tenant_identity is not None:
                    query += " AND a.tenant_identity=?"
                    params.append(tenant_identity)
                row = con.execute(query, params).fetchone()
                if row is None:
                    return {"success": False, "error": "artifact not found or expired", "artifact_id": artifact_id}
                rowid, kind, mime_type, text_type, paging_id, section_json, section_checksum = row
                if mime_type:
                    return {"success": False, "error": "binary artifact requires binary retrieval"}
                if text_type != "text":
                    return {"success": False, "error": "artifact text encoding unsupported", "error_code": "artifact_text_encoding_unsupported", "artifact_id": artifact_id}
                if paging_id != artifact_id:
                    raise ArtifactTextReadError(
                        "artifact_paging_metadata_invalid", "artifact paging metadata is missing",
                    )
                metadata = (
                    self._decode_section_metadata(section_json, artifact_id, section_checksum)
                    if isinstance(section_json, str) else None
                )
                if section_json is not None and metadata is None:
                    raise ArtifactTextReadError(
                        "artifact_paging_metadata_invalid", "artifact paging metadata is invalid",
                    )
                sections, sections_truncated = metadata if metadata is not None else ([], False)
                encoding = str(con.execute("PRAGMA encoding").fetchone()[0])

                if section:
                    if section.startswith("json:"):
                        text = self._read_small_text(
                            con, int(rowid), encoding, MAX_ARTIFACT_JSON_SOURCE_BYTES, deadline,
                        )
                        try:
                            parsed = json.loads(text, object_pairs_hook=self._json_object_without_duplicate_keys)
                        except (TypeError, ValueError):
                            return {"success": False, "error": "artifact JSON section source is invalid",
                                    "error_code": "artifact_json_invalid", "artifact_id": artifact_id}
                        self._check_read_deadline(deadline)
                        if isinstance(parsed, dict):
                            sections, sections_truncated = self._json_section_names(parsed)
                            key = section[5:]
                            if len(key) > MAX_ARTIFACT_HEADING_CHARS - len("json:"):
                                return {"success": False, "error": "artifact JSON section name exceeds its limit",
                                        "error_code": "artifact_section_invalid", "artifact_id": artifact_id,
                                        "sections": sections, "sections_truncated": True}
                            if key not in parsed:
                                return {"success": False, "error": "artifact section not found", "artifact_id": artifact_id,
                                        "sections": sections, "sections_truncated": sections_truncated}
                            value = json_dumps(parsed[key], ensure_ascii=False, indent=2) if not isinstance(parsed[key], str) else parsed[key]
                            piece = value[offset:offset + max_chars]
                            return {"success": True, "artifact_id": artifact_id, "kind": kind, "section": section,
                                    "text": piece, "offset": offset,
                                    "next_offset": offset + len(piece) if offset + len(piece) < len(value) else None,
                                    "total_chars": len(value), "sections": sections,
                                    "sections_truncated": sections_truncated}

                    scan = self._stream_text(
                        con, int(rowid), encoding, target_section=section, deadline=deadline,
                    )
                    start, end = scan["target_start"], scan["target_end"]
                    if start is None or end is None:
                        return {"success": False, "error": "artifact section not found", "artifact_id": artifact_id,
                                "sections": scan["section_names"], "sections_truncated": scan["sections_truncated"]}
                    section_chars = max(0, end - start)
                    piece_length = max(0, min(max_chars, section_chars - offset))
                    if piece_length:
                        piece_scan = self._stream_text(
                            con, int(rowid), encoding, [(start + offset, piece_length)],
                            parse_sections=False, deadline=deadline,
                        )
                        piece = piece_scan["pieces"][0]
                    else:
                        piece = ""
                    return {"success": True, "artifact_id": artifact_id, "kind": kind, "section": section,
                            "text": piece, "offset": offset,
                            "next_offset": offset + len(piece) if offset + len(piece) < section_chars else None,
                            "total_chars": section_chars, "sections": scan["section_names"],
                            "sections_truncated": scan["sections_truncated"]}

                scan = self._stream_text(
                    con, int(rowid), encoding, [(offset, max_chars)],
                    parse_sections=metadata is None,
                    deadline=deadline,
                )
                piece = scan["pieces"][0]
                total_chars = scan["total_chars"]
                if metadata is None:
                    sections = scan["section_names"]
                    sections_truncated = scan["sections_truncated"]
                return {"success": True, "artifact_id": artifact_id, "kind": kind, "text": piece,
                        "offset": offset,
                        "next_offset": offset + len(piece) if offset + len(piece) < total_chars else None,
                        "total_chars": total_chars, "sections": sections,
                        "sections_truncated": sections_truncated}

        try:
            return retry_busy(_do_get, retries=3)
        except ArtifactTextReadError as exc:
            return {"success": False, "error": str(exc), "error_code": exc.code, "artifact_id": artifact_id}
        except sqlite3.Error:
            if time.monotonic() >= deadline:
                error = ArtifactTextReadError("artifact_text_read_timeout", "artifact text read exceeded its time limit")
                return {"success": False, "error": str(error), "error_code": error.code, "artifact_id": artifact_id}
            raise

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
        deadline = time.monotonic() + MAX_ARTIFACT_READ_SECONDS
        tenant_identity = self._tenant_identity(tenant) if tenant is not None else None

        def _do_get_slices() -> dict[str, Any]:
            with closing(self._connect()) as con:
                self._configure_read_deadline(con, deadline)
                con.execute("BEGIN")
                params: list[Any] = [artifact_id, cutoff]
                query = (
                    f"SELECT a.rowid, a.kind, a.mime_type, typeof(a.text), p.artifact_id, "
                    f"CASE WHEN length(CAST(p.section_json AS BLOB)) <= {MAX_ARTIFACT_SECTION_METADATA_BYTES} "
                    "THEN p.section_json END, p.section_checksum "
                    f"FROM {self._table} AS a LEFT JOIN {_ARTIFACT_PAGING_TABLE} AS p "
                    "ON p.artifact_id=a.artifact_id WHERE a.artifact_id=? AND a.created_at>=?"
                )
                if tenant_identity is not None:
                    query += " AND a.tenant_identity=?"
                    params.append(tenant_identity)
                row = con.execute(query, params).fetchone()
                if row is None:
                    return {"success": False, "error": "artifact not found or expired", "artifact_id": artifact_id}
                rowid, kind, mime_type, text_type, paging_id, section_json, section_checksum = row
                if mime_type:
                    return {"success": False, "error": "binary artifact requires binary retrieval", "artifact_id": artifact_id}
                if text_type != "text":
                    return {"success": False, "error": "artifact text encoding unsupported", "error_code": "artifact_text_encoding_unsupported", "artifact_id": artifact_id}
                if paging_id != artifact_id:
                    raise ArtifactTextReadError(
                        "artifact_paging_metadata_invalid", "artifact paging metadata is missing",
                    )
                metadata = (
                    self._decode_section_metadata(section_json, artifact_id, section_checksum)
                    if isinstance(section_json, str) else None
                )
                if section_json is not None and metadata is None:
                    raise ArtifactTextReadError(
                        "artifact_paging_metadata_invalid", "artifact paging metadata is invalid",
                    )
                sections, sections_truncated = metadata if metadata is not None else ([], False)
                encoding = str(con.execute("PRAGMA encoding").fetchone()[0])
                scan = self._stream_text(
                    con, int(rowid), encoding,
                    [(offset, size) for offset, size in normalized],
                    parse_sections=metadata is None,
                    deadline=deadline,
                )
                pieces = scan["pieces"]
                total_chars = scan["total_chars"]
                if metadata is None:
                    sections = scan["section_names"]
                    sections_truncated = scan["sections_truncated"]

                return {
                    "success": True,
                    "artifact_id": artifact_id,
                    "kind": kind,
                    "slices": [
                        {"offset": offset, "text": pieces[index]}
                        for index, (offset, _max_chars) in enumerate(normalized)
                    ],
                    "total_chars": total_chars,
                    "sections": sections,
                    "sections_truncated": sections_truncated,
                    "truncated": False,
                    "budget_limited": False,
                }

        try:
            return retry_busy(_do_get_slices, retries=3)
        except ArtifactTextReadError as exc:
            return {"success": False, "error": str(exc), "error_code": exc.code, "artifact_id": artifact_id}
        except sqlite3.Error:
            if time.monotonic() >= deadline:
                error = ArtifactTextReadError("artifact_text_read_timeout", "artifact text read exceeded its time limit")
                return {"success": False, "error": str(error), "error_code": error.code, "artifact_id": artifact_id}
            raise

    def get_lines(
        self,
        artifact_id: str,
        start_line: int = 1,
        end_line: int | None = None,
        tenant: str | None = None,
    ) -> dict[str, Any]:
        """Fetch a specific 1-indexed range of lines from a stored text artifact."""
        if isinstance(start_line, bool) or not isinstance(start_line, int) or start_line < 1:
            raise ValueError("start_line must be a positive integer")
        start = start_line
        if end_line is not None:
            if isinstance(end_line, bool) or not isinstance(end_line, int) or end_line < 1:
                raise ValueError("end_line must be a positive integer")
            end = end_line
            if end < start:
                return {
                    "success": False,
                    "error": "end_line must be greater than or equal to start_line",
                    "artifact_id": artifact_id,
                }
        else:
            end = None

        cutoff = time.time() - self.ttl_seconds

        def _do_get() -> tuple[Any, ...] | None:
            with closing(self._connect()) as con:
                query = f"SELECT kind, text, mime_type, created_at FROM {self._table} WHERE artifact_id=? AND created_at>=?"
                params: list[Any] = [artifact_id, cutoff]
                if tenant is not None:
                    query += " AND tenant_identity=?"
                    params.append(self._tenant_identity(tenant))
                return con.execute(query, params).fetchone()

        row = retry_busy(_do_get, retries=3)
        if not row:
            return {"success": False, "error": "artifact not found or expired", "artifact_id": artifact_id}
        if row[2]:
            return {"success": False, "error": "binary artifact cannot be sliced by lines", "artifact_id": artifact_id}

        text = row[1] or ""
        all_lines = text.splitlines()
        total_lines = len(all_lines)

        if start > total_lines or total_lines == 0:
            sliced_lines: list[str] = []
            actual_end = start
        else:
            actual_end = min(end, total_lines) if end is not None else total_lines
            sliced_lines = all_lines[start - 1 : actual_end]

        return {
            "success": True,
            "artifact_id": artifact_id,
            "kind": row[0],
            "start_line": start,
            "end_line": actual_end,
            "total_lines": total_lines,
            "lines": sliced_lines,
            "text": "\n".join(sliced_lines),
        }

    def list(self, tenant: str = "", limit: int = 20) -> list[dict[str, Any]]:
        if not isinstance(tenant, str):
            raise ValueError("tenant label must be a string")
        self._init_db()
        with closing(self._connect()) as con:
            lim = max(1, min(limit, 100))
            if tenant:
                tenant_identity = self._tenant_identity(tenant)
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
