from __future__ import annotations

from contextlib import closing
import importlib
import logging
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterable

from .cache import SingleFlightCache, SQLiteCache, TieredCache, stable_hash
from .process_utils import canonical_workspace_id
from .rag_chunking import _regex_ast_chunks
from .rag_constants import RAG_INDEX_COMPAT_VERSION
from .sqlite_support import (
    connect_sqlite,
    ensure_incremental_vacuum,
    initialize_wal,
    is_busy_error,
    retry_busy,
)


RAGStore = None


class RAGStorageMixin:
    def __init__(self, config: dict[str, Any], services: Any = None, reranker: Any = None):
        self.config = config
        self.services = services
        self.reranker = reranker
        state_dir = Path(config["server"]["state_dir"])
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "rag.sqlite3"
        self._workspace_locks: dict[str, threading.RLock] = {}
        self._workspace_locks_guard = threading.Lock()
        self._workspace_repository_ids: dict[str, str] = {}
        self._index_lock = threading.RLock()
        self._index_flights_lock = threading.Lock()
        self._index_flights: dict[tuple[str, str], dict[str, Any]] = {}
        self._index_wait_timeout_seconds = float(
            config.get("resilience", {}).get("singleflight_wait_timeout_seconds", 240)
        )
        preprocessing_cfg = config.get("preprocessing", {})
        self._sqlite_busy_seconds = max(
            1.0, float(preprocessing_cfg.get("sqlite_busy_timeout_seconds", 5.0))
        )
        self._sqlite_write_retries = max(
            1, int(preprocessing_cfg.get("sqlite_write_retries", 6))
        )
        rag_cfg = config.get("rag", {})
        cpu_cfg = config.get("cpu_retrieval", {})
        model_cfg = config.get("models", {})
        self.index_fingerprint = stable_hash({
            "app_version": RAG_INDEX_COMPAT_VERSION,
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
        self._validate_existing_database(self.db_path, self.index_fingerprint)
        if not ensure_incremental_vacuum(self.db_path).get("success"):
            logging.getLogger(__name__).warning("RAG database incremental vacuum setup incomplete")
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
            if is_busy_error(exc):
                raise
            raise RuntimeError(
                "RAG database is unreadable; original database and sidecars were preserved; "
                "explicit offline recovery required"
            ) from exc

    @staticmethod
    def _validate_existing_database(db_path: Path, fingerprint: str) -> None:
        if not db_path.exists():
            return
        try:
            if db_path.stat().st_size:
                with db_path.open("rb") as database:
                    header = database.read(16)
                if header != b"SQLite format 3\x00":
                    raise RuntimeError(
                        "RAG database is unreadable; original database and sidecars were preserved; "
                        "explicit offline recovery required"
                    )
        except OSError as exc:
            raise RuntimeError(
                "RAG database could not be inspected read-only; original database and sidecars "
                "were preserved; explicit offline recovery required"
            ) from exc
        uri = db_path.resolve().as_uri() + "?mode=ro"
        try:
            with closing(connect_sqlite(uri, uri=True, timeout_seconds=1.0, read_only=True)) as con:
                known_tables = ("chunks", "files", "project_file_owners", "rag_meta", "chunk_fts")
                tables = {str(row[0]) for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?,?,?)",
                    known_tables,
                )}
                canonical = {"chunks", "files", "project_file_owners", "rag_meta"}
                present = canonical.intersection(tables)
                if "chunk_fts" in tables:
                    present.add("chunk_fts")
                if not present:
                    return
                if not canonical.issubset(tables):
                    raise RuntimeError(
                        "RAG database has an incomplete or incompatible durable schema; "
                        "explicit offline conversion required"
                    )
                expected = {
                    "chunks": {"workspace", "path", "chunk_no", "content_hash", "text", "embedding", "embedding_space"},
                    "files": {"workspace", "path", "mtime_ns", "size", "content_hash"},
                    "project_file_owners": {"workspace", "root", "path"},
                    "rag_meta": {"key", "value"},
                }
                for table, required in expected.items():
                    columns = {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}
                    if "tenant" in columns:
                        raise RuntimeError(
                            "RAG database has tenant-shaped durable schema; explicit offline conversion required"
                        )
                    if columns != required:
                        raise RuntimeError(
                            "RAG database has an incompatible durable schema; "
                            "explicit offline conversion required"
                        )
                if "chunk_fts" in tables:
                    fts_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(chunk_fts)")}
                    if "tenant" in fts_columns or fts_columns != {"workspace", "path", "chunk_no", "text"}:
                        raise RuntimeError(
                            "RAG database has an incompatible durable schema; "
                            "explicit offline conversion required"
                        )
                metadata = con.execute(
                    "SELECT value FROM rag_meta WHERE key='index_fingerprint'"
                ).fetchone()
                stored_fingerprint = str(metadata[0]) if metadata is not None else None
                if stored_fingerprint != fingerprint:
                    reason = "fingerprint mismatch" if stored_fingerprint else "missing fingerprint"
                    raise RuntimeError(
                        f"RAG database has {reason}; explicit offline rebuild required"
                    )
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(
                "RAG database is unreadable; original database and sidecars were preserved; "
                "explicit offline recovery required"
            ) from exc

    def _get_workspace_lock(self, workspace: str | None = None) -> threading.RLock:
        ws_key = str(workspace or "default")
        with self._workspace_locks_guard:
            if ws_key not in self._workspace_locks:
                self._workspace_locks[ws_key] = threading.RLock()
            return self._workspace_locks[ws_key]

    def _connect(self) -> sqlite3.Connection:
        con = connect_sqlite(self.db_path, timeout_seconds=5.0)
        try:
            con.execute("PRAGMA cache_size=-16000")
            con.execute("PRAGMA mmap_size=134217728")
        except sqlite3.OperationalError:
            pass
        return con

    def optimize(self) -> None:
        try:
            with closing(self._connect()) as con:
                con.execute("PRAGMA optimize")
                con.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except (sqlite3.DatabaseError, OSError):
            pass

    def _init_db(self) -> None:
        self._validate_existing_database(self.db_path, self.index_fingerprint)
        with closing(self._connect()) as con:
            initialize_wal(con)
            con.execute(
                """CREATE TABLE IF NOT EXISTS chunks (
                    workspace TEXT NOT NULL,
                    path TEXT NOT NULL,
                    chunk_no INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    embedding_space TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (workspace, path, chunk_no)
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS files (
                    workspace TEXT NOT NULL,
                    path TEXT NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    size INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    PRIMARY KEY (workspace, path)
                )"""
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS content_rag_chunks (
                    content_hash TEXT NOT NULL,
                    embedding_space TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    embedding_blob BLOB NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (content_hash, embedding_space, chunk_index)
                )"""
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_content_rag_lookup "
                "ON content_rag_chunks(content_hash, embedding_space)"
            )
            con.execute(
                """CREATE TABLE IF NOT EXISTS project_file_owners (
                    workspace TEXT NOT NULL,
                    root TEXT NOT NULL,
                    path TEXT NOT NULL,
                    PRIMARY KEY (workspace, root, path)
                )"""
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_project_file_owners_path "
                "ON project_file_owners(workspace, path)"
            )
            try:
                con.execute(
                    """CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
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
            con.execute(
                "INSERT OR IGNORE INTO rag_meta(key,value) VALUES('index_fingerprint',?)",
                (self.index_fingerprint,),
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_workspace ON chunks(workspace)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_embedding_space ON chunks(workspace, embedding_space, path, chunk_no)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_content_hash ON chunks(content_hash)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_files_workspace ON files(workspace)")
            con.commit()

    @staticmethod
    def workspace_id(root: str) -> str:
        return canonical_workspace_id(root)

    def has_workspace_chunks(self, *, workspace: str) -> bool:
        """Return whether a workspace has semantic chunks before model work."""
        if type(workspace) is not str or not workspace:
            return False
        with closing(self._connect()) as con:
            return con.execute(
                "SELECT 1 FROM chunks WHERE workspace=? LIMIT 1", (workspace,)
            ).fetchone() is not None

    def indexed_paths(self, *, workspace: str, paths: list[str]) -> set[str]:
        """Return requested paths already persisted in a workspace index."""
        if type(workspace) is not str or not workspace:
            raise ValueError("RAG workspace must be a non-empty string")
        if not isinstance(paths, list):
            raise TypeError("RAG indexed paths must be a list")
        normalized = list(dict.fromkeys(paths))
        if any(type(path) is not str or not path for path in normalized):
            raise ValueError("RAG indexed paths must be non-empty strings")
        if not normalized:
            return set()

        found: set[str] = set()
        with closing(self._connect()) as con:
            embedding_space = (
                self._stored_workspace_reindex_target(con, workspace)
                or self._stored_workspace_embedding_space(con, workspace)
            )
            # Leave room for the workspace parameter below SQLite's usual
            # bound-variable limit.
            for offset in range(0, len(normalized), 900):
                batch = normalized[offset:offset + 900]
                placeholders = ",".join("?" for _ in batch)
                space_filter = ""
                params: tuple[Any, ...] = (workspace, *batch)
                if embedding_space:
                    space_filter = (
                        " AND NOT EXISTS (SELECT 1 FROM chunks c "
                        "WHERE c.workspace=f.workspace AND c.path=f.path "
                        "AND (COALESCE(c.embedding_space,'')<>? "
                        "OR c.embedding IS NULL OR length(c.embedding)=0))"
                    )
                    params = (*params, embedding_space)
                rows = con.execute(
                    f"SELECT f.path FROM files f WHERE f.workspace=? "
                    f"AND f.path IN ({placeholders}){space_filter}",
                    params,
                ).fetchall()
                found.update(str(row[0]) for row in rows)
        return found

    def paths_needing_reindex(
        self, root: str, *, workspace: str, limit: int = 128,
    ) -> list[str]:
        """Return this project's indexed paths whose vectors use a stale embedding space."""
        if type(workspace) is not str or not workspace:
            raise ValueError("RAG workspace must be a non-empty string")
        if type(limit) is not int or limit < 1:
            raise ValueError("RAG reindex limit must be a positive integer")
        project_root = str(Path(root).resolve())
        with closing(self._connect()) as con:
            con.execute("BEGIN")
            embedding_space = self._stored_workspace_reindex_target(con, workspace)
            if not embedding_space and self._embedding_space_is_resolved():
                embedding_space = self._embedding_space_id()
            if not embedding_space or not self._workspace_has_stale_vectors(con, workspace, embedding_space):
                return []
            rows = con.execute(
                """SELECT o.path FROM project_file_owners o WHERE o.workspace=? AND o.root=? AND EXISTS (
                       SELECT 1 FROM chunks c WHERE c.workspace=o.workspace AND c.path=o.path
                         AND c.embedding IS NOT NULL AND length(c.embedding)>0
                         AND COALESCE(c.embedding_space,'')<>?
                   ) ORDER BY o.path LIMIT ?""",
                (workspace, project_root, embedding_space, limit),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def indexed_chunk_paths(self, *, workspace: str, paths: list[str]) -> set[str]:
        """Return requested paths with persisted semantic chunks."""
        if type(workspace) is not str or not workspace:
            raise ValueError("RAG workspace must be a non-empty string")
        if not isinstance(paths, list):
            raise TypeError("RAG indexed chunk paths must be a list")
        normalized = list(dict.fromkeys(paths))
        if any(type(path) is not str or not path for path in normalized):
            raise ValueError("RAG indexed chunk paths must be non-empty strings")
        if not normalized:
            return set()

        found: set[str] = set()
        with closing(self._connect()) as con:
            for offset in range(0, len(normalized), 900):
                batch = normalized[offset:offset + 900]
                placeholders = ",".join("?" for _ in batch)
                rows = con.execute(
                    f"SELECT DISTINCT path FROM chunks WHERE workspace=? AND path IN ({placeholders})",
                    (workspace, *batch),
                ).fetchall()
                found.update(str(row[0]) for row in rows)
        return found

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
        path_policy: Any | None = None,
    ) -> tuple[bool, str | None]:
        if project_context is None:
            return True, None
        api = self.project_config_api()
        if api is None:
            return True, None
        settings = project_context.settings
        kind = api.custom_extension_kind(Path(path).name, settings)
        if path_policy is None:
            allowed = api.path_is_allowed(
                root,
                path,
                settings,
                phase=phase,
                binary=kind == "binary",
                size_bytes=size_bytes,
            )
        else:
            allowed = path_policy.allows(
                path,
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
                    entry_stat = entry.stat(follow_symlinks=False)
                    is_reparse_point = bool(
                        getattr(entry_stat, "st_file_attributes", 0) & 0x400
                    )
                    if entry.is_symlink() or is_reparse_point:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.lower() not in ignored:
                            child = Path(entry.path)
                            if api is None or settings is None or api.may_descend(
                                root, child, settings, phase="rag",
                            ):
                                child_dirs.append(child)
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

        def bounded(chunks: list[str]) -> list[str]:
            return [part for chunk in chunks for part in (
                [chunk] if len(chunk) <= size else self._text_chunks(chunk, size, overlap)
            )]

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
                return bounded(py_chunks)
        if lang:
            ast_chunks = self._ast_chunks(text, lang, size, overlap)
            if ast_chunks:
                return bounded(ast_chunks)
        if lang in {"typescript", "javascript", "c_sharp", "go", "rust", "java", "cpp", "c", "php"}:
            lexical_chunks = _regex_ast_chunks(text, lang, size)
            if lexical_chunks:
                return bounded(lexical_chunks)

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
        covered = [False] * len(lines)

        def mark_covered(node: Any) -> None:
            for index in range(node.lineno - 1, node.end_lineno):
                covered[index] = True

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                block = "".join(lines[node.lineno - 1 : node.end_lineno]).strip()
                full_chunk = f"{preamble_header}{block}" if preamble_header and not block.startswith(preamble[:50]) else block
                if len(full_chunk) <= size:
                    chunks.append(full_chunk)
                    mark_covered(node)
                else:
                    if isinstance(node, ast.ClassDef):
                        cls_header = f"class {node.name}:\n"
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                mark_covered(item)
                                m_block = "".join(lines[item.lineno - 1 : item.end_lineno]).strip()
                                sub = f"{preamble_header}{cls_header}    # method {item.name}\n{m_block}"
                                if len(sub) <= size:
                                    chunks.append(sub)
                                else:
                                    header_prefix = f"# [Enclosing: class {node.name} -> def {item.name}]\n"
                                    chunk_size = max(32, size - len(header_prefix)) if len(header_prefix) < size else size
                                    sub_chunks = self._text_chunks(sub, chunk_size, overlap)
                                    for idx, sc in enumerate(sub_chunks):
                                        if idx > 0 and header_prefix.strip() not in sc and len(header_prefix) + len(sc) <= size:
                                            sc = f"{header_prefix}{sc}"
                                        chunks.append(sc)
                    else:
                        mark_covered(node)
                        fn_sig = "".join(lines[node.lineno - 1 : (node.body[0].lineno - 1 if getattr(node, "body", None) else node.end_lineno)]).strip()
                        if not fn_sig:
                            fn_sig = f"def {getattr(node, 'name', 'function')}"
                        header_prefix = f"# [Enclosing: {fn_sig}]\n"
                        chunk_size = max(32, size - len(header_prefix)) if len(header_prefix) < size else size
                        sub_chunks = self._text_chunks(full_chunk, chunk_size, overlap)
                        for idx, sc in enumerate(sub_chunks):
                            if idx > 0 and header_prefix.strip() not in sc and len(header_prefix) + len(sc) <= size:
                                sc = f"{header_prefix}{sc}"
                            chunks.append(sc)

        # Definitions are not the whole module: retain constants, docstrings,
        # decorators, top-level statements and non-method class members too.
        gaps: list[str] = []
        gap_start = 0
        while gap_start < len(lines):
            if covered[gap_start]:
                gap_start += 1
                continue
            gap_end = gap_start + 1
            while gap_end < len(lines) and not covered[gap_end]:
                gap_end += 1
            gap = "".join(lines[gap_start:gap_end])
            if gap.strip():
                gaps.append(gap)
            gap_start = gap_end
        for gap in gaps:
            chunks.extend(self._text_chunks(gap, size, overlap))

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

