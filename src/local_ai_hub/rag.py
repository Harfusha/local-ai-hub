from __future__ import annotations

from .json_utils import dumps as json_dumps

import hashlib
import heapq
import json
import math
import os
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
from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error, retry_busy, quick_sanity_check
from .process_utils import canonical_root
from .project_policy_adapter import (
    custom_extension_kind,
    may_descend,
    path_allowed,
    phase_allowed,
    resolve_project_context,
)


import re
from functools import lru_cache


_MAX_RERANK_CANDIDATES = 512
_INDEX_EMBED_BATCH_SIZE = 64
_VECTOR_BATCH_MEMORY_BUDGET_BYTES = 16 * 1024 * 1024
_MAX_VECTOR_BATCH_SIZE = 8192


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
                state_dir / "cache.sqlite3", f"rag-search:{self.index_fingerprint[:16]}",
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
                    # RAG tables are disposable derived state. Rebuild the snapshot
                    # instead of mutating an incompatible legacy schema in place.
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
            fts_exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'"
            ).fetchone() is not None
            previous = con.execute("SELECT value FROM rag_meta WHERE key='index_fingerprint'").fetchone()
            current = self.index_fingerprint
            self.index_reset = legacy_schema_reset
            if previous is None:
                existing = int(con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
                self.index_reset = self.index_reset or existing > 0
                if existing:
                    con.execute("DELETE FROM chunks")
                    con.execute("DELETE FROM files")
                    if fts_exists:
                        con.execute("DELETE FROM chunk_fts")
            elif str(previous[0]) != current:
                self.index_reset = True
                con.execute("DELETE FROM chunks")
                con.execute("DELETE FROM files")
                if fts_exists:
                    con.execute("DELETE FROM chunk_fts")
            if self.index_reset:
                con.execute("DELETE FROM rag_meta WHERE key LIKE 'workspace_embedding_space:%'")
            con.execute("INSERT OR REPLACE INTO rag_meta(key,value) VALUES('index_fingerprint',?)", (current,))
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_workspace ON chunks(tenant, workspace)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_embedding_space ON chunks(tenant, workspace, embedding_space, path, chunk_no)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_content_hash ON chunks(content_hash)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_tenant_hash ON chunks(tenant, content_hash)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_files_workspace ON files(tenant, workspace)")
            con.commit()

    @staticmethod
    def workspace_id(root: str) -> str:
        resolved = canonical_root(root)
        digest = hashlib.sha1(resolved.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
        return f"{Path(resolved).name}-{digest}"

    def project_context(self, root: str | Path) -> Any | None:
        state_dir = self.config.get("server", {}).get("state_dir", "state")
        return resolve_project_context(root, state_dir)

    def _iter_files(
        self, root: Path, project_context: Any | None = None
    ) -> Iterable[Path]:
        cfg = self.config.get("rag", {})
        extensions = {x.lower() for x in cfg.get("extensions", [])}
        ignored = {str(name).lower() for name in cfg.get("ignore_dirs", [])}
        max_bytes = int(cfg.get("max_file_bytes", 2_000_000))
        settings = project_context.settings if project_context is not None else None
        if settings is not None and settings.max_file_size_bytes is not None:
            max_bytes = min(max_bytes, int(settings.max_file_size_bytes))
        pending = [Path(root)]
        while pending:
            current = pending.pop()
            if not may_descend(
                root, current, project_context, phase="rag",
                hard_denied=current != root and current.name.lower() in ignored,
            ):
                continue
            try:
                entries = sorted(os.scandir(current), key=lambda entry: entry.name)
            except OSError:
                continue
            child_dirs: list[Path] = []
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.lower() not in ignored:
                            child_dirs.append(Path(entry.path))
                        continue
                    # Never follow directory symlinks, matching os.walk's default,
                    # but preserve the historical behavior for symlinked files.
                    if entry.is_symlink() and entry.is_dir(follow_symlinks=True):
                        continue
                    path = Path(entry.path)
                    if extensions and path.suffix.lower() not in extensions:
                        kind = custom_extension_kind(project_context, path)
                        if kind != "text":
                            continue
                    size_bytes = int(entry.stat(follow_symlinks=True).st_size)
                    if size_bytes > max_bytes:
                        continue
                    allowed, kind = path_allowed(
                        root, path, project_context, phase="rag", size_bytes=size_bytes,
                    )
                    if allowed and kind != "binary":
                        yield path
                except OSError:
                    continue
            pending.extend(reversed(child_dirs))

    def _chunks(self, text: str, path: str = "") -> list[str]:
        """Split text into semantically meaningful chunks.

        For source code files, try AST-aware splitting that keeps classes and
        methods intact. Falls back to paragraph-aware overlap splitting when
        tree-sitter is unavailable or for unsupported formats.
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
    def _workspace_project_config_key(scope_key: str, workspace: str) -> str:
        return "workspace_project_config:" + stable_hash({"tenant": scope_key, "workspace": workspace})

    def _sync_workspace_project_policy_identity(
        self,
        root: str | Path,
        scope_key: str,
        workspace: str,
        project_context: Any | None,
    ) -> int:
        """Invalidate cached search identity and prune policy-rejected indexed files."""
        digest = getattr(project_context, "config_digest", None)
        if not isinstance(digest, str) or not digest:
            return 0
        key = self._workspace_project_config_key(scope_key, workspace)
        with closing(self._connect()) as con:
            previous = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()
            if previous is not None and str(previous[0]) == digest:
                return 0
            rows = con.execute(
                "SELECT path FROM files WHERE tenant=? AND workspace=?",
                (scope_key, workspace),
            ).fetchall()

        root_path = Path(root).resolve(strict=False)
        cfg = self.config.get("rag", {})
        extensions = {str(ext).lower() for ext in cfg.get("extensions", [])}
        ignored = {str(name).lower() for name in cfg.get("ignore_dirs", [])}
        max_bytes = int(cfg.get("max_file_bytes", 2_000_000))
        settings = project_context.settings
        if settings.max_file_size_bytes is not None:
            max_bytes = min(max_bytes, int(settings.max_file_size_bytes))
        rag_enabled = phase_allowed(project_context, "rag")
        rejected: list[str] = []
        for row in rows:
            rel = str(row[0]).replace("\\", "/")
            candidate = (root_path / rel).resolve(strict=False)
            try:
                candidate.relative_to(root_path)
                stat = candidate.stat()
                if not candidate.is_file():
                    raise OSError("indexed path is not a file")
            except (OSError, ValueError, RuntimeError):
                rejected.append(rel)
                continue
            kind = custom_extension_kind(project_context, candidate)
            if (
                not rag_enabled
                or any(part.lower() in ignored for part in Path(rel).parts[:-1])
                or (extensions and candidate.suffix.lower() not in extensions and kind != "text")
                or int(stat.st_size) > max_bytes
            ):
                rejected.append(rel)
                continue
            allowed, kind = path_allowed(
                root_path, candidate, project_context, phase="rag",
                size_bytes=int(stat.st_size),
            )
            if not allowed or kind == "binary":
                rejected.append(rel)

        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            current = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()
            if current is not None and str(current[0]) == digest:
                con.rollback()
                return 0
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
            con.execute("INSERT OR REPLACE INTO rag_meta(key,value) VALUES(?,?)", (key, digest))
            self._bump_workspace_index_generation(con, scope_key, workspace)
            con.commit()
        return len(set(rejected))

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

    def _embedding_space_id(self, result: dict[str, Any] | None = None) -> str:
        if isinstance(result, dict) and result.get("embedding_space_id"):
            return str(result["embedding_space_id"])
        service_space = getattr(self.services, "space_id", None)
        if service_space and not callable(service_space):
            return str(service_space)
        if isinstance(result, dict) and result.get("success"):
            models = self.config.get("models", {})
            backend = str(result.get("backend") or models.get("embedding_backend", "unknown"))
            model = str(result.get("model") or models.get("embedding", "unknown"))
            embeddings = result.get("embeddings")
            result_dimension = None
            if isinstance(embeddings, (list, tuple)) and embeddings:
                try:
                    result_dimension = len(embeddings[0])
                except TypeError:
                    result_dimension = None
            normalized = result.get("normalized", models.get("embedding_normalized"))
            if normalized is None and backend in {"sentence-transformers", "openvino"}:
                normalized = True
            elif normalized is None and backend == "ollama":
                normalized = False
            payload = {
                "backend": backend,
                "model": model,
                "digest": result.get("model_digest") or models.get("embedding_digest") or models.get("model_digest"),
                "revision": result.get("model_revision") or models.get("embedding_revision") or models.get("model_revision"),
                "device": result.get("device") or models.get("embedding_device"),
                "dimension": result_dimension if isinstance(result_dimension, int) and not isinstance(result_dimension, bool) else models.get("embedding_dimension"),
                "normalized": normalized,
            }
            return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        embedder = getattr(self.services, "embeddings", None)
        identity_factory = getattr(embedder, "embedding_space_id", None)
        if callable(identity_factory):
            return str(identity_factory())
        models = self.config.get("models", {})
        backend = str((result or {}).get("backend") or models.get("embedding_backend", "unknown"))
        model = str((result or {}).get("model") or models.get("embedding", "unknown"))
        result_dimension = (result or {}).get("embedding_dimension")
        if (not isinstance(result_dimension, int) or isinstance(result_dimension, bool)) and isinstance((result or {}).get("embeddings"), (list, tuple)):
            embeddings = (result or {}).get("embeddings")
            if embeddings:
                try:
                    result_dimension = len(embeddings[0])
                except TypeError:
                    result_dimension = None
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
            "dimension": result_dimension if isinstance(result_dimension, int) and not isinstance(result_dimension, bool) else models.get("embedding_dimension"),
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
            result = {"success": False, "error": str(exc), "retryable": True}
        finally:
            flight["result"] = result
            flight["event"].set()
            with self._index_flights_lock:
                self._index_flights.pop(flight_key, None)
        return result

    def _index_locked(
        self,
        root: str,
        tenant: str,
        workspace: str | None = None,
        *,
        _space_override: str | None = None,
        _identity_retry: bool = False,
    ) -> dict[str, Any]:
        root_path = Path(root).resolve()
        if not root_path.exists() or not root_path.is_dir():
            return {"success": False, "error": f"root directory does not exist: {root_path}"}
        workspace = workspace or self.workspace_id(str(root_path))
        project_context = self.project_context(root_path)
        if not phase_allowed(project_context, "rag"):
            removed = self.prune_missing(root, tenant, workspace, [])
            return {"success": True, "workspace": workspace, "skipped": True, "removed_paths": removed}
        scope_key = self._scope_key(tenant)
        self._sync_workspace_project_policy_identity(
            root_path, scope_key, workspace, project_context
        )
        configured_space = _space_override or self._embedding_space_id()
        identity_resolved = _space_override is not None or self._embedding_space_is_resolved()

        with closing(self._connect()) as con:
            stored_space = self._stored_workspace_embedding_space(con, scope_key, workspace)
            old_files_rows = con.execute(
                "SELECT path,mtime_ns,size,content_hash FROM files WHERE tenant=? AND workspace=?",
                (scope_key, workspace),
            ).fetchall()
            old_chunk_rows = con.execute(
                "SELECT path,chunk_no,content_hash,embedding,embedding_space FROM chunks WHERE tenant=? AND workspace=?",
                (scope_key, workspace),
            ).fetchall()
        old_space_counts: dict[str, int] = {}
        for row in old_chunk_rows:
            old_space_counts[str(row[4] or "")] = old_space_counts.get(str(row[4] or ""), 0) + 1
        if stored_space is None and old_space_counts:
            stored_space = sorted(old_space_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        embedding_space = configured_space if identity_resolved else (stored_space or configured_space)
        old_files = {r[0]: {"mtime_ns": int(r[1]), "size": int(r[2]), "content_hash": r[3]} for r in old_files_rows}
        old_chunks = {
            (r[0], int(r[1]), r[2]): r[3]
            for r in old_chunk_rows if str(r[4] or "") == embedding_space
        }
        stale_embedding_paths = (
            {str(r[0]) for r in old_chunk_rows if str(r[4] or "") != embedding_space}
            if stored_space is not None or identity_resolved else set()
        )

        current_meta: dict[str, tuple[Path, int, int]] = {}
        metadata_scanned = 0
        for path in self._iter_files(root_path, project_context):
            metadata_scanned += 1
            try:
                stat = path.stat()
                rel = str(path.relative_to(root_path)).replace("\\", "/")
                current_meta[rel] = (path, int(stat.st_mtime_ns), int(stat.st_size))
            except OSError:
                continue

        current_paths = set(current_meta)
        old_paths = set(old_files)
        deleted_paths = sorted(old_paths - current_paths)
        unchanged_paths: list[str] = []
        changed_paths: list[str] = []
        for rel, (_path, mtime_ns, size) in current_meta.items():
            old = old_files.get(rel)
            if old and old["mtime_ns"] == mtime_ns and old["size"] == size and rel not in stale_embedding_paths:
                unchanged_paths.append(rel)
            else:
                changed_paths.append(rel)

        changed_records: list[dict[str, Any]] = []
        file_rows: list[tuple[str, int, int, str]] = []
        skipped = 0
        read_files = 0
        reused_chunks = 0
        changed_indices: list[int] = []
        rag_cfg = self.config.get("rag", {})
        dedup_near_duplicates = bool(rag_cfg.get("dedup_near_duplicates", True))
        max_hamming = int(rag_cfg.get("near_duplicate_max_hamming", 4))
        near_duplicates_skipped = 0

        for rel in changed_paths:
            path, mtime_ns, size = current_meta[rel]
            try:
                raw = path.read_bytes()
                read_files += 1
                text = _canonical_fragment_text(raw.decode("utf-8", errors="replace"))
                file_hash = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
            except Exception:
                skipped += 1
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
                        f"SELECT content_hash, embedding FROM chunks WHERE tenant=? AND embedding_space=? AND content_hash IN ({placeholders})",
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
            batch_embedding_space = self._embedding_space_id(vectors_result)
            if observed_embedding_space is not None and observed_embedding_space != batch_embedding_space:
                return {"success": False, "error": "embedding identity changed during atomic index build", "retryable": True}
            observed_embedding_space = batch_embedding_space
            if batch_embedding_space != embedding_space:
                if _identity_retry:
                    return {"success": False, "error": "embedding identity changed during atomic index retry", "retryable": True}
                if old_chunk_rows or reused_chunks:
                    return self._index_locked(
                        str(root_path), tenant, workspace,
                        _space_override=batch_embedding_space, _identity_retry=True,
                    )
                embedding_space = batch_embedding_space
            for idx, vector in zip(batch_indices, vectors):
                embedding = _serialize_embedding(vector)
                if embedding is None:
                    return {"success": False, "error": "embedding backend returned an invalid vector"}
                for duplicate_idx in pending_by_hash[str(changed_records[idx]["hash"])]:
                    changed_records[duplicate_idx]["embedding"] = embedding
                    changed_records[duplicate_idx]["embedding_space"] = batch_embedding_space

        # One transaction publishes all changed/deleted file state atomically.
        # The embed phase is intentionally outside this retry: a transient writer
        # must not cause expensive model work to run again.
        def publish() -> None:
            with self._get_workspace_lock(workspace), closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                successfully_read_paths = {str(row[0]) for row in file_rows}
                publish_paths = deleted_paths + [rel for rel in changed_paths if rel in successfully_read_paths]
                del_paths = [(scope_key, workspace, rel) for rel in publish_paths]
                fts_exists = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'"
                ).fetchone()
                if del_paths:
                    con.executemany("DELETE FROM chunks WHERE tenant=? AND workspace=? AND path=?", del_paths)
                    con.executemany("DELETE FROM files WHERE tenant=? AND workspace=? AND path=?", del_paths)
                    if fts_exists:
                        con.executemany("DELETE FROM chunk_fts WHERE tenant=? AND workspace=? AND path=?", del_paths)
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
                self._store_workspace_embedding_space(con, scope_key, workspace, embedding_space)
                if publish_paths:
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
            "embedding_space_id": embedding_space,
            "embedding_space_resolved": bool(identity_resolved or observed_embedding_space or stored_space),
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
            "near_duplicates_skipped": near_duplicates_skipped,
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
            existing = {str(r[0]) for r in con.execute(
                "SELECT path FROM files WHERE tenant=? AND workspace=?", (scope_key, workspace)
            ).fetchall()}
            deleted = existing - current
            for rel in deleted:
                con.execute("DELETE FROM chunks WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                con.execute("DELETE FROM files WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                try:
                    con.execute("DELETE FROM chunk_fts WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                except Exception:
                    pass
            if deleted:
                self._bump_workspace_index_generation(con, scope_key, workspace)
            con.commit()
        return policy_removed + len(deleted)

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
                removed += int(row is not None)
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
        *,
        _space_override: str | None = None,
        _identity_retry: bool = False,
    ) -> dict[str, Any]:
        """Index only explicitly dirty paths supplied by Local AI preprocessing.

        This avoids repeatedly walking a cold repository for each micro-step.
        """
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            return {"success": False, "error": f"root directory does not exist: {root_path}"}
        project_context = self.project_context(root_path)
        if not phase_allowed(project_context, "rag"):
            removed = self.prune_missing(root, tenant, workspace, [])
            return {
                "success": True, "workspace": workspace, "skipped": True,
                "removed_paths": removed, "processed_paths": [],
            }
        scope_key = self._scope_key(tenant)
        configured_space = _space_override or self._embedding_space_id()
        identity_resolved = _space_override is not None or self._embedding_space_is_resolved()
        processed_paths: list[str] = []
        embedded_chunks = 0
        reused_chunks = 0
        observed_embedding_space: str | None = None
        with self._get_workspace_lock(workspace):
            self._sync_workspace_project_policy_identity(
                root_path, scope_key, workspace, project_context
            )
            with closing(self._connect()) as con:
                stored_space = self._stored_workspace_embedding_space(con, scope_key, workspace)
                legacy_rows = (
                    con.execute(
                        "SELECT embedding,embedding_space FROM chunks WHERE tenant=? AND workspace=?",
                        (scope_key, workspace),
                    ).fetchall()
                    if stored_space is None
                    else []
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
                    "success": False,
                    "workspace": workspace,
                    "error": "embedding_space_rebuild_required",
                    "rebuild_required": True,
                    "retryable": False,
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
                        "success": False,
                        "workspace": workspace,
                        "error": "embedding_space_recovery_failed",
                        "retryable": is_busy_error(exc),
                    }
                if recovery_conflict["value"]:
                    return {
                        "success": False,
                        "workspace": workspace,
                        "error": "embedding_space_rebuild_required",
                        "rebuild_required": True,
                        "retryable": False,
                    }
                stored_space = inferred_space

            embedding_space = configured_space if identity_resolved else (stored_space or configured_space)
            # 1. Read files and chunk
            file_data: list[dict[str, Any]] = []
            policy_deleted: set[str] = set()
            for rel in paths:
                if callable(should_yield) and should_yield():
                    return {
                        "success": True, "workspace": workspace, "preempted": True,
                        "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
                        "reused_chunks": reused_chunks,
                    }
                rel = str(rel).replace("\\", "/")
                path = (root_path / rel).resolve(strict=False)
                try:
                    path.relative_to(root_path)
                except ValueError:
                    continue
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                    cfg = self.config.get("rag", {})
                    max_bytes = int(cfg.get("max_file_bytes", 2_000_000))
                    settings = project_context.settings if project_context is not None else None
                    if settings is not None and settings.max_file_size_bytes is not None:
                        max_bytes = min(max_bytes, int(settings.max_file_size_bytes))
                    if int(stat.st_size) > max_bytes:
                        policy_deleted.add(rel)
                        continue
                    extensions = {str(ext).lower() for ext in cfg.get("extensions", [])}
                    kind = custom_extension_kind(project_context, path)
                    if extensions and path.suffix.lower() not in extensions and kind != "text":
                        policy_deleted.add(rel)
                        continue
                    allowed, kind = path_allowed(
                        root_path, path, project_context, phase="rag",
                        size_bytes=int(stat.st_size),
                    )
                    if not allowed or kind == "binary":
                        policy_deleted.add(rel)
                        continue
                    override = (content_overrides or {}).get(rel)
                    if override is None:
                        raw = path.read_bytes()
                        text = _canonical_fragment_text(raw.decode("utf-8", errors="replace"))
                        file_hash = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
                    else:
                        text = _canonical_fragment_text(str(override))
                        file_hash = hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()
                    chunks = list(self._chunks(text, path=rel))
                    file_data.append({"rel": rel, "stat": stat, "file_hash": file_hash, "chunks": chunks})
                except Exception:
                    continue

            deleted_unique = sorted(
                {str(p).replace("\\", "/") for p in (deleted_paths or []) if str(p).strip()}
                | policy_deleted
            )
            if not file_data and not deleted_unique:
                return {
                    "success": True, "workspace": workspace, "preempted": False,
                    "processed_paths": [], "embedded_chunks": 0, "reused_chunks": 0,
                    "embedding_space_id": stored_space or (configured_space if identity_resolved else None),
                    "embedding_space_resolved": bool(stored_space or identity_resolved),
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
                        if str(r[4] or "") == embedding_space:
                            old_chunks[(str(r[0]), int(r[1]), str(r[2]))] = r[3]

            # 3. Build records and identify missing embeddings
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
                        missing_pointers.append((f_idx, len(records) - 1))
                    else:
                        reused_chunks += 1
                item["records"] = records

            # 4. Cross-workspace / cross-worktree instant chunk embedding reuse
            if missing_pointers:
                missing_hashes = [file_data[f_idx]["records"][rec_idx]["hash"] for f_idx, rec_idx in missing_pointers]
                global_chunks: dict[str, Any] = {}
                with closing(self._connect()) as con:
                    for i in range(0, len(missing_hashes), 500):
                        batch_h = missing_hashes[i:i + 500]
                        placeholders = ",".join("?" for _ in batch_h)
                        rows = con.execute(
                            f"SELECT content_hash, embedding FROM chunks WHERE tenant=? AND embedding_space=? AND content_hash IN ({placeholders})",
                            (scope_key, embedding_space, *batch_h),
                        ).fetchall()
                        for r in rows:
                            if r[0] and r[1] and str(r[0]) not in global_chunks:
                                global_chunks[str(r[0])] = r[1]

                if global_chunks:
                    still_missing_pointers: list[tuple[int, int]] = []
                    for f_idx, rec_idx in missing_pointers:
                        chash = file_data[f_idx]["records"][rec_idx]["hash"]
                        if chash in global_chunks:
                            file_data[f_idx]["records"][rec_idx]["embedding"] = global_chunks[chash]
                            file_data[f_idx]["records"][rec_idx]["embedding_space"] = embedding_space
                            reused_chunks += 1
                        else:
                            still_missing_pointers.append((f_idx, rec_idx))
                    missing_pointers = still_missing_pointers

            # 5. Embed bounded batches before the single atomic publish.
            if missing_pointers:
                if callable(should_yield) and should_yield():
                    return {
                        "success": True, "workspace": workspace, "preempted": True,
                        "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
                        "reused_chunks": reused_chunks,
                    }
                for offset in range(0, len(missing_pointers), _INDEX_EMBED_BATCH_SIZE):
                    if offset and callable(should_yield) and should_yield():
                        return {
                            "success": True, "workspace": workspace, "preempted": True,
                            "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
                            "reused_chunks": reused_chunks,
                        }
                    batch_pointers = missing_pointers[offset:offset + _INDEX_EMBED_BATCH_SIZE]
                    batch_texts = [str(file_data[f_idx]["records"][rec_idx]["text"]) for f_idx, rec_idx in batch_pointers]
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
                    batch_embedding_space = self._embedding_space_id(vectors_result)
                    if observed_embedding_space is not None and observed_embedding_space != batch_embedding_space:
                        return {"success": False, "error": "embedding identity changed during RAG path step", "retryable": True}
                    observed_embedding_space = batch_embedding_space
                    if batch_embedding_space != embedding_space:
                        if _identity_retry and reused_chunks:
                            return {"success": False, "error": "embedding identity changed during RAG path retry", "retryable": True}
                        if reused_chunks:
                            return self.index_paths_step(
                                str(root_path), tenant, workspace, paths,
                                should_yield=should_yield, content_overrides=content_overrides,
                                deleted_paths=deleted_paths, _space_override=batch_embedding_space,
                                _identity_retry=True,
                            )
                        embedding_space = batch_embedding_space
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

            # 5. Bulk SQLite transaction. Embedding is complete before this
            # atomic publish; busy retries replay only the bounded DB phase.
            chunks_to_insert: list[tuple[Any, ...]] = []
            files_to_insert: list[tuple[Any, ...]] = []
            for item in file_data:
                rel = item["rel"]
                stat = item["stat"]
                for r in item["records"]:
                    chunks_to_insert.append((scope_key, workspace, rel, r["chunk_no"], r["hash"], r["text"], r["embedding"], r["embedding_space"]))
                files_to_insert.append((scope_key, workspace, rel, int(stat.st_mtime_ns), int(stat.st_size), item["file_hash"]))
                processed_paths.append(rel)

            target_embedding_space = observed_embedding_space or (
                embedding_space if identity_resolved or stored_space else None
            )

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
                    if target_embedding_space:
                        self._store_workspace_embedding_space(con, scope_key, workspace, target_embedding_space)
                    if all_rels:
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
                    "success": False,
                    "workspace": workspace,
                    "error": "publish_failed",
                    "retryable": is_busy_error(exc),
                }

        return {
            "success": True, "workspace": workspace, "preempted": False,
            "embedding_space_id": target_embedding_space,
            "embedding_space_resolved": bool(identity_resolved or observed_embedding_space or stored_space),
            "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
            "reused_chunks": reused_chunks, "deleted_paths": deleted_unique,
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
        workspace = workspace or self.workspace_id(str(root_path))
        project_context = self.project_context(root_path)
        if not phase_allowed(project_context, "rag"):
            removed = self.prune_missing(root, tenant, workspace, [])
            return {
                "success": True, "workspace": workspace, "skipped": True,
                "removed_paths": removed, "processed_files": 0, "done": True,
            }
        scope_key = self._scope_key(tenant)
        with self._get_workspace_lock(workspace):
            self._sync_workspace_project_policy_identity(
                root_path, scope_key, workspace, project_context
            )
            configured_space = self._embedding_space_id()
            identity_resolved = self._embedding_space_is_resolved()
            if callable(should_yield) and should_yield():
                return {"success": True, "workspace": workspace, "preempted": True, "done": False, "processed_files": 0}

            with closing(self._connect()) as con:
                stored_space = self._stored_workspace_embedding_space(con, scope_key, workspace)
                old_rows = con.execute(
                    "SELECT path,mtime_ns,size,content_hash FROM files WHERE tenant=? AND workspace=?",
                    (scope_key, workspace),
                ).fetchall()
                old_chunk_rows = con.execute(
                    "SELECT path,chunk_no,content_hash,embedding,embedding_space FROM chunks WHERE tenant=? AND workspace=?",
                    (scope_key, workspace),
                ).fetchall()
            if stored_space is None and old_chunk_rows:
                space_counts: dict[str, int] = {}
                for row in old_chunk_rows:
                    space_counts[str(row[4] or "")] = space_counts.get(str(row[4] or ""), 0) + 1
                stored_space = sorted(space_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
            embedding_space = configured_space if identity_resolved else (stored_space or configured_space)
            old_files = {r[0]: {"mtime_ns": int(r[1]), "size": int(r[2]), "content_hash": r[3]} for r in old_rows}
            old_chunks = {
                (r[0], int(r[1]), r[2]): r[3]
                for r in old_chunk_rows if str(r[4] or "") == embedding_space
            }
            stale_embedding_paths = (
                {str(r[0]) for r in old_chunk_rows if str(r[4] or "") != embedding_space}
                if stored_space is not None or identity_resolved else set()
            )

            current_meta: dict[str, tuple[Path, int, int]] = {}
            for path in self._iter_files(root_path, project_context):
                try:
                    st = path.stat()
                    rel = str(path.relative_to(root_path)).replace("\\", "/")
                    current_meta[rel] = (path, int(st.st_mtime_ns), int(st.st_size))
                except OSError:
                    continue
            deleted = sorted(set(old_files) - set(current_meta))
            explicit_dirty_paths = {
                str(path).replace("\\", "/")
                for path in (dirty_paths or [])
                if str(path).strip()
            } & set(current_meta)
            changed_all = [
                rel for rel, (_p, mt, sz) in current_meta.items()
                if (
                    rel not in old_files
                    or old_files[rel]["mtime_ns"] != mt
                    or old_files[rel]["size"] != sz
                    or rel in stale_embedding_paths
                    or rel in explicit_dirty_paths
                )
            ]
            changed_all.sort(key=lambda rel: (rel not in explicit_dirty_paths, rel))
            selected = changed_all[: max(1, int(max_files))]

            pending = changed_all + deleted
            selected = pending[: max(1, int(max_files))]
            selected_changed = [rel for rel in selected if rel in current_meta]
            selected_deleted = [rel for rel in selected if rel in deleted]
            staged = self.index_paths_step(
                str(root_path), tenant, workspace, selected_changed,
                should_yield=should_yield, deleted_paths=selected_deleted,
                _space_override=embedding_space if identity_resolved or stored_space else None,
            )
            if not staged.get("success"):
                return staged
            processed_paths = {str(path).replace("\\", "/") for path in staged.get("processed_paths", [])}
            published_deletions = {str(path).replace("\\", "/") for path in staged.get("deleted_paths", [])}
            completed_paths = processed_paths | published_deletions
            target_space = staged.get("embedding_space_id") or embedding_space
            target_known = bool(staged.get("embedding_space_resolved") or identity_resolved or stored_space)
            remaining_paths = {path for path in pending if path not in completed_paths}
            if target_known and target_space:
                with closing(self._connect()) as con:
                    remaining_paths.update(
                        str(row[0])
                        for row in con.execute(
                            "SELECT DISTINCT path FROM chunks WHERE tenant=? AND workspace=? AND embedding_space<>?",
                            (scope_key, workspace, target_space),
                        ).fetchall()
                    )
            return {
                "success": True, "workspace": workspace,
                "embedding_space_id": target_space,
                "embedding_space_resolved": target_known,
                "preempted": bool(staged.get("preempted", False)),
                "done": not remaining_paths and not staged.get("preempted", False),
                "processed_files": len(completed_paths),
                "remaining_changed_files": len(remaining_paths),
                "deleted_files": len(published_deletions),
                "embedded_chunks": staged.get("embedded_chunks", 0),
                "reused_chunks": staged.get("reused_chunks", 0),
            }

            processed = 0
            embedded_chunks = 0
            reused_chunks = 0
            pending_writes: list[tuple[str, int, int, str, list[dict[str, Any]]]] = []
            for rel in selected:
                if callable(should_yield) and should_yield():
                    return {
                        "success": True, "workspace": workspace, "preempted": True, "done": False,
                        "processed_files": processed, "remaining_changed_files": max(0, len(changed_all) - processed),
                        "deleted_files": len(deleted), "embedded_chunks": embedded_chunks, "reused_chunks": reused_chunks,
                    }
                path, mtime_ns, size = current_meta[rel]
                try:
                    raw = path.read_bytes()
                    text = _canonical_fragment_text(raw.decode("utf-8", errors="replace"))
                    file_hash = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
                except Exception:
                    continue
                records: list[dict[str, Any]] = []
                missing_idx: list[int] = []
                missing_texts: list[str] = []
                for chunk_no, chunk in enumerate(self._chunks(text, path=rel)):
                    chash = _fragment_hash(chunk)
                    embedding = old_chunks.get((rel, chunk_no, chash))
                    rec = {
                        "chunk_no": chunk_no, "text": chunk, "hash": chash, "embedding": embedding,
                        "embedding_space": embedding_space if embedding is not None else "",
                    }
                    records.append(rec)
                    if embedding is None:
                        missing_idx.append(len(records) - 1)
                        missing_texts.append(chunk)
                    else:
                        reused_chunks += 1
                if missing_texts:
                    # Cross-workspace chunk reuse check
                    missing_hashes = [records[idx]["hash"] for idx in missing_idx]
                    global_chunks: dict[str, Any] = {}
                    with closing(self._connect()) as con:
                        for i in range(0, len(missing_hashes), 500):
                            batch_h = missing_hashes[i:i + 500]
                            placeholders = ",".join("?" for _ in batch_h)
                            rows = con.execute(
                                f"SELECT content_hash, embedding FROM chunks WHERE tenant=? AND embedding_space=? AND content_hash IN ({placeholders})",
                                (scope_key, embedding_space, *batch_h),
                            ).fetchall()
                            for r in rows:
                                if r[0] and r[1] and str(r[0]) not in global_chunks:
                                    global_chunks[str(r[0])] = r[1]

                    if global_chunks:
                        still_idx: list[int] = []
                        still_texts: list[str] = []
                        for idx, text in zip(missing_idx, missing_texts):
                            chash = records[idx]["hash"]
                            if chash in global_chunks:
                                records[idx]["embedding"] = global_chunks[chash]
                                records[idx]["embedding_space"] = embedding_space
                                reused_chunks += 1
                            else:
                                still_idx.append(idx)
                                still_texts.append(text)
                        missing_idx = still_idx
                        missing_texts = still_texts

                if missing_texts:
                    if callable(should_yield) and should_yield():
                        return {
                            "success": True, "workspace": workspace, "preempted": True, "done": False,
                            "processed_files": processed, "remaining_changed_files": len(changed_all) - processed,
                            "deleted_files": len(deleted), "embedded_chunks": embedded_chunks, "reused_chunks": reused_chunks,
                        }
                    try:
                        vectors_result = self.services.embed(missing_texts, tenant, priority=0, query=False, background=True)
                    except (TimeoutError, QueueFullError) as exc:
                        return {
                            "success": True, "workspace": workspace, "preempted": True, "done": False,
                            "processed_files": processed, "remaining_changed_files": len(changed_all) - processed,
                            "deleted_files": len(deleted), "embedded_chunks": embedded_chunks, "reused_chunks": reused_chunks,
                            "note": f"embedder busy or timed out: {exc}",
                        }
                    if not vectors_result.get("success"):
                        return vectors_result
                    vectors = vectors_result.get("embeddings", [])
                    if len(vectors) != len(missing_idx):
                        return {"success": False, "error": "embedding count mismatch during background RAG step"}
                    embedding_space = self._embedding_space_id(vectors_result)
                    for idx, vector in zip(missing_idx, vectors):
                        embedding = _serialize_embedding(vector)
                        if embedding is None:
                            return {"success": False, "error": "embedding backend returned an invalid vector"}
                        records[idx]["embedding"] = embedding
                        records[idx]["embedding_space"] = embedding_space
                    embedded_chunks += len(missing_idx)

                if callable(should_yield) and should_yield():
                    return {
                        "success": True, "workspace": workspace, "preempted": True, "done": False,
                        "processed_files": processed, "remaining_changed_files": len(changed_all) - processed,
                        "deleted_files": len(deleted), "embedded_chunks": embedded_chunks, "reused_chunks": reused_chunks,
                    }
                pending_writes.append((rel, mtime_ns, size, file_hash, records))
                processed += 1

            remaining = max(0, len(changed_all) - processed)
            if callable(should_yield) and should_yield():
                return {
                    "success": True, "workspace": workspace, "preempted": True, "done": False,
                    "processed_files": 0, "remaining_changed_files": len(changed_all),
                    "deleted_files": len(deleted), "embedded_chunks": embedded_chunks, "reused_chunks": reused_chunks,
                }

            # Publish deletions and completed files as one snapshot. A preemption
            # above leaves the previous workspace state intact.
            with self._get_workspace_lock(workspace), closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                replace_paths = [*deleted, *(item[0] for item in pending_writes)]
                for rel in replace_paths:
                    con.execute("DELETE FROM chunks WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                    con.execute("DELETE FROM files WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                    try:
                        con.execute("DELETE FROM chunk_fts WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                    except Exception:
                        pass
                for rel, mtime_ns, size, file_hash, records in pending_writes:
                    con.executemany(
                        "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?,?)",
                        [(scope_key, workspace, rel, r["chunk_no"], r["hash"], r["text"], r["embedding"], r["embedding_space"]) for r in records],
                    )
                    try:
                        con.executemany(
                            "INSERT INTO chunk_fts(tenant,workspace,path,chunk_no,text) VALUES(?,?,?,?,?)",
                            [(scope_key, workspace, rel, r["chunk_no"], r["text"]) for r in records],
                        )
                    except Exception:
                        pass
                    con.execute(
                        "INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)",
                        (scope_key, workspace, rel, mtime_ns, size, file_hash),
                    )
                con.commit()
            return {
                "success": True, "workspace": workspace, "preempted": False, "done": remaining == 0,
                "processed_files": processed, "remaining_changed_files": remaining,
                "deleted_files": len(deleted), "embedded_chunks": embedded_chunks, "reused_chunks": reused_chunks,
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
            self._rev_cache: dict[tuple[str, str], tuple[float, str]] = {}
            self._rev_lock = threading.Lock()
        with self._rev_lock:
            cached = self._rev_cache.get((scope_key, workspace))
            if cached and now - cached[0] < 3.0:
                return cached[1]
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT path,content_hash,mtime_ns,size FROM files WHERE tenant=? AND workspace=? ORDER BY path",
                (scope_key, workspace),
            ).fetchall()
        rev = stable_hash({"index": self.index_fingerprint, "files": rows})
        with self._rev_lock:
            if len(self._rev_cache) > 256:
                oldest_keys = sorted(self._rev_cache.keys(), key=lambda k: self._rev_cache[k][0])[:128]
                for k in oldest_keys:
                    self._rev_cache.pop(k, None)
            self._rev_cache[(scope_key, workspace)] = (now, rev)
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
        clean_query = normalize_query(query)
        revision = self.revision(tenant, workspace)
        scope_key = self._scope_key(tenant)
        cache_identity_known = self._embedding_space_cache_identity_known()
        query_space = self._embedding_space_id()
        with closing(self._connect()) as con:
            stored_space = self._stored_workspace_embedding_space(con, scope_key, workspace)
            generation = self._workspace_index_generation(con, scope_key, workspace)
        cache_target_space = query_space if cache_identity_known else stored_space
        key = stable_hash({
            "workspace": workspace, "revision": revision, "query": clean_query,
            "top_k": top_k, "reranker": use_reranker, "scope_path": scope_path,
            "embedding_space": cache_target_space if cache_identity_known else None,
            "index_generation": generation,
        })
        if cache_identity_known:
            raw, hit, coalesced = self.search_flight.get_or_compute(
                key,
                lambda: self._search_uncached(clean_query, tenant, workspace, top_k, use_reranker, priority, scope_path),
            )
            with closing(self._connect()) as con:
                latest_generation = self._workspace_index_generation(con, scope_key, workspace)
            if latest_generation != generation:
                raw = self._search_uncached(
                    clean_query, tenant, workspace, top_k, use_reranker, priority, scope_path
                )
                hit, coalesced = False, False
        else:
            raw = self._search_uncached(clean_query, tenant, workspace, top_k, use_reranker, priority, scope_path)
            hit, coalesced = False, False
        result = dict(raw) if isinstance(raw, dict) else {"success": False, "error": "search failed"}
        result["search_cache"] = {"hit": hit, "coalesced": coalesced, "revision": revision}
        return self._postprocess_search_payload(result, top_k) if isinstance(result, dict) else result

    def _search_fts_candidates(self, query: str, tenant: str, workspace: str, limit: int = 16, scope_path: str | None = None) -> list[dict[str, Any]]:
        scope_key = self._scope_key(tenant)
        try:
            tokens = [re.sub(r"[^\w_]", "", t) for t in query.split()]
            tokens = [t for t in tokens if len(t) > 1]
            if not tokens:
                return []
            fts_expr = " OR ".join(f'"{t}"' for t in tokens[:8])
            with closing(self._connect()) as con:
                if scope_path:
                    norm_scope = scope_path.replace("\\", "/").rstrip("/")
                    fts_rows = con.execute(
                        """SELECT c.path, c.chunk_no, c.text, c.content_hash, bm25(chunk_fts)
                           FROM chunk_fts
                           JOIN chunks c ON c.tenant=chunk_fts.tenant AND c.workspace=chunk_fts.workspace AND c.path=chunk_fts.path AND c.chunk_no=chunk_fts.chunk_no
                           WHERE chunk_fts.tenant=? AND chunk_fts.workspace=? AND (chunk_fts.path=? OR chunk_fts.path LIKE ? || '/%') AND chunk_fts MATCH ?
                           ORDER BY bm25(chunk_fts) LIMIT ?""",
                        (scope_key, workspace, norm_scope, norm_scope, fts_expr, limit),
                    ).fetchall()
                else:
                    fts_rows = con.execute(
                        """SELECT c.path, c.chunk_no, c.text, c.content_hash, bm25(chunk_fts)
                           FROM chunk_fts
                           JOIN chunks c ON c.tenant=chunk_fts.tenant AND c.workspace=chunk_fts.workspace AND c.path=chunk_fts.path AND c.chunk_no=chunk_fts.chunk_no
                           WHERE chunk_fts.tenant=? AND chunk_fts.workspace=? AND chunk_fts MATCH ?
                           ORDER BY bm25(chunk_fts) LIMIT ?""",
                        (scope_key, workspace, fts_expr, limit),
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

    def _search_token_overlap(self, query: str, tenant: str, workspace: str, limit: int = 16, scope_path: str | None = None) -> list[dict[str, Any]]:
        scope_key = self._scope_key(tenant)
        terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 1]
        if not terms:
            return []
        with closing(self._connect()) as con:
            if scope_path:
                norm_scope = scope_path.replace("\\", "/").rstrip("/")
                rows = con.execute(
                    "SELECT path, chunk_no, text, content_hash FROM chunks WHERE tenant=? AND workspace=? AND (path=? OR path LIKE ? || '/%')",
                    (scope_key, workspace, norm_scope, norm_scope),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT path, chunk_no, text, content_hash FROM chunks WHERE tenant=? AND workspace=?",
                    (scope_key, workspace),
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

    def _search_uncached(self, query: str, tenant: str, workspace: str, top_k: int = 8, use_reranker: bool = True, priority: int = 3, scope_path: str | None = None) -> dict[str, Any]:
        scope_key = self._scope_key(tenant)
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
            candidates = self._search_fts_candidates(query, tenant, workspace, max(16, top_k * 2), scope_path)
            if not candidates:
                candidates = self._search_token_overlap(query, tenant, workspace, max(16, top_k * 2), scope_path)
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
                "fallback": "bm25_fts",
                "reason": str(query_result.get("error", "embedder_unavailable")),
            }
        query_vec = query_result["embeddings"][0]
        embedding_space = self._embedding_space_id(query_result)
        fallbacks: list[str] = []
        if query_result.get("degraded"):
            fallbacks.append(str(query_result.get("fallback") or "embedding_backend"))

        rag_cfg = self.config.get("rag", {})
        candidate_limit = min(_MAX_RERANK_CANDIDATES, max(16, int(rag_cfg.get("rerank_candidates", 16))))
        configured_batch_size = max(32, int(rag_cfg.get("search_batch_size", 512)))
        best: list[tuple[float, tuple[int, ...], int, tuple[int, ...], dict[str, Any]]] = []
        rows_seen = 0
        has_stale_embedding_rows = False
        try:
            import numpy as np
        except Exception:
            np = None

        if np is not None:
            q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
            dimension = int(q.size)
            # Bound several simultaneous scoring arrays, not just decoded vectors.
            memory_batch_limit = _VECTOR_BATCH_MEMORY_BUDGET_BYTES // max(16, dimension * 16)
            batch_size = min(_MAX_VECTOR_BATCH_SIZE, memory_batch_limit, configured_batch_size)
            q_norm = float(np.linalg.norm(q))
            if q_norm > 1e-9:
                q = q / q_norm
            else:
                q = np.zeros(dimension, dtype=np.float32)
        else:
            batch_size = min(2048, configured_batch_size)

        def offer(row: Any, score: float) -> None:
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
            con.execute("BEGIN")
            norm_scope = scope_path.replace("\\", "/").rstrip("/") if scope_path else None
            last_path: str | None = None
            last_chunk_no: int | None = None
            while True:
                predicates = ["tenant=?", "workspace=?", "embedding_space=?"]
                params: list[Any] = [scope_key, workspace, embedding_space]
                if norm_scope is not None:
                    predicates.append("(path=? OR path LIKE ? || '/%')")
                    params.extend((norm_scope, norm_scope))
                if last_path is not None:
                    predicates.append("(path, chunk_no) > (?, ?)")
                    params.extend((last_path, last_chunk_no))
                cursor = con.execute(
                    "SELECT path, chunk_no, embedding, content_hash FROM chunks WHERE "
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
                    norms = np.linalg.norm(matrix, axis=1)
                    scores = np.zeros(len(batch), dtype=np.float32)
                    valid = np.isfinite(norms) & (norms > 1e-9)
                    if q_norm > 1e-9 and valid.any():
                        dot_scores = np.dot(matrix, q)
                        scores[valid] = dot_scores[valid] / norms[valid]
                    scores = np.where(np.isfinite(scores), scores, 0.0)
                    local_count = min(candidate_limit, len(batch))
                    if local_count < len(batch):
                        kth = len(batch) - local_count
                        partition = np.argpartition(scores, kth)
                        cutoff = scores[partition[kth]]
                        above = np.flatnonzero(scores > cutoff)
                        tied = np.flatnonzero(scores == cutoff)
                        remaining = local_count - len(above)
                        if tied.size > remaining:
                            tie_paths = np.asarray(
                                [str(batch[int(index)][0]) for index in tied], dtype=np.str_
                            )
                            tie_chunks = np.fromiter(
                                (int(batch[int(index)][1]) for index in tied),
                                dtype=np.int64,
                                count=len(tied),
                            )
                            tie_hashes = np.asarray(
                                [str(batch[int(index)][3] or "") for index in tied],
                                dtype=np.str_,
                            )
                            tie_order = np.lexsort((tie_hashes, tie_chunks, tie_paths))
                            tied = tied[tie_order[:remaining]]
                        candidate_indices = np.concatenate((above, tied))
                    else:
                        candidate_indices = np.arange(len(batch), dtype=np.intp)
                    path_keys = np.asarray(
                        [str(batch[int(index)][0]) for index in candidate_indices], dtype=np.str_
                    )
                    chunk_keys = np.fromiter(
                        (int(batch[int(index)][1]) for index in candidate_indices),
                        dtype=np.int64,
                        count=len(candidate_indices),
                    )
                    hash_keys = np.asarray(
                        [str(batch[int(index)][3] or "") for index in candidate_indices], dtype=np.str_
                    )
                    local_order = candidate_indices[
                        np.lexsort((hash_keys, chunk_keys, path_keys, -scores[candidate_indices]))
                    ]
                    for index in local_order:
                        offer(batch[index], float(scores[index]))
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
                "SELECT 1 FROM chunks WHERE tenant=? AND workspace=? AND embedding_space<>? LIMIT 1",
                (scope_key, workspace, embedding_space),
            ).fetchone() is not None

        if self._embedding_space_is_resolved(query_result):
            try:
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
            lexical = self._search_fts_candidates(query, tenant, workspace, max(16, top_k * 2), scope_path)
            if not lexical:
                lexical = self._search_token_overlap(query, tenant, workspace, max(16, top_k * 2), scope_path)
            if lexical:
                return {
                    "success": True,
                    "workspace": workspace,
                    "results": [
                        {
                            "path": item["path"],
                            "chunk_no": item["chunk_no"],
                            "text": item.get("text", ""),
                            "content_hash": item.get("content_hash", ""),
                            "score": float(item.get("fts_score", 0.5)),
                        }
                        for item in lexical[:top_k]
                    ],
                    "reranked": False,
                    "degraded": True,
                    "fallback": "embedding_space_mismatch",
                    "reason": "no indexed vectors match the query embedding space",
                    "reindex_required": has_stale_embedding_rows,
                }
            with closing(self._connect()) as con:
                has_indexed_chunks = con.execute(
                    "SELECT 1 FROM chunks WHERE tenant=? AND workspace=? LIMIT 1",
                    (scope_key, workspace),
                ).fetchone() is not None
            if has_indexed_chunks:
                return {
                    "success": True,
                    "workspace": workspace,
                    "results": [],
                    "reranked": False,
                    "degraded": True,
                    "fallback": "embedding_space_mismatch",
                    "reason": "indexed vectors do not match the query embedding space",
                    "reindex_required": has_stale_embedding_rows,
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
        fts_candidates = self._search_fts_candidates(query, tenant, workspace, 16, scope_path)

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
                try:
                    rr = self.reranker.rerank(query, [c["text"] for c in candidates], top_k=top_k, priority=priority)
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
            state_db = state_dir / "agent_state.sqlite3"
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
                self._bump_workspace_index_generation(con, scope_key, clean_ws)
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
