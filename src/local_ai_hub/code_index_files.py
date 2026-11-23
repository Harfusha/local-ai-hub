from __future__ import annotations

import ast
from collections import Counter
from contextlib import closing
import json
import logging
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Iterable

from .cache import stable_hash
from .code_index_candidate_parse import parse_index_candidate
from .code_index_constants import (
    ARROW_DEF,
    GENERIC_DEF,
    GO_METHOD,
    IMPORT,
    INLINE_ARROW_DEF,
    JS_METHOD,
    TYPED_METHOD,
    _CONTROL_NAMES,
    _PARSER_ANALYZER_VERSION,
    _declaration_call_spans,
)
from .code_index_locks import (
    _advance_query_cache_generation,
    _code_index_initialization_lock,
    _query_cache_generation,
)
from .code_index_parse_blobs import load_parse_blobs
from .code_index_scoring import _resolve_code_index_path_policy
from .code_index_spans import (
    _arrow_expression_end_line,
    _call_edge_source,
    _callable_block_close_position,
    _callable_needs_close_position,
    _edge_endpoint_name,
    _mask_non_code,
)
from .json_utils import dumps as json_dumps
from .process_utils import canonical_root
from .repo_tools import FileTooLargeError, is_root_archive_path
from .sqlite_counts import initialize_row_counts
from .sqlite_support import (
    connect_sqlite,
    ensure_incremental_vacuum,
    initialize_wal,
    is_busy_error,
    quick_sanity_check,
    sqlite_batches,
    write_transaction,
)


CodeIndex = None


class CodeIndexFileMixin:
    def _write_budget_roots(self, root: str, protected_roots: Iterable[str] = ()) -> tuple[str, ...] | None:
        roots = {canonical_root(root)}
        if isinstance(protected_roots, (str, bytes)):
            return None
        try:
            supplied = tuple(protected_roots)
        except TypeError:
            return None
        for item in supplied:
            if not isinstance(item, str) or not item.strip() or not Path(item).is_absolute():
                return None
            try:
                roots.add(canonical_root(item))
            except (OSError, RuntimeError, ValueError):
                return None
        provider = self._active_roots_provider
        if callable(provider):
            try:
                active = provider()
                if isinstance(active, (str, bytes)) or active is None:
                    return None
                for item in active:
                    if not isinstance(item, str) or not item.strip() or not Path(item).is_absolute():
                        return None
                    try:
                        roots.add(canonical_root(item))
                    except (OSError, RuntimeError, ValueError):
                        return None
            except Exception:
                # Without the active-root snapshot, refuse eviction rather than
                # risk removing another worker's in-flight worktree.
                return None
        return tuple(sorted(roots))

    def _physical_storage_bytes(self) -> int:
        total = 0
        for path in (self.db_path, Path(str(self.db_path) + "-wal"), Path(str(self.db_path) + "-shm")):
            try:
                total += path.stat().st_size
            except FileNotFoundError:
                continue
        return total

    def _reserve_write_budget(
        self, root: str, expected_growth_bytes: int, *, protected_roots: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Make room before a write; refuse indexing when the bounded eviction pass cannot."""
        if type(expected_growth_bytes) is not int or expected_growth_bytes < 0:
            return {"success": False, "budget_limited": True, "error": "invalid growth estimate"}
        physical_bytes = self._physical_storage_bytes()
        if physical_bytes + expected_growth_bytes <= self.max_index_bytes:
            return {
                "success": True, "budget_limited": False, "estimated_growth_bytes": expected_growth_bytes,
                "before": {"physical_bytes": physical_bytes}, "after": {"physical_bytes": physical_bytes},
                "eviction": None,
            }
        before = self.measure_storage()
        target = self.max_index_bytes - expected_growth_bytes
        if target < 1:
            return {
                "success": False, "budget_limited": True, "estimated_growth_bytes": expected_growth_bytes,
                "before": before, "after": before, "eviction": None,
            }
        protected = self._write_budget_roots(root, protected_roots)
        if protected is None:
            return {
                "success": False, "budget_limited": True, "reason": "active_roots_unavailable",
                "estimated_growth_bytes": expected_growth_bytes, "before": before, "after": before,
                "eviction": None,
            }
        eviction = self.enforce_size_limit(
            max_bytes=target, max_files=512,
            protected_roots=protected,
        )
        after = self.measure_storage()
        admitted = bool(eviction.get("success") is True and after["physical_bytes"] + expected_growth_bytes <= self.max_index_bytes)
        return {
            "success": admitted, "budget_limited": not admitted,
            "estimated_growth_bytes": expected_growth_bytes, "before": before, "after": after,
            "eviction": eviction,
        }

    def _reconcile_post_write_budget(self, paths: Iterable[tuple[str, str]]) -> dict[str, Any]:
        """Enforce the physical cap after SQLite/WAL write amplification is known."""
        requested = list(dict.fromkeys((str(root), str(path)) for root, path in paths))
        before = self.measure_storage()
        if before["physical_bytes"] <= self.max_index_bytes:
            return {"success": True, "within_budget": True, "before": before, "after": before,
                    "evicted_paths": [], "missing_paths": []}

        # Do not evict a project that another active preprocessor may be using.
        # A malformed/incomplete active-root snapshot fails closed.
        protected_roots: tuple[str, ...] = ()
        provider = self._active_roots_provider
        if callable(provider):
            try:
                active = provider()
                if isinstance(active, (str, bytes)) or active is None:
                    raise ValueError("invalid active roots")
                normalized_active: set[str] = set()
                for item in active:
                    if not isinstance(item, str) or not item.strip() or not Path(item).is_absolute():
                        raise ValueError("invalid active root")
                    normalized_active.add(canonical_root(item))
                protected_roots = tuple(sorted(normalized_active))
            except Exception:
                return {"success": False, "within_budget": False, "before": before,
                        "after": before, "evicted_paths": [], "missing_paths": [],
                        "reason": "active_roots_unavailable"}

        eviction = self.enforce_size_limit(
            max_bytes=self.max_index_bytes, max_files=512, protected_roots=protected_roots,
        )
        after = self.measure_storage()
        recovery_vacuum: dict[str, Any] | None = None
        # The regular maintenance path deliberately avoids VACUUM on oversized
        # legacy databases. A single write can cross the cap after WAL/page
        # amplification, though; permit one bounded recovery only when the
        # entire physical store is at most twice the configured cap.
        if after["physical_bytes"] > self.max_index_bytes and after["physical_bytes"] <= self.max_index_bytes * 2:
            deadline = time.monotonic() + 5.0
            try:
                with closing(self._connect()) as con:
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 2000)
                    con.execute("VACUUM")
                recovery_vacuum = {"success": True, "method": "bounded_overshoot_vacuum"}
            except sqlite3.DatabaseError as exc:
                recovery_vacuum = {"success": False, "method": "bounded_overshoot_vacuum",
                                   "error": type(exc).__name__}
            after = self.measure_storage()
        surviving: set[tuple[str, str]] = set()
        for root in sorted({root for root, _path in requested}):
            with self._lock, closing(self._connect()) as con:
                rows = con.execute("SELECT path FROM files WHERE root=?", (root,)).fetchall()
            surviving.update((root, str(row[0])) for row in rows)
        missing = [item for item in requested if item not in surviving]
        within_budget = after["physical_bytes"] <= self.max_index_bytes
        return {
            "success": bool(within_budget and not missing),
            "within_budget": within_budget, "before": before, "after": after,
            "evicted_paths": eviction.get("evicted_paths", []), "missing_paths": missing,
            "eviction_success": eviction.get("success") is True,
            "eviction": eviction, "recovery_vacuum": recovery_vacuum,
        }

    @staticmethod
    def _estimate_write_growth(
        file_count: int, parse_blob_rows: Iterable[tuple[Any, ...]],
        symbols: Iterable[tuple[Any, ...]], refs: Iterable[tuple[Any, ...]], edges: Iterable[tuple[Any, ...]],
    ) -> int:
        """Conservative page-growth estimate for serialized rows and SQLite indexes."""
        if file_count <= 0:
            return 0
        payload_bytes = sum(len(str(row[3]).encode("utf-8")) for row in parse_blob_rows)
        row_bytes = 0
        trigram_rows = 0
        for row in symbols:
            row_bytes += sum(len(str(value).encode("utf-8")) + 32 for value in row[2:])
            # symbol_trigrams is a table plus a multi-column index. Text bytes
            # alone badly understate its growth for code with many long names,
            # paths, containers, or docstrings. Match _replace_symbol_trigrams.
            if len(row) >= 11:
                for value in (row[2], row[7], row[6], row[1], row[10]):
                    text_value = str(value or "").lower()
                    if len(text_value) >= 3:
                        trigram_rows += len({
                            text_value[offset:offset + 3]
                            for offset in range(len(text_value) - 2)
                        })
        row_bytes += sum(
            len(str(value).encode("utf-8")) + 32
            for rows in (refs, edges) for row in rows for value in row[2:]
        )
        # Each distinct trigram is stored in both the table and its lookup
        # index, with root/path/field and SQLite page overhead. The 384-byte
        # allowance stayed above measured growth in the trigram-heavy fixture.
        return max(
            65536 * file_count,
            (payload_bytes + row_bytes) * 2 + trigram_rows * 384 + 32768 * file_count,
        )

    def _cache_generation(self) -> int:
        with self._cache_guard:
            version = self._cache_observer.version()
            if version is None or version != self._observed_data_version:
                for cache in (
                    getattr(self, "_query_l1", None),
                    getattr(self, "_symbol_l1", None),
                    getattr(self, "_parse_blob_l1", None),
                    getattr(self, "_impact_result_l1", None),
                    getattr(self, "_impact_path_format_l1", None),
                    getattr(self, "_impact_candidate_count_l1", None),
                ):
                    if cache is not None:
                        cache.clear()
                self._status_cache.clear()
                self._advance_query_cache_generation()
            self._observed_data_version = version
            return _query_cache_generation(self._query_cache_generation_key)

    def close(self) -> None:
        observer = getattr(self, "_cache_observer", None)
        if observer is not None:
            observer.close()

    def _advance_query_cache_generation(self) -> None:
        # A generation key makes in-flight pre-update queries unreachable after
        # any index mutation without clearing the bounded cache under readers.
        # The registry is shared by CodeIndex instances that use this database.
        _advance_query_cache_generation(self._query_cache_generation_key)

    def _connect(self, *, register_archive_function: bool = True) -> sqlite3.Connection:
        if self._read_only:
            uri = self.db_path.resolve(strict=True).as_uri() + "?mode=ro"
            con = connect_sqlite(uri, uri=True, timeout_seconds=5.0, row_factory=sqlite3.Row, read_only=True)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA busy_timeout=5000")
            con.execute("PRAGMA query_only=ON")
        else:
            con = connect_sqlite(self.db_path, timeout_seconds=5.0, row_factory=sqlite3.Row)
        try:
            con.execute("PRAGMA recursive_triggers=ON")
            if register_archive_function:
                con.create_function("hub_root_archive_path", 1, is_root_archive_path, deterministic=True)
        except Exception:
            con.close()
            raise
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

    def _schema(self, con: sqlite3.Connection) -> None:
        existing_symbols = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='symbols'"
        ).fetchone()
        existing_trigrams = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='symbol_trigrams'"
        ).fetchone()
        if existing_symbols and not existing_trigrams:
            # The index is derived state; old databases are rebuilt, never migrated.
            raise sqlite3.DatabaseError("stale derived code-index trigram schema; rebuild this cache")
        for table, required_columns in (
            ("files", {"analyzer_version", "mtime_ns", "size_bytes"}),
            ("edges", {"src_name", "dst_name"}),
        ):
            exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,),
            ).fetchone()
            if exists:
                columns = {
                    str(row["name"])
                    for row in con.execute(f"PRAGMA table_info({table})").fetchall()
                }
                if not required_columns.issubset(columns):
                    # Check before CREATE INDEX references new columns, so the
                    # disposable-cache recovery path gets the stable diagnosis.
                    raise sqlite3.DatabaseError(
                        "stale derived code-index schema; rebuild this cache"
                    )
        if existing_trigrams:
            trigram_columns = {
                str(row["name"])
                for row in con.execute("PRAGMA table_info(symbol_trigrams)").fetchall()
            }
            if not {"root", "path", "symbol_rowid", "field", "gram"}.issubset(trigram_columns):
                raise sqlite3.DatabaseError("invalid derived code-index trigram schema; rebuild this cache")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS files(
            root TEXT,
            path TEXT,
            content_hash TEXT,
            analyzer_version TEXT,
            language TEXT,
            updated_at REAL,
            mtime_ns INTEGER,
            size_bytes INTEGER,
            PRIMARY KEY(root, path)
        );
        CREATE INDEX IF NOT EXISTS idx_files_parse_blob_ref
            ON files(content_hash, analyzer_version, language);
        CREATE TABLE IF NOT EXISTS file_usage(
            root TEXT NOT NULL,
            path TEXT NOT NULL,
            use_count INTEGER NOT NULL DEFAULT 0,
            last_used_at REAL NOT NULL DEFAULT 0,
            PRIMARY KEY(root, path)
        );
        CREATE TABLE IF NOT EXISTS symbols(
            root TEXT,
            path TEXT,
            name TEXT,
            kind TEXT,
            line INTEGER,
            end_line INTEGER,
            container TEXT,
            name_path TEXT,
            signature TEXT,
            access TEXT,
            docstring TEXT,
            PRIMARY KEY(root, path, name_path, line)
        );
        CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(root, name);
        CREATE INDEX IF NOT EXISTS idx_symbols_name_lc ON symbols(root, lower(name));
        CREATE INDEX IF NOT EXISTS idx_symbols_name_path ON symbols(root, name_path);
        CREATE INDEX IF NOT EXISTS idx_symbols_name_path_lc ON symbols(root, lower(name_path));
        CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(root, path);
        CREATE INDEX IF NOT EXISTS idx_symbols_container ON symbols(root, container);

        CREATE TABLE IF NOT EXISTS symbol_trigrams(
            root TEXT NOT NULL,
            path TEXT NOT NULL,
            symbol_rowid INTEGER NOT NULL,
            field TEXT NOT NULL,
            gram TEXT NOT NULL,
            PRIMARY KEY(root, path, symbol_rowid, field, gram)
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS idx_symbol_trigrams_root_gram_symbol
            ON symbol_trigrams(root, gram, symbol_rowid, field);

        CREATE TABLE IF NOT EXISTS refs(
            root TEXT,
            path TEXT,
            name TEXT,
            line INTEGER,
            kind TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_refs_name ON refs(root, name);
        CREATE INDEX IF NOT EXISTS idx_refs_name_path ON refs(root, name, path);
        CREATE INDEX IF NOT EXISTS idx_refs_name_lc ON refs(root, lower(name));
        CREATE INDEX IF NOT EXISTS idx_refs_path ON refs(root, path);

        CREATE TABLE IF NOT EXISTS edges(
            root TEXT,
            src TEXT,
            dst TEXT,
            src_name TEXT,
            dst_name TEXT,
            kind TEXT,
            path TEXT,
            line INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(root, src);
        CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(root, dst);
        CREATE INDEX IF NOT EXISTS idx_edges_dst_path ON edges(root, dst, path);
        CREATE INDEX IF NOT EXISTS idx_edges_path ON edges(root, path);

        CREATE TABLE IF NOT EXISTS parse_blobs(
            content_hash TEXT,
            analyzer_version TEXT,
            language TEXT,
            payload_json TEXT,
            updated_at REAL,
            PRIMARY KEY(content_hash, analyzer_version, language)
        );
        CREATE INDEX IF NOT EXISTS idx_parse_blobs_updated ON parse_blobs(updated_at);
        """)
        edge_columns = {str(row["name"]) for row in con.execute("PRAGMA table_info(edges)").fetchall()}
        file_columns = {str(row["name"]) for row in con.execute("PRAGMA table_info(files)").fetchall()}
        if not {"src_name", "dst_name"}.issubset(edge_columns) or not {
            "analyzer_version", "mtime_ns", "size_bytes"
        }.issubset(file_columns):
            # Derived state is disposable: let the existing initialization
            # recovery archive and rebuild it instead of migrating old rows.
            raise sqlite3.DatabaseError("stale derived code-index schema; rebuild this cache")
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_edges_root_kind_dst_name ON edges(root, kind, dst_name)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_edges_root_kind_src_name ON edges(root, kind, src_name)"
        )
        initialize_row_counts(con, ("files", "symbols", "refs", "edges"))

    def _init_db(self) -> None:
        with _code_index_initialization_lock(self.db_path):
            self._initialize_db()
            # Converting a legacy database to INCREMENTAL auto-vacuum requires a
            # full VACUUM. Do not make Hub startup attempt that conversion on an
            # already oversized index: the bounded conversion can still hold a
            # large database lock for seconds on every restart. Large legacy DBs
            # remain usable; eviction reports that physical compaction needs a
            # separately scheduled maintenance window.
            try:
                physical_bytes = sum(
                    candidate.stat().st_size
                    for candidate in (
                        self.db_path,
                        Path(str(self.db_path) + "-wal"),
                        Path(str(self.db_path) + "-shm"),
                    )
                    if candidate.exists()
                )
                if physical_bytes > self.max_index_bytes:
                    logging.getLogger(__name__).warning(
                        "Skipping code-index auto-vacuum setup for oversized database (%s bytes)",
                        physical_bytes,
                    )
                    return
            except (OSError, sqlite3.Error, TypeError, ValueError):
                # Keep the index available; normal database health checks report
                # corruption separately and the bounded eviction path can retry.
                return
            if not ensure_incremental_vacuum(self.db_path).get("success"):
                logging.getLogger(__name__).warning("code-index database incremental vacuum setup incomplete")

    def _initialize_db(self) -> None:
        try:
            with self._lock, closing(self._connect()) as con:
                initialize_wal(con)
                if not quick_sanity_check(con):
                    raise sqlite3.DatabaseError("code-index sanity check failed")
                self._schema(con)
                con.commit()
        except sqlite3.DatabaseError as exc:
            if is_busy_error(exc):
                return
            stamp = int(time.time())
            try:
                if self.db_path.exists():
                    self.db_path.replace(self.db_path.with_name(self.db_path.name + f".corrupt-{stamp}"))
                for suffix in ("-wal", "-shm"):
                    side = Path(str(self.db_path) + suffix)
                    if side.exists():
                        side.unlink(missing_ok=True)
            except OSError as archive_error:
                reason = (
                    "stale derived code-index schema recovery failed"
                    if "stale derived code-index schema" in str(exc)
                    else "code-index recovery failed"
                )
                raise sqlite3.DatabaseError(
                    f"{reason}: unable to archive cache ({type(archive_error).__name__})"
                ) from exc
            with self._lock, closing(self._connect()) as con:
                initialize_wal(con)
                self._schema(con)
                con.commit()

    @staticmethod
    def _lang(path: str) -> str:
        suffix = Path(path).suffix.lower()
        return {
            ".py": "python",
            ".cs": "csharp",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".php": "php",
            ".java": "java",
            ".cpp": "cpp",
            ".go": "go",
            ".rs": "rust",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
        }.get(suffix, "generic")

    def _project_config_context(self, root: str) -> tuple[Any | None, Any | None]:
        try:
            from importlib import import_module

            api = import_module("local_ai_hub.project_config")
        except ModuleNotFoundError as exc:
            if exc.name == "local_ai_hub.project_config":
                return None, None
            raise
        state_dir = self.config.get("server", {}).get("state_dir", "state")
        return api, api.resolve_project_context(root, state_dir)

    @staticmethod
    def _language_for_path(path: str, settings: Any | None) -> str:
        from .treesitter_parser import language_for_path
        suffix = Path(path).suffix.lower()
        overrides = getattr(settings, "language_overrides", {}) if settings is not None else {}
        for language, override in overrides.items() if hasattr(overrides, "items") else ():
            extensions = override.get("text_extensions", ()) if hasattr(override, "get") else ()
            if suffix in {str(extension).lower() for extension in extensions}:
                return str(language).strip().lower()
        if suffix == ".tsx":
            return "tsx"
        return language_for_path(path, CodeIndex._lang(path), settings)

    def _remove_indexed_paths(self, root: str, paths: list[str]) -> None:
        if not paths:
            return
        c_root = canonical_root(root)
        with self._lock, closing(self._connect()) as con, write_transaction(
            con, rollback_label="code index remove paths"
        ):
            for path in paths:
                con.execute("DELETE FROM symbol_trigrams WHERE root=? AND path=?", (c_root, path))
                for table in ("files", "symbols", "refs", "edges", "file_usage"):
                    con.execute(f"DELETE FROM {table} WHERE root=? AND path=?", (c_root, path))
        self._status_cache.pop(c_root, None)
        self._advance_query_cache_generation()

    def _parse_python(self, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        max_file_bytes = getattr(getattr(self, "repo_tools", None), "max_file_bytes", 2_000_000) or 2_000_000
        if len(text) > max_file_bytes or len(text.encode("utf-8")) > max_file_bytes:
            return [], [], []
        syms: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return syms, refs, edges

        stack: list[str] = []
        scope_kinds: list[str] = []
        overloads: dict[str, int] = {}

        def is_tool_decorator(node: ast.AST) -> bool:
            target = node.func if isinstance(node, ast.Call) else node
            name = target.id if isinstance(target, ast.Name) else target.attr if isinstance(target, ast.Attribute) else ""
            return name == "tool" or name.endswith("_tool")

        class V(ast.NodeVisitor):
            def visit_ClassDef(s, n):
                container = "/".join(stack)
                name_path = (container + "/" if container else "") + n.name
                doc = ast.get_docstring(n) or ""
                doc_summary = doc.strip().splitlines()[0] if doc.strip() else ""
                bases = [ast.unparse(b) for b in n.bases]

                syms.append({
                    "name": n.name,
                    "kind": "class",
                    "line": n.lineno,
                    "end_line": getattr(n, "end_lineno", n.lineno),
                    "container": container,
                    "name_path": name_path,
                    "signature": f"class {n.name}({', '.join(bases)})" if bases else f"class {n.name}",
                    "access": "public" if not n.name.startswith("_") else "private",
                    "docstring": doc_summary[:200],
                })
                for b in bases:
                    edges.append({"src": name_path, "dst": b, "kind": "inherits", "line": n.lineno})

                stack.append(n.name)
                scope_kinds.append("class")
                s.generic_visit(n)
                scope_kinds.pop()
                stack.pop()

            def visit_FunctionDef(s, n):
                container = "/".join(stack)
                base_name_path = (container + "/" if container else "") + n.name
                idx = overloads.get(base_name_path, 0)
                overloads[base_name_path] = idx + 1
                name_path = base_name_path if idx == 0 else f"{base_name_path}[{idx}]"
                doc = ast.get_docstring(n) or ""
                doc_summary = doc.strip().splitlines()[0] if doc.strip() else ""

                try:
                    args_str = ast.unparse(n.args) if getattr(n, "args", None) else ""
                except Exception:
                    args_str = ", ".join(a.arg for a in n.args.args)
                try:
                    ret = ast.unparse(n.returns) if getattr(n, "returns", None) else ""
                except Exception:
                    ret = ""
                fn_kw = "async def" if isinstance(n, ast.AsyncFunctionDef) else "def"
                sig = f"{fn_kw} {n.name}({args_str})" + (f" -> {ret}" if ret else "")

                is_method = bool(scope_kinds) and scope_kinds[-1] == "class"
                kind = "method" if is_method else "function"
                if any(isinstance(d, ast.Name) and d.id == "property" for d in n.decorator_list):
                    kind = "property"

                syms.append({
                    "name": n.name,
                    "kind": kind,
                    "line": n.lineno,
                    "end_line": getattr(n, "end_lineno", n.lineno),
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public" if not n.name.startswith("_") else "private",
                    "docstring": doc_summary[:200],
                    "tool_entrypoint": any(is_tool_decorator(d) for d in n.decorator_list),
                })

                stack.append(n.name)
                scope_kinds.append("function")
                s.generic_visit(n)
                scope_kinds.pop()
                stack.pop()

            def visit_AsyncFunctionDef(s, n):
                s.visit_FunctionDef(n)

            def visit_Call(s, n):
                name = ""
                if isinstance(n.func, ast.Name):
                    name = n.func.id
                elif isinstance(n.func, ast.Attribute):
                    name = n.func.attr
                if name:
                    refs.append({"name": name, "line": getattr(n, "lineno", 0), "kind": "call"})
                    edges.append({"src": "/".join(stack) or "<module>", "dst": name, "kind": "calls", "line": getattr(n, "lineno", 0)})
                s.generic_visit(n)

            def visit_Import(s, n):
                for a in n.names:
                    edges.append({"src": "<module>", "dst": a.name, "kind": "imports", "line": n.lineno})

            def visit_ImportFrom(s, n):
                module = "." * n.level + (n.module or "")
                targets = {module} if module else set()
                for alias in n.names:
                    if alias.name != "*":
                        separator = "" if not module or module.endswith(".") else "."
                        targets.add(f"{module}{separator}{alias.name}")
                for target in sorted(targets):
                    edges.append({"src": "<module>", "dst": target, "kind": "imports", "line": n.lineno})

        V().visit(tree)
        return syms, refs, edges

    @staticmethod
    def _brace_metadata(lines: list[str]) -> tuple[dict[int, int], list[int | None]]:
        """Build brace pairs and next-opening positions in one linear pass.

        End-line metadata is only informational, but repeatedly scanning hundreds
        of lines for every symbol made large C#/JS files quadratic to parse.
        """
        pairs: dict[int, int] = {}
        stack: list[int] = []
        has_open = ["{" in line.split("//", 1)[0] for line in lines]
        for index, line in enumerate(lines):
            for char in line.split("//", 1)[0]:
                if char == "{":
                    stack.append(index)
                elif char == "}" and stack:
                    pairs[stack.pop()] = index
        next_open: list[int | None] = [None] * len(lines)
        nearest: int | None = None
        for index in range(len(lines) - 1, -1, -1):
            if has_open[index]:
                nearest = index
            next_open[index] = nearest
        return pairs, next_open

    @staticmethod
    def _block_end_line(start_index: int, pairs: dict[int, int], next_open: list[int | None], max_lines: int) -> int:
        opening = next_open[start_index] if 0 <= start_index < len(next_open) else None
        if opening is None or opening - start_index >= max_lines:
            return start_index + 1
        closing = pairs.get(opening)
        return (closing + 1) if closing is not None else start_index + 1

    @staticmethod
    def _call_owners_by_line(symbols: list[dict[str, Any]], line_count: int) -> list[str]:
        """Map source lines to the narrowest enclosing fallback function symbol."""
        function_kinds = {"function", "method", "constructor", "func", "fn"}
        starts: dict[int, list[dict[str, Any]]] = {}
        for symbol in symbols:
            start = int(symbol.get("line", 0))
            end = int(symbol.get("end_line", 0))
            if str(symbol.get("kind", "")).lower() in function_kinds and 1 <= start <= end <= line_count:
                starts.setdefault(start, []).append(symbol)

        owners = ["<module>"] * (line_count + 1)
        active: list[dict[str, Any]] = []
        for line in range(1, line_count + 1):
            active = [symbol for symbol in active if int(symbol.get("end_line", 0)) >= line]
            active.extend(starts.get(line, ()))
            if active:
                owner = min(
                    active,
                    key=lambda symbol: (
                        int(symbol.get("end_line", 0)) - int(symbol.get("line", 0)),
                        -int(symbol.get("line", 0)),
                    ),
                )
                owners[line] = str(owner.get("name_path") or owner.get("name") or "<module>")
        return owners

    def _parse_csharp(self, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        syms: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        lines = _mask_non_code(text, "csharp").splitlines()
        brace_pairs, next_open = self._brace_metadata(lines)

        class_re = re.compile(
            r"^\s*(?:\[[^\]]+\]\s*)*(?:(public|private|protected|internal|static|abstract|sealed|partial)\s+)*(class|interface|struct|enum|record)\s+([A-Za-z0-9_]+)(?:<[^>]+>)?(?:\s*:\s*([A-Za-z0-9_,\s<>]+))?",
            re.M,
        )
        method_re = re.compile(
            r"^\s*(?:\[[^\]]+\]\s*)*(?:(public|private|protected|internal|static|virtual|override|abstract|async|sealed)\s+)*(?:([A-Za-z0-9_<>\[\]?]+)\s+)?([A-Za-z0-9_]+)\s*\(([^;{}]*)\)\s*(?:where\s+.*?)?(?:\{|=>|;)",
            re.M,
        )
        prop_re = re.compile(
            r"^\s*(?:(public|private|protected|internal|static|virtual|override|abstract)\s+)+([A-Za-z0-9_<>\[\]?]+)\s+([A-Za-z0-9_]+)\s*\{[^}]*\}",
            re.M,
        )
        using_re = re.compile(r"^\s*using\s+(?:static\s+)?([A-Za-z0-9_.]+);")

        container_stack: list[tuple[str, str, int, int]] = []
        overloads: dict[str, int] = {}
        class_names: set[str] = set()

        for i, line in enumerate(lines, 1):
            um = using_re.match(line)
            if um:
                edges.append({"src": "<module>", "dst": um.group(1), "kind": "imports", "line": i})

        for i, line in enumerate(lines, 1):
            container_stack = [c for c in container_stack if c[3] >= i]
            curr_container = "/".join(c[0] for c in container_stack)

            cm = class_re.match(line)
            if cm:
                access = cm.group(1) or "internal"
                kind = cm.group(2)
                name = cm.group(3)
                class_names.add(name)
                heritage = cm.group(4) or ""

                end_l = self._block_end_line(i - 1, brace_pairs, next_open, 3500)

                container_stack.append((name, kind, i, end_l))
                name_path = (curr_container + "/" if curr_container else "") + name

                doc = ""
                if i > 1:
                    prev = lines[i - 2].strip()
                    if prev.startswith("///"):
                        doc = re.sub(r"<[^>]+>", "", prev.replace("///", "")).strip()

                syms.append({
                    "name": name,
                    "kind": kind,
                    "line": i,
                    "end_line": end_l,
                    "container": curr_container,
                    "name_path": name_path,
                    "signature": f"{access} {kind} {name}" + (f" : {heritage.strip()}" if heritage else ""),
                    "access": access,
                    "docstring": doc[:200],
                })

                if heritage:
                    for base in heritage.split(","):
                        b = base.strip().split("<")[0].strip()
                        if b:
                            edges.append({"src": name_path, "dst": b, "kind": "inherits" if "class" in kind else "implements", "line": i})
                curr_container = "/".join(c[0] for c in container_stack)
                method_text = line[cm.end():]
                class_body_open = method_text.find("{")
                if class_body_open >= 0:
                    method_text = method_text[class_body_open + 1:]
            else:
                method_text = line

            if not cm and i < len(lines) and re.match(r"^\s*\{", lines[i]):
                method_text += "\n" + lines[i]
            mm = method_re.match(method_text)
            if (
                mm
                and not mm.group(2)
                and (mm.group(3) != curr_container.rsplit("/", 1)[-1] or "{" not in method_text)
            ):
                mm = None
            if mm and mm.group(3) not in _CONTROL_NAMES:
                access = mm.group(1) or "private"
                ret_type = mm.group(2) or "void"
                name = mm.group(3)
                params = mm.group(4) or ""

                end_l = i
                if "{" in method_text:
                    opening = i - 1 if "{" in line else i
                    closing = brace_pairs.get(opening)
                    if closing is not None and closing - (i - 1) < 800:
                        end_l = closing + 1
                elif "=>" in method_text:
                    end_l = max(end_l, _arrow_expression_end_line(lines, i - 1, method_text.find("=>")) + 1)

                base_name_path = (curr_container + "/" if curr_container else "") + name
                idx = overloads.get(base_name_path, 0)
                overloads[base_name_path] = idx + 1
                name_path = base_name_path if idx == 0 else f"{base_name_path}[{idx}]"

                syms.append({
                    "name": name,
                    "kind": "method" if curr_container else "function",
                    "line": i,
                    "end_line": max(i, end_l),
                    "container": curr_container,
                    "name_path": name_path,
                    "signature": f"{access} {ret_type} {name}({params.strip()})",
                    "access": access,
                    "docstring": "",
                })

            pm = prop_re.match(line)
            if pm:
                access = pm.group(1)
                prop_type = pm.group(2)
                prop_name = pm.group(3)
                name_path = (curr_container + "/" if curr_container else "") + prop_name
                syms.append({
                    "name": prop_name,
                    "kind": "property",
                    "line": i,
                    "end_line": i,
                    "container": curr_container,
                    "name_path": name_path,
                    "signature": f"{access} {prop_type} {prop_name} {{ get; set; }}",
                    "access": access,
                    "docstring": "",
                })

        for symbol in syms:
            if _callable_needs_close_position(lines, symbol):
                close_position = _callable_block_close_position(lines, symbol)
                if close_position is not None:
                    symbol["_body_close_position"] = close_position

        call_pattern = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$]{2,})\s*\(")
        for i, line in enumerate(lines, 1):
            cleaned = line
            declaration_spans = _declaration_call_spans(cleaned)
            for m in call_pattern.finditer(cleaned):
                cname = m.group(1)
                if cname.lower() not in _CONTROL_NAMES and m.span(1) not in declaration_spans:
                    refs.append({"name": cname, "line": i, "kind": "call"})
                    edges.append({
                        "src": _call_edge_source(syms, i, column=m.start(1), source_line=line),
                        "dst": cname,
                        "kind": "calls",
                        "line": i,
                    })

        for symbol in syms:
            symbol.pop("_body_close_position", None)
        return syms, refs, edges

    def _parse_generic(self, text: str, lang: str = "generic") -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        syms: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        raw_lines = text.splitlines()
        lines = _mask_non_code(text, lang).splitlines()
        brace_pairs, next_open = self._brace_metadata(lines)

        ns_pattern = re.compile(r"^\s*namespace\s+([A-Za-z0-9_\\]+)")
        curr_namespace = ""
        for line in lines:
            nm = ns_pattern.match(line)
            if nm:
                curr_namespace = nm.group(1).rstrip(";")
                break

        raw_syms: list[dict[str, Any]] = []
        for i, line in enumerate(lines, 1):
            m = GENERIC_DEF.match(line)
            declarations: list[tuple[str, str]] = []
            if m:
                declarations.append((m.group(1), m.group(2)))
            else:
                for pattern in (ARROW_DEF, GO_METHOD, TYPED_METHOD, JS_METHOD):
                    mm = pattern.search(line) if pattern is TYPED_METHOD else pattern.match(line)
                    if mm and mm.group(1).lower() not in _CONTROL_NAMES:
                        declarations.append(("function", mm.group(1)))
                        break
            if "=>" in line:
                known_names = {name for _kind, name in declarations}
                declarations.extend(
                    ("function", match.group(1))
                    for match in INLINE_ARROW_DEF.finditer(line)
                    if match.group(1) not in known_names
                )
            raw_sig = raw_lines[i - 1].strip() if i - 1 < len(raw_lines) else line.strip()
            # Keep a terminal arrow: multiline expression-body call ownership
            # uses it to stop at the body's terminating semicolon.
            clean_sig = re.sub(r"\s*(?:\{|;)\s*$", "", raw_sig)[:160]
            for kind, name in declarations:
                raw_syms.append({
                    "name": name,
                    "kind": kind,
                    "line": i,
                    "end_line": i,
                    "container": curr_namespace,
                    "name_path": f"{curr_namespace}\\{name}" if curr_namespace else name,
                    "signature": clean_sig,
                    "access": "public",
                    "docstring": "",
                })

            im = IMPORT.match(raw_lines[i - 1]) if line.strip() else None
            if im:
                dst = next((x for x in im.groups() if x), "")
                edges.append({"src": "<module>", "dst": dst, "kind": "imports", "line": i})

        for s in raw_syms:
            start_l = s["line"] - 1
            declaration_line = lines[start_l] if 0 <= start_l < len(lines) else str(s.get("signature", ""))
            arrow_offset = declaration_line.find("=>")
            if arrow_offset >= 0:
                body = declaration_line[arrow_offset + 2:].strip()
                if not body and start_l + 1 < len(lines):
                    body = lines[start_l + 1].strip()
                if body and not body.startswith("{"):
                    end_l = _arrow_expression_end_line(lines, start_l, arrow_offset) + 1
                elif not body:
                    end_l = start_l + 1
                else:
                    end_l = self._block_end_line(start_l, brace_pairs, next_open, 2500)
            else:
                end_l = self._block_end_line(start_l, brace_pairs, next_open, 2500)
            s["end_line"] = max(s["line"], end_l)
            if _callable_needs_close_position(lines, s):
                close_position = _callable_block_close_position(lines, s)
                if close_position is not None:
                    s["_body_close_position"] = close_position
            syms.append(s)

        call_re = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$]{2,})\s*\(")
        for i, line in enumerate(lines, 1):
            declaration_spans = _declaration_call_spans(line)
            for m in call_re.finditer(line):
                name = m.group(1)
                if name.lower() not in _CONTROL_NAMES and m.span(1) not in declaration_spans:
                    refs.append({"name": name, "line": i, "kind": "call"})
                    edges.append({
                        "src": _call_edge_source(syms, i, column=m.start(1), source_line=line),
                        "dst": name,
                        "kind": "calls",
                        "line": i,
                    })

        for symbol in syms:
            symbol.pop("_body_close_position", None)
        return syms, refs, edges

    def _tree_source_key(self, root: str, path: str) -> str:
        return stable_hash({"database": str(self.db_path.resolve()), "root": root,
                            "path": path, "analyzer": _PARSER_ANALYZER_VERSION})

    @staticmethod
    def _sync_file_rows(con: sqlite3.Connection, table: str, root: str, path: str,
                        rows: list[tuple[Any, ...]]) -> dict[str, int]:
        """Retain identical metadata rows, including duplicate reference occurrences."""
        columns = {
            "symbols": "name,kind,line,end_line,container,name_path,signature,access,docstring",
            "refs": "name,line,kind",
            "edges": "src,dst,src_name,dst_name,kind,line",
        }[table]
        if table == "symbols":
            # Match INSERT OR REPLACE's last occurrence for the existing primary key.
            rows = list({(row[5], row[2]): row for row in rows}.values())
        wanted = Counter(rows)
        removed: list[tuple[int]] = []
        retained = 0
        for old in con.execute(f"SELECT rowid,{columns} FROM {table} WHERE root=? AND path=?", (root, path)):
            value = tuple(old)[1:]
            if wanted[value]:
                wanted[value] -= 1
                retained += 1
            else:
                removed.append((old[0],))
        con.executemany(f"DELETE FROM {table} WHERE rowid=?", removed)
        added = [(root, path, *value) for value, count in wanted.items() for _ in range(count)]
        placeholders = ",".join("?" for _ in range(len(columns.split(",")) + 2))
        con.executemany(f"INSERT INTO {table}(root,path,{columns}) VALUES({placeholders})", added)
        return {"retained": retained, "deleted": len(removed), "inserted": len(added)}

    @staticmethod
    def _replace_symbol_trigrams(con: sqlite3.Connection, root: str, paths: list[str]) -> None:
        """Rebuild searchable trigrams from the symbol rows in the current transaction."""
        for path in dict.fromkeys(paths):
            con.execute("DELETE FROM symbol_trigrams WHERE root=? AND path=?", (root, path))
            tool_symbols: set[tuple[str, int]] = set()
            cached = con.execute(
                "SELECT p.payload_json FROM files f JOIN parse_blobs p "
                "ON p.content_hash=f.content_hash AND p.language=f.language AND p.analyzer_version=f.analyzer_version "
                "WHERE f.root=? AND f.path=? AND f.analyzer_version=?",
                (root, path, _PARSER_ANALYZER_VERSION),
            ).fetchone()
            if cached:
                try:
                    payload = json.loads(cached[0])
                    tool_symbols = {(item["name"], item["line"]) for item in payload.get("symbols", [])
                                    if item.get("tool_entrypoint") is True}
                except (ValueError, TypeError, AttributeError, KeyError):
                    # Missing or malformed optional parse evidence cannot assert registration.
                    tool_symbols = set()
            additions: list[tuple[str, str, int, str, str]] = []
            rows = con.execute(
                "SELECT rowid,name,name_path,container,path,docstring,line FROM symbols WHERE root=? AND path=?",
                (root, path),
            )
            for row in rows:
                symbol_rowid = int(row[0])
                if (str(row[1]), row[6]) in tool_symbols:
                    additions.append((root, path, symbol_rowid, "tool_entrypoint", "too"))
                for field, raw in zip(("name", "name_path", "container", "path", "docstring"), row[1:6]):
                    value = str(raw or "").lower()
                    if len(value) < 3:
                        continue
                    for offset in range(len(value) - 2):
                        additions.append((root, path, symbol_rowid, field, value[offset:offset + 3]))
                        if len(additions) == 2048:
                            con.executemany(
                                "INSERT OR IGNORE INTO symbol_trigrams(root,path,symbol_rowid,field,gram) VALUES(?,?,?,?,?)",
                                additions,
                            )
                            additions.clear()
            if additions:
                con.executemany(
                    "INSERT OR IGNORE INTO symbol_trigrams(root,path,symbol_rowid,field,gram) VALUES(?,?,?,?,?)",
                    additions,
                )

    def _parse_file_content_report(
        self, text: str, lang: str, *, source_key: str | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        parser_report: dict[str, Any] = {
            "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        }
        try:
            from .treesitter_parser import parse_treesitter_with_status
            parser_report = (parse_treesitter_with_status(text, lang, source_key=source_key)
                             if source_key is not None else parse_treesitter_with_status(text, lang))
            ts_res = parser_report.get("result")
            if ts_res is not None and (ts_res[0] or ts_res[2]):
                if lang == "python":
                    # Native parsers can classify every nested callable in a class
                    # as a method and omit docstrings. Python's own AST supplies
                    # lexical kind and documentation for the same exact definition.
                    python_symbols, _, _ = self._parse_python(text)
                    metadata = {(item["name"], item["line"]): item for item in python_symbols}
                    corrected = []
                    for symbol in ts_res[0]:
                        symbol = dict(symbol)
                        authoritative = metadata.get((symbol.get("name"), symbol.get("line")))
                        if authoritative is not None:
                            symbol["kind"] = authoritative["kind"]
                            symbol["docstring"] = authoritative["docstring"]
                            if authoritative.get("tool_entrypoint") is True:
                                symbol["tool_entrypoint"] = True
                        corrected.append(symbol)
                    ts_res = (corrected, ts_res[1], ts_res[2])
                diagnostic = {
                    "status": str(parser_report.get("status") or "unknown"),
                    "parser": str(parser_report.get("parser") or "tree_sitter"),
                    "fallback_used": False,
                    "syntax_error_count": int(parser_report.get("syntax_error_count", 0) or 0),
                    "syntax_error_count_truncated": bool(parser_report.get("syntax_error_count_truncated", False)),
                }
                for field in ("incremental", "tree_cache_hit", "tree_reused", "edit", "incremental_fallback"):
                    if field in parser_report:
                        diagnostic[field] = parser_report[field]
                return (*ts_res, diagnostic)
        except Exception as exc:
            parser_report = {
                "status": "failed", "parser": "tree_sitter",
                "fallback_reason": "parser_error", "error_type": type(exc).__name__,
                "syntax_error_count": 0,
            }

        if lang == "python":
            parsed = self._parse_python(text)
        elif lang == "csharp":
            parsed = self._parse_csharp(text)
        else:
            parsed = self._parse_generic(text, lang)
        syntax_error_count = int(parser_report.get("syntax_error_count", 0) or 0)
        diagnostic = {
            "status": "syntax_error" if syntax_error_count else "fallback",
            "parser": str(parser_report.get("parser") or "tree_sitter"),
            "fallback_used": True,
            "fallback_reason": str(parser_report.get("fallback_reason") or "no_extracted_nodes"),
            "syntax_error_count": syntax_error_count,
            "syntax_error_count_truncated": bool(parser_report.get("syntax_error_count_truncated", False)),
        }
        if parser_report.get("error_type"):
            diagnostic["error_type"] = str(parser_report["error_type"])
        if "worker_cleanup_confirmed" in parser_report:
            diagnostic["worker_cleanup_confirmed"] = bool(parser_report["worker_cleanup_confirmed"])
        return (*parsed, diagnostic)

    def _parse_file_content(self, text: str, lang: str, *, source_key: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        if source_key is not None:
            try:
                symbols, refs, edges, diagnostic = self._parse_file_content_report(text, lang, source_key=source_key)
            except TypeError:
                symbols, refs, edges, diagnostic = self._parse_file_content_report(text, lang)
        else:
            symbols, refs, edges, diagnostic = self._parse_file_content_report(text, lang)
        self._parse_diagnostic.value = diagnostic
        return symbols, refs, edges

    def _parse_blob_get(self, content_hash: str, language: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
        cached = self._parse_blob_get_with_report(content_hash, language)
        return cached[0] if cached is not None else None

    def _parse_blob_get_with_report(
        self, content_hash: str, language: str
    ) -> tuple[tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]] | None:
        key = f"{content_hash}:{_PARSER_ANALYZER_VERSION}:{language}"
        cached = self._parse_blob_l1.get(key)
        if cached is not None:
            if len(cached) >= 4 and isinstance(cached[3], dict):
                return (cached[0], cached[1], cached[2]), dict(cached[3])
            return (cached[0], cached[1], cached[2]), {"status": "unknown", "parser": "unknown", "fallback_used": False}
        try:
            with self._lock, closing(self._connect()) as con:
                row = con.execute("SELECT payload_json FROM parse_blobs WHERE content_hash=? AND analyzer_version=? AND language=?", (content_hash, _PARSER_ANALYZER_VERSION, language)).fetchone()
            if row:
                data = json.loads(str(row[0]))
                if isinstance(data, dict):
                    res = (list(data.get("symbols", [])), list(data.get("refs", [])), list(data.get("edges", [])))
                    diagnostic = data.get("parse_outcome")
                    if not isinstance(diagnostic, dict):
                        diagnostic = {"status": "unknown", "parser": "unknown", "fallback_used": False}
                    self._parse_blob_l1.set(key, (*res, dict(diagnostic)))
                    return res, dict(diagnostic)
        except Exception:
            pass
        return None

    def _parse_blob_put(
        self, content_hash: str, language: str,
        syms: list[dict[str, Any]], refs: list[dict[str, Any]], edges: list[dict[str, Any]],
        parse_outcome: dict[str, Any] | None = None,
    ) -> None:
        key = f"{content_hash}:{_PARSER_ANALYZER_VERSION}:{language}"
        diagnostic = dict(parse_outcome or {"status": "unknown", "parser": "unknown", "fallback_used": False})
        self._parse_blob_l1.set(key, (syms, refs, edges, diagnostic))
        try:
            payload = json_dumps({"symbols": syms, "refs": refs, "edges": edges, "parse_outcome": diagnostic}, ensure_ascii=False, separators=(",", ":"))
            with self._lock, closing(self._connect()) as con:
                con.execute("INSERT OR REPLACE INTO parse_blobs(content_hash, analyzer_version, language, payload_json, updated_at) VALUES(?,?,?,?,?)", (content_hash, _PARSER_ANALYZER_VERSION, language, payload, time.time()))
                count = int(con.execute("SELECT COUNT(*) FROM parse_blobs").fetchone()[0])
                if count > self.parse_blob_max:
                    con.execute("DELETE FROM parse_blobs WHERE rowid IN (SELECT rowid FROM parse_blobs ORDER BY updated_at ASC LIMIT ?)", (max(100, count - self.parse_blob_max),))
                con.commit()
        except Exception:
            pass

    def files_needing_reindex(
        self, root: str, items: list[tuple[str, str]], *, only_existing: bool = False,
    ) -> list[tuple[str, str]]:
        """Select paths with changed content or stale parser analyzer versions."""
        if type(only_existing) is not bool:
            raise TypeError("only_existing must be a boolean")
        c_root = canonical_root(root)
        if not items:
            return []
        api, project_context = self._project_config_context(c_root)
        settings = project_context.settings if project_context is not None else None
        if api is not None and settings is not None and not api.phase_is_allowed(settings, "call_graph"):
            return []
        path_policy = _resolve_code_index_path_policy(api, c_root, settings)
        existing: dict[str, tuple[str, str, str, int | None, int | None]] = {}
        with self._lock, closing(self._connect()) as con:
            con.execute("BEGIN")
            for batch in sqlite_batches(list(dict.fromkeys(str(path) for path, _ in items))):
                placeholders = ",".join("?" for _ in batch)
                rows = con.execute(
                    f"SELECT path,content_hash,analyzer_version,language,mtime_ns,size_bytes FROM files WHERE root=? AND path IN ({placeholders})",
                    (c_root, *batch),
                ).fetchall()
                for row in rows:
                    existing[str(row["path"])] = (
                        str(row["content_hash"] or ""),
                        str(row["analyzer_version"] or ""),
                        str(row["language"] or ""),
                        row["mtime_ns"],
                        row["size_bytes"],
                    )
        pending = []
        for path, content_hash in items:
            path = str(path)
            target = Path(c_root) / path
            try:
                target_stat = target.stat()
                size_bytes = target_stat.st_size
            except OSError:
                target_stat = None
                size_bytes = None
            if api is not None and settings is not None:
                if target_stat is None:
                    continue
                if not path_policy.allows(
                    target, phase="call_graph", size_bytes=size_bytes,
                ):
                    continue
            language = self._language_for_path(path, settings)
            ex = existing.get(path)
            if ex is None and only_existing:
                continue
            if ex is not None:
                if (ex[0], ex[1], ex[2]) == (str(content_hash), _PARSER_ANALYZER_VERSION, language):
                    continue
                is_uncomparable_hash = (
                    not content_hash
                    or not ex[0]
                    or (str(content_hash).startswith("git:") != str(ex[0]).startswith("git:"))
                )
                if (
                    is_uncomparable_hash
                    and target_stat is not None
                    and ex[1] == _PARSER_ANALYZER_VERSION
                    and ex[2] == language
                    and ex[3] is not None
                    and ex[4] is not None
                    and target_stat.st_mtime_ns == ex[3]
                    and target_stat.st_size == ex[4]
                ):
                    continue
            pending.append((path, str(content_hash)))
        return pending

    def _mark_file_unindexable(self, root: str, path: str, language: str) -> dict[str, Any]:
        """Retain authorized path metadata while removing stale parsed data."""
        updated_at = time.time()
        with self._write_lock, self._lock:
            with closing(self._connect()) as con:
                existing = con.execute(
                    "SELECT 1 FROM files WHERE root=? AND path=?", (root, path),
                ).fetchone() is not None
            budget: dict[str, Any] | None = None
            if not existing:
                budget = self._reserve_write_budget(root, 8192)
                if not budget["success"]:
                    return {
                        "success": False, "budget_limited": True, "coverage_complete": False,
                        "reason": "code index size limit", "budget": budget,
                    }
            with closing(self._connect()) as con:
                with write_transaction(
                    con, max_duration_seconds=5.0, rollback_label="code index unindexable file"
                ):
                    con.execute("DELETE FROM symbol_trigrams WHERE root=? AND path=?", (root, path))
                    for table in ("symbols", "refs", "edges"):
                        con.execute(f"DELETE FROM {table} WHERE root=? AND path=?", (root, path))
                    con.execute(
                        "INSERT INTO files(root,path,content_hash,analyzer_version,language,updated_at,mtime_ns,size_bytes) "
                        "VALUES(?,?,NULL,NULL,?,?,NULL,NULL) "
                        "ON CONFLICT(root,path) DO UPDATE SET content_hash=NULL, "
                        "analyzer_version=NULL, language=excluded.language, updated_at=excluded.updated_at, "
                        "mtime_ns=NULL, size_bytes=NULL",
                        (root, path, language, updated_at),
                    )
        self._advance_query_cache_generation()
        self._status_cache.pop(root, None)
        return {"success": True, "budget_limited": False, "budget": budget}

    @staticmethod
    def _file_stat_is_current(path: Path, expected_stat: Any) -> bool:
        try:
            current_stat = path.stat()
        except OSError:
            return False
        return (
            current_stat.st_mtime_ns == expected_stat.st_mtime_ns
            and current_stat.st_size == expected_stat.st_size
        )

    def update_file(self, root: str, path: str, content_hash: str | None = None) -> dict[str, Any]:
        base = Path(canonical_root(root))
        target = (base / path).resolve(strict=False)
        try:
            target.relative_to(base)
        except ValueError:
            return {"success": False, "error": "invalid path"}
        api, project_context = self._project_config_context(str(base))
        settings = project_context.settings if project_context is not None else None
        if api is not None and settings is not None and not api.phase_is_allowed(settings, "call_graph"):
            self.prune(str(base), [])
            return {"success": True, "skipped": True, "path": path, "reason": "project phase disabled"}
        if api is not None and settings is not None:
            try:
                size_bytes = target.stat().st_size if target.is_file() else None
            except OSError:
                size_bytes = None
            if not api.path_is_allowed(
                str(base), target, settings, phase="call_graph", size_bytes=size_bytes,
            ):
                self._remove_indexed_paths(str(base), [path])
                return {"success": True, "skipped": True, "path": path, "reason": "project path excluded"}
        if not target.is_file():
            with self._lock, closing(self._connect()) as con:
                con.execute("DELETE FROM symbol_trigrams WHERE root=? AND path=?", (str(base), path))
                for t in ("files", "symbols", "refs", "edges", "file_usage"):
                    con.execute(f"DELETE FROM {t} WHERE root=? AND path=?", (str(base), path))
                con.commit()
            self._advance_query_cache_generation()
            self._status_cache.pop(str(base), None)
            return {"success": True, "deleted": True}

        try:
            target_stat = target.stat()
        except OSError:
            return {"success": False, "error": "file unavailable"}
        lang = self._language_for_path(path, settings)
        if target_stat.st_size > self.repo_tools.max_file_bytes:
            marked = self._mark_file_unindexable(str(base), path, lang)
            if not marked["success"]:
                return {"path": path, **marked}
            return {"success": True, "skipped": True, "path": path, "reason": "file exceeds max indexable size"}

        # Unchanged size/mtime does not establish unchanged content. Reuse the
        # existing content-addressed parse only after the bounded snapshot read.
        try:
            digest, lines = self.repo_tools._read_snapshot(
                target, stat=target_stat, force=True, max_bytes=self.repo_tools.max_file_bytes,
            )
        except FileTooLargeError:
            marked = self._mark_file_unindexable(str(base), path, lang)
            if not marked["success"]:
                return {"path": path, **marked}
            return {"success": True, "skipped": True, "path": path, "reason": "file exceeds max indexable size"}
        content_hash = digest
        stat_is_current = self._file_stat_is_current(target, target_stat)
        with self._lock, closing(self._connect()) as con:
            row = con.execute("SELECT content_hash,analyzer_version,language FROM files WHERE root=? AND path=?", (str(base), path)).fetchone()
            if row and row[0] == content_hash and str(row[1] or "") == _PARSER_ANALYZER_VERSION and str(row[2] or "") == lang:
                if stat_is_current:
                    con.execute(
                        "UPDATE files SET mtime_ns=?,size_bytes=? WHERE root=? AND path=?",
                        (target_stat.st_mtime_ns, target_stat.st_size, str(base), path),
                    )
                    con.commit()
                cached = self._parse_blob_get_with_report(content_hash, lang)
                return {
                    "success": True, "cached": True, "path": path,
                    "parse_outcome": dict(cached[1]) if cached is not None else {"status": "unknown", "parser": "unknown"},
                }

        parsed_with_report = self._parse_blob_get_with_report(content_hash, lang)
        parsed = parsed_with_report[0] if parsed_with_report is not None else None
        parse_blob_rows: list[tuple[Any, ...]] = []
        if parsed is None:
            text = "\n".join(lines)
            syms, refs, edges = self._parse_file_content(text, lang, source_key=self._tree_source_key(str(base), path))
            parse_outcome = dict(getattr(self._parse_diagnostic, "value", {}))
            payload = json_dumps(
                {"symbols": syms, "refs": refs, "edges": edges, "parse_outcome": parse_outcome},
                ensure_ascii=False, separators=(",", ":"),
            )
            parse_blob_rows.append((content_hash, _PARSER_ANALYZER_VERSION, lang, payload, time.time()))
        else:
            syms, refs, edges = parsed
            parse_outcome = parsed_with_report[1]

        budget_symbols = [
            (str(base), path, x["name"], x["kind"], x["line"], x["end_line"], x.get("container", ""),
             x.get("name_path", x["name"]), x.get("signature", ""), x.get("access", "public"), x.get("docstring", ""))
            for x in syms
        ]
        budget_refs = [(str(base), path, x["name"], x["line"], x.get("kind", "call")) for x in refs]
        budget_edges = [
            (str(base), x["src"], x["dst"], _edge_endpoint_name(x["src"]), _edge_endpoint_name(x["dst"]),
             x.get("kind", "reference"), path, x["line"])
            for x in edges
        ]
        growth = self._estimate_write_growth(1, parse_blob_rows, budget_symbols, budget_refs, budget_edges)
        with self._write_lock, self._lock:
            budget = self._reserve_write_budget(str(base), growth)
            if not budget["success"]:
                return {
                    "success": False, "budget_limited": True, "coverage_complete": False,
                    "reason": "code index size limit", "budget": budget,
                }
            if parse_blob_rows:
                self._parse_blob_put(content_hash, lang, syms, refs, edges, parse_outcome)
            with closing(self._connect()) as con:
                with write_transaction(
                    con, max_duration_seconds=5.0, rollback_label="code index update file"
                ):
                    con.execute(
                        "INSERT OR REPLACE INTO files(root,path,content_hash,analyzer_version,language,updated_at,mtime_ns,size_bytes) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (
                            str(base), path, content_hash, _PARSER_ANALYZER_VERSION, lang, time.time(),
                            target_stat.st_mtime_ns if stat_is_current else None,
                            target_stat.st_size if stat_is_current else None,
                        ),
                    )
                    metadata_update = {
                        "symbols": self._sync_file_rows(con, "symbols", str(base), path, [
                            (x["name"], x["kind"], x["line"], x["end_line"], x.get("container", ""),
                             x.get("name_path", x["name"]), x.get("signature", ""), x.get("access", "public"),
                             x.get("docstring", "")) for x in syms]),
                        "refs": self._sync_file_rows(con, "refs", str(base), path, [
                            (x["name"], x["line"], x.get("kind", "call")) for x in refs]),
                        "edges": self._sync_file_rows(con, "edges", str(base), path, [
                            (x["src"], x["dst"], _edge_endpoint_name(x["src"]), _edge_endpoint_name(x["dst"]),
                             x.get("kind", "reference"), x["line"]) for x in edges]),
                    }
                    self._replace_symbol_trigrams(con, str(base), [path])
            post_write_budget = self._reconcile_post_write_budget([(str(base), path)])

        self._advance_query_cache_generation()
        self._status_cache.pop(str(base), None)
        return {
            "success": post_write_budget["success"], "cached": False, "path": path,
            "budget_limited": not post_write_budget["success"],
            "coverage_complete": post_write_budget["success"],
            "symbols": len(syms), "refs": len(refs), "edges": len(edges),
            "parse_outcome": dict(parse_outcome), "budget": budget,
            "post_write_budget": post_write_budget,
            "metadata_update": metadata_update,
        }

    def update_files_batch(self, root: str, items: list[str] | list[tuple[str, str]]) -> dict[str, Any]:
        """Batch-process files with one read phase and one SQLite write transaction."""
        c_root = canonical_root(root)
        base = Path(c_root)
        normalized: list[tuple[str, str | None]] = []
        for item in items:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                normalized.append((str(item[0]), str(item[1]) or None))
            else:
                normalized.append((str(item), None))
        if not normalized:
            return {"success": True, "files_processed": 0, "cached": 0, "symbols": 0, "refs": 0, "edges": 0}

        api, project_context = self._project_config_context(c_root)
        settings = project_context.settings if project_context is not None else None
        if api is not None and settings is not None and not api.phase_is_allowed(settings, "call_graph"):
            self.prune(c_root, [])
            return {"success": True, "files_processed": 0, "cached": 0, "symbols": 0, "refs": 0, "edges": 0, "skipped": len(normalized)}
        path_policy = _resolve_code_index_path_policy(api, c_root, settings)

        existing: dict[str, tuple[str, str, str, int | None, int | None]] = {}
        with self._lock, closing(self._connect()) as con:
            con.execute("BEGIN")
            for batch in sqlite_batches(list(dict.fromkeys(str(path) for path, _ in normalized))):
                placeholders = ",".join("?" for _ in batch)
                rows = con.execute(
                    f"SELECT path,content_hash,analyzer_version,language,mtime_ns,size_bytes FROM files WHERE root=? AND path IN ({placeholders})",
                    (c_root, *batch),
                ).fetchall()
                for row in rows:
                    existing[str(row["path"])] = (
                        str(row["content_hash"] or ""),
                        str(row["analyzer_version"] or ""),
                        str(row["language"] or ""),
                        row["mtime_ns"],
                        row["size_bytes"],
                    )

        blob_map: dict[tuple[str, str], tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]] = {}

        supplied_pairs: list[tuple[str, str]] = []
        for path, supplied_hash in normalized:
            if supplied_hash:
                lang = self._language_for_path(path, settings)
                if existing.get(path, ())[:3] != (supplied_hash, _PARSER_ANALYZER_VERSION, lang):
                    supplied_pairs.append((supplied_hash, lang))
        if supplied_pairs:
            blob_map.update(load_parse_blobs(self, supplied_pairs, _PARSER_ANALYZER_VERSION, sqlite_batches))

        candidates: list[tuple[str, str, str, list[str]]] = []
        file_stats: dict[str, Any] = {}
        cached = 0
        denied_paths: list[str] = []
        deleted_paths: list[tuple[str, str]] = []
        budget_limited_paths: list[str] = []
        for path, supplied_hash in normalized:
            file_path = (base / path).resolve(strict=False)
            try:
                relative_path = file_path.relative_to(base)
            except ValueError:
                continue
            if is_root_archive_path(relative_path):
                denied_paths.append(path)
                continue
            if not file_path.is_file():
                deleted_paths.append((c_root, path))
                continue
            try:
                file_stat = file_path.stat()
            except OSError:
                continue
            if path_policy is not None:
                if not path_policy.allows(
                    file_path, phase="call_graph", size_bytes=file_stat.st_size,
                ):
                    denied_paths.append(path)
                    continue
            lang = self._language_for_path(path, settings)
            if file_stat.st_size > self.repo_tools.max_file_bytes:
                marked = self._mark_file_unindexable(c_root, path, lang)
                if marked.get("budget_limited") is True:
                    budget_limited_paths.append(path)
                continue
            file_stats[path] = file_stat
            if supplied_hash and path not in existing:
                if (supplied_hash, lang) in blob_map:
                    candidates.append((path, supplied_hash, lang, []))
                    continue
            try:
                digest, lines = self.repo_tools._read_snapshot(
                    file_path, stat=file_stat, force=True, max_bytes=self.repo_tools.max_file_bytes,
                )
            except FileTooLargeError:
                marked = self._mark_file_unindexable(c_root, path, lang)
                if marked.get("budget_limited") is True:
                    budget_limited_paths.append(path)
                continue
            except OSError:
                continue
            content_hash = digest
            if existing.get(path, ())[:3] == (content_hash, _PARSER_ANALYZER_VERSION, lang):
                cached += 1
                continue
            candidates.append((path, content_hash, lang, lines))

        self._remove_indexed_paths(c_root, denied_paths)

        if candidates:
            pairs = list(dict.fromkeys((h, lang) for _, h, lang, _ in candidates))
            missing_pairs = [pair for pair in pairs if pair not in blob_map]
            if missing_pairs:
                blob_map.update(load_parse_blobs(self, missing_pairs, _PARSER_ANALYZER_VERSION, sqlite_batches))

        files_to_insert: list[tuple[Any, ...]] = []
        syms_to_insert: list[tuple[Any, ...]] = []
        refs_to_insert: list[tuple[Any, ...]] = []
        edges_to_insert: list[tuple[Any, ...]] = []
        parse_blob_rows: list[tuple[Any, ...]] = []
        paths_to_clean: list[tuple[str, str]] = []
        now = time.time()
        # Tree-sitter parsers are shared per language and guarded by one lock.
        # Threading here queues parses behind that lock and adds scheduler cost;
        # the bounded batch SQL write is where this path gains throughput.
        parsed_candidates = [
            parse_index_candidate(self, candidate, blob_map, c_root, now, _PARSER_ANALYZER_VERSION)
            for candidate in candidates
        ]

        for path, content_hash, lang, syms, refs, edges, row_blob in parsed_candidates:
            if row_blob is not None:
                parse_blob_rows.append(row_blob)
            paths_to_clean.append((c_root, path))
            file_stat = file_stats.get(path)
            stat_is_current = bool(
                file_stat is not None
                and self._file_stat_is_current((base / path).resolve(strict=False), file_stat)
            )
            files_to_insert.append((
                c_root, path, content_hash, _PARSER_ANALYZER_VERSION, lang, now,
                file_stat.st_mtime_ns if stat_is_current else None,
                file_stat.st_size if stat_is_current else None,
            ))
            syms_to_insert.extend((c_root, path, x["name"], x["kind"], x["line"], x["end_line"], x.get("container", ""), x.get("name_path", x["name"]), x.get("signature", ""), x.get("access", "public"), x.get("docstring", "")) for x in syms)
            refs_to_insert.extend((c_root, path, x["name"], x["line"], x.get("kind", "call")) for x in refs)
            edges_to_insert.extend(
                (
                    c_root, x["src"], x["dst"], _edge_endpoint_name(x["src"]),
                    _edge_endpoint_name(x["dst"]), x.get("kind", "reference"), path, x["line"],
                )
                for x in edges
            )

        single_delta = len(files_to_insert) == 1 and not deleted_paths
        metadata_update: dict[str, Any] = {}
        if files_to_insert or deleted_paths:
            growth = self._estimate_write_growth(
                len(files_to_insert), parse_blob_rows, syms_to_insert, refs_to_insert, edges_to_insert,
            )
            with self._write_lock, self._lock:
                budget = self._reserve_write_budget(c_root, growth)
                if not budget["success"]:
                    if deleted_paths:
                        self._remove_indexed_paths(c_root, [path for _root, path in deleted_paths])
                    return {
                        "success": False, "budget_limited": True, "coverage_complete": False,
                        "files_processed": 0, "cached": cached, "reason": "code index size limit",
                        "budget": budget,
                    }
                with closing(self._connect()) as con:
                    with write_transaction(
                        con, max_duration_seconds=5.0, rollback_label="code index batch update"
                    ):
                        if parse_blob_rows:
                            con.executemany("INSERT OR REPLACE INTO parse_blobs(content_hash,analyzer_version,language,payload_json,updated_at) VALUES(?,?,?,?,?)", parse_blob_rows)
                        _IDX_TABLES = frozenset({"symbols", "refs", "edges"})
                        if deleted_paths:
                            con.executemany("DELETE FROM files WHERE root=? AND path=?", deleted_paths)
                            con.executemany("DELETE FROM symbol_trigrams WHERE root=? AND path=?", deleted_paths)
                            for table in ("symbols", "refs", "edges"):
                                assert table in _IDX_TABLES
                                con.executemany(f"DELETE FROM {table} WHERE root=? AND path=?", deleted_paths)  # noqa: S608
                        if not single_delta:
                            for table in ("symbols", "refs", "edges"):
                                assert table in _IDX_TABLES
                                con.executemany(f"DELETE FROM {table} WHERE root=? AND path=?", paths_to_clean)
                        con.executemany(
                            "INSERT OR REPLACE INTO files(root,path,content_hash,analyzer_version,language,updated_at,mtime_ns,size_bytes) "
                            "VALUES(?,?,?,?,?,?,?,?)",
                            files_to_insert,
                        )
                        if single_delta:
                            changed_path = str(files_to_insert[0][1])
                            metadata_update = {
                                "symbols": self._sync_file_rows(con, "symbols", c_root, changed_path,
                                                                [tuple(row[2:]) for row in syms_to_insert]),
                                "refs": self._sync_file_rows(con, "refs", c_root, changed_path,
                                                             [tuple(row[2:]) for row in refs_to_insert]),
                                "edges": self._sync_file_rows(con, "edges", c_root, changed_path,
                                                              [(row[1], row[2], row[3], row[4], row[5], row[7])
                                                       for row in edges_to_insert]),
                            }
                        else:
                            con.executemany("INSERT OR REPLACE INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) VALUES(?,?,?,?,?,?,?,?,?,?,?)", syms_to_insert)
                            con.executemany("INSERT INTO refs(root,path,name,line,kind) VALUES(?,?,?,?,?)", refs_to_insert)
                            con.executemany(
                                "INSERT INTO edges(root,src,dst,src_name,dst_name,kind,path,line) VALUES(?,?,?,?,?,?,?,?)",
                                edges_to_insert,
                            )
                        self._replace_symbol_trigrams(
                            con,
                            c_root,
                            [str(item[1]) for item in files_to_insert],
                        )
                post_write_budget = self._reconcile_post_write_budget(
                    [(c_root, str(item[1])) for item in files_to_insert],
                )
            self._advance_query_cache_generation()
        self._status_cache.pop(c_root, None)
        indexed_paths = [str(item[1]) for item in files_to_insert]
        if files_to_insert and not post_write_budget["success"]:
            budget_limited_paths.extend(
                path for _root, path in post_write_budget.get("missing_paths", [])
                if path not in budget_limited_paths
            )
            budget_limited_paths.extend(
                str(item[1]) for item in files_to_insert
                if str(item[1]) not in budget_limited_paths
            )
        return {
            "success": not (files_to_insert and not post_write_budget["success"]),
            "files_processed": len(files_to_insert), "cached": cached,
            "symbols": len(syms_to_insert), "refs": len(refs_to_insert), "edges": len(edges_to_insert),
            "parse_blob_hits": len(candidates) - len(parse_blob_rows),
            "parse_outcomes": self._parse_outcomes_for_paths(c_root, indexed_paths),
            "metadata_update": metadata_update, "budget": budget if files_to_insert else None,
            "budget_limited": bool(budget_limited_paths) or bool(files_to_insert and not post_write_budget["success"]),
            "budget_limited_paths": budget_limited_paths,
            "coverage_complete": not budget_limited_paths and (not files_to_insert or post_write_budget["success"]),
            "post_write_budget": post_write_budget if files_to_insert else None,
        }

