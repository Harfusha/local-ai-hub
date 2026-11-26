from __future__ import annotations

import subprocess
import time
from typing import Any

from .process_utils import hidden_run_kwargs


RepositoryTools = None


class RepoToolsFilesMixin:
    def git_revert_file(self, root: str, path: str) -> dict[str, Any]:
        """Revert uncommitted changes to a specific file in the working tree."""
        try:
            repo = self._root(root)
        except (ValueError, TypeError) as exc:
            return {"success": False, "error": f"invalid repository root: {exc}"}

        if not path or not isinstance(path, str) or "\0" in path or len(path) > 4096:
            return {"success": False, "error": "invalid file path"}

        target_path = (repo / path).resolve()
        try:
            target_path.relative_to(repo.resolve())
        except ValueError:
            return {"success": False, "error": "path outside repository root"}

        try:
            proc = subprocess.run(
                ["git", "-C", str(repo), "checkout", "HEAD", "--", path],
                capture_output=True, text=True, timeout=5, check=False,
                encoding="utf-8", errors="replace", **hidden_run_kwargs(),
            )
            if proc.returncode != 0:
                proc2 = subprocess.run(
                    ["git", "-C", str(repo), "checkout", "--", path],
                    capture_output=True, text=True, timeout=5, check=False,
                    encoding="utf-8", errors="replace", **hidden_run_kwargs(),
                )
                if proc2.returncode != 0:
                    return {"success": False, "error": proc.stderr.strip() or proc2.stderr.strip() or "git checkout failed"}

            self.invalidate_snapshot(target_path)
            return {"success": True, "path": path.replace("\\", "/"), "reverted": True}
        except Exception as exc:
            return {"success": False, "error": f"git revert failed: {exc}"}

    def find_files(
        self,
        root: str,
        pattern: str = "*",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Find relative file paths matching a glob pattern without reading file contents."""
        import fnmatch

        base = self._root(root)
        try:
            norm_limit = max(1, min(int(limit), 1000))
        except (ValueError, TypeError):
            norm_limit = 100
        try:
            norm_offset = max(0, int(offset))
        except (ValueError, TypeError):
            norm_offset = 0

        clean_pattern = pattern.strip() if isinstance(pattern, str) and pattern.strip() else "*"
        pattern_lower = clean_pattern.lower()
        matched: list[str] = []

        inventory_deadline = time.monotonic() + self.git_files_timeout
        git_inventory = self._git_files(base, deadline=inventory_deadline)
        if git_inventory is not None and not git_inventory.complete:
            return {
                "success": False,
                "error_code": "repository_inventory_incomplete",
                "status_code": 422,
                "error": "file inventory exceeded its path limit; narrow the pattern",
                "terminal": True,
                "retryable": False,
            }
        if git_inventory is not None:
            # Filter the complete Git path inventory before touching the filesystem.
            # Glob misses need no symlink, reparse-point, or file-size checks.
            candidates = git_inventory
            validate_candidate = True
        else:
            with self._git_files_lock:
                git_cooldown = self._git_files_slow_until.get(str(base), 0.0)
            if git_cooldown > time.monotonic():
                return {
                    "success": False,
                    "status_code": 503,
                    "error": "Git file inventory timed out; narrow the pattern or use a repository file index",
                    "terminal": True,
                    "retryable": False,
                }
            inventory_status: dict[str, Any] = {
                "complete": True, "reasons": [], "examples": {},
                "examples_truncated": False, "excluded_link_paths": 0,
            }
            candidates = (
                path for path, _stat in self._iter_files_with_stat(
                    str(base), max_files=self.max_files, inventory_status=inventory_status,
                    inventory_deadline=inventory_deadline,
                )
            )
            validate_candidate = False

        for p in candidates:
            try:
                relative = p.relative_to(base)
                rel = str(relative).replace("\\", "/")
            except ValueError:
                continue
            name = p.name
            if not (fnmatch.fnmatch(rel.lower(), pattern_lower) or fnmatch.fnmatch(name.lower(), pattern_lower)):
                continue
            if validate_candidate:
                if self._is_ignored_relative_path(relative) or not self._inventory_path_safe(base, p):
                    continue
                try:
                    if p.stat().st_size > self.max_file_bytes:
                        continue
                except OSError:
                    continue
            matched.append(rel)

        if git_inventory is None and inventory_status["reasons"]:
            return {
                "success": False,
                "error_code": "repository_inventory_incomplete",
                "status_code": 422,
                "error": "file inventory was incomplete: " + ", ".join(inventory_status["reasons"]),
                "terminal": True,
                "retryable": False,
            }

        total = len(matched)
        sliced = matched[norm_offset : norm_offset + norm_limit]
        has_more = total > (norm_offset + norm_limit)

        return {
            "success": True,
            "root": str(base),
            "pattern": clean_pattern,
            "files": sliced,
            "count": len(sliced),
            "total_matches": total,
            "limit": norm_limit,
            "offset": norm_offset,
            "has_more": has_more,
        }

    def file_info(
        self,
        root: str,
        path: str,
    ) -> dict[str, Any]:
        """Inspect file metadata (existence, size, lines, type, modification time) without full reading."""
        base = self._root(root)
        if not path or not isinstance(path, str):
            return {"success": False, "error": "path is required", "terminal": True, "retryable": False}
        clean_path = path.strip().replace("\\", "/")
        target = (base / clean_path).resolve()
        try:
            target.relative_to(base.resolve())
        except ValueError:
            return {"success": False, "error": "path escapes repository root", "terminal": True, "retryable": False}

        if not target.exists():
            return {
                "success": True,
                "exists": False,
                "path": clean_path,
                "is_file": False,
                "is_dir": False,
                "size_bytes": 0,
                "line_count": 0,
            }

        is_file = target.is_file()
        is_dir = target.is_dir()
        size_bytes = target.stat().st_size if is_file else 0
        line_count = 0
        if is_file and size_bytes <= 10_000_000:
            try:
                with open(target, "rb") as f:
                    line_count = sum(1 for _ in f)
            except Exception:
                line_count = 0

        return {
            "success": True,
            "exists": True,
            "path": clean_path,
            "is_file": is_file,
            "is_dir": is_dir,
            "size_bytes": size_bytes,
            "line_count": line_count,
            "modified": target.stat().st_mtime,
            "mtime": target.stat().st_mtime,
        }

