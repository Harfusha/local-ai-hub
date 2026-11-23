# Lexical search engine extracted from service_repo_search.py
from __future__ import annotations

import logging
import math
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from .cache import stable_hash
from .features import rollout_feature_enabled
from .normalizer import normalize_query
from .search_modes import prefers_lexical_precision
from .search_pagination import MAX_PAGE_SIZE, MAX_PAGE_WINDOW, pagination_bounds_error
from .state_paths import configured_state_dir
from .treesitter_parser import parse_treesitter

logger = logging.getLogger("local_ai_hub.services")


def _safe_int(val: Any, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    if isinstance(val, bool) or val is None:
        return default
    try:
        if isinstance(val, float) and not math.isfinite(val):
            return default
        res = int(val)
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res


_SOURCE_FOCUS_TERMS = (
    "source", "code", "implementation", "implement", "bug", "fix",
    "refactor", "symbol", "function", "class", "test", "audit",
    "kód", "kod", "oprava",
)
_SOURCE_SUFFIXES = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".go", ".rs", ".java", ".kt", ".cs", ".c", ".h", ".cc", ".cpp",
    ".hpp", ".sql", ".html", ".css", ".scss",
})


def _source_focused_query(query: str) -> bool:
    lowered = query.casefold()
    return any(term in lowered for term in _SOURCE_FOCUS_TERMS)


def _context_path_priority(
    relative: str, *, source_focused: bool, override_match: bool,
) -> int:
    if override_match:
        return 0
    if not source_focused:
        return 1
    normalized = relative.replace("\\", "/").casefold()
    parts = normalized.split("/")
    suffix = Path(normalized).suffix
    filename = parts[-1] if parts else ""
    if (
        filename.startswith("test_")
        or filename.endswith("_test.py")
        or any(part in {"test", "tests", "fixture", "fixtures"} for part in parts[:-1])
    ):
        return 2
    if suffix in _SOURCE_SUFFIXES and not any(part in {"docs", "doc", "plans"} for part in parts[:-1]):
        return 1
    return 3


def enclosing_symbol_at_line(source: str, path: str, line: int) -> dict[str, Any] | None:
    """Return the smallest existing Tree-sitter symbol spanning one source line."""
    if not isinstance(source, str) or not isinstance(path, str) or "\x00" in path:
        return None
    line_num = _safe_int(line, default=-1)
    if line_num <= 0:
        return None
    try:
        language = Path(path).suffix.lower().lstrip(".")
    except Exception:
        return None
    parsed = parse_treesitter(source, language)
    if not parsed:
        return None
    symbols, _, _ = parsed
    matches = [
        symbol for symbol in symbols
        if int(symbol.get("line", 0) or 0) <= line_num <= int(symbol.get("end_line", 0) or 0)
    ]
    if not matches:
        return None
    symbol = min(matches, key=lambda item: int(item.get("end_line", 0) or 0) - int(item.get("line", 0) or 0))
    return {
        key: symbol[key] for key in ("name", "kind", "line", "end_line", "name_path")
        if key in symbol
    }


def _hint_directory_candidates(file_inventory, hint_root: Path, target: Path):
    """Filter tracked paths lexically; path policy validates before reading."""
    for raw_candidate in file_inventory:
        try:
            candidate = Path(raw_candidate)
            if candidate.is_absolute():
                relative = candidate.relative_to(hint_root)
            else:
                if candidate.drive:
                    continue
                relative = candidate
            if any(part in {".."} for part in relative.parts):
                continue
            candidate = hint_root / relative
            candidate.relative_to(hint_root)
        except (TypeError, ValueError):
            continue
        if candidate == target or target in candidate.parents:
            yield candidate


def _extract_request_hints(path_hints: Any) -> list[Any]:
    from .project_config import PathHint
    request_hints: list[PathHint] = []
    allowed_hint_fields = {
        "path", "purpose", "scope", "evidence_id", "provenance",
        "repository_revision", "config_digest", "expires_at",
    }
    if isinstance(path_hints, (list, tuple)):
        for item in path_hints[:64]:
            if isinstance(item, PathHint):
                hint = item
            elif isinstance(item, dict) and not (set(item) - allowed_hint_fields):
                try:
                    hint = PathHint(**item)
                except TypeError:
                    continue
            else:
                continue
            if (
                isinstance(hint.path, str)
                and isinstance(hint.purpose, str)
                and isinstance(hint.scope, str)
                and all(
                    value is None or isinstance(value, str)
                    for value in (
                        hint.evidence_id, hint.provenance,
                        hint.repository_revision, hint.config_digest,
                        hint.expires_at,
                    )
                )
            ):
                request_hints.append(hint)
    return request_hints


def _validate_hint_paths(
    self,
    effective_hints: list[Any],
    hint_root: Path | None,
    search_scope: str,
    repository_revision: str,
    project_context: Any,
    file_inventory: Any,
    exact_count: bool,
    phase_timings_ms: dict[str, float],
) -> tuple[list[str], bool, Any]:
    from .project_config import path_is_allowed, validate_path_hint

    hint_path_validation_started = time.perf_counter()
    hinted_search_paths: list[str] = []
    hinted_force_include = False
    try:
        extension_is_searchable = getattr(
            self.repo_tools, "_path_extension_is_searchable", None
        )
        ignored_dirs = getattr(self.repo_tools, "ignore_dirs", set())
        seen_hint_paths: set[str] = set()
        for hint in effective_hints:
            target = validate_path_hint(
                hint_root,
                hint,
                purpose="repository_search",
                scope=search_scope,
                repository_revision=repository_revision,
                config_digest=project_context.config_digest,
                learned=bool(hint.evidence_id),
            )
            if target is None:
                continue
            if target.is_file():
                candidates = (target,)
            elif target.is_dir():
                if file_inventory is None:
                    inventory_loader = getattr(self.repo_tools, "_git_files", None)
                    if hint_root is not None and callable(inventory_loader):
                        hint_inventory_started = time.perf_counter()
                        try:
                            file_inventory = inventory_loader(hint_root, force=exact_count)
                        except TypeError:
                            file_inventory = inventory_loader(hint_root)
                        phase_timings_ms["search_hint_inventory_ms"] += round(
                            (time.perf_counter() - hint_inventory_started) * 1000.0, 1,
                        )
                if file_inventory is not None:
                    candidates = _hint_directory_candidates(
                        file_inventory, hint_root, target,
                    )
                else:
                    def walk_hint_directory():
                        count = 0
                        for item in target.rglob("*"):
                            if item.is_file():
                                yield item
                                count += 1
                                if count >= 64:
                                    break
                    candidates = walk_hint_directory()
            for candidate in candidates:
                try:
                    relative_path = candidate.relative_to(hint_root)
                    relative = relative_path.as_posix()
                    size_bytes = candidate.stat().st_size
                except (OSError, RuntimeError, ValueError):
                    continue
                if callable(extension_is_searchable) and not extension_is_searchable(
                    candidate, project_settings=project_context.settings,
                ):
                    continue
                soft_ignored = any(
                    part.lower() in ignored_dirs for part in relative_path.parts[:-1]
                )
                if not path_is_allowed(
                    hint_root,
                    candidate,
                    project_context.settings,
                    phase="search",
                    soft_ignored=soft_ignored,
                    size_bytes=size_bytes,
                ):
                    continue
                hinted_force_include = hinted_force_include or soft_ignored
                if relative not in seen_hint_paths:
                    hinted_search_paths.append(relative)
                    seen_hint_paths.add(relative)
                if len(hinted_search_paths) >= 64:
                    break
            if len(hinted_search_paths) >= 64:
                break
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        hinted_search_paths = []
        hinted_force_include = False
    phase_timings_ms["search_hint_path_validation_ms"] = round(
        (time.perf_counter() - hint_path_validation_started) * 1000.0, 1,
    )
    return hinted_search_paths, hinted_force_include, file_inventory


def _collect_index_candidate_paths(
    self,
    root: str,
    query: str,
    use_index_candidates: bool,
    top_k: int,
) -> list[str]:
    paths: list[str] = []
    if use_index_candidates and self.deterministic is not None:
        code_index_hint_safe = True
        code_index = getattr(self, "code_index", None)
        measure_storage = getattr(code_index, "measure_storage", None)
        if callable(measure_storage):
            max_index_bytes = getattr(code_index, "max_index_bytes", None)
            if type(max_index_bytes) is not int or max_index_bytes < 1:
                code_index_hint_safe = False
            else:
                try:
                    storage = measure_storage()
                    physical_bytes = (
                        storage.get("physical_bytes") if isinstance(storage, dict) else None
                    )
                    code_index_hint_safe = (
                        type(physical_bytes) is int and physical_bytes <= max_index_bytes
                    )
                except (OSError, sqlite3.Error, TypeError, ValueError) as storage_exc:
                    logger.debug(
                        "Code-index size unavailable; expensive symbol hints skipped (%s)",
                        type(storage_exc).__name__,
                    )
                    code_index_hint_safe = False
        if code_index_hint_safe:
            try:
                paths.extend(self.deterministic.related_paths(root, query, max(16, top_k * 3)))
            except (OSError, sqlite3.Error, ValueError) as candidate_exc:
                logger.debug(
                    "Deterministic candidate search skipped (%s)",
                    type(candidate_exc).__name__,
                )
    if use_index_candidates and self.preprocessor is not None:
        try:
            candidate_search = getattr(self.preprocessor, "candidate_paths_lexical", None)
            if not callable(candidate_search):
                candidate_search = self.preprocessor.candidate_paths
            for p in candidate_search(root, query, max(16, top_k * 3)):
                if p not in paths:
                    paths.append(p)
        except (OSError, sqlite3.Error, ValueError) as candidate_exc:
            logger.debug(
                "Preprocessor candidate search skipped (%s)",
                type(candidate_exc).__name__,
            )
    return paths


def _blend_candidate_paths(
    self,
    candidate_paths: list[str] | tuple[str, ...] | None,
    hinted_search_paths: list[str],
    force_include_patterns: tuple[str, ...],
    hint_root: Path | None,
    file_inventory: Any,
) -> tuple[str, ...] | list[str] | None:
    from .project_config import path_matches_pattern

    if not candidate_paths or not hinted_search_paths:
        return candidate_paths
    eligible_hints = hinted_search_paths
    if (hint_root is not None and getattr(self.repo_tools, "prefer_git", False)
            and (hint_root / ".git").exists()):
        if getattr(file_inventory, "complete", False) is True:
            git_paths = {
                os.path.normcase(path.relative_to(hint_root).as_posix())
                for path in file_inventory
            }
        else:
            try:
                hinted_git_files = self.repo_tools._git_files(
                    hint_root, pathspecs=tuple(hinted_search_paths),
                )
                git_paths = {
                    os.path.normcase(path.relative_to(hint_root).as_posix())
                    for path in hinted_git_files or ()
                }
            except (OSError, RuntimeError, TypeError, ValueError):
                git_paths = set()
        eligible_hints = [
            path for path in hinted_search_paths
            if os.path.normcase(path) in git_paths
            or any(path_matches_pattern(path, pattern) for pattern in force_include_patterns)
        ]
    return tuple(dict.fromkeys((*eligible_hints, *candidate_paths)))[:64]


def _filter_allowed_results(
    self,
    combined: list[dict[str, Any]],
    base: Path,
    project_context: Any,
) -> list[dict[str, Any]]:
    from .project_config import path_is_allowed

    allowed_results: list[dict[str, Any]] = []
    extension_is_searchable = getattr(
        self.repo_tools, "_path_extension_is_searchable", None
    )
    for item in combined:
        relative = str(item.get("path") or "").replace("\\", "/")
        if not relative:
            continue
        target = (base / relative).resolve(strict=False)
        try:
            target.relative_to(base)
            size_bytes = target.stat().st_size
        except (OSError, RuntimeError, ValueError):
            continue
        if callable(extension_is_searchable) and not extension_is_searchable(
            target, project_settings=project_context.settings,
        ):
            continue
        if not path_is_allowed(
            base,
            target,
            project_context.settings,
            phase="search",
            hard_denied=bool(item.get("hard_denied", False)),
            binary=bool(item.get("binary", False)),
            size_bytes=size_bytes,
        ):
            continue
        item["path"] = target.relative_to(base).as_posix()
        allowed_results.append(item)
    return allowed_results


def _materialize_search_results(
    self,
    full_result: dict[str, Any],
    root: str,
    base: Path,
    project_context: Any,
    search_scope: str,
    repository_revision: str,
    request_hints: list[Any],
    page_limit: int,
    offset: int,
    exact_count: bool,
    paths: list[str],
    enrich: bool,
    phase_timings_ms: dict[str, float],
    result_materialization_started: float,
) -> dict[str, Any]:
    from .project_config import path_matches_pattern, prioritize_paths_with_hints

    if not isinstance(full_result, dict) or not full_result.get("success", True):
        result = dict(full_result) if isinstance(full_result, dict) else {
            "success": False, "error": "repository search failed"
        }
        result["preprocessed_hit"] = False
        return result

    combined: list[dict[str, Any]] = []
    seen_hits: set[tuple[str, int]] = set()
    for source in (full_result,):
        source_hits = source.get("results", []) if isinstance(source, dict) else []
        if not isinstance(source_hits, list):
            continue
        for item in source_hits:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            try:
                line_number = int(item.get("start_line", 0) or 0)
            except (TypeError, ValueError):
                line_number = 0
            key = (item["path"], line_number)
            if key not in seen_hits:
                combined.append(dict(item))
                seen_hits.add(key)

    result_path_validation_started = time.perf_counter()
    allowed_results = _filter_allowed_results(self, combined, base, project_context)
    phase_timings_ms["search_result_path_validation_ms"] = round(
        (time.perf_counter() - result_path_validation_started) * 1000.0, 1,
    )

    result_prioritization_started = time.perf_counter()
    override_patterns = tuple(
        pattern
        for pattern, action in project_context.settings.path_overrides.items()
        if action == "include"
    )
    override_order = sorted(
        allowed_results,
        key=lambda item: not any(
            path_matches_pattern(str(item["path"]), pattern)
            for pattern in override_patterns
        ),
    )
    result_paths = [str(item["path"]) for item in override_order]
    configured_usage = project_context.prioritize_paths(
        result_paths,
        purpose="repository_search",
        scope=search_scope,
        repository_revision=repository_revision,
        path_hints=(),
    )
    request_usage = prioritize_paths_with_hints(
        base,
        configured_usage.paths,
        request_hints,
        purpose="repository_search",
        scope=search_scope,
        repository_revision=repository_revision,
        config_digest=project_context.config_digest,
    )
    phase_timings_ms["search_result_prioritization_ms"] = round(
        (time.perf_counter() - result_prioritization_started) * 1000.0, 1,
    )
    hint_used = configured_usage.hint_used or request_usage.hint_used
    hint_fallback_used = (
        configured_usage.fallback_used or request_usage.fallback_used
    ) and not hint_used

    result = dict(full_result)
    count_is_exact = (
        full_result.get("count_exact") is True
        and isinstance(full_result.get("total_matches"), int)
        and not isinstance(full_result.get("total_matches"), bool)
    )
    if not count_is_exact:
        if not exact_count:
            candidate_page = allowed_results[:page_limit]
            result["results"] = candidate_page
            result["total_matches"] = None
            result["matches_count"] = None
            result["count_exact"] = False
            result["candidate_count"] = len(allowed_results)
            result["candidate_count_exact"] = False
            result["offset"] = offset
            result["limit"] = page_limit
            result["has_more"] = (
                True if full_result.get("has_more") or len(allowed_results) > page_limit
                else None
            )
            result["truncated"] = bool(full_result.get("truncated"))
            result["preprocessed_hit"] = bool(
                paths and any(str(item.get("path")) in set(paths) for item in candidate_page)
            )
            result["path_hint_usage"] = {
                "hint_used": hint_used,
                "fallback_used": hint_fallback_used,
                "hint_helped": None,
            }
            phase_timings_ms["result_materialization_ms"] = round(
                (time.perf_counter() - result_materialization_started) * 1000.0, 1,
            )
            return result
        return {
            "success": False,
            "error": "repository search could not produce an exact match count",
            "status_code": 503,
            "preprocessed_hit": False,
            "results": [],
        }

    total_matches = int(full_result["total_matches"])
    source_page = full_result.get("results", [])
    if not isinstance(source_page, list) or len(allowed_results) != len(source_page):
        return {
            "success": False,
            "error": "repository search filters disagreed while materializing the exact page",
            "status_code": 503,
            "preprocessed_hit": False,
            "results": [],
        }
    result["total_matches"] = total_matches
    result["matches_count"] = total_matches
    result["count_exact"] = count_is_exact
    result["offset"] = offset
    result["limit"] = page_limit
    page_results = allowed_results
    result["results"] = page_results
    result["has_more"] = (
        offset + len(page_results) < total_matches
        if count_is_exact
        else True if offset + len(page_results) < len(allowed_results) else None
    )
    result["truncated"] = False
    result["preprocessed_hit"] = bool(
        paths
        and any(str(item.get("path")) in set(paths) for item in allowed_results)
    )
    result["path_hint_usage"] = {
        "hint_used": hint_used,
        "fallback_used": hint_fallback_used,
        "hint_helped": None,
    }
    if enrich:
        result["enriched"] = True
        for hit in result.get("results", []):
            rel = str(hit.get("path") or "")
            target = (base / rel).resolve()
            try:
                target.relative_to(base)
                if target.is_file() and target.stat().st_size <= 512_000:
                    symbol = enclosing_symbol_at_line(
                        target.read_text(encoding="utf-8", errors="replace"), rel,
                        int(hit.get("start_line", 0) or 0),
                    )
                    if symbol:
                        hit["enclosing_symbol"] = symbol
            except (OSError, ValueError):
                continue
    phase_timings_ms["result_materialization_ms"] = round(
        (time.perf_counter() - result_materialization_started) * 1000.0, 1,
    )
    if self.evidence_store is not None and isinstance(result.get("results"), list):
        evidence_store_started = time.perf_counter()
        try:
            result = dict(result)
            stored_results = self.evidence_store.put_many(
                str(result.get("root", root)),
                result["results"],
                source_code="indexed",
            )
            receipts_complete = all(
                isinstance(item, dict)
                and (
                    not any(item.get(field) for field in ("text", "raw", "content"))
                    or bool(item.get("evidence_id"))
                )
                for item in stored_results
            )
            result["results"] = stored_results
            result["progressive_disclosure"] = receipts_complete
        except (OSError, sqlite3.Error, ValueError) as store_exc:
            logger.debug(
                "Repository search evidence persistence skipped (%s)",
                type(store_exc).__name__,
            )
            result = dict(result)
            result["progressive_disclosure"] = False
        finally:
            phase_timings_ms["evidence_store_ms"] = round(
                (time.perf_counter() - evidence_store_started) * 1000.0, 1,
            )
    return result


def _repo_search_lexical(
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
    exact_count: bool = True,
    candidate_paths: list[str] | tuple[str, ...] | None = None,
    candidate_query: str | None = None,
    installation_intent_priority: bool = False,
) -> dict[str, Any]:
    search_started = time.perf_counter()
    phase_timings_ms: dict[str, float] = {
        "search_hint_state_ms": 0.0,
        "search_saved_hints_ms": 0.0,
        "search_hint_digest_ms": 0.0,
        "search_learning_record_ms": 0.0,
        "search_hint_inventory_ms": 0.0,
        "search_hint_path_validation_ms": 0.0,
        "search_priority_setup_ms": 0.0,
    }
    page_limit = max(1, int(top_k)) if limit is None else limit
    bounds_error = pagination_bounds_error(page_limit, offset)
    if bounds_error:
        return {
            "success": False,
            "error": bounds_error,
            "status_code": 400,
            "root": root,
            "results": [],
            "total_matches": 0,
            "has_more": False,
            "limit": page_limit if isinstance(page_limit, int) and not isinstance(page_limit, bool) and 1 <= page_limit <= MAX_PAGE_SIZE else None,
            "offset": offset if isinstance(offset, int) and not isinstance(offset, bool) and 0 <= offset < MAX_PAGE_WINDOW else None,
        }
    if enrich and not rollout_feature_enabled(self.config, "enriched_search"):
        return {
            "success": False,
            "unsupported": True,
            "feature": "enriched_search",
            "error": "enriched search is disabled (features.enriched_search=false)",
        }
    symbol_like_query = prefers_lexical_precision(query)
    normalized_query = normalize_query(query, strip_punctuation=False)
    query = normalized_query if symbol_like_query else normalized_query.casefold()
    eff_ctx_lines = int(context_lines) if context_lines is not None else (8 if enrich else None)

    from .project_config import (
        PathHint,
        ProjectConfigError,
        path_matches_pattern,
        resolve_project_context,
        validate_path_hint,
    )

    project_config_started = time.perf_counter()
    try:
        project_context = resolve_project_context(
            root,
            configured_state_dir(getattr(self, "config", {}), create=False),
        )
    except ProjectConfigError as exc:
        return {
            "success": False,
            "root": root,
            "error": f"project configuration is invalid: {exc}",
            "terminal": True,
            "retryable": False,
        }
    finally:
        phase_timings_ms["project_config_ms"] = round(
            (time.perf_counter() - project_config_started) * 1000.0, 1,
        )
    if project_context.resolution.error_codes:
        return {
            "success": False,
            "root": root,
            "error": "project_policy_unavailable",
            "results": [],
            "terminal": True,
            "retryable": False,
        }
    hint_root = getattr(project_context, "root", None)
    if hint_root is None:
        try:
            hint_root = Path(root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            hint_root = None

    file_inventory = None
    search_scope = scope if isinstance(scope, str) else "repository_search"
    page_limit = top_k if limit is None else limit
    bounds_error = pagination_bounds_error(page_limit, offset)
    if bounds_error:
        return {"success": False, "error": bounds_error, "status_code": 400,
                "limit": page_limit if isinstance(page_limit, int) and not isinstance(page_limit, bool) and 1 <= page_limit <= MAX_PAGE_SIZE else None,
                "offset": offset if isinstance(offset, int) and not isinstance(offset, bool) and 0 <= offset < MAX_PAGE_WINDOW else None,
                "total_matches": 0, "has_more": False, "results": []}

    request_hints = _extract_request_hints(path_hints)

    fingerprint_started = time.perf_counter()
    try:
        tracker = getattr(self, "repo_state", None)
        fingerprint = getattr(tracker, "fingerprint", None)
        workspace_state = (
            fingerprint(root) or {}
            if callable(fingerprint)
            else self._repo_cache_state(root) or {}
        )
    except Exception:
        workspace_state = {}
    finally:
        phase_timings_ms["workspace_fingerprint_ms"] = round(
            (time.perf_counter() - fingerprint_started) * 1000.0, 1,
        )
    repository_revision = (
        str(workspace_state.get("fingerprint") or "")
        if not workspace_state.get("stale") and not workspace_state.get("degraded")
        else ""
    )

    search_preparation_started = time.perf_counter()
    search_hint_state_started = time.perf_counter()
    saved_hints_started = time.perf_counter()
    saved_hints = project_context.path_hints(
        purpose="repository_search",
        scope=search_scope,
        repository_revision=repository_revision,
    )
    phase_timings_ms["search_saved_hints_ms"] = round(
        (time.perf_counter() - saved_hints_started) * 1000.0, 1,
    )
    hint_digest_started = time.perf_counter()
    effective_hints = [*request_hints, *saved_hints]
    request_hint_digest = stable_hash([
        {
            "path": hint.path,
            "purpose": hint.purpose,
            "scope": hint.scope,
            "evidence_id": hint.evidence_id,
            "provenance": hint.provenance,
            "repository_revision": hint.repository_revision,
            "config_digest": hint.config_digest,
            "expires_at": hint.expires_at,
        }
        for hint in effective_hints
    ])
    phase_timings_ms["search_hint_digest_ms"] = round(
        (time.perf_counter() - hint_digest_started) * 1000.0, 1,
    )
    learning_record_started = time.perf_counter()
    if self.learner is not None:
        try:
            if hint_root is not None:
                self.learner.record_resolved(hint_root, query)
            else:
                self.learner.record(root, query)
        except Exception:
            pass
    phase_timings_ms["search_learning_record_ms"] = round(
        (time.perf_counter() - learning_record_started) * 1000.0, 1,
    )
    phase_timings_ms["search_hint_state_ms"] = round(
        (time.perf_counter() - search_hint_state_started) * 1000.0, 1,
    )

    use_index_candidates = exact_count and symbol_like_query
    paths = _collect_index_candidate_paths(self, root, query, use_index_candidates, top_k)

    force_include_patterns = tuple(project_context.settings.force_include_paths) + tuple(
        pattern
        for pattern, action in project_context.settings.path_overrides.items()
        if action == "include"
    )

    hinted_search_paths, hinted_force_include, file_inventory = _validate_hint_paths(
        self,
        effective_hints,
        hint_root,
        search_scope,
        repository_revision,
        project_context,
        file_inventory,
        exact_count,
        phase_timings_ms,
    )

    search_priority_setup_started = time.perf_counter()
    candidate_paths = _blend_candidate_paths(
        self, candidate_paths, hinted_search_paths, force_include_patterns, hint_root, file_inventory,
    )
    paths = list(dict.fromkeys([*hinted_search_paths, *paths]))

    def compute() -> dict[str, Any]:
        override_patterns = tuple(
            pattern
            for pattern, action in project_context.settings.path_overrides.items()
            if action == "include"
        )

        def matching_hint_roots(hints: list[PathHint], *, learned: bool) -> tuple[Path, ...]:
            if hint_root is None:
                return ()
            roots: list[Path] = []
            for hint in hints:
                target = validate_path_hint(
                    hint_root,
                    hint,
                    purpose="repository_search",
                    scope=search_scope,
                    repository_revision=repository_revision,
                    config_digest=project_context.config_digest,
                    learned=learned,
                )
                if target is not None:
                    roots.append(target)
            return tuple(roots)

        configured_hints = [
            PathHint(path=path, purpose="repository_search", scope=search_scope)
            for path in project_context.settings.entry_points
        ]
        durable_hint_roots = (
            *matching_hint_roots(saved_hints, learned=True),
            *matching_hint_roots(configured_hints, learned=False),
        )
        request_hint_roots = matching_hint_roots(request_hints, learned=False)
        candidate_hint_paths = tuple(
            relative for relative in (
                candidate.relative_to(hint_root).as_posix() for candidate in request_hint_roots
            ) if relative != "."
        )
        normalized_hint_paths = tuple(
            os.path.normcase(relative).replace("\\", "/").rstrip("/")
            for relative in candidate_hint_paths
        )

        source_focused = _source_focused_query(query)

        def candidate_path_priority(relative: str) -> int:
            candidate = os.path.normcase(relative).replace("\\", "/").rstrip("/")
            return 0 if candidate and any(
                candidate == path or candidate.startswith(path + "/") or path.startswith(candidate + "/")
                for path in normalized_hint_paths
            ) else 1

        def path_priority(relative: str) -> tuple[int, int, int]:
            candidate = hint_root / relative if hint_root else None

            def matches(roots: tuple[Path, ...]) -> bool:
                return bool(candidate and any(
                    candidate == root or root in candidate.parents for root in roots
                ))

            override_match = any(
                path_matches_pattern(relative, pattern) for pattern in override_patterns
            )
            return (
                0 if matches(request_hint_roots) else 1,
                0 if matches(durable_hint_roots) else 1,
                _context_path_priority(
                    relative,
                    source_focused=source_focused,
                    override_match=override_match,
                ),
            )

        search_options = {
            "context_lines": eff_ctx_lines,
            "project_settings": project_context.settings,
            "git_inventory": file_inventory,
            "candidate_paths": candidate_paths,
            "limit": page_limit,
            "offset": offset,
            "exact_count": exact_count,
            "force_include_paths": list(force_include_patterns),
            "path_priority": path_priority,
            "installation_intent_priority": installation_intent_priority,
        }
        if candidate_hint_paths:
            search_options["candidate_path_priority"] = candidate_path_priority
            search_options["candidate_hint_paths"] = candidate_hint_paths
        if candidate_query and candidate_query != query:
            search_options["candidate_query"] = normalize_query(
                candidate_query, strip_punctuation=False,
            ).casefold()
        phase_timings_ms["search_priority_setup_ms"] = round(
            (time.perf_counter() - search_priority_setup_started) * 1000.0, 1,
        )
        phase_timings_ms["search_preparation_ms"] = round(
            (time.perf_counter() - search_preparation_started) * 1000.0, 1,
        )
        repo_search_started = time.perf_counter()
        try:
            full_result = self.repo_tools.search(
                root, query, **search_options,
            )
        finally:
            phase_timings_ms["repo_tools_search_ms"] = round(
                (time.perf_counter() - repo_search_started) * 1000.0, 1,
            )
        if isinstance(full_result, dict):
            repo_search_phases = full_result.pop("search_phase_timings_ms", None)
            if isinstance(repo_search_phases, dict):
                phase_timings_ms.update({
                    f"repo_tools_{name}": duration_ms
                    for name, duration_ms in repo_search_phases.items()
                    if isinstance(name, str)
                })

        result_materialization_started = time.perf_counter()
        base = getattr(project_context, "root", None) or Path(root).expanduser().resolve(strict=False)
        return _materialize_search_results(
            self,
            full_result,
            root,
            base,
            project_context,
            search_scope,
            repository_revision,
            request_hints,
            page_limit,
            offset,
            exact_count,
            paths,
            enrich,
            phase_timings_ms,
            result_materialization_started,
        )

    result = self._repo_cached(
        "search",
        root,
        {
            "query": query,
            "top_k": top_k,
            "limit": page_limit,
            "offset": offset,
            "ci": paths[:24],
            "ctx": eff_ctx_lines,
            "enrich": enrich,
            "scope": search_scope,
            "config_digest": project_context.config_digest,
            "path_hints_digest": request_hint_digest,
            "exact_count": exact_count,
            "candidate_query": candidate_query or "",
            "force_include_patterns": list(force_include_patterns),
        },
        compute,
        state_override=workspace_state,
        cache_results=False,
    )
    if isinstance(result, dict):
        result = dict(result)
        phase_timings_ms["total_ms"] = round(
            (time.perf_counter() - search_started) * 1000.0, 1,
        )
        result["phase_timings_ms"] = phase_timings_ms
    return result
