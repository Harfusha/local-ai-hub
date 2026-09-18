from __future__ import annotations

from .json_utils import dumps as json_dumps

import base64
import hashlib
import json
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
_ARTIFACT_V2_TABLE = "artifacts_v2"


class ArtifactTransportError(ValueError):
    """Bounded, caller-safe artifact transport failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ArtifactStore:
    """Stores verbose local outputs outside the agent context and returns compact references."""

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

    @staticmethod
    def _tenant_identity(tenant: str) -> str:
        """Persist stable tenant identity without retaining caller-controlled text."""
        return hashlib.sha256(str(tenant).encode("utf-8")).hexdigest()

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
                        "CREATE TABLE IF NOT EXISTS artifact_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                    )
                    marker = con.execute(
                        "SELECT value FROM artifact_schema_meta WHERE key=?",
                        ("tenant_storage",),
                    ).fetchone()
                    tenant_storage_scrubbed = bool(marker and marker[0] == "sha256-v1")
                    full_schema = {
                        "artifact_id", "created_at", "tenant", "tenant_identity", "kind", "text",
                        "mime_type", "encoding", "blob", "size_bytes", "checksum", "identity_json",
                    }
                    table_info = list(con.execute("PRAGMA table_info(artifacts)"))
                    existing_columns = {str(row[1]) for row in table_info}
                    if not existing_columns:
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
                        legacy_rows = list(con.execute(
                            "SELECT rowid, artifact_id, created_at, tenant, kind, text FROM artifacts"
                        ))
                        for rowid, artifact_id, created_at, tenant, kind, text in legacy_rows:
                            raw_tenant = str(tenant)
                            identity = raw_tenant if tenant_storage_scrubbed else self._tenant_identity(raw_tenant)
                            con.execute("UPDATE artifacts SET tenant=? WHERE rowid=?", (identity, rowid))
                            con.execute(
                                """INSERT OR IGNORE INTO artifacts_v2(
                                    artifact_id, created_at, tenant, tenant_identity, kind, text
                                ) VALUES(?,?,?,?,?,?)""",
                                (artifact_id, created_at, identity, identity, kind, text),
                            )
                        self._table = _ARTIFACT_V2_TABLE
                    con.execute(
                        "INSERT OR REPLACE INTO artifact_schema_meta(key, value) VALUES(?, ?)",
                        ("tenant_storage", "sha256-v1"),
                    )
                    con.execute(f"CREATE INDEX IF NOT EXISTS idx_{self._table}_created ON {self._table}(created_at)")
                    con.commit()
            retry_busy(_setup, retries=5, base_delay_seconds=0.02)
            self._initialized = True

    def _purge(self, con: sqlite3.Connection, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_purge) < self._purge_interval:
            return
        self._last_purge = now
        con.execute(f"DELETE FROM {self._table} WHERE created_at < ?", (now - self.ttl_seconds,))

    def _scoped_artifact_id(self, con: sqlite3.Connection, base_id: str, tenant_identity: str) -> str:
        row = con.execute(
            f"SELECT tenant_identity, tenant FROM {self._table} WHERE artifact_id=?",
            (base_id,),
        ).fetchone()
        existing_identity = str((row[0] if row and row[0] else row[1]) if row else "")
        if not row or existing_identity == tenant_identity:
            return base_id
        return f"{base_id}_{tenant_identity}"

    def put(self, text: str, tenant: str, kind: str) -> str:
        digest = hashlib.sha256((kind + "\0" + text).encode("utf-8")).hexdigest()[:24]
        artifact_id = f"art_{digest}"
        tenant_identity = self._tenant_identity(tenant)
        stored_id = artifact_id
        def _do_put() -> None:
            nonlocal stored_id
            with closing(self._connect()) as con:
                self._purge(con)
                scoped_id = self._scoped_artifact_id(con, artifact_id, tenant_identity)
                con.execute(
                    f"INSERT OR REPLACE INTO {self._table}(artifact_id, created_at, tenant, tenant_identity, kind, text) VALUES(?,?,?,?,?,?)",
                    (scoped_id, time.time(), tenant_identity, tenant_identity, kind, text),
                )
                stored_id = scoped_id
                con.commit()
        retry_busy(_do_put, retries=4)
        return stored_id

    def put_bytes(
        self,
        data: bytes,
        tenant: str,
        kind: str,
        mime_type: str,
    ) -> str:
        """Store complete image bytes without interpreting or truncating them."""
        if not isinstance(data, bytes):
            raise ArtifactTransportError("invalid_bytes", "artifact bytes must be bytes")
        normalized_mime = str(mime_type or "").strip().lower()
        if not normalized_mime.startswith("image/"):
            raise ArtifactTransportError("invalid_mime_type", "image MIME type required")
        if len(data) > self.max_binary_bytes:
            raise ArtifactTransportError("artifact_too_large", "artifact size exceeds configured limit")

        checksum = hashlib.sha256(data).hexdigest()
        base_artifact_id = "art_" + hashlib.sha256(
            (str(kind) + "\0" + normalized_mime + "\0" + checksum).encode("utf-8")
        ).hexdigest()[:24]
        encoding = "base64"
        identity = {
            "artifact_id": base_artifact_id,
            "kind": str(kind),
            "mime_type": normalized_mime,
            "encoding": encoding,
            "size_bytes": len(data),
            "checksum": checksum,
        }
        tenant_identity = self._tenant_identity(tenant)

        artifact_id = ""
        def _do_put() -> None:
            nonlocal artifact_id
            with closing(self._connect()) as con:
                self._purge(con)
                artifact_id = self._scoped_artifact_id(con, base_artifact_id, tenant_identity)
                identity["artifact_id"] = artifact_id
                con.execute(
                    f"""INSERT OR REPLACE INTO {self._table}(
                        artifact_id, created_at, tenant, tenant_identity, kind, text, mime_type,
                        encoding, blob, size_bytes, checksum, identity_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        artifact_id,
                        time.time(),
                        tenant_identity,
                        tenant_identity,
                        str(kind),
                        "",
                        normalized_mime,
                        encoding,
                        sqlite3.Binary(data),
                        len(data),
                        checksum,
                        json_dumps(identity, ensure_ascii=False),
                    ),
                )
                con.commit()

        retry_busy(_do_put, retries=4)
        return artifact_id

    def put_json(self, value: dict[str, Any], tenant: str, kind: str) -> str:
        """Store a bounded JSON artifact, preserving full DOM payload semantics."""
        if not isinstance(value, dict):
            raise ArtifactTransportError("invalid_json", "JSON artifact must be an object")
        text = json_dumps(value, ensure_ascii=False, sort_keys=True)
        if len(text.encode("utf-8")) > self.max_json_bytes:
            raise ArtifactTransportError("artifact_too_large", "JSON artifact size exceeds configured limit")
        return self.put(text, tenant, kind)

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
        cutoff = time.time() - self.ttl_seconds
        def _do_get() -> tuple[str, str, float] | None:
            with closing(self._connect()) as con:
                # Reads stay read-only; expiry cleanup happens on writes. This avoids
                # turning every artifact slice fetch into a WAL writer.
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
            return {"success": False, "error": "binary artifact requires binary retrieval"}
        text = row[1]
        section = str(section or "").strip()
        sections = self._section_map(text)
        if section:
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if section.startswith("json:") and isinstance(parsed, dict):
                key = section[5:]
                if key not in parsed:
                    return {"success": False, "error": "artifact section not found", "artifact_id": artifact_id, "sections": list(sections)[:50]}
                value = json_dumps(parsed[key], ensure_ascii=False, indent=2) if not isinstance(parsed[key], str) else parsed[key]
                piece = value[:max_chars]
                return {"success": True, "artifact_id": artifact_id, "kind": row[0], "section": section, "text": piece,
                        "next_offset": len(piece) if len(piece) < len(value) else None, "total_chars": len(value), "sections": list(sections)[:50]}
            if section not in sections:
                return {"success": False, "error": "artifact section not found", "artifact_id": artifact_id, "sections": list(sections)[:50]}
            start, end = sections[section]
            section_text = text[start:end]
            piece = section_text[offset:offset + max_chars]
            return {"success": True, "artifact_id": artifact_id, "kind": row[0], "section": section, "text": piece,
                    "offset": offset, "next_offset": offset + len(piece) if offset + len(piece) < len(section_text) else None,
                    "total_chars": len(section_text), "sections": list(sections)[:50]}

        piece = text[offset:offset + max_chars]
        return {
            "success": True,
            "artifact_id": artifact_id,
            "kind": row[0],
            "text": piece,
            "offset": offset,
            "next_offset": offset + len(piece) if offset + len(piece) < len(text) else None,
            "total_chars": len(text),
            "sections": list(sections)[:50],
        }
