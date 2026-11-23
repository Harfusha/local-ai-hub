from __future__ import annotations

from collections import Counter
import hashlib
import math
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .budget import estimate_tokens
from .process_utils import hidden_run_kwargs
from .repo_tools_constants import (
    MAX_EXACT_GIT_PATHS,
    _HARD_SEARCH_DIRS,
    _MAX_DIRECTORY_HINT_FILES,
    _MAX_PATH_CONTROLS,
    _UNSET_GIT_INVENTORY,
)
from .retrieval import is_source_context_query, source_context_path_tier


RepositoryTools = None


class RepoToolsPatchMixin:
    def _path_extension_is_searchable(
        self, path: str | os.PathLike[str], *, project_settings: Any | None = None,
    ) -> bool:
        candidate = Path(path)
        name = candidate.name.casefold()
        if name in {".local-ai.toml", ".local-ai.worktree.toml"}:
            return False
        suffix = candidate.suffix.casefold()
        text_extensions, binary_extensions, _forced, _maximum = self._project_settings_values(project_settings)
        if suffix in self.ignore_extensions or any(name.endswith(item) for item in binary_extensions):
            return False
        if any(name.endswith(item) for item in text_extensions):
            return True
        return not (
            self.extensions
            and suffix not in self.extensions
            and name not in self.special_filenames
        )

    def _searchable_context_file(
        self, base: Path, path: Path, *, force_include: bool = False,
        project_settings: Any | None = None,
    ) -> bool:
        try:
            relative = path.relative_to(base)
            parent_parts = tuple(part.casefold() for part in relative.parts[:-1])
            _text, _binary, forced_patterns, _maximum = self._project_settings_values(project_settings)
            policy_forced = self._project_path_matches(relative.as_posix(), forced_patterns)
            if path.is_symlink() or any(part in _HARD_SEARCH_DIRS for part in parent_parts) or (
                not (force_include or policy_forced)
                and any(part in self.ignore_dirs for part in parent_parts)
            ):
                return False
            if not self._path_extension_is_searchable(path, project_settings=project_settings):
                return False
            if not path.is_file():
                return False
            size_bytes = path.stat().st_size
            if size_bytes > self.max_file_bytes:
                return False
            if project_settings is not None and not self._project_file_allowed(
                base, path, project_settings, force_include=force_include,
            ):
                return False
            return True
        except (OSError, ValueError):
            return False

    def _expand_context_directory(
        self, base: Path, relative: str, directory: Path, limit: int,
        *, project_settings: Any | None = None,
    ) -> list[tuple[str, Path]]:
        """Enumerate only one explicitly hinted directory, with bounded Git ignores."""
        if limit <= 0:
            return []
        collected: list[tuple[str, Path]] = []
        try:
            completed = subprocess.run(
                ["git", "-C", str(base), "ls-files", "-co", "--exclude-standard", "-z", "--", relative],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=self.git_files_timeout,
                check=False, **hidden_run_kwargs(),
            )
            if completed.returncode == 0:
                listed = sorted({raw.decode("utf-8", errors="surrogateescape").replace("\\", "/")
                                 for raw in completed.stdout.split(b"\0") if raw})
                for item in listed:
                    if not (item == relative or item.startswith(relative.rstrip("/") + "/")):
                        continue
                    candidate = base.joinpath(*item.split("/"))
                    if self._searchable_context_file(
                        base, candidate, project_settings=project_settings,
                    ):
                        collected.append((item, candidate))
                        if len(collected) >= limit:
                            break
                return collected
        except (OSError, subprocess.TimeoutExpired):
            pass

        for dirpath, dirnames, filenames in os.walk(directory, followlinks=False):
            current = Path(dirpath)
            dirnames[:] = sorted(
                name for name in dirnames
                if name.lower() not in self.ignore_dirs and not (current / name).is_symlink()
            )
            if len(current.relative_to(directory).parts) >= 25:
                dirnames.clear()
            for name in sorted(filenames):
                candidate = current / name
                if not self._searchable_context_file(base, candidate, project_settings=project_settings):
                    continue
                try:
                    rel = candidate.relative_to(base).as_posix()
                except ValueError:
                    continue
                collected.append((rel, candidate))
                if len(collected) >= limit:
                    return collected
        return collected

    def search_paths(
        self, root: str, query: str, paths: list[str], top_k: int = 10,
        context_lines: int | None = None, *, directory_hints: list[str] | tuple[str, ...] = (),
        exclude_paths: list[str] | tuple[str, ...] = (),
        force_include_paths: list[str] | tuple[str, ...] = (),
        max_directory_files: int = _MAX_DIRECTORY_HINT_FILES,
        project_settings: Any | None = None,
        git_inventory: Any = _UNSET_GIT_INVENTORY,
    ) -> dict[str, Any]:
        """Search explicit files and bounded content below caller-supplied directories."""
        from .project_config import path_is_allowed, resolve_project_context
        from .state_paths import configured_state_dir

        base = self._root(root)
        try:
            project_context = resolve_project_context(base, configured_state_dir(self.config))
            if project_context.resolution.error_codes:
                raise ValueError("project_policy_unavailable")
            if project_settings is None:
                project_settings = project_context.settings
        except (OSError, RuntimeError, ValueError):
            return {
                "success": False, "root": str(base), "error": "project_policy_unavailable",
                "results": [], "scanned_files": 0, "targeted": True,
            }
        if git_inventory is _UNSET_GIT_INVENTORY:
            try:
                git_inventory = self._git_files(base, max_files=MAX_EXACT_GIT_PATHS)
            except TypeError:
                git_inventory = self._git_files(base)
        git_metadata = base / ".git"
        valid_git_metadata = (
            (git_metadata.is_dir() and (git_metadata / "HEAD").is_file())
            or git_metadata.is_file()
            or (base / ".gitignore").is_file()
        )
        if git_inventory is None and valid_git_metadata:
            return {
                "success": False, "root": str(base), "error": "git_inventory_unavailable",
                "results": [], "scanned_files": 0, "targeted": True,
            }
        git_paths = None
        git_inventory_complete = True
        if git_inventory is not None:
            git_inventory_complete = getattr(git_inventory, "complete", True)
            git_paths = set()
            for candidate in git_inventory:
                try:
                    git_paths.add(candidate.relative_to(base).as_posix())
                except (OSError, RuntimeError, ValueError):
                    continue
        if not isinstance(paths, (list, tuple)):
            return {"success": False, "error": "paths must be a list"}
        controls: list[tuple[str, tuple[str, ...]]] = []
        for field, values in (("directory_hints", directory_hints), ("exclude_paths", exclude_paths), ("force_include_paths", force_include_paths)):
            if not isinstance(values, (list, tuple)):
                return {"success": False, "error": f"{field} must be a list"}
            if len(values) > _MAX_PATH_CONTROLS:
                return {"success": False, "error": f"{field} exceeds the path limit"}
            try:
                normalized = tuple(
                    self._validated_context_path(base, value, field, reject_symlink=field == "directory_hints")[0]
                    for value in values
                )
            except ValueError as exc:
                return {"success": False, "error": str(exc)}
            controls.append((field, normalized))
        directory_values, excluded_values, forced_values = (item[1] for item in controls)
        normalized_inputs: list[tuple[str, Path]] = []
        for value in paths[:_MAX_PATH_CONTROLS]:
            try:
                normalized_inputs.append(self._validated_context_path(base, value, "paths"))
            except ValueError as exc:
                if "repository-relative" in str(exc) or "symlinks" in str(exc):
                    return {"success": False, "error": str(exc)}
                # Stale in-repository candidates are hints; traversal and symlink
                # attempts are rejected above.
                continue
        normalized_inputs.extend(
            self._validated_context_path(base, value, "force_include_paths") for value in forced_values
        )

        if isinstance(max_directory_files, bool):
            return {"success": False, "error": "max_directory_files must be an integer"}
        try:
            expansion_cap = max(0, min(int(max_directory_files), _MAX_DIRECTORY_HINT_FILES))
        except (TypeError, ValueError, OverflowError):
            return {"success": False, "error": "max_directory_files must be an integer"}
        if isinstance(max_directory_files, float) and max_directory_files != int(max_directory_files):
            return {"success": False, "error": "max_directory_files must be an integer"}

        hinted_directories = {value.casefold() for value in directory_values}
        targets: list[tuple[str, Path]] = []
        seen_targets: set[str] = set()
        expanded = 0
        for rel, candidate in normalized_inputs:
            key = rel.casefold()
            if key in seen_targets:
                continue
            seen_targets.add(key)
            if candidate.is_symlink():
                return {"success": False, "error": "paths cannot traverse symlinks"}
            if candidate.is_file():
                forced = self._path_control_matches(rel, forced_values)
                if not self._path_control_matches(rel, excluded_values) and self._searchable_context_file(
                    base, candidate, force_include=forced, project_settings=project_settings,
                ):
                    targets.append((rel, candidate))
            elif candidate.is_dir() and key in hinted_directories:
                children = self._expand_context_directory(
                    base, rel, candidate, expansion_cap - expanded,
                    project_settings=project_settings,
                )
                for child_rel, child_path in children:
                    expanded += 1
                    forced = self._path_control_matches(child_rel, forced_values)
                    if self._path_control_matches(child_rel, excluded_values):
                        continue
                    child_key = child_rel.casefold()
                    if child_key not in seen_targets:
                        targets.append((child_rel, child_path))
                        seen_targets.add(child_key)
                if expanded >= expansion_cap:
                    break
        terms = self._terms(query)
        phrase = query.strip().lower()
        effective_snippet_lines = max(1, min(int(context_lines), 40)) if context_lines is not None else self.snippet_lines
        hits: list[dict[str, Any]] = []
        scanned = 0
        seen_paths: set[str] = set()
        path_rank = {rel: rank for rank, (rel, _path) in enumerate(targets)}
        for rel, path in targets:
            if rel in seen_paths:
                continue
            seen_paths.add(rel)
            path = (base / rel).resolve(strict=False)
            try:
                relative = path.relative_to(base)
            except ValueError:
                continue
            forced = self._path_control_matches(rel, forced_values)
            if self._is_ignored_relative_path(relative) and not forced:
                continue
            if not path.is_file():
                continue
            if (
                git_paths is not None
                and git_inventory_complete
                and rel not in git_paths
                and not forced
                and not path_is_allowed(
                    base, rel, project_settings, phase="search", soft_ignored=True,
                )
            ):
                continue
            scanned += 1
            try:
                file_hash, lines = self._read_snapshot(path)
            except Exception:
                continue
            path_lower = rel.lower()
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
                start = max(0, idx - effective_snippet_lines)
                end = min(len(lines), idx + effective_snippet_lines + 1)
                snippet = self._format_search_snippet(lines, start, end)
                hits.append({
                    "path": rel, "start_line": start + 1, "end_line": end,
                    "score": round(score, 3), "text": snippet, "file_sha256": file_hash,
                })
        hits.sort(
            key=lambda x: (
                -x["score"],
                path_rank.get(x["path"], len(path_rank)),
                x["path"],
                x["start_line"],
            )
        )
        dedup: list[dict[str, Any]] = []
        per_file: Counter[str] = Counter()
        for hit in hits:
            if per_file[hit["path"]] >= self.max_snippets_per_file:
                continue
            per_file[hit["path"]] += 1
            dedup.append(hit)
            if len(dedup) >= max(1, int(top_k)):
                break
        candidate_pool = hits[: max(len(dedup), max(1, int(top_k)) * 4)]
        candidate_tokens = sum(estimate_tokens(str(item.get("text", ""))) for item in candidate_pool)
        result = {"success": True, "root": str(base), "scanned_files": scanned, "terms": terms, "results": dedup, "targeted": True}
        if candidate_tokens:
            result["candidate_context_tokens_est"] = candidate_tokens
        return result

    def context_pack_paths(
        self, root: str, query: str, paths: list[str], max_tokens: int = 2600, top_k: int = 10, *,
        directory_hints: list[str] | tuple[str, ...] = (),
        exclude_paths: list[str] | tuple[str, ...] = (),
        force_include_paths: list[str] | tuple[str, ...] = (),
        priority_paths: list[str] | tuple[str, ...] = (),
        max_directory_files: int = _MAX_DIRECTORY_HINT_FILES,
    ) -> dict[str, Any]:
        source_query = is_source_context_query(query)
        requested_top_k = max(1, int(top_k))
        search_top_k = max(requested_top_k, min(64, requested_top_k * 4)) if source_query else top_k
        search = self.search_paths(
            root, query, paths, top_k=search_top_k, directory_hints=directory_hints,
            exclude_paths=exclude_paths, force_include_paths=force_include_paths,
            max_directory_files=max_directory_files,
        )
        if not search.get("success"):
            return search
        if source_query:
            results = search.get("results", [])
            input_rank = {str(path).replace("\\", "/").casefold(): rank for rank, path in enumerate(paths)}
            protected = {
                str(path).replace("\\", "/").casefold()
                for path in (*priority_paths, *force_include_paths)
            }
            force_patterns = tuple(str(path) for path in force_include_paths)

            def source_result_rank(item: dict[str, Any]) -> tuple[int, float, int, str, int]:
                raw_path = str(item.get("path", ""))
                normalized_path = raw_path.replace("\\", "/").casefold()
                explicitly_prioritized = normalized_path in protected or self._path_control_matches(
                    raw_path, force_patterns,
                )
                return (
                    0 if explicitly_prioritized else 1 + source_context_path_tier(raw_path),
                    -float(item.get("score", 0.0)),
                    input_rank.get(normalized_path, len(input_rank)),
                    raw_path,
                    int(item.get("start_line", 0)),
                )

            results.sort(key=source_result_rank)
            search["results"] = results[:requested_top_k]
        return self._pack_ranked_context(search, query, max_tokens, targeted=True)

    def _pack_ranked_context(
        self, search: dict[str, Any], query: str, max_tokens: int, *, targeted: bool = False,
    ) -> dict[str, Any]:
        """Render ranked evidence once; keep snippets whole and provenance aligned.

        ``max_tokens`` limits context text. HTTP/MCP callers enforce their separate
        serialized-envelope budget at the transport boundary.
        """
        pieces: list[str] = []
        evidence: list[dict[str, Any]] = []
        candidate_tokens = 0
        context_bytes = 0
        results = search.get("results", [])
        token_limit = max(0, int(max_tokens)) if results else 0
        for item in results:
            header = f"--- {item['path']}:{item['start_line']}-{item['end_line']} score={item['score']} ---\n"
            candidate_tokens += estimate_tokens(header + item["text"] + "\n")
        for item in results:
            header = f"--- {item['path']}:{item['start_line']}-{item['end_line']} score={item['score']} ---\n"
            piece = header + item["text"] + "\n"
            trial_bytes = context_bytes + (1 if pieces else 0) + len(piece.encode("utf-8"))
            if max(1, math.ceil(trial_bytes / 3.4)) > token_limit:
                # Ranked order is authoritative; lower-ranked short snippets must
                # not jump ahead of a higher-ranked excerpt that did not fit.
                break
            pieces.append(piece)
            context_bytes = trial_bytes
            ev = {k: item[k] for k in ("path", "start_line", "end_line", "score", "file_sha256")}
            ev["raw"] = item.get("text", "")
            evidence.append(ev)
        packed = "\n".join(pieces)
        result = {
            "success": True, "root": search["root"], "query": query, "context": packed,
            "evidence": evidence, "estimated_tokens": estimate_tokens(packed),
            "original_estimated_tokens": max(candidate_tokens, estimate_tokens(packed)),
            "scanned_files": search.get("scanned_files", 0),
        }
        if targeted:
            result["targeted"] = True
        return result

    def file_inventory(self, root: str, include_hashes: bool = True) -> dict[str, Any]:
        """Return a deterministic file inventory backed by the shared snapshot cache.

        Preprocessing uses this as its durable content-addressed source of truth.
        """
        base = self._root(root)
        items: list[dict[str, Any]] = []
        total_bytes = 0
        for path, file_stat in self._iter_files_with_stat(str(base)):
            try:
                rel = str(path.relative_to(base)).replace("\\", "/")
                item: dict[str, Any] = {
                    "path": rel, "size": int(file_stat.st_size), "mtime_ns": int(file_stat.st_mtime_ns),
                    "extension": path.suffix.lower(),
                }
                if include_hashes:
                    digest, _lines = self._read_snapshot(path, stat=file_stat)
                    item["sha256"] = digest
                items.append(item)
                total_bytes += int(file_stat.st_size)
            except Exception:
                continue
        items.sort(key=lambda x: x["path"])
        digest = hashlib.sha256(
            "\n".join(f"{x['path']}:{x.get('sha256','')}:{x['size']}" for x in items).encode("utf-8")
        ).hexdigest()
        return {"success": True, "root": str(base), "files": items, "file_count": len(items), "total_bytes": total_bytes, "inventory_sha256": digest}

    def file_slice(self, root: str, path: str, start_line: int = 1, end_line: int = 240, max_chars: int = 16000) -> dict[str, Any]:
        """Read an exact bounded source slice through the snapshot cache."""
        base = self._root(root)
        candidate = (base / path).resolve(strict=False)
        try:
            candidate.relative_to(base)
        except ValueError:
            return {"success": False, "error": "path escapes repository root"}
        if not candidate.is_file():
            return {"success": False, "error": f"file not found: {path}"}
        try:
            digest, lines = self._read_snapshot(candidate)
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        rel = str(candidate.relative_to(base)).replace("\\", "/")
        if not lines:
            return {
                "success": True, "root": str(base), "path": rel, "start_line": 1, "end_line": 0,
                "text": "", "file_sha256": digest, "truncated": False,
            }
        start = max(1, min(int(start_line), len(lines)))
        end = max(start, min(int(end_line), len(lines)))
        rendered = "\n".join(f"{n}: {lines[n-1]}" for n in range(start, end + 1))
        truncated = len(rendered) > max_chars
        if truncated:
            rendered = rendered[:max_chars] + "\n[…slice truncated…]"
        return {
            "success": True, "root": str(base), "path": rel, "start_line": start, "end_line": end,
            "text": rendered, "file_sha256": digest, "truncated": truncated,
        }

    def context_pack(self, root: str, query: str, max_tokens: int = 4500, top_k: int = 14) -> dict[str, Any]:
        source_query = is_source_context_query(query)
        requested_top_k = max(1, int(top_k))
        search_top_k = max(requested_top_k, min(64, requested_top_k * 4)) if source_query else top_k
        search = self.search(root, query, limit=search_top_k)
        if not search.get("success"):
            return search
        if source_query:
            results = search.get("results", [])
            results.sort(key=lambda item: (
                source_context_path_tier(str(item.get("path", ""))),
                -float(item.get("score", 0.0)),
                str(item.get("path", "")),
                int(item.get("start_line", 0)),
            ))
            search["results"] = results[:requested_top_k]
        return self._pack_ranked_context(search, query, max_tokens)

    def apply_patch(
        self,
        root: str,
        path: str,
        old_code: str,
        new_code: str,
    ) -> dict[str, Any]:
        """Apply a patch with CRLF/LF normalization and trailing-whitespace tolerance."""
        if not isinstance(path, str) or not path.strip():
            return {"success": False, "error": "path must be a non-empty string", "status_code": 400}
        if not isinstance(old_code, str):
            return {"success": False, "error": "old_code must be a string", "status_code": 400}
        if not isinstance(new_code, str):
            return {"success": False, "error": "new_code must be a string", "status_code": 400}

        base = self._root(root)
        resolved = self._resolve_under_base(base, path)
        if resolved is None:
            return {"success": False, "error": f"Path '{path}' escapes repository root", "status_code": 403}
        target_path, relative_path = resolved
        if not target_path.is_file():
            return {"success": False, "error": f"File '{path}' does not exist", "status_code": 404}

        try:
            content_bytes = target_path.read_bytes()
        except OSError as exc:
            return {"success": False, "error": f"Failed to read '{path}': {exc}", "status_code": 500}

        encoding = "utf-8"
        try:
            content = content_bytes.decode(encoding)
        except UnicodeDecodeError:
            encoding = "latin-1"
            content = content_bytes.decode(encoding)

        has_crlf = "\r\n" in content
        newline = "\r\n" if has_crlf else "\n"

        matched_strategy = None
        new_content = None

        # Strategy 1: Exact match
        count = content.count(old_code)
        if count == 1:
            new_content = content.replace(old_code, new_code, 1)
            matched_strategy = "exact"
        elif count > 1:
            return {
                "success": False,
                "error": f"Target old_code found {count} times; provide more surrounding context",
                "status_code": 400,
            }

        # Strategy 2: Line-ending normalized match (CRLF vs LF)
        if matched_strategy is None:
            norm_content = content.replace("\r\n", "\n")
            norm_old = old_code.replace("\r\n", "\n")
            norm_new = new_code.replace("\r\n", "\n")
            norm_count = norm_content.count(norm_old)
            if norm_count == 1:
                replaced_norm = norm_content.replace(norm_old, norm_new, 1)
                new_content = replaced_norm.replace("\n", "\r\n") if has_crlf else replaced_norm
                matched_strategy = "normalized_line_endings"
            elif norm_count > 1:
                return {
                    "success": False,
                    "error": f"Target old_code found {norm_count} times; provide more surrounding context",
                    "status_code": 400,
                }

        # Strategy 3: Whitespace-tolerant line window matching
        if matched_strategy is None:
            content_lines = content.splitlines(keepends=True)
            old_lines = old_code.splitlines(keepends=False)
            new_lines = new_code.splitlines(keepends=False)

            if old_lines:
                matches = []
                window_size = len(old_lines)
                for i in range(len(content_lines) - window_size + 1):
                    window = [cl.rstrip("\r\n").rstrip() for cl in content_lines[i : i + window_size]]
                    target_stripped = [ol.rstrip() for ol in old_lines]
                    if window == target_stripped:
                        matches.append(i)

                if len(matches) == 1:
                    match_idx = matches[0]
                    formatted_new = [nl + newline for nl in new_lines]
                    if not content_lines[match_idx + window_size - 1].endswith(("\n", "\r")):
                        if formatted_new:
                            formatted_new[-1] = formatted_new[-1].rstrip("\r\n")
                    new_lines_slice = content_lines[:match_idx] + formatted_new + content_lines[match_idx + window_size:]
                    new_content = "".join(new_lines_slice)
                    matched_strategy = "whitespace_tolerant"
                elif len(matches) > 1:
                    return {
                        "success": False,
                        "error": f"Target old_code found {len(matches)} times with whitespace tolerance; provide more surrounding context",
                        "status_code": 400,
                    }

        if matched_strategy is None:
            return {
                "success": False,
                "error": "Target old_code was not found in the file (tried exact, line-ending normalized, and whitespace-tolerant)",
                "status_code": 400,
            }

        try:
            target_path.write_bytes(new_content.encode(encoding))
            self.invalidate_snapshot(target_path)
        except OSError as exc:
            return {"success": False, "error": f"Failed to write '{path}': {exc}", "status_code": 500}

        return {
            "success": True,
            "path": str(relative_path).replace("\\", "/"),
            "matched_strategy": matched_strategy,
            "old_bytes": len(content_bytes),
            "new_bytes": len(new_content.encode(encoding)),
        }

    def git_status(self, root: str) -> dict[str, Any]:
        """Return structured Git status for the given repository root."""
        try:
            repo = self._root(root)
        except (ValueError, TypeError) as exc:
            return {"success": False, "error": f"invalid repository root: {exc}", "dirty": False}

        if shutil.which("git") is None:
            return {"success": False, "error": "git unavailable", "dirty": False}

        try:
            probe = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True, timeout=3, check=False,
                encoding="utf-8", errors="replace", **hidden_run_kwargs(),
            )
            if probe.returncode != 0 or probe.stdout.strip().lower() != "true":
                return {"success": False, "error": "not a git repository", "dirty": False}

            branch_proc = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=3, check=False,
                encoding="utf-8", errors="replace", **hidden_run_kwargs(),
            )
            branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else ""

            head_proc = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=3, check=False,
                encoding="utf-8", errors="replace", **hidden_run_kwargs(),
            )
            head = head_proc.stdout.strip() if head_proc.returncode == 0 else ""

            status_output = self._git_snapshot_run(repo, "status", "--porcelain=v2", "--untracked-files=all", "-z")
            entries = self._git_parse_status(status_output)

            changed: list[str] = []
            staged: list[str] = []
            untracked: list[str] = []

            for path_str, x, y, state, _ in entries:
                if state == "untracked":
                    untracked.append(path_str)
                else:
                    if x != ".":
                        staged.append(path_str)
                    if y != ".":
                        changed.append(path_str)

            all_modified = list(dict.fromkeys(changed + [p for p, x, y, s, _ in entries if s != "untracked"]))

            return {
                "success": True,
                "root": str(repo),
                "head": head,
                "branch": branch,
                "dirty": bool(entries),
                "changed_paths": all_modified,
                "staged_paths": list(dict.fromkeys(staged)),
                "untracked_paths": untracked,
                "count": len(entries),
            }
        except Exception as exc:
            return {"success": False, "error": f"git status failed: {exc}", "root": str(repo), "dirty": False}

