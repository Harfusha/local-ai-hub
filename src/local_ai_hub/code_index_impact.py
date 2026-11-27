from __future__ import annotations

from contextlib import closing
import copy
from pathlib import Path
import sqlite3
from typing import Any

from .cache import stable_hash
from .code_index_constants import MAX_IMPACT_DEPENDENTS
from .code_index_scoring import _root_archive_path_sql
from .json_utils import dumps as json_dumps
from .process_utils import canonical_root
from .sqlite_support import is_busy_error, sqlite_batches


CodeIndex = None


class CodeIndexImpactMixin:
    def impact(self, root: str, changed_paths: list[str], max_symbols: int = 48, max_dependents: int = 30, *,
               verify_freshness: bool = False) -> dict[str, Any]:
        """Resolve changed symbols, dependents and likely tests from SQLite only."""
        resolved_root = canonical_root(root)
        changed = list(dict.fromkeys(self._norm_rel(p) for p in changed_paths if self._norm_rel(p)))
        max_symbols = max(1, min(int(max_symbols), 200))
        max_dependents = max(1, min(int(max_dependents), MAX_IMPACT_DEPENDENTS))
        if not changed:
            return {
                "success": True,
                "root": resolved_root,
                "changed_symbols": [],
                "likely_dependents": [],
                "suggested_tests": [],
                "confidence": 1.0,
                "coverage": {
                    "complete": True, "changed_files_count": 0, "indexed_changed_files": 0,
                    "dependent_candidate_count": 0, "dependent_count": 0,
                    "dependent_returned_count": 0, "dependents_truncated": False,
                },
                "freshness": {"status": "not_checked"},
                "truncated": False,
                "truncation": {"changed_symbols": False, "likely_dependents": False, "suggested_tests": False},
            }

        cache_generation = self._cache_generation()
        cache_key = stable_hash({
            "query": "impact",
            "root": resolved_root,
            "changed": changed,
            "max_symbols": max_symbols,
            "max_dependents": max_dependents,
            "generation": cache_generation,
        })
        cached = self._impact_result_l1.get(cache_key)
        if isinstance(cached, dict):
            result = copy.deepcopy(cached)
            return self._verify_impact_candidates(result, changed, cache_generation) if verify_freshness else result

        try:
            with self._lock, closing(self._connect()) as con:
                # Bound host parameters so large diffs remain safe on every supported SQLite build.
                indexed_rows: list[sqlite3.Row] = []
                symbol_rows: list[sqlite3.Row] = []
                symbols_truncated = False
                for chunk in sqlite_batches(changed):
                    placeholders = ",".join("?" for _ in chunk)
                    indexed_rows.extend(con.execute(
                        f"SELECT path FROM files WHERE root=? AND {_root_archive_path_sql('path')} AND path IN ({placeholders})",
                        (resolved_root, *chunk),
                    ).fetchall())
                    if len(symbol_rows) < max_symbols:
                        remaining = max_symbols - len(symbol_rows)
                        fetched_symbols = con.execute(
                            f"SELECT path,name,kind,line,name_path FROM symbols WHERE root=? AND {_root_archive_path_sql('path')} AND path IN ({placeholders}) ORDER BY path,line LIMIT ?",
                            (resolved_root, *chunk, remaining),
                        ).fetchall()
                        if len(fetched_symbols) == remaining:
                            has_more_symbols = con.execute(
                                f"SELECT 1 FROM symbols WHERE root=? AND {_root_archive_path_sql('path')} AND path IN ({placeholders}) ORDER BY path,line LIMIT 1 OFFSET ?",
                                (resolved_root, *chunk, remaining),
                            ).fetchone()
                            symbols_truncated = has_more_symbols is not None
                        symbol_rows.extend(fetched_symbols)
                    elif not symbols_truncated:
                        later_symbol = con.execute(
                            f"SELECT 1 FROM symbols WHERE root=? AND {_root_archive_path_sql('path')} AND path IN ({placeholders}) LIMIT 1",
                            (resolved_root, *chunk),
                        ).fetchone()
                        if later_symbol is not None:
                            symbols_truncated = True
                symbol_rows = symbol_rows[:max_symbols]
                changed_symbols = [
                    {"name": str(r["name"]), "name_path": str(r["name_path"] or r["name"]), "kind": str(r["kind"]), "path": str(r["path"]), "line": int(r["line"])}
                    for r in symbol_rows
                ]
                names = list(dict.fromkeys(str(r["name"]) for r in symbol_rows if str(r["name"])))
                dependent_scores: dict[str, dict[str, Any]] = {}
                dependent_source_truncated = False
                import_graph_truncated = False
                dependent_scan_limit = max(200, max_dependents * 20)
                if names:
                    name_placeholders = "SELECT value FROM json_each(?)"
                    name_params = (json_dumps(names),)
                    ref_rows = con.execute(
                        f"SELECT path,name,COUNT(*) AS mentions FROM refs WHERE root=? AND {_root_archive_path_sql('path')} AND name IN ({name_placeholders}) GROUP BY path,name LIMIT ?",
                        (resolved_root, *name_params, dependent_scan_limit + 1),
                    ).fetchall()
                    if len(ref_rows) > dependent_scan_limit:
                        dependent_source_truncated = True
                    for r in ref_rows[:dependent_scan_limit]:
                        path = self._norm_rel(str(r["path"]))
                        if path in changed:
                            continue
                        item = dependent_scores.setdefault(path, {"path": path, "symbols": [], "mentions": 0})
                        name = str(r["name"])
                        if name not in item["symbols"] and len(item["symbols"]) < 8:
                            item["symbols"].append(name)
                        item["mentions"] += int(r["mentions"] or 0)
                    edge_rows = con.execute(
                        f"SELECT path,dst,kind FROM edges WHERE root=? AND {_root_archive_path_sql('path')} AND dst IN ({name_placeholders}) LIMIT ?",
                        (resolved_root, *name_params, dependent_scan_limit),
                    ).fetchall()
                    if len(edge_rows) == dependent_scan_limit:
                        has_more_edges = con.execute(
                            f"SELECT 1 FROM edges WHERE root=? AND {_root_archive_path_sql('path')} AND dst IN ({name_placeholders}) LIMIT 1 OFFSET ?",
                            (resolved_root, *name_params, dependent_scan_limit),
                        ).fetchone()
                        dependent_source_truncated = dependent_source_truncated or has_more_edges is not None
                    for r in edge_rows[:dependent_scan_limit]:
                        path = self._norm_rel(str(r["path"]))
                        if path in changed:
                            continue
                        item = dependent_scores.setdefault(path, {"path": path, "symbols": [], "mentions": 0})
                        dst = str(r["dst"])
                        if dst not in item["symbols"] and len(item["symbols"]) < 8:
                            item["symbols"].append(dst)
                        item["mentions"] += 2 if str(r["kind"]) in {"imports", "inherits"} else 1

                # Expand file-level import dependents transitively. Direct symbol
                # references alone miss tests of intermediate modules when a
                # shared module changes (shared -> core -> app -> tests).
                import_rows = con.execute(
                    f"SELECT path,dst FROM edges WHERE root=? AND {_root_archive_path_sql('path')} AND kind='imports' LIMIT ?",
                    (resolved_root, dependent_scan_limit + 1),
                ).fetchall()
                if len(import_rows) > dependent_scan_limit:
                    import_graph_truncated = True

                def module_aliases(value: str) -> set[str]:
                    normalized = str(value or "").replace("\\", "/").strip()
                    while normalized.startswith("./"):
                        normalized = normalized[2:]
                    normalized = normalized.lstrip(".")
                    suffixes = (".pyi", ".py", ".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs")
                    lowered = normalized.lower()
                    for suffix in suffixes:
                        if lowered.endswith(suffix):
                            normalized = normalized[:-len(suffix)]
                            break
                    normalized = normalized.strip("/")
                    if normalized.endswith("/__init__"):
                        normalized = normalized[:-len("/__init__")]
                    parts = [part for part in normalized.split("/") if part]
                    return {".".join(parts[index:]) for index in range(len(parts))}

                importers_by_module: dict[str, set[str]] = {}
                for import_row in import_rows[:dependent_scan_limit]:
                    importer_path = self._norm_rel(str(import_row["path"]))
                    for alias in module_aliases(str(import_row["dst"])):
                        importers_by_module.setdefault(alias, set()).add(importer_path)

                visited_paths = set(changed)
                frontier = list(changed)
                while frontier and len(visited_paths) <= dependent_scan_limit:
                    next_frontier: list[str] = []
                    for source_path in frontier:
                        for alias in module_aliases(source_path):
                            for importer_path in importers_by_module.get(alias, ()):
                                if importer_path in visited_paths:
                                    continue
                                visited_paths.add(importer_path)
                                next_frontier.append(importer_path)
                                item = dependent_scores.setdefault(
                                    importer_path, {"path": importer_path, "symbols": [], "mentions": 0}
                                )
                                item["mentions"] += 2
                    frontier = next_frontier
                if frontier:
                    import_graph_truncated = True

                dependent_candidate_count = len(dependent_scores)
                dependent_candidate_count_exact = (
                    not symbols_truncated and not dependent_source_truncated and not import_graph_truncated
                )
                if (
                    names and not symbols_truncated and dependent_source_truncated
                    and not import_graph_truncated and len(changed) <= 250
                ):
                    changed_placeholders = ",".join("?" for _ in changed)
                    path_generation = cache_generation
                    candidate_count_key = stable_hash({
                        "database": self._query_cache_generation_key,
                        "generation": path_generation,
                        "root": resolved_root,
                        "changed": sorted(set(changed)),
                        "names": sorted(set(names)),
                    })
                    cached_candidate_count = self._impact_candidate_count_l1.get(candidate_count_key)
                    if cached_candidate_count is not None:
                        dependent_candidate_count = int(cached_candidate_count)
                        dependent_candidate_count_exact = True
                    path_format_key = f"{self._query_cache_generation_key}:{path_generation}:{resolved_root}:{stable_hash(sorted(set(names)))}"
                    paths_are_canonical = (
                        self._impact_path_format_l1.get(path_format_key)
                        if cached_candidate_count is None else None
                    )
                    raw_candidate_count: int | None = None
                    if cached_candidate_count is None and paths_are_canonical is None:
                        raw_candidate_row = con.execute(
                            f"""
                            SELECT COUNT(*) AS candidate_count,
                                   MAX(CASE
                                       WHEN instr(path, char(92)) > 0
                                         OR substr(path, 1, 1) = '/'
                                         OR substr(path, -1, 1) = '/'
                                       THEN 1 ELSE 0
                                   END) AS has_noncanonical_path
                            FROM (
                                SELECT path FROM refs
                                WHERE root=? AND {_root_archive_path_sql('path')} AND name IN ({name_placeholders})
                                UNION
                                SELECT path FROM edges
                                WHERE root=? AND {_root_archive_path_sql('path')} AND dst IN ({name_placeholders})
                            ) AS candidate_paths
                            WHERE path NOT IN ({changed_placeholders})
                            """,
                            (
                                resolved_root, *name_params,
                                resolved_root, *name_params,
                                *changed,
                            ),
                        ).fetchone()
                        if raw_candidate_row is not None:
                            raw_candidate_count = int(raw_candidate_row["candidate_count"] or 0)
                            paths_are_canonical = not bool(raw_candidate_row["has_noncanonical_path"])
                            self._impact_path_format_l1.set(path_format_key, paths_are_canonical)
                    if cached_candidate_count is None and paths_are_canonical is True:
                        if raw_candidate_count is None:
                            raw_candidate_row = con.execute(
                                f"""
                                SELECT COUNT(*) FROM (
                                    SELECT path FROM refs WHERE root=? AND {_root_archive_path_sql('path')} AND name IN ({name_placeholders})
                                    UNION
                                    SELECT path FROM edges WHERE root=? AND {_root_archive_path_sql('path')} AND dst IN ({name_placeholders})
                                ) AS candidate_paths
                                WHERE path NOT IN ({changed_placeholders})
                                """,
                                (
                                    resolved_root, *name_params,
                                    resolved_root, *name_params,
                                    *changed,
                                ),
                            ).fetchone()
                            if raw_candidate_row is not None:
                                raw_candidate_count = int(raw_candidate_row[0])
                        if raw_candidate_count is not None:
                            dependent_candidate_count = raw_candidate_count
                            dependent_candidate_count_exact = True
                    elif cached_candidate_count is None and paths_are_canonical is False:
                        normalized_candidate_row = con.execute(
                            f"""
                            SELECT COUNT(*) FROM (
                                SELECT trim(replace(path, char(92), '/'), '/') AS normalized_path
                                FROM refs WHERE root=? AND {_root_archive_path_sql('path')} AND name IN ({name_placeholders})
                                UNION
                                SELECT trim(replace(path, char(92), '/'), '/') AS normalized_path
                                FROM edges WHERE root=? AND {_root_archive_path_sql('path')} AND dst IN ({name_placeholders})
                            )
                            WHERE normalized_path NOT IN ({changed_placeholders})
                            """,
                            (
                                resolved_root, *name_params,
                                resolved_root, *name_params,
                                *changed,
                            ),
                        ).fetchone()
                        if normalized_candidate_row is not None:
                            dependent_candidate_count = int(normalized_candidate_row[0])
                            dependent_candidate_count_exact = True
                    if cached_candidate_count is None and dependent_candidate_count_exact:
                        self._impact_candidate_count_l1.set(candidate_count_key, dependent_candidate_count)

                likely_dependents = sorted(dependent_scores.values(), key=lambda x: (-int(x["mentions"]), str(x["path"])))[:max_dependents]
                indexed_test_rows = con.execute(
                    f"SELECT path FROM files WHERE root=? AND {_root_archive_path_sql('path')} AND (lower(path) LIKE '%test%' OR lower(path) LIKE '%spec%') LIMIT 501",
                    (resolved_root,),
                ).fetchall()
                indexed_tests_truncated = len(indexed_test_rows) > 500
                indexed_tests = [self._norm_rel(str(r[0])) for r in indexed_test_rows[:500]]
        except sqlite3.DatabaseError as exc:
            return {
                "success": False,
                "root": resolved_root,
                "error": str(exc),
                "busy": is_busy_error(exc),
                "confidence": 0.0,
                "graph_complete": False,
                "changed_symbols": [],
                "likely_dependents": [],
                "suggested_tests": [],
                "coverage": {
                    "complete": False,
                    "changed_files_count": len(changed),
                    "indexed_changed_files": 0,
                    "dependent_candidate_count": 0,
                    "dependent_candidate_count_exact": False,
                    "dependent_count": None,
                    "dependent_returned_count": 0,
                    "dependents_truncated": None,
                },
                "freshness": {"status": "not_checked"},
                "truncated": False,
                "truncation": {"changed_symbols": False, "likely_dependents": False, "suggested_tests": False},
            }

        changed_stems = {Path(p).stem.lower().replace("test_", "").replace("_test", "").replace(".test", "").replace("_spec", "").replace(".spec", "") for p in changed}
        symbol_names_l = [str(x["name"]).lower() for x in changed_symbols]
        test_scores: list[tuple[int, str]] = []
        for path in indexed_tests:
            stem = Path(path).stem.lower().replace("test_", "").replace("_test", "").replace(".test", "").replace("_spec", "").replace(".spec", "")
            score = sum(3 for changed_stem in changed_stems if changed_stem and (changed_stem in stem or stem in changed_stem))
            score += sum(1 for name in symbol_names_l[:20] if name and name in path.lower())
            if score:
                test_scores.append((score, path))
        for item in likely_dependents:
            path = str(item["path"])
            if self._is_test_path(path):
                test_scores.append((max(1, int(item["mentions"])), path))
        best_test_scores: dict[str, int] = {}
        for score, path in test_scores:
            best_test_scores[path] = max(score, best_test_scores.get(path, 0))
        sorted_test_scores = sorted(((score, path) for path, score in best_test_scores.items()), key=lambda x: (-x[0], x[1]))
        suggested_tests_truncated = indexed_tests_truncated or len(sorted_test_scores) > 20
        suggested_tests = [{"path": path, "score": score} for score, path in sorted_test_scores[:20]]
        sorted_dependents = sorted(dependent_scores.values(), key=lambda x: (-int(x["mentions"]), str(x["path"])))
        dependents_truncated = (
            symbols_truncated or dependent_source_truncated or import_graph_truncated
            or len(sorted_dependents) > max_dependents
        )
        likely_dependents = sorted_dependents[:max_dependents]
        indexed_count = len(indexed_rows)
        changed_file_coverage = indexed_count / max(1, len(changed))
        confidence = round(min(0.98, 0.35 + 0.60 * changed_file_coverage + (0.03 if changed_symbols else 0.0)), 3)
        truncation = {
            "changed_symbols": symbols_truncated,
            "likely_dependents": dependents_truncated,
            "suggested_tests": suggested_tests_truncated,
        }
        truncated = any(truncation.values())
        result = {
            "success": True,
            "root": resolved_root,
            "changed_symbols": changed_symbols,
            "likely_dependents": likely_dependents,
            "suggested_tests": suggested_tests,
            "confidence": confidence,
            "indexed_changed_files": indexed_count,
            "changed_files_count": len(changed),
            "coverage": {
                "complete": indexed_count == len(changed) and not truncated,
                "scope": "indexed_changed_files_and_candidates",
                "changed_files_count": len(changed),
                "indexed_changed_files": indexed_count,
                "changed_file_ratio": round(changed_file_coverage, 3),
                "dependent_candidate_count": dependent_candidate_count,
                "dependent_candidate_count_exact": dependent_candidate_count_exact,
                "dependent_count": dependent_candidate_count if dependent_candidate_count_exact else None,
                "dependent_returned_count": len(likely_dependents),
                "dependents_truncated": dependents_truncated,
            },
            "freshness": {"status": "not_checked"},
            "truncated": truncated,
            "truncation": truncation,
            "graph_complete": False,
            # A non-truncated scan of indexed rows says nothing about files
            # outside this partial index.
            "dependency_graph_complete": False,
            "indexed_candidate_graph_complete": not truncated,
        }
        self._impact_result_l1.set(cache_key, result)
        return self._verify_impact_candidates(copy.deepcopy(result), changed, cache_generation) if verify_freshness else result

    def _verify_impact_candidates(self, result: dict[str, Any], changed: list[str], generation: int) -> dict[str, Any]:
        """Check bounded returned candidates against current content, never the entire graph."""
        candidate_paths = list(dict.fromkeys(
            path for key in ("likely_dependents", "suggested_tests")
            for item in result.get(key, [])[:8]
            if isinstance(item, dict) and isinstance(path := item.get("path"), str) and path
        ))
        all_paths = list(dict.fromkeys([*changed, *candidate_paths]))
        # Reserve space for both changed source files and returned consumers/tests.
        selected = list(dict.fromkeys([*changed[:48], *candidate_paths]))[:64]
        freshness = self._candidate_freshness(result["root"], selected, content_hash=True)
        freshness["scope"] = "changed_and_returned_impact_candidates"
        freshness["requested_path_count"] = len(all_paths)
        freshness["omitted_path_count"] = len(set(all_paths) - set(selected))
        freshness["index_generation_stable"] = self._cache_generation() == generation
        if not freshness["index_generation_stable"]:
            freshness["status"] = "index_changed_during_verification"
        elif freshness["omitted_path_count"] and freshness.get("status") == "verified_current_candidates":
            freshness["status"] = "verification_incomplete"
        freshness["complete"] = False
        result["freshness"] = freshness
        return result

