# Service repo search module extracted from services.py
from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from .search_modes import (
    canonical_search_mode,
    default_search_mode,
    deduplicate_search_files,
    expand_semantic_query,
    fuse_search_results,
    lexical_precision_query,
    prefers_lexical_precision,
    repository_search_timeout,
    search_execution_stopped,
)
from .search_pagination import MAX_PAGE_SIZE, MAX_PAGE_WINDOW, pagination_bounds_error

logger = logging.getLogger("local_ai_hub.services")


from .service_repo_search_lexical import (
    _SOURCE_FOCUS_TERMS,
    _SOURCE_SUFFIXES,
    _context_path_priority,
    _hint_directory_candidates,
    _repo_search_lexical,
    _source_focused_query,
    enclosing_symbol_at_line,
)


def _rag_fragment_matches_source(fragment: str, source: str) -> bool:
    """Verify indexed text while accounting for deterministic AST chunk wrappers."""
    normalized_fragment = fragment.replace("\r\n", "\n").replace("\r", "\n")
    normalized_source = source.replace("\r\n", "\n").replace("\r", "\n")
    if normalized_fragment in normalized_source:
        return True
    marker = "# [Module context]\n"
    if not normalized_fragment.startswith(marker):
        return False
    _preamble, separator, body = normalized_fragment[len(marker):].partition("\n\n")
    if not separator or not body:
        return False
    method_wrapper = re.search(r"(?m)^    # method [^\n]*\n", body)
    if method_wrapper is not None:
        body = body[method_wrapper.end():]
    return bool(body) and body in normalized_source


def repo_search(
    self,
    root: str,
    query: str,
    top_k: int = 12,
    context_lines: int | None = None,
    enrich: bool = False,
    path_hints: list[Any] | tuple[Any, ...] | None = None,
    scope: str = "repo_search",
    *,
    limit: int | None = None,
    offset: int = 0,
    search_mode: str | None = None,
    exact_count: bool = True,
) -> dict[str, Any]:
    if type(exact_count) is not bool:
        return {
            "success": False, "error": "exact_count must be a boolean",
            "status_code": 400, "terminal": True, "retryable": False,
            "root": root, "results": [], "total_matches": 0,
            "count_exact": False, "has_more": False,
        }
    mode = default_search_mode(query) if search_mode is None else canonical_search_mode(search_mode)
    if mode is None:
        return {
            "success": False, "error": "search_mode must be lexical, rag, or hybrid",
            "status_code": 400, "terminal": True, "retryable": False,
            "search_mode": search_mode, "results": [], "total_matches": 0,
            "count_exact": False, "has_more": False,
        }
    page_limit = max(1, int(top_k)) if limit is None else limit
    bounds_error = pagination_bounds_error(page_limit, offset)
    if bounds_error:
        return {
            "success": False, "error": bounds_error, "status_code": 400,
            "root": root, "results": [], "total_matches": 0, "has_more": False,
            "limit": page_limit if type(page_limit) is int and 1 <= page_limit <= MAX_PAGE_SIZE else None,
            "offset": offset if type(offset) is int and 0 <= offset < MAX_PAGE_WINDOW else None,
            "search_mode": mode,
        }
    if mode == "lexical":
        lexical_query = (
            lexical_precision_query(query)
            if prefers_lexical_precision(query) else query
        )
        result = self._repo_search_lexical(
            root, lexical_query, top_k, context_lines, enrich, path_hints, scope,
            limit=page_limit, offset=offset, exact_count=exact_count,
            installation_intent_priority=not prefers_lexical_precision(query),
        )
        result.update({
            "search_mode": "lexical", "result_source": "lexical",
            "index_state": "current_sources" if result.get("success") is True else "unavailable",
            "coverage_complete": (
                result.get("success") is True
                and result.get("truncated") is False
                and result.get("has_more") is False
                and result.get("read_errors", 0) == 0
            ),
            "reranker": {"requested": False, "used": False, "degraded": False},
        })
        for item in result.get("results", []) if result.get("success") is True else []:
            if isinstance(item, dict):
                item["sources"] = ["lexical"]
                item["result_source"] = "lexical"
        return result

    if mode == "hybrid" and prefers_lexical_precision(query):
        lexical_query = lexical_precision_query(query)
        result = self._repo_search_lexical(
            root, lexical_query, top_k, context_lines, enrich, path_hints, scope,
            limit=page_limit, offset=offset, exact_count=exact_count,
        )
        succeeded = result.get("success") is True
        lexical_count = result.get("total_matches")
        lexical_count_exact = result.get("count_exact") is True
        result.update({
            "search_mode": "hybrid",
            "result_source": "lexical",
            "coverage_complete": (
                succeeded
                and result.get("truncated") is False
                and result.get("has_more") is False
                and result.get("read_errors", 0) == 0
            ),
            "degraded": not succeeded,
            "degradation_reason": None if succeeded else result.get("error", "lexical_search_unavailable"),
            "index_state": "current_sources" if succeeded else "unavailable",
            "candidate_freshness": "verified_against_current_sources" if succeeded else "unknown",
            "lexical_total_matches": lexical_count,
            "lexical_count_exact": lexical_count_exact,
            "rag_candidate_count": 0,
            "rag_candidate_count_exact": False,
            "rag_search_skipped": True,
            "rag_skip_reason": "exact_lexical_precision",
            "reranker": {
                "requested": bool(self.config.get("features", {}).get("reranker", True)),
                "used": False,
                "degraded": not succeeded,
                "skipped_reason": "exact_lexical_precision",
            },
        })
        for item in result.get("results", []) if succeeded else []:
            if isinstance(item, dict):
                item["sources"] = ["lexical"]
                item["result_source"] = "lexical"
        return result

    semantic_query, query_expansion_applied = expand_semantic_query(query)
    candidate_query = semantic_query
    # Search fallback needs both the user's original lexical anchors and
    # the expansion terms. RepoTools separates added terms for ranking, so
    # passing only the suffix can hide exact source wording (for example
    # "installation" when expansion contains only "install").
    rag_rows, rag_meta = self._repo_rag_search(
        root,
        semantic_query,
        max(32, page_limit),
    )
    search_cache = rag_meta.get("search_cache")
    search_cache_fields = {}
    if isinstance(search_cache, dict):
        if type(search_cache.get("hit")) is bool:
            search_cache_fields["cache_hit"] = search_cache["hit"]
        if type(search_cache.get("coalesced")) is bool:
            search_cache_fields["coalesced"] = search_cache["coalesced"]

    if search_execution_stopped(rag_meta):
        # A normal HTTP response preserves lower-layer status without transport replay.
        return {
            **{key: value for key, value in rag_meta.items() if key != "search_cache"},
            **search_cache_fields,
            "success": False, "root": root, "search_mode": mode, "results": [],
            "total_matches": None, "count_exact": False, "has_more": None,
            "offset": offset, "limit": page_limit, "coverage_complete": False,
            "degraded": True, "index_state": "unknown",
        }

    def lexical_preprocessed_candidates() -> tuple[str, ...] | None:
        preprocessor = getattr(self, "preprocessor", None)
        if prefers_lexical_precision(query) or preprocessor is None:
            return None
        try:
            candidate_limit = 128
            candidates = preprocessor.candidate_paths(
                root, candidate_query, candidate_limit,
            )
            return tuple(candidates[:candidate_limit]) if candidates else None
        except (OSError, sqlite3.Error, ValueError) as candidate_exc:
            logger.debug(
                "Hybrid preprocessing candidates skipped (%s)",
                type(candidate_exc).__name__,
            )
            return None

    if prefers_lexical_precision(query):
        literal = query.casefold()
        rag_rows = [
            row for row in rag_rows
            if literal in str(row.get("text", "")).casefold()
            or literal in str(row.get("path", "")).casefold()
        ]
    if rag_meta.get("success") is not True:
        if mode == "hybrid":
            lexical_candidate_paths = lexical_preprocessed_candidates()
            result = self._repo_search_lexical(
                root, query, top_k, context_lines, enrich, path_hints, scope,
                limit=page_limit, offset=offset, exact_count=False,
                candidate_paths=lexical_candidate_paths,
                candidate_query=(
                    candidate_query
                    if query_expansion_applied
                    else None
                ),
                installation_intent_priority=(
                    mode == "hybrid" and not prefers_lexical_precision(query)
                ),
            )
            result["results"] = deduplicate_search_files(result.get("results", []))
            result.update({
                "search_mode": "hybrid", "result_source": "lexical_fallback",
                "coverage_complete": False, "degraded": True,
                "total_matches": None, "count_exact": False, "has_more": None,
                "degradation_reason": rag_meta.get("reason", "rag_unavailable"),
                "index_state": rag_meta.get("index_state", "unavailable"),
                "index_coverage": rag_meta.get("index_coverage", "unknown_or_partial"),
                "candidate_freshness": "verified_against_current_sources",
                "lexical_total_matches": None, "lexical_count_exact": False,
                "reranker": rag_meta.get("reranker", {"requested": True, "used": False, "degraded": True}),
                "lexical_candidate_source": (
                    "preprocess_index" if lexical_candidate_paths else "current_source_scan"
                ),
                "lexical_preprocessed_candidate_count": len(lexical_candidate_paths or ()),
                "query_expansion_applied": query_expansion_applied,
            })
            for item in result.get("results", []):
                if isinstance(item, dict):
                    item["sources"] = ["lexical"]
                    item["result_source"] = "lexical_fallback"
            return result
        return {
            "success": False, "status_code": 503, "root": root,
            "search_mode": "rag", "results": [], "total_matches": None,
            "count_exact": False, "has_more": None, "offset": offset,
            "limit": page_limit, "coverage_complete": False,
            "degraded": True, "degradation_reason": rag_meta.get("reason", "rag_unavailable"),
            "index_state": rag_meta.get("index_state", "unavailable"),
            "reranker": rag_meta.get("reranker", {"requested": True, "used": False, "degraded": True}),
            **search_cache_fields,
        }

    if mode == "rag":
        rows = rag_rows[offset : offset + page_limit]
        return {
            "success": True, "root": root, "search_mode": "rag",
            "result_source": "rag", "results": rows,
            "total_matches": None, "count_exact": False,
            "candidate_count": len(rag_rows), "candidate_count_exact": False,
            "has_more": True if offset + len(rows) < len(rag_rows) else None,
            "offset": offset, "limit": page_limit, "coverage_complete": False,
            "index_state": rag_meta.get("index_state", "unknown"),
            "index_coverage": rag_meta.get("index_coverage", "unknown_or_partial"),
            "candidate_freshness": rag_meta.get("candidate_freshness", "verified_against_current_sources"),
            "source_validation": rag_meta.get("source_validation", {}),
            "stale_candidate_count": rag_meta.get("stale_candidate_count", 0),
            "stale_candidate_reasons": rag_meta.get("stale_candidate_reasons", {}),
            "stale_candidate_details": rag_meta.get("stale_candidate_details", []),
            "index_revision": rag_meta.get("index_revision"),
            "query_expansion_applied": query_expansion_applied,
            "degraded": bool(rag_meta.get("degraded")),
            "degradation_reason": rag_meta.get("degradation_reason"),
            "reranker": rag_meta.get("reranker", {}),
            **search_cache_fields,
        }

    if not rag_rows and rag_meta.get("degraded"):
        lexical_candidate_paths = lexical_preprocessed_candidates()
        result = self._repo_search_lexical(
            root, query, top_k, context_lines, enrich, path_hints, scope,
            limit=page_limit, offset=offset, exact_count=False,
            candidate_paths=lexical_candidate_paths,
            candidate_query=(
                candidate_query
                if query_expansion_applied
                else None
            ),
            installation_intent_priority=(
                mode == "hybrid" and not prefers_lexical_precision(query)
            ),
        )
        result.update({
            "search_mode": "hybrid", "result_source": "lexical_fallback",
            "coverage_complete": False, "degraded": True,
            "total_matches": None, "count_exact": False, "has_more": None,
            "degradation_reason": rag_meta.get("degradation_reason") or rag_meta.get("fallback") or rag_meta.get("reason") or "rag_backend_degraded",
            "index_state": rag_meta.get("index_state", "unknown"),
            "index_coverage": rag_meta.get("index_coverage", "unknown_or_partial"),
            "candidate_freshness": rag_meta.get("candidate_freshness", "unknown"),
            "source_validation": rag_meta.get("source_validation", {}),
            "stale_candidate_count": rag_meta.get("stale_candidate_count", 0),
            "stale_candidate_reasons": rag_meta.get("stale_candidate_reasons", {}),
            "stale_candidate_details": rag_meta.get("stale_candidate_details", []),
            "lexical_total_matches": None, "lexical_count_exact": False,
            "lexical_candidate_source": (
                "preprocess_index" if lexical_candidate_paths else "current_source_scan"
            ),
            "lexical_preprocessed_candidate_count": len(lexical_candidate_paths or ()),
            "rag_candidate_count": 0, "rag_candidate_count_exact": False,
            "reranker": rag_meta.get("reranker", {}),
            "query_expansion_applied": query_expansion_applied,
            **search_cache_fields,
        })
        result["results"] = deduplicate_search_files(result.get("results", []))
        for item in result.get("results", []):
            if isinstance(item, dict):
                item["sources"] = ["lexical"]
                item["result_source"] = "lexical_fallback"
        return result

    lexical_limit = min(MAX_PAGE_SIZE, max(page_limit + offset, 64))
    lexical_candidate_query = candidate_query if query_expansion_applied else query
    lexical_candidate_paths = None
    preprocessor = getattr(self, "preprocessor", None)
    if not prefers_lexical_precision(query) and preprocessor is not None:
        try:
            candidates = preprocessor.candidate_paths(
                root, lexical_candidate_query, max(64, page_limit),
            )
            if candidates:
                lexical_candidate_paths = tuple(candidates[:64])
        except (OSError, sqlite3.Error, ValueError) as candidate_exc:
            logger.debug(
                "Preprocessing hybrid lexical candidates skipped (%s)",
                type(candidate_exc).__name__,
            )
    lexical_result = self._repo_search_lexical(
        root, query, top_k, context_lines, enrich, path_hints, scope,
        limit=lexical_limit, offset=0, exact_count=False,
        candidate_paths=lexical_candidate_paths,
        candidate_query=lexical_candidate_query if lexical_candidate_paths and query_expansion_applied else None,
        installation_intent_priority=(
            mode == "hybrid" and not prefers_lexical_precision(query)
        ),
    )
    if lexical_result.get("success") is not True:
        return {
            "success": True, "root": root, "search_mode": "hybrid",
            "result_source": "rag_fallback", "results": rag_rows[offset:offset + page_limit],
            "total_matches": None, "count_exact": False,
            "candidate_count": len(rag_rows), "candidate_count_exact": False,
            "has_more": None, "offset": offset, "limit": page_limit,
            "coverage_complete": False, "degraded": True,
            "degradation_reason": "lexical_backend_unavailable",
            "index_state": rag_meta.get("index_state", "unknown"),
            "index_coverage": rag_meta.get("index_coverage", "unknown_or_partial"),
            "candidate_freshness": rag_meta.get("candidate_freshness", "verified_against_current_sources"),
            "source_validation": rag_meta.get("source_validation", {}),
            "stale_candidate_count": rag_meta.get("stale_candidate_count", 0),
            "stale_candidate_reasons": rag_meta.get("stale_candidate_reasons", {}),
            "stale_candidate_details": rag_meta.get("stale_candidate_details", []),
            "query_expansion_applied": query_expansion_applied,
            "reranker": rag_meta.get("reranker", {}),
            **search_cache_fields,
        }
    fused, fusion_meta = fuse_search_results(
        lexical_result.get("results", []), rag_rows, limit=page_limit, offset=offset,
        lexical_first=(
            prefers_lexical_precision(query)
            or bool(lexical_candidate_paths and query_expansion_applied)
        ),
    )
    return {
        "success": True, "root": root, "search_mode": "hybrid",
        "result_source": "hybrid", "results": fused, **fusion_meta,
        "lexical_priority": prefers_lexical_precision(query),
        "lexical_total_matches": lexical_result.get("total_matches"),
        "lexical_count_exact": lexical_result.get("count_exact") is True,
        "lexical_candidate_source": "preprocessed_index" if lexical_candidate_paths else "current_source_scan",
        "lexical_preprocessed_candidate_count": len(lexical_candidate_paths or ()),
        "rag_candidate_count": len(rag_rows), "rag_candidate_count_exact": False,
        "coverage_complete": False,
        "index_state": rag_meta.get("index_state", "unknown"),
        "index_coverage": rag_meta.get("index_coverage", "unknown_or_partial"),
        "candidate_freshness": rag_meta.get("candidate_freshness", "verified_against_current_sources"),
        "source_validation": rag_meta.get("source_validation", {}),
        "stale_candidate_count": rag_meta.get("stale_candidate_count", 0),
        "stale_candidate_reasons": rag_meta.get("stale_candidate_reasons", {}),
        "stale_candidate_details": rag_meta.get("stale_candidate_details", []),
        "index_revision": rag_meta.get("index_revision"),
        "query_expansion_applied": query_expansion_applied,
        "degraded": bool(rag_meta.get("degraded")),
        "degradation_reason": rag_meta.get("degradation_reason"),
        "reranker": rag_meta.get("reranker", {}),
        **search_cache_fields,
    }

def _repo_rag_search(self, root: str, query: str, top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rag = getattr(self, "rag", None)
    reranker_requested = bool(self.config.get("features", {}).get("reranker", True))
    if rag is None or not self.config.get("features", {}).get("rag", True):
        return [], {"success": False, "reason": "rag_disabled", "index_state": "unavailable",
                    "reranker": {"requested": reranker_requested, "used": False,
                                 "degraded": reranker_requested}}
    try:
        base = Path(root).expanduser().resolve(strict=True)
        if not base.is_dir():
            raise ValueError("repository root is not a directory")
        workspace = rag.workspace_id(str(base))
        rag.require_workspace_root(workspace=workspace, root=str(base))
        use_reranker = reranker_requested
        has_chunks = getattr(rag, "has_workspace_chunks", None)
        if callable(has_chunks):
            workspace_indexed = has_chunks(workspace=workspace)
        else:
            workspaces = {
                str(item.get("workspace")): item
                for item in rag.list_workspaces() if isinstance(item, dict)
            }
            workspace_info = workspaces.get(workspace)
            workspace_indexed = bool(
                workspace_info and int(workspace_info.get("files", 0)) > 0
            )
        if not workspace_indexed:
            return [], {
                "success": False, "reason": "rag_index_missing", "index_state": "missing",
                "reranker": {"requested": use_reranker, "used": False,
                             "degraded": bool(use_reranker)},
            }
        deadline = time.perf_counter() + repository_search_timeout(self.config)
        raw = rag.search(query, workspace=workspace, top_k=min(MAX_PAGE_SIZE, max(1, top_k)),
                         use_reranker=use_reranker, semantic_only=True, priority=1,
                         deadline=deadline)
        if search_execution_stopped(raw):
            fields = (
                "error", "error_code", "in_progress", "outcome_unknown", "cancelled",
                "timed_out", "terminal", "retryable", "retry_after_seconds", "owner_age_seconds",
                "operation_not_started", "request_not_sent", "cleanup_unconfirmed", "job_id",
                "scheduler_state", "wait_reason", "index_revision", "search_cache",
            )
            return [], {"success": False, **{key: raw[key] for key in fields if key in raw}}
        if not isinstance(raw, dict) or raw.get("success") is not True:
            raise RuntimeError("rag_search_failed")
        project_context = rag.project_context(base)
        max_bytes = int(self.config.get("rag", {}).get("max_file_bytes", 2_000_000))
        resilience = self.config.get("resilience", {})
        if not isinstance(resilience, dict):
            resilience = {}
        source_validation_timeout = max(
            0.1,
            min(5.0, float(resilience.get("repository_search_source_validation_timeout_seconds", 1.5))),
        )
        source_validation_limit_bytes = max(
            1,
            min(64_000_000, int(resilience.get("repository_search_source_validation_max_bytes", 8_000_000))),
        )
        source_validation_deadline = min(deadline, time.perf_counter() + source_validation_timeout)
        source_validation_bytes = 0
        source_validation_candidates_checked = 0
        source_validation_reason: str | None = None
        valid: list[dict[str, Any]] = []
        stale = 0
        stale_reasons = {
            "source_changed_during_read": 0,
            "source_read_failed": 0,
            "fragment_mismatch": 0,
        }
        stale_details: list[dict[str, Any]] = []
        source_cache: dict[str, tuple[str, int, int]] = {}
        seen_paths: set[str] = set()
        for candidate in raw.get("results", []):
            if time.perf_counter() >= source_validation_deadline:
                source_validation_reason = "time_limit"
                break
            if not isinstance(candidate, dict):
                continue
            rel = candidate.get("path")
            if type(rel) is not str or not rel or "\x00" in rel:
                continue
            rel_path = Path(rel)
            if rel_path.is_absolute() or ".." in rel_path.parts:
                continue
            authorized_rel: str | None = None
            try:
                target = (base / rel_path).resolve(strict=True)
                target.relative_to(base)
                stat = target.stat()
                if not target.is_file() or stat.st_size > max_bytes:
                    continue
                rel_key = os.path.normcase(target.relative_to(base).as_posix())
                if rel_key in seen_paths:
                    continue
                allowed, kind = rag._project_path_decision(base, target, project_context,
                                                           phase="search", size_bytes=int(stat.st_size))
                if not allowed or kind == "binary":
                    continue
                authorized_rel = target.relative_to(base).as_posix()
                fragment = str(candidate.get("text") or "")
                source_meta = source_cache.get(rel_key)
                if source_meta is None:
                    source_size = int(stat.st_size)
                    if source_validation_bytes + source_size > source_validation_limit_bytes:
                        source_validation_reason = "byte_limit"
                        break
                    source_chunks: list[bytes] = []
                    remaining_bytes = source_size
                    try:
                        with target.open("rb") as source_stream:
                            while remaining_bytes:
                                if time.perf_counter() >= source_validation_deadline:
                                    raise TimeoutError("repository search source validation deadline exceeded")
                                chunk = source_stream.read(min(64 * 1024, remaining_bytes))
                                if not chunk:
                                    raise OSError("source file ended before its stat size")
                                source_chunks.append(chunk)
                                source_validation_bytes += len(chunk)
                                remaining_bytes -= len(chunk)
                    except TimeoutError:
                        source_validation_reason = "time_limit"
                        break
                    source = b"".join(source_chunks).decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
                    after_stat = target.stat()
                    if (after_stat.st_mtime_ns, after_stat.st_size) != (stat.st_mtime_ns, stat.st_size):
                        stale += 1
                        reason = "source_changed_during_read"
                        stale_reasons[reason] += 1
                        if len(stale_details) < 32:
                            detail = {"path": authorized_rel, "reason": reason}
                            if type(candidate.get("chunk_no")) is int:
                                detail["chunk_no"] = candidate["chunk_no"]
                            stale_details.append(detail)
                        continue
                    source_meta = (source, int(after_stat.st_mtime_ns), int(after_stat.st_size))
                    source_cache[rel_key] = source_meta
                source = source_meta[0]
                source_validation_candidates_checked += 1
                if not fragment or not _rag_fragment_matches_source(fragment, source):
                    stale += 1
                    reason = "fragment_mismatch"
                    stale_reasons[reason] += 1
                    if len(stale_details) < 32:
                        detail = {"path": authorized_rel, "reason": reason}
                        if type(candidate.get("chunk_no")) is int:
                            detail["chunk_no"] = candidate["chunk_no"]
                        stale_details.append(detail)
                    continue
            except (OSError, ValueError):
                stale += 1
                reason = "source_read_failed"
                stale_reasons[reason] += 1
                if authorized_rel is not None and len(stale_details) < 32:
                    detail = {"path": authorized_rel, "reason": reason}
                    if type(candidate.get("chunk_no")) is int:
                        detail["chunk_no"] = candidate["chunk_no"]
                    stale_details.append(detail)
                continue
            item = dict(candidate)
            item["path"] = target.relative_to(base).as_posix()
            item["sources"] = ["rag"]
            item["result_source"] = "rag"
            item["source_mtime_ns"] = source_meta[1]
            item["source_size_bytes"] = source_meta[2]
            valid.append(item)
            seen_paths.add(rel_key)
        source_validation_incomplete = source_validation_reason is not None
        source_validation = {
            "complete": not source_validation_incomplete,
            "candidates_checked": source_validation_candidates_checked,
            "bytes_read": source_validation_bytes,
            "limit_bytes": source_validation_limit_bytes,
            "limit_seconds": source_validation_timeout,
            "reason": source_validation_reason,
        }
        degraded = bool(
            raw.get("degraded") or stale or raw.get("reindex_required")
            or source_validation_incomplete
        )
        raw_fallbacks = raw.get("fallbacks", [])
        if not isinstance(raw_fallbacks, list):
            raw_fallbacks = []
        if source_validation_reason:
            reason = f"source_validation_{source_validation_reason}"
        else:
            reason = "stale_or_denied_candidates" if stale else (
                raw.get("fallback") or (raw_fallbacks[0] if raw_fallbacks else None)
            )
        if raw.get("degraded") and not reason:
            reason = "rag_backend_degraded"
        return valid, {
            "success": True,
            "index_state": "stale" if (stale or raw.get("reindex_required")) else "available",
            "index_coverage": "unknown_or_partial",
            "candidate_freshness": (
                "partially_verified" if stale or source_validation_incomplete
                else "verified_against_current_sources"
            ),
            "stale_candidate_count": stale,
            "stale_candidate_reasons": stale_reasons,
            "stale_candidate_details": stale_details,
            "source_validation": source_validation,
            "index_revision": raw.get("index_revision"), "degraded": degraded,
            "degradation_reason": reason,
            "search_cache": raw.get("search_cache") if isinstance(raw.get("search_cache"), dict) else {},
            "reranker": {"requested": use_reranker, "used": raw.get("reranked") is True,
                         "degraded": bool(use_reranker and raw.get("reranked") is not True),
                         "degradation_reasons": list(raw.get("fallbacks", [])) if isinstance(raw.get("fallbacks"), list) else []},
        }
    except Exception as exc:
        return [], {"success": False, "reason": type(exc).__name__, "index_state": "unavailable",
                    "reranker": {"requested": reranker_requested, "used": False,
                                 "degraded": reranker_requested}}


__all__ = [
    "repo_search",
    "_repo_rag_search",
    "_repo_search_lexical",
    "_hint_directory_candidates",
    "enclosing_symbol_at_line",
    "_source_focused_query",
    "_context_path_priority",
    "_rag_fragment_matches_source",
    "_SOURCE_FOCUS_TERMS",
    "_SOURCE_SUFFIXES",
]
