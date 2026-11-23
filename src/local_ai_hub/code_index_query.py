from __future__ import annotations

from contextlib import closing
import copy
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any

from .cache import stable_hash
from .code_index_constants import _PARSER_ANALYZER_VERSION
from .code_index_scoring import _code_index_candidate_score, _root_archive_path_sql
from .normalizer import tokenize_query_terms
from .process_utils import canonical_root
from .search_pagination import MAX_PAGE_SIZE, MAX_PAGE_WINDOW, pagination_bounds_error
from .sqlite_support import sqlite_batches


CodeIndex = None


class CodeIndexQueryMixin:
    @staticmethod
    def _query_terms(query: str) -> list[str]:
        return [t.lower() for t in tokenize_query_terms(query, min_len=2, max_terms=16)]

    def _candidate_freshness(self, root: str, paths: list[str], *, content_hash: bool = True) -> dict[str, Any]:
        unique_paths = list(dict.fromkeys(self._norm_rel(path) for path in paths if path))
        if not unique_paths:
            return {"status": "no_candidates", "scope": "returned_symbol_candidates", "checked_paths": 0, "stale_paths": [], "unknown_paths": [], "complete": False}
        resolved_root = canonical_root(root)
        try:
            with closing(self._connect()) as con:
                rows = []
                con.execute("BEGIN")
                for batch in sqlite_batches(unique_paths):
                    placeholders = ",".join("?" for _ in batch)
                    rows.extend(con.execute(
                        f"SELECT path,content_hash,mtime_ns,size_bytes,analyzer_version FROM files WHERE root=? AND path IN ({placeholders})",
                        (resolved_root, *batch),
                    ).fetchall())
            file_hashes = {str(row["path"]): str(row["content_hash"] or "") for row in rows}
            file_stats = {str(row["path"]): (row["mtime_ns"], row["size_bytes"]) for row in rows}
            file_analyzers = {str(row["path"]): str(row["analyzer_version"] or "") for row in rows}
        except sqlite3.DatabaseError:
            return {"status": "verification_failed", "scope": "returned_symbol_candidates", "checked_paths": 0, "stale_paths": [], "unknown_paths": unique_paths[:64], "complete": False}

        reader = getattr(self.repo_tools, "_read_snapshot", None)
        verified: list[str] = []
        stale: list[str] = []
        unknown: list[str] = []
        for rel_path in unique_paths:
            indexed_hash = file_hashes.get(rel_path)
            if not indexed_hash:
                unknown.append(rel_path)
                continue
            if file_analyzers.get(rel_path) != _PARSER_ANALYZER_VERSION:
                stale.append(rel_path)
                continue
            target = Path(resolved_root, rel_path).resolve(strict=False)
            try:
                target.relative_to(Path(resolved_root))
            except ValueError:
                unknown.append(rel_path)
                continue
            if not target.is_file():
                stale.append(rel_path)
                continue
            if not content_hash:
                try:
                    current_stat = target.stat()
                    indexed_stat = file_stats[rel_path]
                    if None in indexed_stat:
                        unknown.append(rel_path)
                    elif (current_stat.st_mtime_ns, current_stat.st_size) == indexed_stat:
                        verified.append(rel_path)
                    else:
                        stale.append(rel_path)
                except OSError:
                    unknown.append(rel_path)
                continue
            if not callable(reader):
                unknown.append(rel_path)
                continue
            try:
                current_hash, _lines = reader(target, force=True)
            except (OSError, ValueError):
                unknown.append(rel_path)
                continue
            (verified if str(current_hash) == indexed_hash else stale).append(rel_path)
        status = ("stale_candidates" if stale else
                  ("verified_current_candidates" if content_hash else "stat_current_candidates")
                  if len(verified) == len(unique_paths) else "verification_incomplete")
        return {
            "status": status,
            "scope": "returned_symbol_candidates",
            "checked_paths": len(verified) + len(stale),
            "verified_paths": verified[:64],
            "stale_paths": stale[:64],
            "unknown_paths": unknown[:64],
            "complete": False,
            "verification": "content_hash" if content_hash else "mtime_ns_and_size",
        }

    def _apply_query_freshness(self, result: dict[str, Any], *, verify_content: bool) -> dict[str, Any]:
        paths = list(dict.fromkeys(str(item["path"]) for item in result.get("symbols", []) if item.get("path")))
        root = str(result["root"])
        freshness = self._candidate_freshness(root, paths, content_hash=verify_content)
        status = freshness.get("status")
        current = status in {"verified_current_candidates", "stat_current_candidates"}
        result["freshness"] = freshness
        if status == "stale_candidates":
            result["stale"] = True
        elif current:
            result["stale"] = False
        else:
            # Unknown freshness is described by freshness.status/unknown_paths.
            # The optional public envelope flag is boolean, never JSON null.
            result.pop("stale", None)
        factor = 1.0 if status == "verified_current_candidates" else 0.5 if current else 0.0
        coverage = float(result.get("coverage", {}).get("query_term_coverage", 0.0))
        support = min(1.0, len(result.get("symbols", [])) / 3.0)
        confidence = round(0.65 * coverage + 0.20 * support + 0.15 * factor, 3) if paths else 0.0
        result["confidence"] = min(confidence, 0.90 if current else 0.50) if status != "verified_current_candidates" else confidence
        callback = getattr(self, "_reindex_callback", None)
        queued = 0
        if callable(callback):
            for path in freshness.get("stale_paths", []):
                key = stable_hash({"root": root, "path": path})
                if self._reindex_notifications.get(key) is not None:
                    continue
                self._reindex_notifications.set(key, True)
                try:
                    queued += int(bool(callback(str(Path(root, path)))))
                except Exception:
                    logging.getLogger(__name__).debug("stale candidate notification failed", exc_info=True)
        freshness["reindex_notifications_queued"] = queued
        return result

    def _parse_outcomes_for_paths(self, root: str, paths: list[str]) -> dict[str, Any]:
        unique_paths = list(dict.fromkeys(self._norm_rel(path) for path in paths if path))
        counts = {"syntax_error_files": 0, "fallback_files": 0, "unavailable_files": 0, "failed_files": 0, "unknown_files": 0}
        diagnostics: list[dict[str, Any]] = []
        if not unique_paths:
            return {"scope": "returned_symbol_candidates", "files_examined": 0, **counts, "diagnostics": [], "diagnostics_truncated": False, "complete": False}
        try:
            with closing(self._connect()) as con:
                rows = []
                con.execute("BEGIN")
                for batch in sqlite_batches(unique_paths):
                    placeholders = ",".join("?" for _ in batch)
                    rows.extend(con.execute(
                        f"SELECT f.path,f.language,p.payload_json FROM files f LEFT JOIN parse_blobs p "
                        f"ON p.content_hash=f.content_hash AND p.language=f.language AND p.analyzer_version=? "
                        f"WHERE f.root=? AND f.path IN ({placeholders})",
                        (_PARSER_ANALYZER_VERSION, canonical_root(root), *batch),
                    ).fetchall())
        except sqlite3.DatabaseError:
            return {"scope": "returned_symbol_candidates", "files_examined": 0, **counts, "unknown_files": len(unique_paths), "diagnostics": [], "diagnostics_truncated": False, "complete": False}
        for row in rows:
            diagnostic: Any = {}
            if row["payload_json"]:
                try:
                    payload = json.loads(str(row["payload_json"]))
                    diagnostic = payload.get("parse_outcome", {}) if isinstance(payload, dict) else {}
                except (TypeError, ValueError):
                    diagnostic = {}
            if not isinstance(diagnostic, dict) or not diagnostic:
                counts["unknown_files"] += 1
                diagnostics.append({"path": str(row["path"]), "language": str(row["language"] or "generic"), "status": "unknown"})
                continue
            state = str(diagnostic.get("status") or "unknown")
            if state == "syntax_error":
                counts["syntax_error_files"] += 1
            if bool(diagnostic.get("fallback_used")):
                counts["fallback_files"] += 1
            if str(diagnostic.get("fallback_reason") or "") == "parser_unavailable":
                counts["unavailable_files"] += 1
            if str(diagnostic.get("fallback_reason") or "") == "parser_error":
                counts["failed_files"] += 1
            if state != "ok":
                diagnostics.append({
                    "path": str(row["path"]), "language": str(row["language"] or "generic"),
                    "status": state, "fallback_used": bool(diagnostic.get("fallback_used")),
                    "fallback_reason": str(diagnostic.get("fallback_reason") or ""),
                    "syntax_error_count": int(diagnostic.get("syntax_error_count", 0) or 0),
                    "syntax_error_count_truncated": bool(diagnostic.get("syntax_error_count_truncated", False)),
                })
        return {
            "scope": "returned_symbol_candidates", "files_examined": len(rows), **counts,
            "diagnostics": diagnostics[:64], "diagnostics_truncated": len(diagnostics) > 64,
            "complete": len(rows) == len(unique_paths),
        }

    def query(
        self,
        root: str,
        query: str,
        limit: int = 24,
        offset: int = 0,
        *,
        verify_freshness: bool = False,
    ) -> dict[str, Any]:
        """Search the built-in symbol index without requiring an external model.

        The endpoint intentionally returns compact symbol metadata. Agents can follow
        with ``find_symbol``/``inspect_symbol`` when source bodies are actually needed.
        """
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {
                "success": False, "error": bounds_error,
                "status_code": 400,
                "limit": limit if isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= MAX_PAGE_SIZE else None,
                "offset": offset if isinstance(offset, int) and not isinstance(offset, bool) and 0 <= offset < MAX_PAGE_WINDOW else None,
                "total_matches": 0, "has_more": False, "symbols": [],
            }
        limit = max(1, min(limit, int(self.config.get("code_index", {}).get("max_query_results", 30))))
        resolved_root = canonical_root(root)
        if not Path(resolved_root).is_dir():
            return {
                "success": False, "root": resolved_root, "error": "root directory does not exist",
                "stale_root": True, "confidence": 0.0,
                "total_matches": 0, "has_more": False, "limit": limit, "offset": offset,
                "coverage": {"query_term_count": 0, "matched_term_count": 0, "query_term_coverage": 0.0, "complete": False, "scope": "no_candidates"},
                "freshness": {"status": "stale_root", "scope": "repository", "checked_paths": 0, "stale_paths": [], "unknown_paths": [], "complete": False},
                "truncated": False,
                "truncation": {"returned_count": 0, "observed_match_count": 0, "candidate_cap_reached": False},
                "parse_outcomes": {"scope": "no_candidates", "files_examined": 0, "syntax_error_files": 0, "fallback_files": 0, "unavailable_files": 0, "failed_files": 0, "unknown_files": 0, "complete": False},
            }
        exact_identifier = query if query.isidentifier() and query.isascii() else None
        terms = self._query_terms(query)
        if not terms and exact_identifier is not None:
            terms = [exact_identifier.lower()]
        if not terms:
            return {
                "success": True, "root": resolved_root, "query": query, "terms": [],
                "matches_count": 0, "total_matches": 0, "has_more": False,
                "returned_count": 0, "symbols": [], "confidence": 0.0,
                "limit": limit, "offset": offset,
                "coverage": {"query_term_count": 0, "matched_term_count": 0, "query_term_coverage": 0.0, "complete": False, "scope": "indexed_symbol_candidates"},
                "freshness": {"status": "not_checked", "scope": "returned_symbol_candidates", "checked_paths": 0, "stale_paths": [], "unknown_paths": [], "complete": False},
                "truncated": False,
                "parse_outcomes": {"scope": "returned_symbol_candidates", "files_examined": 0, "unknown_files": 0, "complete": False},
            }
        cache_generation = self._cache_generation()
        cache_key = stable_hash({
            "root": resolved_root, "query": query, "terms": terms, "limit": limit, "offset": offset,
            "generation": cache_generation,
        })
        cached = None if verify_freshness else self._query_l1.get(cache_key)
        if isinstance(cached, dict):
            return self._apply_query_freshness(copy.deepcopy(cached), verify_content=False)

        ignored_paths = []
        for directory in sorted(getattr(self.repo_tools, "ignore_dirs", ())):
            name = str(directory).strip().strip("/\\").lower()
            if name and "/" not in name and "\\" not in name:
                ignored_paths.append(name)
        ignored_path_sql = " AND ".join(
            "instr('/' || lower(path) || '/', ?) = 0" for _ in ignored_paths
        )
        root_archive_sql = _root_archive_path_sql()
        base_filters_sql = " AND ".join((
            "root=?",
            root_archive_sql,
            *([ignored_path_sql] if ignored_path_sql else []),
        ))
        base_args: list[Any] = [resolved_root, *(f"/{name}/" for name in ignored_paths)]
        # WAL readers need a stable snapshot, not the writer mutex; otherwise
        # preprocessing batches can stall foreground symbol queries.
        with closing(self._connect()) as con:
            con.execute("BEGIN")
            exact_match_exists = False
            if exact_identifier is not None:
                exact_match_exists = con.execute(
                    "SELECT 1 FROM symbols WHERE " + base_filters_sql + " AND lower(name)=? LIMIT 1",
                    [*base_args, exact_identifier.lower()],
                ).fetchone() is not None
            candidate_filters_sql = base_filters_sql
            candidate_args = list(base_args)
            if all(len(term) >= 3 for term in terms):
                try:
                    con.execute(
                        "CREATE TEMP TABLE hub_query_trigrams("
                        "term_index INTEGER NOT NULL,gram TEXT NOT NULL,gram_count INTEGER NOT NULL,"
                        "PRIMARY KEY(term_index,gram)) WITHOUT ROWID"
                    )
                    con.execute(
                        "CREATE TEMP TABLE hub_query_symbol_candidates("
                        "symbol_rowid INTEGER PRIMARY KEY) WITHOUT ROWID"
                    )
                    for term_index, term in enumerate(terms):
                        grams = {term[offset:offset + 3] for offset in range(len(term) - 2)}
                        con.executemany(
                            "INSERT INTO temp.hub_query_trigrams(term_index,gram,gram_count) VALUES(?,?,?)",
                            ((term_index, gram, len(grams)) for gram in grams),
                        )
                    con.execute(
                        "INSERT OR IGNORE INTO temp.hub_query_symbol_candidates(symbol_rowid) "
                        "SELECT matched.symbol_rowid FROM ("
                        "SELECT postings.symbol_rowid,postings.field,query.term_index "
                        "FROM symbol_trigrams AS postings "
                        "JOIN temp.hub_query_trigrams AS query ON query.gram=postings.gram "
                        "WHERE postings.root=? "
                        "GROUP BY postings.symbol_rowid,postings.field,query.term_index "
                        "HAVING COUNT(*)=MAX(query.gram_count)) AS matched",
                        (resolved_root,),
                    )
                    candidate_filters_sql += (
                        " AND rowid IN (SELECT symbol_rowid FROM temp.hub_query_symbol_candidates)"
                    )
                except sqlite3.Error:
                    # The derived candidate index is an optimization only. A
                    # failed lookup must retain the complete scan contract.
                    candidate_filters_sql = base_filters_sql
                    candidate_args = list(base_args)
            architecture = bool(re.search(r"\b(?:architecture|lifecycle|ownership|orchestration|entrypoints?)\b", query, re.I))
            public_entrypoints = bool(re.search(r"\bpublic\b", query, re.I) and re.search(r"\b(?:tools?|api|exports?|entrypoints?)\b", query, re.I))
            prefer_tests = bool(re.search(r"\b(?:tests?|pytest)\b|\btest_", query, re.I))

            def source_priority(path: Any) -> int:
                parts = str(path or "").replace("\\", "/").casefold().split("/")
                name = parts[-1]
                is_test = "tests" in parts or "test" in parts or name.startswith("test_") or name.endswith("_test.py")
                return int(is_test != prefer_tests)

            def score_match(name: Any, name_path: Any, container: Any, path: Any, docstring: Any, kind: Any) -> float:
                return _code_index_candidate_score(
                    name, name_path, container, path, terms, exact_identifier,
                    docstring=docstring, kind=kind, architecture=architecture,
                    public_entrypoints=public_entrypoints,
                )

            con.create_function("hub_code_index_score", 6, score_match, deterministic=True)
            con.create_function("hub_code_index_source_priority", 1, source_priority, deterministic=True)
            if exact_match_exists and exact_identifier is not None:
                # Boost indexed exact hits without filtering fuzzy candidates,
                # which still count toward totals and later offset pages.
                score_sql = (
                    "CASE WHEN lower(name)=? THEN 1000.0 "
                    "ELSE hub_code_index_score(name,name_path,container,path,docstring,kind) END"
                )
                candidate_args = [exact_identifier.lower(), *base_args]
            else:
                score_sql = "hub_code_index_score(name,name_path,container,path,docstring,kind)"
            if public_entrypoints:
                score_sql = "(" + score_sql + "+ CASE WHEN EXISTS(SELECT 1 FROM symbol_trigrams AS registration " \
                    "WHERE registration.symbol_rowid=symbols.rowid AND registration.root=symbols.root " \
                    "AND registration.field='tool_entrypoint' AND registration.gram='too') THEN 40.0 ELSE 0.0 END)"
            sql = (
                "WITH scored AS MATERIALIZED ("
                "SELECT rowid AS _rowid," + score_sql + " AS _score "
                "FROM symbols WHERE " + candidate_filters_sql
                + "), matches AS MATERIALIZED ("
                "SELECT * FROM scored WHERE _score > 0"
                "), stats AS (SELECT COUNT(*) AS _total_matches FROM matches), "
                "page AS (SELECT matches._rowid,matches._score,1 AS _present "
                "FROM matches JOIN symbols AS ranked ON ranked.rowid=matches._rowid "
                "ORDER BY (matches._score >= 1000) DESC,hub_code_index_source_priority(ranked.path) ASC,"
                "matches._score DESC,ranked.path ASC,ranked.line ASC,ranked.name_path ASC "
                "LIMIT ? OFFSET ?) "
                "SELECT symbols.path,symbols.name,symbols.kind,symbols.line,symbols.end_line,"
                "symbols.container,symbols.name_path,symbols.signature,symbols.access,symbols.docstring,"
                "page._score,page._present,stats._total_matches FROM stats "
                "LEFT JOIN page ON 1=1 LEFT JOIN symbols ON symbols.rowid=page._rowid"
            )
            rows = con.execute(sql, [*candidate_args, limit, offset]).fetchall()
            indexed_files_present = None
            if not rows or int(rows[0]["_total_matches"]) == 0:
                indexed_files_present = con.execute(
                    "SELECT 1 FROM files WHERE root=? LIMIT 1", (resolved_root,)
                ).fetchone() is not None
        total_matches = int(rows[0]["_total_matches"]) if rows else 0
        rows = [row for row in rows if row["_present"] is not None]
        candidate_truncated = False
        candidate_limit = None

        ranked: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            name = str(row["name"])
            name_l = name.lower()
            name_path = str(row["name_path"] or "")
            haystack = " ".join((name_l, name_path.lower(), str(row["container"] or "").lower(), str(row["path"]).lower(), str(row["docstring"] or "").lower()))
            score = float(row["_score"])
            matched_terms: list[str] = []
            for term in terms:
                if name_l == term:
                    matched_terms.append(term)
                elif name_l.startswith(term):
                    matched_terms.append(term)
                elif term in name_l:
                    matched_terms.append(term)
                elif term in haystack:
                    matched_terms.append(term)
            item = {
                "name": name,
                "name_path": name_path,
                "kind": str(row["kind"]),
                "path": str(row["path"]),
                "line": int(row["line"]),
                "end_line": int(row["end_line"] or row["line"]),
                "container": str(row["container"] or ""),
                "signature": str(row["signature"] or ""),
                "access": str(row["access"] or "public"),
                "score": round(score, 2),
                "matched_terms": matched_terms,
            }
            ranked.append((score, item))
        symbols = [item for _, item in ranked]
        matched_terms = sorted({term for item in symbols for term in item["matched_terms"]})
        term_coverage = round(len(matched_terms) / max(1, len(terms)), 3)
        has_more = offset + len(symbols) < total_matches
        truncated = has_more
        candidate_paths = list(dict.fromkeys(str(item["path"]) for item in symbols if item.get("path")))
        freshness = {
            "status": "not_checked", "scope": "returned_symbol_candidates", "checked_paths": 0,
            "stale_paths": [], "unknown_paths": candidate_paths[:64], "complete": False,
        }
        parse_outcomes = self._parse_outcomes_for_paths(resolved_root, candidate_paths)
        out = {
            "success": True,
            "root": resolved_root,
            "query": query,
            "terms": terms,
            "matches_count": len(symbols),
            "total_matches": total_matches,
            "has_more": has_more,
            "limit": limit,
            "offset": offset,
            "observed_match_count": total_matches,
            "returned_count": len(symbols),
            "symbols": symbols,
            "confidence": 0.0,
            "confidence_basis": "returned_query_term_coverage_result_support_and_candidate_freshness",
            "coverage": {
                "query_term_count": len(terms),
                "matched_term_count": len(matched_terms),
                "matched_terms": matched_terms,
                "query_term_coverage": term_coverage,
                "candidate_match_count": total_matches,
                "returned_symbol_count": len(symbols),
                "complete": False,
                "scope": "indexed_symbol_candidates",
                **({"indexed_files_present": indexed_files_present} if indexed_files_present is not None else {}),
            },
            "freshness": freshness,
            "truncated": truncated,
            "truncation": {
                "result_limit": limit,
                "returned_count": len(symbols),
                "observed_match_count": total_matches,
                "candidate_cap": candidate_limit,
                "candidate_cap_reached": candidate_truncated,
            },
            "parse_outcomes": parse_outcomes,
        }
        self._apply_query_freshness(out, verify_content=verify_freshness)
        if not verify_freshness:
            self._query_l1.set(cache_key, out)
        return out

