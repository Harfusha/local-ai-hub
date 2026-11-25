from __future__ import annotations

import ast
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterable

from .cache import stable_hash
from .code_index_scoring import _root_archive_path_sql
from .json_utils import dumps as json_dumps
from .process_utils import canonical_root
from .repo_tools import FileTooLargeError
from .search_pagination import pagination_bounds_error
from .sqlite_support import is_busy_error, write_transaction


CodeIndex = None


class CodeIndexSymbolMixin:
    def indexed_skeleton(self, root: str, path: str) -> dict[str, Any]:
        """Render an authorized, stat-current symbol outline without reading source."""
        if not Path(root).is_absolute() or not path:
            return {"success": False, "terminal": True, "retryable": False,
                    "error": "indexed skeleton requires an absolute root and file path"}
        base = Path(canonical_root(root))
        try:
            target = (base / path).resolve(strict=True)
            relative = target.relative_to(base).as_posix()
            before = target.stat()
            if not target.is_file():
                raise ValueError("not a regular file")
        except (OSError, ValueError, RuntimeError):
            return {"success": False, "terminal": True, "retryable": False, "error": "invalid source path"}
        api, project_context = self._project_config_context(str(base))
        settings = project_context.settings if project_context is not None else None
        if api is not None and settings is not None and (
            not api.phase_is_allowed(settings, "call_graph")
            or not api.path_is_allowed(str(base), target, settings, phase="call_graph", size_bytes=before.st_size)
        ):
            return {"success": False, "terminal": True, "retryable": False,
                    "error_code": "project_path_excluded", "error": "project policy excludes this indexed path"}
        with self._lock, closing(self._connect()) as con:
            con.execute("BEGIN")
            metadata = con.execute(
                "SELECT mtime_ns,size_bytes,language FROM files WHERE root=? AND path=?", (str(base), relative),
            ).fetchone()
            if metadata is None or metadata[0] != before.st_mtime_ns or metadata[1] != before.st_size:
                return {"success": False, "stale": metadata is not None, "terminal": True, "retryable": False,
                        "error_code": "indexed_skeleton_unavailable", "error": "index this file or supply source text explicitly"}
            rows = con.execute(
                "SELECT name,kind,name_path,signature,line,end_line FROM symbols WHERE root=? AND path=? "
                "ORDER BY line,name LIMIT 2001", (str(base), relative),
            ).fetchall()
        if not self._file_stat_is_current(target, before):
            return {"success": False, "stale": True, "terminal": True, "retryable": False,
                    "error_code": "indexed_skeleton_changed", "error": "file changed during outline retrieval"}
        lines: list[str] = []
        used, truncated = 0, len(rows) > 2000
        for row in rows[:2000]:
            signature = str(row["signature"] or f"{row['kind']} {row['name']}").splitlines()[0]
            indent = "    " * min(8, str(row["name_path"] or "").count("/"))
            text = f"{indent}{signature}  # lines {row['line']}-{row['end_line']}"
            if used + len(text) + 1 > 64_000:
                truncated = True
                break
            lines.append(text)
            used += len(text) + 1
        skeleton = "\n".join(lines)
        return {"success": True, "path": relative, "source": "code_index", "language": metadata[2],
                "skeleton_code": skeleton, "skeleton_chars": len(skeleton), "source_size_bytes": before.st_size,
                "skeleton_format": "symbol_outline", "symbols_returned": len(lines), "truncated": truncated,
                "freshness_verification": "mtime_ns_and_size", "imports_included": False,
                "omissions": ["imports", "decorators", "docstrings", "bodies"]}

    def symbol_bounds_at(
        self, root: str, path: str, line: int, *, content_hash: str
    ) -> tuple[int, int] | None:
        """Return enclosing body bounds only for the caller's current source bytes."""
        with self._lock, closing(self._connect()) as con:
            row = con.execute(
                "SELECT s.line,s.end_line FROM symbols s JOIN files f "
                "ON f.root=s.root AND f.path=s.path "
                "WHERE s.root=? AND s.path=? AND f.content_hash=? "
                "AND s.kind IN ('class','function','method','constructor','enum','interface','struct','trait','impl') "
                "AND s.line<=? AND s.end_line>=? "
                "ORDER BY (s.end_line-s.line),s.line DESC LIMIT 1",
                (canonical_root(root), self._norm_rel(path), content_hash, line, line),
            ).fetchone()
        return (int(row[0]), int(row[1])) if row is not None else None

    def find_symbol(
        self,
        root: str,
        name_path_pattern: str,
        depth: int = 0,
        include_body: bool = False,
        include_info: bool = True,
        include_kinds: list[str] | None = None,
        exclude_kinds: list[str] | None = None,
        substring_matching: bool = False,
        relative_path: str | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        resolved_root = canonical_root(root)
        pat = name_path_pattern.strip()
        if not pat:
            return {"success": False, "error": "name_path_pattern required"}

        cache_generation = self._cache_generation()
        cache_key = stable_hash({
            "root": resolved_root,
            "pattern": pat,
            "depth": depth,
            "include_body": include_body,
            "include_info": include_info,
            "include_kinds": include_kinds,
            "exclude_kinds": exclude_kinds,
            "substring_matching": substring_matching,
            "relative_path": relative_path,
            "limit": limit,
            "generation": cache_generation,
        })
        cached = self._symbol_l1.get(cache_key)
        if isinstance(cached, dict):
            return copy.deepcopy(cached)

        where = ["root = ?", _root_archive_path_sql("path")]
        args: list[Any] = [resolved_root]

        if relative_path:
            norm_path = relative_path.replace("\\", "/").strip("/")
            if "." in Path(norm_path).name:
                where.append("path = ?")
                args.append(norm_path)
            else:
                where.append("path LIKE ?")
                args.append(f"{norm_path}/%")

        if include_kinds:
            where.append("kind IN (SELECT value FROM json_each(?))")
            args.append(json_dumps(list(include_kinds)))

        if exclude_kinds:
            where.append("kind NOT IN (SELECT value FROM json_each(?))")
            args.append(json_dumps(list(exclude_kinds)))

        if substring_matching:
            where.append("(name_path LIKE ? OR name LIKE ?)")
            args.extend([f"%{pat}%", f"%{pat}%"])
        elif "/" in pat:
            where.append("(name_path = ? OR name_path LIKE ?)")
            args.extend([pat, f"%/{pat}"])
        else:
            where.append("(lower(name) = lower(?) OR name_path LIKE ? OR lower(name) LIKE ?)")
            args.extend([pat, f"%/{pat}", f"%{pat.lower()}%"])

        sql = f"SELECT path, name, kind, line, end_line, container, name_path, signature, access, docstring FROM symbols WHERE {' AND '.join(where)} ORDER BY path, line LIMIT ?"
        args.append(limit)

        with self._lock, closing(self._connect()) as con:
            rows = con.execute(sql, args).fetchall()

        results: list[dict[str, Any]] = []
        base_path = Path(resolved_root)

        for r in rows:
            p, name, kind, line = str(r["path"]), str(r["name"]), str(r["kind"]), int(r["line"])
            end_line = int(r["end_line"] or r["line"])
            name_path = str(r["name_path"])
            container = str(r["container"] or "")
            sig = str(r["signature"] or "")
            doc = str(r["docstring"] or "")

            item: dict[str, Any] = {
                "name": name,
                "name_path": name_path,
                "kind": kind,
                "path": p,
                "line": line,
                "end_line": end_line,
                "container": container,
            }

            if include_info:
                item["signature"] = sig
                item["docstring"] = doc
                item["access"] = str(r["access"] or "public")

            if include_body:
                file_full = base_path / p
                if file_full.is_file():
                    try:
                        _digest, flines = self.repo_tools._read_snapshot(
                            file_full, max_bytes=self.repo_tools.max_file_bytes,
                        )
                        item["body"] = "\n".join(flines[max(0, line - 1):min(len(flines), end_line)])
                    except Exception:
                        item["body"] = ""

            if depth > 0 and kind in {"class", "interface", "struct"}:
                with self._lock, closing(self._connect()) as con:
                    child_rows = con.execute(
                        f"SELECT path, name, kind, line, end_line, name_path, signature FROM symbols WHERE root=? AND path=? AND container=? AND {_root_archive_path_sql('path')} LIMIT 50",
                        (resolved_root, p, name),
                    ).fetchall()
                    item["children"] = [
                        {
                            "name": str(cr["name"]),
                            "name_path": str(cr["name_path"]),
                            "kind": str(cr["kind"]),
                            "line": int(cr["line"]),
                            "end_line": int(cr["end_line"] or cr["line"]),
                            "signature": str(cr["signature"] or ""),
                        }
                        for cr in child_rows
                    ]

            results.append(item)

        result = {
            "success": True,
            "root": resolved_root,
            "pattern": pat,
            "returned_count": len(results),
            "symbols": results,
        }
        self._symbol_l1.set(cache_key, copy.deepcopy(result))
        return result

    def find_declaration(self, root: str, symbol_name: str, path: str | None = None) -> dict[str, Any]:
        if not isinstance(symbol_name, str) or not symbol_name.strip():
            return {
                "success": False,
                "status_code": 400,
                "terminal": True,
                "retryable": False,
                "error_code": "invalid_symbol",
                "error": "symbol cannot be empty",
            }
        res = self.find_symbol(root, symbol_name, depth=0, include_body=True, include_info=True, relative_path=path, limit=5)
        if res.get("success") is not True:
            return res
        symbols = res.get("symbols", [])
        if not symbols:
            return {
                "success": False,
                "status_code": 404,
                "terminal": True,
                "retryable": False,
                "error_code": "declaration_not_found",
                "error": f"Declaration of '{symbol_name}' not found in indexed symbols; repository coverage is not verified",
                "coverage": {"complete": False, "scope": "indexed_symbols"},
                "freshness": {"status": "not_checked"},
            }
        return {"success": True, "declaration": symbols[0]}

    def find_implementations(
        self, root: str, symbol_name: str, path: str | None = None, limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}
        if not isinstance(symbol_name, str) or not symbol_name.strip():
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": "symbol cannot be empty"}
        resolved_root = canonical_root(root)
        where = f"root=? AND {_root_archive_path_sql('path')} AND (lower(dst)=lower(?) OR dst LIKE ?) AND kind IN ('inherits', 'implements')"
        args: list[Any] = [resolved_root, symbol_name, f"%{symbol_name}%"]
        if path:
            where += " AND path=?"
            args.append(path.replace("\\", "/").strip("/"))
        try:
            with self._lock, closing(self._connect()) as con:
                deadline = time.monotonic() + 1.0
                con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                edges = con.execute(
                    f"SELECT src, dst, kind, path, line FROM edges WHERE {where} ORDER BY path, line, src, dst, kind LIMIT ? OFFSET ?",
                    (*args, limit + 1, offset),
                ).fetchall()
                con.set_progress_handler(None, 0)
        except sqlite3.DatabaseError as exc:
            busy = is_busy_error(exc)
            return {
                "success": False, "status_code": 503 if busy else 500,
                "terminal": not busy, "retryable": busy, "error": str(exc), "busy": busy,
                "implementations": [], "count": 0, "offset": offset, "limit": limit,
                "coverage": {"complete": False, "returned": 0, "offset": offset, "limit": limit, "scope": "indexed_edges"},
                "freshness": {"status": "not_checked"},
            }

        implementations: list[dict[str, Any]] = []
        has_more = len(edges) > limit
        for e in edges[:limit]:
            src_name = str(e["src"])
            p = str(e["path"])
            ln = int(e["line"])
            implementations.append({
                "implementer": src_name,
                "target": str(e["dst"]),
                "relationship": str(e["kind"]),
                "path": p,
                "line": ln,
            })

        result = {
            "success": True,
            "symbol": symbol_name,
            "implementations_count": len(implementations),
            "implementations": implementations,
            "count": len(implementations),
            "offset": offset,
            "limit": limit,
            "returned_count": len(implementations),
            "has_more": has_more,
            "truncated": has_more,
            "coverage": {"complete": offset == 0 and not has_more, "returned": len(implementations), "limit": limit, "offset": offset, "scope": "indexed_edges"},
            "freshness": {"status": "not_checked"},
        }
        if not has_more and (offset == 0 or implementations):
            result["total_matches"] = offset + len(implementations)
        if has_more:
            result["next_offset"] = offset + len(implementations)
        return result

    def find_referencing_symbols(self, root: str, symbol_name: str, path: str | None = None) -> dict[str, Any]:
        resolved_root = canonical_root(root)
        where = f"root=? AND {_root_archive_path_sql('path')} AND (lower(name)=lower(?) OR name LIKE ?)"
        args: list[Any] = [resolved_root, symbol_name, f"%{symbol_name}%"]
        if path:
            where += " AND path=?"
            args.append(path.replace("\\", "/").strip("/"))
        with self._lock, closing(self._connect()) as con:
            rows = con.execute(
                f"SELECT path, name, line, kind FROM refs WHERE {where} ORDER BY path, line LIMIT 100",
                tuple(args),
            ).fetchall()

        references = [
            {"path": str(r["path"]), "symbol": str(r["name"]), "line": int(r["line"]), "kind": str(r["kind"])}
            for r in rows
        ]

        return {
            "success": True,
            "symbol": symbol_name,
            "references_count": len(references),
            "references": references,
        }

    def get_symbols_overview(self, root: str, path: str, depth: int = 1) -> dict[str, Any]:
        resolved_root = canonical_root(root)
        norm_path = path.replace("\\", "/").strip("/")

        with self._lock, closing(self._connect()) as con:
            rows = con.execute(
                f"SELECT name, kind, line, end_line, container, name_path, signature, access FROM symbols WHERE root=? AND path=? AND {_root_archive_path_sql('path')} ORDER BY line",
                (resolved_root, norm_path),
            ).fetchall()

        overview: list[dict[str, Any]] = []
        for r in rows:
            overview.append({
                "name": str(r["name"]),
                "kind": str(r["kind"]),
                "line": int(r["line"]),
                "end_line": int(r["end_line"] or r["line"]),
                "container": str(r["container"] or ""),
                "name_path": str(r["name_path"] or r["name"]),
                "signature": str(r["signature"] or ""),
                "access": str(r["access"] or "public"),
            })

        return {
            "success": True,
            "path": norm_path,
            "symbols_count": len(overview),
            "symbols": overview,
        }

    def get_diagnostics_for_file(self, root: str, path: str) -> dict[str, Any]:
        resolved_root = Path(canonical_root(root)).resolve()
        target = (resolved_root / path).resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError:
            return {"success": False, "error": f"path escapes root: {path}"}
        if not target.is_file():
            return {"success": False, "error": f"file not found: {path}"}

        errors: list[dict[str, Any]] = []
        lang = self._lang(path)

        if lang == "python":
            try:
                _digest, lines = self.repo_tools._read_snapshot(
                    target, max_bytes=self.repo_tools.max_file_bytes,
                )
                txt = "\n".join(lines)
                ast.parse(txt, filename=str(target))
            except FileTooLargeError:
                return {
                    "success": True,
                    "path": path,
                    "errors": [],
                    "skipped": True,
                    "reason": "file exceeds max indexable size",
                }
            except (SyntaxError, OSError) as e:
                errors.append({
                    "line": getattr(e, "lineno", 1) or 1,
                    "column": getattr(e, "offset", 1) or 1,
                    "severity": "ERROR",
                    "message": str(getattr(e, "msg", e)),
                    "source": "python-ast",
                })
        elif lang == "json":
            try:
                txt = target.read_text(encoding="utf-8", errors="replace")
                json.loads(txt)
            except (json.JSONDecodeError, OSError) as e:
                errors.append({
                    "line": getattr(e, "lineno", 1),
                    "column": getattr(e, "colno", 1),
                    "severity": "ERROR",
                    "message": str(getattr(e, "msg", e)),
                    "source": "json-parser",
                })

        return {
            "success": True,
            "path": path,
            "clean": len(errors) == 0,
            "diagnostics_count": len(errors),
            "diagnostics": errors,
        }

    @staticmethod
    def _norm_rel(path: str) -> str:
        return str(path or "").replace("\\", "/").strip("/")

    @staticmethod
    def _is_test_path(path: str) -> bool:
        low = "/" + str(path or "").replace("\\", "/").lower()
        name = Path(low).name
        stem = Path(low).stem
        return (
            "/test" in low or "/spec" in low or name.startswith("test_")
            or any(marker in stem for marker in ("_test", ".test", "_spec", ".spec"))
        )

    def file_summary(self, root: str, path: str, limit: int = 80) -> dict[str, Any]:
        """Return compact pre-indexed facts for one file without reopening source text."""
        resolved_root = canonical_root(root)
        norm_path = self._norm_rel(path)
        limit = max(1, min(int(limit), 250))
        try:
            with self._lock, closing(self._connect()) as con:
                file_row = con.execute(
                    f"SELECT content_hash,language,updated_at FROM files WHERE root=? AND path=? AND {_root_archive_path_sql('path')}",
                    (resolved_root, norm_path),
                ).fetchone()
                symbols = [dict(r) for r in con.execute(
                    f"SELECT name,kind,line,end_line,container,name_path,signature,access,docstring "
                    f"FROM symbols WHERE root=? AND path=? AND {_root_archive_path_sql('path')} ORDER BY line LIMIT ?",
                    (resolved_root, norm_path, limit),
                ).fetchall()]
                refs = [dict(r) for r in con.execute(
                    f"SELECT name,line,kind FROM refs WHERE root=? AND path=? AND {_root_archive_path_sql('path')} ORDER BY line LIMIT ?",
                    (resolved_root, norm_path, limit),
                ).fetchall()]
                edges = [dict(r) for r in con.execute(
                    f"SELECT src,dst,kind,line FROM edges WHERE root=? AND path=? AND {_root_archive_path_sql('path')} ORDER BY line LIMIT ?",
                    (resolved_root, norm_path, limit),
                ).fetchall()]
        except sqlite3.DatabaseError as exc:
            return {"success": False, "root": resolved_root, "path": norm_path, "error": str(exc), "busy": is_busy_error(exc)}
        if file_row is None:
            return {"success": False, "root": resolved_root, "path": norm_path, "indexed": False, "symbols": [], "references": [], "edges": []}
        return {
            "success": True,
            "root": resolved_root,
            "path": norm_path,
            "indexed": True,
            "content_hash": str(file_row["content_hash"] or ""),
            "language": str(file_row["language"] or "generic"),
            "updated_at": float(file_row["updated_at"] or 0.0),
            "symbols": symbols,
            "references": refs,
            "edges": edges,
        }

    def related_paths(
        self,
        root: str,
        query: str,
        limit: int = 30,
        *,
        result: dict[str, Any] | None = None,
    ) -> list[str]:
        """Rank likely files entirely from the persistent code index.

        This is intentionally bounded and does not read repository files. It is used as
        a cheap candidate generator before lexical/RAG fallbacks.
        """
        resolved_root = canonical_root(root)
        terms = self._query_terms(query)
        if not terms:
            return []
        limit = max(1, min(int(limit), 100))
        scores: dict[str, float] = {}
        symbol_result = result
        if symbol_result is None:
            symbol_result = self.query(resolved_root, query, min(max(limit * 2, 20), 100))
        for item in symbol_result.get("symbols", []) if isinstance(symbol_result, dict) else []:
            path = self._norm_rel(str(item.get("path", "")))
            if path:
                scores[path] = scores.get(path, 0.0) + 8.0 + float(item.get("score", 0.0) or 0.0)

        clauses = " OR ".join("(lower(name) LIKE ? OR lower(path) LIKE ?)" for _ in terms)
        ref_args: list[Any] = [resolved_root]
        for term in terms:
            like = f"%{term}%"
            ref_args.extend([like, like])
        edge_clauses = " OR ".join("(lower(src) LIKE ? OR lower(dst) LIKE ? OR lower(path) LIKE ?)" for _ in terms)
        edge_args: list[Any] = [resolved_root]
        for term in terms:
            like = f"%{term}%"
            edge_args.extend([like, like, like])
        file_clauses = " OR ".join("lower(path) LIKE ?" for _ in terms)
        file_args: list[Any] = [resolved_root, *[f"%{term}%" for term in terms]]
        row_cap = max(80, limit * 12)
        try:
            with self._lock, closing(self._connect()) as con:
                for row in con.execute(
                    f"SELECT path,name,kind FROM refs WHERE root=? AND {_root_archive_path_sql('path')} AND ({clauses}) LIMIT ?",
                    (*ref_args, row_cap),
                ).fetchall():
                    path = self._norm_rel(str(row["path"]))
                    scores[path] = scores.get(path, 0.0) + (4.0 if str(row["name"]).lower() in terms else 2.0)
                for row in con.execute(
                    f"SELECT path,src,dst,kind FROM edges WHERE root=? AND {_root_archive_path_sql('path')} AND ({edge_clauses}) LIMIT ?",
                    (*edge_args, row_cap),
                ).fetchall():
                    path = self._norm_rel(str(row["path"]))
                    scores[path] = scores.get(path, 0.0) + (3.0 if str(row["kind"]) in {"imports", "inherits"} else 1.5)
                for row in con.execute(
                    f"SELECT path FROM files WHERE root=? AND {_root_archive_path_sql('path')} AND ({file_clauses}) LIMIT ?",
                    (*file_args, row_cap),
                ).fetchall():
                    path = self._norm_rel(str(row["path"]))
                    scores[path] = scores.get(path, 0.0) + 2.0
        except sqlite3.DatabaseError:
            pass
        return [path for path, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]]

    def prune(
        self, root: str, current_paths: Iterable[str], *, stale_paths: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Remove stale per-workspace index rows in bounded transactions."""
        resolved_root = canonical_root(root)
        current = {self._norm_rel(p) for p in current_paths if self._norm_rel(p)}
        stale_candidates = (
            {self._norm_rel(p) for p in stale_paths if self._norm_rel(p)}
            if stale_paths is not None else None
        )
        pruned_count = 0
        try:
            with self._lock, closing(self._connect()) as con:
                indexed = {self._norm_rel(str(r[0])) for r in con.execute("SELECT path FROM files WHERE root=?", (resolved_root,)).fetchall()}
                stale = sorted(indexed - current)
                if stale_candidates is not None:
                    stale = [path for path in stale if path in stale_candidates]
                if not stale:
                    return {"success": True, "root": resolved_root, "pruned": 0}
                pairs = [(resolved_root, path) for path in stale]
                for offset in range(0, len(pairs), 128):
                    batch = pairs[offset:offset + 128]
                    with write_transaction(
                        con, max_duration_seconds=5.0, rollback_label="code index prune"
                    ):
                        con.executemany("DELETE FROM symbol_trigrams WHERE root=? AND path=?", batch)
                        for table in ("symbols", "refs", "edges", "files"):
                            con.executemany(f"DELETE FROM {table} WHERE root=? AND path=?", batch)
                        con.executemany("DELETE FROM file_usage WHERE root=? AND path=?", batch)
                    pruned_count += len(batch)
            self._advance_query_cache_generation()
            self._status_cache.pop(resolved_root, None)
            return {"success": True, "root": resolved_root, "pruned": pruned_count, "paths": stale[:100]}
        except sqlite3.DatabaseError as exc:
            if pruned_count:
                self._advance_query_cache_generation()
                self._status_cache.pop(resolved_root, None)
            return {
                "success": False, "root": resolved_root, "pruned": pruned_count,
                "partial": pruned_count > 0, "error": str(exc), "busy": is_busy_error(exc),
            }

