from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
import os
from pathlib import Path
import time
from typing import Any

from .budget import estimate_tokens
from .repo_tools_constants import _SYMBOL_PATTERNS, _UNSET_GIT_INVENTORY
from .repo_tools_models import GitFileInventory
from .repo_tools_path_helpers import (
    _intent_path_adjustment,
    _intent_query_terms,
    _is_installation_intent,
)
from .search_pagination import MAX_PAGE_SIZE, MAX_PAGE_WINDOW, pagination_bounds_error


RepositoryTools = None


class RepoToolsWorkspaceMixin:
    def search(
        self, root: str, query: str, limit: int = 12, context_lines: int | None = None,
        *, project_settings: Any | None = None,
        git_inventory: Any = _UNSET_GIT_INVENTORY,
        candidate_paths: list[str] | tuple[str, ...] | None = None,
        candidate_query: str | None = None,
        offset: int = 0,
        exact_count: bool = False,
        force_include_paths: list[str] | tuple[str, ...] = (),
        path_priority: Callable[[str], tuple[int, int, int]] | None = None,
        candidate_path_priority: Callable[[str], int] | None = None,
        candidate_hint_paths: tuple[str, ...] = (),
        installation_intent_priority: bool = True,
    ) -> dict[str, Any]:
        base = self._root(root)
        if type(installation_intent_priority) is not bool:
            return {"success": False, "status_code": 400, "terminal": True,
                    "retryable": False, "error": "installation_intent_priority must be a boolean",
                    "root": str(base), "results": []}
        if exact_count:
            if candidate_paths is not None:
                return {
                    "success": False, "root": str(base), "results": [],
                    "error": "candidate_paths cannot be used for exact-count search",
                    "terminal": True, "retryable": False,
                }
            exact_limit = limit
            bounds_error = pagination_bounds_error(exact_limit, offset)
            if bounds_error:
                return {
                    "success": False, "root": str(base), "results": [],
                    "error": bounds_error, "status_code": 400,
                    "limit": exact_limit if isinstance(exact_limit, int) and not isinstance(exact_limit, bool) and 1 <= exact_limit <= MAX_PAGE_SIZE else None,
                    "offset": offset if isinstance(offset, int) and not isinstance(offset, bool) and 0 <= offset < MAX_PAGE_WINDOW else None,
                    "total_matches": 0, "has_more": False,
                }
            return self._exact_search_page(
                base, query, exact_limit, offset, context_lines,
                project_settings, git_inventory, force_include_paths,
                path_priority, installation_intent_priority,
            )
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                    "error": "limit must be a positive integer", "root": str(base), "results": []}
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                    "error": "offset must be a nonnegative integer", "root": str(base), "results": []}
        if candidate_paths is not None:
            if (not isinstance(candidate_paths, (list, tuple)) or not candidate_paths or len(candidate_paths) > 64
                    or any(type(item) is not str or not item or "\x00" in item
                           or Path(item).is_absolute() or ".." in Path(item.replace("\\", "/")).parts
                           for item in candidate_paths)):
                return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                        "error": "candidate_paths must contain 1 to 64 safe relative paths",
                        "root": str(base), "results": []}
            git_inventory = [base / Path(item.replace("\\", "/")) for item in candidate_paths]
        candidate_text = candidate_query if type(candidate_query) is str and candidate_query else query
        terms = self._terms(candidate_text)
        expanded_terms = set(terms).difference(self._terms(query))
        phrase = query.strip().lower()
        if not terms and phrase:
            terms = [phrase]
        if not terms and not phrase:
            return {
                "success": True, "root": str(base), "results": [],
                "total_matches": 0, "returned_count": 0, "has_more": False,
                "limit": limit, "offset": offset,
                "truncated": False, "count_exact": True,
            }
        result_limit = limit
        effective_snippet_lines = max(1, min(int(context_lines), 40)) if context_lines is not None else self.snippet_lines
        hits: list[dict[str, Any]] = []
        scanned = 0
        python_fallback_scanned: int | None = None
        read_errors = 0
        truncation_reasons: list[str] = []
        # Keep candidate scanning bounded independently of caller pagination.
        # Pages beyond this ranked working set remain explicitly truncated.
        # Installation queries often fan out over setup scripts and old plans.
        # Give that intent a larger bounded recall window so one noisy path
        # cannot hide the actual user guide. Other queries retain the smaller
        # default window; response size stays controlled by pagination.
        install_intent = installation_intent_priority and _is_installation_intent(
            _intent_query_terms(query)
        )
        candidate_limit = max(
            4,
            min(
                self.max_hits * (8 if install_intent else 4),
                limit * (8 if install_intent else 6),
            ),
        )
        candidate_path_budget = max(256, min(512, candidate_limit * 4))
        candidate_engine = "python"
        project_candidates = None
        priority_relpaths: set[str] = set()
        pinned_paths: set[str] = set()
        request_hint_paths: set[str] = set()
        search_phase_timings_ms: dict[str, float] = {
            "git_inventory_ms": 0.0,
            "project_file_iteration_ms": 0.0,
        }
        candidate_discovery_started = time.perf_counter()
        if project_settings is not None:
            # Bounded non-exact search can use the cached Git path inventory.
            # Falling back to a fresh os.walk here repeatedly enumerates large
            # ignored workspace trees before the ripgrep candidate cap applies.
            candidate_inventory = (
                _UNSET_GIT_INVENTORY if git_inventory is None else git_inventory
            )
            # Select query-name matches before the bounded inventory prefix.
            # The iterator validates path policy and symlink safety on every
            # selected path before ripgrep can read its contents.
            git_inventory_started = time.perf_counter()
            if candidate_inventory is _UNSET_GIT_INVENTORY:
                candidate_inventory = self._git_files(base)
            if (candidate_hint_paths and isinstance(candidate_inventory, GitFileInventory)
                    and not candidate_inventory.complete):
                hinted = self._git_files(base, pathspecs=candidate_hint_paths)
                if hinted is not None:
                    candidate_inventory = GitFileInventory(
                        list(dict.fromkeys([*hinted, *candidate_inventory])), complete=False,
                    )
            search_phase_timings_ms["git_inventory_ms"] = round(
                (time.perf_counter() - git_inventory_started) * 1000.0, 1,
            )
            project_file_iteration_started = time.perf_counter()
            project_candidates = list(self._iter_project_search_files(
                base, project_settings, 25, git_inventory=candidate_inventory,
                candidate_limit=candidate_path_budget + 16,
                candidate_priority_terms=terms,
                candidate_path_priority=candidate_path_priority,
                phase_timings_ms=search_phase_timings_ms,
            ))
            search_phase_timings_ms["project_file_iteration_ms"] = round(
                (time.perf_counter() - project_file_iteration_started) * 1000.0, 1,
            )
            if (
                isinstance(candidate_inventory, list)
                and len(candidate_inventory) > candidate_path_budget
            ) or (isinstance(candidate_inventory, GitFileInventory) and not candidate_inventory.complete) or (
                len(project_candidates) >= min(max(1, self.max_files), candidate_path_budget)
            ):
                truncation_reasons.append("candidate_file_limit")
        elif candidate_paths is not None:
            # This is an explicitly incomplete candidate set for hybrid search,
            # never a source of exact lexical counts or complete-coverage claims.
            project_candidates = [base / Path(item.replace("\\", "/")) for item in candidate_paths]
        search_phase_timings_ms["candidate_discovery_ms"] = round(
            (time.perf_counter() - candidate_discovery_started) * 1000.0, 1,
        )
        accelerator_search_started = time.perf_counter()
        if project_candidates is None:
            candidates, accelerator_failed = self._ripgrep_candidates(
                base, terms, candidate_limit + 1,
            )
        else:
            candidate_budget = candidate_limit + 1
            priority_terms = {term.casefold() for term in terms if isinstance(term, str) and term}
            # Pinned context has already passed project policy and symlink
            # checks in _iter_project_search_files. Search it before a noisy
            # repository prefix exhausts the bounded accelerator match budget.
            pinned_paths = {
                item.replace("\\", "/")
                for item in getattr(project_settings, "pinned_context", ())
                if isinstance(item, str)
            } if project_settings is not None else set()
            priority_candidates: list[Path] = []
            remaining_candidates: list[Path] = []
            for candidate in project_candidates:
                try:
                    relative_path = candidate.relative_to(base).as_posix()
                    path_stem = candidate.stem.casefold()
                except ValueError:
                    remaining_candidates.append(candidate)
                    continue
                request_hinted = False
                if candidate_path_priority is not None:
                    try:
                        request_hinted = candidate_path_priority(relative_path) == 0
                    except (OSError, RuntimeError, TypeError, ValueError):
                        pass
                if request_hinted:
                    request_hint_paths.add(relative_path)
                overlap = sum(
                    1 for term in priority_terms
                    if path_stem == term
                    or (len(term) >= 4 and path_stem.startswith(term))
                    or (len(path_stem) >= 4 and term.startswith(path_stem))
                )
                (priority_candidates if overlap or request_hinted or relative_path in pinned_paths
                 else remaining_candidates).append(candidate)

            priority_candidates.sort(key=lambda candidate: (
                0 if candidate.relative_to(base).as_posix() in request_hint_paths else 1,
                0 if candidate.relative_to(base).as_posix() in pinned_paths else 1,
                0 if candidate.relative_to(base).stem.casefold() in priority_terms else 1,
                len(candidate.relative_to(base).stem),
                candidate.as_posix().casefold(),
            ))
            priority_file_limit = max(4, min(16, self.max_hits))
            remaining_candidates.extend(priority_candidates[priority_file_limit:])
            priority_candidates = priority_candidates[:priority_file_limit]
            request_priority_candidates = [
                candidate for candidate in priority_candidates
                if candidate.relative_to(base).as_posix() in request_hint_paths
            ]
            other_priority_candidates = [
                candidate for candidate in priority_candidates
                if candidate.relative_to(base).as_posix() not in request_hint_paths
            ]
            # Ripgrep batches have a fixed command-size ceiling. Passing the
            # entire repository inventory can spawn several expensive scans
            # per natural query, even after enough candidates exist. Keep the
            # prioritized files, then inspect a bounded inventory prefix; the
            # explicit truncation flag prevents claiming complete coverage.
            if len(remaining_candidates) > candidate_path_budget:
                remaining_candidates = remaining_candidates[:candidate_path_budget]
                if "candidate_file_limit" not in truncation_reasons:
                    truncation_reasons.append("candidate_file_limit")
            project_candidates = [*priority_candidates, *remaining_candidates]
            priority_relpaths = {
                candidate.relative_to(base).as_posix()
                for candidate in priority_candidates
            }

            if request_priority_candidates:
                request_matches, request_failed = self._ripgrep_candidates(
                    base, terms, candidate_budget,
                    candidate_paths=request_priority_candidates,
                )
            else:
                request_matches, request_failed = None, False

            if request_priority_candidates and request_matches is not None:
                remaining_budget = candidate_budget - len(request_matches)
                priority_matches: list[tuple[str, int]] | None = []
                priority_failed = False
                if other_priority_candidates and remaining_budget > 0:
                    priority_matches, priority_failed = self._ripgrep_candidates(
                        base, terms, remaining_budget,
                        candidate_paths=other_priority_candidates,
                    )
                if priority_matches is None:
                    candidates = request_matches
                    accelerator_failed = request_failed
                else:
                    remaining_budget -= len(priority_matches)
                    remaining_matches: list[tuple[str, int]] | None = []
                    remaining_failed = False
                    if remaining_candidates and remaining_budget > 0:
                        remaining_matches, remaining_failed = self._ripgrep_candidates(
                            base, terms, remaining_budget,
                            candidate_paths=remaining_candidates,
                        )
                    if remaining_matches is None:
                        candidates = [*request_matches, *priority_matches]
                        accelerator_failed = request_failed or priority_failed
                    else:
                        candidates = []
                        seen_matches: set[tuple[str, int]] = set()
                        for match in (*request_matches, *priority_matches, *remaining_matches):
                            if match not in seen_matches:
                                seen_matches.add(match)
                                candidates.append(match)
                        accelerator_failed = request_failed or priority_failed or remaining_failed
            else:
                priority_matches, priority_failed = None, False
                if priority_candidates:
                    priority_matches, priority_failed = self._ripgrep_candidates(
                        base, terms, candidate_budget,
                        candidate_paths=priority_candidates,
                    )
                if priority_matches is None:
                    candidates, accelerator_failed = self._ripgrep_candidates(
                        base, terms, candidate_budget,
                        candidate_paths=project_candidates,
                    )
                    accelerator_failed = accelerator_failed or priority_failed
                else:
                    remaining_matches: list[tuple[str, int]] | None = []
                    remaining_failed = False
                    remaining_budget = candidate_budget - len(priority_matches)
                    if remaining_candidates and remaining_budget > 0:
                        remaining_matches, remaining_failed = self._ripgrep_candidates(
                            base, terms, remaining_budget,
                            candidate_paths=remaining_candidates,
                        )
                    if remaining_matches is None:
                        candidates = priority_matches
                        accelerator_failed = False
                    else:
                        candidates = []
                        seen_matches: set[tuple[str, int]] = set()
                        for match in (*priority_matches, *remaining_matches):
                            if match not in seen_matches:
                                seen_matches.add(match)
                                candidates.append(match)
                        accelerator_failed = False
        accelerated = candidates is not None
        if accelerated:
            candidate_engine = "ripgrep"
        else:
            git_grep_failed = False
            if project_settings is None:
                candidates, git_grep_failed = self._git_grep_candidates(base, terms, candidate_limit + 1)
            accelerator_failed = accelerator_failed or git_grep_failed
            accelerated = candidates is not None
            if accelerated:
                candidate_engine = "git-grep"
        if candidates is not None and len(candidates) > candidate_limit:
            truncation_reasons.append("result_limit")
            candidates = candidates[:candidate_limit]
        search_phase_timings_ms["accelerator_search_ms"] = round(
            (time.perf_counter() - accelerator_search_started) * 1000.0, 1,
        )
        candidate_scan_started = time.perf_counter()
        if candidates:
            per_path_lines: dict[str, list[int]] = {}
            for rel, line_no in candidates:
                per_path_lines.setdefault(rel, []).append(line_no)
            # For a small set of query-matching filenames, inspect current
            # content fully. Ripgrep's per-file cap can hide the specific term
            # near the end of a source file behind repeated generic matches.
            for rel in priority_relpaths:
                per_path_lines.setdefault(rel, [])
            read_jobs: list[tuple[Any, Path]] = []
            for rel, line_numbers in per_path_lines.items():
                resolved_info = self._resolve_under_base(base, rel)
                if resolved_info is None:
                    continue
                path, relative = resolved_info
                if project_settings is None and self._is_ignored_relative_path(relative):
                    continue
                if project_settings is not None and not self._project_file_allowed(base, path, project_settings):
                    continue
                read_jobs.append(((rel, line_numbers), path))
            # A filename nominated by a precise expansion can arrive from
            # ripgrep's bounded fallback without being in priority_relpaths.
            # Ensure a small number of these already-opened source snapshots
            # have their full line span ranked, otherwise ripgrep's per-file
            # max-count can hide the actual identifier near EOF.
            named_file_scan_slots = 4
            for (rel, line_numbers), file_hash, lines, error in self._read_search_snapshots(read_jobs):
                if error is not None:
                    read_errors += 1
                    continue
                scanned += 1
                path_lower = rel.lower()
                named_expansion = (
                    named_file_scan_slots > 0
                    and bool(expanded_terms)
                    and len(lines) <= 4096
                    and Path(rel).stem.casefold() in expanded_terms
                    and rel not in priority_relpaths
                )
                if named_expansion:
                    named_file_scan_slots -= 1
                source_lines = (
                    range(1, len(lines) + 1)
                    if rel in priority_relpaths or named_expansion else line_numbers
                )
                for line_no in source_lines:
                    idx = line_no - 1
                    if idx < 0 or idx >= len(lines): continue
                    low = lines[idx].lower()
                    matched = [t for t in terms if t in low]
                    path_matches = sum(1 for t in terms if t in path_lower)
                    score = float(len(matched) * 3 + path_matches * 2 + sum(min(low.count(t), 3) * 0.5 for t in matched))
                    if expanded_terms:
                        # Expansion terms matching a filename are strong intent
                        # evidence in bounded hybrid candidates; keep exact lexical
                        # ranking unchanged when no query expansion was applied.
                        stem = Path(rel).stem.lower()
                        title_matches = sum(1 for term in expanded_terms if term in stem)
                        score += min(40.0, title_matches * 20.0)
                        # A precise expanded identifier should not disappear
                        # behind dozens of identical generic-token lines in the
                        # same file when per-file snippets are bounded.
                        score += max((
                            min(3.0, len(term) / 5.0)
                            for term in matched if term in expanded_terms
                        ), default=0.0)
                    if phrase and len(phrase) <= 120 and phrase in low: score += 8
                    if installation_intent_priority:
                        score += _intent_path_adjustment(query, rel)
                    # A verified pinned context file must survive a bounded
                    # top-k page when many generic-token files match. Pinning
                    # changes ranking only, never authorization or matching.
                    if rel in priority_relpaths and rel in pinned_paths:
                        score += 32.0
                    start = max(0, idx - effective_snippet_lines); end = min(len(lines), idx + effective_snippet_lines + 1)
                    snippet = self._format_search_snippet(lines, start, end)
                    hits.append({"path": rel, "start_line": start + 1, "end_line": end, "score": round(score, 3), "text": snippet, "file_sha256": file_hash})
        search_phase_timings_ms["candidate_scan_ms"] = round(
            (time.perf_counter() - candidate_scan_started) * 1000.0, 1,
        )
        # A timeout/error must not trigger an unbounded O(repository) Python scan.
        # Validated project candidates keep fallback bounded; accelerated zero stays final.
        if not accelerated and accelerator_failed and not project_candidates:
            return {
                "success": False,
                "root": str(base),
                "terms": terms,
                "results": [],
                "engine": "bounded-accelerator-failure",
                "error": "bounded search accelerators timed out or failed",
                "retryable": True,
            }
        if not hits and not accelerated:
            python_fallback_scanned = 0
            with self._git_files_lock:
                self._git_stats["python_search_fallbacks"] = min(
                    1_000_000, self._git_stats["python_search_fallbacks"] + 1
                )
            fallback_paths = (
                project_candidates
                if project_candidates is not None
                else self.iter_files(str(base), max_files=self.python_fallback_max_files + 1)
            )
            if expanded_terms:
                # Preserve authorized pinned paths before the generic source
                # inventory when reordering by expanded filename terms.
                # Otherwise sorting moves docs/INSTALLATION.md behind noisy
                # alphabetically-earlier files and the strict hit budget is
                # exhausted before the pinned file is even read. Only already
                # validated candidates reach this bounded fallback.
                pinned_keys = {os.path.normcase(path) for path in pinned_paths}
                fallback_paths = sorted(
                    fallback_paths,
                    key=lambda candidate: (
                        os.path.normcase(candidate.relative_to(base).as_posix()) not in pinned_keys,
                        candidate.stem.casefold() not in expanded_terms,
                        candidate.as_posix().casefold(),
                    ),
                )
            fallback_jobs: list[tuple[str, Path]] = []
            for path in fallback_paths:
                if python_fallback_scanned >= self.python_fallback_max_files:
                    truncation_reasons.append("file_limit")
                    break
                scanned += 1
                python_fallback_scanned += 1
                rel = str(path.relative_to(base)).replace("\\", "/")
                resolved_info = self._resolve_under_base(base, rel)
                if resolved_info is None:
                    continue
                resolved_path, _relative = resolved_info
                fallback_jobs.append((rel, resolved_path))
            for rel, file_hash, lines, error in self._read_search_snapshots(fallback_jobs):
                path_lower = rel.lower()
                if error is not None:
                    read_errors += 1
                    continue
                full_precision_file = (
                    bool(expanded_terms)
                    and len(lines) <= 4096
                    and Path(rel).stem.casefold() in expanded_terms
                )
                for idx, line in enumerate(lines):
                    low = line.lower()
                    matched = [t for t in terms if t in low]
                    path_matches = sum(1 for t in terms if t in path_lower)
                    if not matched and not path_matches:
                        continue
                    score = float(len(matched) * 3 + path_matches * 2)
                    if phrase and len(phrase) <= 120 and phrase in low:
                        score += 8
                    score += sum(min(low.count(t), 3) * 0.5 for t in matched)
                    if expanded_terms:
                        stem = Path(rel).stem.casefold()
                        score += min(40.0, 20.0 * sum(1 for term in expanded_terms if term in stem))
                        score += max((
                            min(3.0, len(term) / 5.0)
                            for term in matched if term in expanded_terms
                        ), default=0.0)
                    if installation_intent_priority:
                        score += _intent_path_adjustment(query, rel)
                    # The pure-Python fallback must honor validated pinned
                    # files exactly like the accelerated candidate path.
                    # Pinned paths came from project_candidates, already
                    # checked against project path and symlink policy.
                    if rel in pinned_paths and project_settings is not None:
                        score += 32.0
                    start = max(0, idx - effective_snippet_lines)
                    end = min(len(lines), idx + effective_snippet_lines + 1)
                    snippet = self._format_search_snippet(lines, start, end)
                    hits.append({
                        "path": rel, "start_line": start + 1, "end_line": end,
                        "score": round(score, 3), "text": snippet, "file_sha256": file_hash,
                    })
                    if len(hits) > candidate_limit:
                        if full_precision_file:
                            # Rank all lines in only this small, query-named
                            # file before selecting its best evidence, while
                            # keeping the candidate list strictly bounded.
                            hits.sort(key=lambda x: (-x["score"], x["path"], x["start_line"]))
                            del hits[candidate_limit:]
                        else:
                            hits.pop()
                        if "result_limit" not in truncation_reasons:
                            truncation_reasons.append("result_limit")
                        if not full_precision_file:
                            break
                if "result_limit" in truncation_reasons:
                    break
        # Pinned files are ranked ahead of generic-token noise only after
        # normal repository authorization and a real content match. A numeric
        # bonus alone is insufficient when query expansion raises the scores
        # of dozens of repetitive files; it can still bury valid pinned
        # evidence outside the bounded first page.
        hits.sort(key=lambda x: (
            0 if x["path"] in request_hint_paths else 1,
            0 if x["path"] in pinned_paths and project_settings is not None else 1,
            -x["score"], x["path"], x["start_line"],
        ))
        dedup: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        per_file: Counter[str] = Counter()
        for hit in hits:
            key = (hit["path"], hit["start_line"] // max(1, self.snippet_lines))
            if key in seen or per_file[hit["path"]] >= self.max_snippets_per_file:
                continue
            seen.add(key)
            per_file[hit["path"]] += 1
            dedup.append(hit)
        total_matches = len(dedup)
        page_results = dedup[offset : offset + result_limit]
        has_more = offset + len(page_results) < total_matches
        if has_more and "result_limit" not in truncation_reasons:
            truncation_reasons.append("result_limit")
        candidate_pool = hits[: max(len(page_results), result_limit * 4)]
        candidate_tokens = sum(estimate_tokens(str(item.get("text", ""))) for item in candidate_pool)
        if read_errors:
            truncation_reasons.append("read_errors")
        result = {
            "success": True,
            "root": str(base),
            "scanned_files": scanned,
            "terms": terms,
            "results": page_results,
            "total_matches": total_matches,
            "returned_count": len(page_results),
            "has_more": has_more,
            "engine": candidate_engine,
            "truncated": bool(truncation_reasons or read_errors or has_more),
            "truncation_reasons": truncation_reasons,
            "read_errors": read_errors,
            "search_phase_timings_ms": search_phase_timings_ms,
        }
        if python_fallback_scanned is not None:
            result["python_fallback_files_scanned"] = python_fallback_scanned
            result["python_fallback_scanned_files"] = python_fallback_scanned
            result["python_fallback_file_limit"] = self.python_fallback_max_files
            result["python_fallback_limit"] = self.python_fallback_max_files
            result["python_fallback_truncated"] = "file_limit" in truncation_reasons
        if candidate_tokens:
            # Diagnostic only. Local RG-like filtering is not proof that a cloud
            # agent would otherwise have paid for the candidate snippets.
            result["candidate_context_tokens_est"] = candidate_tokens
        return result

    def repo_map(self, root: str, max_symbols: int = 120, paths: Iterable[str] | None = None) -> dict[str, Any]:
        base = self._root(root)
        extensions: Counter[str] = Counter()
        top_dirs: Counter[str] = Counter()
        symbols: list[dict[str, Any]] = []
        files = 0
        if paths is None:
            candidates: Iterable[Path] = self.iter_files(str(base))
        else:
            bounded: list[Path] = []
            for raw in paths:
                candidate = (base / str(raw)).resolve(strict=False)
                try:
                    candidate.relative_to(base)
                except ValueError:
                    continue
                bounded.append(candidate)
            candidates = bounded
        for path in candidates:
            if not path.is_file():
                continue
            if self.extensions and path.suffix.lower() not in self.extensions and path.name.lower() not in self.special_filenames:
                continue
            try:
                if path.stat().st_size > self.max_file_bytes:
                    continue
            except OSError:
                continue
            files += 1
            rel = str(path.relative_to(base)).replace("\\", "/")
            extensions[path.suffix.lower() or "<none>"] += 1
            top_dirs[rel.split("/", 1)[0]] += 1
            if len(symbols) >= max_symbols:
                continue
            try:
                _hash, lines = self._read_snapshot(path)
            except Exception:
                continue
            for line_no, line in enumerate(lines, 1):
                for pattern in _SYMBOL_PATTERNS:
                    match = pattern.match(line)
                    if match:
                        symbols.append({"name": match.group(1), "path": rel, "line": line_no})
                        break
                if len(symbols) >= max_symbols:
                    break
        return {
            "success": True, "root": str(base), "files": files,
            "extensions": extensions.most_common(20), "top_paths": top_dirs.most_common(30),
            "symbols_sample": symbols,
        }

    def project_profile(self, root: str) -> dict[str, Any]:
        """Detect project languages, manifests and likely validation commands without an LLM.

        Only small manifest/config files are read. Validation commands are suggestions;
        this method never executes project code.
        """
        base = self._root(root)
        language_by_ext = {
            ".py": "Python", ".php": "PHP", ".js": "JavaScript", ".jsx": "JavaScript",
            ".ts": "TypeScript", ".tsx": "TypeScript", ".cs": "C#", ".java": "Java",
            ".go": "Go", ".rs": "Rust", ".cpp": "C++", ".cc": "C++", ".cxx": "C++",
            ".c": "C", ".rb": "Ruby", ".kt": "Kotlin", ".swift": "Swift", ".scala": "Scala",
            ".dart": "Dart", ".ex": "Elixir", ".exs": "Elixir",
        }
        manifest_names = {
            "package.json", "pyproject.toml", "requirements.txt", "pipfile", "pipfile.lock", "poetry.lock", "uv.lock",
            "composer.json", "composer.lock", "cargo.toml", "cargo.lock", "go.mod", "go.sum",
            "pom.xml", "build.gradle", "build.gradle.kts", "gradlew", "gradlew.bat", "makefile",
            "cmakelists.txt", "gemfile", "gemfile.lock", "mix.exs", "pubspec.yaml", "deno.json", "deno.jsonc",
            "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb",
        }
        project_suffixes = {".sln", ".csproj", ".fsproj", ".vbproj"}
        raw_files = self._git_files(base)
        if raw_files is None:
            raw_files = []
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if d.lower() not in self.ignore_dirs]
                for name in filenames:
                    p = Path(dirpath) / name
                    ext = p.suffix.lower()
                    if ext not in language_by_ext and name.lower() not in manifest_names and ext not in project_suffixes:
                        continue
                    raw_files.append(p)
                    if len(raw_files) >= self.max_files:
                        break
                if len(raw_files) >= self.max_files:
                    break
        raw_files = raw_files[:self.max_files]
        languages: Counter[str] = Counter()
        manifests: list[str] = []
        by_name: dict[str, list[Path]] = {}
        basenames: set[str] = set()

        for path in raw_files:
            try:
                rel = str(path.resolve(strict=False).relative_to(base)).replace("\\", "/")
            except ValueError:
                continue
            ext = path.suffix.lower()
            language = language_by_ext.get(ext)
            if language:
                languages[language] += 1
            name = path.name.lower()
            basenames.add(name)
            by_name.setdefault(name, []).append(path)
            if name in manifest_names or ext in project_suffixes:
                manifests.append(rel)

        tools: set[str] = set()
        commands: list[dict[str, str]] = []

        def add_command(command: str, purpose: str, confidence: str = "high") -> None:
            if not any(x["command"] == command for x in commands):
                commands.append({"command": command, "purpose": purpose, "confidence": confidence})

        package_files = by_name.get("package.json", [])[:20]
        if package_files:
            tools.add("node")
            package_manager = "npm"
            if "pnpm-lock.yaml" in basenames:
                package_manager = "pnpm"
            elif "yarn.lock" in basenames:
                package_manager = "yarn"
            elif "bun.lock" in basenames or "bun.lockb" in basenames:
                package_manager = "bun"
            tools.add(package_manager)
            import json
            for package_file in package_files:
                try:
                    if package_file.stat().st_size > 1_000_000:
                        continue
                    data = json.loads(package_file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
                if isinstance(scripts, dict):
                    for script, purpose in [("test", "tests"), ("lint", "lint"), ("typecheck", "type-check"), ("check", "checks"), ("build", "build")]:
                        if script in scripts:
                            add_command(f"{package_manager} run {script}", purpose)
                deps: dict[str, Any] = {}
                for section in ("dependencies", "devDependencies"):
                    value = data.get(section, {}) if isinstance(data, dict) else {}
                    if isinstance(value, dict):
                        deps.update(value)
                for dep, label in [("typescript", "typescript"), ("eslint", "eslint"), ("vitest", "vitest"), ("jest", "jest"), ("next", "nextjs"), ("vite", "vite")]:
                    if dep in deps:
                        tools.add(label)

        pyproject_files = by_name.get("pyproject.toml", [])[:20]
        requirements_files = by_name.get("requirements.txt", [])[:20]
        if pyproject_files or requirements_files or languages.get("Python"):
            tools.add("python")
            all_py_parts: list[str] = []
            for file in [*pyproject_files, *requirements_files]:
                try:
                    if file.stat().st_size <= 1_000_000:
                        all_py_parts.append(file.read_text(encoding="utf-8", errors="replace").lower())
                except Exception:
                    pass
            all_py = "\n".join(all_py_parts)
            if "pytest" in all_py:
                tools.add("pytest"); add_command("python -m pytest", "tests")
            if "ruff" in all_py:
                tools.add("ruff"); add_command("ruff check .", "lint")
            if "mypy" in all_py:
                tools.add("mypy"); add_command("mypy .", "type-check", "medium")
            if "pyright" in all_py:
                tools.add("pyright"); add_command("pyright", "type-check", "medium")

        composer_files = by_name.get("composer.json", [])[:20]
        if composer_files or languages.get("PHP"):
            tools.add("php")
            import json
            for composer in composer_files:
                try:
                    if composer.stat().st_size > 1_000_000:
                        continue
                    data = json.loads(composer.read_text(encoding="utf-8"))
                except Exception:
                    continue
                scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
                if isinstance(scripts, dict):
                    for script, purpose in [("test", "tests"), ("phpunit", "tests"), ("phpstan", "static-analysis"), ("cs", "style/checks"), ("check", "checks")]:
                        if script in scripts:
                            add_command(f"composer {script}", purpose)
                reqs: dict[str, Any] = {}
                for section in ("require", "require-dev"):
                    value = data.get(section, {}) if isinstance(data, dict) else {}
                    if isinstance(value, dict):
                        reqs.update(value)
                for dep, label in [("phpunit/phpunit", "phpunit"), ("phpstan/phpstan", "phpstan"), ("cakephp/cakephp", "cakephp"), ("laravel/framework", "laravel"), ("symfony/framework-bundle", "symfony")]:
                    if dep in reqs:
                        tools.add(label)

        if "cargo.toml" in basenames or languages.get("Rust"):
            tools.update({"rust", "cargo"}); add_command("cargo test", "tests"); add_command("cargo check", "type/build-check")
        if "go.mod" in basenames or languages.get("Go"):
            tools.add("go"); add_command("go test ./...", "tests")
        if any(Path(x).suffix.lower() in project_suffixes for x in manifests) or languages.get("C#"):
            tools.add("dotnet"); add_command("dotnet test", "tests", "medium"); add_command("dotnet build --no-restore", "build", "medium")
        if "pom.xml" in basenames:
            tools.add("maven"); add_command("mvn test", "tests")
        if "build.gradle" in basenames or "build.gradle.kts" in basenames:
            tools.add("gradle")
            gradle_cmd = ".\\gradlew.bat test" if os.name == "nt" and "gradlew.bat" in basenames else "./gradlew test" if "gradlew" in basenames else "gradle test"
            add_command(gradle_cmd, "tests")
        if "makefile" in basenames:
            tools.add("make")

        ci: list[str] = []
        for candidate in [".github/workflows", ".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile"]:
            if (base / candidate).exists():
                ci.append(candidate)

        manifests = sorted(set(manifests), key=lambda x: (x.count("/"), x.lower()))[:80]
        return {
            "success": True,
            "root": str(base),
            "scanned_paths": len(raw_files),
            "languages": [{"name": name, "files": count} for name, count in languages.most_common(12)],
            "manifests": manifests,
            "tools": sorted(tools),
            "validation_commands": commands[:24],
            "ci": ci,
            "note": "Validation commands are detected/suggested only; Local AI Hub does not execute project code.",
        }

