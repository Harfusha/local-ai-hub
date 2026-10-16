from __future__ import annotations

from .json_utils import dumps as json_dumps

import hashlib
import importlib
import heapq
import json
import logging
import math
import os
import errno
import sqlite3
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .cache import SQLiteCache, TieredCache, SingleFlightCache, stable_hash
from .normalizer import normalize_query
from .scheduler import QueueFullError
from .sqlite_support import (
    connect_sqlite,
    ensure_incremental_vacuum,
    initialize_wal,
    is_busy_error,
    retry_busy,
    quick_sanity_check,
)
from .process_utils import canonical_root, canonical_workspace_id


import re
from functools import lru_cache
from collections import OrderedDict


_MAX_RERANK_CANDIDATES = 512
_INDEX_EMBED_BATCH_SIZE = 64
# Approximate pruning stays opt-in until representative recall is validated.
_CENTROID_FILTER_ENABLED = False
_CENTROID_FILTER_MIN_CHUNKS = 10_000
_CENTROID_COUNT = 64
_CENTROID_SAMPLE_SIZE = 512
_CENTROID_ITERATIONS = 8
_CENTROID_PROBES = 4
_CENTROID_CACHE_MAX_ENTRIES = 8
_CENTROID_CACHE_MAX_BYTES = 64 * 1024 * 1024
_CENTROID_ENTRY_MAX_BYTES = 16 * 1024 * 1024
_CENTROID_CACHE_LOCK = threading.RLock()
_CENTROID_BUILD_LOCK = threading.Lock()
_CENTROID_CACHE: OrderedDict[tuple[Any, ...], tuple[Any, dict[int, tuple[tuple[str, int], ...]], int]] = OrderedDict()
_CENTROID_CACHE_BYTES = 0
_REGEX_AST_MAX_SOURCE_CHARS = 2_000_000
_REGEX_AST_BUDGET_SECONDS = 0.5
_REGEX_AST_MAX_BLOCK_DEPTH = 4096
_REGEX_AST_MAX_BLOCKS = 4096
_RUST_LIFETIME_RE = re.compile(r"'[A-Za-z_][A-Za-z0-9_]*")


def _centroid_threshold_reached(chunk_count: int) -> bool:
    return chunk_count > _CENTROID_FILTER_MIN_CHUNKS


def _fine_cosine_scores(matrix: Any, query_vector: Any) -> Any:
    """Exact cosine stage, kept separate so candidate filtering stays measurable."""
    import numpy as np

    norms = np.linalg.norm(matrix, axis=1)
    valid = np.isfinite(norms) & (norms > 1e-9)
    if valid.any():
        dot_scores = np.dot(matrix, query_vector)
        np.divide(dot_scores, norms, out=norms, where=valid)
    norms[~valid] = 0.0
    norms[~np.isfinite(norms)] = 0.0
    return norms


def _decode_centroid_vector(raw: Any, dimension: int, np: Any) -> Any | None:
    try:
        if isinstance(raw, (bytes, memoryview)):
            vector = np.frombuffer(raw, dtype=np.float32)
        elif isinstance(raw, str):
            vector = np.asarray(json.loads(raw), dtype=np.float32)
        else:
            return None
        vector = np.asarray(vector, dtype=np.float32).reshape(-1)
        if vector.size != dimension or not np.isfinite(vector).all():
            return None
        norm = float(np.linalg.norm(vector))
        if norm > 1e-9:
            vector = vector / norm
        return vector
    except Exception:
        return None


def _centroid_cache_get(key: tuple[Any, ...]) -> tuple[Any, dict[int, tuple[tuple[str, int], ...]], int] | None:
    with _CENTROID_CACHE_LOCK:
        value = _CENTROID_CACHE.get(key)
        if value is not None:
            _CENTROID_CACHE.move_to_end(key)
        return value


def _centroid_cache_put(
    key: tuple[Any, ...],
    value: tuple[Any, dict[int, tuple[tuple[str, int], ...]], int],
) -> bool:
    global _CENTROID_CACHE_BYTES
    size = value[2]
    if size > _CENTROID_ENTRY_MAX_BYTES:
        return False
    with _CENTROID_CACHE_LOCK:
        for old_key in tuple(_CENTROID_CACHE):
            if old_key != key and old_key[:4] == key[:4]:
                _CENTROID_CACHE_BYTES -= _CENTROID_CACHE.pop(old_key)[2]
        previous = _CENTROID_CACHE.pop(key, None)
        if previous is not None:
            _CENTROID_CACHE_BYTES -= previous[2]
        while _CENTROID_CACHE and (
            len(_CENTROID_CACHE) >= _CENTROID_CACHE_MAX_ENTRIES
            or _CENTROID_CACHE_BYTES + size > _CENTROID_CACHE_MAX_BYTES
        ):
            _, evicted = _CENTROID_CACHE.popitem(last=False)
            _CENTROID_CACHE_BYTES -= evicted[2]
        _CENTROID_CACHE[key] = value
        _CENTROID_CACHE_BYTES += size
    return True


class ProjectPolicySyncError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable



def _reverse_text_order(value: str) -> tuple[int, ...]:
    """Heap key where lexically smaller text has higher semantic rank."""
    return tuple(-ord(char) for char in value) + (1,)


def _canonical_fragment_text(text: str) -> str:
    """Normalize transport-only differences without changing source semantics."""
    return str(text).replace("\r\n", "\n").replace("\r", "\n")


def _fragment_hash(text: str) -> str:
    return hashlib.sha1(
        _canonical_fragment_text(text).encode("utf-8"), usedforsecurity=False
    ).hexdigest()


@lru_cache(maxsize=131_072)
def _simhash_shingle_hash(shingle: str) -> int:
    return int(
        hashlib.md5(shingle.encode("utf-8"), usedforsecurity=False).hexdigest()[:16],
        16,
    )


def _simhash(text: str) -> int:
    """Compute 64-bit SimHash of text based on character 4-grams."""
    clean = re.sub(r"\s+", " ", text.lower().strip())
    if len(clean) < 4:
        shingles = [clean] if clean else []
    else:
        shingles = [clean[i : i + 4] for i in range(len(clean) - 3)]
    if not shingles:
        return 0

    # Start at -N, then add two for each set bit. This is mathematically
    # identical to adding +1/-1 for every bit, without 64 Python bit tests
    # per shingle.
    v = [-len(shingles)] * 64
    for s in shingles:
        h = _simhash_shingle_hash(s)
        while h:
            lsb = h & -h
            v[lsb.bit_length() - 1] += 2
            h ^= lsb
    fp = 0
    for i in range(64):
        if v[i] > 0:
            fp |= (1 << i)
    return fp


def _python_ast_chunks(text: str, size: int | Any = 4500, overlap: int | Any = 450) -> list[str]:
    store = RAGStore.__new__(RAGStore)
    sz = size if isinstance(size, int) else 4500
    ov = overlap if isinstance(overlap, int) else 450
    return store._python_ast_chunks(text, sz, ov)


def _regex_ast_chunks(text: str, language: str, size: int = 4500) -> list[str]:
    """Conservatively split brace languages without cutting balanced code blocks.

    This is lexical grouping, not parsing: each outermost brace block stays whole,
    including oversized classes or functions. Ambiguous, malformed, or over-budget
    input is kept as one complete chunk rather than split at an unsafe boundary.
    """
    if language not in {"typescript", "c_sharp", "go", "rust"}:
        return []
    if len(text) > _REGEX_AST_MAX_SOURCE_CHARS or size < 1:
        return [text] if text.strip() else []

    deadline = time.monotonic() + _REGEX_AST_BUDGET_SECONDS
    spans: list[tuple[int, int]] = []
    braces: list[int] = []
    segment_start = 0
    index = 0
    text_length = len(text)

    def skip_escaped_quote(start: int, quote: str) -> tuple[int, bool]:
        cursor = start + 1
        while cursor < text_length:
            if cursor % 8192 == 0 and time.monotonic() >= deadline:
                return text_length, False
            char = text[cursor]
            if char == "\\":
                cursor += 2
                continue
            if char == quote:
                return cursor + 1, True
            cursor += 1
        return text_length, False

    def skip_verbatim_quote(quote_index: int) -> tuple[int, bool]:
        cursor = quote_index + 1
        while cursor < text_length:
            if cursor % 8192 == 0 and time.monotonic() >= deadline:
                return text_length, False
            if text[cursor] == '"':
                if cursor + 1 < text_length and text[cursor + 1] == '"':
                    cursor += 2
                    continue
                return cursor + 1, True
            cursor += 1
        return text_length, False

    while index < text_length:
        if index % 8192 == 0 and time.monotonic() >= deadline:
            return [text] if text.strip() else []

        if text.startswith("//", index):
            newline = text.find("\n", index + 2)
            index = text_length if newline < 0 else newline + 1
            continue
        if text.startswith("/*", index):
            cursor = index + 2
            depth = 1
            while cursor < text_length and depth:
                if cursor % 8192 == 0 and time.monotonic() >= deadline:
                    return [text] if text.strip() else []
                if text.startswith("/*", cursor):
                    depth += 1
                    cursor += 2
                elif text.startswith("*/", cursor):
                    depth -= 1
                    cursor += 2
                else:
                    cursor += 1
            if depth:
                return [text] if text.strip() else []
            index = cursor
            continue

        if language == "c_sharp" and text[index] in "$@":
            if re.match(r"(?:\$+@?|@\$+)\"", text[index:]):
                # Interpolation expressions may contain quoted strings and
                # nested braces; this scanner cannot prove their boundaries.
                return [text] if text.strip() else []

        if language == "c_sharp" and (text.startswith('@"', index)
                or text.startswith('$@"', index) or text.startswith('@$"', index)):
            quote_index = index + 1 if text.startswith('@"', index) else index + 2
            index, closed = skip_verbatim_quote(quote_index)
            if not closed:
                return [text] if text.strip() else []
            continue

        raw_prefix = None
        if language == "rust":
            if text.startswith("br", index):
                raw_prefix = index + 2
            elif text[index] == "r":
                raw_prefix = index + 1
        if raw_prefix is not None:
            hash_end = raw_prefix
            while hash_end < text_length and text[hash_end] == "#":
                if hash_end % 8192 == 0 and time.monotonic() >= deadline:
                    return [text] if text.strip() else []
                hash_end += 1
            if hash_end < text_length and text[hash_end] == '"':
                terminator = '"' + text[raw_prefix:hash_end]
                close_at = text.find(terminator, hash_end + 1)
                if close_at < 0:
                    return [text] if text.strip() else []
                index = close_at + len(terminator)
                continue

        if language == "c_sharp" and text[index] == '"':
            quote_end = index
            while quote_end < text_length and text[quote_end] == '"':
                if quote_end % 8192 == 0 and time.monotonic() >= deadline:
                    return [text] if text.strip() else []
                quote_end += 1
            delimiter_size = quote_end - index
            if delimiter_size >= 3:
                delimiter = '"' * delimiter_size
                close_at = text.find(delimiter, quote_end)
                if close_at < 0:
                    return [text] if text.strip() else []
                index = close_at + delimiter_size
                continue

        if language == "rust" and text[index] == "'":
            lifetime = _RUST_LIFETIME_RE.match(text, index)
            if lifetime is not None:
                # ``match(text, index)`` returns absolute match offsets.
                after_lifetime = lifetime.end()
                if after_lifetime >= text_length or text[after_lifetime] != "'":
                    index = after_lifetime
                    continue

        if text[index] in "'\"`":
            if language == "typescript" and text[index] == "`":
                first_close = text.find("`", index + 1)
                interpolation = text.find("${", index + 1, first_close if first_close >= 0 else text_length)
                if interpolation >= 0:
                    expression_close = text.find("}", interpolation + 2, first_close if first_close >= 0 else text_length)
                    if expression_close < 0:
                        # Nested templates inside ${...} need a real template
                        # lexer; keep the source whole rather than ending early.
                        return [text] if text.strip() else []
            index, closed = skip_escaped_quote(index, text[index])
            if not closed:
                return [text] if text.strip() else []
            continue

        if language == "typescript" and text[index] == "/":
            prefix = text[max(0, index - 32):index].rstrip()
            previous = prefix[-1:] if prefix else ""
            starts_expression = (
                not prefix
                or previous in "([{=,:;!?&|+-*%^~>"
                or re.search(r"\b(?:return|throw|case|yield|await|else|do)\s*$", prefix) is not None
            )
            if starts_expression:
                cursor = index + 1
                in_character_class = False
                closed = False
                while cursor < text_length and text[cursor] not in "\r\n":
                    if cursor % 8192 == 0 and time.monotonic() >= deadline:
                        return [text] if text.strip() else []
                    if text[cursor] == "\\":
                        cursor += 2
                        continue
                    if text[cursor] == "[":
                        in_character_class = True
                    elif text[cursor] == "]":
                        in_character_class = False
                    elif text[cursor] == "/" and not in_character_class:
                        cursor += 1
                        while cursor < text_length and text[cursor].isalpha():
                            cursor += 1
                        closed = True
                        break
                    cursor += 1
                if closed:
                    index = cursor
                    continue
                return [text] if text.strip() else []

        if text[index] == "{":
            if language == "typescript" and not braces:
                # A typed function can contain a structural return type before
                # its body. Brace balancing alone cannot distinguish that type
                # from the body, so retain this source as one safe unit.
                header = text[segment_start:index]
                suffix = header[-512:]
                if len(header) > 512 and re.search(r"\)[ \t]*:[ \t]*$", suffix):
                    return [text] if text.strip() else []
                if re.search(r"\bfunction\b[^;{}]*\)[ \t]*:[ \t]*$", suffix):
                    return [text] if text.strip() else []
            if len(braces) >= _REGEX_AST_MAX_BLOCK_DEPTH:
                return [text] if text.strip() else []
            if not braces:
                braces.append(segment_start)
            else:
                braces.append(index)
            index += 1
            continue
        if text[index] == "}":
            if not braces:
                return [text] if text.strip() else []
            braces.pop()
            index += 1
            if not braces:
                if len(spans) >= _REGEX_AST_MAX_BLOCKS:
                    return [text] if text.strip() else []
                spans.append((segment_start, index))
                segment_start = index
            continue
        index += 1

    if braces:
        return [text] if text.strip() else []
    if not spans:
        return [text] if text.strip() else []
    if len(spans) + int(segment_start < text_length) > _REGEX_AST_MAX_BLOCKS:
        return [text] if text.strip() else []

    chunks: list[str] = []
    pending_parts: list[str] = []
    pending_chars = 0
    for start, end in spans:
        if time.monotonic() >= deadline:
            return [text] if text.strip() else []
        block = text[start:end]
        if pending_parts and pending_chars + len(block) > size:
            chunks.append("".join(pending_parts))
            pending_parts = []
            pending_chars = 0
        if len(block) > size:
            if pending_parts:
                chunks.append("".join(pending_parts))
                pending_parts = []
                pending_chars = 0
            chunks.append(block)
        else:
            pending_parts.append(block)
            pending_chars += len(block)
    # Unbraced declarations/expressions in the tail have no proven safe split.
    # Keep the entire tail together even when it exceeds the requested size.
    if segment_start < text_length:
        tail = text[segment_start:]
        if pending_parts and pending_chars + len(tail) <= size:
            pending_parts.append(tail)
            pending_chars += len(tail)
        else:
            if pending_parts:
                chunks.append("".join(pending_parts))
            pending_parts = [tail]
    if time.monotonic() >= deadline:
        return [text] if text.strip() else []
    if pending_parts:
        chunks.append("".join(pending_parts))
    return chunks


def _serialize_embedding(vector: Any) -> bytes | str | None:
    try:
        values = [float(value) for value in vector]
        if values and not any(value != 0.0 for value in values):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    if not values or not all(math.isfinite(value) for value in values) or not any(value != 0.0 for value in values):
        return None
    try:
        import numpy as np
        packed = np.asarray(values, dtype=np.float32)
        if not np.isfinite(packed).all() or float(np.linalg.norm(packed)) <= 1e-9:
            return None
        return sqlite3.Binary(packed.tobytes())
    except ImportError:
        return json_dumps(values, separators=(",", ":"))
    except (TypeError, ValueError, OverflowError):
        return None


def _read_bounded_file(path: Path, max_bytes: int) -> bytes | None:
    """Read at most max_bytes plus one byte to detect growth after stat."""
    limit = max(0, int(max_bytes))
    with path.open("rb") as source:
        raw = source.read(limit + 1)
    return raw if len(raw) <= limit else None


class RAGStore:
    """Persistent semantic index with file-level incremental updates.

    Local AI keeps a metadata manifest so unchanged files are not reopened/chunked during
    re-index. Changed files are updated transactionally while searches keep seeing
    the previous committed snapshot until the new one is ready.
    """

    def __init__(self, config: dict[str, Any], services: Any = None, reranker: Any = None):
        self.config = config
        self.services = services
        self.reranker = reranker
        state_dir = Path(config["server"]["state_dir"])
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "rag.sqlite3"
        if not ensure_incremental_vacuum(self.db_path).get("success"):
            logging.getLogger(__name__).warning("RAG database incremental vacuum setup incomplete")
        self.scope = str(config.get("rag", {}).get("scope", "shared")).lower()
        self._workspace_locks: dict[str, threading.RLock] = {}
        self._workspace_locks_guard = threading.Lock()
        self._index_lock = threading.RLock()
        self._index_flights_lock = threading.Lock()
        self._index_flights: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._index_wait_timeout_seconds = float(
            config.get("resilience", {}).get("singleflight_wait_timeout_seconds", 240)
        )
        preprocessing_cfg = config.get("preprocessing", {})
        self._sqlite_busy_seconds = max(
            0.25, float(preprocessing_cfg.get("sqlite_busy_timeout_seconds", 0.5))
        )
        self._sqlite_write_retries = max(
            1, int(preprocessing_cfg.get("sqlite_write_retries", 6))
        )
        rag_cfg = config.get("rag", {})
        cpu_cfg = config.get("cpu_retrieval", {})
        model_cfg = config.get("models", {})
        self.index_fingerprint = stable_hash({
            "app_version": __version__,
            "embedding": model_cfg.get("embedding"),
            "backend": model_cfg.get("embedding_backend"),
            "device": model_cfg.get("embedding_device"),
            "digest": model_cfg.get("embedding_digest") or model_cfg.get("model_digest"),
            "revision": model_cfg.get("embedding_revision") or model_cfg.get("model_revision"),
            "dimension": model_cfg.get("embedding_dimension", cpu_cfg.get("embedding_dimension")),
            "normalized": model_cfg.get("embedding_normalized"),
            "max_seq": cpu_cfg.get("embedding_max_seq_length", 8192),
            "chunk_chars": rag_cfg.get("chunk_chars", 4500),
            "chunk_overlap": rag_cfg.get("chunk_overlap_chars", 450),
        })
        self.index_reset = False
        workspace_cfg = config.get("workspace_cache", {})
        self.search_cache = TieredCache(
            SQLiteCache(
                state_dir / "cache.sqlite", f"rag-search:{self.index_fingerprint[:16]}",
                int(workspace_cfg.get("rag_search_ttl_seconds", 86400)),
                int(workspace_cfg.get("rag_search_max_entries", 10000)),
            ),
            l1_entries=256, l1_ttl_seconds=900,
        )
        self.search_flight = SingleFlightCache(
            self.search_cache, enabled=True,
            wait_timeout_seconds=float(config.get("resilience", {}).get("singleflight_wait_timeout_seconds", 240)),
        )
        try:
            retry_busy(self._init_db, retries=5, base_delay_seconds=0.02)
        except sqlite3.DatabaseError as exc:
            if not is_busy_error(exc):
                self._recover_db()

    def _get_workspace_lock(self, workspace: str | None = None) -> threading.RLock:
        ws_key = str(workspace or "default")
        with self._workspace_locks_guard:
            if ws_key not in self._workspace_locks:
                self._workspace_locks[ws_key] = threading.RLock()
            return self._workspace_locks[ws_key]

    def _recover_db(self) -> None:
        import time
        stamp = int(time.time())
        try:
            if self.db_path.exists():
                self.db_path.replace(self.db_path.with_name(self.db_path.name + f".corrupt-{stamp}"))
            for suffix in ("-wal", "-shm"):
                side = Path(str(self.db_path) + suffix)
                if side.exists(): side.unlink()
        except OSError:
            pass
        retry_busy(self._init_db, retries=5, base_delay_seconds=0.02)

    def _connect(self) -> sqlite3.Connection:
        con = connect_sqlite(self.db_path, timeout_seconds=5.0)
        try:
            con.execute("PRAGMA cache_size=-16000")
            con.execute("PRAGMA mmap_size=134217728")
        except sqlite3.OperationalError:
            pass
        return con

    def _init_db(self) -> None:
        with closing(self._connect()) as con:
            initialize_wal(con)
            if not quick_sanity_check(con):
                raise sqlite3.DatabaseError("rag sanity check failed")
            legacy_schema_reset = False
            existing_chunks = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks'"
            ).fetchone()
            if existing_chunks is not None:
                chunk_columns = {
                    str(row[1]) for row in con.execute("PRAGMA table_info(chunks)").fetchall()
                }
                if "embedding_space" not in chunk_columns:
                    con.execute("DROP TABLE IF EXISTS chunk_fts")
                    con.execute("DROP TABLE IF EXISTS chunks")
                    con.execute("DROP TABLE IF EXISTS files")
                    con.execute("DROP TABLE IF EXISTS rag_meta")
                    legacy_schema_reset = True
            con.execute(
                """CREATE TABLE IF NOT EXISTS chunks (
                    tenant TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    path TEXT NOT NULL,
                    chunk_no INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    embedding_space TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (tenant, workspace, path, chunk_no)
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS files (
                    tenant TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    path TEXT NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    size INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    PRIMARY KEY (tenant, workspace, path)
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS project_file_owners (
                    tenant TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    root TEXT NOT NULL,
                    path TEXT NOT NULL,
                    PRIMARY KEY (tenant, workspace, root, path)
                )"""
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_project_file_owners_path "
                "ON project_file_owners(tenant, workspace, path)"
            )
            try:
                con.execute(
                    """CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
                        tenant UNINDEXED,
                        workspace UNINDEXED,
                        path UNINDEXED,
                        chunk_no UNINDEXED,
                        text
                    )"""
                )
            except Exception:
                pass
            con.execute(
                """CREATE TABLE IF NOT EXISTS rag_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )"""
            )
            previous = con.execute("SELECT value FROM rag_meta WHERE key='index_fingerprint'").fetchone()
            current = self.index_fingerprint
            if previous is None:
                existing = int(con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
                self.index_reset = legacy_schema_reset or existing > 0
                if existing:
                    con.execute("DELETE FROM chunks")
                    con.execute("DELETE FROM files")
                    con.execute("DELETE FROM project_file_owners")
                    try:
                        con.execute("DELETE FROM chunk_fts")
                    except Exception:
                        pass
            elif str(previous[0]) != current:
                self.index_reset = True
                con.execute("DELETE FROM chunks")
                con.execute("DELETE FROM files")
                con.execute("DELETE FROM project_file_owners")
                try:
                    con.execute("DELETE FROM chunk_fts")
                except Exception:
                    pass
            con.execute("INSERT OR REPLACE INTO rag_meta(key,value) VALUES('index_fingerprint',?)", (current,))
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_workspace ON chunks(tenant, workspace)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_embedding_space ON chunks(tenant, workspace, embedding_space, path, chunk_no)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_content_hash ON chunks(content_hash)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_tenant_hash ON chunks(tenant, content_hash)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_files_workspace ON files(tenant, workspace)")
            con.commit()

    @staticmethod
    def workspace_id(root: str) -> str:
        return canonical_workspace_id(root)

    def project_config_api(self) -> Any | None:
        """Load project policy lazily so shared revisions without the API still work."""
        try:
            return importlib.import_module("local_ai_hub.project_config")
        except ModuleNotFoundError as exc:
            if exc.name == "local_ai_hub.project_config":
                return None
            raise

    def project_context(self, root: str | Path) -> Any | None:
        api = self.project_config_api()
        if api is None:
            return None
        state_dir = self.config.get("server", {}).get("state_dir", "state")
        return api.resolve_project_context(root, state_dir)

    def _project_phase_allowed(self, project_context: Any | None, phase: str) -> bool:
        if project_context is None:
            return True
        api = self.project_config_api()
        return True if api is None else bool(api.phase_is_allowed(project_context.settings, phase))

    def _project_path_decision(
        self,
        root: str | Path,
        path: str | Path,
        project_context: Any | None,
        *,
        phase: str,
        size_bytes: int,
    ) -> tuple[bool, str | None]:
        if project_context is None:
            return True, None
        api = self.project_config_api()
        if api is None:
            return True, None
        settings = project_context.settings
        kind = api.custom_extension_kind(Path(path).name, settings)
        allowed = api.path_is_allowed(
            root,
            path,
            settings,
            phase=phase,
            binary=kind == "binary",
            size_bytes=size_bytes,
        )
        return bool(allowed), kind

    def _iter_files(
        self,
        root: Path,
        project_context: Any | None = None,
        discovery_errors: set[str] | None = None,
    ) -> Iterable[Path]:
        cfg = self.config.get("rag", {})
        extensions = {x.lower() for x in cfg.get("extensions", [])}
        ignored = {str(name).lower() for name in cfg.get("ignore_dirs", [])}
        max_bytes = int(cfg.get("max_file_bytes", 2_000_000))
        api = self.project_config_api() if project_context is not None else None
        settings = project_context.settings if project_context is not None else None
        if settings is not None and settings.max_file_size_bytes is not None:
            max_bytes = min(max_bytes, int(settings.max_file_size_bytes))
        pending = [Path(root)]
        while pending:
            current = pending.pop()
            if api is not None and settings is not None and not api.may_descend(
                root, current, settings, phase="rag",
                hard_denied=current != root and current.name.lower() in ignored,
            ):
                continue
            try:
                entries = sorted(os.scandir(current), key=lambda entry: entry.name)
            except OSError:
                if discovery_errors is not None:
                    rel = current.relative_to(root).as_posix() if current != root else ""
                    discovery_errors.add(rel)
                continue
            child_dirs: list[Path] = []
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.lower() not in ignored:
                            child = Path(entry.path)
                            if api is None or settings is None or api.may_descend(
                                root, child, settings, phase="rag",
                            ):
                                child_dirs.append(child)
                        continue
                    # Never follow directory symlinks, matching os.walk's default,
                    # but preserve the historical behavior for symlinked files.
                    if entry.is_symlink() and entry.is_dir(follow_symlinks=True):
                        continue
                    path = Path(entry.path)
                    if extensions and path.suffix.lower() not in extensions:
                        kind = api.custom_extension_kind(path.name, settings) if api is not None and settings is not None else None
                        if kind != "text":
                            continue
                    stat = entry.stat(follow_symlinks=True)
                    size_bytes = int(stat.st_size)
                    if size_bytes > max_bytes:
                        continue
                    if api is not None and settings is not None:
                        allowed, kind = self._project_path_decision(
                            root, path, project_context, phase="rag", size_bytes=size_bytes,
                        )
                        if not allowed or kind == "binary":
                            continue
                    yield path
                except OSError:
                    if discovery_errors is not None:
                        rel = Path(entry.path).relative_to(root).as_posix()
                        discovery_errors.add(rel)
                    continue
            pending.extend(reversed(child_dirs))

    def _chunks(self, text: str, path: str = "") -> list[str]:
        """Split text into semantically meaningful chunks.

        For source code files, try syntax-aware splitting first and conservative
        lexical block grouping second. Unsupported formats use paragraph splitting.
        """
        cfg = self.config.get("rag", {})
        size = int(cfg.get("chunk_chars", 4500))
        overlap = min(int(cfg.get("chunk_overlap_chars", 450)), size // 3)

        if len(text) <= size:
            return [text] if text.strip() else []

        # Determine language from extension for AST-aware chunking
        ext = Path(path).suffix.lower() if path else ""
        LANGUAGE_MAP = {
            ".py": "python",
            ".cs": "c_sharp",
            ".ts": "typescript", ".tsx": "typescript",
            ".js": "javascript", ".jsx": "javascript",
            ".rs": "rust",
            ".go": "go",
            ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
            ".c": "c",
            ".java": "java",
            ".rb": "ruby",
            ".php": "php",
            ".sql": "sql",
        }
        lang = LANGUAGE_MAP.get(ext)
        if ext == ".py":
            py_chunks = self._python_ast_chunks(text, size, overlap)
            if py_chunks:
                return py_chunks
        if lang:
            ast_chunks = self._ast_chunks(text, lang, size, overlap)
            if ast_chunks:
                return ast_chunks
        if lang in {"typescript", "c_sharp", "go", "rust"}:
            lexical_chunks = _regex_ast_chunks(text, lang, size)
            if lexical_chunks:
                return lexical_chunks

        # Paragraph-aware fallback (original logic)
        return self._text_chunks(text, size, overlap)

    def _python_ast_chunks(self, text: str, size: int, overlap: int) -> list[str]:
        """Split Python code along AST boundaries (classes, functions) with module import headers."""
        import ast
        try:
            tree = ast.parse(text)
        except Exception:
            return []

        lines = text.splitlines(keepends=True)
        if not lines:
            return []

        import_lines: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                import_lines.extend(lines[node.lineno - 1 : node.end_lineno])
        preamble = "".join(import_lines).strip()
        if len(preamble) > 400:
            preamble = preamble[:400] + "\n# ... imports truncated ..."
        preamble_header = f"# [Module context]\n{preamble}\n\n" if preamble else ""

        chunks: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                block = "".join(lines[node.lineno - 1 : node.end_lineno]).strip()
                full_chunk = f"{preamble_header}{block}" if preamble_header and not block.startswith(preamble[:50]) else block
                if len(full_chunk) <= size:
                    chunks.append(full_chunk)
                else:
                    if isinstance(node, ast.ClassDef):
                        cls_header = f"class {node.name}:\n"
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                m_block = "".join(lines[item.lineno - 1 : item.end_lineno]).strip()
                                sub = f"{preamble_header}{cls_header}    # method {item.name}\n{m_block}"
                                if len(sub) <= size:
                                    chunks.append(sub)
                                else:
                                    chunks.extend(self._text_chunks(sub, size, overlap))
                    else:
                        chunks.extend(self._text_chunks(full_chunk, size, overlap))

        return [c for c in chunks if c.strip()]

    def _ast_chunks(self, text: str, language: str, size: int, overlap: int) -> list[str]:
        """Try to split code using tree-sitter AST boundaries."""
        # Try to load the appropriate language grammar
        try:
            from tree_sitter import Parser
            lang_obj = self._get_ts_language(language)
            if lang_obj is None:
                return []
            parser = Parser(lang_obj)
            tree = parser.parse(text.encode("utf-8", errors="replace"))
        except Exception:
            return []

        # Top-level node types that represent logical code units
        BLOCK_TYPES = {
            "class_definition", "class_declaration", "class_body",
            "function_definition", "function_declaration", "method_declaration",
            "method_definition", "arrow_function",
            "struct_item", "impl_item", "fn_item",
            "func_literal", "function_declaration",
            "namespace_declaration", "struct_declaration",
            "interface_declaration", "enum_declaration",
        }

        def _collect_blocks(node: Any, depth: int = 0) -> list[tuple[int, int]]:
            """Collect byte ranges of top-level logical blocks."""
            if node.type in BLOCK_TYPES and depth <= 2:
                return [(node.start_byte, node.end_byte)]
            blocks: list[tuple[int, int]] = []
            for child in node.children:
                blocks.extend(_collect_blocks(child, depth + 1))
            return blocks

        encoded = text.encode("utf-8", errors="replace")
        blocks = _collect_blocks(tree.root_node)

        if not blocks:
            return []

        chunks: list[str] = []
        covered_end = 0

        # Merge any leading preamble (imports, module declarations) into first block
        if blocks and blocks[0][0] > 0:
            preamble = encoded[:blocks[0][0]].decode("utf-8", errors="replace").strip()
            if preamble:
                blocks[0] = (0, blocks[0][1])

        for start_b, end_b in sorted(blocks):
            # Keep imports, decorators, comments and top-level statements between
            # AST blocks. Previously only preamble and trailing text survived.
            if start_b > covered_end:
                gap = encoded[covered_end:start_b].decode("utf-8", errors="replace").strip()
                if gap:
                    chunks.extend(self._text_chunks(gap, size, overlap))
            block_text = encoded[start_b:end_b].decode("utf-8", errors="replace").strip()
            if not block_text:
                continue
            if len(block_text) <= size:
                chunks.append(block_text)
            else:
                chunks.extend(self._text_chunks(block_text, size, overlap))
            covered_end = max(covered_end, end_b)

        # Any trailing text after last block
        if covered_end < len(encoded):
            tail = encoded[covered_end:].decode("utf-8", errors="replace").strip()
            if tail:
                chunks.extend(self._text_chunks(tail, size, overlap))

        return [c for c in chunks if c.strip()]

    @staticmethod
    def _get_ts_language(language: str) -> Any:
        """Load a tree-sitter Language object for the given language identifier."""
        if os.name == "nt" and sys.version_info >= (3, 13):
            return None
        try:
            from tree_sitter import Language
            if language in ("python",):
                import tree_sitter_python as m; return Language(m.language())
            elif language in ("c_sharp",):
                import tree_sitter_c_sharp as m; return Language(m.language())
            elif language in ("typescript",):
                import tree_sitter_typescript as m; return Language(m.language_typescript())
            elif language in ("javascript",):
                import tree_sitter_javascript as m; return Language(m.language())
        except Exception:
            pass
        return None


    def _text_chunks(self, text: str, size: int, overlap: int) -> list[str]:
        """Paragraph/newline-aware overlap chunker (original logic)."""
        if len(text) <= size:
            return [text] if text.strip() else []
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + size)
            piece = text[start:end]
            if end < len(text):
                split = max(piece.rfind("\n\n"), piece.rfind("\n"))
                if split > size // 2:
                    end = start + split
                    piece = text[start:end]
            if piece.strip():
                chunks.append(piece)
            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
        return chunks


    def _scope_key(self, tenant: str) -> str:
        return tenant if self.scope == "tenant" else "*"

    @staticmethod
    def _workspace_embedding_space_key(scope_key: str, workspace: str) -> str:
        return "workspace_embedding_space:" + stable_hash({"tenant": scope_key, "workspace": workspace})

    @staticmethod
    def _workspace_index_generation_key(scope_key: str, workspace: str) -> str:
        return "workspace_index_generation:" + stable_hash({"tenant": scope_key, "workspace": workspace})

    @staticmethod
    def _project_root_identity(root: str | Path) -> str:
        canonical = canonical_root(str(Path(root).resolve(strict=False)))
        return stable_hash({"root": canonical})

    @staticmethod
    def _workspace_root_identity_key(scope_key: str, workspace: str) -> str:
        return "workspace_root_identity:" + stable_hash({"tenant": scope_key, "workspace": workspace})

    @staticmethod
    def _workspace_project_config_key(
        scope_key: str, workspace: str, root_identity: str = ""
    ) -> str:
        return "workspace_project_config:" + stable_hash({
            "tenant": scope_key, "workspace": workspace, "root": root_identity,
        })

    @staticmethod
    def _workspace_read_uncertainty_key(scope_key: str, workspace: str) -> str:
        return "workspace_read_uncertainty:" + stable_hash({"tenant": scope_key, "workspace": workspace})

    def _workspace_read_uncertain_paths(self, con: sqlite3.Connection, scope_key: str, workspace: str) -> set[str]:
        key = self._workspace_read_uncertainty_key(scope_key, workspace)
        row = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()
        if row is None or not row[0]:
            return set()
        try:
            value = json.loads(str(row[0]))
        except (TypeError, ValueError):
            return {"*"}
        if not isinstance(value, list):
            return {"*"}
        return {str(path).replace("\\", "/") for path in value if isinstance(path, str) and path.strip()}

    def _update_workspace_read_uncertainty(
        self, con: sqlite3.Connection, scope_key: str, workspace: str,
        *, uncertain_paths: set[str] | None = None, clear_paths: set[str] | None = None,
        bump_generation: bool = True,
    ) -> bool:
        key = self._workspace_read_uncertainty_key(scope_key, workspace)
        current = self._workspace_read_uncertain_paths(con, scope_key, workspace)
        updated = current - {str(path).replace("\\", "/") for path in (clear_paths or set())}
        updated |= {str(path).replace("\\", "/") for path in (uncertain_paths or set())}
        if updated == current:
            return False
        if updated:
            con.execute("INSERT OR REPLACE INTO rag_meta(key,value) VALUES(?,?)", (
                key, json.dumps(sorted(updated), separators=(",", ":")),
            ))
        else:
            con.execute("DELETE FROM rag_meta WHERE key=?", (key,))
        if bump_generation:
            self._bump_workspace_index_generation(con, scope_key, workspace)
        return True

    def _publish_workspace_read_uncertainty(
        self, scope_key: str, workspace: str, uncertain_paths: set[str]
    ) -> None:
        if not uncertain_paths:
            return

        def publish() -> None:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                changed = self._update_workspace_read_uncertainty(
                    con, scope_key, workspace,
                    uncertain_paths=uncertain_paths,
                    bump_generation=False,
                )
                if changed:
                    self._bump_workspace_index_generation(con, scope_key, workspace)
                con.commit()

        retry_busy(
            publish,
            retries=self._sqlite_write_retries,
            base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
        )

    def _sync_workspace_project_policy_identity(
        self,
        root: str | Path,
        scope_key: str,
        workspace: str,
        project_context: Any | None,
    ) -> int:
        """Bind policy state to one root and prune only paths conclusively rejected."""
        digest = getattr(project_context, "config_digest", None)
        if not isinstance(digest, str) or not digest:
            return 0
        root_path = Path(root).resolve(strict=False)
        root_identity = self._project_root_identity(root_path)
        context_root = getattr(project_context, "root", None)
        if context_root is not None and self._project_root_identity(context_root) != root_identity:
            raise ProjectPolicySyncError(
                "project policy context belongs to a different root",
                retryable=False,
            )
        key = self._workspace_project_config_key(scope_key, workspace, root_identity)
        root_key = self._workspace_root_identity_key(scope_key, workspace)
        with closing(self._connect()) as con:
            bound_root = con.execute("SELECT value FROM rag_meta WHERE key=?", (root_key,)).fetchone()
            if bound_root is not None and str(bound_root[0]) != root_identity:
                raise ProjectPolicySyncError(
                    "RAG workspace is already bound to a different project root",
                    retryable=False,
                )
            previous = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()
            previous_digest = str(previous[0]) if previous is not None else None
            if previous_digest == digest and bound_root is not None:
                return 0
            rows = con.execute(
                "SELECT path FROM files WHERE tenant=? AND workspace=?",
                (scope_key, workspace),
            ).fetchall()

        cfg = self.config.get("rag", {})
        extensions = {str(ext).lower() for ext in cfg.get("extensions", [])}
        ignored = {str(name).lower() for name in cfg.get("ignore_dirs", [])}
        max_bytes = int(cfg.get("max_file_bytes", 2_000_000))
        settings = project_context.settings
        if settings.max_file_size_bytes is not None:
            max_bytes = min(max_bytes, int(settings.max_file_size_bytes))
        rag_enabled = self._project_phase_allowed(project_context, "rag")
        rejected: list[str] = []
        uncertain: set[str] = set()
        for row in rows:
            rel = str(row[0]).replace("\\", "/")
            try:
                candidate = (root_path / rel).resolve(strict=False)
                candidate.relative_to(root_path)
                stat = candidate.stat()
                if not candidate.is_file():
                    rejected.append(rel)
                    continue
                api = self.project_config_api()
                kind = api.custom_extension_kind(candidate.name, settings) if api is not None else None
                if (
                    not rag_enabled
                    or any(part.lower() in ignored for part in Path(rel).parts[:-1])
                    or (extensions and candidate.suffix.lower() not in extensions and kind != "text")
                    or int(stat.st_size) > max_bytes
                ):
                    rejected.append(rel)
                    continue
                allowed, kind = self._project_path_decision(
                    root_path, candidate, project_context, phase="rag",
                    size_bytes=int(stat.st_size),
                )
                if not allowed or kind == "binary":
                    rejected.append(rel)
            except ValueError:
                rejected.append(rel)
                continue
            except OSError as exc:
                if exc.errno in {errno.ENOENT, errno.ENOTDIR}:
                    rejected.append(rel)
                    continue
                uncertain.add(rel)
            except RuntimeError:
                uncertain.add(rel)

        if uncertain:
            self._publish_workspace_read_uncertainty(scope_key, workspace, uncertain)
            raise ProjectPolicySyncError(
                "project policy scan could not verify indexed paths; retry required",
                retryable=True,
            )

        def verify_current_context() -> None:
            current_context = self.project_context(root_path)
            current_digest = getattr(current_context, "config_digest", None)
            current_root = getattr(current_context, "root", None)
            if (
                current_digest != digest
                or (current_root is not None and self._project_root_identity(current_root) != root_identity)
            ):
                raise ProjectPolicySyncError(
                    "project policy changed during RAG policy synchronization",
                    retryable=True,
                )

        def persist_identity() -> int:
            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                current_root = con.execute(
                    "SELECT value FROM rag_meta WHERE key=?", (root_key,)
                ).fetchone()
                if current_root is not None and str(current_root[0]) != root_identity:
                    con.rollback()
                    raise ProjectPolicySyncError(
                        "RAG workspace was concurrently bound to a different project root",
                        retryable=False,
                    )
                current = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()
                current_digest = str(current[0]) if current is not None else None
                if current_digest == digest and current_root is not None:
                    con.rollback()
                    return 0
                if current_digest != previous_digest:
                    con.rollback()
                    raise ProjectPolicySyncError(
                        "project policy identity changed during RAG policy synchronization",
                        retryable=True,
                    )
                verify_current_context()
                if rejected:
                    pairs = [(scope_key, workspace, rel) for rel in sorted(set(rejected))]
                    con.executemany(
                        "DELETE FROM chunks WHERE tenant=? AND workspace=? AND path=?", pairs
                    )
                    con.executemany(
                        "DELETE FROM files WHERE tenant=? AND workspace=? AND path=?", pairs
                    )
                    fts_exists = con.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'"
                    ).fetchone() is not None
                    if fts_exists:
                        con.executemany(
                            "DELETE FROM chunk_fts WHERE tenant=? AND workspace=? AND path=?", pairs
                        )
                    self._update_workspace_read_uncertainty(
                        con, scope_key, workspace, clear_paths=set(rejected), bump_generation=False
                    )
                con.execute(
                    "INSERT OR REPLACE INTO rag_meta(key,value) VALUES(?,?)",
                    (root_key, root_identity),
                )
                con.execute("INSERT OR REPLACE INTO rag_meta(key,value) VALUES(?,?)", (key, digest))
                self._bump_workspace_index_generation(con, scope_key, workspace)
                verify_current_context()
                con.commit()
            return len(set(rejected))

        return retry_busy(
            persist_identity,
            retries=5,
            base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
        )

    def _workspace_index_generation(self, con: sqlite3.Connection, scope_key: str, workspace: str) -> int:
        key = self._workspace_index_generation_key(scope_key, workspace)
        row = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()
        try:
            return max(0, int(row[0])) if row and row[0] is not None else 0
        except (TypeError, ValueError):
            return 0

    def _bump_workspace_index_generation(self, con: sqlite3.Connection, scope_key: str, workspace: str) -> int:
        key = self._workspace_index_generation_key(scope_key, workspace)
        generation = self._workspace_index_generation(con, scope_key, workspace) + 1
        con.execute("INSERT OR REPLACE INTO rag_meta(key,value) VALUES(?,?)", (key, str(generation)))
        return generation

    def _stored_workspace_embedding_space(
        self, con: sqlite3.Connection, scope_key: str, workspace: str
    ) -> str | None:
        key = self._workspace_embedding_space_key(scope_key, workspace)
        row = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row and row[0] else None

    def _store_workspace_embedding_space(
        self, con: sqlite3.Connection, scope_key: str, workspace: str, embedding_space: str
    ) -> None:
        key = self._workspace_embedding_space_key(scope_key, workspace)
        con.execute("INSERT OR REPLACE INTO rag_meta(key,value) VALUES(?,?)", (key, embedding_space))

    def _embedding_space_is_resolved(self, result: dict[str, Any] | None = None) -> bool:
        if isinstance(result, dict) and result.get("embedding_space_id"):
            return True
        service_space = getattr(self.services, "space_id", None)
        if service_space and not callable(service_space):
            return True
        if isinstance(result, dict) and result.get("success"):
            embeddings = result.get("embeddings")
            if isinstance(embeddings, (list, tuple)) and embeddings:
                return True
        embedder = getattr(self.services, "embeddings", None)
        if getattr(embedder, "_active_cache_identity", None):
            return True
        models = self.config.get("models", {})
        return bool(
            models.get("embedding_digest") or models.get("model_digest")
            or models.get("embedding_revision") or models.get("model_revision")
        )

    def _embedding_space_cache_identity_known(self) -> bool:
        service_space = getattr(self.services, "space_id", None)
        if service_space and not callable(service_space):
            return True
        embedder = getattr(self.services, "embeddings", None)
        return bool(getattr(embedder, "_active_cache_identity", None))

    def _embedding_dimension_cache_identity(self) -> dict[str, Any]:
        models = self.config.get("models", {})
        cpu_cfg = self.config.get("cpu_retrieval", {})

        def valid_dimension(value: Any) -> int | None:
            return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

        dimensions: dict[str, Any] = {
            "configured_model": valid_dimension(models.get("embedding_dimension")),
            "configured_cpu": valid_dimension(cpu_cfg.get("embedding_dimension")),
        }
        for owner_name, owner in (
            ("services", self.services),
            ("embedder", getattr(self.services, "embeddings", None)),
        ):
            for attribute in ("_active_embedding_dimension", "embedding_dimension", "dimension"):
                dimension = valid_dimension(getattr(owner, attribute, None)) if owner is not None else None
                if dimension is not None:
                    dimensions[f"{owner_name}_{attribute}"] = dimension
        return dimensions

    def _embedding_space_id(self, result: dict[str, Any] | None = None) -> str:
        if isinstance(result, dict) and result.get("embedding_space_id"):
            return str(result["embedding_space_id"])
        service_space = getattr(self.services, "space_id", None)
        if service_space and not callable(service_space):
            return str(service_space)
        embedder = getattr(self.services, "embeddings", None)
        identity_factory = getattr(embedder, "embedding_space_id", None)
        if callable(identity_factory):
            return str(identity_factory())
        models = self.config.get("models", {})
        backend = str((result or {}).get("backend") or models.get("embedding_backend", "unknown"))
        model = str((result or {}).get("model") or models.get("embedding", "unknown"))
        result_dimension = (result or {}).get("embedding_dimension") or models.get("embedding_dimension")
        normalized = (result or {}).get("normalized", models.get("embedding_normalized"))
        if normalized is None and backend in {"sentence-transformers", "openvino"}:
            normalized = True
        elif normalized is None and backend == "ollama":
            normalized = False
        payload = {
            "backend": backend,
            "model": model,
            "digest": (result or {}).get("model_digest") or models.get("embedding_digest") or models.get("model_digest"),
            "revision": (result or {}).get("model_revision") or models.get("embedding_revision") or models.get("model_revision"),
            "device": (result or {}).get("device") or models.get("embedding_device"),
            "dimension": result_dimension,
            "normalized": normalized,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def index(self, root: str, tenant: str, workspace: str | None = None) -> dict[str, Any]:
        resolved_root = str(Path(root).resolve())
        resolved_workspace = workspace or self.workspace_id(resolved_root)
        flight_key = (resolved_root, self._scope_key(tenant), resolved_workspace)
        with self._index_flights_lock:
            flight = self._index_flights.get(flight_key)
            if flight is None:
                flight = {"event": threading.Event(), "result": None}
                self._index_flights[flight_key] = flight
                owner = True
            else:
                owner = False

        if not owner:
            if not flight["event"].wait(self._index_wait_timeout_seconds):
                return {
                    "success": False,
                    "error": "timed out waiting for identical RAG indexing work",
                    "retryable": True,
                    "coalesced": True,
                }
            shared_result = flight.get("result")
            if isinstance(shared_result, dict):
                result = dict(shared_result)
                result["coalesced"] = True
                return result
            return {
                "success": False,
                "error": "identical RAG indexing work ended without a result",
                "retryable": True,
                "coalesced": True,
            }

        result: dict[str, Any] = {
            "success": False,
            "error": "RAG indexing cancelled before publish completed",
            "retryable": True,
        }
        try:
            with self._get_workspace_lock(resolved_workspace):
                result = self._index_locked(resolved_root, tenant, resolved_workspace)
        except Exception as exc:
            result = {
                "success": False, "error": str(exc),
                "retryable": bool(getattr(exc, "retryable", is_busy_error(exc))),
            }
        finally:
            flight["result"] = result
            flight["event"].set()
            with self._index_flights_lock:
                self._index_flights.pop(flight_key, None)
        return result

    def _index_locked(
        self, root: str, tenant: str, workspace: str | None = None, *,
        _space_override: str | None = None, _identity_retry: bool = False,
    ) -> dict[str, Any]:
        try:
            root_path = Path(root).resolve()
            root_available = root_path.exists() and root_path.is_dir()
        except OSError as exc:
            return {
                "success": False,
                "retryable": True,
                "error": f"unable to inspect root directory: {exc}",
            }
        if not root_available:
            return {
                "success": False,
                "retryable": True,
                "error": f"root directory is unavailable: {root_path}",
            }
        project_context = self.project_context(root_path)
        if not self._project_phase_allowed(project_context, "rag"):
            target_ws = workspace or self.workspace_id(str(root_path))
            removed = self.prune_missing(root_path, tenant, target_ws, [])
            return {
                "success": True, "workspace": target_ws,
                "skipped": True, "reason": "project phase disabled",
                "removed_paths": removed, "processed_paths": [],
            }
        workspace = workspace or self.workspace_id(str(root_path))
        scope_key = self._scope_key(tenant)
        self._sync_workspace_project_policy_identity(root_path, scope_key, workspace, project_context)
        embedding_space = _space_override or self._embedding_space_id()

        with closing(self._connect()) as con:
            uncertain_retry_paths = self._workspace_read_uncertain_paths(con, scope_key, workspace)
            old_files_rows = con.execute(
                "SELECT path,mtime_ns,size,content_hash FROM files WHERE tenant=? AND workspace=?",
                (scope_key, workspace),
            ).fetchall()
            old_chunk_rows = con.execute(
                "SELECT path,chunk_no,content_hash,embedding,embedding_space FROM chunks WHERE tenant=? AND workspace=?",
                (scope_key, workspace),
            ).fetchall()
        old_files = {r[0]: {"mtime_ns": int(r[1]), "size": int(r[2]), "content_hash": r[3]} for r in old_files_rows}
        persisted_spaces = {
            str(r[4]).strip()
            for r in old_chunk_rows
            if r[4] and str(r[4]).strip()
        }
        if _space_override is None and len(persisted_spaces) == 1 and (
            not getattr(self.services, "space_id", None)
            and not self.config.get("models", {}).get("embedding_digest")
            and not self.config.get("models", {}).get("embedding_revision")
        ):
            embedding_space = next(iter(persisted_spaces))
        old_chunks = {
            (r[0], int(r[1]), r[2]): r[3]
            for r in old_chunk_rows
            if embedding_space and str(r[4] or "").strip() == embedding_space
        }
        embedding_space_changed = any(
            str(row[4] or "") != embedding_space for row in old_chunk_rows
        )

        current_meta: dict[str, tuple[Path, int, int]] = {}
        metadata_scanned = 0
        discovery_errors: set[str] = set()
        for path in self._iter_files(
            root_path, project_context,
            discovery_errors if embedding_space_changed else None,
        ):
            metadata_scanned += 1
            try:
                stat = path.stat()
                rel = str(path.relative_to(root_path)).replace("\\", "/")
                current_meta[rel] = (path, int(stat.st_mtime_ns), int(stat.st_size))
            except OSError:
                rel = path.relative_to(root_path).as_posix()
                if rel in old_files:
                    discovery_errors.add(rel)
                continue

        current_paths = set(current_meta)
        old_paths = set(old_files)
        discovery_error_hides_old_file = any(
            not failed_path
            or rel == failed_path
            or rel.startswith(failed_path + "/")
            for failed_path in discovery_errors
            for rel in old_files
        )
        if embedding_space_changed and discovery_error_hides_old_file:
            return {
                "success": False,
                "retryable": True,
                "workspace": workspace,
                "error": "embedding-space reindex could not inspect previously indexed files",
            }
        deleted_paths = sorted(old_paths - current_paths)
        unchanged_paths: list[str] = []
        changed_paths: list[str] = []
        for rel, (_path, mtime_ns, size) in current_meta.items():
            old = old_files.get(rel)
            if (
                old and old["mtime_ns"] == mtime_ns and old["size"] == size
                and rel not in uncertain_retry_paths
            ):
                unchanged_paths.append(rel)
            else:
                changed_paths.append(rel)
        if embedding_space_changed:
            unchanged_paths = []
            changed_paths = sorted(current_meta)

        changed_records: list[dict[str, Any]] = []
        file_rows: list[tuple[str, int, int, str]] = []
        read_uncertain_paths: set[str] = set()
        skipped = 0
        read_files = 0
        reused_chunks = 0
        changed_indices: list[int] = []
        rag_cfg = self.config.get("rag", {})
        dedup_near_duplicates = bool(rag_cfg.get("dedup_near_duplicates", True))
        max_hamming = int(rag_cfg.get("near_duplicate_max_hamming", 4))
        near_duplicates_skipped = 0
        max_file_bytes = max(0, int(rag_cfg.get("max_file_bytes", 2_000_000)))
        settings = project_context.settings if project_context is not None else None
        if settings is not None and settings.max_file_size_bytes is not None:
            max_file_bytes = min(max_file_bytes, int(settings.max_file_size_bytes))

        for rel in changed_paths:
            path, mtime_ns, size = current_meta[rel]
            try:
                raw = _read_bounded_file(path, max_file_bytes)
                if raw is None:
                    skipped += 1
                    read_uncertain_paths.add(rel)
                    continue
                read_files += 1
                text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
                file_hash = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
            except Exception:
                skipped += 1
                read_uncertain_paths.add(rel)
                continue
            file_rows.append((rel, mtime_ns, size, file_hash))
            file_chunks = self._chunks(text, path=rel)
            seen_simhashes: list[int] = []
            chunk_seq = 0
            for chunk in file_chunks:
                if dedup_near_duplicates and len(chunk) > 80:
                    fp = _simhash(chunk)
                    if fp != 0 and any((fp ^ s_fp).bit_count() <= max_hamming for s_fp in seen_simhashes):
                        near_duplicates_skipped += 1
                        continue
                    if fp != 0:
                        seen_simhashes.append(fp)

                chunk_hash = _fragment_hash(chunk)
                record = {
                    "path": rel,
                    "chunk_no": chunk_seq,
                    "text": chunk,
                    "hash": chunk_hash,
                    "embedding": old_chunks.get((rel, chunk_seq, chunk_hash)),
                }
                record["embedding_space"] = embedding_space if record["embedding"] is not None else ""
                chunk_seq += 1
                idx = len(changed_records)
                changed_records.append(record)
                if record["embedding"] is None:
                    changed_indices.append(idx)
                else:
                    reused_chunks += 1

        self._publish_workspace_read_uncertainty(scope_key, workspace, read_uncertain_paths)
        if embedding_space_changed and any(p in old_files for p in read_uncertain_paths):
            return {
                "success": False,
                "retryable": True,
                "workspace": workspace,
                "error": "embedding-space reindex could not read previously indexed files",
            }

        if changed_indices:
            # Cross-workspace chunk reuse check
            pending_by_hash: dict[str, list[int]] = {}
            for idx in changed_indices:
                pending_by_hash.setdefault(str(changed_records[idx]["hash"]), []).append(idx)
            missing_hashes = list(pending_by_hash)
            global_chunks: dict[str, Any] = {}
            with closing(self._connect()) as con:
                for i in range(0, len(missing_hashes), 500):
                    batch_h = missing_hashes[i:i + 500]
                    placeholders = ",".join("?" for _ in batch_h)
                    rows = con.execute(
                        f"SELECT content_hash, embedding FROM chunks WHERE tenant=? AND embedding_space=? AND embedding_space<>'' AND content_hash IN ({placeholders})",
                        (scope_key, embedding_space, *batch_h),
                    ).fetchall()
                    for r in rows:
                        if r[0] and r[1] and str(r[0]) not in global_chunks:
                            global_chunks[str(r[0])] = r[1]

            if global_chunks:
                still_indices: list[int] = []
                for chash, indices in pending_by_hash.items():
                    if chash in global_chunks:
                        for idx in indices:
                            changed_records[idx]["embedding"] = global_chunks[chash]
                            changed_records[idx]["embedding_space"] = embedding_space
                        reused_chunks += len(indices)
                    else:
                        first_idx = indices[0]
                        still_indices.append(first_idx)
                changed_indices = still_indices
            else:
                changed_indices = [indices[0] for indices in pending_by_hash.values()]

        if changed_indices:
            observed_embedding_space: str | None = None
            for offset in range(0, len(changed_indices), _INDEX_EMBED_BATCH_SIZE):
                batch_indices = changed_indices[offset:offset + _INDEX_EMBED_BATCH_SIZE]
                batch_texts = [str(changed_records[idx]["text"]) for idx in batch_indices]
                try:
                    vectors_result = self.services.embed(batch_texts, tenant, priority=2, query=False)
                except (TimeoutError, QueueFullError) as exc:
                    return {"success": False, "retryable": True, "error": f"embedder busy or timed out: {exc}"}
                except Exception as exc:
                    return {"success": False, "retryable": False, "error": f"embedder failed: {exc}"}
                if not isinstance(vectors_result, dict) or not vectors_result.get("success"):
                    return vectors_result if isinstance(vectors_result, dict) else {"success": False, "error": "embed failed"}
                vectors = vectors_result.get("embeddings", [])
                if len(vectors) != len(batch_indices):
                    return {"success": False, "error": f"embedding count mismatch: {len(vectors)} != {len(batch_indices)}"}
                batch_space = self._embedding_space_id(vectors_result)
                if observed_embedding_space is not None and observed_embedding_space != batch_space:
                    return {"success": False, "error": "embedding identity changed during atomic index build", "retryable": True}
                observed_embedding_space = batch_space
                if batch_space != embedding_space:
                    if _identity_retry:
                        return {"success": False, "error": "embedding identity changed during atomic index retry", "retryable": True}
                    if old_chunk_rows or reused_chunks:
                        return self._index_locked(
                            str(root_path), tenant, workspace,
                            _space_override=batch_space, _identity_retry=True,
                        )
                    embedding_space = batch_space
                for idx, vector in zip(batch_indices, vectors):
                    embedding = _serialize_embedding(vector)
                    if embedding is None:
                        return {"success": False, "error": "embedding backend returned an invalid vector"}
                    for duplicate_idx in pending_by_hash[str(changed_records[idx]["hash"])]:
                        changed_records[duplicate_idx]["embedding"] = embedding
                        changed_records[duplicate_idx]["embedding_space"] = batch_space

        # One transaction publishes all changed/deleted file state atomically.
        # The embed phase is intentionally outside this retry: a transient writer
        # must not cause expensive model work to run again.
        def publish() -> None:
            with self._get_workspace_lock(workspace), closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                fts_exists = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'"
                ).fetchone()
                successfully_read_paths = {str(row[0]) for row in file_rows}
                publish_paths = deleted_paths + [rel for rel in changed_paths if rel in successfully_read_paths]
                del_paths = [(scope_key, workspace, rel) for rel in publish_paths]
                if del_paths:
                    con.executemany("DELETE FROM chunks WHERE tenant=? AND workspace=? AND path=?", del_paths)
                    con.executemany("DELETE FROM files WHERE tenant=? AND workspace=? AND path=?", del_paths)
                    if fts_exists:
                        con.executemany("DELETE FROM chunk_fts WHERE tenant=? AND workspace=? AND path=?", del_paths)
                con.execute(
                    "DELETE FROM project_file_owners WHERE tenant=? AND workspace=? AND root=?",
                    (scope_key, workspace, str(root_path)),
                )
                con.executemany(
                    "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?,?)",
                    [
                        (scope_key, workspace, r["path"], r["chunk_no"], r["hash"], r["text"], r["embedding"], r["embedding_space"])
                        for r in changed_records
                    ],
                )
                if fts_exists:
                    con.executemany(
                        "INSERT INTO chunk_fts(tenant,workspace,path,chunk_no,text) VALUES(?,?,?,?,?)",
                        [
                            (scope_key, workspace, record["path"], record["chunk_no"], record["text"])
                            for record in changed_records
                        ],
                    )
                con.executemany(
                    "INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)",
                    [(scope_key, workspace, rel, mtime_ns, size, file_hash) for rel, mtime_ns, size, file_hash in file_rows],
                )
                owner_root = str(root_path)
                con.executemany(
                    "INSERT OR IGNORE INTO project_file_owners(tenant,workspace,root,path) "
                    "SELECT ?,?,?,? WHERE EXISTS (SELECT 1 FROM files WHERE tenant=? AND workspace=? AND path=?)",
                    [
                        (scope_key, workspace, owner_root, rel, scope_key, workspace, rel)
                        for rel in current_meta
                    ],
                )
                self._store_workspace_embedding_space(con, scope_key, workspace, embedding_space)
                uncertainty_changed = self._update_workspace_read_uncertainty(
                    con, scope_key, workspace,
                    uncertain_paths=read_uncertain_paths,
                    clear_paths=set(publish_paths),
                    bump_generation=False,
                )
                if publish_paths or uncertainty_changed:
                    self._bump_workspace_index_generation(con, scope_key, workspace)
                con.commit()

        retry_busy(
            publish,
            retries=self._sqlite_write_retries,
            base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
        )

        with closing(self._connect()) as con:
            chunk_count = con.execute(
                "SELECT COUNT(*) FROM chunks WHERE tenant=? AND workspace=?", (scope_key, workspace)
            ).fetchone()[0]
            file_count = con.execute(
                "SELECT COUNT(*) FROM files WHERE tenant=? AND workspace=?", (scope_key, workspace)
            ).fetchone()[0]

        return {
            "success": True,
            "scope": self.scope,
            "workspace": workspace,
            "files_root": str(root_path),
            "files": int(file_count),
            "chunks": int(chunk_count),
            "metadata_scanned_files": metadata_scanned,
            "read_files": read_files,
            "unchanged_files": len(unchanged_paths),
            "changed_files": len(changed_paths),
            "deleted_files": len(deleted_paths),
            "embedded_chunks": len(changed_indices),
            "reused_chunks": reused_chunks,
            "skipped_files": skipped,
            "read_uncertain_paths": sorted(read_uncertain_paths),
            "near_duplicates_skipped": near_duplicates_skipped,
            "embedding_space_id": embedding_space,
        }


    def prune_missing(self, root: str, tenant: str, workspace: str, current_paths: list[str]) -> int:
        """Delete RAG rows for files no longer present without rescanning the filesystem."""
        scope_key = self._scope_key(tenant)
        current = set(current_paths)
        with self._get_workspace_lock(workspace), closing(self._connect()) as con:
            policy_removed = 0
            if Path(root).is_dir():
                policy_context = self.project_context(root)
                policy_removed = self._sync_workspace_project_policy_identity(
                    root, scope_key, workspace, policy_context
                )
            owner_root = str(Path(root).resolve())
            owned = {str(r[0]) for r in con.execute(
                "SELECT path FROM project_file_owners WHERE tenant=? AND workspace=? AND root=?",
                (scope_key, workspace, owner_root),
            ).fetchall()}
            deleted = owned - current
            for rel in deleted:
                con.execute(
                    "DELETE FROM project_file_owners WHERE tenant=? AND workspace=? AND root=? AND path=?",
                    (scope_key, workspace, owner_root, rel),
                )
                still_owned = con.execute(
                    "SELECT 1 FROM project_file_owners WHERE tenant=? AND workspace=? AND path=? LIMIT 1",
                    (scope_key, workspace, rel),
                ).fetchone()
                if still_owned is None:
                    self._delete_rag_path_rows(con, scope_key, workspace, rel)
            if deleted:
                self._bump_workspace_index_generation(con, scope_key, workspace)
            con.commit()
        return policy_removed + len(deleted)

    @staticmethod
    def _delete_rag_path_rows(con: sqlite3.Connection, tenant: str, workspace: str, path: str) -> None:
        con.execute("DELETE FROM chunks WHERE tenant=? AND workspace=? AND path=?", (tenant, workspace, path))
        con.execute("DELETE FROM files WHERE tenant=? AND workspace=? AND path=?", (tenant, workspace, path))
        try:
            con.execute("DELETE FROM chunk_fts WHERE tenant=? AND workspace=? AND path=?", (tenant, workspace, path))
        except sqlite3.Error:
            pass

    def remove_project(
        self, root: str, tenant: str, workspace: str, *, preserve_paths: set[str] | None = None
    ) -> int:
        """Delete indexed paths only when this exact root owns their provenance."""
        scope_key = self._scope_key(tenant)
        owner_root = str(Path(root).resolve())
        preserve = {str(path).replace("\\", "/") for path in (preserve_paths or set())}
        with self._get_workspace_lock(workspace), closing(self._connect()) as con:
            paths = [str(row[0]) for row in con.execute(
                "SELECT path FROM project_file_owners WHERE tenant=? AND workspace=? AND root=?",
                (scope_key, workspace, owner_root),
            ).fetchall()]
            removed = 0
            for path in paths:
                con.execute(
                    "DELETE FROM project_file_owners WHERE tenant=? AND workspace=? AND root=? AND path=?",
                    (scope_key, workspace, owner_root, path),
                )
                still_owned = con.execute(
                    "SELECT 1 FROM project_file_owners WHERE tenant=? AND workspace=? AND path=? LIMIT 1",
                    (scope_key, workspace, path),
                ).fetchone()
                if still_owned is None and path not in preserve:
                    before = con.total_changes
                    self._delete_rag_path_rows(con, scope_key, workspace, path)
                    removed += int(con.total_changes > before)
            if removed:
                self._bump_workspace_index_generation(con, scope_key, workspace)
            con.commit()
        return removed

    def remove_paths(self, tenant: str, workspace: str, paths: list[str]) -> int:
        """Remove explicitly known paths from a semantic workspace.

        Used when a newer deterministic analyzer proves that a declarative file no
        longer needs embeddings. This keeps rebuilt indexes free of stale semantic chunks.
        """
        scope_key = self._scope_key(tenant)
        unique = sorted({str(p).replace("\\", "/") for p in paths if str(p).strip()})
        if not unique:
            return 0
        removed = 0
        with self._get_workspace_lock(workspace), closing(self._connect()) as con:
            changes_before = con.total_changes
            for rel in unique:
                row = con.execute(
                    "SELECT 1 FROM files WHERE tenant=? AND workspace=? AND path=?",
                    (scope_key, workspace, rel),
                ).fetchone()
                con.execute("DELETE FROM chunks WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                con.execute("DELETE FROM files WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                try:
                    con.execute("DELETE FROM chunk_fts WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                except Exception:
                    pass
                con.execute(
                    "DELETE FROM project_file_owners WHERE tenant=? AND workspace=? AND path=?",
                    (scope_key, workspace, rel),
                )
                removed += int(row is not None)
            if con.total_changes > changes_before:
                self._bump_workspace_index_generation(con, scope_key, workspace)
            con.commit()
        return removed

    def index_paths_step(
        self,
        root: str,
        tenant: str,
        workspace: str,
        paths: list[str],
        should_yield: Any | None = None,
        content_overrides: dict[str, str] | None = None,
        deleted_paths: list[str] | None = None,
        *, _space_override: str | None = None, _identity_retry: bool = False,
    ) -> dict[str, Any]:
        """Index only explicitly dirty paths supplied by Local AI preprocessing.

        This avoids repeatedly walking a cold repository for each micro-step.
        """
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            return {"success": False, "error": f"root directory does not exist: {root_path}"}
        project_context = self.project_context(root_path)
        if not self._project_phase_allowed(project_context, "rag"):
            return {
                "success": True, "workspace": workspace, "skipped": True,
                "reason": "project phase disabled", "processed_paths": [],
                "embedded_chunks": 0, "reused_chunks": 0,
            }
        scope_key = self._scope_key(tenant)
        embedding_space = _space_override or self._embedding_space_id()
        processed_paths: list[str] = []
        embedded_chunks = 0
        reused_chunks = 0
        with self._get_workspace_lock(workspace):
            try:
                self._sync_workspace_project_policy_identity(
                    root_path, scope_key, workspace, project_context
                )
            except ProjectPolicySyncError as exc:
                return {"success": False, "error": str(exc), "retryable": exc.retryable}
            with closing(self._connect()) as con:
                stored_space = self._stored_workspace_embedding_space(con, scope_key, workspace)
                legacy_rows = (
                    con.execute(
                        "SELECT embedding,embedding_space FROM chunks WHERE tenant=? AND workspace=?",
                        (scope_key, workspace),
                    ).fetchall()
                    if stored_space is None else []
                )
            inferred_spaces: set[str] = set()
            unresolved_legacy_vectors = False
            for row in legacy_rows:
                if not row[0]:
                    continue
                row_space = str(row[1] or "").strip()
                if not row_space:
                    unresolved_legacy_vectors = True
                else:
                    inferred_spaces.add(row_space)
            if stored_space is None and (unresolved_legacy_vectors or len(inferred_spaces) > 1):
                return {
                    "success": False, "workspace": workspace,
                    "error": "embedding_space_rebuild_required",
                    "rebuild_required": True, "retryable": False,
                }
            if stored_space is None and inferred_spaces:
                inferred_space = next(iter(inferred_spaces))
                recovery_conflict = {"value": False}

                def persist_recovered_space() -> None:
                    with closing(self._connect()) as con:
                        con.execute("BEGIN IMMEDIATE")
                        current_space = self._stored_workspace_embedding_space(con, scope_key, workspace)
                        if current_space is not None and current_space != inferred_space:
                            con.rollback()
                            recovery_conflict["value"] = True
                            return
                        if current_space is None:
                            self._store_workspace_embedding_space(con, scope_key, workspace, inferred_space)
                            self._bump_workspace_index_generation(con, scope_key, workspace)
                        con.commit()

                try:
                    retry_busy(
                        persist_recovered_space,
                        retries=self._sqlite_write_retries,
                        base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
                    )
                except Exception as exc:
                    return {
                        "success": False, "workspace": workspace,
                        "error": "embedding_space_recovery_failed",
                        "retryable": is_busy_error(exc),
                    }
                if recovery_conflict["value"]:
                    return {
                        "success": False, "workspace": workspace,
                        "error": "embedding_space_rebuild_required",
                        "rebuild_required": True, "retryable": False,
                    }
                stored_space = inferred_space
                embedding_space = inferred_space
            elif stored_space is not None and not self._embedding_space_is_resolved():
                embedding_space = stored_space
            embedding_space_resolved = bool(stored_space or self._embedding_space_is_resolved())
            # 1. Read files and chunk
            file_data: list[dict[str, Any]] = []
            policy_deleted: set[str] = set()
            read_uncertain_paths: set[str] = set()
            ignored_dirs = {
                str(name).lower() for name in self.config.get("rag", {}).get("ignore_dirs", [])
            }
            for rel in paths:
                if callable(should_yield) and should_yield():
                    self._publish_workspace_read_uncertainty(scope_key, workspace, read_uncertain_paths)
                    return {
                        "success": True, "workspace": workspace, "preempted": True,
                        "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
                        "reused_chunks": reused_chunks,
                    }
                rel = str(rel).replace("\\", "/")
                path = (root_path / rel).resolve(strict=False)
                try:
                    relative_path = path.relative_to(root_path)
                except ValueError:
                    continue
                ignored_parts = relative_path.parts[:-1]
                requested_path = Path(os.path.normpath(rel))
                if not requested_path.is_absolute():
                    ignored_parts = (*ignored_parts, *requested_path.parts[:-1])
                if any(part.lower() in ignored_dirs for part in ignored_parts):
                    policy_deleted.add(rel)
                    continue
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                    cfg = self.config.get("rag", {})
                    extensions = {str(ext).lower() for ext in cfg.get("extensions", [])}
                    if extensions and path.suffix.lower() not in extensions:
                        api = self.project_config_api() if project_context is not None else None
                        if api is None or api.custom_extension_kind(path.name, project_context.settings) != "text":
                            policy_deleted.add(rel)
                            continue
                    max_bytes = max(0, int(cfg.get("max_file_bytes", 2_000_000)))
                    if project_context is not None and project_context.settings.max_file_size_bytes is not None:
                        max_bytes = min(max_bytes, int(project_context.settings.max_file_size_bytes))
                    if int(stat.st_size) > max_bytes:
                        policy_deleted.add(rel)
                        continue
                    allowed, kind = self._project_path_decision(
                        root_path, path, project_context, phase="rag", size_bytes=int(stat.st_size),
                    )
                    if not allowed or kind == "binary":
                        policy_deleted.add(rel)
                        continue
                    override = (content_overrides or {}).get(rel)
                    if override is None:
                        raw = _read_bounded_file(path, max_bytes)
                        if raw is None:
                            read_uncertain_paths.add(rel)
                            continue
                        text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
                        file_hash = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
                    else:
                        text = str(override).replace("\r\n", "\n")
                        if len(text.encode("utf-8")) > max_bytes:
                            policy_deleted.add(rel)
                            continue
                        file_hash = hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()
                    chunks = list(self._chunks(text, path=rel))
                    file_data.append({"rel": rel, "stat": stat, "file_hash": file_hash, "chunks": chunks})
                except Exception:
                    read_uncertain_paths.add(rel)
                    continue

            self._publish_workspace_read_uncertainty(scope_key, workspace, read_uncertain_paths)

            deleted_unique = sorted(
                {str(p).replace("\\", "/") for p in (deleted_paths or []) if str(p).strip()}
                | policy_deleted
            )
            if not file_data and not deleted_unique:
                if read_uncertain_paths:
                    def publish_uncertain_only() -> None:
                        with closing(self._connect()) as con:
                            con.execute("BEGIN IMMEDIATE")
                            self._update_workspace_read_uncertainty(
                                con, scope_key, workspace, uncertain_paths=read_uncertain_paths,
                            )
                            con.commit()

                    retry_busy(
                        publish_uncertain_only,
                        retries=self._sqlite_write_retries,
                        base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
                    )
                return {
                    "success": True, "workspace": workspace, "preempted": False,
                    "embedding_space_id": stored_space or embedding_space,
                    "embedding_space_resolved": embedding_space_resolved,
                    "processed_paths": [], "embedded_chunks": 0, "reused_chunks": 0,
                    "read_uncertain_paths": sorted(read_uncertain_paths),
                }

            # 2. Bulk load existing chunks
            all_rels = sorted({f["rel"] for f in file_data} | set(deleted_unique))
            old_chunks: dict[tuple[str, int, str], str] = {}
            with closing(self._connect()) as con:
                # Load in chunks of 500
                for i in range(0, len(all_rels), 500):
                    batch_rels = all_rels[i:i+500]
                    placeholders = ",".join("?" for _ in batch_rels)
                    rows = con.execute(
                        f"SELECT path,chunk_no,content_hash,embedding,embedding_space FROM chunks WHERE tenant=? AND workspace=? AND path IN ({placeholders})",
                        (scope_key, workspace, *batch_rels),
                    ).fetchall()
                    for r in rows:
                        if embedding_space and str(r[4] or "").strip() == embedding_space:
                            old_chunks[(str(r[0]), int(r[1]), str(r[2]))] = r[3]

            # 3. Build records and identify missing embeddings
            all_missing_texts: list[str] = []
            missing_pointers: list[tuple[int, int]] = []  # (file_idx, record_idx)

            for f_idx, item in enumerate(file_data):
                rel = item["rel"]
                records: list[dict[str, Any]] = []
                for chunk_no, chunk in enumerate(item["chunks"]):
                    chash = _fragment_hash(chunk)
                    embedding = old_chunks.get((rel, chunk_no, chash))
                    records.append({
                        "chunk_no": chunk_no, "text": chunk, "hash": chash, "embedding": embedding,
                        "embedding_space": embedding_space if embedding is not None else "",
                    })
                    if embedding is None:
                        all_missing_texts.append(chunk)
                        missing_pointers.append((f_idx, len(records) - 1))
                    else:
                        reused_chunks += 1
                item["records"] = records

            # 4. Cross-workspace / cross-worktree instant chunk embedding reuse
            if all_missing_texts:
                missing_hashes = [file_data[f_idx]["records"][rec_idx]["hash"] for f_idx, rec_idx in missing_pointers]
                global_chunks: dict[str, Any] = {}
                with closing(self._connect()) as con:
                    for i in range(0, len(missing_hashes), 500):
                        batch_h = missing_hashes[i:i + 500]
                        placeholders = ",".join("?" for _ in batch_h)
                        rows = con.execute(
                            f"SELECT content_hash, embedding FROM chunks WHERE tenant=? AND embedding_space=? AND embedding_space<>'' AND content_hash IN ({placeholders})",
                            (scope_key, embedding_space, *batch_h),
                        ).fetchall()
                        for r in rows:
                            if r[0] and r[1] and str(r[0]) not in global_chunks:
                                global_chunks[str(r[0])] = r[1]

                if global_chunks:
                    still_missing_texts: list[str] = []
                    still_missing_pointers: list[tuple[int, int]] = []
                    for (f_idx, rec_idx), text in zip(missing_pointers, all_missing_texts):
                        chash = file_data[f_idx]["records"][rec_idx]["hash"]
                        if chash in global_chunks:
                            file_data[f_idx]["records"][rec_idx]["embedding"] = global_chunks[chash]
                            file_data[f_idx]["records"][rec_idx]["embedding_space"] = embedding_space
                            reused_chunks += 1
                        else:
                            still_missing_texts.append(text)
                            still_missing_pointers.append((f_idx, rec_idx))
                    all_missing_texts = still_missing_texts
                    missing_pointers = still_missing_pointers

            # 5. Embed bounded batches. Do not publish partial vector batches.
            if all_missing_texts:
                if callable(should_yield) and should_yield():
                    return {
                        "success": True, "workspace": workspace, "preempted": True,
                        "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
                        "reused_chunks": reused_chunks,
                    }
                batch_embedding_space = None
                for offset in range(0, len(all_missing_texts), _INDEX_EMBED_BATCH_SIZE):
                    if offset and callable(should_yield) and should_yield():
                        return {
                            "success": True, "workspace": workspace, "preempted": True,
                            "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
                            "reused_chunks": reused_chunks,
                        }
                    batch_texts = all_missing_texts[offset:offset + _INDEX_EMBED_BATCH_SIZE]
                    batch_pointers = missing_pointers[offset:offset + _INDEX_EMBED_BATCH_SIZE]
                    try:
                        vectors_result = self.services.embed(batch_texts, tenant, priority=0, query=False, background=True)
                    except (TimeoutError, QueueFullError) as exc:
                        return {
                            "success": True, "workspace": workspace, "preempted": True,
                            "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
                            "reused_chunks": reused_chunks, "note": f"embedder busy or timed out: {exc}",
                        }
                    if not isinstance(vectors_result, dict) or not vectors_result.get("success"):
                        return vectors_result if isinstance(vectors_result, dict) else {"success": False, "error": "embed failed"}
                    vectors = vectors_result.get("embeddings", [])
                    if len(vectors) != len(batch_pointers):
                        return {"success": False, "error": "embedding count mismatch during background RAG path step"}
                    current_space = self._embedding_space_id(vectors_result)
                    if batch_embedding_space is not None and current_space != batch_embedding_space:
                        return {"success": False, "error": "embedding identity changed during RAG path step", "retryable": True}
                    if batch_embedding_space is None:
                        batch_embedding_space = current_space
                        if current_space != embedding_space:
                            if _identity_retry and reused_chunks:
                                return {"success": False, "error": "embedding identity changed during RAG path retry", "retryable": True}
                            if reused_chunks:
                                return self.index_paths_step(
                                    str(root_path), tenant, workspace, paths,
                                    should_yield=should_yield, content_overrides=content_overrides,
                                    deleted_paths=deleted_paths, _space_override=current_space,
                                    _identity_retry=True,
                                )
                            embedding_space = batch_embedding_space
                        embedding_space_resolved = True
                    for (f_idx, rec_idx), vector in zip(batch_pointers, vectors):
                        embedding = _serialize_embedding(vector)
                        if embedding is None:
                            return {"success": False, "error": "embedding backend returned an invalid vector"}
                        file_data[f_idx]["records"][rec_idx]["embedding"] = embedding
                        file_data[f_idx]["records"][rec_idx]["embedding_space"] = batch_embedding_space
                    embedded_chunks += len(batch_pointers)

            if callable(should_yield) and should_yield():
                return {
                    "success": True, "workspace": workspace, "preempted": True,
                    "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
                    "reused_chunks": reused_chunks,
                }

            # 5. Bulk SQLite transaction
            chunks_to_insert: list[tuple[Any, ...]] = []
            files_to_insert: list[tuple[Any, ...]] = []
            for item in file_data:
                rel = item["rel"]
                stat = item["stat"]
                for r in item["records"]:
                    chunks_to_insert.append((scope_key, workspace, rel, r["chunk_no"], r["hash"], r["text"], r["embedding"], r["embedding_space"]))
                files_to_insert.append((scope_key, workspace, rel, int(stat.st_mtime_ns), int(stat.st_size), item["file_hash"]))
                processed_paths.append(rel)

            def publish() -> None:
                with closing(self._connect()) as con:
                    con.execute("BEGIN IMMEDIATE")
                    fts_exists = con.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'"
                    ).fetchone()
                    for i in range(0, len(all_rels), 500):
                        batch_rels = all_rels[i:i+500]
                        placeholders = ",".join("?" for _ in batch_rels)
                        con.execute(f"DELETE FROM chunks WHERE tenant=? AND workspace=? AND path IN ({placeholders})", (scope_key, workspace, *batch_rels))
                        con.execute(f"DELETE FROM files WHERE tenant=? AND workspace=? AND path IN ({placeholders})", (scope_key, workspace, *batch_rels))
                        if fts_exists:
                            con.execute(f"DELETE FROM chunk_fts WHERE tenant=? AND workspace=? AND path IN ({placeholders})", (scope_key, workspace, *batch_rels))
                    con.executemany(
                        "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?,?)",
                        chunks_to_insert,
                    )
                    if fts_exists:
                        con.executemany(
                            "INSERT INTO chunk_fts(tenant,workspace,path,chunk_no,text) VALUES(?,?,?,?,?)",
                            [(c[0], c[1], c[2], c[3], c[5]) for c in chunks_to_insert],
                        )
                    con.executemany(
                        "INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)",
                        files_to_insert,
                    )
                    for rel in set(deleted_paths or []) | policy_deleted:
                        con.execute(
                            "DELETE FROM project_file_owners WHERE tenant=? AND workspace=? AND root=? AND path=?",
                            (scope_key, workspace, str(root_path), str(rel).replace("\\", "/")),
                        )
                    con.executemany(
                        "INSERT OR IGNORE INTO project_file_owners(tenant,workspace,root,path) VALUES(?,?,?,?)",
                        [(scope_key, workspace, str(root_path), rel) for rel in processed_paths],
                    )
                    if embedding_space:
                        self._store_workspace_embedding_space(con, scope_key, workspace, embedding_space)
                    uncertainty_changed = self._update_workspace_read_uncertainty(
                        con, scope_key, workspace,
                        uncertain_paths=read_uncertain_paths,
                        clear_paths=set(all_rels),
                        bump_generation=False,
                    )
                    if all_rels or uncertainty_changed:
                        self._bump_workspace_index_generation(con, scope_key, workspace)
                    con.commit()

            try:
                retry_busy(
                    publish,
                    retries=self._sqlite_write_retries,
                    base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
                )
            except Exception as exc:
                return {
                    "success": False, "workspace": workspace,
                    "error": "publish_failed", "retryable": is_busy_error(exc),
                }

        return {
            "success": True, "workspace": workspace, "preempted": False,
            "embedding_space_id": embedding_space,
            "embedding_space_resolved": embedding_space_resolved,
            "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
            "reused_chunks": reused_chunks,
            "read_uncertain_paths": sorted(read_uncertain_paths),
        }

    def index_step(
        self,
        root: str,
        tenant: str,
        workspace: str | None = None,
        max_files: int = 2,
        should_yield: Any | None = None,
        dirty_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Index only a few changed files so idle preprocessing stays preemptible.

        Each call commits independently. Repeated calls converge to the same state as
        :meth:`index`, while foreground work can take over between calls.
        """
        root_path = Path(root).resolve()
        if not root_path.exists() or not root_path.is_dir():
            return {"success": False, "error": f"root directory does not exist: {root_path}"}
        project_context = self.project_context(root_path)
        if not self._project_phase_allowed(project_context, "rag"):
            target_ws = workspace or self.workspace_id(str(root_path))
            removed = self.prune_missing(root, tenant, target_ws, [])
            return {
                "success": True, "workspace": target_ws,
                "skipped": True, "reason": "project phase disabled", "done": True,
                "removed_paths": removed,
                "processed_files": 0,
            }
        workspace = workspace or self.workspace_id(str(root_path))
        with self._get_workspace_lock(workspace):
            scope_key = self._scope_key(tenant)
            try:
                self._sync_workspace_project_policy_identity(
                    root_path, scope_key, workspace, project_context
                )
            except ProjectPolicySyncError as exc:
                return {"success": False, "error": str(exc), "retryable": exc.retryable}
            embedding_space = self._embedding_space_id()
            if callable(should_yield) and should_yield():
                return {"success": True, "workspace": workspace, "preempted": True, "done": False, "processed_files": 0}

            with closing(self._connect()) as con:
                old_rows = con.execute(
                    "SELECT path,mtime_ns,size,content_hash FROM files WHERE tenant=? AND workspace=?",
                    (scope_key, workspace),
                ).fetchall()
                old_chunk_rows = con.execute(
                    "SELECT path,chunk_no,content_hash,embedding,embedding_space FROM chunks WHERE tenant=? AND workspace=?",
                    (scope_key, workspace),
                ).fetchall()
                uncertain_retry_paths = self._workspace_read_uncertain_paths(con, scope_key, workspace)
                stale_embedding_paths = {
                    str(row[0]).replace("\\", "/")
                    for row in old_chunk_rows
                    if str(row[4] or "") != embedding_space
                }
            old_files = {r[0]: {"mtime_ns": int(r[1]), "size": int(r[2]), "content_hash": r[3]} for r in old_rows}
            old_chunks = {
                (r[0], int(r[1]), r[2]): r[3]
                for r in old_chunk_rows if str(r[4] or "") == embedding_space
            }

            current_meta: dict[str, tuple[Path, int, int]] = {}
            for path in self._iter_files(root_path, project_context):
                try:
                    st = path.stat()
                    rel = str(path.relative_to(root_path)).replace("\\", "/")
                    current_meta[rel] = (path, int(st.st_mtime_ns), int(st.st_size))
                except OSError:
                    continue
            deleted = sorted(set(old_files) - set(current_meta))
            changed_all = [
                rel for rel, (_p, mt, sz) in current_meta.items()
                if rel not in old_files or old_files[rel]["mtime_ns"] != mt or old_files[rel]["size"] != sz
                or rel in stale_embedding_paths
                or rel in uncertain_retry_paths
            ]
            if dirty_paths:
                norm_dirty = set()
                for dp in dirty_paths:
                    try:
                        p_obj = Path(dp)
                        if p_obj.is_absolute():
                            norm_dirty.add(str(p_obj.relative_to(root_path)).replace("\\", "/"))
                        else:
                            norm_dirty.add(str(dp).replace("\\", "/"))
                    except Exception:
                        norm_dirty.add(str(dp).replace("\\", "/"))
                changed_all = sorted(set(changed_all) | (norm_dirty & set(current_meta)))
                changed_all.sort(key=lambda rel: (rel not in norm_dirty, rel))
            else:
                changed_all.sort()

            pending = sorted(set(changed_all) | set(deleted))
            selected = pending[: max(1, int(max_files))]
            selected_changed = [rel for rel in selected if rel in current_meta]
            selected_deleted = [rel for rel in selected if rel in deleted]
            staged = self.index_paths_step(
                str(root_path), tenant, workspace, selected_changed,
                should_yield=should_yield, deleted_paths=selected_deleted,
            )
            if not staged.get("success"):
                return staged
            completed_paths = {
                str(path).replace("\\\\", "/") for path in staged.get("processed_paths", [])
            }
            completed_paths.update(
                str(path).replace("\\\\", "/") for path in staged.get("deleted_paths", [])
            )
            remaining_paths = set(pending) - completed_paths
            remaining = len(remaining_paths)
            return {
                "success": True, "workspace": workspace,
                "preempted": bool(staged.get("preempted", False)),
                "done": remaining == 0 and not staged.get("preempted", False),
                "processed_files": len(staged.get("processed_paths", [])) + len(selected_deleted),
                "remaining_changed_files": remaining,
                "deleted_files": len(selected_deleted),
                "embedded_chunks": staged.get("embedded_chunks", 0),
                "reused_chunks": staged.get("reused_chunks", 0),
            }

    @staticmethod
    def _dot(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            return 0.0
        if not all(math.isfinite(value) for value in (*a, *b)):
            return 0.0
        dot = RAGStore._dot(a, b)
        na = math.sqrt(RAGStore._dot(a, a))
        nb = math.sqrt(RAGStore._dot(b, b))
        score = dot / (na * nb) if na and nb else 0.0
        return score if math.isfinite(score) else 0.0

    def revision(self, tenant: str, workspace: str) -> str:
        scope_key = self._scope_key(tenant)
        now = time.monotonic()
        if not hasattr(self, "_rev_cache"):
            self._rev_cache: dict[tuple[str, str], tuple[float, str, int]] = {}
            self._rev_lock = threading.Lock()
        with closing(self._connect()) as con:
            generation = self._workspace_index_generation(con, scope_key, workspace)
        with self._rev_lock:
            cached = self._rev_cache.get((scope_key, workspace))
            if cached and now - cached[0] < 3.0 and cached[2] == generation:
                return cached[1]
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT path,content_hash,mtime_ns,size FROM files WHERE tenant=? AND workspace=? ORDER BY path",
                (scope_key, workspace),
            ).fetchall()
        rev = stable_hash({"index": self.index_fingerprint, "generation": generation, "files": rows})
        with self._rev_lock:
            if len(self._rev_cache) > 256:
                oldest_keys = sorted(self._rev_cache.keys(), key=lambda k: self._rev_cache[k][0])[:128]
                for k in oldest_keys:
                    self._rev_cache.pop(k, None)
            self._rev_cache[(scope_key, workspace)] = (now, rev, generation)
        return rev

    @staticmethod
    def _postprocess_search_payload(payload: dict[str, Any], top_k: int) -> dict[str, Any]:
        """Remove duplicate evidence after ranking without altering source text."""
        result = dict(payload)
        removed = 0
        limit = max(1, int(top_k))
        for list_key in ("results", "matches", "chunks", "evidence"):
            candidates = result.get(list_key)
            if not isinstance(candidates, list):
                continue
            seen: set[str] = set()
            unique: list[Any] = []
            for position, item in enumerate(candidates):
                if isinstance(item, dict):
                    identity = str(item.get("content_hash") or "")
                    if not identity:
                        text = item.get("text") or item.get("content") or item.get("excerpt")
                        identity = _fragment_hash(str(text)) if text else stable_hash(item)
                else:
                    identity = _fragment_hash(str(item))
                if identity in seen:
                    removed += 1
                    continue
                seen.add(identity)
                unique.append(item)
                if len(unique) >= limit:
                    removed += len(candidates) - position - 1
                    break
            result[list_key] = unique
        if removed:
            result["deterministic_postprocess"] = {"deduplicated": removed}
        return result

    def search(self, query: str, tenant: str, workspace: str, top_k: int = 8, use_reranker: bool = True, priority: int = 3, scope_path: str | None = None) -> dict[str, Any]:
        if "/" in workspace or "\\" in workspace or ":" in workspace:
            workspace = self.workspace_id(workspace)
        clean_query = normalize_query(query)
        revision = self.revision(tenant, workspace)
        scope_key = self._scope_key(tenant)
        cache_identity_known = self._embedding_space_cache_identity_known()
        query_space = self._embedding_space_id()
        with closing(self._connect()) as con:
            generation = self._workspace_index_generation(con, scope_key, workspace)
        cache_dimension = self._embedding_dimension_cache_identity()

        def cache_key(space: str | None, dimension: dict[str, Any], index_generation: int) -> str:
            return stable_hash({
                "tenant": tenant, "scope": self.scope, "effective_scope": scope_key,
                "workspace": workspace, "revision": revision, "generation": index_generation,
                "query": clean_query, "top_k": top_k, "reranker": use_reranker,
                "scope_path": scope_path,
                "embedding_space": space if cache_identity_known else None,
                "embedding_dimension": dimension,
            })

        key = cache_key(query_space, cache_dimension, generation)
        observed_identity: dict[str, Any] = {}

        def compute_search() -> dict[str, Any]:
            raw_result = self._search_uncached(
                clean_query, tenant, workspace, top_k, use_reranker, priority, scope_path
            )
            observed_identity["space"] = self._embedding_space_id()
            observed_identity["dimension"] = self._embedding_dimension_cache_identity()
            return raw_result

        if cache_identity_known:
            raw, hit, coalesced = self.search_flight.get_or_compute(
                key,
                compute_search,
            )
            actual_space = observed_identity.get("space")
            actual_dimension = observed_identity.get("dimension")
            if (
                actual_dimension is not None
                and (actual_space != query_space or actual_dimension != cache_dimension)
            ):
                self.search_flight.cache.delete(key)
                key = cache_key(str(actual_space) if actual_space else None, actual_dimension, generation)
                computed_raw = raw
                raw, hit, coalesced = self.search_flight.get_or_compute(key, lambda: computed_raw)
            if isinstance(raw, dict) and raw.get("retrieval_mode") == "lexical_fallback":
                self.search_flight.cache.delete(key)
        else:
            raw = self._search_uncached(clean_query, tenant, workspace, top_k, use_reranker, priority, scope_path)
            hit, coalesced = False, False
        with closing(self._connect()) as con:
            latest_generation = self._workspace_index_generation(con, scope_key, workspace)
        if latest_generation != generation:
            raw = self._search_uncached(clean_query, tenant, workspace, top_k, use_reranker, priority, scope_path)
            hit, coalesced = False, False
        result = dict(raw) if isinstance(raw, dict) else {"success": False, "error": "search failed"}
        result["search_cache"] = {"hit": hit, "coalesced": coalesced, "revision": revision}
        return self._postprocess_search_payload(result, top_k) if isinstance(result, dict) else result

    @staticmethod
    def _search_path_exclusion(
        con: sqlite3.Connection, excluded_paths: set[str] | None, column: str
    ) -> str:
        paths = excluded_paths or set()
        if "*" in paths:
            return " AND 0"
        if not paths:
            return ""
        con.execute("CREATE TEMP TABLE rag_uncertain_paths(path TEXT PRIMARY KEY)")
        con.executemany(
            "INSERT OR IGNORE INTO rag_uncertain_paths(path) VALUES(?)",
            [(path,) for path in sorted(paths)],
        )
        con.commit()
        return f" AND {column} NOT IN (SELECT path FROM rag_uncertain_paths)"

    def _search_fts_candidates(
        self, query: str, tenant: str, workspace: str, limit: int = 16,
        scope_path: str | None = None, embedding_space: str | None = None,
        excluded_paths: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        scope_key = self._scope_key(tenant)
        try:
            tokens = [re.sub(r"[^\w_]", "", t) for t in query.split()]
            tokens = [t for t in tokens if len(t) > 1]
            if not tokens:
                return []
            fts_expr = " OR ".join(f'"{t}"' for t in tokens[:8])
            space_filter = " AND c.embedding_space=?" if embedding_space is not None else ""
            space_params = (embedding_space,) if embedding_space is not None else ()
            with closing(self._connect()) as con:
                path_filter = self._search_path_exclusion(con, excluded_paths, "c.path")
                if scope_path:
                    norm_scope = scope_path.replace("\\", "/").rstrip("/")
                    fts_rows = con.execute(
                        f"""SELECT c.path, c.chunk_no, c.text, c.content_hash, bm25(chunk_fts)
                           FROM chunk_fts
                           JOIN chunks c ON c.tenant=chunk_fts.tenant AND c.workspace=chunk_fts.workspace AND c.path=chunk_fts.path AND c.chunk_no=chunk_fts.chunk_no
                           WHERE chunk_fts.tenant=? AND chunk_fts.workspace=? AND (chunk_fts.path=? OR chunk_fts.path LIKE ? || '/%'){space_filter}{path_filter} AND chunk_fts MATCH ?
                           ORDER BY bm25(chunk_fts) LIMIT ?""",
                        (scope_key, workspace, norm_scope, norm_scope, *space_params, fts_expr, limit),
                    ).fetchall()
                else:
                    fts_rows = con.execute(
                        f"""SELECT c.path, c.chunk_no, c.text, c.content_hash, bm25(chunk_fts)
                           FROM chunk_fts
                           JOIN chunks c ON c.tenant=chunk_fts.tenant AND c.workspace=chunk_fts.workspace AND c.path=chunk_fts.path AND c.chunk_no=chunk_fts.chunk_no
                           WHERE chunk_fts.tenant=? AND chunk_fts.workspace=?{space_filter}{path_filter} AND chunk_fts MATCH ?
                           ORDER BY bm25(chunk_fts) LIMIT ?""",
                        (scope_key, workspace, *space_params, fts_expr, limit),
                    ).fetchall()
                return [
                    {
                        "path": r[0], "chunk_no": r[1], "text": r[2], "content_hash": r[3],
                        "fts_score": float(r[4]),
                    }
                    for r in fts_rows
                ]
        except Exception:
            return []

    def _search_token_overlap(
        self, query: str, tenant: str, workspace: str, limit: int = 16,
        scope_path: str | None = None, embedding_space: str | None = None,
        excluded_paths: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        scope_key = self._scope_key(tenant)
        terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 1]
        if not terms:
            return []
        space_filter = " AND embedding_space=?" if embedding_space is not None else ""
        space_params = (embedding_space,) if embedding_space is not None else ()
        with closing(self._connect()) as con:
            path_filter = self._search_path_exclusion(con, excluded_paths, "path")
            if scope_path:
                norm_scope = scope_path.replace("\\", "/").rstrip("/")
                rows = con.execute(
                    "SELECT path, chunk_no, text, content_hash FROM chunks WHERE tenant=? AND workspace=? AND (path=? OR path LIKE ? || '/%')" + space_filter + path_filter,
                    (scope_key, workspace, norm_scope, norm_scope, *space_params),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT path, chunk_no, text, content_hash FROM chunks WHERE tenant=? AND workspace=?" + space_filter + path_filter,
                    (scope_key, workspace, *space_params),
                ).fetchall()
        scored: list[dict[str, Any]] = []
        for r in rows:
            low = str(r[2]).lower()
            matches = sum(1 for t in terms if t in low)
            if matches:
                score = matches / len(terms)
                scored.append({
                    "path": r[0], "chunk_no": r[1], "text": r[2], "content_hash": r[3],
                    "fts_score": float(score),
                })
        scored.sort(key=lambda x: x["fts_score"], reverse=True)
        return scored[:limit]

    def _centroid_index_for_search(
        self, scope_key: str, workspace: str, embedding_space: str, query_vector: Any,
    ) -> tuple[int, tuple[tuple[str, int], ...]] | None:
        try:
            np = importlib.import_module("numpy")
        except Exception:
            return None
        dimension = int(getattr(query_vector, "size", len(query_vector) if isinstance(query_vector, (list, tuple)) else 0))
        if dimension <= 0 or dimension > 4096:
            return None
        with closing(self._connect()) as con:
            generation = self._workspace_index_generation(con, scope_key, workspace)
            row = con.execute(
                "SELECT COUNT(*) FROM chunks WHERE tenant=? AND workspace=? AND embedding_space=? AND embedding_space<>''",
                (scope_key, workspace, embedding_space),
            ).fetchone()
            chunk_count = int(row[0]) if row else 0
        if not _centroid_threshold_reached(chunk_count):
            return None
        key = (str(self.db_path.resolve()), scope_key, workspace, embedding_space, dimension, generation)
        cached = _centroid_cache_get(key)
        if cached is None:
            with _CENTROID_BUILD_LOCK:
                cached = _centroid_cache_get(key)
                if cached is None:
                    cached = self._build_centroid_index(
                        scope_key, workspace, embedding_space, dimension, generation, chunk_count
                    )
                    if cached is not None and not _centroid_cache_put(key, cached):
                        return None
                    cached = _centroid_cache_get(key)
        if cached is None:
            return None
        centers, buckets, _ = cached
        query = np.asarray(query_vector, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(query))
        if query.size != dimension or not math.isfinite(norm) or norm <= 1e-9:
            return None
        similarities = np.dot(centers, query / norm)
        ordered = np.argsort(-similarities, kind="stable")
        selected: list[tuple[str, int]] = []
        for cluster_id in ordered[: min(_CENTROID_PROBES, len(centers))]:
            selected.extend(buckets.get(int(cluster_id), ()))
        return (generation, tuple(selected)) if selected else None

    def _build_centroid_index(
        self, scope_key: str, workspace: str, embedding_space: str,
        dimension: int, generation: int, chunk_count: int,
    ) -> tuple[Any, dict[int, tuple[tuple[str, int], ...]], int] | None:
        try:
            np = importlib.import_module("numpy")
        except Exception:
            return None
        sample_count = min(_CENTROID_SAMPLE_SIZE, chunk_count)
        if sample_count < 2:
            return None
        positions = {
            round(index * (chunk_count - 1) / max(1, sample_count - 1))
            for index in range(sample_count)
        }
        query = (
            "SELECT path,chunk_no,embedding FROM chunks WHERE tenant=? AND workspace=? "
            "AND embedding_space=? AND embedding_space<>'' ORDER BY path,chunk_no"
        )
        with closing(self._connect()) as con:
            con.execute("BEGIN")
            if self._workspace_index_generation(con, scope_key, workspace) != generation:
                return None
            sample = []
            sample_path_bytes = 0
            cursor = con.execute(query, (scope_key, workspace, embedding_space))
            position = 0
            try:
                while True:
                    batch = cursor.fetchmany(512)
                    if not batch:
                        break
                    for path, _, raw in batch:
                        if position in positions:
                            vector = _decode_centroid_vector(raw, dimension, np)
                            if vector is None:
                                return None
                            sample.append(vector)
                            sample_path_bytes += len(str(path).encode("utf-8"))
                        position += 1
            finally:
                cursor.close()
            if len(sample) < 2:
                return None
            training = np.stack(sample).astype(np.float32, copy=False)
            centers = [training[0].copy()]
            while len(centers) < min(_CENTROID_COUNT, len(training)):
                nearest = np.max(np.dot(training, np.stack(centers).T), axis=1)
                candidate = training[int(np.argmin(nearest))]
                if float(np.max(np.dot(np.stack(centers), candidate))) > 0.99999:
                    break
                centers.append(candidate.copy())
            centers_array = np.stack(centers).astype(np.float32, copy=False)
            for _ in range(_CENTROID_ITERATIONS):
                labels = np.argmax(np.dot(training, centers_array.T), axis=1)
                updated = []
                for cluster_id in range(len(centers_array)):
                    members = training[labels == cluster_id]
                    if len(members):
                        center = members.mean(axis=0)
                        norm = float(np.linalg.norm(center))
                        if norm > 1e-9:
                            updated.append(center / norm)
                if not updated:
                    return None
                centers_array = np.stack(updated).astype(np.float32, copy=False)

            estimated_entry_bytes = int(
                centers_array.nbytes
                + chunk_count * (sample_path_bytes // max(1, len(sample)) + 256)
            )
            if estimated_entry_bytes > _CENTROID_ENTRY_MAX_BYTES:
                return None

            buckets: dict[int, list[tuple[str, int]]] = {index: [] for index in range(len(centers_array))}
            retained_bytes = int(centers_array.nbytes)
            cursor = con.execute(query, (scope_key, workspace, embedding_space))
            try:
                while True:
                    batch = cursor.fetchmany(256)
                    if not batch:
                        break
                    vectors = []
                    for _, _, raw in batch:
                        vector = _decode_centroid_vector(raw, dimension, np)
                        if vector is None:
                            return None
                        vectors.append(vector)
                    labels = np.argmax(np.dot(np.stack(vectors), centers_array.T), axis=1)
                    for (path, chunk_no, _), cluster_id in zip(batch, labels):
                        path = str(path)
                        retained_bytes += len(path.encode("utf-8")) + 256
                        if retained_bytes > _CENTROID_ENTRY_MAX_BYTES:
                            return None
                        buckets[int(cluster_id)].append((path, int(chunk_no)))
            finally:
                cursor.close()
            if self._workspace_index_generation(con, scope_key, workspace) != generation:
                return None
        return centers_array, {key: tuple(value) for key, value in buckets.items()}, retained_bytes

    def _search_uncached(self, query: str, tenant: str, workspace: str, top_k: int = 8, use_reranker: bool = True, priority: int = 3, scope_path: str | None = None) -> dict[str, Any]:
        scope_key = self._scope_key(tenant)
        with closing(self._connect()) as con:
            uncertain_paths = self._workspace_read_uncertain_paths(con, scope_key, workspace)

        def visible(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [item for item in candidates if "*" not in uncertain_paths and str(item.get("path", "")) not in uncertain_paths]

        try:
            query_result = self.services.embed([query], tenant, priority=priority, query=True)
        except Exception as exc:
            query_result = {"success": False, "error": str(exc)}
        if query_result.get("success"):
            embeddings = query_result.get("embeddings")
            try:
                if not isinstance(embeddings, (list, tuple)) or not embeddings:
                    raise TypeError("embedding result has no query vector")
                query_vector = [float(value) for value in embeddings[0]]
                valid_query_vector = (
                    bool(query_vector)
                    and all(math.isfinite(value) for value in query_vector)
                )
                if valid_query_vector:
                    query_norm = math.sqrt(sum(value * value for value in query_vector))
                    valid_query_vector = math.isfinite(query_norm) and query_norm > 1e-9
            except (IndexError, KeyError, TypeError, ValueError, OverflowError):
                valid_query_vector = False
            if not valid_query_vector:
                query_result = {**query_result, "success": False, "error": "invalid_query_embedding"}
        if not query_result.get("success"):
            lexical_backend = "fts5"
            candidates = visible(self._search_fts_candidates(
                query, tenant, workspace, max(16, top_k * 2), scope_path,
                excluded_paths=uncertain_paths,
            ))
            if not candidates:
                lexical_backend = "token_overlap"
                candidates = visible(self._search_token_overlap(
                    query, tenant, workspace, max(16, top_k * 2), scope_path,
                    excluded_paths=uncertain_paths,
                ))
            results = [
                {
                    "path": c["path"],
                    "chunk_no": c["chunk_no"],
                    "text": c.get("text", ""),
                    "content_hash": c.get("content_hash", ""),
                    "score": float(c.get("fts_score", 0.5)),
                }
                for c in candidates[:top_k]
            ]
            return {
                "success": True,
                "workspace": workspace,
                "results": results,
                "degraded": True,
                "fallback": "source_read_uncertain" if uncertain_paths else "bm25_fts",
                "retrieval_mode": "lexical_fallback",
                "lexical_backend": lexical_backend,
                "reason": str(query_result.get("error", "embedder_unavailable")),
            }
        query_vec = query_result["embeddings"][0]
        embedding_space = self._embedding_space_id(query_result)
        embedding_space_resolved = self._embedding_space_is_resolved(query_result)
        stored_embedding_space: str | None = None
        stored_embedding_space_read = False
        fallbacks: list[str] = []
        if uncertain_paths:
            fallbacks.append("source_read_uncertain")
        if query_result.get("degraded"):
            fallbacks.append(str(query_result.get("fallback") or "embedding_backend"))

        rag_cfg = self.config.get("rag", {})
        candidate_limit = min(_MAX_RERANK_CANDIDATES, max(16, int(rag_cfg.get("rerank_candidates", 16))))
        query_dim = len(query_vec) if isinstance(query_vec, (list, tuple)) else int(getattr(query_vec, "size", 0))
        configured_batch = int(rag_cfg.get("search_batch_size", 512))
        batch_size = min(8192, max(32, configured_batch))
        if query_dim > 0:
            batch_size = min(batch_size, max(32, (1024 * 1024) // query_dim))
        best: list[tuple[float, tuple[int, ...], int, tuple[int, ...], dict[str, Any]]] = []
        rows_seen = 0
        try:
            import numpy as np
        except Exception:
            np = None

        centroid_index = None
        # Workspace-wide centroids cannot guarantee coverage after a path
        # scope or read-uncertainty exclusion is applied. Keep those queries
        # exact so the prefilter cannot hide their only matching chunks.
        if (
            _CENTROID_FILTER_ENABLED
            and np is not None
            and embedding_space_resolved
            and not scope_path
            and not uncertain_paths
        ):
            try:
                centroid_index = self._centroid_index_for_search(
                    scope_key, workspace, embedding_space, query_vec
                )
            except Exception:
                centroid_index = None

        if np is not None:
            q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
            dimension = int(q.size)
            q_norm = float(np.linalg.norm(q))
            if q_norm > 1e-9:
                q = q / q_norm
            else:
                q = np.zeros(dimension, dtype=np.float32)

        def offer(row: Any, score: float) -> None:
            if "*" in uncertain_paths or str(row[0]) in uncertain_paths:
                return
            score = float(score)
            if not math.isfinite(score):
                score = 0.0
            item = {
                "path": row[0], "chunk_no": row[1], "content_hash": row[3],
                "embedding_score": score,
            }
            entry = (
                score,
                _reverse_text_order(str(row[0])),
                -int(row[1]),
                _reverse_text_order(str(row[3] or "")),
                item,
            )
            if len(best) < candidate_limit:
                heapq.heappush(best, entry)
            elif entry[:4] > best[0][:4]:
                heapq.heapreplace(best, entry)

        with closing(self._connect()) as con:
            # Keep one read snapshot across keyset batches, but close each SQL
            # cursor before vector parsing/scoring so the statement VM is idle.
            path_filter = self._search_path_exclusion(con, uncertain_paths, "path")
            con.execute("BEGIN")
            norm_scope = scope_path.replace("\\", "/").rstrip("/") if scope_path else None
            centroid_active = False
            if centroid_index is not None:
                centroid_generation, centroid_rows = centroid_index
                if self._workspace_index_generation(con, scope_key, workspace) == centroid_generation:
                    con.execute(
                        "CREATE TEMP TABLE IF NOT EXISTS rag_centroid_candidates "
                        "(path TEXT NOT NULL, chunk_no INTEGER NOT NULL, PRIMARY KEY(path,chunk_no)) WITHOUT ROWID"
                    )
                    con.execute("DELETE FROM rag_centroid_candidates")
                    con.executemany(
                        "INSERT OR IGNORE INTO rag_centroid_candidates(path,chunk_no) VALUES(?,?)",
                        centroid_rows,
                    )
                    centroid_active = True
            last_path: str | None = None
            last_chunk_no: int | None = None
            while True:
                predicates = ["tenant=?", "workspace=?", "embedding_space=?", "embedding_space<>''"]
                params: list[Any] = [scope_key, workspace, embedding_space]
                if centroid_active:
                    predicates.append(
                        "EXISTS (SELECT 1 FROM rag_centroid_candidates cc "
                        "WHERE cc.path=chunks.path AND cc.chunk_no=chunks.chunk_no)"
                    )
                if path_filter:
                    predicates.append(path_filter.removeprefix(" AND "))
                if norm_scope is not None:
                    predicates.append("(path=? OR path LIKE ? || '/%')")
                    params.extend((norm_scope, norm_scope))
                if last_path is not None:
                    predicates.append("(path>? OR (path=? AND chunk_no>?))")
                    params.extend((last_path, last_path, last_chunk_no))
                cursor = con.execute(
                    "SELECT chunks.path, chunks.chunk_no, chunks.embedding, chunks.content_hash FROM chunks AS chunks WHERE "
                    + " AND ".join(predicates)
                    + " ORDER BY path, chunk_no LIMIT ?",
                    (*params, batch_size),
                )
                try:
                    batch = cursor.fetchmany(batch_size)
                finally:
                    cursor.close()
                if not batch:
                    break
                rows_seen += len(batch)
                last_path, last_chunk_no = str(batch[-1][0]), int(batch[-1][1])

                if np is not None:
                    if all(isinstance(row[2], (bytes, memoryview)) and len(row[2]) == dimension * 4 for row in batch):
                        packed = b"".join(bytes(row[2]) for row in batch)
                        matrix = np.frombuffer(packed, dtype=np.float32).reshape(len(batch), dimension)
                    else:
                        matrix = np.zeros((len(batch), dimension), dtype=np.float32)
                        for index, row in enumerate(batch):
                            raw = row[2]
                            try:
                                if isinstance(raw, (bytes, memoryview)):
                                    vector = np.frombuffer(raw, dtype=np.float32)
                                elif isinstance(raw, str):
                                    vector = np.asarray(json.loads(raw), dtype=np.float32).reshape(-1)
                                else:
                                    continue
                                if vector.size == dimension:
                                    matrix[index] = vector
                            except (TypeError, ValueError, OverflowError, json.JSONDecodeError):
                                continue
                    scores = _fine_cosine_scores(matrix, q)
                    local_count = min(candidate_limit, len(batch))
                    if local_count < len(batch):
                        kth = len(batch) - local_count
                        partition = np.argpartition(scores, kth)
                        cutoff = scores[partition[kth]]
                        above = np.flatnonzero(scores > cutoff)
                        tied = np.flatnonzero(scores == cutoff)
                        remaining = local_count - len(above)
                        if tied.size > remaining:
                            tie_paths = np.asarray([str(batch[int(index)][0]) for index in tied], dtype=np.str_)
                            tie_chunks = np.fromiter(
                                (int(batch[int(index)][1]) for index in tied), dtype=np.int64, count=len(tied)
                            )
                            tie_hashes = np.asarray(
                                [str(batch[int(index)][3] or "") for index in tied], dtype=np.str_
                            )
                            tie_order = np.lexsort((tie_hashes, tie_chunks, tie_paths))
                            tied = tied[tie_order[:remaining]]
                        candidate_indices = np.concatenate((above, tied))
                    else:
                        candidate_indices = np.arange(len(batch), dtype=np.intp)
                    for index in candidate_indices:
                        offer(batch[int(index)], float(scores[int(index)]))
                else:
                    import struct

                    for index, row in enumerate(batch):
                        raw = row[2]
                        try:
                            if isinstance(raw, (bytes, memoryview)) and len(raw) % 4 == 0:
                                vector = struct.unpack(f"{len(raw) // 4}f", raw)
                            elif isinstance(raw, str):
                                vector = [float(value) for value in json.loads(raw)]
                            else:
                                vector = []
                            score = self._cosine(query_vec, vector) if len(vector) == len(query_vec) else 0.0
                        except (TypeError, ValueError, OverflowError, struct.error, json.JSONDecodeError):
                            score = 0.0
                        offer(row, score)
            has_stale_embedding_rows = con.execute(
                "SELECT 1 FROM chunks WHERE tenant=? AND workspace=? AND COALESCE(embedding_space,'')<>? LIMIT 1",
                (scope_key, workspace, embedding_space),
            ).fetchone() is not None
            if embedding_space_resolved:
                try:
                    stored_embedding_space = self._stored_workspace_embedding_space(con, scope_key, workspace)
                    stored_embedding_space_read = True
                except sqlite3.Error:
                    pass

        if embedding_space_resolved:
            try:
                if not stored_embedding_space_read or stored_embedding_space != embedding_space:
                    with closing(self._connect()) as con:
                        con.execute("BEGIN IMMEDIATE")
                        if self._stored_workspace_embedding_space(con, scope_key, workspace) != embedding_space:
                            self._store_workspace_embedding_space(con, scope_key, workspace, embedding_space)
                        con.commit()
            except sqlite3.Error:
                fallbacks.append("embedding_space_metadata")

        if has_stale_embedding_rows:
            fallbacks.append("embedding_space_rebuild_pending")

        if rows_seen == 0:
            if uncertain_paths:
                return {
                    "success": True, "workspace": workspace, "results": [],
                    "degraded": True, "fallback": "source_read_uncertain",
                    "reason": "source files could not be read during indexing",
                }
            if has_stale_embedding_rows:
                return {
                    "success": True, "workspace": workspace, "results": [], "degraded": True,
                    "fallback": "embedding_space_mismatch",
                    "reason": "indexed vectors do not match the query embedding space",
                    "reindex_required": True,
                }
            return {"success": True, "workspace": workspace, "results": [], "warning": "workspace has no matching indexed chunks"}

        candidates = [
            entry[4]
            for entry in sorted(
                best,
                key=lambda item: (
                    -item[0], str(item[4]["path"]), int(item[4]["chunk_no"]), str(item[4]["content_hash"] or "")
                ),
            )
        ]

        # Hybrid search: combine vector candidates with FTS5 keyword hits via Reciprocal Rank Fusion (RRF)
        fts_candidates = visible(self._search_fts_candidates(
            query, tenant, workspace, 16, scope_path, embedding_space, uncertain_paths
        ))

        is_hybrid = bool(fts_candidates)
        if is_hybrid:
            k_rrf = 60.0
            combined: dict[tuple[str, int], dict[str, Any]] = {}
            for rank, c in enumerate(candidates):
                ckey = (c["path"], c["chunk_no"])
                item = dict(c)
                item["rrf_score"] = 1.0 / (k_rrf + rank + 1)
                combined[ckey] = item

            for rank, c in enumerate(fts_candidates):
                ckey = (c["path"], c["chunk_no"])
                rrf_delta = 1.0 / (k_rrf + rank + 1)
                if ckey in combined:
                    combined[ckey]["rrf_score"] += rrf_delta
                    combined[ckey]["fts_score"] = c.get("fts_score", 0.0)
                else:
                    item = dict(c)
                    item["rrf_score"] = rrf_delta
                    item["embedding_score"] = 0.0
                    combined[ckey] = item

            candidates = sorted(
                combined.values(),
                key=lambda item: (
                    -float(item.get("rrf_score", 0.0)), str(item.get("path", "")),
                    int(item.get("chunk_no", 0)), str(item.get("content_hash", "")),
                ),
            )
            candidates = candidates[:candidate_limit]

        # Hydrate text for winning candidates from DB
        needed_map: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for c in candidates:
            if "text" not in c or not c.get("text"):
                needed_map.setdefault((c["path"], c["chunk_no"]), []).append(c)
        if needed_map:
            with closing(self._connect()) as con:
                for (chunk_path, chunk_no), target_candidates in needed_map.items():
                    txt_row = con.execute(
                        "SELECT text FROM chunks WHERE tenant=? AND workspace=? AND path=? AND chunk_no=?",
                        (scope_key, workspace, chunk_path, chunk_no),
                    ).fetchone()
                    chunk_text = str(txt_row[0]) if txt_row else ""
                    for c in target_candidates:
                        c["text"] = chunk_text

        reranked = False
        reranker_failed = False
        heuristic_fallback = False
        if use_reranker and candidates:
            if self.config.get("features", {}).get("reranker", True) and hasattr(self, "reranker") and self.reranker:
                reranker_device = str(
                    getattr(self.reranker, "active_device", None)
                    or getattr(self.reranker, "device", None)
                    or ""
                ).strip().lower()
                if reranker_device and reranker_device not in {"unknown", "none", "auto"} and not reranker_device.startswith("cpu"):
                    try:
                        rr = self.reranker.rerank(
                            query,
                            [c["text"] for c in candidates],
                            top_k=top_k,
                            priority=priority,
                            allow_cpu_fallback=False,
                        )
                        if rr.get("success"):
                            ordered: list[dict[str, Any]] = []
                            for item in rr["results"]:
                                base = dict(candidates[item["index"]])
                                base["rerank_score"] = item["score"]
                                ordered.append(base)
                            candidates = ordered
                            reranked = True
                        else:
                            reranker_failed = True
                    except Exception:
                        reranker_failed = True

            if not reranked:
                q_terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 1]
                if q_terms:
                    for c in candidates:
                        h_score = float(c.get("rrf_score", c.get("embedding_score", 0.5)))
                        txt = str(c.get("text", "")).lower()
                        p_low = str(c.get("path", "")).lower()
                        if any(t in p_low for t in q_terms):
                            h_score *= 1.35
                        for t in q_terms:
                            if f"def {t}" in txt or f"class {t}" in txt or f"interface {t}" in txt:
                                h_score *= 1.5
                        if len(q_terms) >= 2 and all(t in txt for t in q_terms[:2]):
                            h_score *= 1.2
                        c["heuristic_rerank_score"] = round(h_score, 4)
                candidates = sorted(candidates, key=lambda x: x.get("heuristic_rerank_score", 0.0), reverse=True)
                heuristic_fallback = True

        if heuristic_fallback:
            fallbacks.append("heuristic_rerank")
        elif reranker_failed:
            fallbacks.append("reranker")

        graphrag_enriched = False
        try:
            state_dir = Path(self.config.get("server", {}).get("state_dir", "state")).resolve()
            state_db = state_dir / "agent_state.sqlite"
            if state_db.is_file():
                con_state = connect_sqlite(state_db)
                try:
                    cur_rel = con_state.cursor()
                    for c in candidates[:top_k]:
                        c_text = c.get("text", "")
                        words = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b", c_text[:1000]))
                        if not words:
                            continue
                        matched_rels: list[dict[str, Any]] = []
                        for w in list(words)[:15]:
                            rows_rel = cur_rel.execute(
                                "SELECT source_entity, relation, target_entity, weight FROM agent_entity_relations WHERE source_entity = ? OR target_entity = ? LIMIT 5",
                                (w, w),
                            ).fetchall()
                            for r_row in rows_rel:
                                matched_rels.append({
                                    "source": r_row[0], "relation": r_row[1], "target": r_row[2], "weight": float(r_row[3]),
                                })
                        if matched_rels:
                            c["graph_relations"] = matched_rels[:5]
                            graphrag_enriched = True
                finally:
                    con_state.close()
        except Exception:
            pass

        return {
            "success": True,
            "workspace": workspace,
            "reranked": reranked,
            "degraded": bool(fallbacks),
            "fallback": fallbacks[0] if fallbacks else None,
            "fallbacks": fallbacks,
            "reindex_required": has_stale_embedding_rows,
            "hybrid": is_hybrid,
            "graphrag_enriched": graphrag_enriched,
            "results": candidates[:top_k],
        }

    def list_workspaces(self, tenant: str) -> list[dict[str, Any]]:
        scope_key = self._scope_key(tenant)
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT workspace, COUNT(*), COUNT(DISTINCT path) FROM chunks WHERE tenant=? GROUP BY workspace ORDER BY workspace",
                (scope_key,),
            ).fetchall()
        return [{"workspace": r[0], "chunks": r[1], "files": r[2]} for r in rows]

    def docset_index(self, name: str, root: str, tenant: str = "docset") -> dict[str, Any]:
        """Index an offline library or API documentation directory under a named docset workspace."""
        clean_name = str(name or "").strip().lower().replace(" ", "_")
        if not clean_name:
            return {"success": False, "error": "docset name is required"}
        return self.index(root, tenant, workspace=f"docset:{clean_name}")

    def docset_search(self, name: str, query: str, tenant: str = "docset", top_k: int = 8, use_reranker: bool = True) -> dict[str, Any]:
        """Search an indexed offline library or API docset."""
        clean_name = str(name or "").strip().lower().replace(" ", "_")
        if not clean_name:
            return {"success": False, "error": "docset name is required"}
        return self.search(query, tenant, f"docset:{clean_name}", top_k=top_k, use_reranker=use_reranker)

    def ingest_document(
        self,
        workspace: str,
        content: str,
        title: str = "",
        metadata: dict[str, Any] | None = None,
        tenant: str = "default",
    ) -> dict[str, Any]:
        """Ingest raw document or specification content into a RAG workspace."""
        raw_text = str(content or "")
        rag_cfg = self.config.get("rag", {})
        max_bytes = max(0, int(rag_cfg.get("max_file_bytes", 2_000_000)))
        content_bytes = len(raw_text.encode("utf-8"))
        if content_bytes > max_bytes:
            return {
                "success": False,
                "error": "document content exceeds configured file size limit",
                "content_bytes": content_bytes,
                "max_file_bytes": max_bytes,
            }
        clean_text = raw_text.strip()
        if not clean_text:
            return {"success": False, "error": "content is required"}

        clean_ws = str(workspace or "default").strip()
        doc_metadata = metadata if isinstance(metadata, dict) else {}
        doc_title = str(title or "").strip() or str(doc_metadata.get("title") or "").strip() or f"doc_{_fragment_hash(clean_text)[:8]}"
        doc_path = f"doc:{doc_title}"
        scope_key = self._scope_key(tenant)

        index_parts = [f"Title: {doc_title}"]
        if doc_metadata:
            index_parts.append(f"Metadata: {json_dumps(doc_metadata, sort_keys=True, default=str)}")
        index_parts.append(f"Content:\n{clean_text}")
        indexed_bytes = sum(len(part.encode("utf-8")) for part in index_parts) + len(index_parts) - 1
        if indexed_bytes > max_bytes:
            return {
                "success": False,
                "error": "indexed document exceeds configured file size limit",
                "indexed_bytes": indexed_bytes,
                "max_file_bytes": max_bytes,
            }
        indexed_text = "\n".join(index_parts)

        raw_chunks = self._text_chunks(indexed_text, size=1000, overlap=100)
        if not raw_chunks:
            raw_chunks = [indexed_text[:1000]]

        records: list[dict[str, Any]] = []
        for i, ch_text in enumerate(raw_chunks):
            records.append({
                "chunk_no": i,
                "text": ch_text,
                "hash": _fragment_hash(ch_text),
                "embedding": None,
                "embedding_space": "",
            })

        if self.services is not None:
            for offset in range(0, len(records), _INDEX_EMBED_BATCH_SIZE):
                batch_records = records[offset:offset + _INDEX_EMBED_BATCH_SIZE]
                try:
                    vec_res = self.services.embed(
                        [record["text"] for record in batch_records],
                        tenant,
                        priority=2,
                        query=False,
                    )
                    if not isinstance(vec_res, dict) or not vec_res.get("success"):
                        break
                    vectors = vec_res.get("embeddings", [])
                    if len(vectors) > len(batch_records):
                        break
                    embedding_space = self._embedding_space_id(vec_res)
                    for record, vector in zip(batch_records, vectors):
                        embedding = _serialize_embedding(vector)
                        if embedding is not None:
                            record["embedding"] = embedding
                            record["embedding_space"] = embedding_space
                    if len(vectors) < len(batch_records):
                        break
                except Exception:
                    break

        for r in records:
            if r["embedding"] is None:
                r["embedding"] = ""

        def publish_document() -> None:
            with self._get_workspace_lock(clean_ws), closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                con.execute("DELETE FROM chunks WHERE tenant=? AND workspace=? AND path=?", (scope_key, clean_ws, doc_path))
                con.execute("DELETE FROM files WHERE tenant=? AND workspace=? AND path=?", (scope_key, clean_ws, doc_path))
                fts_exists = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'"
                ).fetchone()
                if fts_exists:
                    con.execute("DELETE FROM chunk_fts WHERE tenant=? AND workspace=? AND path=?", (scope_key, clean_ws, doc_path))

                now_ns = time.time_ns()
                con.execute(
                    "INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)",
                    (scope_key, clean_ws, doc_path, now_ns, len(indexed_text.encode("utf-8")), _fragment_hash(indexed_text)),
                )
                con.executemany(
                    "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?,?)",
                    [(scope_key, clean_ws, doc_path, r["chunk_no"], r["hash"], r["text"], r["embedding"], r["embedding_space"]) for r in records],
                )
                if fts_exists:
                    con.executemany(
                        "INSERT INTO chunk_fts(tenant,workspace,path,chunk_no,text) VALUES(?,?,?,?,?)",
                        [(scope_key, clean_ws, doc_path, r["chunk_no"], r["text"]) for r in records],
                    )
                con.commit()

        try:
            retry_busy(
                publish_document,
                retries=self._sqlite_write_retries,
                base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
            )
        except Exception as exc:
            return {
                "success": False,
                "workspace": clean_ws,
                "document_title": doc_title,
                "error": "ingest_publish_failed",
                "detail": str(exc),
                "retryable": is_busy_error(exc),
            }

        embedded_chunks = sum(bool(r["embedding_space"]) for r in records)
        embedded = embedded_chunks == len(records)
        return {
            "success": True,
            "workspace": clean_ws,
            "document_title": doc_title,
            "chunks_ingested": len(records),
            "embedded": embedded,
            "embedded_chunks": embedded_chunks,
            "embedding_status": "embedded" if embedded else "degraded",
            "degraded": not embedded,
        }

    def ingest_diagram(
        self,
        workspace: str,
        image_path: str,
        caption: str = "",
        metadata: dict[str, Any] | None = None,
        tenant: str = "default",
    ) -> dict[str, Any]:
        """Ingest architectural diagram, flowchart, or visual asset into RAG workspace."""
        p_img = Path(image_path).expanduser().resolve(strict=False)
        if not p_img.is_file():
            return {"success": False, "error": f"image file not found: {image_path}"}

        suffix = p_img.suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".svg", ".bmp"):
            return {"success": False, "error": f"unsupported diagram format: {suffix}"}

        clean_ws = str(workspace or "default").strip()
        doc_title = f"diagram_{p_img.stem}_{_fragment_hash(str(p_img))[:16]}"

        diagram_text = ""
        svg_text_nodes: list[str] = []
        if suffix == ".svg":
            try:
                rag_cfg = self.config.get("rag", {})
                max_bytes = max(0, int(rag_cfg.get("max_file_bytes", 2_000_000)))
                if int(p_img.stat().st_size) > max_bytes:
                    return {
                        "success": False,
                        "error": "diagram exceeds configured file size limit",
                        "diagram_indexed": False,
                    }
                with p_img.open("rb") as svg_file:
                    raw_bytes = svg_file.read(max_bytes + 1)
                if len(raw_bytes) > max_bytes:
                    return {
                        "success": False,
                        "error": "diagram exceeds configured file size limit",
                        "diagram_indexed": False,
                    }
                raw_svg = raw_bytes.decode("utf-8", errors="replace")
                texts = re.findall(r"<text[^>]*>(.*?)</text>", raw_svg, re.DOTALL | re.I)
                svg_text_nodes = [t.strip() for t in texts if t.strip()]
                diagram_text = f"SVG Diagram: {p_img.name}\nCaption: {caption}\nText nodes:\n" + "\n".join(svg_text_nodes)
            except Exception:
                return {
                    "success": False,
                    "error": "diagram could not be read",
                    "diagram_indexed": False,
                }
        else:
            file_size_kb = round(p_img.stat().st_size / 1024, 1)
            diagram_text = f"Architectural Diagram / Visual Asset: {p_img.name}\nFormat: {suffix.lstrip('.')}\nSize: {file_size_kb} KB\nCaption: {caption}\nFile path: {str(p_img)}"

        res = self.ingest_document(
            workspace=clean_ws,
            content=diagram_text,
            title=doc_title,
            metadata={"type": "diagram", "format": suffix, "image_path": str(p_img), **(metadata or {})},
            tenant=tenant,
        )
        if isinstance(res, dict):
            res["diagram_indexed"] = bool(res.get("success"))
            res["image_path"] = str(p_img)
            res["diagram_content_mode"] = "svg_text_nodes" if svg_text_nodes else "metadata_only"
            res["vision_or_ocr_used"] = False
        return res
