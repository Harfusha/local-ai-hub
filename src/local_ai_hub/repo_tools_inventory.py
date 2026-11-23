from __future__ import annotations

from collections import OrderedDict
import hashlib
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import subprocess
import threading
import time
from typing import Any, Iterable

from .process_utils import canonical_root, hidden_run_kwargs, popen_managed, terminate_tree
from .repo_tools_constants import MAX_EXACT_GIT_PATH_BYTES, MAX_EXACT_GIT_PATHS
from .repo_tools_models import (
    FileTooLargeError,
    GitFileInventory,
    GitSnapshot,
    _BoundedSortedPaths,
)
from .repo_tools_path_helpers import (
    _record_security_inventory_issue,
    is_root_archive_path,
)


RepositoryTools = None


class RepoToolsInventoryMixin:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        rag = config.get("rag", {})
        search = config.get("search", {})
        self.extensions = {str(x).lower() for x in rag.get("extensions", [])}
        self.special_filenames = {str(x).lower() for x in search.get("special_filenames", [
            "dockerfile", "containerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
            "makefile", "gnumakefile", "justfile", "gemfile", "pipfile", ".env", ".env.example", ".env.sample",
            ".gitlab-ci.yml", ".gitlab-ci.yaml", "azure-pipelines.yml", "azure-pipelines.yaml",
            "pytest.ini", "tox.ini", "phpunit.xml", "phpunit.xml.dist", "phpstan.neon", "phpstan.neon.dist",
        ])}
        default_ignore_dirs = {
            ".git", ".svn", ".hg", ".idea", ".vscode", ".venv", "venv", "tool-envs", "node_modules",
            "vendor", "dist", "build", "bin", "obj", "coverage", ".next", ".cache",
            "library", "temp", "logs", "usersettings", "packagestore", "memorycaptures", "builds",
            ".serena", ".local-ai-hub", ".codegraphcontext", ".handoff",
            ".t03-main-preflight-overlay", ".system_generated",
            ".pytest_cache", ".mypy_cache", ".ruff_cache",
        }
        self.ignore_dirs = {str(name).lower() for name in rag.get("ignore_dirs", [])} | default_ignore_dirs
        self.ignore_extensions = {str(x).lower() for x in rag.get("ignore_extensions", [
            ".meta", ".asset", ".prefab", ".mat", ".unity", ".anim", ".controller",
            ".overridecontroller", ".physicmaterial", ".physicsmaterial2d", ".guiskin",
            ".mask", ".cubemap", ".flare", ".fontsettings", ".terrainlayer",
            ".mesh", ".fbx", ".obj", ".blend", ".tga", ".psd", ".png", ".jpg", ".jpeg",
            ".wav", ".mp3", ".ogg", ".shadergraph", ".shadersubgraph"
        ])}
        self.max_file_bytes = int(rag.get("max_file_bytes", 2_000_000))
        self.max_files = int(search.get("max_files", 8000))
        self.python_fallback_max_files = max(
            1, min(max(1, self.max_files), int(search.get("python_fallback_max_files", self.max_files)))
        )
        self.max_hits = int(search.get("max_hits", 80))
        self.max_search_terms = max(4, int(search.get("max_terms", 12)))
        self.snippet_lines = int(search.get("snippet_lines", 5))
        self.max_snippets_per_file = int(search.get("max_snippets_per_file", 3))
        self.prefer_git = bool(search.get("prefer_git_files", True))
        self.use_ripgrep = bool(search.get("use_ripgrep_if_available", True))
        self.ripgrep_timeout = max(0.5, float(search.get("ripgrep_timeout_seconds", 15.0)))
        self.ripgrep_slow_cooldown = max(1.0, float(search.get("ripgrep_slow_cooldown_seconds", 15.0)))
        self.git_grep_timeout = max(0.5, float(search.get("git_grep_timeout_seconds", min(10.0, self.ripgrep_timeout))))
        self.git_files_timeout = max(0.5, float(search.get("git_files_timeout_seconds", 15.0)))
        self.git_files_cache_ttl = max(0.0, float(search.get("git_files_cache_ttl_seconds", 3.0)))
        self.git_files_slow_cooldown = max(1.0, float(search.get("git_files_slow_cooldown_seconds", 15.0)))
        self.use_git_grep = bool(search.get("use_git_grep_fallback", True))
        self._rg = shutil.which("rg") if self.use_ripgrep else None
        self._git_files_lock = threading.RLock()
        self._git_files_cache: dict[str, tuple[float, tuple[str, ...]]] = {}
        self._git_blob_cache: dict[str, tuple[float, dict[str, str]]] = {}
        self._git_snapshot_cache: dict[str, tuple[float, GitSnapshot]] = {}
        self._git_snapshot_slow_until: dict[str, float] = {}
        self._git_files_slow_until: dict[str, float] = {}
        self._git_files_flights: dict[str, threading.Lock] = {}
        self._git_grep_slow_until: dict[str, float] = {}
        self._ripgrep_slow_until: dict[str, float] = {}
        self._git_stats = {"file_list_hits": 0, "file_list_misses": 0, "file_list_timeouts": 0, "file_list_coalesced": 0, "grep_timeouts": 0, "grep_cooldown_skips": 0, "ripgrep_timeouts": 0, "ripgrep_cooldown_skips": 0, "python_search_fallbacks": 0, "snapshot_hits": 0, "snapshot_misses": 0, "snapshot_degraded": 0}
        snap = config.get("snapshot_cache", {})
        self.snapshot_max_entries = max(64, int(snap.get("max_entries", max(4096, self.max_files))))
        self.snapshot_max_bytes = max(8_000_000, int(snap.get("max_bytes", 256_000_000)))
        self._snapshot_lock = threading.RLock()
        self._snapshots: OrderedDict[str, tuple[int, int, int, int, str, list[str], int]] = OrderedDict()
        self._hash_only_cache: OrderedDict[str, tuple[int, int, int, int, str, bool]] = OrderedDict()
        self._hash_only_max_entries = 8192
        self._snapshot_bytes = 0
        self.snapshot_hits = 0
        self.snapshot_misses = 0
        self.snapshot_verified_rehashes = 0
        self._resolved_paths_lock = threading.Lock()
        self._resolved_paths: OrderedDict[tuple[str, str], tuple[Path, Path] | None] = OrderedDict()
        self._resolved_paths_max = 8192

    def _resolve_under_base(self, base: Path, raw: str | Path) -> tuple[Path, Path] | None:
        raw_str = str(raw)
        key = (str(base), raw_str)
        with self._resolved_paths_lock:
            if key in self._resolved_paths:
                self._resolved_paths.move_to_end(key)
                return self._resolved_paths[key]
        try:
            p = Path(raw_str)
            resolved = (base / p).resolve(strict=False) if not p.is_absolute() else p.resolve(strict=False)
            relative = resolved.relative_to(base)
            res: tuple[Path, Path] | None = (resolved, relative)
        except (OSError, RuntimeError, ValueError):
            res = None
        with self._resolved_paths_lock:
            if len(self._resolved_paths) >= self._resolved_paths_max:
                self._resolved_paths.popitem(last=False)
            self._resolved_paths[key] = res
        return res

    @staticmethod
    def _root(root: str) -> Path:
        canon = canonical_root(root)
        path = Path(canon)
        if not path.is_dir():
            raise ValueError(f"root directory does not exist: {path}")
        return path

    def _git_files(self, root: Path, *, max_files: int | None = None, force: bool = False,
                   pathspecs: tuple[str, ...] = (),
                   inventory_status: dict[str, Any] | None = None,
                   deadline: float | None = None) -> GitFileInventory | None:
        """Stream a bounded tracked + untracked Git inventory.

        At most ``max_files`` paths are retained (the default hard bound is
        ``MAX_EXACT_GIT_PATHS``); ``complete=False`` marks a further eligible path.
        The NUL-delimited subprocess output is consumed in fixed-size chunks.
        """
        if not self.prefer_git or not (root / ".git").exists():
            return None
        limit = self.max_files if max_files is None else max(0, int(max_files))
        if (not isinstance(pathspecs, tuple) or len(pathspecs) > 64 or any(
            type(value) is not str or not value or "\x00" in value
            or value.startswith(("/", "\\")) or Path(value).is_absolute() or PureWindowsPath(value).drive
            or any(part in {".", ".."} for part in value.replace("\\", "/").split("/"))
            for value in pathspecs
        )):
            return None
        key = str(root)
        if pathspecs:
            key += "\0hints"
        now = time.monotonic()
        root_resolved = root.resolve(strict=False)
        with self._git_files_lock:
            cached = self._git_files_cache.get(key)
            if not pathspecs and not force and cached and (self.git_files_cache_ttl <= 0 or now - cached[0] <= self.git_files_cache_ttl):
                self._git_stats["file_list_hits"] += 1
                return GitFileInventory(
                    [(root_resolved / rel) for rel in cached[1][:limit]],
                    complete=len(cached[1]) <= limit,
                )
            if now < self._git_files_slow_until.get(key, 0.0):
                return None
            flight = self._git_files_flights.setdefault(key, threading.Lock())

        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        if remaining is not None and remaining <= 0:
            return None
        wait_timeout = self.git_files_timeout + 0.25 if remaining is None else min(self.git_files_timeout + 0.25, remaining)
        if not flight.acquire(timeout=wait_timeout):
            with self._git_files_lock:
                self._git_stats["file_list_coalesced"] += 1
            return None
        process = None
        timer = None
        timed_out = threading.Event()
        try:
            now = time.monotonic()
            with self._git_files_lock:
                cached = self._git_files_cache.get(key)
                if not pathspecs and not force and cached and (self.git_files_cache_ttl <= 0 or now - cached[0] <= self.git_files_cache_ttl):
                    self._git_stats["file_list_hits"] += 1
                    self._git_stats["file_list_coalesced"] += 1
                    return GitFileInventory(
                        [(root_resolved / rel) for rel in cached[1][:limit]],
                        complete=len(cached[1]) <= limit,
                    )
                if now < self._git_files_slow_until.get(key, 0.0):
                    return None
                self._git_stats["file_list_misses"] += 1
            command = ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"]
            if pathspecs:
                command.extend(["--", *(f":(literal){path}" for path in pathspecs)])
            process = popen_managed(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                **hidden_run_kwargs(text=False),
            )

            def kill_on_timeout() -> None:
                if process is not None and process.poll() is None:
                    timed_out.set()
                    try:
                        terminate_tree(process.pid, grace_seconds=0.1, process_handle=process)
                    except (OSError, ValueError):
                        pass

            git_timeout = self.git_files_timeout if deadline is None else min(self.git_files_timeout, max(0.0, deadline - time.monotonic()))
            if git_timeout <= 0:
                return None
            inventory_deadline = time.monotonic() + git_timeout
            timer = threading.Timer(git_timeout, kill_on_timeout)
            timer.daemon = True
            timer.start()
            inventory_paths = _BoundedSortedPaths(limit)
            pending = bytearray()
            scanned_paths = 0
            scanned_bytes = 0
            scan_capped = False

            def consider(raw: bytes) -> bool:
                nonlocal scanned_paths, scanned_bytes, scan_capped
                if deadline is not None and time.monotonic() >= deadline:
                    scan_capped = True
                    _record_security_inventory_issue(inventory_status, root, "time_limit")
                    return False
                if not raw:
                    return True
                scanned_paths += 1
                scanned_bytes += len(raw) + 1
                if scanned_paths > MAX_EXACT_GIT_PATHS or scanned_bytes > MAX_EXACT_GIT_PATH_BYTES:
                    scan_capped = True
                    return False
                rel = raw.decode("utf-8", errors="surrogateescape").replace("\\", "/")
                if ".." in rel.split("/") or rel.startswith("/"):
                    candidate = (root / rel).resolve(strict=False)
                    try:
                        candidate.relative_to(root)
                    except ValueError:
                        return True
                if max_files is not None:
                    relative = Path(rel)
                    if any(part.lower() in self.ignore_dirs for part in relative.parts[:-1]):
                        return True
                    if relative.suffix.lower() in self.ignore_extensions:
                        return True
                    if self.extensions and relative.suffix.lower() not in self.extensions and relative.name.lower() not in self.special_filenames:
                        return True
                    if inventory_status is not None and not self._inventory_path_safe(root, root / rel):
                        try:
                            intentional_link = self._inventory_path_has_link(root, root / rel)
                            if intentional_link:
                                inventory_status["excluded_link_paths"] = int(inventory_status.get("excluded_link_paths", 0)) + 1
                            else:
                                _record_security_inventory_issue(inventory_status, root, "unavailable_path", root / rel)
                        except FileNotFoundError:
                            pass
                        except (OSError, ValueError):
                            _record_security_inventory_issue(inventory_status, root, "inventory_error", root / rel)
                        return True
                    try:
                        if (root / rel).stat().st_size > self.max_file_bytes:
                            _record_security_inventory_issue(inventory_status, root, "oversized_file", root / rel)
                            return True
                    except FileNotFoundError:
                        return True
                    except OSError:
                        _record_security_inventory_issue(inventory_status, root, "inventory_error", root / rel)
                        return True
                inventory_paths.add(rel)
                return True

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
                            raise OSError("Git path exceeded bounded inventory buffer")
                        break
                    raw = bytes(pending[:separator])
                    del pending[:separator + 1]
                    if not consider(raw):
                        break
                if scan_capped:
                    break
            if pending and not scan_capped:
                consider(bytes(pending))
            rels, within_limit = inventory_paths.finish()
            if scan_capped:
                try:
                    terminate_tree(process.pid, grace_seconds=0.1, process_handle=process)
                except (OSError, ValueError):
                    pass
            try:
                return_code = process.wait(timeout=max(0.001, inventory_deadline - time.monotonic()))
            except TypeError:
                return None
            if timed_out.is_set() or (return_code != 0 and not scan_capped):
                if timed_out.is_set():
                    with self._git_files_lock:
                        self._git_stats["file_list_timeouts"] += 1
                        self._git_files_slow_until[key] = time.monotonic() + self.git_files_slow_cooldown
                return None
            complete = within_limit and not scan_capped
            inventory = GitFileInventory(
                [(root_resolved / rel) for rel in rels], complete=complete,
            )
            with self._git_files_lock:
                if inventory_status is None and not pathspecs and (max_files is None or max_files >= self.max_files) and complete:
                    self._git_files_cache[key] = (time.monotonic(), tuple(rels))
                    if len(self._git_files_cache) > 64:
                        for cache_key in list(self._git_files_cache.keys())[:-32]:
                            self._git_files_cache.pop(cache_key, None)
                self._git_files_slow_until.pop(key, None)
            return inventory
        except (OSError, subprocess.TimeoutExpired) as exc:
            with self._git_files_lock:
                if isinstance(exc, subprocess.TimeoutExpired):
                    self._git_stats["file_list_timeouts"] += 1
                self._git_files_slow_until[key] = time.monotonic() + self.git_files_slow_cooldown
            return None
        finally:
            if timer is not None:
                timer.cancel()
            if process is not None and process.poll() is None:
                try:
                    terminate_tree(process.pid, grace_seconds=0.1, process_handle=process)
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired, TypeError):
                    pass
            if process is not None and process.stdout is not None:
                try:
                    process.stdout.close()
                except OSError:
                    pass
            flight.release()

    def iter_files(
        self, root: str, max_depth: int = 25, *, project_settings: Any | None = None,
        max_files: int | None = None,
    ) -> Iterable[Path]:
        for path, _stat in self._iter_files_with_stat(
            root, max_depth=max_depth, project_settings=project_settings, max_files=max_files,
        ):
            yield path

    def security_inventory(self, root: str, *, deadline: float | None = None) -> tuple[list[Path], dict[str, Any]]:
        """Return a bounded audit inventory together with explicit coverage."""
        status: dict[str, Any] = {"complete": True, "reasons": [], "examples": {}, "examples_truncated": False, "excluded_link_paths": 0}
        bound = max(0, self.max_files)
        entries = list(self._iter_files_with_stat(
            root, max_files=bound + 1, inventory_status=status, inventory_deadline=deadline,
        ))
        if len(entries) > bound:
            _record_security_inventory_issue(status, self._root(root), "file_limit", entries[bound][0])
            entries = entries[:bound]
        status["_identity"] = {
            str(path): (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            for path, info in entries
        }
        status["reasons"] = list(dict.fromkeys(status["reasons"]))
        return [path for path, _ in entries], status

    def _is_ignored_relative_path(self, relative: Path) -> bool:
        if is_root_archive_path(relative):
            return True
        if any(part.lower() in self.ignore_dirs for part in relative.parts[:-1]):
            return True
        if relative.suffix.lower() in self.ignore_extensions:
            return True
        return bool(
            self.extensions
            and relative.suffix.lower() not in self.extensions
            and relative.name.lower() not in self.special_filenames
        )

    @staticmethod
    def _inventory_path_has_link(base: Path, path: Path) -> bool:
        relative = path.relative_to(base)
        if any(part in {".", ".."} for part in relative.parts):
            raise ValueError("invalid inventory path")
        current = base
        for part in relative.parts:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                return True
        return False

    @staticmethod
    def _resolve_inventory_path_safe(
        base: Path,
        path: Path,
        *,
        resolved_base: Path | None = None,
    ) -> tuple[Path, Path] | None:
        """Resolve an inventory path after rejecting links and reparse points."""
        resolved = RepositoryTools._resolve_inventory_path_safe_with_stat(
            base, path, resolved_base=resolved_base,
        )
        if resolved is None:
            return None
        return resolved[0], resolved[1]

    @staticmethod
    def _resolve_inventory_path_safe_with_stat(
        base: Path,
        path: Path,
        *,
        resolved_base: Path | None = None,
    ) -> tuple[Path, Path, os.stat_result] | None:
        """Return the safe resolved path and final lstat metadata."""
        try:
            relative = path.relative_to(base)
            if any(part in {".", ".."} for part in relative.parts):
                return None
            current = base
            info: os.stat_result | None = None
            for part in relative.parts:
                current = current / part
                info = current.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                    return None
            if info is None:
                return None
            if resolved_base is None:
                resolved_base = base.resolve(strict=True)
            elif not resolved_base.is_absolute() or (
                os.fspath(base) != os.fspath(resolved_base) and not base.samefile(resolved_base)
            ):
                return None
            resolved_path = resolved_base / relative
            resolved_path.relative_to(resolved_base)
            return resolved_base, resolved_path, info
        except (OSError, RuntimeError, ValueError):
            return None

    @staticmethod
    def _inventory_path_safe(base: Path, path: Path) -> bool:
        """Reject links and Windows reparse points before traversal or stat."""
        return RepositoryTools._resolve_inventory_path_safe(base, path) is not None

    def _iter_files_with_stat(
        self, root: str, max_depth: int = 25, *, project_settings: Any | None = None,
        max_files: int | None = None, inventory_status: dict[str, Any] | None = None,
        inventory_deadline: float | None = None,
    ) -> Iterable[tuple[Path, os.stat_result]]:
        def incomplete(reason: str, path: Path | None = None) -> None:
            _record_security_inventory_issue(inventory_status, base, reason, path)

        def expired() -> bool:
            if inventory_deadline is not None and time.monotonic() >= inventory_deadline:
                incomplete("time_limit")
                return True
            return False

        base = self._root(root)
        def safe(path: Path) -> bool:
            if self._inventory_path_safe(base, path):
                return True
            if inventory_status is not None:
                try:
                    intentional_link = self._inventory_path_has_link(base, path)
                    if not intentional_link:
                        incomplete("unavailable_path", path)
                except (OSError, ValueError):
                    incomplete("inventory_error", path)
            return False

        limit = self.max_files if max_files is None else max(0, int(max_files))
        if expired():
            return
        if project_settings is not None:
            yielded = 0
            for path in self._iter_project_search_files(base, project_settings, max_depth):
                if yielded >= limit:
                    break
                yielded += 1
                try:
                    stat = path.stat()
                except OSError:
                    continue
                yield path, stat
            return
        git_files = (
            self._git_files(base, max_files=limit, force=True, inventory_status=inventory_status, deadline=inventory_deadline)
            if inventory_status is not None
            else self._git_files(base, max_files=limit) if max_files is not None else self._git_files(base)
        )
        if git_files is not None:
            if isinstance(git_files, GitFileInventory):
                if not git_files.complete and not (inventory_status is not None and "time_limit" in inventory_status["reasons"]):
                    incomplete("file_limit")
            else:
                incomplete("inventory_coverage_unknown")
            candidates = git_files
        else:
            candidates = []
            visited_realpaths: set[str] = set()
            try:
                visited_realpaths.add(os.path.realpath(base))
            except Exception:
                incomplete("inventory_error")
            def walk_error(error: OSError) -> None:
                error_path = Path(error.filename) if error.filename else None
                if error_path is not None:
                    try:
                        if self._inventory_path_has_link(base, error_path):
                            if inventory_status is not None:
                                inventory_status["excluded_link_paths"] = int(inventory_status.get("excluded_link_paths", 0)) + 1
                            return
                    except (OSError, ValueError):
                        pass
                incomplete("inventory_error", error_path)
            walk_options: dict[str, Any] = {"followlinks": False}
            if inventory_status is not None:
                walk_options["onerror"] = walk_error
            for dirpath, dirnames, filenames in os.walk(base, **walk_options):
                if expired():
                    return
                try:
                    relative_dir = Path(dirpath).relative_to(base)
                except ValueError:
                    incomplete("unavailable_path")
                    relative_dir = Path()
                dirnames[:] = sorted((
                    d for d in dirnames
                    if d.lower() not in self.ignore_dirs
                    and not is_root_archive_path(relative_dir / d)
                ), key=lambda name: (name.casefold(), name))
                try:
                    rel_parts = Path(dirpath).relative_to(base).parts
                    if len(rel_parts) >= max_depth:
                        if dirnames or filenames:
                            incomplete("depth_limit")
                        dirnames.clear()
                        continue
                except ValueError:
                    incomplete("unavailable_path")

                kept_dirnames: list[str] = []
                for d in dirnames:
                    if expired():
                        return
                    subdir = os.path.join(dirpath, d)
                    try:
                        if not safe(Path(subdir)):
                            continue
                        rpath = os.path.realpath(subdir)
                        if rpath in visited_realpaths:
                            continue
                        visited_realpaths.add(rpath)
                        kept_dirnames.append(d)
                    except Exception:
                        incomplete("inventory_error", Path(subdir))
                        continue
                dirnames[:] = kept_dirnames

                for name in sorted(filenames, key=lambda value: (value.casefold(), value)):
                    if expired():
                        return
                    p = Path(dirpath) / name
                    if not safe(p):
                        continue
                    if p.suffix.lower() in self.ignore_extensions:
                        continue
                    if self.extensions and p.suffix.lower() not in self.extensions and p.name.lower() not in self.special_filenames:
                        continue
                    if max_files is not None:
                        try:
                            if p.stat().st_size > self.max_file_bytes:
                                incomplete("oversized_file", p)
                                continue
                        except OSError:
                            incomplete("inventory_error", p)
                            continue
                    candidates.append(p)
                    if len(candidates) >= limit:
                        incomplete("file_limit", p)
                        break
                if len(candidates) >= limit:
                    break
        count = 0
        for path in candidates:
            if expired():
                return
            if count >= limit:
                break
            try:
                relative = path.relative_to(base)
            except ValueError:
                incomplete("unavailable_path", path)
                continue
            # `git ls-files -co --exclude-standard` can return ignored paths from
            # other worktrees; configured exclusions apply to every inventory path.
            if self._is_ignored_relative_path(relative):
                continue
            if not safe(path):
                continue
            try:
                stat = path.stat()
                if stat.st_size > self.max_file_bytes:
                    incomplete("oversized_file", path)
                    continue
            except OSError:
                incomplete("inventory_error", path)
                continue
            count += 1
            yield path, stat

    def _read_snapshot(
        self,
        path: Path,
        *,
        stat: os.stat_result | None = None,
        force: bool = False,
        max_bytes: int | None = None,
    ) -> tuple[str, list[str]]:
        """Cache decoded file content/hash by stat identity across different repo queries."""
        if max_bytes is not None:
            # Re-stat and enforce the bound before cache lookup. Cache misses and
            # identities that need content verification still use a bounded read.
            stat = path.stat()
            if stat.st_size > max_bytes:
                raise FileTooLargeError(f"{path} exceeds {max_bytes} bytes")
        stat_was_supplied = stat is not None
        if stat is None:
            stat = path.stat()
        key = str(path)
        identity, verify_content = self._cache_identity(path, stat)
        allow_cached_lookup = True
        if stat_was_supplied and os.name != "nt":
            with self._snapshot_lock:
                allow_cached_lookup = key in self._snapshots
            if allow_cached_lookup:
                # POSIX identity uses the supplied stat, which can predate this read.
                stat = path.stat()
                identity, verify_content = self._cache_identity(path, stat)
        cached = None
        with self._snapshot_lock:
            item = self._snapshots.get(key) if allow_cached_lookup else None
            if item is not None and item[:4] == identity:
                self._snapshots.move_to_end(key)
                if not verify_content and not force:
                    self.snapshot_hits += 1
                    return item[4], item[5]
                cached = item
        if max_bytes is None:
            raw = path.read_bytes()
        else:
            with path.open("rb") as source:
                raw = source.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise FileTooLargeError(f"{path} exceeds {max_bytes} bytes")
        digest = hashlib.sha256(raw).hexdigest()
        if cached is not None and cached[4] == digest:
            with self._snapshot_lock:
                self.snapshot_verified_rehashes += 1
                current = self._snapshots.get(key)
                if current is not None and current[4] == digest:
                    self._snapshots.move_to_end(key)
                self._hash_only_cache[key] = (*identity, digest, False)
                self._hash_only_cache.move_to_end(key)
                while len(self._hash_only_cache) > self._hash_only_max_entries:
                    self._hash_only_cache.popitem(last=False)
            return cached[4], cached[5]
        lines = raw.decode("utf-8", errors="replace").splitlines()
        size = len(raw)
        with self._snapshot_lock:
            if cached is not None:
                self.snapshot_verified_rehashes += 1
            old = self._snapshots.pop(key, None)
            if old:
                self._snapshot_bytes -= old[6]
            self._snapshots[key] = (*identity, digest, lines, size)
            self._snapshot_bytes += size
            self._hash_only_cache[key] = (*identity, digest, False)
            self._hash_only_cache.move_to_end(key)
            if len(self._hash_only_cache) > self._hash_only_max_entries:
                self._hash_only_cache.popitem(last=False)
            self.snapshot_misses += 1
            while self._snapshots and (len(self._snapshots) > self.snapshot_max_entries or self._snapshot_bytes > self.snapshot_max_bytes):
                _k, evicted = self._snapshots.popitem(last=False)
                self._snapshot_bytes -= evicted[6]
        return digest, lines

