from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import time
from typing import Any

from .code_index_constants import _PARSER_ANALYZER_VERSION
from .code_index_scoring import _escape_like_literal, _root_archive_path_sql
from .code_index_spans import _edge_endpoint_name
from .process_utils import canonical_root
from .repo_tools import is_root_archive_path
from .search_pagination import pagination_bounds_error
from .sqlite_counts import global_row_counts
from .sqlite_support import is_busy_error


CodeIndex = None


class CodeIndexNavigationMixin:
    def inspect_symbol(self, root: str, symbol_name: str) -> dict[str, Any]:
        decl = self.find_declaration(root, symbol_name)
        if decl.get("success"):
            d = decl["declaration"]
            return {
                "success": True,
                "root": canonical_root(root),
                "name": d["name"],
                "kind": d["kind"],
                "path": d["path"],
                "line": d["line"],
                "end_line": d["end_line"],
                "container": d.get("container", ""),
                "signature": d.get("signature", ""),
                "snippet": d.get("body", ""),
            }
        return {"success": False, "error": f"Symbol '{symbol_name}' not found"}

    def find_dead_code(self, root: str, limit: int = 50) -> dict[str, Any]:
        """Detect unreferenced symbols using the precomputed symbols and refs tables."""
        resolved_root = canonical_root(root)
        try:
            with self._lock, closing(self._connect(register_archive_function=False)) as con:
                con.execute("CREATE TEMP TABLE dead_code_archive_paths(path TEXT PRIMARY KEY)")
                with closing(
                    con.execute(
                        "SELECT path FROM symbols WHERE root=? UNION SELECT path FROM refs WHERE root=?",
                        (resolved_root, resolved_root),
                    )
                ) as path_rows:
                    while path_batch := path_rows.fetchmany(250):
                        con.executemany(
                            "INSERT INTO dead_code_archive_paths(path) VALUES(?)",
                            (
                                (path,)
                                for row in path_batch
                                if is_root_archive_path(path := str(row[0]))
                            ),
                        )
                sql = """
                SELECT s.path, s.name, s.kind, s.line, s.end_line, s.container, s.name_path, s.access
                FROM symbols s
                LEFT JOIN refs r ON s.root = r.root AND s.name = r.name
                    AND NOT EXISTS (
                        SELECT 1 FROM dead_code_archive_paths archived WHERE archived.path = r.path
                    )
                WHERE s.root = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM dead_code_archive_paths archived WHERE archived.path = s.path
                  )
                  AND r.name IS NULL
                  AND s.name NOT IN (
                      'main', 'run', 'cli', 'app', 'handler', '__init__', '__str__', '__repr__',
                      'setUp', 'tearDown', 'setUpClass', 'tearDownClass', 'test'
                  )
                  AND NOT s.name LIKE 'test_%'
                  AND NOT s.path LIKE '%test%'
                ORDER BY s.path, s.line
                LIMIT ?
                """
                rows = con.execute(sql, (resolved_root, max(1, int(limit)))).fetchall()

            dead_symbols = []
            for r in rows:
                dead_symbols.append({
                    "file": r["path"],
                    "path": r["path"],
                    "name": r["name"],
                    "kind": r["kind"],
                    "line": r["line"],
                    "end_line": r["end_line"],
                    "container": r["container"] or "",
                    "name_path": r["name_path"] or r["name"],
                    "access": r["access"] or "public",
                    "reason": "no indexed references found",
                })
            return {
                "success": True,
                "candidate_count": len(dead_symbols),
                "dead_code": dead_symbols,
                "dead_symbols": dead_symbols,
                "indexed": True,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "candidate_count": 0, "dead_code": [], "dead_symbols": []}

    def status(self, root: str | None = None) -> dict[str, Any]:
        self._cache_generation()
        now = time.monotonic()
        key = str(root or "__all__")
        cached = self._status_cache.get(key)
        if cached and now - cached["time"] < 5.0:
            return dict(cached["data"])
        try:
            # Table names are compile-time constants; validate against explicit whitelist
            # before f-string interpolation as defence-in-depth.
            _ALLOWED_TABLES = {"files", "symbols", "refs", "edges"}
            # A fresh WAL reader sees committed counts without waiting for the
            # Python lock held by a large indexing transaction.
            with closing(self._connect()) as con:
                where = " WHERE root=?" if root else ""
                args = (canonical_root(root),) if root else ()
                vals = ({t: int(con.execute(f"SELECT COUNT(*) FROM {t}{where}", args).fetchone()[0])  # noqa: S608
                         for t in _ALLOWED_TABLES} if root else
                        global_row_counts(con, ("files", "symbols", "refs", "edges")))
            res = {"success": True, "healthy": True, **vals}
            self._status_cache[key] = {"time": now, "data": res}
            return res
        except sqlite3.DatabaseError as exc:
            return {"success": False, "healthy": False, "error": str(exc)}

    def find_callers(self, root: str, symbol: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Find all call sites and references to a symbol across repository AST."""
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error, "callers": []}
        if not isinstance(symbol, str) or not symbol.strip():
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": "symbol cannot be empty", "callers": []}
        resolved = canonical_root(root)
        sym = symbol.strip()
        result_limit = limit
        escaped_sym = _escape_like_literal(sym)
        try:
            with closing(self._connect()) as con:
                deadline = time.monotonic() + 1.0
                con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                con.execute("BEGIN")
                index_available = con.execute(
                    f"SELECT 1 FROM files WHERE root=? AND {_root_archive_path_sql('path')} LIMIT 1",
                    (resolved,),
                ).fetchone() is not None
                rows = con.execute(
                    f"""SELECT src, dst, kind, path, line FROM edges
                       WHERE root=? AND kind=? AND dst_name=?
                         AND {_root_archive_path_sql("path")}
                         AND (dst=? OR dst LIKE ? ESCAPE '!' OR dst LIKE ? ESCAPE '!')
                       ORDER BY path, line, src, dst, kind LIMIT ? OFFSET ?""",
                    (
                        resolved, "calls", _edge_endpoint_name(sym), sym,
                        f"%/{escaped_sym}", f"%::{escaped_sym}", result_limit + 1, offset,
                    ),
                ).fetchall()
                con.set_progress_handler(None, 0)
        except sqlite3.DatabaseError as exc:
            busy = is_busy_error(exc)
            return {
                "success": False,
                "status_code": 503 if busy else 500,
                "terminal": not busy,
                "retryable": busy,
                "symbol": sym,
                "callers": [],
                "count": 0,
                "root": resolved,
                "error": str(exc),
                "busy": busy,
                "truncated": False,
                "truncation": {"callers": False},
                "offset": offset,
                "limit": result_limit,
                "coverage": {"complete": False, "returned": 0, "limit": result_limit, "offset": offset},
                "freshness": {"status": "not_checked"},
                "index_available": None,
            }
        truncated = len(rows) > result_limit
        callers = [
            {"caller": str(r["src"]), "callee": str(r["dst"]), "kind": str(r["kind"]), "path": str(r["path"]), "line": int(r["line"])}
            for r in rows[:result_limit]
        ]
        result = {
            "success": True,
            "symbol": sym,
            "callers": callers,
            "caller_count": len(callers),
            "count": len(callers),
            "root": resolved,
            "offset": offset,
            "limit": result_limit,
            "returned_count": len(callers),
            "has_more": truncated,
            "truncated": truncated,
            "truncation": {"callers": truncated},
            "coverage": {"complete": offset == 0 and not truncated, "returned": len(callers), "limit": result_limit, "offset": offset, "scope": "indexed_edges"},
            "freshness": {"status": "not_checked"},
            "index_available": index_available,
        }
        result["coverage"]["index_available"] = index_available
        if not truncated and (offset == 0 or callers):
            result["total_matches"] = offset + len(callers)
        if truncated:
            result["next_offset"] = offset + len(callers)
        return result

    def find_callees(self, root: str, symbol: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Find all functions/methods called by a symbol."""
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error, "callees": []}
        if not isinstance(symbol, str) or not symbol.strip():
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": "symbol cannot be empty", "callees": []}
        resolved = canonical_root(root)
        sym = symbol.strip()
        result_limit = limit
        escaped_sym = _escape_like_literal(sym)
        try:
            with closing(self._connect()) as con:
                deadline = time.monotonic() + 1.0
                con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                con.execute("BEGIN")
                index_available = con.execute(
                    f"SELECT 1 FROM files WHERE root=? AND {_root_archive_path_sql('path')} LIMIT 1",
                    (resolved,),
                ).fetchone() is not None
                rows = con.execute(
                    f"""SELECT src, dst, kind, path, line FROM edges
                       WHERE root=? AND kind=? AND src_name=?
                         AND {_root_archive_path_sql("path")}
                         AND (src=? OR src LIKE ? ESCAPE '!' OR src LIKE ? ESCAPE '!')
                       ORDER BY path, line, src, dst, kind LIMIT ? OFFSET ?""",
                    (
                        resolved, "calls", _edge_endpoint_name(sym), sym,
                        f"%/{escaped_sym}", f"%::{escaped_sym}", result_limit + 1, offset,
                    ),
                ).fetchall()
                con.set_progress_handler(None, 0)
        except sqlite3.DatabaseError as exc:
            busy = is_busy_error(exc)
            return {
                "success": False,
                "status_code": 503 if busy else 500,
                "terminal": not busy,
                "retryable": busy,
                "symbol": sym,
                "callees": [],
                "count": 0,
                "root": resolved,
                "error": str(exc),
                "busy": busy,
                "truncated": False,
                "truncation": {"callees": False},
                "offset": offset,
                "limit": result_limit,
                "coverage": {"complete": False, "returned": 0, "limit": result_limit, "offset": offset},
                "freshness": {"status": "not_checked"},
                "index_available": None,
            }
        truncated = len(rows) > result_limit
        callees = [
            {"caller": str(r["src"]), "callee": str(r["dst"]), "kind": str(r["kind"]), "path": str(r["path"]), "line": int(r["line"])}
            for r in rows[:result_limit]
        ]
        result = {
            "success": True,
            "symbol": sym,
            "callees": callees,
            "callee_count": len(callees),
            "count": len(callees),
            "root": resolved,
            "offset": offset,
            "limit": result_limit,
            "returned_count": len(callees),
            "has_more": truncated,
            "truncated": truncated,
            "truncation": {"callees": truncated},
            "coverage": {"complete": offset == 0 and not truncated, "returned": len(callees), "limit": result_limit, "offset": offset, "scope": "indexed_edges"},
            "freshness": {"status": "not_checked"},
            "index_available": index_available,
        }
        result["coverage"]["index_available"] = index_available
        if not truncated and (offset == 0 or callees):
            result["total_matches"] = offset + len(callees)
        if truncated:
            result["next_offset"] = offset + len(callees)
        return result

    def python_module_import_graph(self, root: str) -> dict[str, Any]:
        """Return the fresh Python import edges already stored for one indexed root."""
        resolved_root = canonical_root(root)
        root_path = Path(resolved_root)
        if not root_path.is_dir():
            return {"success": False, "state": "unindexed", "error": f"directory not found: {root}"}

        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT path, analyzer_version, mtime_ns, size_bytes FROM files WHERE root=? AND language='python' ORDER BY path",
                (resolved_root,),
            ).fetchall()
            if not rows:
                return {"success": False, "state": "unindexed", "error": "no indexed Python files"}

            stale_paths: list[str] = []
            for row in rows:
                relative = Path(str(row["path"]))
                candidate = (root_path / relative).resolve(strict=False)
                try:
                    candidate.relative_to(root_path)
                    current = candidate.stat()
                    fresh = (
                        str(row["analyzer_version"] or "") == _PARSER_ANALYZER_VERSION
                        and current.st_mtime_ns == row["mtime_ns"]
                        and current.st_size == row["size_bytes"]
                    )
                except (OSError, ValueError):
                    fresh = False
                if not fresh:
                    stale_paths.append(str(row["path"]))
            if stale_paths:
                return {
                    "success": False,
                    "state": "stale",
                    "error_code": "index_stale",
                    "status_code": 409,
                    "terminal": True,
                    "retryable": False,
                    "error": "indexed Python files need reindexing",
                    "stale_paths": stale_paths[:20],
                }

            imports = con.execute(
                "SELECT e.path, e.dst FROM edges AS e JOIN files AS f ON f.root=e.root AND f.path=e.path "
                "WHERE e.root=? AND f.language='python' AND e.kind='imports' ORDER BY e.path, e.line, e.dst",
                (resolved_root,),
            ).fetchall()
        return {
            "success": True,
            "state": "indexed",
            "paths": [str(row["path"]) for row in rows],
            "imports": [{"path": str(row["path"]), "target": str(row["dst"] or "")} for row in imports],
        }

