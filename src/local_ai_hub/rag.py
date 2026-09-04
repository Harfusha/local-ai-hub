from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from .cache import SQLiteCache, TieredCache, SingleFlightCache, stable_hash
from .normalizer import normalize_query
from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error


def _canonical_fragment_text(text: str) -> str:
    """Normalize transport-only differences without changing source semantics."""
    return str(text).replace("\r\n", "\n").replace("\r", "\n")


def _fragment_hash(text: str) -> str:
    return hashlib.sha1(
        _canonical_fragment_text(text).encode("utf-8"), usedforsecurity=False
    ).hexdigest()


class RAGStore:
    """Persistent semantic index with file-level incremental updates.

    Local AI keeps a metadata manifest so unchanged files are not reopened/chunked during
    re-index. Changed files are updated transactionally while searches keep seeing
    the previous committed snapshot until the new one is ready.
    """

    def __init__(self, config: dict[str, Any], services: Any, reranker: Any):
        self.config = config
        self.services = services
        self.reranker = reranker
        state_dir = Path(config["server"]["state_dir"])
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "rag.sqlite3"
        self.scope = str(config.get("rag", {}).get("scope", "shared")).lower()
        self._index_lock = threading.Lock()
        self._index_flights_lock = threading.Lock()
        self._index_flights: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._index_wait_timeout_seconds = float(
            config.get("resilience", {}).get("singleflight_wait_timeout_seconds", 240)
        )
        rag_cfg = config.get("rag", {})
        cpu_cfg = config.get("cpu_retrieval", {})
        model_cfg = config.get("models", {})
        self.index_fingerprint = stable_hash({
            "v": 1,
            "embedding": model_cfg.get("embedding"),
            "backend": model_cfg.get("embedding_backend"),
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
            self._init_db()
        except sqlite3.DatabaseError as exc:
            if not is_busy_error(exc):
                self._recover_db()

    def _recover_db(self) -> None:
        import time, sqlite3
        stamp = int(time.time())
        try:
            if self.db_path.exists():
                self.db_path.replace(self.db_path.with_name(self.db_path.name + f".corrupt-{stamp}"))
            for suffix in ("-wal", "-shm"):
                side = Path(str(self.db_path) + suffix)
                if side.exists(): side.unlink()
        except OSError:
            pass
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = connect_sqlite(self.db_path, timeout_seconds=0.75)
        con.execute("PRAGMA cache_size=-64000")
        con.execute("PRAGMA mmap_size=268435456")
        return con

    def _init_db(self) -> None:
        with closing(self._connect()) as con:
            initialize_wal(con)
            row = con.execute("PRAGMA quick_check").fetchone()
            if row and row[0] != "ok":
                import sqlite3
                raise sqlite3.DatabaseError("rag quick_check failed")
            con.execute(
                """CREATE TABLE IF NOT EXISTS chunks (
                    tenant TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    path TEXT NOT NULL,
                    chunk_no INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    embedding TEXT NOT NULL,
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
                """CREATE TABLE IF NOT EXISTS rag_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )"""
            )
            previous = con.execute("SELECT value FROM rag_meta WHERE key='index_fingerprint'").fetchone()
            current = self.index_fingerprint
            if previous is None:
                existing = int(con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
                self.index_reset = existing > 0
                if existing:
                    con.execute("DELETE FROM chunks")
                    con.execute("DELETE FROM files")
            elif str(previous[0]) != current:
                self.index_reset = True
                con.execute("DELETE FROM chunks")
                con.execute("DELETE FROM files")
            con.execute("INSERT OR REPLACE INTO rag_meta(key,value) VALUES('index_fingerprint',?)", (current,))
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_workspace ON chunks(tenant, workspace)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_content_hash ON chunks(content_hash)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_files_workspace ON files(tenant, workspace)")
            con.commit()

    @staticmethod
    def workspace_id(root: str) -> str:
        resolved = str(Path(root).resolve())
        digest = hashlib.sha1(resolved.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
        return f"{Path(resolved).name}-{digest}"

    def _iter_files(self, root: Path) -> Iterable[Path]:
        cfg = self.config.get("rag", {})
        extensions = {x.lower() for x in cfg.get("extensions", [])}
        ignored = set(cfg.get("ignore_dirs", []))
        max_bytes = int(cfg.get("max_file_bytes", 2_000_000))
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ignored]
            for filename in filenames:
                path = Path(dirpath) / filename
                if extensions and path.suffix.lower() not in extensions:
                    continue
                try:
                    if path.stat().st_size <= max_bytes:
                        yield path
                except OSError:
                    continue

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
        if lang:
            ast_chunks = self._ast_chunks(text, lang, size, overlap)
            if ast_chunks:
                return ast_chunks

        # Paragraph-aware fallback (original logic)
        return self._text_chunks(text, size, overlap)

    def _ast_chunks(self, text: str, language: str, size: int, overlap: int) -> list[str]:
        """Try to split code using tree-sitter AST boundaries."""
        # Try to load the appropriate language grammar
        try:
            from tree_sitter import Language, Parser
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

        try:
            with self._index_lock:
                result = self._index_locked(resolved_root, tenant, resolved_workspace)
        except Exception as exc:
            result = {"success": False, "error": str(exc), "retryable": True}
        finally:
            flight["result"] = result
            flight["event"].set()
            with self._index_flights_lock:
                self._index_flights.pop(flight_key, None)
        return result

    def _index_locked(self, root: str, tenant: str, workspace: str | None = None) -> dict[str, Any]:
        root_path = Path(root).resolve()
        if not root_path.exists() or not root_path.is_dir():
            return {"success": False, "error": f"root directory does not exist: {root_path}"}
        workspace = workspace or self.workspace_id(str(root_path))
        scope_key = self._scope_key(tenant)

        with closing(self._connect()) as con:
            old_files_rows = con.execute(
                "SELECT path,mtime_ns,size,content_hash FROM files WHERE tenant=? AND workspace=?",
                (scope_key, workspace),
            ).fetchall()
            old_chunk_rows = con.execute(
                "SELECT path,chunk_no,content_hash,embedding FROM chunks WHERE tenant=? AND workspace=?",
                (scope_key, workspace),
            ).fetchall()
        old_files = {r[0]: {"mtime_ns": int(r[1]), "size": int(r[2]), "content_hash": r[3]} for r in old_files_rows}
        old_chunks = {(r[0], int(r[1]), r[2]): r[3] for r in old_chunk_rows}

        current_meta: dict[str, tuple[Path, int, int]] = {}
        metadata_scanned = 0
        for path in self._iter_files(root_path):
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
            if old and old["mtime_ns"] == mtime_ns and old["size"] == size:
                unchanged_paths.append(rel)
            else:
                changed_paths.append(rel)

        changed_records: list[dict[str, Any]] = []
        file_rows: list[tuple[str, int, int, str]] = []
        skipped = 0
        read_files = 0
        reused_chunks = 0
        changed_indices: list[int] = []
        changed_texts: list[str] = []

        for rel in changed_paths:
            path, mtime_ns, size = current_meta[rel]
            try:
                raw = path.read_bytes()
                read_files += 1
                text = raw.decode("utf-8", errors="replace")
                file_hash = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
            except Exception:
                skipped += 1
                continue
            file_rows.append((rel, mtime_ns, size, file_hash))
            for chunk_no, chunk in enumerate(self._chunks(text, path=rel)):
                chunk_hash = _fragment_hash(chunk)
                record = {
                    "path": rel,
                    "chunk_no": chunk_no,
                    "text": chunk,
                    "hash": chunk_hash,
                    "embedding": old_chunks.get((rel, chunk_no, chunk_hash)),
                }
                idx = len(changed_records)
                changed_records.append(record)
                if record["embedding"] is None:
                    changed_indices.append(idx)
                    changed_texts.append(chunk)
                else:
                    reused_chunks += 1

        if changed_texts:
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
                        f"SELECT content_hash, embedding FROM chunks WHERE tenant=? AND content_hash IN ({placeholders})",
                        (scope_key, *batch_h),
                    ).fetchall()
                    for r in rows:
                        if r[0] and r[1] and str(r[0]) not in global_chunks:
                            global_chunks[str(r[0])] = r[1]

            if global_chunks:
                still_indices: list[int] = []
                still_texts: list[str] = []
                for chash, indices in pending_by_hash.items():
                    if chash in global_chunks:
                        for idx in indices:
                            changed_records[idx]["embedding"] = global_chunks[chash]
                        reused_chunks += len(indices)
                    else:
                        first_idx = indices[0]
                        still_indices.append(first_idx)
                        still_texts.append(str(changed_records[first_idx]["text"]))
                changed_indices = still_indices
                changed_texts = still_texts
            else:
                changed_indices = [indices[0] for indices in pending_by_hash.values()]
                changed_texts = [str(changed_records[idx]["text"]) for idx in changed_indices]

        if changed_texts:
            vectors_result = self.services.embed(changed_texts, tenant, priority=2, query=False)
            if not vectors_result.get("success"):
                return vectors_result
            vectors = vectors_result.get("embeddings", [])
            if len(vectors) != len(changed_indices):
                return {"success": False, "error": f"embedding count mismatch: {len(vectors)} != {len(changed_indices)}"}
            for idx, vector in zip(changed_indices, vectors):
                try:
                    import numpy as np
                    embedding = sqlite3.Binary(np.array(vector, dtype=np.float32).tobytes())
                except Exception:
                    embedding = json.dumps(vector, separators=(",", ":"))
                for duplicate_idx in pending_by_hash[str(changed_records[idx]["hash"])]:
                    changed_records[duplicate_idx]["embedding"] = embedding

        # One transaction publishes all changed/deleted file state atomically.
        with closing(self._connect()) as con:
            for rel in deleted_paths + changed_paths:
                con.execute("DELETE FROM chunks WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                con.execute("DELETE FROM files WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
            con.executemany(
                "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding) VALUES(?,?,?,?,?,?,?)",
                [
                    (scope_key, workspace, r["path"], r["chunk_no"], r["hash"], r["text"], r["embedding"])
                    for r in changed_records
                ],
            )
            con.executemany(
                "INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)",
                [(scope_key, workspace, rel, mtime_ns, size, file_hash) for rel, mtime_ns, size, file_hash in file_rows],
            )
            con.commit()

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
        }


    def prune_missing(self, root: str, tenant: str, workspace: str, current_paths: list[str]) -> int:
        """Delete RAG rows for files no longer present without rescanning the filesystem."""
        scope_key = self._scope_key(tenant)
        current = set(current_paths)
        with self._index_lock, closing(self._connect()) as con:
            existing = {str(r[0]) for r in con.execute(
                "SELECT path FROM files WHERE tenant=? AND workspace=?", (scope_key, workspace)
            ).fetchall()}
            deleted = existing - current
            for rel in deleted:
                con.execute("DELETE FROM chunks WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                con.execute("DELETE FROM files WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
            con.commit()
        return len(deleted)

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
        with self._index_lock, closing(self._connect()) as con:
            for rel in unique:
                row = con.execute(
                    "SELECT 1 FROM files WHERE tenant=? AND workspace=? AND path=?",
                    (scope_key, workspace, rel),
                ).fetchone()
                con.execute("DELETE FROM chunks WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                con.execute("DELETE FROM files WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                removed += int(row is not None)
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
    ) -> dict[str, Any]:
        """Index only explicitly dirty paths supplied by Local AI preprocessing.

        This avoids repeatedly walking a cold repository for each micro-step.
        """
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            return {"success": False, "error": f"root directory does not exist: {root_path}"}
        scope_key = self._scope_key(tenant)
        processed_paths: list[str] = []
        embedded_chunks = 0
        reused_chunks = 0
        with self._index_lock:
            # 1. Read files and chunk
            file_data: list[dict[str, Any]] = []
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
                    override = (content_overrides or {}).get(rel)
                    if override is None:
                        raw = path.read_bytes()
                        text = raw.decode("utf-8", errors="replace")
                        file_hash = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
                    else:
                        text = str(override)
                        file_hash = hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()
                    chunks = list(self._chunks(text, path=rel))
                    file_data.append({"rel": rel, "stat": stat, "file_hash": file_hash, "chunks": chunks})
                except Exception:
                    continue

            if not file_data:
                return {
                    "success": True, "workspace": workspace, "preempted": False,
                    "processed_paths": [], "embedded_chunks": 0, "reused_chunks": 0,
                }

            # 2. Bulk load existing chunks
            all_rels = [f["rel"] for f in file_data]
            old_chunks: dict[tuple[str, int, str], str] = {}
            with closing(self._connect()) as con:
                # Load in chunks of 500
                for i in range(0, len(all_rels), 500):
                    batch_rels = all_rels[i:i+500]
                    placeholders = ",".join("?" for _ in batch_rels)
                    rows = con.execute(
                        f"SELECT path,chunk_no,content_hash,embedding FROM chunks WHERE tenant=? AND workspace=? AND path IN ({placeholders})",
                        (scope_key, workspace, *batch_rels),
                    ).fetchall()
                    for r in rows:
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
                    records.append({"chunk_no": chunk_no, "text": chunk, "hash": chash, "embedding": embedding})
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
                            f"SELECT content_hash, embedding FROM chunks WHERE tenant=? AND content_hash IN ({placeholders})",
                            (scope_key, *batch_h),
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
                            reused_chunks += 1
                        else:
                            still_missing_texts.append(text)
                            still_missing_pointers.append((f_idx, rec_idx))
                    all_missing_texts = still_missing_texts
                    missing_pointers = still_missing_pointers

            # 5. Single bulk embedding call for truly novel chunks
            if all_missing_texts:
                if callable(should_yield) and should_yield():
                    return {
                        "success": True, "workspace": workspace, "preempted": True,
                        "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
                        "reused_chunks": reused_chunks,
                    }
                vectors_result = self.services.embed(all_missing_texts, tenant, priority=0, query=False)
                if not vectors_result.get("success"):
                    return vectors_result
                vectors = vectors_result.get("embeddings", [])
                if len(vectors) != len(all_missing_texts):
                    return {"success": False, "error": "embedding count mismatch during background RAG path step"}
                for (f_idx, rec_idx), vector in zip(missing_pointers, vectors):
                    try:
                        import numpy as np
                        file_data[f_idx]["records"][rec_idx]["embedding"] = sqlite3.Binary(np.array(vector, dtype=np.float32).tobytes())
                    except Exception:
                        file_data[f_idx]["records"][rec_idx]["embedding"] = json.dumps(vector, separators=(",", ":"))
                embedded_chunks += len(all_missing_texts)

            # 5. Bulk SQLite transaction
            chunks_to_insert: list[tuple[Any, ...]] = []
            files_to_insert: list[tuple[Any, ...]] = []
            for item in file_data:
                rel = item["rel"]
                stat = item["stat"]
                for r in item["records"]:
                    chunks_to_insert.append((scope_key, workspace, rel, r["chunk_no"], r["hash"], r["text"], r["embedding"]))
                files_to_insert.append((scope_key, workspace, rel, int(stat.st_mtime_ns), int(stat.st_size), item["file_hash"]))
                processed_paths.append(rel)

            with closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                for i in range(0, len(all_rels), 500):
                    batch_rels = all_rels[i:i+500]
                    placeholders = ",".join("?" for _ in batch_rels)
                    con.execute(f"DELETE FROM chunks WHERE tenant=? AND workspace=? AND path IN ({placeholders})", (scope_key, workspace, *batch_rels))
                    con.execute(f"DELETE FROM files WHERE tenant=? AND workspace=? AND path IN ({placeholders})", (scope_key, workspace, *batch_rels))
                con.executemany(
                    "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding) VALUES(?,?,?,?,?,?,?)",
                    chunks_to_insert,
                )
                con.executemany(
                    "INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)",
                    files_to_insert,
                )
                con.commit()

        return {
            "success": True, "workspace": workspace, "preempted": False,
            "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
            "reused_chunks": reused_chunks,
        }

    def index_step(
        self,
        root: str,
        tenant: str,
        workspace: str | None = None,
        max_files: int = 2,
        should_yield: Any | None = None,
    ) -> dict[str, Any]:
        """Index only a few changed files so idle preprocessing stays preemptible.

        Each call commits independently. Repeated calls converge to the same state as
        :meth:`index`, while foreground work can take over between calls.
        """
        with self._index_lock:
            root_path = Path(root).resolve()
            if not root_path.exists() or not root_path.is_dir():
                return {"success": False, "error": f"root directory does not exist: {root_path}"}
            workspace = workspace or self.workspace_id(str(root_path))
            scope_key = self._scope_key(tenant)
            if callable(should_yield) and should_yield():
                return {"success": True, "workspace": workspace, "preempted": True, "done": False, "processed_files": 0}

            with closing(self._connect()) as con:
                old_rows = con.execute(
                    "SELECT path,mtime_ns,size,content_hash FROM files WHERE tenant=? AND workspace=?",
                    (scope_key, workspace),
                ).fetchall()
                old_chunk_rows = con.execute(
                    "SELECT path,chunk_no,content_hash,embedding FROM chunks WHERE tenant=? AND workspace=?",
                    (scope_key, workspace),
                ).fetchall()
            old_files = {r[0]: {"mtime_ns": int(r[1]), "size": int(r[2]), "content_hash": r[3]} for r in old_rows}
            old_chunks = {(r[0], int(r[1]), r[2]): r[3] for r in old_chunk_rows}

            current_meta: dict[str, tuple[Path, int, int]] = {}
            for path in self._iter_files(root_path):
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
            ]
            changed_all.sort()
            selected = changed_all[: max(1, int(max_files))]

            # Deletions are cheap and safe to publish immediately.
            if deleted:
                with closing(self._connect()) as con:
                    for rel in deleted:
                        con.execute("DELETE FROM chunks WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                        con.execute("DELETE FROM files WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                    con.commit()

            processed = 0
            embedded_chunks = 0
            reused_chunks = 0
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
                    text = raw.decode("utf-8", errors="replace")
                    file_hash = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
                except Exception:
                    continue
                records: list[dict[str, Any]] = []
                missing_idx: list[int] = []
                missing_texts: list[str] = []
                for chunk_no, chunk in enumerate(self._chunks(text, path=rel)):
                    chash = _fragment_hash(chunk)
                    embedding = old_chunks.get((rel, chunk_no, chash))
                    rec = {"chunk_no": chunk_no, "text": chunk, "hash": chash, "embedding": embedding}
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
                                f"SELECT content_hash, embedding FROM chunks WHERE tenant=? AND content_hash IN ({placeholders})",
                                (scope_key, *batch_h),
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
                    vectors_result = self.services.embed(missing_texts, tenant, priority=0, query=False)
                    if not vectors_result.get("success"):
                        return vectors_result
                    vectors = vectors_result.get("embeddings", [])
                    if len(vectors) != len(missing_idx):
                        return {"success": False, "error": "embedding count mismatch during background RAG step"}
                    for idx, vector in zip(missing_idx, vectors):
                        try:
                            import numpy as np
                            records[idx]["embedding"] = sqlite3.Binary(np.array(vector, dtype=np.float32).tobytes())
                        except Exception:
                            records[idx]["embedding"] = json.dumps(vector, separators=(",", ":"))
                    embedded_chunks += len(missing_idx)

                with closing(self._connect()) as con:
                    con.execute("DELETE FROM chunks WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                    con.execute("DELETE FROM files WHERE tenant=? AND workspace=? AND path=?", (scope_key, workspace, rel))
                    con.executemany(
                        "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding) VALUES(?,?,?,?,?,?,?)",
                        [(scope_key, workspace, rel, r["chunk_no"], r["hash"], r["text"], r["embedding"]) for r in records],
                    )
                    con.execute(
                        "INSERT INTO files(tenant,workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?,?)",
                        (scope_key, workspace, rel, mtime_ns, size, file_hash),
                    )
                    con.commit()
                processed += 1

            remaining = max(0, len(changed_all) - processed)
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
        dot = RAGStore._dot(a, b)
        na = math.sqrt(RAGStore._dot(a, a))
        nb = math.sqrt(RAGStore._dot(b, b))
        return dot / (na * nb) if na and nb else 0.0

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
        key = stable_hash({"workspace": workspace, "revision": revision, "query": clean_query, "top_k": top_k, "reranker": use_reranker, "scope_path": scope_path})
        raw, hit, coalesced = self.search_flight.get_or_compute(
            key, lambda: self._search_uncached(clean_query, tenant, workspace, top_k, use_reranker, priority, scope_path)
        )
        result = dict(raw) if isinstance(raw, dict) else {"success": False, "error": "search failed"}
        result["search_cache"] = {"hit": hit, "coalesced": coalesced, "revision": revision}
        return self._postprocess_search_payload(result, top_k) if isinstance(result, dict) else result

    def _search_uncached(self, query: str, tenant: str, workspace: str, top_k: int = 8, use_reranker: bool = True, priority: int = 3, scope_path: str | None = None) -> dict[str, Any]:
        scope_key = self._scope_key(tenant)
        query_result = self.services.embed([query], tenant, priority=priority, query=True)
        if not query_result.get("success"):
            return query_result
        query_vec = query_result["embeddings"][0]

        with closing(self._connect()) as con:
            if scope_path:
                norm_scope = scope_path.replace("\\", "/").rstrip("/")
                rows = con.execute(
                    "SELECT path, chunk_no, text, embedding, content_hash FROM chunks WHERE tenant=? AND workspace=? AND (path=? OR path LIKE ? || '/%')",
                    (scope_key, workspace, norm_scope, norm_scope),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT path, chunk_no, text, embedding, content_hash FROM chunks WHERE tenant=? AND workspace=?",
                    (scope_key, workspace),
                ).fetchall()

        if not rows:
            return {"success": True, "workspace": workspace, "results": [], "warning": "workspace has no matching indexed chunks"}

        # SIMD-vectorized cosine similarity via NumPy
        try:
            import numpy as np
            q = np.array(query_vec, dtype=np.float32)
            q_norm = float(np.linalg.norm(q))
            if q_norm > 1e-9:
                q = q / q_norm

            vec_list = []
            for r in rows:
                raw_v = r[3]
                if isinstance(raw_v, (bytes, memoryview)):
                    vec_list.append(np.frombuffer(raw_v, dtype=np.float32))
                elif isinstance(raw_v, str):
                    try:
                        vec_list.append(np.array(json.loads(raw_v), dtype=np.float32))
                    except Exception:
                        vec_list.append(np.zeros(len(query_vec), dtype=np.float32))
                else:
                    vec_list.append(np.zeros(len(query_vec), dtype=np.float32))

            mat = np.vstack(vec_list)
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms < 1e-9] = 1.0
            normed_mat = mat / norms

            scores = np.dot(normed_mat, q)
            top_n = min(len(rows), max(16, int(self.config.get("rag", {}).get("rerank_candidates", 16))))
            top_indices = np.argpartition(scores, -top_n)[-top_n:]
            top_indices = top_indices[np.argsort(-scores[top_indices])]

            candidates = [
                {
                    "path": rows[idx][0],
                    "chunk_no": rows[idx][1],
                    "text": rows[idx][2],
                    "content_hash": rows[idx][4],
                    "embedding_score": float(scores[idx]),
                }
                for idx in top_indices
            ]
        except Exception:
            def _parse_vec(v: Any) -> list[float]:
                if isinstance(v, (bytes, memoryview)):
                    try:
                        import numpy as np
                        return np.frombuffer(v, dtype=np.float32).tolist()
                    except Exception:
                        import struct
                        return list(struct.unpack(f"{len(v)//4}f", v))
                elif isinstance(v, str):
                    try:
                        return [float(x) for x in json.loads(v)]
                    except Exception:
                        return [0.0] * len(query_vec)
                return [0.0] * len(query_vec)

            scored = [
                {
                    "path": row[0], "chunk_no": row[1], "text": row[2], "content_hash": row[4],
                    "embedding_score": self._cosine(query_vec, _parse_vec(row[3])),
                }
                for row in rows
            ]
            scored.sort(key=lambda item: item["embedding_score"], reverse=True)
            candidates = scored[: int(self.config.get("rag", {}).get("rerank_candidates", 16))]

        reranked = False
        if use_reranker and self.config.get("features", {}).get("reranker", True) and candidates:
            rr = self.reranker.rerank(query, [c["text"] for c in candidates], top_k=top_k, priority=priority)
            if rr.get("success"):
                ordered: list[dict[str, Any]] = []
                for item in rr["results"]:
                    base = dict(candidates[item["index"]])
                    base["rerank_score"] = item["score"]
                    ordered.append(base)
                candidates = ordered
                reranked = True

        return {"success": True, "workspace": workspace, "reranked": reranked, "results": candidates[:top_k]}

    def list_workspaces(self, tenant: str) -> list[dict[str, Any]]:
        scope_key = self._scope_key(tenant)
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT workspace, COUNT(*), COUNT(DISTINCT path) FROM chunks WHERE tenant=? GROUP BY workspace ORDER BY workspace",
                (scope_key,),
            ).fetchall()
        return [{"workspace": r[0], "chunks": r[1], "files": r[2]} for r in rows]
