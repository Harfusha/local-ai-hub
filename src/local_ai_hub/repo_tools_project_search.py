from __future__ import annotations

from collections.abc import Callable, Generator, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
import fnmatch
import heapq
from itertools import chain, islice
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import subprocess
import threading
import time
from typing import Any

from .process_utils import hidden_run_kwargs, popen_managed, run_hidden, terminate_tree
from .repo_tools_constants import (
    MAX_EXACT_GIT_PATH_BYTES,
    MAX_EXACT_GIT_PATHS,
    MAX_EXACT_SEARCH_FILES,
    _HARD_SEARCH_DIRS,
    _MAX_PATH_CONTROLS,
    _UNSET_GIT_INVENTORY,
)
from .repo_tools_models import FileTooLargeError, _IncompleteGitInventory
from .repo_tools_path_helpers import (
    _intent_path_adjustment,
    _lower_expansion_characters,
    _unicode_lower_expansions,
    is_root_archive_path,
)


RepositoryTools = None


class RepoToolsProjectSearchMixin:
    @staticmethod
    def _project_settings_values(project_settings: Any | None) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], int | None]:
        if project_settings is None:
            return (), (), (), None
        text_extensions = tuple(
            str(value).casefold() for value in getattr(project_settings, "text_extensions", ())
            if isinstance(value, str)
        )
        binary_extensions = tuple(
            str(value).casefold() for value in getattr(project_settings, "binary_extensions", ())
            if isinstance(value, str)
        )
        forced = [
            str(value) for value in getattr(project_settings, "force_include_paths", ())
            if isinstance(value, str)
        ]
        overrides = getattr(project_settings, "path_overrides", {})
        if isinstance(overrides, Mapping):
            forced.extend(str(path) for path, action in tuple(overrides.items()) if action == "include")
        maximum = getattr(project_settings, "max_file_size_bytes", None)
        if isinstance(maximum, bool) or (maximum is not None and not isinstance(maximum, int)):
            maximum = 0
        return text_extensions, binary_extensions, tuple(forced), maximum

    @staticmethod
    def _project_path_matches(relative: str, patterns: tuple[str, ...]) -> bool:
        from .project_config import path_matches_pattern

        return any(path_matches_pattern(relative, pattern) for pattern in patterns)

    def _project_file_allowed(
        self, base: Path, path: Path, project_settings: Any, *, force_include: bool = False,
        project_path_policy: Any | None = None,
    ) -> bool:
        return self._project_file_stat(
            base, path, project_settings, force_include=force_include,
            project_path_policy=project_path_policy,
        ) is not None

    def _project_file_stat(
        self, base: Path, path: Path, project_settings: Any, *, force_include: bool = False,
        project_path_policy: Any | None = None,
    ) -> os.stat_result | None:
        try:
            relative_candidate = path.relative_to(base)
            if not relative_candidate.parts or any(part in {".", ".."} for part in relative_candidate.parts):
                return None
            relative = relative_candidate.as_posix()
            if any(part.casefold() in _HARD_SEARCH_DIRS for part in relative_candidate.parts[:-1]):
                return None
            if is_root_archive_path(relative_candidate):
                return None
            if relative_candidate.name in {".local-ai.toml", ".local-ai.worktree.toml"}:
                return None
            _text, _binary, forced_patterns, _maximum = self._project_settings_values(project_settings)
            force_include = force_include or self._project_path_matches(relative, forced_patterns)
            soft_ignored = any(part.casefold() in self.ignore_dirs for part in relative_candidate.parts[:-1])
            if soft_ignored and not force_include:
                return None

            cached_root = getattr(project_path_policy, "project_root", None)
            resolved_paths = self._resolve_inventory_path_safe_with_stat(
                base,
                path,
                resolved_base=cached_root if isinstance(cached_root, Path) else None,
            )
            if resolved_paths is None:
                return None
            resolved_base, resolved, inventory_stat = resolved_paths
            lexical_relative = relative
            size_bytes = inventory_stat.st_size
            if size_bytes > self.max_file_bytes:
                return None
            if project_path_policy is None:
                from .project_config import path_is_allowed

                allowed = path_is_allowed(
                    base, resolved, project_settings, phase="search",
                    soft_ignored=soft_ignored and not force_include, size_bytes=size_bytes,
                )
            else:
                allowed = project_path_policy.allows(
                    resolved, phase="search",
                    soft_ignored=soft_ignored and not force_include, size_bytes=size_bytes,
                    _resolved_candidate=resolved,
                    _lexical_relative=lexical_relative,
                )
            if not allowed:
                return None
            if not self._path_extension_is_searchable(resolved, project_settings=project_settings):
                return None
            return inventory_stat
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            return None

    def _expand_project_force_paths(
        self, base: Path, project_settings: Any, limit: int,
        *, extra_patterns: Sequence[str] = (),
    ) -> list[Path]:
        _text, _binary, patterns, _maximum = self._project_settings_values(project_settings)
        if extra_patterns:
            patterns = tuple(dict.fromkeys((*patterns, *extra_patterns)))
        found: dict[str, Path] = {}
        entry_budget = max(256, min(65_536, max(1, limit) * 32))
        deadline = time.monotonic() + min(2.0, self.git_files_timeout)
        entries_seen = 0
        for raw_pattern in patterns[:_MAX_PATH_CONTROLS]:
            pattern = raw_pattern.replace("\\", "/").strip()
            pure = PureWindowsPath(pattern)
            parts = tuple(part for part in pattern.split("/") if part not in {"", "."})
            if not parts or pure.is_absolute() or pure.drive or any(part == ".." for part in parts):
                continue
            stack: list[tuple[Path, int]] = [(base, 0)]
            visited: set[tuple[str, int]] = set()
            while stack and len(found) < limit and entries_seen < entry_budget and time.monotonic() < deadline:
                directory, index = stack.pop()
                try:
                    directory.resolve(strict=True).relative_to(base)
                    key = (str(directory), index)
                    if key in visited:
                        continue
                    visited.add(key)
                    if index >= len(parts):
                        if directory.is_file():
                            found[str(directory)] = directory
                        continue
                    segment = parts[index]
                    with os.scandir(directory) as scanner:
                        for entry in scanner:
                            entries_seen += 1
                            if entries_seen > entry_budget or time.monotonic() >= deadline:
                                break
                            if entry.is_symlink():
                                continue
                            child = Path(entry.path)
                            if not self._inventory_path_safe(base, child):
                                continue
                            relative_parts = child.relative_to(base).parts
                            denied_parts = relative_parts if entry.is_dir(follow_symlinks=False) else relative_parts[:-1]
                            if any(part.casefold() in _HARD_SEARCH_DIRS for part in denied_parts):
                                continue
                            if entry.is_dir(follow_symlinks=False) and is_root_archive_path(child.relative_to(base)):
                                continue
                            if segment == "**":
                                stack.append((directory, index + 1))
                                if entry.is_dir(follow_symlinks=False):
                                    stack.append((child, index))
                                elif index == len(parts) - 1 and entry.is_file(follow_symlinks=False):
                                    found[str(child)] = child
                            elif fnmatch.fnmatchcase(entry.name, segment):
                                if index == len(parts) - 1 and entry.is_file(follow_symlinks=False):
                                    found[str(child)] = child
                                elif entry.is_dir(follow_symlinks=False):
                                    stack.append((child, index + 1))
                except (OSError, RuntimeError, ValueError):
                    continue
        return list(found.values())[:limit]

    def _iter_project_search_files(
        self, base: Path, project_settings: Any, max_depth: int,
        *, git_inventory: Any = _UNSET_GIT_INVENTORY,
        candidate_limit: int | None = None,
        candidate_priority_terms: Iterable[str] = (),
        candidate_path_priority: Callable[[str], int] | None = None,
        phase_timings_ms: dict[str, float] | None = None,
    ) -> Iterable[Path]:
        limit = max(1, min(int(self.max_files), 100_000))
        if candidate_limit is not None:
            limit = min(limit, max(1, int(candidate_limit)))
        _text, _binary, _forced, maximum = self._project_settings_values(project_settings)
        from .project_config import ProjectPathPolicy

        project_path_policy = ProjectPathPolicy(base, project_settings)
        forced_paths = self._expand_project_force_paths(base, project_settings, limit)
        seen: set[str] = set()
        yielded = 0
        for path in forced_paths:
            try:
                key = os.path.normcase(path.relative_to(base).as_posix())
            except ValueError:
                continue
            if key in seen or not self._project_file_allowed(
                base, path, project_settings, force_include=True,
                project_path_policy=project_path_policy,
            ):
                continue
            seen.add(key)
            yielded += 1
            yield path
            if yielded >= limit:
                return

        pinned_context = getattr(project_settings, "pinned_context", ())
        if isinstance(pinned_context, (list, tuple)):
            for raw_path in pinned_context[:_MAX_PATH_CONTROLS]:
                if not isinstance(raw_path, str) or not raw_path.strip():
                    continue
                relative_path = Path(raw_path.replace("\\", "/"))
                if relative_path.is_absolute() or any(
                    part in {"", ".", ".."} for part in relative_path.parts
                ):
                    continue
                path = base / relative_path
                key = os.path.normcase(relative_path.as_posix())
                # Pinned context improves candidate order, but does not bypass
                # project access policy, extension checks, or symlink guards.
                if key in seen or not self._project_file_allowed(
                    base, path, project_settings,
                    project_path_policy=project_path_policy,
                ):
                    continue
                seen.add(key)
                yielded += 1
                yield path
                if yielded >= limit:
                    return

        git_files = (
            self._git_files(base)
            if git_inventory is _UNSET_GIT_INVENTORY
            else git_inventory
        )
        if git_files is not None:
            candidates = git_files
        else:
            candidates = []
            entry_budget = max(256, min(65_536, limit * 16))
            entries_seen = 0
            try:
                for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
                    relative_dir = Path(dirpath).relative_to(base)
                    depth = len(relative_dir.parts)
                    dirnames[:] = sorted((
                        name for name in dirnames
                        if name.casefold() not in _HARD_SEARCH_DIRS
                        and name.casefold() not in self.ignore_dirs
                        and depth < max_depth
                        and self._inventory_path_safe(base, Path(dirpath) / name)
                    ), key=lambda name: (
                        candidate_path_priority((relative_dir / name).as_posix()) if candidate_path_priority else 0,
                        name.casefold(), name,
                    ))
                    for name in sorted(filenames, key=lambda value: (
                        candidate_path_priority((relative_dir / value).as_posix()) if candidate_path_priority else 0,
                        value.casefold(), value,
                    )):
                        entries_seen += 1
                        if entries_seen > entry_budget:
                            break
                        candidates.append(Path(dirpath) / name)
                    if entries_seen > entry_budget:
                        break
            except (OSError, RuntimeError, ValueError):
                pass

        candidate_priority_started = time.perf_counter()
        entry_points = getattr(project_settings, "entry_points", ())
        entry_point_parts: list[tuple[str, ...]] = []
        if isinstance(entry_points, (list, tuple)):
            for raw_entry in entry_points[:_MAX_PATH_CONTROLS]:
                if not isinstance(raw_entry, str) or not raw_entry.strip():
                    continue
                normalized_entry = raw_entry.replace("\\", "/").strip("/")
                parts = tuple(part for part in normalized_entry.split("/") if part)
                if (
                    not parts or any(part in {".", ".."} for part in parts)
                    or PureWindowsPath(normalized_entry).is_absolute()
                    or PureWindowsPath(normalized_entry).drive
                ):
                    continue
                entry_point_parts.append(parts)
        if entry_point_parts and candidates:
            priority_groups: list[list[Path]] = [[] for _ in entry_point_parts]
            remaining_candidates: list[Path] = []
            for candidate in candidates:
                try:
                    relative_parts = candidate.relative_to(base).parts
                except ValueError:
                    remaining_candidates.append(candidate)
                    continue
                matched_rank = next((
                    rank for rank, prefix in enumerate(entry_point_parts)
                    if relative_parts[:len(prefix)] == prefix
                ), None)
                if matched_rank is None:
                    remaining_candidates.append(candidate)
                else:
                    priority_groups[matched_rank].append(candidate)
            candidates = [
                *[path for group in priority_groups for path in group],
                *remaining_candidates,
            ]

        priority_terms = {
            term.casefold() for term in candidate_priority_terms
            if isinstance(term, str) and term
        }
        if candidate_limit is not None and priority_terms and candidates:
            selection_limit = max(0, limit - yielded)

            def path_term_rank(item: tuple[int, Path]) -> tuple[int, int, int]:
                position, candidate = item
                stem = candidate.stem.casefold()
                overlap = sum(
                    1 for term in priority_terms
                    if stem == term
                    or (len(term) >= 4 and stem.startswith(term))
                    or (len(stem) >= 4 and term.startswith(stem))
                )
                try:
                    preferred = candidate_path_priority(candidate.relative_to(base).as_posix()) if candidate_path_priority else 0
                except ValueError:
                    preferred = 1
                return (preferred, -overlap, position)

            candidates = [
                path for _position, path in heapq.nsmallest(
                    selection_limit, enumerate(candidates), key=path_term_rank,
                )
            ]
        elif candidate_limit is not None and candidate_path_priority and candidates:
            def hint_rank(candidate: Path) -> int:
                try:
                    return candidate_path_priority(candidate.relative_to(base).as_posix())
                except ValueError:
                    return 1
            candidates = heapq.nsmallest(max(0, limit - yielded), candidates, key=hint_rank)

        if phase_timings_ms is not None:
            phase_timings_ms["candidate_priority_sort_ms"] = round(
                (time.perf_counter() - candidate_priority_started) * 1000.0, 1,
            )

        if candidate_limit is not None:
            candidates = candidates[:max(0, limit - yielded)]

        candidate_path_validation_started = time.perf_counter()
        try:
            def validation_pairs():
                for path in candidates:
                    if yielded >= limit:
                        break
                    try:
                        relative_path = path.relative_to(base)
                    except ValueError:
                        continue
                    key = os.path.normcase(relative_path.as_posix())
                    if key in seen or any(part.casefold() in _HARD_SEARCH_DIRS for part in relative_path.parts[:-1]):
                        continue
                    if any(part.casefold() in self.ignore_dirs for part in relative_path.parts[:-1]):
                        continue
                    yield path, key

            def is_allowed(path: Path) -> bool:
                return self._project_file_allowed(
                    base, path, project_settings,
                    project_path_policy=project_path_policy,
                )

            def accept_validated(items: Iterable[tuple[Path, str]], allowed: Iterable[bool]):
                nonlocal yielded
                for (path, key), is_valid in zip(items, allowed):
                    if not is_valid:
                        continue
                    seen.add(key)
                    yielded += 1
                    yield path

            if candidate_limit is not None:
                validation_candidates = list(validation_pairs())
                pending_keys: set[str] = set()
                deduplicated = []
                for path, key in validation_candidates:
                    if key in pending_keys:
                        continue
                    pending_keys.add(key)
                    deduplicated.append((path, key))
                if len(deduplicated) >= 32:
                    with ThreadPoolExecutor(
                        max_workers=min(8, len(deduplicated)),
                        thread_name_prefix="repo-path-check",
                    ) as executor:
                        yield from accept_validated(
                            deduplicated,
                            executor.map(is_allowed, (path for path, _key in deduplicated)),
                        )
                else:
                    yield from accept_validated(
                        deduplicated,
                        map(is_allowed, (path for path, _key in deduplicated)),
                    )
            else:
                for path, key in validation_pairs():
                    if not is_allowed(path):
                        continue
                    seen.add(key)
                    yielded += 1
                    yield path
        finally:
            if phase_timings_ms is not None:
                phase_timings_ms["candidate_path_validation_ms"] = round(
                    (time.perf_counter() - candidate_path_validation_started) * 1000.0, 1,
                )

    def _read_search_snapshots(
        self, jobs: list[tuple[Any, Path]],
    ):
        """Read search files in order with bounded workers and queued snapshots."""
        if not jobs:
            return

        worker_count = min(4, len(jobs))
        pending_limit = min(8, worker_count * 2)

        def read(path: Path) -> tuple[str | None, list[str] | None, OSError | None]:
            try:
                stat = path.stat()
                if stat.st_size > self.max_file_bytes:
                    raise FileTooLargeError(f"{path} exceeds {self.max_file_bytes} bytes")
                file_hash, lines = self._read_snapshot(path, stat=stat)
                return file_hash, lines, None
            except OSError as exc:
                return None, None, exc

        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="repo-search-read") as pool:
            for offset in range(0, len(jobs), pending_limit):
                batch = jobs[offset:offset + pending_limit]
                for (metadata, _path), (file_hash, lines, error) in zip(
                    batch, pool.map(read, (path for _metadata, path in batch)),
                ):
                    yield metadata, file_hash, lines, error

    @staticmethod
    def _format_search_snippet(
        lines: Any,
        start: int,
        end: int,
        *,
        max_line_chars: int = 1000,
        max_total_chars: int = 4000,
    ) -> str:
        parts: list[str] = []
        total = 0
        for idx in range(start, end):
            line = lines[idx]
            if len(line) > max_line_chars:
                line = line[:max_line_chars] + " ... [line truncated]"
            formatted = f"{idx + 1}: {line}"
            if total + len(formatted) > max_total_chars and parts:
                remaining = end - idx
                parts.append(f"... [{remaining} lines omitted to fit snippet bound]")
                break
            parts.append(formatted)
            total += len(formatted)
        return "\n".join(parts)

    def _exact_search_page(
        self, base: Path, query: str, limit: int, offset: int,
        context_lines: int | None, project_settings: Any | None,
        git_inventory: Any, force_include_paths: list[str] | tuple[str, ...],
        path_priority: Callable[[str], tuple[int, int, int]] | None,
        installation_intent_priority: bool,
    ) -> dict[str, Any]:
        """Count every eligible result while retaining only the requested prefix."""
        terms = self._terms(query)
        raw_phrase = query.strip()
        phrase = raw_phrase.lower()
        symbol_query = (
            bool(raw_phrase)
            and not any(ch.isspace() for ch in raw_phrase)
            and (
                any(ch in raw_phrase for ch in ("_", "::", "/", "\\", ".", "+", "#", "$", ":"))
                or re.search(r"[a-z][A-Z]", raw_phrase) is not None
            )
        )
        case_sensitive_symbol_query = symbol_query and raw_phrase.isascii()
        if not terms and phrase:
            terms = [phrase]
        declaration_pattern = (
            re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([^\W\d]\w*)\b")
            if phrase.isidentifier() else None
        )
        if not terms and not phrase:
            return {
                "success": True, "root": str(base), "results": [], "terms": [],
                "total_matches": 0, "returned_count": 0, "has_more": False,
                "limit": limit, "offset": offset, "truncated": False,
                "count_exact": True, "engine": "python_exact",
            }

        snippet_lines = max(1, min(int(context_lines), 40)) if context_lines is not None else self.snippet_lines
        project_path_policy = None
        if project_settings is not None:
            from .project_config import ProjectPathPolicy

            project_path_policy = ProjectPathPolicy(base, project_settings)
        retain_count = offset + limit
        file_cap = max(1, min(int(self.max_files), MAX_EXACT_SEARCH_FILES))
        deadline = time.monotonic() + 60.0

        def remaining_candidate_time() -> float:
            return max(0.001, deadline - time.monotonic())

        extension_check = getattr(self, "_path_extension_is_searchable", None)
        force_patterns = tuple(force_include_paths or ())
        configured_state_relative: Path | None = None
        server_config = self.config.get("server", {})
        raw_state_dir = server_config.get("state_dir") if isinstance(server_config, Mapping) else None
        if isinstance(raw_state_dir, (str, os.PathLike)) and os.fspath(raw_state_dir).strip():
            try:
                state_path = Path(raw_state_dir).expanduser()
                if not state_path.is_absolute():
                    state_path = Path.cwd() / state_path
                configured_state_relative = state_path.resolve(strict=False).relative_to(base)
            except (OSError, RuntimeError, TypeError, ValueError):
                configured_state_relative = None

        matching_relpaths: set[str] | None = None
        git_grep_candidates_authoritative = False
        ripgrep_candidates_authoritative = False
        ripgrep_timed_out_after: float | None = None
        # Ripgrep uses simple Unicode folding. Use it only where candidate
        # coverage is provably complete; Python verifies candidates and counts.
        simple_casefold_query = all(
            len(char.lower()) == 1
            and len(char.casefold()) == 1
            and char.lower() == char.casefold()
            for char in phrase
        ) and all(
            len(char.lower()) == 1
            and len(char.casefold()) == 1
            and char.lower() == char.casefold()
            for term in terms
            for char in term
        )
        # Python verifies text with .lower(), while ripgrep uses Unicode simple
        # folding. Add source characters whose lowercase expansion contains a
        # query character so ripgrep remains a complete candidate filter; Python
        # still verifies every candidate and produces exact counts.
        lower_expansion_characters = _lower_expansion_characters()
        expansion_candidate_sources = tuple(
            source for source in _unicode_lower_expansions()[0]
            if any(char in phrase for char in source.lower())
        ) if any(char in lower_expansion_characters for char in phrase) else ()
        lower_complete_query = (
            case_sensitive_symbol_query
            or not any(char in lower_expansion_characters for char in phrase)
            or bool(expansion_candidate_sources)
        )
        ripgrep_candidates_complete = (
            bool(terms)
            and len(terms) <= 16
            and lower_complete_query
            and (phrase.isascii() or simple_casefold_query)
            # The verifier preserves BOMs and inserts U+FFFD for malformed UTF-8.
            and "\ufeff" not in phrase
            and "\ufffd" not in phrase
        )
        if (
            self.use_git_grep
            and self.prefer_git
            and (base / ".git").exists()
            and ripgrep_candidates_complete
            and not (self.use_ripgrep and self._rg)
        ):
            git_grep_cmd = [
                "git", "-C", str(base), "grep", "--files-with-matches",
                "--fixed-strings", "--text", "--null",
                "--untracked", "--exclude-standard",
            ]
            if not case_sensitive_symbol_query:
                git_grep_cmd.append("--ignore-case")
            candidate_terms = [raw_phrase] if case_sensitive_symbol_query else terms[:16]
            for term in candidate_terms:
                git_grep_cmd.extend(["-e", term])
            if not case_sensitive_symbol_query:
                for source in expansion_candidate_sources:
                    git_grep_cmd.extend(["-e", source])
            if (
                not case_sensitive_symbol_query
                and phrase and len(phrase) <= 120 and phrase not in terms
            ):
                git_grep_cmd.extend(["-e", phrase])
            pathspecs: list[str] = ["."]
            for directory_name in sorted(self.ignore_dirs):
                pathspecs.append(f":(exclude,glob)**/{directory_name}/**")
            project_excludes = getattr(project_settings, "exclude_paths", ())
            if isinstance(project_excludes, (list, tuple)):
                for pattern in project_excludes:
                    if not isinstance(pattern, str):
                        continue
                    if re.fullmatch(r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+/\*\*", pattern):
                        if not any(part in {".", ".."} for part in pattern[:-3].split("/")):
                            pathspecs.append(f":(exclude,glob){pattern}")
                    elif re.fullmatch(r"[A-Za-z0-9_.-]+\*?", pattern):
                        pathspecs.append(f":(exclude,glob){pattern}")
            if configured_state_relative and configured_state_relative.parts and all(
                not any(char in part for char in "*?[]{}")
                for part in configured_state_relative.parts
            ):
                pathspecs.append(
                    f":(exclude,glob){configured_state_relative.as_posix()}/**"
                )
            git_grep_cmd.extend(["--", *pathspecs])
            try:
                proc = run_hidden(
                    git_grep_cmd,
                    capture_output=True,
                    text=False,
                    timeout=min(self.git_grep_timeout, 10.0, remaining_candidate_time()),
                    max_output_bytes=MAX_EXACT_GIT_PATH_BYTES,
                    cwd=str(base),
                )
                if proc.returncode in (0, 1) and not proc.stderr and not getattr(proc, "stdout_truncated", False):
                    git_grep_candidates_authoritative = True
                    matching_relpaths = set()
                    for raw_path in proc.stdout.split(b"\0"):
                        if not raw_path:
                            continue
                        try:
                            relative = raw_path.decode("utf-8", errors="surrogateescape")
                            p = Path(relative)
                            if p.is_absolute():
                                rel_path = p.resolve(strict=False).relative_to(base).as_posix()
                            else:
                                rel_path = p.as_posix()
                                if rel_path.startswith("./"):
                                    rel_path = rel_path[2:]
                            matching_relpaths.add(rel_path)
                        except (OSError, RuntimeError, TypeError, ValueError):
                            continue
            except Exception:
                matching_relpaths = None

        if matching_relpaths is None and self.use_ripgrep and self._rg and ripgrep_candidates_complete:
            # The verifier decodes raw bytes as UTF-8 even after a UTF-16 BOM.
            rg_cmd = [
                self._rg, "--no-config", "--glob-case-insensitive", "--files-with-matches", "--null", "--text",
                "--encoding", "none", "--fixed-strings", "--hidden", "--no-ignore",
                "-g", "!.git/**",
            ]
            if 0 <= self.max_file_bytes < (1 << 64):
                rg_cmd.extend(["--max-filesize", str(self.max_file_bytes)])
            if not case_sensitive_symbol_query:
                rg_cmd.append("--ignore-case")
            # Exact search applies the project's ignore policy after candidate
            # discovery, so mirror those directory exclusions in ripgrep too.
            # Otherwise --no-ignore scans large ignored environments/state
            # trees (for example .venv and tool-envs) before the bounded exact
            # pass can inspect the repository's eligible files.
            for d in sorted(self.ignore_dirs):
                rg_cmd.extend(["-g", f"!**/{d}/**"])
            # Only translate literal, root-relative directory exclusions. More
            # expressive project patterns retain their existing post-filtering;
            # guessing glob equivalence here could hide eligible matches.
            project_excludes = getattr(project_settings, "exclude_paths", ())
            # Project globs are case-sensitive on POSIX, while this ripgrep
            # invocation uses case-insensitive globs for built-in ignores.
            if os.name == "nt" and isinstance(project_excludes, (list, tuple)):
                for pattern in project_excludes:
                    if not isinstance(pattern, str):
                        continue
                    if re.fullmatch(r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+/\*\*", pattern):
                        if any(part in {".", ".."} for part in pattern[:-3].split("/")):
                            continue
                        rg_cmd.extend(["-g", f"!{pattern}"])
                    elif re.fullmatch(r"[A-Za-z0-9_.-]+\*?", pattern):
                        # Safe basename-only file patterns can be applied before
                        # rg reads ignored user config and backup files.
                        rg_cmd.extend(["-g", f"!{pattern}"])
            if configured_state_relative and configured_state_relative.parts and all(
                not any(char in part for char in "*?[]{}")
                for part in configured_state_relative.parts
            ):
                rg_cmd.extend(["-g", f"!{configured_state_relative.as_posix()}/**"])
            candidate_terms = [raw_phrase] if case_sensitive_symbol_query else terms[:16]
            for term in candidate_terms:
                rg_cmd.extend(["-e", term])
            if not case_sensitive_symbol_query:
                for source in expansion_candidate_sources:
                    rg_cmd.extend(["-e", source])
            if (
                not case_sensitive_symbol_query
                and phrase and len(phrase) <= 120 and phrase not in terms
            ):
                rg_cmd.extend(["-e", phrase])
            rg_cmd.append(".")
            ripgrep_timeout = min(self.ripgrep_timeout, remaining_candidate_time())
            try:
                proc = run_hidden(
                    rg_cmd,
                    capture_output=True,
                    text=False,
                    timeout=ripgrep_timeout,
                    max_output_bytes=MAX_EXACT_GIT_PATH_BYTES,
                    cwd=str(base),
                )
                if (proc.returncode in (0, 1) and not proc.stderr
                        and not getattr(proc, "stdout_truncated", False)
                        and not getattr(proc, "stderr_truncated", False)
                        and (not proc.stdout or proc.stdout.endswith(b"\0"))):
                    candidate_paths: set[str] = set()
                    candidate_bytes = 0
                    candidates_complete = True
                    # Line separators can be part of an eligible filename.
                    for record in re.finditer(rb"([^\0]+)\0", proc.stdout):
                        try:
                            raw_path = record[1]
                            p = Path(raw_path.decode("utf-8", errors="surrogateescape"))
                            if p.is_absolute():
                                rel_p = p.resolve(strict=False).relative_to(base).as_posix()
                            else:
                                rel_p = p.as_posix()
                                if rel_p.startswith("./"):
                                    rel_p = rel_p[2:]
                            candidate_bytes += len(rel_p.encode("utf-8", errors="surrogateescape"))
                            candidate_paths.add(rel_p)
                            if (
                                len(candidate_paths) > MAX_EXACT_GIT_PATHS
                                or candidate_bytes > MAX_EXACT_GIT_PATH_BYTES
                            ):
                                candidates_complete = False
                                break
                        except (OSError, RuntimeError, ValueError, UnicodeError):
                            candidates_complete = False
                            break
                    if candidates_complete:
                        matching_relpaths = candidate_paths
                        ripgrep_candidates_authoritative = True
            except subprocess.TimeoutExpired:
                ripgrep_timed_out_after = ripgrep_timeout
            except Exception:
                matching_relpaths = None

        if (
            ripgrep_candidates_authoritative
            and matching_relpaths is not None
            and self.prefer_git
            and (base / ".git").exists()
        ):
            if not matching_relpaths:
                git_grep_candidates_authoritative = True
            else:
                try:
                    ignore_input = b"".join(
                        relative.encode("utf-8", errors="surrogateescape") + b"\0"
                        for relative in sorted(matching_relpaths)
                    )
                    ignored = run_hidden(
                        ["git", "-C", str(base), "check-ignore", "--stdin", "-z"],
                        input=ignore_input,
                        capture_output=True,
                        text=False,
                        timeout=min(self.git_files_timeout, 10.0, remaining_candidate_time()),
                        max_output_bytes=MAX_EXACT_GIT_PATH_BYTES,
                        cwd=str(base),
                    )
                    if (
                        ignored.returncode in (0, 1) and not ignored.stderr
                        and not getattr(ignored, "stdout_truncated", False)
                    ):
                        ignored_relpaths = {
                            Path(raw.decode("utf-8", errors="surrogateescape")).as_posix()
                            for raw in ignored.stdout.split(b"\0")
                            if raw
                        }
                        if ignored_relpaths.issubset(matching_relpaths):
                            matching_relpaths.difference_update(ignored_relpaths)
                            git_grep_candidates_authoritative = True
                except Exception:
                    pass

        def candidates() -> Generator[Path, None, None]:
            if time.monotonic() >= deadline:
                raise TimeoutError("exact repository search exceeded 60 seconds")
            if git_inventory is not _UNSET_GIT_INVENTORY and getattr(git_inventory, "complete", True) is False:
                raise _IncompleteGitInventory(
                    f"Git inventory is truncated at the {file_cap}-file exact-search bound"
                )

            # A successful `git grep --files-with-matches --untracked
            # --exclude-standard` pass is already an authoritative, bounded
            # candidate set for this literal query. Re-reading every Git path
            # just to intersect it repeats the expensive part of exact search.
            # Exact Python matching below still reads, validates and counts each
            # eligible current source before results are returned.
            if git_grep_candidates_authoritative and matching_relpaths is not None:
                forced_inventory: set[str] = set()
                for forced_path in self._expand_project_force_paths(
                    base, project_settings, file_cap, extra_patterns=force_patterns,
                ):
                    try:
                        forced_inventory.add(forced_path.relative_to(base).as_posix())
                    except (OSError, RuntimeError, ValueError):
                        continue
                for relative in sorted(matching_relpaths | forced_inventory):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("exact repository search exceeded 60 seconds")
                    yield base / relative
                return

            if self.prefer_git and (base / ".git").exists():
                process = popen_managed(
                    ["git", "-C", str(base), "ls-files", "-co", "--exclude-standard", "-z"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    **hidden_run_kwargs(text=False),
                )
                timed_out = threading.Event()

                def stop_git() -> None:
                    if process.poll() is None:
                        timed_out.set()
                        try:
                            terminate_tree(process.pid, grace_seconds=0.1, process_handle=process)
                        except (OSError, ValueError):
                            pass

                inventory_timeout = min(self.git_files_timeout, remaining_candidate_time())
                inventory_deadline = time.monotonic() + inventory_timeout
                timer = threading.Timer(inventory_timeout, stop_git)
                timer.daemon = True
                timer.start()
                pending = bytearray()
                inventory: set[str] = set()
                inventory_bytes = 0
                inventory_path_count = 0

                def remember_path(raw: bytes) -> None:
                    nonlocal inventory_bytes, inventory_path_count
                    if not raw:
                        return
                    inventory_bytes += len(raw)
                    if inventory_bytes > MAX_EXACT_GIT_PATH_BYTES:
                        raise _IncompleteGitInventory("Git exact-search path bytes exceeded bounded inventory")
                    inventory_path_count += 1
                    if inventory_path_count > MAX_EXACT_GIT_PATHS:
                        raise _IncompleteGitInventory("Git exact-search path count exceeded bounded inventory")
                    relative = raw.decode("utf-8", errors="surrogateescape").replace("\\", "/")
                    normalized = Path(relative).as_posix()
                    # Keep Git's complete bounded inventory check, but retain
                    # only content candidates before deterministic ordering.
                    if matching_relpaths is None or normalized in matching_relpaths:
                        inventory.add(normalized)

                try:
                    assert process.stdout is not None
                    while True:
                        chunk = process.stdout.read(64 * 1024)
                        if not chunk:
                            break
                        pending.extend(chunk)
                        while True:
                            separator = pending.find(0)
                            if separator < 0:
                                if len(pending) > 64 * 1024:
                                    raise OSError("Git path exceeded bounded stream buffer")
                                break
                            raw = bytes(pending[:separator])
                            del pending[:separator + 1]
                            remember_path(raw)
                    if pending:
                        remember_path(bytes(pending))
                    try:
                        return_code = process.wait(timeout=max(0.001, inventory_deadline - time.monotonic()))
                    except subprocess.TimeoutExpired as exc:
                        raise TimeoutError("exact Git inventory exceeded its configured time bound") from exc
                    if timed_out.is_set():
                        raise TimeoutError("exact Git inventory exceeded its configured time bound")
                    if return_code != 0:
                        raise OSError("Git exact-search inventory failed")
                    for forced_path in self._expand_project_force_paths(
                        base, project_settings, file_cap, extra_patterns=force_patterns,
                    ):
                        try:
                            inventory.add(forced_path.relative_to(base).as_posix())
                        except (OSError, RuntimeError, ValueError):
                            continue
                    # Git groups cached and untracked output separately; -co is
                    # not globally ordered. Sort a hard-bounded, deduplicated set
                    # only after successful enumeration, preserving exactness.
                    for relative in sorted(inventory):
                        if time.monotonic() >= deadline:
                            raise TimeoutError("exact repository search exceeded 60 seconds")
                        yield base / relative
                finally:
                    timer.cancel()
                    try:
                        if process.poll() is None:
                            terminate_tree(process.pid, grace_seconds=0.1, process_handle=process)
                            try:
                                process.wait(timeout=1.0)
                            except subprocess.TimeoutExpired as exc:
                                raise TimeoutError("exact Git inventory process cleanup did not finish") from exc
                    finally:
                        if process.stdout is not None:
                            process.stdout.close()
                return

            # Exact mode does not consume an unchecked cached inventory. The Git
            # stream above has independent path-count/byte bounds; filesystem
            # fallback below remains streaming with the eligible-file scan cap.
            def raise_walk_error(error: OSError) -> None:
                raise error

            # Without a Git inventory, a successful complete ripgrep pass is
            # authoritative for file contents. Git roots keep their inventory
            # contract above; this accelerator only avoids a filesystem walk.
            if matching_relpaths is not None:
                forced_inventory: set[str] = set()
                for forced_path in self._expand_project_force_paths(
                    base, project_settings, file_cap, extra_patterns=force_patterns,
                ):
                    try:
                        forced_inventory.add(forced_path.relative_to(base).as_posix())
                    except (OSError, RuntimeError, ValueError):
                        continue
                for relative in sorted(matching_relpaths | forced_inventory):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("exact repository search exceeded 60 seconds")
                    yield base / relative
                return

            for directory, dirnames, filenames in os.walk(
                base, followlinks=False, onerror=raise_walk_error,
            ):
                dirnames[:] = [
                    name for name in dirnames
                    if name.casefold() not in _HARD_SEARCH_DIRS
                ]
                for filename in filenames:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("exact repository search exceeded 60 seconds")
                    yield Path(directory) / filename

        priority_path: str | None = None
        cached_priority = (0, 0, 0)

        class _WorstFirst:
            __slots__ = ("rank", "item")

            def __init__(self, item: dict[str, Any]) -> None:
                nonlocal priority_path, cached_priority
                self.item = item
                relative = str(item["path"])
                if relative != priority_path:
                    cached_priority = path_priority(relative) if path_priority else (0, 0, 0)
                    if (
                        installation_intent_priority
                        and len(cached_priority) >= 2
                        and _intent_path_adjustment(query, relative) > 0
                    ):
                        # A generic configured entry point must not outrank the
                        # actual user guide for a natural installation question.
                        # Keep explicit request hints first, then rank matching
                        # installation docs ahead of durable generic hints.
                        cached_priority = (
                            cached_priority[0], 0, *cached_priority[2:]
                        )
                    priority_path = relative
                priority = cached_priority
                score_rank = (
                    *priority, -float(item["score"]),
                    str(item["path"]), int(item["start_line"]),
                )
                self.rank = (
                    (int(item.get("path_hit_ordinal", 0)), *score_rank)
                    if phrase.isidentifier() else score_rank
                )

            def __lt__(self, other: Any) -> bool:
                return self.rank > other.rank

        def retain(heap: list[Any], item: dict[str, Any], maximum: int) -> None:
            entry = _WorstFirst(item)
            if len(heap) < maximum:
                heapq.heappush(heap, entry)
            elif entry.rank < heap[0].rank:
                heapq.heapreplace(heap, entry)

        def eligible_file(
            path: Path, previous_path: str | None = None, *, for_scan_bound: bool = False,
        ) -> tuple[Path, str] | None:
            try:
                relative = path.relative_to(base)
            except ValueError:
                try:
                    path = path.resolve(strict=True)
                    relative = path.relative_to(base)
                except (OSError, RuntimeError, ValueError):
                    return None
            rel = relative.as_posix()
            forced = any(self._path_control_matches(rel, (pattern,)) for pattern in force_patterns)
            if configured_state_relative and not forced:
                state_prefix = configured_state_relative.as_posix().rstrip("/")
                if rel == state_prefix or rel.startswith(f"{state_prefix}/"):
                    return None
            # An authoritative accelerator excludes nonmatching paths. Explicit
            # force-includes still go through the full path and policy checks.
            if matching_relpaths is not None and rel not in matching_relpaths and not forced:
                return None
            st = None
            if project_settings is None:
                if path.is_symlink() or self._is_ignored_relative_path(relative):
                    return None
            elif for_scan_bound:
                st = self._project_file_stat(
                    base, path, project_settings,
                    force_include=forced,
                    project_path_policy=project_path_policy,
                )
                if st is None:
                    return None
            elif not self._project_file_allowed(
                base, path, project_settings,
                force_include=forced,
                project_path_policy=project_path_policy,
            ):
                return None
            if st is None and callable(extension_check) and not extension_check(path, project_settings=project_settings):
                return None
            # Explicit sorted inventories can contain adjacent duplicates.
            if rel == previous_path:
                return None
            if st is None:
                try:
                    st = path.stat()
                except OSError:
                    return None
            if not stat.S_ISREG(st.st_mode) or st.st_size > self.max_file_bytes:
                return None
            return path, rel

        def scan_bound_error() -> dict[str, Any]:
            error = f"exact repository search exceeds the {file_cap}-file scan bound"
            if ripgrep_timed_out_after is not None:
                error += f". ripgrep reached its {ripgrep_timed_out_after:g}-second limit."
                if ripgrep_timed_out_after == self.ripgrep_timeout:
                    error += " Adjust [search].ripgrep_timeout_seconds to allow more time."
            return {
                "success": False, "root": str(base), "results": [],
                "error": error,
                "status_code": 503, "terminal": True, "retryable": False,
            }

        global_best: list[Any] = []
        total_matches = 0
        scanned = 0
        previous_relative_path: str | None = None
        source_paths = candidates()
        try:
            paths: Iterable[Path] = source_paths
            if matching_relpaths is None:
                probe_limit = 2 * file_cap
                prefix = list(islice(source_paths, probe_limit))
                if len(prefix) == probe_limit:
                    # Use the probe only to prove rejection. Searches that can
                    # proceed still check each path immediately before reading.
                    # Skip the extra policy pass for near-bound raw inventories.
                    seen: set[str] = set()
                    for path in islice(prefix, file_cap + 1):
                        if time.monotonic() >= deadline:
                            raise TimeoutError("exact repository search exceeded 60 seconds")
                        try:
                            checked = eligible_file(path, for_scan_bound=True)
                        except (OSError, RuntimeError, ValueError):
                            break
                        if checked is None or checked[1] in seen:
                            break
                        seen.add(checked[1])
                    else:
                        return scan_bound_error()
                paths = chain(prefix, source_paths)

            for path in paths:
                if time.monotonic() >= deadline:
                    raise TimeoutError("exact repository search exceeded 60 seconds")
                try:
                    eligible = eligible_file(path, previous_relative_path)
                    if eligible is None:
                        continue
                    if scanned >= file_cap:
                        return scan_bound_error()
                    path, rel = eligible
                    scanned += 1
                    previous_relative_path = rel

                    if not path.is_absolute():
                        try:
                            path = path.resolve(strict=True)
                        except (OSError, RuntimeError, ValueError):
                            continue

                    file_hash, lines = self._read_snapshot(
                        path, max_bytes=self.max_file_bytes,
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    return {
                        "success": False, "root": str(base), "results": [],
                        "error": f"exact repository search could not enumerate/read an eligible file ({type(exc).__name__})",
                        "status_code": 503, "terminal": True, "retryable": False,
                    }

                path_lower = rel.lower()
                path_score = sum(1 for term in terms if term in path_lower) * 2
                file_best: list[Any] = []
                file_matched_terms: set[str] = set()
                current_bucket: int | None = None
                bucket_best: dict[str, Any] | None = None

                def finish_bucket() -> None:
                    nonlocal bucket_best
                    if bucket_best is not None:
                        retain(file_best, bucket_best, max(1, self.max_snippets_per_file))
                        bucket_best = None

                for idx, line in enumerate(lines):
                    if idx % 1024 == 0 and time.monotonic() >= deadline:
                        raise TimeoutError("exact repository search exceeded 60 seconds")
                    low = line.lower()
                    matched = [term for term in terms if term in low]
                    if not matched:
                        continue
                    file_matched_terms.update(matched)
                    score = float(
                        len(matched) * 3
                        + path_score
                        + sum(min(low.count(term), 3) * 0.5 for term in matched)
                    )
                    if installation_intent_priority:
                        score += _intent_path_adjustment(query, rel)
                    if phrase and len(phrase) <= 120 and phrase in low:
                        score += 8
                    if declaration_pattern is not None:
                        declaration = declaration_pattern.match(line)
                        if declaration is not None and declaration.group(1).lower() == phrase:
                            score += 6
                    start = max(0, idx - snippet_lines)
                    end = min(len(lines), idx + snippet_lines + 1)
                    hit = {
                        "path": rel, "start_line": start + 1, "end_line": end,
                        "score": round(score, 3),
                        "text": "",
                        "file_sha256": file_hash,
                    }
                    bucket = hit["start_line"] // snippet_lines
                    if current_bucket is not None and bucket != current_bucket:
                        finish_bucket()
                    current_bucket = bucket
                    if bucket_best is None or _WorstFirst(hit).rank < _WorstFirst(bucket_best).rank:
                        bucket_best = hit
                finish_bucket()
                total_matches += len(file_best)
                coverage_bonus = max(0, len(file_matched_terms) - 1) * 2.0
                ranked_file_best = sorted(file_best, key=lambda entry: entry.rank)
                for path_hit_ordinal, entry in enumerate(ranked_file_best):
                    hit = entry.item
                    hit["score"] += coverage_bonus
                    global_hit = {
                        key: hit[key]
                        for key in ("path", "start_line", "end_line", "score", "file_sha256")
                    }
                    if phrase.isidentifier():
                        global_hit["path_hit_ordinal"] = path_hit_ordinal
                    retain(global_best, global_hit, retain_count)
        except TimeoutError as exc:
            return {
                "success": False, "root": str(base), "results": [],
                "error": str(exc), "status_code": 503,
                "terminal": True, "retryable": False,
            }
        except _IncompleteGitInventory as exc:
            return {
                "success": False, "root": str(base), "results": [],
                "error": str(exc), "status_code": 503,
                "terminal": True, "retryable": False,
            }
        except OSError as exc:
            return {
                "success": False, "root": str(base), "results": [],
                "error": f"exact repository search could not enumerate files ({type(exc).__name__})",
                "status_code": 503, "terminal": True, "retryable": False,
            }
        finally:
            source_paths.close()

        ranked = [entry.item for entry in sorted(global_best, key=lambda entry: entry.rank)]
        for reference in ranked:
            reference.pop("path_hit_ordinal", None)
        page_refs = ranked[offset:offset + limit]
        page_by_path: dict[str, list[dict[str, Any]]] = {}
        for reference in page_refs:
            page_by_path.setdefault(str(reference["path"]), []).append(reference)
        materialized: dict[tuple[str, int], dict[str, Any]] = {}
        for relative_path, references in page_by_path.items():
            target = base / relative_path
            try:
                target = target.resolve(strict=True)
                target.relative_to(base)
                digest, lines = self._read_snapshot(target, max_bytes=self.max_file_bytes)
            except (OSError, RuntimeError, ValueError) as exc:
                return {
                    "success": False, "root": str(base), "results": [],
                    "error": f"exact repository search could not materialize a page file ({type(exc).__name__})",
                    "status_code": 503, "terminal": True, "retryable": False,
                }
            if any(reference["file_sha256"] != digest for reference in references):
                return {
                    "success": False, "root": str(base), "results": [],
                    "error": "repository changed while exact search was materializing its page",
                    "status_code": 503, "terminal": True, "retryable": False,
                }
            for reference in references:
                start = max(0, int(reference["start_line"]) - 1)
                end = min(len(lines), int(reference["end_line"]))
                materialized[(relative_path, int(reference["start_line"]))] = {
                    **reference,
                    "text": self._format_search_snippet(lines, start, end),
                }
        page = [
            materialized[(str(reference["path"]), int(reference["start_line"]))]
            for reference in page_refs
        ]
        return {
            "success": True, "root": str(base), "scanned_files": scanned,
            "terms": terms, "results": page, "returned_count": len(page),
            "total_matches": total_matches,
            "has_more": offset + len(page) < total_matches,
            "limit": limit, "offset": offset, "truncated": False,
            "count_exact": True, "engine": "python_exact",
        }

